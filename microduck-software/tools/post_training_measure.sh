#!/usr/bin/env bash
# Run the two measurements that need the GPU to themselves, once std012 finishes.
#
# Both would be corrupted by contention (that is the whole finding of the 5 fps
# investigation), and both are the evidence for the next decision, so they are
# chained here instead of being run by hand at the right moment:
#
#   1. profile_joy_viewer_step.py  -> how fast the 3D viewer *would* run on an
#      idle GPU, i.e. the number that says whether "wait until training ends"
#      is a real fix or just an assumption.
#   2. trace_joy_foot_phase.py     -> target vs commanded vs actual foot height
#      over a gait cycle, which separates "policy never asks to lift" from
#      "hardware refuses the lift" from "lifted but out of phase".
#
# Usage: bash tools/post_training_measure.sh [run_tag] [total_iters]
set -u
cd "$(dirname "$0")/.."

RUN_TAG="${1:-std012}"
TOTAL="${2:-600}"
LOG="out/train_joy_smooth_2048x600_1024_${RUN_TAG}.log"
PY=".venv-mjlab/Scripts/python.exe"

echo "[wait] $LOG -> $TOTAL iterations"
for _ in $(seq 1 240); do
  n=$(grep -c "Learning iteration" "$LOG" 2>/dev/null || echo 0)
  if [ "$n" -ge "$TOTAL" ]; then
    echo "[wait] reached $n iterations"
    break
  fi
  sleep 15
done

if [ "$(grep -c 'Learning iteration' "$LOG" 2>/dev/null || echo 0)" -lt "$TOTAL" ]; then
  echo "[wait] timeout, not measuring"
  exit 1
fi

# Let the last checkpoint flush and the CUDA context tear down.
sleep 30

CKPT=$(ls -1t logs/rsl_rl/microduck_joy_smooth/*"$RUN_TAG"*/model_*.pt 2>/dev/null | head -1)
if [ -z "${CKPT:-}" ]; then
  echo "[error] no checkpoint for $RUN_TAG"
  exit 1
fi
echo "[ckpt] $CKPT"

echo "=== 1/2 viewer step cost, idle GPU ==="
"$PY" tools/profile_joy_viewer_step.py --checkpoint "$CKPT" --num-envs 1 64 --repeat 30 \
  > out/viewer_uncontended.txt 2>&1
grep -E "^envs=|LAUNCH|compute-bound" out/viewer_uncontended.txt || tail -5 out/viewer_uncontended.txt

echo "=== 2/2 foot phase trace ==="
"$PY" tools/trace_joy_foot_phase.py --checkpoint "$CKPT" --num-envs 1 --seconds 8 \
  > out/joy_foot_phase.log 2>&1
sed -n '/valid samples/,$p' out/joy_foot_phase.log | head -20

echo "[done] out/viewer_uncontended.txt  out/joy_foot_phase.{json,png,log}"
