# HD-1910 主机 SBC 选型：四板横向对比（Radxa / Orange Pi A733 / 泰山派 / Pi 4B）

_日期：2026-11-09 · 结论速览见 §1 总表。_

_一手来源：各板官方规格/brief；robotd 源码（`configd/src/identity.rs`、`duck-control/src/feetech.rs`、`Cargo.toml`）；部署 toml（`out/robotd_hd1910_mode0.toml`）；社区泰山派移植（`microduck-泰山派HAT研究-2026-11-08.md`）。_

---

## 0. 四块板子在项目里的角色

| 板子 | SoC | 在我们项目里的角色 |
|---|---|---|
| **Radxa Zero 3W** | Rockchip RK3566 (4×A55) | **我们 HD-1910 复刻线现状主机**。零改动基准。 |
| **Orange Pi A733** | Allwinner A733 (2×A76+6×A55) | **robotd 原厂 DuckBuddy 线（HL-2915 机器人）用的板子**。robotd 已为它写好（reg6/reg33 开机硬校验、`feetech_hls`/500k 默认配置）。是"robotd 跨 SoC 可行"的原厂证据，但属另一条产品线。 |
| **泰山派 RK3566** | Rockchip RK3566 (4×A55) | **候选替代**。与 Radxa 同 SoC，但设备树不同（`ttyS3`/`i2c-2`）。 |
| **Raspberry Pi 4B** | Broadcom BCM2711 (4×A72) | **候选替代**。不同 SoC；串口必须切 PL011。 |

> 项目现状（见 `MEMORY.md` SBC 选型段）：**此刻最优是"别买板"——台架 PC + URT-2 ¥0 且 50 Hz。**
> 除非要给真机上部署主机且 Radxa 不好买，否则任何板都不是当前刚需。

---

## 1. 四板总对比表（速查）

| 维度 | Radxa Zero 3W（现状） | Orange Pi A733（原厂线） | 泰山派 RK3566（候选） | Pi 4B（候选） |
|---|---|---|---|---|
| **SoC** | RK3566 A55 | A733 A76+A55 | RK3566 A55 | BCM2711 A72 |
| **尺寸 / 重** | 65×30 mm / ~15 g | 50×55 mm / 21 g（Zero 4）<br>或 89×56 mm / 58 g（4 Pro） | 70×45 mm / 98.6 g | 85×56 mm / 75 g |
| **供电** | 5V / 2A USB-C | 5V / 3A USB-C | 5V/3A USB-C 或 5–18V(JST) | 5V / 3A USB-C（**挑电源**） |
| **无线** | **WiFi 6 + BT 5.4** | **WiFi 6 + BT 5.4** | 2.4GHz n（多未标 ax） | WiFi 5 (ac) + BT 5.0 |
| **系统盘** | eMMC + TF | eMMC 模块 + microSD + UFS(可选) | eMMC + TF | microSD（无 eMMC） |
| **伺服总线(舵机)** | `/dev/ttyS2` 已配 | 原厂已配（`ttySx`，属另一条线） | 设备树通常 `ttyS3`（社区印证） | 🔴 必改：`dtoverlay=disable-bt` → `ttyAMA0` |
| **robotd 支持度** | 已验证（复刻线） | **原厂支持（最高）** | 需移植（同 SoC 易） | 需移植（跨 SoC） |
| **价格** | ~¥136–165 | Zero 4 ~¥200–400 / 4 Pro ~¥300+ | ~¥138（DDR 涨价至 ~¥580） | ~¥300–400 裸板（套件 ¥1500+） |
| **迁移成本** | 0（现状） | 0（另一条线，非复刻线迁移） | 中（设备树 + 机构） | 高（串口 + 机构 + 贵） |

---

## 2. 为什么软件层都不钉死（跨 SoC 可行）

- **robotd 不钉板子厂商**：身份识别只从通用的 `/proc/device-tree/serial-number` 读 SoC 序列号
  （`configd/src/identity.rs:35` `const SERIAL_PATH = "/proc/device-tree/serial-number"`）；
  `radxa-zero3` 仅为 configd 连不上时的命名回退，无 Orange Pi / Radxa / Broadcom 专属 SoC 分支。
