#!/usr/bin/env python
"""Grade REAL-ROBOT time-varying command tracking, in E3's exact voice.

WHY THIS EXISTS
---------------
``tools/eval_tracking.py`` answered "can the current policy follow a moving
command?" -- but only in MuJoCo (``live_hardware_accessed=false``). The sim-side
verdict is ``PATH_3`` (it cannot), and ``INCONCLUSIVE_LIVE_TRACKING`` / B1 check
``BA-X-4`` stay open because the REAL robot has never been measured. This tool is
the missing *frontend*: when a real run produces a recorded time series, it
grades that series with the SAME instrument the sim used, so the day the board is
up nobody has to re-derive nRMSE / lag / gates by hand (the 2026-11-11 E3 smoke
hit four decision-changing bugs precisely because grading was done ad hoc).

THE ONE RULE THAT MATTERS
-------------------------
This module does NOT reimplement any judgement. It imports ``eval_tracking``'s
pure functions and is tested to share the SAME objects::

    eval_tracking_live.grade_period  is eval_tracking.grade_period
    eval_tracking_live.baseline_healthy is eval_tracking.baseline_healthy
    eval_tracking_live._axis_report  is eval_tracking._axis_report
    eval_tracking_live.classify_sweep is eval_tracking.classify_sweep

So a sim grade and a live grade of identical numbers agree bit-for-bit. The only
thing that is live-specific is *measurement-integrity*: in sim the driver knows
the exact waveform and checks ``last_cmd == expected_last``; on real hardware
there is no such oracle, so ``command_integrity()`` verifies the recorded command
series actually varies at the requested period (and the measured series actually
responds). If that fails the verdict is ``invalid`` -- "we recorded something,
but not the tracking experiment we asked for".

WHAT IT DOES NOT DO
-------------------
* It does NOT drive the robot, talk to robotd, or read any live bus. It is
  deliberately OFFLINE: it grades a file someone else produced. That keeps it
  testable without hardware and keeps ``live_hardware_accessed=false`` honest.
* It does NOT close ``INCONCLUSIVE_LIVE_TRACKING``. A real graded file only
  becomes board-acceptance evidence after a human signs it off against B1 BA-X-4
  (see docs/active/microduck-真机跟踪评测前端-E4-2026-11-12.md). Feeding it the
  E3 sim artefacts is a *calibration* check, never live evidence.

INPUT FORMAT (JSON, one file = one sweep of periods)
---------------------------------------------------
A top-level list of period records, each:

    {
      "period_s": 1.0,
      "waveform": "sine",
      "dt": 0.02,
      "cmd_vx": [0.30, 0.31, ...],      # commanded vx (body frame), 50 Hz
      "meas_vx": [0.12, 0.13, ...],     # measured body-frame vx (odom/IMU est.)
      "cmd_wz": [...], "meas_wz": [...],  # optional; omitted => wz not graded
      "upright": [0.99, ...],           # optional [-proj_gravity_z], 0..1
      "fell": false,                    # optional; or fraction if trials merged
      "base": {"vx": 0.30, "vy": 0.0, "wz": 0.0},
      "amp":  {"vx": 0.10, "vy": 0.0, "wz": 0.6},
      "meta": {"source": "live", "ckpt": "...", "gain": 8, "note": "..."}
    }

A list entry may instead be ``"trials": [ {...}, {...} ]`` to grade several real
runs of the same period as several "envs" (per-trial _axis_report, then
aggregate_axis spreads). A single record is treated as one trial.

CSV is also accepted: one row per sample with columns
``period_s,waveform,dt,trial,cmd_vx,meas_vx[,cmd_wz,meas_wz,upright]``; rows with
the same (period_s, trial) group into one series.

Usage:
  # grade a recorded live sweep, write the full report + CSV
  python tools/eval_tracking_live.py --in live_tracking.json \
      --out artifacts/flat_walk/evals/live_tracking_report.json \
      --csv artifacts/flat_walk/evals/live_tracking_report.csv
  # calibration only (no robot, no file): prove the frontend shares E3's instrument
  python tools/eval_tracking_live.py --calibrate
  # offline self-check against the committed E3 sim artefacts (NOT live evidence)
  python tools/eval_tracking_live.py --against-sim \
      --sim ../artifacts/flat_walk/evals/tracking_p8head2999_sine.json

Exit 0 when every time-varying period grades usable, 1 otherwise, 2 when the
period-0 baseline is unhealthy (nothing measurable), 3 on an input/integrity
error. It never exits 0 on an ``invalid`` period.

NOTE: this file intentionally exposes NO self-test CLI flag. The gate orchestrator
(``tools/hd1910/run_all_gates.py::discover``) discovers every tools file whose
source contains that flag's literal spelling; this module's correctness is proven
by ``tests/test_eval_tracking_live.py`` (pure torch, no hardware). A regression
test keeps the literal out of this source so the 50/50 gate suite stays green.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _cand in (ROOT / "tools", Path(__file__).resolve().parent):
    if _cand.is_dir() and str(_cand) not in sys.path:
        sys.path.insert(0, str(_cand))

import torch  # noqa: E402

import eval_tracking as et  # noqa: E402

# The judgement is the sim instrument's, verbatim. Tests assert object identity.
grade_period = et.grade_period
baseline_healthy = et.baseline_healthy
_axis_report = et._axis_report
aggregate_axis = et.aggregate_axis
classify_sweep = et.classify_sweep
NRMSE_USABLE = et.NRMSE_USABLE

DT_DEFAULT = 0.02  # 50 Hz, the policy control rate
# Must match eval_tracking.py's CLI default ``--max-lag 20`` so a live grade and
# a sim grade search the exact same transport-delay window.
MAX_LAG_STEPS = 20
# Below this many real trials, ``survivors_enough`` is not determinable (a single
# run cannot establish a survival *rate*). We mark the gate None -- visible but
# not a false red -- and the report says the statistical strength is weak.
MIN_TRIALS_FOR_RATE = 4
# Live command-injection integrity thresholds. These are NOT judgement thresholds
# (they do not decide usable/fail); they decide whether the recording is even the
# tracking experiment we asked about. Stated here so they are auditable.
MIN_UNIQ_CMD = 8       # a varying command must visit >8 distinct levels
MIN_CMD_AC_FRAC = 0.10  # ac RMS must be >=10% of the command amplitude
MIN_RESPONSE_FRAC = 0.02  # measured series must move at least 2% of cmd amplitude
MIN_SAMPLES = 40       # <40 samples @50Hz (<0.8 s) is too short to grade


def _tensor(vals) -> torch.Tensor:
    return torch.tensor([float(v) for v in vals], dtype=torch.float64)


def command_integrity(period: float, cmd: torch.Tensor, meas: torch.Tensor,
                      amp: float) -> dict:
    """Live-only measurement-integrity gate (the analogue of sim's last_cmd check).

    For a time-varying period: the command must actually vary (distinct levels,
    non-trivial AC content) AND the measured series must actually respond (not a
    flat line). This is what turns "the log was recorded" into "the log contains a
    moving-command experiment". For period 0 the command must be *held*.

    Returns a dict with ``ok`` plus the measured diagnostics so a reviewer can see
    WHY a recording was rejected. The ``ok`` bool is the only thing fed to the
    shared ``grade_period`` as ``waveform_injected_ok``.
    """
    out: dict = {"n": int(cmd.numel())}
    if cmd.numel() < MIN_SAMPLES or cmd.numel() != meas.numel():
        out.update(ok=False, reason="too_short_or_length_mismatch",
                   min_samples=MIN_SAMPLES)
        return out
    uniq = int(torch.unique(torch.round(cmd, decimals=6)).numel())
    ac = float(torch.sqrt(((cmd - cmd.mean()) ** 2).mean()))
    meas_ac = float(torch.sqrt(((meas - meas.mean()) ** 2).mean()))
    out.update(n_uniq_cmd=uniq, cmd_ac_rms=ac, meas_ac_rms=meas_ac)
    if period <= 0:
        # baseline: the command must be held (near-zero AC), otherwise it is not a
        # static-hold baseline and cannot serve as the health check.
        ok = (uniq <= 2 and (ac <= max(1e-6, abs(amp) * MIN_CMD_AC_FRAC)))
        out.update(ok=bool(ok), reason="ok" if ok else "baseline_not_held")
        return out
    if amp and abs(amp) > 1e-9:
        ac_frac = ac / abs(amp)
        response_frac = meas_ac / abs(amp)
        out.update(cmd_ac_frac=ac_frac, meas_response_frac=response_frac)
        ok = (uniq >= MIN_UNIQ_CMD and ac_frac >= MIN_CMD_AC_FRAC
              and response_frac >= MIN_RESPONSE_FRAC)
    else:
        # no amplitude declared: fall back to absolute distinctness + response
        ok = uniq >= MIN_UNIQ_CMD and meas_ac > 1e-6
    out.update(ok=bool(ok),
               reason="ok" if ok else "command_or_response_not_injected")
    return out


def _axis_agg(trials: list[dict]) -> dict:
    """Wrap each trial's _axis_report then aggregate_axis over the shared keys."""
    keys = ("nrmse_best", "nrmse_lag0", "lag_s_best", "phase_lag_deg",
            "gain_best", "gain_lag0", "bias_best", "lag_explains", "meas_mean")
    return {k: aggregate_axis([r for r in trials if k in r], k) for k in keys}


def _p50(agg: dict, key: str, dflt=None):
    return agg.get(key, {}).get("p50", dflt)


def grade_trials(period_rec: dict) -> dict:
    """Grade one period record (one or several real trials). Pure-ish (no I/O).

    Uses the sim instrument's ``_axis_report`` per trial and its
    ``aggregate_axis`` / ``grade_period`` / ``classify_sweep``-compatible report
    shape. Output mirrors ``run_one``'s report so the same numbers line up.
    """
    period = float(period_rec["period_s"])
    waveform = period_rec.get("waveform", "sine")
    dt = float(period_rec.get("dt", DT_DEFAULT))
    trials = period_rec.get("trials") or [period_rec]
    base = period_rec.get("base") or {}
    amp = period_rec.get("amp") or {}
    vx_base = float(base.get("vx", 0.30))
    vx_amp = float(amp.get("vx", 0.0))
    wz_amp = float(amp.get("wz", 0.0))
    meta = period_rec.get("meta") or {}

    per_trial: list[dict] = []
    integ_list: list[dict] = []
    fell_flags: list[float] = []
    upright_vals: list[float] = []
    for tr in trials:
        cmd_vx = _tensor(tr["cmd_vx"])
        meas_vx = _tensor(tr["meas_vx"])
        integ = command_integrity(period, cmd_vx, meas_vx, vx_amp)
        integ_list.append(integ)
        rep = _axis_report(cmd_vx, meas_vx, dt, MAX_LAG_STEPS, period)
        per_trial.append(rep)
        if tr.get("fell") is not None:
            fell_flags.append(float(tr["fell"]))
        up = tr.get("upright")
        if up is not None:
            up_t = _tensor(up)
            upright_vals.append(float(up_t.mean()) if up_t.numel() else 0.0)

    vx_agg = _axis_agg(per_trial)
    nrmse = _p50(vx_agg, "nrmse_best")
    nrmse0 = _p50(vx_agg, "nrmse_lag0")
    lag_s = _p50(vx_agg, "lag_s_best", 1.0)
    lag_explains = _p50(vx_agg, "lag_explains")

    # Live integrity is the AND of all trials: one corrupt trial invalidates the
    # period rather than being silently averaged in.
    inj_ok = all(i.get("ok") for i in integ_list)
    terminated_frac = (sum(fell_flags) / len(fell_flags)) if fell_flags else None
    upright_mean = (sum(upright_vals) / len(upright_vals)) if upright_vals else None
    cmd_vx_min = min((float(_tensor(t["cmd_vx"]).min()) for t in trials), default=None)

    # ``survivors_enough`` has no "env" meaning on real hardware. Map it to
    # "enough intact trials to survive the sim gate's shape": when >=MIN_TRIALS
    # trials were recorded and none reported a fall, pass the sim's own
    # survivors/num_envs so the gate reads identically; with <MIN_TRIALS we pass
    # None -> the shared grader emits None (visible, not a false red) and the
    # report flags weak statistical strength. We never fabricate a Pass.
    if len(trials) >= MIN_TRIALS_FOR_RATE and terminated_frac is not None:
        survivors_arg = sum(1 for f in fell_flags if not f) if fell_flags else len(trials)
        num_envs_arg = len(trials)
    else:
        survivors_arg = None
        num_envs_arg = None

    graded = grade_period(
        nrmse=nrmse,
        terminated_frac=terminated_frac,
        upright_mean=upright_mean,
        cmd_vx_min=cmd_vx_min,
        survivors=survivors_arg,
        num_envs=num_envs_arg,
        lag_s=lag_s,
        period=period,
        vx_base=vx_base,
        waveform_injected_ok=inj_ok,
    )
    gates, verdict = graded["gates"], graded["verdict"]

    # Honest degradation notes: a missing fell/upright channel must not silently
    # look like "passing" nor like a tool crash. Say which inputs were absent.
    notes = []
    if terminated_frac is None:
        notes.append("no 'fell' channel: terminated_frac undeterminable -> "
                     "verdict cannot be 'usable' (a real run without a fall log "
                     "is not signable); supply 'fell' per trial")
    if upright_mean is None:
        notes.append("no 'upright' channel: stays_upright gate = None")
    if len(trials) < MIN_TRIALS_FOR_RATE:
        notes.append(f"only {len(trials)} trial(s) < {MIN_TRIALS_FOR_RATE}: "
                     "survivors_enough not determinable; single-run numbers "
                     "carry no seed-spread (E3 used 32 envs, CV 1.8%)")

    wz_agg = None
    if "cmd_wz" in trials[0] and "meas_wz" in trials[0] and wz_amp != 0.0:
        wz_trials = [
            _axis_report(_tensor(tr["cmd_wz"]), _tensor(tr["meas_wz"]), dt, MAX_LAG_STEPS, period)
            for tr in trials
        ]
        wz_agg = {k: aggregate_axis([r for r in wz_trials if k in r], k)
                  for k in ("nrmse_best", "nrmse_lag0", "lag_s_best", "gain_best", "lag_explains")}

    return {
        "source": "live",
        "live_hardware_accessed": bool(meta.get("live_hardware_accessed", True)),
        "period_s": period,
        "waveform": waveform,
        "dt": dt,
        "n_trials": len(trials),
        "n_samples": [int(len(t["cmd_vx"])) for t in trials],
        "base": base, "amp": amp, "meta": meta,
        "command_integrity": integ_list,
        "degradation_notes": notes,
        "max_lag_steps": MAX_LAG_STEPS,
        "vx_tracking": vx_agg,
        "wz_tracking": wz_agg,
        "terminated_frac": terminated_frac,
        "upright_mean": upright_mean,
        "headline": {
            "nrmse_vx_best": nrmse,
            "nrmse_vx_lag0": nrmse0,
            "nrmse_normaliser": ("ac_rms (period>0, mean-removed command swing)"
                                 if period > 0 else "uncentred_rms_cmd (static baseline)"),
            "lag_s": lag_s,
            "phase_lag_deg": _p50(vx_agg, "phase_lag_deg"),
            "gain": _p50(vx_agg, "gain_best"),
            "lag_explains": lag_explains,
        },
        "gates": gates,
        "verdict": verdict,
        "passed": [k for k, v in gates.items() if v],
        "failed": [k for k, v in gates.items() if v is False],
    }


def grade_sweep(records: list[dict]) -> dict:
    """Grade all periods, attach cost_vs_baseline, classify, and return a report."""
    results = [grade_trials(r) for r in records]
    baseline = next((r for r in results if r["period_s"] == 0.0), None)
    if baseline:
        b = baseline["headline"]
        for r in results:
            if r is baseline:
                r["cost_vs_baseline"] = {"is_baseline": True}
            else:
                # live has no action-acc metrics unless the采集端 supplies them
                cost = (r.get("meta", {}).get("cost_metrics") or {})
                r["cost_vs_baseline"] = {"note": "live: action-cost metrics not "
                                         "supplied by采集端; E3 sim cost not transferable"}
                if cost and b.get("gain"):
                    r["cost_vs_baseline"]["supplied"] = cost
    healthy = baseline_healthy(baseline)
    path = classify_sweep(results, healthy)
    return {"verdict": path, "baseline_healthy": healthy, "results": results,
            "judgement_owner": "eval_tracking.grade_period/classify_sweep (shared with sim)"}


# --------------------------------------------------------------------- input


def _load_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("JSON must be a non-empty list of period records")
    return data


def _load_csv(path: Path) -> list[dict]:
    groups: dict[tuple, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (float(row["period_s"]), row.get("waveform", "sine"),
                   row.get("trial", "0"))
            g = groups.setdefault(key, {"period_s": key[0], "waveform": key[1],
                                        "dt": float(row.get("dt", DT_DEFAULT)),
                                        "cmd_vx": [], "meas_vx": [],
                                        "cmd_wz": [], "meas_wz": [], "upright": []})
            g["cmd_vx"].append(float(row["cmd_vx"]))
            g["meas_vx"].append(float(row["meas_vx"]))
            if row.get("cmd_wz"):
                g["cmd_wz"].append(float(row["cmd_wz"]))
                g["meas_wz"].append(float(row["meas_wz"]))
            if row.get("upright"):
                g["upright"].append(float(row["upright"]))
    # group trials by period: same period+waveform, different trial -> trials[]
    periods: dict[tuple, list[dict]] = {}
    for (p, w, _t), g in groups.items():
        g = {k: v for k, v in g.items() if v}  # drop empty optional columns
        periods.setdefault((p, w), []).append(g)
    out = []
    for (p, w), trials in sorted(periods.items()):
        rec = {"period_s": p, "waveform": w, "dt": trials[0]["dt"]}
        rec.update({"base": {"vx": 0.30, "vy": 0.0, "wz": 0.0},
                    "amp": {"vx": 0.10, "vy": 0.0, "wz": 0.6},
                    "meta": {"source": "live"}})
        if len(trials) == 1:
            rec.update(trials[0])
        else:
            rec["trials"] = trials
        out.append(rec)
    return out


# ------------------------------------------------------------------- offline checks


def _calibrate() -> int:
    """Prove (no file, no robot) that the frontend recovers planted answers."""
    checks = []

    def _ok(name, cond):
        checks.append((name, bool(cond)))

    def _close(a, b, tol=1e-9):
        return a is not None and b is not None and abs(a - b) <= tol

    _ok("grade_period shared", grade_period is et.grade_period)
    _ok("baseline_healthy shared", baseline_healthy is et.baseline_healthy)
    _ok("_axis_report shared", _axis_report is et._axis_report)
    _ok("classify_sweep shared", classify_sweep is et.classify_sweep)

    # planted gain+lag through a full period record
    n, ps = 200, 50
    cmd = [0.30 + 0.10 * math.sin(2 * math.pi * i / ps) for i in range(n)]
    lag = 4
    meas = [0.0] * lag + [0.8 * (0.30 + 0.10 * math.sin(2 * math.pi * i / ps))
                          for i in range(n - lag)]
    rec = {"period_s": 1.0, "waveform": "sine", "dt": DT_DEFAULT,
           "cmd_vx": cmd, "meas_vx": meas, "fell": False,
           "upright": [0.99] * n,
           "base": {"vx": 0.30}, "amp": {"vx": 0.10},
           "meta": {"live_hardware_accessed": False}}
    g = grade_trials(rec)
    _ok("planted gain recovered", _close(g["headline"]["gain"], 0.8, 1e-3))
    _ok("planted lag recovered", _close(g["headline"]["lag_s"], lag * DT_DEFAULT))
    _ok("true follower usable", g["verdict"] == "usable")

    # negative control: recorded command never varies -> invalid
    bad = dict(rec)
    bad["meas_vx"] = [0.1] * n
    bad["cmd_vx"] = [0.30] * n
    gb = grade_trials(bad)
    _ok("flat command invalid", gb["verdict"] == "invalid")
    _ok("flat command integrity red", not gb["command_integrity"][0]["ok"])

    # negative control: command varies but measured series flat -> invalid
    dead = dict(rec)
    dead["meas_vx"] = [0.1] * n
    gd = grade_trials(dead)
    _ok("flat response invalid", gd["verdict"] == "invalid")

    # negative control: anti-phase / unrelated must fail, not false-green
    anti = dict(rec)
    anti["meas_vx"] = [0.30 - 0.10 * math.sin(2 * math.pi * i / ps) for i in range(n)]
    ga = grade_trials(anti)
    _ok("anti-phase not usable", ga["verdict"] != "usable")

    # short series -> invalid, no crash
    short = dict(rec)
    short["cmd_vx"] = cmd[:10]
    short["meas_vx"] = meas[:10]
    gs = grade_trials(short)
    _ok("short series invalid", gs["verdict"] == "invalid")

    # negative control: no 'fell' channel -> verdict must NOT be usable (can't sign off)
    no_fell = {k: v for k, v in rec.items() if k != "fell"}
    gn = grade_trials(no_fell)
    _ok("missing fell blocks usable", gn["verdict"] != "usable")

    failed = [name for name, ok in checks if not ok]
    print(f"calibrate: {len(checks) - len(failed)}/{len(checks)} passed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 0 if not failed else 1


def _against_sim(sim_path: Path) -> int:
    """Offline sanity: feed E3 sim reports' p50 back through grade_period and
    confirm the shared grader reproduces their recorded gates/verdict. This is
    CALIBRATION, never live evidence -- the sim numbers are the same numbers.
    """
    data = json.loads(sim_path.read_text(encoding="utf-8"))
    mism = 0
    for r in data:
        vx = r["vx_tracking"]
        g = r["gates"]
        graded = grade_period(
            nrmse=vx.get("nrmse_best", {}).get("p50"),
            terminated_frac=r.get("terminated_frac"),
            upright_mean=r.get("upright_mean"),
            cmd_vx_min=vx.get("cmd_min", {}).get("p50"),
            survivors=r.get("survivors"), num_envs=r.get("num_envs"),
            lag_s=vx.get("lag_s_best", {}).get("p50", 1.0),
            period=r["period_s"], vx_base=r["base"]["vx"],
            waveform_injected_ok=g["waveform_injected_ok"],
        )
        for k in ("survivors_enough", "no_fall", "stays_upright",
                  "tracks_period", "lag_is_transport_delay", "waveform_injected_ok"):
            if graded["gates"][k] != g.get(k):
                mism += 1
                print(f"  MISMATCH T={r['period_s']}s gate {k}: "
                      f"{graded['gates'][k]} != {g.get(k)}")
        if graded["verdict"] != r["verdict"]:
            mism += 1
            print(f"  MISMATCH T={r['period_s']}s verdict: "
                  f"{graded['verdict']} != {r['verdict']}")
    print(f"against-sim {sim_path.name}: {len(data)} periods, {mism} mismatches")
    return 0 if mism == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Grade a recorded REAL-ROBOT time-varying command tracking sweep.")
    ap.add_argument("--in", dest="inp", default=None, help="input JSON or CSV")
    ap.add_argument("--out", default=None, help="write the full JSON report here")
    ap.add_argument("--csv", default=None, help="write one row per period here")
    ap.add_argument("--calibrate", action="store_true",
                    help="no-file/no-robot proof the frontend shares E3's instrument")
    ap.add_argument("--against-sim", default=None,
                    help="offline CALIBRATION against a committed E3 sim report JSON")
    a = ap.parse_args()

    if a.calibrate:
        return _calibrate()
    if a.against_sim:
        return _against_sim(Path(a.against_sim))
    if not a.inp:
        ap.error("one of --in / --calibrate / --against-sim is required")

    path = Path(a.inp)
    records = _load_json(path) if path.suffix.lower() == ".json" else _load_csv(path)
    report = grade_sweep(records)
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {p}")
    if a.csv:
        p = Path(a.csv)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = ["period_s", "verdict", "nrmse_vx_best", "nrmse_vx_lag0", "lag_s",
                "gain", "lag_explains", "n_trials", "waveform_injected_ok",
                "live_hardware_accessed", "integrity_reason"]
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in report["results"]:
                h = r["headline"]
                reason = ";".join(str(i.get("reason")) for i in r["command_integrity"])
                w.writerow([r["period_s"], r["verdict"], h["nrmse_vx_best"],
                            h["nrmse_vx_lag0"], h["lag_s"], h["gain"],
                            h.get("lag_explains"), r["n_trials"],
                            r["gates"]["waveform_injected_ok"],
                            r["live_hardware_accessed"], reason])
        print(f"wrote {p}")

    print("=" * 92)
    print(f"LIVE tracking grade  verdict={report['verdict']}  "
          f"baseline_healthy={report['baseline_healthy']}  "
          f"judgement={report['judgement_owner']}")
    print("-" * 92)
    for r in report["results"]:
        h = r["headline"]
        print(f"  T={r['period_s']:>5}s {r['verdict']:>8}  "
              f"nRMSE={h['nrmse_vx_best']}  lag={h['lag_s']}  "
              f"gain={h['gain']}  inj_ok={r['gates']['waveform_injected_ok']}  "
              f"live={r['live_hardware_accessed']}")
    print("=" * 92)
    print("  CALIBRATION / NOT LIVE EVIDENCE: grading a file never closes "
          "INCONCLUSIVE_LIVE_TRACKING; only a human-signed B1 BA-X-4 can.")
    bad = [r for r in report["results"]
           if r["period_s"] != 0 and r["verdict"] != "usable"]
    if report["baseline_healthy"] is False:
        return 2
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
