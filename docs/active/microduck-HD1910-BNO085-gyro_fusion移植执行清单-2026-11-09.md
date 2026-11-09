# HD-1910 / BNO085 `gyro_fusion` 移植执行清单（2026-11-09）

> 状态：**真机阶段执行手册，当前不改一行代码**。现状是台架 PC + URT-2 + 单舵机，无机器人、无 BNO085 上板；软件 0 成本但改的是 vendored 上游源码，按「改上游只纯新增」准则，先在文档里把插入点和负对照钉死。
> 源码依据：`fanhao375/Microduck-kissqy@hd1910-v167-trunk-imu-i2c`（GitHub API `contents` + base64 逐个读）＋本地 `.upstream/hd1910m/microduck/duck-control/src/`。
> 姊妹文档（研究篇）：`microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md`。

---

## 0. 🔴 适用边界：代次 + 输入路径绑定（写错就是反向结论）

| robotd 代次 | 绑定 | IMU 输入 | 本清单适用? |
|---|---|---|---|
| **`hd1910m/microduck`**（Radxa / FT-SCS / 固件 `row[33]==4`） | 上游原机；`installation.json:5` 有 `imu_mount_wxyz` | **同时保留两条**：`bno08x.rs`（BNO085 I2C SH-2，`feetech.rs:203-207` 的 `open_imu`）与 `imu.rs`（总线 `imu_to_dxl v2` 板解码器） | ✅ **只这条线的 BNO08x 输入路径** |
| `DuckBuddy-main`（OrangePi / HL-2915 / `feetech_hls` / 500k / EEPROM reg6=1,reg33=0 硬校验） | **`out/robotd_hd1910_mode0.toml`**（其注释 §69-77/§105-111 自述，且**不含任何 BNO08x 键**） | 总线 `imu_to_dxl v2`（LSM6DSV16X，ID 200），`SflpDecoder`，板上 SFLP 自带陀螺 bias 估计 | ❌ **不装 gyro_fusion**（芯片自己融合，装了是重复纠偏） |

⇒ 凡谈 IMU 融合 / EEPROM 校验 / 增益口径，先问「哪一代 robotd + 哪条输入路径」。上轮只读一个 `imu.rs` 就差点写反结论，这条是本清单第一门禁。

---

## 1. 为什么做（风险已实证，不是推测）

- BNO085 的 `0x08 game-rotation` 在走路时**单 20ms tick 跳 20–60°**，而校准过的陀螺 `0x02` 说躯干几乎没动。kissqy `gyro_fusion.rs:4-9`：50Hz 真机录像里走路帧命中 1.9–23%（视脚垫）、站立 0.05%；陀螺、腿部运动学、摔倒记录三者一致 ⇒ 是芯片融合出错，不是机器人在动。
- `gravity` 正是策略观测量与跌倒判据（`imu.rs:38-41` 的 `ImuData` 注释明写）⇒ 跳变 = 策略被突然告知「你在倒」。
- 🔴 **我们这条路径原样吃进跳变**：本地 `hd1910m/.../bno08x.rs:87-95` 对 0x08 **只做 `normalized()` 后直接存 `self.quat`**；`sample():113-117` 直接拿它算 `trunk`/`gravity`。
  - `reference_native` **不是**融合：`bno08x.rs:76-79` 只对**陀螺**做半衰 10ms 的 EMA（测试 `:123-137` 证明 1.0→0.5→0.5→0.125），四元数无门控。
  - `sample():107-111` 只管 150ms 龄 + 30ms 两报告偏斜 ⇒ 一个 20ms 内的大跳**完全合法通过**。
- 对照效果（kissqy `IMU-MODULE.md`）：`chip` 模式推摇杆 9s 摔 2 次，`gyro` 模式 60s 零摔。

---

## 2. 现状盘点：我们已有什么（决定这是「小改」而非搬整套架构）

