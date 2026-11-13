# MicroDuck 安卓 App（fanhao 栈）

给 MicroDuck（飞特 HD-1910，fanhao `hd1910-v167-trunk-imu-i2c` 固件）用的安卓控制端。
Native Kotlin。**当前进度：P0 全闭环 + P1 驾驶/健康 + 多页/横屏/双模式 UI + 开源遥控 App 方案对照落地，
已在 Android 真机上运行验证**。
`core` 真编译真测 **230/230**；真固件活体：**C2 11/11**、**C2+ 真状态流 24/24**、
**P1 驾驶 28/28（连跑 5 次）**；**真机 UI 门禁 59/59**；
`:app:assembleDebug` ⇒ `app/build/outputs/apk/debug/app-debug.apk`。

> 🔑 **多页 / 横屏 / 双模式 + 开源方案对照（2026-11-12 晚 – 2026-11-13 收口）**：竖屏控制台三页（状态/健康/设置）
> + 独立横屏 `DriveActivity`，手动/自动模式可切，取景框铺底、双摇杆叠加左右下角。
> **vivo V2338A / Android 16 (API 36)** 上 `tools/device_ui_check.py` **59/59 全绿**（脚本共定义 59 条
> 行为级断言：47 条直接 check + 12 条 `tap()` 注入的「可定位」check，含 348/354 互斥对只计其一）：
> 主页竖屏 / 遥控页横屏(rotation=1)、左右摇杆分离、心跳 +41 帧、松手 +0、
> `ACTION_CANCEL` 同归零、退出停车、自动页零驾驶帧且无摇杆、状态页 4 列紧凑栅格（单屏可见）、
> **A1 BLE 连接面板已进设置页（运行时权限 + 扫描入口）**、
> **设置跨冷启动持久化**、**冷启动强制回手动**、全生命周期零 FATAL。
> **连跑 3 次全 59/59（RC=0）**；并用 `cmd statusbar expand-notifications` 主动注入通知栏污染
> 做负对照：门禁识别「本包节点 0 个」→ BACK 收起 → 仍 59/59，证明窗口归属修复生效、非偶发绿。
> 收口轮修掉最后一类门禁假读数：**uiautomator 只 dump 视口内节点**（非 vivo 特有，一手依据
> GitHub `navigate-app-adb`），状态页遥测区 / 设置页 BLE 面板被推到折叠线以下读不到 ⇒
> 状态页 2 列 8 行(≈480dp)改 **4 列 4 行(≈240dp)** 单屏可见、设置页改用小步幅滚到面板最低按钮
> 「扫描附近 BLE 设备」再断言。另完成 **A5 主仓 `duck-ipc-proto` 协议核对 + 3 个社区 App 一手核验**
> （`Ley-WL/ducklink` 原生安卓 BLE 最相关、另两个不采纳），详见
> `docs/active/microduck-安卓App-开源遥控App设计对照-2026-11-12.md` §7。
> ⚠️ 文档写于无设备连接时段：59/59 为最近一次真机实测（2026-11-13）结果，脚本源码断言数已逐条核对；
> 新一次跑门前建议重跑 `python tools/device_ui_check.py` 复验。
> ⚠️ 这是 **App 在 Android 真机**上运行，不是「机器人整机联调」；
> 真视频 / BLE GATT / 传感器 / 手感 / 策略启停仍 `UNVERIFIED != PASS`。

> 🔑 **P1+ 真机闭环（2026-11-12 / Pass135，单页版历史记录）**：用户接入
> **vivo V2338A / Android 16 (API 36)**，旧单页版 `tools/device_ui_check.py` **16/16、连跑 3 次全绿**：
> 冷启动 329ms、logcat 零 FATAL、心跳真发帧、松手 `+0`、保持按下恢复发帧（排除假阴）、
> **`ACTION_CANCEL` 真机注入与 UP 同归零（三次均 +0）**、HOME→回前台无崩溃。补齐
> **adaptive icon logo**（108dp 三层、中心 66dp 安全区、monochrome 主题层），
> `aapt2 dump badging` 实证已进包，桌面与标题栏同款。该单页版已被上面的多页架构取代。

> 🔑 **P1 已闭环（2026-11-12）**：驾驶走 `robot.move` notification（无 id、无响应，一手 `robotd:3483-3489`），
> 双通道可插拔（JSON-RPC / fanhao UDP netpad 28B wire），`DriveController` 做摇杆映射/死区/圆形限幅/
> 松手归零/100ms 心跳（< netpad timeout 250 < deadman 500）。真固件实测 `requested` 随意图变化、
> `applied` 真被执行、松手零帧生效、deadman 在固件侧限幅并点名原因。健康屏直接渲染 `robot.health`
> 真字段，**缺失显示「未读到」而非 0**（一手 `HealthResult` / `LoopHealth` 注释）。详见 `tools/c2_drive_gate.sh`。

> 🔑 **阶段 C2 已闭环（2026-11-12）**：core 经纯字节 relay 接到 WSL2 里编译好的**真 Rust robotd**，
> handshake / hello 版本差异 / health / -32601 / robot.subscribe 全部由真固件应答，**无 canned 响应**。
> 证据边界：那份固件是 **B 代 DuckBuddy-main（API_VERSION=16 / daemon 0.10.0）**，不是 fanhao API40；
> 验的是跨版本共通的传输/会话语义，**不证明** fanhao 特有方法面。C2 当时未起 body_server ⇒
> 控制循环 `ticks=0`、真 `robot.state` 通知流不可达，标 `INCONCLUSIVE_LIVE_STATE_STREAM`；
> **该悬案已由下面 C2+ 在仿真固件层消掉**。详见 `tools/c2_gate.sh`。
>
> ✅ **阶段 C2+ 已闭环（2026-11-12）**：Windows 起真 `body_server`（MuJoCo）+ WSL 真
> `robotd --sim <网关>:7801` ⇒ 50 Hz 控制循环真跑（`ticks>0 / achieved_hz≈50 / healthy=true`），
> `robot.state` **真通知流**到 App。`C2PlusLiveCheck` **24/24 活体断言全绿、连跑 3 次无偶发**：
> 帧结构/时序/50Hz 量级、`streamMethod` 过滤、重复订阅替换速率、**断链→重连→自动重订阅→通知流恢复**。
> 断链由独立控制端口注入（只关 socket、零字节注入；一手依据 Shopify Toxiproxy 独立控制面 +
> `reset_peer`/`limit_data`），数据面仍**零 canned**；`FAULT_INJECT_DROP pairs=2` 实测留痕。
> 🔴 边界：这是 **B 代 API16 真固件 + MuJoCo 仿真体**的状态流，**不是真机状态流**，也不证 fanhao API40；
> 真机 50 Hz 抖动 / 传感器 / BLE GATT 时序仍 UNVERIFIED。

> ⚠️ **四后端中 Mock / Tcp / Ble 已落地并真测**（WebRtc 属 P2 视频，尚未实现）。但 **BLE 真机 GATT I/O（`AndroidBleGattLink` 的 bonding/CCCD/onCharacteristicWrite 时序）本机无 Android 真机/无整机，仅编译验证、未上板**；`core` 的 BLE 协议编排已用 `FakeGattLink` 在 JVM 真测。真机联调待整机落地。

> 需求与功能清单见 `docs/active/microduck-安卓App功能调研-2026-11-12.md`；
> 落地计划见 `docs/active/microduck-安卓App-P0开发计划-会话层与仿真开发模式-2026-11-12.md`。

## UI / IA 重构（2026-11-12 晚）

用户反馈链：「界面有点丑，屏幕顶部遮住了」→「双摇杆 + 中间取景框 + 实机状态数据」→
「取景框过宽时摇杆叠加在取景框上」→「再加点监测数据」→「找资料让布局合理」→
「一个界面放不下，应拆分界面、遥控页横屏」→「自动/手动模式可选」→
「多找点遥控车/飞机/机器人的开源 App 设计方案，取长补短」。

### 最终架构

| 页面 | 方向 | 内容 |
|---|---|---|
| `MainActivity` | 竖屏 | 连接 / 模式选择 / 进入遥控；三页 **状态 · 健康 · 设置**（M3 3–5 destinations） |
| `DriveActivity`（手动） | `sensorLandscape` 横屏 | 取景框铺满全屏 + 左右下角双摇杆叠加 + 顶部**无背景紧凑只读 HUD**（FPV OSD 风格）+ 底部计数/回显 |
| `DriveActivity`（自动） | 同上 | 同上但**无摇杆**、零驾驶帧，显式写明「App 无停车能力」+「切回手动」按钮 |

