# IMU 三方对照：666wsp · kissqy · DuckBuddy

_2026-11-05。三方定位：**666wsp** = 通用 IMU 板厂商（IMU_TO_DXL）；**kissqy** = HD1910 复刻社区作者（自制 HAT+IMU，淘宝卖套件）；**DuckBuddy** = 上游软件（robotd/duck-control）+ 参考硬件（PDB/IMU R2f）。目的：判断买的 IMU 板能不能接上自己跑的 DuckBuddy robotd。_

**一句话结论：IMU 板固件决定了同步读里 IMU 的排队位置，而 666wsp 与 kissqy 的固件都要求「IMU 排第一位」，DuckBuddy 的 robotd（HD1910/feetech 后端）却硬编码「IMU 排最后」且总线跑 500k。两者不能直接对接——要么改 robotd 的排队顺序，要么用 DuckBuddy 自己的 IMU 固件/板。原生匹配只有 DuckBuddy 的 PDB/IMU 板。**

## 0.1 标定流程权威源（2026-11-07 补 · 修正原缺口假设）

> 原"缺资料"复核把 `build-tutorial` 的 `bno08x_calibrate_ui.py` 列为应引的 IMU 标定流程——**核实后发现这是错配**：该 build-tutorial（AI-FanGe/Microduck-build-tutorial 中文复刻）IMU 用的是 **BNO08x** 系列（README BOM 与 `IMU_MOUNT_QUAT` 朝向约定），而我们的 HD-1910 线是 **LSM6DSV16X**（§0.5 三方同芯片），**不是同一颗**，其 BNO08x 标定脚本不可直接套用。

正确的 LSM6DSV16X 相关权威源（均本地 `.upstream`）：

- `community-kit/firmware/v1/docs/lsm6dsv16x_driver_spec.md` —— LSM6DSV16X 驱动规格（寄存器/量程/融合）。
- DuckBuddy `imu-feetech` 固件（STM32G031 + LSM6DSV16X，500k，原生匹配，见 §0.5）—— 这是和我们硬件真正对口的 IMU 实现。
- 安装朝向约定：build-tutorial 的 `IMU_MOUNT_QUAT` 思路可借鉴，但取值必须按 LSM6DSV16X 在 HD-1910 上的实际安装方向重新确定（不可抄 BNO08x 的值）。

真正对 HD-1910 **整机标定（关节零位/方向）** 有用、且开源可查的"标定流程"参照是社区工具（见 `awesome-microduck` 的 *Calibration and Assembly Tools* 段）：

- `janauto/microduck-calibration-guide` —— 只读关节方向核对，不驱舵机，动画比对预期运动。
- `lxm/microduck-maker` —— 逐关节零位标定 + 3D 参考 + 装配检查（含 kissqy 非商用例）。
- `jackwuwei/microduck-tools` —— SSH/串口零位标定工作台 + 打印标定托盘。

⇒ 本笔记后续若补"标定"章节，应引上述 LSM6DSV16X + 社区工具，而非 build-tutorial 的 BNO08x 脚本。

## 0. 先澄清一个常见误判：A733 的 UART7 上不了真 1 Mbps ≠ 性能不如 Radxa

DuckBuddy INTERFACE-CN.md 注明「A733 的 UART7 设 1 Mbps 实际只有约 750 kbps，所以统一用 500k」。这**不是 A733 的劣势**：

- **总线根本不需要 1 Mbps**。每 tick（50 Hz）一次同步读 16 设备 ≈ 295 字节，500 kbps 下占线 ~4.7 ms / 20 ms = **~24%**，余量 4 倍。DuckBuddy 整套（含自己的 IMU 固件 imu-feetech）就是跑 500k。
- **Radxa 上也是跑 500k**，不是 1M。1M 在两家平台上都没被用上，A733 少一个用不到的 capability 不构成劣势。
- **1 Mbps 只是第三方 IMU 固件的出厂默认**：666wsp 板可用 FD.exe 改；kissqy FT6 锁 1M；DuckBuddy 自己的 IMU 固件就是 500k。
- 且 A733 在 CPU（2×A76+6×A55@2.0GHz 八核 vs 4×A55@1.8GHz）、NPU（3 TOPS vs 0.8）、内存（LPDDR5 vs LPDDR4）上全面更强；DuckBuddy upstream 主控就是香橙派 Zero 3W（已验证整机运行）。

