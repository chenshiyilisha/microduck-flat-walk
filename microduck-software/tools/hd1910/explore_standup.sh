#!/usr/bin/env bash
# HD1910 StandUp explore on GPU (4070 / 4070 Ti).
# Task: Mjlab-StandUp-Flat-MicroDuck — fall recovery / get-up (not Velocity).
#
# AGENTS.md: trick-class → explore 1024 × 500–1000 first; formal 4096 × 4000 later.
# Defaults here: 1024×1000 (curve check). Override for Ti after smoke:
#   ENVS=1024 ITERS=1000 bash tools/hd1910/explore_standup.sh
#   ENVS=4096 ITERS=4000 bash tools/hd1910/explore_standup.sh   # formal
#
# Do NOT resume from velocity model_5999 — different task → train from zero.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-1024}"
ITERS="${ITERS:-1000}"
SAVE="${SAVE:-100}"
RUN="${1:-hd1910_standup_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-StandUp-Flat-MicroDuck

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
  'ref': 'AGENTS.md explore; upstream StandUp Flat; HD1910 m5; 4070 Ti',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== StandUp explore $RUN envs=$ENVS iters=$ITERS (GPU) =="
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
  --agent.experiment-name microduck_standup_hd1910 \
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
echo "next (same recipe only): ENVS=$ENVS MAX_ITERS=<higher> LOAD_RUN=… LOAD_CKPT=model_*.pt bash tools/hd1910/resume_standup.sh"
