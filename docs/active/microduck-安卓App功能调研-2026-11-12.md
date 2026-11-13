# MicroDuck 安卓 App 功能调研（HD-1910 / fanhao 栈版）

> 日期 2026-11-12。用户要求：给 MicroDuck 开发一款安卓 App，先调研需要什么功能。
> 用户补充：主链用 **fanhao 的方案**（ft1910 系），并希望在调研结果之外**自行考虑需要什么功能**。
> 本文件只做调研，不写代码。结论基于一手资料：Pollen 原厂设计文档、机器人侧协议源码、社区 APK。
>
> **🔴 来源术语（2026-11-13 用户明确；准绳见 `docs/active/microduck-来源术语约定-2026-11-13.md`）：
> 本项目「官方 / 原厂」只指 Pollen Robotics 原厂 `pollen-robotics/microduck`。**
> 本文历史行文里的「官方」一律读作 Pollen 原厂；`fanhao375/Microduck-kissqy`（API40，本 App
> 对接目标）、B 代 API16 本地快照、`pollen-robotics/reachy_mini_mobile_app`（Pollen **另一产品**
> Reachy Mini 的公开 App）均**不是官方**，须具名。原厂手机 App 仓 `pollen-robotics/microduck-app`
> 私有（GitHub API 404），只能引用其设计文档。
> ⚠️ API 版本三套别混：原厂 main=61（2026-11-13 实测）、fanhao=40（对接）、B 代=16（联调证据）。
>
> **核心结论：对接目标已定为 fanhao 栈（`fanhao375/Microduck-kissqy` fork）。**
> Pollen 原厂早就设计并实现过这款 App（`pollen-robotics/microduck-app`，Tauri 2 + React），但仓库私有。
> fanhao 栈**完整继承了 Pollen 原厂的 BLE 契约**（`duck-ble`/`duck-ipc-proto`/`btd/route.rs`），
> 且 `API_VERSION=40` 满足原厂设计文档 §6 的 App 下限 31。我们要做的不是从零设计功能，而是：
> **照原厂功能清单裁剪 → 结合我们实际处境补充 → 自研客户端**。

---

## 0. 一句话结论

| 问题 | 答案 |
|---|---|
| 对接哪个 robotd 栈 | **fanhao**（`fanhao375/Microduck-kissqy`，分支 `hd1910-v167-trunk-imu-i2c`），已一手核实 |
| 功能清单从哪来 | 官方 `docs/design/mobile-app.md` §1 的屏幕×调用表，fanhao 原样保留，直接适用 |
| 协议版本 | fanhao `API_VERSION=40`（官方 App 下限 31，满足） |
| 驾驶通道 | 官方走 WebRTC；**fanhao 额外提供 UDP 手柄（netpad）**，是更轻的备选——见 §5 |
| 我们的独特需求 | 无整机（台架期）、只有 walk 策略、有自训模型 → 见 §5「基于我们处境的功能考虑」 |

---

## 1. 前置：App 对接 fanhao 栈（已核实，不再是决策点）

fanhao 栈 = kissqy 的 HD-1910 整套（R17 V167 / control.43）+ 三样可选改动（躯干 IMU、舵机调参、UDP 手柄）。
本地已拉源码逐项核实（`/tmp/fanhao/Microduck-kissqy-hd1910-v167-trunk-imu-i2c/microduck-hd1910/firmware/`）：

| 项 | fanhao 栈实况 | 核实依据 |
|---|---|---|
| 来源 | `fanhao375/Microduck-kissqy` fork，分支 `hd1910-v167-trunk-imu-i2c`（默认分支） | GitHub API |
| 固件版本 | **control.43**（`1fa8438-feetech-ft6-control.43`） | `BUILD.json:120` |
| API 版本 | **`API_VERSION = 40`** | `duck-ipc-proto/src/lib.rs:437` |
| BLE 服务 | ✅ **btd + duck-ble 完整在仓**，编进固件、板上可跑 | `board-test.sh:470` 跑 `/bin/robot/btd --version` |
| BLE 契约 | 与官方**逐字节相同**：服务 `6f5d2a10…`、RPC `6f5d2a11…`、PIN `000000`、NDJSON 分帧 | `duck-ble/src/gatt.rs`、`btd/src/pairing.rs` |
| 路由表 | 与官方**同一套**（允许/拒绝逐条理由一致） | `btd/src/route.rs` |
| 驾驶通道 | ① WebRTC（mediad，官方路径）② **UDP 手柄 netpad（:4210，fanhao 新增）** | `docs/design/remote-webrtc.md`、`docs/robot/udp-pad.md` |
| 中控 | SSH 基（非 WebSocket）；另有 webpad 浏览器手柄服务 | `console/connection.py`、`microduck-webpad.service` |
| 官方 App 文档 | `mobile-app.md`/`app-path-design.md` **fanhao 原样保留**，功能清单直接适用 | `docs/design/` |
| 现成 APK | ❌ release 资产里没有 APK（只有中控/训练中控 ZIP 和固件） | `release-assets/` |

