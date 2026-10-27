"""Is the policy *stepping* (alternating) or *standing on one leg*?

Why this exists
---------------
`eval_curric_400` came back with `feet_peak_left_m = 24.5 mm` but
`feet_peak_right_m = 5.8 mm`. Seven earlier versions had both feet at ~5.3 mm,
so one leg learned the lift. But a per-foot window peak cannot tell these apart:

    alternating gait   left high while sin(p) > 0, right high while sin(p) < 0
    one-leg stance     left held up for the whole cycle, right bearing weight

Both produce a high left peak. The gate's `min(left, right)` fails either way,
but the fixes are opposite: alternating means the clock is being tracked and
only the right leg lags (keep training / fix the asymmetry); one-leg stance
means the policy parks a leg in the air and the clock is irrelevant (the
control problem is wrong).

So: bin foot height by gait phase and look at the shape.

    phase-locked sine      -> alternating gait
    flat high / flat low   -> one-leg stance (or a frozen leg)

Also reports the correlation between foot height and sin(phase), which is the
single number that separates the two: |r| high = locked to the clock.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/probe_phase_profile.py \
        --checkpoint logs/rsl_rl/microduck_joy_smooth/<run>/model_400.pt
"""

from __future__ import annotations

import argparse
import math
from dataclasses import asdict

import torch

TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"
FREQ = 1.15
STANCE = 0.0005
NBIN = 24


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--envs", type=int, default=64)
    ap.add_argument("--seconds", type=float, default=6.0)
    args = ap.parse_args()

    import mjlab_microduck.tasks  # noqa: F401
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.managers.scene_entity_config import SceneEntityCfg
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()

    env_cfg = load_env_cfg(TASK, play=False)
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
    robot = u.scene["robot"]
    origin_z = u.scene.terrain.env_origins[:, None, 2]

    obs, _ = env.reset()
    zs, phases = [], []
    for _ in range(n_steps):
        with torch.no_grad():
            act = policy(obs)
        obs, _rew, _d, _e = env.step(act)
        h = (robot.data.site_pos_w[:, foot_cfg.site_ids, 2] - origin_z - STANCE) * 1000
        zs.append(h.clone())
        phases.append(u.episode_length_buf.to(torch.float32) * step_dt)

    h_all = torch.stack(zs)                       # [T, N, 2] mm
    ph = (torch.stack(phases) * FREQ) % 1.0       # [T, N] in cycles
    bin_id = (ph * NBIN).long().clamp(0, NBIN - 1)

    print(f"\ncheckpoint {args.checkpoint.split('/')[-1]}   {args.envs} envs x {n_steps} steps"
          f"   ({n_steps * step_dt:.1f} s, {n_steps * step_dt * FREQ:.1f} cycles)\n")

    # mean height per phase bin, averaged over envs
    prof = torch.zeros(NBIN, 2)
    cnt = torch.zeros(NBIN)
    for b in range(NBIN):
        m = bin_id == b
        if bool(m.any()):
            prof[b] = h_all[m].mean(0).cpu()
            cnt[b] = m.sum()
    print("=== mean foot height (mm) by gait phase ===")
    print(f"{'phase':>7}{'left':>9}{'right':>9}")
    for b in range(NBIN):
        p = (b + 0.5) / NBIN
        bar_l = "#" * int(prof[b, 0] / 1.2)
        bar_r = "#" * int(prof[b, 1] / 1.2)
        print(f"{p:>7.2f}{prof[b, 0]:>9.2f}{prof[b, 1]:>9.2f}   {bar_l:<22}|{bar_r}")

    # the number that separates stepping from one-leg stance
    s = torch.sin(2 * math.pi * ph).cpu().reshape(-1)
    print("\n=== phase locking (corr of foot height with sin(phase)) ===")
    for f, name in enumerate(("left", "right")):
        v = h_all[:, :, f].cpu().reshape(-1)
        sv = v.std()
        r = float(((s - s.mean()) * (v - v.mean())).mean() / (s.std() * sv + 1e-9))
        print(f"  {name:<6} mean {float(v.mean()):6.2f} mm   sd {float(sv):5.2f} mm   "
              f"r={r:+.3f}   p2p {float(v.max() - v.min()):6.2f} mm")

    l_mean, r_mean = prof.mean(0).tolist()
    l_sd, r_sd = prof[:, 0].std().item(), prof[:, 1].std().item()
    print("\n=== verdict ===")
    print(f"  phase-profile sd:  left {l_sd:5.2f} mm   right {r_sd:5.2f} mm"
          "   (near 0 = a flat line = not stepping)")
    print(f"  dc offset:         left {l_mean:5.2f} mm   right {r_mean:5.2f} mm")
    if min(l_sd, r_sd) < 2.0:
        print("  -> at least one foot is FLAT across the cycle: one-leg stance / frozen leg,")
        print("     not an alternating gait. The phase clock is not being tracked.")
    else:
        print("  -> both feet vary with phase: an alternating gait is being tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
