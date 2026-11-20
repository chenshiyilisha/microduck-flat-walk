# MicroDuck 安卓 App · 最优界面设计（两稿融合裁决）· 2026-11-20

_输入：用户提供的两份 UI 评审稿（稿一「全局性问题 + 五页」、稿二「跨页优先改 + 分页面 + 刻意不做 + 三周路线」）。_
_方法：逐条对照一手源码（MainActivity.kt / DriveActivity.kt / SshPanel.kt / styles.xml）裁决，不照单全收_
_——凡是会打破门禁硬串或数据诚实性的建议，改造采纳或明确否决。_
_铁律：`UNVERIFIED != PASS`；缺数据一律「未读到」/「--」，绝不默认 0/绿；`ship_verdict=NOT_SHIPPABLE` 不因 UI 改版变化。_

---

## 0. 结论先行：三条裁决铁律

两稿方向一致（减负、分组、保命、去 AI 味），但有几处互相冲突或与代码事实/项目铁律冲突。先立三条裁决铁律，后面所有条目按此判：

1. **不回到全屏卡片化。** 11-19 刚以一手资料（standoutmcp「card around everything / three equal cards」= 反模式）把卡片全拆成 1px ruled rows。稿一的「三个 Card / 卡片化分组」和稿二的「给设置/健康加卡片背景」**不采纳字面**：改用「分区标题 + 1px 边界 + 局部浅底 section」实现"分组容器"的诉求，视觉是 ruled rows 不是浮卡。稿二「刻意不要做：不要全屏卡片化」优先。
2. **安全件必须是真功能，不做假按钮。** 全仓（App + 固件 + 上游）无硬件 E-Stop/`estop` 命令；App 唯一停车能力 = `DriveController.release()/stop()` 发 `robot.move` 全零帧 + 停心跳（`DriveController.kt:84-114`，死循环靠 deadman 500ms 兜底）。故「紧急停止」做成**「制动」（软件）按钮**，按下 = 强制归零 + 停心跳 + 触觉/视觉确认，界面**明写「软件制动，不替代物理急停」**（一手依据 CSDN 机器人交互工程指南：界面急停只发指令、链路故障时会失效，不能替代断主回路的物理急停）。
3. **门禁硬串与诚实性不可牺牲。** 59 条 `device_ui_check` 依赖固定文案/content-desc（见 §5），稿二「未读到全部隐藏/换 --」在**横屏 HUD**可全改（那里无门禁），但在**状态页/健康页首屏**只能降视觉权重、折叠次要项，主断言文案原样保留。空态只在「整块无数据源」时启用，且必须写「未读到/未订阅」不写 0。

---

## 1. 两稿逐条裁决表

