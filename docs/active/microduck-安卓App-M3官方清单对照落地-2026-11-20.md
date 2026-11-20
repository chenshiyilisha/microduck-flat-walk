# MicroDuck 安卓 App · M3 / Android 官方清单对照落地 · 2026-11-20

_用户要求：按官方清单对照改一版。本文件是对照表 + 落地项；色板/布局改动以本表为准。_

## 1. 官方来源（一手）

| # | 文档 | 本 App 取用的硬规则 |
|---|---|---|
| A | [M3 Usability](https://m3.material.io/foundations/usability/overview) | 每屏一个主任务；主动作最大/最醒目；相关内容用容器分组 |
| B | [M3 Layout](https://m3.material.io/foundations/layout/layout-overview) | 一致间距；手机 compact = 单栏 |
| C | [M3 Breakpoints](https://m3.material.io/foundations/layout/breakpoints) | 手机用 Navigation bar，不用 rail |
| D | [M3 Navigation bar](https://m3.material.io/components/navigation-bar/guidelines) | 3–5 destinations；底栏固定不滚动；选中态指示 |
| E | [M3 Color roles](https://m3.material.io/styles/color/roles) | surface / onSurface / primary；组件吃语义色 |
| F | [M3 Expressive](https://m3.material.io/blog/building-with-m3-expressive) | 强调字阶 + 容器；hero 留给关键交互（本仓禁用循环动画） |
| G | [Android Settings](https://developer.android.com/design/ui/mobile/guides/patterns/settings) | 组间分隔、标题具体、勿三明治重复 |
| H | [Android edge-to-edge](https://developer.android.com/develop/ui/views/layout/edge-to-edge) | insets → padding；不退回 opt-out |
| I | FPV OSD / teleop（驾驶页例外） | 中心留空；遥测贴边；摇杆贴拇指 |

## 2. 对照 → 落地

| 规则 | 改前问题 | 本轮改法 |
|---|---|---|
| A 单主任务 | 连接/模式/休息/监测平铺抢层级 | 状态页「控制」整块用 `surfaceContainer` 包住；**进入遥控**唯一 filled |
| A 空态降权 | 「未读到」22sp 抢眼 | 空态 14sp + onSurfaceVariant |
| D 底栏 | 指示条在图标上方、无 surface 底 | 底栏 `surfaceContainer`；选中 = primary 圆角指示 pill 衬在图标后 |
| E 色角色 | 冷青/冷蓝科技模板 | primary=鸭橙 trim；bg/surface 暖石墨阶梯 |
| F hero | 顶栏「M」方块 + 22sp 标题抢 CTA | 顶栏瘦标题；hero = 进入遥控 |
| G 设置 | 滑块挤成一坨、标题三明治、恢复默认飘在组外 | 按 Settings 官方：分区头 title+supporting、组 containment、滑块 label\|value、恢复默认入组；门禁硬串原样 |
| G 连接 | BLE 说明墙+嵌套 Scroll；Wi‑Fi 状态 dump+裸 EditText | 见 `…连接配网UI设计依据`：状态→CTA→两行列表；Outlined 输入；PLAINTEXT/门禁硬串不动 |
| I 遥控 | 制动键干扰中心 | **已删除制动**；READY 接管时淡化 |
| 门禁 | — | 硬串 / content-desc 零改 |

## 3. 字阶（收敛 5 档，对齐 M3 type 用途）

| 档 | sp | 用途 |
|---|---|---|
| title | 16 | AppBar 页名 |
| section | 11 | 分区 Label（字距略增） |
| body | 14–18 | 有数据时的读数 |
| label | 11–12 | 按钮/标签 |
| caption | 10–11 | 脚注/空态 |

## 4. 验证

- `assembleDebug`
- 真机装包截图：状态 / 健康 / 设置 / 终端 / 横屏遥控
- 有空再跑 `device_ui_check.py`