🔴 **修正**：此前记忆里写 fanhao 是「control.44」，一手核实为 **control.43**（BUILD.json 权威）。

**结论**：App 直接照官方 BLE 契约做即可，无需为「有没有 BLE」担心——fanhao 栈 BLE 全通，`API_VERSION 40 ≥ 31`。

---

## 2. 官方 App 功能清单（照抄这个表，fanhao 契约适用）

来源：fanhao 仓 `docs/design/mobile-app.md` §1 + `btd/src/route.rs` 逐臂核对。
每个屏幕 = 一组 JSON-RPC 调用（BLE 或 WebRTC）。

| # | 屏幕 | 调用 | 用途 |
|---|---|---|---|
| 1 | **选机器人** | 广告（name + IPv4）→ `hello` → `system.authenticate`（PIN） | 发现、身份、认证。广告带 IPv4（manufacturer data），无需连接即见地址 |
| 2 | **机器人主页** | `system.info`、`robot.health`、`system.services`、`system.setName`、`system.reboot`、`robot.init`、`robot.enable`、`robot.rebootMotors` | 让鸭站起来（init）、开策略（enable）、看健康、改名、重启 |
| 3 | **驾驶** | WebRTC：视频 + `robot.move` + `robot.subscribe` | 摇杆/键盘驱动 + 相机流。**不走 BLE** |
| 4 | **技能/策略** | `robot.skills`、`robot.do`、`robot.policies`、`robot.loadPolicy`、`policy.check`、`policy.search`、`policy.fetch`、`policy.install` | 让鸭做技能、热换策略、从 Hub 装策略 |
| 5 | **Wi-Fi** | `net.status`、`net.scan`、`net.connect`、`net.forget` | 配网。**BLE 独有价值**：无网机器人的救砖路径 |
| 6 | **升级** | `update.check`、`update.apply`、`update.subscribe`、`update.status`、`update.listInstalled`、`update.log`、`update.rollback`、`update.select` | 系统升级/回滚/进度订阅 |
| 7 | **日志** | `system.logs` | 各 daemon journal tail |
| 8 | **账号** | `account.login`（HF OAuth 设备码）、`account.status`、`account.logout` | 签名登录（远程访问前置） |
| 9 | **手柄绑定** | `pad.bindings`、`pad.bind` | 手机给手柄按键绑技能（路由了但官方 App 未 reach） |
| 10 | **其他路由** | `robot.reloadPolicies`、`robot.model`、`robot.setSkill`/`removeSkill`、`detector.check`/`install` | 重读策略、模型信息、技能表编辑、鸭群检测模型 |

### 2.1 BLE 上**允许** vs **拒绝**（route.rs，拒绝返回错误码 14）

**允许（App 可做）**：`hello`、`system.authenticate`（本地）、`system.*`、`net.*`、
`update.check/status/apply/subscribe/log/rollback/select/listInstalled`、
`robot.health/policies/skills/model/do/init/enable/rebootMotors/rest/loadPolicy/reloadPolicies/setSkill/removeSkill`、
`policy.check/search/fetch/install`、`detector.check/install`、`pad.bindings/bind`、`account.*`。

**拒绝（App 不可做，官方理由在 route.rs 注释里）**：
- `robot.move/head/look/pose/mouth/stop/relax/subscribe` —— 遥测是 50 Hz 流，BLE 通知只有 512 B/chunk，
  装不下；e-stop 不做是因为「看起来是 e-stop 实际不是」比没有更糟（死man 机制兜底）。
- `pad.input`、`tof.stream`、`head_imu.stream` —— 同样是高频流，走 mediad 视频路径。
- `robot.sound/theremin/chorale`、`robot.shutdown`、`robot.mode/setMode` —— 留给手柄/终端。
- `update.pin`、`update.resetToGolden`、`system.pairingPin/setPairingPin` —— 永不上无线电。

