#!/usr/bin/env bash
# 复现 Vottivott/microduck-playground 踩高跷完整课程（已执行 lineage，seed 72）
# 用法（在 AutoDL 实例上）：
#   cd /root/autodl-tmp/microduck-playground
#   nohup bash /root/autodl-tmp/run_stilt_curriculum.sh > logs/curriculum_main.log 2>&1 &
# 断点续跑：已完成阶段记录在 logs/curriculum/completed.tsv，重跑同一命令自动跳过。
#
# 关键机制（已核实）：
# - 形态由环境变量 MICRODUCK_STILT_HEIGHT_CM / MICRODUCK_STILT_BLEND 在编译期固定，每阶段一个进程
# - 本仓库 rsl_rl：learn() 的 num_learning_iterations 是相对起点的增量；
#   checkpoint 存的是最后一个已训练 it，最终保存为 model_{last_it}.pt（不是累计目标号）。
#   因此续训一律用「上一阶段目录里编号最大的 model_*.pt」，不做文件名算术。
# - 日志目录为 logs/rsl_rl/stilt_locomotion/<日期>_<时间>_stilt-h<H>cm-b<BBB>
set -uo pipefail

REPO=${REPO:-/root/autodl-tmp/microduck-playground}
cd "$REPO"

ENVS=${ENVS:-4096}
SEED=72
export WANDB_MODE=${WANDB_MODE:-offline}   # 实例无 wandb 登录，沿用旧例离线模式
EXP=logs/rsl_rl/stilt_locomotion
STATUS=logs/curriculum_status.log
DONE_TSV=logs/curriculum/completed.tsv
mkdir -p logs/curriculum eval
touch "$DONE_TSV"

run_name() { # height_cm blend -> stilt-h{H}cm-b{BBB}（与 cfg 的 _stage_name 一致）
  local h b
  h=$(printf '%g' "$1")
  b=$(awk "BEGIN{printf \"%03.0f\", $2 * 100}")
  echo "stilt-h${h}cm-b${b}"
}

