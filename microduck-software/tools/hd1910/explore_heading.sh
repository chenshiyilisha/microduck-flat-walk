#!/usr/bin/env bash
# HD1910 velocity explore on GPU **with heading closed loop** (P3/P8 retrain).
#
# P3 target plant is hd1910_kp5 (kp_fw=5.0), so the old explore_train.sh gate
# (detected=hd1910 / kp_fw=32.0) will fail after the P3 switch. This script is
# the P3-era replacement: P3 plant gate + train_heading_variant.py
# (--rel-heading-envs) so the heading knob actually executes in the run.
#
# PLANT=p8 runs the same recipe on the bench sweet-spot plant (kp_fw=8.0, same
# params JSON and control law). The gate below is derived from PLANT so the two
# cannot be confused -- training on one plant and believing it was the other is
# the XL330<->HD1910 incident all over again.
#
# Default 4096x2000 per RL_duck throughput note. The heading retrain must be
# **one** run that merges P3 plant + rel_heading_envs>0 (task change => retrain).
#
# Override: PLANT=p8 ENVS=8192 ITERS=6000 REL_HEADING=0.50 bash tools/hd1910/explore_heading.sh [run_name]
#
# ⚠️ The heading REWARD recipe is part of the comparison, not decoration. Until
# 2026-11-03 this script passed only --rel-heading-envs, so runs launched from
# here carried no heading_hold / heading_tracking rewards at all and were NOT
# comparable with the p3head_rw_* line (which had them). Defaults below must
# match tools/hd1910/resume_heading_run.py::RECIPE:
#   hold 1.0 / tracking 3.0 / ang_vel_z clip 0.5 / stages 0,1000,1750,2500
# HEADING_STAGE_ITERS is in ITERATIONS and its last mark must be strictly inside
# the run (pre-checked below), or the tracking phase never activates.
#
# PIN_ARATE=<w> (default: unset) additionally pins the action_rate_l2 penalty at a
# constant weight: the staged ramp -0.1/.../-1.0 is replaced by one stage at <w>.
# This is the single-variable test of "is the smoothing penalty what caps forward
# speed", so everything else (P3 plant, REL_HEADING, envs, iters, seed) must stay
# identical to the run it is compared against.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-4096}"
ITERS="${ITERS:-2000}"
SAVE="${SAVE:-100}"
REL_HEADING="${REL_HEADING:-0.30}"
PIN_ARATE="${PIN_ARATE:-}"
# P3 seed sweep (server_pack/p3_sweep.sh) needs distinct seeds. Previously the
# seed was left at the trainer default (42) with no CLI flag, so launching this
# script 3x produced 3 identical runs -- a silent bug, not a sweep. Default 42
# keeps every archived run name/behaviour byte-identical; only SEED != 42 tags
# the run name so repeated launches cannot collide inside the same minute.
SEED="${SEED:-42}"
# --- heading reward recipe -------------------------------------------------
# These were missing for a long time: the script drove only --rel-heading-envs,
# so a run launched from here carried NO heading rewards at all and was not
# comparable with the p3head_rw_* line (hold 1.0 / tracking 3.0 / clip 0.5).
# Keep in sync with tools/hd1910/resume_heading_run.py::RECIPE.
HEADING_HOLD="${HEADING_HOLD:-1.0}"
HEADING_TRACKING="${HEADING_TRACKING:-3.0}"
ANG_VEL_Z_CLIP="${ANG_VEL_Z_CLIP:-0.5}"
HEADING_STAGE_ITERS="${HEADING_STAGE_ITERS:-0,1000,1750,2500}"
PLANT="${PLANT:-p3}"
# E4-5 (low-level retrain, resampling window experiment): single-variable tyro
# overrides forwarded verbatim (word-split) to train_heading_variant.py, exactly
# like tools/train_velocity.sh's EXTRA_ARGS. This keeps the kp8 BAM plant
# injection in this wrapper (the one thing option A would make a human redo by
# hand) while letting the twist command-resampling window vary:
#   EXTRA_ARGS="--env.commands.twist.resampling-time-range 0.1,0.5" \
#     PLANT=p8 bash tools/hd1910/explore_heading.sh myrun
# NOTE: tuple values must be comma-joined WITHOUT spaces (0.1,0.5), because the
# consumer (train_heading_variant.py) resolves them through tyro. The resolved
# EFFECTIVE value is written to heading_meta by the trainer and checked below --
# a declared override is not evidence that it took effect.
EXTRA_ARGS="${EXTRA_ARGS:-}"
# DRY=1 runs the full plant/recipe path + train_heading_variant.py --dry-run and
# records a heading_meta (with the effective resampling window), but launches no
# GPU training. Mirrors explore_heading_control.sh. Use it to verify that an
# EXTRA_ARGS override actually reaches tyro before committing to a 2.6-10.3 h run.
DRY="${DRY:-0}"
case "$PLANT" in
  p3) PLANT_ID=hd1910_official_m6_kp5; DET_EXPECT=hd1910_kp5; KP_EXPECT=5.0 ;;
  p8) PLANT_ID=hd1910_official_m6_kp8; DET_EXPECT=hd1910_kp8; KP_EXPECT=8.0 ;;
  *)  echo "PLANT must be p3 or p8 (got '$PLANT')" >&2; exit 2 ;;