### 2.2 两条传输的分工（官方架构，别混）

```
BLE（永远在线、无网可用）   → 配置/健康/技能/配网/升级/日志/账号
WebRTC/局域网（需网络）     → 驾驶（robot.move）+ 视频 + 高频状态流
```
`drive` 屏需要网络，地址从 `net.status`（经 BLE）拿——「永远能用的传输告诉你怎么连快的传输」。

---

## 3. 传输契约（照抄公开源码，别自己发明）

来源：fanhao 仓 `duck-ble/src/{gatt,framing,adv}.rs`、`app-path-design.md`（与官方同）。

| 项 | 值 |
|---|---|
| GATT 服务 | `6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019` |
| RPC 特征 | `6f5d2a11-3b47-4c8e-9a1f-2d7e8c4b6019`（**读写+通知合一**，一个特征两用） |
| 帧格式 | NDJSON 行分隔（`\n` 即帧界），chunk 重组上限 8 KiB |
| 版本读取 | 连接后先 **read** 一次 RPC 特征拿 `API_VERSION`（需要加密链路，同时促成配对） |
| 认证 | `system.authenticate` 带 6 位 PIN；3 次失败断连；PIN 默认 `000000`（公开） |
| 广播 | 间隔 100–150 ms（默认 1.28 s 太慢）；name 在 scan response；IPv4 在 manufacturer data |
| MTU | 手机协商 515 → 通知按 512 B chunk |
| 身份 | 名 = `duck-` + SoC 序列号 SHA-256 前 4 hex；App 以 **serial 为 key**（地址会变，serial 不变） |
| 会话 | 断线=重新认证；订阅分 lane，一连接一 lane |
| 加密 | ⚠️ 官方默认**明文**（`--require-pairing` 关着）。内部使用可照抄；若要交付需自加应用层加密（Reachy Mini 的 x25519-hkdf-sha256-aesgcm 是现成方案） |

---

## 4. 社区 APK 对照（hd1910m `com.microduck.control 0.1.2`）

来源：`.upstream/hd1910m/microduck_app/backend/src/main.rs`（441 行，全部功能）。
（这是**另一条栈**，无 BLE，仅作「驾驶+技能」功能集的对照，不是我们的对接目标。）

| 维度 | 它的做法 |
|---|---|
| 形态 | APK = WebView 壳，连 PC 的 `http://电脑IP:38880`（Rust axum 后端）；**无 BLE 原生** |
| 发现 | UDP 广播 `MICRODUCK_DISCOVER_V1` :38882 |
| 驾驶 | WebSocket `move`：vx±0.30、vy±0.04、vyaw±0.8（Reference 模型） |
| 技能 | walk/stand/recovery/ground_pick/roulade/step；`enable`、`stop`、`clear_fault` |
| 安全 | 死man 300 ms、owner 独占（claim_control）、命令范围校验 |
| 无 | 配网、升级、日志、账号、BLE 救砖 |

**结论**：它证明了「驾驶+技能」的最小功能集，但形态（WebView+PC 中转）不是我们想要的。
我们的 App 应覆盖：**官方 BLE 救砖链路（配网/升级/健康）+ 驾驶体验**。

---

## 5. 基于我们实际处境的功能考虑（调研之外，自主补充）

这一节不是照抄官方，而是结合**我们的现状**（无整机、台架期、只有 walk 策略、有自训模型、fanhao 栈特性）提的功能。

**我们的现状（决定功能取舍）**：
- 无整机：仍是台架 PC + URT-2 + 单舵机，整机未落地 → App 需要**台架/仿真开发模式**，否则没东西可测。
- 只有 walk 策略，无 stand/skill；自训 `p8head_2999`（hd1910_kp8 plant）→ 技能屏初期只有 walk 语义，
  策略屏要能管理**我们自己的模型**，而非官方 Hub 流程。
- E3 结论：p8head_2999 低层 vx 命令通道响应弱（undershoot ~45%）→ 摇杆的**速度标定/死区**要可调。
- 低速死区 cmd≥0.15（训练侧结论）→ 摇杆死区要照此设。
- fanhao 栈独有：UDP 手柄 netpad、舵机调参、躯干 IMU 融合。

### 5.1 驾驶通道：UDP 手柄（netpad）优先，WebRTC 做视频