**唯一 relevant 的情形**：硬要用锁 1M 的第三方 IMU 固件时，A733 喂不饱 → 把板降到 500k 或换 DuckBuddy IMU 固件，三条路都通。

## 0.5 以 A733 为主控 · 结合三家的长处（2026-11-05 本轮结论）

你的整机配置：**香橙派 Zero 3W（A733）+ 15×HD-1910 + 2S**。软件可自己改，所以「同步读顺序 / 波特率这类软件冲突」不再是阻塞项；真正定生死的只剩**硬件物理层**。本轮逐一核实如下。

### 本轮确认的硬件底线

1. **A733 与树莓派 Zero 同 footprint**（65×32 mm、40 针同布局，第三方实测「compatible with existing Pi Zero HATs」）。DuckBuddy HAT（65×30 mm、58×23 mm 孔距、四角 Ø2.75 安装孔）可直接叠插。→ **HAT 物理兼容：通过**。（且 DuckBuddy `INTERFACE-CN.md` 架构图标题就是「Orange Pi Zero 3W」——这块板子本来就是照着它设计的。）
2. **A733 的 UART7 = pin16(PL2 TX)/pin18(PL3 RX)**，DuckBuddy HAT 的 J1 信号表正好是「16/18 = UART7(`/dev/ttyS7`)」。→ **总线引脚：原生对齐，零适配**。
3. **DuckBuddy PDB 分 2S / 3S 两个版本**：2S 版配 HD-1910（启动≈6.3 V，背面标「2S」），3S 版配 HL-2915（启动≈8.5 V）。**2S 版不能装到 3S 机器人**，否则欠压锁定失效。→ **买 HD-1910+2S 必须认准 2S 版 PDB**。HAT 由 5 V 降压给 A733 供电（引脚 2/4），无需单独 USB 供电。

### 三家长处 × A733 兼容性矩阵

| 板 + 固件 | 与 A733 配不配 | 关键约束 | 判定 |
|---|---|---|---|
| **DuckBuddy PDB/IMU + imu-feetech**（STM32G031，500k，IMU 后） | ✅ 原生 | 无 | **最贴合，零改动** |
| 666wsp IMU_TO_DXL（CH32V203，1M，IMU 前） | ⚠️ 需改软件 | FD.exe 把 1M 调到 500k（**需实测确认**）+ 改 robotd 把 IMU 放首位 | 可达成，改动中等 |
| **kissqy RevA + FT6**（STM32G031，**1M 固定**，IMU 前） | ❌ **硬件制约** | **FT6 固件锁 1 Mbps，A733 UART7 设 1M 实际只有 ≈750 kbps，喂不起真 1M** | **直接不兼容，除非重刷固件** |

> **本轮最关键的新结论**：kissqy 的方案要分两种固件看待——它的 **FT6 固件锁 1M**，在 A733 上**物理上跑不起来**；但 kissqy 板本身是 **STM32G031 + LSM6DSV16X**（和 DuckBuddy PDB/IMU 同芯片同传感器），**刷成 DuckBuddy 的 imu-feetech（500k）就变成原生匹配**。所以 kissqy 板能用，前提是重刷固件 + 逐脚核对引脚（见 §5）。

### 「结合三家长处」到底怎么结合

三方的真实长处各是一条：
- **DuckBuddy**：主控软件栈 + 原生 A733 的 HAT/PDB 参考设计（软硬件最匹配，且是你能直接抄的板级方案）。
- **666wsp**：IMU 板自带的诊断最全（`status`/`sequence` 字节、READER_SLOW 告警、SELF_TEST 位），FD.exe 可改波特率、总线 OTA。
- **kissqy**：淘宝成品 HAT+IMU（≈¥150，AMP2.0 到手即用）+ 完整的 HD1910 复刻社区资料。

**最务实的组合**：以 **DuckBuddy HAT + PDB(2S 版) + robotd** 为骨架（原生匹配、你一直审它的 TOML，最省事）；想要 IMU 板自带的丰富诊断位，就把 IMU 换成 **666wsp**（FD.exe 调 500k + 改 robotd 把 IMU 放首位）；**kissqy 只在「想要到手即用且不介意重刷 IMU 固件」时选**。

## 1. 关键判据：同步读顺序是固件属性，不是总线属性

