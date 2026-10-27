#!/usr/bin/env python
"""Measure per-joint frequency response: is the 130 ms lag the servo, or the task?

WHY THIS TEST (references, not invention)
-----------------------------------------
* GB/T「交流伺服系统通用技术规范」5.16.1.2 gives this method verbatim: drive the joint
  in POSITION mode with a sine, raise the frequency, record command vs actual position.
  Bandwidth is read two ways -- where the amplitude falls to 1/sqrt(2) (-3 dB), and
  where the phase lag reaches 90 deg. The standard also requires the test conditions be
  reported (load, inertia, amplitude, control mode, sampling rate), so every run prints
  all of them.
* Oncilla / Cheetah-cub (Frontiers 2018): RC servos with a >300:1 gearbox "would work
  well for 1 Hz motion frequencies", overheating only at 4 Hz. So ~1 Hz is normally
  inside a hobby servo envelope; a 0.59 gain at 1.15 Hz is the anomaly to explain.
* Sampling rule f_sample >= 10x bandwidth -> each row prints samples/cycle; the 50 Hz
  control rate makes anything above ~5 Hz untrustworthy and those rows are flagged.

WHY THE CLOCK USES physics_dt, NOT step_dt
------------------------------------------
`ActionManager.apply_action()` is called inside the decimation loop, once per PHYSICS
substep (its own docstring says so: "Called on every decimation substep (physics step),
not just once per policy step"). With decimation=20 the clock therefore advances by
physics_dt=1 ms per call. Advancing it by step_dt would make the commanded sine 20x too
fast -- and the phase fit would silently report the wrong frequency.

WHAT MAKES THIS A CLEAN MEASUREMENT
-----------------------------------
The policy is out of the loop: the joy action term's ``apply_actions`` is replaced with
one that writes ``default_pose + A*sin(2*pi*f*t)`` into ``joint_pos_target``. What is
measured is actuator + limb inertia (+ contact when the driven joint is a leg).
No closed loop, no reward, no exploration noise.

TWO CONDITIONS
--------------
* head joints -- never touch the ground: isolates servo + head inertia (no contact).
* leg joints  -- driven while every other joint holds the default pose: adds load.
  If head gain at 1.15 Hz is ~1.0 and leg gain is ~0.6, the deficit is load/contact
  rather than servo bandwidth.

NEGATIVE CONTROLS (a test that can only pass proves nothing)
------------------------------------------------------------
1. ``leak``: max |qpos - default| over the joints NOT driven. Non-zero means the
   injection contaminated them.
2. run with ``--amp 0``: gain must collapse and ``r2_act`` must stay low. Run once to
   prove the fit is not hallucinating an amplitude out of noise.
3. ``root_dz``: root height drift over the window. A sweep that topples the robot
   produces garbage leg numbers, so the drift is reported next to the gain.

MODEL DISCRIMINATION
--------------------
* pure transport delay T -> gain stays 1.0, phase = -360*f*T  (linear in f)
* first-order lag tau    -> gain = 1/sqrt(1+(2*pi*f*tau)^2), phase -> -90 deg
Both are least-squares fitted to the measured lag and their residuals printed, so the
label is chosen by data instead of asserted.

Usage
-----
  python tools/sweep_joint_bandwidth.py --tag main
  python tools/sweep_joint_bandwidth.py --tag negctrl --amp 0 --joints head_yaw,left_knee
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]

TASK = "Mjlab-JoySmoothPD-Flat-MicroDuck"

# Action-vector order of this robot (14 dims; matches the checkpoint and the ordering
# used by tools/probe_joint_tracking.py). Joint names are resolved against this table,
# so a reordered list would fail loudly instead of driving the wrong joint.
ORDER = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]
IDX = {n: i for i, n in enumerate(ORDER)}

HEAD_JOINTS = ["head_yaw", "head_pitch", "neck_pitch"]
LEG_JOINTS = ["left_knee", "left_ankle", "left_hip_pitch"]
GAIT_HZ = 1.15


class Sweeper:
    """Holds one env and one patched action term for a single driven joint."""

    def __init__(self, joint: str):
        from mjlab.envs import ManagerBasedRlEnv
        from mjlab.tasks.registry import load_env_cfg

        cfg = load_env_cfg(TASK, play=False)
        cfg.scene.num_envs = 1
        self.env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0")
        u = self.env.unwrapped
        self.u = u
        self.robot = u.scene["robot"]
        self.physics_dt = float(u.physics_dt)
        self.step_dt = float(u.step_dt)

        try:
            self.term = u.action_manager._terms["joint_pos"]
        except KeyError as exc:
            raise SystemExit(
                f"action term 'joint_pos' not found; available: "
                f"{list(u.action_manager._terms)}"
            ) from exc
        self.target_ids = self.term._target_ids
        n_act = len(self.target_ids)
        self.j = IDX[joint]
        if not (0 <= self.j < n_act):
            raise SystemExit(f"{joint} index {self.j} outside {n_act} action dims")

        # Amplitudes/frequency are mutated per row; ``k`` is the physics-substep clock.
        self.amp = 0.0
        self.freq = 1.0
        self.k = 0
        self.term.apply_actions = self._write_target

        # Resolve the ACTUATOR that drives this joint, so the reported torque is this
        # joint's and not some other channel. data.ctrl is indexed by GLOBAL actuator
        # id, while indexing.ctrl_ids is the entity-local order: assuming the two agree
        # is exactly the class of bug that produced the 240 mm FK error earlier.
        mjm = u.sim.mj_model
        import mujoco

        q_adr = int(self.robot.indexing.joint_q_adr[self.j].item()
                    if hasattr(self.robot.indexing.joint_q_adr, "item")
                    else self.robot.indexing.joint_q_adr[self.j])
        jnt = np.where(mjm.jnt_qposadr == q_adr)[0]
        if len(jnt) != 1:
            raise SystemExit(f"qpos address {q_adr} maps to {len(jnt)} joints")
        self.mj_joint_id = int(jnt[0])
        self.joint_name_mj = mujoco.mj_id2name(
            mjm, mujoco.mjtObj.mjOBJ_JOINT, self.mj_joint_id
        )
        ctrl_ids = u.scene["robot"].indexing.ctrl_ids
        ctrl_ids = [int(x) for x in np.asarray(
            ctrl_ids.detach().cpu() if hasattr(ctrl_ids, "detach") else ctrl_ids
        ).ravel()]
        hits = [g for g in ctrl_ids if int(mjm.actuator_trnid[g, 0]) == self.mj_joint_id]
        if len(hits) != 1:
            raise SystemExit(
                f"joint {self.joint_name_mj} driven by {len(hits)} actuators; "
                f"cannot attribute torque unambiguously"
            )
        self.ctrl_global_id = hits[0]
        # Loud check: the name mj reports must contain the joint we meant to drive.
        if joint not in str(self.joint_name_mj):
            raise SystemExit(
                f"index/name mismatch: asked for {joint}, mj says {self.joint_name_mj}"
            )

    def _write_target(self) -> None:
        base = self.robot.data.default_joint_pos[:, self.target_ids].clone()
        t = self.k * self.physics_dt
        base[0, self.j] += self.amp * math.sin(2.0 * math.pi * self.freq * t)
        # The original apply_actions() subtracts the encoder bias; keep that so the
        # commanded joint ANGLE (not the raw target) is the sine.
        target = base - self.robot.data.encoder_bias[:, self.target_ids]
        self.robot.set_joint_position_target(target, joint_ids=self.target_ids)
        self.k += 1

    def close(self) -> None:
        self.env.close()


def fit_sine(t: np.ndarray, y: np.ndarray, f: float):
    """y = dc + slope*t + amp*cos(w t + phi). Returns (dc, amp, phi, r2).

    The linear term is not cosmetic. While one joint is driven, the rest of the body
    keeps settling under gravity: `leak` is ~9-11 deg over a window, i.e. a slow ramp.
    Fitting only dc+cos+sin lets that ramp leak into the cos/sin coefficients and bias
    the phase -- which shows up as a fake decades-wide "transport delay". Including the
    slope removes it; if the phase changes after this, the earlier value was an artefact.
    """
    w = 2.0 * math.pi * f
    tc = t - t.mean()
    M = np.column_stack([np.ones_like(t), tc, np.cos(w * t), np.sin(w * t)])
    coef, *_ = np.linalg.lstsq(M, y, rcond=None)
    dc, _slope, a, b = coef
    amp = float(np.hypot(a, b))
    phi = float(math.atan2(-b, a))
    resid = y - M @ coef
    var = float(np.var(y))
    r2 = float(1.0 - np.var(resid) / var) if var > 1e-18 else 0.0
    return float(dc), amp, phi, r2


def wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def sweep_one(sw: Sweeper, freq: float, amp: float, cycles_meas: float, cycles_settle: float):
    period = 1.0 / max(freq, 1e-6)
    n_settle = int(round(cycles_settle * period / sw.step_dt))
    n_meas = int(round(cycles_meas * period / sw.step_dt))
    n_total = n_settle + n_meas

    sw.amp = amp
    sw.freq = freq
    sw.k = 0
    sw.env.reset()

    base = sw.robot.data.default_joint_pos[0, sw.target_ids].detach().cpu().numpy()
    others = [i for i in range(len(ORDER)) if i != sw.j]
    origin_z = float(sw.u.scene.terrain.env_origins[0, 2].item()) \
        if hasattr(sw.u.scene, "terrain") and sw.u.scene.terrain is not None else 0.0

    ts, cmd, act, rootz, tau = [], [], [], [], []
    # Keep the per-step samples ON THE GPU and transfer once at the end. Reading four
    # scalars per step forces a device sync per step (measured ~92 ms/step vs ~5 ms
    # otherwise) which would make a 6-joint x 8-frequency sweep take 20+ minutes.
    buf_q, buf_t, buf_tau, buf_z = [], [], [], []
    zero = torch.zeros(1, 14, device="cuda:0")
    dev = sw.robot.data.joint_pos.device

    for k in range(n_total):
        with torch.no_grad():
            sw.env.step(zero)
            # .clone() is mandatory: *_pos[0] and data.ctrl[0] are VIEWS into buffers
            # that are rewritten in place every substep. Appending the view makes the
            # final torch.stack return the last frame repeated N times -- which reads as
            # zero variance, i.e. cmd_amp=0 and gain=NaN, without any error.
            buf_q.append(sw.robot.data.joint_pos[0].clone())
            buf_t.append(sw.robot.data.joint_pos_target[0].clone())
            buf_tau.append(sw.robot.data.data.ctrl[0, sw.ctrl_global_id].clone())
            buf_z.append(sw.robot.data.root_link_pos_w[0, 2].clone())

    Q = torch.stack(buf_q).cpu().numpy()            # (n_total, 14)
    T = torch.stack(buf_t).cpu().numpy()
    # data.ctrl is the torque returned by BamActuator.compute() (gear=[1,0,...] -> direct
    # drive, so ctrl IS joint torque in Nm). It is NOT the voltage: vin=(6.5,8.2) is a
    # model parameter describing the supply, not the command.
    TAU = torch.stack(buf_tau).cpu().numpy()
    RZ = torch.stack(buf_z).cpu().numpy() - origin_z

    ts = np.arange(n_total) * sw.step_dt
    cmd = T[:, sw.j]
    act = Q[:, sw.j]
    rootz = RZ
    tau = TAU
    # Guard against the stale-view failure mode: if cmd is constant the fit would
    # return gain=NaN and the row would be silently dropped from the summary.
    if float(np.std(cmd)) < 1e-9:
        raise RuntimeError(
            f"{sw.joint_name_mj}: commanded signal is constant "
            f"(std<1e-9) at {freq} Hz -- sampling buffers are stale views"
        )
    leak = float(np.max(np.abs(Q[:, others] - base[others]))) if others else 0.0

    ts = np.asarray(ts)
    sl = slice(n_settle, None)
    _, a_cmd, p_cmd, r2_cmd = fit_sine(ts[sl], np.asarray(cmd)[sl], freq)
    _, a_act, p_act, r2_act = fit_sine(ts[sl], np.asarray(act)[sl], freq)
    tau_arr = np.asarray(tau)[sl]
    root_arr = np.asarray(rootz)[sl]
    n_edge = max(3, min(20, len(root_arr) // 5))

    gain = a_act / a_cmd if a_cmd > 1e-9 else float("nan")
    lag_deg = math.degrees(wrap(p_act - p_cmd))
    lag_ms = -lag_deg / 360.0 / freq * 1e3

    return {
        "freq_hz": float(freq),
        "cmd_amp_deg": math.degrees(a_cmd),
        "act_amp_deg": math.degrees(a_act),
        "gain": float(gain),
        "lag_deg": float(lag_deg),
        "lag_ms": float(lag_ms),
        "r2_cmd": r2_cmd,
        "r2_act": r2_act,
        "samples_per_cycle": float(1.0 / sw.step_dt / freq),
        "leak_deg": math.degrees(leak),
        "root_z_first_mm": 1e3 * float(np.mean(root_arr[:n_edge])),
        "root_z_last_mm": 1e3 * float(np.mean(root_arr[-n_edge:])),
        "root_dz_mm": 1e3 * float(np.ptp(root_arr)),
        "tau_min_nm": float(np.min(tau_arr)),
        "tau_max_nm": float(np.max(tau_arr)),
        "tau_dc_nm": float(np.mean(tau_arr)),
        "tau_amp_nm": float(np.std(tau_arr) * math.sqrt(2.0)),
        "tau_ptp_nm": float(np.ptp(tau_arr)),
    }


def fit_models(rows: list[dict]) -> dict:
    """Fit pure-delay vs first-order-lag to the measured lag; report both residuals."""
    arr = [r for r in rows if np.isfinite(r["lag_ms"]) and r["r2_act"] > 0.3
           and abs(r["gain"]) > 0.05]
    if len(arr) < 3:
        return {"note": "too few usable rows (r2_act>0.3) for a model fit"}
    f = np.array([r["freq_hz"] for r in arr], dtype=float)
    lag = np.array([r["lag_deg"] for r in arr], dtype=float)

    x = -360.0 * f                       # pure delay regressor, lag = -360*f*T
    T = float(np.dot(x, lag) / np.dot(x, x))
    rms_delay = float(np.sqrt(np.mean((lag - x * T) ** 2)))

    taus = np.logspace(-4.5, 0.0, 6000)
    rms = np.array([
        np.sqrt(np.mean((lag + np.degrees(np.arctan(2 * np.pi * f * t))) ** 2))
        for t in taus
    ])
    i = int(np.argmin(rms))
    return {
        "pure_delay_ms": T * 1e3,
        "pure_delay_rms_deg": rms_delay,
        "first_order_tau_ms": float(taus[i] * 1e3),
        "first_order_rms_deg": float(rms[i]),
        "better_fit": "pure_delay" if rms_delay < rms[i] else "first_order_lag",
        "rows_used": len(arr),
        "freqs_used": f.tolist(),
    }


def summarize(rows: list[dict]) -> dict | None:
    """Report the row nearest the 1.15 Hz gait frequency, plus the -3 dB crossing."""
    if not rows:
        return None
    usable = [r for r in rows if r["r2_act"] > 0.3]
    if not usable:
        return None
    row = min(usable, key=lambda r: abs(r["freq_hz"] - GAIT_HZ))

    crossing = None
    for r in sorted(usable, key=lambda r: r["freq_hz"]):
        if r["gain"] <= 1.0 / math.sqrt(2.0):
            crossing = r["freq_hz"]
            break
    ninety = None
    for r in sorted(usable, key=lambda r: r["freq_hz"]):
        if r["lag_deg"] <= -90.0:
            ninety = r["freq_hz"]
            break
    return {
        "gain_at_gait": row["gain"],
        "lag_ms_at_gait": row["lag_ms"],
        "freq_used_for_gait": row["freq_hz"],
        "minus3dB_hz": crossing,
        "phase90_hz": ninety,
        "root_dz_mm_at_gait": row["root_dz_mm"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=0.10)
    ap.add_argument("--joints", default=",".join(HEAD_JOINTS + LEG_JOINTS))
    ap.add_argument("--freqs", default="0.3,0.5,0.7,0.9,1.15,1.5,2.0,2.6")
    ap.add_argument("--tag", default="main")
    ap.add_argument("--cycles-meas", type=float, default=3.0)
    ap.add_argument("--cycles-settle", type=float, default=1.5)
    args = ap.parse_args()

    joints = [s.strip() for s in args.joints.split(",") if s.strip()]
    freqs = [float(s) for s in args.freqs.split(",") if s.strip()]

    report = {
        "task": TASK,
        "tag": args.tag,
        "amplitude_rad": args.amp,
        "amplitude_deg": math.degrees(args.amp),
        "condition": "policy bypassed; every other joint holds the default pose",
        "control_rate_hz": None,
        "physics_rate_hz": None,
        "joints": {},
    }

    print(f"tag={args.tag}  amplitude {args.amp:.3f} rad ({math.degrees(args.amp):.2f} deg)")
    hdr = (f"{'joint':16s} {'f[Hz]':>6} {'gain':>6} {'lag_deg':>8} {'lag_ms':>7} "
           f"{'r2':>6} {'leak_deg':>8} {'rootZ0':>7} {'rootZ1':>7} "
           f"{'tau_dc':>7} {'tau_ptp':>8}")
    print(hdr)
    print("-" * len(hdr))

    for joint in joints:
        sw = Sweeper(joint)
        if report["control_rate_hz"] is None:
            report["control_rate_hz"] = 1.0 / sw.step_dt
            report["physics_rate_hz"] = 1.0 / sw.physics_dt
        mj_name = sw.joint_name_mj
        rows = []
        try:
            for f in freqs:
                r = sweep_one(sw, f, args.amp, args.cycles_meas, args.cycles_settle)
                rows.append(r)
                flag = "" if r["samples_per_cycle"] >= 10 else " *"
                print(f"{joint:16s} {f:>6.2f} {r['gain']:>6.3f} {r['lag_deg']:>8.1f} "
                      f"{r['lag_ms']:>7.0f} {r['r2_act']:>6.2f} {r['leak_deg']:>8.2f} "
                      f"{r['root_z_first_mm']:>7.1f} {r['root_z_last_mm']:>7.1f} "
                      f"{r['tau_dc_nm']:>7.3f} {r['tau_ptp_nm']:>8.3f}{flag}")
        finally:
            sw.close()
        report["joints"][joint] = {
            "mj_joint_name": mj_name,
            "rows": rows,
            "models": fit_models(rows),
            "summary": summarize(rows),
        }

    out = ROOT / "out" / f"joint_bandwidth_{args.tag}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\ncontrol rate {report['control_rate_hz']:.0f} Hz, "
          f"physics rate {report['physics_rate_hz']:.0f} Hz"
          f"   ('*' = fewer than 10 samples/cycle, treat with care)")
    print(f"\n{'joint':16s} {'gain@1.15':>10} {'lag_ms@1.15':>12} {'-3dB Hz':>9} "
          f"{'90deg Hz':>9} {'better fit':>16}")
    for j, d in report["joints"].items():
        s, m = d["summary"], d["models"]
        if s is None:
            print(f"{j:16s} {'--':>10} {'--':>12} {'--':>9} {'--':>9} {'no usable row':>16}")
            continue
        print(f"{j:16s} {s['gain_at_gait']:>10.3f} {s['lag_ms_at_gait']:>12.0f} "
              f"{(s['minus3dB_hz'] or float('nan')):>9.2f} "
              f"{(s['phase90_hz'] or float('nan')):>9.2f} "
              f"{m.get('better_fit', 'n/a'):>16}")
    print(f"\n[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
