"""Closed-loop probe: add a bias to the policy's knee command and see what happens.

Why this exists
---------------
`probe_openloop_lift.py` scripted the joints directly and every case fell over
(`upright` 0.42-0.71 against a > 0.9 requirement), so its foot heights are
contaminated by trunk tilt. That probe answered the wrong question: it asked
"can the *joints* move that far" (yes, the FK sweep already said 115 mm is
kinematically reachable) instead of "can the *policy* lift a foot without
falling".

The two remaining hypotheses need different fixes and this separates them:

    H1  the policy can balance through a lift but has no incentive to command
        one -- fix is the reward / a curriculum on the target height
    H2  the policy cannot balance through a lift at all, because a 0.6 rad knee
        excursion tips the trunk past what the support leg can absorb -- fix is
        a curriculum that grows the lift from 2 mm, or a two-leg coordinated
        reference the explorer can actually stumble onto

Method: run the trained policy normally and add a constant bias to only the
left knee channel of its action. The policy still sees the resulting state and
still tries to stay upright, so `upright` here measures the *controller's* margin,
not the absence of one. If `upright` holds above 0.9 while the left foot rises
past 15 mm, H1. If `upright` collapses as soon as the bias is nonzero, H2.

Note the conditioner is still in the path (`joy_alpha=0.25`, `joy_max_step=0.08`),
so a 0.6 rad bias arrives as a ~0.08 rad/step ramp -- the deployed ramp.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/probe_policy_bias_lift.py \
        --checkpoint logs/rsl_rl/microduck_joy_smooth/<run>/model_599.pt
"""

from __future__ import annotations

import argparse
import pathlib
from dataclasses import asdict

import torch

TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"

# Action columns come straight from the MJCF actuator order (robot_walk.xml):
#   0 left_hip_yaw 1 left_hip_roll 2 left_hip_pitch 3 left_knee 4 left_ankle
#   5 neck_pitch   6 head_pitch    7 head_yaw       8 head_roll
#   9 right_hip_yaw 10 right_hip_roll 11 right_hip_pitch 12 right_knee 13 right_ankle
ACTION_COLS = {
    "left_knee": 3, "left_hip_pitch": 2, "left_hip_roll": 1,
    "right_knee": 12, "right_hip_pitch": 11, "right_hip_roll": 10,
}
LEFT_KNEE = ACTION_COLS["left_knee"]  # kept for callers that predate --joint


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--envs", type=int, default=16)
    ap.add_argument("--joint", default="left_knee", choices=sorted(ACTION_COLS),
                    help="which action channel to bias. Biasing the RIGHT knee asks "
                         "the question the left-knee sweep could not: can this policy "
                         "hand support over to the left leg, or does it only know how "
                         "to keep the right leg planted?")
    ap.add_argument("--no-gait-clock", action="store_true",
                    help="drop the +2 gait_clock observation so checkpoints trained "
                         "before tools/patch_joy_gait_clock.py still load (their actor "
                         "input is 2 dims narrower and strict load would fail)")
    args = ap.parse_args()

    import mjlab_microduck.tasks  # noqa: F401
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(TASK, play=False)
    if args.no_gait_clock:
        for g in ("actor", "critic"):
            env_cfg.observations[g].terms.pop("gait_clock", None)
    agent_cfg = load_rl_cfg(TASK)
    env_cfg.scene.num_envs = args.envs
    raw = ManagerBasedRlEnv(cfg=env_cfg, device=args.device)
    env = RslRlVecEnvWrapper(raw, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(TASK) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=args.device)
    runner.load(args.checkpoint, load_cfg={"actor": True}, strict=True,
                map_location=args.device)
    policy = runner.get_inference_policy(device=args.device)

    u = env.unwrapped
    step_dt = float(u.step_dt)
    n_steps = int(round(args.seconds / step_dt))
    foot_cfg = SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])
    foot_cfg.resolve(u.scene)
    left_site, right_site = foot_cfg.site_ids
    robot = u.scene["robot"]

    print(f"checkpoint {pathlib.Path(args.checkpoint).name}   "
          f"{1 / step_dt:.0f} Hz   {n_steps} steps   {args.envs} envs   "
          f"bias on {args.joint} (col {ACTION_COLS[args.joint]})\n")
    col = ACTION_COLS[args.joint]
    print(f"{'bias (rad)':>11}{'biased foot':>13}{'other foot':>12}"
          f"{'upright med':>13}{'upright min':>13}{'fell':>7}")
    print("-" * 70)

    for bias in (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
        obs, _ = env.reset()
        origin_z = u.scene.terrain.env_origins[:, None, 2]
        fz_hist, up_hist = [], []
        fell = False
        for _ in range(n_steps):
            with torch.no_grad():
                act = policy(obs)
            act = act.clone()
            act[:, col] += bias
            obs, _rew, dones, extras = env.step(act)
            # Index the two foot sites explicitly. Slicing `site_pos_w[..., 2]`
            # wholesale gives all 7 sites (imu, left_foot, head_camera, tof,
            # head_imu, mouth_tip, right_foot), and column 0 is the *imu* at
            # ~104 mm -- which reads as a 104 mm "foot" and looks like a result.
            fz = robot.data.site_pos_w[:, foot_cfg.site_ids, 2] - origin_z
            fz_hist.append(fz.clone())
            q = robot.data.root_link_quat_w
            w, x, y, z = q.unbind(-1)
            up = 1.0 - 2.0 * (x * x + y * y)
            up_hist.append(up.clone())
            timeouts = extras.get("time_outs")
            if timeouts is not None:
                fell = fell or bool((dones.bool() & ~timeouts.bool()).any())
            else:
                fell = fell or bool(dones.any())
        fz_all = torch.stack(fz_hist)          # [T, N, 2]
        up_all = torch.stack(up_hist)          # [T, N]
        biased = 0 if args.joint.startswith("left") else 1
        other = 1 - biased
        print(f"{bias:>11.2f}{float(fz_all[:, :, biased].max()) * 1000:>12.2f}m"
              f"{float(fz_all[:, :, other].mean()) * 1000:>11.2f}m"
              f"{float(up_all.median()):>13.3f}{float(up_all.min()):>13.3f}"
              f"{str(fell):>7}")

    print("\nread it as: if 'upright med' stays > 0.9 and 'foot peak' climbs past "
          "15 mm,\n            the policy can already balance through a lift (H1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
