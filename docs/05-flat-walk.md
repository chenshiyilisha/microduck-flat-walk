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

_（2026-10-26 修订：本节最初把任务包归为 `tailong-wu/microduck-mjbatch`——**归因错误**。
那个仓是纯 CPU 的 mjbatch 实现，依赖里没有 mjlab，从未参与本节任何训练。实际任务包来自
**官方** `pollen-robotics/microduck_rl`（2645★，Apache-2.0，public）的 `develop` 快照，
训练入口见 `microduck-software/tools/train_velocity.sh`，其注释写明
"upstream-native task: its cfg is byte-identical to `.upstream/microduck_rl-develop/...`"。）_

本仓库 `third_party/` 下两条 submodule 的 URL 继承自上游 DuckEMW，原指向
`github.com/emwstudio/microduck_rl` 与 `github.com/emwstudio/microduck-playground`
（**均 404**：私有或已删），外部读者拿不到内容。**这是上游指针的问题，不是官方私有化**——
两个 public 原仓都存在：`pollen-robotics/microduck_rl`（任务包本体）与
`Vottivott/microduck-playground`（Hannes von Essen 的可复现实验仓，running 配方出处）。
`.gitmodules` 已改指 public 原仓，gitlink pin 到
`microduck_rl@b02fdea`、`microduck-playground@f010ef1`。

#### 快照核对（2026-10-26，方法与结果）

训练所用的任务包是官方 `develop` 的**解压快照 + 纯追加补丁**，不是纯官方。核对方法：
取 `b02fdea` 的完整 tree（254 个 blob），对本地快照每个文件重算 git blob sha1 逐一比对。

| 结果 | 数量 | 明细 |
|---|---|---|
| 逐字节相同 | **249** | 含 `microduck_velocity_env_cfg.py`（velocity cfg 与官方零差异） |
| 纯追加补丁 | 5 | `mdp.py` +380（**全部为 joy 函数群**）；`export.py` +56（joy 导出元数据）；`microduck_constants.py` +42（`pd_actuators` PD 执行器，joy 用）；`tasks/__init__.py` +10（joy 注册）；`symmetry.py` +18/−1（唯一被改的「1 行」是一个行内注释换成维度防御检查） |
| 快照新增文件 | 2 | `microduck_joy_env_cfg.py`、`tests/test_joy_cfg.py`（joy 专用，velocity 不引用） |
| 快照多余垃圾 | 7 | `__pycache__`、`.pytest_cache`、`mdp.py.pre-sync` 备份（不入库） |

⚠️ **修正（2026-10-26 第二次核对）**：最初把 mdp.py 头部的 NaN 防护（`Patch 1-2`）、
导出元数据（`Patch 4`）、WARM_START（`Patch 5`）当成我们打的补丁——**错，它们是官方
`b02fdea` 自带的**（官方 `mdp.py:25` 起就有）。即 **velocity 任务的官方代码零自加补丁**；
5 个文件的追加全部是 joy 专用，velocity 任务一行都不引用。

补丁重放已闭环为一条命令：`tools/upstream_patches/replay_all.py`（11 个工具 + 15 KB 的
`rc_joy.patch` 输入入库；前置自检 submodule 在 `b02fdea`；末尾按快照实测的 EOL 表归一
行尾并打印 velocity 关键文件 sha1）。重放验证：**254/256 文件与训练快照逐字节一致**；
唯二残差（`mdp.py`、`microduck_joy_env_cfg.py` 的 joy 段）来自已丢失的
`tools/patch_joy_foot_peak.py`，效果只存在于 joy 任务，velocity 路线不受影响。

本节全部数字产生于官方 `microduck_rl` 快照注册的 `Mjlab-Velocity-Flat-MicroDuck` 任务包，
环境：Python 3.12 + `mjlab 1.3.0` + `mujoco_warp 3.7.0.1` + `warp-lang 1.12.0`，
RTX 4070 Laptop 8 GB。

所以「可复现」在本文的确切含义是：

- **给定同一份任务包与环境**，`artifacts/flat_walk/evals/*.json` 里每个数都能用
  `tools/flat_walk/eval_velocity_in_sim.py` 逐位算回来（同参：32 envs × 8 s × cmd 0.4 × solver 100/50）；
- `runmeta` 里的 `cfg_byte_identical_to_upstream: true` 和 cfg/mdp 的字节哈希，
  是「没有偷偷改奖励」的机器证据；
- **公开读者**：`git clone --recurse-submodules`（submodule 已指 public 原仓）后
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
  **部署彩跑正式数据**（§14.4，`evals/rehearse_*.json` 已入库：P1/P3/P4/P6 通过，
  P2 记录 6.5 V 不可用，P5/P7 只记录不作结论）。
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

> **2026-10-30 指针**：XL330 线已不推进；本节的两个候选方向在 HD1910 线上的对应解法
> 已定——给训练加 heading 闭环（`rel_heading_envs > 0`，每步重算 `cmd[2]` 比例控制器），
> 工具与机制验证就绪、取值 0.30 已定稿，且与 P3 植物切换合并为**同一次**重训。
> 完整依据见 `docs/active/microduck-HD1910软件方案.md` §P3 附；
> 仪器：`microduck-software/tools/hd1910/probe_heading_loop.py`、`train_heading_variant.py`。

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
`high_batt`(8.2 V, sag 0) / `train_lag{3,4,6}`（原标「训练同款执行器延迟」，**实为
60/80/120 ms，是训练带的 2–4 倍，见下方单位更正**）。

> ⚠️ **2026-11-02 单位更正（延迟维）**：`train_lag{3,4,6}` **不是**训练同款延迟。
> 训练侧 `apply_delay()` 在 decimation 循环内、每次 `sim.step()` 之前执行
> （`mjlab/entity/entity.py::write_data_to_sim` 的 docstring 原文："Called before each
> `sim.step()` within the decimation loop"），所以 `delay_min_lag=3 / delay_max_lag=6`
> 的单位是**5 ms 物理步** ⇒ **15–30 ms**。彩排的最外层循环跑在 50 Hz，`--delay=N` 的单位是
> **20 ms 控制步**。于是旧 `train_lag3/4/6` 实际测的是 **60/80/120 ms**。
>
> 结论影响：§14.4 那三行的读数仍然成立，但它们证明的是「**60–120 ms 站不住**」，
> **不能**用来证明训练带内的 15–30 ms 站不住。条件已改名为 `delay1/2/4`（20/40/80 ms），
> 输出里带 `delay=NNms`，超过 30 ms 的会标 `(>band)`。**延迟维继续只记缺口、不作判决**。

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

### 14.4 正式读数（2026-10-26，JSON 已入库 `evals/rehearse_*.json`）

正式跑与自检期**逐位一致**（nominal 0.4632/3.545、high 0.4526/3.485、low_batt 摔 @2.64 s、
lag 1.88/1.36/0.84 s、no-bam 0.4145/2.794）——脚本自 §14 定稿后未被改动，符合 §14.8 预期。

| 条件 | vx (m/s) | dx (m) | 摔倒时刻 | tilt（触发值；未摔则最大） | 说明 |
|---|---|---|---|---|---|
| `nominal` | 0.4632 | 3.545 | — | 9.1° | **P1 通过** |
| `high_batt` | 0.4526 | 3.485 | — | 8.2° | **P1 通过** |
| `low_batt` | **n/a(fell)** | — | 2.64 s | 71.87° | P2 如实记录：6.5 V 下限站不住 |
| `train_lag3` | **n/a(fell)** | — | 1.88 s | 81.54° | P5：不作结论，只记录 |
| `train_lag4` | **n/a(fell)** | — | 1.36 s | 72.26° | 同上 |
| `train_lag6` | **n/a(fell)** | — | 0.84 s | 73.32° | 同上，延迟越大摔得越早 |
| `nominal + --no-bam` | 0.4145 | 2.794 | — | 5.9° | 负对照；P3 由 ctrl 探针判 |

**P1–P7 判定**（判据见 §14.3，跑前已定死）：

- **P1 站得住：通过**。nominal 与 high_batt 均未摔、dx > 2 m（3.545 / 3.485）。
- **P2 电压下限：记录为 6.5 V 不可用**。low_batt 2.64 s 摔倒（触发 71.87° > 70° 判据）；
  摔倒的跑 vx 记 n/a，不进任何对比（§14.6）。
