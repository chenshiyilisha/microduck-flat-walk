# MicroDuck 安卓 App — 功能缺口与可加功能清单（资料支撑版）

_2026-11-13 建档。用户要求：「看看还缺什么功能，还有什么功能可以加上，找找资料」。_
_**2026-11-18 更新**：§5 落地状态已刷新（A2/A2'/A3/A6/A7 已落地、A8 明确不做），并新增 §5.1 原厂 9 屏逐方法对照、§5.2 原厂 §7 欠账归属。§0/§2 保留 11-13 历史盘点原貌（当时 A2–A8 全未做），**以 §5 为准**。_

_**2026-11-18 晚更新**：新增 §5.4 —— 一手定位并修复 hello 握手死锁（updaterd 默认关闭导致的 `Updater is not answering`），**真机打通 BLE→READY→configd→net.status/scan 配网链路**并端到端换 WiFi 成功；A2 从「链路不通」升级为「真机验收通过」。_

_**2026-11-18 中午补充**：新增 §5.5 —— 用户反馈驱动的两处 UX 改进：`net.scan` SSID 可点选（取代手录）、BLE 扫描列表只列 MicroDuck 候选（无名非目标设备隐藏）；均带门禁负对照与真机验证。_

_**2026-11-18 晚补充（用户「软件这块还能做什么」→「都做，照最优的来，记得查资料」）**：不新增 App 功能（不依赖整机的功能已做尽），转做三件准备：① `deploy_import_checklist.md` 新增 H14–H16（DuckBuddy 借鉴的 IMU 握手/SYNC_READ 错误率/reg46 联写三条判据，全标 UNVERIFIED）；② 新建 WebRTC 接入准备文档（依赖替换查实为 `stream-webrtc-android`，但:**机器人侧信令零鉴权 ⇒ 接入前必须安全拍板**，不引依赖不改 gradle）；③ 加密规格文档顶部加一手更新：**原厂 btd 已默认链路层加密 + setup-code PSK**（`main.rs:123`），本 App 对接的 fanhao 线默认仍不加密，原判决继续有效、但 §4 应用层方案不再是唯一最优。三处均只改文档，未写功能代码，`ship_verdict` 不变。详见 §5.6。_
_本文件**只做盘点与依据核对，不改功能代码**。每条建议挂一手来源；_
_术语严格遵循 `docs/active/microduck-来源术语约定-2026-11-13.md`：**「原厂 / 官方」只指 Pollen Robotics 原厂**。_
_整机未落地 ⇒ 交付判定仍为「不可交付」；未验证不等于通过。_

---

## 0. 结论速览

**最大缺口不是「功能少」，而是「原厂 App 的核心价值那一半根本没做」**：
`Wire.kt` 里挂了 `net.* / update.* / system.logs / robot.do / robot.policies / robot.loadPolicy / robot.init`
等常量，但 **app 层一次都没调用**（本轮逐文件 Grep 核实）—— 这些只是常量，不是功能。

Pollen 原厂 `docs/design/mobile-app.md` §1 的屏幕×调用表定义了 9 个屏：
`pick a robot` / `the robot` / `drive` / `moves` / `wifi` / `update` / `logs` / `account`，
外加会话层。我们目前只覆盖 **drive + 健康 + 设置** 三块，
**配网救砖 / 升级 / 日志 / 系统信息 / 技能策略 / 账户全缺**。

三个最该先补、且**不依赖整机**的：

1. **BLE 前台服务 + 运行时权限 + FGS 类型**（真 GATT 上板的硬前置，代码里确定没有）
2. **配网救砖链路（wifi 屏）**（原厂 §1.2 明写这是 BLE 存在的理由）
3. **控制者归属 / 会话活性显示**（`robot.remoteSessionActive` + ISO 10218「单一控制站」）

⚠️ 一条资料带出来的因果：**一旦做配网（要写 Wi-Fi 密码），原厂 §7 明说 BLE 明文就不能交付**
⇒ Q3「是否加应用层加密」从可选项变成配网功能的**前置依赖**。

---

## 1. 来源层级（不重复展开，见术语约定文档）

| 简称 | 全称 | 地位 |
|---|---|---|
| **原厂** | `pollen-robotics/microduck@main`（Pollen Robotics），`docs/design/mobile-app.md`、`app-path-design.md`、`duck-ipc-proto/src/lib.rs`、`btd/src/route.rs`、`duckctl.md` | **唯一官方**。原厂手机 App 仓 `pollen-robotics/microduck-app` 私有（HTTP 404），只能引用设计文档 |
| fanhao fork | `fanhao375/Microduck-kissqy` @ `hd1910-v167-trunk-imu-i2c`，`API_VERSION=40` | **本 App 实际对接目标**。非官方；该仓 GitHub API 现 404，本地 `/tmp/fanhao/...` 保有整份源码 |
| B 代快照 | 本地 `.upstream/ft1910`、`imu-displace`、BoBo 等同源分支，`API_VERSION=16` | 目前所有「真固件活体」证据的版本。非官方 |
| Reachy Mini | `pollen-robotics/reachy_mini_mobile_app`（public） | Pollen **另一产品**的公开参考 App，非 MicroDuck 官方 |
| 第三方 | Google / Android / Wandelbots / NIST / GitHub / JetBrains 等 | 一律具名 + 「平台文档 / 规范 / 项目文档」 |

