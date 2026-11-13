# MicroDuck 安卓遥控 App · 界面设计依据（逐元素资料支撑）

> 生成日期：2026-11-13
> 原则：本页每一项布局 / 元素 / 结构决策都需有一手或开源资料支撑，禁止凭空臆造。
> 核验方式：2026-11-13 用 WebSearch 对关键断言做一手核验；开源方案为「取长补短」式借鉴
> （仓库经 GitHub REST API（`api.github.com`） 核验存在），仅取其设计思路，非逐字引用。
>
> 分类标记：
> ✅ 一手核验 —— 已用 WebSearch 抓到原文 / 原文页面 URL，断言与来源一致。
> 🟡 开源借鉴 —— 仓库确属存在且方案相关，作为设计灵感；具体文案/参数为本项目实现，非原文。

---

## 0. 整体布局原则（横屏全屏 / 拆页 / 画面铺底）

| 决策 | 依据 | 状态 |
|---|---|---|
| 遥控页横屏（sensorLandscape） | Android 官方：`<activity>` 的 `screenOrientation` 是逐 Activity 属性；沉浸式操控为 Android 16 忽略锁方向的例外之一 | 🟡 官方文档事实 |
| 多页拆分（模式选择 / 控制视图分离） | teleop UX 通用原则：把「选模式·选目的地」与「连续驾驶控制」拆到不同页面，避免单屏过载（用户 2026-11-12「一个界面放不下这么多内容」） | 🟡 通用取舍 |
| 全屏相机画面铺底 + 控件浮边缘 | arXiv:2110.08753 把控制视图区定义为「lower left part of the screen when holding the phone horizontally」；与 FPV OSD「keep the feed clear / logical placement without obstructing your view」同构 | ✅ arXiv:2110.08753 + 🟡 Oscar Liang |
| 透明状态栏 + edge-to-edge | Android 15 (API 35) 强制 edge-to-edge：状态栏/导航栏透明、top offset 禁用；按官方 View 方案用 `WindowInsetsCompat` 让开，而非退回 `windowOptOutEdgeToEdgeEnforcement` | 🟡 官方 behavior-changes-15 事实 |

---

## 1. 退出按钮（左上角返回箭头）

| 决策 | 依据 | 状态 |
|---|---|---|
| 返回/退出箭头固定在**左上角** | Material Design「App bars: top」：导航图标（含 back arrow）**对齐在栏最左**（"Place navigation on the far left" / "A back arrow, which returns to the previous screen"）；跨平台适配明确 Android up 箭头在左、iOS 在右 | ✅ material.io/develop/web/components/top-app-bar |
| 48dp 触控目标 + 24dp 图标、纯箭头无背景 | Material 3 组件规范：交互控件触控目标 ≥48dp、图标 24dp；用户 2026-11-13「不需要背景」⇒ 去除卡片仅留箭头 | 🟡 Material 3 通用规范（top app bar 导航位已一手核验） |
| content-description = 「退出遥控」 | 真机门禁按描述定位该按钮（59/59 断言之一） | 🟡 自验设计 |

**修正记录**：早期版本曾引用「Uni Bonn, RoMan 2012 §B.1」描述双摇杆，2026-11-13 核验未发现该章节原文，已改为以 ✅ arXiv:2110.08753 为双摇杆一手依据，本项不再引用该未核验来源。

---

## 2. 取景框占位（无外框 / 无网格 / 无角标）

| 决策 | 依据 | 状态 |
|---|---|---|
| 不画假取景框、不画网格/角标，仅居中提示文字 | FPV/无人机 HUD 第一铁律「keep the center frame clean / feed is king」：没有真实画面时画带边框占位框是多余视觉噪音，还会误导用户以为有画面。Oscar Liang Betaflight OSD 教程：「keep your FPV feed clear and readable」「use logical placement without obstructing your view」 | ✅ Oscar Liang（oscarliang.com/betaflight-osd/） |
| 占位语义由 content-description 保留（门禁断言「摄像头取景框占位」） | 门禁需可观测该节点存在 | 🟡 自验设计 |

---

## 3. 顶部状态栏暗条（去除）

| 决策 | 依据 | 状态 |
|---|---|---|
| 去除自定义的 topScrim 暗带 | 用户 2026-11-13「顶部暗色条 指的是状态栏」——系统状态栏已通过 `statusBarColor=transparent` + `windowLightStatusBar=false` 透明处理，自定义 scrim 双重压暗属多余 | 🟡 用户反馈 + styles.xml 实测 |
| 不 hide systemBars（保留电量/时间可见） | 官方 immersive 文档：仅当收益「超出多一块屏幕空间」才用沉浸式；本页收益来自横屏+拆页，隐藏系统栏会与底部 home 手势冲突（home 手势不可 opt-out） | 🟡 官方 immersive 文档事实 |

