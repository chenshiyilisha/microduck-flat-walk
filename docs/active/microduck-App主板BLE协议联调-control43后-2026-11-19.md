# App↔主板 BLE 协议级联调（control.43 刷入后回归）— 2026-11-19

_范围：只做**协议面**联调（BLE 扫描 / GATT UUID / API_VERSION 单次只读），验证 control.40→.43 刷入后 App 对接契约未被破坏。不验证整机、不验证舵机/IMU、不改 ship_verdict。铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`。_

## 1. 为什么要做这次联调

用户问「不需要 app+主板联调一下吗」。固件刚从 `control.40` 刷到 `control.43`，而 App↔板的唯一通道是 `btd` 的 BLE GATT（板上无 TCP RPC 监听，11-14 已确证；App 的 `Tcp`/`WebRtc` 后端在本板无对应服务）。刷机后协议寻址是否仍通、API_VERSION 是否漂移，是本轮必须一手核的回归点。

## 2. 联调分层（诚实界定能做什么）

| 层 | 本次是否做 | 原因 / 结论 |
|---|---|---|
| 板侧 daemon 健康 | ✅ 已核 | `btd/configd/robotd/mediad` 全 `active`；`robotd` SubState=running |
| BLE 广播可见 | ✅ 已核 | 板上 `ActiveInstances` 广播在；`GATT application registered; waiting for a central` |
| PC 侧真实无线电扫描 | ✅ 已做 | 命中 `duck-6a07`，63 个独立设备负对照 |
| GATT UUID 契约 | ✅ 一致 | control.43(v167) 固件 `6f5d2a10…`/`6f5d2a11…` 与 App `GattLink.kt` 逐字一致 |
| API_VERSION 单次只读 | ✅ 已做 | 板报 `0x25`=37；App Wire=40；三重负对照全过 |
| 完整握手（hello→auth→READY） | ❌ 未做 | 需真实中心的 NDJSON 写+订阅；探针设计**禁写**，真机 App 手机未插 adb |
| 整机动作（站立/行走/50Hz 总线） | ❌ 未做 | 15 舵机全 timeout、IMU not ready，整机未落地 |

⇒ 本次是**协议面只读联调**，不是端到端功能联调。后者仍卡整机 + 手机 adb。

## 3. 一手证据（`tools/evidence/2026-11-19-ble-api-readback/ble_api_version_single_read.json`）

- sha256 `9df9667a13a116d066d79241ab91569f37cee4d2cdef8c32b74b3de5a9db4eb3`（源 downloads 与 evidence 目录逐字一致）。
- 探针：`probe_ble_api_version.py`（`--selftest` 8/8，含"注入写操作必被 AST 抓到"负对照；源码 AST 断言零 `write/notify/pair/bond`、零凭据赋值）。
- 环境：`bleak` 装在系统临时目录 `.../Temp/bleak_probe_20261119`（腾讯 PyPI 镜像，**未污染项目 venv**），沿用 11-14 先例。11-14 那套临时目录只剩残缺 `backends/`（无 `__init__.py`），按"残缺目录"教训未复用。

### 3.1 观测值（两条独立算法互算）

| 项 | 值 |
|---|---|
| 命中候选 | `CC:C8:37:E3:7C:90` / `duck-6a07` / vendor UUID `6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019` / RSSI −45 |
| 扫描独立设备 | 63（负对照：真实无线电扫描，非固定列表）|
| RPC_UUID 单次 read | `read_bytes_hex=25`，`read_len=1` |
| 十进制派生 | 算法① `int("25",16)=37`；算法② `int.from_bytes(bytes.fromhex("25"),"little")=37` ⇒ 自洽 |
| `api_version_matches_app` | false（板 37 vs App Wire 40）|
| 探针 verdict | `API_VERSION_MISMATCH`（判据本身正确，语义见 §4）|

### 3.2 三重负对照（证明测量可信）

- 不存在的 peer `00:00:00:00:00:00` → 连接失败 `BleakDeviceNotFoundError`，`as_expected=true`。
- 不存在的 characteristic `0000dead-…` → 读失败 `BleakCharacteristicNotFoundError`，`as_expected=true`。
- AST：源码无写/订阅/配对/凭据赋值；注入写操作被自检抓到（8/8 含此负对照）。

## 4. `API_VERSION_MISMATCH` 为何不是联调失败

- 板报 37、App `Wire.API_VERSION=40` 的 skew **不是刷机引入**：11-14 源码注释已记录同值 `0x25=37`（SSH 侧 `robotctl` v37 CLI / `robotd` v40 daemon）。刷 control.43 后**仍是 37** ⇒ 刷机未破坏版本面。
- App 对 skew **只记录、不硬拒**：`BleTransport.kt` 把读到的值存入 `peerApiVersion` 供可观测，绝不因此断链。一手依据：上游 `duck-ipc-proto/src/lib.rs:961` "A version difference is logged and served"，`PROTOCOL_MISMATCH` 已退役，方法缺失靠 −32601 逐方法降级。
- 探针的 `API_VERSION_MISMATCH` 只是"读到的值≠写死的 App 常量"这一**字面判据**，不代表连接会失败。App 的真实握手行为（hello 带 api_version=40、服务端 logged-and-served）需真机中心才能端到端验证 —— 本次未做，标 `UNVERIFIED`。

## 5. 与 11-14 证据契约的关系（不篡改历史）

- `tools/check_ble_gatt_evidence.py` 的 `transcribed_observations` 里，`API_VERSION_SINGLE_READ_STABLE(0x25)` 仍诚实标 `SESSION_STDOUT_TRANSCRIPT` / `TRANSCRIBED_NOT_ADMISSIBLE_FOR_PASS`——11-14 那次确实没落盘 JSON，**不因今天补了新证据就改写它**（改了等于伪造历史）。
- 本次 11-19 的 `ble_api_version_single_read.json` 是**独立的一手落盘证据**（`FIRST_HAND_PERSISTED`），固化在 evidence 目录。它闭合的是"探针 --json-out 缺口"（契约 note 里写"下次上板补齐"），不是把旧转录洗白成 PASS。
- `BA-X-5` 判定链未动；本工具永不输出 PASS，签收权仍在 `board_acceptance` + signoff。

## 6. 改动与验证

- 新增证据：`tools/evidence/2026-11-19-ble-api-readback/ble_api_version_single_read.json`（sha 如上）。
- 新增文档：本文件。
- 未改：`check_ble_gatt_evidence.py` / `ble_gatt_evidence_contract.json` / 任何 App 功能代码 / 固件 / 契约 / xlsx / SSOT。
- 验证：探针 selftest 8/8、真实扫描+单次只读 rc=0、三重负对照全过、sha 源/目的一致、两条十进制算法互算=37。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不翻；`verification_tier` 至多到 `SBC_LIVE`（bleak 从 PC 读板载 BLE，非整机）。

## 7. 仍待（不属本次范围）

- 完整握手 hello→auth→READY：需把手机插回 adb、装最新包、真 App 点 `duck-6a07` 走一遍并抓 logcat（11-14 `android_app_connect_live.json` 那次握手 FAILED，修复后是否已通未复验）。
- 整机功能：15 舵机 + IMU + 电池落地后，才能验 50Hz 总线与站立/行走。
