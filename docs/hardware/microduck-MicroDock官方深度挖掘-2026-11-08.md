# MicroDock 官方项目深度挖掘（源码级）

> 2026-11-08 深挖。源：本地 `.upstream/playground/hardware/microdock/` 与 `microdock-v2/`（官方 Pollen
> `pollen-robotics/microduck` 仓库的 Playground 实验项目，引用了真实的 issue #174/#470 与 `microduck_rl`
> commit `bae39f59`）。**本文档基于实际读到的源码、仿真脚本、训练 patch 与 7 份结果 JSON，不是只看 README。**
>
> ⚠️ 状态（官方自述）：**全部仅仿真验证，真机从未测过**；对接/转身/停走的触发逻辑是"在仿真里脚本化"的，
> 机器人 runtime 还没有这些功能。
>
> ⚠️ 本文档**取代**同日早些时候写的浅层参照 `microduck-MicroDock官方研究参照-2026-11-08.md`（那份没读源码）。

---

## 0. 项目文件全貌（哪些能直接复用 / 打印 / 复现）

```
playground/hardware/microdock/         # v1 站立倒车坞
  README.md              # 设计说明、BOM、装配、复现命令、velstand.onnx / alpha_sitstand.onnx 的 SHA-256
  sim/docking.py         # 对接仿真：接近→转身→倒车→停于USB上电（脚本化，非机器人代码）
  sim/back_patch.py      # 把"新版机背"（电池下沉+壳开口+下沉USB-C口）做成视觉网格
  sim/visuals.py, render_preview.py, render_gallery.py
  source/dock.py         # ★所有几何参数 + MuJoCo 碰撞片 + 磁吸模型 + 场景
  source/cad.py          # 把 dock.py 参数转成可打印 STL（manifold3d）
  source/plates.py, bambu_project.py   # Bambu P1S 打印盘 / 工程
  stl/*.stl  print/*.3mf # 5 个打印件（base/board/hood/keeper/tag）
  results/backin30.json  # 30/30 仿真对接结果（含每步 log）

playground/hardware/microdock-v2/      # v2 坐姿坞
  README.md
  training/butt_walk.patch              # ★把 Butt-Walk 任务加进 microduck_rl 的完整 diff（mdp.py + env cfg 全改）
  training/mdp_butt_walk.py             # 实际是 env cfg 的 import 包装（核心在 patch 内）
  training/microduck_butt_walk_env_cfg.py  # ★Butt-Walk 任务完整定义（61D obs / 14 act / 坐姿带状约束 / 脱坞磁吸力）
  sim/docking_seated.py   # 坐姿对接仿真（走→坐→scoot 后退→停于USB上电→doze/limp 睡去）
  sim/undocking_seated.py # 脱坞仿真（scoot 前出→站起→走开；或续接展示run）
  sim/latency.py          # ★把"训练时的延迟"注入仿真控制环（脱坞策略只有带延迟才挣脱磁铁）
  sim/scoot_eval.py       # 策略评测
  source/seated.py        # v2 几何参数（继承 dock.py，仅覆盖 z0/hood_float_y/hood_drop）
  source/build.py
  policy/scoot_dock.onnx  policy/scoot_undock.onnx  policy/experimental/scoot_dock_undock.onnx  # 官方训好的策略
  results/*.json          # 6 份结果（seated30 / undock30 / experimental_dock_undock / seat_friction /
                          #         undock_magnet / scoot_dock_commands）
  media/assembly/*.jpg, microdock_v2_assembly.pdf  # 装配图
```

**可直接落到 HD-1910 复刻的**：坞体 STL（需按复刻壳实测尺寸微调）、`dock.py` 全套几何与磁吸参数、
`butt_walk.patch`（任务加法模板）、三份 onnx 策略（**但须按 HD-1910 重训，见 §4 风险 R3**）。

---

## 1. v1 站立倒车坞（microdock/）

### 1.1 机构动作（README + docking.py + dock.py）
- 鸭走近 AprilTag → **约 24 cm 处原地转身 180°** → 用 `velstand` 以 `vx=-0.4` **倒车**入坞。
- 坞上 **浮动罩（hood）** 跨在机背电源键与指示灯之上（skid 在 |y|≥22.5mm 处落于机背，避开按钮和灯）；
  罩侧墙把机身夹正；磁性 USB-C 适配器（在罩内）对接鸭**背部的 USB-C 口**（口在电池上方壳开口里）。
