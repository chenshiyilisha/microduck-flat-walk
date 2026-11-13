# MicroDuck 安卓 App — P0 开发计划：会话层 + 仿真开发模式

> 日期 2026-11-12。承接 `microduck-安卓App功能调研-2026-11-12.md`（对接栈=fanhao，语言=原生 Kotlin）。
> 本文件把调研报告 §6 的两个 P0（**会话层**、**台架/仿真开发模式**）落成可执行计划。
> 结论基于一手源码（fanhao 固件 `duck-ipc-proto`/`duck-ble`/`btd`/`robotd`/`mediad`）与四份外部参考实现。
> **范围声明**：本文保留 2026-11-12 制定的原始计划（含当时的假设），**逐阶段追加实测进度与修正**。
> 现状（Pass134 / 2026-11-12）：阶段 A/B/C1/**C2**/C2+/D **全部落地**，且 **P1 驾驶+健康屏已落地并产出 debug APK**；
> 代码在 `microduck-android-app/`。下文表格中的「预期出口」如与实测不符，以紧随其后的 ✅ 进度段与 README 为准
> （尤其 API_VERSION 与认证归属）。
> 无整机（台架期），P0 目标都已在 PC 上闭环验证；**P1 驾驶手感标定按 §216 必须整机测，仿真不作数**。
>
> ✅ **P1 实测（Pass134）**：`core` 新增 `Twist` / `NetpadWire`（28B wire 逐字节移植）/ `DriveController` /
> 双 `DriveSink`（JSON-RPC notification 与 UDP netpad）/ `HealthSnapshot`；`RobotSession.notify()` 支持
> 无 id 连续意图，三个 transport 后端已显式声明「无 id 行写出即返回、不等响应」。
> `app` 新增 `JoystickView`（ACTION_UP/ACTION_CANCEL 同归零）+ 驾驶/健康双页 `MainActivity`。
> 证据链：`selftest.sh` **163/163**、`c2_drive_gate.sh` 真固件驾驶 **28/28 连跑 5 次**、原 C2 **11/11** /
> C2+ **24/24** 复跑未破坏、`:app:assembleDebug` BUILD SUCCESSFUL ⇒ `app-debug.apk`。
> ⚠️ 边界：真固件为 **B 代 API16 + MuJoCo 仿真体**；netpad UDP 通道在 B 代不存在（仅 JVM 真 UDP 单测 +
> 逐字节 wire 移植），真机 BLE GATT / 手感 / 传感器仍 UNVERIFIED。

---

## 0. 这一阶段要解决什么

一句话：**在没有整机的前提下，把 App 的「骨架」——传输抽象 + 常驻会话层——开发并自测到可交付，整机落地后只换 transport 就能跑真机。**

为什么这两个 P0 必须绑在一起做（不是一个接一个）：
- 会话层（自动重连/重认证/重订阅）是**Pollen 原厂** `mobile-app.md` §4 明说的「App 真正的核心复杂度」，但它**只有在能反复断/连的环境里才测得了**——真机现在没有。
- 仿真开发模式提供这个环境（`MockTransport` 可任意注入断连、`TcpTransport` 连 `robotd --sim`）。
- 二者共享同一个前置决策：**`RobotTransport` 接口**。先定接口，会话层只面对接口，仿真后端只是接口的一个实现。

---

## 1. 架构：一个接口，四个后端（P0 的地基）

