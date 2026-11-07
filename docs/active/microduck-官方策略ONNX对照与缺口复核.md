# 官方策略 ONNX 对照与资料缺口复核（2026-11-07）

> 收口两条元任务：① 挖掘参考过的开源项目还有哪些可用；② 复核前面是否有缺资料对照的环节。
> 落实 5 个缺口：**缺口5**（GroundPick 未与官方 `alpha_ground_pick.onnx` 对照）、**缺口1**（MicroDock 未挖 v2 / scoot_dock.onnx）、**缺口2**（轮滑未引 roller 生态）、**缺口3**（Backlash 未引官方 walk-flat 齿隙微调）、**缺口4**（IMU 未引标定流程——已修正为 LSM6DSV16X 正确源，原 build-tutorial 是 BNO08x 错配）。
> 所有 ONNX 来自 `pollen-robotics/microduck-policies`（HuggingFace，apache-2.0，11 个 ONNX + `manifest.json`）。

## 0. 官方策略仓库与 ONNX 规格【核实】

- 仓库：`pollen-robotics/microduck-policies`（**HuggingFace，不是 GitHub**；HF 镜像 `hf-mirror.com` 可拉，直连 `huggingface.co` 不可达）。
- `manifest.json` 关键字段：`obs_len=61`、`action_len=14`、`control_hz=50`、`robot: {hw_rev:1, servos:xl330}`。
- 11 个 ONNX：`alpha_walking / velstand / alpha_stand / alpha_sitstand / alpha_ground_pick / roller / roller_crouch / roulade / ball_kick_left / ball_kick_right`。
- **ONNX 图结构统一**：`Sub(均值) + Div(标准差) + 4×Gemm + 3×Elu`——即**内嵌观测归一化**，接收**原始（未归一化）obs**，输出 14 个动作。
- 关键推论：本 fork 的 `RslRlVecEnvWrapper` **不在 wrapper 端归一化**（`obs_normalizer is None`），env 返回的就是原始 obs，正好直接喂给内嵌归一化的官方 ONNX——无需在脚本里反归一化。

## 1. 缺口5：GroundPick 与官方 `alpha_ground_pick.onnx` 对照【核实】

- 官方条目：`alpha_ground_pick.onnx`，`kind=episodic`、`duration_s=2.8`、`command: {encoding:phase, slots:twist.vx,twist.vy, period_s:4.0, end_phase:0.7}`（与本项目评测用的 twist 相位命令同构）。manifest **无 training 溯源块**。
- 对照方法：用 `microduck-software/tools/hd1910/eval_ground_pick.py --onnx` 把官方 ONNX 接进**本项目 HD-1910 GroundPick env**，跑同一套相位无关指标（成功率 / 摔倒 / 下降 / 直立 / 回姿）。
- **重要前提**：官方 ONNX 是 **B代（MicroDuck）训练**，本项目 env 是 **HD-1910 复刻线**——关节序与动力学不同，所以这是**跨机型压力测试**，不是官方策略的原生分数（原生分数需 B代 env，本 fork 未保留可加载的 B代 GroundPick env）。
- 结果（64 envs × 3 seeds）：

  | 策略 | 成功率 | 摔倒率 | 下降 | 直立 | 回姿 | 站立嘴高 |
  |---|---|---|---|---|---|---|
  | 我们 HD-1910 重训 `model_3999.pt` | **96.9%** (iqr 96.1–98.4) | 3.1% | 98.4% | 100% | 100% | 0.217 m |
  | 官方 `alpha_ground_pick.onnx`（在 HD-1910 上） | **23.4%** (iqr 23.4–27.3) | 76.6% | 81.2% | 100% | 100% | 0.220 m |

- 解读：官方 B代策略落到 HD-1910 上，**运动模式可复现（下降/直立/回姿仍 ~100%），但站不稳（76.6% 摔倒）**。对照我们 96.9% → 证明**官方策略不能直接移植 HD-1910，plant 专用重训既必要又成功**。这与"关节 ID 两套体系不能混用"的铁律一致。
- 复现：
  ```bash
  .venv-mjlab/Scripts/python.exe microduck-software/tools/hd1910/eval_ground_pick.py \
      --onnx out/official_policies/alpha_ground_pick.onnx --envs 64 --seeds 3 --device cuda:0 \
      --json out/groundpick_eval_alpha_gp_onnx_hd1910.json
  ```