- "停走"触发：**磁性头碰到适配器→USB 上电→鸭停走**（仿真里用 `dk.connected(err)` 判定，即 tip 在 adapter
  面 ±2.5mm / 轴向 -4~+2mm 内）。磁吸最后 1mm 由磁吸闭合。

### 1.2 关键几何参数（dock.py，单位 mm，来自"近期量产机照片估计"）
| 参数 | 值 | 含义 |
|---|---|---|
| `port_above_bat` | 4.8 | USB-C 口中心高于电池顶端（壳开口上沿约 4.5mm 高于壳边） |
| `notch_w` | 12.1 | 壳开口宽度（11.8mm 磁吸头刚好进得去） |
| `shell_back_x` | -47.13 | 磁吸头头部靠住的壳背位置（缝脊） |
| `port_recess` | 1.0 | USB-C 座面在壳面后方 |
| `button_xy / button_r` | (-28,13) / 4.6 | 电源键位置（罩 skid 须避开） |
| `skid_y` | 22.5 | 罩 skid 落在机背 |y|≥22.5mm 处 |
| `trunk_top` | 40.6 | 机背落点高度（|y|≈23–31） |
| `dock_x` | 81.5 | 对接完成时机身原点 x（板面在 trunk x=-81.5） |
| `z0` | 118.6 | 站立对接时机身原点高度（仿真测得） |
| `hood_float_y` | 12 | 罩横向浮动半幅 |
| `hood_drop / hood_lift` | 7 / 6 | 罩可下沉 / 上浮量 |
| `tip_w / tip_h / tip_out` | 11.8 / 6.0 / 3.4 | 磁吸头尺寸 |

### 1.3 磁吸模型（dock.py `magnet()` / 常量）
- `MAG_F = 4.0 N`（轴向吸力），`MAG_RANGE = 4.0 mm`（吸合范围），`MAG_LAT = 3.5 mm`（横向可达），
  `MAG_K = 250 N/m`（软对中力）。
- **注意**：这是仿真的"官方默认 4N"，**真实适配器吸力官方没测过**。

### 1.4 约束 / 不碰电源键
- 罩 skid 在 |y|<22.5mm 留空，按钮领圈（中心左 13mm、半径 5.8mm）与灯须落在内；仿真里检测 hood 是否压到
  `power_button`（`docking.py` 中 `pressed[0]` 计数）—— **30/30 全部 0 次触碰**。

### 1.5 仿真结果（results/backin30.json，seed 41/42/43 × 10）
- **30 / 30 对接成功，0 次压到电源键**。
- 每次落点在适配器各方向 **< 0.4mm**。
- 鸭子转身后能偏移 **≤32mm、≤7°**，被罩侧墙 + 浮动罩（最多横移 6.3mm）吸收。
- 起点 380–460mm、±40mm 横移、朝向 180±12°；磁吸建模为 4N 吸合 + 软对中。

---

## 2. v2 坐姿坞（microdock-v2/）

### 2.1 与 v1 的区别（README + seated.py）
- 同款坞，但鸭**先坐（官方 sitstand 策略）→ 再在座位上"屁股走"后退**（scoot_dock.onnx）入坞。
- 坐姿时机身比站立低约 **57mm**，板与罩相应下移：`z0=62.0`（v1 是 118.6）、`hood_float_y=20`（v1 12）、
  `hood_drop=12`（v1 7）。
- 新增一件 board 把罩压低 57mm；**罩/基座/keeper/tag 与 v1 通用**。
- 适配器高度 `adapter_dz=0`：坐姿策略坐平，适配器与口同高。

### 2.2 Butt-Walk 任务（训练配方，training/ 全读）
- **网络**：61D obs / 14 actions / 512-256-128 ELU（与官方 velstand 同构，actor 可热启动）。
- **指令**：`twist=[vx,vy,wz]`，全零=坐定（部署空闲）。**偏向后退**：`LIN_VEL_X_RANGE=(-0.10, 0.06)`，
  `ZERO_COMMAND_FRAC=0.2`（20% 全零指令=坐定休息），`ANG_VEL_Z_RANGE=(-0.30,0.30)`。
- **坐姿带**：`SEATED_Z=0.065m` 高斯，`SEATED_Z_SOFT=0.080` 单向 L1 上限，`SEATED_Z_MAX=0.095` 终止（站起=0.115，
  "站起来"=失败，因为走路比坐走容易）。
