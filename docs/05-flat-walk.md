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
| 横向漂移 `abs(dy_body)` 中位 | 0.476 m |
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
  9 档 checkpoint 的同协议曲线（§2b），确认 **1250 是峰值**；
  单变量配方（std² 0.04，§10）+ **部署图与 parity 闸门**（§13）+
  **部署彩排工具与七条判据**（§14，`evals/rehearse_*.json` 待重跑入库）。
- **已停止**：run 在 iter 6000 后人为停止（原计划 12000）。依据是曲线——4000 比 1250 慢 13%、
  误差高 10%，6000 再跌一个 `no_fall` 闸门；继续跑 5800 轮（约 5.3 h）没有证据支持会回升。
  ckpt 全部保留（`model_0 … model_6000`），`tools/flat_walk/resume_velocity.sh` 可随时从
  任意一档续训到任意目标轮数，所以这个决定是可逆的。
- **已关闭的方向**：把「iter 1250 之后退化」归因于课程跳档——§12 用一次整跑证伪。
  课程不再作为杠杆；iter 1999 的掉点按上游口径是 checkpoint 级抖动，用扫点处置。
- **未做**：真机（本仓库约定：暂无实体机器人）。ONNX 本身已导出并通过 parity（§13），
  彩排也证明部署栈能工作（§14），但「图与权重等价」+「栈活着」都不等于「真机跑得好」。
  上游 `scripts/testbench_sim2real.py` 是缺口最小的一步：同一 ONNX 在 sim(BAM) 与真机
  XL330 上跑同一角度序列做对比，只需一个电机 + 一个 USB 口。
- **验收结论**见 §9——**11/11 闸门是及格线，不是优秀线**，别把前者当后者。

### 下一步候选（按性价比排）

1. **低速死区（唯一还没解决的机制性问题，§11）**：要真做 0.15 m/s 以下，必须改任务定义
   （`air_time` 目标滞空随指令缩放，或给 `foot_clearance` 正权重），会同时动到高速步态，
   必须重跑整条工作点扫描。不做就只能把部署下限钉在 0.15。
2. 把 `command_frozen_ok` / `metric_window_ok` / `check_onnx_parity.py` 这类**协议闸门**
   扩展到其它三个任务（走楼梯 / 高跷 / 秋千），它们大概率共享同一个 `standing_envs` 课程项。
3. 用修好的评估器重扫 1000 / 1100 / 1250 三档，确认峰值位置（每档 ~1 min）。

## 9. 验收：达到什么、没达到什么

对 `model_1250.pt` 的分层判定。之所以要分层，是因为「闸门全过」在实践中很容易被读成
「达到预期」，而这两件事并不等价：闸门阈值（`error_vel_xy ≤ 0.25`）本身就是按及格设的。

| 层 | 判据 | 结果 |
|---|---|---|
| 工程闭环 | 从零训练、成本、可复现 | **达标** 1250 iter / ¥0 / 配置字节哈希进 runmeta / 证据全部入库 |
| **会走** | 有速度、脚离地、交替、不摔 | **达标** 0.252 m/s、脚峰 15.9 / 17.2 mm、1.88 Hz 每脚、同时落地 4.0%、终止 0% |
| **跟得准** | cmd 0.4 | **低于指令** 63%、净位移比 0.59、`error_vel_xy` 0.212 —— 但**高于上游部署版**（42.5%，见 §9.3） |
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

**但要说清这个 `sqrt(0.5)` 是谁定的**：它与 mjlab 官方
`tasks/velocity/velocity_env_cfg.py:284` **一字不差**，是上游原样，不是本项目调松的。
所以收紧它属于「改上游配方」，需要单变量实验支撑，不能当 bug 修。

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

### 9.3 参照系：上游部署版在同一个指令上走多少

一手来源：`pollen-robotics/microduck_rl`（公开仓库，默认分支 `develop`）的
`docs/velstand_policy.md:185-186` 原文：

> Walking / push (`velstand_bench.py --backlash --only walking,push`): vx tracking ≈ v7 and
> `alpha_walking` (**0.4 m/s → 0.17 achieved, same as the teacher**)

那是这个机器人**已经部署到真机**的策略（wandb `0045i2si` @ `model_2749.pt`，tag v8，
2026-10-12 真机验证），任务为 `Mjlab-VelStand-Rough-Backlash-MicroDuck` —— **Rough 地形 + 背隙**。
本项目是 `Mjlab-Velocity-Flat-MicroDuck` —— **平地 + 无背隙**。

⇒ **条件不同，不能据此宣称我们更好**（他们的更难）。它能确定的是三件事：

1. 「0.4 指令只走到 40–60%」在这个平台上**是常态，不是本配方失败**：上游真机版的 ratio 是 **42.5%**。
2. 所以本表原先把「跟得准」判成**未达标**，是按**指令值**判的，不是按**平台可达水平**判的，偏严。
   按可达水平看，0.62（baseline）/ 0.77（std004）在同一量级或更高。
3. 想要 ratio ≥ 0.9 是**另一个任务**（要重新定义「什么叫跟上」），不是调参能到的 ——
   上游也没做到，并且把这个水平直接上了真机。

### 9.4 四条现象与上游的对应（旁证，不是同一测量）

