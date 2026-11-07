#!/usr/bin/env bash
# v4 全自动管线 v2：每分钟抢 4090D → 确认 running（处理开机失败）→ SSH 就绪
# → rsync（带重试）→ 启动训练 → 验证进程在跑
set -uo pipefail
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py
SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO_LOCAL=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground

echo "[v4] $(date '+%T') start: waiting for 4090D stock..."
while true; do
  status=$(python3 "$AUTODL" status "$INSTANCE" 2>/dev/null | grep -o '"[a-z_]*"$' | tr -d '"' || true)
  echo "[v4] $(date '+%T') status=$status"
  if [ "$status" = "running" ]; then break; fi
  if [ "$status" = "shutdown" ] || [ "$status" = "shutdown_by_starting_error" ]; then
    out=$(python3 "$AUTODL" on "$INSTANCE" 2>&1)
    grep -q '"ok": true' <<< "$out" && echo "[v4] power-on accepted, booting..." || echo "[v4] no stock, retry in 1 min"
  fi
  sleep 60
done

echo "[v4] $(date '+%T') running, waiting for SSH..."
ssh_ok=0
for i in $(seq 1 40); do
  if $SSH "true" 2>/dev/null; then ssh_ok=1; echo "[v4] $(date '+%T') ssh ready"; break; fi
  sleep 15
done
[ "$ssh_ok" = "1" ] || { echo "[v4] SSH never came up"; exit 1; }

for attempt in 1 2 3; do
  rsync -az -e "ssh -p 34652" --exclude='.git' --exclude='.venv' --exclude='logs' --exclude='__pycache__' \
    "$REPO_LOCAL/src" "$REPO_LOCAL/tests" "$REPO_LOCAL/scripts" \
    root@connect.bjb2.seetacloud.com:/root/autodl-tmp/microduck-playground/ && break
  echo "[v4] rsync attempt $attempt failed, retry in 30s"; sleep 30
done

$SSH "cd /root/autodl-tmp/microduck-playground && export PATH=/root/miniconda3/bin:\$PATH && nohup env TAG_PREFIX=v4- MODE=trial bash /root/autodl-tmp/run_tug.sh > /root/autodl-tmp/run_tug_v4.log 2>&1 & sleep 20; tail -3 /root/autodl-tmp/run_tug_v4.log"
sleep 10
cnt=$($SSH "ps aux | grep -c 'train Mjlab\|run_tug'" 2>/dev/null || echo 0)
echo "[v4] $(date '+%T') launch verify: matching processes=$cnt"
[ "${cnt:-0}" -ge 2 ] && echo "[v4] PIPELINE RUNNING" || { echo "[v4] LAUNCH FAILED"; exit 1; }
