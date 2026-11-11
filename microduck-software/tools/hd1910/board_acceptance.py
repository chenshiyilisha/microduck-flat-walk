#!/usr/bin/env python3
"""B1: scripted board-acceptance checklist + evidence collection skeleton.

Why this exists (2026-11-11, four-source comparison, follow-up B1)
------------------------------------------------------------------
docs/hardware/microduck-Radxa上电验收清单-2026-11-06.md has real PASS/FAIL
criteria for sections 0-9, but it was drafted before SSOT 订正⑬/㉑/㉔/㉕.
Several of its statements are now wrong as *current* instructions:

  - §0/§1.1 say Radxa ZERO 3W 2GB; SSOT pins 1GB / no eMMC.
  - §0/§1.2 say kissqy HAT; SSOT ㉕ pins the 人人 C1 board.
  - §5 describes a HAT I2C head IMU, while 路① gets its 61-dim angular
    velocity from the bus IMU at ID200.
  - §6.2 explicitly uses DuckBuddy (feetech_hls) config keys.
  - §7 uses `uv run publish`, but 路① deploys through R17→V167 console.

Turning that document into an executable checklist without marking those
would manufacture false green. So every item carries an `authority` and a
first-party note, and SUPERSEDED / LINE_MISMATCH entries are reported as
NOT CURRENT -- never as pass criteria to execute verbatim.

This tool NEVER talks to a robot, opens a serial port, or evaluates a
criterion. --record only stores an observation plus the sha256 of an
evidence file, with verdict COLLECTED. Signoff stays in
closure_contract.json (single owner), and UNVERIFIED is never a PASS.

Cross-contract assertion (open-microduck check_book.py style): every
status=UNVERIFIED contract in closure_contract.json must be referenced by
at least one check, and no check may reference an unknown contract id.

Single source of truth: board_acceptance_contract.json. Stdlib only.

Usage (cwd = microduck-software):
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --check
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --check --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --check --ship-gate
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --list
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --record BA-3-2 --value "ttyS2 present" --evidence path/to/dmesg.txt
    .venv-mjlab/Scripts/python.exe tools/hd1910/board_acceptance.py --selftest
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
ROOT = SOFTWARE.parent
CONTRACT = HERE / "board_acceptance_contract.json"
CLOSURE = HERE / "closure_contract.json"
DEFAULT_EVIDENCE = SOFTWARE / "out" / "board_acceptance"
CHECK_FIELDS = ("id", "section", "title", "pass_criterion", "command",
                "authority", "authority_note", "superseded_by",
                "evidence_kind", "closure_refs")
MARK = re.compile(r"INCONCLUSIVE_[A-Z_]+")
BASE_SECTIONS = {"§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"}


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def load_closure(path: Path = CLOSURE) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_contract_ids(closure: dict) -> set[str]:
    return {c["id"] for c in closure.get("contracts", [])
            if c.get("status") == "UNVERIFIED"}


def all_contract_ids(closure: dict) -> set[str]:
    return {c["id"] for c in closure.get("contracts", [])}


def validate(data: dict, closure: dict | None = None) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    rule = data.get("rule") or ""
    if "NOT_SHIPPABLE" not in rule or "UNVERIFIED" not in rule:
        p.append("rule must state that UNVERIFIED is NOT_SHIPPABLE")
    checks = data.get("checks") or []
    if not checks:
        p.append("empty checks: refusing to call an empty checklist verified")
        return p
    kinds = set(data.get("authority_kinds") or [])
    ids = [c.get("id", "") for c in checks]
    if len(ids) != len(set(ids)):
        p.append("duplicate check ids")
    declared = set(data.get("required_check_ids") or [])
    if not declared:
        p.append("required_check_ids must explicitly register the checklist")
    else:
        missing = sorted(declared - set(ids))
        extra = sorted(set(ids) - declared)
        if missing:
            p.append("registered checks missing from checklist: %s" % missing)
        if extra:
            p.append("checklist has unregistered ids: %s" % extra)
    sections = {c.get("section") for c in checks}
    missing_sections = sorted(BASE_SECTIONS - sections)
    if missing_sections:
        p.append("checklist does not cover sections: %s" % missing_sections)
    known_refs = all_contract_ids(closure) if closure else None
    referenced: set[str] = set()
    for c in checks:
        cid = c.get("id", "<no id>")
        for k in CHECK_FIELDS:
            if k not in c:
                p.append("%s missing field %s" % (cid, k))
        if c.get("authority") not in kinds:
            p.append("%s invalid authority %r" % (cid, c.get("authority")))
        if not str(c.get("authority_note") or "").strip():
            p.append("%s empty authority_note" % cid)
        if c.get("authority") in ("SUPERSEDED", "LINE_MISMATCH") \
                and not (c.get("superseded_by") or []):
            p.append("%s is %s but names no superseding source" %
                     (cid, c["authority"]))
        if c.get("authority") == "CURRENT" and (c.get("superseded_by") or []):
            p.append("%s is CURRENT but also declares superseded_by" % cid)
        if not (c.get("evidence_kind") or []):
            p.append("%s empty evidence_kind" % cid)
        for ref in c.get("closure_refs") or []:
            referenced.add(ref)
            if known_refs is not None and ref not in known_refs:
                p.append("%s references unknown closure contract %s" % (cid, ref))
    if closure is not None:
        uncovered = sorted(open_contract_ids(closure) - referenced)
        if uncovered:
            p.append("UNVERIFIED contracts with no board check: %s" % uncovered)
    if not (data.get("coverage_rule") or "").strip():
        p.append("coverage_rule must be explicit")
    if not (data.get("record_rule") or "").strip():
        p.append("record_rule must be explicit")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be explicitly false")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be non-empty")
    signoff = data.get("signoff") or {}
    if signoff.get("status") == "PASS" and not (signoff.get("evidence") or []):
        p.append("signoff claims PASS without evidence")
    return p


def overall_verdict(data: dict, collected: int = 0) -> str:
    """Evidence alone never signs off: signoff stays in closure_contract.json."""
    if (data.get("signoff") or {}).get("status") != "PASS":
        return "NOT_SHIPPABLE"
    if collected < 1:
        return "NOT_SHIPPABLE"
    return "SHIPPABLE"


def collect_evidence(evidence_dir: Path) -> list[str]:
    out: list[str] = []
    if not evidence_dir.is_dir():
        return out
    for p in sorted(evidence_dir.glob("*.json")):
        try:
            rec = json.loads(io.open(p, encoding="utf-8").read())
        except (ValueError, OSError):
            continue
        if rec.get("verdict") == "COLLECTED" and rec.get("id"):
            out.append(rec["id"])
    return out


def record(data: dict, cid: str, value: str, evidence: Path,
           evidence_dir: Path) -> tuple[int, str]:
    if cid not in {c["id"] for c in data["checks"]}:
        return 1, "unknown check id %s" % cid
    if not evidence.is_file():
        return 1, "evidence file does not exist: %s" % evidence
    payload = {
        "id": cid,
        "value": value,
        "verdict": "COLLECTED",
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "evidence_path": str(evidence),
        "evidence_sha256": sha256_of(evidence),
        "evidence_bytes": evidence.stat().st_size,
        "note": "COLLECTED is not PASS; signoff lives in closure_contract.json",
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / ("%s.json" % cid)
    io.open(out, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0, "recorded %s: COLLECTED (evidence sha256=%s)" % (
        cid, payload["evidence_sha256"][:16])


def report(data: dict, problems: list[str], collected: list[str]) -> dict:
    counts: dict[str, int] = {}
    for c in data["checks"]:
        k = c.get("authority", "?")
        counts[k] = counts.get(k, 0) + 1
    return {
        "tool": "board_acceptance.py",
        "contract_sha256": sha256_of(CONTRACT),
        "check_ids": [c["id"] for c in data["checks"]],
        "authority_counts": counts,
        "not_current_ids": [c["id"] for c in data["checks"]
                            if c["authority"] != "CURRENT"],
        "collected_evidence": collected,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": overall_verdict(data, len(collected)),
        "live_hardware_accessed": False,
        "not_proof_of": data["scope"]["not_proof_of"],
        "known_gaps": data["scope"]["known_gaps"],
        "scope": "上板验收清单 + 证据采集骨架；--record 只写 COLLECTED，不自动判 PASS",
    }


def selftest() -> int:
    data = load()
    closure = load_closure()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data, closure)
    ck("盘上清单结构自校验通过", not base, "; ".join(base[:3]))
    ck("5 个 UNVERIFIED 悬案全部被清单引用",
       open_contract_ids(closure) <= {r for c in data["checks"]
                                      for r in c["closure_refs"]})
    ck("当前整体判 NOT_SHIPPABLE", overall_verdict(data) == "NOT_SHIPPABLE")
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("过时条目确实被标出来",
       any(c["authority"] == "SUPERSEDED" for c in data["checks"])
       and any(c["authority"] == "LINE_MISMATCH" for c in data["checks"])
       and any(c["authority"] == "BENCH_ONLY" for c in data["checks"]))
    ck("§7 的 publish 链如实标 LINE_MISMATCH",
       next(c for c in data["checks"] if c["id"] == "BA-7-1")["authority"]
       == "LINE_MISMATCH")
    ck("§0 的 2GB 如实标 SUPERSEDED",
       next(c for c in data["checks"] if c["id"] == "BA-0-1")["authority"]
       == "SUPERSEDED")

    good = copy.deepcopy(data)
    good["signoff"] = {"status": "PASS", "evidence": ["selftest synthetic"]}
    ck("正对照：人工签署 + 至少一条证据才 SHIPPABLE",
       overall_verdict(good, 1) == "SHIPPABLE")
    ck("负对照：只签署不采证据仍 NOT_SHIPPABLE",
       overall_verdict(good, 0) == "NOT_SHIPPABLE")
    ck("负对照：只采证据不签署仍 NOT_SHIPPABLE",
       overall_verdict(data, 5) == "NOT_SHIPPABLE")

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad, closure)))

    must_fail("负对照：删一条 check 必红", lambda d: d["checks"].pop())
    must_fail("负对照：新增一条未登记 check 必红",
              lambda d: d["checks"].append(dict(d["checks"][0], id="BA-GHOST")))
    must_fail("负对照：抹掉 required_check_ids 必红",
              lambda d: d.update({"required_check_ids": []}))
    must_fail("负对照：重复 id 必红",
              lambda d: d["checks"].append(copy.deepcopy(d["checks"][0])))
    must_fail("负对照：引用不存在的悬案 id 必红",
              lambda d: d["checks"][0]["closure_refs"].append("INCONCLUSIVE_GHOST"))
    must_fail("负对照：抹掉某悬案的全部引用必红",
              lambda d: [c.update({"closure_refs": []}) for c in d["checks"]])
    must_fail("负对照：SUPERSEDED 无覆盖来源必红",
              lambda d: next(c for c in d["checks"]
                             if c["authority"] == "SUPERSEDED").update(
                                 {"superseded_by": []}))
    must_fail("负对照：SUPERSEDED 无说明必红",
              lambda d: next(c for c in d["checks"]
                             if c["authority"] == "SUPERSEDED").update(
                                 {"authority_note": ""}))
    must_fail("负对照：CURRENT 却声明被覆盖必红",
              lambda d: next(c for c in d["checks"]
                             if c["authority"] == "CURRENT").update(
                                 {"superseded_by": ["SSOT_13"]}))
    must_fail("负对照：非法 authority 必红",
              lambda d: d["checks"][0].update({"authority": "MAGIC"}))
    must_fail("负对照：空 checks 必红", lambda d: d.update({"checks": []}))
    must_fail("负对照：抹掉 rule 语义必红", lambda d: d.update({"rule": "all good"}))
    must_fail("负对照：scope 声称碰过硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("负对照：删掉 coverage_rule 必红",
              lambda d: d.update({"coverage_rule": ""}))
    must_fail("负对照：signoff 无证据称 PASS 必红",
              lambda d: d["signoff"].update({"status": "PASS"}))

    # Real CLI run: --record must store COLLECTED and MUST NOT turn the
    # ship gate green. A fake evidence file is a real file on disk.
    script = str(HERE / "board_acceptance.py")
    with tempfile.TemporaryDirectory(prefix="md_ba_") as td:
        tmp = Path(td)
        ev = tmp / "dmesg.txt"
        ev.write_text("[  1.234] ttyS2 at MMIO 0x...\n", encoding="utf-8")
        edir = tmp / "evidence"
        rec = subprocess.run(
            [sys.executable, script, "--record", "BA-3-2", "--value", "ttyS2 present",
             "--evidence", str(ev), "--evidence-dir", str(edir)],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("真对照：CLI --record 落盘成功",
           rec.returncode == 0 and "COLLECTED" in rec.stdout,
           "rc=%d" % rec.returncode)
        rec_file = edir / "BA-3-2.json"
        payload = json.loads(rec_file.read_text(encoding="utf-8")) if rec_file.is_file() else {}
        ck("真对照：证据记录含文件 sha256 且 verdict=COLLECTED",
           payload.get("verdict") == "COLLECTED"
           and len(payload.get("evidence_sha256") or "") == 64)
        chk = subprocess.run(
            [sys.executable, script, "--check", "--evidence-dir", str(edir), "--json"],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        rep = json.loads(chk.stdout) if chk.returncode == 0 else {}
        ck("负对照：采了证据也不许 ship 变绿",
           rep.get("ship_verdict") == "NOT_SHIPPABLE"
           and "BA-3-2" in rep.get("collected_evidence", []))
        ship = subprocess.run(
            [sys.executable, script, "--check", "--evidence-dir", str(edir),
             "--ship-gate"],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("负对照：--ship-gate 有证据仍 rc=1", ship.returncode == 1)
        bad_id = subprocess.run(
            [sys.executable, script, "--record", "BA-DOES-NOT-EXIST",
             "--value", "x", "--evidence", str(ev), "--evidence-dir", str(edir)],
            cwd=str(SOFTWARE), capture_output=True, text=True)
        ck("负对照：--record 未知 id 必 rc=1", bad_id.returncode == 1)

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\nboard_acceptance selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: checklist structure + evidence skeleton; no serial, no bus, no robot.")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the checklist")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 unless signed off")
    ap.add_argument("--list", action="store_true", help="list checks, run nothing")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable report")
    ap.add_argument("--record", metavar="ID", default=None,
                    help="store one observation (never a PASS)")
    ap.add_argument("--value", metavar="TEXT", default="", help="observation text")
    ap.add_argument("--evidence", metavar="FILE", default=None,
                    help="path to an evidence file (its sha256 is recorded)")
    ap.add_argument("--evidence-dir", metavar="DIR", default=str(DEFAULT_EVIDENCE),
                    help="where COLLECTED records are stored")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    data = load()
    if args.record is not None:
        if not args.evidence:
            print("[FAIL] --record requires --evidence FILE")
            return 1
        rc, msg = record(data, args.record, args.value, Path(args.evidence),
                         Path(args.evidence_dir))
        print(msg if rc == 0 else "[FAIL] " + msg)
        return rc

    if args.list:
        for c in data["checks"]:
            print("%-8s %-4s %-14s %s" % (c["id"], c["section"],
                                          c["authority"], c["title"]))
        print("total = %d" % len(data["checks"]))
        return 0

    closure = load_closure()
    problems = validate(data, closure)
    collected = collect_evidence(Path(args.evidence_dir))
    rep = report(data, problems, collected)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("board_acceptance_contract.json sha256 = " + rep["contract_sha256"])
        print("checks = %d  authority = %s" %
              (len(rep["check_ids"]), json.dumps(rep["authority_counts"], ensure_ascii=False)))
        print("not-current ids = " + ", ".join(rep["not_current_ids"]))
        print("collected evidence = %d" % len(collected))
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship verdict = " + rep["ship_verdict"] + "  (COLLECTED != PASS)")
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate and rep["ship_verdict"] != "SHIPPABLE":
        if not args.json:
            print("SHIP GATE REFUSED: no signed-off board acceptance")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
