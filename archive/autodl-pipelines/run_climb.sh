#!/usr/bin/env bash
# desk-climb 爬梯复现管线（AutoDL 4090D，实例端执行器）
# 用法（实例上）：nohup env MODE=eval bash /root/autodl-tmp/run_climb.sh > /root/autodl-tmp/run_climb.log 2>&1 &
# 阶段：setup -> smoke ×2 -> evaluate 基线 -> climber 250 -> getup 128
# 断点：logs/climb/completed.tsv 记录已完成阶段，重跑自动跳过（改配方请换 TAG_PREFIX）。
set -uo pipefail

PKG=${PKG:-/root/autodl-tmp/desk-climb}
MODE=${MODE:-all}         # smoke=只冒烟；eval=到基线评估；all=续训也跑
TAG_PREFIX=${TAG_PREFIX:-}
export WANDB_MODE=${WANDB_MODE:-offline}
export UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export PATH=/root/.local/bin:/root/miniconda3/bin:$PATH

cd "$PKG/source"
DONE="$PKG/logs/climb/completed.tsv"
mkdir -p "$PKG/logs/climb" && touch "$DONE"

step() { # <tag> <cmd...> —— 带断点和计时的阶段执行器
  local tag=$1; shift
  if grep -q "^${TAG_PREFIX}$tag\$" "$DONE"; then echo "==> skip ${TAG_PREFIX}$tag (done)"; return 0; fi
  echo "==> $(date '+%F %T') start ${TAG_PREFIX}$tag"
  local t0=$SECONDS
  "$@" >> "$PKG/logs/climb/${TAG_PREFIX}${tag}.log" 2>&1
  local rc=$?
  local dt=$((SECONDS - t0))
  if [ $rc -eq 0 ]; then
    echo "${TAG_PREFIX}$tag" >> "$DONE"
    echo "==> $(date '+%F %T') done ${TAG_PREFIX}$tag (${dt}s)"
  else
    echo "==> $(date '+%F %T') FAILED ${TAG_PREFIX}$tag rc=$rc (${dt}s, 见 logs/climb/${TAG_PREFIX}${tag}.log)"
  fi
  return $rc
}

# 一次性环境准备：锁定依赖 + 下载模型(sha256 自校验) + 修上游残留
if ! grep -q "^${TAG_PREFIX}setup\$" "$DONE"; then
  echo "==> $(date '+%F %T') setup: uv sync --frozen + download_models + 路径修补"
  uv sync --frozen >> "$PKG/logs/climb/${TAG_PREFIX}setup.log" 2>&1 \
    || { echo "==> setup: uv sync FAILED (见 logs/climb/${TAG_PREFIX}setup.log)"; exit 1; }
  uv run ../training/download_models.py >> "$PKG/logs/climb/${TAG_PREFIX}setup.log" 2>&1 \
    || { echo "==> setup: model download FAILED (见 logs/climb/${TAG_PREFIX}setup.log)"; exit 1; }
  # 原开发机残留的硬编码 bank 路径 → 包内 training/balanced-bank.json（纯路径修复，不改配方）
  sed -i "s|/scratch/floor-desk/desk-recovery-training/balanced-bank.json|$PKG/training/balanced-bank.json|g" \
    src/mjlab_microduck/tasks/mdp.py
  # run.py 的 env.update 会无条件覆盖外部环境变量；给消融旋钮留门（默认仍是官方值）
  sed -i \
    -e "s|TRIGGER_MODE='supported_root'|TRIGGER_MODE=os.environ.get('TRIGGER_MODE','supported_root')|" \
    -e "s|SWITCH_MAX_SPIN='999'|SWITCH_MAX_SPIN=os.environ.get('SWITCH_MAX_SPIN','999')|" \
    -e "s|RECOVERY_MIN_ROOT_Z='.74'|RECOVERY_MIN_ROOT_Z=os.environ.get('RECOVERY_MIN_ROOT_Z','.74')|" \
    ../training/run.py
  echo "${TAG_PREFIX}setup" >> "$DONE"
  echo "==> $(date '+%F %T') setup done"
fi

step smoke-climber uv run ../training/run.py climber --envs 64 --iterations 5 --out /tmp/climber-smoke || exit 1
step smoke-getup   uv run ../training/run.py getup   --envs 64 --iterations 5 --out /tmp/getup-smoke   || exit 1
[ "$MODE" = smoke ] && { echo "==> MODE=smoke, stop here"; exit 0; }

step eval-baseline uv run ../training/run.py evaluate --envs 64 --seconds 60 --seed 19923 --out "$PKG/logs/desk-eval" || exit 1
[ "$MODE" = eval ] && { echo "==> MODE=eval, stop here"; exit 0; }

step train-climber uv run ../training/run.py climber --envs 1024 --iterations 250 --seed 233 --out "$PKG/logs/desk-climber" || exit 1
step train-getup   uv run ../training/run.py getup   --envs 1024 --iterations 128 --out "$PKG/logs/desk-getup" || exit 1
echo "==> $(date '+%F %T') pipeline finished (mode=$MODE)"
