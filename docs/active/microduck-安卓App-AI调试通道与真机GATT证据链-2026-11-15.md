# 安卓 App：AI 可控调试通道 + 真机 BLE GATT 证据链（2026-11-15）

_回应「可以把 app 做成能让 ai 控制，这样可以方便调试」+「继续完善 app 吧，手机我拔了，按计划一直做下去」。_
_本文是这一线的**单一权威**。状态口径：`UNVERIFIED != PASS`、`COLLECTED != PASS`、
`ship_verdict` 由证据派生不手翻；`BA-X-5` 仍 `UNVERIFIED_NOT_PASS`。_
_🔴 手机已拔 ⇒ 本轮所有新增代码的 **Android 真机端到端验证全部 UNVERIFIED**，不假称验过。_

---

## 0. 结论先行

离线把「AI 用 adb 读 App 状态 / 扫设备 / 发起连接 / 读失败原因」这条通道做完了，
并把 2026-11-14 真机取证的四份原始日志固化进仓库、接上自动派生判定链。
**真编译 + 全量离线门禁全绿**；但通道在真机上能不能收到广播、修复后的 App 能不能握手成功，
**没有测过**（手机拔了），必须等下次插线复跑。

| 项 | 结果 |
|---|---|
| `:app:assembleDebug` + `:app:assembleRelease` | `BUILD SUCCESSFUL in 1m 8s`（`GRADLE_RC=0`） |
| core 自检 | `383 passed, 0 failed` |
| App 侧统一门禁 | `ALL_PASS`（4 个 Python 自检 + core JVM + 产物隔离） |
| 软件侧全量门禁 | `ALL_PASS 51/51`，`ship_verdict=NOT_SHIPPABLE` |
| 注入式负对照 | 静态 2 errors / 动态 `380 passed, 3 failed` / 恢复后全绿 |
| `BA-X-5`（自动派生） | `UNVERIFIED_NOT_PASS`（4/4 充分条件未满足） |
| 真机 AI 通道端到端 | 🔴 **UNVERIFIED**（手机已拔） |

---

## 1. 触发问题（2026-11-14 真机实测，非推断）

`drive_app_ble_live.py` 驱动真机 App：扫描到 `duck-6a07`（`CC:C8:37:E3:7C:90`，
判别=服务 UUID）、点击连接 → UI 进 `FAILED`，文案是
「BLE 连接失败（真 GATT 尚未上板验证）」。`diag_app_gatt_logcat.py` 清空 logcat 重放后
`total_kept = 0`。回源码追出三条真缺口：

1. `RobotSession.connect()` 吞掉真实异常，只返回 `false`；
2. `SessionHolder` 用一句通用文案盖掉失败原因（App 源码里没有任何 `Log.*`）；
3. `AndroidBleGattLink` 把 `onMtuChanged` 回调当成 `connect()` 的**硬前置** ——
   MTU 协商只是可选优化，不该阻塞「服务发现完成即就绪」。

另有 PC 侧 bleak 只读探针实读：板上 `RPC_UUID` 的 `read` 返回 `0x25`（=37），
而 App `Wire.API_VERSION = 40`。查 fanhao 分支一手源码
`duck-ipc-proto/src/lib.rs` 确认 `PROTOCOL_MISMATCH` 已退役、版本差异「logged and served」，
所以**不该硬拒**，但必须在 App 里可观测 —— 旧代码把 `readApiVersion()` 的返回值直接丢了。

> 术语口径：唯一「官方/原厂」= `pollen-robotics/microduck`；fanhao 分支、Google Android
> 平台文档、AOSP、BlueZ 一律写「机构名 + 平台文档 / 源码」，不称官方。

---

## 2. 代码改动（本轮 tracked 7 个 + 新增 10 个）

**App 可观测性修复**
- `core/BleTransport.kt`：新增 `@Volatile var peerApiVersion: Int?`，connect 前清空、
  `readApiVersion()` 成功后赋值；只记录不硬拒版本差异。
- `core/RobotSession.kt`：新增 `Event.ConnectFailed(stage, reason)` 与 `lastConnectError`；
  link / handshake / auth / PIN 四处失败都带真实异常。
- `app/SessionHolder.kt`：失败 note 改带 `s.lastConnectError`，事件订阅加失败横幅；
  新增 `peerApiVersion` / `connectError` / `modelApiText` 供 AI 通道只读。
- `app/ble/AndroidBleGattLink.kt`：`onMtuChanged()` 只更新 `negotiatedMtu`；
  `awaitConnectReady()` 改判 `rpcChar != null`；操作超时 3s→12s；删 `mtuDone` 死代码。