`SessionHolder` 单例持有唯一 `RobotSession` / `robot.state` 订阅 / 模式 / 遥测；
`DriveController` / `HeadController` **只由 DriveActivity 持有**，`onStop` 立刻归零停心跳
⇒ 退回控制台机器人必停。`SettingsStore` 用 SharedPreferences 持久化纯参数。

### 布局的一手依据（不是靠感觉）

- **Android 15 / targetSdk35 强制 edge-to-edge**：官方明确 "top offset is disabled"，顶部遮挡不是
  普通 padding bug ⇒ `ViewCompat.setOnApplyWindowInsetsListener` + `systemBars()/displayCutout()`
  padding + 状态栏 scrim；横屏刘海在侧边，左右摇杆与退出按钮都让开 cutout。
- **M3** `foundations/designing/structure`：触控目标 ≥48dp、间距 ≥8dp；
  `components/navigation-bar/guidelines`：3–5 个顶层目的地用 navigation bar；
  `components/snackbar/guidelines`：半透明容器文字要清晰 ⇒ 浮层 alpha≈238。
- **双拇指热区**：arXiv:2110.08753 横屏实测摇杆中心距左/下边 9.8–19.4mm 为推荐区；
  Uni Bonn RoMan 2012 §B.1 全屏相机画面 + 左右下角双虚拟摇杆、双手握持双拇指操作。
- **手势冲突**：官方 gesture-nav 文档 `setSystemGestureExclusionRects()` 只对左右边缘返回手势
  局部 opt-out；**底部 home 手势不可 opt-out** ⇒ 靠 bottom padding 让开，且**不隐藏系统栏**
  （官方 immersive 文档：只在收益超过「单纯多占屏幕」时才隐藏）。
- **拆页**：M3 Navigation bar、Weston Robot Teleop「driving view has its own arrangement ...
  kept separately from the dashboard's」、RoMan 2012 §A 模式/页面选择与控制视图分离、
  QGC 官方 Fly View 的 View Selector（Fly / Plan / Analyze / Setup）。
- **方向**：官方 `<activity>` 文档 `screenOrientation` 是 per-Activity 属性；
  `uses-feature ... required="false"` 避免 Google Play 按方向过滤设备。
  ⚠️ Android 16 (API36) 在 `sw>=600dp` 大屏会忽略方向限制，本项目 targetSdk35 / 手机暂不受影响，
  **未来升 36 或上平板必须改响应式布局**。
- **模式语义**：NIST UTAP 3.2.19 / Sheridan LOA。MANUAL = 人的连续输入；
  AUTO = supervisory **监督/监测视图**，App 零驾驶帧。契约里虽有 `robot.do` / `robot.loadPolicy`，
  但**无整机、未验证策略启停** ⇒ 不调用、不宣称已启动自主行走。

### 开源方案「取长补短」（仓库均经 GitHub 官方 API 核验）

完整对照表、原文摘录、采纳/不采纳理由见
`docs/active/microduck-安卓App-开源遥控App设计对照-2026-11-12.md`。摘要：

| 来源 | 采纳 | 明确不采纳 |
|---|---|---|
| `ob-f/OpenBot`（3659★，MIT） | 档位可读性、**控制回显**「最后输入」、随时停车安全措辞、R1 一键接管 ⇒ 自动页「切回手动」 | ❌ 它的 `DefaultActivity` **单屏塞满**正是用户否决的做法 |
| `mavlink/qgroundcontrol`（5112★） | Fly/Setup 分离、顶部只读 Telemetry/Status、视频主显示 | ❌ 地图/航点/参数调优：无已验证导航栈，画出来就是假地图 |
| `Lukaszm94/AndroidROSRobotTeleoperation` | **SP/PV** 速度曲线 ⇒ HUD「命令→实际」 | ❌ 手机倾斜体感：未上板验证、会让实体机器人动 |
| `livekit-examples/teleop`（MIT） | yaw/pitch degree scales ⇒ HUD「头部 °」；View/Operator ⇒ 模式切换 | — |
| `SuhasDissa/ROS_Robot_Controller`、`ohho-robotics/ohho.apk` | **设置持久化**；ohho 的 **LIVE/DEMO 显式标注** ⇒ 驾驶页「数据来源标签」 | ❌ Arena/RTSP 双播放器（无视频通道）；❌ 6 项底部栏破 M3 上限 |
| `NextGTI/ble-rc-controller`（MIT） | 可调 **dead zone**、连接状态点、松手/切 App 即停、keep-alive | ❌ 冷启动自动连上次设备（会话内重连已由 `RobotSession` CAS guard 覆盖） |
| `LeandroPiqueira/CarDroiDuino`、`DroneBridge/*` | 印证 relay / UDP netpad 分层 | ❌ 加速度计操控 |
| `DroidPlanner/Tower`（632★，Java） | 平板横屏飞行视图的历史佐证 | 已停更，仅参照 |

**刻意不持久化的两项（安全取舍）**：`ControlMode`（每次冷启动强制回 MANUAL，保住手动接管入口）
与 `host:port`（连接必须由用户主动发起）。真机门禁已为这两条加了负对照。

### 本轮代码与验证

新增 `SettingsStore.kt`、`PreviewPlaceholderView.kt`、`DriveActivity.kt`、`SessionHolder.kt`；
重写 `MainActivity.kt`、`AndroidManifest.xml`、`JoystickView.kt`、`styles.xml`、`tools/device_ui_check.py`。
零新增依赖（Material Components Views 1.12.0 + AppCompat，ViewCompat 走传递依赖）。

- `bash tools/selftest.sh` ⇒ **230 passed / 0 failed**（`SELFTEST_RC=0`）。
- `JAVA_HOME=E:/软件工具/OpenJdk17 ./gradlew :app:assembleDebug --offline` ⇒
  **BUILD SUCCESSFUL / GRADLE_RC=0**（`compileDebugKotlin` 真执行）。
- `adb install -r` ⇒ `Success`；`python tools/device_ui_check.py` ⇒ **59 passed / 0 failed**
  （脚本共定义 59 条断言，连跑 3 次 RC=0；最近一次实测 2026-11-13）。
- 门禁覆盖：主页竖屏 / 遥控页横屏、双摇杆左右分离、取景框占位（不伪造视频）、
  HUD 六格（含 SP→PV、头部 °）、LIVE/DEMO 标签、控制回显、心跳正对照、
  松手/`ACTION_CANCEL` 归零负对照、退出停车、自动零驾驶帧、状态页 4 列紧凑栅格单屏可见、
  **A1 BLE 连接面板进设置页（运行时权限 + 扫描入口）**、设置跨冷启动持久化、
  冷启动强制回手动、全生命周期零 FATAL。
- 🔴 数据来源不串源：HUD 新增两格**只读 `robot.state`**，Mock 不推流 ⇒ 一律「— 未读到」，
  绝不用本地意图/计数器补值；「本地刷新」明确标为 App 自观测、非实机数据。

## 🔑 设计主线：一个接口，四个后端

App 的骨架是 `RobotTransport` 抽象——四个后端收发**同一份 NDJSON JSON-RPC 2.0**，
上层会话层 + 所有屏幕只面对接口。于是**无整机期能用 Mock/TCP 把会话层全测完，整机落地只换 BLE 后端**。

```
        UI 屏幕（发现/健康/配网/升级/日志/策略）—— 后续补
                    │  只依赖 RobotSession
        ┌───────────▼────────────┐
        │  RobotSession 会话层     │  握手状态机 / 去重退避重连 / 重认证 / 重订阅 / 幂等重放 / 错误码分类
        └───────────┬────────────┘
                    │  RobotTransport（唯一抽象）
     ┌──────┬───────┼────────┬──────────┐
   Ble   Tcp    WebRtc    Mock
  真机  仿真+relay 驾驶+视频  无后端自测
 (P0-D✅)(P0-C✅C1+C2)(P1/P2) (P0-A ✅)
  ↑core编排真测/app GATT仅编译↑ ↑真固件活体已验↑
```

**为什么能换后端**：官方设计意图就是同一套 serde 消息类型复用在 BLE / WebRTC 数据通道上；
`robot.*` JSON-RPC 在 unix socket / BLE / mediad control datachannel 上是同一份协议。
`robotd` 只在 unix socket 服务，Android 连不了 → 仿真期经 PC 侧 `ssh -L`/relay 转 TCP。

## 版本基线（已查官方矩阵，别乱改）

