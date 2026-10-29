# MicroDuck HD-1910 软件方案（采集开源长处）

日期 2026-10-26。硬件定案：**飞特 HD-1910-C001 ×15**（见 `../hardware/microduck-采购清单.md` §7、
`../archive/microduck-国内自制方案.md` 已证伪段）。本文只定**软件怎么拼**，不重复 BOM。

**工作区入口**：[根目录 `README.md`](../../README.md)（文档地图 + 命令）。  
**真机清单**：[阶段 C](microduck-HD1910阶段C软件清单.md)。**工具**：[tools/hd1910](../../microduck-software/tools/hd1910/README.md)。  
**主线执行计划**：[§8](#8-主线执行计划2026-10-28-定hd1910-为唯一主线)（2026-10-28 定：HD1910 唯一主线、偏航为首要缺口）。  
**10-27 纪要**（IMU / 组装机 / 场景 / kissqy·XGO）：[microduck-2026-10-27裁决与场景纪要.md](microduck-2026-10-27裁决与场景纪要.md)。  
**2026-10-27 裁决纪要**（场景 / IMU / 组装机 / kissqy↔XGO）：[microduck-2026-10-27裁决与场景纪要.md](microduck-2026-10-27裁决与场景纪要.md)。

### 当前进度（滚动）

| 项 | 状态 |
|---|---|
| 植物 live | OpenMicroDuck **m5**（`kp_fw=32`）；A/B 后已切回 |
| GPU smoke 64×5 | ✅ `hd1910_smoke_1026_gpu2` |
| 探索 1024×2000 | ✅；P-walk **未过**（ratio≈0.34） |
| 探索 4096×2000 | ✅；P-walk **过**（vx0.4 ratio≈**0.62**）；ONNX `out/hd1910_explore_4096x2000_1026_it1999.onnx` |
| 续训 4096→≈6000 | ✅ `model_5999.pt`（`…_to6000_1027`）；P-walk **过**（vx0.4 median/cmd≈**0.76**）；`translates_forward` ✅（1999 时否）；仍 `not_sideways` ❌ |
| A/B m5↔m6 1024×500 | ✅ 两腿 `cuda:0`；短训均 **100% fall**（500 不够判植物） |
| 探索 8192×2000 | ⛔ 已停（~13/2000）；本机 8GB 上 ~100 s/iter、显存顶满，非甜点 |
| 飞特 m6 | JSON+别名就绪；**勿整包装** ftservo-bam；长训仍主 **m5** |
| ONNX + parity（5999） | ✅ `out/hd1910_resume_4096_to6000_1027_it5999.onnx`；parity max\|Δ\|≈**2.5e−6** |
| 彩排（5999） | 名义/低电/高电 **过**；`train_lag3/4/6` 仍挂（与 1999 同类；CPU MuJoCo±delay 非训练同仪） |
| 下一步 | **人：阶段 0 下单**；Velocity 不必再长训。可选新场景 **StandUp**（`tools/hd1910/explore_standup.sh`，4070 Ti：先 1024×1000） |

---

## 0. 一页结论

| 层 | 采用谁的 | 不采用谁的 |
|---|---|---|
| **训练框架** | 官方 `pollen-robotics/microduck_rl`（mjlab 1.3 / PPO / 61×14） | `tailong-wu/microduck-mjbatch`（仅作历史脚手架） |
| **执行器植物** | **OpenMicroDuck 台架 m5**（已在本仓 `tools/bam_params/hd1910/`）作**当前可跑基线**；目标升级到 **飞特官方 BAM** `feetech_hd1910_7_4V` m6 | 陆吾 `1910_m6.json`（`actuator: sts3215` 错标） |
| **任务适配参考** | `qiaosiyi/microduck_rl_hd1910`（33 任务全改、质量 +3 g×15、公开 iter2000） | 其 DcMotor「规格书临时模型」——只作对照，不作主植物 |
| **真机运行时** | `kissqy/Microduck-kissqy` control.43 + R17 V167（或 fanhao 镜像 fork） | 官方 `pollen-robotics/microduck` 原版（只认 Dynamixel） |
| **机械/CAD/装配** | `fanhao375/microduck-replica` 飞特版 `-FT` | XL330 舵盘件 |
| **评估协议** | 本仓已有 `eval_velocity_in_sim` / 彩排 / parity（契约 61/14 不变） | 换植物后旧 XL330 ckpt **不可热插拔** |
| **部署契约** | obs 61 / act 14 / 50 Hz / ONNX + normalizer | 改 obs 维数的实验（Walk These Ways 式）— 二期再说 |

**原则**：契约不动；植物可换；改上游只做**可逆覆盖**，不永久 patch 官方 blob。

**铁律（2026-10-26 用户裁定）**：遇事先查资料，再改代码 / 下结论。
落地见 `.cursor/rules/look-up-first.mdc` 与 `workbuddy-history/memory/MEMORY.md` §0。

---

## 1. 开源长处对照（采什么）

| 来源 | ★ / 状态 | 采 | 弃 / 慎用 |
|---|---|---|---|
| **官方 microduck_rl** | 2645★ | 任务定义、奖励、课程、export/infer、AGENTS.md 方法论 | XL330 BAM kwargs（`motor_name=xl330`, `kp_fw=200`） |
| **qiaosiyi/microduck_rl_hd1910** | 10★ | 全任务 HD1910 接线清单、质量修正算法、smoke 矩阵、公开权重作**负对照** | `datasheet_based_provisional` 植物；HOME 开环 8/8 摔是已知事实 |
| **飞特 ftservo-bam** | Gitee 官方 | `feetech_hd1910_7_4V` m1–m6、`kp=32`、`error_gain=0.163`、mjlab 集成 | PyPI `better-actuator-models` **不含** HD1910，必须本地装 Gitee 克隆 |
| **OpenMicroDuck 辨识** | 本仓已镜像 | 72 摆锤 + 48 腿实测 → m5：`kt=0.692`, `R=3.75`, delay 25.3 ms | 5 V 台架口径；上 7.4 V 时 vin 改、kt/R 可沿用 |
| **kissqy** | 291★ | 真机镜像、中控、固件、采购账单、抖动修复（D=0） | 许可：原创部分**个人非商业**；陆吾参数勿当主植物 |
| **fanhao375/microduck-replica** | 1356★ | `-FT` CAD、BOM、装配教程、踩坑、训练工程打包 | 早期「待步态验收」记录；以当前 README 真机演示为准并自验 |
| **zhuoligetu123/hd1910m** | 28★ | 四模型 + APK 作部署对照 | **原始接线图作者自标有错**，勿照抄 |
| **本仓已有工具** | — | `tools/bam_actuators.py`、`tools/plant.py` HD1910 SPECS、`eval_velocity_in_sim`、`train_velocity.sh` | `walk_std004` XL330 权重（交付物归档，不上 HD1910 机） |

### BAM 参照链（纪律）

```
hd1910_our_measured_m*     # 终点：自己台架（阶段 0 之后）
hd1910_ftservo_official_m6 # 目标强先验：飞特 Gitee（装好后切换）
hd1910_openmicroduck_m5    # 当前基线：本仓 tools/bam_params/hd1910/m5.json  ← 先跑通
hd1910_luwu_1910_m6        # 历史对照 ONLY，禁止当训练主植物
```

---

## 2. 仓库布局（本工作区）

```
microduck-software/
  tools/
    bam_actuators.py          # 已有：注册 hd1910 / hl2915 到 BAM
    bam_params/hd1910/m5.json # 已有：OpenMicroDuck 台架
    plant.py                  # 已有：HD1910 SPECS（CPU 植物）
    hd1910/                   # ★ 本方案新增
      plant_spec.py           # 单一真相：数字 + 出处
      apply_to_live.py        # 可逆覆盖 site-packages 植物
      smoke_train.sh          # 64×5 冒烟
      restore_xl330.sh        # 一键恢复 XL330 植物
  .upstream/
    microduck_rl-develop/     # 官方任务包快照（对照用）
    j_hd1910_*.json           # 辨识原文
    kissqy/                   # 真机参考摘录
.upstream/dew_repo/           # 主线文档与 XL330 交付归档（flat-walk）
```

训练仍走 `.venv-mjlab` + `Mjlab-Velocity-Flat-MicroDuck`；换植物 = 换
`FrictionDRBamActuatorCfg` 的 `json_path` / `kp_fw` / `vin_*`，**不改任务 ID、不改 obs**。

---

## 3. 植物切换（当前可执行）

覆盖点：`site-packages/mjlab_microduck/robot/microduck_constants.py` 里
`_BAM_ACTUATOR_KWARGS`（与上游 `microduck_rl-develop` 同源）。

| 键 | XL330（现状） | HD1910（目标基线） |
|---|---|---|
| `motor_name` / `json_path` | `xl330` + bundled m6 | **`json_path` → `tools/bam_params/hd1910/m5.json`** |
| `kp_fw` | 200 | **32** |
| `vin_range` | (6.5, 8.2) | (6.5, 8.2) 保持 |
| `delay_*_lag` | 3–6 | 3–6（25.3 ms ≈ 1.3 控制拍，落在区间内） |

质量 +3 g×15、齿隙 XML：**二期**（对照 qiaosiyi），冒烟不阻塞。

> ### ✅ `kp_fw=32` 已查明出处（2026-10-29 结案）：它是**出厂默认值**，不是运行值
>
> **32 的确切出处 = BAM 官方 `STS3215Actuator` 的构造默认值**。源码（Apache-2.0，
> `.upstream/bam-62bd8ce.../bam/feetech/actuator.py`）：
> `super().__init__(testbench_class, vin=7.4, kp=32, error_gain=0.166, max_pwm=0.97)`。
> 本仓 `tools/bam_actuators.py` 的 `HD1910Actuator` 当初照抄了这个 32。
>
> 四条来源交叉证实「32 = 出厂未干预值」：
>
> | 来源 | 内容 |
> |---|---|
> | BAM 官方源码 | `STS3215Actuator` 默认 `kp=32`（Feetech 舵机的固件默认 P） |
> | 真机只读体检（`replica` 上机实测 §97） | 15/15 颗 EEPROM 与 SRAM 的 **P/D/I 都是 32/40/0** |
> | kissqy 运行器表格 | 写 SRAM 50/51 = **P5/D20**，结束**恢复原值 32/40** |
> | 社区踩坑记录 | 「HD-1910 出厂 EEPROM 是 **P32 / D40 / I0**」 |
>
> 而**训练侧 + 部署侧实际生效的是另一组值**（相差 6.4~10 倍）：
>
> | 来源 | 值 |
> |---|---|
> | kissqy config diff（12 个 task 全一致） | studio 侧 HD1910：`kp_fw=5.0` + `hd1910_m6.json` |
> | kissqy 部署（V164「部署合同」、V167） | HOME 上力写 **P=5 / D=0 / 转矩 1000** |
> | 社区实机调参结论 | 「P 越大越晃：P5 晃 56°/s、P3 晃 30°/s」，现用 **P3 / D0 / 转矩 700** |
>
> 物理含义（BAM 控制律 `duty = err · kp · error_gain`，`error_gain≈0.163`、`err` 单位为 rad；
> 单位链路见 Open Duck Mini 辨识文档 `ε_f = ε·4096/2π`、`λ = Kp·Kg·ε`）：
> 产生 `duty=0.3` 需要的位置误差 **P=32 → 3.3°**，**P=5 → 21.1°**，P=3 → 35.2°。
> 即 P=5 的腿在物理上「很软」，策略必须在这种软动态里学行走。
>
> #### ✅ 已裁决（2026-10-29）：**P3 用 `kp_fw=5`，并同时换到官方控制律**
>
> 32 与 5 不是「紧一点/松一点」的偏好，是**两种不同物理特性的机器**。本仓现有全部 HD1910
> 数字（`§13` A/B 的 vx0.109/摔 100%、`model_5999` 的 vx0.2989 与 `error_vel_yaw`1.164、
> m5/m6 A/B 的 `terminated_frac=1.0`）**都是在 P=32 这个植物下测的**，换 kp 后全部作废需重训。
>
> **目标植物 = `hd1910_kp5`**（`tools/bam_params/hd1910/official_m6_stslaw.json`），三条均有出处：
>
> | 层 | 取什么 | 出处 |
> |---|---|---|
> | 参数（kt/R/摩擦） | 飞特官方 HD1910 ID @7.4V、m6 | 上游 `ftservo-bam`，与 2S 电压匹配 |
> | **控制律** | **官方 `STS3215Actuator`** | 只把 json 的 `actuator` 改为 `"sts3215"`，即继承官方限速 5.2155 rad/s、`max_pwm=0.97`、`error_gain=0.166` |
> | `kp_fw` | **5.0** | kissqy config-diff 12/12 task + V164/V167 部署合同 + 社区实机结论 |
>
> **关键实现细节**：`Model.load_parameters_from_dict`（BAM `model.py:229-239`）会把 json 里
> **同名键覆盖类 `initialize()` 设的值**。所以 json **刻意不写** `max_velocity` 与
> `error_gain_ratio` —— 写了就拿不到官方限速。这正是陆吾那份的问题：它写了
> `max_velocity: 100`（≈5730°/s），把官方 5.22 rad/s 的限速**悄悄拆掉了**。
>
> 验证手段（不要靠读 json 猜）：`.venv-mjlab/Scripts/python.exe tools/hd1910/probe_plant_law.py
> --json <params.json> --kp-fw 5`，它打印实际生效的 `law_class` / `kp` / `max_velocity` / `max_pwm`。
>
> **执行顺序（不要提前烧 GPU）**：阶段 0 台架实测 → 用真机 kt/R/死区/齿隙回填 json → **一次**重训。
> 若决定同时治偏航（`rel_heading_envs > 0`），合并进同一次重训。
>
> 反向选项（保持 32、部署时自己在 SRAM 写 P=32）**没有任何社区路线走过**，且已知实机 P 大会颤，已否决。
>
> #### 同时发现两个同样重要的差异（一并入 P3）
>
> 1. **控制律不同**。官方 `STS3215Actuator` 有 `q_target_smooth` 内部限速
>    （`default_max_velocity = 3400·2π/4096 = 5.22 rad/s ≈ 299°/s`）且 `max_pwm=0.97`；
>    本仓自写 `HD1910Actuator` **完全没有限速**、`max_pwm=1.0`、多了 `max_current` 限幅。
>    ⇒ 我们的仿真舵机能「瞬移」，真机会按梯形规划走，是独立的 sim2real 缺口。
> 2. **模型阶数**。kissqy 用 `hd1910_m6.json`（m6），本仓用 `m5.json`。本地已有陆吾
>    `1910_m6.json`（`.upstream/l_1910_m6.json`，`actuator:"sts3215"`、`max_velocity:100`、
>    `error_gain_ratio:1.3217`、`command_delay:0.006`）。
>    ⚠️ 既往判定「陆吾 m6 因 `actuator` 误标 sts3215 而禁用」**是误判**：BAM 的 `actuators`
>    注册表里 Feetech 唯一合法键就是 `sts3215`，反倒是本仓的两个 plant 名是**自己注册**的。
> 3. ⚠️ **10-26 那次 m5 vs m6 A/B 无效**：两者均在 kp=32 下 `terminated_frac=1.0`（全摔），
>    当时记的「差不多」实为「两个都废」，不构成对照。

命令（实现见 `tools/hd1910/`）：

```bash
cd microduck-software
# 复现已归档数字 → m5 + kp_fw=32
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910
# P3 正式重训目标 → 官方 m6 + 官方控制律 + kp_fw=5
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_kp5
# 回 XL330（走 microduck_constants.py.xl330.bak 恢复路线）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330

# 开关本身的回归自检（含负对照：改坏 kp 后闸门必须变红，最后还原现场）
.venv-mjlab/Scripts/python.exe tools/hd1910/selftest_plant_switch.py

# 冒烟：64 env × 5 iter —— **必须 GPU**（cuda:0）；Windows 固定 MUJOCO_GL=glfw（勿 egl）
bash tools/hd1910/smoke_train.sh

# 评估（沿用现有脚本，checkpoint 换成 HD1910 run）
.venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py \
  --checkpoint logs/.../model_*.pt --num-envs 32 --seconds 8 --cmd-vx 0.4

# 恢复 XL330（对照实验用）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330
```

训练铁律：正式训练走 **GPU `cuda:0`**；CPU 只做探针。见 `.cursor/rules/look-up-first.mdc`。


---

## 4. 分阶段交付

### 阶段 A — 今天～2 天（仿真植物跑通）

1. ~~`apply_to_live.py --plant hd1910` + smoke 64×5~~ **已过（2026-10-26）**  
   - plant gate：`detected=hd1910`，`kp_fw=32`，live sha16 `f3d62a7a51de2bfe`  
   - GPU smoke：`hd1910_smoke_1026_gpu2`，`device=cuda:0`（RTX 4070），64×5，iter≈1.34s，无 NaN  
   - 戳记：`out/plant_*.json` / `out/runmeta_hd1910_smoke_1026_gpu2.json`  
   - Windows 坑：mjlab `train.py` 曾硬编码 `MUJOCO_GL=egl`（本机非法）→ 已改 win32→glfw；空 `CUDA_VISIBLE_DEVICES` 会逼 CPU，smoke 脚本会 unset  
2. 探索档  
   - ~~1024×2000~~ **已完** `hd1910_explore_1024x2000_1026`（`cuda:0`，model_1999）——摸底，**未过 P-walk**  
   - ~~4096×2000~~ **已完** `hd1910_explore_4096x2000_1026`——**P-walk 过**（ratio≈0.62）  
   - **8192×2000**（RL_duck §2.1 甜点）——进行中 `hd1910_explore_8192x2000_1026`  
   - 量级对照仍是 ~590 M 环境步（RL_duck §3.1）；本轮 8192×2000 ≈ 393 M step（24×8192×2000）  
3. 同协议评估 32env×8s：  

   | run | vx=0.4 ratio | no_fall | 备注 |
   |---|---|---|---|
   | 1024×2000 | 0.34 | ✅ | 未过 P-walk |
   | **4096×2000** | **0.62** | ✅ | **过闸**；yaw 仍漂；ONNX 已导出 |
   | A/B m5/m6 ×500 | ~0.13 / 0.14 | ❌ 100% | 短训不可比植物 |

4. 文档：runmeta 写 `plant=hd1910_openmicroduck_m5`（smoke / explore 已写）

### 阶段 B — 本周（对齐官方 BAM）

1. ~~克隆 `gitee.com/ftservo/ftservo-bam`~~ **已做**（`.upstream/ftservo-bam` @ `4f7c0b0`）  
   - ⚠️ **不能**把 ftservo-bam 整包 editable 盖掉训练用 bam：官方 `BamActuatorCfg` 把  
     `vin_drop_gain_range` 改成了 `vin_drop_resistance_range`，microduck 植物立刻  
     `unexpected keyword`（2026-10-26 实测）。  
   - **现行 pin**：`.venv-mjlab` editable → `.upstream/bam-62bd8ce…`（`vin_drop_gain_range`，与 4096 训一致）  
   - 官方仓只取：**参数 JSON + 对照**；控制类暂走本仓 `tools/bam_actuators.HD1910Actuator`  
2. ~~大小写别名~~ **已做**：表键 `HD1910` vs JSON `hd1910` → `bam_actuators` 双注册  
   - 本地参数：`tools/bam_params/hd1910/ftservo_official_m6.json`（actuator=`HD1910`）  
   - ftservo clone 内 `actuators.py` 亦补了小写键（仅参考，未装进 venv）  
3. ~~切植物 m6~~ **A/B 时已切过**；长训主线 **切回 m5**（`apply_to_live.py --plant hd1910`）  
4. ~~A/B 短训~~ **已完** `ab_train.sh both`（1024×500，seed 42）  
   - 结果：m5/m6 **均 100% fall、ratio~0.13**——500 iter 不够分离植物；**不以短训改主植物**  
   - 参数表：`tools/hd1910/bam_param_compare.md`  
   - 待 8192/加长后再做 **同量级** m6 对照  

### 阶段 C — 与硬件并行（真机栈）

清单正文：`microduck-HD1910阶段C软件清单.md`（2026-10-26 并行起草）。

1. 部署侧跟 kissqy V167 / fanhao 镜像（不自写 robotd）——入口与许可已写入清单 §1  
2. 阶段 0 台架：**URT-2（优先）或 URT-1** + 1 颗（**勿用 U2D2**），事务 ≤5 ms，复核 kt/R——闸门见清单 §3 / `stage0_software_prep.md`。HD-1910 接 **TTL**；**外电直供舵机 V/G，URT 只共地+信号，勿灌 V1**（出处：`.upstream/r_踩坑记录.md`）  
3. ONNX export + parity ✅；部署彩排入口 `tools/hd1910/rehearse_hd1910.py`（m5 / kp_fw=32）  
4. 有整机后再做 sim2real；仿真结论不得单独宣称「真机已会走」

### 阶段 D — 能力补强（可选，植物稳定后）

- 低速死区：QRC 式接触计数 + 自适应 σ（见既有参考资料清单）  
- 质量/齿隙：合并 qiaosiyi XML 修正  
- head_pose 冻结评估：补交互维度

---

## 5. 明确不做

1. 不把现有 `walk_std004_1250`（XL330）部署到 HD1910 真机  
2. 不用陆吾 m6 当训练主植物  
3. 不改 obs_len / action_len（一期）  
4. 不自写飞特总线 daemon（用 kissqy/fanhao）  
5. 不以 qiaosiyi 规格书 DcMotor 替代 BAM  

---

## 6. 成功判据（软件侧）

| 闸门 | 通过条件 |
|---|---|
| P-plant | `apply_to_live --check` 回读 `json_path` 含 `hd1910` 且 `kp_fw==32` |
| P-smoke | 64×5 结束、无 NaN、写出 ckpt |
| P-walk | 32env×8s cmd 0.4：`no_fall` 且 ratio≥0.5（探索档下限，非交付线） |
| P-meta | runmeta 含 plant 指纹 + bam 参数 sha256 |
| P-revert | `--plant xl330` 后 cfg sha 回到官方 XL330 口径 |

交付线（ratio≥0.75 等）等阶段 A 出数后再钉，避免空定门槛。

---

## 7. 与旧文档的关系

| 文档 | 关系 |
|---|---|
| `../archive/microduck-国内自制方案.md` | 硬件选型已过时（S288）；**软件跟本文** |
| `../hardware/microduck-采购清单.md` §7 | 硬件花钱顺序；本文管软件 |
| `microduck-最优方案.md` | 曾推 HL-2915；**用户已定 HD1910**，HL 仅作对照 |
| `.upstream/dew_repo/docs/05-flat-walk.md` | XL330 交付档案保留；新实验进 HD1910 runmeta |

---

*依据：本仓 `tools/plant.py` / `bam_actuators.py` / OpenMicroDuck 表征 JSON；
qiaosiyi、kissqy、fanhao、ftservo-bam、LuwuDynamics 公开 README；检索日 2026-10-26。*

---

# 8. 主线执行计划（2026-10-28 定：HD1910 为唯一主线）

## 8.0 今天读到的现状（以实测读数为准，勿再翻旧结论）

依据：`microduck-software/out/eval_hd1910_resume_4096_to6000_1027/vx040.json`
（ckpt `logs/.../microduck_velocity_hd1910/2026-10-27_08-37-16_hd1910_resume_4096_to6000_1027/model_5999.pt`，
32 env × 8 s，cmd 0.4，solver 100/50）

| 读数 | HD1910 `model_5999` | XL330 `walk_std004_1250`（冻结档案，仅参照） |
|---|---|---|
| vx mean / ratio | 0.2989 / **0.747** | 0.3158 / 0.79–0.81 |
| 摔倒率 / upright min | 0.0% / 0.9953 | 0.0% / 0.9940 |
| `error_vel_xy` | 0.2016 | 0.1590 |
| **`error_vel_yaw`** | **1.164 rad/s** ⇦ 差 3.4× | 0.342 |
| 净位移比 `dx_over_expected` | **0.359** | 0.662 |
| `abs_dy_body_median` | **0.899 m** | 0.784 m |
| 闸门 | 11 PASS，`not_sideways` ❌ | 12 PASS |

**主干结论（≠ 旧结论）**：HD1910 上不需要「为了会走路」去重训 —— 它已经在走。
**真缺口不是前进速度，是它在往旁边漂**：体坐标 vx 达标 0.75，但净位移只有 0.36×，
8 s 横移 0.90 m，偏航误差是 XL330 那版的 3.4 倍。

> 纠错备案：2026-10-28 上午曾据「换 plant ⇒ 必重训」推断 HD1910 需要重训，
> 那是漏读本文 §0 进度表的错话。HD1910 已于 10-26/27 完成 4096×2000 + 续训至 6000。

**范围裁定**：XL330 系（`artifacts/flat_walk/`，含 `walk_std004_1250.onnx`）**冻结为档案**，
只能作跨 plant 参照，不作目标值、不可热插拔到 HD1910。两条线的数字**不许横比**，
比也只能说「不同任务的参照」（参照 `.workbuddy/memory/MEMORY.md` §8）。

## 8.1 为什么现在不急着长训

两项输入还没到位，先别把 GPU 投进去：

| 阻塞项 | 现状 | 影响 |
|---|---|---|
| **舵机参数不是实测** | `m5.json` = OpenMicroDuck 社区拟合（**vin 5 V** 标定）；`ftservo_official_m6.json` = 飞特官方（**vin 7.4**）；两者 R 差 21%、kt 差 18%（对照表 `tools/hd1910/bam_param_compare.md`） | 我们用电是 **2S 7.4 V** ⇒ 回填前**默认倾向官方 m6**；现在投长训有可能等于烧给一套错参数 |
| **A/B 已经做过且无效** | `tools/hd1910/ab_train.sh` 1024×500 两条腿**都 100% fall**（500 轮判不了植物） | ⛔ **别重复这个实验**；要 A/B 就 ≥2000 轮，或干脆等实测 |

结论：**先用本地 4070 做几乎免费的诊断（P2），把 GPU 花在实测参数落地之后的那一次重训上。**

## 8.2 阶段表

### P0 · 采购与上电（人，≈¥245–324）

- 采购：`docs/hardware/路线B-HD1910-今日下单清单.md`（今天只买阶段 0 五项）
- SOP：`microduck-software/tools/hd1910/stage0_software_prep.md`
- **G0 闸门**：ping 通 → 拉到 1 Mbps → **50 Hz 事务 ≤5 ms 且 0 CRC** →
  **打开出厂默认关闭的过流/过压保护** → 额定 0.36 N·m 连续 60 s 外壳 <60 ℃ → 确认 **reg50 P=32**
- 不过就换货，别买齐 15 颗

### P1 · 真机辨识 → 回填（本机，半天）

- 量 kt / R / 死区 / 齿隙 / 空载与堵转电流（`tools/hd1910/urt1_bench.py`）
- 产出 `tools/bam_params/hd1910/hd1910_measured_<date>.json`，用 `apply_to_live.py` 装成新 plant
- **G1 闸门**：kt/R 落在 m5 与官方 m6 之间（偏离 >20% 先查接线与标定，不信单点）；
  plant 记录（`out/plant_*.json`）写出该 json 的 sha256

### P2 · 修偏航（首要缺口：先诊断，再烧 GPU）本机 4070，纯评估，¥0

**状态：G2 已达一半（2026-10-28 实测，¥0，本机 4070）。**

对象 `model_5999.pt`（HD1910）；cmd 0.4 / 32 env / 8 s / solver 100/50；**seed 11·22·33 三次重复**。
产物 `artifacts/flat_walk/evals/p2_yaw/hd1910_5999_vx040_s{11,22,33}.json`。

| | seed 11 | 22 | 33 |
|---|---|---|---|
| vx / ratio | 0.303 / 0.76 | 0.306 / 0.77 | 0.294 / 0.74 |
| error_vel_yaw (rad/s) | 1.18 | 1.20 | 1.21 |
| **signed yaw drift (deg/s)** | **+2.52** | **−1.99** | **−1.08** |
| frac 同号 / frac>0 | 0.53 / 0.53 | 0.47 / 0.53 | 0.53 / 0.47 |
| signed dy (m) | −0.27 | +0.17 | −0.21 |
| dx 比（净沿初始航向） | 0.21 | 0.13 | 0.19 |
| path_dx / 摔率 / upmin | 2.44 / 0% / .9955 | 2.47 / 0% / .9958 | 2.28 / 0% / .9958 |

**① 头号假设 symmetry 被证伪。** 三次符号翻转、均值 −0.18 deg/s、同号率 0.51 ≈ 抛硬币
⇒ **不是左右结构性不对称**，启用 symmetry 增强治不了这个缺口（不必为它动 GPU）。
排除方式是**看符号而不是看大小**：脚本原先把 yaw drift 取了 `.abs()`，符号被抹，答不了这题。

**② 真机理 = 航向随机游走。** 它能走（path_dx 2.3–2.5 m、体坐标 vx 0.75），但航向无反馈地扩散
（|drift| 中位 13–17 deg/s，极值 ±43），净沿初始航向的位移只剩 **13–21%**。
定量支持（96 env）：`sin(dpsi)/dpsi` 预测 vs 实测 **corr +0.55**、量级同阶（预测 1.04 vs 实测 0.70；
单一匀速转弯模型偏乐观，真实是游走轨迹）。

**③ 为什么它根本没有"保持航向"这门本事 —— 查源码，不是推测：**
`microduck_velocity_env_cfg.py:643` 明写 **`command.rel_heading_envs = 0.0`** ⇒ 训练中**零个** env
练过航向闭环，wz 全程开环采样自 `(-1.0, 1.0)`。
⚠️ **别照抄 mjlab 官方默认的 0.3**：通用文档不等于本任务（这条差点是第 4 次「拿通用资料套自家 cfg」）。

**④ 副作用 —— 本仿真栈不可逐位复现，已证实并有官方依据：**
同 seed ⇒ **初始条件逐位相同**（yaw0 = 38.8096 / −110.9149 / −12.9005 三次一致），
但只推 **20 步空动作** yaw 就在第 4 位漂了（−111.5129 vs −111.5186）。
依据 `mjlab/docs/faq.md`：*"MuJoCo Warp does not yet guarantee determinism… tracked in
mujoco_warp#562"*；MuJoCo 官方 FAQ 给的出路是 **`wp.set_device("cpu")`**。
⇒ **"再跑一遍验证"不算验证**，独立性只能来自 N 次重复 + sem（本轮即按此做）。

**参考尺度**：ANYmal（Science Robotics, arXiv:1901.08652）实测 yaw rate error **0.174 rad/s**，
我们 1.2 ⇒ 差 7 倍（跨任务粗对标，只当量级参照）。

次选假设（`TURN_IN_PLACE_FRACTION = 0.15` 对软伺服不够）**暂不需要**：turn-in-place 只加样本，
而 ① 已证明问题不是样本偏向一侧，是**没有反馈**。真要治，候选是给训练加 `rel_heading_envs > 0`
（让部分 env 用航向误差经 P 控制器生成 wz）—— 这属 **task 改动 ⇒ 按纪律必须重训**。
- **G2 闸门**：主因已判明 ✅ ⇒ 可进 P3；但 P3 之前先做 P1（见下），否则会训在参数未实测的植物上。

### P3 · 一次正式重训（改代码 ⇒ 按 AGENTS.md §2 从零）

- 本机探索档 **1024×2000**（⛔ 8192 已证伪：8 GB 上 ~100 s/iter、显存顶满）
- 上云仅 **4090D ¥1.88/h**：先 64×5 冒烟，**开工前报预计时长×单价征得同意**
- **G3 闸门**（3 次重复取中位，不看单次）：32env×8s cmd 0.4 下 `no_fall` ✅、
  `not_sideways` ✅（判据 `|dy| ≤ 0.5×|dx_body|`）、ratio ≥0.75（具体值待 P2 出数后钉）

#### P3 附 · heading 闭环（治偏航，建议与 P3 合并为**同一次**重训）

**机制**（`mjlab/tasks/velocity/mdp/velocity_command.py`）

```python
_resample_command():                              # 每个窗口 3–8 s 一次
    heading_target[ids] = U(-pi, pi)              # :81
    is_heading_env[ids] = U(0,1) <= rel_heading_envs   # :83
_update_command():                                # 每一步
    heading_error = wrap_to_pi(heading_target - heading_w)          # :118
    vel_command_b[ids, 2] = clip(stiffness * heading_error,         # :119-123
                                 *ranges.ang_vel_z)
```

即 heading env 的 `cmd[2]` 不再是窗口内的随机常值，而是**每步重算的比例控制器**。
命令槽位仍是那个三维 `vel_command_b` ⇒ **观测/动作契约不变**（obs 61 / act 14 / 50 Hz），
导出的 ONNX 可直接用；评估脚本本来就把所有 `rel_*` 反射清零，读数不受训练侧设置影响。

**必须回读对象，不能读源码**：`heading_command` 在 `microduck_velocity_env_cfg.py` 里
**一次都不出现**（靠基类继承、再经 `VelocityCommandCommandOnlyCfg(**vars(cmd))` 重建），
grep 源码会以为这个字段不存在。实际回读：

| 字段 | live 值 | 结论 |
|---|---|---|
| `heading_command` | **True** | 开关在 |
| `heading_control_stiffness` | **0.5** | 增益在 |
| `ranges.heading` | **(-π, π)** | 目标范围在，非 None |
| `rel_heading_envs` | **0.0** | **唯一被关的那个** |

⇒ 打开它**只需改这一个数字**，不需要同时补 `heading_command` / `ranges.heading`。
`--rel-heading-envs` 值超过 ±2 rad 时 cmd[2] 饱和（`ang_vel_z` 上界 1.0 / 刚度 0.5 = 2.0 rad）。

**改法**（落在 `microduck-software/tools/train_heading_variant.py`）

跟 `train_velocity_variant.py` 同一套路：`Parse TrainConfig → in-process 改 live cfg →
回读 before/after → 记录 meta → launch_training`，**site-packages 一行不动**，
`check_velocity_ready.py` 的 pristine 检查继续有效。已加三道护栏：
- 改完比较 requested vs effective，不一致直接退出（声明了没生效 = 这类 bug 的全部由来）
- 反射扫**所有** curriculum term 的 stage table，确认没有第二个写者在训练中偷改它
  （`standing_envs` 就是这么偷过一次）⇒ 实测 **写者唯一**
- 拒绝概率量越界（`-0.1` / `1.5` / `stiffness=0` 三组负对照全部变红）

**代价：`rel_*` 是独立伯努利，不是互斥分类**

heading env 可能同时是 forward env。`_resample_command` 给它 ω=0，`_update_command` 随后
**每步覆盖**。期望重叠 `rel_heading_envs × rel_forward_envs`（0.30×0.20 = **6%**）。
探针实测（`rel_heading=0.5, rel_forward=0.5`, 32 env）：重叠 env 的 `max|ω| = 1.0`，
未重叠的 forward env `max|ω| = 0.0` —— 干净的对照。
vx 那半不受影响（`clamp(≥0.3)` 保留），所以 forward 桶"防低速摸鱼"的作用还在。
真要互斥得改 `mdp.py`，被 `mdp_patch_contained` 挡着 ⇒ **接受并记录，不掩盖**。

**已验证**（`tools/hd1910/probe_heading_loop.py`，CPU 8 env、90 步、无 policy、几秒）

| 判据 | control | variant |
|---|---|---|
| `cmd[2]` 与闭式 `clip(k·wrap(target-heading))` 逐位相符 | `1.737`（1.7e6× 容差） | **0.000e+00** |
| 每步 `Δcmd[2]` 与 `Δheading` 反号 | — | **441/441 步一致** |

⚠️ 判据踩过一次坑：原先用 `corr(heading_w, cmd[2]) < -0.9`，结果 -0.24 FAIL。
原因是 base 被驱动转了 6.26 rad > π，`wrap_to_pi` 把关系折成三角波，
**全局相关系数天然拉低** ⇒ 换成局部符号一致性（只在未饱和且真移动的步上要求反号）。
**机制没错，是判据的数学形式假设错了。**

**待定：`--rel-heading-envs` 取多少** —— 不预设。mjlab 通用默认 0.3
（`velocity_env_cfg.py:182`）**不能照抄**（本仓 §0 已在同类处踩过一次）；
上游 AGENTS.md:186 只给原则「稀有的重要命令区需要显式 bucket」，`rel_turn_in_place_envs`
因此是 0.15。⇒ **P3 当日小档 sweep 决定，别现在拍脑袋。**

### P4 · 交付链重做

export → ONNX → parity（**负对照必须严重偏离**，照抄 §13）→ 彩排六条件。
文件名带上 plant 标签；⛔ 作废 `walk_std004_1250.onnx`（XL330，勿再引用）。

### P5 · 阶段 3 自动跟随（偏航修好后才有意义）

跑 `tools/flat_walk/eval_tracking.py`（已带 plant 指纹 + 基线健康闸门），回答
`resampling_time_range [3.0, 8.0] s` 那条；再扫 cmd 0.15–0.4 找 **HD1910 自己的低速地板**
（XL330 那条 0.15 m/s 下限**不适用**，属跨 plant 引用，重测）。

## 8.3 本轮新加的三条纪律

| # | 纪律 | 起因 |
|---|---|---|
| 1 | **每次读数必带 plant 指纹** | cfg/mdp sha 盖不到 `_BAM_ACTUATOR_KWARGS`（传递闭包），换 plant 时它们照样全绿。已落地 `tools/flat_walk/plant_id.py`，两个评估脚本都写 `plant_fingerprint` |
| 2 | **跨 plant 数字不横比** | 同一 ckpt 同命令：xl330 vx 0.318/摔 0% ↔ hd1910 vx 0.109/摔 100%（10-28 实测 A/B）。说「变差」是错的，是任务变了 |
| 3 | **位移类读数必须 ≥3 次重复才判决** | `abs_dy_body_median` CV 31.4%；`not_sideways` 用的是单次 `|dy| vs 0.5×|dx|` |
| 4 | **验证靠 N 次重复 + sem，不靠"再跑一遍"** | MJWarp 不确定性（mujoco_warp#562，官方 FAQ 确认）：同 seed 只保证**初始条件**一致，20 步后就在第 4 位发散。⇒ 复跑取同值不成立；需要确定性时另有官方出路 `wp.set_device("cpu")` |

## 8.4 待你定的两件事

1. **阶段 0 是否今天就下单**（清单已就绪，≈¥245–324）—— P1 的实测参数卡在它后面
2. ~~P2 是否启用 symmetry 试跑~~ —— **已作废**：P2 实测三次符号翻转、同号率 0.51 ⇒ 假设证伪，不用再问
3. ~~P3 要不要顺带加 `rel_heading_envs > 0`~~ —— **问题变了**：工具与机制验证已就绪
   （`tools/train_heading_variant.py` + `tools/hd1910/probe_heading_loop.py`，8/8 PASS），
   **不再问"要不要加"，只剩"取多少"**。建议 P3 开训当天用探索档小 sweep（如 0.15 / 0.30）
   由数据决定，而不是现在拍脑袋。仍须与 P3 合并为**同一次**重训（属 task 改动 ⇒ 必重训）。
   详见上面的「P3 附」
4. 是否接受「验证靠 N 次重复 + sem，而不是复跑取同值」？（MJWarp 不确定性限制；
   若确实需要确定性读数，可选 `--device cpu` + `wp.set_device("cpu")` 那条官方出路，代价是速度）
