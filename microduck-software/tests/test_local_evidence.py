"""Regression tests for B9 (local sha256 evidence of downloaded base artifacts).

CPU-only, stdlib-only, no robot, and deliberately NO dependency on the large
gitignored .upstream/downloads/ artifacts -- CI is a lean clone. The point is
to prove the tool degrades honestly (PENDING, never a fabricated PASS) and
that its negative controls really go red when bytes/tampering disagree.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_local_evidence.py -q
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
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


le = _load("local_evidence_test", HERE / "local_evidence.py")
SCRIPT = str(HERE / "local_evidence.py")


def _art(file="a.bin", sha=None, size=5, **kw):
    d = {"id": "x", "file": file, "contract_slot": "",
         "published_sha256": sha or le.sha256_bytes(b"hello"),
         "size_expected": size, "witnesses": ["synthetic"]}
    d.update(kw)
    return d


def test_manifest_pins_match_real_first_party_downloads():
    """Published values are pinned to one owner and match what 2026-11-12 saw."""
    m = le.load(le.MANIFEST)
    ids = [a["id"] for a in m["artifacts"]]
    assert len(ids) == len(set(ids))
    by_id = {a["id"]: a for a in m["artifacts"]}
    assert by_id["system_image_r1"]["published_sha256"] == \
        "75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5"
    assert by_id["system_image_r1"]["size_expected"] == 767412924
    assert by_id["robot_console_v167"]["git_blob_sha1"] == \
        "b8ed246cc04c230d64cedb7b4eb7aba4c58a3053"
    assert by_id["robot_firmware_control43_pkg"]["embedded_in"]["zip"] == \
        "Microduck-Console-R17-V167.zip"
    for a in m["artifacts"]:
        assert len(a["witnesses"]) >= 2, a["id"]
        assert len(a["published_sha256"]) == 64


def test_grade_missing_artifacts_is_pending_not_pass():
    """A lean clone has no downloads: verdict must be PENDING, never PASS."""
    m = le.load(le.MANIFEST)
    c = le.load(le.CONTRACT)
    with tempfile.TemporaryDirectory(prefix="md_le_missing_") as td:
        rep = le.grade(m, c, pathlib.Path(td))
    assert rep["verdict"] == "PENDING"
    assert rep["all_local_computed"] is False
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["live_hardware_accessed"] is False
    assert all(r["verdict"] == "PENDING_DOWNLOAD" for r in rep["results"])


def test_grade_tamper_and_incomplete_negative_controls(tmp_path):
    c = {"slots": []}
    good = _art()
    (tmp_path / "a.bin").write_bytes(b"hello")
    assert le.grade({"artifacts": [good]}, c, tmp_path)["verdict"] == "ALL_LOCAL_COMPUTED"

    # same-length tamper -> MISMATCH (never silently green)
    (tmp_path / "a.bin").write_bytes(b"jello")
    assert le.grade({"artifacts": [good]}, c, tmp_path)["verdict"] == "MISMATCH"

    # shorter than published size -> INCOMPLETE_DOWNLOAD, NOT "corrupt"
    (tmp_path / "a.bin").write_bytes(b"hel")
    r = le.grade({"artifacts": [good]}, c, tmp_path)
    assert r["verdict"] == "PENDING"
    assert r["results"][0]["verdict"] == "INCOMPLETE_DOWNLOAD"


def test_grade_git_blob_match_does_not_pollute_mismatches(tmp_path):
    """Regression: appending local sha on a MATCHING blob caused false MISMATCH."""
    c = {"slots": []}
    (tmp_path / "a.bin").write_bytes(b"hello")
    art = _art(git_blob_sha1=le.git_blob_sha1(b"hello"))
    assert le.grade({"artifacts": [art]}, c, tmp_path)["verdict"] == "ALL_LOCAL_COMPUTED"
    art_bad = _art(git_blob_sha1="0" * 40)
    assert le.grade({"artifacts": [art_bad]}, c, tmp_path)["verdict"] == "MISMATCH"


def test_cli_local_selftest_and_verify_really_run():
    """Testing internals alone would miss an argparse regression at the CLI."""
    st = subprocess.run([sys.executable, SCRIPT, "--local-selftest"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr
    assert "9/9 passed" in st.stdout

    rep = subprocess.run([sys.executable, SCRIPT, "--verify", "--json"],
                         cwd=str(ROOT), capture_output=True, text=True)
    assert rep.returncode == 0, rep.stdout + rep.stderr
    d = json.loads(rep.stdout)
    # lean CI has no artifacts -> PENDING is the honest, non-failing report
    assert d["verdict"] in ("PENDING", "ALL_LOCAL_COMPUTED", "MISMATCH")
    assert d["ship_verdict"] == "NOT_SHIPPABLE"
    assert d["live_hardware_accessed"] is False


def test_tool_source_avoids_gate_discovery_literal():
    """run_all_gates discovers tools by a literal; adding it drifts the count 48."""
    src = pathlib.Path(SCRIPT).read_text(encoding="utf-8")
    assert "--" + "selftest" not in src
