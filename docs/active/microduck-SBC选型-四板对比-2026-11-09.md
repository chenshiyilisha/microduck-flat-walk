# HD-1910 主机 SBC 选型：四板横向对比（Radxa / Orange Pi A733 / 泰山派 / Pi 4B）

_日期：2026-11-09 · 结论速览见 §1 总表。_

_一手来源：各板官方规格/brief；robotd 源码（`configd/src/identity.rs`、`duck-control/src/feetech.rs`、`runtime/duck-control/src/scs.rs`、`runtime/robotd-params/src/lib.rs`、`Cargo.toml`）；部署 toml（`out/robotd_hd1910_mode0.toml`）；社区泰山派移植（`microduck-泰山派HAT研究-2026-11-08.md`）；**立创官方 Microduck 泰山派案例镜像**（`wiki.lckfb.com/zh-hans/tspi-rk3566/project-case/microduck/image.html`）；**EasyDuck 开源整机**（`github.com/jlckfb/easyduck`，`runtime/` 组件逐一对应我们 robotd 栈）。_

---

## 0. 四块板子在项目里的角色

| 板子 | SoC | 在我们项目里的角色 |
|---|---|---|
| **Radxa Zero 3W** | Rockchip RK3566 (4×A55) | **我们 HD-1910 复刻线现状主机**。零改动基准（`feetech_hls`/500k/1-15 体系）。 |
| **Orange Pi A733** | Allwinner A733 (2×A76+6×A55) | **robotd 原厂 DuckBuddy 线（HL-2915 机器人）用的板子**。robotd 已为它写好（`feetech_hls`/500k 默认配置）。是"robotd 跨 SoC 可行"的原厂证据，但属另一条产品线。 |
| **泰山派 RK3566** | Rockchip RK3566 (4×A55) | **有现成开源整机方案（EasyDuck + 立创官方案例镜像）**——同 SoC + 同舵机芯片 + 同 robotd 栈，但舵机协议走 **SCS 标准分支（1MHz + 官方 ID 体系）**，与我们复刻线 `feetech_hls`（500k + 1-15）是**两条不同协议分支**。 |
| **Raspberry Pi 4B** | Broadcom BCM2711 (4×A72) | **候选替代**。不同 SoC；串口必须切 PL011。 |

> 项目现状（见 `MEMORY.md` SBC 选型段）：**此刻最优是"别买板"——台架 PC + URT-2 ¥0 且 50 Hz。**
> 除非要给真机上部署主机且 Radxa 不好买，否则任何板都不是当前刚需。

---

## 1. 四板总对比表（速查）

| 维度 | Radxa Zero 3W（现状） | Orange Pi A733（原厂线） | 泰山派 RK3566（候选，有现成方案） | Pi 4B（候选） |
|---|---|---|---|---|
| **SoC** | RK3566 A55 | A733 A76+A55 | RK3566 A55 | BCM2711 A72 |
| **尺寸 / 重** | 65×30 mm / ~15 g | 50×55 mm / 21 g（Zero 4）<br>或 89×56 mm / 58 g（4 Pro） | 70×45 mm / 98.6 g | 85×56 mm / 75 g |
| **供电** | 5V / 2A USB-C | 5V / 3A USB-C | 5V/3A USB-C 或 5–18V(JST) | 5V / 3A USB-C（**挑电源**） |
| **无线** | **WiFi 6 + BT 5.4** | **WiFi 6 + BT 5.4** | 2.4GHz n（多未标 ax） | WiFi 5 (ac) + BT 5.0 |
| **系统盘** | eMMC + TF | eMMC 模块 + microSD + UFS(可选) | eMMC + TF | microSD（无 eMMC） |
| **伺服总线(舵机)** | `/dev/ttyS2` 已配（`feetech_hls`） | 原厂已配（`feetech_hls`） | **立创镜像/开源整机已配 `ttyS3`**（SCS 1MHz 分支） | 🔴 必改：`dtoverlay=disable-bt` → `ttyAMA0` |
| **robotd 支持度** | 已验证（复刻线） | **原厂支持（最高）** | **已有现成镜像+整机（同栈；但舵机协议分支不同）** | 需移植（跨 SoC） |
| **价格** | ~¥136–165 | Zero 4 ~¥200–400 / 4 Pro ~¥300+ | ~¥138（DDR 涨价至 ~¥580） | ~¥300–400 裸板（套件 ¥1500+） |
| **迁移成本** | 0（现状） | 0（另一条线，非复刻线迁移） | **低**（镜像/总线/标定现成；注意协议分支选择 + 机构） | 高（串口 + 机构 + 贵） |

