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
which required inputs are present, tracked, and byte-identical to the bundle.

Pass18 FIX (2026-11-08): those inputs are now committed -- 3 deployed .onnx
(2.27 MiB), the 9 read-only robotd/RL contract sources the guards actually
parse (450 KiB), and the runmeta/heading_meta companions. The probe's old
UPSTREAM_SOURCES list had only 5 entries and MISSED four files that
verify_policy_bundle.load_contract() really reads; the list below was derived
by emptying a clean checkout until load_contract() reported 0 problems again.

TWO verdicts, because CI and a developer workstation cannot verify the same
things (do not collapse them into one boolean):
  * ci_scope_gate_possible -- all committed gate inputs present/tracked/identical.
    This is what `--strict` asserts in CI. With it true, four of the five
    conductor stages really execute.
  * ci_full_gate_possible  -- the above AND an importable mjlab_microduck training
    stack. Only this makes the `contract` stage (obs layout / joint order / home
    pose vs the live training cfg) execute. CI on ubuntu-latest installs only
    tools/hd1910/requirements.txt, so it is legitimately false there; that
    stage stays an EXPLICIT SKIP via assert_ci_verdict.py --allow-skip contract
    and must be run locally with .venv-mjlab before shipping.

Usage
-----
    python tools/hd1910/assert_clean_checkout.py
    python tools/hd1910/assert_clean_checkout.py --json out/ci_readiness.json
    python tools/hd1910/assert_clean_checkout.py --strict          # CI scope
    python tools/hd1910/assert_clean_checkout.py --strict-full    # incl. training stack
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

