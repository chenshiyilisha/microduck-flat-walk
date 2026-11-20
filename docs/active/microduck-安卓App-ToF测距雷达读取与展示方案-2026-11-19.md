# MicroDuck 安卓 App · ToF 测距雷达数据读取与展示方案（2026-11-19）

_需求：用户「还差一个测距雷达的数据读取展示，按最优的来」。_
_约束：一手源码优先；缺字段「未读到」不填 0；不改任何既有门禁断言；真机可达性如实标注，不用 Mock 冒充实机。_

## 0. 一手数据契约（ft1910 `duck-ipc-proto/src/lib.rs`，本地全文核证 2026-11-19）

| 项 | 值 | 出处 |
|---|---|---|
| 订阅方法 | `tof.stream`（`Call::TofStream`，由 `tofd` 应答） | lib.rs:1145, 917 |
| 帧通知 | `tof.frame`（无 id 的 notification） | lib.rs:934, 1949-1965 |
| 帧结构 | `TofFrame{seq:u64, at_us:u64, t_ns:u64, rows:u8, cols:u8, distance_mm:Vec<i16>, status:Vec<u8>}` | lib.rs:4838-4865 |
| 单位 | **毫米**，status 是 ST 原始字节（不是米、不要自己造阈值） | lib.rs:4840-4845 |
| 分辨率 | 8×8=64 格，row-major | `tof/src/lib.rs:50-54` |
| 三态判据 | status ∈{5,9} 且 distance>0 → Range(m)；255 → NoTarget；其余 → Unusable(code)；缺字段 → NoTarget | `tof/src/lib.rs:74-108`（`Frame::zone`） |
| 有效计数 | `valid_count()` = Range 格数 | `tof/src/lib.rs:115-119` |
| 量程边界 | <10cm 读数不可信（传感器串扰）；下视 >85% 传感器高度判 Floor（本项目只展示原始距离，不做重投影） | `kinematics/src/tof.rs:97-103` |

## 1. 真机可达性（关键判决，不能假装读到）

- `btd` **明确拒绝** `tof.stream`（`btd/src/route.rs:489-494`）：64 格 ×15Hz 塞不进 20 字节 BLE 管道，且 `tofd` 不是 `btd` 持有的 socket。
- 唯一真机路径：**`mediad` 的 WebRTC datachannel**（`mediad/src/route.rs:210-215` 放行 `TofStream`；`upstream.rs:48-70` 代理到 `/run/tofd/tof.sock`）。
- App 现状：`RobotTransport.WebRtc(host, 8443)` 后端骨架存在，但当前 UI 走 Mock/TCP；完整真机 ToF 需要 mediad 信令握手 + `tof.stream` 订阅，**属整机联调范畴，本轮不宣称完成**。
- ⇒ 判决：本轮落地**解析层 + golden vector + 展示 UI（Mock 夹具标注非实机）**，真机订阅入口按一手契约预埋并如实标注「需 mediad WebRTC 链路，未实机验证」。不把 Mock 数据伪装成实机。

## 2. 设计

### 2.1 core 层（可 JVM 真测）
- `Wire.TOF_STREAM="tof.stream"` / `Wire.TOF_FRAME="tof.frame"`（常量注释绑一手行号）。
- `TofSnapshot`：解析 `TofFrame` JSON → 64 格 `TofZone`（Range 米 / NoTarget / Unusable 码 / Missing），带 `seq/atUs/t_ns/rows/cols/validCount`。
  - 逐字对齐 `Frame::zone`：**status 决定含义**；有效 status 但 distance≤0 判 Unusable（负距离是失败收敛）；数组长度不符/缺失按 NoTarget 处理，越界不 panic。
  - 解析失败/缺整个 frame → 整帧空，UI 显示「未读到」，**不填 0**。
