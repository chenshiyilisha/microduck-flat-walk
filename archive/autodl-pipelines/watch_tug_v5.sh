#!/usr/bin/env bash
# 盯 v5 trial（2000×2）：完成后导出 ONNX 拉回本地。不关机（可能续训 4000）。
# checkpoint 选取修复：直接取最新 run 目录里的 model_1999.pt。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch-v5] $(date '+%T') start polling"
while true; do
  done_tags=$($SSH "cat $REPO/logs/tug/completed.tsv 2>/dev/null" || echo "__ssh_fail__")
  if [ "$done_tags" = "__ssh_fail__" ]; then
    echo "[watch-v5] $(date '+%T') ssh failed (maybe still powering on), retry in 5 min"
  else
    steady=$(grep -c '^v5-trial-steady$' <<< "$done_tags" || true)
    shuffle=$(grep -c '^v5-trial-shuffle$' <<< "$done_tags" || true)
    prog=$($SSH "grep -ho 'Learning iteration [0-9]*/2000' $REPO/logs/tug/v5-trial-*.log 2>/dev/null | tail -1" || true)
    echo "[watch-v5] $(date '+%T') steady_done=$steady shuffle_done=$shuffle; $prog"
    if [ "$steady" -ge 1 ] && [ "$shuffle" -ge 1 ]; then break; fi
    if grep -qc 'FAILED' <<< "$($SSH 'cat /root/autodl-tmp/run_tug_v5.log 2>/dev/null')"; then
      echo "[watch-v5] TRAINING FAILED"; exit 1
    fi
  fi
  sleep 300
done

echo "[watch-v5] $(date '+%T') both v5 trials done, exporting"
$SSH "bash -s" <<'EOF'
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
mkdir -p /root/autodl-tmp/artifacts
for pair in "Steady:tug_steady" "Shuffle:tug_shuffle"; do
  task="Mjlab-Microduck-Tug-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt="${rundir}model_1999.pt"
  [ -f "$ckpt" ] || { echo "NO CHECKPOINT $ckpt"; exit 1; }
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v5.onnx"
done
ls -la /root/autodl-tmp/artifacts/tug_*_v5.onnx
EOF

for f in tug_steady_v5 tug_shuffle_v5; do
  scp -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx"
done
echo "[watch-v5] $(date '+%T') ALL DONE -> policies/tug_{steady,shuffle}_v5.onnx"
