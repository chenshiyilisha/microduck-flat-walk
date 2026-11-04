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
              = "how much smaller A's yaw tracking error is than B's"
              error_vel_yaw is |cmd_wz - actual_wz| averaged over the window
              (mjlab velocity_command._update_metrics), so SMALLER IS BETTER
              and d > 0 means the reward arm A is the better one.
  verdict   = "reward helps"  if median(d) >= +10% and at least 80% of pairs
                               have d > 0
              "reward hurts"  if median(d) <= -10% and >= 80% of pairs have d < 0
              "no decision"   otherwise
  guard     = the arm is only declared the winner if its vx is not below
              0.97x the control arm's median vx at the same iterations (an
              err_yaw win bought by standing still is not a win -- the same
              "no speed regression" rule gate_p3_yaw.py applies to baselines)

The sign of d and the direction of the verdict were BOTH inverted in the first
version of this file (it read d < 0 as "B better, therefore reward helps", which
is the opposite of what d measures, and the vx guard fired when the control arm
was SLOWER rather than when the reward arm was). Fixed 2026-11-04 before any real
data was run through it; `--selftest` builds synthetic arms where the answer is
known and fails if the verdict points the wrong way.

10% is the pre-registered effect size because single-eval noise on err_yaw is
CV 1.2-2.6% (three repeats, artifacts/flat_walk/evals/p2_yaw/) and the paired
difference at the same iteration is tighter than that, while the effect the
reward is supposed to have (1.20 -> 0.73 rad/s on the kp8 reference point) is
~39%. A 10% bar cannot be cleared by luck and is nowhere near the effect size.

abs_dy / dx_over_expected are printed but never gated: CV 15-25%, and N=10
checkpoints of ONE seed does not fix that (measured 2026-11-03).

Degraded pairs are REPORTED, never used to change the verdict
-------------------------------------------------------------
A checkpoint can look good on err_yaw because the robot is not walking at all
(err_yaw is an error against a yaw command; a robot that has fallen holds no
heading and gets a small |cmd_wz - actual_wz| by accident). The first real
sweep had exactly this: model_300 arm A fell in 91% of envs, walked at 0.046
m/s against a 0.4 m/s command, and scored d_yaw = +221% -- one such pair moves
the median from +0.18% to +5.87%.

So every pair is checked against two thresholds that come from OUTSIDE this
comparison -- the termination counter, and the frozen kp8 reference baseline
measured before this A/B existed (vx 0.1629 at cmd 0.4, 3 seeds,
artifacts/flat_walk/evals/p8head_ref/). A threshold cannot be derived from the
quantity it is supposed to judge:
  vx < 0.5 * WALK_REF_VX    -- walks less than half of what this plant's own
                               reference achieves
  terminated_frac >= 0.5    -- more than half the envs ended early
The first version used "vx < 0.5 * cmd_vx" (0.2 m/s) and flagged 10/10 pairs:
on kp8, 0.4 m/s is simply not reachable (the reference itself tracks 41%), so
the bar said "nobody here is walking" about the whole sweep. A bar that is
always red is as broken as one that is always green.

Matching pairs are listed, and the median d_yaw of the REST is printed next to
the pre-registered one. The verdict keeps using ALL pairs: dropping data after
seeing it would make the pre-registered rule meaningless. The filtered number
is there so that a reader can tell "the arm is better" from "the arm stopped
walking", which is the only thing this test can be fooled by.

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
# "the robot is not walking" thresholds, for the degraded-pair report only.
# WALK_REF_VX is the frozen kp8 baseline (3 seeds, cmd 0.4, artifacts/flat_walk/
# evals/p8head_ref/), NOT a number read off the pairs being judged.
WALK_REF_VX = 0.1629
DEG_VX_OF_REF = 0.50      # vx below half of what this plant's reference achieves
DEG_TERM = 0.50           # more than half the envs terminated early


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


def _mk_arm(root: Path, tag: str, role: str, errs, vxs, *, iters, cmd_vx=0.25,
            is_true_mean=True) -> Path:
    """Build one synthetic arm: a run dir (for arm_identity) + matching eval JSONs."""
    run = root / f"run_{tag}"
    (run / "params").mkdir(parents=True, exist_ok=True)
    key = "track_heading" if role == "rewards" else "track_lin_vel_xy"
    (run / "params" / "env.yaml").write_text("rewards:\n  " + key + ": 1.0\n",
                                             encoding="utf-8")
    ev = root / f"eval_{tag}"
    ev.mkdir(parents=True, exist_ok=True)
    for it, e, v in zip(iters, errs, vxs):
        rec = {
            "checkpoint": str(run / f"model_{it}.pt"),
            "seed": 42,
            "num_envs": 1024,
            "seconds": 20.0,
            "command": {"vx": cmd_vx},
            "plant_fingerprint": {"name": "hd1910_kp8", "kwargs": {"kp_fw": 8},
                                  "source_sha256_12": "0123456789ab",
                                  "json_sha256_12": "ba9876543210"},
            "metric_window": {"is_true_mean": is_true_mean},
            "official_metrics": {"error_vel_yaw": e, "error_vel_xy": 0.30},
            "speed": {"vx_mean": v},
            "stability": {"terminated_frac": 0.0},
            "displacement": {"abs_dy_body_median": 0.10, "dx_over_expected": 0.90},
        }
        (ev / f"model_{it}.json").write_text(json.dumps(rec), encoding="utf-8")
    return ev


