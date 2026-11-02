"""Stop a running training job by command-line match, then prove a usable checkpoint.

Why not just close the window: the trainer is a child of this session, and on Windows
a window close does not reliably take the whole tree with it. A leftover trainer keeps
the GPU and keeps adding iterations after the wall clock the user allowed.

What this does NOT do, and why it is safe
----------------------------------------
* It matches on the training script name *plus* the run name, and prints every match
  with its full command line before touching anything. No match -> exit 1, no kill.
* `--yes` is required to actually terminate. Without it this is a read-only listing.
* Nothing is saved on kill. rsl_rl writes a checkpoint every `save_interval`
  iterations, and that number is NOT the 50 from rsl_rl's defaults -- the MicroDuck
  task ships 250, so a hard stop can throw away up to 250 iterations (~16 min at
  15.5 iter/min). The interval is read back from the run's own params/agent.yaml and
  printed, together with the checkpoint actually left behind, instead of being
  assumed here.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import resume_heading_run as R  # noqa: E402  (same dir, tiny module)


def list_matches(pattern: str) -> list[tuple[int, str]]:
    """Return (pid, cmdline) for processes whose command line contains `pattern`."""
    me = os.getpid()
    out: list[tuple[int, str]] = []
    if os.name == "nt":
        ps = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like '*train_heading_variant.py*' } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        text = (r.stdout or "").strip()
        if not text:
            return []
        import json
        rows = json.loads(text)
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            cmd = row.get("CommandLine") or ""
            pid = int(row.get("ProcessId") or -1)
            if pattern in cmd and pid != me:
                out.append((pid, cmd))
    else:
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            pid = int(p.name)
            if pid == me:
                continue
            try:
                cmd = (p / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                    "utf-8", "replace")
            except OSError:
                continue
            if "train_heading_variant.py" in cmd and pattern in cmd:
                out.append((pid, cmd))
    return out


def save_interval(run_dir: Path) -> int | None:
    text = (run_dir / "params" / "agent.yaml").read_text(encoding="utf-8")
    m = re.search(r"^save_interval:\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else None


def report_checkpoint(run_dir: Path) -> None:
    ckpt, _ = R.latest_ckpt(run_dir)
    it, counter = R.read_state(ckpt)
    nse = R.num_steps_per_env(run_dir)
    ok = counter == (it + 1) * nse
    si = save_interval(run_dir)
    print(f"newest checkpoint: {ckpt.name}  iter={it}  counter={counter}  "
          f"coherent={'yes' if ok else 'NO'}")
    if si:
        print(f"save_interval={si}: the iterations after {it} up to the moment of the "
              f"kill are lost (at most {si} x 3.9 s ~ {si * 3.9 / 60:.0f} min of compute)")
    if not ok:
        print(f"  ! counter != (iter+1)x{nse} = {(it + 1) * nse}; "
              "resume_heading_run.py will refuse this checkpoint.")
    print(f"resume tomorrow: python tools/hd1910/resume_heading_run.py "
          f"--run-dir {run_dir} --launch")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", default="p3head_rw",
                    help="substring of the run name in the trainer's command line")
    ap.add_argument("--yes", action="store_true", help="actually terminate (default: list only)")
    ap.add_argument("--grace", type=float, default=20.0,
                    help="seconds to wait for the process to disappear")
    a = ap.parse_args()

    hits = list_matches(a.match)
    if not hits:
        print(f"no trainer process matching {a.match!r} -- nothing to stop")
        return 1

    print(f"{len(hits)} match(es) for {a.match!r}:")
    for pid, cmd in hits:
        run = re.search(r"--agent\.run-name\s+(\S+)", cmd)
        print(f"  pid {pid}  run={run.group(1) if run else '?'}")
        print(f"    {cmd[:160]}{'...' if len(cmd) > 160 else ''}")
    if len(hits) > 1:
        print("  (more than one process is expected: the venv launcher shim re-execs "
              "the real interpreter, so both share the command line -- all are stopped)")

    if not a.yes:
        print("\nread-only listing; re-run with --yes to terminate")
        return 0

    for pid, _ in hits:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"sent terminate to {pid}")
        except OSError as e:
            print(f"  could not terminate {pid}: {e}")

    t0 = time.time()
    while time.time() - t0 < a.grace:
        if not list_matches(a.match):
            print("trainer stopped")
            break
        time.sleep(1.0)
    else:
        print("! trainer still alive after grace period -- check GPU before resuming")
        return 1

    run_dir = R.latest_run()
    report_checkpoint(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
