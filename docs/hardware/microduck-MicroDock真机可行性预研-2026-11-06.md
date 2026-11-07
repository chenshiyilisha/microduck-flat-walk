# MicroDuck MicroDock 真机可行性预研（非实现文档）

> 状态：预研盘点（2026-11-06 初稿；2026-11-07 补 MicroDock v2 坐姿坞与 scoot 策略）。
> 所有结论区分【核实】/【未核实】/【需实测】。
> 依据：上游 `playground/hardware/microdock/README.md`、`microdock-v2/README.md`、`microdock-v2/training/README.md`、
> `microdock-v2/sim/scoot_eval.py`、`microdock-v2/results/*.json`，以及官方 `pollen-robotics/microduck-policies` 的
> `manifest.json`（2026-11-06 拉取，apache-2.0）。
> 本文不承诺"能直接装机"——docs 与实现分开，真机验证前不作为功能承诺。

## 0. 一句话结论

MicroDock 是**官方 Playground 实验硬件自回充坞**：鸭子走到 AprilTag、原地转身 180°、倒车入坞，浮动罩下落接住机身，磁性 USB-C 适配器对接鸭子自己背部的 USB-C 口充电。**仿真验证 30/30 充电对接成功【核实】，但真机从未试过【核实】**，且机器人侧 docking 行为全部是仿真脚本、**未在真实机器人上实现【核实】**——真机落地需要重建三块（坞体打印件 + USB 充电电路 + 机器人动作/检测），其中**充电电路是最大卡点**（beta 板 USB-C 仅到 5V 轨、不充电，官方量产版本（issue #174 承诺）才带充电）。

## 1. MicroDock 是什么（核实的原文口径）

- 动作流程：找坞（AprilTag 识别）→ 全停约 24 cm 处原地转身 → 倒车（`velstand` vx=−0.4）入坞 → 磁性触点相遇后 USB 光亮起，鸭子停止 → 罩子归位充电。
- 坞体：5 个打印件（base 195×200、board 247×110、hood 109×111×54、keeper、AprilTag），P1S PLA，三块板共 **约 5 h 33 min / 241 g PLA**【核实】。
- 无螺丝、无弹性件；浮罩靠两滑轨骑跨在鸭子背顶（电源键/状态灯所在），侧壁导正机壳。
- 停靠精度【仿真】：每轮 0.4 mm 内完成对接，30/30 seed=41,42,43 ×10 成功；11 度偏移 32 mm 横向误差被浮罩±12 mm吸收。
- v2 是"坐姿坞"（鸭子坐回充电，多一个 board 件），非本文重点。

## 2. 机器人侧需要什么（真机落地≠仿真）

仿真里的 docking 行为**脚本化实现、未在真机实现【核实】**。真机需要的三块：

| 块 | 仿真做法 | 真机需要重建 |
|---|---|---|
| 坞体 | 打印件（STL 齐全） | 打印 5 件（来源：`playground/hardware/microdock/`） |
| 离合器/电路 | 磁吸 4N + USB 供电 | 磁吸 USB-C 适配器组合（官方 BOM：Auravale 适配器、弯头线、充电器，价格 ~$35 + PLA） |
| 机器人动作/检测 | AprilTag 检测是仿真脚本；转身/倒车调官方 `velstand.onnx` | 相机 AprilTag 检测（本项目 BOM 已有 IMX219）+ 走到标签前 + 原地转身 = 需要机器人侧视觉/运动规划——**这部分官方没有真机实现** |
| USB power detection |仿真触发停走 | 鸭子何时停走由检测 USB 供电信号决定——由电路板与 robotd 的供电检测决定【未核实】 |

## 3. 对 HD-1910 复刻版机器人的适配检查（三大风险点）

### R1（最优先）USB-C 充电电路
- 官方口径【核实】："The current beta boards do not charge over USB-C (their USB-C port only reaches the 5 V rail)。"
- **MicroDock 前提是鸭子自己的 USB-C 口带充电路径（power path 要走到电池）**。beta 板只到 5V 轨 ⇒ 坞上只会让鸭子 USB 口亮一点电，**不充电**。
- 所以第一个 gating 问题：**本台鸭子（HD-1910 replica，beta 板）USB-C 口能否给电池充电？**【需实测】——决定 MicroDock 在本台机器上能否工作（而非打印坞体）。
- 若 USB-C 不带充电 → 坞体只能做"停靠演示"，充电功能不成立；若要走真充电，需要改板子（电池充电 IC）、或换官方量产主控（issue #174 承诺）。

