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

Pass23 / loop R7
----------------
Pass22 fixed the ARCHIVED deploy_check_*.json evidence (re-derive its verdict
from its stages and bind the stage set to the conductor's FULL_STAGES). The
LIVE report CI had just produced was still checked by a DIFFERENT, weaker rule:
``stages`` was folded into a dict (duplicate names silently overwrite) and the
self-reported top-level ``verdict`` was trusted. A tamper matrix on the real
workspace proved all of these were accepted:

  * a report trimmed to a single ``inference`` stage (four stages dropped)
  * a duplicate stage name masking a FAIL behind a later PASS
  * an unknown sixth stage
  * ``skipped_stages`` disagreeing with the stage statuses
  * a FAIL stage masked while the top-level verdict still said PASS*

Official basis: GitHub Docs ("Troubleshooting required status checks") says a
job skipped by a condition "reports success", a job depending on a failed one
is "skipped and does not report a failure", and recommends ``always()`` plus
explicit per-dependency assertions. SLSA v1.0 ("Verifying artifacts") requires
untrusted externalParameters to be verified downstream and unrecognised ones
to fail verification. So a green aggregate is NOT evidence.

Both report consumers now share deploy_stages.py: the stage authority comes
from the CURRENT conductor SOURCE (ast, never imported or executed) and the
verdict is RE-DERIVED from the report's own stages.

Policy
------
* the report's stage set must equal FULL_STAGES exactly (no missing/extra/
  duplicate stages);
* its top-level verdict must equal the verdict re-derived from those stages;
* ``skipped_stages`` and ``full_stage_set`` must agree with the stages;
* ``inference`` must be PASS (the runtime is installed by this workflow);
* ``--allow-skip`` names must be real stages and may not name a MUST_PASS
  stage; in CI only ``contract`` may skip (it needs the full training stack).

Usage
-----
    python tools/hd1910/assert_ci_verdict.py out/ci_walk.json \
        --allow-skip contract
    python tools/hd1910/assert_ci_verdict.py --selftest

Exit: 0 ok / 1 assertion failed / 2 bad input.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

# Loaded via importlib.spec_from_file_location by the test suite too, so the
# sibling module is not importable by name until its directory is on sys.path.
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from deploy_stages import (DEFAULT_AUTHORITY, authority_variant,  # noqa: E402
                           derive_verdict, stage_authority)

# The stage that MUST have really executed in a CI that installs the runtime.
MUST_PASS = ("inference",)
# Stages whose SKIP is expected in CI (training stack intentionally absent).
DEFAULT_ALLOW_SKIP = ("contract",)


