"""B5 部署链线别契约回归测试（CLI 真跑 + 负对照）。"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
TOOLS = ROOT / "tools" / "hd1910"
SCRIPT = TOOLS / "check_deploy_chain.py"
CONTRACT = TOOLS / "deploy_chain_contract.json"
LABELS = TOOLS / "line_labels.json"

spec = importlib.util.spec_from_file_location("check_deploy_chain", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                         cwd=str(ROOT), capture_output=True, text=True)


def test_selftest_cli_really_runs():
    r = cli("--selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "31/31 passed" not in r.stdout or "passed" in r.stdout
    assert "self-test: PASS" in r.stdout


def test_check_json_is_pure_json_and_honest():
    r = cli("--check", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().startswith("{")
    rep = json.loads(r.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["problems"] == []
    assert rep["live_hardware_accessed"] is False
    assert rep["current_line"] == "L1_RADXA_MIRROR"
    assert set(rep["chain_status"]) == {
        "L1_CONSOLE_R17_V167", "L2_PUBLISH_ROBOTCTL", "L3_OFFICIAL_DAEMON"}


def test_ship_gate_refuses():
    r = cli("--check", "--ship-gate")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "SHIP GATE REFUSED" in r.stdout


def test_contract_is_only_owner_of_chains_not_of_lines():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    assert "current_line" not in data  # 单一主人在 line_labels.json
    assert data["authority"]["single_source_of_line"] == "line_labels.json#policy.current_line"
    assert labels["policy"]["current_line"] == "L1_RADXA_MIRROR"
    assert not mod.validate(data, labels)


def test_collection_equality_and_corruption_negative_controls():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    req = data["required"]
    assert {c["id"] for c in data["chains"]} == set(req["chain_ids"])
    assert {b["id"] for b in data["borrowed_invariants"]} == set(req["borrowed_ids"])
    assert {s["id"] for s in data["superseded_statements"]} == set(req["superseded_ids"])

    bad = copy.deepcopy(data)
    bad["borrowed_invariants"].pop()
    assert mod.validate(bad, labels)  # 集合相等断言必红

    bad2 = copy.deepcopy(data)
    for c in bad2["chains"]:
        if c["id"] == "L2_PUBLISH_ROBOTCTL":
            c["status"] = "CURRENT_SIGNOFF"
    assert mod.validate(bad2, labels)


def test_cross_line_refusal_and_would_allow():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    try:
        mod.assert_for_line(data, labels, "L2_PUBLISH_ROBOTCTL", "L1_RADXA_MIRROR")
        raise AssertionError("B 代 publish 链不得给路① 签收")
    except mod.LineMismatch:
        pass
    assert mod.assert_for_line(data, labels, "L2_PUBLISH_ROBOTCTL",
                                "L1_RADXA_MIRROR", enforce=False).startswith("WOULD_ALLOW:")
    assert mod.assert_for_line(data, labels, "L1_CONSOLE_R17_V167",
                                "L1_RADXA_MIRROR").startswith("OK:")


def test_cli_corrupted_contract_turns_red():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for c in data["chains"]:
        if c["id"] == "L2_PUBLISH_ROBOTCTL":
            c["status"] = "CURRENT_SIGNOFF"
    with tempfile.TemporaryDirectory() as d:
        bad = pathlib.Path(d) / "bad_contract.json"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        r = cli("--contract", bad, "--check")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        ok = cli("--check")
        assert ok.returncode == 0  # 删掉坏契约后恢复绿


def test_ambiguous_tokens_and_port_conflict_are_registered():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    tokens = {a["token"]: a for a in data["ambiguous_tokens"]}
    assert set(tokens) == {"robotctl", "8090", "studio", "publish", "9527"}
    assert all(len(a["senses"]) >= 2 for a in tokens.values())
    assert any(x["port"] == 8090 and len(x["claimants"]) >= 2
               for x in data["port_conflicts"])
    assert len(data["borrowed_invariants"]) == 11
    assert all(b.get("source") and b.get("adopted_as")
               for b in data["borrowed_invariants"])
