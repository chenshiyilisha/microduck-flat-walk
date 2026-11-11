"""Regression tests for B1 (board-acceptance checklist + evidence skeleton).

CPU-only, stdlib-only, no serial / no bus / no robot. The key assertion is
that --record stores COLLECTED and NEVER turns the ship gate green.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_board_acceptance.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ba = _load("board_acceptance_test", HERE / "board_acceptance.py")
SCRIPT = str(HERE / "board_acceptance.py")
PASSED = re.compile(r"(\d+)/(\d+) passed")


def test_cross_contract_coverage_is_exact():
    data = ba.load()
    closure = ba.load_closure()
    assert not ba.validate(data, closure)
    referenced = {r for c in data["checks"] for r in c["closure_refs"]}
    assert ba.open_contract_ids(closure) <= referenced
    assert referenced <= ba.all_contract_ids(closure)
    assert set(c["id"] for c in data["checks"]) == set(data["required_check_ids"])


def test_stale_2026_11_06_criteria_are_marked_not_current():
    data = ba.load()
    by_id = {c["id"]: c for c in data["checks"]}
    assert by_id["BA-0-1"]["authority"] == "SUPERSEDED"     # 2GB vs SSOT 1GB
    assert by_id["BA-0-2"]["authority"] == "SUPERSEDED"     # kissqy HAT vs 人人 C1
    assert by_id["BA-5-1"]["authority"] == "LINE_MISMATCH"  # HAT I2C vs bus ID200
    assert by_id["BA-6-2"]["authority"] == "LINE_MISMATCH"  # DuckBuddy keys
    assert by_id["BA-7-1"]["authority"] == "LINE_MISMATCH"  # uv run publish
    assert by_id["BA-4-4"]["authority"] == "BENCH_ONLY"     # 4.6V bench scale
    assert by_id["BA-6-3"]["authority"] == "BENCH_ONLY"     # bench P/D
    for c in data["checks"]:
        if c["authority"] in ("SUPERSEDED", "LINE_MISMATCH"):
            assert c["superseded_by"], c["id"]
            assert c["authority_note"], c["id"]


def test_deleting_or_adding_a_check_turns_red():
    data = ba.load()
    closure = ba.load_closure()
    bad = copy.deepcopy(data)
    bad["checks"].pop()
    assert ba.validate(bad, closure)
    bad = copy.deepcopy(data)
    bad["checks"].append(dict(data["checks"][0], id="BA-GHOST"))
    assert ba.validate(bad, closure)
    bad = copy.deepcopy(data)
    for c in bad["checks"]:
        c["closure_refs"] = []
    assert ba.validate(bad, closure)


def test_record_never_signs_off(tmp_path):
    ev = tmp_path / "dmesg.txt"
    ev.write_text("[  1.234] ttyS2 at MMIO 0xfeb50000\n", encoding="utf-8")
    edir = tmp_path / "evidence"
    rec = subprocess.run(
        [sys.executable, SCRIPT, "--record", "BA-3-2", "--value", "ttyS2 present",
         "--evidence", str(ev), "--evidence-dir", str(edir)],
        cwd=str(ROOT), capture_output=True, text=True)
    assert rec.returncode == 0, rec.stdout + rec.stderr
    payload = json.loads((edir / "BA-3-2.json").read_text(encoding="utf-8"))
    assert payload["verdict"] == "COLLECTED"
    assert len(payload["evidence_sha256"]) == 64
    assert payload["evidence_bytes"] > 0

    chk = subprocess.run(
        [sys.executable, SCRIPT, "--check", "--evidence-dir", str(edir), "--json"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout + chk.stderr
    rep = json.loads(chk.stdout)
    assert "BA-3-2" in rep["collected_evidence"]
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["live_hardware_accessed"] is False

    ship = subprocess.run(
        [sys.executable, SCRIPT, "--check", "--evidence-dir", str(edir), "--ship-gate"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert ship.returncode == 1
    assert "SHIP GATE REFUSED" in ship.stdout

    ghost = subprocess.run(
        [sys.executable, SCRIPT, "--record", "BA-GHOST", "--value", "x",
         "--evidence", str(ev), "--evidence-dir", str(edir)],
        cwd=str(ROOT), capture_output=True, text=True)
    assert ghost.returncode == 1


def test_signoff_and_evidence_are_both_required():
    data = ba.load()
    assert ba.overall_verdict(data, 0) == "NOT_SHIPPABLE"
    assert ba.overall_verdict(data, 5) == "NOT_SHIPPABLE"
    good = copy.deepcopy(data)
    good["signoff"] = {"status": "PASS", "evidence": ["synthetic"]}
    assert ba.overall_verdict(good, 0) == "NOT_SHIPPABLE"
    assert ba.overall_verdict(good, 1) == "SHIPPABLE"


def test_cli_selftest_list_and_check_really_run():
    st = subprocess.run([sys.executable, SCRIPT, "--selftest"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr
    m = PASSED.search(st.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) > 0

    lst = subprocess.run([sys.executable, SCRIPT, "--list"],
                         cwd=str(ROOT), capture_output=True, text=True)
    assert lst.returncode == 0
    # Count comes from the contract, never a hard-coded snapshot: C1 added
    # BA-9-1 (roller policy board check) and the old "total = 23" rotted.
    expected_total = len(ba.load()["checks"])
    assert "BA-7-1" in lst.stdout
    assert "total = %d" % expected_total in lst.stdout

    ok = subprocess.run([sys.executable, SCRIPT, "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    rep = json.loads(ok.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
