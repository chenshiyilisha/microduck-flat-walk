# MicroDuck 安卓 App：开源遥控 App 设计方案对照（取长补短）

日期：2026-11-12　用户要求：「多找点遥控车、遥控飞机、遥控机器人 的开源app设计方案，取长补短」

## 0. 调研方法（先查资料，不靠自己推）

- **GitHub 仓库一律走官方 API 核验**（`api.github.com/repos/...`、`/search/repositories`），
  不采信搜索引擎给出的仓库名。本次实测就撞上一次：
  搜索 `OpenBot robot car` 返回的是 0 star 的 `enjineerMan/Openbot-Online`，
  **不是**真正的 OpenBot；直接用仓库 API 才拿到 `full_name=ob-f/OpenBot`（3659★）。
  ⚠️ 该仓库已从旧命名空间 `intel-isl/OpenBot` 迁到 `ob-f`（API 会跟随重定向），
  后续引用一律写 `ob-f/OpenBot`。
- **UI/IA 结论只读一手文件**：仓库 `README.md` / 子模块 README、QGC 官方 User Guide，
  不用二次转载的评测文章。
- 每条「采纳」都要落到代码或明确标注为「不采纳 + 理由」；
  不把「看到别人有」当成「我们该有」。

## 1. 仓库核验表（GitHub REST API（`api.github.com`） 实测）

| 类别 | 仓库（API 返回的 full_name） | ★ | 语言 | License | 默认分支 | 一手文档 |
|---|---|---|---|---|---|---|
| 遥控车 | `ob-f/OpenBot` | 3659 | Swift(含 Android 模块) | MIT | `master` | `robot/android/app/README.md`、`controller/README.md`、`DISCLAIMER.md` |
| 遥控车 | `NextGTI/ble-rc-controller` | 1 | Dart/Flutter | MIT | `main` | `README.md` |
| 遥控车 | `LeandroPiqueira/CarDroiDuino` | 7 | Java | 无 | — | API description |
| 无人机 GCS | `mavlink/qgroundcontrol` | 5112 | C++/QML | Apache-2.0 | `master` | `README.md`、官方 `Fly View` User Guide |
| 无人机 GCS | `DroidPlanner/Tower` | 632 | Java | NOASSERTION | `develop` | `README.md`（最后 push 2022-02） |
| 链路层(参照) | `DroneBridge/DroneBridge` / `DroneBridge/ESP32` | 955 / 1146 | C/C++ | Apache-2.0 | `master` | API description |
| 机器人遥操作 | `Lukaszm94/AndroidROSRobotTeleoperation` | 6 | Java | 无 | `master` | `README.md` |
| 机器人遥操作 | `SuhasDissa/ROS_Robot_Controller` | 0 | Kotlin+Compose | GPL-3.0 | `main` | `README.md` |
| 机器人遥操作 | `ohho-robotics/ohho.apk` | 0 | Kotlin | Apache-2.0 | `main` | `README.md`（「What is real in this build」表） |
| 机器人遥操作 | `livekit-examples/teleop` | 10 | TypeScript | MIT | `main` | `README.md`、`web/README.md` |
| ❌ 排除 | `enjineerMan/Openbot-Online` | 0 | JavaScript | MIT | `main` | 同名仿冒/无关项目，0★，不引用 |

> 星数少不等于没价值：`ohho.apk` 与 `ROS_Robot_Controller` 都是 2025–2026 年的 Kotlin/Compose
> 新项目，UI 取舍写得很细；而 632★ 的 Tower 已 4 年没 push，只作历史参照。

## 2. 逐项目设计要点（一手原文摘录）

### 2.1 遥控车

**OpenBot**（`ob-f/OpenBot`）
- `robot/android/app/README.md`：`DefaultActivity`「includes the most important features
  of the OpenBot app **in a single screen**. It displays the connection status to the vehicle
  and reports measurements from vehicle sensors」；Vehicle Status 三字段 `Battery` /
  `Speed (l,r)` / `Sonar`。
- 三个独立档位：`control mode`（Gamepad / Phone）、`drive mode`（Game / Joystick / Dual）、
  `speed mode`（Slow 50% / Normal 75% / Fast 100%）。
