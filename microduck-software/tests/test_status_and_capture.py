"""Pass113 regression: derived contract status + read-only capture skeleton.

Both tools must work as REAL CLI processes (project rule: testing only internal
functions produced all-green suites while the CLI was broken). Negative
controls cover a moving derived quantity and the "pull the IMU" case.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cs = _load("check_contract_status_test", "check_contract_status.py")
bc = _load("board_capture_test", "board_capture.py")
cm = _load("ci_meta_targets_status_test", "ci_meta_targets.py")


def _workflow() -> str:
    return io.open(cs.WORKFLOW, encoding="utf-8").read()


def test_derived_status_cli_is_a_real_gate():
    r = subprocess.run([sys.executable, str(HERE / "check_contract_status.py"),
                        "--check", "--json"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["derived"]["unlabelled_count"] == 0
    assert rep["derived"]["ci_meta_step_present"] is True
    assert rep["live_hardware_accessed"] is False


def test_negative_control_deleting_a_label_moves_the_derived_count():
    labels = cs.load_json(cs.LABELS)
    bad = copy.deepcopy(labels)
    victim = bad["tools"].pop(0)["path"]
    d = cs.derive(bad, _workflow())
    assert d["unlabelled_count"] == 1
    assert d["unlabelled_selftest_tools"] == [victim]


def test_negative_control_restoring_a_prose_snapshot_is_rejected():
    contract = cs.load_json(cs.CONTRACT)
    labels = cs.load_json(cs.LABELS)
    stale = copy.deepcopy(contract)
    stale["scope"]["known_gaps"].append(
        "line_labels.json 仍有 20 个 --selftest 工具为 REPORT_ONLY")
    problems = cs.validate(stale, labels, cs.derive(labels, _workflow()))
    assert any("hardcoded status snapshot" in x for x in problems)


def test_capture_plan_cli_and_no_pass_claim():
    r = subprocess.run([sys.executable, str(HERE / "board_capture.py"),
                        "--check", "--json"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["live_hardware_accessed"] is False
    assert rep["plan"]["unmapped_owed"] == ["wifi_5g"]
    assert all(c["authority"] == "CURRENT"
               for o in rep["plan"]["owed"] for c in o["items"])
    assert "PASS" not in rep["capture_verdict"]


def test_negative_control_pull_the_imu(tmp_path):
    board = bc.load_json(bc.BOARD)
    chain = bc.signoff_chain(bc.load_json(bc.CHAIN))
    plan = bc.build_plan(board, chain)
    for cid in plan["required_check_ids"]:
        if cid in bc.IMU_CHECK_IDS:
            continue
        (tmp_path / ("%s.json" % cid)).write_text(
            json.dumps(bc._fake_record(cid)), encoding="utf-8")
    unplugged = bc.capture_verdict(board, plan, tmp_path)
    assert unplugged["capture_verdict"] == "INCOMPLETE"
    assert unplugged["imu_missing_check_ids"] == list(bc.IMU_CHECK_IDS)

    (tmp_path / "BA-5-2.json").write_text(
        json.dumps(bc._fake_record("BA-5-2")), encoding="utf-8")
    complete = bc.capture_verdict(board, plan, tmp_path)
    assert complete["capture_verdict"] == "COLLECTED"
    assert "PASS" not in complete["capture_verdict"]


def test_new_guards_are_in_the_derived_ci_list():
    names, problems, _ = cm.derive(cm.load())
    assert not problems, problems
    assert {"check_contract_status.py", "board_capture.py",
            "assert_ci_verdict.py", "bundle_bindings.py"} <= set(names)
