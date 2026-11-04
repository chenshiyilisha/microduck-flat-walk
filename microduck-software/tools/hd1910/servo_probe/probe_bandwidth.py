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
MIN_PER_PERIOD = 10.0           # 每周期最少采样点
MAX_GAP_TICKS = 3               # 单次间隔不得超过 3 个 tick
MONOTONIC_TOL = 0.10            # gain 回升超过 10% 即判采集可疑
# 部署实际写的速度上限（duck-control/src/feetech.rs:107 `RUNNING_SPEED = 250`，
# 250 × 0.732 rpm ≈ 183 rpm，远高于 ~110 rpm 的空载转速 ⇒ 不受限）。
# ⚠️ 同文件 :61 明确写着 reg46 **0 表示停转**，不是"无限"。第一版默认 1000、
# 后来又试过 0，两者都不是部署值；用 0 时 mode 0 的舵机一动不动就是这条。
RUNNING_SPEED = 250
MIN_P2P = 4                     # 峰峰小于 4 步 = 位置几乎没动，不是"跟踪好"


def _solve3(A: list[list[float]], b: list[float]):
    """3×3 线性方程组，高斯消元（带部分主元）。"""
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        p = M[col][col]
        for r in range(col + 1, 3):
            fac = M[r][col] / p
            for k in range(col, 4):
                M[r][k] -= fac * M[col][k]
    x = [0.0, 0.0, 0.0]
    for r in (2, 1, 0):
        x[r] = (M[r][3] - sum(M[r][k] * x[k] for k in range(r + 1, 3))) / M[r][r]
    return x


def _fit(t: list[float], y: list[float], f: float):
    """拟合 y ≈ a + b·cos(wt) + c·sin(wt)，返回 (幅值, 相位 rad)。

    **带截距项的最小二乘**，不是裸投影。位置读数在 2014 counts 附近，而"最后 2
    个周期"的窗口落不到整数个周期上 ⇒ 裸投影里 DC 会漏进来，泄漏量正比于 1/n，
    于是每周期点数越少 gain 越虚高。2026-11-04 实测 gain 随频率从 0.09 升到
    0.88（被动系统不可能）就是这个 bug。

    先扣窗口均值只治一半 —— 非整数周期时窗口均值本身也被正弦带偏（实测还剩
    9% 误差）。把 DC 当自由参数一起解掉，对任意窗口长度都精确：数据若严格落在
    `a + b cos + c sin` 上，三个未知数必然被解出来，与窗口是否整数周期无关。
    """
    n = len(y)
    if n < 8:
        return None
    w = 2.0 * math.pi * f
    cs = [math.cos(w * ti) for ti in t]
    sn = [math.sin(w * ti) for ti in t]
    A = [[n, sum(cs), sum(sn)],
         [sum(cs), sum(ci * ci for ci in cs), sum(ci * si for ci, si in zip(cs, sn))],
         [sum(sn), sum(ci * si for ci, si in zip(cs, sn)), sum(si * si for si in sn)]]
    b = [sum(y), sum(yi * ci for yi, ci in zip(y, cs)), sum(yi * si for yi, si in zip(y, sn))]
    sol = _solve3(A, b)
    if sol is None:
        return None
    _, b1, b2 = sol                      # y = a + b1·cos + b2·sin
    # 写成 y = A·sin(wt + θ)：b1 = A sinθ, b2 = A cosθ ⇒ θ = atan2(b1, b2)。
    # 写成 atan2(b2, b1) 得到的是 90°−θ，lag 会整体镜像（自检逮到的）。
    return math.hypot(b1, b2), math.atan2(b1, b2)


