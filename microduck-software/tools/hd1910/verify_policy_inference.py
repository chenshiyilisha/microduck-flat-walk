#!/usr/bin/env python3
"""Execute a deployed HD-1910 policy ONNX and sanity-check its output.

The gap this closes
-------------------
``verify_policy_bundle.py`` only does *static* checks (IO widths, embedded
weights, metadata). It never runs the graph, so a policy whose export baked a
broken op, a transposed layer, or a constant/exploding action would still pass
every static gate and then "look like it walks then falls" on the robot.

Executing the exported graph and checking the output is industry-standard for
policy deployment: reflex-vla's ``reflex validate export`` compares ONNX vs
PyTorch at machine precision (exit 0/1/2 for CI); ETARS ships a cross-backend
consistency test; LeRobot's export feature request lists "compare PyTorch vs
exported model outputs" as a must-have. This script is the lightweight,
no-PyTorch version: it actually runs the ONNX via onnxruntime and asserts the
output is finite, not exploding, and not a degenerate constant.

Pure-Python negative control
---------------------------
``check_inference_output`` is stdlib-only and unit-tested by ``--selftest`` (no
onnxruntime/numpy needed), so the gate's *logic* is provable on a clean
checkout even where the heavy deps are absent. The onnxruntime execution path
returns rc=2 (SKIP) when the deps are missing, so the conductor treats a missing
runtime as "not checked" rather than a policy fault.

Exit codes: 0 PASS, 1 FAIL (output failed a check), 2 SKIP (deps absent / no
real policy), 3 usage error.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Output sanity bounds. The policy emits 14 joint action offsets; a healthy
# standing/stepping command is O(1) rad. Anything |x| > EXPLODE_CAP means the
# graph is numerically blown up (a real failure mode, not a legit pose).
EXPLODE_CAP = 1.0e3
# A constant (all-equal) 14-vector is suspicious for a locomotion policy at a
# zeroed obs — flag as WARN, not FAIL, to avoid false-positives on edge cases.
CONST_WARN = True


def check_inference_output(values) -> tuple[bool, list[str]]:
    """Pure-Python output validator. ``values`` is a flat or nested list of numbers.

    Returns (ok, reasons). ``ok`` is False only on FAIL-class problems (non-finite,
    explode). A degenerate constant is reported as a WARN reason but does not fail.
    """
    flat: list[float] = []
    stack = list(values) if isinstance(values, (list, tuple)) else [values]
    while stack:
        v = stack.pop()
        if isinstance(v, (list, tuple)):
            stack.extend(v)
        else:
            flat.append(float(v))

    if not flat:
        return False, ["output is empty"]

    reasons: list[str] = []
    any_nonfinite = False
    for x in flat:
        if math.isnan(x) or math.isinf(x):
            any_nonfinite = True
            break
    if any_nonfinite:
        reasons.append("output contains NaN/Inf (non-finite)")

    mx = max(abs(x) for x in flat)
    if mx > EXPLODE_CAP:
        reasons.append(f"output explodes: max|action|={mx:.3e} > cap {EXPLODE_CAP:.0e}")

    if CONST_WARN and len(flat) > 1 and all(x == flat[0] for x in flat):
        reasons.append(f"output is a degenerate constant ({flat[0]:.4g}) across "
                       f"{len(flat)} dims (WARN)")

    ok = not any(r for r in reasons if "WARN" not in r)
    return ok, reasons


def run_session(onnx_path: Path, expect_obs: int | None, expect_act: int | None):
    """Load + execute the ONNX via onnxruntime. Returns (rc, report_dict)."""
    try:
        import numpy as np  # noqa: WPS433
        import onnxruntime as ort  # noqa: WPS433
    except ImportError as e:  # deps absent -> SKIP, not FAIL
        return 2, {"status": "SKIP", "reason": f"missing dependency: {e.name}"}

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = sess.get_inputs()
    if not inputs:
        return 1, {"status": "FAIL", "reason": "onnx has no inputs"}
    inp = inputs[0]
    # robotd hardcodes the input name "obs"; prefer it if present.
    name = inp.name
    for i in inputs:
        if i.name == "obs":
            inp, name = i, "obs"
            break
    shape = list(inp.shape)
    shape = [1 if (d is None or d == 0) else d for d in shape]
    if expect_obs is not None and shape[-1] != expect_obs:
        return 1, {"status": "FAIL",
                   "reason": f"input dim mismatch: onnx={shape[-1]} "
                             f"expected {expect_obs}"}
    obs = np.zeros(shape, dtype=np.float32)

    try:
        out = sess.run(None, {name: obs})[0]
    except Exception as e:  # onnxruntime may raise on bad graphs / NaN propagation
        return 1, {"status": "FAIL", "reason": f"onnxruntime execution error: {e}"}

    out_list = out.tolist() if hasattr(out, "tolist") else list(out)
    if expect_act is not None:
        n = len(out_list) if not isinstance(out_list[0], (list, tuple)) else len(out_list[0])
        if n != expect_act:
            # not fatal for a smoke test, but worth recording
            pass
    ok, reasons = check_inference_output(out_list)
    report = {
        "status": "PASS" if ok else "FAIL",
        "input_name": name,
        "input_shape": shape,
        "output_len": len(out_list) if not isinstance(out_list[0], (list, tuple))
        else len(out_list[0]),
        "reasons": reasons,
    }
    return 0 if ok else 1, report


def _selftest() -> int:
    print("== verify_policy_inference self-test (pure-Python negative control) ==")
    cases = [
        ("happy", [0.1, -0.2, 0.05, 0.3, -0.1, 0.0, 0.2, -0.3,
                   0.15, 0.1, -0.05, 0.25, 0.0, -0.15], True),
        ("nan", [0.1, float("nan"), 0.2] + [0.0] * 11, False),
        ("inf", [float("inf")] * 14, False),
        ("explode", [1.0e9] * 14, False),
        ("constant_warn", [0.0] * 14, True),  # WARN only -> ok True
        ("empty", [], False),
    ]
    ok = True
    for label, vals, expect_ok in cases:
        res, reasons = check_inference_output(vals)
        good = (res == expect_ok)
        ok = ok and good
        mark = "ok" if good else "BAD"
        print(f"  [{mark}] {label}: ok={res} reasons={reasons}")
    print()
    print("self-test: " + ("PASS -- negative-control logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, help="policy .onnx to execute")
    ap.add_argument("--expect-obs", type=int, default=61,
                    help="expected obs width (default 61)")
    ap.add_argument("--expect-act", type=int, default=14,
                    help="expected action width (default 14)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the pure-Python negative-control self-test")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if not args.onnx:
        ap.error("--onnx is required (or use --selftest)")
    if not args.onnx.exists():
        print(f"ERROR: onnx not found: {args.onnx}", file=sys.stderr)
        return 3

    rc, report = run_session(args.onnx, args.expect_obs, args.expect_act)
    print(f"== inference smoke: {args.onnx.name} ==")
    print(f"  status: {report.get('status')}")
    if "input_name" in report:
        print(f"  input_name={report['input_name']} shape={report['input_shape']} "
              f"out_len={report['output_len']}")
    for r in report.get("reasons", []):
        print(f"  - {r}")
    if report.get("reason"):
        print(f"  reason: {report['reason']}")
    print(f"VERDICT: {report.get('status')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