官方 App 驾驶走 WebRTC（视频 + `robot.move` + `robot.subscribe` 一条龙）。但 fanhao 额外提供 **UDP 手柄 netpad**：

| 通道 | 优点 | 缺点 | 建议 |
|---|---|---|---|
| **UDP 手柄 netpad（:4210）** | 客户端极轻（发游戏手柄状态数据报，wire 格式 = `duckctl udp-pad`，逐字节同上游）；延迟低；无需 WebRTC 栈 | **默认关**，需在板上 `service.sh netpad on`（要 root/ssh，**无 JSON-RPC 方法可开**）；**无视频** | **驾驶首选**（P1），前提是板上预开 netpad |
| **WebRTC（mediad）** | 自带视频 + 驾驶 + 高频状态流；板上常开、无需预配置 | 客户端要实现 WebRTC（原生 Android 较重）；**信令端口不鉴权**，局域网内谁都能开鸭 | **视频用它**（P2），驾驶也可走它（免预配置） |

🔴 **关键约束**：netpad 没有 JSON-RPC 开关，App 无法经 BLE 远程打开它——要么板上预开，要么改用 WebRTC 驾驶。
**推荐组合**：驾驶走 UDP 手柄（轻、快），视频走 WebRTC（独立），两者解耦。若不愿在板上预开 netpad，则驾驶也走 WebRTC。

### 5.2 舵机健康诊断屏（`robot.health` 细化）

fanhao 的 `robot.health` 含**每个舵机的电压/温度/负载**、IMU、电池。做一张 15 舵机网格/列表屏：
- 用途：台架标定、提前发现失效舵机、电池监控（NP-F550 2S 7.4V，低电告警防过放）。
- 这是官方 App 没单独做的，但对「调试+维护」价值高，且数据源现成。

### 5.3 自有策略优先的策略屏（不做官方 Hub 流程）

我们的策略是本地的（walk / `p8head_2999`），不是从 HF Hub 搜来的。初期：
- `robot.policies` 列已装策略、`robot.model` 显示当前 plant/模型信息、`robot.loadPolicy` 切换。
- **不做** `policy.search/fetch/install`（官方 Hub 流程）——我们用不上，且无整机时无意义。
- 屏上标注当前 plant（hd1910_kp8）和模型版本，避免误切。

### 5.4 标定/零位引导（开发者模式）

fanhao 有 `servo-parameters`、`calibration-config.py`、关节零位标定（`joint_offsets = raw_at_joint_zero - 2048`）。
- App 可做一个**开发者标定模式**：引导零位标定、显示标定结果。
- ⚠️ 对普通用户有风险（标定错会摔），建议限开发者模式/需确认。

### 5.5 故障/跌倒状态屏

FallPredictor、gain_limp、跌倒事件。显示：跌倒检测、limp 模式是否激活、故障历史，
一键恢复（`robot.init`）。安全感知价值高，数据源现成。

### 5.6 台架/仿真开发模式（当前最实际，含传输层前置）

无整机期，App 必须能连 **`robotd --sim`（仿真鸭）** 或台架 robotd 做开发自测——这是**现在就能开发测试、不用等整机**的关键。但有一个**传输层前置问题**必须先解决：

🔴 **`robotd` 只在 unix socket 上服务，Android 连不了。** 一手核实：`robotd/src/main.rs` 用 `tokio::net::UnixListener` 绑定 `/run/robotd.sock`，**没有 TCP/WebSocket 监听**；`btd` 是 BLE↔unix socket 的桥（`btd/src/bluez.rs` 用 `UnixStream` 连 robotd）。仿真模式下没有真板、没有 BLE，App 够不到这个 socket。

**解法 = 在 App 与 robotd 之间插入一个「传输抽象层」，真机/仿真后端可换。** 这正是官方和社区参考实现的做法（见 §5.9 对照四/五），不是我们发明。四种可达传输（全部承载**同一份 NDJSON JSON-RPC**）：

