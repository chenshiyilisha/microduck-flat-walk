"""判据汇总：读 out/xplant_* 的逐格 JSON，算 vx / |err| / 摔倒率 / Welch t。

字段来源（rehearse_hd1910 的输出）：
  speed.vx_mean_steady、heading.heading_error_final_deg、stability.fell

用法：python tools/hd1910/judge_summary.py out/xplant_a out/xplant_b ...
"""
import glob
import json
import math
import os
import statistics as st
import sys


def load(d):
    """逐格 JSON 里 runs 是一个列表（目前每格 1 个 run）；manifest.json 跳过。"""
    rows = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(f) == "manifest.json":
            continue
        try:
            d_ = json.load(open(f, encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows.extend(d_.get("runs") or [])
    return rows


def cell(name, d, kp=None):
    """kp 非 None 时只取该 kp_fw 的 run（同一目录里可能同时有 p3/p8 两档）。"""
    rows = load(d)
    if kp is not None:
        rows = [j for j in rows if (j.get("settings") or {}).get("kp_fw") == kp]
    vx, err, fell = [], [], 0
    for j in rows:
        if (j.get("stability") or {}).get("fell"):
            fell += 1
        v = (j.get("speed") or {}).get("vx_mean_steady")
        e = (j.get("heading") or {}).get("heading_error_final_deg")
        if v is not None:
            vx.append(v)
        if e is not None:
            err.append(abs(e))
    return {"name": name, "n": len(rows), "fell": fell, "vx": vx, "err": err}


def welch(a, b):
    """Welch t，b 相对 a。a/b 样本数 <2 或方差为 0 时返回 inf/nan 并在打印时说明。"""
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    den = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    if den == 0:
        return float("inf")
    return (st.mean(b) - st.mean(a)) / den


def fmt(x, w=8, p=4):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a".rjust(w)
    return f"{x:{w}.{p}f}"


def main(argv):
    cells = []
    for spec in argv:
        # 目录[:kp] —— 同目录里有 p3(5) 与 p8(8) 两档时必须指定，否则会混成一行
        d, _, kp = spec.partition(":")
        name = os.path.basename(d.rstrip("/\\")).replace("xplant_", "")
        cells.append(cell(f"{name}[kp{kp}]" if kp else name, d, float(kp) if kp else None))
    print(f"{'cell':34s} {'n':>3} {'fall':>5} {'vx':>8} {'sem':>7} {'|err|°':>8} {'sem':>6}")
    for c in cells:
        v, e = c["vx"], c["err"]
        vs = st.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else float("nan")
        es = st.stdev(e) / math.sqrt(len(e)) if len(e) > 1 else float("nan")
        print(f"{c['name']:34s} {c['n']:>3} {c['fell']:>5} "
              f"{fmt(st.mean(v) if v else None)} {fmt(vs, 7)} "
              f"{fmt(st.mean(e) if e else None, 8, 2)} {fmt(es, 6, 2)}")
    if len(cells) >= 2:
        base = cells[0]
        print()
        for c in cells[1:]:
            print(f"{c['name']} vs {base['name']}: "
                  f"vx {100 * (st.mean(c['vx']) / st.mean(base['vx']) - 1):+.1f}%  "
                  f"(Welch t={welch(base['vx'], c['vx']):.1f})   "
                  f"|err| {st.mean(c['err']):.2f}° vs {st.mean(base['err']):.2f}°  "
                  f"(t={welch(base['err'], c['err']):.1f})")


if __name__ == "__main__":
    main(sys.argv[1:])
