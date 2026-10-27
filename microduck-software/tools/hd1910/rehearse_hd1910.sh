#!/usr/bin/env bash
# HD1910 deploy rehearsal (BAM m5 / kp_fw=32) — C-prep deploy gate, sim only.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ONNX="${ONNX:-out/hd1910_explore_4096x2000_1026_it1999.onnx}"
OUT="${OUT:-out/rehearse_hd1910_explore_4096x2000_1026_it1999.json}"

test -f "$ONNX" || { echo "missing $ONNX"; exit 1; }

# Default: full DR sweep. Override with e.g. ARGS='--condition nominal --seconds 4'
ARGS="${ARGS:---sweep --cmd-vx 0.4 --seconds 8}"
# shellcheck disable=SC2086
"$PY" tools/hd1910/rehearse_hd1910.py --onnx "$ONNX" --out "$OUT" $ARGS "$@"
echo "rehearse json -> $OUT"
