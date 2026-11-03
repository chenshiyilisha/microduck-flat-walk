#!/usr/bin/env bash
# Wait for a training run to finish, then produce the pre-registered judgment data.
#
# The point of encoding this in a script is that the criteria are fixed BEFORE
# the numbers exist (NEXT-p8-train.md §3.2): which plant rows, which start yaws,
# which condition. Hand-typing the same 24 rehearsals afterwards is how a metric
# quietly changes between "what we said we would measure" and "what we measured".
#
# Usage:
#   RUN=p8head_030_4096x3000 ITERS=3000 TRAIN_PLANT=p8 \
#     bash tools/hd1910/await_and_judge.sh
#
# Env:
#   RUN          run name (log is out/train_${RUN}.log)
#   ITERS        expected final iteration
#   TRAIN_PLANT  p3|p8 — recorded in every manifest, not verified by this script
#   POLL         seconds between checks (default 30)
#   MAXWAIT      poll budget (default 480 → 4 h)
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe

RUN="${RUN:?RUN is required}"
ITERS="${ITERS:?ITERS is required}"
TRAIN_PLANT="${TRAIN_PLANT:-?}"
POLL="${POLL:-30}"
MAXWAIT="${MAXWAIT:-480}"

LOG="out/train_${RUN}.log"
[ -f "$LOG" ] || { echo "no log: $LOG" >&2; exit 2; }

echo "await_and_judge: RUN=$RUN ITERS=$ITERS train_plant=$TRAIN_PLANT"
echo "  log $LOG (polling every ${POLL}s, budget ${MAXWAIT} polls)"

progress() { grep -o "Learning iteration [0-9]*/${ITERS}" "$LOG" 2>/dev/null | tail -1; }

done_marker=""
last=""
stall=0
# ⚠️ 2026-11-03 踩过：训练跑满了 3000 轮、ckpt 与 ONNX 都齐，但 `out/train_${RUN}.log`
# 里没有 "Learning iteration 3000/3000"（该文件只有 1 行启动错误）⇒ 本脚本在
# 一个永远不更新的日志上空转了 3 小时，最后什么也没判。
# 教训：**完成判据不能只看日志**，要以产物为准。两个判据取"或"：
#   ① 日志出现末轮标记；② 最新 model_*.pt 的编号 >= ITERS-1。
RUN_DIR_GLOB="logs/rsl_rl/microduck_velocity_hd1910/*${RUN}"
newest_ckpt() {
  local d n
  d="$(ls -d $RUN_DIR_GLOB 2>/dev/null | tail -1)"
  [ -n "$d" ] || { echo -1; return; }
  n="$(ls -1 "$d"/model_*.pt 2>/dev/null | sed 's/.*model_//;s/\.pt$//' | sort -n | tail -1)"
  echo "${n:--1}"
}
for i in $(seq 1 "$MAXWAIT"); do
  if grep -q "Learning iteration ${ITERS}/${ITERS}" "$LOG" 2>/dev/null; then
    done_marker="final-iteration"
    break
  fi
  ck="$(newest_ckpt)"
  if [ "${ck:-0}" -ge "$((ITERS - 1))" ] 2>/dev/null; then
    done_marker="ckpt>=${ck}（日志里没有末轮标记，按产物判完成）"
    break
  fi
  cur="$(progress)"
  if [ -n "$last" ] && [ "$cur" = "$last" ]; then
    stall=$((stall + 1))
  else
    stall=0
  fi
  last="$cur"
  # 6 polls (~3 min) with no new iteration and no final marker => assume it died.
  # 只在"日志有迭代行但停住"时才成立；日志完全没有迭代行（开局就错）时，
  # 由 ckpt 判据兜底，stall 不该误杀。
  if [ "$stall" -ge 6 ] && [ -n "$cur" ]; then
    echo "ABORT: no progress for $((stall * POLL))s, last seen '$cur'" >&2
    exit 3
  fi
  sleep "$POLL"
done
[ -n "$done_marker" ] || { echo "ABORT: never reached iteration $ITERS" >&2; exit 3; }
echo "  完成判据: $done_marker"

RUNDIR="$(ls -d logs/rsl_rl/microduck_velocity_hd1910/*"${RUN}" 2>/dev/null | tail -1)"
[ -n "$RUNDIR" ] || { echo "ABORT: no run dir matching ${RUN}" >&2; exit 2; }
echo "  run dir $RUNDIR"

# The exporter hook rewrites the run's single ONNX on each save, so wait until it
# is newer than the newest checkpoint -- otherwise we judge an earlier iteration.
for i in $(seq 1 30); do
  NEWCKPT="$(ls -t "$RUNDIR"/model_*.pt 2>/dev/null | head -1 || true)"
  ONNX="$(ls -t "$RUNDIR"/*.onnx 2>/dev/null | head -1 || true)"
  if [ -n "$NEWCKPT" ] && [ -n "$ONNX" ] && [ "$ONNX" -nt "$NEWCKPT" ]; then
    break
  fi
  sleep 10
done
ONNX="$(ls -t "$RUNDIR"/*.onnx 2>/dev/null | head -1 || true)"
[ -n "$ONNX" ] || { echo "ABORT: no ONNX in $RUNDIR" >&2; exit 2; }
NEWCKPT="$(ls -t "$RUNDIR"/model_*.pt 2>/dev/null | head -1 || true)"
echo "  ckpt  $(basename "${NEWCKPT:-<none>}")"
echo "  onnx  $(basename "$ONNX")"
if [ -n "$NEWCKPT" ] && [ ! "$ONNX" -nt "$NEWCKPT" ]; then
  echo "⚠️  ONNX is not newer than the checkpoint -- it may be a stale export" >&2
fi

echo
echo "== [1/3] 2x2 cross-plant grid (nominal) =="
TRAIN_PLANT="$TRAIN_PLANT" ONNX="$ONNX" TAG="${RUN}" \
  bash tools/hd1910/xplant_matrix.sh

echo
echo "== [2/3] 80 ms delay (the P5 verdict's hard boundary) =="
TRAIN_PLANT="$TRAIN_PLANT" ONNX="$ONNX" TAG="${RUN}_delay4" \
  PLANTS="p8" COND=delay4 \
  bash tools/hd1910/xplant_matrix.sh

echo
echo "== [3/3] +-90 deg target negative control (is it tracking, or one attractor?) =="
for T in 90 -90; do
  TRAIN_PLANT="$TRAIN_PLANT" ONNX="$ONNX" TAG="${RUN}_t${T}" \
    PLANTS="p8" YAWS="0 90 180 270" TARGET="$T" \
    bash tools/hd1910/xplant_matrix.sh
done

echo
echo "await_and_judge done for $RUN — see out/xplant_${RUN}*/summary.json"