- 「**The controls that are sent to the robot are displayed on the right side**」。
- Data Log 四档 `only_sensors / crop_img / preview_img / all_imgs`。
- ⚠️ 安全原文（DISCLAIMERS）：「Special care is necessary when using automated control
  (e.g. person following or driving policy). **Make sure you always have a game controller
  connected and are familiar with the key mapping, so you can stop the vehicle at any time.**」
  同页又说网络运行时 game controller 被禁用，但可用「R1 trigger button to regain control」。
- 🔴 **反面教材**：单屏塞全部信息，正是用户 2026-11-12 反馈「一个界面放不下这么多内容」
  要否掉的做法 ⇒ 我们**不抄它的信息架构**，只抄它的档位可读性、控制回显与安全措辞。

**ble-rc-controller**（`NextGTI/ble-rc-controller`）
- 「A **dark dashboard** with a line-drawn top view of the car, a **steering gauge** and a
  **throttle scale**」；`Battery level, signal strength, automatic reconnection to your last car`。
- 输入三合一：gamepad / keyboard / on-screen touch；Settings 含 **dead zone**、按键重映射、
  「Teach a new controller」向导与「Live signals」。
- 安全：「**the car stops when you disconnect, switch apps, or lose the controller**」；
  协议文档写明 keep-alive「at least five times a second」。

**CarDroiDuino**（`LeandroPiqueira/CarDroiDuino`）
- 双手机：一台在车上做 server（收 UDP 命令 → 蓝牙转 Arduino，同时把摄像头帧 UDP 回传），
  另一台做 client 控制器，用加速度计生成命令。
- ⇒ 印证本项目「PC 侧 relay 转 TCP / UDP netpad」的分层不是自创；但**加速度计操控不采纳**。

### 2.2 无人机 GCS

**QGroundControl**（`mavlink/qgroundcontrol`）
- README：跨平台（Windows/macOS/Linux/**Android**/iOS）单代码库；
  「**Live Fly View** — real-time flight display with map, **instruments**, and full vehicle
  telemetry」、「**Vehicle setup** — guided wizards」、「**Mission planning**」。
- QGC Fly View User Guide（QGroundControl 项目文档）：`View Selector` 切 Fly / Plan / Analyze / Vehicle Configuration /
  Application Settings；`Status Indicators`、`Telemetry Values`（**configurable**）、
  `Attitude/Compass`、`Video`（可与 Map 切主显示，video switcher 在左下角）。
- ⇒ 强印证「驾驶/命令页 与 设置/分析页 分离」；只读仪表放顶部；视频是主显示而非小窗。

**Tower / DroidPlanner**（`DroidPlanner/Tower`）
- Android 原生 GCS（DroneKit-Android，ArduPilot）；README 里的 beta 截图路径含
  `flight.tablet.land.png` ⇒ 平板横屏飞行视图是当年既定形态，
  与用户「打开遥控界面应该横屏」同向。项目已停更，仅作历史佐证。

### 2.3 机器人遥操作

**AndroidROSRobotTeleoperation**（`Lukaszm94/...`）
- 「setting robots speed setpoint (linear and angular) — via **virtual joystick or tilting
  your phone**」、「displaying **live camera image**」、
  「viewing linear and angular velocity plots (**setpoint (SP) and process variable (PV)**)」。
- ⇒ SP/PV 是关键长项：只显示「实际速度」看不出命令有没有被跟随。

**ROS_Robot_Controller**（`SuhasDissa/...`）
- Kotlin + Jetpack Compose + MVVM；Joystick / D-pad / angle controls / switches；
  **Arena View + Live Robot Tracking**；RTSP 摄像头 + 双播放器后端；
  「Configurable URLs」「**Settings Management: Persistent user preferences**」。

**ohho.apk**（`ohho-robotics/ohho.apk`）
- README 有一张「**What is real in this build | What you see | What the code does**」表：
  Settings IP/port「Saved in DataStore」、连接点「Green / amber / red」、
  Home 卡片「show **live** values」否则「stay **demo**」「The banner labels **LIVE vs DEMO**」、
  「Dashboard camera ... Badge **CAMERA OFFLINE** ... **NO FEED**」「The camera has no frame」。
