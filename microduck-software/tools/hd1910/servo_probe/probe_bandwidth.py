#!/usr/bin/env python3
"""正弦跟踪带宽：mode 0 vs mode 4 在小幅连续运动下还差一倍吗？

为什么需要这一条
----------------
`probe_mode_ab.py` 量的是**阶跃**：mode 0 的 10–90% 上升时间恒为 mode 4 的 1.9–2.0 倍，
与 `reg46`、`reg41`、阶跃幅度都无关。但阶跃是"末端定位"，而走路是**小幅连续跟踪**——
2 Hz 步频、关节峰值角速度 ~190°/s。阶跃慢不等于带宽低：内部若有一段速度规划，
阶跃会被规划拖长，而连续跟踪时规划已经饱和、不再限制。

所以判决要看**增益与相位**，不是上升时间：

    gain(f)  = 实测位置振幅 / 命令振幅        （幅值衰减）
    lag(f)   = 命令相位 − 位置相位            （滞后，度）

命令以 50 Hz 更新（= robotd 的控制周期），f 取 0.5–4 Hz（步频 2 Hz 上下各一档）。

用法
    python probe_bandwidth.py --port COM3 --ids 1            # 两模式都测
    python probe_bandwidth.py --selftest                     # 不碰硬件
"""

from __future__ import annotations

import argparse
import math
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hd1910_ident as ident  # noqa: E402

REG_MODE = 33
REG_ACCEL = 41
TICK = 0.02                     # 50 Hz，与 robotd 一致
FREQS = (0.5, 1.0, 2.0, 3.0, 4.0)


def _fit(t: list[float], y: list[float], f: float):
    """在频率 f 上的正弦投影 → (幅值, 相位 rad)。只对整数个周期才有意义。"""
    n = len(y)
    if n < 8:
        return None
    w = 2.0 * math.pi * f
    i = sum(yi * math.cos(w * ti) for ti, yi in zip(t, y)) * 2.0 / n
    q = sum(yi * math.sin(w * ti) for ti, yi in zip(t, y)) * 2.0 / n
    # y = sin(wt + θ) ⇒ i = sinθ, q = cosθ ⇒ 相位 θ = atan2(i, q)。
    # 写成 atan2(q, i) 得到的是 90°−θ，lag 会整体镜像（自检逮到的）。
    return math.hypot(i, q), math.atan2(i, q)


def gains(rec: list[tuple[float, int, int]], f: float, cycles: int = 2):
    """取最后 `cycles` 个整周期做拟合，返回 (gain, lag_deg)。"""
    if not rec:
        return None
    t_end = rec[-1][0]
    t_start = t_end - cycles / f
    seg = [r for r in rec if r[0] >= t_start]
    if len(seg) < 20:
        return None
    t = [r[0] - seg[0][0] for r in seg]
    cmd = [r[1] for r in seg]
    pos = [r[2] for r in seg]
    fc = _fit(t, cmd, f)
    fp = _fit(t, pos, f)
    if not fc or not fp or fc[0] < 1e-9:
        return None
    gain = fp[0] / fc[0]
    lag = math.degrees(fc[1] - fp[1])
    while lag > 180:
        lag -= 360
    while lag < -180:
        lag += 360
    return gain, lag


def verdict(m4: dict, m0: dict, *, gain_tol=0.20, lag_tol=10.0) -> str:
    """两模式的带宽差。m4/m0: {freq: (gain, lag)}"""
    common = sorted(set(m4) & set(m0))
    if not common:
        return "无法判决（没有共同频率）"
    rows, worst_g, worst_l = [], 0.0, 0.0
    for f in common:
        g4, l4 = m4[f]
        g0, l0 = m0[f]
        dg = (g0 - g4) / g4 if g4 else float("nan")
        dl = l0 - l4
        worst_g = max(worst_g, abs(dg))
        worst_l = max(worst_l, abs(dl))
        rows.append(f"    {f:4.1f} Hz  gain {g4:.2f} → {g0:.2f} ({dg:+.0%})   "
                    f"lag {l4:+.0f}° → {l0:+.0f}° ({dl:+.0f}°)")
    head = ("两模式在小信号连续跟踪下**等价**（≤20% 增益 / ≤10° 相位）"
            if worst_g <= gain_tol and worst_l <= lag_tol
            else "两模式在小信号下也**不等价** ⇒ mode 0 的影响不能忽略")
    return head + "\n" + "\n".join(rows)