| 能力 | 我们已有 | kissqy 对应 | 结论 |
|---|---|---|---|
| 独立 IMU reader 线程，控制线程不阻塞 I2C | `bno08x.rs:188-193` spawn `bno085` worker，`supervise()/run():269-405` | `trunk_imu_i2c.rs` 独立 reader + `HostImuGate` | ✅ 已有，**不搬** |
| 100Hz 订阅 0x02/0x08 | `run():353-359` 写 `10_000u32`（µs） | `bno08x.rs:65` `REPORT_INTERVAL_US=10_000` | ✅ 周期一致，`dt = step × 0.01s` 可直接用 |
| 报告序号 + 去重 | `fresh():42-44` `(1..128).contains(&next.wrapping_sub(p))`，`parse():74/:87` 各存 `(value, seq, Instant)` | `SEQUENCE_BACKWARDS=128`、`:463-514` | ✅ 判重已等价；**缺 step→dt 换算** |
| 单位 / 分量顺序 | gyro Q9 `/512`（`:75`）、quat Q14 `/16384`（`:89-92`），scalar-first `[w,x,y,z]` | `QUAT_SCALE=16384`/`GYRO_SCALE=512`（`:68-69`）、`grv_quat():327-333` 返回 `[w,x,y,z]` | ✅ 数值口径一致；⚠️ kissqy 强制 `w≥0`（`:332`），我们 `normalized()` 不强制 |
| 遥测钩子 | `report_stats():226-235` 返回 `json!`，`feetech.rs:449` 挂到 `value["imu_transport"]`，`imu_only.rs:44/76` 也用；`robotctl` 已有 `consecutive_stale_blocks`（`main.rs:725`） | `HostImuHealth.fusion` / `RawLogHealth` | ✅ **Phase 0 零新增 IPC** |
| 配置结构 | `feetech.rs:29-43` `Config`，**`#[serde(deny_unknown_fields)]`**；`load_config():89-99` 用 `serde_json::from_slice` | `[trunk_imu] bno08x_fusion`（`trunk_imu_i2c.rs:25/:51-56`） | ⚠️ 见 §4 |
| 融合核心 / 测试 | ❌ 无 | `gyro_fusion.rs` **1363 行**（核心 ~497 + 19 个单测 + 4 份 CSV replay 的 Python 比对） | 需搬 |
| 门控 | 150ms 龄 + 30ms 偏斜（`sample():107-111`） | `HOST_IMU_SETTLE=1s` + 50ms 龄 + 1s 稳定 + 3 次冻结判定 | 暂不搬（§7） |

**配置链路已当场查清**（不是「待去找」）：入口 `robotd --port "feetech:<path.json>"`（`robotd/src/main.rs:1128-1133`）或 `imu:<path.json>`（`imu_only.rs:104` 测试用 `"imu:unused.json"`）；`path` 指向 **JSON**（`load_config():90` 与 `imu_only.rs:8` 都是 `serde_json::from_slice`），`Config.installation` 是相对该 JSON 的另一个 JSON（`installation.json`）。`deploy/robotd.toml` 的 `[bus] port`（`:15-19`）只是上层启动参数，**不是** `Config` 的载体。

---

## 3. 分阶段决策（每阶段有门禁，过不了就停）

```
Phase 0  最小观测（只加计数，不改姿态输出）  → 回答「我这颗到底跳不跳」
   │ 门禁：真机走路 >1% 的 tick 出现 >5° 单步跳 ⇒ 风险成立；站立 ≈0
   ▼
Phase 1  搬 gyro_fusion，mode 默认 chip（行为不变），A/B 可切 gyro
   │ 门禁：19 单测 + 4 CSV replay 全绿；5 条负对照能删红
   ▼
Phase 2  上板 A/B 验收与调参（6° / 0.66s / 0.5s / 5°·s⁻¹ 是否适配我们这颗）
```

Phase 0 若显示不跳 ⇒ **不进 Phase 1**，省掉 1363 行改动（fanhao 的芯片是个例，不能默认我们这颗同样）。这就是「读数先于结论」。

---

## 4. Phase 0：最小观测（零新依赖、零 IPC 改动）

**改动位置**：`hd1910m/microduck/duck-control/src/bno08x.rs`，纯新增字段与统计，不动 `sample()` 输出。

1. `Reports`（`:19-29`）新增：`last_chip_gravity: Option<[f64;3]>`、`chip_reports: u64`、`jumps_gt5: u64`、`jump_max_deg: f64`。
2. `parse()` 的 0x08 分支（`:87-95`）在 `q` 归一化之后：算 `gravity(q)`，与 `last_chip_gravity` 用 **`atan2(|a×b|, a·b)`** 求夹角（照抄 kissqy `gyro_fusion.rs:452-478` 的 `gravity()`/`angle_deg()`，别用 `acos`，近零不稳）；`>5°` 则 `jumps_gt5 += 1`，更新 `jump_max_deg`。
   - ⚠️ 这段必须放在 **`fresh()` 通过之后**，否则重复 seq 会重复计数（`fresh():42-44`）。
   - ⚠️ 不要顺手改 `normalized()`：它不强制 `w≥0`，而 `q` 与 `−q` 是同一旋转，`gravity` 相同 ⇒ 统计不受影响。
