# 泰山派 MicroDuck 扩展板（BMI088 HAT）研究

_日期：2026-11-08 · 研究者：延续 microduck-upstream-对照 的 fact-check 纪律_
_一手来源：_
- 立创开源页 `https://oshwhub.com/liubin6320884/project_mwixoamq`（标题「泰山派MicroDuck 扩展板」，CC BY-NC 4.0，复刻成本 ¥80，创建 2026-09-30，更新 2026-10-29）
- GitHub `https://github.com/Fisheatingcats/microduck_tsp_hat`（作者 WestTower / Fisheatingcats，1 star，单 commit 2026-10-27，**仓库无 LICENSE → 代码默认保留所有权利**）

> 取数方式：立创页 + GitHub API 元数据 + codeload tarball（`raw.githubusercontent.com` 与 `git clone` 都被本地代理 502 挡，按纪律走 codeload）。已解包到本地逐文件核对。

---

## 1. 这是什么

为 **泰山派（RK3566）Linux 开发板** 适配 MicroDuck 的 RobotHat：

- 在机器人**背部直接集成一颗 BMI088 六轴 IMU**（作者原话「省掉一个 IMU 板」），舵机驱动与 IMU 采集一体。
- 硬件开源 CC BY-NC 4.0（**不得商用**）；软件（Python/Rust）**仓库未声明 LICENSE，默认全保留权利**，复用需先联系作者授权。
- 软件栈是「**采集服务 + 桌面站 + 只读舵机探针**」三件套，不是单一固件。

---

## 2. 系统架构

```
BMI088 (I2C, 默认 /dev/i2c-2)
   │  原生 Rust 二进制 bmi088_stream 独占 I2C（flock 锁）
   ▼  NDJSON 每行一帧采样
bmi088_server.py
   ├─ LAN HTTP + NDJSON 接口（:8765, Bearer Token 认证）
   └─ 本地 UNIX socket broker  /run/tsp-hat-bmi088.sock
        ├─ robotd-taishanpi  作为 "robot client" 订阅（robotd 据此得到 IMU）
        └─ 桌面站 imu_station.py（泰山派自带 LCD，PyQt6 / linuxfb）
```

- **HAT 不驱动舵机**：`hls_probe.py` 注释写明「Read-only FT-HLS/HD1910 UART probe. Sends only PING(1) and READ(2)」「HAT 自动切换单线方向，无需 RTS 翻转」→ 舵机由 robotd 自己开 UART 驱动，HAT 只做诊断/IMU。
- systemd 服务 `tsp-bmi088.service`：`ExecStart=/usr/bin/python3 /opt/tsp-hat/bmi088_server.py`，`Restart=on-failure`，`ProtectSystem=full`，只写 `/etc/robot`、`/run`。

---

## 3. 对我们项目最有价值的发现（带出处）

### 3.1 robotd 的 IMU 接口面（与我们的 robotd **共用**，不只是该作者自加）

`verify_robotd_imu.py`（其集成测试）揭示了 robotd 真实契约：
- `robot.subscribe({"hz":20})` → `robot.state` 帧含 **`safety.gravity`**（体坐标重力 3 向量 = IMU 数据落点）。
- `robot.health` RPC 返回 **`imu.consecutive_stale_blocks`**（过期块计数）。
- 它断言：`robot.state.safety.gravity` 与 broker 的 `s['gravity']` 在 **1e-12** 内一致 → robotd 直接透传 broker 重力。
- 负对照：把采样进程 `SIGSTOP` → `age_ms>100` 且 `ready=False` 且 `consecutive_stale_blocks>0`（IMU 健康退化）；`SIGCONT` 后恢复 → **这是现成的「IMU 断流」自检模板**。