## 2. 缺口1：MicroDock v2（坐姿坞）+ scoot 策略【核实，已写入预研文档 §6】

- 写入 `docs/hardware/microduck-MicroDock真机可行性预研-2026-11-06.md` 的 **§6** 与 **R3 补正**。
- v2 = 坐姿坞：鸭子**坐下**，用**学到的 scoot 策略**坐滑入坞、充电时坐着休息、充满后坐滑出再走开。比 v1 只多一个件 `board`（把浮动罩压低 57 mm 到坐姿高度 `z0=62` mm）。
- **机器人侧 docking 控制器 = 学到的策略网络**（直接填补原文档 R3"机器人侧实现缺失"）：
  `playground/hardware/microdock-v2/policy/scoot_dock.onnx`（入坞）、`scoot_undock.onnx`（出坞）、实验 `scoot_dock_undock.onnx`（一个网络兼顾进出）。
  同策略族：61-D 观测 → 14 动作（BAM XL330，50 Hz），训练任务 `Mjlab-ButtWalk-Flat-MicroDuck`（microduck_rl develop `bae39f59`）。
- 仿真验证：入坞 30/30（seeds 41/42/43 ×10）、0 次罩碰电源键；出坞 4 N 磁吸 30/30 脱困（中位 1.06 s）；**延迟敏感**（无训练延迟仅 1/10 脱困）。
- HD-1910 移植警示：scoot 权重是 **B代训练**，直接装 HD-1910 不可靠（同 §1 的 plant 差异逻辑），须在 HD-1910 上重训；坞体打印件机器人无关、可复现。

## 3. 缺口2：roller 生态与官方 `roller.onnx`【核实】

- 官方条目：`roller.onnx`（`kind=perpetual, mode=roller, action_scale=0.8`）、`roller_crouch.onnx`（`kind=episodic, duration_s=3.5, mode=roller, action_scale=0.8`）。
- 本项目已注册 4 个 Roller 任务：`Mjlab-Velocity-Flat-MicroDuck-Rollers`、`Mjlab-RollerCrouch-Flat-MicroDuck`、`Mjlab-RollerSlope-Flat-MicroDuck`、`Mjlab-RollerStandUp-Flat-MicroDuck`（均在本 fork，HD-1910 轮滑变体；critic obs 含 `wheel_vel(4)`）。
- 对照方法：`microduck-software/tools/hd1910/eval_roller_onnx.py` 把官方 `roller.onnx`（`--action-scale 0.8`）接进 **HD-1910 Rollers env**，测摔倒率 + 存活 + 步奖励。
- 结果（32 envs × 2 seeds × 500 步）：
  - **官方 `roller.onnx` 在 HD-1910 上：摔倒 17.2%，其余存活满窗 10 s，平均步奖励 0.102。**
  - 解读：轮滑任务跨机型迁移**远好于** GroundPick（17% vs 77% 摔倒）——"保持直立并滑行"对 plant 差异不敏感，**官方 roller ONNX 可作 HD-1910 轮滑训练的参考起点**；但 17% 摔倒说明仍有动力学差异（质量/轮摩擦/齿隙），真机上需 HD-1910 重训才稳。
- `roller_crouch.onnx` 补充对照（任务 `Mjlab-RollerCrouch-Flat-MicroDuck`，同 `--action-scale 0.8`）：
  - **官方 `roller_crouch.onnx` 在 HD-1910 上：摔倒 50.0%，平均步奖励 0.134。**
  - 注：脚本的 `mean_survival` 在 episodic 任务上会重复计数（倒地后 env 自动重置、后续步继续累加非摔倒步），对 crouch 不可信，**以 `fall_rate`（累计摔倒占比）为准**。crouch 多为末段摔倒（存活步数接近满窗但一半 env 倒过），与"蹲滑更难、平衡裕度更小"一致。
  - 解读：蹲滑（crouch）跨机型迁移**明显差于** plain roller（50% vs 17%）——重心压低的平衡裕度被 plant 差异吃掉更多；若要做 HD-1910 蹲滑，应直接重训而非移植官方 crouch。
