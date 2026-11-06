# 未核实项核查报告（2026-11-06）

> 触发：用户「未核实的查查资料」。范围 = 两份全景文档 §8 的全部未决项 +
> `microduck-IMU三方对照` §5 待核对项 + `microduck-IMU板对照` §6 未决事项，共 14 条。
> 方法：按项目铁律，**先回一手资料**（本地 `.upstream/` 源码 / KiCad / 原理图 PDF /
> 官方 datasheet / GitHub contents API），查不到才标「未能核实」；涉及数值判据的一律带负对照。
> 本轮新用到的外部路径：Holtek 官方 HT75xx-1 datasheet、kissqy 仓库采购清单与固件源码、
> 666wsp 原理图 PDF（PDF 提取工具）、我方三份 ONNX（含病态负对照 `deploy61`）。

---

## 1. 结论总表

| # | 原未决项 | 新结论 | 证据强度 |
|---|---|---|---|
| 1 | `hd1910m` 两颗 +1 是否真实装法差异 | **否**，是未验证示例值；文件自标 `calibration_verified:false`，README 明写「仅供对照，部署用本机实际标定」 | 一手文件 + README |
| 2 | AI-FanGe「Shutdown 去输入电压错误项」对应 HLS 哪个寄存器 | **不是同一个寄存器**：教程是 DXL XL330 的 `Shutdown(63)`；飞特 HLS 对应 **reg19(0x13) 卸载条件 BIT0=电压保护**，配套 reg20 报警、reg65 状态、reg14/15 电压窗、`0x06 RECOVERY` | 厂商内存表（一手转抄） |
| 3 | esp-duck 门限能否直接搬到 FP32 ONNX | **不能，且照搬会误杀健康、放过病态**（定量见 §3）。已重标并落成脚本 | 我方 ONNX 实测 + 负对照 |
| 4 | community-kit Gerber 是否适配 2S 8.4V / A733 HAT 尺寸 | **电压适配但有硬边界**；「HAT 尺寸」这个担心**不适用**（三块板不插 40-pin） | KiCad 原理图/PCB 解析 |
| 5 | community-kit IMU 固件是否支持 500k | **支持**（`fee_baud_code=1`），但默认 1M 且 DXL 侧无 500k 档 | 固件源码（一手） |
| 6 | `dxl_hub` 拓扑（4 分支 vs 全并联）、铜箔载流 | **全并联**（网络只有 `GND/+BATT//DATA`）；banana_pcb 铜宽 3 mm、README 标 **3–5 A**（不是 30 A） | `.kicad_pcb` 解析 + README |
| 7 | 666wsp 与 community-kit 15 字节布局同源 | **契约同源**（community-kit 明写契约取自 kissqy FT6），offset/status 逐位对应；**不是同一份固件** | `board.h` / 手册对照 |
| 8 | ft1910「21-byte block at 56」vs 15 字节 | **不矛盾**：15 = 数据净荷，21 = 应答整帧长度（`LEN=17 → LEN+4=21`）。源码 `sync_read(56, 0x0F)` 为证 | Rust 源码 + 测试向量 |
| 9 | kissqy 香蕉母座焊盘 | **与官方资料冲突**：kissqy 采购清单明写「香蕉板（暂未上架）」；商品页仍登录墙 | 官方采购清单（一手） |
| 10 | 666wsp 板 BAT+ 电压范围 | **已定**：U2 = `HT7533-1`，Holtek 官方 `VIN max 30 V`、推荐 4.3–30 V ⇒ 2S 6.6–8.4 V 安全 | 原理图 PDF + 官方 datasheet |
| 11 | kissqy IMU 板引脚 vs DuckBuddy imu-feetech | **逐脚核对完成**：PA2/3/4/5/6/7 全同，**PA1 方向使能有效电平相反**；交叉刷固件必须改极性 | 两边固件源码 |
| 12 | mindthink / witcheer / RemiFabre 策略 sim-only | 维持原判（模型卡自标 sim-only），本轮未找到任何实机证据 | 模型卡（一手） |
| 13 | playground / mdlab / replica-kit 未逐份解析 | 抽查目录与 README，**无改判**；记录边界 | 目录抽查 |
| 14 | MHDuck / Ley-WL-observer 未下载全文 | 抽查 README/文档树：**MHDuck 是 HD1910+I²C IMU 已实施实机运行时**（H6 修法现成参考）；observer 自标「未部署实机」 | 官方 README + 设计文档 |

