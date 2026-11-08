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


def test_conductor_verdict_surfaces_skips():
    """A SKIP means 'could not be checked', not a pass. The conductor must not
    print a plain PASS when a structural stage (e.g. contract, which needs the
    training stack) was skipped -- an operator would otherwise read green CI as
    'fully verified'. This guards the PASS* verdict branch."""
    pc = _load("pre_deploy_check_test", HERE / "pre_deploy_check.py")
    assert pc._verdict(False, []) == "PASS -- safe to load (all stages verified)"
    assert pc._verdict(True, []) == "FAIL -- do NOT load this policy"
    skipped = pc._verdict(False, ["contract", "inference"])
    assert skipped.startswith("PASS* -- loadable IF the skipped stage(s)")
    assert "contract" in skipped and "inference" in skipped


def test_conductor_selftest_runs():
    """The guards must self-validate with no real policy / no robot.

    Pass18: lean CI has no mjlab_microduck, so contract.selftest returns a
    genuine SKIP. That is only acceptable when the caller names it explicitly;
    the same run without the allow-list must be a FAIL (tested below). On a full
    training stack there must be NO PARTIAL at all -- otherwise a silently
    skipped guard would look like a pass again.
    """
    lean = importlib.util.find_spec("mjlab_microduck") is None
    cmd = [sys.executable, str(HERE / "pre_deploy_check.py"), "--selftest"]
    if lean:
        cmd += ["--selftest-allow-skip", "contract.selftest"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    if lean:
        assert "PARTIAL" in proc.stdout, proc.stdout[-2000:]
    else:
        assert "PARTIAL" not in proc.stdout, proc.stdout[-2000:]
        assert "PASS -- conductor + guards wired correctly" in proc.stdout


def test_conductor_argparse_usage_error_is_not_a_skip():
    """rc=2 means 'SKIP' ONLY for a genuinely unavailable side. argparse also
    exits 2 on a CLI usage error; swallowing that as SKIP hides a broken guard
    (Pass13-15 shipped exactly this: inference invoked with a positional onnx
    while the script expects --onnx, reported as 'onnxruntime absent')."""
    pc = _load("pre_deploy_check_usage_test", HERE / "pre_deploy_check.py")

    usage = ("usage: verify_policy_inference.py [-h] [--onnx ONNX]\n"
             "verify_policy_inference.py: error: unrecognized arguments: x.onnx")
    assert pc._is_argparse_usage_error(usage)

    # Negative control: a genuine dependency-missing SKIP must stay a SKIP.
    real_skip = ("== inference smoke ==\n  status: SKIP\n"
                 "  reason: missing dependency: onnxruntime\nVERDICT: SKIP")
    assert not pc._is_argparse_usage_error(real_skip)
    assert pc._classify(2) == "SKIP"

    # Negative control 2: a bare 'usage:' without an argparse error line is
    # not enough -- otherwise any policy log mentioning 'usage' trips a FAIL.
    assert not pc._is_argparse_usage_error("the word usage: appears in a report")


def test_conductor_inference_stage_rejects_positional_onnx():
    """Feed the REAL guard the OLD (broken) invocation. It must come back FAIL,
    not SKIP. This is the negative control that proves the new detector fires
    on the exact bug that was shipped -- not just on a hand-written string."""
    pc = _load("pre_deploy_check_invoke_test", HERE / "pre_deploy_check.py")
    onnx = (ROOT / "logs/rsl_rl/microduck_velocity_hd1910/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999.onnx")
    if not onnx.exists():
        pytest.skip("real walk onnx not present in this checkout")
    r = pc._stage("inference", pc.INFERENCE, str(onnx),
                  "--expect-obs", "61", "--expect-act", "14")
    assert r.rc == 2, r.tail
    assert r.status == "FAIL", r.tail
    assert "GUARD INVOCATION BROKEN" in r.tail


def test_ci_verdict_cli_selftest_runs():
    """CLI-level regression: `--selftest` must work WITHOUT a report argument.
    Only testing check() left a green suite while the CI step actually failed
    at argparse. This guards the entry point the workflow really calls."""
    proc = subprocess.run(
        [sys.executable, str(HERE / "assert_ci_verdict.py"), "--selftest"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-1200:]
    assert "PASS -- negative-control logic wired correctly" in proc.stdout


def test_ci_verdict_assertion_negative_controls():
    """The CI assertion must reject the exact Pass13-15 failure mode: a report
    where inference is SKIP while CI installed onnxruntime."""
    ac = _load("assert_ci_verdict_test", HERE / "assert_ci_verdict.py")
    good = {
        "verdict": "PASS*",
        "skipped_stages": ["contract"],
        "stages": [
            {"name": "contract", "status": "SKIP"},
            {"name": "bundle", "status": "PASS"},
            {"name": "numeric", "status": "PASS"},
            {"name": "inference", "status": "PASS"},
            {"name": "toml", "status": "PASS"},
        ],
    }
    assert ac.check(good) == []

    # Negative control 1: inference SKIP must be rejected.
    bad = json.loads(json.dumps(good))
    bad["stages"][3]["status"] = "SKIP"
    assert any("inference" in p for p in ac.check(bad))

    # Negative control 2: an extra unexpected skip must be rejected.
    bad2 = json.loads(json.dumps(good))
    bad2["stages"][2]["status"] = "SKIP"
    bad2["skipped_stages"] = ["contract", "numeric"]
    assert any("unexpected SKIP" in p for p in ac.check(bad2))

    # Negative control 3: FAIL verdict / empty stages must be rejected.
    bad3 = json.loads(json.dumps(good))
    bad3["verdict"] = "FAIL"
    assert any("FAIL" in p for p in ac.check(bad3))
    assert ac.check({"verdict": "PASS", "skipped_stages": [], "stages": []})


def test_ci_verdict_assertion_on_real_conductor_report(tmp_path):
    """Feed a REAL --json report from the conductor, then corrupt it and prove
    the assertion turns red. Uses the actual artifact, not a hand-built dict."""
    onnx = (ROOT / "logs/rsl_rl/microduck_velocity_hd1910/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999.onnx")
    if not onnx.exists():
        pytest.skip("real walk onnx not present in this checkout")
    report = tmp_path / "gate.json"
    proc = subprocess.run(
        [sys.executable, str(HERE / "pre_deploy_check.py"),
         "--onnx", str(onnx), "--toml", str(ROOT / "out/robotd_hd1910_mode0.toml"),
         "--expect-kp", "16", "--json", str(report)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-800:]
    data = json.loads(report.read_text(encoding="utf-8"))
    # In a full stack nothing is skipped -> plain PASS, which is also accepted.
    assert not ac_check(data), data

    # Corrupt: mark inference SKIP -> assertion must reject the real report.
    data["stages"] = [{"name": s["name"], "status": "SKIP" if s["name"] == "inference"
                       else s["status"]} for s in data["stages"]]
    data["skipped_stages"] = sorted(set(data["skipped_stages"] + ["inference"]))
    assert any("inference" in p for p in ac_check(data))


def ac_check(report):
    mod = _load("assert_ci_verdict_real_test", HERE / "assert_ci_verdict.py")
    return mod.check(report)


def test_conductor_inference_stage_uses_onnx_option():
    """The CORRECTED invocation must actually execute the graph and PASS when
    onnxruntime is installed (and be a genuine SKIP when it is not)."""
    pc = _load("pre_deploy_check_invoke_ok_test", HERE / "pre_deploy_check.py")
    onnx = (ROOT / "logs/rsl_rl/microduck_velocity_hd1910/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999/"
            "2026-11-07_22-12-33_p8head_030_4096x3000_resume2999.onnx")
    if not onnx.exists():
        pytest.skip("real walk onnx not present in this checkout")
    r = pc._stage("inference", pc.INFERENCE, "--onnx", str(onnx),
                  "--expect-obs", "61", "--expect-act", "14")
    # With onnxruntime present it must be a real PASS; absent -> honest SKIP.
    # What it must NEVER be is a FAIL (that would mean the arguments are wrong).
    assert r.status in ("PASS", "SKIP"), r.tail
    if r.status == "PASS":
        assert "VERDICT: PASS" in r.tail or "status: PASS" in r.tail, r.tail


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


def test_record_provenance_absent_meta_is_honest(tmp_path):
    """An onnx with NO companion meta must be reported as 'absent', never a
    fabricated success. The shipped deploy candidates (p8head_2999) carry only a
    short name, so this is the honest path.

    Pass18: this used to skip whenever ``out/p8head_2999.onnx`` (a gitignored
    local sample) was absent, i.e. on EVERY clean CI checkout. provenance_for_onnx
    only reads the file stem and looks for companions under OUT, so a synthetic
    bare path exercises exactly the same logic with no uncommitted asset.
    """
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    bare = tmp_path / "p8head_2999.onnx"
    bare.write_bytes(b"synthetic bare policy; provenance reads only the stem")
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


# ── Pass14: 推理闸门强制 robotd 契约(输入名obs / 输出宽度) + provenance 完整性 ──

def test_inference_validate_outputs_width_mismatch():
    """A metadata/export skew like the official 28-vs-14 standup bug (action
    width != expect_act) must be a hard FAIL, not silently ignored."""
    vi = _load("verify_policy_inference_test", HERE / "verify_policy_inference.py")
    ok, reasons = vi.validate_outputs([0.1] * 13, expect_act=14)
    assert (not ok) and any("width" in r for r in reasons)
    # correct width passes
    ok, _ = vi.validate_outputs([0.1] * 14, expect_act=14)
    assert ok
    ok, _ = vi.validate_outputs([[0.1] * 14], expect_act=14)  # nested batch form
    assert ok


def test_inference_validate_inputs_obs_contract():
    """The HD-1910 robotd hardcodes the input tensor name 'obs' and never reads
    the ONNX manifest, so any other input name is a guaranteed load failure and
    must be a hard FAIL here (not advisory)."""
    vi = _load("verify_policy_inference_test", HERE / "verify_policy_inference.py")
    ok, _ = vi.validate_inputs(["obs"])
    assert ok
    ok, reasons = vi.validate_inputs(["observation", "states"])
    assert (not ok) and any("obs" in r for r in reasons)
    ok, reasons = vi.validate_inputs([])
    assert not ok


def test_record_provenance_verify_consistent():
    """The committed bundle's provenance must match the onnx companion meta on
    disk — no field drift. Pure stdlib, CI-safe (guards against 'onnx changed
    but provenance never refreshed')."""
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    bundle = ROOT / "out" / "hd1910_kp8_deploy_bundle.json"
    if not bundle.exists():
        pytest.skip(f"bundle not present: {bundle}")
    rc, msgs = rp.verify_bundle(bundle)
    assert rc == 0, msgs


def test_record_provenance_verify_detects_drift(tmp_path):
    """verify_bundle must FAIL (rc=1) when a stored artifact field disagrees
    with a fresh recomputation, or when a recorded onnx is missing on disk."""
    rp = _load("record_provenance_test", HERE / "record_provenance.py")
    bundle = ROOT / "out" / "hd1910_kp8_deploy_bundle.json"
    if not bundle.exists():
        pytest.skip(f"bundle not present: {bundle}")
    data = json.loads(bundle.read_text(encoding="utf-8"))
    pa = data["provenance"]["per_artifact"]
    key = next(iter(pa))

    # 1) corrupt a stable artifact field -> DRIFT
    bad = json.loads(json.dumps(data))
    bad["provenance"]["per_artifact"][key]["cfg_sha256_16"] = "deadbeefdeadbeef"
    p1 = tmp_path / "bad1.json"
    p1.write_text(json.dumps(bad), encoding="utf-8")
    rc, msgs = rp.verify_bundle(p1)
    assert rc == 1 and any("DRIFT" in m for m in msgs)

    # 2) a recorded onnx that does not exist on disk -> DRIFT
    bad2 = json.loads(json.dumps(data))
    bad2["provenance"]["per_artifact"]["logs/rsl_rl/nonexistent/onnx.onnx"] = {
        "task": "x", "plant_name": "x", "cfg_sha256_16": "0" * 16,
        "mdp_sha256_16": "0" * 16, "export_iteration": 1,
    }
    p2 = tmp_path / "bad2.json"
    p2.write_text(json.dumps(bad2), encoding="utf-8")
    rc, msgs = rp.verify_bundle(p2)
    assert rc == 1 and any("DRIFT" in m for m in msgs)


def test_verification_boundary_negative_controls(tmp_path):
    """A green deploy gate must not be quietly upgradeable to a hardware
    sign-off. Every attempt to flip/remove the boundary has to turn the
    verification red. Cross-checks the REAL installation.json, not a mock."""
    rp = _load("record_provenance_boundary_test", HERE / "record_provenance.py")
    bundle = ROOT / "out" / "hd1910_kp8_deploy_bundle.json"
    if not bundle.exists() or not rp._CALIBRATION_SOURCE.is_file():  # noqa: SLF001
        pytest.skip("bundle or authoritative installation.json not present")
    data = json.loads(bundle.read_text(encoding="utf-8"))
    assert rp.verify_boundary(data)[0] == 0

    # Negative control 1: claim calibration verified while the authoritative
    # file still says false -> DRIFT.
    bad = json.loads(json.dumps(data))
    bad["verification_boundary"]["calibration_verified"] = True
    rc, msgs = rp.verify_boundary(bad)
    assert rc == 1 and any("BOUNDARY DRIFT" in m for m in msgs)

    # Negative control 2: claim hardware was tested while calibration is
    # unverified -> CONTRADICTION (two sources disagree).
    bad2 = json.loads(json.dumps(data))
    bad2["verification_boundary"]["hardware_tested"] = True
    rc, msgs = rp.verify_boundary(bad2)
    assert rc == 1 and any("CONTRADICTION" in m for m in msgs)

    # Negative control 3: enable motion without verified calibration + IMU.
    bad3 = json.loads(json.dumps(data))
    bad3["verification_boundary"]["motion_permitted"] = True
    rc, msgs = rp.verify_boundary(bad3)
    assert rc == 1 and any("CONTRADICTION" in m for m in msgs)

    # Negative control 4: delete the whole boundary block / empty limits.
    bad4 = json.loads(json.dumps(data))
    del bad4["verification_boundary"]
    assert rp.verify_boundary(bad4)[0] == 1
    bad5 = json.loads(json.dumps(data))
    bad5["verification_boundary"]["limits"] = []
    assert rp.verify_boundary(bad5)[0] == 1

    # ...and the full --verify path must reject a tampered bundle too.
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(bad), encoding="utf-8")
    rc, msgs = rp.verify_bundle(tampered)
    assert rc == 1 and any("BOUNDARY DRIFT" in m for m in msgs)


# ── Pass17: CI readiness probe (the "clean checkout" precondition) ─────────


def test_clean_checkout_probe_cli_selftest_runs():
    """CLI-level: `--selftest` must run with no checkout/report argument.

    Pass16 shipped assert_ci_verdict.py with `report` as a required positional,
    so its --selftest died at argparse while all 50 unit tests stayed green
    (they only called check()). Never add a CLI tool without testing its CLI.
    """
    proc = subprocess.run(
        [sys.executable, str(HERE / "assert_clean_checkout.py"), "--selftest"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout[-1200:] + proc.stderr[-1200:]
    assert "readiness logic wired correctly" in proc.stdout


def test_clean_checkout_assess_negative_controls():
    """A checkout missing ANY input must not be reported as runnable."""
    acc = _load("assert_clean_checkout_test", HERE / "assert_clean_checkout.py")
    good = [{"name": "walk", "rel_path": "x/walk.onnx", "exists": True,
             "tracked": True, "bytes_match": True, "sha_match": True}]
    ups = [{"rel_path": ".upstream/imu.rs", "exists": True}]

    assert acc.assess(good, ups, True)["ci_full_gate_possible"] is True
    # The exact Pass13-16 trap: the file exists on the developer's disk but a
    # fresh checkout never receives it because it is gitignored.
    untracked = acc.assess([dict(good[0], tracked=False)], ups, True)
    assert untracked["ci_full_gate_possible"] is False
    assert any("NOT tracked" in p for p in untracked["problems"])
    assert acc.assess([dict(good[0], exists=False)], ups, True)["ci_full_gate_possible"] is False
    assert acc.assess([dict(good[0], sha_match=False)], ups, True)["ci_full_gate_possible"] is False
    assert acc.assess(good, [dict(ups[0], exists=False)], True)["ci_full_gate_possible"] is False
    assert acc.assess(good, ups, False)["ci_full_gate_possible"] is False
    assert acc.assess([], [], True)["ci_full_gate_possible"] is False


def test_clean_checkout_probe_reads_bundle_and_flags_untracked(tmp_path):
    """probe() must verify size + sha AND tracking, not mere existence."""
    import hashlib
    acc = _load("assert_clean_checkout_probe_test", HERE / "assert_clean_checkout.py")
    payload = b"fake onnx graph"
    f = tmp_path / "policy.onnx"
    f.write_bytes(payload)
    bundle = {"artifacts": {"walk": {
        "rel_path": "policy.onnx",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }}}
    bp = tmp_path / "bundle.json"
    bp.write_text(json.dumps(bundle), encoding="utf-8")

    report = acc.probe(tmp_path, bp)
    a = report["artifacts"][0]
    assert a["exists"] and a["bytes_match"] and a["sha_match"]
    # tmp_path is not a git checkout of this repo, so nothing here is tracked.
    assert report["ci_full_gate_possible"] is False
    assert "artifacts" in report and "upstream_sources" in report
    assert "problems" in report and "reason" in report


def test_imu_chain_guard_runs_in_full_stack():
    """The IMU decode-chain guard must actually EXECUTE somewhere automatic.

    Pass17 found verify_imu_chain.py (13 checks + 15 negative controls, covering
    the first six observation slots) was only *mentioned* in README/checklist --
    never called by the conductor, CI, or pytest. The `imu_median = false`
    deployment decision rests on it, so it needs an automatic execution point.

    It needs scipy + mjlab_microduck + the .upstream Rust source; a lean CI
    checkout has none of those, so a skip there is HONEST and must be surfaced,
    never mistaken for a pass. Run pytest with the full .venv-mjlab before ship.
    """
    if (importlib.util.find_spec("scipy") is None
            or importlib.util.find_spec("mjlab_microduck") is None):
        pytest.skip("scipy / mjlab_microduck absent: IMU-chain guard needs the "
                    "full training stack (run with .venv-mjlab before shipping)")
    imu_rs = ROOT / ".upstream" / "DuckBuddy-main" / "duck-control" / "src" / "imu.rs"
    if not imu_rs.is_file():
        pytest.skip(".upstream Rust source absent (gitignored in a clean checkout)")

    main = subprocess.run(
        [sys.executable, str(HERE / "verify_imu_chain.py")],
        capture_output=True, text=True,
    )
    assert main.returncode == 0, main.stdout[-1500:] + main.stderr[-1500:]
    assert "all pass" in main.stdout
    assert "trained window 0-1 steps = 0-20 ms" in main.stdout

    selftest = subprocess.run(
        [sys.executable, str(HERE / "verify_imu_chain.py"), "--selftest"],
        capture_output=True, text=True,
    )
    assert selftest.returncode == 0, selftest.stdout[-1500:] + selftest.stderr[-1500:]
    assert "all consistent" in selftest.stdout


def test_verify_bundle_now_checks_artifact_hashes():
    """Pass17: the bundle's own artifacts[] sha256/bytes must be verified.

    Pass12 edited robotd_hd1910_mode0.toml (clarifying a comment) but the
    bundle kept the OLD fingerprint (9007 B / b71a5907) for four audit passes,
    because verify_bundle() only diffed provenance.per_artifact and the
    verification_boundary. A single source of truth whose hashes are never
    checked is decoration. These negative controls prove the new guard bites.
    """
    rp = _load("record_provenance_hash_test", HERE / "record_provenance.py")
    data = json.loads((ROOT / "out" / "hd1910_kp8_deploy_bundle.json")
                      .read_text(encoding="utf-8"))

    # Clean: after the Pass17 refresh, every stored hash matches disk.
    rc, msgs = rp.verify_artifact_hashes(data)
    assert rc == 0, msgs
    assert any("OK artifacts sha256/bytes match" in m for m in msgs)

    # Negative control 1: a same-length sha edit must be caught.
    bad = json.loads(json.dumps(data))
    bad["artifacts"]["robotd_toml"]["sha256"] = "0" * 64
    rc, msgs = rp.verify_artifact_hashes(bad)
    assert rc == 1 and any("DRIFT artifact robotd_toml" in m for m in msgs)

    # Negative control 2: a size-only edit must be caught independently.
    bad2 = json.loads(json.dumps(data))
    bad2["artifacts"]["robotd_toml"]["bytes"] = 1
    rc2, msgs2 = rp.verify_artifact_hashes(bad2)
    assert rc2 == 1 and any("bytes stored=1" in m for m in msgs2)

    # Negative control 3: deleting the whole block must not look like a pass.
    rc3, msgs3 = rp.verify_artifact_hashes({})
    assert rc3 == 1 and any("no 'artifacts'" in m for m in msgs3)

    # ...and the full --verify path must reject a tampered bundle too.
    tmp = pathlib.Path(__file__).parent / "_hash_probe_bundle.json"
    try:
        tmp.write_text(json.dumps(bad), encoding="utf-8")
        rc4, msgs4 = rp.verify_bundle(tmp)
        assert rc4 == 1 and any("DRIFT artifact robotd_toml" in m for m in msgs4)
    finally:
        tmp.unlink(missing_ok=True)


# ── Pass18: lean-CI boundaries and the committed-input closure ────────────

def test_conductor_selftest_skip_requires_explicit_allowlist():
    """A skipped guard selftest must be a FAIL unless the caller names it.

    Negative controls in both directions: an unlisted SKIP is red, a whitelisted
    SKIP is allowed (but PARTIAL), an unknown allow-list entry is rejected, and
    a real FAIL stays red even when whitelisted.
    """
    pc = _load("pc_selftest_allow_test", HERE / "pre_deploy_check.py")
    real_stage = pc._stage

    def one_skip(name, script, *args):
        status = "SKIP" if name == "contract.selftest" else "PASS"
        return pc.StageResult(name, 2 if status == "SKIP" else 0, status, "")

    try:
        pc._stage = one_skip
        assert pc.run_selftest() == 1
        assert pc.run_selftest(("contract.selftest",)) == 0
        assert pc.run_selftest(("typo.selftest",)) == 2

        pc._stage = lambda name, script, *args: pc.StageResult(
            name, 1, "FAIL", "deliberately broken")
        assert pc.run_selftest(("contract.selftest",)) == 1
    finally:
        pc._stage = real_stage


def test_conductor_selftest_allowlist_cli():
    """CLI level: the new option must actually work when invoked (Pass16 lesson)."""
    base = [sys.executable, str(HERE / "pre_deploy_check.py"), "--selftest"]
    ok = subprocess.run(base + ["--selftest-allow-skip", "contract.selftest"],
                         capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout[-1500:] + ok.stderr[-1500:]
    bad = subprocess.run(base + ["--selftest-allow-skip", "typo.selftest"],
                          capture_output=True, text=True)
    assert bad.returncode == 2
    assert "no such guard" in (bad.stdout + bad.stderr)


def test_clean_checkout_layered_verdicts():
    """Scope (4/5 stages) and full (5/5) must not collapse into one boolean."""
    acc = _load("acc_layered_test", HERE / "assert_clean_checkout.py")
    art = [{"name": "walk", "rel_path": "x/walk.onnx", "exists": True,
            "tracked": True, "bytes_match": True, "sha_match": True}]
    ups = [{"rel_path": f".upstream/{i}", "exists": True} for i in range(9)]

    full = acc.assess(art, ups, True)
    lean = acc.assess(art, ups, False)
    assert full["ci_scope_gate_possible"] and full["ci_full_gate_possible"]
    assert lean["ci_scope_gate_possible"] and not lean["ci_full_gate_possible"]
    assert lean["scope_problems"] == []
    assert any("training stack" in p for p in lean["problems"])

    missing = acc.assess(art, [dict(ups[3], exists=False)] + ups[:3] + ups[4:], False)
    assert not missing["ci_scope_gate_possible"]


def test_clean_checkout_cli_strict_and_strict_full():
    """--strict is the CI gate; --strict-full must additionally turn red
    when the training stack is absent (an honest negative control)."""
    lean = importlib.util.find_spec("mjlab_microduck") is None
    base = [sys.executable, str(HERE / "assert_clean_checkout.py")]
    strict = subprocess.run(base + ["--strict"], cwd=ROOT,
                            capture_output=True, text=True)
    assert strict.returncode == 0, strict.stdout[-1500:] + strict.stderr[-1500:]
    assert "ci_scope_gate_possible = true" in strict.stdout

    strict_full = subprocess.run(base + ["--strict-full"], cwd=ROOT,
                                 capture_output=True, text=True)
    assert strict_full.returncode == (1 if lean else 0), \
        strict_full.stdout[-1500:] + strict_full.stderr[-1500:]


def test_upstream_closure_feeds_bundle_contract():
    """The probe's source list is only useful if it really is the parser's
    closure. Positive: all 9 parse to a clean 61/14/15 contract. Negative:
    removing ONE source must make load_contract() report problems."""
    import shutil

    acc = _load("acc_closure_test", HERE / "assert_clean_checkout.py")
    vpb = _load("vpb_closure_test", HERE / "verify_policy_bundle.py")
    for rel in acc.UPSTREAM_SOURCES:
        assert (ROOT / rel).is_file(), f"committed contract source missing: {rel}"
    clean = vpb.load_contract()
    assert clean.problems == [], clean.problems
    assert (clean.obs_len, clean.action_len, len(clean.joint_names)) == (61, 14, 15)

    # Build a throwaway tree with exactly the same layout, minus one file.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        duck = base / "DuckBuddy-main"
        rl = base / "microduck_rl-develop"
        rels = []
        for rel in acc.UPSTREAM_SOURCES:
            prefix = ".upstream/DuckBuddy-main/"
            if rel.startswith(prefix):
                dst = duck / rel[len(prefix):]
            elif rel.startswith(".upstream/microduck_rl-develop/"):
                dst = rl / rel[len(".upstream/microduck_rl-develop/"):]
            else:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst)
            rels.append(dst)
        assert vpb.load_contract(duck=duck, rl=rl).problems == []
        (duck / "duck-control" / "src" / "policy.rs").unlink()
        broken = vpb.load_contract(duck=duck, rl=rl)
        assert broken.problems, "removing policy.rs must break contract parsing"


# ── Pass19: GitHub discovers workflows ONLY at <repo-root>/.github/workflows ──


def test_ci_workflow_is_at_repo_root():
    """Pass13-18 kept deploy-gate.yml under microduck-software/.github/ and
    never pushed it; the remote Actions API reported total_count=0. A workflow
    that GitHub never registers cannot guard anything, and CI cannot report
    its own absence -- so this is a LOCAL structural assertion."""
    repo = ROOT.parent
    wf = repo / ".github" / "workflows" / "deploy-gate.yml"
    assert wf.is_file(), f"CI workflow missing at repo root: {wf}"
    text = wf.read_text(encoding="utf-8")
    assert "on:" in text and "jobs:" in text, "root workflow has no triggers/jobs"
    assert "working-directory: microduck-software" in text, (
        "workflow moved to repo root must keep running inside microduck-software")
    # An orphan copy in a subdirectory would never be discovered and would
    # mislead the next person into editing the wrong file.
    orphan_dir = ROOT / ".github" / "workflows"
    orphans = (list(orphan_dir.glob("*.yml")) + list(orphan_dir.glob("*.yaml"))
               if orphan_dir.is_dir() else [])
    assert not orphans, f"orphan(never-discovered) workflows: {orphans}"


def test_workflow_placement_negative_controls():
    acc = _load("assert_clean_checkout_wf", HERE / "assert_clean_checkout.py")
    good = {"root_workflow_exists": True, "root_workflow_valid": True,
            "orphan_workflows": []}
    assert acc.workflow_problems(good) == []
    assert "NOT DISCOVERABLE" in " ".join(
        acc.workflow_problems(dict(good, root_workflow_exists=False)))
    assert "NOT USABLE" in " ".join(
        acc.workflow_problems(dict(good, root_workflow_valid=False)))
    assert "ORPHAN" in " ".join(acc.workflow_problems(
        dict(good, orphan_workflows=["microduck-software/.github/workflows/x.yml"])))


def test_workflow_probe_cli_detects_missing_root_workflow(tmp_path):
    """CLI-level control: --strict must go red when the root workflow is gone,
    and must clear that problem when it is restored. Tests the real entry
    point, not just workflow_problems()."""
    script = HERE / "assert_clean_checkout.py"
    fake_root = tmp_path / "microduck-software"
    (fake_root / "out").mkdir(parents=True)
    bundle = fake_root / "out" / "hd1910_kp8_deploy_bundle.json"
    bundle.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")
    report = fake_root / "out" / "readiness.json"

    def run():
        return subprocess.run(
            [sys.executable, str(script), "--root", str(fake_root),
             "--bundle", "out/hd1910_kp8_deploy_bundle.json",
             "--strict", "--json", str(report)],
            capture_output=True, text=True,
        )

    missing = run()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert missing.returncode == 1, missing.stdout + missing.stderr
    assert any("NOT DISCOVERABLE" in p for p in data["workflow_problems"]), data
    assert "NOT DISCOVERABLE" in missing.stdout

    wf = tmp_path / ".github" / "workflows" / "deploy-gate.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: x\non:\n  push:\njobs:\n  j:\n"
                  "    runs-on: ubuntu-latest\n"
                  "    defaults:\n      run:\n"
                  "        working-directory: microduck-software\n",
                  encoding="utf-8")
    restored = run()
    data2 = json.loads(report.read_text(encoding="utf-8"))
    assert data2["workflow"]["root_workflow_exists"] is True
    assert data2["workflow"]["root_workflow_valid"] is True
    assert data2["workflow_problems"] == [], data2["workflow_problems"]
    assert "NOT DISCOVERABLE" not in restored.stdout
    # Other problems (empty bundle) still keep --strict red: no false green.
    assert restored.returncode == 1


# ── Pass19: evidence fingerprints must be platform-independent ──


def test_bundle_artifact_hashes_match_committed_blobs():
    """The first real GitHub Actions run (Pass19) failed with
    "artifact robotd_toml: sha256 differs from bundle": the bundle had recorded
    the WINDOWS working-tree bytes (CRLF, 9520 B) while git stored and CI
    checked out the LF blob (9382 B). Evidence must be anchored to what a clean
    checkout receives, not to whichever EOL this machine happens to use.
    """
    import hashlib
    bundle = json.loads(
        (ROOT / "out" / "hd1910_kp8_deploy_bundle.json").read_text(encoding="utf-8"))
    repo = ROOT.parent
    assert bundle["artifacts"], "bundle has no artifacts to verify"
    for name, meta in bundle["artifacts"].items():
        rel = "microduck-software/" + meta["rel_path"]
        proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo,
                              capture_output=True, check=True)
        blob = proc.stdout
        assert len(blob) == meta["bytes"], (name, len(blob), meta["bytes"])
        assert hashlib.sha256(blob).hexdigest() == meta["sha256"], (
            f"{name}: bundle fingerprint is not the committed blob's")


def test_evidence_toml_is_lf_and_pinned_by_gitattributes(tmp_path):
    """Negative control for the EOL trap: a CRLF working tree must NOT hash to
    the committed fingerprint, and .gitattributes must pin this file to LF."""
    import hashlib
    path = ROOT / "out" / "robotd_hd1910_mode0.toml"
    raw = path.read_bytes()
    assert b"\r\n" not in raw, (
        "evidence TOML has CRLF in the working tree; core.autocrlf or a "
        "missing .gitattributes will make CI see different bytes")
    bundle = json.loads(
        (ROOT / "out" / "hd1910_kp8_deploy_bundle.json").read_text(encoding="utf-8"))
    meta = bundle["artifacts"]["robotd_toml"]
    assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
    # If the file were converted back to CRLF, both the size and the digest
    # would drift -- i.e. the invariant above really can detect the regression.
    crlf = raw.replace(b"\n", b"\r\n")
    assert len(crlf) != len(raw)
    assert hashlib.sha256(crlf).hexdigest() != meta["sha256"]

    attr = subprocess.run(
        ["git", "check-attr", "text", "eol", "--",
         "microduck-software/out/robotd_hd1910_mode0.toml"],
        cwd=ROOT.parent, capture_output=True, text=True, check=True)
    assert "eol: lf" in attr.stdout, attr.stdout

    # The probe must be able to NAME an EOL-only drift, and must NOT mislabel
    # real content tampering as one.
    acc = _load("assert_clean_checkout_eol", HERE / "assert_clean_checkout.py")
    crlf_file = tmp_path / "crlf.toml"
    crlf_file.write_bytes(crlf)
    assert acc._eol_only_drift(crlf_file, meta["sha256"]) is True
    tampered = tmp_path / "tampered.toml"
    tampered.write_bytes(crlf + b"\n[extra]\nx = 1\n")
    assert acc._eol_only_drift(tampered, meta["sha256"]) is False

