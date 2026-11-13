# MicroDuck 安卓 App · 现代化 / 科技感视觉改造设计依据（逐元素资料支撑）

> 生成日期：2026-11-13
> 原则：界面每个元素 / 布局 / 结构 / 设计决策都要有资料支撑，禁止臆造；引用必须一手核验，
> 查不到就删或降级，不写想当然的章节号与引文。
> 触发需求：用户「界面做的现代化一点，科技感一点，找找参考资料」+「再检查一下写的代码是否符合代码规范」。
>
> 分类标记：
> ✅ 一手核验 —— 抓到原文 / 解包本地 AAR 逐项实证 / 逐字命中官方源码。
> 🟡 通用规范或项目约定 —— 方向有依据，具体数值/文案为本项目实现。
> ⚠️ 已降级 / 待复核 —— 原文无法核验，已从注释中删除或明确改写。

---

## 0. 改造范围与结论

| 项 | 改造前 | 改造后 | 依据 |
|---|---|---|---|
| 主题色板 | 8 个裸 hex，主题只映射 `colorPrimary` | 补齐 M3 语义角色 + 五级 tonal surface + outline | ✅ M3 Color roles / 本地 AAR attr 实证 |
| 卡片/容器 | 纯色块堆叠、16dp 圆角 | 1dp 细描边 + 20dp 圆角 + 分层表面 | ✅ M3 outline 角色 + HUD「Borders Over Fills」 |
| 实时数值 | 比例数字，刷新时左右抖动 | `tnum` 等宽数字 + 具名字距 | ✅ AndroidX `tabularNum()` 一手源码 |
| 设置页下拉 | `android.widget.Spinner`：纯黑直角弹窗、无选中标记、不吃主题色 | M3 exposed dropdown menu：OutlinedBox + 浮动 label + 分层弹窗 + 选中高亮 | ✅ MDC Menu.md + 本地 javap + 真机截图 |

**结论**：`Spinner` **没有**被 Android 平台标记为 API deprecated；过时的是它的**视觉/交互**
（平台老式弹窗），不是 API 可用性。替换依据是 MDC 官方菜单规范，不是「已废弃」的误判。

---

## 1. 色板：语义角色 + tone-based surface + 深色主题

| 决策 | 依据 | 状态 |
|---|---|---|
| `colorSurfaceContainerLowest/Low/Container/High/Highest` 五级映射 | 解包 `material-1.12.0.aar/res/values/values.xml` 逐个 grep，五个 attr 均存在 | ✅ 本地 AAR 一手 |
| 深灰而非纯黑、高层级表面更亮、有限面积强调色、WCAG AA 4.5:1 | Google Material Design「Dark theme」(material.io/design/color/dark-theme.html)：「Use dark grey – rather than black – to express elevation and space」「Higher elevation, lighter surface」「Apply limited color accents in dark theme UIs」 | ✅ 官方原文 |
| 主题固定深色、不用 DayNight | 本地 AAR 实证 `Theme.Material3.DayNight.NoActionBar` parent 是 Light；`Theme.Material3.Dark.NoActionBar` 链到 `Theme.MaterialComponents`（MaterialCardView / TextInputLayout 需要该祖先） | ✅ 本地 AAR 一手 |
| `outline` / `outlineVariant` 用于 1dp 描边与分割线 | M3「Color roles」：outline = borders & dividers；配合 HUD 参考「Borders Over Fills — thin luminous borders define panels」 | ✅ M3 + HUD 参考 |
| 状态色：青 nominal / 琥珀 caution / 红 critical / 绿 confirmed | Sci-Fi Interface 设计参考「Color is purely functional」「Luminance Over Hue」；本项目既有 4 色与之逐一对应，故保留色值 | ✅ 参考原文 + 项目既有 |

> ⚠️ **引用降级**：初稿曾引用「Introducing Tone-based Surfaces in Material 3」并转述五级
> container 的推荐语。2026-11-13 复抓该页（会重定向到 `m3.material.io/blog/...`）**只得到页面
> 标题**，正文为 JS 渲染无法逐字核验 ⇒ 已删除转述，改以上面「本地 AAR 五个 attr」为证据。

---