def check(report: dict, allow_skip: tuple[str, ...] = DEFAULT_ALLOW_SKIP,
          stage_source: Path | None = None) -> list[str]:
    """Return a list of problems; empty means a real, complete gate result."""
    full, err = stage_authority(Path(stage_source) if stage_source is not None
                                else DEFAULT_AUTHORITY)
    if err:
        return [err]
    problems: list[str] = []

    # SLSA v1.0: unrecognised external parameters SHOULD fail verification.
    unknown = sorted(set(allow_skip) - set(full))
    if unknown:
        problems.append(
            f"--allow-skip names unknown stage(s) {unknown}; current "
            f"FULL_STAGES={full} -- refusing a policy for a stage that does "
            "not exist")
    for name in MUST_PASS:
        if name in allow_skip:
            problems.append(
                f"--allow-skip {name!r} is forbidden: CI installs its runtime, "
                "so this stage must really execute")

    derived, stage_problems = derive_verdict(report, full, allow_skip)
    problems.extend(stage_problems)

    verdict = report.get("verdict")
    if verdict != derived:
        problems.append(f"verdict={verdict!r} disagrees with its own stages "
                        f"(re-derived {derived!r})")

    raw_stages = report.get("stages")
    statuses = {s.get("name"): s.get("status")
                for s in (raw_stages if isinstance(raw_stages, list) else [])
                if isinstance(s, dict)}
    for name in MUST_PASS:
        if statuses.get(name) != "PASS":
            problems.append(
                f"stage {name!r} is {statuses.get(name)!r}, expected PASS -- "
                "CI installs onnxruntime, so a SKIP means the guard is broken "
                "or mis-invoked")

    # A report from an older or forged conductor is not LIVE evidence.
    declared_full = report.get("full_stage_set")
    if not isinstance(declared_full, list) or declared_full != full:
        problems.append(
            f"report full_stage_set={declared_full!r} does not match the "
            f"CURRENT conductor FULL_STAGES={full}; regenerate it with "
            "pre_deploy_check.py --json")

    skipped = report.get("skipped_stages", [])
    if isinstance(skipped, list):
        unexpected = sorted(set(skipped) - set(allow_skip))
        if unexpected:
            problems.append(
                f"unexpected SKIP stage(s) {unexpected}; only "
                f"{list(allow_skip)} may be skipped in CI")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", nargs="?", type=Path,
                    help="conductor --json output (not needed with --selftest)")
    ap.add_argument("--allow-skip", action="append", default=None,
                    metavar="STAGE",
                    help="stage allowed to SKIP (repeatable; default: contract)")
    ap.add_argument("--stage-source", type=Path, default=None,
                    help="override the conductor source FULL_STAGES is read "
                         "from (negative controls / staged upgrades only)")
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

    problems = check(report, allow, args.stage_source)
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
    """Negative controls: deliberately broken reports MUST be rejected.

    The good report and every mutation are BUILT FROM the current stage
    authority, so adding a stage to the conductor cannot silently rot this
    matrix into testing a historical gate.
    """
    full, err = stage_authority(DEFAULT_AUTHORITY)
    if err:
        print(f"  [BAD] {err}")
        return 1
    ok = True

    def ci_report():
        stages, skipped = [], []
        for name in full:
            is_skip = name in DEFAULT_ALLOW_SKIP and name not in MUST_PASS
            stages.append({"name": name,
                           "status": "SKIP" if is_skip else "PASS",
                           "rc": 2 if is_skip else 0})
            if is_skip:
                skipped.append(name)
        return {"verdict": "PASS*" if skipped else "PASS",
                "skipped_stages": skipped,
                "full_stage_set": list(full),
                "stages": stages}

    def stage(report, name):
        return next(s for s in report["stages"] if s["name"] == name)

    good = ci_report()
    other = next(n for n in full
                 if n not in DEFAULT_ALLOW_SKIP and n not in MUST_PASS)

    cases: list[tuple[str, dict, tuple[str, ...], Path | None, bool]] = []
    cases.append(("clean CI report (contract skip allowed)", good,
                  DEFAULT_ALLOW_SKIP, None, True))

    bad = copy.deepcopy(good)
    stage(bad, "inference")["status"] = "SKIP"
    stage(bad, "inference")["rc"] = 2  # a real conductor SKIP, not an rc=0 contradiction
    bad["skipped_stages"] = sorted(set(bad["skipped_stages"] + ["inference"]))
    cases.append(("the Pass13-15 bug: inference SKIP", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    stage(bad, "inference")["status"] = "FAIL"
    stage(bad, "inference")["rc"] = 1
    bad["verdict"] = "FAIL"
    cases.append(("inference FAIL", bad, DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    stage(bad, other)["status"] = "SKIP"
    stage(bad, other)["rc"] = 2
    bad["skipped_stages"] = sorted(set(bad["skipped_stages"] + [other]))
    cases.append((f"unexpected {other} SKIP", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    cases.append(("empty stages",
                  {"verdict": "PASS", "skipped_stages": [], "stages": [],
                   "full_stage_set": list(full)},
                  DEFAULT_ALLOW_SKIP, None, False))

    # R7 tamper matrix: every one of these was ACCEPTED by the old assertion.
    bad = copy.deepcopy(good)
    bad["stages"] = [s for s in bad["stages"] if s["name"] == "inference"]
    cases.append(("R7 trimmed to inference only (other stages dropped)", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    hidden = copy.deepcopy(stage(bad, other))
    hidden["status"], hidden["rc"] = "FAIL", 1
    bad["stages"].append(hidden)
    cases.append(("R7 duplicate stage name masks a FAIL", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    bad["stages"].append({"name": "mystery_stage", "status": "PASS", "rc": 0})
    cases.append(("R7 unknown extra stage", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    bad["skipped_stages"] = []
    cases.append(("R7 skipped_stages detached from stage statuses", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    bad["verdict"] = "PASS"
    cases.append(("R7 top-level verdict contradicts its stages", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    bad.pop("full_stage_set")
    cases.append(("R7 report has no full_stage_set", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    bad = copy.deepcopy(good)
    bad["full_stage_set"] = list(full)[:-1]
    cases.append(("R7 full_stage_set belongs to an older gate", bad,
                  DEFAULT_ALLOW_SKIP, None, False))

    cases.append(("R7 unrecognised --allow-skip name", good,
                  ("contract", "mystery_stage"), None, False))
    cases.append(("R7 --allow-skip may not waive inference", good,
                  ("contract", "inference"), None, False))

    print("=== assert_ci_verdict selftest (negative controls) ===")
    for label, report, allow, source, expect_ok in cases:
        problems = check(report, allow, source)
        got_ok = not problems
        mark = "ok" if got_ok == expect_ok else "BAD"
        if got_ok != expect_ok:
            ok = False
        print(f"  [{mark}] {label}: accepted={got_ok} (expect {expect_ok})"
              + (f" :: {problems[0]}" if problems else ""))

    # Prove the SINGLE authority drives behaviour: editing the conductor's
    # FULL_STAGES must invalidate an otherwise intact live report. Variants are
    # derived from the parsed authority, not a second copy of the stage list.
    with tempfile.TemporaryDirectory(prefix="hd1910_verdict_scope_") as td:
        tdp = Path(td)
        src_text = DEFAULT_AUTHORITY.read_text(encoding="utf-8")
        src6 = authority_variant(src_text, add=("future_stage",))
        src4 = authority_variant(src_text, drop=(full[-1],))
        no_authority = tdp / "no_authority.py"
        no_authority.write_text("x = 1\n", encoding="utf-8")
        if not src6 or not src4:
            ok = False
            print("  [BAD] cannot derive stage-authority variants")
        else:
            conductor6 = tdp / "conductor6.py"
            conductor4 = tdp / "conductor4.py"
            conductor6.write_text(src6, encoding="utf-8")
            conductor4.write_text(src4, encoding="utf-8")
            for label, source in (
                    ("R7 conductor gains a stage -> live report red", conductor6),
                    ("R7 conductor loses a stage -> live report red", conductor4),
                    ("R7 stage authority missing -> fail loud", no_authority)):
                problems = check(good, DEFAULT_ALLOW_SKIP, source)
                got_ok = not problems
                mark = "ok" if not got_ok else "BAD"
                ok &= not got_ok
                print(f"  [{mark}] {label}: accepted={got_ok} (expect False)"
                      + (f" :: {problems[0]}" if problems else ""))

    print()
    print("self-test: " + ("PASS -- negative-control logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
