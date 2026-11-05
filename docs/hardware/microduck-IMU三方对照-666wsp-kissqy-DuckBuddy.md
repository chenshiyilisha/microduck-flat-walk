# IMU 三方对照：666wsp · kissqy · DuckBuddy

_2026-11-05。三方定位：**666wsp** = 通用 IMU 板厂商（IMU_TO_DXL）；**kissqy** = HD1910 复刻社区作者（自制 HAT+IMU，淘宝卖套件）；**DuckBuddy** = 上游软件（robotd/duck-control）+ 参考硬件（PDB/IMU R2f）。目的：判断买的 IMU 板能不能接上自己跑的 DuckBuddy robotd。_

**一句话结论：IMU 板固件决定了同步读里 IMU 的排队位置，而 666wsp 与 kissqy 的固件都要求「IMU 排第一位」，DuckBuddy 的 robotd（HD1910/feetech 后端）却硬编码「IMU 排最后」且总线跑 500k。两者不能直接对接——要么改 robotd 的排队顺序，要么用 DuckBuddy 自己的 IMU 固件/板。原生匹配只有 DuckBuddy 的 PDB/IMU 板。**

## 0. 先澄清一个常见误判：A733 的 UART7 上不了真 1 Mbps ≠ 性能不如 Radxa

DuckBuddy INTERFACE-CN.md 注明「A733 的 UART7 设 1 Mbps 实际只有约 750 kbps，所以统一用 500k」。这**不是 A733 的劣势**：

- **总线根本不需要 1 Mbps**。每 tick（50 Hz）一次同步读 16 设备 ≈ 295 字节，500 kbps 下占线 ~4.7 ms / 20 ms = **~24%**，余量 4 倍。DuckBuddy 整套（含自己的 IMU 固件 imu-feetech）就是跑 500k。
- **Radxa 上也是跑 500k**，不是 1M。1M 在两家平台上都没被用上，A733 少一个用不到的 capability 不构成劣势。
- **1 Mbps 只是第三方 IMU 固件的出厂默认**：666wsp 板可用 FD.exe 改；kissqy FT6 锁 1M；DuckBuddy 自己的 IMU 固件就是 500k。
- 且 A733 在 CPU（2×A76+6×A55@2.0GHz 八核 vs 4×A55@1.8GHz）、NPU（3 TOPS vs 0.8）、内存（LPDDR5 vs LPDDR4）上全面更强；DuckBuddy upstream 主控就是香橙派 Zero 3W（已验证整机运行）。

**唯一 relevant 的情形**：硬要用锁 1M 的第三方 IMU 固件时，A733 喂不饱 → 把板降到 500k 或换 DuckBuddy IMU 固件，三条路都通。

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

- **kissqy IMU 板引脚 vs DuckBuddy imu-feetech 固件**：两者都是 STM32G031+LSM6DSV16X，但板设计不同（kissqy RevA 22.7×25.6mm 两层 vs DuckBuddy PDB/IMU R2f）。要把 kissqy 板刷成 DuckBuddy 固件，需逐脚核对：SWD、USART TX/RX、DE 方向控制、LED、传感器 SPI/I2C、供电。**不能假设引脚兼容。**
- **DuckBuddy imu-feetech 固件源码位置**：`.upstream/DuckBuddy-main/firmware/imu-feetech`（本地已有），可作为重刷参考。
- **666wsp 板 BAT+ 电压范围**：手册标注「待确认」（imu_dev_guide.md:158）。

## 6. 给你的选择建议

你的软件栈是 **DuckBuddy robotd**（本项目一直在审它的 TOML）。因此：

- **最省事**：用 **DuckBuddy 自己的 PDB/IMU 板 + imu-feetech 固件**（500k，IMU 后），原生匹配，零改动。
- **想用 kissqy 淘宝套件（¥150，到手即用）**：IMU 板是 STM32G031，理论上能刷 DuckBuddy 固件，但**必须先核对引脚**（§5）。核对通过则重刷成 DuckBuddy IMU，变成原生匹配。核对不通，就得改 robotd（IMU 前 + 1Mbps），工作量大。
- **不建议买 666wsp 板接 DuckBuddy**：CH32V203 刷不了 DuckBuddy 固件，又强制 IMU 前，改动最重。除非你就是要做 666wsp 固件 + 自改 robotd 的路线。

> ⚠️ 注意：kissqy 的 HAT+IMU 套件是配 **kissqy 自己的 control.43 / R17 中控**（1Mbps，IMU 前）用的，不是配 DuckBuddy robotd。买它的前提是接受 kissqy 那一整套软件栈，或愿意重刷 IMU 固件+核对引脚。
