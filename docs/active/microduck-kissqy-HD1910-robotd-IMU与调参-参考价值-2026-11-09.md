# kissqy / fanhao375 HD-1910 robotd 的 IMU 与舵机调参 · 参考价值

> 研究对象：`fanhao375/Microduck-kissqy`（分支 `hd1910-v167-trunk-imu-i2c`，2026-11-09 拉取）。
> 这是 `kissqy/Microduck-kissqy`（R17 V167 / control.43）的第三方 fork，由 `fanhao375/microduck-replica` 维护，**非官方、未经 kissqy 审阅**。
> 对照对象：我们 workspace 里 `.upstream/DuckBuddy-main/` 与 `.upstream/hd1910m/microduck/` 两套 robotd + `microduck-software/out/robotd_hd1910_mode0.toml`。

---

## 0. 一句话结论（先给判决）

1. **🔴 最重要的发现（真实风险，不是纸面参考）**：fanhao 在真机上实测到 **BNO085 的 game-rotation（0x08）走路时会突然跳 20–60°**，芯片自己的陀螺却说机身几乎没动；策略看到的 gravity 跟着跳 = 突然被告知"你在倒" = 摔。我们 `hd1910m/microduck/duck-control/src/bno08x.rs` 读的正是 `0x02 gyro` + `0x08 game-rotation`，而 **0x08 分支（`:87-95`）只做归一化、直接采信，无任何跳变门控**；`reference_native`（`reference_filter`）只是**对陀螺做 EMA**（`:76-79`），不保护四元数。→ **只要走 BNO08x I2C 路径，这个乱跳会原样进 policy**。fanhao 的 `gyro_fusion.rs` 就是现成解法。
2. **🔴 别脱离"robotd 代次 / IMU 输入路径"谈 IMU 类型**（本次踩过一次坑）：workspace 里**并存两套 robotd + 三条 IMU 输入**：
   - `DuckBuddy-main`（Orange Pi A733 / HL-2915 / `feetech_hls` / 500k / EEPROM reg6=1,reg33=0 硬校验）→ IMU = **总线 `imu_to_dxl v2` 板（LSM6DSV16X，ID 200）**，`sync_read` 56..70 前 12B，`SflpDecoder`。`out/robotd_hd1910_mode0.toml` 明确绑这一代（其注释 §69-77、§105-111 自述），且**不含任何 BNO08x 专属键**（`reference_native`/`imu_bus`/`imu_address`/`imu_mount_wxyz` 全无）。
   - `hd1910m/microduck`（Radxa / FT-SCS 原生 / `open_with_imu` 固件元数据 `row[33]==4`）→ **同时保留两条输入**：`bno08x.rs`（Native BNO085 I2C SH-2，`open_imu` + `reference_native`）和 `imu.rs`（同一颗 LSM6DSV16X 总线板解码器）。MEMORY.md §IMU 第 54 行说的 "HD-1910 = BNO08x、非总线板" 指的是**这条线的 `open_imu` 输入路径**，不是部署 toml 绑的那一代。
   - `kissqy/fanhao` 的 `Bus` 选项 = 上面那块 **LSM6DSV16X 总线板**（`hardware/IMU-TIMELINE.md`：ID 200、1 Mbps、最初 Dynamixel P2.0 后适配 Feetech SCS v1、STM32G031F8P6 + LSM6DSV16X）。
   → **本次研究过程中我曾只读 `DuckBuddy-main/imu.rs` 就要推翻 MEMORY 的 BNO08x 结论，属于「查全不够」，已纠正。IMU 类型必须绑定代次与输入路径，这正是项目「plant 是一等坐标」准则。**
