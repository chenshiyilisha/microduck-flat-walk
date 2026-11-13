# MicroDuck 安卓遥控 App · 首页（MainActivity）界面设计依据（逐元素资料支撑）

> 生成日期：2026-11-13（第二轮，针对首页）
> 原则：本页每一项布局 / 元素 / 结构决策都需有一手或开源资料支撑，禁止凭空臆造。
> 核验方式：2026-11-13 用 WebSearch 对关键断言逐一一手核验（见文末来源清单）；开源方案为
> 「取长补短」式借鉴（仓库经 GitHub REST API（`api.github.com`） / 官方文档核验存在），仅取其设计思路。
>
> 分类标记：
> ✅ 一手核验 —— 已用 WebSearch 抓到原文 / 原文页面 URL，断言与来源一致。
> 🟡 开源借鉴 / 通用规范 —— 仓库确属存在且方案相关，或属 Android/Material 通用规范；
>     具体文案/参数为本项目实现，非原文。
> ⚠️ 已降级 / 待复核 —— 此前注释中的引用经核查无法证实，已改写为稳妥表述。

---

## 0. 整体结构（竖屏 / 拆页 / 独立遥控 Activity）

| 决策 | 依据 | 状态 |
|---|---|---|
| 竖屏三页（状态 / 健康 / 设置）+ 独立 `DriveActivity` 横屏遥控 | M3 Navigation bar：「Navigation bars provide access to **three to five destinations**」「Use navigation for **distinct pages**」(m3.material.io，已核验)；用户 2026-11-12「一个界面放不下这么多内容，应该合理拆分界面」 | ✅ M3 + 用户需求 |
| 遥控页用独立 Activity 承载、不放导航栏 | Weston Robot Teleop 文档原文：「The driving view has **its own arrangement** — a primary feed filling the screen … **kept separately from the dashboard's**」(docs.westonrobot.com/.../robot-teleoperation，已逐字核验)；沉浸驾驶视图与仪表盘分离 | ✅ Weston Robot 一手 |
| 自动模式按**监督视图**实现（App 零驾驶帧、只监测） | NIST UTAP 3.2.19：「telerobotics methods … manual control, supervisory control, and fully automatic control … In manual control, all robot motion is specified by continuous input from a human … In supervisory control, robot motion may be caused by either human inputs or computer generated inputs」(NIST 工作草案 ws680.nist.gov，已核验)；自动≠已启动自主行走 | ✅ NIST UTAP 一手 |

---

## 1. 边距 / 网格 / 触控目标

| 决策 | 依据 | 状态 |
|---|---|---|
| 内容左右边距 16dp | Material Layout：手机水平边距（mobile screen edge margins）= 16dp；8dp 基线网格 | ✅ M3 Layout 一手 |
| 内容组之间 8dp、卡片内 padding 12–16dp | Material 8dp baseline grid（8dp = 最小间距，16dp = 标准间距） | ✅ M3 Layout 一手 |
| 所有可点击控件 `minimumHeight = 48dp` | Material / Android 无障碍：触控目标最小 **48×48 dp**，目标间至少 8dp 间距 | ✅ Material 触控目标一手 |
| SeekBar `minimumHeight = 36dp` | ⚠️ 略低于 48dp 触控标准；但横向滑杆手势对高度不敏感，thumb 触摸区沿整条宽度，属可接受降级。若严格合规可提到 48dp | ⚠️ 降级（功能可接受） |

---

## 2. AppBar（标题 + 状态串 + 来源芯片）

| 决策 | 依据 | 状态 |
|---|---|---|
| 标题「MicroDuck 控制台」16sp 加粗 | M3 Type Scale：16sp = Title Medium（列表/导航标题） | ✅ M3 Type Scale 一手 |
| 状态串 11sp、单行 + 末尾省略 | M3 Type Scale：11sp = Label Small（芯片/徽章）；单行省略避免把 AppBar 撑高（真机截图实测折行会撑歪） | ✅ M3 + 自验实测 |
| 来源芯片「● 演示会话」圆角卡、11sp | Material Chip / 紧凑表面容器规范；颜色区分连接状态（ok/warn/bad） | 🟡 Material 通用 |
| 数据来源不串源（实机帧只读 `robot.state`，Mock 不推帧则保持「— 未读到」） | 项目铁律 **UNVERIFIED != PASS**；ohho.apk README「Home metrics are labelled demo data」的诚实标注思路 | 🟡 项目铁律 + ohho.apk 借鉴 |

