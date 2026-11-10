#!/usr/bin/env python3
"""Whole-stack gate for ``robotd --sim`` (run INSIDE WSL2).

Prerequisites (two live processes):

* Windows host: ``python -m mjlab_microduck.sim.body_server --headless --host 0.0.0.0 --port 7801 --ducks 2``
* WSL2: ``robotd --sim <windows-gateway>:7801 --socket /run/robotd.sock``

The gateway is ``ip route show default | awk '{print $3}'`` inside WSL2 (NAT mode).

What this gate proves (and why it sends NO torque itself)
---------------------------------------------------------
This gate deliberately never sends ``torque`` or ``gain``. It only says ``hello``
to check the peer and speaks ``robot.*`` over the daemon's unix socket. The whole
point of ``RemoteIo::at_powered`` is that the daemon, running against a simulator,
declares the power-on torque state on its very first handshake -- matching real
servos, which already have torque when the board is powered and never wait for
``robotd`` to tell them so.

``body_server.py`` holds an unclaimed duck still: every physics step it calls
``restore()`` on any body whose ``released`` flag is false (``World.step``), and
the ONLY frame that clears that flag is ``torque on`` (``Body.set_torque``). So:

* if ``robotd --sim`` uses ``at_powered`` (the fix), it sends ``torque on`` at the
  handshake, ``released`` becomes true, and the policy actually drives the body;
* if someone regresses it to the plain ``at`` client, no torque frame is ever
  sent, the body stays pinned, and this gate goes RED (joint span / odom flat).

That is the negative control, and it is a *behavioural* one: reverting one line
in ``robotd/src/main.rs`` is enough to fail the normal path. No mocking.

Independent observer (the second duck)
--------------------------------------
Start the server with ``--ducks 2`` and pass ``--observer-port 7802``. The gate
opens a bare protocol client to duck #1, sends only ``hello`` + ``read`` (never
``torque``), and asserts it stays frozen while duck #0 (driven by ``robotd``)
walks. Both ducks share one MuJoCo world and one wall clock, but ``released`` is
per-duck, so one moving and one frozen in the same world proves it is the torque
frame -- not physics drift, not a clock, not the policy -- that frees the body.
``--no-torque`` runs just this observer as a standalone negative control.
"""
import argparse
import collections
import json
import socket
import subprocess
import sys
import threading
import time

DEFAULT_SOCKET = "/run/robotd.sock"
DEFAULT_RCTL = "/root/duck/DuckBuddy-main/target/debug/robotctl"
PROTOCOL = 1


def ipc_call(method, params=None, sock=DEFAULT_SOCKET):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect(sock)
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1,
                               "method": method, "params": params or {}}) + "\n").encode())
        line = s.makefile("r", encoding="utf-8").readline()
        return json.loads(line) if line.strip() else None
    finally:
        s.close()


def sim_hello(host, port):
    """Liveness + protocol check ONLY. No torque, no gain -- that is robotd's job."""
    s = socket.create_connection((host, port), timeout=3)
    f = s.makefile("r", encoding="utf-8")
    try:
        s.sendall((json.dumps({"op": "hello", "protocol": PROTOCOL}) + "\n").encode())
        answer = json.loads(f.readline())
        if answer.get("protocol") != PROTOCOL:
            raise RuntimeError(f"protocol mismatch: {answer}")
        return answer
    finally:
        s.close()


