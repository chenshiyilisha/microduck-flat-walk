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

## §8 2026-11-15 下午修订：双模型 / 配色 / 页面去重 / SSH 界面

用户连续反馈 5 条，逐条落在一手依据上，不靠猜：

### 8.1 「两个模型，一横一竖，横着的缺少舵机模型」
**根因（读源码坐实，非推测）**：`duck_mesh.bin` 存的是 **MuJoCo 世界坐标 Z-up**
（依据：MuJoCo 平台文档「default world orientation is Z-up，option.gravity 默认
`0 0 -9.81`」；本项目 `robot_walk.xml` 的 `trunk_base pos="0 0 0.12"` 表明 Z 是高度、
`neck`/`lens` 在 +X 即喙方向、`hip_l` 在 +Y 即左）。
而 `DuckModelGeometry` 约定 **Y-up**（y 向上、+z 朝观察者）。
`build_duck_mesh.py` 只做居中归一化、**从未做轴变换**，注释却误写成「y 向上」。
结果 `DuckModelView.onDraw` 同时画真实 STL 网格（躺倒 = 横着）与程序化椭球/火柴人
（竖立），且 15 个舵机状态圆点只画在竖着那套上 ⇒ 「横着的缺少舵机模型」。

**修复**：`DuckMesh` 加载时做循环置换 `(x,y,z)_mjc → (y,z,x)_app`
（app.y=mjc.z 上、app.z=mjc.x 喙、app.x=mjc.y 左→右）。这是 3-cycle 偶置换
**det=+1 保持手性**；与 mjswan / mujoco_wasm 的 `(x,y,z)→(x,z,-y)`（绕 X −90°）
同族，仅再绕 Y −90° 令喙正对观察者。变换后按 `NODES` 的 y 范围 `[-1.48, 1.32]`
做**均匀**缩放+居中，让网格与 15 个关节锚点同坐标系同尺度。
`DuckModelView` 改为**单一模型**：只画真实三角形 + 把 15 个 JOINT 状态点叠上去；
程序化 hull/bones/surfaces/bodyEllipse 只在网格加载失败时降级绘制。

**别人怎么做（查证）**：ROCOS HMI「从控制器加载 URDF 及网格，随关节状态更新模型」、
Lucy Control Panel「3D viewer 消费 `/joint_states`」、Reachy Mini dashboard
「MuJoCo + Three.js 实时镜像实体姿态」—— 都是**一个真实网格 + 关节状态叠加**，
不存在两套几何并列。⇒ 本项目改为单模型是有依据的通行做法，不是自创。

**自检证据**（`bash tools/selftest.sh`）：476/476 PASS。轴置换用两条独立算法互算
（逐基向量断言 + 叉积定手性），并带「不是恒等变换」「删掉轴变换会躺倒」负对照；
另验证 y 跨度对齐 NODES 尺度 2.8、官方配色已生效。

### 8.2 「别人模型用什么颜色也参考一下」
一手依据：ROBOTIS 产品页「REAL MICRODUCK COLORWAYS」与 Economic Times 规格文：
Cream = 奶油白壳 + 橙 trim/喙；Graphite = 石墨灰壳 + 黄；Lavender = 薰衣草紫 + 黄；
Sky = 天蓝 + 橙；镜头/眼恒黑。
旧 `PART_COLORS` 把整只画成纯橙，不还原。现按首发 **Cream** 款重映射：
主橙语义色 → 奶油白壳 `0xFFF3E6D2`、深橙 → 橙 trim/喙 `0xFFFF8A3D`、黑 → 镜头黑。
重映射放在 core 加载层（纯视觉，不参与判据），`build_duck_mesh.py` 写入的仍是
生成期语义色，避免两处配色表漂移。

### 8.3 「模型要能左右滑动 / 模型展示可以大一点」
触摸拖动旋转保留；新增 `ZOOM=1.32` 屏幕空间缩放（同时作用于网格与状态点，
不会错位），健康页 View 高度 168→220dp。

