# MicroDock v2 坐式坞深研

_2026-11-10，核对于上游 `main@052a2494`。上一份总览见 `microduck-playground-仓库研究-2026-11-09.md`；
本文只拆 v2 与它背后的 scoot（butt walk）策略。_

## 0. 一句话判决

**v2 的机械增量很小（多一块 board 板），真正的资产是两个坐姿挪动策略**（`scoot_dock.onnx` /
`scoot_undock.onnx`）及其**完整可复现的训练配方**（patch + env cfg + mdp helpers + 全部超参环境变量）。
对我们（HD-1910 线）而言：**机械可照抄（不依赖真机测量值的部分），策略必须在我们 plant 上重训**；
配方是可直接搬的模板。

## 1. v2 与 v1 的全部差异

四件套（hood / base / keeper / tag）与 v1 完全共用，唯一新零件是 `board`。参数级差异只有三处
（`source/seated.py`，继承 `microdock/source/dock.py` 的 `Params`）：

| 参数 | v1 站立 | v2 坐姿 | 原因 |
|---|---|---|---|
| `z0`（trunk 原点高度） | ~119 mm | **62 mm** | 坐下后躯干矮 ~57 mm，board 把 hood 窗口/V 座/线夹整体下移 |
| `hood_float_y`（横向浮动） | 12 mm | **20 mm** | 坐姿落点横向散布更大（sim 实测 ±25 mm） |
| `hood_drop`（下垂余量） | 7 mm | **12 mm** | 坐姿高度方差更大 |
| `adapter_dz` | 0 | **0** | 坐姿策略坐得很平（早版策略前倾 7° 时曾需要 -2.3 mm，已废） |

## 2. 完整行为链（部署时序）

1. 走向 AprilTag，原地转身，距板约 200 mm 处停——**故意多转 6.6°**，因为坐下动作会把朝向拉回约这么多。
2. 官方 `alpha_sitstand` 坐下——坐下过程本身向后挪约 65 mm。
3. `scoot_dock` 坐姿倒退 ~4 cm/s，走完最后 6–9 cm；喇叭口侧壁纠偏，hood 最多横浮 20 mm，磁头吸合。
4. 检测到 USB 上电 → 全零命令 → 坐着充电（演示版还睡觉：腿 limp、头落到限位、所有舵机断电）。
5. 醒来 1 s 内回坐姿 → `scoot_undock` 坐姿前挪，约 1.06 s（中位）挣脱磁铁，2 s 后出 70 mm。
6. 官方 `alpha_sitstand` 站起 → 官方 `velstand` 走掉。

其中**只有 3 和 5 是学出来的策略**；tag 识别/转身/坐下/上电检测/睡眠/离开全部是脚本（真机运行时未实现）。

## 3. butt walk 任务拆解（训练配方全文）

任务名 `Mjlab-ButtWalk-Flat-MicroDuck`。构建方式：对 `microduck_rl@bae39f59` 打
`training/butt_walk.patch`（53KB），在 **sitstand env** 上派生——继承同一机器人模型、坐下接触的
contact-solver 加固、DR/观测噪声/延迟、可命令头部、NaN 防护、BAM 摩擦场。每回合从 SIT keyframe 起步。

⚠️ **注意 commit 差异**：patch 针对 `bae39f59`，我们 submodule 锁的是 `b02fdea`——引入前先 diff 这两个 commit 的
sitstand/velocity 文件，确认 patch 可干净落上。

### 3.1 命令与观察

- 观察契约与我们完全一致：**61D（48 本体 + 13 命令块）**，twist 槽 `[vx, vy, wz]` 体坐标，head 槽照旧，body pose 槽全零。
- 命令范围：**vx −0.10～+0.06**（偏后退，倒车进坞是主业）、**vy ±0.01**（纯为保输入活性——与我们 AGENTS.md 的
  dead-weight 规则同源）、wz ±0.3；**20% 精确全零**（停靠静止 + 充电休息都是部署态）；重采样 2.5–6 s；回合 12 s。

### 3.2 奖励设计（逐项 + 每项的「为什么」）

