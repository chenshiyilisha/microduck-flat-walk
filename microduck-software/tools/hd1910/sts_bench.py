#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Stage-0 URT-2 / URT-1 / HD-1910 bench gates (G0 in the 2026-11-06 plan).

Sources
-------
* ``docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md`` §1.1 / §4 (G0)
* ``docs/active/microduck-HD1910阶段C软件清单.md`` §3
* ``docs/hardware/microduck-采购清单.md`` §1 / §7.6
* ``tools/hd1910/stage0_software_prep.md``

Hardware: Feetech **URT-2 (preferred) or URT-1** (not U2D2) + one HD-1910 on
**TTL**. 2026-11-03 改判：URT-2 的 **V1/G 5.08 端子本就是外电输入**（规格书
"TTL Bus Power DC 4.8-12 V"），外电 7.4 V 从这里进，**不倒灌 USB**；原文
"leave V1 empty / 外电直供舵机 V/G" 已作废。三条硬约束：
  1. 三档开关**必须拨 5V**（拨 VCC 会把 7.4 V 抬到信号线烧舵机）；
  2. AMP2.0 舵机线插不进 URT-2 的 2.5 mm 白座 ⇒ 需 **2.0->2.5 3P 转接线**；
  3. 上电顺序 **先插 USB、后给舵机上电**（反了总线被压到约 2.1 V，一片不应答，
     见 ``deploy_import_checklist.md`` H1）。
软件边界：这里只做短台架读写判据，**不写 robotd / bus daemon**（方案 §5 / 阶段C §6）。
帧实现复用 ``servo_probe/hd1910_readonly.py``，寄存器表复用
``servo_probe/hd1910_ident.py``（TELEM_LEN=15 / 56..70），不另造第二套协议。

Five gates
----------
0.1 ping；0.2 50 Hz 单字节事务 median <= 5 ms 且 0 错误；
0.3 遥测块合理值（位置/电压/温度）+ 可选 goal 回读；
0.4 50 Hz 长跑（默认 60 s，可设 3600 s）0 错误、温度不越阈值；
0.5 运行时 P == 部署档 kp_fw。

⚠️ 两个口径不能互套：单颗 5 ms 是 URT-2 台架闸门；整机 16 设备在 500 kbps
下约 10.9 ms / 20 ms（``deploy_import_checklist.md`` §B13）。
⚠️ 负载/电流**只记录不判**：台架实测 reg60 恒 0、reg69 正弦中读到 16000 量级，
读数与物理上下界矛盾 ⇒ 错的是读数，不是执行器。

Without hardware
----------------
``--dry-run`` 合成一次全 PASS 并写 JSON（清单彩排，不作为证据）。
``--selftest`` 用注入故障的假总线跑**负对照**：每个被故意改坏的量都必须让对应
闸门变红，健康总线必须全绿。只见过绿色的断言不是证据。

With hardware
-------------
Pass ``--port COMx`` (Windows) or ``/dev/ttyUSBx`` (``pip install pyserial``).
We do **not** vendor the FTServo SDK in-tree.

⚠️ ``--id`` 默认 1 是**出厂新舵机**口径。本机台架这颗在 2026-11-02 已改成
**ID 10**（见 ``docs/active/microduck-HD1910软件方案.md`` 行 1315 的 EEPROM 备份），
跑真机要显式 ``--id 10``；不确定就先按 1 Mbps 扫 ID。

2026-11-06 首次真机（COM3 / CH343 / 1 Mbps / ID 10 / 60 s）：五闸全绿，
0.2 median 1.75 ms、0.4 3000 帧 0 错误且温度 25→25 °C、0.3 ``goal_echo=ok``、
0.5 ``reg50=8``。报告 ``out/g0_60s.json``（``out/`` 被 gitignore，不入库）。
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

