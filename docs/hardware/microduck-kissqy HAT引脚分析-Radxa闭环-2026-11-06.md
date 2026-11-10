# kissqy RPI_Robot_HAT 引脚分析 —— Radxa 路线闭环

_2026-11-06。一手来源：`kissqy/elec_RPI_Robot_HAT`（GitHub，KiCAD 9 工程，codeload 下载 `elec_RPI_Robot_HAT.kicad_pcb` 本地解析）+ Radxa 官方 `radxa_zero_3w_product_brief.pdf` GPIO 复用表。随 `docs/hardware/microduck-双版本推进-Radxa与OrangePi-2026-11-06.md` 一起看。_

## 0. 结论（先给）

**Radxa Zero 3W + kissqy RPI_Robot_HAT，舵机总线插上即用，无需改任何引脚。**

- HAT 舵机总线 TTL 接在 40-pin 的 **Pin 8 / Pin 10**（RPi GPIO14/15 = UART）。
- Radxa Zero 3W 的 Pin 8/10 **硬件固定复用为 UART2_M0**（RK3566 官方 brief 确认），Linux 设备节点即 **`/dev/ttyS2`**——与主仓 `pollen-robotics/microduck`（本身就是 Radxa Zero 3W）的 robotd 配置完全一致，1 Mbps 已实测。
- HAT 的 **DE 方向信号由板内自动产生，不占用 SBC 任何 GPIO**（见 §2）——所以 Radxa 侧只需提供 UART（Pin8/10）+ I2C（IMU）+ 电源，不存在"引脚定义不兼容 RPi"的问题。
- IMU 走 I2C（HAT 按 RPi Pin 3/5 连接）；Radxa Pin 3/5 也是 I2C（I2C3），软件里把 I2C 总线号从 1 改成 3 即可，**非物理不兼容**。

> 这把 `microduck-双版本推进-...md` 里"待授权第 3 项（查 kissqy HAT 舵机总线接到 Radxa 哪个 UART）"**收口为已闭环**。

## 1. 一手证据链

### 1.1 HAT 硬件源（kissqy/elec_RPI_Robot_HAT）
- 仓库树：`README.md`、`docs/config.txt`、`elec_RPI_Robot_HAT.kicad_pcb`（2.2 MB）、`elec_RPI_Robot_HAT.kicad_pro`、`production/*.csv`。**未提交原理图 .sch**（仅 PCB）。
- README 原文："designed for raspberry pi"，含 **IMU over I2C**、**Dynamixel motor communication (both TTL and 485)**、audio、Qwiic。
- `docs/config.txt`（RPi 的 `config.txt`）：`enable_uart=1` + `dtparam=i2c_arm=on` + `dtparam=i2s=on` + `dtoverlay=tlv320aic3104`（音频 codec）——证实 UART/I2C 走 40-pin 标准位置。

### 1.2 40-pin 连接器 = J4（解析 PCB）
- `Library_Pollen:PinHeader_2x20_P2.54mm_Vertical_with_rasp_HAT_zero_SMD_connector`，refdes **J4**，装在 B 面（RPi HAT zero 尺寸适配）。
- J4 全部 44 个焊盘网络见下；舵机 TTL 来自 **Pin 8 = net `/Schematic/Audio/IO_14`**、**Pin 10 = net `/Schematic/Audio/IO_15`**。
- 网络名里的 `IO_14/IO_15` 正是 RPi 的 **GPIO14/15**（= UART TX/RX）；设计者把所有 SBC GPIO 归到 "Audio" section 命名，非语义错误。