| 现象 | 本项目 | 上游 |
|---|---|---|
| 0.4 指令的实际速度 | 0.249（baseline）/ 0.309（std004） | **0.17**（Rough+Backlash 部署版） |
| 1250 附近是好档 | 9 档里 vx / `error_vel_xy` / `dx_body` 三项最优 | 「`1250` has neither drift」，而 `500` 右偏 −0.20 rad/s、`1499` 左偏 +0.27（`velstand_policy.md:86-91`） |
| 训练指标看不出档间差异 | 训练侧 `error_vel_xy` 1250→1999 只差 2.5%，去稀释后方向还反了（§10.5） | 「Checkpoints differ a lot in yaw behaviour **although the training metrics do not**」 |
| 必须多档扫再选点 | 9 档全测（约 9 min） | 「**Always run the walk sweep before picking a checkpoint**」 |

第一条量的类型不同（他们测 yaw 漂移，我们测 vx ratio），所以只能算旁证。但四条同向 ⇒
§2b / §10.4 那个「1250 峰值、1500 之后退化」**不是本项目配置的偶然**，
上游在另一套配方、另一个仿真栈上复现了同一个形状。

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

**2026-10-25 按当前评估脚本复测两侧**（旧数字来自评估器加 `per_env`/口径闸门之前，
跨版本不可混用，见 §12.5）：

| | baseline（std²=0.10） | std004（std²=0.04） | 变化 |
|---|---|---|---|
| vx 中位 | 0.2518 ± 0.0137 | **0.3242 ± 0.0052** | **+28.8%** |
| ratio | 0.630 | **0.811** | +28.7% |
| `error_vel_xy` | 0.2135 ± 0.0096 | **0.1592 ± 0.0050** | **−25.4%** |

两套协议给出同一方向、同一量级（+24% → +29%，−25% → −25%），结论不变。
baseline 的重复性明显更差（CV 5.4% vs std004 的 1.6%）——慢策略本身的方差就大，
这也是判据要用 3 次重复而不是 1 次的原因。
数据：`evals/eval_base010_it1250_cmd40_r{1,2,3}.json`、`evals/eval_base_it1250_cmd40_r{1,2,3}.json`。

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
2500–4000 部分回升但没回到 1250。

> **⚠️ 2026-10-25 更正：本节的因果结论已被 §12 的整跑实验证伪。**
> 这里原来写的是「『1250 之后退化』不是某个配方的偶然，是课程调度的产物」——
> 那是从**时间重合**（部署侧 1999 掉点 vs 课程 1500 跳档）推的，不是判据。
> 按上游 `AGENTS.md` 给的判据（课程边界处训练指标是否 step DOWN）实测**不触发**，
> 且把整条课程表推后 1000 档后 iter 1999 的 ratio 只有 0.684（要 0.77）。
> ⇒ 1999 的掉点应定性为 **checkpoint 级抖动**，处置方式是扫点选点。
> 本节保留的是**现象**（1250 峰值、1999 掉回），**因果解释请以 §12 为准**。


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

## 11. 低速死区的机制：滞空塌陷，而 `air_time` 在低速区归零

§10.3 记了「cmd ≤ 0.12 出现双稳态死区」。这一节把它的机制测出来，
并说明**它不是配置写错了，而是奖励体系对「小步慢走」的固有盲区**。

### 11.1 三个实测（cmd 0.12 vs 0.40，同一 ckpt `model_1250_std004.pt`）

| 量 | cmd 0.12 | cmd 0.40 | 判读 |
|---|---|---|---|
| vx 中位 | 0.0035 | 0.3158 | 净位移几乎为零 |
| `landings_per_foot_hz` | 0.73 | 2.26 | 步频掉到 1/3 |
| 抬脚峰（双脚较差值） | **5.4 mm** | **18.1 mm** | 脚几乎不离地 |
| **滞空时间中位** | **0.040 s** | **0.220 s** | = 2 个物理步 vs 11 个 |
| 滞空落在 `[0.125, 0.3]` 的比例 | **2.9%** | **79.0%** | 这是关键 |
| `mean_action_acc` | 0.0713 | 0.0714 | **和全速行走一样大** |
| `terminated_frac` | **0.0** | 0.0 | 不摔 |
| `upright_mean` | 0.9994 | 0.9985 | 站得比行走还稳 |

三条推论：

1. **它不是「安静站着」**：`aacc` 与全速行走相同（0.0713 vs 0.0714），但净位移近零
   ⇒ 在**原地乱蹬/搓地**。之前把它读成「78% env 完全静止」是不准的 —— 那个数是
   `|vx| < 0.01` 的比例，不区分「站着」和「在动但没走出去」。
2. **它不是物理不可行**：终止 0%、upright 0.9994，低速比高速更稳
   ⇒ 不存在「小步幅会倒」这回事，是**行为选择**。
3. **抬脚与滞空同时塌**：18.1 → 5.4 mm、0.220 → 0.040 s，两者是同一件事的两面。

### 11.2 为什么它会选「滑行」：`air_time` 是阶跃函数

`feet_air_time`（`mjlab/tasks/velocity/mdp/rewards.py:209-238`）在本任务里的实现是：