```
        ┌─────────────────────────────────────────────┐
        │  UI 屏幕（发现/健康/配网/升级/日志/策略）      │
        │  全部只依赖 RobotSession + NDJSON 方法面       │
        └──────────────────┬──────────────────────────┘
                           │  send(method, params) / subscribe(lane)
        ┌──────────────────▼──────────────────────────┐
        │  RobotSession（会话层，P0 核心）              │
        │  hello→auth→ready；断线重连+重认证+重订阅；    │
        │  lane 管理；错误码分类；pending 请求重放      │
        └──────────────────┬──────────────────────────┘
                           │  RobotTransport（唯一抽象）
     ┌─────────────┬───────┴───────┬──────────────────┐
     ▼             ▼               ▼                  ▼
 BleTransport  TcpTransport   WebRtcTransport    MockTransport
 (真机, P0)    (仿真/relay,   (驾驶+视频, P1/P2) (无后端自测, P0)
               P0)
   GATT 515       /run/robotd    mediad:8443       内存 canned
   NDJSON分帧     .sock→relay    control datach.    + 可编程断连
   pin auth       :7788 直连     NDJSON             + 故障注入
```

**接口契约（Kotlin，伪签名）**：
```kotlin
interface RobotTransport {
    val kind: TransportKind          // BLE / TCP / WEBRTC / MOCK
    suspend fun connect(target: ConnectTarget): Result<Unit>
    suspend fun send(line: String): Result<String>     // 一条 NDJSON 请求→一条响应
    fun subscribe(lane: String, onFrame: (String) -> Unit): Disposable
    fun onDisconnected(cb: () -> Unit): Disposable     // 会话层据此重连
    suspend fun close()
}
```
🔑 **所有后端收发的是同一份 NDJSON JSON-RPC 2.0 行协议**（`duck-ipc-proto/src/lib.rs:10` 原文：
"one object per line (NDJSON), over a unix socket"；BLE 分帧后重组也是 NDJSON；mediad control datachannel
源码原文 "a pipe to the robot API"，跑同款 NDJSON）。**这是「换后端不改上层」能成立的根本原因**，
也是官方设计意图（同一套 serde 消息类型复用在 BLE 与 WebRTC 数据通道上）。

---

## 2. 阶段拆解（每个阶段都有可验证的出口）

### 阶段 A — `RobotTransport` 接口 + `MockTransport`（无后端，纯 JVM 自测）

**目标**：先在没有任何硬件/PC 后端的条件下，把接口和会话层的「状态机骨架」跑通。

| 任务 | 出口（可验证） |
|---|---|
| 定义 `RobotTransport` + `TransportKind` + NDJSON 帧模型 | 单元测试：一条 JSON 请求行 ↔ 响应行序列化往返 |
| 实现 `MockTransport`：内存返回 canned `hello`/`system.info`/`robot.health`/`robot.state` | 能应答一份真实结构的健康报告（字段照 `duck-ipc-proto` 的 `HelloResult`/`HealthReport`） |
| **Mock 可编程故障注入**：按脚本发 `disconnect`、延迟响应、返回 error code 14 / -32601、丢帧 | ✅ 负对照：故意注入断连→会话层必须走重连（这是「自检带负对照」准则） |
| NDJSON 行协议工具：分帧/重组（chunk 上限 8 KiB，`\n` 为界） | 单测：分片到达能正确重组；超长帧拒绝 |

**为什么先做 Mock**：会话层的重连逻辑最容易被「看起来连上了」的假象蒙混。Mock 能精确控制断连时机，
让「断线后是否真的重新 hello+auth+重订阅」变成可断言的测试，而不是靠真机偶发掉线碰运气。

### 阶段 B — 会话层 `RobotSession`（P0 核心，用 Mock 驱动开发）

**目标**：把**Pollen 原厂** `mobile-app.md` §4 的会话语义实现完整，且每条都能被 Mock 的故障注入测到。

**必须先落地的 wire 事实（一手核实，别猜）**：

