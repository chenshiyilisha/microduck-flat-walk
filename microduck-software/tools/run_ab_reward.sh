#!/usr/bin/env bash
# Paired A/B on the reward side only. Both arms start from the same checkpoint and run the
# same number of iterations with the same seed; the ONLY difference is whether DuckBuddy's
# straightness terms are on. Judged on heading_error_deg_median / lateral_m under
# tools/robustness.py, open loop and with the deployed heading loop -- not on `track`,
# which the gait's own sway can keep high while the duck veers off.
set -u
cd "$(dirname "$0")/.." || exit 1
PY=.venv/Scripts/python
ITERS=${ITERS:-400}

BASE="--init out/robust61_a.pt --iterations $ITERS --upstream-rewards --curriculum --upstream-commands"
EXTRA="--yaw-drift 1.5 --lin-tight tight"

echo "=== arm ctl: upstream recipe only ==="
$PY repo/train_robust.py $BASE --out out/ab_ctl.pt > out/train_ab_ctl.log 2>&1
echo "ctl exit=$?"

echo "=== arm db: + yaw_drift 1.5 + lin_tight ==="
$PY repo/train_robust.py $BASE $EXTRA --out out/ab_db.pt > out/train_ab_db.log 2>&1
echo "db exit=$?"

CONDS=nominal,push_0.3mps
for arm in ctl db; do
  for loop in open hold; do
    LOG=out/ab_${arm}_${loop}.log
    if [ "$loop" = hold ]; then FLAGS="--heading-hold --heading-stiffness 0.7"; else FLAGS=""; fi
    $PY tools/robustness.py --policy out/ab_${arm}.pt --conditions $CONDS \
      --seconds 8 --envs 8 --seeds 3 --seed 0 $FLAGS \
      --out out/ab_${arm}_${loop}.json > $LOG 2>&1
    echo "eval $arm/$loop exit=$?"
  done
done
echo "=== ALL DONE ==="
