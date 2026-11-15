# MicroDuck 安卓 App：硬件状态监控 + 告警 + 缓慢旋转 3D 仿真模型（2026-11-15）

> 单一权威文档。需求原话：「监控再加点功能，每个硬件的状态，比如温度，通信状态等，状态异常有提醒，电量低温度高有提醒，最好有个仿真模型在那缓慢旋转，状态异常的位置有异常颜色标记，查查资料，看能不能实现」；追加授权：「如果镜像不支持可以优化镜像，除非硬件不支持，软件方面都可以改可以重构」。
>
> 铁律不变：`UNVERIFIED != PASS`、`COLLECTED != PASS`、`ship_verdict = NOT_SHIPPABLE`。
> **改源码 ≠ 板上已生效**：本地 `ft1910` 是 API 39 快照，板上 V112 镜像跑的是 `robotd` v40，两者不是同一份二进制。

---

## §0 结论：能不能实现

**能实现，而且核心需求（异常部位着色）不需要等固件补丁。**

| 需求 | 结论 | 一手依据 |
|---|---|---|
| 电量 / 电压显示 + 低电量提醒 | ✅ 真字段 | `HealthResult.battery.{volts,percent}` |
| 温度显示 + 高温提醒 | ✅ 聚合温度真字段 | `motors.{hottest,max_c,mean_c}`、`cpu_temp_c` |
| 通信状态 | ✅ 真字段组合 | `bus.*`、`control_loop.last_tick_age_ms`、传输层事件、health 轮询新鲜度 |
| 状态异常提醒 | ✅ App 内横幅 + AI 通道结构化输出 | 本轮实现 |
| 缓慢旋转仿真模型 | ✅ 零新依赖、离线可编译 | Google Android 平台文档 `android.graphics.Camera` / `Matrix`；软件透视投影 + 2D Canvas |
| 异常位置异常颜色标记 | ✅ **真数据驱动** | `BusHealth.missing: Vec<u8>` 精确点名 15 个舵机 ID → `JOINT_IDS` 映射 → 模型关节锚点 |
| 每个舵机**各自**的温度/电压/负载 | ⚠️ 协议当前不提供 | 底层有 `temps_c: [f64; 15]`，被 `robotd` fold 成 3 个标量后丢弃；见 §5 补丁提案 |
| 无线通信 RSSI / 链路质量 | ❌ 协议没有 | `app-path-design.md:922-923`「RSSI is a sort key, never identity」；`net.status.signal` 是 WiFi 0–100 百分比，属另一个 method |

**明确不做的假象**：不伪造 15 路温度、不伪造 RSSI 数值、不把「没读到」画成绿色、不把 Mock 夹具告警当真机告警、不发会污染真机门禁窗口的系统通知。

---

## §1 一手资料清单（先查资料，不自己推）

### 协议字段（本地一手 Rust 源码）
- `microduck-software/.upstream/ft1910/duck-ipc-proto/src/lib.rs`
  - `HealthResult`（:3479-3548）、`Battery`（:3726-3730）、`MotorThermal`（:3712-3718）、`CpuThrottle`（:3677-3693）、`LoopHealth`（:3551-3567）、`BusHealth`（:3574-3590）、`ImuHealth`（:3628-3647）
  - `BusHealth.missing` 注释（:3584-3587）：「All fifteen is servo power off; some of them is servos unplugged, **and naming them is the point**」
  - `JOINT_NAMES`（:536-552）/ `JOINT_IDS`（:560-564）= 左腿 20–24 / 颈头喙 30–34 / 右腿 10–14
- `robotd/src/main.rs:752-785` `fn health()`：注释明写这些描述量 "consulted by none of the checks below"（**Reported, never judged**）
- `robotd/src/main.rs:3999-4064`：逐舵机 `slow.temps_c` 在 :4046-4057 被 fold 成 `hottest/max_c/mean_c`，数组丢弃
- `duck-control/src/model.rs:170-191`：`BATTERY_FULL_V=8.2` / `BATTERY_EMPTY_V=6.6`，`battery_percent()` 线性 clamp
- `btd/src/route.rs:130,474-478`：BLE 只放行 `RobotHealth`，`RobotSubscribe` 被拒（20 字节管道 firehose）⇒ 手机侧只能 2 秒级 `robot.health` 轮询
- `docs/robot/cheatsheet.md:52-55`：电池/温度「comes from `robot.health`, polled every two seconds, because none of it is on the state stream」
- 录制的真实应答：`microduck-software/.upstream/replica/software/studio/tests/fixtures/now-20261018.jsonl:3`，键名与 `HealthResult` 一致，含 `battery/motors/cpu_temp_c/cpu_throttle/control_loop/imu/bus`，**无 per-servo 数组、无 rssi**