| 事实 | 值 / 位置 | 对会话层的约束 |
|---|---|---|
| 握手顺序 | `hello`（updaterd 应答）→ **`system.authenticate`（v4 起 BLE 必过）** → 就绪 | 会话状态机 = `DISCONNECTED→HELLO→AUTH→READY`；未 AUTH 前不发业务调用（`lib.rs:44`） |
| API 版本 | `API_VERSION=40`；**没有 daemon 因版本不同拒答**（`lib.rs:58`） | 不硬拒旧/新版本；按 `METHOD_NOT_FOUND` 命名的方法做能力降级 |
| 错误码 | `PERMISSION_DENIED=14`（BLE 拒绝）、`METHOD_NOT_FOUND=-32601`、`INVALID_PARAMS`（未知成员） | 14 → 该能力在 BLE 不可用，UI 隐藏/灰化；-32601 → 标该方法不支持，降级；INVALID_PARAMS → 报契约 skew |
| 订阅 | `robot.subscribe` 为 Stream 型，按 **lane** 管理，一连接一 lane | 重连后必须**重放所有活跃订阅**；lane 与连接绑定，断连即失效 |
| 会话身份 | 以 **serial** 为 key（地址会变，serial 不变） | 重连按 serial 找回设备，不按 MAC |
| 掉线触发 | 升级中 btd 重启、等 OAuth 签时 App 后台化（BLE 被系统拆链） | 这两类掉线是**预期**，重连要退避且不能杀流程（Reachy 对照） |

| 任务 | 出口 |
|---|---|
| 状态机 `DISCONNECTED→HELLO→AUTH→READY` + 退避重连 | Mock 注入断连→状态机自动回到 HELLO 并重新到 READY；断言 hello/auth 调用次数 |
| pending 请求在断连期的处理（失败回执 vs 重放，按幂等性分类） | 单测：只读方法重放、写方法不盲目重放（避免重复执行 `robot.do`/`update.apply`） |
| lane 订阅表 + 重连重订阅 | 注入断连→断言所有活跃 lane 被重新订阅 |
| 错误码分类器（14 / -32601 / INVALID_PARAMS / 传输错误） | 每类错误有确定 UI 行为；**负对照**：喂错码必须走错分支 |
| 会话事件流（连接态/重连中/认证失败/就绪）暴露给 UI | 「连接状态徽章」有数据；可显示「重连中…」而非假「已连接」 |

**验收门槛**：阶段 B 结束时，**App 在纯 Mock 下**能完成「发现→hello→auth→健康读数→手动断连→自动恢复→健康读数」全链路，
且每一步有单测；注入故障必红、修好必绿。这一步完全不需要整机，也不需要 PC 后端。

### 阶段 C — `TcpTransport` + `robotd --sim`（真协议栈，PC 上闭环）