# 部署档改判（2026-11-04）：原写 5（P3 裁决），但 plant 已定 `hd1910_kp8`
# —— P8 在 kp8 上 vx 0.2069、P5 线只有 0.1129，且 P8 在 kp5 上 7/8 摔（无降级模式）。
# 台架读数只有对齐 reg50=8 才代表部署。与 `servo_probe/hd1910_ident.py:127` 的
# KP_FW_DEPLOY = 8 同源，别让两份工具各说一个数。
# 2026-11-01 曾实测出厂 ID 1 的 reg21=32 / reg50=32；之后用
# `set_gains_all.py --persist` 改过台架这颗（现 ID 10）。
# ✅ 2026-11-06 真机回读：reg21=8（EEPROM）、reg50=8（RAM）、reg55=1（锁已上），
#   断电后仍是 8 ⇒ 0.5 现在是真 PASS，不是「恰好没 FAIL」。
# 若换一颗没改过的舵机，0.5 仍会**正确地**报 FAIL；那不是 bug，是提醒。
KP_FW_TARGET = 8
KP_FW_FACTORY_ROM = 32
TXN_BUDGET_MS = 5.0  # gate 0.2: one sync txn on the URT-2 bench
HZ_TARGET = 50.0

# ---- 遥测块（hd1910_ident.py:103/123，56..70 共 15 B）----
# 布局：56-57 pos / 58-59 speed / 60-61 load / 62 volt(0.1 V) / 63 temp(C)
#       / 64 ? / 65 status / 66 moving / 67-68 goal 镜像 / 69-70 current
REG_TELEM = 56
TELEM_LEN = 15
REG_GOAL = 42
OFF_VOLT = 6
OFF_TEMP = 7
OFF_GOAL = 11
OFF_LOAD = 4
OFF_CURRENT = 13

# 闸门阈值一律取固定物理量级，**不取自被测量本身**。
VOLT_MIN_V = 4.0       # HD-1910 规格下限 / 厂商 reg15 最低输入 40 = 4.0 V
VOLT_MAX_V = 8.7       # 规格上限 8.4 V，留 0.3 V 读数容差；2S LiHV 8.7 由 max_volts 拦
TEMP_MIN_C = 5.0       # 室温下限，防「传感器没起来」的 0 被当成合理值
TEMP_MAX_C = 85.0      # 舵机过热 latch 在 reg13 = 80 C，留 5 C 余量
POS_RAW_MAX = 4095     # 12 位磁编码，纯物理上下界，不依赖任何解码函数
SOAK_SECONDS_DEFAULT = 60.0    # 路线 B §7.6 温升判据 60 s；1 h 用 --soak-seconds 3600
MAX_TEMP_SOAK_C = 55.0        # 采购清单 §1；路线 B §7.6 写 60，默认取更严的 55


@dataclass
class GateResult:
    gate: str
    ok: bool
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


class StsBus(Protocol):
    """Minimal surface the stage-0 gates need. Plug SMS_STS / scservo here."""

    def ping(self, servo_id: int) -> bool: ...
    def read_block(self, servo_id: int, reg: int, count: int) -> bytes: ...
    def write_bytes(self, servo_id: int, reg: int, data: bytes) -> None: ...
    def read_u8(self, servo_id: int, reg: int) -> int: ...
    def write_u8(self, servo_id: int, reg: int, value: int) -> None: ...
    def close(self) -> None: ...