esac
AR_TAG=""
if [ -n "$PIN_ARATE" ]; then AR_TAG="_ar${PIN_ARATE}"; fi
SEED_TAG=""
if [ "$SEED" != "42" ]; then SEED_TAG="_s${SEED}"; fi
RUN="${1:-${PLANT}head_${REL_HEADING}${AR_TAG}${SEED_TAG}_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "plant=$PLANT ($PLANT_ID, expect detected=$DET_EXPECT kp_fw=$KP_EXPECT)"
echo "rel_heading=$REL_HEADING"
echo "seed=$SEED"
echo "pin_action_rate=${PIN_ARATE:-<unchanged ramp>}"
"$PY" -c "import torch; assert torch.cuda.is_available(); print('cuda', torch.cuda.get_device_name(0))"
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='$DET_EXPECT' and d.get('kp_fw')==$KP_EXPECT else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': '$PLANT_ID', 'kp_fw': $KP_EXPECT,
  'device': 'cuda:0', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  # Command-delay band actually live at launch (physics steps, 5 ms each).
  # Recorded because --delay-lag is an overlay that the next --plant wipes; a
  # run whose manifest cannot show its latency band is not comparable with one
  # that can. Bench 2026-11-03: the real servo carries ~26-45 ms more lag than
  # BAM models, so this field is the first thing to check when rehearsal delay
  # results disagree with training.
  'delay_min_lag': json.load(open('out/plant_${RUN}.json', encoding='utf-8'))['delay_min_lag'],
  'delay_max_lag': json.load(open('out/plant_${RUN}.json', encoding='utf-8'))['delay_max_lag'],
  'rel_heading_envs': $REL_HEADING,
  'heading_hold_weight': $HEADING_HOLD,
  'heading_tracking_final_weight': $HEADING_TRACKING,
  'ang_vel_z_clip': $ANG_VEL_Z_CLIP,
  'heading_stage_iters': '$HEADING_STAGE_ITERS',
  'pin_action_rate_weight': ('${PIN_ARATE}' or None),
  'expected_heading_x_forward_overlap': $REL_HEADING * 0.20,
  'envs': $ENVS, 'iters': $ITERS, 'seed': $SEED,
  # E4-5: declare the single-variable override here. The EFFECTIVE resolved
  # window is NOT copied from this string -- it is read back from tyro by
  # train_heading_variant.py into heading_meta_<run>.json under
  # `resampling_time_range_effective`. Keep declaration and evidence separate:
  # a declared override is not proof it took effect.
  'extra_args': '$EXTRA_ARGS',
  'ref': '$PLANT plant ($PLANT_ID) + heading closed loop (yaw gap fix)',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"

# Fast fail before 4096 envs are built: mdp.reward_weight applies a stage only
# while common_step_counter > step, so a last mark >= the run length is a stage
# that never fires (docs/archive/05-flat-walk.md §17.2 — the shipped 0,1000,1750,2500
# table silently trained 0 iterations at tracking weight 3.0 on a 2500 run).
LAST_STAGE="${HEADING_STAGE_ITERS##*,}"
if [ "$LAST_STAGE" -ge "$ITERS" ]; then
  echo "FAIL: --heading-stage-iters last mark $LAST_STAGE >= iters $ITERS;" \
       "the tracking phase would never activate" >&2
  exit 2
fi
echo "heading: hold=$HEADING_HOLD tracking=$HEADING_TRACKING clip=$ANG_VEL_Z_CLIP" \
     "stages=$HEADING_STAGE_ITERS (last mark $LAST_STAGE < iters $ITERS)"

