#!/usr/bin/env bash
# Sweep checkpoints of the two heading arms through the SAME eval, so the A/B is
# decided on a checkpoint chosen by an outer sweep rather than by "the last one".
#
# Why a sweep and not model_2999
# ------------------------------
# This repo has no best-by-eval selection: rsl_rl writes model_<iter>.pt every
# SAVE iterations and the last one is whatever the run happened to end on.
# Checkpoint-to-checkpoint jitter has been the dominant term in every previous
# comparison here, so the arm's number is defined as the sweep, and the ckpt is
# picked afterwards (see tools/hd1910/summarize_heading_ab.py).
#
# Arm A = reward arm, arm B = reward-free control (explore_heading_control.sh).
# Both are evaluated with the exact flags the frozen `--baseline-set kp8`
# numbers used (32 env x 8 s, cmd 0.4, seed 11, solver 100/50), so the outputs
# are directly comparable with artifacts/flat_walk/evals/p8head_ref/.
#
# Usage
#   bash tools/hd1910/sweep_heading_arms.sh            # last+stride picks, both arms
#   STRIDE=100 bash tools/hd1910/sweep_heading_arms.sh # every save
#   ENVS=8 SECONDS=2 STRIDE=500 bash tools/hd1910/sweep_heading_arms.sh  # plumbing test
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe

ARM_A="${ARM_A:-2026-11-03_08-33-18_p8head_030_4096x3000}"     # rewards
ARM_B="${ARM_B:-}"                                              # control
if [ -z "$ARM_B" ]; then
  # newest p8ctl_* run; fail loudly rather than evaluating nothing.
  # Exclude smoke runs -- *_p8ctl_smoke_* also matches the glob and sorts into
  # the same namespace, so picking "newest p8ctl" by date alone can land on a
  # 2-checkpoint plumbing run and quietly produce a bogus A/B.
  ARM_B=$(ls -d logs/rsl_rl/microduck_velocity_hd1910/*_p8ctl_* 2>/dev/null \
            | grep -v smoke | sort | tail -1 | xargs -r basename || true)
fi
if [ -z "$ARM_B" ]; then
  echo "FAIL: no control run (*_p8ctl_*) found; run explore_heading_control.sh first" >&2
  exit 2
fi

STRIDE="${STRIDE:-300}"
ENVS="${ENVS:-32}"
SECONDS_PER_RUN="${SECONDS_PER_RUN:-8}"
SEED="${SEED:-11}"
CMD_VX="${CMD_VX:-0.4}"
OUT_ROOT="${OUT_ROOT:-../artifacts/flat_walk/evals/ab_heading}"
# 域可换（默认无齿隙 Flat）。齿隙域：TASK=Mjlab-Velocity-Flat-Backlash-MicroDuck
TASK="${TASK:-Mjlab-Velocity-Flat-MicroDuck}"
case "$TASK" in
  *Backlash*) TASK_TAG="_bl" ;;
  *) TASK_TAG="" ;;
esac

find_run() {
  local name="$1" d=""
  # accept a full path, "2026-11-03_08-33-18_xxx", or just the run-name suffix "xxx"
  if [ -d "$name" ]; then echo "$name"; return 0; fi
  d=$(ls -d "logs/rsl_rl/microduck_velocity_hd1910/$name" 2>/dev/null | sort | tail -1) || true
  if [ -z "$d" ]; then
    d=$(ls -d logs/rsl_rl/microduck_velocity_hd1910/*_"$name" 2>/dev/null | sort | tail -1) || true
  fi
  if [ -z "$d" ]; then
    d=$(ls -d logs/rsl_rl/microduck_velocity_hd1910/*"$name"* 2>/dev/null | sort | tail -1) || true
  fi
  if [ -z "$d" ]; then echo "FAIL: no run dir for $name" >&2; return 2; fi
  echo "$d"
}
DIR_A=$(find_run "$ARM_A")
DIR_B=$(find_run "$ARM_B")

echo "== A (rewards)  $DIR_A"
echo "== B (control)  $DIR_B"
echo "== eval: ${ENVS}env x ${SECONDS_PER_RUN}s cmd_vx=$CMD_VX seed=$SEED stride=$STRIDE"

# Same plant as training; the JSON stamps it, and gate_p3_yaw refuses a mismatch.
"$PY" tools/hd1910/apply_to_live.py --check 2>&1 | tail -3

eval_one() {
  local arm="$1" dir="$2" ckpt="$3"
  local tag; tag=$(basename "$ckpt" .pt)
  local out="$OUT_ROOT/$arm/${tag}_vx${CMD_VX}_s${SEED}_e${ENVS}t${SECONDS_PER_RUN}${TASK_TAG}.json"
  if [ -f "$out" ]; then
    echo "  skip $arm/$tag (have $out)"
    return 0
  fi
  mkdir -p "$(dirname "$out")"
  # eval_velocity_in_sim.py exits non-zero when its own single-run gates fail
  # (tracks_half_command etc). Those gates are per-run diagnostics, not verdicts:
  # a sweep only needs the metrics, which are written before the exit code is
  # decided. So tolerate the code, but refuse to continue without the JSON.
  set +e
  "$PY" tools/eval_velocity_in_sim.py --task "$TASK" \
    --checkpoint "$ckpt" --num-envs "$ENVS" --seconds "$SECONDS_PER_RUN" \
    --device cuda:0 --cmd-vx "$CMD_VX" --seed "$SEED" \
    --solver-iters 100 --solver-ls 50 --out "$out" \
    > /dev/null 2>"${out%.json}.err"
  local rc=$?
  set -e
  if [ ! -f "$out" ]; then
    echo "  FAIL $arm/$tag (rc=$rc, no JSON written); last lines:"
    tail -5 "${out%.json}.err" | sed 's/^/    /'
    return 1
  fi
  if [ "$rc" -ne 0 ]; then
    echo "  note $arm/$tag: eval rc=$rc (its own gates failed; metrics are in the JSON)"
  fi
  "$PY" - "$out" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
pm, sp, st = d['official_metrics'], d['speed'], d['stability']
print(f"  {d['checkpoint'].split('/')[-1].split(chr(92))[-1]:16s} vx={sp['vx_mean']:.4f} "
      f"err_xy={pm['error_vel_xy']:.4f} err_yaw={pm['error_vel_yaw']:.4f} "
      f"fall={st['terminated_frac']:.3f}")
EOF
}

sweep_arm() {
  local arm="$1" dir="$2"
  local all last
  all=$(ls "$dir"/model_*.pt | sort -V)
  last=$(echo "$all" | tail -1)
  echo "== $arm ($(echo "$all" | wc -l) ckpts)"
  local k bad=0
  for f in $all; do
    k=$(basename "$f" .pt); k=${k#model_}
    if [ "$k" -eq 0 ] || [ $((k % STRIDE)) -eq 0 ] || [ "$f" = "$last" ]; then
      eval_one "$arm" "$dir" "$f" || bad=$((bad + 1))
    fi
  done
  if [ "$bad" -gt 0 ]; then
    echo "  $arm: $bad checkpoint(s) produced no JSON" >&2
    return 1
  fi
}

sweep_arm A "$DIR_A"
sweep_arm B "$DIR_B"

echo
echo "ok — swept into $OUT_ROOT/{A,B}"
echo "next: $PY tools/hd1910/summarize_heading_ab.py --a-dir $OUT_ROOT/A --b-dir $OUT_ROOT/B"