# The authoritative read-only contract sources the guards PARSE. Derived by
# measurement (Pass18): with all nine present in a clean checkout,
# verify_policy_bundle.load_contract() reports obs_len=61 / action_len=14 /
# 15 joint names / 15 home values / input 'obs' and zero problems. The old
# 5-entry list missed policy.rs, duck-ipc-proto/lib.rs, feetech.rs and
# microduck_rl-develop's publish/manifest.py -- a probe that under-reports its
# own inputs is exactly the Pass13-16 failure mode. Keep this list in sync with
# .gitignore's force-add note (these nine ARE tracked, via `git add -f`).
UPSTREAM_SOURCES = (
    ".upstream/hd1910m/radxa/installation.json",
    ".upstream/DuckBuddy-main/duck-control/src/obs.rs",
    ".upstream/DuckBuddy-main/duck-control/src/model.rs",
    ".upstream/DuckBuddy-main/duck-control/src/policy.rs",
    ".upstream/DuckBuddy-main/duck-control/src/imu.rs",
    ".upstream/DuckBuddy-main/duck-control/src/feetech.rs",
    ".upstream/DuckBuddy-main/duck-ipc-proto/src/lib.rs",
    ".upstream/DuckBuddy-main/robotd-params/src/lib.rs",
    ".upstream/microduck_rl-develop/src/mjlab_microduck/publish/manifest.py",
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
            problems.append(f"upstream contract source missing: {u.get('rel_path')}")

    # Split BEFORE the training-stack condition. A lean CI checkout has every
    # committed input but no mjlab_microduck; that is a legitimate, explicitly
    # declared SKIP for the contract stage -- NOT a missing gate input. Merging
    # the two made `--strict` permanently red in CI (Pass17's own blind spot).
    scope_problems = list(problems)
    if not training_stack:
        problems.append("training stack (mjlab_microduck) not importable: "
                        "contract stage must be an EXPLICIT SKIP "
                        "(assert_ci_verdict.py --allow-skip contract)")

    scope_ok = not scope_problems
    full_ok = not problems
    if not scope_ok:
        reason = ("committed gate inputs are missing/untracked/stale; the real "
                  "deploy gate MUST be run in a full local workspace")
    elif not full_ok:
        reason = ("CI scope is complete (4/5 conductor stages execute); "
                  "contract stage needs the training stack and MUST be run "
                  "locally with .venv-mjlab before shipping")
    else:
        reason = "all gate inputs present, tracked and byte-identical; training stack present"

    return {
        "ci_scope_gate_possible": scope_ok,
        "ci_full_gate_possible": full_ok,
        "scope_problems": scope_problems,
        "problems": problems,
        "n_artifacts": len(artifacts),
        "n_upstream_sources": len(upstream),
        "training_stack": bool(training_stack),
        "reason": reason,
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
                     help="append scope_gate/full_gate=<true|false> ($GITHUB_OUTPUT)")
    ap.add_argument("--strict", action="store_true",
                     help="exit 1 when a COMMITTED gate input is missing/untracked/stale "
                          "(the CI scope; does not require the training stack)")
    ap.add_argument("--strict-full", action="store_true",
                     help="as --strict, and also require an importable mjlab_microduck "
                          "training stack (local pre-ship checklist)")
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

    scope_ok = report["ci_scope_gate_possible"]
    full_ok = report["ci_full_gate_possible"]
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
    print(f"ci_scope_gate_possible = {str(scope_ok).lower()}  (4/5 stages in CI)")
    print(f"ci_full_gate_possible  = {str(full_ok).lower()}  (5/5, needs training stack)")
    print(f"reason: {report['reason']}")
    for p in report["problems"]:
        print(f"  - {p}")

    if not scope_ok:
        print()
        print("::warning:: deploy-gate CANNOT run the real gate on this checkout. "
              "A green CI here verifies guard LOGIC only, not a deploy policy. "
              "Run pre_deploy_check.py + pytest tests/ in the full local workspace "
              "before shipping.")
        print("REAL GATE NOT RUN -- do not read a green CI as a deployment sign-off")
    elif not full_ok:
        print()
        print("::notice:: CI scope complete: 4/5 conductor stages will REALLY execute. "
              "The `contract` stage needs mjlab_microduck (torch/mujoco) and is an "
              "EXPLICIT SKIP here, asserted by assert_ci_verdict.py --allow-skip "
              "contract. Run pre_deploy_check.py locally with .venv-mjlab before ship.")
        print("CONTRACT STAGE NOT VERIFIED IN CI -- do not read a green CI as full sign-off")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print(f"report -> {args.json_out}")
    # Path("") is Path(".") and is truthy -- an unset $GITHUB_OUTPUT would
    # otherwise try to append to a directory. Guard it explicitly.
    if args.github_output and str(args.github_output) not in ("", "."):
        with args.github_output.open("a", encoding="utf-8") as fh:
            fh.write(f"scope_gate={str(scope_ok).lower()}\n")
            fh.write(f"full_gate={str(full_ok).lower()}\n")

    demand_full = args.strict or args.strict_full
    if args.strict_full and not full_ok:
        return 1
    return 0 if (scope_ok or not demand_full) else 1


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

    # Pass18: the two verdicts must stay DISTINCT. Collapsing them made
    # --strict permanently red in lean CI, which is how a real gate could be
    # mistaken for "impossible" and quietly dropped again.
    lean = assess(good_art, good_up, False)
    layered = (lean["ci_scope_gate_possible"] is True
               and lean["ci_full_gate_possible"] is False
               and lean["scope_problems"] == []
               and any("training stack" in p for p in lean["problems"]))
    ok &= layered
    print(f"  [{'ok' if layered else 'BAD'}] lean CI: scope=True full=False "
          "(contract is an explicit SKIP, not a missing input)")

    missing_contract = assess(
        good_art, [dict(good_up[0], exists=False)] + good_up[1:], False)
    scope_red = (not missing_contract["ci_scope_gate_possible"]
                 and not missing_contract["ci_full_gate_possible"])
    ok &= scope_red
    print(f"  [{'ok' if scope_red else 'BAD'}] missing contract source turns BOTH verdicts red")

    # The Pass17 list had 5 entries and missed four files that
    # verify_policy_bundle.load_contract() actually parses. Pin the closure.
    required = ("policy.rs", "duck-ipc-proto", "feetech.rs", "microduck_rl-develop")
    complete = (len(UPSTREAM_SOURCES) == 9
                and all(any(k in p for p in UPSTREAM_SOURCES) for k in required))
    ok &= complete
    print(f"  [{'ok' if complete else 'BAD'}] upstream closure lists all 9 parsed sources")
    print()
    print("self-test: " + ("PASS -- readiness logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
