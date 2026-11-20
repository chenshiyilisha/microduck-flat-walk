# 连接 / BLE / Wi-Fi 配网 UI 设计依据 · 2026-11-20

用户反馈：设置页「Wi‑Fi 和蓝牙配置这块感觉不是很好」。本文件先摆一手依据，再定落地。

## 1. 一手来源

| # | 来源 | 取用规则 |
|---|---|---|
| A | [Android Settings](https://developer.android.com/design/ui/mobile/guides/patterns/settings) | primary label + secondary **状态**；组用 containment；长说明放到次屏/短 supporting；依赖项放在被依赖项下方并说明不可用原因 |
| B | [M3 Lists](https://m3.material.io/components/lists/overview) + MDC `docs/components/List.md` | 列表项 = headline + supporting（+ trailing）；短、可扫；一致格式；按逻辑排序（本仓 BLE/Wi‑Fi 按 RSSI/信号） |
| C | 系统蓝牙设置常见 IA（与 A/B 同构） | **状态 → 扫描 CTA → 设备列表**；空态写清下一步 |
| D | 本仓既有铁律 | 门禁硬串不动：`BLE 连接` / `扫描附近 BLE 设备` / `Wi-Fi 配网` / `PLAINTEXT_TRANSPORT_WARNING`；嵌套 ScrollView 已导致门禁滚屏坑（见开源对照文档） |

## 2. 现状问题（对照截图 + 代码）

1. 说明墙压过状态：BLE 两段说明 + Wi‑Fi 长 Banner 抢主视线，当前连接/候选列表像附录。
2. BLE 列表是密 TextView + **内嵌 160dp ScrollView**（父设置页已是 ScrollView）→ 难滚、难扫、不像列表。
3. Wi‑Fi：裸 `EditText` 下划线 + 多行状态 dump + 扫描项无两行结构 → 不像 Settings/Lists。
4. 写操作按钮与列表同级并列，主任务（选设备 / 选网络）不突出。

## 3. 落地（本轮）

| 块 | 改法 |
|---|---|
| BLE | IA：标题 → 一行状态 → 一句 supporting → **扫描** → 两行列表项；去掉内嵌 ScrollView |
| Wi‑Fi | IA：标题 → 紧凑状态 → Banner（硬串保留）→ 刷新 → 两行网络列表 → Outlined 输入 → 写操作 |
| 共用 | `connectListRow(headline, supporting)`：56dp 触控、左文右状态节奏 |

门禁与明文警示常量**零改字**；只改布局与列表呈现。