| 后端 | 怎么连 | 无整机期可用 | 说明 |
|---|---|---|---|
| **`robotd --sim` + TCP** | `robotd --sim <addr>` 内部 `duck_control::sim::RemoteIo` 就是 **TCP**（`duck-control/src/sim.rs`）；同一 daemon、同一 IPC/策略/安全层，只换 body | ✅ | 仿真鸭跑在 PC，MuJoCo 喂关节；`--sim` 上层「无法分辨真假」。**这是 App 开发的主后端** |
| **TCP relay / `ssh -L`** | PC 上 `ssh -L 7788:/run/robotd.sock` 或跑一个 relay 把 unix socket 转 TCP :7788，App 连 TCP | 部分（需台架 robotd） | OpenCastor 实证的 off-board 路径；Android 有 `DatagramSocket`/`Socket`，直连 TCP 无障碍 |
| **WebRTC（mediad :8443）** | 连 mediad 信令，开 `control` datachannel——源码原文「a pipe to the robot API」，跑 NDJSON | ✅（若 mediad 也在仿真旁跑） | 官方驾驶路径，自带视频；信令不鉴权 |
| **Mock transport** | App/A 侧内置假后端返回 canned `robot.health`/`robot.state` | ✅ 最轻 | microduck-mcp 的 `mock` 档；**UI/会话层开发第一步用它**，连 PC 都不用 |

**设计要点（P0 核心）**：App 定义一个 `RobotTransport` 接口（`connect` / `send(NDJSON)` / `subscribe` / `close`），四个实现 `BleTransport`(真机) / `TcpTransport`(仿真+relay) / `WebRtcTransport`(驾驶+视频) / `MockTransport`(无后端自测)。**上层会话层（重连/重认证/重订阅）、所有屏幕、安全逻辑只面对这一个接口**——于是：
- 无整机期用 `Mock` + `Tcp(sim)` 把会话层和各屏全部开发测完；
- 整机落地后**只换 transport 实现**，上层零改动（Reachy Mini（Pollen 另一产品）的 `daemon --sim` 与真机同 API、SDK 不改代码，是同一思路）。
- 🔑 这把「仿真开发模式」和「会话层」两个 P0 合并成**同一个架构决策**：先定 `RobotTransport`，两者一起落地。

⚠️ 注意 sim fidelity：microduck-mcp 的独立实测指出**参考 MuJoCo 场景对小速度命令 under-track、弱 yaw**（与我们 E3 的 undershoot ~45% 独立吻合）→ 仿真后端**不能用来标定驾驶手感**，只用来测协议/会话/UI 数据流；真实手感必须整机调。

### 5.7 摇杆手感调参（回应 E3 的弱响应）

E3 显示低层 vx 响应弱（undershoot ~45%），则 App 摇杆需要：
- 可调**最大速度上限**、**死区（≥0.15）**、**指令缩放**（补偿弱响应）。
- 可设「稳健/激进」档位。

### 5.8 明确不做（沿用官方 route.rs 的拒绝理由）

- **e-stop 按钮**（`robot.stop` 被拒）：死man 机制兜底，假 e-stop 比没有更糟。
- **factory reset / PIN 管理界面**（`update.resetToGolden`、`system.pairingPin` 被拒）：永不上无线电；PIN 默认 `000000`。
- **BLE 上跑驾驶流**：改 route.rs 不推荐，官方理由充分。

---

## 5.9 外部参考实现对照（取长补短）

用户要求「多找资料对照，取长补短」。除官方文档外，找到两份**公开源码**可对照：

### 对照一：`pollen-robotics/reachy_mini_mobile_app`（Pollen **另一产品** Reachy Mini 的参考 App，Apache-2.0，公开）

这是 **Pollen 原厂** `docs/design/mobile-app.md` §2 说的「参考实现」，仓库**公开可读**
（`pollen-robotics/microduck-app` 本身私有；此仓是 **Reachy Mini**，**不是 MicroDuck 官方**）。
Tauri 2 + React 19 + MUI + tauri-plugin-blec，iOS/Android/桌面三端。**它的 BLE 是「跑一次」的配网向导，
我们的是「永久通道」——结构不同，但配网 FSM、错误恢复、地址可见性的做法可直接借。**

