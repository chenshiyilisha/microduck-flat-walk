# HD-1910 复刻线 · Pi 4B 完整部署方案（`feetech_hls` 换板不换协议）

_起草日期：2026-11-09 · 状态：**方案草案（未上板、未买板）**，非已验证流程。_

_定位：综合前面几轮「SBC 四板对比 / Pi 4B 开源 Feetech 方案 / 全社区复刻参考价值 / kissqy Rust robotd / gyro_fusion 移植清单 / 策略导出部署链 / 泰山派烤板步骤」的全部查证结果，把 Pi 4B 从「开源现状调查」提升为一份与 `microduck-泰山派部署-feetech_hls烤板步骤-2026-11-09.md` 同粒度的可执行方案。_

**证据等级**（全文沿用）：`✅` = 官方文档 / 一手仓库源码 / 本项目实测；`🟡` = 社区实测或第三方规格（可信但未在本项目复现）；`⚠️` = **这是推的 / 未查到现成方案 / 需上板证实**。凡 ⚠️ 处不得当结论用。

**🔴 现状边界（用户定调）**：此刻只有**台架 PC + URT-2 + 单舵机**，没有机器人、没有 SBC 上板。软件 0 成本 ⇒ 本文件与其余 SBC 文档一样是**未来真决定换板时的参考，不是当前任务，别买板**（`MEMORY.md` SBC 段「现状定位」）。§13 列出了**在台架上零成本就能先验掉**的几项。

---

## 0. 一句话结论与最关键的三条新判决

**Pi 4B 能跑我们这套 `feetech_hls` robotd，且串口波特率比现状板更干净；但「怎么接」与泰山派完全不同，且开源界没有现成整机可抄。**

| # | 判决 | 依据 |
|---|---|---|
| 🔴 **N1** | **泰山派那套内核补丁一行都不能复用**：泰山派改的是 `drivers/tty/serial/8250/8250_dw.c`（DesignWare 8250），Pi 4B 的 UART 是 **ARM PL011 / `amba-pl011.c`**，是两套驱动、两套寄存器、两套 DE 时序 | vendored patch 的 hunk 路径；Raspberry Pi 官方 UART 文档；LKML `amba-pl011` RS485 系列补丁明写「AMBA PL011 do not have hardware support for RS485」 |
| 🔴 **N2** | **Pi 4B 主方案必须走板载 PL011，不能走 USB 串口**——用项目自己的总线预算实测反推（§6） | `.workbuddy/memory/2026-11-06.md:245-250` `probe_bus_budget.py` 真机实测 |
| ✅ **N3** | `BAUD_RATE = 500_000` 硬编码在 Pi 4B 上**精确可达**：PL011 参考时钟 48 MHz，`48e6/(16×500000) = 6.0` 整数分频（IBRD=6, FBRD=0），比现状 A733 UART7 的 `24MHz/16/3` 更整 | 树莓派论坛 `clk_summary` 实测 `uart 47999625`（≈48 MHz）；`rpi-hal` PL011 文档「Assumes a 48MHz UART reference clock… confirmed empirically」 |

> ⚠️ N3 的 6.0 是**算术推导**（基于已查实的 48 MHz 时钟），不是本项目在 Pi 4B 上量出来的位宽；上板必须用示波器/logic analyzer 确认 2 µs 位宽（§11 自检 #2）。

---

## 1. 决策：保留 `feetech_hls` 分支（不要切 SCS）

与泰山派草案 §1 同结论，Pi 4B 上额外补两行：

| 维度 | 本方案采用 | 不采用 |
|---|---|---|
| 协议实现 | `DuckBuddy-main/duck-control/src/feetech.rs` / `servo = "feetech_hls"` | EasyDuck `scs.rs` / 标准 SCS（1 MHz + 官方 ID 20-24/30-34/10-14） |
| 波特率 | **500_000**（`feetech.rs:35` 硬编码；toml **没有 `baud` 键**，写了反而 `deny_unknown_fields` 拒加载） | 1_000_000 |
| 关节 ID | **1–15**（`out/robotd_hd1910_mode0.toml:115`，来自 `hd1910m/radxa/installation.json`） | 官方 B 代 20-24/30-34/10-14 |
| 现有工具链 | ✅ `hls_probe` / EEPROM 校验 / 零位 / `pre_deploy_check` 全兼容 | ❌ 全不兼容 |

- 🔴 **H11 陷阱**（`deploy_import_checklist.md:90`）：两套 ID 体系不可混抄；且头 13/14 在两套里 `head_yaw`/`head_roll` 定义相反。照抄别家 `installation.json` ⇒ 15 颗全错位但 ping/读写/电气全过，症状只是「往错方向倒」。
- ⚠️ **Pi 4B 特有诱饵**：Waveshare / LeKiwi / SO-ARM100 生态默认 **1 Mbps + ST/SC 系列**；若照它们的示例把舵机 reg6 留在 0（1M），我们 robotd 会**完全静默**（与掉电不可区分）。reg6 必须逐颗改成 1（§8）。

---

## 2. 硬件清单与供电树

### 2.1 主控（✅ 官方规格）
`raspberrypi.com/products/raspberry-pi-4-model-b/specifications/`：
- BCM2711，4×Cortex-A72 @1.8 GHz，**aarch64**；1/2/4/8 GB LPDDR4。
- **输入电源 5 V DC via USB-C（≥3 A）或 via GPIO header（≥3 A）**；官方建议 15 W USB-C；2.5 A 仅在下游 USB 总耗 <500 mA 时可用。
- 40-pin GPIO、2×USB3 + 2×USB2、WiFi 5 双频 / BT 5.0、microSD（无 eMMC）、0–50 °C。
- 🟡 重量 **75 g**，尺寸约 **85.6 × 56.5 mm**（经销商规格页 `raspberrypi.dk`；官方 product brief 给外形图但文字未列重量）⇒ 与四板文档 §3.4 的 75 g 一致。

### 2.2 舵机接口板三选一（✅ 官方 wiki，⚠️ 一处未核实）

| 板 | 关键规格 | 对本方案的判定 |
|---|---|---|
| **Waveshare `Bus Servo Adapter (A)`**（42×33 mm） | 输入标注 **9~12.6 V**（ST 系列），但 wiki 明写 *「If you use an SC series servo… the voltage marked … is specified for ST series, but in reality, it can also accept the power voltage for the SC series servos」*；跳线 **A=UART**（wiki 明写接线是 **RX-RX / TX-TX，非交叉**）、**B=USB**（CH343，官方明列 *Raspberry Pi 4B*）；最多 253 颗 ST/SC | ✅ **首选硬件方向层**：板上「integrated control circuit」承担半双工转换，主机只发普通全双工 UART 帧。⚠️ **官方 wiki 未给方向控制芯片型号**（只给原理图 PDF），「MAX13487 类自动方向收发器」是社区说法，**未从原理图核实** |
| **Waveshare `Bus Servo Driver HAT (A)`**（65×57 mm，约 82 g） | ESP32-WROOM-32、**9~25 V** 输入、板载 **5 V buck 给 Raspberry Pi 供电**、40-pin 直插、RS485 + TTL 舵机口；ESP32 可刷 **Transparent Transmission** 固件后由 Pi 的 `/dev/serial0` 控制（wiki 明写此模式是 **RX-TX / TX-RX 交叉 + 共地**，与 Adapter (A) 相反） | ❌ **供电否决**：9~25 V 输入必须匹配舵机电压，我们是 **2S 7.4 V**（额定 4–8.4 V），接 9 V 起就超额定；改 3S 会烧舵机（`lib.rs:52` "burn on 3S"）。除非另做电源树，否则不用 |
| 自搭自动方向收发器 | MAX13487 / SP3485 类自动方向 + **3.3 V↔5 V 电平转换**（Pi GPIO 是 3.3 V TTL）+ 共地 | ⚠️ 可行但需画板/核电平；未查到本项目现成原理图。作为备选 |

