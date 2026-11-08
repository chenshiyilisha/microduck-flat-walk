# ~~MicroDock 官方研究参照（追溯结果 + 设计全貌）~~ —— 已被源码级深挖取代

> ⚠️ **本文件已过时**：2026-11-08 同日后续做了源码级深挖（读了全部仿真脚本、训练 patch、几何参数、7 份结果
> JSON），权威版本见 **`microduck-MicroDock官方深度挖掘-2026-11-08.md`**。下面仅保留追溯结论，细节以深挖文档为准。

> 追溯结论：本项目 `microduck-software/.upstream/playground/hardware/microdock(+v2)/` 即为官方研究真身。
> 它属于 `pollen-robotics/microduck` 仓库的 **Playground 实验项目**（README 引用官方 issue #174/#470、
> `microduck_rl` commit `bae39f59`、仓库 `LICENSE`/`LICENSE-HARDWARE`）。
> **不在 main 发布分支**（已用 Git Tree API 核实 main 根目录无 `playground/`），**不在已发布策略 manifest**
> （`scoot_dock/undock.onnx` 只存在于本地 playground，未进 `microduck-policies`）。
> 状态：仿真验证过、真机从未测过。
>
> 本文是"参照官方研究"的整理版，不判断对错、不谈实现可行性（实现另立工程）。

---

## 0. 一句话

MicroDock = 官方做的**自回充坞**：鸭子走到 AprilTag → 转身 →（v1 站立倒车 / v2 坐下坐滑）入坞 →
浮动罩的**磁性 USB-C 适配器**对接鸭子**背部自己的 USB-C 口** → 不换电池、直接给机器人自身电池充电。
全打印、无螺丝。v1/v2 均 **sim-only、真机未测**；且依赖"量产板带机内充电"（beta 板 USB-C 仅到 5V 轨、不充电）。

---

## 1. 来源与状态（已核实）

| 项 | 内容 |
|---|---|
| 官方性 | ✅ Pollen 官方 Playground 项目，仓库内 `playground/hardware/microdock(-v2)/`，许可跟随仓库（硬件 CC BY-NC-SA 4.0 / 软件 Apache-2.0） |
| 是否在 main 分支 | ❌ 否。main 根目录无 `playground/`（已用 Git Tree API 核实）。在一条未合入主线的分支/PR 上 |
| 是否发布策略 | ❌ 否。`scoot_dock.onnx`/`scoot_undock.onnx` 仅在本地 playground，未进 `microduck-policies` manifest |
| 真机验证 | ❌ 否。README 明写 "designed and tested in simulation only; not yet tried on hardware" |
| 关联官方 issue | #174（量产板机内充电承诺）、#470（机内充电行为未公开） |
| 依赖训练栈 | `microduck_rl` develop @ `bae39f59`；官方策略 `velstand.onnx` / `alpha_sitstand.onnx` |
| README 时间戳 | v1 有 "Update, 5 November 2026"（keeper 加高到 32mm 等修订）→ 说明是近期活跃项目 |

---

## 2. MicroDock v1（站立倒车坞）

**流程**：找坞（AprilTag）→ 约 24cm 处原地转身 180°（侧偏 12mm 补偿）→ 倒车 `velstand` vx=−0.4 + 陀螺仪保持航向
→ 浮动罩骑上鸭背、喇叭侧壁导正、磁吸头最后 1mm 由磁力闭合 → USB 上电鸭子停走 → 站立充电。

**关键设计点**：
- **不换电池**：经机器人自身 USB-C 口给自身电池充电（依赖 #174 量产板机内充电；beta 板不充）。
- **全打印无螺丝**：浮动罩骑跨在鸭背顶的电源键/状态灯上，侧壁导正机壳；两滑轨 + keeper + 1.75mm  filament 销锁定。
- **容差由硬件吸收**：浮罩 ±12mm 横向浮动 + 喇叭侧壁；11° 偏移 / 32mm 横向误差被吸收。
- **对接精度（仿真）**：每轮 0.4mm 内完成；30/30（seeds 41/42/43 ×10）对接成功，0 次碰电源键。

