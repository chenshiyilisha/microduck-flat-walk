#!/usr/bin/env python3
"""C9 / esp-duck-style numeric gate, re-calibrated on OUR action scale.

Why this exists
---------------
`xingxingRealzyx/esp-duck` ships a boot-time "quantization-accuracy gate":
two input distributions (random / standing) and scale-aware thresholds
(`cos >= 0.998`, `relL2 <= 8%`, `maxabs <= 2% of S`).  Those numbers measure
**INT8-weight vs FP32-reference divergence**.  Our deployment chain runs the
very same FP32 ONNX in robotd, so there is no quantised twin to compare against
-- copying those thresholds would gate a quantity that does not exist here.

What we keep is the *structure*: two distributions, a scale taken from the
policy itself, a gate at every import/boot, and a hard negative control.
What we replace is the *quantity*: absolute physical magnitude of the action
(a joint offset in radians) and its response to a real command.  This is the
blind spot that let `deploy61` through both existing probes (C8 and R2):
its normaliser divisor has no floor, so a 5.7 degree head command becomes
-35.7 rad, while a zero-command stance still looks perfectly healthy.

Calibration (this repo, `docs/active/microduck-HD1910软件方案.md` §13.5):
  healthy   p8head_2999 / resume_5999 / alpha_walking : max|a| < 0.5 rad
  broken    deploy61                                   : max|a| up to 107 rad
The thresholds below are set from the healthy band and must turn `deploy61`
red (negative control), otherwise this file is not evidence of anything.

Usage
-----
  python policy_numeric_gate.py ONNX [--json OUT] [--probe] [--selftest]
  --selftest runs the three checked-in models and asserts healthy PASS /
  deploy61 FAIL.  No serial port, no robot, no network needed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

# Observation layout, byte-for-byte the order in verify_policy_bundle.py
# `plausible_obs()` (which itself mirrors obs.rs):
#   0:3 gyro | 3:6 gravity | 6:20 joint_pos | 20:34 joint_vel
#   34:48 last_action | 48:51 twist | 51:55 head | 55:57 body.x/y
#   57 body.z | 58 body.roll | 59 body.pitch | 60 body.yaw
OBS_LEN = 61
SLOT_HEAD = 51
SLOT_BODY_Z = 57
SLOT_BODY_ROLL = 58
SLOT_BODY_PITCH = 59

# Re-calibrated gates.  Units: radians of joint offset (raw policy output).
# STAND_MAX / CMD_MAX come from R2's "a joint offset, not a number" (<= 3.0).
# CMD_DELTA_MAX is 10x the largest healthy command response measured in §13.5
# (0.244 rad for 5.7 deg head on p8head_2999).
# RANDOM_STD_MAX is 6x the healthy band (0.29..0.83) seen in publish's smoke
# run; deploy61 measures 104 there.
STAND_MAX = 3.0
CMD_MAX = 3.0
CMD_DELTA_MAX = 3.0
RANDOM_STD_MAX = 5.0


def plausible_obs(twist=(0.3, 0.0, 0.0)) -> np.ndarray:
    """One stance at robot magnitudes. Mirrors verify_policy_bundle.plausible_obs."""
    o = np.zeros(OBS_LEN, dtype=np.float32)
    o[3:6] = (0.0, 0.0, -1.0)                      # projected gravity
    for i in range(14):
        o[6 + i] = 0.05 * (1 if i % 2 else -1)     # joint_pos off home
    for i in range(14):
        o[20 + i] = 0.3 * (1 if i % 3 else 0)      # joint_vel
    for i in range(14):
        o[34 + i] = 0.02 * (1 if i % 2 else 0)     # last_action
    o[48:51] = twist
    return o


def with_command(base: np.ndarray, slot: int, value_rad: float) -> np.ndarray:
    o = base.copy()
    o[slot] = value_rad
    return o


def _session(path: Path):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def infer(sess, rows: np.ndarray) -> np.ndarray:
    """Run row by row: several checked-in exports hard-code batch=1."""
    name = sess.get_inputs()[0].name
    out = []
    for row in rows:
        one = np.asarray(row, dtype=np.float32).reshape(1, -1)
        out.append(np.asarray(sess.run(None, {name: one})[0], dtype=np.float64).reshape(-1))
    return np.stack(out)


def probe(path: Path) -> dict:
    sess = _session(path)
    base = plausible_obs()

    # --- distribution A: off-distribution, same N(0,0.05) as publish's smoke run
    rng = np.random.default_rng(0)
    random_rows = rng.normal(0.0, 0.05, size=(64, OBS_LEN)).astype(np.float32)
    a_rand = infer(sess, random_rows)
    scale = float(np.mean(np.linalg.norm(a_rand, axis=1)))

    # --- distribution B: in-distribution stance + real commands robotd writes
    stand = infer(sess, base[None, :])[0]
    commands = {
        "head_5.7deg": (SLOT_HEAD, math.radians(5.7)),
        "head_17deg": (SLOT_HEAD, math.radians(17.0)),
        "body_pitch_5.7deg": (SLOT_BODY_PITCH, math.radians(5.7)),
        "body_z_5.7deg": (SLOT_BODY_Z, math.radians(5.7)),
        "body_roll_5.7deg": (SLOT_BODY_ROLL, math.radians(5.7)),
    }
    cmd_rows = np.stack([with_command(base, s, v) for s, v in commands.values()])
    a_cmd = infer(sess, cmd_rows)

    cmd_report = {}
    for (label, _), row in zip(commands.items(), a_cmd):
        cmd_report[label] = {
            "max_abs": float(np.max(np.abs(row))),
            "max_delta": float(np.max(np.abs(row - stand))),
            "a0": float(row[0]),
        }

    report = {
        "path": str(path),
        "scale_S_random": scale,
        "random_std": float(np.std(a_rand)),
        "random_max_abs": float(np.max(np.abs(a_rand))),
        "standing_max_abs": float(np.max(np.abs(stand))),
        "commands": cmd_report,
    }

    # -- Why esp-duck's own numbers cannot be copied (quantitative, not rhetorical):
    # its binding gate is `maxabs(standing) <= 2% of S` where S is the *policy's
    # own* random-set output scale.  A policy whose normaliser exploded has an
    # exploded S too, so that gate scales itself out of the way.
    esp_maxabs_gate = 0.02 * scale
    report["esp_gate_would"] = {
        "2pct_of_S": esp_maxabs_gate,
        "standing_max_abs": report["standing_max_abs"],
        "standing_passes": report["standing_max_abs"] <= esp_maxabs_gate,
        "comment": ("a healthy policy FAILS this (its stance is ~5x 2%S) while "
                    "deploy61 PASSES it (S inflated ~128x) -- copy the structure, "
                    "not the thresholds"),
    }

    checks = {
        "G1 standing magnitude": (report["standing_max_abs"] <= STAND_MAX,
                                  f"max|a|={report['standing_max_abs']:.4f} <= {STAND_MAX}"),
        "G2 command magnitude": (all(v["max_abs"] <= CMD_MAX for v in cmd_report.values()),
                                 f"max over commands={max(v['max_abs'] for v in cmd_report.values()):.4f} <= {CMD_MAX}"),
        "G3 command response": (all(v["max_delta"] <= CMD_DELTA_MAX for v in cmd_report.values()),
                                f"max|delta|={max(v['max_delta'] for v in cmd_report.values()):.4f} <= {CMD_DELTA_MAX}"),
        "G4 off-distribution spread": (report["random_std"] <= RANDOM_STD_MAX,
                                       f"std(a)={report['random_std']:.4f} <= {RANDOM_STD_MAX}"),
    }
    report["checks"] = {k: {"pass": bool(ok), "detail": d} for k, (ok, d) in checks.items()}
    report["verdict"] = "PASS" if all(ok for ok, _ in checks.values()) else "FAIL"
    return report


ROOT = Path(__file__).resolve().parents[2]  # microduck-software/
SELFTEST_MODELS = {
    "healthy_p8head_2999": ROOT / "out" / "p8head_2999.onnx",
    "healthy_resume_5999": ROOT / "out" / "hd1910_resume_4096_to6000_1027_it5999.onnx",
    "broken_deploy61": ROOT / "out" / "deploy61.onnx",
}


def selftest() -> int:
    missing = [str(p) for p in SELFTEST_MODELS.values() if not p.exists()]
    if missing:
        print("SKIP selftest (models not present):", ", ".join(missing))
        return 0
    ok = True
    for label, path in SELFTEST_MODELS.items():
        r = probe(path)
        expect = "FAIL" if label.startswith("broken") else "PASS"
        got = r["verdict"]
        mark = "ok" if got == expect else "MISMATCH"
        ok &= got == expect
        print(f"  {mark:<9} {label:<24} verdict={got:<4} expect={expect:<4} "
              f"S={r['scale_S_random']:.3f} std={r['random_std']:.3f} "
              f"stand={r['standing_max_abs']:.3f} "
              f"cmd_max={max(v['max_abs'] for v in r['commands'].values()):.3f}")
        for name, c in r["checks"].items():
            print(f"              {name:<28} {'PASS' if c['pass'] else 'FAIL'}  {c['detail']}")
    print("SELFTEST", "OK" if ok else "FAILED", "(negative control is mandatory)")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("onnx", nargs="?", type=Path, help="policy to gate")
    ap.add_argument("--probe", action="store_true", help="print statistics only, always exit 0")
    ap.add_argument("--json", type=Path, help="write the full report as JSON")
    ap.add_argument("--selftest", action="store_true", help="healthy PASS / deploy61 FAIL negative control")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.onnx is None:
        ap.error("need an ONNX path, or --selftest")
    r = probe(args.onnx)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if (args.probe or r["verdict"] == "PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