def selftest() -> int:
    """合成：位置=命令的一阶滞后系统，已知 gain/lag，检查能不能读出来。"""
    def synth(f, gain, lag_deg, cycles=3, amp=150, n_per=TICK):
        w = 2 * math.pi * f
        rec, t = [], 0.0
        while t < cycles / f:
            c = amp * math.sin(w * t)
            p = gain * amp * math.sin(w * t - math.radians(lag_deg))
            rec.append((t, int(round(c)), int(round(p))))
            t += n_per
        return rec

    bad = 0
    for f, g, l in ((1.0, 1.00, 0.0), (2.0, 0.80, -25.0), (4.0, 0.35, -70.0)):
        got = gains(synth(f, g, l), f)
        ok = got is not None and abs(got[0] / g - 1) < 0.06 and abs(got[1] - l) < 6
        bad += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {f} Hz 真值 gain={g} lag={l}° → "
              f"{'None' if got is None else f'gain={got[0]:.3f} lag={got[1]:+.1f}°'}")

    # 负对照：真值差很多的两种系统，判决必须说"不等价"
    a = {2.0: (1.0, 0.0)}
    b = {2.0: (0.5, -60.0)}
    v = verdict(a, b)
    ok = v.startswith("两模式在小信号下也")
    bad += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] 负对照：gain 1.0→0.5 / lag 0→−60° 必须判不等价")

    # 同理，几乎一样的两种必须判等价（否则判据只会说"不等价"）
    c = {2.0: (0.98, -5.0)}
    v2 = verdict(a, c)
    ok2 = v2.startswith("两模式在小信号连续跟踪下")
    bad += 0 if ok2 else 1
    print(f"  [{'PASS' if ok2 else 'FAIL'}] 负对照：gain 1.0→0.98 / lag 0→−5° 必须判等价")
    print(f"  self-checks: {5 - bad}/5 pass")
    return 0 if bad == 0 else 1


def measure(bus, sid: int, *, mode: int, freq: float, amp: int, center: int,
            speed: int, cycles: int = 3) -> list[tuple[float, int, int]]:
    bus.write_u8(sid, REG_MODE, mode)
    time.sleep(0.25)
    if bus.read_u8(sid, REG_MODE) != mode:
        return []
    bus.write_u16(sid, ident.REG_SPEED, speed)
    time.sleep(0.03)
    bus.write_u8(sid, REG_ACCEL, 0)
    time.sleep(0.03)
    w = 2.0 * math.pi * freq
    dur = (cycles + 1) / freq                   # 多跑一个周期再取后两个，避开起始瞬态
    rec = []
    t0 = time.perf_counter()
    nxt = t0
    while True:
        now = time.perf_counter()
        if now - t0 > dur:
            break
        t = now - t0
        cmd = center + int(round(amp * math.sin(w * t)))
        bus.write_u16(sid, ident.REG_GOAL, cmd)
        p = bus.read_u16(sid, ident.REG_POS)
        if p is not None:
            rec.append((t, cmd, p))
        nxt += TICK
        slp = nxt - time.perf_counter()
        if slp > 0:
            time.sleep(slp)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="1")
    ap.add_argument("--amp", type=int, default=150, help="振幅（步）；150 步 ≈ 13°")
    ap.add_argument("--center", type=int, default=2014, help="正弦中心（物理行程中点）")
    ap.add_argument("--lo", type=int, default=1213)
    ap.add_argument("--hi", type=int, default=2816)
    ap.add_argument("--speed", type=int, default=1000)
    ap.add_argument("--freqs", default=",".join(str(f) for f in FREQS))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    freqs = [float(x) for x in a.freqs.split(",") if x.strip()]
    if not (a.lo <= a.center - a.amp and a.center + a.amp <= a.hi):
        print(f"振幅 {a.amp} 在中心 {a.center} 会撞限位 [{a.lo},{a.hi}]")
        return 1
    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    bus = ident.Bus(a.port)
    try:
        for sid in ids:
            if not bus.ping(sid):
                print(f"  ID {sid}: 无应答")
                continue
            mode0 = bus.read_u8(sid, REG_MODE)
            spd0 = bus.read_u16(sid, ident.REG_SPEED)
            print(f"  ID {sid}: 起始 mode={mode0}，中心 {a.center} 振幅 {a.amp} 步"
                  f"（{a.amp * 360 / 4096:.1f}°），50 Hz 命令")
            res = {}
            for mode in (mode0, 0):
                if mode in res:
                    continue
                got = {}
                for f in freqs:
                    rec = measure(bus, sid, mode=mode, freq=f, amp=a.amp,
                                  center=a.center, speed=a.speed)
                    g = gains(rec, f)
                    if g:
                        got[f] = g
                        print(f"    mode{mode} {f:4.1f} Hz: gain {g[0]:.3f}  "
                              f"lag {g[1]:+.1f}°  ({len(rec)} 点)")
                    else:
                        print(f"    mode{mode} {f:4.1f} Hz: 取不到")
                res[mode] = got
            # 收尾
            bus.write_u8(sid, REG_MODE, mode0)
            time.sleep(0.25)
            c = bus.read_u16(sid, ident.REG_POS)
            if c is not None:
                bus.write_u16(sid, ident.REG_GOAL, c)
            bus.write_u16(sid, ident.REG_SPEED, spd0 or 0)
            print(f"\n  收尾 mode={bus.read_u8(sid, REG_MODE)} reg46={spd0}")
            print()
            print("  判决: " + verdict(res.get(mode0, {}), res.get(0, {})))
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
