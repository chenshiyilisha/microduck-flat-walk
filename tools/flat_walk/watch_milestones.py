#!/usr/bin/env python
"""Watch a LIVE velocity run, evaluate milestone checkpoints, stop if flat.

Why this exists
---------------
The 4096x12000 run (`vel_4096x12000_1025`) is expected to finish around 19:00.
We already have a good policy at iter 1250 (`out/eval_iter1250_v2.json`:
error_vel_xy 0.194, vx 0.258 m/s, 10/10 gates).  The open question is only
whether more iterations still buy anything.  So: evaluate at 4000, compare
against 1250, and if it is flat, stop the run at 6000 (saves ~5 h of GPU).

Everything here is read-only with respect to the training run until the very
last step (`--stop-pid`, only when the verdict is flat).  Evaluating does NOT
disturb training: it is a separate process, and this exact combination
(train 4096 envs + eval 32 envs, same 8 GB GPU) already ran at 09:31 while the
run was going -- `model_1250.pt` was evaluated mid-flight.  Training used
3.6 GB, 4.3 GB stayed free.

Comparability notes
-------------------
* Baseline and milestones must use the SAME eval flags or the numbers are not
  comparable: --num-envs 32 --seconds 8 --device cuda:0 --cmd-vx 0.4
  --solver-iters 100 --solver-ls 50.
* `error_vel_xy` from the eval harness overestimates by ~3x for this task
  (five-mode command mix + whole-episode accumulation); it is only meaningful
  as a monotone trend against the same harness, never against the value in the
  training log (0.42-0.43, which upstream also reports at 5000-6000 it).
* Verdict thresholds live in `verdict()` below and are printed, so a later
  reader can audit the decision instead of guessing it.

Usage
-----
  python tools/watch_milestones.py                       # 4000 + 6000, no stop
  python tools/watch_milestones.py --stop-pid 23760      # stop at 6000 if flat
  python tools/watch_milestones.py --targets 4000       # single milestone
  python tools/watch_milestones.py --dry-run            # print the plan, exit

Outputs: out/eval_iter<N>.json, out/eval_iter<N>.log,
         out/milestone_verdict.json, out/watch_milestones.status.json,
         out/watch_milestones.log
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv-mjlab", "Scripts", "python.exe")
EXP = "microduck_velocity"
RUNS = os.path.join(ROOT, "logs", "rsl_rl", EXP)
OUT = os.path.join(ROOT, "out")

ITER_RE = re.compile(r"Learning iteration (\d+)/(\d+)")


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, fh=None) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    if fh is not None:
        fh.write(line + "\n")
        fh.flush()


def newest_run() -> str:
    cands = [
        d for d in os.listdir(RUNS)
        if os.path.isdir(os.path.join(RUNS, d)) and not d.endswith("_smoke")
    ]
    cands.sort(key=lambda d: os.path.getmtime(os.path.join(RUNS, d)))
    if not cands:
        sys.exit(f"no run dirs under {RUNS}")
    return cands[-1]


def resolve_log(run_dir_name: str) -> str:
    """Map an mjlab run dir (timestamped) to the wrapper's log file.

    mjlab creates `logs/rsl_rl/<exp>/2026-10-25_08-10-20_<run-name>` while
    `tools/train_velocity.sh` writes `out/train_<run-name>.log` (no timestamp),
    so the timestamp prefix has to be stripped before looking the log up.
    """
    m = re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(?P<name>.+)$", run_dir_name)
    run_name = m.group("name") if m else run_dir_name
    exact = os.path.join(OUT, f"train_{run_name}.log")
    if os.path.exists(exact):
        return exact
    # fall back to a glob on the suffix, newest wins
    import glob
    cands = glob.glob(os.path.join(OUT, f"train_*{run_name}*.log"))
    if cands:
        cands.sort(key=os.path.getmtime)
        return cands[-1]
    return exact


def latest_iter(log_path: str) -> int:
    """Last 'Learning iteration N/M' in the log; 0 if none yet."""
    if not os.path.exists(log_path):
        return 0
    got = 0
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        # tail-ish read: the file is a few MB, full read is fine and simpler
        for line in f:
            m = ITER_RE.search(line)
            if m:
                got = int(m.group(1))
    return got


def wait_for_ckpt(ckpt: str, target: int, log_path: str, poll: int, fh) -> bool:
    """Block until model_<target>.pt exists AND is not still being written."""
    last_size = -1
    while True:
        if os.path.exists(ckpt):
            size = os.path.getsize(ckpt)
            if size == last_size and size > 1_000_000:
                return True
            last_size = size
        it = latest_iter(log_path)
        log(f"waiting for {os.path.basename(ckpt)} (train at iter {it}/{target})", fh)
        time.sleep(poll)


def run_eval(run_dir: str, ckpt: str, out_json: str, num_envs: int, seconds: float,
             cmd_vx: float, solver_iters: int, solver_ls: int, fh) -> dict:
    ckpt_rel = os.path.relpath(ckpt, ROOT).replace("\\", "/")
    cmd = [
        PY, os.path.join("tools", "eval_velocity_in_sim.py"),
        "--checkpoint", ckpt_rel,
        "--num-envs", str(num_envs),
        "--seconds", str(seconds),
        "--device", "cuda:0",
        "--cmd-vx", str(cmd_vx),
        "--solver-iters", str(solver_iters),
        "--solver-ls", str(solver_ls),
        "--out", os.path.relpath(out_json, ROOT).replace("\\", "/"),
    ]
    log("eval: " + " ".join(cmd[1:]), fh)
    t0 = time.time()
    log_path = out_json.replace(".json", ".log")
    with open(log_path, "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT,
                              timeout=3600)
    dt = time.time() - t0
    if proc.returncode != 0:
        tail = ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                tail = "".join(lf.readlines()[-12:])
        except OSError:
            pass
        log(f"eval FAILED rc={proc.returncode} after {dt:.0f}s; tail:\n{tail}", fh)
        return {"error": f"rc={proc.returncode}", "seconds": dt}
    with open(out_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    log(f"eval ok in {dt:.0f}s -> {os.path.basename(out_json)}", fh)
    return data


def verdict(cur: dict, base: dict) -> dict:
    """Improved / flat against the 1250 baseline.  Thresholds are explicit."""
    if "error" in cur:
        return {"decision": "eval-failed", "reason": cur["error"]}
    b_err = base["official_metrics"]["error_vel_xy"]
    c_err = cur["official_metrics"]["error_vel_xy"]
    b_vx = base["speed"]["vx_median_of_env_means"]
    c_vx = cur["speed"]["vx_median_of_env_means"]
    failed = cur.get("failed") or []
    err_down = c_err < b_err * 0.97          # >=3% better
    speed_up = c_vx > b_vx * 1.05 and c_err <= b_err * 1.02   # >=5% faster, err not worse
    out = {
        "baseline_iter": 1250,
        "baseline_error_vel_xy": round(b_err, 4),
        "baseline_vx": round(b_vx, 4),
        "iter": cur.get("_iter"),
        "error_vel_xy": round(c_err, 4),
        "vx_median": round(c_vx, 4),
        "dx_body_mean": round(cur["displacement"]["dx_body_mean"], 3),
        "feet_peak_mm": round(cur["feet"]["both_peak_mm_median"], 2),
        "landings_hz": round(cur["feet"]["landings_per_foot_hz"], 2),
        "gates_failed": failed,
        "rule": "improved if error_vel_xy < 0.97*baseline OR (vx > 1.05*baseline and error <= 1.02*baseline); any failed gate => flat",
    }
    if failed:
        out["decision"] = "flat"
        out["reason"] = f"{len(failed)} gate(s) failed: {','.join(failed)}"
    elif err_down:
        out["decision"] = "improved"
        out["reason"] = f"error_vel_xy {b_err:.4f} -> {c_err:.4f} ({100*(c_err/b_err-1):+.1f}%)"
    elif speed_up:
        out["decision"] = "improved"
        out["reason"] = f"vx {b_vx:.4f} -> {c_vx:.4f} ({100*(c_vx/b_vx-1):+.1f}%), error not worse"
    else:
        out["decision"] = "flat"
        out["reason"] = (f"error_vel_xy {b_err:.4f} -> {c_err:.4f} "
                         f"({100*(c_err/b_err-1):+.1f}%), vx {b_vx:.4f} -> {c_vx:.4f}")
    return out


def stop_training(pid: int, fh) -> None:
    log(f"stopping training pid={pid} (checkpoints are already on disk)", fh)
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, text=True)
    time.sleep(5)
    chk = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True).stdout
    log("still alive" if str(pid) in chk else "training stopped", fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="run dir name (default: newest)")
    ap.add_argument("--targets", default="4000,6000")
    ap.add_argument("--baseline", default="out/eval_iter1250_v2.json")
    ap.add_argument("--num-envs", type=int, default=32)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--cmd-vx", type=float, default=0.4)
    ap.add_argument("--solver-iters", type=int, default=100)
    ap.add_argument("--solver-ls", type=int, default=50)
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--stop-pid", type=int, default=0,
                    help="kill this training pid at the LAST target, only if flat")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    run = args.run or newest_run()
    run_dir = os.path.join(RUNS, run)
    log_path = resolve_log(run)
    targets = [int(t) for t in args.targets.split(",") if t.strip()]
    base_path = os.path.join(ROOT, args.baseline)
    with open(base_path, "r", encoding="utf-8") as f:
        base = json.load(f)

    plan = {
        "run": run,
        "log": os.path.relpath(log_path, ROOT),
        "targets": targets,
        "baseline": args.baseline,
        "eval_flags": {
            "num_envs": args.num_envs, "seconds": args.seconds,
            "cmd_vx": args.cmd_vx, "solver_iters": args.solver_iters,
            "solver_ls": args.solver_ls, "device": "cuda:0",
        },
        "stop_pid": args.stop_pid or None,
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("dry-run: exiting")
        return 0

    status_path = os.path.join(OUT, "watch_milestones.status.json")
    verdict_path = os.path.join(OUT, "milestone_verdict.json")

    with open(os.path.join(OUT, "watch_milestones.log"), "a", encoding="utf-8") as fh:
        log(f"=== start run={run} targets={targets} stop_pid={args.stop_pid or '-'}", fh)
        results: list[dict] = []
        stopped = False
        for i, target in enumerate(targets):
            ckpt = os.path.join(run_dir, f"model_{target}.pt")
            out_json = os.path.join(OUT, f"eval_iter{target}.json")
            if os.path.exists(ckpt) and os.path.exists(out_json):
                log(f"model_{target}.pt + eval already present, reusing", fh)
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_iter"] = target
            else:
                status = {"stage": "waiting", "target": target,
                          "train_iter": latest_iter(log_path),
                          "updated": datetime.now().isoformat(timespec="seconds")}
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(status, f, indent=2)
                if not wait_for_ckpt(ckpt, target, log_path, args.poll, fh):
                    return 1
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump({"stage": "evaluating", "target": target,
                               "updated": datetime.now().isoformat(timespec="seconds")},
                              f, indent=2)
                data = run_eval(run_dir, ckpt, out_json, args.num_envs, args.seconds,
                                args.cmd_vx, args.solver_iters, args.solver_ls, fh)
                data["_iter"] = target
            v = verdict(data, base)
            results.append(v)
            log(f"iter {target}: {v['decision']} -- {v['reason']}", fh)
            with open(verdict_path, "w", encoding="utf-8") as f:
                json.dump({"run": run, "baseline": args.baseline,
                           "milestones": results, "stopped": stopped}, f,
                          indent=2, ensure_ascii=False)
            if i == len(targets) - 1 and args.stop_pid and not stopped:
                if all(r["decision"] == "flat" for r in results):
                    stop_training(args.stop_pid, fh)
                    stopped = True
                    with open(verdict_path, "w", encoding="utf-8") as f:
                        json.dump({"run": run, "baseline": args.baseline,
                                   "milestones": results, "stopped": stopped}, f,
                                  indent=2, ensure_ascii=False)
                else:
                    log("verdict improved -> training keeps running to 12000", fh)
        log("=== done", fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
