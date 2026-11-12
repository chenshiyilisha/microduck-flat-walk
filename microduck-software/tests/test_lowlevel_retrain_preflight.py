"""Preflight guards for the E4-5 low-level retrain (resampling window override).

WHY THIS EXISTS
---------------
E3 proved ``p8head_2999`` cannot track time-varying velocity commands
(``PATH_3``); the one software lever is retraining the low-level policy with the
twist command-resampling window narrowed from the task default ``(3.0, 8.0)`` to
``(0.1, 0.5)`` s. That override is declared on ``explore_heading.sh``'s
``EXTRA_ARGS`` and resolved by tyro inside ``train_heading_variant.py``.

Two silent-failure modes this suite exists to kill:

1. **Declared != effective.** A typo'd flag, a space in the tuple (``0.1 0.5``),
   or an old trainer that never records the field would let a 2.6-10.3 h GPU run
   train on the WRONG command distribution while its run name claims otherwise.
   ``resampling_gate.grade`` is the single authority reconciling the two; tests
   carry negative controls (mismatch / bad value / missing field must go RED).
2. **The wrapper's passthrough silently drops EXTRA_ARGS** (option B of the
   retrain plan). An end-to-end ``DRY=1`` local test proves the declaration
   actually reaches tyro and lands in heading_meta -- without a GPU run.

CI BOUNDARY
-----------
``resampling_gate.py`` and its CLI are pure stdlib: the logic + CLI tests run in
BOTH lean CI (``requirements.txt``) and local ``.venv-mjlab``. The two
end-to-end tests need mjlab/torch, so they ``importorskip("mjlab")`` and run only
locally. The tool source contains NO ``--selftest`` literal, so the gate
orchestrator's dynamic discovery does not mistake it for a gate (count stays 48).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
HD = TOOLS / "hd1910"
sys.path.insert(0, str(HD))
import resampling_gate as rg  # noqa: E402

PY = Path(sys.executable)
OPT = "--env.commands.twist.resampling-time-range 0.1,0.5"


# ── pure-function authority ──────────────────────────────────────────────────

def test_declared_window_three_forms():
    assert rg.declared_window(f"--task T {OPT}") == [0.1, 0.5]
    # tuple spelling with spaces + alternative underscore flag also parse
    assert rg.declared_window("--env.commands.twist.resampling_time_range (0.1, 0.5)") == [0.1, 0.5]
    assert rg.declared_window("--task T") is None  # no override = control run


def test_declared_window_only_takes_the_resampling_value():
    # other numeric overrides in the string must not contaminate the parse
    got = rg.declared_window(
        "--env.scene.num-envs 4096 --agent.max-iterations 3000 " + OPT
    )
    assert got == [0.1, 0.5]


def test_declared_window_malformed_raises():
    # a flag with too few numbers must raise, never silently become a window
    with pytest.raises(ValueError):
        rg.declared_window("--env.commands.twist.resampling-time-range 0.1")


def test_grade_override_match_passes():
    meta = {"resampling_time_range_effective": [0.1, 0.5]}
    g = rg.grade(meta, OPT)
    assert g["passed"] and g["verdict"] == "PASS_OVERRIDE_TOOK_EFFECT"


def test_grade_mismatch_negative_control():
    """The core negative control: declared 0.1,0.5 but effective stayed default."""
    meta = {"resampling_time_range_effective": [3.0, 8.0]}
    g = rg.grade(meta, OPT)
    assert not g["passed"] and g["verdict"] == "FAIL_MISMATCH"


def test_grade_missing_effective_negative_control():
    """An old trainer that never wrote the field must refuse, not pass."""
    g = rg.grade({}, OPT)
    assert not g["passed"] and g["verdict"] == "FAIL_MISSING_EFFECTIVE"


def test_grade_bad_effective_negative_control():
    for bad in ([0.1], "0.1,0.5", [8.0, 0.1], [float("nan"), 0.5]):
        g = rg.grade({"resampling_time_range_effective": bad}, OPT)
        assert not g["passed"] and g["verdict"] == "FAIL_BAD_EFFECTIVE", bad


def test_grade_no_override_still_records_default():
    """Control run: no declaration, but a valid recorded window is provenance."""
    g = rg.grade({"resampling_time_range_effective": [3.0, 8.0]}, "--task T")
    assert g["passed"] and g["verdict"] == "PASS_NO_OVERRIDE"
    # no declaration + no recorded field is still a failure (can't prove what ran)
    g2 = rg.grade({}, "--task T")
    assert not g2["passed"] and g2["verdict"] == "FAIL_MISSING_EFFECTIVE"


# ── CLI as a real subprocess (catches argparse drift, E2-style lesson) ───────

def _write_meta(tmp_path, effective, *, omit=False):
    p = tmp_path / "heading_meta_run.json"
    d = {"run": "run"}
    if not omit:
        d["resampling_time_range_effective"] = effective
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def test_cli_check_match_rc0(tmp_path):
    meta = _write_meta(tmp_path, [0.1, 0.5])
    r = subprocess.run([str(PY), str(HD / "resampling_gate.py"), "--check",
                        "--meta", meta, "--extra-args", OPT],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "PASS_OVERRIDE_TOOK_EFFECT" in r.stdout


def test_cli_check_mismatch_rc6(tmp_path):
    meta = _write_meta(tmp_path, [3.0, 8.0])
    r = subprocess.run([str(PY), str(HD / "resampling_gate.py"), "--check",
                        "--meta", meta, "--extra-args", OPT],
                       capture_output=True, text=True)
    assert r.returncode == 6
    assert "FAIL_MISMATCH" in r.stdout


def test_cli_check_bad_declared_rc6(tmp_path):
    meta = _write_meta(tmp_path, [0.1, 0.5])
    r = subprocess.run([str(PY), str(HD / "resampling_gate.py"), "--check",
                        "--meta", meta, "--extra-args",
                        "--env.commands.twist.resampling-time-range 0.1"],
                       capture_output=True, text=True)
    assert r.returncode == 6
    assert "malformed" in r.stderr


def test_cli_check_missing_meta_rc6(tmp_path):
    r = subprocess.run([str(PY), str(HD / "resampling_gate.py"), "--check",
                        "--meta", str(tmp_path / "nope.json"), "--extra-args", OPT],
                       capture_output=True, text=True)
    assert r.returncode == 6
    assert "not found" in r.stderr


# ── tool source hygiene: must not be auto-discovered as a gate ────────────────

def test_tool_source_does_not_declare_gate_flag_literal():
    """run_all_gates.discover() text-scans tools/**/*.py; this helper is NOT a
    gate, so its source must not carry the discovery literal (would perturb the
    48-gate count and demand a selftest CLI it does not implement)."""
    src = (HD / "resampling_gate.py").read_text(encoding="utf-8")
    assert "--" + "selftest" not in src


# ── end-to-end, local-only (needs mjlab/torch; skipped in lean CI) ───────────

def _venv_python() -> Path | None:
    cand = ROOT / ".venv-mjlab" / "Scripts" / "python.exe"
    return cand if cand.is_file() else None


@pytest.mark.skipif(importlib.util.find_spec("mjlab") is None,
                    reason="mjlab not installed (lean CI); E2E runs under .venv-mjlab")
def test_dryrun_records_resampling_effective(tmp_path):
    """The trainer must write the EFFECTIVE (tyro-resolved) window to its meta,
    for both the default and an override, and refuse a malformed value."""
    assert (vpy := _venv_python()) is not None
    env = {"MUJOCO_GL": "glfw"}
    import os
    runenv = dict(os.environ, **env)

    base = [str(vpy), str(TOOLS / "train_heading_variant.py"), "--task",
            "Mjlab-Velocity-Flat-MicroDuck", "--env.scene.num-envs", "64",
            "--agent.max-iterations", "5", "--dry-run"]

    # default
    name_d = "lhpreflight_default"
    r = subprocess.run(base + ["--agent.run-name", name_d], cwd=ROOT,
                       env=runenv, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    md = json.loads((ROOT / "out" / f"heading_meta_{name_d}.json").read_text(encoding="utf-8"))
    assert md["resampling_time_range_effective"] == [3.0, 8.0]
    assert "resampling_time_range (effective): [3.0, 8.0]" in r.stdout

    # override
    name_o = "lhpreflight_override"
    r = subprocess.run(base + ["--agent.run-name", name_o,
                               "--env.commands.twist.resampling-time-range", "0.1,0.5"],
                       cwd=ROOT, env=runenv, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    mo = json.loads((ROOT / "out" / f"heading_meta_{name_o}.json").read_text(encoding="utf-8"))
    assert mo["resampling_time_range_effective"] == [0.1, 0.5]

    # malformed (space-separated tuple) -> tyro refuses
    r = subprocess.run(base + ["--agent.run-name", "lhpreflight_bad",
                               "--env.commands.twist.resampling-time-range", "0.1", "0.5"],
                       cwd=ROOT, env=runenv, capture_output=True, text=True)
    assert r.returncode != 0

    for n in (name_d, name_o):
        (ROOT / "out" / f"heading_meta_{n}.json").unlink(missing_ok=True)


@pytest.mark.skipif(importlib.util.find_spec("mjlab") is None,
                    reason="mjlab not installed (lean CI); E2E runs under .venv-mjlab")
def test_wrapper_dryrun_forwards_extra_args(tmp_path):
    """Option B: explore_heading.sh DRY=1 must forward EXTRA_ARGS to tyro and
    reconcile declared vs effective via resampling_gate -- without training."""
    import os
    assert (vpy := _venv_python()) is not None
    name = "lhpreflight_wrap"
    runenv = dict(os.environ, MUJOCO_GL="glfw")
    r = subprocess.run(["bash", "tools/hd1910/explore_heading.sh", name], cwd=ROOT,
                       env=dict(runenv, DRY="1", PLANT="p8", ENVS="64", ITERS="5",
                                HEADING_STAGE_ITERS="0,1,2,3", EXTRA_ARGS=OPT),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1200:] + r.stderr[-400:]
    assert "DRY ok" in r.stdout
    # wrapper records the DECLARATION in runmeta...
    rm = json.loads((ROOT / "out" / f"runmeta_{name}.json").read_text(encoding="utf-8"))
    assert rm["extra_args"] == OPT
    # ...and the trainer writes the EFFECTIVE value to heading_meta
    hm = json.loads((ROOT / "out" / f"heading_meta_dryrun_{name}.json").read_text(encoding="utf-8"))
    assert hm["resampling_time_range_effective"] == [0.1, 0.5]
    assert rg.grade(hm, OPT)["passed"]

    for f in (f"runmeta_{name}.json", f"plant_{name}.json",
              f"heading_meta_dryrun_{name}.json"):
        (ROOT / "out" / f).unlink(missing_ok=True)
