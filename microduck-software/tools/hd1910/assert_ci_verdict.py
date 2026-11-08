#!/usr/bin/env python3
"""Assert a conductor --json report is a REAL gate result, not a silent skip.

Why this exists
--------------
deploy-gate.yml installs onnx/onnxruntime/numpy itself, so in CI the
``inference`` stage MUST execute the ONNX graph. Pass13-15 shipped an inference
stage invoked with the wrong arguments (positional onnx instead of ``--onnx``);
argparse exits 2, the conductor classified that rc as "SKIP / dependency
absent", and CI stayed green because a SKIP never trips ``set -e``. A broken
guard is indistinguishable from a missing dependency if nobody asserts on the
verdict. This script makes the assumption explicit and machine-checked.

Policy
------
* verdict must not be FAIL.
* ``inference`` must be PASS (the runtime is installed by this workflow).
* Only explicitly allowed stages may be SKIP. In CI that is ``contract`` alone:
  it needs the full training stack (mjlab_microduck + torch + mujoco), which is
  deliberately not in requirements.txt. Any OTHER skip is a regression.

Usage
-----
    python tools/hd1910/assert_ci_verdict.py out/ci_walk.json \
        --allow-skip contract

Exit: 0 ok / 1 assertion failed / 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The stage that MUST have really executed in a CI that installs the runtime.
MUST_PASS = ("inference",)
# Stages whose SKIP is expected in CI (training stack intentionally absent).
DEFAULT_ALLOW_SKIP = ("contract",)


def check(report: dict, allow_skip: tuple[str, ...] = DEFAULT_ALLOW_SKIP) -> list[str]:
    """Return a list of problems; empty means the report is a real gate result."""
    problems: list[str] = []
    verdict = report.get("verdict")
    if verdict == "FAIL":
        problems.append("verdict is FAIL")
    elif verdict not in ("PASS", "PASS*"):
        problems.append(f"verdict is {verdict!r}, expected PASS/PASS*")

    stages = {s.get("name"): s.get("status") for s in report.get("stages", [])}
    if not stages:
        problems.append("report has no stages")

    for name in MUST_PASS:
        status = stages.get(name)
        if status != "PASS":
            problems.append(
                f"stage {name!r} is {status!r}, expected PASS -- CI installs "
                f"onnxruntime, so a SKIP means the guard is broken or mis-invoked")

    skipped = report.get("skipped_stages", [])
    unexpected = sorted(set(skipped) - set(allow_skip))
    if unexpected:
        problems.append(
            f"unexpected SKIP stage(s) {unexpected}; only {list(allow_skip)} "
            f"may be skipped in CI")

    for name, status in stages.items():
        if status == "FAIL":
            problems.append(f"stage {name!r} is FAIL")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", nargs="?", type=Path,
                    help="conductor --json output (not needed with --selftest)")
    ap.add_argument("--allow-skip", action="append", default=None,
                    metavar="STAGE",
                    help="stage allowed to SKIP (repeatable; default: contract)")
    ap.add_argument("--selftest", action="store_true",
                    help="run negative-control self-test, no report needed")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.report is None:
        print("ERROR: report is required unless --selftest", file=sys.stderr)
        return 2
    allow = tuple(args.allow_skip) if args.allow_skip is not None else DEFAULT_ALLOW_SKIP
    if not args.report.is_file():
        print(f"ERROR: report not found: {args.report}", file=sys.stderr)
        return 2
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        print(f"ERROR: cannot read report: {e}", file=sys.stderr)
        return 2

    problems = check(report, allow)
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print("VERDICT: FAIL -- CI gate result is not a real verification")
        return 1
    print(f"OK: verdict={report.get('verdict')} stages="
          f"{ {s['name']: s['status'] for s in report.get('stages', [])} }")
    print("VERDICT: PASS -- gate really executed")
    return 0


def _selftest() -> int:
    """Negative controls: deliberately broken reports MUST be rejected."""
    good = {
        "verdict": "PASS*",
        "skipped_stages": ["contract"],
        "stages": [
            {"name": "contract", "status": "SKIP"},
            {"name": "bundle", "status": "PASS"},
            {"name": "numeric", "status": "PASS"},
            {"name": "inference", "status": "PASS"},
            {"name": "toml", "status": "PASS"},
        ],
    }
    import copy
    cases = []
    cases.append(("clean CI report (contract skip allowed)", good, True))

    bad_inf = copy.deepcopy(good)
    bad_inf["stages"][3]["status"] = "SKIP"
    bad_inf["skipped_stages"] = ["contract", "inference"]
    cases.append(("the Pass13-15 bug: inference SKIP", bad_inf, False))

    bad_inf_fail = copy.deepcopy(good)
    bad_inf_fail["stages"][3]["status"] = "FAIL"
    bad_inf_fail["verdict"] = "FAIL"
    cases.append(("inference FAIL", bad_inf_fail, False))

    bad_extra = copy.deepcopy(good)
    bad_extra["stages"][2]["status"] = "SKIP"
    bad_extra["skipped_stages"] = ["contract", "numeric"]
    cases.append(("unexpected numeric SKIP", bad_extra, False))

    empty = {"verdict": "PASS", "skipped_stages": [], "stages": []}
    cases.append(("empty stages", empty, False))

    ok = True
    for label, report, expect_ok in cases:
        problems = check(report)
        got_ok = not problems
        good_mark = "ok" if got_ok == expect_ok else "BAD"
        if got_ok != expect_ok:
            ok = False
        print(f"  [{good_mark}] {label}: accepted={got_ok} (expect {expect_ok})"
              + (f" :: {problems[0]}" if problems else ""))
    print()
    print("self-test: " + ("PASS -- negative-control logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