## 2. 形状：细描边 + 大圆角

| 决策 | 依据 | 状态 |
|---|---|---|
| 卡片 1dp `outlineVariant` 描边、取消纯色块堆叠 | HUD 参考「Borders Over Fills」「Hierarchy Through Luminance」+ M3 outline 角色 | ✅ 参考原文 |
| 主容器 / 按钮 / 输入框统一 20dp 圆角 | MDC 1.12.0 AAR 实测组件圆角 `m3_navigation_drawer_layout_corner_size=16dp`、`m3_carousel_small_item_default_corner_size=28dp`；20dp 取同一量级 | 🟡 量级有一手实证，数值为项目约定 |
| 圆角 / 描边 / 字距 / `tnum` 抽成具名 token，不散落裸值 | Kotlin 官方 coding conventions（不可变常量命名、可读性）+ 可维护性：改一处全局生效 | ✅ Kotlin 官方 + 工程约定 |

> ⚠️ **引用降级**：初稿注释写「M3 Expressive 2025-05：Added corner radii tokens,
> Large increased (20dp)」。核验发现 `m3.material.io/styles/shape/overview` 是 JS 页抓不到
> 原文，且本地 AAR 中**没有** 20dp 的通用 shape token（`mtrl_shape_corner_size_large_component`
> 实为 0dp）⇒ 已删除该引文，20dp 明确降级为「本项目约定值」。`m3_corner_large` 资源名
> 只表示风格取向，不是官方 token 名。

---

## 3. 排版：等宽数字与微字距

| 决策 | 依据 | 状态 |
|---|---|---|
| 实时读数 `fontFeatureSettings = "tnum"` | Android 平台 `TextView.setFontFeatureSettings` 支持 `tnum`；AndroidX `LayoutElementBuilders.FontSetting.tabularNum()` 官方 API 文档与 cs.android.com 一手源码原文：「all numeral characters will have the same width. This corresponds to tnum OpenType feature.」 | ✅ 官方 API + 一手源码逐字 |
| 标题 / 标签微字距 0.08f / 0.05f / 0.04f | 参照 HUD 参考的小标签加字距方向 | 🟡 方向有依据，数值为项目约定（不声称规范值） |
| 只改字形宽度、不改任何文本 | 真机门禁 59 条断言依赖固定文本子串 | ✅ 门禁硬约束 |

> ⚠️ **引用纠偏（张冠李戴）**：初稿把「Use tabular figures so digits do not jitter …」这句
> 挂在「控制站排版一手文献 Falcon」名下。复核 `falcon.so/resources/design-basics/real-time-design`
> 原文**没有**这句话——该文献讲的是「make loss visible immediately / a frozen value that still
> looks live」，是 DriveActivity 状态停滞告警的依据，不是数字排版 ⇒ 该引文已删除，改用上面的
> AndroidX 源码。`DriveActivity.kt` / `SessionHolder.kt` 里既有的 Falcon 引用经这次复核**有效**，保留。

---

## 4. 设置页下拉：Spinner → M3 exposed dropdown menu

