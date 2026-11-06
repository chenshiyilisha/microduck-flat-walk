#!/usr/bin/env python3
"""每 tick 的总线预算：robotd 的 50 Hz 在 500 kbps 上到底装不装得下。

为什么单独查这一项
------------------
它**不报错**。总线占满了，每一包都还是合法的；症状是 `achieved_hz` 掉下来，
而 robotd 的 `update_gate.min_achieved_hz`（默认 45）会把一个"只是慢"的版本判成
unhealthy 并**自动回滚 release**（`main.rs:726` 的注释），于是一个总线预算问题
看起来像发布系统故障。ticker 又是 `MissedTickBehavior::Skip`，丢掉的周期不补，
所以超时不会被吸收、只会变成低频。

两个来源对质（沿用 §10 的规矩：不共用常量、不互相引用）
--------------------------------------------------------
A. **静态**：从 Rust 源码解析 `READ_ADDR` / `READ_LEN` / `GOAL_POSITION` /
   `NUM_JOINTS` / `IMU_DXL_ID` / `BAUD_RATE`，按 SCS v1 帧长算每 tick 字节数。
   帧长不是猜的：`frame = 4 + LEN`，`LEN = 参数个数 + 2`（飞特手册与社区实现一致）。
B. **实测**：台架上单颗，测 `ping` / `read(2)` / `read(15)` 的往返时间，用两个长度的
   **差分**拆出"每字节时间"，剩下的就是"每包固定开销"。

差分是关键：绝对时间里有 USB 转换器的批延迟（不可外推），差分里没有。
所以外推不按比例缩放，而是 `bytes × 每字节 + 固定开销`。

只读：不写任何寄存器，不动扭矩。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import statistics
import sys
import time

try:
    import serial
except ImportError:  # 自检路径不碰硬件
    serial = None

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[3]
UPSTREAM = REPO / ".upstream" / "DuckBuddy-main"
FEETECH_RS = UPSTREAM / "duck-control" / "src" / "feetech.rs"
MODEL_RS = UPSTREAM / "duck-control" / "src" / "model.rs"

# 8N1 下每字节 10 个位时间（1 起始 + 8 数据 + 1 停止）。
BITS_PER_BYTE = 10

# feetech.rs:37 的注释：reg6 取值 0..7
BAUD_OF_REG6 = {0: 1_000_000, 1: 500_000, 2: 250_000, 3: 128_000, 4: 115_200}


# ---------------------------------------------------------------- 协议帧长


def tx_frame_len(n_params: int) -> int:
    """指令帧：FF FF | id | len | inst | params | chk，len = n_params + 2，整帧 = 4 + len。"""
    return n_params + 6


def rx_frame_len(n_data: int) -> int:
    """响应帧：FF FF | id | len | err | data | chk，len = n_data + 2，整帧 = 4 + len。"""
    return n_data + 6


def tick_bytes(n_read: int, read_len: int, n_write: int, write_len: int) -> dict:
    """一次 tick 的字节数，收发分开列。

    sync_read 的 params = 起始地址 + 长度 + N 个 id；响应每颗一帧。
    sync_write 的 params = 起始地址 + 长度 + N × (id + 数据)。
    """
    read_tx = tx_frame_len(2 + n_read)
    read_rx = n_read * rx_frame_len(read_len)
    write_tx = tx_frame_len(2 + n_write * (1 + write_len))
    return {
        "read_tx": read_tx,
        "read_rx": read_rx,
        "write_tx": write_tx,
        "write_rx": 0,
        "total": read_tx + read_rx + write_tx,
    }


def wire_seconds(n_bytes: int, baud: int) -> float:
    return n_bytes * BITS_PER_BYTE / baud


def per_byte_us(baud: int, ratio: float = 1.0) -> float:
    """目标波特率下的每字节时间，乘上实测校正因子。

    ⚠️ 实测的"每字节时间"是**在台架那个波特率下**测的，不能直接搬到另一个波特率上。
    能搬的只有无量纲比值（实测/理论）：11 µs @1 Mbps 就是 1.10×，那么 @500 kbps
    是 20×1.10 = 22 µs，不是 11 µs。这里差 2× —— 是这一版差点发出去的那个错。
    """
    return BITS_PER_BYTE / baud * 1e6 * ratio


# ---------------------------------------------------------------- 源码常量


def read_source_constants(feetech: pathlib.Path = FEETECH_RS,
                          model: pathlib.Path = MODEL_RS) -> dict:
    """从 Rust 源码取常量。取不到就报错，不退回硬编码默认值。"""
    ft = feetech.read_text(encoding="utf-8")
    md = model.read_text(encoding="utf-8")

    def one(pattern: str, text: str, what: str) -> int:
        m = re.search(pattern, text)
        if not m:
            raise RuntimeError(f"源码里找不到 {what}（{pattern}）——先核对文件路径/版本")
        return int(m.group(1).replace("_", ""))

    def const_u8(name: str, text: str, depth: int = 0) -> int:
        """解析 `const X: u8 = N;`，右值可以是另一个常量名（如 READ_ADDR = PRESENT_POSITION）。"""
        if depth > 4:
            raise RuntimeError(f"常量 {name} 解析层数过深（循环引用？）")
        m = re.search(rf"const {name}: u8 = (\w+);", text)
        if not m:
            raise RuntimeError(f"源码里找不到 const {name}: u8 = ...;")
        val = m.group(1)
        return int(val) if val.isdigit() else const_u8(val, text, depth + 1)

    return {
        "read_addr": const_u8("READ_ADDR", ft),
        "read_len": one(r"const READ_LEN: u8 = (\d+);", ft, "READ_LEN"),
        "goal_pos": one(r"const GOAL_POSITION: u8 = (\d+);", ft, "GOAL_POSITION"),
        # 写包的目标寄存器只写 2 字节（goal position）。
        "goal_bytes": 2,
        "num_joints": one(r"pub const NUM_JOINTS: usize = (\d+);", md, "NUM_JOINTS"),
        "imu_id": one(r"pub const IMU_DXL_ID: u8 = (\d+);", md, "IMU_DXL_ID"),
        # feetech.rs 的 BAUD_RATE 才是 robotd 打开串口用的那个。
        # model.rs 另有一个同名 1 Mbps 常量，属 bus.rs（XL330）路径——不要混用。
        "baud": one(r"pub const BAUD_RATE: u32 = ([\d_]+);", ft, "feetech BAUD_RATE"),
        "baud_reg6": one(r"pub const BAUD_REGISTER_VALUE: u8 = (\d+);", ft, "BAUD_REGISTER_VALUE"),
        "read_timeout_ms": one(r"const READ_TIMEOUT: Duration = Duration::from_millis\((\d+)\);",
                               ft, "READ_TIMEOUT"),
    }


def defaults_from_source(params_rs: pathlib.Path | None = None) -> dict:
    """`[control] hz` 与 `update_gate.min_achieved_hz` 的默认值，从源码读。"""
    p = params_rs or (UPSTREAM / "robotd-params" / "src" / "lib.rs")
    text = p.read_text(encoding="utf-8")
    out = {}
    m = re.search(r"impl Default for Control\b[^{]*\{(.*?)\n\}", text, re.S)
    if m:
        h = re.search(r"hz: ([\d_.]+),", m.group(1))
        if h:
            out["hz"] = float(h.group(1).replace("_", ""))
    m = re.search(r"impl Default for UpdateGate\b[^{]*\{(.*?)\n\}", text, re.S)
    if m:
        g = re.search(r"min_achieved_hz: ([\d_.]+),", m.group(1))
        if g:
            out["min_achieved_hz"] = float(g.group(1).replace("_", ""))
        s = re.search(r"stall_periods: (\d+),", m.group(1))
        if s:
            out["stall_periods"] = int(s.group(1))
    return out


def mouth_is_limp(params_rs: pathlib.Path | None = None) -> bool:
    """`mouth_torque` 默认值决定写包是 15 个 ID 还是 14 个。

    `main.rs:1159`: `limp[9] = j == 9 && !mouth_torque && !mouth_wake`，
    所以默认 `mouth_torque = true` ⇒ 嘴**不是** limp ⇒ sync_write 连它一起写。
    """
    p = params_rs or (UPSTREAM / "robotd-params" / "src" / "lib.rs")
    m = re.search(r"mouth_torque: (true|false),", p.read_text(encoding="utf-8"))
    return (m.group(1) == "false") if m else True


# ---------------------------------------------------------------- 台架实测


def frame(pid: int, inst: int, params: bytes = b"") -> bytes:
    body = bytes([pid, len(params) + 2, inst, *params])
    return b"\xff\xff" + body + bytes([(~sum(body)) & 0xFF])


def _roundtrip(ser, payload: bytes, n_expect: int, pid: int, timeout: float) -> float | None:
    """发一帧、等到够 n_expect 字节，返回耗时（秒）。用 perf_counter，不用 time.time。"""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    ser.write(payload)
    ser.flush()
    got = 0
    while True:
        got = ser.in_waiting
        if got >= n_expect:
            dt = time.perf_counter() - t0
            break
        if time.perf_counter() - t0 > timeout:
            return None
    # 读到干净为止，避免残留影响下一发
    ser.read(ser.in_waiting)
    return dt


def measure(ser, pid: int, repeats: int = 40, timeout: float = 0.05) -> dict:
    """测 ping / read(2) / read(15) 的往返。取 min 与 p50。

    min 是链路固有延迟的下限估计（OS 调度只会加时间），p50 才是常见值。
    两者差距大 = 这台机器/这条 USB 有抖动，外推要按 p50 看。
    """
    out: dict[str, dict] = {}

    def run(name: str, payload: bytes, n_expect: int) -> None:
        xs = []
        misses = 0
        for _ in range(repeats):
            dt = _roundtrip(ser, payload, n_expect, pid, timeout)
            if dt is None:
                misses += 1
            else:
                xs.append(dt)
        out[name] = {
            "min": min(xs) if xs else None,
            "p50": statistics.median(xs) if xs else None,
            "n": len(xs),
            "miss": misses,
        }

    run("ping", frame(pid, 1), 6)
    run("read2", frame(pid, 2, bytes([56, 2])), rx_frame_len(2))
    run("read15", frame(pid, 2, bytes([56, 15])), rx_frame_len(15))
    return out


def split_transport(m: dict, baud: int) -> dict:
    """用 read2 与 read15 的差分求每字节时间，剩下的算每包固定开销。

    差分里不含 USB 批延迟（两包都有，抵消掉了），所以这是"总线上真正花的时间"。
    """
    na, nb = m["read2"], m["read15"]
    if not na["min"] or not nb["min"]:
        return {"ok": False, "why": "read2/read15 有测不到的"}
    tx_a = tx_frame_len(2)          # 8 字节
    tx_b = tx_frame_len(2)          # 8 字节，指令帧一样长
    rx_a = rx_frame_len(2)          # 8 字节
    rx_b = rx_frame_len(15)         # 21 字节
    d_bytes = (tx_b + rx_b) - (tx_a + rx_a)   # 13
    d_t = nb["min"] - na["min"]
    if d_t <= 0:
        return {"ok": False, "why": f"read15 不慢于 read2（差 {d_t*1e6:.1f} µs），差分法失效"}
    per_byte = d_t / d_bytes
    theory = BITS_PER_BYTE / baud
    fixed_a = na["min"] - (tx_a + rx_a) * per_byte
    return {
        "ok": True,
        "d_bytes": d_bytes,
        "d_us": d_t * 1e6,
        "per_byte_us": per_byte * 1e6,
        "theory_per_byte_us": theory * 1e6,
        "ratio": per_byte / theory,
        "fixed_us": fixed_a * 1e6,
    }


def extrapolate(per_byte_us: float, n_read: int, read_len: int,
                gap_us: float) -> dict:
    """16 个设备在 500 kbps 上的同步读时间。

    gap 是相邻两颗响应之间的空隙（总线换向 + 下一颗固件准备）。单颗测量**测不出**它，
    因为只有一颗就只有一个 gap。所以这里给出敏感性，而不是假装测到了。
    """
    read_tx = tx_frame_len(2 + n_read)
    read_rx = n_read * rx_frame_len(read_len)
    tx_us = read_tx * per_byte_us
    rx_us = read_rx * per_byte_us
    gaps = n_read * gap_us
    return {
        "read_tx_us": tx_us,
        "read_rx_us": rx_us,
        "gaps_us": gaps,
        "total_us": tx_us + rx_us + gaps,
    }


# ---------------------------------------------------------------- 输出


def render(st: dict, m: dict | None, sp: dict | None, dflt: dict,
           ratio: float, gap_table: list[float]) -> None:
    n_read = st["num_joints"] + 1          # 15 舵机 + IMU，读不看 limp
    n_write = st["num_joints"] - (1 if st["mouth_limp"] else 0)
    b = tick_bytes(n_read, st["read_len"], n_write, st["goal_bytes"])
    hz = dflt.get("hz", 50.0)
    period_us = 1e6 / hz

    print(f"== A. 静态模型（源码：feetech.rs / model.rs）==")
    print(f"  读 {n_read} 个设备（{st['num_joints']} 关节 + IMU {st['imu_id']}），"
          f"每颗 {st['read_len']} 字节 @ addr {st['read_addr']}")
    print(f"  写 {n_write} 个 ID，每颗 {st['goal_bytes']} 字节 @ addr {st['goal_pos']}"
          f"（mouth_torque 默认 {'true ⇒ 嘴也写' if not st['mouth_limp'] else 'false ⇒ 嘴不写'}）")
    print(f"  sync_read  发 {b['read_tx']:>3} B  →  收 {b['read_rx']:>3} B "
          f"（{n_read} × {rx_frame_len(st['read_len'])}）")
    print(f"  sync_write 发 {b['write_tx']:>3} B  →  收   0 B")
    print(f"  合计 {b['total']} B")

    print()
    print(f"== B. 纯传输时间（{BITS_PER_BYTE} bit/字节，无 gap、无 USB 延迟）==")
    print(f"  {'波特率':>10} {'读发':>8} {'读收':>8} {'写':>8} {'合计':>8} {'占周期':>8}")
    for baud in (1_000_000, 500_000):
        parts = {k: wire_seconds(v, baud) * 1e6 for k, v in b.items() if k != "total"}
        tot = wire_seconds(b["total"], baud) * 1e6
        print(f"  {baud:>10} {parts['read_tx']:>7.0f}us {parts['read_rx']:>7.0f}us "
              f"{parts['write_tx']:>7.0f}us {tot:>7.0f}us {tot/period_us:>7.0%}")
    t500 = wire_seconds(b["total"], 500_000) * 1e6
    print(f"  ⚠️ robotd 用的是 **500 kbps**（feetech.rs 的 BAUD_RATE）；"
          f"tree 里另有一个同名的 1 Mbps 常量属于 XL330 路径")

    if m is None or sp is None or not sp.get("ok"):
        print()
        print("== C. 台架实测 ==")
        print("  跳过" + (f"：{sp.get('why')}" if sp and not sp.get("ok") else ""))
        return

    print()
    print(f"== C. 台架实测（ID {st['probe_id']}，{st['probe_baud']} bps，每组 {m['ping']['n']} 次）==")
    for name, label in (("ping", "ping      "), ("read2", "read 2B   "), ("read15", "read 15B  ")):
        r = m[name]
        if r["min"] is None:
            print(f"  {label} 全部无应答（{r['miss']} 次）")
            continue
        print(f"  {label} min {r['min']*1e6:>7.1f} µs   p50 {r['p50']*1e6:>7.1f} µs   "
              f"未答 {r['miss']}")
    print(f"  差分（13 字节）：{sp['d_us']:.1f} µs ⇒ **每字节 {sp['per_byte_us']:.2f} µs**"
          f"（理论 {sp['theory_per_byte_us']:.2f}，比值 {sp['ratio']:.2f}）")
    print(f"  固定开销（每包）：{sp['fixed_us']:.1f} µs"
          f"（含 USB 批延迟，**不可**按设备数外推）")
    if abs(sp["ratio"] - 1.0) > 0.5:
        print(f"  ⚠️ 每字节时间是理论的 {sp['ratio']:.1f}×：实测波特率与配置不符，"
              f"先查 reg6 与 --baud")

    # 外部对质：单颗测不出"每颗间隙"，只能借一个多颗的公开实测把量级钉住
    if st["probe_baud"] == 1_000_000 and m["read15"]["min"]:
        one = m["read15"]["min"] * 1e6
        print(f"  外部对质：SO-101（6 颗 STS3215）sync_read 往返公开实测 ≈ 900 µs @ 1 Mbps；"
              f"本台单颗 read15 = {one:.0f} µs")
        print(f"            ⇒ 6 颗相对 1 颗的增量 ≈ {(900 - one) / 5:.0f} µs/颗"
              f"（两边读的字节数不同，只能当量级）")
        print(f"            ⇒ D 段 50–200 µs 那几档不是空想，500 µs 是悲观上界")

    print()
    print(f"== D. 外推到 {n_read} 个设备 @ 500 kbps（敏感性：每颗响应间隙）==")
    pb500 = per_byte_us(500_000, ratio)
    print(f"  传输基准 {pb500:.2f} µs/字节 = 20 µs(500k 理论) × {ratio:.2f}(实测校正)")
    print(f"  {'间隙':>8} {'读合计':>10} {'写入':>8} {'每 tick':>9} {'占 20 ms':>9} {'余量':>9}")
    write_us = wire_seconds(b["write_tx"], 500_000) * 1e6
    for gap in gap_table:
        e = extrapolate(pb500, n_read, st["read_len"], gap)
        tot = e["total_us"] + write_us
        print(f"  {gap:>7.0f}us {e['total_us']:>9.0f}us {write_us:>7.0f}us "
              f"{tot:>8.0f}us {tot/period_us:>8.0%} {period_us-tot:>8.0f}us")

    floor = dflt.get("min_achieved_hz")
    print()
    print("== E. 判据 ==")
    worst = extrapolate(pb500, n_read, st["read_len"], gap_table[-1])
    tot_worst = worst["total_us"] + write_us
    print(f"  最坏档（间隙 {gap_table[-1]:.0f} µs）每 tick 总线 {tot_worst/1000:.2f} ms，"
          f"策略推理可用 {period_us-tot_worst:.0f} µs")
    if floor:
        print(f"  robotd 的 unhealthy 门槛是 {floor:.0f} Hz ⇒ 周期超过 "
              f"{1e6/floor:.0f} µs 就开始报病")
        ok = tot_worst < 1e6 / floor
        print(f"  最坏档 {'仍在门槛内' if ok else '已越过门槛'}，"
              f"但门槛只管\"还活着\"，不管\"控制质量\"")
    print(f"  ⚠️ 这只算了传输。没算：策略推理（CPU/ONNX）、控制律、"
          f"IPC、以及**一次读超时 {st['read_timeout_ms']} ms > 一个周期**")
    print(f"     ⇒ 任何一次超时都直接吃掉整个 tick，且 Skip 语义不补")

    # F：波特率是板子的事。⚠️ 2026-11-06 定案已变：主控从 Radxa Zero 3W
    # (RK3566) 改成 Orange Pi Zero 3W (A733) —— 下面这段早期结论整个反过来。
    e500 = extrapolate(pb500, n_read, st["read_len"], 100.0)["total_us"] + write_us
    pb1m = per_byte_us(1_000_000, ratio)
    e1m = extrapolate(pb1m, n_read, st["read_len"], 100.0)["total_us"] + write_us
    print()
    print("== F. 500 kbps 是本方案（A733）自己的硬约束，不是「别人的板」 ==")
    print("  feetech.rs:34 原文：'Exactly representable on the A733's UART7 "
          "(24 MHz / 16 / 3). 1 Mbit/s is not.'")
    print("  ⇒ 本方案主控 = **Orange Pi Zero 3W (A733)**，正是 B 代 robotd 那块板。")
    print("    时钟分频只能精确给出 500 kbps；1M 在该 UART 上实测约 750 kbps，不是真 1M。")
    print("  ⇒ 所以 BAUD_RATE 保持 500_000，**不能**改成 1_000_000；")
    print("    reg6 必须逐颗从出厂 0（1 Mbps）改成 1（500 kbps），EEPROM 写入不可省。")
    print("    台架 1 Mbps 只是 URT-2 / USB-TTL 这一路的速率，不能据此推断整机可跑 1M。")
    print(f"  〔历史，已作废〕若换 RK3566 且 BAUD_RATE 改 1M：每 tick 总线 "
          f"{e1m/1000:.2f} ms（现在 {e500/1000:.2f} ms，间隙按 100 µs 估），")
    print("    且 reg6 可保持出厂 0。依据是 Radxa Zero 3 的 debug UART 默认 1 500 000 bps、")
    print("    RK3566 datasheet 'up to 4 Mbps'、上游主仓在 Zero 3W 上跑 1 Mbps —— ")
    print("    **这三条只对 RK3566 成立，A733 上不适用**。")
    print("  ⚠️ 编码陷阱（换板时才用得上）：Feetech 是 0=1M / 1=500k；")
    print("     model.rs 里那个 '3 = 1 Mbps' 是 **Dynamixel** 编码，套过来会写成 128 kbps = 失联。")


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    checks = []

    def check(name: str, got, want) -> None:
        checks.append((name, got == want, got, want))

    # 帧长：飞特手册 frame = 4 + LEN，LEN = params + 2
    check("ping 指令帧 6 字节", tx_frame_len(0), 6)
    check("read(1B addr,1B len) = 8 字节", tx_frame_len(2), 8)
    check("响应 2 字节数据 = 8 字节", rx_frame_len(2), 8)
    check("响应 15 字节数据 = 21 字节", rx_frame_len(15), 21)
    check("sync_read 16 个 id = 24 字节", tx_frame_len(2 + 16), 24)
    check("sync_write 15 id × 3B = 53 字节", tx_frame_len(2 + 15 * 3), 53)

    # 每 tick 字节数：读 16、写 15
    b = tick_bytes(16, 15, 15, 2)
    check("read_tx 24", b["read_tx"], 24)
    check("read_rx 336", b["read_rx"], 336)
    check("write_tx 53", b["write_tx"], 53)
    check("合计 413", b["total"], 413)
    # 嘴 limp 时少一颗
    check("嘴 limp 时写包 50 字节", tick_bytes(16, 15, 14, 2)["write_tx"], 50)

    # 传输时间：413 B @500k = 413*10/500000 = 8.26 ms
    check("413 B @500k ≈ 8.26 ms", round(wire_seconds(413, 500_000) * 1e3, 2), 8.26)
    check("413 B @1M ≈ 4.13 ms", round(wire_seconds(413, 1_000_000) * 1e3, 2), 4.13)

    # 差分法：造一组"每字节 10 µs、固定 80 µs"的合成读数，必须还原
    fake = {
        "read2": {"min": (8 + 8) * 10e-6 + 80e-6, "p50": None, "n": 1, "miss": 0},
        "read15": {"min": (8 + 21) * 10e-6 + 80e-6, "p50": None, "n": 1, "miss": 0},
    }
    sp = split_transport(fake, 1_000_000)
    check("差分还原每字节 10 µs", round(sp["per_byte_us"], 3), 10.0)
    check("差分还原固定开销 80 µs", round(sp["fixed_us"], 1), 80.0)
    check("比值 1.00", round(sp["ratio"], 2), 1.0)

    # 负对照：波特率写错一半 ⇒ 每字节时间翻倍，比值必须变 2
    fake2 = {
        "read2": {"min": (8 + 8) * 20e-6 + 80e-6, "p50": None, "n": 1, "miss": 0},
        "read15": {"min": (8 + 21) * 20e-6 + 80e-6, "p50": None, "n": 1, "miss": 0},
    }
    sp2 = split_transport(fake2, 1_000_000)
    check("负对照：波特率差一半 ⇒ 比值 2", round(sp2["ratio"], 2), 2.0)

    # 负对照：read15 不慢于 read2 ⇒ 必须判失效，不能编一个 0
    fake3 = {
        "read2": {"min": 300e-6, "p50": None, "n": 1, "miss": 0},
        "read15": {"min": 300e-6, "p50": None, "n": 1, "miss": 0},
    }
    check("负对照：无差分 ⇒ 判失效", split_transport(fake3, 1_000_000)["ok"], False)

    # 外推：间隙单调、gap=0 时等于纯传输
    e0 = extrapolate(10.0, 16, 15, 0.0)
    check("gap=0 时读传输 = 360×10 µs", round(e0["total_us"], 1), 3600.0)
    e1 = extrapolate(10.0, 16, 15, 100.0)
    check("16 颗 ×100 µs 间隙 = 1600 µs", round(e1["gaps_us"], 1), 1600.0)
    check("间隙单调", e1["total_us"] > e0["total_us"], True)

    # 跨波特率只能搬"比值"，不能搬绝对时间（这一版差点发出去的那个 2× 错）
    check("每字节 @1M、ratio 1.1 = 11 µs", round(per_byte_us(1_000_000, 1.1), 1), 11.0)
    check("每字节 @500k、ratio 1.1 = 22 µs", round(per_byte_us(500_000, 1.1), 1), 22.0)
    check("负对照：同 ratio 下 500k 恰为 1M 的 2×",
          round(per_byte_us(500_000, 1.0) / per_byte_us(1_000_000, 1.0), 6), 2.0)
    # 若把 1 Mbps 的实测绝对时间直接搬到 500 kbps，会低估一半 —— 断言它确实不同
    check("负对照：搬绝对值会差 2×（不是四舍五入问题）",
          round(11.05 / per_byte_us(500_000, 1.105), 2), 0.5)

    good = sum(1 for _, ok, _, _ in checks if ok)
    for name, ok, got, want in checks:
        if not ok:
            print(f"  ✗ {name}: got {got!r}, want {want!r}")
    print(f"{good}/{len(checks)} 自检通过")
    return 0 if good == len(checks) else 1


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="每 tick 总线预算（只读，不动扭矩）")
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--id", type=int, default=10, help="台架上那唯一一颗的 ID")
    ap.add_argument("--baud", type=int, default=1_000_000,
                    help="台架实测用的波特率。台架那颗是出厂 reg6=0 ⇒ 1 Mbps；"
                         "粗估 500 kbps 请传 500000，但那时 --baud 与 reg6 必须一致")
    ap.add_argument("--repeats", type=int, default=40)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    st = read_source_constants()
    dflt = defaults_from_source()
    st["mouth_limp"] = mouth_is_limp()
    st["probe_id"] = args.id
    st["probe_baud"] = args.baud

    m = sp = None
    if serial is not None:
        try:
            ser = serial.Serial(args.port, args.baud, bytesize=8, parity="N",
                                stopbits=1, timeout=0.05)
        except Exception as e:  # noqa: BLE001
            print(f"(端口 {args.port} 打不开：{e} —— 只输出静态模型)\n")
        else:
            try:
                m = measure(ser, args.id, repeats=args.repeats)
                sp = split_transport(m, args.baud)
            finally:
                ser.close()

    # 实测到的每字节时间若不可信，退回纯理论（并明说）。注意跨波特率只能搬"比值"。
    if sp and sp.get("ok") and abs(sp["ratio"] - 1.0) < 0.5:
        ratio = sp["ratio"]
        basis = (f"实测 {sp['per_byte_us']:.2f} µs/字节 @ {args.baud} bps "
                 f"= {ratio:.2f}× 该波特率的理论值")
    else:
        ratio = 1.0
        basis = "纯理论（台架实测不可用或不自洽，未校正）"

    render(st, m, sp, dflt, ratio, [50.0, 100.0, 200.0, 500.0])
    print(f"\n  外推基准：{basis}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
