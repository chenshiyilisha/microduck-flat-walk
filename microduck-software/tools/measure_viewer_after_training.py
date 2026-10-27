"""Wait for the running training job to finish, then measure viewer step cost
with the GPU to itself.

Why this has to wait: the 5 fps reading is a *contended* measurement. Training
holds 98 % of the GPU, so every CUDA graph launch the viewer submits sits behind
a queued training kernel. To say "the viewer will be smooth once training ends"
is a prediction, and predictions in this project get measured before they are
believed.

Sequence:
  1. Poll the training log until it reports the final iteration (or the process
     exits), so we do not measure while a straggler checkpoint is being written.
  2. Suspend the viser viewer. It is the thing being measured; leaving it running
     would make it contend with the profiler and halve both. Suspending (not
     killing) keeps the browser session and camera pose intact.
  3. Run tools/profile_joy_viewer_step.py for 1 and 64 envs, then resume.

The output lands in out/viewer_uncontended.txt so the number survives the
conversation.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv-mjlab" / "Scripts" / "python.exe"
LOG = ROOT / "out" / "train_joy_smooth_2048x600_1024_std012.log"


def training_done(log: pathlib.Path, total_iters: int) -> tuple[bool, int]:
    if not log.exists():
        return False, 0
    n = 0
    with log.open("rb") as fh:
        for line in fh:
            if b"Learning iteration" in line:
                n += 1
    return n >= total_iters, n


def viewer_pids():
    import psutil

    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "mjlab.scripts.play" in cl:
            out.append((p.info["pid"], cl[:100]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=pathlib.Path, default=LOG)
    ap.add_argument("--total-iters", type=int, default=600)
    ap.add_argument("--poll", type=float, default=15.0)
    ap.add_argument("--max-poll", type=float, default=5400.0)
    args = ap.parse_args()

    t0 = time.time()
    while True:
        done, n = training_done(args.log, args.total_iters)
        if done:
            print(f"[wait] training reached {n} iterations after {time.time() - t0:.0f}s", flush=True)
            break
        if time.time() - t0 > args.max_poll:
            print(f"[wait] gave up after {args.max_poll:.0f}s at iter {n}; aborting", flush=True)
            return 1
        time.sleep(args.poll)

    # Let the final checkpoint write and the CUDA context tear down.
    time.sleep(25)

    # Suspend rather than kill: the viewer keeps its clocked clock, camera pose and
    # the browser session stays connected, so the operator only sees a ~90 s freeze
    # instead of losing the whole page. Resumed in the `finally` below even if the
    # profiling step blows up.
    import psutil

    suspended: list = []
    for pid, cl in viewer_pids():
        print(f"[pause] viewer pid={pid}  {cl}", flush=True)
        try:
            p = psutil.Process(pid)
            p.suspend()
            suspended.append(p)
        except Exception as exc:  # noqa: BLE001
            print(f"[pause] failed on {pid}: {exc}", flush=True)
    time.sleep(8)

    ckpts = sorted(
        (ROOT / "logs" / "rsl_rl" / "microduck_joy_smooth").glob("*std012*/model_*.pt"),
        key=lambda p: p.stat().st_mtime,
    )
    if not ckpts:
        print("[profile] no checkpoint found", flush=True)
        return 1
    ckpt = ckpts[-1]
    print(f"[profile] checkpoint {ckpt.relative_to(ROOT)}", flush=True)

    out = ROOT / "out" / "viewer_uncontended.txt"
    cmd = [
        str(PY),
        str(ROOT / "tools" / "profile_joy_viewer_step.py"),
        "--checkpoint",
        str(ckpt),
        "--num-envs",
        "1",
        "64",
        "--repeat",
        "30",
    ]
    try:
        with out.open("w", encoding="utf-8") as fh:
            r = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            fh.write(r.stdout + "\n--- stderr tail ---\n" + r.stderr[-2000:])
        for line in r.stdout.splitlines():
            if line.startswith("envs=") or "LAUNCH" in line or "compute-bound" in line:
                print(line, flush=True)
        print(f"[profile] written to {out.relative_to(ROOT)}", flush=True)
    finally:
        for p in suspended:
            try:
                p.resume()
                print(f"[resume] viewer pid={p.pid} (reload the page if it looks frozen)", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[resume] failed on {p.pid}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
