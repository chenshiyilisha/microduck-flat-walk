# MicroDuck 最优方案：价格 → 硬件 → 软件（2026-11-06 综合定案）

> 触发：用户「综合参考，根据价格→硬件→软件 给一个最优方案」。
> 本文不是资料汇总，是**取舍判决**：每一段都写清「选了什么 / 否掉什么 / 为什么 / 下一段因此要付什么代价」。
> 价格检索日 2026-10-23 ~ 11-06，均为渠道价，**下单当天必须复核**；未闭合项一律标「待验」，不写成定案。
> 一手资料索引见 §6；逐条证据见 `docs/reference/microduck-未核实项核查报告-2026-11-06.md`。

---

## 0. 一句话判决

**当前阶段：一分钱不花，用台架 PC + 已有的 1 颗 HD-1910 + URT-2 把软件链跑通；
整机阶段走「15×HD-1910-C001 + 香橙派 Zero 3W(A733) 4GB+eMMC + 2S + community-kit 现成 Gerber + B 代 robotd」，
总额约 ¥2,574–2,653，比 XL330 路线省约 58%。**

决策链（三段是因果，不是并列）：

```
价格约束 ──► 硬件定案 ──► 软件代价
省 60% 舵机成本      选 HD-1910 + 2S     ⇒ 协议走飞特 0x82、B 代 schema、ID/HOME/零位三套坑
不买打样/电源        选现成 Gerber       ⇒ 载流只有 3-5 A，软件侧必须加上电姿态写入顺序
同价买更强主控       选 A733 而非 Radxa   ⇒ 放弃 kissqy R1 镜像，robotd 自己 cargo build
A733 UART7 上限      锁 500k             ⇒ IMU 固件必须 imu-feetech(500k)，不能锁 1M 的 FT6
```

### 0.1 选 / 不选对照

| 维度 | 选 | 否掉 | 理由 |
|---|---|---|---|
| 舵机 | HD-1910-C001 ×15（¥99/颗） | XL330-M288-T（¥259/颗） | 舵机占整机成本约 6 成；HD-1910 21 g 只重 17%，机身不用放大；BAM 已有一份 C001 实测辨识表（kt 0.692 / R 3.75 / armature 0.00224 / 延迟 25.3 ms） |
| 主控 | Orange Pi Zero 3W（A733）4GB + eMMC 8GB + 40-pin | Radxa Zero 3W；kissqy 指定的 2GB 无 eMMC 档 | 同价位八核 2×A76+6×A55 / 3 TOPS / LPDDR5；**DuckBuddy upstream 就是这块板并有 4GB+15 舵机 3S 整机日常运行的实机证据** |
| 总线速率 | 500 kbps | 1 Mbps | 50 Hz / 16 设备同步读：早期净荷估算 295 B → 4.7 ms ≈ 24%，源码整帧解析 413 B → 8.26 ms ≈ 41%，台架实测校正后 10.28–11.01 ms ≈ 51–55%（N=5，三套口径见 §4.3，不可混用）；A733 UART7 只有 500k 可精确表示，1M 实测约 750 kbps，B 代 robotd 写死 500k ⇒ 锁 500k 且 reg6 必改 |
| 供电板 | community-kit 三块现成 Gerber（CERN-OHL-P） | 自绘打样、kissqy HUB 成品 ¥69 | 三个 zip 直接发嘉立创；2S 适配已解析 `.kicad_pcb` 确认；省掉设计与打样那一轮 |
| IMU 固件 | DuckBuddy `imu-feetech`（500k，IMU 排最后） | kissqy FT6（锁 1M，IMU 排第一）、666wsp 板 | 与 B 代 robotd 原生匹配；666wsp 是 CH32V203 刷不了该固件，改动最重 |
| 软件栈 | B 代 robotd（`.upstream/DuckBuddy-main/`） | kissqy R1 镜像 / 自写飞特 daemon | 镜像是 Radxa 专属，A733 用不了；B 代 robotd 本身就是 A733 平台，且 TOML 审计 R1–R29 已完成 |
| 策略 | `p8head_2999` / `resume_5999` | `deploy61` | `deploy61` 归一化分母 10 个维 = 1.113e-05（差 1157 倍），5.7° 头命令会放大到 −35.7 rad，已下线 |

---

## 1. 价格轴（第一约束）

### 1.1 三笔账

| 阶段 | 现在要付 | 内容 | 不通过就停 |
|---|---|---|---|
| **阶段 0（此刻）** | **¥0–5** | 已有 1 颗舵机 + 调试板；**台架 PC + URT-2 本身就是 50 Hz 仪器**，只可能补一条 2.0→2.5 3P 转接线（¥3–5） | 到货 **48 h 内**跑完 G0 五道闸门（§4）：ping／事务 ≤5 ms／遥测合理值／50 Hz 长跑 0 错误且温度不越限／运行时 P=8 |
| 阶段 1（单腿） | **≈¥733** | 5 颗 ¥495 + NP-F550×2 ¥118 + 15 A 慢断保险座 ¥10 + PLA/热熔螺母 ¥120 | 5 颗同步读、零位重复性 <1°、吊架 ±10° 正弦 10 min 无丢包 |
| 阶段 2（整机） | **≈¥1,596** | 9 颗 ¥891 + 1 备 ¥99 + A733 4GB+eMMC ≈¥360 + HAT+IMU ¥218 + IMX219 ¥30 + VL53L8CX ¥66 + 电池/线材/结构件余项 | 一次 sync_read 读到 15 舵机 + IMU 200；母线 ≥6.6 V 不掉 |
| **整机合计** | **≈¥2,574–2,653** | 路线 B 原表 ≈¥2,419–2,498，主控从 Radxa ¥205 换 A733 ≈¥360 后 +¥155 | — |

> 数字口径：`docs/hardware/microduck-采购清单.md` §7.5 / §7.9.1；价格按 2026-10-23（舵机/电池）、11-05（A733）、11-06（HAT+IMU 勘误）三段拼接，**不是同日快照**。
> ⚠️ 「事务 ≤5 ms」是**单颗台架**闸门（URT-2 调试速率下）；整机 16 设备的总线预算是另一回事 —— 早期估算 500k 下约 10.9 ms / 20 ms（checklist §B13），**2026-11-06 台架实测校准（N=5）后为 10.28–11.01 ms / 51–55%，最坏档 16.68–17.41 ms / 83–87%（§4.3）**。两个量不能互相套。

### 1.2 参照系

| 方案 | 到手 | 判定 |
|---|---|---|
| 路线 A：XL330×15 + 官方 HAT 打样 | ≈¥6,100–6,300 | 贵 2.4 倍，且官方 HAT 的 D1 BOM 52 行/128 贴片位 |
| Pollen 官方整机 $399 | ≈¥2,850 + 转运后 ¥3,400–3,800 | **只发北美/欧洲/英国**，大陆需转运；有海外地址时这条反而更省且开箱能走 |
| `7757/fanduck` 1:1 复刻实账 | ¥11,923.60 | 官方 9 策略全通过，但是 XL330 路线 |
| 本方案 | ≈¥2,574–2,653 | 省的是钱，付的是调试时间；社区四条实机线**没有一条说「装完就能走」** |

