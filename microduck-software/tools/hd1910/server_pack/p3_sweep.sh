#!/usr/bin/env bash
# P3 seed sweep launcher for the Windows / 4070 Ti training server.
#
# Task #76: walk / ground_pick / standup each run >=3 seeds on the SAME plant,
# then pick a checkpoint by fixed-condition eval (p3_select.py select).
# rsl_rl has no best-checkpoint-by-eval, so an outer sweep is the only honest
# way to choose one -- the last .pt is where training stopped, not where it peaked.
#
# Why this wrapper exists: explore_heading.sh used to ignore --agent.seed, so
# launching it 3x produced three byte-identical runs at seed 42. It now accepts
# SEED (default 42, unchanged). This wrapper passes SEED explicitly and tags
# every run name so repeated launches cannot collide.
#
# Usage (Git Bash, from anywhere):
#   bash tools/hd1910/server_pack/p3_sweep.sh
#   TASKS="walk" SEEDS="42 43 44" WALK_ENVS=4096 WALK_ITERS=3000 \
#     bash tools/hd1910/server_pack/p3_sweep.sh
#   DRY_RUN=1 bash tools/hd1910/server_pack/p3_sweep.sh   # print commands only
#
# Resume: a (task,seed,envs,iters) row already recorded with status=ok is
# skipped. Delete the manifest row (or use a new MANIFEST path) to force a rerun.
set -euo pipefail
cd "$(dirname "$0")/../../.."

PY=.venv-mjlab/Scripts/python.exe
HELPER=tools/hd1910/server_pack/p3_select.py
MANIFEST="${MANIFEST:-out/p3_sweep_manifest.jsonl}"
TASKS="${TASKS:-walk ground_pick standup}"
SEEDS="${SEEDS:-42 43 44}"
PLANT="${PLANT:-p8}"          # p8 = hd1910_kp8, the current deployment plant
DRY_RUN="${DRY_RUN:-0}"

# Per-task defaults. These are the *explore* sizes from AGENTS.md; the 4070 Ti
# (12 GB) can go larger, but a sweep is a selection experiment, not a throughput
# contest. Override per task, e.g. WALK_ENVS=4096 WALK_ITERS=3000.
WALK_ENVS="${WALK_ENVS:-4096}";     WALK_ITERS="${WALK_ITERS:-2000}"
GP_ENVS="${GP_ENVS:-1024}";         GP_ITERS="${GP_ITERS:-1000}"
SU_ENVS="${SU_ENVS:-1024}";         SU_ITERS="${SU_ITERS:-1000}"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then unset CUDA_VISIBLE_DEVICES || true; fi

for f in "$PY" "$HELPER" tools/hd1910/apply_to_live.py tools/train_heading_variant.py; do
  [ -f "$f" ] || { echo "FAIL: missing $f — pack is incomplete" >&2; exit 2; }
done

echo "== P3 sweep preflight =="
"$PY" tools/hd1910/apply_to_live.py --check
"$PY" -c "
import json, subprocess, sys
d = json.loads(subprocess.check_output([sys.executable, 'tools/hd1910/apply_to_live.py', '--check', '--json']))
want = {'p8': ('hd1910_kp8', 8.0), 'p3': ('hd1910_kp5', 5.0)}['$PLANT']
assert (d.get('detected'), d.get('kp_fw')) == want, (d.get('detected'), d.get('kp_fw'), want)
print('plant', d['detected'], 'kp_fw', d['kp_fw'], '== sweep target', '$PLANT')
"
mkdir -p out

for task in $TASKS; do
  case "$task" in
    walk)
      SCRIPT=tools/hd1910/explore_heading.sh
      ENVS="$WALK_ENVS"; ITERS="$WALK_ITERS"
      EXP=microduck_velocity_hd1910
      ;;
    ground_pick)
      SCRIPT=tools/hd1910/explore_ground_pick.sh
      ENVS="$GP_ENVS"; ITERS="$GP_ITERS"
      EXP=microduck_groundpick_hd1910
      ;;
    standup)
      SCRIPT=tools/hd1910/explore_standup.sh
      ENVS="$SU_ENVS"; ITERS="$SU_ITERS"
      EXP=microduck_standup_hd1910
      ;;
    *) echo "FAIL: unknown TASK '$task' (walk|ground_pick|standup)" >&2; exit 2 ;;
  esac

  for seed in $SEEDS; do
    # run name carries task + seed + instrument so two sweeps never share a dir
    RUN="p3sweep_${task}_s${seed}_${ENVS}x${ITERS}"

    if "$PY" "$HELPER" done --manifest "$MANIFEST" --task "$task" \
        --seed "$seed" --envs "$ENVS" --iters "$ITERS" >/dev/null 2>&1; then
      echo "[skip] $task seed=$seed already recorded ok"
      continue
    fi

    echo ""
    echo "== $task seed=$seed envs=$ENVS iters=$ITERS plant=$PLANT run=$RUN =="
    CMD=(env PLANT="$PLANT" SEED="$seed" ENVS="$ENVS" ITERS="$ITERS" bash "$SCRIPT" "$RUN")
    if [ "$DRY_RUN" = "1" ]; then
      echo "[dry-run] ${CMD[*]}"
      continue
    fi

    set +e
    "${CMD[@]}"
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then
      "$PY" "$HELPER" record --manifest "$MANIFEST" --task "$task" \
        --seed "$seed" --run "$RUN" --status ok --envs "$ENVS" --iters "$ITERS" \
        --plant "$PLANT" --ckpt-glob "logs/rsl_rl/$EXP/*_$RUN"
      echo "[ok] $RUN"
    else
      "$PY" "$HELPER" record --manifest "$MANIFEST" --task "$task" \
        --seed "$seed" --run "$RUN" --status fail --envs "$ENVS" --iters "$ITERS" \
        --plant "$PLANT" --ckpt-glob "logs/rsl_rl/$EXP/*_$RUN" || true
      echo "FAIL: $task seed=$seed exited $rc — stopping sweep (fix before rerun)" >&2
      exit "$rc"
    fi
  done
done

echo ""
if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run: no training executed, no manifest written"
else
  echo "P3 sweep done. Manifest: $MANIFEST"
fi
echo "Next: $PY $HELPER select --manifest $MANIFEST --out out/p3_sweep_summary.json"
