"""Regression tests for the C3 B1->A2 read-only evidence bridge.

A COLLECTED record is a fact, never an acceptance verdict. A2 remains the
single owner of "closed"; this bridge only makes the gap legible.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


le = _load("link_evidence_test", HERE / "link_evidence.py")


def test_links_are_derived_from_closure_refs_only():
    board, closure = le.load(), le.load(le.CLOSURE)
    links, problems = le.build_links(board, closure)
    assert not problems, problems
    assert not (HERE / "evidence_links.json").exists()
    for c in closure["contracts"]:
        if c["status"] == "UNVERIFIED":
            assert links[c["id"]], c["id"]
    expected = {ref for chk in board["checks"]
                for ref in chk["closure_refs"]}
    assert expected <= set(links)


def test_forged_records_turn_red():
    board, closure = le.load(), le.load(le.CLOSURE)
    ids = {c["id"] for c in board["checks"]}
    good = [{"id": "BA-4-2", "verdict": "COLLECTED",
             "evidence_sha256": "a" * 64, "evidence_bytes": 1, "_file": "x.json"}]
    assert not le.validate_records(good, ids, False)
    assert le.validate_records(
        [{"id": "BA-GHOST", "verdict": "COLLECTED",
          "evidence_sha256": "a" * 64, "evidence_bytes": 1}], ids, False)
    assert le.validate_records(
        [{"id": "BA-4-2", "verdict": "PASS",
          "evidence_sha256": "a" * 64, "evidence_bytes": 1}], ids, False)
    assert le.validate_records(
        [{"id": "BA-4-2", "verdict": "COLLECTED",
          "evidence_sha256": "nope", "evidence_bytes": 1}], ids, False)
    assert not le.validate(board, closure, good, False)

    bad_board = copy.deepcopy(board)
    bad_board["checks"][0]["closure_refs"].append("INCONCLUSIVE_GHOST")
    assert le.validate(bad_board, closure, [], False)
    bad_closure = copy.deepcopy(closure)
    bad_closure["contracts"].append(
        dict(bad_closure["contracts"][0], id="INCONCLUSIVE_GHOST", evidence=[]))
    assert le.validate(board, bad_closure, [], False)


def test_collected_evidence_never_closes_a_gap():
    script = str(HERE / "link_evidence.py")
    with tempfile.TemporaryDirectory(prefix="md_link_test_") as td:
        tmp = pathlib.Path(td)
        ev = tmp / "scope.txt"
        ev.write_text("waveform\n", encoding="utf-8")
        edir = tmp / "evidence"
        rec = subprocess.run(
            [sys.executable, str(HERE / "board_acceptance.py"), "--record", "BA-4-2",
             "--value", "500k bit width", "--evidence", str(ev),
             "--evidence-dir", str(edir)],
            cwd=str(ROOT), capture_output=True, text=True)
        assert rec.returncode == 0, rec.stdout + rec.stderr
        js = subprocess.run([sys.executable, script, "--check",
                             "--evidence-dir", str(edir), "--json"],
                            cwd=str(ROOT), capture_output=True, text=True)
        assert js.returncode == 0, js.stdout + js.stderr
        rep = json.loads(js.stdout)
        assert rep["ship_verdict"] == "NOT_SHIPPABLE"
        assert rep["a2_verdict"] == "NOT_SHIPPABLE"
        assert rep["collected_records"] == 1
        target = next(g for g in rep["gaps"]
                      if g["gap"] == "INCONCLUSIVE_RATE_MISMATCH")
        assert target["evidence_now"][0]["check_id"] == "BA-4-2"
        assert target["awaiting_signoff"] is True
        assert all(k in target for k in
                   ("gap", "evidence_now", "measurement", "closed_when"))

        gate = subprocess.run([sys.executable, script, "--check", "--ship-gate",
                               "--evidence-dir", str(edir)],
                              cwd=str(ROOT), capture_output=True, text=True)
        assert gate.returncode == 1

        ev.write_text("tampered\n", encoding="utf-8")
        verify = subprocess.run([sys.executable, script, "--check", "--verify",
                                 "--evidence-dir", str(edir)],
                                cwd=str(ROOT), capture_output=True, text=True)
        assert verify.returncode == 1 and "drift" in verify.stdout


def test_cli_selftest_and_json():
    script = str(HERE / "link_evidence.py")
    r = subprocess.run([sys.executable, script, "--selftest"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    m = re.search(r"(\d+)/(\d+) passed", r.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 17, r.stdout
    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert js.returncode == 0
    rep = json.loads(js.stdout)
    assert rep["live_hardware_accessed"] is False
    assert rep["structure_verdict"] == "PASS"
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
