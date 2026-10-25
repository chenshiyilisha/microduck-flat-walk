# flat_walk — 平地速度跟踪产物

对应文档：`docs/05-flat-walk.md`（方法与判决）、`JOURNEY.md`（时间线与教训）。

| 文件 | 是什么 |
|---|---|
| `checkpoints/model_1250.pt` | iter 1250 策略，11/11 闸门通过（4.8 MB，与 `simple_stairs/checkpoints/` 同规格） |
| `evals/eval_iter1250_clean.json` | 交付档的评估原始输出，含全部闸门布尔值与逐项指标 |
| `evals/eval_iter6000_clean.json` | 停训档（11 项里 `no_fall` 失败），用来说明「继续训没有更好」 |
| `evals/eval_curve_clean.json` | 同 run 的 **9 档** checkpoint 同协议曲线（1250 / 1500 / 1750 / 2000 / 2500 / 3000 / 3500 / 4000 / 6000） |
| `evals/runmeta_vel_4096x12000_1025.json` | 训练契约：envs/iters/PPO 超参/求解器/**cfg 与 mdp 的字节哈希** |
| `videos/walk_1250_side.mp4` | 侧视 8 s（azimuth 90 / 俯角 −8° / 1.15 m），看抬脚与落地相位 |
| `videos/walk_1250_34.mp4` | 3/4 视角 8 s（135° / −22° / 1.45 m），看整体姿态 |

> 早期版本的 `eval_iter1250_v2.json` 已删除：它是在「25% 的 env 被课程静默改成站着」的
> 错误协议下测的，留着会被当成可比数字。

## 评估口径（要复现数字必须同参）

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
一个 4.8 MB 的 checkpoint + 2.0 MB 的两条片子，换来「clone 即能复现判决、也能直接看到它走」，
比重下 10 小时训练便宜。
其余训练产物（每 250 轮一个 ckpt、TensorBoard events、4 MB 日志、调试录屏）不入库。