这是整个对照的核心。DuckBuddy 在 feetech.rs 里注释的实测：

> 「Feetech servos do not wait to hear the device ahead of them finish... a board that answers even ~60 µs slower than a servo has its reply's tail trampled by the next servo (measured: **990/1000 reads clean with the IMU first, 1000/1000 with it last). The IMU firmware counts the replies ahead of it before speaking, and nothing follows it.**」

注意最后一句：**「IMU firmware counts the replies ahead of it before speaking」**——这是 DuckBuddy **自己的 imu-feetech 固件**的设计：它会先数前面有几个应答再开口，所以放最后最稳（1000/1000）。

而 666wsp 和 kissqy 的固件**没有这个「数前面应答」的逻辑**，它们假设「主机发完我立刻回」，因此强制要求 IMU 排第一。所以：

| IMU 固件 | 同步读位置要求 | 理由 |
|----------|----------------|------|
| DuckBuddy imu-feetech（STM32G031） | **排最后** | 固件会数前面的应答数，放最后无尾踩 |
| 666wsp IMU_TO_DXL（CH32V203） | **排第一位** | 主机发完立刻回，禁止别的设备插前面 |
| kissqy FT6_SYNC15（STM32G031） | **排第一位** | 同上；文档明写「不移植社区未经实测的其他位次排队逻辑」 |

## 1. 三方 IMU 硬件对照

| 项目 | 666wsp IMU_TO_DXL v1.2 | kissqy IMU RevA（FT6） | DuckBuddy PDB/IMU R2f |
|------|------------------------|------------------------|------------------------|
| MCU | CH32V203（RISC-V 96 MHz） | STM32G031F8P6 | STM32G031 |
| 传感器 | LSM6DSV16X + SFLP | LSM6DSV16X + SFLP | LSM6DSV16X + SFLP |
| 从站 ID | 200（可改） | 200（固定） | 200 |
| 波特率 | **1 Mbps，FD.exe 可改**（±2%） | **1 Mbps 固定** | 随总线 500k |
| FT 数据块 | addr 56，15 字节 | addr 56–70，15 字节 | addr 56，读 15 用前 12 |
| 板尺寸 | 34.0 × 42.3 mm | 22.7 × 25.6 mm（两层） | PDB+IMU 合一 |
| 获取方式 | 666wsp 渠道（裸板/资料） | 淘宝 kissqy 套件 HAT+IMU（¥150，AMP2.0，到手即用） | DuckBuddy 参考硬件 |
| 15 字节布局 | gyro6 + quat6 + seq + status + reserved | gyro6 + quat6 + u8计数 + u8状态 + reserved（另 addr124–143 有 20 字节诊断区） | 同前 12 字节（gyro+quat） |

**字节级一致**：三方前 12 字节都是 gyro x/y/z（int16）+ quat x/y/z（half），W 由主机补 `√(1−x²−y²−z²)`，陀螺刻度 17.5 mdps/LSB。DuckBuddy 只消费这前 12 字节。

## 2. 三方软件栈对照

| 项目 | 666wsp 配套 | kissqy 配套 | DuckBuddy 上游 |
|------|-------------|-------------|----------------|
| 主控软件 | 无（只给板+固件+工具） | R17 V167 中控 / control.43 | robotd / duck-control（feetech.rs） |
| 总线波特率 | 1 Mbps（示例） | **1 Mbps 整机** | **500 kbps**（`BAUD_RATE=500_000`，feetech.rs:35） |
| 同步读 IMU 位置 | 第一位（固件要求） | 第一位（固件要求） | **最后一位**（feetech.rs:314-316 硬编码 `ids.push(IMU_DXL_ID)`） |
| 是否可配置顺序/波特率 | — | — | **无配置键**（只 `imu`/`imu_axes`/`imu_median`/`imu_pitch_trim_deg`/`imu_roll_trim_deg`，顺序与波特率写死） |
| 实测验证 | 开发资料 | 整机长时间验证正常 | 990/1000(前) vs 1000/1000(后) |

DuckBuddy 侧确认：`deploy/robots/opi-hl2915-rev-a.toml` 里 IMU 相关只有上面 5 个键，**没有任何「IMU 排前/排后」或「IMU 波特率」的配置项**——顺序和波特率在 feetech.rs 里写死。

