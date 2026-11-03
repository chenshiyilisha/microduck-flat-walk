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
    raw=3 只有 3 个计数，系数取 4/6.5/8 分别得 12/19.5/24 mA，**这个点区分不了系数**
    （kissqy duck-control 亦明确不猜：feetech.rs "current/gain units are deliberately
    not guessed from another feetech model"，current_ma_per_count 默认 0.0 且带
    units_verified 标志）。⇒ **只能在堵转点校**：7.4 V ÷ 3.75 Ω ≈ 1.97 A，
    按 6.5 mA/LSB 应读 ≈308 counts，再与电源屏显交叉（stage0_software_prep.md §5.7）。
  - 64 / 65 / 66 在静止时全为 0，未做过扰动 ⇒ 语义按官方表（异步写标志/状态/移动）
    标注，但**未经本机实测**。
"""
import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hd1910_readonly import frame, query, ping, signed_mag  # noqa: E402


def load_mag(lo: int, hi: int) -> int:
    """Present Load (reg 60) 的专属解码：**bit10 = 方向，bit0-9 = 幅度**。

    不能复用 ``signed_mag()``：那个函数假设符号位在 bit15（speed/current 是
    这个布局，pos 是纯无符号 12 位），而飞特 STS 的 load 把方向放在 bit10。
    2026-11-03 实测证据（ID10 @4.6 V，200 步阶跃）：up 段原始值稳定在
    1044-1124，back 段在 0-116；减掉 0x400 后两段落到同一量级 20-124，
    且方向位与电流符号逐一吻合。用 signed_mag 读会把 11.6% 的负载报成
    1145（"114.5%"），超满量程 1000 —— 上下界矛盾即读数错误的典型形态。
    """
    v = lo | (hi << 8)
    mag = v & 0x3FF
    return -mag if (v & 0x400) else mag

# 仓库根（tools/hd1910/servo_probe 上溯三层）。默认把录制数据落到 out/steps/，
# 免得跑一次就在仓库根留一个 CSV。
ROOT = Path(__file__).resolve().parents[3]
REC_DIR = ROOT / "out" / "steps"
SINE_DIR = ROOT / "out" / "sine"

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
REG_ID = 5             # 总线 ID（改后要断电重启才在旧 ID 上消失）
REG_LOCK = 55          # 0 = EPROM 可写；1 = 锁定（HL2915/HD 同表，见 ref_hl2915_bench.py:57）

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
        "load": load_mag(rx[4], rx[5]),           # 60-61 bit10 方向 + bit0-9 幅度
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
    # Peak speed from POSITION DIFFERENCES, in 步/s — NOT from the telemetry `speed`
    # field. That field has its own unit: measured ratio (position diff) / (field)
    # = 51.5..63x, median ~54, i.e. 1 unit ~= 53 步/s ~= 4.7 deg/s. Printing it as
    # 步/s overstated peak speed by ~54x for two days before anyone checked.
    #
    # p95 rather than max: the largest single sample-to-sample difference is noise
    # (measured +-20% spread across repeats, and it lands near the physical cap),
    # so max alone is not a usable number. Both are returned; read p95.
    #
    # ⚠️ 窗口：p95 必须在**运动段**上算，不能在整个相位窗口上算。整段里含静止保持，
    # hold 从 2 s 改到 3 s 会把 p95 从 661 拉到 525 步/s（同一颗舵机、同一参数）。
    # 这是"指标依赖窗口长度"，和 error_vel_xy 那个坑同类。截到 settle 点，
    # settle 由 tol 决定、与 hold 无关 ⇒ 换 hold 不再改变峰速。
    def _speeds(seq):
        out = []
        for a, b in zip(seq, seq[1:]):
            t1, p1, t2, p2 = a[1], a[3], b[1], b[3]
            if t2 > t1:
                out.append(abs(p2 - p1) * 1000.0 / (t2 - t1))
        return out

    win_end = settle_ms is not None
    if win_end:
        # settle_ms 是时间戳，换成下标
        idx_end = next((i for i, r in enumerate(pts) if r[1] >= settle_ms), len(pts) - 1)
    else:
        idx_end = len(pts) - 1
    moving = pts[: idx_end + 1] if idx_end >= 4 else pts

    vs_win = _speeds(moving)
    vs_full = _speeds(pts)

    def _p95(vals):
        if not vals:
            return 0.0
        s = sorted(vals)
        return s[min(len(s) - 1, max(0, math.ceil(0.95 * len(s)) - 1))]

    v_p95, v_max = _p95(vs_win), (max(vs_win) if vs_win else 0.0)
    return {
        "err": err,
        "over_pct": 100.0 * over_steps / abs(travel),
        "settle_ms": settle_ms,
        "v_p95_steps": v_p95,
        "v_p95_deg_s": v_p95 * 360.0 / STEPS_PER_REV,
        "v_max_steps": v_max,
        "v_win_s": (moving[-1][1] - moving[0][1]) / 1000.0 if len(moving) > 1 else 0.0,
        "v_win_n": len(moving),
        # 旧口径（含保持段），只用于和修好之前的 JSON 对照，别再拿它下结论
        "v_p95_full_steps": _p95(vs_full),
        "speed_field_peak_raw": max(abs(v) for _, _, _, _, v, _, _ in pts),
        "imax": max(c for _, _, _, _, _, _, c in pts),
        # abs：load 是双向的，up/back 两段符号相反，直接 max 会漏掉整段
        "load_max": max((abs(l) for _, _, _, _, _, l, _ in pts), default=0),
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


def _write_gains(bus: Bus, sid: int, kp, kd):
    """写 RAM 增益（reg50/51）并**回读确认生效**。

    为什么要回读：写 reg50 不改 EEPROM reg21，而读 reg21 拿到的仍是旧值。
    只看写入返回码 = 只看"我发了"，看不到"它认了"。
    """
    if kp is not None:
        bus.write_u8(sid, REG_P_RAM, kp)
    if kd is not None:
        bus.write_u8(sid, REG_D_RAM, kd)
    time.sleep(0.05)
    got_p = bus.read_u8(sid, REG_P_RAM)
    got_d = bus.read_u8(sid, REG_D_RAM)
    return got_p, got_d


def write_step_json(path, armed: dict, phases: dict, extra: dict) -> None:
    """Persist one step run's metrics next to its CSV.

    The reg46 A/B needs this: comparing runs by eye off the printed line is how
    the first A/B ended up attributing a reg41 change to reg46. Both the
    requested and the READ-BACK register values go in, because a requested 4095
    can come back truncated and "I sent it" is not "it took".
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"armed": armed, "protocol": extra, "phases": phases},
        indent=1, ensure_ascii=False), encoding="utf-8")