**14 条里 11 条完全闭合，2 条转为明确的边界说明，1 条（淘宝商品页）仍受登录墙阻挡但已被官方资料反证。**

---

## 2. 五处会改定案的硬发现

### 2.1 现成 Gerber 能吃 2S，但**吃不下我们的 30 A 设计**（#4 #6）

解析 `jyg9/microduck-community-kit/hardware/*/` 的 `.kicad_sch` / `.kicad_pcb`：

| 板 | 事实 | 对我方的影响 |
|---|---|---|
| `dxl_hub` | 元件表含 **`1000uF/10V 固态`**；网络只有 `GND` / `+BATT` / `/DATA` ⇒ **全并联**；铜宽 0.5/1.0/1.5/2.0 mm、28 个铺铜区；板框约 22×31 mm | **2S 8.4 V 可用但余量仅 1.6 V**；3S 12.6 V 会超电容耐压 ⇒ 这块板本质就是 2S 设计，恰好配 HD-1910+2S。上一轮「4 分支拓扑」是**推的，错了** |
| `banana_pcb` | 铜宽 **3.0 mm**（12 段）、8 过孔；README 原文「**正常运行电流 3-5A**」「引出导线不要太细」 | ⚠️ **不是我硬件清单里写的 30 A 母线**。replica 实机 10 A 电源能走，说明正常电流 <10 A，但站起/堵转峰值仍会压降。照搬现成 Gerber 时要认这个上限，站起掉电就另并粗线 |
| `imu_to_dxl` | README 明写 **供电 5~36 V**；板约 26×30 mm | 2S/3S 都覆盖，无电压顾虑 |
| 三块板 | 都是独立小板，通过 3P 线连接，**不插 40-pin** | 「是否适配 A733 HAT 物理尺寸」这个未决项**撤销**——问题本身不成立。要核对的是 1.8 mm 螺丝孔与结构件 |

> 交叉印证：kissqy 采购清单里 HUB 成品也写「板载 **1000 µF** 缓冲电容，防止瞬时压降导致 ZERO 重启」。两条独立来源给同一个值，说明这是社区共识而不是某家随手选的。

### 2.2 IMU 固件**支持 500k**，但有三个前提（#5）

`community-kit/firmware/v1/src/boot_regs.c:282-288`：

```c
uint32_t dev_fee_baud(void) {
    static const uint32_t tbl[12] = { 1000000U, 500000U, 250000U, 128000U, ... };
    uint8_t c = s_blob.cfg.fee_baud_code;
    return (c <= 11U) ? tbl[c] : BUS_BAUD_DEFAULT;
}
```

- `fee_baud_code = 1` ⇒ **500 kbps**；`dev.c:76-79` 接受 0..11；写飞特寄存器 **6** 会被 `dev.c:313 persist ... plain registers` 自动存进 flash blob（`dev_cfg_save_now()`），**掉电保持**。
- `docs/flash_layout.md:522` 原文：「若以后要缩短，可临时把总线降到 500 kbps（`dev_dxl_baud()` / `dev_fee_baud()` 都支持）」。
- ⚠️ **前提一**：默认 `dev_cfg.c:22` 是 `FEE_BAUD_CODE_1M (=0)`，出厂 1 Mbps。必须先用 1M 写寄存器 6=1，再让主机切 500k；**上电第一帧的握手顺序仍需台架验证**（`bus.c:254-257` 显示 served baud 跟随「主机最后一次说的协议」）。
- ⚠️ **前提二**：DXL 侧码表 `tbl[7] = {9600, 57600, 115200, 1M, 2M, 3M, 4M}` **没有 500k**。只有走飞特 `0x82` 协议时才能 500k —— 我方正是飞特总线，成立。
- ⚠️ **前提三**：把整条总线设成 500k 时，15 颗舵机的 reg6 也要一起改（`0=1M / 1=500k`），这与我们已定的 500k 方案一致。

⇒ 上一轮的判断「第四条路能否成立取决于 500k 可配性」**答案是可配**，这条路成立。

### 2.3 「刷成 DuckBuddy 固件就原生匹配」需要改一行：DE 极性（#11）

逐脚对照（左边 `DuckBuddy-main/firmware/imu-feetech/src/main.rs:9-14`，右边 kissqy `imu-source/src/main.c:140-152`）：

