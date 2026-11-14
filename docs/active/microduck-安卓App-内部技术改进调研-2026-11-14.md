# MicroDuck 安卓 App — 内部技术改进调研（资料支撑版）

_2026-11-14。用户要求：「找找资料，有没有可进行内部技术改进的地方」。_
_本文件**只做调研与依据核对，不改功能代码**。每条挂一手来源；术语遵循_
_`docs/active/microduck-来源术语约定-2026-11-13.md`：**「原厂 / 官方」只指 Pollen Robotics 原厂**，_
_Google / Android / GitHub 一律写「Google Android 平台文档」「GitHub 官方文档」等具名。_

---

## 0. 结论速览

功能面缺口见《功能缺口与可加功能清单》（A2/A3/A6/A7/A8 未做，多需拍板或等整机）。
**本轮聚焦「不依赖整机、纯内部工程质量的改进」**，共 7 项，按优先级：

| 优先级 | 改进项 | 一句话依据 |
|---|---|---|
| P0 | ⑤ BLE GATT 操作串行化 + 回调线程纪律 | Google Android BLE 无内部队列，多份工程一手实践一致 |
| P1 | ① 更新检查加 ETag 条件请求 | GitHub 官方文档：304 不计入速率限制 |
| P1 | ② 发布构建上 R8 | Google 官方文档：发布版应开 isMinifyEnabled + isShrinkResources |
| P2 | ③ 下载断点续传（Range + If-Range） | RFC 7233/7232；GitHub Release 资产 CDN 实测支持 206 |
| P2 | ④ 长下载放 dataSync 前台服务 | Google Android 官方 FGS 类型文档：dataSync 用于数据下载 |
| P2 | ⑥ OkHttp 替代 HttpURLConnection | 与 ③④ 绑定决策，不单独做 |
| P3 | ⑦ Settings 迁 DataStore | Google Android 官方倡议，收益有限，顺带做 |

---

## 1. 逐项调研

### ① 更新检查加 ETag 条件请求（P1，成本极低）

- **依据（一手）**：GitHub 官方文档《Best practices for using the REST API》
  （docs.github.com/en/rest/guides/best-practices-for-integrators）：
  「Making a conditional request does not count against your primary rate limit if a 304
  response is returned … This makes conditional requests especially useful when you poll an
  endpoint, because each 304 Not Modified response is fast and does not use your rate limit.」
  做法：保存响应 `etag` 头，下次请求带 `If-None-Match`；未变化返回 304。
- **现状（读码）**：`UpdateController` 用 SharedPreferences 做 3 小时节流，每次「检查更新」
  都实打实请求一次 `releases/latest`。本机未认证限流 60 次/小时，实测过 404 路径。
- **改进**：节流之外叠加条件请求——存上次 ETag，带 `If-None-Match`；304 → 直接「已是最新」，
  不限流、更省流量。HttpURLConnection 原生支持自定义头，**无需换网络库**。
- **负对照**：故意传坏 ETag 值 → 必须回落正常 200 解析流程，不得误判「无更新」。

### ② 发布构建上 R8（P1，官方明确）

- **依据（一手）**：Google Android 官方文档《Enable app optimization with R8》
  （developer.android.com/topic/performance/app-optimization/enable-app-optimization）：
  「我们建议您始终同时启用（isMinifyEnabled 与 isShrinkResources）……建议仅在发布前测试的
  最终版本（通常是发布构建版本）中启用」；收益 = 更快启动、更低内存占用、更少 ANR。
  另见《Configuration of R8》：release 构建类型须用默认优化规则
  `proguard-android-optimize.txt`。
- **现状（读配置）**：当前发布的 `app-debug.apk` 是 **debug 构建**（未开 R8、带调试信息、
  包体更大）。固定签名（`signingConfigs.fixed`）已就位，只差构建类型本身。
- **改进**：release 构建类型开 `isMinifyEnabled = true` + `isShrinkResources = true`，
  用 `getDefaultProguardFile("proguard-android-optimize.txt")` + 自写 keep 规则；
  发布脚本改为产出并校验 **release APK**。
- **注意（一手）**：Gson 走反射，R8 可能裁掉反射用到的字段/类——keep 规则必须按
  Google 文档补，并用「构建成功 + 真机安装 + 门禁 59/59」做端到端负对照；
  若 keep 规则写崩，R8 的裁剪错误会以运行时崩溃形式出现，属可逆（改规则重编），风险可控。

### ③ 下载断点续传（P2，需先实测服务端行为）

