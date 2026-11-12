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
    python tools/hd1910/check_closure.py --explain [--json]

--explain (read-only diagnostic, NEVER a gate)
----------------------------------------------
scan_doc_marks() walks the FILESYSTEM over the allow-listed roots, so an
untracked draft .md bearing a new marker turns the LOCAL structure check red
while a clean CI checkout (tracked files only) stays green. That asymmetry is
by design: tracked-only scanning would hide a marker the moment it is staged.
--explain makes the asymmetry legible WITHOUT changing --check's verdict or
rc: it reports which markers are visible in the committed view (git index),
which are local-only, and attributes each to its file(s). It never turns a red
structure green. If git is unavailable it reports INCONCLUSIVE, not green.
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

    # --- D2: local-vs-committed diagnosis (fully injected; disk-independent) --
    # These run green on BOTH a dirty local workspace and a clean CI checkout.
    ids = [c["id"] for c in data["contracts"]]
    base = {m: [{"file": "docs/tracked_note.md", "tracked": True}] for m in ids}
    ghost = "INCONCLUSIVE_GHOST_MARKER"
    any_set = {"docs/tracked_note.md"}

    aligned = grade_env(data, base, any_set, [])
    ck("正对照：本机与提交态一致判 ALIGNED 且双绿",
       aligned["classification"] == "ALIGNED"
       and aligned["local_structure_verdict"] == "PASS"
       and aligned["committed_structure_verdict"] == "PASS")

    draft = dict(base)
    draft[ghost] = [{"file": "docs/active/untracked_draft.md", "tracked": False}]
    d_rep = grade_env(data, draft, any_set, validate(data, set(draft)))
    ck("本机假红：草稿未登记标记 → LOCAL_ONLY_DRAFT_RED / 本机红·提交态绿",
       d_rep["classification"] == "LOCAL_ONLY_DRAFT_RED"
       and d_rep["local_structure_verdict"] == "FAIL"
       and d_rep["committed_structure_verdict"] == "PASS")
    ck("负对照：本机假红不得改 ship_verdict（仍 NOT_SHIPPABLE）",
       d_rep["ship_verdict"] == "NOT_SHIPPABLE")

    committed_bad = dict(base)
    committed_bad[ghost] = [{"file": "docs/active/committed.md", "tracked": True}]
    cb_rep = grade_env(data, committed_bad, any_set, validate(data, set(committed_bad)))
    ck("负对照：未登记标记进 tracked → REAL_CI_RED / 提交态红",
       cb_rep["classification"] == "REAL_CI_RED"
       and cb_rep["committed_structure_verdict"] == "FAIL"
       and ghost in (cb_rep["ci_unregistered_markers"] or []))

    mixed = dict(base)
    mixed[ghost] = [{"file": "docs/active/unknown.md", "tracked": None}]
    m_rep = grade_env(data, mixed, any_set, validate(data, set(mixed)))
    ck("负对照：来源 tracked 状态未知 → MIXED 不判 benign",
       m_rep["classification"] == "MIXED_UNATTRIBUTED")

    nogit = grade_env(data, draft, None, validate(data, set(draft)))
    ck("负对照：git 不可用 → INCONCLUSIVE_NO_GIT（提交态 UNKNOWN，不宣称绿）",
       nogit["classification"] == "INCONCLUSIVE_NO_GIT"
       and nogit["committed_structure_verdict"] == "UNKNOWN")

    frozen = copy.deepcopy(draft)
    grade_env(data, draft, any_set, [])
    ck("只读性：grade_env 不改动注入的 by_source 与契约",
       draft == frozen and data["contracts"] == load()["contracts"])

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


def doc_marks_by_source(roots: list[Path] | None = None,
                        tracked: set[str] | None = None) -> dict:
    """Attribute every scanned marker to its files and to the committed view.

    `tracked` is the set of repo-relative paths known to git (the index). When
    None (or when git is unavailable) the committed view is UNKNOWN -- we do
    not guess that local == committed. Two views are produced:

      * filesystem view  == what --check actually scans (all .md on disk)
      * committed view   == markers in .md files that are tracked by git

    A marker present on disk but absent from the committed view is a
    LOCAL_ONLY candidate; it only becomes a benign "untracked draft" when
    every file carrying it is untracked. If ANY tracked file carries a marker
    that has no contract entry, that is a REAL regression (CI will be red).
    """
    roots = default_scan_roots() if roots is None else roots
    by_mark: dict[str, list[dict]] = {}
    for r in roots:
        files = [r] if r.is_file() else sorted(r.rglob("*.md"))
        for f in files:
            if f.suffix.lower() != ".md":
                continue
            try:
                rel = f.relative_to(ROOT).as_posix()
            except ValueError:
                rel = str(f)
            marks = MARK.findall(io.open(f, encoding="utf-8", errors="replace").read())
            is_tracked = None if tracked is None else (rel in tracked)
            for m in set(marks):
                by_mark.setdefault(m, []).append({"file": rel, "tracked": is_tracked})
    return by_mark


