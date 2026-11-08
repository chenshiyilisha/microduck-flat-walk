#!/usr/bin/env python3
"""Machine-readable probe: what can THIS checkout actually verify?

Why this exists
---------------
Pass17 (2026-11-08) ran the whole deploy-gate command set inside a
`git archive HEAD` clean checkout -- i.e. exactly the file set GitHub Actions
gets -- and found that the workflow had never been validated against it:

  * `.upstream/` is gitignored, so every guard that reads robotd's Rust source
    (contract / imu chain / provenance boundary) has no authoritative side.
  * the three verified deploy .onnx are gitignored too (`*.onnx`, `logs/`),
    so `record_provenance.py --verify` reports three DRIFTs and the "real
    deploy gate" step gets four FAILs with an onnxruntime NO_SUCHFILE traceback.
  * consequently `pre_deploy_check.py --selftest` was rc=1 and
    `pytest tests/` was 25 failed / 18 passed / 9 skipped.

Pass13-16 had all been editing that workflow while only ever running it in a
full local workspace. A green-looking CI config is not evidence that CI can
run. This probe makes the precondition explicit and machine-checked: it lists
which required inputs are present, tracked, and byte-identical to the bundle,
and writes `ci_full_gate_possible=false` when the real gate cannot execute.

This is deliberately a PROBE, not a green-light: by default it exits 0 so CI can
still run the checks that ARE possible, but it prints `::warning::` plus a JSON
report saying the full gate was NOT run. Use --strict to turn a missing input
into a hard failure (e.g. from a local pre-ship checklist).

Usage
-----
    python tools/hd1910/assert_clean_checkout.py
    python tools/hd1910/assert_clean_checkout.py --json out/ci_readiness.json
    python tools/hd1910/assert_clean_checkout.py --strict
    python tools/hd1910/assert_clean_checkout.py --selftest

Exit: 0 probe ok / 1 --strict found missing inputs / 2 bad input.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = ROOT / "out" / "hd1910_kp8_deploy_bundle.json"

# The authoritative third-party snapshot the guards read, gitignored on purpose.
UPSTREAM_SOURCES = (
    ".upstream/hd1910m/radxa/installation.json",
    ".upstream/DuckBuddy-main/duck-control/src/imu.rs",
    ".upstream/DuckBuddy-main/duck-control/src/obs.rs",
    ".upstream/DuckBuddy-main/duck-control/src/model.rs",
    ".upstream/DuckBuddy-main/robotd-params/src/lib.rs",
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tracked(root: Path, rel: str) -> bool:
    """A file only helps CI if a fresh checkout actually receives it."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel],
            cwd=root, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def assess(artifacts: list[dict], upstream: list[dict], training_stack: bool) -> dict:
    """Pure logic: fold per-input observations into one verdict. Easy to test.

    An input counts only when it is present AND byte-identical AND tracked.
    A file that exists locally but is gitignored does NOT make CI runnable --
    that is precisely the Pass13-16 mistake.
    """
    problems: list[str] = []
    if not artifacts:
        # An empty bundle is not a healthy checkout -- the gate would have
        # nothing to check and would otherwise report "runnable".
        problems.append("bundle lists no artifacts: the gate has nothing to check")
    for a in artifacts:
        name = a.get("name", "?")
        if not a.get("exists"):
            problems.append(f"artifact {name}: missing on disk ({a.get('rel_path')})")
            continue
        # sha mismatch MUST be checked independently of size: the classic
        # bitrot case is a same-length edit, where bytes_match stays True.
        if not a.get("sha_match"):
            problems.append(f"artifact {name}: sha256 differs from bundle "
                            f"(bitrot or a stale bundle)")
        elif not a.get("bytes_match"):
            problems.append(f"artifact {name}: size differs from bundle")
        if not a.get("tracked"):
            problems.append(f"artifact {name}: exists but is NOT tracked by git "
                            f"(a clean checkout will not receive it)")
    for u in upstream:
        if not u.get("exists"):
            problems.append(f"upstream source missing: {u.get('rel_path')}")
    if not training_stack:
        problems.append("training stack (mjlab_microduck) not importable: "
                        "contract / IMU-chain stages cannot execute")

    return {
        "ci_full_gate_possible": not problems,
        "problems": problems,
        "n_artifacts": len(artifacts),
        "n_upstream_sources": len(upstream),
        "training_stack": bool(training_stack),
        "reason": ("all gate inputs present, tracked and byte-identical"
                   if not problems else
                   "this checkout cannot run the full deploy gate; the checks that "
                   "need these inputs MUST be run in a full local workspace"),
    }


