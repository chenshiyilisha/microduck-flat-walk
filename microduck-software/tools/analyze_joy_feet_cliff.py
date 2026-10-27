"""Is `joy_foot_rhythm` climbable, or is there a gradient barrier at the stance pose?

The reward is

    target_foot(t) = 0.0005 + 0.024 * relu(+/- sin p)^2      [m]
    r              = prod_feet exp(-((z_foot - target_foot) / 0.009)^2)

The foot site rests at 5.7 mm. The commanded peak is 24.5 mm. Equal weights on
both feet, alternating phase.

A reward that only pays off near 24 mm is useless as a bootstrap signal: the
policy has to cross ~15 mm of "no reward" to reach it, and standing still is a
stable local optimum at every point along the way. This script prints the reward
*cuvve* and its *marginal slope* so the barrier is a number rather than a story.

`lift` is expressed as the extra height above the rest pose, in mm, so the x-axis
is something a servo can actually be asked for.
"""

from __future__ import annotations

import math

FREQ_HZ = 1.15
SIGMA = 0.009
AMP = 0.024
FLOOR = 0.0005
FOOT_REST = 0.0057


def mean_reward(peak_lift_mm: float, samples: int = 40000) -> float:
    """Cycle-mean reward when the foot tracks `peak_lift_mm` above rest at its peak.

    The tracking law is the same one used in `analyze_joy_feet_floor.py`: the
    foot goes from rest (at the trough) to rest + peak_lift (at the peak),
    following the command shape scaled so the peak reaches `peak_lift_mm`.
    """
    amp = peak_lift_mm / 1000.0
    total = 0.0
    for i in range(samples):
        p = 2 * math.pi * i / samples
        s = math.sin(p)
        t_l = FLOOR + AMP * max(s, 0.0) ** 2
        t_r = FLOOR + AMP * max(-s, 0.0) ** 2
        # commanded shape, normalised to unit peak, then scaled to the achieved peak
        shape_l = max(s, 0.0) ** 2
        shape_r = max(-s, 0.0) ** 2
        a_l = FOOT_REST + amp * shape_l
        a_r = FOOT_REST + amp * shape_r
        e_l = (a_l - t_l) / SIGMA
        e_r = (a_r - t_r) / SIGMA
        total += math.exp(-e_l * e_l) * math.exp(-e_r * e_r)
    return total / samples


def main() -> None:
    print(f"rest {FOOT_REST*1000:.1f} mm | commanded peak {AMP*1000:.1f} mm | sigma {SIGMA*1000:.0f} mm")
    print(f"trough target {FLOOR*1000:.1f} mm is {(FOOT_REST-FLOOR)*1000:.1f} mm BELOW the rest pose\n")

    grid = [i for i in range(0, 25, 1)]
    vals = {g: mean_reward(g) for g in grid}

    print(f"{'peak lift':>10}{'reward':>10}{'gain vs prev':>15}{'weight-12 dR':>15}")
    print("-" * 52)
    prev = None
    for g in grid:
        v = vals[g]
        d = "" if prev is None else f"{(v-prev):+.5f}"
        dw = "" if prev is None else f"{(v-prev)*12:+.4f}"
        print(f"{g:>8} mm{v:>10.4f}{d:>15}{dw:>15}")
        prev = v

    print()
    # Where is the gradient best?  This is the slope the policy feels at each height.
    best_g, best_slope = None, -1.0
    for g in grid[:-1]:
        s = vals[g + 1] - vals[g]
        if s > best_slope:
            best_g, best_slope = g, s
    print(f"最大边际斜率出现在 {best_g}-{best_g+1} mm 之间: "
          f"每毫米 +{best_slope:.5f} 原始分 (= 权重 12 下 +{best_slope*12:.4f} 分)")
    print(f"0→5 mm 区间的总回报: {vals[5]-vals[0]:+.5f} "
          f"(权重 12 下 {(vals[5]-vals[0])*12:+.4f} 分)  <- 前 5 mm 几乎白给")
    print(f"15→24 mm 区间: {vals[24]-vals[15]:+.5f} "
          f"(权重 12 下 {(vals[24]-vals[15])*12:+.4f} 分)  <- 大部分回报在这里")
    print(f"0→24 mm 全程: {vals[24]-vals[0]:+.5f} "
          f"(权重 12 下 {(vals[24]-vals[0])*12:+.4f} 分)")

    print("\n对照: `mdp.feet_air_time`（二值计数，接触一断就给分）")
    print("  它不关心脚抬多高，只关心 `current_air_time > 0`。")
    print("  所以决定它有没有梯度的唯一问题是: **抬多少毫米会断接触**。")


if __name__ == "__main__":
    main()
