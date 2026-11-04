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
| 植物 live | **hd1910_kp8**（`official_m6_stslaw.json`、`kp_fw=8.0`；`apply_to_live.py --check` 回报）。早先的 m5/kp32 只用于跨 plant 对照，不再是 live |
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
| P3 闸门（2026-11-03） | ✅ 预注册 `tools/flat_walk/gate_p3_yaw.py`（阈值写死 + `--audit-baseline` + 16 项负对照）；`not_sideways` 退出判决、改当诊断 |
| kp8 参考点（2026-11-03 晚） | ✅ 部署候选 `model_2999` 三次重复：vx **0.1629**、`err_yaw` **0.7284**、absdy 0.476、dx 比 0.316（已冻结成 `--baseline-set kp8`）。⚠️ 与 m5/kp32 差三样（plant/奖励/迭代数）⇒ **不是 heading 有效性的证据** |
| heading A/B 控制臂（2026-11-03 晚备好） | 🟡 发现原"干净对照"（11-02）还多一个 `ang_vel_z ±1.0`（`--ang-vel-z-clip` 被静默忽略）⇒ 先补 `set_ang_vel_z_range`；控制臂脚本 + 反向闸门 + 配对判决全部就绪并冒烟通过，**待次日 3.28 h 开跑**（`explore_heading_control.sh`） |
| 控制臂训练（2026-11-04） | 🟢 **跑中**：`2026-11-04_08-38-17_p8ctl_030_1104`（起步核对全绿；早期曲线与奖励臂基本重合，err_yaw 略高符合预期），ETA ~11:40 |
| ONNX + parity（kp8 候选 2999） | ✅ `artifacts/flat_walk/checkpoints/p8head_2999.onnx`；parity max\|Δ\|**3.53e−6**、负对照 53348× 容差（`evals/onnx_parity_p8head_2999.json`）——P4 链第一步完成，A/B 判决后如换臂重导即可 |
| cmd 包线扫点工具 | ✅ `tools/hd1910/sweep_cmd_envelope.sh`（0.15/0.2/0.3/0.4×3 seed，与冻结基线同口径；只报数不判决），训练完与 A/B 扫点一起排 GPU 队；`TASK=` 可换域 |
| **齿隙域（backlash，2026-11-04）** | ✅ **上游自带**，非自研：`add_backlash.py` 串 `passive_<joint>_backlash` 硬限位铰链 + `BacklashEncoderBamActuator`（PD 读输出侧）+ obs 换 `*_rel_backlash`；任务 `Mjlab-Velocity-Flat-Backlash-MicroDuck` 与 **hd1910 kp8 零改动组合**（执行器共用 `_BAM_ACTUATOR_KWARGS`）。闸门 `check_backlash_task.py` 6 项自检全绿（obs/act **61/14 不变**、nq 21→35）。**剂量曲线**（同策略三 seed CPU）：0.5°(厂标) → err_yaw **+9.2%**、1.0° → +15.8%、2.0°(上游默认) → +17.7%，**均不摔不降速** ⇒ 真机量级约 +9%，不进单独 3.3 h run，并入 P4 候选那一版 |
| **信息缺口台账（2026-11-04）** | ✅ 见 **§8.5**。补齐 8 项（齿轮虚位 **≤0.5° 官网一手**、7.4 V 三档全表、IMU 真实配置 **±4 g/±500 dps/120 Hz**、**电池已含在 737 g 内**（MJCF `np_f970` 网格名误导，几何是 F550）、obs 噪声量级、方向性齿隙的学术依据）；剩 6 项只能上台架（游隙/地面摩擦/IMU 削顶/总线事务/实称 782 g/SFLP 延迟） |

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

> 2026-11-03 修订：来源集合不变，只更新 kissqy 行、新增 xgoduck 行、BAM 链加注。依据为当日读
> `kissqy/Microduck-kissqy` 与 `LuwuDynamics/xgoduck*` 一手源码（见 §1.1 证据）。

| 来源 | ★ / 状态 | 采 | 弃 / 慎用 |
|---|---|---|---|
| **官方 microduck_rl** | 2645★ | 任务定义、奖励、课程、export/infer、AGENTS.md 方法论 | XL330 BAM kwargs（`motor_name=xl330`, `kp_fw=200`） |
| **qiaosiyi/microduck_rl_hd1910** | 10★ | 全任务 HD1910 接线清单、质量修正算法、smoke 矩阵、公开权重作**负对照** | `datasheet_based_provisional` 植物；HOME 开环 8/8 摔是已知事实 |
| **飞特 ftservo-bam** | Gitee 官方 | `feetech_hd1910_7_4V` m1–m6、`kp=32`、`error_gain=0.163`、mjlab 集成 | PyPI `better-actuator-models` **不含** HD1910，必须本地装 Gitee 克隆 |
| **OpenMicroDuck 辨识** | 本仓已镜像 | 72 摆锤 + 48 腿实测 → m5：`kt=0.692`, `R=3.75`, delay 25.3 ms | 5 V 台架口径；上 7.4 V 时 vin 改、kt/R 可沿用 |
| **kissqy** | 424★ | 真机镜像、中控、采购账单、抖动修复（D=0）；**IMU 桥固件完全开源**（`firmware/imu-source/`，STM32G031F8P6+LSM6DSV16X，ID 200，同步读 `[56,15,200]`）＋ PCB 工程（立创EDA）＋可买预烧成品板；`duck-control/src/feetech.rs` 是 HD1910 寄存器契约一手来源（遥测 15B@56..70、速度 58..59 signed-mag 50 steps/s、扭矩 40、位置命令 42） | 许可：原创部分**个人非商业**；陆吾参数勿当主植物；**总线协议是 Feetech SCS v1 不是 Dynamixel P2.0**（帧 `FF FF ID LEN INST PARAM ~SUM`），所有 hd1910 工具按此帧 |
| **LuwuDynamics/xgoduck** | 商业产品 | 架构对照：Arduino UNO Q + STM32 协处理、2 Mbps、QMI8658A 走 I²C——**证明"MCU 侧 100 Hz 闭环 + I²C IMU"绕开 Dynamixel 总线 IMU 可行** | 另一套硬件生态，迁移成本高；其 `1910_m6.json` 与陆吾同组（见 BAM 链注） |
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

> 注（2026-11-03，**当日自我更正**）：陆吾 `1910_m6.json` 被 xgoduck 商业产品实际采用
> （kt 0.624/R 4.91），我一度据此认为"规格书堵转点筛法失效"，还推测原因是"输出扭矩含减速器效率"。
> **那个推测是错的**：`plant.py:54-55` 早写明该文件是 **STS3215 改名**
> （`"actuator":"sts3215"`, `max_velocity 100`），根本不是 HD1910 的参数 ——
> 筛法其实是正确地识别出了"这是另一台电机"。
> xgoduck 拿它跑 HD1910 也能走，说明的是**策略对 kt/R 的容差比我以为的宽**，
> 而不是"那组参数可用"。⇒ 与 §1 的结论同向：**不必把 kt/R 测到高精度**
> （`stage0_software_prep.md` §5.8）。仍禁止当主植物：它是 STS3215 的参数，两个物种。

### 1.1 kissqy 一手证据（2026-11-03 读取）

