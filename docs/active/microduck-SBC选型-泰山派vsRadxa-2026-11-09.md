# HD-1910 主机 SBC 选型：泰山派(RK3566)能否平替 Radxa Zero 3W

_日期：2026-11-09 · 结论：功能 100% 覆盖；不是"即插即用平替"，是"同 SoC 的可行替代，落地在集成"。_

_一手来源：Radxa 官方文档/产品brief；立创·泰山派(LCKFB-TSPI-RK3566)数据手册与 Wiki；
robotd 源码(`configd/src/identity.rs`、`duck-control/src/feetech.rs`)；部署 toml(`out/robotd_hd1910_mode0.toml`)。
交叉印证见 `microduck-泰山派HAT研究-2026-11-08.md`（社区泰山派移植，确认其设备树用 `ttyS3`/`i2c-2`）。_

---

## 1. 结论（两句话）

- **功能层面：泰山派(RK3566)与 Radxa Zero 3W 同 SoC、同外设类别，机器人需要的每一项接口它都有，零功能缺口。**
- **工程层面：不是平替/即插即用。** 伺服总线是板载原生 UART（不是 USB），换板要重映射 UART 引脚与 `/dev/ttySx` 名、重接 IMU I2C、重做机构（泰山派 70×45mm / 98.6g vs Radxa 65×30mm / ~15g）、重评供电、并接受无线降级（2.4GHz n vs WiFi 6）。

> 项目现状（见 `MEMORY.md` SBC 选型段）：**此刻最优是"别买板"——台架 PC + URT-2 ¥0 且 50 Hz。**
> 除非要给真机上部署主机且 Radxa 不好买，否则泰山派与 Radxa 都不是当前刚需。若要上真机，泰山派是 Radxa 的可行替代，但下面 §4 的 6 步省不掉。

---

## 2. 为什么"软件/SoC 能跑"

- **同 SoC**：两者都是 Rockchip **RK3566**（4×Cortex-A55, aarch64, 1.6–1.8GHz）。指令集、Debian/Ubuntu 生态完全一致；robotd(Rust) 二进制无需为 CPU 重编译。
- **robotd 不钉板子厂商**：身份识别只从通用的 `/proc/device-tree/serial-number` 读 SoC 序列号
  （`configd/src/identity.rs:35` `const SERIAL_PATH: &str = "/proc/device-tree/serial-number"`）；
  `radxa-zero3` 只是 configd 连不上时的命名回退，无 Orange Pi / Radxa 专属 SoC 分支。

---

## 3. 为什么"不是平替"——四个真风险（集成差异，非功能缺失）

| 维度 | Radxa Zero 3W（现状） | 泰山派(LCKFB RK3566) | 风险 |
|---|---|---|---|
| **伺服总线** | `/dev/ttyS2` 原生 UART，feetech_hls，**500k 硬编码** | 同样有 RK3566 UART，但 **设备树通常暴露为 `ttyS3`**（社区移植印证），且 TX/RX/RTS 引脚分配两板不同 | 🔴 必改 toml `port` + 配设备树 pinmux（半双工方向脚 RTS） |
| **IMU I2C** | Radxa 某路 I2C | 社区移植用 **`i2c-2`** | 🟡 重接/重配 I2C 总线号与引脚 |
| **机构/重心** | 65×30 mm, ~15 g（Pi Zero 级） | 70×45 mm, **98.6 g** | 🔴 机壳为 Radxa 小板设计；泰山派大且重 ~80g，装机身抬高重心，影响平衡 |
| **供电** | 5V/2A USB-C | 5V/3A USB-C **或** 5–18V(JST/GH1.25) | 🟡 5V3A 略吃电；宽输入是优点但接法不同，重评电源树 |
| **无线** | **WiFi 6 + BT 5.4** 板载（robotctl + WebRTC relay 靠它） | 规格只写 **2.4GHz WiFi+BT**（多为 802.11n，未标 ax） | 🟡 远程控制/实时姿态流可靠性下降，需实测 |
| **价格** | ~¥136–165 | 基础版 ~¥138（近期 DDR 涨价至 ~¥580） | 🟢 同量级，无决定性节省 |

关键证据：
- 部署 toml 总线是**板载原生串口**而非 USB：`out/robotd_hd1910_mode0.toml:60` `port = "/dev/ttyS2"`；
  `feetech.rs:301` `serialport::new(port, BAUD_RATE)` 直接开；`BAUD_RATE = 500_000` 硬编码（toml 注释引 `feetech.rs:35`）。
