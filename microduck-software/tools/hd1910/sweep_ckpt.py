#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Pick a checkpoint by fixed-condition evaluation -- rsl_rl has no best-by-eval.

Why this file exists
--------------------
`model_1999.pt` is where training *stopped*, not where it peaked. rsl_rl keeps no
"best so far" model, so the only honest way to choose a delivery checkpoint is to
measure several of them at conditions that do not move underneath the measurement.
The training log cannot answer this: `Metrics/twist/error_vel_xy` climbs while
reward climbs, because the curriculum is widening the command range and 30% of the
envs run the heading loop -- that is a harder task, not a worse policy.

What makes the comparison valid
-------------------------------
* **Same plant.** `--plant default` means the task's own actuator, i.e. whatever
  `microduck_constants._BAM_ACTUATOR_KWARGS` currently holds (P3 `hd1910_kp5`).
  `plant_id`'s fingerprint is copied into every row so a mismatch is visible
  instead of silent -- cfg/mdp hashes do not cover the actuator, which lives one
  import deeper.
* **Same window.** `eval_velocity_in_sim.freeze_command` pins
  `resampling_time_range = (duration, duration)`, so `error_vel_xy` is a true
  m/s mean and `metric_window.is_true_mean` is checked, not assumed.
* **Same initial draw.** One `--seed` for every checkpoint, so a difference
  between two models is a difference between two policies rather than between two
  sets of reset states. (MJWarp is not bit-reproducible past ~20 steps, so this
  removes the initial-condition lottery, not the trajectory noise; repeat with
  another seed before believing a gap smaller than the spread between seeds.)

Outputs
-------
`<out>/<ckpt>_vx<cmd>_wz<cmd>.json` per run (full eval payload), plus
`summary.csv` and a markdown table on stdout. Existing json is reused unless
`--force`, so an interrupted sweep resumes instead of restarting.

Usage:
  .venv-mjlab/Scripts/python.exe tools/hd1910/sweep_ckpt.py \
      --ckpt-dir logs/rsl_rl/microduck_velocity_hd1910/2026-11-02_09-28-18_p3head030_4096x2000 \
      --ckpts 1400,1600,1800,1900,1999 --cmds 0.3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "tools" / "eval_velocity_in_sim.py"


def discover(ckpt_dir: Path) -> list[int]:
    its = []
    for p in ckpt_dir.glob("model_*.pt"):
        m = re.fullmatch(r"model_(\d+)\.pt", p.name)
        if m:
            its.append(int(m.group(1)))
    return sorted(its)


def run_one(ckpt: Path, vx: float, wz: float, a, out: Path) -> dict | None:
    # The filename carries the instrument (envs, seconds, seed), not just the
    # condition: two readings taken with different instruments are not comparable,
    # so a cache keyed only on (ckpt, cmd) would silently serve a 64-env number
    # where a 256-env one was asked for.
    tag = (f"{ckpt.stem}_vx{vx:.2f}_wz{wz:.2f}"
           f"_n{a.num_envs}_s{a.seconds:g}_g{a.seed}")
    js = out / f"{tag}.json"
    log = out / f"{tag}.log"
    if js.exists() and not a.force:
        print(f"[cached] {tag}", flush=True)
        return json.loads(js.read_text(encoding="utf-8"))

    cmd = [
        sys.executable, str(EVAL),
        "--checkpoint", str(ckpt),
        "--num-envs", str(a.num_envs),
        "--seconds", str(a.seconds),
        "--cmd-vx", str(vx),
        "--cmd-wz", str(wz),
        "--plant", a.plant,
        "--seed", str(a.seed),
        "--out", str(js),
    ]
    env = dict(os.environ)
    env.setdefault("MUJOCO_GL", "glfw")
    print(f"[run] {tag}  ({a.num_envs} envs x {a.seconds:.0f}s)", flush=True)
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env,
                              stdout=fh, stderr=subprocess.STDOUT)
    if not js.exists():
        print(f"[FAIL] {tag}: eval produced no json (rc={proc.returncode}); see {log}",
              flush=True)
        return None
    r = json.loads(js.read_text(encoding="utf-8"))
    # The eval tool exits 1 on any failed gate. That is a reading, not an error:
    # an unlucky checkpoint is allowed to be bad, and dropping it would bias the pick.
    if proc.returncode != 0:
        print(f"[warn] {tag}: gates not all green (rc={proc.returncode})", flush=True)
    return r


def row(r: dict, ckpt: Path, vx: float, wz: float) -> dict:
    om = r.get("official_metrics") or {}
    st = r.get("stability") or {}
    sp = r.get("speed") or {}
    mw = r.get("metric_window") or {}
    fp = r.get("plant_fingerprint") or {}
    gates = r.get("gates") or {}
    # Added 2026-11-02: achieved joint amplitude, for comparing against the plant's
    # own ceiling. Absent in readings taken before the instrument existed -> None,
    # which prints as n/a rather than 0 (a zero would read as "the legs are frozen").
    jo = r.get("joints") or {}
    failed = sorted(k for k, v in gates.items() if v is False)
    vx_med = sp.get("vx_median_of_env_means")
    return {
        "ckpt": ckpt.stem,
        "iter": int(ckpt.stem.split("_")[1]),
        "cmd_vx": vx,
        "cmd_wz": wz,
        "vx_median": vx_med,
        "ratio": (vx_med / vx) if (vx_med is not None and vx) else None,
        "err_xy": om.get("error_vel_xy"),
        "err_yaw": om.get("error_vel_yaw"),
        "fall_pct": (st.get("terminated_frac") * 100) if st.get("terminated_frac") is not None else None,
        "upright_min": st.get("upright_min"),
        "window_ok": mw.get("is_true_mean"),
        "gates_failed": ",".join(failed),
        "plant": fp.get("name") or fp.get("detected"),
        "amp_deg": jo.get("amp_deg_median_max"),
        "amp_joint": jo.get("amp_deg_median_max_joint"),
        "peak_dq": jo.get("peak_vel_rad_s_max"),
    }


