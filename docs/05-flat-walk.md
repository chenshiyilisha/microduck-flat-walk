# 平地速度跟踪（2026-10-25，flat-walk）

一句话：在**上游默认 flat 任务** `Mjlab-Velocity-Flat-MicroDuck` 上，**没有改任何奖励、没有改环境**，
4096 envs 从零训练到 **iter 1250** 就得到一个 11 项闸门全过、cmd 0.4 m/s 下跟出 **0.252 m/s** 的行走策略；
再往后跑（1500 → 6000，逐 250 轮存档共 9 档实测）**没有一档超过它**，6000 轮还跌出一个摔倒闸门失败。

> **修订说明（同日）**：本文早先版本的 vx 0.258 / `error_vel_xy` 0.194 是在**有 25% 的 env 被静默
> 改成站立指令**的协议下测的（见 §5 坑 3）。修掉之后所有数字整体下移，结论方向不变。

## 0. 与 README 里的「极速项目」不是同一件事

| | 极速项目（sprint） | 本项目（flat-walk） |
|---|---|---|
| 任务 | `Mjlab-Sprint-Flat-MicroDuck`（自建） | `Mjlab-Velocity-Flat-MicroDuck`（**上游默认**） |
| 考核 | 峰值/百米均速（2.06 / 1.66 m/s） | 按指令速度走（cmd 0.4 → 实测 0.252） |
| 起点 | Hannes running 配方 512 envs | 上游配置原样，4096 envs 从零 |
| 关注 | 「能跑多快」 | 「指令跟不跟得住、脚抬不抬得起来」 |

出厂 `alpha_walking.onnx` 在 cmd 0.4 下实测只有 **0.164 m/s**（原地策略实测，非训练指标），
所以 0.252 m/s 已经是出厂水平的 **1.54 倍**——0.4 不是及格线，是出厂策略也够不到的命令值。

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

## 2. 结果（`evals/eval_iter1250_clean.json`，32 envs × 8 s，cmd vx 0.4，solver 100/50）

| 指标 | 值 |
|---|---|
| vx 中位（各 env 均值的中位） | **0.2519 m/s**（指令的 63%） |
| vx / vy / wz 均值 | 0.2522 / 0.0199 / 0.0319 |
| 官方 `error_vel_xy` | **0.212**（median 0.210） |
| 沿自身朝向净位移 `dx_body` | **+1.821 m**（期望 3.2 m，ratio 0.59） |
| 横向漂移 `|dy_body|` 中位 | 0.476 m |
| 航向漂移 | 3.29 °/s |
| 脚峰（L / R 中位） | **15.90 / 17.20 mm**（目标 20 mm） |
| 落地频率 / 同时落地 | **1.88 Hz/脚** / 4.0% |
| 站立位脚底高度中位 | 0.99 mm |
| upright 均值 / 最低 | 0.9981 / 0.9970 |
| 终止率 | **0.00%**（32/32 跑满 8 s，含 fall_over 与 nan_state） |
| `mean_action_acc` | 0.0747 |

11 项闸门（`passed` 字段）：`command_frozen_ok`（**协议自检**：整段 32×400 步的指令确实恒为
(0.4, 0, 0)，偏差 0.0000）、`sensor_zero_ok`、`measurement_consistent`、`tracks_half_command`、
`translates_forward`、`not_sideways`、`error_vel_xy_le_0.25`、`no_fall`、`stays_upright`、
`feet_clear_8mm`、`steps_alternate` —— **全 PASS**。

## 2b. 逐档 checkpoint 曲线：1250 是峰值，之后再没回去

同一 run 每 250 轮存档，全部用上面同一套协议评测（`evals/eval_curve_clean.json` 汇总）：

| iter | vx 中位 | `error_vel_xy` | `dx_body` | ratio | 脚峰 mm | 落地 Hz | 闸门 |
|---|---|---|---|---|---|---|---|
| **1250** | **0.252** | **0.212** | **1.821** | **0.59** | 15.9 | 1.88 | **11/11** |
| 1500 | 0.234 | 0.223 | 1.547 | 0.49 | 17.8 | 1.89 | 11/11 |
| 1750 | 0.191 | 0.258 | 1.364 | 0.43 | 16.4 | 1.72 | 9/11（跟踪、误差） |
| 2000 | 0.182 | 0.266 | 1.288 | 0.43 | 15.2 | 1.77 | 9/11（跟踪、误差） |
| 2500 | 0.218 | 0.245 | 1.341 | 0.44 | 16.9 | 1.86 | 11/11 |
| 3000 | 0.198 | 0.248 | 1.449 | 0.42 | 15.5 | 1.87 | 10/11（跟踪） |
| 3500 | 0.219 | 0.230 | 1.604 | 0.50 | 16.4 | 1.96 | 11/11 |
| 4000 | 0.220 | 0.234 | 1.536 | 0.51 | 15.9 | 1.75 | 11/11 |
| 6000 | 0.213 | 0.234 | 1.456 | 0.47 | 15.0 | 1.88 | **10/11（no_fall）** |