### 1.3 省钱点（都是已核实的改判，不是估计）

- **阶段 0 不买直流稳压电源**（¥66–145）：2026-11-03 二次改判，kt/R 用现成实测辨识、电流系数是官方寄存器单位、动态量已无消费判据；带载保护用 2S 电池即可做。
- **阶段 0 不买主控**：`microduck-板子设计备忘.md` §5.4「要省钱，先别买板」。⚠️ 该条当时第三个理由「换板没有先例」**已被 DuckBuddy 的 A733 实机证据闭合**，但第一个理由（台架 PC 已够 50 Hz）仍成立。
- **不打样**：`banana_pcb` / `dxl_hub` / `imu_to_dxl` 现成 Gerber，省一整轮设计与试错。
- **不单买 HUB 成品 ¥69**：配电功能由 `dxl_hub` 承担。
- **不买 666wsp 板**：CH32V203 刷不了 `imu-feetech`，买了要改 robotd 排队顺序，软件代价最大。
- **可砍相机 + ToF −¥96**：走路阶段不需要；但 ToF 量程约 1 m 只够避障，若计划做自动跟随，相机不能砍。
- **不要一次买齐 15 颗**：阶段 0 不过，后面全白买。

### 1.4 不能省的两笔

- **15 颗舵机 ¥1,485**（约整机 58%）：没有更便宜且 21 g 级的替代。
- **1 颗备件 ¥99**：超压运行 + 金属齿，社区烧舵机是常态。

---

## 2. 硬件轴（由价格推出的定案）

### 2.1 BOM 定案

| 模块 | 型号 / 规格 | 数 | 关键约束 |
|---|---|---|---|
| 主控 | Orange Pi Zero 3W（A733）**4 GB LPDDR5 + eMMC 8 GB + 40-pin** | 1 | eMMC 官方**默认空贴**，要选带 eMMC 的 SKU；别买 1 GB（LPDDR4 降档 + 无板载存储）；别与 Radxa Zero 3W / Zero 3E 混淆 |
| 舵机 | Feetech **HD-1910-C001**（4–8.4 V，AMP2.0-3P，15 cm 自带线） | 15 + 1 备 | ID 用 **B 代体系**：左腿 20–24 / 头颈 30–34 / 右腿 10–14 / IMU 200；**禁止照抄复刻线 1–15** |
| HAT + IMU | kissqy 淘宝成品（HAT ¥119 + IMU ¥99）或 DuckBuddy 参考设计 | 1 | HAT 必须（半双工收发 + 5 V 降压）；IMU ID 200 必须；**详见 §2.4 的固件判决** |
| 供电板 | community-kit `banana_pcb` + `dxl_hub` + `imu_to_dxl` 现成 Gerber | 3 | `dxl_hub` 焊 **AMP175778/8283/A2007WV-3P 立式**（不是 XL330 的 B3B-EH-A） |
| 电池 | **NP-F550** 2S 2600 mAh（不是 F970） | 2 | 一块飞一块充；放电能力必须 ≥3C / ≥8 A；满电 8.4 V 顶格无余量 ⇒ 建议供电调到 **8.0 V** 或输入并 1000–2200 µF |
| 配电 | XT60 + 15 A（单腿）/ 30–40 A（整机）慢断 + 16–18 AWG 短线 | — | 主电**必须并联**，AMP2.0 菊花链触点约 3 A 不能当供电 |
| 调试 | FE-URT2（TTL，非 U2D2）+ 2.0→2.5 3P 转接线 | 1 | 三档开关拨 **5V**；先插 USB 后给舵机上电 |
| 外设 | IMX219 / VL53L8CX / 8Ω 1W 喇叭 | 各 1 | 走路阶段可砍 |

### 2.2 三个物理层硬约束

1. **UART7 = 40-pin pin16 TX / pin18 RX = `/dev/ttyS7`**，与 DuckBuddy HAT 的 J1 信号表原生对齐；`[bus] baud` 固定 500k。A733 与 Pi Zero 同 footprint（65×32 mm），HAT 可叠插。
2. **2S 而非 3S**：`dxl_hub` 板载 `1000µF/10V` 固态（8.4 V 余量仅 1.6 V，3S 12.6 V 必超压）；`[battery] cells = [2]` + `max_volts = 8.4`。DuckBuddy PDB 也分 2S / 3S 版，HD-1910 必须认 **2S 版**。
3. **载流边界**：`banana_pcb` 铜宽 3 mm、README 标 **3–5 A**，不是 30 A 母线；`dxl_hub` 经解析是**全并联**（网络只有 GND/+BATT/DATA）。整机站起/跌倒恢复的峰值压降**待上板实测**，掉电就另并粗线。三块板都不插 40-pin，所以「HAT 尺寸适配」这个问题不成立。

### 2.3 焊与不焊的真实边界

三块 Gerber 省的是**设计与打样**，不是焊接动作：`dxl_hub` 的 AMP2.0 立式座、香蕉母座仍要自己烙铁焊。
想彻底免焊：电池入口改 **XT60 线直出 + 接线柱**，香蕉 PCB 整块跳过（对应 `microduck-硬件清单-详细接线版.md` §5.1 的备用路线）。

### 2.4 IMU 选型判决（上一轮「三方对照」的收口）

| 组合 | 判定 |
|---|---|
| **DuckBuddy `imu-feetech`（STM32G031，500k，IMU 排最后）+ B 代 robotd** | **最优，零改动**。`feetech.rs` 实测 IMU 排最后 1000/1000 干净、排第一 990/1000 |
| kissqy 成品板刷 `imu-feetech` | **可行但必须改一行**：两边 PA2–PA7 全同，**PA1 方向使能有效电平相反**（DuckBuddy 高有效 OE vs kissqy active-low `DXL_TX_EN`）。不反转会「电气全过、整条总线失联」 |
| kissqy 原装 FT6（1 Mbps 固定） | **不用**。A733 UART7 喂不起真 1M；15 颗舵机要跟着重配到 1M |
| 666wsp IMU_TO_DXL（CH32V203） | **不买**。刷不了 `imu-feetech`，且要求 IMU 排第一，必须改 robotd 与 FD.exe 调波特率 |

> 三条协议事实已闭合：飞特 `0x82` SYNC_READ / addr56 / **净荷 15 B** / 缺席也占约 295 µs 槽；DXL `0x8A` / addr124 / 12 B；所谓「21 byte」是应答整帧（`LEN=17 → LEN+4=21`），与 15 B 净荷不矛盾。

### 2.5 上电与装配顺序（真机重启级，不可省）

- **H1**：先插 USB、后给舵机上电；反了总线被压到约 2.1 V，一颗都不应答。
- **H8**：`set_torque(true)` 之前必须 **先写机器人当前姿态到 goal → 回读验证 → 再上扭矩**，且封装在一次调用内；否则 15 颗 × 最多 26° 误差的 inrush 会触发欠压锁定（community-kit 实机记录 8 分钟内 4 次 SBC 重启）。`reg40` 必须逐台带 ACK 的 WRITE，`sync_write` 会造成「假释放成功」。
- 装配三段：单颗台架 → 单腿吊架 → 整机；每段的 Go 判据见 §4。

