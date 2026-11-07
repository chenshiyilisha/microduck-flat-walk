#!/usr/bin/env bash
# 盯 AutoDL 拔河 v3 正式训练（4000×2）：完成后导出 ONNX 拉回本地，验证后关机。
# 用户已明确授权：训练完成后关机（off，保留磁盘，不 release）。
set -uo pipefail

SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py

echo "[watch-v3] $(date '+%T') start polling"
while true; do
  done_tags=$($SSH "cat $REPO/logs/tug/completed.tsv 2>/dev/null" || echo "__ssh_fail__")
  if [ "$done_tags" = "__ssh_fail__" ]; then
    echo "[watch-v3] $(date '+%T') ssh failed, retry in 5 min"
  else
    steady=$(grep -c '^v3-final-steady$' <<< "$done_tags" || true)
    shuffle=$(grep -c '^v3-final-shuffle$' <<< "$done_tags" || true)
    prog=$($SSH "grep -ho 'Learning iteration [0-9]*/4000' $REPO/logs/tug/v3-final-*.log 2>/dev/null | tail -1" || true)
    echo "[watch-v3] $(date '+%T') steady_done=$steady shuffle_done=$shuffle; $prog"
    if [ "$steady" -ge 1 ] && [ "$shuffle" -ge 1 ]; then break; fi
    failed=$($SSH "grep -c FAILED /root/autodl-tmp/run_tug_v3.log 2>/dev/null" || echo 0)
    if [ "${failed:-0}" -ge 1 ]; then echo "[watch-v3] TRAINING FAILED, see run_tug_v3.log"; break; fi
  fi
  sleep 300
done

echo "[watch-v3] $(date '+%T') training phase ended, exporting latest checkpoints"
$SSH "bash -s" <<'EOF' || true
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
mkdir -p /root/autodl-tmp/artifacts
for pair in "Steady:tug_steady" "Shuffle:tug_shuffle"; do
  task="Mjlab-Microduck-Tug-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt=$(ls -t "$rundir"model_*.pt 2>/dev/null | sort -t_ -k2 -n | tail -1)
  if [ -z "$ckpt" ]; then echo "NO CHECKPOINT for $exp"; continue; fi
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_final.onnx"
done
ls -la /root/autodl-tmp/artifacts/tug_*_final.onnx 2>/dev/null || true
EOF

ok=1
for f in tug_steady_final tug_shuffle_final; do
  scp -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx" || ok=0
  sz=$(stat -f%z "$LOCAL_POLICIES/$f.onnx" 2>/dev/null || echo 0)
  if [ "$sz" -lt 100000 ]; then echo "[watch-v3] $f.onnx missing/too small ($sz)"; ok=0; fi
done

if [ "$ok" = "1" ]; then
  echo "[watch-v3] $(date '+%T') ONNX verified local, powering off instance $INSTANCE (user authorized)"
  python3 "$AUTODL" off "$INSTANCE"
  echo "[watch-v3] $(date '+%T') ALL DONE — instance off, ONNX in policies/"
else
  echo "[watch-v3] $(date '+%T') EXPORT/PULL FAILED — leaving instance ON for debugging"
fi