3. **C1「总线 IMU 从机 ID200」**：对 `DuckBuddy-main` 部署代次 = **已在用**（同一块板）；fanhao 的 EasyEDA 工程 `ProPrj_imu_to_dxl_RevA_V1` + `firmware/imu-source/` 固件是这块板子的**维修/重制一手参考**（项目 `microduck-HD1910软件方案.md:68/:96-101/:788` 已把它列为寄存器契约与 IMU 规格来源）。对 `hd1910m` 的 BNO08x 输入路径则不适用。
4. **C2「IMU 融合务必自做」**：具体化 = `gyro_fusion.rs` 的倾斜门控算法 + BNO085 乱跳真机实证。对 **BNO08x 输入路径直接适用且高度优先**；对 LSM6DSV16X 总线板路径不直接适用（板上 STM32 跑 SFLP，host 不做融合）。
5. **门控细化**：fanhao `HostImuGate`（50ms 龄 / 1s 稳定期 / 3 次重复判冻结）比 `SflpDecoder` 的 `ready()>=25 samples` 细；`hd1910m/bno08x.rs:sample()` 已有 150ms 龄 + 30ms 偏斜门（比 fanhao 宽）。
6. **舵机调参**：kissqy 把 P/D/转矩限制写 RAM 48–51，V167 默认 P5/D0/1000；我们部署线 `position_kp=16/position_kd=8`，**增益口径不同，数字不可抄**。

---

## 1. 仓库定位与架构分层

- 原版 `kissqy/Microduck-kissqy` = HD-1910 整套（R17 V167 / control.43）的 Rust robotd（`robotd`/`robotctl`/`padd`）。
- fanhao fork 在 V167 上加三样**可选**改动：IMU 模块直连主板 I²C、舵机调参、UDP 手柄；每个改动"不打开就跟 V167 原版逐字节一致"。
- 原版 robotd **只认总线 IMU 小板（ID 200，刷 FT6 固件）**；fork 加 `[trunk_imu]` 让配置切到 `bno08x` / `lsm6dsv16x`（主板 I²C）。

---

## 2. IMU 三路线架构（`trunk_imu.rs`）

```rust
pub enum TrunkImuKind { Bus, Bno08x, Lsm6dsv16x }
```

三种来源**统一收敛到 `crate::imu::TrunkFrame`**，policy 无法区分，只靠各自的 `mount`（安装四元数）区分：

| 来源 | 硬件 | 接入 | 解码 / freshness |
|---|---|---|---|
| `Bus`（原版默认） | 总线 IMU 小板，ID 200，FT6 固件 | 舵机总线，同一 `sync_read` | `crate::feetech` 据板子状态判 freshness |
| `Bno08x` | BNO085/086 模块 | 主板 I²C（0x4A/0x4B） | `crate::bno08x` + `gyro_fusion`（可选） |
| `Lsm6dsv16x` | LSM6DSV16X 转接板（与总线小板同芯片） | 主板 I²C（0x6A/0x6B） | `crate::lsm6dsv16x` |

**架构原则（值得抄）**：host 自读的 IMU 由**独立 reader 线程**拥有设备、对话 codec、发布最新 `HostImuSample`；控制线程每 tick 取一个，`HostImuGate` 决定能否用。**控制线程绝不等待 reader**——慢/卡住的 I2C 表现为"旧 sample + 拒绝 tick"，与总线板故障一视同仁（拒绝文本统一为 `"Feetech IMU not ready or stale"`），而非阻塞在 read 里。

### 2.1 总线 IMU 小板（C1 实物）的来龙去脉

`hardware/IMU-TIMELINE.md`：ID 200、1 Mbps，**最初 Dynamixel Protocol 2.0**（09-03~04），后适配 **Feetech SCS v1**（09-20，修复与舵机共线时序，3000/3000 验证）；硬件 **LSM6DSV16X + STM32G031 + TLV70433 + 74LVC2G125**，22.7×25.6mm 两层板；固件 `microduck-hd1910/firmware/firmware/imu-source/`。这与项目 `microduck-HD1910软件方案.md:68/:98-100` 记录的 `SYNC_ADDRESS=56 / SYNC_LENGTH=15 / IMU_ID=200 / SYNC_READ=0x82`、诊断块 124..143 / 紧凑块 56..70 **同一块板**。

### 2.2 我们的两套 robotd 与 IMU 输入路径（本次踩坑后的正确分层）