- ⚠️ **电平**：Pi 4B GPIO UART 是 **3.3 V**，Feetech 总线是 5 V 级单线半双工。Adapter (A) 的 UART 口电平官方 wiki **未明示**，自搭必须加电平转换。这是会「接线全对但读不到」的静默项。
- ⚠️ **接线极性**：两块 Waveshare 板的 UART 接法**相反**（Adapter A = RX-RX/TX-TX；Driver HAT A 透传 = 交叉）。别把两块板的说明混用。

### 2.3 供电树（✅ 规格 + 项目约束）
```
2S LiPo / LiHV  7.4 V (满电 ≤8.4 V)
  ├── 舵机总线电源 ──> Adapter (A) DC5521 / 绿色端子 ──> 15×HD-1910（板无稳压，输入=输出）
  └── 5 V / ≥3 A Buck ──> Pi 4B（USB-C 或 GPIO 5V 脚，官方两种都允许）
        └── 必须共地（总线参考地 ↔ Pi GND）
```
- 🔴 `[battery] cells = [2]` + `max_volts = 8.4` **必须保持**（`toml:127-128`；默认 `[2,3]` 会把 3S 判成合法并照常驱动 ⇒ 烧舵机，**且不报错**）。
- 🔴 robotd 上电至少 **~6.0 V**（`toml:129-132`：4.6 V / 2 串 = 2.3 V/cell 低于 2.95 V 下限 ⇒ 报「neither 2S nor 3S」并保持瘫软）。Pi 的 5 V 与舵机电池是**两个域**，别拿 Pi 的 5 V 去驱动舵机做整机测试。
- 🟡 **散热**：第三方 Pi 4B 持续推理实测 SoC 12 分钟 45→82 °C 触发降频至 600 MHz、推理慢 3.2×（CSDN 实战贴）。50 Hz 硬实时环被降频打乱的风险真实存在 ⇒ 散热片/风扇 + `performance` governor（§7）。

---

## 3. UART 层：Pi 4B 特有的三条岔路（✅ 官方资料）

`raspberrypi.com/documentation/configuration/uart.md` + `/boot/firmware/overlays/README`：

- ✅ **Pi 4 默认**：primary = **UART1（mini-UART，`/dev/ttyS0`）**，secondary = **UART0（PL011，`/dev/ttyAMA0`）连蓝牙**。`/dev/serial0` 是 primary 的符号链接。
- 🔴 **mini-UART 死穴**：时钟来自 VPU core clock，core 频率动态变化 ⇒ **波特率跟着变**；`enable_uart=1` 只是把 core 锁在 250 MHz 才勉强可用。500 kbps 半双工舵机总线绝不能用（四板文档 §3.4 已记 3.2% 偏差超容限）。

| 方案 | 配置 | 端口 | 评价 |
|---|---|---|---|
| **U1**：关蓝牙换 PL011 | `sudo systemctl disable hciuart` + `dtoverlay=disable-bt` | `/dev/ttyAMA0`（GPIO14/15） | ✅ 官方标准做法；代价是**失去板载蓝牙** |
| **U2 ★ 推荐**：启用额外 PL011 | `dtoverlay=uart3`（可选 `,ctsrts`） | `/dev/ttyAMA3`（GPIO4/5） | ✅ Pi 4B 有 **UART2–5 共 4 个额外 PL011**，官方文档明列 `dtoverlay=uart2..uart5`；**不用关蓝牙**、不占主串口、避开了 GPIO0/1 保留脚 |
| U3：USB CDC | 插 CH343 适配器 | `/dev/ttyACM0` | ⚠️ 完全绕开 UART 问题，**但被 §6 的总线预算否决**（仅可用于台架/调试） |

**UART2–5 引脚表**（`/boot/overlays/README`，社区多处逐字转录）：
```
uart2: GPIO0-3   (TXD2=GPIO0, RXD2=GPIO1)  ← GPIO0/1 是 HAT ID EEPROM 保留脚，不建议
uart3: GPIO4-7   (TXD3=GPIO4, RXD3=GPIO5)  ← ★ 推荐；ctsrts 时 CTS/RTS 在 GPIO6-7
uart4: GPIO8-11  ← 与 SPI0 冲突
uart5: GPIO12-15 ← 与默认 gpio-fan 冲突，且 ctsrts 会占 GPIO14/15
```
- ✅ 设备节点：当前内核 `/dev/ttyAMAn` 对应 UARTn；旧 OS 是顺序编号 ⇒ **别写死，先看 `ls -l /dev/ttyAMA*` + `dtoverlay -h uart3`**。
- 🔴 **`/dev/serial0` 这个符号链接会随 overlay 变**（它永远指向 primary）⇒ toml 里写**具体设备名**，不要写 `serial0`。
- ✅ 必须**禁掉串口控制台**：`raspi-config` → Interface Options → Serial Port（login shell = No / hardware = Yes），或从 `/boot/firmware/cmdline.txt` 删掉 `console=serial0,115200`。否则内核日志会往舵机总线灌字节。
- ⚠️ **未查**：GPIO4/5 对应的 40-pin **物理脚号**、以及 `ctsrts` 时哪根是 RTS。GPIO 编号是查实的；物理脚位要查官方 pinout 图钉死，**不要照抄 Radxa / 泰山派排针定义**。

---

## 4. 🔴 半双工方向层：本方案最关键的判决

### 4.1 前提（R1 已查源码闭环，见泰山派草案 §9）
我们 `feetech_hls` robotd **用户态完全不翻方向脚**：`FeetechIo::open`(`feetech.rs:301`) 只 `serialport::new(port, BAUD_RATE).timeout(...).open()`；整个 `DuckBuddy-main`（含 firmware 子仓）+ `rustypot` 1.6.0 **零** `TIOCSRS485/TIOCMSET/set_rts/RS485` 代码；EasyDuck `ScsIo::open`(`scs.rs:199`) 同样。⇒ **方向 100% 必须由 kernel/硬件提供**，且不存在「robotd 与内核双重驱动」的冲突。

### 4.2 三条路径在 Pi 4B 上的可用性

| 路径 | 机制 | Pi 4B 判定 |
|---|---|---|
| **A. SDK 翻 RTS** | LeKiwi `config/robot.yaml:6` ttyACM0 + `scservo_sdk` `PortHandler`(`feetech.py:128`) 用户态翻 RTS 接 DE | ❌ **对这一类适配器不可用**：robotd 不用 SDK、也不翻 RTS；接**没有硬件方向脚**的 USB 适配器会静默读不到总线，症状像「舵机坏了」。⚠️ 判据不能一概套到所有 USB 适配器，见 §4.2.1 |
| **B. 外部板硬件自动方向** | `commanderfun/STS3215/servo.py:5,24`（Waveshare 板封装，零 RTS 代码）；kevsrobots 博客「handles the half-duplex conversion for you」 | ✅ **★ 主方案**：接 Adapter (A) 的 UART 口（跳线 A），方向由板上电路完成，**robotd 零改动** |
| **C. kernel DE / RS485** | 泰山派 = `8250_dw.c` + `485_ctrl_gpio`（GPIO3_C4） | ⚠️ **不推荐**，见下 |

### 4.2.1 🔑 2026-11-09 精确化：CH343 自带 `TNOW` 硬件方向脚

WCH 官方 `wch.cn/products/CH343.html` 原话「**支持半双工，提供正在发送状态 TNOW 支持 RS485 切换**」，同页还写「通讯波特率 50 bps–6 Mbps」「支持免安装的操作系统内置 CDC 类驱动程序」。⇒ **USB 适配器不必然需要 SDK 翻 RTS**：只要板子把 CH343 的 `TNOW` 接到收发器 DE/RE，方向就在**芯片硬件层**，robotd 零改动照样能收发。我们台架的 URT-2 正是 CH343P（PnP `USB\VID_1A86&PID_55D3`，`chenkui164/调试记录.md` 与 `fanhao375/tools/飞特/README.md` 均确认），能在 1 Mbps 下 ping 通单舵机就是这条路径的证据。

