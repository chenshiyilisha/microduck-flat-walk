#!/usr/bin/env bash
# 盯 v8 3v3 链式训练（v9chain3s-steady/shuffle，2048 envs×2000）：完成后导出拉回。不关机。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch-v9] $(date '+%T') start polling"
while true; do
  if $SSH "test -f /root/autodl-tmp/v9chain3s.done" 2>/dev/null; then
    echo "[watch-v9] $(date '+%T') ALLDONE marker found"; break
  fi
  prog=$($SSH "grep -ho 'Learning iteration [0-9]*/2000' $REPO/logs/tug/v9chain3s-*.log 2>/dev/null | tail -1" 2>/dev/null || true)
  echo "[watch-v9] $(date '+%T') $prog"
  # 冒烟失败或训练报错检测
  if $SSH "grep -q 'Traceback' $REPO/logs/tug/v9-smoke-steady.log 2>/dev/null" 2>/dev/null && \
     ! $SSH "test -f $REPO/logs/tug/v9chain3s-steady.log" 2>/dev/null; then
    echo "[watch-v9] SMOKE FAILED"; exit 1
  fi
  sleep 300
done

echo "[watch-v9] $(date '+%T') exporting"
$SSH "bash -s" <<'EOF' || exit 1
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
for pair in "Steady:tugchain3s_steady" "Shuffle:tugchain3s_shuffle"; do
  task="Mjlab-Microduck-TugChain3S-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt="${rundir}model_1999.pt"
  [ -f "$ckpt" ] || { echo "NO CHECKPOINT $ckpt"; exit 1; }
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v9.onnx"
done
ls -la /root/autodl-tmp/artifacts/*_v9.onnx
EOF

ok=1
for f in tugchain3s_steady_v8 tugchain3s_shuffle_v8; do
  for i in 1 2 3 4 5; do
    scp -o ConnectTimeout=20 -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx" && break
    echo "[watch-v9] scp $f attempt $i failed, retry in 30s"; sleep 30
  done
  sz=$(stat -f%z "$LOCAL_POLICIES/$f.onnx" 2>/dev/null || echo 0)
  [ "$sz" -lt 100000 ] && { echo "[watch-v9] $f bad ($sz)"; ok=0; }
done
[ "$ok" = "1" ] && echo "[watch-v9] $(date '+%T') ALL DONE" || echo "[watch-v9] PULL FAILED"
