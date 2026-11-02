#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Aggregate a grid of rehearsal JSONs into per-group mean/sem + Welch t vs baseline.

Why this exists
---------------
A rehearsal grid (kp_fw x initial yaw, or condition x yaw) is one JSON per cell,
and the interesting numbers are *across* cells. Doing that by hand twice is how
the first kp sweep got judged with ``yaw_delta_deg`` — the wrong quantity — and
then re-judged by eye. This script fixes the metric set once:

* forward speed  -> ``speed.vx_mean_steady``        (body frame, steady window)
* heading        -> ``abs(heading.heading_error_final_deg)``  (NOT yaw_delta_deg:
                    with 8 start yaws a "successful" turn is a LARGE delta)
* falls          -> ``stability.fell``

It also reports ``moves_forward`` gate failures separately from real failures:
under a closed heading loop a big initial yaw error makes the robot curve, so net
``dx_body`` can go negative while it is plainly walking forward. That gate is a
net-displacement test and is simply the wrong instrument there.

Usage::

  python tools/hd1910/summarize_rehearsal_grid.py out/kpsweep2999/p*_y*.json
  python tools/hd1910/summarize_rehearsal_grid.py out/kpsweep2999/p*_y*.json \\
      --baseline 5 --json out/kpsweep2999/summary.json
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import math
import os
import pathlib
import re
import statistics as st


def _welch_t(a: list[float], b: list[float]) -> tuple[float, float]:
    """Welch t statistic and a conservative dof (never NaN for n>=2)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan"), 0.0
    va, vb = st.variance(a), st.variance(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return float("nan"), 0.0
    t = (st.mean(a) - st.mean(b)) / se
    dof = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    )
    return t, dof


def _cells(paths: list[str], group_by: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        runs = d.get("runs") or []
        if not runs:
            continue
        r = runs[0]
        if group_by == "kp_fw":
            key = f"{float(r['settings']['kp_fw']):g}"
        elif group_by == "condition":
            key = r["condition"]
        else:  # pragma: no cover - argparse restricts
            raise SystemExit(f"bad --group-by {group_by}")
        rec = {
            "file": os.path.basename(p),
            "yaw0_deg": float(r["settings"].get("yaw_deg", 0.0)),
            "vx": float(r["speed"]["vx_mean_steady"]),
            "heading_err_abs": abs(float(r["heading"]["heading_error_final_deg"])),
            "heading_err": float(r["heading"]["heading_error_final_deg"]),
            "fell": bool(r["stability"]["fell"]),
            "fell_at_s": r["stability"].get("fell_at_s"),
            "dx_body": float(r["displacement"]["dx_body"]),
            "gates_failed": list(r.get("failed") or []),
        }
        out.setdefault(key, []).append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patterns", nargs="+", help="globs of rehearse JSONs")
    ap.add_argument("--group-by", default="kp_fw", choices=["kp_fw", "condition"])
    ap.add_argument("--baseline", default=None,
                    help="group key to compare every other group against")
    ap.add_argument("--json", default=None, help="write the summary here")
    a = ap.parse_args(argv)

    paths: list[str] = []
    for pat in a.patterns:
        hits = sorted(globmod.glob(pat))
        if not hits:
            print(f"⚠️  no match: {pat}")
        paths.extend(hits)
    if not paths:
        raise SystemExit("no input JSONs")

    cells = _cells(paths, a.group_by)
    rows = []
    for key in sorted(cells, key=lambda k: float(k) if re.match(r"^[\d.]+$", k) else k):
        recs = cells[key]
        vx = [r["vx"] for r in recs if not r["fell"]]
        he = [r["heading_err_abs"] for r in recs if not r["fell"]]
        falls = [r for r in recs if r["fell"]]
        dxneg = [r for r in recs if not r["fell"] and r["dx_body"] <= 0.02]
        row = {
            "group": key,
            "n": len(recs),
            "n_valid": len(vx),
            "falls": len(falls),
            "vx_mean": st.mean(vx) if vx else float("nan"),
            "vx_sem": st.stdev(vx) / math.sqrt(len(vx)) if len(vx) > 1 else 0.0,
            "vx_range": [min(vx), max(vx)] if vx else None,
            "herr_abs_mean": st.mean(he) if he else float("nan"),
            "herr_abs_sem": st.stdev(he) / math.sqrt(len(he)) if len(he) > 1 else 0.0,
            "herr_abs_range": [min(he), max(he)] if he else None,
            "herr_signed_mean": st.mean([r["heading_err"] for r in recs if not r["fell"]])
            if he else float("nan"),
            "dx_body_negative": len(dxneg),
        }
        rows.append(row)

    base = next((r for r in rows if r["group"] == a.baseline), None) if a.baseline else None
    if base is not None:
        bvx = [r["vx"] for r in cells[base["group"]] if not r["fell"]]
        bhe = [r["heading_err_abs"] for r in cells[base["group"]] if not r["fell"]]
        for r in rows:
            gvx = [x["vx"] for x in cells[r["group"]] if not x["fell"]]
            ghe = [x["heading_err_abs"] for x in cells[r["group"]] if not x["fell"]]
            t, dof = _welch_t(gvx, bvx)
            r["vx_vs_base_pct"] = (
                (r["vx_mean"] / base["vx_mean"] - 1.0) * 100.0
                if base["vx_mean"] else float("nan")
            )
            r["vx_t_vs_base"] = t
            r["vx_t_dof"] = dof
            t2, dof2 = _welch_t(ghe, bhe)
            r["herr_t_vs_base"] = t2
            r["herr_t_dof"] = dof2

    hdr = f"{a.group_by:>8} {'n':>2} {'fall':>4} | {'vx':>8} {'sem':>6} | {'|err|deg':>9} {'sem':>5} | vs base"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        extra = ""
        if base is not None and r["group"] != base["group"]:
            extra = (f"{r['vx_vs_base_pct']:+6.1f}%  t={r['vx_t_vs_base']:+5.2f} "
                     f"(herr t={r['herr_t_vs_base']:+5.2f})")
        elif base is not None:
            extra = "baseline"
        print(f"{r['group']:>8} {r['n']:>2} {r['falls']:>4} | "
              f"{r['vx_mean']:8.4f} {r['vx_sem']:6.4f} | "
              f"{r['herr_abs_mean']:9.2f} {r['herr_abs_sem']:5.2f} | {extra}")

    bad = sum(r["dx_body_negative"] for r in rows)
    if bad:
        print(f"\n⚠️  {bad} non-fallen runs have dx_body <= 0.02 — net displacement along the "
              "initial heading is NOT a forward-motion test once the heading loop turns the "
              "robot; those runs' `moves_forward` gate FAILs are expected, not real failures.")

    if a.json:
        p = pathlib.Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"rows": rows, "baseline": a.baseline,
                                 "per_run": cells}, indent=1), encoding="utf-8")
        print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