| 借什么（规则/模式） | 具体 |
|---|---|
| **每个错误带 `recoverPhase`** | "Try again" 弹回出错的那个步骤，不重开整个流程。配网是多步 FSM，这是关键 UX |
| **地址徽章（address badge）** | 把两个「看不见的前置条件」显性化：IP 解析中 / 已找到 IP / 手机可达 / 不可达。让配网进度不撒谎 |
| **HTTP 探测 = 真正的「同网」测试** | IP 是经 BLE 读的，证明不了手机也在同网。手机→机器人 HTTP probe（任何响应即算可达）才是真测试。**只作信息，不阻断流程** |
| **无 mDNS 回退** | `xxx.local` 在手机网络下不稳，打不开不可达 URL 会假造进度。**只认 LAN IP** |
| **`WIFI_STATUS.mode` 门控** | 区分 hotspot（机器人自己的 AP，非联网）vs 真联网，决定走「已在线」快路径还是走 Wi-Fi 扫描 |
| **BLE 掉线在等签时是预期，不是错误** | 开 HF 页面会后台化 App，iOS 会拆 GATT 链路。此时 BLE 已完成使命，断连监听应忽略而非杀流程 |
| **`connectedSsid` 记忆** | 记住已连的网，返回时直达，不重复输密码 |
| **device-code 屏以码为主** | 设备码屏先显示码（点按复制），不自动跳浏览器（自动跳会挡住用户看码） |
| **RobotSession 类** | 封装 WebRTC + 重试感知的 bring-up、wake/sleep、视频缓存、传输/数据通道健康监测 |
| **BLE 权限处理、edge-to-edge、安全区、竖屏锁** | Android BLE 运行时权限处理（选 blec 而非裸 btleplug 的理由） |

| 不借（它的场景不同） | 原因 |
|---|---|
| 配网向导状态机整体 | 它的 BLE 只跑一次；我们的 BLE 是永久通道，要有常驻会话层（自动重连+重认证） |
| TanStack Query | 它缓存 HTTP 服务端状态，我们没有 HTTP 服务端状态可缓存 |
| 字符串匹配的错误分类（`ERROR:`/`OK:`/`ECHO:`） | 官方 `configd` 用类型（`BadKey`/`NotFound`），缺方法自名 `METHOD_NOT_FOUND`，别学这套 |
| 它们的 btleplug vendored patch | 上游已修，blec 0.14 基于 btleplug 0.13，patch 已不需要 |

### 对照二：`TonyRuan/microduck-android`（社区安卓 App，Apache-2.0，公开，已发 APK）

手机端跑**仿真**（策略+MuJoCo 全离线，不连真机，无网络权限）。**它不是机器人控制 App，但驾驶屏的 UX 模式可直接搬。**

| 借什么 | 具体（搬到我们的驾驶屏） |
|---|---|
| **半透明浮动摇杆** | 左下浮动摇杆，前/后/左转/右转，松手即停。触感比静态摇杆好 |
| **松手归零 = 安全** | 摇杆松开自动回中、指令清零。配合死man，双保险 |
| **快捷动作按钮** | 坐/站/滚/踢一行按钮 → 对应我们的 walk/stand/技能按钮 |
| **可折叠参数面板** | **前速、后速、转向速度分开设**（不是单一速度）。回应我们 E3 弱响应：可分别调 |
| **Android 生命周期** | 后台暂停物理、**恢复时摇杆自动归零**、速度/档位持久化。安全且符合 Android 习惯 |
| **无网络权限（按需）** | 纯离线功能不申请网络权限，降低审核/隐私面 |

| 不借 | 原因 |
|---|---|
| 手机端跑仿真/策略 | 我们的策略在板上 robotd 跑，手机是控制端不是执行端（除非做「仿真鸭」离线演示模式，可作 P3 彩蛋） |
| 横屏锁定 | 我们的 App 以竖屏操作为主（参考 Reachy），横屏仅驾驶屏可横 |

### 对照三：`hd1910m` APK（社区，WebView+WebSocket，见 §4）

借「驾驶+技能」最小功能集的**命令范围与安全参数**：vx±0.30 / vy±0.04 / vyaw±0.8、死man 300 ms、owner 独占。
不借其形态（WebView+PC 中转，无 BLE）。

### 综合取舍结论

- **架构**：原生 Kotlin（Android 首选）。BLE 层照抄 `duck-ble` 契约；**配网 FSM + 错误 recoverPhase + 地址徽章**照 Reachy 借；**驾驶屏摇杆 UX** 照 microduck-android 借。
- **会话层是核心**（官方 mobile-app.md §4）：BLE 是永久通道，App 要有自动重连+重认证+重订阅的会话层，且每个屏幕容忍链路掉线再回来（含升级中 btd 重启、签等待时后台化掉线）。**这是 App 真正的复杂度所在，优先做。**
- **驾驶**：摇杆（松手归零、前后/转向分速可调）+ 快捷动作按钮；通道用 fanhao 的 UDP 手柄 netpad（预开）或 WebRTC（§5.1）。
- **可见性**：地址徽章、连接状态、死man 倒计时、舵机健康——把「看不见的状态」显性化，是三份参考的共同优点。