| 功能 | DuckBuddy imu-feetech | kissqy FT6 | 判定 |
|---|---|---|---|
| MCU | STM32G031F8P6 TSSOP-20 | STM32G031xx | ✅ 同族 |
| USART2 TX/RX | PA2 / PA3 | PA2 / PA3 (AF1) | ✅ |
| SPI1 | PA5 SCK / PA6 MISO / PA7 MOSI / PA4 CS | PA5/6/7 (AF0) / PA4 active-low CS | ✅ |
| **DE 方向使能** | **PA1 = 74LVC1G126 OE，USART2 硬件 DE，发送期间拉高** | **PA1 = `active-low DXL_TX_EN`，软件 GPIO** | ❌ **有效电平相反** |
| 其它 | 64 MHz PLL、500k | 16 MHz HSI、`DXL_BAUD=1000000`、PA0 DEBUG_LED | △ 各自固件管理 |

⇒ **引脚号几乎全同，但方向控制极性相反**。直接刷 DuckBuddy 固件上去，总线要么被一直驱动（抢占）、要么从不发声（不应答）——是「电气检查全过、症状是整条总线失联」的形状。修法：把固件里 DE 的有效电平反转一行（或按目标板收发器改硬件），再台架验一次。

### 2.4 21 字节 vs 15 字节：不是矛盾，是两个对象（#8）

`ft1910/duck-control/src/scs/wire.rs:588-594` 的测试向量逐字节给出：

```rust
sync_read(&ids, reg::PRESENT_POSITION_L /* 0x38 = 56 */, block::LEN as u8 /* 0x0F = 15 */)
```

`scs/mod.rs:31` 明写「one `sync_read` of sixteen devices at address 56 **and length 15**」。而飞特应答帧 `整帧长度 = LEN + 4`，`LEN = 数据 15 + 2 = 17` ⇒ **21 字节**。`wire.rs:468` 的 `self.buf[3] as usize + 4 != total` 就是这个公式。

⇒ first light 那句「the 21-byte block at 56 ... and the node's shared 15 bytes」里的 21 是**整帧**、15 是**净荷**，措辞含混但不是自相矛盾。上一轮「内部矛盾，先记录不判」可以撤销。

### 2.5 AI-FanGe 的 Shutdown 是 DXL 概念，飞特要写 reg19（#2）

`AI-FanGe/Microduck-build-tutorial/README.md:85-91` 原文推荐参数：「Protocol `2.0` / Baud `1Mbps` / **Shutdown: 去掉输入电压错误触发项**」——它整条教程是 **XL330 + Dynamixel Wizard + OpenRB-150**，Shutdown 是 DXL control table 的 addr 63。

飞特 HLS 内存表（`community-kit/docs/飞特通讯协议说明.md` §5/§6.1）里的对应物：

| 寄存器 | 名称 | 与欠压的关系 |
|---|---|---|
| **19 (0x13)** | **卸载条件** | **BIT0 = 电压保护（1=开启）** ← 这才是「去掉输入电压错误触发项」要改的位 |
| 20 (0x14) | LED 报警条件 | 同上位屏蔽，只管闪灯 |
| 14 / 15 | 最高 / 最低输入电压 | 0.1 V/LSB；最低出厂 **40 = 4.0 V** |
| 65 (0x41) | 舵机状态 | BIT0 电压 / BIT1 磁编码 / BIT2 温度 / BIT3 电流（1=异常） |
| `0x06` | RECOVERY | 从保护状态恢复 |

⚠️ **别照抄**：DXL 的「改一个 Shutdown 位」到飞特是「写 EEPROM reg19 的 BIT0」，而 reg55 写入锁开着时写进去只进 RAM、静默不持久化（我们已验证两次）。要按 H 段的 EEPROM 时序做，并回读 + 断电回读双验。

---

## 3. 定量实验：esp-duck 门限不能搬，且搬了会反向放行（#3）

`xingxingRealzyx/esp-duck/tools/validate_all.py` 的真实门限（README 头部注释与代码**不一致**，以代码为准）：

```
random  : cos >= 0.998, relL2 <= 8%      # 度量 INT8 权重 vs FP32 参考的偏差
standing: maxabs <= 2% of S              # S = mean ||a_fp|| over random set
```

我们 B 代 robotd 跑的就是同一份 FP32 ONNX，**没有量化孪生可比** ⇒ 照搬等于 gate 一个不存在的量。更糟的是「尺度感知」在这里会自我失效。用我方三份 ONNX 实测（`tools/hd1910/policy_numeric_gate.py`）：