- **P3 执行器路径：通过**。BAM `max|ctrl−target|` = 0.407（>1e-3），no-BAM = 0.000e+00
  （<1e-9），阈值两侧各 400× 裕度。lag 条件因摔倒截断，探针不记录（None），不影响判定。
- **P4 形状：通过**。全部跑 `obs_dim 61`、`nu 14`、执行器顺序逐项 == `DEFAULT_POSE`。
- **P5 延迟：只记录**。lag 3/4/6 → 摔 1.88/1.36/0.84 s（单调），训练同 lag 几乎不摔 ⇒
  彩排延迟路径与训练不是同一件事（§14.6），缺口保持开放。
- **P6 覆盖窗口：对可引用的跑通过**（8/8 s）；摔倒跑 valid < 75% 且 vx 已记 n/a，一致。
- **P7 低速：只记录**。cmd 0.12 / 0.15 × yaw {0,45,90,135,180} **15/15 全站**
  （vx ≈ 0、tilt ≤ 3.3°）；cmd 0.20 × 5 yaw **15/15 全走**（vx ≈ 0.136，ratio 0.68）。
  与 32env 评估（0.15 ratio 0.533）方向相反 ⇒ 单机低速不可结论（§14.7），
  部署下限仍以 32env 的 **0.15 m/s** 为准。
- **零指令（stand 槽）**：vx −0.0001、dx 0.000、tilt 1.4°，8 s 纹丝不动——
  策略在 stand 语义下行为正确（真机 walk/stand 热切换需要 stand 策略，这一条是个正面信号，
  但不等于我们有合格的 stand 策略，见 §12 的 `--switch-threshold`）。

P3 探针：BAM **0.407** / no-BAM **0.000e+00**（阈值 1e-3）。P4：`obs_dim 61`、`nu 14`、
执行器顺序逐项 == `DEFAULT_POSE`（left_hip_yaw … right_ankle）。

### 14.4b 结论（彩排能支持的说法）

- **能**：部署栈（导出图 + BAM 执行器 + 电压模型 + 50 Hz 环）在 nominal/high_batt 下
  接口正确、站得住、按指令方向走；ctrl 路径探针证明 BAM 真的接在控制路径上；
  stand 槽行为正确。
- **不能**：任何速度数字与 32env 评估混用（仪器差 §14.5）；延迟行为下结论（P5）；
  低速行为下结论（P7）。
- **新增的部署侧事实**：**6.5 V 不可用**（2.64 s 摔）——上游 BAM VIN 下限就是 6.5 V，
  这条把「契约允许」与「策略撑得住」区分开了。

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

---

## 15. 台架实测 HD1910（P3 植物）：单关节到底跟不跟得上

§14 只能回答"部署栈站不站得住"，回答不了"单关节能不能跟上步态"。这一节用一个舵机回答。
仪器 `tools/hd1910/servo_probe/hd1910_ident.py sine`：给 goal 发正弦，单频最小二乘拟合出
幅值比 / 相位滞后 / 残差，产物 `out/sine/*.csv|json`（**已入库**，见 §15.4）。ID 10 @ COM3。

判据沿用 §14 的口径：`gain ≥ 0.8 且滞后 ≤ 30°` 才算跟上；`gain < 0.6 或滞后 > 60°` 判跟不上。

### 15.1 主结果：4.5 V 下没有任何 P 能在步态点跟上

正弦 ±16.9°（= knee 半幅 = 192 步），P=5 是 P3 部署值：

| P | 1.0 Hz | 1.5 Hz | **1.89 Hz（步态主频）** | 2.5 Hz |
|---|---|---|---|---|
| 5 | 0.679 / 65° | 0.506 / 91° | **0.433 / 116°** | 0.249 / 233° |
| 16 | — | — | 0.710 / 103° | — |
| 32（出厂） | 0.996 / 23° | 0.940 / 44° | 0.750 / 105° | 0.514 / 220° |

滞后 116° = **171 ms**，在 50 Hz 环里是 8.5 个控制周期。即使出厂 P=32 也只有 0.750，
说明这不是"P3 选错了 P"，而是**这代舵机在 4.5 V 下的闭环带宽天花板**。

### 15.2 排除法：不是饱和、不是缺电、不是限速

三个独立的否证，任何一个成立都会改变结论：

1. **不是饱和/缺电**：P5 幅度扫描（2°→16.9°）gain 几乎恒定（0.454 / 0.453 / 0.439 / 0.433），
   峰流只 98→351 mA。同幅度下 P32 是 1.010。饱和的特征是"小幅度好、大幅度差"，P5 没有。
2. **不是力矩限制**：把 `reg48` 从 500（50%）抬到 1000（100%），gain 0.433→0.435、
   峰流 344→351 mA —— **无变化**。
3. **不是速度限速**：`reg46` 三点标定（150 / 300 / 450，600 步阶跃）整定时间全是 382 ms、
   峰速全是 ~67 units，**三档完全相同** ⇒ mode=4 下 `reg46` 根本不是有效约束。
   ⚠️ 这条**撤回**了本节早期写下的"部署脚本必须写 reg46"——写不写都一样。
   真正影响速度的是 `reg41` 加速度与供电电压。

### 15.3 电压：唯一没被实测闭合的维度

全部 4.5 V（USB 供电，规格 4–8.4 V 的下限附近）。规格书给了外推依据：
空载速度 92 RPM @6 V → 113 RPM @7.4 V，比值 1.228 ≈ 电压比 1.233 ⇒ **速度能力 ∝ V**。
按 4.5→7.4 V（1.64×）缩放环路增益推 P5 gain → ~0.62（**推算，未实测**）。

但**单点 7.4 V 实测也不是真机工况**：社区记录 7.4 V 整机走起来母线跌到 6.5 V 触发保护，
抬到 ~8.0 V 才稳。所以台架该回答的不是"7.4 V 多少"，而是"电压区间内策略是否都站得住"——
这个问题用仿真扫更合适（§15.5）。

### 15.4 工程遗留

- ✅ `step` / `sine` 写 `reg48` 不恢复 —— 已修（存原值 + 恢复 + 回读）。
- ✅ 遥测 `speed` 字段量纲 ≈ **53 步/s per unit**（≈4.7 °/s）却按"步/s"打印 —— 已修：
  峰速改由**位置差分**算，取 **p95**（单点 max 噪声 ±20%，只作为参考同时打印），
  遥测字段改名 `speed_field_peak_raw` 不再冒充速度。`selftest` 加了负对照：
  把 speed 字段 ÷54 后重算，位置差分峰速必须**逐位不变**（证明新口径不依赖该字段）。
  修之前脚本会把峰速打成 ~37500「步/s」，而物理上限是 3400 —— 一眼就该发现。
- ⚠️ `hd1910_ident.py --help` 曾经**整个崩掉**：`--torque-limit` 的 help 里写了 `100%`，
  argparse 把它当格式符（`_expand_help` → `ValueError`）。已改写成「1000 = 满量程」。
  ⇒ **argparse 的 help 字符串不能出现裸 `%`**。
- 正弦拟合对频率错标不敏感（错标 1.3× 仍给 gain 0.809），**必须同时看残差**（判据 >3%）。
- 台架产物已入库：`microduck-software/out/sine/`（`.gitignore` 里 `out/*` + `!out/sine/`）。

### 15.4b ⏳ reg46 / reg41 单变量 A/B（待硬件，脚本已就绪）

原结论「reg46 300→4095 把整定 561→161 ms」已撤回，但**那个 A/B 本身从没被正确跑过**：
`_arm()` 一次写三个寄存器（reg46 / reg41 / reg48），只盯 reg46 就会漏看 reg41。
`tools/hd1910/ab_reg4641.sh` 把两个变量分开（改一个钉死另一个），每档 3 次重复，
并且 **reg46/41/48 的请求值与回读值都进 JSON**（请求 4095 可能被固件截断，
"我发了" 不等于 "它生效了"）。`hd1910_ident.py step --json PATH` 是该脚本的数据源。

```bash
PORT=COM3 ID=10 REPS=3 bash tools/hd1910/ab_reg4641.sh
```