- ⇒ **数据出处显式标注**是本项目最值得抄的一条：不把夹具/占位画成真数据。
- 另：底部栏 6 项（自定义 `OmniBottomNavigationView` 抬高 Material 的 5 项上限），
  Settings 由顶部栏打开 —— 我们按 M3 保持 3 项，不跟这个例外。

**LiveKit teleop**（`livekit-examples/teleop`）
- `web/README.md`：「Full-screen video viewport with picture-in-picture secondary feed」、
  「Draggable joystick ... **springs back to center on release**」、
  「**Animated degree scales showing current yaw and pitch angles**」、
  「**View/Operator mode toggle** with operator seat locking」、
  「Real-time connection status display」；`bottom-bar.tsx` 放连接状态与模式切换。

**Weston Robot Teleop / Blue Robotics Cockpit / Enou GCS**（前一轮已查）
- driving view 布局独立于 dashboard；全屏相机 + 左右下角双摇杆 + 双拇指；松手即停；
  顶部/底部 mini widgets 放遥测。已在多页架构中落地。
- ⚠️ 2026-11-13 复核：原列在此处的「Uni Bonn RoMan 2012 §A/§B.1」经核验**无原文可证**
  （RoMan 2012 论文列表无此 Uni Bonn teleoperation 论文及章节），已从依据中移除；
  双摇杆改以 arXiv:2110.08753 + FPV OSD 为依据，拆页改以 M3 / Weston / QGC 为依据。

## 3. 取长补短对照表

