#!/usr/bin/env bash
# HD1910 roller training on GPU.
# Task: Mjlab-Velocity-Flat-MicroDuck-Rollers (plain, no backlash) — same env the
# official roller.onnx baseline (17.2% fall) was measured on, so the trained
# policy is apple-to-apple comparable to that baseline.
#
# Plant: hd1910_kp8 (kp_fw=8, deployment plant) — MUST match the roller.onnx eval
# baseline. The live plant is asserted below; do not run under a different plant.
#
# "Based on roller.onnx" = benchmark against it (beat 17.2% fall). roller.onnx is
# B-gen trained with embedded norm + action_scale=0.8; direct weight warm-start
# crosses the norm/action-scale boundary and is avoided (silent-bug risk). Trained
# from scratch on the HD1910 plant instead.
#
# Override: ENVS=4096 ITERS=4000 SAVE=100 MUJOCO_ITERS=10 MUJOCO_LS_ITERS=10 bash tools/hd1910/train_roller.sh [run_name]
#
# MUJOCO_ITERS / MUJOCO_LS_ITERS: mujoco 求解器迭代次数。默认 10（平地任务官方默认）。
# 注意：此前用 100/50 在 Windows WDDM 驱动下触发 TDR（显卡超时重置）-> CUDA error: unknown
# -> 训练崩溃成僵尸（见 microduck-software/out/train_hd1910_roller_formal_1107_formal.CRASHED.log）。
# 高迭代使单步求解内核过重，易超 TDR 阈值；降到 10 规避。如需更高接触精度可调大，但需关注 TDR。
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
ENVS="${ENVS:-64}"
ITERS="${ITERS:-5}"
SAVE="${SAVE:-${ITERS}}"
SEED="${SEED:-42}"   # fixed seed -> reproducible run, captured in provenance
RUN="${1:-hd1910_roller_${ENVS}x${ITERS}_$(date +%m%d_%H%M)}"
TASK=Mjlab-Velocity-Flat-MicroDuck-Rollers
DEVICE="${MICRODUCK_DEVICE:-cuda:0}"

export MUJOCO_GL=glfw
if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
  unset CUDA_VISIBLE_DEVICES || true
fi

echo "== GPU / GL =="
echo "MUJOCO_GL=$MUJOCO_GL  device=$DEVICE  task=$TASK  envs=$ENVS  iters=$ITERS"
"$PY" -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('cuda', torch.cuda.get_device_name(0))"

echo "== plant check (must be hd1910_kp8 / kp_fw=8) =="
"$PY" tools/hd1910/apply_to_live.py --check
DET=$("$PY" -c "import json,subprocess,sys; d=json.loads(subprocess.check_output([sys.executable,'tools/hd1910/apply_to_live.py','--check','--json'])); print(d['detected']); raise SystemExit(0 if d.get('detected')=='hd1910_kp8' and d.get('kp_fw')==8.0 else 1)")
echo "detected $DET"

mkdir -p out
"$PY" tools/hd1910/apply_to_live.py --check --json > "out/plant_${RUN}.json"
"$PY" -c "
import json, hashlib, pathlib
p=pathlib.Path('tools/bam_params/hd1910/official_m6_stslaw.json')
meta={
  'run': '$RUN', 'task': '$TASK',
  'plant': 'hd1910_kp8', 'kp_fw': 8.0,
  'device': '$DEVICE', 'gpu_ids': [0], 'mujoco_gl': 'glfw',
  'official_m6_stslaw_sha256_16': hashlib.sha256(p.read_bytes()).hexdigest()[:16],
  'delay_min_lag': 3, 'delay_max_lag': 6,
  'envs': $ENVS, 'iters': $ITERS,
  'baseline': 'official roller.onnx on this env = 17.2% fall',
  'ref': 'HD1910 roller retrain; beat roller.onnx baseline; kp8=deploy plant',
}
pathlib.Path('out/runmeta_${RUN}.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
print('runmeta -> out/runmeta_${RUN}.json')
"
"$PY" tools/hd1910/log_run_provenance.py --run "$RUN" --seed "$SEED" --via "$0"

LOG="out/train_${RUN}.log"
echo "== roller train $RUN envs=$ENVS iters=$ITERS (GPU cuda:0) =="
echo "log $LOG"
set +e
.venv-mjlab/Scripts/train.exe "$TASK" \
  --env.scene.num-envs "$ENVS" \
  --env.sim.mujoco.iterations "${MUJOCO_ITERS:-10}" \
  --env.sim.mujoco.ls-iterations "${MUJOCO_LS_ITERS:-10}" \
  --agent.max-iterations "$ITERS" \
  --agent.save-interval "$SAVE" \
  --gpu-ids '[0]' \
  --agent.logger tensorboard \
  --agent.experiment-name microduck_roller_hd1910 \
  --agent.run-name "$RUN" \
  --agent.seed "$SEED" \
  > "$LOG" 2>&1
RC=$?
set -e
echo "exit $RC"
if [ "$RC" -ne 0 ]; then
  echo "--- last 40 log lines ---"
  tail -40 "$LOG"
  exit "$RC"
fi
grep -q "Training with: device=cuda:0" "$LOG" || {
  echo "FAIL: expected device=cuda:0 in log"
  grep -E "Training with: device=" "$LOG" || true
  exit 2
}
tail -8 "$LOG"
echo "ok — roller train $RUN passed; stamps: out/plant_${RUN}.json / out/runmeta_${RUN}.json / log $LOG"
