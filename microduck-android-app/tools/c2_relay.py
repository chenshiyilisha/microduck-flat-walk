#!/usr/bin/env python3
"""C2 relay -- AF_UNIX <-> TCP byte-forwarder for a real robotd.

Deliberately dumb on purpose: no JSON parsing, no canned responses, no retries.
Every byte the Kotlin client receives comes from the real Rust daemon. That is
what makes C2 evidence stronger than LocalRelayServer (a protocol-equivalent
fixture). AF_UNIX client usage follows the project's own tools/robot-tests/rpc.py.
"""
import argparse
import socket
import threading


def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--unix", default="/run/robotd.sock")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(8)
    print("RELAY_READY port=%d unix=%s" % (args.port, args.unix), flush=True)
    while True:
        client, _ = srv.accept()
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(args.unix)
        except OSError as e:
            print("UPSTREAM_FAIL %r" % (e,), flush=True)
            client.close()
            upstream.close()
            continue
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


if __name__ == "__main__":
    main()
