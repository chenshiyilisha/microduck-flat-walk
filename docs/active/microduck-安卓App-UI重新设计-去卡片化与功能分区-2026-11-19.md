# MicroDuck 安卓 App · UI/布局重新设计依据（2026-11-19）

_目标：更现代、去「AI 味」、少卡片块与边距、功能分区位置合理。_
_约束：不碰任何门禁断言文案 / content-desc；不碰数据来源真实性（UNVERIFIED != PASS）。_

## 0. 现状诊断（真机截图 2026-11-19，`build/uiredesign/before/01_state.png`）

| 症状 | 具体表现 | 归类 |
|---|---|---|
| 卡片套卡片 | 状态页 = 圆角大卡，里面 8 个圆角小卡；控制区大卡里再套分隔线与两个按钮行 | 反模式「A card around everything / Three equal cards」 |
| 圆角过大且统一 | 20dp 主容器 / 12dp 单元格，全屏同一种圆润感 | 反模式「Rounded everything」 |
| 边距层层叠加 | 根 16dp + 页间 8dp + 卡内 16dp + 行间 8dp，实际内容被挤到窄条 | 反模式「Excessive whitespace」 |
| 主按钮过多 | 连接 / 进入遥控 / 手动 / 自动 / 一键休息 / 恢复站立 —— 6 个填充态按钮抢同一层级 | 反模式「Every button primary」 |
| 冷蓝 + 高饱和青 | 底色偏冷 #0D1015，主色 #5BA3D4 在深底上像默认科技模板 | 反模式「cyan-on-dark / default palette」 |

## 1. 查到的资料（分级标注）

### A. 一手页面（本次 WebFetch 逐字核验，2026-11-19）

1. **standoutmcp.io《How to fix a vibe-coded UI: the AI-slop checklist》**（updated 2026-06-16）
   - 原文："A card around everything — Borders and shadows on all things flatten the hierarchy." → fix: **"Group with whitespace and 1px rules. Cards only for real elevation."**
   - 原文："Three equal cards — The most templated row on the web." → fix: **"Zig-zag, bento, or ruled rows."**
   - 原文："Pure black (#000) backgrounds — Reads harsh, not premium." → fix: "Use off-blacks like **#101013** or **#1B1F22**."
   - 原文："One accent on a neutral base. Never a purple-to-blue gradient."
   - 流程："Break the center, replace the three-card row, and **vary section rhythm** so it does not repeat the same block."

2. **skillcraft.cloud《Frontend Design — Anti-Slop Edition》**（2026-04-05）
   - "**Warm over corporate.** Dark backgrounds should feel like a room at night, not a SaaS dashboard. Use **brown-blacks (#12110f)** over pure blacks. **Warm grays over cool grays.**"
   - "**Borders > shadows.** Subtle 1px borders create structure without the floaty feeling of box-shadows."
   - "**Content density over whitespace theater.** ... natural spacing (4/8/12/16px increments), not massive gaps."
   - "**Rounded-lg maximum.** ... Subtle rounding (8px) feels intentional. Excessive rounding feels like a template."
   - "**One accent color, used sparingly.** ... only for primary actions and active states."
   - 暗色参考色板：bg `#12110f` / surface `#1e1c18` / border `#33302a` / text `#e8e4dc` / muted `#8a8578`。
   - 组件："**Outlined style for secondary** (border + text color). Filled style for primary."

### B. 平台规范（仓库既有 2026-11-13 一手核验，见 `docs/active/microduck-安卓App-现代化科技感视觉设计依据-2026-11-13.md`）

- Material 3 Color roles：组件只用 `surface / surfaceContainer* / outline / onSurface*`，禁止硬编码 hex。
- Material 3 Dark theme：深灰而非纯黑表达层级，限色强调，状态色降饱和过 WCAG AA。
- M3 Navigation bar：3–5 目的地用底部导航；distinct pages 才用导航，不是每屏复制卡片。
- NNG / Apple HIG 渐进式披露：低频配置按需展开。
- ⚠️ 上述 A 类为**社区设计经验**（非 Google 官方规范），只作审美判据；B 类才是平台硬约束。二者不冲突时以 B 为准。

## 2. 设计决策（相对旧版的具体改动）

