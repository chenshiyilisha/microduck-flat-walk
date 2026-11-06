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
| 总线速率 | 500 kbps | 1 Mbps | 50 Hz、16 设备同步读约 295 B/tick，500k 占线约 4.7 ms / 20 ms ≈ 24%；Radxa 上也跑 500k，1M 从未被用上；A733 UART7 设 1M 实测只有约 750 kbps |
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
> ⚠️ 「事务 ≤5 ms」是**单颗台架**闸门（URT-2 调试速率下）；整机 16 设备的总线预算是另一回事 —— 500k 下约 10.9 ms / 20 ms（`deploy_import_checklist.md` §B13）。两个量不能互相套。

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

---

## 4. Go / No-Go 闸门（严格按三段顺序，不并行下单）

| 闸门 | 属于 | 判据 | 不过的动作 |
|---|---|---|---|
| **G0** | 价格 | `sts_bench.py` 五道闸门全绿：ping／事务 ≤5 ms／遥测合理值／50 Hz 长跑 0 错误且温度 ≤55 °C／运行时 P=8；**先跑 `--selftest` 12/12 负对照** | 停，联系卖家换货，不买后面任何东西 |
| **G1** | 价格 | 5 颗同步读、零位 <1°、吊架 10 min 无丢包 | 停，回到单颗 |
| **G2** | 硬件 | 15 舵机 + IMU 200 一次 sync_read 全到；bus 绿、loop **50 Hz 0 missed**；母线 ≥6.6 V 不掉 | 查 H8 上电姿态顺序 / H1 上电顺序 / 配电载流 |
| **G3** | 硬件 | 上电静止站立、SFLP 收敛 0.5 s；IMU 落脚乱跳判据一轮；H2 方向逐颗核对 | 记入软件修复队列，**不重训** |
| **G4** | 软件 | 契约三检 + C9 数值 gate + `--selftest` 全绿；ONNX 无 EXTERNAL | 停，不上策略 |
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
python microduck-software/tools/hd1910/sts_bench.py --port COM3 --id 1 --soak-seconds 60
python microduck-software/tools/hd1910/sts_bench.py --port COM3 --id 1 \
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

---

## 5. 仍未闭合的边界（不写成定案）

1. **淘宝商品页**（登录墙）：kissqy HAT+IMU 具体款式、拆卖价、是否含已烧 FT6、香蕉板是否上架 —— 见上一轮「需要上淘宝核实」清单，其中 **HAT 的 UART 引脚映射（换 A733 后）** 与 **IMU 板 MCU 型号/固件版本** 是决定要不要飞线或换板的两条。
2. **HAT 的 5 V 降压输入范围与板上 10 µF 电容耐压**：原理图未标；2S 8.4 V 大概率 OK，3S 一定不行。
3. **community-kit IMU 上电首帧握手**：默认 1M → 先用 1M 写 reg6=1 → 再切 500k，`bus.c` 的协议粘滞逻辑意味着顺序需台架验证。
4. **`banana_pcb` 3–5 A 上限**与整机 30 A 峰值设计的差距：站起/跌倒恢复压降需上板实测。
5. **`position_kp = 16` 分支**的电流/发热代价：这颗舵机 `reg60` 恒 0、`reg62` 会拼进温度，电流回读坏，只能用真机 per-joint 温度验收。
6. 官方 3D 模型衍生件带 **CC BY-NC-SA 4.0** 非商用限制，不满足 OSHWA 开源硬件定义；打印件不等于可制造套件。
7. **G0 脚本只在合成总线上验过**：`--selftest` 12/12 与 `--dry-run` 全绿只证明门禁逻辑有效，
   **不是台架证据**。真机 URT-2 的帧时序、`goal` 镜像是否即时更新、60 s 长跑的实际温度曲线
   都还没跑；`--write-goal-echo` 若在某版固件上失败，先记 firmware 版本再判，别直接改阈值放行。

---

## 6. 来源（均为一手，按段索引）

| 段 | 主要依据 |
|---|---|
| 价格 | `docs/hardware/microduck-采购清单.md` §7 / §7.5 / §7.9.1 / §9；`docs/active/microduck-板子设计备忘.md` §5.4；`docs/archive/microduck-低成本方案.md` §阶段 0 |
| 硬件 | `docs/hardware/microduck-硬件清单-详细接线版.md` §1–§9；`docs/hardware/microduck-IMU三方对照-666wsp-kissqy-DuckBuddy.md` §0 / §0.5 / §5；`docs/hardware/microduck-IMU板对照-666wsp-vs-DuckBuddy.md` §4–§6；`docs/hardware/microduck-供电接线图.svg` / `microduck-分线板设计图.svg`（已降为备用） |
| 软件 | `microduck-software/tools/hd1910/deploy_import_checklist.md` A/B/H/C/D/E 全段；`microduck-software/tools/hd1910/audit_robotd_toml.py` R1–R29；`microduck-software/tools/hd1910/sts_bench.py`（G0 五闸门 + 负对照）；`microduck-software/tools/hd1910/servo_probe/hd1910_ident.py`（56..70 寄存器表）；`docs/reference/microduck-软件到硬件全链路资料地图-2026-11-06.md` §2；`docs/reference/microduck-未核实项核查报告-2026-11-06.md` §2 / §3 / §5 |
| 上游源码 | `.upstream/DuckBuddy-main/`（`feetech.rs` / `model.rs` / `obs.rs` / `lib.rs`）、`.upstream/community-kit/`（KiCad + `boot_regs.c`）、`.upstream/replica/`（`directions.json`）、`.upstream/kissqy/`（`imu-source/src/main.c`）、`.upstream/666wsp-microduck-hd1910/`（原理图 PDF） |
