#!/usr/bin/env bash
# 抢 4090D → 渲染 13s 正面 3/4 视角爬梯片 → 回传 → 关机
set -uo pipefail
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py
SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"

echo "[render13] $(date '+%T') waiting for 4090D..."
while true; do
  status=$(python3 "$AUTODL" status "$INSTANCE" 2>/dev/null | grep -o '"[a-z_]*"$' | tr -d '"' || true)
  if [ "$status" = "running" ]; then break; fi
  if [ "$status" = "shutdown" ] || [ "$status" = "shutdown_by_starting_error" ]; then
    out=$(python3 "$AUTODL" on "$INSTANCE" 2>&1)
    grep -q '"ok": true' <<< "$out" && echo "[render13] power-on accepted" || echo "[render13] no stock, retry 1min"
  fi
  sleep 60
done
echo "[render13] running, waiting for SSH..."
for i in $(seq 1 40); do $SSH "true" 2>/dev/null && break; sleep 15; done

scp -q -P 34652 /Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/experiments/desk-climb/training/render_climb_video.py \
  root@connect.bjb2.seetacloud.com:/root/autodl-tmp/desk-climb/training/ || { echo "[render13] scp FAILED"; exit 1; }

$SSH "export PATH=/root/miniconda3/bin:\$PATH && cd /root/autodl-tmp/desk-climb/source && \
  MUJOCO_GL=osmesa PYTHONPATH=/root/autodl-tmp/desk-climb/training:/root/autodl-tmp/desk-climb/source/src \
  ENDING_ROLE=above LADDER_SHIFT=.06 HANDOFF_ARM=official TRIGGER_MODE=supported_root SWITCH_MARGIN=.04 \
  SWITCH_MAX_SPIN=999 GETUP_FILE=getup.onnx RECOVERY_MIN_ROOT_Z=.74 \
  uv run python ../training/render_climb_video.py --source ../logs/desk-climber/final.pt \
    --out ../logs/render-front-az45 --seconds 13 --seed 19923 --azimuth 45 \
    > /root/autodl-tmp/desk-climb/logs/climb/render-front.log 2>&1; echo render rc=\$?"
rc=$?

mkdir -p /Users/emwstudio/Desktop/DuckEMW/artifacts/desk_climb
scp -q -P 34652 root@connect.bjb2.seetacloud.com:/root/autodl-tmp/desk-climb/logs/render-front-az45/rl-video-step-0.mp4 \
  /Users/emwstudio/Desktop/DuckEMW/artifacts/desk_climb/climb-front-az45-13s.mp4 && echo "[render13] video pulled"

echo "[render13] shutting down..."
python3 "$AUTODL" off "$INSTANCE"
sleep 15
python3 "$AUTODL" status "$INSTANCE"
echo "[render13] ALL DONE (render rc=$rc)"
