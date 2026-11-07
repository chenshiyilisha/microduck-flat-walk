#!/usr/bin/env bash
# 盯 v4 续训（v4r-steady/shuffle，至 5999 迭代）：完成后导出 ONNX 拉回本地并关机。
# 关机已由用户授权（"训练好记得关机"）。
set -uo pipefail

SSH="ssh -o ConnectTimeout=30 -p 34652 root@connect.bjb2.seetacloud.com"
REPO=/root/autodl-tmp/microduck-playground
LOCAL_POLICIES=/Users/emwstudio/Desktop/DuckEMW/third_party/microduck-playground/policies
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py

echo "[watch-v4r] $(date '+%T') start polling"
while true; do
  done_tags=$($SSH "cat $REPO/logs/tug/completed.tsv 2>/dev/null" || echo "__ssh_fail__")
  if [ "$done_tags" = "__ssh_fail__" ]; then
    echo "[watch-v4r] $(date '+%T') ssh failed, retry in 5 min"
  else
    steady=$(grep -c '^v4r-steady$' <<< "$done_tags" || true)
    shuffle=$(grep -c '^v4r-shuffle$' <<< "$done_tags" || true)
    prog=$($SSH "grep -ho 'Learning iteration [0-9]*/5999' $REPO/logs/tug/v4r-*.log 2>/dev/null | tail -1" || true)
    echo "[watch-v4r] $(date '+%T') steady_done=$steady shuffle_done=$shuffle; $prog"
    if [ "$steady" -ge 1 ] && [ "$shuffle" -ge 1 ]; then break; fi
    failed=$($SSH "grep -c FAILED /root/autodl-tmp/run_tug_v4_resume.log 2>/dev/null || true" || echo 0)
    if [ "${failed:-0}" -ge 1 ]; then echo "[watch-v4r] RESUME FAILED, see run_tug_v4_resume.log"; break; fi
  fi
  sleep 300
done

echo "[watch-v4r] $(date '+%T') resume phase ended, exporting"
$SSH "bash -s" <<'EOF' || true
set -e
export PATH=/root/miniconda3/bin:$PATH
cd /root/autodl-tmp/microduck-playground
for pair in "Steady:tug_steady" "Shuffle:tug_shuffle"; do
  task="Mjlab-Microduck-Tug-${pair%%:*}"; exp="${pair##*:}"
  rundir=$(ls -td logs/rsl_rl/$exp/*/ | head -1)
  ckpt="${rundir}model_5999.pt"
  if [ ! -f "$ckpt" ]; then
    ckpt=$(ls -V "$rundir"model_*.pt | tail -1)  # 回退：取最大迭代号
    echo "model_5999.pt missing, fallback to $ckpt"
  fi
  [ -f "$ckpt" ] || { echo "NO CHECKPOINT for $exp"; continue; }
  echo "exporting $exp <- $ckpt"
  uv run scripts/export.py "$task" --checkpoint-file "$ckpt" \
    --onnx-file "/root/autodl-tmp/artifacts/${exp}_v4final.onnx"
done
ls -la /root/autodl-tmp/artifacts/tug_*_v4final.onnx 2>/dev/null || true
EOF

ok=1
for f in tug_steady_v4final tug_shuffle_v4final; do
  scp -P 34652 "root@connect.bjb2.seetacloud.com:/root/autodl-tmp/artifacts/$f.onnx" "$LOCAL_POLICIES/$f.onnx" || ok=0
  sz=$(stat -f%z "$LOCAL_POLICIES/$f.onnx" 2>/dev/null || echo 0)
  [ "$sz" -lt 100000 ] && { echo "[watch-v4r] $f.onnx bad ($sz)"; ok=0; }
done

if [ "$ok" = "1" ]; then
  echo "[watch-v4r] $(date '+%T') ONNX verified, powering off $INSTANCE"
  python3 "$AUTODL" off "$INSTANCE"
  echo "[watch-v4r] $(date '+%T') ALL DONE — instance off"
else
  echo "[watch-v4r] $(date '+%T') EXPORT/PULL FAILED — instance left ON"
fi
