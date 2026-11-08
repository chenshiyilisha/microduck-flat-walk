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

Robotd compatibility is enforced, not just advisory
---------------------------------------------------
The B-gen robotd that drives the HD-1910 hardcodes the input tensor name
``"obs"`` and never reads the ONNX manifest/metadata (verified in
``verify_official_loader.py``: ``input_name="obs"`` contract, and the robotd
``policy.rs`` only calls ``check_width(inputs[-1]==61)``). A model whose input
is named anything else would raise at load on the robot even though every
static gate passed. So this gate *fails* when the input name is not ``"obs"``
(line: ``validate_inputs``) and when the action width is not ``expect_act``
(line: ``validate_outputs``) — those are guaranteed load/run failures, not
cosmetic warnings.

Pure-Python negative control
---------------------------
``validate_inputs`` and ``validate_outputs`` are stdlib-only and unit-tested by
``--selftest`` (no onnxruntime/numpy needed), so the gate's *logic* is provable
on a clean checkout even where the heavy deps are absent. The onnxruntime
execution path returns rc=2 (SKIP) when the deps are missing, so the conductor
treats a missing runtime as "not checked" rather than a policy fault.

Exit codes: 0 PASS, 1 FAIL (output or contract failed a check), 2 SKIP (deps
absent / no real policy), 3 usage error.
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
# robotd hardcodes the input tensor name "obs" and never reads the manifest.
OBS_NAME = "obs"


def validate_inputs(input_names, expect_name: str = OBS_NAME) -> tuple[bool, list[str]]:
    """Pure-Python: the ONNX must expose an input named ``expect_name``.

    robotd feeds ``{"obs": ...}`` at load and never consults the manifest, so a
    differently-named input is a guaranteed load failure on the robot. Returns
    (ok, reasons); ok is False when no input carries ``expect_name``.
    """
    reasons: list[str] = []
    if not input_names:
        return False, [f"onnx has no inputs (robotd needs an input named '{expect_name}')"]
    if expect_name not in input_names:
        # This is a hard contract failure, not advisory — record it as such.
        reasons.append(
            f"no input named '{expect_name}'; the HD-1910 robotd hardcodes the "
            f"input name '{expect_name}' and never reads the ONNX manifest, so a "
            f"differently-named input is a guaranteed load failure "
            f"(found inputs: {input_names})"
        )
        return False, reasons
    return True, reasons


def validate_outputs(values, expect_act: int | None = None) -> tuple[bool, list[str]]:
    """Pure-Python output validator. ``values`` is a flat or nested list of numbers.

    Returns (ok, reasons). ``ok`` is False on FAIL-class problems: non-finite,
    explode, or (when ``expect_act`` is given) an action-width mismatch. A
    degenerate constant is reported as a WARN reason but does not fail.
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

    if any(math.isnan(x) or math.isinf(x) for x in flat):
        reasons.append("output contains NaN/Inf (non-finite)")

    mx = max(abs(x) for x in flat)
    if mx > EXPLODE_CAP:
        reasons.append(f"output explodes: max|action|={mx:.3e} > cap {EXPLODE_CAP:.0e}")

    if expect_act is not None and len(flat) != expect_act:
        reasons.append(
            f"output width {len(flat)} != expected action width {expect_act} "
            f"(a metadata/export skew like the official 28-vs-14 standup bug)"
        )

    if CONST_WARN and len(flat) > 1 and all(x == flat[0] for x in flat):
        reasons.append(f"output is a degenerate constant ({flat[0]:.4g}) across "
                       f"{len(flat)} dims (WARN)")

    ok = not any("WARN" not in r for r in reasons)
    return ok, reasons


# Backward-compatible alias used by existing tests.
check_inference_output = validate_outputs


def run_session(onnx_path: Path, expect_obs: int | None, expect_act: int | None):
    """Load + execute the ONNX via onnxruntime. Returns (rc, report_dict)."""
    try:
        import numpy as np  # noqa: WPS433
        import onnxruntime as ort  # noqa: WPS433
    except ImportError as e:  # deps absent -> SKIP, not FAIL
        return 2, {"status": "SKIP", "reason": f"missing dependency: {e.name}"}

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inputs = sess.get_inputs()
    ok_in, r_in = validate_inputs([i.name for i in inputs])
    if not ok_in:
        return 1, {"status": "FAIL", "reason": r_in[0]}

    # robotd feeds {"obs": ...}; select that input explicitly.
    names = [i.name for i in inputs]
    inp = inputs[names.index(OBS_NAME)]
    shape = [1 if (d is None or d == 0) else d for d in inp.shape]
    if expect_obs is not None and shape[-1] != expect_obs:
        return 1, {"status": "FAIL",
                   "reason": f"input dim mismatch: onnx={shape[-1]} "
                             f"expected {expect_obs}"}
    obs = np.zeros(shape, dtype=np.float32)

    try:
        out = sess.run(None, {OBS_NAME: obs})[0]
    except Exception as e:  # onnxruntime may raise on bad graphs / NaN propagation
        return 1, {"status": "FAIL", "reason": f"onnxruntime execution error: {e}"}

    out_list = out.tolist() if hasattr(out, "tolist") else list(out)
    ok, reasons = validate_outputs(out_list, expect_act)
    report = {
        "status": "PASS" if ok else "FAIL",
        "input_name": OBS_NAME,
        "input_shape": shape,
        "output_len": len(out_list) if out_list else 0,
        "reasons": reasons,
    }
    return 0 if ok else 1, report


def _selftest() -> int:
    print("== verify_policy_inference self-test (pure-Python negative control) ==")
    cases = [
        ("happy", lambda: validate_outputs(
            [0.1, -0.2, 0.05, 0.3, -0.1, 0.0, 0.2, -0.3,
             0.15, 0.1, -0.05, 0.25, 0.0, -0.15])[0], True),
        ("nan", lambda: validate_outputs(
            [0.1, float("nan"), 0.2] + [0.0] * 11)[0], False),
        ("inf", lambda: validate_outputs([float("inf")] * 14)[0], False),
        ("explode", lambda: validate_outputs([1.0e9] * 14)[0], False),
        ("constant_warn", lambda: validate_outputs([0.0] * 14)[0], True),  # WARN only
        ("empty", lambda: validate_outputs([])[0], False),
        ("width_mismatch", lambda: validate_outputs([0.1] * 13, expect_act=14)[0], False),
        ("width_ok", lambda: validate_outputs([0.1] * 14, expect_act=14)[0], True),
        ("nested_width_ok", lambda: validate_outputs([[0.1] * 14], expect_act=14)[0], True),
    ]
    ok = True
    for label, fn, expect in cases:
        res = fn()
        good = (res == expect)
        ok = ok and good
        mark = "ok" if good else "BAD"
        print(f"  [{mark}] {label}: ok={res} (expect {expect})")
    print()

    # input-name contract (robotd hardcodes "obs")
    iok, _ = validate_inputs(["obs"])
    print(f"  [{'ok' if iok else 'BAD'}] input_has_obs -> {iok}")
    ibad, r = validate_inputs(["observation", "states"])
    print(f"  [{'ok' if not ibad else 'BAD'}] input_missing_obs -> {ibad} :: {r}")
    ok = ok and iok and (not ibad)

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
