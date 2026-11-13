#!/usr/bin/env python3
"""C2+ state-stream probe -- talk NDJSON/JSON-RPC to a REAL robotd unix socket,
with a Windows body_server behind it (so the 50 Hz control loop actually ticks).

Read-only on the robot side: no motion commands. Establishes the *live* wire
contract for the Kotlin C2PlusLiveCheck before any assertion is written.

Framing note (one-hand source, Python docs socket.html):
  socket.makefile() requires a blocking socket, and "the file object's internal
  buffer may end up in an inconsistent state if a timeout occurs" -> a readline()
  timeout then raises OSError('cannot read from timed out object') forever.
  The "no subscriber" phase below intentionally produces NO data, so a timeout
  was guaranteed. Therefore: keep the socket blocking, use select() to decide
  readability, and split NDJSON lines on '\n' ourselves (same shape as
  TcpTransport's readerLoop). No timeout can ever poison the buffer.

Negative controls (from upstream one-hand source):
  - robotd/src/main.rs:2949 `if state.state_tx.receiver_count() > 0` +
    upstream test `no_subscribers_means_no_frames` (main.rs:5282):
    with no subscriber there must be ZERO robot.state frames.
  - robotd/src/main.rs:3499-3506 "Subscribing again replaces the rate rather
    than opening a second stream": re-subscribing with hz=10 must yield ~10 Hz,
    NOT 4+10 Hz and NOT two lanes.
  - probe self-check: hello MUST get a response, else the read channel is broken
    and every "0 frames" result would be a false green.
"""
import json
import select
import socket
import sys
import time

SOCK = "/run/robotd.sock"


class LineReader:
    """NDJSON line reader over a blocking socket. select() gates every recv()."""

    def __init__(self, sock):
        self.s = sock
        self.buf = bytearray()

    def poll(self, wait_s):
        if wait_s <= 0:
            return
        ready, _, _ = select.select([self.s], [], [], min(wait_s, 0.2))
        if ready:
            data = self.s.recv(65536)
            if not data:
                raise EOFError("peer closed")
            self.buf.extend(data)

    def pop(self):
        i = self.buf.find(b"\n")
        if i < 0:
            return None
        raw = bytes(self.buf[:i])
        del self.buf[:i + 1]
        return raw.decode("utf-8", errors="replace")


def main():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(None)          # blocking: never let a timeout poison the buffer
    s.connect(SOCK)
    rd = LineReader(s)
    seq = [0]

    def send(method, params=None):
        seq[0] += 1
        obj = {"jsonrpc": "2.0", "method": method, "id": seq[0]}
        if params is not None:
            obj["params"] = params
        s.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        return obj

    def pump(window_s):
        """Read every line in [window_s]; split into responses / notifications."""
        responses, states, others = [], [], []
        deadline = time.time() + window_s
        while time.time() < deadline:
            while True:
                line = rd.pop()
                if line is None:
                    break
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception as e:
                    others.append({"__bad_json__": line[:200], "err": repr(e)})
                    continue
                if "id" in o:
                    responses.append(o)
                elif o.get("method") == "robot.state":
                    states.append(o)
                else:
                    others.append(o)
            try:
                rd.poll(max(0.0, deadline - time.time()))
            except (EOFError, OSError) as e:
                others.append({"__io_error__": repr(e)})
                break
        # Drain any lines that arrived in the same recv as the last poll.
        while True:
            line = rd.pop()
            if line is None:
                break
            try:
                o = json.loads(line)
            except Exception:
                continue
            (responses if "id" in o else states if o.get("method") == "robot.state" else others).append(o)
        return responses, states, others

    def one(name, method, params=None, window=0.8):
        req = send(method, params)
        resp, states, others = pump(window)
        print(json.dumps({"case": name, "sent": req,
                          "responses": resp[:2], "state_frames": len(states),
                          "others": others[:2]},
                         ensure_ascii=False, separators=(",", ":"))[:1800],
              flush=True)
        return resp, states, others

    # ---- 0. negative control: NO subscriber => NO frames ----
    _, pre_states, pre_others = pump(1.0)
    print(json.dumps({"case": "no_subscriber_negative_control",
                      "state_frames": len(pre_states), "others": pre_others[:2]},
                     ensure_ascii=False, separators=(",", ":")), flush=True)

    # ---- probe self-check: read channel must actually work ----
    hello_resp, _, _ = one("hello_v40", "hello", {"api_version": 40})
    if not hello_resp:
        print(json.dumps({"probe_channel_broken": True,
                          "reason": "hello got no response; all zero-frame results are invalid"}),
              flush=True)
        sys.exit(2)
    one("health", "robot.health")

    # ---- 1. subscribe hz=4, collect real frames ----
    req1 = send("robot.subscribe", {"hz": 4})
    resp1, st1, ot1 = pump(2.5)
    p1 = [o.get("params", {}) for o in st1]
    t1 = [x.get("t") for x in p1]
    print(json.dumps({
        "case": "subscribe_hz4", "sent": req1, "responses": resp1[:1],
        "state_frames": len(st1), "others": ot1[:2],
        "first_frame_keys": sorted(p1[0].keys()) if p1 else [],
        "first_frame_t": t1[0] if t1 else None,
        "last_frame_t": t1[-1] if t1 else None,
        "t_monotonic": all(t1[i] < t1[i + 1] for i in range(len(t1) - 1)) if len(t1) > 1 else None,
        "policies": sorted({x.get("policy") for x in p1}),
        "joints_len": len(p1[0].get("joints", [])) if p1 else None,
        "has_loop": "loop" in p1[0] if p1 else None,
        "loop_hz": p1[0].get("loop", {}).get("hz") if p1 else None,
        "has_move": "move" in p1[0] if p1 else None,
    }, ensure_ascii=False, separators=(",", ":")), flush=True)

    # ---- 2. re-subscribe hz=10 on the SAME connection => rate replaced, not added ----
    req2 = send("robot.subscribe", {"hz": 10})
    resp2, st2, ot2 = pump(2.0)
    print(json.dumps({
        "case": "resubscribe_hz10_same_connection", "sent": req2,
        "responses": resp2[:1], "state_frames": len(st2),
        "window_s": 2.0, "others": ot2[:2],
    }, ensure_ascii=False, separators=(",", ":")), flush=True)

    s.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"probe_error": repr(e)}), flush=True)
        sys.exit(1)