```python
in_range = (current_air_time > 0.125) & (current_air_time < 0.300)   # 阶跃
reward   = sum(in_range)                 # 每只脚 1 分，与滞空多长无关
reward  *= (||cmd_xy|| + |cmd_wz| > 0.01)     # 门控
```

weight 是 **3.0**，而且它是**唯一正向激励抬脚**的项：

| 项 | weight | 方向 |
|---|---|---|
| `air_time` | **+3.0** | 奖励：滞空落在窗口内 |
| `foot_clearance` | **−2.0** | 惩罚：`abs(h − 0.02)` × ‖v_foot,xy‖（`rewards.py:256-259`）|
| `foot_swing_height` | **−0.25** | 惩罚：偏离目标高度 |

低速时滞空 **0.040 s < 0.125 s** ⇒ 这项 3.0 权重 **97% 归零**。
抬脚要付 `action_rate` 与 `foot_clearance` 的代价，却拿不到 `air_time` 的分
⇒ **奖励地形上「抬脚」这条路在低速区没有坡**，而 `foot_clearance` 的 cost 乘了脚速，
所以「不抬脚 + 不动」是零代价。策略滑向滑行是**最优解**，不是训练不足。

训练日志侧对得上：`Episode_Reward/air_time` 全程只有 1.0–1.25，除以 weight 3.0
⇒ 平均 **0.33–0.42 只脚**处于窗口内（trot 理想值约 1）。

### 11.3 外部资料：这是「小步慢走」的固有盲区，不是本项目写错

| 来源 | 口径 | 与我们的差别 |
|---|---|---|
| legged_gym `_reward_feet_air_time` | `sum((t_air − 0.5) · 1{first_contact})`，门控 `‖cmd_xy‖ > 0.1` | **线性**，只有下界 0.5 s，无上界 |
| IsaacLab / mjlab 本任务 | `sum(1{0.125 < t < 0.3})`，门控 `‖cmd‖ > 0.01` | 换成**阶跃窗口**，多了上界 |
| 社区调参清单（lsqyrobot, 2026-07） | 「不要让低速/零速也被奖励抬腿」「`feet_air_time` 是最容易导致翘腿的项」 | 警告方向相反，针对零速 |

关键推演：**按 legged_gym 的 τ=0.5 s，滞空 0.04 s 同样拿不到正分**。也就是说，
0.12 m/s 需要的「短促小步」在**两套主流口径下都不被算作迈步** —— 这些奖励是为大步设计的
（legged_gym 隐含 τ=0.5 s，mjlab 为本项目 40 cm 机器人改到 0.125–0.3 s，正好对应 0.22 s 的实际滞空）。

同一份中文资料还直接解释了我们的现象：「如果没有这个奖励，机器人往往会选择在地上『滑行』
（拖步），**因为这样最稳**；加入了腾空奖励，机器人就会被迫抬腿。」

### 11.4 所以下一步**不是**把窗口下界调低

这个念头很自然（下界 0.125 → 0.04 就能覆盖实测滞空），但被资料否掉：

- 0.04 s = **2 个物理步**。把这里算作迈步，等于奖励「抖两帧」，
  正是社区警告的「低速被奖励抬腿 → 翘腿」那类失败模式；
- 而把 `command_threshold` 收紧到 legged_gym 的 0.1 只会让 0.12 更没分，方向相反。

正确处置有两条，**都需要先决定「部署要不要 0.15 m/s 以下」**：

1. **工程上限定工作区**（推荐）：部署下限设 0.15 m/s。§10.3 的扫描说明 0.15 以上完全正常
   （ratio 0.533→0.782→0.790），而 0.4 的绝对水平已经高于上游真机版（§9.3）。
   这条**不需要再训练**。
2. **要真低速就得改任务定义**：让 `air_time` 的目标滞空随指令速度缩放（或直接给
   `foot_clearance` 正权重作为独立抬脚激励）。这是新任务，不是单变量实验 ——
   而且会同时动到高速步态，必须重新跑整条工作点扫描。

### 11.5 这一节的结论

- 低速死区**有机制、有数字、可复现**：滞空 0.04 s 掉出 `air_time` 的阶跃窗口，
  抬脚因此失去唯一正激励，策略选择滑行。
- 但**它不是 bug**：两套主流 `air_time` 口径对「小步慢走」都不给分。
  这解释了为什么上游把研究重点放在 0.2–0.4 m/s 与转向，而不在 0.1 m/s 巡航。
- 因此 §8「下一步候选」里那条「低速 bucket」**应当撤回**：bucket 只增加经验，
  而这里是奖励在低速区**本身不给分**，给多少经验都一样。

## 12. 课程推后实验：一个被证伪的假设（负结果）

§10.4 断言「1250 之后退化是这个课程调度的产物」。这一节用一次完整训练把这个断言
**否掉**，并记录它的方法论成本：判据本来 10 分钟能跑完，我却先花了 2 小时做干预。

### 12.1 假设与干预

假设：`standing_envs` / `head_pose_range` 在 iter 1500 跳档 → iter 1999 掉点。
干预：把 iter 1500 之后的**整条**课程时间表推后 1000 步档，奖励核宽与其它一切不动。

