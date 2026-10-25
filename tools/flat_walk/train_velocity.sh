#!/usr/bin/env bash
# Train the leg-walking task (`Mjlab-Velocity-Flat-MicroDuck`) on the mjlab/GPU stack.
#
# Why this wrapper exists
# -----------------------
# 1. `Mjlab-Velocity-Flat-MicroDuck` is an **upstream-native** task: its cfg is
#    byte-identical to `.upstream/microduck_rl-develop/...` and the joy patch does
#    not touch it. So unlike `train_joy.sh` there is no patch step here -- and a
#    config drift would be a silent bug. This script therefore fingerprints the
#    live cfg + mdp.py and refuses to start if the config changed under it.
# 2. Every hyper-parameter that has ever been guessed wrong in this project is
#    re-read from the live objects and written to `out/runmeta_<run>.json`, not
#    copied from a doc. A run must be reconstructible from that file alone.
# 3. The task's default `num_envs` is **1** (only `max_iterations` is 50000), and
#    `max_iterations` defaults to 50000. Both are easy to get wrong: a run left on
#    defaults trains one robot for a very long time. They are required here.
#
# Budget reference (measured on the RTX 4070 Laptop 8 GB):
#   4096 envs = 3.08 s/iter = ~31.8k env-steps/s  -> 12000 iter = 1179.6 M = 10.3 h
#   8192 envs = 14.13 s/iter (memory-starved)     -> 4096 is the sweet spot
#   Walkable peers needed 393-590 M env-steps; 12000x4096 clears that with ~2x margin.
#
# Usage:
#   bash tools/train_velocity.sh                    # 4096 envs, 12000 iter
#   bash tools/train_velocity.sh 4096 12000 myrun   # explicit run name
#   bash tools/train_velocity.sh --check-only       # preflight only, no GPU run
#   bash tools/train_velocity.sh --no-check 4096 600 # skip preflight (not advised)
set -euo pipefail
cd "$(dirname "$0")/.."

TASK=Mjlab-Velocity-Flat-MicroDuck
PY=.venv-mjlab/Scripts/python.exe

CHECK_ONLY=0
NO_CHECK=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --check-only) CHECK_ONLY=1 ;;
    --no-check)   NO_CHECK=1 ;;
    *)            ARGS+=("$a") ;;
  esac
done

ENVS="${ARGS[0]:-4096}"
ITERS="${ARGS[1]:-12000}"
RUN="${ARGS[2]:-vel_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"

# ---------------------------------------------------------------- solver ----
# The flat task ships microduck_rl's original contact budget: iterations=10,
# ls_iterations=20. Only the `rough` branch of the cfg raises it -- and we run
# flat, so the raise never applies. Isaac Lab's own MicroDuck port raises it for
# both, saying "microduck_rl's 10 iterations stop some contact solves short;
# MJWarp exits once every world converges".
#
# Measured on this box (64 env x 8 s replay, `out/solver_ab_*.json`):
#   iterations 10->100, ls 20->50  =>  45 s vs 43 s (free), foot peaks unchanged.
#   So this buys solver headroom against "contact under-resolved -> NaN" at
#   ~zero wall-clock cost, and does NOT change gait on its own.
# Override with SOLVER_ITERS=10 SOLVER_LS=20 to reproduce the old behaviour.
SOLVER_ITERS="${SOLVER_ITERS:-100}"
SOLVER_LS="${SOLVER_LS:-50}"

LIVE_TASKS=.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks
CFG="$LIVE_TASKS/microduck_velocity_env_cfg.py"
MDP="$LIVE_TASKS/mdp.py"
UP_CFG=.upstream/microduck_rl-develop/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py

for f in "$CFG" "$MDP"; do
  [ -f "$f" ] || { echo "missing $f -- is .venv-mjlab installed?" >&2; exit 1; }
done

sha() { "$PY" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:16])" "$1"; }

echo "==============================================================="
echo " task   $TASK"
echo " envs   $ENVS"
echo " iters  $ITERS"
echo " run    $RUN"
echo " solver iterations=$SOLVER_ITERS ls=$SOLVER_LS"
echo "==============================================================="

# ---------------------------------------------------------------- preflight --
if [ "$NO_CHECK" -eq 0 ]; then
  echo
  set +e
  "$PY" tools/check_velocity_ready.py --envs "$ENVS" --iters "$ITERS" \
        --json "out/velocity_ready_${RUN}.json"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "preflight FAILED (rc=$rc) -- fix the blocking checks or pass --no-check" >&2
    exit "$rc"
  fi
else
  echo "[--no-check] skipping preflight"
fi

[ "$CHECK_ONLY" -eq 1 ] && { echo; echo "--check-only: stopping before training"; exit 0; }

# ------------------------------------------------------------- run metadata --
# Anything that could change the meaning of the resulting checkpoint gets frozen
# here. If two runs disagree later, this file says which knobs differed.
CFG_SHA=$(sha "$CFG")
MDP_SHA=$(sha "$MDP")
if [ -f "$UP_CFG" ] && cmp -s "$UP_CFG" "$CFG"; then PRISTINE=true; else PRISTINE=false; fi