### 2.6 备选主控评估：Radxa Cubie A7Z（2026-11-06 判决：**不换**）

**一句话：同 SoC、同 footprint，但 40-pin 复用表不同 ⇒ 不是平替，是换平台。** 它是目前找到的
「最近亲」，但当前方案要的是**能直插现成 HAT**，这一条它不满足。

| 项 | Orange Pi Zero 3W（方案定案） | Radxa Cubie A7Z | 判决 |
|---|---|---|---|
| SoC | Allwinner A733 | **Allwinner A733** | ✅ 完全同一颗：2×A76+6×A55、3 TOPS、同一 UART 时钟域 ⇒ 500k 可精确分频、1M 同样到不了 |
| 尺寸 | 65 × 32 × 1.2 mm | 65 × 30 mm | ✅ Pi Zero footprint，物理塞得进头部 |
| 40-pin pin16 / 18 | **PL2 / PL3 = UART7 TX/RX = `/dev/ttyS7`** | **PJ24 / PJ25 = UART4 TX/RX**；官方 40-pin 复用表只列 UART0–4，**没有 UART7** | 🔴 舵机总线落在另一个 UART 控制器上 |
| pin7 / pin19 / 23 | PB4（I2S0 MCLK）/ PE2·PE1（TWI2 SDA·SCL） | PB0（UART2 TX）/ PD12·PD11（SPI1·PWM）；TWI2 挪到 pin27/28，PB4 挪到 pin36 | 🔴 HAT 的 audio codec、ToF、功放全部接错脚 |
| 内存 | LPDDR5（1 GB 档才 LPDDR4/4X） | LPDDR4/4X | ⚠️ 对 50 Hz 小 ONNX 影响不大，但最坏档只剩 2.59–3.32 ms 给推理，非零风险 |
| 板载存储 | **eMMC** 8/16/32 GB + UFS 可选 + TF | **无 eMMC**，只有 UFS 可选 + TF | ⚠️ 方案定的是 eMMC 8 GB；microSD 长期 50 Hz 写入可靠性弱于 eMMC |
| 供电 | Type-C 5 V / 3 A | Type-C 5 V / **1 A**，或 GPIO pin2/4 5 V；第三方实测满载 6.2 W > 5 W | ⚠️ HAT 的 LMR51450 需按 ≥1.5 A 复核 |
| 软件 / 实机证据 | Debian + `orangepiEnv.txt` / `sun60iw2` / `ttyS7`；DuckBuddy README 明写 **4 GB + 15×HL-2915 + 3S ✅ 整机日常运行**，HD-1910+2S 版 🚧 在焊 | Debian/Buildroot/Tina/Android 13，Radxa BSP；**未找到任何 microduck / robotd 用例** | 🔴 全套 TOML 审计 R1–R29、设备树说明、checklist 都绑在 Orange Pi 上，换板等于重新验证一遍 |

资料：Radxa 官方产品页与 Product Brief v1.1 §5.1.1（40-pin 复用表，官方原理图 v1.11 sheet 14
`PCIE_40PIN_CONNECT`）、Orange Pi Zero 3W 官方规格与公开 pinout；本仓
`.upstream/DuckBuddy-main/docs/hardware/INTERFACE-CN.md` §2.1（HAT J1 逐针表）、
`deploy/robotd.toml:19`（`port = "/dev/ttyS7"`）、`deploy/audio/README-A733-CN.md:16`。
🔑 这条判决靠的是**两个一手来源互相矛盾**：上游源码说 pin16/18 是 UART7，Radxa 官方表说同一对
物理针是 UART4 —— 同 SoC 不等于同引脚复用。

分场景结论：

- **用现成 HAT（当前方案）⇒ ❌ 不合适。** 改一个 `port` 救不了，I²C/I2S/codec 复位也全错位，
  等于要重画 HAT 或飞线，还丢掉唯一有整机实机证据的平台。
- **自绘最小载板**（只要半双工收发 + 5 V 降压，砍掉音频 / ToF / 摄像头）⇒ ✅ 技术上可行，
  且属用户已接受的「软件可自己改」：总线迁到 UART4，改 `port = "/dev/ttyS4"` + 使能对应
  overlay。**但这是换平台**，须先验三件事：① UART4 是否同样能精确输出 500 kbps（同 24 MHz/16
  时钟源，推断可行，**未实测**）；② Radxa Debian 的 UART overlay 与 50 Hz 实时性；
  ③ ONNX 在这块板上的推理耗时能否塞进 2.59–3.32 ms。
- **当第二供应商 / 更便宜平替** ⇒ 现在没有理由启动。价格口径**未核实**：官方 Allnet China
  1 GB 版 $34.99（2026-11-03，缺货），宣传起价 $15 是 1 GB 且**不带 GPIO 排针**；
  淘宝聚合页 ¥888–1291 很可能是 16 GB+UFS 高配或套装，不是 4 GB 档，登录墙无法确认。
  方案里 Orange Pi 4 GB+eMMC ≈ ¥360。⇒ **不能断言它更贵**，但也不能据此改判。

> 结论：保持 Orange Pi Zero 3W。Cubie A7Z 记为「同 SoC 备选」，仅在 Orange Pi 供货/价格出问题时
> 重启评估，重启时先问淘宝「4 GB + 已焊 40-pin 排针 + 无 UFS」的单价，再按上面三条闸门验收。
> **不重训**（§3.6）：换主控载板不进 MDP / obs / plant；但若 UART4 拿不到 500k 而改总线速率，
> 就触及 domain 改动，须重新判。

---

## 3. 软件轴（由硬件推出的代价，用户已明确「软件可自己改」）

### 3.1 骨架判决

**用 B 代 robotd（`.upstream/DuckBuddy-main/`），自己 `cargo build`，不用 kissqy R1 镜像。**
理由链：选了 A733（§1）⇒ kissqy 的 `microduck-zero3w-0.15.1-R1.img.xz` 是 **Radxa Zero 3W 专属镜像**，control.43 / R17 V167 中控也在那条线上，A733 不能直接刷；而 DuckBuddy upstream 本身就是 A733 平台，`robotd` 有现成的 aarch64 支持与 `feetech_hls` 后端。
代价：设备树 / overlay、`hw_rev`、HAT 专属服务（`tofd`/`padd`）需自己处理 —— 这正是「软件可自己开发」所接受的那部分，也是换主控唯一真正的成本。

### 3.2 配置最小集（每个键都先回 Rust 源码 grep）