class DryRunBus:
    """Synthetic bus. Parameterised so ``--selftest`` can inject single faults.

    刻意让每一个故障都只改**一个量**：负对照的意义是证明「这个闸门真的在盯这个量」，
    而不是「总有个地方变红了」。
    """

    def __init__(
        self,
        pretend_id: int = 1,
        pretend_p: int = KP_FW_TARGET,
        volt: float = 4.6,          # 台架欠压实测值
        temp: float = 29.0,
        pos_raw: int = 2048,
        goal_raw: int | None = None,
        ping_ok: bool = True,
        inject_latency_ms: float = 0.0,
        read_fail_every: int = 0,
        goal_echo_broken: bool = False,
    ) -> None:
        self._id = pretend_id
        self._p = pretend_p
        self._closed = False
        self.volt = volt
        self.temp = temp
        self.pos_raw = pos_raw
        self.goal_raw = pos_raw if goal_raw is None else goal_raw
        self.ping_ok = ping_ok
        self.inject_latency_ms = inject_latency_ms
        self.read_fail_every = read_fail_every
        self.goal_echo_broken = goal_echo_broken
        self._reads = 0

    def _telem(self) -> bytes:
        b = bytearray(TELEM_LEN)
        b[0] = self.pos_raw & 0xFF
        b[1] = (self.pos_raw >> 8) & 0xFF
        b[OFF_VOLT] = max(0, min(255, round(self.volt * 10)))
        b[OFF_TEMP] = max(0, min(255, round(self.temp)))
        b[OFF_GOAL] = self.goal_raw & 0xFF
        b[OFF_GOAL + 1] = (self.goal_raw >> 8) & 0xFF
        return bytes(b)

    def ping(self, servo_id: int) -> bool:
        return self.ping_ok and servo_id == self._id

    def read_block(self, servo_id: int, reg: int, count: int) -> bytes:
        self._reads += 1
        if self.inject_latency_ms:
            time.sleep(self.inject_latency_ms / 1000.0)
        if self.read_fail_every and self._reads % self.read_fail_every == 0:
            raise OSError("synthetic CRC/timeout")
        if servo_id != self._id:
            raise OSError(f"no reply from id {servo_id}")
        if reg == REG_TELEM and count == TELEM_LEN:
            return self._telem()
        if count == 1:
            if reg == REG_ID:
                return bytes([self._id])
            if reg == REG_P:
                return bytes([self._p])
            if reg == REG_BAUD:
                return bytes([0])  # Feetech baud index 0 == 1 Mbps
            idx = reg - REG_TELEM
            if 0 <= idx < TELEM_LEN:
                return self._telem()[idx:idx + 1]
            return b"\x00"
        return bytes(count)

    def read_u8(self, servo_id: int, reg: int) -> int:
        return self.read_block(servo_id, reg, 1)[0]

    def write_bytes(self, servo_id: int, reg: int, data: bytes) -> None:
        if reg == REG_GOAL and len(data) >= 2 and not self.goal_echo_broken:
            self.goal_raw = data[0] | (data[1] << 8)
        if reg == REG_ID and len(data) >= 1:
            self._id = data[0]
        if reg == REG_P and len(data) >= 1:
            self._p = data[0]

    def write_u8(self, servo_id: int, reg: int, value: int) -> None:
        self.write_bytes(servo_id, reg, bytes([value & 0xFF]))

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

    def read_block(self, servo_id: int, reg: int, count: int) -> bytes:
        # 复用同一份 query —— 不写第二套帧解析（两个实现会互相抵消）。
        raw = self._ro.query(self._ser, servo_id, reg, count)
        if raw is None or len(raw) != count:
            raise OSError(
                f"no/short reply: READ reg {reg} len {count} from id {servo_id}"
            )
        return bytes(raw)

    def read_u8(self, servo_id: int, reg: int) -> int:
        return self.read_block(servo_id, reg, 1)[0]

    def write_bytes(self, servo_id: int, reg: int, data: bytes) -> None:
        self._write(servo_id, reg, bytes(data))

    def write_u8(self, servo_id: int, reg: int, value: int) -> None:
        self.write_bytes(servo_id, reg, bytes([value & 0xFF]))

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