| 文件 | 内容 |
|---|---|
| `firmware/firmware/imu-source/src/ft_protocol.c` | 帧解析：`FF FF ID LEN INST PARAM SUM`，`LEN=参数数+2`，`SUM=~Σ(bytes[2..])`，长度字段 1 字节 |
| `firmware/firmware/imu-source/src/ft_fast_sync.c` | 同步读应答：21 B，`LEN=17`，`[0..11]` 数据块，`[12]` seq u8，`[13]` status，`[14]` 保留 |
| `firmware/firmware/imu-source/src/ft_imu.c` | 地址契约：身份 `6..12`、诊断块 `124..143`（20 B）、紧凑块 `56..70`（15 B）；旧 56/20 布局报 0x08 |
| `firmware/firmware/imu-source/src/main.c` | 1 Mbps、IMU 5 ms 轮询、FIFO 水位 1、SFLP 120 Hz |
| `firmware/duck-control/src/feetech.rs` | 主机侧常量：`SYNC_ADDRESS=56`、`SYNC_LENGTH=15`、`IMU_ID=200`、`BROADCAST=254`、`SYNC_READ=0x82` |
| `hardware/IMU-FIRMWARE.md` | 烧录指南、针脚定义、SHA256；成品板预烧 FT6 固件 |

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
> **执行顺序（不要提前烧 GPU）**：阶段 0 台架**验证**（kt/R 不辨识，只核是否落在 plant 值附近，
> 见 `stage0_software_prep.md` §5.8）→ 只在实测明显偏离时才回填 json → **一次**重训。
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
2. 阶段 0 台架：**URT-2（优先）或 URT-1** + 1 颗（**勿用 U2D2**），事务 ≤5 ms，**核 kt/R 是否落在 plant 值附近（不重新辨识）**——闸门见清单 §3 / `stage0_software_prep.md` §4 与 §5.8。HD-1910 接 **TTL**；**外电进 URT-2 的 V1/G 端子、舵机照常插 TTL-Bus 口**（V1 本来就是 TTL 总线外电输入，2026-11-03 更正：早先"勿灌 V1"是错的，见 `stage0_software_prep.md` §2）  
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

两项曾被当成长训前提，2026-11-03 复核后都不成立了（留在这里是因为它们仍会误导决策）：

| 阻塞项 | 现状 | 影响 |
|---|---|---|
| ~~**舵机参数不是实测**~~ → **2026-11-03 解除** | `m5.json` = OpenMicroDuck 真机台架（vin 5 V）；`ftservo_official_m6.json` = 飞特官方（vin 7.4）；两者 R 差 21%、kt 差 18% | kt/R **不需要自己辨识**：`plant.py` 用的就是真机台架值（kt r²=0.99），本机阶跃响应已验偏差 <15%，且策略对 kt/R 容差宽（xgoduck 拿 STS3215 参数也能走）⇒ **不再是阻塞**，见 `stage0_software_prep.md` §5.8 |
| **A/B 已经做过且无效** | `tools/hd1910/ab_train.sh` 1024×500 两条腿**都 100% fall**（500 轮判不了植物） | ⛔ **别重复这个实验**；要 A/B 就 ≥2000 轮，或干脆等实测 |

结论（2026-11-03 更新）：参数这一项**已不是阻塞**（kt/R 不自测，§5.8）⇒ 剩下的阻塞只在硬件
（ID 200 桥、7.4 V 电源）。重训的触发条件改为**真机行为与 sim 不符**，不再是"参数没落地"。

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
- **G2 闸门**：主因已判明 ✅ ⇒ 可进 P3。
  ~~但 P3 之前先做 P1（否则会训在参数未实测的植物上）~~ —— **2026-11-03 作废**：
  §8.1 已把"参数未实测"从阻塞项里划掉（kt/R 不自测，§5.8），kt 另有 §4 闭环动态对标间接验到
  <15%。⇒ P1 降级为"真机行为与 sim 不符时才做的回填"，不再是 P3 的前置。

### P3 · 一次正式重训（改代码 ⇒ 按 AGENTS.md §2 从零）

- 本机探索档 **1024×2000**（⛔ 8192 已证伪：8 GB 上 ~100 s/iter、显存顶满）
- 上云仅 **4090D ¥1.88/h**：先 64×5 冒烟，**开工前报预计时长×单价征得同意**
- **G3 闸门已预注册**（`tools/flat_walk/gate_p3_yaw.py`，2026-11-03 钉死，`--selftest` 14 项全绿）：

| 轴 | 量 | 基线（3 seed 均值） | 阈值 | 为什么是它 |
|---|---|---|---|---|
| 安全 | `terminated_frac` | 0 | <0.02 **每次** | 摔了不谈别的 |
| **vx 不退化** | `vx_mean` | 0.30103（sem 0.0035，CV **1.98%**） | ≥0.97× = **0.29200** | 防"用降速换稳定" |
| **偏航** | `error_vel_yaw` | 1.19890（sem 0.0083，CV **1.20%**） | 判决 ≤0.90× = **1.07901**；目标 ≤0.50× = **0.59945** | 低 CV：10% 改善 = 14 sem，噪声翻不了面 |
| **xy 不退化** | `error_vel_xy` | 0.19833（CV 1.75%） | ≤1.05× = **0.20825** | 同上 |
| 直行（诊断） | `abs_dy_body_median` / `dx_ratio` | 0.838 / 0.177（CV **19.6% / 25.5%**） | **不作判决**，只报数 | N=3 只能分辨 ≥50% 的效应 |

- 判决口径：**3 次重复取均值**（不取单次、不挑最好那次）；退出码 0 过 / 1 红 / 2 重复数不足（PROVISIONAL，不退 0）/ 3 完整性坏。
- ⛔ **`not_sideways` 退出判决**：它是单次 `|dy| ≤ 0.5|dx|`，两个量 CV 19.6% / 25.5%
  —— §8.3 #3 已经禁止拿高 CV 量当门禁，而当初恰恰把最稳的 `error_vel_yaw`（1.2%）
  留成了诊断、把最抖的放进了闸门。JSON 里的原字段照旧保留（历史可比），只是不再当判据。
- 负对照固化在脚本里（`--selftest`）：基线自身**偏航门必须红**、vx 门必须绿；
  偏航只改善 5% 必须红；偏航好但 vx 掉 20% 必须红；混 plant / 混 cmd / 坏 metric_window 必须报完整性错。
- 阈值可审计：`--audit-baseline` 比对冻结常量与三份基线 JSON 的 sha256 + 均值 + sem + CV
  （改文件不改常量 ⇒ 直接红）。
- **为什么偏航用 `error_vel_yaw` 而不是净漂移**：cmd 冻结 wz=0 时它是**瞬时** |ω| 误差（≈1.2 rad/s），
  净漂移是积分结果（中位 14 deg/s ≈0.25 rad/s）。两者差 4.8× 不是矛盾 ——
  同次里 signed mean ω = 0.043 rad/s ≈ `yaw_drift_signed` 2.52 deg/s ⇒ 净转角小、瞬时在**摆**
  （等效 ±17° @ 1 Hz 的步态偏航摇摆）。摆是随机游走的源头，也是唯一低 CV 可判的量。
- **两套基线**（`--baseline-set`）：上表是 `m5kp32`；另有 `kp8` = 部署候选 `model_2999`
  （`2026-11-03_08-33-18_p8head_030_4096x3000`），2026-11-03 晚本机实测 3 seed
  （同 cmd 0.4 / 32 env × 8 s / solver 100/50 / seed 11·22·33，
  产物 `artifacts/flat_walk/evals/p8head_ref/`）：

| kp8 基线（3 seed 均值） | 值 | sem | CV |
|---|---|---|---|
| vx | 0.1629 | 0.0016 | 1.75% |
| `error_vel_xy` | 0.2702 | 0.0011 | 0.69% |
| `error_vel_yaw` | 0.7284 | 0.0110 | 2.62% |
| `abs_dy_body_median` | 0.4761 | 0.0410 | 14.92% |
| `dx_over_expected` | 0.3162 | — | **3.55%** |

  ⚠️ **它只是参考点，不是 heading 对照**：相对 m5/kp32 同时换了 plant、heading 奖励、
  迭代数（3000 vs 6000）⇒ **不能用它宣称"heading 闭环有效"**。见下一小节：原来的"干净对照"
  也不干净，控制臂到 2026-11-03 晚才真正具备。