| 维度 | 别人的长处 | 本项目决定 | 落点 |
|---|---|---|---|
| 信息架构 | QGC 多 View / Weston dashboard 与 driving view 分离 / M3 3–5 destinations | ✅ 已采用：竖屏控制台三页 + 独立横屏遥控页 | `MainActivity` / `DriveActivity` / Manifest |
| 单屏塞满 | OpenBot `DefaultActivity` | ❌ **明确不采用**（用户已否决） | 拆页 |
| 方向 | Tower 平板横屏飞行视图 | ✅ `sensorLandscape` 逐 Activity 声明 | `AndroidManifest.xml` |
| 只读仪表布局 | QGC Status Indicators + configurable Telemetry Values | ✅ 顶部**无背景紧凑单行 HUD**（FPV OSD「keep the center frame clean」），交互控件不进顶部 | `DriveActivity.buildHud()` |
| 遥测 overlay 形态 | FPV OSD（Betaflight / DJI / Walksnail）共识：「几乎隐形、只在需要时出现」「keep the center frame clean」，文字叠投影即可读、绝不铺卡片 | ✅ 2026-11-13 去外层卡片+单元格内层表面色→无背景单行文字条+`setShadowLayer`投影；两行三列高 ~140dp→~48dp（用户「太占地方/不需要背景」） | `DriveActivity.buildHud()/metricCell()/setHudMetric()` |
| 命令跟随 | AndroidROS 的 SP/PV 曲线 | ✅ HUD「命令→实际」，两值只取 `robot.state` | `DriveActivity.renderHud()` |
| 头部角度 | LiveKit animated degree scales | ✅ HUD「头部 °」，只取 `robot.state.head` | 同上 |
| 数据出处 | ohho.apk LIVE/DEMO banner、ble-rc 连接点 | ✅ 驾驶页新增「数据来源标签」；Mock 明写「非实机读数」 | `sourceRow` |
| 控制回显 | OpenBot「controls sent are displayed」 | ✅ 计数条第二行显示「最后输入」 | `counterText` |
| 设置持久化 | ROS_Robot_Controller / ohho.apk DataStore | ✅ `SharedPreferences`（零新依赖）+「恢复默认」负对照 | `SettingsStore.kt` |
| 死区可调 | ble-rc-controller Settings dead zone | ✅ 方向/头部两个死区滑杆并接入 core | `MainActivity` / `setupControllers()` |
| 随时停车/接管 | OpenBot DISCLAIMERS + R1 regain、LiveKit View/Operator | ✅ 自动页「切回手动」按钮 + 明写「App 无停车能力」 | `toManualButton` / `autoNotice` |
| 松手即停 | Weston / ble-rc / LiveKit spring-back | ✅ `ACTION_UP`/`CANCEL` 同归零、onStop 停车 | `JoystickView` / `DriveController` |
| 心跳保活 | ble-rc「at least five times a second」 | ✅ 100ms < timeout250 < deadman500 | `DriveController` |
| 模式语义 | NIST UTAP / Sheridan + LiveKit View/Operator | ✅ MANUAL=连续意图；AUTO=监督视图、零驾驶帧 | `SessionHolder.selectMode()` |
| 地图 / 航点 / Arena | QGC Map、Tower mission、ROS_Robot_Controller Arena | ❌ 不采纳：无整机、无已验证导航栈，画出来就是假地图 | — |
| 实时视频 | QGC GStreamer、ohho MJPEG、RTSP 双播放器 | ❌ 不采纳：`media.frame` 是 mediad 本地 Unix socket，WebRTC drive 属 P2 未实现；保留**明确标注的占位框** | `PreviewPlaceholderView` |
| 手机倾斜体感 | AndroidROS / CarDroiDuino 加速度计 | ❌ 不采纳：未上板验证、会让实体机器人动 | — |
| 手柄/键盘/D-pad/机械臂 | ble-rc、OpenBot、ROS_Robot_Controller | ⏸ 暂缓(P3)：fanhao API40 无对应方法；`JoystickModel` 已是输入无关的 Passive View，架构留好口 | — |
| 数据日志 | OpenBot Data Log 四档 | ⏸ 暂缓(P3)：需存储/同意与整机验证 | — |
| 冷启动自动连上次设备 | ble-rc「reconnect to your last car」 | ❌ 刻意不做：连接必须由用户主动发起；会话内断链重连已由 `RobotSession` 的 CAS guard + jitter 覆盖 | `SettingsStore` 注释 |
| 记住控制模式 | — | ❌ 刻意不做：每次冷启动**强制回 MANUAL**，保住手动接管入口（OpenBot 安全条款） | `SettingsStore` 注释 |
| 6 项底部栏 | ohho.apk 自定义控件破 M3 上限 | ❌ 不采纳：维持 3 个顶层目的地 | `buildTabRow()` |
| e-stop / 出厂重置 / PIN 管理 | 部分 GCS 有 | ❌ 用户前期明确排除 | — |
| 自动模式触发策略启停 | OpenBot network switch | ❌ 不采纳：契约有 `robot.do`/`robot.loadPolicy`，但**无整机、未验证**；AUTO 只监测 | `SessionHolder` KDoc |

## 4. 本轮实际代码改动（可核对）