| 策略 | S = mean‖a‖ | 2%·S | standing max‖a‖ | 照搬 esp 门限 |
|---|---:|---:|---:|---|
| `p8head_2999`（健康） | 2.914 | 0.0583 | 0.3018 | ❌ **FAIL**（超 5.2×） |
| `resume_5999`（健康） | 2.079 | 0.0416 | 0.2880 | ❌ **FAIL**（超 6.9×） |
| `deploy61`（病态） | **373.693** | 7.4739 | 0.4915 | ✅ **PASS** |

**病态策略的 S 被放大 128×，门限跟着一起放大，于是它把自己合法化了。** 这是「读数与算术上下界矛盾 ⇒ 错的是读数」的又一个实例：`S` 取自被测量本身，不能当门禁尺度（项目铁律）。

### 重标结果（已落成脚本）

`microduck-software/tools/hd1910/policy_numeric_gate.py`：保留 esp-duck 的**结构**（两套分布、开机必跑、尺度打印、负对照），换掉**被测量**——改为绝对物理量级与命令响应：

| 门 | 判据 | 阈值来源 |
|---|---|---|
| G1 站姿量级 | `max‖a‖ ≤ 3.0` | R2「关节偏移不是数字」 |
| G2 命令后量级 | 5 个真实命令下 `max‖a‖ ≤ 3.0` | 同上 |
| G3 命令响应 | `max‖Δa‖ ≤ 3.0` | §13.5 健康最大响应 0.244 rad，取 10× 余量 |
| G4 离群散布 | `std(a) over N(0,0.05) ≤ 5.0` | publish smoke run 健康带 0.29–0.83 |

`--selftest` 结果（**负对照必带**）：

```
ok  healthy_p8head_2999   PASS  S=2.914 std=0.774 stand=0.302 cmd_max=0.422
ok  healthy_resume_5999   PASS  S=2.079 std=0.553 stand=0.288 cmd_max=0.324
ok  broken_deploy61       FAIL  S=373.693 std=105.479 stand=0.491 cmd_max=519.876
                                G1 PASS（正是 R2/C8 的盲区）, G2/G3/G4 FAIL
SELFTEST OK
```

⇒ C9 从「未测、门限需重标」变成**已标、已跑、带负对照**。命令槽按 `verify_policy_bundle.plausible_obs()` 的布局写 51(head) / 57-59(body)，与 `docs/active/microduck-HD1910软件方案.md` §13.5 用的是同一批槽。

---

## 4. 其余各条证据路径（可复核）

| # | 一手证据位置 | 结论要点 |
|---|---|---|
| 1 | `hd1910m/radxa/installation.json` + `README.md:46-48` | `purpose: "Read-only wiring/mapping example"`，+1 的是 `neck_pitch(12)` / `head_pitch(11)`；README「按图对齐连杆和机身，再核对每个关节正方向」。⇒ 头部 +1 **不构成反证**，H2 仍以 replica 2026-09-20 实机逐颗核对为准 |
| 7 | `community-kit/firmware/v1/src/board.h:103-110, 549-556`；`666wsp.../imu_dev_guide.md:94-104` | `FEE_BLOCK_LEN=15 / CNT=12 / STATUS=13 / RESERVED=14`；status `0x01 NOT_READY / 0x02 STALE / 0x04 / 0x08 READER_SLOW` 两边逐位对应（bit2 命名 `ERR` vs `SELF_TEST`，主机 `(status & 0x07)==0` 行为等价）。board.h 明写契约来自 `Microduck-kissqy firmware/imu-source`，即 kissqy/666wsp 那条线 |
| 9 | `kissqy/Microduck-kissqy/DUCK-SHOPPING-LIST.md`「电池接入」段 | 原文「电池取电可使用**香蕉板（暂未上架）**，也可以使用仓库配套电池仓，加 M2.6 螺丝作为取电触点」。⇒ 用户提供的「kissqy 有香蕉母座焊盘」与官方清单冲突（也可能是文档未跟上新上架），**不撤销但降级为「下单前到店确认」**；主路径改回 community-kit `banana_pcb` 现成 Gerber（已核实、CERN-OHL-P） |
| 10 | `666wsp.../00_SCH/SCH_imu_todxl_v1.2_2026-10-24.pdf`（PDF 提取）+ Holtek `HT75xx-1v281.pdf` | U2=`HT7533-1`（Vin 2 / Vout 3，官方 `VIN max 30 V`、3.3 V±3%、100 mA）；U4=`CH32V203F8U6`；U3=`LSM6DSV16XTR` 走 SPI；CN2/CN3=`A2007WR-3P`；D2=`RCLAMP0521T` 在数据线上。⇒ BAT+ 推荐 **4.3–30 V**，2S 安全；⚠️ 原理图未标 10 µF 电容耐压，3S 前仍需实物核对 |
| 11 | `kissqy .../imu-source/src/main.c:140-152`、`DuckBuddy-main/firmware/imu-feetech/src/main.rs:9-14` | 见 §2.3 |
| 12 | `.upstream/hf-policies/*.README.md` | 三份卡都自标 sim-only；`standup v2` 是负结果（齿隙成本为零） |
| 13 | `playground/docs/*`、`mdlab/docs/*`、`replica-kit/docs/*` | 抽查目录：都是训练变体/路线图/成本估算，无与我方定案冲突的新事实 |
| 14 | `MHDuck/microduck` README + `docs/design/hd1910-i2c-imu-migration.md`；`Ley-WL/microduck-observer` README | MHDuck = HD1910 + **I²C BNO085** 的已实施实机运行时（Radxa Zero 3W 2GB/Armbian/50Hz），把 `ImuIo` 与 `RobotIo` 分离、保留 12 字节 `SflpDecoder` 契约 ⇒ **H6 若检出落脚乱跳，这是现成的「IMU 挪下总线」软件修法参考**，比 imu-displace（仅台架工具）完整。observer 自标「当前为本地实现，未部署实机」，不构成实机证据 |

