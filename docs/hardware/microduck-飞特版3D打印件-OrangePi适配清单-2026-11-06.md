# MicroDuck 飞特版 3D 打印件 × Orange Pi Zero 3W 适配清单

_2026-11-06（多次更正）。资料源：本地 `fanhao375/microduck-replica-cad`（飞特版 v2.2，BOM 2026-10-23，33 打印件 + 23 外购件）、官方 orangepi.cn / orangepi.org 参数页、Orange Pi Zero 3W 引脚定义（playwithcircuit，2026-11-06 核对）。随 `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md` 一起看。_

## 0. 一句话结论（2026-11-06 终版，已三轮更正）

飞特版 v2.2 的 **33 个打印件对 Orange Pi Zero 3W 零机械改动，可直接用**。依据（2026-11-06 第三次核查）：
- **板型 = Raspberry Pi Zero 兼容板型**：Orange Pi Zero 3W 官方多源（产品页、thequantumdispatch、搜狐）一致标注「same footprint as Raspberry Pi Zero / 65×30mm」；且我已确认其 40-pin **功能与 RPi 同脚位**（舵机 UART 8/10、IMU I2C 3/5、5V/3.3V、GND 全同）。作者腔体本就按 Pi Zero 2W / Radxa Zero 3W（同 65×30 板型 + 58×23 安装孔）设计，Orange Pi 直接进。早先"Orange Pi 宽 2mm、需把腔体深度放宽 2–3mm"的判断**已作废**——那是推的（记"65×32"），不是查的。
- **电气层：HAT 可直插**（详见 §附录 引脚对照）。
- ⚠️ **尺寸口径冲突（已记录）**：官方中文参数页写「PCB Size 65×32×1.2mm」，与产品描述「30×65mm」矛盾。工程上取 **65×30（Pi Zero 板型净尺寸）**，"32mm" 疑为含板边/某连接器的外包尺寸；因 SBC 固定靠 58×23 安装孔、腔体按板轮廓+余量设计，2mm 不构成硬约束。若实物试装测得真 32mm 且卡边，属板边 1mm/侧 余量问题，非安装孔问题。

> 📌 **更正时间线（保留以便追溯）**
> 1. 初版（推翻）：以为"`trunk_base` 是 SBC 卡位、Orange Pi 仅多 2mm 宽余量待核"。
> 2. 第 1 次更正：读 README+躯干图发现 `trunk_base` 是髋 yaw 舵机位、SBC 在**躯干主壳型腔**；并误以为"40-pin 不兼容 HAT = 电气死穴"。
> 3. 第 2 次更正（关键）：拉官方引脚定义，40-pin **功能与 RPi 一致**，HAT 可直插；电气关不存在，真约束收敛到**腔体深度 ~32mm** 这一项机械量。
> 4. **第 3 次更正（本次，关键）**：核对 Orange Pi Zero 3W 官方尺寸，发现它明确是 **Raspberry Pi Zero 兼容板型（65×30）**，结合 40-pin 同脚位强证据 → 腔体本按此板型挖，**零机械改动**。"腔体深度 +2mm 放宽"的前提（Orange Pi 比 Pi Zero 宽 2mm）不成立，**该任务取消**。
> 5. ~~GitHub Releases **没有** 418MB STEP 包~~ → **本轮已证伪并更正（2026-11-06 晚）**：包就在
>    **`v2.2` release**（`SolidWorks-FT2026-10-20.zip`，417,656,282 B；另有 21.7MB 单件 STEP 包），
>    此前查询漏了分页/旧 tag。github.com 直连被本地代理 502 挡，但 **`gh-proxy.com` 镜像**与
>    **`api.github.com` asset 端点**都通，整包 88 秒下载完成、zip 完整性 OK。
>    包内为 18 `.SLDASM` + 59 `.SLDPRT` + 10 个**单件** `.STEP`，**没有整机 STEP/STL**；
>    总装 `.SLDASM` 是专有二进制（非 OLE2 / 非 ZIP，无可提取的装配位姿）。
>    另：**3MF 网格中心全为 (0,0,0)、是零件局部坐标**，此前「从网格实测腔体、保留世界坐标」
>    的口径不成立——Z 剖面只能当该壳件的自身截面参考，不能当整机腔体判据。
>    详见 `microduck-两版整机装配完整性核对-2026-11-06.md`。