| 项 | 值 | 依据 |
|---|---|---|
| Kotlin | **2.4.0** | 用户指定；官方 2026-07-14 稳定版；K2 唯一引擎，**不能回滚 K1 / `-language-version=1.9`** |
| JDK | **17**（`E:/软件工具/OpenJdk17`） | 实测 Kotlin 2.4.0 编译器 + target 17 + 产物 major 61 全通 |
| jvmTarget | **17** | 同上 |
| AGP | **8.9.1** | KGP 2.4.0–2.4.10 支持 AGP 8.5.2–9.1.0；AGP 8.9.x 最高 compileSdk 35（官方 KGP 表 + AGP 8.9 发布说明） |
| Gradle | **8.11.1**（wrapper） | KGP 支持 Gradle 7.6.3–9.5.0；**AGP 8.9.x 要求 Gradle 最低 8.11.1**（真构建抓出后修正） |
| Gson | **2.10.1** | 本机 Gradle 缓存现成；Android 常用 JSON 库 |

来源（**三条交叉约束必须一起查**，只查一条会翻车）：
① Kotlin 官方 `docs/gradle-configure-project.html` KGP 兼容矩阵；`docs/whatsnew24.html`；
② Android 官方 `developer.android.com/build/releases/agp-8-9-0-release-notes`（AGP 8.9 ⇒ Gradle 8.11.1 / JDK17 / API≤35 / Build Tools 35.0.0）；
③ Gradle 官方 `docs.gradle.org/current/userguide/compatibility.html`（Gradle 运行需 JDK 17–27）。2026-11-12 核。

## 模块结构

- `core/`（**纯 Kotlin/JVM，无 Android 依赖**）—— 可脱离 Gradle/模拟器，用 kotlinc 直接真编译真测：
  - `Wire.kt` —— NDJSON 模型、方法常量、错误码。严格对齐 fanhao `duck-ipc-proto/src/lib.rs`：
    `API_VERSION=40`、`hello`(带 api_version) → `system.authenticate`(v4 起 BLE 必过)、
    `robot.subscribe`(订阅动作) vs `robot.state`(通知 method，两者**不同字符串**)、
    错误码 `PERMISSION_DENIED=14` / `METHOD_NOT_FOUND=-32601` / `INVALID_PARAMS=-32602`。
  - `RobotTransport.kt` —— 传输抽象接口 + 连接目标 + Disposable。
  - `MockTransport.kt` —— 内存后端：canned 响应 + 可编程故障注入（断连/丢帧/错误码/延迟）+ 线程安全。
  - `TcpTransport.kt`（**阶段 C1**）—— 真 Socket 后端：`BufferedReader.readLine()` 按 NDJSON 行分帧
    （一手 Oracle JDK17 API：`\n`/`\r`/`\r\n`/EOF 终止、内部缓冲自动处理半包/粘包、EOF 返回 null 作断连判据）；
    独立读线程按「有无 `id`」分流响应 vs 通知；断连唤醒所有 pending + 触发 onDisconnected；
    `soTimeout` 默认 0（**读超时≠断连**，一手 Oracle `Socket.setSoTimeout`：超时抛 `SocketTimeoutException`
    但 **Socket still valid**，故读线程捕获后回到循环继续读，不误判断连；half-open（对端静默消失、
    不发 FIN/RST）仍需应用层心跳，C2+ 验的是**对端主动断链**，half-open 未验）。
  - `RobotSession.kt` —— **会话层（P0 核心）**：状态机 `DISCONNECTED→HELLO→[AUTH 仅 BLE]→READY`、
    去重退避重连（in-flight CAS guard + jitter）、重订阅、pending 幂等重放（只读重放/写类不重放）、错误码分类、serial 身份。
    🔑 **`AuthPolicy`（阶段 C2 真固件抓出并修）**：`system.authenticate` 只由 **BLE transport(btd)** 回答，
    TCP/unix/WebRTC 链路发它会被真 robotd 回 `-32601` ⇒ `AUTO` 只对 BLE（及模拟 BLE 的 Mock）要求 PIN；
    旧版无条件认证会让 TCP 仿真模式握手必失败，而 Mock 自带 canned 认证应答，103/103 全绿也照不出来。
  - `C2LiveCheck.kt`（**阶段 C2 活体验证**，独立 main）—— 用现成 `TcpTransport`+`RobotSession` 连真
    `robotd`，11 条断言（含「强制 REQUIRED 必须失败」证明 relay 没有偷造 canned 认证应答）。
    ⚠️ 它**不进** `bash tools/selftest.sh` 的默认断言集（默认自检不依赖 WSL/Rust），由 `tools/c2_gate.sh` 单独跑。
  - `BleChunkCodec.kt`（**阶段 D**）—— BLE GATT 分帧，**一比一移植** fanhao `duck-ble/src/framing.rs`：
    `MAX_LINE=8KiB`(收请求紧边界)/`MAX_REPLY_LINE=64KiB`(收回复松边界)、`FLOOR_MTU=20`、`MAX_ATTRIBUTE_VALUE=512`；
    `notification_payload(mtu)=(mtu-3).clamp(20,512)`（**517→512 静默丢字节回归**，本 App 一手发现）；
    `chunks(line,mtu)`（换行计入 payload、自动补帧界）+ `Reassembler`（forRequests/forReplies 方向区分、
    空行跳过、CRLF 容忍、超长/非 UTF-8 清空 buf 拒收）。
    ⚠️ **出站固定 `chunks(line, 20)`、入站 `forReplies()`** —— duckctl 一手调用选择，别自作聪明用协商 MTU。
  - `GattLink.kt`（**阶段 D**）—— BLE GATT I/O 抽象，**把唯一依赖 Android 的部分隔离到接口后**：
    connect/readApiVersion(促成加密配对)/setNotificationHandler/writeChunk(串行+确认)/mtu/close。
    契约：实现方必须**单操作串行等回调** + **write type=WRITE_TYPE_DEFAULT(acknowledged)**。
  - `BleTransport.kt`（**阶段 D**）—— BLE 协议编排（纯 JVM）：出站按 20B 切块串行写、入站 for_replies
    重组后按 id 分流（与 TcpTransport 同构）、connect 先 read RPC_UUID 促成配对。会话层零改动。
  - `src/test/kotlin/.../LocalRelayServer.kt`（**阶段 C1 测试夹具**）—— 本地纯 JVM `ServerSocket`
    模拟 robotd 对端语义（hello/auth/health/subscribe/robot.state 通知/错误码），可编程：
    粘包（多条一帧）、半包（单字节分次 flush）、一次性断链、**握手中间态连续断链**（逼重连重入）。
  - `src/test/kotlin/.../FakeGattLink.kt`（**阶段 D 测试夹具**）—— `GattLink` 的 JVM 协议等价对端：
    收 20B chunk 重组请求、回 canned 响应并**按 notification chunk 切碎**回调（验客户端跨片重组）。
    ⚠️ 它/ LocalRelayServer 都**不是真固件**，是协议语义等价对端，让真 I/O 在无整机期可测。
  - `src/test/kotlin/.../CoreSelfTest.kt` —— 自检 harness，**每条正向断言配负对照**（`[1-21]`）。
  - **P1+ 手势状态机（Passive View 抽层）**：`JoystickModel.kt` —— 纯 JVM，零 Android 依赖。
    `TouchEvent`(Down/Move/PointerUp/Up/Cancel) → `StickOutput`(Move/Release/Noop)；
    🔴 按 **pointer ID** 追踪活跃指（官方 `gestures/multi`：index 会变、ID 稳定），
    主指抬起切到仍活跃的另一指、最后一指/UP/CANCEL 归零、`invertY` 只翻 y、圆形限幅、
    release 幂等不重复零帧。`JoystickView` 退成薄壳（只翻译 MotionEvent + 绘制）。
  - **P1 驾驶/健康（纯 JVM）**：
    - `Twist.kt` —— `MoveParams{vx,vy,vyaw}` 的 Kotlin 映射；`deny_unknown_fields` ⇒ params **恰好三键**。
    - `NetpadWire.kt` —— fanhao `padd/src/udp/wire.rs` **28 字节逐字节移植**（DKPD / LE / seq / t_ms / 6×i16 轴 / u16 按钮）。
      🔴 显式实现 Rust `f64::round` 的 half-away-from-zero，不用 Kotlin `roundToInt()`（负半值差 1 LSB）。
    - `DriveController.kt` —— 摇杆→物理量（死区/圆形限幅/右杆取负 vyaw）、松手归零、100ms 心跳
      （门禁 `< netpad timeout 250 < deadman 500`）；`stop()` 发零帧并停心跳。
    - `DriveSink.kt` —— `JsonRpcDriveSink`（`robot.move` notification）与 `NetpadDriveSink`（真 UDP datagram）；
      R4 待拍板 ⇒ 两条都实现、运行时切换。
    - `HealthSnapshot.kt` —— `robot.health` 真字段 null-safe 解析；`battery` / `achieved_hz` 缺失渲染「未读到」
      而非 0；百分比直接取固件值（一手 `HealthResult` 注释：客户端不要自己按电压算）。
  - **P1 活体检查**：`DriveLiveCheck.kt`（真固件驾驶，独立 main，不进默认 selftest）/ `C2LiveCheck.kt` /
    `C2PlusLiveCheck.kt` / `LocalRelayServer.kt` / `FakeGattLink.kt`。
