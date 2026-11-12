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


def test_list_cli_shows_every_registered_decision():
    """--list must show EVERY decision in the on-disk contract, not a frozen
    count. The ledger legitimately grew 3 -> 6 on 2026-11-12 (E4 registered
    three more NOT-to-do decisions); a hardcoded len==3 would have gone red on a
    valid growth and tempted someone to delete real entries. Assert the semantic
    relation instead, keeping a lower bound as the 'ledger not emptied' control.
    """
    r = run("--list")
    assert r.returncode == 0
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    contract_ids = {x["id"] for x in load()["decisions"]}
    listed_ids = {l.split()[0] for l in lines if l.strip()}
    assert len(lines) >= 3, "ledger must never be emptied (structural control)"
    assert contract_ids == listed_ids, (
        f"--list drifted from contract: missing={contract_ids - listed_ids}, "
        f"extra={listed_ids - contract_ids}")
    assert any("DECISION_HOSTIMU_GATE" in l and "DEFERRED" in l for l in lines)
    # E4 additions must each appear with their decided status.
    assert any("DECISION_SIM_TORQUE_BRINGUP" in l and "WITHDRAWN" in l for l in lines)
    assert any("DECISION_SIM_HEALTH_UNAVAILABLE" in l and "REJECTED" in l for l in lines)
    assert any("DECISION_MDUCK_CLI_GPU_LOCK" in l and "DEFERRED" in l for l in lines)
    assert any("DECISION_LOWLEVEL_RETRAIN_DEFERRED" in l and "DEFERRED" in l for l in lines)


def test_lowlevel_retrain_deferred_has_executable_reopen_and_no_stale_drift():
    """User 2026-11-12 chose 'defer until whole robot'. The ledger must own it:
    DEFERRED status, an executable reopen_when (board + ≥3 logs), and the owner
    plan doc must have landed the marker with the old 'await user decision'
    phrasing removed, so a later agent cannot re-mine the retrain as a TODO.
    """
    sys.path.insert(0, str(HERE / "tools" / "hd1910"))
    import check_decisions as cd  # noqa: E402
    d = load()
    dec = next(x for x in d["decisions"] if x["id"] == "DECISION_LOWLEVEL_RETRAIN_DEFERRED")
    assert dec["status"] == "DEFERRED"
    assert dec["resolution_marker"] == "DECISION_LOWLEVEL_RETRAIN_DEFERRED"
    rw = dec["reopen_when"]
    assert "BA-X-4" in rw and "上板" in rw  # executable, gated on whole robot
    assert any(ch.isdigit() for ch in rw)  # ≥3 log groups / measurable trigger
    assert "GPU" in dec["negative_control"]
    # real docs: marker landed in owner doc AND no watch+stale conflict anywhere
    docs = cd.walk_markdown()
    marks = {x["id"] for x in d["decisions"]}
    assert not cd.validate(d, marks, docs), cd.validate(d, marks, docs)
    owner_path = dec["decided_in"].split()[0].replace("\\", "/")
    assert any(rel.replace("\\", "/") == owner_path and dec["resolution_marker"] in text
               for rel, text in docs), "owner plan doc must carry its DECISION marker"
    # negative control: deleting this decision must turn --check-driven validate red
    bad = copy.deepcopy(d)
    bad["decisions"] = [x for x in bad["decisions"] if x["id"] != dec["id"]]
    text_by_owner = dict(docs)
    assert any("DECISION_LOWLEVEL_RETRAIN_DEFERRED" in x
               for x in cd.validate(bad, marks, docs)), (
                   "removing the owner decision while docs still reference it must go red")


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
