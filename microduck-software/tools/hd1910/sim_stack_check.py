#!/usr/bin/env python3
"""Whole-stack gate for ``robotd --sim`` (run INSIDE WSL2).

Prerequisites (two live processes):

* Windows host: ``python -m mjlab_microduck.sim.body_server --headless --host 0.0.0.0 --port 7801``
* WSL2: ``robotd --sim <windows-gateway>:7801 --socket /run/robotd.sock``

The gateway is ``ip route show default | awk '{print $3}'`` inside WSL2 (NAT mode).

Why this script sends ``torque on`` itself
------------------------------------------
``body_server`` starts with torque off. On real hardware the bus opens with torque on, but
the ``--sim`` bringup path does not get that far: the daemon loads and steps the ONNX policy
and writes joint targets (``targets`` changes by >1 rad) while ``joints``/``odom`` stay
frozen. Confirmed by a negative control on 2026-11-09: before an explicit ``torque on`` the
joint span was exactly 0 for all 15 joints; after it, 0.13-1.40 rad and 27 distinct odom
positions. So the gate enables torque first, then checks the whole chain.

Also required: ``robot.enable {on:true}`` -- the daemon deliberately will not drive just
because a process started (``Bringup::Limp``), and ``robot.move`` alone leaves the policy
at ``held``/``step_ms=0``.
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


def sim_ops(host, port):
    """Open torque and set a position gain on the MuJoCo body."""
    s = socket.create_connection((host, port), timeout=3)
    f = s.makefile("r", encoding="utf-8")
    try:
        for req in ({"op": "hello", "protocol": 1},
                    {"op": "torque", "on": True},
                    {"op": "gain", "kp": 8}):
            s.sendall((json.dumps(req) + "\n").encode())
            answer = json.loads(f.readline())
            if "error" in answer:
                raise RuntimeError(f"{req['op']}: {answer['error']}")
        print("sim: hello/torque/gain acknowledged", flush=True)
    finally:
        s.close()


def span(frames, key):
    frames = [f[key] for f in frames if key in f]
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
    ap.add_argument("--sim-port", type=int, default=7801)
    ap.add_argument("--vx", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--no-torque", action="store_true",
                    help="negative control: skip torque; the body must NOT move")
    args = ap.parse_args()

    if not args.no_torque:
        sim_ops(args.sim_host, args.sim_port)

    enable = ipc_call("robot.enable", {"on": True, "toggle": False}, args.socket)
    print("enable:", enable, flush=True)
    if not enable or not enable.get("result", {}).get("accepted"):
        print("VERDICT: FAIL (robot.enable refused)", flush=True)
        return 1
    time.sleep(2.5)  # homing ramp before commanding a twist

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

    print(f"frames={len(frames)} policy={labels}", flush=True)
    print(f"step_ms max={max(steps) if steps else 0:.4f}  "
          f"hz=[{min(hz):.3f},{max(hz):.3f}]  missed={sorted(missed)}", flush=True)
    print(f"joint_span={joint_span:.5f} rad  odom_dx={dx:.4f} m  "
          f"odom_distinct={len({tuple(o) for o in odom})}", flush=True)

    if args.no_torque:
        ok = joint_span < 1e-6 and abs(dx) < 1e-6
        print("VERDICT:", "PASS (negative control: body stayed frozen)" if ok
              else "FAIL (negative control: body moved without torque)", flush=True)
        return 0 if ok else 1

    ok = (steps and max(steps) > 0 and missed == {0}
          and hz and min(hz) > 49.0 and max(hz) < 51.0
          and joint_span > 1e-3 and dx > 0.01
          and "walk" in labels)
    print("VERDICT:", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