| 项 | 对照 | 变体 |
|---|---|---|
| `track_linear_velocity` std² | 0.04 | 0.04（未动；runmeta 回读 `std_over_cmd_max`=0.5 确认） |
| `standing_envs` 跳档 | 36000 步 = iter 1500 | 60000 步 = iter 2500 |
| `head_pose_range` 跳档 | 36000 步 = iter 1500 | 60000 步 = iter 2500 |
| 预算 | 4096 env × 2000 iter | 同（3.44 s/iter，1 h 56 min，rc=0） |

**干预确实生效**：iter 1999 时变体 `standing_envs`=0.150、`head_pose_range`=0.490，
对照为 0.200 / 0.910。课程单位是**步**不是轮（`iteration × 24`），72000 步 = iter 3000
⇒ 这两个跳档在 2000 轮内根本不会发生。

**且没有污染前半程**：iter 480 时两跑逐项相同——Mean reward 101.66 / 101.08、
episode 长度 937.5 / 930.9、`error_vel_xy` 0.4811 / 0.4969、`air_time` 1.2539 / 1.2553、
`fell_over` 0.625 / 0.667。这是「改动没生效」与「改动生效但无害」的区分点：
只看 cfg 改没改是不算证据的。

### 12.2 结果：判据未达成，而且退化换了性质

判据事先固定：**iter 1999 的 ratio 守在 0.77 附近**（对照组 0.620）。
同一版评估脚本、cmd 0.4、32 env、8 s、两边各 3 次重复：

| run | iter | vx | `error_vel_xy` | ratio | 终止率 | 滞空 | landings |
|---|---|---|---|---|---|---|---|
| 对照 | 1250 | 0.3242 ± 0.0052 | 0.1592 | **0.811** | 0.0% | 0.227 | 2.29 |
| 对照 | 1999 | 0.2432 ± 0.0110 | 0.2137 | **0.608** | 1.0% | 0.220 | 2.06 |
| 变体 | 1250 | 0.3119 ± 0.0089 | 0.1620 | **0.780** | 0.0% | 0.220 | 2.27 |
| 变体 | 1999 | 0.2734 ± 0.0020 | 0.1991 | **0.684** | **7.3%** | 0.220 | 2.26 |

- 判据要 0.77，实测 **0.684 ⇒ 不成立**。
- 回退幅度从 −24.9% 缩到 −12.3%：**减半，但没消除**。
- **退化换了性质**，这是最重要的一点：对照组 1999 是「变慢但稳」（landings 2.29→2.06、
  终止率 1.0%）；变体 1999 是「步态完好但 7.3% 的 env 摔了」——它的滞空 0.220 s、
  抬脚峰 19.7 mm、landings 2.26 与自己的 1250 几乎一致，掉的只是稳定性。
- ⇒ 两个 run 的 iter 1999 不能用同一个「退化」词概括。只看 vx/error 会把这两件事混为一谈。

### 12.3 资料把结论翻了过来

上游 `microduck_rl/AGENTS.md`（Curricula 节）给了这条规则的**判据**，而我在干预之前没跑它：

> When a wandb metric steps DOWN exactly at curriculum stage boundaries, the pacing is wrong —
> stretch stages or move the introduction later, never earlier.

按这条判据查对照组的训练曲线：

| 对照 | iter 1460–1499 | iter 1501–1650 |
|---|---|---|
| `Metrics/twist/error_vel_xy` | 0.4017 | **0.3921**（更好） |
| `Episode_Reward/track_linear_velocity` | 0.9703 | **0.9993**（更好） |

**没有 step down，规则根本不触发。** 我原来的依据是「部署侧在 1999 掉点」与
「课程在 1500 跳档」**时间重合**——这种证据同时兼容「A 致 B」「B 致 A」「第三因素」，
是最弱的一种。

`docs/velstand_policy.md`（Checkpoint choice）则直接给了另一种解释：

> Checkpoints differ a lot in yaw behaviour although the training metrics do not: `500` turns
> right when asked to walk straight (−0.20 rad/s at 0.4 m/s), `1499` turns left (+0.27).
> `1250` has neither drift. **Always run the walk sweep before picking a checkpoint.**

同一份文档里 v8b 还写「`@2000` 偏、`@2749` 反而 settled」⇒ **后期不是单向变差**。
我们的做法（1250 峰值 + 多档扫）本来就是对的；把 1999 的掉点当成「训练退化」去修，
方向从一开始就错了。

另外两条资料也指向相反方向：

- 课程在上游是**鲁棒性来源**：fine-tune 时 `_collapse_curricula_to_final` 把继承的课程
  直接 **collapse 到 final stage**，理由是「加载进来的策略就是在那些条件下训出来的」。
  我们把 `head_pose_range` 从 0.91 推掉，等于削掉扰动多样性——7.3% 的摔倒正是这么来的。
- `rsl_rl` 没有 best-checkpoint-by-eval，`on_policy_runner.py` 里只有
  `if it % self.cfg["save_interval"] == 0` ⇒ **选点只能在外层做**，这也解释了上游为什么
  把它写成一条操作纪律而不是一个开关。

### 12.4 这个实验设计本身也有缺陷

结果是有效的（判据未达成），但**不能归因到某一个课程项**：

