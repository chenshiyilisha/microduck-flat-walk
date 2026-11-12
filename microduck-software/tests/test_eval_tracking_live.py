"""Instrument calibration for ``tools/eval_tracking_live.py``.

WHY THIS EXISTS
---------------
The live frontend grades a REAL-ROBOT tracking recording with E3's judgement
(``eval_tracking``). Its verdict will be weighed at B1 ``BA-X-4`` when the board
is up. Before that, we must prove two things with no hardware:

1. **ONE judgement, not two.** ``eval_tracking_live`` must import the SAME pure
   functions as the sim runner (``grade_period`` / ``baseline_healthy`` /
   ``_axis_report`` / ``classify_sweep``). A second drifting copy would let the
   live grade disagree with the sim grade on identical numbers -- the exact class
   of silent bug this project keeps finding. Tests assert object identity.
2. **The live-only integrity check actually catches a bad recording.** A flat
   command, a flat response, an anti-phase response, too few samples -- each must
   produce ``invalid``, never a false ``usable``.

CI BOUNDARY: torch is not in the lean CI deps, so ``importorskip("torch")``
SKIPS this module in CI and RUNS locally under ``.venv-mjlab``. This file has NO
``--selftest`` CLI flag and does not put that literal in the tool source, so the
gate orchestrator's dynamic discovery does not mistake the tool for a gate.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import eval_tracking as et  # noqa: E402
import eval_tracking_live as live  # noqa: E402

DT = live.DT_DEFAULT
PY = Path(sys.executable)


def _sine(n, period_steps, amp=0.10, base=0.30):
    return [base + amp * math.sin(2 * math.pi * i / period_steps) for i in range(n)]


def _rec(period, cmd, meas, *, n=300, fell=False, trials=None, amp_vx=0.10):
    return {"period_s": period, "waveform": "sine", "dt": DT,
            "base": {"vx": 0.30}, "amp": {"vx": amp_vx},
            "meta": {"source": "live", "live_hardware_accessed": False},
            "cmd_vx": cmd, "meas_vx": meas, "fell": fell,
            "upright": [0.99] * len(cmd), **({"trials": trials} if trials else {})}


# --------------------------------------------------------- one judgement, not two


class TestSharedJudgementIdentity:
    """The live grade and the sim grade must be the SAME function objects."""

    @pytest.mark.parametrize("name", [
        "grade_period", "baseline_healthy", "_axis_report",
        "aggregate_axis", "classify_sweep",
    ])
    def test_imports_the_sim_function_object(self, name):
        assert getattr(live, name) is getattr(et, name), (
            f"{name} drifted: live has its own copy instead of importing E3's")


# ------------------------------------------------------------- grade_period purity


class TestGradePeriodPure:
    def test_healthy_follower_is_usable(self):
        g = et.grade_period(nrmse=0.10, terminated_frac=0.0, upright_mean=0.99,
                            cmd_vx_min=0.20, survivors=8, num_envs=8, lag_s=0.02,
                            period=1.0, vx_base=0.30, waveform_injected_ok=True)
        assert g["verdict"] == "usable"
        assert all(v is True for v in g["gates"].values())

    @pytest.mark.parametrize("nrmse,expected", [
        (0.30, "usable"), (0.55, "marginal"), (0.95, "fail"),
    ])
    def test_verdict_bands_match_shared_thresholds(self, nrmse, expected):
        g = et.grade_period(nrmse=nrmse, terminated_frac=0.0, upright_mean=0.99,
                            cmd_vx_min=0.20, survivors=8, num_envs=8, lag_s=0.02,
                            period=1.0, vx_base=0.30, waveform_injected_ok=True)
        assert g["verdict"] == expected

    def test_injection_failure_forces_invalid(self):
        """NEGATIVE CONTROL: even a 'usable' nRMSE becomes invalid if the
        measurement-integrity gate is red -- we measured the wrong thing."""
        g = et.grade_period(nrmse=0.10, terminated_frac=0.0, upright_mean=0.99,
                            cmd_vx_min=0.20, survivors=8, num_envs=8, lag_s=0.02,
                            period=1.0, vx_base=0.30, waveform_injected_ok=False)
        assert g["verdict"] == "invalid"

    def test_none_terminated_frac_blocks_usable(self):
        """A recording with no fall log cannot be signed off as usable."""
        g = et.grade_period(nrmse=0.10, terminated_frac=None, upright_mean=0.99,
                            cmd_vx_min=0.20, survivors=8, num_envs=8, lag_s=0.02,
                            period=1.0, vx_base=0.30, waveform_injected_ok=True)
        assert g["verdict"] != "usable"
        assert g["gates"]["no_fall"] is None

    def test_period0_lag_gate_is_undefined_not_false(self):
        g = et.grade_period(nrmse=0.10, terminated_frac=0.0, upright_mean=0.99,
                            cmd_vx_min=0.20, survivors=8, num_envs=8, lag_s=0.02,
                            period=0.0, vx_base=0.30, waveform_injected_ok=True)
        assert g["gates"]["lag_is_transport_delay"] is None


# ------------------------------------------------------ baseline_healthy 4 states


class TestBaselineHealthy:
    @staticmethod
    def _b(nrmse, terminated=0.0):
        return {"terminated_frac": terminated,
                "headline": {"nrmse_vx_best": nrmse}}

    def test_zero_nrmse_is_healthy_not_missing(self):
        """REGRESSION: the old ``(nrmse or 9.9)`` read a legitimate 0.0 as
        missing and falsely red a perfect static hold. Must stay fixed."""
        assert et.baseline_healthy(self._b(0.0)) is True

    def test_e3_real_baseline_is_healthy(self):
        assert et.baseline_healthy(self._b(0.143)) is True

    def test_large_error_is_unhealthy(self):
        assert et.baseline_healthy(self._b(0.9)) is False

    def test_undefined_nrmse_is_unhealthy(self):
        assert et.baseline_healthy(self._b(None)) is False

    def test_falling_baseline_is_unhealthy(self):
        assert et.baseline_healthy(self._b(0.1, terminated=0.3)) is False

    def test_none_baseline_is_undeterminable(self):
        assert et.baseline_healthy(None) is None


# ------------------------------------------------------------ command_integrity


class TestCommandIntegrity:
    """Live-only: is this recording even the tracking experiment we asked for?"""

    def test_varying_command_with_response_passes(self):
        cmd = _sine(300, 50)
        meas = [0.30 + 0.45 * (c - 0.30) for c in cmd]
        r = live.command_integrity(1.0, torch.tensor(cmd), torch.tensor(meas), 0.10)
        assert r["ok"] is True and r["reason"] == "ok"

    def test_flat_command_fails(self):
        cmd = [0.30] * 300
        meas = [0.17] * 300
        r = live.command_integrity(1.0, torch.tensor(cmd), torch.tensor(meas), 0.10)
        assert r["ok"] is False

    def test_flat_response_fails(self):
        cmd = _sine(300, 50)
        meas = [0.17] * 300
        r = live.command_integrity(1.0, torch.tensor(cmd), torch.tensor(meas), 0.10)
        assert r["ok"] is False

    @pytest.mark.parametrize("n", [3, 10, 39])
    def test_too_short_fails_without_crash(self, n):
        cmd = _sine(n, 50)
        r = live.command_integrity(1.0, torch.tensor(cmd), torch.tensor(cmd), 0.10)
        assert r["ok"] is False and r["reason"] == "too_short_or_length_mismatch"

    def test_length_mismatch_fails(self):
        r = live.command_integrity(1.0, torch.tensor(_sine(300, 50)),
                                   torch.tensor(_sine(200, 50)), 0.10)
        assert r["ok"] is False

    def test_baseline_held_passes(self):
        r = live.command_integrity(0.0, torch.tensor([0.30] * 300),
                                   torch.tensor([0.17] * 300), 0.0)
        assert r["ok"] is True

    def test_baseline_not_held_fails(self):
        """NEGATIVE CONTROL: a period-0 record whose command actually moves is
        not a static-hold baseline; must be rejected, not used as health check."""
        r = live.command_integrity(0.0, torch.tensor(_sine(300, 50)),
                                   torch.tensor(_sine(300, 50)), 0.10)
        assert r["ok"] is False and r["reason"] == "baseline_not_held"


# ---------------------------------------------------------------- grade_trials end-to-end


class TestGradeTrials:
    def test_planted_gain_and_lag_recovered(self):
        n, ps, lag = 300, 50, 4
        cmd = _sine(n, ps)
        meas = [0.0] * lag + [0.8 * c for c in cmd[:-lag]]
        g = live.grade_trials(_rec(1.0, cmd, meas))
        assert abs(g["headline"]["gain"] - 0.8) < 1e-3
        assert abs(g["headline"]["lag_s"] - lag * DT) < 1e-9
        assert g["verdict"] == "usable"

    @pytest.mark.parametrize("mutate,expect_verdict", [
        ("flat_cmd", "invalid"),
        ("flat_meas", "invalid"),
        ("short", "invalid"),
    ])
    def test_bad_recordings_never_false_green(self, mutate, expect_verdict):
        cmd = _sine(300, 50)
        meas = [0.30 + 0.45 * (c - 0.30) for c in cmd]
        if mutate == "flat_cmd":
            cmd = [0.30] * 300
        elif mutate == "flat_meas":
            meas = [0.17] * 300
        elif mutate == "short":
            cmd, meas = cmd[:10], meas[:10]
        g = live.grade_trials(_rec(1.0, cmd, meas))
        assert g["verdict"] == expect_verdict

    def test_missing_fell_blocks_usable(self):
        cmd = _sine(300, 50)
        meas = [0.30 + 0.8 * (c - 0.30) for c in cmd]
        rec = _rec(1.0, cmd, meas)
        rec.pop("fell")
        rec.pop("upright")
        g = live.grade_trials(rec)
        assert g["verdict"] != "usable"
        assert any("fell" in n for n in g["degradation_notes"])

    def test_single_trial_survivors_gate_is_none_not_false_red(self):
        """A single real run cannot establish a survival RATE; the gate must be
        undeterminable (None), never a false red that looks like a policy defect."""
        cmd = _sine(300, 50)
        meas = [0.30 + 0.8 * (c - 0.30) for c in cmd]
        g = live.grade_trials(_rec(1.0, cmd, meas))
        assert g["gates"]["survivors_enough"] is None
        assert any("trial" in n for n in g["degradation_notes"])

    def test_six_trials_survivors_gate_is_determinable(self):
        n, ps = 300, 50
        one_cmd = _sine(n, ps)
        trials = [{"cmd_vx": one_cmd,
                   "meas_vx": [0.30 + 0.8 * (c - 0.30) for c in one_cmd],
                   "fell": False, "upright": [0.99] * n} for _ in range(6)]
        rec = _rec(1.0, one_cmd, trials[0]["meas_vx"], trials=trials)
        g = live.grade_trials(rec)
        assert g["gates"]["survivors_enough"] is True
        assert g["n_trials"] == 6


# ------------------------------------------- calibration against the E3 sim artefact


class TestAgainstSimArtefact:
    """Offline: feed E3's committed sim reports through the shared grader.

    This is CALIBRATION, never live evidence -- the numbers are the sim's own.
    It proves the extracted grade_period reproduces the verdicts the E3 commit
    already shipped, so the refactor of eval_tracking.py moved nothing.
    """

    @pytest.mark.parametrize("name", ["sine", "step"])
    def test_sim_report_reproduces_zero_mismatches(self, name):
        p = (Path(__file__).resolve().parents[2] / "artifacts" / "flat_walk"
             / "evals" / f"tracking_p8head2999_{name}.json")
        if not p.exists():
            pytest.skip(f"E3 artefact not present: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data:
            vx, g = r["vx_tracking"], r["gates"]
            got = et.grade_period(
                nrmse=vx.get("nrmse_best", {}).get("p50"),
                terminated_frac=r.get("terminated_frac"),
                upright_mean=r.get("upright_mean"),
                cmd_vx_min=vx.get("cmd_min", {}).get("p50"),
                survivors=r.get("survivors"), num_envs=r.get("num_envs"),
                lag_s=vx.get("lag_s_best", {}).get("p50", 1.0),
                period=r["period_s"], vx_base=r["base"]["vx"],
                waveform_injected_ok=g["waveform_injected_ok"])
            for k in ("survivors_enough", "no_fall", "stays_upright",
                      "tracks_period", "lag_is_transport_delay",
                      "waveform_injected_ok"):
                assert got["gates"][k] == g.get(k), (name, r["period_s"], k)
            assert got["verdict"] == r["verdict"], (name, r["period_s"], "verdict")


# --------------------------------------------------------------- CLI (real process)


class TestCLIEndToEnd:
    """The project keeps getting bitten by 'only internal funcs tested, argparse
    command dies'. These run the tool as a REAL subprocess over a real JSON file.
    """

    @staticmethod
    def _write_sweep(tmp_path):
        n = 300
        base = {"period_s": 0.0, "waveform": "sine", "dt": DT,
                "cmd_vx": [0.30] * n, "meas_vx": [0.17] * n, "fell": False,
                "upright": [0.99] * n, "base": {"vx": 0.30}, "amp": {"vx": 0.0},
                "meta": {"source": "live", "live_hardware_accessed": False}}
        trials = []
        for _ in range(6):
            cmd = _sine(n, 50)
            meas = [0.30 + 0.45 * (c - 0.30) for c in cmd]  # weak follower -> fail
            trials.append({"cmd_vx": cmd, "meas_vx": meas, "fell": False,
                           "upright": [0.99] * n})
        slow = {"period_s": 5.0, "waveform": "sine", "dt": DT, "trials": trials,
                "base": {"vx": 0.30}, "amp": {"vx": 0.10},
                "meta": {"source": "live", "live_hardware_accessed": False}}
        p = tmp_path / "sweep.json"
        p.write_text(json.dumps([base, slow]), encoding="utf-8")
        return p

    def test_calibrate_flag_exits_zero(self):
        r = subprocess.run([str(PY), str(TOOLS / "eval_tracking_live.py"),
                            "--calibrate"], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "13/13 passed" in r.stdout

    def test_against_sim_flag_exits_zero(self):
        sim = (Path(__file__).resolve().parents[2] / "artifacts" / "flat_walk"
               / "evals" / "tracking_p8head2999_sine.json")
        if not sim.exists():
            pytest.skip("E3 artefact not present")
        r = subprocess.run([str(PY), str(TOOLS / "eval_tracking_live.py"),
                            "--against-sim", str(sim)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "0 mismatches" in r.stdout

    def test_full_json_run_writes_report_and_csv(self, tmp_path):
        inp = self._write_sweep(tmp_path)
        out, csv = tmp_path / "report.json", tmp_path / "report.csv"
        r = subprocess.run([str(PY), str(TOOLS / "eval_tracking_live.py"),
                            "--in", str(inp), "--out", str(out), "--csv", str(csv)],
                           capture_output=True, text=True)
        # weak follower -> the time-varying period fails -> exit 1 (not a crash)
        assert r.returncode == 1, r.stdout + r.stderr
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["baseline_healthy"] is True
        assert report["verdict"] == "PATH_3"
        assert report["results"][0]["source"] == "live"
        assert csv.exists() and "verdict" in csv.read_text(encoding="utf-8").splitlines()[0]

    def test_no_input_errors_out(self):
        r = subprocess.run([str(PY), str(TOOLS / "eval_tracking_live.py")],
                           capture_output=True, text=True)
        assert r.returncode != 0
        assert "required" in r.stderr or "--in" in r.stderr

    def test_tool_source_has_no_selftest_literal(self):
        """The gate orchestrator discovers tools by the '--selftest' literal in
        source. This tool must NOT carry it, or it will be run as a gate with an
        unknown flag and turn the 50/50 green suite red."""
        src = (TOOLS / "eval_tracking_live.py").read_text(encoding="utf-8")
        assert "--self" + "test" not in src