判据：整定时间与峰速一起看——只有速度变了而整定没变，才说明该寄存器不是瓶颈
（或在该 mode 下无效）。汇总逻辑已用合成 JSON 干跑验证（含回读截断告警）。

### 15.4c ✅ `moves_forward` 闸门：闭环转向下的假 FAIL 已修

判据原是「沿**初始朝向**的净位移 `dx_body > 0.02`」。闭环把机器人转到目标朝向时净位移
可为负 ⇒ 32 组里 15 组（未摔倒、vx 0.07–0.11 全为正）判 FAIL、退出码 1，被当成失败读了两天。
现改为：初始航向误差 >30° 时判 `vx_mean_steady > 0.02`；否则仍用 `dx_body`。
`dx_body` 照旧进报告，`forward_gate_basis` 记录这一档用的是哪个量。
负对照：`--action-scale 0`（策略不动）→ vx = −0.0004 → 闸门**仍然 FAIL**（没有放宽）。

### 15.5 对应的仿真侧检查

`tools/rehearse_deploy.py --sweep` 现在含 `low_volt`（4.5 V，与台架同电压，可作软硬件锚点）、
`nominal`（7.4）、`low_batt`（6.5，sag 0.2）、`high_batt`（8.2）。首次结果（it1600 ckpt）：

| 档 | vin | vx_mean | ratio | 摔倒 |
|---|---|---|---|---|
| low_volt | 4.5 | 0.1085 | 0.271 | 否 |
| low_batt | 6.5 | 0.1192 | 0.298 | 否 |
| nominal | 7.4 | 0.1342 | 0.336 | 否 |
| high_batt | 8.2 | 0.1406 | 0.352 | 否 |

两点值得记：① 电压单调性成立；② **最悲观档也没摔，vx 相对 nominal 只掉 19%**——
单关节 gain 掉 33% 而整机速度只掉 19% ⇒ **整机对舵机带宽的敏感度远低于单关节跟踪**。
⚠️ 该 ckpt 无 heading 奖励，各档 yaw 漂移 -145°/+83°/+130°，**数字只能内部纵比，不能当部署结论**。

## 16. 固件 P 该写几：台架 / 仿真 plant / 整机三边对照

§15 排除了一切外部嫌疑（力矩、限速、时间约束、饱和、死区、模式语义）之后，
唯一剩下可调的是**固件位置环 P（RAM reg50 = BAM 的 `kp_fw`）**。本节给出三边证据。

### 16.1 台架（4.5 V，1.89 Hz ±16.9°，只改 reg50）

| P | gain | 滞后 | jerk× | 峰流 | 判据 |
|---|---|---|---|---|---|
| 5 | 0.435 | 115.9° | 1.00 | 364 mA | 带宽不足 |
| **8** | **0.623** | 105.1° | **1.15** | 462 mA | **甜点** |
| 12 | 0.714 | 99.0° | 2.09 | 624 mA | 抖 |
| 16 | 0.721 | 100.4° | 2.90 | 871 mA | 抖 |
| 24 | 0.763 | 98.7° | 3.38 | 1216 mA | 抖 |
| 32 | 0.767 | 101.8° | 3.50 | 1339 mA | 抖 |

**滞后几乎不随 P 变**（P 放大 6.4 倍只降 17°）⇒ 这 100 多度主要是**纯延迟**，不是增益不足。

### 16.2 仿真 plant 只在自己的工作点成立

BAM free-shaft（`probe_kp5_bandwidth.py`，同一 plant json，只改 kp）：

| P | 台架 4.5V gain/lag | BAM 4.5V gain/lag | gain 误差 | lag 差 | BAM 7.4V |
|---|---|---|---|---|---|
| 5 | 0.435 / 115.9 | 0.439 / 86.4 | **+0.8%** | −29.5° | 0.670 / 70.4 |
| 8 | 0.623 / 105.1 | 0.657 / 71.4 | +5.4% | −33.7° | 0.863 / 53.4 |
| 12 | 0.714 / 99.0 | 0.831 / 56.6 | +16.4% | −42.4° | 0.963 / 40.3 |
| 16 | 0.721 / 100.4 | 0.920 / 46.7 | +27.6% | −53.7° | 0.998 / 32.8 |
| 32 | 0.767 / 101.8 | 1.009 / 28.7 | +31.6% | −73.1° | 1.017 / 21.1 |

🔑 **P=5（训练用的那个值）上 BAM 是准的**（0.439 vs 0.435），**P 越大越乐观**（P32 高估 32%）。
⇒ **仿真没有资格裁决 P8/P12 的收益**，那些只能由台架背书。

### 16.3 定性差异：台架是纯延迟，BAM 是一阶滞后

台架 kp5 多频点滞后 1.0→65.4°、1.5→90.7°、1.89→116.0°，反推延迟 **182 / 168 / 171 ms**
（±7% 一致）；一阶系统滞后上限是 90°，台架远超 ⇒ **必含纯延迟**。
BAM 同频点滞后 58.5 / 75.7 / 86.4 / 100.4°，隐含延迟 **162→140→127→112 ms 随频率下降**
⇒ **一阶滞后**。

⇒ **提 P 能改 BAM 的相位，改不了台架的相位**。BAM 恰好在这件事上比硬件乐观，
这是它高 P 时相位误差的来源。⚠️ 170 ms 的量级来源未查明（可能是固件内部滤波/总线轮询），
7.4 V 复测是未闭合项。

### 16.4 整机（彩排，model_1750，8 个初始 yaw，只改 `--kp-fw`）

> ⚠️ **本节结论已于 2026-11-02 被 §18.1 撤回。** 同样的配方换到定稿 ckpt（model_2999）上，
> P8 从 **+23.8% 变成 −13.1%（符号翻转）**，三次复跑逐位相同。这张表保留作为
> 「结论曾经长这样、以及它是怎么被推翻的」的记录，**不要再引用它的数字下结论**。

| P | n | vx mean | sem | 摔倒 | vs P5 |
|---|---|---|---|---|---|
| 5 | 8 | 0.0944 | 0.0035 | 0 | 基准 |
| **8** | 8 | **0.1168** | 0.0033 | 0 | **+23.8%（t=4.69）** |
| 12 | 8 | 0.0939 | 0.0036 | 0 | −0.5% |
| 16 | 9 | 0.1065 | 0.0117 | 2 | +12.8% |

- 混淆已排除：`corr(vx, |Δyaw|) = −0.106`（n=16），差异不是"转得多所以快"。
- **非单调**：P12 回到 P5 水平 ⇒ 不是"P 越大越好"。
- ⚠️ **OOD 评价**：策略在 P5 下训的，换 P 属换植物（§10）。数字只作方向性证据。
- ⚠️ **当时用的 ckpt 是 model_1750**，不是后来的定稿 model_2999。两者在 P5 上差 +19.6%，
  在 P8 上差 −16% ⇒ 这张表测的是「1750 这个 ckpt 对换 P 的鲁棒性」，不是「P8 植物好不好」。

### 16.5 结论（已修正，见 §18.1）

原结论：「kp_fw=8 是唯一三边都支持的改值（台架 gain +43% / jerk 仅 +15% / 整机 vx +23.8%）」。

**修正后**：整机那条腿**没有复现**（§18.1），P8 现在只有**台架一边**支持
（gain +43% / jerk +15%）。换 P8 = 换植物 ⇒ 仍**必须伴随一次重训**，
而且不能指望「只改部署时的寄存器、同一个策略就变好」——实测那是 **−13%**。

## 17. heading 奖励：判决 + 一个配置 bug（含一次指标更正）

### 17.1 ⚠️ 先更正指标：`yaw_delta` 是错的量

`heading.yaw_delta_deg` 是「末−初」。用 `--heading-target-deg 0` 配 8 个不同初始 yaw 时，
**从 180° 起步"成功"本来就要转 ~180°** ⇒ 大 Δyaw 是**成绩**不是失败。
正确的量是 JSON 里本来就有的 **`heading.heading_error_final_deg`（末态到目标的角差）**。

同数据重算（n=8，nominal，target 0）：

| | \|Δyaw\|（错的量） | \|末态误差\|（正确） | vx |
|---|---|---|---|
| model_2000 | 88.2° ±19.7 | **11.4° ±0.8**（9–14） | 0.0973 |
| model_2499 | 88.3° ±19.0 | **14.9° ±1.7**（7–20） | 0.1038 |

