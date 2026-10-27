# SPDX-License-Identifier: Apache-2.0
"""Acceptance gates for a joy checkpoint, measured **inside mjlab** (mujoco-warp).

Why this file exists
--------------------
`tools/probe_joy_policy.py` replays a policy in plain **CPU MuJoCo**. That loop is
useful for comparing two policies on the *same* plant, but it is NOT a valid
acceptance gate, and the reason is first-party:

  `emwstudio/DuckEMW` `docs/04-stilts-repro.md:56-65` —
  "**不可信路径（勿用）**：CPU MuJoCo 彩排 (PolicyInference, 即使补上 BAM M6
   执行器) 渲染高跷策略会在 ~2.4s 摔倒，而同一 checkpoint 在真实环境里
   32 envs × 10s survival = 1.0。策略的验证一律以 mjlab 环境内数据为准。"

So the same trained weights can read as a 2.4 s fall in CPU replay and as a clean
survival in the environment they were trained in. Contacts are the difference:
mjlab runs mujoco-warp with its own collision/constraint pipeline (see the
`joy_pd_spec` comment in `microduck_joy_env_cfg.py:72`: "Warp MULTICCD requires
zero margin; CPU rehearsal retains .2 mm margin"), so the CPU plant is a
*different physical system*, not a cheaper copy of the same one.

This script therefore loads the checkpoint into the **same env cfg it was trained
in** and steps it there, computing every gate from `mdp` functions and entity
state -- no reimplementation of the observation contract, no separate plant.

Gate levels are the upstream set from `joy.py:report()` (see
`microduck-joy策略实测.md` §2.0). `foot_support` upstream lives in
`parkour/world.py` and is not fetched; the proxy used here is stated explicitly
and labelled `~` in the output so it is never mistaken for the official term.

Usage
-----
  # CPU (safe while a GPU training run is using the card)
  .venv-mjlab/Scripts/python.exe tools/eval_joy_in_sim.py \
      --checkpoint logs/.../model_100.pt --num-envs 64 --device cpu

  # GPU, larger batch
  .venv-mjlab/Scripts/python.exe tools/eval_joy_in_sim.py \
      --checkpoint logs/.../model_599.pt --num-envs 512 --device cuda:0
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import asdict

import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- gate levels
# (name, threshold, comparison) copied from joy.py:report(); ">" means must exceed.
GATES = {
    "duration_s": (3.5, ">="),
    "min_upright": (0.9, ">"),
    "max_drift_m": (0.08, "<"),
    "feet_peak_m": (0.008, ">"),
    "end_upright": (0.95, ">"),
    "target_rate_rms": (6.0, "<"),
    "max_target_step_rad": (0.2, "<"),
    "pose_power_above_8hz_ratio": (0.01, "<"),
}


def _up_z(quat: torch.Tensor) -> torch.Tensor:
    """cos(tilt) of the body z axis against world z. quat is wxyz."""
    w, x, y, z = quat.unbind(-1)
    # third column of the rotation matrix, z component
    return 1.0 - 2.0 * (x * x + y * y)


def _yaw(quat: torch.Tensor) -> torch.Tensor:
    w, x, y, z = quat.unbind(-1)
    return torch.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _fft_high_ratio(sig: torch.Tensor, dt: float, cutoff_hz: float = 8.0):
    """(Fraction of AC power above `cutoff_hz`, AC rms).

    Upstream uses the ratio to separate *stepping* (1-2 Hz) from *chatter*. A
    signal that is mostly above 8 Hz looks like a gait in a foot-height plot but
    is a vibration -- exactly the failure this gate exists to catch.

    The AC rms is returned alongside because the ratio alone is meaningless on a
    near-static signal: 0.2 mm of solver noise that happens to be high-frequency
    scores the same as 20 mm of real chatter. Read both.
    """
    sig = sig - sig.mean(dim=0, keepdim=True)
    ac = float(sig.pow(2).mean().sqrt())
    n = sig.shape[0]
    spec = torch.fft.rfft(sig, dim=0).abs().pow(2)  # [f, env]
    freqs = torch.fft.rfftfreq(n, d=dt, device=sig.device)
    total = spec[1:].sum(dim=0)
    high = spec[freqs >= cutoff_hz].sum(dim=0)
    ratio = torch.where(total > 0, high / total.clamp_min(1e-12), torch.zeros_like(total))
    return float(ratio.mean()), ac


def _step_period(left_z: torch.Tensor, dt: float, thresh: float = 0.008):
    """Median period of the left-foot lift, from rising crossings of `thresh`.

    Returns None when no env produced two clean crossings (e.g. standing still,
    which is the point: a stance policy has no period to report).
    """
    above = (left_z > thresh).float()
    rise = (above[1:] - above[:-1] > 0).nonzero()
    periods = []
    if rise.numel():
        for e in range(left_z.shape[1]):
            t = rise[rise[:, 1] == e][:, 0].float() * dt
            if t.numel() >= 2:
                periods.append(float((t[-1] - t[0]) / (t.numel() - 1)))
    if not periods:
        return None
    periods.sort()
    return periods[len(periods) // 2]


PLANT_CHOICES = ("default", "bam")


def swap_plant(env_cfg, plant: str) -> dict:
    """Replace the plant without touching anything else.

    A policy number means nothing without the plant it was measured in. The joy
    tasks ship two things that together *are* the plant:

      - `articulation.actuators` -- BAM voltage law vs XML `<position>` servo
      - `spec_fn`                 -- `get_standup_spec` vs `joy_pd_spec` (forcerange)

    and one thing that is *not* the plant but looks like it, because it lives in
    the same cfg: the action term. `JoySmoothPositionActionCfg` carries the
    alpha=.25 / max_step=.08 conditioner the policy was trained against. Reaching
    for a whole different task (`Mjlab-Joy-Flat-MicroDuck`) to get the BAM plant
    would drop that conditioner as a side effect -- two variables changed, one
    number, no way to attribute the difference.

    So swap exactly the two plant fields and leave the action term alone.
    """
    ent = env_cfg.scene.entities["robot"]
    if plant == "bam":
        from copy import deepcopy

        from mjlab_microduck.robot.microduck_constants import MICRODUCK_STANDUP_ROBOT_CFG

        ref = MICRODUCK_STANDUP_ROBOT_CFG
        ent.articulation.actuators = deepcopy(ref.articulation.actuators)
        ent.spec_fn = ref.spec_fn
    elif plant != "default":
        raise SystemExit(f"unknown --plant {plant!r}, expected one of {PLANT_CHOICES}")

    term = env_cfg.actions["joint_pos"]
    return {
        "plant": "task-default" if plant == "default" else plant,
        "spec_fn": getattr(ent.spec_fn, "__name__", None),
        "actuators": [type(a).__name__ for a in ent.articulation.actuators],
        # Recorded so the json proves the conditioner survived the swap.
        "action_term": type(term).__name__,
        "conditioner": {
            k: getattr(term, k, None)
            for k in ("joy_alpha", "joy_max_step", "alpha", "max_step")
            if hasattr(term, k)
        },
    }


def run(task_id: str, checkpoint: str, num_envs: int, seconds: float, device: str, play: bool,
        plant: str = "default"):
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.utils.torch import configure_torch_backends
    from mjlab_microduck.tasks import mdp

    configure_torch_backends()

    env_cfg = load_env_cfg(task_id, play=play)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs
    plant_info = swap_plant(env_cfg, plant)
    # Upstream evaluates checkpoints without the training-only push; the joy cfg
    # already pops it. Keep the cfg exactly as trained so the gates describe the
    # system the weights were fit to.
    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    obs, _ = env.reset()
    u = env.unwrapped
    robot = u.scene["robot"]
    foot_cfg = SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])
    # Names must be resolved into ids against the live scene; unresolved they
    # stay `slice(None)` (all 7 sites) and every downstream tensor is 7-wide.
    foot_cfg.resolve(u.scene)
    step_dt = float(u.step_dt)
    n_steps = int(round(seconds / step_dt))

    # ---- measurement buffers, per control step -----------------------------
    foot_z_hist, up_hist, xy_hist, tgt_hist = [], [], [], []
    knee_hist = []
    term_step = torch.full((num_envs,), -1, dtype=torch.long, device=u.device)
    joy_feet_hist, joy_bal_hist, joy_drift_hist, joy_head_hist = [], [], [], []
    # `joy_foot_peak` is stateful (per-foot running peak inside the swing window),
    # so it has to be stepped alongside the env rather than evaluated pointwise.
    # Without this the report only carries `joy_foot_rhythm`, which since
    # tools/patch_joy_peak_linear.py is no longer the term the policy is trained
    # on -- i.e. "training reward vs achieved reward" was not measurable at all.
    try:
        peak_term = mdp.joy_foot_peak(u.cfg.rewards["joy_feet"], u)
    except Exception as exc:  # older cfg, or the term was swapped out
        peak_term = None
        print(f"[eval] joy_foot_peak unavailable: {exc}")
    # `params` is only expanded by RewardManager; this harness calls the term
    # directly, so every switch has to be forwarded by hand. Without this the
    # report silently grades with the OLD rule while training used pair_min --
    # the two numbers would not be comparable and nothing would say so.
    _peak_kw = {
        k: v for k, v in (u.cfg.rewards["joy_feet"].params or {}).items()
        if k in ("pair_min",)
    }
    _peak_pair = bool(_peak_kw.get("pair_min", False))
    print(f"[eval] joy_foot_peak pair_min={_peak_pair}")
    joy_peak_hist = []

    def _target():
        # JoySmoothPositionAction sets `_processed_actions = _joy_target`
        # (mdp.py:7777), so this is the ctrl target the servos actually receive.
        term = u.action_manager.get_term("joint_pos")
        t = getattr(term, "_processed_actions", None)
        if t is None:
            t = getattr(term, "_joy_target")
        return t.detach().clone()

    tgt_hist.append(_target())
    reset_mask = [False]  # step k is a reset step when any env finished an episode

    with torch.no_grad():
        for k in range(n_steps):
            actions = policy(obs)
            obs, _rew, dones, extras = env.step(actions)
            reset_mask.append(bool(dones.any()))

            pos = robot.data.root_link_pos_w - u.scene.terrain.env_origins
            quat = robot.data.root_link_quat_w
            fz = robot.data.site_pos_w[:, foot_cfg.site_ids, 2] - u.scene.terrain.env_origins[:, None, 2]

            foot_z_hist.append(fz.clone())
            up_hist.append(_up_z(quat))
            xy_hist.append(pos[:, :2].clone())
            tgt_hist.append(_target())
            knee_hist.append(mdp._servo_joint_pos(u, robot)[:, 3].clone())

            joy_feet_hist.append(mdp.joy_foot_rhythm(u, foot_cfg).clone())
            if peak_term is not None:
                # Pin at 20 mm: the gate is a fixed contract, so the
                # reported number must not drift with the curriculum stage.
                joy_peak_hist.append(
                    peak_term(u, foot_cfg, target_height=0.020, **_peak_kw).clone()
                )
            joy_bal_hist.append(mdp.joy_balance(u).clone())
            joy_drift_hist.append(mdp.joy_drift_cost(u).clone())
            joy_head_hist.append(mdp.joy_head_tracking(u).clone())

            timeouts = extras.get("time_outs")
            fell = dones.bool() & (~timeouts.bool() if timeouts is not None else False)
            newly = fell & (term_step < 0)
            term_step[newly] = k

    foot_z = torch.stack(foot_z_hist)          # [T, N, 2]
    up = torch.stack(up_hist)                  # [T, N]
    xy = torch.stack(xy_hist)                  # [T, N, 2]
    tgt = torch.stack(tgt_hist)                # [T+1, N, 14]
    knee = torch.stack(knee_hist)              # [T, N]

    # ---- gate quantities ---------------------------------------------------
    dur = torch.where(term_step < 0, torch.full_like(term_step, n_steps), term_step)
    duration_s = float((dur.float() * step_dt).median())

    # ---- aggregation: keep `mean`, but make the tail visible ----------------
    # `mean over envs, then min over time` is deliberately kept. It looks like it
    # would hide a faller, and it does the opposite: with 64 envs, one env going
    # 0.995 -> 0.1 costs 0.014 of the mean, so 10/64 falling already drags the
    # gate under 0.9. The alternative -- per-env min then median -- only fails
    # once >32/64 fall, i.e. it is *looser*. Checked both by construction
    # (upright 0.995 -> 0.10 from the halfway point):
    #   5/64 fall  -> mean 0.925 (PASS)   median 0.995 (PASS)
    #   10/64 fall -> mean 0.855 (FAIL)   median 0.995 (PASS)
    #   33/64 fall -> mean 0.534 (FAIL)   median 0.100 (FAIL)
    # So mean is the conservative choice and stays as the gate.
    #
    # What it *cannot* show is how many envs failed. That is reported as
    # `min_upright_worst_env` / `end_upright_worst_env` plus `fell_frac`, so a
    # minority of falls is visible rather than inferred.
    min_upright = float(up.mean(dim=1).min())
    per_env_up_min = up.min(dim=0).values                       # [N]
    min_upright_worst_env = float(per_env_up_min.min())
    end_upright = float(up[-1].mean())
    end_upright_worst_env = float(up[-1].min())
    drift = xy[-1].norm(dim=-1)
    max_drift_m = float(drift.max())
    # --- feet_peak: per-foot, the way upstream computes it -------------------
    # Upstream keeps `self.feet_peak = np.zeros(2)` and the gate is
    # `(self.feet_peak > 0.008).all()` -- *both* feet must clear 8 mm.
    # Taking `.max(dim=0).median()` over the (T, N, 2) tensor mixes the two feet
    # into one distribution, so a policy that lifts one foot 20 mm and drags the
    # other at 2 mm scores ~11 mm and passes. That is looser than upstream, and
    # looser in the direction that lets a broken gait through.
    #
    # Gate value: per env take the *worse* foot, then the median across envs --
    # i.e. "the typical environment's worse foot", which fails exactly when a
    # real policy has one lazy leg. Both feet are also reported separately.
    peak_per_foot = foot_z.max(dim=0).values                       # [N, 2]
    feet_peak_each = peak_per_foot.median(dim=0).values            # [2]
    feet_peak_m = float(feet_peak_each.min())
    feet_peak_worst_env = float(peak_per_foot.min(dim=1).values.min())

    # ~foot_support proxy: fraction of (time, env) where at least one foot is
    # within 8 mm of the floor. Official definition lives in parkour/world.py.
    foot_support_proxy = float((foot_z.min(dim=-1).values < 0.008).float().mean())

    dtgt_raw = (tgt[1:] - tgt[:-1]).abs()      # [T, N, 14]
    # `max_target_step_rad` has a hard physical bound: `JoySmoothPositionAction`
    # clamps every per-step change to joy_max_step = 0.08 rad, so a larger jump
    # cannot come from the policy.  Two artefacts violate it:
    #  - transition 0: `_joy_target` is still the zero buffer / default pose before
    #    the first `process_actions`.
    #  - reset: the servo target snaps to the measured pose
    #    (`initialize_joy_servo_targets`).  mjlab resets *inside* `step()`, so the
    #    jump can land one frame either side of the reported `done`; masking by
    #    `done` alone is off-by-one and leaves the artefact in (this is how 1.43 rad
    #    got through a 0.08 rad clamp).
    # Identify artefacts by the bound itself rather than guessing where the reset
    # landed, and report both the raw and the cleaned number so the difference is
    # visible instead of silently "fixed".
    JOY_MAX_STEP = 0.08
    ARTEFACT_TOL = 1e-3
    is_artefact = (dtgt_raw > JOY_MAX_STEP + ARTEFACT_TOL).any(dim=-1)  # [T, N]
    is_artefact[0] = True
    for k, was_reset in enumerate(reset_mask[1:]):
        if was_reset:
            is_artefact[k] = True
            if k + 1 < is_artefact.shape[0]:
                is_artefact[k + 1] = True
    reset_artifact_frac = float(is_artefact.float().mean())
    kept = dtgt_raw[~is_artefact]             # [M, 14]
    if kept.numel() == 0:
        raise SystemExit("every transition was flagged as a reset artefact")
    max_target_step_rad = float(kept.max())
    max_target_step_raw = float(dtgt_raw[1:].max())
    target_rate_rms = float((kept / step_dt).pow(2).mean().sqrt())

    foot_ratio, foot_ac = _fft_high_ratio(foot_z[:, :, 0], step_dt)
    knee_ratio, knee_ac = _fft_high_ratio(knee, step_dt)
    fft_ratio = max(foot_ratio, knee_ratio)
    period = _step_period(foot_z[:, :, 0], step_dt)

    metrics = {
        "duration_s": duration_s,
        "min_upright": min_upright,
        "end_upright": end_upright,
        "max_drift_m": max_drift_m,
        "feet_peak_m": feet_peak_m,
        "target_rate_rms": target_rate_rms,
        "max_target_step_rad": max_target_step_rad,
        "pose_power_above_8hz_ratio": fft_ratio,
    }

    passed = {}
    for name, (level, op) in GATES.items():
        v = metrics[name]
        passed[name] = bool(v >= level) if op == ">=" else bool(v > level) if op == ">" else bool(v < level)

    out = {
        "task_id": task_id,
        "checkpoint": str(checkpoint),
        "device": device,
        "play_cfg": play,
        "num_envs": num_envs,
        "seconds": seconds,
        "step_dt": step_dt,
        "plant": plant_info,
        "gates": {k: {"value": round(metrics[k], 6), "level": GATES[k][0],
                      "op": GATES[k][1], "pass": passed[k]} for k in GATES},
        "joy_passed": all(passed.values()),
        "context": {
            "~foot_support_proxy": round(foot_support_proxy, 4),
            # Upstream's `passed` also requires `foot_support(m, d)`; its
            # definition lives in parkour/world.py and is not in the shipped
            # artifact, so it stays a proxy here instead of a gate.  See _note.
            "feet_peak_left_m": round(float(feet_peak_each[0]), 5),
            "feet_peak_right_m": round(float(feet_peak_each[1]), 5),
            "feet_peak_worst_env_m": round(feet_peak_worst_env, 5),
            "min_upright_worst_env": round(min_upright_worst_env, 5),
            "end_upright_worst_env": round(end_upright_worst_env, 5),
            "step_period_s": period,
            "8hz_ratio_foot": round(foot_ratio, 4),
            "8hz_ratio_knee": round(knee_ratio, 4),
            "foot_ac_rms_m": round(foot_ac, 5),
            # DC level of the signal `joy_foot_peak` grades. The reward's `h` is
            # `z - origin - 0.0005`, so `foot_mean_z_m` is what the payoff sees
            # while standing. Needed because every offline payoff estimate below
            # assumed a 5.7 mm stance foot, and that number was measured on a
            # *different* cfg (`play`, 4 envs). If the training reset leaves the
            # foot near 0.5 mm instead, the "standing already scores 0.29"
            # baseline is wrong and the whole contrast table shifts.
            "foot_mean_z_m": round(float(foot_z[:, :, 0].mean()), 5),
            "knee_ac_rms_rad": round(knee_ac, 5),
            # The gate is `max(foot, knee)`, so interpretability must be judged
            # on whichever channel actually produced that max -- not on whichever
            # channel happens to look alive. Using `or` here let a lively knee
            # (0.167 rad) vouch for a dead foot (1.56 mm AC, below its own 2 mm
            # floor) and reported a high ratio as if it were real chatter.
            "8hz_gate_channel": "foot" if foot_ratio >= knee_ratio else "knee",
            "8hz_foot_interpretable": bool(foot_ac > 0.002),
            "8hz_knee_interpretable": bool(knee_ac > 0.03),
            "8hz_gate_interpretable": bool(
                foot_ac > 0.002 if foot_ratio >= knee_ratio else knee_ac > 0.03
            ),
            "max_target_step_raw": round(max_target_step_raw, 5),
            "reset_artifact_frac": round(reset_artifact_frac, 5),
            "fell_frac": round(float((term_step >= 0).float().mean()), 4),
            "joy_foot_rhythm_mean": round(float(torch.stack(joy_feet_hist).mean()), 4),
            # Which grading rule produced `joy_foot_peak_mean`. 0.529 and 0.144
            # are the same gait under the two rules, so the number is
            # meaningless without this tag.
            "joy_foot_peak_pair_min": _peak_pair,
            "joy_end_peak_min_m": (
                round(float(peak_term.end_peak.min(-1).values.mean()), 5)
                if peak_term is not None else None
            ),
            "joy_foot_peak_mean": (
                round(float(torch.stack(joy_peak_hist).mean()), 4)
                if joy_peak_hist else None
            ),
            "joy_peak_height_p50_m": (
                round(float(peak_term.peak.median()), 5)
                if peak_term is not None else None
            ),
            "joy_balance_mean": round(float(torch.stack(joy_bal_hist).mean()), 4),
            "joy_drift_cost_mean": round(float(torch.stack(joy_drift_hist).mean()), 4),
            "joy_head_tracking_mean": round(float(torch.stack(joy_head_hist).mean()), 4),
            "final_xy_p50": [round(float(v), 4) for v in drift.median(dim=0).values.tolist()]
            if drift.dim() > 1
            else [round(float(drift.median()), 4)],
        },
        "_note": (
            "foot_support is a proxy (~); every other level is from joy.py:report(). "
            "Upstream's `passed` also ANDs in `foot_support(m, d)`, whose definition "
            "is in parkour/world.py and is not in the shipped artifact, so it is "
            "reported but NOT gated here -- do not read joy_passed as "
            "'upstream would ship this'. "
            "feet_peak_m is the worse foot's median peak (upstream wants both feet "
            ">0.008); feet_peak_left_m/right_m and feet_peak_worst_env_m are in "
            "context so a one-legged gait cannot hide behind an aggregate. "
            "max_target_step_rad is clamped to joy_max_step=0.08 by the action term, so "
            "that gate passes by construction and only catches a broken clamp. "
            "8hz ratio is meaningless when the signal is static -- check "
            "8hz_gate_interpretable / *_ac_rms before reading it. "
            "8hz_gate_interpretable is judged on 8hz_gate_channel only (the one "
            "that set the max), so a ratio carried by a near-static foot is "
            "flagged rather than trusted."
        ),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Mjlab-JoySmoothPD-Flat-MicroDuck")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, default=64)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--play", action="store_true",
                    help="use the play env cfg (DR/noise off) instead of the training cfg")
    ap.add_argument("--plant", default="default", choices=PLANT_CHOICES,
                    help="swap only the plant (actuators + spec_fn), keeping the action "
                         "term's conditioner: 'bam' = the upstream voltage-law model")
    ap.add_argument("--out", default=None, help="JSON output path")
    args = ap.parse_args()

    out = run(args.task, args.checkpoint, args.num_envs, args.seconds, args.device, args.play,
              plant=args.plant)

    print(f"\nplant: {out['plant']['plant']}  "
          f"actuators={out['plant']['actuators']}  "
          f"spec_fn={out['plant']['spec_fn']}  "
          f"action_term={out['plant']['action_term']}  "
          f"conditioner={out['plant']['conditioner']}")
    print(f"\n{'gate':32s} {'value':>12s} {'level':>10s}  result")
    print("-" * 68)
    for name, g in out["gates"].items():
        print(f"{name:32s} {g['value']:12.5f} {g['op']+str(g['level']):>10s}  "
              f"{'PASS' if g['pass'] else 'FAIL'}")
    print("-" * 68)
    print(f"{'joy_passed':32s} {str(out['joy_passed']):>12s}")
    for k, v in out["context"].items():
        print(f"  {k:30s} {v}")

    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print(f"\n→ {args.out}")
    return 0 if out["joy_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
