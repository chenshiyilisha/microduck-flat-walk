# 双版本推进总览：Radxa Zero 3W vs Orange Pi Zero 3W

_2026-11-06。用户指令「两个版本都推进」。本文把两条主控路线的机械件适配、电气兼容、当前进度与下一步并排写清，作为 `microduck-飞特版3D打印件-OrangePi适配清单-2026-11-06.md` 的上层总览。_

## 0. 结论速览

- **两版都值得推进，不是二选一**：
  - **Radxa 版** = 与作者 CAD（fanhao375 飞特版）+ kissqy 镜像**完全对齐**，机械件零改动、舵机总线 1 Mbps 直接可行。
  - **Orange Pi 版** = 板子便宜/现成、与 Radxa/Pi Zero 2W **同板型（65×30，Pi Zero 兼容板型）**，HAT 40-pin **功能同脚位可直插**、IMU I2C 同脚位 → **机械件亦零改动**；唯一差异是 **A733 UART7 总线限 500 kbps**（软件配置层，非机械），以及需软件开 UART0/TWI0 overlay。
- **机械件层面**：两版都直接用 fanhao375 飞特版 v2.2（实机 Radxa，但腔体按 Pi Zero 2W 板型挖，Orange Pi 同板型兼容）；本仓 `cad/orangepi_zero3w_carrier.scad` 已降级为"外挂固定草模"参考，不再是 Orange Pi 必需件（详见适配清单 §4）。

## 1. 两版关键参数对比

| 维度 | Radxa Zero 3W（RK3566） | Orange Pi Zero 3W（A733） |
|---|---|---|
| 板型尺寸 | 65 × 30 mm（Pi Zero 板型） | **65 × 30 mm（Pi Zero 兼容板型；参数页"32mm"为含边/连接器外包，见适配清单 §0）** |
| 40-pin GPIO | 官方确认「compatible with most SBC accessories」（docs.radxa.com）；GPIO 3.3 V | **功能与 RPi 同脚位一致**（UART8/10、I2C3/5、5V/3.3V、GND 全同）→ HAT 可直插 |
| 舵机总线波特率 | RK3566 UART 支持 1 Mbps（kissqy 实机跑 1 Mbps，上游主仓在 Zero 3W 上跑 1 Mbps） | A733 UART7 分频限制（`feetech.rs:34` 原话 *1 Mbit/s is not*）→ 只能 500 kbps |
| 机械件 | **零改动**：fanhao375 飞特版 CAD 实机即 Radxa（README 第 357 行） | **零改动**：腔体按 Pi Zero 2W 板型挖，Orange Pi 同板型兼容（同 §0） |
| HAT | 可直插 RPi 形态 kissqy HAT（40-pin 物理兼容）；舵机总线=J4 Pin8/10=RPi GPIO14/15=UART，插上即用 | **可直插**：舵机总线 Pin8/10=UART0、IMU I2C Pin3/5=TWI0（与 RPi 同脚位），插上即用 |
| 现有软件镜像 | kissqy V167/ fanhao 镜像本就是 Radxa，开箱即用 | 需验证或自建；总线 500k 需改 `BAUD_RATE` 常量 |
| 主要风险 | ~~HAT 舵机总线 UART 需避开 Pin 8/10 调试串口~~ → **已闭环**：Pin8/10=UART2_M0，主仓正是把它当舵机总线跑 1 Mbps，HAT 的 DE 还由板内自动产生（不占 SBC GPIO） | **已闭环**：HAT 同脚位可直插、IMU I2C 同脚位；仅剩 A733 总线 500k 配置（软件）+ 软件开 UART0/TWI0 |

## 2. Orange Pi Zero 3W 版（A733）

### 2.1 机械件（已闭环：零改动）

