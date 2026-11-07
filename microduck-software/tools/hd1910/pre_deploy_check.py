#!/usr/bin/env python3
"""One-command pre-deploy self-check for loading an HD-1910 policy onto the robot.

Context
-------
`publish` is NOT on this robot generation's chain: the B-gen robotd ignores the
official manifest fields, so a policy is loaded through a different path. The
individual guards already exist as standalone scripts, but a single slip
(obs-layout mismatch, broken normaliser floor, a constant/exploding action, or a
gain-scale typo in robotd.toml) produces a robot that "looks like it walks then
falls" with no error. This conductor chains the guards into one verdict so the
operator runs ONE command before touching the hardware:

    # prove the conductor + guards work with no real policy (no GPU, no robot)
    python tools/hd1910/pre_deploy_check.py --selftest

    # the real check, once a policy + robotd.toml exist
    python tools/hd1910/pre_deploy_check.py \
        --onnx out/p8head_2999.onnx \
        --toml out/robotd_hd1910_mode0.toml

Stages (each is an existing, independently-tested script)
--------------------------------------------------------
  contract   verify_policy_contract.py  obs 61/act 14/50Hz layout, joint order,
                                       home pose, action mapping  <-> robotd obs.rs
  bundle     verify_policy_bundle.py    normaliser lower bound, metadata, no
                                       EXTERNAL weights, joint_names in metadata
  numeric    policy_numeric_gate.py     G1-G4 absolute-magnitude gate (catches the
                                       deploy61 1157x normaliser blow-up)
  toml       audit_robotd_toml.py       gain-scale consistency of robotd.toml
                                       (only when --toml is given; --expect-kp 8)

Exit code: 0 if every stage PASSES (SKIPs are allowed), 1 if any FAILs.
A JSON report is written with --json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent

CONTRACT = HERE / "verify_policy_contract.py"
BUNDLE = HERE / "verify_policy_bundle.py"
NUMERIC = HERE / "policy_numeric_gate.py"
TOML_AUDIT = HERE / "audit_robotd_toml.py"


@dataclass
class StageResult:
    name: str
    rc: int
    status: str  # PASS / FAIL / SKIP
    tail: str


def _classify(rc: int) -> str:
    if rc == 0:
        return "PASS"
    if rc == 2:
        return "SKIP"  # sides unavailable / input needed, not a policy fault
    return "FAIL"


def _run(script: Path, *args: str) -> tuple[int, str, list[str]]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True,
        )
    except OSError as e:  # noqa: BLE001
        return 127, f"could not launch {script.name}: {e}", []
    out = (proc.stdout + proc.stderr).strip().splitlines()
    # Surface the actual problem lines (FAIL / "!" negative-control markers /
    # ERROR) so the summary tells the operator *why* a stage failed.
    problems = [l.strip() for l in out if any(k in l for k in ("FAIL", "! ", "ERROR", "BAD"))]
    return proc.returncode, "\n".join(out[-3:]) if out else "", problems


def _stage(name: str, script: Path, *args: str) -> StageResult:
    rc, tail, problems = _run(script, *args)
    detail = " | ".join(problems[-3:]) if problems else tail
    return StageResult(name=name, rc=rc, status=_classify(rc), tail=detail)


def run_selftest() -> int:
    print("== pre_deploy_check self-test (runs each guard's --selftest) ==")
    results: list[StageResult] = [
        _stage("contract.selftest", CONTRACT, "--selftest"),
        _stage("bundle.selftest", BUNDLE, "--selftest"),
        _stage("numeric.selftest", NUMERIC, "--selftest"),
        _stage("toml.selftest", TOML_AUDIT, "--selftest"),
    ]
    ok = True
    for r in results:
        mark = "ok" if r.status == "PASS" else "BAD"
        if r.status != "PASS":
            ok = False
        print(f"  [{mark}] {r.name}: {r.status}")
        if r.tail:
            for line in r.tail.splitlines():
                print(f"        {line}")
    print()
    print("self-test: " + ("PASS -- conductor + guards wired correctly"
                           if ok else "FAIL -- a guard's --selftest did not pass"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, help="policy .onnx to load-check")
    ap.add_argument("--toml", type=Path, help="robotd.toml (enables the toml-audit stage)")
    ap.add_argument("--manifest", type=Path, help="policy manifest.json beside the onnx")
    ap.add_argument("--upstream", type=Path,
                    help="B-gen Rust source for the contract check "
                         "(default: verify_policy_contract.py's default)")
    ap.add_argument("--expect-kp", type=int, default=16,
                    help="expected robotd position_kp / reg50 for the toml audit. "
                         "Default 16 matches this project's deliberate choice "
                         "(docs: B14 -- position_kp 16 reproduces the kp8 plant's "
                         "bandwidth on the servo without retraining). Set to the "
                         "intended reg50 for other plants.")
    ap.add_argument("--json", type=Path, help="write the full report as JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="run each guard's --selftest; needs no real policy")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    if not args.onnx:
        ap.error("--onnx is required (or use --selftest)")

    print(f"== HD-1910 pre-deploy load self-check: {args.onnx.name} ==")
    results: list[StageResult] = []

    contract_args = ["--onnx", str(args.onnx)]
    if args.toml:
        contract_args += ["--toml", str(args.toml)]
    if args.upstream:
        contract_args += ["--upstream", str(args.upstream)]
    results.append(_stage("contract", CONTRACT, *contract_args))

    bundle_args = [str(args.onnx)]
    if args.manifest:
        bundle_args += ["--manifest", str(args.manifest)]
    if args.toml:
        bundle_args += ["--toml", str(args.toml)]
    results.append(_stage("bundle", BUNDLE, *bundle_args))

    results.append(_stage("numeric", NUMERIC, str(args.onnx)))

    if args.toml:
        results.append(_stage("toml", TOML_AUDIT,
                              "--toml", str(args.toml),
                              "--expect-kp", str(args.expect_kp)))

    # ── report ──
    print()
    print(f"{'STAGE':<10} {'RESULT':<6} DETAIL")
    print("-" * 60)
    any_fail = False
    for r in results:
        if r.status == "FAIL":
            any_fail = True
        detail = r.tail.replace("\n", " | ")
        print(f"{r.name:<10} {r.status:<6} {detail[:90]}")
    print("-" * 60)
    verdict = "FAIL -- do NOT load this policy" if any_fail else "PASS -- safe to load (see SKIPs)"
    print(f"VERDICT: {verdict}")

    if args.json:
        payload = {
            "onnx": str(args.onnx),
            "toml": str(args.toml) if args.toml else None,
            "verdict": "FAIL" if any_fail else "PASS",
            "stages": [
                {"name": r.name, "status": r.status, "rc": r.rc, "tail": r.tail}
                for r in results
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"report -> {args.json}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