### R2 机壳背部 USB-C 口位置
- 官方描述（来自近期量产鸭子照片）：USB-C 口居中于机壳接缝、电池正上方，cut-out 宽 12 mm、口中心高出 rear edge 约 4.5 mm 等——**照片估计值【需实测】**。
- 本项目复刻版机的 CAD 是 FT2026-10-20 口径，左/右壳与新量产壳大概率对应（CAD 未书面记录 USB-C 口），**装机前需按 MicroDock 的 docking 参数（`port_above_bat`、`notch_w`、`shell_back_x` 等）实测对位**【需实测】。
- 若实测不对位 → 坞体几何需要改（branch point：坞体设计参数 vs 鸭子壳外形）。

### R3 真机 docking 实现（最大软件工作量）
- 需要：相机 AprilTag 检测（官方 mag 4 N + 仿真匹配的外参）、标签引导（A*驱动）到 dock 中心线、24cm 处定停转身 180°、倒车入坞（`velstand.onnx` 默认含负 vx，官方仿真未改）、触碰检测停走。
- 官方只给了仿真脚本 `<robot_docking>` 形状【核实】，机器人侧源码不随仓库——实现量不小于一个"视觉伺服导航 + 停靠调度"工程。

#### R3 补正（2026-11-07）：MicroDock v2 已给出"学到的"机器人侧 docking 控制器
- **v2 把 docking / undocking 做成了学到的策略网络**，不再是 v1 的纯脚本化运动：
  `playground/hardware/microdock-v2/policy/scoot_dock.onnx`（入坞：坐下后坐滑后退入坞并定停）与
  `scoot_undock.onnx`（出坞：顶着磁吸向前滑出）。另有实验性的 `policy/experimental/scoot_dock_undock.onnx`（一个网络靠命令正负号兼顾进出）。
- 它们属于**同一策略族**（与本项目 ground_pick / walk 同构）：输入 61-D 观测（48 本体 + 13 命令），输出 14 个 BAM XL330 动作，50 Hz；训练任务 `Mjlab-ButtWalk-Flat-MicroDuck`（microduck_rl develop `bae39f59`，每回合从坐姿开始）。
- **但仍是仿真产物、未在真机跑过**，且是 **B代（MicroDuck）训练**——与本项目 HD-1910 复刻线存在 plant 差异（见 §6 与 GroundPick 对照结论：官方 B代策略直接落到 HD-1910 仅 23.4% 成功率）。所以 v2 给出的是"可参考的控制器范式 + 网络权重"，不是 HD-1910 可直接装载的 docking 策略；真机落地仍需在 HD-1910 上重训（同样的 plant 专用重训逻辑）。
- 围绕 scoot 的"行为层"（AprilTag 检测、转身、坐下、USB 上电停走、充满唤醒离开）在 v2 里**仍是脚本/仿真**，未在机器人侧实现。

## 4. 成本与打印盘点

| 项 | 量/成本 |
|---|---|
| 打印 | P1S 三块板 ~5h33min、241g PLA（坞体外壳白色） |
| 电子/外购 | 磁吸 USB-C 适配器（Auravale ~€8.99）+ 直角弯头 USB-C 线（~$11.99）+ USB-C 充电器（~$15.99）；价格 2026-11 口径【核实】 |
| 工作量 | 坞体打印+装配（坞体打印参数与装配步骤见上游 microdock/README）；真机 docking 软件为剩余大头【未核实】 |
| 风险 | 充电电路 gating：R1 不满足则坞体停在演示不能做功能承诺 |

## 5. 结论与建议

- MicroDock 对 HD-1910 复刻机**不是现成功能**，是官方仿真验证过的实验硬件：坞体打印、配重、几何都可复现，但**机器人充电电路 + 真机 docking 实现两道齐全**才成立。
- **最小 gate 循环**：先实测本台鸭子 USB-C 口是否有经验证充电路径（R1）→ 再实测机壳缺口对位（R2）→ 都在，才投入坞体打印（~5.5h）→ 最后才是 docking 软件实现（R3，完整另立工程）。
- 推荐顺序：R1（首日可测：坞体送 5V，看鸭子电池电压是否上升）→ R2（直尺/照片对位）→ 坞体打印（并行，~5.5h）→ docking 软件（另立项目，不占本文）。
- **v2 坐姿坞的软件工作量更小**：入坞/出坞已是学到的 scoot 策略（§6），真机移植主要是"把 B代 scoot 网络在 HD-1910 上重训 + 行为层脚本化"，比 v1 从零写 docking 运动规划省力；但充电电路 R1 仍是不可绕过的硬 gate。

