"""How much foot height does one sigma of action noise actually buy?

The joy_foot_rhythm reward is `exp(-((z - z_target)/9mm)^2)`. That is a very
narrow kernel: perturbing foot height by 9 mm costs 63% of the term. PPO
optimises the *expectation* over exploration noise, and the expected value of a
concave function under noise is pulled below its peak -- so if one sigma of joint
noise moves the foot by a comparable number of millimetres, the gap between
"standing" and "tracking perfectly" can be almost entirely washed out during
training (even though eval, which uses the mean action, still shows a gap).

This script measures that mapping directly instead of assuming it:
  joint noise (rad)  ->  foot height noise (mm)

Method: reset, then write joint positions = nominal + N(0, sigma^2) into the sim,
mj_forward, read foot site heights. Pure kinematics -- no PD, no contact. That is
the right level for this question because the reward is evaluated on the resulting
pose, and because it lets us sweep sigma without training anything.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigmas", type=float, nargs="+",
                    default=[0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.52, 0.60])
    ap.add_argument("--samples", type=int, default=4000)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import torch
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.tasks.registry import load_env_cfg
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()
    cfg = load_env_cfg("Mjlab-JoySmoothPD-Flat-MicroDuck", play=False)
    n = args.samples
    cfg.scene.num_envs = n
    env = ManagerBasedRlEnv(cfg=cfg, device=args.device)
    env.reset()
    robot = env.scene["robot"]

    site_names = [s.name for s in robot.spec.sites]
    foot_idx = [i for i, nm in enumerate(site_names) if "foot" in nm]
    joint_names = [j.name for j in robot.spec.joints if "freejoint" not in j.name]
    print(f"feet={ [site_names[i] for i in foot_idx] }  joints={len(joint_names)}")

    origin_z = env.scene.terrain.env_origins[:, None, 2]

    def read_foot_z() -> np.ndarray:
        return (robot.data.site_pos_w[:, foot_idx, 2] - origin_z).cpu().numpy()

    base_q = robot.data.joint_pos.clone()  # [n, 14]
    rest = read_foot_z()
    print(f"\nrest foot z: mean {rest.mean()*1000:.2f} mm  "
          f"(min {rest.min()*1000:.2f}, max {rest.max()*1000:.2f})")

    rows = []
    for sigma in args.sigmas:
        torch.manual_seed(0)
        noise = torch.randn_like(base_q) * sigma
        robot.write_joint_position_to_sim(base_q + noise)
        env.sim.forward()
        z = read_foot_z()
        # Per-env std across the two feet of the same perturbation, then average.
        d = z - rest
        rows.append({
            "sigma_rad": sigma,
            "foot_z_std_mm": float(d.std(axis=0).mean() * 1000.0),
            "abs_foot_dev_mm": float(np.abs(d).mean() * 1000.0),
        })

    robot.write_joint_position_to_sim(base_q)
    env.sim.forward()
    env.close()

    # Now propagate that foot-noise into the actual reward kernel.
    # Expected value of exp(-((z + eps - t)/9mm)^2) for eps ~ N(0, s^2),
    # evaluated at the reward's own peak (z = t) -- i.e. the best case a policy
    # could achieve in expectation.
    SIGMA_R = 0.009

    def expected_kernel(foot_std_mm: float) -> float:
        """E[exp(-(eps/9mm)^2)] for eps ~ N(0, std^2). Closed form for a Gaussian."""
        s = foot_std_mm / 1000.0
        if s <= 0:
            return 1.0
        # E[exp(-eps^2/(2a^2))] with a = SIGMA_R/sqrt(2) -> 1/sqrt(1+2 s^2/SIGMA_R^2)
        return 1.0 / math.sqrt(1.0 + 2.0 * (s / SIGMA_R) ** 2)

    # Baseline: what a perfect tracker would score *in expectation* vs a static
    # stander (foot stays at rest height while the target swings 0.5..24.5 mm).
    def standing_expected(foot_std_mm: float, rest_m: float) -> float:
        """Average over one gait cycle of E[kernel] when the foot never lifts."""
        s = foot_std_mm / 1000.0
        amp, floor = 0.024, 0.0005
        tot = 0.0
        N = 720
        for i in range(N):
            ph = 2.0 * math.pi * i / N
            t = floor + amp * max(math.sin(ph), 0.0) ** 2  # one foot's target
            mu = rest_m - t                            # standing offset from target
            # E[exp(-((mu+eps)/SIGMA_R)^2)] for a Gaussian offset -- numerically,
            # since mu is not zero here.
            acc = 0.0
            for k in range(-30, 31):
                e = k * s / 6.0
                w = math.exp(-0.5 * (e / s) ** 2) if s > 0 else (1.0 if k == 0 else 0.0)
                acc += w * math.exp(-((mu + e) / SIGMA_R) ** 2)
            norm = sum(math.exp(-0.5 * (k * s / 6.0 / s) ** 2)
                       for k in range(-30, 31)) if s > 0 else 1.0
            tot += acc / norm
        return tot / N

    rest_m = float(rest.mean())
    print("\n" + "=" * 78)
    print(f"{'sigma(rad)':>11}{'foot std(mm)':>14}{'E@peak':>10}"
          f"{'E@stand':>10}{'gap':>9}{'gap*12':>10}")
    print("-" * 78)
    out_rows = []
    for r in rows:
        std = r["foot_z_std_mm"]
        e_peak = expected_kernel(std)
        e_stand = standing_expected(std, rest_m)
        gap = e_peak - e_stand
        out_rows.append({**r, "E_peak": e_peak, "E_stand": e_stand,
                         "gap": gap, "gap_weighted": gap * 12.0})
        print(f"{r['sigma_rad']:>11.2f}{std:>14.2f}{e_peak:>10.3f}"
              f"{e_stand:>10.3f}{gap:>9.3f}{gap*12.0:>10.2f}")

    print("=" * 78)
    print("E@peak  = best achievable expected reward fraction if the policy aims")
    print("          exactly at the target (1.0 with no noise).")
    print("E@stand = same for a policy that never lifts a foot.")
    print("gap*12  = how many of the 12 joy_feet points separate those two, in")
    print("          expectation, during training. Shrinking gap = unlearnable.")

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"rest_foot_z_m": rest_m, "rows": out_rows},
                                indent=1), encoding="utf-8")
        print(f"\n-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
