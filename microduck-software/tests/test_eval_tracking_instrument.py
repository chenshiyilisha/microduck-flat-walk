"""Instrument calibration for ``tools/eval_tracking.py`` (synthetic ground truth).

WHY THIS EXISTS
---------------
``eval_tracking.py`` makes a *measurement*: the gain / transport lag / normalised
RMSE with which a walking policy tracks a moving velocity command. Its verdict
(``usable`` / ``marginal`` / ``fail``) drives a real architecture decision
(path 1 / 2 / 3 in ``docs/active/microduck-阶段3-自动跟随.md``). Before trusting
that verdict on a real policy, we must prove the instrument recovers KNOWN
answers from signals we construct ourselves -- the same "does the number move,
is the magnitude right" discipline applied to every new physical quantity.

Everything here is pure torch on CPU: no checkpoint, no GPU, no MuJoCo, no
simulation. Every positive assertion has a NEGATIVE CONTROL: break the rule,
the check must go red. A calibration suite that has only ever been green proves
nothing (the project's standing rule).

CI BOUNDARY
-----------
torch is intentionally NOT in ``tools/hd1910/requirements.txt`` (lean CI installs
only onnx / onnxruntime), so ``pytest.importorskip("torch")`` SKIPS this entire
module in CI and RUNS it locally under ``.venv-mjlab``. This file deliberately
does not define a self-test CLI entry point, so the gate orchestrator's tool
discovery (which scans ``tools/**/*.py``) does not mistake it for a gate.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import eval_tracking as et  # noqa: E402

DT = 0.02  # 50 Hz, the policy control rate


def _sine(n: int, period_steps: int, amp: float, base: float = 0.0) -> torch.Tensor:
    return base + amp * torch.sin(
        2.0 * math.pi * torch.arange(n, dtype=torch.float64) / period_steps
    )


# ------------------------------------------------------------------ make_wave


class TestMakeWave:
    """The command driver itself must be correct before its output is trusted."""

    def test_period_zero_holds_base(self):
        f = et.make_wave("sine", base=0.30, amp=0.10, period=0.0, dt=DT)
        vals = [f(i) for i in range(200)]
        assert all(abs(v - 0.30) < 1e-12 for v in vals)
        # negative control: a driver that ignored base would read != 0.30
        assert not all(abs(v) < 1e-12 for v in vals)

    def test_zero_amplitude_holds_base(self):
        f = et.make_wave("sine", base=0.30, amp=0.0, period=1.0, dt=DT)
        assert all(abs(f(i) - 0.30) < 1e-12 for i in range(200))

    def test_sine_is_bounded_centred_and_periodic(self):
        period, amp, base = 1.0, 0.10, 0.30
        steps = int(round(period / DT))  # 50 steps == one period
        f = et.make_wave("sine", base, amp, period, DT)
        vals = [f(i) for i in range(4 * steps)]
        assert max(vals) <= base + amp + 1e-12
        assert min(vals) >= base - amp - 1e-12
        assert abs(sum(vals) / len(vals) - base) < 1e-2  # centred on base
        periodic = all(abs(f(i) - f(i + steps)) < 1e-9 for i in range(steps))
        assert periodic, "sine must close on itself after one period"

    def test_step_has_exactly_two_levels(self):
        period, amp, base = 1.0, 0.10, 0.30
        steps = int(round(period / DT))
        f = et.make_wave("step", base, amp, period, DT)
        vals = [f(i) for i in range(4 * steps)]
        levels = sorted(set(round(v, 9) for v in vals))
        assert levels == [round(base - amp, 9), round(base + amp, 9)]
        # NEGATIVE CONTROL: a broken driver collapsing to a constant would have
        # one level; this assertion must then fail.
        assert len(levels) == 2

    def test_sine_and_step_are_not_the_same_wave(self):
        s = et.make_wave("sine", 0.3, 0.1, 1.0, DT)
        q = et.make_wave("step", 0.3, 0.1, 1.0, DT)
        assert any(abs(s(i) - q(i)) > 1e-3 for i in range(50))

    def test_unknown_waveform_raises(self):
        with pytest.raises(ValueError):
            et.make_wave("triangle", 0.3, 0.1, 1.0, DT)


# ---------------------------------------------------------------- axis_report


class TestAxisReportRecoversKnownGainAndLag:
    """The core instrument: it must reconstruct a planted gain and delay."""

    def test_pure_gain_zero_lag(self):
        x = _sine(200, 50, 0.1, 0.3)
        y = 0.8 * x
        r = et._axis_report(x, y, DT, max_lag=20, period=1.0)
        assert r["gain_best"] == pytest.approx(0.8, abs=1e-6)
        assert r["nrmse_best"] < 1e-6
        assert r["lag_steps_best"] == 0

    def test_gain_plus_planted_lag(self):
        x = _sine(200, 50, 0.1, 0.3)
        lag = 5
        y = torch.cat([torch.zeros(lag, dtype=torch.float64), 0.8 * x[:-lag]])
        r = et._axis_report(x, y, DT, max_lag=20, period=1.0)
        assert r["lag_steps_best"] == lag, "must find the planted 5-step delay"
        assert r["lag_s_best"] == pytest.approx(lag * DT, abs=1e-9)
        assert r["gain_best"] == pytest.approx(0.8, abs=1e-6)
        assert r["nrmse_best"] < 1e-6
        # lag0 error must be strictly worse: that is what makes the lag search
        # non-cosmetic (a constant-gain-only grader would miss this).
        assert r["nrmse_lag0"] > r["nrmse_best"] * 10
        assert r["lag_explains"] > 0.9

    def test_magnitude_of_recovered_lag_tracks_planted_lag(self):
        """New physical quantity -> check it MOVES with the thing it measures."""
        x = _sine(240, 60, 0.1, 0.3)
        found = {}
        for planted in (2, 8, 14):
            y = torch.cat(
                [torch.zeros(planted, dtype=torch.float64), 0.7 * x[:-planted]]
            )
            found[planted] = et._axis_report(x, y, DT, 20, 1.0)["lag_steps_best"]
        assert found == {2: 2, 8: 8, 14: 14}, found

    def test_noise_monotonically_degrades_nrmse(self):
        """NEGATIVE CONTROL: more noise -> strictly worse nRMSE."""
        torch.manual_seed(0)
        x = _sine(200, 50, 0.1, 0.3)
        clean = 0.8 * x
        errs = []
        for sd in (0.0, 0.02, 0.06):
            y = clean + torch.randn(200, dtype=torch.float64) * sd
            errs.append(et._axis_report(x, y, DT, 20, 1.0)["nrmse_best"])
        assert errs[0] < errs[1] < errs[2], errs
        assert errs[0] < 1e-6

    def test_nrmse_is_scale_invariant(self):
        """Normalisation by the command RMS must make nRMSE amplitude-independent."""
        x = _sine(200, 50, 0.1, 0.3)
        y = 0.8 * x
        base = et._axis_report(x, y, DT, 20, 1.0)["nrmse_best"]
        scaled = et._axis_report(3.0 * x, 3.0 * y, DT, 20, 1.0)["nrmse_best"]
        assert base == pytest.approx(scaled, abs=1e-6)

    def test_constant_command_reads_finite_nrmse(self):
        """period-0 baseline: command RMS is constant, must not divide by ~0."""
        x = torch.full((200,), 0.3, dtype=torch.float64)
        y = torch.full((200,), 0.22, dtype=torch.float64)  # 22% static under-shoot
        r = et._axis_report(x, y, DT, 20, period=0.0)
        assert math.isfinite(r["nrmse_best"])
        assert r["nrmse_best"] == pytest.approx(0.0, abs=1e-6)  # gain absorbs it
        assert r["gain_best"] == pytest.approx(0.22 / 0.3, abs=1e-6)
        assert r["norm_kind"] == "uncentred_rms_cmd"  # static baseline keeps its old scale


class TestNormaliserCatchesNonTracking:
    """Regression for a REAL false-green found by instrument calibration 2026-11-11.

    The command has a large DC base (vx 0.30) and a small swing (amplitude 0.10):
    uncentred rms_cmd = 0.308 while the AC-facing RMS is only 0.071 (4.36x).
    Dividing residuals by the uncentred value made UNRELATED signals (different
    frequency, white noise, even anti-phase) all score nRMSE 0.14-0.37 < the
    usable bar 0.40 -- i.e. "it follows" when it demonstrably does not. A policy
    that ignores the moving command would have been signed off as "usable".

    The fix: for period>0, normalise by the mean-removed (AC-facing) RMS of the
    command. period==0 keeps uncentred rms_cmd so the static baseline stays finite.
    These tests fail loudly if anyone reverts to the diluted denominator.
    """

    def _cmd(self):
        return _sine(200, 50, 0.1, 0.3)

    def test_time_varying_uses_ac_facing_denominator(self):
        x = self._cmd()
        r = et._axis_report(x, 0.8 * x, DT, 20, 1.0)
        assert r["norm_kind"] == "ac_rms"
        assert r["norm_value"] == pytest.approx(float((x - x.mean()).square().mean().sqrt()), abs=1e-9)
        assert r["norm_value"] < float((x * x).mean().sqrt())  # strictly smaller than diluted

    @pytest.mark.parametrize("bad_name,bad", [
        ("unrelated_p7", lambda x: _sine(200, 7, 0.1, 0.3)),
        ("unrelated_p13", lambda x: _sine(200, 13, 0.1, 0.3)),
        ("white_noise", lambda x: 0.3 + torch.randn(200, dtype=torch.float64) * 0.1),
    ])
    def test_non_tracking_signal_is_failed(self, bad_name, bad):
        """NEGATIVE CONTROL: every no-relation response MUST exceed the usable bar."""
        torch.manual_seed(0)
        x = self._cmd()
        r = et._axis_report(x, bad(x), DT, 20, 1.0)
        assert r["nrmse_best"] > et.NRMSE_USABLE, (
            "%s scored nRMSE %.3f <= usable %.2f (false green is back)"
            % (bad_name, r["nrmse_best"], et.NRMSE_USABLE)
        )

    def test_true_tracking_stays_usable_under_ac_normaliser(self):
        """POSITIVE CONTROL: the fix must not condemn a genuine follower."""
        x = self._cmd()
        lag = 4
        y = torch.cat([torch.zeros(lag, dtype=torch.float64), 0.8 * x[:-lag]])
        r = et._axis_report(x, y, DT, 20, 1.0)
        assert r["nrmse_best"] <= et.NRMSE_USABLE
        assert r["lag_steps_best"] == lag

    def test_too_short_series_returns_only_n(self):
        r = et._axis_report(torch.arange(3, dtype=torch.float64),
                            torch.arange(3, dtype=torch.float64), DT, 20, 1.0)
        assert r == {"n": 3}


# --------------------------------------------------------------------- spread


class TestSpread:
    """The per-env distribution summary must report the real min/p50/max shape."""

    def test_known_values(self):
        s = et._spread([1.0, 2.0, 3.0, 4.0, 5.0])
        assert s["n"] == 5
        assert s["p10"] < s["p50"] < s["p90"]
        assert s["p50"] == pytest.approx(3.0, abs=1e-9)
        assert s["mean"] == pytest.approx(3.0, abs=1e-9)
        assert s["std"] > 0
        assert s["sem"] == pytest.approx(s["std"] / math.sqrt(5), abs=1e-9)

    def test_coverage_fraction_moves_with_content(self):
        """NEGATIVE CONTROL: adding an outlier must move mean but not median."""
        clean = et._spread([1.0, 2.0, 3.0, 4.0, 5.0])
        with_outlier = et._spread([1.0, 2.0, 3.0, 4.0, 500.0])
        assert with_outlier["mean"] > clean["mean"] * 10
        assert with_outlier["p50"] == pytest.approx(clean["p50"], abs=1e-9)

    def test_empty_and_single(self):
        assert et._spread([]) == {"n": 0}
        one = et._spread([7.0])
        assert one["n"] == 1 and one["p50"] == pytest.approx(7.0)
        assert one["std"] is None and one["sem"] is None


class TestAggregateAxisSkipsUndefined:
    """Regression for the 2026-11-11 CLI crash that left eval_tracking unused.

    The very first real smoke (period-0 baseline) died with
    ``TypeError: must be real number, not NoneType``: _axis_report returns None
    for phase_lag_deg at period 0 and for lag_explains when the lag-0 residual
    is ~0, and the per-env aggregation fed those straight into torch.tensor.
    As a result the tool had been committed but NEVER produced a verdict. The
    fix aggregates only defined values and reports n = count of defined ones.
    """

    def test_none_values_are_skipped_not_treated_as_zero(self):
        reports = [
            {"v": 0.4, "phase": None},
            {"v": 0.6, "phase": 12.0},
            {"v": None, "phase": 18.0},
        ]
        v = et.aggregate_axis(reports, "v")
        assert v["n"] == 2, "None must be skipped, n counts defined values"
        assert v["p50"] == pytest.approx(0.5)
        ph = et.aggregate_axis(reports, "phase")
        assert ph["n"] == 2 and ph["p50"] == pytest.approx(15.0)

    def test_all_undefined_field_returns_empty_not_crash(self):
        """NEGATIVE CONTROL: an all-None field (period-0 phase) must not crash."""
        reports = [{"phase": None}, {"phase": None}]
        assert et.aggregate_axis(reports, "phase") == {"n": 0}
        assert et.aggregate_axis(reports, "missing_key") == {"n": 0}

    def test_period0_axis_report_aggregates_without_exception(self):
        """End-to-end-ish: real period-0 _axis_report output aggregated for all keys."""
        x = torch.full((200,), 0.3, dtype=torch.float64)
        y = 0.73 * x
        r = et._axis_report(x, y, DT, 20, 0.0)
        vx_keys = ("nrmse_best", "nrmse_lag0", "lag_s_best", "phase_lag_deg",
                   "gain_best", "gain_lag0", "bias_best", "lag_explains", "meas_mean")
        for k in vx_keys:
            out = et.aggregate_axis([r], k)  # previously raised TypeError
            assert out["n"] in (0, 1)
        assert et.aggregate_axis([r], "phase_lag_deg")["n"] == 0  # undefined at period 0
        assert et.aggregate_axis([r], "gain_best")["n"] == 1       # defined


class TestClassifySweep:
    """CLI path-1/2/3 decision + the 2026-11-11 baseline-only crash regression.

    The CLI used to hold this logic inline, where a baseline-only run
    (``--periods 0``) raised ``UnboundLocalError: fast`` and an empty ``fast``
    could satisfy path 1 via ``all()``'s vacuous truth. Now it is a pure
    function with real negative controls, no sim/GPU/ckpt required.
    """

    @staticmethod
    def _r(period, verdict="usable"):
        return {"period_s": period, "verdict": verdict}

    def test_baseline_only_is_not_path_1(self):
        """NEGATIVE CONTROL: empty fast must not be mistaken for 'all follow'."""
        assert et.classify_sweep([self._r(0.0)], healthy=True) == "BASELINE_ONLY"

    def test_broken_baseline_short_circuits_everything(self):
        results = [self._r(0.0), self._r(1.0)]  # even a 'usable' period
        assert et.classify_sweep(results, healthy=False) == "INSTRUMENT_BROKEN"

    def test_all_fast_periods_usable_is_path_1(self):
        results = [self._r(0.0), self._r(0.5), self._r(1.0), self._r(2.0)]
        assert et.classify_sweep(results, healthy=True) == "PATH_1"

    def test_fast_but_slow_only_is_path_2(self):
        """Only the 5s period tracks; the 0.5/1/2s fast ones do not."""
        results = [self._r(0.0), self._r(0.5, "fail"), self._r(2.0, "fail"),
                   self._r(5.0, "usable")]
        assert et.classify_sweep(results, healthy=True) == "PATH_2"

    def test_nothing_tracks_is_path_3(self):
        results = [self._r(0.0), self._r(0.5, "fail"), self._r(5.0, "fail")]
        assert et.classify_sweep(results, healthy=True) == "PATH_3"

    def test_marginal_is_not_usable(self):
        """NEGATIVE CONTROL: 'marginal' must not count as tracking."""
        results = [self._r(0.0), self._r(1.0, "marginal"), self._r(5.0, "marginal")]
        assert et.classify_sweep(results, healthy=True) == "PATH_3"


# ---------------------------------------------------------------- wave driver


class _FakeTerm:
    """Minimal stand-in for the mjlab twist command term (no simulation)."""

    def __init__(self, n_envs: int):
        self.vel_command_b = torch.zeros(n_envs, 3, dtype=torch.float64)
        self.metric_calls = 0

    def _update_metrics(self):
        self.metric_calls += 1


class TestWaveDriverInjection:
    """The driver must actually WRITE the waveform into the live command buffer."""

    def test_writes_wave_per_step_and_keeps_metrics(self):
        term = _FakeTerm(4)
        waves = [lambda i, b=b, a=a: b + a * math.sin(i / 3.0)
                 for b, a in ((0.3, 0.1), (0.0, 0.0), (0.0, 0.6))]
        driver = et.WaveDriver(term, waves, DT)
        for i in range(6):
            driver(DT)
            assert term.vel_command_b[:, 0] == pytest.approx(0.3 + 0.1 * math.sin(i / 3.0))
            assert term.vel_command_b[:, 2] == pytest.approx(0.6 * math.sin(i / 3.0))
        assert driver.n == 6
        assert term.metric_calls == 6  # official accumulator still ticks

    def test_zero_dt_does_not_advance_command(self):
        """NEGATIVE CONTROL: a paused sim must not advance the waveform."""
        term = _FakeTerm(2)
        driver = et.WaveDriver(term, [lambda i: 0.3 + 0.1 * i], DT)
        driver(0.0)
        assert driver.n == 0
        assert float(term.vel_command_b[:, 0].mean()) == 0.0
        assert term.metric_calls == 1  # metrics still called even on a paused step
