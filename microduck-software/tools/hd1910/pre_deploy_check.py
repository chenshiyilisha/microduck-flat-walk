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
  inference  verify_policy_inference.py actually EXECUTES the ONNX via onnxruntime
                                       and asserts: input name == "obs" (robotd hardcodes
                                       it and never reads the manifest), output width ==
                                       expect-act (catches 28-vs-14 metadata skew), and a
                                       finite / non-exploding / non-degenerate output
                                       (closes the "static-only" blind spot; SKIP if
                                       onnx/onnxruntime absent, so a clean checkout without
                                       the runtime is not flagged as a policy fault)
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
INFERENCE = HERE / "verify_policy_inference.py"
TOML_AUDIT = HERE / "audit_robotd_toml.py"

# SINGLE AUTHORITY for the set of stages this conductor can execute.
# bundle_bindings.py parses this constant OUT OF THIS FILE (ast, no import)
# and refuses any archived deploy_check report whose stage set differs. So
# adding a 6th stage here automatically invalidates stale evidence instead of
# letting a 5-stage report keep looking green. Do NOT keep a second copy of
# this list: Pass20 proved that a third copy of an input list rots in silence.
# `toml` only runs when --toml is supplied; every report used as shipping
# evidence is generated with --toml, so FULL_STAGES is its expected shape.
FULL_STAGES: tuple[str, ...] = (
    "contract", "bundle", "numeric", "inference", "toml",
)


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


# argparse exits 2 on a CLI usage error -- the SAME rc the guards use to mean
# "SKIP (dependency absent)". Pass13-15 shipped an inference stage called with
# a positional onnx path while the script expects --onnx, so on a machine WITH
# onnxruntime the stage was silently reported "SKIP" instead of running. A
# broken guard invocation is a FAIL, never a skip: keep the two apart by the
# output signature, not by rc alone.
_USAGE_ERROR_MARKERS = (
    "error: unrecognized arguments",
    "error: the following arguments are required",
    "error: argument ",
    "error: ambiguous option",
)


def _is_argparse_usage_error(text: str) -> bool:
    """True only for an argparse CLI-usage failure (rc 2), not a genuine SKIP.

    Requires BOTH the usage banner and an argparse error line, so a policy
    output that merely mentions the word "usage" cannot trip it.
    """
    low = text.lower()
    return "usage:" in low and any(m in low for m in _USAGE_ERROR_MARKERS)


def _verdict(any_fail: bool, skipped: list[str]) -> str:
    """A SKIP is 'could not be checked', NOT a pass. Surface the skipped stage
    names so an operator never reads 'PASS' as 'fully verified' when (e.g.) the
    contract stage was skipped because the training stack is absent."""
    if any_fail:
        return "FAIL -- do NOT load this policy"
    if skipped:
        return (f"PASS* -- loadable IF the skipped stage(s) {skipped} pass "
                f"locally; run pre_deploy_check.py with the full training env + "
                f"onnxruntime before shipping")
    return "PASS -- safe to load (all stages verified)"


def _run(script: Path, *args: str) -> tuple[int, str, list[str], str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True,
        )
    except OSError as e:  # noqa: BLE001
        return 127, f"could not launch {script.name}: {e}", [], ""
    full = (proc.stdout + proc.stderr).strip()
    out = full.splitlines()
    # Surface the actual problem lines (FAIL / "!" negative-control markers /
    # ERROR) so the summary tells the operator *why* a stage failed.
    problems = [l.strip() for l in out if any(k in l for k in ("FAIL", "! ", "ERROR", "BAD"))]
    return proc.returncode, "\n".join(out[-3:]) if out else "", problems, full


def _stage(name: str, script: Path, *args: str) -> StageResult:
    rc, tail, problems, full = _run(script, *args)
    detail = " | ".join(problems[-3:]) if problems else tail
    status = _classify(rc)
    if rc == 2 and _is_argparse_usage_error(full):
        # A guard that rejected our arguments is NOT "dependency absent".
        # Without this, a wrong parameterization is indistinguishable from a
        # clean SKIP and the whole stage silently stops protecting anything.
        status = "FAIL"
        detail = "GUARD INVOCATION BROKEN (argparse usage error, not a SKIP): " + detail
    return StageResult(name=name, rc=rc, status=status, tail=detail)