三个独立量（vx、`dx_body`、`error_vel_xy`）同向：1250 最好，1750–2000 塌陷，之后部分回升但
**一次都没回到 1250**；`mean_action_acc` 却从 0.0747 单调降到 0.0604——策略越来越「平滑」，
同时越来越慢。这条曲线是「优化到后期把跟踪换成了平滑」的典型形状，也是**过早相信
单点里程碑会误判**的例子：只看 1250→4000 是「误差降 10%」，看完 9 档才发现那是 1250 自己的峰值。

## 3. 四个参照系（不建立参照系，就会把「会走」误判成「没走」）

| 参照 | 数值 | 用途 |
|---|---|---|
| 出厂策略（官方 `alpha_walking.onnx`，cmd 0.4） | 0.164 m/s | 判断「速度低是不是我没练好」→ 不是 |
| Datawhale 复现（4096×6000，同任务） | `error_vel_xy` **0.4167**、脚峰 **14.1 mm** | 6000 轮的公开水平 |
| issue #46 各组 + Qi-hub-dot（5000 轮） | 0.42–0.43 | 与我们同 commit 的四拨人都卡这里 |
| 上游 `foot_clearance.target_height` | **20 mm** | 平地抬脚的目标值 |

**结论一**：`error_vel_xy ≈ 0.42` 不是任务固有天花板——我们 1250 轮就是 0.212，
比公开的 5000–6000 轮还好一倍。那几组是配方问题，不是任务上限。
（注意：他们的 0.42 是训练日志口径 = 五模式混合指令 + 整回合累积，我们的 0.212 是固定单一
指令、8 s 窗口的同一公式值，**只能作量级参考，不能当同口径对比**。同口径可比的是本仓库内
1250 与后续各档之间的趋势。）

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
整回合累积；本仓库评估器固定单一 cmd 后得到 0.212。**两者不可直接比**，只能在同一评估器内比趋势。

**坑 3（最贵的一个）：课程会偷偷改掉你冻结的指令。**
`freeze_command()` 把 `rel_standing_envs` 设成 0，但 `microduck_velocity_env_cfg.py` 里还有一个
`standing_envs` 课程项，它**每一步**按 `common_step_counter` 重写这个字段
（`mdp.py:3440-3474`，分级到 `2000*24` 步 = 0.25）。而让评测可复现的做法正是把计数器钉到 1e9
（= 所有课程取末级），于是每次评测都有 **25% 的 env 被命令「站着别动」**，跑完还挂着
"cmd vx 0.4" 的招牌。

后果不是「读数偏一点」，是**符号会反**：

| | 旧协议（含 25% 站立 env） | 修后（全 32 env 都走） |
|---|---|---|
| iter 1250 `error_vel_xy` | 0.194 | **0.212** |
| iter 4000 `error_vel_xy` | 0.174 | **0.234** |
| 结论 | 「4000 比 1250 好 10%」 | **「4000 比 1250 差 10%」** |

机制：站立 env 的跟踪误差≈0，会把均值稀释；而 25% 是按 env 独立随机抽的，**每次抽到的
个数不同**（实测 32 env 里 6–10 个），于是两次评测的稀释比例不同，差值就被读成了「进步」。

修法两条，必须同时做：
1. `freeze_command()` 里 `cfg.curriculum.pop("standing_envs", None)`——只改 cfg 值没用，
   下一步课程又写回去；
2. 把协议本身变成一项闸门：记录每步的 `vel_command_b`，新增 `command_frozen_ok`
   （要求 `max|cmd - frozen| <= 1e-3`）。**负对照**：把 `pop` 那行去掉重跑，
   该项立刻 FAIL 并打印 `uniq vx [0.0, 0.4] / frac cmd==0 25.0%`。

教训：**「我设了这个字段」不等于「这个字段还是这个值」。** 任何跨模块共享的配置，只要还有
第二个写者（课程、manager、reset 事件），冻结就必须是可测量的，不能是声明式的。

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

- **已完成**：iter 1250 策略（`artifacts/flat_walk/checkpoints/model_1250.pt`）+ 11/11 闸门证据；
  9 档 checkpoint 的同协议曲线（§2b），确认 **1250 是峰值**。
- **已停止**：run 在 iter 6000 后人为停止（原计划 12000）。依据是曲线——4000 比 1250 慢 13%、
  误差高 10%，6000 再跌一个 `no_fall` 闸门；继续跑 5800 轮（约 5.3 h）没有证据支持会回升。
  ckpt 全部保留（`model_0 … model_6000`），`tools/flat_walk/resume_velocity.sh` 可随时从
  任意一档续训到任意目标轮数，所以这个决定是可逆的。