- **顺手撞到的证据**（同一批 gates 打在 kp8 策略上）：`not_sideways` **2 过 1 挂** ——
  absdy 0.558 / 0.443 / 0.428，阈值 0.486 正好落在分布中间。这就是"单次高 CV 门会靠运气翻面"
  的现场复现，不是推测。

#### P3 附 · heading 奖励 A/B：控制臂（2026-11-03 晚备好，次日开跑）

**原以为的对照不成立。** `2026-11-02_21-26-53_p8head_030` 一直被当作"kp8 + `rel_heading_envs=0.3`
不带奖励"的干净对照（只跑到 `model_0` 就中止）。逐叶比对它的 `params/env.yaml` 与奖励臂
（`tools/hd1910/diff_run_recipes.py`，29 处差异）后确认：它还多一个 `ranges.ang_vel_z = ±1.0`
（奖励臂是 ±0.5）。原因不是手误 —— `train_heading_variant.py` 里 `--ang-vel-z-clip`
**只在奖励分支内被读取**，不带奖励时这个 flag 被静默忽略。⇒ 那条 run 等于一次改了**两个**变量，
和奖励臂不可比；"再跑一遍 11-02 的配方"会同时改转向范围。

**改法**（`train_heading_variant.py::set_ang_vel_z_range`）：转向范围是**命令环**的属性，不是奖励的
属性 —— `cmd[2] = clip(stiffness·heading_error, ranges.ang_vel_z)` 每步生效，±1.0 就是允许以
1 rad/s 猛打方向。抽出独立函数后，`--ang-vel-z-clip` 在**不带奖励**时也生效并回读断言；
带奖励的路径行为不变（回归干跑逐字对过）。meta 新增 `ang_vel_z_clip_without_rewards` 记录这条。

**两臂定义**（唯一差别＝两个奖励项）

| | 奖励臂 A | 控制臂 B |
|---|---|---|
| run | `2026-11-03_08-33-18_p8head_030_4096x3000` | `p8ctl_030_4096x3000`（待跑） |
| plant / seed / envs / iters | kp8 / 42 / 4096 / 3000 | 同 |
| `rel_heading_envs` / `ang_vel_z` | 0.30 / ±0.5 | 同 |
| heading 奖励 | hold 1.0→0、tracking 0→3.0 | **无** |
| solver | 100 / 50 | 同 |

**开跑一条命令**（本机 4070，实测 **3.28 h**：11-03 那条 08:33:29→11:50:16、3.94 s/iter；
之前估的 2.7 h 偏乐观）

```bash
bash microduck-software/tools/hd1910/explore_heading_control.sh
# DRY=1 先看解析结果；SMOKE=1 跑 64×5 只验闸门
```

**闸门**（`tools/hd1910/check_control_arm.py`，读 run 自己的 `params/`，不信命令行）
① 奖励项**必须缺席**（`rewards`/`curriculum` 里零个含 heading 的键 —— 反向断言，多一个就红）；
② `ang_vel_z == ±0.5`；③ `rel_heading_envs == 0.3`；④ envs / iters / seed 与 A 相同。
每次跑完自动做**负对照**：同一脚本打在奖励臂上必须红，否则说明闸门是坏的。
`--selftest` 6 项：奖励臂必须被拒、±1.0 无奖励臂必须被拒（就是 11-02 那种）、把范围改成 ±0.5
后必须通过（证明不是"对谁都红"）、seed 不同必须被拒。

**判决规则**（`tools/hd1910/summarize_heading_ab.py`，开跑前写死）
同 seed 同迭代 ⇒ 每个 `model_k` 是一**配对**，比配对差而不是比两臂均值：

- `d(k) = 100·(err_yaw_B − err_yaw_A)/err_yaw_A`，`median(d) ≤ −10%` 且 ≥80% 的配对同号 ⇒
  "奖励有效"；反向 ⇒ "奖励有害"；否则 **no decision**（退出码 2，不当作失败也不当作通过）。
- 速度护栏：B 的 vx 不得低于 A 的 97%（"靠少走路换来的偏航改善"不算赢，与 `gate_p3_yaw.py`
  对基线用的是同一条）。
- 10% 的依据：单次 eval 的 `err_yaw` CV 1.2–2.6%，配对差更紧；而奖励想拿到的效应是
  1.20→0.73 rad/s ≈ **39%**。10% 既不会被运气跨过，也远低于效应量。
- `abs_dy` / `dx_over_expected` **只报不判**（CV 15–25%，单 seed 十个点救不回来）。

**评估路径**（跑完直接两条命令）

```bash
bash microduck-software/tools/hd1910/sweep_heading_arms.sh      # 默认 stride 300 → 每臂 11 点
python microduck-software/tools/hd1910/summarize_heading_ab.py \
  --a-dir ../artifacts/flat_walk/evals/ab_heading/A \
  --b-dir ../artifacts/flat_walk/evals/ab_heading/B
```

扫点用固定 32 env × 8 s / cmd 0.4 / seed 11 / solver 100/50，与冻结的 `--baseline-set kp8`
同口径；`summarize` 在配对前会核对两目录的 eval 设置、plant 指纹与"谁有奖励、谁没有"，
不一致直接 exit 3。

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
**2026-11-04 进展**：kp8 候选 `model_2999` 已导出+parity 全绿（`checkpoints/p8head_2999.onnx`，
max|Δ|=3.53e−6）；cmd 包线工具 `sweep_cmd_envelope.sh` 备好。彩排不适用（`rehearse_deploy.py`
写死 XL330/kp200）。

**真机水平参照（2026-11-04 查证，回答"多训能达到什么水平"）**：
- 同舵机级别的开源正主 **Open Duck Mini v2**（apirrone，BAM+STS3215+Pi Zero 2W，技术路线与我们同源）：
  其参考步态生成器 `walk_max_dx_forward = 0.1 m/s`——即该级别公认"能走"的量级是 **0.1 m/s**，
  真机闭环靠模仿奖励+参考运动（改 obs 维数，属我们二期）。他们运行时 50 Hz / action_scale 0.25 /
  obs 带三步历史动作与步态相位。
- 本项目 sim kp8 候选 0.163 m/s @cmd0.4：**已在同级别参照之上**。多训的现实上限是把 41% 抬到
  m5 线的 75%（std 收窄在 m5 上 +24%），不是把绝对速度翻倍。
- ⚠️ 搜索噪声警告："Microduck 2.07 m/s 百米跑"一类文章是内容农场水文（混入轮式小车），
  不可引用。可信参照只有：ODM v2 0.1 m/s 级、上游 alpha_walking 真机 v8 0.17 m/s（cmd 0.4）。
- **部署首跑注意**（社区高频翻车点，已核对上游随机化覆盖）：训练域 `foot_friction=(0.7,1.3)`
  假设高摩擦脚垫 ⇒ 真机首跑选橡胶垫/地毯，**别在瓷砖上首跑**（侧滑是社区头号 sim2real 症状）；
  IMU 角速度 z 符号、关节零位是上电第一检查项。

### P4 附 · 齿隙域（backlash）：不用自研，上游已给，且与 kp8 零改动组合

**结论先说**：之前写的"plant 无齿隙字段、二期再做"是**错的定位**——齿隙不是 plant 参数，
而是**任务域**。上游 `microduck_rl@develop` 自带完整实现，且与我们换过的 hd1910 植物自动兼容。

