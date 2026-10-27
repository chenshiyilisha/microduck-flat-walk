"""Why do the leg joints only cover 40-60% of their commanded range?

`tools/trace_joy_foot_phase.py` established (with an exact FK control, 0.0000 mm)
that the foot reaches 5.3 mm while the commanded pose would put it at 24.7 mm --
so the deficit is entirely joint tracking. This tool asks the next question and
keeps the two answers apart, because they call for opposite fixes:

  ATTENUATION  qpos = a * target + b with a < 1 and small residual.
               The servo cannot follow the waveform: velocity/torque saturation.
               Fix = slower or smaller gait, not a reward change.

  OFFSET/SCALE a ~= 1 but |b| large, or a far from 1 with R^2 high.
               `joint_pos_target` is not in the same frame as `qpos`
               (encoder bias, servo units). The measurement is the bug.

  NEITHER      R^2 low: the joint is being back-driven by contact, not tracking
               at all. Then the commanded pose is a fiction and the reward is
               asking for something the body never attempts.

Per joint it reports the least-squares fit, the best integer lag from
cross-correlation (a pure transport delay also attenuates range when the signal
is periodic and the window is short), and the peak joint speed implied by both
the target and the measured motion so the two can be compared against the
servo's own limit.
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_trace():
    spec = importlib.util.spec_from_file_location("tj", ROOT / "tools" / "trace_joy_foot_phase.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def newest_ckpt(pattern: str) -> str:
    hits = [p for p in glob.glob(str(ROOT / "logs/rsl_rl/microduck_joy_smooth" / f"*{pattern}*" / "model_*.pt"))]
    hits = [p for p in hits if os.path.getsize(p) > 1024]
    if not hits:
        raise SystemExit(f"no checkpoint matching {pattern}")
    return max(hits, key=os.path.getmtime)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Mjlab-JoySmoothPD-Flat-MicroDuck")
    ap.add_argument("--run", default="std012")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--out", default="out/joint_tracking.json")
    args = ap.parse_args()

    import mujoco
    import torch

    tj = _load_trace()
    ckpt = args.checkpoint or newest_ckpt(args.run)
    env, policy = tj.build(args.task, ckpt, 1, args.device, False)
    u = env.unwrapped
    robot = u.scene["robot"]
    mjm = u.sim.mj_model
    step_dt = float(u.step_dt)

    q_adr = tj._np(robot.indexing.joint_q_adr).astype(int)
    names = [
        mujoco.mj_id2name(mjm, mujoco.mjtObj.mjOBJ_JOINT, int(np.where(mjm.jnt_qposadr == a)[0][0]))
        for a in q_adr
    ]

    env.reset()
    n = int(round(args.seconds / step_dt))
    tgt, pos, ep = [], [], []
    for _ in range(n):
        with torch.no_grad():
            obs = env.get_observations()
            act = policy(obs)
            env.step(act)
        tgt.append(tj._np(robot.data.joint_pos_target)[0].copy())
        pos.append(tj._np(robot.data.joint_pos)[0].copy())
        ep.append(float(tj._np(u.episode_length_buf)[0]))
    tgt = np.asarray(tgt)
    pos = np.asarray(pos)
    ep = np.asarray(ep)

    # A reset re-initialises joint_pos_target (initialize_joy_servo_targets) and
    # teleports the joints home. Regressing across that discontinuity produces a
    # meaningless slope and drags R^2 to zero -- which is exactly how the first
    # version of this tool "found" a 1734 deg/s target speed for a 229 deg/s
    # rate-limited signal. Keep only the stretch after the last reset.
    resets = np.where(np.diff(ep) < 0)[0] + 1
    start = int(resets[-1]) if len(resets) else 0
    keep = np.arange(len(ep)) >= max(start, 40)  # also skip the 0.8 s gait ramp
    n_dropped = int(len(ep) - keep.sum())
    tgt, pos = tgt[keep], pos[keep]
    out = {
        "checkpoint": ckpt,
        "seconds": args.seconds,
        "step_dt": step_dt,
        "samples_used": int(keep.sum()),
        "samples_dropped": n_dropped,
        "n_resets": int(len(resets)),
        "joints": {},
    }
    print(f"using {keep.sum()}/{len(ep)} samples ({n_dropped} dropped: "
          f"{len(resets)} reset(s) + 0.8 s ramp)")

    max_lag = 40
    print(f"{'joint':22s} {'R2_raw':>7} {'lag':>4} {'R2_lag':>7} {'slope':>6} "
          f"{'tgt_rng':>8} {'pos_rng':>8} {'ratio':>6} {'lag_ms':>7}")
    for i, nm in enumerate(names):
        x, y = tgt[:, i], pos[:, i]
        A = np.vstack([x, np.ones_like(x)]).T
        (a_raw, b_raw), *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - (a_raw * x + b_raw)
        ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-12
        r2_raw = 1.0 - float((resid ** 2).sum()) / ss_tot

        # Best integer lag: shift pos back in time until it lines up with target.
        # A pure transport delay shows up here as slope ~1 and high R^2 -- which
        # is a completely different disease from amplitude attenuation.
        best_lag, best_r2, best_slope = 0, -1e9, float("nan")
        for lag in range(0, max_lag + 1):
            xs = x[: len(x) - lag] if lag else x
            ys = y[lag:] if lag else y
            if xs.std() < 1e-9 or ys.std() < 1e-9:
                continue
            Ai = np.vstack([xs, np.ones_like(xs)]).T
            (aa, bb), *_ = np.linalg.lstsq(Ai, ys, rcond=None)
            ri = ys - (aa * xs + bb)
            sst = float(((ys - ys.mean()) ** 2).sum()) or 1e-12
            r2i = 1.0 - float((ri ** 2).sum()) / sst
            if r2i > best_r2:
                best_lag, best_r2, best_slope = lag, r2i, float(aa)

        rng_t = float(np.degrees(x.max() - x.min()))
        rng_p = float(np.degrees(y.max() - y.min()))
        out["joints"][nm] = {
            "slope_raw": float(a_raw),
            "r2_raw": r2_raw,
            "best_lag_steps": int(best_lag),
            "best_lag_ms": float(best_lag * step_dt * 1e3),
            "r2_at_best_lag": float(best_r2),
            "slope_at_best_lag": best_slope,
            "target_range_deg": rng_t,
            "pos_range_deg": rng_p,
            "range_ratio": rng_p / rng_t if rng_t > 1e-9 else float("nan"),
        }
        print(f"{nm:22s} {r2_raw:>7.3f} {best_lag:>4} {best_r2:>7.3f} {best_slope:>6.2f} "
              f"{rng_t:>8.1f} {rng_p:>8.1f} "
              f"{rng_p / rng_t if rng_t > 1e-9 else float('nan'):>6.2f} "
              f"{best_lag * step_dt * 1e3:>7.0f}")

    # Aggregate verdict on the legs only (the head is not part of the gait).
    legs = {k: v for k, v in out["joints"].items() if "leg" in k.replace("hip", "leg").replace("knee", "leg").replace("ankle", "leg")}
    med_r2_raw = float(np.median([v["r2_raw"] for v in legs.values()]))
    med_r2_lag = float(np.median([v["r2_at_best_lag"] for v in legs.values()]))
    med_slope = float(np.median([v["slope_at_best_lag"] for v in legs.values()]))
    med_ratio = float(np.median([v["range_ratio"] for v in legs.values()]))
    med_lag_ms = float(np.median([v["best_lag_ms"] for v in legs.values()]))
    out["summary"] = {
        "median_leg_r2_raw": med_r2_raw,
        "median_leg_r2_at_best_lag": med_r2_lag,
        "median_leg_slope_at_best_lag": med_slope,
        "median_leg_range_ratio": med_ratio,
        "median_leg_lag_ms": med_lag_ms,
    }
    if med_r2_lag < 0.5:
        verdict = "BACK-DRIVEN: leg joints do not follow the target even after re-aligning in time"
    elif med_lag_ms > 60 and med_r2_lag > 0.8:
        verdict = ("DELAY: legs follow the shape once shifted by %.0f ms (R2 %.2f) -- "
                   "the actuator is bandwidth-limited, not mis-scaled" % (med_lag_ms, med_r2_lag))
    elif med_slope < 0.75 and med_r2_lag > 0.8:
        verdict = "ATTENUATION: servo tracks the shape but only %.2f of the amplitude" % med_slope
    elif med_ratio < 0.8:
        verdict = "AMPLITUDE LOSS: range ratio %.2f" % med_ratio
    else:
        verdict = "TRACKING OK on the legs; look elsewhere for the foot-height deficit"
    out["summary"]["verdict"] = verdict
    print(f"\nmedian leg: R2_raw {med_r2_raw:.3f} -> R2@lag {med_r2_lag:.3f}, "
          f"lag {med_lag_ms:.0f} ms, slope {med_slope:.2f}, range ratio {med_ratio:.2f}")
    print(f"VERDICT: {verdict}")

    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[done] {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