def observer_sample(host, port, stop, out):
    """Bare client to an unclaimed duck: hello + read forever, NEVER torque.

    ``body_server`` keeps it ``restore()``-ed in place, so its joint positions and
    trunk must be constant for the whole window. Any motion here means the
    simulator itself (or cross-duck physics) moves released bodies, and the
    one-moving-one-frozen proof above collapses.
    """
    try:
        s = socket.create_connection((host, port), timeout=3)
        f = s.makefile("r", encoding="utf-8")
        s.sendall((json.dumps({"op": "hello", "protocol": PROTOCOL}) + "\n").encode())
        hello = json.loads(f.readline())
        if hello.get("protocol") != PROTOCOL:
            raise RuntimeError(f"observer protocol mismatch: {hello}")
        frames = []
        while not stop.is_set():
            s.sendall((json.dumps({"op": "read"}) + "\n").encode())
            line = f.readline()
            if not line:
                break
            o = json.loads(line)
            if "positions" in o:
                frames.append({"positions": o["positions"], "trunk": o.get("trunk", [])})
            stop.wait(0.05)
        s.close()
        out["frames"] = frames
    except Exception as error:  # surface the reason; a dead observer must not look like PASS
        out["error"] = repr(error)


def span(frames, key):
    frames = [f[key] for f in frames if key in f and f[key]]
    if not frames:
        return 0.0
    return max(max(f[j] for f in frames) - min(f[j] for f in frames)
               for j in range(len(frames[0])))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--rctl", default=DEFAULT_RCTL)
    ap.add_argument("--sim-host", required=True, help="Windows host as seen from WSL2")
    ap.add_argument("--sim-port", type=int, default=7801, help="duck #0, driven by robotd")
    ap.add_argument("--observer-port", type=int, default=0,
                    help="duck #1 port (e.g. 7802) for the no-torque independent observer; "
                         "0 disables it. Requires body_server --ducks 2")
    ap.add_argument("--vx", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--no-torque", action="store_true",
                    help="negative control ONLY: observe the unclaimed duck (--observer-port) "
                         "with no torque at all; it must stay frozen")
    args = ap.parse_args()

    if args.no_torque:
        if not args.observer_port:
            print("VERDICT: FAIL (--no-torque needs --observer-port, and body_server --ducks 2)",
                  flush=True)
            return 2
        out = {}
        stop = threading.Event()
        th = threading.Thread(target=observer_sample,
                              args=(args.sim_host, args.observer_port, stop, out), daemon=True)
        th.start()
        time.sleep(args.seconds)
        stop.set()
        th.join(timeout=3)
        frames = out.get("frames", [])
        if out.get("error") or not frames:
            print(f"VERDICT: FAIL (observer could not read duck #{args.observer_port - args.sim_port}: "
                  f"{out.get('error', 'no frames')})", flush=True)
            return 2
        jspan = span(frames, "positions")
        tdisp = span(frames, "trunk")
        print(f"observer(no torque): frames={len(frames)} joint_span={jspan:.8f} "
              f"trunk_disp={tdisp:.8f}", flush=True)
        ok = jspan < 1e-4 and tdisp < 1e-4
        print("VERDICT:", "PASS (negative control: unclaimed duck stayed frozen)" if ok
              else "FAIL (negative control: unclaimed duck moved without torque)", flush=True)
        return 0 if ok else 1

    # Normal path: prove the daemon, not this script, owns the torque state.
    hello = sim_hello(args.sim_host, args.sim_port)
    print(f"sim hello(duck 0): {hello}  [gate sends NO torque/gain]", flush=True)

    enable = ipc_call("robot.enable", {"on": True, "toggle": False}, args.socket)
    print("enable:", enable, flush=True)
    if not enable or not enable.get("result", {}).get("accepted"):
        print("VERDICT: FAIL (robot.enable refused)", flush=True)
        return 1
    time.sleep(2.5)  # homing ramp before commanding a twist

    obs_out, obs_stop, obs_th = {}, threading.Event(), None
    if args.observer_port:
        obs_th = threading.Thread(target=observer_sample,
                                  args=(args.sim_host, args.observer_port, obs_stop, obs_out),
                                  daemon=True)
        obs_th.start()

    states = []
    p = subprocess.Popen([args.rctl, "--robot-socket", args.socket, "monitor", "--json"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def reader():
        for line in p.stdout:
            try:
                o = json.loads(line)
                if o.get("method") == "robot.state":
                    states.append(o["params"])
            except (ValueError, KeyError):
                pass

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(0.6)
    cut = len(states)

    t0 = time.time()
    while time.time() - t0 < args.seconds:
        ipc_call("robot.move", {"vx": args.vx, "vy": 0.0, "vyaw": 0.0}, args.socket)
        time.sleep(0.05)
    ipc_call("robot.stop", {}, args.socket)
    time.sleep(0.6)
    p.terminate()
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()

    frames = states[cut:]
    if not frames:
        print("VERDICT: FAIL (no telemetry captured)", flush=True)
        return 2

    labels = dict(collections.Counter(f.get("policy") for f in frames))
    steps = [f["loop"]["step_ms"] for f in frames if "step_ms" in f.get("loop", {})]
    hz = [f["loop"]["hz"] for f in frames if "hz" in f.get("loop", {})]
    missed = {f["loop"].get("missed") for f in frames if "loop" in f}
    joint_span = span(frames, "joints")
    odom = [f["odom"]["position"] for f in frames if "odom" in f]
    dx = (odom[-1][0] - odom[0][0]) if odom else 0.0
    # "Did it move" (per-axis span), NOT "which way" (net dx sign). On this stack a +vx
    # body-frame command integrates to world-frame -x once walking reaches steady state
    # (a pre-existing odom/heading behaviour, reproduced at both kp=200 and kp=8; the daemon's
    # +vx never touches the quat convention). A short window straddling the stand-up transient
    # can even flip the sign, so gating on dx > 0 would be measuring the sampling phase, not
    # whether at_powered worked. The span cannot be fooled by sign drift, and a body pinned
    # by the regression (plain `at`, no torque frame) still yields span ~ 0.
    odom_span = (max(max(p[j] for p in odom) - min(p[j] for p in odom) for j in range(3))
                 if len(odom) >= 2 else 0.0)

    print(f"duck 0 (robotd at_powered): frames={len(frames)} policy={labels}", flush=True)
    print(f"  step_ms max={max(steps) if steps else 0:.4f}  "
          f"hz=[{min(hz):.3f},{max(hz):.3f}]  missed={sorted(missed)}", flush=True)
    print(f"  joint_span={joint_span:.5f} rad  odom_span={odom_span:.4f} m  "
          f"net_dx={dx:+.4f} m (sign is pre-existing, not gated)  "
          f"odom_distinct={len({tuple(o) for o in odom})}", flush=True)

    # duck #0 must be driven by the daemon's power-on torque declaration.
    ok0 = (steps and max(steps) > 0 and missed == {0}
           and hz and min(hz) > 49.0 and max(hz) < 51.0
           and joint_span > 1e-3 and odom_span > 0.05
           and "walk" in labels)

    ok_obs = True
    if obs_th:
        obs_stop.set()
        obs_th.join(timeout=3)
        obs_frames = obs_out.get("frames", [])
        ospan = span(obs_frames, "positions") if obs_frames else -1
        odisp = span(obs_frames, "trunk") if obs_frames else -1
        print(f"duck 1 (no torque, independent observer): frames={len(obs_frames)} "
              f"joint_span={ospan:.8f} trunk_disp={odisp:.8f}", flush=True)
        if obs_out.get("error"):
            print(f"  observer error: {obs_out['error']}", flush=True)
        ok_obs = bool(obs_frames) and ospan < 1e-4 and odisp < 1e-4

    ok = ok0 and ok_obs
    if ok:
        print("VERDICT: PASS (at_powered freed duck 0; duck 1 stayed frozen with no torque)",
              flush=True)
    else:
        why = []
        if not ok0:
            why.append("duck 0 not driven (check robotd --sim uses RemoteIo::at_powered, "
                       "not RemoteIo::at)")
        if not ok_obs:
            why.append("duck 1 moved without torque (observer invalid)")
        print("VERDICT: FAIL (" + "; ".join(why) + ")", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