| | `DuckBuddy-main`（部署 toml 绑定的代次） | `hd1910m/microduck`（上游原机代次） |
|---|---|---|
| SBC / 总线 | Orange Pi A733 / HL-2915 / `feetech_hls` 500k | Radxa / FT-SCS 原生 |
| 开机校验 | EEPROM reg6=1,reg33=0,reg9=0,reg11=4095 | 固件元数据 `open_with_imu` `row[33]==4`(mode-4) |
| IMU 输入 1 | **总线 `imu_to_dxl v2`（LSM6DSV16X, ID 200）**，`imu.rs:SflpDecoder`，`feetech.rs:319` `SflpDecoder::new(config.imu_mount).with_median(config.imu_median)` | **同款总线板解码器**（`imu.rs` 开头逐字相同） |
| IMU 输入 2 | 无 | **`bno08x.rs` Native BNO085 I2C SH-2**，`feetech.rs:203-207` `open_imu` → `Bno08x::open(cfg.imu_bus, cfg.imu_address, installation.imu_mount_wxyz)` + `set_reference_filter(cfg.reference_native)` |
| 配置 | `out/robotd_hd1910_mode0.toml`（`[bus] deny_unknown_fields`、`imu_median=false` 活键、`servo=feetech_hls`；**无 BNO08x 键**） | `hd1910-calibration.option-a.toml` / `hd1910m/radxa/installation.json`（`imu_mount_wxyz=[0.5,-0.5,0.5,-0.5]`） |

→ MEMORY.md §IMU 的 "HD-1910 = BNO08x、非总线板" 描述的是**右列的 `open_imu` 输入路径**；部署 toml 是**左列**。**两者并存、不矛盾，只是代次与输入路径不同**。

---

## 3. BNO085 乱跳 + 陀螺积分融合（C2，本次最高价值）

### 3.1 问题（`gyro_fusion.rs` 头部注释 + `IMU-MODULE.md` §4.4）

走路时 BNO085 的 **game rotation vector（报告 0x08）会突然跳 20–60°**（一个 20ms tick 内），同刻标定陀螺（0x02）说机身几乎没动。50Hz 真机录像：走路帧 1.9–23 % 发生（看脚底材料），静站 0.05 %。gravity 跟着跳 = 策略突然被告知"你在倒" = 摔。

### 3.2 🔴 我们 `hd1910m` 的 BNO08x 路径会原样吃进这个乱跳

`hd1910m/microduck/duck-control/src/bno08x.rs`：
- `:1` 注释 "Native BNO085 I2C SH-2 gyro/game-rotation input"。
- `:63-67` 只接受 `0x02`(gyro,10B) / `0x08`(quat,12B) / `0xfa,0xfb`(5B)。
- `:74-85` **0x02 陀螺**：`reference_filter` 开时做 EMA（`weight=0.5^(Δt/0.01)`），仅此而已。测试 `reference_gyro_ema_is_applied_once_per_fresh_report`（`:123-136`）证明它是陀螺 EMA。
- `:87-95` **0x08 四元数**：`normalized()` 后**直接 `self.quat = Some(...)`，无任何跳变门控、无陀螺交叉校验**。
- `:104-111 sample()` 唯一的门是 **150ms 龄 + 30ms gyro/quat 偏斜**，管"过期/不对齐"，**不管"跳变"**。
- `feetech.rs:206` `set_reference_filter(cfg.reference_native)` 只影响上面那个陀螺 EMA。

→ **结论**：`reference_native` ≠ fanhao 的 `gyro_fusion`。若 `hd1910m` 这条 BNO08x 输入路径上真机也用 BNO085，fanhao 实测的乱跳会直接进 `gravity`（`:117`）→ policy / 跌倒判据。**这是待上板验证的真实风险，不是纸面借鉴。**

### 3.3 fanhao 的解法：host 自己做陀螺积分姿态（`gyro_fusion.rs`）

纯数学、无 I/O、无时钟（时间由 report 序列号驱动），可直接移植：
- 每个陀螺报告积分为 host 自己的姿态。
- 每个 game-rotation-vector 与之比**倾斜度（两重力方向夹角）**：
  - `< GATE_DEG(6°)`：缓慢跟随芯片 `1 − e^(−Δt/τ)`（τ=0.66s），留下 <0.1° 陀螺偏置；
  - `≥ 6°`：拒绝芯片，纯陀螺积分撑着；
  - 拒绝超 `REALIGN_AFTER_S(0.5s)` + 芯片平静（`CALM_RATE_DEG_S=100°/s`）+ 躯干静止（`STILL_RMS_DEG_S=30°/s`）：整步对齐芯片（纠漂移，且在无步相位）；
  - 否则 `SLEW_DEG_S(5°/s)` 缓慢拉向芯片（永不长期开环）。