def probe(root: Path, bundle_path: Path) -> dict:
    """Read the single source of truth and inspect every input it names."""
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    raw = bundle.get("artifacts", {})

    artifacts = []
    for name, meta in raw.items():
        rel = meta.get("rel_path", "")
        path = root / rel
        digest = _sha256(path)
        artifacts.append({
            "name": name,
            "rel_path": rel,
            "exists": path.is_file(),
            "tracked": _tracked(root, rel),
            "bytes_match": path.stat().st_size == meta.get("bytes")
                           if path.is_file() else False,
            "sha_match": digest == meta.get("sha256"),
        })

    upstream = [{"rel_path": rel, "exists": (root / rel).is_file()}
                for rel in UPSTREAM_SOURCES]
    training_stack = importlib.util.find_spec("mjlab_microduck") is not None
    out = assess(artifacts, upstream, training_stack)
    out["bundle"] = str(bundle_path.relative_to(root)) if bundle_path.is_relative_to(root) \
        else str(bundle_path)
    out["artifacts"] = artifacts
    out["upstream_sources"] = upstream
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--json", type=Path, dest="json_out",
                     help="write the machine-readable report here")
    ap.add_argument("--github-output", type=Path,
                     help="append full_gate=<true|false> to this file ($GITHUB_OUTPUT)")
    ap.add_argument("--strict", action="store_true",
                     help="exit 1 when any gate input is missing/untracked")
    ap.add_argument("--selftest", action="store_true",
                     help="run negative controls, no checkout needed")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    root = args.root.resolve()
    bundle = args.bundle if args.bundle.is_absolute() else root / args.bundle
    if not bundle.is_file():
        print(f"ERROR: bundle not found: {bundle}", file=sys.stderr)
        return 2
    try:
        report = probe(root, bundle)
    except (ValueError, OSError) as exc:
        print(f"ERROR: cannot probe: {exc}", file=sys.stderr)
        return 2

    ok = report["ci_full_gate_possible"]
    print(f"== CI input readiness ({bundle.name}) ==")
    for a in report["artifacts"]:
        flags = ("present" if a["exists"] else "MISSING",
                 "sha-ok" if a["sha_match"] else "SHA-DIFF",
                 "tracked" if a["tracked"] else "NOT-TRACKED")
        print(f"  {a['name']:<14} {' | '.join(flags)}  {a['rel_path']}")
    for u in report["upstream_sources"]:
        print(f"  upstream       {'present' if u['exists'] else 'MISSING'}  {u['rel_path']}")
    print(f"  training stack: {'present' if report['training_stack'] else 'MISSING'}")
    print()
    print(f"ci_full_gate_possible = {str(ok).lower()}  ({report['reason']})")
    for p in report["problems"]:
        print(f"  - {p}")

    if not ok:
        print()
        print("::warning:: deploy-gate CANNOT run the full gate on this checkout. "
              "A green CI here verifies guard LOGIC only, not a deploy policy. "
              "Run pre_deploy_check.py + pytest tests/ in the full local workspace "
              "before shipping.")
        print("REAL GATE NOT RUN -- do not read a green CI as a deployment sign-off")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print(f"report -> {args.json_out}")
    # Path("") is Path(".") and is truthy -- an unset $GITHUB_OUTPUT would
    # otherwise try to append to a directory. Guard it explicitly.
    if args.github_output and str(args.github_output) not in ("", "."):
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"full_gate={str(ok).lower()}\n")

    return 0 if (ok or not args.strict) else 1


def _selftest() -> int:
    """Negative controls: a checkout missing ANY input must not look runnable."""
    good_art = [{"name": n, "rel_path": f"x/{n}.onnx", "exists": True,
                 "tracked": True, "bytes_match": True, "sha_match": True}
                for n in ("walk", "ground_pick", "stand", "robotd_toml")]
    good_up = [{"rel_path": f".upstream/{i}", "exists": True} for i in range(3)]

    cases = []
    cases.append(("complete checkout", good_art, good_up, True, True))
    cases.append(("onnx missing on disk (clean checkout)",
                  [dict(good_art[0], exists=False)] + good_art[1:],
                  good_up, True, False))
    cases.append(("onnx present but gitignored (Pass13-16 trap)",
                  [dict(good_art[0], tracked=False)] + good_art[1:],
                  good_up, True, False))
    cases.append(("onnx sha drift",
                  [dict(good_art[0], sha_match=False)] + good_art[1:],
                  good_up, True, False))
    cases.append(("upstream snapshot absent",
                  good_art, [dict(good_up[0], exists=False)] + good_up[1:],
                  True, False))
    cases.append(("training stack absent",
                  good_art, good_up, False, False))
    cases.append(("no artifacts at all", [], [], True, False))

    ok = True
    for label, arts, ups, stack, expect_ok in cases:
        got = assess(arts, ups, stack)["ci_full_gate_possible"]
        mark = "ok" if got == expect_ok else "BAD"
        if got != expect_ok:
            ok = False
        print(f"  [{mark}] {label}: runnable={got} (expect {expect_ok})")
    # A missing input must produce a problem naming it, not just a False.
    r = assess([dict(good_art[0], tracked=False)] + good_art[1:], good_up, True)
    named = any("NOT tracked" in p for p in r["problems"])
    ok &= named
    print(f"  [{'ok' if named else 'BAD'}] untracked input is named in problems")
    print()
    print("self-test: " + ("PASS -- readiness logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