---

## 2. 为什么软件层都不钉死（跨 SoC 可行）

- **robotd 不钉板子厂商**：身份识别只从通用的 `/proc/device-tree/serial-number` 读 SoC 序列号
  （`configd/src/identity.rs:35` `const SERIAL_PATH = "/proc/device-tree/serial-number"`）；
  `radxa-zero3` 仅为 configd 连不上时的命名回退，无 Orange Pi / Radxa / Broadcom 专属 SoC 分支。
- **编译目标通用**：`.cargo/config.toml:3` 写的是 `aarch64-unknown-linux-gnu`——RK3566 / A733 / BCM2711 都是 aarch64，二进制无需为架构重编（仅 glibc/链接器需匹配）。
- **控制栈不用 Rockchip 专属硬件**：`duck-control/src/feetech.rs:301` 只用标准 `serialport` 库 + POSIX serial（跨平台）；ONNX 策略推理走 **CPU**。`Cargo.toml:34/45` 提到的 **RKNN NPU / MPP H.264** 是给 `duck-detect`（视觉检测）和 WebRTC 视频编码的——且这两条在另两块板上都有等价能力：
  - Pi 4B 自带 **H.264 硬件编码**（文档明写 1080p60 encode），不依赖 Rockchip MPP；
  - Orange Pi A733 自带 **H.264/H.265 4K@30fps 硬件编码**（Allwinner VPU），也不依赖 MPP。
- **关键佐证（两条独立证据）**：
  1. Orange Pi A733（**Allwinner，非 RK3566**）就是 robotd 原厂 DuckBuddy 线用的 SoC → 证明 robotd 已经跨 SoC 原厂验证过（见 §3.2）。
  2. **泰山派（RK3566）上已有现成开源整机 EasyDuck（`jlckfb/easyduck`）+ 立创官方案例镜像**——把 robotd 同栈 + HD-1910 舵机 + 泰山派做成完整方案（`runtime/` 里 `robotd/duck-control/duck-ipc-proto/kinematics/robotd-params/robotctl/padd/sounds` 与我们工作区逐一对应）。**这比"社区零散移植"强得多**，是"泰山派上能跑我们这套栈"的权威现成证据。
- **重要洞察：robotd 生态存在「舵机协议两条分支」**：同一颗飞特 1910 舵机（寄存器布局 40/42/50/56–70 完全一致），不同产品线选了不同协议实现——
  - **HLS 半双工分支**（`feetech.rs` / `feetech_hls`，**500k** 硬编码）：我们复刻线 + Orange Pi 原厂线采用；
  - **SCS 标准分支**（`scs.rs`，**1MHz**）：EasyDuck（泰山派线）采用（`scs.rs:BAUD = 1_000_000`）。
  两条分支都驱动同一颗舵机芯片，但**协议帧/波特率/关节 ID 体系不同，驱动代码不能互相替换**（见 §3.3 + §7）。

---

## 3. 各板细节与风险

### 3.1 Radxa Zero 3W（现状零改动）
- 复刻线主机：`out/robotd_hd1910_mode0.toml:60` `port = "/dev/ttyS2"`，`feetech.rs:301` 直接开，`BAUD_RATE = 500_000` 硬编码（toml 注释引 `feetech.rs:35`）。
- **HLS 半双工分支**：`feetech_hls` servo 类型 + 关节 ID 体系 1-15（左腿优先）。
- 风险项：无（现状基准）。唯一注意：toml 注释写"A733's UART7"（Orange Pi 线），**换板前先确认 Radxa 上 `ttyS2` 到底对应哪路 UART/引脚**——连现状都可能接错，别先假设配置是对的。

