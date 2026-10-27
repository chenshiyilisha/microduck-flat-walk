"""What does `joy_foot_rhythm` actually pay, as a function of how high the foot goes?

The reward is

    target(t) = floor + amp * relu(sin p)^2     (per foot, alternating)
    actual(t) = foot site z above terrain
    r         = prod_over_feet exp(-((actual - target)/sigma)^2)

A foot site on MicroDuck rests at z = 5.7 mm (measured, 4 envs, play cfg), but the
upstream `floor` is 0.5 mm.  So the stance pose already collects most of the term --
which removes the incentive to lift a foot at all.

This integrates one full phase cycle for a family of "lift fraction" policies and
reports the cycle-mean reward, so the hand-waving becomes a number.
"""
from __future__ import annotations

import math

FREQ_HZ = 1.15
SIGMA = 0.009
AMP = 0.024
FOOT_REST = 0.0057  # measured: site_pos_w z - terrain origin, standing
FLOOR_UPSTREAM = 0.0005


def cycle_mean(floor: float, lift_frac: float, samples: int = 20000) -> float:
    """Mean reward over one period.

    `lift_frac` = how much of the commanded lift height the feet actually achieve,
    as a fraction of (target - FOOT_REST).  0 = rigid stance, 0.5 = half-way,
    1.0 = perfect tracking.
    """
    total = 0.0
    for i in range(samples):
        p = 2 * math.pi * i / samples
        s = math.sin(p)
        # Left foot commanded on the positive half, right foot on the negative half.
        t_left = floor + AMP * max(s, 0.0) ** 2
        t_right = floor + AMP * max(-s, 0.0) ** 2
        # The policy lifts toward its target, proportionally.
        a_left = FOOT_REST + lift_frac * (t_left - FOOT_REST)
        a_right = FOOT_REST + lift_frac * (t_right - FOOT_REST)
        e_l = (a_left - t_left) / SIGMA
        e_r = (a_right - t_right) / SIGMA
        total += math.exp(-e_l * e_l) * math.exp(-e_r * e_r)
    return total / samples


def main() -> None:
    print(f"foot rest height = {FOOT_REST*1000:.1f} mm, sigma = {SIGMA*1000:.0f} mm, "
          f"amp = {AMP*1000:.1f} mm\n")
    print(f"{'policy':<34}{'floor=0.5mm':>14}{'floor=5.7mm':>14}{'delta':>10}")
    print("-" * 72)
    for label, frac in (
        ("静止站桩 (lift 0%)", 0.0),
        ("抬到目标的 25%", 0.25),
        ("抬到目标的 50%", 0.50),
        ("抬到目标的 75%", 0.75),
        ("完美跟随 (lift 100%)", 1.0),
    ):
        a = cycle_mean(FLOOR_UPSTREAM, frac)
        b = cycle_mean(FOOT_REST, frac)
        print(f"{label:<30}{a:>16.4f}{b:>16.4f}{b-a:>+10.4f}")

    print()
    a0 = cycle_mean(FLOOR_UPSTREAM, 0.0)
    a1 = cycle_mean(FLOOR_UPSTREAM, 1.0)
    b0 = cycle_mean(FOOT_REST, 0.0)
    b1 = cycle_mean(FOOT_REST, 1.0)
    print(f"上游基准 (floor=0.5mm): 站桩 {a0:.4f} -> 完美 {a1:.4f}   "
          f"差距 {(a1-a0)*12:+.2f} 分 (权重 12)")
    print(f"修正基准 (floor=5.7mm): 站桩 {b0:.4f} -> 完美 {b1:.4f}   "
          f"差距 {(b1-b0)*12:+.2f} 分 (权重 12)")
    print(f"\n修正后站桩白拿的分数下降 {(a0-b0)*12:.2f} 分，"
          f"而满分的绝对高度不变 -> 踏步的边际收益变大")
    print(f"\n参考：实测 raw 约 0.469 (2048envs 训练日志 joy_feet 5.63/12)")
    print(f"      站桩理论值 floor=0.5mm -> {a0:.4f}，与实测同量级")


if __name__ == "__main__":
    main()