def run_selftest(allow_skip: tuple[str, ...] = ()) -> int:
    """Run each guard's --selftest.

    A SKIP means "one side was unavailable", never "the guard passed". By
    default that is a FAIL. Lean CI (no mjlab_microduck) genuinely cannot run
    `contract.selftest`, so CI must name it EXPLICITLY via
    --selftest-allow-skip; the result is then printed as PARTIAL, not PASS.
    This mirrors assert_ci_verdict.py's --allow-skip for the real gate.
    """
    known = ("contract.selftest", "bundle.selftest", "numeric.selftest",
             "inference.selftest", "toml.selftest")
    unknown = sorted(set(allow_skip) - set(known))
    if unknown:
        print(f"ERROR: --selftest-allow-skip names no such guard: {unknown}",
              file=sys.stderr)
        return 2

    print("== pre_deploy_check self-test (runs each guard's --selftest) ==")
    results: list[StageResult] = [
        _stage("contract.selftest", CONTRACT, "--selftest"),
        _stage("bundle.selftest", BUNDLE, "--selftest"),
        _stage("numeric.selftest", NUMERIC, "--selftest"),
        _stage("inference.selftest", INFERENCE, "--selftest"),
        _stage("toml.selftest", TOML_AUDIT, "--selftest"),
    ]
    ok = True
    skipped: list[str] = []
    for r in results:
        if r.status == "PASS":
            mark = "ok"
        elif r.status == "SKIP" and r.name in allow_skip:
            mark = "skip"
            skipped.append(r.name)
        else:
            mark = "BAD"
            ok = False
        print(f"  [{mark}] {r.name}: {r.status}")
        if r.tail:
            for line in r.tail.splitlines():
                print(f"        {line}")
    print()
    if not ok:
        print("self-test: FAIL -- a guard's --selftest did not pass")
    elif skipped:
        print(f"self-test: PARTIAL -- {len(skipped)} guard selftest(s) skipped by "
              f"explicit allow-list ({', '.join(skipped)}); NOT a full verification")
        print("GUARD SELFTEST NOT FULLY VERIFIED -- rerun with the full training "
              "stack (.venv-mjlab) before shipping")
    else:
        print("self-test: PASS -- conductor + guards wired correctly")
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
    ap.add_argument("--selftest-allow-skip", default="",
                    help="comma-separated guard selftests allowed to SKIP in lean CI "
                         "(only 'contract.selftest' is legitimate). Default empty: "
                         "any SKIP is a FAIL. A whitelisted SKIP prints PARTIAL.")
    args = ap.parse_args()

    if args.selftest:
        allow = tuple(s.strip() for s in args.selftest_allow_skip.split(",")
                      if s.strip())
        return run_selftest(allow)

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

    # verify_policy_inference.py takes --onnx (an option), NOT a positional
    # path. Passing it positionally makes argparse exit 2, which used to be
    # swallowed as "SKIP / onnxruntime absent" -- hiding the broken stage.
    results.append(_stage("inference", INFERENCE,
                          "--onnx", str(args.onnx),
                          "--expect-obs", "61", "--expect-act", "14"))

    if args.toml:
        results.append(_stage("toml", TOML_AUDIT,
                              "--toml", str(args.toml),
                              "--expect-kp", str(args.expect_kp)))

    # Fail loud if someone adds a stage without updating the single authority
    # above (the bundle-evidence guard derives its expectations from it).
    if args.toml:
        ran = tuple(r.name for r in results)
        if ran != FULL_STAGES:
            raise RuntimeError(
                f"stage set drift: conductor ran {ran} but FULL_STAGES="
                f"{FULL_STAGES}; update the single authority in "
                "pre_deploy_check.py and regenerate the archived reports")

    # ── report ──
    print()
    print(f"{'STAGE':<10} {'RESULT':<6} DETAIL")
    print("-" * 60)
    any_fail = False
    skipped = []
    for r in results:
        if r.status == "FAIL":
            any_fail = True
        if r.status == "SKIP":
            skipped.append(r.name)
        detail = r.tail.replace("\n", " | ")
        print(f"{r.name:<10} {r.status:<6} {detail[:90]}")
    print("-" * 60)
    if any_fail:
        verdict = "FAIL -- do NOT load this policy"
    elif skipped:
        # A SKIP means "could not be checked" (heavy dep absent / needs a real
        # policy), NOT a pass. The contract stage in particular needs the full
        # training stack (mjlab_microduck) and is skipped in CI -- so an operator
        # must not read "PASS" as "fully verified". Surface the skipped names.
        verdict = _verdict(any_fail, skipped)
    else:
        verdict = "PASS -- safe to load (all stages verified)"
    print(f"VERDICT: {verdict}")

    if args.json:
        payload = {
            "onnx": str(args.onnx),
            "toml": str(args.toml) if args.toml else None,
            "verdict": "FAIL" if any_fail else ("PASS*" if skipped else "PASS"),
            "skipped_stages": skipped,
            "full_stage_set": list(FULL_STAGES),
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