| # | 稿一/稿二建议 | 裁决 | 依据（代码 / 一手资料） |
|---|---|---|---|
| 1 | 状态页三 Card、设置页卡片化分组 | **改造采纳**：分区标题 + 1px 边界 + 局部浅底 section，无浮卡 | 11-19 去卡片化决策；稿二「刻意不做」；Material Settings「divider group related settings」 |
| 2 | Mock 状态不醒目 → 贯穿全屏高对比条 | **采纳**：复用 `linkBanner` 机制，Mock/未连接时常驻琥珀条 | `renderLinkBanner()` `MainActivity.kt:371-388` 已有全宽横幅 |
| 3 | 每页有大标题+两行副标题，浪费 | **事实纠正 + 部分采纳**：`chrome` 全局唯一一份（`MainActivity.kt:228-245`，四页共享，不重复）。采纳「收简」：标题去 `MicroDuck ·` 前缀、缩到 14f；副标题折成状态 pill + 摘要 | 源码实证，稿一「每页重复」不成立 |
| 4 | 未读到大面积 → 空状态/折叠 | **分场景采纳**：横屏 HUD 全改 `--`；状态/健康页整块无数据源才显空态，个别缺字段仍「未读到」但降权 | 门禁硬串 + `UNVERIFIED != PASS`；Material Empty states「subtle neutral image + tagline」 |
| 5 | 深色对比度不足、卡片偏暗 | **部分采纳**：`md_text_dim #9C978C` 实测对 `#121110` 已过 AA（≈6:1），无需提亮正文；只把「未读到」降权用更淡 muted 而非提亮 | WCAG 4.5:1 正文 / 3:1 大字；styles.xml 注释已声明过 AA |
| 6 | 进入遥控按钮太长、对比弱 | **采纳**：文案缩「进入遥控」（保留 desc `进入遥控界面`）；主填充品牌色、minHeight 56dp | `launchButton` `MainActivity.kt:504-511,1563`；主填充唯一 |
| 7 | 健康 15 舵机渐进披露（腿/颈→展开） | **采纳**：默认按 3 组折叠为「良好/警告/离线」汇总，点组展开 5 舵机 | NNG 渐进披露；`buildServoGrid()` `L1054-1092` |
| 8 | ToF 占位大、无色阶 | **采纳**：无帧折叠成一行「等待 ToF 帧」；有帧才显 8×8 + 色阶图例 | `renderToF()` `L1024-1052` 已有近红远蓝色阶，缺图例与小化 |
| 9 | 刷新系统信息藏太深 | **采纳**：健康页分区标题右侧放描边「刷新」，不新增悬浮按钮（避免多一个主按钮） | `L908-910` 现按钮位置 |
| 10 | 3D 插画保留并联动健康高亮 | **采纳为 P2**：`DuckModelView` 已按 report 着色（`renderMonitor L1582`），补点击部位→展开对应舵机组 | `DuckModelView` `L831-834` |
| 11 | 设置页分组（操控/硬件/关于）、警告 Banner、滑块实时值 | **全采纳**：分区 section；明文警告改暗红底 Banner（保留 `PLAINTEXT_TRANSPORT_WARNING` 逐字）；滑块实时值**已有**（`updateSettingLabels L1485-1490`）无需重做 | Material Settings；`L1199,1348-1351` |
| 12 | 终端连接后表单折叠、等宽、#0D1117、> 提示符、快捷按钮统一 | **采纳**：连接后收起输入行；`outputText` 设 monospace、底 `#0D1117`；快捷命令 ghost 描边、横向；「启动 updaterd」已二次确认保留 | `SshPanel.kt:265-273,311,218-229` 现状=默认字体+冷蓝底 |
| 13 | 横屏摇杆去彩色/激活才高亮、视频铺满、E-Stop、数据牌、READY 中心 | **全采纳（P0）**，E-Stop 按铁律 2 做软件制动；视频未接入用信息占位而非纯黑；HUD 改半透明数据牌 | `DriveActivity.kt` 全页；FPV OSD「中心留空」与稿二「中心不空」冲突→未接入时中心放**半透明 READY/制动态**，不堆数据 |
| 14 | 字阶收敛、空态降权、按钮层级、组件统一 | **采纳**：title16/section12/body13/label11/caption10；空态 muted；每屏单一主填充、其余 outlined；输入统一 outlined | 11-19 字阶表已定，两稿一致 |
| 15 | 按压反馈（缩放/透明度） | **有条件采纳**：仅触觉反馈（已有 `vibrator`）与非主按钮 ripple；**不加呼吸/扫描/位移动画**（uiautomator 1000ms 静默窗 + 11-19 负向决策） | `DriveActivity.kt:465-476` 已有 haptic |

**明确否决**：① 全屏卡片化/玻璃拟态/霓虹扫描线/呼吸动画（两稿自己也说不要，且违反 11-19 决策与门禁静默窗）；② 把物理急停写进 UI 能力宣称（无此命令，造假）；③ 首屏「未读到」全部隐藏（打破门禁与诚实性）。

---

## 2. 全局设计系统（一次定义，五页复用）

### 2.1 顶栏（`chrome`，全局唯一一份）
```
[Mock/未连接 高对比警示条 —— 仅异常态常驻，复用 linkBanner]
MicroDuck                        [● MOCK 状态pill]  ← 标题 14f 去"·状态"
已连接MOCK · 手动 · READY · 0帧 → 收简为:  ● MOCK · 手动 · 0帧   ← 11f dim
```
- 状态 pill：连接态一枚（Mock=琥珀、实机=绿、未连接=灰），点击展开详情（帧率/READY/会话，渐进披露）。
- 警示条只在 Mock/断链时出现，实机正常连接不占高度。

