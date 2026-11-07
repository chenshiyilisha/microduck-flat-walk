#!/usr/bin/env bash
# v11 前倾策略训练管线：每分钟抢 4090D → 确认 running → SSH → rsync → 开训
set -uo pipefail
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py
SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO_LOCAL=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground

echo "[v11] $(date '+%T') waiting for 4090D..."
while true; do
  status=$(python3 "$AUTODL" status "$INSTANCE" 2>/dev/null | grep -o '"[a-z_]*"$' | tr -d '"' || true)
  if [ "$status" = "running" ]; then echo "[v11] $(date '+%T') running"; break; fi
  if [ "$status" = "shutdown" ] || [ "$status" = "shutdown_by_starting_error" ]; then
    out=$(python3 "$AUTODL" on "$INSTANCE" 2>&1)
    grep -q '"ok": true' <<< "$out" && echo "[v11] power-on accepted" || echo "[v11] no stock, retry 1min"
  fi
  sleep 60
done

for i in $(seq 1 40); do
  $SSH "true" 2>/dev/null && { echo "[v11] ssh ready"; break; }
  sleep 15
done

rsync -az -e "ssh -p 34652" --exclude='.git' --exclude='.venv' --exclude='logs' --exclude='__pycache__' \
  "$REPO_LOCAL/src" "$REPO_LOCAL/tests" \
  root@connect.bjb2.seetacloud.com:/root/autodl-tmp/microduck-playground/ && echo "[v11] synced"

$SSH "cd /root/autodl-tmp/microduck-playground && export PATH=/root/miniconda3/bin:\$PATH && nohup bash -c 'export WANDB_MODE=offline; uv run train Mjlab-Microduck-TugChain-Steady --env.scene.num-envs 4096 --agent.max_iterations 2000 > logs/tug/v11-steady.log 2>&1 && echo ALLDONE > /root/autodl-tmp/v11.done' > /root/autodl-tmp/run_v11.log 2>&1 & sleep 20; tail -2 /root/autodl-tmp/run_v11.log 2>/dev/null; ps aux | grep -c 'train Mjlab'" || true
echo "[v11] $(date '+%T') launch issued"