- **座椅摩擦 DR**：`SEAT_FRICTION_RANGE=0.3–1.0`，课程从 0.05–0.25 升到 0.25–0.7 再到 0.3–1.0（真实塑料壳在
  PLA/木地 ~0.3–0.5）。
- **头抬起**：头高斯 + `HEAD_L1_WEIGHT=5.0` + 终端 `HEAD_MAX_ERROR=0.8rad`（否则策略会把头低 85° 去压脚卸座）。
- **臀部离限位**：`HIP_LIMIT_WEIGHT` 默认 0（发的策略没开）；腿扭²可分阶段加。
- **脱坞（默认关）**：`UNDOCK_PROB=0`；`UNDOCK_F_STAGES` 磁吸吸力课程（0:0.5–1.5 → 900:2–6 N），
  `UNDOCK_YAW_K=2.0 N·m/rad`（罩对朝向的约束），`UNDOCK_CMD_S=5s` 前置前进指令。
- **课程上限**：`CURRICULUM_CAP`——v2 继承 sitstand 的在 1500 迭代硬化的课程会让 butt-walk 在 1400 崩溃，发的策略是
  **1400 迭代 checkpoint**。

### 2.3 脱坞物理（butt_walk.patch 内 `mdp.py` 新增函数）
- `UNDOCK_PORT_B=(-0.05053, 0, 0.0265)`、`UNDOCK_TOP_B=(-0.030, 0, 0.0406)`（trunk_base 坐标系，m）。
- `magnet_axial_force`：磁吸 + 适配器面阻尼止挡（k_stop=2000 N/m, c_stop=40 N·s/m，前瞻 0.01s 防弹跳）。
- `hood_ceiling`：罩顶在机身原点上方上限（随唇口外滑上升，最多 6mm 抬升）。
- `hood_yaw_torque`： docked 朝向阻尼（3° 自由游隙，外滑按 7°/11mm 打开，20mm 外自由）。

### 2.4 v2 仿真结果（results/，seed 41/42/43 × 10，**全仿真**）
| 文件 | 内容 | 结果 |
|---|---|---|
| `seated30.json` | 坐姿对接 | **30/30 入坞，0 压键** |
| `undock30.json` | scoot_dock + scoot_undock | **30/30 入坞 / 脱困 / 出坞 / 站起 / 走开**；release_s_max=1.34s，scoot_max_yaw=8.4°，stand_max_hood_force=5.6N |
| `experimental_dock_undock.json` | **单一策略 dock+undock** | **30/30 全部成功**；release_s_max=1.86s，scoot_max_yaw=7.4° |
| `seat_friction.json` | 座椅摩擦鲁棒 | mu=0.3 → 10/10；mu=0.8 → 10/10（训练 0.25–0.7，主批 0.45） |
| `undock_magnet.json` | 磁吸力鲁棒 | mag=6N → 10/10 全成（release_s_max=5.26s）；**mag=8N → 仅 1/10 站起/走开，stand_force=92.6N（罩卡死）** |
| `scoot_dock_commands.json` | 策略指令跟踪 | 8 组指令下 z≈60–64mm、pitch≤±4.6°、roll≤±1.1°、**从不跌倒**、头保持低位 ~80mm |

**结论**：v2 仿真极强——尤其 `scoot_dock_undock.onnx` 单策略完成"进坞+脱坞+站起+走开" 30/30。但**全部是仿真**。

---

## 3. 两条我之前没掌握、对移植最致命的风险（深挖新发现）

### 3.1 延迟耦合（sim/latency.py）—— 脱坞策略**只有带训练延迟才挣脱磁铁**
- 训练时执行延迟：伺服目标 **3–6 个物理步（5ms/步）迟到**、关节速度 **1 个控制步迟到**、IMU（陀螺/重力）**0–1 步迟到**。
- `latency.py` 把这套延迟注入仿真控制环；脱坞仿真 `undocking_seated.py` 默认调用它。
- 官方明写：**"the undocking policy only breaks free of the magnet with them [the latencies]：它按延迟设定的节奏推。"**
- **对 HD-1910 的含义**：你的 feetech HLS 伺服延迟特性与官方 BAM XL330 **不是一回事**（plant 不同）。即使 R1/R2/R3 全过，
  若实机延迟与训练不一致，脱坞可靠性会塌。而且**官方自述真机延迟没测过**。→ 这层必须在 HD-1910 上重测延迟、必要时重训。

