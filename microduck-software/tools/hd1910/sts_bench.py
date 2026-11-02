#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Stage-0 URT-2 / URT-1 / HD-1910 bench skeleton (gates 0.1 / 0.2 / 0.4).

Sources
-------
* ``docs/active/microduck-HD1910阶段C软件清单.md`` §3
* ``docs/hardware/microduck-采购清单.md`` §7.6
* ``tools/hd1910/stage0_software_prep.md``

Hardware: Feetech **URT-2 (preferred) or URT-1** (not U2D2) + one HD-1910 on
**TTL**. External supply feeds the **servo V/G** directly; share GND with the
adapter; leave URT **V1 empty** (do not backfeed 7.4 V into USB). See
`.upstream/r_踩坑记录.md` and `stage0_software_prep.md`.
Software intent: short STS script **or** FD continuous R/W — **do not** write a
robotd / bus daemon here (方案 §5 / 阶段C §6).

Without hardware
----------------
``--dry-run`` prints the protocol plan and exits 0. Use this to verify the
checklist before parts arrive.

With hardware
-------------
Pass ``--port COMx`` (Windows) or ``/dev/ttyUSBx``. This skeleton looks for a
pluggable STS backend:

1. ``scservo_sdk`` / ``SMS_STS`` if importable (Feetech Python port), else
2. clear error telling you to finish 0.1–0.4 in **FD** first.

We do **not** vendor the FTServo SDK in-tree.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "out" / "sts_bench_stage0.json"

# Feetech SMS/STS register map (public FD / manual; confirmed by community
# HD1910 fits — see 采购清单 §7 / OpenMicroDuck characterization).
REG_ID = 5
REG_BAUD = 6
REG_TORQUE_ENABLE = 40
REG_GOAL_CURRENT = 44  # mA units on STS; training power budget uses ~3.25 A cap
REG_P = 50  # runtime P gain (RAM); EEPROM copy is reg 21, applied at power-on
BAUD_1M = 1_000_000

# P3 裁决（2026-10-29）：32 是出厂 ROM 默认，真正跑的是 5。
# duty = err * kp * error_gain；duty=0.3 时 P=32 → 3.3°、P=5 → 21.1°
# ⇒ 32 与 5 是两种物理特性的机器，不能只改一边。
# 本机实测（2026-11-01，出厂 ID 1）：reg21=32、reg50=32 —— 还没改。
# 所以闸门 0.4 在真机写 P 之前会 **正确地** 报 FAIL；这不是 bug，是提醒。
KP_FW_TARGET = 5
KP_FW_FACTORY_ROM = 32
TXN_BUDGET_MS = 5.0  # gate 0.2: one sync txn @ 1 Mbps
HZ_TARGET = 50.0


@dataclass
class GateResult:
    gate: str
    ok: bool
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


class StsBus(Protocol):
    """Minimal surface the stage-0 gates need. Plug SMS_STS / scservo here."""

    def ping(self, servo_id: int) -> bool: ...
    def read_u8(self, servo_id: int, reg: int) -> int: ...
    def write_u8(self, servo_id: int, reg: int, value: int) -> None: ...
    def close(self) -> None: ...


class DryRunBus:
    """Stand-in that never opens a port — for checklist rehearsal only."""

    def __init__(self, pretend_id: int = 1, pretend_p: int = KP_FW_TARGET):
        self._id = pretend_id
        self._p = pretend_p
        self._closed = False

    def ping(self, servo_id: int) -> bool:
        return servo_id == self._id

    def read_u8(self, servo_id: int, reg: int) -> int:
        if reg == REG_ID:
            return self._id
        if reg == REG_P:
            return self._p
        if reg == REG_BAUD:
            return 0  # Feetech baud index 0 == 1 Mbps on SMS/STS
        return 0

    def write_u8(self, servo_id: int, reg: int, value: int) -> None:
        if reg == REG_ID:
            self._id = value
        if reg == REG_P:
            self._p = value

    def close(self) -> None:
        self._closed = True