**API 版本三套别混**：原厂 main = **61**（2026-11-13 GitHub REST API 实测）、fanhao = **40**（对接）、B 代 = **16**（联调证据）。
此前 A5 文档写「主仓 16」是本地旧快照，不代表原厂现状。

**副本核对（本轮实做）**：原厂 `mobile-app.md` 18796 B / md5 `a4652408f430`，
fanhao 副本 `5cb5394f864e`，逐行 diff **仅 §7 一行**（`robot.sound` 是否已路由 / `duckctl quack`）；
本文引用的 §1 / §1.2 / §4 / §6 / §7 其余条目两版一致。

---

## 2. 现状盘点（读代码，不是照规划文档抄）

### 2.1 已实现（有证据）

- `RobotTransport` 四接口：**Mock / Tcp / Ble（协议层）已落地真测**，WebRtc 未实现。
- 会话层：自动重连 + 重认证 + 重订阅（C2 11/11、C2+ **24/24** 含断链恢复与「不订阅零帧」负对照）。
- 驾驶：双摇杆、死区/圆形限幅、松手归零、100ms 心跳 < 250ms timeout < 500ms deadman、
  JSON-RPC notification + UDP netpad 双通道、触觉反馈、死区可视化。
- 健康屏 `robot.health`（缺失≠0）、状态页 4 列紧凑栅格、设置页死区/速度/方向持久化、
  BLE 扫描面板、LIVE/DEMO 来源标签、AUTO 监督视图（零驾驶帧）。
- `tools/selftest.sh` **230/230**、真机 UI 门禁 **59/59**（连跑 3 次 RC=0）。

### 2.2 **只有常量、app 层零调用**（`Wire.kt` 的 `Method` 表）

`system.info` / `net.status` / `net.scan` / `net.connect` / `update.check` / `update.status` /
`system.logs` / `robot.init` / `robot.enable` / `robot.do` / `robot.policies` /
`robot.loadPolicy` / `robot.model` / `robot.look`（注释已写「本版 UI 不用」）。

### 2.3 **连常量都没有**（原厂 `duck-ipc-proto/src/lib.rs` 里有、App 完全未建模）

`system.services` / `system.setName` / `system.reboot` / `robot.rebootMotors` / `robot.skills` /
`net.forget` / `update.apply|subscribe|listInstalled|log|rollback|select` /
`policy.check|search|fetch|install` / `account.login|status|logout` /
`pad.status|pair|forget|bindings|bind` / `detector.check|install` /
**`robot.remoteSessionActive`**（"Is a telepresence session live?"）/ `robot.safeToRestart` /
`robot.modelApi` / `robot.setSkill|removeSkill` / `robot.reloadPolicies`。

> 一手：`/tmp/fanhao/.../duck-ipc-proto/src/lib.rs:583-877`；
> 屏幕×调用表：原厂 `docs/design/mobile-app.md` §1（fanhao 副本同版）。

---

## 3. 可加功能清单（逐条挂依据）

标记：**✅ 一手核验**（原文逐字命中） / **🟡 开源借鉴** / **⚠️ 待拍板或有风险**。

### A 类：不依赖整机，现在就能开发并用 Mock / relay 自测

