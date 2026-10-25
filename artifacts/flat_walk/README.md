# flat_walk — 平地速度跟踪产物

对应文档：`docs/05-flat-walk.md`（方法与判决）、`JOURNEY.md`（时间线与教训）。

| 文件 | 是什么 |
|---|---|
| `checkpoints/model_1250.pt` | **baseline**（std²=0.10）iter 1250 策略，11/11 闸门通过（4.8 MB） |
| `checkpoints/model_1250_std004.pt` | **单变量后**（std²=0.04）iter 1250 策略，**当前最好**：cmd 0.4 下 ratio 0.773 / `error_vel_xy` 0.162（4.8 MB，见 `docs/05-flat-walk.md` §10） |
| `evals/eval_iter1250_clean.json` | baseline 交付档的评估原始输出，含全部闸门布尔值与逐项指标 |
| `evals/eval_iter6000_clean.json` | baseline 停训档（11 项里 `no_fall` 失败），用来说明「继续训没有更好」 |
| `evals/eval_curve_clean.json` | baseline 同 run 的 **9 档** checkpoint 同协议曲线（1250 / 1500 / 1750 / 2000 / 2500 / 3000 / 3500 / 4000 / 6000） |
| `evals/eval_std004_iter1250_cmd*.json` | 单变量实验的**逐工作点**扫描：cmd 0 / 0.10 / 0.12 / 0.15 / 0.18 / 0.20 / 0.30 / 0.40，其中 0.10–0.12 是低速死区、0.15 是边界 |
| `evals/eval_std004_iter1250_cmd40_rep{2,3}.json` | cmd 0.4 的两次重复，用来证明 24% 的差异不是噪声（三次 CV 1.8%） |
| `evals/eval_std004_iter1999_cmd*.json` | 同 run 的 iter 1999（ratio 掉回 0.620），用来说明「1500 课程跳档后回退」 |
| `evals/runmeta_vel_4096x12000_1025.json` | baseline 训练契约：envs/iters/PPO 超参/求解器/**cfg 与 mdp 的字节哈希** |
| `evals/runmeta_vel_4096x2000_std004_1025.json` | 单变量实验契约：除哈希外还有 **`rewards_effective`**（回读解析出的 `std` / `std_sq` / `std_over_cmd_max`）与 `extra_args` |
| `videos/walk_1250_side.mp4` | baseline 侧视 8 s（azimuth 90 / 俯角 −8° / 1.15 m），看抬脚与落地相位 |
| `videos/walk_1250_34.mp4` | baseline 3/4 视角 8 s（135° / −22° / 1.45 m），看整体姿态 |
| `videos/walk_std004_1250_side.mp4` | std004 版侧视，**与 baseline 同机位/同 8 s/同 cmd 0.4**，可直接并排比 |
| `videos/walk_std004_1250_34.mp4` | std004 版 3/4 视角，参数同上 |

> 早期版本的 `eval_iter1250_v2.json` 已删除：它是在「25% 的 env 被课程静默改成站着」的
> 错误协议下测的，留着会被当成可比数字。

## 评估口径（要复现数字必须同参）

> 前提：需要 `Mjlab-Velocity-Flat-MicroDuck` 任务包与对应环境；本仓库的 `third_party/*`
> 是 private submodule，**外部 clone 拿不到**。所以「可复现」的含义与边界写在
> `docs/05-flat-walk.md` §7.0，别按「clone 即出数」去理解。

```bash
uv run python tools/flat_walk/eval_velocity_in_sim.py \
  --checkpoint artifacts/flat_walk/checkpoints/model_1250.pt \
  --num-envs 32 --seconds 8 --cmd-vx 0.4 \
  --solver-iters 100 --solver-ls 50 --out out/eval.json
```

- `--num-envs` / `--seconds` / `--cmd-vx` / solver 三项**都要一致**，否则数字不可比。
- 评估器丢弃 `push_robot` 事件（评测不测抗扰）；把 `common_step_counter` 钉到 `1e9`，
  让地形/指令范围等课程项取末级（否则新建的 env 计数器是 0，等于按第 0 级评测）；
  **同时 `pop` 掉 `standing_envs` 课程项**——它每步按同一个计数器重写 `rel_standing_envs`
  （末级 0.25），会把「冻结到 vx 0.4」悄悄变成「25% 的 env 站着不动」。
  这两件事必须成对出现，只做前者会让误差被稀释（详见 `docs/05-flat-walk.md` §5 坑 1）。
- `command_frozen_ok` 闸门就是这条协议的自检：它记录每步 `vel_command_b`，
  要求 `max|cmd − frozen| ≤ 1e-3`。**去掉 pop 那一行，它会立刻 FAIL 并打印
  `uniq cmd vx [0.0, 0.4] / frac_cmd_zero 25.0%`** —— 一个只见过绿色的闸门不是证据。
- `error_vel_xy` 只在**同一评估器**内比较趋势；训练日志里的同名指标是五模式混合口径，不可横比。
- 故意把 `resampling_time_range` 设成 `duration`（而不是 1e9）：官方累加器用它当除数，
  设成 1e9 会把误差除以 5e10 报出一个完美的 0。

## 关于体积

本目录的 `.pt` 与 `.mp4` 是**刻意入库**的：`artifacts/` 默认被 `.gitignore` 排除，
这里走逐项例外规则（不是目录级白名单，新增文件仍会被挡住）。
两个 4.8 MB 的 checkpoint + 4 条片子（共约 6.2 MB），换来三件事：**clone 下来就能看到它走**、
**两个配方可以直接并排比**，以及**判决所依据的原始数据都在**（要重算数字仍需任务包与环境，见 §7.0）。
这比重新烧 10 小时训练便宜得多。
其余训练产物（每 250 轮一个 ckpt、TensorBoard events、4 MB 日志、调试录屏）不入库。

## 单变量实验怎么跑（不用改 cfg）

```bash
EXTRA_ARGS="--env.rewards.track-linear-velocity.params.std 0.2" \
  bash tools/flat_walk/train_velocity.sh 4096 2000 vel_4096x2000_std004
```

tyro 把 reward dict 暴露在命令行上，所以改核宽**不必碰 `site-packages` 里的 cfg**，
`velocity_cfg_pristine` 预检保持绿。发车前脚本会用**同一条 tyro 路径**重解析 `EXTRA_ARGS`，
把实际生效的 `std / std_sq / std_over_cmd_max` 写进 runmeta 的 `rewards_effective`；
解析失败则 `FATAL` + exit 1 拒绝发车。**声明式记录不算证据。**