- `--defer-by` 平移的是**整张表**，`standing_envs`（多站少走 → 应更快）与
  `head_pose_range`（少扰动 → 应更脆）**反向同时动**。观察到的「更快但更爱摔」
  恰好是这两个方向叠加，无法拆分。
- 单种子。对照只有一个 run，两跑的差异里含训练噪声（这个噪声本项目**没有测过**）。
- 正确的单变量做法是逐档指定：`--defer-from 1500 --defer-by 1000 --only standing_envs`。

### 12.5 结论：这条线关掉

- 「课程跳档导致退化」**被证伪**。iter 1999 的掉点按上游口径定性为 **checkpoint 级抖动**，
  处置方式是**扫点选点**，不是改课程。
- 交付点仍是 **iter 1250**（ratio 0.78–0.81、`error_vel_xy` 0.16、零摔倒）。
- 课程**不再作为杠杆**。真正还没解决的是 §11 的低速死区，那是任务定义问题，需要新任务。
- 数据：`evals/eval_defer_it{1250,1999}_cmd40_r{1,2,3}.json`、
  `evals/eval_base_it{1250,1999}_cmd40_r{1,2,3}.json`、`runmeta/variant_meta_vel_defer1500x1000_1025.json`。
- ⚠️ **跨版本评估脚本的数字不可混用**：同一 ckpt（std004 @1250）在 §10.4 记的是
  0.3093 / ratio 0.773，用当前脚本复测是 0.3242 / 0.811，差 4.8%，大于同版本重复的
  CV 1.8%。两次之间评估器改过（`resampling_time_range` 对齐、闸门、`per_env`）。
  ⇒ 比较只能在**同一次会话、同一版脚本**内做；本节两侧都重测过。

## 13. 交付件：ONNX 导出与 parity 闸门

这一节把「iterate 至 1250 就结束」的那条路补完：模型出图、并且**证明**图与权重等价。

### 13.1 出口只有一个，但它不自检

`mjlab_microduck.export` 是 checkpoint → 可部署 `.onnx` 的唯一路径
（`runner.export_policy_to_onnx`，`scripts/export.py` 是它的 CLI 包装）。它的 docstring
明确写了为什么不能手工转：`ActorCritic.as_onnx` 导出的是 `actor(normalizer(obs))`，
normalizer 必须烘进图里，否则模拟器照旧（Python 里已经归一化过），上机就完全不对。

**但上游这个导出不做任何校验**——在 `mjlab_microduck/export.py` 里
`parity` / `onnxruntime` / `InferenceSession` / `allclose` 的出现次数**都是 0**。
它信的是注释里的那句话。

### 13.2 `check_onnx_parity.py`：用独立实现当参考

```
python tools/flat_walk/check_onnx_parity.py --checkpoint model_1250.pt --onnx walk.onnx
```

关键设计：**参考前向不复用 rsl_rl 的 `forward`**，而是从 `actor_state_dict` 的裸张量
用 numpy 重建（Linear / ELU(1.0)）。原因是如果用 `policy.act_inference()` 当参考，
normalizer 就在同一个模块上——**导出路径的 bug 和参考路径的 bug 会互相抵消**，
检查恒绿。这也和 §12 的教训同源：参考必须独立，否则它在测自己。

两个常量从源码取，不是猜的：

- `EmpiricalNormalization.forward` 是 `(x − _mean) / (_std + eps)`——除的是**存储的 std
  buffer**，不是 `sqrt(_var)`；而 **`eps` 默认 1e-2**（`rsl_rl/modules/normalization.py`）。
  老导出器里常见的 1e-5 会让每个输出都偏移，看起来像真不匹配。
- MLP 是 Linear/ELU(alpha=1.0) 重复，只输出均值动作（不含采样头）。

**灵敏度是被断言的，不是假设的**：`--control` 用同一个参考跑一遍**去掉归一化**的版本，
要求它必须严重偏离。一个检测不出「normalizer 没烘进去」的检查毫无价值——它会在
机器人会失败的图上给出绿灯。控制组不偏离时整体 exit 非零。

### 13.3 iter 1250 的实测

| 项 | 值 |
|---|---|
| 输入 / 输出 | `obs` (1, 61) float32 → `actions` (1, 14) |
| opset | 18 |
| batch 维 | **静态 1**（`get_dummy_inputs` 就是一行，正是控制器每次发的形状） |
| parity `max abs(onnx − ref)` | **2.65e−06**（容差 1e−4，float32 精度量级） |
| 负对照（拆掉归一化） | **5.30**，即输出量程的 91%，是容差的 **53000 倍** |
| 闸门 | `single_output` / `input_shape_ok` / `parity_ok` / `control_detects_missing_normalizer` 全过 |

产物：`checkpoints/walk_std004_1250.onnx`（794 KB）、
`evals/onnx_parity_std004_1250.json`。

### 13.4 还没做的

- **真机**：本仓库约定没有实体机器人，这一环空缺。能声明的是「图与权重在 float32 精度内等价」，
  不能声明「跑得好」。
- 动作后处理（`ctrl = stand_pose + ACTION_SCALE · action`）刻意留在图外——它是机器人
  静立姿态的属性，不是控制器的属性。

### 13.5 小结