**已在我们的 `duck-control` 源码正面印证**（不是该作者的私货）：
- `imu.rs:32` `pub gravity: [f64;3]`；`imu.rs:41` 默认 `[0.0,0.0,-1.0]` → **直立时重力指向 -Z（体坐标 Z 向上）**，正是我们的坐标约定。
- `safety.rs:266` `gravity[2] > fall_gravity_z(-0.5)` → 跌倒判据用重力 Z 分量；`safety.rs:72` `fall_gravity_z: -0.5`（与本项目记忆一致）。

> **结论**：`robot.state.safety.gravity` 是 robotd 通用接口。我们 `tools/hd1910/live_viewer.py` 目前只画关节，**应补上 `safety.gravity`（体坐标重力向量）+ `imu` 健康**，利用共用的接口面，无需改 robotd。

### 3.2 策略 61 维布局确认

`imu_station.py:327` 注释原文：「策略输入保持原来的 61 维布局：**前 3 维为机身角速度 rad/s，接下来 3 维为重力单位向量**」。
→ 与本项目记忆「obs 61 / act 14 / IMU 供前 6 维（3 角速度 + 3 重力）」完全吻合。

### 3.3 板端 EKF + 无磁力计 → Yaw 漂移

同注释：`板端采用姿态误差状态 EKF；加速度模长或方向创新异常时拒绝该次重力修正。只有六轴，没有磁力计，绝对航向不可观测；Yaw 会漂移。`
→ 解释了我们为什么没有可靠绝对航向（与 heading 奖励 A/B 那段讨论一致）。

### 3.4 `gyro_lpf_hz` 默认 0（低通关闭）→ 印证我们 `[bus] imu_median = false` 的刻意偏离

`imu_station.py:327`：「**角速度额外低通默认关闭（gyro_lpf_hz=0）。启用后训练侧也应复现噪声、滤波和时延**。」
→ 正面印证本项目记忆：`[bus] imu_median = false`（上游默认 true，我们**故意偏离**）——上游 `imu.rs:150` 确实有 `median3_each(&self.gravity_history, gravity)` 三样中值；我们关掉它，因为训练侧 IMU 是尽量原始的（延迟包络 0–20ms），额外滤波/时延必须训练侧复现，否则分布错位。

### 3.5 BMI088 I2C 启动（可复用参考实现）

`tools/bmi088.py`（纯标准库，无第三方依赖）：
- `i2c-dev` + `I2C_RDWR` ioctl 组合传输（带 repeated START），accel `0x19` / gyro `0x68`（默认）。
- 配置：accel 200 Hz / ±6 g，gyro ±500 °/s / 200 Hz / 64 Hz 带宽（寄存器与 BST-BMI088-DS000-19 对应）。
- 独占 `flock` 锁：「IMU bus is owned by robotd or the calibration service」——**单进程独占 I2C**，与 server 经原生二进制持有总线的设计一致。
- 标定 schema（`calibration.example.json`）：`accel_matrix`/`accel_offset_g`/`gyro_matrix`/`gyro_bias_rad_s`/`sensor_to_body`（3×3 安装旋转）+ `gyro_calibrated`/`accel_calibrated`/`mount_confirmed`/`gyro_lpf_hz`。

> 若将来在 HD-1910（Radxa）或别的小板带 BMI088，这份 stdlib-only 驱动是现成起点（`scan()` 只读 CHIP_ID 不瞎配，值得照抄）。

### 3.6 HD1910 舵机总线约定 — 第三方独立实现的交叉印证

来自 `hls_probe.py`（只读 PING/READ，社区独立实现，非我们的 robotd）：
- `speed_rpm = signed(speed) * 0.732` → **印证本项目记忆的速度标度 0.732 rpm/count** ✓
- 寄存器 `56..70`（15 字节）布局：position(2)/speed(2)/load(2)/voltage(1)/temp(1)/async_flag(1)/status(1)/moving(1)/goal_position(2)/current(2) → 与 `feetech.rs` 反馈寄存器一致 ✓
- 默认 UART `/dev/ttyS3`、baud `1000000` → **印证本项目记忆：泰山派设备树用 ttyS3（另一变体 ttyS2）** ✓

