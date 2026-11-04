#!/usr/bin/env python3
"""训练用的 BAM 执行器，对同一条正弦的 gain/lag 是多少？

为什么必须问这一句
------------------
台架实测（`probe_bandwidth.py`，P=8 = 部署增益、mode 0、4.6 V）给出 2 Hz 时
gain **0.35**、滞后 **90°**。这可以有两种完全不同的解释：

  (a) 训练 plant 没建模这个衰减 ⇒ 策略学的动作在真机上打不出来（sim2real 缺口）；
  (b) 训练 plant **本来就这样** ⇒ 策略早就知道关节跟不上，不是缺口。

两者对"要不要重训 / 要不要改 kp"的结论相反，所以不能靠"应该差不多吧"。

所以这里把**同一套** BAM 执行器方程（`check_step_vs_sim.py` 用的那套，不重写）
放在与台架相同的边界条件下 —— 空载 `FreeShaft`、同样的 vin、同样的 kp ——
喂 50 Hz 更新的正弦目标，物理步 5 ms，用**同一个** `analyze()` 拟合位置。

用法
    python sim_bandwidth.py                 # kp=8、vin=4.6（台架现状）
    python sim_bandwidth.py --kp 5 --vin 7.4
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import probe_bandwidth as pb  # noqa: E402  同一个拟合与判据，不另写一份

ROOT = HERE.parents[2]
STEPS_PER_RAD = 4096 / (2 * math.pi)
CTRL_S = 0.02                  # robotd / 训练命令周期
PHYS_S = 0.005                 # timestep
DECIM = int(round(CTRL_S / PHYS_S))


class FreeShaft:
    """台架：舵机躺在桌上、输出轴空载。与 check_step_vs_sim.py 的同名类一致。"""

    def compute_mass(self, q, dq):
        return 0.0

    def compute_bias(self, q, dq):
        return 0.0


def load_plant(json_path: Path, kp: float, vin: float, smooth: bool):
    sys.path.insert(0, str(ROOT / "tools"))
    import bam_actuators  # noqa: F401  registers repo-local actuator names
    from bam.model import load_model

    model = load_model(str(json_path))
    act = model.actuator
    if vin > 0:                 # vin<=0 表示"用 json 自带的值"（= 训练时的条件）
        act.vin = vin
    act.kp = kp
    act.testbench_class = FreeShaft
    act.testbench = FreeShaft()
    if not smooth and hasattr(act, "q_target_smooth"):
        # ⚠️ 必须 del，不能赋 None（安装版用 hasattr 判断要不要重新播种）
        del act.q_target_smooth
    model.actuator = act
    return model, act


def sine_run(model, act, *, freq: float, amp_steps: int, cycles: int,
             delay_s: float, center_steps: float,
             settle_s: float = 2.0) -> list[tuple[float, int, int]]:
    """50 Hz 更新目标、5 ms 物理步，返回 [(t, cmd_steps, pos_steps)]，t 从正弦起点算。

    ⚠️ `settle_s` 不是礼貌，是正确性。`sim.reset` 把 q 放在 0，而命令中心是 2014 步
    （=177°），所以正弦一开始就叠了一个 3.09 rad 的阶跃 —— 闭环在 ~2 Hz 上振铃。
    2026-11-04 实测：4 Hz 只跑 1.0 s 时，"最后 2 个周期"整个落在振铃里，pos 峰峰
    读到 941 步（命令才 300），而先站 2 s 再扫就只有 92 步。读出来像"自己振起来"，
    其实是初始阶跃没衰减。`steady()` 用来在分析前拦住这类窗口。
    """
    from bam.simulate import Simulator

    sim = Simulator(model)
    sim.reset(0.0, 0.0)
    if hasattr(act, "q_target_smooth"):
        del act.q_target_smooth

    # ⚠️ hist 的步长是控制周期（20 ms）而不是物理步（5 ms）。第一版写成
    # round(delay_s/PHYS_S)=4 再取 hist[-5]，实际读到的是 4 个控制周期前 = 80 ms，
    # 于是相位滞后凭空多出 60 ms（0.5→4 Hz 斜率 130 ms vs 台架 58 ms，2026-11-04 逮到）。
    delay_n = max(0, int(round(delay_s / CTRL_S)))
    hist: list[float] = [0.0] * max(1, delay_n)
    w = 2.0 * math.pi * freq

    def tick(qt: float) -> float:
        hist.append(qt)
        cmd_qt = hist[-delay_n - 1] if delay_n else qt
        for _ in range(DECIM):
            # numpy 标量：安装版用 shape 判断是否重播种，Python float 会每步重播
            volt = act.compute_control(np.float64(cmd_qt), sim.q, sim.dq, PHYS_S)
            sim.step(volt, True, PHYS_S)
        return sim.q * STEPS_PER_RAD

    for _ in range(max(1, int(round(settle_s / CTRL_S)))):      # 阶段 A：站到中心
        tick(center_steps / STEPS_PER_RAD)

    rec = []
    for k in range(int(round(cycles / freq / CTRL_S))):          # 阶段 B：正弦
        t = k * CTRL_S
        cmd = center_steps + amp_steps * math.sin(w * t)
        rec.append((t, int(round(cmd)), tick(cmd / STEPS_PER_RAD)))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "tools/bam_params/hd1910/official_m6_stslaw.json"))
    ap.add_argument("--kp", type=float, default=8.0, help="部署值 reg50 / kp_fw = 8")
    ap.add_argument("--vin", type=float, default=4.6, help="台架实测电压；<=0 表示不覆盖，用 json 自带的（=训练条件）")
    ap.add_argument("--amp", type=int, default=150, help="振幅（步），与台架同 150 步")
    ap.add_argument("--center", type=float, default=2014.0)
    ap.add_argument("--freqs", default="0.5,1,2,3,4")
    ap.add_argument("--delay-ms", type=float, default=20.0,
                    help="命令延迟；训练是 15–30 ms（delay 3–6 物理步）")
    ap.add_argument("--keep-smooth", action="store_true",
                    help="保留 q_target_smooth（默认删掉，与 check_step_vs_sim 一致）")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="扫频前先站在中心的时长（s）；0 会带回初始阶跃的振铃")
    ap.add_argument("--cycles", type=int, default=3)
    a = ap.parse_args()

    model, act = load_plant(Path(a.json), a.kp, a.vin, a.keep_smooth)
    print(f"json {Path(a.json).name}  kp {a.kp}  vin {a.vin} V  amp {a.amp} 步"
          f"（{a.amp * 360 / 4096:.1f}°）  延迟 {a.delay_ms:.0f} ms  先站 {a.settle:.1f} s")
    got = {}
    for f in [float(x) for x in a.freqs.split(",") if x.strip()]:
        rec = sine_run(model, act, freq=f, amp_steps=a.amp, cycles=a.cycles,
                       delay_s=a.delay_ms / 1000.0, center_steps=a.center,
                       settle_s=a.settle)
        an = pb.analyze(rec, f)
        st, pps = pb.steady(rec, f)
        tail = " ".join(f"{p:.0f}" for p in pps)
        if not an["ok"]:
            print(f"  {f:4.1f} Hz: 作废（{an['why']}）")
        elif not st:
            # 不收敛 ⇒ 分析窗里装的是瞬态，gain 不可引用
            print(f"  {f:4.1f} Hz: 作废（逐周期峰峰未收敛：{tail}）"
                  f"  gain {an['gain']:.3f} 仅打印")
        else:
            got[f] = an["gain"]
            vp = an["gain"] * 2 * math.pi * f * a.amp * 360 / 4096
            print(f"  {f:4.1f} Hz: gain {an['gain']:.3f}  lag {an['lag']:+.1f}°  "
                  f"峰值角速度 {vp:5.0f} °/s  （pos 峰峰 {an['p2p']:.0f} 步 / 振幅 "
                  f"{an['amp_pos']:.0f}；逐周期 {tail}）")

    is1f, vs, fc = pb.one_over_f(got, a.amp * 360 / 4096)
    if is1f:
        print(f"  ⇒ 已进入 1/f 段，等效拐点 ~{fc:.2f} Hz"
              f"（注意：一阶滚降与速度饱和在这里形状相同，"
              f"要区分得扫 kp 或扫电压）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