def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def show(rows: list[dict]) -> None:
    print()
    hdr = ("ckpt", "cmd", "vx", "ratio", "err_xy", "err_yaw", "fall%", "upr_min",
           "amp°", "dq", "failed gates")
    print("| " + " | ".join(hdr) + " |")
    print("|" + "|".join(["---"] * len(hdr)) + "|")
    for r in rows:
        print("| {} | {:.2f} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["ckpt"], r["cmd_vx"], fmt(r["vx_median"]), fmt(r["ratio"], 2),
            fmt(r["err_xy"]), fmt(r["err_yaw"]), fmt(r["fall_pct"], 1),
            fmt(r["upright_min"], 4),
            fmt(r["amp_deg"], 1), fmt(r["peak_dq"], 2),
            r["gates_failed"] or "-"))
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt-dir", required=True)
    ap.add_argument("--ckpts", default="",
                    help="comma list of iteration numbers; empty = last N of the dir")
    ap.add_argument("--last", type=int, default=5, help="how many to take when --ckpts empty")
    ap.add_argument("--cmds", default="0.3", help="comma list of --cmd-vx values")
    ap.add_argument("--wz-cmds", default="", help="extra yaw commands run at vx=0.3")
    ap.add_argument("--num-envs", type=int, default=256)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--plant", default="default")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    ckpt_dir = Path(a.ckpt_dir)
    if not ckpt_dir.is_absolute():
        ckpt_dir = (ROOT / ckpt_dir).resolve()
    if not ckpt_dir.exists():
        raise SystemExit(f"no such ckpt dir: {ckpt_dir}")

    have = discover(ckpt_dir)
    if a.ckpts:
        its = [int(x) for x in a.ckpts.split(",") if x.strip()]
        missing = [i for i in its if i not in have]
        if missing:
            raise SystemExit(f"missing checkpoints {missing}; dir has {have}")
    else:
        its = have[-a.last:]

    cmds = [float(x) for x in a.cmds.split(",") if x.strip()]
    wzs = [float(x) for x in a.wz_cmds.split(",") if x.strip()]
    out = Path(a.out) if a.out else ROOT / "out" / f"sweep_{ckpt_dir.name}"
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"ckpt dir   {ckpt_dir}")
    print(f"iters      {its}")
    print(f"conditions vx={cmds}  wz(extra, vx=0.3)={wzs or '-'}")
    print(f"budget     {a.num_envs} envs x {a.seconds:.0f}s, seed {a.seed}, plant {a.plant}")
    print(f"out        {out}", flush=True)

    rows: list[dict] = []
    for it in its:
        ckpt = ckpt_dir / f"model_{it}.pt"
        for vx in cmds:
            r = run_one(ckpt, vx, 0.0, a, out)
            if r is not None:
                rows.append(row(r, ckpt, vx, 0.0))
        for wz in wzs:
            r = run_one(ckpt, 0.3, wz, a, out)
            if r is not None:
                rows.append(row(r, ckpt, 0.3, wz))

    if not rows:
        raise SystemExit("no rows; every eval failed -- read the per-run .log files")

    plants = sorted({r["plant"] for r in rows})
    if len(plants) > 1:
        print(f"!! plant fingerprint differs across runs: {plants}", flush=True)
    bad_win = [r["ckpt"] for r in rows if r["window_ok"] is False]
    if bad_win:
        print(f"!! metric window is not a true mean for {bad_win}", flush=True)

    show(rows)

    csv = out / "summary.csv"
    keys = list(rows[0].keys())
    with csv.open("w", encoding="utf-8", newline="") as fh:
        import csv as _csv
        w = _csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {csv}")

    # Ranking is deliberately explicit rather than a single score: falling is a
    # different failure from tracking badly, and one stalled env should not be
    # hidden by a good mean (hence ratio next to err, never err alone).
    def key(r):
        fall = 99.0 if r["fall_pct"] is None else r["fall_pct"]
        err = 9.9 if r["err_xy"] is None else r["err_xy"]
        return (fall, err)

    same = [r for r in rows if abs(r["cmd_vx"] - cmds[0]) < 1e-9 and r["cmd_wz"] == 0.0]
    if len(same) > 1:
        print(f"\nranked at vx={cmds[0]:.2f} (fall first, then error_vel_xy):")
        for i, r in enumerate(sorted(same, key=key), 1):
            print(f"  {i}. {r['ckpt']}  fall {fmt(r['fall_pct'],1)}%  "
                  f"err_xy {fmt(r['err_xy'])}  ratio {fmt(r['ratio'],2)}  "
                  f"err_yaw {fmt(r['err_yaw'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
