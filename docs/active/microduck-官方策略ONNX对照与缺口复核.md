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
- 对照方法：用 `tools/hd1910/eval_ground_pick.py --onnx` 把官方 ONNX 接进**本项目 HD-1910 GroundPick env**，跑同一套相位无关指标（成功率 / 摔倒 / 下降 / 直立 / 回姿）。
- **重要前提**：官方 ONNX 是 **B代（MicroDuck）训练**，本项目 env 是 **HD-1910 复刻线**——关节序与动力学不同，所以这是**跨机型压力测试**，不是官方策略的原生分数（原生分数需 B代 env，本 fork 未保留可加载的 B代 GroundPick env）。
- 结果（64 envs × 3 seeds）：

  | 策略 | 成功率 | 摔倒率 | 下降 | 直立 | 回姿 | 站立嘴高 |
  |---|---|---|---|---|---|---|
  | 我们 HD-1910 重训 `model_3999.pt` | **96.9%** (iqr 96.1–98.4) | 3.1% | 98.4% | 100% | 100% | 0.217 m |
  | 官方 `alpha_ground_pick.onnx`（在 HD-1910 上） | **23.4%** (iqr 23.4–27.3) | 76.6% | 81.2% | 100% | 100% | 0.220 m |

- 解读：官方 B代策略落到 HD-1910 上，**运动模式可复现（下降/直立/回姿仍 ~100%），但站不稳（76.6% 摔倒）**。对照我们 96.9% → 证明**官方策略不能直接移植 HD-1910，plant 专用重训既必要又成功**。这与"关节 ID 两套体系不能混用"的铁律一致。
- 复现：
  ```bash
  .venv-mjlab/Scripts/python.exe tools/hd1910/eval_ground_pick.py \
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
- 对照方法：`tools/hd1910/eval_roller_onnx.py` 把官方 `roller.onnx`（`--action-scale 0.8`）接进 **HD-1910 Rollers env**，测摔倒率 + 存活 + 步奖励。
- 结果（32 envs × 2 seeds × 500 步）：
  - **官方 `roller.onnx` 在 HD-1910 上：摔倒 17.2%，其余存活满窗 10 s，平均步奖励 0.102。**
  - 解读：轮滑任务跨机型迁移**远好于** GroundPick（17% vs 77% 摔倒）——"保持直立并滑行"对 plant 差异不敏感，**官方 roller ONNX 可作 HD-1910 轮滑训练的参考起点**；但 17% 摔倒说明仍有动力学差异（质量/轮摩擦/齿隙），真机上需 HD-1910 重训才稳。
- `roller_crouch.onnx` 补充对照（任务 `Mjlab-RollerCrouch-Flat-MicroDuck`，同 `--action-scale 0.8`）：
  - **官方 `roller_crouch.onnx` 在 HD-1910 上：摔倒 50.0%，平均步奖励 0.134。**
  - 注：脚本的 `mean_survival` 在 episodic 任务上会重复计数（倒地后 env 自动重置、后续步继续累加非摔倒步），对 crouch 不可信，**以 `fall_rate`（累计摔倒占比）为准**。crouch 多为末段摔倒（存活步数接近满窗但一半 env 倒过），与"蹲滑更难、平衡裕度更小"一致。
  - 解读：蹲滑（crouch）跨机型迁移**明显差于** plain roller（50% vs 17%）——重心压低的平衡裕度被 plant 差异吃掉更多；若要做 HD-1910 蹲滑，应直接重训而非移植官方 crouch。
- 复现：
  ```bash
  .venv-mjlab/Scripts/python.exe tools/hd1910/eval_roller_onnx.py \
      --task Mjlab-Velocity-Flat-MicroDuck-Rollers \
      --onnx out/official_policies/roller.onnx --action-scale 0.8 \
      --envs 32 --seeds 2 --device cuda:0 --max-steps 500 \
      --json out/roller_eval_onnx_hd1910.json
  # crouch 对照
  .venv-mjlab/Scripts/python.exe tools/hd1910/eval_roller_onnx.py \
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

## 6. 下游动作：基于 roller.onnx 启动 HD-1910 轮滑重训（2026-11-07 进行中）

原"两个任务"中「补回 B代 env 跑原生分」经核实**前提不成立**（官方 B代 RL 源 `microduck_rl-develop` 与我们 fork 是同一 `mjlab_microduck` 包、`robot_walk.xml` 惯量逐字节相同、velocity/roller env 配置一字不差——不存在独立 B代 plant 可补；之前测的 23.4%/17.2% 已是共享 plant 上的苹果对苹果分）。故只做**真有价值的第二条：HD-1910 原生轮滑重训**。

- 训练 env：`Mjlab-Velocity-Flat-MicroDuck-Rollers`（与 roller.onnx 基线**同 env**），plant 固定 `hd1910_kp8`（kp_fw=8，部署 plant，即基线评测生效 plant）。
- "基于 roller.onnx"取 **benchmark** 含义而非权重 warm-start：roller.onnx 内嵌归一化 + `action_scale=0.8`，与 rsl_rl actor（外部归一化）跨归一化/动作缩放两道边界，warm-start 有静默 bug 风险，避开。
- 流水线对齐 GroundPick：smoke 64×5 ✅（exit 0 / nan 0 / 7s）→ explore 1024×1000 🔄（reward −14.5→−0.18，fell 55.8%→46.6%，nan 0）→ formal 4096×4000 ⏳ → eval `.pt` 对比。
- 评估脚本 `tools/hd1910/eval_roller_onnx.py` 已支持 `--checkpoint`（rsl_rl `.pt`，原生 HD-1910 策略）与 `--onnx`（官方 B代）互斥，统一回放 + `fall_rate`/`mean_survival` 指标。
  - ⚠️ **已抓修一个会阻断最终对比的 bug**：`--checkpoint` 模式原用 `policy_call` 包装推理策略，闭包自引用导致 `RecursionError`；已改为直接用 `runner.get_inference_policy()`（与 `eval_ground_pick.py` 一致）。用 explore `model_100.pt` 冒烟已验证端到端能出 `fall_rate` 字段。