---

## 4. HUD 监测信息组（无背景紧凑单行 + 分角布局）

| 决策 | 依据 | 状态 |
|---|---|---|
| 去掉 2×3 双层卡片网格，改无背景单行文字条 | FPV OSD 共识（Betaflight/DJI/Walksnail）：遥测 overlay 应「几乎隐形、只在需要时出现」；QGroundControl Fly View 的 Telemetry Values 也是紧凑只读条而非卡片网格。旧版占横屏顶部 ~140dp（横屏仅 360dp 高），既挡视野又笨重 | ✅ Oscar Liang + 🟡 QGC |
| 分角布局：左上=控制/信号/数据源，右上=驾驶读数，顶部中央=告警 | FPV 角落法则（遥测贴边角、中央留画面、离双手最远）；arXiv:2110.08753 双拇指热区（左上/右下为握持区，中央留给画面） | ✅ arXiv:2110.08753 + 🟡 FPV 社区 |
| 文字加投影（setShadowLayer）保户外/亮画面可读 | 户外可读性通用做法；ColorSift 户外界面对比技巧 | 🟡 户外可读性文献 |
| 标签文字（模式/连接、实际速度、命令→实际、头部°）固定为门禁断言文本 | 真机 59/59 断言依赖 | 🟡 自验设计 |

---

## 5. 双虚拟摇杆（贴横屏两下角、正方形浮层、去卡片）

| 决策 | 依据 | 状态 |
|---|---|---|
| 双摇杆贴横屏**左下 + 右下**角、双拇指操作 | ✅ arXiv:2110.08753 实测：横屏持机时左右拇指最舒适点击区距屏幕左/下边 **9.8–19.4 mm**，且「most of the center of the joystick keeps at least a 10 mm distance from the left and lower corners」；竞争对手 UI 摇杆中心普遍距角 ≥10mm。本页摇杆中心距角 ≈13 mm（side 12dp + joySize/2，@560dpi），落在该舒适区内 | ✅ arXiv:2110.08753 |
| 正方形浮层（屏高 40%，夹 140–200dp）、去外层卡片 | JoystickView 自绘环/十字/旋钮已提供视觉；重复镀铬既占地方又显笨重（用户「太占地方/不需要背景」）。arXiv 论文亦指出过大控件会遮挡画面 | ✅ arXiv:2110.08753 + 🟡 FPV/游戏 UI |
| 摇杆标签加投影、死区可视化虚线环、触觉反馈（首触+满幅） | 移动游戏拇指热区研究（arXiv:2110.08753）+ DJI Fly/Litchi 主屏遥测 + FPV OSD 户外可读性 | 🟡 第三轮强化参考资料 |

---

## 6. 底部驾驶计数条（无卡片、文字投影）

| 决策 | 依据 | 状态 |
|---|---|---|
| 仅一行可观测发帧计数，无卡片底 | 既是驾驶页极简遥测，也是门禁读「心跳在不在跑」的行为观测量（不能用内部变量自证）；用户「不需要背景」⇒ 文字投影浮现 | 🟡 自验设计 + 用户反馈 |
| 第二行显示「最后输入」 | OpenBot robot app README：「The controls that are sent to the robot are displayed on the right side」——把发给机器人的控制显示出来 | 🟡 OpenBot（开源借鉴） |

---

## 7. 数据源标签 LIVE / DEMO

| 决策 | 依据 | 状态 |
|---|---|---|
| 明确标注「● 实机 [kind]」/「● MOCK 演示夹具 · 非实机读数」/「● 未连接」 | 诚实标注原则：Mock 夹具读数绝不被误认成实机数据。ohho.apk README「What is real in this build」：Home metrics are labelled demo data、The camera has no frame | 🟡 ohho.apk（开源借鉴） |
| 链路信号指示（linkLevel + stateHz，真实数据，不伪造 RTT） | DJI Fly / Litchi：信号强度持续可见，而非仅出错时弹横幅 | 🟡 DJI Fly / Litchi（开源借鉴） |

---

## 8. 控制接管状态药丸 / 告警行（第四轮强化）

