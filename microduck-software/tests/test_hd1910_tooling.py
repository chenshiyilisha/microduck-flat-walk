"""Regression tests for the HD-1910 deploy/rehearsal/provenance tooling.

CPU-only, no GPU, no robot. Guards the plant-class first-class invariant at the
tooling layer: a cross-plant rehearsal must be refused loudly, the pre-deploy
conductor must classify stage return codes correctly, and provenance must always
carry the keys a reproducible run needs.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_tooling.py -q
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import contextlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"


def _load(modname: str, path: pathlib.Path):
    """Import a tool module by path without polluting the package namespace."""
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def test_conductor_classify():
    pc = _load("pre_deploy_check_test", HERE / "pre_deploy_check.py")
    assert pc._classify(0) == "PASS"
    assert pc._classify(1) == "FAIL"
    assert pc._classify(2) == "SKIP"
    # Anything else is treated as a failure, not silently passed.
    assert pc._classify(3) == "FAIL"


def test_conductor_selftest_runs():
    """The four guards must self-validate with no real policy / no robot."""
    proc = subprocess.run(
        [sys.executable, str(HERE / "pre_deploy_check.py"), "--selftest"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_rehearsal_onnx_plant_key():
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    onnx = ROOT / "out" / "hd1910_explore_4096x2000_1026_it1999.onnx"
    if not onnx.is_file():
        import pytest
        pytest.skip("m5 reference ONNX not present")
    assert rh._onnx_plant_key(onnx) == "m5"


def test_rehearsal_cross_plant_guard():
    """An m5 ONNX rehearsed at p8 must warn; at m5 must not."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    onnx = ROOT / "out" / "hd1910_explore_4096x2000_1026_it1999.onnx"
    if not onnx.is_file():
        import pytest
        pytest.skip("m5 reference ONNX not present")
    # Case A: rehearse m5 onnx at p8 (live) -> CROSS-PLANT warning.
    rh._STATE["key"] = "p8"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rh._inject_defaults(["--onnx", str(onnx), "--out", "/tmp/x.json"], kp_fw=8.0)
    assert "CROSS-PLANT" in buf.getvalue()
    # Case B: rehearse m5 onnx at m5 -> no warning.
    rh._STATE["key"] = "m5"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rh._inject_defaults(["--onnx", str(onnx), "--out", "/tmp/x.json"], kp_fw=32.0)
    assert "CROSS-PLANT" not in buf2.getvalue()


def test_provenance_keys():
    prov = _load("_provenance_test", HERE / "_provenance.py")
    rec = prov.capture_provenance(ROOT, seed=42, command=["train", "--agent.seed", "42"])
    # git identity must always be present (the reproducibility anchor).
    assert isinstance(rec["git_commit"], str) and len(rec["git_commit"]) >= 7
    assert isinstance(rec["git_dirty"], bool)
    assert rec["seed"] == 42
    assert rec["command"] == ["train", "--agent.seed", "42"]
    # Dependencies are best-effort but must be a dict, not an error.
    assert isinstance(rec["versions"], dict)
