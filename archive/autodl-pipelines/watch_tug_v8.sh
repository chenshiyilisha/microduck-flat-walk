#!/usr/bin/env bash
# 盯 v8 3v3 链式训练（v8chain3-steady/shuffle，2048 envs×2000）：完成后导出拉回。不关机。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch-v8] $(date '+%T') start polling"
while true; do
  if $SSH "test -f /root/autodl-tmp/v8chain3.done" 2>/dev/null; then
    echo "[watch-v8] $(date '+%T') ALLDONE marker found"; break
  fi
  prog=$($SSH "grep -ho 'Learning iteration [0-9]*/2000' $REPO/logs/tug/v8chain3-*.log 2>/dev/null | tail -1" 2>/dev/null || true)
  echo "[watch-v8] $(date '+%T') $prog"
  # 冒烟失败或训练报错检测
  if $SSH "grep -q 'Traceback' $REPO/logs/tug/v8-smoke-steady.log 2>/dev/null" 2>/dev/null && \
     ! $SSH "test -f $REPO/logs/tug/v8chain3-steady.log" 2>/dev/null; then
    echo "[watch-v8] SMOKE FAILED"; exit 1
  fi
  sleep 300
done

echo "[watch-v8] $(date '+%T') exporting"
$SSH "bash -s" <<'EOF' || exit 1
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
for pair in "Steady:tugchain3_steady" "Shuffle:tugchain3_shuffle"; do
  task="Mjlab-Microduck-TugChain3-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt="${rundir}model_1999.pt"
  [ -f "$ckpt" ] || { echo "NO CHECKPOINT $ckpt"; exit 1; }
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v8.onnx"
done
ls -la /root/autodl-tmp/artifacts/*_v8.onnx
EOF

ok=1
for f in tugchain3_steady_v8 tugchain3_shuffle_v8; do
  for i in 1 2 3 4 5; do
    scp -o ConnectTimeout=20 -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx" && break
    echo "[watch-v8] scp $f attempt $i failed, retry in 30s"; sleep 30
  done
  sz=$(stat -f%z "$LOCAL_POLICIES/$f.onnx" 2>/dev/null || echo 0)
  [ "$sz" -lt 100000 ] && { echo "[watch-v8] $f bad ($sz)"; ok=0; }
done
[ "$ok" = "1" ] && echo "[watch-v8] $(date '+%T') ALL DONE" || echo "[watch-v8] PULL FAILED"