| 项 | 权重 | 说明 |
|---|---|---|
| track_linear_velocity | 3.0 | Gaussian，**std 0.04 m/s**（对接速度 ~0.05 m/s 量级，std 必须同量级） |
| track_angular_velocity | 1.5 | Gaussian，std 0.25 rad/s |
| progress_lin / progress_ang | 2.0 / 1.0 | **线性封顶进度项**：Gaussian 在低速段是平的（不动也能拿满）→ 首批策略就原地不动；进度项按「实际/命令，截断 ±1」付费，超过命令速度不给。无 jackpot |
| seated_height | 1.0 | 高度 Gaussian @65 mm，std 0.02 |
| seated_height_cap | 20.0 | 一侧 L1，>80 mm 才罚（自取负→写正权重） |
| stood_up（终止） | — | >95 mm 终止（站立 115 mm）——**站起来走路是移动的捷径，直接掐掉** |
| seated_upright | 1.5 | 躯干 tilt Gaussian，std 0.07（≈4°，很尖）——坐得平 = hood 里磁头与适配器对得正（hood 在 trunk 系对躯干） |
| head_pose_tracking + head_pose_l1 | 1.5 / 5.0 | 头部追踪 + 线性 L1 + **>0.8 rad 终止**。不罚：策略低头 ~85° 把重心压到脚上卸掉坐垫载荷（摄像头离地一英寸） |
| still_at_zero_command | 1.0 | 全零命令下的静止（vel_std 0.03） |
| seated_leg_pose | 0.5 | 松的腿部姿态（std 0.6，SIT 覆盖值），腿折在前面但不挡蹭行 |
| hip_limit_proximity | −3 | 见 3.4 |
| fell_over（终止） | — | 60°（与我们摔倒口径一致） |

### 3.3 坐垫摩擦 DR（对 sim2real 最要命的一项）

屁股一直在地上滑，摩擦系数直接决定任务成不成立（塑料壳对 PLA/木头 ≈ 0.3–0.5，而模型碰撞 geom 默认 1.0）。
**导出的 XML 里坐垫 geom 是未命名的**（只有脚掌命名了），mjlab 的 CollisionCfg 和摩擦 DR 都点不到名
→ 先在 spec 里把所有碰撞 geom 改名 `<body>_<k>_collision`，脚掌两个保持 friction 1.0，其余按 env 重采样。
课程：0–400 迭代 0.05–0.25 → 900 迭代 0.25–0.7 → 1500 迭代全范围 0.3–1.0（先滑后真，先学会蹭再扛摩擦）。

### 3.4 舵机代价教训：hip 停在硬限位上 = 18 W 发热

不罚 hip 限位：首版策略把两个 hip roll（加一个 hip yaw）**停在硬限位上，目标角超限 +94°～+340°**，
舵机以电流限值硬顶着——CPU 彩排实测 **~18 W 电机发热 vs 官方坐姿策略 0.5 W**。罚项加在 **qpos 侧**
（命令侧超冲是低 kp 舵机到目标的正常方式，不能罚）。加了之后 hip 离开限位，坐高稳定 61–64 mm——
**这就是 dock 把 hood 定在 z0=62 的原因**：机械尺寸被策略行为反推。

### 3.5 脱困（undock）训练

- 30% 回合以已入坞状态起步：磁铁吸住 port、hood 罩背（当天花板 + 航向保持器，`UNDOCK_YAW_K=2 N·m/rad`，
  出坞 ~20 mm 前一直箍着航向——不箍的策略倒车时自旋 0.3–0.65 rad/s，错过坞）。
- 磁力未知（真适配器没量过）→ 按课程从范围里抽：0 迭代 0.5–1.5 N → 1600 迭代 2–6 N。
- `UNDOCK_PROGRESS=1.0`：**potential-based** 出坞净进度，回合被终止要**退还**——猛冲出去摔了=白干。
- `UNDOCK_CRITIC=1`：**磁力只给 critic**，策略必须自己「感觉」到磁铁。
- 脱困策略 = 迭代 1100；**只有带训练延迟才能挣脱**（舵机目标晚 3–6 物理步、每步重采样；关节速度与 IMU 晚
  1 控制步）——它是照延迟的节奏推的；去掉延迟 10 次只成 1 次。真机延迟与真磁力都没量过（明确留下的缺口）。

### 3.6 课程天花板（跟我们 1500 迭代的故事同构）

继承自 sitstand 的课程在**迭代 1500 全部硬化**（头姿范围 0.49→0.91、pushes ×2、action rate −1.0、
起身速度 5），butt walk 在那里**全线崩**：head-off 终止 ×15，回合 580→250 步，到 2000 都不恢复。
`MICRODUCK_BW_CURRICULUM_CAP=1499` 把继承课程在 1499 截断（自己的三个课程保留）。
**发布的 dock 策略 = 2000 轮跑里的迭代 1400 checkpoint**——又是一次「峰值在中途，靠外层 sweep 选点」。