### 阈值一手依据
| 阈值 | 值 | 出处 |
|---|---|---|
| 舵机 WARN | ≥ 60 °C | Feetech STS3215 产品规格书：工作温度范围 −10 ~ 60 °C |
| 舵机 CRITICAL | ≥ 70 °C | 同规格书 §7-11「过热 Over Hot 大于 **70°C** 关闭扭矩输出」 |
| CPU WARN | ≥ 80 °C | Radxa ZERO 3W 相关热管理资料与项目实机踩坑记录（~80 °C 起降频） |
| CPU CRITICAL | ≥ 85 °C | Radxa ZERO 3W Product Brief Rev 1.8 §6.5：internal thermal management governor「CPU temperature does not exceed a threshold of **85°C**」 |
| 电池 WARN | < 20 %（或 ≤ 6.92 V） | 2S Li-ion 3.3 V/芯 = 6.6 V 警戒线；6.92 V 由源码线性映射反推 20% |
| 电池 CRITICAL | < 10 %（或 ≤ 6.6 V） | 源码 `BATTERY_EMPTY_V=6.6`；2S 低于 6.0 V（3.0 V/芯）有过放损伤风险 |
| 控制环停滞 | `last_tick_age_ms > 1000` | `LoopHealth.target_hz=50`（源码），1 s 无 tick 即异常 |
| 读数陈旧 | > 6000 ms | 轮询周期 2 s 的 3 倍，本地显示策略 |

🔴 **这些都是「本地显示策略阈值」，不是固件判定**。`robotd::health()` 的 `healthy/degraded/reason` 才是 robotd 自己的判决，本实现单独作为第 ⑦ 条判据接入，不与显示阈值混为一谈。电池 `percent` 一律显示服务端算好的值，App **不重算**（`robotd-design.md:735-741` 明写重算会导致两块屏数字不一致）。

### 3D 渲染平台依据
- Google Android 平台文档 `android.graphics.Camera`（API 1）：「A camera instance can be used to compute 3D transformations and generate a matrix that can be applied, for instance, on a Canvas.」
- 同文档 `androidx.compose.ui.graphics.Matrix`：`rotateX/rotateY/rotateZ` + 透视项 `Perspective0/1/2`。
- 官方文档《Create custom view components》另注「真正的 3D 图形应扩展 SurfaceView」；本模型是**软件透视投影的线框 + 部位标记**，本质是 2D Canvas 绘制，落在 `Camera`/`Matrix` 适用范围内。
- 收益：**零 OpenGL ES / Sceneform / filament / 第三方引擎、零新增 Gradle 依赖**，项目离线构建（Google 域名不通、Gradle `--offline`）不受影响。

### 版本口径冲突（必须标注，不能混用）
| 来源 | API | 说明 |
|---|---|---|
| 本地 `ft1910` 一手源码 | 39 | 本协议字段清单的依据 |
| Android `Wire.kt` | 40 | 注释称对齐 fanhao 分支 |
| 实机板子（V112 镜像） | `robotd` v40 / `robotctl` v37 | SSH 验收实读 |
| replica 上游跟踪 | 47 | 另一快照 |

`docs/active/microduck-安卓App功能调研-2026-11-12.md:165` 写「`robot.health` 含每个舵机的电压/温度/负载」，属 **fanhao 分支假设**，与 `ft1910` 一手源码不符；本轮以 Rust 源码为准，未找到即标 UNKNOWN。

---

## §2 实现清单