- 交付链现在是：`model_1250.pt` → `walk_std004_1250.onnx` → parity 闸门 → （缺）真机。
- 静态 batch 1 意味着这个图**只能发单条 obs**；要批量推理得自己 unsqueeze 循环，
  这不是缺陷，是导出时的 dummy 输入决定的。

## 14. 部署彩排：执行器栈能不能工作（数字不可与评估横比）

parity 只回答了「图是不是同一套数学」。它**没有闭环**、也**没有跑执行器模型**，
所以它答不了「这个图在部署栈上还站得住吗」。这一节是那一环的工具与判据。

⚠️ 本节给出的数**不能**与 §2 / §10 / §12 的 0.312 / 0.1592 放同一张表——两个仪器（§14.5）。

### 14.1 官方链是四步，parity 只覆盖第一步

`microduck_rl/AGENTS.md:21` 给的是：

```
uv run scripts/export.py ...                       # 1. checkpoint -> onnx
uv run scripts/infer_policy.py --walking out.onnx  # 2. CPU MuJoCo *deployment rehearsal*
uv run publish                                     # 3. 上传策略集
robotctl policy load ...                           # 4. 上机
```

第二步就是**彩排**。`tests/test_infer_policy_bam.py` 的 docstring 把它的定位写死了：

> infer_policy.py drives the CPU MuJoCo rehearsal with the SAME BAM M6 actuator the policies
> are trained against in warp ... These tests **lock the two halves together**.

它逐项断言 `BAM_MOTOR_NAME/MODEL/KP_FW/VIN_RANGE/VIN_DROP_GAIN_RANGE/VIN_MIN/MAX_CURRENT`
与训练 cfg 相等，装配层面断言 `forcerange == 7.4·kt/R`、`dof_armature == get_extra_inertia()`、
`ctrl` 就是力矩、每步重写 `dof_frictionloss`。**但它一个字都没断言轨迹、速度、是否摔倒。**
锁住的是执行器，不是动力学数值。这与 §13.1 是同一个模式的第二个实例：**结构有测试，
行为没有**。

### 14.2 `rehearse_deploy.py`：只换外层循环，不重写栈

`infer_policy.py` 的两个「不能直接用」：`import termios, tty`（Windows 没有），
以及末尾必然进 viewer + 键盘循环（`NativeMujocoViewer(...).run()`），**没有 headless 开关**。

所以这个工具的做法是**加载上游模块，复用它的全部实现**——
`load_bam_model` / `load_mujoco_with_bam` / `PolicyInference.get_observations/infer/apply_action`
——只把最外层换成「固定条件进、JSON 出」的循环。`termios`/`tty` 用两个惰性 stub 塞进
`sys.modules`（彩排路径不碰它们）。

**为什么不自己重写一份**：重写就是第二个意见，而两个独立实现一致并不能证明「发出去的那份」
对——同一个理由见 §13.2。复用上游才让它是一次**测量**而不是一次复述。

```bash
MUJOCO_GL=glfw python tools/flat_walk/rehearse_deploy.py \
  --onnx artifacts/flat_walk/checkpoints/walk_std004_1250.onnx \
  --infer-policy /path/to/microduck_rl/scripts/infer_policy.py \
  --cmd-vx 0.4 --seconds 8 --sweep --out out/rehearse_1250_sweep.json
```

六个条件是训练 DR 的采样点：`nominal`(7.4 V, sag 0.1) / `low_batt`(6.5 V, sag 0.2) /
`high_batt`(8.2 V, sag 0) / `train_lag{3,4,6}`（训练同款执行器延迟）。
前提三件不在本仓库：上游 `infer_policy.py`、`mjlab_microduck` 任务包（含 scene XML）、
`mujoco`——与 §7.0 的可复现边界同一条，工具能支持的说法只是「给定同一任务包与环境，
输出里的每个数能按 `settings` 复算」。

其余三组（负对照 / 低速 / 零指令），`--infer-policy` 与 `--onnx` 同上省略：

```bash
# 负对照：同一图、同一命令，换回 XML 位置伺服。P3 由 ctrl 探针判，不看这条的 vx
... --cmd-vx 0.4 --seconds 8 --condition nominal --no-bam --out out/rehearse_nobam.json

# 低速：必须每档扫 yaw。单机固定初态只等于一个样本，双稳态会被它掩盖（§14.7）
for c in 0.12 0.15 0.20; do for y in 0 45 90 135 180; do
  ... --cmd-vx $c --seconds 8 --condition nominal --yaw-deg $y \
      --out out/rehearse_cmd${c}_yaw${y}.json
done; done

# 零指令：all-zeros 是 stand 语义（AGENTS.md:265-269），单独跑、单独解读
... --cmd-vx 0.0 --seconds 8 --condition nominal --out out/rehearse_cmd0_standslot.json
```

`speed.comparable=false` 的跑（摔过的）不要写进任何速度对比——只写 `fell_at_s`（§14.6）。

### 14.3 判据先定死，跑完不许改口径