- **编译目标通用**：`.cargo/config.toml:3` 写的是 `aarch64-unknown-linux-gnu`——RK3566 / A733 / BCM2711 都是 aarch64，二进制无需为架构重编（仅 glibc/链接器需匹配）。
- **控制栈不用 Rockchip 专属硬件**：`feetech.rs:301` 只用标准 `serialport` 库 + POSIX serial（跨平台）；ONNX 策略推理走 **CPU**。`Cargo.toml:34/45` 提到的 **RKNN NPU / MPP H.264** 是给 `duck-detect`（视觉检测）和 WebRTC 视频编码的——且这两条在另两块板上都有等价能力：
  - Pi 4B 自带 **H.264 硬件编码**（文档明写 1080p60 encode），不依赖 Rockchip MPP；
  - Orange Pi A733 自带 **H.264/H.265 4K@30fps 硬件编码**（Allwinner VPU），也不依赖 MPP。
- **关键佐证**：Orange Pi A733（**Allwinner，非 RK3566**）就是 robotd 原厂 DuckBuddy 线用的 SoC → 证明 robotd 已经跨 SoC 原厂验证过。跨 SoC 移植本身不是死路，但**物理迁移（机构/布线/设备树）仍免不掉**。

---

## 3. 各板细节与风险

### 3.1 Radxa Zero 3W（现状零改动）
- 复刻线主机：`out/robotd_hd1910_mode0.toml:60` `port = "/dev/ttyS2"`，`feetech.rs:301` 直接开，`BAUD_RATE = 500_000` 硬编码（toml 注释引 `feetech.rs:35`）。
- 风险项：无（现状基准）。唯一注意：toml 注释写"A733's UART7"（Orange Pi 线），**换板前先确认 Radxa 上 `ttyS2` 到底对应哪路 UART/引脚**——连现状都可能接错，别先假设配置是对的。

### 3.2 Orange Pi A733（原厂 DuckBuddy 线 HL-2915）
- SoC：Allwinner A733，2×Cortex-A76 @2.0GHz + 6×Cortex-A55 @1.8GHz，12nm，3TOPS NPU。
- 形态：Orange Pi **Zero 4**（50×55mm / 21g，小，接近 Radxa 尺寸）或 **4 Pro**（89×56mm / 58g，信用卡尺寸）。
- 优势：**robotd 原厂就为它写好了**（reg6/reg33 开机硬校验、`feetech_hls`/500k 默认配置就是这条线的），无线 WiFi 6+BT5.4 与 Radxa 同级，价格亲民（Zero 4 起 $26.5 / 4GB $52）。
- 对我们复刻线的定位：**它是"robotd 跨 SoC 可行"的原厂证据，不是"直接可用的替代"**。它属于另一条独立产品线（DuckBuddy 官方 HL-2915 机器人，物理机壳/舵机布线与我们 HD-1910 复刻线不同）。若把我们的复刻线迁到 Orange Pi A733，机构/布线/设备树一样要重做——除非直接采用 DuckBuddy 官方线整套方案（那是另一条路线，不在本选型范围）。

### 3.3 泰山派 RK3566（候选替代）
- 同 SoC 同外设类别（RK3566），机器人需要的接口零功能缺口。
- 风险：设备树通常暴露为 **`ttyS3`**（非 `ttyS2`）+ IMU **`i2c-2`**（社区移植印证 `microduck-泰山派HAT研究-2026-11-08.md` §3.6/§4）→ 换板后 toml `port` 与 I2C 总线号都要改；机构 70×45mm / 98.6g 比 Radxa 大重 ~80g，装机身抬高重心；无线降级为 2.4GHz n。
- 半双工方向走串口 RTS（`Sts3215Controller` 内），物理 RTS 引脚随设备树变；板子无关，但需配 pinmux。