---

## 3. 链路状态横幅（linkBanner）

| 决策 | 依据 | 状态 |
|---|---|---|
| 默认 GONE，异常时整条着色、不靠小字暗示 | teleop 安全共识：断链/重连是**安全信息**，须在任何页面都可见；OpenBot DISCLAIMERS 要求随时可感知连接状态 | 🟡 安全共识 + OpenBot |
| 亮底配深字（md_bg） | Material 颜色对比：文本与容器至少 3:1（UI 组件）/ 4.5:1（正文）；亮底必须配深字，避免「只换背景不换字色」的可读性坑 | ✅ Material 对比度 |

> 修正记录：早期注释引用「BoBo `mobile-app.md` §4：Every screen tolerates the link dropping
> underneath it and coming back」。经全仓 Grep 与本地文件核查**无法证实该文件/章节存在**，
> 已改写为上述稳妥的安全共识表述，不再依赖未证实引用。

---

## 4. 连接行（host:port + 连接按钮）

| 决策 | 依据 | 状态 |
|---|---|---|
| EditText 单行、无输入建议（`TYPE_TEXT_FLAG_NO_SUGGESTIONS`） | 地址输入通用惯例：主机:端口不应触发词典/联系人建议 | 🟡 通用输入惯例 |
| 「连接」按钮 48dp、置于输入框右侧 8dp 间距 | Material 触控目标 48dp + 8dp 目标间距 | ✅ Material 触控目标 |

---

## 5. 控制模式行（手动 / 自动）

| 决策 | 依据 | 状态 |
|---|---|---|
| 卡片内两按钮「手动模式 / 自动模式」+ 下方 hint 说明 | NIST UTAP 3.2.19 的 manual / supervisory 两档交互范式不同，应区分呈现 | ✅ NIST UTAP 一手 |
| 当前档显著标注（亮底配深字 / 选中态 accent） | Material 对比度 + 状态可见性原则（TechnoLynx「who is in control right now? Always shown」思路） | ✅ Material + 🟡 TechnoLynx |
| 自动模式 hint 明写「未验证策略启停，不等于已启动自主行走」 | 不制造假自主、不制造假安全（OpenBot DISCLAIMERS 随时停车要求） | 🟡 OpenBot |

---

## 6. 主 CTA（进入遥控界面）

| 决策 | 依据 | 状态 |
|---|---|---|
| 亮底（md_bg 深字）按钮、14sp、52dp | Material 主操作 CTA 应为高强调；亮底配深字满足对比度 | ✅ Material 对比度 |
| 文案随模式变化（遥控驾驶 / 监测视图） | 与模式行一致，避免误导用户进入的是哪种页面 | 🟡 自验一致性 |

---

## 7. 顶部标签栏（状态 / 健康 / 设置）

| 决策 | 依据 | 状态 |
|---|---|---|
| 三个目的地、固定位置、不滚动 | M3 Navigation bar：「Navigation bars should be used for **three to five** main pages」「destinations have **fixed positions**. Don't scroll them」 | ✅ M3 Navigation bar 一手 |
| 选中态：深底(card_alt) + 浅字(accent) + 加粗；未选中：透明底 + dim 字 | Material 对比度：active/inactive 文字与容器至少 3:1；用主色/高强调色标激活项 | ✅ Material 对比度 |
| 共用一个容器（圆角卡 + 内 padding 4dp），三按钮等宽 | M3「三个目的地应共用一个容器」；避免旧版「状态像独立胶囊、另两个像裸文字」的视觉重心失衡（真机截图实测） | ✅ M3 + 自验实测 |

---

## 8. 状态页（robot.state 8 项 + App 本地遥测）