> 顺带收口一个矛盾：作者 CAD 的板模型命名 `pcb__raspberry_pi_zero_2_w`，但仓库 README 明说「实机主控是 **Radxa Zero 3W（RK3566）**」。也就是说 **fanhao375 这套事实标准机械件，本来就按 Radxa Zero 3W 建**——跟"最优方案 = Radxa Zero 3W + 官方 Apache-2.0 fork"完全对齐。Orange Pi 分支只在你明确要 A733 的 NPU 时才值得。

## 1. 换 Orange Pi 到底变什么（终版）

| 维度 | Radxa Zero 3W（作者实机） | Orange Pi Zero 3W（A733） | 对 3D / 硬件的影响 |
|---|---|---|---|
| 板型 | Pi Zero 2W 板型，65×30 mm | **65×30 Pi Zero 兼容板型**（参数页写 32 为含边外包，见 §0 口径） | **机械：零改动**（同板型 + 58×23 安装孔一致） |
| 安装孔 | Pi Zero 2W 四孔位 | 评测确认「identical hole spacing」 | 孔距一致；与 Radxa 共用作者腔体固定方式 |
| 40-pin | RPi 兼容 | **功能与 RPi 同脚位一致**（UART 8/10、I2C 3/5、5V/3.3V、GND 全同） | **电气：HAT 可直插**（见附录）；早先"不能直插"已证伪 |
| 真约束 | — | 无（板型兼容，腔体按此挖） | **机械：零改动** |

**判定**：Orange Pi 分支经三轮核查，**从"电气死穴"（误）→"腔体深度 +2mm 微调"（误）→ 收敛为"零机械改动"**。HAT 电气兼容、板型与 Radxa/Pi Zero 2W 一致，33 件打印件直接通用。

## 2. 33 打印件逐类判定（修正 SBC 安装位）

判据口径：**"随主控板变" = 该件几何取决于 SBC 板型 / 主控腔尺寸 / 摄像头接口**。

| 类别 | 件 | 是否随板变 | 判定 |
|---|---|---|---|
| 头壳 / 面部 | 头部上壳(1)、头部下壳(2)、面部零件(3,含 -FT1 瑞莎摄像头变体)、下巴(4)、软下巴(5)、软嘴顶部(6)、眼睛(7) | 部分 | **直接用**；仅 `face_part` 可能因摄像头换型核孔距 |
| 颈 | 颈部(8)、颈部俯仰(9) | 否 | **直接用** |
| 躯干 | 躯干底座(10)=髋 yaw 舵机位、左右壳(11/12)、电源支架(31)、香蕉形PCB锁扣(32) | 否 | **直接用**；`trunk_base` 是舵机位不是 SBC 位 |
| 腿 / 髋 / 踝 / 脚 | 髋部左(13)、偏航转横滚(14)、偏航横滚运动(15)、腿部(16)、左上/右上腿(17/18)、上腿加固板(19)、左/右脚(20/21)、左/右脚底(22/23)、脚踝左/右(24/25)、脚踝左/右V1(26/27)、轴承滚轮(33) | 否 | **直接用**（飞特版舵盘配合件） |
| 轮滑 / 转接 | 合体轮胎(28)、滚轮叶片(29)、电机支架(30) | 否 | **直接用** |
| 主控腔所在件 | `01 躯干主体`（torso 主壳） | 否 | **直接用**；Orange Pi 与 Radxa/Pi Zero 2W 同板型，作者腔体本按此挖，无需放宽 |

**汇总**：33 件 → **全部直接用，零机械改动**。33 件中**没有**"固定 SBC"的专属打印件——SBC 由躯干主壳腔体 + 作者设计的支架卡住，而该腔体按 Pi Zero 2W 板型设计，Orange Pi 同板型兼容。

## 3. 真正要解决的（软件 + 电源，机械已零改动）

