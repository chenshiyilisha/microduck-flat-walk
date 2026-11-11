"""Regression tests for the A3 unified gate (real CLI runs, no silent SKIP).

CPU-only, stdlib-only, no robot. Full 38-stage --check is intentionally NOT
in the unit suite (it takes ~40 s); this file tests the classifier, the
injected fixtures, and that a broken injected tool turns the gate RED.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_run_all_gates.py -q
    .venv-mjlab/Scripts/python.exe tools/hd1910/run_all_gates.py --check
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
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


gates = _load("run_all_gates_test", HERE / "run_all_gates.py")


def test_classifier_never_calls_a_skip_a_pass():
    c = gates.classify
    assert c(0, "selftest: 3/3 passed")[0] == "PASS"
    assert c(1, "selftest: 1 check FAILED")[0] == "FAIL"
    assert c(2, "usage: x.py [-h]\nerror: unrecognized arguments")[0] == "FAIL"
    assert "GUARD INVOCATION BROKEN" in c(2, "usage: x.py [-h]")[1]
    assert c(0, "SKIP: dependency absent")[0] == "SUSPECT_SKIP"
    assert c(0, "self-test: PARTIAL -- 1 guard skipped")[0] == "SUSPECT_SKIP"
    # Negative control: turning strict off lets rc=2 through as a SKIP.
    assert c(2, "usage: x.py [-h]", strict=False)[0] == "SKIP"
    # Negative control for the negative control: merely MENTIONING a status
    # word in a test name must not be read as the guard's verdict.
    assert c(0, "negative control mentions SKIP and NOT_SHIPPABLE\n"
                "self-test: PASS -- ok")[0] == "PASS"


def test_discovery_finds_the_real_tools():
    found = gates.discover(ROOT / "tools")
    assert len(found) >= 30
    assert any(f.name == "pre_deploy_check.py" for f in found)
    assert any(f.name == "run_all_gates.py" for f in found)


def test_cli_selftest_and_list_really_run():
    selftest = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"), "--selftest"],
                              cwd=str(ROOT), capture_output=True, text=True)
    assert selftest.returncode == 0, selftest.stdout + selftest.stderr
    # Do not hardcode the count: the project already got bitten once by a
    # hardcoded check count drifting away from the real number of checks.
    m = re.search(r"(\d+)/(\d+) passed", selftest.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(1)) >= 12, selftest.stdout

    listing = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"), "--list"],
                             cwd=str(ROOT), capture_output=True, text=True)
    assert listing.returncode == 0
    assert "discovered --selftest tools" in listing.stdout
    assert "conductor guards" in listing.stdout


def test_injected_broken_tool_turns_the_gate_red():
    """A rc=2 argparse guard must make --check FAIL, never a quiet SKIP."""
    with tempfile.TemporaryDirectory(prefix="md_gates_test_") as td:
        root = pathlib.Path(td)
        (root / "green.py").write_text("# --selftest\nprint('selftest: 3/3 passed')\n",
                                       encoding="utf-8")
        (root / "broken.py").write_text(
            "# --selftest\nimport sys\nprint('usage: broken.py [-h]', file=sys.stderr)\n"
            "print('error: unrecognized arguments', file=sys.stderr)\nsys.exit(2)\n",
            encoding="utf-8")
        proc = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"),
                               "--check", "--tools-dir", str(root), "--json"],
                              cwd=str(ROOT), capture_output=True, text=True)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        rep = json.loads(proc.stdout)
        assert rep["verdict"] == "FAILED"
        assert rep["live_hardware_accessed"] is False
        stages = {t["tool"]: t for t in rep["tool_stages"]}
        assert stages["green.py"]["status"] == "PASS"
        assert stages["broken.py"]["status"] == "FAIL"
        assert "GUARD INVOCATION BROKEN" in stages["broken.py"]["detail"]

        # Negative control: a green-only fixture must be ALL_PASS.
        (root / "broken.py").unlink()
        ok = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"),
                             "--check", "--tools-dir", str(root), "--json"],
                            cwd=str(ROOT), capture_output=True, text=True)
        assert ok.returncode == 0
        assert json.loads(ok.stdout)["verdict"] == "ALL_PASS"


def test_interpreter_is_explicit_and_empty_discovery_is_red():
    """Pre-commit review findings (2026-11-11).

    (1) PY = sys.executable, so a wrong interpreter makes 10 guards rc=1.
        That red run must be EXPLAINED, not misread as broken guards.
    (2) build_report([]) used to say ALL_PASS -- a zero-evidence green run.
    """
    info = gates.interpreter_info()
    assert info["executable"] == sys.executable
    assert set(info["heavy_deps"]) == {"onnx", "onnxruntime"}
    assert info["child_guards_inherit"] == "sys.executable"
    assert info["heavy_deps_ok"] == all(info["heavy_deps"].values())
    # negative control: injected missing deps must flip the flag red
    assert gates.interpreter_info({"onnx": False, "onnxruntime": True})["heavy_deps_ok"] is False
    assert gates.interpreter_info({"onnx": True, "onnxruntime": False})["heavy_deps_ok"] is False
    # negative control: zero discovered stages is FAILED, never ALL_PASS
    assert gates.build_report([], [], [], False, info)["verdict"] == "FAILED"
    assert gates.build_report([{"status": "PASS"}], [], [], False, info)["verdict"] == "ALL_PASS"

    with tempfile.TemporaryDirectory(prefix="md_gates_interp_") as td:
        root = pathlib.Path(td)
        (root / "green.py").write_text("# --selftest\nprint('self-test: PASS')\n",
                                       encoding="utf-8")
        proc = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"),
                               "--check", "--tools-dir", str(root), "--json"],
                              cwd=str(ROOT), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rep = json.loads(proc.stdout)  # pure JSON: HINT must not leak into --json
        assert rep["verdict"] == "ALL_PASS"
        assert rep["interpreter"]["executable"] == sys.executable
        assert "heavy_deps_ok" in rep["interpreter"]

        # CLI negative control: an empty tools dir must NOT be a green run.
        empty = root / "empty"
        empty.mkdir()
        blank = subprocess.run([sys.executable, str(HERE / "run_all_gates.py"),
                                "--check", "--tools-dir", str(empty), "--json"],
                               cwd=str(ROOT), capture_output=True, text=True)
        assert blank.returncode == 1, blank.stdout + blank.stderr
        assert json.loads(blank.stdout)["verdict"] == "FAILED"