---

## 6. 功能优先级（结合现状重排）

| 优先级 | 功能 | 说明 |
|---|---|---|
| **P0 会话层** | BLE 常驻会话：自动重连+重认证+重订阅，每屏容忍掉线再回来 | 官方 mobile-app.md §4：**App 真正的核心复杂度**，优先做 |
| **P0 台架/仿真开发模式** | 连 `robotd --sim`/台架 robotd，全链路自测 | 无整机期唯一能开发测试的路径 |
| **P0 救砖/配置**（无网可活） | 发现配对、`system.info`/`robot.health`、`net.*`、`update.*`、`system.logs` | 官方 App 核心价值；无网机器人唯一入口 |
| **P0 配网 FSM** | 扫描→连接→PIN→配网→地址徽章→同网探测，每步错误带 recoverPhase | 照 Reachy 参考实现借（§5.9） |
| **P1 驾驶** | 浮动摇杆（松手归零、前后/转向分速可调）+ 快捷动作按钮 + 死man 显示 | UX 照 microduck-android 借；通道走 UDP 手柄 netpad（预开）或 WebRTC |
| **P1 舵机健康/电池屏** | `robot.health` 15 舵机明细 + 低电告警 | 调试+维护，数据源现成 |
| **P2 视频** | WebRTC 相机流 | 需实现 WebRTC 客户端，较重 |
| **P2 自有策略管理** | `robot.policies`/`robot.loadPolicy`/`robot.model` | 不做官方 Hub 流程 |
| **P3 标定/故障/技能** | 开发者标定模式、故障跌倒屏、walk 技能、离线仿真鸭演示 | 有整机后价值上升 |

---

## 7. 技术选型建议

| 方案 | 优点 | 缺点 | 适配度 |
|---|---|---|---|
| **原生 Kotlin + Android BLE** | Android 体验最好、BLE 栈最成熟、无 Rust 依赖 | 协议解析自己写（照抄 duck-ble 即可） | ★★★★（**Android 首选**） |
| Tauri 2 + React + tauri-plugin-blec（官方路线） | Rust 侧直接复用 `duck-ipc-proto`/`duck-ble`，协议变更编译期暴露 | 打包链重、BLE 插件维护成本 | ★★★（官方同款，但 Android 上非首选） |
| Flutter + flutter_blue_plus | 一套代码双端、BLE 生态成熟 | 与官方 Rust 协议库脱节 | ★★★ |
| WebView 壳 + 后端（hd1910m 路线） | 最快出活 | 依赖网络、无 BLE 救砖 | ★★（仅作对照） |

**建议**：Android 优先**原生 Kotlin**（BLE 是 Android 强项，协议照抄 `duck-ble` 三个文件即可）；
驾驶通道与 BLE 解耦——同一 JSON-RPC 方法面，BLE 做配置/健康，UDP 手柄或 WebRTC 做驾驶。

---

## 8. 风险与待确认（动手前必须解决）

| # | 事项 | 状态 |
|---|---|---|
| R1 | 对接栈定为 fanhao | ✅ **已闭合**（一手核实 BLE/API40/路由表全通） |
| R2 | 官方 App 仓库私有（404）→ 协议细节照 `duck-ble`/`duck-ipc-proto` 源码 + `duckctl.md` | ✅ 已核 |
| R3 | BLE 明文传输默认开启 | ⚠️ 内部使用可接受，交付前需应用层加密 |
| R4 | netpad 默认关、无 JSON-RPC 开关 → 驾驶若走 UDP 需板上预开 | ⚠️ 需用户拍板（预开 netpad vs 纯 WebRTC） |
| R5 | 我们无 stand 策略 → App「站立」按钮语义（`robot.init` 直接进 HOME？） | 设计时定 |
| R6 | 低速死区 cmd≥0.15 + E3 弱响应 → 摇杆死区/缩放要调 | 训练侧结论，App 照做 |
| R7 | WebRTC 信令端口不鉴权 | ⚠️ 仅可信局域网；交付前评估 |
| R8 | control 版本：记忆曾写 .44，一手核实为 **.43** | ✅ 已修正 |

---

## 9. 参考资料（本仓一手 + 外部公开源码）