class SerialStsBus:
    """URT-2 / URT-1 真串口后端：飞特 SCS v1 半双工帧。

    帧格式不自己推 —— 直接复用 ``tools/hd1910/servo_probe/hd1910_readonly.py``
    （PING inst=1 / READ inst=2；地址表出自 whatled 台架指南 §6 + kissqy hd1910.rs）。
    WRITE inst=0x03、params=[addr, data...]、应答无参数，出自
    ``microduck-replica/rl-series/scripts/hl2915_bench.py:156-159``
    —— 帧同族可抄，**寄存器表不可抄**（HL-2915 与 HD-1910 地址不同）。
    """

    _INST_WRITE = 0x03

    def __init__(self, port: str, baud: int = BAUD_1M) -> None:
        import importlib.util

        import serial

        src = (
            pathlib.Path(__file__).resolve().parent / "servo_probe" / "hd1910_readonly.py"
        )
        if not src.exists():
            raise SystemExit(f"missing protocol impl: {src}")
        spec = importlib.util.spec_from_file_location("hd1910_ro", src)
        assert spec is not None and spec.loader is not None
        self._ro = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._ro)
        self._ser = serial.Serial(
            port, baud, bytesize=8, parity="N", stopbits=1, timeout=0.05
        )

    def ping(self, servo_id: int) -> bool:
        return bool(self._ro.ping(self._ser, servo_id))

    def read_u8(self, servo_id: int, reg: int) -> int:
        raw = self._ro.query(self._ser, servo_id, reg, 1)
        if raw is None:
            raise OSError(f"no reply: READ reg {reg} from id {servo_id}")
        return int(raw[0])

    def write_u8(self, servo_id: int, reg: int, value: int) -> None:
        self._write(servo_id, reg, bytes([value & 0xFF]))

    def _write(self, servo_id: int, reg: int, data: bytes) -> None:
        """WRITE 后等一帧应答（write 应答无参数 = 共 6 字节）。"""
        ser = self._ser
        ser.reset_input_buffer()
        ser.write(self._ro.frame(servo_id, self._INST_WRITE, bytes([reg]) + data))
        ser.flush()
        deadline = time.monotonic() + 0.1
        buf = b""
        while time.monotonic() < deadline:
            n = ser.in_waiting
            if n:
                buf += ser.read(n)
            if len(buf) >= 6:
                break
            time.sleep(0.0005)
        if len(buf) < 6 or buf[0] != 0xFF or buf[1] != 0xFF or buf[2] != servo_id:
            raise OSError(
                f"no reply: WRITE reg {reg} to id {servo_id} (buf={buf.hex()!r})"
            )

    def close(self) -> None:
        self._ser.close()


def try_open_live(port: str, baud: int = BAUD_1M) -> StsBus:
    """Open a real backend on ``port``.

    首选 ``SerialStsBus``：pyserial + 仓库内现成帧实现，装了 pyserial 就能跑，
    不需要 vendor 飞特 SDK。pyserial 缺失时才退回「用 FD 手工过闸」的提示。
    """
    try:
        import serial  # noqa: F401 — 只为探测可用性
    except ImportError:
        pass
    else:
        return SerialStsBus(port, baud)

    for mod_name in ("scservo_sdk", "STservo_sdk"):
        try:
            __import__(mod_name)
        except ImportError:
            continue
        raise SystemExit(
            f"found {mod_name} but this tool has no adapter for it — "
            f"`pip install pyserial` and rerun (SerialStsBus path), or finish "
            f"gates 0.1–0.4 in Feetech FD on {port} @ {baud}. "
            f"Do not invent a robotd here."
        )
    raise SystemExit(
        f"no serial backend: `pip install pyserial` (that gives SerialStsBus). "
        f"Otherwise finish stage-0 in Feetech FD on URT-2/URT-1 ({port} @ {baud})."
    )


def gate_01_ping(bus: StsBus, servo_id: int) -> GateResult:
    ok = bool(bus.ping(servo_id))
    return GateResult(
        gate="0.1_ping_id_1mbps",
        ok=ok,
        detail=(
            f"ping id={servo_id} @ {BAUD_1M} — "
            + ("ok" if ok else "no reply (check URT-2/URT-1 TTL / power / ID)")
        ),
        metrics={"servo_id": servo_id, "baud": BAUD_1M},
    )


