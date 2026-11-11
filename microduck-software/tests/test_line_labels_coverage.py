"""Regression tests for B4: every --selftest tool has a line label.

The coverage gap is derived from the SAME function run_all_gates.py calls
(line_contract.unlabelled_tools); no hand-copied list of 20 paths here.
Negative controls prove that a future unlabelled tool, a stale risk token,
a cross-line sign-off, or a heavy tool mislabelled as a CI guard all turn red.
"""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, filename: str):
    p = HERE / filename
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lc = _load("line_contract_coverage_test", "line_contract.py")
cm = _load("ci_meta_targets_coverage_test", "ci_meta_targets.py")
dc = _load("check_deploy_chain_coverage_test", "check_deploy_chain.py")

TOOLS = ROOT / "tools"


def test_coverage_gap_is_zero_on_real_tools_tree():
    labels = lc.load()
    assert lc.unlabelled_tools(labels, TOOLS) == []
    assert not lc.validate(labels)


def test_every_label_points_at_a_real_file_and_a_real_risk_token():
    labels = lc.load()
    for t in labels["tools"]:
        rel = t["path"]
        src_path = ROOT / rel
        assert src_path.is_file(), rel
        assert t.get("evidence"), rel
        assert t["line"] in (set(labels["lines"])
                             | set(labels["non_line_labels"])), rel
        src = src_path.read_text(encoding="utf-8", errors="replace")
        for tok in t.get("risk_tokens") or []:
            assert tok in src, (rel, tok)


def test_b4_new_labels_are_all_registered():
    """The 20 B4 entries must exist; count is derived, not hardcoded twice."""
    labels = lc.load()
    new = [t for t in labels["tools"]
           if (t.get("evidence") or "").startswith("B4 补登记")]
    assert len(new) == 20
    assert {t["line"] for t in new} == {"TRAINING", "META_GUARD", "BENCH", "L2_BGEN"}
    # heavy-dependency tools must NOT be META_GUARD (lean CI has no deps)
    heavy = {"tools/hd1910/verify_policy_inference.py",
             "tools/hd1910/check_backlash_task.py",
             "tools/hd1910/policy_numeric_gate.py"}
    assert all(next(t for t in labels["tools"] if t["path"] == h)["line"] != "META_GUARD"
               for h in heavy)


def test_negative_control_new_unlabelled_tool_is_detected(tmp_path, monkeypatch):
    labels = lc.load()
    # unlabelled_tools() computes paths relative to SOFTWARE; point it at the
    # temp tree so this is a real CLI-style discovery, not a mocked return.
    monkeypatch.setattr(lc, "SOFTWARE", tmp_path)
    fake = tmp_path / "tools" / "ghost_guard.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("def main():\n    print('--selftest')\n", encoding="utf-8")
    gap = lc.unlabelled_tools(labels, tmp_path / "tools")
    assert "tools/ghost_guard.py" in gap


def test_negative_control_removing_one_label_reopens_the_gap():
    labels = lc.load()
    bad = copy.deepcopy(labels)
    victim = bad["tools"].pop(0)["path"]
    gap = lc.unlabelled_tools(bad, TOOLS)
    assert victim in gap


def test_negative_control_stale_risk_token_turns_red():
    labels = lc.load()
    bad = copy.deepcopy(labels)
    next(t for t in bad["tools"]
         if t["path"] == "tools/hd1910/servo_probe/probe_ch343_baud.py")["risk_tokens"].append(
        "THIS_TOKEN_DOES_NOT_EXIST_9f3a")
    assert any("stale risk token" in x for x in lc.validate(bad))


def test_negative_control_training_tool_never_looks_like_signoff():
    labels = lc.load()
    train = next(t["path"] for t in labels["tools"] if t["line"] == "TRAINING")
    # Pre-existing contract: non-hardware lines may self-test but their verdict
    # must carry NOT_SIGNOFF. Callers have to read the returned prefix.
    verdict = lc.assert_for_line(labels, train, "L1_RADXA_MIRROR")
    assert verdict.startswith("TRAINING_OK_NOT_SIGNOFF")
    assert not verdict.startswith("LINE_OK")
    assert lc.assert_for_line(labels, train, "TRAINING").startswith(
        "TRAINING_OK_NOT_SIGNOFF")
    relabel = copy.deepcopy(labels)
    next(t for t in relabel["tools"] if t["path"] == train)["line"] = "L1_RADXA_MIRROR"
    assert lc.assert_for_line(relabel, train, "L1_RADXA_MIRROR").startswith("LINE_OK")
    bad = copy.deepcopy(labels)
    bad["non_line_labels"].pop("TRAINING", None)
    assert any("unknown line label" in x
               for x in lc.validate(bad, with_sources=False))


def test_negative_control_heavy_tool_mislabelled_as_ci_guard_turns_red():
    labels = lc.load()
    bad = copy.deepcopy(labels)
    next(t for t in bad["tools"]
         if t["path"] == "tools/hd1910/verify_policy_inference.py")["line"] = "META_GUARD"
    _, problems, _ = cm.derive(bad)
    assert any("not stdlib-only" in x for x in problems)


def test_deploy_chain_valid_lines_are_derived_from_labels():
    labels = lc.load()
    data = dc.load_json(dc.DEFAULT_CONTRACT)
    assert "TRAINING" in dc.known_lines(labels)
    assert not dc.validate(data, labels)
    drop = copy.deepcopy(labels)
    drop["lines"].pop("L2_BGEN", None)
    assert any("unknown line" in x for x in dc.validate(data, drop))
