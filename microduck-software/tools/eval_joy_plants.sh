#!/usr/bin/env bash
# Evaluate one checkpoint under several plants, one variable at a time.
#
# The point is attribution. A single number from a single plant cannot tell you
# whether a policy learned to step or learned to exploit the servo model it was
# trained on. Running the *same weights* through the same task with only
# `articulation.actuators` + `spec_fn` swapped gives a table where the only
# difference between rows is the plant.
#
#   default : what the task ships (XML <position kp=0.55> for JoySmoothPD)
#   bam     : upstream voltage-law model (FrictionDRBamActuatorCfg, XL330, kp_fw=200)
#
# Usage:
#   bash tools/eval_joy_plants.sh <checkpoint> [tag] [num_envs] [seconds]
#
# The action term is deliberately left alone by --plant, so the alpha=.25 /
# max_step=.08 conditioner stays identical across rows. Without that, a
# comparison runs the policy in an action space it was never trained in and the
# difference cannot be attributed to the plant.

set -uo pipefail

CKPT="${1:?usage: eval_joy_plants.sh <checkpoint> [tag] [num_envs] [seconds]}"
TAG="${2:-$(basename "$(dirname "$CKPT")")}"
NUM_ENVS="${3:-64}"
SECONDS_EVAL="${4:-8.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv-mjlab/Scripts/python.exe"
TASK="${TASK:-Mjlab-JoySmoothPD-Flat-MicroDuck}"

echo "checkpoint : $CKPT"
echo "task       : $TASK"
echo "envs       : $NUM_ENVS   seconds: $SECONDS_EVAL"
echo

for PLANT in default bam; do
  OUT="$ROOT/out/eval_joy_${TAG}_${PLANT}.json"
  echo "==================== plant=$PLANT ===================="
  "$PY" "$ROOT/tools/eval_joy_in_sim.py" \
    --task "$TASK" \
    --checkpoint "$CKPT" \
    --num-envs "$NUM_ENVS" \
    --seconds "$SECONDS_EVAL" \
    --plant "$PLANT" \
    --out "$OUT" 2>&1 | tail -28
  echo
done

echo "==================== side by side ===================="
"$PY" - "$ROOT/out/eval_joy_${TAG}_default.json" "$ROOT/out/eval_joy_${TAG}_bam.json" <<'PYEOF'
import json, sys
rows = []
for path in sys.argv[1:]:
    try:
        d = json.load(open(path))
    except FileNotFoundError:
        print(f"missing: {path}")
        continue
    rows.append((d["plant"]["plant"], d["gates"], d.get("context", {})))

if len(rows) < 2:
    raise SystemExit(0)

gates = list(rows[0][1].keys())
w = 34
print(f"{'gate':<{w}}" + "".join(f"{r[0]:>16}" for r in rows) + "   note")
print("-" * (w + 16 * len(rows) + 8))
for g in gates:
    vals = []
    for _, gg, _ in rows:
        v = gg[g]
        vals.append(f"{v['value']:>10.5f}{'  ' if v['pass'] else ' !'}")
    print(f"{g:<{w}}" + "".join(f"{v:>16}" for v in vals))

print()
# These two decide whether the 8hz row is even readable.
for key in ("8hz_gate_channel", "8hz_gate_interpretable", "foot_ac_rms_m", "knee_ac_rms_rad"):
    vals = [str(r[2].get(key)) for r in rows]
    print(f"{key:<{w}}" + "".join(f"{v:>16}" for v in vals))
PYEOF
