#!/usr/bin/env bash
# Rehearsal sweeps that produced docs/05-flat-walk.md §22 (kp plateau) and §23
# (command envelope). One script because both are "one variable x n start yaws"
# over the same instrument, and because both need the same readback guard.
#
# Why a script and not a documented one-liner
# -------------------------------------------
# The failure mode this guards against is the one we hit three times in a row on
# this project: a sweep that *looks* like it varied a parameter but didn't.
#   - `apply_to_live.py` counted matches outside the kwargs block (§10)
#   - `--delay-lag` fired on `pd_actuators`' same-named key
#   - the `SECONDS` builtin made 16 rehearsals run for 0 s
# So after every sweep this script reads back `settings.kp_fw` (and the command,
# from the directory name) out of each JSON and FAILS if the effective value is
# not what was asked for. A sweep that silently reused one plant would otherwise
# produce a perfectly plausible table — exactly what §22.1 would have hidden if
# kp=4..12 had all been the same plant.
#
# Usage
# -----
#   ONNX=logs/rsl_rl/.../run.onnx bash tools/hd1910/sweep_envelope.sh kp
#   ONNX=logs/rsl_rl/.../run.onnx bash tools/hd1910/sweep_envelope.sh cmd
#
# Env:
#   ONNX     policy to sweep (required; no default — a stale graph is a silent trap)
#   YAW      space-separated start yaws        (default "0 90 180 270")
#   DUR      seconds per run                   (default 8)
#   PLANT    rehearsal plant key               (default p8)
#   TAG      output dir name                   (default sweep_<mode>)
#   FORCE=1  redo runs instead of skipping existing JSONs
#
# ⚠️ DUR, not SECONDS: SECONDS is a bash builtin (seconds since shell start), so
# `${SECONDS:-8}` reads 0 at startup and every run becomes 0 s long.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe

MODE="${1:-}"
case "$MODE" in
  kp)  VALUES="4 6 7 8 9 10 12"; PLANTS_PLANT="${PLANT:-p8}" ;;
  cmd) VALUES="0.00 0.10 0.15 0.20 0.30 0.40 0.50 0.60"; PLANTS_PLANT="${PLANT:-p8}" ;;
  *) echo "usage: ONNX=<path> $0 kp|cmd" >&2; exit 2 ;;
esac

: "${ONNX:?set ONNX to the exported policy (no default: a stale graph is a silent trap)}"
YAW="${YAW-0 90 180 270}"
DUR="${DUR-8}"
PLANT="$PLANTS_PLANT"
TAG="${TAG-sweep_$MODE}"
OUT="out/$TAG"

[ -f "$ONNX" ] || { echo "ONNX not found: $ONNX" >&2; exit 2; }

# Guard 1: refuse an untrained graph (smoke / aborted run's iter-0 export looks fine).
"$PY" -c "
import sys, pathlib
sys.path.insert(0,'tools'); sys.path.insert(0,'tools/hd1910')
import rehearse_hd1910 as r
p = pathlib.Path(r'''$ONNX''')
ck, it = r._onnx_companion(p)
if it < r.MIN_TRAINED_ITER:
    sys.exit(f'FAIL: companion ckpt iter {it} < {r.MIN_TRAINED_ITER}; not a trained policy')
print(f'onnx {p.name}  ckpt {ck.name if ck else \"<none>\"}  iter {it}')
" || exit 2

mkdir -p "$OUT"
echo "== sweep $MODE: plant=$PLANT values=[$VALUES] yaws=[$YAW] dur=${DUR}s -> $OUT =="

for V in $VALUES; do
  D="$OUT/$V"
  mkdir -p "$D"
  for Y in $YAW; do
    F="$D/y${Y}.json"
    if [ -f "$F" ] && [ "${FORCE:-0}" != "1" ]; then continue; fi
    if [ "$MODE" = kp ]; then
      # Same plant preset, different firmware P: --kp-fw is what actually moves.
      "$PY" tools/hd1910/rehearse_hd1910.py --plant "$PLANT" --onnx "$ONNX" \
        --kp-fw "$V" --yaw-deg "$Y" --heading-target-deg 0 --cmd-vx 0.4 \
        --seconds "$DUR" --out "$F" --quiet > "$D/y${Y}.log" 2>&1 || true
    else
      "$PY" tools/hd1910/rehearse_hd1910.py --plant "$PLANT" --onnx "$ONNX" \
        --kp-fw 8 --yaw-deg "$Y" --heading-target-deg 0 --cmd-vx "$V" \
        --seconds "$DUR" --out "$F" --quiet > "$D/y${Y}.log" 2>&1 || true
    fi
  done
  echo "   $MODE=$V done"
done

# Guard 2: read back what the runs actually used, then summarize. Exit nonzero on
# any mismatch — a table built from the wrong plant is worse than no table.
"$PY" - "$OUT" "$MODE" "$VALUES" "$YAW" <<'PY'
import glob, json, math, os, statistics as st, sys

out, mode, values, yaws = sys.argv[1], sys.argv[2], sys.argv[3].split(), sys.argv[4].split()
want_kp = 8.0 if mode == "cmd" else None
bad = []

def runs(v):
    return [json.load(open(f))["runs"][0] for f in sorted(glob.glob(os.path.join(out, v, "*.json")))]

for v in values:
    got = set()
    for f in sorted(glob.glob(os.path.join(out, v, "*.json"))):
        got.add((json.load(open(f))["runs"][0].get("settings") or {}).get("kp_fw"))
    expect = float(v) if mode == "kp" else want_kp
    if expect is not None and got != {expect}:
        bad.append(f"{v}: settings.kp_fw={sorted(got, key=lambda x: (x is None, x))} != {expect}")
    n = len(glob.glob(os.path.join(out, v, "*.json")))
    if n != len(yaws):
        bad.append(f"{v}: {n} runs, expected {len(yaws)}")

if bad:
    print("FAIL readback:", *bad, sep="\n  ")
    sys.exit(3)

print(f"\n{'value':>6} {'n':>2} {'fall':>4} {'vx':>8} {'sem':>7} {'abs(err)':>9}"
      f"{'  ratio' if mode == 'cmd' else ''}")
for v in values:
    rs = runs(v)
    vx = [r["speed"]["vx_mean_steady"] for r in rs
          if (r.get("speed") or {}).get("vx_mean_steady") is not None
          and not (r.get("stability") or {}).get("fell")]
    err = [abs(r["heading"]["heading_error_final_deg"]) for r in rs
           if (r.get("heading") or {}).get("heading_error_final_deg") is not None]
    fell = sum(1 for r in rs if (r.get("stability") or {}).get("fell"))
    m = st.mean(vx) if vx else float("nan")
    # n<2 has no dispersion; printing 0.0000 would read as "very precise".
    sem = st.stdev(vx) / math.sqrt(len(vx)) if len(vx) > 1 else float("nan")
    c = float(v)
    fmt = lambda x, w, p: (f"{x:{w}.{p}f}" if x == x else f"{'n/a':>{w}}")
    line = (f"{v:>6} {len(rs):>2} {fell:>4} {fmt(m, 8, 4)} {fmt(sem, 7, 4)} "
            f"{fmt(st.mean(err) if err else float('nan'), 9, 2)}")
    # ratio is vx/cmd and only defined for the command sweep; in kp mode the
    # "value" is a gain, so dividing by it produces a meaningless 0.03.
    if mode == "cmd":
        line += f"  {fmt(m / c if c > 0 and vx else float('nan'), 6, 2)}"
    print(line)
print("\nvx excludes falling runs (a fall's vx is not a speed measurement).")
PY