def gate_03_telemetry(
    bus: StsBus, servo_id: int, write_goal_echo: bool = False
) -> GateResult:
    """四项遥测的「量级对不对」，不问「结果对不对」。

    位置用原始 12 位值判物理上下界，不依赖 signed_mag/load_mag 解码；
    负载/电流**只记录不判**（台架读数坏，见模块 docstring）。
    ``write_goal_echo`` 把当前位置原样写回 goal 再读镜像 —— **不改 reg40**
    （2026-11-06 真机实测 reg40=1，扭矩本来就是开的；因为目标 == 当前位置，
    仍不产生位移），与 H8 的「15 颗同时上扭矩 inrush」不是同一件事，
    却验证了「写指令确实生效」。前提：单颗静止台架，位置在动时别开这个选项。
    """
    try:
        blk = bus.read_block(servo_id, REG_TELEM, TELEM_LEN)
    except Exception as exc:  # noqa: BLE001 — 总线 I/O 各家实现不同
        return GateResult(
            gate="0.3_telemetry",
            ok=False,
            detail=f"cannot read telemetry 56..70: {exc}",
            metrics={"block_len": 0},
        )
    if len(blk) != TELEM_LEN:
        return GateResult(
            gate="0.3_telemetry",
            ok=False,
            detail=f"short telemetry block: {len(blk)} of {TELEM_LEN} bytes",
            metrics={"block_len": len(blk)},
        )

    pos_raw = blk[0] | (blk[1] << 8)
    volt = blk[OFF_VOLT] / 10.0
    temp = float(blk[OFF_TEMP])
    load_raw = blk[OFF_LOAD] | (blk[OFF_LOAD + 1] << 8)
    cur_raw = blk[OFF_CURRENT] | (blk[OFF_CURRENT + 1] << 8)

    checks = {
        "block_len": True,
        "volt_in_range": VOLT_MIN_V <= volt <= VOLT_MAX_V,
        "temp_in_range": TEMP_MIN_C <= temp <= TEMP_MAX_C,
        "pos_raw_in_range": 0 <= pos_raw <= POS_RAW_MAX,
    }
    echo: bool | None = None
    echo_err = ""
    if write_goal_echo:
        try:
            bus.write_bytes(servo_id, REG_GOAL, bytes(blk[0:2]))
            blk2 = bus.read_block(servo_id, REG_TELEM, TELEM_LEN)
            echo = (
                len(blk2) == TELEM_LEN
                and bytes(blk2[OFF_GOAL:OFF_GOAL + 2]) == bytes(blk[0:2])
            )
        except Exception as exc:  # noqa: BLE001
            echo = False
            echo_err = f" ({exc})"
        checks["goal_echo"] = bool(echo)

    bad = [k for k, v in checks.items() if not v]
    ok = not bad
    detail = (
        f"volt={volt:.1f}V temp={temp:.0f}C pos_raw={pos_raw} "
        f"load_raw={load_raw} cur_raw={cur_raw}"
        + (f" goal_echo={'ok' if echo else 'FAIL'}{echo_err}" if echo is not None else "")
        + ("" if ok else f" — FAIL checks: {','.join(bad)}")
        + " | load/current logged only, never judged"
    )
    return GateResult(
        gate="0.3_telemetry",
        ok=ok,
        detail=detail,
        metrics={
            "volt_v": volt,
            "temp_c": temp,
            "pos_raw": pos_raw,
            "load_raw": load_raw,
            "cur_raw": cur_raw,
            "goal_echo": echo,
            "checks": checks,
            "ranges": {
                "volt_v": [VOLT_MIN_V, VOLT_MAX_V],
                "temp_c": [TEMP_MIN_C, TEMP_MAX_C],
                "pos_raw": [0, POS_RAW_MAX],
            },
        },
    )


