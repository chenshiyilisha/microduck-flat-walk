# 三个 MicroDuck 开源硬件项目研究（f9420 / avanx / team_wijnbslh）

_日期：2026-11-08 · 延续「先查一手资料、带出处」的 fact-check 纪律_
_取数方式：立创页 WebFetch + GitHub API 元数据 + codeload tarball（raw/clone 被代理 502，走 codeload）_

---

## 0. TL;DR 与关键修正

1. **项目 2 / 3 不是我们机器人的硬件**：它们是 **ft1910（官方）线** 的 LSM6DSV16X 总线 IMU 板。我们的 **HD-1910（hd1910m）线用的是 BNO08x（I2C）IMU**，不是它。两者是「同机器人本体、不同 IMU 架构」的表亲。
2. **项目 1 正好是我们要的**：它适配 **Radxa ZERO 3W**（我们记忆里「零改动最优 SBC」），是计算 + 电源扩展板。
3. **记忆要纠正**：`[bus] imu_median = false`（「故意偏离上游默认 true」）在整仓搜不到任何消费点；ft1910 `imu.rs` 的 `median3_each` 是**无条件**应用。该条目无当前上游依据。
4. `row[2..5] == [0,10,31]` 是**舵机 EEPROM 元数据校验**（HD1910M mode-4），不是 IMU 型号。

---

## 1. 三个项目分别是什么 + 与我们的对应

### 1.1 `f9420/project_zdvhlzkd` = **microduck-ext**
- **Radxa ZERO 3W 扩展板**（= 我们的 SBC！）。集成：2S 锂电池供电（AP63205 降压→5V，舵机电源带保险丝/MOS/储能电容）、3 个共用 DATA 总线的**总线舵机**接口（半双工）、ES8311 音频编解码（I²S+I²C）+ NS4150B 功放 + 模拟麦、40Pin 接 Radxa、引出 UART/I²C。
- 约 **30×65 mm 四层 PCB**。开源协议 **GPL 3.0**（可复用，须保留版权）。
- 创建 2026-09-15，更新 2026-10-27。立创页的「设计图/BOM」为空（**原理图未上传**，只有文字说明）。
- **对应**：我们 hd1910m 线的「计算 + 电源 + 音频 + 舵机总线」一体板。复刻/升级机器人控制器时直接参考。

### 1.2 `avanx/project_whiijerp` = **MicroDuck IMU_to_DXL**
- 身体 IMU 板，做成 **Dynamixel 半双工总线从板**（`imu_to_dxl`）。Apache 2.0。
- 固件仓 `github.com/avanx/microduck_imu_to_ttl`（master，2026-10-01）：含完整 MCU 固件、工具 `scs_imu_gui.py`、**`docs/datasheet/HD-1910-C001串型规格书`**（我们机器人的舵机规格书！）+ `ST-LSM6DSV16X.pdf`。
- 作者**反向工程了我们的 `duck-control/src/imu.rs`** 的安装旋转与躯干坐标（见 §4）。
- **对应**：ft1910（官方）线 IMU 板（LSM6DSV16X on bus）。

### 1.3 `team_wijnbslh/project_jhgdebrg` = **imu_to_servo（microduck imu 模块）**
- 基于 **STM32G031F8P6 + LSM6DSV16XTR** 的 Feetech / DYNAMIXEL TTL 半双工**总线 IMU「伪舵机」节点**。复刻成本 **¥40**。CERN-OHL-S-2.0（强硬件开源，可制作/再分发）。
- **两种总线版本都已实物验证**（Feetech 版 + DXL 版，同核心电路）。附件含固件源码/烧录文件/说明（DXL V1.0 用 Dynamixel Protocol 2.0；Feetech v0.1 同步读取需「舵机在前、IMU 在后 [1,200]」，反向顺序仍报错，独立冷启动未验证）。
- 3D 模型 `imu_to_feetech.step`（152 下载）/ `imu_to_dynamixel.step`。
- **对应**：ft1910（官方）线 IMU 板（**Feetech 版**，比 avanx 更贴近我们 feetech 总线）。

> **项目 2 与 3 的关系**：avanx 的固件仓（AT32F425 + LSM6DSV16X + 飞特 SCS）是更完整/权威的参考资料（含舵机规格书）；team_wijnbslh 的 STM32G031 版是另一个 MCU 实现、已双总线实物验证。两者架构相同，都是 ft1910 线的 IMU 板。