| 维度 | 旧 | 新 | 依据 |
|---|---|---|---|
| 底色 | 冷灰 #0D1015 | 暖近黑 #121110（tinted off-black） | A1 off-black；A2 warm over corporate |
| 表面 | 卡片全用 md_card + 1dp 描边 | 页面**无外层卡**；层级靠 1px 分隔线 + 暖灰表面差 | A1 ruled rows / cards only for elevation；A2 borders > shadows |
| 圆角 | 20dp 主卡 / 12dp 格 | 12dp 主控件 / 8dp 格 / 6dp chip | A2 rounded-lg max；M3 shape 量级 |
| 网格 | 每格独立圆角小卡 | **ruled rows**：无填充、底部 1px 线分列，文字靠字重/颜色分层 | A1 three-equal-cards → ruled rows |
| 按钮 | 6 个填充态 | 每屏 **1 个**主填充（进入遥控）；模式=分段描边，休息类=描边次级 | A2 one accent / outlined secondary |
| 行距 | 16+8+16+8 四层叠加 | 4/8/12/16 四档，section 之间 1px 线 | A2 content density |
| 字阶 | 8.5/9/10/11/12/13/14/16 混杂 | 收敛到 title 16 / section 12 / body 13 / label 11 / caption 10；等宽只给数字与 chip | A2 ≤4 sizes；M3 type scale |

### 保留项（不许动）

- 状态语义色（cyan nominal / amber caution / red critical / green confirmed）：机器人监控控制台的**功能色**，非装饰色；只降饱和不删除。
- DuckMesh 模型本体色（奶油白壳 / 橙 trim）：物理外观，core 自检锁定。
- 门禁文案与 content-desc：`手动模式 / 自动模式`、`进入遥控界面`、`标签页状态/健康/设置`、`实机状态帧`、`当前无状态帧`、`App 本地遥测（非实机数据`、`已本地持久化`、`方向摇杆死区`、`扫描附近 BLE 设备`、`BLE 连接`、`robot.health`、`Mock 演示夹具 / 非实机读数` 等。
- 数据来源真实性：缺字段一律「未读到」，绝不默认绿 / 填 0。
- 不引入动画 / 扫描线 / 呼吸灯：`uiautomator` 1000ms 静默窗硬约束。

## 3. 页面重排

```
顶部：标题 + 单行状态（无卡片轮廓，仅 1px 下边界）
状态页：整页单一 ScrollView（连接 → 控制 → 实机状态 → 遥测，连续滚动，不再有内层小滚动窗）
连接：折叠摘要行 / 展开输入行（已连接默认折叠）
控制：分区标题「控制」→ 模式分段（描边）→ 单一主按钮 → 分隔线 → 休息次级按钮（描边）
状态：分区标题「实机状态帧 · robot.state」→ ruled rows 4 列 → 分隔线 →「App 本地遥测」→ ruled rows
健康：来源声明 → 3D 模型 → 分区标题「硬件状态」→ ruled rows 5 项 → 15 舵机 ruled grid → 诊断
设置：分区标题「遥控参数」→ 下拉/开关/滑杆 → 分隔线 →「连接与配网」（BLE + Wi-Fi）→「更新」
终端：SshPanel 原样（不属于本次视觉范围，功能面板）
底部：4 目的地常驻，图标+文字居中对齐、选中态强调色 + 2px 指示条，不再套整条大圆角卡
```

### 3.1 追加修正（2026-11-19 用户实测反馈）

1. **底部导航图标没跟文字对齐**：`TextView` 默认 `MATCH_PARENT` 宽导致文本左对齐，
   而固定宽度图标被 `gravity=CENTER` 居中 ⇒ 文字偏左。修法：标签自身 `gravity=CENTER`
   + `LayoutParams(WRAP, WRAP)`，图标/文字/指示条三者同轴居中。
2. **状态页底部信息挤在一小块区域滑动**：旧版把监测数据塞进 `weight=1f` 的内层
   ScrollView（页面里套滚动小窗）。修法：整页单一 ScrollView，连接/控制/监测同面连续滚动。
   一手依据 Android 官方 ScrollView 文档「Never add a scrollable view inside another
   scroll view」+ Material scrolling patterns（一个目的地 = 一个连续滚动面）。
3. **图标粗糙**：手绘填充路径改为统一 2dp 描边线性图标（趋势图 / 心形 / 滑杆 / 终端），
   笔宽一致、几何规整，对齐用户给的参考风格（蓝色系单色线性图标）。

## 4. 验证计划

- 静态：`tools/selftest.sh`（core 640）、`tools/check_all_app_gates.py` ALL_PASS（**须用
  `.venv-mjlab` 解释器**，系统 Python 缺 mujoco/密码学依赖会假红）。
