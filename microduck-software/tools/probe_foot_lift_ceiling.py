"""What is the *kinematic* ceiling on foot lift, given the 4.0 rad/s step clamp?

Why this exists
---------------
Four reward variants (pointwise 9 mm, pointwise 18 mm, running-peak, official
trio) all landed at 5.3-5.7 mm of foot lift on `joy_smooth`. Before spending
another 40 min of training on a fifth variant, measure what is *physically*
reachable, so the next experiment targets a number that exists.

The arithmetic that motivated this
----------------------------------
`conditioner.joy_max_step = 0.08 rad @ 50 Hz` caps every joint at 4.0 rad/s.
A symmetric swing that must go out and come back within a half-cycle of the
1.15 Hz clock (0.435 s) therefore has |dq| <= 4.0 * 0.435 / 2 = 0.870 rad.
The earlier pure-knee estimate (8.8 mm) assumed that symmetric profile.

But 0.870 is only the *symmetric* budget. A monotone out-and-then-fall-profile
can spend the whole half-cycle rising: |dq| <= 4.0 * 0.435 = 1.74 rad. And a
stride that gives the swing foot more than half the cycle gets more still.
So the ceiling is a function of the assumed budget; this script reports it as
a curve instead of one number.

Measurement convention (this is the part that is easy to get wrong)
------------------------------------------------------------------
Height must be measured **relative to the support foot**, not as an absolute
site z. The trunk height is set by the support leg; changing the swing leg's
joints barely moves the trunk, so comparing absolute z of the swing foot before
and after is fine *only if the support leg is untouched*. It is, here. But the
stance-vs-swing difference is what `joy_foot_rhythm` actually grades (it uses
`site_pos_w[:, :, 2] - env_origins[:, :, 2]`, and both feet rest on the same
ground), so we report `z_left(q) - z_left(HOME)` and cross-check it against
`(z_left(q) - z_right(HOME)) - (z_left(HOME) - z_right(HOME))`. Those two are
identical by construction when the right leg is held at HOME -- the assert below
enforces that instead of trusting it.

Joint limits bite hard and non-obviously
----------------------------------------
`hip_roll` is limited to +-0.3840 rad. HOME already sits at -0.0873, so from
HOME the lift-relevant travel is +0.471 up / -0.297 down -- roughly half the
0.870 symmetric budget and a quarter of the 1.74 monotone budget. Any plan that
leans on abduction is capped by the limit, not by the servo.
"""

from __future__ import annotations

import itertools
import pathlib

import mujoco
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
XML = (ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/robot/microduck/"
       "robot_walk.xml")

# HOME/JOINT_POS from microduck_constants.py HOME_FRAME (STAND2 pose).
HOME = {
    "left_hip_yaw": 0.0, "left_hip_roll": -0.0873, "left_hip_pitch": -0.4579,
    "left_knee": -0.0049, "left_ankle": 0.4530,
    "right_hip_yaw": 0.0, "right_hip_roll": 0.0873, "right_hip_pitch": 0.4579,
    "right_knee": 0.0049, "right_ankle": -0.4530,
    "neck_pitch": 0.3491, "head_pitch": 0.3491, "head_yaw": 0.0, "head_roll": 0.0,
}
# Trunk stands at the HOME height; it is held fixed so the sweep measures the
# swing leg alone. Free-joint quat is wxyz and identity = upright.
TRUNK_Z = 0.117
LEG_JOINTS = ["left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle"]


def build():
    m = mujoco.MjModel.from_xml_path(str(XML))
    d = mujoco.MjData(m)
    jid = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i): i for i in range(m.njnt)}
    sid = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i): i for i in range(m.nsite)}
    return m, d, jid, sid


def foot_z(m, d, jid, sid, q):
    """Absolute site z of both feet for joint dict `q` (trunk fixed at TRUNK_Z)."""
    d.qpos[:] = 0.0
    d.qpos[0:3] = (0.0, 0.0, TRUNK_Z)
    d.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
    full = dict(HOME)
    full.update(q)
    for name, val in full.items():
        d.qpos[m.jnt_qposadr[jid[name]]] = val
    mujoco.mj_kinematics(m, d)
    return d.site_xpos[sid["left_foot"]][2], d.site_xpos[sid["right_foot"]][2]


def lift_mm(m, d, jid, sid, q):
    """Foot lift relative to the support (right) foot, in mm, vs HOME."""
    zl, zr = foot_z(m, d, jid, sid, q)
    zl0, zr0 = foot_z(m, d, jid, sid, {})
    return (zl - zr - (zl0 - zr0)) * 1000.0


def _within_limits(m, jid, combo):
    return all(m.jnt_range[jid[j], 0] <= HOME[j] + dq <= m.jnt_range[jid[j], 1]
               for j, dq in zip(LEG_JOINTS, combo))


def search(m, d, jid, sid, budget: float = 1e9, centre=None, step: float = 0.20):
    """Best foot lift over a coarse grid, refined around the winner.

    A dense 4-D product (0.05 rad x 4 joints) is 1.2e8 kinematics calls, which
    is ~20 min of wall clock for a number that only needs 2 significant digits.
    Coarse-then-refine gets the same answer in seconds: 0.20 rad grid (27^4) to
    find the basin, then 0.02 rad inside +-0.20 of it (21^4).
    """
    def scan(grids, best):
        for combo in itertools.product(*grids):
            if max(abs(x) for x in combo) > budget + 1e-9:
                continue
            if not _within_limits(m, jid, combo):
                continue
            q = {j: HOME[j] + dq for j, dq in zip(LEG_JOINTS, combo)}
            v = lift_mm(m, d, jid, sid, q)
            if v > best[0]:
                best = (v, combo)
        return best

    if centre is None:
        grids = [np.arange(-2.6, 2.601, step)] * len(LEG_JOINTS)
        best = scan(grids, (-1e9, None))
        if best[1] is None:
            return None
        coarse = best
        centre = best[1]
    else:
        coarse = (-1e9, None)
    grids = [np.arange(c - 0.20, c + 0.2001, 0.02) for c in centre]
    best = scan(grids, coarse)  # keep the coarse winner as the floor
    if best[1] is None:
        return None
    return best


