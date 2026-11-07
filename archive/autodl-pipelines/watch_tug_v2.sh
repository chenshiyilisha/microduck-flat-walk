#!/usr/bin/env bash
# 盯 AutoDL 拔河 v2 trial 训练：完成后自动导出 ONNX 并拉回本地。
# v1 的教训：最终 checkpoint 是 model_1999.pt（不是 2000），run 目录取各实验最新。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch-v2] $(date '+%T') start polling"
while true; do
  done_tags=$($SSH "cat $REPO/logs/tug/completed.tsv 2>/dev/null" || echo "__ssh_fail__")
  if [ "$done_tags" = "__ssh_fail__" ]; then
    echo "[watch-v2] $(date '+%T') ssh failed, retry in 5 min"
  else
    steady=$(grep -c '^v2-trial-steady$' <<< "$done_tags" || true)
    shuffle=$(grep -c '^v2-trial-shuffle$' <<< "$done_tags" || true)
    prog=$($SSH "grep -ho 'Learning iteration [0-9]*/2000' $REPO/logs/tug/v2-trial-*.log 2>/dev/null | tail -1" || true)
    echo "[watch-v2] $(date '+%T') steady_done=$steady shuffle_done=$shuffle; $prog"
    if [ "$steady" -ge 1 ] && [ "$shuffle" -ge 1 ]; then break; fi
  fi
  sleep 300
done

echo "[watch-v2] $(date '+%T') both v2 trials done, exporting ONNX on instance"
$SSH "bash -s" <<'EOF'
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
mkdir -p /root/autodl-tmp/artifacts
for pair in "Steady:tug_steady" "Shuffle:tug_shuffle"; do
  task="Mjlab-Microduck-Tug-${pair%%:*}"; exp="${pair##*:}"
  ckpt=$(ls -t logs/rsl_rl/$exp/*/model_1999.pt 2>/dev/null | head -1)
  if [ -z "$ckpt" ]; then echo "NO CHECKPOINT for $exp"; exit 1; fi
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v2.onnx"
done
ls -la /root/autodl-tmp/artifacts/tug_*_v2.onnx
EOF

echo "[watch-v2] $(date '+%T') pulling ONNX to local policies/"
scp -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/tug_steady_v2.onnx" "$LOCAL_POLICIES/tug_steady_v2.onnx"
scp -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/tug_shuffle_v2.onnx" "$LOCAL_POLICIES/tug_shuffle_v2.onnx"
echo "[watch-v2] $(date '+%T') ALL DONE -> $LOCAL_POLICIES/tug_{steady,shuffle}_v2.onnx"