- `app/`（Android UI **零新依赖**：只用框架 View + core）——
  - `ble/AndroidBleGattLink.kt`（**阶段 D**）—— `GattLink` 的 Android 实现：connectGatt→discoverServices→
    requestMtu→read RPC_UUID(配对)→setNotify+写 CCCD `0x2902`；**单操作串行 latch** 等
    `onCharacteristicWrite`/`onDescriptorWrite`/`onMtuChanged`；WithResponse；API 33+/26 兼容分支。
    ⚠️ **可编译骨架、未在真机验证**（无 Android 真机/整机），GATT I/O 须上板验收。
  - `JoystickView.kt`（**P1**）—— 原生 Canvas 摇杆。🔴 `ACTION_UP` 与 `ACTION_CANCEL` **同走归零**
    （官方：父容器拦截时最后一条是 CANCEL，只处理 UP 会让机器人继续走）；`onTouchEvent` 恒返回 true；
    `forceRelease()` 供 Activity 生命周期归零；`invertY` 对应 `udp-pad.md --invert-y`（真机 R17 映射决定方向）。
  - `MainActivity.kt`（**本轮重写**）—— 竖屏控制台：连接 / 手动·自动模式 / 进入遥控 +
    状态·健康·设置三页。健康页渲染 `HealthSnapshot.summary()`；设置页写 `SessionHolder` 并
    经 `SettingsStore` 落盘。连接地址留空=Mock 演示、填 `host:port`=连 PC relay 的 TcpTransport。
    🔴 **不持有 controller**，也不在 `onDestroy` 关 session（由 `SessionHolder` 拥有）。
  - `DriveActivity.kt`（**本轮新建**）—— 横屏全屏驾驶/监督页；`onStop` 主动
    `forceRelease()` + `drive.stop()` + `head.stop()` 停车与回中。
  - `SessionHolder.kt` / `SettingsStore.kt` / `PreviewPlaceholderView.kt`（**本轮新建**）——
    跨页共享会话、参数持久化、明确标注「非实时视频」的取景框占位（绝不画假帧）。

## 验证命令

### core 会话层自检（**推荐**，最轻、最快、无需 Android/Gradle）
```bash
bash tools/selftest.sh
```
干三件事：用 **真 Kotlin 2.4.0 + JDK17 + `-jvm-target 17`** 编译 core+harness →
把 gson 合并进 `build/fat/`（绕开 Windows classpath 分隔符坑）→ 跑 main，失败 exit 1。
当前结果：**230 passed / 0 failed**（`[22-24]` 头部控制 / `robot.head` / `robot.state`
缺失≠零 后，连跑多次无偶发）。覆盖：
`[1-7]` Mock 后端（握手/业务/重连/幂等重放/错误码/状态门禁/并发负对照）+ `[8-12]` **阶段 C1 真 Socket**
（换后端零改动、TCP 粘包/半包分帧、真断链→重连→重握手→重订阅、错误码经真 socket 透传、
**握手中间态连续断链无重连风暴回归锁**）+ `[13]` soTimeout 读超时≠断连负对照（真 socket idle 跨 5 次超时）
+ `[14]` **阶段 D framing.rs 12 组测试逐条移植**（跨 chunk 重组/一帧多行/尾部半行/空行/CRLF/超长拒收/
方向边界 8KiB vs 64KiB/非法 UTF-8/全 MTU 往返/恰好一个换行/517→512 回归）
+ `[15]` **阶段 D 换 BleTransport 后端真 chunk I/O**（FakeGattLink：会话层零改动、出站 20B 切块、
入站跨 7B 通知分片重组、按 id 分流、断连重连重认证、连接/读版本/写失败负对照）
+ `[16]` **阶段 C2 认证归属回归锁**：TCP/AUTO 不发认证仍 READY、强制 REQUIRED 在真固件语义下必失败、
BLE/AUTO 仍走 PIN、显式 SKIP 可覆盖
+ `[17]` **P1 netpad 28B wire 逐字节移植**：手写期望字节数组（不从被测代码反推）、Rust
  `round-away-from-zero` 负半值 `-0.5→-16384(0xC000)`、decode 往返、短包/坏 magic/错版本/超范围 clamp/
  保留位/timeout<deadman 数值约束，全部带负对照
+ `[18]` **P1 驾驶控制**：满杆 vx / 右杆 vyaw 取负（一手 `MoveParams` +左转）、死区、对角圆形限幅、
  `onAxes` 立即发帧、松手归零（负对照：不 release 仍非零）、心跳持续重发（负对照：未启动不自发发包）、
  `stop()` 归零关通道、心跳周期 ≥ timeout 被门禁拒绝
+ `[19]` **P1 双通道**：`robot.move` notification **无 id**、params **恰好三键**（`deny_unknown_fields`）、
  带 id 的 `RpcRequest` 同类行确实有 id（断言不恒真）、DISCONNECTED 时 notify 不发包；
  **真 UDP socket** 收发 28B 数据报、摇杆值往返、seq 递增、close 后再 send 失败
+ `[20]` **P1 健康快照**：`battery` 缺失 ⇒ null 且渲染不是 0 V、`achieved_hz` 缺失 ⇒ null 且不是 0 Hz、
  `startup_failures>0` 提示舵机未上电、百分比直接取固件值（负对照：0 不误报）。

### C2 活体验证（连真 `robotd --sim`，需 WSL2 + 已编译 robotd）
```bash
# 先跑一次 selftest.sh 把 C2LiveCheck 编进 build/fat，再执行单次前台 harness：
export MSYS2_ARG_CONV_EXCL='*'
wsl.exe bash -lc 'bash /mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app/tools/c2_gate.sh'
```
`c2_gate.sh` 一次托管全生命周期：起真 `robotd --sim` → 等 `/run/robotd.sock` → 起
`c2_relay.py`（**纯字节** AF_UNIX↔TCP 转发，零 canned 响应）→ 调 Windows JDK17 跑 `C2LiveCheck` → kill。
实测 **C2 RESULT: 11 passed, 0 failed / C2_GATE_RC=0**。
`tools/c2_probe.sh` + `c2_probe.py` 是前置一手契约探针（不改代码，直接问真固件
hello/authenticate/health/subscribe 的真实应答），阶段 C2 的认证结论就来自它。
⚠️ 为什么必须 WSL 内**单次前台** harness：`wsl.exe` 在后台/非交互上下文报 126（仿真鸭文档 §9.7）。

### C2+ 活体验证（真状态流 + 断链重订阅，需 Windows body_server + WSL2）
```bash
# ① Windows 侧（Git Bash，前台常驻或 background 任务）：起 MuJoCo 仿真体
bash tools/c2_body_server.sh
# ② 本机：编译出 build/fat（含 C2PlusLiveCheck.class）
bash tools/selftest.sh
# ③ WSL2 单次前台 harness：真 robotd --sim <网关>:7801 + 零 canned relay + 断链控制面
export MSYS2_ARG_CONV_EXCL='*'
wsl.exe bash -lc 'bash /mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app/tools/c2_gate_plus.sh'
```
- `c2_body_server.sh` 用**现成** `microduck-software/.venv-mjlab/Scripts/python.exe`（torch 2.9.1 / mujoco 3.7.0），
  必须监听 `0.0.0.0:7801`（WSL2 NAT 网关 `172.26.32.1` 才连得上，仿真鸭文档 §9.1/§9.2）。
- `c2_gate_plus.sh` 托管全生命周期并校验 body_server 可达性；`c2_relay_plus.py` 数据面**纯字节零 canned**，
  断链走**独立控制端口 7789**（只 close socket，不注入任何字节/应答；一手依据 Shopify Toxiproxy
  独立控制面 + `reset_peer`/`limit_data`，同型于 `LocalRelayServer.dropTimes`）。
