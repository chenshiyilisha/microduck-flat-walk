#!/usr/bin/env bash
# Reward-free CONTROL arm for the kp8 heading A/B (the run 2026-11-03 lacks).
#
# What is being compared
# ----------------------
#   A (reward arm):  logs/rsl_rl/.../2026-11-03_08-33-18_p8head_030_4096x3000
#                    4096x3000, seed 42, rel_heading_envs 0.3, ang_vel_z +-0.5,
#                    heading_hold 1.0 -> 0 / heading_tracking 0 -> 3.0
#   B (this script): 4096x3000, seed 42, rel_heading_envs 0.3, ang_vel_z +-0.5,
#                    NO heading reward terms
#
# Everything else must be byte-identical, which is what the gates at the bottom
# check and what tools/hd1910/check_ab_recipe.py re-checks afterwards by
# diffing the two runs' params/*.yaml leaf by leaf.
#
# Why a separate script instead of a flag on explore_heading.sh
# ------------------------------------------------------------
# That script's defaults ADD the rewards; a control selected by a flag there
# would be one forgotten env var away from being another reward run that looks
# like a control. Here the reward-free recipe is the only thing this script can
# produce, and the gate is INVERTED: params/env.yaml must contain zero
# occurrences of heading_hold / heading_tracking. Adding a reward term by
# accident turns the gate red instead of silently changing the arm.
#
# Why ang_vel_z +-0.5 on BOTH arms
# --------------------------------
# `rel_heading_envs > 0` drives cmd[2] = clip(stiffness * heading_error,
# ranges.ang_vel_z) every step, so the range is how hard the policy may steer,
# independent of any reward. The 2026-11-02 21:26 run is the cautionary case:
# launched with only --rel-heading-envs, its --ang-vel-z-clip was silently
# ignored (read only inside the reward branch), so it trained on +-1.0 and is
# NOT a usable reward-free arm for a +-0.5 run even though its name says 030.
#
# Cost (measured, not estimated): the 2026-11-03 arm took 08:33:29 -> 11:50:16
# = 3.28 h for 3000 iters at 4096 envs (3.94 s/iter) on the 4070 Ti laptop.
#
# Usage
#   bash tools/hd1910/explore_heading_control.sh                 # real run
#   DRY=1 bash tools/hd1910/explore_heading_control.sh           # plant+recipe only
#   SMOKE=1 bash tools/hd1910/explore_heading_control.sh         # 64x5, gates only
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
TASK=Mjlab-Velocity-Flat-MicroDuck

# --- recipe (single source of truth; SMOKE only changes sizes) --------------
REL_HEADING="${REL_HEADING:-0.30}"
CLIP="${CLIP:-0.5}"
SEED="${SEED:-42}"
if [ "${SMOKE:-0}" = "1" ]; then
  ENVS=64; ITERS=5; SAVE=5; RUN="${1:-p8ctl_smoke_$(date +%m%d_%H%M)}"
else
  ENVS="${ENVS:-4096}"; ITERS="${ITERS:-3000}"; SAVE="${SAVE:-100}"
  RUN="${1:-p8ctl_030_${ENVS}x${ITERS}}"
fi
# The arm this control is paired with. Used for the runmeta stamp and, at the
# end, for the recipe diff.
REWARD_ARM="${REWARD_ARM:-2026-11-03_08-33-18_p8head_030_4096x3000}"

# Plant is hard-coded, not overridable: this control only means anything on the
# deployment plant the reward arm was trained on.
PLANT_ID=hd1910_official_m6_kp8
DET_EXPECT=hd1910_kp8
KP_EXPECT=8.0

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== recipe =="
echo "run=$RUN envs=$ENVS iters=$ITERS save=$SAVE seed=$SEED"
echo "plant=$PLANT_ID (expect detected=$DET_EXPECT kp_fw=$KP_EXPECT)"
echo "rel_heading_envs=$REL_HEADING  ang_vel_z=+-$CLIP  heading_rewards=<none by design>"
echo "paired with reward arm: $REWARD_ARM"