| 判据 | 通过条件 | 含义 |
|---|---|---|
| **P1 站得住** | `nominal` 与 `high_batt` 都 `fell=n` 且 `dx > 2.0 m` | 部署栈能工作 |
| **P2 电压下限** | `low_batt` 摔倒与否**如实记录**，不设预期 | 决定部署 vin 下限 |
| **P3 执行器路径** | `max abs(ctrl − (default_pose + action·scale))`：BAM **> 1e-3**、`--no-bam` **< 1e-9** | 证明 BAM 真的接在控制路径上 |
| **P4 形状** | `obs_dim == 61`、`nu == 14`、执行器顺序 == `DEFAULT_POSE` 顺序 | 已在工具自检期逐项验过 |
| **P5 延迟维** | **不作结论，只记录** | 见 §14.6 末：彩排的延迟路径与训练不是同一件事 |
| **P6 覆盖窗口** | `window.valid_s >= 0.75 × seconds` | 摔了的跑窗口不足，速度不可引用 |
| **P7 低速维** | **不作结论，只记录** | 见 §14.7：单机在低速只给一个样本，且方向与 0.4 相反 |

**P3 改过一次，改法本身就是教训。** 原来的 P3 是「`--no-bam` 与 BAM 的 vx/tilt 明显不同」。
实测 BAM 0.4626 / 9.1° vs no-BAM 0.4145 / 5.9°——**vx 只差 10%，落在条件之间的散布里**，
既没有阈值，也不能「为了正确的理由失败」。改成量纲判据是因为去读了那一行源码：

```python
# infer_policy.PolicyInference.set_position_targets
if self.bam_ctrl is not None:
    self.bam_ctrl.q_target[:] = target_positions   # BAM: update() 写的是力矩
else:
    self.data.ctrl[:] = target_positions           # legacy: ctrl 逐位就是目标角
```

⇒ `max|data.ctrl − target|` 是天然的二值量，实测 **BAM 0.407 / no-BAM 0.000e+00**，
阈值 1e-3 有 400 倍裕度。`--no-bam` 的 vx/tilt 差异照旧记录，但它回答的是另一个问题
（「同一策略换一套被控对象会怎样」），不是「BAM 接上没有」。

### 14.4 工具自检期读数（JSON 尚未入库，以重跑为准）

以下数字来自**工具自检**（同一脚本、`walk_std004_1250.onnx`、cmd 0.4、8 s、单机）。
它们的作用是证明这个仪器**能测出差异**，正文表等 `evals/rehearse_*.json` 入库后替换。

| 条件 | vx (m/s) | dx (m) | 摔倒时刻 | tilt（触发值；未摔则最大） | 说明 |
|---|---|---|---|---|---|
| `nominal` | 0.4632 | 3.545 | — | 9.1° | P1 通过 |
| `high_batt` | 0.4526 | 3.485 | — | — | P1 通过 |
| `low_batt` | **n/a** | — | 2.64 s | 71.87° | 见 §14.6：摔了就不能引速度 |
| `train_lag3` | **n/a** | — | 1.88 s | 81.54° | P5：不作结论 |
| `train_lag4` | **n/a** | — | 1.36 s | 72.26° | 同上 |
| `train_lag6` | **n/a** | — | 0.84 s | 73.32° | 同上，延迟越大摔得越早 |
| `nominal + --no-bam` | 0.4145 | 2.794 | — | 5.9° | 负对照；P3 由 ctrl 探针判 |

P3 探针：BAM **0.407** / no-BAM **0.000e+00**（阈值 1e-3）。P4：`obs_dim 61`、`nu 14`、
执行器顺序逐项 == `DEFAULT_POSE`（left_hip_yaw … right_ankle）。

### 14.5 三个「不可比」的出处

1. **官方只说这是 rehearsal，没说数字可比。** `AGENTS.md:21` 的括注是
   「CPU MuJoCo deployment rehearsal (BAM M6 actuators as in training; `--no-bam` = XML PD)」；
   `AGENTS.md:265-269` 说它的用途是「rehearse ... **before touching the robot**，
   用正确的命令槽（a posture flag lives in the twist vx slot; feeding all-zeros means
   stand）」。⇒ 资料把它定位成**接口与命令槽验证**，不是性能测量。
2. **执行器一致有测试锁，性能一致没有**（§14.1）。
3. **训练有 3–6 步执行器延迟，彩排默认没有**：
   `microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS` 是 `delay_min_lag=3, delay_max_lag=6`
   （50 Hz ⇒ 60–120 ms），而 `infer_policy.py --delay` 默认关闭、
   `tests/test_infer_policy_bam.py` 也没把 delay 纳入断言。⇒ 「nominal」在这里比训练**更轻**，
   不是「等于训练」。

再加两条仪器差异，写进输出的 `training_parity` 块里：CPU MuJoCo（Newton/implicitfast）vs
训练侧 warp/MJX；本仓库 scene 用 XML 的 `self_collision_only` 类，而训练是
`collisions=(FULL_COLLISION,)`；摩擦在训练侧由 `FrictionDRBamActuatorCfg` 逐 env 随机，
这里是 XML 固定值。

**方向也不一致**：无延迟彩排 vx 0.463，32-env 评估 0.312，彩排快 49%。这不是标定偏移，
是两台仪器。与 §12.5「跨版本评估脚本不可混用」是同一条纪律的延伸——**只在同一仪器内部纵比**
（BAM vs no-BAM、高压 vs 低压）。

