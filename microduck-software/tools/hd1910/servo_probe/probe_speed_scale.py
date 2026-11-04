#!/usr/bin/env python3
"""标定速度寄存器的单位（counts → rad/s），判 0.229 还是 0.732。

为什么值得单独跑一趟
--------------------
部署链 `duck-control/src/bus.rs:40 RAD_PER_SEC_PER_COUNT = 0.229`（单位 rev/min per
count，出自 XL330）。HD-1910 是飞特 STS 系，官方内存表的速度单位是 **0.732 rpm/count**，
两者差 **3.2×**。若 robotd 沿用 0.229，obs 61 维里的 **15 维 joint_vel 会静默错 3.2 倍**
—— 不报错、不崩溃，只是策略看到的角速度比真实值小 3.2 倍（或反之）。

原理：不用相信任何速度标度
--------------------------
同一时刻读两件事：

  ① 位置 `reg56`（2B，0–4095，`STEPS_PER_REV = 4096` counts/rev）
  ② 速度 `reg58`（2B，signed-magnitude）

位置的时间差商 `dpos/dt` 只依赖 **位置分辨率**，与速度单位无关 ⇒ 它是独立基准。

  ratio = (counts/s) / reg58

  若速度单位 u（rpm/count），则 counts/s = u·S/60·4096 ⇒ ratio = u·4096/60
    u = 0.732  ⇒ ratio = 49.97
    u = 0.229  ⇒ ratio = 15.63

两者差 3.2×，噪声再大也分得开。且 ratio 与 u 的乘积关系让「官方 u」与「实测 ratio」
在 4096 处闭合 —— 若实测落在 49.97±3%，则三方（实测比值、官方 0.732、4096/rev）一致。

怎么让它在 mode 4 下匀速走（不切 mode）
---------------------------------------
切 mode 会让固件从 EEPROM 重载配置（写保护那轮踩过），**这里绝不切**。mode 4 下
写 `reg46`（目标速度）是在给"趋向 goal"限速：把 goal 推一段距离、reg46 设成中等值，
舵机就以受控速度匀速走过去，途中 reg58 是真实的瞬时速度。

⚠️ 台架 4.6 V ⇒ 空载约 69 RPM（部署 7.4 V 是 113 RPM）。所以 reg46 别设大，
   否则撞速度饱和，ratio 会被低估。默认 40（≈29 RPM），走 1500 counts ≈ 0.37 rev ≈ 0.8 s。

用法
    python probe_speed_scale.py --port COM3 --ids 10            # 实测
    python probe_speed_scale.py --selftest                      # 负对照，不碰硬件
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hd1910_ident as ident  # noqa: E402
from hd1910_readonly import signed_mag  # noqa: E402

REG_POS = 56
REG_SPEED_PRESENT = 58
TELEM_LEN = 15

RATIO_STS = 4096 * 0.732 / 60.0      # 49.97  —— 飞特 STS/HD-1910
RATIO_XL330 = 4096 * 0.229 / 60.0    # 15.63  —— 现部署常数的来处
TOLERANCE = 0.03


def ratio_verdict(ratio: float) -> str:
    """把实测比值翻译成「速度单位是多少」。"""
    if abs(ratio / RATIO_STS - 1) <= TOLERANCE:
        return f"STS 0.732 rpm/count（bus.rs 的 0.229 错 3.2×，必须改）"
    if abs(ratio / RATIO_XL330 - 1) <= TOLERANCE:
        return "XL330 0.229 rpm/count（与现部署常数一致）"
    return "两个都不符 —— 不猜，先查是不是没走到匀速段"


def analyse(trace: list[tuple[float, int, int]], *, min_speed: int = 5):
    """trace: [(t, pos, speed)] → (counts_per_s, speed_median, ratio) 或 None。

    只取**中间一半**样本：两端是加减速段，那里位置差分与速度环不同步。
    """
    pts = [(t, p, s) for t, p, s in trace if abs(s) >= min_speed]
    if len(pts) < 20:
        return None
    q = len(pts) // 4
    mid = pts[q:len(pts) - q]
    spd = st.median([s for _, _, s in mid])
    if not spd:
        return None
    v = []
    for (t0, p0, _), (t1, p1, _) in zip(mid, mid[1:]):
        d = p1 - p0
        if d > 2048:                    # 单圈 4096，半步 2048 判回绕
            d -= 4096
        elif d < -2048:
            d += 4096
        dt = t1 - t0
        if dt > 0:
            v.append(d / dt)
    if not v:
        return None
    vel = st.median(v)
    return vel, spd, vel / spd


def _read_telem(bus, sid: int):
    buf = bus.read(sid, REG_POS, TELEM_LEN)
    if not buf or len(buf) < 4:
        return None
    pos = buf[0] | (buf[1] << 8)
    spd = signed_mag(buf[2], buf[3])
    return pos, spd


def measure(bus, sid: int, *, reg46: int, span: int, seconds: float,
            sign: int = -1, period: float = 0.01) -> dict:
    """推一段 goal，途中采 (t, pos, speed)，再还原现场。"""
    pos0 = bus.read_u16(sid, ident.REG_POS)
    if pos0 is None:
        return {"ok": False, "why": "读不到位置"}
    old_speed = bus.read_u16(sid, ident.REG_SPEED)
    old_limit = bus.read_u16(sid, ident.REG_TORQUE_LIMIT)

    target = pos0 + sign * span
    if not 0 <= target <= 4095:
        return {"ok": False, "why": f"位置 {pos0} 加 {sign * span} 出界"}

    trace: list[tuple[float, int, int]] = []
    try:
        bus.write_u16(sid, ident.REG_TORQUE_LIMIT, 1000)   # 先放满扭矩限
        time.sleep(0.05)
        bus.write_u16(sid, ident.REG_SPEED, reg46)         # 再限速
        time.sleep(0.05)
        bus.write_u16(sid, ident.REG_GOAL, target)         # 最后才动
        t0 = time.perf_counter()
        while (el := time.perf_counter() - t0) < seconds:
            r = _read_telem(bus, sid)
            if r:
                trace.append((el, r[0], r[1]))
            time.sleep(period)
    finally:
        cur = bus.read_u16(sid, ident.REG_POS) or pos0
        bus.write_u16(sid, ident.REG_GOAL, cur)            # 停：goal=当前位置
        time.sleep(0.05)
        if old_speed is not None:
            bus.write_u16(sid, ident.REG_SPEED, old_speed)
        if old_limit is not None:
            bus.write_u16(sid, ident.REG_TORQUE_LIMIT, old_limit)

    end = trace[-1][1] if trace else pos0
    hit_limit = abs(end - target) > 50
    return {"ok": True, "trace": trace, "pos0": pos0, "target": target,
            "moved": end - pos0, "hit_limit": hit_limit, "end": end}


def selftest() -> int:
    """合成轨迹，答案已知；负对照必须能把 0.229 和 0.732 分开。"""
    # 每步位移要明显大于 1 count：位置是整数，量化的 ±0.5 count 若占每步位移的
    # 几个百分点，就会把 15.63 判成 15.0（第一版自检正是这么红的）。
    # 实测时 reg46=40 每步约 40 counts，量化误差 1.3%，在 3% 容差内。
    def synth(ratio: float, S: int = 400, n: int = 60):
        tr, p = [], 1000.0
        for i in range(n):
            ramp = min(1.0, i / 8.0, (n - 1 - i) / 8.0)   # 两端减速，模拟加减速段
            s = S * ramp
            tr.append((i * 0.02, int(p), int(round(s))))
            p += ratio * s * 0.02
        return tr

    cases = [
        ("STS 标度 (ratio 49.97)", RATIO_STS),
        ("XL330 标度 (ratio 15.63)", RATIO_XL330),
        ("乱值 30 → 必须判不出", 30.0),
        ("超容差 49.97×1.2 → 必须判不出", RATIO_STS * 1.2),
    ]
    bad = 0
    for name, ratio in cases:
        got = analyse(synth(ratio))
        if got is None:
            print(f"  [FAIL] {name}  analyse 返回 None")
            bad += 1
            continue
        v = ratio_verdict(got[2])
        if ratio in (RATIO_STS, RATIO_XL330):
            ok = abs(got[2] / ratio - 1) <= TOLERANCE
        else:
            ok = v.startswith("两个都不符")
        bad += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ratio={got[2]:.2f}  → {v.split('（')[0]}")

    # 负对照：判据必须对两种标度给出**不同**结论（否则它只是"永远说 STS"）
    neg_ok = (ratio_verdict(RATIO_STS) != ratio_verdict(RATIO_XL330)
              and ratio_verdict(RATIO_STS).startswith("STS")
              and ratio_verdict(RATIO_XL330).startswith("XL330"))
    bad += 0 if neg_ok else 1
    print(f"  [{'PASS' if neg_ok else 'FAIL'}] 负对照：49.97 与 15.63 必须判成不同标度")

    print(f"  self-checks: {len(cases) + 1 - bad}/{len(cases) + 1} pass")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="10")
    ap.add_argument("--reg46", type=int, default=40, help="目标速度（限速值）")
    ap.add_argument("--span", type=int, default=1500, help="走多少 counts")
    ap.add_argument("--sign", type=int, default=-1, choices=(-1, 1),
                    help="往负/正方向走；默认负 —— 本台架正方向约 2800 处有机械限位")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    bus = ident.Bus(a.port)
    rc = 0
    try:
        for sid in ids:
            if not bus.ping(sid):
                print(f"  ID {sid}: 无应答")
                rc = 1
                continue
            mode = bus.read_u8(sid, ident.REG_MODE)
            volt = bus.read_u8(sid, 62)
            print(f"  ID {sid}: mode={mode}  电压={volt / 10 if volt else '?'} V  "
                  f"reg46={a.reg46}  span={a.span}")
            ratios = []
            limits = []
            for k in range(a.repeat):
                # 来回走：物理行程只有 ~1600 counts（本台架实测 1213..2816），
                # 单向重复第二次就顶到限位，运动段短到采不满匀速点。
                sg = a.sign if k % 2 == 0 else -a.sign
                r = measure(bus, sid, reg46=a.reg46, span=a.span,
                            seconds=a.seconds, sign=sg)
                if not r["ok"]:
                    print(f"    第 {k + 1} 次: 跳过 —— {r['why']}")
                    continue
                got = analyse(r["trace"])
                if got is None:
                    print(f"    第 {k + 1} 次: 没走到匀速（speed 恒 0 或运动点不足）"
                          f"，reg46 可能太小")
                    continue
                vel, spd, ratio = got
                ratios.append(ratio)
                warn = ""
                if r["hit_limit"]:
                    limits.append(r["end"])
                    warn = (f"  ⚠️ 堵在 {r['end']}（目标 {r['target']}）：撞机械限位，"
                            f"匀速段仍有效但这次 --span 太大")
                print(f"    第 {k + 1} 次: 位置 {vel:+7.1f} counts/s  "
                      f"reg58={spd:+5.0f}  ratio={ratio:6.2f}  "
                      f"位移 {r['moved']:+5d} counts{warn}")
                time.sleep(0.3)
            if ratios:
                med = st.median(ratios)
                spread = st.pstdev(ratios) / med if len(ratios) > 1 else 0.0
                print(f"    → ratio 中位 {med:.2f}（CV {spread:.1%}）："
                      f"{ratio_verdict(med)}")
                if limits:
                    print(f"    ⚠️ 观测到机械限位在 {sorted(set(limits))}；"
                          f"EEPROM 行程 reg9/reg11 = 0/4095 在物理上不起作用")
                if med and abs(med / RATIO_STS - 1) > TOLERANCE and \
                        abs(med / RATIO_XL330 - 1) > TOLERANCE:
                    rc = 2
            else:
                rc = 2
    finally:
        bus.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
