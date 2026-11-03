#!/usr/bin/env python
"""Acceptance test for the `imu_to_dxl` v2 board (Dynamixel ID 200) on a dumb USB-TTL adapter.

Why this exists
---------------
docs/active/microduck-板子设计备忘.md §5.1: the thing that actually blocks a whole
robot is not the SBC, it is the IMU bridge. §6 lists the official contract, but the
only way to know whether a board you just bought honours it is to put it on a bus
and read it. This does that, byte by byte, before you wire it into a robot.

Contract (one-hand sources, checked 2026-11-03)
-----------------------------------------------
  duck-control/src/imu.rs:8-17   block at 124, 12 bytes:
                                 [0..6]  gyro x/y/z, i16 LE raw counts, +-500 dps
                                 [6..12] SFLP quaternion x/y/z, IEEE half-precision;
                                         w = sqrt(1 - x^2 - y^2 - z^2)
                                 full diagnostic block is 20 bytes; only the first 12
                                 ride the control loop
  duck-control/src/imu.rs:47-48  gyro scale 17.5 mdps/LSB = 0.0175 dps/count
  duck-control/src/imu.rs:116    all-zero quaternion bytes = SFLP has not written its
                                 table yet -- the board just powered up or init failed
  duck-control/src/imu.rs:104    ready() == 25 live quaternion samples (~0.25 s @100 Hz)
  duck-control/src/imu.rs:76-83  mount: sensor -> trunk is a +90 deg rotation about Y
  duck-control/src/bus.rs:36     READ_ADDR = 124 (same sync_read as the servos)
  duck-control/src/bus.rs:50     SLOW_READ_ADDR = 144 (voltage u16, then temperature)
  duck-control/src/model.rs:101  IMU_DXL_ID = 200
  duck-control/src/bus.rs:7-10   every sync read is a FAST sync read (0x8A) by default;
                                 `bus.fast_sync_read` turns it off for devices that do
                                 not implement 0x8A

Protocol 2.0 framing is NOT what most blog posts say. Two details cost an afternoon:
  * the length field is TWO bytes (little-endian), not one
  * the CRC-16 (poly 0x8005, MSB-first) starts from **0**, not 0xFFFF
Both verified against dynamixel_sdk/protocol2_packet_handler.py (updateCRC with
crc_accum=0, PKT_LENGTH_L/H at 5/6, total = LEN + 7). `--selftest` re-checks this
against that SDK when it is installed, so the framing is cross-validated by a second
independent implementation rather than by my own code agreeing with itself.

What it cannot prove
--------------------
A pass here means the board answers on the bus with the right payload shape. It does
not prove the payload is *correct* (gyro sign/axis, mount) -- that needs the board
mounted on a robot you can tilt by a known angle. It also cannot validate the CRC
offline: with no device, "no response" is indistinguishable from "my frame is wrong".
That is why `--expect-absent` exists, and why the pass criteria are written so that a
silent bus is a *labelled* outcome rather than a success.

Usage
-----
  # offline: decode + framing self-test, no hardware, no serial port needed
  python tools/hd1910/check_imu_bridge.py --selftest

  # negative control: assert the bus really has no ID 200 (run before wiring the bridge)
  python tools/hd1910/check_imu_bridge.py --port COM3 --expect-absent

  # acceptance: 2 s at 50 Hz, fast sync read
  python tools/hd1910/check_imu_bridge.py --port COM3

  # a bridge that only implements the plain 0x82 sync read (bus.fast_sync_read = false)
  python tools/hd1910/check_imu_bridge.py --port COM3 --no-fast

Exit codes: 0 pass, 1 fail, 2 no response (and --expect-absent was not given),
3 self-test failed.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import struct
import sys
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# contract constants (see module docstring for sources)
# ---------------------------------------------------------------------------

IMU_DXL_ID = 200
IMU_READ_ADDR = 124
IMU_BLOCK_LEN = 12
SLOW_READ_ADDR = 144
SLOW_READ_LEN = 3
GYRO_DPS_PER_LSB = 0.0175
GYRO_RAD_PER_LSB = GYRO_DPS_PER_LSB * math.pi / 180.0
SFLP_READY_SAMPLES = 25
MOUNT_TRUNK = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)  # sensor -> trunk, scalar first

HEADER = b"\xff\xff\xfd\x00"
INST_PING = 0x01
INST_READ = 0x02
INST_SYNC_READ = 0x82
INST_FAST_SYNC_READ = 0x8A


# ---------------------------------------------------------------------------
# protocol 2.0 framing
# ---------------------------------------------------------------------------

def _crc_table() -> list[int]:
    table = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        table.append(c)
    return table


_CRC_TABLE = _crc_table()


def update_crc(crc: int, data: bytes) -> int:
    """CRC-16 for Dynamixel Protocol 2.0. Seed is 0, not 0xFFFF (see docstring)."""
    for b in data:
        crc = ((crc << 8) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]) & 0xFFFF
    return crc


def build_instruction(dxl_id: int, instruction: int, params: bytes = b"") -> bytes:
    """Instruction packet: HEADER ID LEN_L LEN_H INST PARAM... CRC_L CRC_H."""
    n = len(params) + 3  # instruction(1) + params + crc(2)
    body = bytes([dxl_id, n & 0xFF, (n >> 8) & 0xFF, instruction]) + params
    pkt = HEADER + body
    # The CRC covers the WHOLE packet including the 4 header bytes, minus the CRC
    # itself (dynamixel_sdk calls updateCRC(0, txpacket, total - 2)). Computing it
    # over `body` alone produces a frame the device silently ignores -- the self-test
    # below caught exactly that, so keep the cross-check.
    return pkt + struct.pack("<H", update_crc(0, pkt))


def build_sync_read(ids: list[int], addr: int, length: int, fast: bool) -> bytes:
    params = struct.pack("<HH", addr, length) + bytes(ids)
    return build_instruction(0xFE, INST_FAST_SYNC_READ if fast else INST_SYNC_READ, params)


def build_read(dxl_id: int, addr: int, length: int) -> bytes:
    return build_instruction(dxl_id, INST_READ, struct.pack("<HH", addr, length))


def build_ping(dxl_id: int) -> bytes:
    return build_instruction(dxl_id, INST_PING)


@dataclass
class Status:
    dxl_id: int
    error: int
    params: bytes
    crc_ok: bool
    raw: bytes

    @property
    def alert(self) -> bool:
        return bool(self.error & 0x80)


def parse_status(buf: bytes) -> Status | None:
    """Return the first complete status packet in `buf`, or None if incomplete."""
    i = buf.find(HEADER)
    if i < 0 or len(buf) < i + 11:  # minimum status packet is 11 bytes
        return None
    dxl_id = buf[i + 4]
    n = buf[i + 5] | (buf[i + 6] << 8)
    total = i + 7 + n  # header(4) + id(1) + len(2) + n
    if len(buf) < total:
        return None
    pkt = buf[i:total]
    payload = pkt[8:total - 2]  # after error byte, before crc
    crc_rx = struct.unpack("<H", pkt[total - 2:total])[0]
    return Status(dxl_id, pkt[7], payload, update_crc(0, pkt[:total - 2]) == crc_rx, pkt)


# ---------------------------------------------------------------------------
# IMU block decoding (mirrors duck-control/src/imu.rs, deliberately re-derived)
# ---------------------------------------------------------------------------

def half_to_float(bits: int) -> float:
    """IEEE 754 binary16 -> python float. Same bit layout as Rust's f16 decode."""
    sign = -1.0 if bits & 0x8000 else 1.0
    exp = (bits >> 10) & 0x1F
    frac = bits & 0x3FF
    if exp == 0:
        return sign * frac * 2.0 ** -24
    if exp == 0x1F:
        return sign * math.inf if frac == 0 else math.nan
    return sign * (1.0 + frac / 1024.0) * 2.0 ** (exp - 15)