| # | 功能 | 依据 | 价值 / 风险 | 建议 |
|---|---|---|---|---|
| A1 | **BLE 前台服务 + `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_CONNECTED_DEVICE` / `POST_NOTIFICATIONS`**（⚠️ 复核修正：运行时权限请求 `BleConnectPanel.requiredPermissions()/requestPermissions()` **已有**，不是缺口） | ✅ Google `developer.android.com/develop/connectivity/bluetooth/bt-permissions`：API31+ 的 SCAN/CONNECT 是运行时权限、SCAN 可加 `neverForLocation`；API34+ 的 `connectedDevice` FGS 类型需先持有 BLUETOOTH_CONNECT/SCAN/ADVERTISE 之一；API31+ 后台起 FGS 抛 `ForegroundServiceStartNotAllowedException` ⇒ 必须在 Activity 可见时启动。🟡 社区 `Ley-WL/ducklink`：前台服务持 `BluetoothGatt` + 全部 GATT 操作串行 | **复核后真实缺口**：Manifest 原先只有 `BLUETOOTH_SCAN/CONNECT`（`neverForLocation`、legacy 限 `maxSdkVersion=30` 均已正确），**没有 FGS 权限、没有 Service 声明**，且 GATT link 只由 `BleConnectPanel` 的 Activity 局部变量持有 ⇒ 切后台/锁屏引用丢失、链路断 | **最高优先**，2026-11-13 已落地 `DuckBleService`；纯策略部分用 JVM 自检，真 GATT 仍待整机 |
| A2 | **配网 / 救砖（wifi 屏）**：`net.status` / `net.scan` / `net.connect` / `net.forget`，每步错误带 `recoverPhase`、地址徽章、手机→机器人 HTTP 同网探测 | ✅ 原厂 §1.2：「**BLE is the app's channel** … A board arrives somewhere new, the wifi it knows is not there … an app that needed the LAN to change a setting could not fix the setting keeping the robot off the LAN」；`drive` 的地址从 `net.status` 经 BLE 拿。✅ 原厂 `btd/src/route.rs` 把 `NET_CONNECT` / `NET_FORGET` 列为 BLE **允许**的 mutating 调用。🟡 Reachy Mini（Pollen 另一产品）的配网 FSM / address badge / HTTP probe | 原厂 App 的**核心价值**，我们完全没有；无网机器人唯一入口 | **先做，但见 A2'** |
| A2' | **BLE 应用层加密**（Q3 从待拍板升级为配网前置） | ✅ 原厂 §7 原文：「an app whose job is writing a wifi passphrase **cannot ship over a link that carries it in clear**」；§8.1 三个候选修复中有两个不需要 bonding。🟡 Reachy Mini `x25519-hkdf-sha256-aesgcm` 现成方案 | 与 A2 绑定：**先做配网而不加密 = 明文传 Wi-Fi 密码**。内部自测可接受，对外交付不行 | 与 A2 同批评估；或 A2 先只做「只读 `net.status`」不写密码 |
| A3 | **系统信息 / 服务 / 日志屏**：`system.info` / `system.services` / `system.logs` / `system.setName` / `system.reboot` | ✅ 原厂 §1「the robot」「logs」屏明列；`lib.rs:823-831` | 台架排障价值高、只读为主、成本低 | 先做只读三项；改名/重启属 mutating，后置 |
| A4 | **控制者归属 / 会话活性显示**：`robot.remoteSessionActive` + `robot.modelApi` 读回，HUD 显示「当前谁在控制 / 是否有其它遥在场」 | ✅ 原厂 `lib.rs:589` "Is a telepresence session live?"；✅ Wandelbots NOVA 合规文档（`docs.wandelbots.com/26.1/developing-norm-compliance`）：「**It must always be made clear by the UI which device is currently controlling the robot**」(DIN EN ISO 10218-1)；✅ ISO 10218 修订解读（KAN）：「**Only one control station may be active at any one time**」 | 只读展示、零运动风险；补齐合规可观测性；当前 HUD 只有链路强/弱/断 + 状态 Hz | **低成本高价值，建议做** |
| A5 | **断链即停状态显性化**：把「断链 ⇒ 已停车 ⇒ 恢复后须重新主动接管」做成第一态 | ✅ Wandelbots NOVA 合规文档：「Communication losses between components **must result in a safety stop**」「**Restored communication can't result in machine reboots, actions or movements**」；✅ 原厂 §4「Every screen tolerates the link dropping underneath it and coming back」 | 机制我们**已有**（100ms/250ms/500ms + 松手归零 + `onStop` 停车），但 HUD 只写「心跳中/已停」，没把恢复后**不自动续动**说清 | 不是造新安全功能，是把已有机制显性化；建议做 |
| A6 | **策略 / 技能只读屏**：`robot.policies` / `robot.model` / `robot.skills` 列已装策略、当前 plant / 模型版本 | ✅ 原厂 §1「moves」屏；`lib.rs:726-745,858`；本项目《功能调研》§5.3「自有策略优先、不做原厂 Hub 流程」 | 避免误切、为整机后策略启停铺路 | **只做只读，不做启停**（无整机、AUTO 刻意零驾驶帧，防「假启动」） |
| A7 | **升级屏（先只读）**：`update.status` / `update.check` / `update.listInstalled` / `update.log` | ✅ 原厂 §1「update」屏 + §4：「`updaterd` keeps the latest progress per component and **replays it to a new subscriber**, and `update.status` answers from a cached snapshot during an update」 | 与我们的会话层（断链重连重订阅）**天然契合**，是原厂特意设计过的场景 | 只读优先；`update.apply/rollback/select` 属 mutating，等整机 |
| A8 | **离线演示模式显式入口**（Mock 后端一键进入，LIVE/DEMO 标签一致） | 🟡 MABEL Teleop（`robotmabel.github.io/website/teleop.html`）「Demo Mode: No robot near? The app runs its own simulator」；🟡 Hey Reachy「Start the simulator」 | 已有 `MockTransport` 与 `sourceRow` 标签，缺显式入口；无整机时演示/回归都方便 | 低成本，可做 |
| A9 | **API 版本下限硬拒**（原厂 §6：`App refuses a robot below API_VERSION 31 at the handshake`） | ✅ 原厂 §6 原文；✅ 原厂 `app-path-design.md` §3 相反规则（daemon「reports and never refuses」） | ⚠️ **建议维持不做**：我们靠 `-32601` 能力降级，且台架是 **B 代 API16 < 31**，加硬拒会把当前唯一可测固件拒之门外 | 等整机换到 fanhao API40 后再评估；把理由写进文档，别悄悄改 |

### B 类：依赖整机 / 真板（已有专门清单，本文不重复）

| 功能 | 状态 | 出处 |
|---|---|---|
| 真机 GATT 上板（bonding / CCCD / `onCharacteristicWrite` 时序） | 未验证 | 《整机落地验收清单》§1 |
| netpad 上板（UDP 4210 / 250ms timeout） | 未验证（B 代 API16 无 netpad） | 同上 §2 |
| 真视频（WebRTC mediad 推流） | 未验证 | 同上 §3 |
| 策略启停（AUTO 目前零驾驶帧） | 未验证 | 同上 §4 |
| 手感标定（`maxVx/maxVyaw` 占位） | 未验证 | 同上 §5 |
| 真机 50Hz / IMU / ToF 传感器 | 未验证 | 同上 §6 |