## 3. 兼容性矩阵（你的 DuckBuddy robotd × 三种 IMU）

| IMU 板 + 固件 | 接 DuckBuddy robotd 结果 |
|----------------|--------------------------|
| **DuckBuddy PDB/IMU + imu-feetech**（STM32G031，500k，IMU 后） | ✅ **原生匹配**，无需改动 |
| **kissqy RevA + FT6**（STM32G031，1Mbps，IMU 前） | ⚠️ **MCU 相同，但固件要 IMU 前 + 1Mbps**。robotd 是 IMU 后 + 500k，对不上。两条路：① 把 IMU 板重刷 DuckBuddy imu-feetech 固件（同 MCU 同传感器，但**需核对引脚定义**，见 §5）；② 改 robotd feetech.rs：IMU 插首位 + 总线跑 1Mbps（还要重配 15 个舵机到 1M） |
| **666wsp IMU_TO_DXL + 自有固件**（CH32V203，波特率可改，IMU 前） | ❌ **MCU 不同**（CH32V203 ≠ STM32G031），**无法刷 DuckBuddy 固件**。只能用 666wsp 自己的固件，那就必须改 robotd 把 IMU 插首位，波特率用 FD.exe 调到与总线一致 |

## 4. 三个坑（按严重度）

1. **MCU 不兼容（666wsp）**：CH32V203 跑不了 DuckBuddy 的 STM32 imu-feetech 固件。买 666wsp 板 = 绑定它自己的固件 = 必须改 DuckBuddy robotd 的同步读顺序。这是最重的改动。
2. **波特率（kissqy）**：kissqy FT6 固件 **1 Mbps 固定**。DuckBuddy HD1910 总线是 **500k**。要让 kissqy IMU 上 DuckBuddy 总线，要么整机升到 1Mbps（15 个舵机也要重配），要么别用 kissqy 固件。
3. **同步读顺序**：666wsp/kissqy 固件强制 IMU 前，DuckBuddy robotd 硬编码 IMU 后。这是软件层面的硬冲突，改 robotd 才能接。

## 5. 待核对项（下单前）

✅ **2026-11-06 三条都已核实**（逐条证据见 `docs/reference/microduck-未核实项核查报告-2026-11-06.md` §2.3 / §4）：

- **kissqy IMU 板引脚 vs DuckBuddy imu-feetech —— 逐脚核对完成**：
  | 功能 | DuckBuddy `imu-feetech/src/main.rs:9-14` | kissqy `imu-source/src/main.c:140-152` | 判定 |
  |---|---|---|---|
  | MCU | STM32G031F8P6 TSSOP-20 | STM32G031xx | ✅ 同族 |
  | USART2 TX/RX | PA2 / PA3 | PA2 / PA3 (AF1) | ✅ |
  | SPI1 | PA5 SCK / PA6 MISO / PA7 MOSI / PA4 CS | PA5/6/7 (AF0) / PA4 active-low CS | ✅ |
  | **DE 方向使能** | **PA1 = 74LVC1G126 OE，USART2 硬件 DE，发送期间拉高** | **PA1 = `active-low DXL_TX_EN`，软件 GPIO** | ❌ **有效电平相反** |
  | 其它 | 64 MHz PLL / 500k | 16 MHz HSI / `DXL_BAUD=1000000` / PA0 DEBUG_LED | △ 各自固件管理 |

  ⇒ **引脚号几乎全同，但 DE 极性相反**：直接刷 DuckBuddy 固件会导致总线被一直驱动（抢占）或从不发声（不应答）。「刷成原生匹配」**必须改一行把 DE 有效电平反转**，再台架验。这是「电气检查全过、症状是整条总线失联」的静默 bug 形状。
- **DuckBuddy imu-feetech 固件源码位置**：`.upstream/DuckBuddy-main/firmware/imu-feetech`（本地已有），可作为重刷参考。
- **666wsp 板 BAT+ 电压范围 —— 已定**：原理图 PDF 提取出 U2 = **`HT7533-1`**（Vin 2 / Vout 3），Holtek 官方 `HT75xx-1` datasheet：`VIN max 30 V`、`4.3 V ≤ VIN ≤ 30 V`（Line Regulation 条件）、3.3 V±3% / 100 mA。⇒ **BAT+ 推荐 4.3–30 V，2S 6.6–8.4 V 安全**；3S 前仍需核 10 µF 电容耐压（原理图未标）。原理图同时给出 U4=`CH32V203F8U6`、U3=`LSM6DSV16XTR` 走 **SPI**、CN2/CN3=`A2007WR-3P`、D2=`RCLAMP0521T`（在数据线上，非电源）。