⇒ 2500 那 750 轮对**末态误差**也没有改善（11.4 → 14.9，略差），但两个 ckpt **都已达标（≤20°）**。
⇒ **部署指标只能是 `heading_error_final_deg`**；`error_vel_yaw`（70% env 是随机角速度指令）
与 `yaw_delta_deg` 都不能用。

### 17.1b 目标跟随的负对照（排除「固定吸引子」）

末态航向在所有起点下都 ≈+12°，需排除「只是有个吸引子恰好在 0 附近」——换目标后末态跟着走：

| target | 0 | 90 | −90 |
|---|---|---|---|
| 末态航向 | ≈+12 | ≈+108 | ≈−64 |

真跟踪，带 **+15~30° 的系统性偏置**（比例控制器稳态差）。

### 17.1c ✅ 等轮数 A/B：这两项奖励到底有没有用

对照 `2026-11-02_09-28-18_p3head030_4096x2000`（**只有 rel_heading_envs=0.3、无两项奖励**）
vs rw 线 model_2000（**有 heading_hold + heading_tracking**），同为 2000 轮、n=8、target 0：

| | \|末态误差\| | sem | 末态航向范围 |
|---|---|---|---|
| 030（无奖励） | **34.3°** | 2.8 | −18 ~ −43 |
| rw（有奖励） | **11.4°** | 0.8 | +9 ~ +14 |

**Δ = −22.9°，t = −7.79** ⇒ 奖励配方把稳态航向误差降到 1/3，离散度也收窄一个量级。
⚠️ 混淆：030 的 `ang_vel_z` 是 ±1.0、rw 收窄到 ±0.5，两者打包改的，贡献未分离。

### 17.2 直接原因：设计的最后一段权重从未生效

`mjlab_microduck/tasks/mdp.py:3601` 用严格大于：

```python
for stage in weight_stages:
    if env.common_step_counter > stage["step"]:
        term_cfg.weight = stage["weight"]
```

而 `--heading-stage-iters 0,1000,1750,2500` 最后一段 mark = 2500×24 = **60000**，
2500 轮训练的最终 counter 正好也是 60000 ⇒ `60000 > 60000` 为假 ⇒
**tracking 3.0 / hold 0.0 这一段从没被应用**（只因 §17.3 的偏移在末轮摸到 1 轮）。

- 训练脚本原校验 `stage_iters[3] > absolute_total` 漏判等号，已改 `>=` 并写清算术
  （负对照：`0,10,20,30` + 30 轮 → 退出码 1，且在碰 GPU 之前）。
- **判据：课程最后一段的 mark 必须严格小于总轮数**（2500 轮应配 `0,1000,1750,2100`）。

### 17.3 附带发现：每次 resume 会重跑一次边界迭代

| run | counter − (iter+1)×24 |
|---|---|
| 从 0 起的原始 run（model_0…1750） | 全部 **+0** |
| 从 model_1750 续训的 run（1750/2000/2250/2499） | 全部 **+24** |

rsl_rl `load()` 恢复 `current_learning_iteration = it`，`learn()` 接着跑 `range(it, …)`，
边界那一轮被重跑 ⇒ counter 每次 resume 永久多 `num_steps_per_env` 步。
原闸门 `counter == (iter+1)*nse` 因此拒绝一切二级续训；已改为允许整数轮 drift（≤2）并打印，
同时新增从 `params/env.yaml` 回读 weight_stages、报告本次 launch 实际会跑的 tracking 权重。

### 17.4 ✅ 跑满 3.0 段后的定稿：model_2999 是当前最佳

tracking 权重 3.0 真正跑满 500 轮后（此前因 §17.2 的 bug 从未执行）：

| ckpt | tracking 权重 | \|末态误差\| | vx |
|---|---|---|---|
| 030 对照（无 heading 奖励，2000 轮） | — | 34.3° ±2.8 | — |
| model_2000 | 1.5（250 轮） | 11.4° ±0.8 | 0.0973 |
| model_2499 | 1.5（750 轮） | 14.9° ±1.7 | 0.1038 |
| model_2750 | 3.0（250 轮） | **20.8° ±0.8（恶化）** | 0.0920 |
| **model_2999** | **3.0（500 轮）** | **3.7° ±0.6** | **0.1129** |

非单调：权重跳变先恶化、跑满后**两轴同时最好**（误差 −68%、vx +16%，对 2000 轮）。
⇒ **中途 ckpt 不能判配方成败**。

### 17.5 全电压档（model_2999，target 0）

| 电压 | \|末态误差\| | vx | 摔倒 |
|---|---|---|---|
| 4.5 V | 2.4° ±0.6 | 0.1033 | 0 |
| 6.5 V | 1.7° ±0.2 | 0.1055 | 0 |
| 7.4 V (n=8) | 3.7° ±0.6 | 0.1129 | 0 |
| 8.2 V | 1.9° ±0.6 | 0.1010 | 0 |

**4.5–8.2 V 全档达标、零摔倒** ⇒ §21「低压偏航更差」作废（同源于错指标）；
7.4 V 台架实测不再是部署阻塞项。目标跟随负对照：target ±90 → 末态误差均 −6.4°，
两个起点收敛到同一点（真跟踪，稳态偏置由 +15~30° 降至 ~6°）。

### 17.6 ⚠️ 唯一未闭合的部署风险：延迟

| 附加延迟 | \|末态误差\| | vx | 结果 |
|---|---|---|---|
| 20 ms | 2.0° | 0.1267 | 不摔 |
| 40 ms | 7.3° | 0.1319 | 不摔 |
| **80 ms** | 114.5° | — | **1.20 s 摔倒** |

**策略容忍 ≤40 ms，80 ms 必摔**；而 §16.3 台架测到舵机本身约 **170 ms 相位滞后**
（BAM 只建模了一阶滞后）⇒ 真机很可能落在必摔一侧。这是当前第一号部署风险，
并使 §15 的 7.4 V 台架复测重新成为必要项（提高电压可压掉一部分滞后）。

### 17.7 部署链状态

- 导出：`2026-11-02_20-23-39_..._resume2499.onnx`（随 model_2999 落盘）
- parity：**PASS**，max\|Δ\| = 2.514e-06；负对照（拆归一化）偏离 48670× 容差

## 18. kp_fw 对照重做（model_2999 口径）+ P8 植物落地

### 18.1 ⚠️ §16 的「整机」那条腿没有复现：结论符号翻转

§16.3 那个 P8 甜点是三边支持的，其中「整机」一边当时用 **model_1750** 测的。
用定稿 **model_2999** + §17.1 的正确指标重测（p3 植物 / 7.4 V / cmd 0.4 / 8 s /
heading 闭环 target 0 / **n=8 起始 yaw**，与旧批完全同一配方）：

| P | vx mean | sem | \|末态误差\| | sem | 摔倒 | vx vs P5 |
|---|---|---|---|---|---|---|
| **5** | **0.1129** | 0.0008 | 3.73° | 0.59 | 0 | 基准 |
| 8 | 0.0981 | 0.0014 | **1.93°** | 0.38 | 0 | **−13.1%（t=−9.38）** |
| 12 | 0.0829 | 0.0015 | 6.57° | 1.74 | 0 | −26.6%（t=−17.48） |
| 16 | 0.0699 | 0.0049 | 22.21° | 4.68 | 0 | −38.1%（t=−8.64） |

旧批（model_1750）同口径重算对照：

| P | vx | vx vs P5 |
|---|---|---|
| 5 | 0.0944 | 基准 |
| 8 | 0.1168 | **+23.8%（t=+4.69）** |

- 🔑 **P8 的整机优势是 checkpoint 特异的**：model_1750 上 +23.8%，model_2999 上 −13.1%，
  **符号翻转**。⇒ §16.3「三边支持 P8」里的整机这条腿**不能复现**，应视为撤回。
  剩下的支撑只有台架（gain +43% / jerk +15%）。
- 三次复跑与原值**逐位相同**（单 env 固定初始状态下这台仿真可复现），不是噪声。
- 横向看：model_2999 在 P5 比 model_1750 快 **+19.6%**，在 P8 反而慢 **−16%**
  ⇒ 2999 更贴合 P5 植物（它就是在 P5 上训的），换 P 的 OOD 代价随 \|P−5\| 单调增大。