### 2.2 色板（沿用 styles.xml，不新增 hex）
`md_bg #121110` / `md_card #1C1B19` / `md_card_alt #26241F` / `md_text #E8E6DF` / `md_text_dim #9C978C` / `md_accent #6E9BB5` / `md_warn #C7A052` / `md_ok #6EA483` / `md_bad #CE6A63`。
section 浅底 = `md_card`；边界 = `md_outline #3E3B34` 1px；「未读到」muted 用 `md_text_dim` 再降透明度到 ~70%（仍 ≥ AA 需实测，取 `Color.argb` 不新 hex）。

### 2.3 字阶（收敛 5 档，删 9.5/8.5）
| 档 | 大小 | 用途 | 字重/字形 |
|---|---|---|---|
| title | 16f | 页面主标题（仅必要处） | BOLD |
| section | 12f | 分区标题 | BOLD |
| body | 13f | 数值/主要读数 | BOLD + `tnum` |
| label | 11f | 标签/次要 | 普通 |
| caption | 10f | chip/图例/脚注 | 普通 + `tnum` |

### 2.4 组件规则
- 分区 section：上方 12f BOLD 标题 + 内容 + 底部 1px `md_outline`，**无圆角浮卡、无阴影**。
- 主按钮：每屏唯一 filled（`launchButton`/制动键），56dp；次操作 outlined 描边 44dp；危险/低频（启动 updaterd/恢复默认）保持二次确认。
- 输入：统一 outlined；滑块：accent 单色 + 右侧实时数值。
- 空态：一行灰色说明（「等待状态帧」/「等待 ToF 帧」）+ 中性小图标，不铺满、不拟人插画抢眼。

---

## 3. 分页面落地规范（绑定代码位置）

### 3.1 状态页（`buildStatePage` `MainActivity.kt:653`）
- 连接区：折叠摘要（已连接默认收起），展开才显地址输入。
- 控制 section：单一主填充「进入遥控」（desc 不变）→ 1px 线 → 休息/站立描边次级。
- 实机状态 section：`robot.state` 8 格 ruled rows；**无状态帧时整块折叠**为一行「等待状态帧 · 当前无状态帧」（保留门禁串），有帧才展开 8 格。
- 本地遥测 section：**默认折叠**（渐进披露），标题含门禁硬串「App 本地遥测（非实机数据）」不动。

### 3.2 健康页（`buildHealthPage` `L810`）
- 顶部：来源声明（门禁串不动）+ `DuckModelView` 3D 模型（视觉锚点，P2 补点击部位联动）。
- 硬件状态：3 组（左腿 20–24 / 颈 30–34 / 右腿 10–14）默认折叠为汇总条「良好/警告/离线」，点击展开 5 舵机点（P1）。
- ToF：无帧→一行「等待 ToF 帧 · 真机需 mediad WebRTC（btd 拒绝 tof.stream）」；有帧→8×8 热力 + 近红远蓝图例（P1）。
- 诊断：分区标题右侧描边「刷新系统信息」；文本缺字段仍「未读到」但降权；协议内部名不新增外露。

### 3.3 设置页（`buildSettingsPage` `L1302`）
- 三 section：遥控参数（下拉/开关/4 滑块，实时值已有）/ 连接与配网（BLE + Wi-Fi）/ 关于与更新。
- 明文警告：「⚠ + `PLAINTEXT_TRANSPORT_WARNING`」改暗红底 Banner（左竖条 + 图标），逐字不软化。
- Wi-Fi 写按钮两列并排（现状已改），主 CTA 唯一。

### 3.4 终端页（`SshPanel.kt`）
- 未连接：输入区为主，快捷命令/启动 updaterd 弱化。
- 已连接：输入行 `cmdRow` 收起为单行窄条，输出区 `outputScroll` 撑满。
- 输出区：`outputText.typeface = MONOSPACE`，底色 `#0D1117`（替 `#0A1626`），加 `> ` 提示符由 `terminal.render()` 输出侧处理（不改真机返回内容）。
- 快捷命令 4 按钮：统一 outlined ghost、横向可滑，「启动 updaterd」维持二次确认且不再用琥珀填充抢眼。

