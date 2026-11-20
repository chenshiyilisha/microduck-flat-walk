# MicroDuck Studio 手机中控（`/m`）借鉴核证与判决（2026-11-19）

_起因：用户给 `https://github.com/7757/fanduck` 并描述「microduck-replica：Microduck Studio 网页中控，手机浏览器就能配网、标定、遥控」，要「看看有什么值得借鉴参考的」。_
_约束：一手源码优先（GitHub raw 逐字，不取搜索摘要）；区分「我们已经做了 / 值得补 / 不该抄」；不因借鉴就推翻刚全绿的 UI 重设计。_

## 0. 先正名：用户给的链接与「网页中控」不是同一个仓

| 对象 | 仓库 | 实际形态 | 证据 |
|---|---|---|---|
| 用户给的链接 | `7757/fanduck` | **制作资料仓**（BOM / 打印件 / 板件 / 3D 工作台），无网页中控代码 | GitHub API `contents/` 根目录，2026-11-19 一手核对 |
| 描述中的「Studio 网页中控」 | `fanhao375/microduck-replica`（master，~1740★） | `software/studio/` 下有 PC 版 + **手机版 `/m`** | GitHub API `contents/software/studio/web`，README + PR #52 |

→ 结论：可借鉴对象是 `fanhao375/microduck-replica` 的 `software/studio/web/m/`，不是 `7757/fanduck`。

## 1. 一手资料（2026-11-19 逐行核证，路径绑 `fanhao375/microduck-replica@master`）

| 文件 | 关键行 | 逐字要点 |
|---|---|---|
| `web/m.html` | 6–7 | `<meta name="color-scheme" content="light">` / `theme-color #F2F2F7` —— 手机壳走**浅色 iOS 风** |
| `web/m/app.js` | 3 | 「同一个 Studio 进程、同一个 `/ws`、同一套 `pad.op` 命令，只是换了一副为竖屏手机做的壳」 |
| `web/m/app.js` | 15–16 | `STALE_MS = 1500`（超 1.5s 算读不到）/ `GREY_MS = 1000`（超 1s 数值变灰） |
| `web/m/app.js` | 18–24 | 5 个 tab 图标全为线性 SVG（总览 / 语音 / 手柄 / 模型 / 更多） |
| `web/m/app.js` | 28–34 | `TABS = 总览·语音·手柄·模型·更多`；「五个 tab 全部是内部路由，底栏始终留在原位」 |
| `web/m/app.js` | 54–65 | 顶栏常驻「卸力」按钮，`aria-label="卸力：让所有舵机松掉力气"` |
| `web/m/app.js` | 154–155 | `live = conn open && st && now - stAt < STALE_MS`；`age = now - stAt` |
| `web/m/app.js` | 166–173 | `doEstop()` 直接 `link.cmd('relax')`，单点就发 |
| `web/m/app.js` | 199–205 | 断连 banner + 重连按钮；失联提示「N 秒没收到状态，站着走的鸭子会自己停下」 |
| `web/m/mobile.css` | 7–26 | token：底 `#F2F2F7` / 卡 `#FFFFFF` / 三级文字灰 `#1D1D1F·#6E6E73·#A1A1A6` / 品牌黄 `#F5B400` / 危险红 `#D70015` / tabbar 58px + `safe-area` |
| `web/m/mobile.css` | 71 | 注释：「**卸力：跟桌面同一个命令（relax），单点就发，不弹二次确认——急停多一次点击就是少一条命**」 |
| `web/m/mobile.css` | 93 | `stroke-width: 1.7`（线性图标统一笔宽） |
| `web/m/mobile.css` | 95–96 | 选中态 `::after` 顶部 `20×3px` 圆角指示条 |
| `web/m/mobile.css` | 336–339 | `.m-kv` 键值行用 1px `border-top` 分组 + `tabular-nums` |
| `web/m/more.js` | 10–17 | 切热点前先把热点信息存本机（「切热点会把这台手机的连接断掉，可能收不到后端的状态和回执」） |
| `web/m/more.js` | 19–26, 180–188 | 「这一版没重做的页」列出 6 页入口，并**明说**「其余是桌面版 Studio 的页面…只是没按手机重新排过」 |

## 2. 判决矩阵（对照我们刚落地的 UI 重设计）

