#!/usr/bin/env python3
"""HD-1910-C001 辨识台架 —— 阶跃响应 / 死区 / 回差 / 遥测。

⚠️ **开扭矩的子命令需要 7.4 V 限流电源**（负载电流 690 mA @6 V，USB 5 V 档带不动，
   且 USB 档没有可调限流）。电源到货前用 `--dry-run` 验证指标计算，不碰硬件。

子命令：
    telem    --seconds 10            遥测流（50 Hz，只读；USB 档可跑）
    step     --steps 200             PD 阶跃录制 → CSV + 超调/稳态误差/整定  [需电源]
    deadzone --max-step 20           双向最小可动步（不灵敏区）              [需电源]
    backlash --approach 100          双向趋近同一目标 → 回差                 [需电源]

协议不自己拼：
  - PING / READ 复用同目录 `hd1910_readonly.py`（kissqy hd1910.rs 寄存器表）。
    **不复制一份**——两份实现会互抵，历史上踩过（见 MEMORY §7/§8）。
  - WRITE inst=0x03、params=[addr]+data、应答无参数，
    出处 `microduck-replica rl-series/scripts/hl2915_bench.py:156-159`（帧同族可抄）。

★ HD-1910 与 HL2915 的关键差异（抄范本时最容易错的地方）：
  - 位置/速度/电流是 **signed-magnitude（bit15 = 符号）**，不是两位补码。
    HL2915 范本写 `if v >= 0x8000: v -= 0x10000` —— **照抄就错**。
  - 单圈 0–4095，不是多圈。

★★ 真机实测推翻的两条（2026-11-01，COM3 / ID 1 / USB 5 V 档，fw 3.46 / mode 4）：

  1. **`reg40`（扭矩开关）在 mode=4 下拦不住运动。** 官方表写"0 = 关闭扭力输出/
     自由状态"（fanhao375《HD-1910训练前数据清单》第 141 行亦记 reg40 = 使能 1 开 0 关），
     但实测：明确写 reg40=0、读回 0、mode=4，写 goal=1847 后舵机 **0.4 s 内走到 1848**。
     ⇒ **本脚本不靠关扭矩来"停"，收尾一律写 `goal = 当前位置`。**
     ⇒ 同理，"开扭矩"也不是运动的前提 —— 写 goal 就会动。所以**必须先设好
        reg46 速度 / reg48 扭矩限制，再写 goal**，顺序反了就是全速冲。

  2. **67-68 = 目标位置（Goal）镜像，不是位置副本。** 写 goal=2000 → 67-68 读到 2000
     而 56-57 仍是当时实际位置；写 goal=1847 → 67-68=1847。
     ⇒ 一次读 15 字节同时拿到**命令与实际，且两者时间对齐（同一帧）**，
        阶跃录制不必再单独发读 goal 的事务。

未决：
  - 电流 6.5 mA/LSB 引自 HL2915 表；HD-1910 静态 raw 3 ≈ 20 mA 与规格书"静态 20 mA"
    自洽，但**未经真机校准** ⇒ 同时输出 raw 与 mA 两列，mA 只作量级参考。
  - 64 / 65 / 66 在静止时全为 0，未做过扰动 ⇒ 语义按官方表（异步写标志/状态/移动）
    标注，但**未经本机实测**。
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hd1910_readonly import frame, query, ping, signed_mag  # noqa: E402

try:
    import serial
except ImportError:
    serial = None

# ---- 寄存器（kissqy duck-control/src/hd1910.rs；与飞特磁编码版同族）----
REG_ANGLE_MIN = 9
REG_ANGLE_MAX = 11
REG_P_GAIN = 21        # EPROM 位置环 P（掉电保存）
REG_D_GAIN = 22
REG_I_GAIN = 23
REG_MODE = 33
REG_TORQUE = 40        # ⚠️ 官方表「1开/0关」，但 mode=4 下 0 拦不住写 goal 引发的运动（实测）
REG_ACCEL = 41
REG_GOAL = 42          # 2B；mode=4 下写它立即执行，与 reg40 无关
REG_GOAL_FB = 67       # 2B 目标位置镜像（遥测块 67-68，实测确认）
REG_SPEED = 46         # 2B；0 = 固件解释为"零速趋向目标"= 不动（HL2915 实测，HD 同理）
REG_TORQUE_LIMIT = 48  # 2B，1000 = 100%
REG_P_RAM = 50         # RAM 增益，掉电回落 21  ← P3 部署写的是这个
REG_D_RAM = 51
REG_POS = 56           # 遥测块起
REG_STATUS = 65
REG_MOVING = 66
REG_CURRENT = 69       # 2B

TELEM_LEN = 15         # 56..70
CURRENT_MA_PER_LSB = 6.5
STEPS_PER_REV = 4096
DEAD_ZONE_GUARD = 3    # 26/27 号不灵敏区出厂 1 步，再留余量
KP_FW_P3 = 5           # P3 裁决：部署时 reg50 应为 5（32 只是出厂 ROM 默认）


# ---------------------------------------------------------------- 数据链路

class Bus:
    def __init__(self, port: str, baud: int = 1_000_000):
        self.ser = serial.Serial(port, baud, bytesize=8, parity="N",
                                 stopbits=1, timeout=0.05)

    def close(self) -> None:
        self.ser.close()

    def ping(self, sid: int) -> bool:
        return ping(self.ser, sid)

    def read(self, sid: int, addr: int, n: int):
        return query(self.ser, sid, addr, n)

    def read_u8(self, sid: int, addr: int):
        r = query(self.ser, sid, addr, 1)
        return r[0] if r else None

    def read_u16(self, sid: int, addr: int):
        r = query(self.ser, sid, addr, 2)
        return (r[0] | (r[1] << 8)) if r else None

    def write(self, sid: int, addr: int, data) -> bool:
        """WRITE inst=0x03, params=[addr]+data, 应答无参数。"""
        self.ser.reset_input_buffer()
        self.ser.write(frame(sid, 0x03, bytes([addr, *data])))
        self.ser.flush()
        deadline = time.time() + 0.05
        buf = b""
        while time.time() < deadline:
            n = self.ser.in_waiting
            if n:
                buf += self.ser.read(n)
            if len(buf) >= 6:
                break
            time.sleep(0.001)
        return any(buf[i:i + 3] == b"\xff\xff" + bytes([sid])
                   for i in range(max(1, len(buf) - 2)))

    def write_u8(self, sid: int, addr: int, v: int) -> bool:
        return self.write(sid, addr, [v & 0xFF])

    def write_u16(self, sid: int, addr: int, v: int) -> bool:
        return self.write(sid, addr, [v & 0xFF, (v >> 8) & 0xFF])


def telemetry(bus: Bus, sid: int):
    """读 56..70 一次拿全。返回 dict，含原始 hex 供人工核对布局。"""
    rx = bus.read(sid, REG_POS, TELEM_LEN)
    if rx is None or len(rx) != TELEM_LEN:
        return None
    u16 = lambda o: rx[o] | (rx[o + 1] << 8)  # noqa: E731
    return {
        "pos": signed_mag(rx[0], rx[1]),          # 56-57 signed-magnitude
        "speed": signed_mag(rx[2], rx[3]),        # 58-59
        "load": signed_mag(rx[4], rx[5]),         # 60-61
        "volt": rx[6] / 10.0,                     # 62  0.1 V/LSB
        "temp": rx[7],                            # 63  °C
        "unk64": rx[8],                           # 64  未确认
        "status": rx[9],                          # 65
        "moving": rx[10],                         # 66
        "goal": u16(11),                          # 67-68 目标位置镜像（实测确认）
        "cur_raw": signed_mag(rx[13], rx[14]),    # 69-70
        "cur_ma": signed_mag(rx[13], rx[14]) * CURRENT_MA_PER_LSB,
        "hex": rx.hex(),
    }


def unique_path(path: str) -> str:
    stem, ext = os.path.splitext(path)
    cand, i = path, 1
    while os.path.exists(cand):
        cand = f"{stem}-{i}{ext}"
        i += 1
    return cand


# ---------------------------------------------------------------- 指标（纯函数，可 dry-run）

def step_metrics(rows, phase, target, tol):
    """超调 / 稳态误差 / 整定时间 —— 辨识 kp/kd 看的就是这三个数。

    rows: (phase, t_ms, target, pos, speed, load, cur_ma)
    """
    pts = [r for r in rows if r[0] == phase]
    if len(pts) < 5:
        return None
    p0 = pts[0][3]
    travel = target - p0
    if abs(travel) < 10:
        return None
    tail = [p for _, _, _, p, _, _, _ in pts[-10:]]
    err = sum(tail) / len(tail) - target
    dirn = 1 if travel > 0 else -1
    extreme = (max if dirn > 0 else min)(p for _, _, _, p, _, _, _ in pts)
    over_steps = max(0.0, (extreme - target) * dirn)
    settle_ms = None
    for i in range(len(pts)):
        if all(abs(p - target) <= tol for _, _, _, p, _, _, _ in pts[i:]):
            settle_ms = pts[i][1]
            break
    return {
        "err": err,
        "over_pct": 100.0 * over_steps / abs(travel),
        "settle_ms": settle_ms,
        "vmax": max(abs(v) for _, _, _, _, v, _, _ in pts),
        "imax": max(c for _, _, _, _, _, _, c in pts),
        "load_max": max(l for _, _, _, _, _, l, _ in pts),
    }


def synth_step(pos0, target, seconds, hz=50.0, zeta=0.35, wn=18.0):
    """合成二阶阶跃响应（供 --dry-run 验证指标计算，不碰硬件）。

    zeta < 1 → 有超调；zeta >= 1 → 无超调。负对照用后者。
    """
    import math
    rows = []
    n = int(seconds * hz)
    wd = wn * math.sqrt(max(1e-9, 1 - zeta * zeta))
    for i in range(n):
        t_ms = int(1000 * i / hz)
        t = i / hz
        if zeta < 1:
            env = math.exp(-zeta * wn * t)
            y = target - (target - pos0) * env * (
                math.cos(wd * t) + (zeta * wn / wd) * math.sin(wd * t))
        else:
            y = target - (target - pos0) * (1 + wn * t) * math.exp(-wn * t)
        v = 0.0 if i == 0 else (y - rows[-1][3]) * hz
        rows.append(("up", t_ms, target, y, v, 0.0, 0.0))
    return rows


# ---------------------------------------------------------------- 子命令

def cmd_telem(bus: Bus, sid: int, args):
    """只读遥测流。USB 5 V 档可跑（静态 20 mA）。"""
    end = time.monotonic() + args.seconds
    n = 0
    print(f"遥测 {sid} @ {args.seconds}s，50 Hz。Ctrl-C 中止。")
    print(f"{'pos':>6} {'goal':>6} {'spd':>6} {'load':>6} {'V':>5} {'°C':>4} "
          f"{'cur_raw':>7} {'cur_mA':>8}  hex(56..70)")
    try:
        while time.monotonic() < end:
            t = telemetry(bus, sid)
            if t is None:
                print("  (丢包)")
            else:
                n += 1
                if n % 5 == 1 or args.verbose:
                    print(f"{t['pos']:>6} {t['goal']:>6} {t['speed']:>6} {t['load']:>6} "
                          f"{t['volt']:>5.1f} {t['temp']:>4} "
                          f"{t['cur_raw']:>7} {t['cur_ma']:>8.1f}  {t['hex']}")
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n中止")
    print(f"-- {n} 个有效样本 --")


def move_and_settle(bus: Bus, sid: int, target: int, timeout_s=3.0):
    bus.write_u16(sid, REG_GOAL, target)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if bus.read_u8(sid, REG_MOVING) == 0:
            break
        time.sleep(0.01)
    time.sleep(0.3)
    return bus.read_u16(sid, REG_POS)


def _arm(bus: Bus, sid: int, args) -> None:
    """写 goal 之前的必要动作 —— **顺序不能反**。

    mode=4 下写 goal 立即执行（reg40 拦不住，见 docstring ★★），所以限速和限流
    必须在第一次写 goal 之前落到位，否则就是全速全扭矩冲。
    reg46 速度：上电默认 0，固件解释为"零速趋向目标"= 不动（HL2915 实测，HD 同理）。
    """
    bus.write_u16(sid, REG_SPEED, args.speed)
    bus.write_u8(sid, REG_ACCEL, args.accel)
    bus.write_u16(sid, REG_TORQUE_LIMIT, args.torque_limit)
    time.sleep(0.1)


def _disarm(bus: Bus, sid: int) -> None:
    """让舵机就地停住 —— mode=4 下唯一可靠的办法（reg40=0 无效）。"""
    pos = bus.read_u16(sid, REG_POS)
    if pos is not None:
        bus.write_u16(sid, REG_GOAL, pos)


def cmd_step(bus: Bus, sid: int, args):
    """PD 阶跃录制：50 Hz 录"目标-实际"→ CSV + 指标。kt/R/齿隙之外的形状数据出在这里。"""
    start = bus.read_u16(sid, REG_POS)
    kp0 = bus.read_u8(sid, REG_P_GAIN)
    kd0 = bus.read_u8(sid, REG_D_GAIN)
    if start is None or kp0 is None:
        sys.exit("读不到位置/增益，先跑 telem 确认通信")
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件，用 `selftest` 子命令验证指标")
    print(f"起始 {start}  当前 P={kp0} D={kd0}（P3 部署值 P={KP_FW_P3}）")
    if kp0 != KP_FW_P3:
        print(f"⚠️ 真机 P={kp0}，P3 仿真用 kp_fw={KP_FW_P3} —— 两边不对齐时，"
              f"这份阶跃形状不能代表部署后的行为。要对齐就写 reg50={KP_FW_P3}。")

    up, back = start + args.steps, start
    path = unique_path(args.csv or f"hd1910_step_id{sid}_kp{kp0}_kd{kd0}.csv")
    f = open(path, "w", newline="", buffering=1)   # 行缓冲：Ctrl-C 不丢已采的点
    writer = csv.writer(f)
    writer.writerow(["phase", "t_ms", "target", "pos", "speed", "load",
                     "volt", "temp_c", "cur_raw", "cur_ma"])
    rows, miss = [], 0
    print(f"录制 → {path}：静置 {args.pre}s → {start}→{up}→{back}，"
          f"每段 {args.hold}s，50 Hz。Ctrl-C 中止，数据照常落盘。")
    try:
        _arm(bus, sid, args)
        for phase, target, secs in (("pre", start, args.pre),
                                    ("up", up, args.hold),
                                    ("back", back, args.hold)):
            if phase != "pre":
                bus.write_u16(sid, REG_GOAL, target)
            t0 = time.monotonic()
            while time.monotonic() - t0 < secs:
                t = telemetry(bus, sid)
                t_ms = int((time.monotonic() - t0) * 1000)
                if t is None:
                    miss += 1
                    writer.writerow([phase, t_ms, target, "", "", "", "", "", "", ""])
                    continue
                writer.writerow([phase, t_ms, target, t["pos"], t["speed"], t["load"],
                                 f"{t['volt']:.1f}", t["temp"], t["cur_raw"],
                                 f"{t['cur_ma']:.0f}"])
                rows.append((phase, t_ms, target, t["pos"], t["speed"],
                             t["load"], t["cur_ma"]))
                time.sleep(max(0.0, 0.02 - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        print("\n手动中止")
    finally:
        _disarm(bus, sid)
        f.close()
    print(f"有效样本 {len(rows)}，丢包 {miss}"
          + ("  ⚠️ 有丢包，曲线可能有洞，先查共地/线长" if miss else ""))
    for phase, target in (("up", up), ("back", back)):
        m = step_metrics(rows, phase, target, DEAD_ZONE_GUARD + 2)
        if m is None:
            print(f"{phase}: 样本不足或行程太小，跳过")
            continue
        settle = (f"{m['settle_ms']}ms" if m["settle_ms"] is not None
                  else f">{args.hold * 1000:.0f}ms 未整定")
        print(f"{phase}: 稳态误差 {m['err']:+.1f} 步 | 超调 {m['over_pct']:.1f}% | "
              f"整定 {settle} | 峰速 {m['vmax']:.0f} 步/s | 峰值电流 {m['imax']:.0f}mA")
    print(f"CSV → {path}")


def cmd_deadzone(bus: Bus, sid: int, args):
    """双向最小可动步：从 1 步起递增，看实际有没有动。"""
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件")
    start = bus.read_u16(sid, REG_POS)
    if start is None:
        sys.exit("读不到位置")
    print(f"起始 {start}，逐档 ±1..{args.max_step} 步，看实际跟不跟")
    out = {}
    try:
        _arm(bus, sid, args)
        for direction in (+1, -1):
            found = None
            for d in range(1, args.max_step + 1):
                actual = move_and_settle(bus, sid, start + direction * d)
                moved = actual - start          # 带符号：负方向的位移必须是负的
                print(f"  命令 {start + direction * d:>5}（{direction * d:+d}）"
                      f" → 实际 {actual}（位移 {moved:+d}）")
                if abs(moved) >= 1:
                    found = d
                    break
            out["plus" if direction > 0 else "minus"] = found
            move_and_settle(bus, sid, start)
    finally:
        _disarm(bus, sid)
    print(f"最小可动步：正向 {out.get('plus')} / 反向 {out.get('minus')}"
          f"（None = 到 {args.max_step} 步都没动）")
    print(f"⚠️ 读数依赖当前参数：P={bus.read_u8(sid, REG_P_GAIN)}、"
          f"扭矩限制 reg48={args.torque_limit}、速度 reg46={args.speed}、供电"
          f"—— 记数时必须把这些一起记，否则不可复现。")
    print("⚠️ 这是「最小可动步」，含齿轮间隙；要分离纯电气死区需夹住输出轴重测。")
    print("⚠️ 扭矩限制压到 20% 时『不动』可能是力矩不足而非死区 ⇒ 正式数据应在 "
          "7.4 V + 部署用 P（P3=5）+ 额定扭矩限制下复测。")
    print("⚠️ 边界会抖：本机连测两次得 (正2/反2) 与 (正2/反1)，因为『动不动』取决于"
          "齿轮当前的贴合侧。⇒ **单次读数不可作结论，需重复 ≥5 次取众数**。")


def cmd_backlash(bus: Bus, sid: int, args):
    """双向趋近同一目标：两向稳定位置之差 = 回差（齿隙的可测量代理）。"""
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件")
    start = bus.read_u16(sid, REG_POS)
    if start is None:
        sys.exit("读不到位置")
    target = start
    print(f"目标 {target}，分别从 {target - args.approach} / "
          f"{target + args.approach} 趋近，各稳定后读数")
    res = {}
    try:
        _arm(bus, sid, args)
        for name, via in (("from_below", target - args.approach),
                          ("from_above", target + args.approach)):
            move_and_settle(bus, sid, via)
            res[name] = move_and_settle(bus, sid, target)
            print(f"  {name}（经 {via}）→ {res[name]}")
    finally:
        _disarm(bus, sid)
    gap = res["from_below"] - res["from_above"]
    print(f"回差 = {gap} 步（{gap / STEPS_PER_REV * 360:.2f}°）")
    print("⚠️ 含伺服稳态误差；要纯机械齿隙需在扭矩关闭时用手扳（摇晃法）对照。")


def cmd_selftest(_bus, _sid, args):
    """不碰硬件：合成曲线验证 step_metrics，含负对照。"""
    print("=== 正例：欠阻尼（zeta=0.35）应有超调 ===")
    rows = synth_step(2000, 2200, 3.0, zeta=0.35)
    m = step_metrics(rows, "up", 2200, 5)
    print(f"  超调 {m['over_pct']:.2f}%  稳态误差 {m['err']:+.2f}  整定 {m['settle_ms']}ms")
    ok1 = m["over_pct"] > 1.0

    print("=== 负对照：临界阻尼（zeta=1.0）超调应 ≈0 ===")
    rows2 = synth_step(2000, 2200, 3.0, zeta=1.0)
    m2 = step_metrics(rows2, "up", 2200, 5)
    print(f"  超调 {m2['over_pct']:.2f}%  稳态误差 {m2['err']:+.2f}  整定 {m2['settle_ms']}ms")
    ok2 = m2["over_pct"] < 1.0

    print("=== 负对照：反向阶跃（travel<0）超调方向不能反 ===")
    rows3 = synth_step(2200, 2000, 3.0, zeta=0.35)
    m3 = step_metrics(rows3, "up", 2000, 5)
    print(f"  超调 {m3['over_pct']:.2f}%  稳态误差 {m3['err']:+.2f}")
    ok3 = m3["over_pct"] > 1.0

    print("=== 负对照：样本不足应返回 None 而不是崩 ===")
    ok4 = step_metrics([("up", 0, 2200, 2000, 0, 0, 0)] * 3, "up", 2200, 5) is None
    print(f"  3 样本 → {step_metrics([('up', 0, 2200, 2000, 0, 0, 0)] * 3, 'up', 2200, 5)}")

    allok = ok1 and ok2 and ok3 and ok4
    print(f"\nselftest: {'ALL PASSED' if allok else 'FAILED'}")
    return 0 if allok else 1


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="HD-1910 辨识台架")
    ap.add_argument("cmd", choices=["telem", "step", "deadzone", "backlash", "selftest"])
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="不碰硬件（仅部分子命令支持）")
    ap.add_argument("--seconds", type=float, default=10, help="telem 时长")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--steps", type=int, default=200, help="step 阶跃幅度（步）")
    ap.add_argument("--hold", type=float, default=2.0, help="step 每段保持秒数")
    ap.add_argument("--pre", type=float, default=1.0, help="step 静置秒数")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--max-step", type=int, default=20, help="deadzone 最大探测步")
    ap.add_argument("--approach", type=int, default=100, help="backlash 趋近距离")
    ap.add_argument("--speed", type=int, default=300, help="reg46 目标速度（步/s）")
    ap.add_argument("--accel", type=int, default=10, help="reg41 加速度（×100 步/s²）")
    ap.add_argument("--torque-limit", type=int, default=500, help="reg48（1000=100%）")
    args = ap.parse_args()

    if args.cmd == "selftest":
        return cmd_selftest(None, args.id, args)

    if serial is None:
        sys.exit("缺 pyserial：pip install pyserial")
    if args.dry_run:
        print("dry-run：不开串口")
        return 0

    bus = Bus(args.port, args.baud)
    try:
        if not bus.ping(args.id):
            sys.exit(f"ID {args.id} 无应答：查线序（1=信号 2=V 3=G）、供电、波特率")
        print(f"✔ PING {args.id} @ {args.port}")
        if args.cmd in ("step", "deadzone", "backlash"):
            mode = bus.read_u8(args.id, REG_MODE)
            print(f"  reg33 mode = {mode}（本脚本所有实测结论基于 mode=4）")
            if mode != 4:
                print(f"  ⚠️ mode={mode} ≠ 4：『reg40 拦不住运动』『写 goal 立即执行』"
                      f"两条实测结论在别的模式下可能不成立，先小幅度试一次再放量。")
            p = bus.read_u8(args.id, REG_P_GAIN)
            print(f"  reg21 P = {p}"
                  + ("" if p == KP_FW_P3 else
                     f"  ⚠️ P3 部署值是 {KP_FW_P3}，两边不对齐时这份辨识不代表部署后行为"))
        {"telem": cmd_telem, "step": cmd_step,
         "deadzone": cmd_deadzone, "backlash": cmd_backlash}[args.cmd](bus, args.id, args)
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
