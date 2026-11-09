# Pi 4B 上开源 Feetech 总线舵机方案研究（2026-11-09）

> 来源：用户问"Pi 4B 有开源项目吗"，按"先查资料再下结论"纪律做的查证。
> 目的：弄清 Pi 系（含 4B）跑 Feetech/STS 总线舵机到底怎么接、半双工方向到底落在哪一层，
> 以支撑 SBC 选型里 Pi 4B 段的结论。
> 证据全部来自真实仓库源码 / 官方文档，非推演。

---

## 0. 一句话结论

Pi 4B 上**有成熟的开源 Feetech/STS 总线舵机驱动方案**（LeKiwi、commanderfun/Waveshare、Joshua、python-st3215），
但**完整 Microduck/HD-1910 复刻线，开源界没人用 Pi 4B**（都用 Radxa Zero 3W 或 Pi Zero 2W）。
对**我们的 robotd**（Rust、用户态零 RTS 翻转）：Pi 4B 能跑，但方向必须落在**硬件/kernel 层**（接 Waveshare 类自动方向板，或板载 UART+kernel DE），
**不能照搬 LeKiwi 那种"USB 适配器 + scservo_sdk 翻 RTS"的 Python 栈**。

---

## 1. 开源项目分三类（查证结果）

### 1.1 四足/机器人主控用 Pi 4B——但都是 PWM 舵机（≠ 总线舵机）
- `aswin-pn/project_axl`、`UMN-VR/GoldyDogV7`、`mrhello291/SimpleQuad`：Pi 4B + **PCA9685 + MG996R/PDI-HV5523MG 等 PWM 舵机**，ROS/裸 Python。
- `WAVEGO KIT`（Waveshare 商业套件）：Pi 4B + ROS2。
- ⚠️ 证明"Pi 4B 当四足主控算力够、社区成熟"，但舵机是 **PWM 波形驱动**，跟我们的 Feetech **TTL 半双工总线（HLS/STS 协议）** 是完全不同的通信栈，代码不能直接借。

### 1.2 Pi 4B + 飞特 STS 总线舵机——有现成开源驱动（关键证据）
- **`e5l/lekiwi-control-center`**（LeKiwi / LeRobot 系）：README 明写 *"Raspberry Pi (tested on Pi 4)"*，控制的就是 **Feetech STS3215 servos**（SO-ARM100 机械臂 / LeKiwi 移动底盘）。
- **`commanderfun/STS3215`**（HuggingFace LeRobot 社区推荐）：明确为 **Waveshare Serial Bus Servo Driver Board** 写的高层封装。
- **Joshua AI Robotics**（`joshua-ai-robotics.org`）：`STS3215_SERVO` 驱动（C++ + Python），SO-ARM100，`serial_port="/dev/ttyUSB0"`、`baudrate=1000000`。
- **`sinayanaik/python-st3215`（aka Mickael-Roger）**：pyserial 高层封装，自动发现舵机。
- → 证明 **Pi 4B 当飞特总线舵机主控，在软件/驱动层已被多个开源项目验证可行**。我们的 HL-1915 正是 STS3215 姊妹型号，协议栈通用。

### 1.3 完整 Microduck / HD-1910 复刻线——开源界没人用 Pi 4B
- `fanhao375/microduck-replica`、`chenkui164/microduck-replica`、`AI-FanGe/Microduck-build-tutorial` 全用 **Radxa Zero 3W + Pollen RPI Robot HAT**；官方 stock 用 **Pi Zero 2 W**。
- Pi 4B 没被任何复刻线列为机器人主控。

---

## 2. 半双工方向控制：三种现实实现路径（核心，决定了 robotd 怎么接）

Feetech/STS 总线是**半双工 TTL**（同一条线收发），必须有方向切换（DE/RE）。查源码确认开源项目用三种不同落点：

