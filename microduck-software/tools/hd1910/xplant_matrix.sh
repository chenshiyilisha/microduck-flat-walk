#!/usr/bin/env bash
# 2x2 cross-plant judgment grid: {trained on P5/P8} x {rehearsed on P5/P8}.
#
# Why this exists: §18.1 showed that changing kp_fw WITHOUT retraining costs
# -13% on a P5-trained policy, i.e. "the plant is better" and "the policy fits
# the plant" are different claims and only a crossed grid separates them. One
# cell (P8-trained x P5-eval) is also the OOD check that tells us whether the
# new policy is plant-specific or just better.
#
# Each cell is n start yaws (default 8) because a single start yaw was the
# §24 false positive: yaw0=0 happened to look like a pass while n=8 gave 88 deg.
#
# Usage:
#   TRAIN_PLANT=p8 ONNX=logs/.../run.onnx bash tools/hd1910/xplant_matrix.sh
#   TRAIN_PLANT=p5 YAWS="0 90 180 270" PLANTS="p3" bash tools/hd1910/xplant_matrix.sh
#
# Env:
#   ONNX        policy to judge (default: newest *trained* export, via
#               rehearse_hd1910.resolve_latest_onnx -- guards against a smoke
#               /aborted run's iter-0 graph)
#   TRAIN_PLANT p3|p8 — which plant the policy was TRAINED on. Record only;
#               this script cannot verify it, so it is written into the
#               manifest and into every report's printout.
#   PLANTS      eval plants (default "p3 p8")
#   YAWS        start yaws (default 8 compass points)
#   DUR / CMD_VX / TARGET / COND   forwarded to the rehearsal
#   FORCE=1                        redo cells instead of skipping existing ones
# ⚠️ DUR, not SECONDS: SECONDS is a bash builtin (seconds since shell start).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe

# `${VAR-default}` (not `:-`) so an explicitly empty value really means "none".
PLANTS="${PLANTS-p3 p8}"
YAWS="${YAWS-0 45 90 135 180 225 270 315}"
# NOT $SECONDS -- that is a bash builtin counting seconds since shell start, so
# `${SECONDS:-8}` silently became 0 and every rehearsal was 0 s long.
DUR="${DUR-8}"
CMD_VX="${CMD_VX:-0.4}"
TARGET="${TARGET:-0}"
COND="${COND:-}"
TRAIN_PLANT="${TRAIN_PLANT:-?}"
EXTRA="${EXTRA:-}"

case "$TRAIN_PLANT" in
  p3|p5|P5|p8|P8|'?') ;;
  *) echo "TRAIN_PLANT must be p3/p5 or p8 (got '$TRAIN_PLANT')" >&2; exit 2 ;;
esac

ONNX="${ONNX:-}"
if [ -z "$ONNX" ]; then
  ONNX="$("$PY" -c "
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'tools/hd1910')
import rehearse_hd1910 as r
print(r.resolve_latest_onnx())
")"
fi
[ -f "$ONNX" ] || { echo "ONNX not found: $ONNX" >&2; exit 2; }

# Guard: an untrained graph would silently produce a plausible-looking cell.
"$PY" -c "
import sys, pathlib
sys.path.insert(0,'tools'); sys.path.insert(0,'tools/hd1910')
import rehearse_hd1910 as r
p = pathlib.Path(r'''$ONNX''')
ckpt, it = r._onnx_companion(p)
print(f'onnx   : {p.name}')
print(f'ckpt   : {ckpt.name if ckpt else \"<none>\"}  iter {it}')
if it < r.MIN_TRAINED_ITER:
    sys.exit(f'FAIL: companion ckpt is at iter {it} < {r.MIN_TRAINED_ITER}; '
             'this is a smoke or an aborted run, not a trained policy')
print('trained: ok')
" || exit 2

TAG="${TAG:-$(basename "$ONNX" .onnx)}"
OUT="out/xplant_${TAG}"
mkdir -p "$OUT"
echo "== xplant matrix: trained on $TRAIN_PLANT, judging $ONNX =="
echo "   outdir $OUT"

COND_FLAG=""
if [ -n "$COND" ]; then COND_FLAG="--condition $COND"; fi

for P in $PLANTS; do
  case "$P" in
    p3) KP=5 ;;
    p8) KP=8 ;;
    *) echo "unknown eval plant '$P'" >&2; exit 2 ;;
  esac
  for Y in $YAWS; do
    F="$OUT/${P}_y${Y}.json"
    if [ -f "$F" ] && [ "${FORCE:-0}" != "1" ]; then
      echo "   skip $P yaw $Y (exists; FORCE=1 to redo)"
      continue
    fi
    echo "   run  $P (kp_fw=$KP) yaw $Y"
    "$PY" tools/hd1910/rehearse_hd1910.py \
      --plant "$P" --onnx "$ONNX" --kp-fw "$KP" \
      --yaw-deg "$Y" --heading-target-deg "$TARGET" \
      --cmd-vx "$CMD_VX" --seconds "$DUR" \
      $COND_FLAG $EXTRA \
      --out "$F" --quiet > "$OUT/${P}_y${Y}.log" 2>&1 \
      || echo "   ⚠️  nonzero exit on $P yaw $Y (see $OUT/${P}_y${Y}.log)"
  done
done

"$PY" -c "
import json, pathlib
out = pathlib.Path(r'''$OUT''')
json.dump({'onnx': r'''$ONNX''', 'train_plant': '$TRAIN_PLANT',
           'eval_plants': '''$PLANTS'''.split(), 'yaws': '''$YAWS'''.split(),
           'cmd_vx': float('''$CMD_VX'''), 'seconds': float('''$DUR'''),
           'heading_target_deg': float('''$TARGET'''), 'condition': '''$COND''' or None},
          open(out/'manifest.json','w'), indent=2)
print('manifest ->', out/'manifest.json')
"

echo
echo "== summary (vx / |heading_error_final_deg| / falls; Welch t vs P5) =="
"$PY" tools/hd1910/summarize_rehearsal_grid.py "$OUT/p*_y*.json" \
  --baseline 5 --json "$OUT/summary.json" || true