| 文件 | 改动 |
|---|---|
| `app/.../SettingsStore.kt` | **新建**。8 项参数 SharedPreferences 持久化、load clamp、`reset()`；注释写明 mode/host 刻意不持久化及一手依据 |
| `app/.../SessionHolder.kt` | `setMode` → `selectMode`（修 JVM setter 签名冲突）；新增 `driveDeadzone` / `headDeadzone` |
| `app/.../MainActivity.kt` | onCreate 先 `SettingsStore.load()`；Settings 页加两个死区滑杆 + 「恢复默认设置」；所有监听器落盘；`persist()` / `restoreSettingsUi()` / `updateSettingLabels()`；调用点改名 |
| `app/.../DriveActivity.kt` | HUD 4 格 → 2×3 六格（新增「命令→实际」「头部 °」）；新增 LIVE/DEMO `sourceRow`；计数条加「最后输入」；自动页加「切回手动」与安全告示；两个 Controller 接死区；KDoc 补开源依据 |
| `tools/device_ui_check.py` | ✅ 已补：持久化跨冷启动回归（`checked` 属性读 CheckBox）、「冷启动强制回手动」负对照、LIVE/DEMO 来源标签、数据来源分组；并修掉两处验证工具自身的假读数（见 §6） |
| `app/.../MainActivity.kt`（状态页） | 状态页「实机状态帧」8 项 +「App 本地遥测」7 项两栅格由 **2 列改 4 列紧凑栅格**（每格仍保留独立表面色 + label 9dp dim / value 12dp 近白加粗分色分层）；cell 高度 48→40、`metricGrid` 间距 6→4。依据：vivo V2338A（1260×2800@560dpi ⇒ 360×800dp）uiautomator 只 dump 视口内节点（off-screen 不吐，OEM 无关、是 uiautomator 固有行为），2 列 8 行≈480dp 超出 ~370dp 可用高度 ⇒ 遥测区被推到折叠线以下、门禁读不到；4 列 4 行≈240dp 单屏可见。已 `screencap` 截图目视：可读、对比度 OK |
| `tools/device_ui_check.py`（A1 BLE 面板） | 新增 `scroll_down / scroll_up / scroll_until()`；设置页 BLE 面板在 ScrollView 末端，先**小步**滚到按钮「扫描附近 BLE 设备」出现（它是面板里位置最低的元素，出现即整块含标题入镜）再断言。修掉两个坑：① 冷启动测试后停在状态页、`scroll_until` 滚错页面；② 大步幅一次跨过整块面板，把标题/按钮甩出视口顶部只留中间描述 |

## 5. 证据边界（铁律）

- ✅ 最终门禁 **59/59、连跑 3 次 RC=0**；`cmd statusbar expand-notifications` 负对照注入后
  门禁自动收起 systemui 面板并仍 59/59（§6 #4 的修复经「改坏必红」验证）。
- `UNVERIFIED != PASS`：本轮所有改动只在 **Mock 会话 + vivo V2338A 真机 UI 门禁**范围内验证；
  **整机未落地**，真机 GATT / 真视频 / 真策略启停 / 手感标定全部仍 `UNVERIFIED`。
- 新增 HUD 两格只读 `robot.state`；Mock 不推流 ⇒ 一律「— 未读到」，**不用本地意图/计数器补值**。
- 「切回手动」只是**模式切换**，不是 e-stop；自动模式下 App 无停车能力，界面已明写。
- Gradle 8.11.1 被 KGP 2.4.0 提示 deprecated（Kotlin 2.5.0 起要 ≥8.14.4），
  当前组合按已查过的三条版本矩阵保持不变，不为消 warning 乱升级。

## 6. 验证工具自身抓出的 3 个假读数（本轮真机实测）