| 决策 | 依据 | 状态 |
|---|---|---|
| 用 `TextInputLayout` + `MaterialAutoCompleteTextView` 替换平台 Spinner | MDC `docs/components/Menu.md`：「The exposed dropdown menu is implemented through the TextInputLayout.」；平台 Spinner 弹窗真机截图为纯黑直角、无圆角/阴影/选中标记、不吃 M3 主题色 | ✅ 官方文档 + 真机截图 |
| 样式 `Widget.Material3.TextInputLayout.OutlinedBox.Dense.ExposedDropdownMenu` | 本地 AAR values.xml 实证该样式存在且含 `endIconMode=dropdown_menu`；Dense 为紧凑表单变体 | ✅ 本地 AAR 一手 |
| 浮动 label 由 `setHint()` 注入、`setText(text, false)` 设默认值 | Menu.md「Non editable variation」「Setting a default value」两节逐字核验 | ✅ 官方文档 |
| `app:simpleItems` / `dropDownBackgroundTint` / `simpleItemSelectedColor` / `popupElevation=3dp` | Menu.md 属性表；本地 `javap material-1.12.0.aar` 实证 `setSimpleItems(String[])`、`setDropDownBackgroundTint(int)` 等签名 | ✅ 官方文档 + 本地 javap |
| **非编辑态只设 `android:inputType="none"`**，不写 `keyListener=null` / `isFocusable=false` / 自定义 `showDropDown()` | MDC `DropdownMenuEndIconDelegate.java` 逐行核验：`setUpDropdownShowHideBehavior()` 已注册 `OnTouchListener`（ACTION_UP → `showHideDropdown()` 开/关切换）、endIcon 复用同一路径、`showHideDropdown()` 内 `requestFocus() + showDropDown()`；`isFocusable=false` 会破坏焦点态/无障碍路径，另挂「只弹不关」的 OnClickListener 会与框架 toggle 语义打架 | ✅ 一手源码 |
| Dense + `paddingTop/Bottom=4dp` + 顶部说明压成单行 | 真机 `uiautomator` 只 dump 视口内节点：标准 OutlinedBox 两个下拉各 168px，把「方向摇杆死区」标签推出设置页可视区 `[1590,2594]` ⇒ 门禁 58/59。压缩后该标签回到 `[2515,2567]`，门禁 59/59 | ✅ 真机实测负对照 |

> 弹窗容器形状沿用 MDC `popupMenuBackground` 默认值，本项目只改 tint / elevation / 选中色，
> 不自定义形状（避免无依据地改官方组件）。候选项文案一字未改，门禁可见文本零改动。

---

## 5. 负向决策（明确不做）

