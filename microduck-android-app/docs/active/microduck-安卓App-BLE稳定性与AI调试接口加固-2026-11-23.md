# MicroDuck Android App —— BLE/Wi-Fi 稳定性与 AI 调试接口加固（2026-11-23）

> 范围：延续「先完善 App，真机测试后面再说」。本轮只做**离线可证实**的加固，不碰真机。
> 提交后状态：`ship_verdict = NOT_SHIPPABLE` 不变；真机 Noise 握手 / PIN 门 / 配网 IP 回填 / 整机活体仍 `UNVERIFIED`。

## 一手依据（先查证，不自己拍）

1. **BLE 扫描限流真实存在**：AOSP 17 `AppScanStats.isScanningTooFrequently()` 保留最近 5 次已结束扫描，
   最早一次仍在 30s 窗口内则拒绝后续非特权回调扫描注册（`SCAN_FAILED_SCANNING_TOO_FREQUENTLY`）；
   Bleak 文档、PunchThrough 排障文三源一致。该配额是 `DeviceConfig` 默认值、OEM 可变；
   Android 13 前超限**静默失败**（不回调 `onScanFailed`，只写 Logcat）。
   ⇒ 结论：重试路径不能反复 start/stop，`stop` 之后必须留收敛空窗再 start。
   - 来源：`wiki.androidperformance.com` / `Gracker/android-internals-wiki`（AOSP 17 行为）、
     `bleak.readthedocs.io`（5 start/stop per 30s）、`punchthrough.com/android-ble-scan-errors/`。
2. **`stopScan` 异步收敛 + 同 callback**：上一轮已锁定；本轮不重复。
3. **`system.logs` 的 unit 参数**：一手 `LogsParams{unit,lines,boot}` 只带 `deny_unknown_fields`
   （约束**键名**精确、不可多键），**没有任何「unit 固定白名单」约束**；上游 tree 里确有
   `btd/systemd/btd.service`、`robotd/systemd/robotd.service` 两个 systemd 单元。
   ⇒ `AiDebugReceiver.doRootCause` 旧提示「unit 仅接受固定白名单」是臆造约束，已订正为
     「填 `system.services` 回报的真实 systemd 单元名，无白名单」。

## 修复清单

### BLE/Wi-Fi 稳定性（4 项，均可离线证实）
| # | 文件 | 问题 | 修法 |
|---|------|------|------|
| 1 | `AndroidBleGattLink.kt` | `gatttrace/rootcause` 三个失败标签只有 TIMEOUT 可达：`awaitConnectReady()` 遇非 SUCCESS 就 `return false`，外层一律记 TIMEOUT，NO_CHAR / STATUS=n 成死标签 | `connect()` 失败时按 `opStatus` 分流：`GATT_LOCAL_NO_CHARACTERISTIC → NO_CHAR`、仍 SUCCESS → `TIMEOUT`、其它 → `STATUS=n`；三条都各自 `abortConnect(g)` close |
| 2 | `BleScanCoordinator.kt` | `end()` 用 `BluetoothAdapter.getDefaultAdapter()` stop，多卡设备可能与 `begin` 不同卡 → 旧扫描残留 → 下次 code=1 | 新增 `activeAdapter` 记录 begin 的实例，start/stop 同一 adapter；新增 `stop(cb)`（只停+归还闸位，不重新登记） |
| 3 | `BleConnectPanel.kt` | code=1 重试：`onScanFailed` 调 `begin` 停旧后又登记自己，500ms 后 `startScan` 里**再 begin 一次**紧贴 start 又 stop → 吃掉收敛间隔 + 撞 5/30 限流 | 重试路径改 `BleScanCoordinator.stop(this)`（只停不登记），500ms 空窗真正收敛；清掉因此失效的 `bleAdapter` 死字段 |
| 4 | `BleConnectPanel.kt` / `AiDebugReceiver.kt` | `begin` 后若 `startScan` 抛异常，闸位残留 current（僵尸 callback 卡住进程唯一闸） | 两条链的两个 catch 都补 `end(cb)` 归还 |

### AI 调试接口（3 项）
- `AiDebugPolicy.kt`：新增 `SNAPSHOT_METHODS` 单一权威（4 个只读诊断方法的 `Method` 常量子集）。
  刻意**不是** `READ_ONLY_METHODS` 全集（9 个）：`goAsync` 硬预算约 10s、逐方法 6s 有界 RPC，全集会撑爆预算 ANR。
- `AiDebugReceiver.doSnapshot`：方法名从手写字符串改为遍历 `AiDebugPolicy.SNAPSHOT_METHODS`，逐项仍经 `isRpcAllowed` 双保险。
- `AiDebugReceiver.doRootCause`：删臆造的 unit 白名单提示，改为指向 `system.services` 真实单元名。

## 门禁加固（负对照「改坏必红」）
- `check_ble_scan_mutex.py`：新增 7 组判据（GATT 三标签可达 + 各自 close、end 不用默认 adapter、activeAdapter 存在、
  重试路径用 stop 而非 begin、onScanFailed 内无 begin、start/AI 异常路径归还闸位）。
  负对照列表提为单一权威 `_trial_patches`，计数自动；selftest **13/13**。
- `check_ai_debug_extended.py`：新增 snapshot 子集判据（元素必须 Method 常量、⊆ 只读白名单、∩ 禁止方法=∅、
  doSnapshot 必须消费权威）+ rootcause 不得臆造 unit 白名单。负对照同样提为单一权威；selftest **13/13**。

## 验证结果
- 全量离线门禁 `check_all_app_gates.py`：**ALL_PASS**（19 项）；core JVM 自检 **725/725**。
- `:app:compileDebugKotlin`：**BUILD SUCCESSFUL**（`PIPE_RC=0`；2 条 deprecated warning 是既有 API 兼容回调）。
- `:app:assembleDebug`：**成功**，产出 `app-debug.apk`（30,639,215 B，09:14 本次构建）。
- ⚠️ `:app:lintDebug` / `:app:assembleRelease` leg：`clean + 三构建` 组合命令在
  `lintVitalAnalyzeRelease` 阶段遇 Gradle daemon JVM `EXCEPTION_ACCESS_VIOLATION (0xc0000005)`
  （伴随 R8 kotlin-metadata warning，jvm.dll 层崩溃，见 `hs_err_pid15696.log`）。
  这是**环境/JVM 崩溃**而非编译错误：本次无新增类、未改 R8 keep 规则，且 debug 编译链已全绿。
  按安全策略未重试该命令；release/lint leg 标记 `UNVERIFIED`，待下次分步单独跑确认。

## 真机边界（未测，按用户要求留后）
- 重试时序（stop → 500ms → start）是否消除 code=1/code=6：需真机 logcat 观察 `DuckGatt` 与 `onScanFailed` 码。
- GATT 失败三标签（NO_CHAR/TIMEOUT/STATUS=n）真机可读性：需复现缺 characteristic / status=133 场景。
- AI 通道全部命令（含 snapshot 子集、rootcause 新提示）：真机 Receiver 输出仍未闭环。
- `ship_verdict = NOT_SHIPPABLE` 不变。
