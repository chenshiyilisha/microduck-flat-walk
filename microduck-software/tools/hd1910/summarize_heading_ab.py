"""Decide the heading A/B from the two sweeps, on paired checkpoints.

The design, fixed BEFORE looking at any control number
-----------------------------------------------------
Both arms were trained with `seed 42`, `4096 envs`, `3000 iters`, the same
plant (`kp8`), the same command loop (`rel_heading_envs 0.3`, `ang_vel_z +-0.5`)
and the same solver. So for every save index k the two runs are a PAIR: same
initial conditions, same number of gradient steps, one difference (the two
heading reward terms). Comparing arms through paired differences removes both
the checkpoint-selection freedom and most of the run-to-run noise.

Pre-registered rule (written here, not after the fact):

  d(k)      = 100 * (err_yaw_B(k) - err_yaw_A(k)) / err_yaw_A(k)      [%]
  verdict   = "reward helps"  if median(d) <= -10% and at least 80% of pairs
                               have d < 0
              "reward hurts"  if median(d) >= +10% and >= 80% of pairs have d > 0
              "no decision"   otherwise
  guard     = the arm is only declared the winner if its vx is not below
              0.97x the other arm's median vx at the same iterations (an
              err_yaw win bought by standing still is not a win -- the same
              "no speed regression" rule gate_p3_yaw.py applies to baselines)

10% is the pre-registered effect size because single-eval noise on err_yaw is
CV 1.2-2.6% (three repeats, artifacts/flat_walk/evals/p2_yaw/) and the paired
difference at the same iteration is tighter than that, while the effect the
reward is supposed to have (1.20 -> 0.73 rad/s on the kp8 reference point) is
~39%. A 10% bar cannot be cleared by luck and is nowhere near the effect size.

abs_dy / dx_over_expected are printed but never gated: CV 15-25%, and N=10
checkpoints of ONE seed does not fix that (measured 2026-11-03).

Exit codes: 0 decided, 2 no decision (not a failure of the run, a failure of the
test to resolve), 3 integrity problem (mismatched eval settings, missing pairs,
or the two directories are not the two arms).

Usage
    python tools/hd1910/summarize_heading_ab.py \\
        --a-dir ../artifacts/flat_walk/evals/ab_heading/A \\
        --b-dir ../artifacts/flat_walk/evals/ab_heading/B
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_control_arm import load_yaml  # noqa: E402  same tag-stripping reader

ARM_A_ROLE = "rewards"
ARM_B_ROLE = "control (no heading rewards)"
MIN_PAIRS = 5
DECIDE_PCT = 10.0
CONSISTENCY = 0.80
VX_FLOOR = 0.97


def iter_of(rec: dict, path: Path) -> int:
    m = re.search(r"model_(\d+)", Path(rec["checkpoint"]).name) or re.search(r"model_(\d+)", path.name)
    if not m:
        raise SystemExit(f"cannot read the iteration from {path.name}")
    return int(m.group(1))


def load_dir(d: Path) -> list[dict]:
    files = sorted(d.glob("*.json"))
    if not files:
        raise SystemExit(f"no eval JSON in {d}")
    out = []
    for f in files:
        rec = json.load(open(f, encoding="utf-8"))
        rec["_path"] = f
        rec["_iter"] = iter_of(rec, f)
        out.append(rec)
    return sorted(out, key=lambda r: r["_iter"])


def settings(recs: list[dict]) -> dict:
    """The eval settings of one arm; raises if the directory mixes several."""
    keys = ("seed", "num_envs", "seconds")
    per_rec = []
    for r in recs:
        s = {k: r[k] for k in keys}
        s["cmd_vx"] = r["command"]["vx"]
        fp = r["plant_fingerprint"]
        s["plant"] = (fp.get("name"),
                      fp.get("kwargs", {}).get("kp_fw"),
                      fp.get("source_sha256_12"),
                      fp.get("json_sha256_12"))
        s["is_true_mean"] = r["metric_window"]["is_true_mean"]
        per_rec.append((s, r["_path"].name))
    uniq = {json.dumps(s, sort_keys=True, default=str) for s, _ in per_rec}
    if len(uniq) != 1:
        detail = "; ".join(f"{name}: {json.dumps(s, sort_keys=True, default=str)}"
                           for s, name in per_rec[:3])
        raise SystemExit(f"directory mixes several eval settings, cannot pair: {detail}")
    return per_rec[0][0]


def arm_identity(rec: dict) -> str:
    """'rewards' / 'control' read off the run's own params/env.yaml."""
    run = Path(rec["checkpoint"]).parent
    env = run / "params" / "env.yaml"
    if not env.exists():
        return "unknown"
    rewards = load_yaml(env).get("rewards") or {}
    return "rewards" if any("heading" in k for k in rewards) else "control"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True)
    ap.add_argument("--b-dir", required=True)
    ap.add_argument("--decide-pct", type=float, default=DECIDE_PCT)
    ap.add_argument("--consistency", type=float, default=CONSISTENCY)
    ap.add_argument("--min-pairs", type=int, default=MIN_PAIRS)
    a = ap.parse_args()

    A, B = load_dir(Path(a.a_dir)), load_dir(Path(a.b_dir))
    sa, sb = settings(A), settings(B)
    problems = []
    if sa != sb:
        problems.append(f"eval settings differ:\n  A={sa}\n  B={sb}")
    if not (sa["is_true_mean"] and sb["is_true_mean"]):
        problems.append("metric_window.is_true_mean is false: error_vel_xy is not a "
                        "true mean, so it must not be compared across runs")
    ida, idb = arm_identity(A[0]), arm_identity(B[0])
    if ida != "rewards" or idb != "control":
        problems.append(f"directories are not the two arms: A is {ida!r}, B is {idb!r} "
                        f"(expected A=rewards, B=control)")
    ra = {r["_iter"]: r for r in A}
    rb = {r["_iter"]: r for r in B}
    common = sorted(set(ra) & set(rb))
    if len(common) < a.min_pairs:
        problems.append(f"only {len(common)} paired iterations (need >= {a.min_pairs}); "
                        f"unpaired means would mix checkpoint jitter into the verdict")
    if problems:
        for p in problems:
            print(f"INTEGRITY: {p}")
        return 3

    print(f"A (rewards): {a.a_dir}  [{len(A)} ckpts, {sa['num_envs']} env x "
          f"{sa['seconds']}s, seed {sa['seed']}, cmd vx {sa['cmd_vx']}, plant {sa['plant']}]")
    print(f"B (control): {a.b_dir}  [{len(B)} ckpts]")
    print()
    print(f"{'iter':>5} | {'A err_yaw':>9} {'A vx':>6} | {'B err_yaw':>9} {'B vx':>6} | "
          f"{'d_yaw%':>7} {'d_vx%':>7} {'fall A/B':>9}")

    ds, dvx, same_sign, n_neg = [], [], 0, 0
    for k in common:
        ea, eb = ra[k], rb[k]
        ya = ea["official_metrics"]["error_vel_yaw"]
        yb = eb["official_metrics"]["error_vel_yaw"]
        va, vb = ea["speed"]["vx_mean"], eb["speed"]["vx_mean"]
        d = 100.0 * (yb - ya) / ya if ya else float("nan")
        dv = 100.0 * (vb - va) / va if va else float("nan")
        ds.append(d)
        dvx.append(dv)
        if d < 0:
            n_neg += 1
        print(f"{k:5d} | {ya:9.4f} {va:6.4f} | {yb:9.4f} {vb:6.4f} | {d:+7.2f} {dv:+7.2f} "
              f"{ea['stability']['terminated_frac']:4.2f}/{eb['stability']['terminated_frac']:4.2f}")

    n = len(common)
    med_d, med_vx = st.median(ds), st.median(dvx)
    frac_neg = n_neg / n
    print()
    print(f"paired checkpoints: {n}")
    print(f"median d_yaw = {med_d:+.2f}%   (B better in {n_neg}/{n} = {frac_neg:.0%})")
    print(f"median d_vx  = {med_vx:+.2f}%   (guard: B must be >= -3%)")

    # secondary, reported not gated
    for name, get in (("err_xy", lambda r: r["official_metrics"]["error_vel_xy"]),
                      ("abs_dy", lambda r: r["displacement"]["abs_dy_body_median"]),
                      ("dx_ratio", lambda r: r["displacement"]["dx_over_expected"])):
        xa = [get(ra[k]) for k in common]
        xb = [get(rb[k]) for k in common]
        print(f"  {name:9s} A median {st.median(xa):.4f}  B median {st.median(xb):.4f}  "
              f"(CV too high to gate)")

    verdict = "no decision"
    if med_d <= -a.decide_pct and frac_neg >= a.consistency:
        verdict = "reward helps"
    elif med_d >= a.decide_pct and (1 - frac_neg) >= a.consistency:
        verdict = "reward hurts"
    print()
    if verdict == "reward helps" and med_vx < 100 * (VX_FLOOR - 1):
        print(f"CAUTION: yaw improved but the control arm is slower ({med_vx:+.2f}%): "
              f"the win may be bought by walking less. Check per-ckpt vx before shipping.")
    print(f"VERDICT: {verdict}")
    if verdict == "no decision":
        print(f"  (needs |median d_yaw| >= {a.decide_pct:.0f}% and >= "
              f"{a.consistency:.0%} consistency in one direction)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
