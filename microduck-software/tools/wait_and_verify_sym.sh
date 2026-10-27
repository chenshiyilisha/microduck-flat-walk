#!/usr/bin/env bash
# Wait for joy_sym_2048x600 to finish, then run the two acceptance probes back to
# back so the GPU is never idle and we never race the trainer for 8 GB of VRAM.
#
# Judgement (from microduck-joy踏步失败诊断与修法.md 19.3 / 20.6):
#   right foot rising from ~5.6 mm  -> mirror augmentation works, keep it
#   right flat AND left falling     -> augmentation averaged both sides flat
#   either way the number that decides it is the PER-FOOT swing-window peak from
#   probe_phase_profile.py, not any tensorboard scalar (joy_peak_swing_p50 is the
#   median over ALL steps, so it sits in the ramp-up段 and reads ~5 mm regardless).
set -u
cd "$(dirname "$0")/.." || exit 1

RUN=logs/rsl_rl/microduck_joy_smooth/2026-10-24_18-40-46_joy_sym_2048x600
CKPT="$RUN/model_599.pt"
LOG=out/train_joy_sym_2048x600.log

echo "[wait] $(date +%H:%M:%S) waiting for model_599.pt"
for _ in $(seq 1 180); do          # up to 30 min at 10 s
  [ -f "$CKPT" ] && break
  sleep 10
done
if [ ! -f "$CKPT" ]; then
  echo "[fail] $(date +%H:%M:%S) model_599.pt never appeared; last log lines:"
  grep -E "Learning iteration|ETA|Traceback|Error" "$LOG" | tail -5
  exit 1
fi
echo "[wait] $(date +%H:%M:%S) checkpoint found, letting the trainer exit cleanly"
sleep 25                          # trainer writes the onnx + returns after the ckpt

# --- 1) phase-resolved per-foot height: THE deciding number ------------------
echo "[probe] $(date +%H:%M:%S) probe_phase_profile"
.venv-mjlab/Scripts/python.exe tools/probe_phase_profile.py \
  --checkpoint "$CKPT" --envs 64 --seconds 6.0 \
  > out/probe_phase_sym.log 2>&1
echo "[probe] exit=$? -> out/probe_phase_sym.log"
tail -25 out/probe_phase_sym.log

# --- 2) episode-level gate readings (feet_peak_left/right, 8hz, upright) ----
echo "[gate] $(date +%H:%M:%S) eval_joy_in_sim"
.venv-mjlab/Scripts/python.exe tools/eval_joy_in_sim.py \
  --checkpoint "$CKPT" --num-envs 64 --seconds 8.0 \
  --out out/eval_joy_sym_2048x600.json \
  > out/eval_joy_sym_2048x600.log 2>&1
echo "[gate] exit=$? -> out/eval_joy_sym_2048x600.json"

echo "[done] $(date +%H:%M:%S)"