### 8.4 「舵机展示只有 20 到 34」
`JOINT_IDS` 一手为 20–24 / 30–34 / 10–14 三组，代码本就建 15 格；
真机只见前两组是**模型放大后「15 舵机网格」第 3 行（10–14 右腿）被挤出视口**：
旧健康页 `col` 直接 addView 到 MaterialCardView，只有底部 `healthText` 有独立
ScrollView（嵌套滚动），整页不可滚。
修复：健康页整体套一层 `ScrollView(isFillViewport)`，`healthText` 去掉独立
ScrollView 避免嵌套；网格按三组各加显式标题「左腿 20–24」「颈·头·喙 30–34」
「右腿 10–14」，让 10–14 的归属一眼可见。

### 8.5 「三个界面都有顶部控制台卡片和底部通道卡片，重复了，还缺少 SSH 远程控制界面」
旧 `buildPage()` 每页各 `addView` 一套 AppBar + linkBanner（`pageChromes` 三份），
且全局另有 `buildBottomStatus()` 一条「通道=… 已发 N 帧」，与状态页
「App 本地遥测」的驱动通道/驾驶帧/状态帧**完全重复**。
修复（M3 navigation bar「3–5 destinations」「distinct pages」）：
- AppBar + 链路横幅收敛为**框架层全局唯一一份** `chrome`，标题随目的地变化
  （MicroDuck · 状态/健康/设置/终端），来源标签与状态串只此一份；
- 移除底部「通道=…」状态条（信息由状态页遥测网格承载）；
- 新增第 4 个目的地「终端」= `SshPanel`，复用已编译通过的
  `SshClient` / `SshCredentialStore` / `TerminalEmulator`。

`SshPanel` 安全边界：凭据默认**不落盘**（仅用户勾选「记住凭据」才写
EncryptedSharedPreferences 密文）；连接后显示主机指纹供肉眼核对；
快捷命令只用 `robotctl health --json`（一手实机依据）与 Linux 平台通用只读命令
`uptime` / `df -h`，**不编造未核实的控制命令**；网络操作全在后台线程、
UI 更新 `post` 回主线程；`onDestroy` 断开会话。
交互式 PTY shell 与 `TerminalEmulator` 已就绪但本页先用一次性 `exec`
（每条命令才刷一次 UI，避免 uiautomator idle 死锁）⇒ 交互式终端状态
**UNVERIFIED**，不声称已实现。

### 8.6 验证状态
| 项 | 结果 |
|---|---|
| `bash tools/selftest.sh`（含轴变换/配色自检） | 476/476 PASS |
| `python tools/check_hardware_monitor.py` | 0 errors, VERDICT=OK |
| `./gradlew :app:assembleDebug --offline` | BUILD SUCCESSFUL |
| 真机 `device_ui_check.py` | ⏳ 设备 CM_PROB_PHANTOM 假掉线，需重新插线复跑 |

⚠️ 真机门禁未复跑的原因：PnP 有 `Android Composite ADB Interface`（VID_2D95）
记录但 `adb devices` 空 = 物理已断的假掉线；按 SOP `kill-server`/`start-server`/
`adb reconnect` 均无效，必须重新插 USB 线。本轮所有**不依赖设备**的门禁已全绿。

---

## 9. 第 4 轮（同日 19:40–20:45）：R8 断点、门禁契约修正、**模型碎片真因根治**

§8.6 的验证状态表是当时的快照，以本节为最新单一权威。