---

## 2. 权威 IMU 规格（来自 avanx 固件仓 `firmware/docs/interfaces.md`，已 codeload 核实）

| 项 | 值 |
|---|---|
| MCU | AT32F425K8U7-4（8 MHz→96 MHz PLL） |
| IMU | **LSM6DSV16X**，`WHO_AM_I(0x0F)=0x70`；SPI 模式3，~6 MHz |
| 陀螺仪 | ODR 120 Hz，±500 dps，**17.50 mdps/LSB**（主机 `rad/s = count·0.0175·π/180`） |
| 加速度 | ODR 120 Hz，±4 g，0.122 mg/LSB（只给诊断，控制环不读） |
| SFLP | 芯片内嵌游戏旋转向量，120 Hz，FIFO 标签 `0x13`，6 字节小端半精度 |
| 总线 | **飞特 SCS**（TTL 半双工）；出厂 **ID=200**、**1 Mbps** |
| 指令 | PING 0x01 / READ 0x02 / WRITE 0x03（仅 addr5=ID、addr6=波特率）/ SYNC READ 0x82（广播 0xFE + ID 列表） |
| 帧格式 | `FF FF | ID | LEN | INST | PARAM… | CS`（`LEN=参数+2`，`CS=~(ID+LEN+INST+PARAM)` 低8位） |
| 控制表 | addr3=型号 **0x4955**（小端 55 49）；addr5=ID(200)；addr6=波特率枚举 |
| **IMU 块** | **addr 124 起 20 字节**，主机每拍只读**前 12 字节**（READ_ADDR=124 / READ_LEN=12）：`124` gyro X i16、`126` gyro Y、`128` gyro Z、`130` SFLP-X half、`132` Y、`134` Z；后 8 字节（accel 6 + 采样计数 u8 + 状态）仅诊断 |
| 状态字节 | bit0=传感器在线 / bit1=收到过 SFLP / bit2=陀螺或加速有效输出 |
| 同步读排队 | IMU 在 ID 列表第 k 位则先等前 k 个完整应答（每槽超时 2 ms）；**故 IMU 必须排最后 [1,200]** |

> 120 Hz 采样 vs 50 Hz 总线读取，使相邻两次 12 字节读数通常不同，避免被主机当成「姿态卡住」。SFLP 未输出时 6 字节保持 0，主机据此保留上一帧姿态（与 `imu.rs` 完全一致）。

---

## 3. 与我们代码的逐项对齐 / 修正（带出处）

### 3.1 ft1910 `imu.rs` / `bus.rs` 与 avanx 规格精确吻合
- `imu.rs:78-83` `DEFAULT_MOUNT=[√½,0,√½,0]`（绕 Y +90°）、`:29` `gravity=[0,0,-1]`、`:48` `GYRO_RAD_PER_LSB=0.0175·π/180`、`:149-150` 无条件 `median3_each`（gyro+gravity）、`:99` `ready()` 需 `quat_samples>=25`、`IMU_BLOCK_LEN=12`、块布局（gyro i16 + SFLP half）与 §2 完全一致。
- `bus.rs:36` `READ_ADDR=124`、`:119` `imu: SflpDecoder`、`:452`「`imu_to_dxl` board is `id 200` on this bus」。

### 3.2 ⚠️ 修正 1：我们的 IMU 是 BNO08x（I2C），不是 LSM6DSV16X 总线板
- `hd1910m/microduck/duck-control/src/feetech.rs:203` `open_imu`：`Bno08x::open(&cfg.imu_bus, cfg.imu_address, installation.imu_mount_wxyz)` + `:205` `set_reference_filter(cfg.reference_native)`。驱动在 `bno08x.rs`。
- **结论**：HD-1910（hd1910m）线 = Feetech SCS 舵机（EEPROM 元数据校验）+ **BNO08x I2C IMU**（带安装四元数 `imu_mount_wxyz`、参考滤波 `reference_native`）。项目 2/3 的 LSM6DSV16X 总线板属于 ft1910（官方）线，不是我们机器人的硬件。

### 3.3 ⚠️ 修正 2：`row[2..5]==[0,10,31]` 是舵机元数据，不是 IMU 型号
- `hd1910m/.../feetech.rs:693` `|| row[2..5] != [0, 10, 31]` 在 `open_with_imu` 内，校验的是**舵机 EEPROM 的型号/版本元数据**（HD1910M mode-4 的一部分）。IMU 型号 0x4955 只在 avanx 固件仓出现，我们 robotd 不靠它识别 IMU（BNO08x 走 I2C 独立枚举）。