首轮门禁 **54/56** 两条失败都指向「UI 文本在 1.2 s 采样窗内没变化」，但后续断言证明心跳确实在发帧（+40 帧）。
按项目铁律「读数与算术矛盾 ⇒ 错的是读数」，写了 `build/device/diag_frames.py` 逐帧采样，抓到：

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| 1 | `uiautomator dump` / `adb pull` 不查返回码，失败时 `parse_dump()` 读到**上一次陈腐 XML** | 诊断显示心跳 101→810 帧持续增长，门禁却读到 `+0` | 逐条校验 `returncode` / `ERROR` / 内容含 `<hierarchy`；改用 `adb exec-out cat` 取**本次** XML，零本地文件 |
| 2 | `SessionHolder.tick()` 同时被主页与遥控页两个 Handler 调用，共享快照互相踩 | 诊断第 12/14 次采样「心跳中」抖动成「已停」 | `tick()` 改由当前前台 Activity 单点驱动，快照写入加同步；主页不再假装有心跳 |
| 3 | 为防陈腐而每轮 `os.remove(LOCAL_XML)`，连跑两轮删几十次触发环境**批量删除保护** `SAFE_DELETE_BULK_CONFIRM_REQUIRED count=50 threshold=50`，脚本静默中断、无 RESULT 行 | `ui_check_rep2.log` 无任何 `FAIL` 行却中途截断 | 改为零本地删除（见 #1），连跑不再误伤 |
| 4 | 连跑首轮：**下拉通知栏 / 快速设置面板**被当成 App 界面（USB 调试/文件传输通知常驻），`uiautomator dump` 返回的全是 systemui 节点，节点数 ≥8 且非 ListView ⇒ 旧判据放行 | `ui_check_final1.log`：16 条全 FAIL、detail 是「通知中心 \| 已开启 USB 文件传输模式」，`RC=2` 且无 RESULT；下一轮面板收起即 57/57 | `parse_dump()` 读 `package` 属性（App 页实测 60/60 命中）；`dump_nodes()` 加硬判据「本包节点 ≥3」，否则 BACK 收起 overlay 重取；负对照用 `cmd statusbar expand-notifications` 注入。所有提前 `return 2` 收口到 `finish(2)`，**任何路径都打印 RESULT** |
| 5 | 状态页遥测区 / 设置页 BLE 面板被推到**视口外**，uiautomator 只 dump 视口内节点 ⇒ 门禁读不到「本地刷新 / 扫描附近 BLE 设备」 | 54/58：①「本地遥测数值真在变化」②（主页零驾驶帧被误读）③「数据来源分组标注」④「A1 BLE 面板」四项失败；抓全量 dump 只见 STATE 8 格后直接跳 `bottomStatus`，中间 divider+遥测标题+7 格全缺 | 状态页两栅格 2 列→**4 列紧凑栅格**（4 行≈240dp < ~370dp 可用高度，单屏可见，不再依赖 ScrollView dump）；设置页 BLE 面板**小步滚动**到按钮出现再断言（见 §4）。根因确认：uiautomator off-screen 不吐是固有行为（navigate-app-adb 技能原文 "Off-screen elements don't dump… below the fold won't appear until you scroll"），与 OEM 无关，靠滚屏不可靠 ⇒ 改「让内容单屏可见」而非「依赖 dump 视口外节点」 |

另有一条**过时断言**：拆页后主页本来就不发驾驶帧，旧门禁仍断言「主页帧数必须增长」，已改为主页只验「数据来源分组 / 持久化」，帧增长只在横屏遥控页验。

## 7. A5 续：主仓协议 + 3 个社区 App 核验（用户点名要查）

用户 2026-11-13 点名核查：`pollen-robotics/microduck` 主仓（`btd/src/route.rs`、`duck-ble`、`duck-ipc-proto`）
+ `Ley-WL/ducklink`（Java/Android 原生）、`apirrone/microduck_app`（TS）、`KilllerBoss/microduck`（Kotlin RL）。
**方法**：主仓协议文件走本地 `.upstream/DuckBuddy-main` + `out/evidence-official/official-main` 一手源码；
3 个社区仓库走 GitHub REST API（`api.github.com`） 核验（不采信搜索引擎）。

### 7.1 主仓协议（`duck-ipc-proto` / `btd`）—— 确认 App 契约正确

| 维度 | 主仓一手事实 | 与本项目 App 的关系 |
|---|---|---|
| 线格式 | `JSONRPC_VERSION="2.0"`，NDJSON | ✅ App 用 JSON-RPC 2.0 / NDJSON，一致 |
| 方法面 | `robot.move / head / subscribe / state`、`system.authenticate`、`robot.health`、`robot.do`、`robot.setMode`、`pad.* / net.* / update.* / tof.* / chorale.*` 等一大票 | ✅ App 只取步行/遥测子集（`move/head/subscribe/state` + BLE 的 `system.authenticate`），主仓全有 ⇒ App 子集合法，未用的方法（look/theremin/chorale/pad/tof）正确不碰 |
| 错误码 | `-32601` METHOD_NOT_FOUND、`-32602` INVALID_PARAMS、`-32603`、`PERMISSION_DENIED=14`；`route.rs` 明确「a refusal must be distinguishable from no-such-method」 | ✅ App 的 `-32601/-32602` 能力降级 + `AuthPolicy.AUTO` 按 kind 判 PIN 归属，正是这套语义 |
| GATT UUID | `btd/src/gatt.rs`：`SERVICE_UUID=6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019`、`RPC_UUID=6f5d2a11-…-6019` | ✅ App `Wire.BLE_SERVICE_UUID` 用同一个 `6f5d2a10-…-6019`，与 **Pollen 原厂**一致 |
| 链路/插座 | `robotd` 监听 unix `/run/robotd.sock`；`route.rs` 路由 `Route::Local / To(upstream,lane) / Refused` | ✅ App「PC 侧 relay 转 TCP」正是为仿真期绕开 unix socket；`RobotTransport` 四后端（Ble/Tcp/WebRtc/Mock）统一收口 |
| **API 版本分歧** | 主仓 `API_VERSION=16` | ⚠️ **fanhao 分支（App 实际对接）是 API40**（control.43/API40/imu-ft6）。这正是 App 不做「版本硬拒」、而靠 `-32601` 能力降级的理由；`HelloResult` 无 serial 不依赖、能力靠 -32601 判 |

