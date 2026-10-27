#!/usr/bin/env bash
# HD1910 velocity explore on GPU. Default 4096×2000 per RL_duck throughput note
# (microduck-RL_duck教学仓对照.md §2.1: 2048→4096 almost free; sweet spot 8192).
# Override: ENVS=8192 ITERS=6000 bash tools/hd1910/explore_train.sh [run_name]
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-4096}"
ITERS="${ITERS:-2000}"
SAVE="${SAVE:-100}"
RUN="${1:-hd1910_explore_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910' and d.get('kp_fw')==32.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/m5.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': 'hd1910_openmicroduck_m5', 'kp_fw': 32.0,
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'm5_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'envs': $ENVS, 'iters': $ITERS,
  'ref': 'RL_duck throughput; HD1910 plant m5',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== explore $RUN envs=$ENVS iters=$ITERS (GPU) =="
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
  --agent.experiment-name microduck_velocity_hd1910 \
  --agent.run-name "$RUN" \
  > "$LOG" 2>&1
RC=$?
set -e
echo "exit $RC"
if [ "$RC" -ne 0 ]; then
  tail -40 "$LOG"
  exit "$RC"
fi
grep -q "Training with: device=cuda:0" "$LOG" || {
  echo "FAIL: expected device=cuda:0"
  exit 2
}
tail -8 "$LOG"
echo "ok — $LOG"