- **依据（一手）**：
  - RFC 7233（Range 请求 / 206 Partial Content）、RFC 7232（ETag / If-Range）；
  - GitHub Release 资产经 CDN 分发，**实测支持 Range**：对 `releases/download/...` 发
    `Range: bytes=0-1023` 返回 206（michaelaye.github.io《Using GitHub Releases as a Free
    Data CDN》实测记录；gh-release-mcp 等工具以分片 Range 下载 GitHub 资产为默认行为）；
  - GitHub REST API 资产对象自带 `digest: "sha256:..."` 字段（docs.github.com
    《发布资源的 REST API 端点》）——可作为 update.json 之外的**第二校验来源**；
  - 踩坑一手记录（CSDN 工程实践）：服务端不支持 Range 时必须**降级全量重下**，硬拼分片
    必坏；续传前用 HEAD 拿最新 ETag，带 `If-Range`，文件换版则服务端返回 200 全量，
    此时必须放弃旧进度。
- **现状（读码）**：`GithubReleaseClient` 整包重下，失败即从头再来；无 Range / If-Range。
- **改进**：下载前 HEAD 拿 ETag；续传带 `Range: bytes=<已下字节>-` + `If-Range: <ETag>`；
  206 → 追加写；200 → 弃旧进度全量重下；SHA-256 校验失败删临时文件。
  临时文件名带 versionCode，防半包被当成完整包（工程实践共识）。
- **边界**：5.8 MB 包在好网络下收益有限，弱网（移动网络/不稳定 Wi-Fi）才显著；
  不做多线程分片（单连接顺序续传已够，分片引入竞态复杂度，收益不成比例）。

### ④ 长下载放 dataSync 前台服务（P2，官方一手）

- **依据（一手）**：Google Android 官方文档《前台服务类型》
  （developer.android.com/guide/components/fg-service-types）：`dataSync` 类型描述为
  「Data transfer operations … Data upload or download … Transfer data between a device
  and the cloud over a network」，**运行时前提：无**；Android 14 起 FGS 必须声明类型，
  否则 `startForeground()` 抛 `MissingForegroundServiceTypeException`（Android 14 变更文档）。
  官方还提示多类型可组合声明，但须同时满足所有类型的强制要求。
- **现状（读码）**：下载在 Activity 内由 `UpdateController` 执行，切后台/锁屏进程有被回收
  风险，目前 App 里唯一的前台服务是 BLE 的 `DuckBleService`（connectedDevice 类型）。
- **改进**：长下载（尤其 ③ 上量后）改由 `dataSync` 前台服务承载 + 进度通知；
  Manifest 声明 `FOREGROUND_SERVICE_DATA_SYNC` 权限与 `foregroundServiceType="dataSync"`。
  下载与 BLE 是两个独立服务，不必与 connectedDevice 组合，避免叠加强制要求。

### ⑤ BLE GATT 操作串行化 + 回调线程纪律（P0，真机核心链路硬前置）

- **依据（一手，多源一致）**：
  - ZOOZ Engineering《Making Android BLE work — part 3》（Martijn van Welie，BLE 领域公认
    实践系列）：Android 的 `BluetoothGatt` **没有内部队列**，reads/writes/notifications
    交错会互相干扰；`BluetoothGattCallback` 跑在 Binder 线程，**阻塞会卡住后续所有回调**；
    Android 会**复用** `BluetoothGattCharacteristic` 对象——收到通知后必须**立即拷贝
    byte[]** 再处理，否则竞态丢数据；GATT 调用应从自己的线程发起，尽快离开 Binder 线程；
  - Punch Through《Android BLE: The Ultimate Guide》：同结论，「Queue operations and execute
    them serially, and always wait for a callback for a previous operation before you initiate
    a new one」——适用于连接、服务发现、MTU、读写、断开**所有**操作；
  - 社区佐证：`Ley-WL/ducklink`（本项目此前已引用）即「前台服务持 GATT + 操作串行」。
- **现状（读码）**：`BleTransport` 已有 `synchronized(writeLock)` 等锁，但**是否做到
  「等待 onCharacteristicWrite 回调后再发下一条写」需逐行核对**；入站数据是否在回调里
  立即拷贝需核对；DuckBleService 持 GATT 的上板行为仍 UNVERIFIED。
- **改进**：把 GATT 操作收敛为**单线程串行队列**（等回调再发下一条）、入站字节**立即拷贝**、
  回调只做投递不做重活；串行队列逻辑放 core，可用 Mock GattLink 做 JVM 自检 + 负对照
  （乱序发写必须被拒绝/排队）。**不依赖整机**，但直接决定真机 GATT 稳定性，是最该先做的。

