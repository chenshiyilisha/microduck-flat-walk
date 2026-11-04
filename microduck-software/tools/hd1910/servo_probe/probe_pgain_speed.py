#!/usr/bin/env python3
"""mode 0 的"半速"是增益不够（可调 P 救回来），还是这个模式的硬属性？

为什么问
--------
2026-11-04 台架：同一条 2 Hz / 13.2° 正弦，`gain·2πfA` 在 2 Hz 以上变平 ——
mode 4 封顶 ~103 °/s、mode 0 只有 ~57 °/s（= 55%）。而 103 °/s 正好等于规格书
空载 0.222 s/60° @12 V 按 4.6 V 折算的 103.6 °/s（STS3215 规格书），说明
**mode 4 能跑到额定速度，mode 0 只能跑到一半**。

这直接决定部署路径：
  (a) 半速是控制增益不足 ⇒ 提高 reg50 就能救，不必改 fork 去用 mode 4；
  (b) 半速是 mode 0 的硬属性 ⇒ 只能改 fork 允许 mode 4（或重训）。

做法
----
钉住 2 Hz / 13.2°（已确认处于饱和段），扫 P = 8/12/16/24/32，看 v_peak 会不会
跟着涨。回读 reg50 确认 P 真的生效。

⚠️ P 必须由 `pb.measure(p_gain=...)` 写：它在**切 mode 之后**才写 P。自己先写
P 再调 measure 会被 measure 里的切 mode 冲掉（切 mode 从 EEPROM 重载配置）。

用法
    python probe_pgain_speed.py --port COM3 --ids 10
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

FREQ = 2.0
AMP = 150                                  # 13.2°
CENTER = 2014                              # 物理行程 [1213, 2816] 的中点
P_LIST = (8, 12, 16, 24, 32)


def one(bus, sid: int, *, mode: int, p_gain: int, speed: int) -> dict:
    """跑一条 2 Hz 正弦。P 交给 measure 在切 mode 之后写。"""
    rec = pb.measure(bus, sid, mode=mode, freq=FREQ, amp=AMP, center=CENTER,
                     speed=speed, cycles=5, settle_s=1.2, p_gain=p_gain)
    p_back = bus.read_u8(sid, ident.REG_P_RAM)
    an = pb.analyze(rec, FREQ)
    st, pps = pb.steady(rec, FREQ)
    if not an["ok"]:
        return {"ok": False, "why": an["why"], "p_back": p_back}
    return {"ok": True, "gain": an["gain"], "lag": an["lag"], "p_back": p_back,
            "stable": st, "pps": pps,
            "v_peak": an["gain"] * 2 * math.pi * FREQ * AMP * 360 / 4096}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", default="10")
    ap.add_argument("--speed", type=int, default=250, help="reg46，部署值 250")
    ap.add_argument("--p-list", default=",".join(str(p) for p in P_LIST))
    a = ap.parse_args()

    ps = [int(x) for x in a.p_list.split(",") if x.strip()]
    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    bus = ident.Bus(a.port)
    try:
        for sid in ids:
            if not bus.ping(sid):
                print(f"  ID {sid}: 无应答")
                continue
            mode0 = bus.read_u8(sid, pb.REG_MODE)
            p0 = bus.read_u8(sid, ident.REG_P_RAM)
            spd0 = bus.read_u16(sid, ident.REG_SPEED)
            print(f"  ID {sid}: 起始 mode={mode0} P={p0} reg46={spd0}；"
                  f"钉住 {FREQ:g} Hz / {AMP * 360 / 4096:.1f}°")
            print(f"{'mode':>5} {'P':>4} {'回读':>4} | {'gain':>6} {'v_peak':>8} "
                  f"{'lag':>7} {'稳态':>4} | 逐周期 p2p")

            rows = []
            plan = [(0, p) for p in ps]
            if mode0 != 0:
                plan.append((mode0, ps[0]))       # 参照：mode 4 在同一个 P 上
            for mode, p in plan:
                r = one(bus, sid, mode=mode, p_gain=p, speed=a.speed)
                if not r["ok"]:
                    print(f"{mode:>5} {p:>4} {r['p_back']:>4} | 作废（{r['why']}）")
                    continue
                rows.append((mode, p, r))
                tail = " ".join(f"{x:.0f}" for x in r["pps"])
                print(f"{mode:>5} {p:>4} {r['p_back']:>4} | {r['gain']:>6.3f} "
                      f"{r['v_peak']:>7.0f}° {r['lag']:>+6.1f}° "
                      f"{'是' if r['stable'] else '否':>4} | {tail}")

            # 判决用"涨了多少"这个与 P 无关的比值，不用绝对阈值
            m0 = [r for m, _, r in rows if m == 0 and r["stable"]]
            m4 = [r for m, _, r in rows if m != 0]
            if len(m0) < 2:
                print("  （mode0 可用点不足 2 个，无法判）")
            else:
                lo, hi = m0[0]["v_peak"], max(r["v_peak"] for r in m0)
                print(f"\n  mode0: P={m0[0]['p_back']} 时 {lo:.0f} °/s → "
                      f"P 最高 {hi:.0f} °/s（{100 * (hi / lo - 1):+.0f}%）")
                if m4:
                    print(f"  mode{mode0}: {m4[0]['v_peak']:.0f} °/s "
                          f"（mode0 最好 / mode{mode0} = "
                          f"{hi / m4[0]['v_peak']:.2f}）")
                print("  判决: " + ("P 能把大半速度找回来 ⇒ mode 0 可用，"
                                    "但要看电流余量（duty%≈5.1·kp）"
                                    if hi >= 1.3 * lo else
                                    "P 基本救不回来 ⇒ mode 0 的硬属性："
                                    "要么改 fork 允许 mode 4，要么在 mode 0 上重训"))

            # 收尾：P 与 mode 恢复
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