三件套（源码位置，已逐行核对）：

| 组件 | 位置 | 做的事 |
|---|---|---|
| `add_backlash.py` | `robot/microduck/` | 给每个 `class="chosen_actuator"` 关节串一根**不驱动**的 `passive_<joint>_backlash` 铰链，`range=±deg/2`、`limited=true`、`solreflimit=0.01 1`（否则小行程下限位会被冲击穿透 ~2×）。死区内电机转负载不动，撞限位后刚性传递 ⇒ **方向相关**，加噪声模拟不出来 |
| `BacklashEncoderBamActuator` | `actuator/friction_dr_bam.py` | 固件位置环读 `qpos[main]+qpos[backlash]`（输出侧编码器），与真舵机一致；缺失齿隙关节时自动退化为普通 BAM |
| `make_backlash_variant` | `tasks/backlash.py` | joint_pos/vel obs 换 `*_rel_backlash`；`dof_pos_limits` 奖励收窄到舵机关节（齿隙关节终生贴限位，否则喂永久越界惩罚）；`pose` 正则加 `^(?!passive_.*_backlash)` 防歧义 |

**为什么能直接接我们的 plant**：`backlash_actuators = BacklashEncoderBamActuatorCfg(**_BAM_ACTUATOR_KWARGS)`，
与主任务**共用同一块 kwargs**，而 `apply_to_live.py --plant` 改的正是那块 ⇒ 实测 backlash 任务的执行器
就是 `json_path=official_m6_stslaw.json`、`kp_fw=8.0`。

**实测（2026-11-04，`check_backlash_task.py` 闸门）**：
- 29 关节 = 14 舵机 + 14 齿隙（+1 基座自由关节，`nq 21→35`），14 根齿隙全部 `limited`、范围 ±0.017453 rad（**2° 总游隙**）；
- **obs 61 / action 14 不变** ⇒ ONNX、`infer_policy.py`、robotd 一行都不用改（导出侧已有 `passive_*` 过滤补丁）；
- 奖励键与基础任务逐键一致、命令范围一致（只换域，不换任务）；
- 建环境 + 两步 `step` 无 NaN。

**同策略跨域实测**（`model_2999`，CPU 8env×4s，seed 11/22/33；`--backlash-deg` 可扫游隙，
读数落 `evals/p8head_backlash_diag/`）：

| 总游隙 | vx（mean±sd）| err_yaw（mean±sd）| 配对中位 Δerr_yaw | 同号 |
|---|---|---|---|---|
| flat（0°）| 0.1434 ± 0.0294 | 0.6930 ± 0.0413 | — | — |
| **0.5°（HD1910 厂标上限）** | 0.1571 ± 0.0158 | **0.7667** ± 0.0339 | **+9.2%** | 3/3 |
| 1.0° | 0.1647 ± 0.0168 | 0.7956 ± 0.0193 | +15.8% | 3/3 |
| 2.0°（上游默认，XL330 级）| 0.1648 ± 0.0159 | 0.8115 ± 0.0340 | +17.7% | 3/3 |

三条读法：
1. **单调剂量响应且饱和**：0.5°→2° 只再涨 8 个点 ⇒ 约一半效应来自**反馈路径**（PD/obs 读输出侧），
   不是死区宽度本身。**只要开齿隙域就有固定成本**，这决定了"为齿隙重训"的收益上限有限。
2. **不摔、vx 不降**（vx 的 sd 20%，不作判据）。齿隙吃的是**偏航精度**，与"脚踝游隙 ⇒ 转向松"
   的物理预期一致。
3. 结构已核：16 body / 75 geom / 7 site / 质量 0.7372 / 14 舵机行程**全部相同**，只多 14 根被动铰链
   ⇒ 差异可归因于齿隙本身，不是模型换了别的。

⚠️ **仪器限制**：CPU 8env×4s，flat 臂 0.143 比冻结基线（GPU 32env×8s）的 0.163 低 12%
⇒ **只能同仪器纵比，不能与冻结基线横比**；上 GPU 后应重跑 32env×8s×3seed 再定论。

⚠️ **踩过的坑**：`--backlash-deg` 首版读回用 `startswith("passive_")` 筛关节，而编译模型名带实体前缀
（`robot/passive_...`）⇒ 读到 **0 个关节却"无异常"**，一个未验证的读数就写进了 JSON。现已改为
**0 个关节即失败** + 逐关节回读编译模型的 `jnt_range` 对齐请求值（实测 `actual_half_range_rad=[0.004363]`
= 0.25°）。凡"改参数"的开关都必须这样回读，不能只看 flag 生效。

**结论与队列位置（2026-11-04 修正）**：
- **2° 是上游按 XL330 级行星减速给的默认，HD1910 厂标只有 ≤0.5°（4× 之差）** ⇒ 早先"2° 吃掉 18%"
  是**最坏上界**，真机量级是 **~+9% 的瞬时偏航误差**，不摔、不降速。
- 因此**不值得现在就为齿隙单开一条 3.3 h 的 run**：收益小，且会引入新变量。正确位置是
  **A/B 判决出胜出配方后，把齿隙域并进 P4 部署候选那一版**（同一配方 + 实测游隙）。
- 台架到手必做（1 分钟）：抓住舵机、晃舵盘量游隙；`--backlash-deg` 直接吃这个数，无需改 XML/代码。
  若实测接近 1.5–2°，则齿隙域从"可选"升为"该单独训一版"。


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
| 5 | **闸门只能压在低 CV 量上，且阈值必须开训前钉死** | P2 三次重复的 CV 表：`error_vel_yaw` **1.20%**、`vx` 1.98%、`error_vel_xy` 1.75% vs `abs_dy_body_median` 19.6%、`dx_over_expected` 25.5%。原来的 G3 恰好把最抖的 `not_sideways` 放进闸门、把最稳的 `error_vel_yaw` 留成诊断 ⇒ 判决能被运气翻面。已改：`tools/flat_walk/gate_p3_yaw.py`（阈值写死 + `--audit-baseline` 防漂移 + 负对照里基线自己被判红） |

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

## 8.5 信息缺口台账（2026-11-04 专项查证）

问题：**还有哪些数是不确定/缺失的，能不能靠查资料补齐？**
分两类答，并把**来源等级写死**（§8.3 纪律的延伸：转录 ≠ 一手）。凡标"一手"的，
指官方页面 / 固件源码 / 模型文件本身；标"代理/转录"的不得当判据基础。

### 8.5.1 本次补齐的（此前缺或只有二手转录）

