#!/usr/bin/env bash
# Phase 4bc 完成后的收尾：聚合结果 → 拉取产物 → 关机（用户明确要求训练完关机）
set -uo pipefail
INSTANCE=pro-78811e875f25
AUTODL=/Users/emwstudio/.agents/skills/autodl/autodl.py
SSH="ssh -o ConnectTimeout=20 -p 34652 root@connect.bjb2.seetacloud.com"
SCP="scp -q -P 34652"
REMOTE=/root/autodl-tmp/desk-climb
ART=/Users/emwstudio/Desktop/DuckEMW/artifacts/desk_climb

echo "== 聚合 4b/4c 电池 =="
$SSH "export PATH=/root/miniconda3/bin:\$PATH && cd $REMOTE && \
  source/.venv/bin/python3 logs/audit_climb_eval.py logs/eval-z66-s19723 logs/eval-z66-s19823 logs/eval-z66-s19923 logs/eval-z66-s20023 | tail -2; \
  source/.venv/bin/python3 logs/audit_climb_eval.py logs/eval-getup-cost1-s19723 logs/eval-getup-cost1-s19823 logs/eval-getup-cost1-s19923 logs/eval-getup-cost1-s20023 | tail -2"

echo "== 拉回产物 =="
mkdir -p "$ART"/models "$ART"/evals
# 模型：续训 climber（采纳）+ 0.66 臂 + getup cost1 臂的 ONNX 与 checkpoint
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/desk-climber/desk-climber.onnx "$ART"/models/ 2>/dev/null || true
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/desk-climber/final.pt "$ART"/models/climber-cont56750.pt
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/desk-climber-z66/desk-climber-z66.onnx "$ART"/models/ 2>/dev/null || true
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/desk-climber-z66/final.pt "$ART"/models/climber-z66.pt
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/training/models/getup-cost1.onnx "$ART"/models/ 2>/dev/null || true
# 各电池轻量产物（switches/manifest/日志）
for d in eval-contA eval-contB eval-trig-root050 eval-trig-bothfeet eval-trig-spin2 eval-z66 eval-getup-cost1; do
  for s in 19723 19823 19923 20023; do
    mkdir -p "$ART/evals/$d-s$s"
    $SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/$d-s$s/switches.json "$ART/evals/$d-s$s/" 2>/dev/null || true
  done
done
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/climb/*.log "$ART"/evals/ 2>/dev/null || true
$SCP root@connect.bjb2.seetacloud.com:$REMOTE/logs/desk-climber/{manifest.json,height-gate-config.json,training-input-audit.json} "$ART"/evals/ 2>/dev/null || true
ls -la "$ART"/models/

echo "== 关机 =="
python3 "$AUTODL" off "$INSTANCE"
sleep 20
python3 "$AUTODL" status "$INSTANCE"
