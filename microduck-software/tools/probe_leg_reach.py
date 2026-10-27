"""Can the foot rise 20 mm straight up? Exact FK, no training, no GPU.

Answers the question §29.8 called the cheapest decisive one: before asking why
the policy only reaches 6 mm, check whether 20 mm exists in the leg's reachable
set at all.

Why not simply maximise foot height over the joint box: that answer is useless.
Swinging the *straightened* leg to hip_pitch=90 deg lifts the toe ~189 mm while
sliding it 100 mm through space. Nothing about that is a step. The joy task asks
for a foot that goes up and comes back down **near the same place**, so the real
question is a 2-D inverse-kinematics one:

    is there a (hip_pitch, knee, ankle) with
        dz = +20 mm   and   |dx| <= --max-dx ?

So this tool sweeps knee angle and, for each, finds the hip_pitch that pins the
foot's horizontal position, then reports the height that vertical column reaches.
That produces the curve "how much lift does a given knee bend buy, if the foot is
not allowed to travel" -- the only form of the answer that constrains a gait.

The §13 claim ("the knee is singular at the standing pose") is measured directly
as dz/dq at q=0. A near-zero slope means the first tens of degrees of knee
command buy almost nothing, which is exactly what a policy commanding 31 deg of
knee and getting 0.4 mm looks like.

Usage:
    ./.venv-mjlab/Scripts/python.exe tools/probe_leg_reach.py
    ./.venv-mjlab/Scripts/python.exe tools/probe_leg_reach.py --trunk-pitch 0.15
    ./.venv-mjlab/Scripts/python.exe tools/probe_leg_reach.py --max-dx 0.002
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np


XML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".venv-mjlab", "Lib", "site-packages", "mjlab_microduck",
    "robot", "microduck", "robot_groundcontact.xml",
)


def build_model():
    import mujoco

    return mujoco, mujoco.MjModel.from_xml_path(XML)


def name_id(mujoco, m, obj, name: str) -> int:
    i = mujoco.mj_name2id(m, obj, name)
    if i < 0:
        raise SystemExit(f"model has no {name}")
    return int(i)


def make_fk(mujoco, m, sid, qadr, trunk):
    d = mujoco.MjData(m)

    def f(hip_pitch, knee, ankle, *, pitch=0.0, roll=0.0, yaw=0.0):
        d.qpos[:] = m.qpos0
        d.qpos[0:3] = 0.0
        if pitch or roll:
            cy, sy = np.cos(pitch / 2), np.sin(pitch / 2)
            cr, sr = np.cos(roll / 2), np.sin(roll / 2)
            d.qpos[3], d.qpos[4] = cr * cy, sr * cy
            d.qpos[5], d.qpos[6] = cr * sy, -sr * sy
        else:
            d.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
        d.qpos[qadr["hip_yaw"]] = yaw
        d.qpos[qadr["hip_roll"]] = roll
        d.qpos[qadr["hip_pitch"]] = hip_pitch
        d.qpos[qadr["knee"]] = knee
        d.qpos[qadr["ankle"]] = ankle
        mujoco.mj_kinematics(m, d)
        rel = d.site_xpos[sid] - d.xpos[trunk]
        return float(rel[0]), float(rel[2])  # x forward, z up

    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", default="left", choices=["left", "right"])
    ap.add_argument("--trunk-pitch", type=float, default=0.0, help="radians, +nose-up")
    ap.add_argument("--trunk-roll", type=float, default=0.0, help="radians")
    ap.add_argument("--max-dx", type=float, default=0.005,
                    help="metres; horizontal tolerance allowed while lifting")
    ap.add_argument("--hip-limit-deg", type=float, default=30.0,
                    help="clamp on thigh swing; without it the sweep finds "
                         "degenerate fold-the-leg-onto-the-body poses")
    ap.add_argument("--xml", default=None,
                    help="robot xml; default is the joy/standup model. "
                         "Walking uses robot_walk.xml -- a different model.")
    ap.add_argument("--out", default="out/leg_reach.json")
    a = ap.parse_args()

    global XML
    if a.xml:
        XML = a.xml if os.path.isabs(a.xml) else os.path.abspath(a.xml)
    mujoco, m = build_model()
    sid = name_id(mujoco, m, mujoco.mjtObj.mjOBJ_SITE, f"{a.leg}_foot")
    jid = name_id(mujoco, m, mujoco.mjtObj.mjOBJ_JOINT, "trunk_base_freejoint")
    trunk = int(m.jnt_bodyid[jid])

    qadr, rng = {}, {}
    for j in ("hip_yaw", "hip_roll", "hip_pitch", "knee", "ankle"):
        jj = name_id(mujoco, m, mujoco.mjtObj.mjOBJ_JOINT, f"{a.leg}_{j}")
        qadr[j] = int(m.jnt_qposadr[jj])
        rng[j] = (float(m.jnt_range[jj][0]), float(m.jnt_range[jj][1]))

    fk = make_fk(mujoco, m, sid, qadr, trunk)
    tp, tr = a.trunk_pitch, a.trunk_roll
    x0, z0 = fk(0.0, 0.0, 0.0, pitch=tp, roll=tr)

    # ---- sensitivity at the standing pose -------------------------------------
    eps = 0.02
    mmdeg = 1e3 * np.pi / 180.0
    sens = {}
    for label, (dp, dk, da) in {
        "hip_pitch": (eps, 0.0, 0.0),
        "knee_pos": (0.0, +eps, 0.0),
        "knee_neg": (0.0, -eps, 0.0),
        "ankle_pos": (0.0, 0.0, +eps),
        "ankle_neg": (0.0, 0.0, -eps),
    }.items():
        _, z = fk(dp, dk, da, pitch=tp, roll=tr)
        sens[label] = float((z - z0) / eps * mmdeg)

    # ---- vertical column: pin dx, sweep knee, find best hip_pitch -------------
    # hip_pitch is clamped to a gait-plausible arc. Without that clamp the sweep
    # finds degenerate solutions: hip_pitch=86 deg with the knee folded 95 deg
    # puts the foot 84 mm *above* the trunk with dx unchanged -- a pose that
    # means folding the leg onto the body, not stepping. The clamp is the
    # statement "the thigh swings, it does not invert".
    knee_grid = np.radians(np.arange(-95.0, 40.0 + 1e-9, 5.0))
    hip_grid = np.radians(np.arange(-a.hip_limit_deg, a.hip_limit_deg + 1e-9, 1.0))
    ankle_grid = np.radians(np.arange(-40.0, 40.0 + 1e-9, 10.0))

    curve = []
    best_ok = (0.0, None)
    for k in knee_grid:
        col = None
        for an in ankle_grid:
            for p in hip_grid:
                x, z = fk(p, k, an, pitch=tp, roll=tr)
                if abs(x - x0) > a.max_dx:
                    continue
                dz = z - z0
                if col is None or dz > col[0]:
                    col = (dz, float(p), float(an))
        if col is not None:
            curve.append({"knee_deg": float(np.degrees(k)),
                          "max_lift_mm": col[0] * 1e3,
                          "hip_pitch_deg": float(np.degrees(col[1])),
                          "ankle_deg": float(np.degrees(col[2]))})
            if col[0] > best_ok[0]:
                best_ok = (col[0], (float(k), col[1], col[2]))

    # ---- smallest-action pose for exactly 20 mm -------------------------------
    # Among all poses that put the foot 20 mm up with dx inside tolerance, take
    # the one with the smallest joint displacement from standing. That is the
    # ask the reward implicitly makes; if it needs a 90 deg knee the ask is
    # unreasonable no matter how reachable it is geometrically.
    target = 0.020
    least = None
    for k in knee_grid:
        for an in ankle_grid:
            for p in hip_grid:
                x, z = fk(p, k, an, pitch=tp, roll=tr)
                if abs(x - x0) > a.max_dx:
                    continue
                if abs((z - z0) - target) > 0.002:
                    continue
                norm = float(np.degrees(np.hypot(np.hypot(p, k), an)))
                if least is None or norm < least[0]:
                    least = (norm, float(p), float(k), float(an))

    # ---- thresholds: smallest knee bend that clears each height ---------------
    thresh = {}
    for h in (0.008, 0.010, 0.015, 0.020, 0.025, 0.030, 0.040):
        hit = None
        for row in curve:
            if row["max_lift_mm"] >= h * 1e3:
                hit = row
                break
        thresh[f"{h*1e3:.0f}mm"] = {
            "reachable": hit is not None,
            "knee_deg": None if hit is None else hit["knee_deg"],
            "hip_pitch_deg": None if hit is None else hit["hip_pitch_deg"],
            "ankle_deg": None if hit is None else hit["ankle_deg"],
        }

    out = {
        "leg": a.leg,
        "trunk_pitch_deg": float(np.degrees(tp)),
        "trunk_roll_deg": float(np.degrees(tr)),
        "max_dx_m": a.max_dx,
        "hip_limit_deg": a.hip_limit_deg,
        "stand": {"x_mm": x0 * 1e3, "z_mm": z0 * 1e3},
        "best_lift_mm": best_ok[0] * 1e3,
        "best_deg": None if best_ok[1] is None else
        {"knee": float(np.degrees(best_ok[1][0])),
         "hip_pitch": float(np.degrees(best_ok[1][1])),
         "ankle": float(np.degrees(best_ok[1][2]))},
        "least_action_20mm": None if least is None else
        {"joint_norm_deg": least[0],
         "hip_pitch_deg": float(np.degrees(least[1])),
         "knee_deg": float(np.degrees(least[2])),
         "ankle_deg": float(np.degrees(least[3]))},
        "sensitivity_mm_per_deg": sens,
        "thresholds": thresh,
        "curve": curve,
        "joint_ranges_deg": {k: [float(np.degrees(x)) for x in v] for k, v in rng.items()},
        "verdict_20mm": bool(least is not None),
    }

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print(f"xml={os.path.basename(XML)}")
    print(f"leg={a.leg}  trunk pitch={np.degrees(tp):+.1f} roll={np.degrees(tr):+.1f} deg"
          f"  |dx|<={a.max_dx*1e3:.0f} mm")
    print(f"  foot at stand: x={x0*1e3:+.2f} mm  z={z0*1e3:+.2f} mm (relative to trunk)")
    print(f"  hip_pitch clamped to +/-{a.hip_limit_deg:.0f} deg (gait-plausible arc)")
    print(f"  reachable lift (vertical column) = {best_ok[0]*1e3:.2f} mm")
    if best_ok[1]:
        b = out["best_deg"]
        print(f"    at knee={b['knee']:+.1f} hip_pitch={b['hip_pitch']:+.1f} "
              f"ankle={b['ankle']:+.1f} deg")
    print("  dz/dq at standing pose (mm/deg):")
    for k, v in sens.items():
        print(f"    {k:10s} {v:+.4f}")
    if out["least_action_20mm"]:
        b = out["least_action_20mm"]
        print(f"  least-action 20 mm pose: hip_pitch={b['hip_pitch_deg']:+.1f} "
              f"knee={b['knee_deg']:+.1f} ankle={b['ankle_deg']:+.1f} deg "
              f"(|q|={b['joint_norm_deg']:.1f})")
    else:
        print("  least-action 20 mm pose: NONE within tolerance")
    print("  smallest knee bend clearing each height:")
    for k, v in thresh.items():
        if v["reachable"]:
            print(f"    {k:6s} knee={v['knee_deg']:+7.1f}  hip_pitch={v['hip_pitch_deg']:+7.1f}  "
                  f"ankle={v['ankle_deg']:+6.1f} deg")
        else:
            print(f"    {k:6s} UNREACHABLE at this dx tolerance")
    print(f"  -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
