#!/usr/bin/env bash
# Resume HD1910 velocity explore from a saved checkpoint (m5 plant).
# Default: continue the finished 4096×2000 run toward 6000 iters (~RL_duck env-step scale).
#
# Usage:
#   bash tools/hd1910/resume_train.sh
#   ENVS=4096 MAX_ITERS=6000 bash tools/hd1910/resume_train.sh
#   LOAD_RUN='2026-10-26_12-55-20_hd1910_explore_4096x2000_1026' \
#     LOAD_CKPT='model_1999.pt' bash tools/hd1910/resume_train.sh my_resume_name
#
# Notes:
# - Only resumes from periodic saves (save-interval). Kill mid-interval ⇒ lose < SAVE iters.
# - MICRODUCK_WARM_START: default 1 (restart curricula). For true continue set =0
#   (keeps ckpt iter + curriculum). rsl_rl stop = ckpt_iter + MAX_ITERS.
# - Do not switch plant while resuming; must stay OpenMicroDuck m5 for this ckpt.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-4096}"
MAX_ITERS="${MAX_ITERS:-6000}"
SAVE="${SAVE:-100}"
EXP="${EXP:-microduck_velocity_hd1910}"
LOAD_RUN="${LOAD_RUN:-2026-10-26_12-55-20_hd1910_explore_4096x2000_1026}"
LOAD_CKPT="${LOAD_CKPT:-model_1999.pt}"
RUN="${1:-hd1910_resume_${ENVS}x${MAX_ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck
export MICRODUCK_WARM_START="${MICRODUCK_WARM_START:-1}"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

CKPT_PATH="logs/rsl_rl/${EXP}/${LOAD_RUN}/${LOAD_CKPT}"
if [ ! -f "$CKPT_PATH" ]; then
  echo "FAIL: missing checkpoint $CKPT_PATH"
  exit 1
fi

echo "== GPU / GL =="
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"
"$PY" tools/hd1910/apply_to_live.py --plant hd1910
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
  'envs': $ENVS, 'max_iterations': $MAX_ITERS,
  'resume': True, 'load_run': '$LOAD_RUN', 'load_checkpoint': '$LOAD_CKPT',
  'warm_start': '$MICRODUCK_WARM_START',
  'ref': 'resume from 4096 explore toward RL_duck ~590M env steps',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== resume $RUN envs=$ENVS max_iters=$MAX_ITERS from $LOAD_RUN/$LOAD_CKPT =="
echo "log $LOG"
set +e
.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --env.sim.mujoco.iterations 100 \
  --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations "$MAX_ITERS" \
  --agent.save-interval "$SAVE" \
  --agent.resume True \
  --agent.load-run "$LOAD_RUN" \
  --agent.load-checkpoint "$LOAD_CKPT" \
  --gpu-ids '[0]' \
  --agent.logger tensorboard \
  --agent.experiment-name "$EXP" \
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
grep -qiE "Loading model checkpoint|Loading checkpoint" "$LOG" || {
  echo "WARN: did not see checkpoint-load line; check log head"
}
tail -8 "$LOG"
echo "ok — $LOG"