- `CoreSelfTest` 加 KAT（golden vector，从 Rust 测试值搬）：
  - status 5 + 1234mm → Range 1.234；status 9 + 500mm → 0.5；255 → NoTarget；4 + 900 → Unusable(4)；5 + (−3) → Unusable(5)。
  - 负对照：ragged 帧（distance 3 项/status 2 项）第 2 格 NoTarget、越界 NoTarget；改坏任一阈值必须变红。
- `MockTransport` 加 `tof.frame` 通知夹具（演示用，UI 明示「Mock 演示夹具 / 非实机读数」）。

### 2.2 UI 层
- 新页/新区块「ToF 测距 · 8×8 深度」：4×… 实际按 8×8 网格渲染 64 格，每格按三态着色：
  - Range → 按距离映射色阶（近=暖/远=冷，图例写距离区间）；NoTarget → 中性暗格；Unusable → 告警色 + 角标码。
  - 顶部：`seq / valid_count / 数据来源声明（Mock 非实机 or 实机 tof.frame）/ 未读到`。
  - 底部图例 + 一手边界注记（<10cm 不可信、本展示为原始斜距非重投影）。
- 数据来源标注与既有健康页同规格：Mock 夹具必须显示「非实机读数」；无帧显示「未读到」，绝不默认绿。
- 不新增门禁断言文案（新增文案不与既有断言冲突）；content-desc 给新组件但不动 `标签页*` 四个硬串。

## 3. 实现落地（2026-11-19）
- **core**：新增 `TofSnapshot.kt`（安全解析 + 三态判据逐字对齐 Rust `Frame::zone`）；`Wire` 加 `TOF_STREAM/TOF_FRAME`；`MockTransport` 订阅 tof.stream 推 8×8 夹具（非实机）；`RobotRepository` Snapshot 加 `tof` 字段 + 订阅 + 换链路/断连清空。
- **app**：`MainViewModel.UiState` 透传 `tof`；健康页新增「头部 ToF · 8×8 深度」分区（64 格网格 + 三态着色 + 来源标注 + 一手边界注记）。
- 🔴 **负对照抓到真 bug**：首版 `disconnect()` 漏清 `tof` 字段 ⇒ 旧深度帧回灌（负对照 `disconnect 后 ToF 清空` 变红）；已修（disconnect + connectWith 双路径都 `tof=null`）。这正是「只见过绿色的断言不是证据」的又一例。

## 4. 验证结果
- ✅ core selftest **662/662**（基线 640 + ToF 22 条，含 golden vector、ragged 帧、status 决定语义、负距离、disconnect 回灌负对照）。
- ✅ 统一门禁 `check_all_app_gates.py` **ALL_PASS**（`.venv-mjlab`，含 core 662）。
- ✅ `assembleDebug` **BUILD SUCCESSFUL**。
- ✅ **真机目视已补（USB 重插后，设备 `10CE3T12D40011F`）**：`build/uiredesign/tof/tof_grid_fixed.png` 目视确认 —— 来源标注「⚠ Mock 演示夹具 · 非实机 · 第 1 帧 · 有效 9/64」，中央 3×3 距离数值 0.60→0.75（近暖橙/远冷蓝色阶正确），两格红色 `!` 告警格，其余空暗格 NoTarget，无视觉 bug。
- ✅ **真机门禁无回归**：`device_ui_check.py` = **61 passed / 0 failed**。
- 🔴 **又抓一处 UI bug**：首版把 `renderToF` 放在 `renderMonitor` 末尾，而 `renderMonitor` 在 `monitorReport==null` 时提前 return（Mock 不调 health ⇒ 恒提前返回）⇒ ToF 区全空点、来源标注空白。修法：把 `renderToF` 移到 `renderAll` 里独立调用，不受 health 是否读到影响。再次印证「看不到数据先问渲染链走没走到」。

## 5. 真机 ToF 数据可达性（不变结论）
- 本轮只做到「解析层 + 展示层 + 真机订阅入口预埋」。真机要真出深度帧，必须走 mediad WebRTC datachannel 订阅 `tof.stream`；当前 UI 默认 Mock/TCP 链路下 tof 保持「未读到」是**如实行为**，不是 bug。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。