- ⇒ 路径 A 的正确判据是「**这个适配器有没有把方向做在硬件里**」，不是「是不是 USB」。LeKiwi 那类靠 SDK 翻 RTS 的仍不可用；CH343 + TNOW 引出的板子可用。
- ⚠️ 这**不推翻 N2**：USB 被否决的理由是 §5 的总线预算 / 批延迟，与方向无关。此处只是把「USB 一律静默读不到总线」这句过度声明收窄。
- 🔴 `TNOW` 是否真被 Adapter (A) 引出并接到 DE，仍属 R4（官方只给原理图 PDF，未核实）。**别把「芯片支持」当成「这块板已接好」**。

### 4.3 为什么路径 C 在 Pi 4B 上要单独判定（本次新建证据）
- ✅ **补丁不可复用**：泰山派 vendored patch 的三个 hunk 是 `8250_dw.c` / `8250_port.c` / `serial_8250.h`；Pi 4B PL011 走 `drivers/tty/serial/amba-pl011.c`。**驱动不同，patch 直接不适用**。
- ✅ **PL011 硬件无 RS485**：LKML 2020-01-07 Ivan Sistik `[PATCH] tty: serial: amba-pl011: added RS485 support` 原话「AMBA PL011 do not have hardware support for RS485」，其实现用 RTS 脚 + 2 个 hrtimer 轮询 TX FIFO 空（PL011 **没有 FIFO empty 中断**），会多一个 timer tick 的延迟。
- ✅ **主线后来有了**：2021-06-18 Lino Sanfilippo `[PATCH v2] serial: amba-pl011: add RS485 support`，支持 `TIOCSRS485` + DT `rs485-enabled-at-boot-time`，**测试于 Raspberry Pi CM3**；主线现已含 `rs485_tx_drain_interval` / `pl011_rs485_tx_stop()` 代码。
- 🟡 **但 RPi 自家内核刚修完 panic**：2026-01-20 树莓派论坛 6by9 明确：上游两个 fix 改了 `pl011_probe`，而 RPi 分支的 `pl011_axi_probe`（RP1，**也用于 Pi0–Pi4**）漏了 hrtimer 初始化 ⇒ RS485 模式下 kernel bad reference → watchdog 重启；PR `raspberrypi/linux#7202` 修复后，用户 `sudo rpi-update pulls/7202`（6.18.6-v8+）在 **CM4 UART3 RS485 @115200 + UART4 @460800** 上验证通过。
- ⇒ ⚠️ **结论**：路径 C 在 Pi 4B 上「理论可行但要挑内核版本 + 需要 `ctsrts` 把 RTS 引出 + 500 kbps 半双工舵机总线**从未有人验证过**（社区只到 460800）+ PL011 无 FIFO empty 中断带来的额外延迟正好压在 §6 的紧预算上」。**不做首选**；若坚持走 C，必须先在台架用单舵机 + 示波器验 DE 时序。

### 4.4 方向波形验收（🟡 工业界通用判据）
用双通道抓 **TXD** 与 **DE**：DE 必须在**请求第一个起始位之前**拉高、在**总线上最后一个停止位结束之后**才拉低（Modbus RTU 排障文献，DE 时序是最常被误诊的静默故障：主机 UART 报发送成功、从机从未响应）。负对照：把 DE 断开 ⇒ 总线全沉默。

---

## 5. 🔴 为什么不能走 USB：用项目自己的实测预算反推（N2）

这一节是**本方案相对「Pi 4B 开源现状研究」新增的决定性结论**，也订正了那份文档 §4 的落地建议。

- ✅ 每 tick 帧长 **413 B**（`deploy_import_checklist.md` / 记忆 2026-11-04:554-563）：`sync_read` 发 24 收 336（16 设备 = 15 关节 + IMU 200）+ `sync_write` 发 53。
- ✅ **`probe_bus_budget.py` 台架实测 + 比值外推**（`.workbuddy/memory/2026-11-06.md:245-250`，N=5 重复 + selftest 25/25）：实测条件是 **COM3 / ID10 / 1 Mbps / 单舵机**，量到每字节 10.58–11.60 µs、固定开销 76–99 µs/包；**500 kbps / 16 设备的标称档 10.28–11.01 ms（中位 10.81）、最坏档 16.68–17.41 ms 是按无量纲比值外推出来的，不是 500 kbps 直测**。日志明写「跨波特率只能搬比值，不能搬绝对时间」与「⚠️ USB 批延迟每次不同 ⇒ 单次读数不能写定值」。⇒ 20 ms 周期里**只剩 2.59–3.32 ms 给 ONNX 推理**（外推值）。
  - 🔴 **2026-11-09 订正**：本条初版写成「500 kbps / 16 设备台架真机实测」，混淆了「1M 单设备实测」与「比值外推」。数字不变，**证据等级从实测降为外推**，判决 N2 仍成立但不可当成 Pi 4B 实测。另注：**整个台架参数体系都在 1 Mbps 下测**（`2026-11-04.md:558` 「台架实测 ID10/CH343/1 Mbps」），而部署目标是 500 kbps——台架不能当作 500k 的已验证平台；这只影响「用 URT-2 验 500k」的可行性，**不影响部署线本身**（部署走板载 UART）。
- ✅ 45 Hz 门槛（`update_gate.min_achieved_hz`）只管「活着」；一次读超时 30 ms > 20 ms 周期且 Skip 不补。B23 指出低于门槛 ⇒ unhealthy ⇒ **updater 自动回滚 release，症状像发布系统故障**。
- 🟡 USB 转串口的已知延迟：FTDI `latency_timer` 默认 **16 ms ⇒ 62.5 Hz 上限**（`cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer` 可改 1，但重启/重插会回退）；`orca_core` 文档明写 **CH340/CP210x 没有这个可调项**。CH343 是 CDC/ACM（`/dev/ttyACM0`，Linux 5.x+ 内置驱动免装），规格 **50 bps–6 Mbps**，但**CDC 端点轮询 + 批延迟不可调、也未经本项目实测**。
- 🔴 **2026-11-09 新增两条独立证据（社区实测，非官方）**，来自 `bun-serial` README 的 CH343 / Linux `cdc_acm` / Radxa ZERO 3W 实测记录：
  1. **「驱动接受 ≠ 芯片真发」**：CH343 在 `400000` / `1152000` / `1843200` 波特下**驱动接受、随后一个字节都不发**（写超时）；`250000` / `256000` / 常规值到 3M 才工作，原话 *"Try an unusual rate on your adapter before relying on it"*。**500000 不在其已验证集合里** ⇒ R3 从「精度待示波器」升级为「**可用性本身待验**」。规格表写 50 bps–6 Mbps 只是范围，不能当可用性证明。
  2. **`drain()` 提前 40–130 ms 报告完成**（芯片仍握着最后若干字节），且 *"A baud rate change or an RS-485 turnaround straight after drain() can cut them off"* ⇒ 直接打在半双工方向切换上；对 20 ms/tick 的 50 Hz 环是比 FTDI 16 ms 更严重的量级。
- 🟡 **Linux 驱动路径分叉**（同一颗 CH343 会有不同节点与不同行为）：CDC-ACM → `/dev/ttyACM*`；内核 `ch341` 模块（5.14+ 扩展覆盖 CH343）→ `/dev/ttyUSB*`；WCH 厂商 VCP 驱动 `ch343.ko` → `/dev/ttyCH343USB*`。⇒ 上板先 `dmesg` / `ls -l /dev/tty*` 确认绑的是哪条，非标准波特率行为不能跨驱动外推。