- **未做**：ONNX 导出 + parity（部署侧契约会另起一次验证）；真机（本仓库约定：暂无实体机器人）。
- **验收结论**见 §9——**11/11 闸门是及格线，不是优秀线**，别把前者当后者。

### 下一步候选（按性价比排）

1. 用修好的评估器重扫 1000 / 1100 / 1250 三档，确认峰值位置（每档 ~1 min）；
2. 若目标是「按 0.4 走」，问题不在训练轮数而在配方：1250 已到 63% 的跟踪率，继续 PPO 只会
   把跟踪换成平滑——需要动奖励（`tools/flat_walk/patch_issue46.py` 就是为此准备的）或换任务
   （带前进门控的 `feet_air_time`）；
3. 把 `command_frozen_ok` 这类**协议闸门**扩展到其它三个任务（走楼梯 / 高跷 / 秋千），
   它们大概率共享同一个 `standing_envs` 课程项。

## 9. 验收：达到什么、没达到什么

对 `model_1250.pt` 的分层判定。之所以要分层，是因为「闸门全过」在实践中很容易被读成
「达到预期」，而这两件事并不等价：闸门阈值（`error_vel_xy ≤ 0.25`）本身就是按及格设的。

| 层 | 判据 | 结果 |
|---|---|---|
| 工程闭环 | 从零训练、成本、可复现 | **达标** 1250 iter / ¥0 / 配置字节哈希进 runmeta / 证据全部入库 |
| **会走** | 有速度、脚离地、交替、不摔 | **达标** 0.252 m/s、脚峰 15.9 / 17.2 mm、1.88 Hz 每脚、同时落地 4.0%、终止 0% |
| **跟得准** | cmd 0.4 | **未达标** 63%、净位移比 0.59、`error_vel_xy` 0.212 |
| 走直线 | 保持航向 | **任务未要求**（见下） |

### 9.1 航向：上游任务本身没有这条要求

`microduck_velocity_env_cfg.py:643` 是 `command.rel_heading_envs = 0.0`——heading env
比例为 0，heading 奖励在整个训练里从未生效，航向只被 `track_angular_velocity`
（weight 2.0）约束到「wz 逼近 0」。所以「8 s 后朝向偏了」不是策略违约，是任务定义留的空白。
要判「走直」，得先改任务，而不是怪策略。

三个和 yaw 有关的数**不是同一个量**，不能互相当校验（这个项目已经因为混口径翻过一次案）：

| 量 | 定义 | 实测 |
|---|---|---|
| `wz_mean` | 体坐标角速度的**带符号**平均 | 0.032 rad/s（1.8 °/s）⇒ 没有稳定打转 |
| `error_vel_yaw` | `mean abs(cmd_wz − wz)`（`velocity_command.py:70-73`） | 0.298 rad/s（17 °/s）⇒ 瞬时抖动大 |
| `yaw_drift_deg_s` | **端点差** `abs(yaw[-1] − yaw[0]) / T`（`eval_velocity_in_sim.py:357`） | 3.29 °/s ⇒ 8 s 中位偏 **26°** |

三者并置的结论：它在**左右晃**，不是在打转（带符号平均只有 1.8 °/s，绝对值平均却有 17 °/s）。
因此修法不是加一个「锁死世界朝向」的 heading 惩罚（那是更难的要求），
而是收紧 `track_angular_velocity`：现在 `std = sqrt(0.5)` 太松，wz 偏 0.3 时奖励
`exp(-0.3²/1.0) = 0.914`，几乎不罚。

横向偏移中位 0.476 m 与端点偏 26° 量级自洽 ⇒ 两者都是真的，不是测量误差。
**注意**：`yaw_drift_deg_s` 是端点差、不是速率，引用时要写「8 s 端点偏 26°」，
不能写成「漂移 3.29 °/s」——后者会被读成恒定的角速度，那不是实测的形状。

### 9.2 判「没达到」之后，瓶颈在哪

后 4750 轮（1250 → 6000）在拿跟踪换平滑：`mean_action_acc` 从 0.0747 单调降到 0.0604，
9 档里没有一档回到 1250。所以「按 0.4 走」差的那 37% 不是轮数问题。
两个候选方向（都需要新实验，不是续训；完整清单见 §8 的「下一步候选」）：

1. **收紧角速度跟踪**（只改 `std` / weight，单变量，2000 轮可判）；
2. **前进门控**：`tools/flat_walk/patch_issue46.py` 里的 `feet_air_time_forward_gated`
   + track 侧向加权，针对「走得慢但平滑」这个具体形状。
