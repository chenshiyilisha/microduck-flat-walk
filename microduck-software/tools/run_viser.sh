#!/usr/bin/env bash
# Launch the viser 3D viewer for a trained checkpoint.
#
# Why --device defaults to cuda (measured 2026-10-24)
# ---------------------------------------------------
# The viewer had been started with `--device cpu` on purpose (to keep the GPU
# free while training), and it reported 3 fps. Measured cause, not guessed:
#   * `nvidia-smi --query-compute-apps` listed ONLY the training pid -- the
#     viewer had no GPU allocation at all.
#   * The startup log said `Environment device | cpu`, and
#     `Module mujoco_warp._src.render_util load on device 'cpu'` -- so *rendering*
#     was on the CPU too.
#   * The viewer process burned 12 of 20 logical cores (training used 1 core).
# mujoco_warp's kernels are written for GPU. On CPU each kernel launch pays a
# dispatch cost, and this env runs 1 kHz physics with 20 substeps per control
# step, so the 3 fps is dispatch overhead, not network.
#
# Side benefit: moving the viewer to the GPU frees those 12 CPU cores, which the
# training process needs for its (much cheaper) host-side work.
#
# Usage:
#   bash tools/run_viser.sh                       # newest run, model_400, cuda
#   bash tools/run_viser.sh 0757 400 cuda         # run substring, ckpt number, device
#   bash tools/run_viser.sh std012 100 cuda
#   bash tools/run_viser.sh 0757 400 cpu          # old behaviour, for comparison
set -euo pipefail
cd "$(dirname "$0")/.."

RUNPAT="${1:-std012}"
CKPT="${2:-400}"
DEVICE="${3:-cuda}"
TASK=Mjlab-JoySmoothPD-Flat-MicroDuck

# Newest matching run directory that actually has the requested checkpoint.
# skip stub dirs: a run that died during startup leaves an ~88-byte tfevents and
# no model_*.pt, and would otherwise be picked as "newest".
# `_logstd` fallback: runs trained before the std_type log switch (0757, ar03)
# only load after tools/convert_ckpt_stdtype.py, which writes model_N_logstd.pt
# next to the original. Accept it so old baselines stay viewable.
RUN_DIR=""
CKPT_FILE=""
for d in $(ls -dt logs/rsl_rl/microduck_joy_smooth/*"$RUNPAT"* 2>/dev/null); do
  if [ -f "$d/model_${CKPT}.pt" ]; then
    RUN_DIR="$d"; CKPT_FILE="$d/model_${CKPT}.pt"; break
  fi
  if [ -f "$d/model_${CKPT}_logstd.pt" ]; then
    RUN_DIR="$d"; CKPT_FILE="$d/model_${CKPT}_logstd.pt"; break
  fi
done

if [ -z "$RUN_DIR" ]; then
  echo "no run matching '$RUNPAT' has model_${CKPT}.pt or model_${CKPT}_logstd.pt" >&2
  echo "available checkpoints:" >&2
  ls -1 logs/rsl_rl/microduck_joy_smooth/*/model_*.pt 2>/dev/null | sed 's/^/  /' | tail -12 >&2
  exit 1
fi

case "$DEVICE" in
  cuda|cuda:0) DEVFLAG=cuda:0 ;;
  cpu)         DEVFLAG=cpu ;;
  *)           DEVFLAG="$DEVICE" ;;
esac

export MJLAB_VISER_HOST="${MJLAB_VISER_HOST:-127.0.0.1}"
export MJLAB_VISER_PORT="${MJLAB_VISER_PORT:-8080}"

echo "run    $RUN_DIR"
echo "ckpt   $(basename "$CKPT_FILE")"
echo "device $DEVFLAG"
echo "url    http://${MJLAB_VISER_HOST}:${MJLAB_VISER_PORT}"

exec .venv-mjlab/Scripts/python.exe -m mjlab.scripts.play "$TASK" \
  --checkpoint-file "$CKPT_FILE" \
  --viewer viser \
  --device "$DEVFLAG" \
  --num-envs 1