## 6. 给你的选择建议

你的软件栈是 **DuckBuddy robotd**（本项目一直在审它的 TOML）。因此：

- **最省事**：用 **DuckBuddy 自己的 PDB/IMU 板 + imu-feetech 固件**（500k，IMU 后），原生匹配，零改动。
- **想用 kissqy 淘宝套件（¥150，到手即用）**：IMU 板是 STM32G031，理论上能刷 DuckBuddy 固件，但**必须先核对引脚**（§5）。核对通过则重刷成 DuckBuddy IMU，变成原生匹配。核对不通，就得改 robotd（IMU 前 + 1Mbps），工作量大。
- **不建议买 666wsp 板接 DuckBuddy**：CH32V203 刷不了 DuckBuddy 固件，又强制 IMU 前，改动最重。除非你就是要做 666wsp 固件 + 自改 robotd 的路线。

> ⚠️ 注意：kissqy 的 HAT+IMU 套件是配 **kissqy 自己的 control.43 / R17 中控**（1Mbps，IMU 前）用的，不是配 DuckBuddy robotd。买它的前提是接受 kissqy 那一整套软件栈，或愿意重刷 IMU 固件+核对引脚。

---

## 7. 2026-11-06 重要修正：排队位冲突的根因是**两套协议**，不是固件口味

> 新证据：`jyg9/microduck_ft1910`（官方 `pollen-robotics/microduck` 0.16.0 的飞特 SCS/HLS 适配 fork）
> `docs/design/scs-bus.md`，以及 `jyg9/microduck-community-kit` `firmware/v1/docs/bus_timing_borrow_plan.md`
> （GD32F303CC 固件的真机联调报告）。详见 `docs/reference/microduck-开源资料全景-2026-11-06.md` §3。

### 7.1 此前本文 §1 的判断需要收窄

§1 写「同步读顺序是固件属性」——这话不错，但**把两件不同的事混成了一件**。
实际有两条协议路径，让位算法、地址、块长、位次规则全都不同：

| | **Dynamixel 路线** | **飞特 SCS/HLS 路线** |
|---|---|---|
| 同步读指令 | `0x8A` **Fast Sync Read**（一台设备发一个聚合帧，逐段累积 CRC-16） | `0x82` SYNC_READ（每个被点名设备各回一帧，8 位取反校验和） |
| 读取地址 / 长度 | addr **124** / **12 B** | addr **56** / **15 B**（文档化块 56..70） |
| IMU 位次 | **第 0 位**（官方 tick 读 `[200] + 15 关节`） | 也是**第一位**，因为「协议让每个设备按列表位置对应的槽应答」 |
| 让位规则 | 按**前面 k 段的字节数**让位 `8 + k×(X+4)` | 按**槽**让位，实测 **≈295 µs/槽**，且**前导设备缺席也照样占一槽** |
| 缺席判定 | 聚合帧缺一段即整包作废 | `BURST_IDLE=4 ms` 静默收尾（实测相邻应答最长间隔 1.94 ms，**2 ms 会被调度抖动截断**） |
| 波特率 | 1 Mbaud | 1 Mbaud（ft1910 first light：RK3566 `/dev/ttyS2` @1M，50.0/50.0 Hz、0 missed/436 ticks） |

`community-kit` 固件报告 D10 明确：**在 `0x8A` 下按「槽」让位必撞包**（一段只有 `(X+4)×10 µs`，比 295 µs 短）。
所以「IMU 必须排第一」不是各家固件的偏好，而是**两套协议各自的物理时序约束**。
而 DuckBuddy 的 `feetech.rs` 把 IMU 排最后、跑 500k，是它自己那条 500k 飞特路径上的实现
（注释给的实测「IMU 在前 990/1000 干净、排最后 1000/1000」仍成立，只是不能推广到 1M 的 DXL 路径）。

### 7.2 于是多出第四条路（比改 robotd 省事）