| 缺口 | 补上的结论 | 来源等级 | 影响什么 |
|---|---|---|---|
| **齿轮虚位到底多少** | **≤ 0.5°（总游隙）**。飞特官网 HD-1910-C001 规格栏原文 `齿轮虚位Back Lash ≦0.5°` | **一手**（feetech.cn/510257） | P4 齿隙域取 0.5° 而非上游默认 2°，从推断升级为厂标 |
| **7.4 V 档额定扭矩/电流** | 额定 **3.7 kg·cm = 0.363 N·m / 900 mA**；堵转 15 kg·cm = 1.47 N·m / 2.0 A；空载 113 RPM。三档全表：4.8 V 2.2 kg·cm/500 mA、6 V 3 kg·cm/690 mA、7.4 V 3.7 kg·cm/900 mA | **代理+转录**（台湾代理三档表、台架指南、上游清单三方一致）。⚠️ 代理写"额定电流 2900 mA@7.4V"是 **900 的笔误**——堵转才 2.0 A，额定不可能大于堵转 | G0 闸门「额定 0.36 N·m 连续 60 s」判据成立，但**证据等级是转录**；台架实测温升才算一手 |
| **空载 / 静态电流** | 空载 **≤210 mA**@7.4V（4.8V ≤160、6V ≤180）；静态 20 mA | 代理 | 续航与压降估算此前完全没有这两个数 |
| **温宽与过热** | 运行 **−20~60 ℃**（储存 −30~80）；过热保护 **80 ℃ 默认开**，过流(0.5 A/2 s)与过压(>10 V 或 <4 V)**默认关** | 一手（官网）+ 台架指南 | 已在 §5.9；确认"出厂只开过热" |
| **IMU 真实配置** | LSM6DSV16X：**±4 g / ±500 dps / ODR 120 Hz**，SFLP `game_rotation`（6 轴，**不含磁力计**），FIFO watermark=1 | **一手源码**（kissqy `firmware/imu-source/src/main.c:283-292`） | 见 8.5.2 的量程余量问题；也是 gravity 噪声/滞后的物理依据 |
| **电池到底算没算进质量** | **算了**。MJCF `trunk_base` 里就有 `np_f970` 网格。⚠️ **网格名误导**：几何是 **F550 尺寸 39×21×71 mm**，不是 F970。NP-F550 实测类 ~108 g ⇒ 199.2 g 内已含电池 | **一手**（MJCF 几何 + 电池称重资料） | chenkui 清单里"是否已含在 trunk_base 待核"**闭合**，不必再加 100 g |
| **obs 噪声有没有建模** | 已建模，且是照真机定的：`base_ang_vel ±0.03`、`gravity ±0.01`、`joint_pos ±0.001`、`joint_vel ±0.25`；`gravity` 延迟 0–1 **控制步**、`joint_vel` 固定 1 **控制步** | **一手 cfg**（`microduck_velocity_env_cfg.py:587-611`） | `joint_pos ±0.001 rad = 0.057°` ≈ 编码器量化 0.088° 的一半，**不是随手写的** |
| **方向性齿隙存不存在** | **存在，但上游没建**。学术证据：非对称滞回（摆线针轮两侧针齿接触对数不同导致刚度/宽度不对称）、齿隙宽度随**角度位置与负载**变化（UR5e 实测、PSO-BP 建模）。上游 `add_backlash.py` 是**对称 ±deg/2** | 论文/专利（**非本机型实测**） | 判决见下 |
| **IMU 融合需要多久才可信** | **SFLP：orientation stabilization 0.7 s、calibration 0.8 s**；静态精度 roll/pitch 1.5°、yaw 0.5°/5 min；动态精度 roll 0.5–1.2° | **一手**（ST DS13510 Rev 3, p.7-8 `Table 1. Sensor fusion performance`） | **部署序列硬约束**，见 8.5.3 ③ |

### 8.5.2 仍然缺的（查资料补不了，只能上台架）

| 项 | 为什么资料补不了 | 怎么测（成本） | 判据 |
|---|---|---|---|
| **真机实际游隙** | 编码器在**输出侧**，测不到自己的间隙；厂标只是上界 | 通电保持位姿，外部角度参考（手机水平仪/量角器）掰舵盘读 reg56 差；**正转/反转各一次 × 3 个角度**（≈1 min/颗） | 总量 ≥1.5° 才单独开齿隙 run；正反向差 >0.5×总量 ⇒ 再谈非对称建模 |
| **地面摩擦系数** | 取决于脚垫材料（**官方 BOM 未指定打印材料**，只有 jaw/mouth 是 TPU） | 倾斜平面法 μ≈tanθ，木地板/瓷砖/地毯各 5 次（脚已在手，**现在就能做**） | 参考量级（**商用资料，非一手**）：TPU 95A 对硬地面 **μ≈0.70–0.80**、85A ≈0.80–0.90；橡胶对瓷砖 0.5–0.6、对木地板 0.5–0.7 ⇒ **上游 `foot_friction=(0.7,1.3)` 的下半段正好是 TPU 在木地板上的真值**，1.3 那端要靠胶垫/硅胶。**瓷砖 μ≈0.5–0.6 < 训练下界 0.7 ⇒ 明确 OOD**，"别在瓷砖上跑"从经验变成有数 |
| **IMU 是否削顶** | 仿真接触模型比真机软，仿真峰值答不了真机峰值 | 读原始 gyro/accel，看是否连续出现满量程码值。量程换算：**±500 dps = 8.73 rad/s**、**±4 g = 39.2 m/s²** | 走路段无削顶即通过。理论估算：躯干 2.5 Hz×5°⇒≈78 dps，远低于 500；**加速度更危险**（落地冲击常见 2–4 g），但削顶只污染 SFLP 短暂融合，且此时已进 limp 路径 |
| **总线实测事务时间** | 与转接板方向切换、线长、调度有关，理论算不准 | 50 Hz 跑 1000 次，统计事务耗时与 CRC | G0 闸门：**≤5 ms 且 0 CRC** |
| **整机实称质量** | HD1910 21 g vs XL330 18 g ⇒ **15 颗 +45 g**；各 link 质心也要挪 | 装完直接称 | 现模型 737.1 g ⇒ 预期 ~782 g（+6.1%）。6% 对 kp8 的电流余量 2.47× 只吃到 2.33×，**不构成换档理由** |
| **SFLP 融合延迟的官方数值** | ST 应用笔记没给可直接引用的数字（搜到的全是二手博客） | 台架：静止快速翻转 + 记录四元数与真实角度的相位差 | 暂沿用上游 cfg 的 **±20 ms 包线**（注释来源是 2026-07 的真机审计）。⚠️ 另有一条**新算出来的抖动**：IMU 120 Hz 对控制 50 Hz ⇒ 最新样本年龄均匀分布 **0–8.3 ms**，仍落在 20 ms 包线内 ⇒ **不用改** |

### 8.5.3 三个判决

**① 方向性齿隙：不追，但台架顺手量。**
学术上确认非对称滞回真实存在，机理是传动结构不对称 + 位置/负载相关。但它**被 0.5° 总游隙上界卡住**：
剂量曲线显示 0.5° 全域只让 `err_yaw` 涨 9.2%，非对称只能是这 9.2% 里的一部分。⇒ 不为它开 3.3 h，
把"正反转各量一次"并进台架那 1 分钟（成本≈0）。若真测出正反向差 >0.25°（即总量一半），
再考虑在 `add_backlash.py` 上叠一个偏置——那是 P4 之后的事。

**② 量程与延迟都不构成阻塞，但记两条新事实。**
- IMU 是 **±4 g / ±500 dps**，比常见高端板（±2000 dps / ±16 g）窄一档。走路角速度余量 ~6×（78 vs 500 dps），
  加速度余量只有 ~1–2×，是**唯一值得首跑盯一眼的量**。
- **延迟要分清是哪一层的，单位还不一样**（这是本轮差点又踩的坑）：
  - 训练侧 **obs** 延迟：`gravity` 0–1 **控制步**、`joint_vel` 固定 1 **控制步**；cfg 注释里
    "was 3 (=60 ms worst case)" 就是按 20 ms/步算的 ⇒ 包线 **0–20 ms**。
  - 训练侧 **动作** 延迟：`delay_min_lag=3 / delay_max_lag=6`，单位是**物理步 5 ms** ⇒ **15–30 ms**，
    不到一个控制周期（2026-11-02 已查证，`stage0_software_prep.md` §4；**别按控制步读成 60–120 ms**）。
  - 真机 obs 链路粗算（总线 16 设备 ×12 B ≈ 3.3 ms + SFLP ~4 ms + 采样抖动 0–8.3 ms + 推理 ~1 ms）
    ≈ **12–16 ms** ⇒ **落在 0–20 ms 包线内**，训练已覆盖，不用额外加延迟随机化。
  - 真机动作链路（写 goal → 舵机 PD 响应）≈ 1–2 ms（BAM `command_delay` 0.98 ms + 总线 0.6 ms），
    **比训练的 15–30 ms 更短** ⇒ 这一维对真机是有利方向。

