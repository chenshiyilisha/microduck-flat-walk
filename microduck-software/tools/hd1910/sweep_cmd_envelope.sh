#!/usr/bin/env bash
# P4 前置：部署候选的 cmd 包线扫点。
#
# 为什么存在
# ----------
# kp8 参考点（--baseline-set kp8）只测了 cmd 0.4 一个点：vx 0.1629 = cmd 的 41%，
# 单次 gates 里 tracks_half_command 三 seed 全挂。m5/kp32 那条是 75%。跨 plant 不能
# 横比，但「别默认它能跑 0.4」是已经写进 §8.2 的事实 ⇒ P4 之前必须知道这条策略在
# 哪个 cmd 档位上开始塌（vx/cmd 曲线的斜率和截距），否则部署侧选速度档没有依据。
#
# 口径与冻结基线一致：32 env × 8 s / solver 100/50 / seeds 11·22·33 / plant kp8。
# 每个 (cmd, seed) 一份 JSON，汇总只做 mean±sem（N=3 只分辨 ≥50% 效应，不作判决；
# 判决闸门是 gate_p3_yaw.py 的事——这里只报数）。
#
# 用法
# ----
#   bash tools/hd1910/sweep_cmd_envelope.sh <ckpt路径> [run标签]
#   CMDS="0.15 0.2 0.3 0.4" SEEDS="11 22 33"   # 可覆盖
#   DRY=1 只打印将执行的命令
set -euo pipefail
cd "$(dirname "$0")/../.."   # microduck-software/

PY=.venv-mjlab/Scripts/python.exe
CKPT="${1:?usage: sweep_cmd_envelope.sh <ckpt.pt> [tag]}"
TAG="${2:-envelope}"
CMDS="${CMDS:-0.15 0.2 0.3 0.4}"
SEEDS="${SEEDS:-11 22 33}"
ENVS="${ENVS:-32}"
SECONDS_PER_RUN="${SECONDS_PER_RUN:-8}"
OUT_ROOT="${OUT_ROOT:-../artifacts/flat_walk/evals/cmd_envelope}"
# 域可换（默认无齿隙 Flat）。齿隙域：TASK=Mjlab-Velocity-Flat-Backlash-MicroDuck
TASK="${TASK:-Mjlab-Velocity-Flat-MicroDuck}"
case "$TASK" in
  *Backlash*) TASK_TAG="_bl" ;;
  *) TASK_TAG="" ;;
esac
DEVICE="${DEVICE:-cuda:0}"

[ -f "$CKPT" ] || { echo "FAIL: ckpt not found: $CKPT" >&2; exit 2; }
name=$(basename "$CKPT" .pt)

run_one() {
  local cmd="$1" seed="$2"
  local out="$OUT_ROOT/${TAG}/${name}_vx${cmd}_s${seed}${TASK_TAG}.json"
  if [ -f "$out" ]; then echo "  skip vx=$cmd s=$seed (have $out)"; return 0; fi
  mkdir -p "$(dirname "$out")"
  echo "  eval vx=$cmd seed=$seed -> $out"
  if [ "${DRY:-0}" = "1" ]; then return 0; fi
  MUJOCO_GL=glfw "$PY" tools/eval_velocity_in_sim.py --task "$TASK" \
    --checkpoint "$CKPT" --num-envs "$ENVS" --seconds "$SECONDS_PER_RUN" \
    --device "$DEVICE" --cmd-vx "$cmd" --seed "$seed" \
    --solver-iters 100 --solver-ls 50 --out "$out" > /dev/null
  [ -f "$out" ] || { echo "FAIL: no JSON for vx=$cmd s=$seed" >&2; exit 2; }
}

echo "== cmd envelope: $name (plant must be hd1910_kp8) =="
echo "   task=$TASK cmds=[$CMDS] seeds=[$SEEDS] ${ENVS}env x ${SECONDS_PER_RUN}s"
for cmd in $CMDS; do
  for seed in $SEEDS; do
    run_one "$cmd" "$seed"
  done
done

if [ "${DRY:-0}" = "1" ]; then echo "(DRY=1, nothing ran)"; exit 0; fi

# 汇总：只报 mean±sem 与 vx/cmd 比值，不作判决
"$PY" - "$OUT_ROOT/$TAG" <<'EOF'
import json, glob, sys, statistics as st
from collections import defaultdict
rows = defaultdict(list)
for p in sorted(glob.glob(sys.argv[1] + "/*.json")):
    d = json.load(open(p, encoding="utf-8"))
    rows[d["command"]["vx"]].append(d)
print(f"{'cmd':>5} {'n':>2} {'vx_mean':>8} {'±sem':>7} {'ratio':>6} "
      f"{'err_yaw':>8} {'fall':>6} {'absdy':>7}")
for cmd in sorted(rows):
    rs = rows[cmd]
    vx = [r["speed"]["vx_mean"] for r in rs]
    ey = [r["official_metrics"]["error_vel_yaw"] for r in rs]
    fl = [r["stability"]["terminated_frac"] for r in rs]
    dy = [r["displacement"]["abs_dy_body_median"] for r in rs]
    m, sd = st.mean(vx), st.stdev(vx)
    print(f"{cmd:>5.2f} {len(rs):>2} {m:>8.4f} {sd/len(rs)**0.5:>7.4f} "
          f"{m/cmd:>6.2f} {st.mean(ey):>8.4f} {st.mean(fl):>6.3f} {st.mean(dy):>7.4f}")
EOF
