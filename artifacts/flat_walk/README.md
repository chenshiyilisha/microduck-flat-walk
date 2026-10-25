# flat_walk — 平地速度跟踪产物

对应文档：`docs/05-flat-walk.md`（方法与判决）、`JOURNEY.md`（时间线与教训）。

| 文件 | 是什么 |
|---|---|
| `checkpoints/model_1250.pt` | iter 1250 策略，11/11 闸门通过（4.8 MB，与 `simple_stairs/checkpoints/` 同规格） |
| `evals/eval_iter1250_v2.json` | 评估原始输出，含全部闸门布尔值与逐项指标 |
| `evals/runmeta_vel_4096x12000_1025.json` | 训练契约：envs/iters/PPO 超参/求解器/**cfg 与 mdp 的字节哈希** |

## 评估口径（要复现数字必须同参）

```bash
uv run python tools/flat_walk/eval_velocity_in_sim.py \
  --checkpoint artifacts/flat_walk/checkpoints/model_1250.pt \
  --num-envs 32 --seconds 8 --cmd-vx 0.4 \
  --solver-iters 100 --solver-ls 50 --out out/eval.json
```

- `--num-envs` / `--seconds` / `--cmd-vx` / solver 三项**都要一致**，否则数字不可比。
- 评估器丢弃 `push_robot` 事件（评测不测抗扰），并把课程计数器固定到 ckpt 自带的值，
  这样策略看到的地形/指令范围与训练末态一致。
- `error_vel_xy` 只在**同一评估器**内比较趋势；训练日志里的同名指标是五模式混合口径，不可横比。

## 关于体积

本目录的 `.pt` 是**刻意入库**的：`artifacts/` 默认被 `.gitignore` 排除，这里走例外规则。
一个 4.8 MB 的 checkpoint 换来「clone 即能复现判决」，比重下 10 小时训练便宜。
其余训练产物（每 250 轮一个 ckpt、TensorBoard events、4 MB 日志）不入库。