**坞体 5 件 STL（组装朝向）**：
| 件 | 尺寸(mm) | 说明 |
|---|---|---|
| base | 195×200×19 | 平板+前坡+插座，鸭子站在上面压住坞 |
| board | 247×110×6 | 平卧，左缘夹线 |
| hood | 109×111×54 | 倒置，网格支撑（仅底板外表面与 peg）；含适配器卡爪 |
| keeper | 42×32×4 | 滑入 peg 后侧，filament 销锁定（v1 初版太短已改 32mm 高） |
| tag | 60×60×2.2 | AprilTag tag36h11 #0，黑底白凸点 |

**打印**：Bambu P1S，3 板 ~5h33min / 241g PLA（白+黑），`print/microdock_P1S.3mf` 是现成工程。

**BOM（2026-11 口径）**：磁吸 USB-C 适配器 2 件套(Auravale 240W, 过 CC 让充电器启充) €8.99；直角 USB-C 线(UGREEN 100W) $11.99；USB-C 充电器(Anker 30W) $15.99；PLA ~€4。

**依赖的机体几何（需真机实测，README 标为照片估计）**：
- USB-C 口居中于机壳接缝、电池正上方；cut-out 宽 12mm、口中心高出 rear edge ~4.5mm、口比机壳略深。
- 磁吸头(11.8×6mm)贴 cut-out 宽但高于口上空间 → 靠在 cut-out 顶边，插头伸入 ~5.85/6.65mm。
- 黄色电源键在左肩后顶面的凸起白环；两状态灯在另一侧。
- 相关参数在 `source/dock.py`：`port_above_bat` / `notch_w` / `port_recess` / `shell_back_x` / `button_xy` / `leds_xy` / `skid_y` / `hood` 尺寸。

**仿真复现**：
```bash
export MICRODUCK_RL_DIR=...   # microduck_rl @ bae39f59
export MICRODUCK_POLICY_DIR=... # velstand.onnx, alpha_sitstand.onnx
uv run python hardware/microdock/sim/docking.py --seeds 41,42,43 --n 10 --stop_gap 0 --out backin30.json
```
验证环境：mujoco 3.10.0 / onnxruntime 1.24.4 / better-actuator-models 1.0.1；
`velstand.onnx` SHA-256 `2fc7f8ee…`、`alpha_sitstand.onnx` SHA-256 `a6f102d9…` 时结果可精确复现。

---

## 3. MicroDock v2（坐姿坞，更省电）

**流程**：走到 tag → 约 200mm 处转身（比正对多转 6.6° 抵消坐下回正）→ `alpha_sitstand` **坐下**（后移 ~65mm）
→ `scoot_dock.onnx` 以 **~4cm/s** 坐滑后退、保持航向、最后 6–9cm 入坞 → USB 上电停走、坐充
→ 充满 `scoot_undock.onnx` 顶磁吸向前滑出(~1.06s 脱困) → `alpha_sitstand` 站起 → `velstand` 走开。

**为什么坐姿更好**：腿几乎不承重→伺服功耗低、无热/磨损、不会摔倒。

**与 v1 结构差异**：只多一件 **board**（把浮动罩压低 57mm 到坐姿高度 z0=62mm；罩可多横向浮动±20mm、多下坠）。hood/base/keeper/tag 沿用 v1。1:1 装配手册 `media/microdock_v2_assembly.pdf`。

**策略网络（关键）**：
- `policy/scoot_dock.onnx`（入坞）、`policy/scoot_undock.onnx`（出坞）；另 `policy/experimental/scoot_dock_undock.onnx`（一个网络靠命令正负号兼顾进出）。
- **同策略族**：输入 61-D（48 本体感知 + 13 命令块，twist=[vx,vy,wz] 体坐标，head 姿态槽同其它策略，body 姿态槽为 0），输出 14 个 BAM XL330 动作，50Hz，obs 归一化已烤进图。
- 训练：`microduck_rl` develop @ `bae39f59`，任务 **`Mjlab-ButtWalk-Flat-MicroDuck`**（butt_walk.patch 新增），每回合从坐姿开始。
- **均由官方 B 代（MicroDuck）模型训练，未在真机跑过**。
- 命令电池（`sim/scoot_eval.py` + `results/scoot_dock_commands.json`）：vx −0.05→后退 0.040m/s；vx −0.08→0.046m/s；vx−0.05+wz±0.2→转向 +0.46/−0.57 rad/s；全零→静止；vx+0.05→前进 0.043m/s。trunk 水平(~2°前倾)，头最低点 80mm 高。