**外部公开源码（对照，已拉本地 `/tmp/reachy/`、`/tmp/mda/`）**：
- `pollen-robotics/reachy_mini_mobile_app`（Apache-2.0，**公开**）—— 官方参考实现，Tauri2+React19+MUI+blec，
  三端；`docs/BLE_SETUP_FLOW.md`（配网 FSM/地址徽章/同网探测）、`docs/BLE_SCAN_ARCHITECTURE.md`、
  `src/features/robot-session/`（RobotSession/重试/健康监测）。**配网与错误恢复的取长来源**。
- `TonyRuan/microduck-android`（Apache-2.0，**公开**，已发 APK）—— 手机端仿真 App；
  半透明摇杆/快捷动作/分速参数面板/生命周期归零。**驾驶屏 UX 的取长来源**。
- `microduck-software/.upstream/awesome-microduck/readme.md` §Apps and Ports / Mobile and XR
  —— 社区手机端/XR 全清单（除上述外多为仿真，无第二份真机控制 App）。

**外部一手资料（传输抽象层 / 仿真开发模式，本轮新增，Web 检索）**：
- **`craigm26/OpenCastor` `docs/hardware/microduck.md`**（GitHub）—— 第三方驱动库，列出到达 robotd 的
  **四种传输全部承载同一份 JSON-RPC**：`unix` `/run/robotd.sock` / `ssh -L 7788:/run/robotd.sock` /
  `tcp relay :7788` / `webrtc mediad:8443`（control datachannel）。实证 off-board 推荐 `ssh -L` 转发；
  确认 mediad 无鉴权、绑 0.0.0.0。**§5.6 四传输表的一手来源**。
- **`joeynyc/microduck-mcp`**（LobeHub 索引）—— MCP server，`DuckTransport` 单接口统一
  `mock`(canned) / `sim`(CPU MuJoCo+官方ONNX, sidecar) / `unix` / `ssh`，原文「工具与安全层在仿真和真机上完全相同」。
  **§5.6 `RobotTransport` 抽象的直接原型**；其 sim fidelity note（小速度 under-track、弱 yaw）与 E3 独立吻合。
- **Reachy Mini（Pollen 另一产品）的文档**（Seeed wiki + `involvex/reachy_mini` `docs/platforms/simulation/get_started.md`）——
  `reachy-mini-daemon --sim` 与真机**同一套 HTTP(localhost:8000)/WebSocket API**，Python SDK 不改代码；
  Daemon 监听 localhost 提供 REST+WebSocket。**「仿真/真机同 API、客户端不改代码」的官方背书**。
- **Hey Reachy**（`apps.apple.com` 独立客户端，非 Pollen 官方）—— Connect 页 Developer 下
  「Start the simulator」**无机器人/无网/无账号**开会话，App 自带模拟器；直连 daemon 公开的 HTTP/WebSocket API。
  **§5.6 「无后端开发模式」的产品级对照**。
- **MicroDuck 架构二手拆解**（`tonybai.com` / `youduck.ai/reference/concepts/control-plane`）——
  确认 IPC 选 Unix Socket 的理由（0660 权限组 + SO_PEERCRED 审计 + 物理上杜绝监听错网卡），
  以及「同一套 serde 消息类型复用在 BLE 和 WebRTC 数据通道上」= 官方设计意图，非我们臆断。

**本仓一手**：
- fanhao 源码（本地 `/tmp/fanhao/Microduck-kissqy-hd1910-v167-trunk-imu-i2c/microduck-hd1910/firmware/`）：
  - `docs/design/mobile-app.md` —— 官方 App 设计（功能清单源头，fanhao 原样保留）
  - `docs/design/app-path-design.md` —— BLE 契约（GATT/配对/路由/广告）
  - `docs/design/remote-webrtc.md`、`docs/robot/udp-pad.md` —— 驾驶/视频通道
  - `btd/src/route.rs` —— 路由表（允许/拒绝逐条理由）
  - `duck-ble/src/*.rs` —— GATT UUID/分帧/广告（wire contract）
  - `duck-ipc-proto/src/lib.rs` —— `API_VERSION=40`
  - `IMU-MODULE.md`（仓库根）—— fanhao 三样改动（躯干 IMU/舵机调参/UDP 手柄）
- `microduck-software/.upstream/ft1910/docs/design/mobile-app.md` —— 官方 App 设计（同源）
- `microduck-software/.upstream/hd1910m/microduck_app/backend/src/main.rs` —— 社区 APK 后端（驾驶/技能功能集对照）
- `docs/active/microduck-HD1910阶段C软件清单.md` §1 —— robotd 栈选型背景