def gate_02_txn(bus: StsBus, servo_id: int, samples: int = 100) -> GateResult:
    """50 Hz continuous read of REG_P; budget = median txn ≤ 5 ms, 0 CRC errors."""
    times_ms: list[float] = []
    errors = 0
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            _ = bus.read_u8(servo_id, REG_P)
        except Exception as exc:  # noqa: BLE001 — backend-specific I/O
            errors += 1
            detail_err = str(exc)
        else:
            detail_err = ""
        dt_ms = (time.perf_counter() - t0) * 1000.0
        times_ms.append(dt_ms)
        # Pace at 50 Hz so we measure a realistic loop, not a burst.
        sleep = max(0.0, (1.0 / HZ_TARGET) - (dt_ms / 1000.0))
        if sleep:
            time.sleep(sleep)
    times_ms.sort()
    median = times_ms[len(times_ms) // 2]
    p95 = times_ms[int(len(times_ms) * 0.95)]
    ok = errors == 0 and median <= TXN_BUDGET_MS
    return GateResult(
        gate="0.2_50hz_txn_le_5ms",
        ok=ok,
        detail=(
            f"n={samples} median={median:.2f}ms p95={p95:.2f}ms errors={errors}"
            + (f" last_err={detail_err}" if detail_err else "")
            + ("" if ok else f" — FAIL budget {TXN_BUDGET_MS:g} ms / 0 CRC")
        ),
        metrics={
            "samples": samples,
            "median_ms": round(median, 3),
            "p95_ms": round(p95, 3),
            "errors": errors,
            "budget_ms": TXN_BUDGET_MS,
            "hz": HZ_TARGET,
        },
    )


def gate_04_kp(bus: StsBus, servo_id: int, target: int = KP_FW_TARGET) -> GateResult:
    try:
        p = int(bus.read_u8(servo_id, REG_P))
    except Exception as exc:  # noqa: BLE001 — 舵机不在总线上是很常见的情况
        # 15 颗巡检时少接一颗不能让整个工具崩掉。
        return GateResult(
            gate=f"0.4_firmware_P_eq_{target}",
            ok=False,
            detail=f"cannot read reg {REG_P} from id {servo_id}: {exc}",
            metrics={"reg": REG_P, "P": None, "kp_fw_target": target},
        )
    ok = p == target
    hint = ""
    if not ok and p == KP_FW_FACTORY_ROM:
        hint = (
            f" — 实测是出厂 ROM 默认 {KP_FW_FACTORY_ROM}，真机尚未对齐 P3。"
            f" 部署前须把 reg {REG_P} 写成 {target}（RAM 增益，掉电回落 reg21="
            f"{KP_FW_FACTORY_ROM} ⇒ 每次上电都要写，或把 EEPROM reg21 一并改掉）"
        )
    return GateResult(
        gate=f"0.4_firmware_P_eq_{target}",
        ok=ok,
        detail=f"reg {REG_P} P={p} (want {target} = training kp_fw){hint}",
        metrics={"reg": REG_P, "P": p, "kp_fw_target": target},
    )


def run_gates(
    bus: StsBus, servo_id: int, samples: int, kp_target: int = KP_FW_TARGET
) -> list[GateResult]:
    return [
        gate_01_ping(bus, servo_id),
        gate_02_txn(bus, servo_id, samples=samples),
        gate_04_kp(bus, servo_id, target=kp_target),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="no serial — print plan + synthetic pass (default if --port omitted)",
    )
    ap.add_argument("--port", default=None, help="URT-2/URT-1 serial port, e.g. COM5")
    ap.add_argument("--id", type=int, default=1, help="servo ID (default 1)")
    ap.add_argument("--samples", type=int, default=100, help="txn samples for gate 0.2")
    ap.add_argument(
        "--kp-target",
        type=int,
        default=KP_FW_TARGET,
        help=f"expected runtime P in reg {REG_P} (default {KP_FW_TARGET} = P3)",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="write JSON report")
    args = ap.parse_args(argv)

    dry = args.dry_run or not args.port
    if dry:
        bus: StsBus = DryRunBus(pretend_id=args.id, pretend_p=KP_FW_TARGET)
        mode = "dry_run"
    else:
        bus = try_open_live(args.port)
        mode = "live"

    try:
        results = run_gates(bus, args.id, args.samples, kp_target=args.kp_target)
    finally:
        bus.close()

    payload = {
        "tool": "sts_bench",
        "mode": mode,
        "port": args.port,
        "servo_id": args.id,
        "kp_target": args.kp_target,
        "refs": [
            "docs/active/microduck-HD1910阶段C软件清单.md §3",
            "docs/hardware/microduck-采购清单.md §7.6",
            "tools/hd1910/stage0_software_prep.md",
        ],
        "gates": [asdict(r) for r in results],
        "all_pass": all(r.ok for r in results),
        "note": (
            "dry_run is checklist-only; live pass requires URT-2/URT-1 + HD-1910. "
            "Gate 0.3 (kt/R) is out of scope here — see bam_param_compare.md."
        ),
    }

    out = pathlib.Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.gate}: {r.detail}")
    print(f"all_pass = {payload['all_pass']}  mode={mode}")
    print(f"wrote {out}")
    # dry_run always exits 0 (skeleton readiness); live uses gate outcomes.
    if mode == "dry_run":
        return 0
    return 0 if payload["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