- 作者飞特版按 Radxa（Pi Zero 板型 65×30）建模；Orange Pi **同为 Pi Zero 兼容板型（65×30，58×23 安装孔一致）** → 腔体本就按此板型挖，**33 件零改动直接通用**（躯干/腿/壳/头/电池全通用）。"Orange Pi 宽 2mm 需改腔体"经核查不成立（参数页"32mm"为含边外包）。
- 本仓 `cad/orangepi_zero3w_carrier.scad` + `cad/orangepi_zero3w_carrier.stl` 是按"外挂固定"思路建的，**已降级为草模参考**（HAT 已直插、SBC 应整栈进腔，外挂载板不再必需）。若最终确需外挂固定，再据此重做。
- 已提取 `01 躯干主体` 独立网格 `out/microduck_replica/01_躯干主体_torso_shell.stl`（可查看该壳件形态）。⚠️ **2026-11-06 晚更正**：3MF 网格中心全为 `(0,0,0)`、是**零件局部坐标**，不是世界/装配坐标；`torso_cavity_profile.txt` 只是该壳件自身高度的 Z 截面，**不能当整机腔体判据**，净深一律以实物为准。详见 `microduck-两版整机装配完整性核对-2026-11-06.md`。

### 2.2 电气兼容性（已查，已闭环）

- **40-pin 功能与 RPi 同脚位一致** → BOM 第 3 项「树莓派机器人 HAT」**可直插**（舵机 UART 8/10、IMU I2C 3/5、5V/3.3V、GND 全同）。早先"引脚定义≠树莓派、HAT 不能直插、IMU I2C 失效"的判断**已证伪**。
- **A733 UART7 分频限制（仍成立）** → 舵机总线只能 500 kbps（这是那块板的分频限制，不是舵机的；`feetech.rs:34` 原文针对 A733，与 Radxa 无关）；需保持 `BAUD_RATE=500k` 并将 15 颗舵机 reg6 从出厂 0 改为 1。
- **软件层唯一新增**：Orange Pi 上需启用 UART0（舵机总线，Pin8/10）+ TWI0/I2C（IMU，Pin3/5）overlay（armbian-config），核对设备名与 robotd 配置一致。

### 2.3 当前进度与下一步

- ✅ 载板 scad + 效果图完成（连接耳已升级为通用长圆孔耳）。
- ✅ **可打印 STL 已生成**：本机 Windows 沙箱无 OpenSCAD（files.openscad.org 的 Linux 包跑不了），改用纯 Python 网格构造器 `cad/build_carrier_stl.py` 直接写二进制 STL → `cad/orangepi_zero3w_carrier.stl`（896 面，bbox X[-44.5,44.5]×Y[-18,18]×Z[0,4.2]，与 scad 同参）。与 scad 的偏差（可接受简化）：底板实心不贯穿 M2 孔、连接耳长圆孔用矩形框实现、边轨用 4 盒近似。
- ✅ **418 MB STEP 不再必需**：连接耳长圆孔 ±4 mm 可调 + 框式结构不依赖精确螺接位即可打样；仅当要"精确拧到飞特版躯干原孔"时才拉 `SolidWorks-FT2026-10-20.zip` 定准。
  - 📦 **2026-11-06 晚更新**：该包确实在 `v2.2` release（此前误判"不在 Releases"已更正），并已通过 `gh-proxy.com` 镜像完整下载到本地（417,656,282 B，zip 完整性 OK）。但包内是 18 `.SLDASM` + 59 `.SLDPRT` + 10 个**单件** STEP，**无整机 STEP/STL**，总装 `.SLDASM` 为专有二进制，本机仍无法参数化编辑或还原整机位姿。
- ✅ Orange Pi 经核查**机械零改动 + HAT 可直插 + IMU I2C 同脚位**；唯一差异 A733 总线 500k（软件配置）。下一步：① 软件开 UART0/TWI0 overlay；② 上电按 Radxa 验收清单同类项核对（节点名、I2C、500k 扫舵机）；③ 实物试装核板宽 30/32（大概率不卡）。

## 3. Radxa Zero 3W 版（RK3566）

### 3.1 机械件（零改动，已闭环）

- 作者 fanhao375 飞特版 CAD **实机主控就是 Radxa Zero 3W**（README 第 357 行：Radxa Zero 3W，RK3566，Pi Zero 板型 65×30）。
- kissqy 镜像主控也是 Radxa（本仓裁决纪要 + HD1910 软件方案 §11.5 确认）。
- ⇒ 33 打印件 + 原 RPi 托架**直接用**，无需自建任何机械件。本仓 Orange Pi 载板在该路线下**作废**（仅作为 Orange Pi 分支的专用件保留）。

### 3.2 电气兼容性（已查，可行）