⇒ 🔴 **判决**：总线预算最坏档已吃掉 20 ms 周期的 83–87%，USB 额外几毫秒几乎必然把 50 Hz 环顶到 45 Hz 以下。所以 **Pi 4B 主方案 = 板载 PL011（U2）+ 外部自动方向板（路径 B）**；USB（U3 / Adapter A 跳线 B）**只用于台架单舵机调试、不用于整机**。
- ✅ **负对照（能删就红）**：整机 15 颗 + IMU 跑起来后，把 `port` 从 `/dev/ttyAMA3` 改回 `/dev/ttyACM0` 重测，应观测到 loop <45 Hz / missed ticks / 读超时；若两者一样稳，说明 N2 的判据在本硬件上不成立，需要重新测预算而不是照抄结论。
- ✅ 为什么 LeKiwi 用 `/dev/ttyACM0` 没事：那是 6 颗机械臂、没有 15 颗 + IMU 的 sync_read 预算压力，也不是 50 Hz 硬实时步态环 —— **不能被当作「USB 也能跑整机」的证据**。

---

## 6. 系统 / 编译 / 运行时（✅ 源码）

| 项 | 结论 | 依据 |
|---|---|---|
| OS | **Raspberry Pi OS 64-bit (Bookworm/Trixie)**，`uname -m = aarch64` | 官方规格；ORT aarch64 wheel/tarball 前提 |
| Rust target | `aarch64-unknown-linux-gnu`，**不用改**；`cargo board` = `cargo zigbuild --release --target aarch64-unknown-linux-gnu.2.31` | `.cargo/config.toml`（其注释写的是 Radxa/Armbian，但目标三元组与 glibc floor 是通用的） |
| glibc | pin **2.31** 是**下限**，防「构建机 glibc 比板新、链接过了上板才炸」；Pi OS Bookworm glibc 2.36 / Bullseye 2.31 均 ≥2.31 ⇒ ✅ 兼容 | `.cargo/config.toml` 注释 |
| 板子识别 | `configd/src/identity.rs:35` 读通用 `/proc/device-tree/serial-number`（**不钉 SoC/厂商**，Pi 也提供）⇒ **无需改代码** | 源码注释明写「a generic binding that any board populating it satisfies」 |
| **ONNX Runtime** | `duck-control/Cargo.toml:27` 用 `ort =2.0.0-rc.11` + **`load-dynamic`**：构建期**不需要** target-arch ORT，运行时 **dlopen `libonnxruntime.so`**；`policy.rs:70-78` 支持 `ORT_DYLIB_PATH`，`:482` 有版本检查。`[workspace.metadata.onnxruntime]` **floor=1.23 / target=1.28.0**（注释：板子曾装 1.20.1 而 ort 在 <1.23 panic） | 源码 + workspace `Cargo.toml:30-33` |
| ORT 安装（Pi 4B） | 🟡 官方 release 有 `onnxruntime-linux-aarch64-1.28.0.tgz`（`lib/libonnxruntime.so*`），第三方安装 wiki 明写覆盖 *Raspberry Pi 4/5 (64-bit OS)*；或 64-bit Pi OS 上 `pip install onnxruntime` 后把 wheel 内的 `.so` 指给 `ORT_DYLIB_PATH`。**必须 ≥1.23，按 target 装 1.28.0** | birdnet-go ORT 安装 wiki（tarball 命名与命令）、outspoken.cloud（aarch64 pip 可用） |
| 🔴 **Rockchip 专属件** | `[workspace.metadata.gst-plugins]` 的 `mpph264enc`（**Rockchip MPP** 硬件 H.264）与 `rknpu`(`duck-detect`, v2.3.2) **Pi 4B 上不存在** ⇒ `mediad` 视频链路要么禁用、要么换 Pi 侧实现（v4l2h264enc 等）；`[detect]` 保持 `enabled=false`（本来就是默认 off，B23） | workspace `Cargo.toml:35-51`；`deploy_import_checklist.md` B23 |
| 实时性 | performance governor / 关无关服务 / 散热；microSD 比 eMMC 慢，日志别打同步写 | 🟡 通用实践 + §2.3 降频实测 |

> ⚠️ **未查**：Pi 4B 上 `ort load-dynamic` 加载 **ORT 1.28.0 aarch64** 是否与我们编译出的 robotd ABI 完全一致（版本元数据是查实的，**上板 dlopen 未验**）。这是 §11 自检 #6。

---

## 7. 部署 toml 改造（基线 `out/robotd_hd1910_mode0.toml`）

| 项 | 现状 | Pi 4B（改后） | 说明 |
|---|---|---|---|
| `[bus] port` | `/dev/ttyS2` | **`/dev/ttyAMA3`**（U2）或 `/dev/ttyAMA0`（U1） | ✅ Pi 上不存在 ttyS2；**别写 `/dev/serial0`**（会随 overlay 漂）。⚠️ 实际编号上板 `ls /dev/ttyAMA*` 确认 |
| `[bus] servo` | `feetech_hls` | 不变 | 保持 HLS 分支 |
| `[bus] joint_ids` | `[10,9,8,7,6,12,11,14,13,15,5,4,3,2,1]`（`:115`） | 不变 | ⚠️ 装机后仍要 `identify_joints.py` 逐颗复核（上游 `calibration_verified=false`）；别照抄官方 ID 体系 |
| `[bus] joint_signs` | 15 项（`:120`） | 不变 | `joint_offsets` 默认全 0；零位唯一杠杆是 signs/offsets（B22） |
| `[bus] position_kp` / `_head` | `16` / `16` | 不变 | 部署档 = kp8 等效；`[policy] gain=200`（XL330 口径）**别改成 8**（P6：reg50 会变 1 ⇒ 瘫软） |
| `[policy] lowpass` | `head/legs = 1.0` | 不变 | 训练零低通（P8） |
| `[bus] imu_median` | `false` | 不变 | 中值 = 纯 20 ms 延迟，超训练包络（B20） |
| `[battery] cells` / `max_volts` | `[2]` / `8.4` | 不变 | 🔴 3S 会烧舵机且不报错 |
| `[thermal] walk_max_c` | `70.0` | 不变 | ⚠️ Pi 4B 自身降频是另一回事，别混 |
| `[policy] walk/stand/ground_pick` | 仓库相对路径 | **板上绝对路径** | `policy.rs` 相对路径按 robotd 自己的 CWD 解析，dev 相对路径在机器人上不解析 |
| `[media]` / `[detect]` | — | **禁用 / 保持 off** | Rockchip 专属插件与 NPU 在 Pi 上不存在（§6） |

**策略文件**：`p8head_2999` 是**唯一走路级部署候选**（default + kp8 双 plant `terminated_frac=0`；`resume_5999` 归一化虽对但 83% 摔，已划出候选）。发布前确认 **ONNX 权重在图内**（P2：`manifest.py:237` `load_external_data=False` 会让 split/EXTERNAL 图以 3 KB 空权重过关）。

**EEPROM 上电硬校验**（`feetech.rs:386`，"checked, not corrected"）：`reg6=1`（500k，出厂 0 **必改**）、`reg33=0`（mode 0，出厂 4 **必改**）、`reg9/11=0/4095`（一般已 OK）；另 `reg19=13` 保护开关（B11）。写入时序不可改：**断电 → 解锁 55=0 等 0.25 s → 写等 0.50 s → 上锁 55=1 等 0.50 s → 再断电回读**；绝不切 mode；**回读 PASS ≠ 持久 PASS**。

---

## 8. IMU：必须按 robotd 代次绑定（引用 Pass48 的结论）

| 代次 | 绑定 | IMU | Pi 4B 要不要 I2C |
|---|---|---|---|
| **`DuckBuddy-main`**（本 toml 绑定：OrangePi/HL-2915/`feetech_hls`/500k/EEPROM reg6=1,reg33=0 硬校验；toml 注释 `:69-77/:105-111` 自述，**且不含任何 BNO08x 键**） | `out/robotd_hd1910_mode0.toml` | **总线 `imu_to_dxl v2`（LSM6DSV16X，ID 200）**，`SflpDecoder`；与舵机共用一条总线、同一个 `sync_read` | ❌ **不需要** —— IMU 随 Adapter (A) 一起挂在舵机总线上，这也是 §5 里「16 设备」的由来 |
| `hd1910m/microduck`（Radxa / FT-SCS / `row[33]==4`） | 上游原机 | **同时保留** `bno08x.rs`（BNO085 I2C SH-2）与同款总线板解码器 | ✅ 若改走这条：`/dev/i2c-1`（GPIO2/3）+ `gyro_fusion` 移植执行清单 |

