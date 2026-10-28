#!/usr/bin/env python
"""Acceptance measurements for a **walking** (`Mjlab-Velocity-Flat-MicroDuck`) checkpoint.

Every physical quantity is read from an object that already exists in the
training env. Nothing here re-derives what mjlab already computes:

  | quantity | official source |
  |---|---|
  | foot clearance (m) | `scene["foot_height_scan"].data.heights` -- a `TerrainHeightSensor`, the same tensor behind the `foot_height` observation (cfg line ~580) and the `feet_clearance` / `feet_swing_height` rewards |
  | touchdown events | `scene["feet_ground_contact"].compute_first_contact(step_dt)` -- `ContactSensor`, LEFT then RIGHT |
  | in-contact mask | `scene["feet_ground_contact"].data.found` |
  | upright | `robot.data.projected_gravity_b[:, 2]` |
  | yaw | `euler_xyz_from_quat()` |
  | tracking error | `UniformVelocityCommand.metrics["error_vel_xy"] / ["error_vel_yaw"]` |
  | falls | env `dones` minus `extras["time_outs"]` (the termination manager, not a tilt proxy) |
  | action smoothness | `metrics_manager` (`mean_action_acc`) |

Still hand-written, because upstream has no eval-time equivalent:
  * per-**foot** landing peak (official `feet_swing_height` pools both feet into one
    `Metrics/peak_height_mean`; the 8 mm gate needs the worse foot);
  * swing segmentation (peak accumulates while `found == 0`, is banked on first
    contact and zeroed afterwards -- the same three lines `feet_swing_height` uses);
  * net displacement;
  * step rate / simultaneity, counted from the official touchdown events.

Why the whole "did it learn?" question needs physical quantities at all:
1. `Episode_Reward/*` already has the weight folded in. Duckverse's log reads
   `joy_feet: 5.87...6.46`, which looks like 6 mm but is weight 12 x reward 0.5.
2. Mean reward can be filled by standing still (`RL_duck`'s measured counter-example:
   40 falls scored 0.127, no falls scored 0.122 -- resets drop the robot into a stance).
3. Curriculum terms key off `common_step_counter`, which starts at 0 for a fresh env.
   Forgetting that silently grades at stage 0.

Usage:
  .venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py \
      --checkpoint logs/.../model_12000.pt --num-envs 64 --cmd-vx 0.4

Exit code is 0 when every requested gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import torch  # noqa: E402

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from eval_joy_in_sim import PLANT_CHOICES, swap_plant  # noqa: E402

try:
    from plant_id import fingerprint as _plant_fingerprint, one_line as _plant_one_line
except Exception as _e:  # never let the stamp take the measurement down
    def _plant_fingerprint():
        return {"name": "unknown", "error": f"plant_id unavailable: {_e!r}"}

    def _plant_one_line():
        return "plant=UNKNOWN (plant_id import failed)"

TASK_DEFAULT = "Mjlab-Velocity-Flat-MicroDuck"

HEIGHT_SENSOR = "foot_height_scan"
CONTACT_SENSOR = "feet_ground_contact"
FEET = ("left", "right")


def pin_curriculum(env) -> int:
    """Put every curriculum term at its final stage.

    `common_step_counter` is what `reward_weight`, `standing_envs`, the command
    range and the pose ranges all read. It is 0 on a fresh env, which is stage 0.
    A big number is enough -- the counter only ever increases.
    """
    u = env.unwrapped
    before = int(getattr(u, "common_step_counter", 0))
    u.common_step_counter = 10**9
    return before


def freeze_command(cfg, vx: float, vy: float, wz: float, duration: float) -> None:
    """Hold one command for the whole episode.

    `rel_standing_envs` / `rel_turn_in_place_envs` are *training* diversity knobs.
    In an acceptance test they are noise: 15% of the batch would be graded on a
    command it was not asked to follow, and the mean would mix three behaviours.

    `resampling_time_range` is set to the evaluation length on purpose, and not to
    an arbitrarily large number. `UniformVelocityCommand._update_metrics` divides
    every step's error by `resampling_time_range[1] / step_dt`, i.e. by the number
    of steps in one command window. Setting it to `duration` makes that divisor
    exactly the evaluation length, so the official accumulator ends up holding the
    **mean** tracking error for the run. Setting it to 1e9 would divide by 5e10
    and report a flawless zero.
    """
    cmd = cfg.commands["twist"]
    cmd.ranges.lin_vel_x = (vx, vx)
    cmd.ranges.lin_vel_y = (vy, vy)
    cmd.ranges.ang_vel_z = (wz, wz)
    # EVERY `rel_*` knob is a training-diversity switch: leave one non-zero and a
    # fraction of the batch is graded on a command it was never given. `rel_forward_envs`
    # was missed here until a `--cmd-vx 0.0` run tripped `command_frozen_ok`:
    # velocity_command.py:95-99 clamps forward-env vx to `abs().clamp(min=0.3)`, so
    # with rel_forward_envs=0.2 a "cmd vx 0.00" run actually graded 5 of 32 envs at
    # 0.3 m/s. Invisible at cmd 0.4 (0.4 > 0.3), fatal for any sweep below 0.3 --
    # i.e. exactly the experiment that was about to be run. Swept reflectively rather
    # than by name so an upstream addition cannot slip through the same way.
    swept = {}
    for knob in [k for k in dir(cmd) if k.startswith("rel_") or k == "init_velocity_prob"]:
        val = getattr(cmd, knob)
        if isinstance(val, (int, float)):
            swept[knob] = float(val)
            setattr(cmd, knob, 0.0)
    still_on = {k: v for k, v in swept.items() if (getattr(cmd, k) or 0.0) != 0.0} or None
    if still_on:
        raise RuntimeError(f"command-diversity knob could not be zeroed: {still_on}")
    # `heading_command` must stay True: the command class raises
    # "ranges.heading is set but heading_command=False" and refuses to build.
    # With `rel_heading_envs = 0` no env is ever a heading env, so `ang_vel_z`
    # above is used verbatim and heading never overrides it.
    cmd.heading_command = True
    cmd.ranges.heading = (0.0, 0.0)
    cmd.resampling_time_range = (duration, duration)

    # The `standing_envs` curriculum term rewrites `rel_standing_envs` on EVERY
    # step from `common_step_counter`, so pinning the counter to 1e9 (which is
    # what makes the run reproducible) also pins it to the LAST stage -- 0.25 --
    # silently undoing the 0.0 two lines above. Measured on model_4000: 6 of 16
    # envs were graded on "stand still" while the run was reported as
    # "cmd vx 0.4". That dilutes vx_mean by the standing fraction and mixes ~0
    # error into error_vel_xy, so two checkpoints cannot be compared. Removing
    # the term is the only fix that survives: setting the cfg value alone is
    # overwritten again on the next curriculum tick.
    cfg.curriculum.pop("standing_envs", None)


def drop_pushes(cfg) -> list[str]:
    """Remove the push event -- it exists to train robustness, not to be graded."""
    dropped = [k for k in list(cfg.events.keys()) if "push" in k.lower()]
    for k in dropped:
        cfg.events.pop(k)
    return dropped


def override_solver(cfg, iters=None, ls_iters=None, nconmax=None) -> dict:
    """Override the contact solver budget, so one checkpoint can be graded at two fidelities.

    Why this exists: the flat velocity task ships microduck_rl's original budget
    (``iterations=10``, ``ls_iterations=20``). Isaac Lab's own MicroDuck port raises
    it to 100/50 with the comment *"microduck_rl's 10 iterations stop some contact
    solves short; MJWarp exits once every world converges"* -- and MJWarp is the same
    solver mjlab runs on. So the question "is the foot too low because the policy
    never learned to lift it, or because the solver cannot resolve the sole contact"
    can be answered without retraining: replay one checkpoint at both budgets.
    """
    before = {
        "iterations": int(cfg.sim.mujoco.iterations),
        "ls_iterations": int(cfg.sim.mujoco.ls_iterations),
        "nconmax": int(cfg.sim.nconmax),
    }
    if iters is not None:
        cfg.sim.mujoco.iterations = int(iters)
    if ls_iters is not None:
        cfg.sim.mujoco.ls_iterations = int(ls_iters)
    if nconmax is not None:
        cfg.sim.nconmax = int(nconmax)
    after = {
        "iterations": int(cfg.sim.mujoco.iterations),
        "ls_iterations": int(cfg.sim.mujoco.ls_iterations),
        "nconmax": int(cfg.sim.nconmax),
    }
    return {"before": before, "after": after}


def _read_metrics(u) -> dict[str, float]:
    """Current step's official metric values for env 0 (cheap, public API)."""
    out: dict[str, float] = {}
    try:
        mm = u.metrics_manager
        if not mm.active_terms:
            return out
        for name, values in mm.get_active_iterable_terms(0):
            if values:
                out[name] = float(values[0])
    except Exception:  # noqa: BLE001
        pass
    return out