> 结论：主仓协议 **证实 App 的契约子集合法且 GATT UUID 一致**；唯一实质分歧是 API 版本（主仓 16 vs fanhao 40），App 已用能力降级正确规避，无需改动。

### 7.2 三个社区 App（GitHub API 核验）

| 仓库 | 语言/★ | 一手定位 | 值得借鉴 / 不采纳 |
|---|---|---|---|
| `Ley-WL/ducklink` | **Java / 0★** | 「DuckLink Android app and authenticated BLE gateway for MicroDuck」；`android/.../BleLink.java`、`BleSession.java`、`BleCodec.java`、`BleConnectionService.java`、`BleDiscovery.java`、`Joystick.java`、`ServoTelemetry.java`、`PoseTelemetry.java`、`BatteryIndicator.java`；`design/BLE-0.4.0.md`、`gateway/PROTOCOL.md` | ✅ **最相关的原生安卓线**：它的 BLE 后台长连接（`connectedDevice` 前台服务持有 GATT + 认证，切后台/锁屏/Activity 重建复用，全部 GATT 操作串行、急停优先、断连仍有效）正是本项目 `AndroidBleGattLink` 骨架**将来上板时**应照着补的方向；`BleCodec` 的 `columns-v1` 无损压缩 15 舵机字段（1629→758 字节）可作真 GATT 吞吐优化参考；它的「每次发版 `verification.json`（build/lint/签名/OTA 公网验签/逐字节 APK 长度 SHA）」与本项目 `device_ui_check.py` 门禁 + `UNVERIFIED!=PASS` 是**同一种自我验证文化**。⚠️ 它已 OTA 到 0.9.4x、有真实主板部署，项目整机未落地 ⇒ 它的真 GATT 行为**不能外推**到本项目（边界同 §5） |
| `apirrone/microduck_app` | TypeScript / 2★ | 无描述；TS 技术栈 | ⏸ 低优先：Web/TS，与本项目原生 Kotlin + 真机门禁不同路线；方法面与主仓一致即可，无新增借鉴 |
| `KilllerBoss/microduck` | Kotlin / 0★ | 德语：「RL 训练双足机器人（mjlab/PPO）、Snapdragon-NPU 部署、Android-APK 含 In-App-3D 模拟 + Gemini 混合控制」 | ❌ 不采纳：是 RL 训练/演示 Demo（含 In-App 3D 模拟、Gemini 控制），不是 faithful 控制 App；本项目已明确不做假地图/假视频/体感，与其定位相反 |

> 一句话：**3 个社区里只有 `Ley-WL/ducklink` 对原生安卓 BLE 有实质参考价值**（且其验证文化与本项目同源）；另两个是 Web/RL 演示线，无新增借鉴。App 当前 `AndroidBleGattLink` 真 GATT 仍 `UNVERIFIED`，待整机后应以 ducklink 的「前台服务持 GATT + 串行写 + 后台/锁屏复用」为参照补齐。

> 🔑 教训泛化：**门禁工具本身也是被测对象**。它读不到数、读到旧数、读到别人的窗口、
> 被环境保护掐断、或提前退出不打 RESULT，都会伪装成「产品行为异常」或「偶发 flaky」。
> 判窗口归属要用**结构性判据**（`package` 属性），不要用「节点数够不够」这种表面特征；
> 先写独立诊断脚本实测时序，再动产品代码；每个修复都要有能把它改红的负对照。