**P2 视频的一手前置（本轮新查，别照旧教程踩坑）**：
Google 的 `org.webrtc:google-webrtc:1.0.32006` **已停止维护**，JCenter 关闭后 2026 年新工程
**无法解析**；维护中的替代是 `io.getstream:stream-webrtc-android:1.3.10`（Maven Central，
保持 `org.webrtc.*` 包名，`PeerConnection` / `VideoTrack` 导入路径不变）
或 `io.github.webrtc-sdk:android`。
⚠️ 引入即新增重型依赖 + APK 体积，且 mediad 信令端口不鉴权 ⇒ **需用户拍板**。

### C 类：明确不做 / 有合规张力（不是「忘了做」）

| 项 | 判定 | 依据 |
|---|---|---|
| **e-stop 按钮** | **维持不做**，但写清边界 | 用户前期明确排除；✅ 原厂 `btd/src/route.rs` 拒 `robot.stop`，理由是「看起来是 e-stop 实际不是」比没有更糟（靠 deadman 兜底）。⚠️ **张力**：ISO 10218 修订（KAN 解读）要求「能引发运动的便携控制站（含手机/平板）须有 ISO 13850 急停 + 三段式使能」，但「**仅监控、不能引发运动**的控制站豁免」。我们 MANUAL 页能发 `robot.move`，理论上落入前者；然而这是工业机器人标准、MicroDuck 属小型教育机器人，且我们没有安全级链路 ⇒ 加软件按钮只会制造**假安全感**。**结论：不加按钮，把该合规边界写进文档，对外交付前做风险评估** |
| 自动连上次设备 / 记住控制模式 | 维持不做 | 连接须用户主动发起；冷启动强制回 MANUAL 保住接管入口（OpenBot DISCLAIMERS） |
| 假地图 / 假视频 / 体感 / 超过 5 项底部栏 | 维持不做 | 无已验证导航栈；画出来即是伪造数据；Material 3 Navigation bar 为 3–5 个目的地 |
| 原厂 Hub 策略流程（`policy.search/fetch/install`）、账户登录 | 暂不做 | 本项目自有训练模型优先；账户体系无对应后端 |

---

## 4. 建议顺序（按「不依赖整机 + 依据强度 + 成本」排）

1. **A1 BLE 前台服务 + 权限**（真 GATT 的硬前置，不补则后面全是空谈）
2. **A4 控制者归属 + A5 断链即停显性化**（纯只读 / 纯展示，零运动风险，合规收益明确）
3. **A3 系统信息 / 日志（只读）+ A7 升级（只读）**（复用已验证的会话层，台架排障立刻可用）
4. **A2 配网 + A2' 加密**（价值最高，但牵扯安全交付判定，需用户拍板 Q3）
5. **A6 策略只读 + A8 演示入口**（低成本）
6. B 类全部等整机；A9 等换到 fanhao API40 后再评估

⚠️ 每一步都要守：**软线饱和不等于整机可用**。无整机期堆再多评测，
交付判定仍是不可交付，真机 GATT / 真视频 / 策略启停 / 手感标定仍为未验证。

---

## 5. 落地状态（2026-11-18 更新）

**分两批落地，均为用户「你决定，按最优的来」/「都做，按最优的来」授权：**

- 11-13 批次：A1 / A4 / A5（BLE 前台服务、控制者归属、断链即停显性化）。
- 11-18 批次：A2 / A2' / A3 / A6 / A7（配网、加密能力预埋、系统信息日志、策略只读、升级只读）。提交 `f6d4d07` 已 push origin/main。**A8 用户明确不做**（留空地址栏已是 Mock 入口，不另加显式按钮）。

### 5.0 逐项状态