LOG="out/train_${RUN}.log"
echo "== explore_heading $RUN envs=$ENVS iters=$ITERS (GPU) =="
echo "log $LOG"
echo "extra_args=${EXTRA_ARGS:-<none>}  dry=${DRY}"
set +e
AR_FLAG=""
if [ -n "$PIN_ARATE" ]; then AR_FLAG="--pin-action-rate $PIN_ARATE"; fi
# Single source of truth for the training flags: DRY and the real run consume
# this SAME array, so a --dry-run check cannot drift from what the 10 h job sees.
# EXTRA_ARGS is appended verbatim (word-split), like train_velocity.sh; tuple
# values must be space-free (0.1,0.5). The resolved effective values are read
# back from live objects by train_heading_variant.py and written to heading_meta.
TRAIN_FLAGS=(
  --rel-heading-envs "$REL_HEADING"
  --heading-hold-weight "$HEADING_HOLD"
  --heading-tracking-final-weight "$HEADING_TRACKING"
  --ang-vel-z-clip "$ANG_VEL_Z_CLIP"
  --heading-stage-iters "$HEADING_STAGE_ITERS"
)
# shellcheck disable=SC2206  # deliberate word-split: "--pin-action-rate <w>" is 2 words
if [ -n "$AR_FLAG" ]; then TRAIN_FLAGS+=($AR_FLAG); fi
TRAIN_FLAGS+=(
  --task "$TASK"
  --env.scene.num-envs "$ENVS"
  --env.sim.mujoco.iterations 100
  --env.sim.mujoco.ls-iterations 50
  --agent.max-iterations "$ITERS"
  --agent.save-interval "$SAVE"
  --agent.seed "$SEED"
  --gpu-ids '[0]'
  --agent.logger tensorboard
  --agent.experiment-name microduck_velocity_hd1910
)
# shellcheck disable=SC2206  # deliberate word-split: mirrors train_velocity.sh EXTRA_ARGS
EXTRA_ARR=( $EXTRA_ARGS )

if [ "$DRY" = "1" ]; then
  echo "== DRY: resolved variant + effective resampling window, no training =="
  "$PY" tools/train_heading_variant.py \
    "${TRAIN_FLAGS[@]}" "${EXTRA_ARR[@]}" \
    --agent.run-name "dryrun_${RUN}" --dry-run 2>&1 | tail -20
  RC=${PIPESTATUS[0]}
  set -e
  if [ "$RC" -ne 0 ]; then
    echo "FAIL: --dry-run rejected the resolved config (rc=$RC)" >&2
    exit "$RC"
  fi
  echo "DRY ok — launch without DRY=1 to train"
  exit 0
fi

"$PY" tools/train_heading_variant.py \
  "${TRAIN_FLAGS[@]}" "${EXTRA_ARR[@]}" \
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

# Gate (E4-5): when EXTRA_ARGS declares a twist resampling override, the
# EFFECTIVE value resolved by tyro (written to heading_meta + printed to the log
# by train_heading_variant.py) must equal the declared one. This is the "a
# declared override is not evidence that it took effect" check: a mistyped flag
# that tyro silently ignores, or a comma/space mistake, turns this red instead of
# letting a 10 h run train on the wrong command distribution. No-op when no
# override is declared (the task default is still recorded for provenance).
if [ -n "$EXTRA_ARGS" ]; then
  "$PY" tools/hd1910/resampling_gate.py --check \
    --meta "out/heading_meta_${RUN}.json" --extra-args "$EXTRA_ARGS" || exit 6
fi

# Gate: the action-rate pin (when requested) reached the object training uses,
# AND the training log's own curriculum telemetry agrees -- the printed readback
# is written by the same process that mutates the cfg, so it is necessary but not
# sufficient. `Curriculum/action_rate_weight` is what the env actually applied.
if [ -n "$PIN_ARATE" ]; then
"$PY" -c "
import re, sys
log = open('out/train_${RUN}.log', encoding='utf-8', errors='replace').read()
want = float('${PIN_ARATE}')
m = re.search(r'pin action_rate_l2 weight: (\S+)', log)
got = float(m.group(1)) if m else None
if got is None or abs(got - want) > 1e-9:
    print(f'FAIL: action_rate pin did not take (got={got}, want={want})')
    sys.exit(4)
if 'stages 6 -> 1' not in log:
    print('FAIL: stage table was not collapsed to a single stage')
    sys.exit(4)
print(f'ok: action_rate_l2 pinned at {got} (ramp replaced, stages 6 -> 1)')
" || exit 4
fi
tail -8 "$LOG"
echo "ok — $LOG"