---

## 5. 仍为边界 / 新增待核对

1. **淘宝商品页**（登录墙）：kissqy HAT+IMU+HUB 的具体款式与「香蕉母座焊盘」仍无法独立核实；官方清单说香蕉板暂未上架。下单前到店确认。
2. **community-kit 板上电首帧时序**：固件默认 1M、写 reg6=1 后转 500k，`bus.c:254-257` 的协议粘滞逻辑意味着首次握手顺序需台架验证。纸面不能定。
3. **banana_pcb 3–5 A 上限**：与整机 30 A 峰值设计的差距是真实存在的，站起/跌倒恢复时的压降需上板实测（replica 用 10 A 电源能走，说明常态电流没那么高）。
4. **10 µF 电容耐压**（666wsp 与 community-kit）：原理图/元件表未标，2S 8.4 V 大概率没问题但属于「推的」。
5. **🆕 kissqy HAT 与 A733 的引脚映射**：kissqy 采购清单明写主控是 **Radxa ZERO 3W 2GB 无 eMMC 带排针 ¥309**，HAT 尺寸 **65×30.9 mm**、AMP2.0 接口。A733 虽同 footprint，但 HAT 的 UART 走哪两个 pin 是按 Radxa 设计的；换 A733 后要么设备树把 UART7 映射到同 pin，要么飞线。**这条是换主控后新冒出来的硬件未决项**。
6. **🆕 价格勘误**：kissqy 官方清单是 **HAT ¥119 + IMU ¥99（已烧 FT6）+ HUB ¥69**，不是我们文档里写的「HAT+IMU 一套 ¥150」。三项合计 ¥287。
7. `mindthink` / `witcheer` / `RemiFabre` 全部策略仍 sim-only；`playground` / `mdlab` / `replica-kit` 未逐份解析（抽查无改判）。

---

## 6. 对我方定案的影响

**不变**：A733 4GB+eMMC / UART7(pin16/18)@500k / 2S PDB / HAT+IMU / obs61-act14-50Hz / plant 一等坐标 / 总线只需 500k。

**改**：
- 供电主路径从「kissqy 母座焊盘 + 嘉立创打样」改回 **community-kit 现成 Gerber**，并写入 3–5 A / 10 V 电容 / 全并联 / 不插 40-pin 四条边界。
- IMU 第四条路（community-kit 板）从「500k 未核实」升级为**可配、可用**，附三个前提。
- 「kissqy 板刷 DuckBuddy 固件 = 原生匹配」修正为**需改 DE 极性一行**。
- C9 从「未测」变成**已标已跑**（新脚本 + 负对照）。
- H6 检出乱跳时的修法第一顺位参考改为 **MHDuck 的 I²C ImuIo 分离实现**。
- 新增待核对：kissqy HAT 的 UART 引脚映射与 A733；价格勘误。