| 项 | 状态 | 实现 | 证据 |
|---|---|---|---|
| A1 | ✅ 已落地（11-13） | 新增 `DuckBleService`（`connectedDevice` 前台服务，持 GATT 引用、通知带「断开」action）、Manifest 三项权限 + `<service>` 声明、`BleConnectPanel` 在连接成功回调（Activity 可见）启动 FGS、权限集合统一下沉到 core `BleForegroundPolicy`（JVM 自检与真机共用同一判据） | `selftest.sh` **283/283**；真负对照「把权限名改成 `_BROKEN`」→ **281/2 红**、恢复后 283/0；`assembleDebug` BUILD SUCCESSFUL；真机门禁 59/59 |
| A4 | ✅ 已落地（11-13） | `Wire` 加 `robot.remoteSessionActive` / `robot.modelApi`（一手 `lib.rs:589/587`）、纳入 `RobotSession.isReadOnly`、`SessionHolder.refreshSessionInfo()` null-safe 读回（**Mock 不查**、缺字段保持「未知」）、HUD `signalRow` 显示「遥在场 有/无/未知」 | 门禁输出可见「链路 无 · 状态 — Hz · 遥在场 未知」；自检对方法名与只读归属各带负对照 |
| A5 | ✅ 已落地（11-13，机制本就有，只做显性化） | 断链恢复 READY 时横幅显示「驾驶不自动续动，需重新主动接管」，4s 后由 `tick` 清除；`renderLinkBanner` 改差异更新，避免再次触发 `could not get idle state` | 门禁 59/59；⚠️ **真机断链→恢复场景未复验**（`UNVERIFIED`） |
| ANR 修复 | ✅ 已落地（11-18，审计追加） | `MainViewModel.onConnect/onConnectWith` 建链从主线程移到 IO 协程、回调切主线程；地址栏 TCP 同步阻塞最坏 ~7s 的 ANR 源消除 | `tools/check_no_mainthread_blocking.py` **5/5 + 5 负对照** |
| A3 | ✅ 已落地（11-18） | `DiagnosticsSnapshot` 纯 JVM 只读解析（缺字段 null / 空列表、不造假），`RobotRepository.refreshDiagnostics()` 后台拉取，健康页只读展示；Wire/RobotSession 只读白名单登记 | `tools/check_diagnostics_readonly.py` **6/6 + 负对照**；core 自检 |
| A6 | ✅ 已落地（11-18，只读） | `robot.policies`/`robot.model` 纳入诊断快照只读展示（**不做启停**，AUTO 零驾驶帧防假启动） | core 自检 + 只读门禁 |
| A7 | ✅ 已落地（11-18，只读） | `update.status`/`update.listInstalled`/`update.log` 纳入诊断快照（**不做 apply/rollback/select**，mutating 等整机） | core 自检 + 只读门禁 |
| A2 | ✅ 已落地（11-18，仅内测；11-18 晚真机打通配网链路） | `NetSnapshot`（net.status/net.scan 解析）+ `NetProvisioning`（net.connect/net.forget 请求构造，严格 deny_unknown_fields 键集，**psk 只进出站 JSON 不落日志**）；设置页配网卡片（Mock 隔离、明文风险常驻警示、连接二次确认）。11-18 晚修复 hello 握手死锁（见 §5.4）：仅「上游版本探测服务不可达」降级继续握手，net.connect 链路真机可用 | `tools/check_net_provisioning.py` **13/13（含 4 项新增负对照）**、`tools/check_ble_candidate_filter.py` **7/7**；core 自检 629/629；统一门禁 13 项 ALL_PASS；**真机端到端换 WiFi 成功**（Microduck-kissqy→DS1002 / IPv4 192.168.0.55 / 凭据已存 / 三观测面互证，§5.4）；**SSID 可点选 + BLE 候选过滤真机验证通过**（§5.5） |
| A2.1 | ✅ 已落地（11-18 晚，hello 握手死锁修复） | 一手定位：hello→updaterd 而首启镜像故意关 updaterd ⇒ btd 回 `Updater is not answering`（INTERNAL_ERROR）；但 authorize/配网都走 configd，不经 updaterd。`isHelloDegradable` 仅该消息两段结构命中才降级继续 auth→READY，如实记录 `helloDegradedReason` + `Event.HelloDegraded`（不伪造 hello 成功），其余错误仍致命 | core `testHelloDegrade` 16 项（8 正向含 net.connect 能发出 + 7 负对照 + 判据）；统一门禁 ALL_PASS；Debug/Release 编译 PASS；**真机 UI 逐字抓到「已连接·hello 版本探测降级…READY」+ net.status/scan 实读** |
| A2' | 🟡 能力预埋（11-18，**默认不接入配网路径**） | `ProvisioningCrypto` 纯 JVM 参考实现（X25519/HKDF-SHA256/AES-GCM）+ RFC7748/5869 权威向量 KAT + 低阶点负对照。不接入理由：固件端零加密实现、minSdk26 无稳定 X25519 API ⇒ 接入即假绿。规格见 `docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md` | core KAT 真跑通过；门禁约束「加密默认不接入」 |
| A8 | ⛔ 明确不做（用户 11-18 拍板） | 地址栏留空进 Mock 已是可用入口，`sourceRow` LIVE/DEMO 标签已齐，不另加显式按钮 | — |
| A9 / B / C | 维持不做 / 等整机 | 见 §3、§4、§5.1、§5.2 | — |

### 5.1 原厂 9 屏逐方法覆盖对照（2026-11-18 读代码核对）

一手：原厂 `mobile-app.md` §1 屏幕×调用表（fanhao 副本，清单 §1 已核对与原厂仅差 §7 一行）。核对方式：Grep `Wire.Method` 常量 + `Method.*` 实际调用点，不照规划抄。

| 原厂屏 | 原厂调用 | 当前覆盖 |
|---|---|---|
| pick a robot | 广告名+IPv4 → `hello`/`system.authenticate` | ✅ BLE 扫描/握手/认证 |
| the robot | `system.info`/`robot.health`/`system.services` +（mutating）`system.setName`/`system.reboot`/`robot.init`/`robot.enable`/`robot.rebootMotors` | 🟡 只读三项齐（A3）；mutating 侧 `robot.init`/`robot.enable` 有，**改名/重启/舵机重启未做**（等整机） |
| drive | WebRTC 视频 + `robot.move` + `robot.subscribe` | 🟡 驾驶有；**真视频 WebRTC 未接**（B 类，依赖整机 + 需拍板重型依赖） |
| moves | `robot.skills`/`robot.do`/`robot.policies`/`robot.loadPolicy` + `policy.check/search/fetch/install` | 🟡 `do`/`policies`/`loadPolicy` 有、只读模型有（A6）；**`robot.skills` + 原厂 Hub 策略流程未做**（C 类：自有训练模型优先，明确不做） |
| wifi | `net.status`/`net.scan`/`net.connect`/`net.forget` | ✅ A2 四项全做（明文仅内测） |
| update | `check`/`status`/`listInstalled`/`log` +（mutating）`apply`/`subscribe`/`rollback`/`select` | 🟡 只读四项齐（A7）；**apply/rollback/select 未做**（mutating，等整机） |
| logs | `system.logs` | ✅ A3 |
| account | `account.login`/`status`/`logout` | ❌ 未做（无对应后端，C 类明确不做） |

