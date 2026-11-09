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

## 4. 落地建议（若真换 Pi 4B）

1. `config.txt` 加 `dtoverlay=disable-bt` → 用 `ttyAMA0`（PL011）。
2. toml `port` 改 `/dev/ttyAMA0`（原 `ttyS2` 在 Pi 上不存在）。
3. **接 Waveshare Bus Servo Driver Board**（或等价自动方向板）做硬件半双工 + 电平转换；robotd 不改方向代码。
4. 其余（HLS 500k 分支、`position_kp`/`gain`、EEPROM 开机硬校验、IMU 朝向）与现状 Radxa 完全一致，无需重做。
5. 机构（85×56mm/75g）仍要重做；价格/供电仍是缺点（见四板对比 §3.4）。

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