### 1.3 舵机总线信号链（解析 PCB）
```
SBC UART (J4 Pin8/10, GPIO14/15)
   └─ net 31 / net 14 (Audio/IO_14 / IO_15)
        └─ U7 (pad2=net31), U8 (pad4=net31)   电平转换 / 缓冲
             └─ U8 pad6=net36, pad7=net37  →  J3 / J11  (Dynamixel 输出, 4-pin: BATT/GND/DATA+/DATA-)
```
- **J3 与 J11 并联**：`pad1=GND, pad2=+BATT, pad3=net36, pad4=net37`。这是 HAT 的 Dynamixel 连接器（TTL+485 双模，README 已声明）。
> 🔴 **订正（2026-11-10，SSOT 订正㉑ / 决策文档 §7.6⑥ kicad 双版 pad net 全表实测）——本节 §1.3 的座名归属记错、保留原文作史料**：本节把 `U8 pad6/7 → J3/J11` 记为『Dynamixel 输出 / TTL+485 双模』，**错在把 J3/J11 当成 TTL 舵机口**。双版 kicad 全表实测定案：**`J13/J14`（3P，JST EH 2.5mm）= TTL 半双工**（pin1=GND/pin2=+BATT/pin3→`TH1`100R→`D4`5V1→`R33`→`U7`SN74LVC1G126/`U6`SN74LVC1G125→`IO_14/IO_15`，`Dynamixel_dir` 自动切收发；带 100R 串阻+5.1V 齐纳保护）；**`J3/J11`（4P，JST EH 2.5mm）= RS-485 差分**（pin3/pin4→`U8`=`SIT3088E`/`GM3088ENA` pad6/7 A/B，`Dynamixel_dir` 自动 DE/RE）。⇒ **飞特 HD-1910（TTL 半双工、1M）应接 `J13/J14`，不是 `J3/J11`**；`J4 Pin8/10=GPIO14/15=UART2_M0=/dev/ttyS2`、`DE 板内自动、SBC 不出 DE GPIO` 两条结论不变。⚠️ 上板前以实物扫 ID 为准（kicad+卖家 UI 双指 J13/J14）；误接 J3/J11 = 舵机无应答。本节 U7/U8 的 pad net 原始记录仍是一手、只是『J3/J11=TTL 舵机口』的归属推断错误，勿再据此接线。
- U7/U8 还接收 **net 45 (Dynamixel_dir = DE 方向)**。

### 1.4 DE 方向信号——HAT 内部自动，不依赖 SBC
- net 45 的全部焊盘归属：**Q1(pad3)、R28(pad2)、R40(pad1)、U6(pad1)、U7(pad1)、U8(pad3)**。
- **J4 的 44 个焊盘中没有 net 45** ⇒ DE 完全由 HAT 板内电路（Q1 晶体管 + U6 缓冲 + U7/U8 收发器使能）产生，典型的"TX 驱动自动 DE"结构。
- 结论：**SBC 不需要提供任何 DE / 方向 GPIO**。这比需要 SBC 给 DE 的 HAT 更省心，也是 Radxa 即插即用的关键。

> 注：旧记忆里"kissqy PA1 DE 极性与 DuckBuddy 相反"的 **PA1 属于 DuckBuddy（Orange Pi 版，用 Allwinner PA1 作 DE）**，不是 kissqy HAT。kissqy HAT 的 DE 是内部自动的，无 SBC GPIO 参与——两者机制不同，不可混用该结论。

### 1.5 Radxa Zero 3W Pin 8/10 的 UART 节点（官方 brief 确认）
Radxa 官方 `radxa_zero_3w_product_brief.pdf` GPIO 复用表（节选）：
```
Pin#  Function1     Function2
 8    GPIO0_D1      UART2_TX_M0
 9    GND
10    GPIO0_D0      UART2_RX_M0
```
- **Pin 8/10 硬件固定复用为 UART2_M0**（RK3566）。Radxa 官方文档同时注明"UART2_M0 是默认 U-Boot 控制台，不建议作普通串口"——但主仓 `pollen-robotics/microduck` 恰恰是 Radxa Zero 3W，把该口当舵机总线跑 1 Mbps（之前文档已核：`/dev/ttyS2` 跑 1 Mbps）。
- RK3566 惯例：UART2 对应 `/dev/ttyS2`。故 **HAT 舵机总线物理 = Pin8/10 = UART2_M0 = `/dev/ttyS2`**，与主仓 robotd 配置零差异。
- ⚠️ 待现场确认（非阻塞）：具体设备节点名（`ttyS2` vs `ttyFIQ0`）以 `dmesg | grep tty` 上电后为准；功能层（UART2_M0 on Pin8/10）已由官方 brief 钉死。

