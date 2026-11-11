"""Regression tests for B8 (reproducible card recipe + rollback honesty).

CPU-only, stdlib-only, no dd / no card. The key assertions are: forbidden
flags are refused with a real rc=1 (never an argparse rc=2), and two
independent scripts disagreeing on the U-Boot sha turns the gate red.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_reproducible_card.py -q
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


rc = _load("reproducible_card_test", HERE / "reproducible_card.py")
SCRIPT = str(HERE / "reproducible_card.py")
PASSED = re.compile(r"(\d+)/(\d+) passed")


def test_recipe_is_the_single_source_of_truth():
    data = rc.load()
    assert not rc.validate(data)
    assert len(data["pins"]) >= 8
    assert data["rollback_contract"]["status"] == "NOT_IMPLEMENTED"
    assert rc.overall_verdict(data) == "NOT_SHIPPABLE"
    assert data["scope"]["live_hardware_accessed"] is False


def test_forbidden_flags_positive_assertions_only():
    data = rc.load()
    assert rc.audit_flags("--no-camera", data) == ["--no-camera"]
    assert rc.audit_flags("--no-tof", data) == ["--no-tof"]
    assert rc.audit_flags("--overlay i2c4-m0", data) == []
    # A lookalike flag must not be caught by a bare prefix rule.
    assert rc.audit_flags("--no-camera-debug", data) == []


def test_normalise_argv_prevents_argparse_rc2():
    assert rc.normalise_argv(["--check", "--flags", "--no-camera"]) == [
        "--check", "--flags=--no-camera"]
    assert rc.normalise_argv(["--check", "--flags", "--overlay i2c4-m0"]) == [
        "--check", "--flags=--overlay i2c4-m0"]
    assert rc.normalise_argv(["--check", "--json"]) == ["--check", "--json"]


def test_source_crosscheck_disagreement_turns_red(tmp_path):
    data = rc.load()
    radxa = tmp_path / "replica" / "tools" / "radxa"
    radxa.mkdir(parents=True)
    ub_sha = next(p["value"] for p in data["pins"] if p["id"] == "uboot_deb_sha256")
    ub_url = next(p["value"] for p in data["pins"] if p["id"] == "uboot_deb_url")
    r1_sha = next(p["value"] for p in data["pins"] if p["id"] == "r1_original_sha256")
    common = ("UBOOT_DEB_URL=%s\nUBOOT_DEB_SHA=%s\n"
              "dd if=x of=y bs=512 seek=64\ndd if=x of=y bs=512 seek=16384\n"
              "console=tty1\nserial-getty@ttyS2\n" % (ub_url, ub_sha))
    (radxa / "build-armbian-card.sh").write_text(common, encoding="utf-8")
    (radxa / "kissqy-r1-v112.sh").write_text(
        common + "R1_SHA=%s\n32768\n--no-camera\n--no-tof\n" % r1_sha,
        encoding="utf-8")
    assert rc.pins_from_sources(tmp_path, data)["all_ok"] is True

    (radxa / "kissqy-r1-v112.sh").write_text(
        common.replace(ub_sha, "1" * 64)
        + "R1_SHA=%s\n32768\n--no-camera\n--no-tof\n" % r1_sha,
        encoding="utf-8")
    res = rc.pins_from_sources(tmp_path, data)
    assert res["all_ok"] is False
    assert any("agree on U-Boot sha" in c["name"] and not c["ok"]
               for c in res["checks"])


def test_rollback_claim_without_evidence_turns_red():
    data = rc.load()
    bad = copy.deepcopy(data)
    bad["rollback_contract"]["status"] = "IMPLEMENTED"
    assert rc.validate(bad)

    good = copy.deepcopy(bad)
    good["rollback_contract"]["evidence"] = ["selftest synthetic"]
    for p in good["pins"]:
        if p["kind"] == "UPSTREAM_PUBLISHED":
            p["kind"] = "LOCAL_COMPUTED"
    good["signoff"] = {"status": "PASS", "evidence": ["selftest synthetic"]}
    assert rc.overall_verdict(good) == "SHIPPABLE"
    good["rollback_contract"]["status"] = "NOT_IMPLEMENTED"
    assert rc.overall_verdict(good) == "NOT_SHIPPABLE"


def test_cli_real_runs_including_the_argparse_trap():
    st = subprocess.run([sys.executable, SCRIPT, "--selftest"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr
    m = PASSED.search(st.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) > 0

    # Space-separated form used to be argparse rc=2 (GUARD INVOCATION BROKEN).
    bad = subprocess.run([sys.executable, SCRIPT, "--check", "--flags", "--no-camera"],
                         cwd=str(ROOT), capture_output=True, text=True)
    assert bad.returncode == 1, "rc=%d %s" % (bad.returncode, bad.stdout + bad.stderr)
    assert "forbidden flags refused" in bad.stdout

    eq = subprocess.run([sys.executable, SCRIPT, "--check", "--flags=--no-tof"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert eq.returncode == 1

    ok = subprocess.run([sys.executable, SCRIPT, "--check",
                         "--flags", "--overlay i2c4-m0", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    rep = json.loads(ok.stdout)
    assert rep["refused_flags"] == []
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["live_hardware_accessed"] is False

    ship = subprocess.run([sys.executable, SCRIPT, "--check", "--ship-gate"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert ship.returncode == 1
    assert "SHIP GATE REFUSED" in ship.stdout
