"""Turn the TensorBoard event file into a self-contained training dashboard.

Why not just use TensorBoard: the point is to *look at this run* next to the
reference levels we derived analytically (standing-still baseline for joy_feet,
the 12-point ceiling, the gate thresholds).  A single HTML with those reference
lines drawn in is easier to read than 36 separate TB panels.

Writes one .html with the curves and the raw numbers embedded; no CDN, no server.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
from pathlib import Path

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

# (tag, title, unit, reference lines as [(value, label, color)])
PANELS = [
    ("Train/mean_reward", "总奖励", "", []),
    ("Train/mean_episode_length", "平均 episode 长度", "steps", [(400, "满 8s", "#64748b")]),
    ("Episode_Reward/joy_feet", "joy_feet（踏步节奏，权重 +12）", "", [
        (4.39, "站桩基线 4.39", "#f59e0b"),
        (8.18, "只抬一只脚 8.18", "#a855f7"),
        (12.0, "满分 12", "#22c55e"),
    ]),
    ("Episode_Reward/action_rate_l2", "action_rate_l2（惩罚项，权重退火到 -1.0）", "", []),
    ("Episode_Reward/joy_balance", "joy_balance（权重 +5，越稳越高）", "", [(5.0, "满分 5", "#22c55e")]),
    ("Episode_Reward/joy_drift", "joy_drift（权重 100，罚位移）", "", [(0.0, "零漂移", "#22c55e")]),
    ("Episode_Reward/joy_head", "joy_head（头部跟踪，权重 +3）", "", [(3.0, "满分 3", "#22c55e")]),
    ("Episode_Termination/fell_over", "摔倒率", "", [(0.0, "不摔", "#22c55e")]),
    ("Metrics/twist/error_vel_xy", "水平速度跟踪误差", "m/s", []),
    ("Metrics/twist/error_vel_yaw", "偏航速度跟踪误差", "rad/s", []),
    ("Policy/mean_std", "策略输出标准差（探索强度）", "", []),
    ("Loss/entropy", "策略熵", "", []),
    ("Perf/collection_time", "采样耗时（rollout）", "s", []),
    ("Perf/learning_time", "PPO 更新耗时", "s", []),
    ("Curriculum/action_rate_weight", "action_rate 权重课程", "", []),
    ("Episode_Metrics/mean_action_acc", "动作二阶差分均值", "", []),
]


def load(run_dir: Path) -> dict[str, list[tuple[int, float]]]:
    files = sorted(glob.glob(str(run_dir / "events.out.tfevents*")))
    if not files:
        raise SystemExit(f"no event file under {run_dir}")
    out: dict[str, list[tuple[int, float]]] = {}
    for f in files:
        ea = EventAccumulator(f, size_guidance={"scalars": 0})
        ea.Reload()
        for tag in ea.Tags()["scalars"]:
            out.setdefault(tag, []).extend((s.step, s.value) for s in ea.Scalars(tag))
    for k in out:
        out[k] = sorted(out[k])
    return out


def svg_path(points, w, h, pad_l, pad_r, pad_t, pad_b, ymin, ymax, xmin, xmax):
    if not points:
        return ""
    if xmax <= xmin:
        xmax = xmin + 1
    if ymax <= ymin:
        ymax = ymin + 1
    sx = (w - pad_l - pad_r) / (xmax - xmin)
    sy = (h - pad_t - pad_b) / (ymax - ymin)
    d = []
    for i, (x, y) in enumerate(points):
        px = pad_l + (x - xmin) * sx
        py = h - pad_b - (y - ymin) * sy
        d.append(("M" if i == 0 else "L") + f"{px:.1f},{py:.1f}")
    return " ".join(d)


def build_panel(tag, title, unit, refs, series, xmax_global):
    w, h, pad_l, pad_r, pad_t, pad_b = 640, 190, 58, 14, 26, 24
    if not series:
        return f'<div class="card"><h3>{title}</h3><p class="muted">无数据</p></div>'
    xs = [p[0] for p in series]
    ys = [p[1] for p in series]
    ymin, ymax = min(ys), max(ys)
    for v, _, _ in refs:
        ymin, ymax = min(ymin, v), max(ymax, v)
    if ymax - ymin < 1e-12:
        ymax = ymin + 1.0
    span = ymax - ymin
    ymin -= span * 0.08
    ymax += span * 0.08
    xmax = max(xs) if xs else 1
    d = svg_path(series, w, h, pad_l, pad_r, pad_t, pad_b, ymin, ymax, 0, xmax)

    def ypx(v):
        return h - pad_b - (v - ymin) / (ymax - ymin) * (h - pad_t - pad_b)

    def xpx(v):
        return pad_l + (v / (xmax or 1)) * (w - pad_l - pad_r)

    ref_svg = ""
    for v, label, color in refs:
        if ymin <= v <= ymax:
            y = ypx(v)
            ref_svg += (
                f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="4 3" opacity="0.75"/>'
                f'<text x="{w-pad_r-2}" y="{y-4:.1f}" fill="{color}" font-size="10" '
                f'text-anchor="end">{label}</text>'
            )

    # y ticks
    ticks = ""
    for i in range(5):
        v = ymin + (ymax - ymin) * i / 4
        y = ypx(v)
        ticks += (f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" '
                  f'stroke="#1e293b" stroke-width="1"/>'
                  f'<text x="{pad_l-6}" y="{y+3.5:.1f}" fill="#64748b" font-size="10" '
                  f'text-anchor="end">{v:+.3g}</text>')
    # last value marker + label
    lx, ly = series[-1]
    last = (f'<circle cx="{xpx(lx):.1f}" cy="{ypx(ly):.1f}" r="3.5" fill="#38bdf8"/>'
            f'<text x="{xpx(lx)-6:.1f}" y="{ypx(ly)-8:.1f}" fill="#38bdf8" font-size="11" '
            f'text-anchor="end" font-weight="600">{ly:.4g}</text>')

    return f'''<div class="card">
  <h3>{title} <span class="tag">{tag}</span></h3>
  <svg viewBox="0 0 {w} {h}" width="100%" height="{h}">
    {ticks}{ref_svg}
    <path d="{d}" fill="none" stroke="#38bdf8" stroke-width="1.8" stroke-linejoin="round"/>
    {last}
    <text x="{pad_l}" y="{h-6}" fill="#64748b" font-size="10">iter 0</text>
    <text x="{w-pad_r}" y="{h-6}" fill="#64748b" font-size="10" text-anchor="end">iter {xmax}</text>
  </svg>
</div>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="joy 训练过程")
    args = ap.parse_args()

    data = load(Path(args.run_dir))
    cards = [build_panel(*p, data.get(p[0], []), 0) for p in PANELS]

    # summary table of the latest value of every tag
    rows = []
    for tag in sorted(data):
        s = data[tag]
        if not s:
            continue
        first, last = s[0][1], s[-1][1]
        rows.append(
            f"<tr><td class='mono'>{tag}</td><td class='num'>{s[0][0]}</td>"
            f"<td class='num'>{first:+.5g}</td><td class='num'>{last:+.5g}</td>"
            f"<td class='num'>{last-first:+.4g}</td></tr>"
        )
    n_iter = max((s[-1][0] for s in data.values() if s), default=0)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{args.title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:24px;background:#0b1220;color:#e2e8f0;
     font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}
.meta{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:14px}}
.card{{background:#111a2b;border:1px solid #1e293b;border-radius:10px;padding:12px 14px}}
.card h3{{font-size:13px;font-weight:600;margin:0 0 8px;color:#cbd5e1}}
.tag{{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:#475569;font-weight:400}}
.muted{{color:#64748b;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px}}
th,td{{padding:4px 8px;border-bottom:1px solid #1e293b;text-align:left}}
th{{color:#94a3b8;font-weight:500;position:sticky;top:0;background:#0b1220}}
.mono{{font-family:ui-monospace,Consolas,monospace;color:#cbd5e1}}
.num{{text-align:right;font-family:ui-monospace,Consolas,monospace;color:#94a3b8}}
h2{{font-size:15px;margin:26px 0 6px;color:#cbd5e1}}
</style></head><body>
<h1>{args.title}</h1>
<div class="meta">{os.path.basename(args.run_dir.rstrip(os.sep))} · {n_iter} 次迭代 ·
{len(data)} 条曲线 · 生成于 {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}</div>
<div class="grid">{''.join(cards)}</div>
<h2>全部曲线最新值</h2>
<table><thead><tr><th>标签</th><th class="num">最后一次 iter</th><th class="num">首值</th>
<th class="num">末值</th><th class="num">变化</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out}  ({len(html)/1024:.0f} KB, {len(data)} tags, {n_iter} iters)")


if __name__ == "__main__":
    main()