- `core/.../FakeGattLink.kt`：`setPeerApiVersion(v)` 供注入板端 37。
- `core/.../CoreSelfTest.kt`：新增 13 条版本/失败原因断言 + 24 条策略真跑断言。
- `tools/selftest.sh`：禁止回退 IDEA Kotlin 1.9.0，改用 Gradle 缓存里的 2.4.0
  embeddable compiler；`main` 补 `@JvmStatic`（否则 `java -cp` 根本起不来，历史假绿）。

**AI 调试通道（新增）**
- `core/AiDebugPolicy.kt`：唯一策略真源（TAG / 组件名 / 命令白名单 / RPC 只读白名单 /
  禁止集合 / 有界超时常量），三条消费链共用。
- `app/src/debug/AndroidManifest.xml` + `app/src/debug/.../AiDebugReceiver.kt`：
  release 包不含该组件。
- `tools/ai_debug_bridge.py`：PC 侧唯一配套发送方，从 `AiDebugPolicy.kt` 正则提取常量。
- `tools/check_ai_debug_channel.py`：跨文件结构化静态核对 + 11/11 注入式负对照。

**证据与门禁（新增）**
- `tools/evidence/2026-11-14-ble-gatt/*.json`：四份一手原始日志（sha256 见契约）。
- `tools/ble_gatt_evidence_contract.json` + `tools/check_ble_gatt_evidence.py`：
  机读契约、自动派生 `BA-X-5`、12/12 负对照。
- `tools/check_apk_debug_isolation.py`：产物级隔离核验（AXML 字符串池 + dex 字节），12/12 负对照。
- `tools/check_all_app_gates.py`：统一门禁入口，10/10 真实子进程夹具负对照。

---

## 3. AI 调试通道设计

### 3.1 为什么是「显式广播 + debug-only」

| 一手依据 | 结论 |
|---|---|
| Google Android 平台文档《后台执行限制》：「Apps can continue to register for **explicit broadcasts** in their manifests.」 | `adb shell am broadcast -n <pkg>/.Receiver` 是显式广播，targetSdk 35 / Android 8+ 仍能送达 manifest receiver |
| AOSP `ActivityManagerService.broadcastIntentLocked` 默认加 `FLAG_EXCLUDE_STOPPED_PACKAGES` | PC helper 固定带 `-f 32`；否则首次安装未启动 / force-stop 后的 App 零应答。🔴 零应答时先查这个最前置前提，别先猜 GATT/权限 |
| Google Android《Broadcasts overview》 | `android:exported=false` 收不到 App 之外的广播；adb shell 是外部发送方 ⇒ 必须 `true`（代价由白名单兜住） |
| Google Android `BroadcastReceiver.goAsync()` 参考 | goAsync 后仍受约 10 s 广播超时约束，必须 `PendingResult.finish()` ⇒ 所有等待设硬上限，超时回 `ASYNC_PENDING` 让调用方轮询 `status` |
| AGP sourceSet 合并规则 | 组件放 `app/src/debug/`，release 变体**看不到这份 manifest**；不能靠 `BuildConfig.DEBUG` 运行时 if 替代（那样组件仍在 release 清单里） |

**刻意不写 `<intent-filter>`**：只接受显式 component 广播，不注册任何隐式 action。
**不建 socket / 不监听端口 / 不新增权限 / 不起前台服务**（API31+ 后台起 FGS 会抛
`ForegroundServiceStartNotAllowedException`，Receiver 没有可见 Activity）。

### 3.2 命令表（白名单外一律回结构化错误，不是静默忽略）

| cmd | 作用 | 边界 |
|---|---|---|
| `help` | 回命令表 / 白名单 / 组件名 / TAG | 只读 |
| `status` | 会话状态、失败原因、`peer_api_version`、状态帧计数、心跳、UI tick | 只读 |
| `scan` | 3 s BLE 扫描，回设备列表 | 需运行时权限；只读 |
| `connect` | 按 MAC 走 `AndroidBleGattLink → BleTransport → SessionHolder.connectWith` | 先回 `phase=accepted`，再回 `phase=result`（带 `last_connect_error`），8 s 超时回 `phase=timeout` |
| `mock` | 连 Mock 后端（离线自检通道是否活着） | 3 s 有界 |
| `rpc` | 发**只读** JSON-RPC 方法 | `AiDebugPolicy.READ_ONLY_METHODS` 白名单；`robot.move` / `robot.do` / `robot.enable` / `net.connect` / `system.authenticate` / `net.scan` / `update.check` 等禁止 |
| `disconnect` | 断开并清空版本残留 | 只动 App 会话 |

### 3.3 结果契约

固定 Logcat TAG `MicroDuckAiDebug`，**单行 JSON**，字段
`v`(schema=1) / `rid` / `cmd` / `ok` / `ts_ms` / `build=debug` /
`evidence=COLLECTED_ONLY_NOT_PASS` / 可选 `phase` `reason` `next`。
`rid` 由调用方生成并回填，PC 桥靠它把结果和指令对上，拒收别的 rid 与畸形行。
超过 3200 字符截断并回 `RESULT_TOO_LARGE`（Android Logcat 单条约 4 KiB）。

