#!/usr/bin/env bash
# desk-climb 爬梯复现管线（本地编排器）：抢 4090D → 等 SSH → rsync → 启动实例端执行器
# 用法：MODE=eval bash autodl/run_climb_pipeline.sh   （MODE 透传给 run_climb.sh）
set -uo pipefail
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py
SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
CLIMB_LOCAL=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/experiments/desk-climb
MODE=${MODE:-eval}

echo "[climb] $(date '+%T') start: waiting for 4090D stock..."
while true; do
  status=$(python3 "$AUTODL" status "$INSTANCE" 2>/dev/null | grep -o '"[a-z_]*"$' | tr -d '"' || true)
  echo "[climb] $(date '+%T') status=$status"
  if [ "$status" = "running" ]; then break; fi
  if [ "$status" = "shutdown" ] || [ "$status" = "shutdown_by_starting_error" ]; then
    out=$(python3 "$AUTODL" on "$INSTANCE" 2>&1)
    grep -q '"ok": true' <<< "$out" && echo "[climb] power-on accepted, booting..." || echo "[climb] no stock, retry in 1 min"
  fi
  sleep 60
done

echo "[climb] $(date '+%T') running, waiting for SSH..."
ssh_ok=0
for i in $(seq 1 40); do
  if $SSH "true" 2>/dev/null; then ssh_ok=1; echo "[climb] $(date '+%T') ssh ready"; break; fi
  sleep 15
done
[ "$ssh_ok" = "1" ] || { echo "[climb] SSH never came up"; exit 1; }

for attempt in 1 2 3; do
  rsync -az -e "ssh -p 34652" --exclude='.venv' --exclude='__pycache__' --exclude='logs' \
    "$CLIMB_LOCAL/source" "$CLIMB_LOCAL/training" "$CLIMB_LOCAL/models.json" \
    root@connect.bjb2.seetacloud.com:/root/autodl-tmp/desk-climb/ \
    && scp -P 34652 /Users/emwstudio/Desktop/DuckEMW/autodl/run_climb.sh root@connect.bjb2.seetacloud.com:/root/autodl-tmp/ \
    && break
  echo "[climb] rsync attempt $attempt failed, retry in 30s"; sleep 30
done

$SSH "export PATH=/root/.local/bin:/root/miniconda3/bin:\$PATH && nohup env MODE=$MODE bash /root/autodl-tmp/run_climb.sh > /root/autodl-tmp/run_climb.log 2>&1 & sleep 20; tail -5 /root/autodl-tmp/run_climb.log"
sleep 10
cnt=$($SSH "ps aux | grep -c 'run_climb\|train_climber\|train_getup\|evaluate_sequence'" 2>/dev/null || echo 0)
echo "[climb] $(date '+%T') launch verify: matching processes=$cnt"
[ "${cnt:-0}" -ge 2 ] && echo "[climb] PIPELINE RUNNING (MODE=$MODE)" || { echo "[climb] LAUNCH FAILED"; exit 1; }