def min_travel_for(m, d, jid, sid, target_mm: float, hi: float = 3.0) -> float | None:
    """Smallest `max|dq_i|` budget whose best lift reaches `target_mm`.

    Lift is monotone in the budget (a looser box contains every tighter one), so
    this is a 6-step bisection at 0.02 rad resolution -- enough to say whether a
    target sits inside the 0.870 / 1.740 service budgets.
    """
    top = search(m, d, jid, sid, budget=hi)
    if top is None or top[0] < target_mm:
        return None
    lo = 0.0
    for _ in range(6):
        mid = 0.5 * (lo + hi)
        got = search(m, d, jid, sid, budget=mid)
        if got is not None and got[0] >= target_mm:
            hi = mid
        else:
            lo = mid
    return hi


def main() -> int:
    m, d, jid, sid = build()
    zl0, zr0 = foot_z(m, d, jid, sid, {})
    print(f"trunk z={TRUNK_Z}  HOME left_foot z={zl0:.5f}  right_foot z={zr0:.5f}")
    print(f"HOME foot-height difference = {(zl0 - zr0) * 1000:+.3f} mm\n")

    # Cross-check the convention: holding the right leg at HOME must make the
    # absolute-z delta and the support-relative delta identical.
    probe = {"left_knee": HOME["left_knee"] - 0.5}
    abs_d = (foot_z(m, d, jid, sid, probe)[0] - zl0) * 1000
    rel_d = lift_mm(m, d, jid, sid, probe)
    print(f"convention check (left_knee -0.5): absolute={abs_d:+.4f} mm  "
          f"support-relative={rel_d:+.4f} mm")
    assert abs(abs_d - rel_d) < 1e-6, "support-relative != absolute with right leg at HOME"
    print("  -> identical, as required\n")

    # ---- 1. single-joint curves: how much lift does each joint buy, and over
    # what travel? Answer is "the lift is not monotone in the joint" for knee,
    # which is exactly why a reward centred on 24 mm never fired.
    print("=" * 72)
    print("1. single-joint sweep (mm of lift vs travel from HOME)")
    print("=" * 72)
    for j in LEG_JOINTS:
        lo, hi = (float(m.jnt_range[jid[j], 0]), float(m.jnt_range[jid[j], 1]))
        print(f"\n{j}: limit [{lo:+.4f}, {hi:+.4f}]  HOME {HOME[j]:+.4f}  "
              f"travel_down {HOME[j] - lo:+.4f}  travel_up {hi - HOME[j]:+.4f}")
        best = (-1e9, None)
        for dq in np.arange(-1.6, 1.601, 0.05):
            q = HOME[j] + dq
            if not (lo <= q <= hi):
                continue
            v = lift_mm(m, d, jid, sid, {j: q})
            if v > best[0]:
                best = (v, dq)
            if abs(dq * 100) % 20 < 1e-6:
                print(f"    dq={dq:+.2f} rad -> {v:+8.3f} mm")
        print(f"    BEST within limit: {best[0]:+.3f} mm at dq={best[1]:+.2f} rad")

    # ---- 2. the ceiling under a travel budget. Grid over all four joints, keep
    # the best lift subject to max|dq_i| <= budget.
    print("\n" + "=" * 72)
    print("2. best lift from a 4-joint grid, subject to max|dq_i| <= budget")
    print("=" * 72)
    print("   budgets: 0.870 = symmetric swing inside a 0.435 s half cycle")
    print("            1.740 = monotone rise over the same half cycle")
    print("            2.610 = monotone rise over 75% of the 0.87 s stride")
    budgets = (0.870, 1.740, 2.610)
    for C in budgets:
        best = search(m, d, jid, sid, budget=C)
        if best is None:
            continue
        v, combo = best
        desc = "  ".join(f"{j.replace('left_', '')}{dq:+.2f}"
                         for j, dq in zip(LEG_JOINTS, combo))
        print(f"   budget {C:5.3f} rad -> ceiling {v:7.3f} mm   ({desc})")

    # ---- 3. what the reward actually asks for: 24 mm, and what the audit's
    # 18.5-20.0 mm PASS requires. Print the cheapest joint combo that reaches
    # each, so we can see whether it is even inside the limit box.
    print("\n" + "=" * 72)
    print("3. can 18 / 20 / 24 mm be reached at all (limit box only, no budget)?")
    print("=" * 72)
    grid2 = None  # replaced by the bisection below; a dense grid is too slow
    for target in (8.0, 12.0, 18.0, 20.0, 24.0):
        need = min_travel_for(m, d, jid, sid, target)
        if need is None:
            print(f"   target {target:5.1f} mm -> UNREACHABLE inside joint limits")
        else:
            verdict = ("inside the 0.870 symmetric budget" if need <= 0.870 else
                       "needs the 1.740 monotone budget" if need <= 1.740 else
                       "needs >75% of the stride as swing time")
            print(f"   target {target:5.1f} mm -> needs max|dq| >= {need:.2f} rad  "
                  f"({verdict})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
