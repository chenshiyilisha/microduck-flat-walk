#!/usr/bin/env bash
# Train Duckverse's continuous-joy task on our mjlab/GPU stack.
#
# Why this wrapper exists
# -----------------------
# 1. The joy files live in `.upstream/microduck_rl-develop/src`, but the package was
#    installed as a *copy* into site-packages, so `train.exe` cannot see them.
#    `PYTHONPATH` does not fix it reliably: on Windows the separator is `;`, not
#    `:`, and a bash-built `a:b` collapses to one bogus entry (this cost one run --
#    train.exe printed the task list without any Joy task and exited 1).
#    `tools/apply_joy_patch.py` therefore syncs the three changed files into
#    site-packages; this script only verifies they are there.
# 2. Recorded args -- the joy task's own defaults (600 iter, lr 3e-4, init_std .4)
#    come from the patch's `MicroduckJoyRlCfg`; everything else is chosen here and
#    written to the run name so a checkpoint can never be mistaken for another.
#
# Usage:
#   bash tools/train_joy.sh                      # BAM plant, 4096 envs, 600 iter
#   bash tools/train_joy.sh smooth 2048 600      # position-servo plant (deployable)
#   bash tools/train_joy.sh bam 2048 300 myrun
set -euo pipefail
cd "$(dirname "$0")/.."

PLANT="${1:-bam}"        # bam | pd | smooth
ENVS="${2:-4096}"
ITERS="${3:-600}"
RUN="${4:-joy_${PLANT}_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"

case "$PLANT" in
  bam)    TASK=Mjlab-Joy-Flat-MicroDuck ;;
  pd)     TASK=Mjlab-JoyPD-Flat-MicroDuck ;;
  smooth) TASK=Mjlab-JoySmoothPD-Flat-MicroDuck ;;
  *) echo "plant must be bam|pd|smooth, got '$PLANT'" >&2; exit 2 ;;
esac

JOY_MOD=.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_joy_env_cfg.py
if [ ! -f "$JOY_MOD" ]; then
  echo "missing $JOY_MOD -- run tools/apply_joy_patch.py first" >&2
  exit 1
fi

LOG="out/train_${RUN}.log"

echo "task      $TASK"
echo "envs      $ENVS"
echo "iters     $ITERS"
echo "run       $RUN"
echo "log       $LOG"
# Self-report every behaviour switch. Two runs that differ only by an env var
# otherwise produce identical-looking logs, and the difference has to be
# recoverable from the run after the fact (agent.yaml records the cfg, but not
# which switches were on when the two runs are compared side by side).
echo "switches  pair_min=${MICRODUCK_JOY_PAIR_MIN:-0} phase_rsi=${MICRODUCK_JOY_PHASE_RSI:-0} mirror=${MICRODUCK_JOY_SYMMETRY:-0} ds_weight=${MICRODUCK_JOY_DS_WEIGHT:-0}"

.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --agent.max-iterations "$ITERS" \
  --agent.save-interval 100 \
  --agent.logger tensorboard \
  --agent.experiment-name "microduck_joy_${PLANT}" \
  --agent.run-name "$RUN" \
  > "$LOG" 2>&1
echo "EXIT=$?"
grep -c "Learning iteration" "$LOG" || true
tail -3 "$LOG"