- 复现：
  ```bash
  .venv-mjlab/Scripts/python.exe microduck-software/tools/hd1910/eval_roller_onnx.py \
      --task Mjlab-Velocity-Flat-MicroDuck-Rollers \
      --onnx out/official_policies/roller.onnx --action-scale 0.8 \
      --envs 32 --seeds 2 --device cuda:0 --max-steps 500 \
      --json out/roller_eval_onnx_hd1910.json
  # crouch 对照
  .venv-mjlab/Scripts/python.exe microduck-software/tools/hd1910/eval_roller_onnx.py \
      --task Mjlab-RollerCrouch-Flat-MicroDuck \
      --onnx out/official_policies/roller_crouch.onnx --action-scale 0.8 \
      --envs 32 --seeds 2 --device cuda:0 --max-steps 500 \
      --json out/roller_crouch_eval_onnx_hd1910.json
  ```

## 4. 方法学备注

- 三个对照的"官方 ONNX 在 HD-1910 env"都是**跨机型压力测试**（官方 B代训练 vs 本 fork HD-1910 env），**不是官方策略的原生分数**；原生分数需 B代 env，本 fork 未保留可加载的 B代训练环境。
- 这反而强化了项目主线结论：**HD-1910 复刻线必须做 plant 专用重训**，GroundPick 已用 96.9% 闭环证明，轮滑预期同样适用。
- 可复现：ONNX 由 `hf-mirror.com/pollen-robotics/microduck-policies/resolve/main/<f>` 重新拉取（已落 `out/official_policies/`，但 `*.onnx` 被 gitignore，属可复现产物）。

## 5. 缺口3 / 缺口4 收口（2026-11-07 补）

原"复核缺资料环节"列了 5 个缺口，前三个（5/1/2）已在 §1–§3 收口。剩下两个：

- **缺口3（Backlash 未引官方 walk-flat 齿隙微调）— 已收口**：在 `docs/active/microduck-开源对照地图.md` §3 补了 `witcheer/microduck-walk-flat` 的权威齿隙微调配方（v1 平地行走 + `Mjlab-Velocity-Flat-Backlash-MicroDuck` 每舵机 ±1° 齿隙续训 3000 iter；齿隙仿真 20s 不倒率 2/5→4/5，真机未测）。这正是我们 HD-1910 Backlash 系列任务借鉴的范式。
- **缺口4（IMU 未引 build-tutorial 标定流程）— 修正，不是盲引**：核实发现 build-tutorial（AI-FanGe 中文复刻）的 `bno08x_calibrate_ui.py` 是 **BNO08x** 标定，而我们 HD-1910 线是 **LSM6DSV16X**（§0.5 三方同芯片）——**芯片错配，不可直接套用**。已在 `docs/hardware/microduck-IMU三方对照-666wsp-kissqy-DuckBuddy.md` §0.1 改写为正确权威源：`community-kit` 的 `lsm6dsv16x_driver_spec.md` + DuckBuddy `imu-feetech`（同芯片同传感器），外加 HD-1910 整机标定社区工具（janauto/lxm/jackwuwei）。这条正好印证"查全比查到更重要"——只看到"有标定脚本"就引，会引错芯片。

⇒ 5 个缺口至此全部收口/修正，元任务（挖掘开源资产 + 复核缺资料环节）闭环。

## 6. 下游动作：基于 roller.onnx 启动 HD-1910 轮滑重训（2026-11-07 已完成，**结果为负面**）

原"两个任务"中「补回 B代 env 跑原生分」经核实**前提不成立**（官方 B代 RL 源 `microduck_rl-develop` 与我们 fork 是同一 `mjlab_microduck` 包、`robot_walk.xml` 惯量逐字节相同、velocity/roller env 配置一字不差——不存在独立 B代 plant 可补；之前测的 23.4%/17.2% 已是共享 plant 上的苹果对苹果分）。故只做**真有价值的第二条：HD-1910 原生轮滑重训**。