- 航向那一列 P8 更好（1.93° vs 3.73°，t=−2.57），但**两档都早已达标（≤20°）**，
  不构成改植物的理由。

⇒ 这轮测量没有推翻「P8 值得试」，但它**把依据从「三边」降为「只有台架一边」**，
并且明确了一件事：**不能靠换 P 而不重训来拿收益**（−13%）。

### 18.2 `moves_forward` 闸门在闭环转向下会假 FAIL（已知，非失败）

32 组里有 15 组（未摔倒）`dx_body ≤ 0.02`，闸门判 FAIL、进程退出码 1，但数据有效。
原因：闭环把机器人转到目标朝向，净位移沿**初始朝向**的分量可以为负——闸门问的是
「沿初始朝向走了多远」，不是「有没有往前走」。判前进请用 `speed.vx_mean_steady`
（本档 0.07–0.11，全部为正）。**看到这个 FAIL 不要当成摔倒或 obs 错位。**

### 18.3 P8 植物已落地（工具链）

`hd1910_kp8` = 与 P3 **同一份** `official_m6_stslaw.json` + **同一条**官方 STS3215 控制律，
**只有 reg 50（kp_fw）不同**。改动：

- `plant_spec.HD1910_OFFICIAL_M6_KP8`（provenance 里写明了 BAM 在 P8 处乐观 +5.4% gain / −34° lag）
- `apply_to_live.py --plant p8`：⚠️ **回读必须按 kp 区分** P5/P8——两者共用一份 JSON，
  光看文件名分不出来（原先的 `is_official_m6_stslaw ⇒ hd1910_kp5` 会把 P8 认成 P5）。
- `rehearse_hd1910.py --plant p8`；`explore_heading.sh` / `smoke_heading.sh` 的植物闸门
  泛化为 `PLANT=p3|p8`（检测名与期望 kp 都由 PLANT 推导，两条线不能互混）。
- P8 冒烟（64 env × 5 iter，GPU cuda:0）：**PASS**。live 已切到 `hd1910_kp8`
  （sha16 `30768e18ffebf763`，gate_ok True）。

### 18.4 护栏：彩排默认 ONNX 会吃到「没训过」的图（已修）

`--onnx` 缺省时按 mtime 取 `logs/rsl_rl/` 下最新的 ONNX。但**被中止的 run 会留下
iter 0 的 ONNX**、**64×5 的冒烟会留下 iter 4 的 ONNX**，两者 mtime 都比昨夜真 ckpt 新
⇒ 第二天不带 `--onnx` 跑彩排，会静默拿一张**随机初始化**的图当「最新策略」。
已加 `MIN_TRAINED_ITER = 50`：跳过 companion ckpt 迭代号 ≤50 的候选并打印被跳过的文件；
负对照已验（只剩 iter 0 的 ONNX 时打印告警）。

### 18.5 待办：P8 重训（同轮数、同课程，只改 reg 50）

```bash
PLANT=p8 ENVS=4096 ITERS=3000 REL_HEADING=0.30 \
  bash tools/hd1910/explore_heading.sh p8head_030_4096x3000
```

与 model_2999 同轮数（3000）、同课程（`0,1000,1750,2500`，末段 mark 60000 < 72000
⇒ 权重 3.0 真正生效，避开 §17.2 那个坑）、同 `rel_heading_envs=0.30`。

**判决用 2×2 交叉矩阵**（分离「训得好」与「植物好」），每格 n=8 起始 yaw：

| 训练植物 \ 彩排植物 | P5 | P8 |
|---|---|---|
| P5（model_2999，已有） | 0.1129 / 3.73° | 0.0981 / 1.93° |
| P8（待产出） | ? | ? |

- **主判据**：P8×P8 的 vx 相对 P5×P5 显著更高（Welch \|t\| > 3）；
  **副判据**：`\|heading_error_final_deg\|` 不劣于 3.73°。
- 🚫 禁用 `yaw_delta_deg` 与 `error_vel_yaw`（§17.1）。
- 出结果后必须补 **换目标负对照（±90）** 与 **延迟档 20/40/80 ms**
  （P5 定稿 80 ms 必摔，P8 不能更差）。
- ⚠️ 中途 ckpt 不可用于判决（§17.4 非单调）。
- ⚠️ 无论结论如何，**判决后把 live 植物切回 p3**，否则后续彩排都在 P8 植物上，
  而 P5 线的全部数字（含 §17.5 全电压表）都不适用。

### 18.6 🔴 两个启动脚本都不带 heading 奖励配方（2026-11-03 起训前抓到）

`explore_heading.sh` / `smoke_heading.sh` 只传 `--rel-heading-envs`。heading **奖励**
却在 `--heading-hold-weight` + `--heading-tracking-final-weight` + `--ang-vel-z-clip`
后面，**三者都默认 `None`，而 `None` 的含义是「不加这个奖励」**
（`train_heading_variant.py:603-609`）。

- 后果：2026-11-02 的 P8 冒烟与被中止的 4096×3000 **都只验了命令闭环、没验奖励**；
  照原命令开训会得到**没有 heading_hold / heading_tracking** 的策略，与 `model_2999`
  不是一个任务 ⇒ 2×2 交叉矩阵会退化成假对照。
- 权威配方 = `resume_heading_run.py::RECIPE`：hold 1.0 / tracking 3.0 / clip 0.5 /
  stages `0,1000,1750,2500`。两个脚本现已默认对齐它（可 env 覆盖）。
- 新增两道闸门：① 冒烟后断言 run 的 `params/env.yaml` 里出现
  `heading_hold_reward` / `heading_tracking_reward`；② 课程末档必须**严格落在**
  run 之内（末档 ≥ ITERS → 退出码 2，且在建 4096 env **之前**退出）。
  负对照：`ITERS=2000` + 默认表 → exit 2。

🔑 这是「声明 ≠ 生效」失效模式的又一次复发，但换了形态：以前是 CLI 覆盖没回读，
这次是**脚本压根没传，而缺省值恰好是「关掉这个功能」**。
**凡是「默认 None = 不加某物」的开关，启动脚本必须显式列出，并回读功能是否真的出现。**

### 18.7 判决工具：`xplant_matrix.sh` + `await_and_judge.sh`

- `tools/hd1910/xplant_matrix.sh`：2×2 网格一条命令（8 起始 yaw × 2 彩排植物），
  写 manifest，复用 `summarize_rehearsal_grid.py` 钉死口径；含 ONNX 代数护栏
  （companion ckpt < 50 拒绝）。
- `tools/hd1910/await_and_judge.sh`：等末轮 → 等 ONNX 比 ckpt 新 → 自动跑
  ① 2×2 网格 ② `delay4`（80 ms，P5 定稿的硬边界）③ ±90° 目标负对照。
  判据在数字出现**之前**写死，避免事后改口径；无进展 3 min 自动 ABORT。

**两个 bash 坑（干跑抓到，都会毁掉一整批数据）**：

- ⛔ `SECONDS` 是 bash 内建变量（shell 启动秒数），`${SECONDS:-8}` 开局读到 0
  ⇒ 16 次彩排全跑 0 秒。改用 `DUR`。
- ⛔ `${VAR:-default}` 对空串也回落默认值 ⇒ `PLANTS=""` 想跳过循环却跑满。
  要「显式的空」必须写 `${VAR-default}`。

## 19. 台架 vs BAM：增益对上了，相位差 30°（2026-11-03）

第一次把台架扫频和**同一台仿真植物**放在同一口径下对照
（`probe_kp5_bandwidth.py --kp 5 --amp-deg 16.9 --vin 4.5` vs 台架 sine，同 50 Hz 写、同拟合）：

| f Hz | 台架 gain | BAM gain | 台架 lag° | BAM lag° | 缺口 |
|---|---|---|---|---|---|
| 1.00 | 0.679 | 0.690 | 65.4 | 58.5 | 6.9° ≈ 19 ms |
| 1.50 | 0.506 | 0.532 | 90.7 | 75.7 | 15.0° ≈ 28 ms |
| 1.89 | 0.435 | 0.439 | 115.9 | 86.4 | **29.5° ≈ 43 ms** |
| 2.50 | 0.249 | 0.333 | 126.7* | 100.4 | 26.3° |