### 9.1 release R8 缺类（构建断点）
`:app:minifyReleaseWithR8` 报 `Missing class javax.annotation.concurrent.GuardedBy`
（来自 `androidx.security:security-crypto:1.0.0` → Tink）。AGP 自动生成
`app/build/outputs/mapping/release/missing_rules.txt`，逐字为
`-dontwarn javax.annotation.concurrent.GuardedBy`。已按**产物原文**写入
`app/proguard-rules.pro`，只落地这一条：不预先写宽泛的 `javax.annotation.**`
兜底，否则会掩盖后续真实缺类。修后
`./gradlew :app:assembleDebug :app:lintDebug :app:assembleRelease --offline`
→ `BUILD SUCCESSFUL`、`GRADLE_RC=0`、lint `0 errors, 48 warnings`；
debug / release APK 均含 `assets/duck_mesh.bin`。

### 9.2 「pip 装上了」是假的：管道 rc 污染
`python -m pip install mujoco 2>&1 | tail -8` 后台报 `exit code 0` —— 但管道 rc 来自
`tail`。去掉管道真跑：`PIP_RC=1`、`ERROR: Could not find a version that satisfies the
requirement mujoco (from versions: none)`（系统 Python 3.13 + 清华源）。
按「先穷尽现成环境」查到项目自带
`microduck-software/.venv-mjlab/Scripts/python.exe`（Python 3.12.13 / mujoco 3.7.0 /
numpy 2.5.4 / trimesh 5.1.1），统一门禁改用该解释器即全绿。
⇒ **解释器契约**：`check_all_app_gates.py` / `build_duck_mesh.py` 必须用
`.venv-mjlab`；系统 Python 3.13 没有 mujoco，如实标环境缺口，不放宽判据。

### 9.3 门禁契约：结论行 + 真实计数 + 产物级负对照
- `build_duck_mesh.py --selftest` 旧版只打印 `SELFTEST: ... — PASS`，不匹配
  `check_all_app_gates.py` 的结论行正则 ⇒ 被判「无结论行(静默成功不算绿)」误红。
  改为统一输出 `RESULT: N passed, M failed`，N/M 取真实 checks 计数，不写死数字。
- 新增判据：二进制 header 第二条独立 `struct` 解析、两份产物字节一致、
  坏魔数 / 截断 / 一字节漂移 / 散落碎片负对照。
- `check_hardware_monitor.py` 补**产物级**字节一致判据（源码注入覆盖不到产物漂移），
  负对照 22/22 → **23/23**。真在磁盘上翻转 assets 末字节 → `RESULT: 1 errors` /
  rc=1；恢复后 sha256 与备份逐字节一致、门禁转绿。
- 统一门禁 `VERDICT = ALL_PASS`：bridge 19/19、mesh 18/18、静态 11/11、
  APK 隔离 12/12、证据链 12/12、硬件监控 23/23、core JVM 483/483、runner 夹具 10/10。

### 9.4 🔴 模型「还是不行」的**真正**根因：stride 抽样只留 2% 的面
前几轮都在改渲染层（轴变换、配色、不透明、Lambert、文字移出），但用户反复反馈
「模型做的还是不行」。本轮新增 `tools/render_mesh_preview.sh` + `tools/MeshPreview.java`，
**调用与真机完全相同的** `DuckMesh.project()` 把一帧画成 PNG（手机拔线也能目视），
第一次真正「看见」结果：上下两团细碎线状碎片 + 中间一列灰点，而不是实心鸭子。

一手数据量出真因：

| 量 | 旧 stride 抽样 | 顶点聚类后 |
|---|---|---|
| 原始外观面数 | 334880（25 个 geom 实例） | 同左 |
| 输出三角形 | 7500（每隔 N 面取一个，互不相邻） | 11972（连通表面） |
| 顶点数 | 113508（绝大多数未被任何面引用） | 3137 |
| 共享边比例 | 0.254 | **1.000** |
| 退化面占比 | 20.9% | **0.0%** |
| 中位三角形面积 | 5.5e-6 | **5.4e-4** |
| 文件体积 | 1.45 MB | 229 KB |

