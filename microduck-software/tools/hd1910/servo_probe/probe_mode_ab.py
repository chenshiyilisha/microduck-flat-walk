#!/usr/bin/env python3
"""mode 0 vs mode 4 的阶跃响应 A/B —— kp8 平台结论在部署口径下还成立吗？

为什么要跑
----------
robotd 打开 Feetech 总线时**硬校验 `mode == 0`**（`feetech.rs:386` `check_registers()`，
不满足就 `IoError::Bus` 拒绝启动，且注释写明 checked, not corrected）。
而本台架从第一天起就是 **mode 4**（出厂默认，juxitech 记作「纯位置 PD / Sim2Real」）——
kp8 平台、duty%、双向最小可动步**全是在 mode 4 下取的**。

若 mode 0 与 mode 4 的跟踪特性不同，那些结论就不代表部署口径，得重取。

上游怎么让 mode 0 变成「纯位置跟踪」
------------------------------------
mode 0 是位置伺服，但它同时写两个 RAM 寄存器把它压成无规划：

  reg46 (GOAL_SPEED) = 250  →  250 × 0.732 rpm ≈ 183 rpm，远超这颗的 110 rpm 上限
                               ⇒ 实际不限速
  reg41 (ACCELERATION) = 0  →  0 是「最大加速度」⇒ 不做梯形规划

所以这个 A/B 也必须在**同样的 250 / 0 组合**下比较，否则比的是"限速 vs 不限速"，
不是 mode。两边都写 250/0。

用法
    python probe_mode_ab.py --port COM3 --ids 10              # 跑 A/B
    python probe_mode_ab.py --selftest                        # 不碰硬件

安全
----
只改 RAM（lock=1，EEPROM 不动），收尾把 mode / reg46 / reg41 全部写回原值。
mode 是 EEPROM 地址，锁着时写只影响 RAM，断电即恢复出厂的 4。
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

REG_MODE = 33
REG_ACCEL = 41
GOAL_SPEED_UNCAPPED = 250          # 上游的 RUNNING_SPEED


def _step(bus, sid: int, *, delta: int, speed: int, accel: int, lo: int = 0,
          hi: int = 4095, seconds: float = 1.5, period: float = 0.01):
    """从当前位置走 delta 步，返回 [(t, pos)]。"""
    pos0 = bus.read_u16(sid, ident.REG_POS)
    if pos0 is None:
        return None, None
    target = pos0 + delta
    if not lo <= target <= hi:
        return None, None
    bus.write_u16(sid, ident.REG_TORQUE_LIMIT, 1000)
    time.sleep(0.03)
    bus.write_u16(sid, ident.REG_SPEED, speed)
    time.sleep(0.03)
    bus.write_u8(sid, REG_ACCEL, accel)
    time.sleep(0.03)
    bus.write_u16(sid, ident.REG_GOAL, target)
    t0, tr = time.perf_counter(), []
    while (el := time.perf_counter() - t0) < seconds:
        p = bus.read_u16(sid, ident.REG_POS)
        if p is not None:
            tr.append((el, p))
        time.sleep(period)
    return (pos0, target), tr


def metrics(trace, *, delta: int):
    """10–90% 上升时间、超调、稳态误差、末段抖动（都用 counts，再换度）。

    位移不足半个阶跃 ⇒ 返回 None（这次根本没走：撞了机械限位）。不这样拦，
    静止轨迹会被算成「超调 = 整个阶跃」，看着像有数据，其实全是假的。
    """
    if not trace or len(trace) < 20:
        return None
    y0 = trace[0][1]
    moved = trace[-1][1] - y0
    if abs(moved) < abs(delta) * 0.5:
        return None
    sign = 1 if delta > 0 else -1
    target = y0 + delta

    def crossed(frac):
        # 阈值一律从起点按方向插值。原先写成先定 lo/hi 再按 sign 反解，负方向时
        # 10% 的阈值反而比 90% 还远 —— rise 恒为负，整个负方向样本被静默丢掉
        # （诊断打印暴露的：明明走了 199/200 步，却报「没采到轨迹」）。
        lvl = y0 + delta * frac
        for t, p in trace:
            if sign * (p - lvl) >= 0:
                return t
        return None

    t10, t90 = crossed(0.10), crossed(0.90)
    rise = (t90 - t10) if (t10 is not None and t90 is not None) else None
    if rise is None or rise <= 0:
        return None
    peak = max(p for _, p in trace) if sign > 0 else min(p for _, p in trace)
    overshoot = sign * (peak - target)          # counts, 正 = 冲过头
    tail = [p for _, p in trace[-15:]]
    ss_err = sign * (target - st.mean(tail))
    jitter = st.pstdev(tail)
    return {"rise_ms": None if rise is None else rise * 1e3,
            "overshoot_ct": overshoot, "ss_err_ct": ss_err, "jitter_ct": jitter,
            "overshoot_deg": overshoot * 360.0 / 4096,
            "ss_err_deg": ss_err * 360.0 / 4096,
            "jitter_deg": jitter * 360.0 / 4096}


def verdict(m4: list[dict], m0: list[dict], tol: float = 0.20,
            otol_ct: float = 20) -> str:
    """两模式的判决。缺任一侧就不判。tol 可调，只为自检能证明阈值真的在起作用。"""
    if not m4 or not m0:
        return "无法判决（有一侧没取到数据）"
    r4 = [m["rise_ms"] for m in m4 if m["rise_ms"]]
    r0 = [m["rise_ms"] for m in m0 if m["rise_ms"]]
    if not r4 or not r0:
        return "无法判决（没有一次走完 10–90%）"
    a, b = st.median(r4), st.median(r0)
    diff = (b - a) / a
    o4 = st.median([m["overshoot_ct"] for m in m4])
    o0 = st.median([m["overshoot_ct"] for m in m0])
    txt = (f"上升时间 mode4 {a:.1f} ms vs mode0 {b:.1f} ms（{(diff):+.1%}）；"
           f"超调 {o4 * 360 / 4096:+.2f}° vs {o0 * 360 / 4096:+.2f}°")
    if abs(diff) <= tol and abs(o0 - o4) <= otol_ct:
        return f"两模式等价（≤{tol:.0%}）⇒ kp8 结论可沿用\n  " + txt
    return ("**两模式不等价 ⇒ kp8 平台/duty%/最小可动步要在 mode 0 上重取**\n  " + txt)


def selftest() -> int:
    """合成两条轨迹，答案已知：mode 4 快、mode 0 慢一半，判决必须说得出来。"""
    def synth(rise_ms: float, overshoot_ct: int, n: int = 150, dt: float = 0.01,
              delta: int = 200):
        tr, y = [], 0.0
        for i in range(n):
            t = i * dt * 1000
            if t < 0:
                y = 0.0
            elif t < rise_ms:
                y = delta * (t / rise_ms)
            else:
                # 一阶趋近 + 一次性超调
                k = min(1.0, (t - rise_ms) / 150.0)
                y = delta + overshoot_ct * (k if k < 1 else 1) - overshoot_ct * 0.3 * k
            tr.append((i * dt, int(round(y))))
        return tr

    bad = 0
    fast = [metrics(synth(60, 6), delta=200) for _ in range(3)]
    slow = [metrics(synth(120, 6), delta=200) for _ in range(3)]
    s_fast = verdict(fast, fast)
    s_diff = verdict(fast, slow)
    ok1 = s_fast.startswith("两模式等价")
    ok2 = s_diff.startswith("**两模式不等价")
    for name, ok in (("同样轨迹 → 判等价", ok1), ("rise 60 vs 120 ms → 判不等价", ok2)):
        bad += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    # 负对照：把阈值放宽到 200%，同一对轨迹必须改判「等价」—— 证明上面那个绿是
    # 阈值算出来的，不是函数永远返回同一个字符串。
    loosened = verdict(fast, slow, tol=2.0, otol_ct=10**6)
    ok3 = loosened.startswith("两模式等价")
    bad += 0 if ok3 else 1
    print(f"  [{'PASS' if ok3 else 'FAIL'}] 负对照：阈值放宽到 200% → 必须改判等价")
    print(f"  self-checks: {3 - bad}/3 pass")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="10")
    ap.add_argument("--delta", type=int, default=200, help="阶跃步数（0.088°/步）")
    ap.add_argument("--lo", type=int, default=1213,
                    help="物理行程下限（实测；EEPROM 的 0/4095 不起作用）")
    ap.add_argument("--hi", type=int, default=2816, help="物理行程上限（实测）")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--accel", type=int, default=0,
                    help="reg41；0 上游当作最大加速度，但这颗固件未必")
    ap.add_argument("--speed", type=int, default=GOAL_SPEED_UNCAPPED,
                    help="reg46；用它做敏感性检查，证明差异不是限速造成的")
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
            mode0 = bus.read_u8(sid, REG_MODE)
            acc0 = bus.read_u8(sid, REG_ACCEL)
            spd0 = bus.read_u16(sid, ident.REG_SPEED)
            pos0 = bus.read_u16(sid, ident.REG_POS)
            print(f"  ID {sid}: 起始 mode={mode0} accel={acc0} reg46={spd0} pos={pos0}")
            # 双向都要有 a.delta 的余量，否则一头会撞限位（上一版就是这么得到
            # 三个样本里两个"完全没动"、超调恰好等于整个阶跃的）
            margin = a.delta + 80
            if pos0 is not None and not (a.lo + margin <= pos0 <= a.hi - margin):
                mid = (a.lo + a.hi) // 2
                print(f"  位置 {pos0} 离端点太近，先移到行程中点 {mid}")
                bus.write_u16(sid, ident.REG_SPEED, a.speed)
                time.sleep(0.05)
                bus.write_u16(sid, ident.REG_GOAL, mid)
                for _ in range(80):                 # 等它真到，别用固定 sleep 猜
                    time.sleep(0.1)
                    p = bus.read_u16(sid, ident.REG_POS)
                    if p is not None and abs(p - mid) < 30:
                        break
                pos0 = bus.read_u16(sid, ident.REG_POS)
                bus.write_u16(sid, ident.REG_GOAL, pos0 or mid)
                time.sleep(0.2)
                print(f"  就位 pos={pos0}")

            def run_block(label: str, mode: int):
                bus.write_u8(sid, REG_MODE, mode)
                time.sleep(0.25)
                got = bus.read_u8(sid, REG_MODE)
                if got != mode:
                    print(f"    {label}: 模式没切成 {mode}（读回 {got}），跳过")
                    return []
                out = []
                sign = -1
                for k in range(a.repeat):
                    cur = bus.read_u16(sid, ident.REG_POS)
                    if cur is None:
                        continue
                    step = a.delta * sign
                    if not a.lo <= cur + step <= a.hi:
                        sign = -sign
                        step = a.delta * sign
                        if not a.lo <= cur + step <= a.hi:
                            print(f"    {label} #{k + 1}: 位置 {cur} 两侧都走不开，跳过")
                            continue
                    span, tr = _step(bus, sid, delta=step, lo=a.lo, hi=a.hi,
                                     speed=a.speed, accel=a.accel)
                    m = metrics(tr, delta=step) if tr else None
                    if m:
                        out.append(m)
                        print(f"    {label} #{k + 1}: rise {m['rise_ms']:.1f} ms  "
                              f"超调 {m['overshoot_deg']:+.2f}°  "
                              f"稳态误差 {abs(m['ss_err_deg']):.2f}°  "
                              f"抖动 {m['jitter_deg']:.2f}°")
                    else:
                        if tr:
                            print(f"    {label} #{k + 1}: 无效 —— 起点 {tr[0][1]} "
                                  f"末点 {tr[-1][1]}（要 {step:+d}），"
                                  f"{len(tr)} 点，跨 "
                                  f"{(tr[-1][0] - tr[0][0]) * 1e3:.0f} ms")
                        else:
                            print(f"    {label} #{k + 1}: 没采到轨迹（目标出界？）")
                    # 停稳再反向：goal 钉住当前位置。0.9 s 是按 mode 0 最慢的那次
                    # （rise 436 ms）留的余量，0.35 s 会让反向阶跃从还在动的位置起算。
                    c2 = bus.read_u16(sid, ident.REG_POS)
                    if c2 is not None:
                        bus.write_u16(sid, ident.REG_GOAL, c2)
                    time.sleep(0.9)
                    sign = -sign
                return out

            print(f"  -- mode {mode0}（台架原口径）--")
            m_orig = run_block(f"mode{mode0}", mode0)
            print(f"  -- mode 0（robotd 要求的口径，reg46={GOAL_SPEED_UNCAPPED} reg41=0）--")
            m_m0 = run_block("mode0", 0)

            # 收尾：模式先改回、再恢复 RAM 寄存器
            bus.write_u8(sid, REG_MODE, mode0)
            time.sleep(0.25)
            back = bus.read_u8(sid, REG_MODE)
            c = bus.read_u16(sid, ident.REG_POS)
            if c is not None:
                bus.write_u16(sid, ident.REG_GOAL, c)
            time.sleep(0.05)
            bus.write_u16(sid, ident.REG_SPEED, spd0 or 0)
            bus.write_u8(sid, REG_ACCEL, acc0 or 0)
            print(f"  收尾: mode 回 {back}，reg46={bus.read_u16(sid, ident.REG_SPEED)} "
                  f"reg41={bus.read_u8(sid, REG_ACCEL)}")

            print()
            if mode0 == 0:
                print("  ⚠️ 起始就是 mode 0，这次没法做 A/B（只记录了一侧）")
                rc = 2
            else:
                print("  判决: " + verdict(m_orig, m_m0))
    finally:
        bus.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
