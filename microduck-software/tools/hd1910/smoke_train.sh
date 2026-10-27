#!/usr/bin/env bash
# HD1910 plant smoke: 64 envs × 5 iters on **GPU** (cuda:0).
# Windows: MUJOCO_GL=glfw (egl invalid). Refuses if plant gate is red.
# mjlab train picks device from --gpu-ids (default [0] → cuda:0); empty
# CUDA_VISIBLE_DEVICES forces CPU — clear it before launch.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
RUN="${1:-hd1910_smoke_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"

# Official Windows path used by every successful velocity run in this repo.
export MUJOCO_GL=glfw
# Empty CUDA_VISIBLE_DEVICES ⇒ select_gpus → CPU; unset so [0] maps to GPU 0.
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-<unset>}"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910' and d.get('kp_fw')==32.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/m5.json')
meta={
  'run': '$RUN',
  'task': '$TASK',
  'plant': 'hd1910_openmicroduck_m5',
  'kp_fw': 32.0,
  'device': '$DEVICE',
  'gpu_ids': [0],
  'mujoco_gl': '$MUJOCO_GL',
  'm5_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'envs': 64, 'iters': 5,
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta,indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== smoke train $RUN (GPU cuda:0) =="
echo "log $LOG"
set +e
.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs 64 \
  --env.sim.mujoco.iterations 100 \
  --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations 5 \
  --agent.save-interval 5 \
  --gpu-ids '[0]' \
  --agent.logger tensorboard \
  --agent.experiment-name microduck_velocity_hd1910 \
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
# Gate: must have actually trained on GPU (not silently CPU).
grep -q "Training with: device=cuda:0" "$LOG" || {
  echo "FAIL: expected device=cuda:0 in log"
  grep -E "Training with: device=" "$LOG" || true
  exit 2
}
tail -8 "$LOG"
echo "ok — GPU smoke passed; plant stamp: out/plant_${RUN}.json / out/runmeta_${RUN}.json"