> ✅ **进度（Pass129 + Pass132 / 2026-11-12）：C1、C2 均已完成**（原「C2 待环境」作废——
> 复核发现 WSL2 里**早有编译好的真 robotd**：`/root/duck/DuckBuddy-main/target/debug/robotd`，
> 缺口不是环境而是没去查；仿真鸭文档 §9 已记整栈真跑通）。
> **C1（本机纯 Kotlin 闭环）**：`TcpTransport`（真 Socket NDJSON 行收发）+ 本地 `LocalRelayServer`
> （协议语义等价的 JVM 测试对端，非真 robotd）已落地；`CoreSelfTest [8-12]` 真 Socket 验证
> 换后端零改动 / 粘包半包分帧 / 真断链→重连→重握手→重订阅 / 错误码透传 / **握手态连断无风暴回归锁**。
> 期间真 Socket 抓到并修复 Mock 漏掉的真会话层 bug「重连风暴」（state 判重→并发 loop；改用
> in-flight CAS guard + jitter，一手依据 Jitsi/Apollo/K8s 稳定态 + Reachy guard）——详见 README 踩坑 14/15。
> **C2（Pass132 完成）**：`tools/c2_gate.sh` 单次前台 harness（WSL2 内起真 `robotd --sim` →
> 等 `/run/robotd.sock` → `c2_relay.py` **纯字节** AF_UNIX↔TCP 转发 → Windows JDK17 跑
> `C2LiveCheck` → kill）。**11/11 活体断言全绿 / C2_GATE_RC=0**，无 canned 响应。
> - 🔴 **C2 抓出并修复第二个 Mock 漏掉的真 bug**：`system.authenticate` 只由 **BLE transport(btd)** 回答，
>   真 robotd unix 面回 `-32601 "not served by robotd"`；旧会话层无条件发认证 ⇒ TCP 仿真模式握手必失败。
>   修法 `AuthPolicy.AUTO` 按 `transport.kind` 决定，状态机改 `HELLO→[AUTH 仅 BLE]→READY`；
>   回归锁 `[16]` 7 条。一手依据 fanhao `lib.rs:44` / `btd/pairing.rs:24` / `btd/route.rs:987` /
>   `updater/ipc.rs:879` / `mediad/session.rs:21`，以及 `c2_probe.py` 真固件探针实测。
> - ⚠️ **证据边界（不可外推）**：WSL2 那份是 **B 代 DuckBuddy-main，API_VERSION=16 / daemon 0.10.0**，
>   **不是 fanhao API40**。C2 验的是跨版本共通的传输/会话语义（NDJSON 分帧、版本差异不硬拒、错误码、
>   只读调用、订阅端点、认证归属），**不证明** fanhao 特有方法面 / 真机 BLE GATT 时序。
>   未起 body_server ⇒ 当时登记 `INCONCLUSIVE_LIVE_STATE_STREAM`（真 `robot.state` 通知流 /
>   重连后重订阅推送未验）——**已由下方 C2+ 在「仿真固件状态流」这一层消掉**，真机仍 UNVERIFIED。
> - ✅ 产品代码侧：`RobotSession` 改了认证策略（真 bug 必须修），`TcpTransport` / `BleTransport` /
>   四后端接口**零改动**；`bash tools/selftest.sh` 103→**110/110**；Gradle 全模块 `BUILD SUCCESSFUL in 30s`。
>
> ✅ **C2+（Pass133 / 2026-11-12 完成）**：把上一条的 `INCONCLUSIVE_LIVE_STATE_STREAM` 消掉。
> Windows 侧起真 `body_server`（`microduck-software/.venv-mjlab` 现成环境，torch 2.9.1 / mujoco 3.7.0），
> WSL 侧 `robotd --sim <网关>:7801`，50 Hz 控制循环真跑（`ticks>0 / achieved_hz≈50 / healthy=true`）。
> `C2PlusLiveCheck` **24/24 活体断言全绿、连跑 3 次无偶发**，覆盖：真 `robot.state` 帧结构
> （t/loop/move/joints=15/policy/odom）、`t` 单调递增、`loop.hz≈50`、订阅前零帧、
> 错误 `streamMethod` 零帧、重复订阅替换速率不叠加、**断链→重连→自动重订阅→通知流恢复**。
> 断链由**独立控制端口**注入（只关 socket、零字节/零 canned；一手依据 Shopify Toxiproxy 独立控制面
> 与 `reset_peer`/`limit_data` toxic），数据面仍是纯字节转发；`FAULT_INJECT_DROP pairs=2` 实测留痕。
> 关键负对照：同栈另开**不订阅**的对照会话 sB，断链重连后仍零帧 ⇒ sA 的恢复只能来自会话层重发
> `robot.subscribe`（真固件订阅是 per-connection，`main.rs:3366-3371` 局部变量）。
> 🔴 边界：这是 **B 代 API16 真固件 + MuJoCo 仿真体**的状态流，**不是真机状态流**，也不证 fanhao API40。
> 原 C2 门禁复跑仍 **11/11**（C2+ 用独立 `c2_relay_plus.py`，未改动已验证的 C2 证据链）。

**目标**：把 Mock 换成真协议——连 PC 上跑的仿真鸭，验证 NDJSON/方法面/订阅在**真实固件代码**上成立。

**前置（已一手核实可做）**：
- `robotd --sim <addr>`：同一个 daemon、同一 IPC/策略/安全层，只把 body 换成 MuJoCo `RemoteIo`（**TCP**，
  `duck-control/src/sim.rs` 原文解释选 TCP 而非 unix socket：SUN_LEN ~108 字节限制 + 需跨容器/VM 可达）。
  上层「无法分辨真假」——**这就是 App 开发的主后端**。