**连常量都没有、且仍属"可做但低价值"的边角**：`robot.safeToRestart`（重启前安全确认）、`robot.skills`（只读技能表）。二者是「the robot / moves」屏边角，未排期，非遗漏。

### 5.2 原厂 §7「机器人欠 App 的」归属判定（不在 App 仓可解）

一手：原厂 `mobile-app.md` §7 表 + §8 Open。这些是**原厂自己承认的固件/硬件欠账**，不是我们少写界面：

| 欠账 | 判定 |
|---|---|
| **加密**（§5.5/§8.1） | 交付前头号 blocker；本轮已判决：固件明文传 Wi-Fi 密码、固件端零加密实现 ⇒ App 单侧加密无法互操作。见配网加密规格文档 |
| **identify / 每台机器人 PIN / 出厂重置 / 绑定注销** | 原厂 §7 明列 "robot still owes the app"；要改固件或等硬件（打印 PIN、清 `configd`、注销 API） |
| **pad 在手机连接时重连** | 固件限制（peripheral 占用），原厂称无 daemon 修复 |
| §8 Open：PIN 屏 / 手柄从手机配对 / 双机器人一 App / UI kit | 原厂列为开放问题，非功能缺口；本项目维持不做 |

### 5.3 过程中真实踩坑（留档防复发）

1. **裸子串扫描假绿**（11-13）：新增的 Manifest 声明自检原用 `xml.contains(权限名)`；真负对照把权限名改成 `..._BROKEN` 后原串仍是子串，自检 **283/0 假绿**。改为正则提取所有 `android:name` 完整值做集合包含后，负对照正确变红（281/2，exit 1）。
2. **vivo 安装拦截**（11-13）：Manifest 新增运行时权限后 `adb install -r` 报 `INSTALL_FAILED_ABORTED: User rejected permissions`。`adb install -r -g`（自动授予运行时权限）成功。
3. **门禁全绿照不出编译错误**（11-18）：core 613/613 + 12 项门禁 ALL_PASS，但 `assembleDebug` 报 `MainViewModel.kt:84 Unresolved reference 'NetSnapshot'`（app 模块漏 import）。⇒ 新增 core 数据类被 app 引用后必须真跑 assembleDebug/Release，不能只靠门禁。
4. **注入式负对照抓出门禁自身 typo**（11-18）：`check_net_provisioning.py` 的 UI 警示负对照用 `variant(act=...)`，但 evaluate 读的 key 是 `activity`，导致该负对照"改坏后仍绿"。修 key 名后 9/9 真红。⇒ 负对照"改坏没变红"时先怀疑替换未命中/key 名错。
5. **build_duck_mesh.py 依赖 mujoco**（11-18）：统一门禁用 `sys.executable`，系统 Python 缺 mujoco ⇒ `NOT_PASS` 是环境噪声非回归；用项目自带 `.venv-mjlab/Scripts/python.exe`（mujoco 3.7.0）跑即 ALL_PASS。

**11-18 批次验证汇总**：core **613/613**；统一门禁 **ALL_PASS**（12 项）；`assembleDebug` + `assembleRelease` **PASS**；提交 `f6d4d07` 已 push（local==remote）。

⚠️ 边界：真 GATT 上板、后台保活真机行为、断链恢复提示显示均**未验证**；配网 **11-18 晚真机端到端换 WiFi 成功**（用户输入凭据授权后真发 net.connect：板子 SSID 从 Microduck-kissqy 切到 DS1002、拿到 IPv4 192.168.0.55、凭据「已存」，板子自报 net.status + 外部 ping/ARP 三观测面互证）。明文传输仍是交付前 blocker（§8.1），对外交付必须固件端加密。整机落地前 `ship_verdict=NOT_SHIPPABLE`。

### 5.4 hello 握手死锁修复（2026-11-18 晚，A2 配网链路的前置解锁）

上一轮真机验证卡在 `hello: Updater is not answering: ... os error 2`，一度判定「net.connect 链路不通、需 SSH 登板或走 8088 门户」。本轮一手源码定位后纯 App 侧修复并真机打通，无需改固件：

