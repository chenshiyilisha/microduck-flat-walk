# SPDX-License-Identifier: Apache-2.0
"""Paired comparison of two `sweep_ckpt.py` output directories.

Why this file exists
--------------------
Every time this project compared two runs by hand, it eventually compared two
*different instruments*: 64-env numbers next to 256-env ones, an 8 s window next
to a 16 s one, a `error_vel_xy` measured before and after the resampling-window
fix. The rule that came out of it ("numbers from different eval-script versions
must never be divided") is easy to state and easy to violate with a one-off
`python -c`.

So the guard is mechanical: this script reads the instrument parameters back out
of every JSON (`num_envs`, `seconds`, `seed`, metric window, plant fingerprint)
and **refuses to print a delta** when they disagree. A pair that cannot be
compared is reported as such, instead of yielding a plausible-looking ratio.

What it compares
----------------
Rows are paired by `(iteration, cmd_vx, cmd_wz)`. For each pair it prints the
absolute numbers of both sides plus the two decision axes of the HD1910 line:
`ratio` = vx/cmd (does it go as fast as asked) and `err_xy` (does it track), with
`err_yaw`, fall rate, achieved joint amplitude and peak joint speed alongside.

Usage
-----
    # directories
    .venv-mjlab/Scripts/python.exe tools/hd1910/compare_sweeps.py \
        --a out/sweep_2026-11-02_09-28-18_p3head030_4096x2000 \
        --b out/sweep_2026-11-02_14-05-00_p3head030_ar020_4096x2000

    # or run names (resolved to out/sweep_<name>/)
    .venv-mjlab/Scripts/python.exe tools/hd1910/compare_sweeps.py \
        --a p3head030_4096x2000 --b p3head030_ar020_4096x2000 --cmd 0.30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out"


def resolve(spec: str) -> Path:
    p = Path(spec)
    if p.is_dir():
        return p
    # Sweep dirs are `out/sweep_<timestamp>_<run-name>/`, so a bare run name is a
    # suffix match, not an exact one.
    cands = sorted(OUT.glob(f"sweep_*{spec}*"))
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        raise SystemExit(
            f"ambiguous sweep for {spec!r}: {[c.name for c in cands]}; pass the directory"
        )
    raise SystemExit(f"not a sweep directory: {spec} (no out/sweep_*{spec}*)")


_LEG_PREFIX = ("left_", "right_")


def _leg_joints(jo: dict, suffix: str | None = None) -> list[dict]:
    out = []
    for p in jo.get("per_joint") or []:
        name = p.get("joint", "")
        if not name.startswith(_LEG_PREFIX):
            continue
        if suffix and not name.endswith(suffix):
            continue
        out.append(p)
    return out


def _leg_amp(jo: dict, suffix: str | None = None) -> float | None:
    """Mean p2p amplitude (deg) over matching leg joints; None if the block is absent."""
    js = _leg_joints(jo, suffix)
    vals = [p["amp_deg_median"] for p in js if p.get("amp_deg_median") is not None]
    return sum(vals) / len(vals) if vals else None


def _leg_dq(jo: dict) -> float | None:
    vals = [p["peak_vel_rad_s"] for p in _leg_joints(jo) if p.get("peak_vel_rad_s") is not None]
    return max(vals) if vals else None


def load(dirpath: Path) -> list[dict]:
    rows = []
    for f in sorted(dirpath.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        sp = d.get("speed") or {}
        om = d.get("official_metrics") or {}
        st = d.get("stability") or {}
        jo = d.get("joints") or {}
        cmd = d.get("command") or {}
        mw = d.get("metric_window") or {}
        fp = d.get("plant_fingerprint") or {}
        vx_med = sp.get("vx_median_of_env_means")
        cmd_vx = cmd.get("vx")
        rows.append(
            {
                "file": f.name,
                "ckpt": Path(d.get("checkpoint", "")).stem,
                "iter": int(Path(d.get("checkpoint", "model_0")).stem.split("_")[1]),
                "cmd": cmd_vx,
                "wz": cmd.get("wz", 0.0),
                "seed": d.get("seed"),
                "envs": d.get("num_envs"),
                "seconds": d.get("seconds"),
                "window_ok": mw.get("is_true_mean"),
                "plant": fp.get("name") or fp.get("detected"),
                "kp_fw": fp.get("kp_fw"),
                "vx": vx_med,
                "ratio": (vx_med / cmd_vx) if (vx_med is not None and cmd_vx) else None,
                "err_xy": om.get("error_vel_xy"),
                "err_yaw": om.get("error_vel_yaw"),
                "fall": (st.get("terminated_frac") or 0.0) * 100.0,
                # Leg-only aggregates. The json-wide maxima are head_yaw / neck and
                # routinely 3-5x the legs, so quoting them as "joint amplitude" reads
                # as if the legs swing 90 deg. Keep the json-wide ones as *_all.
                "knee": _leg_amp(jo, "knee"),
                "hip_pitch": _leg_amp(jo, "hip_pitch"),
                "dq_leg": _leg_dq(jo),
                "amp_all": jo.get("amp_deg_median_max"),
                "dq_all": jo.get("peak_vel_rad_s_max"),
            }
        )
    return rows


def instrument(rows: list[dict]) -> dict:
    """The parameters that make two readings comparable at all."""
    def uniq(key):
        return sorted({r[key] for r in rows}, key=lambda v: (v is None, v))

    return {
        "envs": uniq("envs"),
        "seconds": uniq("seconds"),
        "seed": uniq("seed"),
        "plant": uniq("plant"),
        "kp_fw": uniq("kp_fw"),
        "window_ok": uniq("window_ok"),
    }


def fmt(x, nd=3, suf=""):
    return "n/a" if x is None else f"{x:.{nd}f}{suf}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", required=True, help="baseline sweep dir or run name")
    ap.add_argument("--b", required=True, help="variant sweep dir or run name")
    ap.add_argument("--cmd", type=float, default=None,
                    help="only rows whose cmd_vx equals this (e.g. 0.30)")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    a = ap.parse_args()

    da, db = resolve(a.a), resolve(a.b)
    ra, rb = load(da), load(db)
    if not ra or not rb:
        raise SystemExit(f"empty sweep: {da} ({len(ra)} rows), {db} ({len(rb)} rows)")

    ia, ib = instrument(ra), instrument(rb)
    print(f"A = {a.label_a}  ({da.name}, {len(ra)} readings)")
    print(f"B = {a.label_b}  ({db.name}, {len(rb)} readings)")
    print("\n-- instrument --")
    bad = []
    for k in ia:
        same = ia[k] == ib[k]
        print(f"  {k:9s} A={ia[k]}  B={ib[k]}  {'ok' if same else '!! DIFFERS'}")
        if not same:
            bad.append(k)

    if a.cmd is not None:
        ra = [r for r in ra if r["cmd"] is not None and abs(r["cmd"] - a.cmd) < 1e-9]
        rb = [r for r in rb if r["cmd"] is not None and abs(r["cmd"] - a.cmd) < 1e-9]

    keyed = {}
    for tag, rows in (("A", ra), ("B", rb)):
        for r in rows:
            keyed.setdefault((r["iter"], round(r["cmd"] or 0, 6), round(r["wz"] or 0, 6)), {})[tag] = r

    if bad:
        print(f"\n!! refusing to print deltas: instrument differs in {bad}")
        print("   (absolute rows below; do NOT divide across these two columns)")

    hdr = (f"{'iter':>5} {'cmd':>5} | {'vx A':>6} {'vx B':>6} {'dvx%':>6} | "
           f"{'ratio A':>7} {'ratio B':>7} | {'err A':>6} {'err B':>6} | "
           f"{'yaw A':>6} {'yaw B':>6} | {'fall A':>6} {'fall B':>6} | "
           f"{'knee A':>6} {'knee B':>6} | {'dq A':>5} {'dq B':>5}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for key in sorted(keyed):
        it, cmd, wz = key
        A, B = keyed[key].get("A"), keyed[key].get("B")
        if A is None or B is None:
            have = A or B
            side = "A only" if A else "B only"
            print(f"{it:>5} {cmd:>5.2f} | {side}: vx {fmt(have['vx'])} "
                  f"ratio {fmt(have['ratio'], 2)} err {fmt(have['err_xy'])}")
            continue
        dvx = (100.0 * (B["vx"] - A["vx"]) / A["vx"]) if (A["vx"] and B["vx"]) else None
        print(f"{it:>5} {cmd:>5.2f} | {fmt(A['vx']):>6} {fmt(B['vx']):>6} "
              f"{fmt(dvx, 1, '%'):>6} | "
              f"{fmt(A['ratio'], 2):>7} {fmt(B['ratio'], 2):>7} | "
              f"{fmt(A['err_xy'], 3):>6} {fmt(B['err_xy'], 3):>6} | "
              f"{fmt(A['err_yaw'], 3):>6} {fmt(B['err_yaw'], 3):>6} | "
              f"{fmt(A['fall'], 1):>6} {fmt(B['fall'], 1):>6} | "
              f"{fmt(A['knee'], 1):>6} {fmt(B['knee'], 1):>6} | "
              f"{fmt(A['dq_leg'], 2):>5} {fmt(B['dq_leg'], 2):>5}")

    print("\nreading: ratio = vx/cmd is the speed axis; err_xy the tracking axis; "
          "fall%% >= 3 means unusable regardless of speed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