- 但注意：Android 连的是 `robotd` **对外服务 socket**（unix），不是 `--sim` 的 MuJoCo body TCP。
  所以仍需一个 **unix→TCP relay**：PC 上 `ssh -L 7788:/run/robotd.sock` 或一个几十行转发器即可
  （OpenCastor 实证 off-board 推荐 `ssh -L`）。`TcpTransport` 连这个 :7788。

| 任务 | 出口 |
|---|---|
| `TcpTransport`（`Socket` 连 :7788，NDJSON 行收发） | 连上 relay，能发 `hello` 拿到真 `HelloResult`。⚠️ **C2 实测修正**：本机 WSL2 真固件是 B 代 `api_version=16`（`daemon_version=0.10.0`, `revision=null`, **无 serial**），App 发 40 不被拒答而是被服务；fanhao API40 需整机核 |
| bus 侧 relay 脚本（PC 端，非 App 代码）：`socat`/`ssh -L`/Python 转发 unix→TCP | 一条命令起 relay；文档化 |
| 用真 `robot.health`/`robot.state` 数据喂健康屏 | 健康屏显示真字段（15 舵机电压/温度/负载、IMU、电池） |
| 订阅 `robot.state` lane，断 relay 再起→验证重连重订阅 | ✅ **C2+ 已完成**：真固件 + body_server 上 24/24 活体断言（真帧结构/50Hz/过滤/替换速率/断链重订阅恢复），见上方 C2+ 段 |
| 能力协商：`hello` 后按方法探测 40 版支持面 | 不支持的方法 UI 灰化，不崩溃 |

🔑 **sim fidelity 边界（必须写进测试约定）**：microduck-mcp 独立实测指出参考 MuJoCo 场景
**小速度命令 under-track、弱 yaw**，与我们 E3 的 undershoot ~45% 独立吻合 ⇒
**仿真后端只测协议/会话/UI 数据流，不标定驾驶手感**；真实手感等整机。

### 阶段 D — `BleTransport`（真机候选，可在有 BLE 硬件时用）

> ✅ **进度（Pass132 补记 / 2026-11-12）：协议层已完成，真机 I/O 未上板**。
> `BleChunkCodec`（一比一移植 `duck-ble/src/framing.rs`，12 组原测逐条移植，含 517→512 静默丢字节回归）、
> `GattLink`（把唯一 Android 依赖隔离成接口）、`BleTransport`（纯 JVM 协议编排：出站固定 20B chunk、
> 入站 `forReplies` 重组）、`FakeGattLink`（JVM 协议等价对端）、`AndroidBleGattLink`（GATT 骨架：
> WithResponse / CCCD 0x2902 / 单操作串行 latch / API33+ 兼容）。`CoreSelfTest [14][15]` 真测、
> Gradle 全模块真编译；`bash tools/selftest.sh` 累计 103/103。
> ⚠️ **`AndroidBleGattLink` 的 bonding/CCCD/onCharacteristicWrite 时序仅编译验证，无 Android 真机/整机**，
> 真机 GATT 联调待整机落地。
> 🔑 **C2 补充（Pass132）**：下表中 `hello → system.authenticate` 是 **BLE 专属**；会话层已按
> `AuthPolicy.AUTO` 只对 BLE 发认证，TCP/WebRTC 不发（真 robotd 会回 -32601）。

**目标**：把 transport 换成 BLE，验证 GATT 契约。**不需要整机鸭子，任意 Android 手机 + 一个 BLE 外设模拟器
（或 PC 上跑 btd 的 mock GATT）即可先开发**；整机到手只做联调。