- 🔴 **四板文档 §4 功能表那行「IMU I2C（BNO08x 系列） / Pi i2c-1 需开」是按另一代次写的**，对**本部署 toml 不适用**；已在四板文档加脚注。
- ✅ 装后自检：`live_viewer.py` 的 `imu_mount_sanity`（水平静止 gravity ≈ −Z，>20° 标 ⚠MOUNT?）；**上电姿态 = 参考姿态**（B21：SFLP 参考系是上电那一刻，开机必须正常站立且静止，`ready()` 需 25 样本 ≈0.5 s）。
- 🔴 若哪天改走 **BNO08x 路径**：`hd1910m/.../bno08x.rs:87-95` 对 `0x08` game-rotation **只归一化直接采信、无跳变门控**，`reference_native` 只是陀螺 EMA ⇒ 会原样吃进 fanhao 实测的走路 20–60° 乱跳。按 `microduck-HD1910-BNO085-gyro_fusion移植执行清单-2026-11-09.md` 先做 Phase 0 观测再决定是否移植。

---

## 9. 策略导出 → 部署链（复用现有文档，不重述）

链路：`export.py`（**必须走 checkpoint 路径**，normalizer 才烤进图）→ `uv run publish`（obs61/act14 门 + smoke）→ `sudo robotctl policy load walk <repo>`；50 Hz / obs 61 / act 14。

逐条引用 `microduck-HD1910-策略导出部署链-2026-11-09.md` 的 **P1–P13**，Pi 4B 上尤其容易踩的：
- **P2** EXTERNAL 权重上传 3 KB 空图；**P4** manifest `servos` 硬编码 `"xl330"` 但 daemon 不验（元数据错、运行对）；**P5** `rehearse_deploy.py` 写死 XL330/kp200 ⇒ **不能用于 HD1910**；**P6** `gain` 口径；**P9** `fast_sync_read` 不存在（写了整份配置加载失败）；**P10/P11/P12** EEPROM / reg19 / joint_ids。
- 板前门禁：`python tools/hd1910/pre_deploy_check.py --selftest` + 带 `--onnx <p8head_2999.onnx> --toml <改造后的 toml>` 实跑；`verify_policy_contract.py` 对质 obs 布局与关节序（B19，61 个 float 错一个偏移不报错、只表现为「看着在走然后摔倒」）。
- ⚠️ `pre_deploy_check.py` 必须用项目自带 `.venv-mjlab/Scripts/python.exe`（系统 Python 缺 numpy/onnxruntime/mjlab_microduck，见 2026-11-06 日志 G4）。

---

## 10. 上板自检清单（每条都带负对照）

> 原则：**绝不在台架 PC 上断言整机结果**。以下除 #1/#2/#3 外都必须在 Pi 4B 实板 + 15 颗舵机上跑。

| # | 检查 | 命令 / 期望 | 负对照（怎样算 FAIL 有效） |
|---|---|---|---|
| 1 | UART 是 **PL011 不是 mini-UART** | `readlink -f /dev/serial0`；`dtoverlay -h uart3`；`ls /dev/ttyAMA*` 出现 ttyAMA3；`raspi-gpio get 4,5` 为 TXD3/RXD3 | 改回默认配置（不加载 overlay）⇒ `/dev/serial0 → ttyS0`，且 core_freq 变化下 500k 位宽漂移 |
| 2 | **500000 精确** | `stty -F /dev/ttyAMA3 500000` 成功；示波器量位宽 **2 µs** | 写 1_000_000 ⇒ 舵机全沉默（reg6=1 只认 500k），与掉电不可区分 |
| 3 | 串口控制台已关 | `cat /boot/firmware/cmdline.txt` 无 `console=serial0`；空闲时总线无杂字节 | 留着 console ⇒ 内核日志灌进舵机总线、帧校验错 |
| 4 | **方向波形** | 抓 TXD + DE：DE 早于首起始位拉高、晚于末停止位拉低（§4.4） | 拔 DE / 跳线拨错 ⇒ 总线全沉默，但 UART 仍报「发送成功」 |
| 5 | 自动方向板透传 HLS 帧 | `servo_probe` 在 `/dev/ttyAMA3` ping 到 ID 1；逐级加到 15 颗 + IMU 200 | 把板子跳线拨到 B（USB）却仍用 ttyAMA3 ⇒ 全沉默 |
| 6 | **ORT 版本** | robotd 启动日志/ `policy::ensure_runtime` 通过；`ldconfig -p \| grep onnxruntime` 或 `ORT_DYLIB_PATH` 指向 1.28.0 | 装 <1.23 ⇒ ort panic、启动失败（不是「策略坏了」） |
| 7 | **50 Hz 无 missed** | `robotctl health --json` loop 50 Hz、0 missed；连续 10 min | 🔴 把 `port` 换成 `/dev/ttyACM0` 复测应掉到 <45 Hz / 出现读超时（§5 的 N2 负对照）；若一样稳 ⇒ 重测预算 |
| 8 | EEPROM 四项 + reg19 | `hd1910_ident.py` 回读 reg6=1 / reg33=0 / reg9=0 / reg11=4095；reg19=13 | 任一不符 ⇒ robotd 开机 `IoError::Bus`（checked, not corrected） |
| 9 | reg50 增益标度 | 起 robotd 后回读 reg50 = `round(200×16/200)` = **16** | 读到 1 ⇒ `gain` 被写成 8；读到 8 ⇒ `position_kp` 还是默认 8 |
| 10 | 电池识别 | ≥6.0 V 上电，`cells=[2]` 拦住 3S | 4.6 V 台架电压 ⇒ 「neither 2S nor 3S」瘫软 |
| 11 | IMU 读到 / 朝向 | `robotctl health` 有 IMU 数据；`imu_mount_sanity` 不报 ⚠MOUNT?；开机站姿静止 | 歪着开机 ⇒ 姿态全偏**且不报错**（B21） |
| 12 | 策略契约 | `pre_deploy_check.py --onnx … --toml …` 全绿；`verify_policy_contract.py` 全绿 | 故意改一个 obs 偏移 ⇒ 必须变红；只见过绿色的断言不是证据 |
| 13 | 散热 / 降频 | 跑 10 min 后 `vcgencmd measure_temp` + `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq` 不塌陷 | 关风扇跑到 82 °C ⇒ 降频、loop 抖动（🟡 第三方实测） |
| 14 | Rockchip 件已隔离 | `[detect] enabled=false`、media 未启用 MPP 插件 | 开着 detect ⇒ `rknpu` `.so` 找不到，症状像 NPU/模型问题 |

---

## 11. 已知风险与待查项（🔴 逐条标是否已查）