- **根因**：`hello → Upstream::Updater`（`duck-ipc-proto/src/lib.rs:858`），首启镜像 drop-in `zzzz-r17-manual.conf` 故意关 updaterd，`/run/updaterd.sock` 不存在（`btd/src/session.rs:218-221` 回消息）。App 把 hello 的 JSON-RPC error 一律当致命 ⇒ 到不了 auth/READY ⇒ net.connect 发不出。
- **为什么能降级**：btd 注释 `session.rs:163-166` 明说 hello「only reports versions」；`system.authenticate` 是 btd 本地应答、`net.connect → Upstream::Config`（configd），都不经过 updaterd。版本探测服务不可达 ≠ 授权/配网不可用。
- **判据（严，带负对照）**：仅 `code==INTERNAL_ERROR(-32603) && message 含 "is not answering"` 才降级；错 PIN / 普通 INTERNAL_ERROR / -32602 / -32601 / 传输失败全部仍致命。降级如实记录原因、不伪造 hello 成功/serial。
- **真机证据**（vivo V2338A 无线 adb）：BLE 连 `duck-6a07` 后 UI 显示「已连接·hello 版本探测降级（updaterd 未启动，配网/认证链路可用）：Updater is not answering… · READY」；点刷新读到 `net.status`（SSID=Microduck-kissqy / 10.42.0.1 / MAC=CC:C8:37:E3:F2:1A）与 `net.scan`（DS1002 等真实网络）。⇒ A2 换 WiFi 链路具备可用会话通道。
- **端到端换 WiFi 成功**（用户授权凭据后真发 net.connect）：二次确认弹窗（§8.1 警示 + 目标 DS1002）→「仍要连接」→ 板子自报 net.status 变为 SSID=**DS1002** / IPv4=**192.168.0.55** / MAC=CC:C8:37:E3:F2:1A（同板）/ DS1002「已存」（凭据持久化）；外部 WlanScan（首启 AP 消失）+ ping 192.168.0.55（0% 丢包）+ ARP（MAC 一致）三观测面互证。⇒ **A2「通过 App 更换主板 WiFi」真机验收通过**。凭据仅进程内存用一次，未落任何文件/日志/git。

### 5.5 配网 / 扫描列表两处 UX 改进（2026-11-18 中午，用户反馈驱动）

用户两句反馈：「SSID 不能选吗，必须手录？」「按理说无名蓝牙不应该显示出来」。两处都先查一手源码再动手，**并否决了一个想顺手做的增强**：

- `configd/src/nm.rs:585`：非开放网络 `psk.is_none()` 一律 `Failed{Unsupported,"this network needs a passphrase"}`，**即便该网络是 saved**；每次 `net.connect` 都得显式带 psk ⇒ 「点选已存网络免密直连」不成立，不做，UI 常驻如实提示「已存网络仍需填密码」。
- `configd/src/nm.rs:567`：`connect()` 内部先 `scan()` 找 SSID，扫不到直接 `NotFound`，隐藏 SSID / 802.1X 都不支持 ⇒ **从 `net.scan` 结果点选是固件唯一保证能找到网络的输入方式**（手录串框的坑已踩过）。

| 改动 | 实现 | 一手依据 |
| --- | --- | --- |
| SSID 可点选 | `net.scan` 结果由只读纯文本改为可点选列表（每项 `选择网络 <ssid>`），点一下填 `netSsidEdit`；**只写 SSID、绝不碰密码框**；`netScanSignature` 签名节流防 1s tick 重建 View / 持续发事件；手输 EditText 保留兜底 | 上面两行 `nm.rs` |
| BLE 列表只列候选 | 呈现层只列 `matchedBy != "附近设备"` 的候选，隐藏非目标（含无名）设备；状态行如实回显「附近 N 台 / 候选 M 台 / 非目标 K 台已隐藏」；候选未广播名称显示「(未广播名称)」而非杂项「(无名)」 | 原厂 `app-path-design.md` §3.3 + DuckLink 0.9.25：硬件 UUID 过滤会漏掉以空 service list 广播的 bonded 设备 ⇒ 扫描层仍 `startScan(null)` 全量接收，**过滤只绑一手判别字段 `matchedBy`（服务 UUID/广播名/已绑定），绝不按设备名筛**（否则误筛掉已绑定但无名的真板子） |

**门禁**：`check_net_provisioning.py` 9/9 → **13/13**（新增 4 条负对照：删点击监听 / 点选误清空密码框 / 去掉 tick 节流 / 删手输 EditText 必红）；新建 `tools/check_ble_candidate_filter.py` **7/7**（6 条负对照：加硬件 filters / 删候选过滤 / 退化成按名字筛 / 删已绑定兜底 / 删隐藏数量回显 / 删点击监听 必红）；统一门禁自动发现纳入，13 项 ALL_PASS；core 629/629；Debug+Release BUILD SUCCESSFUL。

**真机**（vivo V2338A 无线 adb，11:35 新包，显式授予 `BLUETOOTH_SCAN/CONNECT`）：① BLE `收到 1898 条广播 · 附近 75 台 · 候选 1 台 · 非目标 74 台已隐藏`，列表只剩 `● duck-6a07 · -36 dBm · 判别=服务 UUID`，`(无名)` / `○` 全消失，扫描层仍统计到 75 台；② `net.scan` 渲染出 9 个可点选项，点「选择网络 DS1002」⇒ SSID 框自动填入 `DS1002`；先在密码框放占位串再点「选择网络 ChinaNet-7ZyE」⇒ SSID 变更且**占位串原样保留**（证明点选不清空已输入密码）。本轮未输入任何真实 WiFi 密码、未点连接；`ship_verdict=NOT_SHIPPABLE` 不变。

---

## 5.6 软件剩余价值三方向落地（2026-11-18 晚）

用户「软件这块还能做什么」→ 判定：**不依赖整机的 App 功能已做尽**（A1–A9 + ANR + hello 降级 + 两处 UX 全有结论），
剩余价值不在"加功能"而在三件准备。用户「都做，照最优的来，记得查资料」⇒ 三件全做，全程先一手查资料：

