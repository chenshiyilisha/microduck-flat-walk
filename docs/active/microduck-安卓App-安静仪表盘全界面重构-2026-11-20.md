# MicroDuck 安卓 App · 安静仪表盘全界面重构 · 2026-11-20

_触发：用户「所有界面都重构一遍，按照最优的来，记得多查查资料」。_
_方法：对照一手资料 + 仓内已核验决策，统一视觉语言；门禁硬串 / 数据诚实性不动。_

## 0. 结论

竖屏控制台走 **安静仪表盘**（专业仪器感、低装饰）；横屏遥控走 **FPV 座舱**（画面中心清空、控件贴拇指）。  
撤销 11-20 HTML 稿带回的「冷黑 + `#4A8BFF` + 分区浮卡 + 营销方块 logo」，回到并强化 11-19 去 AI 味路线。

## 1. 查到的资料（本轮）

| 来源 | 采纳 |
|---|---|
| [M3 Expressive](https://m3.material.io/blog/building-with-m3-expressive)（2025-05） | 字重/色阶/容器拉开层级；每屏一个主动作；hero 只留给关键交互 |
| [M3 Color roles / Surface](https://m3.material.io/styles/color/roles) | 层级靠 tonal surface，不靠嵌套卡片阴影 |
| Betaflight OSD / VP0 drone HUD 指南 | 中心留空；遥测贴边；告警醒目；双摇杆贴下角 |
| OpenROV / TelloNO 遥控实践 | 深色透明 overlay；次要信息一键之外；触控目标够大 |
| standoutmcp / skillcraft（11-19 已核） | 禁止 card-around-everything；暖近黑；一强调色；borders > shadows |
| 仓内 11-20 融合裁决 | 不做物理急停假按钮；软件制动须写明；不做呼吸/扫描动画 |

## 2. 设计系统（全页共用）

### 色板（暖近黑 · 钢青强调）

| token | hex | 用途 |
|---|---|---|
| `md_bg` | `#121110` | 页底 |
| `md_card` / `md_surface` | `#1C1B19` | 分区浅底 |
| `md_card_alt` | `#26241F` | 分段控件底 / hover |
| `md_text` | `#E8E6DF` | 正文 |
| `md_text_dim` | `#9C978C` | 次要 |
| `md_accent` | `#6E9BB5` | 唯一主 CTA / 选中 |
| `md_warn` / `md_ok` / `md_bad` | `#C7A052` / `#6EA483` / `#CE6A63` | 功能状态色 |
| `md_outline` | `#3E3B34` | 1px 分隔 |

### 组件规则

- 分区：标题 12sp + 内容 + 底部 1px 线；**无浮卡套层**（撤 `asCard`）。
- 读数格：ruled row（底部分隔），非 20dp 圆角小卡。
- 按钮：每屏 1 个 filled；其余 outlined。
- 顶栏：产品名 + 状态 pill；**去掉「M」营销方块**。
- 遥控：半透明数据牌贴右上；中央 READY 无发光晕；双摇杆间加「制动」（软件，文案标明不替代物理急停）。
- 动画：仍禁止呼吸/扫描（uiautomator 1000ms idle）。

## 3. 门禁硬串（逐字保留）

`进入遥控界面` / `手动模式` / `自动模式` / `标签页*` / `方向摇杆` / `头部摇杆` / `退出遥控` /
`实机状态帧` / `当前无状态帧` / `— 未读到` / `App 本地遥测（非实机数据` /
`robot.health` / `Mock 演示夹具` / `已本地持久化` / `方向摇杆死区` /
`扫描附近 BLE 设备` / `BLE 连接` / `进入遥控驾驶` / HUD_LABELS / PLAINTEXT 常量。

## 4. 验证

- `assembleDebug`
- 有设备时：`python tools/device_ui_check.py`（目标 61/61 或当前脚本全绿）
- 目视：四竖屏页 + 横屏遥控截图