| 编号 | 项 | 状态 |
|---|---|---|
| R1 | 泰山派 `8250_dw.c` 补丁能否复用 | ✅ **不能**（驱动不同），§4.3 已查源码 + 官方资料 |
| R2 | `amba-pl011` RS485 在 **500 kbps 半双工 + 16 设备**下是否稳 | ⚠️ **未查到现成方案**：主线有支持、RPi 分支 2026-01 才修 panic，社区验证只到 460800；且 PL011 无 FIFO empty 中断 ⇒ 不走此路径 |
| R3 | CH343 CDC / `serialport::new(port, 500_000)` 能否产生可用的 500 kbps | 🟡 **已实跑，但仍不可判**：官方规格 50 bps–6 Mbps + `TNOW`（§4.2.1）；社区报 `400000` 等波特静默不发。2026-11-09 插上 URT-2 实跑（§12.1 第二轮）：CH343 在 1 Mbps 通道 20/20 应答、无自发自收回声；但**台架舵机 reg6=0 只认 1M** ⇒ 500k 零应答判 `INCONCLUSIVE_RATE_MISMATCH`，**不是** CH343 静默的证据。🔴 **用户 2026-11-09 拍板不切 reg6**（自指风险，§12.1）⇒ 消项留到示波器/逻辑分析仪或真上板；位宽 2 µs 仍需示波器 |
| R4 | Adapter (A) 的方向控制芯片型号 / 是否真为自动方向 | ⚠️ **未从原理图核实**：官方只写 "integrated control circuit"；社区（kevsrobots）说 handles half-duplex conversion。**接线前读官方 Sch.pdf** |
| R5 | Pi GPIO UART 3.3 V ↔ 舵机 5 V 电平 | ⚠️ **未查**：Adapter (A) UART 口电平官方未明示；自搭必须加转换 |
| R6 | USB 批延迟对 50 Hz 环的实际吃掉量 | ⚠️ **上板实测**（§10 #7 已设计负对照）；判决 N2 是基于预算的**推论 + 已知 USB 延迟量级**，不是 Pi 4B 实测。2026-11-09 新增社区证据：CH343 `drain()` 提前 40–130 ms 且 drain 后做 RS485 方向切换会截断尾字节（§5），但**仍非本项目实测**。2026-11-09 台架补到一个数：CH343 @**1 Mbps** 单 ping RTT p50 **0.2532 ms** / max 0.3574 ms（§12.1）；口径是 1M、单设备、ping，不是 500k/16 设备的 50 Hz 环，**不能**当 R6 的结论 |
| R7 | GPIO4/5 的 40-pin 物理脚号、`ctsrts` 具体 RTS 脚 | ⚠️ **未查**：GPIO 编号已查实，物理脚位查官方 pinout；**不照抄别板排针** |
| R8 | ORT 1.28.0 aarch64 与本 robotd 的 dlopen ABI | ⚠️ **版本元数据已查实，上板 dlopen 未验** |
| R9 | 机构 / 重心 / 价格 | ✅ 已知：85.6×56.5 mm / 75 g + Adapter 42×33 mm + 散热 ⇒ 机壳几乎全重做，重心重评（H12：HOME 是模型站姿不是编码器零位） |
| R10 | 完整 Microduck/HD-1910 复刻线无人用 Pi 4B | ✅ 已查：`fanhao375` / `chenkui164` / `AI-FanGe` 全用 Radxa Zero 3W 或 Pi Zero 2W ⇒ **没有整机镜像可抄** |
| R11 | 台架口径与部署口径不同 | ✅ **已查实、非风险但易写错**：所有台架实测都在 **1 Mbps**（URT-2 / CH343 / ID10 单舵机），部署是 **500 kbps / 16 设备**；`2026-11-06` 的 10.28–17.41 ms 是**比值外推**（§5 已订正措辞）。⇒ 不能把台架数写成「500k 实测」，也不能拿台架当 500k 的验证平台。**2026-11-09 实证**：reg6 实读 = 0，把这条从「口径提醒」升级成「实测混淆」——500k 零应答就是速率不匹配，见 §12.1 第二轮 |

**明确「这是推的」清单**：N3 的 6.0 整数分频（基于查实的 48 MHz 时钟做算术）、N2 的 USB 否决（基于本项目 1M 实测 + 比值外推的预算，叠加社区 USB 延迟/静默波特/drain 量级）、U2 选 uart3（基于 overlays README 引脚冲突表做的取舍）、供电树拓扑（基于官方「5 V via USB-C 或 GPIO header 均 ≥3 A」+ 项目 2S 约束的组合）。四者均未在本项目 Pi 4B 上实测；其中 N2 的两条新增证据是**社区实测而非本项目实测**，来源等级已标。

---

## 12. 执行顺序（先做零成本的，不买板）

1. ✅ **已完成（本轮）**：查清 UART/PL011/方向层/ORT/供电/IMU 代次/部署链的所有「下一步资料线索」，没有留「去找 X」当结论。
2. 🔴 **台架零成本先验：已实跑，500k 仍不可判，且已拍板不切 reg6**（2026-11-09 三轮记录见 §12.1，此路径冻结）：
   - `microduck-software/tools/hd1910/servo_probe/probe_ch343_baud.py`：在 `115200 / 250000 / 400000 / 500000 / 1M` 五个波特率下逐个打开 URT-2、发 HLS ping、统计应答率与 RTT 分布。用**舵机是否回帧**证明「芯片真发了」，不信 `Serial.baudrate` 回显；再用 ghost ID 排除自发自收回声。⚠️ `400000` 坏值锚点**只有在舵机也切到该速率时才有区分力**（reg6=0 时与 500k 同判 RATE_MISMATCH）。
   - `python probe_ch343_baud.py --port COM3 --id 10 --out out/ch343_baud.json` 已跑：1M PASS（RTT p50 0.2532 ms）、500k `INCONCLUSIVE_RATE_MISMATCH`。🔴 **消 R3 的下一步已冻结**：查完可逆性后用户拍板**不切 reg6**（§12.1 决策块），台架保持 1 Mbps，本条不再列为待办；将来若重新拍板，先按 §12.1 切 reg6=1 并断电重上电，再跑同一条命令，目标 500000 在 `rate_match=true` 下判 PASS 才算数（位宽 2 µs 仍需示波器）。当前 RTT 是 **@1 Mbps** 的数，别当 500k 的 USB 批延迟。⚠️ 切 reg6 有**自指风险**（若 500k 通道不通，现有 URT-2 就切不回来），完整可逆性判决见 §12.1。
   - 第三项「自动方向板能否原样透传 HLS 500k 帧」**台架做不了**（手上没有 Adapter (A)，需买板），保留在真机阶段。
3. 真决定换板后：买 Pi 4B + Adapter (A)，按 §3 配 `uart3`、按 §4 接方向层、按 §2.3 做供电树。
4. 交叉编译 robotd（§6）、装 ORT 1.28.0、拷策略 onnx 并改写绝对路径（§7）。
5. 逐颗写 EEPROM（§7 时序 + 断电回读），跑 §10 自检清单；**过了 #4 方向波形与 #7 50 Hz 才接整机舵机负载**。

### 12.1 台架先验结果（2026-11-09 两轮：先未插 → 后插上实跑）

#### 第一轮（URT-2 未插，如实 SKIP）

| 检查 | 读数 |
|---|---|
| `pyserial` 活动串口枚举 | `count = 0` |
| WMI `Win32_SerialPort` | 空 |
| PnP Ports 类 | `USB-Enhanced-SERIAL CH343 (COM3)`，`VID_1A86&PID_55D3`，但 **`Status = Unknown`**（未连接的残留条目） |
| 实际打开 `COM3/COM4/COM1` @500000 | 三者全 `SerialException: PermissionError(13, 拒绝访问)` |

⇒ 当时 URT-2 没插，`--port COM3` 如实 `rc=2` + `SKIP`。纯软件侧：`--selftest` 20/20 PASS、CLI 入口真跑、把 `classify()` 改成「只看回显就 PASS」自检掉到 **14/20**、`pyserial loop://` 回显 500000 只是**弱证据**（缓存值不是芯片时钟）。

#### 第二轮（插上 URT-2 + 舵机 4.6 V 供电，实跑）

**硬件确认**：`USB-Enhanced-SERIAL CH343 (COM3)`，`VID_1A86&PID_55D3`，**`Status = OK`**（不再是 Unknown）；`SerialPort.GetPortNames() = [COM3]`。`probe_ids.py --baud 1000000 --ids 1-20` → `found IDs: [10]`（pos=1750 / 153.8°，V=4.6，T=23 °C）；同扫描 @500000 → `found IDs: []`。

**🔴 关键判决：这轮验不了 500 kbps，不是探针没跑，是舵机根本不听 500k。**