### core（纯 JVM，零 Android 依赖，可自检真跑）
| 文件 | 职责 |
|---|---|
| `RobotParts.kt` | 21 个部位（15 关节 + 6 系统）、`JOINT_IDS/JOINT_NAMES` 一手表、`partOfId/partOfName`、`Severity`、`severityArgb` 语义色单一真源 |
| `HardwareMonitor.kt` | `HwThresholds`、`MonitorSource`、`LinkState`、`MonitorVerdict`、`HwAlert`、`MonitorReport`、`evaluate()` |
| `DuckModelGeometry.kt` | `Vec3`、21 个 3D 锚点、椭球线框 + 骨架、`rotateY` / **`rotateYTwice`（第二条独立算法）**、`project`、`frame`（深度排序） |
| `HealthSnapshot.kt` | 纯新增带默认值字段：`bus.missing[]`（区分「省略」与「显式空」）、`imu.*`、`cpu_throttle.*`、`servo_telemetry` 前向兼容解析 |
| `AiDebugPolicy.kt` | 白名单新增只读 `monitor` 命令 |

### app
| 文件 | 职责 |
|---|---|
| `monitor/DuckModelView.kt` | 自定义 View，Canvas 画线框/骨架/部位圆点；异常部位红/琥珀光晕 + 标签；每 1 s 有限补间转 6°（一圈 60 s） |
| `MainActivity.kt` | 健康页顶部保留两行门禁断言文本，其下新增 3D 视图 + 告警横幅 + 部位统计；`renderMonitor()` 用 `setTextIfChanged` 节流；切页暂停旋转 |
| `SessionHolder.kt` | `lastHealthOkMs` / `linkState` / `monitorSource()` / `monitorReport()` 统一报告入口；换链路清空旧读数 |
| `AiDebugReceiver.kt` | `monitor` 命令输出 `SessionHolder.monitorReport().toJson()`（与 UI 同一函数） |

### 数据真实性分层（防止假绿）
- `NO_DATA`：未连接 / 调用失败 ⇒ 零告警、零部位判定；「没数据 ≠ 正常，也 ≠ 故障」
- `MOCK_FIXTURE`：**verdict 恒 `DEMO_ONLY`**，每条告警带 `demo=true`，摘要自带「非实机读数」
- `REAL_HEALTH`：才允许按判据触发告警
- 字段缺失一律 `UNKNOWN`（灰色），**绝不默认绿**；`achieved_hz=null`、`battery` 省略等遵循 `HealthSnapshot` 已有「缺失 ≠ 0」口径
- `MonitorVerdict` 枚举**没有 PASS**；`toJson()` 只输出观测值

### 告警/着色判据（全部带 `basis` 一手依据，UI 与 JSON 均可追溯）
1. 电池低：`percent<20` WARN / `<10` 或 `volts<=6.6` CRITICAL → 电池部位
2. 舵机高温：`max_c>=60` WARN / `>=70` CRITICAL → **只给 `hottest` 对应关节着色**，其余 14 关节保持 UNKNOWN
3. CPU 高温/降频：`cpu_temp_c>=80/85`、`cpu_throttle.level>0` → CPU 部位
4. 总线：`bus.missing[]` 非空 → BUS + **每个缺失 ID 对应关节精确标红**；`consecutive_errors>0` WARN；`startup_failures>0` CRITICAL
5. IMU：`ready=false` CRITICAL；`consecutive_stale_blocks>0` WARN
6. 通信/控制环：`link=DOWN` CRITICAL；读数陈旧 >6 s ⇒ LINK 退出 OK；`last_tick_age_ms>1 s` 或 `achieved_hz<90% target` WARN
7. robotd 自报：`!healthy || degraded` → 躯干 CRITICAL，`reason` 原文进告警
8. 前向兼容：`servo_telemetry` 出现时启用逐舵机温度判据；缺失时明确 note「逐舵机温度 UNVERIFIED」

> 实机场景对照：11-14 SSH 验收 `missing IDs [10,11,12,13,14,20,21,22,23,24,30,31,32,33,34]` 全 15 个缺失 ⇒ 模型 15 个关节**全部标红**，这正是「状态异常的位置有异常颜色标记」的真实数据驱动，不是演示动画。

---

## §3 为什么用「有限补间」而不是无限动画