### ⑥ OkHttp 替代 HttpURLConnection（P2，与 ③④ 绑定决策）

- **依据**：Google Android 官方《避免使用尚未最佳化的下载内容》以 OkHttp 为例讲解
  条件缓存与下载优化（developer.android.com/training/efficient-downloads）；
  社区工程实践一致认为 OkHttp 的连接池 / HTTP/2 / 拦截器是断点续传、ETag 缓存的成熟载体。
  ⚠️ 如实说明：「Google 官方推荐 OkHttp」的说法主要来自社区与媒体文章，
  **Google 官方文档本身并未强制要求第三方网络库**；HttpURLConnection 对简单请求完全够用。
- **现状**：`GithubReleaseClient` 用 `HttpURLConnection`。
- **判定**：**不单独做**。若做 ③④，Range/进度/重试手写成本高，换 OkHttp 更省；
  只做 ① 的话 HttpURLConnection 足够。三者绑成一个决策。

### ⑦ Settings 迁 DataStore（P3，规范性改进）

- **依据（一手）**：Android Developers Blog《Prefer Storing Data with Jetpack DataStore》：
  SharedPreferences 的同步 API 可在 UI 线程调用、无错误信号机制、无事务；
  DataStore 提供异步 Flow、事务性读写、损坏处理，并提供官方
  `SharedPreferencesMigration` 自动迁移。
- **现状**：`SettingsStore` 与 `UpdateController` 节流均用 SharedPreferences
  （当初选它是「零新依赖」，注释里写明）。
- **判定**：键值很少，**收益有限，属规范性而非痛点**；若做 ①② 可顺带迁移，不单独立项。

## 2. 明确不列入本轮的项（及理由）

| 项 | 理由 |
|---|---|
| WebRTC 真视频 | 依赖整机 mediad 信令，需用户拍板，属功能线（功能清单 B 类），非内部工程质量 |
| A2 配网 + 应用层加密 | 是功能决策（Q3 拍板），不是纯技术改进 |
| `route.rs::permits()` 对 `RobotModelApi/RemoteSessionActive/SafeToRestart` 返回 false | **固件侧**问题（fanhao API40 的 btd 路由），App 侧无法修，等整机 |
| e-stop / 账户 / 原厂 Hub 流程 | 维持不做（见功能清单 C 类），有合规边界说明 |

## 3. 建议执行顺序

1. **⑤ BLE 串行化**（不依赖整机、真机 GATT 硬前置）
2. **① ETag 条件请求**（成本最低、官方明确鼓励，先落地）
3. **② R8 发布构建**（发布质量，注意 Gson keep 规则 + 端到端负对照）
4. **③④⑥ 下载强化包**（Range 续传 + dataSync FGS + 网络库，一次做掉）
5. **⑦ DataStore**（顺带）

⚠️ 守项目铁律：软线改进再充分，整机未落地前 `ship_verdict` 仍为 `NOT_SHIPPABLE`；
每步改完必须过编译、lint、`tools/selftest.sh`、真机 59 条门禁。

## 4. 一手来源清单

**Google / Android 平台文档**
- 《Enable app optimization with R8》developer.android.com/topic/performance/app-optimization/enable-app-optimization
- 《Configuration of R8》developer.android.com/agents/skills/performance/r8-analyzer/references/CONFIGURATION
- 《前台服务类型》developer.android.com/guide/components/fg-service-types
- 《Android 14 变更：前台服务类型必填》developer.android.com/about/versions/14/changes/fgs-types-required
- 《避免使用尚未最佳化的下载内容》developer.android.com/training/efficient-downloads
- Android Developers Blog《Prefer Storing Data with Jetpack DataStore》android-developers.googleblog.com/2020/09/prefer-storing-data-with-jetpack.html
- 《SharedPreferencesMigration》API reference developer.android.com/reference/androidx/datastore/migrations/SharedPreferencesMigration

**GitHub 官方文档**
- 《Best practices for using the REST API》docs.github.com/en/rest/guides/best-practices-for-integrators
- 《发布资源的 REST API 端点》docs.github.com/en/rest/releases/assets

**工程实践（非官方，具名）**
- ZOOZ Engineering《Making Android BLE work — part 3》（Martijn van Welie）
- Punch Through《Android BLE: The Ultimate Guide to Bluetooth Low Energy》
- michaelaye.github.io《Using GitHub Releases as a Free Data CDN》（GitHub 资产 Range 206 实测）
- RFC 7232（条件请求）、RFC 7233（Range）