⇒ 每隔 N 个面取一个是**散点抽样**，把闭合壳体打碎；加光照 / 不透明都救不回几何本身。
修法（`tools/build_duck_mesh.py`）：全量读 334880 面 → **顶点聚类**（量化到 cell、
相邻三角形共享簇顶点、丢塌陷面、簇内取均值）→ 二分搜索最细 cell 使输出
`<= TARGET_TRIS=12000`。零新增 Gradle 依赖；生成侧只需 `.venv-mjlab` 的 mujoco + numpy
（曾试 `trimesh` + `fast-simplification` 的 quadric decimation，在该薄壳网格上会卡在
~3700 面/部件，故选更可控的聚类）。输出仍为 `DMSH` v1，**Kotlin 侧零改动**。

离线 PNG 目视复验（0/30/60/90 度四帧）：**单一、站立、可辨的鸭子** —— 奶油白圆头 +
黑镜头眼 + 橙色喙/下巴 + 奶油白躯干 + 两条腿 + 两只橙脚；无文字遮挡、无线框碎片。
`CoreSelfTest` **483/483** 含「网格站直 y 跨度对齐 NODES 2.8」「官方配色」「Lambert」
判据，新网格全部通过。debug / release APK 内 `assets/duck_mesh.bin` 与源文件 sha256
一致 `e3a715a8…b412`。

⚠️ 该 PNG **只证明 core 几何 / 配色 / 光照正确**，不证明 Android assets 加载成功、
不证明 `onDraw` 真的画出来 —— 那几项仍需真机 `contentDescription` 与截图。
`UNVERIFIED != PASS`。

### 9.5 SSH 终端：updaterd 开启按钮（代码已落地，未在真板执行）
一手依据：`microduck-主板到货-SSH只读实机验收与App适配-2026-11-14.md` §4.3、
`microduck-V112镜像-按开发规范审查与优化候选-2026-11-14.md` §8.3 —— 实机
`updaterd` = `inactive`/`disabled`，drop-in `zzzz-r17-manual.conf` 是**镜像故意手动**，
非故障；`updaterd.service` 有一手 `[Install] WantedBy=multi-user.target`。
- `SshPanel` 新增只读「更新服务状态」按钮（前后对照）与唯一写操作
  「启动 updaterd（默认关闭 · 需确认）」，`AlertDialog` 二次确认，不自动执行。
- 命令 `sudo -S -p '' systemctl start updaterd`：sudo 官方手册 `-S` 从 stdin 读密码；
  `SshClient.exec(..., stdin)` 把当前登录密码在内存里送一次，不拼命令行、不回显、
  不写日志、不落盘；`-p ''` 去掉提示串。
- 同时修 `SshClient.exec` 静默 bug：旧版 `channel.setErrStream(channel.outputStream)`
  把 stderr 接到**远端 stdin**（JSch outputStream 是写给远端的），会污染密码通道；
  改为独立 `ByteArrayOutputStream` 收集，末尾 `[stderr]` 合并。
- 只用 `start` 不用 `enable --now`：`start` 管当下、`enable` 管开机自启，不改镜像策略。
- 修正 `SshPanel` 类注释里遗留的 `sudo -n` 旧方案（与实现不一致）。
- 🔴 真板上**从未点过该按钮**：服务是否已启动、`/run/updaterd.sock` 是否存在，
  一律 `UNVERIFIED`。

### 9.6 本轮踩的坑
- 管道 `| tail` 让失败命令显示 exit 0（mujoco 安装、早前 gradle 组合命令同理）⇒
  一律 `set -o pipefail` 或重定向到文件后取 `$?`。