3. `report_stats()`（`:226-235`）的 `json!` 加三个字段：`chip_reports`、`jumps_gt5`、`jump_max_deg`。unchanged 的 `feetech.rs:449` / `imu_only.rs:44/76` 会自动透出。
4. **观测命令**：`robotctl monitor --json` 读 `feedback.imu_transport.*`；健康侧看 `robotctl health --json` 的 `consecutive_stale_blocks`（记忆：monitor 无 health，两者独立）。
5. **判据**：站立 60s `jumps_gt5 / chip_reports` 应 ≈0（参考 0.05%）；正常走路若 >1%（参考 1.9–23%）⇒ 风险成立，进 Phase 1。

**负对照（必做，且要能删红）**
- 注入两帧相差 30° 的合法 0x08 报文（构造参考本地 `:421` 与 `:459` 的 fixture，注意 **`fresh()` 要求 seq 递增**，第二帧 seq 必须 +1）⇒ `jumps_gt5` 必须恰好 +1；删掉第二帧 ⇒ 必须为 0。
- 🔴 **阈值负对照**：把 `5.0` 改成 `1e9` 后注入同样两帧，`jumps_gt5` 必须不变。只见过绿色断言不算证据；这条专门防「把字面量搬了家但门没接上」。
- 用 `home-still.csv`（kissqy replay）回放，`jumps_gt5` 应为 0；用 `walk-glitch.csv` 回放应 >0。**两个数据集都要红/绿分明**，否则统计口径错了。

---

## 5. Phase 1：移植 `gyro_fusion.rs`（默认 chip，行为不变）

### 5.1 搬什么 / 不搬什么
- ✅ 搬 `gyro_fusion.rs:44-495`（类型、常量、`GyroFusion`、数学函数）到 `duck-control/src/gyro_fusion.rs`，`lib.rs` 加 `pub mod gyro_fusion;`。
- ✅ 搬 `:497-1362` 的 19 个 `#[cfg(test)]` 测试 + 4 份 `test-data/bno08x-fusion-replay/*.csv`（列头 `t,policy,limp,fallen,push,qw,qx,qy,qz,gx,gy,gz`，见 `walk-glitch.csv:6`）。测试的 Python 参考比对齐（`:1203 near()` / `:1224 like_python()`）一并保留。
- ❌ 不搬 `trunk_imu.rs` 的三路线架构（我们只有一条 BNO08x 输入）、不搬 `HostImuGate`、不搬 `trunk_imu_raw_log.rs`（理由见 §7）。

### 5.2 常量对齐（逐项核，别照抄数值）
| 常量 | kissqy | 我们 | 动作 |
|---|---|---|---|
| `REPORT_PERIOD_S` | `10_000µs/1e6 = 0.01`（`:74`） | `run():356` 写 `10_000u32` | ✅ 直接 `0.01` |
| `GYRO_BRIDGE=3` / `SEQUENCE_BACKWARDS=128` / `GYRO_GAP_HOST=100ms` / `GRV_MAX_STEPS=10`（`:76-85`） | — | `fresh():43` 已是 `(1..128)` | ✅ 等价，补 step 换算 |
| `GATE_DEG=6` / `TILT_TAU_S=0.66` / `REALIGN_AFTER_S=0.5` / `CALM_RATE_DEG_S=100` / `FOLLOW_S=1.0` / `STILL_RMS_DEG_S=30` / `SLEW_DEG_S=5` / `MAX_STEP_S=0.1` / `WINDOW_S=0.5`（`:50-69`） | 50Hz replay 初调值，注释 `:39-42` 明说「**要由真机 100Hz 原始报告日志重定**」 | 无 | ⚠️ 先原样搬，**标注「待 Phase 2 用我机数据重定」**，不得当成已验证真值 |
| `MAX_RATE_RAD_S=120` | Q9 `i16` ⇒ ±64 rad/s，超过即非读数（`:70-71`） | 同 Q9 | ✅ 一致 |