> 🔴 通道**不产生验收结论**：所有返回值都是 `COLLECTED_ONLY_NOT_PASS` 级观测，
> 真机 GATT 握手成功与否仍由 `BA-X-5` / `board_acceptance` 证据链判定。

### 3.4 怎么用（下次插上手机照抄）

```bash
cd microduck-android-app
# 0) 先机械核对最前置前提：设备在线 / debug 包 / 广播能送达
python tools/ai_debug_bridge.py --precheck

# 1) 装 debug 包（固定签名；旧 debug 签名包须先卸载）
adb install -r -g app/build/outputs/apk/debug/app-debug.apk

# 2) 读状态（一步出 JSON）
python tools/ai_debug_bridge.py --cmd status

# 3) 扫设备 / 连真板 / 看失败原因
python tools/ai_debug_bridge.py --cmd scan
python tools/ai_debug_bridge.py --cmd connect --arg CC:C8:37:E3:7C:90
python tools/ai_debug_bridge.py --cmd status       # 读 last_connect_error / peer_api_version

# 4) 只读 RPC（白名单内）
python tools/ai_debug_bridge.py --cmd rpc --method system.info

# 5) 离线自检通道是否活着（不连板）
python tools/ai_debug_bridge.py --cmd mock
```

等价的手工广播（调试用）：
`adb shell am broadcast -f 32 -n io.microduck.app/.AiDebugReceiver --es rid <12hex> --es cmd status`
读结果：`adb logcat -s MicroDuckAiDebug`。

---

## 4. 产物级隔离实证（源码绿 ≠ 产物绿）

`:app:assembleDebug` + `:app:assembleRelease` 真跑后，两条独立观测面：

| 观测面 | debug | release |
|---|---|---|
| `aapt dump xmltree … AndroidManifest.xml` receiver 数 | **2**（含 `io.microduck.app.AiDebugReceiver`，`enabled/exported=true`） | **1**（只有 `androidx.profileinstaller.ProfileInstallReceiver`） |
| binary AXML 字符串池差集 | `['io.microduck.app.AiDebugReceiver']` | — |
| classes*.dex 中 `AiDebugReceiver` ASCII 引用 | **42** | **0** |
| classes*.dex 中 `MicroDuckAiDebug` TAG 引用 | **2** | **0** |

`check_apk_debug_isolation.py` 用结构化 AXML ResStringPool 解析（非裸子串）+ dex 字节计数
自动派生 `DEBUG_ONLY_ISOLATION_CONFIRMED`；产物缺失如实回 `UNVERIFIED_ARTIFACTS_ABSENT`，不当 PASS。

> 🔴 顺手修掉一个**读数错**：临时核验脚本曾把同一个 dict key 加两遍、漏算 UTF-16LE 项，
> 打印 `xml_AiDebugReceiver=0`，与 aapt 明明列出的 receiver 直接矛盾。
> 按项目铁律「读数与算术矛盾 ⇒ 错的是读数」，改为解析字符串池拿**集合**再判包含；
> 正式工具对合成 AXML 同时覆盖 UTF-8 / UTF-16 两种池并有 `_BROKEN` 负对照。

---

## 5. 真机 GATT 证据链（四份原始日志 + 自动派生）

原始日志固化在 `microduck-android-app/tools/evidence/2026-11-14-ble-gatt/`，
契约在 `tools/ble_gatt_evidence_contract.json`（含每份 sha256，`--rebuild` 可重算）：

| 原始日志 | 内容 | verdict |
|---|---|---|
| `gatt_discovery_readonly.json` | 只读服务发现：`SERVICE_UUID` / `RPC_UUID` 命中，properties=`notify/write-without-response/write/read`，CCCD 在；负对照 `00:00:00:00:00:00` → `BleakDeviceNotFoundError` | `GATT_CONTRACT_ALIGNED` |
| `api_version_read_first_attempt_failed.json` | 首次单次 read 连上后断开 | `READ_FAILED` / `BleakError: disconnected`（如实保留失败，不掩盖） |
| `android_app_connect_live.json` | 真机 App 点连接：`handshake_ready_claimed=false`、`handshake_failed_claimed=true` | `APP_GATT_HANDSHAKE_NOT_READY`，`ba_x_5 = UNVERIFIED (partial evidence only; NOT PASS)` |
| `app_gatt_logcat_diag.json` | 清空 logcat 重放 | `total_kept = 0`（坐实 App 无 `Log.*`） |