- `[bus] servo = "feetech_hls"`；**没有 `protocol` 键、没有 `fast_sync_read` 键**。`Bus` 带 `#[serde(deny_unknown_fields)]`，写一个不存在的键 = **整份配置加载失败**。A 代（Radxa+XL330，有 `[board]`）与 B 代（OPi+HL-2915，有 `servo`/`joint_ids`/`[battery]`）schema 不能混。
- `[bus] joint_ids` 15 条，顺序固定按 `JOINT_NAMES`（0–4 左腿 / 5–9 颈头 / 10–14 右腿），按**关节名字**映射，不能拿模型数组下标当 ID；空或重复 ⇒ 总线拒绝打开。
- `[battery] cells = [2]` + `max_volts = 8.4`（默认是 `[2,3]`，3S 会被判合法并照常驱动 ⇒ 烧舵机且**不报错**）。
- `[bus] imu_median = false`（上游默认 true，**故意偏离**）：中值是纯一拍 20 ms 延迟，而训练侧 IMU 延迟包络 0–20 ms 且一半 env 是 0；`imu.rs` 明写走路策略超过约 20 ms IMU 滞后会失败。
- `[policy] head_lowpass = 1.0` / `legs_lowpass = 1.0`（默认 0.5/0.7 是 alpha 策略训练值，本管线零低通）；`action_scale = 1.0`。
- `[policy] gain = 200`（XL330 口径参考值，**不是寄存器 P**）+ `[bus] position_kp`：寄存器 `reg50 = clamp(round(gain × position_kp / 200), 1, 254)` 由 **robotd 算出并每次启动重写**，手写 EEPROM 只覆盖「robotd 起来之前」。
  - 当前部署档是 **kp8**（P8 速度 0.2069 vs P5 线 0.1129，+83%；但 P8 在 kp5 plant 上 7/8 摔 ⇒ **无降级模式**）。
  - 台架另有一条分支：mode 0 下把 `position_kp` 提到 16 可与 mode4/P8 的带宽等价（2 Hz gain 0.604 vs 0.604），但代价是电流/发热，**这颗舵机电流回读是坏的**，只能靠真机 per-joint 温度验收。⇒ **该分支标「待验」，不写进默认配置**；上板后回读 reg50 再定，禁止照抄旧清单的 `gain = 8`（会落成 reg50=1，机器人瘫软）。
- `[bus] joint_signs` / `joint_offsets` 各 15 条：腿部 10 颗方向 −1 有 replica 实机逐颗证据，**头部 5 颗存在分歧**（给出 +1 的那份自标 `calibration_verified:false`），先查 `left_knee` 再单验头部。零位只能靠 `joint_offsets`（链上没有 0x0B 校准指令，CENTER=2048 有厂商背书）；**HOME 是模型站姿，不是编码器零位**，两者各管各的。
- `[thermal] walk_max_c = 70`（舵机自身过热 latch 在 reg13=80 °C）。

### 3.3 开机硬校验与保护（robotd 只检查、不替你改）

- `feetech.rs` 逐颗比对 EEPROM：**baud / mode / limits**，不满足即 `IoError::Bus` 拒绝启动（注释 `checked, not corrected`）。台架现状 reg6=0（1M）、mode=4 ⇒ 两颗必改；reg9/11=0/4095 已合格，但**物理上不起限位作用**（实测堵在 1213/2816），限位只能由标定文件给。
- `reg19 = 13`（电压+过热+过流；出厂只有 4=仅过热）。**过载位 32 绝不能开**；别拿「恢复出厂」当安全动作（出厂 52 含 32）。
- **EEPROM 写入时序（已两次断电验证）**：断电 → 解锁 55=0 等 0.25 s → 写值等 0.50 s → 上锁 55=1 等 0.50 s → **再断电回读**。窗口 <0.35 s 全灭；绝不切 mode（会从 EEPROM 重载冲掉）；值没变跳过 commit。**回读 PASS ≠ 持久 PASS**。只能在「上电默认 reg40=0（扭矩关）、robotd 起来之前」的窗口写。
- **H9 volatile P/D 守卫**：50/51 是 RAM，`0x08 REBOOT` 会从 EEPROM 21/22 重载；上电前写 profile 并回读、`slow_sensors` 每秒比对 15 颗、reboot 清 verified flag；**EEPROM 永不自动写**。
- 安全层：跌倒判据 60°（`fall_gravity_z=-0.5`，debounce 200 ms）；FallPredictor 26° + 速率 + 300 ms 外推 → `gain_limp=50` → 0.6 s 回站姿；`deadman_ms=500` 只归零 twist。无关节限位，温度/电流只观测不判。

### 3.4 策略链与门检（上板前全部可在 PC 上跑完）

```
export.py → ONNX（单文件、initializer 无 EXTERNAL）
  → verify_policy_contract.py（obs 61 / act 14 / 50 Hz / 关节序 / HOME 逐位）
  → verify_policy_bundle.py（归一化分母下限 + metadata）
  → policy_numeric_gate.py --selftest（G1–G4 绝对物理量级；健康 PASS×2、deploy61 FAIL）
  → infer_policy.py --walking  →  uv run publish  →  robotctl policy load
```

- `publish` 与这代 robotd **不是一条链**：manifest 一个字段都不生效，对 ONNX 只查两个宽度（末维 61/14）。
- `publish` **不打包外部权重**：split 导出会以 3 KB 无权重图上传成功，拷贝前必须确认没有 `EXTERNAL`。
- `deploy61` 已下线（归一化分母 10 个维 1.113e-05，差 1157 倍）；用 `p8head_2999` / `resume_5999`（下限 0.01289）。
- **C9 数值 gate 不能照搬 esp-duck 的 `maxabs ≤ 2% of S`**：实测会误杀健康（超 5.2×/6.9×）又放行病态 `deploy61`（S 被放大 128×）；已重标 G1–G4 并带负对照。
- **H6 IMU 落脚乱跳首检**：`python servo_probe/imu_jitter_bench.py --port COM3 --id 200 --dur 10`，判据 δ_sflp>5° 且陀螺帧增量 <2° 判乱跳、`axis_dot<−0.3` 判 flip；`--selftest` 四条负对照全绿。检出是**纯软件问题、不重训**，修法第一顺位参考 `MHDuck/microduck` 的 I²C `ImuIo` 分离实现。
- **H13 验证速度不要用低速**：官方 velstand v8 在 0.15 m/s 下 4/10 不走、所有策略只有指令速度的 40–60%、0.10 m/s 下没有策略能走 ⇒ 上板先用 **≥0.3 m/s** 判「会不会走」，偏航漂移先记基线。

### 3.5 训练侧边界

- **plant 是一等坐标**：每次读数带 plant 指纹，cfg sha 盖不到传递闭包；**换 plant = 换任务，必须重训**。
- 训练命令：`cuda:0` + `MUJOCO_GL=glfw` + 显式 `--agent.logger tensorboard`。
- heading 奖励 A/B 结论是 **no decision**（median +5.87%，剔除降级后 +0.18%，趋势反转），不值得再花 3.3 h 重训。
- 改上游只纯新增；判决双轴 `err < 0.97×` 且 `vx ≥ 0.97×`；同 seed 不保证轨迹一致，重跑不算验证，只能 N 次重复 + sem。
- ⚠️ 台架 **4.6 V 欠压**（低于额定 4.8 V），kp8/duty/齿隙读数全是欠压取的；换 7.4 V 电池后必须重测。4.6 V 也跑不了会走路的 robotd（`identify_pack` 判成 2.3 V/cell，低于 2.95 V 下限）。

