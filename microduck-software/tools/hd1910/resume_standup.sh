#!/usr/bin/env bash
# Resume HD1910 StandUp from a StandUp checkpoint only (same recipe + more iters).
# Never point this at velocity model_5999 — wrong task.
#
# Usage:
#   LOAD_RUN='2026-10-27_…_hd1910_standup_1024x1000_…' \
#     LOAD_CKPT='model_999.pt' \
#     ENVS=1024 MAX_ITERS=4000 \
#     bash tools/hd1910/resume_standup.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-1024}"
MAX_ITERS="${MAX_ITERS:-4000}"
SAVE="${SAVE:-100}"
EXP="${EXP:-microduck_standup_hd1910}"
TASK=Mjlab-StandUp-Flat-MicroDuck
export MICRODUCK_WARM_START="${MICRODUCK_WARM_START:-1}"

if [ -z "${LOAD_RUN:-}" ] || [ -z "${LOAD_CKPT:-}" ]; then
  echo "FAIL: set LOAD_RUN and LOAD_CKPT (StandUp logs under logs/rsl_rl/${EXP}/)"
  exit 1
fi
RUN="${1:-hd1910_standup_resume_${ENVS}_$(date +%m%d_%H%M)}"

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
  'ref': 'StandUp same-recipe resume; HD1910 m5',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== StandUp resume $RUN envs=$ENVS max_iters=$MAX_ITERS from $LOAD_RUN/$LOAD_CKPT =="
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
tail -8 "$LOG"
echo "ok — $LOG"
