#!/usr/bin/env bash
# Heading-closed-loop smoke: 64 envs × 5 iters on **GPU** (cuda:0).
#
# Same shape as tools/hd1910/smoke_train.sh but drives the heading variant
# (train_heading_variant.py --rel-heading-envs <v>) instead of train.exe, so
# the run really executes the modified command loop. Plant gate is P3
# (hd1910_kp5 / kp_fw=5.0) by default, not the m5/kp32 gate smoke_train.sh
# checks; PLANT=p8 switches it to the bench sweet-spot plant.
#
# Env overrides:
#   REL_HEADING=0.30 bash tools/hd1910/smoke_heading.sh [run_name]
#   PLANT=p8 REL_HEADING=0.30 bash tools/hd1910/smoke_heading.sh [run_name]
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
RUN="${1:-head_smoke_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck
REL_HEADING="${REL_HEADING:-0.30}"
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"
# Same heading reward recipe as explore_heading.sh / resume_heading_run.py::RECIPE,
# except HEADING_STAGE_ITERS: the real table (0,1000,1750,2500) cannot activate
# inside a 5-iteration smoke, and train_heading_variant.py rejects it outright.
# A smoke that leaves the rewards off would pass while the real run carries them
# (or vice versa), so they are asserted in the gates below instead.
HEADING_HOLD="${HEADING_HOLD:-1.0}"
HEADING_TRACKING="${HEADING_TRACKING:-3.0}"
ANG_VEL_Z_CLIP="${ANG_VEL_Z_CLIP:-0.5}"
HEADING_STAGE_ITERS="${HEADING_STAGE_ITERS:-0,1,2,3}"
PLANT="${PLANT:-p3}"
case "$PLANT" in
  p3) PLANT_ID=hd1910_official_m6_kp5; DET_EXPECT=hd1910_kp5; KP_EXPECT=5.0 ;;
  p8) PLANT_ID=hd1910_official_m6_kp8; DET_EXPECT=hd1910_kp8; KP_EXPECT=8.0 ;;
  *)  echo "PLANT must be p3 or p8 (got '$PLANT')" >&2; exit 2 ;;
esac

# Official Windows path used by every successful velocity run in this repo.
export MUJOCO_GL=glfw
# Empty CUDA_VISIBLE_DEVICES ⇒ select_gpus → CPU; unset so [0] maps to GPU 0.
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  rel_heading=$REL_HEADING  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-<unset>}"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check ($PLANT: $DET_EXPECT / kp_fw=$KP_EXPECT) =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='$DET_EXPECT' and d.get('kp_fw')==$KP_EXPECT else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN',
  'task': '$TASK',
  'plant': '$PLANT_ID',
  'kp_fw': $KP_EXPECT,
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
  --heading-hold-weight "$HEADING_HOLD" \
  --heading-tracking-final-weight "$HEADING_TRACKING" \
  --ang-vel-z-clip "$ANG_VEL_Z_CLIP" \
  --heading-stage-iters "$HEADING_STAGE_ITERS" \
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
# Gate: the heading REWARDS must be in the run, not just the command loop.
# --rel-heading-envs alone leaves them out, and a run without them is a
# different task from the p3head_rw_* line it would be compared against.
"$PY" -c "
import glob, sys
hits = glob.glob('logs/rsl_rl/microduck_velocity_hd1910/*${RUN}*/params/env.yaml')
if not hits:
    print('FAIL: no params/env.yaml for ${RUN}'); sys.exit(4)
text = open(sorted(hits)[-1], encoding='utf-8').read()
missing = [k for k in ('heading_hold_reward', 'heading_tracking_reward',
                       'heading_hold_weight', 'heading_tracking_weight')
           if k not in text]
if missing:
    print(f'FAIL: heading rewards absent from env.yaml: {missing}'); sys.exit(4)
print('ok: heading_hold + heading_tracking rewards present in env.yaml')
" || exit 4
tail -8 "$LOG"
echo "ok — GPU heading smoke passed; plant stamp: out/plant_${RUN}.json / out/runmeta_${RUN}.json"