**③ 上电后必须等 ≥0.7 s 再进策略（本次查出的唯一新增硬约束）。**
ST 官方给 SFLP 的 **orientation stabilization time = 0.7 s**、**calibration time = 0.8 s**。
在此之前四元数还在收敛，`projected_gravity` 是假的。这与安全层已知的坑同源——
「姿态滤波未收敛时不得投票，否则 200 ms 就把直立机器人 latch 成 fallen」——
现在有了**官方时长依据**，把它写成硬数字：

```
上电 → 使能扭矩 → 等 ≥1.0 s（0.7 s 稳定 + 0.3 s 余量）→ 才允许：① 进策略 ② 进跌倒判据 ③ 采基线
```

⚠️ 这条与"跌倒判据 debounce 200 ms"叠加：若 0.7 s 内就开始投票，**3 个 debounce 周期全落在错误窗口里**，
必然误判。建议在 `robotd` 起策略前加一个显式的 `imu_settle` 等待，并在日志里打出等待时长。

**附带一个可选优化（不必改）**：kissqy 固件只 batch 了 `game_rotation`（`.gravity = 0, .gbias = 0`），
所以 gravity 是**四元数 fp16 再投影**算出来的（fp16 分量量化误差 ~5e-4 ⇒ ~0.06°，可忽略）。
SFLP 本身能直接输出 gravity vector（TAG 17h，int16，2 g 灵敏度），精度更高、少一次坐标变换。
**若真机发现 gravity 噪声异常**，改固件一处即可：`const lsm6dsv16x_fifo_sflp_raw_t fifo_sflp = { .game_rotation = 1u, .gravity = 1u, .gbias = 0u };`
（需重编译，`Makefile.feetech` 已有）。当前没有理由动它。

### 8.5.4 顺带记一条资料来源教训

搜"microduck 齿隙"会命中 `whatled.com/post-9859`、`youduck.ai/train/sim2real` 这类页面，
**内容读起来相当专业，但代码细节是编的**：它们写 `src/mjlab_microduck/tasks/backlash.py`、
`passive__backlash`（双下划线），而真实上游是 `robot/microduck/add_backlash.py`、
`passive_<joint>_backlash`（单下划线）。⇒ **判据是数字能不能回到一手源码/官方页核对，
不是站点看起来像不像技术站**。同一批站点里 `duck.whatled.com/learn/hd1910-bench` 的规格表
反而与官方一致——**逐条核，不按站点一票否决**。

### 8.5.5 部署侧四个「中立」默认值，其实每个都是结论（2026-11-04 补）

来源是一手：`deploy/robotd.toml` + `robotd/src/control.rs:106` + `duck-control/src/bus.rs`。
四个默认值看上去只是"出厂设置"，但对照训练侧真值后全是**会咬人的偏置**：

| 参数 | robotd 默认 | 训练侧真值（一手） | 不匹配的后果 | 结论 |
|---|---|---|---|---|
| `[policy] action_scale` | **0.9** | **1.0**（`microduck_velocity_env_cfg.py:273` 显式赋值） | 每个动作先缩 10% 再进 PD | 必须写 1.0（已在 B9） |
| `[policy] head_lowpass` / `legs_lowpass` | **0.5 / 0.7** | **没有低通** | 目标被 τ≈17 ms 一阶滤波：2 Hz 处 −2%、4 Hz 处 −7%、相移 6–11° | 必须写 **1.0**（新增 B10） |
| `[bus] fast_sync_read` | **true（0x8A）** | Feetech 只有 **0x82** | 设备不应答 ⇒ **每一次读都超时**，症状像接线/波特率错 | 先写 **false**（新增 B10） |
| `[control] cmd_alpha` | **0.2** | **无**（训练是阶跃命令） | 指令变成 τ≈90 ms 的斜坡：0→0.4 要 ~0.4 s 才到 95% | 首跑写 **1.0**；确认无害后再开 |

**「训练侧没有低通」是查出来的，不是推的**：`grep -r "low_pass\|lowpass"` 在
`microduck_rl` 全树、`mjlab 1.3.0`、本地 `bam` 包三处**零命中**；动作项就是
`target = current_joint_pos + action * scale`（`mjlab/envs/mdp/actions/actions.py:231`）。
robotd 注释里说 0.5/0.7 是"alpha 策略的训练值"——那是**上一代 isaaclab 血统**的事，
不是这条 mjlab 管线。⇒ 这条注释对我们是**过时的**，不能当依据。

**两条量级参照（都来自官方，一手）**：

1. **执行器模型是最大单因子**。官方 `duck-sim` 拿 MJCF 的 position actuator 顶替 BAM 模型后，
   `0.15 m/s` 指令只走出 **0.06**（40%，且他们自己标注 "the forward shortfall is still open"）。
   对比：地形（flat↔rough）、奖励、迭代数这些我们反复调的量，动的是 5–20%；
   **执行器模型动的是 2.5×**。⇒ 我们这条链路是舵机固件 PD 本身就是 BAM 本体，
   且 **sim 侧只有 `kp_fw`、没有 D 项**（`BamActuatorCfg` 无 kd 字段）⇔ 部署 `D = 0`（B6 钉的），两端一致，**不吃这一刀**。
   但这也说明：**凡是要用别人数字做参照，先看他的执行器是不是同一套**。
2. **总线这一项有现成仪器**：`bench_dynamixel_bus`（`microduck_runtime`）直接报
   achieved rate / jitter / bus utilisation / error counts，robotd 还有自带的 5 分钟汇总。
   ⇒ 8.5.2 里"总线实测事务时间"不必自己造，**先对齐它的口径**（我们已有 fanhao 的 4.8 ms/15 颗）。

补充进 8.5.2 的一条台架项：**HD1910 固件是否应答 0x8A**。一条包就能测，但**测错方向的代价是
上电即全红**，所以默认按 false 配、按 true 验。

→ **工具已就位**：`servo_probe/probe_sync_read.py`（2026-11-04，零运动、不写寄存器、11 项自检全绿）。
上游 `bus.rs:474-489` 说自己**不做探测**，理由写得很明白：「不应答」和「没上电」长得一样，
开机探测只能猜。那段话在它那个上下文里是对的，但它缺一个前提——台架上 PING 先过一遍，
"设备活着"就是**已知条件**，0x8A 的沉默于是只剩一种解释。探针就是把这个前提补上。

两个指令码不是"同一件的两种叫法"，是两套协议（自检里逐项钉住）：

| | 0x82 SYNC_READ（Feetech SCS v1） | 0x8A FAST_SYNC_READ（Dynamixel P2.0） |
|---|---|---|
| 帧头 | `FF FF <id> <len8>` | `FF FF FD 00 <id> <len16>` |
| 地址/长度宽度 | 各 1 字节 | **各 2 字节** |
| 校验 | `~sum`，body 求和 = 255 | **CRC16**，poly 0x8005 MSB-first，**从包首起算** |
| 每设备额外字段 | 无 | 有（数据长度 2 字节） |

CRC 那格是踩过才写下来的：LSB-first/0xA001（MODBUS 那套）、从 id 起算、从 `FF FF` 起算
三个错法分别给出 `3A14`/`3A14`/`C94C`，**只有全对才得 `194E`**（PING id1 已知向量）。
判决口径把不确定性放在安全的一侧：`0x82 应答 ∧ 0x8A 沉默 → false`；
`0x82 也沉默 → 不下结论`（先修接线）；0x8A 的**参数布局**我只有 P2.0 手册、无可核对的一手实现，
但布局写错只会造成假阴性，而假阴性的落点正是默认值 false。