- `C2PlusLiveCheck` 的强负对照：同栈另开**不订阅**的会话 sB，断链重连后仍零帧 ⇒ sA 的恢复只能来自
  会话层重发 `robot.subscribe`（真固件订阅是 per-connection，`robotd/src/main.rs:3366-3371` 局部变量）。
- 实测 **C2PLUS RESULT: 24 passed, 0 failed**，连跑 3 次无偶发，`FAULT_INJECT_DROP pairs=2`；
  原 C2 门禁复跑仍 **11/11**（C2+ 用独立 relay，未改动已验证的 C2 证据链）。
- `tools/c2_state_probe.py` + `c2_state_gate.sh` 是前置一手契约探针（先于 Kotlin 断言问真固件
  「无订阅是否零帧 / 订阅后帧结构 / 重订阅是否替换速率」），实测 hz=4→10 帧、hz=10→19 帧/2s。

### P1 驾驶活体验证（真固件 `robot.move`，需 Windows body_server + WSL2）
```bash
# ① Windows 侧起 MuJoCo 仿真体（常驻）：bash tools/c2_body_server.sh
# ② 本机编译 build/fat：bash tools/selftest.sh
# ③ WSL2 单次前台 harness（复用**未改动**的 c2_relay.py，纯字节零 canned）
export MSYS2_ARG_CONV_EXCL='*'
wsl.exe bash -lc 'bash /mnt/e/WorkBuddy/2026-10-23-08-26-15/microduck-android-app/tools/c2_drive_gate.sh'
```
`DriveLiveCheck` **28/28、连跑 5 次无偶发**；复跑原 C2 仍 **11/11**、C2+ 仍 **24/24**。断言主线：
基线 `requested/applied` 全 0 → `DriveController` 心跳发 `robot.move` notification ⇒ 真固件
`requested≈0.3`、`applied>0.05`、无 deadman → 松手零帧 ⇒ `requested` 归零 → 带 id 的 request
路径也生效（`accepted=true`、`requested≈0.2`）→ **只停发不发零** ⇒ `requested` 仍是 0.3 但
`applied` 指数衰减 >99% 且 `limited_by` 点名 `deadman`（跨进程复现上游 `:5220-5270` 单测）。

🔴 判据边界：上游单测的 `applied == 0` 只在**冷启动**（`twist_ema` 初值 0）成立；本检查是稳态驱动后
停发，按 `cmd_alpha=0.2`（`robotd-params:1111`）每 tick ×0.8 指数衰减，实测
`0.0403→0.0132→0.0035→0.0011`，比值 ≈ `0.8^5=0.328`（50Hz tick / 10Hz 状态帧）。
**照抄 `==0` 是判据外推错误，不是产品 bug**；已改为单调衰减 + 衰减比 + 量级判据。
⚠️ 该真固件是 B 代 API16，**没有 netpad**；UDP 通道只由 `[17]/[19]` 在 JVM 真 UDP socket 上验证。

### P1+ 真机 UI 活体门禁（adb + 已授权 Android 真机）

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
python tools/device_ui_check.py
```

脚本只用 `adb` + `uiautomator dump`（**无 Robolectric / 无模拟器**），对设备只读 + 注入触摸，
不修改手机系统设置；只对自己的包做 `force-stop`/`start`，不卸载、不清数据。
多页版实测 **59/59 全绿**（vivo V2338A / Android 16 / API 36，脚本共 59 条断言，连跑 3 次 RC=0）；旧单页版曾 16/16 连跑 3 次。
判据靠 UI 层级里能真读出来的「已发 N 帧」：心跳在跑时增长（+41）→ `ACTION_UP` 松手后 `+0`
→ 保持按下又恢复（排除「App 卡死导致假阴」）→ `ACTION_CANCEL` 注入后同样 `+0`
→ 退出遥控页 `+0` → 自动模式 `+0`（零驾驶帧）。
另验：主页竖屏 / 遥控页横屏（hierarchy rotation）、双摇杆左右分离、HUD 六格、
LIVE/DEMO 数据源标签、设置跨冷启动持久化（`checked` 真读回）、冷启动强制回手动、
全生命周期零 FATAL。
🔴 `dump_nodes()` 会删旧 XML 并校验 `uiautomator dump` / `adb pull` 的 rc 与文件非空 ——
不校验就会读到陈腐 hierarchy 制造「心跳停了」的假读数（见踩坑 27）。
⚠️ `adb input motionevent` 只支持 `DOWN/UP/MOVE/CANCEL`，**不能注入多指**；
多指/ID 漂移由 core 的 `JoystickModel` 在 `selftest [21]` 里非插桩真测。

### Gradle 完整构建 / 产出 APK（首次需联网拉依赖）
```bash
JAVA_HOME=E:/软件工具/OpenJdk17 ./gradlew :core:compileKotlin :core:compileTestKotlin :app:assembleDebug
```
（Windows 上用 `gradlew.bat`，配好 JAVA_HOME=JDK17）
实测 **BUILD SUCCESSFUL in 45s** ⇒ `app/build/outputs/apk/debug/app-debug.apk`（1.06 MB / 5 个 dex，
已验证 dex 内含 `JoystickView`/`MainActivity`/`DriveController`/`NetpadWire`/`NetpadDriveSink`/
`HealthSnapshot`/`JsonRpcDriveSink`）。**零新增依赖**（不引 Compose/androidx）。

## ⚠️ 踩过的坑（写下来防复发）

1. **必须用真 2.4.0 编译**，IDEA 2023.2.3 自带的是 1.9.0，且 2.4.0 起不能回滚 K1——1.9.0 编译通过**不能**当 2.4.0 的证据。故 `tools/selftest.sh` 优先用 `/tmp/kotlin240/`（下载脚本见文件内）。
2. **Git Bash（MSYS2）会把 `/` 开头的参数自动改写成 Windows 路径**（一手：git-for-windows
   discussion #3038 / MSYS2 path conversion）：`/tmp/x` → `C:/Program Files/Git/tmp/x`，
   Windows `java.exe` 拿到错路径 ⇒ 找不到类。**曾为此纯试错约 70 次工具调用**（Pass130 审计揪出，
   当时没先查机制）。✅ 正解：产物输出到项目 `build/`，运行时用相对路径（不以 `/` 开头 ⇒ 不触发改写）。
3. **classpath 分隔符 Windows 是 `;`、其它平台是 `:`**（一手：Oracle `java` man 页
   "On Windows, semicolons (`;`) separate entities in this list; on other platforms it is a colon (`:`)"）。
   Windows `java.exe` 要 `;`，但 bash 里 `;` 需引号、且 `:` 分隔的路径列表本身**又触发 MSYS 改写**
   —— 两个坑叠加才是当年稳不住的真因。✅ 正解：`build/fat/` 单目录法——gson + selftest 类解压到同一目录，
   classpath **只给单个相对目录**，既无分隔符又无 POSIX 路径（这就是 fat 目录法的机制，非玄学）。
3b. **`Socket.setSoTimeout` 读超时 ≠ 断连**（一手：Oracle JDK17 官方
   "If the timeout expires, a `SocketTimeoutException` is raised, **though the Socket is still valid**"；
   `0` = infinite）。`TcpTransport.readerLoop` 必须把超时捕获放在 `readLine` 内层、**回到循环继续读**，
   不能 fall-through 到 `finally` 误判断连。曾有一版注释写「超时后底层流进入不确定态，按断连处理」是
   **没查证的推断、与官方相反**（Pass130 审计揪出），已纠正 + 加负对照 `[13]`。
4. **Gson `JsonObject` 没有 `optString/optBoolean/optInt`**（那是 org.json 的 `JSONObject` 方法）——用 null-safe 辅助函数。真编译抓到，肉眼会漏。
5. **`robot.subscribe` ≠ `robot.state`**：前者是订阅动作（带 hz），后者是推送通知的 method 名。回调过滤要用 `streamMethod=robot.state`，否则永不匹配。一手依据见 `RobotSession.subscribe` 注释。
6. **Mock 必须线程安全**：重连在后台线程调 request，断言在主线程读日志，不加锁会 `ConcurrentModificationException`（真测试抓到）。
7. **重连重订阅是替换不叠加**：robotd 注释「Subscribing again replaces the rate rather than opening a second stream」→ lane 数不随重连增长，Mock 用 `Set`。
8. **验证带负对照**：错 PIN 必须进 FAILED、写类掉线不得重放、未知方法不得假装有数据——只见过绿色的断言不是证据。
9. **Gradle 版本组合查全三条交叉约束**（KGP↔Gradle/AGP、AGP↔Gradle/JDK/API、Gradle↔JDK）：
   起初只查 KGP 表就拍 Gradle 8.9，真构建报「AGP 8.9.1 要求最低 Gradle 8.11.1」→ 修为 8.11.1。
10. **`pluginManagement.google().content` 必须含三组**：`com.android.*`、`com.google.*`、`androidx.*`。
    漏 `androidx.*` / 把 `com.google.*` 写窄 → AGP 传递依赖 `androidx.databinding`、`com.google.testing.platform:core-proto`
    在 Google Maven 被挡，跑去 mavenCentral 找不到 → 构建失败（官方 Android 模板的三组过滤，真构建抓出）。
11. **Gradle distribution 官方域名在本网络下不通**：`services.gradle.org` java.net 10s 超时、
    `downloads.gradle.org` curl 返回 502、curl 直连 `services.gradle.org` exit 7。
    ✅ 解法：**腾讯镜像** `https://mirrors.cloud.tencent.com/gradle/gradle-8.11.1-bin.zip`（阿里/华为镜像也通，
    Content-Length 均 136920070 一致）。下到 `~/.gradle/wrapper/dists/gradle-8.11.1-bin/<hash>/`、
    解压、`touch gradle-8.11.1-bin.zip.ok`，wrapper 即认。wrapper `networkTimeout` 也已调 120000。
    注意：**core 会话层自检不依赖 Gradle distribution**，用 `tools/selftest.sh` 即可，别被这条卡住。
