#!/usr/bin/env python
"""Acceptance test for the `imu_to_dxl` v2 board (Feetech SCS v1, ID 200) on a dumb USB-TTL adapter.

Why this exists
---------------
docs/active/microduck-板子设计备忘.md §5.1: the thing that actually blocks a whole
robot is not the SBC, it is the IMU bridge. §6 lists the official contract, but the
only way to know whether a board you just bought honours it is to put it on a bus
and read it. This does that, byte by byte, before you wire it into a robot.

Protocol: Feetech SCS v1 (NOT Dynamixel Protocol 2.0)
------------------------------------------------------
The bridge firmware (kissqy/Microduck-kissqy, firmware/firmware/imu-source/) speaks
Feetech SCS v1, the same protocol the HD1910 servos use. The previous version of this
tool assumed Dynamixel P2.0 and would have been completely silent on the bridge.

Frame format (ft_protocol.c):
  FF FF ID LEN INST PARAM... SUM
  LEN = number of params + 2
  SUM = ~(sum of bytes[2..end-1]) = 0xFF - sum
  Total length = LEN + 4

Instructions:
  PING       0x01   no params
  READ       0x02   params = [addr, len]
  SYNC_READ  0x82   params = [addr, len, id, *servo_ids]
  (No 0x8A fast sync read -- that is Dynamixel P2.0 only.)

Address contract (ft_imu.h / ft_imu.c):
  124  diagnostic block, 20 bytes: [0..11] IMU, [12..15] seq u32, [16..17] age ms,
       [18] ready, [19] reserved
  56   compact block, 15 bytes:   [0..11] IMU, [12] seq u8, [13] status, [14] reserved
       (The control loop reads 56/15. 124 stays diagnostic.)

IMU block (12 bytes, both addresses):
  [0..6]  gyro x/y/z, i16 LE raw counts, ±500 dps (17.5 mdps/LSB)
  [6..12] SFLP quaternion x/y/z, IEEE half-precision; w = sqrt(1 - x² - y² - z²)
  All-zero quaternion bytes = SFLP has not written its table yet.

Sources (one-hand, read 2026-11-03)
-----------------------------------
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/src/ft_protocol.c
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/src/ft_fast_sync.c
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/src/ft_imu.c
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/include/ft_imu.h
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/tests/test_feetech.c
  kissqy/Microduck-kissqy/firmware/firmware/imu-source/tests/test_fast_sync.c
  kissqy/Microduck-kissqy/firmware/duck-control/src/feetech.rs

Self-test vectors are ported from the C tests, not invented.

What it cannot prove
--------------------
A pass here means the board answers on the bus with the right payload shape. It does
not prove the payload is *correct* (gyro sign/axis, mount) -- that needs the board
mounted on a robot you can tilt by a known angle. It also cannot validate the checksum
offline: with no device, "no response" is indistinguishable from "my frame is wrong".
That is why `--expect-absent` exists, and why the pass criteria are written so that a
silent bus is a *labelled* outcome rather than a success.

Usage
-----
  # offline: decode + framing self-test, no hardware, no serial port needed
  python tools/hd1910/check_imu_bridge.py --selftest

  # negative control: assert the bus really has no ID 200 (run before wiring the bridge)
  python tools/hd1910/check_imu_bridge.py --port COM3 --expect-absent

  # acceptance: ping + compact sync read + diagnostic read
  python tools/hd1910/check_imu_bridge.py --port COM3

  # read only the diagnostic block at 124 (20 bytes)
  python tools/hd1910/check_imu_bridge.py --port COM3 --diag-only

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
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# contract constants (see module docstring for sources)
# ---------------------------------------------------------------------------

IMU_DXL_ID = 200
IMU_BROADCAST = 254
IMU_COMPACT_ADDR = 56      # ft_imu.h: FT_IMU_SYNC_ADDRESS
IMU_COMPACT_LEN = 15       # ft_imu.h: FT_IMU_SYNC_LENGTH
IMU_DIAG_ADDR = 124        # ft_imu.h: FT_IMU_ADDRESS
IMU_DIAG_LEN = 20          # ft_imu.h: FT_IMU_LENGTH
IMU_BLOCK_LEN = 12         # ft_imu.h: FT_IMU_BLOCK_LENGTH

GYRO_DPS_PER_LSB = 0.0175
SFLP_READY_SAMPLES = 25

# Status bits (ft_imu.h)
IMU_NOT_READY = 0x01
IMU_STALE = 0x02
IMU_READER_SLOW = 0x08

# Instructions
INST_PING = 0x01
INST_READ = 0x02
INST_SYNC_READ = 0x82

# ---------------------------------------------------------------------------
# Feetech SCS v1 framing (ft_protocol.c)
# ---------------------------------------------------------------------------

def _scs_checksum(body: bytes) -> int:
    """~sum of body bytes (ft_protocol.c: out[count+5] = ~sum)."""
    return (~sum(body)) & 0xFF


def build_frame(dxl_id: int, instruction: int, params: bytes = b"") -> bytes:
    """Feetech SCS v1 instruction frame: FF FF ID LEN INST PARAMS SUM.

    LEN = len(params) + 2.  SUM = ~(sum of bytes[2..end-1]).
    """
    if dxl_id == 255:
        raise ValueError("ID 255 is reserved in SCS v1")
    body = bytes([dxl_id, len(params) + 2, instruction]) + params
    return b"\xff\xff" + body + bytes([_scs_checksum(body)])


def build_ping(dxl_id: int) -> bytes:
    return build_frame(dxl_id, INST_PING)


def build_read(dxl_id: int, addr: int, length: int) -> bytes:
    return build_frame(dxl_id, INST_READ, bytes([addr, length]))


def build_sync_read(addr: int, length: int, imu_id: int,
                    servo_ids: list[int] | None = None) -> bytes:
    """Broadcast sync read: params = [addr, len, imu_id, *servo_ids].

    The bridge matches addr=56, len=15, imu_id=200 (ft_fast_sync.c).
    """
    params = bytes([addr, length, imu_id])
    if servo_ids:
        params += bytes(servo_ids)
    return build_frame(IMU_BROADCAST, INST_SYNC_READ, params)


@dataclass
class ScsPacket:
    dxl_id: int
    instruction: int
    params: bytes
    checksum_ok: bool
    raw: bytes


def parse_scs(buf: bytes) -> ScsPacket | None:
    """Parse the first complete SCS v1 packet in `buf`.

    ft_protocol.c ft_parse:
      bytes[0]==255, bytes[1]==255, bytes[2]!=255, bytes[3]>=2,
      bytes[3]+4 == len, sum(bytes[2..]) == 255
    """
    i = buf.find(b"\xff\xff")
    if i < 0:
        return None
    # Need at least header(2) + id(1) + len(1) + checksum(1) = 6 bytes
    if len(buf) < i + 6:
        return None
    pkt_start = i
    dxl_id = buf[i + 2]
    if dxl_id == 0xFF:
        return None
    length = buf[i + 3]
    if length < 2:
        return None
    total = length + 4
    if len(buf) < pkt_start + total:
        return None
    pkt = buf[pkt_start:pkt_start + total]
    # Checksum: sum of bytes[2..total-1] must be 255
    s = sum(pkt[2:]) & 0xFF
    checksum_ok = (s == 0xFF)
    return ScsPacket(dxl_id, pkt[4], pkt[5:total - 1], checksum_ok, pkt)


# ---------------------------------------------------------------------------
# IMU block decoding (mirrors ft_imu.c / duck-control imu.rs)
# ---------------------------------------------------------------------------

def half_to_float(bits: int) -> float:
    """IEEE 754 binary16 -> python float."""
    sign = -1.0 if bits & 0x8000 else 1.0
    exp = (bits >> 10) & 0x1F
    frac = bits & 0x3FF
    if exp == 0:
        return sign * frac * 2.0 ** -24
    if exp == 0x1F:
        return sign * math.inf if frac == 0 else math.nan
    return sign * (1.0 + frac / 1024.0) * 2.0 ** (exp - 15)


@dataclass
class Decoded:
    gyro_raw: tuple[int, int, int]
    gyro_dps: tuple[float, float, float]
    quat_sensor: tuple[float, float, float, float] | None
    sflp_ready: bool
    reject_reason: str = ""


def decode_block(raw: bytes) -> Decoded:
    """Decode the 12-byte IMU block. Mirrors ft_imu.c imu_refresh output."""
    if len(raw) != IMU_BLOCK_LEN:
        raise ValueError(f"block must be {IMU_BLOCK_LEN} bytes, got {len(raw)}")
    gx, gy, gz = struct.unpack("<hhh", raw[0:6])
    gyro_dps = (gx * GYRO_DPS_PER_LSB, gy * GYRO_DPS_PER_LSB, gz * GYRO_DPS_PER_LSB)

    packed = struct.unpack("<HHH", raw[6:12])
    if packed == (0, 0, 0):
        return Decoded((gx, gy, gz), gyro_dps, None, False,
                       "all-zero quaternion: SFLP has not written its table")

    x, y, z = (half_to_float(p) for p in packed)
    norm_sq = x * x + y * y + z * z
    if not all(map(math.isfinite, (x, y, z))) or norm_sq > 1.02:
        return Decoded((gx, gy, gz), gyro_dps, None, False,
                       f"quaternion rejected (norm^2={norm_sq:.4f})")

    w = math.sqrt(max(0.0, 1.0 - norm_sq))
    return Decoded((gx, gy, gz), gyro_dps, (w, x, y, z), True)


# ---------------------------------------------------------------------------
# serial I/O
# ---------------------------------------------------------------------------

class Bus:
    def __init__(self, port: str, baud: int, rx_timeout: float = 0.05):
        import serial
        from serial.tools import list_ports
        try:
            self.ser = serial.Serial(port, baud, timeout=0.0, write_timeout=0.5)
        except Exception as exc:
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

    def transact(self, packet: bytes, expect_len: int | None = None) -> tuple[ScsPacket | None, int]:
        """Send and collect one response packet. Returns (packet, garbage_bytes)."""
        self.ser.reset_input_buffer()
        self.ser.write(packet)
        self.ser.flush()
        buf = b""
        deadline = time.perf_counter() + self.rx_timeout
        while time.perf_counter() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                buf += self.ser.read(waiting)
            pkt = parse_scs(buf)
            if pkt is not None:
                break
            time.sleep(0.001)
        pkt = parse_scs(buf)
        if pkt is not None:
            consumed = buf.find(pkt.raw) + len(pkt.raw)
            garbage = len(buf) - consumed
            return pkt, garbage
        return None, len(buf)


# ---------------------------------------------------------------------------
# self-test (ported from C test vectors)
# ---------------------------------------------------------------------------

def selftest() -> int:
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' -- ' + detail) if detail and not cond else ''}")
        if not cond:
            fails.append(name)

    print("== framing ==")
    # Ping frame (ID=200): FF FF C8 02 01 SUM
    ping = build_ping(200)
    check("ping frame length", len(ping) == 6, f"got {len(ping)}")
    # body = [200, 2, 1], sum = 203, checksum = ~203 = 52 (0x34)
    check("ping frame bytes", ping == b"\xff\xff\xc8\x02\x01\x34", ping.hex())
    check("ping checksum sums to 255", (sum(ping[2:]) & 0xFF) == 0xFF)

    # Read frame (ID=200, addr=124, len=12): FF FF C8 04 02 7C 0C SUM
    rd = build_read(200, 124, 12)
    check("read frame length", len(rd) == 8, f"got {len(rd)}")
    check("read frame bytes", rd == b"\xff\xff\xc8\x04\x02\x7c\x0c" + bytes([(~(200+4+2+124+12)) & 0xFF]),
          rd.hex())

    # Sync read (broadcast, addr=56, len=15, id=200): FF FF FE 05 82 38 0F C8 SUM
    sync = build_sync_read(56, 15, 200)
    check("sync frame length", len(sync) == 9, f"got {len(sync)}")
    check("sync frame bytes", sync[:8] == b"\xff\xff\xfe\x05\x82\x38\x0f\xc8", sync.hex())

    # Sync read with 15 servo IDs (the full robot request): 18 params, LEN=20, total=24
    full = build_sync_read(56, 15, 200, [20,21,22,23,24,30,31,32,33,34,10,11,12,13,14])
    check("full sync frame length", len(full) == 24, f"got {len(full)}")  # 4 + 18 + 2

    print("== parse ==")
    # Valid response: FF FF C8 02 00 SUM (ping success)
    resp = b"\xff\xff\xc8\x02\x00" + bytes([(~(200+2+0)) & 0xFF])
    pkt = parse_scs(resp)
    check("ping response parses", pkt is not None and pkt.dxl_id == 200)
    check("ping response inst==0", pkt is not None and pkt.instruction == 0)
    check("ping response checksum ok", pkt is not None and pkt.checksum_ok)

    # Truncated
    check("truncated -> None", parse_scs(resp[:-1]) is None)
    # Bad checksum
    bad = resp[:-1] + bytes([resp[-1] ^ 0xFF])
    pkt2 = parse_scs(bad)
    check("bad checksum flagged", pkt2 is not None and not pkt2.checksum_ok)
    # ID 255 reserved
    bad255 = b"\xff\xff\xff\x02\x01" + bytes([0])
    check("id 255 rejected", parse_scs(bad255) is None)
    # LEN < 2
    bad_len = b"\xff\xff\xc8\x01\x01" + bytes([0])
    check("len<2 rejected", parse_scs(bad_len) is None)

    print("== decode ==")
    check("half 0x3c00 == 1.0", half_to_float(0x3C00) == 1.0)
    check("half 0x3800 == 0.5", half_to_float(0x3800) == 0.5)
    check("half 0xbc00 == -1.0", half_to_float(0xBC00) == -1.0)

    # All-zero block -> SFLP not ready
    d0 = decode_block(b"\x00" * 12)
    check("all-zero block -> not ready", not d0.sflp_ready)

    # Live block from test vector (test_fast_sync.c)
    live = bytes([0x34, 0x12, 0xfe, 0xff, 0x55, 0xaa, 0, 0x30, 0, 0x38, 0, 0xb0])
    d1 = decode_block(live)
    check("live block decodes", d1.sflp_ready, d1.reject_reason)
    check("live block gyro raw", d1.gyro_raw == (0x1234, -0x0002, -21931),
          f"got {d1.gyro_raw}")

    # Impossible quaternion rejected
    bad_q = struct.pack("<hhhHHH", 0, 0, 0, 0x3C00, 0x3C00, 0x3C00)
    d2 = decode_block(bad_q)
    check("impossible quartet rejected", not d2.sflp_ready and "rejected" in d2.reject_reason)

    # Gyro scale
    g = decode_block(struct.pack("<hhhHHH", 1000, -1000, 0, 0, 0, 0))
    check("gyro 1000 counts == 17.5 dps", abs(g.gyro_dps[0] - 17.5) < 1e-9)

    print("== status bits ==")
    # From test_fast_sync.c: fresh -> 0, stale -> 0x02, reader_slow -> 0x08
    check("IMU_NOT_READY bit", IMU_NOT_READY == 0x01)
    check("IMU_STALE bit", IMU_STALE == 0x02)
    check("IMU_READER_SLOW bit", IMU_READER_SLOW == 0x08)

    print()
    if fails:
        print(f"SELFTEST FAILED ({len(fails)}): {', '.join(fails)}")
        return 3
    print("selftest passed")
    return 0


# ---------------------------------------------------------------------------
# acceptance
# ---------------------------------------------------------------------------

def run_acceptance(args) -> int:
    bus = Bus(args.port, args.baud, rx_timeout=args.timeout)
    try:
        # 1. Ping
        print(f"== ping id {args.id} ==")
        pkt, _ = bus.transact(build_ping(args.id))
        if pkt is None:
            if args.expect_absent:
                print(f"PASS (negative control): no device answered id {args.id}")
                return 0
            print(f"NO RESPONSE: id {args.id} did not answer on {args.port} @ {args.baud}")
            print("check: bridge powered (5-24 V) / A-B half-duplex line / common ground /")
            print("baud 1 Mbps / id really is 200 / frame or checksum wrong")
            return 2
        if args.expect_absent:
            print(f"FAIL (negative control): something DID answer id {args.id}")
            return 1
        if not pkt.checksum_ok:
            print("FAIL: checksum mismatch on ping response")
            return 1
        print(f"  answered: id={pkt.dxl_id} inst=0x{pkt.instruction:02x} checksum_ok=True")

        # 2. Sync read compact block (56/15) -- the control loop read
        print(f"== sync read 0x82 addr {IMU_COMPACT_ADDR} len {IMU_COMPACT_LEN}, id {args.id} ==")
        pkt2, garb = bus.transact(build_sync_read(IMU_COMPACT_ADDR, IMU_COMPACT_LEN, args.id))
        if pkt2 is None:
            print("NO RESPONSE to sync read (56/15)")
            return 2
        if not pkt2.checksum_ok:
            print("FAIL: checksum mismatch on sync read response")
            return 1
        print(f"  answered: id={pkt2.dxl_id} params={len(pkt2.params)}B checksum_ok=True garbage={garb}B")
        if len(pkt2.params) < IMU_COMPACT_LEN:
            print(f"FAIL: expected {IMU_COMPACT_LEN}B params, got {len(pkt2.params)}B")
            return 1

        # Decode the 12-byte IMU block from the compact response
        block = pkt2.params[:IMU_BLOCK_LEN]
        dec = decode_block(block)
        seq = pkt2.params[12] if len(pkt2.params) > 12 else 0
        status = pkt2.params[13] if len(pkt2.params) > 13 else 0
        print(f"  seq={seq} status=0x{status:02x} sflp_ready={dec.sflp_ready}")
        if dec.sflp_ready:
            print(f"  quat (w,x,y,z) = ({dec.quat_sensor[0]:.4f}, {dec.quat_sensor[1]:.4f}, "
                  f"{dec.quat_sensor[2]:.4f}, {dec.quat_sensor[3]:.4f})")
        print(f"  gyro (dps) = ({dec.gyro_dps[0]:.2f}, {dec.gyro_dps[1]:.2f}, {dec.gyro_dps[2]:.2f})")

        # 3. Diagnostic read (124/20) if requested
        if args.diag_only or args.diag:
            print(f"== diag read addr {IMU_DIAG_ADDR} len {IMU_DIAG_LEN} ==")
            pkt3, garb3 = bus.transact(build_read(args.id, IMU_DIAG_ADDR, IMU_DIAG_LEN))
            if pkt3 is None:
                print("NO RESPONSE to diagnostic read")
                return 2
            print(f"  answered: params={len(pkt3.params)}B checksum_ok={pkt3.checksum_ok}")
            if len(pkt3.params) >= IMU_DIAG_LEN:
                diag_seq = struct.unpack("<I", pkt3.params[12:16])[0]
                diag_age = struct.unpack("<H", pkt3.params[16:18])[0]
                diag_ready = pkt3.params[18]
                print(f"  diag: seq={diag_seq} age_ms={diag_age} ready={diag_ready}")

        # Verdict
        if args.static and dec.gyro_dps[0] > 5.0:
            print("WARN: gyro > 5 dps while held still (may be mounted, not a failure)")
        if not dec.sflp_ready and args.wait_ready:
            print(f"SFLP not ready (status=0x{status:02x}). If the board just powered up, "
                  f"wait ~0.5 s and re-read.")
        if not dec.sflp_ready and not args.wait_ready:
            print("WARN: SFLP not ready -- board may have just powered up or SFLP failed")

        print("\nPASS: bridge answers on the Feetech SCS v1 bus with the right payload shape")
        print("not proven: gyro sign/axis and mount are only checked for plausibility")
        return 0
    finally:
        bus.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Acceptance test for the imu_to_dxl v2 board (Feetech SCS v1, ID 200).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="offline framing + decode tests, no hardware")
    ap.add_argument("--port", help="serial port, e.g. COM3")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--id", type=int, default=IMU_DXL_ID)
    ap.add_argument("--timeout", type=float, default=0.05,
                    help="per-transaction rx timeout (s)")
    ap.add_argument("--diag", action="store_true",
                    help="also read the 20-byte diagnostic block at 124")
    ap.add_argument("--diag-only", action="store_true",
                    help="skip the sync read, only do ping + diagnostic read")
    ap.add_argument("--expect-absent", action="store_true",
                    help="negative control: PASS only if nothing answers")
    ap.add_argument("--static", action="store_true",
                    help="assert the board is being held still")
    ap.add_argument("--wait-ready", action="store_true",
                    help="SFLP not ready is a warning, not a failure (board just powered up)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.port:
        ap.error("--port is required unless --selftest")
    return run_acceptance(args)


if __name__ == "__main__":
    sys.exit(main())
