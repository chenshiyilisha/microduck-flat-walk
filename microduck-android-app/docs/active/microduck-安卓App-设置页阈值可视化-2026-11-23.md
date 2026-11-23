# MicroDuck Android App：设置页滑块危险阈值可视化（2026-11-23）

> 范围：App 离线 UI 完善，与整机签收无关。`ship_verdict=NOT_SHIPPABLE`、`UNVERIFIED != PASS` 不变。
> 用户诉求「先完善 App，真机测试后面再说」；本轮把最后一版 HTML 基准稿 5 个设计点里
> 唯一没落地的「设置·阈值可视化」补齐，不做真机联调。

## 1. 差距从哪来（不靠记忆判断）

逐项比对基准稿 `docs/active/microduck-安卓App-最优界面设计-最后一版HTML基准稿-2026-11-20.html`
的 5 个设计点（状态 / 健康 / 设置 / 终端 / 横屏）：

| 设计点 | 落地状态（读代码确认） |
|---|---|
| 状态页：主次分明、缺字段显示 `--` | 已落地 |
| 健康页：部位分组 + ToF 8×8 色带 legend | 已落地（`renderToF` / `TofSnapshot.zone`） |
| **设置页：滑块危险阈值可视化** | **未落地** —— `accentSeekDrawable()` 背景仍是单色 `md_outline_variant` |
| 终端页：底部悬浮 + 快捷键横滑 | 已落地 |
| 横屏遥控：摇杆中性灰 | 已落地（11-20） |

基准稿原文（设置页 note）：「滑块右侧超过 70% 的区域底色变红，提示操作者此区间的高风险」，
CSS 为 `linear-gradient(90deg, primary 0%, primary 70%, bad 70%, bad 100%)` —— 即 70% 处**硬切**。

## 2. 一手资料与判决（先查再动手）

| 资料 | 一手事实 | 本项目判决 |
|---|---|---|
| m3.material.io/components/sliders/specs | Slider 只定义 active / inactive track、handle、stop indicator、value indicator；**无「危险区」token** | 危险区是本项目基于 M3 色板的**自定义视觉扩展**，类注释与本文均声明，不冒充官方规范 |
| developer.android.com SeekBar/LayerDrawable（`setId(@android:background / @android:progress)`） | progressDrawable 用 LayerDrawable 分层、progress 层用 ClipDrawable 是按比例着色的标准结构 | 保留该结构，只替换 background 层为分段 Drawable；进度 fill 与手势零改动 |
| 社区实现（SeekBar 多色渐变，StackOverflow/指南一致做法） | 「clip 的 on drawable 叠在 off drawable 上」是通用方案 | 采用同构方案；用胶囊 `clipPath` 保证两段共用外轮廓、切点不凹陷 |

⚠️ 数值安全上限**不**从这条视觉线推导：真正的 clamp 在 `SettingsStore`（MAX_VX=0.80 /
MAX_VYAW=2.50 / MAX_DEADZONE=0.30，写入即 `coerceIn`）。UI 红线只是提示，判据独立于被测量。

## 3. 代码落点

- 新增 `app/src/main/kotlin/io/microduck/app/ui/ThresholdTrackDrawable.kt`
  - `DANGER_FROM = 0.7f` 单一权威切点；`dangerTint()` 把 `md_bad` 压到 alpha 0.35。
  - `draw()`：胶囊 `clipPath` + 按 `bounds.width * dangerFrom` 硬切两段填色；
    前段安全色（`md_outline_variant`）、后段警示色（低透明 `md_bad`）。
- `MainActivity.accentSeekDrawable()`：background 层由单色 `GradientDrawable` 换成
  `ThresholdTrackDrawable`；progress 层 `ClipDrawable` 与 thumb 不变。影响 4 条滑块
  （前进上限 / 转向上限 / 方向摇杆死区 / 头部摇杆死区）。
- `tools/check_ui_modernization.py`：新增第 6 组判据（分段类 + 单一权威切点 + 按比例两段着色 +
  胶囊裁剪 + 接入 SeekBar + 低透明警示色），负对照试验列表提为模块级 `TRIALS` 单一权威，计数不再写死。

## 4. 验证与边界

- `check_ui_modernization.py --selftest` **13/13**（12 个改坏试验全部变红，含切点 0.7→0.9、
  比例计算换成常数、不接进滑块、警示色去透明、去掉胶囊裁剪）。
- 全量离线门禁 `check_all_app_gates.py`：**ALL_PASS**；core 自检 725/725。
- 三构建：`assembleDebug / lintDebug / assembleRelease` 全绿（首次 `packageDebug` 因
  junction 路径 `E:\WorkBuddy` vs `E:\WorkBuddyData\WorkBuddy` 增量 dex 缓存不一致报
  `No file known for: classes.dex`，`clean` 后重跑通过）。R8 kotlin-metadata warning 是
  AGP/R8 版本兼容提示，非 error、非本次新类引入。
- ⚠️ 真机视觉未确认：手机无线 adb 不在线、无 AVD；按用户要求真机测试留后。门禁锁的是
  **结构 + 常量 + 算法**，不等于截图目视。要在真机核对：设置页 4 条滑块的后 30% 是否为淡红、
  进度 fill 是否盖在其上清晰可见。
- 大屏 navigation rail、危险区随数值动态变色（非本次范围）均未做。