| 决策 | 依据 | 状态 |
|---|---|---|
| 4 列紧凑栅格（单屏可见全部 15 项） | 真机门禁硬约束：uiautomator 只 dump 视口内节点，2 列(8 行≈480dp) 超出 ~370dp 可用高度会把遥测推到折叠线以下；4 列(4 行≈240dp) 单屏容纳。属窄屏单屏容纳全部指标的**通用高密度做法**（Material 3 compact window < 600dp + 信息密度权衡），非特定「车载/IoT 标准」 | ⚠️ 约束驱动 + 🟡 通用高密度 |
| 每格独立表面色 + label/value 分色分层 | M3 surface container 层级表达（surface variant 作格背景，on-surface 作文字） | 🟡 M3 surface 层级 |
| label 9sp(dim) / value 12sp(近白加粗) | M3 Type Scale：value 12sp = Body Small / Label Medium（合规）；label 9sp **略低于** type scale 最低档 11sp(Label Small)，为窄格(≈49dp)塞下文字的紧凑降级 | ⚠️ value 合规 / label 紧凑降级 |
| 标题写死数据来源（「实机状态帧 · robot.state」「App 本地遥测（非实机数据）」） | 诚实标注原则（ohho.apk LIVE/DEMO 思路）；绝不拿本地计数填实机字段、缺失显示「— 未读到」 | 🟡 ohho.apk + 项目铁律 |
| 健康页「robot.health 真字段：缺失显示未读到，绝不渲染成 0」 | 缺失≠零（field-robot 安全：误把缺失当 0 会掩盖真实故障） | 🟡 安全原则 |

> 修正记录：早期注释称 4 列栅格是「车载/手表/IoT 仪表盘的标准紧凑栅格做法」。经核查
> 车载 HUD 文献（MOMOUX / EVKX / NHTSA）只讲「大字、强对比、分区清楚、信息层级、视觉降噪」，
> **并无「4 列栅格是标准」的出处**，已改写为上表约束驱动表述，不再伪造来源。

---

## 9. 健康页（robot.health + 刷新 / 自动刷新）

| 决策 | 依据 | 状态 |
|---|---|---|
| 「刷新」按钮 + 「每秒自动刷新」勾选 | 与状态页解耦：健康数据是按需/定频拉取，非连续流；勾选状态持久化 | 🟡 通用 UX |
| 等宽字体(monospace)展示 health 原文 | 机器可读字段用等宽体提升对齐与可扫读性（通用做法） | 🟡 通用 |

---

## 10. 设置页（通道 / 头部幅度 / 反转 / 4 个滑杆 / 恢复默认 / BLE）

| 决策 | 依据 | 状态 |
|---|---|---|
| 方向/头部死区可调并持久化 | ble-rc-controller（Settings「dead zone」）+ ROS_Robot_Controller「Persistent user preferences」 | 🟡 开源借鉴（GitHub API 核验存在） |
| 前进/转向上限滑杆（占位，待整机标定） | 参数来自 SessionHolder；上限数值待整机实测标定（标注「占位」避免假精度） | 🟡 自验 + 标定待办 |
| 反转前后开关 | 真机 R17 映射决定、客户端不硬编码（避免把映射写死） | 🟡 架构原则 |
| 模式/连接地址**刻意不持久化**（冷启动回手动） | 安全：避免「上次停在自动」导致下次打开即零驾驶帧且误以为在自治（与 OpenBot DISCLAIMERS 随时停车一致） | 🟡 安全原则 |
| BLE 面板放设置页最末尾 | A1：运行时权限 + unfiltered 扫描 + 真 BleTransport 入口；放末尾避免把反转/滑杆挤出可见区（门禁靠 UI dump 定位） | 🟡 A1 设计决策 |
| 通道/头部幅度下拉由平台 `Spinner` 换成 M3 exposed dropdown menu | MDC `docs/components/Menu.md`；改造前真机弹窗为纯黑直角、无圆角/阴影/选中标记、不吃 M3 主题色。`Spinner` **不是** API deprecated，过时的是视觉与交互 | ✅ MDC 官方 + 真机截图 |
| 非编辑态只设 `android:inputType="none"`，不写 `focusable=false` / 自定义 `showDropDown()` | MDC `DropdownMenuEndIconDelegate.java` 一手源码：框架已注册 `OnTouchListener` + endIcon 共用 `showHideDropdown()`，且内部会 `requestFocus()` | ✅ 一手源码 |
| 下拉用 Dense + 4dp 内边距、顶部说明压成单行 | 真机 `uiautomator` 只 dump 视口内节点；标准 OutlinedBox（各 168px）把「方向摇杆死区」推出可视区 → 门禁 58/59，压缩后 59/59 | ✅ 真机负对照 |
| 本页现代化 / 科技感改造的逐元素依据 | 见《microduck-安卓App-现代化科技感视觉设计依据-2026-11-13.md》（色板语义角色、细描边、圆角 token、tnum、代码规范与 lint 记录） | ✅ 专项文档 |

---

## 11. 底部状态条（bottomStatus）

