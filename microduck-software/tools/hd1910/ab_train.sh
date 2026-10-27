#!/usr/bin/env bash
# Phase B A/B: same seed short train on OpenMicroDuck m5 vs Feetech official m6.
# GPU only. Switches live plant — do NOT run while another train holds the plant.
#
# Usage:
#   bash tools/hd1910/ab_train.sh              # both legs, default 1024×500
#   ENVS=1024 ITERS=500 bash tools/hd1910/ab_train.sh m5
#   ENVS=1024 ITERS=500 bash tools/hd1910/ab_train.sh m6
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-1024}"
ITERS="${ITERS:-500}"
SAVE="${SAVE:-100}"
SEED="${SEED:-42}"
WHICH="${1:-both}"   # m5 | m6 | both
TASK=Mjlab-Velocity-Flat-MicroDuck
TAG="$(date +%m%d_%H%M)"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"

run_leg() {
  local plant="$1"   # hd1910 | hd1910_ftservo_m6
  local name="$2"    # m5 | m6
  local run="hd1910_ab_${name}_${ENVS}x${ITERS}_${TAG}"
  echo "== apply plant=$plant =="
  "$PY" tools/hd1910/apply_to_live.py --plant "$plant"
  "$PY" tools/hd1910/apply_to_live.py --check
  "$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${run}.json"
  mkdir -p out
  "$PY" -c "
import json, hashlib, pathlib
meta={
  'run': '$run', 'task': '$TASK', 'ab_leg': '$name', 'plant_arg': '$plant',
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'envs': $ENVS, 'iters': $ITERS, 'seed': $SEED,
}
pathlib.Path('out/runmeta_${run}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
"
  local log="out/train_${run}.log"
  echo "== train $run =="
  set +e
  .venv-mjlab/Scripts/train.exe "$TASK" \
    --env.scene.num-envs "$ENVS" \
    --env.sim.mujoco.iterations 100 \
    --env.sim.mujoco.ls-iterations 50 \
    --agent.max-iterations "$ITERS" \
    --agent.save-interval "$SAVE" \
    --agent.seed "$SEED" \
    --gpu-ids '[0]' \
    --agent.logger tensorboard \
    --agent.experiment-name microduck_velocity_hd1910_ab \
    --agent.run-name "$run" \
    > "$log" 2>&1
  local rc=$?
  set -e
  echo "exit $rc log=$log"
  grep -q "Training with: device=cuda:0" "$log" || { echo "FAIL: not cuda:0"; exit 2; }
  [ "$rc" -eq 0 ] || { tail -40 "$log"; exit "$rc"; }
  echo "$run" >> "out/ab_runs_${TAG}.txt"
}

case "$WHICH" in
  m5) run_leg hd1910 m5 ;;
  m6) run_leg hd1910_ftservo_m6 m6 ;;
  both)
    run_leg hd1910 m5
    run_leg hd1910_ftservo_m6 m6
    # leave live on m6 after A/B; restore m5 explicitly if needed
    echo "A/B done. live plant is hd1910_ftservo_m6. Restore: apply_to_live.py --plant hd1910"
    ;;
  *) echo "usage: $0 [m5|m6|both]"; exit 1 ;;
esac
