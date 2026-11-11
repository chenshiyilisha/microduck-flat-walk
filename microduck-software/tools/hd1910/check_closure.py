#!/usr/bin/env python3
"""Closure contract: every open INCONCLUSIVE_* has an executable way to close.

Why this exists (2026-11-11, four-source comparison)
---------------------------------------------------
The project had five open markers and one closed one, but no definition of
"what evidence closes it, who signs, what must turn red, and what it blocks".
Four first-party sources agree that offline results are not hardware
acceptance:

  - official docs/policy-manifest.md: "Absent fields are not evidence;
    a robot refuses a policy only on a claim that is present and wrong".
    Its eval field records "what was checked, in what sim, how it did".
  - kissqy README: "本次源码公开不扩大原有模型的实机验收范围".
  - fanhao verification/*.md: "Verified locally" vs "Board acceptance
    still required", "do not claim success until ... read back".
  - luwu commit records: test counts are recorded, and local validation
    tools are excluded from the source release.

So UNVERIFIED is never a PASS. A structurally valid contract that still has
UNVERIFIED entries is NOT_SHIPPABLE; --ship-gate turns that into rc=1.

Field design borrows fanhao 的 HD-1910训练前数据清单 (每个数标出处 + 待实测)、
open-microduck 的 evidence-backlog / source-ledger (证据性质、尚不能排除的解释、
本轮没有取得的证据), and open-microduck check_book.py (id 集合相等断言 +
输出 sha256 + 末尾 Scope 声明).

Single source of truth: closure_contract.json. Stdlib only.

Scan coverage (C1, 2026-11-11)
------------------------------
The first version scanned ONLY ROOT/docs/**/*.md. A marker introduced by a
user decision could therefore live in a delivery note under out/deliverables/
(or in a tool docstring / root README) without ever being registered here --
the "a marker in a document with no contract entry turns the gate red"
promise was bypassable. scan_doc_marks() now walks an EXPLICIT allow-list of
roots and the report names the roots it actually walked, so the coverage is
auditable. Deliberately excluded: .workbuddy/memory/** (historical work log,
not a live contract), .upstream/** (third-party markers), and out/** other
than deliverables (scratch / evidence snapshots). Those are史料, not 规范文档.
An explicit allow-list -- not a whole-repo rglob -- is required: a blanket
scan would drag dozens of historical markers into the "must register" set.

Usage (cwd = microduck-software):
    python tools/hd1910/check_closure.py --check
    python tools/hd1910/check_closure.py --check --ship-gate
    python tools/hd1910/check_closure.py --selftest
    python tools/hd1910/check_closure.py --check --json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "closure_contract.json"
MARK = re.compile(r"INCONCLUSIVE_[A-Z_]+")
# Explicit allow-list. Relative to ROOT. A file entry is scanned as one .md.
SCAN_ROOTS = (
    "docs",
    "out/deliverables",
    "microduck-software/tools/hd1910",
    "README.md",
    "AGENTS.md",
)
EXCLUDED_SCAN_ROOTS = (
    ".workbuddy/memory",
    ".upstream",
    "out (outside out/deliverables)",
)
EXCLUDED_REASON = ("史料与第三方文档不是活的契约；全仓 rglob 会把历史标记拉进『必须登记』集合，"
                   "造成大量假红。只扫显式白名单，缺失的根自动跳过并在报告里如实列出。")

REQUIRED = ("id", "status", "summary", "why_open", "evidence_kind",
            "verification_boundary", "local_verified",
            "board_acceptance_required", "still_owed", "negative_control",
            "blocked_actions", "source_refs", "signoff", "evidence")
VALID_STATUS = {"UNVERIFIED", "PASS", "CLOSED", "FAIL"}


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_scan_roots(root: Path = ROOT) -> list[Path]:
    """Allow-listed roots that actually exist (CI has no gitignored out/)."""
    return [root / rel for rel in SCAN_ROOTS if (root / rel).exists()]


def scan_doc_marks(roots: list[Path] | None = None) -> set[str]:
    """Every marker in the allow-listed documents must be registered.

    This is the check_book.py "expected == {actual}" assertion: a new
    INCONCLUSIVE_* in ANY scanned document with no contract entry turns the
    gate red instead of silently becoming an untracked open question.
    `roots` is injectable so the negative control can PROVE that an extra
    root is really walked (and that dropping it really loses the marker).
    """
    out: set[str] = set()
    for r in (default_scan_roots() if roots is None else roots):
        files = [r] if r.is_file() else sorted(r.rglob("*.md"))
        for f in files:
            if f.suffix.lower() != ".md":
                continue
            out.update(MARK.findall(io.open(f, encoding="utf-8", errors="replace").read()))
    return out


def validate(data: dict, doc_marks: set[str] | None = None) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    cs = data.get("contracts") or []
    if not cs:
        p.append("empty contracts: refusing to call an empty contract verified")
        return p
    if "UNVERIFIED" not in (data.get("rule") or "") or "PASS" not in (data.get("rule") or ""):
        p.append("rule must state that UNVERIFIED is not PASS")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be explicitly false")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be a non-empty list")

    ids = [c.get("id", "") for c in cs]
    if len(ids) != len(set(ids)):
        p.append("duplicate contract ids")
    if not all(MARK.fullmatch(x) for x in ids):
        p.append("contract id must look like INCONCLUSIVE_<UPPERCASE>")
    own = set(ids)
    if doc_marks is not None:
        missing = sorted(doc_marks - own)
        extra = sorted(own - doc_marks)
        if missing:
            p.append("markers in docs with no contract entry: %s" % missing)
        if extra:
            p.append("contract entries not present in docs: %s" % extra)

    for c in cs:
        cid = c.get("id", "<no id>")
        for k in REQUIRED:
            if k not in c:
                p.append("%s missing field %s" % (cid, k))
        st = c.get("status")
        if st not in VALID_STATUS:
            p.append("%s invalid status %r" % (cid, st))
        for k in ("evidence_kind", "local_verified", "board_acceptance_required",
                  "blocked_actions", "source_refs"):
            if k in c and isinstance(c[k], list) and not c[k]:
                p.append("%s empty %s" % (cid, k))
        if "negative_control" in c and not str(c["negative_control"]).strip():
            p.append("%s empty negative_control" % cid)
        if st == "UNVERIFIED":
            if c.get("evidence"):
                p.append("%s is UNVERIFIED but carries closing evidence" % cid)
            if not (c.get("still_owed") or []):
                p.append("%s UNVERIFIED must list what is still owed" % cid)
        if st in ("PASS", "CLOSED") and not (c.get("evidence") or []):
            p.append("%s is %s without evidence" % (cid, st))
    return p


def overall_verdict(data: dict) -> str:
    """UNVERIFIED / FAIL never pass. Only all PASS/CLOSED is shippable."""
    statuses = [c.get("status") for c in (data.get("contracts") or [])]
    if not statuses or any(s in ("UNVERIFIED", "FAIL") for s in statuses):
        return "NOT_SHIPPABLE"
    if all(s in ("PASS", "CLOSED") for s in statuses):
        return "SHIPPABLE"
    return "NOT_SHIPPABLE"


def selftest() -> int:
    data = load()
    marks = scan_doc_marks()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data, marks)
    ck("盘上契约结构自校验通过", not base, "; ".join(base[:3]))
    ck("id 集合与 docs 扫描集合相等", set(c["id"] for c in data["contracts"]) == marks,
       "docs=%d contract=%d" % (len(marks), len(data["contracts"])))
    ck("当前整体判 NOT_SHIPPABLE", overall_verdict(data) == "NOT_SHIPPABLE")
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)

    # UNVERIFIED != PASS, with the complementary positive control
    good = copy.deepcopy(data)
    for c in good["contracts"]:
        if c["status"] == "UNVERIFIED":
            c["status"] = "CLOSED"
            c["evidence"] = ["selftest synthetic evidence"]
            c["still_owed"] = ["synthetic"]
    ck("正对照：全部闭合且有证据则 SHIPPABLE", overall_verdict(good) == "SHIPPABLE")
    back = copy.deepcopy(good)
    back["contracts"][0]["status"] = "UNVERIFIED"
    back["contracts"][0]["evidence"] = []
    ck("负对照：塞回一个 UNVERIFIED 立刻 NOT_SHIPPABLE",
       overall_verdict(back) == "NOT_SHIPPABLE")

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad, marks)))

    must_fail("负对照：删一个契约 id 必红", lambda d: d["contracts"].pop())
    must_fail("负对照：重复 id 必红",
              lambda d: d["contracts"].append(copy.deepcopy(d["contracts"][0])))
    must_fail("负对照：未知 id 必红",
              lambda d: d["contracts"][0].update({"id": "INCONCLUSIVE_NOT_REGISTERED"}))
    must_fail("负对照：UNVERIFIED 塞证据冒充闭合必红",
              lambda d: d["contracts"][0].update({"evidence": ["bogus"]}))
    must_fail("负对照：CLOSED 清空证据必红",
              lambda d: [c.update({"evidence": []}) for c in d["contracts"] if c["status"] == "CLOSED"])
    must_fail("负对照：删 negative_control 必红",
              lambda d: d["contracts"][0].update({"negative_control": ""}))
    must_fail("负对照：删 board_acceptance_required 必红",
              lambda d: d["contracts"][0].update({"board_acceptance_required": []}))
    must_fail("负对照：空契约必红", lambda d: d.update({"contracts": []}))
    must_fail("负对照：rule 抹掉 UNVERIFIED 语义必红",
              lambda d: d.update({"rule": "everything passes"}))
    must_fail("负对照：scope 声称碰过硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    ck("负对照：docs 出现未登记标记必红",
       bool(validate(data, marks | {"INCONCLUSIVE_GHOST_MARKER"})))

    # --- C1: prove the widened scan really walks extra roots -----------------
    roots = default_scan_roots()
    ck("扫描根是显式白名单且 docs 在内",
       any(r.name == "docs" for r in roots)
       and all(not any(x in r.as_posix() for x in (".workbuddy/memory", ".upstream"))
               for r in roots),
       "roots=%d" % len(roots))
    ck("扫描根排除史料日志与第三方上游",
       not any(any(x in r.as_posix() for x in (".workbuddy/memory", ".upstream"))
               for r in roots))
    with tempfile.TemporaryDirectory(prefix="md_closure_scan_") as td:
        tmp = Path(td)
        with_marker = tmp / "deliverable"
        clean = tmp / "clean"
        with_marker.mkdir()
        clean.mkdir()
        (with_marker / "note.md").write_text(
            "new decision: INCONCLUSIVE_GHOST_MARKER is open\n", encoding="utf-8")
        (clean / "note.md").write_text("nothing open here\n", encoding="utf-8")
        ck("扩扫描：交付说明里的新标记被检到",
           "INCONCLUSIVE_GHOST_MARKER" in scan_doc_marks([with_marker]))
        ck("负对照：同一扫描器对无标记根不报",
           "INCONCLUSIVE_GHOST_MARKER" not in scan_doc_marks([clean]))
        widened = scan_doc_marks(roots + [with_marker])
        ck("负对照：新根里的未登记标记让门禁变红",
           bool(validate(data, widened)) and "INCONCLUSIVE_GHOST_MARKER" in widened)
        ck("负对照：去掉新根后门禁恢复绿",
           not validate(data, scan_doc_marks(roots)))
    ck("报告如实列出实际扫描根与排除理由",
       set(report(data, [], marks, roots)["scan_roots"])
       == {r.relative_to(ROOT).as_posix() for r in roots}
       and bool(report(data, [], marks, roots)["scan_excluded"]))

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\ncheck_closure selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: contract structure only; no hardware, no live identify, no R3 closure.")
    return 0


def report(data: dict, problems: list[str], marks: set[str],
           roots: list[Path] | None = None) -> dict:
    counts: dict[str, int] = {}
    for c in data.get("contracts") or []:
        counts[c.get("status", "?")] = counts.get(c.get("status", "?"), 0) + 1
    walked = default_scan_roots() if roots is None else roots
    walked_names = []
    for r in walked:
        try:
            walked_names.append(r.relative_to(ROOT).as_posix())
        except ValueError:
            walked_names.append(str(r))
    return {
        "tool": "check_closure.py",
        "contract_sha256": sha256_of(CONTRACT),
        "scan_roots": sorted(walked_names),
        "scan_excluded": list(EXCLUDED_SCAN_ROOTS),
        "scan_excluded_reason": EXCLUDED_REASON,
        "doc_markers": sorted(marks),
        "contract_ids": [c["id"] for c in data["contracts"]],
        "status_counts": counts,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": overall_verdict(data),
        "live_hardware_accessed": False,
        "not_proof_of": data["scope"]["not_proof_of"],
        "known_gaps": data["scope"]["known_gaps"],
        "scope": "未闭环标记的结构与证据要求校验；UNVERIFIED 不算 PASS，不替代上板验收",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk contract")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 when anything is still UNVERIFIED")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    data = load()
    roots = default_scan_roots()
    marks = scan_doc_marks(roots)
    problems = validate(data, marks)
    rep = report(data, problems, marks, roots)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("closure_contract.json sha256 = " + rep["contract_sha256"])
        print("scan roots = %s" % ", ".join(rep["scan_roots"]))
        print("doc markers = %d  contract ids = %d" % (len(marks), len(rep["contract_ids"])))
        print("status counts = " + json.dumps(rep["status_counts"], ensure_ascii=False))
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship_verdict = " + rep["ship_verdict"] + "  (UNVERIFIED != PASS)")
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate and rep["ship_verdict"] != "SHIPPABLE":
        if not args.json:
            print("SHIP GATE REFUSED: %d contract(s) not closed" % rep["status_counts"].get("UNVERIFIED", 0))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