def analyze(rec: list[tuple[float, int, int]], f: float, cycles: int = 2) -> dict:
    """取最后 `cycles` 个周期做拟合，并顺手做一次**独立交叉校验**。

    `gain` 是拟合出来的；`pos p2p` 是时域直接量的，两者互不依赖。任何信号的
    单频振幅都不可能超过峰峰值的一半，超了就是拟合坏了（不是"信号很强"）。
    上一轮 gain 随频率上升，正是这一条能当场逮住的。
    """
    if not rec:
        return {"ok": False, "why": "没采到点"}
    t_end = rec[-1][0]
    seg = [r for r in rec if r[0] >= t_end - cycles / f]
    if len(seg) < 20:
        return {"ok": False, "why": f"窗口内仅 {len(seg)} 点"}
    t = [r[0] - seg[0][0] for r in seg]
    cmd = [r[1] for r in seg]
    pos = [r[2] for r in seg]
    fc = _fit(t, cmd, f)
    fp = _fit(t, pos, f)
    if not fc or not fp or fc[0] < 1e-9:
        return {"ok": False, "why": "拟合失败"}
    p2p = max(pos) - min(pos)
    if p2p < MIN_P2P:
        # 舵机没动 —— 常见原因是 reg46 被写成 0（"停转"），也可能卡住。
        # 这不是"跟踪很差"，是数据没有意义，必须分开报。
        return {"ok": False, "p2p": p2p, "amp_cmd": fc[0],
                "why": f"位置几乎没动（峰峰 {p2p} 步，命令 {fc[0]:.0f}）——"
                       f"查 reg46 是否写成 0"}
    if fp[0] > 0.5 * p2p * 1.05:
        return {"ok": False, "amp_cmd": fc[0], "amp_pos": fp[0], "p2p": p2p,
                "why": f"拟合振幅 {fp[0]:.0f} 超过峰峰值一半 {p2p / 2:.0f}"}
    lag = math.degrees(fc[1] - fp[1])
    while lag > 180:
        lag -= 360
    while lag < -180:
        lag += 360
    return {"ok": True, "gain": fp[0] / fc[0], "lag": lag,
            "amp_cmd": fc[0], "amp_pos": fp[0], "p2p": p2p, "n": len(seg)}


def gains(rec: list[tuple[float, int, int]], f: float, cycles: int = 2):
    """兼容旧接口：只要 (gain, lag)，校验不过则 None。"""
    r = analyze(rec, f, cycles)
    return (r["gain"], r["lag"]) if r["ok"] else None


def rate_stats(rec: list[tuple[float, int, int]], f: float) -> dict:
    """这次采集到底能不能用 —— 采样密度与间隔抖动。

    上一轮 3/4 Hz 的数就是这么废掉的：gain 随频率**上升**（物理上不成立），
    回头查是每周期只有 ~12.5 点、还被训练进程抢 CPU。所以把判据写进工具，
    不留在人脑里：每周期点数 < MIN_PER_PERIOD，或最大间隔超过 3 个 tick，即作废。
    """
    if len(rec) < 2:
        return {"n": len(rec), "valid": False, "why": "没采到点"}
    dts = [rec[i + 1][0] - rec[i][0] for i in range(len(rec) - 1)]
    dts_sorted = sorted(dts)
    p95 = dts_sorted[int(0.95 * (len(dts_sorted) - 1))]
    span = rec[-1][0] - rec[0][0] or 1e-9
    rate = len(rec) / span
    per_period = rate / f
    why = []
    if per_period < MIN_PER_PERIOD:
        why.append(f"每周期仅 {per_period:.1f} 点 (<{MIN_PER_PERIOD})")
    if max(dts) > MAX_GAP_TICKS * TICK:
        why.append(f"最大间隔 {max(dts) * 1e3:.1f} ms "
                   f"(>{MAX_GAP_TICKS}×{TICK * 1e3:.0f} ms)")
    return {"n": len(rec), "rate": rate, "p95_ms": p95 * 1e3,
            "max_ms": max(dts) * 1e3, "per_period": per_period,
            "valid": not why, "why": "; ".join(why)}