### 3.4 Pi 4B（候选替代）
- SoC：Broadcom BCM2711，4×Cortex-A72 @1.5–1.8GHz（**单核比 A55 高两代，算力最强**）。
- 🔴 **串口是死穴**：默认 GPIO14/15 是 **mini UART (`ttyS0`)**——波特率随 GPU 时钟浮动（实测偏差 3.2% 超 RS232 容限）、**无硬件 RTS**，500k 半双工舵机总线绝不能用。必须用 **PL011 (`ttyAMA0`)**：改 `config.txt` `dtoverlay=disable-bt` 把 PL011 从蓝牙让给 GPIO（独立 180MHz 时钟、500k 精准、完整 RTS/CTS）。且 toml `port="/dev/ttyS2"` 在 Pi 上**不存在**，要改成 `ttyAMA0`。
- 机构最大最重（85×56mm / 75g），机壳几乎完全重做，重心问题最严重；价格明显贵（裸板 ~¥300–400，套件 ¥1500+）；供电挑电源。
- 优势：无线 WiFi 5 双频 + BT 5.0（比泰山派强）、H.264 硬件编码（替代 MPP）、USB3.0×2。

---

## 4. 功能需求 ↔ 四板覆盖（逐项核对）

| 机器人需要的功能 | Radxa | Orange Pi A733 | 泰山派 | Pi 4B |
|---|---|---|---|---|
| CPU 算力（50Hz 环 + ONNX） | ✅ A55 | ✅ A76+A55（最强档） | ✅ A55 | ✅ A72（单核强） |
| 伺服总线 UART @500k 半双工 | ✅ ttyS2 已配 | ✅ 原厂已配 | ✅ ttyS3 需配 | 🔴 必切 ttyAMA0 |
| IMU BNO08x I2C | ✅ | ✅ | ✅ i2c-2 需配 | ✅ i2c-1 需开 |
| 同时占 UART + I2C | ✅ | ✅ | ✅ | ✅ |
| GPIO / 方向 / 使能 | ✅ | ✅ | ✅ | ✅ |
| USB（URT-2/调试） | ✅ | ✅ | ✅ | ✅ 2×USB3+2×USB2 |
| 无线控制（robotctl+relay） | ✅ WiFi6 | ✅ WiFi6 | ⚠️ 2.4G n | ✅ WiFi5 |
| 视频流编码（若推流） | ✅ | ✅ H264/265 硬件 | ✅（无 MPP，用软/其他） | ✅ H264 硬件 |
| 系统盘 | ✅ eMMC | ✅ eMMC+SD | ✅ eMMC+SD | ⚠️ microSD（无 eMMC） |

---

## 5. 通用迁移清单（换非现状板必做，按风险排序）

1. **总线 UART 重映射**：启用一路 UART（设备树 overlay），确认 TX/RX/**RTS** 引脚；把 toml `port` 改成对应设备（泰山派多 `ttyS3`、Pi 必 `ttyAMA0`）；用 `servo_probe` 在板上实测 500k 半双工稳定通。
2. **IMU I2C 重映射**：BNO08x 重接/配 I2C 总线号（泰山派 `i2c-2`、Pi `i2c-1`），确认 `imu_mount_quat` 安装朝向自检通过。
3. **机械重设计**：按新板尺寸/重量重做机壳支架，重评行走重心（可能需重新训练）。
4. **供电评估**：确认 5V/3A（或宽输入）与机器人电源树余量；Pi 尤忌劣质电源掉压。
5. **无线实测**：robotctl 无线 + `live_viewer --source robotctl` 的 WebRTC relay 在对应 WiFi 档次下的延迟/丢包。
6. **上板自检**：绝不在台架 PC 上断言。把 toml 烤到目标板，跑 robotd 开机校验（`feetech.rs:374-386` 的 reg6/reg33 硬校验）+ `pre_deploy_check.py --selftest`，确认总线打开、IMU 读到、EEPROM 四项通过。

---

## 6. 文档关系与现状结论

- `microduck-泰山派HAT研究-2026-11-08.md`：社区给泰山派做的 BMI088 扩展板 + MicroDuck 移植（独立 robotd 客户端）。是"泰山派上能跑 MicroDuck"的社区证据。
- 本文件：四板横向选型判断（功能覆盖 + 集成风险 + 迁移成本），角度互补。
- `MEMORY.md` SBC 选型段：保持"别买板"现状结论；本文件补充"若要买——Orange Pi A733 是原厂已验证基准（但属另一条线），泰山派同 SoC 可作 Radxa 替代，Pi 4B 功能够但机构/价格最差；§5 六步不可省"。