### 3.2 Orange Pi A733（原厂 DuckBuddy 线 HL-2915）
- SoC：Allwinner A733，2×Cortex-A76 @2.0GHz + 6×Cortex-A55 @1.8GHz，12nm，3TOPS NPU。
- 形态：Orange Pi **Zero 4**（50×55mm / 21g，小，接近 Radxa 尺寸）或 **4 Pro**（89×56mm / 58g，信用卡尺寸）。
- 优势：**robotd 原厂就为它写好了**（`feetech_hls`/500k 默认配置就是这条线的，reg6/reg33 开机硬校验属于它），无线 WiFi 6+BT5.4 与 Radxa 同级，价格亲民（Zero 4 起 $26.5 / 4GB $52）。
- 对我们复刻线的定位：**它是"robotd 跨 SoC 可行"的原厂证据，不是"直接可用的替代"**。它属于另一条独立产品线（DuckBuddy 官方 HL-2915 机器人，物理机壳/舵机布线与我们 HD-1910 复刻线不同）。若把我们的复刻线迁到 Orange Pi A733，机构/布线/设备树一样要重做——除非直接采用 DuckBuddy 官方线整套方案（那是另一条路线，不在本选型范围）。

### 3.3 泰山派 RK3566（候选替代，**已有现成开源整机方案**）
- **现成方案（已核实真实性）**：
  - **立创官方 Microduck 泰山派案例镜像**（`wiki.lckfb.com/.../project-case/microduck/image.html`）：定制 Debian 12，内核 6.1.141 **"包含 UART3 半双工控制支持"**，预装 ONNX Runtime 1.28、整套 robotd；舵机 `/dev/ttyS3`，IMU `/dev/i2c-2` @0x6B。
  - **EasyDuck 开源整机**（`github.com/jlckfb/easyduck`，立创官方组织 `jlckfb`，`fork:false` 原创）：控制核心泰山派 1M；舵机 15× HD-1910-C001（飞特 1910 系列）；IMU BNO085 / LSM6DSV16X；`runtime/` 组件（`robotd/duck-control/duck-ipc-proto/kinematics/robotd-params/robotctl/padd/sounds`）与我们工作区逐一对应。**是和我们同一条 robotd 栈的现成整机**。
- **功能层面**：同 SoC 同外设类别（RK3566），机器人需要的接口零功能缺口。
- **🔴 关键核对结论（2026-11-09 拉源码核实）—— EasyDuck 与我们复刻线是「两条舵机协议分支」**：

  | 维度 | 我们 HD-1910 复刻线 | EasyDuck（泰山派现成方案） | 是否一致 |
  |---|---|---|---|
  | SoC | RK3566（Radxa Z3W） | RK3566（泰山派 1M） | ✅ 同 |
  | 舵机芯片 | 飞特 1910 系列 | 飞特 1910 系列（HD-1910-C001） | ✅ 同颗 |
  | 协议实现 | `feetech.rs` / **`feetech_hls`** | `scs.rs` / **标准 SCS**（`lib.rs` 仅 `pub mod scs;`，无 `feetech`） | ❌ 不同分支 |
  | 波特率 | **500_000**（`feetech.rs:301` 硬编码） | **1_000_000**（`scs.rs:BAUD`） | ❌ 不同 |
  | 关节 ID 体系 | **1–15**（左腿优先） | **20–24 / 30–34 / 10–14**（官方）（`scs.rs:CAL_ZERO` 注释） | ❌ 不同 |
  | 寄存器布局 | 40/42/50/56–70 | 40/42/50/56–70（`scs.rs` 同地址） | ✅ 一致（同颗芯片） |
  | 默认串口 | `/dev/ttyS2`（上游默认） | 默认 `/dev/ttyS2` → 部署覆盖 **`/dev/ttyS3`**（`robotd-params Bus.port` 默认 ttyS2，镜像部署层改） | ⚠️ 部署层不同 |
  | IMU | BNO08x（I2C，0x4A/4B） | BNO085（0x4A/4B）+ LSM6DSV16X（0x6A/6B），**自动识别**（`robotd-params` validate） | ✅ 同系列，自动识别 |
  | 控制栈 | robotd 50Hz | robotd 50Hz（同 workspace） | ✅ 同栈 |