### 8.5.6 守护进程不是「二选一」，是硬性：必须用 Feetech 分支（2026-11-04 补）

一手来源：官方 `duck-control/src/bus.rs:40,563-566,764` 对照 kissqy
`microduck-hd1910/firmware/duck-control/src/{hd1910,feetech}.rs`。

官方那条总线层**写死在 XL330 上**，两处不兼容，都落在 obs 的 15 维 `joint_vel` 上：

| | 官方（XL330 / Dynamixel） | HD1910（Feetech） | 后果 |
|---|---|---|---|
| 速度标度 | `RAD_PER_SEC_PER_COUNT = 0.229 rev/min per count` = **0.02398 rad/s per count** | `SPEED_RAD_S_PER_COUNT = 50 × 2π/4096` = **0.07668 rad/s per count** | **差 3.2×**：策略看到的速度只有真值的 1/3.2 |
| 速度编码 | 4 字节二补码（读 `[4..8]`） | 2 字节 **符号-幅值**，bit15 是符号（`feetech.rs:659` `signed_magnitude(_, 15)`） | 负速度解成 32768 量级的大正数 |
| 位置 | XL330 行程/偏移 | `2π·raw/4096 − π`，中位 2048（`bus.rs:543`） | 零位整体偏 |

⇒ **装上游 robotd 跑 HD1910，观测里有 15/61 维是错的，而且不报错。** 这属于本仓反复踩的那一类
（输出落在"看起来合理"区间）：策略会显得迟钝、步态发飘，但没有任何一行日志说单位错了。
判决：**部署二进制用 Feetech 分支**，不是风格偏好，是坐标问题。

**同一仓库里还有一份自训策略的现成配置**（`firmware/config/robotd-selftrained.toml`，
注为 "R17 self-trained HD1910"），它修正了我上面两条判断的**强度**：

| 键 | 它的值 | 对我们的意义 |
|---|---|---|
| `[bus] protocol` | `"feetech"` | 上游 schema **没有这个键**——我们的 `audit_robotd_toml.py` 审的是上游 schema，会放过一份 Feetech 守护进程直接拒绝的文件。待扩（P4） |
| `[bus] feetech_calibration` | `/etc/robot/feetech-ft5/hd1910-calibration.toml` | 每机标定（零位/方向/限位/IMU 安装）是**独立文件**，不是写死在 toml 里；对应我们的 B4 |
| `[policy] gain` | **5** | 低于我们实测平台 [7,12]，说明它是另一条策略；**不构成对 kp8 的反证** |
| `[policy] action_scale` | **0.7** | ⚠️ **改判**：`action_scale` 是**旋钮不是常数**。B9 的"必须 1.0"应读作"默认值必须显式写、匹配训练时用 1.0"；真机偏冲时 0.7 是**已被用过并走起来的**值 |
| `head/legs_lowpass`、`cmd_alpha` | **都没写**（= 吃默认 0.5/0.7/0.2） | ⇒ 8.5.5 那三个不匹配**是可容忍的**（有人这么跑起来了），是"能对上最好"，不是"不对上就走不了"。优先级下调 |
| `[safety] limp_fall` / `battery_empty_shutdown` | **false / false** | 他们为自训策略**关掉了保护层**。我们**不跟**：6.6 V 关断是唯一电学保护，跌倒卸力是唯一防烧舵机的手段 |

**顺带两条同源的一手数字**（官方 `docs/design/robotd-design.md` §2.1）：

- **`return_delay_time = 0` 是 Dynamixel 上的承重项，在 HD1910 上是无效项 —— 这段不能搬过来。**
  官方 `robotd-design.md` §2.1 说的是 XL330：出厂 250（×2 µs = 500 µs），16 颗合计 ~8 ms/tick、
  占 20 ms 预算 40%，所以必须归零。**三条独立证据同向表明 HD1910 上这一项不生效**：
  ① **官方内存表自注「STS 此地址无功能」**（地址确实没错，是 reg 7 / 1 B / 2 µs per LSB / 出厂 250；
  该注记由 `out/dl/ref_hl2915_bench.py:44` 抄录）；
  ② **第三方整机记录**（fanhao375）同样写「STS 系列上这项不起作用」，且他们整机跑通并未改它；
  ③ **本机实测**：reg7 读出 **253**，但单读 RTT 中位只有 **289 µs** —— 若 506 µs 延迟生效，
  RTT 不可能低于它。**读数与算术下界矛盾 ⇒ 错的是"它生效"这个假设。**
  ⇒ **不写 reg7=0（写了也是 no-op）**，20 ms 预算里没有这 8 ms。
- **这 4.8 ms 有整机实证，G0 的 ≤5 ms 闸门不再是我推的**：同型号 15 颗 + 同一个 URT-2，
  第三方整机记录给的是 **同步读 4.8 ms、0 超时 0 校验错**（7.2 V / 30–40 ℃）。
  4.8 ms ÷ 15 = **320 µs/颗**，与本机单颗 289 µs 相差 10% —— 两条独立测量一致，
  同时反证应答是**串行**的、且没有附加回传延迟。24% 的预算，可接受但必须算进 50 Hz。
- 官方出厂 `shutdown=53` 会因电压位在电池满电时**清扭矩**，他们改成 52。
  **HD1910 这一层出厂是关的 —— 不要以为有**：出厂 **reg19 = 4**，即只有 bit2（温度）启用，
  ⇒ 过压(bit0) / 过流(bit3) / 过载(bit5) / 磁编(bit1) **四项全关**。
  阈值确实都在（reg14 = **100 = 10.0 V**、reg15 = **40 = 4.0 V**、reg28 = **500 = 3.25 A**、reg13 = **80 ℃**），
  但**「阈值存在」不等于「保护生效」**——这一条我自己先写错过一次（见下）。