- **只融合倾斜；航向跟随芯片但不进 policy/跌倒检测**（只进 roller 航迹/里程计）。
- epoch 重启跟随芯片 `FOLLOW_S(1s)`（与门控 `HOST_IMU_SETTLE` 一致）；陀螺流空洞（序列跳 >3 / 时间间隙 / 无读数）不能跨积分。
- 全部结果检查 finite + 单位长度，否则 `Fallback` 采信芯片（NaN 进 `TrunkFrame` 会"看起来新鲜"地冻结旧姿态）。

### 3.4 实测对比（10-15 真机，BNO085，全默认，硅胶脚，806g）

| | `chip`（芯片融合） | `gyro`（陀螺积分） |
|---|---|---|
| 直立走路 / 推摇杆 | 62s / 9s | 634s / 60s |
| 摔倒 | 3 次（推着摇杆 2 次） | 1 次（不在推杆时） |
| 芯片姿态 >5° 跳变 | 330 次（策略看到的） | 745 次（策略那路没跟着跳） |
| 静站与芯片倾斜差（最差 10s 窗口） | 中位 0.043° | 中位 0.026° |

两段不是轮流 A/B，现场差别太大直接定 `gyro`。**默认仍是 `chip`，要自己切 `bno08x_fusion="gyro"`**。

### 3.5 适用性判定（按代次/路径分开）

| 路径 | `gyro_fusion` 是否适用 |
|---|---|
| `hd1910m` 的 **BNO08x I2C** 输入（`bno08x.rs` 读 0x08） | ✅ **直接适用且高优先**：同一颗芯片、同一个 0x08 报告、同一类乱跳；我们的 `reference_native` 只 EMA 陀螺，不设防 |
| `DuckBuddy-main` / `hd1910m` 的 **LSM6DSV16X 总线板** 输入（板上 SFLP） | ❌ 不直接适用：融合在板上 STM32 做，host 只解码；故障模型是"块迟到/冻结"，靠 freshness + 门控，不是陀螺积分 |

---

## 4. 安装方向四元数机制（跨代次同构）

- fanhao：`hd1910-calibration.toml` 的 `[imu_mounts.<source>]`，**未 `verified=true` 的运动模式拒绝上力**。BNO085 默认 `[0.5,0.5,0.5,0.5]`（标量优先 w=0.5，注释"120° turn about (1,1,1)"，传感器 X左/Y上/Z前 → 躯干映射）。
- `hd1910m`：`installation.json` 的 `imu_mount_wxyz=[0.5,-0.5,0.5,-0.5]`，`imu_mount_basis` 明写 "Body XYZ = [sensor Z, -sensor X, -sensor Y]"；`bno08x.rs:113` `mul(q, mount_inv)`。
- `DuckBuddy-main`：`robotd-params` 的 `imu_axes`/`imu_pitch_trim_deg`/`imu_roll_trim_deg`，`SflpDecoder.mount`；`feetech.rs:319` 传入。
- 机制同构：**安装朝向四元数 + 确认门控**；数值不同是传感器安装朝向不同。装歪/碰歪 → 读数漂，必须重新校（fanhao `verify-imu` 或站 HOME 算偏差补四元数；我们 `imu_mount_sanity` / `verify_imu_chain.py`）。

---

## 5. 舵机调参（增益口径不可抄）

`IMU-MODULE.md` §4.1：
- `servo-parameters P D 转矩限制`，15 个舵机同一组；范围 **P 1–32、D 0–64、转矩限制 200–1000**。
- 存 `/etc/robot/feetech-ft5/servo-test-parameters.json`，内容 `{"kp":3,"kd":0,"torque_limit":700}`。
- **下次 HOME 上力时一次写进舵机 RAM 的 48 号起 4 字节（转矩限制低、高、P、D），再读回核对；不写 EEPROM**。卸力后恢复 P=上力前值、D=0、转矩限制=1000。
- 不设参数文件 = V167 原版（P=模型合同 5 / D=0 / 1000，与 control.43 逐字节相同）。
- V167 原版"修复鸭身抖动"：每次上力把 RAM 的 D 写成 0、转矩限制写成 1000。