- 编译：`assembleDebug` / `lintDebug`。
- 真机：`device_ui_check.py` 61/61 + 各页截图目视核对。
- ✅ **本轮最终状态（2026-11-19，无线 adb）**：静态 core 640/640 + 统一门禁 ALL_PASS、
  `assembleDebug` 绿；**真机 `device_ui_check.py` = 61 passed / 0 failed**
  （`build/uiredesign/device_gate_settings.log`，无线 `192.168.0.15:5555`，含冷启动模式回退、
  SharedPreferences 真读回、全生命周期无崩溃等所有负对照）。
  - 状态页最终截图：`build/uiredesign/after/`（整页单一 ScrollView + 线性图标）；
  - 设置页改前/改后：`build/uiredesign/settings_before/{top,scroll1}.png` →
    `build/uiredesign/settings_after/{real_top,mid,scroll1,scroll2}.png`。
  - 中途 USB 掉线（CM_PROB_PHANTOM）已改用无线 adb 绕过，不再是阻断点。
- 负对照：把卡片/描边改回旧值，目视必须能看出差异；门禁断言文本任一被改必须变红。

## 5. 设置页重排（2026-11-19 追加，用户反馈「太乱了」）

### 5.1 真机诊断（`build/uiredesign/settings_before/top.png` + `scroll1.png`）

| 症状 | 截图实据 | 归类 |
|---|---|---|
| 三明治标题 | 「连接与配网·BLE/Wi-Fi」下又套「BLE 连接（运行时权限·真 GATT 未上板验证）」；「软件更新·GitHub Releases」下又套「版本与更新·GitHub Releases」 | Material settings「Section titles should be specific / avoid repeating words」反例 |
| 调试文本外露 | 标题带 `(net.status / scan / connect / forget)`；状态区 `【当前连接 net.status】`、`【附近网络 net.scan】`；边界说明 `（configd/nm.rs:585）` | 协议内部名甩给用户，非产品化文案 |
| 按钮层级混乱 | 全页描边次级按钮里夹一个亮蓝填充「扫描附近 BLE 设备」 | A2「Outlined for secondary, filled for primary」违例 |
| 说明重复 | `（占位，待整机标定）` 连着 4 行各出现一次 | NNG 渐进披露反例（同一句重复 N 次） |
| 按钮纵向堆叠 | Wi-Fi 的「连接（写操作·明文）」「忘记该网络（写操作）」两个全宽按钮上下叠 | 无主次、占高 |

### 5.2 一手资料（本次查验）

- **Material Design《Settings》模式页**（`m1.material.io/patterns/settings.html`，2026-11-19 WebSearch 命中，一手规范）：
  - "Settings should be **well-organized, predictable, and contain a manageable number of options**."
  - "**Use divider lines to group together several related settings. Avoid using dividers between each individual setting.**"
  - "Section titles ... should be **specific, avoiding ambiguous names**."
  - "**Labels** ... start with the most important text ... avoid repeating words from the section title."
  - "Show the most important or frequently used settings upfront."
- **Android Developers 中文《设置》模式页**（`developer.android.google.cn/design/ui/mobile/guides/patterns/settings`，同日核验）：
  - 「将设定分组成较小的相关群组。在群组之间使用视觉或内在的容器和标题，**而非个别项目**。」
  - 「如果有 15 个以上的设定,请将相关设定分组至子画面。」（本页约 12 项，未达阈值，保持单页分组）

### 5.3 落地改动

| 项 | 改前 | 改后 |
|---|---|---|
| 分区标题 | 外层套 BLE/Wi-Fi/更新三个同义 sectionTitle | 删除外层，子面板自带具体标题（BLE 连接 / Wi-Fi 配网 / 版本与更新）为唯一标题 |
| Wi-Fi 标题 | `Wi-Fi 配网（net.status / scan / connect / forget）` | `Wi-Fi 配网` |
| 状态区 | `【当前连接 net.status】` | `当前连接` |
| 附近网络 | `附近网络（net.scan · 点选填入 SSID）` | `附近网络 · 点选填入 SSID` |
| 固件边界 | `（configd/nm.rs:585）` | `（固件 nm.rs:585）` |
| 占位说明 | 4 行各带 `（占位，待整机标定）` | 滑杆组上方一行统一说明 + 各标签只留数值 |
| BLE 按钮 | 亮蓝填充 | 描边（与全页次级按钮同层级） |
| Wi-Fi 写按钮 | 两个全宽纵向堆叠 | 两列并排「连接·明文 / 忘记网络」 |
| 子面板卡底 | BLE/更新各套圆角卡 | 撤卡底，改 1px 分隔线分区 |

🔴 **门禁硬串未动**：`已本地持久化`（标题内）、`方向摇杆死区`（滑杆标签内）、`BLE 连接`、`扫描附近 BLE 设备`（content-desc）全部原样保留；明文警示常量 `PLAINTEXT_TRANSPORT_WARNING` 逐字未软化。