**仿真结果（v2）**：
- **入坞** `results/seated30.json`（41/42/43×10）：**30/30** 入坞且保持，0 碰电源键；精度 推程±0.1mm / 横向0.6mm / 竖向0.5mm；座摩擦 0.3&0.8 各 10 组均 10/10。
- **出坞** `results/undock30.json`（磁吸 4N）：**30/30** 入坞、30/30 脱困(中位1.06s)、30 站起、30 走开；6N→10/10(中位1.49s)；8N→大多脱不出、站起被卡。
- **延迟敏感**：出坞策略**只有按训练延迟节奏**才脱困（无延迟 10 次仅 1 次）；真机延迟与真磁吸拉力未测。
- **实验单网络** `results/experimental_dock_undock.json`：4N/6N 各 30/30、10/10，但训练环境自带 check 与结果矛盾、评估较少 → 标 experimental。

**打印**：v2 多 board，三板 ~5h32min / 240g（`print/microdock_v2_P1S.3mf`）。

---

## 4. 对 HD-1910 复刻机的移植警示（官方源已写明 + 本项目补充）

1. **R1 充电电路（硬 gate，官方也点名）**：官方口径 "current beta boards do not charge over USB-C (only 5V rail)"，
   依赖 #174 量产板机内充电。**HD-1910 复刻 beta 板同理→坞上只亮灯不充电**，真充电需改板或换量产主控。
2. **R2 机壳 USB-C 口位置**：官方参数来自量产鸭照片估计（`port_above_bat`/`notch_w`/`shell_back_x` 等），
   复刻壳须**真机实测对位**再决定坞体几何要不要改。
3. **R3 策略移植**：`scoot_dock/undock` 是 **B 代（MicroDuck）训练**权重，与 HD-1910 复刻线存在 plant 差异。
   本项目 `eval_ground_pick.py` 已证明 B 代策略直落 HD-1910 仅 23.4% 成功率 → **须在 HD-1910 上重训**（同 plant 专用逻辑）。
4. **行为层仍是脚本/仿真**：AprilTag 检测、转身、坐下、USB 上电停走、充满唤醒离开——官方没在机器人侧实现，须自建。
5. **许可**：硬件 STL 是 **CC BY-NC-SA 4.0**（非商业），商业整机不得直接用；软件/策略 Apache-2.0。

---

## 5. 文件清单（本地真源路径）

```
microduck-software/.upstream/playground/hardware/
├── microdock/            # v1
│   ├── README.md  source/{dock,cad,plates,bambu_project}.py
│   ├── stl/  print/  renders/  media/  sim/{docking,back_patch,visuals,render_preview,render_gallery}.py
│   └── results/backin30.json
└── microdock-v2/         # v2（坐姿）
    ├── README.md  media/microdock_v2_assembly.pdf
    ├── source/{seated,build}.py
    ├── policy/{scoot_dock,scoot_undock}.onnx  policy/experimental/scoot_dock_undock.onnx
    ├── training/README.md + butt_walk.patch + mdp_butt_walk.py
    ├── sim/{docking_seated,undocking_seated,latency,scoot_eval}.py
    └── results/{seated30,seat_friction,undock30,undock_magnet,experimental_dock_undock,scoot_dock_commands}.json
```

---

## 6. 与既有文档的关系

- 推翻 `microduck-自充电官方参照与核实-2026-11-08.md` 中"MicroDock 无法核实/疑似非官方"的结论：
  现已在本地上游快照内找到完整官方真源，确认其为**官方 Playground 实验项目**（非幻觉、非社区），但**不在 main 发布分支、未发布策略**。
- `microduck-MicroDock真机可行性预研-2026-11-06.md` 的事实内容基本准确，仅"官方"归属应精确为"官方 Playground（未合主线、未发布、sim-only）"。
