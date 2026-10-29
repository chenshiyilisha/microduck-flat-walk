# 板子设计备忘（私人定做 · 后置）

记录日：2026-10-29。施工主线仍以 [采购清单 §7](../hardware/microduck-采购清单.md) 为准；**本页只钉「以后真要改板时怎么干」，现在不启动。**

相关：[2026-10-27 纪要 §1.2 IMU](microduck-2026-10-27裁决与场景纪要.md) · [软件方案](microduck-HD1910软件方案.md)

---

## 1. 现在不设计板

| 项 | 现行口径 | 出处 |
|---|---|---|
| 阶段 2 默认板 | **买 kissqy HAT+IMU 成品**（AMP2.0），不自打 | 采购清单 §7.4 |
| 官方 HAT 开源资料 | `pollen-robotics/elec_RPI_Robot_HAT` rev D1，`production/` 可交嘉立创（路线 A / 对照） | 采购清单 §4 |
| `imu_to_dxl` | **延后**；要对齐官方双 IMU / 镜像只认总线 ID 200 时再做 | 采购清单 §5；纪要 §1.2 |
| 社区可抄板 | `avanx/microduck_imu_to_ttl`、`jyg9/microduck-community-kit`、fanhao 手册 | `docs/reference/microduck-生态全景.md` |

阶段 0 台架过闸前，**不买打样、不开私人 PCB 项目**。

---

## 2. 以后私人定做时：可借鉴工具

**仓库**：[biosshot/easyeda-copilot](https://github.com/biosshot/easyeda-copilot)（MIT，TypeScript）

**是什么**：EasyEDA Pro / 嘉立创 EDA 的 **MCP 扩展**——用自然语言在**原生工程**里生成/重组原理图、搜 LCSC、约束布局与布线、跑官方 DRC；产出可继续手改，不是静态图。演示含 ESP32-C3 / MIMXRT 控制器，以及 `pico_duck` 一类小板例子。

**怎么接**：装 EasyEDA 扩展 + MCP 客户端（Codex / Claude Code 等）→ `npx -y easyeda-copilot-mcp`（见该仓 README.zh-CN）。

**适合我们的场景**

1. 以官方 HAT（Apache-2.0）或 kissqy/社区原理图为底，**改接口 / 供电 / 舵机座 / 1000 µF 入口**再下单。
2. 自研或改版 **`imu_to_dxl` 类总线小板**（LSM6 + MCU + 半双工，落 ID 200）。
3. 小转接 / 分线板（AMP2.0、XT60 并联供电），避免舵机座菊花链扛电流。

**硬边界**

- 必须 EasyEDA Pro；不是离线 KiCad 全家桶替代品。
- AI 过 DRC ≠ 可焊交付：半双工总线、电源、ESD、热仍要人审。
- MIT 可私用 / fork；**不替代**「先成品跑通」的花钱顺序。

---

## 3. 启动闸门（未满足就别开板）

1. 阶段 0 单颗 + 温升 / 总线闸门过。
2. 阶段 2 镜像版本已定（是否强制总线 ID 200）。
3. 成品 HAT 实测暴露**明确缺口**（缺座、缺电容、缺第二 IMU、供电触点不够）——缺口写成一页需求再进 EasyEDA。

---

## 4. 待开时的最小清单（预留，未采购）

| 步骤 | 内容 |
|---|---|
| 参考导入 | 官方 D1 Gerber/BOM 或社区开源工程 → EasyEDA |
| 工具 | EasyEDA Pro + easyeda-copilot MCP |
| 打样 | 嘉立创 5 片起；LCSC 对料；舵机座 **AMP2.0 / JST 规格写死** |
| 验收 | 空载上电 → 无短路 → sync_read 见预期 ID → 再上舵机 |

*本页不写入采购金额；金额仍跟采购清单阶段表。*