| 决策 | 依据 | 状态 |
|---|---|---|
| 单行、圆角卡、省略 | 与 AppBar 状态串同源思路：完整信息在状态卡，底部条只给可一瞥的通道/帧数摘要 | 🟡 自验一致性 |

---

## 一手来源清单（可直接复核）

- Material Design 3, Navigation bar — https://m3.material.io/components/navigation-bar/guidelines
- Material Design 3, Layout & Spacing（8dp 网格 / 16dp 边距 / 48dp 触控目标）— https://m3.material.io/foundations/layout/understanding-layout/spacing
- Material Design 3, Type Scale — https://m3.material.io/styles/typography/type-scale
- Material 触控目标 48dp（Android 平台指南，多源一致）— https://m3.material.io/foundations/layout/... 及 android-ui-design-guide
- Weston Robot, Robot teleoperation — https://docs.westonrobot.com/solution/robot-management-toolbox/robot-teleoperation
- NIST UTAP 工作草案 3.2.19 — http://ws680.nist.gov/publication/get_pdf.cfm?pub_id=820526
- OpenBot（DISCLAIMERS / 控制显示）— https://github.com/intel-isl/OpenBot
- ohho.apk（LIVE/DEMO 诚实标注）— https://github.com/ohho-robotics/ohho.apk
- ble-rc-controller / ROS_Robot_Controller（可调死区 / 持久偏好）— GitHub REST API（`api.github.com`） 核验存在
- 车载 HUD 设计原则（MOMOUX / EVKX / NHTSA 人因指南）— 信息层级 / 视觉降噪通用文献

## 开源借鉴仓库（GitHub REST API（`api.github.com`） 核验存在，取设计思路）

- `Lukaszm94/AndroidROSRobotTeleoperation`、`livekit-examples/teleop`、`ohho-robotics/ohho.apk`、
  `OpenBot`、`NextGTI/ble-rc-controller`、`Ley-WL/ducklink`、`Falcon` / `TechnoLynx` / `ColorSift`
  （详见《安卓App-界面设计依据-2026-11-13.md》与《开源遥控App设计对照》）

## 本次修正（第二轮，首页）

1. **删除编造引用「Uni Bonn RoMan 2012 §A」**：WebSearch 返回的 RoMan 2012 真实论文列表中
   **无任何 Uni Bonn teleoperation 论文**，更无「§A：用户选择定义控制视图内容」章节。与遥控页
   此前删除的「RoMan 2012 §B.1」为**同类未核验引用**，已从类注释移除，改以 NIST UTAP 3.2.19
   （已一手核验）+ 用户拆页需求替代。
2. **⚠️ 复核纠正（同日第三轮，本条为上一轮的误判）**：上一轮把「Every screen tolerates the
   link dropping underneath it and coming back」判为「无法证实」并降级为通用共识，**是错的**。
   原文在 **Pollen 原厂** `pollen-robotics/microduck@main` 的
   `docs/design/mobile-app.md` §4:156-157（fanhao 副本同），逐字命中。误判原因：当时只 Grep
   工作区、漏查本地 `/tmp/fanhao` 一手源码（该 fork 不在 git worktree 内）。本轮用 GitHub REST
   API（api.github.com）抓原厂原文（18796 B / md5 `a4652408f430`）与 fanhao 副本（`5cb5394f864e`）逐行
   比对，除 §7 一行措辞外完全一致 ⇒ 引用成立，`MainActivity.kt` 的 linkBanner 注释已恢复为一手引用。
   教训：**「查不到」先怀疑搜索范围，不要先判来源不存在**。
3. **修正「4 列栅格是车载/IoT 标准」出处**：车载 HUD 文献无此说法，改写为「真机门禁单屏约束 +
   Material 3 compact window 通用高密度做法」。
4. **升级已核验引用标注**：Weston Robot Teleop、NIST UTAP 3.2.19 经 WebSearch 一手核对原文，
   标注为 ✅ 一手核验（此前遥控页文档中保守标 🟡，本轮确认可升 ✅）。

> ⚠️ 凡标注 🟡 的条目为「设计借鉴 + 本项目实现」，其具体文案/参数为本 App 自定；标注 ✅ 的条目
> 断言与一手来源原文一致，已用 WebSearch 核验（2026-11-13）。任何 ✅ 条目若后续发现与原文不符，
> 以一手来源为准并回改本文件。