**与我们部署线的差异**：kissqy 默认 **P5/D0/1000**，我们 `out/robotd_hd1910_mode0.toml` 是 `position_kp=16 / position_kp_head=16 / gain=200 / position_kd=8`。根因是 **gain 口径不同**——我们 `feetech.rs:236` `reg50 = clamp(round(gain·position_kp/200),1,254)`，且 `[policy] gain=200` 是 XL330 口径（写 8 会得 reg50=1 瘫软，toml §3-10 行明记这个坑）。kissqy 的 "P5" 是它自己的模型合同值，经它自己的映射 → 不等于我们的 reg50。**结论：数字不可抄，只抄"写 RAM 并回读核对 + 卸力恢复默认值"的机制**。

---

## 6. 门控对比（跨代次可借鉴）

| 维度 | `DuckBuddy-main` SflpDecoder | `hd1910m` Bno08x | fanhao HostImuGate |
|---|---|---|---|
| 启动期 | `ready()` = `quat_samples>=25`（~0.25s） | 首报到达 + 150ms 龄 | `HOST_IMU_SETTLE=1s` + epoch 重启跟随 |
| 老化/冻结 | median3 拒单点野值（`imu_median`，部署 toml 已关） | 150ms 龄 + 30ms gyro/quat 偏斜 | `HOST_IMU_MAX_AGE=50ms` + `HOST_IMU_REPEATS=3` 连续重复判冻结 |
| 跳变门控 | 无（板上 SFLP） | **无**（0x08 直接采信） | `gyro_fusion` 6° 倾斜门 |
| 阻塞控制循环 | 否（进 sync_read） | 否（reader 线程 + 时间戳） | 否（reader 线程解耦） |

**可借鉴**：① 对 BNO08x 路径补一个 `gyro_fusion` 式倾斜门控（最高优先）；② 对总线板路径补 `max_age` + `repeats`（我们的 `ready()` 只管启动期，不拒绝"板子活着但块迟到/卡住"）；③ `imu_median=false` 的决策与 fanhao "median 多 1 tick 延迟 >20ms 让走路失败"的教训一致（toml §86-98 已论证），验证关掉是对的。

---

## 7. 落地建议（按代次分开，别混）

**对 `DuckBuddy-main` 部署代次（当前 `robotd_hd1910_mode0.toml`）**
1. IMU = 总线 LSM6DSV16X 板，硬件路线无需改；fanhao 的 EasyEDA 工程 + `firmware/imu-source/` 是这块板的维修/重制一手参考（项目软件方案已引用）。
2. 门控可细化：在 `SflpDecoder` 外加 `max_age`/`repeats`（参考 `HostImuGate`），不阻塞控制循环。
3. **`gyro_fusion` 暂不需要**（板上 SFLP）。若实测 SFLP 走路也乱跳，再移植。
4. 增益只走我们的 `reg50=clamp(round(gain·position_kp/200),1,254)` + `position_kd=8`，不抄 P5/D0。

**对 `hd1910m` 的 BNO08x 输入路径**
1. 🔴 **上板第一检查项**：录 100Hz 原始 0x08 报告（fanhao `bno08x_raw_log` 有现成 CSV 机制，约 1MB/min、64MB 封顶），统计走路帧里 >5° 单 tick 跳变比例；若命中，就是 fanhao 描述的乱跳。
2. 若命中 → 移植 `gyro_fusion.rs`（纯算法、无依赖）做 host 陀螺积分姿态，默认 `gyro` 模式；注意它是**标量优先**四元数、`w≥0`，与 `bno08x.rs:88-92 normalized([w,x,y,z])` 顺序一致。
3. 顺带把 `sample()` 的 150ms 龄收紧到 50ms 量级并加 `repeats` 冻结判据（与 fanhao 对齐）。
4. `reference_native` 保留为陀螺 EMA（与 gyro_fusion 不冲突，一个管 gyro 平滑、一个管 quat 门控）。