- **2026-11-04 台架判决：reg19 写成 13 = 电压(1) + 过热(4) + 过流(8)**。
  ⚠️ **落盘这条我翻了三次车，先把结论钉住**：第一次 `--apply` 回读 13、上锁 1，
  写"已落盘"；**断电重上电后回到 4**。真正活过断电的是第 4 次尝试（reg13 改 80→75→80
  的对照组也一起活过），唯一时序见文末「EEPROM 写入时序」。
  位映射（飞特官方教程原文）：`32 过载 / 16 空 / 8 过流 / 4 过热 / 2 磁编码 / 1 电压`。
  - **bit2 过热（厂默认就有）**：唯一阈值真的落在可达工况里的保护。堵转 2.0 A 数分钟即到 80 ℃，
    这是摔倒后腿被压住时的唯一兜底。
  - **bit0 电压**：10.0 V 对 2S 满电 8.4 V 有 **19% 余量**，规范工况永不触发；只在接错电源
    （3S / 可调电源拧过头）时卸力。**功能性 A/B 已证它真卸力且不因新指令解除**（下表）。
  - **bit3 过流**：阈值 **3.25 A = 1.6× 堵转 2.0 A**，规范工况永不触发；只对绕组/驱动短路这类
    硬故障动作。零代价保险。第三方整机（15 颗同型号）也是"过流、过压全开"后走起来的。
  - **bit5 过载（32）刻意关 —— 绝不能开**：判据是"指令到了、位置没跟上"，而 kp8（P=8、
    D=0、软）**带载稳态误差本来就是走路的常态** ⇒ 走两步就判成"被挡住" ⇒ 卸力 2 s 到 20% ⇒ 必摔。
    ⚠️ STS 系列出厂默认是 **52（含 32）**，**别拿"恢复出厂"当安全动作**。
  - **bit1 磁编码**：触发语义无文档、无阈值可核，一次误触发就是一次摔倒；先关，
    靠 reg65 的 BIT1 在日志里观察。

  | 台架 A/B（同一次过压条件，只差 bit0） | reg19 | reg14 | status(65) | 实际位移 |
  |---|---|---|---|---|
  | 对照 | 4 | 100 | 0 | **+59 步** |
  | 过压、bit0 关 | 4 | 40 | 0→1 | **−59 步**（照走） |
  | 过压、bit0 关、**告警稳定 1 s 后**再动 | 4 | 40 | 1 | **+59 步**（仍照走） |
  | 过压、bit0 开 | 5 | 40 | 1 | **0 步**（卸力） |
  | 恢复 | 4 | 100 | 0 | **−59 步**（自恢复） |

  第三行是补的：第一步"照走"有可能只是告警还没锁存（60 步在 400 步/s 下 0.15 s 就走完，
  而锁存要约 200 ms）——所以**先等告警稳定 1 s 再动**，结果仍是 59 步，结论才站得住。

  ⚠️ **过压卸载不因新指令解除**（要等电压回落），这与过流"来新指令即解除"不同 ——
  所以 reg14 不能设低，否则一次误判就是持续瘫软。
  ⚠️ **`reg65` 状态位段是无条件反映工况的**：bit0 关着的时候照样报电压位。所以
  "status 报了"不能当作"保护开着"的证据 —— 我第一次就是这么误判的，加了负对照才抓到。
  ⇒ 只读复核用 `servo_probe/set_protection.py --verify`，写入用 `--apply`（9 项自检）。

  **EEPROM 写入时序（四次尝试的台账，别自己重推）**

  | # | 时序 | 回读 | 断电后 | 判定 |
  |---|---|---|---|---|
  | 1 | 解锁 +0.05 → 写 +0.10 → 上锁 +0.10 | PASS | **回 4** | 窗口太短 |
  | 2 | 切 mode4→0 关扭矩（探针 0 步）→ 解锁 +0.10 → 写 +0.30 → 上锁 +0.30 → 模式改回 | PASS | **回 4** | **切 mode 把配置从 EEPROM 重载了** |
  | 3 | 同 2，且先写异值制造真实变化 | PASS | **回 4** | 同上 |
  | 4 | **上电（reg40 默认 0）→ 解锁 +0.25 → 写 +0.50 → 上锁 +0.50** | PASS | **保住 13** | ✅ 采用 |

  三条硬约束：
  1. **窗口 ≥0.35 s**。0.10 s 两次都失败；固件 commit 比"10 ms/字节"的旧假设长一个量级。
  2. **绝不切 mode**。切 mode 会重载配置，把刚写的值冲回旧值 —— 第 2/3 次就是毁在这一步。
     连带：mode 4 下 **reg40 关不掉扭矩**（写 0、回读 0，给 goal +60 步照走 58 步），
     而官方要求写 EEPROM 前扭矩必须是关的 ⇒ 只能借「**上电默认 reg40 = 0**」这个窗口，
     即**断电重上电后、robotd 起来之前**写。`--apply` 现在会在 reg40=1 时直接拒写。
  3. **值没变会被跳过 commit**（回读 PASS、掉电回旧值，与写失败同形）⇒ 已是目标值时
     先写一个异值再写回；并且**唯一判据永远是断电后 --verify**。
  4. 顺带证实：写入包的 **ERR 字节恒为 0**，锁着写也不报错 —— 不能拿 ERR 当判据。

  ⚠️ **台架供电只有 4.6 V（reg62 = 46），是部署点的 60%** —— 但仍在规格内，不是故障。

  官方规格（HD-1910-C001，三源一致：robotkingdom 规格表 / juxitech / chenkui164 训练前数据清单）：
  **工作电压 4–8.4 V，典型 6 V**；堵转扭矩 9 / 12 / 15 kg·cm，堵转电流 1.2 / 1.6 / 2.0 A，
  空载 72 / 92 / 113 RPM，额定 2.2 / 3.0 / 3.7 kg·cm，额定电流 500 / 690 / 900 mA
  （依次为 **4.8 V / 6 V / 7.4 V** 档，供应商公差 ±10%）。

  | 量 | 台架 4.6 V | 部署 2S（6.6–8.4 V） | 台架/部署 |
  |---|---|---|---|
  | 堵转扭矩 | ≈8.6 kg·cm（插值） | 15 kg·cm @7.4 V | **约 57%** |
  | 空载转速 | ≈69 RPM | 113 RPM @7.4 V | 约 61% |
  | 堵转电流 | ≈1.15 A | 2.0 A @7.4 V | 约 57% |

  **哪些结论受这条影响、往哪边偏**（四条，全部偏保守 ⇒ 不必重做，但换 2S 后要抽查）：
  - **kp8 平台**：P8 是在只有 57% 扭矩的条件下走起来的 ⇒ 部署侧扭矩余量更大，结论更成立。
  - **duty% ≈ 5.1·kp（kp8 ⇒ 40.8%，留 2.47× 电流余量）**：reg60 是 PWM 占空比，
    同一负载力矩下 duty 大致随 1/V 缩放 ⇒ 7.4 V 时约 **0.62×**（≈25%），余量更宽。**这条是推的**（按阻性项线性缩放，未实测）。
  - **双向最小可动步 2/2 = 0.176°（上界 0.35–0.44°）**：可动步下限由"可用扭矩 vs 摩擦+齿隙"决定，
    扭矩只有 57% 时量出的步数只会**偏大** ⇒ 也是保守上界。
  - **不受影响**：同步读 4.8 ms / 289 µs RTT（协议层）、reg19 过压 A/B（那次把 reg14 压到 4.0 V 才触发）。

  🔴 **但 bit0 落盘后多了一个新风险**：reg15 = 40 = **4.0 V** 欠压阈值，离台架的 4.5–4.6 V 只差
  **0.5–0.6 V**。堵转拉 1.15 A 时一条 USB 5 V 线/端子掉 0.6 V 毫不稀奇 ⇒ **台架上会出现
  "莫名其妙卸力几秒"**，而且它长得像"策略/增益问题"。4.6 V 下做台架测试前先看 `reg62`；
  真要做扭矩相关的测试，把台架供电换成**机器人自己那块 2S 电池**（6.6–8.4 V，正好等于部署电压，
  且 4.0 V 阈值离得远）。⚠️ 别用 USB-PD 的 9 V 档 —— 超过 8.4 V 上限，10.0 V 过压阈值也只剩 10% 余量。
- 修一个数字：**reg28 是 2 字节**（28 低 / 29 高）。只读 1 字节会拿到 `0xF4 = 244`，
  于是把 3.25 A 误算成 1.59 A。×6.5 mA/LSB ⇒ **500 = 3.25 A**。
  反证也简单：0.5 A（某些二手文档的写法）低于额定 900 mA，正常工作就会触发，不可能是它。
- ⚠️ **我在这条上先写错了一次，记下来当负样本**：看到 reg14 = 100（10.0 V）就推出
  "过压保护是活的、余量够"。错在把**阈值**当成了**开关**——真正的开关在 reg19，
  而 reg19 早就在 11-01 的记忆里（`reg19=4`），我没去查。
  抓法还是老一套：**拿第二个来源（记忆里的 reg19）去撞第一个来源（reg14）**，
  两个都"合理"但不可能同时成立（有 10.0 V 阈值 vs 只有温度保护开着）。
