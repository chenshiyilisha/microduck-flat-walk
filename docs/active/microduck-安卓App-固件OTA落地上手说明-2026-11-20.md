# MicroDuck 安卓 App 固件 OTA 落地上手说明（2026-11-20）

_用户「能不能再加一个固件更新功能，有新版本 app 提示，通过 app 更新」+「查查资料，看固件的更新流程和技术」+「全部落地，按照最优的来，多查资料」。本文记录固件 OTA 的一手依据、落地结构、操作路径、验证证据与真机边界。_

> 铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`；写操作（apply/rollback/select）必须二次确认；真机升级落地/health gate/BLE lane 分道 **恒 UNVERIFIED**，`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

---

## 0. 一句话结论

固件侧 OTA 后端**早已完整**（kissqy v167 updaterd + btd 放行 update.*）；本轮补齐的是**手机 App 侧的消费链**：检查提示、写操作、进度、回滚、二次确认，全部按一手协议逐字对齐。手机只做「触发 + 看进度 + 查询」，**固件包由板子自身 WiFi/HTTPS 拉取并 minisign 验签**，BLE 不传大包（这是最优方案的一手硬约束，不是取舍）。真机能否升级仍须整机落地后验证。

---

## 1. 一手依据（本轮新核，非沿用记忆）

### 1.1 固件协议（kissqy v167 源码逐字）

路径：`microduck-software/.upstream/kissqy-firmware/versions/v167/microduck-hd1910/firmware/`

- `duck-ipc-proto/src/lib.rs`：`update.check` 的 `CheckResult` 是**三态内部标签** `up_to_date`/`available`/`incompatible`（available 带 installed/candidate/mandatory/changelog）；`Phase` 是 **13 个值**（非旧文档的 downloading/done/failed）；`ApplyResult.outcome` 是 applied/already_current/dry_run_passed/rolled_back/stuck；`update.status`/`log`/`listInstalled` 的 result 都是 **Vec 数组**。
- `docs/design/updater-design.md`：「robot **pulls** from CDN over its own wifi; phone is trigger + progress only. Big payloads never touch BLE.」验签顺序：验 manifest 签名 → 下 artifact → 验 sha256 → 验 artifact 签名（minisign，公钥集合 `/etc/robot/trusted_keys/`）。
- `docs/project/update-over-ble.md`：**apply reply 后约 5 秒 btd 重启断连属成功路径**；进度每整百分比≤1 条、每秒≤4 条；`update.subscribe` 独占整条连接；无 cancel。
- `btd/src/route.rs`：BLE 放行 `check/apply/status/subscribe/log/show/listInstalled/rollback/select`；拒绝 `update.pin`/`resetToGolden`。
- 错误码：1 BUSY / 5 NETWORK / 6 VERIFICATION / 9 HEALTH_CHECK_FAILED / 14 PERMISSION_DENIED / -32601 METHOD_NOT_FOUND。

### 1.2 外部 OTA 最佳实践（交叉核对，非作为协议依据）

- RFC 9019（IETF IoT 固件更新架构）：manifest 带序号、拒绝降级到已知漏洞版本 —— 与固件 `min_supported`/downgrade guard 一致。
- Android in-app updates / WithIntent OTA UX：设置专区提供手动检查入口 + 详情/二次确认 + 进度反馈；不后台轮询、不打断当前操作 —— 与本项目「手动检查、无后台轮询」一致。
- Android OTA 通用：签名校验由设备端执行、客户端不重复验签 —— 固件已用 minisign 在板端验，App 不重复实现验签（避免假安全）。

---

## 2. 落地结构（文件清单）

| 层 | 文件 | 职责 |
|---|---|---|
| core 决策 | `FirmwareUpdate.kt`（新） | check 三态/status 13 phase/apply outcome/progress/log/listInstalled 解析；写操作参数构造（deny_unknown_fields 精确键）；错误码解读。纯 JVM，含 null-safe 类型防护 |
| core 快照 | `FirmwareSnapshot.kt`（新） | 不可变 OTA 状态（check/components/installed/logs/progress/busy/resultText） |
| core wire | `Wire.kt` | 新增 6 个一手方法常量（apply/rollback/select/subscribe/progress/show） |
| core 会话 | `RobotSession.kt` | 新增 `callRaw()` 收数组 result（普通 `call` 用 `getAsJsonObject` 会把 Vec 吞成 null）；`UPDATE_SHOW` 进只读白名单 |
| core 数据 | `RobotRepository.kt` | 只读刷新 + check + apply/rollback/select 写操作（replayable=false）；进度经 `Event.Notification` 临时收集，换链路/断开即作废 |
| app UI | `FirmwarePanel.kt`（新） | 设置页「更新」区：检查/刷新/立即更新（二次确认）/回滚（二次确认）+ 进度条 + 结果回显 |
| app 接线 | `MainViewModel.kt` / `MainActivity.kt` | UiState.firmware + 事件转发 + renderAll 渲染 |
| 门禁 | `tools/check_firmware_ota.py`（新） | 锁一手常量/数组走 callRaw/写操作不重放/二次确认/不独占连接/断连不谎报；元负对照 6/6 |
| 自检 | `CoreSelfTest.kt` | `testFirmwareUpdate` 45 项（含 12+ 负对照 + session 端到端） |