def run(task_id, checkpoint, num_envs, seconds, device, vx, vy, wz, plant, play,
        solver_iters=None, solver_ls=None, solver_ncon=None, seed=None):
    from dataclasses import asdict

    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.lab_api.math import euler_xyz_from_quat
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(task_id, play=play)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs
    # None = the pre-P2 behaviour (random seed), so archived readings stay
    # comparable.
    # What a seed does and does NOT buy here, measured 2026-10-28 on 8 envs:
    #   * same seed twice -> IDENTICAL initial conditions
    #     (yaw0 = 38.8096 / -110.9149 / -12.9005 ... bit for bit), so the seed is
    #     genuinely plumbed through cfg.seed -> seed_rng -> torch/numpy/random/wp;
    #   * but after only 20 zero-action steps yaw already differs in the 4th
    #     decimal (-111.5129 vs -111.5186). mjlab ships the warning itself --
    #     utils/random.py: "Note: MuJoCo Warp is not fully deterministic yet"
    #     (mujoco_warp#562). A policy-driven contact-rich rollout amplifies that
    #     over hundreds of steps.
    # So a seed pins the STARTING POINT, never the trajectory: no single reading
    # on this stack is bit-reproducible, and "rerun it to double-check" cannot be
    # used as verification. Independence has to come from N repeats + sem.
    if seed is not None:
        env_cfg.seed = int(seed)

    frozen = {"vx": vx, "vy": vy, "wz": wz}
    freeze_command(env_cfg, vx, vy, wz, seconds)
    dropped = drop_pushes(env_cfg)

    plant_info = None
    if plant != "default":
        plant_info = swap_plant(env_cfg, plant)

    solver = override_solver(env_cfg, solver_iters, solver_ls, solver_ncon)

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    obs, _ = env.reset()
    counter_before = pin_curriculum(env)

    u = env.unwrapped
    robot = u.scene["robot"]
    height_sensor = u.scene[HEIGHT_SENSOR]
    contact = u.scene[CONTACT_SENSOR]

    step_dt = float(u.step_dt)
    n_steps = int(round(seconds / step_dt))
    dev = u.device

    vx_h, vy_h, wz_h, up_h, yaw_h, xy_h = [], [], [], [], [], []
    # The command is assumed frozen for the whole window; recording it is what
    # turns that assumption into a measurement (see the `command` block).
    cmd_h: list[torch.Tensor] = []
    metric_h: dict[str, list[float]] = {}

    # Swing bookkeeping, mirroring `mjlab.tasks.velocity.mdp.rewards.feet_swing_height`:
    # peak accumulates only while the foot is airborne, is banked at touchdown,
    # then reset.
    peaks = torch.zeros((num_envs, len(FEET)), device=dev)
    # One list per foot: `peaks[mask]` on a [N, 2] mask flattens the column away,
    # so the two feet must be selected separately or left/right merge silently.
    landing_peaks: list[list[torch.Tensor]] = [[], []]
    stance_heights: list[list[torch.Tensor]] = [[], []]
    # Air-time bookkeeping -- the same quantity `feet_air_time` scores: seconds
    # since the foot last touched the ground, sampled at each touchdown.
    # That reward is a step function (`threshold_min < t < threshold_max`), so
    # the raw distribution is what decides whether a command region earns the
    # term at all. Without it, "the policy stopped lifting its feet" and "the
    # window moved past the gait" look identical from the outside.
    swing_t = torch.zeros((num_envs, len(FEET)), device=dev)
    air_samples: list[list[torch.Tensor]] = [[], []]
    touchdowns = torch.zeros((num_envs, len(FEET)), device=dev)
    simultaneous = torch.zeros((), device=dev)  # steps where both feet land together
    fell = torch.zeros(num_envs, dtype=torch.bool, device=dev)

    def f(x):
        return float(x)

    def mm(x):
        return float(x) * 1e3

    with torch.no_grad():
        for _k in range(n_steps):
            actions = policy(obs)
            obs, _rew, dones, extras = env.step(actions)

            # Re-pin every step: the curriculum manager advances the counter, and
            # an episode reset must not drag the term back to an earlier stage.
            u.common_step_counter = 10**9

            d = robot.data
            cmd_h.append(u.command_manager.get_term("twist").vel_command_b[:, :2].clone())
            vx_h.append(d.root_link_lin_vel_b[:, 0].clone())
            vy_h.append(d.root_link_lin_vel_b[:, 1].clone())
            wz_h.append(d.root_link_ang_vel_b[:, 2].clone())
            # up = -projected gravity z, i.e. cos(tilt); same quantity the
            # `bad_orientation` termination thresholds.
            up_h.append((-d.projected_gravity_b[:, 2]).clone())
            yaw_h.append(euler_xyz_from_quat(d.root_link_quat_w)[2].clone())
            xy_h.append(d.root_link_pos_w[:, :2].clone())

            heights = height_sensor.data.heights          # [N, 2] metres above terrain
            found = contact.data.found                    # [N, 2] 1 = touching
            first_contact = contact.compute_first_contact(dt=step_dt)  # [N, 2] bool

            peaks = torch.where(found == 0, torch.maximum(peaks, heights), peaks)
            if bool(first_contact.any()):
                for j in range(len(FEET)):
                    sel = first_contact[:, j]
                    if bool(sel.any()):
                        landing_peaks[j].append(peaks[sel, j].clone())
                        # Read *before* the clock is advanced: at this step the
                        # foot has just landed, so `swing_t` still holds the
                        # time it spent airborne.
                        air_samples[j].append(swing_t[sel, j].clone())
                touchdowns += first_contact.float()
                simultaneous += first_contact.all(dim=1).float().sum()
            # Advance the air clock: touching resets it, airborne accumulates.
            swing_t = torch.where(
                found > 0, torch.zeros_like(swing_t), swing_t + step_dt
            )
            # Bare-contact height is the sensor's zero: it must read ~0. If it does
            # not, every "peak" below is offset by the same amount and the 8 mm
            # gate is measuring the wrong thing.
            for j in range(len(FEET)):
                grounded = found[:, j] > 0
                if bool(grounded.any()):
                    stance_heights[j].append(heights[grounded, j].clone())
            peaks = torch.where(first_contact, torch.zeros_like(peaks), peaks)

            timeouts = extras.get("time_outs")
            terminated = dones.bool() & (~timeouts.bool() if timeouts is not None else False)
            fell |= terminated
            # A reset teleports the robot back into a stance: stale swing state
            # from the previous episode must not leak into the next one.
            keep = (~dones.bool()).float().unsqueeze(-1)
            peaks = peaks * keep

            for name, value in _read_metrics(u).items():
                metric_h.setdefault(name, []).append(value)

    vx_t = torch.stack(vx_h)          # [T, N]
    vy_t = torch.stack(vy_h)
    wz_t = torch.stack(wz_h)
    up_t = torch.stack(up_h)
    xy_t = torch.stack(xy_h)          # [T, N, 2]
    yaw_t = torch.stack(yaw_h)        # [T, N]

    vx_mean_t = vx_t.mean(dim=0)      # per-env mean over the window

    speed = {
        "cmd_vx": vx,
        # Median over envs is the robust centre; mean is kept alongside so a
        # bimodal batch (half walking, half stalled) shows up as mean << median
        # instead of being averaged into one misleading number.
        "vx_median_of_env_means": f(vx_mean_t.median()),
        "vx_mean": f(vx_t.mean()),
        "vy_mean": f(vy_t.mean()),
        "wz_mean": f(wz_t.mean()),
    }

    # The command is a BODY-frame velocity, and the inherited `reset_base` event
    # randomises yaw uniformly over (-pi, pi) -- velocity_env_cfg.py:
    # pose_range["yaw"] = (-3.14, 3.14). So WORLD-frame net displacement cancels
    # ACROSS envs: dx_mean reads ~0 even while every individual robot is walking
    # away from its own start point. Measured on iter 1250: world dx -0.039 m
    # while body vx was +0.210 m/s. Projecting each env's displacement onto its
    # own INITIAL heading is the only comparable quantity.
    net = xy_t[-1] - xy_t[0]
    yaw0 = yaw_t[0]
    cos0, sin0 = torch.cos(yaw0), torch.sin(yaw0)
    dx_body = cos0 * net[:, 0] + sin0 * net[:, 1]
    dy_body = -sin0 * net[:, 0] + cos0 * net[:, 1]
    # Body-frame path length: integral of body vx, immune to any turning.
    path_dx = (vx_t * step_dt).sum(dim=0)
    disp = {
        "dx_body_mean": f(dx_body.mean()),
        "path_dx_median": f(path_dx.median()),
        "expected_dx": vx * seconds,
        # median of the per-env ratio: a mean would let one stalled env drag the
        # headline number around.
        "dx_over_expected": (f((dx_body / (vx * seconds)).median())
                             if vx != 0 else None),
        "abs_dy_body_median": f(dy_body.abs().median()),
        # Signed lateral drift: a bug/assymmetry shows up as a NON-ZERO MEAN here,
        # while `abs_dy_body_median` stays large either way. Same unwrap logic does
        # not apply (this is metres, not an angle) -- no wrapping possible.
        "dy_body_mean": f(dy_body.mean()),
        "dy_body_median": f(dy_body.median()),
        "dy_body_sem": f(dy_body.std(unbiased=False) / max(dy_body.numel(), 1) ** 0.5),
        # kept for the record only -- never judge on this one (see above)
        "dx_world_mean_unused": f(net[:, 0].mean()),
    }

    # Was the command actually the frozen one for every env, every step?
    # This is a MEASUREMENT of the protocol, not a behaviour metric: a `standing`
    # or `turn-in-place` curriculum rewriting rel_* behind our back (see
    # freeze_command) shows up here as a non-zero `frac_cmd_zero` instead of
    # quietly deflating vx_mean by 25%.
    cmd_t = torch.stack(cmd_h)                       # [T, N, 2]
    want = torch.tensor([vx, vy], dtype=cmd_t.dtype, device=cmd_t.device)
    dev_from_frozen = (cmd_t - want).abs().amax(dim=-1)          # [T, N]
    command = {
        "frozen": frozen,
        "uniq_cmd_vx": sorted({round(float(x), 6) for x in torch.unique(cmd_t[..., 0])}),
        "frac_cmd_zero_vx": f((cmd_t[..., 0].abs() < 1e-6).float().mean()),
        "frac_off_frozen_1e3": f((dev_from_frozen > 1e-3).float().mean()),
        "max_dev_from_frozen": f(dev_from_frozen.max()),
    }

    # P2 (2026-10-28): the sign of the drift is the whole question -- "does the
    # robot systematically veer one way" is invisible once you take .abs(). Both
    # `heading` below and `per_env` keep the UNSIGNED number for continuity with
    # every archived reading, and add SIGNED variants next to it.
    _drift = (yaw_t[-1] - yaw_t[0]) / seconds * 180 / math.pi   # [N], deg/s
    # Unwrap: yaw comes from euler_xyz and can cross +-pi, which would fake a
    # huge signed value and flip its sign. Work modulo 360 deg instead.
    _drift = (_drift + 180.0) % 360.0 - 180.0
    _sign_agree = (torch.sign(_drift) == torch.sign(_drift.mean())) & (_drift.abs() > 1e-9)
    heading = {
        "yaw_drift_deg_s": f(_drift.abs().median()),
        "yaw_drift_signed_deg_s_mean": f(_drift.mean()),
        "yaw_drift_signed_deg_s_median": f(_drift.median()),
        "yaw_drift_signed_deg_s_sem": f(_drift.std(unbiased=False) / max(_drift.numel(), 1) ** 0.5),
        # 1.0 = every env veered the same way (systematic / left-right asymmetric);
        # ~0.5 = coin flip (random, i.e. sample noise or undiagnosed).
        "frac_same_sign": f(_sign_agree.float().mean()),
    }

    stability = {
        "upright_mean": f(up_t.mean()),
        "upright_min": f(up_t.mean(dim=1).min()),
        "terminated_frac": f(fell.float().mean()),
    }

    peak_l = torch.cat(landing_peaks[0]) if landing_peaks[0] else None
    peak_r = torch.cat(landing_peaks[1]) if landing_peaks[1] else None
    n_land = (0 if peak_l is None else int(peak_l.numel())) + (
        0 if peak_r is None else int(peak_r.numel()))
    med_l = None if peak_l is None else mm(peak_l.median())
    med_r = None if peak_r is None else mm(peak_r.median())
    # "both" is the *worse* foot's median landing peak: the 8 mm gate must not be
    # passed by one good leg while the other barely leaves the ground.
    both = None if (med_l is None or med_r is None) else min(med_l, med_r)
    stance_l = torch.cat(stance_heights[0]).median() if stance_heights[0] else None
    stance_r = torch.cat(stance_heights[1]).median() if stance_heights[1] else None
    env_seconds = num_envs * seconds
    # Air-time distribution + the share that lands inside `feet_air_time`'s
    # window. The window is read from the live cfg rather than assumed, because
    # this task overrides mjlab's default [0.05, 0.5] with [0.125, 0.3]
    # (microduck_velocity_env_cfg.py:333-336) -- and that tightening is exactly
    # what a slow gait can fall out of.
    air_win = (0.125, 0.300)
    try:
        _p = u.cfg.rewards["air_time"].params
        air_win = (
            float(_p.get("threshold_min", air_win[0])),
            float(_p.get("threshold_max", air_win[1])),
        )
    except Exception:  # noqa: BLE001
        pass
    air_all = (
        torch.cat([torch.cat(s) for s in air_samples if s]) if any(air_samples) else None
    )
    air_stats = None
    if air_all is not None and air_all.numel() > 0:
        air_stats = {
            "n_samples": int(air_all.numel()),
            "p25_s": f(air_all.quantile(0.25)),
            "median_s": f(air_all.median()),
            "p75_s": f(air_all.quantile(0.75)),
            "max_s": f(air_all.max()),
            "frac_in_reward_window": f(
                ((air_all > air_win[0]) & (air_all < air_win[1])).float().mean()
            ),
            "window_s": [air_win[0], air_win[1]],
            "gain_if_in_window": "1 per airborne foot (weight in cfg.rewards.air_time)",
        }
    feet = {
        "landings_per_foot_hz": f(touchdowns.sum() / (2 * env_seconds)),
        "air_time": air_stats,
        "landing_events": n_land,
        "touchdown_events": int(touchdowns.sum()),
        "simultaneous_frac": f(simultaneous / max(int(touchdowns.sum()), 1)),
        "left_peak_mm_median": med_l,
        "right_peak_mm_median": med_r,
        "both_peak_mm_median": both,
        "stance_mm_median": None if stance_l is None else mm(stance_l),
    }

    official: dict = {}
    err_env = yaw_err_env = None
    try:
        term = u.command_manager.get_term("twist")
        # Keep the per-env vector, not only its mean: `metrics[...]` is [N] and is
        # only ever accumulated (never reset), so at the end of the window each
        # entry already holds that env's own window average.
        err_env = term.metrics["error_vel_xy"].detach().clone()
        yaw_err_env = term.metrics["error_vel_yaw"].detach().clone()
        official["error_vel_xy"] = f(term.metrics["error_vel_xy"].mean())
        official["error_vel_yaw"] = f(term.metrics["error_vel_yaw"].mean())
        official["error_vel_xy_median"] = f(term.metrics["error_vel_xy"].median())
    except Exception as e:  # noqa: BLE001
        official["error"] = f"{type(e).__name__}: {e}"

    metrics = {k: f(sum(v) / len(v)) for k, v in metric_h.items() if v}

    # The official metric does NOT divide by the number of steps:
    #   metrics["error_vel_xy"] += ||cmd_xy - v_xy|| / max_command_step   (accumulated)
    #   max_command_step = resampling_time_range[1] / step_dt
    # (mjlab/tasks/velocity/mdp/velocity_command.py:61-69.)
    # So it equals the TRUE window mean only when the evaluation window happens to
    # be exactly max_command_step long. This task resamples commands over
    # (3.0, 8.0) s at 50 Hz -> max_command_step = 400 = the 8.0 s window, which is
    # the only reason 0.21 reads as a velocity in m/s. Run --seconds 4 and the same
    # policy would score half as bad with nothing about the robot having changed.
    # Pinning that coincidence down as a gate is the difference between a reading
    # and a reading whose units are assumptions.
    rtr = tuple(getattr(env_cfg.commands["twist"], "resampling_time_range", (0.0, 0.0)))
    max_cmd_step = (rtr[1] / step_dt) if step_dt else None
    metric_window = {
        "window_steps": n_steps,
        "step_dt": step_dt,
        "resampling_time_range_s": list(rtr),
        "max_command_step": max_cmd_step,
        "ratio_window_over_max": (n_steps / max_cmd_step) if max_cmd_step else None,
        "is_true_mean": bool(max_cmd_step and abs(n_steps - max_cmd_step) <= 1e-6),
        "note": ("error_vel_xy is a true m/s mean only when is_true_mean is true; "
                 "otherwise multiply by ratio_window_over_max before comparing."),
    }

    def _spread(t) -> dict | None:
        if t is None:
            return None
        x = t.detach().float().double().flatten()
        n_ = int(x.numel())
        sd = float(x.std(unbiased=True)) if n_ > 1 else None
        q = torch.quantile(
            x, torch.tensor([0.1, 0.5, 0.9], dtype=torch.float64, device=x.device)
        ).tolist()
        return {
            "n": n_,
            "mean": float(x.mean()),
            "std": sd,
            "sem": (sd / math.sqrt(n_)) if sd is not None else None,
            "p10": q[0], "p50": q[1], "p90": q[2],
            "min": float(x.min()), "max": float(x.max()),
            "values": [round(float(v), 6) for v in x],
        }

    # One number per ENV. `sem = std/sqrt(n)` is how far the batch mean above can
    # wander when the initial conditions are redrawn -- i.e. the repeatability of
    # the headline number. The step axis is deliberately NOT used as a sample: one
    # robot walks a single correlated 400-step trajectory, so 400 steps are not
    # 400 independent observations, and dividing by sqrt(400) would manufacture a
    # 20x-too-small error bar.
    per_env = {
        "note": ("per-env values; sem = std/sqrt(n) over the env axis only, which is "
                 "the uncertainty of the mean above"),
        "vx_mean": _spread(vx_mean_t),
        "error_vel_xy": _spread(err_env),
        "error_vel_yaw": _spread(yaw_err_env),
        "dx_body": _spread(dx_body),
        "abs_dy_body": _spread(dy_body.abs()),
        "dy_body_signed": _spread(dy_body),
        "yaw_drift_signed_deg_s": _spread(_drift),
        "upright": _spread(up_t.mean(dim=0)),
        "yaw_drift_deg_s": _spread(
            (yaw_t[-1] - yaw_t[0]).abs() / seconds * 180 / math.pi),
    }

    env.close()

    gates = {
        # Measurement integrity first: if these fail, every number below is
        # suspect, so they must not be buried under the behaviour gates.
        "command_frozen_ok": bool(command["max_dev_from_frozen"] <= 1e-3),
        # Unit gate: error_vel_xy is only a velocity (m/s) while the window equals
        # max_command_step. See the metric_window block.
        "metric_window_ok": bool(metric_window["is_true_mean"]),
        "sensor_zero_ok": (None if feet["stance_mm_median"] is None
                           else bool(abs(feet["stance_mm_median"]) <= 3.0)),
        "measurement_consistent": bool(feet["landing_events"] == feet["touchdown_events"]),
        # 0.5x the command is deliberately lenient: run #1 asks "does it move at
        # all under a real forward command", not "is it as good as the 12195-iter
        # reference".
        "tracks_half_command": bool(speed["vx_median_of_env_means"] >= 0.5 * vx) if vx > 0 else None,
        # Directional gates, added after upstream issue #46 + the diagnosis repo
        # (Qi-hub-dot/microduck-locomotion-diagnosis) showed the failure mode is
        # not "does not walk" but "walks sideways / steps in place":
        #   * gate pays for air_time whenever |cmd| > 0.01, so stepping in place
        #     collects the largest positive weight (3.0) without translating;
        #   * track_linear_velocity weights the x and y errors equally, so a
        #     policy whose lateral drift is 2x its forward speed loses almost
        #     nothing (measured: fwd +0.112 / lat -0.230 at step 7).
        # Both are visible only if displacement is judged per axis AND in the
        # env's own heading frame (see the disp block: world-frame dx is ~0 by
        # construction because reset yaw is uniform).
        "translates_forward": (bool(disp["dx_over_expected"] >= 0.2)
                               if disp["dx_over_expected"] is not None else None),
        "not_sideways": (bool(disp["abs_dy_body_median"] <= 0.5 * abs(disp["dx_body_mean"]))
                         if disp["dx_over_expected"] is not None else None),
        # Official error_vel_xy replaces the hand-rolled |vx - cmd|: same idea, and
        # it is the number the training logs already carry. BUT it averages all
        # five command modes and the whole episode including the reset ramp-up,
        # so it reads ~3x high: the same checkpoint measures 0.07 frame-by-frame
        # in steady state and logs 0.206. Threshold therefore 0.25, not 0.15 --
        # 0.15 would fail a policy that demonstrably walks (0.206 was that run's
        # number AFTER the lateral fix). Trust tracks_half_command instead.
        "error_vel_xy_le_0.25": bool(official["error_vel_xy"] <= 0.25) if "error_vel_xy" in official else None,
        "no_fall": bool(stability["terminated_frac"] < 0.02),
        "stays_upright": bool(stability["upright_min"] > 0.90),
        "feet_clear_8mm": bool((feet["both_peak_mm_median"] or 0.0) >= 8.0),
        # >= 3 touchdowns per foot in the window, and the two feet do not land
        # together most of the time (a hop lands both at once).
        "steps_alternate": bool(feet["landings_per_foot_hz"] * seconds >= 3.0
                                and feet["simultaneous_frac"] < 0.5),
    }

    return {
        "task": task_id,
        "checkpoint": str(checkpoint),
        "num_envs": num_envs,
        "seconds": seconds,
        "device": device,
        "plant": plant,
        "plant_info": plant_info,
        # Recorded, not assumed: with seed=None the run is not reproducible, so a
        # reading that later has to be re-checked cannot be re-checked.
        "seed": seed,
        # Which physical plant produced this reading. cfg/mdp hashes do NOT cover
        # it (the actuator lives one import deeper, in microduck_constants), and
        # it moves vx from 0.316/0%-falls to 0.109/100%-falls. Never omit this.
        "plant_fingerprint": _plant_fingerprint(),
        "solver": solver,
        "play_cfg": play,
        "command": frozen,
        "command_measured": command,
        "curriculum_counter_before_pin": counter_before,
        "dropped_events": dropped,
        "sensors": {"height": HEIGHT_SENSOR, "contact": CONTACT_SENSOR},
        "speed": speed,
        "official_metrics": official,
        "official_metric_terms": metrics,
        "displacement": disp,
        "heading": heading,
        "stability": stability,
        "feet": feet,
        "metric_window": metric_window,
        "per_env": per_env,
        "gates": gates,
        "passed": [k for k, v in gates.items() if v],
        "failed": [k for k, v in gates.items() if v is False],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=TASK_DEFAULT)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, default=64)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--cmd-vx", type=float, default=0.4)
    ap.add_argument("--cmd-vy", type=float, default=0.0)
    ap.add_argument("--cmd-wz", type=float, default=0.0)
    ap.add_argument("--plant", default="default", choices=list(PLANT_CHOICES))
    ap.add_argument("--solver-iters", type=int, default=None,
                    help="override sim.mujoco.iterations (flat task default: 10)")
    ap.add_argument("--solver-ls", type=int, default=None,
                    help="override sim.mujoco.ls_iterations (flat task default: 20)")
    ap.add_argument("--solver-ncon", type=int, default=None,
                    help="override sim.nconmax (flat task default: 35)")
    ap.add_argument("--play", action="store_true",
                    help="build the play cfg (drops some training-only terms)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--seed", type=int, default=None,
                    help="env rng seed; None keeps the archived random-seed "
                         "behaviour. Three different seeds = three independent "
                         "repeats (needed for quantities whose single-run CV is "
                         "of order tens of percent).")
    a = ap.parse_args()

    r = run(a.task, a.checkpoint, a.num_envs, a.seconds, a.device,
            a.cmd_vx, a.cmd_vy, a.cmd_wz, a.plant, a.play,
            a.solver_iters, a.solver_ls, a.solver_ncon, a.seed)

    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {p}")

    if a.json_only:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0 if not r["failed"] else 1

    s, d, h, st, ft = r["speed"], r["displacement"], r["heading"], r["stability"], r["feet"]
    om, mm_ = r["official_metrics"], r["official_metric_terms"]
    print()
    print("=" * 66)
    print(f"checkpoint  {Path(a.checkpoint).name}   plant={a.plant}   play={a.play}")
    print(f"plant       {_plant_one_line()}")
    sv = r.get("solver") or {}
    if sv and sv.get("before") != sv.get("after"):
        print(f"solver      iters {sv['before']['iterations']} -> {sv['after']['iterations']}"
              f"   ls {sv['before']['ls_iterations']} -> {sv['after']['ls_iterations']}"
              f"   ncon {sv['before']['nconmax']} -> {sv['after']['nconmax']}")
    print(f"command     vx={a.cmd_vx:+.2f} vy={a.cmd_vy:+.2f} wz={a.cmd_wz:+.2f}   "
          f"{a.num_envs} envs x {a.seconds:.0f}s")
    cq = r.get("command_measured") or {}
    if cq:
        print(f"            measured: uniq vx {cq['uniq_cmd_vx']}  "
              f"frac cmd==0 {cq['frac_cmd_zero_vx']*100:.1f}%  "
              f"offfrozen {(cq['frac_off_frozen_1e3']*100):.1f}% of steps  "
              f"max dev {cq['max_dev_from_frozen']:.4f}")
    print(f"curriculum  pinned 1e9 (was {r['curriculum_counter_before_pin']}); "
          f"dropped events: {r['dropped_events'] or 'none'}")
    print("-" * 66)
    print(f"speed       vx mean {s['vx_mean']:+.3f}  median-of-envs "
          f"{s['vx_median_of_env_means']:+.3f}  (cmd {s['cmd_vx']:+.3f} m/s)"
          f"  vy {s['vy_mean']:+.3f}  wz {s['wz_mean']:+.3f}")
    if "error_vel_xy" in om:
        print(f"            official error_vel_xy {om['error_vel_xy']:.3f} m/s  "
              f"error_vel_yaw {om['error_vel_yaw']:.3f} rad/s")
    print(f"displacement dx_body {d['dx_body_mean']:+.3f} m  path {d['path_dx_median']:+.3f} m "
          f"(expected {d['expected_dx']:+.3f}, ratio "
          f"{d['dx_over_expected'] if d['dx_over_expected'] is None else round(d['dx_over_expected'], 2)})"
          f"  |dy_body| {d['abs_dy_body_median']:.3f} m"
          f"  [world dx {d['dx_world_mean_unused']:+.3f}, not a criterion]")
    print(f"heading     yaw drift {h['yaw_drift_deg_s']:.1f} deg/s")
    print(f"stability   upright mean {st['upright_mean']:.4f}  min {st['upright_min']:.4f}  "
          f"terminated {st['terminated_frac']*100:.2f}%")
    both = "n/a" if ft["both_peak_mm_median"] is None else f"{ft['both_peak_mm_median']:.2f}"
    left = "n/a" if ft["left_peak_mm_median"] is None else f"{ft['left_peak_mm_median']:.2f}"
    right = "n/a" if ft["right_peak_mm_median"] is None else f"{ft['right_peak_mm_median']:.2f}"
    print(f"feet        L {left} mm  R {right} mm  both {both} mm  |  "
          f"{ft['landings_per_foot_hz']:.2f} Hz per foot, "
          f"{ft['simultaneous_frac']*100:.0f}% simultaneous  ({ft['landing_events']} landings)")
    if mm_:
        print(f"metrics     " + "  ".join(f"{k} {v:.4f}" for k, v in mm_.items()))
    print("-" * 66)
    for k, v in r["gates"].items():
        if v is None:
            print(f"  [skip] {k}")
        else:
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print("=" * 66)
    return 0 if not r["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