**`API_VERSION=37` 的诚实分级**：随后连续 3 次稳定返回单字节 `0x25(37)` 那几次
**stdout 未落盘**，只有会话转录。契约里单列为
`SESSION_STDOUT_TRANSCRIPT` / `TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS`，
数值用 `int('25',16)` 与 `int.from_bytes(bytes.fromhex('25'),'little')` 两条独立算法互算自洽，
但**永远不能作为 PASS 级判据**。下次上板用探针的 `--json-out` 补一手日志。

**自动派生链**：`BA-X-5` 的充分条件不另写清单，直接从
`microduck-software/tools/hd1910/board_acceptance_contract.json` 的 `evidence_kind` 派生 4 条；
当前 4/4 都 `UNVERIFIED` 且无落盘一手证据 ⇒ 自动判 `UNVERIFIED_NOT_PASS`。
契约里**禁止手写 `verdict` / `ba_x_5_verdict`**，检查器见到即红；即使证据齐全也只到
`EVIDENCE_COMPLETE_NOT_SIGNOFF`，签收权在 `board_acceptance + signoff`。
本链完全不碰 `closure_contract.json`，避免按集合相等判红的连锁反应。

---

## 6. 本轮真跑结果

```
./gradlew :core:compileKotlin :core:compileTestKotlin :app:assembleDebug :app:assembleRelease --offline
  BUILD SUCCESSFUL in 1m 8s   GRADLE_RC=0
bash tools/selftest.sh                         RESULT: 383 passed, 0 failed
python tools/check_all_app_gates.py --selftest VERDICT = ALL_PASS
  ai_debug_bridge              19/19    check_ai_debug_channel      11/11
  check_apk_debug_isolation    12/12    check_ble_gatt_evidence     12/12
  core JVM selftest            383/0    runner 子进程夹具            10/10
  apk-debug-isolation          DEBUG_ONLY_ISOLATION_CONFIRMED
run_all_gates.py --check（软件侧）          ALL_PASS 51/51  ship_verdict=NOT_SHIPPABLE
```

**注入式负对照（故意改坏必红）**：把 `Method.ROBOT_MOVE` 塞进只读白名单后 →
静态检查器 `RESULT: 2 errors`、core 动态自检 `380 passed, 3 failed`、rc=1；
恢复后静态 `0 errors` / 动态 `383 passed, 0 failed`。
另有 `peerApiVersion` 丢弃 → `357 passed, 2 failed` → 恢复 `359/0`（上一轮），
本轮在此基础上再加策略断言。

---

## 7. 明确未验证（🔴 手机已拔，全部 `UNVERIFIED`）

1. `adb am broadcast` 能否送达这个 manifest receiver（显式广播 + `-f 32` 在真机上是否生效）；
2. Logcat TAG 结构化 JSON 的端到端读取、`rid` 配对、`phase=accepted→result` 时序；
3. **修复后的 App** 能否在真板 `duck-6a07` 上握手成功（MTU 前置移除 + 12s 超时是否够）；
4. `status` 里 `peer_api_version=37` 是否真能从 App 侧读到；
5. `BA-X-5` 全部 4 项：真机 bonding / CCCD / `onCharacteristicWrite` 时序、
   50Hz `robot.state` 帧计数 + 不订阅零帧负对照、断链重连重订阅、
   板上 netpad `:4210` UDP 驾驶方向与 250ms timeout。

`live_hardware_accessed=false`、15 个舵机 ID 全缺、`imu not ready`、`robotd read-only`
等状态**一个都没翻**：登录过 SBC ≠ 整机落地，读-only GATT 服务发现 ≠ 整机联调。

---

## 8. 下次上板 SOP（按顺序，别跳步）

1. 机械核前提：`adb devices` 有设备、板子在广播、装的是 **debug** 包
   （`aapt dump badging | grep package` 看版本；release 包**故意收不到**广播）。
2. `python tools/ai_debug_bridge.py --precheck` —— 前提不成立会直接报
   `PRECONDITION_FAIL` 且**零 HTTP / 零连接**，不要把 timeout 当服务挂了。
3. `--cmd status` 拿基线 → `--cmd scan` 确认 `duck-6a07` → `--cmd connect --arg <MAC>`。
4. 失败就读 `status` 的 `last_connect_error`；这次有真实异常了，不用再靠 UI 猜。
5. 若要补 `API_VERSION` 一手日志：PC 侧只读探针带 `--json-out` 落盘，
   回填契约后 `python tools/check_ble_gatt_evidence.py --rebuild`。
6. 全部通过后跑 `python tools/check_all_app_gates.py`；
   `BA-X-5` 的 PASS 仍须走 `board_acceptance` 的 `signoff`，本链不代签。

---

## 9. 复跑命令一行版

```bash
cd microduck-android-app && python tools/check_all_app_gates.py --selftest
```

> 统一门禁 `ALL_PASS` 只代表**离线**门禁：不验证真机、不改 `ship_verdict`、
> 不消 `INCONCLUSIVE_LIVE_STATE_STREAM`。
