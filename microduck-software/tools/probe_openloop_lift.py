"""Open-loop probe: if we *command* a large leg excursion, does the foot actually lift?

Why this exists
---------------
Five reward variants produced 5.3-5.7 mm of foot peak, and the last two reward
shapes were opposites in almost every respect (time-average Gaussian at 18 mm vs
swing-window running peak with a linear 20 mm payoff). The trained policies were
also different: `joy_feet` came out at 8.5/12 on one and 1.3/12 on the other, and
their `target_rate_rms` differed (1.255 vs 0.965). Yet the foot peak was 5.3 mm
both times, with `foot_mean_z` at 3.46 mm and `knee_ac_rms` at 0.063 rad -- i.e.
the knee is executing a +-3.6 deg wiggle.

Two hypotheses remain, and they call for completely different next steps:

    H1 (policy)   the actuator path is fine; the policy simply never commands a
                  large excursion, because 0.57 rad is ~4.8 sigma of the
                  `init_std=0.12` exploration noise and nothing bootstraps it
    H2 (plant)    something between the action and the joint -- the conditioner,
                  the PD gains, the torque limit, the contact -- caps the
                  excursion regardless of what is commanded

This probe separates them by bypassing the policy: it drives the env with a
scripted action (a step on one leg's joints) and records the foot height. The
action still goes through `JoySmoothPositionAction`, i.e. through the real
`joy_alpha=0.25 / joy_max_step=0.08` conditioner, so the measured rise time is
the deployed one, not an idealised ramp.

Read the output as:
    "foot rose to X mm within 0.435 s (one half-cycle of the 1.15 Hz clock)"
If X >= 15 mm for some joint set -> H1. The target is reachable; the reward or
the exploration is the problem.
If X stays near the 3.5 mm stance height for every joint set -> H2. No reward
change can help; the plant is the constraint.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/probe_openloop_lift.py
    .venv-mjlab/Scripts/python.exe tools/probe_openloop_lift.py --device cpu
"""

from __future__ import annotations

import argparse
import math

import torch

TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"
# Joint order of the 14-d action, resolved from the actor's output width. The
# left leg is indices 0..4 (hip_yaw, hip_roll, hip_pitch, knee, ankle), matching
# `probe_joint_tracking.py`'s `_servo_joint_pos(...)[:, 3]` = left_knee.
LEFT = {"hip_yaw": 0, "hip_roll": 1, "hip_pitch": 2, "knee": 3, "ankle": 4}

CASES = [
    ("knee +0.60", {"knee": 0.60}),
    ("knee +0.85", {"knee": 0.85}),
    ("hip_pitch +0.60", {"hip_pitch": 0.60}),
    ("hip_pitch +0.85", {"hip_pitch": 0.85}),
    ("hip_roll +0.35", {"hip_roll": 0.35}),
    ("pitch+0.45 knee+0.45", {"hip_pitch": 0.45, "knee": 0.45}),
    ("pitch+0.30 knee+0.60 ankle-0.30", {"hip_pitch": 0.30, "knee": 0.60, "ankle": -0.30}),
    ("all: roll+0.30 pitch+0.40 knee+0.50", {"hip_roll": 0.30, "hip_pitch": 0.40, "knee": 0.50}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--seconds", type=float, default=1.6)
    ap.add_argument("--envs", type=int, default=8)
    args = ap.parse_args()

    import mjlab_microduck.tasks  # noqa: F401  (registers the tasks)
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.tasks.registry import load_env_cfg
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(TASK, play=True)
    env_cfg.scene.num_envs = args.envs
    u = ManagerBasedRlEnv(cfg=env_cfg, device=args.device)
    step_dt = float(u.step_dt)
    n_steps = int(round(args.seconds / step_dt))
    print(f"step_dt={step_dt:.4f}s ({1 / step_dt:.0f} Hz)  n_steps={n_steps}  "
          f"envs={args.envs}")
    print(f"half-cycle at 1.15 Hz = {1 / (2 * 1.15):.4f}s = "
          f"{1 / (2 * 1.15) / step_dt:.1f} control steps\n")

    foot_cfg = SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])
    foot_cfg.resolve(u.scene)
    left_site, right_site = foot_cfg.site_ids

    print(f"{'case':<38}{'stance':>9}{'peak L':>9}{'peak R':>9}"
          f"{'rise@0.435s':>13}{'upright':>9}")
    print("-" * 88)

    half_steps = int(round((1 / (2 * 1.15)) / step_dt))
    for label, offsets in CASES:
        u.reset()
        robot = u.scene["robot"]
        origin_z = u.scene.terrain.env_origins[:, None, 2]
        z0 = robot.data.site_pos_w[:, left_site, 2] - u.scene.terrain.env_origins[:, 2]
        stance = float(z0.median())

        act = torch.zeros((args.envs, 14), device=u.device)
        for name, val in offsets.items():
            act[:, LEFT[name]] = val
        # Only the left leg is scripted; the right leg holds its default target so
        # the robot keeps a support foot. This is the same asymmetry the gait uses.
        peak_l = peak_r = 0.0
        rise = 0.0
        up_min = 1.0
        for k in range(n_steps):
            u.step(act)
            fz = robot.data.site_pos_w[:, :, 2] - origin_z
            peak_l = max(peak_l, float(fz[:, left_site].median()))
            peak_r = max(peak_r, float(fz[:, right_site].median()))
            if k == half_steps:
                rise = float(fz[:, left_site].median())
            q = robot.data.root_link_quat_w
            w, x, y, z = q.unbind(-1)
            up = float((1.0 - 2.0 * (x * x + y * y)).median())
            up_min = min(up_min, up)
        print(f"{label:<38}{stance * 1000:>8.2f}m{peak_l * 1000:>8.2f}m"
              f"{peak_r * 1000:>8.2f}m{rise * 1000:>12.2f}m{up_min:>9.3f}")

    print("\nlegend: 'stance' = foot height before the step; peak = max held for "
          ">=50% of envs.\n        'rise@0.435s' = height one swing half-cycle in. "
          "up must stay > 0.9.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
