#!/usr/bin/env bash
# DuckEMW 拔河红蓝策略训练管线（AutoDL 4090D）
# 用法（实例上）：nohup bash /root/autodl-tmp/run_tug.sh > /root/autodl-tmp/run_tug.log 2>&1 &
# 阶段：smoke ×2 -> 2000 快试 ×2 -> (人工评估后) 4000 正式 ×2
# 断点：logs/tug/completed.tsv 记录已完成阶段，重跑自动跳过。
set -uo pipefail

REPO=${REPO:-/root/autodl-tmp/microduck-playground}
BRANCH=${BRANCH:-tug-of-war}
MODE=${MODE:-trial}        # trial=2000 快试；final=4000 正式；smoke=只冒烟
TAG_PREFIX=${TAG_PREFIX:-}  # 配方迭代轮次前缀（如 v2-），避免 completed.tsv 跳过
ENVS=${ENVS:-4096}
export WANDB_MODE=${WANDB_MODE:-offline}

cd "$REPO"
# 代码由本地 rsync 同步（实例的 origin 是上游 Vottivott，且 GitHub 直连慢），
# 不走 git；要启用 git 同步设 SYNC_GIT=1。
if [ "${SYNC_GIT:-0}" = "1" ]; then
  git fetch origin && git checkout "$BRANCH" && git pull --ff-only origin "$BRANCH"
fi
uv sync

DONE=logs/tug/completed.tsv
mkdir -p logs/tug && touch "$DONE"

run() { # <tag> <task_id> <iters> <envs>
  local tag=$1 task=$2 iters=$3 envs=$4
  if grep -q "^$tag" "$DONE"; then echo "==> skip $tag (done)"; return 0; fi
  echo "==> $(date '+%F %T') start $tag ($task, $iters iters, $envs envs)"
  uv run train "$task" --env.scene.num-envs "$envs" --agent.max_iterations "$iters" \
    >> "logs/tug/${tag}.log" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then echo "$tag" >> "$DONE"; echo "==> $(date '+%F %T') done $tag"; \
  else echo "==> $(date '+%F %T') FAILED $tag rc=$rc (见 logs/tug/${tag}.log)"; fi
  return $rc
}

run "${TAG_PREFIX}smoke-steady"  Mjlab-Microduck-Tug-Steady  5    64  || exit 1
run "${TAG_PREFIX}smoke-shuffle" Mjlab-Microduck-Tug-Shuffle 5    64  || exit 1
[ "$MODE" = smoke ] && exit 0

if [ "$MODE" = trial ]; then
  run "${TAG_PREFIX}trial-steady"  Mjlab-Microduck-Tug-Steady  2000 "$ENVS" || exit 1
  run "${TAG_PREFIX}trial-shuffle" Mjlab-Microduck-Tug-Shuffle 2000 "$ENVS" || exit 1
else
  run "${TAG_PREFIX}final-steady"  Mjlab-Microduck-Tug-Steady  4000 "$ENVS" || exit 1
  run "${TAG_PREFIX}final-shuffle" Mjlab-Microduck-Tug-Shuffle 4000 "$ENVS" || exit 1
fi
echo "==> $(date '+%F %T') pipeline finished (mode=$MODE)"