12. **Kotlin 2.4.0 的 `kotlinOptions { jvmTarget = "17" }` 是 error 不是 warning**（"Using 'jvmTarget: String' is an error.
    Please migrate to the compilerOptions DSL"）⇒ 必须用顶层 `kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }`。
    core 模块早用了新 DSL 所以没事，app 模块从旧模板抄的 `kotlinOptions` 被真构建抓出。
13. **别用 `gradlew ... 2>&1 | tail` 的管道尾值当构建结果**——`tail` 的 exit 恒 0，会掩盖 Gradle 的失败
    （曾出现 `gradlew_exit=0` 但日志里 `BUILD FAILED` 的假绿）。要 `> log 2>&1; RC=$?` 单独取码。
14. 🔴 **重连风暴：绝不能用 mutable state 判重，要用 in-flight CAS guard**（阶段 C1 真 Socket 抓到，Mock 30/30 全绿也漏掉）：
    旧 `triggerReconnect` 靠 `state==RECONNECTING` 去重，但 `handshake()` 会把 state 改成 `HELLO→AUTH`；
    弱网下「刚建连、握手**中途**又断」时 state 不是 RECONNECTING → 又起一个 loop → 多 loop 并发 connect，
    后建连接拆掉前一个刚握到一半的链路 → **指数风暴**（实测刷几百条 hello、卡 AUTH、hang 8 分钟）。
    ✅ 修法（一手依据：社区连接锁 isConnecting / Reachy Mini `session.guard.expectedStop` / Jitsi
    `stable-connection-threshold`）：`reconnectInFlight: AtomicBoolean` CAS 保证全程**恰好一个** loop，
    loop 结束（finally）才释放；退避加 ±20% jitter（AWS Builders Library：无 jitter 是指数退避 clear loser）；
    释放前复查链路防「断连回调在 CAS 窄窗口被吞」；`close()` 先置 DISCONNECTED 再关 transport 防残回调抢 guard。
    回归锁 `[12]`：握手态连断 3 次后仍稳定恢复，accept/hello 次数有界（≤8，风暴时几十~几百）。
15. 🔴 **「重连恢复了」要判稳定态，不能用瞬时 state / 单次 awaitReady**（真 Socket 连跑 8 次才抓到的 flaky，5/8 次里 1 次假红）：
    `awaitReady` 抓到的瞬时 READY 可能落在中间某次 attempt 的短暂 READY，随后又进 RECONNECTING →
    紧跟的瞬时断言全红。✅ 修法（一手依据：Jitsi `stable-connection-threshold`「只有稳定连接才重置 attempt/backoff」、
    Apollo `stability=5×delay`、K8s `successThreshold` 连续成功、Open-Kilda antiflap）：`waitStable` 要求
    连续 N ms 都 READY 才算恢复。另：**断言条件与 detail lambda 不能各读一次会变的计数**
    （曾 `cc=2` 却判 FAIL——条件读到 1、detail 重读已 2）；一次取快照再断言。
16. 🔴 **`:core:compileKotlin` 卡住/「daemon disappeared」真根因 = Kotlin 2.4.0 编译器主 jar 只落了 .pom 没落 .jar**
    （2026-11-12 定位并修，之前误当「daemon/网络玄学」搁置）：
    - 症状：配置阶段过了、daemon 日志停在 `The daemon has started executing the build` 后**再无任何输出**，
      编译 11 分钟无进展；用 `timeout 180` 硬杀 daemon 后报 `Gradle build daemon disappeared unexpectedly`
      ——**这个报错是硬超时制造的假象，不是根因**。
    - 根因（靠缓存盘点抓出，非推断）：`~/.gradle/caches/.../kotlin-compiler-embeddable/2.4.0/`
      下**只有 60MB 主 jar 的 pom、没有 jar**（2.0.21 是完整的）。`mavenCentral()` 大文件传输中断只落 pom，
      Gradle metadata 却认为 module 已解析 ⇒ Kotlin daemon 启动即卡在反复重试这个大 jar。
      负对照：无 OOM、无 `hs_err_pid*.log`、无编译错误输出 ⇒ 排除 OOM/crash，锁定依赖缺失。
    - ✅ 修法（两步，缺一不可）：① `settings.gradle.kts` 的 `dependencyResolutionManagement.repositories`
      把**阿里云 central 镜像放最前**（四源 HEAD 实测 200 且 content-length 全等 60,351,320 B：官方
      Maven Central／阿里／华为／腾讯），mavenCentral/google 兜底；② **删掉只有 pom 无 jar 的残缺版本目录**
      强制重下（否则 Gradle 认 stale metadata 不重新拉）。清理带断言：只删「确认无 `*.jar`」的 2.4.0 目录，
      `kotlin-reflect`/`kotlin-stdlib-jdk8` 本链无需单独目录、`trove4j` 是 1.0.x 版本且有 jar，均不动。
    - ✅ 验证：`GRADLE_CORE4_EXIT=0 / BUILD SUCCESSFUL in 40s`（原来卡 11 分钟）；主 jar 60,351,320 B 补齐；
      31 个 class 真生成；`javap -verbose` 见 `major version: 61`(=Java17)；
      `:app:compileDebugKotlin` 也 `BUILD SUCCESSFUL in 26s`（15 tasks executed，验 UI 骨架能 import core）。
    - ⚠️ 别把本地 `/tmp/kotlin240/lib/kotlin-compiler.jar` 塞进缓存顶替：那是**非 embeddable** 版
      （依赖未 relocation），Maven 坐标与 KGP 预期不符。别再 `timeout N` 硬杀 Gradle daemon。
    - 一条 harmless warning：KGP 2.4.0 提示 Gradle 8.11.1 将弃用（2.5.0 起要求 ≥8.14.4）——
      **当前 2.4.0 明确支持 8.11.1**，非失败，别被它诱导乱升版本（升了会破坏上面的三条交叉矩阵）。

17. 🔴🔴 **`system.authenticate` 只属于 BLE 传输层，不是协议层的通用握手**（阶段 C2 真固件抓出的**真产品 bug**，
    修前 103/103 全绿也照不出来）：旧 `RobotSession` 无条件 hello→authenticate，但真 `robotd` 的 unix/TCP 面
    实测回 `{"code":-32601,"message":"system.authenticate is not served by robotd"}` ⇒ TCP 仿真开发模式握手必失败。
    - 一手依据（fanhao 全量源码 `/tmp/fanhao/.../microduck-hd1910/firmware/`）：`duck-ipc-proto/src/lib.rs:44`
      「v4 added `system.authenticate`, which **a BLE client** must now pass」；`btd/src/pairing.rs:24`
      「answered by the **transport** rather than [a service]」；`btd/src/route.rs:987`「must be answered by btd itself」；
      `updater/src/ipc.rs:879`「answered by the **BLE transport**, not by updaterd」；`mediad/src/session.rs:21` 也按名字拒绝。
    - ✅ 修法：`AuthPolicy.AUTO` 按 `transport.kind` 决定（BLE 要 PIN；TCP/WEBRTC 跳过；Mock 是有意模拟 BLE 会话
      的 canned 夹具，保留认证以不丢覆盖）。状态机相应变成 `HELLO→[AUTH 仅 BLE]→READY`。
    - 回归锁 `[16]` 四条负对照；C2 活体第 11 条「强制 REQUIRED 在真 robotd 上必须失败」进一步证明 relay 没造假。
