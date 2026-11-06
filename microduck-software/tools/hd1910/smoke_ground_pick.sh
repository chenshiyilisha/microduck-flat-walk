#!/usr/bin/env bash
# HD1910 GroundPick smoke: 64 envs x 5 iters on GPU (cuda:0).
# Task: Mjlab-GroundPick-Flat-MicroDuck — mouth-to-ground approach/return.
#
# Why stock task id and NOT Mjlab-GroundPick-Flat-MicroDuck-HD1910-Reference:
# the HD1910 suite twin block lives in the branch's tasks/__init__.py (426 lines),
# but the venv only carries the develop-branch __init__.py (290 lines) — only
# robot/microduck_constants.py is patched by apply_to_live.py. venv's ground-pick
# env cfg file is byte-identical to the branch's, so stock id trains HD1910 text.
# (Updating the installed tasks module is a separate deployment decision.)
#
# Plant: mm1910_official_m6_kp8 (kp_fw=8, the deployment plant). GroundPick is a
# slow careful mouth-reach task -- it uses the global actuators/plant (same as
# velocity p8), NOT StandUp's m5/kp32 high-stiffness plant.
#
# Windows: MUJOCO_GL=glfw. Run from repo root: bash tools/hd1910/smoke_ground_pick.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
RUN="${1:-hd1910_groundpick_smoke_$(date +%m%d_%H%M)}"
TASK=Mjlab-GroundPick-Flat-MicroDuck
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  task=$TASK"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check =="
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
  'device': '$DEVICE', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'delay_min_lag': 3, 'delay_max_lag': 6,
  'envs': 64, 'iters': 5,
  'ref': 'GroundPick HD1910 suite twin; plant = deployment kp8 (NOT m5/kp32)',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== GroundPick smoke $RUN (GPU cuda:0) =="
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
  grep -E "Training with: device=" "$LOG" || true
  exit 2
}
tail -8 "$LOG"
echo "ok — GroundPick GPU smoke passed; stamps: out/plant_${RUN}.json / out/runmeta_${RUN}.json"