def cmd_step(bus: Bus, sid: int, args):
    """PD 阶跃录制：50 Hz 录"目标-实际"→ CSV + 指标。kt/R/齿隙之外的形状数据出在这里。

    ★ 有效增益在 **RAM reg50/51**，不是 EEPROM reg21/22。掉电回落 EEPROM。
      本命令的 `--kp/--kd` 改的是 RAM，测完恢复原 RAM 值（不动 EEPROM）。
    """
    start = bus.read_u16(sid, REG_POS)
    # 有效值读 RAM；EEPROM 只作对照（两者不等时容易误读"当前 P 是多少"）
    kp_ram = bus.read_u8(sid, REG_P_RAM)
    kd_ram = bus.read_u8(sid, REG_D_RAM)
    kp_ee = bus.read_u8(sid, REG_P_GAIN)
    kd_ee = bus.read_u8(sid, REG_D_GAIN)
    if start is None or kp_ram is None:
        sys.exit("读不到位置/增益，先跑 telem 确认通信")
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件，用 `selftest` 子命令验证指标")

    target_p = args.kp if args.kp is not None else kp_ram
    target_d = args.kd if args.kd is not None else kd_ram
    if args.kp is not None and args.kd is None:
        # BAM 官方 STS3215 控制律是纯 P（无 D）。要把真机对齐仿真，
        # 只写 P 而留着 D=40 会多出一份 sim 里不存在的阻尼。
        target_d = 0
        print(f"⚠️ 给了 --kp 未给 --kd ⇒ 按 BAM 纯 P 律把 D 归零（否则多出仿真没有的阻尼项）")

    print(f"起始 {start}  RAM P={kp_ram} D={kd_ram}｜EEPROM P={kp_ee} D={kd_ee}")
    if kp_ram != kp_ee:
        print(f"  ↳ RAM≠EEPROM：当前生效的是 RAM（{kp_ram}/{kd_ram}），"
              f"掉电会回落到 EEPROM（{kp_ee}/{kd_ee}）")
    if target_p != KP_FW_P3:
        print(f"⚠️ 本次阶跃 P={target_p}，P3 仿真 kp_fw={KP_FW_P3} —— "
              f"两边不对齐时这份形状不代表部署后行为。")
    if target_d != 0:
        print(f"⚠️ 本次 D={target_d}。BAM 官方 STS3215 律无 D 项，"
              f"部署契约是 D=0；D≠0 的曲线不能直接跟 sim 比。")

    up, back = start + args.steps, start
    REC_DIR.mkdir(parents=True, exist_ok=True)
    path = unique_path(args.csv or str(
        REC_DIR / f"step_id{sid}_kp{target_p}_kd{target_d}.csv"))
    f = open(path, "w", newline="", buffering=1)   # 行缓冲：Ctrl-C 不丢已采的点
    writer = csv.writer(f)
    writer.writerow(["phase", "t_ms", "target", "pos", "speed", "load",
                     "volt", "temp_c", "cur_raw", "cur_ma"])
    rows, miss = [], 0
    print(f"录制 → {path}：静置 {args.pre}s → {start}→{up}→{back}，"
          f"每段 {args.hold}s，50 Hz。Ctrl-C 中止，数据照常落盘。")
    # 限速/限流三个寄存器必须先存原值 —— step 原先只存了增益，于是反测完
    # reg48=500（50% 力矩）在舵机上留了一整天，下一个人测到的是未知基线。
    sp_orig = bus.read_u16(sid, REG_SPEED)
    ac_orig = bus.read_u8(sid, REG_ACCEL)
    tl_orig = bus.read_u16(sid, REG_TORQUE_LIMIT)
    print(f"原限速 reg46={sp_orig} reg41={ac_orig}｜限流 reg48={tl_orig}（测完恢复）")
    try:
        # ① 先把 goal 钉在当前位置：切增益的瞬间若 goal 还停在上一轮残留值，
        #    新增益会立刻把它拽过去 —— 那是"没测就动了"。
        bus.write_u16(sid, REG_GOAL, start)
        time.sleep(0.2)
        # ② 切增益并回读（只认回读，不认写入返回码）
        got_p, got_d = _write_gains(bus, sid, target_p, target_d)
        if (got_p, got_d) != (target_p, target_d):
            print(f"✗ 增益未生效：写入 ({target_p},{target_d}) → 回读 ({got_p},{got_d})")
            sys.exit("增益回读不符，拒测（否则这份数据标错增益）")
        print(f"✔ 增益生效 RAM P={got_p} D={got_d}（回读确认）")
        _arm(bus, sid, args)
        # 回读限速/限流：写进去了不等于它认了（reg46 有固件上限，4095 会被截断）。
        # A/B 若只记请求值就会把"我发了"当"它生效了"，这正是 reg46 那次 A/B
        # 需要重做的原因之一。
        armed = {
            "reg46_speed_req": args.speed,
            "reg46_speed_rb": bus.read_u16(sid, REG_SPEED),
            "reg41_accel_req": args.accel,
            "reg41_accel_rb": bus.read_u8(sid, REG_ACCEL),
            "reg48_torque_req": args.torque_limit,
            "reg48_torque_rb": bus.read_u16(sid, REG_TORQUE_LIMIT),
            "kp_ram": got_p,
            "kd_ram": got_d,
        }
        for phase, target, secs in (("pre", start, args.pre),
                                    ("up", up, args.hold),
                                    ("back", back, args.hold)):
            if phase != "pre":
                bus.write_u16(sid, REG_GOAL, target)
            # ⚠️ 必须 perf_counter：Windows 上 time.monotonic() 分辨率 15.6 ms，
            #    50 Hz（20 ms）采样会出现"同一毫秒几十个样本"，时间轴直接作废。
            t0 = time.perf_counter()
            dt_s = 1.0 / args.rate
            next_t = t0
            while True:
                now = time.perf_counter()
                if now - t0 >= secs:
                    break
                t = telemetry(bus, sid)
                t_ms = int((time.perf_counter() - t0) * 1000)
                if t is None:
                    miss += 1
                    writer.writerow([phase, t_ms, target, "", "", "", "", "", "", ""])
                else:
                    writer.writerow([phase, t_ms, target, t["pos"], t["speed"], t["load"],
                                     f"{t['volt']:.1f}", t["temp"], t["cur_raw"],
                                     f"{t['cur_ma']:.0f}"])
                    rows.append((phase, t_ms, target, t["pos"], t["speed"],
                                 t["load"], t["cur_ma"]))
                # 绝对节拍：按"下一个应采时刻"睡，不按"已用时间"减 ——
                # 后者在 elapsed>dt 之后恒为 0，会变成无节拍空转。
                next_t += dt_s
                slack = next_t - time.perf_counter()
                if slack > 0:
                    time.sleep(slack)
                else:
                    next_t = time.perf_counter()   # 落后了就从现在重新起拍
    except KeyboardInterrupt:
        print("\n手动中止")
    finally:
        _disarm(bus, sid)
        # 限速/限流同样要恢复并回读。sine 早就有这段，step 一直没有 ——
        # 于是 reg48=500 被留了整天（A/B 证明无影响，但那是运气，不是设计）。
        try:
            bus.write_u16(sid, REG_SPEED, sp_orig)
            bus.write_u8(sid, REG_ACCEL, ac_orig)
            bus.write_u16(sid, REG_TORQUE_LIMIT, tl_orig)
            time.sleep(0.05)
            rb = (bus.read_u16(sid, REG_SPEED), bus.read_u8(sid, REG_ACCEL),
                  bus.read_u16(sid, REG_TORQUE_LIMIT))
            ok = rb == (sp_orig, ac_orig, tl_orig)
            print(f"{'✔' if ok else '✗'} 限速/限流恢复 reg46={rb[0]} reg41={rb[1]} "
                  f"reg48={rb[2]}（原 {sp_orig}/{ac_orig}/{tl_orig}）")
        except Exception as e:
            print(f"✗ 限速/限流恢复失败：{e}  ⚠️ 舵机仍是测试值，手动写回 "
                  f"reg46={sp_orig} reg41={ac_orig} reg48={tl_orig}")
        # 恢复原 RAM 增益（不动 EEPROM）。恢复也要回读 —— 否则"以为恢复了"。
        if args.kp is not None or args.kd is not None:
            try:
                rp, rd = _write_gains(bus, sid, kp_ram, kd_ram)
                ok = (rp, rd) == (kp_ram, kd_ram)
                print(f"{'✔' if ok else '✗'} 增益恢复 RAM P={rp} D={rd}"
                      f"（原 {kp_ram}/{kd_ram}）")
            except Exception as e:                       # 串口已断也要把话说完
                print(f"✗ 增益恢复失败：{e}  ⚠️ 现在 RAM P/D 可能仍是 "
                      f"{target_p}/{target_d}，断电或重跑一次 step 修回")
        f.close()
    print(f"有效样本 {len(rows)}，丢包 {miss}"
          + ("  ⚠️ 有丢包，曲线可能有洞，先查共地/线长" if miss else ""))
    # 时间轴自检：采样率是否达到标称，否则整条曲线的形状都不可信
    dts = []
    for ph in ("pre", "up", "back"):
        ts = [r[1] for r in rows if r[0] == ph]
        dts += [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if dts:
        dts_sorted = sorted(dts)
        p50 = dts_sorted[len(dts_sorted) // 2]
        print(f"采样间隔 p50={p50}ms（标称 {1000/args.rate:.0f}ms）、"
              f"max={dts_sorted[-1]}ms、重复时间戳 {dts.count(0)}")
        if p50 > 1.5 * 1000 / args.rate:
            print("  ⚠️ 达不到标称采样率：阶跃上升沿可能被漏掉，先降 --rate 或查串口卡顿")
    # 速度字段交叉校验：位置差反算 vs 遥测 speed。两个来源不一致 ⇒ 单位不是 步/s。
    for phase, target in (("up", up), ("back", back)):
        seg = [(r[1], r[3]) for r in rows if r[0] == phase]
        v_pos = 0.0
        for (t1, p1), (t2, p2) in zip(seg, seg[1:]):
            if t2 > t1:
                v_pos = max(v_pos, abs(p2 - p1) * 1000.0 / (t2 - t1))
        v_rep = max((abs(r[4]) for r in rows if r[0] == phase), default=0)
        if v_pos > 0 and v_rep > 0:
            print(f"{phase}: 位置差分峰速 {v_pos:.0f} 步/s ↔ 遥测 speed={v_rep}"
                  f"（差 {v_pos / v_rep:.1f}×）" +
                  ("  ⇒ speed 字段不是 步/s，勿直接当速度用"
                   if v_pos / v_rep > 1.5 or v_pos / v_rep < 0.67 else "  ✓ 两个来源一致"))
    phases = {}
    for phase, target in (("up", up), ("back", back)):
        m = step_metrics(rows, phase, target, DEAD_ZONE_GUARD + 2)
        if m is None:
            print(f"{phase}: 样本不足或行程太小，跳过")
            continue
        phases[phase] = m
        settle = (f"{m['settle_ms']}ms" if m["settle_ms"] is not None
                  else f">{args.hold * 1000:.0f}ms 未整定")
        print(f"{phase}: 稳态误差 {m['err']:+.1f} 步 | 超调 {m['over_pct']:.1f}% | "
              f"整定 {settle} | 峰速 p95 {m['v_p95_steps']:.0f} 步/s "
              f"({m['v_p95_deg_s']:.0f} °/s，单点 max {m['v_max_steps']:.0f} 步/s，噪声大) | "
              f"峰值电流 {m['imax']:.0f}mA")
    print(f"CSV → {path}")
    if args.json:
        write_step_json(args.json, armed, phases,
                        {"steps": args.steps, "hold_s": args.hold, "rate": args.rate,
                         "csv": str(path), "start_pos": start})
        print(f"JSON → {args.json}")


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


def cmd_set_id(bus: Bus, sid: int, args):
    """改总线 ID：unlock reg55=0 → write reg5=new_id → 验证新 ID 应答。

    ⚠️ 改完必须**断电重启**才能在旧 ID 上消失（reg5 写入的是 EEPROM）。
    一次只接一只舵机！
    """
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件")
    new_id = args.new_id
    if new_id is None or new_id < 0 or new_id > 253:
        sys.exit("需要 --new-id（0-253）。一次只接一只舵机！")
    # 1. unlock EPROM
    bus.write_u8(sid, REG_LOCK, 0)
    time.sleep(0.05)
    # 2. write new ID
    if not bus.write_u8(sid, REG_ID, new_id):
        sys.exit(f"写 reg5={new_id} 失败（无应答）。检查线序/供电/波特率。")
    time.sleep(0.05)
    # 3. verify: PING new ID
    ok = bus.ping(new_id)
    print(f"{'✔' if ok else '✗'} 新 ID {new_id} "
          f"{'有应答' if ok else '无应答——回旧 ID 重试'}")
    print("⚠️ 改完必须断电重启（拔 USB），旧 ID 才会消失。")
    return 0 if ok else 1


# ---------------------------------------------------------------- 正弦跟踪（带宽）

def _sine_fit(rows, freq, skip_cycles=1.0):
    """基波最小二乘拟合的公共内核 —— sine_metrics 与 tremor_metrics 共用。

    两个指标必须吃**同一份**拟合结果：震颤 = 残差的高频能量，残差又是
    "输出 − 基波"，若各算一遍，gain 与震颤就不是同一组数据推出来的，
    互相校验的意义就没了（本项目已两次栽在"两个实现互抵"上）。
    """
    import math

    import numpy as np

    pts = [r for r in rows if r[0] == freq and r[3] is not None and r[4] is not None]
    if len(pts) < 12:
        return None
    skip_s = skip_cycles / float(freq)
    tg = np.array([r[1] / 1000.0 for r in pts])
    tp = np.array([r[2] / 1000.0 for r in pts])
    g = np.array([r[3] for r in pts], dtype=float)
    p = np.array([r[4] for r in pts], dtype=float)
    keep = tg >= (tg[0] + skip_s)
    if int(keep.sum()) < 12:
        keep = np.ones_like(tg, dtype=bool)
    tg, tp, g, p = tg[keep], tp[keep], g[keep], p[keep]

    w = 2.0 * math.pi * freq

    def fit(t, y):
        X = np.column_stack([np.cos(w * t), np.sin(w * t), np.ones_like(t)])
        a, b, dc = np.linalg.lstsq(X, y, rcond=None)[0]
        return math.hypot(a, b), math.atan2(b, a), dc, (a, b, dc), X

    amp_g, ph_g, dc_g, cg, Xg = fit(tg, g)
    amp_p, ph_p, dc_p, cp, Xp = fit(tp, p)
    if amp_g < 1.0:                      # 目标没动起来，比值没有意义
        return None
    lag = ph_p - ph_g                    # >0 = pos 落后于 goal
    lag = (lag + math.pi) % (2.0 * math.pi) - math.pi
    resid = p - (Xp @ np.array(cp))
    return {
        "freq_hz": freq, "tg": tg, "tp": tp, "g": g, "p": p,
        "amp_g": amp_g, "amp_p": amp_p, "dc_g": dc_g, "dc_p": dc_p,
        "lag": lag, "resid": resid, "n_pts": int(len(p)),
    }


def sine_metrics(rows, freq, skip_cycles=1.0):
    """单频最小二乘拟合 → 幅值比 / 相位滞后 / 跟踪误差。

    rows: (freq, t_goal_ms, t_pos_ms, goal, pos, speed, load, volt, temp, cur_ma)

    为什么用拟合而不是"逐点比峰值"：
      峰值对比在**有噪声或有直流偏置时会失真** —— 舵机稳态误差（P5/D0 实测 −2 步）
      会让上下峰不对称，取峰峰值就混进了偏置。拟合把基波幅值、相位、直流分量
      三个量分开解，各自独立可读。

    为什么 goal 与 pos 各用自己的时间戳：写 goal 与读位置之间有 ~1.6 ms 事务延迟，
    用同一时刻会把这段固定延迟算成相位滞后。两条时间轴各自拟合，延迟只影响
    pos 轴的绝对时刻（拟合对绝对相位不敏感，只看两轴之差），所以读到的滞后
    里仍含这段测量延迟 —— 量级 1.6 ms × 360°×f，1.89 Hz 下 ≈1.1°，可接受。
    """
    import math

    import numpy as np

    d = _sine_fit(rows, freq, skip_cycles)
    if d is None:
        return None
    amp_g, amp_p, lag, resid, p, g = d["amp_g"], d["amp_p"], d["lag"], d["resid"], d["p"], d["g"]
    pts = [r for r in rows if r[0] == freq]
    return {
        "freq_hz": freq,
        "amp_goal_deg": amp_g * 360.0 / STEPS_PER_REV,
        "amp_pos_deg": amp_p * 360.0 / STEPS_PER_REV,
        "gain": amp_p / amp_g,
        "loss_pct": 100.0 * (1.0 - amp_p / amp_g),
        "lag_deg": math.degrees(lag),
        "lag_ms": math.degrees(lag) / 360.0 * 1000.0 / freq,
        "dc_err_steps": d["dc_p"] - d["dc_g"],
        "rms_track_err_deg": float(np.sqrt(np.mean((p - g) ** 2))) * 360.0 / STEPS_PER_REV,
        "rms_resid_deg": float(np.sqrt(np.mean(resid ** 2))) * 360.0 / STEPS_PER_REV,
        "n_pts": d["n_pts"],
        "cur_ma_peak": float(np.max(np.abs([r[9] for r in pts if r[9] is not None]))),
    }


def tremor_metrics(rows, freq, skip_cycles=1.0, hf_cut=3.0):
    """震颤判据 —— 光看 gain 会把人骗了。

    P 调大必然抬 gain，但代价通常是高频抖动（社区实机记录：P 大颤）。
    只报 gain 的扫描会一路把 P 推到最大，然后在真机上抖成一团。

    所以把残差（输出 − 基波拟合）按频率拆开：
      * ``hf_ratio``  — 残差中 > ``hf_cut × f0`` 的能量占总残差能量的比例。
        谐波（2f0/3f0）不算震颤，抖动才算，所以从 3 倍基频起算。
      * ``jerk_rms_deg`` — 位置二阶差分的 RMS。对高频极敏感，是"抖不抖"的
        最直接读数，单位仍然是度，可与行程幅度直接比。

    两者都不设绝对阈值（没有厂商规格可依），**只做同条件跨 P 的相对比较**：
    基线取最小 P 那一档，倍数由打印层算。
    """
    import numpy as np

    d = _sine_fit(rows, freq, skip_cycles)
    if d is None:
        return None
    resid = d["resid"]
    n = len(resid)
    if n < 24:
        return None

    amp_p = d["amp_p"]
    spec = np.abs(np.fft.rfft(resid)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0 / (n / (d["tp"][-1] - d["tp"][0])))
    total = float(spec[1:].sum())        # 去掉直流
    hf = float(spec[freqs >= hf_cut * freq].sum())
    hf_ratio = (hf / total) if total > 1e-12 else 0.0

    jerk = np.diff(resid, n=2)
    scale = 360.0 / STEPS_PER_REV
    return {
        "freq_hz": freq,
        "hf_ratio": hf_ratio,
        "rms_resid_deg": float(np.sqrt(np.mean(resid ** 2))) * scale,
        "jerk_rms_deg": float(np.sqrt(np.mean(jerk ** 2))) * scale if len(jerk) else 0.0,
        "resid_over_amp": float(np.sqrt(np.mean(resid ** 2)) / amp_p) if amp_p else 0.0,
        "n_pts": n,
    }



def synth_sine(center, amp_steps, freq, seconds, hz=50.0, gain=0.8,
               lag_deg=30.0, noise=0.0, dc_err=0.0):
    """合成正弦跟踪曲线（供 selftest 验证 sine_metrics，不碰硬件）。"""
    import math

    import numpy as np

    rng = np.random.default_rng(0)
    rows, n = [], int(seconds * hz)
    lag = math.radians(lag_deg)
    for i in range(n):
        t = i / hz
        g = center + amp_steps * math.sin(2 * math.pi * freq * t)
        p = center + gain * amp_steps * math.sin(2 * math.pi * freq * t - lag) + dc_err
        if noise:
            p += rng.normal(0, noise)
        rows.append((freq, t * 1000.0, (t + 0.0016) * 1000.0, g, p, 0, 0, 7.4, 30, 0.0))
    return rows


def cmd_sine(bus: Bus, sid: int, args):
    """正弦跟踪录制：给 goal 发正弦，量"输出/输入"的幅值比与相位滞后。

    ★ 与阶跃的三点不同，都有后果：

    1. **必须解除 reg46/reg41 限速**，否则测的是限速不是 P。
       step 命令默认 `--speed 300`（步/s）= 26 °/s；而 1.89 Hz × ±16.9° 的正弦
       峰值速度是 2πfA = **209 °/s**，是默认限速的 8 倍。不解除的话，
       曲线会被梯形规划器削成三角波，P 再大也"跟不上" —— 那是假阴性。
    2. **幅度要取步态幅值**。knee 半幅 16.9°（=192 步）是策略实际要求的行程；
       用 ±5° 的小信号测出来的是另一台机器（已实测：小幅度反而更慢）。
    3. **电压要记**。全部在台架电压下测，7.4 V 会更快 ⇒ 这里的滞后是**上界**。
    """
    import math

    start = bus.read_u16(sid, REG_POS)
    kp_ram = bus.read_u8(sid, REG_P_RAM)
    kd_ram = bus.read_u8(sid, REG_D_RAM)
    kp_ee = bus.read_u8(sid, REG_P_GAIN)
    kd_ee = bus.read_u8(sid, REG_D_GAIN)
    amin = bus.read_u16(sid, REG_ANGLE_MIN)
    amax = bus.read_u16(sid, REG_ANGLE_MAX)
    if start is None or kp_ram is None:
        sys.exit("读不到位置/增益，先跑 telem 确认通信")
    if args.dry_run:
        sys.exit("--dry-run 不碰硬件，用 `selftest` 子命令验证指标")

    target_p = args.kp if args.kp is not None else kp_ram
    target_d = args.kd if args.kd is not None else kd_ram
    if args.kp is not None and args.kd is None:
        target_d = 0
        print("⚠️ 给了 --kp 未给 --kd ⇒ 按 BAM 纯 P 律把 D 归零（否则多出仿真没有的阻尼项）")

    amp_steps = int(round(args.sine_amp_deg / 360.0 * STEPS_PER_REV))
    # 必须记下原限速并在收尾恢复：sine 把 reg46 拉到最大，留下的舵机在别人
    # 用 telem / 手写 goal 时就是"无限速"状态 —— 那是下一个人的事故。
    sp_orig = bus.read_u16(sid, REG_SPEED)
    ac_orig = bus.read_u8(sid, REG_ACCEL)
    tl_orig = bus.read_u16(sid, REG_TORQUE_LIMIT)
    sp_rb = ac_rb = None
    print(f"起始 {start}  RAM P={kp_ram} D={kd_ram}｜EEPROM P={kp_ee} D={kd_ee}")
    print(f"原限速 reg46={sp_orig} reg41={ac_orig}｜限流 reg48={tl_orig}（测完恢复）")
    print(f"行程限制 reg9/reg11 = {amin}/{amax}　幅度 ±{amp_steps} 步 "
          f"({args.sine_amp_deg}°)")

    # 中心必须让整个行程落在限位内，否则正弦会被机械限位削顶 ——
    # 削顶后基波拟合出来的"幅值比"是假的。
    center = start
    if amin is not None and amax is not None and amax > amin:
        lo, hi = amin + amp_steps, amax - amp_steps
        if lo <= hi:
            if not (lo <= center <= hi):
                center = int((amin + amax) // 2)
                print(f"⚠️ 起始位置 {start} 会让正弦撞限位 ⇒ 中心移到 {center}")
        else:
            sys.exit(f"幅度 ±{amp_steps} 超出行程 [{amin},{amax}]，减小 --sine-amp-deg")

    dt_s = 1.0 / args.rate
    freqs = [float(x) for x in args.sine_freqs.split(",") if x.strip()]
    if not freqs:
        sys.exit("--sine-freqs 为空")
    # 采样定理闸门：每周期样本数太少，基波幅值会被混叠污染。
    min_pts = min(args.rate / f for f in freqs)
    if min_pts < 10:
        sys.exit(f"每周期仅 {min_pts:.1f} 点（{args.rate} Hz 采 {max(freqs)} Hz），"
                 f"至少要 10 点/周期；提高 --rate 或降低 --sine-freqs")

    SINE_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(unique_path(args.csv or str(
        SINE_DIR / f"sine_id{sid}_kp{target_p}_kd{target_d}.csv")))
    f = open(path, "w", newline="", buffering=1)
    writer = csv.writer(f)
    writer.writerow(["freq", "t_goal_ms", "t_pos_ms", "goal", "pos", "speed",
                     "load", "volt", "temp_c", "cur_ma"])
    rows, miss = [], 0
    total_s = sum(max(args.sine_cycles, 1.0) / fr for fr in freqs)
    print(f"录制 → {path}：{len(freqs)} 档频率，每档 {args.sine_cycles} 周期，"
          f"共约 {total_s:.0f}s，{args.rate:g} Hz。Ctrl-C 中止，数据照常落盘。")
    try:
        bus.write_u16(sid, REG_GOAL, center)
        time.sleep(0.3)
        got_p, got_d = _write_gains(bus, sid, target_p, target_d)
        if (got_p, got_d) != (target_p, target_d):
            print(f"✗ 增益未生效：写入 ({target_p},{target_d}) → 回读 ({got_p},{got_d})")
            sys.exit("增益回读不符，拒测")
        print(f"✔ 增益生效 RAM P={got_p} D={got_d}（回读确认）")

        # ① 限速/限流必须在第一次写 goal 之前落到位（_arm 的注释：顺序不能反）
        bus.write_u16(sid, REG_SPEED, args.sine_speed)
        bus.write_u8(sid, REG_ACCEL, args.sine_accel)
        bus.write_u16(sid, REG_TORQUE_LIMIT, args.torque_limit)
        time.sleep(0.1)
        sp_rb = bus.read_u16(sid, REG_SPEED)
        ac_rb = bus.read_u8(sid, REG_ACCEL)
        print(f"✔ 限速 reg46 → {sp_rb}（请求 {args.sine_speed}"
              + ("" if sp_rb == args.sine_speed else "  ⚠️ 回读被截断，固件上限如此")
              + f"）　加速度 reg41 → {ac_rb}")
        need_v = args.sine_amp_deg * 2 * math.pi * max(freqs)   # deg/s
        print(f"  正弦峰值速度需求 {need_v:.0f} °/s"
              f"（{need_v / 360 * STEPS_PER_REV:.0f} 步/s，按 reg46=步/s 口径）"
              f"　若 reg46 上限低于此值 ⇒ 限速削波，本测量只反映限速")

        for fr in freqs:
            n_steps = int(round(args.sine_cycles / fr * args.rate))
            w = 2.0 * math.pi * fr
            print(f"  ── {fr:g} Hz × {args.sine_cycles:g} 周期（{n_steps} 点）")
            t0 = time.perf_counter()
            next_t = t0
            for i in range(n_steps):
                tgt = center + amp_steps * math.sin(w * (i * dt_s))
                t_send = time.perf_counter()
                bus.write_u16(sid, REG_GOAL, int(round(tgt)))
                t_goal_done = time.perf_counter()
                t_read = time.perf_counter()
                tm = telemetry(bus, sid)
                t_pos = time.perf_counter()
                tg_ms = (t_goal_done - t0) * 1000.0
                tp_ms = (t_read - t0) * 1000.0
                if tm is None:
                    miss += 1
                    writer.writerow([fr, f"{tg_ms:.1f}", f"{tp_ms:.1f}",
                                     int(round(tgt)), "", "", "", "", "", ""])
                else:
                    writer.writerow([fr, f"{tg_ms:.1f}", f"{tp_ms:.1f}",
                                     int(round(tgt)), tm["pos"], tm["speed"],
                                     tm["load"], f"{tm['volt']:.1f}", tm["temp"],
                                     f"{tm['cur_ma']:.0f}"])
                    rows.append((fr, tg_ms, tp_ms, int(round(tgt)), tm["pos"],
                                 tm["speed"], tm["load"], tm["volt"], tm["temp"],
                                 tm["cur_ma"]))
                next_t += dt_s
                slack = next_t - time.perf_counter()
                if slack > 0:
                    time.sleep(slack)
                else:
                    next_t = time.perf_counter()
            # 回到中心再切下一档，避免档间阶跃污染下一档的拟合
            bus.write_u16(sid, REG_GOAL, center)
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n手动中止")
    finally:
        _disarm(bus, sid)
        try:
            bus.write_u16(sid, REG_SPEED, sp_orig)
            bus.write_u8(sid, REG_ACCEL, ac_orig)
            bus.write_u16(sid, REG_TORQUE_LIMIT, tl_orig)
            sr, ar = bus.read_u16(sid, REG_SPEED), bus.read_u8(sid, REG_ACCEL)
            tr = bus.read_u16(sid, REG_TORQUE_LIMIT)
            ok = (sr, ar, tr) == (sp_orig, ac_orig, tl_orig)
            print(f"{'✔' if ok else '✗'} 限速/限流恢复 "
                  f"reg46={sr} reg41={ar} reg48={tr}（原 {sp_orig}/{ac_orig}/{tl_orig}）")
        except Exception as e:
            print(f"✗ 限速恢复失败：{e}  ⚠️ 舵机仍是无限速状态，"
                  f"下次上电或手动写 reg46={sp_orig}")
        if args.kp is not None or args.kd is not None:
            try:
                rp, rd = _write_gains(bus, sid, kp_ram, kd_ram)
                ok = (rp, rd) == (kp_ram, kd_ram)
                print(f"{'✔' if ok else '✗'} 增益恢复 RAM P={rp} D={rd}"
                      f"（原 {kp_ram}/{kd_ram}）")
            except Exception as e:
                print(f"✗ 增益恢复失败：{e}  ⚠️ RAM P/D 可能仍是 {target_p}/{target_d}")
        f.close()

    print(f"有效样本 {len(rows)}，丢包 {miss}"
          + ("  ⚠️ 有丢包，拟合可能偏" if miss else ""))
    volt = [r[7] for r in rows if r[7] is not None]
    if volt:
        print(f"电压 {min(volt):.1f}~{max(volt):.1f} V　⚠️ 台架电压≠部署 7.4 V，"
              f"滞后读数是上界")

    print(f"\n{'freq':>6} {'目标°':>7} {'输出°':>7} {'幅值比':>7} {'损失%':>7} "
          f"{'滞后°':>7} {'滞后ms':>8} {'跟踪RMS°':>9} {'峰流mA':>8}  判据")
    results = []
    for fr in freqs:
        m = sine_metrics(rows, fr, skip_cycles=args.sine_skip_cycles)
        if m is None:
            print(f"{fr:>6g} {'—':>7} {'—':>7} {'—':>7} {'—':>7} {'—':>7} "
                  f"{'—':>8} {'—':>9} {'—':>8}  样本不足")
            continue
        results.append(m)
        # 滞后 >180° 会被 wrap 成负（atan2 的值域），直接读会看成"超前"。
        lag = m["lag_deg"]
        star = ""
        if lag < -90.0:                      # 真滞后 = lag+360，已超过半个周期
            lag += 360.0
            star = "*"
        verdict = ("跟上" if m["gain"] >= 0.8 and lag <= 30
                   else "勉强" if m["gain"] >= 0.6 and lag <= 60
                   else "跟不上")
        print(f"{fr:>6g} {m['amp_goal_deg']:>7.2f} {m['amp_pos_deg']:>7.2f} "
              f"{m['gain']:>7.3f} {m['loss_pct']:>7.1f} {lag:>7.1f}{star:<1} "
              f"{m['lag_ms']:>8.1f} {m['rms_track_err_deg']:>9.2f} "
              f"{m['cur_ma_peak']:>8.0f}  {verdict}")
    if results:
        json_path = path.with_suffix(".json")
        json_path.write_text(json.dumps(
            {"servo_id": sid, "kp": target_p, "kd": target_d,
             "amp_deg": args.sine_amp_deg, "rate_hz": args.rate,
             "speed_reg46": sp_rb, "accel_reg41": ac_rb,
             "torque_limit": args.torque_limit, "center": center,
             "voltage_v": [min(volt), max(volt)] if volt else None,
             "csv": str(path), "freqs": results},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n指标 → {json_path}")
    print("口径：幅值比 = 输出基波/输入基波；"
          "≥0.8 且滞后≤30° 判『跟上』，<0.6 或滞后>60° 判『跟不上』。")
    print("  * = 真滞后 >半个周期，被 atan2 折成负数，本表已加回 360°。")
    print("对表：仿真 plant 预测 P=5 在 1.89 Hz 约 35% 幅值损失 / 70° 滞后。")
    print("⚠️ 只凭 gain/lag 两个数字不够：本仪器对频率错标不敏感（见 selftest），"
          "削波/失真也能给出像样的数 —— 必须同时看残差和原始 CSV。")
    # 供 cmd_psweep 复用：单档扫描也要能拿到原始行，否则 P 扫描就得重写一遍
    # 录制循环 —— 那是两个实现互抵，本项目明确禁止。
    return results, rows


def cmd_psweep(bus: Bus, sid: int, args):
    """P 扫描：同一正弦、同一行程、只改 RAM P，**同时**量带宽与震颤。

    ★ 为什么必须二维判据（本子命令存在的唯一理由）
      只报 gain 的扫描一定会把 P 推到上限：gain 随 P 单调涨，数字很好看，
      而真机上早就抖成一团。社区记录「实机 P 大颤」不是传说。
      所以每一档都同时给 ``jerk_rms``（位置二阶差分，对抖动最敏感）与
      ``hf_ratio``（残差里 >3f0 的能量占比），并按最小 P 档归一化。

    ★ 与单个 --kp 测量的关系
      内部**直接调用 cmd_sine**，不复制录制循环 —— 两个实现互抵是本项目明确
      禁止的事。因此各档之间只差一个寄存器，行程中心 / 限速 / 限流 / 采样率
      / 周期数完全一致，这是"可比"的前提。

    ★ 不写 EEPROM
      只动 RAM reg50/reg51（掉电回落），不碰 reg21/22。cmd_sine 每档结束会把
      RAM 增益恢复成进来时的值，所以档间不会互相污染。
    """
    import argparse as _ap

    kps = []
    for tok in str(args.kp_list).split(","):
        tok = tok.strip()
        if tok:
            kps.append(int(tok))
    if not kps:
        sys.exit("--kp-list 为空")
    freqs = [float(x) for x in args.sine_freqs.split(",") if x.strip()]
    if not freqs:
        sys.exit("--sine-freqs 为空")
    if len(freqs) > 1:
        print("⚠️ psweep 只用第一个频率；要多频请分次跑（各档必须同频才可比）")
    fr = freqs[0]

    out, base = [], None
    for kp in kps:
        print(f"\n{'=' * 20} RAM P={kp}  D=0 {'=' * 20}")
        sub = _ap.Namespace(
            kp=kp, kd=0, dry_run=False,
            sine_freqs=args.sine_freqs, sine_amp_deg=args.sine_amp_deg,
            sine_cycles=args.sine_cycles, sine_skip_cycles=args.sine_skip_cycles,
            rate=args.rate, csv=str(SINE_DIR / f"psweep_id{sid}_kp{kp}.csv"),
            sine_speed=args.sine_speed, sine_accel=args.sine_accel,
            torque_limit=args.torque_limit)
        try:
            res, rows = cmd_sine(bus, sid, sub)
        except SystemExit as e:
            print(f"✗ P={kp} 中止（{e}），继续下一档")
            continue
        m = next((r for r in res if abs(r["freq_hz"] - fr) < 1e-9), None)
        t = tremor_metrics(rows, fr, skip_cycles=args.sine_skip_cycles)
        if m is None or t is None:
            print(f"✗ P={kp} 拟合失败（样本不足或被限位削顶）")
            continue
        if base is None:
            base = {"kp": kp, "gain": m["gain"], "jerk": t["jerk_rms_deg"]}
        out.append({
            "kp": kp, "gain": m["gain"], "lag_deg": m["lag_deg"],
            "rms_resid_deg": t["rms_resid_deg"], "hf_ratio": t["hf_ratio"],
            "jerk_rms_deg": t["jerk_rms_deg"], "cur_ma_peak": m["cur_ma_peak"],
            "rms_track_err_deg": m["rms_track_err_deg"],
        })

    if not out:
        sys.exit("没有一档成功，无法比较")

    print(f"\n{'=' * 92}")
    print(f"P 扫描汇总　{fr:g} Hz　±{args.sine_amp_deg:g}°　"
          f"基线 = 最小 P（P={base['kp']}）")
    print(f"{'P':>4} {'gain':>7} {'滞后°':>7} {'残差°':>7} {'hf%':>6} {'jerk°':>7} "
          f"{'gain×':>6} {'jerk×':>6} {'峰流mA':>7}  判据")
    print("-" * 92)
    for r in out:
        gx = r["gain"] / base["gain"] if base["gain"] else float("nan")
        jx = r["jerk_rms_deg"] / base["jerk"] if base["jerk"] else float("nan")
        if r["gain"] >= 0.6 and jx <= 2.0:
            verdict = "可用"
        elif r["gain"] >= 0.6:
            verdict = "带宽够但抖 ⚠️"
        else:
            verdict = "带宽不足"
        print(f"{r['kp']:>4} {r['gain']:>7.3f} {r['lag_deg']:>7.1f} "
              f"{r['rms_resid_deg']:>7.2f} {r['hf_ratio'] * 100:>6.2f} "
              f"{r['jerk_rms_deg']:>7.4f} {gx:>6.2f} {jx:>6.2f} "
              f"{r['cur_ma_peak']:>7.0f}  {verdict}")
    print("-" * 92)
    print("口径：『可用』= gain≥0.6 且 jerk ≤ 2× 基线。")
    print("  **jerk**（位置二阶差分 RMS，单位度）是主判据 —— 已在历史数据上验证有区分度："
          "P32 0.41 vs P5 0.14（2.7×）。")
    print("  hf%（残差里 >3f0 的能量占比）只作参考：同一 P 重复测量在 25~68% 间跳，"
          "不可单独判据。")
    print("⚠️ 阈值是相对判据，不是规格：飞特没给 P 与带宽的曲线，只能同条件跨 P 横比，"
          "并回看原始 CSV 是否出现静止位微振。")

    p = Path(unique_path(str(SINE_DIR / f"psweep_id{sid}.json")))
    p.write_text(json.dumps({
        "servo_id": sid, "freq_hz": fr, "amp_deg": args.sine_amp_deg,
        "rate_hz": args.rate, "cycles": args.sine_cycles,
        "baseline_kp": base["kp"], "ladder": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"扫描结果 → {p}")
    return out


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

    # ---- sine_metrics：合成正弦，验证幅值比 / 相位滞后能被还原 ----
    print("\n=== 正弦指标：应还原已知的 gain / lag ===")
    ok5 = True
    for gain0, lag0 in ((0.8, 30.0), (1.0, 0.0), (0.65, 70.0)):
        rows5 = synth_sine(2048, 192, 1.89, 6.0, gain=gain0, lag_deg=lag0)
        m = sine_metrics(rows5, 1.89)
        dg = abs(m["gain"] - gain0)
        dl = abs(m["lag_deg"] - lag0)
        good = dg < 0.02 and dl < 2.0
        ok5 &= good
        print(f"  真值 gain={gain0:.2f} lag={lag0:>4.1f}° → 拟合 "
              f"gain={m['gain']:.3f} lag={m['lag_deg']:>6.1f}°  "
              f"{'ok' if good else 'FAIL'}")

    print("=== 已知局限（不作判据）：拟合对频率误差不敏感 ===")
    # 数据是真 1.89 Hz，标签写成 2.457 Hz。结果 gain=0.809（真值 0.8）、
    # lag=+21.9°（真值 30°）—— 两个都没崩。原因：goal 与 pos 同频，投影到错基波上
    # 分子分母被**同等缩放**，比值近乎不变；相位受的影响也远小于预期。
    # ⇒ **这份仪器挑不出频率错标**。真机上对应的风险是：被限速削成三角波、
    # 或撞限位削顶的信号，照样能给出一个"看起来合理"的 gain/lag。
    # 所以每次测量必须**另外看残差**（下一条）和原始 CSV，不能只信这两个数。
    rows6 = [(1.89 * 1.3,) + r[1:]
             for r in synth_sine(2048, 192, 1.89, 6.0, gain=0.8, lag_deg=30.0)]
    m6 = sine_metrics(rows6, 1.89 * 1.3)
    print(f"  1.3× 频率拟合 → gain={m6['gain']:.3f} lag={m6['lag_deg']:+.1f}° "
          f"（真值 0.8 / 30°）—— 都没崩，见上方说明")

    print("=== 负对照：削波必须能被残差发现（否则上一条的局限无解）===")
    rows_pure = synth_sine(2048, 192, 1.89, 6.0, gain=0.8, lag_deg=30.0)
    clip = 0.6 * 192                      # 削到 60% —— 撞限位 / 被限速削顶的形状
    rows_clip = [(r[0], r[1], r[2], r[3], 2048.0 + max(-clip, min(clip, r[4] - 2048.0)),
                  0, 0, 7.4, 30, 0.0) for r in rows_pure]
    mp, mc = sine_metrics(rows_pure, 1.89), sine_metrics(rows_clip, 1.89)
    # 判据用**相对**残差：绝对门槛会随幅度变，而"曲线不像正弦"是形状问题。
    # 实测纯正弦 ≈0%，削到 60% 时 ≈6.8%（三次谐波），门槛取 3%。
    rp = 100.0 * mp["rms_resid_deg"] / max(1e-9, mp["amp_pos_deg"])
    rc = 100.0 * mc["rms_resid_deg"] / max(1e-9, mc["amp_pos_deg"])
    ok6 = rc > 3.0 and rp < 0.1
    print(f"  纯正弦 resid={rp:.3f}% → 削波后 resid={rc:.2f}%（应 >3%）  "
          f"{'ok' if ok6 else 'FAIL'}")
    print(f"  同时 gain 被拉低 {mp['gain']:.3f}→{mc['gain']:.3f}："
          f"削波会让『跟不上』看起来更严重，读数偏保守")

    print("=== 负对照：输出完全不动 ⇒ 幅值比必须 ≈0（不能读成『跟上』）===")
    rows6b = [(1.89, r[1], r[2], r[3], 2048.0, 0, 0, 7.4, 30, 0.0)
              for r in synth_sine(2048, 192, 1.89, 6.0)]
    m6b = sine_metrics(rows6b, 1.89)
    ok6b = m6b is not None and m6b["gain"] < 0.05
    print(f"  pos 恒为中点 → gain={m6b['gain']:.4f}（应 <0.05）  "
          f"{'ok' if ok6b else 'FAIL'}")

    print("=== 负对照：直流偏置不能被算进幅值（P5 实测有 −2 步稳态误差）===")
    rows7 = synth_sine(2048, 192, 1.89, 6.0, gain=0.8, lag_deg=30.0, dc_err=-40)
    m7 = sine_metrics(rows7, 1.89)
    ok7 = abs(m7["gain"] - 0.8) < 0.02 and abs(m7["dc_err_steps"] + 40) < 3
    print(f"  偏置 −40 步 → gain={m7['gain']:.3f} dc_err={m7['dc_err_steps']:+.1f} 步  "
          f"{'ok' if ok7 else 'FAIL'}")

    print("=== 峰速口径：必须由位置差分算，不能由遥测 speed 字段算 ===")
    # 真机 speed 字段的单位不是 步/s（实测 1 unit ≈ 53 步/s）。把它按 1/54 缩放后
    # 重算，峰速必须**完全不变**——因为新口径只读位置。这正是旧口径（直接拿字段
    # 当 步/s 打印，高估 54×）踩的坑；负对照保证它不会以另一种形式回来。
    rows_v = synth_step(2000, 2200, 3.0, zeta=0.35)
    mv = step_metrics(rows_v, "up", 2200, 5)
    rows_v54 = [(r[0], r[1], r[2], r[3], r[4] / 54.0, r[5], r[6]) for r in rows_v]
    mv54 = step_metrics(rows_v54, "up", 2200, 5)
    ok_v = (
        abs(mv["v_p95_steps"] - mv54["v_p95_steps"]) < 1e-6
        and abs(mv54["speed_field_peak_raw"] * 54.0 - mv["speed_field_peak_raw"]) < 1e-6
        and mv["v_p95_steps"] > 0.0
    )
    print(f"  位置差分峰速 p95 = {mv['v_p95_steps']:.1f} 步/s "
          f"({mv['v_p95_deg_s']:.0f} °/s)"
          f"；speed 字段 ÷54 后仍 = {mv54['v_p95_steps']:.1f} 步/s  "
          f"{'ok' if ok_v else 'FAIL'}")

    print("=== 负对照：峰速必须与保持时长无关（窗口不能含静止段）===")
    # 实测踩过：hold 从 2 s 改 3 s，同一颗舵机同一参数，p95 从 661 掉到 525 步/s。
    # 原因是 p95 在整个相位窗口上算，静止样本稀释了分位点。修法是截到 settle。
    # 判据：把静止尾段拉长一倍，新口径必须**完全不变**，旧口径必须明显下降。
    rows_long = synth_step(2000, 2200, 6.0, zeta=0.35)   # hold 3 s → 6 s
    mv_long = step_metrics(rows_long, "up", 2200, 5)
    inv_new = abs(mv["v_p95_steps"] - mv_long["v_p95_steps"]) < 1e-6
    inv_old = mv_long["v_p95_full_steps"] < mv["v_p95_full_steps"] * 0.9
    print(f"  hold 3s → 6s：新口径 {mv['v_p95_steps']:.1f} → {mv_long['v_p95_steps']:.1f}"
          f"（应完全相同）{'ok' if inv_new else 'FAIL'}")
    print(f"                 旧口径 {mv['v_p95_full_steps']:.1f} → "
          f"{mv_long['v_p95_full_steps']:.1f}（应明显下降，证明旧口径确实有依赖）"
          f"{'ok' if inv_old else 'FAIL'}")

    print("=== 负对照：样本不足应返回 None 而不是崩 ===")
    ok8 = sine_metrics([(1.89, 0, 0, 2048, 2048, 0, 0, 7.4, 30, 0)] * 5, 1.89) is None
    print(f"  5 样本 → {sine_metrics([(1.89, 0, 0, 2048, 2048, 0, 0, 7.4, 30, 0)] * 5, 1.89)}")

    allok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok6b and ok7 and ok8 and ok_v \
        and inv_new and inv_old
    print(f"\nselftest: {'ALL PASSED' if allok else 'FAILED'}")
    return 0 if allok else 1


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="HD-1910 辨识台架")
    ap.add_argument("cmd", choices=["telem", "step", "sine", "psweep", "deadzone",
                                     "backlash", "set-id", "selftest"])
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="不碰硬件（仅部分子命令支持）")
    ap.add_argument("--seconds", type=float, default=10, help="telem 时长")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--steps", type=int, default=200, help="step 阶跃幅度（步）")
    ap.add_argument("--hold", type=float, default=2.0, help="step 每段保持秒数")
    ap.add_argument("--rate", type=float, default=50.0, help="step 采样率 Hz（默认 50）")
    ap.add_argument("--pre", type=float, default=1.0, help="step 静置秒数")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--max-step", type=int, default=20, help="deadzone 最大探测步")
    ap.add_argument("--approach", type=int, default=100, help="backlash 趋近距离")
    ap.add_argument("--speed", type=int, default=300, help="reg46 目标速度（步/s）")
    ap.add_argument("--accel", type=int, default=10, help="reg41 加速度（×100 步/s²）")
    # ⚠️ help 字符串里不能出现裸 `%`：argparse 会对它做 %-format，
    # 于是 --help 整个崩在 _expand_help（这里曾经写成 "1000=100%"，帮助页打不出来）。
    ap.add_argument("--torque-limit", type=int, default=500,
                    help="reg48 扭矩上限（1000 = 满量程）")
    ap.add_argument("--new-id", type=int, default=None,
                    help="set-id：新总线 ID（0-253）")
    ap.add_argument("--kp", type=int, default=None,
                    help="step：临时写 reg50（RAM P），测完恢复原值；不动 EEPROM reg21")
    ap.add_argument("--kd", type=int, default=None,
                    help="step：临时写 reg51（RAM D）。只给 --kp 时自动置 0（BAM 纯 P 律）")
    ap.add_argument("--sine-freqs", default="1.0,1.5,1.89,2.5",
                    help="sine：扫描频率（Hz，逗号分隔）。1.89 是步态主频")
    ap.add_argument("--sine-amp-deg", type=float, default=16.9,
                    help="sine：正弦振幅（度）。默认取 knee 半幅 = 策略实际要求的行程")
    ap.add_argument("--sine-cycles", type=float, default=6.0,
                    help="sine：每档频率跑多少个周期")
    ap.add_argument("--sine-skip-cycles", type=float, default=1.0,
                    help="sine：拟合时丢弃开头几个周期（躲掉起步瞬态）")
    ap.add_argument("--sine-speed", type=int, default=4095,
                    help="sine：reg46 限速。★ 默认 300 会把 1.89Hz×±17° 的正弦削成"
                         "三角波，测出来是限速不是 P ⇒ sine 默认把它拉到最大")
    ap.add_argument("--sine-accel", type=int, default=254,
                    help="sine：reg41 加速度上限，同理解限速")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="step：把指标（含 reg46/41/48 的请求值与**回读值**）写成 JSON。"
                         "A/B 靠它对比，别再靠肉眼读打印行")
    ap.add_argument("--kp-list", default="5,8,12,16,24,32",
                    help="psweep：要扫的 RAM P 列表（逗号分隔）。P3 部署值是 5，"
                         "实测带宽不足；本扫描找『带宽够且不颤』的档位")
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
        if args.cmd in ("step", "sine", "psweep", "deadzone", "backlash"):
            mode = bus.read_u8(args.id, REG_MODE)
            print(f"  reg33 mode = {mode}（本脚本所有实测结论基于 mode=4）")
            if mode != 4:
                print(f"  ⚠️ mode={mode} ≠ 4：『reg40 拦不住运动』『写 goal 立即执行』"
                      f"两条实测结论在别的模式下可能不成立，先小幅度试一次再放量。")
            p = bus.read_u8(args.id, REG_P_GAIN)
            print(f"  reg21 P = {p}"
                  + ("" if p == KP_FW_P3 else
                     f"  ⚠️ P3 部署值是 {KP_FW_P3}，两边不对齐时这份辨识不代表部署后行为"))
        {"telem": cmd_telem, "step": cmd_step, "sine": cmd_sine,
         "psweep": cmd_psweep, "deadzone": cmd_deadzone, "backlash": cmd_backlash,
         "set-id": cmd_set_id}[args.cmd](bus, args.id, args)
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
