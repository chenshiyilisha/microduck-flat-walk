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
import pytest

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
    # deploy candidates SHIPPED WITHOUT a companion meta: the file-name heuristic
    # is the only thing that catches them. The old code returned None here, so the
    # guard silently passed the real policy that goes onto the robot.
    assert rh._onnx_plant_key(ROOT / "out" / "p8head_2999.onnx") == "p8"
    assert rh._onnx_plant_key(ROOT / "out" / "onnx_p3head030_it1600.onnx") == "p3"
    # deprecated XL330-origin samples must NOT be inferred as an HD1910 plant
    assert rh._onnx_plant_key(ROOT / "out" / "deploy61.onnx") is None
    assert rh._onnx_plant_key(ROOT / "out" / "walk_std004_1250.onnx") is None


def test_onnx_plant_key_real_exported_artifacts():
    """The actual policies that ship to the robot are exported by rsl_rl under a
    timestamped run directory (``2026-11-07_22-12-33_p8head_...``), while the
    companion runmeta/heading_meta are written WITHOUT that prefix. ``_onnx_plant_key``
    must strip the leading timestamp so the real artifacts resolve -- Pass9 found the
    groundpick and standup onnxs returning None, i.e. the guard going silent on exactly
    the artifact that goes onto the robot."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    real = [
        "logs/rsl_rl/microduck_velocity_hd1910/2026-11-07_22-12-33_p8head_030_4096x3000_resume2999/2026-11-07_22-12-33_p8head_030_4096x3000_resume2999.onnx",
        "logs/rsl_rl/microduck_groundpick_hd1910/2026-11-06_22-17-10_hd1910_groundpick_4096x4000_1106_2216/2026-11-06_22-17-10_hd1910_groundpick_4096x4000_1106_2216.onnx",
        "logs/rsl_rl/microduck_standup_hd1910/2026-11-08_03-08-50_p8_standup_4096x4000_1108_0308/2026-11-08_03-08-50_p8_standup_4096x4000_1108_0308.onnx",
    ]
    missing = [p for p in real if not (ROOT / p).exists()]
    if missing:
        pytest.skip("exported onnx artifacts not present in this checkout: "
                    + ", ".join(missing))
    for p in real:
        assert rh._onnx_plant_key(ROOT / p) == "p8", p


def test_rehearse_injects_cmd_vx_zero_for_nonwalk():
    """Non-walking policies (GroundPick / StandUp) must get --cmd-vx 0 so rehearsal's
    moves_forward gate becomes not_applicable instead of a spurious failure.

    Uses the REAL shipped groundpick onnx (its runmeta records task=
    Mjlab-GroundPick-Flat-MicroDuck). Regression for the Pass10 fix: before it,
    rehearse reported all_gates_pass=False for groundpick/standup purely because
    they ignore the default 0.4 m/s vel command."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    gp = ROOT / ("logs/rsl_rl/microduck_groundpick_hd1910/2026-11-06_22-17-10_"
                 "hd1910_groundpick_4096x4000_1106_2216/2026-11-06_22-17-10_"
                 "hd1910_groundpick_4096x4000_1106_2216.onnx")
    if not gp.exists():
        pytest.skip("groundpick onnx not present in this checkout")
    assert rh._onnx_task(gp) == "Mjlab-GroundPick-Flat-MicroDuck"
    rh._STATE["key"] = "p8"  # main() sets this before _inject_defaults runs
    out = rh._inject_defaults(["--onnx", str(gp)], 8.0)
    # --cmd-vx 0 must be injected (as a pair) for non-walking tasks
    assert "--cmd-vx" in out
    assert out[out.index("--cmd-vx") + 1] == "0"


def test_rehearse_keeps_default_for_walk():
    """Walk policies must NOT get --cmd-vx 0: rehearsal's default (0.4 m/s) genuinely
    exercises the moves_forward gate for them."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    walk = ROOT / ("logs/rsl_rl/microduck_velocity_hd1910/2026-11-07_22-12-33_"
                   "p8head_030_4096x3000_resume2999/2026-11-07_22-12-33_"
                   "p8head_030_4096x3000_resume2999.onnx")
    if not walk.exists():
        pytest.skip("walk onnx not present in this checkout")
    assert rh._is_walking_task(rh._onnx_task(walk)) is True
    rh._STATE["key"] = "p8"  # main() sets this before _inject_defaults runs
    out = rh._inject_defaults(["--onnx", str(walk)], 8.0)
    assert "--cmd-vx" not in out


def test_rehearsal_cross_plant_guard():
    """A p8 deploy-candidate ONNX rehearsed at m5 must warn; at p8 must not.

    Uses the REAL shipped candidate (``p8head_2999.onnx`` -- no companion meta),
    so the guard is exercised on the artifact that actually goes onto the robot.
    Its plant is resolved by the file-name heuristic, which means the ONNX file
    need not even exist for the guard to fire."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    p8_onnx = ROOT / "out" / "p8head_2999.onnx"
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