def selftest() -> int:
    """Synthetic arms with a known answer. Fails if the sign ever flips again."""
    import shutil
    import subprocess
    import tempfile

    iters = [500, 1000, 1500, 2000, 2500, 3000]
    shape = [1.00, 0.95, 1.05, 1.00, 0.90, 1.02]
    E = lambda s: [s * x for x in shape]   # noqa: E731
    V = lambda s: [s * x for x in shape]   # noqa: E731
    R, C = "rewards", "control"

    def probe(arm_a: dict, arm_b: dict) -> tuple[int, str]:
        root = Path(tempfile.mkdtemp(prefix="abself_"))
        try:
            da = _mk_arm(root, "A", arm_a["role"], arm_a["err"], arm_a["vx"],
                         iters=iters, cmd_vx=arm_a.get("cmd_vx", 0.25),
                         is_true_mean=arm_a.get("is_true_mean", True))
            db = _mk_arm(root, "B", arm_b["role"], arm_b["err"], arm_b["vx"],
                         iters=iters, cmd_vx=arm_b.get("cmd_vx", 0.25),
                         is_true_mean=arm_b.get("is_true_mean", True))
            r = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--a-dir", str(da), "--b-dir", str(db)],
                capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        finally:
            shutil.rmtree(root, ignore_errors=True)

    cases = [
        ("A 的 yaw 误差小 25% (d=+33%) -> helps", 0, "VERDICT: reward helps", False, False,
         dict(role=R, err=E(0.75), vx=V(1.00)),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("A 的 yaw 误差大 30% (d=-23%) -> hurts", 0, "VERDICT: reward hurts", False, False,
         dict(role=R, err=E(1.30), vx=V(1.00)),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("两臂只差 1% -> no decision", 2, "VERDICT: no decision", False, False,
         dict(role=R, err=E(0.99), vx=V(1.00)),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("A 好但慢 11% -> helps 且必须 CAUTION", 0, "VERDICT: reward helps", True, False,
         dict(role=R, err=E(0.75), vx=V(0.90)),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("A 好且更快 -> helps 且不得 CAUTION", 0, "VERDICT: reward helps", False, False,
         dict(role=R, err=E(0.75), vx=V(1.10)),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        # 正常的 kp8 配对（cmd 0.4 下只能走 0.163）绝不能被判成"不走路"。
        # 第一版阈值用 0.5*cmd=0.2，把真扫点的 10/10 全标了红，就是这条漏了。
        ("正常 kp8 速度 -> 不得 WARNING", 0, "VERDICT: reward helps", False, False,
         dict(role=R, err=E(0.75), vx=[0.1629 * x for x in shape]),
         dict(role=C, err=E(1.00), vx=[0.1629 * x for x in shape])),
        # 一个配对里 A 几乎站着不动：它的 err_yaw 是假象。
        # 必须打出 WARNING + 剔除后的中位数，而判决仍按全部配对算。
        ("A 有一个配对不走路 -> 必须 WARNING，判决不变",
         0, "VERDICT: reward helps", False, True,
         dict(role=R, err=E(0.75), vx=[0.05] + V(1.00)[1:]),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("eval 设置不同 -> 完整性退出 3", 3, "eval settings differ", False, False,
         dict(role=R, err=E(0.75), vx=V(1.00), cmd_vx=0.30),
         dict(role=C, err=E(1.00), vx=V(1.00))),
        ("两臂标反 -> 完整性退出 3", 3, "not the two arms", False, False,
         dict(role=C, err=E(0.75), vx=V(1.00)),
         dict(role=R, err=E(1.00), vx=V(1.00))),
        ("is_true_mean=false -> 完整性退出 3", 3, "is_true_mean is false", False, False,
         dict(role=R, err=E(0.75), vx=V(1.00), is_true_mean=False),
         dict(role=C, err=E(1.00), vx=V(1.00))),
    ]

    bad = 0
    for name, want_exit, want_text, want_caution, want_warn, arm_a, arm_b in cases:
        code, out = probe(arm_a, arm_b)
        found_text = want_text in out
        caution = "CAUTION:" in out
        warn = "WARNING: " in out and "pairs are degraded" in out
        ok = ((code == want_exit) and found_text and (caution == want_caution)
              and (warn == want_warn))
        bad += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         exit={code} (want {want_exit})  text={found_text}  "
                  f"caution={caution} (want {want_caution})  "
                  f"warn={warn} (want {want_warn})")
            for ln in out.splitlines():
                if ln.startswith(("VERDICT", "CAUTION", "WARNING", "median d_yaw",
                                  "  median d_yaw", "INTEGRITY")):
                    print(f"         | {ln}")

    print(f"  self-checks: {len(cases) - bad}/{len(cases)} pass")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir")
    ap.add_argument("--b-dir")
    ap.add_argument("--selftest", action="store_true",
                    help="用合成两臂验判决方向（负对照，不需要真实 eval）")
    ap.add_argument("--decide-pct", type=float, default=DECIDE_PCT)
    ap.add_argument("--consistency", type=float, default=CONSISTENCY)
    ap.add_argument("--min-pairs", type=int, default=MIN_PAIRS)
    ap.add_argument("--walk-ref-vx", type=float, default=WALK_REF_VX,
                    help="vx this plant's frozen reference baseline achieves at the "
                         "same command; only used to report degraded pairs")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.a_dir and a.b_dir):
        ap.error("--a-dir and --b-dir are required unless --selftest")

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

    ds, dvx, n_pos, n_neg = [], [], 0, 0
    degraded = []
    for k in common:
        ea, eb = ra[k], rb[k]
        ya = ea["official_metrics"]["error_vel_yaw"]
        yb = eb["official_metrics"]["error_vel_yaw"]
        va, vb = ea["speed"]["vx_mean"], eb["speed"]["vx_mean"]
        fa, fb = ea["stability"]["terminated_frac"], eb["stability"]["terminated_frac"]
        d = 100.0 * (yb - ya) / ya if ya else float("nan")    # >0 => A is better
        dv = 100.0 * (vb - va) / va if va else float("nan")   # >0 => B is faster
        ds.append(d)
        dvx.append(dv)
        if d > 0:
            n_pos += 1
        else:
            n_neg += 1
        why = []
        vmin = min(va, vb)
        if vmin < DEG_VX_OF_REF * a.walk_ref_vx:
            why.append(f"vx {vmin:.4f} < {DEG_VX_OF_REF:.2f}x walk ref "
                       f"{a.walk_ref_vx:.4f}")
        if max(fa, fb) >= DEG_TERM:
            why.append(f"terminated {max(fa, fb):.2f} >= {DEG_TERM:.2f}")
        if why:
            degraded.append((k, d, "; ".join(why)))
        print(f"{k:5d} | {ya:9.4f} {va:6.4f} | {yb:9.4f} {vb:6.4f} | {d:+7.2f} {dv:+7.2f} "
              f"{fa:4.2f}/{fb:4.2f}")

    n = len(common)
    med_d, med_vx = st.median(ds), st.median(dvx)
    frac_pos = n_pos / n
    print()
    print(f"paired checkpoints: {n}")
    print(f"median d_yaw = {med_d:+.2f}%   (A/rewards better in {n_pos}/{n} = "
          f"{frac_pos:.0%}; d>0 means A's yaw error is smaller)")
    print(f"median d_vx  = {med_vx:+.2f}%   (guard: A must not be slower than B by "
          f"more than {100 * (1 / VX_FLOOR - 1):.1f}%)")

    # A pair where an arm is not walking makes its err_yaw meaningless: report
    # it, and show the median of the rest, but never re-decide on the subset.
    if degraded:
        deg_keys = {k for k, _, _ in degraded}
        kept_d = [d for k, d in zip(common, ds) if k not in deg_keys]
        print()
        print(f"WARNING: {len(degraded)}/{n} pairs are degraded (an arm is not walking, "
              f"so its err_yaw is not a heading error):")
        for k, d, why in degraded:
            print(f"  model_{k}: {why}  ->  d_yaw {d:+.2f}% is an artefact")
        if kept_d:
            print(f"  median d_yaw on the remaining {len(kept_d)} pairs: "
                  f"{st.median(kept_d):+.2f}%   <-- post-hoc, NOT the verdict")

    # secondary, reported not gated
    for name, get in (("err_xy", lambda r: r["official_metrics"]["error_vel_xy"]),
                      ("abs_dy", lambda r: r["displacement"]["abs_dy_body_median"]),
                      ("dx_ratio", lambda r: r["displacement"]["dx_over_expected"])):
        xa = [get(ra[k]) for k in common]
        xb = [get(rb[k]) for k in common]
        print(f"  {name:9s} A median {st.median(xa):.4f}  B median {st.median(xb):.4f}  "
              f"(CV too high to gate)")

    verdict = "no decision"
    if med_d >= a.decide_pct and frac_pos >= a.consistency:
        verdict = "reward helps"
    elif med_d <= -a.decide_pct and (1 - frac_pos) >= a.consistency:
        verdict = "reward hurts"
    print()
    if verdict == "reward helps" and med_vx > 100 * (1 / VX_FLOOR - 1):
        print(f"CAUTION: yaw improved but the reward arm is slower "
              f"({-med_vx:+.2f}% vs the control arm): the win may be bought by walking "
              f"less. Check per-ckpt vx before shipping.")
    print(f"VERDICT: {verdict}")
    if verdict == "no decision":
        print(f"  (needs |median d_yaw| >= {a.decide_pct:.0f}% and >= "
              f"{a.consistency:.0%} consistency in one direction)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
