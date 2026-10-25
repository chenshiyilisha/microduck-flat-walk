# 平地速度跟踪（2026-10-25，flat-walk）

一句话：在**上游默认 flat 任务** `Mjlab-Velocity-Flat-MicroDuck` 上，**没有改任何奖励、没有改环境**，
4096 envs 从零训练到 **iter 1250** 就得到一个 10 项闸门全过、cmd 0.4 m/s 下跟出 **0.258 m/s** 的行走策略。

## 0. 与 README 里的「极速项目」不是同一件事

| | 极速项目（sprint） | 本项目（flat-walk） |
|---|---|---|
| 任务 | `Mjlab-Sprint-Flat-MicroDuck`（自建） | `Mjlab-Velocity-Flat-MicroDuck`（**上游默认**） |
| 考核 | 峰值/百米均速（2.06 / 1.66 m/s） | 按指令速度走（cmd 0.4 → 实测 0.258） |
| 起点 | Hannes running 配方 512 envs | 上游配置原样，4096 envs 从零 |
| 关注 | 「能跑多快」 | 「指令跟不跟得住、脚抬不抬得起来」 |

出厂 `alpha_walking.onnx` 在 cmd 0.4 下实测只有 **0.164 m/s**（原地策略实测，非训练指标），
所以 0.258 m/s 已经是出厂水平的 **1.57 倍**——0.4 不是及格线，是出厂策略也够不到的命令值。

## 1. 契约（逐项可核：`artifacts/flat_walk/evals/runmeta_vel_4096x12000_1025.json`）

| 项 | 值 |
|---|---|
| 任务 | `Mjlab-Velocity-Flat-MicroDuck` |
| envs × iters | 4096 × 12000（本地 RTX 4070 Laptop 8 GB，3.14–3.19 s/iter ≈ 10.6 h，**¥0**） |
| 观测/动作契约 | 61D 观测 / 14 关节（与运行时 daemon 同一契约）；控制 50 Hz（sim 200 Hz × decimation 4） |
| 网络 | actor/critic 512-256-128，ELU，obs 归一化，`std_type=scalar`，`init_std=1.0` |
| PPO | lr 1e-3 adaptive，24 steps，5 epochs，4 minibatches，γ0.99，λ0.95，entropy 0.01，clip 0.2，desired_kl 0.01 |
| 求解器 | CLI 覆盖 `iterations=100` / `ls_iterations=50`（cfg 默认 10/20），`nconmax=35` |
| **cfg 是否改过** | **否**：`cfg_sha256_16=75a0430b814ac749`、`mdp_sha256_16=9f9b77c05d16a1a3`、`cfg_byte_identical_to_upstream: true` |

也就是说：这条策略的全部内容就是「上游任务的正确配方 + 足够的并行度 + 求解器加保险」。

## 2. 结果（`evals/eval_iter1250_v2.json`，32 envs × 8 s，cmd vx 0.4，solver 100/50）

| 指标 | 值 |
|---|---|
| vx 中位（各 env 均值的中位） | **0.2577 m/s**（指令的 65%） |
| vx / vy / wz 均值 | 0.2298 / 0.0162 / −0.0195 |
| 官方 `error_vel_xy` | **0.194**（median 0.192） |
| 沿自身朝向净位移 `dx_body` | **+1.575 m**（期望 3.2 m，ratio 0.55） |
| 横向漂移 `|dy_body|` 中位 | 0.530 m |
| 航向漂移 | 4.55 °/s |
| 脚峰（L / R 中位） | **15.26 / 15.81 mm**（目标 20 mm） |
| 落地频率 / 同时落地 | **2.13 Hz/脚** / 5.1% |
| 站立位脚底高度中位 | 0.70 mm |
| upright 均值 / 最低 | 0.998 / 0.996 |
| 终止率 | **0.00%**（32/32 跑满 8 s，含 fall_over 与 nan_state） |
| `mean_action_acc` | 0.0876 |

10 项闸门（`passed` 字段）：`sensor_zero_ok`、`measurement_consistent`、`tracks_half_command`、
`translates_forward`、`not_sideways`、`error_vel_xy_le_0.25`、`no_fall`、`stays_upright`、
`feet_clear_8mm`、`steps_alternate` —— **全 PASS**。

## 3. 四个参照系（不建立参照系，就会把「会走」误判成「没走」）

| 参照 | 数值 | 用途 |
|---|---|---|
| 出厂策略（官方 `alpha_walking.onnx`，cmd 0.4） | 0.164 m/s | 判断「速度低是不是我没练好」→ 不是 |
| Datawhale 复现（4096×6000，同任务） | `error_vel_xy` **0.4167**、脚峰 **14.1 mm** | 6000 轮的公开水平 |
| issue #46 各组 + Qi-hub-dot（5000 轮） | 0.42–0.43 | 与我们同 commit 的四拨人都卡这里 |
| 上游 `foot_clearance.target_height` | **20 mm** | 平地抬脚的目标值 |

**结论一**：`error_vel_xy ≈ 0.42` 不是任务固有天花板——我们 1250 轮就是 0.194，
比公开的 5000–6000 轮还好一倍。那几组是配方问题，不是任务上限。