*2.5 Hz 台架点残差 1.461（其余 ≤0.15），不可信；新版工具已解折叠（真滞后 233.8°）。

- **增益在 1.0–1.89 Hz 对得很好（≤6%）**，1.89 Hz 只差 1.4% ⇒ BAM 的一阶带宽基本对。
- **相位系统性偏乐观 19–43 ms**。台架四次重复 ±0.4° ⇒ 不是噪声。
- 从 8 频点密集扫频拆参数：**τ ≈ 176 ms（0.5–1.89 Hz 一致）** vs BAM ≈ 169 ms；
  但「扣掉一阶后的剩余滞后」从 39 ms（0.5 Hz）单调涨到 77 ms（1.89 Hz）——**不是纯延迟**。

### 19.1 两个候选解释都被否了

- **舵机内部死区**：资料查证（Feetech/lerobot 社区）——内环约 1 kHz、
  `return_delay_time` 默认仅 500 µs、宣传响应 <8 ms ⇒ 不存在 30 ms 级死区。
- **带载下垂**：BAM 恒定 3.9 V 时滞后只 +4°（86.4→90.2°），而缺口 +30° ⇒ 解释不了。
  （台架 0.35 A 就从 4.5 掉到 3.9 V，说明**现在这个电源内阻 ~1.9 Ω**，本身就是要换的。）

### 19.2 结论与动作

1. **BAM 在步态工作点（1.89 Hz ±16.9°）相位乐观 ~43 ms（4.5 V 下）**。7.4 V 未测——
   台架电源到不了，DC-DC 模块（亚博 MP2491C + 12 V 输入）已订，到了重跑同一条扫频闭合。
2. **训练延迟带 15–30 ms vs 实测缺口 26–45 ms：上界刚好卡在实测下沿。**
   ⇒ `apply_to_live.py` 新增 `--delay-lag MIN,MAX`（物理步，5 ms/步），
   下一次重训把带拉到覆盖实测（建议 3..10 = 15–50 ms）。
   ⚠️ 该覆盖会被下一次 `--plant` 重置；`--check` 现在回报
   `delay_min_lag/delay_max_lag/delay_ms`，两个启动脚本的 runmeta 也记录它。
3. **防呆**：`--delay-lag` 的计数与替换都限定在 kwargs 块内——活体文件里
   `pd_actuators`（XmlActuatorCfg）也有一对 `delay_*_lag`，全文件计数会误报拒改
   （实测全文件 5 处、块内 1 处）。
4. **`low_volt` 彩排档（4.5 V）的「零摔倒」结论要打折**：那是仿真在相位上最乐观的工况。

### 19.3 🔑 缺口是「归一化峰速」的单值函数 ⇒ 4.5 V 的 43 ms 不是部署数字

§19.2 提过要把训练延迟带从 15–30 ms 拉宽到 15–50 ms。**这条建议撤回**——
它建立在一个错的前提上：把 4.5 V 下测到的缺口当成了部署缺口。三个新事实把它推翻。

**① 训练域不是 7.4 V 固定值，而是 6.5–8.2 V 的区间。**
live 执行器读回来是 `vin_range=(6.5, 8.2)` + `vin_drop_gain_range=(0.0, 0.2)` +
`vin_min=6.0`（§11 里「出厂默认 vin=7.4」是 **BAM 构造函数默认值**，不是本仓的活体配置）。
⇒ 台架长期使用的 **4.5 V 根本不在训练域内**，§19.1/19.2 的 43 ms 是一个域外读数。

**② 缺口是 `u = 峰速 / 该电压下的最大转速` 的单值函数，与 f、amp 各自无关。**

台架与 BAM **同电压（4.5 V）、同 kp、同拟合口径**，11 个配对点：

| f Hz | amp° | 峰速 °/s | u | 台架 lag | BAM lag | 缺口° | 缺口 ms | BAM peak_duty |
|---|---|---|---|---|---|---|---|---|
| 1.89 | 2.0 | 23.8 | 0.131 | 88.1 | 101.8 | **−13.7** | −20.1 | 0.030 |
| 0.5 | 16.9 | 53.1 | 0.292 | 35.2 | 35.2 | **+0.1** | +0.3 | 0.140 |
| 1.89 | 5.0 | 59.4 | 0.327 | 91.0 | 91.4 | **−0.4** | −0.6 | 0.078 |
| 0.75 | 16.9 | 79.6 | 0.438 | 51.3 | 47.7 | +3.6 | 13.3 | 0.181 |
| 1.89 | 8.5 | 100.9 | 0.555 | 97.0 | 88.0 | +9.0 | 13.2 | 0.131 |
| 1.0 | 16.9 | 106.2 | 0.584 | 65.5 | 58.5 | +7.1 | 19.7 | 0.210 |
| 1.25 | 16.9 | 132.7 | 0.730 | 78.6 | 67.7 | +10.9 | 24.3 | 0.230 |
| 1.5 | 16.9 | 159.3 | 0.877 | 90.9 | 75.7 | +15.2 | 28.1 | 0.244 |
| 1.89 | 16.9 | 200.7 | 1.104 | 116.6 | 86.4 | **+30.2** | 44.4 | 0.257 |

**交叉验证（这才是它成为机制而不是曲线拟合的原因）**：`1.0 Hz ±16.9°`（峰速 106）与
`1.89 Hz ±8.5°`（峰速 101）是两个完全不同的 (f, amp) 组合，**绝对滞后差 31.5°**，
但**缺口几乎相同（+7.1 vs +9.0）**。缺口只跟峰速走，不跟 f 或 amp 各自走。

**③ BAM 在这些工况下根本没饱和**：全部 11 点 `duty_sat_frac = 0.00`，
`peak_duty ≤ 0.257`，而 `max_pwm = 0.97`。所以缺口不是「BAM 饱和 vs 真机饱和」，
而是**真机在需求转速逼近其电压上限时出现了 BAM 没有的额外滞后**。

`u` 的分母用「最大转速 ∝ vin」：官方标称 6 V 时 42 RPM、7.4 V 时 52 RPM，
比值 **1.238**，而 7.4/6 = **1.233** ⇒ 线性成立，归一化有据。

### 19.4 外推：部署域缺口 11–18 ms，落在训练带内

沿 `u` 插值到训练域（步态工作点 1.89 Hz ±16.9°，峰速 201 °/s）：

| vin | u | 缺口° | 等效 ms | 训练延迟带 15–30 ms |
|---|---|---|---|---|
| 4.5（台架） | 1.104 | +29.8 | **43.8** | ❌ 超上界 |
| 6.5 | 0.765 | +11.9 | **17.5** | ✅ |
| 7.4（部署） | 0.672 | +9.4 | **13.8** | ✅（低于下沿 ⇒ 被覆盖） |
| 8.2 | 0.606 | +7.7 | **11.3** | ✅（低于下沿） |

- **在部署电压域，缺口 11–18 ms，全部 ≤ 训练带**⇒ 策略训练时见过的延迟覆盖了它
  ⇒ **植物在工作点是忠实的，不需要拉宽延迟带**。§19.2 第 2 条建议撤回。
- 工具：`tools/hd1910/phase_gap_vs_load.py`（可重跑），数据 `out/sine/phase_gap.json`。
- ⚠️ **这是沿 u 的外推，不是实测。** 它把部署缺口**界定**在 11–18 ms，
  不能替代一次 7.4 V 扫频；但它把优先级从「阻塞项」降为「确认项」。

### 19.5 必须作废的结论：所有 4.5 V 彩排档

- **`low_volt`（4.5 V）档的「零摔倒」不可用**：该档既在训练域外（域下限 6.0 V），
  缺口 43.8 ms 又超出训练带 30 ms 上界 ⇒ 它同时踩了两个坑，数字没有部署含义。
- §17.5「4.5/6.5/7.4/8.2 V 全部零摔倒」里，**只有 7.4 与 8.2 V 两档可信**；
  4.5 V 那档作废，6.5 V 那档可用（在域内、缺口 17.5 ms 在带内）。
- `low_batt`（6.5 V）与 `high_batt`（8.2 V）两档站位正确，保留。

### 19.6 为什么这比买电源更重要