### 5.3 接入点（精确到函数与行）
1. `Reports` 新增 `fusion: GyroFusion`、`mode: FusionMode`、`last_gyro: Option<(u8, Instant)>`、`last_grv: Option<u8>`、`counts: FusionCounts`、`disabled: bool`。
2. 🔴 **`parse()` 的 `while` 循环内逐报告喂**（`:61-101`），照 kissqy `bno08x.rs:445-460`。**绝不能**只在 `receive():51-59` 末尾喂最后一帧——一个 SHTP payload 常含多个报告，丢中间 step 会让 `dt` 系统性偏大（静默 bug：数字看着合理，姿态慢慢漂）。
3. 0x02 分支（`:74-86`）：
   ```
   let step = seq.wrapping_sub(last_seq);
   if step == 0 { skip }                       // 重复
   if step > 128 { counts.out_of_order += 1; skip }  // 回读/乱序
   let bridged = step <= 3 && now - last_at <= 100ms;
   if bridged { fusion.gyro(RAW_RATE, f64::from(step) * 0.01) } else { fusion.gap() }
   ```
   - 🔴 **`RAW_RATE` 必须是 EMA 之前的 `g`**（`:75`），即先取原始值喂 fusion，再在 `:76-79` 做 `reference_filter` 覆盖 `self.gyro`。若把 EMA 后的值喂进去，`a_constant_rate_about_any_axis_integrates_exactly`（`gyro_fusion.rs:569-587`）会因相位滞后不再 <1e-9。
   - `ImuData.gyro` 的输出仍走原有 `rotate(mount, g)`（`:115`），**观测契约不动**。
4. 0x08 分支（`:87-95`）：`dt = min(step, 10) * 0.01` → `fusion.chip(q, dt)`，记 `Verdict` 到 `counts`（照 `:500-520`）。
5. `sample()`（`:104-119`）：
   ```
   let q_raw = self.quat...;
   let q = if mode == Gyro && !disabled { fusion.fused().unwrap_or(q_raw) } else { q_raw };
   let trunk = mul(q, [mount[0], -mount[1], -mount[2], -mount[3]]);   // = mul(q, conj(mount))
   gravity = rotate_inverse(trunk, [0.,0.,-1.]);
   ```
   - 🔴 **fusion 跑在 sensor 系，mount 只在 `sample()` 里做一次**（`:113` 原位）。kissqy 测试 `fusing_in_sensor_axes_is_fusing_in_trunk_axes()`（`:1317-1361`）证明：sensor 系融合 + `TrunkFrame(mount)` ≡ trunk 系融合 + identity mount，逐 tick `gravity`/`gyro` 差 <1e-9。**禁止把 `trunk` 再喂回 fusion**（双重安装）。
   - `q` 与 `fused()` 的 `w≥0` 差异：两者代表的旋转相同，`gravity` 一致，但 `ImuData.quat` 可能差一个整体符号 ⇒ **断言一律用 `gravity`，不要逐位比 `quat`**。
6. **panic 隔离**：fusion 跑在 reader worker 线程里（`run():363-403`），该线程 panic 后无人重启（对比 `supervise():269-291` 只处理 `Result::Err`）。必须照 `bno08x.rs:432-443` 用 `std::panic::catch_unwind(AssertUnwindSafe(...))` 包住，一旦 panic 置 `disabled=true`、样本永久回退 chip，并写 `tracing::error!`。
7. **新 epoch 重置**：`invalidate()`（`:47-50`）与 `reconnect()`（`:208-223`）要重建 `GyroFusion`（`FOLLOW_S=1.0` 对应 kissqy `HOST_IMU_SETTLE=1s`，测试 `:632-651` 钉死二者相等），`counts` 跨重连累计。

### 5.4 配置键（🔴 写键前先 grep Rust 源码）
- 加到 **`duck-control/src/feetech.rs:29-43` 的 `Config`**：`#[serde(default)] pub bno08x_fusion: Bno08xFusionMode`（枚举 `chip`/`gyro`，默认 **chip**），并在 `ThreadedFeetechIo::open_with_imu()`（`:203-207` 附近）把 `cfg.bno08x_fusion` 传给 `Bno08x`。
- 🔴 该结构带 **`#[serde(deny_unknown_fields)]`**（`:30`），且 `load_config():90` 是 **JSON** 反序列化 ⇒ **先在 Rust struct 注册键，再可选写进真机那份 `feetech:<path.json>`**；顺序反了整份配置加载失败（项目铁律）。**不要写进 `deploy/robotd.toml`**。
- 🔴 **绝对不要为了融合去改 `reference_native`**。它是全局「原生参考」开关，除 `bno08x.rs:76-79` 的陀螺 EMA 外还控制：关节速度 EMA（`feetech.rs:970-977`）、目标越界 clamp 而非常报错（`:1043-1047`）、skill 解析顺序（`robotd-params/src/lib.rs:1303`）、策略/安全多条分支（`robotd/src/main.rs:1633/1799/1805/2031/…`）。关它会一次改变 4+ 处行为。正确做法是把 IMU 侧 EMA 与融合解耦（§5.3 第 3 条）。
- 默认 `chip` = 保持现有行为，未上板验证前**零回归面**；`gyro` 只在 A/B 时显式打开。

