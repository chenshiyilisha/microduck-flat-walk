#!/usr/bin/env bash
# HD1910 GroundPick explore on GPU (4070 / 4070 Ti).
# Task: Mjlab-GroundPick-Flat-MicroDuck — mouth-to-ground
# approach/return (never touch), 4 s phase-coded command.
#
# Why stock task id and NOT -HD1910-Reference: the HD1910 suite twin block lives
# in the branch's tasks/__init__.py (426 lines), which the venv does NOT carry
# (venv has the develop-branch __init__.py, 290 lines; only
# robot/microduck_constants.py is patched by apply_to_live.py). The venv's
# ground-pick env cfg is byte-identical to the branch's, so the stock id trains
# HD1910 code. Upgrading the installed tasks module is a separate decision.
#
# AGENTS.md trail-class flow: explore 1024 x 500–1000 first (curve check), formal
# 4096 x 4000 later. Defaults here: 1024x1000. Override for formal after smoke:
#   ENVS=4096 ITERS=4000 bash tools/hd1910/explore_ground_pick.sh
#
# Do NOT resume from velocity/p8 model_5999 — different task and plant scale;
# train from zero.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-1024}"
ITERS="${ITERS:-1000}"
SAVE="${SAVE:-100}"
RUN="${1:-hd1910_groundpick_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-GroundPick-Flat-MicroDuck

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  envs=$ENVS iters=$ITERS  task=$TASK"
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected'], 'kp_fw', d.get('kp_fw')); raise SystemExit(0 if d.get('kp_fw')==8.0 and str(d.get('detected','')).startswith('hd1910') else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': 'hd1910_official_m6_kp8', 'kp_fw': 8.0,
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'delay_min_lag': 3, 'delay_max_lag': 6,
  'envs': $ENVS, 'iters': $ITERS,
  'ref': 'AGENTS.md explore; upstream GroundPick Flat; HD1910 suite twin',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== GroundPick explore $RUN envs=$ENVS iters=$ITERS (GPU) =="
echo "log $LOG"
set +e
.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --env.sim.mujoco.iterations 100 \
  --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations "$ITERS" \
  --agent.save-interval "$SAVE" \
  --gpu-ids '[0]' \
  --agent.logger tensorboard \
  --agent.experiment-name microduck_groundpick_hd1910 \
  --agent.run-name "$RUN" \
  > "$LOG" 2>&1
RC=$?
set -e
echo "exit $RC"
if [ "$RC" -ne 0 ]; then
  echo "--- last 40 log lines ---"
  tail -40 "$LOG"
  exit "$RC"
fi
grep -q "Training with: device=cuda:0" "$LOG" || {
  echo "FAIL: expected device=cuda:0 in log"
  exit 2
}
tail -8 "$LOG"
echo "ok — $LOG"
echo "next: inspect curves (reward/term ratios, save ratio), then formal run with"
echo "      ENVS=4096 ITERS=4000 — and only after smoke + first-curve read-out."