### 路径 A：USB 串口适配器 + scservo_sdk 翻 RTS（LeKiwi/LeRobot 系）
- 证据：`e5l/lekiwi-control-center` `config/robot.yaml:6` → `port: "/dev/ttyACM0"`（USB 适配器，非板载 mini-UART）；
  `src/lekiwi_control/motors/feetech/feetech.py:37` → `DEFAULT_BAUDRATE = 1_000_000`；
  `feetech.py:128` → `self.port_handler = scs.PortHandler(self.port)`（**scservo_sdk 飞特官方 SDK**）。
- 机制：scservo_sdk 的 `PortHandler` 在发送时**翻 RTS 脚接 DE**（dynamixel/feetech SDK 标准做法）。
  ⚠️ 注意 `feetech.py:49/52/55` 的 "direction bit" 注释是**协议帧方向位**（0x2e 最高位 / 0x2c bit11 / 0x2a 最高位，表示正反转），**不是硬件 RTS**，两者不同概念。
- 落点：**方向在 SDK（用户态）层**，靠 USB 适配器 RTS 脚。

### 路径 B：外部 Bus Servo Driver Board 硬件自动方向（Waveshare / LeLamp 系）
- 证据：`commanderfun/STS3215` `servo.py:5` 明确 *"Waveshare Serial Bus Servo Driver Board. Wraps the low-level scservo_sdk"*；
  `servo.py:24` → `from scservo_sdk import sms_sts, PortHandler`；封装里**零 RTS 代码**。
  kevsrobots 博客证实 Waveshare 板 *"handles the voltage regulation and half-duplex conversion for you"*。
- `humancomputerlab/LeLamp`：Pi Zero 2W + **自定义 Servo Driver Board**（ESP32 + TTL 电平转换 + 电源分配），走 `/dev/ttyUSB0`——方向由驱动板硬件处理。
- 机制：板子内部用 **MAX13487 类自动方向收发器或 MOSFET 方案**，方向 100% 在硬件，MCU 只发普通全双工 UART。
- 落点：**方向在硬件层**，软件零参与。

### 路径 C：板载 UART + kernel/hardware DE gpio（我们 robotd 的泰山派/立创载板方案）
- 证据：我们 vendored 的泰山派内核补丁 `485_ctrl_gpio`（GPIO3_C4），自动在 FIFO 批次翻 DE。
- 机制：方向在 **kernel 层**，robotd 用户态完全不碰（已查源码：FeetechIo/ScsIo 只 `serialport::new().open()`，全仓零 RS485/TIOCMSET）。
- 落点：**方向在 kernel 层**。

---

## 3. 对我们 robotd 的含义（最关键，精确到"不能照搬"）

- 我们已查源码确认：**robotd 用户态零 RTS 翻转**（DuckBuddy-main 全仓 + rustypot 1.6.0 零 RS485/TIOCMSET/set_rts）。
- 因此 robotd 在 Pi 4B 上**不能照搬路径 A**（LeKiwi 的 USB 适配器 + scservo_sdk 翻 RTS）——因为那是 Python SDK 翻 RTS，而 robotd 不用 SDK、也不翻 RTS，接纯 USB 适配器会**静默读不到总线**（症状像"舵机坏了"）。
- robotd 在 Pi 4B 上的方向必须落在**硬件/kernel 层**：
  - **最简**：接一个 **Waveshare 类 Bus Servo Driver Board**（硬件自动方向 + 电平转换），机器人侧 `ttyAMA0` 接驱动板 UART 口，**robotd 零改动**（与路径 B 同机制）。
  - 或：板载 UART + kernel DE（路径 C 思路，但要在 Pi 内核上重做 485_ctrl_gpio 类补丁，工作量大）。
- **串口**：无论哪种方向方案，Pi 4B 必须切 **PL011**（`config.txt` `dtoverlay=disable-bt`，把 mini-UART `ttyS0` 换成 `ttyAMA0`），否则波特率随 GPU 时钟浮动、无硬件 RTS/CTS。

---

## 4. 落地建议（🔴 2026-11-09 已被完整方案订正，勿照抄旧版）

> **完整可执行方案见 `microduck-Pi4B-完整部署方案-feetech_hls-2026-11-09.md`**（与泰山派烤板步骤同粒度）。
> 本节旧版 5 条有**两处需要订正**：

