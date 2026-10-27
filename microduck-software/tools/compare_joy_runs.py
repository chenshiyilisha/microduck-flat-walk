"""Side-by-side gate comparison for two (or more) joy runs.

Same env cfg, same device, same duration -- the only thing that differs is the
checkpoint. Reads the `gates` block that `eval_joy_in_sim.py` already writes
(thresholds and pass flags included), so this script never restates upstream's
numbers and cannot drift from them.

Usage:
    # evaluate fresh checkpoints
    python tools/compare_joy_runs.py --run a=path/model.pt --run b=path/model.pt

    # or re-print a table from JSONs produced earlier (no GPU needed)
    python tools/compare_joy_runs.py --reuse out/cmp_a.json out/cmp_b.json

Each evaluation runs as a subprocess. Note `eval_joy_in_sim.py` exits non-zero
when any gate fails -- that is a verdict, not an error, so the presence of the
output JSON decides success here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = ROOT / ".venv-mjlab" / "Scripts" / "python.exe"
OUT_DIR = ROOT / "out"

# Extra context numbers worth printing: v is the value, wider = more decimals.
CONTEXT_FIELDS: list[tuple[str, int]] = [
    ("fell_frac", 4),
    ("joy_foot_rhythm_mean", 4),
    ("step_period_s", 3),
    ("foot_ac_rms_m", 5),
    ("knee_ac_rms_rad", 4),
    ("8hz_ratio_foot", 4),
    ("8hz_ratio_knee", 4),
    ("max_target_step_raw", 4),
    ("reset_artifact_frac", 4),
    ("~foot_support_proxy", 4),
]


def gate_value(doc: dict, key: str):
    """Return (value, pass, level, op) from the `gates` block, or Nones."""
    g = doc.get("gates", {}).get(key)
    if not isinstance(g, dict):
        return None, None, None, None
    return g.get("value"), g.get("pass"), g.get("level"), g.get("op")


def evaluate(label: str, ckpt: Path, args) -> Path | None:
    out_json = OUT_DIR / f"cmp_{label}.json"
    cmd = [
        str(PY), str(HERE / "eval_joy_in_sim.py"),
        "--checkpoint", str(ckpt),
        "--num-envs", str(args.num_envs),
        "--seconds", str(args.seconds),
        "--device", args.device,
        "--out", str(out_json),
    ]
    print(f"\n=== {label} :: {ckpt.name} ===", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in (proc.stdout or "").strip().splitlines()[-2:]:
        print("   ", line)
    if not out_json.exists():
        print(f"[fail] {label}: no JSON (exit {proc.returncode})", file=sys.stderr)
        print((proc.stderr or "")[-1500:], file=sys.stderr)
        return None
    return out_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[], metavar="LABEL=CKPT")
    ap.add_argument("--reuse", nargs="+", default=[], metavar="JSON")
    ap.add_argument("--num-envs", type=int, default=512)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--device", default="cuda:0")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    docs: dict[str, dict] = {}

    for spec in args.run:
        label, _, ckpt = spec.partition("=")
        if not ckpt:
            print(f"bad --run {spec!r}, expected LABEL=CKPT", file=sys.stderr)
            return 2
        p = evaluate(label, Path(ckpt).resolve(), args)
        if p:
            docs[label] = json.loads(p.read_text(encoding="utf-8"))

    for raw in args.reuse:
        p = Path(raw)
        if not p.exists():
            print(f"[skip] missing {p}", file=sys.stderr)
            continue
        label = p.stem.removeprefix("cmp_")
        docs[label] = json.loads(p.read_text(encoding="utf-8"))

    if not docs:
        print("nothing to compare", file=sys.stderr)
        return 1

    labels = list(docs)
    gate_keys = list(docs[labels[0]].get("gates", {}))
    w = max([len(k) for k in gate_keys] + [len("max_target_step_raw")]) + 2
    col = 15
    total = w + 16 + col * len(labels)

    print("\n" + "=" * total)
    print(f"{'gate':<{w}}{'threshold':<16}" + "".join(f"{l:>{col}}" for l in labels))
    print("-" * total)

    for k in gate_keys:
        # Threshold/op come from the first doc that has them; they are global.
        thr = op = ""
        cells = []
        for l in labels:
            v, ok, lvl, o = gate_value(docs[l], k)
            if lvl is not None:
                thr, op = f"{o} {lvl:g}", o
            cells.append(f"{'-':>{col}}" if v is None
                         else f"{v:>{col-4}.5f} {'PASS' if ok else 'FAIL'}")
        print(f"{k:<{w}}{thr:<16}" + "".join(cells))

    print("-" * total)
    for key, nd in CONTEXT_FIELDS:
        cells = []
        for l in labels:
            v = docs[l].get("context", {}).get(key)
            cells.append(f"{v:>{col}.{nd}f}" if isinstance(v, (int, float)) else f"{'-':>{col}}")
        print(f"{key:<{w}}{'':<16}" + "".join(cells))
    print("=" * total)

    for l in labels:
        failed = [k for k in gate_keys if gate_value(docs[l], k)[1] is False]
        npass = len(gate_keys) - len(failed)
        print(f"{l:<{w}} joy_passed={bool(docs[l].get('joy_passed'))}  "
              f"({npass}/{len(gate_keys)} gates)  failed: {', '.join(failed) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
