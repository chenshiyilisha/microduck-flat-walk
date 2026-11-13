#!/usr/bin/env python3
"""C2+ relay -- AF_UNIX <-> TCP byte-forwarder for a real robotd, with a
separate fault-injection control channel.

WHY A SEPARATE FILE (not editing c2_relay.py):
  c2_relay.py + c2_gate.sh are the evidence chain behind the already-green
  C2 11/11 result. Touching them would mean re-proving a closed result. This
  file is C2+ only; the default C2 harness stays byte-for-byte unchanged.

Deliberately dumb on the DATA path: no JSON parsing, no canned responses, no
retries. Every byte the Kotlin client receives comes from the real Rust daemon,
so the zero-canned evidence boundary is preserved.

Fault injection (one-hand source: Shopify Toxiproxy, github.com/shopify/toxiproxy):
  - "Toxics manipulate the pipe between the client and upstream ... added and
     removed from proxies using the HTTP api"  => INDEPENDENT control channel
  - "limit_data: Closes connection when transmitted data exceeded limit"
  - "reset_peer: Simulate TCP RESET ... by closing the stub input"
  The proxy never speaks the application protocol. Same shape as this project's
  own LocalRelayServer.dropAfterMethod/dropTimes (socket.close()), but at the
  byte-forwarder layer so the peer stays a REAL robotd.
  One connection to --control-port closes every active forwarded pair (client
  + upstream). It injects NO bytes and NO replies: only a link-layer cable pull.
"""
import argparse
import socket
import threading

_active = set()
_active_lock = threading.Lock()


def _close_pair(pair):
    for s in pair:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass


def pipe(src, dst, pair):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        with _active_lock:
            _active.discard(pair)
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        _close_pair(pair)


def control_loop(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(8)
    print("CONTROL_READY port=%d" % port, flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            conn.close()
        except OSError:
            pass
        with _active_lock:
            pairs = list(_active)
        for p in pairs:
            _close_pair(p)
        print("FAULT_INJECT_DROP pairs=%d" % len(pairs), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--unix", default="/run/robotd.sock")
    ap.add_argument("--control-port", type=int, default=7789)
    args = ap.parse_args()

    threading.Thread(target=control_loop, args=(args.control_port,), daemon=True).start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(8)
    print("RELAY_READY port=%d unix=%s control=%d" %
          (args.port, args.unix, args.control_port), flush=True)
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
        pair = (client, upstream)
        with _active_lock:
            _active.add(pair)
        threading.Thread(target=pipe, args=(client, upstream, pair), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client, pair), daemon=True).start()


if __name__ == "__main__":
    main()
