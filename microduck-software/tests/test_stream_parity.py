"""Regression tests for the C4 SCS v1 stream-parser two-implementation parity gate.

CPU-only, stdlib-only, no robot. A real production parser (AST-extracted from
check_imu_bridge.py) and an independent byte state machine must frame a dirty
byte stream identically. Offline parity is not a sign-off.
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


sp = _load("check_stream_parity_test", HERE / "check_stream_parity.py")


def test_contract_structure_and_case_set():
    data = sp.load()
    assert not sp.validate(data), sp.validate(data)
    assert data["status"] == "OFFLINE_PARITY_ONLY"
    assert data["line"] == "META_GUARD"
    assert data["scope"]["live_hardware_accessed"] is False
    assert set(data["required_dirty_cases"]) == set(sp.build_cases())
    assert set(data["required_dirty_cases"]) == set(data["case_notes"])


def test_production_extraction_is_real_not_a_copy():
    src = (HERE / "check_imu_bridge.py").read_text(encoding="utf-8")
    prod = sp.extract_production(src)
    assert set(prod) == set(sp.EXTRACT_SYMBOLS)
    # The extracted parse_scs is the production function object, not our B.
    assert prod["parse_scs"] is not sp.parse_first_b
    # Protocol pins on the real source pass.
    assert not sp.verify_source(src), sp.verify_source(src)


def test_all_dirty_cases_byte_equal_with_expected_counts():
    src = (HERE / "check_imu_bridge.py").read_text(encoding="utf-8")
    prod = sp.extract_production(src)
    for cid, (buf, expected) in sp.build_cases().items():
        a, b, eq = sp.parity(buf, prod)
        assert eq, "%s: A/B byte-inequality" % cid
        assert len(a) == expected == len(b), \
            "%s: A=%d B=%d expected=%d" % (cid, len(a), len(b), expected)


def test_crlf_noise_regression_single_packet():
    """The exact bug the first real run caught: A used to double-frame this."""
    src = (HERE / "check_imu_bridge.py").read_text(encoding="utf-8")
    prod = sp.extract_production(src)
    buf = sp.build_cases()["crlf_noise"][0]
    a, b, eq = sp.parity(buf, prod)
    assert eq and len(a) == 1 and len(b) == 1, \
        "crlf_noise must frame exactly one packet in BOTH implementations"


def test_negative_controls_change_the_verdict():
    src = (HERE / "check_imu_bridge.py").read_text(encoding="utf-8")
    # Tamper production LEN+4 -> A/B must diverge.
    prod_bad = sp.extract_production(src.replace("total = length + 4",
                                                "total = length + 5"))
    buf = sp.build_cases()["valid_status_frame"][0]
    _a, _b, eq = sp.parity(buf, prod_bad)
    assert not eq, "tampered A still agreed with B (parity is a no-op)"

    # Inject a framing bug into B -> must diverge on some case.
    detected = False
    for _buf, _exp in sp.build_cases().values():
        try:
            if sp.frame_all(_buf, sp.parse_first_b_buggy) \
                    != sp.frame_all(_buf, sp.parse_first_b):
                detected = True
                break
        except RuntimeError:
            detected = True
            break
    assert detected, "injected B bug was not detected"


def test_contract_corruption_is_rejected():
    data = sp.load()

    def must_fail(mutate):
        bad = copy.deepcopy(data)
        mutate(bad)
        assert sp.validate(bad), "tampered contract accepted"

    must_fail(lambda d: d["required_dirty_cases"].pop())
    must_fail(lambda d: d.update({"status": "PASS"}))
    must_fail(lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail(lambda d: d["acceptance"].update({"empty_run_is_fail": False}))
    must_fail(lambda d: d["case_notes"].popitem())
    must_fail(lambda d: d["protocol"].update({"header": "00 00"}))
    must_fail(lambda d: d.update({"negative_controls": []}))


def test_cli_selftest_check_json_and_ship_gate():
    script = str(HERE / "check_stream_parity.py")
    selftest = subprocess.run([sys.executable, script, "--selftest"],
                              cwd=str(ROOT), capture_output=True, text=True)
    assert selftest.returncode == 0, selftest.stdout + selftest.stderr
    m = re.search(r"(\d+)/(\d+) passed", selftest.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 30, selftest.stdout

    check = subprocess.run([sys.executable, script, "--check"],
                           cwd=str(ROOT), capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "NOT_SHIPPABLE" in check.stdout
    assert "OFFLINE_PARITY_ONLY" in check.stdout

    gate = subprocess.run([sys.executable, script, "--check", "--ship-gate"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert gate.returncode == 1 and "SHIP GATE REFUSED" in gate.stdout

    js = subprocess.run([sys.executable, script, "--check", "--json", "--verify-source"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert js.returncode == 0, js.stdout + js.stderr
    rep = json.loads(js.stdout)
    assert rep["live_hardware_accessed"] is False
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["status"] == "UNVERIFIED"
    assert rep["all_byte_equal"] is True
    assert rep["negative_control_live"] is True
    assert rep["source_files_verified"] is True
    assert rep["total_framed_packets"] >= 12
