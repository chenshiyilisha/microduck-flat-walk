"""Regression tests for the A2 closure contract (UNVERIFIED != PASS).

CPU-only, stdlib-only, no robot. Four first-party sources agree that offline
results are not hardware acceptance; these tests lock that semantics down.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_closure_contract.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
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


cc = _load("check_closure_test", HERE / "check_closure.py")


def test_every_marker_in_docs_has_a_contract_entry():
    data = cc.load()
    marks = cc.scan_doc_marks()
    ids = {c["id"] for c in data["contracts"]}
    assert ids == marks, (ids - marks, marks - ids)
    assert not cc.validate(data, marks)
    assert any(x.startswith("INCONCLUSIVE_LIVE_IDENTIFY") for x in ids)


def test_unverified_is_not_a_pass():
    data = cc.load()
    assert cc.overall_verdict(data) == "NOT_SHIPPABLE"
    statuses = [c["status"] for c in data["contracts"]]
    assert "UNVERIFIED" in statuses
    assert "CLOSED" in statuses

    closed = copy.deepcopy(data)
    for c in closed["contracts"]:
        if c["status"] == "UNVERIFIED":
            c["status"] = "CLOSED"
            c["evidence"] = ["synthetic evidence"]
            c["still_owed"] = ["synthetic"]
    assert cc.overall_verdict(closed) == "SHIPPABLE"

    reopened = copy.deepcopy(closed)
    reopened["contracts"][0]["status"] = "UNVERIFIED"
    reopened["contracts"][0]["evidence"] = []
    assert cc.overall_verdict(reopened) == "NOT_SHIPPABLE"


def test_contract_corruption_turns_red():
    data = cc.load()
    marks = cc.scan_doc_marks()

    def must_fail(mutate):
        bad = copy.deepcopy(data)
        mutate(bad)
        assert cc.validate(bad, marks), "corrupted contract was accepted"

    must_fail(lambda d: d["contracts"].pop())
    must_fail(lambda d: d["contracts"].append(copy.deepcopy(d["contracts"][0])))
    must_fail(lambda d: d["contracts"][0].update({"id": "INCONCLUSIVE_GHOST"}))
    must_fail(lambda d: d["contracts"][0].update({"evidence": ["bogus"]}))
    must_fail(lambda d: [c.update({"evidence": []})
                         for c in d["contracts"] if c["status"] == "CLOSED"])
    must_fail(lambda d: d["contracts"][0].update({"negative_control": ""}))
    must_fail(lambda d: d["contracts"][0].update({"board_acceptance_required": []}))
    must_fail(lambda d: d.update({"contracts": []}))
    must_fail(lambda d: d["scope"].update({"live_hardware_accessed": True}))
    assert cc.validate(data, marks | {"INCONCLUSIVE_GHOST"})


def test_cli_selftest_check_and_ship_gate():
    selftest = subprocess.run([sys.executable, str(HERE / "check_closure.py"), "--selftest"],
                              cwd=str(ROOT), capture_output=True, text=True)
    assert selftest.returncode == 0, selftest.stdout + selftest.stderr
    assert "17/17 passed" in selftest.stdout

    check = subprocess.run([sys.executable, str(HERE / "check_closure.py"), "--check"],
                           cwd=str(ROOT), capture_output=True, text=True)
    assert check.returncode == 0
    assert "ship_verdict = NOT_SHIPPABLE" in check.stdout

    # A green structure check must NOT be mistaken for a ship sign-off.
    gate = subprocess.run([sys.executable, str(HERE / "check_closure.py"),
                           "--check", "--ship-gate"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert gate.returncode == 1
    assert "SHIP GATE REFUSED" in gate.stdout

    js = subprocess.run([sys.executable, str(HERE / "check_closure.py"), "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert js.returncode == 0
    rep = json.loads(js.stdout)
    assert rep["live_hardware_accessed"] is False
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["structure_verdict"] == "PASS"