- `javac` 在中文 Windows 默认 GBK，UTF-8 源文件报「不可映射字符」⇒ `-encoding UTF-8`。
- Gradle daemon 一次 `EXCEPTION_ACCESS_VIOLATION`（`jvm.dll` C2 CompilerThread 编译
  IntelliJ `AnnotationUtil`）导致 `daemon disappeared unexpectedly`；`hs_err_pid15340.log`
  是环境崩溃非代码错误。`./gradlew --stop` 后重跑即 `BUILD SUCCESSFUL`。
  资料：OpenJDK JDK-8393350 同类 Windows C2 问题，列出的缓解项含
  `-XX:TieredStopAtLevel=1`。崩溃转储已加进 `.gitignore`。
- docstring 里写死「7500 个三角形」随网格重建漂移 ⇒ 全部改成不写死数量。

### 9.7 当前状态与边界
- ✅ 离线全绿：三构建 `BUILD SUCCESSFUL`、lint 0 errors、统一门禁 `ALL_PASS`、
  core 483/483、静态 23/23、mesh 18/18、离线 PNG 目视可辨鸭子。
- 🔴 手机已拔：PnP `Android Composite ADB Interface` = `CM_PROB_PHANTOM`（Code 45），
  `adb devices` 空 ⇒ 物理已断，adb 层任何操作无效，**必须重新插 USB 线**。
- 因此以下全部 `UNVERIFIED`：`adb install -r -g` 装新包、`device_ui_check.py` 59/59
  复跑、真机截图确认模型、`contentDescription` 是否显示「真实外观网格已加载」、
  终端页 / updaterd 按钮真机可定位、SSH 连真板执行 `start updaterd` 前后对照。
- `BA-X-5` / `live_hardware_accessed` / `ship_verdict` 一个都没翻，
  `ship_verdict` 仍 `NOT_SHIPPABLE`。

## 10. 第 5 轮（同日 21:0x）：订正 §9.4 —— 模型「悬空分离」的第二层真因

> 🔴 **本节订正 §9.4 的过度结论**。§9.4 把「模型还是不行」**全部**归因于 stride
> 抽样，并写下「新 PNG 目视：单一站立鸭子」。本轮真的把 PNG 打开逐帧看，发现
> 碎片是修好了，但**头、躯干、腿、脚仍是几块悬空分离的壳**，并不是一只鸭子。
> 即：stride 抽样只是第一层，第二层（几何取舍）当时没查出来。
> **教训：结论必须由「真的看见」支撑，不能由门禁全绿或摘要措辞支撑。**

### 10.1 一手事实：官方根本没有「内部件」这个分类

`robot_walk.xml` 由 **onshape-to-robot** 生成。本机用 `.venv-mjlab` 的 mujoco 真跑枚举：

| 项 | 读数 |
|---|---|
| `ngeom` | 75（全部是 `type=mesh`，`class="visual"` ⇒ `group=2`；`group=3` 是 `self_collision_only`） |
| `nmesh` | 38 种 |
| `group=2`（MuJoCo 默认可见） | **70 个 geom / 38 种 mesh** |
| `group=3`（默认不渲染） | 5 个 geom（`leg`/`sole_left`/`sole_right`/`power_support` 等） |
| 旧 `VISUAL_MESHES` 白名单 | 只命中 21 个 `group=2` geom（18 种），**却多画了 4 个 `group=3` 自碰撞体** |
| 被漏掉的 `group=2` geom | **49 个 / 20 种 mesh** |
| `geom_rgba`（CAD 材质色） | 全部是占位灰 `(0.5,0.5,0.5,1)` ⇒ 不能拿它当配色，语义色表仍必要 |

被漏掉的 49 个里恰好是**全部连接骨架**：
`upper_leg_left/right`(各 12250 面, z≈0.068–0.116)、`ankle_left/right`(z≈0.022–0.048)、
`yaw_roll_motion`(z≈0.227–0.249)、`yaw2roll`、`xl330`(15 个实例, z≈0.029–0.250)、
`seeed_bearing*`、`bearing_roll`、`motor_support`、`upper_leg_rigidity_plate`。
⇒ 只画外壳就必然「壳与壳之间断开」。旧注释写的「跳过内部机械件」是我们**按 mesh 名字
自己拍的分类**，不是 MJCF 的官方语义。

