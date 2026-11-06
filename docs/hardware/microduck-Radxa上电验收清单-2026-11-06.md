# MicroDuck (HD-1910) Radxa 版上电验收清单

_2026-11-06 起草。配合 `microduck-kissqy HAT引脚分析-Radxa闭环-2026-11-06.md`（电气闭环）与 `microduck-双版本推进-Radxa与OrangePi-2026-11-06.md`（路线决策）使用。_

_本清单是**拿到硬件后**的逐项验收，每条都有明确的 **PASS / FAIL 判据**。所有硬结论均来自一手源码 / 官方 brief / PCB 解析，已在上述两份文档闭合，此处只做"怎么验"的落地。_

---

## 0. 验收对象（路线已定）

- **主控**：Radxa ZERO 3W 2GB（RK3566，Pi Zero 板型 65×30）
- **HAT**：kissqy `RPI_Robot_HAT`（40-pin RPi HAT 形态，舵机 TTL + IMU I2C + 音频）
- **机械件**：fanhao375 飞特版 v2.2 打印件（**零改动**，该 CAD 实机即 Radxa）
- **舵机**：HD-1910（凸盘，飞特版 v2.2 已适配）
- **软件镜像**：kissqy V167 / fanhao 镜像（本就是 Radxa）
- **电源**：2S 锂电池（7.4 V 档）

> 本仓 Orange Pi 载板（`cad/orangepi_zero3w_carrier.scad`）在 Radxa 路线下**作废**，仅保留给 Orange Pi 分支。

---

## 1. 备料清单（装机前静态核对）

| # | 物料 | 关键规格 / 核对点 | 判据 |
|---|---|---|---|
| 1.1 | Radxa ZERO 3W | 2GB 版，板型 65×30 | 板面丝印 "RADXA ZERO 3W" |
| 1.2 | kissqy RPI_Robot_HAT | 40-pin 母头 = J4，舵机口 J3/J11 | 插上后 40-pin 物理贴合，无顶针错位 |
| 1.3 | 飞特版 v2.2 打印件 | 33 件 + 原 RPi 托架 | 托架按 Radxa 建模，直接装 |
| 1.4 | HD-1910 舵机 ×15 | 凸盘，飞特版 v2.2 已适配 | 盘型与 CAD 一致，不混用平盘 |
| 1.5 | 2S 电池 | 7.4 V 档（**非 3S**） | 实测满电 ≤ 8.4 V |
| 1.6 | URT-2 调试板 | 台架调试用 | 持有，未上电前不接电机线 |

**FAIL 处理**：1.5 若误用 3S，见 §6.3（battery cells 配置陷阱）。

---

## 2. 装机前静态检查（不通电）

| # | 检查项 | 操作 | PASS 判据 |
|---|---|---|---|
| 2.1 | HAT 方向 | 40-pin 母头对准 Radxa 排针，缺口朝板边 | 完全插到底，无歪斜 |
| 2.2 | 舵机排线 | J3/J11 接 15 颗舵机总线（BATT/GND/DATA） | 极性不错位（红=BATT、黑=GND、黄/绿=DATA） |
| 2.3 | IMU 落点 | HAT 上的 IMU 模块在板载 I2C 上（非 40-pin 飞线） | 模块焊接完好，无虚焊 |
| 2.4 | 电池不接 | 装机阶段**先不接电池** | 万用表量 HAT 供电端无短接（< 1 Ω 报警） |

---

## 3. 首次上电（boot + 节点确认）

> 先接 **USB-C 供电**（不走电机电池），串口/SSH 进 Radxa。

| # | 操作 | 命令 | PASS 判据 |
|---|---|---|---|
| 3.1 | 确认启动 | 串口看 U-Boot → Linux 内核启动日志 | 无 panic，进 login |
| 3.2 | 舵机总线节点 | `dmesg \| grep tty` | 出现 **`/dev/ttyS2`**（UART2_M0）。⚠️ 若显示 `ttyFIQ0` 等别名，以 `dmesg` 实际名为准，功能层已由官方 brief 钉死 Pin8/10=UART2_M0 |
| 3.3 | 节点可读写 | `ls -l /dev/ttyS2` | 存在且当前用户有 rw 权限（否则 `usermod -aG dialout $USER`） |
| 3.4 | 镜像 UART 服务 | 确认镜像未把 ttyS2 占作登录控制台（kissqy/fanhao 镜像已处理） | `cat /proc/cmdline` 无 `console=ttyS2`；或 robotd 能 open 成功 |

**FAIL 处理**：3.2 若节点名不符，先 `dmesg` 定位真实节点名再改 robotd 配置，不臆改引脚。

---

