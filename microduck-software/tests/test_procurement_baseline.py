"""E2 procurement-baseline regression tests.

Point is the CLI + the four-state verdict, not just pure functions: this repo
was bitten by "50 unit tests green but --selftest dies at argparse" before.
Every behaviour that matters is exercised through a REAL subprocess.

These tests do NOT require the untracked procurement working copies (CI clean
checkout has none). They build real inlineStr xlsx fixtures with the stdlib and
point the tool at them via --root.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
HD = HERE / "tools" / "hd1910"
TOOL = HD / "check_procurement_baseline.py"
CONTRACT = HD / "procurement_baseline.json"
PY = sys.executable

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def run(*args: str, cwd: Path = HERE) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(TOOL), *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8")


def load():
    return json.loads(io.open(CONTRACT, encoding="utf-8").read())


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _col_names(n: int) -> list[str]:
    out = []
    for i in range(1, n + 1):
        s = ""
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        out.append(s)
    return out


def make_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    """Build a minimal multi-sheet inlineStr xlsx with the stdlib only."""
    wb_sheets, rels, files = [], [], []
    for idx, (name, rows) in enumerate(sheets.items(), 1):
        row_xml = []
        for i, row in enumerate(rows, 1):
            cells = []
            for j, val in enumerate(row):
                ref = _col_names(j + 1)[-1] + str(i)
                cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, esc(val)))
            row_xml.append('<row r="%d">%s</row>' % (i, "".join(cells)))
        sx = ('<?xml version="1.0"?><worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>'
              % (NS["m"], "".join(row_xml)))
        rid = "rId%d" % idx
        target = "worksheets/sheet%d.xml" % idx
        wb_sheets.append('<sheet name="%s" sheetId="%d" r:id="%s"/>' % (esc(name), idx, rid))
        rels.append('<Relationship Id="%s" Type="http://schemas.openxmlformats.org/'
                    'officeDocument/2006/relationships/worksheet" Target="%s"/>' % (rid, target))
        files.append(("xl/" + target, sx))
    wb = ('<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
          % (NS["m"], RID.rsplit("}", 1)[0][1:], "".join(wb_sheets)))
    rx = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
          'package/2006/relationships">%s</Relationships>' % "".join(rels))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rx)
        for n, body in files:
            z.writestr(n, body)


def buy_rows(n: int = 19) -> list[list[str]]:
    rows = [["标题"], ["SSOT 指针"], ["图例"], ["☑", "阶段", "类别", "物料 / SKU", "规格"]]
    for i in range(5, 5 + n):
        rows.append(["☐", "阶段2", "核心", "物料%02d" % i, "spec"])
    return rows


# --- CLI smoke (the real commands CI/local will run) ------------------------

def test_selftest_cli_passes():
    r = run("--selftest")
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-300:]
    assert "self-test: PASS" in r.stdout
    assert "verdict: PASS" in r.stdout
    assert "不验硬件" in r.stdout  # selftest prints scope:, not the --check field name


def test_list_cli():
    r = run("--list")
    assert r.returncode == 0
    assert "registered files = 6" in r.stdout
    assert "semantic anchors" in r.stdout


def test_real_check_cli_is_green_on_this_machine():
    """On the authoring machine the 6 working copies exist and are at baseline.
    In a CI clean checkout they do NOT, and the honest result is UNVERIFIED --
    either way the tool must NOT crash and must ship the NOT_SHIPPABLE boundary.
    """
    r = run("--check", "--json")
    assert r.returncode in (0, 1)
    d = json.loads(r.stdout)
    assert d["tool"] == "check_procurement_baseline.py"
    assert d["ship_verdict"] == "NOT_SHIPPABLE"
    assert d["live_hardware_accessed"] is False
    assert d["verdict"] in ("BASELINE_MATCH", "UNVERIFIED", "DRIFT_UNCONFIRMED",
                            "COVERAGE_SUSPECT")
    assert d["recorded_at"]
    assert len(d["files"]) == 6
    assert len(d["not_proof_of"]) >= 3


def test_missing_files_in_clean_checkout_is_unverified_not_pass(tmp_path):
    """CI-clean-checkout shape: root has none of the registered paths."""
    r = run("--check", "--json", "--root", str(tmp_path))
    assert r.returncode == 1  # UNVERIFIED is never a green exit
    d = json.loads(r.stdout)
    assert d["verdict"] == "UNVERIFIED"
    assert all(f["state"] == "UNVERIFIED" for f in d["files"].values())


# --- four-state engine on injected real fixtures ----------------------------

def _inject(tmp_path: Path, buy_sheet: dict[str, list[list[str]]] | None = None):
    """Build a one-file contract rooted at tmp_path, return (contract, root)."""
    data = load()
    data["files"] = [f for f in data["files"] if f["id"] == "BUY_SHEET"]
    data["cross_file_invariants"] = []
    f = data["files"][0]
    f["path"] = "buy.xlsx"
    f["kind"] = "hand_edited_xlsx"
    data["semantic_anchors"] = [
        {"id": "A_COUNT", "why": "test", "kind": "material_row_count", "file": "BUY_SHEET",
         "sheet": "照着买", "range": [5, 23], "expected": 19},
        {"id": "A_ABSENT", "why": "test", "kind": "absent_as_material_subject",
         "file": "BUY_SHEET", "sheet": "照着买", "range": [5, 23],
         "subject_col_index": 3, "terms": ["直流稳压电源", "万用表", "转接线"]},
    ]
    rows = buy_sheet or buy_rows()
    make_xlsx(tmp_path / "buy.xlsx", {"照着买": rows})
    f["sha256"] = hashlib.sha256((tmp_path / "buy.xlsx").read_bytes()).hexdigest()
    f["size_bytes"] = (tmp_path / "buy.xlsx").stat().st_size
    (tmp_path / "contract.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data, tmp_path


def check_with(contract: Path, root: Path) -> dict:
    # The tool reads its contract from a fixed path, so import and inject it.
    sys.path.insert(0, str(HD))
    import check_procurement_baseline as cp  # noqa: E402
    data = json.loads(io.open(contract, encoding="utf-8").read())
    return cp.check(data, root)


def test_state_match(tmp_path):
    _c, root = _inject(tmp_path)
    rep = check_with(tmp_path / "contract.json", root)
    assert rep["verdict"] == "BASELINE_MATCH", rep["problems"]


def test_state_byte_drift_unconfirmed(tmp_path):
    _c, root = _inject(tmp_path)
    (root / "buy.xlsx").write_bytes((root / "buy.xlsx").read_bytes() + b"\n")
    rep = check_with(tmp_path / "contract.json", root)
    assert rep["verdict"] == "DRIFT_UNCONFIRMED"
    assert rep["verdict"] != "BASELINE_MATCH"  # never pass a legal-but-unreviewed edit


def test_state_build_py_overwrite_is_suspect(tmp_path):
    """The real 准则8 accident: build.py writes back 16 rows + revives a deleted line."""
    rows = buy_rows(12)  # 4 header + 12 = only 12 material rows
    rows.append(["☐", "阶段2", "供电", "直流稳压电源 15V/5A", "重跑写回"])
    # _inject takes the ROW LIST (it wraps it under sheet name itself).
    # Passing {"照着买": rows} would write a 1-row sheet and make the test
    # pass for the WRONG reason (0 material rows) -- a vacuous false-green.
    _c, root = _inject(tmp_path, rows)
    rep = check_with(tmp_path / "contract.json", root)
    assert rep["verdict"] == "COVERAGE_SUSPECT"
    # Assert the REAL reason: row count collapsed below 19 AND a deleted line
    # revived as its own material subject -- not an empty-sheet accident. Do
    # NOT hardcode the collapsed number (it drifts with the fixture): require
    # the A_COUNT problem to carry a != expected 19 count signal.
    assert any("A_COUNT" in p and "expected 19" in p and "!=" in p
               for p in rep["problems"]), rep["problems"]
    assert any("A_ABSENT" in p for p in rep["problems"]), rep["problems"]


def test_legal_speaker_with_cable_not_false_red(tmp_path):
    """rule-10 real case: 扬声器+配套转接线 is legal, subject is 扬声器, not 转接线."""
    rows = buy_rows()
    rows[5] = ["☐", "阶段2", "音频", "扬声器 3525腔体 4Ω3W（kissqy 同源）+ 配套转接线", "补件"]
    _c, root = _inject(tmp_path, rows)
    # Guard against the vacuous false-green: the sheet really has 19 material
    # rows; we are testing the absent_anchor, not an empty-sheet pass.
    sys.path.insert(0, str(HD))
    import check_procurement_baseline as cp  # noqa: E402
    sh = cp.read_xlsx(root / "buy.xlsx")
    assert sum(1 for r in cp.material_rows(sh, "照着买", [5, 23]) if any(c.strip() for c in r)) == 19
    rep = check_with(tmp_path / "contract.json", root)
    assert rep["verdict"] == "BASELINE_MATCH", rep["problems"]


def test_corrupt_xlsx_even_with_matching_hash_never_green(tmp_path):
    _c, root = _inject(tmp_path)
    (root / "buy.xlsx").write_bytes(b"not a zip")
    # Re-record the corrupt bytes so the ONLY defect is "unparseable".
    data = json.loads(io.open(tmp_path / "contract.json", encoding="utf-8").read())
    data["files"][0]["sha256"] = hashlib.sha256((root / "buy.xlsx").read_bytes()).hexdigest()
    data["files"][0]["size_bytes"] = (root / "buy.xlsx").stat().st_size
    (tmp_path / "contract.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rep = check_with(tmp_path / "contract.json", root)
    assert rep["verdict"] == "COVERAGE_SUSPECT"


# --- contract self-validation ----------------------------------------------

def test_contract_never_claims_retrospective_proof():
    d = load()
    assert d["scope"]["live_hardware_accessed"] is False
    assert d["scope"]["ship_verdict"] == "NOT_SHIPPABLE"
    assert any("过去从未" in x for x in d["scope"]["not_proof_of"])
    assert "--rebaseline" in d["baseline"]["rebaseline_policy"]


def test_validate_mutated_contract_fails():
    sys.path.insert(0, str(HD))
    import check_procurement_baseline as cp  # noqa: E402
    d = load()
    assert not cp.validate(d)
    for mutate in (
        lambda x: x.update({"semantic_anchors": []}),
        lambda x: x["files"][0].update({"sha256": "z" * 64}),
        lambda x: x["files"][0].update({"path": "../../escape"}),
        lambda x: x["scope"].update({"ship_verdict": "SHIPPABLE"}),
        lambda x: x["baseline"].pop("recorded_at"),
    ):
        bad = copy.deepcopy(d)
        mutate(bad)
        assert cp.validate(bad), "mutated contract must fail validation"
