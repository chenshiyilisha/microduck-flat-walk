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


def _meta_for(onnx: pathlib.Path) -> pathlib.Path | None:
    """Locate the companion runmeta/heading_meta for an ONNX stem (or None)."""
    run = onnx.stem
    if "_it" in run:
        run = run.rsplit("_it", 1)[0]
    for name in (f"runmeta_{run}.json", f"heading_meta_{run}.json"):
        p = ROOT / "out" / name
        if p.is_file():
            return p
    return None


def test_normalize_plant_all_formats():
    """``_normalize_plant`` must understand every plant shape the training side
    actually writes -- rehearsal preset-id string, training-side/DETECTED
    string, and the nested-dict heading_meta disambiguated by kp_fw. The old
    code raised TypeError on the nested dict and returned None on the
    training-side strings, so the cross-plant guard was dead for the real
    deploy-candidate ONNX."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    N = rh._normalize_plant
    # rehearsal preset ids (single source of truth in plant_spec)
    assert N("hd1910_openmicroduck_m5") == "m5"
    assert N("hd1910_official_m6_kp8") == "p8"
    assert N("hd1910_official_m6_kp5") == "p3"
    assert N("hd1910_ftservo_official_m6") == "ftservo"
    # training-side / DETECTED names (used by some runmetas)
    assert N("hd1910_kp8") == "p8"
    assert N("hd1910_kp5") == "p3"
    assert N("hd1910_ftservo_m6") == "ftservo"
    # nested-dict heading_meta
    assert N({"name": "hd1910_kp8", "kp_fw": 8.0}) == "p8"
    # generic "hd1910" name disambiguated by kp_fw -- the deploy-candidate path
    assert N({"name": "hd1910", "kp_fw": 8.0}) == "p8"
    assert N({"name": "hd1910", "kp_fw": 5.0}) == "p3"
    assert N({"name": "hd1910", "kp_fw": 32.0}) == "m5"
    # unresolvable -> None, never raises
    assert N(None) is None
    assert N({"name": "bogus"}) is None
    assert N(123) is None


def test_onnx_plant_key_real_metas():
    """``_onnx_plant_key`` must resolve the *real* meta files on disk, including
    the deploy-candidate p8head heading_meta (which used to raise TypeError)."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    # deploy candidate: nested-dict heading_meta, name='hd1910_kp8'
    assert rh._onnx_plant_key(
        ROOT / "out" / "p8head_030_4096x3000_resume2999_it2999.onnx") == "p8"
    # generic-name heading_meta disambiguated by kp_fw
    assert rh._onnx_plant_key(
        ROOT / "out" / "p8head_030_4096x3000_it2999.onnx") == "p8"
    assert rh._onnx_plant_key(
        ROOT / "out" / "p3head030_4096x2000_it1600.onnx") == "p3"
    # training-side string runmetas (used to return None)
    assert rh._onnx_plant_key(
        ROOT / "out" / "hd1910_roller_formal_1107_formal_it100.onnx") == "p8"
    assert rh._onnx_plant_key(
        ROOT / "out" / "hd1910_kp5_head015_4096x4000_resume_1030_0841_it100.onnx") == "p3"
    # preset-id string runmeta (previously the only working case)
    assert rh._onnx_plant_key(
        ROOT / "out" / "hd1910_explore_4096x2000_1026_it1999.onnx") == "m5"


def test_rehearsal_cross_plant_guard():
    """A p8 ONNX rehearsed at m5 must warn; at p8 must not. Exercises the real
    heading_meta nested-dict path (the deploy candidate), not a synthetic
    happy-path string -- the old code crashed or stayed silent there. The guard
    now resolves the plant from the meta alone, so the ONNX file need not exist."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    p8_onnx = ROOT / "out" / "p8head_030_4096x3000_resume2999_it2999.onnx"
    if _meta_for(p8_onnx) is None:
        import pytest
        pytest.skip("p8head heading_meta not present")
    # Case A: rehearse p8 onnx at m5 -> CROSS-PLANT warning.
    rh._STATE["key"] = "m5"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rh._inject_defaults(["--onnx", str(p8_onnx), "--out", "/tmp/x.json"], kp_fw=32.0)
    assert "CROSS-PLANT" in buf.getvalue()
    # Case B: rehearse p8 onnx at p8 -> no warning.
    rh._STATE["key"] = "p8"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rh._inject_defaults(["--onnx", str(p8_onnx), "--out", "/tmp/x.json"], kp_fw=8.0)
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