def check_monotonic(freqs: list[float], got: dict) -> tuple[list[float], list[str]]:
    """被动系统的 gain 不可能随频率上升；升了就说明这次采集是坏的。

    返回 (可用频率, 说明行)。一旦在某个频率上看到 gain 回升，该频率及更高频
    一律标为可疑 —— 它大概率是同一次采集抖动，不是"电机变快了"。
    """
    notes, usable = [], []
    prev_f = prev_g = None
    for f in sorted(freqs):
        if f not in got:
            continue
        g = got[f][0]
        if prev_g is not None and g > prev_g * (1.0 + MONOTONIC_TOL):
            notes.append(f"    {f:4.1f} Hz gain {g:.2f} > {prev_f:.1f} Hz 的 "
                         f"{prev_g:.2f} ({g / prev_g - 1:+.0%}) —— 被动系统不可能，"
                         f"该频点及更高频作废")
            break
        usable.append(f)
        prev_f, prev_g = f, g
    return usable, notes


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
    def synth(f, gain, lag_deg, cycles=3, amp=150, n_per=TICK, offset=0):
        w = 2 * math.pi * f
        rec, t = [], 0.0
        while t < cycles / f:
            c = offset + amp * math.sin(w * t)
            p = offset + gain * amp * math.sin(w * t - math.radians(lag_deg))
            rec.append((t, int(round(c)), int(round(p))))
            t += n_per
        return rec

    # 计数由 chk() 自己累，不写死分母 —— 手写的 "9 - bad"/"10 - bad" 已经错过
    # 一次（9 项检查打印 10/10），自报的数字必须是真的。
    total = bad = 0

    def chk(name: str, ok: bool) -> None:
        nonlocal total, bad
        total += 1
        bad += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    for f, g, l in ((1.0, 1.00, 0.0), (2.0, 0.80, -25.0), (4.0, 0.35, -70.0)):
        got = gains(synth(f, g, l), f)
        ok = got is not None and abs(got[0] / g - 1) < 0.06 and abs(got[1] - l) < 6
        chk(f"{f} Hz 真值 gain={g} lag={l}° → "
            f"{'None' if got is None else f'gain={got[0]:.3f} lag={got[1]:+.1f}°'}", ok)

    # 负对照：真值差很多的两种系统，判决必须说"不等价"
    a = {2.0: (1.0, 0.0)}
    chk("负对照：gain 1.0→0.5 / lag 0→−60° 必须判不等价",
        verdict(a, {2.0: (0.5, -60.0)}).startswith("两模式在小信号下也"))

    # 同理，几乎一样的两种必须判等价（否则判据只会说"不等价"）
    chk("负对照：gain 1.0→0.98 / lag 0→−5° 必须判等价",
        verdict(a, {2.0: (0.98, -5.0)}).startswith("两模式在小信号连续跟踪下"))

    # 采集可用性：50 Hz 采 2 Hz 必须合格；12.5 点/周期必须判不可用
    rs = rate_stats(synth(2.0, 0.9, -20.0, cycles=3), 2.0)
    chk(f"50 Hz 采 2 Hz → 每周期 {rs['per_period']:.1f} 点，判可用",
        rs["valid"] and rs["per_period"] >= 20)

    rs2 = rate_stats(synth(4.0, 0.5, -60.0, cycles=3, n_per=0.08), 4.0)  # 12.5 Hz
    chk(f"12.5 Hz 采 4 Hz → 判不可用（{rs2['why']}）", not rs2["valid"])

    # gain 随频率上升 = 采集坏了，该频点及更高频必须作废
    rise = {0.5: (0.96, 20.0), 1.0: (0.85, 40.0), 2.0: (0.59, 73.0),
            3.0: (0.70, 60.0), 4.0: (0.80, 50.0)}
    keep, notes = check_monotonic([0.5, 1.0, 2.0, 3.0, 4.0], rise)
    chk(f"gain 在 3 Hz 回升 → 只保留 {keep}", keep == [0.5, 1.0, 2.0] and bool(notes))

    flat = {0.5: (0.96, 20.0), 1.0: (0.85, 40.0), 2.0: (0.59, 73.0)}
    keep2, notes2 = check_monotonic([0.5, 1.0, 2.0], flat)
    chk("单调下降的 profile 必须全部保留", keep2 == [0.5, 1.0, 2.0] and not notes2)

    # DC 偏置 + 非整数周期窗口：这是 2026-11-04 那个 bug 的现场（位置在 2014
    # counts 附近，窗口是"最后 2 个周期"但落不到整数个周期上）。不扣均值时
    # DC 会漏进投影，gain 随每周期点数变少而虚高。
    an = analyze(synth(2.0, 0.80, -25.0, cycles=4, offset=2014), 2.0, cycles=1.7)
    chk(f"带 2014 DC 偏置 + 1.7 周期窗口 → gain "
        f"{an.get('gain', float('nan')):.3f}（真值 0.80）/ lag "
        f"{an.get('lag', float('nan')):+.1f}°（真值 −25°）",
        an["ok"] and abs(an["gain"] - 0.80) < 0.06 and abs(an["lag"] + 25) < 6)

    # 交叉校验本身：拟合振幅超过峰峰值一半 = 拟合坏了，必须作废而不是"信号很强"
    real_fit = globals()["_fit"]
    globals()["_fit"] = lambda t, y, f: (1e6, 0.0)
    try:
        bad_an = analyze(synth(2.0, 1.0, 0.0), 2.0)
    finally:
        globals()["_fit"] = real_fit
    chk("拟合振幅超过峰峰一半 → 必须判作废", not bad_an["ok"])

    print(f"  self-checks: {total - bad}/{total} pass")
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
    ap.add_argument("--speed", type=int, default=RUNNING_SPEED,
                    help="reg46 速度上限；默认取部署值 250（0 = 停转，不是无限）")
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
                    an = analyze(rec, f)
                    rs = rate_stats(rec, f)
                    dens = (f"{rs['rate']:.1f} 点/s，每周期 {rs['per_period']:.1f} 点，"
                            f"p95 {rs['p95_ms']:.1f} ms，最大 {rs['max_ms']:.1f} ms"
                            if rs.get("rate") else rs.get("why", ""))
                    if an["ok"]:
                        got[f] = (an["gain"], an["lag"])
                        print(f"    mode{mode} {f:4.1f} Hz: gain {an['gain']:.3f}  "
                              f"lag {an['lag']:+.1f}°  （pos 峰峰 {an['p2p']} 步 /"
                              f" 振幅 {an['amp_pos']:.0f}；{an['n']} 点；{dens}）")
                        if not rs.get("valid"):
                            print(f"      但采集质量不合格（{rs['why']}）⇒ 该频点作废")
                            got.pop(f, None)
                    else:
                        print(f"    mode{mode} {f:4.1f} Hz: 作废（{an['why']}）"
                              f"—— {dens}")
                usable, notes = check_monotonic(freqs, got)
                if notes:
                    print("\n".join(notes))
                    print(f"    ⇒ mode{mode} 只保留 {usable}")
                res[mode] = {f: got[f] for f in usable}
            # 收尾：模式恢复成进来时的，速度恢复成进来时的 —— 但进来时若读到 0
            # （= 停转），恢复 0 会把舵机冻住，下一次探针就以为舵机坏了。0 不是
            # 合法的工作值，改写成部署值。
            bus.write_u8(sid, REG_MODE, mode0)
            time.sleep(0.25)
            c = bus.read_u16(sid, ident.REG_POS)
            if c is not None:
                bus.write_u16(sid, ident.REG_GOAL, c)
            bus.write_u16(sid, ident.REG_SPEED, spd0 or RUNNING_SPEED)
            print(f"\n  收尾 mode={bus.read_u8(sid, REG_MODE)} reg46={spd0}")
            print()
            print("  判决: " + verdict(res.get(mode0, {}), res.get(0, {})))
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