台架电源到不了 7.4 V，原本被当成阻塞项。但**缺口随 u 变化的规律一旦建立，
一个 4.5 V 的数据集就能把部署域的值外推出来**——因为 4.5 V 恰好覆盖了
`u ∈ [0.13, 1.10]` 的整个区间，而部署域落在 `u ∈ [0.61, 0.77]` 的**内部**（内插，非外推）。

仍需实测的只有一件事：确认「真机在 u≈0.67 时的缺口确实约 9°」。这需要 ≥6 V。
进训练域的最低门槛是 **6.0 V**，不是 7.4 V ⇒ 4 节 AA（6 V）或 5 节镍氢就够，
不必等 DC-DC 模块。

## 20. 台架工具链三处纠错（2026-11-03，USB 4.6 V，单颗 ID10）

这一节全部是**仪器层的错误**，不是舵机行为。三条都会让后续调参得出错结论，先修先记。

### 20.1 ⛔ `load` 寄存器解析错：把 11.3% 报成 114.5%

`hd1910_ident.py` 里 `load` 复用了 `signed_mag()`——那个函数的符号位在 **bit15**，
适用于 speed / current。但飞特 STS 的 **Present Load 是 bit10 方向 + bit0–9 幅度**。

后果：读数 1145 > 理论满量程 1000（0.1% 单位）。**上下界矛盾 ⇒ 错的一定是读数。**

修法与负对照：

- 新增 `load_mag()`，`load_max` 改为取**绝对值**的最大值（原来 `max()` 会把整段负值漏掉）。
- 修后 `up = −108 / back = +113`：符号两段相反、方向位与电流符号逐一吻合、无越界元素。
- 负对照：把新值按旧约定还原得 1132（首测 1145，差异来自不同次抽样的峰值）⇒ 确认旧解码错误。

⚠️ **`load` 的物理语义仍是假设**：飞特文档称「负载百分比」，工程界常当 PWM 占空比映射。
两种解读都指向「余量充足」，本条结论不受影响；但**要拿 `load` 当 duty 的定量替代前，
必须先确定语义**，否则又是一个静默偏差。

### 20.2 ✅ 4.5 V 下 duty 余量充足：最坏情况 25.8%，不是 72%

上一轮按「同误差下 duty ∝ 1/P」把 P=32→5 外推成 72%，**实测是 8.8%**。原因：
那个是**静态**公式，阶跃是动态过程——P 小 ⇒ 输出软 ⇒ 轴走得更慢、加速度更小 ⇒
实际负载力矩反而更低。两效应方向相反，实测后者上风。
⇒ **静态公式不能外推动态响应。**

| 增益（4.6 V，200 步阶跃，n=250 样本） | up load_max | back load_max | 整定 ms | 峰速 p95 |
|---|---|---|---|---|
| P=32 / D=40（出厂） | 108（10.8%） | 113（11.3%） | 842 | 35.2 °/s |
| **P=5 / D=0（部署）** | 88（8.8%） | 88（8.8%） | **1221** | 30.8 °/s |

「软腿」到这里有数字了：**P=5 比 P=32 慢 45%**（1221 vs 842 ms）。这比 §11 那种
「duty=0.3 需 P=32→3.3° / P=5→21.1°」的静态换算更能说明部署手感。
> ⚠️ §20.2 那个 45% 是在**慢斜坡开着**的条件下测的（脚本默认写 reg41=10）。
> 干净口径见 §20.4：无斜坡时 P=5 比 P=32 慢 **3.0 倍**（595 vs 201 ms）。
> 另外 §20.2 的 p95 用的是**旧峰速口径**（见 §20.5），只可看量级，不可与 §20.3/20.4 混用。

### 20.3 🔑 `reg46` = 速度上限，`reg41` = 加速度斜坡（一次扫清，含两个被自己推翻的中间结论）

这一节的过程值得保留：24 小时内对同一对寄存器给出了**三个不同解释**，前两个都被数据推翻。
最终模型只有下面四条，全部有 3 次重复的实测支撑（P=5/D=0、USB 4.6 V、200 步 = 17.6°）。

**① `reg46` 是速度上限，单位 ≈ 0.732 rpm/LSB ≈ 50 步/s 每 LSB。**

固定 `reg41=0`（关掉斜坡，隔离上限；脚本 `ab_reg4641.sh` 会拒绝 `reg41≠0` 的组合），
只扫 reg46，`out/ab_reg_canon2/`，各 3 次：

| reg46 | 整定 ms | 峰速 p95 步/s | 上限 50×V 步/s | 判定 |
|---|---|---|---|---|
| 0 | 588 | 828 | 0（无上限） | 基线 |
| 3 | 1548 | 211 | 150 | 上限生效（+41% 过冲） |
| 5 | 1102 | 311 | 250 | 上限生效（+24%） |
| 10 | 781 | 475 | 500 | 上限生效（−5%） |
| 20 | 669 | 656 | 1000 | 已不受限 |
| 46 | 608 | 758 | 2300 | 不受限 |
| 100 | 595 | 790 | 5000 | 不受限 |
| 300 | 608 | 813 | 15000 | 不受限 |
| 4095 | 628 | 801 | 204750 | 不受限 |

峰值在 **reg46 ≤ 10 时逐档被卡住**、且从 20 起全部停在 **~800 步/s**（P=5 在此电压下的
物理可达峰速，≈70 °/s）⇒ 上限语义成立，`reg46=0` = 无上限。
<span style="color:gray">（注：本表用修好的峰速口径，见 §20.5；旧口径会把 ≥46 各档压到 530 左右。）</span>

**② `reg41` 是加速度斜坡：数值越大斜坡越紧（整定越快）；`reg41=0` = 无斜坡。**

固定 `reg46=300`（上限 15000 步/s，不约束），只扫 reg41：

| reg41 | 整定 ms | 峰速 p95 步/s |
|---|---|---|
| 0 | 648 | 833 |
| 5 | **1468** | 300 |
| 10 | 1148 | 362 |
| 50 | 822 | 534 |
| 100 | 742 | 667 |
| 254 | 681 | 759 |

最钝的是 `reg41=5`（1.47 s），往上单调变快，`0` 等于不设斜坡（648 ms 最快）。
⇒ **想让舵机快，正确做法是不写 reg41（或写 0），不是写一个大数。**

**③ 「与」关系只在一个位置成立：`reg46=0` 时 `reg41` 被完全忽略。**

| reg46 | reg41 | 整定 ms | 峰速 p95 步/s |
|---|---|---|---|
| 0 | 0 | 595 | 831 |
| 0 | 10 | **595** | **839** |
| 300 | 0 | 588 | 866 |
| **300** | **10** | **1108** | **350** |

`0/10` 与 `0/0` 完全一样 ⇒ 上限为 0 时斜坡不启用。反过来**上限单独生效**：
`reg41=0, reg46=5` → 整定 1142 ms、峰速 286（≈250+15% 过冲），上限照样卡住。
⇒ **不是「两个都必须非零才限速」，而是「斜坡必须挂在一个非零上限上」。**

**④ 被推翻的两个中间结论（写下来防止再犯）**

- ❌ 第一版：「`reg46` 从 150 到 4095 无差别 ⇒ 它不是速度上限」。**错在选错了观察区间**——
  这些值对应的上限（7500–200000 步/s）远高于斜坡在 17.6° 内能达到的 ~640 步/s，
  上限不可见 ≠ 不存在。**扫参数必须扫到它开始响应的区间**，否则"无差别"只是分辨率不足。
- ❌ 第二版：「两者是『与』关系，单独写任何一个都不生效」。**只对了一半**——
  上限单独生效，被 gate 的是斜坡。这条差点写进脚本护栏（已改成按 ①③ 设计）。

**对部署的直接影响（更正 §15/§18 遗留说法）**

- 「部署必须写 reg46，默认 300 距需求差 7.6 倍」**是错的**：`reg46=300` 对应上限
  **15000 步/s**，而步态工作点只需 2287 步/s（201 °/s）。**300 毫不约束。**
  按 50 步/s/LSB 反算，需求下限是 **reg46 ≥ 46**；出厂 0（无上限）也满足。
- 那条「差 7.6 倍」的原始观感来自 `_arm()` **同时写了 `reg41=10`**——真正让人变慢的是
  这个钝斜坡（整定从 588 → 1089 ms，2×），不是 reg46。