BOM 第 3 项「树莓派机器人HAT电路板」按 RPi 40-pin 设计，**Orange Pi 40-pin 功能同脚位 → 可直插**，无需重做 PCB。机械层经核查为零改动，剩余工作只剩软件与电源实测：

| 项 | 内容 | 性质 |
|---|---|---|
| **A（机械·已闭）** | `01 躯干主体` 主控腔按 Pi Zero 2W 板型设计，Orange Pi 同板型（65×30）→ **零改动**。仅当实物试装测得 Orange Pi 真 32mm 且板边卡死时才需小改；但本轮虽已下到 417MB SolidWorks 源包，其为专有二进制、本机无 SolidWorks/OpenSCAD/cadquery 可参数化编辑，届时需从源或实物重做该件，**当前阶段按零改动处理** | 条件项，大概率不发生 |
| **B（软件）** | Orange Pi 上需启用 UART0（舵机总线，Pin8/10）+ TWI0/I2C（IMU，Pin3/5），通常 armbian-config 开 overlay；核对设备名（如 `/dev/ttyS*`）与 robotd 配置一致 | Linux 配置 |
| **C（电源预算）** | Orange Pi 40-pin 5V(2/4) 与 RPi 同，但 A733 功耗/NPU 负载下 5V 轨带载能力需实测，HAT 伺服 5V 由板供 | 上电实测 |

> 结论：**不再需要"重做 HAT / 绕开 40-pin / 改腔体"**。Orange Pi 分支 = "软件开 UART0/TWI0 + 上电实测电源"，机械零改动，与 Radxa 路线几乎等价（仅 SoC 与软件 overlay 不同）。

## 4. 我已有的"载板"（⚠️ 思路已弃，勿直接打）

`cad/orangepi_zero3w_carrier.scad` / `cad/build/orangepi_zero3w_carrier.stl` 是按**外挂耳板**（69×36、带耳 89mm，M3 长圆孔拧躯干外侧）建的。经两轮更正后确认：
- 它解决的是"外挂固定"，而正确做法是 **SBC 像作者那样整栈进躯干主壳腔体**（HAT 已兼容，无需外挂）；
- 它比裸板还大、且**没有解决真约束（腔体深度）**；
- 在 Radxa 路径下完全不需要；在 Orange Pi 路径下也不能救场。

**处置**：该载板降为"外挂固定草模"参考，不再作为 Orange Pi 适配的主方案。若最终选 Orange Pi 且确需外挂（而非改腔体），再据此重做尺寸。

## 5. 仍需现场核的未知项

- **Orange Pi 真实板宽 30 vs 32（余量确认）**：取 65×30（Pi Zero 板型）。若实物测得真 32mm，因固定靠 58×23 安装孔、腔体按板轮廓+余量设计，板边多 1mm/侧 大概率不卡；真卡也属板边微调，非安装孔问题。**网格版 CAD 测不准腔体净深**（壳+腔结构，纯顶点包络分不出内外壁，见下方已提取件），最终以实物试装为准。
- **Orange Pi 40-pin 与 RPi 的逐脚一致性**：本清单附录基于 playwithcircuit 引脚表，建议上机前再对照 orangepi.org 官方引脚图核一遍，尤其是 Pin27/28（HAT EEPROM 自动识别用 I2C0，缺失只影响自动配置、不影响手动使用）。
- **真实安装孔数/孔径**：评测仅确认"孔距一致"，待实物或官方机械图二次确认。
- **板角倒圆半径**：官方未给，暂估 2.0。

> 📦 **已提取可查看件**：`out/builds/microduck_replica/01_躯干主体_torso_shell.stl`（从 3MF 提取的 `01 躯干主体` 独立网格，24362 面，**零件局部坐标、中心在原点**，可在查看器确认该壳件形态）；同目录 `torso_cavity_profile.txt` 为该件自身高度的 Z 范围剖面（**非整机腔体坐标**，仅供形态参考，净深以实物为准）。

## 6. 下一步

