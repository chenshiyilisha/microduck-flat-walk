#!/usr/bin/env bash
# Phase 4a: 切换触发消融电池（实例端）。用法: bash phase4a_triggers.sh
# 基座组合 = 续训 climber(final.pt) + 官方 getup.onnx；每组 4 seeds × 64 envs × 60s
set -uo pipefail
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/desk-climb/source
SRC=../logs/desk-climber/final.pt

run_battery() { # <name> <extra env assignments...>
  local name=$1; shift
  for s in 19723 19823 19923 20023; do
    env "$@" uv run ../training/run.py evaluate --source "$SRC" --envs 64 --seconds 60 \
      --seed "$s" --out "../logs/eval-${name}-s${s}" > "../logs/climb/eval-${name}-s${s}.log" 2>&1
    echo "$name $s rc=$?"
  done
}

run_battery trig-root050  TRIGGER_MODE=root050
run_battery trig-bothfeet TRIGGER_MODE=both_feet
run_battery trig-spin2    SWITCH_MAX_SPIN=2.0
echo "phase4a done"