**结论二**：脚峰 15.3–15.8 mm 对 20 mm 的目标是 **76–79%**。同一台机器上「原地抬腿」的关节限位
天花板只有 **25.3 mm**，所以这个 20 mm 目标本身是**压着物理天花板**设的——这解释了为什么平地上
「抬到 20 mm」特别费劲，也是 joy 式原地踏步任务反复失败的物理原因。

**结论三（易错）**：简单直楼梯 JOURNEY 里的 **66.6 mm** 是**官方交替梯策略**的脚 apex 净空，
用于跨 24–26 mm 级高；**不能**拿来当平地参照。平地参照是 14–20 mm。

## 4. 求解器 100/50 是「抗 NaN 保险」，不是「抬脚杠杆」

上游 flat 只用 `iterations=10 / ls_iterations=20`，加固只写在 `if rough:` 分支
（`microduck_velocity_env_cfg.py` 的 solver 段）。我们把它抬到 100/50 做 A/B：

- 脚峰：2.11 / 3.25 mm → 1.82 / 3.05 mm（冒烟尺度下的测量噪声，**不是改善**）
- 墙钟：45 s → 43 s（MJWarp 收敛即退出，多给的迭代不花钱）

⇒ **不值得指望它解决抬脚**；留着只是为了让 4096 env 长跑不因接触求解退化而 NaN
（本项目训练全程 `nan_state` 终止率 0.0000）。这是一条**负结果**，写下来是为了别重复试。

## 5. 评测口径的两个坑（都自己踩过）

**坑 1：世界系位移 vs 体坐标命令。** `reset_base` 的 `pose_range["yaw"] = (-3.14, 3.14)`
—— 每个 env 的初始朝向在整个圆周上随机。用 `root_link_pos_w` 算净位移，各 env 互相抵消，
`dx_mean` 必然趋近 0：实测 −0.039 m，看着像「原地打转」，而同一次运行的体坐标 ∫vx·dt 是 +1.6 m。
修法：把位移投影到**各 env 自己的初始朝向**，并用体坐标积分做独立交叉校验。

**坑 2：`error_vel_xy` 与训练日志不是同一口径。** 训练日志里的 0.42–0.43 是五模式混合指令 +
整回合累积；本仓库评估器固定单一 cmd 后得到 0.194。**两者不可直接比**，只能在同一评估器内比趋势。

## 6. 续训三个坑（都在 `tools/flat_walk/` 里写成了注释）

1. **`--agent.max-iterations` 是增量不是总量**（rsl_rl 5.0.1 `on_policy_runner.py:77-79`：
   `total_it = start_it + num_learning_iterations`）——从 10000 传 12000 会跑到 22000。
   用 `resume_velocity.sh` 传**目标绝对轮数**，脚本自己算余量。
2. **别设 `MICRODUCK_WARM_START=1`**（`mjlab_microduck/tasks/mdp.py:118-146`「Patch 5」）：
   它把 `env.common_step_counter` 清零，课程全部回到 stage 0——那是「从旧 ckpt 起新实验」用的，
   「接着跑」不设。
3. **ckpt 排序别信 help 文本**：`mjlab/utils/os.py:61` 用零填充 key
   （`f"{m:0>15}"`）排序，实际是数字序；而 docstring 和 `--help` 都写 "alphabetical order"，
   按字面理解会挑错档。以代码为准。

## 7. 复现

```bash
# 从零训练（4096 envs；Windows + .venv-mjlab 的包装脚本见 tools/flat_walk/train_velocity.sh）
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 4096 --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations 12000 --agent.save-interval 250 \
  --agent.logger tensorboard --agent.experiment-name microduck_velocity

# 判读（10 项闸门；cmd 0.4，与文档里所有数字同参）
uv run python tools/flat_walk/eval_velocity_in_sim.py \
  --checkpoint artifacts/flat_walk/checkpoints/model_1250.pt \
  --num-envs 32 --seconds 8 --cmd-vx 0.4 \
  --solver-iters 100 --solver-ls 50 --out out/eval.json

# 中途体检 + 判停（等 model_4000/6000 落盘后自动评测，泛化不动就停训）
python tools/flat_walk/watch_milestones.py --targets 4000,6000 --stop-pid <训练 pid>
```

## 8. 状态与尚缺

- **已完成**：iter 1250 策略（`artifacts/flat_walk/checkpoints/model_1250.pt`）+ 10/10 闸门证据。
- **在跑**：同一 run 继续到 12000，4000 / 6000 里程碑自动判停；若 4000 相对 1250 无改善，
  就停在 6000（省约 5 h），不换配方。
- **未做**：ONNX 导出 + parity（部署侧契约会另起一次验证）；真机（本仓库约定：暂无实体机器人）。
- **未采用**：issue #46 的三处改法（`air_time` 前进门控 + track 侧向加权）。
  代码已写好并验证（`tools/flat_walk/patch_issue46.py`，`--check/--apply/--revert`，幂等 + 备份），
  但 1250 轮已经过闸，**没有理由在好策略上动奖励**。留作换任务时的待用件，当前刻意保持 `NOT applied`。
