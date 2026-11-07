#!/usr/bin/env python3
"""desk-climb 评估电池聚合：从 run.py evaluate 的产物复算 full-audit 口径的指标。

用法：python3 autodl/audit_climb_eval.py <eval输出目录> [<目录2> ...]
每个目录需含 switches.json 和 actions.npz（standing_safe 逐步标志）。
输出每个目录的 switches / standing2s / standing10s / safe_final / best_safe 中位数，
以及多目录合计（对应 evidence/full-audit.json 的 256 试次口径）。

口径说明（对齐 evidence/full-audit.json 的字段语义）：
- switches: switches.json 条目数
- standingXs: 切换后 standing_safe 连续为真的最长段 >= X 秒的 env 数
- safe_final: 切换后直到结束仍 safe 的 env 数（best_safe 段延伸到末尾）
- best_safe_seconds: 每个已切换 env 的最长连续 safe 段时长（未切换 env 不计）
"""
import json
import sys
from pathlib import Path

import numpy as np


def longest_true_run(flags: np.ndarray) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def audit(d: Path) -> dict:
    switches = json.loads((d / "switches.json").read_text())
    npz = np.load(d / "actions.npz")
    safe = np.asarray(npz["standing_safe"], dtype=bool)  # [steps, envs]
    dt = 0.02  # 50 Hz 控制步
    switch_step = {}
    for s in switches:
        switch_step[s["env"]] = min(switch_step.get(s["env"], 1 << 30), s["step"])
    best_safe = {}
    safe_final = 0
    for env, step in switch_step.items():
        post = safe[step:, env]
        best = longest_true_run(post)
        best_safe[env] = best * dt
        if len(post) and post[-best:].all() if best else False:
            safe_final += 1
    vals = sorted(best_safe.values())
    med = vals[len(vals) // 2] if vals else 0.0
    r = {
        "dir": d.name,
        "switches": len(switch_step),
        "standing2s": sum(1 for v in best_safe.values() if v >= 2.0),
        "standing10s": sum(1 for v in best_safe.values() if v >= 10.0),
        "safe_final": safe_final,
        "best_safe_median": med,
        "best_safe_max": max(best_safe.values()) if best_safe else 0.0,
    }
    print(
        f"{r['dir']:>22}  switches={r['switches']:>3}  stand2s={r['standing2s']:>3}  "
        f"stand10s={r['standing10s']:>3}  safe_final={r['safe_final']:>3}  "
        f"best_safe med={r['best_safe_median']:.2f}s max={r['best_safe_max']:.2f}s"
    )
    return r


def main() -> None:
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        print(__doc__)
        sys.exit(1)
    rows = [audit(d) for d in dirs]
    if len(rows) > 1:
        n = len(rows) * 64
        tot = {k: sum(r[k] for r in rows) for k in ("switches", "standing2s", "standing10s", "safe_final")}
        print(
            f"{'TOTAL':>22}  switches={tot['switches']}/{n}  stand2s={tot['standing2s']}/{n}  "
            f"stand10s={tot['standing10s']}/{n}  safe_final={tot['safe_final']}/{n}"
        )
        print("官方基线:        switches=210/256  stand10s=105/256 (official getup)")


if __name__ == "__main__":
    main()