| 项 | 实读 |
|---|---|
| `reg6` 回读（1M 下发 `ffff0a04020601e8`） | `ffff0a0300 00f2` → LEN=3, ERR=0, **DATA=0** ⇒ **reg6=0 = 1 Mbps**（出厂值，台架历史一直如此） |
| 半双工自发自收回声（ghost ID 253） | `tx fffffd0201ff` → `rx ""` ⇒ **`self_echo=false`**；1M 真响应 `ffff0a0200f3` ≠ 发送帧 `ffff0a0201f2` ⇒ 「收到 6 字节 == 舵机应答」判据干净 |
| 基线 | `baseline_baud=1_000_000`，`servo_configured_baud=1_000_000` |
| 1 Mbps | **PASS** 20/20，RTT p50 **0.2532 ms** / max 0.3574 ms（给 R6 一个本项目的数，**@1 Mbps**） |
| 115200 / 250000 / 400000 / **500000** | 全部 `replies=0/20`，`driver_echo` 各自正确，但一律 **`RATE_MISMATCH`（confounded=true）** |
| `target_verdict` | **`INCONCLUSIVE_RATE_MISMATCH`**；`baud_accuracy = needs_scope` |

**为什么必须订正**：原版把零应答一律写 `SILENT`（「芯片可能根本没发」）。在 reg6=0 的台架上，500k 零应答有**两种互斥解释**——① 舵机只认 1M、听不懂 500k 帧（已证实存在）；② CH343 在 500k 静默不发。软件层没有第三方观测者，**无法区分**，写成 ② 就是把「不可判」留成「CH343 不行」的假证据。同理 `400000` 这个已知坏值锚点在 reg6=0 时也失去区分力（与 500k 同判 RATE_MISMATCH），实机负对照改由 selftest 承担。

**代码订正（同一轮完成）**：`probe_ch343_baud.py` 新增阶段 0（在舵机能应答的波特率上读 reg6 + 用 ghost ID 测回声）、`annotate()` 把零应答拆成 `RATE_MISMATCH` / 真 `SILENT`、`target_verdict()` 只在 `rate_match=true && self_echo=false` 时才认 PASS；reg6 映射 import 自 `probe_bus_budget.BAUD_OF_REG6`（`is` 断言，单一权威）。`--selftest` **30/30**（新增 N6 速率混淆 / N7 回声作废 / N8 单一权威），pytest **5/5**，两条负对照都能删红：改坏 `classify` → 自检变红；删掉 `annotate` 的混淆判据 → 自检变红。

**⇒ R3 状态：仍未消**。官方规格与社区静默波特仍只是间接资料；台架现在证明的是「1M 通道通 + 判据干净」，**没有**证明 CH343 在 500k 真发帧。位宽 2 µs 依旧需要示波器。

#### 🔴 用户拍板（2026-11-09）：**不切 reg6**，本路径冻结

问过「切了能切回来吗」并查完可逆性后，用户明确决定 **不切**。⇒ 台架 ID10 保持 `reg6=0`（1 Mbps），**本轮零 EEPROM 写操作**；所有台架工具继续用默认 `--baud 1000000`，无需任何改动。R3 **保持未消**，且不再把「切 reg6」列为当前待办。

消 R3 改由**不依赖自指通道**的外部条件触发，满足其一再做：① 有示波器/逻辑分析仪，直接量 CH343 在 500000 下的 TX 位宽与是否真发帧；② 真上板（Pi 4B + PL011 或 Adapter (A)）后在真实 500k 通道上测；③ 另备一块已确认能在 500k 发帧的适配器，使回滚通道与被测通道解耦。**robotd 部署那边本来就要逐颗写 `reg6=1`**（§7），不靠这次台架实验，所以不切不影响部署准备。

下面两小节（消项步骤、可逆性判决）**仅作为查证存档保留，当前不执行**；若将来重新拍板要切，按此清单操作。

#### 消 R3 的唯一零成本路径（需一次人工断电）｜📦 存档，当前不执行

台架这颗 `reg6=0` 是**出厂值**，而 robotd 部署硬校验要求 `reg6=1`（500k，§7）⇒ 切成 1 是**朝部署方向对齐**，不是破坏台架：

1. `python hd1910_ident.py baud --port COM3 --baud 1000000 --id 10`（默认 `--baud-index 1`，走 `_eeprom_write` 已验证时序：解锁 55=0 等 0.25 s → 写等 0.50 s → 上锁 55=1 等 0.50 s）。
2. **人工拔掉舵机电源、等 2 s 再上电**（EEPROM 生效 + 避开 RAM shadow；`cmd_set_baud` 自己也这么要求）。
3. `python hd1910_ident.py telem --port COM3 --baud 500000 --id 10 --seconds 1` 确认新速率有应答、回读 reg6=1。
4. 重跑 `probe_ch343_baud.py --port COM3 --id 10 --out out/ch343_baud.json`：此时 `servo_configured_baud=500000`、`rate_match=true` ⇒ **500000 判 PASS 才真正消掉 R3 的可用性一半**；若仍零应答，那才是 CH343 静默的证据。
5. ⚠️ 切完后**所有台架工具默认 `--baud 1000000` 都要改成 `500000`**（`probe_ids.py` / `hd1910_readonly.py` / `probe_bus_budget.py` 等）；R11 里「台架历史数据都在 1 Mbps」依旧成立（指历史）。回滚用 `--baud-index 0`，同样需断电。

#### 可逆性判决（用户问「切了能切回来吗」，2026-11-09 查证）

**结论：参数层面能，操作层面有条件——而这个条件恰好就是 R3 要验的未知量。**

| 依据 | 内容 |
|---|---|
| 飞特官方内存表（`doc.feetech.cn` / AIFITLAB FT-SCS Wiki） | `reg6`(0x06) 波特率 = **读写**、取值 0–7、初始 0（1M）；`1=500000` 是标准档位（SCS15 手册该档误差 0.000%）⇒ **不是一次性熔断**，可反复写回 0 |
| 精确回滚（首选） | `hd1910_ident.py baud --port COM3 --baud 500000 --baud-index 0 --id 10` —— `--baud` 必须用**新**速率；同样要断电回读。只动 reg6 一个字节，不碰标定 |
| 协议级后路 | FT-SCS：`0x09` Parameter Backup（ID10 帧 `FF FF 0A 02 09 EA`）、`0x06` Parameter Restore（`FF FF 0A 02 06 ED`，**均需先解锁 reg55**）、`0x08` Reboot（`FF FF 0A 02 08 EB`，约 800 ms，重启前需关扭矩）。⚠️ `0x06` 的资料说法不一（juxi：除 ID 外回默认；Wiki：恢复 `0x09` 备份的快照），且会抹掉其它参数 ⇒ **别当首选**，精确写 reg6=0 更稳。本项目脚本目前未封装这三条指令 |
| 本地备份 | `eeprom_backup_id10.json`（2026-11-02，addr 0–55 全 dump，含 reg6=0 / reg33=4）；切之前建议重导一份最新的 |
| 网页工具 | `Juxi-Technology/FT-ServoController-web` 的 xdat 备份/回写覆盖 addr 0–48，可作第二适配器上的恢复手段 |

🔴 **别信「自动回滚」**：该工具 guide 写「验证失败会自动切回原速率并提示」，但 `js/app.js:836-846` 的 `changeBaud()` 只把**工具侧串口** `reopen(oldBaud)` 再 `ping(id)`，**没有任何把舵机 reg6 写回的动作**；`:844` 自己写着「严重：波特率修改失败且旧波特率也丢失」。⇒ 那是「试试旧速率还能不能连」，不是事务回滚。

🔴 **自指风险**：切过去以后能不能通信，就是 R3 要验的东西。实验成功（500k 能 ping）⇒ 随时可写回 0；实验失败（CH343 在 500k 静默）⇒ 舵机只在 500k 听、1M 不再听，而这块 URT-2 在 500k 又发不出帧 ⇒ **用现有硬件切不回来**，必须换一块能在 500k 真发帧的 USB-TTL / 飞特调试板，在那个通道上写回 reg6=0 或发 `0x06`。**舵机本身没坏**，只是暂时连不上。