## 4. 舵机总线验收（1 Mbps 复验）

**结论前置**：Radxa RK3566 UART2_M0 支持 1 Mbps；主仓 robotd 正是把它当舵机总线跑 1 Mbps ⇒ **15 颗舵机 EEPROM 一颗都不用写**，`BAUD_RATE` 保持 1 Mbps、`BAUD_REGISTER_VALUE` 保持 0。

| # | 操作 | 工具 / 命令 | PASS 判据 |
|---|---|---|---|
| 4.1 | 扫 ID×1Mbps | 复用台架 `sts_bench.py`（或等价 ping 脚本）扫 15 颗 ID | 15/15 在 1 Mbps 下全部应答，无丢包 |
| 4.2 | 不写 EEPROM | 确认未对任何舵机执行波特率改写 | `BAUD_REGISTER_VALUE=0`，EEPROM 维持出厂 |
| 4.3 | 速度标度复验 | 台架 `probe_pgain_speed.py` 或标定脚本 | 速度标度 ≈ **0.732 rpm/count**（台架 ratio 49.44 vs 理论 49.97） |

**FAIL 处理**：
- 4.1 部分 ID 无应答 → 先查排线极性 / 总线终端电阻 / 供电，不先怀疑波特率。
- 4.3 标度偏离 > 5% → 重测传动比，确认齿轮箱与飞特版一致。

---

## 5. IMU 验收（I2C 总线号 1→3）

**结论前置**：HAT 的 IMU 接在 40-pin **Pin 3/5 = RPi I2C1**；Radxa Pin 3/5 = **I2C3** ⇒ 软件把 I2C 总线号从 `1` 改成 `3`，**非物理不兼容**。

| # | 操作 | 命令 | PASS 判据 |
|---|---|---|---|
| 5.1 | 扫 I2C3 | `i2cdetect -y 3` | IMU 出现在预期地址（类 0x68 / 0x69） |
| 5.2 | 配置对齐 | robotd / 镜像 IMU 配置总线号 = **3** | 启动后 IMU 读数非空、不报 "cannot open i2c-1" |
| 5.3 | 姿态合理 | 静置读四元数 → 重力轴 | `w = +sqrt(1-n²)`（ST 芯片只发 qx,qy,qz，qw≥0 always，有 ST 背书）；静止时 gravity_z ≈ -1 |

**FAIL 处理**：5.1 若 I2C3 扫不到 → 确认 HAT IMU 是否真接 Pin3/5（而非板载独立 I2C）；必要时改总线号或飞线。

---

## 6. robotd 配置校验（关键寄存器 + 部署档）

> 这部分是**软配置硬约束**，错一个会导致电机不转 / 误驱动 / 配置整份加载失败。

### 6.1 开机硬校验（checked, not corrected）
robotd 开机读 EEPROM 并校验以下寄存器，不符只告警不纠正：

| 寄存器 | 期望值 | 台架实测值 | 处置 |
|---|---|---|---|
| reg6 | **1** | 台架 0 | **必改**（写 1） |
| reg33 | **0** | 台架 4 | **必改**（写 0） |
| reg9 | 0 | 0 | OK |
| reg11 | 4095 | 4095 | OK |

→ PASS：`robotd` 启动日志校验项全部 `checked, not corrected` 且无 `MISMATCH` 致命报错。

### 6.2 部署档 / 总线配置
| 键 | 取值 | 说明 |
|---|---|---|
| `[bus] servo` | `"feetech_hls"` | **无 `protocol` 键**；缺 `joint_ids` 总线拒绝打开 |
| `[bus] joint_ids` | 15 颗实际 ID | 必须填，否则总线不开 |
| `[bus] imu_median` | **false** | 上游默认 true（故意偏离）：中值=纯一拍延迟 20ms，而训练侧 IMU 延迟包络 0–20ms |
| `[battery] cells` | **`[2]` + `max_volts=8.4`** | ⚠️ 默认 `[2,3]` 会把 3S 判合法并照常驱动 ⇒ 必须显式写 `[2]` |
| `[bus] position_kp` | 8（与 gain=200 保持） | 第二写者 robotd：`reg50 = clamp(round(gain×kp/200),1,254)`，保持 P/D 环闭合 |
| `[bus] position_kd` | 8（非 0） | D=8 |

### 6.3 battery cells 陷阱（重点）
- **FAIL 场景**：配置漏写 `[battery] cells` 或误写 `[2,3]`，且误接 3S 电池 → robotd 判合法、照常驱动 7.4 V 档舵机于 12 V，**烧毁风险**。
- **PASS 判据**：配置中显式 `[2]`，且 `max_volts=8.4`；上电前电池实测 ≤ 8.4 V。