### 3.5 横屏遥控页（`DriveActivity.kt`）—— P0 重点
- **制动键**：底部中央两摇杆之间，红色圆键「制动」（约 60dp，明显小于两侧摇杆，靠颜色与居中醒目而非体积），按下 = `driveJoystick.forceRelease()` + `headJoystick.forceRelease()` + `drive?.release()` + 三连震 + 按钮态变「已制动」；下方常驻小字「软件制动 · 不替代物理急停」。与现有 onStop/松手即停语义一致，不造假能力。
- **摇杆**：去蓝/橙彩色，统一中性灰描边环；当前按下那只高亮（激活环），松手回中性；低电量/告警时区域泛红（复用 `alertLine`）。`joystickOverlay()` `L525-566`。
- **视频占位**：`PreviewPlaceholderView` 未接入时不再是纯黑——放一个中性占位（简洁图形 + 「摄像头未接入」一行），中心留白给停车/READY。
- **HUD 数据牌**：右上 6 格改半透明底单行牌，未读到用 `--`（HUD_LABELS 门禁串不动，`L772-773`）。
- **READY 中心标识**：复用 `armedPill`，「已松手·已停」态在屏幕中心给淡绿「● 已制动 / READY」，接管时自动消失。现 `armedPill` 在左上角 `L186-190`，新增一个中心 TextView 镜像其状态（不改原 pill 断言）。

---

## 4. 落地路线（按收益排序，每阶段独立可验）

| 阶段 | 内容 | 触及文件 | 验证 |
|---|---|---|---|
| **P0 保命手感** | 制动键 + 摇杆中性化 + 视频占位 + HUD 数据牌 + READY 中心 | `DriveActivity.kt`、`JoystickView`（如需） | `assembleDebug` + 真机横屏截图 + `device_ui_check` 59/59 |
| **P1 减负分组** | 状态/健康空态折叠、舵机渐进披露、ToF 图例、设置 Banner、顶栏收简 + Mock 警示条 | `MainActivity.kt`、`main_vm` | core 自检 + 门禁 59/59 + 各页截图目视 |
| **P2 精细** | 终端等宽/#0D1117/折叠、字阶清理、按压 ripple、3D 点击联动 | `SshPanel.kt`、`DuckModelView`、`styles.xml` | 同上 + 终端页截图 |

每阶段结束独立提交，不跨阶段混改；任何一步门禁变红立即停，回退该步。

---

## 5. 门禁硬串（改造时逐字保留，改名必红）

- `content-desc`：`进入遥控界面` / `标签页状态|健康|设置|终端` / `手动模式` / `自动模式` / `退出遥控` / `方向摇杆` / `头部摇杆` / `链路状态横幅` / `控制接管状态` / `快捷命令 $label` / `写操作 启动 updaterd（默认关闭，需二次确认）` / `执行命令`
- 首屏断言文案：`进入遥控` / `实机状态帧` / `已本地持久化` / `方向摇杆死区` / `robot.health 真字段：缺失显示「未读到」，绝不渲染成 0` / `当前无状态帧` / `App 本地遥测（非实机数据` / `Mock 演示夹具 / 非实机读数` / 下拉候选 `JSON-RPC（TCP/仿真）`、`UDP netpad（真机 :4210）`、头部幅度 `0.5/1.0/2.5 rad`
- 常量：`NetProvisioning.PLAINTEXT_TRANSPORT_WARNING` 逐字不软化。

---

## 6. 验证计划（UNVERIFIED != PASS）

- 静态：`.venv-mjlab` 解释器跑 `core selftest`（本轮 662/662 基线）与 `tools/check_all_app_gates.py` ALL_PASS。
- 编译：`assembleDebug` / `lintDebug`。
- 真机：`device_ui_check.py` 59/59 + 各页截图目视（**横屏页必须真机看**：色板、制动键、HUD 对比度、无动画静默窗）。
- 负对照：①制动键按下后 `sentCount` 停涨/发帧归零（读 `counterText`），改坏须红；②Mock 警示条 Mock 态必现、实机态必隐；③空态在「有帧」时必须让位给真实网格。
- 诚实性：所有「未读到/--」不得随改造变成 0 或绿；E-Stop 文案不得宣称物理制动。
- 交付判定：P0–P2 全绿 + 真机目视通过前，`ship_verdict=NOT_SHIPPABLE` 不变（唯一杠杆仍是整机落地）。