---

## 8. 与既有 C1–C8 的回填

- **C1（总线 IMU 从机 ID200）**：对部署代次 = "已用"，参考价值降为**实物/固件维修参考**；对 hd1910m BNO08x 路径不适用。
- **C2（IMU 融合务必自做）**：具体化 = `gyro_fusion.rs` 倾斜门控（6°/0.66s/0.5s/5°·s⁻¹）+ BNO085 乱跳真机实证；**并新增一条真实风险**：我们 `hd1910m/bno08x.rs` 的 0x08 直接采信、`reference_native` 只 EMA 陀螺，不设防。
- **C-IMU（新增）**：`HostImuGate` 50ms/1s/3-repeats + reader 线程解耦，细化两代次的门控。
- **C-伺服（新增）**：P/D/转矩限制写 RAM 48–51 + 回读核对 + 卸力恢复；增益口径差异不可抄数字。
- **C4（obs 契约）**：`trunk_imu.rs` 把三种 IMU 统一进 `TrunkFrame`、policy 只看 obs —— 印证我们 obs 契约（gyro/gravity 进 obs）正确。
- **项目准则回填**：本次"只读一个 crate 就想推翻 MEMORY"再次命中 `MEMORY.md` 的「查全比查到更重要」与「plant 是一等坐标」——**IMU 类型、EEPROM 校验、增益口径都必须绑定 robotd 代次**。

---

## 9. 证据清单（repo:path）

**fanhao375/Microduck-kissqy@hd1910-v167-trunk-imu-i2c**
- `IMU-MODULE.md`（trunk IMU 三路线 + 调参 + UDP 手柄 + 10-15 上机实测）
- `hardware/IMU-TIMELINE.md`（总线板 ID200 / Dynamixel P2.0 → Feetech SCS / STM32G031+LSM6DSV16X）
- `microduck-hd1910/firmware/duck-control/src/trunk_imu.rs`（三路线统一 `TrunkFrame` + `HostImuGate` + reader 线程解耦）
- `microduck-hd1910/firmware/duck-control/src/gyro_fusion.rs`（陀螺积分融合算法、全部常量、50Hz 回放依据）
- `microduck-hd1910/firmware/duck-control/src/bno08x.rs`（BNO085 codec，0x08/0x02 报告）
- `hardware/ProPrj_imu_to_dxl_RevA_V1_2026-10-07.epro2`（总线板 EasyEDA 工程）

**我们 workspace**
- `microduck-software/.upstream/DuckBuddy-main/duck-control/src/imu.rs`（`imu_to_dxl v2` LSM6DSV16X 总线板，`SflpDecoder`）
- `…/DuckBuddy-main/duck-control/src/feetech.rs:138-149,168,316-319`（`IMU_DXL_ID` / `imu_mount` / `imu_median` / `SflpDecoder::new`）
- `…/DuckBuddy-main/duck-control/src/model.rs:164`（`IMU_DXL_ID=200`）；`…/robotd-params/src/registry.rs:122`（`bus.imu_median` 活键）
- `microduck-software/.upstream/hd1910m/microduck/duck-control/src/bno08x.rs:1,63-95,104-118,123-136,148`（BNO085 I2C / 0x08 直接采信 / gyro EMA / stale 门）
- `…/hd1910m/microduck/duck-control/src/feetech.rs:198-211`（`open_imu` + `set_reference_filter`）
- `…/hd1910m/microduck/duck-control/src/imu.rs`（同款总线板解码器）
- `microduck-software/.upstream/hd1910m/radxa/installation.json:5-6`（`imu_mount_wxyz`）
- `microduck-software/out/robotd_hd1910_mode0.toml:15-31,59-98,105-111`（绑 DuckBuddy-main 代次、`deny_unknown_fields`、`imu_median=false`、无 BNO08x 键）
- `docs/active/microduck-HD1910软件方案.md:68,96-101,788`（kissqy IMU 桥一手来源 + 寄存器契约 + IMU 规格）
- `docs/active/microduck-upstream-对照-2026-11-08.md:73,118,161`（代次区分）