项目真机门禁踩过「1 s `setText` 连发 AccessibilityEvent → `uiautomator waitForIdle` 死锁」（修法 = 1500 ms 节流 + `setTextIfChanged`）。本实现：
- `DuckModelView` 只 `onDraw`、从不 `setText`，不发 AccessibilityEvent
- 旋转由 `MainActivity` 的 1 s tick 调 `advanceFrame()`，每次 **900 ms 有限补间**转 6°，之后主线程留 100 ms 空窗
- `renderMonitor()` 所有 `TextView` 走 `setTextIfChanged`，文本不变不写
- 离开健康页 `setRotating(false)`，后台不空转

⚠️ 但**手机已拔**，上述对真机 `uiautomator` idle 的影响本轮 **UNVERIFIED**，下次插机须复跑既有 59/59 门禁（见 §6）。

---

## §4 你追加授权的镜像/软件改动：处理结论

授权原话：「如果镜像不支持可以优化镜像，除非硬件不支持，软件方面都可以改可以重构」。

**软件侧已按授权真改**：`HealthSnapshot` / `HardwareMonitor` / `RobotParts` / `DuckModelGeometry` / `DuckModelView` / `MainActivity` / `SessionHolder` / `AiDebugPolicy` / `AiDebugReceiver` 均为实质改动或重构，且 App 侧已做**协议前向兼容**——上游一旦提供 `servo_telemetry`，15 个关节立刻获得真实逐舵机判据，无需再改 App。

**镜像侧本轮不重烧，标 `PATCH_PROPOSED_NOT_APPLIED`**，理由是机械验证过的前置前提不成立，不是「不能改」：

| 前置前提 | 实测 | 后果 |
|---|---|---|
| 本机 Rust 工具链 | `cargo` / `rustc` 均不存在 | 无法编译验证补丁，改了就是不可验证的假绿 |
| `.upstream/` 入库状态 | `microduck-software/.gitignore:5` 忽略 `.upstream/` | 改上游源码不产生任何可交付/可审查的 git 证据 |
| 板上二进制版本 | V112 镜像 `robotd` v40 | 本地 `ft1910` 是 API 39，补到 39 不会对板子生效 |
| BLE 管道 | `FLOOR_MTU=20`，`btd/route.rs:474-478` 明确拒绝高码率订阅 | 15 路遥测 JSON 远超单包，需先核 btd 响应分片实现（**未核，标 UNVERIFIED**），属协议层较大改动 |
| 可复现链 | V112 镜像 sha pin `d8207ede…` | 重打包 rootfs 会破坏既有镜像基线校验链 |
| 真机复验通道 | 手机已拔 | 重烧后无法做 App ↔ 板端到端验证 |

⇒ 把改动写成**可审查的纯新增补丁提案**（下节），App 侧先具备消费能力；等「Rust 工具链 + 板上对应版本源码 + 手机/板子在场 + 分片方案」齐备，再按 SOP 落地并重烧，那时才有资格谈「镜像支持」。**改文档/改本地 vendor 源码不等于镜像优化完成。**

### §5 上游逐舵机遥测补丁提案（PATCH_PROPOSED_NOT_APPLIED）

原则：**纯新增、不动旧键**（项目既有准则），serde 层向后兼容。

