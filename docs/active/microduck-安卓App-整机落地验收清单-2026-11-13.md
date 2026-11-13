# MicroDuck 安卓 App —— 整机落地验收清单（UNVERIFIED 收敛路径）

_2026-11-13。目的：把散落在 README / P0 计划 / MEMORY 里的「未验证项」收敛成一份**可执行的验收清单**，
明确每一项怎么验、PASS 长什么样、参照谁。铁律：`UNVERIFIED != PASS`，每收敛一项先落证据再改判。_

## 0. 诚实基线（已验证 / 仍未验证）

**已 PASS（不依赖整机）：**
- `core` 真编译真测 **230/230**、`bash tools/selftest.sh`（`SELFTEST_RC=0`）。
- `:app:assembleDebug` **BUILD SUCCESSFUL**、`app-debug.apk` 可安装。
- 真机 **UI 行为门禁 59/59**（vivo V2338A / Android 16 / API 36，连跑 3 次 RC=0）——只验证 App 在 Android 上的行为，不含机器人整机联调。
- 真固件会话：**C2 11/11**（B 代 API16）、**C2+ 仿真状态流 24/24**（B 代 API16 + MuJoCo 仿真体）。
- **P1 驾驶 28/28**（真固件驾驶帧，连跑 5 次）。

**仍 UNVERIFIED（全部依赖整机 / 真板 / 真策略）：**
| 项 | 当前状态 | 为什么未验证 |
|---|---|---|
| 真机 GATT 上板 | `AndroidBleGattLink` 仅骨架，编译未上板 | 无真板联调 |
| 真视频 | 取景框占位，不伪造视频 | 未接 mediad 推流 |
| 策略启停 | AUTO = 监督视图·零驾驶帧（不调用策略） | 无可上板策略 + 未做启停 |
| 手感标定 | `maxVx/maxVyaw` 占位 | 须整机标定，仿真不作数 |
| 真机 50Hz / 传感器 | C2+ 仅证仿真固件层 | 未在真板复验 |
| netpad 上板 | B 代 API16 无 netpad | fanhao 板才有；当前真机手感/GATT 仍 UNVERIFIED |

## 1. 真机 GATT 联调（最高优先级——当前唯一真通信缺口）

- **现状**：`AndroidBleGattLink` 是骨架，真 GATT 未实现、未上板。Mock/TCP/WebRTC 后端能跑通会话层，但换上真板时 BLE 这条腿是空的。
- **参照实现**：`Ley-WL/ducklink`（Java 原生安卓 BLE 网关，GitHub API 核验，验证文化与本项目同源）。它解决的正好是本项目真 GATT 上板要解决的：
  - **前台 Service 持有 `BluetoothGatt`**：Activity 重建 / 切后台 / 锁屏不断链、GATT 连接复用（本项目 `AndroidBleGattLink` 骨架当前没有这层生命周期保护）。
  - **所有 GATT 操作串行**，急停指令优先。
  - `BleCodec` 的 `columns-v1` 无损压缩可作真 GATT 吞吐优化参考（15 舵机字段 1629→758 字节）。
- **GATT UUID（已与主仓 `btd/src/gatt.rs` 一手核验一致）**：
  - SERVICE：`6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019`
  - RPC：`6f5d2a11-3b47-4c8e-9a1f-2d7e8c4b6019`
- **验收步骤**：
  1. 实现 `AndroidBleGattLink` 真 GATT（按 ducklink 前台服务 + 串行写 + 后台/锁屏复用模式）。
  2. 连接真板 → 发现 services（含上述 SERVICE UUID）→ 写一帧 → 回读确认。
  3. 在 `device_ui_check.py` **新增 GATT 断言**：连接真实板后 `HealthSnapshot` / 状态帧出现非「未读到」，且 `BleTransport` 真收发、**零 canned**。
  4. 负对照：bonding 失败 / CCCD 未开 / `onCharacteristicWrite` 超时，App 必须走确定错误分支（不卡死、不假绿）。
- **PASS 判据**：真板连接后状态流/HUD 从「— 未读到」转为真实数值，断链→重连→自动重订阅恢复。

## 2. netpad 上板（fanhao 有，B 代无）

- 板上 `service.sh netpad on` 后，验证 UDP 4210 驾驶方向与 250ms timeout。
- ⚠️ **B 代 API16 无 netpad** ⇒ 真机手感 / GATT 仍 UNVERIFIED，除非上 fanhao（API40）板。这是当前真通信的另一道墙。

## 3. 真视频（WebRTC mediad）

- 当前「摄像头取景框占位」明确不伪造视频（开源对照里 ohho.apk 的 LIVE/DEMO 标签文化）。
- 接 mediad 推流 → HUD 来源标签从 `MOCK 演示夹具` 切 `实机 [...]`。
- 验收：真流可达、卡顿/延迟可接受、来源标签正确、退出遥控即停流。

## 4. 策略启停（AUTO 模式当前是监督视图，零驾驶帧）

- 当前 AUTO 严格按 NIST UTAP / Sheridan 监督级：**不调用任何策略、不发驾驶帧**。这是有意的「不碰未验证策略启停」。
- 真启动自主行走需要：① 可上板的 stand/walk 策略（来自训练线，但训练线已 `D1 DEFERRED` 等整机）；② 运行时 walk/stand 热切换（主仓 `VelStand` `--switch-threshold` 0.05 思路，`-32601` 能力降级已铺好）。
- PASS 判据：AUTO 下确有策略在跑、可一键切回手动、退出即停车、低速死区有运行时兜底（非 App 侧假启动）。

## 5. 手感标定（`maxVx` / `maxVyaw` 占位）

- 计划中明定为占位，须整机标定，仿真不作数。验收：实机低速/高速手感、转弯半径符合预期、死区/限幅不漂移。

## 6. 真机 50Hz 抖动 / 传感器

- C2+ 只证「仿真固件层」状态流；真机 50Hz 状态流、IMU / ToF 读数须在真板上复验。
- 复验命令同 §7，重点看 `achieved_hz≈50`、`healthy=true`、传感器字段非占位。

## 7. 复验 SOP（每拿到新硬件 / 新板必跑）

1. `adb devices` 确认已授权；多设备时用 `ANDROID_SERIAL=xxx` 指定目标。
2. `bash tools/selftest.sh` → **230/230**。
3. `JAVA_HOME=E:/软件工具/OpenJdk17 ./gradlew :app:assembleDebug --offline` → **BUILD SUCCESSFUL**。
4. `adb install -r app/build/outputs/apk/debug/app-debug.apk` → `Success`。
5. `python tools/device_ui_check.py` → **59/59**（UI 门禁，含状态页 4 列 + 设置页 BLE 面板可见性）。
6. （新增）真板 GATT 连接断言（见 §1）。
7. 负对照逐条复跑：通知栏污染（`cmd statusbar expand-notifications`）、不订阅零帧、断链→重连→重订阅恢复。

## 8. 铁律

- `UNVERIFIED != PASS`；每收敛一项，**先落证据（截图/日志/断言输出）再改文档状态**，绝不先改判。
- 改门禁 / 通信代码后必须重跑 §7，不得凭「之前绿过」外推（uiautomator 视口坑就是这么来的）。
- 整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。
