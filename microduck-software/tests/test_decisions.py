"""D1 decision-ledger regression tests.

The point of this file is the CLI, not just the pure functions: the project has
been bitten by "50 unit tests green but the --selftest command dies at argparse"
before. Every test below that matters runs the real tool as a subprocess.
"""
from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
TOOL = HERE / "tools" / "hd1910" / "check_decisions.py"
CONTRACT = HERE / "tools" / "hd1910" / "decision_contract.json"
PY = sys.executable


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(TOOL), *args], cwd=str(HERE),
                          capture_output=True, text=True, encoding="utf-8")


def load():
    return json.loads(io.open(CONTRACT, encoding="utf-8").read())


def test_selftest_cli_passes_and_prints_verdict_line():
    """The real --selftest command must pass (not just the pure functions)."""
    r = run("--selftest")
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-300:]
    assert "self-test: PASS" in r.stdout
    assert "verdict: PASS" in r.stdout
    assert "live_hardware_accessed=false" in r.stdout


def test_check_cli_passes_with_landed_markers():
    """Real docs have landed their DECISION_* markers: --check must be green."""
    r = run("--check")
    assert r.returncode == 0, r.stdout
    assert "verdict: LOCAL_RESOLUTION_ONLY" in r.stdout
    assert "ship_verdict: NOT_SHIPPABLE" in r.stdout


def test_check_json_shape():
    r = run("--check", "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["ship_verdict"] == "NOT_SHIPPABLE"
    assert d["live_hardware_accessed"] is False
    assert d["verdict"] == "LOCAL_RESOLUTION_ONLY"
    assert d["problems"] == []
    assert "DECISION_HOSTIMU_GATE" in d["decisions"]
    assert d["doc_markers"] == sorted(d["decisions"])
    assert len(d["contract_sha256"]) == 64


def test_list_cli_shows_three_decisions():
    r = run("--list")
    assert r.returncode == 0
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 3
    assert any("DECISION_HOSTIMU_GATE" in l and "DEFERRED" in l for l in lines)


def test_captured_real_case_is_registered():
    d = load()
    ids = {x["id"] for x in d["decisions"]}
    assert "DECISION_HOSTIMU_GATE" in ids
    hostimu = next(x for x in d["decisions"] if x["id"] == "DECISION_HOSTIMU_GATE")
    # The two docs that had opposite readings must both be cited as source_refs.
    refs = " ".join(hostimu["source_refs"])
    assert "BNO085" in refs and "kissqy" in refs
    assert hostimu["conflicts_with"]  # the drift is explicitly recorded
    assert len(hostimu["reopen_when"]) >= 12


def test_contract_orthogonal_to_a2():
    """D1 must not duplicate closure_contract (A2) semantics."""
    d = load()
    assert "INCONCLUSIVE" in d["orthogonality"]
    assert "正交" in d["orthogonality"]
    assert d["scope"]["ship_verdict"] == "NOT_SHIPPABLE"


def test_stale_phrase_detection_with_marker_vs_without():
    """The real information bug: watch+stale no pointer -> red; pointer -> green."""
    sys.path.insert(0, str(HERE / "tools" / "hd1910"))
    import check_decisions as cd  # noqa: E402
    data = load()
    marks = {x["id"] for x in data["decisions"]}
    docs = cd.walk_markdown()
    stale = [("docs/fake.md", "C-IMU（新增）：HostImuGate 50ms/1s/3-repeats，细化两代次门控。")]
    probs = cd.validate(data, marks, stale)
    assert any("stale口径未指向决议" in x for x in probs)
    landed = [("docs/fake.md", stale[0][1] + " → 见 DECISION_HOSTIMU_GATE，本仓不搬。")]
    assert not any("stale口径" in x for x in cd.validate(data, marks, landed))


def test_owner_path_normalisation_negative_control():
    """Windows backslash paths must not silently disable the owner assertion."""
    sys.path.insert(0, str(HERE / "tools" / "hd1910"))
    import check_decisions as cd  # noqa: E402
    data = load()
    marks = {x["id"] for x in data["decisions"]}
    owner = data["decisions"][0]["decided_in"].split()[0]
    # A doc at the owner path WITHOUT the marker must turn the gate red even if
    # the compare uses OS-native separators internally.
    missing = cd.validate(data, marks, [(owner, "no marker here")])
    assert any("owner doc" in x for x in missing)
    present = cd.validate(data, marks, [(owner, "DECISION_HOSTIMU_GATE 本仓不搬")])
    assert not any("owner doc" in x for x in present)


def test_mutating_contract_turns_check_red():
    """Negative control on the contract itself (pure-function level)."""
    sys.path.insert(0, str(HERE / "tools" / "hd1910"))
    import check_decisions as cd  # noqa: E402
    data = load()
    marks = {x["id"] for x in data["decisions"]}
    docs = cd.walk_markdown()
    assert not cd.validate(data, marks, docs)
    bad = copy.deepcopy(data)
    bad["decisions"][0]["reopen_when"] = ""  # arbitrary permanent veto
    assert cd.validate(bad, marks, docs)
    bad2 = copy.deepcopy(data)
    bad2["decisions"][0]["status"] = "PENDING"  # decision must not be do-able
    assert cd.validate(bad2, marks, docs)
