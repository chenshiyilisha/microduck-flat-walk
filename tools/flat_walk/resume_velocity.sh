#!/usr/bin/env bash
# Resume a `Mjlab-Velocity-Flat-MicroDuck` run from its latest checkpoint.
#
# Why this wrapper exists
# -----------------------
# `train.exe --agent.resume True` on its own is actually SAFE for checkpoint
# selection -- but only by accident, and the docs say the opposite, so this
# wrapper exists to make the choice explicit and auditable.
#
# What the code really does:
#   * rsl_rl writes `model_{it}.pt` with NO zero padding
#       (rsl_rl/runners/on_policy_runner.py:129)
#   * mjlab then sorts candidates by a zero-padded key, not raw name:
#       mjlab/utils/os.py:61  ->  model_checkpoints.sort(key=lambda m: f"{m:0>15}")
#     so "model_250.pt" -> "00000model_250.pt", "model_11750.pt" ->
#     "0model_11750.pt", and the padded order IS numeric. Verified: given
#     {0,250,500,9750,10000,11750,12000} it picks model_12000.pt.
#   * BUT the docstring (mjlab/utils/os.py:33-35) and `train.exe --help` both
#     claim "latest alphabetical order", which is the raw-name order and would
#     wrongly pick model_9750.pt. Docs are stale; code is right.
# Net: no silent regression today. Do not trust the help text, trust line 61.
# This script still sorts numerically and refuses to guess, so that a future
# refactor of that sort key cannot silently change which checkpoint we resume.
#
# Second trap: do NOT set MICRODUCK_WARM_START=1 when resuming a run that was
# only interrupted. That env var (mjlab_microduck/tasks/mdp.py:118-146, "Patch 5")
# deliberately zeroes `env.common_step_counter` so every step-based curriculum
# re-ramps from stage 0 -- right for "start a new experiment from an old
# checkpoint", wrong for "continue where I left off".
# Left unset, the counter is restored from the checkpoint
#   (mjlab/rl/runner.py:138-142, from infos["env_state"]["common_step_counter"];
#    verified present in our own model_0.pt: common_step_counter = 24)
# and the curriculum picks up where it stopped -- e.g. action_rate_l2 stays at
# whatever stage (microduck_velocity_env_cfg.py:776-790) instead of snapping
# back to the -0.1 stage 0.
#
# Third trap (the expensive one): --agent.max-iterations is a DELTA, not a
# target. rsl_rl 5.0.1 on_policy_runner.py:78-79:
#     start_it = self.current_learning_iteration      # restored from the ckpt
#     total_it = start_it + num_learning_iterations
# so `--agent.max-iterations 12000` while resuming from model_10000 runs to
# 22000. No error, no warning, just ~10 extra hours. This script takes TARGET
# (absolute) and passes the remainder.
#
# Usage:
#   bash tools/resume_velocity.sh                  # newest run, numerically newest ckpt
#   bash tools/resume_velocity.sh <run_dir_name> <model_N.pt>
#   TARGET=8000 bash tools/resume_velocity.sh       # stop earlier than 12000
#   SOLVER_ITERS=10 SOLVER_LS=20 bash tools/resume_velocity.sh   # must match the original run
set -euo pipefail
cd "$(dirname "$0")/.."

TASK=Mjlab-Velocity-Flat-MicroDuck
PY=.venv-mjlab/Scripts/python.exe
EXP=microduck_velocity
ROOT=logs/rsl_rl/$EXP

SOLVER_ITERS="${SOLVER_ITERS:-100}"
SOLVER_LS="${SOLVER_LS:-50}"

[ -d "$ROOT" ] || { echo "no runs under $ROOT -- nothing to resume" >&2; exit 1; }

