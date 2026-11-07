#!/usr/bin/env bash
# 盯 AutoDL 拔河 trial 训练：两个 2000 迭代跑完后自动导出 ONNX 并拉回本地。
# 本地后台运行；实例上训练由 run_tug.sh 驱动（completed.tsv 断点记录）。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies

echo "[watch] $(date '+%T') start polling"
while true; do
  done_tags=$($SSH "cat $REPO/logs/tug/completed.tsv 2>/dev/null" || echo "__ssh_fail__")
  if [ "$done_tags" = "__ssh_fail__" ]; then
    echo "[watch] $(date '+%T') ssh failed, retry in 5 min"
  else
    steady=$(grep -c '^trial-steady$' <<< "$done_tags" || true)
    shuffle=$(grep -c '^trial-shuffle$' <<< "$done_tags" || true)
    prog=$($SSH "grep -o 'Learning iteration [0-9]*/2000' $REPO/logs/tug/trial-*.log 2>/dev/null | tail -2" || true)
    echo "[watch] $(date '+%T') steady_done=$steady shuffle_done=$shuffle; $prog"
    if [ "$steady" -ge 1 ] && [ "$shuffle" -ge 1 ]; then break; fi
  fi
  sleep 300
done

echo "[watch] $(date '+%T') both trials done, exporting ONNX on instance"
$SSH "bash -s" <<'EOF'
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
mkdir -p /root/autodl-tmp/artifacts
for pair in "Steady:tug_steady" "Shuffle:tug_shuffle"; do
  task="Mjlab-Microduck-Tug-${pair%%:*}"; exp="${pair##*:}"
  ckpt=$(ls -t logs/rsl_rl/$exp/*/model_2000.pt 2>/dev/null | head -1)
  if [ -z "$ckpt" ]; then echo "NO CHECKPOINT for $exp"; exit 1; fi
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_trial.onnx"
done
ls -la /root/autodl-tmp/artifacts/tug_*_trial.onnx
EOF

echo "[watch] $(date '+%T') pulling ONNX to local policies/"
scp -P 34652 root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/tug_steady_trial.onnx "$LOCAL_POLICIES/tug_steady_trial.onnx"
scp -P 34652 root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/tug_shuffle_trial.onnx "$LOCAL_POLICIES/tug_shuffle_trial.onnx"
echo "[watch] $(date '+%T') ALL DONE -> $LOCAL_POLICIES/tug_{steady,shuffle}_trial.onnx"
