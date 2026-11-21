# MicroDuck Android App：M3 整体重构 + 真扫码 + M3 弹窗（2026-11-21）

> 范围：App 无关整机签收。本文只说明 UI 结构/扫码/弹窗的一手依据、落地位置与验证边界；
> `ship_verdict=NOT_SHIPPABLE` 不变，`UNVERIFIED != PASS`。

## 1. 为什么这一轮不是继续“清文案”

用户反馈原文：

- “提示扫码，没有扫码功能”
- “提示框美化一下，现在还是用的默认提示框，就没有好用的 ui 包吗”
- “整 app 界面重构，重新布局重新设计”

所以本轮同时做三件事：

1. 把全局壳层（顶栏 / 导航 / 分组节奏）统一到 Material 3 Views 体系；
2. 把平台默认 `android.app.AlertDialog.Builder` 全部替换成 `MaterialAlertDialogBuilder` 单一入口；
3. 把“扫描配对码”从一句做不到的提示，落成真正的 QR 扫码页 + 手动粘贴兜底。

## 2. 一手资料与判决

### 2.1 顶栏 / 导航 / 弹窗

| 资料 | 一手事实 | 本项目判决 |
|---|---|---|
| Material 3 App bars（material.io/components/app-bars/guidelines） | 顶栏提供当前页内容/动作；small app bar 用于密集或滚动页；headline 要短，不截断；可含 subtitle；trailing 最多两个图标按钮 | `MainActivity` 改用 `MaterialToolbar`，品牌行 + 当前目的地标题 + 一行会话状态；右侧只保留一个来源 pill，不堆动作 |
| Material 3 Navigation bar（m3.material.io/components/navigation-bar/guidelines） | 底栏固定在窗口底部；compact/medium（<840dp）用 navigation bar，expanded 用 navigation rail；3–5 个同级目的地；选中态有 active indicator；切换是顶层导航 | 手机竖屏保留四目的地底栏并强化 active pill；横屏遥控是独立沉浸 Activity，不放底栏。大屏 rail 未实现，见边界 |
| Android Layout and navigation patterns（developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns） | navigation bar 承载 3–5 个顶层目的地；large screens 改用 nav rail；tabs/bottom app bar 是次级导航 | 状态 / 健康 / 设置 / 终端四个目的地保持顶层；不把 BLE/Wi‑Fi/固件拆成更多 tab |
| Material 3 Dialogs（m3.material.io/components/dialogs/specs；m2.material.io/go/android-dialogs） | 基本对话框容器 28dp 圆角、surfaceContainerHigh、24dp padding，宽 280–560dp；Views 官方实现是 `MaterialAlertDialogBuilder`；Dialog 是中断式，只用于阻断型确认 | 新增 `AppDialogs.confirm/input` 作为全 App 唯一入口；写操作统一从它出，保留 M3 按钮顺序与色板 |

### 2.2 扫码库选择

| 方案 | 一手事实 | 判决 |
|---|---|---|
| ML Kit Barcode Scanning（developers.google.com/ml-kit/vision/barcode-scanning/android） | bundled 模型构建时静态链接，约 +2.4 MB，立即可用；unbundled 约 +200 KB，但通过 Google Play services 动态下载，首次可能要等下载 | 选 bundled：国内机型不依赖 GMS，扫码是低频但必须可用 |
| CameraX MLKitAnalyzer（developer.android.com/media/camera/camerax/mlkitanalyzer） | `CameraController + PreviewView + MlKitAnalyzer` 是官方推荐；Analyzer 处理 ImageAnalysis 与 PreviewView 的坐标变换；可只启用 `FORMAT_QR_CODE` | `PairScanActivity` 用 `LifecycleCameraController` + QR-only BarcodeScanner |
| ZXing Android Embedded（journeyapps GitHub README） | IntentIntegrator 接入代码少、纯本地；但自带 CaptureActivity 视觉是旧式扫描界面，且本 App 要 M3 顶栏/状态栏一致性 | 不采用；若 bundled 模型镜像长期不可用，再降级到 ZXing 核心 + 自绘预览（需另开门禁） |

依赖镜像实测（2026-11-21）：阿里云 google 源 `camera-{core,camera2,lifecycle,view,mlkit-vision}:1.4.2` 与
`com.google.mlkit:barcode-scanning:17.3.0` 的 POM/AAR 均 HTTP 200；本机 `dl.google.com` 曾 TLS 超时，沿用现有镜像。

## 3. 代码落点

- `app/src/main/kotlin/io/microduck/app/ui/AppDialogs.kt`
  - `confirm(...)`：M3 图标 + 标题 + supporting text + 正/负按钮；`Tone` 控制 info/warn/danger。
  - `input(...)`：M3 `TextInputLayout` 输入框，只用于手动粘贴配对码。
- `app/src/main/kotlin/io/microduck/app/ble/PairScanActivity.kt`
  - 只在用户主动点击后请求 CAMERA；拒绝或初始化失败都回到手动输入兜底。
  - `MlKitAnalyzer` 识别 QR 后只回传 `EXTRA_SCAN_VALUE`，不解析、不存 PSK、不落盘、不上传。
- `BleConnectPanel`
  - 新增“扫码导入配对码”“手动输入”两个次级按钮；
  - QR / deep link / 手动粘贴三条入口统一进入 `BlePairingStore.parsePairingUri`，避免判据漂移。
- `MainActivity`
  - `buildAppBar()` 改 `MaterialToolbar`；品牌 / 页面标题 / 会话状态 / 来源 pill 一次呈现；
  - 四个顶层目的地、状态页 UDF 消费链、健康页 3D 模型与门禁硬串原样保留。
- Manifest：CAMERA 权限 + `PairScanActivity`（`exported=false`）+ camera feature `required=false`。
- `tools/check_ui_modernization.py`：结构门禁；`tools/check_firmware_ota.py`：确认框语义门禁。

## 4. 验证与边界

- 离线门禁：`check_ui_modernization.py --selftest` 8/8；`check_firmware_ota.py --selftest` 7/7。
- 编译：见提交前最后一次 `:app:assembleDebug / :app:assembleRelease / :app:lintDebug` 结果。
- 真机 QR 扫码、相机权限弹窗、Noise 握手、PIN 门、配网后 IP 回填仍 `UNVERIFIED`；
  本轮只证明扫码入口代码与编译链存在，不能替代真机扫真二维码。
- 大屏 navigation rail 未实现：当前目标是手机竖屏 + 独立横屏遥控页；平板/桌面需要另做自适应布局。
- 平台默认弹窗在 debug-only AI Receiver 或系统组件中不适用；本门禁只约束 App 自身 Kotlin 源码。
