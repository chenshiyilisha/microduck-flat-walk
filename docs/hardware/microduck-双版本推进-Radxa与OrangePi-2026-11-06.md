# 双版本推进总览：Radxa Zero 3W vs Orange Pi Zero 3W

_2026-11-06。用户指令「两个版本都推进」。本文把两条主控路线的机械件适配、电气兼容、当前进度与下一步并排写清，作为 `microduck-飞特版3D打印件-OrangePi适配清单-2026-11-06.md` 的上层总览。_

## 0. 结论速览

- **两版都值得推进，不是二选一**：
  - **Radxa 版** = 与作者 CAD（fanhao375 飞特版）+ kissqy 镜像**完全对齐**，机械件零改动、舵机总线 1 Mbps 直接可行。
  - **Orange Pi 版** = 板子便宜/现成、板型与 Pi Zero 孔距一致（仅宽 2 mm），但 **40-pin 电气不兼容 RPi HAT**、**A733 总线限 500 kbps**，需自建主板载板。
- **机械件层面**：Radxa 版直接用 fanhao375 飞特版 v2.2（它实机就是 Radxa）；Orange Pi 版用本仓自建的 `cad/orangepi_zero3w_carrier.scad`。

## 1. 两版关键参数对比

| 维度 | Radxa Zero 3W（RK3566） | Orange Pi Zero 3W（A733） |
|---|---|---|
| 板型尺寸 | 65 × 30 mm（Pi Zero 板型） | 65 × 32 mm（孔距与 Pi Zero 一致，仅宽 2 mm） |
| 40-pin GPIO | 官方确认「compatible with most SBC accessories」（docs.radxa.com）；GPIO 3.3 V | 引脚定义 ≠ 树莓派（第三方评测确认孔距一致但电气定义不同） |
| 舵机总线波特率 | RK3566 UART 支持 1 Mbps（kissqy 实机跑 1 Mbps，上游主仓在 Zero 3W 上跑 1 Mbps） | A733 UART7 分频限制（`feetech.rs:34` 原话 *1 Mbit/s is not*）→ 只能 500 kbps |
| 机械件 | **零改动**：fanhao375 飞特版 CAD 实机即 Radxa（README 第 357 行） | 主板托架/HAT 支架/摄像头支架需自建（本仓 `cad/orangepi_zero3w_carrier.scad`） |
| HAT | 可直插 RPi 形态 kissqy HAT（40-pin 物理兼容）；舵机总线=J4 Pin8/10=RPi GPIO14/15=UART，插上即用 | 舵机总线物理也能用（Pin8/10 同为 UART），**但 IMU 的 I2C 在 Orange Pi Pin3/5 非 I2C ⇒ IMU 可能失效**，需飞线或换 I2C 引脚 |
| 现有软件镜像 | kissqy V167/ fanhao 镜像本就是 Radxa，开箱即用 | 需验证或自建；总线 500k 需改 `BAUD_RATE` 常量 |
| 主要风险 | ~~HAT 舵机总线 UART 需避开 Pin 8/10 调试串口~~ → **已闭环**：Pin8/10=UART2_M0，主仓正是把它当舵机总线跑 1 Mbps，HAT 的 DE 还由板内自动产生（不占 SBC GPIO） | HAT 出路（转接/绕开）+ IMU I2C 落点 + 连接耳螺接位待定 |

## 2. Orange Pi Zero 3W 版（A733）

### 2.1 机械件（自建中）

- 作者飞特版按 Radxa（Pi Zero 板型 65×30）建模；Orange Pi（65×32）**孔距一致、仅宽 2 mm** → 开顶卡框容得下 2 mm 边余量，躯干/腿/壳/头/电池 31 件直接通用。
- 真正要自建的是 **主板托架 / HAT 支架 / 摄像头支架** 三处（飞特版按 RPi 做）。本仓已建 `cad/orangepi_zero3w_carrier.scad`（参数化、开顶卡框 + 四角 M2 支柱 + **通用可调长圆孔连接耳**），并渲染 `cad/orangepi_zero3w_carrier_preview.png`（已修过坐标系 bug，2D 俯视图确认 4 红孔在板内、2 蓝耳对称）。
- 连接耳当前为「通用耳」：长圆孔沿 x 方向 ±4 mm 可调，装机时微调后用 M3 螺丝或扎带固定到飞特版躯干，**不依赖精确螺接位即可打样**。

### 2.2 电气兼容性（已查，硬约束）

- **40-pin 定义 ≠ 树莓派** → BOM 第 3 项「树莓派机器人 HAT」不能直插。
- **A733 UART7 分频限制** → 舵机总线只能 500 kbps（这是那块板的分频限制，不是舵机的；`feetech.rs:34` 原文针对 A733，与 Radxa 无关）。
- 三条出路（已在适配清单列）：**A** 主板改回 Radxa（零机械改动）/ **B** 重做 HAT 接口 / **C** 绕开 HAT 用 URT-2 + imu_to_dxl 小板（本仓阶段 2 默认）。推荐 **C** 若坚持 Orange Pi。

### 2.3 当前进度与下一步

- ✅ 载板 scad + 效果图完成（连接耳已升级为通用长圆孔耳）。
- ✅ **可打印 STL 已生成**：本机 Windows 沙箱无 OpenSCAD（files.openscad.org 的 Linux 包跑不了），改用纯 Python 网格构造器 `cad/build_carrier_stl.py` 直接写二进制 STL → `cad/orangepi_zero3w_carrier.stl`（896 面，bbox X[-44.5,44.5]×Y[-18,18]×Z[0,4.2]，与 scad 同参）。与 scad 的偏差（可接受简化）：底板实心不贯穿 M2 孔、连接耳长圆孔用矩形框实现、边轨用 4 盒近似。
- ✅ **418 MB STEP 不再必需**：连接耳长圆孔 ±4 mm 可调 + 框式结构不依赖精确螺接位即可打样；仅当要"精确拧到飞特版躯干原孔"时才拉 `SolidWorks-FT2026-10-20.zip` 定准。
- ⏳ 下一步：① 电气定 HAT 出路（推荐 C 绕开 HAT 用 URT-2 + imu_to_dxl 小板）；② 真机打样后用实物核 BOARD_R / 安装孔 / 接插件禁布。

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
- **想压价 / 用现成 Orange Pi**：走 **Orange Pi**（载板已建，但 HAT 需转接或绕开，总线限 500k）。
- 两条路共用：HD-1910 舵机（凸盘，飞特版 v2.2 已适配）、2S 电池、URT-2 调试板。

## 5. 待授权的大动作

- ~~拉 418 MB `SolidWorks-FT2026-10-20.zip` 定准连接耳螺接位~~ → **不再必需**：长圆孔 ±4 mm 可调 + 框式结构，不依赖精确螺接位即可打样。仅"精确对原孔"时才拉。
- ~~本机装 OpenSCAD 导 STL~~ → **已完成（替代方案）**：`cad/build_carrier_stl.py` 纯 Python 生成 `cad/orangepi_zero3w_carrier.stl`，无需 OpenSCAD。若要 OpenSCAD 忠实布尔（穿透 M2 孔、半圆端槽）可本地装后重渲。
- ~~查 kissqy 硬件工程确认 HAT 舵机总线 UART 引脚~~ → **已完成**：`microduck-kissqy HAT引脚分析-Radxa闭环-2026-11-06.md`。
- Radxa 上电验收清单 → **已完成**：`microduck-Radxa上电验收清单-2026-11-06.md`（commit `c61fa6f`）。