18. ⚠️ **「协议语义等价对端」也会等价错对象，且 canned 应答会掩盖契约错误**：`LocalRelayServer` 原先自带
    `authenticated` 状态与 PIN 校验，实际模拟的是 **BLE 会话面**，而它服务的却是 TCP 链路 —— 于是
    「App 在 TCP 上发认证」这个错误被夹具默默答成 OK。C2 真固件探针才把它揪出来。现默认改为模拟
    真 robotd unix 面（`serveAuthenticate=false`：认证回 -32601、HelloResult 无 serial、无需认证）。
    教训推广：**只要夹具自带对被测结论的「善意应答」，绿色就不是证据**；必须有一条对端按真契约拒绝的负对照。
19. 🔑 **API 版本差异是「报告 + 服务」，不是「拒绝」**：B 代 `lib.rs:552` / fanhao `lib.rs` 顶注都写明
    「No daemon refuses a call because this number differs」。实测 App 发 `api_version=40` 给 API16 真 robotd，
    仍回 `result{api_version:16, daemon_version:"0.10.0", revision:null}`。所以会话层不该硬拒版本，
    也不该依赖 `HelloResult.serial`（真固件没有该字段），能力差异靠 `-32601` 逐方法降级。
20. 🔴 **Python `socket.makefile()` 不能配 `settimeout()` 做 NDJSON 探活**（C2+ 探针第一版全 0 帧假象）：
    官方文档原文 "The socket must be in blocking mode; it can have a timeout, but **the file object's
    internal buffer may end up in an inconsistent state if a timeout occurs**"。而「无订阅者」阶段
    **必然**没有数据 ⇒ 必然超时 ⇒ 之后 `readline()` 永久抛 `OSError('cannot read from timed out object')`，
    连 `hello` 都读不到，所有「0 帧」全是假绿。✅ 正解：socket 保持 blocking，用 `select.select()` 判可读，
    自己按 `\n` 分帧（与 `TcpTransport.readerLoop` 同型）；并加**探针自身通道自检**——`hello` 收不到响应
    就直接判失败（`probe_channel_broken`），否则任何零帧结论都无效。
21. 🔑 **已验证的证据链不要动，新验证用新文件**：C2 的 `c2_gate.sh` + `c2_relay.py` 背后是 11/11 活体结论，
    给 relay 加断链控制面若原地改，等于自己改了自己的证据。✅ C2+ 另起 `c2_relay_plus.py` /
    `c2_gate_plus.sh` / `C2PlusLiveCheck.kt`，并在收尾**复跑原 C2 仍 11/11** 证明没破坏。
    断链注入的边界也据此写死：控制面只 `shutdown/close` socket（Toxiproxy `reset_peer`/`limit_data` 同型），
    **不注入任何字节或应答**，否则「零 canned」就不成立了。
22. 🔴 **Rust `f64::round()` ≠ Kotlin `roundToInt()`**（P1 netpad wire 逐字节移植）：Rust 官方
    "If a value is half-way between two integers, **round away from 0.0**"；Kotlin 走 `Math.round`
    = `floor(x+0.5)`，**负半值偏向 +∞**。`-0.5 × 32767 = -16383.5` ⇒ Rust `-16384(0xC000)`、
    Kotlin `-16383(0xC001)`，差 1 LSB，且普通 roundtrip 测试照不出来。✅ 显式实现
    `if (v >= 0) floor(v+0.5) else ceil(v-0.5)`，并由 `[17]` 手写期望字节数组逐字节锁住。
23. 🔴 **别把上游单测的适用边界外推成活体判据**（P1 第一次活体 24/25）：上游
    `main.rs:5220-5270` 断言 deadman 后 `applied == [0,0,0]`，但那是**冷启动**——`intents.set_twist(0.4)`
    后从未驱动控制循环，`twist_ema` 初值就是 0。本检查先稳态驱动到 0.3 再停发，EMA 有历史值，
    按 `cmd_alpha=0.2`（`robotd-params:1111`）指数衰减（实测 0.0403→0.0011）。
    ✅ 判据改为「单调衰减 + 衰减比 < 0.6（理论 0.8^5≈0.328）+ 最终量级 < 1% + `limited_by` 点名
    deadman」。**判据错 ≠ 产品 bug**，阈值全部从源码推导，不从被测量反推。
24. 🔴 **异步流的基线不能取在动作瞬间**（连跑 3 次抓到 1 次 flaky）：`drive.release()` 后立刻取
    `frames.size()` 当基线，状态帧 10Hz 异步推送，发零帧时还有一帧 0.3 在途 ⇒ 被算进「松手后」
    窗口（`req=[0.3, 0.0]`）。✅ 与 C2+ 同一稳定态判据（Jitsi stable-connection-threshold /
    K8s successThreshold）：先等 >2 个帧周期让在途帧落地再取基线；同样风险处（显式发零帧）一并修，
    修后**连跑 5 次全 28/28**。
25. 🔴🔴 **多指下恒用 `event.x/y`（index 0）是真 bug**：官方 `gestures/multi` 明确
    「pointer index 会随事件变化，只有 ID 稳定」、`ACTION_POINTER_UP` 是非主指针抬起、
    `ACTION_CANCEL` 取消整个手势。旧 View 把 POINTER_UP 落到 `else -> true` 忽略，
    主指抬起后会跟错手指甚至卡在按下态 ⇒ **机器人继续走，属安全事故**。
    ✅ 抽 `JoystickModel` 按 ID 追踪 + 主指抬起切换 + CANCEL 归零；`[21]` 26 条负对照锁住
    （含「忽略 CANCEL 必卡按下态」「若按 index0 会拿到另一指坐标」）。
    ⚠️ `adb input motionevent` **不支持 POINTER_DOWN**，多指只能 JVM 非插桩真测；
    真机侧改为注入 `CANCEL` 验官方语义（16/16 连跑 3 次，三次均 +0 帧）。
26. ⚠️ **真机联调两个环境坑**：① vivo `adb install` 首次报
    `INSTALL_FAILED_ABORTED: User rejected permissions`（`verifier_verify_adb_installs=1` +
    厂商「USB 安装」开关），屏幕并无确认弹窗——别瞎改手机安全设置，重试一次即 `Success`；
    ② Git Bash(MSYS2) 会把 `/sdcard/x.png` 改写成 Windows 路径导致 `screencap`/`uiautomator dump`
    落错位置 ⇒ `export MSYS2_ARG_CONV_EXCL='*'`（同 `selftest.sh` 里 classpath 那个坑）。
    `dexdump.exe` 直接吃 APK 在 Windows 会 `mmap / Bad file descriptor`，须先解压出 `classes.dex`。
27. 🔴 **`uiautomator dump` 假读数（门禁自身的 bug）**：`dump_nodes()` 原来只管把
    `uiautomator dump` / `adb pull` 命令发出去，**不检查成败**。窗口繁忙时 dump 报
    `ERROR: could not get idle state`、pull 失败，而本地 `build/device/uicheck.xml` 还留着上一次的
    陈腐文件 ⇒ `parse_dump()` 读到旧 hierarchy，「已发 40 帧 → 已发 40 帧 (+0)」被误判成心跳停了。
    诊断脚本按 400ms 连续采样 16 次，实测同一时段 **101→810 帧持续增长**，且 rotation / 前台
    Activity 始终是 DriveActivity ⇒ **读数与算术矛盾时错的是读数**，不是产品行为。
    ✅ 修法：改用 `adb exec-out cat` 直接读回**本次** dump 的 XML 并 `ET.fromstring` 解析，
    逐条校验 `returncode` / `ERROR` / 内容含 `<hierarchy`，失败重取；完全不落本地文件。
    异步帧基线另加 `>2` 个心跳周期的 warm-up（同 Pass134 的在途帧教训）。
    ⚠️ **二次坑**：中间版本靠「每轮 `os.remove(本地XML)`」防陈腐，连跑两轮门禁删了 50 次本地文件，
    触发环境 `[SAFE_DELETE_BULK_CONFIRM_REQUIRED] count=50 threshold=50`，脚本在半途被中断
    （日志无 FAIL 也无 RESULT 行，别误判成断言失败）。零落盘方案同时解决两个问题。
