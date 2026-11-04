#!/usr/bin/env python3
"""同一条 2 Hz 正弦下，P=8 / P=16 / P=24 各要多少电流？

为什么问
--------
2026-11-04 台架：mode 0 的速度上限完全是 P 造成的 —— P=8 只有 57 °/s，
P=16 就 99 °/s、等于 mode 4 在 P=8 的 100 °/s。于是"不用改 fork，把 reg50
从 8 提到 16"成了候选部署方案。

唯一可能的代价是电流。经验式 `duty% ≈ 5.1·kp` 是**静态**读出来的（记忆里
2026-11-03 那条），不能直接外推到"2 Hz 动态跟踪"。所以这里直接读 reg69
（present current）在整段正弦上的均值/峰值，和 P 一起比。

判据
----
- 峰值电流不撞过流、均值增幅远小于 P 的增幅 ⇒ 提 P 基本免费；
- 均值电流随 P 近似线性涨 ⇒ 就是 5.1·kp 那个静态关系，余量要重算。

用法
    python probe_power_cost.py --port COM3 --ids 10
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hd1910_ident as ident  # noqa: E402
import probe_bandwidth as pb  # noqa: E402

MA_PER_LSB = 6.5                    # STS 电流回读单位
CASES = ((0, 8), (0, 12), (0, 16), (0, 24), (4, 8))


def run(bus, sid: int, *, mode: int, p_gain: int, speed: int, freq: float,
        amp: int, center: int, cycles: int = 4, settle_s: float = 1.2):
    """站稳后跑正弦，同步采 goal/pos/current。"""
    bus.write_u8(sid, pb.REG_MODE, mode)
    time.sleep(0.25)
    bus.write_u8(sid, ident.REG_P_RAM, p_gain)      # 必须写在切 mode 之后
    time.sleep(0.05)
    bus.write_u16(sid, ident.REG_SPEED, speed)
    time.sleep(0.03)
    bus.write_u8(sid, pb.REG_ACCEL, 0)
    time.sleep(0.03)

    tick = pb.TICK
    t_set = time.perf_counter()
    nxt = t_set
    while time.perf_counter() - t_set < settle_s:
        bus.write_u16(sid, ident.REG_GOAL, center)
        nxt += tick
        slp = nxt - time.perf_counter()
        if slp > 0:
            time.sleep(slp)

    w = 2.0 * math.pi * freq
    dur = (cycles + 1) / freq
    rec, cur = [], []
    t0 = time.perf_counter()
    nxt = t0
    while True:
        if time.perf_counter() - t0 > dur:
            break
        t = time.perf_counter() - t0
        cmd = center + int(round(amp * math.sin(w * t)))
        bus.write_u16(sid, ident.REG_GOAL, cmd)
        p = bus.read_u16(sid, ident.REG_POS)
        c = bus.read_u16(sid, ident.REG_CURRENT)
        if p is not None:
            rec.append((t, cmd, p))
        if c is not None:
            cur.append(c)
        nxt += tick
        slp = nxt - time.perf_counter()
        if slp > 0:
            time.sleep(slp)
    return rec, cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="10")
    ap.add_argument("--speed", type=int, default=250)
    ap.add_argument("--freq", type=float, default=2.0)
    ap.add_argument("--amp", type=int, default=150)
    ap.add_argument("--center", type=int, default=2014)
    a = ap.parse_args()

    amp_deg = a.amp * 360 / 4096
    bus = ident.Bus(a.port)
    try:
        for sid in [int(x) for x in a.ids.split(",") if x.strip()]:
            if not bus.ping(sid):
                print(f"  ID {sid}: 无应答")
                continue
            mode0 = bus.read_u8(sid, pb.REG_MODE)
            p0 = bus.read_u8(sid, ident.REG_P_RAM)
            spd0 = bus.read_u16(sid, ident.REG_SPEED)
            v = (bus.read_u8(sid, 62) or 0) * 0.1
            print(f"  ID {sid}: 起始 mode={mode0} P={p0} reg46={spd0}  {v:.1f} V")
            print(f"  {a.freq:g} Hz / {amp_deg:.1f}°，电流单位 {MA_PER_LSB} mA/LSB")
            print("  🔴 reg69 在 ID10 上已验证**不是**电流：静止读 0、运动后 0x8001、"
                  "正弦中读到 16000 量级\n"
                  "     （按 6.5 mA/LSB 是 104 A）。下面电流列只用来对比相对变化，"
                  "绝对值和量级都不可引用。")
            print(f"{'mode':>5} {'P':>4} | {'gain':>6} {'v_peak':>8} | "
                  f"{'电流均值':>9} {'电流峰值':>9} | 稳态")
            rows = []
            for mode, p in CASES:
                rec, cur = run(bus, sid, mode=mode, p_gain=p, speed=a.speed,
                               freq=a.freq, amp=a.amp, center=a.center)
                an = pb.analyze(rec, a.freq)
                st, _ = pb.steady(rec, a.freq)
                if not an["ok"] or not cur:
                    print(f"{mode:>5} {p:>4} | 作废"
                          f"（{an.get('why', '没采到电流')}）")
                    continue
                mean = sum(cur) / len(cur) * MA_PER_LSB / 1000.0
                peak = max(cur) * MA_PER_LSB / 1000.0
                vp = an["gain"] * 2 * math.pi * a.freq * amp_deg
                rows.append((mode, p, vp, mean, peak))
                print(f"{mode:>5} {p:>4} | {an['gain']:>6.3f} {vp:>7.0f}° | "
                      f"{mean:>7.2f} A {peak:>7.2f} A | {'是' if st else '否'}")

            # 判据：把"速度涨了 X 倍"和"电流涨了 Y 倍"摆在一起，人只需要比这两个数
            m0 = [r for r in rows if r[0] == 0]
            if len(m0) >= 2:
                (_, p_lo, v_lo, i_lo, _), (_, p_hi, v_hi, i_hi, _) = m0[0], m0[-1]
                print(f"\n  P {p_lo}→{p_hi}: 速度 ×{v_hi / v_lo:.2f}，"
                      f"平均电流 ×{i_hi / i_lo:.2f}，"
                      f"峰值 {m0[0][4]:.2f}→{m0[-1][4]:.2f} A")
            m4 = [r for r in rows if r[0] != 0]
            if m4:
                _, p4, v4, i4, _ = m4[0]
                # 同速度比电流：这才是"改用 mode 4 换来的净收益"
                print(f"  mode{mode0} P={p4}: 速度 {v4:.0f}°/s，平均电流 {i4:.2f} A"
                      f"  ← 与同速度的 mode0 那一行比这一列")

            bus.write_u8(sid, pb.REG_MODE, mode0)
            time.sleep(0.25)
            bus.write_u8(sid, ident.REG_P_RAM, p0 or 8)
            c = bus.read_u16(sid, ident.REG_POS)
            if c is not None:
                bus.write_u16(sid, ident.REG_GOAL, c)
            bus.write_u16(sid, ident.REG_SPEED, spd0 or 250)
            print(f"  收尾 mode={bus.read_u8(sid, pb.REG_MODE)} "
                  f"P={bus.read_u8(sid, ident.REG_P_RAM)} "
                  f"reg46={bus.read_u16(sid, ident.REG_SPEED)}")
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