| 任务 | 出口（照 `duck-ble` 契约） |
|---|---|
| BLE 扫描：过滤 `duck-` 前缀；读 manufacturer data 的 IPv4；name 在 scan response | 扫描列表显示 name+IP+serial，按 serial 去重 |
| GATT 连接 + 协商 MTU 515 | 协商成功；通知按 512 B chunk 重组 |
| 服务 `6f5d2a10…` / RPC 特征 `6f5d2a11…`（**读写+通知合一**） | 能 read 特征触发版本读取（促成配对） |
| `hello` → `system.authenticate`(PIN 6 位, 默认 `000000`, 3 次失败断连) | 认证成功进入 READY；失败计数与断连正确 |
| NDJSON 分帧重组（8 KiB 上限）+ 会话层复用 | **阶段 B 的会话层零改动**直接跑在 BLE 上——这是架构验收的决定性证据 |
| 加密（可选，交付前） | 官方默认明文；内部可照抄，交付加应用层加密（Reachy 的 x25519-hkdf-aesgcm 现成） |

---

## 3. 阶段顺序与依赖

```
阶段 A (接口+Mock) ──► 阶段 B (会话层, Mock 驱动) ──► 阶段 C (Tcp+sim, 真协议)
                                                          │
                                                          └──► 阶段 D (Ble, 换 transport)
                                                                  │
                                                       整机到手 → 联调 → P1 驾驶
```
- **A→B→C 是 P0，全部可在无整机、纯 PC/手机完成**。
- D 可提前（有 BLE 硬件即可），但**必须在 B 稳定后**——用它验证「会话层零改动换后端」。
- P1 驾驶（摇杆 + netpad/WebRTC）在 P0 之后启动，复用同一 `RobotSession` 与 NDJSON 方法面。

---

## 4. 贯穿全程的工程约定（来自项目准则，防止返工）

1. **先查源码再写码**：每个方法名/字段/错误码都对 `duck-ipc-proto/src/lib.rs` 核过；查不到明标「这是推的」。
2. **验证带负对照**：会话层每条断言都要有「故意改坏必红」的版本（Mock 故障注入天然支持）。
3. **问「量动没动/量级对不对」**，不问「结果对不对」：例如断连后 hello 调用次数是否真的 +1、lane 是否真的重新订阅。
4. **坐标系/单位/轴量双算法互算**：驾驶手感标定（P1）必须整机测，仿真不作数（§2 阶段 C 注）。
5. **不覆盖手改 / 不重跑生成器**：本阶段若生成配置文件，照项目既有约定处理（参照采购表手改教训）。
6. **交付物可验证**：每个阶段有明确「出口」，不是「写完就算」；CI 上跑 Mock 驱动的会话层单测。
7. **argparse/help 不写 `%`、训练/编码约定**与 App 无关，但 CMake/Gradle 脚本同样注意转义。

---

## 5. 待用户拍板 / 未决项（不阻塞 A/B，C 前需定）

| # | 事项 | 影响 | 建议 |
|---|---|---|---|
| Q1 | 仿真后端选 `robotd --sim`+relay，还是直接对接 microduck-mcp 的 `sim`/`mock`（省去自己起 MuJoCo） | 阶段 C 工作量 | 先用Mock，C 用 `robotd --sim`+`ssh -L`（最贴真机固件）；microduck-mcp 的 sim 作快速备选 |
| Q2 | 手机↔PC relay 形态：`ssh -L`（要 SSH 凭据）vs 独立 TCP relay App/脚本 | 阶段 C/D 联调便利 | 台架期用独立 relay 脚本（免 SSH 配置），交付再评估 |
| Q3 | BLE 交付是否要应用层加密 | 阶段 D + 交付 | 内部/个人使用可照抄官方明文；对外交付加 Reachy 那套 AES-GCM |
| Q4 | 是否做「离线仿真鸭演示」彩蛋（手机端跑 MuJoCo，照 TonyRuan） | P3 范围 | 建议 P3，不进 P0 |
| Q5 | 无 stand 策略时「站立」按钮语义（`robot.init` 进 HOME？） | UI 设计 | 阶段 B 会话层不依赖此；P1 驾驶屏前定 |

