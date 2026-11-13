#!/usr/bin/env python3
"""C2 probe -- talk NDJSON/JSON-RPC to a *real* robotd unix socket.

Read-only on the robot side: hello / authenticate probe / health / subscribe.
Sends no motion commands. Used to establish the wire contract before the
Kotlin C2LiveCheck is written, so nothing here is inferred.
"""
import json
import socket
import sys
import time

SOCK = "/run/robotd.sock"


def main():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(SOCK)
    r = s.makefile("r", encoding="utf-8", newline="\n")
    seq = [0]

    def send(method, params=None, with_id=True):
        seq[0] += 1
        obj = {"jsonrpc": "2.0", "method": method}
        if with_id:
            obj["id"] = seq[0]
        if params is not None:
            obj["params"] = params
        s.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        return obj

    def recv_lines(want=1, window=1.2):
        got = []
        deadline = time.time() + window
        s.settimeout(0.3)
        while len(got) < want and time.time() < deadline:
            try:
                line = r.readline()
            except socket.timeout:
                continue
            except OSError as e:
                got.append({"__io_error__": repr(e)})
                break
            if not line:
                got.append({"__eof__": True})
                break
            try:
                got.append(json.loads(line))
            except Exception as e:
                got.append({"__bad_json__": line[:200], "err": repr(e)})
        return got

    def case(name, method, params=None, want=1, window=1.2):
        req = send(method, params)
        got = recv_lines(want, window)
        print(json.dumps({"case": name, "sent": req, "recv": got},
                         ensure_ascii=False, separators=(",", ":"))[:1400],
              flush=True)
        return got

    case("hello_v40_app_wire", "hello", {"api_version": 40})
    case("hello_v16_native", "hello", {"api_version": 16})
    case("authenticate_pin", "system.authenticate", {"pin": "000000"})
    case("authenticate_bad_pin_negative_control", "system.authenticate", {"pin": "999999"})
    case("health", "robot.health")
    case("unknown_method_negative_control", "this.method.does.not.exist", {})
    case("subscribe_hz4", "robot.subscribe", {"hz": 4}, want=4, window=2.0)
    s.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"probe_error": repr(e)}), flush=True)
        sys.exit(1)
