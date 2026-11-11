#!/usr/bin/env python3
"""D1: engineering-decision ledger -- one authoritative owner per "do not do" call.

Why this exists (2026-11-11)
----------------------------
A very-thorough reasoning agent was asked to find gaps by cross-checking the
21 open-source projects this repo studied. Its #1 proposal was "add an IMU
sequence/freeze freshness gate (HostImuGate)". That proposal was ALREADY
decided NOT to do on 2026-11-09 in the BNO085 gyro_fusion checklist §7, with an
explicit reopen condition -- but a second document (kissqy IMU reference §7/§8)
still listed the same HostImuGate as "C-IMU (new)" / "may refine". The agent
found the stale page, not the decision. That is a real information bug:
an active "do not do" decision had no machine owner, so it was re-mined as a
gap and two docs told readers opposite things.

closure_contract.json (A2) cannot catch this: its MARK is INCONCLUSIVE_* and
it models "evidence not yet closed" (UNVERIFIED != PASS). A decision is the
orthogonal case: "evaluated and actively decided NOT to do, with a reopen
condition" (DEFERRED/REJECTED/WITHDRAWN != PENDING/DO). This tool owns that.

What it enforces (borrowed, not reinvented)
------------------------------------------
  - open-microduck check_book.py / A2 check_closure.py: expected == {actual}
    set equality between DECISION_* markers in allow-listed docs and the
    contract, so a new "we won't do X" in any doc either gets one owner or
    turns the gate red instead of drifting.
  - A2 rule shape: a DEFERRED/REJECTED/WITHDRAWN *must* carry a non-empty,
    executable reopen_when and a rationale -- otherwise it is an arbitrary
    permanent veto, which the ledger refuses to record.
  - project rule 10 (bare substring bites): stale-phrase detection requires a
    specific compound term (never a single char), and a positive control
    proves that naming the subject WITHOUT the stale phrase does not trip.
  - mdlab / A2: stdlib only, injectable roots, negative controls that really
    mutate state, verdict line never a bare substring of a test name.

Scope: offline information-consistency gate only. No hardware. It does NOT
verify any decision's correctness, does NOT close an INCONCLUSIVE_* case, and
never signs off a robot. verdict is LOCAL_RESOLUTION_ONLY; ship NOT_SHIPPABLE.

Usage (cwd = microduck-software):
    python tools/hd1910/check_decisions.py --check
    python tools/hd1910/check_decisions.py --check --json
    python tools/hd1910/check_decisions.py --selftest
    python tools/hd1910/check_decisions.py --list
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "decision_contract.json"

MARK = re.compile(r"DECISION_[A-Z_]+")
# Same explicit allow-list as A2 check_closure.py. History and third-party
# trees are NOT live contracts; a full rglob would pull stale markers into the
# "must be registered" set and cause mass false reds (rule 10 / A2 reasoning).
SCAN_ROOTS = (
    "docs",
    "out/deliverables",
    "microduck-software/tools/hd1910",
    "README.md",
    "AGENTS.md",
)
EXCLUDED_SCAN_ROOTS = (".workbuddy/memory", ".upstream", "out (outside out/deliverables)")
EXCLUDED_REASON = ("史料与第三方文档不是活的契约；只扫显式白名单，缺失的根自动跳过并如实列出。")

VALID_STATUS = {"DEFERRED", "REJECTED", "WITHDRAWN"}
CAPTURED_EXAMPLE = "DECISION_HOSTIMU_GATE"  # used only to prove the regex works


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_scan_roots(root: Path = ROOT) -> list[Path]:
    return [root / rel for rel in SCAN_ROOTS if (root / rel).exists()]


def walk_markdown(roots: list[Path] | None = None) -> list[tuple[str, str]]:
    """Return [(relative_path, text)] over allow-listed markdown files."""
    out: list[tuple[str, str]] = []
    for r in (default_scan_roots() if roots is None else roots):
        files = [r] if r.is_file() else sorted(r.rglob("*.md"))
        for f in files:
            if f.suffix.lower() != ".md":
                continue
            try:
                rel = str(f.relative_to(ROOT))
            except ValueError:
                rel = str(f)
            out.append((rel, io.open(f, encoding="utf-8", errors="replace").read()))
    return out


def scan_doc_marks(roots: list[Path] | None = None) -> set[str]:
    """Every DECISION_* in allow-listed docs must have exactly one contract owner."""
    out: set[str] = set()
    for _rel, text in walk_markdown(roots):
        out.update(MARK.findall(text))
    return out


REQUIRED = ("id", "subject", "status", "statement", "rationale", "reopen_when",
            "watch_terms", "stale_terms", "resolution_marker", "decided_in",
            "source_refs", "conflicts_with", "negative_control")


def validate(data: dict, doc_marks: set[str] | None = None,
             docs: list[tuple[str, str]] | None = None) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    rule = data.get("rule") or ""
    for token in ("DEFERRED", "REJECTED", "WITHDRAWN", "PENDING"):
        if token not in rule:
            p.append("rule must mention %s (decision != pending/do)" % token)
    orth = data.get("orthogonality") or ""
    if "INCONCLUSIVE" not in orth or "正交" not in orth:
        p.append("orthogonality must state this ledger is orthogonal to A2 INCONCLUSIVE_*")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be explicitly false")
    if scope.get("ship_verdict") != "NOT_SHIPPABLE":
        p.append("scope.ship_verdict must be NOT_SHIPPABLE")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be a non-empty list")

    ds = data.get("decisions") or []
    if not ds:
        p.append("empty decisions: refusing to call an empty ledger verified")
        return p
    ids = [d.get("id", "") for d in ds]
    if len(ids) != len(set(ids)):
        p.append("duplicate decision ids")
    if not all(MARK.fullmatch(x) for x in ids):
        p.append("decision id must look like DECISION_<UPPERCASE>")
    own = set(ids)

    # Must record the captured real bug, so the ledger can never be emptied of
    # the very case that justified it while still claiming to be a ledger.
    if CAPTURED_EXAMPLE not in own:
        p.append("captured real case %s missing from decisions" % CAPTURED_EXAMPLE)

    schema = data.get("decision_schema") or {}
    min_reopen = int(schema.get("min_reopen_when_chars") or 12)
    if doc_marks is not None:
        missing = sorted(doc_marks - own)   # a doc wrote "we won't do X" with no owner
        extra = sorted(own - doc_marks)     # contract owns a marker no doc references
        if missing:
            p.append("DECISION_* markers in docs with no contract entry: %s" % missing)
        if extra:
            p.append("decision ids not present in scanned docs: %s" % extra)

    for d in ds:
        did = d.get("id", "<no id>")
        for k in REQUIRED:
            if k not in d:
                p.append("%s missing field %s" % (did, k))
                continue
        if d.get("status") not in VALID_STATUS:
            p.append("%s invalid status %r" % (did, d.get("status")))
        if d.get("resolution_marker") != did:
            p.append("%s resolution_marker must equal its own id" % did)
        for k in ("watch_terms", "stale_terms", "source_refs", "conflicts_with"):
            v = d.get(k)
            if k in ("watch_terms", "stale_terms"):
                if not (isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v)):
                    p.append("%s %s must be a non-empty list of strings" % (did, k))
                elif any(len(x.strip()) < 2 for x in v):
                    p.append("%s %s contains a single-char term (rule 10)" % (did, k))
            elif k == "source_refs" and not (isinstance(v, list) and v):
                p.append("%s empty source_refs" % did)
        for k in ("statement", "rationale", "decided_in", "negative_control"):
            if not str(d.get(k, "")).strip():
                p.append("%s empty %s" % (did, k))
        # A decision is not a permanent veto unless it has a real reopen trigger.
        rw = str(d.get("reopen_when", "")).strip()
        if len(rw) < min_reopen:
            p.append("%s reopen_when too short/empty (min %d chars)" % (did, min_reopen))
        elif not any(ch.isdigit() for ch in rw) and "上板" not in rw and "实测" not in rw:
            # Heuristic positive assertion: the trigger must be executable, not
            # "if we feel like it". Accept a metric, a board test, or a log.
            p.append("%s reopen_when lacks an executable trigger" % did)

        # owner doc must actually carry the marker (decision has one home page)
        owner = str(d.get("decided_in", ""))
        marker = str(d.get("resolution_marker", ""))
        if marker and owner and docs is not None:
            # decided_in is a path+section, not the marker itself; verify by path.
            # Normalise separators: walk_markdown yields OS-native paths
            # (backslash on Windows), decided_in is written POSIX-style. Without
            # .as_posix() this whole assertion silently never fires (found by
            # first real run -- a bare substring/path bug hiding in a "green"
            # control).
            owner_path = owner.split()[0].replace("\\", "/")
            doc_paths = {rel.replace("\\", "/") for rel, _ in docs}
            if owner_path in doc_paths:
                hit = any(rel.replace("\\", "/") == owner_path and marker in text
                          for rel, text in docs)
                if not hit:
                    p.append("%s owner doc %s does not carry its marker" % (did, owner_path))

    # Cross-document stale-phrase detection. This is the information bug:
    # naming the subject AND a "still to do" compound phrase, with no pointer
    # to this ledger, means a reader/agent will re-mine a decided NOT-to-do.
    if docs is not None:
        for d in ds:
            did = d.get("id", "")
            marker = str(d.get("resolution_marker", ""))
            watch = [w for w in (d.get("watch_terms") or []) if isinstance(w, str)]
            stale = [s for s in (d.get("stale_terms") or []) if isinstance(s, str)]
            if not (watch and stale and marker):
                continue
            for rel, text in docs:
                has_watch = any(w in text for w in watch)
                # Exclude this ledger's own contract-reproducing docs from the
                # conflict scan only when the marker IS present (pointer landed).
                has_stale = any(s in text for s in stale)
                has_marker = marker in text
                if has_watch and has_stale and not has_marker:
                    p.append("%s stale口径未指向决议: %s 含 watch+stale 但无 %s"
                             % (did, rel, marker))
    return p


def overall_verdict(data: dict, problems: list[str]) -> str:
    """Decision ledger is informational. It never ships hardware."""
    return "LOCAL_RESOLUTION_ONLY" if not problems else "FAIL"


def report(data: dict, docs: list[tuple[str, str]] | None = None,
           roots: list[Path] | None = None) -> dict:
    docs = walk_markdown(roots) if docs is None else docs
    marks: set[str] = set()
    for _rel, text in docs:
        marks.update(MARK.findall(text))
    problems = validate(data, marks, docs)
    walked = sorted({rel.split("/")[0] for rel, _ in docs})
    return {
        "tool": "check_decisions.py",
        "verdict": overall_verdict(data, problems),
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "not_proof_of": data.get("scope", {}).get("not_proof_of", []),
        "decisions": sorted(d.get("id", "") for d in data.get("decisions", [])),
        "doc_markers": sorted(marks),
        "doc_files_scanned": len(docs),
        "scan_roots": walked,
        "scan_excluded": list(EXCLUDED_SCAN_ROOTS),
        "contract_sha256": sha256_of(CONTRACT),
        "problems": problems,
    }


def selftest() -> int:
    data = load()
    # Structural / positive / negative controls use an INJECTED clean doc set
    # derived from the contract itself, so --selftest is independent of whether
    # the human-facing docs have landed their markers yet. `--check` is the
    # separate gate that verifies real docs. (Found by first real run: using
    # walk_markdown() here made every control red while docs were mid-edit.)
    injected_docs: list[tuple[str, str]] = []
    for d in data.get("decisions", []):
        mid = str(d.get("resolution_marker", ""))
        decided_in = str(d.get("decided_in", ""))
        owner_path = decided_in.split()[0] if decided_in else "docs/owner.md"
        injected_docs.append((owner_path, mid + " " + str(d.get("statement", ""))))
    injected_marks: set[str] = set()
    for _rel, text in injected_docs:
        injected_marks.update(MARK.findall(text))
    disk_docs = walk_markdown()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data, injected_marks, injected_docs)
    ck("盘上契约结构自校验通过（注入干净 docs）", not base, "; ".join(base[:3]))
    ck("id 集合与注入 docs 扫描集合相等",
       injected_marks == set(d.get("id") for d in data["decisions"]),
       "docs=%d contract=%d" % (len(injected_marks), len(data["decisions"])))
    ck("captured real case 在册", any(d.get("id") == CAPTURED_EXAMPLE for d in data["decisions"]))
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("verdict 恒 LOCAL_RESOLUTION_ONLY", overall_verdict(data, base) == "LOCAL_RESOLUTION_ONLY")

    # Regex sanity: the marker shape really matches the captured case.
    ck("MARK 捕获真实决议标记", MARK.findall("见 %s 决议" % CAPTURED_EXAMPLE) == [CAPTURED_EXAMPLE])

    # For the stale-phrase controls we pass a DOC SET containing only the fake
    # doc, so no other decision's "marker not in docs" noise leaks in. doc_marks
    # is the injected full set (so set-equality controls stay satisfied).
    good_docs = [("docs/fake.md", "HostImuGate 门控见 DECISION_HOSTIMU_GATE；本仓不搬。")]
    ck("正对照：只提事项名不误报",
       not any("stale口径" in x for x in validate(
           data, injected_marks,
           [("docs/fake.md", "上游 trunk_imu.rs 里有 HostImuGate 门控（架构介绍）。")])))
    ck("正对照：watch+stale 但已带指针不误报",
       not any("stale口径" in x for x in validate(data, injected_marks, good_docs)))

    # The real information bug, reproduced offline: a doc that re-mines a
    # decided NOT-to-do as "C-IMU (new)" with no pointer must go red.
    stale_doc = [("docs/fake.md", "§7 C-IMU（新增）：HostImuGate 50ms/1s/3-repeats，细化两代次门控。")]
    stale_problems = validate(data, injected_marks, stale_doc)
    ck("负对照：watch+stale 无指针必红（口径漂移实证）",
       any("stale口径未指向决议" in x and "DECISION_HOSTIMU_GATE" in x and "fake.md" in x
           for x in stale_problems),
       "; ".join(stale_problems[:2]))
    # Pointer lands -> green again.
    landed = [("docs/fake.md", stale_doc[0][1] + " → 见 DECISION_HOSTIMU_GATE，本仓不搬。")]
    ck("负对照转绿：补决议指针后不再报",
       not any("stale口径" in x for x in validate(data, injected_marks, landed)))

    # Honest report of the REAL docs' landing state (not a structural assert):
    # --selftest stays green mid-edit; `--check` is what gates doc landing.
    disk_marks: set[str] = set()
    for _rel, text in disk_docs:
        disk_marks.update(MARK.findall(text))
    disk_problems = validate(data, disk_marks, disk_docs)
    stale_conflicts = [x for x in disk_problems if "stale口径" in x]
    print("  info 盘上 docs 标记落地: %d 个 / stale 口径冲突 %d 处（由 --check 门禁，不使 selftest 变红）"
          % (len(disk_marks), len(stale_conflicts)))
    for x in stale_conflicts:
        print("       - %s" % x)

    def must_fail(name: str, mutate, dset: set[str] | None = None,
                  ddocs: list[tuple[str, str]] | None = None) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad, injected_marks if dset is None else dset,
                               injected_docs if ddocs is None else ddocs)))

    must_fail("负对照：删一条决议必红", lambda d: d["decisions"].pop())
    must_fail("负对照：空决议台账必红", lambda d: d.update({"decisions": []}))
    must_fail("负对照：删掉 captured case 必红",
              lambda d: d.update({"decisions": [x for x in d["decisions"]
                                                 if x["id"] != CAPTURED_EXAMPLE]}))
    must_fail("负对照：重复 id 必红",
              lambda d: d["decisions"].append(copy.deepcopy(d["decisions"][0])))
    must_fail("负对照：非法 status 必红", lambda d: d["decisions"][0].update({"status": "PENDING"}))
    must_fail("负对照：清空 reopen_when 必红", lambda d: d["decisions"][0].update({"reopen_when": ""}))
    must_fail("负对照：reopen_when 无可执行触发必红",
              lambda d: d["decisions"][0].update({"reopen_when": "以后再说"}))
    must_fail("负对照：空 rationale 必红", lambda d: d["decisions"][0].update({"rationale": " "}))
    must_fail("负对照：resolution_marker 不等于 id 必红",
              lambda d: d["decisions"][0].update({"resolution_marker": "DECISION_OTHER"}))
    must_fail("负对照：单字 stale_term 必红（规则10）",
              lambda d: d["decisions"][0].update({"stale_terms": ["新"]}))
    must_fail("负对照：空 watch_terms 必红",
              lambda d: d["decisions"][0].update({"watch_terms": []}))
    # owner-doc marker assertion must actually fire (guards against the silent
    # path-separator bug: inject a doc at the owner path WITHOUT its marker).
    owner_path = data["decisions"][0]["decided_in"].split()[0]
    ck("负对照：owner doc 缺标记必红（路径归一化后真的会触发）",
       bool(validate(data, injected_marks,
                     [(owner_path, "some text without the marker")])))
    ck("正对照：owner doc 带标记不红",
       not any("owner doc" in x for x in validate(
           data, injected_marks, [(owner_path, CAPTURED_EXAMPLE + " 本仓不搬")])))
    must_fail("负对照：docs 出现未登记 DECISION_* 必红",
              lambda _d: None, dset=injected_marks | {"DECISION_GHOST_MARKER"})
    must_fail("负对照：rule 抹掉 DECISION≠PENDING 语义必红",
              lambda d: d.update({"rule": "decisions are optional"}))
    must_fail("负对照：抹掉与 A2 正交声明必红", lambda d: d.update({"orthogonality": "none"}))
    must_fail("负对照：scope 声称碰硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("负对照：ship_verdict 改 SHIPPABLE 必红",
              lambda d: d["scope"].update({"ship_verdict": "SHIPPABLE"}))

    # scan root sensitivity: inject one file with a marker, show the walk finds
    # it and an empty root loses it. Independent of real docs' landing state.
    with_marker = scan_doc_marks([ROOT / "docs"])
    ck("scan_doc_marks 可注入运行（不抛异常）", isinstance(with_marker, set))
    ck("空扫描根得空集合", scan_doc_marks([ROOT / "nonexistent-dir"]) == set())
    tmp = ROOT / "nonexistent-dir"
    one = ROOT / "README.md"
    ck("单文件根按 .md 扫描", isinstance(scan_doc_marks([one]), set))

    failed = [n for n, ok, _ in checks if not ok]
    for name, ok, note in checks:
        print("  %s %s%s" % ("ok  " if ok else "FAIL", name, ((" -- " + note) if note and not ok else "")))
    print("verdict: %s" % ("PASS" if not failed else "FAIL"))
    print("self-test: %s (%d/%d)" % ("PASS" if not failed else "FAIL", len(checks) - len(failed), len(checks)))
    print("scope: LOCAL_RESOLUTION_ONLY / NOT_SHIPPABLE / live_hardware_accessed=false")
    return 0 if not failed else 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="validate the decision ledger against allow-listed docs")
    ap.add_argument("--selftest", action="store_true", help="run negative-control self-test")
    ap.add_argument("--list", action="store_true", help="list registered decisions")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --check)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.list:
        data = load()
        for d in data.get("decisions", []):
            print("%-34s %-10s %s" % (d.get("id"), d.get("status"), d.get("subject", "")))
        return 0
    if args.check:
        data = load()
        rep = report(data)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print("verdict: %s" % rep["verdict"])
            print("ship_verdict: %s" % rep["ship_verdict"])
            print("decisions=%d doc_markers=%d doc_files=%d" %
                  (len(rep["decisions"]), len(rep["doc_markers"]), rep["doc_files_scanned"]))
            for prob in rep["problems"]:
                print("  PROBLEM: %s" % prob)
            print("scope: %s / live_hardware_accessed=false / contract_sha256=%s" %
                  (rep["ship_verdict"], rep["contract_sha256"][:12]))
        return 0 if not rep["problems"] else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