---

## 6. 参考（一手 + 外部，详见调研报告 §9）

- **一手**：fanhao 固件 `duck-ipc-proto/src/lib.rs`（API_VERSION=40 / 错误码 / 方法名 / v4 认证）、
  `duck-ble/src/{gatt,framing,adv}.rs`（GATT/分帧/广告）、`btd/src/bluez.rs`（BLE↔unix 桥）、
  `robotd/src/main.rs`（UnixListener/NDJSON）、`duck-control/src/sim.rs`（sim=TCP RemoteIo）、
  `mediad/src/{main,pipeline}.rs`（control datachannel = robot API pipe）、`docs/design/mobile-app.md`（会话层要求）。
- **外部**：`craigm26/OpenCastor`（四传输同 JSON-RPC、ssh -L）、`joeynyc/microduck-mcp`（`DuckTransport`=mock/sim/unix/ssh 单接口）、
  Reachy Mini（Pollen 另一产品）的 sim 文档（`--sim` 同 API、SDK 不改）、Hey Reachy（无机器人 simulator 开发模式）、
  `pollen-robotics/reachy_mini_mobile_app`（会话/配网 FSM）、`TonyRuan/microduck-android`（驾驶屏 UX）。

---

## 7. 后续阶段实绩：多页 / 横屏 / 双模式 UI（2026-11-12 晚 ~ 11-13）

> 本节是 P0 计划之外已落地的推进记录；**不改动 P0 的阶段 A–D 划分与验收判据**。
> 完整一手依据、开源方案对照表与「采纳/不采纳」结论见
> `docs/active/microduck-安卓App-开源遥控App设计对照-2026-11-12.md`。

### 7.1 信息架构（用户明确要求「一页放不下就拆页」）

弃用单页堆叠，改为**两个 Activity**：

- `MainActivity`（竖屏控制台，`screenOrientation="portrait"`）：连接 / 模式选择 / 进入遥控 +
  M3 Navigation bar 三页「状态 / 健康 / 设置」。**不持有任何 Controller，不发驾驶帧**。
- `DriveActivity`（`sensorLandscape`，横屏全屏）：取景框铺底、双摇杆叠加左右下角、顶部 2×3 只读 HUD。
  **退出本页 `onStop()` 立即归零 + 停心跳**；`DriveController` / `HeadController` 只由本页持有。
- 跨页共享经 `SessionHolder` 单例（会话、状态订阅、模式、本地遥测）；`SettingsStore` 用
  `SharedPreferences` 持久化 8 项参数，**mode / host 刻意不持久化**，冷启动强制回 MANUAL 保住手动接管入口。

依据：M3 Navigation bar（3–5 个顶层目的地）、Weston Robot Teleop（dashboard 与 driving view 布局分离）、
arXiv:2110.08753（横屏双拇指舒适区实测 ⇒ 全屏取景 + 双摇杆贴两下角）、Android `<activity>` 官方文档
（`screenOrientation` 为逐 Activity 属性）、Android 官方 immersive 文档（不 hide systemBars，
改 edge-to-edge + scrim + insets，避免与底部 home 手势冲突）。

⚠️ **边界**：Android 16 在 target API36 且 `sw>=600dp` 时会忽略 `screenOrientation`；
本项目 targetSdk35 + 手机 `sw<600dp` 暂不受影响，未来升 36 / 上大屏必须改响应式布局。
Manifest 已用 `<uses-feature ... required="false">` 关闭 per-Activity orientation 引起的 Play 设备过滤。

### 7.2 自动 / 手动模式语义（按 NIST UTAP / Sheridan LOA 定，不自己造）

| 模式 | 定义 | App 行为 |
|---|---|---|
| MANUAL | 全部运动由人的连续输入指定 | 双摇杆发 `robot.move` / `robot.head` notification，100 ms 心跳 |
| AUTO | 监督式：人监测、运动由计算机产生 | **零驾驶帧**、不创建任何 Controller、只监测 `robot.state`，提供「切回手动」 |

