#!/usr/bin/env python
"""Step response of one joint: settles two things the frequency sweep cannot.

QUESTION 1 -- is the command delay 3-6 ms or 60-120 ms?
------------------------------------------------------
`microduck_constants.py` sets ``delay_min_lag=3, delay_max_lag=6``. A third-party
replica doc (chenkui164/microduck-replica, docs/actuator-selection.en.md) annotates
these as "in control steps", which at 50 Hz would mean 60-120 ms. Reading the code path
instead says the opposite: ``ManagerBasedRlEnv.step`` calls ``scene.write_data_to_sim()``
*inside* the decimation loop, which calls ``_apply_actuator_controls`` ->
``act.apply_delay``, so the buffer advances once per PHYSICS substep (1 kHz) and 3-6
entries are 3-6 ms. Documentation can be stale or wrong; a step response measures it.
Reported: ``dead_time_ms`` = first sample at which |q - q0| exceeds 1 % of the step.

QUESTION 2 -- is the amplitude shortfall a steady-state error or a bandwidth effect?
-----------------------------------------------------------------------------------
A firmware P loop has finite DC gain, so even a held-constant target is approached but
not reached; stiction can add a dead zone on top. If ``dc_reach`` (final q / command)
is already ~0.76 with no motion at all, then the "gain 0.76 at 1.15 Hz" is mostly a
POSITION-LOOP GAIN deficit, not a bandwidth roll-off -- and the two demand completely
different fixes (raise loop gain vs lower gait frequency). A first-order lag with
gain k and time constant tau shows DC reach = k and 63 % rising time = tau.

METHOD (matches the intent of GB/T 5.16.1.2 step/transient clause)
------------------------------------------------------------------
All joints hold the default pose; at t=t_hold the driven joint's target steps by
``--amp`` and stays there. Sampling at the 50 Hz control rate; the first control step
after the step command is t=0 in the plot. ``t63_ms`` is the first sample reaching
63.2 % of the FINAL value (not of the command), which separates time constant from
steady-state gain.

Usage
-----
  python tools/probe_servo_step.py --joints head_yaw,left_knee --amp 0.10
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"

ORDER = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]
IDX = {n: i for i, n in enumerate(ORDER)}


class Stepper:
    def __init__(self, joint: str):
        from mjlab.envs import ManagerBasedRlEnv
        from mjlab.tasks.registry import load_env_cfg

        cfg = load_env_cfg(TASK, play=False)
        cfg.scene.num_envs = 1
        self.env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0")
        u = self.env.unwrapped
        self.u = u
        self.robot = u.scene["robot"]
        self.step_dt = float(u.step_dt)
        self.term = u.action_manager._terms["joint_pos"]
        self.target_ids = self.term._target_ids
        self.j = IDX[joint]
        self.amp = 0.0
        self.k = 0
        self.k_step = 10 ** 9   # step applied once the clock passes this
        self.term.apply_actions = self._write_target

    def _write_target(self) -> None:
        base = self.robot.data.default_joint_pos[:, self.target_ids].clone()
        # Clock is in PHYSICS substeps: apply_action() runs inside the decimation loop,
        # so the step lands on a substep boundary rather than being smeared by it.
        base[0, self.j] += self.amp if self.k >= self.k_step else 0.0
        target = base - self.robot.data.encoder_bias[:, self.target_ids]
        self.robot.set_joint_position_target(target, joint_ids=self.target_ids)
        self.k += 1

    def close(self) -> None:
        self.env.close()


def run(sw: Stepper, amp: float, n_hold: int, n_after: int):
    sw.amp = amp
    sw.k = 0
    sw.k_step = n_hold * int(round(sw.step_dt / sw.u.physics_dt))
    sw.env.reset()
    zero = torch.zeros(1, 14, device="cuda:0")
    qs, ts = [], []
    for k in range(n_hold + n_after):
        with torch.no_grad():
            sw.env.step(zero)
            # .clone() is mandatory: these are views into buffers rewritten in place.
            qs.append(sw.robot.data.joint_pos[0, sw.j].clone())
        ts.append(k * sw.step_dt)
    q = torch.stack(qs).cpu().numpy()
    t = np.asarray(ts)
    return t - n_hold * sw.step_dt, q


def analyse(t: np.ndarray, q: np.ndarray, amp: float) -> dict:
    """Dead time, DC reach, 63 % rise time, and the first-order time constant.

    Two measurement traps this function has to survive, both observed on real data:
    * EPISODE RESET. Auto-reset fires mid-window and q snaps back to the default pose
      (observed at ~1.4 s on head_yaw). Taking q[-10:] as the final value then reports
      dc_reach ~0.5 for a joint that actually reached 0.82. Resets are detected as a
      single-sample jump larger than half the commanded step and the trace truncated.
    * NOISE-BASED THRESHOLD. "moved" must beat the pre-step noise, not a fixed 1 % of
      the step: 1 % of 0.049 rad is 0.03 deg, below the 0.01 deg/ptp noise floor, which
      makes dead time read as 0 ms for any delay.
    """
    q0 = float(np.mean(q[:5]))
    pre = q[t < 0]
    pre_std = float(np.std(pre)) if len(pre) > 2 else 0.0

    # Truncate at the first single-sample jump that is too large to be tracking.
    post_idx = np.where(t >= 0)[0]
    end = len(q)
    jump_thr = 0.5 * math.degrees(amp)
    for i in post_idx[1:]:
        if abs(q[i] - q[i - 1]) > jump_thr:
            end = int(i)
            break
    reset_at_ms = float(t[end] * 1e3) if end < len(q) else None

    tt, qq = t[post_idx[0]:end], q[post_idx[0]:end]
    if len(qq) < 10:
        return {"error": "window too short before reset", "reset_at_ms": reset_at_ms}

    n_tail = max(5, len(qq) // 4)
    q_final = float(np.mean(qq[-n_tail:]))
    dq = q_final - q0
    if abs(dq) < 1e-6:
        return {"error": "no motion detected", "q0": q0, "q_final": q_final,
                "reset_at_ms": reset_at_ms}

    thr = max(3.0 * pre_std, 0.05 * abs(dq))
    moved = np.abs(qq - q0) > thr
    dead_ms = float(tt[np.argmax(moved)] * 1e3) if moved.any() else float("nan")

    frac = (qq - q0) / dq
    reached63 = frac.max() >= 0.632
    reached90 = frac.max() >= 0.90
    t63_ms = float(tt[np.argmax(frac >= 0.632)] * 1e3) if reached63 else float("nan")
    t90_ms = float(tt[np.argmax(frac >= 0.90)] * 1e3) if reached90 else float("nan")

    return {
        "q0_deg": math.degrees(q0),
        "q_final_deg": math.degrees(q_final),
        "dc_reach": float(dq / amp),
        "dc_error_deg": math.degrees(amp - dq),
        "dead_time_ms": dead_ms,
        "pre_noise_ptp_deg": math.degrees(pre_std * 2.0) if pre_std else 0.0,
        "move_threshold_deg": math.degrees(thr),
        "t63_ms": t63_ms,
        "t90_ms": t90_ms,
        "t90_over_t63": (t90_ms / t63_ms) if reached63 and reached90 else float("nan"),
        "overshoot_pct": float(100.0 * (frac.max() - 1.0)),
        "reset_at_ms": reset_at_ms,
        "samples_used": int(len(qq)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--joints", default="head_yaw,head_pitch,neck_pitch")
    ap.add_argument("--amp", type=float, default=0.10)
    ap.add_argument("--hold-s", type=float, default=0.60)
    ap.add_argument("--after-s", type=float, default=1.20)
    ap.add_argument("--tag", default="main")
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat the step on the SAME env. Distinguishes run-to-run "
                         "spread (fresh env resamples the battery voltage) from "
                         "sample-to-sample noise, so a number is only quoted when it "
                         "reproduces.")
    args = ap.parse_args()

    joints = [s.strip() for s in args.joints.split(",") if s.strip()]
    report = {"task": TASK, "amp_rad": args.amp, "amp_deg": math.degrees(args.amp),
              "joints": {}, "tag": args.tag}

    hdr = (f"{'joint':14s} {'dc_reach':>9} {'dc_err°':>8} {'dead_ms':>8} "
           f"{'t63_ms':>7} {'t90_ms':>7} {'t90/t63':>8} {'ovs%':>6} {'reset_ms':>9}")
    print(f"step {args.amp:.3f} rad ({math.degrees(args.amp):.2f} deg), hold "
          f"{args.hold_s:.2f} s then observe {args.after_s:.2f} s")
    print(hdr); print("-" * len(hdr))

    for joint in joints:
        sw = Stepper(joint)
        trials = []
        try:
            n_hold = int(round(args.hold_s / sw.step_dt))
            n_after = int(round(args.after_s / sw.step_dt))
            for _ in range(max(1, args.repeats)):
                t, q = run(sw, args.amp, n_hold, n_after)
                trials.append(analyse(t, q, args.amp))
        finally:
            sw.close()
        res = trials[0]
        spread = {k: [float(tr[k]) for tr in trials if k in tr]
                  for k in ("dc_reach", "dead_time_ms", "t63_ms")}
        report["joints"][joint] = {"result": res, "trials": trials,
                                   "spread": spread,
                                   "trace_ms": (t * 1e3).round(2).tolist(),
                                   "q_deg": np.degrees(q).round(4).tolist()}
        if "error" in res:
            print(f"{joint:14s} {res['error']}")
            continue
        rst = res.get("reset_at_ms")
        print(f"{joint:14s} {res['dc_reach']:>9.3f} {res['dc_error_deg']:>8.2f} "
              f"{res['dead_time_ms']:>8.0f} {res['t63_ms']:>7.0f} {res['t90_ms']:>7.0f} "
              f"{res['t90_over_t63']:>8.2f} {res['overshoot_pct']:>6.1f} "
              f"{(f'{rst:.0f}' if rst else '-'):>9}")
        if args.repeats > 1:
            print(f"{'':14s} repeats dc_reach={[round(x, 3) for x in spread['dc_reach']]}  "
                  f"dead_ms={[round(x) for x in spread['dead_time_ms']]}  "
                  f"t63_ms={[round(x) for x in spread['t63_ms']]}")

    out = ROOT / "out" / f"servo_step_{args.tag}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\ndc_reach < 1 means the loop settles short of the command (finite P gain /")
    print("stiction) -- that is a GAIN deficit, not a bandwidth roll-off.")
    print("dead_ms settles the '3-6 ms vs 3-6 control steps' question: ~3-6 ms means the")
    print("delay buffer advances per physics substep; ~60-120 ms would mean per control step.")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