---

## 6. Phase 2：验收与负对照（🔴 每条都要能「删一个就红」）

### 6.1 离线（必须先过）
搬来的 19 单测 + 4 CSV replay 全绿，验收数字直接取 kissqy 现成断言：
- `walk-glitch.csv`：verdict `[50,567,132,0,0,0,0]`、`chip_steps=72`、**`fused_steps=0`**、`longest_open_loop=0.34023s`（`:1239-1255`）
- `home-still.csv`：`[50,250,0,...]`、held_med `0.0184°`、P99 `<1°`（`:1260-1269`）
- `fall-walk.csv`：`[51,632,88,29,...]`、**`fused_steps=0`**、`last_second_max<1°`（`:1275-1291`）

### 6.2 五条负对照（本项目铁律：自检必带负对照，且要能删一个让两侧都红）
| # | 故意改坏 | 必须变红的两处 | 抓的是什么静默 bug |
|---|---|---|---|
| N1 | `GATE_DEG: 6.0 → 1e9` | `a_thirty_degree_glitch...`（`:656-669`）断言全 `Rejected` 失败；`walk-glitch` 的 `rejected=132` 与 `fused_steps=0` 同时失败 | 门没接上，跳变被吃进 gravity |
| N2 | `mode=Gyro` 但 `sample()` 忘记把 `q_raw` 换成 `fused()` | 静立时 chip/gyro 输出**相同**（看不出）；注入 30° 跳后断言 `gravity_gyro ≠ gravity_chip` 失败；`report_stats` 的 `rejected` 仍增长但输出不变 | **开关写了没生效**——最典型的静默 bug，必须用 glitch 样本而非静立样本验 |
| N3 | 把 `mul(q, conj(mount))` 后的 `trunk` 喂回 fusion | `fusing_in_sensor_axes_is_fusing_in_trunk_axes()`（`:1317-1361`）的 1e-9 等价性失败 | mount 双重安装 |
| N4 | 把 `reference_filter` **之后**的 `g` 喂 `fusion.gyro` | `a_constant_rate_about_any_axis_integrates_exactly()`（`:569-587`）的 `<1e-9` 失败；`a_coning_trunk...`（`:592-628`）`<0.05°` 失败 | EMA 相位滞后污染积分 |
| N5 | 把 fusion 调用从 `parse()` 循环移到 `receive()` 末尾 | 构造含 3 个报告的 payload，`a_coning_trunk...` 误差 >0.05°；`counts.gyro` 少于 `gyro_count` | 多报告 payload 丢中间 step |

> N1/N2 是「删一个让**单测 + replay 指标两侧都红**」的成对设计；只搬字面量、不加这两条，等于把断言搬了家而不是加了门禁。

### 6.3 上板（真机，尚未执行）
1. `report_stats` 的 `fusion counts` 随 tick 递增；`robotctl health --json` 50Hz、0 missed、`consecutive_stale_blocks=0`。
2. **A/B 同条件**：`mode=chip` 与 `mode=gyro` 各推摇杆 60s，记录摔倒次数与 `gravity` 单 tick 跳变分布。参考 fanhao 实测 chip 9s 摔 2 次 vs gyro 60s 零摔；判据用「我们自己的 chip 基线」，不套别人的绝对值。
3. 若 `gyro` 不优于 `chip` ⇒ 回滚（默认 chip 即回滚）；若优，才用 100Hz 原始日志重定 `6°/0.66s/0.5s/5°·s⁻¹`（`gyro_fusion.rs:39-42` 明说这些是一组初调值）。
4. 安全兜底：`catch_unwind` 触发后永久 chip；`fusion.fused() == None` 时 chip；不写芯片 NVM（我们 `run():353-359` 只发 volatile set-feature，与 kissqy 一致）。

---

## 7. 明确不做（防止范围膨胀）