### 3.7 训练成本

4096 envs、单卡 H200、约 30 迭代/分钟 → 2000 迭代 ≈ **67 分钟一个策略**（3 个策略 ≈ 3.5 h GPU）。
全部从零训；但作者注明前代「butt scoot」actor（61D/14 act/512-256-128 ELU，同契约）可 warm-start。

## 4. 仿真结果与边界

- **入坞**：30/30（种子 41/42/43 × 10）；坐垫摩擦 0.3 / 0.8 各 10/10（训练只到 0.7 也扛住 0.8）。
  精度：沿推进方向 <0.1 mm、横向 0.6 mm、竖向 0.5 mm。坐下落点散布 −18～+14 mm / −6°～+8.5°，
  全被喇叭口+浮动 hood 吸收。
- **出坞**：4 N 30/30、6 N 10/10、**8 N 只有 2/10**——磁力是硬约束，买磁吸件必须实测拉力。
  4/6 N 下 40 次里 2 次起身时蹭到 hood（≤5.6 N 力）。
- **重新对中弱**：V 座（~10°）在 PLA 摩擦下对不中，去掉仿真对中弹簧后 ±10 mm 全过、−20 mm 29/30、
  +20 mm 27/30——**歪了就歪着充，不会自动回正**。
- 入坞推坞 ~3 N（峰值 6 N）、出坞拉 ~3 N：240 g 自由坞必滑，靠墙+固定。
- 实物 hood 连转接头+线头约 45 g（仿真 28 g）——45 g 仍 30/30。
- **实验版单策略**（iter 2699/2700，命令符号区分进/出）：4 N 下 30/30 进+出、6 N 10/10，倒车直行漂移
  0.003 rad/s。标 experimental 的原因：**训练环境自带的 check 报大多数出坞回合提前结束，与仿真结果矛盾且未解释**；
  评估也少。这条要记住——同一个作者自己都不信。

## 5. 对我们的可移植性判决

1. **机械**：board（94KB STL，plate 2 共 3h01/130 g）不依赖真机测量—— hood/base/keeper/tag 沿用 v1 的
   尺寸链。但 hood 上那 4 个鸭子背尺寸（port 高度/切口/壳宽/滑轨高）**仍是 v1 的待量清单**，v2 没有解决它们。
2. **策略**：契约 61D/14 act/50 Hz 与我们一致，但全部在 **BAM XL330（kp_fw=200）** 上训——我们 HD-1910
   飞特 kp8，**换 plant = 换任务必须重训**（我们自己的铁律）。ONNX 本身对我们无用，**值钱的是 patch + env cfg
   + 超参环境变量这套配方**。
3. **配方价值**（可直搬的部分）：
   - 低速任务「Gaussian 平坦 → 加线性封顶 progress」的修法，与我们低速死区结论同源（真低速必须新任务，
     butt walk 就是那个新任务的完整样本）；
   - 「结算在 qpos 侧不罚命令侧」的舵机限位处理；
   - 「磁力只给 critic、策略自己感受」的接触力训练法（potential-based + 终止退还）;
   - 继承课程在特定迭代崩 → 截断继承课程保自己的课程（`CURRICULUM_CAP` 模式）——与我们的
     `--defer-by` 多变量干预教训互为印证；
   - 坐垫/接触面摩擦 DR 的「先命名 geom 再 DR」手法（我们 BAM 下 `dof_frictionloss` 被清零的问题同类）。
4. **集成风险**：patch 针对 `microduck_rl@bae39f59` ≠ 我们锁的 `b02fdea`，引入前必须 diff；
   patch 是对上游文件的**修改**（非纯新增）——按我们「纯新增」铁律，需要转写成自己的 wrapper/新增文件。
5. **缺口清单（作者自己列的）**：真机零验证；真磁力、真延迟未量；行为链脚本化；
   实验版单策略的训练自检与仿真矛盾未解释。

## 6. 附：拉取的文件

全部在 `_stage/duckpg/files/`（已 gitignore）：`v2_source_seated.py`、`v2_training_microduck_butt_walk_env_cfg.py`
（20.7KB 全文）、`v2_training_mdp_butt_walk.py`（18.3KB helpers）、`v2_sim_latency.py`、`v2_sim_scoot_eval.py`、
`hardware_microdock-v2_training_README.md`、`hardware_microdock-v2_README.md`。
原始大件（53KB patch、ONNX、装配 PDF、结果 JSON）需要时按 tree.json 里的 path 直拉 raw。
