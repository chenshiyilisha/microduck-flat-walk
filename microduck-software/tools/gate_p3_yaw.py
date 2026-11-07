"""P3 闸门（预注册）：用 N 次重复的 eval JSON 判「偏航修好了没有，并且没把走路弄坏」。

为什么单独一个脚本
------------------
`eval_velocity_in_sim.py` 里那批 gates 是**单次 Run 的体检**（是否冻结命令、是否在动、
是否摔）。它们不能当 P3 的判决，因为：

  * `not_sideways` = `abs_dy_body_median <= 0.5 * |dx_body_mean|`，两个量在 kp32 基线上
    都是**高 CV**：三次重复 dx_over_expected CV **25.5%**、absdy CV **19.6%**
    ⇒ 单次读数靠运气就能翻面。反直觉的是**该门的判据量在噪声里，而真正稳的量没进闸门**：
    `error_vel_yaw` 三次重复 CV 只有 **1.2%**（1.1831 / 1.2023 / 1.2113）。
    （实测复现：同样三条 gates 打在 kp8 的 model_2999 上，`not_sideways` **2 过 1 挂**，
    而三 seed 的 absdy 是 0.558 / 0.443 / 0.428 —— 阈值 0.486 正好落在分布中间。）
  * 判决必须跨 seed，且判据量本身要可分辨。本仓纪律见
    `.workbuddy/memory/MEMORY.md`「判决双轴」「闸门只用低 CV 量」与
    `docs/active/microduck-HD1910软件方案.md` §8.3。

所以这里把判据**先钉死、再测**（预注册）：阈值全部是写死的字面量（只含"要求"倍数），
基线值只能当"对照"，不能当"被测量"。三道机械护栏：

  1. `--audit-baseline`：核对写死常量与基线 JSON 的 sha256 + 均值 + sem + CV
     （改文件不改常量 ⇒ 直接红）。
  2. 完整性：本次读数的 plant 指纹必须与所选基线的 plant 完全一致
     （跨 plant 不横比 —— m5/kp32 的 run 放进 kp8 基线里必须红）。
  3. **不许拿自己当基线**：本次输入的文件 sha256 只要与基线文件重合 ⇒ 拒绝判决。
     （"阈值取自被测量"这类错误唯一的机械判据就是这条。）

两套基线（都是三 seed、cmd 0.4/0/0、32 env × 8 s、solver 100/50、seed 11/22/33）
---------------------------------------------------------------------------
  m5kp32  ckpt `model_5999.pt`（HD1910 **m5** / `kp_fw=32`，6000 iter）
          `artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s{11,22,33}.json`
          sha16 6bdb55ee591ad339 / 6fe61cf6e5a3bd3c / 3e84f1f7657b0e70
  kp8     ckpt `model_2999.pt`（`2026-11-03_08-33-18_p8head_030_4096x3000`，
          HD1910 **kp8** + heading 奖励，3000 iter）—— 当前部署候选
          `artifacts/flat_walk/evals/p8head_ref/hd1910_p8head2999_vx040_s{11,22,33}.json`
          sha16 9453adc8ec4b3ba8 / 16f81e451d5ba460 / 431da617e159aab8

⚠️ kp8 这组是**参考点，不是 heading 对照**：相对 m5/kp32 它同时换了三样（plant、
heading 奖励、迭代数 3000 vs 6000）⇒ **不能用它宣称"heading 闭环有效"**。
唯一的干净对照（kp8 + rel_heading 0.3 + 不带奖励）在 2026-11-02 21:26 那条 run 里
只跑到 `model_0` 就被中止了（`params/env.yaml` 里确实没有 heading_hold/tracking，
已回读确认）⇒ kp8 上的"奖励有无"这个单变量目前**没有对照**。

判据（双轴 + 不许退化轴，倍数固定、基线值按 --baseline-set 取）
----------------------------------------------------------------
  G1 no_fall      每次 terminated_frac < 0.02                （安全）
  G2 vx 不退化     mean(vx)            >= 0.97 × 基线          （别把走路训坏）
  G3 偏航有反应    mean(error_vel_yaw) <= 0.90 × 基线          （"干预是否真的起作用"）
     目标（非判决）                     <= 0.50 × 基线
  G4 xy 不退化     mean(error_vel_xy)  <= 1.05 × 基线
  D1 直行诊断      只报数、不给判决（N=3 只能分辨 >=50% 的效应）

为什么 G3 用 `error_vel_yaw` 而不是净漂移
----------------------------------------
cmd 冻结 wz=0 时，`error_vel_yaw` 是**瞬时** |ω| 误差（kp32 实测 ≈1.2 rad/s），
而 `yaw_drift` 是**净**转角/时长（中位 14 deg/s ≈ 0.25 rad/s）。两者差 4.8×
不是矛盾：同次里 signed mean ω = 0.043 rad/s ≈ yaw_drift_signed 2.52 deg/s，
即净转角小、瞬时在**摆**（等效 ±17° @ 1 Hz 的步态偏航摇摆）。
摆是随机游走的源头（步态每步给一点航向噪声），且它是低 CV 可判的量；
净漂移是它的积分结果，噪声被放大 20 倍，只适合当诊断。

用法
----
  python microduck-software/tools/gate_p3_yaw.py out/p3/*.json
  python microduck-software/tools/gate_p3_yaw.py --baseline-set kp8 out/p4/*.json
  python microduck-software/tools/gate_p3_yaw.py --audit-baseline [--baseline-set kp8]
  python microduck-software/tools/gate_p3_yaw.py --selftest

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
# 冻结基线。算术写在旁边，是为了让人能拿计算器复核，而不是"相信脚本"。
# 注意：这里只有**测量值**，没有阈值倍数——倍数在 TH_FACTORS 里，两者分开才审得清。
# ---------------------------------------------------------------------------
BASELINES = {
    "m5kp32": {
        "label": "m5/kp32 model_5999（6000 iter，无 heading 奖励）",
        "plant": {"kp_fw": 32.0, "json_sha256_12": "d1553204e756"},
        "ckpt": "2026-10-27_08-37-16_hd1910_resume_4096_to6000_1027/model_5999.pt",
        # mean(0.302725, 0.305979, 0.294377) 等
        "vx": 0.301027,
        "err_xy": 0.198333,
        "err_yaw": 1.198900,
        "abs_dy": 0.838367,
        "sem": {"vx": 0.003468, "err_xy": 0.002000, "err_yaw": 0.008295,
                "abs_dy": 0.094800},
        "cv_pct": {"vx": 1.98, "err_xy": 1.75, "err_yaw": 1.20, "abs_dy": 19.58},
        "files": {
            "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s11.json": "6bdb55ee591ad339",
            "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s22.json": "6fe61cf6e5a3bd3c",
            "artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s33.json": "3e84f1f7657b0e70",
        },
    },
    "kp8": {
        "label": "kp8 model_2999（3000 iter，带 heading 奖励）—— 部署候选，非 heading 对照",
        "plant": {"kp_fw": 8.0, "json_sha256_12": "799800a2ea0d"},
        "ckpt": "2026-11-03_08-33-18_p8head_030_4096x3000/model_2999.pt",
        # mean(0.164335, 0.164722, 0.159573) 等
        "vx": 0.162876,
        "err_xy": 0.270188,
        "err_yaw": 0.728356,
        "abs_dy": 0.476141,
        "sem": {"vx": 0.001643, "err_xy": 0.001070, "err_yaw": 0.011017,
                "abs_dy": 0.041018},
        "cv_pct": {"vx": 1.75, "err_xy": 0.69, "err_yaw": 2.62, "abs_dy": 14.92},
        "files": {
            "artifacts/flat_walk/evals/p8head_ref/hd1910_p8head2999_vx040_s11.json": "9453adc8ec4b3ba8",
            "artifacts/flat_walk/evals/p8head_ref/hd1910_p8head2999_vx040_s22.json": "16f81e451d5ba460",
            "artifacts/flat_walk/evals/p8head_ref/hd1910_p8head2999_vx040_s33.json": "431da617e159aab8",
        },
    },
}

# 只有"要求"的倍数，没有任何测量值。改这里 = 改判据，必须单独 commit。
TH_FACTORS = {
    "g1_fall_max": 0.02,
    "g2_vx": 0.97,
    "g3_yaw_gate": 0.90,
    "g3_yaw_goal": 0.50,
    "g4_xy": 1.05,
    "d1_absdy": 0.50,
}
MIN_REPEATS = 3
FROZEN_CMD = {"vx": 0.4, "vy": 0.0, "wz": 0.0}


def thresholds(base: dict) -> dict:
    f = TH_FACTORS
    return {
        "g1_fall_max": f["g1_fall_max"],
        "g2_vx_min": f["g2_vx"] * base["vx"],
        "g3_yaw_gate_max": f["g3_yaw_gate"] * base["err_yaw"],
        "g3_yaw_goal_max": f["g3_yaw_goal"] * base["err_yaw"],
        "g4_xy_max": f["g4_xy"] * base["err_xy"],
        "d1_absdy_resolvable": f["d1_absdy"] * base["abs_dy"],
    }


def _q(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _sha16(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def load(paths):
    runs = []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        runs.append({
            "path": str(p),
            "sha16": _sha16(p),
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


def integrity(runs, base):
    """返回 (ok, 问题列表)。任何一条不过 ⇒ 后面所有数字都不可用。"""
    bad = []
    if len(runs) < 2:
        bad.append(f"runs={len(runs)} < 2：单次读数不能判（MJWarp 不可逐位复现）")
        return False, bad

    # 护栏 3：不许拿自己当基线（阈值取自被测量）
    overlap = set(r["sha16"] for r in runs) & set(base["files"].values())
    if overlap:
        bad.append(f"输入里有基线自己的文件（sha16 {sorted(overlap)}）⇒ 这是拿被测量当阈值来源")

    # 护栏 2：plant 必须与基线同一套（跨 plant 不横比，§8.3 #2）
    fps = {(r["plant"], r["plant_fp"].get("json_sha256_12"), r["plant_fp"].get("kp_fw"))
           for r in runs}
    if len(fps) != 1:
        bad.append(f"plant 指纹不一致（跨 plant 不横比）：{sorted(fps, key=str)}")
    else:
        _, sha, kp = next(iter(fps))
        if kp != base["plant"]["kp_fw"] or sha != base["plant"]["json_sha256_12"]:
            bad.append(f"plant 与所选基线不符：本次 kp_fw={kp} sha={sha}，"
                       f"基线 kp_fw={base['plant']['kp_fw']} sha={base['plant']['json_sha256_12']}")

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


def judge(runs, base):
    th = thresholds(base)
    s_vx, s_xy, s_yaw = stats(runs, "vx"), stats(runs, "err_xy"), stats(runs, "err_yaw")
    s_dy = stats(runs, "absdy")
    falls = [r["terminated"] for r in runs if r["terminated"] is not None]

    gates = {
        "g1_no_fall": max(falls) < th["g1_fall_max"] if falls else None,
        "g2_vx_not_worse": s_vx["mean"] >= th["g2_vx_min"] if s_vx else None,
        "g3_yaw_responds": s_yaw["mean"] <= th["g3_yaw_gate_max"] if s_yaw else None,
        "g4_xy_not_worse": s_xy["mean"] <= th["g4_xy_max"] if s_xy else None,
    }
    goal = {"g3_yaw_goal": s_yaw["mean"] <= th["g3_yaw_goal_max"] if s_yaw else None}
    # D1：只报数。N=3 且 sd 已知时，只有 >=50% 的效应能被分辨（t≈3），更小的差别不判。
    diagnostic = {
        "abs_dy_median": s_dy["mean"] if s_dy else None,
        "abs_dy_values": s_dy["values"] if s_dy else [],
        "dx_over_expected_median": (stats(runs, "dx_ratio") or {}).get("mean"),
        "straight_improved_resolvable": (None if not s_dy
                                         else s_dy["mean"] <= th["d1_absdy_resolvable"]),
    }
    return gates, goal, diagnostic, th


def fmt(x, w=9, p=4):
    if x is None:
        return "n/a".rjust(w)
    if isinstance(x, bool):
        return ("PASS" if x else "FAIL").rjust(w)
    if isinstance(x, int):
        return str(x).rjust(w)
    return f"{x:.{p}f}".rjust(w)


def report(runs, gates, goal, diagnostic, th, base, ok, problems, as_json=None):
    n = len(runs)
    print("=" * 78)
    print(f"P3 gate — baseline={base['label']}")
    print(f"           {n} runs, seeds {[r['seed'] for r in runs]}")
    for r in runs:
        print(f"  {Path(r['path']).name:44s} vx={fmt(r['vx'],8,4)} "
              f"err_xy={fmt(r['err_xy'],8,4)} err_yaw={fmt(r['err_yaw'],8,4)}")
    print("-" * 78)
    print(f"{'quantity':22s}{'mean':>10s}{'sem':>10s}{'CV%':>8s}{'baseline':>11s}{'vs base':>9s}")
    for name, key, bkey in (("vx_mean", "vx", "vx"),
                            ("error_vel_xy", "err_xy", "err_xy"),
                            ("error_vel_yaw", "err_yaw", "err_yaw")):
        s = stats(runs, key)
        if s is None:
            continue
        b = base[bkey]
        print(f"{name:22s}{fmt(s['mean']):>10s}{fmt(s['sem']):>10s}"
              f"{fmt(s['cv_pct'],8,2)}{fmt(b):>11s}{fmt(s['mean']/b,9,3):>9s}")
    print("-" * 78)
    term = max(r["terminated"] for r in runs) if runs else None
    print(f"{'gate':22s}{'value':>10s}{'thr':>10s}{'':>9s}")
    print(f"{'g1_no_fall (max term)':22s}{fmt(term,10)}{fmt(th['g1_fall_max'],10,3)}   "
          f"{fmt(gates['g1_no_fall'])}")
    print(f"{'g2_vx_not_worse':22s}{fmt((stats(runs,'vx') or {}).get('mean'),10)}"
          f"{fmt(th['g2_vx_min'],10)}{'':3s}{fmt(gates['g2_vx_not_worse'])}")
    print(f"{'g3_yaw_responds':22s}{fmt((stats(runs,'err_yaw') or {}).get('mean'),10)}"
          f"{fmt(th['g3_yaw_gate_max'],10)}{'':3s}{fmt(gates['g3_yaw_responds'])}")
    print(f"{'g4_xy_not_worse':22s}{fmt((stats(runs,'err_xy') or {}).get('mean'),10)}"
          f"{fmt(th['g4_xy_max'],10)}{'':3s}{fmt(gates['g4_xy_not_worse'])}")
    print(f"{'  (goal) g3_yaw_goal':22s}{'':10s}{fmt(th['g3_yaw_goal_max'],10)}   "
          f"{fmt(goal['g3_yaw_goal'])}")
    print("-" * 78)
    print(f"D1 直行诊断（不给判决）: abs_dy median={fmt(diagnostic['abs_dy_median'])} "
          f"values={[round(v,3) for v in diagnostic['abs_dy_values']]} "
          f"dx_ratio={fmt(diagnostic['dx_over_expected_median'])}")
    print(f"   可分辨改善阈值(<=0.5x 基线): {th['d1_absdy_resolvable']:.4f} -> "
          f"{'可宣称改善' if diagnostic['straight_improved_resolvable'] else '未分辨（含可能只是没修好）'}")
    print("-" * 78)
    if not ok:
        print("INTEGRITY FAIL — 读数不可用：")
        for p in problems:
            print("  *", p)
        verdict = "INTEGRITY_FAIL"
    elif n < MIN_REPEATS:
        print(f"PROVISIONAL — 只有 {n} 次重复（<{MIN_REPEATS}），不给判决。"
              f"高 CV 量（absdy {base['cv_pct']['abs_dy']}%）至少要 {MIN_REPEATS} 次。")
        verdict = "PROVISIONAL"
    else:
        red = [k for k, v in gates.items() if v is False]
        verdict = "PASS" if not red else "FAIL"
        print(f"VERDICT {verdict}" + (f" — red: {red}" if red else ""))
        if goal["g3_yaw_goal"]:
            print("  目标值也达成（偏航误差减半）")
        elif gates["g3_yaw_responds"]:
            print("  偏航有反应但未到目标值（<0.5x）——看 rel_heading_envs / 奖励权重是否要调")

    if as_json:
        Path(as_json).write_text(json.dumps({
            "verdict": verdict, "n": n, "seeds": [r["seed"] for r in runs],
            "baseline_label": base["label"], "baseline_ckpt": base["ckpt"],
            "gates": gates, "goal": goal, "diagnostic": diagnostic,
            "thresholds": th, "factors": TH_FACTORS,
            "integrity_problems": problems,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {as_json}")
    return {"PASS": 0, "FAIL": 1, "PROVISIONAL": 2, "INTEGRITY_FAIL": 3}[verdict]


def audit_baseline(root: Path, base) -> int:
    """核对写死的常量 == 基线文件重算值。文件被改而常量没改 = 阈值来源变了。"""
    rc = 0
    runs = []
    for rel, want in base["files"].items():
        p = root / rel
        if not p.exists():
            print(f"[audit] 缺基线文件 {rel}")
            rc = 3
            continue
        got = _sha16(p)
        if got != want:
            rc = 3
        print(f"[audit] {Path(rel).name:40s} sha256[:16]={got} "
              f"{'ok' if got == want else f'MISMATCH 期望 {want}'}")
        runs.append(json.loads(p.read_text(encoding="utf-8")))
    if rc:
        return rc
    rr = [{"vx": _q(d, "speed", "vx_mean"),
           "err_xy": _q(d, "official_metrics", "error_vel_xy"),
           "err_yaw": _q(d, "official_metrics", "error_vel_yaw"),
           "absdy": _q(d, "displacement", "abs_dy_body_median")}
          for d in runs]
    for name, bkey in (("vx", "vx"), ("err_xy", "err_xy"),
                       ("err_yaw", "err_yaw"), ("absdy", "abs_dy")):
        s = stats(rr, name)
        if s is None:
            continue
        base_v = base[bkey]
        ok = abs(s["mean"] - base_v) <= 1e-4 * max(1.0, abs(base_v))
        if not ok:
            rc = 3
        print(f"[audit] {name:22s} file={s['mean']:.6f} frozen={base_v:.6f} "
              f"{'ok' if ok else 'MISMATCH'}")
        if s["sem"] is not None and abs(s["sem"] - base["sem"][bkey]) > 0.01 * base["sem"][bkey]:
            print(f"[audit]   sem 变了：file={s['sem']:.6f} frozen={base['sem'][bkey]:.6f}")
            rc = 3
        cv = s["cv_pct"]
        if cv is not None and abs(cv - base["cv_pct"][bkey]) > 0.05 * base["cv_pct"][bkey]:
            print(f"[audit]   CV 变了：file={cv:.2f}% frozen={base['cv_pct'][bkey]:.2f}%")
            rc = 3
    print("[audit]", f"{base['label']} —— 阈值来源与文件一致" if rc == 0 else "有 MISMATCH")
    return rc


def selftest(root: Path) -> int:
    """每条都是一个**负对照**：故意弄坏某一样，对应闸门必须变红。"""
    fails = []

    def check(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not cond:
            fails.append(name)

    base_sets = {k: BASELINES[k] for k in BASELINES}
    paths = {k: [str(root / rel) for rel in v["files"]] for k, v in base_sets.items()}
    loaded = {k: load(paths[k]) for k in paths}

    # 1) 两套基线自身：vx 门必须绿（它们在走）、偏航门必须红（这就是要修的东西）
    for k, base in base_sets.items():
        ok, probs = integrity(loaded[k], base)
        g, goal, diag, _ = judge(loaded[k], base)
        # 注意：这里只验 audit 路径；判决路径会因"拿自己当基线"被拒，见 t9
        check(f"t1[{k}] 基线自审：vx/sem/CV 与常量一致",
              audit_baseline(root, base) == 0)
        check(f"t1[{k}] D1 不能宣称直行改善", diag["straight_improved_resolvable"] is False)
        del ok, probs, g, goal

    tmp = Path(tempfile.mkdtemp(prefix="gate_p3_selftest_"))

    def mutate(base_key, name, fn, only_first=False):
        out = []
        for i, p in enumerate(paths[base_key]):
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            if only_first and i > 0:
                out.append(p)
                continue
            fn(d)
            q = tmp / f"{name}_{Path(p).name}"
            q.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            out.append(str(q))
        return out

    def scale_err_yaw(d, f):
        d["official_metrics"]["error_vel_yaw"] *= f

    def scale_vx(d, f):
        d["speed"]["vx_mean"] *= f

    # 2) 理想重训（以 m5kp32 为基线）：偏航减 55% ⇒ 四门全绿 + 目标达成
    good = mutate("m5kp32", "good", lambda d: scale_err_yaw(d, 0.45))
    base = base_sets["m5kp32"]
    ok, probs = integrity(load(good), base)
    g, goal, _, _ = judge(load(good), base)
    check("t2 理想重训：完整性过", ok, str(probs))
    check("t2 理想重训：四门全绿", all(v is True for v in g.values()), str(g))
    check("t2 理想重训：目标值达成", goal["g3_yaw_goal"] is True)

    # 3) 治好了偏航但把走路弄坏 ⇒ G2 必须红（防"用降速换稳定"）
    broken = mutate("m5kp32", "slow", lambda d: (scale_err_yaw(d, 0.45), scale_vx(d, 0.80)))
    g3, _, _, _ = judge(load(broken), base)
    ok3, _ = integrity(load(broken), base)
    check("t3 该组完整性过（红的是 G2 而不是别的原因）", ok3 is True)
    check("t3 偏航好但 vx 掉 20% ⇒ G2 红", g3["g2_vx_not_worse"] is False,
          f"vx={stats(load(broken),'vx')['mean']:.4f} < {thresholds(base)['g2_vx_min']:.4f}")
    check("t3 该组 G3 仍绿（定位到 G2）", g3["g3_yaw_responds"] is True)

    # 4) 偏航只好了 5% ⇒ 低于可分辨门槛，必须红（防"噪声当成果"）
    tiny = mutate("m5kp32", "tiny", lambda d: scale_err_yaw(d, 0.95))
    g4, _, _, _ = judge(load(tiny), base)
    check("t4 偏航只改善 5% ⇒ G3 红", g4["g3_yaw_responds"] is False)

    # 5) 混了另一个 plant ⇒ 完整性必须红。三个文件都复制到 tmp（否则会先撞上
    #    "拿基线自己当输入"那条护栏，红的就不是 plant 分支了 —— 这条自己踩过），
    #    只把其中一个的 plant sha 改掉。
    mixed = []
    for i, p in enumerate(paths["m5kp32"]):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if i == 0:
            d.setdefault("plant_fingerprint", {})["json_sha256_12"] = "deadbeef0000"
        q = tmp / f"plant_{Path(p).name}"
        q.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        mixed.append(str(q))
    ok5, probs5 = integrity(load(mixed), base)
    check("t5 混了另一个 plant ⇒ 完整性红", ok5 is False, (probs5 or [""])[0][:46])
    check("t5 红的是 plant 分支（不是撞上自己当基线那条）",
          bool(probs5) and "plant 指纹不一致" in probs5[0], (probs5 or [""])[0][:40])

    # 6) 拿 kp8 的读数去比 m5kp32 基线 ⇒ 完整性红（跨 plant 不横比，护栏 2）
    ok6, probs6 = integrity(loaded["kp8"], base)
    check("t6 kp8 读数 vs m5kp32 基线 ⇒ 完整性红", ok6 is False,
          (probs6 or [""])[0][:46])

    # 7) 命令不是 0.4/0/0 ⇒ 完整性红（和基线不可比）
    cmd = mutate("m5kp32", "cmd", lambda d: d.__setitem__(
        "command", {"vx": 0.3, "vy": 0.0, "wz": 0.0}))
    ok7, _ = integrity(load(cmd), base)
    check("t7 cmd 不是 0.4/0/0 ⇒ 完整性红", ok7 is False)

    # 8) metric_window 坏了（error_vel_* 不是真均值）⇒ 完整性红
    mw = mutate("m5kp32", "mw", lambda d: d.setdefault("gates", {}).__setitem__(
        "metric_window_ok", False))
    ok8, _ = integrity(load(mw), base)
    check("t8 metric_window_ok=False ⇒ 完整性红", ok8 is False)

    # 9) 直接拿基线文件当输入 ⇒ 必须拒（"阈值取自被测量"唯一机械判据，护栏 3）
    ok9, probs9 = integrity(loaded["m5kp32"], base)
    check("t9 拿基线自己当输入 ⇒ 完整性红", ok9 is False,
          (probs9 or [""])[0][:46])

    # 10) 只有 2 次重复 ⇒ PROVISIONAL（不判，也不退 0）
    import contextlib
    import io
    two = good[:2]
    ok10, _ = integrity(load(two), base)
    check("t10 两次重复：完整性过但必须 PROVISIONAL", ok10 is True)
    with contextlib.redirect_stdout(io.StringIO()):
        rc10 = report(load(two), *judge(load(two), base), base, True, [])
    check("t10 退出码 2", rc10 == 2, f"rc={rc10}")

    print(f"\nselftest: {'ALL PASS' if not fails else 'FAILED ' + str(fails)}")
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="P3 闸门（预注册判据）")
    ap.add_argument("jsons", nargs="*", help="eval_velocity_in_sim.py 产出的 JSON（>=3 次重复）")
    ap.add_argument("--baseline-set", default="m5kp32", choices=list(BASELINES),
                    help="用哪套冻结基线（决定 plant 与阈值）")
    ap.add_argument("--audit-baseline", action="store_true", help="核对冻结常量 vs 基线文件")
    ap.add_argument("--selftest", action="store_true", help="负对照自检")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                    help="仓库根（默认从脚本位置推）")
    a = ap.parse_args()
    base = BASELINES[a.baseline_set]

    if a.audit_baseline:
        return audit_baseline(Path(a.root), base)
    if a.selftest:
        return selftest(Path(a.root))
    if not a.jsons:
        ap.error("需要 eval JSON，或用 --selftest / --audit-baseline")

    runs = load(a.jsons)
    ok, probs = integrity(runs, base)
    g, goal, diag, th = judge(runs, base)
    if not ok:
        g = {k: None for k in g}
    return report(runs, g, goal, diag, th, base, ok, probs, a.json_out)


if __name__ == "__main__":
    sys.exit(main())
