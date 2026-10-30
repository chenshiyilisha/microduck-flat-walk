#!/usr/bin/env bash
# HD1910 velocity explore on GPU **with heading closed loop** (P3 retrain).
#
# P3 target plant is hd1910_kp5 (kp_fw=5.0), so the old explore_train.sh gate
# (detected=hd1910 / kp_fw=32.0) will fail after the P3 switch. This script is
# the P3-era replacement: P3 plant gate + train_heading_variant.py
# (--rel-heading-envs) so the heading knob actually executes in the run.
#
# Default 4096x2000 per RL_duck throughput note. The heading retrain must be
# **one** run that merges P3 plant + rel_heading_envs>0 (task change => retrain).
#
# Override: ENVS=8192 ITERS=6000 REL_HEADING=0.50 bash tools/hd1910/explore_heading.sh [run_name]
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-4096}"
ITERS="${ITERS:-2000}"
SAVE="${SAVE:-100}"
REL_HEADING="${REL_HEADING:-0.30}"
RUN="${1:-hd1910_kp5_head_${REL_HEADING}_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "rel_heading=$REL_HEADING"
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910_kp5' and d.get('kp_fw')==5.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': 'hd1910_official_m6_kp5', 'kp_fw': 5.0,
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'rel_heading_envs': $REL_HEADING,
  'expected_heading_x_forward_overlap': $REL_HEADING * 0.20,
  'envs': $ENVS, 'iters': $ITERS,
  'ref': 'P3 plant + heading closed loop (P2 yaw gap fix)',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== explore_heading $RUN envs=$ENVS iters=$ITERS (GPU) =="
echo "log $LOG"
set +e
"$PY" tools/train_heading_variant.py \
  --rel-heading-envs "$REL_HEADING" \
  --task "$TASK" \
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
# Gate: GPU actually used, and heading knob readback took effect.
grep -q "Training with: device=cuda:0" "$LOG" || {
  echo "FAIL: expected device=cuda:0"
  grep -E "Training with: device=" "$LOG" || true
  exit 2
}
"$PY" -c "
import re, sys
log = open('out/train_${RUN}.log', encoding='utf-8', errors='replace').read()
m = re.search(r'rel_heading_envs 0\.0 -> (\S+)', log)
got = float(m.group(1)) if m else None
want = float('${REL_HEADING}')
if got is None or abs(got - want) > 1e-9:
    print(f'FAIL: heading override did not take (got={got}, want={want})')
    sys.exit(3)
print(f'ok: heading knob readback {got} == {want}')
" || exit 3
tail -8 "$LOG"
echo "ok — $LOG"