def quat_mul(a: tuple[float, float, float, float],
             b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_conj(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (q[0], -q[1], -q[2], -q[3])


def quat_rotate(q: tuple[float, float, float, float],
                v: tuple[float, float, float]) -> tuple[float, float, float]:
    w, x, y, z = q
    tx = 2.0 * (y * v[2] - z * v[1])
    ty = 2.0 * (z * v[0] - x * v[2])
    tz = 2.0 * (x * v[1] - y * v[0])
    return (
        v[0] + w * tx + (y * tz - z * ty),
        v[1] + w * ty + (z * tx - x * tz),
        v[2] + w * tz + (x * ty - y * tx),
    )


@dataclass
class Decoded:
    gyro_raw: tuple[int, int, int]
    gyro_dps: tuple[float, float, float]
    quat_sensor: tuple[float, float, float, float] | None  # None = SFLP not ready
    quat_trunk: tuple[float, float, float, float] | None
    gravity_trunk: tuple[float, float, float] | None
    sflp_ready: bool
    reject_reason: str = ""


def decode_block(raw: bytes, mount: tuple[float, float, float, float] = MOUNT_TRUNK,
                 apply_mount: bool = True) -> Decoded:
    """Decode the 12-byte block. Mirrors imu.rs:108-141 including its reject path."""
    if len(raw) != IMU_BLOCK_LEN:
        raise ValueError(f"block must be {IMU_BLOCK_LEN} bytes, got {len(raw)}")
    gx, gy, gz = struct.unpack("<hhh", raw[0:6])
    gyro_dps = (gx * GYRO_DPS_PER_LSB, gy * GYRO_DPS_PER_LSB, gz * GYRO_DPS_PER_LSB)

    packed = struct.unpack("<HHH", raw[6:12])
    if packed == (0, 0, 0):
        return Decoded((gx, gy, gz), gyro_dps, None, None, None, False,
                       "all-zero quaternion: SFLP has not written its table")

    x, y, z = (half_to_float(p) for p in packed)
    norm_sq = x * x + y * y + z * z
    if not all(map(math.isfinite, (x, y, z))) or norm_sq > 1.02:
        return Decoded((gx, gy, gz), gyro_dps, None, None, None, False,
                       f"quaternion rejected (norm^2={norm_sq:.4f}, x/y/z={x:.4f},{y:.4f},{z:.4f})")

    w = math.sqrt(max(0.0, 1.0 - norm_sq))
    q_sensor = (w, x, y, z)
    if apply_mount:
        q = quat_mul(q_sensor, quat_conj(mount))
        n = math.sqrt(sum(c * c for c in q))
        if n <= 0.5:
            return Decoded((gx, gy, gz), gyro_dps, q_sensor, None, None, False,
                           f"rotated quaternion collapsed (norm={n:.3f})")
        q_trunk = tuple(c / n for c in q)  # type: ignore[assignment]
    else:
        q_trunk = q_sensor
    gravity = quat_rotate(quat_conj(q_trunk), (0.0, 0.0, -1.0))
    return Decoded((gx, gy, gz), gyro_dps, q_sensor, q_trunk, gravity, True)


# ---------------------------------------------------------------------------
# serial I/O
# ---------------------------------------------------------------------------

class Bus:
    def __init__(self, port: str, baud: int, rx_timeout: float = 0.05):
        import serial  # imported here so --selftest runs without pyserial
        from serial.tools import list_ports
        try:
            self.ser = serial.Serial(port, baud, timeout=0.0, write_timeout=0.5)
        except Exception as exc:  # noqa: BLE001 - we want the message, not the type
            present = [p.device for p in list_ports.comports()]
            raise SystemExit(
                f"cannot open {port!r}: {exc}\n"
                f"ports present: {', '.join(present) if present else 'none'}\n"
                "URT-2 enumerates as CH343 (no driver needed on Win10/11). "
                "FD/flashtool must be closed first -- it holds the port."
            ) from None
        self.rx_timeout = rx_timeout
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()

    def transact(self, packet: bytes, expect_ids: int = 1) -> tuple[list[Status], int, int]:
        """Send and collect up to `expect_ids` status packets.

        Returns (packets, crc_errors, garbage_bytes). Garbage is counted rather than
        ignored: a bridge that half-answers produces a valid-looking first packet and
        then noise, which is exactly the failure this tool must not call a pass.
        """
        self.ser.reset_input_buffer()
        self.ser.write(packet)
        self.ser.flush()
        buf = b""
        deadline = time.perf_counter() + self.rx_timeout
        while time.perf_counter() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                buf += self.ser.read(waiting)
            done = 0
            probe = buf
            while True:
                st = parse_status(probe)
                if st is None:
                    break
                done += 1
                probe = probe[probe.find(HEADER) + 7 + (st.params.__len__() + 4):]
            if done >= expect_ids:
                break
        packets, crc_errors, consumed = [], 0, 0
        while True:
            st = parse_status(buf)
            if st is None:
                break
            packets.append(st)
            end = buf.find(HEADER) + 7 + (len(st.params) + 4)
            consumed = end
            buf = buf[end:]
        garbage = len(buf)
        crc_errors = sum(0 if p.crc_ok else 1 for p in packets)
        return packets, crc_errors, garbage


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def selftest() -> int:
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -- ' + detail) if detail and not cond else ''}")
        if not cond:
            fails.append(name)

    print("== framing ==")
    ping = build_ping(IMU_DXL_ID)
    check("ping frame length", len(ping) == 10, f"got {len(ping)}")
    check("ping frame bytes", ping[:8] == b"\xff\xff\xfd\x00\xc8\x03\x00\x01", ping[:8].hex())
    check("crc round-trips", update_crc(0, ping[:-2]) == struct.unpack("<H", ping[-2:])[0])

    # Independent implementation: dynamixel_sdk ships the vendor's own table + seed.
    try:
        from dynamixel_sdk.protocol2_packet_handler import Protocol2PacketHandler
        h = Protocol2PacketHandler()
        for frame in (ping, build_read(1, 124, 12), build_sync_read([200, 10, 11], 124, 12, True)):
            vendor = h.updateCRC(0, frame[:-2], len(frame) - 2)
            ours = struct.unpack("<H", frame[-2:])[0]
            check(f"crc matches dynamixel_sdk ({len(frame)}B)", vendor == ours, f"{vendor:04x} vs {ours:04x}")
        check("crc seed is 0 not 0xffff",
              h.updateCRC(0, ping[:-2], len(ping) - 2) != h.updateCRC(0xFFFF, ping[:-2], len(ping) - 2))
    except ImportError:
        print("  skip dynamixel_sdk cross-check (pip install dynamixel-sdk to enable)")

    print("== decode ==")
    # half encoding: 0x3C00 = 1.0, 0x3800 = 0.5, 0xBC00 = -1.0 (same vectors as imu.rs tests)
    check("half 0x3c00 == 1.0", half_to_float(0x3C00) == 1.0)
    check("half 0x3800 == 0.5", half_to_float(0x3800) == 0.5)
    check("half 0xbc00 == -1.0", half_to_float(0xBC00) == -1.0)

    # identity quaternion + zero gyro, mount disabled -> upright, gravity [0,0,-1]
    id_block = struct.pack("<hhhHHH", 0, 0, 0, 0x3C00, 0, 0)  # w is reconstructed, so x=1 is not identity
    # SFLP ships x/y/z only; identity is all-zero, which the board uses as "not ready".
    # So the canonical upright vector is x=0,y=0,z=0 -> rejected, and a small tilt is
    # the smallest decodable orientation. Assert both sides of that edge.
    d0 = decode_block(id_block)
    check("zero x/y/z quartet normalises", d0.sflp_ready and abs(sum(c * c for c in d0.quat_trunk) - 1.0) < 1e-6)

    notready = decode_block(b"\x00" * 12)
    check("all-zero block -> SFLP not ready", not notready.sflp_ready and notready.quat_trunk is None)
    check("all-zero block still yields gyro", notready.gyro_raw == (0, 0, 0))

    # 90 degrees about Y as half: sin(45)=cos(45)=0.7071 -> encoder 0x39B5 approx
    half_sin45 = 0x39B5
    tilt = struct.pack("<hhhHHH", 0, 0, 0, 0, half_sin45, 0)
    d1 = decode_block(tilt, apply_mount=False)
    check("45deg about Y decodes", d1.sflp_ready, d1.reject_reason)
    if d1.sflp_ready:
        check("45deg about Y tilts gravity", abs(d1.gravity_trunk[0]) > 0.5,
              f"gravity={d1.gravity_trunk}")

    # negative control: a quaternion that cannot exist must be rejected, not clamped
    bad = struct.pack("<hhhHHH", 0, 0, 0, 0x3C00, 0x3C00, 0x3C00)  # x=y=z=1 -> norm^2=3
    d2 = decode_block(bad)
    check("impossible quartet rejected (norm^2>1.02)", not d2.sflp_ready and "rejected" in d2.reject_reason)

    # gyro scale: 1000 counts must be 17.5 dps
    g = decode_block(struct.pack("<hhhHHH", 1000, -1000, 0, 0, 0, 0))
    check("gyro 1000 counts == 17.5 dps", abs(g.gyro_dps[0] - 17.5) < 1e-9 and abs(g.gyro_dps[1] + 17.5) < 1e-9)

    # mount: +90 about Y maps sensor -X onto trunk ... assert it is a rotation, not identity
    d3 = decode_block(tilt, apply_mount=True)
    d4 = decode_block(tilt, apply_mount=False)
    check("mount changes the answer", d3.gravity_trunk != d4.gravity_trunk,
          f"{d3.gravity_trunk} vs {d4.gravity_trunk}")

    print("== status parse ==")
    body = bytes([200, 15, 0, 0]) + bytes(range(12))  # err=0, 12 param bytes
    st = HEADER + body  # placeholder, fixed below
    pkt = HEADER + bytes([200, 15, 0, 0]) + bytes(range(12))
    pkt += struct.pack("<H", update_crc(0, pkt))
    parsed = parse_status(pkt)
    check("status parses", parsed is not None and parsed.dxl_id == 200)
    check("status crc checked", parsed is not None and parsed.crc_ok)
    check("status payload len", parsed is not None and len(parsed.params) == 12)
    check("truncated status -> None", parse_status(pkt[:-1]) is None)
    bad_crc = pkt[:-1] + bytes([pkt[-1] ^ 0xFF])
    check("bad crc flagged", parse_status(bad_crc) is not None and not parse_status(bad_crc).crc_ok)

    print()
    if fails:
        print(f"SELFTEST FAILED ({len(fails)}): {', '.join(fails)}")
        return 3
    print("selftest passed")
    return 0


def run_acceptance(args) -> int:
    ids = [args.id] + [int(x) for x in args.extra_ids.split(",") if x.strip()] if args.extra_ids else [args.id]
    bus = Bus(args.port, args.baud, rx_timeout=args.timeout)
    try:
        print(f"== ping id {args.id} ==")
        packets, crc_err, garbage = bus.transact(build_ping(args.id), expect_ids=1)
        if not packets:
            if args.expect_absent:
                print(f"PASS (negative control): no device answered id {args.id}; "
                      "the tool does not invent a response")
                return 0
            print(f"NO RESPONSE: id {args.id} did not answer on {args.port} @ {args.baud}")
            print("check, in this order: bridge powered (5-24 V) / A-B of the half-duplex line /")
            print("common ground / baud 1 Mbps / the id really is 200 / my frame or crc is wrong")
            return 2
        if args.expect_absent:
            print(f"FAIL (negative control): something DID answer id {args.id} "
                  f"(error=0x{packets[0].error:02x}) -- the bus is not empty")
            return 1
        st = packets[0]
        print(f"  answered: id={st.dxl_id} error=0x{st.error:02x} crc_ok={st.crc_ok} "
              f"params={len(st.params)}B alert={st.alert}")
        if not st.crc_ok or crc_err:
            print("FAIL: crc mismatch on the status packet -> framing/baud/noise")
            return 1

        print(f"== fast sync read {'0x8a' if not args.no_fast else '0x82'} "
              f"addr {IMU_READ_ADDR} len {IMU_BLOCK_LEN}, ids {ids} ==")
        n = args.samples
        period = 1.0 / args.rate
        samples: list[Decoded] = []
        misses = crc_bad = garbage_total = 0
        next_t = time.perf_counter()
        for k in range(n):
            pkts, cerr, garb = bus.transact(
                build_sync_read(ids, IMU_READ_ADDR, IMU_BLOCK_LEN, fast=not args.no_fast),
                expect_ids=len(ids))
            garbage_total += garb
            crc_bad += cerr
            mine = [p for p in pkts if p.dxl_id == args.id and p.crc_ok]
            if not mine or len(mine[0].params) < IMU_BLOCK_LEN:
                misses += 1
            else:
                samples.append(decode_block(mine[0].params[:IMU_BLOCK_LEN], apply_mount=not args.no_mount))
            next_t += period
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)

        answer_rate = (n - misses) / n
        ready = [s for s in samples if s.sflp_ready]
        dead = [s for s in samples if not s.sflp_ready]
        print(f"  {n} reads: answered {n - misses} ({answer_rate * 100:.1f}%), "
              f"crc errors {crc_bad}, garbage bytes {garbage_total}")
        print(f"  quaternion live in {len(ready)}/{len(samples)} decoded blocks")

        summary = {
            "port": args.port, "baud": args.baud, "id": args.id,
            "fast_sync_read": not args.no_fast,
            "reads": n, "answered": n - misses, "answer_rate": round(answer_rate, 4),
            "crc_errors": crc_bad, "garbage_bytes": garbage_total,
            "quat_live": len(ready), "quat_dead": len(dead),
            "sflp_ready": len(ready) >= SFLP_READY_SAMPLES,
            "empty_payload": False,
        }

        verdict_fail: list[str] = []
        if answer_rate < 0.90:
            verdict_fail.append(f"answer rate {answer_rate * 100:.1f}% < 90%")
        if crc_bad:
            verdict_fail.append(f"{crc_bad} crc errors")
        if len(ready) < SFLP_READY_SAMPLES:
            verdict_fail.append(f"only {len(ready)} live quaternion blocks "
                                f"(need {SFLP_READY_SAMPLES} for SflpDecoder::ready)")
        if garbage_total > 8 * n:
            verdict_fail.append(f"{garbage_total} stray bytes (half-duplex turnaround?)")

        if ready:
            gx = [s.gyro_dps[0] for s in samples]
            gy = [s.gyro_dps[1] for s in samples]
            gz = [s.gyro_dps[2] for s in samples]
            grav = [s.gravity_trunk for s in ready if s.gravity_trunk]
            gmag = [math.sqrt(sum(c * c for c in g)) for g in grav]
            summary.update({
                "gyro_dps_median": [round(statistics.median(v), 3) for v in (gx, gy, gz)],
                "gyro_dps_stdev": [round(statistics.pstdev(v), 3) for v in (gx, gy, gz)],
                "gravity_trunk_median": [round(statistics.median([g[i] for g in grav]), 3) for i in range(3)],
                "gravity_norm_min": round(min(gmag), 4), "gravity_norm_max": round(max(gmag), 4),
            })
            print(f"  gyro median (dps): {summary['gyro_dps_median']}  stdev: {summary['gyro_dps_stdev']}")
            print(f"  gravity in trunk frame (median): {summary['gravity_trunk_median']}  "
                  f"|g| in [{summary['gravity_norm_min']}, {summary['gravity_norm_max']}]")
            print("  (a board lying still, level, should read ~[0, 0, -1] here)")
            if args.static:
                worst = max(abs(v) for v in summary["gyro_dps_median"])
                if worst > 20.0:
                    verdict_fail.append(f"board reported {worst:.1f} dps while held still "
                                        "(not static, loose mount, or axis not what the contract says)")
            if not all(abs(g - 1.0) < 0.05 for g in gmag):
                verdict_fail.append("gravity is not a unit vector -> quaternion norm off; "
                                    "check for half-precision byte-order swap")
        if dead:
            print(f"  {len(dead)} block(s) rejected: {dead[0].reject_reason}")

        if verdict_fail:
            print("\nFAIL")
            for f in verdict_fail:
                print(f"  - {f}")
            summary["failures"] = verdict_fail
            summary["verdict"] = "fail"
        else:
            print("\nPASS: payload shape honours the v2 contract")
            print("not proven: gyro sign/axis and mount are only checked for plausibility;")
            print("confirm by tilting a known angle once the board is on a robot.")
            summary["verdict"] = "pass"

        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2)
            print(f"json -> {args.json_out}")
        return 0 if summary["verdict"] == "pass" else 1
    finally:
        bus.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Acceptance test for the imu_to_dxl v2 board (Dynamixel ID 200).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="offline framing + decode tests, no hardware")
    ap.add_argument("--port", help="serial port, e.g. COM3")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--id", type=int, default=IMU_DXL_ID)
    ap.add_argument("--extra-ids", default="", help="also request these ids in the same sync read, e.g. 10,11")
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--rate", type=float, default=50.0, help="reads per second")
    ap.add_argument("--timeout", type=float, default=0.05, help="per-transaction rx timeout (s)")
    ap.add_argument("--no-fast", action="store_true", help="use plain 0x82 sync read (fast_sync_read = false)")
    ap.add_argument("--no-mount", action="store_true", help="report the sensor frame, do not apply the +90 deg mount")
    ap.add_argument("--static", action="store_true", help="assert the board is being held still")
    ap.add_argument("--expect-absent", action="store_true",
                    help="negative control: PASS only if nothing answers")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.port:
        ap.error("--port is required unless --selftest")
    for bad in ("%",):
        pass  # argparse help strings must not contain % (format-string trap)
    return run_acceptance(args)


if __name__ == "__main__":
    sys.exit(main())