if [ -d "logs/rsl_rl/microduck_velocity_hd1910" ] && \
   ls -d logs/rsl_rl/microduck_velocity_hd1910/*_"$RUN" >/dev/null 2>&1; then
  echo "FAIL: a run directory for '$RUN' already exists -- pick another name" >&2
  ls -d logs/rsl_rl/microduck_velocity_hd1910/*_"$RUN" >&2
  exit 2
fi

echo "== GPU / GL =="
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='$DET_EXPECT' and d.get('kp_fw')==$KP_EXPECT else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"

if [ "${DRY:-0}" = "1" ]; then
  echo "== DRY: showing the resolved variant, not training =="
  "$PY" tools/train_heading_variant.py \
    --rel-heading-envs "$REL_HEADING" \
    --ang-vel-z-clip "$CLIP" \
    --task "$TASK" \
    --env.scene.num-envs "$ENVS" \
    --env.sim.mujoco.iterations 100 \
    --env.sim.mujoco.ls-iterations 50 \
    --agent.max-iterations "$ITERS" \
    --agent.save-interval "$SAVE" \
    --agent.seed "$SEED" \
    --gpu-ids '[0]' \
    --agent.logger tensorboard \
    --agent.experiment-name microduck_velocity_hd1910 \
    --agent.run-name "dryrun_${RUN}" \
    --dry-run 2>&1 | tail -12
  echo "DRY ok — launch without DRY=1 to train"
  exit 0
fi

"$PY" -c "
import json, hashlib, pathlib
p = pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta = {
  'run': '$RUN', 'task': '$TASK', 'arm': 'control (no heading rewards)',
  'paired_with': '$REWARD_ARM',
  'plant': '$PLANT_ID', 'kp_fw': $KP_EXPECT,
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'delay_min_lag': json.load(open('out/plant_${RUN}.json', encoding='utf-8'))['delay_min_lag'],
  'delay_max_lag': json.load(open('out/plant_${RUN}.json', encoding='utf-8'))['delay_max_lag'],
  'rel_heading_envs': $REL_HEADING,
  'ang_vel_z_clip': $CLIP,
  'heading_rewards': None,
  'heading_hold_weight': None, 'heading_tracking_final_weight': None,
  'seed': $SEED, 'envs': $ENVS, 'iters': $ITERS,
  'ref': 'reward-free arm: same command loop and turn range as the reward arm',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

LOG="out/train_${RUN}.log"
echo "== control run $RUN ${ENVS}x${ITERS} (GPU) =="
echo "log $LOG"
set +e
"$PY" tools/train_heading_variant.py \
  --rel-heading-envs "$REL_HEADING" \
  --ang-vel-z-clip "$CLIP" \
  --task "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --env.sim.mujoco.iterations 100 \
  --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations "$ITERS" \
  --agent.save-interval "$SAVE" \
  --agent.seed "$SEED" \
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

D=$(ls -d logs/rsl_rl/microduck_velocity_hd1910/*_"$RUN" | sort | tail -1)
echo "run dir $D"

# ---------------------------------------------------------------------------
# Gates. Every one of them checks the EFFECTIVE value written to the run's own
# params/, not what was typed on the command line.
# ---------------------------------------------------------------------------
CHECK_ARGS=(--run-dir "$D" --expect-abs-envs "$ENVS" --expect-iters "$ITERS"
            --expect-seed "$SEED" --expect-rel-heading "$REL_HEADING"
            --expect-ang-vel-z "$CLIP")
"$PY" tools/hd1910/check_control_arm.py "${CHECK_ARGS[@]}" || exit $?

# Negative control, run every time: the food the gate is supposed to reject is
# the reward arm itself. If this passes, the gate is broken, not the run.
REWARD_DIR="logs/rsl_rl/microduck_velocity_hd1910/$REWARD_ARM"
if [ -d "$REWARD_DIR" ]; then
  if "$PY" tools/hd1910/check_control_arm.py --run-dir "$REWARD_DIR" \
       --expect-abs-envs 4096 --expect-iters 3000 --expect-seed 42 \
       --expect-rel-heading 0.30 --expect-ang-vel-z 0.5 >/dev/null 2>&1; then
    echo "FAIL: the gate also accepts the reward arm ($REWARD_ARM) -- it proves nothing" >&2
    exit 5
  else
    echo "ok: gate rejects the reward arm (negative control)"
  fi
else
  echo "WARN: reward arm $REWARD_DIR not found, negative control skipped" >&2
fi

echo
echo "ok — control arm trained and verified:"
echo "  $D"
echo "next: sweep checkpoints on this run and on $REWARD_ARM with"
echo "      tools/eval_velocity_in_sim.py, then compare with"
echo "      tools/gate_p3_yaw.py --baseline-set kp8"