| 方向 | 落地 | 验证 / 边界 |
|---|---|---|
| ① 体检判据 | `microduck-software/tools/hd1910/deploy_import_checklist.md` H 段新增 **H14**（IMU ID200 型号 `0x16D6`=5846/标志3/融合90–150Hz/\|q\|≈1/静止陀螺<1dps/零偏<5dps）、**H15**（SYNC_READ 错误率≤0.5%）、**H16**（写目标 42..47 联写否则 HD1910 零电流卡住）。来源 `Animan-AI/DuckBuddy` bringup 文档（社区非官方），三条均标 **UNVERIFIED**（非我方实测，上板先读实际寄存器） | 正负对照证明搜索模式有效（远端命中、本地 0 命中）后才认定"真新增"；`BIT15`/reg31/reg19/750k/ID 体系本地已有更深记录，明确**不借**；改后 `check_closure --check` rc=0、`check_contract_status`/`line_contract` --check 全 PASS、9 markers==9 ids |
| ② WebRTC 视频 | 新建 `docs/active/microduck-安卓App-WebRTC视频接入准备-2026-11-18.md`。一手查实：`google-webrtc:1.0.32006` 停维且 JCenter 关闭后无法解析 → `io.getstream:stream-webrtc-android`（Maven Central、Apache-2.0、**保留 `org.webrtc.*` 包名**、有 BOM 锁 ABI）；机器人侧 `mediad` 进程内自带信令（`ws://127.0.0.1:8443`、绑所有网卡、H.264 constrained-baseline、control+teleop 双 datachannel）；**🔴 信令端口零鉴权**（社区作者明写"a decision not an oversight"，LAN 靠共享 `000000` PIN、远程靠 bridge OAuth，端口转发直暴露无任何保护） | **只做准备，未引依赖/未改 gradle/未写代码**。接入闸门 = 先拍板安全边界（受控 LAN / 加 `system.authenticate` 门 / 走 OAuth bridge），三者未定前接视频=制造假安全。所有固件契约社区一手、非我方实测 ⇒ UNVERIFIED |
| ③ 配网加密 | `docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md` 顶部加一手更新（**不改原判决正文**）：原厂 `btd@main` **已默认链路层加密 + setup-code PSK** —— `main.rs:123` `require_pairing = args.require_pairing \|\| !args.insecure_no_pairing`、`secure_psk_file`/`ble-psk` credential/`btd::secure::Config`、`NoInputNoOutput` agent；2026-11-08 真 Android 配对成功。但**仍 just-works 未认证、iPhone/Wi-Fi 配网/生产镜像全未测** | **跨版本翻案**：本 App 对接 fanhao(API40) 本地同源副本 `main.rs:123` 仍 `if !args.require_pairing {warn}`（默认不加密）⇒ 原判决对当前目标**继续有效**；fanhao 源码本轮不在本地（`/tmp/fanhao` 空）⇒ 它是否已吸收原厂改动 **UNVERIFIED**。原 §4 X25519 应用层方案**不再唯一最优**（原厂走了 §8.1 第一行 Fix the link layer），两路线取舍需用户拍板+真机对拍，本轮不替用户选 |

⚠️ 三方向均**只改文档、未写功能代码**，未碰 xlsx/采购/契约状态/grable；`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

---

## 6. 一手来源清单

**Pollen 原厂（唯一官方）**
- `pollen-robotics/microduck@main` → `docs/design/mobile-app.md` §1 屏幕×调用表、§1.1/§1.2 两条传输、§4 会话层、§6 版本下限、§7 机器人仍欠 App 的清单、§8 Open
- `pollen-robotics/microduck@main` → `docs/design/app-path-design.md` §3.3（不要用 service UUID 硬件过滤）、§8.2（serial 是身份）、§8.1（加密三候选）
- `pollen-robotics/microduck@main` → `duck-ipc-proto/src/lib.rs`、`btd/src/route.rs`、`docs/robot/duckctl.md`
- 副本核对：GitHub REST API `api.github.com/repos/pollen-robotics/microduck/contents/...`

**非官方但一手**
- fanhao fork（API40，本 App 对接目标）`/tmp/fanhao/.../firmware/`：`duck-ipc-proto/src/lib.rs`、`btd/src/route.rs`、`docs/design/`（原厂文档副本）
- `pollen-robotics/reachy_mini_mobile_app`（Pollen 另一产品 Reachy Mini，Apache-2.0，公开）
- `Ley-WL/ducklink`（社区，前台服务持 GATT）、`OpenBot`（DISCLAIMERS）、MABEL Teleop / Hey Reachy（Demo Mode）
- Google `developer.android.com` 蓝牙权限 / 前台服务 / 手势导航；Wandelbots NOVA 合规文档（DIN EN ISO 10218-1）；KAN 对 ISO 10218 修订的解读；NIST UTAP 3.2.19；Material 3（Google）

**本项目**
- `microduck-android-app/app/src/main/kotlin/io/microduck/app/MainActivity.kt`、`DriveActivity.kt`
- `microduck-android-app/core/src/main/kotlin/io/microduck/app/core/{Wire,RobotSession,RobotTransport,DriveController}.kt`
- `microduck-android-app/app/src/main/AndroidManifest.xml`
- `docs/active/microduck-安卓App-整机落地验收清单-2026-11-13.md`
- `docs/active/microduck-来源术语约定-2026-11-13.md`