- **"能否直接复用"判定**：
  - **若采用 EasyDuck 整套（scs + 1MHz + 官方 ID 体系）**：与我们现有的 `feetech_hls` 训练 / EEPROM 工具链（`hls_probe`、`hardware_endtoend_check`、`pre_deploy_check`、标定文件 `zero_pos`/ID 1-15）**不兼容**——这些工具是按 HLS + 500k + 1-15 写的。等于换了一条全新的舵机协议线。
  - **若把我们的复刻线 robotd（`feetech_hls`/500k/1-15）烤到泰山派**：可复用 EasyDuck/立创镜像的**设备树（UART3 半双工）、系统镜像、部署/标定工具链、IMU 驱动（BNO08x 同系列）**，只需把 `port` 指到 `ttyS3`、对齐 `imu_mount_quat` 安装朝向——**软件迁移本质是"换板不换协议"**，比从零移植省事得多。
  - 两种路线下，**机构重做仍可能必要**：泰山派 70×45mm / 98.6g 比 Radxa 大重 ~80g；若直接采用 EasyDuck 整机（板+机壳+舵机+IMU+镜像），立创已解决机构；若只把泰山派塞进我们现有 Radxa 机壳，机构仍要重做。
- 半双工方向：✅ **已查源码闭环（2026-11-09）**。对两条 robotd 线都拉源码核实：① 我们 `feetech_hls`：`FeetechIo::open`(`feetech.rs:301`)只 `serialport::new(...).open()`，整个 `DuckBuddy-main` 仓 + `rustypot` 1.6.0 **零 RTS/RS485/方向代码**；② `jlckfb/easyduck` 的 `ScsIo::open`(`runtime/duck-control/src/scs.rs:199`)同样只 `serialport::new(...).open()`，整个 easyduck runtime **零 TIOCSRS485/TIOCMSET/set_rts/rs485/de_gpio/half-duplex**（`scs.rs:477-486` 的 "direction" 是电机旋转符号位解码，非总线方向）。**两条线用户态都不翻方向脚，半双工方向 100% 在 kernel/硬件层**——也就是 vendored 的泰山派 `485_ctrl_gpio` DE 补丁（A1）提供的正是两者都依赖、却都没自己实现的方向控制，故两条线在同一块板上**不冲突**。无论哪条线，换板都必须保证新板 kernel/硬件层把方向做对（泰山派 = 立创镜像内核 DE gpio 补丁 + 载板 DE 接线）。

### 3.4 Pi 4B（候选替代）
- SoC：Broadcom BCM2711，4×Cortex-A72 @1.5–1.8GHz（**单核比 A55 高两代，算力最强**）。
- 🔴 **串口是死穴**：默认 GPIO14/15 是 **mini UART (`ttyS0`)**——波特率随 GPU 时钟浮动（实测偏差 3.2% 超 RS232 容限）、**无硬件 RTS**，500k/1MHz 半双工舵机总线绝不能用。必须用 **PL011 (`ttyAMA0`)**：改 `config.txt` `dtoverlay=disable-bt` 把 PL011 从蓝牙让给 GPIO（独立 180MHz 时钟、500k 精准、完整 RTS/CTS）。且 toml `port="/dev/ttyS2"` 在 Pi 上**不存在**，要改成 `ttyAMA0`。
- 机构最大最重（85×56mm / 75g），机壳几乎完全重做，重心问题最严重；价格明显贵（裸板 ~¥300–400，套件 ¥1500+）；供电挑电源。
- 优势：无线 WiFi 5 双频 + BT 5.0（比泰山派强）、H.264 硬件编码（替代 MPP）、USB3.0×2。

---

## 4. 功能需求 ↔ 四板覆盖（逐项核对）