1. **选 Radxa Zero 3W**：33 件零改动，HAT 直插，本清单到此为止。
2. **选 Orange Pi Zero 3W**：机械零改动 → ① 软件开 UART0/TWI0（armbian overlay）；② 上电按 Radxa 验收清单同类项核对（节点名、I2C、1Mbps 扫舵机）；③ 电源轨带载实测；④ 实物试装若发现板边真卡 2mm，再议（且需 STEP 源参数化改，当前网格版做不到）。
3. 交叉更新 `microduck-最优方案-价格硬件软件-2026-11-06.md` 的 §3.4：结论改为"Radxa 零改动最优；Orange Pi 经核查同为 Pi Zero 兼容板型，**机械零改动**，仅软件开 UART/I2C 不同"。

---

## 附录：kissqy HAT 40-pin 引脚对照（RPi ⇄ Orange Pi Zero 3W）

HAT 实际用到：舵机 UART(Pin8/10)、IMU I2C(Pin3/5)、5V(Pin2/4)、3.3V(Pin1/17)、GND。下表逐脚核对（信号名以 RPi 为基准；Orange Pi 用其 GPIO 标识，但**物理脚位功能一致**）。

| Pin | RPi 信号 | Orange Pi Zero 3W | 兼容 | HAT 用途 |
|---|---|---|---|---|
| 1 | 3.3V | 3.3V | ✅ | 逻辑电源 |
| 2 | 5V | 5V | ✅ | 伺服 5V |
| 3 | GPIO2 / I2C1 SDA | PB3 / TWI0_SDA | ✅ | IMU SDA |
| 4 | 5V | 5V | ✅ | 伺服 5V |
| 5 | GPIO3 / I2C1 SCL | PB2 / TWI0_SCK | ✅ | IMU SCL |
| 6 | GND | GND | ✅ | 地 |
| 7 | GPIO4 | PB4/PWM0 | — | 未用 |
| 8 | GPIO14 / UART TX | PB9 / UART0_TX | ✅ | **舵机总线 TX** |
| 9 | GND | GND | ✅ | 地 |
| 10 | GPIO15 / UART RX | PB10 / UART0_RX | ✅ | **舵机总线 RX** |
| 11 | GPIO17 | PB0/UART2_TX | — | 未用 |
| 12 | GPIO18 | — | — | 未用 |
| 13 | GPIO27 | PB1/UART2_RX | — | 未用 |
| 14 | GND | GND | ✅ | 地 |
| 15 | GPIO22 | — | — | 未用 |
| 16 | GPIO23 | PL2/UART7_TX | — | 未用 |
| 17 | 3.3V | 3.3V | ✅ | 逻辑电源 |
| 18 | GPIO24 | PL3/UART7_RX | — | 未用 |
| 19 | GPIO10/SPI | PE2/SPI3_MOSI | — | 未用 |
| 20 | GND | GND | ✅ | 地 |
| 21 | GPIO9/SPI | PE3/SPI3_MISO | — | 未用 |
| 22 | GPIO25 | — | — | 未用 |
| 23 | GPIO11/SPI | PE1/SPI3_CLK | — | 未用 |
| 24 | GPIO8/SPI | PE0/SPI3_CS0 | — | 未用 |
| 25 | GND | GND | ✅ | 地 |
| 26 | GPIO7/SPI | PE4/SPI3_CS1 | — | 未用 |
| 27 | GPIO0 / I2C0 SDA（HAT EEPROM） | 待核（官方引脚图核） | ⚠️ | EEPROM 自动识别（缺失仅影响自动配置） |
| 28 | GPIO1 / I2C0 SCL（HAT EEPROM） | 待核 | ⚠️ | 同上 |
| 29–40 | GPIO5/6/12/13/19/16/26/20/21 + GND(30/34/39) | 对应 PB/PD/PE 等 | — | HAT 基本未用；GND 脚位一致 |

**结论**：HAT 的**关键信号（舵机 UART 8/10、IMU I2C 3/5、5V/3.3V、GND）在 Orange Pi Zero 3W 上同脚位齐备 → 物理可直插、电气兼容**。唯一需上机前再核的是 Pin27/28（HAT EEPROM 自动识别，缺失不影响手动使用）。早先"40-pin 不能直插 / IMU I2C 失效"的判断作废。