### 3.6 要不要重训（2026-11-06 判决）

**结论：现在不重训，GPU 开销 ¥0。** 部署候选 `p8head_2999`（`resume_5999` 同族）是
`p8head_030_4096x3000` 在 **`hd1910_kp8` plant**（`official_m6_stslaw.json`、`kp_fw=8.0`）
上训出来的（`docs/05-flat-walk.md` §21/§22，2026-11-03 判决 vx 0.2069、+83%）。
本方案改动的是**主控载板 / 供电 / IMU 固件 / 编译目标**，四者都不进 MDP、不进 obs、
不改 plant 参数 ⇒ 不触发重训。`AGENTS.md` §2 的「修改必重训」管的是**训练侧代码 / 奖励 / 编舞**，
不是部署侧载板。外部旁证：`zhuoligetu123/microduck-hd1910m` 用上游四个官方 ONNX
（**不重训**）在完全适配的 HD1910 硬件上跑起来了（`microduck-software/README.md` §1010）。

#### 不重训，但必须做对（否则会误判成「策略不行」而白烧 GPU）

| 项 | 正确动作 | 依据 |
|---|---|---|
| **mode 0 × `position_kp=8`** | ⚠️ 真机环路只有 plant 的 **54%**（P8/D8，fc 0.69 Hz vs plant 1.28 Hz）。要对齐训练 plant 走 `[bus] position_kp=16` + `gain=200`（P16/D8 = plant **92%**）——**这是配置对齐，不是换 plant，不重训**；以真机 per-joint 温度验收 | `microduck-HD1910软件方案.md` §10.2 / 行 1030–1091 |
| **4.6 V → 7.4/8.0 V** | 训练 json 本来就是 `ftservo_official_m6`（vin 7.4）口径，换电池是**更接近** plant，不是偏离。台架欠压读数（kp/duty/齿隙、饱和 onset ≈kp20）不可外推到 7.4 V（onset 右移到 ≈kp32） | 同上 §8.1；`docs/05-flat-walk.md` §22.2 |
| **IMU 换 `imu-feetech`** | 只要 SFLP 的 gravity/gyro 格式与延迟包络不变就不重训（`imu_median=false` 正是为此）；H6 落脚乱跳是纯软件修复，`joint_signs/offsets` 逐颗核对是标定，heading 控制律是推理侧 | 本方案 §3.2 / §3.4；`microduck-板子设计备忘.md` §156 |
| **`NEXT-p8-train.md:58` 的 `[policy] gain = 8`** | **旧结论，已作废**：`reg50 = clamp(gain × position_kp / 200)`，`gain=8` 会落到 reg50=1 ⇒ 机器人瘫软。保持 `gain = 200` | `microduck-HD1910软件方案.md` 行 1039–1054 |

⚠️ **G5 不过时第一顺位动作是回读 reg50 → 试 `position_kp=16` → 验 per-joint 温度，
不是重训**。§3.2 目前把 16 标「待验、不写进默认配置」，所以默认 8 会让 G5 大概率不通过 ——
那是 **train/deploy 不匹配**，不是策略容量问题，更不是"该重训了"。

#### 真会触发重训的三条（都必须**从零**，不能 `resume`）

1. **真机行为与 sim 不符，且排除配置 / 标定 / 软件后仍不符** ⇒ 回填 plant json ⇒ 换 plant ⇒
   **一次**从零重训。最新口径（§8.1，2026-11-03）已把触发条件从「参数没落地」改成
   「真机与 sim 不符」；**kt/R 不需要自己辨识**，别为此预先烧 GPU。若同时想动延迟域或
   heading 配方，**合并进同一次**重训，别分两次。
2. **端到端延迟超出训练带**：P8 × 80 ms 8/8 摔；部署缺口外推 11–18 ms 落在训练带内，
   但「A733 + 500k 端到端 ≤30 ms」只能实测（`docs/05-flat-walk.md` §19.4 / §19.6）。
   优先**压软件延迟（不重训）**；若必须把新延迟域写进训练 ⇒ domain 改动 ⇒ 从零重训。
3. **动训练侧任何东西**：奖励（含 `air_time` 门控、heading 闭环）、obs 布局、训练侧低通、
   课程 / 步频 ⇒ 从零重训。注意「**只在部署侧加低通**」不重训，但会造成 train/deploy
   不匹配（`microduck-software/README.md` 行 1051 已记此坑）。

**明确不值得的一次**：heading 奖励 A/B = **no decision**（median +5.87%，剔除降级后 +0.18%，
趋势反转），不花那 3.3 h。

⇒ 重训开关留到 **G5 之后**；现在直接拿 `p8head_2999` 跑 G0→G5，零 GPU 开销。

---

## 4. Go / No-Go 闸门（严格按三段顺序，不并行下单）

| 闸门 | 属于 | 判据 | 不过的动作 |
|---|---|---|---|
| **G0** | 价格 | `sts_bench.py` 五道闸门全绿：ping／事务 ≤5 ms／遥测合理值／50 Hz 长跑 0 错误且温度 ≤55 °C／运行时 P=8；**先跑 `--selftest` 12/12 负对照** | 停，联系卖家换货，不买后面任何东西 |
| **G1** | 价格 | 5 颗同步读、零位 <1°、吊架 10 min 无丢包 | 停，回到单颗 |
| **G2** | 硬件 | 15 舵机 + IMU 200 一次 sync_read 全到；bus 绿、loop **50 Hz 0 missed**；母线 ≥6.6 V 不掉 | 查 H8 上电姿态顺序 / H1 上电顺序 / 配电载流 |
| **G3** | 硬件 | 上电静止站立、SFLP 收敛 0.5 s；IMU 落脚乱跳判据一轮；H2 方向逐颗核对 | 记入软件修复队列，**不重训** |
| **G4** | 软件 | 契约 8 PASS / 数值 gate PASS / 无 EXTERNAL 已在本机预检（§4.3(4)）；bundle 的 B0 metadata 待 publish 产物复核 | 停，不上策略 |
| **G5** | 软件 | 先站稳 → ≥0.3 m/s 短走 → 不摔、体坐标前向（勿只报世界系 dx） | 先排查 plant / HOME / joint_offsets，不改奖励 |

### 4.1 G0 现成执行器（2026-11-06 补齐，不另造协议层）

`microduck-software/tools/hd1910/sts_bench.py` 原本只覆盖 ping 与 50 Hz 事务计时；本次
**在原有 `StsBus` / `SerialStsBus` 上纯扩展**，帧实现继续复用 `hd1910_readonly.py`、
寄存器表继续对齐 `hd1910_ident.py`（56..70 共 15 B），没有重写第二套协议：