| 机器人需要的功能 | Radxa | Orange Pi A733 | 泰山派 | Pi 4B |
|---|---|---|---|---|
| CPU 算力（50Hz 环 + ONNX） | ✅ A55 | ✅ A76+A55（最强档） | ✅ A55 | ✅ A72（单核强） |
| 伺服总线 UART 半双工 | ✅ ttyS2（HLS 500k） | ✅ 原厂（HLS 500k） | ✅ ttyS3 **现成**（但 SCS 1MHz 分支，非 HLS 500k） | 🔴 必切 ttyAMA0 |
| IMU I2C（BNO08x 系列） | ✅ | ✅ | ✅ i2c-2 **现成**（BNO085/LSM6DSV16X 自动识别） | ✅ i2c-1 需开 |
| 同时占 UART + I2C | ✅ | ✅ | ✅ | ✅ |
| GPIO / 方向 / 使能 | ✅ | ✅ | ✅ | ✅ |
| USB（URT-2/调试） | ✅ | ✅ | ✅ | ✅ 2×USB3+2×USB2 |
| 无线控制（robotctl+relay） | ✅ WiFi6 | ✅ WiFi6 | ⚠️ 2.4G n | ✅ WiFi5 |
| 视频流编码（若推流） | ✅ | ✅ H264/265 硬件 | ✅（无 MPP，用软/其他） | ✅ H264 硬件 |
| 系统盘 | ✅ eMMC | ✅ eMMC+SD | ✅ eMMC+SD | ⚠️ microSD（无 eMMC） |

---

## 5. 通用迁移清单（换非现状板必做，按风险排序）

