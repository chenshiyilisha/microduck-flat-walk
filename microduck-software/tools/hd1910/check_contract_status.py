#!/usr/bin/env python3
"""P2: contract status is DERIVED from the artifacts, never a prose snapshot.

Why this exists (2026-11-11)
---------------------------
`deploy_chain_contract.json#scope.known_gaps` used to say "line_labels.json
still has 20 --selftest tools as REPORT_ONLY" and "A1/A2/A3 ... not wired into
CI". Both were prose photographs of a measured state. Once B4 registered every
tool and B3 wired the meta guards into CI, the words were stale but nothing
turned red. That is the classic "green because the text never changes" failure.

This tool computes the state from three first-party sources:
  1. line_labels.json + tools/**/*.py  -> unlabelled --selftest tools
     (using the SAME line_contract.unlabelled_tools() run_all_gates.py calls)
  2. ci_meta_targets.derive(labels)    -> lean-CI guard list and its problems
  3. .github/workflows/deploy-gate.yml -> whether the meta-guard step is present

It then refuses any known_gaps item that hardcodes a measured count/status,
and requires the gap lists to cite this tool instead. Negative controls in
--selftest mutate each source and assert the derived value actually MOVES.

Stdlib only (lean CI installs nothing for this guard). No hardware access.

Usage (cwd = microduck-software):
    python tools/hd1910/check_contract_status.py --check
    python tools/hd1910/check_contract_status.py --check --json
    python tools/hd1910/check_contract_status.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
sys.path.insert(0, str(HERE))

import ci_meta_targets  # noqa: E402  (single derivation of the lean CI list)
import line_contract  # noqa: E402  (single derivation of the coverage gap)

LABELS = HERE / "line_labels.json"
CONTRACT = HERE / "deploy_chain_contract.json"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-gate.yml"
TOOLS = SOFTWARE / "tools"

META_STEP = "Meta guards -- derived stdlib-only list"

# These match *prose photographs of a measured state*, not policy statements.
SNAPSHOT_PATTERNS = (
    re.compile(r"\d+\s*个\s*(?:REPORT_ONLY|--selftest)"),
    re.compile(r"coverage gap\s*(?:补到|=)\s*\d+"),
    re.compile(r"\d+\s*条标签"),
    re.compile(r"(?:尚未|仍)\s*(?:未\s*)?接入\s*(?:CI|workflow)"),
)


def load_json(path: Path = LABELS) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def known_gaps_lists(contract: dict, labels: dict) -> dict[str, list[str]]:
    return {
        "deploy_chain_contract.json#scope.known_gaps":
            (contract.get("scope") or {}).get("known_gaps") or [],
        "line_labels.json#known_gaps": labels.get("known_gaps") or [],
    }


def derive(labels: dict, workflow_text: str, tools_dir: Path = TOOLS) -> dict:
    """Compute the live state; never copy a number from prose."""
    gap = line_contract.unlabelled_tools(labels, tools_dir)
    names, problems, _ = ci_meta_targets.derive(labels)
    return {
        "unlabelled_selftest_tools": gap,
        "unlabelled_count": len(gap),
        "ci_guard_count": len(names),
        "ci_derive_problems": problems,
        "ci_meta_step_present": (META_STEP in workflow_text
                                 and "ci_meta_targets.py --names" in workflow_text),
        "workflow_sha256": hashlib.sha256(workflow_text.encode("utf-8")).hexdigest(),
        "labels_sha256": sha256_of(LABELS),
    }


def validate(contract: dict, labels: dict, derived: dict) -> list[str]:
    p: list[str] = []
    p.extend("ci_meta_targets.derive: %s" % x for x in derived["ci_derive_problems"])
    if not derived["ci_meta_step_present"]:
        p.append("workflow no longer contains the derived meta-guard step")
    for owner, gaps in known_gaps_lists(contract, labels).items():
        for item in gaps:
            for pat in SNAPSHOT_PATTERNS:
                if pat.search(item):
                    p.append("hardcoded status snapshot in %s: %s" % (owner, item))
        if not any("check_contract_status.py" in x for x in gaps):
            p.append("%s must cite check_contract_status.py (the derived report)" % owner)
    return p


def report(contract: dict, labels: dict, workflow_text: str,
           tools_dir: Path = TOOLS) -> dict:
    derived = derive(labels, workflow_text, tools_dir)
    problems = validate(contract, labels, derived)
    return {
        "tool": "check_contract_status.py",
        "sources": {
            "line_labels.json": str(LABELS.relative_to(SOFTWARE).as_posix()),
            "deploy_chain_contract.json": str(CONTRACT.relative_to(SOFTWARE).as_posix()),
            "workflow": ".github/workflows/deploy-gate.yml",
        },
        "derived": derived,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "live_hardware_accessed": False,
        "scope": "契约状态的派生一致性；不判整机可签收、不消任何 INCONCLUSIVE 悬案",
    }


def _load_all() -> tuple[dict, dict, str]:
    return load_json(CONTRACT), load_json(LABELS), io.open(
        WORKFLOW, encoding="utf-8").read()


def selftest() -> int:
    contract, labels, wf = _load_all()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = report(contract, labels, wf)
    ck("盘上三份一手源派生后结构自校验通过", not base["problems"],
       "; ".join(base["problems"][:2]))
    d0 = base["derived"]
    ck("真对照：coverage gap 从源码实算为 0", d0["unlabelled_count"] == 0,
       str(d0["unlabelled_selftest_tools"][:3]))
    ck("真对照：CI 护栏名单非空且 meta step 在 workflow 里",
       d0["ci_guard_count"] >= 9 and d0["ci_meta_step_present"])

    # 1) deleting ONE label must move the derived count (a quantity that moves
    #    is the only proof that we are measuring, not echoing a constant).
    bad_labels = copy.deepcopy(labels)
    victim = bad_labels["tools"].pop(0)["path"]
    d1 = derive(bad_labels, wf)
    ck("负对照：删一条标签 ⇒ 未登记数从 0 变 1", d1["unlabelled_count"] == 1,
       "victim=%s" % victim)
    ck("负对照：删掉的正是被删那条路径",
       d1["unlabelled_selftest_tools"] == [victim])

    # 2) removing the CI step must flip the derived boolean.
    no_step = wf.replace(META_STEP, "some other step")
    d2 = derive(labels, no_step)
    ck("负对照：workflow 删掉 meta step ⇒ ci_meta_step_present=False",
       d2["ci_meta_step_present"] is False)
    ck("负对照：workflow 变了 sha 也变（不是读缓存）",
       d2["workflow_sha256"] != d0["workflow_sha256"])
    ck("负对照：meta step 消失必判红",
       any("meta-guard step" in x for x in validate(contract, labels, d2)))

    # 3) restoring a prose snapshot must be rejected.
    stale = copy.deepcopy(contract)
    stale["scope"]["known_gaps"].append(
        "line_labels.json 仍有 20 个 --selftest 工具为 REPORT_ONLY")
    ck("负对照：把『20 个 REPORT_ONLY』写回契约必红",
       any("hardcoded status snapshot" in x
           for x in validate(stale, labels, d0)))
    stale2 = copy.deepcopy(labels)
    stale2["known_gaps"].append("B4 已把 coverage gap 补到 0（46 条标签）")
    ck("负对照：标签契约里写死『46 条标签』必红",
       any("hardcoded status snapshot" in x
           for x in validate(contract, stale2, d0)))

    # 4) removing the citation must be rejected.
    no_cite = copy.deepcopy(contract)
    no_cite["scope"]["known_gaps"] = [
        x for x in no_cite["scope"]["known_gaps"]
        if "check_contract_status.py" not in x]
    ck("负对照：删掉派生工具指针必红",
       any("must cite" in x for x in validate(no_cite, labels, d0)))

    # 5) real CLI entry point (project rule: internal-function-only tests lie).
    cli = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                          "--check", "--json"],
                         cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("CLI 真跑：--check --json rc=0 且为纯 JSON",
       cli.returncode == 0 and cli.stdout.strip().startswith("{"),
       "rc=%s %s" % (cli.returncode, cli.stderr[-120:]))

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name,
                               ("  <- " + note) if note else ""))
    bad = [n for n, ok, _ in checks if not ok]
    print("\ncheck_contract_status selftest: %d/%d passed"
          % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("scope: derived contract status only; no hardware, no sign-off.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk state")
    ap.add_argument("--selftest", action="store_true", help="negative controls, no hardware")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    contract, labels, wf = _load_all()
    rep = report(contract, labels, wf)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        d = rep["derived"]
        print("unlabelled --selftest tools = %d (derived from line_labels.json + tools/)"
              % d["unlabelled_count"])
        for x in d["unlabelled_selftest_tools"]:
            print("  - " + x)
        print("lean CI meta guards = %d (derived by ci_meta_targets.py)" % d["ci_guard_count"])
        print("workflow meta step present = %s" % d["ci_meta_step_present"])
        print("workflow sha256 = %s" % d["workflow_sha256"])
        for x in rep["problems"]:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("scope: " + rep["scope"])
    return 0 if not rep["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
