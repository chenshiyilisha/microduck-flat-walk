# MicroDuck 安卓 App — 功能缺口与可加功能清单（资料支撑版）

_2026-11-13。用户要求：「看看还缺什么功能，还有什么功能可以加上，找找资料」。_
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
| A1 | **BLE 前台服务 + `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_CONNECTED_DEVICE` / `POST_NOTIFICATIONS` + 运行时权限请求** | ✅ Google `developer.android.com/develop/connectivity/bluetooth/bt-permissions`：API31+ 的 SCAN/CONNECT 是运行时权限、SCAN 可加 `neverForLocation`；API34+ 的 `connectedDevice` FGS 类型需先持有 BLUETOOTH_CONNECT/SCAN/ADVERTISE 之一；API31+ 后台起 FGS 抛 `ForegroundServiceStartNotAllowedException` ⇒ 必须在 Activity 可见时启动。🟡 社区 `Ley-WL/ducklink`：前台服务持 `BluetoothGatt` + 全部 GATT 操作串行 | **代码里确定缺**：Manifest 只有 `BLUETOOTH_SCAN/CONNECT`（已正确加 `neverForLocation`、legacy 限 `maxSdkVersion=30`），**没有 FGS 权限、没有 Service 声明** ⇒ 切后台/锁屏 GATT 会断，真 GATT 上板必踩 | **最高优先**。生命周期可用 `FakeGattLink` 在 JVM 测，不需整机 |
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

## 5. 一手来源清单

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
