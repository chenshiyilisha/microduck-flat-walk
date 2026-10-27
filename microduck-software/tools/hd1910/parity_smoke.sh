#!/usr/bin/env bash
# ONNX ↔ checkpoint parity for the HD1910 4096 explore export (C-prep-4 gate).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
CKPT="${CKPT:-logs/rsl_rl/microduck_velocity_hd1910/2026-10-26_12-55-20_hd1910_explore_4096x2000_1026/model_1999.pt}"
ONNX="${ONNX:-out/hd1910_explore_4096x2000_1026_it1999.onnx}"
OUT="${OUT:-out/parity_hd1910_explore_4096x2000_1026_it1999.json}"

test -f "$CKPT" || { echo "missing $CKPT"; exit 1; }
test -f "$ONNX" || { echo "missing $ONNX"; exit 1; }

"$PY" tools/check_onnx_parity.py --checkpoint "$CKPT" --onnx "$ONNX" --out "$OUT"
echo "parity json -> $OUT"
