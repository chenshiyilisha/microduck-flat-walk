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


cc = _load("check_closure_test", HERE / "check_closure.py")


def test_every_marker_in_docs_has_a_contract_entry():
    data = cc.load()
    marks = cc.scan_doc_marks()
    ids = {c["id"] for c in data["contracts"]}
    assert ids == marks, (ids - marks, marks - ids)
    assert not cc.validate(data, marks)
    assert any(x.startswith("INCONCLUSIVE_LIVE_IDENTIFY") for x in ids)
    # C1: the roller decision is now a real contract, not just a delivery note.
    assert "INCONCLUSIVE_ROLLER_POLICY" in ids
    roller = next(c for c in data["contracts"]
                  if c["id"] == "INCONCLUSIVE_ROLLER_POLICY")
    assert roller["status"] == "UNVERIFIED" and roller["evidence"] == []
    assert roller["still_owed"] and roller["negative_control"]


def test_widened_scan_roots_are_explicit_and_walked():
    roots = cc.default_scan_roots()
    assert any(r.name == "docs" for r in roots)
    assert not any(".workbuddy" in r.as_posix() or ".upstream" in r.as_posix()
                   for r in roots)
    with tempfile.TemporaryDirectory(prefix="md_closure_test_") as td:
        extra = pathlib.Path(td) / "deliverable"
        extra.mkdir()
        (extra / "note.md").write_text(
            "INCONCLUSIVE_GHOST_MARKER is open\n", encoding="utf-8")
        widened = cc.scan_doc_marks(roots + [extra])
        assert "INCONCLUSIVE_GHOST_MARKER" in widened
        assert "INCONCLUSIVE_GHOST_MARKER" not in cc.scan_doc_marks(roots)
        # a marker in an extra root with no contract entry must turn the gate red
        assert cc.validate(cc.load(), widened)
        empty = pathlib.Path(td) / "empty"
        empty.mkdir()
        (empty / "note.md").write_text("nothing open\n", encoding="utf-8")
        assert "INCONCLUSIVE_GHOST_MARKER" not in cc.scan_doc_marks([empty])
    rep = cc.report(cc.load(), [], cc.scan_doc_marks(), roots)
    assert rep["scan_roots"] and rep["scan_excluded"]
    assert set(rep["scan_roots"]) == {r.relative_to(cc.ROOT).as_posix()
                                      for r in roots}


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
    # Do NOT pin the case count: C1 added scan-coverage negative controls and
    # the project has already been bitten by a hard-coded "n/n".
    m = re.search(r"(\d+)/(\d+) passed", selftest.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 17, selftest.stdout

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


def _grade(base_ids, extra_mark, where):
    """Inject a synthetic by_source/tracked pair; never touches the workspace."""
    by_source = {m: [{"file": "docs/a.md", "tracked": True}] for m in base_ids}
    if extra_mark:
        by_source[extra_mark] = [{"file": where, "tracked": (where == "docs/a.md")}]
    data = cc.load()
    return cc.grade_env(data, by_source, {"docs/a.md"}, cc.validate(data, set(by_source)))


def test_explain_classifier_separates_draft_red_from_ci_red():
    """Pure, disk-independent: a benign local draft red != a real committed red."""
    ids = [c["id"] for c in cc.load()["contracts"]]
    ghost = "INCONCLUSIVE_GHOST_MARKER"

    aligned = _grade(ids, None, None)
    assert aligned["classification"] == "ALIGNED"
    assert aligned["local_structure_verdict"] == "PASS"
    assert aligned["committed_structure_verdict"] == "PASS"

    draft = _grade(ids, ghost, "docs/active/untracked_draft.md")
    assert draft["classification"] == "LOCAL_ONLY_DRAFT_RED"
    assert draft["local_structure_verdict"] == "FAIL"          # local --check is red
    assert draft["committed_structure_verdict"] == "PASS"      # CI clean tree is green
    assert draft["ci_unregistered_markers"] == []
    assert draft["ship_verdict"] == "NOT_SHIPPABLE"            # never升格

    real = _grade(ids, ghost, "docs/a.md")                     # tracked doc carries it
    assert real["classification"] == "REAL_CI_RED"
    assert real["committed_structure_verdict"] == "FAIL"
    assert ghost in real["ci_unregistered_markers"]

    nogit = cc.grade_env(cc.load(), {"INCONCLUSIVE_GHOST_MARKER": [
        {"file": "docs/active/x.md", "tracked": False}]}, None, [])
    assert nogit["classification"] == "INCONCLUSIVE_NO_GIT"
    assert nogit["committed_structure_verdict"] == "UNKNOWN"   # never claim green


def test_explain_cli_json_is_serializable_and_not_a_gate():
    """CLI regression: --explain --json must parse on ANY workspace (set bug guard)."""
    p = subprocess.run([sys.executable, str(HERE / "check_closure.py"),
                        "--explain", "--json"], cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr            # diagnostic is never a gate
    rep = json.loads(p.stdout)                                # would raise on raw set
    assert rep["mode"] == "explain" and rep["not_a_gate"]
    assert rep["classification"] in ("ALIGNED", "LOCAL_ONLY_DRAFT_RED", "REAL_CI_RED")
    assert rep["live_hardware_accessed"] is False
    assert isinstance(rep["committed_view_markers"], list)    # serialized, not a set
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"


def test_explain_does_not_change_check_verdict_semantics():
    """--explain reports the SAME local structure verdict that --check enforces."""
    check = subprocess.run([sys.executable, str(HERE / "check_closure.py"), "--check", "--json"],
                           cwd=str(ROOT), capture_output=True, text=True)
    exp = subprocess.run([sys.executable, str(HERE / "check_closure.py"),
                          "--explain", "--json"], cwd=str(ROOT), capture_output=True, text=True)
    c, e = json.loads(check.stdout), json.loads(exp.stdout)
    # --check rc still reflects local problems (red on a dirty tree, green on CI);
    # --explain never overrides it, it just explains. Local verdicts must agree.
    assert c["structure_verdict"] == e["local_structure_verdict"]
    assert (check.returncode == 0) == (c["structure_verdict"] == "PASS")
    assert exp.returncode == 0
