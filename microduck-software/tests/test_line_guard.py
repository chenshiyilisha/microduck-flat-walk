"""Regression tests for the A1 line guard (three hardware lines, no mixing).

CPU-only, stdlib-only, no robot. The important assertions are the negative
controls: disabling the cross-line refusal must let a B-generation tool
through, and corrupting line_labels.json must turn --check red.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_line_guard.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lg = _load("line_contract_test", HERE / "line_contract.py")
BTOOL = "tools/hd1910/audit_robotd_toml.py"


def test_labels_are_the_single_source_of_truth():
    data = lg.load()
    assert set(data["lines"]) == {"L1_RADXA_MIRROR", "L2_BGEN", "L3_SELFWRITTEN_SCS"}
    assert data["lines"]["L1_RADXA_MIRROR"]["baud"] == 1000000
    assert data["lines"]["L2_BGEN"]["baud"] == 500000
    # L1 and L3 legitimately share 1 Mbps; the guard must NOT call them equal.
    assert data["lines"]["L3_SELFWRITTEN_SCS"]["baud"] == 1000000
    assert data["lines"]["L1_RADXA_MIRROR"]["reg6"] == 0
    assert data["lines"]["L2_BGEN"]["reg6"] == 1
    assert not lg.validate(data)


def test_gain_200_is_shared_not_a_line_discriminator():
    """The previous round wrongly called policy.gain=200 a B-gen hardcode."""
    data = lg.load()
    facts = [x["fact"] for x in data["shared_not_discriminators"]]
    assert any("gain = 200" in f for f in facts)
    bad = copy.deepcopy(data)
    for t in bad["tools"]:
        if t["path"] == BTOOL:
            t["risk_tokens"].append("policy.gain = 200")
    assert any("shared non-discriminator" in x for x in lg.validate(bad))


def test_cross_line_refusal_and_its_negative_control():
    data = lg.load()
    with pytest.raises(lg.LineMismatch):
        lg.assert_for_line(data, BTOOL, "L1_RADXA_MIRROR")
    # Disabling the guard must let it through: proof the check is not a no-op.
    assert lg.assert_for_line(data, BTOOL, "L1_RADXA_MIRROR",
                              enforce=False).startswith("WOULD_ALLOW:")
    assert lg.assert_for_line(data, BTOOL, "L2_BGEN").startswith("LINE_OK")
    assert lg.assert_for_line(data, "tools/hd1910/verify_official_loader.py",
                              "L3_SELFWRITTEN_SCS").startswith("LINE_OK")
    with pytest.raises(lg.LineMismatch):
        lg.assert_for_line(data, "tools/hd1910/not_registered.py", "L1_RADXA_MIRROR")


def test_label_corruption_turns_red():
    data = lg.load()
    bad = copy.deepcopy(data)
    for t in bad["tools"]:
        if t["path"] == BTOOL:
            t["risk_tokens"] = ["THIS_TOKEN_DOES_NOT_EXIST"]
    assert any("stale risk token" in x for x in lg.validate(bad))

    bad = copy.deepcopy(data)
    bad["tools"] = []
    assert any("empty tools" in x for x in lg.validate(bad, with_sources=False))

    bad = copy.deepcopy(data)
    a, b = bad["lines"]["L1_RADXA_MIRROR"], bad["lines"]["L2_BGEN"]
    for k in ("baud", "reg6", "joint_ids", "imu_path", "deploy_chain", "board"):
        b[k] = a[k]
    assert any("differ in only" in x for x in lg.validate(bad, with_sources=False))


def test_cli_selftest_and_check_really_run():
    """Only internal functions would miss an argparse rc=2 at the CLI."""
    selftest = subprocess.run([sys.executable, str(HERE / "line_contract.py"), "--selftest"],
                              cwd=str(ROOT), capture_output=True, text=True)
    assert selftest.returncode == 0, selftest.stdout + selftest.stderr
    # Do not hardcode the count: B4 adds new self-checks, so the number grows.
    # Assert the *shape* (a N/N summary, ran >= 1, no failed) instead of a
    # stale snapshot. Search the whole stdout: the summary is not the last
    # line (a "scope:" footer follows it).
    sums = re.findall(r"(\d+)/(\d+) passed", selftest.stdout)
    assert sums and all(a == b for a, b in sums) and int(sums[-1][0]) >= 1, (
        "selftest must report an all-passed N/N summary: %r" % selftest.stdout[-200:])
    assert "FAIL" not in selftest.stdout.upper(), selftest.stdout[-200:]

    check = subprocess.run([sys.executable, str(HERE / "line_contract.py"), "--check", "--json"],
                           cwd=str(ROOT), capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    assert '"verdict": "PASS"' in check.stdout
    assert '"live_hardware_accessed": false' in check.stdout


def test_cli_refuses_a_b_generation_tool_for_the_shipped_robot():
    bad = subprocess.run([sys.executable, str(HERE / "line_contract.py"),
                          "--tool", BTOOL, "--line", "L1_RADXA_MIRROR"],
                         cwd=str(ROOT), capture_output=True, text=True)
    assert bad.returncode == 1
    assert "REFUSED" in bad.stdout
    ok = subprocess.run([sys.executable, str(HERE / "line_contract.py"),
                         "--tool", BTOOL, "--line", "L2_BGEN"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert ok.returncode == 0 and "LINE_OK" in ok.stdout