if [ $# -ge 2 ]; then
  RUN="$1"; CKPT="$2"
else
  # Pick the run directory with the newest mtime, then the numerically largest ckpt in it.
  read -r RUN CKPT < <("$PY" - "$ROOT" <<'PYEOF'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
runs = [p for p in root.iterdir() if p.is_dir() and p.name != "wandb_checkpoints"]
runs = [p for p in runs if any(p.glob("model_*.pt"))]
if not runs:
    sys.exit("no run directory contains a checkpoint")
run = max(runs, key=lambda p: max(f.stat().st_mtime for f in p.glob("model_*.pt")))
ckpts = []
for f in run.glob("model_*.pt"):
    m = re.fullmatch(r"model_(\d+)\.pt", f.name)
    if m:
        ckpts.append((int(m.group(1)), f.name))
if not ckpts:
    sys.exit(f"no model_N.pt in {run}")
print(run.name, max(ckpts)[1])
PYEOF
)
fi

# Windows: python's print() emits CRLF, `read -r` strips only the LF and keeps
# the \r, so "$ROOT/$RUN/$CKPT" silently becomes a path that cannot exist and
# the script dies with "missing checkpoint" for a file that is right there.
RUN="${RUN%$'\r'}"
CKPT="${CKPT%$'\r'}"

CKPT_PATH="$ROOT/$RUN/$CKPT"
[ -f "$CKPT_PATH" ] || { echo "missing checkpoint: $CKPT_PATH" >&2; exit 1; }

# rsl_rl 5.0.1 treats --agent.max-iterations as "how many MORE iterations to
# run", not as the absolute target: on_policy_runner.py:78-79 does
#     start_it  = self.current_learning_iteration   # restored from the ckpt
#     total_it  = start_it + num_learning_iterations
#     for it in range(start_it, total_it):
# so passing 12000 while resuming from model_10000 trains to 22000 -- a silent
# 10-hour overspend with no warning. Convert a target into a remainder here.
TARGET="${TARGET:-12000}"
DONE=$(echo "$CKPT" | sed -n 's/^model_\([0-9]\+\)\.pt$/\1/p')
if [ -z "$DONE" ]; then
  echo "cannot parse iteration from '$CKPT' (expected model_<N>.pt) -- set TARGET carefully by hand" >&2
  exit 1
fi
REMAIN=$((TARGET - DONE))
if [ "$REMAIN" -le 0 ]; then
  echo "checkpoint $CKPT is already at/after TARGET=$TARGET iterations -- nothing to do." >&2
  exit 0
fi

# Show what will be loaded, and what else is in the run -- so a wrong pick is visible.
"$PY" - "$ROOT/$RUN" "$CKPT" <<'PYEOF'
import re, sys
from pathlib import Path
d, pick = Path(sys.argv[1]), sys.argv[2]
ck = sorted(((int(m.group(1)), f.name) for f in d.glob("model_*.pt")
             if (m := re.fullmatch(r"model_(\d+)\.pt", f.name))))
print(f"run         {d.name}")
print(f"checkpoints {len(ck)}  ({ck[0][1]} .. {ck[-1][1]})")
print(f"resuming    {pick}   <-- explicit, not alphabetical")
PYEOF

echo "==============================================================="
echo " task   $TASK"
echo " run    $RUN"
echo " from   $CKPT"
echo " solver iterations=$SOLVER_ITERS ls=$SOLVER_LS"
echo " budget $DONE -> $TARGET   (passing --agent.max-iterations $REMAIN, NOT $TARGET)"
echo "==============================================================="

LOG="out/resume_${RUN}.log"
echo "log     $LOG"
echo "start   $(date '+%Y-%m-%d %H:%M:%S')"
echo

# Guard: never let a second trainer share the GPU with a live one. Two runs at
# 4096 envs on an 8 GB card will either OOM or halve each other's speed, and the
# failure mode looks like "training got slow", not like an error.
if command -v nvidia-smi >/dev/null 2>&1; then
  BUSY=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . || true)
  if [ "${BUSY:-0}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
    echo "REFUSING: $BUSY process(es) already use the GPU -- a trainer is probably live." >&2
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader >&2
    echo "Stop it first, or re-run with FORCE=1 if those processes are unrelated." >&2
    exit 1
  fi
fi

# Inspection mode: prints the plan and exits before touching the GPU.
if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1 -- plan printed above, nothing launched."
  exit 0
fi

# MICRODUCK_WARM_START deliberately NOT set: we want the curriculum to continue
# from the checkpoint's step counter, not restart at stage 0.
unset MICRODUCK_WARM_START

.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "${ENVS:-4096}" \
  --env.sim.mujoco.iterations "$SOLVER_ITERS" \
  --env.sim.mujoco.ls-iterations "$SOLVER_LS" \
  --agent.resume True \
  --agent.load-run "$RUN" \
  --agent.load-checkpoint "$CKPT" \
  --agent.max-iterations "$REMAIN" \
  --agent.save-interval 250 \
  --agent.logger tensorboard \
  --agent.experiment-name "$EXP" \
  --agent.run-name "${RUN}_resume_$(date +%m%d_%H%M)" \
  > "$LOG" 2>&1

echo "done. tail of log:"
tail -5 "$LOG"