### 3.4 ⚠️ 修正 3：`imu_median` 配置在整仓不存在
- 全仓（含 toml/配置）`grep imu_median` 无命中；ft1910 `imu.rs` 的 `median3_each` 无条件执行。记忆条目「`[bus] imu_median = false`（上游默认 true，故意偏离）」**在当前上游无依据**——可能混淆了 hd1910m BNO08x 的 `reference_native` 滤波，或来自旧版本。需从项目记忆中纠正。

### 3.5 速度标度再印证
- `hd1910m/.../feetech.rs:958` `signed([row[2],row[3]]) * 0.732 * TAU`（rad/s）= 0.732 rpm/count × 2π，与社区 `hls_probe.py` 的 `signed(speed)*0.732`（rpm）一致。

---

## 4. 躯干坐标 / 安装旋转（avanx 反推，已用 `imu.rs` 验证）

- **trunk 坐标系**：X 前、Y 左、Z 上（右手系）；直立 `gravity=[0,0,-1]`（`imu.rs:29`）。
- **安装旋转**：芯片相对躯干**绕 Y 轴 +90°**，即 `trunk=[+raw_z,+raw_y,−raw_x]`（`imu.rs:76-77`），对应 `DEFAULT_MOUNT=[√½,0,√½,0]`（`imu.rs:78-83`）。
- **IMU 安装位置**（来自 `microduck_rl` 仿真）：`robot_walk.xml` 的 `trunk_base` 内 `imu` site，`pos=(-0.021, +0.0000664, -0.0146984) m`、单位四元数 → 相对躯干原点**向后 21 mm、正中矢状面、向下 14.7 mm**，位于 `power_support`（电池舱支架）前板面。仿真 `imu` site 的 quat 为单位（IMU 按 trunk 对齐建模），实机 90° 安装差由 `DEFAULT_MOUNT` 在解码端补齐，使两端落入同一约定。
- 这些是 **MicroDuck 通用坐标约定**，无论 BNO08x 还是 LSM6DSV16X 都适用；`live_viewer` / 任何 IMU 显示都应据此解释重力向量与角速度。

---

## 5. 可借鉴 / 不可借鉴 + 许可

| 项目 | 许可 | 可复用性 |
|---|---|---|
| microduck-ext（项目1） | GPL 3.0 | 可复用（须保留版权）；但设计图/BOM 未上传，只有文字 |
| IMU_to_DXL（项目2） | Apache 2.0 | 可自由使用/修改/再分发；固件仓含权威 MCU 固件+舵机规格书 |
| imu_to_servo（项目3） | CERN-OHL-S-2.0 | 强硬件开源，可制作/再分发 |

**可借鉴：**
- 项目 1：Radxa ZERO 3W 的 2S 供电 + 舵机半双工 + 音频一体板设计（若升级机器人控制器）。
- 项目 2/3：若评估/复刻 **ft1910 线的总线 IMU 板**，avanx 固件仓是**权威起点**（AT32F425 + LSM6DSV16X + 飞特 SCS + `scs_imu_gui.py` 调试工具 + HD-1910 舵机规格书）。
- §4 的躯干坐标/安装旋转是通用约定，可直接用于 IMU 数据显示。

**不可直接套用到我们的机器人：** 项目 2/3 的 LSM6DSV16X 总线板对应 ft1910 线；我们 hd1910m 线是 BNO08x（I2C），改我们机器人要走 `bno08x.rs` + `imu_mount_wxyz`，不是这块板。

---

## 6. 建议

1. **纠正项目记忆**：①「HD-1910 = BNO08x I2C IMU，非 LSM6DSV16X 总线板」；②删/改「`[bus] imu_median=false` 故意偏离」条目（当前上游无 `imu_median`）；③`row[2..5]==[0,10,31]` 标注为舵机元数据校验。
2. `live_viewer.py` 补 `safety.gravity`（直立≈[0,0,-1]，按 §4 trunk 坐标解释）+ `imu` 健康（两条线共用 `robot.state` 接口面）。
3. 若未来评估 ft1910 线或复刻 IMU 板，avanx 仓为权威参考；要改我们机器人则走 BNO08x 路径。
4. 项目 1 的 Radxa 扩展板设计图未公开，若要评估需联系作者或在立创编辑器查看。