- 40-pin **官方确认兼容 RPi 配件**（docs.radxa.com 原话 *compatible with most SBC accessories on the market*），GPIO 电压 3.3 V（最高 3.63 V）。
- ⚠️ 但 **Pin 8 / 10 = UART2_M0**，是**调试串口 / 默认 U-Boot 控制台**（默认 1.5 Mbps），官方**不建议用作普通 UART**（会中断启动）。RK3566 其他 UART（如 Pin 16/18 = UART4_M1、Pin 32/33 = UART5_M1）可用。
- 总线 1 Mbps 可行：RK3566 datasheet 写 UART "up to 4 Mbps"，kissqy 实机在 Radxa 上跑 1 Mbps 舵机总线（ttyS2），上游主仓也在 Zero 3W 上跑 1 Mbps。
- ⇒ 15 颗舵机 EEPROM **一颗都不用写**（`feetech.rs:34` 的 500k 限制是 A733 的，非 Radxa）；`BAUD_RATE` 保持 1 Mbps，`BAUD_REGISTER_VALUE` 保持 0。

### 3.3 当前进度与下一步

- ✅ 机械零改动确认 + 40-pin 兼容确认 + 1 Mbps 可行确认 + EEPROM 免写确认 + **HAT 舵机总线 UART 引脚已核**（见下）。
- ✅ **HAT 舵机总线 UART 已闭环**：kissqy `elec_RPI_Robot_HAT` PCB 解析确认 —— 舵机 TTL 接 J4 Pin 8/10（RPi GPIO14/15 = UART），经 U7/U8 电平转换去 J3/J11（Dynamixel 输出）；**DE 方向(net45) 仅连 HAT 板内 Q1/U6/U7/U8，不连 J4** ⇒ SBC 无需提供 DE GPIO。Radxa Pin 8/10 = UART2_M0（官方 brief 确认）= `/dev/ttyS2`，与主仓 robotd 配置零差异，**插上即用**。详见 `microduck-kissqy HAT引脚分析-Radxa闭环-2026-11-06.md`。
- ⏳ 下一步：① 备料：Radxa ZERO 3W 2GB + kissqy HAT + fanhao375 飞特版打印件；② 上电后 `dmesg|grep tty` 确认节点、`i2cdetect -y 3` 确认 IMU 在 I2C3、`sts_bench.py` 扫 ID×1Mbps 复验（非阻塞）。

## 4. 决策建议

- **想最快跑通**：走 **Radxa**（零机械改动 + kissqy 镜像开箱 + 总线 1 Mbps）。
- **想压价 / 用现成 Orange Pi**：走 **Orange Pi**（与 Radxa 同 Pi Zero 板型、HAT 可直插、零机械改动；仅 A733 总线限 500k + 需软件开 UART0/TWI0）。
- 两条路共用：HD-1910 舵机（凸盘，飞特版 v2.2 已适配）、2S 电池、URT-2 调试板。
- **轮滑变体**（走路之外的第二形态，走路/轮滑二选一）：在任一版上把踝下换成「V1 备选踝 + 滚轮叶片 + 4 轮 + 4×6×12×3 轴承」，打印件增量仅 TPU 合体轮胎 ×4 + 叶片 ×2；软件换 `roller` 系策略（`action_scale 0.8`、`ROLLER_STAND_Z=0.138`）。**走路件与轮滑件不可混装**。详见 `microduck-两版轮滑变体组件与装配计划-2026-11-06.md`。

## 5. 待授权的大动作

- ~~拉 418 MB `SolidWorks-FT2026-10-20.zip` 定准连接耳螺接位~~ → **不再必需**：长圆孔 ±4 mm 可调 + 框式结构，不依赖精确螺接位即可打样。仅"精确对原孔"时才拉。
- ~~本机装 OpenSCAD 导 STL~~ → **已完成（替代方案）**：`cad/build_carrier_stl.py` 纯 Python 生成 `cad/orangepi_zero3w_carrier.stl`，无需 OpenSCAD。若要 OpenSCAD 忠实布尔（穿透 M2 孔、半圆端槽）可本地装后重渲。
- ~~查 kissqy 硬件工程确认 HAT 舵机总线 UART 引脚~~ → **已完成**：`microduck-kissqy HAT引脚分析-Radxa闭环-2026-11-06.md`。
- Radxa 上电验收清单 → **已完成**：`microduck-Radxa上电验收清单-2026-11-06.md`（commit `c61fa6f`）。