## 2. 引脚级兼容性判定

| 信号 | HAT (J4, RPi 定义) | Radxa Zero 3W | 结论 |
|---|---|---|---|
| 舵机总线 TTL | Pin 8/10 = GPIO14/15 = UART | Pin 8/10 = UART2_M0 (=`ttyS2`) | ✅ **物理对齐，插上即用** |
| DE 方向 | 板内自动（net45，不连 J4） | 无需 SBC GPIO | ✅ 无依赖 |
| IMU I2C | Pin 3/5 = I2C1 (SDA/SCL) | Pin 3/5 = I2C3 (SDA/SCL) | ⚠️ 功能兼容，软件改 I2C 总线号 1→3 |
| 电源 | Pin 2/4 = +5V, Pin 1/17 = +3V3, GND | 同 | ✅ |
| 音频 I2S | Pin 12/35/36/37/38/40 等 | 部分引脚为 I2S3 / GPIO（功能对齐） | ⚠️ 音频非必需，可不管 |

## 3. 与 Orange Pi 路线对照（收口双版本文档）

| | Radxa Zero 3W | Orange Pi Zero 3W |
|---|---|---|
| HAT 舵机总线 | Pin8/10=UART2_M0=`ttyS2`，**插上即用** | Pin8/10 也是 UART（物理兼容），但节点名/复用可能不同，**需现场确认** |
| DE | HAT 内部自动 | 同（HAT 内部自动，与 SBC 无关） |
| IMU I2C | Pin3/5=I2C3，改总线号 | Orange Pi Pin3/5 **不是 I2C**（Allwinner 引脚定义差异），IMU 可能不工作 ⇒ 需另接 I2C 或换 IMU 走法 |
| 机械 | 与作者 fanhao375 飞特版 CAD **零改动** | 需自建载板（已建 `cad/orangepi_zero3w_carrier.scad`） |

**结论**：kissqy HAT 在 Radxa 上几乎零摩擦（仅 I2C 总线号配置差异）；在 Orange Pi 上舵机总线可用，但 **IMU 的 I2C 因 Orange Pi Pin3/5 非 I2C 而可能失效**——这是 Orange Pi 路线比 Radxa 多出的一个真实坑，之前未明确。

## 4. 待现场确认（非阻塞，上电后 5 分钟可验）
1. Radxa 上 `dmesg | grep tty` 确认舵机总线节点名（预期 `ttyS2`）。
2. `i2cdetect -y 3` 确认 HAT IMU 出现在 I2C3（预期地址 0x68/0x69 类）。
3. 实物插 HAT 后，复用之前的 `sts_bench.py` 扫 ID×波特率，确认 1 Mbps 通。
4. Orange Pi 路线若推进，需额外验证 IMU I2C 在 Orange Pi 40-pin 上的落点（可能要飞线或换 I2C 引脚）。

## 5. 方法备注
- GitHub `contents` API 对 >1 MB 文件不返回 content；改走 `codeload.github.com/<o>/<r>/tar.gz/refs/heads/main` 下载 tarball，仅解压 `*.kicad_pcb`（24 MB tarball → 2.2 MB PCB）。
- KiCAD 9 PCB 的 footprint `Description` 属性含未转义括号，破坏朴素括号匹配；改用"位置法"：先定位所有 `(property "Reference" ...)` 与 `(pad ... (net ...))`，按字符位置归属，不提取整块。
- 本机无 OpenSCAD/cadquery，HAT 渲染未做；本次纯几何/网络解析，不依赖渲染。
