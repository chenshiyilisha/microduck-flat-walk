"""Train `Mjlab-Velocity-Flat-MicroDuck` with a non-zero heading-closed-loop fraction.

Why this exists
---------------
`microduck_velocity_env_cfg.py:643` sets `rel_heading_envs = 0.0`, so during
training **not a single env ever gets a closed-loop heading command**. The later
lines set `ranges.ang_vel_z = (-1.0, 1.0)` and the comment calls that change
"the big change -- it makes turning learnable", but a sampled ang_vel_z is an
*open-loop* command: it is constant for the whole resample window and unrelated
to where the robot actually points. Nothing in training ever asks the policy to
drive a heading error to zero.

Measured consequence (`docs/05-flat-walk.md` §15, three repeats): the walk-it
self reporter walks fine (path_dx 2.3-2.5 m) but the heading does an unbiased
random walk (|drift| median 13-17 deg/s), leaving only 13-21% of the path as
net displacement along the initial heading. `error_vel_yaw` is 1.164 rad/s on
HD1910 vs ANYmal's 0.174 -- about 7x -- while forward velocity was never the
shortfall.

The knob is not missing, it is switched off. Read back off the live cfg object:

    heading_command           = True      (inherited from UniformVelocityCommandCfg)
    heading_control_stiffness = 0.5
    ranges.heading            = (-pi, pi) (already present, not None)
    rel_heading_envs          = 0.0       <-- the only one that is off

Note how misleading plain source grepping is here: `heading_command` never
appears in `microduck_velocity_env_cfg.py` at all, because it is inherited and
then rebuilt through `microduck_mdp.VelocityCommandCommandOnlyCfg(**vars(cmd))`.
Reading the *object* is the only way to know; reading the *file* suggests the
field does not exist.

What `rel_heading_envs > 0` changes mechanically
------------------------------------------------
`mjlab/tasks/velocity/mdp/velocity_command.py`:

    _resample_command():                              # once per 3-8 s window
        heading_target[ids] = U(-pi, pi)
        is_heading_env[ids] = U(0,1) <= rel_heading_envs
    _update_command():                                # EVERY step
        heading_error = wrap_to_pi(heading_target - heading_w)
        vel_command_b[ids, 2] = clip(stiffness * heading_error,
                                     min=ranges.ang_vel_z[0], max=ranges.ang_vel_z[1])

so for a heading env, cmd[2] stops being a sampled constant and becomes a
proportional controller over the heading error, saturated at +-1.0 rad/s.
That is the thing training has never contained.

Cost, stated up front (measured in `probe_heading_loop.py`)
-----------------------------------------------------------
The `rel_*` switches are **independent Bernoulli draws, not a partition**, so a
heading env can also be a forward env. `_resample_command()` sets forward envs
to (vx>=0.3, vy=0, wz=0), but `_update_command()` then rewrites their wz every
step. The expected diluted fraction is `rel_heading_envs * rel_forward_envs`
(e.g. 0.30 * 0.20 = 6% of all envs). The forward bucket also loses its wz=0
for those envs, though vx stays clamped >=0.3, so its anti-low-speed role
survives. Standing envs are zeroed at the END of `_update_command()`, so they
are unaffected. Turn-in-place envs keep their large |wz| only until heading
overrides it -- which turns them into "slew to a target and settle", arguably
richer turning supervision than a constant spin.

Making the two mutually exclusive would require editing `mdp.py`, which is out
of bounds (`check_velocity_ready.py::mdp_patch_contained` allows only
joy/NaN/warm-start additions). So the overlap is accepted and recorded rather
than hidden.

Evaluation is unaffected
------------------------
`tools/flat_walk/eval_velocity_in_sim.py` reflectively zeroes every `rel_*`
knob and additionally sets `ranges.heading = (0.0, 0.0)`, so its readings stay
command-following and comparable across variants. The observation/action
contract (obs 61 / act 14 / 50 Hz) does not change either: the actor still sees
a 3-vector `vel_command_b`; only the process that fills slot 2 differs during
training. Exported ONNX therefore remains drop-in.

Usage
-----
    # control (reproduces today's open-loop heading); also what a forgotten flag gives
    .venv-mjlab/Scripts/python.exe tools/train_heading_variant.py \\
        --env.scene.num-envs 4096 --agent.max-iterations 2000 \\
        --agent.run-name head_ctrl

    # variant
    .venv-mjlab/Scripts/python.exe tools/train_heading_variant.py \\
        --rel-heading-envs 0.30 \\
        --env.scene.num-envs 4096 --agent.max-iterations 2000 \\
        --agent.logger tensorboard --agent.experiment-name microduck_velocity \\
        --agent.run-name head_030

    # inspect only
    .venv-mjlab/Scripts/python.exe tools/train_heading_variant.py \\
        --rel-heading-envs 0.30 --dry-run

NOTE -- always pass `--agent.logger tensorboard`
----------------------------------------------
The default logger is broken in this venv: `rsl_rl/utils/wandb_utils.py:46`
constructs `wandb.Settings(start_method="thread")`, and the installed wandb
rejects that key as `extra_forbidden`. Training dies AFTER `device=cuda:0` and
the BamActuator banner, so it looks like a plant problem but is not. Every run
must pass `--agent.logger tensorboard` explicitly; `tools/train_velocity.sh:243`
does the same for the same reason.

Picking a value for --rel-heading-envs
--------------------------------------
Deliberately left with no default other than the cfg's 0.0 (control). mjlab's
*generic* default is 0.3 (`velocity_env_cfg.py:182`) and silently inheriting it
into this task has bitten before.

**Sweep recommendation (2026-10-30, CPU probe `probe_heading_loop.py`):**

| `rel_heading_envs` | heading envs (16-env probe) | training-time overlap | probe |
|---|---|---|---|
| 0.15 | 2 (12.5%) | 3% (0.15×0.2) | 8/8 PASS |
| 0.30 | 6 (37.5%) | 6% (0.30×0.2) | 8/8 PASS |
| 0.50 | 8 (50%) | 10% (0.50×0.2) | 8/8 PASS |

All three pass at machine precision (formula err = 0.000e+00, sign agree = 1.0).
The overlap cost scales linearly with the knob: at 0.15 it costs 3% of envs, at
0.50 it costs 10%. Upstream's own rule (AGENTS.md:186) is that rare-but-important
command regions need an explicit bucket, which is why `rel_turn_in_place_envs`
exists at 0.15. **Recommendation: start with 0.30** — it matches mjlab's generic
default (so the comparison against upstream is clean), gives ~37% of envs a
closed-loop heading target, and the 6% overlap is manageable. If the yaw error
does not drop enough, escalate to 0.50. If training diverges, drop to 0.15.

The overlap at training time uses the real `rel_forward_envs=0.2` (read off the
live cfg), not the probe's exaggerated 0.5.

Second knob: `--pin-action-rate` (added 2026-11-02)
---------------------------------------------------
The reward panel of `p3head030` (iter 1999, per-step weighted means) shows
`Episode_Reward/action_rate_l2 = -1.525` against
`Episode_Reward/track_linear_velocity = +0.910`: **the smoothing penalty is 1.67x
the entire forward-tracking reward**, and it is the only term the recipe
deliberately tightens (stage table -0.1 -> -0.2@500 -> -0.4@750 -> -0.6@1000 ->
-0.8@1250 -> -1.0@1500, `microduck_velocity_env_cfg.py:778-795`, byte-identical
to upstream -- not a local patch).

That run's commanded-vs-measured slope is `vx = 0.28*cmd + 0.025` (ratio 0.30),
against XL330's `0.659*cmd - 0.018`, and the ratio does not improve from iter
1000 to iter 1999 even though the fall rate drops 21.5% -> 0-2%. The last 1000
iterations bought stability, not speed.

But the causal claim "relaxing the penalty buys speed" is NOT established by that
run: at iter 400 the weight was already at its loosest working value (-0.1) and
`error_vel_xy` was 0.353, the same order as the 0.467 at weight -1.0. The ramp and
the curriculum's expanding command ranges move together, so the two variables
cannot be separated from one run. `--pin-action-rate` runs the separation:
replace the stage table with a single stage so the weight is constant from step 0,
identical in every other respect.

This is deliberately a **single-variable** change against `p3head030`: same plant
(hd1910_kp5), same `rel_heading_envs`, same env count/iterations/seed, only the
action-rate schedule differs. Read the effective table back off the live cfg
before launching -- a declared pin that did not take is the exact failure mode
this project keeps hitting.

Note `reward_weight` (mdp.py:3584-3603) mutates `env.reward_manager.get_term_cfg()`
at runtime, so **two** places carry the weight: the curriculum stage table and
`cfg.rewards[...].weight` (the pre-first-step value, set at line 349). Both are
written here, otherwise step 0 would still use -0.1.

Caveat on reading the result: `action_rate_l2` is ~89% exploration-noise floor
(-25*sigma^2, R^2=0.98, measured on the joy task by
`tools/patch_joy_action_rate.py`), so a looser weight partly just permits larger
`sigma`. Compare `feet`/`air_time`/`vx`, not reward totals.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import mjlab
import mjlab.tasks  # noqa: F401  (populates the task registry)
import tyro

DEFAULT_TASK = "Mjlab-Velocity-Flat-MicroDuck"

# Fields this script is allowed to touch on cfg.commands["twist"]. Kept explicit:
# "everything that looks like a heading knob" is not the same set as "everything
# whose value we have derived from evidence".
HEADING_KNOBS = ("rel_heading_envs", "heading_control_stiffness", "rel_forward_envs")


def _sha16(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError as e:  # noqa: BLE001
        return f"<unreadable: {type(e).__name__}>"


def _check_fraction(name: str, value: float) -> None:
    """Guard the `rel_*` knobs, which are probabilities, not arbitrary weights."""
    if not (0.0 <= value <= 1.0):
        raise SystemExit(
            f"{name} must be within 0.0..1.0 (got {value}). It is a per-env "
            "selection probability compared against a U(0,1) draw, so anything "
            "outside that range silently degenerates to 'never' or 'always'."
        )


def read_heading_state(cfg) -> dict[str, Any]:
    """Read the heading-relevant fields off the LIVE cfg object.

    Same reasoning as `train_velocity.py`'s reward readback: a declared override
    is not evidence that tyro resolved it, and here even reading the source file
    is not evidence -- `heading_command` is invisible in the task source.
    """
    cmd = cfg.commands["twist"]
    ranges = cmd.ranges
    out: dict[str, Any] = {
        "command_class": type(cmd).__name__,
        "heading_command": bool(getattr(cmd, "heading_command", False)),
        "heading_control_stiffness": getattr(cmd, "heading_control_stiffness", None),
        "rel_heading_envs": float(getattr(cmd, "rel_heading_envs", 0.0) or 0.0),
        "rel_forward_envs": float(getattr(cmd, "rel_forward_envs", 0.0) or 0.0),
        "rel_standing_envs": float(getattr(cmd, "rel_standing_envs", 0.0) or 0.0),
        "rel_turn_in_place_envs": float(getattr(cmd, "rel_turn_in_place_envs", 0.0) or 0.0),
        "ranges_ang_vel_z": tuple(float(v) for v in ranges.ang_vel_z),
        "ranges_heading": (
            tuple(float(v) for v in ranges.heading)
            if getattr(ranges, "heading", None) is not None
            else None
        ),
    }
    return out


def find_other_writers(cfg) -> list[dict[str, Any]]:
    """Who else writes `rel_heading_envs` while training runs?

    Frozen-field rule: before relying on a value, ask who else writes it. Three
    separate incidents in this project (standing_envs, rel_forward_envs, the
    plant constants) came from a hidden second writer silently undoing a value.

    The known offender pattern is a curriculum stage table whose decades contain
    the key. Scanned reflectively over EVERY curriculum term and EVERY stage so
    an upstream addition cannot slip through by having a new name.
    """
    hits: list[dict[str, Any]] = []
    for term_name, term in getattr(cfg, "curriculum", {}).items():
        params = getattr(term, "params", None) or {}
        for pname, pval in params.items():
            stages = pval if isinstance(pval, (list, tuple)) else [pval]
            for stage in stages:
                if isinstance(stage, dict) and "rel_heading_envs" in stage:
                    hits.append(
                        {
                            "term": term_name,
                            "param": pname,
                            "stage": {k: v for k, v in stage.items()},
                        }
                    )
    return hits


def find_weight_writers(cfg, reward_name: str) -> list[dict[str, Any]]:
    """Who writes `<reward_name>.weight` while training runs?

    Reflective over every curriculum term, and keyed on the term's own
    `reward_name` param rather than on the term name: an upstream rename of
    `action_rate_weight` would silently defeat a name-matched lookup.
    """
    hits: list[dict[str, Any]] = []
    for term_name, term in getattr(cfg, "curriculum", {}).items():
        params = getattr(term, "params", None) or {}
        if params.get("reward_name") != reward_name:
            continue
        hits.append(
            {
                "term": term_name,
                "key": "weight_stages",
                "stages": [dict(s) for s in params.get("weight_stages", [])],
            }
        )
    return hits


def pin_reward_weight(cfg, reward_name: str, weight: float) -> dict[str, Any]:
    """Collapse a staged reward-weight curriculum into one constant.

    Both carriers are written (see module docstring): the stage table, and the
    `cfg.rewards[...].weight` that seeds the reward manager before the first
    curriculum tick. Leaving the second at its shipped value would make step 0
    the one step that disagrees with the declared pin.
    """
    if weight > 0.0:
        raise SystemExit(
            f"refusing a positive {reward_name} weight ({weight}): it is a "
            "penalty, so a positive value would reward large actions."
        )
    writers = find_weight_writers(cfg, reward_name)
    if len(writers) != 1:
        raise SystemExit(
            f"expected exactly one curriculum writer of {reward_name}.weight, "
            f"found {len(writers)}: {writers}. Pinning would leave a second "
            "writer free to undo it."
        )
    term_name = writers[0]["term"]
    term = cfg.curriculum[term_name]
    before = [dict(s) for s in term.params["weight_stages"]]
    seed_before = cfg.rewards[reward_name].weight

    term.params["weight_stages"] = [{"step": 0, "weight": weight}]
    cfg.rewards[reward_name].weight = weight

    return {
        "reward_name": reward_name,
        "term": term_name,
        "seed_weight_before": seed_before,
        "seed_weight_after": cfg.rewards[reward_name].weight,
        "stages_before": before,
        "stages_after": [dict(s) for s in term.params["weight_stages"]],
        "requested": weight,
    }


def read_pin_state(cfg, reward_name: str) -> dict[str, Any]:
    """Read the effective weight carriers back off the live cfg."""
    writers = find_weight_writers(cfg, reward_name)
    term = cfg.curriculum[writers[0]["term"]] if len(writers) == 1 else None
    return {
        "seed_weight": cfg.rewards[reward_name].weight,
        "stage_table": (
            [dict(s) for s in term.params["weight_stages"]] if term is not None else None
        ),
        "n_writers": len(writers),
    }


def add_heading_reward_curriculum(
    cfg,
    *,
    hold_weight: float,
    tracking_weight: float,
    ang_vel_z: float,
    stage_iters: tuple[int, int, int, int],
    num_steps_per_env: int = 24,
) -> dict[str, Any]:
    """Port upstream's reward-side heading recipe onto this task.

    Where this comes from (all upstream, not invented here):

      * `mjlab_microduck/tasks/mdp.py::heading_hold_reward` — rewards the yaw
        ANGLE staying at the spawn heading, `exp(-wrap(yaw-yaw_spawn)^2/std^2)`,
        std=0.4. Its docstring states the reason a yaw-RATE penalty is the wrong
        tool: "it just tells the policy 'never turn' -> it can't steer back and
        drifts open-loop". An angle-based reward lets the policy yaw back.
      * `mjlab_microduck/tasks/mdp.py::heading_tracking_reward` — rewards the
        commanded heading error (`cmd[:, 2]`) being near zero,
        `exp(-cmd[2]^2/std^2)`, std=0.5.
      * `microduck_velocity_swizzle_env_cfg.py:66-107` — the two-phase
        curriculum and the narrowed `ang_vel_z`: straight first
        (`heading_hold` dominant, `heading_tracking`=0), then follow
        (`heading_hold`->0, `heading_tracking`->3.0). Its comment on narrowing
        `ang_vel_z` from +-1.0 to +-0.5 is why the deployment rehearsal
        oscillated at gain 0.5: "a +-1.0-trained policy turned too violently".

    Our velocity task ships NEITHER reward term (verified by grepping
    `cfg.rewards[...]` in `microduck_velocity_env_cfg.py`), which is the actual
    gap: `rel_heading_envs=0.3` only feeds a heading error into cmd[2]; nothing
    ever rewards driving that error to zero.

    `stage_iters` are ITERATIONS, converted here into `common_step_counter`
    steps with the agent's `num_steps_per_env` (24) — upstream writes its stages
    directly as `iteration * 24`, so this keeps the same unit rather than
    silently mixing them.
    """
    from mjlab.managers import CurriculumTermCfg, RewardTermCfg

    from mjlab_microduck.tasks import mdp as microduck_mdp

    if hold_weight <= 0.0:
        raise SystemExit(f"hold_weight must be > 0 (got {hold_weight})")
    if tracking_weight <= 0.0:
        raise SystemExit(f"tracking_weight must be > 0 (got {tracking_weight})")
    if ang_vel_z <= 0.0:
        raise SystemExit(f"ang_vel_z must be > 0 (got {ang_vel_z}); it is the clip bound")

    for name in ("heading_hold", "heading_tracking"):
        if name in cfg.rewards:
            raise SystemExit(
                f"cfg.rewards already contains {name!r}; refusing to double-add "
                "(a silent overwrite would make the readback below meaningless)."
            )
    for name in ("heading_hold_weight", "heading_tracking_weight"):
        if name in cfg.curriculum:
            raise SystemExit(f"cfg.curriculum already contains {name!r}")

    n = int(num_steps_per_env or 24)
    if n <= 0:
        raise SystemExit(f"num_steps_per_env must be > 0 (got {n})")

    cfg.rewards["heading_hold"] = RewardTermCfg(
        func=microduck_mdp.heading_hold_reward,
        weight=float(hold_weight),
        params={"std": 0.4},
    )
    cfg.rewards["heading_tracking"] = RewardTermCfg(
        func=microduck_mdp.heading_tracking_reward,
        weight=0.0,                       # must match the stage table's step-0 value
        params={"command_name": "twist", "std": 0.5},
    )

    marks = [int(i) * n for i in stage_iters]
    cfg.curriculum["heading_hold_weight"] = CurriculumTermCfg(
        func=microduck_mdp.reward_weight,
        params={
            "reward_name": "heading_hold",
            "weight_stages": [
                {"step": marks[0], "weight": float(hold_weight)},
                {"step": marks[1], "weight": float(hold_weight)},
                {"step": marks[2], "weight": float(hold_weight) * 0.5},
                {"step": marks[3], "weight": 0.0},
            ],
        },
    )
    cfg.curriculum["heading_tracking_weight"] = CurriculumTermCfg(
        func=microduck_mdp.reward_weight,
        params={
            "reward_name": "heading_tracking",
            "weight_stages": [
                {"step": marks[0], "weight": 0.0},
                {"step": marks[1], "weight": 0.0},
                {"step": marks[2], "weight": float(tracking_weight) * 0.5},
                {"step": marks[3], "weight": float(tracking_weight)},
            ],
        },
    )

    # Narrowing the clip bound also bounds the OBSERVED heading error, which is
    # what tames the turn rate (upstream's comment, see docstring).
    cfg.commands["twist"].ranges.ang_vel_z = (-float(ang_vel_z), float(ang_vel_z))

    return read_heading_reward_state(cfg)


def read_heading_reward_state(cfg) -> dict[str, Any]:
    """Read the added rewards + curricula back off the live cfg object."""
    out: dict[str, Any] = {}
    for name in ("heading_hold", "heading_tracking"):
        term = cfg.rewards.get(name)
        out[name] = (
            None
            if term is None
            else {
                "weight": float(term.weight),
                "params": dict(term.params),
                "func": getattr(term.func, "__name__", str(term.func)),
            }
        )
    for name in ("heading_hold_weight", "heading_tracking_weight"):
        term = cfg.curriculum.get(name)
        out[name] = (
            None
            if term is None
            else [dict(s) for s in term.params.get("weight_stages", [])]
        )
    out["ranges_ang_vel_z"] = tuple(float(v) for v in cfg.commands["twist"].ranges.ang_vel_z)
    return out


def plant_fingerprint() -> dict[str, Any]:
    """Record which robot this variant is declared against.

    Heading data gathered on the old m5/kp32 plant is not comparable with data
    gathered on hd1910_kp5 (see docs/05-flat-walk.md §13/§16). This is a
    read-only call; it never switches the live plant.
    """
    try:
        import sys

        here = Path(__file__).resolve().parent
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
        from plant_id import fingerprint  # noqa: PLC0415

        return fingerprint()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def main() -> int:
    import argparse

    # Peel the custom flags off before tyro sees argv, exactly like
    # train_velocity_variant.py: tyro is configured for TrainConfig and rejects
    # unknown flags outright.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--rel-heading-envs", type=float, default=None)
    pre.add_argument("--heading-stiffness", type=float, default=None)
    pre.add_argument("--rel-forward-envs", type=float, default=None)
    pre.add_argument("--pin-action-rate", type=float, default=None)
    pre.add_argument("--heading-hold-weight", type=float, default=None,
                     help="add upstream's heading_hold reward at this initial weight "
                          "(std 0.4). Needs --heading-tracking-final-weight too.")
    pre.add_argument("--heading-tracking-final-weight", type=float, default=None,
                     help="add heading_tracking reward (std 0.5), ramped to this weight.")
    pre.add_argument("--ang-vel-z-clip", type=float, default=None,
                     help="set ranges.ang_vel_z = (-x, +x). Bounds the observed heading "
                          "error, which is what tames the turn rate (upstream: 0.5).")
    pre.add_argument("--heading-stage-iters", default="0,1000,1750,2500",
                     help="four iteration marks for the two-phase heading curriculum "
                          "(upstream's swizzle uses 0/1000/1750/2500).")
    pre.add_argument("--resume-offset", type=int, default=None,
                     help="absolute iterations already completed before this launch "
                          "(a resumed run). The heading curriculum is compared against "
                          "env.common_step_counter, which MjlabOnPolicyRunner.load "
                          "restores from the checkpoint, so stage marks stay ABSOLUTE "
                          "while --agent.max-iterations is an INCREMENT on resume. "
                          "Set this to the checkpoint's iter or the two disagree.")
    pre.add_argument("--task", default=DEFAULT_TASK)
    pre.add_argument("--dry-run", action="store_true")
    known, passthrough = pre.parse_known_args()

    from mjlab.scripts.train import TrainConfig, launch_training

    if "--help" in passthrough or "-h" in passthrough:
        import sys

        tyro.cli(
            TrainConfig,
            args=["--help"],
            default=TrainConfig.from_task(known.task),
            config=mjlab.TYRO_FLAGS,
        )
        return 0

    args = tyro.cli(
        TrainConfig,
        args=passthrough,
        default=TrainConfig.from_task(known.task),
        config=mjlab.TYRO_FLAGS,
    )

    cmd = args.env.commands["twist"]
    before = read_heading_state(args.env)

    # Declarative only: --resume-offset feeds this script's stage validation, it does
    # NOT reach the trainer. The real curriculum state comes from env.common_step_counter,
    # which MjlabOnPolicyRunner.load restores out of infos["env_state"]. Requiring it
    # alongside --agent.resume just keeps the validation honest -- a resume with
    # offset 0 (or a wrong one) makes the stage-bound check compare against the wrong
    # end point and can wave a bad schedule through.
    resume_offset = 0 if known.resume_offset is None else int(known.resume_offset)
    if resume_offset < 0:
        raise SystemExit(f"--resume-offset must be >= 0 (got {resume_offset})")
    if getattr(args.agent, "resume", False) and known.resume_offset is None:
        raise SystemExit(
            "--agent.resume is set but --resume-offset was not given. Pass the "
            "checkpoint's iteration as --resume-offset so the heading stage check uses "
            "the run's absolute end point (rsl_rl adds max_iterations to the loaded "
            "iteration). Explicit 0 is accepted, for a checkpoint at iteration 0."
        )

    if not before["heading_command"]:
        raise SystemExit(
            "heading_command is False on the live cfg -- enabling rel_heading_envs "
            "would silently do nothing (velocity_command.py:80 gates on it)."
        )
    if before["ranges_heading"] is None:
        raise SystemExit(
            "ranges.heading is None while heading_command is True -- the command "
            "class refuses to build in this combination."
        )

    writers = find_other_writers(args.env)
    if writers:
        raise SystemExit(
            "another term rewrites rel_heading_envs mid-training; this script "
            f"cannot keep its declared value: {writers}"
        )

    requested: dict[str, float] = {}
    if known.rel_heading_envs is not None:
        # Fraction of envs, i.e. a probability. caught here rather than letting
        # `U(0,1) <= 1.5` quietly evaluate to "all envs" and look like a valid run.
        _check_fraction("rel_heading_envs", known.rel_heading_envs)
        requested["rel_heading_envs"] = known.rel_heading_envs
        cmd.rel_heading_envs = known.rel_heading_envs
    if known.heading_stiffness is not None:
        if known.heading_stiffness <= 0.0:
            raise SystemExit(
                f"heading_stiffness must be > 0 (got {known.heading_stiffness}); "
                "0 would make cmd[2] identically zero for every heading env and "
                "non-positive would invert the correction."
            )
        requested["heading_control_stiffness"] = known.heading_stiffness
        cmd.heading_control_stiffness = known.heading_stiffness
    if known.rel_forward_envs is not None:
        _check_fraction("rel_forward_envs", known.rel_forward_envs)
        requested["rel_forward_envs"] = known.rel_forward_envs
        cmd.rel_forward_envs = known.rel_forward_envs

    # Reward-side heading recipe (upstream's, see add_heading_reward_curriculum).
    # Runs before `after = read_heading_state(...)` so the ang_vel_z readback
    # below sees the narrowed range rather than the shipped +-1.0.
    heading_rewards: dict[str, Any] | None = None
    if (known.heading_hold_weight is None) != (known.heading_tracking_final_weight is None):
        raise SystemExit(
            "--heading-hold-weight and --heading-tracking-final-weight must be "
            "given together: hold alone teaches 'never turn', tracking alone has "
            "no incentive to stay on a heading."
        )
    if known.heading_hold_weight is not None:
        if known.ang_vel_z_clip is None:
            raise SystemExit(
                "--ang-vel-z-clip is required with the heading rewards. The shipped "
                "+-1.0 is what made the deployment loop oscillate; upstream narrows "
                "it to 0.5 for exactly this recipe."
            )
        if known.ang_vel_z_clip <= 0.0:
            raise SystemExit(f"--ang-vel-z-clip must be > 0 (got {known.ang_vel_z_clip})")
        try:
            stage_iters = tuple(int(x) for x in known.heading_stage_iters.split(","))
        except ValueError:
            raise SystemExit(
                f"--heading-stage-iters must be four comma-separated ints, got "
                f"{known.heading_stage_iters!r}"
            ) from None
        if len(stage_iters) != 4:
            raise SystemExit(
                f"--heading-stage-iters needs exactly 4 marks, got {len(stage_iters)}"
            )
        if list(stage_iters) != sorted(stage_iters):
            raise SystemExit(f"--heading-stage-iters must be non-decreasing: {stage_iters}")
        if stage_iters[0] != 0:
            raise SystemExit(f"the first stage must start at iteration 0: {stage_iters}")
        # Stage marks are absolute iteration numbers because the curriculum reads
        # env.common_step_counter, which a resume restores from the checkpoint.
        # --agent.max-iterations, however, is what rsl_rl adds to the loaded
        # iteration (learn(): total_it = start_it + num_learning_iterations), so on
        # a resumed launch it is an INCREMENT. Comparing the two without the offset
        # rejects every resume out of hand -- and worse, silently accepting a
        # mismatched pair would run the tracking phase at the wrong time.
        absolute_total = resume_offset + int(args.agent.max_iterations)
        if stage_iters[3] > absolute_total:
            raise SystemExit(
                f"the last heading stage ({stage_iters[3]}) is past the absolute end of "
                f"this run ({absolute_total} = resume_offset {resume_offset} + "
                f"max_iterations {args.agent.max_iterations}); the run would end "
                "before the tracking phase starts."
            )
        heading_rewards = add_heading_reward_curriculum(
            args.env,
            hold_weight=known.heading_hold_weight,
            tracking_weight=known.heading_tracking_final_weight,
            ang_vel_z=known.ang_vel_z_clip,
            stage_iters=stage_iters,
            num_steps_per_env=int(getattr(args.agent, "num_steps_per_env", 24)),
        )
        # A declared value that did not take is this project's recurring failure
        # mode, so compare the readback against what was asked.
        if heading_rewards["heading_hold"]["weight"] != known.heading_hold_weight:
            raise SystemExit(f"heading_hold weight did not take: {heading_rewards['heading_hold']}")
        if heading_rewards["heading_tracking"]["weight"] != 0.0:
            raise SystemExit(
                f"heading_tracking must start at 0 (the curriculum ramps it): "
                f"{heading_rewards['heading_tracking']}"
            )
        want_clip = (-known.ang_vel_z_clip, known.ang_vel_z_clip)
        if heading_rewards["ranges_ang_vel_z"] != want_clip:
            raise SystemExit(
                f"ang_vel_z clip did not take: requested {want_clip}, "
                f"effective {heading_rewards['ranges_ang_vel_z']}"
            )

    after = read_heading_state(args.env)

    # Reward-weight pin (opt-in). Done after the heading knobs so the readback
    # below covers both, and pinned *before* any launch so a mismatch exits here
    # rather than 2 hours into a GPU run.
    pin: dict[str, Any] | None = None
    pin_after: dict[str, Any] | None = None
    if known.pin_action_rate is not None:
        pin = pin_reward_weight(args.env, "action_rate_l2", known.pin_action_rate)
        pin_after = read_pin_state(args.env, "action_rate_l2")
        got_seed = float(pin_after["seed_weight"])
        table = pin_after["stage_table"] or []
        if abs(got_seed - known.pin_action_rate) > 1e-9:
            raise SystemExit(
                f"pin did not take on cfg.rewards['action_rate_l2'].weight: "
                f"requested {known.pin_action_rate}, effective {got_seed}"
            )
        if len(table) != 1 or abs(float(table[0]["weight"]) - known.pin_action_rate) > 1e-9:
            raise SystemExit(
                f"pin did not take on the stage table: requested a single stage at "
                f"{known.pin_action_rate}, effective {table}"
            )

    # A declared override that did not take is the whole class of bug this
    # script exists to avoid; compare against what was asked, not against the
    # previous value.
    failed: dict[str, dict[str, Any]] = {}
    for k, want in requested.items():
        got = after[k]
        try:
            ok = abs(float(got) - float(want)) <= 1e-9
        except (TypeError, ValueError):
            ok = got == want
        if not ok:
            failed[k] = {"requested": want, "effective": got}
    if failed:
        raise SystemExit(f"override did not take effect: {failed}")

    rh = after["rel_heading_envs"]
    rf = after["rel_forward_envs"]
    stiff = after["heading_control_stiffness"]
    lo, hi = after["ranges_ang_vel_z"]
    # Saturation point of cmd[2] = clip(stiffness * wrapped_error, +-max).
    sat_err = (max(abs(lo), abs(hi)) / stiff) if stiff else float("nan")

    live = (
        Path(__file__).resolve().parents[1]
        / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks"
    )
    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "run": args.agent.run_name,
        "task": known.task,
        "variant": {
            "requested": requested or None,
            "rel_heading_envs": rh,
            "heading_control_stiffness": stiff,
            "rel_forward_envs": rf,
            # Independent Bernoulli draws, so this overlap is expected.
            "expected_heading_x_forward_overlap": rh * rf,
            # |error| beyond this saturates cmd[2] at the ang_vel_z bound.
            "saturation_heading_error_rad": sat_err,
            "saturation_heading_error_deg": (sat_err * 180.0 / 3.141592653589793),
        },
        "command_before": before,
        "command_after": after,
        "other_rel_heading_writers": writers or None,
        "heading_rewards": heading_rewards,
        "heading_stage_iters": (
            list(stage_iters) if known.heading_hold_weight is not None else None
        ),
        "action_rate_pin": pin,
        "action_rate_effective": pin_after,
        "plant": plant_fingerprint(),
        "envs": int(args.env.scene.num_envs),
        "iters": int(args.agent.max_iterations),
        "resume_offset": resume_offset,
        "iters_absolute": resume_offset + int(args.agent.max_iterations),
        # These files are NOT modified by this script; hashes let a future reader
        # tell an unmodified install from a patched one.
        "cfg_sha256_16": _sha16(live / "microduck_velocity_env_cfg.py"),
        "mdp_sha256_16": _sha16(live / "mdp.py"),
        "passthrough_args": passthrough,
    }

    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    name = args.agent.run_name or datetime.now().strftime("%m%d_%H%M%S")
    meta_path = out_dir / f"heading_meta_{name}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if requested:
        print(f"rel_heading_envs {before['rel_heading_envs']} -> {rh}")
        print(f"  expected heading x forward overlap = {rh * rf:.4f}")
        if rf > 0:
            print(f"  forward vz=0 survives on {1.0 - rh:.1%} of forward envs; "
                  f"vx stays clamped >= 0.3 on all of them")
        print(f"  cmd[2] saturates beyond {sat_err:.3f} rad heading error")
    else:
        print("control run: heading knobs left exactly as the cfg ships")
    if heading_rewards is not None:
        print("heading rewards ADDED (upstream recipe):")
        for name in ("heading_hold", "heading_tracking"):
            t = heading_rewards[name]
            print(f"  {name}: {t['func']} weight={t['weight']:.3f} params={t['params']}")
        for name in ("heading_hold_weight", "heading_tracking_weight"):
            stages = ", ".join(f"{s['weight']}@{s['step']}" for s in heading_rewards[name])
            print(f"  curriculum {name}: {stages}  (step = iter x num_steps_per_env)")
        print(f"  ang_vel_z narrowed to {heading_rewards['ranges_ang_vel_z']}")
    if pin is not None:
        n_before = len(pin["stages_before"])
        ramp = ", ".join(f"{s['weight']}@{s['step']}" for s in pin["stages_before"])
        print(
            f"action_rate_l2 weight: seed {pin['seed_weight_before']} -> "
            f"{pin['seed_weight_after']}, stages {n_before} -> 1"
        )
        print(f"  replaced ramp: {ramp}")
        # Machine-checked by tools/hd1910/explore_heading.sh; keep the format.
        print(f"pin action_rate_l2 weight: {pin_after['seed_weight']}")
    print(f"heading meta -> {meta_path}")

    if known.dry_run:
        print("--dry-run: resolved and recorded, not launching training")
        return 0

    launch_training(task_id=known.task, args=args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
