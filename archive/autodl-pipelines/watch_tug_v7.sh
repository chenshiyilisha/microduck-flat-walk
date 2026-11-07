#!/usr/bin/env bash
# 盯 v7 链式自对弈训练（v7chain-steady/shuffle，2000×2）：完成后导出 ONNX 拉回。不关机。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch-v7] $(date '+%T') start polling"
while true; do
  if $SSH "test -f /root/autodl-tmp/v7chain.done" 2>/dev/null; then
    echo "[watch-v7] $(date '+%T') ALLDONE marker found"; break
  fi
  prog=$($SSH "grep -ho 'Learning iteration [0-9]*/2000' $REPO/logs/tug/v7chain-*.log 2>/dev/null | tail -1" 2>/dev/null || true)
  echo "[watch-v7] $(date '+%T') $prog"
  if $SSH "grep -q 'Error\|Traceback' /root/autodl-tmp/run_v7chain.log 2>/dev/null" 2>/dev/null; then
    echo "[watch-v7] pipeline error detected"; break
  fi
  sleep 300
done

echo "[watch-v7] $(date '+%T') exporting"
$SSH "bash -s" <<'EOF' || exit 1
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
for pair in "Steady:tugchain_steady" "Shuffle:tugchain_shuffle"; do
  task="Mjlab-Microduck-TugChain-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt="${rundir}model_1999.pt"
  [ -f "$ckpt" ] || { echo "NO CHECKPOINT $ckpt"; exit 1; }
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v7.onnx"
done
ls -la /root/autodl-tmp/artifacts/*_v7.onnx
EOF

ok=1
for f in tugchain_steady_v7 tugchain_shuffle_v7; do
  for i in 1 2 3 4 5; do
    scp -o ConnectTimeout=20 -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx" && break
    echo "[watch-v7] scp $f attempt $i failed, retry in 30s"; sleep 30
  done
  sz=$(stat -f%z "$LOCAL_POLICIES/$f.onnx" 2>/dev/null || echo 0)
  [ "$sz" -lt 100000 ] && { echo "[watch-v7] $f bad ($sz)"; ok=0; }
done
[ "$ok" = "1" ] && echo "[watch-v7] $(date '+%T') ALL DONE" || echo "[watch-v7] PULL FAILED"
