"""Regression tests for B3: the lean-CI meta-guard target derivation.

The list is derived from line_labels.json, filtered by a real AST dependency
probe. A hand-written YAML list or a hard-coded count would silently rot.
"""
from __future__ import annotations

import copy
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


cm = _load("ci_meta_targets_test", HERE / "ci_meta_targets.py")


def test_derived_list_is_stdlib_only_and_non_empty():
    labels = cm.load()
    names, problems, detail = cm.derive(labels)
    assert not problems, problems
    assert len(names) >= 8
    assert cm.ORCHESTRATOR not in names
    assert all(d["has_selftest"] and not d["imports"]
               for d in detail.values() if d["exists"])
    assert set(names) == {pathlib.Path(k).name for k in detail
                          if pathlib.Path(k).name != cm.ORCHESTRATOR}


def test_tampered_labels_turn_red():
    labels = cm.load()

    def must_fail(mutate):
        bad = copy.deepcopy(labels)
        mutate(bad)
        _, problems, _ = cm.derive(bad)
        assert problems, "tampered label set was accepted"

    must_fail(lambda d: d["tools"].append(
        {"path": "tools/hd1910/ghost_guard.py", "line": cm.META_LINE}))
    must_fail(lambda d: d["tools"].append(
        {"path": "tools/hd1910/verify_policy_bundle.py", "line": cm.META_LINE}))
    must_fail(lambda d: d["non_line_labels"].pop(cm.META_LINE))
    must_fail(lambda d: [t.update({"line": "BENCH"}) for t in d["tools"]
                         if t.get("line") == cm.META_LINE])
    assert "numpy" in cm.third_party_imports(
        "import importlib\nx = import_module('numpy')\n")
    assert "<SYNTAX_ERROR>" in cm.third_party_imports("def (:\n")


def test_lean_deps_are_derived_not_snapshotted():
    deps = cm.lean_deps()
    assert "numpy" in deps and "torch" not in deps
    with tempfile.TemporaryDirectory(prefix="md_ci_deps_test_") as td:
        p = pathlib.Path(td) / "requirements.txt"
        p.write_text("# a comment\ntorch>=2.0\nnumpy\n", encoding="utf-8")
        changed = cm.lean_deps(p)
        assert "torch" in changed and changed != deps
        assert len(changed) == 2


def test_cli_names_sh_check_and_selftest():
    script = str(HERE / "ci_meta_targets.py")
    names, _, _ = cm.derive(cm.load())
    r = subprocess.run([sys.executable, script, "--names"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert [x for x in r.stdout.splitlines() if x.strip()] == names
    # A CR in a filename makes `for G in $(...)` fail on Windows with rc=2.
    raw = subprocess.run([sys.executable, script, "--names"],
                         cwd=str(ROOT), capture_output=True)
    assert b"\r" not in raw.stdout

    sh = subprocess.run([sys.executable, script, "--sh"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert sh.returncode == 0
    assert "META_GUARD_COUNT=%d" % len(names) in sh.stdout

    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert js.returncode == 0
    rep = json.loads(js.stdout)
    assert rep["structure_verdict"] == "PASS"
    assert rep["lean_ci_dependencies"] == cm.lean_deps()
    assert "POST-PUSH ADVISORY" in rep["ci_boundary"]

    st = subprocess.run([sys.executable, script, "--selftest"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr
    m = re.search(r"(\d+)/(\d+) passed", st.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 15, st.stdout


def test_workflow_runs_the_derived_list_and_keeps_the_boundary():
    wf = ROOT.parent / ".github" / "workflows" / "deploy-gate.yml"
    text = wf.read_text(encoding="utf-8")
    assert "ci_meta_targets.py --check" in text
    assert "ci_meta_targets.py --names" in text
    assert "run_all_gates.py --selftest" in text
    # The heavy full run must NOT be a CI step. Comments/echo May mention it;
    # a bare substring assertion would be bitten by our own explanatory text.
    assert not re.search(r"^\s*(?:-\s*)?run:.*run_all_gates\.py --check", text, re.M)
    assert "POST-PUSH ADVISORY" in text
    assert "MERGE GATE" in text