```bash
# 无硬件：先证明门禁本身有效（负对照），再做合成彩排（彩排不是证据）
python microduck-software/tools/hd1910/sts_bench.py --selftest
python microduck-software/tools/hd1910/sts_bench.py --dry-run

# 有硬件：URT-2 + 1 颗，先插 USB 后上电，三档开关拨 5V
# ⚠️ 本机台架这颗 2026-11-02 已改成 ID 10；出厂新舵机才是 1
python microduck-software/tools/hd1910/sts_bench.py --port COM3 --id 10 --soak-seconds 60
python microduck-software/tools/hd1910/sts_bench.py --port COM3 --id 10 \
    --soak-seconds 3600 --write-goal-echo --out out/g0_1h.json
```

五道闸门：`0.1` ping；`0.2` 50 Hz 单字节事务 median ≤5 ms 且 0 错误；`0.3` 遥测块
（位置/电压/温度量级 + 可选「把当前位置原样写回 goal 再读镜像」，**不开扭矩、不产生位移**，
因此不触发 H8 的 inrush）；`0.4` 50 Hz 长跑（默认 60 s，1 h 用 3600）0 错误 + 温度峰值；
`0.5` 运行时 P == 部署档 8。

三条纪律已落进脚本：
- **负对照**：`--selftest` 的 12 条断言里，每个被故意改坏的量（ping 沉默 / 事务 6 ms /
  电压 0 / 温度 255 / 位置越 4095 / 温度 60 °C / CRC 每 3 次丢一次 / P=32 / goal 镜像不跟随）
  都必须让对应闸门变红，健康总线必须全绿。其中 **60 °C 特意选在闸门 0.3 的合理区间内、
  却越过闸门 0.4 的 55 °C**，用来证明两个阈值互不依赖。
- **阈值不取自被测量**：电压/温度/位置窗全是固定物理量级，自检先断言健康读数严格落在窗内且不贴边。
- **负载/电流只记录不判**：台架 reg60 恒 0、reg69 读到 16000 量级，读数与物理上下界矛盾 ⇒ 错的是读数。

顺带修了脚本里两处过时结论：`KP_FW_TARGET` 从 **5（P3 裁决）改为 8（部署档 `hd1910_kp8`）**，
与 `hd1910_ident.py:127` 的 `KP_FW_DEPLOY=8` 对齐；URT-2 供电说明从「V1 留空、外电直供舵机」
改为 **「V1/G 本就是外电输入，三档开关拨 5V，需 2.0→2.5 3P 转接线」**（2026-11-03 改判）。
⚠️ kt/R / 齿隙 / 最高速辨识**不在本脚本**，仍走 `servo_probe/hd1910_ident.py` 与 `bam_param_compare.md`。

⚠️ **闸门 0.5 的适用范围（2026-11-06 补）**：`P == 8` 是**单颗台架（URT-2、robotd 未启动）**
的口径，验的是 EEPROM/RAM 有没有真写进去。整机起来后 **robotd 是第二写者**：
`reg50 = clamp(gain × position_kp / 200)` 每个控制 tick 都会重写，整机回读 reg50 应按
§3.6 的 `mode 0 × position_kp` 判，**不能拿 G0 的 8 去要求整机**。两处数字不同是设计如此，
不是矛盾；把 0.5 照搬到整机会把正常的 `position_kp=16` 误判成 FAIL、进而误导成「换 plant
要重训」。

### 4.2 首次真机 G0 结果（2026-11-06，COM3 / CH343 / 1 Mbps / ID 10）

先扫 ID × 波特率定位：**1 Mbps 下只有 ID 10 应答**，500k / 115200 / 57600 / 9600 全无
⇒ 供电与接线都正常，错的只是脚本默认 `--id 1`（出厂口径）。改 `--id 10` 后：

| 闸门 | 实测 | 判定 |
|---|---|---|
| 0.1 ping | ID 10 @ 1M 应答 | PASS |
| 0.2 50 Hz × 100 | median **1.75 ms**、p95 1.91 ms、0 错误（预算 5 ms，余量 2.9×） | PASS |
| 0.3 遥测 | **4.5 V** / 25 °C / pos_raw 1751 / load_raw 0 / cur_raw 4 / `goal_echo=ok` | PASS |
| 0.4 60 s × 3000 帧 | median 1.62 ms、p95 1.92 ms、**0 错误**、温度峰值 **25 °C**（全程不升） | PASS |
| 0.5 reg50 | **P = 8** | PASS |

报告 `out/g0_60s.json`（`out/` 被 gitignore，不入库）。`--selftest` 12/12 先跑过。

**同一次上电的 EEPROM/RAM 只读扫描（ID 10）**：

| 项 | 值 | 对方案的含义 |
|---|---|---|
| reg5 / reg6 | **10** / **0 = 1 Mbps** | 台架是 1M；整机 B 代 robotd 写死 500k ⇒ 上板要改 reg6=1 |
| reg33 mode | **4** | robotd 硬校验要求 0 ⇒「两颗必改」里的第二颗，实证坐实 |
| reg9 / reg11 | 0 / **4095** | 硬校验已合格（16 位读全，不是低字节 255） |
| reg19 / reg13 | **13** / 80 °C | 保护位已是目标值（电压+过热+过流，无过载位 32） |
| reg21 / reg50 / reg55 | **8 / 8 / 1** | EEPROM 与 RAM 都是 8、锁已上 ⇒ **0.5 是真 PASS，不是恰好没 FAIL** |
| reg40 / reg42 / reg56 / reg67 | **1** / 1751 / 1751 / **1751** | ⚠️ 扭矩本来是开的；goal、位置、镜像三者一致 ⇒ 原样回写不产生位移。脚本旧文案「不开扭矩」不准确，已修 |
| reg48 / reg69 | 1000 / 0 | 空载力矩上限与电流读数合理；脚本注释里「reg69 读到 16000 量级」是特定工况，不能当常态，仍只记录不判 |

**三条结论**：

1. **G0 过了，阶段 0（¥0）收口** ⇒ 可以进 G1（买 5 颗做单腿同步读与零位）。**不需要重训**。
2. **台架与整机的口径差有了实证**：台架 `1M / mode4 / P8 / 4.5 V`，整机
   `500k / mode0 / position_kp=16 / 7.4 V`。§3.6 那张「54% vs 92%」的表不是推的 ——
   `reg33=4` 坐实了 mode 差。上板第一件事按 §3.3 改 reg6 与 reg33 并回读生效值。
3. ⚠️ **4.5 V 欠压**（低于额定 4.8 V）：kp8 / duty / 齿隙 / 饱和 onset 全是欠压读数，
   不能外推；这个电压下 robotd 也起不来（`identify_pack` 判 2.25 V/cell < 2.95 V 下限）。
   G1 之前要么换 7.4 V 供电，要么明确标注「仅通信链路验证，不作动力学证据」。

**仍未跑**：1 h 长跑（`--soak-seconds 3600`，需另开终端）、**带载温升**、7.4 V 电压域、
15 颗同步读。本次 60 s 空载静止、温度全程 25 °C 没升 ⇒ 温升判据**尚未真正受力**。
`goal` 镜像即时性只在这版固件上验过，换固件要重验。