def test_rehearsal_plant_from_filename():
    """The deploy candidates ship without a companion meta, so the file-name
    heuristic must resolve them -- and must NOT invent a plant for the
    deprecated XL330-origin samples."""
    rh = _load("rehearse_hd1910_test", HERE / "rehearse_hd1910.py")
    f = rh._plant_from_filename
    assert f("p8head_2999") == "p8"
    assert f("p8head_030_4096x3000_resume2999") == "p8"
    assert f("p8ctl_030_1104") == "p8"
    assert f("onnx_p3head030_it1600") == "p3"
    assert f("p3head030_4096x2000_it1600") == "p3"
    assert f("p3ctl_xxx") == "p3"
    # anything ambiguous stays None, never guessed
    assert f("hd1910_explore_4096x2000_1026_it1999") is None
    assert f("deploy61") is None
    assert f("walk56") is None
    assert f("walk_std004_1250") is None


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


# ── Pass13: deploy-bundle provenance + inference smoke (对照开源项目) ──

def test_record_provenance_walk_deploy_onnx():
    """Provenance for the real walk deploy onnx must be harvested from its
    companion heading_meta (task / plant / cfg+mdp config hashes / created /
    export iteration) and merged with the code-side git fingerprint — without
    needing ``onnx``. This is the local analogue of upstream find_onnx_source."""
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    walk = ROOT / ("logs/rsl_rl/microduck_velocity_hd1910/"
                   "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999/"
                   "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999.onnx")
    if not walk.exists():
        pytest.skip(f"deploy onnx not present: {walk}")
    pv = rp.provenance_for_onnx(walk)
    assert pv.companion_meta == "heading_meta"
    assert pv.task == "Mjlab-Velocity-Flat-MicroDuck"
    assert pv.plant_name == "hd1910_kp8"
    assert pv.cfg_sha256_16 == "75a0430b814ac749"
    assert pv.mdp_sha256_16 == "9f9b77c05d16a1a3"
    assert pv.export_iteration == 2999
    # code-side fingerprint reuses _provenance.capture_provenance
    code = rp._provenance.capture_provenance(ROOT)  # noqa: SLF001
    assert isinstance(code["git_commit"], str) and len(code["git_commit"]) >= 40


def test_record_provenance_absent_meta_is_honest():
    """An onnx with NO companion meta must be reported as 'absent', never a
    fabricated success. The shipped deploy candidates (p8head_2999) carry only a
    short name, so this is the honest path."""
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    bare = ROOT / "out" / "p8head_2999.onnx"
    if not bare.exists():
        pytest.skip(f"bare onnx not present: {bare}")
    pv = rp.provenance_for_onnx(bare)
    assert pv.companion_meta == "absent"
    assert pv.task is None and pv.cfg_sha256_16 is None


def test_record_provenance_strip_and_parse():
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    assert rp.strip_timestamp("2026-11-07_22-12-33_p8head_030_4096x3000_resume2999") \
        == "p8head_030_4096x3000_resume2999"
    assert rp.parse_iteration("p8head_030_4096x3000_resume2999") == 2999
    assert rp.parse_iteration("p3head030_4096x2000_it1600") == 1600
    assert rp.parse_envxiter("hd1910_groundpick_4096x4000_1106_2216") == (4096, 4000)
    assert rp.parse_envxiter("2026-11-07_22-12-33_p8head_030_4096x3000_resume2999") \
        == (4096, 3000)


def test_inference_check_negative_control():
    """The output validator must catch every real failure mode (NaN/Inf, explode)
    and must NOT pass a broken output. Pure-Python, so this is provable on a clean
    checkout without onnxruntime/numpy — guarding the gate's logic, not just its
    wiring."""
    vi = _load("verify_policy_inference_test", HERE / "verify_policy_inference.py")
    check = vi.check_inference_output
    ok, reasons = check([0.1, -0.2, 0.05, 0.3, -0.1, 0.0, 0.2, -0.3,
                         0.15, 0.1, -0.05, 0.25, 0.0, -0.15])
    assert ok and not reasons
    ok, reasons = check([0.1, float("nan"), 0.2] + [0.0] * 11)
    assert (not ok) and any("NaN" in r for r in reasons)
    ok, reasons = check([float("inf")] * 14)
    assert (not ok) and any("Inf" in r for r in reasons)
    ok, reasons = check([1.0e9] * 14)
    assert (not ok) and any("explode" in r for r in reasons)
    # a degenerate constant is a WARN only -> still ok (no false FAIL)
    ok, reasons = check([0.0] * 14)
    assert ok and any("WARN" in r for r in reasons)
    ok, reasons = check([])
    assert not ok


def test_inference_selftest_runs():
    """verify_policy_inference.py --selftest exercises the negative-control logic
    with no heavy deps; must exit 0."""
    proc = subprocess.run(
        [sys.executable, str(HERE / "verify_policy_inference.py"), "--selftest"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]

