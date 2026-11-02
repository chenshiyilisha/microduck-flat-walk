# SPDX-License-Identifier: Apache-2.0
"""Compare a real bench step response against the BAM plant used for training.

Why this exists
---------------
The P3 plant (``official_m6_stslaw.json``, kp_fw=5) carries nine parameters taken
from a factory identification at 7.4 V.  Not one of them had ever been checked
against *this* batch of servos.  A step response is the cheapest test that
constrains six of them at once (kt, R, armature, friction_base, friction_viscous,
command_delay): it is a closed-loop transient, so errors show up amplified in the
overshoot and the settling time rather than buried in a DC reading.

Design rules
------------
* **The actuator equations are not rewritten.**  Control law, torque equation and
  the friction budget all come from ``bam`` itself — this file only supplies the
  one-DOF integrator that MuJoCo would otherwise provide, via
  ``bam.simulate.Simulator``.
* **One metric implementation.**  ``step_metrics`` is imported from
  ``hd1910_ident`` so the bench numbers and the sim numbers cannot drift apart.
* **A band, not a point.**  The plant is integrated at two timesteps because BAM
  was fitted on 50 Hz logs while the firmware runs far faster.  If the bench lands
  inside the band spanned by both, the shape is right; reporting a single number
  would be fake precision.

Usage::

    .venv-mjlab/Scripts/python.exe tools/hd1910/check_step_vs_sim.py \\
        --csv hd1910_step_id10_kp5_kd0-1.csv --kp 5

Exit code 0 always: this is a measuring instrument, not a gate.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STEPS_PER_RAD = 4096 / (2 * np.pi)


class FreeShaft:
    """Bench testbench: servo lying on the desk, output shaft free.

    No gravity, no arm, no load — exactly the台架 condition.  BAM's own
    ``Pendulum`` would add a gravity bias the bench does not have, and the base
    ``Testbench`` raises NotImplementedError, so this trivial stand-in is the
    honest description of the rig.
    """

    def compute_mass(self, q, dq):
        return 0.0

    def compute_bias(self, q, dq):
        return 0.0


def load_plant(json_path: Path, kp: float, vin: float):
    sys.path.insert(0, str(ROOT / "tools"))
    import bam_actuators  # noqa: F401  registers repo-local actuator names
    from bam.model import load_model

    model = load_model(str(json_path))
    act = model.actuator

    # Match the bench boundary conditions rather than the datasheet ones:
    # - vin: whatever the bench supply actually delivered during the run
    # - kp : the RAM gain the bench was commanded to
    act.vin = vin
    act.kp = kp
    act.testbench_class = FreeShaft
    act.testbench = FreeShaft()
    model.actuator = act
    return model, act


def simulate(model, act, kp, steps: int, vin: float, dt: float,
             pre_s: float, hold_s: float, delay_s: float, sample_hz: float):
    """One step up, integrated at dt, sampled at sample_hz for the metrics."""
    from bam.simulate import Simulator

    sim = Simulator(model)
    sim.reset(0.0, 0.0)
    # ⚠️ 必须 del，不能赋 None：安装版用 hasattr 判断是否需要重新播种，
    #    显式设成 None 会让它跳过播种，随后 None - float 直接崩。
    if hasattr(act, "q_target_smooth"):
        del act.q_target_smooth

    q_target = steps / STEPS_PER_RAD
    # Command pipeline: firmware delay shifts the target in time.
    n_pre = int(round(pre_s / dt))
    n_hold = int(round(hold_s / dt))
    delay_n = int(round(delay_s / dt))
    hist = [0.0] * max(1, delay_n)

    rows, t, i = [], 0.0, 0
    total = n_pre + n_hold
    while i < total:
        qt = q_target if i >= n_pre else 0.0
        hist.append(qt)
        cmd_qt = hist[-max(1, delay_n) - 1] if delay_n else qt
        # ⚠️ 必须传 numpy 标量：安装版用 `shape` 比较决定是否重新播种，
        #    Python float 的 shape 是 None、播种出来的是 ()，永不相等 ⇒
        #    每一步都被判"形状变了"而重播种，内部目标永远停在第一格。
        volt = act.compute_control(np.float64(cmd_qt), sim.q, sim.dq, dt)
        sim.step(volt, True, dt)
        if i >= n_pre and (i - n_pre) % max(1, int(round(1.0 / (sample_hz * dt)))) == 0:
            t_ms = int((i - n_pre) * dt * 1000)
            rows.append(("up", t_ms, float(steps), sim.q * STEPS_PER_RAD,
                         0.0, 0.0, 0.0))
        i += 1
    return rows


def rise_time_ms(rows, phase: str = "up"):
    """10%→90% 上升时间，按**各自实际终值**算跨度。

    为什么不用"整定到目标±5 步"：纯 P 控制带库仑摩擦必然留静态误差，
    仿真的静态误差 17 步 > 容差 5 步时永远"整定不了"，指标退化成 n/a。
    用终值算跨度，上升时间就与静态偏移解耦，两边可比。
    """
    pts = [r for r in rows if r[0] == phase]
    if len(pts) < 10:
        return None
    p0 = pts[0][3]
    final = sum(p[3] for p in pts[-10:]) / 10
    span = final - p0
    if abs(span) < 10:
        return None
    t10 = t90 = None
    for _, t_ms, _, p, _, _, _ in pts:
        frac = (p - p0) / span
        if t10 is None and frac >= 0.1:
            t10 = t_ms
        if t90 is None and frac >= 0.9:
            t90 = t_ms
            break
    if t10 is None or t90 is None:
        return None
    return float(t90 - t10)


def sensitivity(json_path: Path, kp: float, steps: int, vin: float, dt: float,
                pre_s: float, hold_s: float, delay_s: float, sample_hz: float,
                factors=(-0.2, +0.2)):
    """故意把每个参数改坏 ±20%，看上升时间/静态误差动多少。

    没有这一张表，上面那些 PASS 只是"没看见红"，不代表这套测试能看见错。
    动得越少 ⇒ 该参数在这个工作点上不可辨识，别指望靠这条曲线去验它。
    """
    def measure(model, act):
        rows = simulate(model, act, kp, steps, vin, dt, pre_s, hold_s,
                        delay_s, sample_hz)
        return {"rise": rise_time_ms(rows),
                "err": abs(sum(r[3] for r in rows[-10:]) / 10 - steps)}

    m0 = measure(*load_plant(json_path, kp, vin))
    out = []
    for name in ("kt", "R", "armature", "friction_base", "friction_viscous"):
        row = {"param": name}
        for f in factors:
            model, act = load_plant(json_path, kp, vin)
            param = getattr(model, name, None)
            if param is None:
                row[f] = None
                continue
            param.value = param.value * (1 + f)
            row[f] = measure(model, act)
        out.append(row)
    return out, m0


def bench_rows(csv_path: Path, phase: str = "up"):
    out = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            if r["phase"] != phase or r["pos"] == "":
                continue
            out.append((r["phase"], int(r["t_ms"]), float(r["target"]),
                        float(r["pos"]), 0.0, 0.0, 0.0))
    return out


def fmt(m, key, unit=""):
    if m is None or m.get(key) is None:
        return "n/a"
    v = m[key]
    return f"{v:.1f}{unit}" if isinstance(v, float) else f"{v}{unit}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="台架 step 录制的 CSV")
    ap.add_argument("--json", default=str(ROOT / "tools/bam_params/hd1910/official_m6_stslaw.json"))
    ap.add_argument("--kp", type=float, default=5.0, help="台架那次用的 RAM P 值")
    ap.add_argument("--steps", type=int, default=None, help="阶跃幅度；默认从 CSV 读")
    ap.add_argument("--vin", type=float, default=None, help="供电电压；默认取 CSV 中位数")
    ap.add_argument("--sample-hz", type=float, default=50.0)
    ap.add_argument("--pre", type=float, default=1.0)
    ap.add_argument("--hold", type=float, default=2.0)
    ap.add_argument("--sensitivity", action="store_true",
                    help="负对照：各参数改坏 ±20%，看上升时间/静态误差动多少")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "tools/hd1910/servo_probe"))
    from hd1910_ident import DEAD_ZONE_GUARD, step_metrics

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        for cand in (Path.cwd() / csv_path,
                     ROOT / "out" / "steps" / csv_path,
                     ROOT / csv_path):
            if cand.exists():
                csv_path = cand
                break
    brows = bench_rows(csv_path)
    if len(brows) < 20:
        sys.exit(f"{csv_path}: up 相样本太少（{len(brows)}）")
    b_target = brows[0][2]
    steps = args.steps or int(round(b_target - brows[0][3]))

    volts = [float(r["volt"]) for r in csv.DictReader(open(csv_path))
             if r["phase"] == "up" and r["volt"]]
    vin = args.vin if args.vin is not None else float(np.median(volts))

    tol = DEAD_ZONE_GUARD + 2
    m_bench = step_metrics(brows, "up", b_target, tol)

    model, act = load_plant(Path(args.json), args.kp, vin)
    # command_delay 不在 model 上：mjlab 里延迟是 env 级（按控制步 delay 3-6），
    # params JSON 也没有这个键 ⇒ 只能记 0 并明说，不能假装有值。
    import json as _json
    delay = float(_json.loads(Path(args.json).read_text(encoding="utf-8"))
                  .get("command_delay") or 0.0)

    m_sim, r_sim = {}, {}
    for name, dt in (("fast", 0.001), ("log", 1.0 / args.sample_hz)):
        rows = simulate(model, act, args.kp, steps, vin, dt, args.pre, args.hold,
                        delay, args.sample_hz)
        r_sim[name] = rows
        m_sim[name] = step_metrics(rows, "up", float(steps), tol)

    print(f"台架 {csv_path.name}｜阶跃 {steps} 步｜P={args.kp:g} D=0｜vin={vin:.2f} V"
          f"（CSV 中位数）")
    print(f"plant {Path(args.json).name}｜law={type(act).__name__}｜"
          f"kt={model.kt.value:.4f} R={model.R.value:.3f} "
          f"armature={model.armature.value:.5f} delay={delay*1000:.2f} ms")
    print()
    hdr = f"{'指标':<10}{'台架':>12}{'sim@1ms':>12}{'sim@20ms':>12}   判据"
    print(hdr)
    print("-" * len(hdr) + "-" * 20)

    def row(label, key, unit, tol_abs, tol_pct=None):
        b = m_bench.get(key)
        s1 = (m_sim["fast"] or {}).get(key)
        s2 = (m_sim["log"] or {}).get(key)
        lo = min(x for x in (s1, s2) if x is not None) if (s1 is not None or s2 is not None) else None
        hi = max(x for x in (s1, s2) if x is not None) if (s1 is not None or s2 is not None) else None
        ok = None
        if b is not None and lo is not None:
            pad = tol_abs + (tol_pct or 0) * abs(b)
            # bool()：step_metrics 返回 numpy 标量，比较结果是 np.bool_，
            # `ok is False` 对它恒为 False ⇒ FAIL 会被误显示成"无法判"。
            ok = bool((lo - pad) <= b <= (hi + pad))
        mark = "✓ PASS" if ok else ("✗ FAIL" if ok is False else "— 无法判")
        print(f"{label:<10}{fmt(m_bench,key,unit):>12}{fmt(m_sim['fast'],key,unit):>12}"
              f"{fmt(m_sim['log'],key,unit):>12}   {mark}")
        return ok

    r0 = row("整定时间", "settle_ms", "ms", 60, 0.2)
    r2 = row("超调", "over_pct", "%", 5)
    r3 = row("稳态误差", "err", "步", 4)
    # 上升时间：与静态偏移解耦，是动态形状的主判据
    b_rise = rise_time_ms(brows)
    s1_rise = rise_time_ms(r_sim["fast"])
    s2_rise = rise_time_ms(r_sim["log"])
    if b_rise and s1_rise and s2_rise:
        lo, hi = min(s1_rise, s2_rise), max(s1_rise, s2_rise)
        pad = 60 + 0.2 * b_rise
        ok = (lo - pad) <= b_rise <= (hi + pad)
        r1 = ok
        print(f"{'上升时间':<10}{b_rise:>12.0f}{s1_rise:>12.0f}{s2_rise:>12.0f}"
              f"   {'✓ PASS' if ok else '✗ FAIL'}")
    else:
        r1 = None
        print(f"{'上升时间':<10}{'n/a':>12}{'n/a':>12}{'n/a':>12}   — 无法判")
    print()
    print("判据：整定 ±60ms 或 ±20%（仅供参考，见下）｜上升 ±60ms 或 ±20%｜"
          "超调 ±5 个百分点｜稳态误差 ±4 步")
    # 静态误差反推等效库仑摩擦：稳定点满足 kt·vin·duty/R = friction，
    # duty = Δq·kp·error_gain·ratio ⇒ friction = Δq·kp·eg·ratio·vin·kt/R。
    # 这一步把"误差差 6 倍"翻译成"摩擦差 6 倍"，参数级的可执行结论。
    g = (act.kp * act.error_gain * getattr(act.model, "error_gain_ratio").value
         * vin * act.model.kt.value / act.model.R.value)
    print()
    for label, m in (("台架", m_bench), ("sim@1ms", m_sim["fast"]),
                     ("sim@20ms", m_sim["log"])):
        e = (m or {}).get("err")
        if e is None:
            continue
        f = abs(e) / STEPS_PER_RAD * g
        print(f"  {label:<9}静态误差 {abs(e):5.1f} 步 ⇒ 等效库仑摩擦 "
              f"{f:.4f} Nm（{f * 10.197:.2f} kg·cm）")

    checks = (("上升", r1), ("超调", r2), ("稳态误差", r3))
    fails = [n for n, r in checks if r is False]
    unresolved = [n for n, r in checks if r is None]
    if fails:
        print(f"\n结论：{len(fails)} 项落在带外 → {', '.join(fails)}。"
              f"先看该项对哪个参数最敏感，再去补测那个参数，别一次性怀疑全部。")
    elif unresolved:
        print(f"\n结论：{'、'.join(unresolved)} 无法判（台架或仿真缺数），"
              f"这一步没有结论 —— 别把「判不了」当成「通过」。")
    else:
        print("\n结论：全部落在带内 —— P3 plant 的闭环动态在本工作点是对的，"
              "不需要为此重测 kt/R/armature/friction。")
    if r0 is None:
        print("注：整定时间对 sim 恒为 n/a —— 纯 P + 库仑摩擦必然留静态偏移，"
              "偏移 > ±5 步时按「整定到目标」判永远判不了。动态形状请看上升时间。")

    if args.sensitivity:
        table, m0 = sensitivity(Path(args.json), args.kp, steps, vin, 0.001,
                                args.pre, args.hold, delay, args.sample_hz)
        print(f"\n负对照（各参数改坏 ±20%，基准 上升 {m0['rise']:.0f}ms / "
              f"静态误差 {m0['err']:.1f} 步）：")
        print(f"{'参数':<17}{'-20%':>22}{'+20%':>22}   可辨识度")
        for row in table:
            cells = []
            for f in (-0.2, 0.2):
                m = row.get(f)
                if m is None or m["rise"] is None:
                    cells.append(f"{'n/a':>22}")
                else:
                    dr = 100 * (m["rise"] - m0["rise"]) / m0["rise"]
                    cells.append(f"上升{dr:+6.1f}% 误差{m['err']:5.1f}步".rjust(22))
            d = max(abs(100 * (row[f]["rise"] - m0["rise"]) / m0["rise"])
                    for f in (-0.2, 0.2)
                    if row.get(f) and row[f]["rise"])
            verdict = ("强" if d > 12 else "中" if d > 5 else "弱（这条曲线验不了它）")
            print(f"{row['param']:<17}{cells[0]}{cells[1]}   {verdict}")
        print("  ⇒ 「弱」的参数，靠 20% 参数误差在这条曲线上看不出来；"
              "别拿本表之外的 PASS 去声称它被验证过。")
    return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