`community-kit` 的 `imu_to_dxl`（GD32F303CC + LSM6DSV16X）固件 **D2（按槽）+ D10（按字节数）两套都实现**，
`0x8A` 真机验证 19 项全过，三种位次都测了：第 0 位 / 第 1 位 / 未被点名静默。
→ **它的板能放在任意位次**，不需要改主机排队顺序。板子带现成 Gerber + BOM（CERN-OHL-P）、
固件可 A/B 在线升级。

✅ **2026-11-06 已核实：支持 500k**（一手源码，见 `docs/reference/microduck-未核实项核查报告-2026-11-06.md` §2.2）：
`firmware/v1/src/boot_regs.c:282-288` 的 `dev_fee_baud()` 码表 `{1000000, 500000, 250000, ...}` ⇒ **`fee_baud_code=1` 就是 500k**；`dev.c:76-79` 接受 0..11，写飞特寄存器 **6** 由 `dev.c:313` 自动存入 flash blob（掉电保持）；`docs/flash_layout.md:522` 原文「可临时把总线降到 500 kbps（`dev_dxl_baud()` / `dev_fee_baud()` 都支持）」。
⚠️ **三个前提**：① 默认 `dev_cfg.c:22` = `FEE_BAUD_CODE_1M`，出厂 1M ⇒ 要先用 1M 写 reg6=1 再切 500k，**上电首帧握手顺序只能台架验**（`bus.c:254-257` 说 served baud 跟随主机最后一次的协议）；② DXL 侧码表 `{9600,57600,115200,1M,2M,3M,4M}` **没有 500k**，只有飞特 `0x82` 协议能降（我方正是飞特总线）；③ 15 颗舵机 reg6 要一起改成 0=1M/1=500k 中的 1。
⇒ **第四条路成立**，不再卡在「500k 未核实」。

### 7.3 另外两家新候选（比 666wsp / kissqy 更省改动）

| 候选 | 许可 | 相对本文 §6 建议的差异 |
|---|---|---|
| `jyg9/microduck-community-kit` `imu_to_dxl` | 板 CERN-OHL-P / 软件 Apache-2.0 | 固件两套位次仲裁都做完、真机验证、Gerber+BOM 齐全；**前提是确认 500k** |
| `avanx/microduck_imu_to_ttl` | Apache-2.0（立创 OSHWHub 可直打样） | 第四家 `imu_to_dxl`；给出我们一直缺的**硬件方向控制实现**：`SN74LVC2G241` 半双工收发 + TVS/PTC，HT7533(3V3) + SGM2036-1.8(IMU)，MCU↔LSM6DSV16X 走 SPI+INT；附躯干 IMU 安装朝向推理 |
| `Juxi-Technology/imu-displace-microduck` | Apache-2.0 | **根本不挂总线**：I²C ICM-42670-P → 故障域分开（IMU 挂了不再让整笔 sync_read 作废、15 颗一起丢数据）。⚠️ `robotd` 运行时未接线，目前只是台架验证工具，不能拿来走路 |

### 7.4 一个同源观察（推的，未找到直接引用）

666wsp 的 15 字节布局（byte12=sequence / 13=status / 14=reserved）与 community-kit 的
15 字节「契约块」（byte12=采样计数 / 13=状态位 / 14=0）**结构一致、状态位 bit 定义不同**。
community-kit 的 `bus_timing_borrow_plan.md` 明写外部依据来自 `fanhao375/microduck-replica` 的
`总线协议.md` ⇒ 三方很可能同源于 replica 那条线，不是三份独立设计。

### 7.5 时序坑（与 H6 判据相关）

`community-kit` §7.8 抓到：USART 接收中断里按位实现的 CRC-16 耗时 11–20 µs，超过 1 Mbps 下
一个字节的 10 µs，紧跟的字节被单字节接收寄存器覆盖 → **任何「紧跟指令帧发言」的设备都会被吃掉首字节**。
改 256 项查表后解决。500k 下字节时间翻倍到 20 µs，风险更小，但仍是台架要留意的形状。

**结论修正**：本文 §6 的「最省事 = DuckBuddy 自己的 PDB/IMU 板」**依然成立**（零改动、500k 原生）；
但「666wsp 改动最重 / kissqy 要逐脚核对后重刷」之外，现在多了
「用 community-kit 或 avanx 的板、把位次问题在固件侧解决」这条更干净的路。