- ❌ **不搬 `HostImuGate`**（50ms 龄 / 1s 稳定 / 3 次冻结判定）：我们已有 150ms 龄 + 30ms 偏斜门（`:107-111`）与启动期，粗但够用；除非上板真出现「旧 sample 冒充新鲜」再立项。
- ❌ **不搬 `trunk_imu_raw_log.rs`**（我之前把名字说成 `bno08x_raw_log`，**订正**：实际是 `microduck-hd1910/firmware/robotd/src/trunk_imu_raw_log.rs`；开关 `[trunk_imu] bno08x_raw_log` 指向文件路径，CSV 列 `host_us,packet,channel,shtp_seq,report_id,report_seq,status,delay_100us,v0…v5`，64MiB 上限、独立 writer + 有界队列、绝不阻塞 reader）。**Phase 0 用 `report_stats()` 已能回答「跳不跳」**；只有 Phase 2 需要重定阈值时才搬它采 100Hz 原始报告。
- ❌ **不改 `reference_native`**（§5.4）。
- ❌ **不动 `DuckBuddy-main` / `out/robotd_hd1910_mode0.toml` 那条总线板线**（§0）。
- ❌ **不改观测契约**：obs 61 / act 14 / 50Hz、`ImuData.gyro` 口径保持，只换 `gravity`/`quat` 的来源。

---

## 8. 待真机项（链路已查清，非「未查」）

| ID | 项 | 现状 |
|---|---|---|
| R-1 | 真机 `feetech:<path.json>` 的具体路径与内容 | 链路已查清（`main.rs:1128-1133` → `load_config():89-99` JSON）；本仓**无现成模板文件**，需上板 `/etc/robot/` 下确认。写键前照例 grep Rust struct |
| R-2 | 我们这颗 BNO085 走路是否真跳 20–60° | **Phase 0 回答**；fanhao 的数不能当 ours |
| R-3 | 100Hz 报告周期是否稳定 | kissqy 有 `Period`（`bno08x.rs:86-89`，10s 窗口、5% 容差告警），我们没测；若 `dt = step×0.01` 与实际不符，融合会缓慢漂移 |
| R-4 | `installation.json` 的 `imu_mount_wxyz` 装机朝向 | 已有 `[0.5,-0.5,0.5,-0.5]`（`hd1910m/radxa/installation.json:5`）；装后仍走 `imu_mount_sanity` 自检 |

---

## 9. 证据清单（本轮实际读过的源码）

**本地**（`.upstream/hd1910m/microduck/`）
- `duck-control/src/bno08x.rs`：全文 600 行（重点 `:19-29` `Reports`、`:42-44` `fresh`、`:61-101` `parse`、`:74-86` gyro EMA、`:87-95` quat 直采、`:104-119` `sample`、`:226-235` `report_stats`、`:269-291` `supervise`、`:338-405` `run`、`:421/:459/:567-587` 现有测试）
- `duck-control/src/feetech.rs:29-43`（`Config` + `deny_unknown_fields`）、`:89-99`（`load_config` JSON）、`:203-207`（`open_imu`）、`:440-455`（`imu_transport`）、`:970-977` / `:1043-1047`（`reference_native` 副作用）
- `duck-control/src/imu.rs:1-60`（`ImuData` 定义与注释）；`robotd/src/imu_only.rs:1-25/:40-85`；`robotd/src/main.rs:725/:1120-1155`；`robotd-params/src/lib.rs:604-606/:1303`；`deploy/robotd.toml:15-27`

**kissqy**（GitHub API `contents` + base64，分支 `hd1910-v167-trunk-imu-i2c`）
- `firmware/duck-control/src/gyro_fusion.rs`：全文 1363 行（`:4-42` 动机、`:50-74` 常量、`:194-382` `GyroFusion`、`:385-495` 数学、`:497-1362` 19 测试 + replay）
- `firmware/duck-control/src/bno08x.rs:60-89`（常量）、`:320-338`（Q14/Q9 与 `[w,x,y,z]`）、`:396-520`（`Fusion` 逐报告喂入、`catch_unwind`、seq→dt）
- `firmware/duck-control/src/trunk_imu.rs:33-183`（三路线 / `TrunkFrame` / `HOST_IMU_SETTLE`）、`firmware/robotd/src/trunk_imu_i2c.rs:24-77`（`[trunk_imu] bno08x_fusion` 解析）
- `firmware/robotd/src/trunk_imu_raw_log.rs:1-160`（CSV 机制）
- `firmware/test-data/bno08x-fusion-replay/{home-still,walk-glitch,fall-walk,fall-realign}.csv`（列头与回放说明）