- 训练 env：`Mjlab-Velocity-Flat-MicroDuck-Rollers`（与 roller.onnx 基线**同 env**），plant 固定 `hd1910_kp8`（kp_fw=8，部署 plant，即基线评测生效 plant）。
- "基于 roller.onnx"取 **benchmark** 含义而非权重 warm-start：roller.onnx 内嵌归一化 + `action_scale=0.8`，与 rsl_rl actor（外部归一化）跨归一化/动作缩放两道边界，warm-start 有静默 bug 风险，避开。
- 流水线对齐 GroundPick：smoke 64×5 ✅（exit 0 / nan 0 / 7s）→ explore 1024×1000 🔄（reward −14.5→−0.18，fell 55.8%→46.6%，nan 0）→ formal 4096×4000 ⏳ → eval `.pt` 对比。
- 评估脚本 `microduck-software/tools/hd1910/eval_roller_onnx.py` 已支持 `--checkpoint`（rsl_rl `.pt`，原生 HD-1910 策略）与 `--onnx`（官方 B代）互斥，统一回放 + `fall_rate`/`mean_survival` 指标。
  - ⚠️ **已抓修一个会阻断最终对比的 bug**：`--checkpoint` 模式原用 `policy_call` 包装推理策略，闭包自引用导致 `RecursionError`；已改为直接用 `runner.get_inference_policy()`（与 `eval_ground_pick.py` 一致）。用 explore `model_100.pt` 冒烟已验证端到端能出 `fall_rate` 字段。
- **最终对比协议（必须严格同参，保证苹果对苹果）**：
  - 同 plant `hd1910_kp8`、同 env `Mjlab-Velocity-Flat-MicroDuck-Rollers`、同窗口 `--max-steps 500`（10s）、同规模 `--envs 32 --seeds 2`。
  - ONNX 基线：`--onnx roller.onnx --action-scale 0.8`（忠实还原 manifest 的 runtime 0.8 缩放）。
  - 我方 `.pt`：原生输出，无外部缩放（rsl_rl actor 已在其动作空间内学习）。
  - 判据：`fall_rate`（ONNX 基线 17.2%）须显著下降才证明 HD-1910 重训必要且成功；`mean_survival` 在 perpetual 任务下为「首次倒地前平均存活步」，作为辅证。
  - **追加"真在滑吗"指标**（避免"2% 摔但轮子不动"的伪胜利）：eval 从 `extras['log']` 累计 `Episode_Reward/wheel_speed`(权重10) 与 `Episode_Reward/glide`(权重4) 的步均奖励，作为 rolling signal。最终对比时 ONNX 基线与新 `.pt` **同设置同跑**，让摔率 + 滑行信号都苹果对苹果——已验证 `eval_roller_onnx.py` 能稳定输出这两字段。

### 6.1 HD-1910 轮滑重训 formal 评测结果（2026-11-07 17:51，⚠️ 重大负面）

- **训练配方**：`train_roller.sh hd1910_roller_formal_1107_formal`，`ENVS=4096 ITERS=4000 SAVE=100 MUJOCO_ITERS=10 MUJOCO_LS_ITERS=10`（13:47 启动，17:40 exit 0 正常跑满 4000 迭代，无崩溃；末档 `model_3999.pt`，并自动导出 `..._formal.onnx` 单文件）。
- **评测命令**（严格同 §6 协议）：`eval_roller_onnx.py --task Mjlab-Velocity-Flat-MicroDuck-Rollers --checkpoint <run>/model_3999.pt --envs 32 --seeds 2 --device cpu --max-steps 500`，CPU 跑 5m16s，EXIT=0。
- **结果（苹果对苹果，同脚本同 plant `hd1910_kp8` 同窗口）**：

  | 指标 | 我方重训 model_3999.pt | 官方 roller.onnx 基线 | 结论 |
  |---|---|---|---|
  | fall_rate（摔倒率） | **89.1%** | 17.2% | ❌ 差 ~5× |
  | mean survival | 9.9s (497 steps) | 满窗 10s | ❌ |
  | mean step reward | 0.118 | 0.102 | ⚠️ 略高但不可信（见下） |
  | wheel_speed 滚动信号 | 0.151 | — | 轮子转 |
  | glide 滚动信号 | 0.000 | — | ❌ 没在滑 |

