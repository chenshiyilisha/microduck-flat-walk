#!/usr/bin/env python3
"""C3: read-only bridge from B1 COLLECTED evidence to the A2 closure contract.

Why this exists (2026-11-11)
----------------------------
``board_acceptance.py --record`` writes an observation with the evidence file's
sha256 and marks it ``COLLECTED``. ``closure_contract.json`` keeps the open
markers with ``evidence: []`` and a human ``signoff``. Nothing connected the
two: an engineer standing at the robot could collect a stack of evidence files
and still have no way to see, per open question, what was measured, what is
still owed, and what would actually close it.

This is a READ-ONLY report, shaped like replica-kit/docs/open-gaps.md's four
columns (Gap / Evidence now / Measurement / Closed when) plus its rule
"Do not freeze before measurements". It NEVER signs anything:

  * COLLECTED != PASS. A collection is a fact, not an acceptance verdict.
  * The mapping comes from board_acceptance_contract.json#checks[].closure_refs
    -- there is deliberately NO second mapping file (no second source of truth).
  * The final verdict is imported from check_closure.overall_verdict(), i.e.
    A2 remains the single owner of "is this closed".
  * A forged check id, a forged PASS record, a missing/mutated evidence file
    (with --verify) and a broken cross-contract link all turn the report red.

Stdlib only. No serial port, no bus, no robot, no training.

Usage (cwd = microduck-software):
    python tools/hd1910/link_evidence.py --check
    python tools/hd1910/link_evidence.py --check --json
    python tools/hd1910/link_evidence.py --check --evidence-dir DIR
    python tools/hd1910/link_evidence.py --check --verify
    python tools/hd1910/link_evidence.py --check --ship-gate
    python tools/hd1910/link_evidence.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
CONTRACT = HERE / "board_acceptance_contract.json"
CLOSURE = HERE / "closure_contract.json"
DEFAULT_EVIDENCE_DIR = SOFTWARE / "out" / "board_acceptance"
SHA = re.compile(r"^[0-9a-f]{64}$")


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_records(evidence_dir: Path) -> tuple[list[dict], list[str]]:
    """Parse only. Semantic checks live in validate_records() so BOTH the CLI
    path and an in-process caller get exactly the same assertions."""
    records: list[dict] = []
    problems: list[str] = []
    if not evidence_dir.is_dir():
        return records, []
    for p in sorted(evidence_dir.glob("*.json")):
        try:
            rec = json.loads(io.open(p, encoding="utf-8").read())
        except (ValueError, OSError) as e:
            problems.append("unreadable evidence record %s: %s" % (p.name, e))
            continue
        if not isinstance(rec, dict):
            problems.append("evidence record %s is not an object" % p.name)
            continue
        rec["_file"] = p.name
        records.append(rec)
    return records, problems


def validate_records(records: list[dict], check_ids: set[str],
                     verify: bool) -> list[str]:
    """One authoritative record validator, shared by every consumer."""
    p: list[str] = []
    for rec in records:
        name = rec.get("_file", "<record>")
        if rec.get("verdict") != "COLLECTED":
            p.append("%s: verdict %r is not COLLECTED (a record may not claim PASS)"
                     % (name, rec.get("verdict")))
        if not SHA.fullmatch(str(rec.get("evidence_sha256", ""))):
            p.append("%s: missing/invalid evidence_sha256" % name)
        if not isinstance(rec.get("evidence_bytes"), int):
            p.append("%s: missing evidence_bytes" % name)
        if rec.get("id") not in check_ids:
            p.append("%s: unregistered check id %r" % (name, rec.get("id")))
        if verify:
            path = Path(str(rec.get("evidence_path", "")))
            if not path.is_file():
                p.append("%s: evidence file vanished: %s" % (name, path))
                continue
            actual = sha256_of(path)
            if actual != rec.get("evidence_sha256"):
                p.append("%s: evidence sha256 drift (%s != recorded %s)"
                         % (name, actual[:16], str(rec.get("evidence_sha256"))[:16]))
            if path.stat().st_size != rec.get("evidence_bytes"):
                p.append("%s: evidence byte count drift" % name)
    return p


def build_links(board: dict, closure: dict) -> tuple[dict[str, list[str]], list[str]]:
    """contract id -> check ids, derived ONLY from closure_refs."""
    p: list[str] = []
    known = {c["id"] for c in closure.get("contracts", [])}
    check_ids = {c["id"] for c in board.get("checks", [])}
    links: dict[str, list[str]] = {k: [] for k in known}
    for c in board.get("checks", []):
        for ref in c.get("closure_refs") or []:
            if ref not in known:
                p.append("%s references unknown contract %s" % (c.get("id"), ref))
                continue
            links[ref].append(c["id"])
    open_ids = {c["id"] for c in closure.get("contracts", [])
                if c.get("status") == "UNVERIFIED"}
    uncovered = sorted(open_ids - {k for k, v in links.items() if v})
    if uncovered:
        p.append("UNVERIFIED contracts with no linked board check: %s" % uncovered)
    if not check_ids:
        p.append("board checklist is empty")
    return links, p


def validate(board: dict, closure: dict, records: list[dict],
             verify: bool) -> list[str]:
    _, p = build_links(board, closure)
    check_ids = {c["id"] for c in board.get("checks", [])}
    p.extend(validate_records(records, check_ids, verify))
    rule = board.get("record_rule") or ""
    if "COLLECTED" not in rule or "PASS" not in rule:
        p.append("record_rule must state COLLECTED is not PASS")
    return p


def build_gaps(board: dict, closure: dict, records: list[dict],
               links: dict[str, list[str]]) -> list[dict]:
    by_check: dict[str, list[dict]] = {}
    for rec in records:
        by_check.setdefault(rec.get("id", ""), []).append(rec)
    checks = {c["id"]: c for c in board.get("checks", [])}
    gaps: list[dict] = []
    for c in closure.get("contracts", []):
        cid = c["id"]
        linked = sorted(links.get(cid, []))
        collected = [r for k in linked for r in by_check.get(k, [])]
        evidence_now = ([{"check_id": r.get("id"), "value": r.get("value"),
                          "sha256": str(r.get("evidence_sha256", ""))[:16],
                          "bytes": r.get("evidence_bytes"),
                          "recorded_at": r.get("recorded_at"),
                          "verdict": "COLLECTED"} for r in collected]
                       if collected else [])
        gaps.append({
            "gap": cid,
            "status": c.get("status"),
            "evidence_now": evidence_now,
            "measurement": c.get("still_owed") or [],
            "closed_when": {
                "board_acceptance_required": c.get("board_acceptance_required") or [],
                "evidence_kind": c.get("evidence_kind") or [],
                "signoff": c.get("signoff"),
                "signoff_owner": "closure_contract.json (本工具不签字)",
            },
            "linked_checks": linked,
            "linked_check_titles": [checks[k]["title"] for k in linked if k in checks],
            "collected_count": len(collected),
            "awaiting_signoff": True,
            "note": ("COLLECTED != PASS；即便所有 linked_checks 都采证，仍需 A2 人工签署"
                     if c.get("status") == "UNVERIFIED" else "史料条目，无需上板动作"),
        })
    return gaps


def report(board: dict, closure: dict, records: list[dict],
           problems: list[str], verify: bool, evidence_dir: Path) -> dict:
    links, _ = build_links(board, closure)
    gaps = build_gaps(board, closure, records, links)
    open_n = sum(1 for g in gaps if g["status"] == "UNVERIFIED")
    covered = sum(1 for g in gaps if g["collected_count"] > 0 and g["status"] == "UNVERIFIED")
    linked_ids = {k for v in links.values() for k in v}
    unlinked_evidence = [
        {"check_id": r.get("id"), "file": r.get("_file"),
         "verdict": r.get("verdict"),
         "note": "该判据的 closure_refs 为空；证据如实留档，但不闭合任何悬案"}
        for r in records if r.get("id") not in linked_ids
    ]
    # A2 is the single owner of the closing verdict. Import, do not re-derive.
    sys.path.insert(0, str(HERE))
    import check_closure  # noqa: E402
    a2_verdict = check_closure.overall_verdict(closure)
    return {
        "tool": "link_evidence.py",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "evidence_dir": str(evidence_dir),
        "contract_sha256": sha256_of(CONTRACT),
        "closure_sha256": sha256_of(CLOSURE),
        "links": {k: sorted(v) for k, v in links.items()},
        "collected_records": len(records),
        "unlinked_evidence": unlinked_evidence,
        "gaps": gaps,
        "open_contracts": open_n,
        "open_contracts_with_evidence": covered,
        "evidence_sufficiency": ("SUFFICIENT_FOR_REVIEW" if covered == open_n and open_n
                                  else "INSUFFICIENT"),
        "verified_file_hashes": verify,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "a2_verdict": a2_verdict,
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "scope": "B1→A2 只读证据桥接；COLLECTED != PASS，签字权归 closure_contract.json",
        "not_proof_of": ["任何悬案已闭合", "证据已由人工复核", "整机可签收", "策略可上真机"],
    }


def selftest() -> int:
    board, closure = load(), load(CLOSURE)
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    links, lp = build_links(board, closure)
    ck("盘上跨契约链接自校验通过", not lp, "; ".join(lp[:2]))
    ck("每个 UNVERIFIED 悬案都有 B1 判据链接",
       all(links.get(c["id"]) for c in closure["contracts"]
           if c["status"] == "UNVERIFIED"))
    ck("链接只从 closure_refs 派生，不存在第二份映射文件",
       not (HERE / "evidence_links.json").exists())

    def must_fail(name: str, mutate_board, mutate_closure=None, recs=None) -> None:
        b = copy.deepcopy(board)
        c = copy.deepcopy(closure)
        if mutate_board:
            mutate_board(b)
        if mutate_closure:
            mutate_closure(c)
        ck(name, bool(validate(b, c, recs or [], False)))

    must_fail("负对照：引用不存在的悬案必红",
              lambda b: b["checks"][0]["closure_refs"].append("INCONCLUSIVE_GHOST"))
    must_fail("负对照：抹掉某悬案全部引用必红",
              lambda b: [x.update({"closure_refs": []}) for x in b["checks"]])
    must_fail("负对照：伪造未登记 check id 的证据必红",
              None, None,
              [{"id": "BA-GHOST", "verdict": "COLLECTED",
                "evidence_sha256": "a" * 64, "evidence_bytes": 1, "_file": "ghost.json"}])
    must_fail("负对照：证据记录自称 PASS 必红",
              None, None,
              [{"id": "BA-0-1", "verdict": "PASS",
                "evidence_sha256": "a" * 64, "evidence_bytes": 1, "_file": "fake.json"}])
    must_fail("负对照：抹掉 record_rule 的 COLLECTED!=PASS 语义必红",
              lambda b: b.update({"record_rule": "everything passes"}))
    must_fail("负对照：新增一条 UNVERIFIED 却无链接必红",
              None,
              lambda c: c["contracts"].append(
                  dict(c["contracts"][0], id="INCONCLUSIVE_GHOST", evidence=[])))

    # Real CLI: create a genuine evidence file, record it with B1, then bridge.
    script = str(HERE / "link_evidence.py")
    with tempfile.TemporaryDirectory(prefix="md_link_") as td:
        tmp = Path(td)
        ev = tmp / "dmesg.txt"
        ev.write_text("[  1.234] ttyS2 at MMIO 0x...\n", encoding="utf-8")
        edir = tmp / "evidence"
        # BA-4-2 has closure_refs -> INCONCLUSIVE_RATE_MISMATCH; BA-3-2 has
        # none. Both must be handled honestly (do not assume a --record sample
        # is a linked check just because B1's own selftest uses it).
        rec = subprocess.run(
            [sys.executable, str(HERE / "board_acceptance.py"), "--record", "BA-4-2",
             "--value", "scope capture", "--evidence", str(ev),
             "--evidence-dir", str(edir)],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("真对照：B1 --record 真的落盘一条 COLLECTED", rec.returncode == 0)
        rec2 = subprocess.run(
            [sys.executable, str(HERE / "board_acceptance.py"), "--record", "BA-3-2",
             "--value", "ttyS2 present", "--evidence", str(ev),
             "--evidence-dir", str(edir)],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("真对照：无悬案链接的判据也能如实留档", rec2.returncode == 0)

        js = subprocess.run([sys.executable, script, "--check",
                             "--evidence-dir", str(edir), "--json"],
                            cwd=str(SOFTWARE), capture_output=True, text=True)
        rep = json.loads(js.stdout) if js.returncode == 0 else {}
        ck("真对照：桥接报告可读且结构 PASS",
           js.returncode == 0 and rep.get("structure_verdict") == "PASS",
           "" if js.returncode == 0 else js.stdout[-160:])
        target = next((g for g in rep.get("gaps", [])
                       if g["gap"] == "INCONCLUSIVE_RATE_MISMATCH"), {})
        ck("真对照：BA-4-2 的证据出现在 RATE_MISMATCH 的 Evidence now 列",
           rep.get("collected_records") == 2
           and any(x["check_id"] == "BA-4-2" for x in target.get("evidence_now", [])))
        ck("真对照：BA-3-2 无链接证据单列，不塞进任何悬案",
           any(x["check_id"] == "BA-3-2"
               for x in rep.get("unlinked_evidence", []))
           and all(not any(x["check_id"] == "BA-3-2" for x in g["evidence_now"])
                   for g in rep.get("gaps", [])))
        ck("负对照：采了证据也不许把悬案判绿",
           rep.get("ship_verdict") == "NOT_SHIPPABLE"
           and rep.get("a2_verdict") == "NOT_SHIPPABLE"
           and all(g["awaiting_signoff"] for g in rep.get("gaps", [])))
        ck("四列表齐备（Gap/Evidence now/Measurement/Closed when）",
           all(k in target for k in ("gap", "evidence_now", "measurement", "closed_when")))

        ship = subprocess.run([sys.executable, script, "--check", "--ship-gate",
                               "--evidence-dir", str(edir)],
                              cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("负对照：--ship-gate 有证据仍 rc=1", ship.returncode == 1)

        ver = subprocess.run([sys.executable, script, "--check", "--verify",
                              "--evidence-dir", str(edir)],
                             cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("真对照：--verify 对未改动的证据文件通过", ver.returncode == 0,
           "" if ver.returncode == 0 else ver.stdout[-160:])
        ev.write_text("tampered\n", encoding="utf-8")
        ver_bad = subprocess.run([sys.executable, script, "--check", "--verify",
                                  "--evidence-dir", str(edir)],
                                 cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("负对照：证据文件被改后 --verify 必红", ver_bad.returncode == 1)

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\nlink_evidence selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: read-only evidence bridge; COLLECTED != PASS, no serial, no robot.")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build the four-column gap report")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 unless A2 says SHIPPABLE and evidence exists")
    ap.add_argument("--verify", action="store_true",
                    help="re-hash every evidence file; drift/missing is FAIL")
    ap.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR),
                    help="directory holding B1 COLLECTED json records")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.check:
        ap.print_help()
        return 2

    board, closure = load(), load(CLOSURE)
    evidence_dir = Path(args.evidence_dir)
    records, rec_problems = collect_records(evidence_dir)
    problems = rec_problems + validate(board, closure, records, args.verify)
    rep = report(board, closure, records, problems, args.verify, evidence_dir)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("link_evidence: B1 COLLECTED -> A2 closure (read-only)")
        print("evidence dir = %s  records = %d  verified = %s"
              % (rep["evidence_dir"], rep["collected_records"], args.verify))
        print("open contracts = %d  with evidence = %d  sufficiency = %s"
              % (rep["open_contracts"], rep["open_contracts_with_evidence"],
                 rep["evidence_sufficiency"]))
        print("\n%-38s %-6s %-8s %s" % ("Gap", "status", "collected", "linked checks"))
        for g in rep["gaps"]:
            print("%-38s %-6s %-8d %s"
                  % (g["gap"], g["status"], g["collected_count"],
                     ", ".join(g["linked_checks"]) or "-"))
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("a2 verdict = %s  ship verdict = %s  (COLLECTED != PASS)"
              % (rep["a2_verdict"], rep["ship_verdict"]))
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate:
        ok = (rep["a2_verdict"] == "SHIPPABLE" and rep["collected_records"] > 0)
        if not ok:
            if not args.json:
                print("SHIP GATE REFUSED: A2 still %s; %d COLLECTED record(s) "
                      "are not a sign-off" % (rep["a2_verdict"], rep["collected_records"]))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