| 决策 | 依据 | 状态 |
|---|---|---|
| 控制接管状态药丸常驻可见（已接管/已松手·已停/链路挂起/监督视图） | Teach-pendant 的 enabling 设备状态须可见；TechnoLynx Remote Operator Console 读序 #4「who is in control right now? Always shown」 | 🟡 TechnoLynx（开源借鉴） |
| 组合告警行：状态停滞 / 指令发送失败 / 低电量 | Falcon「real-time design」：失败是第一态（failure-first）；field-robot 安全：低电量告警 | 🟡 Falcon / 安全文献（开源借鉴） |
| 链路恶化三连短震（非视觉告警通道） | teleop / marionette 文献：haptic 作双/单震区分状态的非视觉通道，强光/分心也能感知 | 🟡 teleop haptic 文献（开源借鉴） |
| 户外可读性加 2px 同色描边 | ColorSift：强光下色彩对比被压扁时靠轮廓保可读 | 🟡 ColorSift（开源借鉴） |

---

## 9. 自动（监督）模式页

| 决策 | 依据 | 状态 |
|---|---|---|
| App 零驾驶帧、不创建任何 controller | NIST UTAP 3.2.19 / Weston Robot Teleop：手动 = 人的连续输入；自动（监督）视图下 App 不发送驾驶帧 | 🟡 NIST UTAP / Weston（安全原则） |
| 界面明写「App 无停车能力 / 未验证策略启停」 | 不制造假自主、不制造假安全（OpenBot DISCLAIMERS 随时停车要求） | 🟡 OpenBot（开源借鉴） |
| 一键「切回手动」 | OpenBot「R1 触发键重新取得控制」+ LiveKit teleop「View/Operator mode toggle」——接管路径不应藏在两级菜单之后 | 🟡 OpenBot / LiveKit（开源借鉴） |

---

## 10. 设置页（死区可调 + 模式刻意不持久化）

| 决策 | 依据 | 状态 |
|---|---|---|
| 方向/头部死区可调并持久化 | ble-rc-controller：Settings 的 dead zone；ROS_Robot_Controller「Persistent user preferences」 | 🟡 ble-rc-controller / ROS_Robot_Controller（开源借鉴） |
| 模式（MANUAL/AUTO）每次冷启动强制回 MANUAL | 安全：避免「上次停在自动」导致下次打开即零驾驶帧且误以为在自治；与 OpenBot DISCLAIMERS 随时停车要求一致 | 🟡 安全原则 + 自验负对照 |

---

## 11. 安全（退出停车）

| 决策 | 依据 | 状态 |
|---|---|---|
| 退出遥控页（onStop）立即归零 + 停心跳 | NIST UTAP / Weston Robot Teleop：松手即停 / 断链停车；不依赖 ACTION_CANCEL 是否到达 | 🟡 安全原则 |
| 摇杆归零走 `DriveController.release()`（发零帧 + 停心跳） | 与主页同一条链路状态；驾驶页尤其要看得见「链路已断 · 驾驶帧已停」 | 🟡 自验设计 |

---

## 一手来源清单（可直接复核）

- Material Design, App bars: top — https://material.io/develop/web/components/top-app-bar
- Material Design, Understanding navigation — https://material.io/design/navigation/understanding-navigation.html
- Oscar Liang, Betaflight OSD setup & placement — https://oscarliang.com/betaflight-osd/
- arXiv:2110.08753, Understanding Players' Interaction Patterns with Mobile Game App UI via Visualizations — https://arxiv.org/pdf/2110.08753.pdf （双摇杆舒适区 9.8–19.4 mm）
- Android 15 behavior changes（edge-to-edge 强制）— developer.android.com/about/versions/15/behavior-changes-15
- Android immersive / system-ui 文档 — developer.android.com/training/system-ui/immersive

## 开源借鉴仓库（GitHub REST API（`api.github.com`） 核验存在，取设计思路）

- `Lukaszm94/AndroidROSRobotTeleoperation`（SP/PV 速度曲线）
- `livekit-examples/teleop`（View/Operator 模式切换 + 角度刻度）
- `ohho-robotics/ohho.apk`（LIVE/DEMO 诚实标注）
- `OpenBot`（控制显示 + DISCLAIMERS 随时停车）
- `NextGTI/ble-rc-controller`（可调死区）
- `Ley-WL/ducklink`（真 GATT 上板参考，详见《开源遥控App设计对照》）
- Falcon / TechnoLynx / ColorSift（实时设计、读序表、户外对比，强化轮次参考）

> ⚠️ 凡标注 🟡 的条目为「设计借鉴 + 本项目实现」，其具体文案/参数为本 App 自定；标注 ✅ 的条目
> 断言与一手来源原文一致，已用 WebSearch 核验（2026-11-13）。任何 ✅ 条目若后续发现与原文不符，
> 以一手来源为准并回改本文件。