- **原始数据**：`microduck-software/out/measurements/eval_roller_formal.json` + `.log`。
- **判读（必须诚实）**：
  1. **重训彻底失败**——摔倒率 89.1% 是官方的 ~5 倍，几乎不走路。这**推翻了"HD-1910 轮滑必须 plant 专用重训且能超过官方"的假设前提**：官方 roller.onnx 在 HD-1910 上本就只有 17.2% 摔，而我们花 4 小时重训出来的反而更差。
  2. **非偶然**：之前 `model_5999`（velocity 行走，异 plant）terminated 87.5%；本次 roller（同 plant 同 task）fall 89.1%——两次独立训练都 ~85–89%，是**系统性信号**，不是单次抖动或测量 artifact（同脚本、同指标、同 env）。
  3. **step reward 0.118 > 基线 0.102 但 fall 89%**：典型"奖励拿到了但站不稳"——wheel_speed 信号 0.151（轮子转）而 glide 0.000（没真正滑行），说明策略在**动但不平衡**，奖励景观没把"不倒"压够。
  4. **根因诊断（2026-11-07 17:51 读训练曲线，已查实，**非猜**）**：**主因是「欠训」，不是「配方坏」**。证据（tensorboard `events.out.tfevents...26808.0`）：
     - `Train/mean_reward` 从 -15.0 爬到 +1.14，且 **@3000=-0.22 → @3999=+1.14**——末 1000 步仍在快速上升、**远未 plateau**；末 12 步在 0.3–1.4 震荡（学习期高方差）。
     - `Train/mean_episode_length` 24→129 步、末段仍在涨（无收敛平台）；`Policy/mean_std` 0.998→0.309、`Loss/value` 30→0.155 正常收敛、`nan_state` 全程 0（训练干净）。
     - **eval 89% 摔 vs 训练 fell_over 40.6% 主要是窗口长度假象**：训练 episode 有上限（`Episode_Termination/time_out` 占 16.7%，上限约 200 步），policy 平均只站 ~2.6s；eval 窗口 500 步(10s) 站不住自然几乎必摔一次 → 89%。官方能站满 10s（17.2%）才是真差距。
     - **`Episode_Reward/glide` 全程 ≈0.000**（@0:0.0001→@3999:0.0002）：真·滑行(roll)行为**从未涌现**，policy 只学到"轮子转(wheel_speed 0.16)+勉强直立(upright 0.148)"，没学到"滑"。
     - **结论**：曲线在 3999 还在猛涨 → **加迭代大概率能出可站 10s 的策略**；`glide` 不涌现是次要风险（可能需 reward 整形/更长训练）。`MUJOCO_ITERS=10` 降 fidelity 非主因（曲线正常学）。➜ 定位并修正前**不应再烧 GPU 重训**改为：**应「加迭代重训」而非「放弃」**——但属数小时 GPU 投入，需用户拍板（见 §6.2）。
  - **修正上一句结论**：原写"定位并修正训练配方前不应再烧 GPU 重训"——按曲线证据应改为"**加迭代重训值得一试**（曲线未收敛），但需先确认官方训练量基线 + 是否要补 glide 整形；这是数小时 GPU 决策，交用户定"。

- **结论性影响**：§6 标题"进行中"→ **已完成，结果为负面但根因明确**。本路径（fork 内从零重训 roller）**当前**不优于直接拿官方 roller.onnx 部署（17.2% 摔）；但曲线证据（§6.1-4）表明是**欠训**而非配方坏，**加迭代重训值得一试**，决策见 §6.2。

### 6.2 下一步决策（待用户，2026-11-07）
基于 §6.1 证据，fork 内从零重训 roller 目前不优于官方 roller.onnx（17.2% 摔），但根因是欠训（曲线未收敛），不是配方坏。三条路：
- **(A) 加迭代重训（推荐先试）**：把 `ITERS` 提到 10000–20000（4000 用了 ~4h，量线性涨；曲线未收敛，大概率能站满 10s），沿用现有 `train_roller.sh`（`MUJOCO_ITERS=10` 已避险 TDR）。可顺带在 reward 加 glide 权重催化"滑"行为。
- **(B) 先不重训，直接部署官方 roller.onnx**：省 GPU，立刻有 17.2% 摔的可用轮滑策略；代价是放弃 HD-1910 plant 专用优化（但实测官方在 HD-1910 上本就只有 17.2% 摔，够用）。
- **(C) 先查官方训练量基线再定**：去 `microduck_rl` 官方仓确认 roller 训了多少迭代/超参，对齐后再定迭代数——最稳但多一步查资料。

> 注：`MUJOCO_ITERS=10` 已确认非主因（曲线正常学），无需回退 100（那会再触发 TDR 僵尸）。

## 7. 行走策略对照（旗舰主线）+ 部署链审计