⚠️ **position_rad 符号争议（需以我们的 `feetech.rs` 为权威核实，勿照抄 probe）**：
- `hls_probe.py`：`position_rad = π − position*2π/4096`（无符号 0..4095 假设）。
- 本项目记忆 `bus.rs:543`：`position_rad = 2π·position/4096 − π`（正好反号）。
- **权威真相**：`feetech.rs:389` `position_rad()` = `position_raw_to_counts(le_u16(low,high)) * RAD_PER_COUNT`，且 `飞特通讯协议说明.md:510` 明写「**BIT15 为方向位**」解读位置字段。即我们的 robotd 用**有符号**解读，与 probe 的无符号假设 origin/符号约定不同。
- 处置：hls_probe 的**标度（2π/4096）量级**可作交叉校验，但其**符号/origin 不可直接采信**；我们 robotd 的 `feetech.rs` 才是唯一权威。

---

## 4. 与我们两条线的对应关系

| 维度 | 本 HAT（泰山派线） | 我们 HD-1910（Radxa）线 |
|---|---|---|
| SBC | 泰山派 RK3566（ttyS3 / i2c-2） | Radxa（hd191m 线） |
| IMU 架构 | 分离式 BMI088，I2C + socket broker 喂 robotd | IMU 在 feetech 舵机总线上，`feetech.rs::open_with_imu`（row[2..5]==[0,10,31] 等） |
| 舵机驱动 | robotd 开 UART（HAT 只诊断） | robotd 开 UART（feetech_hls / 500k） |
| robotd IMU 接口面 | `safety.gravity` + `health.imu` | **同一套**（duck-control 共用），可直接复用 |

> 本项目记忆已确认泰山派（LCKFB-TSPI-RK3566）完成 MicroDuck 移植，本 HAT 的 `i2c-2` + `ttyS3` 与其中一设备树变体吻合，是社区对该移植的「IMU+诊断」配套板。

---

## 5. 可借鉴 / 不可借鉴

**可借鉴（思路/参考，不改其代码）：**
1. `robot.state.safety.gravity` + `health.imu` 的对接模式 → 给 `live_viewer.py` 补重力向量与 IMU 健康显示。
2. `verify_robotd_imu.py` 的负对照集成测试写法（停采样器→age>100→health 坏→恢复→断言）→ 可作为我们硬件端到端复核的「IMU 断流」用例模板。
3. `bmi088.py` 的 stdlib-only I2C 启动 + 只读 CHIP_ID 的 `scan()`。
4. 标定 schema（`sensor_to_body` / `gyro_matrix` / bias）→ 我们的 IMU 标定可对齐字段。

**不可直接抄：**
1. **许可风险**：代码无 LICENSE（默认全保留）；硬件 CC BY-NC 4.0（不可商用）。**任何 `.py`/`.rs` 复用前必须先联系作者授权**。
2. 我们的 robotd 是自有 Rust 实现、IMU 走 feetech 总线而非 socket broker；架构不同，不能直接接它的 broker。

---

## 6. 建议行动

1. **`live_viewer.py` 补 `safety.gravity`（体坐标重力，直立≈[0,0,-1]）+ `imu` 健康**：纯消费共用的 `robot.state` 接口面，零改 robotd。
2. **把 hls_probe 的 0.732 标度与寄存器 56..70 布局** 作为 `hardware_endtoend_check.py` / `audit_robotd_toml.py` 的交叉校验基准（第三方独立实现印证我们的总线约定）。
3. **`position_rad` 符号**：以 `feetech.rs:389`（BIT15 有符号）为权威，不要采纳 hls_probe 的无符号反号公式。
4. **BMI088 参考**：若未来在别的小板带 BMI088，`bmi088.py` 是现成 I2C 起点（仍需授权）。
5. **许可**：若确要复用其任何代码，先联系 WestTower / Fisheatingcats 取得书面授权（当前默认全保留权利）。
