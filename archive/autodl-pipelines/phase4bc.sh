#!/usr/bin/env bash
# Phase 4b/4c: 0.66 高度门修正臂 + getup 防漂移代价臂（实例端）。用法: bash phase4bc.sh
set -uo pipefail
export PATH=/root/miniconda3/bin:$PATH
export WANDB_MODE=offline
PKG=/root/autodl-tmp/desk-climb
cd "$PKG/source"

battery() { # <name> <climber.pt> <getup-onnx-file>
  local name=$1 src=$2 gf=$3
  for s in 19723 19823 19923 20023; do
    GETUP_FILE="$gf" uv run ../training/run.py evaluate --source "$src" --envs 64 --seconds 60 \
      --seed "$s" --out "../logs/eval-${name}-s${s}" > "../logs/climb/eval-${name}-s${s}.log" 2>&1
    echo "$name $s rc=$?"
  done
}

echo "== 4b: 0.66 高度门 climber 续训 (250 iters)"
RECOVERY_MIN_ROOT_Z=.66 uv run ../training/run.py climber --envs 1024 --iterations 250 \
  --seed 233 --out ../logs/desk-climber-z66 > ../logs/climb/train-climber-z66.log 2>&1 \
  && echo "train z66 rc=0" || { echo "train z66 FAILED"; exit 1; }
battery z66 ../logs/desk-climber-z66/final.pt getup.onnx

echo "== 4c: getup 从零重训 (官方 actor + 新 critic, travel cost=1.0, 128 iters)"
PYTHONPATH="$PKG/training:$PKG/source/src" \
ENDING_ROLE=above LADDER_SHIFT=.06 RECOVERY_MIN_ROOT_Z=.74 \
uv run ../training/train_getup.py --mode train --envs 1024 --iterations 128 \
  --cost 1.0 --out ../logs/desk-getup-cost1 > ../logs/climb/train-getup-cost1.log 2>&1 \
  && echo "train getup-cost1 rc=0" || { echo "train getup-cost1 FAILED"; exit 1; }
uv run python -c "import mjlab_microduck.tasks; from scripts.export import run_export, ExportConfig; run_export('Mjlab-DeskRecoveryBlind-MicroDuck', ExportConfig(checkpoint_file='../logs/desk-getup-cost1/final.pt', onnx_file='../training/models/getup-cost1.onnx', num_envs=1, device='cuda:0'))" \
  >> ../logs/climb/train-getup-cost1.log 2>&1 && echo "export getup-cost1 rc=0" || { echo "export FAILED"; exit 1; }
battery getup-cost1 ../logs/desk-climber/final.pt getup-cost1.onnx

echo "phase4bc done"