### 7.1 行走对照（m5 / kp5 / kp8 三条线均已同 plant 实测，工具缺口已闭合）
- **官方行走 ONNX 全集已下 + 动态 batch 兼容**：`pollen-robotics/microduck-policies` 全部 6 个策略（`alpha_walking`/`velstand`/`alpha_stand`/`alpha_ground_pick`/`roller`/`roller_crouch`）已落 `out/official_policies/`。官方导出把 obs 输入冻结成 `[1,61]` batch，**CPU EP 拒绝 ≠1、CUDA EP 静默广播**——已改为在加载时**内存动态化首维**（MLP 对 batch 维天然安全），脚本自给自足，重下 HF 也无需手工 patch（提交 `c2e0727`）。
- **`eval_velocity_in_sim.py` 加 ONNX 模式**（提交 `c2e0727`）：与我们的 `.pt` 走**同一套严苛物理量闸门**（足 clearance/滞空/速度跟踪误差/摔倒/横向漂移），支持 `--action-scale`（roller 系 0.8）。
- 🔴 **三条行走训练线（关键澄清，2026-11-07 纠正此前误判）**：velocity 行走按**训练 plant**分三条，绝不可混——
  - **m5 线** `microduck_velocity_hd1910`（主 run 2026-10-27 resume，model_5999，**m5.json / kp_fw=32**，`get_walk_spec`）——**最多训练（5999 步）**，但 plant 是 m5，**不是部署目标**。
  - **kp5 线** `microduck_velocity_hd1910_kp5`（model_3999，official_m6_stslaw / kp_fw=5）。
  - **kp8 线** `p8head`/`p8ctl`（model_2999，official_m6_stslaw / kp_fw=8）——**这正是部署目标 plant**，但只训到 2999 步。
  - ⚠️ 此前把 `model_5999` 当"kp8 线"是**错误假设**：其 `params/env.yaml` 写死 `json_path=.../m5.json` + `kp_fw=32.0` = `hd1910_openmicroduck_m5`，与 kp8（official_m6_stslaw / kp_fw=8）是**不同 plant**。
- **官方行走基线（CPU 小样本，噪声大，待 GPU 大样本确认）**：`terminated_frac≈0.875`、`vx_mean≈0.152 m/s`、gates 中 `no_fall`/`translates_forward`/`stays_upright` 均 FAIL——**官方行走 ONNX 在 HD-1910 异 plant 上几乎走不起来**，退化比 groundpick(23.4%成)/roller(17.2%摔) 更严重（走路对质量/重心最敏感），强力支撑"HD-1910 行走必须 plant 专用重训"。
- **同 plant 实测（2026-11-07，已纠正全部 plant 误判）**：
  - `model_5999.pt`（**m5 线**，5999 步）在**其真实训练 plant**（`--plant hd1910` = m5）上：`terminated 0.00%`、`vx_mean +0.32 m/s`（cmd 0.4 的 **80%**）、`dx_body +0.91 m`、`upright 0.998`；`no_fall`/`stays_upright`/`translates_forward` 全 PASS → **m5 行走 excellently**。
  - `p8head/model_2999.pt`（**kp8 线**，2999 步）在**kp8**（`--plant hd1910_kp8`）上：`terminated 0.00%`、`vx_mean +0.167`（cmd 0.4 的 **42%**）、`dx_body +1.18 m`、`upright 0.997`；`no_fall`/`stays_upright`/`translates_forward` 全 PASS → **kp8 也能走，只是训得少所以慢**。
  - 🔴 **此前"kp8 行走 82% 摔 / 走不起来"是误判**：那是把 **m5 训的策略拿到 kp8 上测 = 跨 plant 评测**的结果（`model_5999` 在 kp8 上必然失效），对判断 kp8 毫无意义。真相：**m5 与 kp8 行走策略都会走、都不摔**，kp8 仅因只训 2999 步而速度偏低。训练侧也佐证——kp8 线 `fell_over` 尾段 ~6%、回合 ~990 步，是健康行走策略。
  - 复现：
    ```bash
    # m5 线最佳候选，回其真实 plant（m5）测
    .venv-mjlab/Scripts/python.exe microduck-software/tools/eval_velocity_in_sim.py \
        --task Mjlab-Velocity-Flat-MicroDuck \
        --checkpoint logs/rsl_rl/microduck_velocity_hd1910/2026-10-27_08-37-16_hd1910_resume_4096_to6000_1027/model_5999.pt \
        --num-envs 64 --seconds 8 --device cuda:0 --cmd-vx 0.4 --plant hd1910 --seed 0
    # kp8 线（部署目标 plant），同 plant 测
    .venv-mjlab/Scripts/python.exe microduck-software/tools/eval_velocity_in_sim.py \
        --task Mjlab-Velocity-Flat-MicroDuck \
        --checkpoint logs/rsl_rl/microduck_velocity_hd1910/2026-11-03_08-33-18_p8head_030_4096x3000/model_2999.pt \
        --num-envs 64 --seconds 8 --device cuda:0 --cmd-vx 0.4 --plant hd1910_kp8 --seed 0
    ```