- **最终对比协议（必须严格同参，保证苹果对苹果）**：
  - 同 plant `hd1910_kp8`、同 env `Mjlab-Velocity-Flat-MicroDuck-Rollers`、同窗口 `--max-steps 500`（10s）、同规模 `--envs 32 --seeds 2`。
  - ONNX 基线：`--onnx roller.onnx --action-scale 0.8`（忠实还原 manifest 的 runtime 0.8 缩放）。
  - 我方 `.pt`：原生输出，无外部缩放（rsl_rl actor 已在其动作空间内学习）。
  - 判据：`fall_rate`（ONNX 基线 17.2%）须显著下降才证明 HD-1910 重训必要且成功；`mean_survival` 在 perpetual 任务下为「首次倒地前平均存活步」，作为辅证。
  - **追加"真在滑吗"指标**（避免"2% 摔但轮子不动"的伪胜利）：eval 从 `extras['log']` 累计 `Episode_Reward/wheel_speed`(权重10) 与 `Episode_Reward/glide`(权重4) 的步均奖励，作为 rolling signal。最终对比时 ONNX 基线与新 `.pt` **同设置同跑**，让摔率 + 滑行信号都苹果对苹果——已验证 `eval_roller_onnx.py` 能稳定输出这两字段。

## 7. 行走策略对照（旗舰主线）+ 部署链审计

### 7.1 行走对照准备（已就绪，待 GPU）
- **官方行走 ONNX 全集已下 + 动态 batch 兼容**：`pollen-robotics/microduck-policies` 全部 6 个策略（`alpha_walking`/`velstand`/`alpha_stand`/`alpha_ground_pick`/`roller`/`roller_crouch`）已落 `out/official_policies/`。官方导出把 obs 输入冻结成 `[1,61]` batch，**CPU EP 拒绝 ≠1、CUDA EP 静默广播**——已改为在加载时**内存动态化首维**（MLP 对 batch 维天然安全），脚本自给自足，重下 HF 也无需手工 patch（提交 `c2e0727`）。
- **`eval_velocity_in_sim.py` 加 ONNX 模式**（提交 `c2e0727`）：与我们的 `.pt` 走**同一套严苛物理量闸门**（足 clearance/滞空/速度跟踪误差/摔倒/横向漂移），支持 `--action-scale`（roller 系 0.8）。这样官方 `alpha_walking.onnx` 与我们的 `model_5999.pt` 苹果对苹果。
- **最佳行走候选**：`logs/rsl_rl/microduck_velocity_hd1910/2026-10-27_08-37-16_hd1910_resume_4096_to6000_1027/model_5999.pt`（kp8 线，最高迭代 5999，无 `model_final.pt`，按"外层 sweep 防抖动"后续多 seed 复核）。
- **官方行走基线（CPU 小样本，噪声大，待 GPU 大样本确认）**：`terminated_frac≈0.875`（跌倒率约 87.5%）、`vx_mean≈0.152 m/s`、`dx_over_expected≈-0.16`、gates 中 `no_fall`/`translates_forward`/`stays_upright` 均 FAIL——**官方行走 ONNX 在 HD-1910 异 plant 上几乎走不起来**，退化比 groundpick(23.4%成)/roller(17.2%摔) 更严重（走路对质量/重心最敏感），强力支撑"HD-1910 行走必须 plant 专用重训"。
- 复现：
  ```bash
  # 官方基线（同 plant default，与我们的 .pt 一致）
  .venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py \
      --task Mjlab-Velocity-Flat-MicroDuck --checkpoint out/official_policies/alpha_walking.onnx \
      --num-envs 64 --seconds 10 --device cuda:0 --cmd-vx 0.4 --plant default --seed 0
  # 我们的 .pt
  .venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py \
      --task Mjlab-Velocity-Flat-MicroDuck --checkpoint <model_5999.pt> \
      --num-envs 64 --seconds 10 --device cuda:0 --cmd-vx 0.4 --plant default --seed 0
  ```

### 7.2 部署链审计结论：**软件已成熟，非缺口**
- 审计 `export_onnx.py` / `make_manifest.py` / `verify_policy_contract.py` / `verify_policy_bundle.py` / `policy_numeric_gate.py` 与 `deploy_import_checklist.md §C1–C9`：
  - 导出：`export_onnx.py` 烘焙 normalizer + parity 校验；`make_manifest.py` 强制 `obs_len=61`/`act_len=14` 且拒绝无外部权重的空图（A8）。
  - 契约：`verify_policy_contract.py`（obs61/act14/50Hz）+ `verify_policy_bundle.py`（归一化下限 + metadata 对质）。
  - **致命坑已有专门防线**：`deploy61.onnx` 归一化 `Div` 分母 10 个维 = `1.113e-05`（放大 1157× → 5.7°头 → 动作 −35.7 rad）已被 `policy_numeric_gate.py` 的 G1–G4 + `--selftest` 负对照（健康 PASS / deploy61 FAIL）兜住。
- **结论**：部署软件齐备、文档化、有负对照；剩余风险只在**真机硬件**（清单 §A–B 总线/方向、§H 实机关卡），不在软件。故部署链**不列为软件缺口**。
