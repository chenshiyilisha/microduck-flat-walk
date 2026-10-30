#!/usr/bin/env bash
# Heading-closed-loop smoke: 64 envs × 5 iters on **GPU** (cuda:0).
#
# Same shape as tools/hd1910/smoke_train.sh but drives the heading variant
# (train_heading_variant.py --rel-heading-envs <v>) instead of train.exe, so
# the run really executes the modified command loop. Plant gate is P3
# (hd1910_kp5 / kp_fw=5.0), not the m5/kp32 gate smoke_train.sh checks.
#
# Env overrides:
#   REL_HEADING=0.30 bash tools/hd1910/smoke_heading.sh [run_name]
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
RUN="${1:-head_smoke_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck
REL_HEADING="${REL_HEADING:-0.30}"
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"

# Official Windows path used by every successful velocity run in this repo.
export MUJOCO_GL=glfw
# Empty CUDA_VISIBLE_DEVICES ⇒ select_gpus → CPU; unset so [0] maps to GPU 0.
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  rel_heading=$REL_HEADING  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-<unset>}"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check (P3: hd1910_kp5 / kp_fw=5.0) =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910_kp5' and d.get('kp_fw')==5.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN',
  'task': '$TASK',
  'plant': 'hd1910_official_m6_kp5',
  'kp_fw': 5.0,
  'device': '$DEVICE',
  'gpu_ids': [0],
  'mujoco_gl': '$MUJOCO_GL',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'rel_heading_envs': $REL_HEADING,
  'envs': 64, 'iters': 5,
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta,indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== heading smoke $RUN rel_heading=$REL_HEADING (GPU cuda:0) =="
echo "log $LOG"
set +e
"$PY" tools/train_heading_variant.py \
  --rel-heading-envs "$REL_HEADING" \
  --task "$TASK" \
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
# Gate: heading knob must have taken effect (readback, not declared value).
# Python prints 0.30 as 0.3; match the numeric value, not the exact text.
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
echo "ok — GPU heading smoke passed; plant stamp: out/plant_${RUN}.json / out/runmeta_${RUN}.json"
