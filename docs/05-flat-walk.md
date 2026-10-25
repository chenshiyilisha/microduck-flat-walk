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
**一次都没回到 1250**。这条曲线是「过早相信单点里程碑会误判」的例子：只看 1250→4000 是
「误差降 10%」，看完 9 档才发现那是 1250 自己的峰值。

> **2026-10-25 更正（两处）**
>
> 1. 「`mean_action_acc` 从 0.0747 单调降到 0.0604，说明后期拿跟踪换平滑」——**这个读法错了**。
>    完整序列是 0.0747 → 0.0663 → 0.0649 → 0.0687 → 0.0666 → 0.0604 → **0.0797** → 0.0691 → 0.0618，
>    在 **0.060–0.080 之间来回跳，不是单调**。当时把噪声读成了趋势。
> 2. 这条曲线**真正的原因**在 §10.4 找到了：`standing_envs`（0.15→0.20）与
>    `head_pose_range`（0.49→0.91）**都在 iter 1500 跳档**，与 1250 之后的塌陷时间完全对上。
>    不是「优化到后期自己变坏」，是课程在同一轮加了两级难度。

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

### 7.0 先说清「可复现」指的是什么

本仓库的 `third_party/microduck_rl`、`third_party/microduck-playground` 是 **private submodule**
（`.gitmodules` 指向 `github.com/emwstudio/microduck_rl`，未授权访问返回 404），所以
「clone → 跑命令 → 出数字」这条路**对外部读者不成立**。本节全部数字产生于
**`tailong-wu/microduck-mjbatch` 的 `mjlab_microduck` 任务包**（它注册了
`Mjlab-Velocity-Flat-MicroDuck`），环境：Python 3.13 + `mjlab` + `mujoco_warp 3.7.0.1`
+ `warp-lang 1.12.0`，RTX 4070 Laptop 8 GB。

所以「可复现」在本文的确切含义是：

- **给定同一份任务包与环境**，`artifacts/flat_walk/evals/*.json` 里每个数都能用
  `tools/flat_walk/eval_velocity_in_sim.py` 逐位算回来（同参：32 envs × 8 s × cmd 0.4 × solver 100/50）；
- `runmeta` 里的 `cfg_byte_identical_to_upstream: true` 和 cfg/mdp 的字节哈希，
  是「没有偷偷改奖励」的机器证据；
- 有 submodule 权限的内部读者：`git clone --recurse-submodules` 后
  `cd third_party/microduck_rl && uv sync`，本节命令可直接用。

**不成立的说法**是「clone 下来就能跑出这份结果」——缺任务包，也缺环境。

### 7.1 命令