1. **选协议分支**：先决定沿用我们 `feetech_hls`（500k + 1-15）还是切 EasyDuck 的 `scs`（1MHz + 官方 ID 体系）——两条驱动代码不互换，且影响现有所有 HLS 工具链（`hls_probe`/EEPROM 校验/标定）。**泰山派的现成镜像/整机走 SCS 分支；若要保持我们复刻线工具链，须把 `feetech_hls` robotd 烤到泰山派镜像上**（设备树已含 UART3 半双工，只需改 `port` 到 `ttyS3`）。
2. **总线 UART 重映射**：启用一路 UART（设备树 overlay），确认 TX/RX/**RTS** 引脚；把 toml `port` 改成对应设备（泰山派 `ttyS3`、Pi 必 `ttyAMA0`）；用 `servo_probe` 在板上实测半双工稳定通。
3. **IMU I2C 重映射**：BNO08x 重接/配 I2C 总线号（泰山派 `i2c-2`、Pi `i2c-1`），确认 `imu_mount_quat` 安装朝向自检通过（`live_viewer` 的 `imu_mount_sanity` 自检）。
4. **机械重设计**：按新板尺寸/重量重做机壳支架（若不用 EasyDuck 整机机壳），重评行走重心（可能需重新训练）。
5. **供电评估**：确认 5V/3A（或宽输入）与机器人电源树余量；Pi 尤忌劣质电源掉压。
6. **无线实测**：robotctl 无线 + `live_viewer --source robotctl` 的 WebRTC relay 在对应 WiFi 档次下的延迟/丢包。
7. **上板自检**：绝不在台架 PC 上断言。把 toml 烤到目标板，跑 robotd 开机校验（reg6/reg33 硬校验）+ `pre_deploy_check.py --selftest`，确认总线打开、IMU 读到、EEPROM 四项通过。

---

## 6. 文档关系与现状结论

- `microduck-泰山派HAT研究-2026-11-08.md`：社区给泰山派做的 BMI088 扩展板 + MicroDuck 移植（独立 robotd 客户端）。早期"泰山派能跑 MicroDuck"的社区证据。
- **`github.com/jlckfb/easyduck`（立创官方 `jlckfb` 组织）+ 立创官方案例镜像**：**现成开源整机 / 官方镜像**，`runtime/` 组件逐一对应我们 robotd 栈，是"泰山派上能跑我们这套栈"的**权威现成方案**（但舵机协议走 SCS 1MHz 分支，见 §3.3 + §7）。
- 本文件：四板横向选型判断（功能覆盖 + 集成风险 + 迁移成本 + 现成方案），角度互补。
- `MEMORY.md` SBC 选型段：保持"别买板"现状结论；本文件补充"若要买——Orange Pi A733 是原厂已验证基准（但属另一条线），泰山派有现成 EasyDuck 整机/镜像但舵机协议是 SCS 分支（非我们 HLS），Pi 4B 功能够但机构/价格最差；§5 七步不可省（含协议分支选择）"。

---

## 7. 舵机协议两条分支（SCS vs HLS）—— 本次核对核心结论

_（2026-11-09 拉取 `jlckfb/easyduck` 源码核实，推翻此前"泰山派需从零移植 6 步"的偏保守判断。）_

- **同一颗舵机芯片（飞特 1910 系列），同一套寄存器布局（40 扭矩 / 42 目标 / 50 增益 / 56–70 位置电流）**——`scs.rs` 与我们的 `feetech.rs` 寄存器地址逐一相同，证明是同一硬件。
- **但协议实现分两叉**：
  - **HLS 半双工分支**：`feetech.rs` / `feetech_hls`，**500k** 硬编码，关节 ID **1–15**（我们复刻线 + Orange Pi 原厂线）。
  - **SCS 标准分支**：`scs.rs`（注释 `// SCS/Feetech backend for the HD1910 servos`），**1MHz**，关节 ID **20–24/30–34/10–14**（官方体系，EasyDuck / 泰山派线）。
- **含义**：
  - 不能直接拿 `scs.rs` 替换我们的 `feetech.rs`（波特率、ID 体系、协议帧不同），但可以借鉴其寄存器操作与标定逻辑。
  - 泰山派迁移的"软件难度"被现成镜像/整机大幅拉低——真正的决策变量是**"换不换协议分支"**，而非"能不能跑起来"。
  - 若保持我们 HLS 工具链（推荐，因现有训练/EEPROM/标定全在这条线），只需把 `feetech_hls` robotd 烤到泰山派立创镜像上，改 `port=ttyS3` + 对齐 IMU 朝向即可。

---

## 8. 泰山派 / EasyDuck 项目「可借鉴清单」（2026-11-09 拉源码核实）

_一手来源：`github.com/jlckfb/easyduck`（`runtime/duck-control/src/scs.rs`、`calibration/`、`config/board/robotd.toml`、`deploy/kernel/uart3-halfduplex-20261021.patch`、`models/`）。下列按「能借 / 借不了」分类；证据均为源码/文件级。_

### 8.1 直接可借鉴（与舵机协议分支无关）

**🔴 A1. 半双工 UART 内核补丁 —— 最值钱，可直接拿来用（已 vendored）**
- 文件：`docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch`（源自 `jlckfb/easyduck`，仅作参考留存，未改内容）。
- 改 `8250_dw.c` + `8250_port.c`，给 RK3566 DesignWare UART 加 **DE/RE 方向 GPIO**（设备树属性 `485_ctrl_gpio`，极性取自 GPIO flags cell），由内核在 TX 时自动翻转收发器方向。
- **为何必须绕开标准 `em485`（TIOCSRS485）**：在这颗 SoC 上开 em485 会在**第一帧之后卡死 TX**——`__stop_tx()` 在 `!THRE` 检查处提前返回，stop_tx hrtimer 永不触发，THRI 一直置位，下一帧 `__start_tx()` 看到 THRI 已置就什么都不做（实测 ttyS0/3/4/5 都如此）。
- 另外两件对高速半双工关键：**带 DE 引脚的口禁用 TX DMA**（`if (p->fifosize && up->de_gpio < 0)`——TX DMA 绕过 `serial8250_tx_chars()`，会让 ≥MAX_TX_BYTES 的帧在收发器仍处接收态时发出）；**DE 上电为接收态**（`GPIOF_OUT_INIT_HIGH/LOW` 视极性），符合半双工总线空闲约定。
- **对我们 HLS 线的意义**：我们 `feetech_hls` @500k 在泰山派上要的正是这套"内核级 DE 翻转"。补丁本身与波特率无关（波特率只是 termios `B500000`/`B1000000`），**可直接复用**，省掉自踩 em485 卡死 + DMA 串扰的坑。代价：基于内核 6.1.141 **需重编译内核**（不是 dt-overlay 即插即用），但比从零写方向控制省一个数量级。

**🟢 A2. 标定套件 —— 协议无关逻辑可借鉴架构（`calibration/`）**
- 整套标定工具都操作一个 **`Bus` 抽象**（`calibration/hardware.py`：`read_raw`/`write_raw` + `fcntl.flock` 独占锁 + `B1000000` termios），**标定逻辑本身不依赖 SCS**——只要给个 `feetech_hls` 兼容的 `Bus` shim 就能跑我们的舵机。
- `servo_setup.py`：舵机 ID 扫描（0–253）+ 选中 + 读反馈，**总线锁串行化**（`caller serializes every operation with the bus lock`）——正是我们 provisioning 要的范式。
- `imu_settings.py`：IMU 自动探测（`probe_lsm` 查 0x0f==0x70、`probe_bno` 查 SHTP 身份包）+ **TOML 原子写**（备份 → `fsync` → `os.replace`）。`KEYS=('source','model','i2c_dev','i2c_addr','fusion')` 是 IMU 配置 schema。
- 我们已有 build-tutorial 的 `bno08x_calibrate_ui.py`/`imu_orientation_check.py`，但 EasyDuck 这套"扫描 + 自动探测 + 原子写配置"的工程化更完整，**逻辑层可直接借鉴**。

**🟢 A3. 多策略模型 / 行为范式（`models/`）**
- 5 个 ONNX：`walk` / `getup` / `pick` / `posture` / `roulade`（外加 kick）。我们复刻线目前只有 walk + getup。**pick / posture / roulade 是现成的行为参考**，可借鉴其训练范式或策略组织（`robotd.toml` 里 `[policy]` 用 `mode=` 切换，每个行为一个 onnx）。

**🟢 A4. `config/board/robotd.toml` 接线范式 + 调参数据（对照参考）**
- 实际泰山派接线：`port="/dev/ttyS3"`；`[imu] model="lsm6dsv16x" i2c_dev="/dev/i2c-2" i2c_addr=107 fusion="sflp"`。
- 可对照的调参数据：`policy.gain=6, gain_d=20`（策略级 PD，非舵机级）；`safety.fall_gravity_z=-0.819152`（≈35° 倾覆阈值，比我们 `-0.5`≈60° 更紧）；`low_battery_voltage=6.2`（2S 电池，与我们的 `[2]+8.4` 一致）。
- `[imu]` **同时支持 LSM6DSV16X 与 BNO085 并自动探测**——与我们工作记忆里"BNO08x(HD-1910) vs LSM6DSV16X(ft1910 总线 IMU)"的 IMU 架构区分正好呼应，他们用一套代码两种都吃。

### 8.2 借不了的（舵机协议分支，§3.3 / §7 已详述）
- `duck-control/src/scs.rs` + 标准 SCS 协议 + **`BAUD=1_000_000`** + **官方关节 ID（20-24/30-34/10-14）**，`lib.rs` 仅 `pub mod scs;`（无 `feetech`）。与我们 `feetech_hls` + 500k + **ID 1-15** 两条分支不互通。**他们的 robotd 舵机驱动不能直接用**，只能借鉴 A 类（内核 / 标定 / 配置 / 模型），不能抄 servo 通信层。

### 8.3 借鉴时的注意点
- 半双工补丁要**重编译内核**（基于 6.1.141），不是 overlay 即插即用——但比从零写方向控制省一个数量级。
- 标定套件要写 **HLS 版 `Bus` shim** 才能跑我们的舵机。
- 机构（70×45 / 98.6 g）只有"直接采用 EasyDuck 整机"时才不用管；塞我们自己 Radxa 机壳仍要重做（见 §3.3 / §5.4）。
- **决策变量**：要不要保持我们 HLS 工具链（推荐）vs 切 SCS 分支。保持 HLS 时，§8.1 A1 补丁 + A4 配置 + A2 标定逻辑 是三条最实在的借鉴；切 SCS 则等于换一条全新舵机线（与现有 `hls_probe`/EEPROM 校验/标定全不兼容）。
