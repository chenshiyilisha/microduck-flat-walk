#!/usr/bin/env python3
"""End-to-end gate for the ported `robotd --sim` seam.

Starts the real `mjlab_microduck/sim/body_server.py`, runs the compiled
`duck-control/tests/sim_e2e.rs` harness against it, then **kills the server and runs the same
harness again, requiring it to fail**.

That second run is the point. A test that silently talks to nothing, or whose assertions are all
vacuously true, would go green in both runs. Only a test that genuinely consumed live MuJoCo
frames can be green with the server up and red with it down. A *build* failure is deliberately
not counted as red: the negative control has to fail on the assertions, not on a missing linker.

The Rust build is a separate, explicit prerequisite (not hidden inside this script). On this
Windows machine there is no MSVC, so it uses the gnu target's self-contained lld plus a
`dlltool.exe` shim backed by Zig's `llvm-dlltool`; see
`docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md`. Build once, then gate many times:

    export PATH="$HOME/.cargo/bin:$HOME/.wb_tmp/tools:$PATH"
    export CARGO_TARGET_DIR="C:/Users/hejih/.wb_tmp/ct_dc5"
    export CARGO_INCREMENTAL=0
    export RUSTFLAGS="-C linker=rust-lld -C link-self-contained=yes"
    cd microduck-software/.upstream/DuckBuddy-main
    cargo +stable-x86_64-pc-windows-gnu test -p duck-control --test sim_e2e \
        --target x86_64-pc-windows-gnu --no-run

    # from the repo root
    CARGO_TARGET_DIR=<same> microduck-software/.venv-mjlab/Scripts/python.exe \
        microduck-software/tools/hd1910/sim_e2e_check.py

Exit 0 only when the live run passes AND the server-down run fails on its assertions.
"""

from __future__ import annotations

import argparse
import glob
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
SOFTWARE = HERE.parents[2]  # .../microduck-software
CRATE_DIR = SOFTWARE / ".upstream" / "DuckBuddy-main"
VENV_PY = SOFTWARE / ".venv-mjlab" / "Scripts" / "python.exe"
HOME = Path.home()
SERVER_LOG = HOME / ".wb_tmp" / "sim_e2e_server.log"


def log(msg: str) -> None:
    print(f"[sim_e2e] {msg}", flush=True)


def find_test_binary() -> Path | None:
    """Locate the compiled `sim_e2e` harness in CARGO_TARGET_DIR."""
    target = os.environ.get("CARGO_TARGET_DIR")
    if not target:
        log("MISSING: set CARGO_TARGET_DIR to the directory used for the build")
        return None
    pattern = os.path.join(target, "**", "deps", "sim_e2e-*")
    candidates = [
        Path(p) for p in glob.glob(pattern, recursive=True)
        if not p.endswith((".d", ".pdb", ".rmeta"))
    ]
    if not candidates:
        log(f"MISSING: no sim_e2e-* under {target}; run the cargo --no-run command first")
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def port_is_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_harness(exe: Path, env: dict[str, str], label: str) -> tuple[int, str]:
    cmd = [str(exe), "--ignored", "--nocapture", "--test-threads=1"]
    log(f"harness ({label}): {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, cwd=str(CRATE_DIR), env=env,
        capture_output=True, text=True, timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out[-6000:], flush=True)
    return proc.returncode, out


def start_server(port: int, env: dict[str, str]):
    cmd = [
        str(VENV_PY), "-m", "mjlab_microduck.sim.body_server",
        "--headless", "--port", str(port),
    ]
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log(f"starting body_server: {' '.join(cmd)}")
    handle = open(SERVER_LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd, cwd=str(SOFTWARE), env=env,
        stdout=handle, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            handle.flush()
            raise RuntimeError(
                f"body_server exited early (rc={proc.returncode}); see {SERVER_LOG}"
            )
        # TCP probe only: never send a frame, so the daemon's lazy hello is the first thing
        # the real test puts on the wire.
        if port_is_open(port):
            log(f"body_server listening on {port} (pid {proc.pid})")
            return proc, handle
        time.sleep(0.2)
    proc.terminate()
    handle.close()
    raise TimeoutError(f"body_server did not open port {port}; see {SERVER_LOG}")


def stop_server(proc, handle, port: int) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)
    handle.close()
    # Wait until the listening socket is really gone; otherwise the negative run could
    # connect to a dying server and pass for the wrong reason.
    deadline = time.time() + 10
    while time.time() < deadline and port_is_open(port):
        time.sleep(0.2)
    log("body_server stopped")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free loopback port")
    ap.add_argument("--test-exe", type=Path, default=None, help="override the harness path")
    args = ap.parse_args()

    exe = args.test_exe or find_test_binary()
    if exe is None or not exe.exists():
        return 2
    if not VENV_PY.exists():
        log(f"MISSING: {VENV_PY}")
        return 2
    log(f"harness: {exe}")

    port = args.port or free_port()
    env = os.environ.copy()
    env["SIM_ADDR"] = f"127.0.0.1:{port}"

    proc, handle = start_server(port, env)
    try:
        rc_live, out_live = run_harness(exe, env, "server UP")
    finally:
        stop_server(proc, handle, port)

    rc_down, out_down = run_harness(exe, env, "server DOWN (negative control)")

    live_ok = rc_live == 0 and "test result: ok" in out_live
    # A green negative control is the failure mode this whole script exists to catch.
    down_red = rc_down != 0 and (
        "test result: FAILED" in out_down or "panicked at" in out_down
    )

    log("=" * 68)
    log(f"live run:      rc={rc_live}  -> {'PASS' if live_ok else 'FAIL'}")
    log(f"server-down:   rc={rc_down}  -> {'RED (expected)' if down_red else 'NOT RED (BAD)'}")
    if live_ok and down_red:
        log("VERDICT: PASS — real Rust client consumed real MuJoCo frames; removing the")
        log("         peer turns the same test red, so the green was not a no-op.")
        return 0
    log("VERDICT: FAIL")
    if not live_ok:
        log("  the live run did not pass; see harness output above and " + str(SERVER_LOG))
    if not down_red:
        log("  the negative control did not fail on assertions: the test is not using the server")
    return 1


if __name__ == "__main__":
    sys.exit(main())