### 10.2 为什么 §9 的全套门禁没抓到

`surface_metrics()` 量的是「三角形之间共享顶点」，每块壳**自身**都是闭合表面，
所以旧网格 `shared=1.000 / degenerate=0.000` 照样全绿。
**「面连通」不等于「部件之间有连接几何」**——判据覆盖不到视觉问题本身。
离线 PNG 当时存在，但没有人真的逐帧看，只引用了生成时的印象。

### 10.3 修法：以官方 `group` 为唯一权威，不再按名字挑

- `extract()` 的过滤条件改为 `geom_group[i] == VISUAL_GROUP(=2)`；
  `VISUAL_MESHES` 名字白名单整体删除。
- `PART_COLORS` 退化为**只管颜色**的语义色表；未登记的结构件走
  `DEFAULT_STRUCT_COLOR = 0xFF2B2B2B`；3D 打印连杆（`WHITE_LINKS`）用主橙语义色，
  由 core `officialColor()` 重映射成 Cream 奶油白，舵机/轴承保持深色。
- 覆盖率读数从 MJCF 派生（`visual_mesh_kinds` / `used_mesh_kinds` / `visual_geom_count`），
  **不写死 18/25/38**，MJCF 换版自动跟着变。
- 新增产物级判据 `vertical_coverage()`：用每个三角形的 z 区间做差分覆盖（O(面数)），
  量「竖直方向每个高度有没有实体表面」；配 `gapped_fixture()` 挖掉中段三角形做负对照。

| 产物 | 最长连续断开 | 未覆盖箱总量 |
|---|---|---|
| 旧白名单网格（§9 产物） | `0.039` | `0.109` |
| 本轮 `group=2` 全外观网格 | `0.000` | `0.000` |

### 10.4 本轮真跑与目视

- `build_duck_mesh.py --selftest`：**`RESULT: 22 passed, 0 failed`**，`rc=0`；
  含「官方 visual mesh 全覆盖(38/38 种, 70 个 geom)」「竖直连续覆盖 0.000」
  「负对照:挖掉中段三角形必被拒绝」。
- 产物：`3067` 顶点 / `12000` 三角形 / **38 个部件** /
  `sha256=be05fcf37eec244cbc7ff9856100659d65417069ec1c6fa9890f550cf3a10a6c`；
  `core/resources` 与 `app/assets` 字节一致；门禁重跑后 sha 不变（确定性成立）。
- 统一门禁 `VERDICT = ALL_PASS`（8/8，`GATES_RC=0`），core JVM `483 passed, 0 failed`，
  静态门禁 `23/23`。
- `:app:assembleDebug :app:assembleRelease --offline` → `BUILD SUCCESSFUL`，
  两个 APK 内 `assets/duck_mesh.bin` 与源文件 sha 全一致。
- 离线 PNG `final3` 四帧（0/30/60/90°）目视：**单一、连通、左右对称的站立鸭子**，
  白壳 + 黑镜头眼 + 橙喙 + 颈连杆 + 白躯干 + 双腿 + 橙脚，无碎片、无悬空部件、无文字遮挡。

### 10.5 状态边界（依旧一个都没翻）

- 本节所有结论都是**离线 core 几何 + 构建产物**层面的；`离线 PNG 只证明 core 几何`，
  不证明 Android 真机 `AssetManager.open()` 成功、不证明 `onDraw` 画出来。
- 手机 PnP 仍 `CM_PROB_PHANTOM`、`adb devices` 空 ⇒ 装包 / 59/59 真机门禁 /
  真机截图 / `contentDescription` / 终端页 / 真板 `start updaterd` 全部 `UNVERIFIED`。
- `BA-X-5`、`live_hardware_accessed`、`ship_verdict=NOT_SHIPPABLE` 不变。
