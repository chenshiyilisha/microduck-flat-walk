#!/usr/bin/env python3
"""E2: machine-readable baseline for the UNTRACKED procurement working copies.

Why this exists (2026-11-11, user-approved)
-------------------------------------------
The procurement domain (two hand-edited xlsx, two build.py generators, a p25
snapshot, the price SSOT) is deliberately UNTRACKED by git. "采购域零改动" was
therefore only a human `stat` + staging-area assertion with no machine evidence
(recorded in 多视角自查 §4). The user approved closing that gap ("可以做，按照最优
的来"), with one hard boundary: NEVER rewrite the hand-edited xlsx (rule 8 --
re-running build.py already once wrote the user's 3 hand-deleted rows back).

What it does NOT pretend to do
------------------------------
A baseline captured now proves "unchanged RELATIVE TO THIS INSTANT" only. It
cannot prove "never changed in the past" (same shape as bundle provenance). The
verdict set is deliberately four-valued, never a boolean:
  - BASELINE_MATCH     : hash+size match AND all semantic anchors hold
  - DRIFT_UNCONFIRMED  : bytes changed but anchors hold (likely a legal hand
                         edit) -> NOT green; needs a human + explicit rebaseline
  - COVERAGE_SUSPECT   : a semantic anchor BROKE (material-row count, revived
                         hand-deleted row, edited 订正㉕ SKU) -> RED
  - UNVERIFIED         : a registered file is MISSING (CI clean checkout) -> not
                         PASS and not drift; report honestly

Why not just sha256
-------------------
A pure hash cannot tell "user ticked a ☑" from "build.py overwrote 19 rows back
to 16". So there is a SECOND, semantic layer extracted from the xlsx with the
stdlib only (they use inlineStr, no sharedStrings.xml): row counts, presence of
key SKUs, absence of hand-deleted items, sheet names. Byte drift + intact
anchors = DRIFT_UNCONFIRMED; broken anchor = COVERAGE_SUSPECT. This is the
"量动没动 / 读数 vs 算术" discipline applied to spreadsheets.

Design borrowed, not reinvented
-------------------------------
  - A2 check_closure.py / D1 check_decisions.py: contract-JSON owner, set
    equality, negative controls that really mutate state, verdict line that is
    never a bare substring of a test name (rule 10).
  - B3 ci_meta_targets.py: stdlib-only so --selftest can run in lean CI; the
    REAL file check (--check) cannot run there because the working copies are
    not committed, and must honestly report UNVERIFIED instead of PASS.
  - project rule 8: this tool writes ONLY procurement_baseline.json on an
    explicit --rebaseline; it never touches a single xlsx / build.py / SSOT.

Usage (cwd = microduck-software):
    python tools/hd1910/check_procurement_baseline.py --check
    python tools/hd1910/check_procurement_baseline.py --check --json
    python tools/hd1910/check_procurement_baseline.py --list
    python tools/hd1910/check_procurement_baseline.py --selftest
    # explicit, audited re-baseline after a REVIEWED legal hand edit:
    python tools/hd1910/check_procurement_baseline.py --rebaseline --confirm \
        --reason "用户2026-11-12 勾选阶段0☑，逐行核对未动口径"
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
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "procurement_baseline.json"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
VERIFIED = "BASELINE_MATCH"
UNCONFIRMED = "DRIFT_UNCONFIRMED"
SUSPECT = "COVERAGE_SUSPECT"
UNVERIFIED = "UNVERIFIED"


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(data: dict) -> list[str]:
    """Contract self-check (independent of the real files' state)."""
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be false")
    if scope.get("ship_verdict") != "NOT_SHIPPABLE":
        p.append("scope.ship_verdict must be NOT_SHIPPABLE")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be non-empty (no retrospective claim)")
    base = data.get("baseline") or {}
    if not base.get("recorded_at"):
        p.append("baseline.recorded_at missing (relative-instant claim needs a time)")
    if "rebaseline" not in str(base.get("rebaseline_policy", "")).lower() \
            and "--rebaseline" not in str(base.get("rebaseline_policy", "")):
        p.append("baseline.rebaseline_policy must require explicit --rebaseline")
    sem = data.get("scope_semantics") or {}
    for state in (VERIFIED, UNCONFIRMED, SUSPECT, UNVERIFIED):
        if state not in sem:
            p.append("scope_semantics missing state %s" % state)
    files = data.get("files") or []
    if not files:
        p.append("empty files list: refusing an empty baseline")
        return p
    ids = [f.get("id") for f in files]
    if len(ids) != len(set(ids)):
        p.append("duplicate file ids")
    for f in files:
        fid = f.get("id", "<no id>")
        h = str(f.get("sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", h):
            p.append("%s sha256 must be 64 lowercase hex" % fid)
        if not isinstance(f.get("size_bytes"), int) or f["size_bytes"] < 0:
            p.append("%s size_bytes must be a non-negative int" % fid)
        if not str(f.get("path", "")).strip():
            p.append("%s empty path" % fid)
        if ".." in Path(str(f.get("path", ""))).parts:
            p.append("%s path escapes root" % fid)
        if not str(f.get("why_protected", "")).strip():
            p.append("%s empty why_protected (every file needs a reason)" % fid)
    anchors = data.get("semantic_anchors") or []
    if not anchors:
        p.append("empty semantic_anchors: a hash-only baseline cannot catch build.py overwrite")
    seen = set()
    for a in anchors:
        aid = a.get("id", "<no id>")
        if aid in seen:
            p.append("duplicate anchor id %s" % aid)
        seen.add(aid)
        if a.get("file") not in ids:
            p.append("%s references unknown file %r" % (aid, a.get("file")))
        if a.get("kind") not in ("material_row_count", "absent_in_material_rows",
                                 "absent_as_material_subject",
                                 "contains_any_in_material_rows", "contains_all_in_sheet",
                                 "sheet_names", "contains_all_in_text"):
            p.append("%s unknown anchor kind %r" % (aid, a.get("kind")))
        if not str(a.get("why", "")).strip():
            p.append("%s empty why" % aid)
    # cross-file invariants must reference real file ids
    for x in data.get("cross_file_invariants") or []:
        for side in ("left", "right"):
            if x.get(side) not in ids:
                p.append("invariant %s bad %s ref" % (x.get("id"), side))
    return p


# ---------------------------------------------------------------------------
# stdlib-only xlsx reader (no openpyxl: lean CI has no such dependency)
# ---------------------------------------------------------------------------

def _col_letters(ref: str) -> str:
    return re.match(r"([A-Z]+)", ref or "").group(1) if re.match(r"([A-Z]+)", ref or "") else ""


def _cell_text(c: ET.Element) -> str:
    """inlineStr text, falling back to v (numbers) and formula cached values."""
    parts = [t.text or "" for t in c.findall(".//m:t", NS)]
    if parts:
        return "".join(parts)
    v = c.find("m:v", NS)
    return (v.text or "") if v is not None else ""


def read_xlsx(path: Path) -> dict:
    """Return {sheet_name: [row_values...]} using only zipfile + ElementTree."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.get("Id"): r.get("Target") for r in rels}
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", NS)))
        sheets: dict[str, list[list[str]]] = {}
        for sh in workbook.findall(".//m:sheets/m:sheet", NS):
            name = sh.get("name", "")
            target = relmap.get(sh.get(RID, ""), "")
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                sheets[name] = []
                continue
            root = ET.fromstring(z.read(target))
            rows: list[list[str]] = []
            for r in root.findall(".//m:sheetData/m:row", NS):
                cells = {_col_letters(c.get("r", "")): (
                    "".join(shared[int(v.text)] for v in c.findall("m:v", NS)
                            if c.get("t") == "s" and v.text and v.text.isdigit())
                    if c.get("t") == "s" else _cell_text(c)) for c in r.findall("m:c", NS)}
                if cells:
                    # width = max COLUMN INDEX (not len of the letter string,
                    # which is 1 for A-E and silently truncates every row to A).
                    width = max((_col_index(k) for k in cells if k), default=0)
                    rows.append([cells.get(_n, "") for _n in _col_names(width)])
                else:
                    rows.append([])
            sheets[name] = rows
        return sheets


def _col_names(n: int) -> list[str]:
    out = []
    for i in range(1, n + 1):
        s = ""
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        out.append(s)
    return out


def _col_index(letters: str) -> int:
    """'A'->1, 'D'->4, 'AA'->27. Inverse of _col_names."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def sheet_text(sheets: dict, name: str) -> str:
    return "\n".join(" | ".join(row) for row in sheets.get(name, []))


def material_rows(sheets: dict, name: str, rng: list[int]) -> list[list[str]]:
    rows = sheets.get(name, [])
    return [rows[i - 1] for i in range(rng[0], rng[1] + 1) if i - 1 < len(rows)]


def evaluate_anchor(a: dict, files_by_id: dict, sheets_by_id: dict) -> str:
    """Return 'ok' or a concrete problem string. Never a bare-boolean."""
    kind = a["kind"]
    fid = a["file"]
    if kind == "contains_all_in_text":
        text = files_by_id.get(fid, "")
        missing = [t for t in a["terms"] if t not in text]
        return "ok" if not missing else "missing terms %s" % missing
    if kind == "sheet_names":
        got = sorted(sheets_by_id.get(fid, {}).keys())
        exp = sorted(a["expected"])
        return "ok" if got == exp else "sheet names %s != %s" % (got, exp)
    sheets = sheets_by_id.get(fid, {})
    if kind == "contains_all_in_sheet":
        text = sheet_text(sheets, a["sheet"])
        missing = [t for t in a["terms"] if t not in text]
        return "ok" if not missing else "missing in %s: %s" % (a["sheet"], missing)
    rows = material_rows(sheets, a.get("sheet", ""), a.get("range", [1, 10**6]))
    if kind == "material_row_count":
        # count rows in range whose first meaningful cell (物料/SKU col D) is non-empty
        nonempty = sum(1 for r in rows if any(c.strip() for c in r))
        return "ok" if nonempty == a["expected"] else \
            "material rows %d != expected %d" % (nonempty, a["expected"])
    if kind == "absent_in_material_rows":
        revivals = []
        excl = a.get("exclude_terms", [])
        for r in rows:
            line = " | ".join(r)
            for t in a["terms"]:
                if t in line and not any(e in line for e in excl):
                    revivals.append(t)
        return "ok" if not revivals else "hand-deleted item revived in material rows: %s" % revivals
    if kind == "absent_as_material_subject":
        # Judge ONLY the material/SKU subject cell (default D = index 3), and
        # only the row's PRIMARY subject (the part before a full-width '（' or
        # ASCII '('). A hand-deleted item "revived" means it became its OWN
        # purchasable line -- not that it appears as a sub-part of a legal line.
        # This is the rule-10 fix: bare '转接线' in the whole line matched the
        # legal '扬声器… + 配套转接线'; here that row's subject is '扬声器…',
        # so it is correctly NOT a revival. No exclude-word whack-a-mole.
        subj_idx = int(a.get("subject_col_index", 3))
        revivals = []
        for r in rows:
            subject = r[subj_idx] if subj_idx < len(r) else ""
            head = re.split(r"[（(]", subject, maxsplit=1)[0].strip()
            for t in a["terms"]:
                if head.startswith(t):
                    revivals.append("%s(行=%s)" % (t, head[:24]))
        return "ok" if not revivals else "hand-deleted item revived as its OWN material line: %s" % revivals
    if kind == "contains_any_in_material_rows":
        missing = [g for g, opts in a["groups"].items()
                   if not any(any(o in " | ".join(r) for o in opts) for r in rows)]
        return "ok" if not missing else "missing SKU groups in material rows: %s" % missing
    return "unknown kind %s" % kind


def check(data: dict, root: Path = ROOT) -> dict:
    """Real file check. Missing files -> UNVERIFIED, never PASS."""
    problems: list[str] = []
    file_states: dict[str, dict] = {}
    sheets_by_id: dict[str, dict] = {}
    texts_by_id: dict[str, str] = {}
    for f in data["files"]:
        p = root / f["path"]
        fid = f["id"]
        if not p.is_file():
            file_states[fid] = {"state": UNVERIFIED, "path": f["path"],
                                "note": "file missing (未跟踪工作副本 / CI clean checkout)"}
            continue
        h, size = sha256_of(p), p.stat().st_size
        hash_ok = (h == f["sha256"] and size == f["size_bytes"])
        info = {"state": VERIFIED if hash_ok else UNCONFIRMED, "path": f["path"],
                "sha256": h, "size_bytes": size,
                "recorded_sha256": f["sha256"], "recorded_size_bytes": f["size_bytes"],
                "hash_match": hash_ok}
        if f["kind"] in ("hand_edited_xlsx", "xlsx", "tmp_snapshot"):
            try:
                sheets = read_xlsx(p)
                sheets_by_id[fid] = sheets
                texts_by_id[fid] = "\n".join(sheet_text(sheets, s) for s in sheets)
            except Exception as e:  # a corrupt xlsx is never a green run
                info["state"] = SUSPECT
                info["note"] = "xlsx 无法用 stdlib 解析: %s" % e
        elif f["kind"] in ("generator_source", "ssot_markdown"):
            texts_by_id[fid] = p.read_text(encoding="utf-8", errors="replace")
        file_states[fid] = info

    anchor_states: list[dict] = []
    for a in data["semantic_anchors"]:
        fid = a["file"]
        if fid not in sheets_by_id and fid not in texts_by_id:
            anchor_states.append({"id": a["id"], "state": UNVERIFIED,
                                  "note": "依赖文件缺失，无法抽取锚点"})
            continue
        res = evaluate_anchor(a, texts_by_id, sheets_by_id)
        anchor_states.append({"id": a["id"], "state": "ok" if res == "ok" else "BROKEN",
                              "note": res})

    # cross-file invariants (e.g. tmp snapshot == buy sheet at baseline)
    invariant_states: list[dict] = []
    for x in data.get("cross_file_invariants") or []:
        l, r = file_states.get(x["left"], {}), file_states.get(x["right"], {})
        if l.get("state") == UNVERIFIED or r.get("state") == UNVERIFIED:
            invariant_states.append({"id": x["id"], "state": UNVERIFIED})
            continue
        equal = l.get("sha256") == r.get("sha256")
        expect = bool(x.get("expect_equal_at_baseline"))
        invariant_states.append({"id": x["id"], "state": "ok" if equal == expect else "DIVERGED",
                                 "note": "两文件字节%s，baseline 期望%s" %
                                         ("相同" if equal else "不同",
                                          "相同" if expect else "不同")})

    # --- verdict: four-valued, precedence: SUSPECT > UNVERIFIED > UNCONFIRMED > MATCH
    broken = [a for a in anchor_states if a["state"] == "BROKEN"]
    diverged = [x for x in invariant_states if x["state"] == "DIVERGED"]
    missing = [k for k, v in file_states.items() if v["state"] == UNVERIFIED]
    dirty = [k for k, v in file_states.items() if v["state"] == UNCONFIRMED]
    # A file that cannot even be parsed (corrupt xlsx) is set to SUSPECT at the
    # per-file level. It MUST escalate the whole verdict: otherwise a corrupt
    # sheet with intact recorded hashes still anchors nothing and would fall
    # through to BASELINE_MATCH -- a real false-green caught by selftest DIAG6.
    suspect_files = [k for k, v in file_states.items() if v["state"] == SUSPECT]
    if broken or diverged or suspect_files:
        verdict = SUSPECT
        for a in broken:
            problems.append("锚点破裂 %s: %s" % (a["id"], a["note"]))
        for x in diverged:
            problems.append("跨文件不变量 %s: %s" % (x["id"], x["note"]))
        for k in suspect_files:
            problems.append("文件解析失败/损坏 %s: %s" % (k, file_states[k].get("note", "")))
    elif missing:
        verdict = UNVERIFIED
        problems.append("登记文件缺失: %s" % missing)
    elif dirty:
        verdict = UNCONFIRMED
        problems.append("字节漂移但语义锚点全在（疑似合法手改，需人工 diff + 显式 re-baseline）: %s" % dirty)
    else:
        verdict = VERIFIED

    return {
        "tool": "check_procurement_baseline.py",
        "verdict": verdict,
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "recorded_at": data.get("baseline", {}).get("recorded_at"),
        "proves": data.get("scope", {}).get("proves"),
        "not_proof_of": data.get("scope", {}).get("not_proof_of", []),
        "files": file_states,
        "anchors": anchor_states,
        "cross_file_invariants": invariant_states,
        "problems": problems,
        "contract_sha256": sha256_of(CONTRACT),
        "scope": "采购域未跟踪工作副本相对 baseline 时点的字节+语义一致性；不验硬件、不追溯历史、不作签收",
    }


def selftest() -> int:
    data = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base_problems = validate(data)
    ck("盘上契约结构自校验通过", not base_problems, "; ".join(base_problems[:3]))
    ck("四态结论齐备", all(s in data["scope_semantics"]
                        for s in (VERIFIED, UNCONFIRMED, SUSPECT, UNVERIFIED)))
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("ship_verdict 恒 NOT_SHIPPABLE", data["scope"]["ship_verdict"] == "NOT_SHIPPABLE")
    ck("显式声明不追溯历史", any("过去从未" in x for x in data["scope"]["not_proof_of"]))
    ck("登记 6 个采购文件", len(data["files"]) == 6, "n=%d" % len(data["files"]))

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad)))

    must_fail("负对照：删掉全部语义锚点必红（纯 hash 不足以防覆盖）",
              lambda d: d.update({"semantic_anchors": []}))
    must_fail("负对照：sha256 非 hex 必红",
              lambda d: d["files"][0].update({"sha256": "z" * 64}))
    must_fail("负对照：sha256 大写必红",
              lambda d: d["files"][0].update({"sha256": "A" * 64}))
    must_fail("负对照：sha256 长度不足必红",
              lambda d: d["files"][0].update({"sha256": "0" * 63}))
    must_fail("负对照：file path 越界必红",
              lambda d: d["files"][0].update({"path": "../../etc/passwd"}))
    must_fail("负对照：删 recorded_at 必红",
              lambda d: d["baseline"].pop("recorded_at"))
    must_fail("负对照：ship_verdict 改 SHIPPABLE 必红",
              lambda d: d["scope"].update({"ship_verdict": "SHIPPABLE"}))
    must_fail("负对照：锚点引用不存在的文件必红",
              lambda d: d["semantic_anchors"][0].update({"file": "GHOST"}))
    must_fail("负对照：重复锚点 id 必红",
              lambda d: d["semantic_anchors"].append(copy.deepcopy(d["semantic_anchors"][0])))
    must_fail("负对照：抹掉 rebaseline 显式策略必红",
              lambda d: d["baseline"].update({"rebaseline_policy": "just do it"}))

    # --- xlsx reader + semantic anchors: build tiny REAL xlsx fixtures (stdlib zipfile)
    def make_xlsx(path: Path, sheet: str, rows: list[list[str]]) -> None:
        def esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        row_xml = []
        for i, row in enumerate(rows, 1):
            cells = []
            for j, val in enumerate(row):
                # [+1] column index -> its letter. _col_names(n)[-1] is the
                # n-th letter; [0] is ALWAYS 'A' and silently flattens all
                # columns into A, so every row reads back as one cell.
                ref = _col_names(j + 1)[-1] + str(i)
                cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, esc(val)))
            row_xml.append('<row r="%d">%s</row>' % (i, "".join(cells)))
        sheet_xml = ('<?xml version="1.0"?><worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>'
                     % (NS["m"], "".join(row_xml)))
        wb_xml = ('<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="%s">'
                  '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>'
                  % (NS["m"], RID.rsplit("}", 1)[0][1:], esc(sheet)))
        rels_xml = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/relationships"><Relationship Id="rId1" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                    'worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", wb_xml)
            z.writestr("xl/_rels/workbook.xml.rels", rels_xml)
            z.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    # Mirror the REAL sheet: rows 1-4 are title/SSOT/legend/header; material
    # rows are Excel rows 5..23 (19 rows). Overwrite specific material rows with
    # the 订正㉕ SKUs so the anchor groups are exercised on a realistic layout.
    good_rows = [["标题"], ["SSOT 指针"], ["图例"], ["☑", "阶段", "类别", "物料/SKU", "规格"]]
    for i in range(5, 24):
        good_rows.append(["☐", "阶段2", "核心", "物料%02d" % i, "spec"])
    good_rows[5 - 1 + 7] = ["☐", "阶段2", "取电", "取电板 = 人人 HUB 分线板", "banana"]
    good_rows[5 - 1 + 9] = ["☐", "阶段2", "结构件", "金属结构件（共 7 个）", "整套"]
    good_rows[5 - 1 + 6] = ["☐", "阶段2", "主控", "Radxa ZERO 3W 1GB / 无 eMMC", "179"]
    good_rows[5 - 1 + 11] = ["☐", "阶段2", "光学", "VL53L5CX V2 ToF", "49.5"]
    good_rows[5 - 1 + 10] = ["☐", "阶段2", "光学", "IMX219 摄像头", "160°"]

    with tempfile.TemporaryDirectory(prefix="md_procure_") as td:
        root = Path(td)
        good = root / "good.xlsx"
        make_xlsx(good, "照着买", good_rows)
        sheets = read_xlsx(good)
        ck("stdlib 读 inlineStr xlsx（不依赖 openpyxl）",
           "照着买" in sheets and sheets["照着买"][4][3] == "物料05",
           "row5 D=%r" % (sheets["照着买"][4][3],))
        rows = material_rows(sheets, "照着买", [5, 23])
        ck("正对照：19 行物料抽数正确",
           sum(1 for r in rows if any(c.strip() for c in r)) == 19)
        sku_anchor = {"id": "T_SKU", "why": "fixture", "kind": "contains_any_in_material_rows", "file": "BUY_SHEET",
                      "sheet": "照着买", "range": [5, 23],
                      "groups": {"HUB": ["人人 HUB 分线板"], "金属": ["金属结构件"],
                                 "主控": ["Radxa ZERO 3W 1GB"], "ToF": ["VL53L5CX"],
                                 "摄像头": ["IMX219"]}}
        ck("正对照：SKU 锚点全在", evaluate_anchor(sku_anchor, {}, {"BUY_SHEET": sheets}) == "ok")
        absent_anchor = {"id": "T_ABSENT", "why": "fixture", "kind": "absent_as_material_subject",
                         "file": "BUY_SHEET", "sheet": "照着买", "range": [5, 23],
                         "subject_col_index": 3,
                         "terms": ["直流稳压电源", "万用表", "转接线"]}
        ck("正对照：手删 3 项未作为独立物料行复活",
           evaluate_anchor(absent_anchor, {}, {"BUY_SHEET": sheets}) == "ok")

        # NEGATIVE CONTROL: the real 准则8 accident -- build.py overwrite 19 -> 16
        # (drop last 3 material rows = back to 16) AND revive a hand-deleted row
        # as its OWN material line (subject cell literally starts with the term).
        bad_rows = good_rows[:16] + [["☐", "阶段2", "供电", "直流稳压电源 15V/5A", "重跑写回"]]
        bad = root / "overwritten.xlsx"
        make_xlsx(bad, "照着买", bad_rows)
        bad_sheets = read_xlsx(bad)
        cnt_anchor = {"id": "T_COUNT", "why": "fixture", "kind": "material_row_count", "file": "BUY_SHEET",
                      "sheet": "照着买", "range": [5, 23], "expected": 19}
        rc = evaluate_anchor(cnt_anchor, {}, {"BUY_SHEET": bad_sheets})
        ck("负对照：19→16 行（build.py 覆盖）锚点必破", rc != "ok", rc)
        rv = evaluate_anchor(absent_anchor, {}, {"BUY_SHEET": bad_sheets})
        ck("负对照：手删行作为独立物料复活锚点必破", rv != "ok", rv)

        # rule-10 REAL CAPTURED CASE: the genuine xlsx has a legal material row
        # '扬声器…（kissqy 同源）+ 配套转接线', whose subject is '扬声器…' and
        # merely CONTAINS '转接线'. It must NOT be read as a revived 转接线 line.
        # sheets_by_id is keyed by FILE ID then sheet name; forgetting the fid
        # wrapper reads an empty set -> vacuous pass (caught by first real run).
        legal = [list(r) for r in good_rows]
        legal[5] = ["☐", "阶段2", "音频", "扬声器 3525腔体 4Ω3W（kissqy 同源）+ 配套转接线", "补件"]
        legal_sheets = {"BUY_SHEET": {"照着买": legal}}
        ck("正对照：合法『扬声器+配套转接线』不误红（准则10 实证）",
           evaluate_anchor(absent_anchor, {}, legal_sheets) == "ok")
        ck("正对照：合法『自带转接线』说明行不误红",
           evaluate_anchor(absent_anchor, {}, {"BUY_SHEET": {"照着买":
               [list(r) if i != 5 else ["☐", "阶段0", "调试", "URT-2 调试板（自带转接线）", "不另买"]
                for i, r in enumerate(good_rows)]}}) == "ok")

        # rule-10 negative: the OLD whole-line bare-substring rule WOULD bite
        # this exact legal row. Proving it red demonstrates the subject-based
        # redesign is non-zero-cost, not an arbitrary complexity.
        bare = dict(absent_anchor, kind="absent_in_material_rows", exclude_terms=[])
        ck("负对照：旧裸子串规则会误红合法配套行（证明主体判据非冗余）",
           evaluate_anchor(bare, {}, legal_sheets) != "ok")

        # --- four-state verdict engine on injected contract+root
        inj = copy.deepcopy(data)
        inj["files"] = [f for f in inj["files"] if f["id"] == "BUY_SHEET"]
        inj["files"][0]["path"] = "good.xlsx"
        # The injected contract must record the FIXTURE's real bytes, otherwise
        # 四态① can never reach MATCH (its hash would differ from the fixture).
        inj["files"][0]["sha256"] = hashlib.sha256(good.read_bytes()).hexdigest()
        inj["files"][0]["size_bytes"] = good.stat().st_size
        inj["files"][0]["kind"] = "hand_edited_xlsx"
        inj["semantic_anchors"] = [cnt_anchor, sku_anchor, absent_anchor]
        inj["cross_file_invariants"] = []
        ck("四态①：hash+锚点全中 → BASELINE_MATCH",
           check(inj, root)["verdict"] == VERIFIED, check(inj, root)["verdict"])

        # byte drift, anchors intact -> DRIFT_UNCONFIRMED (not green, not red)
        touched = root / "good.xlsx"
        touched.write_bytes(touched.read_bytes() + b"\n")  # harmless trailing byte
        ck("四态②：字节漂移但锚点在 → DRIFT_UNCONFIRMED（不冒充 PASS）",
           check(inj, root)["verdict"] == UNCONFIRMED, check(inj, root)["verdict"])

        # missing file -> UNVERIFIED (CI clean checkout), never PASS
        missing_contract = copy.deepcopy(inj)
        missing_contract["files"][0]["path"] = "no_such_file.xlsx"
        ck("四态③：文件缺失 → UNVERIFIED（CI 不误绿）",
           check(missing_contract, root)["verdict"] == UNVERIFIED)
        ck("负对照：UNVERIFIED 时 problems 非空且 verdict 非 MATCH",
           check(missing_contract, root)["verdict"] != VERIFIED
           and bool(check(missing_contract, root)["problems"]))

        # broken anchor -> COVERAGE_SUSPECT (red)
        suspect_contract = copy.deepcopy(inj)
        suspect_contract["files"][0]["path"] = "overwritten.xlsx"
        cp = check(suspect_contract, root)
        ck("四态④：锚点破裂 → COVERAGE_SUSPECT（判红）",
           cp["verdict"] == SUSPECT, cp["verdict"])

        # corrupt xlsx must not be green -- even when its BYTES MATCH the
        # contract (hash ok), an unparseable sheet anchors nothing and must
        # escalate to SUSPECT via the file-level path (Bug A regression).
        corrupt = root / "corrupt.xlsx"
        corrupt.write_bytes(b"not a zip")
        corrupt_contract = copy.deepcopy(inj)
        corrupt_contract["files"][0]["path"] = "corrupt.xlsx"
        corrupt_contract["files"][0]["sha256"] = hashlib.sha256(corrupt.read_bytes()).hexdigest()
        corrupt_contract["files"][0]["size_bytes"] = corrupt.stat().st_size
        ccp = check(corrupt_contract, root)
        ck("负对照：损坏 xlsx 即使 hash 匹配也必须判红（不可假绿）",
           ccp["verdict"] == SUSPECT, "%s / %s" % (
               ccp["verdict"], ccp["files"]["BUY_SHEET"].get("note", "")))

    for name, ok, note in checks:
        print("  %s %s%s" % ("ok  " if ok else "FAIL", name, ((" -- " + note) if note and not ok else "")))
    bad = [n for n, ok, _ in checks if not ok]
    print("\ncheck_procurement_baseline selftest: %d/%d passed"
          % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("scope: 采购域未跟踪工作副本相对 baseline 时点的一致性；不验硬件、不追溯历史、不签收。")
    print("verdict: PASS")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify real files against baseline (local only)")
    ap.add_argument("--selftest", action="store_true", help="injected xlsx fixtures + negative controls")
    ap.add_argument("--list", action="store_true", help="list registered files and anchors")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --check)")
    ap.add_argument("--root", default=str(ROOT), help="root that holds the procurement paths (tests)")
    ap.add_argument("--rebaseline", action="store_true", help="capture current bytes as new baseline")
    ap.add_argument("--confirm", action="store_true", help="required together with --rebaseline")
    ap.add_argument("--reason", default="", help="required audited reason for --rebaseline")
    args = ap.parse_args()

    data = load()
    if args.selftest:
        return selftest()
    if args.list:
        print("registered files = %d" % len(data["files"]))
        for f in data["files"]:
            print("  %-12s %-8s %s" % (f["id"], f["kind"], f["path"]))
        print("semantic anchors = %d" % len(data["semantic_anchors"]))
        for a in data["semantic_anchors"]:
            print("  %-28s %s" % (a["id"], a["kind"]))
        return 0

    if args.rebaseline:
        problems = validate(data)
        if problems:
            print("[REFUSE] contract invalid: " + "; ".join(problems), file=sys.stderr)
            return 2
        if not (args.confirm and args.reason.strip()):
            print("[REFUSE] --rebaseline requires --confirm --reason <audited reason>",
                  file=sys.stderr)
            return 2
        root = Path(args.root)
        # Capture current bytes; note (do NOT auto-pass) any file whose anchor breaks.
        rep = check(data, root)
        old = data.get("baseline", {})
        new_suspect = rep["verdict"] == SUSPECT
        # history must record the PREVIOUS authoritative hashes, so snapshot them
        # BEFORE overwriting any file entry.
        previous = {
            "at": old.get("recorded_at"),
            "sha256": {f["id"]: f["sha256"] for f in data["files"]},
            "size_bytes": {f["id"]: f["size_bytes"] for f in data["files"]},
            "verdict_before_rebaseline": rep["verdict"],
            "reason": args.reason.strip(),
        }
        for f in data["files"]:
            p = root / f["path"]
            if p.is_file():
                f["sha256"], f["size_bytes"] = sha256_of(p), p.stat().st_size
        if new_suspect:
            previous["anchor_broken_accepted"] = True
            previous["warning"] = ("本次 re-baseline 在 COVERAGE_SUSPECT 状态下强行接受，"
                                   "须人工确认非 build.py 覆盖事故")
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        history = old.get("history", [])
        history.append(previous)
        data["baseline"]["recorded_at"] = now
        data["baseline"]["recorded_by"] = "显式 --rebaseline --confirm；理由见 history[-1].reason"
        data["baseline"]["history"] = history
        CONTRACT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("re-baseline 写入 %s（未触碰任何采购文件）" % CONTRACT.name)
        print("recorded_at = %s" % now)
        print("verdict_before_rebaseline = %s" % rep["verdict"])
        if new_suspect:
            print("WARNING: 在锚点破裂状态下接受，已记 anchor_broken_accepted=true，请人工复核")
        return 0

    if not args.check:
        ap.print_help()
        return 2

    rep = check(data, Path(args.root))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("verdict = %s" % rep["verdict"])
        print("ship_verdict = %s" % rep["ship_verdict"])
        print("recorded_at = %s" % rep["recorded_at"])
        print("proves: %s" % rep["proves"])
        for fid, info in rep["files"].items():
            if info["state"] == VERIFIED:
                print("  [MATCH]       %-12s %s" % (fid, info["path"]))
            elif info["state"] == UNCONFIRMED:
                print("  [DRIFT?]      %-12s hash/size 变了 %s" % (fid, info["path"]))
            elif info["state"] == SUSPECT:
                print("  [SUSPECT]     %-12s %s" % (fid, info.get("note", "")))
            else:
                print("  [UNVERIFIED]  %-12s %s" % (fid, info["path"]))
        for a in rep["anchors"]:
            mark = "ok" if a["state"] == "ok" else (
                "MISSING" if a["state"] == UNVERIFIED else "BROKEN")
            print("  [anchor %-9s] %-28s %s" % (mark, a["id"], a["note"]))
        for x in rep["cross_file_invariants"]:
            print("  [invariant %-6s] %s %s" % (x["state"], x["id"], x.get("note", "")))
        for prob in rep["problems"]:
            print("  PROBLEM: %s" % prob)
        print("scope: " + rep["scope"])
        print("live_hardware_accessed = false")
        print("not proof of: " + "; ".join(rep["not_proof_of"]))
    # Green ONLY on a full MATCH. UNCONFIRMED / SUSPECT / UNVERIFIED all non-zero.
    return 0 if rep["verdict"] == VERIFIED else 1


if __name__ == "__main__":
    sys.exit(main())