- 🔴 **订正 1（自相矛盾）**：旧第 1/2 条要切 PL011 用 `ttyAMA0`，第 3 条却要接 Waveshare 板——若该板走 **USB 模式 B**，根本用不到板载 UART；只有走 **UART 模式 A（跳线 A，RX-RX/TX-TX）** 时两者才是一套。两条路必须二选一并写清。
- 🔴 **订正 2（USB 路径被预算否决）**：项目 `probe_bus_budget.py` 真机实测（`.workbuddy/memory/2026-11-06.md:245-250`）显示 500 kbps / 16 设备（15 关节 + IMU 200）每 tick **标称 10.28–11.01 ms、最坏 16.68–17.41 ms**，20 ms 周期只剩 **2.59–3.32 ms** 给 ONNX；USB CDC 的批延迟不可调（CH340/CP210x 无 `latency_timer`，FTDI 默认 16 ms ⇒ 62.5 Hz）。⇒ **整机主方案必须是板载 PL011 + 外部自动方向板，USB 只用于台架单舵机调试**（否则掉到 `update_gate` 45 Hz 以下 → updater 自动回滚，症状像发布系统故障）。
- ✅ **订正后的推荐**：`dtoverlay=uart3`（Pi 4B 额外 PL011，GPIO4/5，`/dev/ttyAMA3`）——**不用关蓝牙**、避开 GPIO0/1 保留脚；比旧版 `disable-bt → ttyAMA0` 更优（官方 `overlays/README` 明列 UART2–5）。PL011 参考时钟 48 MHz ⇒ `48e6/(16×500000)=6.0` 整数分频，500 kbps 精确。
- 🔴 **订正 3（内核补丁不可复用）**：泰山派 vendored 补丁改的是 `8250_dw.c`，Pi 4B 是 `amba-pl011.c`；PL011 硬件无 RS485、主线支持到 2021 才有、RPi 分支 2026-01 才修掉 `pl011_axi_probe` 的 hrtimer panic（PR `#7202`），且社区只验证到 460800 ⇒ **kernel DE 路径不做首选**。
- 🔴 **订正 4（IMU 代次）**：本部署 toml 绑 `DuckBuddy-main` 代次，IMU 是**总线板 ID200**（随舵机总线走），**Pi 4B 不需要 I2C**；四板文档 §4 功能表「IMU I2C / Pi i2c-1 需开」是另一代次口径。

保留有效结论：`servo="feetech_hls"` / 500k / ID 1–15 / `position_kp` / `gain` / EEPROM 硬校验 / 机构重做（85.6×56.5 mm / 75 g）与现状 Radxa 一致，无需重做。

---

## 5. 证据清单（repo:path）

| 项目 | 关键文件 | 说明 |
|---|---|---|
| `e5l/lekiwi-control-center` | `config/robot.yaml:6`（ttyACM0）、`src/lekiwi_control/motors/feetech/feetech.py:37,128`（baud 1M、scservo_sdk PortHandler） | 路径 A：USB 适配器 + SDK 翻 RTS |
| `commanderfun/STS3215` | `servo.py:5,24`（Waveshare 板 + scservo_sdk，零 RTS） | 路径 B：硬件自动方向 |
| `joshua-ai-robotics.org` | `docs/robot-layer.html`（`STS3215_SERVO`，ttyUSB0，baud 1M） | 路径 B 同类 |
| `humancomputerlab/LeLamp` | `docs/assets/drawings/ServoDriver.jpg` + 规格（Pi Zero 2W + 自定义 Servo Driver Board，ttyUSB0） | 路径 B 同类 |
| `sinayanaik/python-st3215` | `st3215/__init__.py`（pyserial 封装） | 通用 STS 驱动 |
| kevsrobots 博客 | `www.kevsrobots.com/blog/bus-servos.html`（Waveshare 板 "handles half-duplex conversion"） | 路径 B 佐证 |
| 复刻线（无人用 Pi 4B） | `fanhao375/microduck-replica`、`chenkui164/microduck-replica`、`AI-FanGe/Microduck-build-tutorial` | Radxa Zero 3W / Pi Zero 2W |