1. `duck-ipc-proto/src/lib.rs` 新增
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServoTelemetry {
    pub id: u8,
    pub temp_c: f64,
    pub volts: f64,
    pub load: f64,
}
```
2. `HealthResult` 末尾新增字段（**不删改任何现有字段**）
```rust
#[serde(default, skip_serializing_if = "Vec::is_empty")]
pub servo_telemetry: Vec<ServoTelemetry>,
```
3. `robotd/src/main.rs:4031-4057` 的 `slow_sensors()` 分支，在 fold 聚合量之前保留原始数组：
```rust
state.servo_telemetry.store(Arc::new(
    JOINT_IDS.iter().zip(slow.temps_c.iter()).enumerate()
        .map(|(i, (&id, &t))| ServoTelemetry {
            id, temp_c: t, volts: slow.volts, load: slow.loads_c[i],
        }).collect()
));
```
（`slow.loads_c` 是否存在需按板上实际版本核对；**未核，标 UNVERIFIED**）
4. **BLE 分片前置**：`btd` 对 `robot.health` 响应是否已有分片/重组机制需先读一手实现；若没有，须新增分片协议或改用二进制紧凑编码，否则 15 路遥测会把 20 字节管道撑爆。
5. 重编译 `robotd`（aarch64 目标）→ 替换 V112 rootfs → 重算镜像 sha → 重烧卡 → 真机 `robotctl health --json` 与 App `monitor` 双侧复验。

App 侧消费代码已就绪：`HealthSnapshot.parseServos()` 接受 `servo_telemetry`（兼容别名 `servos`），按 `id` 映射到 `RobotParts.partOfId`，未知 ID 直接丢弃；字段缺失时 15 个关节保持 `UNKNOWN` 并注明「逐舵机温度 UNVERIFIED」。

---

## §6 验证与状态

### 本轮真跑（离线）
| 项 | 结果 |
|---|---|
| `:core:compileKotlin` + `:app:compileDebugKotlin` | `BUILD SUCCESSFUL` |
| `:app:assembleDebug` / `assembleRelease` | 见最终复验记录 |
| `bash tools/selftest.sh` | `RESULT: 454 passed, 0 failed`（新增 71 条监控/几何断言） |
| `python tools/check_hardware_monitor.py --selftest` | 注入式负对照全绿 |
| `python tools/check_all_app_gates.py --selftest` | `ALL_PASS` |
| `run_all_gates.py --check` / `pytest` | 见最终复验记录 |

### 注入式负对照（必须见过红）
- 故意把 `ROBOT_MOVE` 塞进只读白名单（上一轮范式）：静态 2 errors / 动态 380+3 FAIL
- 本轮新增：阈值 70→90、`MonitorVerdict` 混入 `PASS`、Mock 不再 `DEMO_ONLY`、删 `partOfId` 绑定、删 `rotateYTwice`、关节表漂移、删 3D 接入、删 `setTextIfChanged`、删健康页顶部断言文本、白名单删 `monitor`、自检没挂 main、文档删 `UNVERIFIED` —— 全部必须判红

### UNVERIFIED 清单（**一个都没翻**）
- 手机已拔：3D 视图真机渲染效果、旋转对 `uiautomator` idle 的影响、真机 59/59 门禁未复跑
- AI 通道 `monitor` 命令的 `adb logcat` 端到端未复跑
- 修复后 App ↔ 真板 BLE 握手仍 UNVERIFIED（上一轮遗留）
- `BA-X-5` 仍 `UNVERIFIED_NOT_PASS`（bonding / CCCD write / 50 Hz 状态流 / 断链重订阅 / UDP netpad 实机证据缺失）
- 逐舵机遥测补丁 `PATCH_PROPOSED_NOT_APPLIED`，板上 v40 镜像未含
- `live_hardware_accessed=false`（15 舵机全缺、IMU not ready、robotd read-only），`ship_verdict=NOT_SHIPPABLE`
- **本轮所有告警判据只在 Mock / 合成读数与 JVM 自检中被验证过，真机触发行为未验证**

### 状态字段
`ship_verdict` 与 `live_hardware_accessed` **均不因本轮软件改动翻转**：它们由 `board_acceptance.py::overall_verdict()` 从 `signoff + collected` 证据派生，不是可手工开关。本轮新增的 `MonitorVerdict` 是**观测档位**，与验收结论完全隔离。

---

## §7 复现命令

```bash
cd microduck-android-app
python tools/check_hardware_monitor.py --selftest   # 结构化检查 + 负对照
python tools/check_all_app_gates.py --selftest      # App 统一门禁
bash tools/selftest.sh                              # core JVM 真跑
export JAVA_HOME="E:/软件工具/OpenJdk17"
./gradlew :app:assembleDebug :app:assembleRelease --offline --console=plain
```

下次插上手机后：
```bash
adb install -r -g app/build/outputs/apk/debug/app-debug.apk
python tools/ai_debug_bridge.py --precheck
python tools/ai_debug_bridge.py --cmd monitor          # 结构化读回 verdict / parts / alerts
python tools/device_ui_check.py                        # 复跑 59/59 真机门禁
```