"$PY" - "$RUN" "$ENVS" "$ITERS" "$CFG_SHA" "$MDP_SHA" "$PRISTINE" "$SOLVER_ITERS" "$SOLVER_LS" <<'PYEOF'
import json, os, sys, datetime, subprocess
run, envs, iters, cfg_sha, mdp_sha, pristine, solv, solv_ls = sys.argv[1:9]
meta = {
    "run": run, "task": "Mjlab-Velocity-Flat-MicroDuck",
    "envs": int(envs), "iters": int(iters), "created": datetime.datetime.now().isoformat(timespec="seconds"),
    "cfg_sha256_16": cfg_sha, "mdp_sha256_16": mdp_sha,
    "cfg_byte_identical_to_upstream": pristine == "true",
    "switches": {k: os.environ.get(k, "0") for k in
                 ("MICRODUCK_WARM_START", "MICRODUCK_JOY_PAIR_MIN",
                  "MICRODUCK_JOY_PHASE_RSI", "MICRODUCK_JOY_SYMMETRY")},
}

# The solver budget is overridden on the command line, so the cfg sha above no
# longer describes what this run actually simulated. Record both, and never let
# a future reader assume the file was the whole story.
meta["solver"] = {"cli_iterations": int(solv), "cli_ls_iterations": int(solv_ls)}
try:
    import mjlab_microduck.tasks  # noqa: F401
    from mjlab.tasks.registry import load_env_cfg
    _e = load_env_cfg("Mjlab-Velocity-Flat-MicroDuck")
    meta["solver"]["cfg_default_iterations"] = int(_e.sim.mujoco.iterations)
    meta["solver"]["cfg_default_ls_iterations"] = int(_e.sim.mujoco.ls_iterations)
    meta["solver"]["nconmax"] = int(_e.sim.nconmax)
except Exception as e:  # noqa: BLE001
    meta["solver"]["error"] = f"{type(e).__name__}: {e}"
try:
    import mjlab_microduck.tasks  # noqa: F401
    from mjlab_microduck.tasks.microduck_velocity_env_cfg import MicroduckRlCfg as R
    meta["rl"] = {
        "actor_hidden_dims": list(R.actor.hidden_dims),
        "critic_hidden_dims": list(R.critic.hidden_dims),
        "activation": R.actor.activation,
        "obs_normalization": bool(R.actor.obs_normalization),
        "init_std": R.actor.distribution_cfg.get("init_std"),
        "std_type": R.actor.distribution_cfg.get("std_type"),
        "learning_rate": R.algorithm.learning_rate,
        "schedule": R.algorithm.schedule,
        "entropy_coef": R.algorithm.entropy_coef,
        "clip_param": R.algorithm.clip_param,
        "gamma": R.algorithm.gamma, "lam": R.algorithm.lam,
        "desired_kl": R.algorithm.desired_kl,
        "num_learning_epochs": R.algorithm.num_learning_epochs,
        "num_mini_batches": R.algorithm.num_mini_batches,
        "num_steps_per_env": R.num_steps_per_env,
    }
except Exception as e:  # noqa: BLE001
    meta["rl"] = {"error": f"{type(e).__name__}: {e}"}
os.makedirs("out", exist_ok=True)
p = f"out/runmeta_{run}.json"
open(p, "w", encoding="utf-8").write(json.dumps(meta, indent=2, ensure_ascii=False))
print(f"runmeta -> {p}")
PYEOF

LOG="out/train_${RUN}.log"

# ------------------------------------------------------------------- execute --
export MICRODUCK_WARM_START="${MICRODUCK_WARM_START:-0}"

echo
echo "log     $LOG"
echo "start   $(date '+%Y-%m-%d %H:%M:%S')"
START=$(date +%s)

set +e
.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --env.sim.mujoco.iterations "$SOLVER_ITERS" \
  --env.sim.mujoco.ls-iterations "$SOLVER_LS" \
  --agent.max-iterations "$ITERS" \
  --agent.save-interval 250 \
  --agent.logger tensorboard \
  --agent.experiment-name microduck_velocity \
  --agent.run-name "$RUN" \
  > "$LOG" 2>&1
RC=$?
set -e

ELAPSED=$(( $(date +%s) - START ))
echo "exit    $RC   elapsed $((ELAPSED/3600))h$(( (ELAPSED%3600)/60 ))m"
echo "iters   $(grep -c 'Learning iteration' "$LOG" 2>/dev/null || echo 0) logged"

if [ "$RC" -ne 0 ]; then
  echo "--- last 20 log lines ---"
  tail -20 "$LOG"
  exit "$RC"
fi

tail -3 "$LOG"
echo
echo "ckpt dir: logs/microduck_velocity/$RUN  (or out/) -- check with ls"