### 6.4 P/D 环闭合确认
- reg50/51 是 **live P/D**（STS 手册标"无定义"，但台架实测写 reg50 改变带宽）；固件上电拷贝 EEPROM 21/22 → RAM 50/51。
- PASS：`robotctl` 读写 reg50/51 生效，带宽随写入变化（参考台架 P8→24 gain 0.350→0.744）。

---

## 7. 策略加载验收（p8head_2999）

**结论前置**：官方 robotd 加载校验比 B 代严得多（"policy load 只查宽度"是 B 代口径，已推翻）。`p8head_2999` / `resume_5999` 经一手源码闭合可被官方 robotd 加载（commit `8abc225`）。

| # | 操作 | 命令 | PASS 判据 |
|---|---|---|---|
| 7.1 | 导出 ONNX | `export.py` → ONNX | obs 61 / act 14 / 50 Hz，无 EXTERNAL 权重（见 7.3） |
| 7.2 | 推理 / 发布 | `infer_policy.py --walking` → `uv run publish` → `robotctl policy load` | 加载成功，无字段 mismatch |
| 7.3 | 权重打包 | 确认 publish 未因 split 导出丢权重 | onnx 图无 EXTERNAL（split 导出会以 3 KB 无权重图上传成功 → 拷到机器人前必须确认） |
| 7.4 | ✅ 归一化下限 | 部署用 `p8head_2999`/`resume_5999`（下限 0.01289） | 规避 `deploy61` 下线问题（归一化分母差 1157× ⇒ 5.7° 头命令 → 动作 −35.7 rad） |

---

## 8. 台架 / 安全验收

| # | 项 | 配置 / 判据 |
|---|---|---|
| 8.1 | 跌倒判据 | `fall_gravity_z = -0.5`（≈60°），debounce 200 ms |
| 8.2 | FallPredictor | 26° + 速率 + 300 ms 外推 → `gain_limp=50` → 0.6 s 回站姿 |
| 8.3 | deadman | `deadman_ms=500` 只归零 twist（超时断遥控） |
| 8.4 | 限位 / 温度 / 电流 | **无关节限位**；温度/电流只观测不判 |
| 8.5 | 台架供电差异 | 台架 4.6 V 取的数（kp8/duty/齿隙）是**欠压值**；真机 7.4 V 后要重测相关读数 |

**PASS 判据**：8.1–8.4 配置与预期一致；真机首次站立在**限位/低速**下做，确认 0.6 s 回站姿逻辑触发正常。

> **轮滑变体注记**（细节见 `microduck-两版轮滑变体组件与装配计划-2026-11-06.md`）：轮滑版硬件零改动——电源、总线、寄存器校验全套沿用本清单。差异只在软件：策略用 `roller` 系（`roller`/`roller_crouch`/`roller_standup` 等）+ `action_scale 0.8`（walk 为 0.9），且 8 台架项目轮滑版应改为**离手推滚试顺滑**；站起判据换 `ROLLER_STAND_Z=0.138`。轮滑件（TPU 合体轮胎/叶片/6×12×3 轴承）与走路件不可混装。

---

## 9. 总判

| 阶段 | 全 PASS 后结论 |
|---|---|
| §3 上电 | 节点 `/dev/ttyS2` 可用 |
| §4 总线 | 15 舵机 1 Mbps 全通，EEPROM 免写 |
| §5 IMU | I2C3 可用，姿态合理 |
| §6 配置 | 寄存器校验过、电池/总线/IMU 配置正确、P/D 闭合 |
| §7 策略 | p8head_2999 官方 robotd 加载成功 |
| §8 安全 | 跌倒/回站/死人开关就绪 |

**任一阶段 FAIL** → 先回对应章节定位，**不臆改引脚/波特率/EEPROM**。Radxa 路线机械零改动、电气插上即用，绝大多数 FAIL 会落在软配置（§6）或排线极性（§2/§4），而非硬件不兼容。

---

## 附：本仓关联交付物

- `microduck-两版轮滑变体组件与装配计划-2026-11-06.md` —— 轮滑变体（走路的替代形态）组件、装配与软件差异；硬件验收口径与本清单完全共用
- `microduck-kissqy HAT引脚分析-Radxa闭环-2026-11-06.md` —— 电气引脚闭环证据
- `microduck-双版本推进-Radxa与OrangePi-2026-11-06.md` —— 路线决策与进度
- `microduck-飞特版3D打印件-OrangePi适配清单-2026-11-06.md` —— 打印件适配（Radxa 版零改动）
- `docs/active/microduck-HD1910软件方案.md`、`docs/active/microduck-板子设计备忘.md` —— 寄存器/部署档一手来源