### 3.2 磁吸吸力采购上限（undock_magnet.json）—— 适配器不能太强
- 仿真默认 4N；实测 6N 仍 10/10 成功（只是脱坞更慢，release_s_max=5.26s）；**8N 时脱坞几乎全失败**（仅 1/10 站起，
  罩上力 92.6N）。
- 官方**没测过真实适配器吸力**（BOM 上的是 Auravale 240W 磁吸 USB-C，标称吸力未给）。
- **对 HD-1910 的含义**：买磁吸适配器时**必须确认吸力 ≤ ~6N**（最好 4N 左右）。吸力大反而脱不开——这是反直觉的坑。

---

## 4. HD-1910 移植门禁（R1/R2/R3 + 上述两条）

| 门禁 | 内容 | 状态 |
|---|---|---|
| **R1 充电电路**（硬 gate） | beta 板 USB-C 仅到 5V 轨、**不充电**；坞上只会亮灯。须改板或换量产主控（issue #174）。 | 须真机实测"送 5V 看电池电压是否升" |
| **R2 几何对位** | dock.py 全部几何来自"量产机照片估计"（port_above_bat/notch_w/button_xy 等）；复刻壳须**真机实测**再调。 | 须量复刻机背 USB-C 口 / 电池 / 按钮位置 |
| **R3 策略移植** | scoot onnx 是 **B 代（官方 MicroDuck）在 bae39f59 训练**，跑在 BAM XL330 作动模型上；HD-1910 是 feetech HLS → **须按 HD-1910 重训**（任务加法见 butt_walk.patch）。 | 须重训 + 验证 |
| **R4 延迟耦合** | 脱坞策略依赖训练延迟；HD-1910 实机延迟特性未测，与 BAM 不同 → 重测 + 必要时重训。 | 须量实机延迟 |
| **R5 磁吸吸力** | 适配器吸力须 ≤ ~6N（8N 脱不开）。 | 采购时确认 |

## 5. 官方明确"没做 / 没测"的清单（别当成已解决）
- **真机从未测过**（v1 README 明写 "designed and tested in simulation only; not yet tried on hardware"）。
- **机器人 runtime 没有** tag 检测、转身、停于 USB 上电这三件事——它们在仿真里是脚本化的。落到真机要自己在 robotd 实现。
- **机内充电行为未公开**（issue #470）；"带电站立时能否充电"未知。
- **真实适配器磁吸吸力未测**；**真实机器人延迟未测**。
- v1 的 "11-05 更新"：早期 keeper 太短会从板窗滑出，已改 32mm + 1.75mm 耗材锁；board 加了理线夹。

## 6. 复现命令（官方给出，需 microduck_rl@bae39f59 + microduck-policies）
```bash
# v1
uv run python hardware/microdock/sim/docking.py --seeds 41,42,43 --n 10 --stop_gap 0 --out backin30.json
# v2 对接
uv run python hardware/microdock-v2/sim/docking_seated.py --seeds 41,42,43 --n 10 --out results.json
# v2 脱坞（带训练延迟）
uv run python hardware/microdock-v2/sim/undocking_seated.py --seeds 41,42,43 --n 10 --mag 4 --out undock.json
```
验证环境：mujoco 3.10.0 / onnxruntime 1.24.4 / better-actuator-models 1.0.1；
velstand.onnx SHA-256 `2fc7f8ee…d5ccf492`、alpha_sitstand.onnx `a6f102d9…06fc254`。

## 7. 给 HD-1910 的最小行动序列（若真要做）
1. **先测 R1**：对 beta 板 USB-C 送 5V，量电池电压是否上升 —— 不过则只是停靠演示。
2. **量 R2**：复刻机背 USB-C 口 / 电池上端 / 电源键相对位置，填回 dock.py。
3. **测 R4**：量 HD-1910 实机伺服延迟（指令→到位）分布。
4. **挑 R5 适配器**：确认磁吸吸力 ≤ 6N。
5. **重训 R3**：用 butt_walk.patch 把 Butt-Walk 任务加进你的 microduck_rl，在 HD-1910 plant 上训。
6. **在 robotd 实现** tag 检测 + 转身 + 停于 USB 上电 + 坐姿对接调度（仿真里是脚本，真机没有）。
```
