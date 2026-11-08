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

Pass19 (2026-11-08): even a fully supplied checkout is worthless if GitHub
never registers the workflow at all. Pass13-18 kept deploy-gate.yml at
microduck-software/.github/workflows/ (a SUBDIRECTORY), and never pushed it:
GET /repos/.../actions/workflows returned total_count=0 and
GET /contents/.github/workflows returned 404. GitHub discovers workflows
ONLY in <repo-root>/.github/workflows (docs.github.com quickstart: "For GitHub
to discover any GitHub Actions workflows in your repository, you must save the
workflow files in a directory called .github/workflows"). CI cannot guard its
own existence -- if the file is misplaced, no job runs to complain -- so this
LOCAL probe (--strict) plus a pytest test pin the placement.

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
import re
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
WORKFLOW_REL = ".github/workflows/deploy-gate.yml"

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


def _eol_only_drift(path: Path, stored_sha: str | None) -> bool:
    """Pass19: distinguish a CRLF/LF mismatch from real content bitrot."""
    if not stored_sha or not path.is_file():
        return False
    raw = path.read_bytes()
    return (b"\r\n" in raw
            and hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == stored_sha)


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


def _repo_root(root: Path) -> tuple[Path, str]:
    """Find the git root. `root` is the microduck-software subdirectory."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=root,
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()), "git"
    except (OSError, subprocess.TimeoutExpired):
        pass
    # `git archive` copies have no .git; the repo root is still root.parent.
    return root.parent, "fallback-parent"


# Pass20 / loop R4: a hard-coded .onnx path in the workflow is a THIRD copy
# of the input list (bundle.json is the first, this probe's closure the
# second). Negative control proved it can rot in silence: pointing the CI
# gate's ground_pick at a stale onnx left `--strict`, pytest and
# provenance --verify ALL green. So the gate must read targets from the bundle
# via tools/hd1910/ci_gate_targets.py. Text-only on purpose (no PyYAML).
_HARDCODED_TARGET = re.compile(
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]*\.(?:onnx|toml)")
_HARDCODED_KP = re.compile(r"--expect-kp\s+\d+")


def _code_lines(text: str) -> str:
    """Strip YAML comments: prose describing a path is not a hard-coded target.

    The real third copy lived inside the `run: |` shell block, never in a
    comment. Keeping comments out avoids flagging the workflow's own history
    notes (which legitimately mention `artifacts/flat_walk/*.onnx`).
    """
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


def gate_target_problems(text: str) -> list[str]:
    """Pure text check: CI gate targets must come from the bundle, not literals."""
    out: list[str] = []
    code = _code_lines(text)
    literals = sorted({m.group(0) for m in _HARDCODED_TARGET.finditer(code)})
    if literals:
        out.append(
            "CI GATE TARGETS HARD-CODED: workflow names .onnx/.toml paths literally "
            f"({', '.join(literals[:3])}{' ...' if len(literals) > 3 else ''}) -- "
            "these silently diverge from out/hd1910_kp8_deploy_bundle.json; "
            "read them with tools/hd1910/ci_gate_targets.py --sh instead")
    if _HARDCODED_KP.search(code):
        out.append(
            "CI GATE --expect-kp HARD-CODED: read it from bundle.plant via "
            "ci_gate_targets.py (GATE_EXPECT_KP) instead of a literal")
    if "pre_deploy_check.py" in code and "ci_gate_targets.py" not in code:
        out.append(
            "CI GATE NOT BUNDLE-DRIVEN: workflow runs pre_deploy_check.py but "
            "never sources ci_gate_targets.py, so its targets have no single "
            "source of truth")
    return out


def probe_workflow(root: Path) -> dict:
    """Is the CI workflow somewhere GitHub can actually DISCOVER it?

    A workflow file in a subdirectory looks like CI but is never registered.
    This must be a LOCAL guard: GitHub cannot run a job to report that no job
    can run. Borderline cases (root workflow missing, present but not a valid
    workflow text, or an orphan copy in a subdirectory) all become problems.
    Also checks (Pass20) that the gate reads its targets from the bundle.
    """
    repo, how = _repo_root(root)
    wf = repo / WORKFLOW_REL
    exists = wf.is_file()
    valid = False
    gate_problems: list[str] = []
    if exists:
        text = wf.read_text(encoding="utf-8", errors="replace")
        # Deliberately text-only: no PyYAML in the lean CI dependency set.
        valid = ("on:" in text and "jobs:" in text
                 and "working-directory:" in text)
        gate_problems = gate_target_problems(text)

    # Only two directory levels are scanned (this repo's layout), rather than
    # rglob over the whole tree -- the local workspace contains .venv-mjlab and
    # large third-party snapshots under .upstream/.
    orphans: list[str] = []
    for depth in (1, 2):
        prefix = "/".join(["*"] * depth)
        for ext in ("yml", "yaml"):
            for p in repo.glob(f"{prefix}/.github/workflows/*.{ext}"):
                rel = p.relative_to(repo)
                parts = rel.parts
                if ".upstream" in parts or ".git" in parts or "third_party" in parts:
                    continue
                if any(seg.startswith(".venv") for seg in parts):
                    continue
                orphans.append(rel.as_posix())

    return {
        "repo_root": str(repo),
        "repo_root_source": how,
        "root_workflow": WORKFLOW_REL,
        "root_workflow_exists": exists,
        "root_workflow_valid": valid,
        "orphan_workflows": sorted(set(orphans)),
        "gate_target_problems": gate_problems,
    }


def workflow_problems(wf: dict) -> list[str]:
    """Pure logic: turn a workflow-placement observation into problems."""
    out: list[str] = []
    # Pass20: a stale/hard-coded third copy of the onnx list is a silent
    # wrong-policy gate. Synthetic workflows built by tests may omit this key;
    # only a real probe() result carries it.
    out.extend(wf.get("gate_target_problems", []))
    if not wf.get("root_workflow_exists"):
        out.append(
            f"WORKFLOW NOT DISCOVERABLE: {WORKFLOW_REL} is missing at the repo "
            "root; GitHub only registers workflows in <repo-root>/.github/workflows")
    elif not wf.get("root_workflow_valid"):
        out.append(
            f"WORKFLOW NOT USABLE: {WORKFLOW_REL} exists but has no on:/jobs:/"
            "working-directory: content")
    for rel in wf.get("orphan_workflows", []):
        out.append(
            f"ORPHAN WORKFLOW: {rel} sits in a subdirectory -- GitHub will "
            "NEVER discover or run it; move it to <repo-root>/.github/workflows")
    return out


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
            hint = ("  <- EOL-ONLY difference (CRLF working tree vs LF committed "
                    "blob); check core.autocrlf / .gitattributes" if a.get("eol_only") else "")
            problems.append(f"artifact {name}: sha256 differs from bundle "
                            f"(bitrot or a stale bundle){hint}")
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
            "eol_only": _eol_only_drift(path, meta.get("sha256")),
        })

    upstream = [{"rel_path": rel, "exists": (root / rel).is_file()}
                for rel in UPSTREAM_SOURCES]
    training_stack = importlib.util.find_spec("mjlab_microduck") is not None
    out = assess(artifacts, upstream, training_stack)

    # Pass19: an undiscoverable workflow makes EVERY other input irrelevant.
    # It belongs in the scope verdict too (it is a committed-file problem, not
    # a missing heavy dependency), so --strict fails locally before shipping.
    wf = probe_workflow(root)
    wp = workflow_problems(wf)
    out["workflow"] = wf
    out["workflow_problems"] = wp
    if wp:
        out["scope_problems"] = wp + out["scope_problems"]
        out["problems"] = wp + out["problems"]
        out["ci_scope_gate_possible"] = False
        out["ci_full_gate_possible"] = False
        out["reason"] = ("CI workflow is NOT discoverable by GitHub -- "
                         + out["reason"])

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
    wf = report["workflow"]
    print(f"  workflow      : "
          f"{'DISCOVERABLE' if not report['workflow_problems'] else 'NOT DISCOVERABLE'}"
          f"  {wf['root_workflow']} (repo root via {wf['repo_root_source']})")
    for orphan in wf["orphan_workflows"]:
        print(f"  orphan workflow: {orphan}")
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
            fh.write(f"workflow_discoverable="
                     f"{str(not report['workflow_problems']).lower()}\n")

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

    # Pass19: GitHub only discovers workflows at <repo-root>/.github/workflows.
    # A misplaced workflow silently means "no CI at all", so every one of
    # these must produce a problem. These are LOCAL guards on purpose.
    good_wf = {"root_workflow_exists": True, "root_workflow_valid": True,
               "orphan_workflows": [], "root_workflow": WORKFLOW_REL}
    wf_cases = [
        ("workflow at repo root", good_wf, 0, ""),
        ("workflow file absent", dict(good_wf, root_workflow_exists=False), 1,
         "NOT DISCOVERABLE"),
        ("root file is not a workflow", dict(good_wf, root_workflow_valid=False), 1,
         "NOT USABLE"),
        ("orphan copy in subdirectory",
         dict(good_wf, orphan_workflows=[
             "microduck-software/.github/workflows/deploy-gate.yml"]),
         1, "ORPHAN WORKFLOW"),
    ]
    for label, wf, want_n, needle in wf_cases:
        got = workflow_problems(wf)
        good = (len(got) == want_n and (not needle or any(needle in p for p in got)))
        ok &= good
        print(f"  [{'ok' if good else 'BAD'}] {label}: "
              f"{len(got)} problem(s), expect {want_n}")

    # Pass20: THE workflow gate must be bundle-driven. A hard-coded onnx path
    # is a third copy of the input list that can rot in silence -- prove the
    # guard bites on every way someone could reintroduce one.
    clean_gate = (
        'run: |\n'
        '  python tools/hd1910/ci_gate_targets.py --bundle "$BUNDLE" --sh > "$SH"\n'
        '  . "$SH"\n'
        '  python tools/hd1910/pre_deploy_check.py --onnx "$GATE_WALK" '
        '--expect-kp "$GATE_EXPECT_KP"\n')
    gate_cases = [
        ("bundle-driven gate (clean)", clean_gate, 0, ""),
        ("hard-coded onnx path reintroduced",
         clean_gate + 'WALK="logs/rsl_rl/foo/walk.onnx"\n', 1, "HARD-CODED"),
        ("hard-coded toml path reintroduced",
         clean_gate + 'TOML="out/robotd_hd1910_mode0.toml"\n', 1, "HARD-CODED"),
        ("hard-coded --expect-kp literal",
         clean_gate + '  --expect-kp 16\n', 1, "--expect-kp HARD-CODED"),
        ("emitter call removed, gate still runs",
         clean_gate.replace("tools/hd1910/ci_gate_targets.py --bundle", "echo"),
         1, "NOT BUNDLE-DRIVEN"),
    ]
    for label, text, want_n, needle in gate_cases:
        got = workflow_problems(dict(good_wf, gate_target_problems=
                                     gate_target_problems(text)))
        good = (len(got) == want_n and (not needle or any(needle in p for p in got)))
        ok &= good
        print(f"  [{'ok' if good else 'BAD'}] {label}: "
              f"{len(got)} problem(s), expect {want_n}")

    print()
    print("self-test: " + ("PASS -- readiness logic wired correctly"
                           if ok else "FAIL -- negative control misclassified"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