### 14.6 两个读数坑，都会让「摔倒的跑」报出一个好数字

**坑一：摔倒后继续跑，把「躺在地上」算进速度。** 训练侧 `cfg.terminations` 是四条
（`time_out`(True) / `fell_over`(False, `bad_orientation`, `limit_angle=1.2217304763960306`
rad = **70.0000°**) / `out_of_terrain_bounds`(True) / `nan_state`(False)），也就是**摔倒即
episode 结束并 reset**。脚本原来只在 NaN 时 break ⇒ `low_batt` 2.64 s 摔倒后继续躺跑 5.4 s，
报出 `vx=0.4627 / ratio 1.157`，与没摔的 `nominal`（0.4626）几乎一样。
**两个数不可能同时成立**——这就是它的破绽。修法：`TRUNCATE_AT_FALL=True`，触发那步即 break
且触发样本不记入。

**坑二：截断之后仍有存活偏差。** 截断后 `low_batt` 变成 **0.5389 > nominal 0.4632**，
因为剩下的窗口恰好是它跑得最好的那一段——活下来的时间越短，均值越乐观。
⇒ **摔倒的跑，vx 一个数都不能引用**。现在直接输出 `vx=n/a(fell)`、`speed.comparable=false`
并附原因，表里只允许出现 `fell_at_s`。

两个配套修正：`FALL_TILT_DEG` 从拍的 60° 改成训练值 **70°**（两者实现是同一个量
`degrees(acos(−g_z))`，阈值照抄不调）；新增 `window.tilt_at_fall_deg` 记录**触发那一步**的值
——因为触发样本不进 `tilt_hist`，只报 `max_tilt_deg` 会显示 66–67°，看起来像「判据没到就判摔」。
`max` 和「触发值」不是同一个东西，这是「派生量要单独验一遍」的又一例。

**延迟维为什么只记不作结论**：实测延迟 3/4/6 步 ⇒ 摔在 1.88 / 1.36 / 0.84 s，单调；
但训练侧在同样 3–6 lag 下几乎不摔（评估终止率 0–7.3%）。⇒ 彩排的延迟路径与训练不是同一件事
（最可能是 `last_action` 观测的语义不同：训练时策略看到的是延迟后的自身动作，
彩排记录的是延迟前的）。这是**工具缺口**，不是策略结论。

### 14.7 单机在低速区只给一个样本——而这件事本身就是结论

`cmd=0.15` 扫五个初始朝向（`--yaw-deg 0/45/90/135/180`，训练 `reset_base` 的 yaw 是
`(-π, π)` 全随机，固定初态等于只抽一支），**五个全部站着不动**：vx −0.0000、
dx +0.008…−0.008 m、max tilt 3.3°。

而 32-env 评估侧同一 ckpt、同一 `cmd=0.15` 是 **ratio 0.533、`frac站` 0.06**。
**这两组不可能同时成立**——不是「抽到了站的那一支」，是彩排在低速稳定收敛到「站」。
与 `cmd=0.4` 的方向**相反**（彩排 0.463 vs 评估 0.312，快 49%），所以这不是整体标定偏移，
而是低速区行为不同。最可能的解释：彩排单机、确定性初态、无摩擦随机化、无延迟；
评估侧 32 台带 3–6 lag 与摩擦 DR，扰动会把一部分 env 推过死区边界——与 §11
「死区是行为选择、不是噪声」一致。

⇒ 低速段只能回答「单个确定性初态下站不站得住」，**不能**回答「部署下限是多少」。
后者只有 32-env 扫描能答，已有的答案是 **0.15 m/s**（§10.3）。

顺带一个假 FAIL：`moves_forward` 闸门在 `cmd<0.2` 时必然红，但那里的 `dx≈0` 是策略的正确
行为，不是 obs 布局坏了。已改成 `cmd < 0.2` 记 `not_applicable`。
**闸门也要分「策略行为」与「接线错误」**，否则低速扫描每次都是红的一片。

另外 `cmd = 0` **不是**「走得很慢」：`AGENTS.md:265-269` 明说 all-zeros 是 stand 语义
（posture flag 占 twist 的 vx 槽），它是一个独立命令模式，要单独解读、不与低速点并列。

### 14.8 结论与遗留

- **彩排能做、且做完了工具**：`tools/flat_walk/rehearse_deploy.py`，七条判据里 P1/P2/P3/P4/P6
  可判定，P5/P7 明确定为「只记录」。这就是「判据可判定」的意思——不是所有维度都该有结论。
- **能声明的**：部署栈（BAM M6 + XL330 电压模型 + 50 Hz 环）在 nominal / high_batt 下站得住
  且向前走；BAM 确实在控制路径上；obs/动作形状与训练契约一致。
- **不能声明的**：跑得多快（两台仪器）、低速下限（单机样本不足）、延迟鲁棒性（路径不一致）。
- **遗留**：① `evals/rehearse_*.json` 未入库，正文 §14.4 的数字需重跑后替换；
  ② 真机仍缺（仓库约定暂无实体机器人）；③ 上游 `testbench_sim2real.py` 是更便宜的下一步
  ——同一 ONNX 在 sim(BAM) 与真机 XL330 上跑同一角度序列做对比，只需**一个电机 + 一个 USB 口**。
