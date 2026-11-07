#!/usr/bin/env bash
# HD1910 roller-CROUCH training on GPU.
# Task: Mjlab-RollerCrouch-Flat-MicroDuck — the harder roller variant (low COM,
# crouched glide). Same env the official roller_crouch.onnx baseline (50.0% fall)
# was measured on, so the trained policy is apple-to-apple comparable.
#
# Plant: hd1910_kp8 (kp_fw=8, deployment plant) — MUST match the roller_crouch.onnx
# eval baseline. The live plant is asserted below; do not run under a different plant.
#
# "Based on roller_crouch.onnx" = benchmark against it (beat 50.0% fall). Same
# norm/action-scale boundary rationale as plain roller: trained from scratch on the
# HD1910 plant, not a weight warm-start.
#
# Override: ENVS=4096 ITERS=4000 SAVE=100 bash tools/hd1910/train_roller_crouch.sh [run_name]
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-64}"
ITERS="${ITERS:-5}"
SAVE="${SAVE:-${ITERS}}"
RUN="${1:-hd1910_roller_crouch_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-RollerCrouch-Flat-MicroDuck
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  task=$TASK  envs=$ENVS  iters=$ITERS"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check (must be hd1910_kp8 / kp_fw=8) =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910_kp8' and d.get('kp_fw')==8.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': 'hd1910_kp8', 'kp_fw': 8.0,
  'device': '$DEVICE', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'delay_min_lag': 3, 'delay_max_lag': 6,
  'envs': $ENVS, 'iters': $ITERS,
  'baseline': 'official roller_crouch.onnx on this env = 50.0% fall',
  'ref': 'HD1910 roller-crouch retrain; beat roller_crouch.onnx baseline; kp8=deploy plant',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== roller-crouch train $RUN envs=$ENVS iters=$ITERS (GPU cuda:0) =="
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
  --agent.experiment-name microduck_roller_crouch_hd1910 \
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
  grep -E "Training with: device=" "$LOG" || true
  exit 2
}
tail -8 "$LOG"
echo "ok — roller-crouch train $RUN passed; stamps: out/plant_${RUN}.json / out/runmeta_${RUN}.json / log $LOG"