### 4.3 阶段 0 顺带闭合的两件只读验证（2026-11-06，COM3 / ID 10 / 1 Mbps）

G0 之外，趁舵机在线把两个**早已写好但从未在真机上跑过**的探针跑完。两者都只读、不动扭矩、零成本。

#### (1) 500 kbps 整机总线预算：从纯静态推算变成台架实测校准

`servo_probe/probe_bus_budget.py --selftest` **25/25**；真机 `--port COM3 --id 10 --baud 1000000 --repeats 40`。**同一命令连跑 5 次**（下表是首次、也是最保守的一次）：

| 量 | 首次实测 | 说明 |
|---|---|---|
| ping | min 213.9 / p50 239.3 µs | 40 次 0 未答 |
| read 2 B | min 261.9 / p50 273.9 µs | — |
| read 15 B | min 412.7 / p50 446.3 µs | — |
| 差分 13 B | 150.8 µs ⇒ **11.60 µs/字节** | 理论 10.00，比值 **1.16** |
| 固定开销 | 76.3 µs/包 | 含 USB 批延迟，**不可按设备数外推** |

🔑 **重跑不算验证**：5 次重复的每字节时间落在 **10.58–11.60 µs/B**（比值 1.06–1.16；中位 11.32，mean ± sem = 11.18 ± 0.17），固定开销 76–99 µs/包。USB 批延迟每次都不同，把单次读数写成定值就是假精度。所以 D 段按首次（最保守）列，**G2 判定看区间不看单次**：

| 统计量（N=5） | 每字节 µs | 标称档 ms | 最坏档 ms | 留给推理 ms |
|---|---|---|---|---|
| 最小 | 10.58 | 10.28 | 16.68 | 3.32 |
| 中位 | 11.32 | 10.81 | 17.23 | 2.77 |
| mean ± sem | 11.18 ± 0.17 | 10.71 ± 0.13 | 17.11 ± 0.12 | — |
| 最大（最保守） | 11.60 | 11.01 | 17.41 | 2.59 |

方法比数字重要：**跨波特率只能搬「比值」，不能搬绝对时间**（把 1M 的 11.60 µs 直接套到 500k 会低估一半，脚本自检里有这条负对照）。首次读数外推用 `20 µs/B × 1.16 = 23.20 µs/B @500k`。台架 1 Mbps 只是 URT-2 / USB-TTL 这一路的速率，**不能据此认为整机可跑 1M**。

下表按首次读数（ratio 1.16，最保守档）外推：

| 每颗响应间隙 | 读合计 | 每 tick 总线 | 占 20 ms | 留给策略推理 |
|---|---|---|---|---|
| 50 µs | 9.15 ms | 10.21 ms | 51% | 9.79 ms |
| **100 µs（标称）** | 9.95 ms | **11.01 ms** | **55%** | 8.99 ms |
| 200 µs | 11.55 ms | 12.61 ms | 63% | 7.39 ms |
| 500 µs（悲观上界） | 16.35 ms | **17.41 ms** | **87%** | **2.59 ms** |

早期估算 10.9 ms 落在 5 次重复的 **10.28–11.01 ms** 区间内（中位 10.81），被实测**证实**；但新信息是最坏档：45 Hz unhealthy 门槛对应 22.22 ms，最坏档仍在门槛内，**却只留 2.59–3.32 ms 给 ONNX 推理 + 控制律 + IPC**；而一次读超时是 30 ms > 一个 20 ms 周期，`MissedTickBehavior::Skip` 不补 ⇒ 任何一次超时吃掉整个 tick。这正是 G2 要测 `50 Hz 0 missed` 的理由，不是「还活着」就够。

三套数字口径不同，**不可混用**：

| 口径 | 字节数 | 500k 下 | 占周期 | 出处 |
|---|---|---|---|---|
| 早期净荷估算 | 295 B | 4.7 ms | 24% | IMU 三方对照 §0 |
| 源码整帧静态（含帧头 6 B/帧 + 53 B 写包，无 gap） | 413 B | 8.26 ms | 41% | `feetech.rs` / `model.rs` 常量解析 |
| **台架实测校正 + gap 100 µs（N=5）** | 413 B | **10.28–11.01 ms** | **51–55%** | 本节 |

#### (2) 上板成品 TOML 审计：1 FAIL，且现在补不上

`audit_robotd_toml.py --toml out/robotd_hd1910_mode0.toml --expect-kp 16`：schema 白名单从 `lib.rs` 重新推导通过，`gain=200` / `action_scale=1.0` / 两个 lowpass=1.0 / `cells=[2]+max_volts=8.4` / `imu_median=false` / `thermal.walk_max_c=70` 全 ok，**唯一 FAIL 是 `bus.joint_ids` 为空** —— Feetech 总线宁可拒绝打开也不猜关节到 ID 的映射（`main.rs:5495`）。

⇒ 🔴 **这份 TOML 目前加载不了**，是上板前的硬阻塞。`joint_ids` 必须装机后逐颗 `identify_joints.py` 实测再填：B 代 `JOINT_IDS` 是 `20-24 / 30-34 / 10-14`（IMU 200），HD-1910 复刻线是 `1-15`；台架只有一颗 ID 10，只能证明它落在 B 代体系里，**不能**据此推出其余 14 颗。猜错等于「用 A 关节的目标驱动 B 关节」。

顺带澄清 audit 参数：`--expect-kp` 要填**期望的 reg50**（成品写 `position_kp=16` ⇒ 填 16），不是训练 `kp_fw=8`。填 8 会多一条 FAIL，那是把 §3.6 的「配置对齐 ≠ 换 plant」误当成配置错误。

#### (3) 一条会害到上板操作的过时结论，已订正

`deploy_import_checklist.md` B13 与 `probe_bus_budget.py` F 段都写着「改板侧到 1 Mbps ⇒ 15 颗 reg6 一颗都不用写」。那是主控选 **Radxa Zero 3W / RK3566** 时写的；本方案已定 **Orange Pi Zero 3W / A733**，其 UART7 只能精确表示 500 kbps。⇒ **该建议作废**：`BAUD_RATE` 保持 500k，**15 颗必须逐颗把 reg6 从出厂 0 改成 1**，与 `reg33=0` 一起是上板两颗必改。B13、F 段、§0.1 表格已同步改写。

#### (4) G4 策略侧预检：两绿一红，红的那条按部署链判

环境先说清：这几个脚本**必须**用 `microduck-software/.venv-mjlab/Scripts/python.exe`（numpy 2.5.4 / onnxruntime 1.31.0）；系统 Python 缺 numpy / onnxruntime / `mjlab_microduck`，只会报 `ModuleNotFoundError`。