```bash
# 从零训练（4096 envs；Windows + .venv-mjlab 的包装脚本见 tools/flat_walk/train_velocity.sh）
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 4096 --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50 \
  --agent.max-iterations 12000 --agent.save-interval 250 \
  --agent.logger tensorboard --agent.experiment-name microduck_velocity

# 判读（11 项闸门，含 command_frozen_ok 协议自检；cmd 0.4，与文档里所有数字同参）
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

后 4750 轮（1250 → 6000）没有一档回到 1250。所以「按 0.4 走」差的那 37% 不是轮数问题。
**注意**：早期把这段读成「拿跟踪换平滑（`aacc` 单调下降）」是错的（见 §2b 的更正），
真因是 iter 1500 的课程跳档，见 §10.4 —— 那里有用单变量实验得到的证据。
两个候选方向（都需要新实验，不是续训；完整清单见 §8 的「下一步候选」）：

1. **收紧角速度跟踪**（只改 `std` / weight，单变量，2000 轮可判）；
2. **前进门控**：`tools/flat_walk/patch_issue46.py` 里的 `feet_air_time_forward_gated`
   + track 侧向加权，针对「走得慢但平滑」这个具体形状。

## 10. 单变量实验：奖励核宽 std² 0.10 → 0.04

§9 判了「按 0.4 走只到 63%」，并给了诊断：**策略精确优化了给定奖励，而奖励的最优点就在 66%**。
这一节是那个诊断的**实测检验**——只改一个数，其余全不动。

### 10.1 怎么做到「只改一个数」

不加文件、不改 cfg。tyro 已经把 reward dict 暴露在命令行上（`train <TASK> --help` 里有
230 条 `--env.rewards.*`，kebab-case）：

```
--env.rewards.track-linear-velocity.params.std FLOAT   (default: 0.31622776601683794)
```

所以跑 `EXTRA_ARGS="--env.rewards.track-linear-velocity.params.std 0.2" bash tools/flat_walk/train_velocity.sh 4096 2000 vel_4096x2000_std004_1025` 即可。
**这条路比改 `site-packages` 里的 cfg 严格更好**：改文件会让预检的 `velocity_cfg_pristine`
（blocking）直接 FAIL，逼你 `--no-check`，等于拿掉保护来换实验能力。走 CLI 时
`runmeta_vel_4096x2000_std004_1025.json` 里 `cfg_byte_identical_to_upstream: true` 仍然成立。

配套改动（`tools/flat_walk/train_velocity.sh`）：

- `EXTRA_ARGS` 透传；
- runmeta 新增 **`rewards_effective`**：用**同一条 tyro 路径**重新解析 `EXTRA_ARGS`，记录实际生效的
  `weight / std / std_sq / std_over_cmd_max`。cfg 的 sha 对 CLI 覆盖一无所知，
  **声明式记录不算证据**，必须回读解析结果；
- 解析失败且 `EXTRA_ARGS` 非空 ⇒ `FATAL` + exit 1，拒绝发车。这里踩过一个坑：
  `tyro` 遇未知参数抛的是 **`SystemExit(2)`**（继承 `BaseException`），
  `except Exception` 抓不到 ⇒ 进程在写 runmeta **之前**就死，发车确实被拒但**一行证据都没留**。
  改 `except BaseException` 后才记下 `SystemExit: 2`。这类错只有负对照能让它现形。

单变量本身：`std` 0.3162 → **0.2**，即 `std²` 0.10 → **0.04**，`std/cmd_max` 0.791 → **0.500**
（正好回到 mjlab 官方 `velocity_env_cfg.py` 的口径 0.50/1.0 = 0.50）。
weight 2.0、`action_rate_l2` −0.1、`track_angular_velocity` `sqrt(0.5)` **全部未动**。
4096 envs × 2000 iter，3.16 s/iter，1 h 56 m，本地 GPU ¥0。

### 10.2 主结果：三个轴同时改善（iter 1250，cmd 0.4，各 3 次重复）

| | baseline（std²=0.10） | std004（std²=0.04） | 变化 |
|---|---|---|---|
| vx 中位 | 0.2493 | **0.3093** | **+24.1%** |
| ratio（vx / cmd） | 0.623 | **0.773** | +24.1% |
| `error_vel_xy` | 0.2164 | **0.1620** | **−25.1%** |
| `dx_body` | 1.647 m | **2.031 m** | +23.3% |
| `mean_action_acc` | 0.0771 | 0.0714 | 略降（更平滑） |

三次重复的 CV 两边都是 **1.8%**（见 `evals/eval_std004_iter1250_cmd40_rep{2,3}.json`），
差异是 13σ。按双轴判定（误差要降、速度不能退）是 **improved**，不是拿一个轴换另一个。

增益拟合（cmd 0.2–0.4）：

```
baseline:  vx = 0.7136 · cmd − 0.0363
std004  :  vx = 0.7679 · cmd + 0.0025
```

**主改善是截距归零 + 整条曲线上移，斜率只涨 7.6%。** 也就是说旧策略在每条指令上
都系统性「欠走一个固定量」，收紧核宽把这个偏置消掉了。

### 10.3 代价一：cmd ≤ 0.12 出现双稳态死区

逐点扫描（`evals/eval_std004_iter1250_cmd*.json`，`frac站` = `|vx| < 0.01` 的 env 比例）：

| cmd | 0.00 | 0.10 | 0.12 | 0.15 | 0.18 | 0.20 | 0.30 | 0.40 |
|---|---|---|---|---|---|---|---|---|
| vx 中位 | 0.000 | **0.001** | **0.004** | 0.080 | 0.141 | 0.152 | 0.241 | 0.309 |
| ratio | — | **0.008** | **0.029** | 0.533 | 0.782 | 0.761 | 0.802 | 0.790 |
| frac 站 | 0.94 | **0.78** | **0.56** | 0.06 | 0.03 | 0.00 | 0.00 | 0.00 |

过渡发生在 0.12→0.15 之间且很窄 ⇒ 这是**双稳态**（落进了「站立」吸引域），
不是「走得慢」。baseline 在 cmd 0.1 的 ratio 是 0.534，所以**这是用低速段换高速段**，
不是全面变好。`tracks_half_command` 闸门（ratio ≥ 0.5）因此在 0.10/0.12 FAIL、0.15 擦线过（0.533）。

顺带纠正 §2 里那条「cmd=0 时 `error_vel_xy` 有 0.105 与速度无关的底噪」：
它不是纯抖动，而是 baseline **在零速指令下还在原地踏步**（落地 2.22 Hz、aacc 0.0543）。
std004 版在 cmd=0 是落地 **0.17 Hz**、双脚同时触地 0.365、aacc 0.0247 —— 真的站住不动，
`error_vel_xy` 只有 **0.004**。所以「靠减抖动来降误差」那一半空间，这次已经拿到了。

### 10.4 代价二：iter 1999 掉回 baseline 水平，且时间点和课程对得上

| iter | vx 中位 | ratio | `error_vel_xy` |
|---|---|---|---|
| 1250 | 0.3093 | **0.773** | 0.162 |
| 1999 | 0.2438 | **0.620** | 0.211 |

两次重复一致（0.2480 / 0.2396），不是噪声。−20%，等于把这次改进全退回去。

时间对得上，**两个课程都在 iter 1500 跳档**：

| 课程 | 1250 | 1500 | 1999 |
|---|---|---|---|
| `standing_envs`（`rel_standing_envs`） | 0.15 | **0.20** | 0.20 |
| `head_pose_range` | 0.49 | **0.91** | 0.93 |

baseline 那个 12000 轮的 9 档曲线（§2b）是同一个形状：1250 峰值 → 1750–2000 塌陷 →
2500–4000 部分回升但没回到 1250。⇒ **「1250 之后退化」不是某个配方的偶然，是课程调度的产物。**
这是目前真正的天花板：每个配方都卡在 2000 轮以内。

### 10.5 训练指标会骗人：先去稀释再比较

训练侧 `Metrics/twist/error_vel_xy` 从 0.4147 降到 0.4043，读起来像「改善 2.5%」，
但同期 `standing_envs` 从 0.15 涨到 0.20 —— **站立环境的误差≈0，会把均值往下拉**。
按 `moving = (err − f·err_stand) / (1 − f)` 去掉站立 env（取 `err_stand ≈ 0.01`）：

```
it1250:  (0.4147 − 0.15·0.01)/0.85 = 0.4861
it1999:  (0.4043 − 0.20·0.01)/0.80 = 0.5029     ← 退化 3.5%
```

去稀释后方向与部署侧一致。⇒ 本项目里 `standing_envs` / `rel_heading_envs` /
`rel_forward_envs` 都是**会动的分母**；任何「训练指标改善但部署变差」的矛盾，
先查这些比例有没有变，再怀疑策略。

### 10.6 这一节的结论与遗留

- 「奖励最优点在 66%」的诊断**是对的**：改奖励确实推得动，而且推了 24%（速度）、25%（误差）。
- 但**增益只涨 7.6%**，主要收益来自消除截距偏置 ⇒ 想再往上，改核宽不是杠杆。
- 低速死区与「1500 后回退」都还在，且都不是这次改动引入的机制性问题——
  前者是核宽收紧的副作用，后者在这个任务里一直存在。
- 视频：`videos/walk_std004_1250_side.mp4`、`videos/walk_std004_1250_34.mp4`
  （与 `walk_1250_side/34.mp4` 同机位、同 8 s、同 cmd 0.4，可直接并排看）。
- 权重：`checkpoints/model_1250_std004.pt`（4.8 MB，就是这个 run 的 iter 1250）。