latest_run_dir() { # run_name -> 最新时间戳目录名
  ls -1d "$EXP"/*_"$1" 2>/dev/null | sort | tail -1 | xargs -r basename
}

latest_ckpt() { # run_dir_basename -> 编号最大的 model_*.pt 文件名
  ls -1 "$EXP/$1"/model_*.pt 2>/dev/null | sort -V | tail -1 | xargs -r basename
}

completed_line() { # run_name -> completed.tsv 行（无则空）
  grep -P "^$1\t" "$DONE_TSV" | tail -1
}

gate() { # height_cm checkpoint_path —— 里程碑 1024-env 10s 评估，survival >= 0.90
  local h=$1 ckpt=$2 out="eval/repro_h$(printf '%g' "$h")cm.json"
  MICRODUCK_STILT_HEIGHT_CM=$h MICRODUCK_STILT_BLEND=0.5 \
    uv run python scripts/evaluate_running_checkpoint.py \
      --checkpoint-file "$ckpt" --task-id Mjlab-Stilt-Flat-MicroDuck \
      --speed 0.15 --num-envs 1024 --duration-s 10 --warmup-s 1 --seed 123 \
      --output-file "$out" >> "logs/curriculum/eval_h$(printf '%g' "$h")cm.log" 2>&1
  local rc=$?
  [ $rc -ne 0 ] && { echo "EVAL_CRASH h=$h rc=$rc" | tee -a "$STATUS"; return 1; }
  local surv
  surv=$(python3 -c "import json; print(json.load(open('$out'))['survival_fraction'])")
  echo "GATE h=${h}cm survival=${surv} ckpt=$ckpt" | tee -a "$STATUS"
  python3 -c "import sys; sys.exit(0 if float('$surv') >= 0.90 else 1)"
}

train_stage() { # height_cm blend cumulative_iters milestone(0/1)
  local h=$1 b=$2 target=$3 milestone=$4
  local name; name=$(run_name "$h" "$b")

  # 断点续跑：已完成则跳过
  if [ -n "$(completed_line "$name")" ]; then
    echo "SKIP $name（已完成）" | tee -a "$STATUS"
    return 0
  fi

  local args=(--env.scene.num-envs "$ENVS" --agent.seed "$SEED")
  local add=$target

  local prev_line prev_dir prev_ckpt prev_target
  prev_line=$(tail -1 "$DONE_TSV")
  if [ -n "$prev_line" ]; then
    prev_dir=$(echo "$prev_line" | cut -f2)
    prev_ckpt=$(echo "$prev_line" | cut -f3)
    prev_target=$(echo "$prev_line" | cut -f4)
    [ -f "$EXP/$prev_dir/$prev_ckpt" ] || { echo "MISSING_CKPT $EXP/$prev_dir/$prev_ckpt" | tee -a "$STATUS"; exit 2; }
    add=$((target - prev_target))
    args+=(--agent.resume True --agent.load-run "$prev_dir" --agent.load-checkpoint "$prev_ckpt" --agent.max-iterations "$add")
  else
    args+=(--agent.max-iterations "$target")
  fi

  echo "=== $(date '+%F %T') stage $name target=$target (+$add) ===" | tee -a "$STATUS"
  MICRODUCK_STILT_HEIGHT_CM=$h MICRODUCK_STILT_BLEND=$b \
    uv run train Mjlab-Stilt-Flat-MicroDuck "${args[@]}" \
    > "logs/curriculum/${name}_to${target}.log" 2>&1
  local rc=$?
  [ $rc -ne 0 ] && { echo "TRAIN_FAILED $name rc=$rc" | tee -a "$STATUS"; exit $rc; }

  local this_dir this_ckpt
  this_dir=$(latest_run_dir "$name")
  this_ckpt=$(latest_ckpt "$this_dir")
  [ -n "$this_ckpt" ] || { echo "MISSING_FINAL_CKPT in $EXP/$this_dir" | tee -a "$STATUS"; exit 3; }
  printf '%s\t%s\t%s\t%s\n' "$name" "$this_dir" "$this_ckpt" "$target" >> "$DONE_TSV"

  if [ "$milestone" = "1" ]; then
    gate "$h" "$EXP/$this_dir/$this_ckpt" || { echo "GATE_FAILED h=${h}cm（插入中间高度或检查行为后再继续）" | tee -a "$STATUS"; exit 4; }
  fi
}

# ---- 已执行课程表（TRAINING.md，seed-72 lineage）----
# 阶段 1：2cm 收窄支撑 blend 0 -> 0.25 -> 0.50
train_stage 2    0    400 0
train_stage 2    0.25 500 0
train_stage 2    0.5  600 0
# 阶段 2：blend 0.50 高度爬升 3->25cm
train_stage 3    0.5  700 0
train_stage 4    0.5  800 0
train_stage 5    0.5 2000 0   # 5cm 步态巩固
train_stage 7.5  0.5 2100 0
train_stage 10   0.5 2200 1   # ★ 里程碑 10cm
train_stage 12.5 0.5 2300 0
train_stage 15   0.5 2400 1   # ★ 15cm
train_stage 17.5 0.5 2500 0
train_stage 20   0.5 2600 1   # ★ 20cm
train_stage 22.5 0.5 2700 0
train_stage 25   0.5 2800 1   # ★ 25cm
# 阶段 3：27.5->50cm
train_stage 27.5 0.5 2900 0
train_stage 30   0.5 3000 0
train_stage 35   0.5 3100 0
train_stage 40   0.5 3200 0
train_stage 45   0.5 3300 0
train_stage 50   0.5 3400 1   # ★ 50cm
# 阶段 4：55cm->1.4m（纯仿真）
train_stage 55   0.5 3500 0
train_stage 60   0.5 3600 0
train_stage 70   0.5 3700 0
train_stage 80   0.5 3800 0
train_stage 90   0.5 3900 0
train_stage 100  0.5 4000 1   # ★ 1.0m
train_stage 110  0.5 4100 0
train_stage 120  0.5 4200 0
train_stage 140  0.5 4300 1   # ★ 1.4m
# 阶段 5：1.5->2.0m 高跷桥
train_stage 150  0.5 4600 0
train_stage 160  0.5 4950 0
train_stage 170  0.5 5300 0
train_stage 180  0.5 5650 0
train_stage 190  0.5 6000 0
train_stage 200  0.5 6500 1   # ★ 2.0m

echo "ALL_STAGES_DONE $(date '+%F %T')" | tee -a "$STATUS"