| 检查 | 结果 |
|---|---|
| `verify_policy_contract.py --selftest` | 15 条负对照全部按预期变红 |
| 同上，真策略 `p8head_2999.onnx` + 成品 TOML | **8 项全 PASS**：obs 61 / block order / 14 关节顺序 / home pose 差 0 / command 13 / action mapping scale 1 / 50 Hz / ONNX `obs[1,61]` → `actions[1,14]`，站姿动作幅值上限 0.193 rad |
| `policy_numeric_gate.py --selftest` | 健康 PASS×2、`deploy61` FAIL |
| 同上，真策略 | **PASS**：G1 0.3018 / G2 0.4218 / G3 0.2947 / G4 std 0.7735，报告 `out/g4_p8head_2999.json` |
| ONNX 直接检查 | 793 KB、10 个 initializer **全内嵌、无 EXTERNAL**、输入 `obs[1,61]` / 输出 `actions[1,14]` |
| `verify_policy_bundle.py --selftest` | 39/39 |
| 同上，真策略 | **19 checks / 1 FAIL**：B0 `no metadata_props` |

⚠️ **不要把这个 1 FAIL 抹成全绿**。`p8head_2999.onnx` 是训练直出的 checkpoint，没有 `metadata_props` 布局契约；其余 18 项全 ok（含 A8 权重内嵌、C4 归一化下限 0.01289、R1–R3 输出有限且会随输入变化、D1/D3 缩放与低通）。同一份检查也写明 `E0 manifest none given (this robotd never reads one)` —— 这代 robotd 不读 manifest，`publish` 的 manifest 字段一个都不生效，对 ONNX 只有两个宽度检查（末维 61/14）。⇒ **判决：B0 不构成当前部署链的阻塞，但 G4 不能写成「全绿」**；`publish` 之后必须对**发布产物**重跑 bundle 检查，而且只要 obs 曾经重排，缺 metadata 就没人能发现，这条风险要留着。

C9 再次被现场印证：照搬 esp-duck 的 `maxabs ≤ 2% of S` 会**误杀这份健康策略**（站姿约为 2%S 的 5 倍，`standing_passes=false`），却放行 `deploy61`。

两个边界：契约检查**不覆盖** `joint_ids`（那是 (2) 的 audit 唯一 FAIL），也不覆盖躯干坐标系 / 符号 / 零位（B3、B4 台架项）；运行时有一条 `[WARN] Failed to load task package mjlab_microduck ... circular import`，脚本仍给出训练侧数值并判全绿，换环境要重跑确认。

---

## 5. 仍未闭合的边界（不写成定案）

1. **淘宝商品页**（登录墙）：kissqy HAT+IMU 具体款式、拆卖价、是否含已烧 FT6、香蕉板是否上架 —— 见上一轮「需要上淘宝核实」清单，其中 **HAT 的 UART 引脚映射（换 A733 后）** 与 **IMU 板 MCU 型号/固件版本** 是决定要不要飞线或换板的两条。
2. **HAT 的 5 V 降压输入范围与板上 10 µF 电容耐压**：原理图未标；2S 8.4 V 大概率 OK，3S 一定不行。
3. **community-kit IMU 上电首帧握手**：默认 1M → 先用 1M 写 reg6=1 → 再切 500k，`bus.c` 的协议粘滞逻辑意味着顺序需台架验证。
4. **`banana_pcb` 3–5 A 上限**与整机 30 A 峰值设计的差距：站起/跌倒恢复压降需上板实测。
5. **`position_kp = 16` 分支**的电流/发热代价：这颗舵机 `reg60` 恒 0、`reg62` 会拼进温度，电流回读坏，只能用真机 per-joint 温度验收。
6. 官方 3D 模型衍生件带 **CC BY-NC-SA 4.0** 非商用限制，不满足 OSHWA 开源硬件定义；打印件不等于可制造套件。
7. **G0 真机已过（§4.2），但四条仍未闭合**：① 1 h 长跑、② **带载温升**（本次 60 s
   空载静止、温度 25→25 °C 没升，55 °C 闸门尚未真正受力）、③ 7.4 V 电压域（本次 4.5 V
   欠压）、④ 15 颗同步读（G2）。另外 `goal` 镜像即时性只在**这版固件**上 `ok`，换固件要重验；
   `--write-goal-echo` 若失败，先记 firmware 版本再判，别直接改阈值放行。
8. **上板 TOML 的 `joint_ids` 未填**（§4.3(2)，audit 唯一 FAIL）：必须装机后逐颗实测，
   现在填就是猜。另外总线最坏档只留 **2.59–3.32 ms** 给推理，ONNX 在 A733 上的实测耗时还没有，
   G2 之前不能只按「45 Hz 门槛内」判安全。

---

## 6. 来源（均为一手，按段索引）

| 段 | 主要依据 |
|---|---|
| 价格 | `docs/hardware/microduck-采购清单.md` §7 / §7.5 / §7.9.1 / §9；`docs/active/microduck-板子设计备忘.md` §5.4；`docs/archive/microduck-低成本方案.md` §阶段 0 |
| 硬件 | `docs/hardware/microduck-硬件清单-详细接线版.md` §1–§9；`docs/hardware/microduck-IMU三方对照-666wsp-kissqy-DuckBuddy.md` §0 / §0.5 / §5；`docs/hardware/microduck-IMU板对照-666wsp-vs-DuckBuddy.md` §4–§6；`docs/hardware/microduck-供电接线图.svg` / `microduck-分线板设计图.svg`（已降为备用） |
| 软件 | `microduck-software/tools/hd1910/deploy_import_checklist.md` A/B/H/C/D/E 全段；`microduck-software/tools/hd1910/audit_robotd_toml.py` R1–R29；`microduck-software/tools/hd1910/sts_bench.py`（G0 五闸门 + 负对照）；`microduck-software/tools/hd1910/servo_probe/hd1910_ident.py`（56..70 寄存器表）；`docs/reference/microduck-软件到硬件全链路资料地图-2026-11-06.md` §2；`docs/reference/microduck-未核实项核查报告-2026-11-06.md` §2 / §3 / §5；`microduck-software/tools/hd1910/servo_probe/probe_bus_budget.py`（25/25 自检 + §4.3 台架实测）；`microduck-software/out/robotd_hd1910_mode0.toml`（§4.3 审计对象）；`verify_policy_contract.py` / `verify_policy_bundle.py` / `policy_numeric_gate.py`（§4.3(4) G4 预检） |
| 上游源码 | `.upstream/DuckBuddy-main/`（`feetech.rs` / `model.rs` / `obs.rs` / `lib.rs`）、`.upstream/community-kit/`（KiCad + `boot_regs.c`）、`.upstream/replica/`（`directions.json`）、`.upstream/kissqy/`（`imu-source/src/main.c`）、`.upstream/666wsp-microduck-hd1910/`（原理图 PDF） |
| §2.6 主控备选（外部一手，2026-11-06） | Radxa `docs.radxa.com/en/cubie/a7z`、Product Brief v1.1 §5.1.1（40-pin 复用表）、官方原理图 v1.11 sheet 14 `PCIE_40PIN_CONNECT`；Orange Pi `orangepi.org` Zero 3W 规格与公开 pinout；DuckBuddy README「已验证的平台」；本仓 `deploy/robotd.toml:19` 与 `docs/hardware/INTERFACE-CN.md` §2.1。价格为 Allnet China / sbc.compare / 淘宝聚合页，**SKU 未核实，不作定案** |