def git_tracked_paths(root: Path = ROOT) -> set[str] | None:
    """Repo-relative tracked paths from the git index, or None if unavailable.

    Uses `git -C <real toplevel> ls-files -z`. The ROOT here may be a junction
    path (E:/WorkBuddy/...) that differs from the real worktree reported by
    `rev-parse --show-toplevel` (E:/WorkBuddyData/...); resolving the toplevel
    first is REQUIRED or ls-files silently returns an empty set.
    """
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=15)
        if top.returncode != 0 or not top.stdout.strip():
            return None
        real = Path(top.stdout.strip())
        ls = subprocess.run(["git", "-C", str(real), "ls-files", "-z"],
                            capture_output=True, timeout=15)
        if ls.returncode != 0:
            return None
        return set(p for p in ls.stdout.decode("utf-8", "replace").split("\0") if p)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def grade_env(data: dict, by_source: dict,
              tracked: set[str] | None, problems: list[str]) -> dict:
    """Pure classifier: separate a benign local-only draft red from a real CI red.

    Injectable by_source / tracked / problems so negative controls never touch
    the real workspace. Owns no verdict: --check still decides rc; this only
    explains WHY local and committed views differ.
    """
    ids = set(c["id"] for c in data.get("contracts") or [])
    fs_marks = set(by_source)
    if tracked is None:
        ci_marks = None  # committed view genuinely unknown
    else:
        ci_marks = {m for m, srcs in by_source.items()
                    if any(s["tracked"] for s in srcs)}

    local_only = sorted(fs_marks - ci_marks) if ci_marks is not None else None
    ci_unregistered = (sorted(ci_marks - ids) if ci_marks is not None else None)
    # A local-only marker is a benign draft iff EVERY file carrying it is
    # untracked. If a tracked file carries an unregistered marker, CI is red.
    draft_ok: dict[str, bool] = {}
    for m in local_only or []:
        srcs = by_source[m]
        draft_ok[m] = all(s["tracked"] is False for s in srcs) and bool(srcs)

    if tracked is None:
        classification = "INCONCLUSIVE_NO_GIT"
    elif ci_unregistered:
        classification = "REAL_CI_RED"
    elif local_only and all(draft_ok.values()):
        classification = "LOCAL_ONLY_DRAFT_RED"
    elif local_only:
        classification = "MIXED_UNATTRIBUTED"
    else:
        classification = "ALIGNED"

    return {
        "tool": "check_closure.py",
        "mode": "explain",
        "classification": classification,
        "classification_meaning": {
            "ALIGNED": "本机与提交态一致：没有未登记标记。",
            "LOCAL_ONLY_DRAFT_RED": ("本机红仅因未入库草稿文档带未登记标记；"
                                      "提交态(tracked)集合与契约 id 相等，CI 干净树结构绿。"
                                      "这是已知假红，不是交付缺陷；仍 NOT_SHIPPABLE。"),
            "REAL_CI_RED": ("有已 tracked 文档带未登记标记 ⇒ 提交态结构也红，"
                             "必须登记契约或移除标记，不能当本机假红放过。"),
            "MIXED_UNATTRIBUTED": ("本机多出的标记里有的同时出现在 tracked 文件，"
                                    "归因不明；按最坏处理，不当假红。"),
            "INCONCLUSIVE_NO_GIT": ("取不到 git 提交态，无法判定本机红是否会在 CI 复现；"
                                     "INCONCLUSIVE，不宣称绿。"),
        }[classification],
        "local_filesystem_markers": sorted(fs_marks),
        # sorted list, NOT the raw set: --json serializes this report directly.
        "committed_view_markers": sorted(ci_marks) if ci_marks is not None else None,
        "contract_ids": sorted(ids),
        "local_structure_problems": problems,
        "ci_unregistered_markers": ci_unregistered,
        "local_only_markers": local_only,
        "local_only_draft_ok": draft_ok,
        "by_source": by_source,
        "local_structure_verdict": "PASS" if not problems else "FAIL",
        "committed_structure_verdict": (
            "UNKNOWN" if ci_marks is None
            else ("PASS" if not (ci_unregistered or (ids - ci_marks)) else "FAIL")
        ),
        "ship_verdict": overall_verdict(data),
        "live_hardware_accessed": False,
        "not_a_gate": ("--explain 只读、不改 --check 的判定与 rc；"
                        "UNVERIFIED != PASS；工具/SOP 就绪 != 悬案闭合。"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk contract")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 when anything is still UNVERIFIED")
    ap.add_argument("--explain", action="store_true",
                    help="READ-ONLY: diagnose local-vs-committed marker divergence (never a gate)")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    data = load()

    if args.explain:
        tracked = git_tracked_paths(ROOT)
        by_source = doc_marks_by_source(tracked=tracked)
        local_problems = validate(data, set(by_source))
        rep = grade_env(data, by_source, tracked, local_problems)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print("mode = explain (READ-ONLY, not a gate; --check keeps its own rc)")
            print("classification = " + rep["classification"])
            print("  -> " + rep["classification_meaning"])
            print("local filesystem markers = %d  contract ids = %d"
                  % (len(rep["local_filesystem_markers"]), len(rep["contract_ids"])))
            print("committed-view markers   = %s"
                  % ("UNKNOWN (git unavailable)" if rep["committed_view_markers"] is None
                     else len(rep["committed_view_markers"])))
            print("local structure verdict  = " + rep["local_structure_verdict"])
            print("committed structure      = " + rep["committed_structure_verdict"])
            for m in (rep["local_only_markers"] or []):
                srcs = ", ".join("%s[%s]" % (s["file"], "tracked" if s["tracked"] else "untracked")
                                 for s in rep["by_source"][m])
                print("  [LOCAL-ONLY] %s  <- %s" % (m, srcs))
            for m in (rep["ci_unregistered_markers"] or []):
                print("  [CI-RED] %s" % m)
            print("ship_verdict = " + rep["ship_verdict"] + "  (UNVERIFIED != PASS)")
            print("live_hardware_accessed = false")
            print("note: " + rep["not_a_gate"])
        return 0  # a diagnostic is never a gate; --check alone decides rc

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