def gate_04_soak(
    bus: StsBus,
    servo_id: int,
    seconds: float = SOAK_SECONDS_DEFAULT,
    max_temp_c: float = MAX_TEMP_SOAK_C,
) -> GateResult:
    """50 Hz 长跑：0 错误 + 事务中位数 + 温度峰值。

    与 gate 0.2 的区别：这里读的是 **15 B 遥测块**（真实负载），0.2 读 1 B。
    两个 median 不是同一个量，报告里分开列。
    """
    n = max(1, int(round(seconds * HZ_TARGET)))
    times_ms: list[float] = []
    temps: list[float] = []
    errors = 0
    last_err = ""
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            blk = bus.read_block(servo_id, REG_TELEM, TELEM_LEN)
            if len(blk) == TELEM_LEN:
                temps.append(float(blk[OFF_TEMP]))
            else:
                errors += 1
                last_err = f"short block ({len(blk)} B)"
        except Exception as exc:  # noqa: BLE001
            errors += 1
            last_err = str(exc)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        times_ms.append(dt_ms)
        sleep = max(0.0, (1.0 / HZ_TARGET) - (dt_ms / 1000.0))
        if sleep:
            time.sleep(sleep)

    times_ms.sort()
    median = times_ms[len(times_ms) // 2]
    p95 = times_ms[min(len(times_ms) - 1, int(len(times_ms) * 0.95))]
    peak = max(temps) if temps else None
    checks = {
        "zero_errors": errors == 0,
        "median_txn_le_5ms": median <= TXN_BUDGET_MS,
        "temp_below_limit": peak is not None and peak <= max_temp_c,
    }
    bad = [k for k, v in checks.items() if not v]
    ok = not bad
    return GateResult(
        gate="0.4_soak_50hz",
        ok=ok,
        detail=(
            f"n={n} dur={seconds:g}s median={median:.2f}ms p95={p95:.2f}ms "
            f"errors={errors} temp_peak={peak if peak is not None else 'n/a'}C "
            f"limit={max_temp_c:g}C"
            + (f" last_err={last_err}" if last_err else "")
            + ("" if ok else f" — FAIL checks: {','.join(bad)}")
        ),
        metrics={
            "samples": n,
            "seconds": seconds,
            "median_ms": round(median, 3),
            "p95_ms": round(p95, 3),
            "errors": errors,
            "temp_peak_c": peak,
            "max_temp_c": max_temp_c,
            "checks": checks,
        },
    )


def gate_05_kp(bus: StsBus, servo_id: int, target: int = KP_FW_TARGET) -> GateResult:
    try:
        p = int(bus.read_u8(servo_id, REG_P))
    except Exception as exc:  # noqa: BLE001 — 舵机不在总线上是很常见的情况
        # 15 颗巡检时少接一颗不能让整个工具崩掉。
        return GateResult(
            gate=f"0.5_firmware_P_eq_{target}",
            ok=False,
            detail=f"cannot read reg {REG_P} from id {servo_id}: {exc}",
            metrics={"reg": REG_P, "P": None, "kp_fw_target": target},
        )
    ok = p == target
    hint = ""
    if not ok and p == KP_FW_FACTORY_ROM:
        hint = (
            f" — 实测是出厂 ROM 默认 {KP_FW_FACTORY_ROM}，真机尚未对齐部署档 kp8。"
            f" 部署前须把 reg {REG_P} 写成 {target}（RAM 增益，掉电回落 reg21="
            f"{KP_FW_FACTORY_ROM} ⇒ 每次上电都要写，或按 H 段时序把 EEPROM reg21 一并改掉；"
            f" robotd 每次启动还会按 gain*position_kp/200 重写 reg50）"
        )
    return GateResult(
        gate=f"0.5_firmware_P_eq_{target}",
        ok=ok,
        detail=f"reg {REG_P} P={p} (want {target} = deployment kp_fw){hint}",
        metrics={"reg": REG_P, "P": p, "kp_fw_target": target},
    )


def run_gates(
    bus: StsBus,
    servo_id: int,
    samples: int,
    kp_target: int = KP_FW_TARGET,
    soak_seconds: float = SOAK_SECONDS_DEFAULT,
    max_temp_c: float = MAX_TEMP_SOAK_C,
    write_goal_echo: bool = False,
) -> list[GateResult]:
    return [
        gate_01_ping(bus, servo_id),
        gate_02_txn(bus, servo_id, samples=samples),
        gate_03_telemetry(bus, servo_id, write_goal_echo=write_goal_echo),
        gate_04_soak(bus, servo_id, seconds=soak_seconds, max_temp_c=max_temp_c),
        gate_05_kp(bus, servo_id, target=kp_target),
    ]


def selftest() -> int:
    """负对照：故意改坏一个量，对应闸门必须变红。只见过绿色的断言不是证据。

    每个 case 只动一个参数；``soak_overheat`` 特意取 60 C —— 它在闸门 0.3 的
    「合理值」区间内、却越过闸门 0.4 的 55 C，用来证明两个阈值互不依赖。
    """
    # 阈值不得取自被测量本身：健康读数必须严格落在窗内，且不贴边。
    thresholds_ok = (
        VOLT_MIN_V < 4.6 < VOLT_MAX_V
        and TEMP_MIN_C < 29.0 < MAX_TEMP_SOAK_C < 60.0 < TEMP_MAX_C
        and 0 <= 2048 <= POS_RAW_MAX
        and KP_FW_TARGET == 8
    )

    common = dict(
        samples=12,
        soak_seconds=0.24,
        max_temp_c=MAX_TEMP_SOAK_C,
        kp_target=KP_FW_TARGET,
    )
    cases: list[tuple[str, dict, str | None, bool]] = [
        # name, DryRunBus kwargs, 期望变红的 gate（None = 期望全绿）, 是否全绿
        ("healthy", {}, None, True),
        ("ping_silenced", {"ping_ok": False}, "0.1_ping_id_1mbps", False),
        ("slow_txn", {"inject_latency_ms": 6.0}, "0.2_50hz_txn_le_5ms", False),
        ("volt_zero", {"volt": 0.0}, "0.3_telemetry", False),
        ("temp_255", {"temp": 255.0}, "0.3_telemetry", False),
        ("pos_over_range", {"pos_raw": 5000}, "0.3_telemetry", False),
        ("soak_overheat", {"temp": 60.0}, "0.4_soak_50hz", False),
        ("crc_errors", {"read_fail_every": 3}, "0.4_soak_50hz", False),
        ("wrong_kp", {"pretend_p": KP_FW_FACTORY_ROM}, "0.5_firmware_P_eq_8", False),
    ]

    passed = 0
    total = len(cases) + 3  # + 阈值独立性、goal echo 健康、goal echo 故意坏
    if thresholds_ok:
        passed += 1
        print("[PASS] thresholds: fixed physical ranges, healthy readings strictly inside")
    else:
        print("[FAIL] thresholds: a threshold was derived from the measured value")

    for name, kwargs, red_gate, want_all_green in cases:
        bus = DryRunBus(**kwargs)
        try:
            results = run_gates(bus, 1, **common)
        finally:
            bus.close()
        by_name = {r.gate: r for r in results}
        all_green = all(r.ok for r in results)
        ok = (all_green == want_all_green) and (
            red_gate is None or
            (red_gate in by_name and not by_name[red_gate].ok)
        )
        passed += int(ok)
        tag = "PASS" if ok else "FAIL"
        label = f"{red_gate} red" if red_gate else "all green"
        gates_str = ", ".join(
            f"{k}={'ok' if v.ok else 'red'}" for k, v in by_name.items()
        )
        extra = "" if ok else f"  (got all_green={all_green}; {gates_str})"
        print(f"[{tag}] {name}: expect {label}{extra}")

    # goal echo 单独一组：同一个写入动作，镜像跟不跟随必须能区分。
    for name, broken, want_ok in (
        ("goal_echo_healthy", False, True),
        ("goal_echo_broken", True, False),
    ):
        bus = DryRunBus(goal_raw=0, goal_echo_broken=broken)
        try:
            r = gate_03_telemetry(bus, 1, write_goal_echo=True)
        finally:
            bus.close()
        ok = r.ok == want_ok
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got ok={r.ok}, want {want_ok}")

    print(f"selftest: {passed}/{total} passed")
    return 0 if passed == total else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--selftest",
        action="store_true",
        help="run negative controls on a synthetic bus; no serial port needed",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="no serial, synthetic pass (default if --port omitted)",
    )
    ap.add_argument("--port", default=None, help="URT-2/URT-1 serial port, e.g. COM3")
    ap.add_argument(
        "--id", type=int, default=1,
        help="servo ID (default 1 = factory; this lab's single servo is ID 10)",
    )
    ap.add_argument("--samples", type=int, default=100, help="txn samples for gate 0.2")
    ap.add_argument(
        "--soak-seconds",
        type=float,
        default=SOAK_SECONDS_DEFAULT,
        help="gate 0.4 duration at 50 Hz (default 60 s; use 3600 for the 1 h check)",
    )
    ap.add_argument(
        "--max-temp-c",
        type=float,
        default=MAX_TEMP_SOAK_C,
        help="gate 0.4 temperature ceiling (default 55 C; route B allows 60)",
    )
    ap.add_argument(
        "--write-goal-echo",
        action="store_true",
        help="gate 0.3 also writes current position back to goal and reads the mirror",
    )
    ap.add_argument(
        "--kp-target",
        type=int,
        default=KP_FW_TARGET,
        help=f"expected runtime P in reg {REG_P} (default {KP_FW_TARGET} = deployment kp_fw)",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="write JSON report")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    dry = args.dry_run or not args.port
    if dry:
        bus: StsBus = DryRunBus(pretend_id=args.id, pretend_p=KP_FW_TARGET)
        mode = "dry_run"
        soak_seconds = min(args.soak_seconds, 0.2)  # 彩排不真等 60 s
    else:
        bus = try_open_live(args.port)
        mode = "live"
        soak_seconds = args.soak_seconds

    try:
        results = run_gates(
            bus,
            args.id,
            args.samples,
            kp_target=args.kp_target,
            soak_seconds=soak_seconds,
            max_temp_c=args.max_temp_c,
            write_goal_echo=args.write_goal_echo,
        )
    finally:
        bus.close()

    payload = {
        "tool": "sts_bench",
        "mode": mode,
        "port": args.port,
        "servo_id": args.id,
        "kp_target": args.kp_target,
        "soak_seconds": soak_seconds,
        "max_temp_c": args.max_temp_c,
        "write_goal_echo": args.write_goal_echo,
        "refs": [
            "docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md §1.1/§4 (G0)",
            "docs/hardware/microduck-采购清单.md §1/§7.6",
            "tools/hd1910/servo_probe/hd1910_ident.py (register map 56..70)",
            "tools/hd1910/deploy_import_checklist.md H1/H8/B13/B16",
        ],
        "gates": [asdict(r) for r in results],
        "all_pass": all(r.ok for r in results),
        "note": (
            "dry_run is checklist-only, NOT evidence; live pass requires URT-2/URT-1 "
            "+ HD-1910. 5 ms is the single-servo bench gate, not the 16-device "
            "500 kbps budget (about 10.9 ms of 20 ms). Load/current are logged but "
            "never judged (reg60 stuck at 0, reg69 reads in the 16000 range). "
            "kt/R / backlash characterisation is out of scope here - see "
            "bam_param_compare.md and servo_probe/hd1910_ident.py."
        ),
    }

    out = pathlib.Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"[{mark}] {r.gate}: {r.detail}")
    print(f"all_pass = {payload['all_pass']}  mode={mode}")
    print(f"wrote {out}")
    if mode == "dry_run":
        return 0
    return 0 if payload["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
