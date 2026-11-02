# SPDX-License-Identifier: Apache-2.0
"""How much of a stepping-frequency sinusoid does the P3 plant actually deliver?

Why this file exists
--------------------
`p3head030_4096x2000` walks at `vx = 0.28*cmd + 0.025` (ratio 0.30) where the
XL330 baseline was `vx = 0.659*cmd - 0.018`. Before spending another GPU run on
the reward recipe (`--pin-action-rate`), we need a bound on what the *plant* can
do, otherwise "reward is the blocker" and "hardware is the blocker" stay
indistinguishable no matter what the training run returns.

The actuator's own control law (`bam/actuators.py::STS3215Actuator`) is

    q_target_smooth = clamp(q_target, q_target_smooth +- max_velocity*dt)
    duty            = clamp((q_target_smooth - q) * kp * error_gain
                            * error_gain_ratio, -max_pwm, max_pwm)

i.e. two hard nonlinearities *before* the motor even sees the command:

1. **Slew limit.** The target is rate-limited at `model.max_velocity` =
   5.2155 rad/s (the servo's no-load speed, 0.2 s/60 deg). A sinusoid of
   amplitude `A` at frequency `f` demands `2*pi*f*A` rad/s, so above
   `A = 5.2155/(2*pi*f)` the *commanded* waveform is no longer what was asked
   for, no matter what the policy outputs.
2. **Duty clamp.** `duty = error * kp * 0.166` saturates at 0.97, which needs a
   position error of `0.97/(kp*0.166)` = **1.169 rad (67 deg) at kp=5** but only
   **0.183 rad (10.5 deg) at kp=32**. So at kp=5 the servo is torque-starved for
   any error below 67 deg -- it only pushes hard when it is wildly behind.

Measured consequence in this file: the closed-loop gain from commanded joint
amplitude to achieved joint amplitude, per frequency, per kp. Multiply the
shortfall by the gait's amplitude requirement and you get a ceiling on stride,
hence on speed, that no reward change can cross.

This is the same plant object training uses (`bam.model.load_model` on
`tools/bam_params/hd1910/official_m6_stslaw.json`), not a hand-written transfer
function, so the nonlinearities above are in the loop.

Boundary conditions, stated because they bound the claim
--------------------------------------------------------
* **Free shaft**: no leg inertia, no gravity, no ground contact. This measures
  the *servo loop*, not the leg. A real leg adds inertia (lowers bandwidth) and
  contact (adds load) -- so the numbers here are an **upper** bound on what the
  leg can follow.
* Command is held at `--cmd-period` (default 20 ms = 50 Hz), matching the
  deployment loop, and integrated at `--dt` (default 1 ms, the firmware rate),
  so the slew limiter and the ZOH interact exactly as they do on hardware.
* `kp` is the *firmware* gain (P3 = 5). The json itself carries no `kp`; it is
  applied by the plant spec at load time, which is why it is a CLI knob here
  rather than read from the file.

Usage
-----
    # P3 (kp=5) vs the bench default (kp=32), the gait's own frequency included
    .venv-mjlab/Scripts/python.exe tools/hd1910/probe_kp5_bandwidth.py

    # one amplitude, denser frequency grid, JSON out
    .venv-mjlab/Scripts/python.exe tools/hd1910/probe_kp5_bandwidth.py \
        --amp-deg 12 --freqs 0.5,1.0,1.5,1.89,2.5 --json out/bw.json

Reading the output
------------------
`gain` < 1 means the joint moves less than commanded; `lag` is the phase delay in
degrees (a pure delay of `t` seconds at frequency `f` shows up as `360*f*t`).
`need_cmd_deg` is the command amplitude that would be required to *achieve*
`--target-deg` after attenuation -- compare it against the joint's mechanical
range; if it exceeds the range, the strategy physically cannot compensate.
`slew_limit_deg` is the amplitude at which the target itself starts being clipped.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / "tools/bam_params/hd1910/official_m6_stslaw.json"


class FreeShaft:
    """No load, no gravity -- the servo-loop condition, not the leg condition."""

    def compute_mass(self, q, dq):
        return 0.0

    def compute_bias(self, q, dq):
        return 0.0


def load_plant(json_path: Path, kp: float, vin: float):
    sys.path.insert(0, str(ROOT / "tools"))
    import bam_actuators  # noqa: F401  registers repo-local actuator names
    from bam.model import load_model

    model = load_model(str(json_path))
    act = model.actuator
    act.vin = vin
    act.kp = kp
    act.testbench_class = FreeShaft
    act.testbench = FreeShaft()
    model.actuator = act
    return model, act


def _fundamental(t: np.ndarray, y: np.ndarray, f: float) -> tuple[float, float]:
    """Amplitude and phase of the `f` component of `y`, by least squares.

    Returns (amp, phase_rad) such that y ~= amp*sin(2*pi*f*t + phase).
    """
    w = 2.0 * math.pi * f
    design = np.column_stack([np.sin(w * t), np.cos(w * t), np.ones_like(t)])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    amp = float(math.hypot(coef[0], coef[1]))
    phase = float(math.atan2(coef[1], coef[0]))
    return amp, phase


def run_one(
    json_path: Path,
    kp: float,
    freq: float,
    amp_rad: float,
    vin: float,
    dt: float,
    cmd_period: float,
    cycles: int,
    warmup_cycles: int,
) -> dict:
    from bam.simulate import Simulator

    model, act = load_plant(json_path, kp, vin)
    sim = Simulator(model)
    sim.reset(0.0, 0.0)
    # Must delete, not set None: the installed backend re-seeds on `hasattr`.
    if hasattr(act, "q_target_smooth"):
        del act.q_target_smooth

    cmd_hold = max(1, int(round(cmd_period / dt)))
    total = int(round((warmup_cycles + cycles) / freq / dt))
    start = total - int(round(cycles / freq / dt))

    ts, qs, dqs, duty = [], [], [], []
    cmd_now = 0.0
    for i in range(total):
        t = i * dt
        if i % cmd_hold == 0:
            cmd_now = amp_rad * math.sin(2.0 * math.pi * freq * t)
        volt = act.compute_control(np.float64(cmd_now), sim.q, sim.dq, dt)
        sim.step(volt, True, dt)
        if i >= start:
            ts.append(t)
            qs.append(float(sim.q))
            dqs.append(float(sim.dq))
            duty.append(float(volt) / vin)

    t_a = np.asarray(ts)
    q_a = np.asarray(qs)
    dq_a = np.asarray(dqs)
    duty_a = np.asarray(duty)

    amp_out, phase_out = _fundamental(t_a, q_a, freq)
    lag_deg = math.degrees(-phase_out)
    gain = amp_out / amp_rad if amp_rad else float("nan")
    offset = float(np.mean(q_a))

    return {
        "kp": kp,
        "freq_hz": freq,
        "amp_cmd_rad": amp_rad,
        "amp_out_rad": amp_out,
        "gain": gain,
        "lag_deg": lag_deg,
        "mean_offset_rad": offset,
        "peak_dq_rad_s": float(np.max(np.abs(dq_a))),
        "peak_duty": float(np.max(np.abs(duty_a))),
        "duty_sat_frac": float(np.mean(np.abs(duty_a) >= act.max_pwm * 0.999)),
        "max_velocity_rad_s": float(model.max_velocity.value),
        "max_pwm": float(act.max_pwm),
        "error_gain": float(act.error_gain),
        "error_gain_ratio": float(model.error_gain_ratio.value),
        "duty_per_rad": kp * float(act.error_gain) * float(model.error_gain_ratio.value),
        "slew_limit_amp_rad": float(model.max_velocity.value) / (2.0 * math.pi * freq),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json-plant", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--kp", default="5,32", help="firmware gains to compare")
    ap.add_argument(
        "--freqs",
        default="0.5,1.0,1.5,1.89,2.5,3.0",
        help="Hz; 1.89 is this robot's measured step frequency (feet, p3head030)",
    )
    ap.add_argument("--amp-deg", default="6,12,20", help="commanded joint amplitudes")
    ap.add_argument("--target-deg", type=float, default=12.0,
                    help="what the gait needs the joint to actually achieve")
    ap.add_argument("--vin", type=float, default=7.4)
    ap.add_argument("--dt", type=float, default=1e-3, help="integration / firmware step")
    ap.add_argument("--cmd-period", type=float, default=0.02, help="50 Hz control loop")
    ap.add_argument("--cycles", type=int, default=8)
    ap.add_argument("--warmup-cycles", type=int, default=4)
    ap.add_argument("--json", type=Path, default=None, help="write raw rows here")
    a = ap.parse_args()

    kps = [float(x) for x in str(a.kp).split(",") if x.strip()]
    freqs = [float(x) for x in str(a.freqs).split(",") if x.strip()]
    amps = [math.radians(float(x)) for x in str(a.amp_deg).split(",") if x.strip()]

    print(f"plant {a.json_plant.name}  vin={a.vin}V  cmd {1/a.cmd_period:.0f}Hz "
          f"dt={a.dt*1000:.1f}ms  free shaft (upper bound on the leg)")

    rows = []
    for kp in kps:
        # Constants are per-kp, so read them once off a throwaway load.
        probe = run_one(a.json_plant, kp, 1.0, math.radians(2.0), a.vin,
                        a.dt, a.cmd_period, 1, 1)
        dpr = probe["duty_per_rad"]
        mv = probe["max_velocity_rad_s"]
        max_pwm = probe["max_pwm"]
        print(f"\n== kp={kp:g} ==  error_gain*ratio={probe['error_gain']:.3f}*"
              f"{probe['error_gain_ratio']:.2f}  duty/rad={dpr:.3f}  "
              f"max_pwm={max_pwm:.2f}  max_velocity={mv:.4f} rad/s")
        print(f"   duty clamp reached at |err| = {max_pwm/dpr*57.2958:.1f} deg "
              f"({max_pwm/dpr:.3f} rad)")
        print(f"   {'f Hz':>5} {'A cmd':>7} {'A out':>7} {'gain':>6} {'lag':>7} "
              f"{'peak dq':>8} {'duty':>5} {'sat%':>5} {'need cmd':>9} {'slew cap':>9}")
        for f in freqs:
            for amp in amps:
                r = run_one(a.json_plant, kp, f, amp, a.vin, a.dt, a.cmd_period,
                            a.cycles, a.warmup_cycles)
                r["need_cmd_rad"] = (
                    math.radians(a.target_deg) / r["gain"] if r["gain"] > 1e-9 else float("inf")
                )
                rows.append(r)
                print(f"   {f:5.2f} {math.degrees(amp):6.1f}d {math.degrees(r['amp_out_rad']):6.1f}d "
                      f"{r['gain']:6.3f} {r['lag_deg']:6.1f}d {r['peak_dq_rad_s']:7.2f}u "
                      f"{r['peak_duty']:5.2f} {100*r['duty_sat_frac']:4.0f}% "
                      f"{math.degrees(r['need_cmd_rad']):8.1f}d "
                      f"{math.degrees(r['slew_limit_amp_rad']):8.1f}d")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({
            "plant": str(a.json_plant),
            "vin": a.vin,
            "dt": a.dt,
            "cmd_period": a.cmd_period,
            "target_deg": a.target_deg,
            "boundary": "free shaft, no leg inertia/gravity/contact",
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print(f"\nraw -> {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