| Studio 做法 | 我们对应现状 | 判决 |
|---|---|---|
| 线性图标统一笔宽 1.7、选中态顶部指示条 | 本轮已改 2dp 描边线性图标 + 2px 指示条 | ✅ **已做，方向互证**（独立项目同样选择，说明不是 AI 味臆造） |
| 键值行用 1px 细线分组、`tabular-nums` | 本轮状态/健康页 ruled rows + `TABULAR_FIGURES=tnum` | ✅ **已做，方向互证** |
| 单一强调色 + 三级文字灰阶 | 本轮暖近黑 + accent `#6E9BB5`，`md_text`/`md_text_dim` 两级 | ✅ 已做（我们按硬件控制台加状态语义色，比它多一层，合理） |
| 断连 banner + 重连按钮 + **失联时「鸭子会自己停下」明确告知** | 状态行显示「0 帧」，但**主页无「N 秒没收到状态」类时效提示**；驾驶页有「状态停滞 Xs」（`DriveActivity:694`） | 🟡 **可补**：把驾驶页已有的停滞检测抬到主页状态行，与 Studio 同构（详见 §3） |
| 状态新鲜度分级 1000ms 灰化 / 1500ms 失效 | `DriveViewModel.stateFrameAgeMs` 存在但驾驶页才用 | 🟡 **可补**：主页读数增加「陈旧即灰」判据，与 `UNVERIFIED != PASS` 纪律同构 |
| 低频能力收进「更多」页（渐进披露） | 设置页平铺 BLE/Wi-Fi/更新（本轮已去重整理） | ⚪ 参考：其收纳思路对，但我们 4 tab 被门禁锁定，不照搬 5 tab |
| 诚实标注「这一版没重做的页」 | 我们有 `Mock 演示夹具 / 非实机读数`、`未读到` 标注 | ✅ 同构（能力边界对用户诚实，是纪律不是样式） |
| 切热点前先把信息留本机 | 我们配网切换 WiFi 会断连，已有回显但无「断线前留存」 | 🟡 参考：户外场景可补，非本轮 UI 范围 |
| 浅色 iOS 风 `#F2F2F7` + `m-card` 白卡 | 我们刚做**去卡片化**的暖深控制台 | ❌ **不抄**：用户明确要「不要那么多卡片块」，且定性为硬件监控台，深色更合适 |
| Preact SPA / `/ws` / `pad.op` 架构 | Kotlin 原生 + JSON-RPC over 4 transport | ❌ 不抄（语言/传输栈完全不同） |

## 3. 唯一值得动手补的点（待用户拍板，本轮不改）

**主页状态新鲜度提示**。Studio 把「数据是否还活着」做成用户能一眼看到的东西（超时变灰 + banner 明确说「鸭子会自己停下」），这与我们一贯的 `UNVERIFIED != PASS`、`看起来仍实时的陈旧值最危险`（`DriveActivity:113` 注释原文）是同一条纪律。

我们驾驶页已实现停滞检测，主页状态页却没有等价提示。最小改法（不碰任何门禁硬串）：

- 复用 `stateFrameAgeMs`，主页状态行在超阈值时把读数着色为 `md_text_dim`（陈旧灰）并追加「N 秒未收到状态帧」；
- 不改变任何数值内容、不填 0、不伪造「已连接」。

这是一处**功能补强**而非本轮 UI 重设计范围，且会触发全套门禁 + 真机复验。故先落文档、不动代码，等用户拍板。

## 4. 来源与边界

- 一手：`https://raw.githubusercontent.com/fanhao375/microduck-replica/master/software/studio/web/{m.html,m/app.js,m/mobile.css,m/more.js}`，2026-11-19 全文下载核验（本地临时副本 `microduck-android-app/build/uiredesign/fanduck_ref/`，不入库）。
- 排除：`7757/fanduck` 无网页中控；既有 `docs/reference/microduck-replica借鉴参考.md` 覆盖硬件/训练/固件，本文只补 **App UI 层**，不重复。
- 本轮 UI 重设计验证状态：core 640/640、统一门禁 ALL_PASS、assembleDebug 绿、**真机 `device_ui_check.py` 61 passed / 0 failed**（`build/uiredesign/device_gate_settings.log`）。借鉴文档不改变这些结论。
