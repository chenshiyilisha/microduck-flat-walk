"""Watch a joy run as it trains: does joy_feet actually climb, or is it flat again?

Why this exists
---------------
The gates in tools/eval_joy_in_sim.py need a finished checkpoint, so the first
honest answer about whether a config change worked only arrives an hour later.
But the one number that tells the story is already in the tfevents stream:
`Episode_Reward/joy_feet`.

Measured reference points for that scalar (tools/analyze_joy_feet_floor.py,
numerical integration over the real 0.1 mm standing foot height):
    standing still, zero command  ~4.43 / 12
    full commanded swing         ~11.95 / 12
So "did this fix work" reduces to one question: does joy_feet leave ~4.4 and
head for ~12, or does it sit on the 4.4 floor.

We report the value at several checkpoints plus the slope over the last third,
because a curve that rose and then decayed is a different failure from one that
never moved.

Usage:
    python tools/watch_joy_run.py                    # newest run under logs/
    python tools/watch_joy_run.py --run 0757 --run std012
    python tools/watch_joy_run.py --points 10          # 10 sample rows

Exit code is always 0 -- this is an observer, not a gate.
"""

from __future__ import annotations

import argparse
import glob
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs" / "rsl_rl"

WATCH = [
    "Episode_Reward/joy_feet",
    "Policy/mean_std",
    "Loss/entropy",
    "Episode_Reward/joy_balance",
    "Episode_Termination/fell_over",
    "Train/mean_reward",
]

STAND = 4.43   # joy_feet of a standing-still policy, numerically integrated
FULL = 11.95   # joy_feet of a full commanded swing


def find_runs(pattern: str) -> list[pathlib.Path]:
    """Newest matching run first.

    Skips stub event files (<1 KiB). A run whose process dies during startup still
    leaves a directory with an ~88-byte tfevents and no checkpoint; sorting by name
    would then pick it and report an all-empty table, which costs more time to
    diagnose than it takes to filter out here.
    """
    hits = []
    for p in LOGS.glob("**/events.out.tfevents.*"):
        if pattern.lower() not in str(p.parent).lower():
            continue
        if p.stat().st_size < 1024:
            continue
        hits.append(p)
    return sorted(hits, key=lambda p: p.stat().st_mtime)


def load(path: pathlib.Path) -> dict[str, list[tuple[int, float]]]:
    from tensorboard.backend.event_processing.event_accumulator import (
        EventAccumulator,
    )

    ea = EventAccumulator(str(path), size_guidance={"scalars": 0})
    ea.Reload()
    have = set(ea.Tags()["scalars"])
    out: dict[str, list[tuple[int, float]]] = {}
    for tag in WATCH:
        if tag in have:
            out[tag] = [(e.step, e.value) for e in ea.Scalars(tag)]
    return out


def sample(series: list[tuple[int, float]], n: int) -> list[tuple[int, float]]:
    if len(series) <= n:
        return series
    step = (len(series) - 1) / (n - 1)
    return [series[round(i * step)] for i in range(n)]


def report(name: str, data: dict[str, list[tuple[int, float]]], points: int) -> None:
    print(f"\n=== {name} ===")
    if not data:
        print("  (no watchable scalars)")
        return
    feet = data.get("Episode_Reward/joy_feet", [])
    if not feet:
        print("  (no joy_feet scalar)")
        return

    rows = sample(feet, points)
    cols = [c for c in WATCH if c in data]
    idx = {c: {s: v for s, v in data[c]} for c in cols}

    head = f"{'iter':>6}" + "".join(f"{c.split('/')[-1]:>14}" for c in cols)
    print(head)
    for it, _ in rows:
        line = f"{it:>6}"
        for c in cols:
            v = idx[c].get(it)
            line += f"{v:>14.4f}" if v is not None else f"{'-':>14}"
        print(line)

    # slope over the last third, and distance off the standing floor
    third = max(1, len(feet) // 3)
    a, b = feet[-third][1], feet[-1][1]
    lo = min(v for _, v in feet)
    hi = max(v for _, v in feet)
    first = feet[0][1]
    print(
        f"  joy_feet: first {first:.3f} -> last {b:.3f} | "
        f"min {lo:.3f} max {hi:.3f} | last-third slope {(b - a):+.3f}"
    )
    print(
        f"  vs reference: standing {STAND:.2f}, full swing {FULL:.2f}  "
        f"=> last is {100 * (b - STAND) / (FULL - STAND):+.1f}% of the way off the floor"
    )
    if b - STAND < 0.5:
        print("  VERDICT: still on the standing floor -- the foot-lift reward is not being earned")
    elif b - a > 0.05:
        print("  VERDICT: climbing")
    else:
        print("  VERDICT: above the floor but the last third is flat -- may have plateaued")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[], help="substring of the run dir name")
    ap.add_argument("--points", type=int, default=8)
    args = ap.parse_args()

    patterns = args.run or [""]
    found = False
    for pat in patterns:
        runs = find_runs(pat)
        if not runs:
            print(f"\n=== {pat or '(newest)'} ===\n  no runs matched")
            continue
        # newest match per pattern
        found = True
        p = runs[-1]
        report(p.parent.name, load(p), args.points)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