⚠️ **资料矛盾，以本项目实测为准**：juxi `changeBaud()` 解锁→写 reg6→上锁只等 50/200 ms，随后立即 `reopen(baud)`，**不要求断电**；本项目 `hd1910_ident.py::_eeprom_write` 用 0.25/0.50/0.50 s 窗口且 `cmd_set_baud` 明写必须断电。后者是 2026-11-04 在这颗 ID10 上两次断电复现过的（短窗口会「回读 PASS、掉电回旧值」）⇒ 别照抄网页工具时序。这也意味着写入**可能**不立即生效、存在「断电前用 1M 写回 0」的撤销窗口，但应**按立即失联来准备**，不要赌这个窗口。

**保险动作（📦 存档，本轮不执行）**：① 重导一份 EEPROM 全 dump，可选在 1M 下发 `0x09` 把快照存进舵机内部；② 预先写好回滚命令，断电后第一件事就是 `probe_ids.py --baud 500000 --ids 10` 验通道，通了才继续；③ 不通就别反复断电折腾，直接换第二块适配器。**用户已选择不冒这个风险**（见上方决策块）：R3 留到有示波器/逻辑分析仪或上板时再验，台架现状不受影响。

**🔑 静态查证的新事实**（第一轮已回填 §4.2.1 / §5 / §11）：URT-2 = CH343P；WCH 官方 50 bps–6 Mbps + **`TNOW` 硬件半双工方向脚**；Linux 上 CH343 有 `cdc_acm` / `ch341` / WCH VCP 三条驱动路径；社区实测报 `400000` 静默不发、`drain()` 提前 40–130 ms 且 RS485 方向切换会截断尾字节。

**边界**：没有示波器 ⇒ 未测位宽精度；R6 的 0.2532 ms 是 **@1 Mbps** 的 RTT，不是 500k 的 USB 批延迟；没有 Adapter (A) ⇒ 自动方向板透传台架做不了；**reg6 保持 0（1 Mbps），用户 2026-11-09 已拍板不切，本轮零 EEPROM 写操作**。第一轮「未实跑」的结论到此作废，但保留在上方作为证据链。

---

## 13. 与现有文档的关系

- `microduck-泰山派部署-feetech_hls烤板步骤-2026-11-09.md`：**结构模板**；§1/§6/§7/§8 结论可复用，**§3/§4 设备树与内核补丁完全不可复用**（N1）。
- `microduck-Pi4B-开源Feetech总线舵机方案-2026-11-09.md`：开源现状 + 三路径分类；本方案**订正其 §4 落地建议**（详见 §5 与该文件订正段）。
- `microduck-SBC选型-四板对比-2026-11-09.md` §3.4 / §4 / §8：选型结论、功能表（IMU 行脚注已订正）、A1–A4 + C1–C8 可借鉴清单。
- `microduck-开源复刻项目-参考价值-2026-11-09.md`、`microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md`、`microduck-HD1910-BNO085-gyro_fusion移植执行清单-2026-11-09.md`：IMU 代次绑定与 BNO08x 路径风险（§8）。
- `microduck-HD1910-策略导出部署链-2026-11-09.md`：P1–P13（§9）。
- `microduck-software/tools/hd1910/deploy_import_checklist.md`：B10–B23 / H3–H13 实机关卡（EEPROM 时序、HOME、电池、joint_ids、IMU 上电姿态）。
- `microduck-software/tools/hd1910/servo_probe/probe_ch343_baud.py`：**本方案 §12.1 的台架探针**（2026-11-09 新增，同日按实跑结果订正）；`--selftest` **30/30** 全绿、pytest 5/5、两条负对照能删红。帧构造与 reg6 映射都 import 自同目录 `probe_bus_budget.py`（`is` 断言），不另造帧语义/波特率表。

### 证据清单（本轮实际查过的外部来源）

| 来源 | 支撑 |
|---|---|
| `raspberrypi.com/documentation/configuration/uart.md`、`.../configuration/os.html`（含 device-tree overlay 章） | primary/secondary UART、`/dev/{ttyS0,ttyAMA0,serial0}`、mini-UART 随 VPU 时钟漂移、`disable-bt`+`systemctl disable hciuart`、`miniuart-bt`、Pi 4 `uart2..uart5` |
| Raspberry Pi 官方论坛 "Pi-4 Activating additional UART ports" / `/boot/overlays/README` 转录 | UART2–5 的 GPIO 分配、`ctsrts` 参数、`/dev/ttyAMAn` 编号与旧 OS 差异 |
| 官方论坛 `clk_summary` 帖 + `docs.rs/rpi-hal/.../Uart.html` | PL011 参考时钟 48 MHz（实测 47 999 625）、IBRD/FBRD 分频公式 |
| `waveshare.com/wiki/Bus_Servo_Adapter_(A)` | ST/SC 支持、9~12.6 V 标注与 SC 低压兼容说明、跳线 A(UART, RX-RX/TX-TX)/B(USB, 官方列 Pi 4B)、Schematic 链接 |
| `waveshare.com/wiki/Bus_Servo_Driver_HAT_(A)` | 9~25 V、板载 5 V buck 给 Pi、ESP32 透传（**交叉接线 + 共地**）、`/dev/serial0` 示例、65×57 mm |
| LKML 2020-01-07 `amba-pl011` RS485 patch（Ivan Sistik）+ 2020-01-16 回复（Lukas Wunner）+ 2021-06-18 `[PATCH v2]`（Lino Sanfilippo） | PL011 无硬件 RS485、无 TX FIFO empty 中断、主线实现路径 |
| `raspberrypi.org/forums/viewtopic.php?p=2360006`（2026-01-20，6by9 / PR `raspberrypi/linux#7202`） | RPi 分支 `pl011_axi_probe` 漏 hrtimer 初始化 → panic；6.18.6-v8+ 修后 CM4 UART3@115200 / UART4@460800 验证 |
| **WCH 官方** `wch.cn/products/CH343.html` + 立创/LCSC C2846043 规格（2026-11-09 补） | 50 bps–6 Mbps、CDC 类免驱、`TNOW` 半双工方向脚、115200 以下自动识别 ⇒ §4.2.1 |
| `WCHSoftGroup/ch343ser_linux` README + `techeia.com` CH343 Linux 说明 | CDC-ACM / `ch341`(5.14+) / WCH VCP `ch343.ko` 三条驱动路径与节点命名 ⇒ §5 驱动分叉 |
| **`bun-serial` README**（社区实测，非官方；Radxa ZERO 3W / Linux `cdc_acm`） | CH343 在 400000/1152000/1843200 **驱动接受但静默不发**；`drain()` 提前 40–130 ms、其后 RS485 方向切换截断尾字节 ⇒ §5 两条新证据 / R3 / R6。⚠️ 第三方库实测，本项目未复验 |
| 飞特官方 `feetech.cn/530962` + `chenkui164/调试记录.md` + `fanhao375/tools/飞特/README.md` | URT-2 = CH343P（`VID_1A86:PID_55D3`），FD 软件默认 1 Mbps；台架历史实测口径 ⇒ §12.1 / R11 |
| Waveshare CH343 规格页 / `orca_core` Windows 文档 / FTDI latency 资料 | CH343 50 bps–6 Mbps、CDC `/dev/ttyACM0` 免驱、CH340/CP210x 无 latency_timer、FTDI 16 ms→62.5 Hz |
| Raspberry Pi 官方 4B 规格页 + product brief / `raspberrypi.dk` | 5 V ≥3 A（USB-C 或 GPIO header）、15 W 建议、75 g、aarch64 |
| ORT release tarball 命名 + birdnet-go 安装 wiki + outspoken.cloud | `onnxruntime-linux-aarch64-<ver>.tgz` 覆盖 Pi 4/5 64-bit、aarch64 pip 可用 |
| 本项目源码 / 实测日志 | `feetech.rs:301/35/386`、`duck-control/Cargo.toml:27`、workspace `Cargo.toml:30-51`、`.cargo/config.toml`、`identity.rs:35`、`policy.rs:70-78/482`、`toml:60-139`、`.workbuddy/memory/2026-11-06.md:245-250` |