| 不做 | 原因 |
|---|---|
| 扫描线 / 雷达扫描 / 呼吸动画等"科幻装饰" | M3「Don't compromise clarity for the sake of visual design」；且 `uiautomator dump` 要求连续 1000ms 无 Accessibility 事件（`UiAutomation.waitForIdle`），持续动画会让门禁死锁 |
| 伪造遥测值 / 假 RTT / 假视频 | 项目铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`，缺字段一律显示「未读到」 |
| 改门禁 59 条断言文本或放宽判定 | 门禁是黑盒验收；本轮 58/59 是靠压缩 UI 修复，不是改断言 |
| 把「模式/地址持久化」等安全文案做成静态装饰 | 安全信息必须可见；压缩时把完整依据移到代码注释与本文档，不丢信息 |

---

## 6. 代码规范检查记录（用户本轮要求）

对照 Kotlin 官方 `kotlinlang.org/docs/coding-conventions.html`（2026-11-13 抓取逐项）与 Android
Gradle 插件自带 lint：

| 检查项 | 结果 |
|---|---|
| 命名：函数/属性 lowerCamelCase， deeply immutable 常量 SCREAMING_SNAKE_CASE | ✅ 合规；**已修** `CHANNEL_ITEMS/HEAD_RAD_ITEMS` 原为可变 `arrayOf` 却用全大写 ⇒ 改 `listOf` 不可变 List |
| `val` 优先、表达式体、trailing comma、companion object 位于类末、无 wildcard import | ✅ 合规 |
| import 顺序 android → androidx → com → 项目包 | ✅ 合规 |
| `buildDropdown` 返回 `Pair` 后用 `.first/.second` | ✅ **已修**为解构 `val (view, input) = ...` |
| 函数参数 `hint` 与属性 `root.hint` 同名遮蔽 | ✅ **已修**为 `label` |
| 裸数值：20 散落 12 处、`dp(1)` 5 处、`"tnum"` 5 处 | ✅ **已抽**为 `CORNER_*_DP` / `STROKE_HAIRLINE_DP` / `TABULAR_FIGURES` / `TRACKING_*`，XML 侧对应 `@dimen/m3_corner_large` / `m3_stroke_hairline` |
| Android lint `InflateParams`：`inflate(layout, null)` | ✅ **已修**为 `inflate(layout, parent, false)`；负对照 **39 → 38 warnings，InflateParams 归零** |
| lint 全量 | ✅ **0 errors / 38 warnings**；本轮新代码 0 条，其余 38 条为既有欠账（图标 15、`SetTextI18n` 5、`ObsoleteSdkInt` 5 等），因门禁文本依赖且非本轮引入，未动 |

> lint 起初跑不通：`dl.google.com` TLS 握手失败 / 20s 超时（用户开代理后复测仍 HTTP 000，
> 环境变量无 proxy）。实测 `maven.aliyun.com/repository/google` 的 `core-ktx/1.2.0.pom`、
> `lint-gradle/31.9.1.pom`、`AGP gradle/8.9.1.pom` 均 HTTP 200 ⇒ 在 `settings.gradle.kts`
> 把该镜像置顶、保留 `google()` 兜底，lint 才真跑出报告。**未验证前不写 PASS**。

---

## 7. 验证记录

| 验证 | 结果 |
|---|---|
| `./gradlew assembleDebug`（JDK17） | rc=0 |
| `./gradlew :app:lintDebug` | rc=0，0 errors / 38 warnings（负对照 39→38） |
| `tools/selftest.sh` | **283 passed, 0 failed** |
| 真机 `adb install -r -g`（vivo V2338A / Android 16） | Success |
| `tools/device_ui_check.py` 首轮 | **58/59**，FAIL「设置页含持久化说明与可调死区」（死区标签被新下拉推出视口） |
| 修复后复跑 | **59 passed / 0 failed**，rc=0 |
| 真机截图对比 | 弹窗由纯黑直角 → 深蓝分层表面 + 选中高亮；输入框 OutlinedBox + 浮动 label + 青色下拉箭头，与深蓝圆角卡片统一 |

> 真机一开始枚举不到设备（`adb devices` 空、Windows PnP 状态 Unknown），`adb kill-server`
> + `start-server` 后恢复；**不是代码问题，也不是假绿**。

---

## 8. 仍 UNVERIFIED（不得写成 PASS）

沿用《microduck-安卓App-整机落地验收清单-2026-11-13.md》：真机 GATT 上板、后台保活、
断链恢复提示、真视频、策略启停、手感标定均待整机；本轮视觉改造**不消除**这些悬案，
`ship_verdict` 仍为 `NOT_SHIPPABLE`。

---

## 一手来源清单（可直接复核）

- Google Material Design, Dark theme — https://material.io/design/color/dark-theme.html
- Google Material 3, Color system / Color roles — https://m3.material.io/styles/color/system/overview
- Google Android Developers, Dark theme — https://developer.android.com/develop/ui/views/theming/darktheme
- Google Material, Learn About Tone-based Surfaces in Material 3 — http://m3.material.io/blog/tone-based-surface-color-m3/ （⚠️ 仅标题可核验，正文 JS 渲染未取到，故未引用）
- MDC-Android, Menus（含 Exposed dropdown menu / Non editable variation / Setting a default value / 属性表）— https://raw.githubusercontent.com/material-components/material-components-android/master/docs/components/Menu.md
- MDC-Android, `DropdownMenuEndIconDelegate.java` — https://raw.githubusercontent.com/material-components/material-components-android/master/lib/java/com/google/android/material/textfield/DropdownMenuEndIconDelegate.java
- Android Developers, `LayoutElementBuilders.FontSetting.tabularNum()` — https://developer.android.google.cn/reference/androidx/wear/protolayout/LayoutElementBuilders.FontSetting
- AndroidX 一手源码（同上方法的 Javadoc 原文）— https://cs.android.com/androidx/platform/frameworks/support/+/androidx-main:wear/protolayout/protolayout/src/main/java/androidx/wear/protolayout/LayoutElementBuilders.java
- Falcon, Real-time design（**仅用于状态停滞告警，非数字排版**）— https://falcon.so/resources/design-basics/real-time-design
- Sci-Fi Interface Design Aesthetic Reference（状态色 / Borders Over Fills / Luminance Over Hue）— https://chrislemke.github.io/website_designs/examples/Sci_Fi_Interface.html
- Kotlin Coding conventions — https://kotlinlang.org/docs/coding-conventions.html
- 本地一手实证：`com.google.android.material:material:1.12.0` AAR（`res/values/values.xml` + `classes.jar` 经 `javap`）
- 本地一手实证：Android SDK `android-35/android.jar` 的 `TextView.setFontFeatureSettings` / `setLetterSpacing`
