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

    after = read_heading_state(args.env)

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
        "plant": plant_fingerprint(),
        "envs": int(args.env.scene.num_envs),
        "iters": int(args.agent.max_iterations),
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
    print(f"heading meta -> {meta_path}")

    if known.dry_run:
        print("--dry-run: resolved and recorded, not launching training")
        return 0

    launch_training(task_id=known.task, args=args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
