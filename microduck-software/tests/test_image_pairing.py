"""Regression tests for B2 (image / firmware / console / IMU version pairing).

CPU-only, stdlib-only, no robot. The important assertions are the two
different hashes for the IMU HEX (file vs decoded Flash image) and the
negative control proving --verify-sources refuses a tampered HEX.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_image_pairing.py -q
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


ip = _load("image_pairing_test", HERE / "check_image_pairing.py")
SCRIPT = str(HERE / "check_image_pairing.py")
PASSED = re.compile(r"(\d+)/(\d+) passed")


def test_contract_is_the_single_source_of_truth():
    data = ip.load()
    assert not ip.validate(data)
    assert {s["id"] for s in data["slots"]} == set(data["required_slots"])
    kinds = {s["pin_kind"] for s in data["slots"]}
    assert "LOCAL_COMPUTED" in kinds and "UNOBTAINABLE" in kinds
    assert ip.overall_verdict(data) == "NOT_SHIPPABLE"
    assert data["scope"]["live_hardware_accessed"] is False


def test_two_imu_hashes_are_different_quantities():
    """HEX *file* sha and *decoded Flash image* sha must not be conflated."""
    data = ip.load()
    expected = next(s["expected"] for s in data["slots"]
                    if s["id"] == "imu_node_firmware_020")
    pins = ip.SHA.findall(expected)
    assert len(pins) == 2
    assert pins[0] != pins[1]

    # Independent in-process proof of the decoder semantics, with a real
    # file on disk rather than a mocked boolean.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="md_ip_test_") as td:
        p = pathlib.Path(td) / "tiny.hex"
        body = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        p.write_text("\n".join([ip.hexrec(0, bytes([0x08, 0x00]), 4),
                                ip.hexrec(0, body), ":00000001FF"]) + "\n",
                     encoding="ascii")
        img = ip.decode_intel_hex(p)
        assert img == body
        assert ip.sha256_bytes(img) != ip.sha256_bytes(p.read_bytes())


def test_real_hex_when_upstream_is_available():
    """Recompute both pins from the real first-party file when present.

    No pytest.skip: if .upstream is absent, assert the gate still refuses to
    claim verification (a missing source must not become a silent pass).
    """
    data = ip.load()
    upstream = ROOT / ".upstream"
    hex_path = (upstream / "replica" / "hardware" / "imu_to_dxl" / "firmware"
                / "Build" / "imu_to_dxl.hex")
    if not hex_path.is_file():
        res = ip.verify_sources(upstream / "_definitely_missing_dir_", data)
        assert res["all_ok"] is False
        assert res["root_exists"] is False
        return
    res = ip.verify_sources(upstream, data)
    assert res["all_ok"] is True, res["checks"]
    assert any(c["name"] == "IMU Flash image size 10724" and c["ok"]
               for c in res["checks"])
    assert res["control43_build_json_present"] is False


def test_tampered_hex_turns_source_verification_red(tmp_path):
    data = ip.load()
    fw = tmp_path / "replica" / "hardware" / "imu_to_dxl" / "firmware"
    (fw / "Build").mkdir(parents=True)
    tools = tmp_path / "replica" / "tools" / "radxa"
    tools.mkdir(parents=True)
    r1 = ip.SHA.findall(data["slots"][0]["expected"])[0]
    (tools / "kissqy-r1-v112.sh").write_text("R1_SHA=%s\n" % r1, encoding="utf-8")
    (fw / "VALIDATION.md").write_text(
        "decoded %s" % ip.SHA.findall(data["slots"][3]["expected"])[1],
        encoding="utf-8")
    bad_hex = fw / "Build" / "imu_to_dxl.hex"
    bad_hex.write_text("\n".join([ip.hexrec(0, bytes([0x08, 0x00]), 4),
                                  ip.hexrec(0, bytes([0, 0, 0, 0])),
                                  ":00000001FF"]) + "\n", encoding="ascii")
    res = ip.verify_sources(tmp_path, data)
    assert res["all_ok"] is False
    assert any(c["name"].startswith("IMU") and not c["ok"] for c in res["checks"])


def test_contract_corruption_turns_red():
    data = ip.load()
    bad = copy.deepcopy(data)
    bad["slots"][3]["pin_kind"] = "LOCAL_COMPUTED"
    bad["slots"][3]["local_file_present"] = False
    assert ip.validate(bad)

    bad = copy.deepcopy(data)
    bad["slots"][1]["local_file_present"] = True
    assert ip.validate(bad)


def test_cli_selftest_check_and_ship_gate_really_run():
    """Only testing internals would miss an argparse rc=2 at the CLI."""
    st = subprocess.run([sys.executable, SCRIPT, "--selftest"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr
    m = PASSED.search(st.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) > 0

    ok = subprocess.run([sys.executable, SCRIPT, "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    rep = json.loads(ok.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["live_hardware_accessed"] is False

    ship = subprocess.run([sys.executable, SCRIPT, "--check", "--ship-gate"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert ship.returncode == 1
    assert "SHIP GATE REFUSED" in ship.stdout
