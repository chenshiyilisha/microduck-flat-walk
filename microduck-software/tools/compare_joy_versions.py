"""Tabulate every joy acceptance report in `out/eval_*.json` side by side.

The project has accumulated ~10 acceptance JSONs across reward versions. Reading
them by hand has already caused two mistakes: quoting a value from the wrong run
and comparing a metric measured under a different plant. This script prints one
row per report with the gate values and the context that makes them comparable
(plant, play cfg, env count, duration), and marks which rows are apples-to-apples.

    .venv-mjlab/Scripts/python.exe tools/compare_joy_versions.py
    .venv-mjlab/Scripts/python.exe tools/compare_joy_versions.py --extra out/eval_clock_599.json
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Gate thresholds are part of the contract, not a display detail.
GATES = {
    "feet_peak_m": (">", 0.008),
    "pose_power_above_8hz_ratio": ("<", 0.010),
    "min_upright": (">", 0.900),
    "target_rate_rms": ("<=", 3.500),
    "drift_m": ("<", 0.150),
}
COLUMNS = [
    ("feet_peak_left_m", 4),
    ("feet_peak_right_m", 4),
    ("feet_peak_m", 4),
    ("knee_ac_rms_rad", 3),
    ("pose_power_above_8hz_ratio", 5),
    ("target_rate_rms", 3),
    ("min_upright", 4),
    ("drift_m", 4),
    ("fell_frac", 3),
]


def coerce(v):
    """Reports written by older versions nest the number under 'value'."""
    if isinstance(v, dict):
        for k in ("value", "val", "v"):
            if k in v:
                return v[k]
        return None
    return v


def evaluate(name: str, value: float) -> bool | None:
    if name not in GATES or value is None:
        return None
    op, thr = GATES[name]
    if op == ">":
        return value > thr
    if op == "<":
        return value < thr
    if op == "<=":
        return value <= thr
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[], help="additional report paths")
    ap.add_argument("--sort", default="mtime", choices=["mtime", "name"])
    args = ap.parse_args()

    paths = [pathlib.Path(p) for p in args.extra]
    paths += [pathlib.Path(p) for p in glob.glob(str(ROOT / "out" / "eval_*.json")) if p not in args.extra]
    paths = [p for p in paths if p.exists()]
    if args.sort == "mtime":
        paths.sort(key=lambda p: p.stat().st_mtime)

    rows = []
    for p in paths:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # a half-written report should not kill the table
            print(f"  ! {p.name}: unreadable ({e})")
            continue
        gates = d.get("gates", {}) or {}
        ctx = d.get("context", {}) or {}
        # Per-foot / per-env detail lives in `context`, the headline gates in
        # `gates`. Merge them, and give drift its reported name.
        merged = {**ctx, **gates}
        if "max_drift_m" in gates:
            merged["drift_m"] = gates["max_drift_m"]
        plant = d.get("plant", {}) or {}
        rows.append(
            {
                "file": p.name,
                "ckpt": pathlib.Path(str(d.get("checkpoint", "?"))).name,
                "plant": str(plant.get("actuators", "?"))[:22],
                "envs": d.get("num_envs"),
                "secs": d.get("seconds"),
                "values": {k: coerce(merged.get(k)) for k, _ in COLUMNS},
                "passed": d.get("joy_passed"),
                "reset_art": coerce(ctx.get("reset_artifact_frac")),
            }
        )

    # Column widths
    head = f"{'report':<26}{'ckpt':<12}{'plant':<24}{'envs':>5}{'s':>5}"
    for k, _ in COLUMNS:
        head += f"{k[:13]:>15}"
    head += f"{'gate':>7}"
    print(head)
    print("-" * len(head))

    for r in rows:
        line = f"{r['file'][:25]:<26}{r['ckpt']:<12}{r['plant']:<24}{str(r['envs']):>5}{str(r['secs']):>5}"
        for k, nd in COLUMNS:
            v = r["values"].get(k)
            if v is None:
                line += f"{'-':>15}"
                continue
            mark = ""
            ok = evaluate(k, float(v))
            if ok is True:
                mark = ""
            elif ok is False:
                mark = "!"
            line += f"{float(v):>14.{nd}f}{mark}"
        line += f"{str(r['passed']):>7}"
        print(line)

    print("\n'!' marks a value that misses its gate threshold:")
    for k, (op, thr) in GATES.items():
        print(f"  {k} {op} {thr}")

    # Flag rows whose evaluation setting is not comparable: reset artefacts make
    # feet_peak meaningless (episode dies before the foot can lift).
    bad = [r for r in rows if (r["reset_art"] or 0) > 0.2 or (r["secs"] or 0) < 2]
    if bad:
        print("\nNOT comparable (short episode or heavy reset artefacts):")
        for r in bad:
            print(f"  {r['file']}: {r['secs']}s, reset_artifact_frac={r['reset_art']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