- 半双工方向控制走串口自身（RTS/RS485，在 `Sts3215Controller` 内）——软件层板子无关，**物理 RTS 引脚位置随设备树变**。
- 社区泰山派移植：`hls_probe.py` 默认 UART `/dev/ttyS3`、IMU `i2c-2`（`microduck-泰山派HAT研究-2026-11-08.md` §3.6/§4）→ **印证换板后 `port` 与 I2C 总线号都要改**。

> ⚠️ **隐患**：该 toml 注释写的是"A733's UART7"（Orange Pi 线），文件却给 HD-1910/Radxa 用。
> **换板前先确认 Radxa 上 `ttyS2` 到底对应哪路 UART、哪些引脚**——连现状都可能接错，别先假设 Radxa 配置是对的。

---

## 4. 功能需求 ↔ 泰山派覆盖（逐项核对：全 ✅）

| 机器人需要的功能 | 泰山派有没有 | 证据/备注 |
|---|---|---|
| CPU 算力（robotd 50Hz 环 + ONNX 推理 obs61/act14） | ✅ 同款 | RK3566 4×A55，与 Radxa 同 |
| 伺服总线 UART @500k 半双工（feetech_hls, 15 舵机） | ✅ 有 UART | RK3566 多路 UART，40-pin 引出；RTS 方向脚为 UART 标准信号 |
| IMU：BNO08x 走 I2C | ✅ 有 I2C | 40-pin 支持 I2C（规格"支持 PWM,I2C,SPI,UART,GPIO"） |
| 同时占 UART + I2C | ✅ 足够 | 40-pin 同时多 UART + 多 I2C，总线与 IMU 不打架 |
| GPIO / 使能 / 方向控制 | ✅ 有 | 79 个拓展 IO、40-pin GPIO |
| USB（URT-2 / 调试 / 外设） | ✅ 有 | USB2.0 Type-A + Type-C（Radxa 多一个 USB3.0，舵机桥接 USB2.0 足够） |
| 无线控制（robotctl 网络 + WebRTC relay） | ⚠️ 有但弱 | 2.4GHz WiFi+BT（多为 n）；Radxa 是 WiFi 6。功能在，档次低 |
| 系统盘/启动 | ✅ 有 | eMMC(8–128GB) + TF 卡启动 |

---

## 5. 真要换：迁移清单（按风险排序）

1. **总线 UART 重映射**：在泰山派启用一路 UART（设备树 overlay），确认 TX/RX/RTS 引脚；把 toml `port` 改成对应 `/dev/ttySx`（社区变体多为 `ttyS3`，非 `ttyS2`）；用 `servo_probe` 在板实测 500k 半双工稳定通。
2. **IMU I2C 重映射**：BNO08x 重接/配泰山派 I2C 总线号（社区用 `i2c-2`），确认 `imu_mount_quat` 安装朝向自检通过。
3. **机械重设计**：70×45mm 占位 + 98.6g 配重，重做机壳/支架，重评行走重心（或重新训练）。
4. **供电评估**：走 5V3A 还是 5–18V 宽输入；确认机器人电源树余量。
5. **WiFi 实测**：robotctl 无线 + `live_viewer --source robotctl` 的 WebRTC relay 在 2.4GHz n 下的延迟/丢包。
6. **上板自检**：绝不在台架 PC 上断言。把 toml 烤到泰山派，跑 robotd 开机校验（`feetech.rs:374-386` 的 reg6/reg33 硬校验）+ `pre_deploy_check.py --selftest`，确认总线打开、IMU 读到、EEPROM 四项通过。

---

## 6. 与现有文档的关系

- `microduck-泰山派HAT研究-2026-11-08.md`：讲社区给泰山派做的 BMI088 扩展板 + MicroDuck 移植（独立 robotd 客户端 + socket broker 喂 IMU）。**那份是"泰山派上能跑 MicroDuck"的社区证据**；本文是"泰山派代替 Radxa 做我们 HD-1910 主机"的选型判断，角度不同、互补。
- `MEMORY.md` SBC 选型段：保持"别买板"现状结论；本文补充"若要买，泰山派可作 Radxa 替代，但 §5 六步不可省"。