28. 🔴 **两个 Activity 并发 tick 踩共享快照**：MainActivity 的 `Handler` tick 在 `onStop` 不停，
    DriveActivity 前台也在跑，两者每秒都调 `SessionHolder.tick()`；原来每次调用都写
    `lastSentSnapshot`，后一个必然算出 `nowSent == lastSentSnapshot` ⇒ `heartbeatRunning` 被判 false，
    界面在心跳明明持续发帧时闪「已停」（真机诊断第 12/14 次采样可见，但帧数仍在涨）。
    ✅ 修法：状态判定按 ~900ms 时间窗去重（同窗只有第一次采样生效）；本地刷新计数改用
    `AtomicInteger` 每次都加，语义明确为 App 自观测、**非实机数据**。
29. 🔴 **拆页后旧断言语义过时，不是放宽门禁**：单 Activity 时代「主页本地遥测驾驶帧必须增长」
    在拆页后是**错**的 —— controller 只由 DriveActivity 持有，主页零驾驶帧正是安全设计。
    ✅ 改为「主页零驾驶帧（负对照：若主页误建 controller 会变红）」，
    并新增「本地刷新计数真在涨」保留「非静态占位」检查。
30. ⚠️ **Kotlin `@Volatile var mode` 与手写 `fun setMode()` JVM 签名冲突**：
    `var` 自动生成 `setMode(L.../ControlMode;)V` ⇒ `Platform declaration clash`，
    `:app:compileDebugKotlin` 直接失败。改名 `selectMode()`。
    另外 `./gradlew ... | tail` 会让 shell 取到 `tail` 的 rc，**日志里 BUILD FAILED 却报 exit 0**；
    构建一律 `set -o pipefail` + 单独取 `${PIPESTATUS[0]}`。
31. 🔴 **第三类窗口污染：下拉通知栏 / 快速设置被当成 App 界面**（连跑首轮实测）：
    设备上一次 USB 调试 / 文件传输通知面板仍展开，`uiautomator dump` 返回的全是
    `com.android.systemui` 节点（「通知中心 / 已开启 USB 文件传输模式 / USB 调试已开启」），
    节点数 ≥8 且不是 `ListView` ⇒ 旧的「节点数 + Spinner popup」判据放行，16 条断言全 FAIL
    、随后 `return 2` 提前退出、日志**无 RESULT 行**。下一轮面板被 BACK 收起就自动 57/57 ⇒
    极易被误判成「偶发 flaky」，实际是门禁读错了窗口。
    ✅ 修法：`parse_dump()` 读 node 的 `package` 属性（实测 App 页 **60/60 节点都是
    `io.microduck.app`**），`dump_nodes()` 加**窗口归属硬判据** `本包节点 >= 3`，否则按 BACK
    收起系统 overlay 重取；负对照用 `cmd statusbar expand-notifications` 主动注入验证。
    同时把所有提前 `return 2` 收口到 `finish(2)` ⇒ **任何退出路径都打印 RESULT**
    （并标注「断言未跑完」），杜绝「既无 FAIL 也无 RESULT」的静默中断。
32. ⚠️ **`MaterialButton` 只换背景不换文字色 = 深底深字**：模式按钮 / 三页 tab 用
    `setBackgroundColor()` 切选中态，但文字色仍取主题 `colorOnPrimary`（深色，本来配亮底），
    真机截图里未选中的「自动模式 / 健康 / 设置」暗成深紫几乎看不见。
    ✅ 修法：`showPage()` / `refreshModeUi()` 里**背景与文字色同步切换** —— 亮底
    (`md_accent`/`md_warn`) 配 `md_bg` 深字、深底 (`md_card_alt`/透明) 配 `md_text` 近白字，
    选中 tab 另用 `md_accent` 高亮 + 加粗；主 CTA「进入遥控驾驶」也显式设 `md_bg` 深字
    （主题默认 `colorOnPrimary` 偏暗紫）。真机截图复验后才算通过，编译绿不算。

## 下一步（P0/P1 已完成，P2 之后）

- ✅ **阶段 C1 已完成**：`TcpTransport` + 本地 `LocalRelayServer`（现默认对齐真 robotd unix 面），真 Socket 验证换后端零改动/分帧/断连恢复/无风暴回归锁。
- ✅ **阶段 C2 已完成（2026-11-12）**：core 经纯字节 relay 连 WSL2 真 `robotd --sim`，**11/11 活体断言全绿**，
  Transport 与会话层零改动（只因真固件暴露的认证 bug 修了会话层策略）。
  ⚠️ 边界写死在 `C2LiveCheck.kt` 头部：真固件是 **B 代 API16**（非 fanhao API40）、当时未起 body_server
  ⇒ `INCONCLUSIVE_LIVE_STATE_STREAM`（该项**已由 C2+ 消掉**）、真机 BLE GATT 未上板。
  **不要把 C2 结果外推成「App 与 fanhao 真机联调通过」**。
- ✅ **阶段 D 已完成（协议层）**：`BleChunkCodec` 一比一移植 `framing.rs` + `BleTransport` 纯 JVM 编排 +
  `AndroidBleGattLink` 骨架；FakeGattLink JVM 真测、Gradle 真编译。**真机 GATT I/O 仅编译、未上板**。
- ✅ **阶段 C2+ 已完成（2026-11-12）**：Windows `body_server` + WSL `robotd --sim <网关>:7801`
  ⇒ 真 50 Hz 控制循环 + 真 `robot.state` 通知流。`C2PlusLiveCheck` **24/24**、连跑 3 次无偶发，
  含**断链→重连→自动重订阅→通知流恢复**与「不订阅对照会话重连后仍零帧」的强负对照。
  `INCONCLUSIVE_LIVE_STATE_STREAM` 在**仿真固件状态流**这层已消；真机 50Hz/传感器/GATT 仍 UNVERIFIED。
  复跑命令见上面「C2+ 活体验证」。
- ✅ **P1 已完成（2026-11-12 / Pass134）**：驾驶屏（原生 Canvas 摇杆、`ACTION_UP`/`ACTION_CANCEL`
  同归零、前后/转向分速可调、方向反转开关、生命周期归零）+ 舵机健康屏（`robot.health` 真字段、缺失≠0）；
  双通道可插拔（JSON-RPC notification / UDP netpad 28B wire）。`core` **163/163**、真固件驾驶
  **28/28 连跑 5 次**、`:app:assembleDebug` 产出可安装 **debug APK**。复跑命令见「P1 驾驶活体验证」。
  ⚠️ 手感参数 `maxVx/maxVyaw` 是占位，按计划文档 §216 **必须整机标定**，仿真不作数。
- ✅ **UI/IA 重构 + 开源方案对照已完成（2026-11-12 晚）**：M3 深色主题、edge-to-edge insets/scrim、
  双摇杆叠加取景框、监测数据分组、多页拆分、遥控页横屏、手动/自动模式、参数持久化、
  开源 RC car / GCS / teleop 方案对照（详见上文专章与 `docs/active/...设计对照...md`）。
  `core` **230/230**、`:app:assembleDebug` **BUILD SUCCESSFUL**、真机门禁 **59/59**。
  ⚠️ 真视频 / BLE GATT 上板 / 手感标定 / 策略启停仍 `UNVERIFIED != PASS`。
- **真机 GATT 联调 + netpad 上板**（需整机 + Android 真机）：bonding / CCCD / `onCharacteristicWrite`
  时序验收；板上 `service.sh netpad on` 后验证 UDP 驾驶方向与 250ms timeout；真机 50Hz 抖动 / 传感器。
  `AndroidBleGattLink` 真 GATT 上板应照 `Ley-WL/ducklink`（前台服务持 GATT + 串行写 + 后台/锁屏复用）
  补齐；**逐项收敛路径与验收 SOP 见 `docs/active/microduck-安卓App-整机落地验收清单-2026-11-13.md`**。
- **P2/P3**：视频（WebRTC mediad）、自有策略加载、标定/故障/技能屏。
- 待拍板：Q1 仿真后端选型 / Q2 relay 形态 / Q3 BLE 是否加应用层加密 / Q5 无 stand 策略时「站立」按钮语义 /
  **R4 netpad 预开 vs 纯 WebRTC**（现双通道都已实现，可延后决定）。
