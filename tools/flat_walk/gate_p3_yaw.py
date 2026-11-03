"""P3 闸门（预注册）：用 N 次重复的 eval JSON 判「偏航修好了没有，并且没把走路弄坏」。

为什么单独一个脚本
------------------
`eval_velocity_in_sim.py` 里那 12 条 gates 是**单次 Run 的体检**（是否冻结命令、是否在动、
是否摔）。它们不能当 P3 的判决，因为：

  * `not_sideways` = `abs_dy_body_median <= 0.5 * |dx_body_mean|`，两个量都是**高 CV**：
    本次基线三次重复 dx_over_expected CV **25.5%**、absdy CV **19.6%**
    ⇒ 单次读数靠运气就能翻面。反直觉的是**该门的判据量在噪声里，而真正稳的量没进闸门**：
    `error_vel_yaw` 三次重复 CV 只有 **1.2%**（1.1831 / 1.2023 / 1.2113）。
  * 判决必须跨 seed，且判据量本身要可分辨。本仓纪律见
    `.workbuddy/memory/MEMORY.md`「判决双轴」「闸门只用低 CV 量」与
    `docs/active/microduck-HD1910软件方案.md` §8.3。

所以这里把 P3 的判据**先钉死、再开训**（预注册），阈值全部是写死的字面量：
基线值只能当"对照"，不能当"被测量"——即阈值的来源是**上一次的基线 ckpt**，
而判决对象是**重训后的 ckpt**，两者永远不是同一批 JSON。
`--audit-baseline` 只做一件事：核对写死的常量与基线文件仍然一致（防止有人改文件不改常量）。

基线（冻结，勿改）
------------------
  ckpt  `model_5999.pt`（HD1910 m5 / kp_fw 32），cmd vx=0.4 / vy=0 / wz=0，
        32 env × 8 s，solver 100/50，seed 11 / 22 / 33
  files `artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s{11,22,33}.json`
        sha256[:16] = 6bdb55ee591ad339 / 6fe61cf6e5a3bd3c / 3e84f1f7657b0e70

判据（双轴 + 不许退化轴）
------------------------
  G1 no_fall      每次 terminated_frac < 0.02               （安全）
  G2 vx 不退化     mean(vx) >= 0.97 * 0.30103 = 0.29200      （别把走路训坏）
  G3 偏航有反应    mean(error_vel_yaw) <= 0.90 * 1.19890     （"干预是否真的起作用"）
     目标（非判决）                         <= 0.50 * 1.19890 = 0.59945
  G4 xy 不退化     mean(error_vel_xy)  <= 1.05 * 0.19833 = 0.20825
  D1 直行诊断      只报数、不给判决（N=3 只能分辨 >=50% 的效应）

为什么 G3 用 `error_vel_yaw` 而不是净漂移
----------------------------------------
cmd 冻结 wz=0 时，`error_vel_yaw` 是**瞬时** |ω| 误差（实测 ≈1.2 rad/s），
而 `yaw_drift` 是**净**转角/时长（中位 14 deg/s ≈ 0.25 rad/s）。两者差 4.8×
不是矛盾：单次里 signed mean ω = 0.043 rad/s ≈ yaw_drift_signed 2.52 deg/s，
即净转角小、瞬时在**摆**（等效 ±17° @ 1 Hz 的步态偏航摇摆）。
摆是随机游走的源头（步态每步给一点航向噪声），且它是低 CV 可判的量；
净漂移是它的积分结果，噪声被放大 20 倍，只适合当诊断。

用法
----
  python tools/flat_walk/gate_p3_yaw.py out/p3/*.json
  python tools/flat_walk/gate_p3_yaw.py --audit-baseline
  python tools/flat_walk/gate_p3_yaw.py --selftest

退出码：0 全过 / 1 有闸门红 / 2 完整性过但重复数 <3（PROVISIONAL，不给判决）/ 3 完整性红
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics as st
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 冻结基线：来自上面三个 JSON，别从输入推。
# 算术写在旁边，是为了让人能拿计算器复核，而不是"相信脚本"。
# ---------------------------------------------------------------------------
BASE_VX = 0.301027  # mean(0.302725, 0.305979, 0.294377)
BASE_ERR_XY = 0.198333  # mean(0.196500, 0.196200, 0.202300)
BASE_ERR_YAW = 1.198900  # mean(1.183100, 1.202300, 1.211300)

# 每个量的三次重复离散度：决定"多大的差别才算看清了"。
BASE_SEM = {
    "vx_mean": 0.003468,
    "error_vel_xy": 0.002000,
    "error_vel_yaw": 0.008295,
    "abs_dy_body_median": 0.094800,
    "dx_over_expected": 0.026049,
    "yaw_drift_deg_s": 1.215400,
}
BASE_CV_PCT = {
    "vx_mean": 1.98,
    "error_vel_xy": 1.75,
    "error_vel_yaw": 1.20,
    "abs_dy_body_median": 19.58,
    "dx_over_expected": 25.53,
    "yaw_drift_deg_s": 14.91,
}
BASE_ABS_DY = 0.838367  # mean(0.652608, 0.898500, 0.964000)
BASE_FILES = {
    "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s11.json": "6bdb55ee591ad339",
    "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s22.json": "6fe61cf6e5a3bd3c",
    "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s33.json": "3e84f1f7657b0e70",
}

# 阈值：写死。左边是基线，右边是倍数，倍数是"要求"不是"实测"。
TH = {
    "g1_fall_max": 0.02,                      # terminated_frac 上限
    "g2_vx_min": 0.97 * BASE_VX,              # 0.29200
    "g3_yaw_gate_max": 0.90 * BASE_ERR_YAW,   # 1.07901  —— 效应存在（>=10%）
    "g3_yaw_goal_max": 0.50 * BASE_ERR_YAW,   # 0.59945  —— 目标（>=50%）
    "g4_xy_max": 1.05 * BASE_ERR_XY,          # 0.20825
    "d1_absdy_resolvable": 0.50 * BASE_ABS_DY,  # 0.41918 —— 只有 <=这个值才敢说改善
}
MIN_REPEATS = 3
FROZEN_CMD = {"vx": 0.4, "vy": 0.0, "wz": 0.0}


def _q(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def load(paths):
    runs = []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        runs.append({
            "path": str(p),
            "seed": d.get("seed"),
            "cmd": d.get("command"),
            "plant": _q(d, "plant"),
            "plant_fp": _q(d, "plant_fingerprint", default={}) or {},
            "vx": _q(d, "speed", "vx_mean"),
            "err_xy": _q(d, "official_metrics", "error_vel_xy"),
            "err_yaw": _q(d, "official_metrics", "error_vel_yaw"),
            "absdy": _q(d, "displacement", "abs_dy_body_median"),
            "dx_ratio": _q(d, "displacement", "dx_over_expected"),
            "yaw_drift": _q(d, "heading", "yaw_drift_deg_s"),
            "terminated": _q(d, "stability", "terminated_frac"),
            "upright_min": _q(d, "stability", "upright_min"),
            "gates": d.get("gates") or {},
        })
    return runs


def integrity(runs):
    """返回 (ok, 问题列表)。任何一条不过 ⇒ 后面所有数字都不可用。"""
    bad = []
    if len(runs) < 2:
        bad.append(f"runs={len(runs)} < 2：单次读数不能判（MJWarp 不可逐位复现）")
        return False, bad

    # plant：换了 plant 就是换了任务，跨 plant 不横比（§8.3 #2）
    fps = {(r["plant"], r["plant_fp"].get("json_sha256_12"), r["plant_fp"].get("kp_fw"))
           for r in runs}
    if len(fps) != 1:
        bad.append(f"plant 指纹不一致（跨 plant 不横比）：{sorted(fps, key=str)}")

    # 命令必须冻结且等于基线口径，否则 err_* 与基线不可比
    for r in runs:
        c = r["cmd"] or {}
        if any(abs(float(c.get(k, 1e9)) - v) > 1e-9 for k, v in FROZEN_CMD.items()):
            bad.append(f"{Path(r['path']).name}: command={c} 不是 {FROZEN_CMD}")
        if r["gates"].get("command_frozen_ok") is False:
            bad.append(f"{Path(r['path']).name}: command_frozen_ok=False（命令在跑的过程中变了）")
        if r["gates"].get("metric_window_ok") is False:
            bad.append(f"{Path(r['path']).name}: metric_window_ok=False"
                       f"（error_vel_* 不是真均值，乘比例系数才有意义）")
        if r["gates"].get("measurement_consistent") is False:
            bad.append(f"{Path(r['path']).name}: measurement_consistent=False"
                       f"（落地事件数对不上，读数本身有 bug）")
        for key in ("vx", "err_xy", "err_yaw", "terminated"):
            if r[key] is None:
                bad.append(f"{Path(r['path']).name}: 缺 {key}")
    return (not bad), bad


def stats(runs, key):
    xs = [r[key] for r in runs if r[key] is not None]
    n = len(xs)
    if n == 0:
        return None
    m = st.mean(xs)
    sd = st.stdev(xs) if n > 1 else None
    return {"n": n, "values": xs, "mean": m, "sd": sd,
            "sem": (sd / math.sqrt(n)) if sd is not None else None,
            "cv_pct": (100 * sd / abs(m)) if (sd is not None and m) else None}


def judge(runs):
    s_vx, s_xy, s_yaw = stats(runs, "vx"), stats(runs, "err_xy"), stats(runs, "err_yaw")
    s_dy, s_dx = stats(runs, "absdy"), stats(runs, "dx_ratio")
    falls = [r["terminated"] for r in runs if r["terminated"] is not None]

    gates = {
        "g1_no_fall": max(falls) < TH["g1_fall_max"] if falls else None,
        "g2_vx_not_worse": s_vx["mean"] >= TH["g2_vx_min"] if s_vx else None,
        "g3_yaw_responds": s_yaw["mean"] <= TH["g3_yaw_gate_max"] if s_yaw else None,
        "g4_xy_not_worse": s_xy["mean"] <= TH["g4_xy_max"] if s_xy else None,
    }
    goal = {
        "g3_yaw_goal": s_yaw["mean"] <= TH["g3_yaw_goal_max"] if s_yaw else None,
    }
    # D1：只报数。N=3 且 sd 已知时，只有 >=50% 的效应能被分辨（t≈3），更小的差别不判。
    diagnostic = {
        "abs_dy_median": s_dy["mean"] if s_dy else None,
        "abs_dy_values": s_dy["values"] if s_dy else [],
        "dx_over_expected_median": s_dx["mean"] if s_dx else None,
        "straight_improved_resolvable": (None if not s_dy else
                                         s_dy["mean"] <= TH["d1_absdy_resolvable"]),
    }
    return gates, goal, diagnostic


def fmt(x, w=9, p=4):
    if x is None:
        return "n/a".rjust(w)
    if isinstance(x, bool):
        return ("PASS" if x else "FAIL").rjust(w)
    if isinstance(x, int):
        return str(x).rjust(w)
    return f"{x:.{p}f}".rjust(w)


def report(runs, gates, goal, diagnostic, ok, problems, as_json=None):
    n = len(runs)
    print("=" * 78)
    print(f"P3 gate — {n} runs, seeds {[r['seed'] for r in runs]}")
    for r in runs:
        print(f"  {Path(r['path']).name:44s} vx={fmt(r['vx'],8,4)} "
              f"err_xy={fmt(r['err_xy'],8,4)} err_yaw={fmt(r['err_yaw'],8,4)}")
    print("-" * 78)
    print(f"{'quantity':22s}{'mean':>10s}{'sem':>10s}{'CV%':>8s}{'baseline':>11s}{'vs base':>9s}")
    for name, key, base in (("vx_mean", "vx", BASE_VX),
                            ("error_vel_xy", "err_xy", BASE_ERR_XY),
                            ("error_vel_yaw", "err_yaw", BASE_ERR_YAW)):
        s = stats(runs, key)
        if s is None:
            continue
        ratio = s["mean"] / base if base else float("nan")
        print(f"{name:22s}{fmt(s['mean']):>10s}{fmt(s['sem']):>10s}"
              f"{fmt(s['cv_pct'],8,2)}{fmt(base):>11s}{fmt(ratio,9,3):>9s}")
    print("-" * 78)
    print(f"{'gate':22s}{'value':>10s}{'thr':>10s}{'':>9s}")
    print(f"{'g1_no_fall (max term)':22s}{fmt(max(r['terminated'] for r in runs) if runs else None,10)}"
          f"{fmt(TH['g1_fall_max'],10,3)}   {fmt(gates['g1_no_fall'])}")
    print(f"{'g2_vx_not_worse':22s}{fmt(stats(runs,'vx')['mean'] if runs else None,10)}"
          f"{fmt(TH['g2_vx_min'],10)}{'':3s}{fmt(gates['g2_vx_not_worse'])}")
    print(f"{'g3_yaw_responds':22s}{fmt(stats(runs,'err_yaw')['mean'] if runs else None,10)}"
          f"{fmt(TH['g3_yaw_gate_max'],10)}{'':3s}{fmt(gates['g3_yaw_responds'])}")
    print(f"{'g4_xy_not_worse':22s}{fmt(stats(runs,'err_xy')['mean'] if runs else None,10)}"
          f"{fmt(TH['g4_xy_max'],10)}{'':3s}{fmt(gates['g4_xy_not_worse'])}")
    print(f"{'  (goal) g3_yaw_goal':22s}{'':10s}{fmt(TH['g3_yaw_goal_max'],10)}   "
          f"{fmt(goal['g3_yaw_goal'])}")
    print("-" * 78)
    print(f"D1 直行诊断（不给判决）: abs_dy median={fmt(diagnostic['abs_dy_median'])} "
          f"values={[round(v,3) for v in diagnostic['abs_dy_values']]} "
          f"dx_ratio={fmt(diagnostic['dx_over_expected_median'])}")
    print(f"   可分辨改善阈值(<=0.5x 基线): {TH['d1_absdy_resolvable']:.4f} -> "
          f"{'可宣称改善' if diagnostic['straight_improved_resolvable'] else '未分辨（含可能只是没修好）'}")
    print("-" * 78)
    if not ok:
        print("INTEGRITY FAIL — 读数不可用：")
        for p in problems:
            print("  *", p)
        verdict = "INTEGRITY_FAIL"
    elif n < MIN_REPEATS:
        print(f"PROVISIONAL — 只有 {n} 次重复（<{MIN_REPEATS}），不给判决。"
              f"高 CV 量（absdy {BASE_CV_PCT['abs_dy_body_median']}%）至少要 {MIN_REPEATS} 次。")
        verdict = "PROVISIONAL"
    else:
        red = [k for k, v in gates.items() if v is False]
        verdict = "PASS" if not red else "FAIL"
        print(f"VERDICT {verdict}" + (f" — red: {red}" if red else ""))
        if goal["g3_yaw_goal"]:
            print("  目标值也达成（偏航误差减半）")
        elif gates["g3_yaw_responds"]:
            print("  偏航有反应但未到目标值（<0.5x）——看 rel_heading_envs 是否要调")

    if as_json:
        Path(as_json).write_text(json.dumps({
            "verdict": verdict, "n": n, "seeds": [r["seed"] for r in runs],
            "gates": gates, "goal": goal, "diagnostic": diagnostic,
            "thresholds": TH, "baseline": {"vx": BASE_VX, "err_xy": BASE_ERR_XY,
                                           "err_yaw": BASE_ERR_YAW, "abs_dy": BASE_ABS_DY},
            "integrity_problems": problems,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {as_json}")
    return {"PASS": 0, "FAIL": 1, "PROVISIONAL": 2, "INTEGRITY_FAIL": 3}[verdict]


def audit_baseline(root: Path) -> int:
    """核对写死的常量 == 基线文件重算值。文件被改而常量没改 = 阈值的来源变了。"""
    rc = 0
    runs = []
    for rel, want in BASE_FILES.items():
        p = root / rel
        if not p.exists():
            print(f"[audit] 缺基线文件 {rel}")
            rc = 3
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        mark = "ok" if got == want else f"MISMATCH 期望 {want}"
        if got != want:
            rc = 3
        print(f"[audit] {Path(rel).name:32s} sha256[:16]={got} {mark}")
        runs.append(json.loads(p.read_text(encoding="utf-8")))
    if rc:
        return rc
    rr = [{"vx": _q(d, "speed", "vx_mean"),
           "err_xy": _q(d, "official_metrics", "error_vel_xy"),
           "err_yaw": _q(d, "official_metrics", "error_vel_yaw"),
           "absdy": _q(d, "displacement", "abs_dy_body_median"),
           "dx_ratio": _q(d, "displacement", "dx_over_expected"),
           "yaw_drift": _q(d, "heading", "yaw_drift_deg_s")}
          for d in runs]
    # 冻结常量名 -> run 里的短键
    keymap = {"vx_mean": "vx", "error_vel_xy": "err_xy",
              "error_vel_yaw": "err_yaw", "abs_dy_body_median": "absdy",
              "dx_over_expected": "dx_ratio", "yaw_drift_deg_s": "yaw_drift"}
    checks = [("vx_mean", BASE_VX), ("error_vel_xy", BASE_ERR_XY),
              ("error_vel_yaw", BASE_ERR_YAW), ("abs_dy_body_median", BASE_ABS_DY)]
    for name, base in checks:
        s = stats(rr, keymap[name])
        ok = abs(s["mean"] - base) <= 1e-4 * max(1.0, abs(base))
        if not ok:
            rc = 3
        print(f"[audit] {name:22s} file={s['mean']:.6f} frozen={base:.6f} "
              f"{'ok' if ok else 'MISMATCH'}")
        if s["sem"] is not None and abs(s["sem"] - BASE_SEM[name]) > 0.01 * BASE_SEM[name]:
            print(f"[audit]   sem 也变了：file={s['sem']:.6f} frozen={BASE_SEM[name]:.6f}")
            rc = 3
        cv = s["cv_pct"]
        if cv is not None and abs(cv - BASE_CV_PCT[name]) > 0.05 * BASE_CV_PCT[name]:
            print(f"[audit]   CV 变了：file={cv:.2f}% frozen={BASE_CV_PCT[name]:.2f}%")
            rc = 3
    print("[audit]", "OK —— 阈值来源与文件一致" if rc == 0 else "有 MISMATCH")
    return rc


def selftest(root: Path) -> int:
    """每条都是一个**负对照**：故意弄坏某一样，对应闸门必须变红。"""
    fails = []

    def check(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not cond:
            fails.append(name)

    base_paths = [str(root / rel) for rel in BASE_FILES]
    base = load(base_paths)

    # 1) 基线自身：vx 门必须绿（它在走）、偏航门必须红（这就是要修的东西）
    ok, probs = integrity(base)
    g, goal, diag = judge(base)
    check("t1 基线完整性过", ok, str(probs))
    check("t1 基线 vx 门为绿（对照没被误杀）", g["g2_vx_not_worse"] is True)
    check("t1 基线偏航门为红（负对照：这就是缺口）", g["g3_yaw_responds"] is False,
          f"err_yaw={stats(base,'err_yaw')['mean']:.4f} > {TH['g3_yaw_gate_max']:.4f}")
    check("t1 D1 不能宣称直行改善", diag["straight_improved_resolvable"] is False)

    tmp = Path(tempfile.mkdtemp(prefix="gate_p3_selftest_"))

    def mutate(name, fn):
        out = []
        for p in base_paths:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            fn(d)
            q = tmp / f"{name}_{Path(p).name}"
            q.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            out.append(str(q))
        return out

    # 2) 理想重训：偏航减 55%、vx 不退化 ⇒ 全过 + 目标达成
    good = mutate("good", lambda d: (
        d["official_metrics"].__setitem__("error_vel_yaw",
                                          d["official_metrics"]["error_vel_yaw"] * 0.45)))
    ok, probs = integrity(load(good))
    g, goal, _ = judge(load(good))
    check("t2 理想重训：完整性过", ok, str(probs))
    check("t2 理想重训：四门全绿", all(v is True for v in g.values()), str(g))
    check("t2 理想重训：目标值达成", goal["g3_yaw_goal"] is True)

    # 3) 治好了偏航但把走路弄坏 ⇒ G2 必须红（防"用降速换稳定"）
    broken = mutate("slow", lambda d: (
        d["official_metrics"].__setitem__("error_vel_yaw",
                                          d["official_metrics"]["error_vel_yaw"] * 0.45),
        d["speed"].__setitem__("vx_mean", d["speed"]["vx_mean"] * 0.80)))
    g3, _, _ = judge(load(broken))
    check("t3 偏航好但 vx 掉 20% ⇒ G2 红", g3["g2_vx_not_worse"] is False,
          f"vx={stats(load(broken),'vx')['mean']:.4f} < {TH['g2_vx_min']:.4f}")
    check("t3 该组偏航门仍是绿（说明红的是 G2 不是别的原因）", g3["g3_yaw_responds"] is True)

    # 4) 偏航只好了 5% ⇒ 低于可分辨门槛，必须红（防"噪声当成果"）
    tiny = mutate("tiny", lambda d: (
        d["official_metrics"].__setitem__("error_vel_yaw",
                                          d["official_metrics"]["error_vel_yaw"] * 0.95)))
    g4, _, _ = judge(load(tiny))
    check("t4 偏航只改善 5% ⇒ G3 红", g4["g3_yaw_responds"] is False)

    # 5) 换了 plant ⇒ 完整性必须红（跨 plant 不横比）。只改**一个**文件：
    #    三个都改是"一致地换了个 plant"，那是另一码事，不会红。
    mixed = list(base_paths)
    d = json.loads(Path(mixed[0]).read_text(encoding="utf-8"))
    d.setdefault("plant_fingerprint", {})["json_sha256_12"] = "deadbeef0000"
    q = tmp / f"plant_{Path(mixed[0]).name}"
    q.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    mixed[0] = str(q)
    ok5, probs5 = integrity(load(mixed))
    check("t5 混了另一个 plant ⇒ 完整性红", ok5 is False,
          (probs5 or [""])[0][:50])

    # 6) 命令不是 0.4/0/0 ⇒ 完整性红（和基线不可比）
    cmd = mutate("cmd", lambda d: d.__setitem__("command", {"vx": 0.3, "vy": 0.0, "wz": 0.0}))
    ok6, _ = integrity(load(cmd))
    check("t6 cmd 不是 0.4/0/0 ⇒ 完整性红", ok6 is False)

    # 7) metric_window 坏了（error_vel_* 不是真均值）⇒ 完整性红
    mw = mutate("mw", lambda d: d.setdefault("gates", {}).__setitem__(
        "metric_window_ok", False))
    ok7, _ = integrity(load(mw))
    check("t7 metric_window_ok=False ⇒ 完整性红", ok7 is False)

    # 8) 只有 2 次重复 ⇒ PROVISIONAL（不判，不退 0）
    two = good[:2]
    ok8, _ = integrity(load(two))
    check("t8 两次重复：完整性过但必须 PROVISIONAL", ok8 is True)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):  # 报告的正文上面已验过，这里只要 rc
        rc8 = report(load(two), *judge(load(two)), True, [])
    check("t8 退出码 2", rc8 == 2, f"rc={rc8}")

    print(f"\nselftest: {'ALL PASS' if not fails else 'FAILED ' + str(fails)}")
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="P3 闸门（预注册判据）")
    ap.add_argument("jsons", nargs="*", help="eval_velocity_in_sim.py 产出的 JSON（>=3 次重复）")
    ap.add_argument("--audit-baseline", action="store_true", help="核对冻结常量 vs 基线文件")
    ap.add_argument("--selftest", action="store_true", help="负对照自检")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                    help="仓库根（默认从脚本位置推）")
    a = ap.parse_args()

    if a.audit_baseline:
        return audit_baseline(Path(a.root))
    if a.selftest:
        return selftest(Path(a.root))
    if not a.jsons:
        ap.error("需要 eval JSON，或用 --selftest / --audit-baseline")

    runs = load(a.jsons)
    ok, probs = integrity(runs)
    if not ok:
        report(runs, {"g1_no_fall": None, "g2_vx_not_worse": None,
                      "g3_yaw_responds": None, "g4_xy_not_worse": None},
               {"g3_yaw_goal": None},
               {"abs_dy_median": None, "abs_dy_values": [],
                "dx_over_expected_median": None,
                "straight_improved_resolvable": None},
               ok, probs, a.json_out)
        return 3
    g, goal, diag = judge(runs)
    return report(runs, g, goal, diag, ok, probs, a.json_out)


if __name__ == "__main__":
    sys.exit(main())
