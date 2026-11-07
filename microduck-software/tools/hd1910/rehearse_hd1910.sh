#!/usr/bin/env bash
# HD1910 deploy rehearsal — C-prep deploy gate, sim only.
#
# Default ONNX is the m5-line explore policy; PLANT defaults to m5 so the default
# invocation rehearses that policy AT ITS OWN PLANT (no cross-plant mismatch — the
# wrapper now refuses those loudly). Override both for a kp8 deploy gate:
#   ONNX=out/hd1910_resume_4096_to6000_1027_it5999.onnx PLANT=p8 ./rehearse_hd1910.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ONNX="${ONNX:-out/hd1910_explore_4096x2000_1026_it1999.onnx}"
PLANT="${PLANT:-m5}"
OUT="${OUT:-out/rehearse_${PLANT}_$(basename "$ONNX" .onnx).json}"

test -f "$ONNX" || { echo "missing $ONNX"; exit 1; }

# Default: full DR sweep at the policy's own plant. Override with e.g.
# ARGS='--condition nominal --seconds 4'
ARGS="${ARGS:---sweep --cmd-vx 0.4 --seconds 8}"
# shellcheck disable=SC2086
"$PY" tools/hd1910/rehearse_hd1910.py --onnx "$ONNX" --plant "$PLANT" --out "$OUT" $ARGS "$@"
echo "rehearse json -> $OUT"
