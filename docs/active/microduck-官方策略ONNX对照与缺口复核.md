# 官方策略 ONNX 对照与资料缺口复核（2026-11-07）

> 收口两条元任务：① 挖掘参考过的开源项目还有哪些可用；② 复核前面是否有缺资料对照的环节。
> 落实三个缺口：**缺口5**（GroundPick 未与官方 `alpha_ground_pick.onnx` 对照）、**缺口1**（MicroDock 未挖 v2 / scoot_dock.onnx）、**缺口2**（轮滑未引 roller 生态）。
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