## 6. MicroDock v2（坐姿坞）设计要点【核实，均来自 v2 README / training / results】

> v2 是 v1（站立倒车坞）的演进：**鸭子坐下，用学到的 scoot 策略坐滑入坞、充电时坐着休息、充满后坐滑出再走开**。
> 官方状态：仿真设计与验证完成，**未上真机**，与 v1 同源。

### 6.1 与 v1 的结构差异
- **只多一个件：board（基板）**。它把浮动罩压低 57 mm 到"坐姿鸭子"的高度（罩高 `z0 = 62` mm，因为鸭子坐着约 61–64 mm 高）；hood / base / keeper / tag 沿用 v1。
- 装配 12 步（`media/microdock_v2_assembly.pdf` 为 1:1 打印校验手册，page 2 有线缆粗细 1:1 对照；打印必须 100%）。

### 6.2 动作流程（坐姿）
1. 走到 AprilTag 前、约距 board 200 mm 原地转身（比正对多转 6.6°，抵消坐下时的回正）。
2. 官方 `alpha_sitstand` **坐下**（坐下过程后移约 65 mm）。
3. `scoot_dock.onnx` 以约 **4 cm/s** 坐滑后退、保持航向，最后 6–9 cm 入坞：罩的喇叭侧壁导正、罩骑上背可横向浮动 ±20 mm、磁吸头在最后 1 mm 由磁力闭合。
4. 检测到 **USB 上电**→ 全零命令定停、坐着充电（可进入"睡眠"：腿瘫软、头落在限位、所有舵机断电）。
5. 充满 → 唤醒 → `scoot_undock.onnx` 顶着磁吸向前滑出（4 N 磁吸约 1.06 s 脱困，最多 1.34 s）。
6. `alpha_sitstand` 站起 → `velstand` 走开。

### 6.3 机器人侧 docking 控制器 = 学到的 scoot 策略（§3 R3 补正）
- `scoot_dock.onnx` / `scoot_undock.onnx`（+ 实验 `scoot_dock_undock.onnx`）。
- **同策略族**：输入 61-D 观测（48 本体感知 + 13 命令块；twist 槽为 `[vx, vy, wz]` 体坐标，head 姿态槽同其它策略，body 姿态槽为零），输出 14 个 BAM XL330 动作，50 Hz。
- 训练任务 `Mjlab-ButtWalk-Flat-MicroDuck`（microduck_rl develop `bae39f59`），每回合从坐姿开始；座摩擦随机化 0.05–0.25 渐增到 0.3–1.0。
- **HD-1910 移植警示**：这些是 **B代（MicroDuck）训练**权重，与本项目 HD-1910 复刻线存在 plant 差异（关节序/动力学）。GroundPick 的对照已证明官方 B代策略直接落到 HD-1910 仅 23.4% 成功率（见 `microduck-software/tools/hd1910/eval_ground_pick.py --onnx` 结果）——v2 scoot 策略若直接装载 HD-1910 同样不可靠，**须在 HD-1910 上重训**。

### 6.4 仿真验证结果【核实】
- **入坞**（`sim/docking_seated.py`，seeds 41/42/43 ×10）：**30/30** 入坞（USB 接通并保持），**0** 次罩碰到电源键；座摩擦 0.3 / 0.8 各 10 组 → 均 10/10。精度：沿推程 ±0.1 mm、横向 0.6 mm、竖向 0.5 mm。
- **出坞**（`sim/undocking_seated.py`，磁吸 4 N）：30/30 入坞、**30/30 脱困**（中位 1.06 s）、30 站起、30 走开。磁吸 6 N → 10/10 脱困（中位 1.49 s，最多 5.3 s）。磁吸 8 N → 大多脱不出、站起被罩卡住。
- **延迟敏感**：出坞策略**只有在训练时的延迟节奏下**才能脱困（无延迟 10 次仅 1 次脱困）——真机延迟与真磁吸拉力尚未实测。

### 6.5 对 HD-1910 真机落地的含义
- 坞体打印件（v2 比 v1 多一个 board）机器人无关，可复现；装配步骤以 PDF 为准。
- **最大不确定性仍是 R1（充电电路）** 与 R2（机壳 USB-C 口对位）；R3 因 v2 已有 scoot 策略范式而显著减负，但仍需 HD-1910 重训 + 行为层实现。
- 真机未验证项：磁吸 4 N 真值、机器人侧延迟、USB 上电检测、充满唤醒逻辑——这些 v2 也只在仿真里跑过。