- **结论与部署 gap**：
  - 行走**能力本身不是缺口**——m5/kp8 同 plant 实测均 **0% 摔**。
  - **部署 gap 明确**：部署目标是 kp8，但 kp8 线只训到 2999 步（vx 0.167，偏慢）。要把 kp8 走到 m5 的速度（vx 0.32），需对 kp8 线（p8head/p8ctl）**继续加迭代训练**（2999 → 更多），而非从 m5 线迁或重训。m5 线虽走得最好，但 plant 非部署目标，不能直接上机器人。
  - 🔴 **选点教训（仍成立）**：「按迭代数选最高 model_5999」是选到了 **m5 线**而非 kp8 线——印证评估前必须先用 env.yaml **核实训练 plant**，不能凭目录名 `microduck_velocity_hd1910` 推断。
- ✅ **工具缺口已闭合 + plant_id 标签 bug 根治（2026-11-07）**：`swap_plant` 新增 `hd1910`/`hd1910_kp5`/`hd1910_kp8` 三分支（用 `plant_spec.py` 权威参数就地重建执行器，不依赖会被 `apply_to_live.py` 改写的全局单例）；`swap_plant` 始终记录真实 `kp_fw/json`；`plant_id.fingerprint()` 现接受可选 `kw`，eval 用 **`swap_plant` 实际应用到 env_cfg 的执行器**生成指纹，**不再读全局单例**——否则 m5 评测会被误标成 `hd1910_kp8`（正是当初误导标签的根源）。复测打印已正确显示 `plant=hd1910 kp_fw=32.0`（m5）/ `plant=hd1910_kp8 kp_fw=8.0`（kp8）。
  - 📌 评测产物：`out/eval_velocity_m5_model5999.json`（m5 同 plant）、`out/eval_velocity_kp8_p8head_model2999.json`（kp8 同 plant）。
  - ⚠️ 旧产物 `out/eval_velocity_kp8_model5999.json` / `out/eval_velocity_default_model5999.json` 是**跨 plant 误测**（m5 策略在 kp8 上），**结论无效，已弃用**。

### 7.2 部署链审计结论：**软件已成熟，非缺口**
- 审计 `export_onnx.py` / `make_manifest.py` / `verify_policy_contract.py` / `verify_policy_bundle.py` / `policy_numeric_gate.py` 与 `deploy_import_checklist.md §C1–C9`：
  - 导出：`export_onnx.py` 烘焙 normalizer + parity 校验；`make_manifest.py` 强制 `obs_len=61`/`act_len=14` 且拒绝无外部权重的空图（A8）。
  - 契约：`verify_policy_contract.py`（obs61/act14/50Hz）+ `verify_policy_bundle.py`（归一化下限 + metadata 对质）。
  - **致命坑已有专门防线**：`deploy61.onnx` 归一化 `Div` 分母 10 个维 = `1.113e-05`（放大 1157× → 5.7°头 → 动作 −35.7 rad）已被 `policy_numeric_gate.py` 的 G1–G4 + `--selftest` 负对照（健康 PASS / deploy61 FAIL）兜住。
- **结论**：部署软件齐备、文档化、有负对照；剩余风险只在**真机硬件**（清单 §A–B 总线/方向、§H 实机关卡），不在软件。故部署链**不列为软件缺口**。

> **路径约定**：本文档评测/部署命令里的 `out/...`（官方策略 `out/official_policies/*.onnx`、`out/deploy61.onnx`、`out/p8head_2999*.onnx`、`out/robotd_hd1910_mode0.toml` 等）是**相对 `microduck-software/`** 的——脚本从该目录运行，`out/` 即 `microduck-software/out/`（权重与产物实际落点）。仓库根 `out/` 仅含 reorg 桶（`builds/` `evidence-official/` `measurements/`），**不含**上述权重。reorg 未丢失数据。