### 2.1 三个关键设计决策（都是一手逼出来的）

1. **数组 result 必须走 `callRaw`**：`update.status/log/listInstalled` 的 result 是 `Vec`，`RobotSession.call()` 的 `readResult()` 用 `getAsJsonObject("result")`，数组会抛异常被吞成 null ⇒ 假「未读到」。自检里有负对照专证这一点（普通 call 得到空对象、callRaw 得到数组）。
2. **进度不长期订阅 `update.subscribe`**：它独占整条 BLE 连接，会把 `robot.state`/`robot.health` 通道挤掉（一手 `update-over-ble.md`）。改为 apply 调用期间临时监听 `Event.Notification(update.progress)` —— 一手明确 apply 会在自己连接上先推 progress 再回 reply。
3. **断连不谎报成功**：apply reply 后约 5s btd 重启断连是成功路径。call 因断连失败但收到过 progress ⇒ UI 回显「已提交，重连后点刷新确认」，`resultOk=null`（既非成功也非失败）；最终落地只由重连后 `status.last_attempt` 证实（COLLECTED）。

---

## 3. 操作路径（用户怎么用）

1. BLE 连接主板（设置→连接→BLE 连接）→ **先配 WiFi**（固件 OTA 依赖板子自身网络）。
2. 设置→更新→固件更新→「检查更新」。三态回显：发现新版本（可带 mandatory）/已是最新/不兼容。
3. 发现新版本后「立即更新」→ **二次确认对话框**（说明板子会下载验签、重启断连、勿断电、失败自动回滚）→ 确认。
4. 进度条实时显示 13 phase 中文标签 + 百分比。
5. BLE 断连属正常；**重连后点「刷新状态」**，从 `update.status.last_attempt` 读最终结果。
6. 如需回退：「回滚」（只重指向已装 release，不下载），同样二次确认。

> 注意：当前设置页 `applyButton` 仅在「确有问题 check=available」时可点；这是刻意的安全门槛（先检查再装，带明确版本号），不是缺功能。

---

## 4. 验证证据（本轮真跑）

- core 自检 `bash tools/selftest.sh`：**722 passed, 0 failed**（其中 `testFirmwareUpdate` 45 项，含状态拼错/percent 越界/未知 outcome/非数组 result/写操作不重放等负对照，及 Mock session 端到端进度收集）。
- 全量门禁 `python tools/check_all_app_gates.py`：**15 项 ALL_PASS**（新增 `check_firmware_ota.py` 自动纳入，主判据 OK + 元负对照 6/6「改坏必红」）。
- `assembleDebug`：**BUILD SUCCESSFUL**。
- 负对照已证：普通 call 对数组 result 得到空对象（证明 callRaw 必要）；改坏方法常量/重放/二次确认/独占订阅，门禁均变红。

---

## 5. 边界与未解锁项（UNVERIFIED）

- **真机升级**：未与真板对拍；整机未落地（15 舵机缺、IMU not ready、rc=78 启动门）⇒ 升级后无法验证 50Hz 总线。`live_hardware_accessed=false`。
- **health gate 自动回滚**：固件侧有进程测试，但本 App 未真机触发验证。
- **BLE lane 分道**：本实现用「apply 连接临时收进度」规避了 subscribe 独占问题；这是协议允许的路径（一手明确 apply 自己推 progress），但**真机 4-lane 并发未验证**。
- **加密固件**：BLE 链路层 Noise 代码已写（见 §A2' 功能清单），但加密固件未跨仓落地、PSK 配对二维码未真机走通、`INTEROP_UNVERIFIED` 恒真。路线 A/B/C 仍需用户拍板。
- **整卡重刷 20261027**：预案就绪、未执行（缺物理取卡 + 丝印确认）。见 `microduck-固件更新-四项执行预案与硬前置-2026-11-19.md` §5。
- 本轮未碰 xlsx / 采购 / 契约 / SSOT；`ship_verdict=NOT_SHIPPABLE` 不变。