🔴 AUTO **不等于已启动自主行走**：契约虽有 `robot.do` / `robot.loadPolicy`，但无整机、未验证策略启停，
界面已明写「App 无停车能力」「切回手动只是模式切换、不是 e-stop」。

### 7.3 数据来源边界（防伪造）

- 「实机状态帧」8 项只取 `robot.state`；「App 本地遥测」6 项只取 App 自观测，标题明写非实机数据。
- HUD 新增「命令→实际」「头部 °」两格也**只读 `robot.state`**，Mock 不推流时一律「— 未读到」，
  不用本地意图或计数器补值。
- 取景框是 `PreviewPlaceholderView` 明确标注的占位（一手：fanhao `media.frame` 是 mediad 本地
  Unix socket 上的 JSON header + binary tail，不进 Service/Lane routing；`mobile-app.md` 把 video
  归 WebRTC drive 通道，属 P2 未实现）。**绝不画假帧**。
- 驾驶页加 LIVE/DEMO 来源标签；Mock health fixture 明写「非实机读数」。

### 7.4 验证结果

- `bash tools/selftest.sh`：**230 passed / 0 failed**（`SELFTEST_RC=0`）。
- `:app:assembleDebug`：`BUILD SUCCESSFUL`，`GRADLE_RC=0`（`set -o pipefail` 使 rc 不被 `tee` 吞掉），
  `compileDebugKotlin` 真执行。
- 真机 vivo V2338A / Android 16 (API 36)：`adb install -r` Success（首次 vivo 安装校验器
  `INSTALL_FAILED_ABORTED` 按既有经验重试即成功）；`tools/device_ui_check.py` 覆盖主页竖屏、
  遥控页 `rotation=1`、双摇杆分离、心跳增长 / 松手 `+0` / `ACTION_CANCEL` 同归零、退出停车、
  自动页零驾驶帧且无摇杆、设置跨冷启动持久化、冷启动强制回手动、全生命周期零 FATAL。
- 🔴 首轮 54/56 的两条失败是**验证工具自身**的假读数（陈腐 XML / 双 Handler 并发踩共享快照 /
  环境批量删除保护中断 / 通知栏被当成 App 窗口），已按「读数矛盾先怀疑读数」写诊断脚本实测后
  逐个修，详见对照文档 §6。
- ✅ **最终稳定性**：修复后**连跑 3 次全部 59/59、RC=0**（脚本共定义 59 条断言：47 条直接 check
  + 12 条 `tap()`「可定位」check，含 348/354 互斥对只计其一）；负对照用
  `cmd statusbar expand-notifications` 主动展开通知栏，门禁打印「本包节点 0 个，按 BACK
  关闭后重取」后仍 59/59 ⇒ 窗口归属判据确实生效，不是「下一轮碰巧绿」。
  收口轮另修掉最后一类门禁假读数：**uiautomator 只 dump 视口内节点**（一手依据 GitHub
  `navigate-app-adb`），状态页遥测区 / 设置页 BLE 面板被推到折叠线以下读不到 ⇒ 状态页 2 列 8 行
  改 **4 列 4 行**单屏可见、设置页小步幅滚到面板最低按钮再断言；并补齐 **A1 BLE 连接面板进设置页**
  断言。最近一次真机实测 2026-11-13。

### 7.5 不变式

`UNVERIFIED != PASS`、`COLLECTED != PASS`、`ship_verdict=NOT_SHIPPABLE`、
`live_hardware_accessed=false`。本轮只在 **Mock 会话 + Android 真机 UI** 范围验证；
整机未落地，真机 GATT / 真视频 / 真策略启停 / 手感标定 / `maxVx`/`maxVyaw` 全部仍 UNVERIFIED。
`maxVx/maxVyaw` 仍为占位，按本文档 §216 必须整机标定，仿真不作数。