- ⇒ **部署侧不要主动写 `reg41=10`**。若只写 `reg46`，务必回读确认 `reg41` 是 0，
  否则会静默套上一个 2 倍的慢响应。这与 §11 陆吾 `max_velocity:100` 是同一失败模式：
  **限速配置看起来设了，实际生效的是另一个参数。**

### 20.4 「软腿」的真实口径：P=5 在无斜坡下慢 2.8 倍，但电流余量是 4 倍

在**干净寄存器状态**与**统一峰速口径**下重测（`reg46/reg41` 分别为 0/0 与 300/10，各 3 次）：

| kp | reg46/reg41 | 整定 ms | 峰速 p95 步/s | `load_max` |
|---|---|---|---|---|
| 32（出厂） | 0 / 0（无限制） | **201** | 2035（179 °/s） | **1000（满量程）** |
| 5（部署） | 0 / 0 | **595** | 831（73 °/s） | 260（26%） |
| 32 | 300 / 10 | 821 | 436 | 113 |
| 5 | 300 / 10 | 1108 | 350 | 87 |

两条都重要：

- **P=32 在无速度上限时 `load_max` 打到 1000（满量程饱和）**，即 17.6° 阶跃就吃满
  驱动占空比。这解释了为什么它整定只要 201 ms——**它是拿电流换的速度**。
  P=5 的 26% 说明「软腿」的物理含义是**用 3 倍的时间换 4 倍的电流余量**，
  不是「控制律更差」。
- 之前那个「P=5 比 P=32 慢 45%」（1221 vs 842）是**双方都挂着慢斜坡**时的比值，
  它同时低估了差距（真实 3×）和高估了安全（真实余量 4×，因为 P=32 已经饱和）。
  ⇒ **凡是"某参数让响应变慢 X%"的结论，必须写明当时的 reg41/reg46。** 否则不可复现。

待办（需 ≥6 V 才有意义）：这条 `load_max=1000` 是在 4.6 V 下测的，**7.4 V 下饱和点会右移**
（同样力矩所需占空比下降），届时 P=32 可能不再饱和。**别把 4.6 V 的饱和结论外推。**

### 20.5 ⛔ 峰速 p95 依赖保持时长（同一颗舵机，同一个参数，661 → 525）

修 §20.3 的过程中撞到的仪器错误，**性质与 memory 里那条「`error_vel_xy` 单位依赖窗口长度」完全同类**。

现象：同一颗 ID10、同 P=5/D=0、同 200 步阶跃，把 `--hold` 从 2 s 改成 3 s，
峰速 p95 从 **661 掉到 525 步/s**（−21%），而物理响应没有任何变化。

原因：`step_metrics()` 把 **整个相位窗口**（含静止保持段）的位置差分收集起来算 p95。
保持段样本的速度接近 0，**稀释了分位点** ⇒ 静止越久，p95 越低。

修法：窗口截到 **settle 点**（settle 由 tol 决定、与 hold 无关）。
新增字段：`v_win_s` / `v_win_n`（窗口时长与样本数，便于复核）、
`v_p95_full_steps`（旧口径，**只用于和修好之前的 JSON 对照，别再拿它下结论**）。

**负对照（写进 `selftest`，缺了它就等于没修）**：

| 口径 | hold 3 s | hold 6 s | 判定 |
|---|---|---|---|
| 新（截到 settle） | 2167.5 | **2167.5** | 必须完全相同 ✅ |
| 旧（整段） | 695.1 | **360.8** | 必须明显下降（−48%）✅ |

⇒ **判据形式是「同一物理量在两种窗口下相等」，不是「数字看起来合理」。**

**影响面**：修好之前用 p95 得出的绝对值全部偏低，尤其 `hold` 越长偏得越多。
§20.2 与 `out/ab_reg4641_v0_unlim/`、`out/ab_sxa/`、`out/ab_torque/` 里的 p95 都是旧口径；
**settle_ms / load_max / over_pct 不受影响**（那几个量本来就不看窗口长度）。
§20.3/§20.4 已全部改为新口径重测（`out/ab_reg_canon2/`、`out/ab_metric_v2/`）。

## 21. ✅ P8 重训判决：vx +83%，但**只在 kp_fw=8 上成立**（2026-11-03 11:56）

`p8head_030_4096x3000`（4096 env × 3000 iter，08:33→11:50，heading 配方与 P5 线完全相同，
只改 plant 的 reg 50 = 8）。判据在训练前写死在 `microduck-software/NEXT-p8-train.md §3.2`。

### 21.1 主表（同仪器、同脚本版本、n=8 起点，`out/xplant_*`）

| 格子 | n | 摔倒 | `vx_mean_steady` | sem | `abs(heading_err)` | sem |
|---|---|---|---|---|---|---|
| **P5 训练 × p3(kp5) 基线** | 8 | 0 | **0.1129** | 0.0008 | **3.73°** | 0.59 |
| **P8 训练 × p8(kp8)** | 8 | **0** | **0.2069** | 0.0011 | 6.91° | 1.12 |
| P8 训练 × p3(kp5)（OOD） | 8 | **7** | 0.1900 | 0.0193 | 56.65° | 8.32 |
| P8 策略 × 80 ms 延迟 | 8 | **8** | — | — | — | — |
| P8 策略 + 目标 +90° | 4 | 0 | 0.2068 | 0.0024 | 7.46° | 1.41 |
| P8 策略 + 目标 −90° | 4 | 0 | 0.2032 | 0.0017 | 7.55° | 0.94 |

工具：`tools/hd1910/judge_summary.py`（可重跑；同目录含多档时要写 `目录:kp`）。

### 21.2 逐条对照预注册判据

| 判据 | 阈值 | 实测 | 判定 |
|---|---|---|---|
| 主判据：P8×P8 的 vx 显著高于 P5×P3 | Welch \|t\|>3 | **+83.3%，t = 71.0** | ✅ **PASS** |
| 副判据：`abs(heading_err)` 不劣于 3.73°（绝对值目标 ≤20°） | ≤3.73° | 6.91°（t=2.5，确实更差） | ❌ 相对口径 FAIL / ✅ 绝对口径 PASS |
| 80 ms 延迟不比 P5 线更差 | P5 定稿 80 ms 必摔 | 8/8 摔 | ✅ 不更差（同为 80 ms 崩） |
| 换目标负对照（不是固定吸引子） | 末态航向跟目标走 | ±90° 目标下 err 7.46 / 7.55° | ✅ **PASS** |

**基线可复现性**：本次重测 P5×P3 得 0.1129 / 3.73°，与训练前登记的 0.1129 / 3.7°
**逐位相同**，说明这段时间的脚本改动（moves_forward 闸门、峰速口径）没有动到这两个量
⇒ 跨版本数字本次可以并排比较，不是巧合。

### 21.3 🔴 最重要的一条：这个 +83% 不是免费的

**P8 策略在 kp=5 上 7/8 摔倒、航向误差 57°。** 也就是说：

> **+83% 的收益完全绑定在「真机 reg 50 = 8」这个前提上。**

而 kp_fw=8 既不是出厂值（32），也没有社区部署先例（社区全用 5）。
它落在 `kp=5（软腿，整定 595 ms）`与 `kp=32（整定 201 ms 但 duty 打到满量程）`之间，
是**台架上找出来的甜点，不是任何一方的既有配置**。

⇒ 三条必须一起说，不能只说 +83%：

1. 要拿这个收益，**必须改真机 15 颗舵机的 reg 50 = 8**（并回读确认，见 §11 的
   「json 同名键覆盖」与「读文本看不出来」两条）。
2. 一旦某台机器是 5 或 32，这套策略**直接不可用**（7/8 摔），不存在"降级使用"。
3. kp=8 在 4.6 V 台架上的 duty 余量尚未测（只测了 5 与 32）⇒ **上真机前必须补这一档**，
   否则可能重演 P=32「拿电流换速度」的饱和。

### 21.4 延迟这一维仍未闭合（与 §19.4 不冲突）

80 ms 两代策略都必摔，这**不是回归**：§19.4 已把部署域缺口界定在 11–18 ms，
80 ms 是刻意的越界测试，用来确认「延迟一升就崩」这个性质两代都成立。
真正的部署风险仍在「真机端到端延迟是否 ≤30 ms」——它只能实测（§19.6）。
