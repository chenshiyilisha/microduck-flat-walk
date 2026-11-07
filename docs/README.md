# 文档目录（microduck / flat-walk 衍生仓）

本目录按主题分桶。所有链接均为**仓库根相对路径**（渲染器以仓库根为基准解析 `docs/...`）。

| 文件夹 | 内容定位 |
|---|---|
| [`active/`](active/) | **现行 HD1910 主线**（当前工作均落在此处） |
| [`hardware/`](hardware/) | 硬件：采购 / BOM / 装配 / 轮滑变体 / Radxa·OrangePi 双版本 / IMU 对照 / MicroDock 预研 / 验收清单 |
| [`reference/`](reference/) | 横向对照与资料溯源（开源项目、上游配置、社区、未核实项核查） |
| [`sideline/`](sideline/) | 旁线：joy / XL330 交付、DuckEMW 对照、走起来的配方（不挡 HD1910 主线） |
| [`archive/`](archive/) | 过时选型 + 早期编号笔记（Dance / stilts / DuckEMW 时代，2026-08~09） |

工作区总入口是仓库根 [`../README.md`](../README.md)。根目录不保留旧文件名 stub，一律从根 README 或本页进入。

---

## `active/` — 现行 HD1910 主线

| 文件 | 主题 |
|---|---|
| [`microduck-HD1910软件方案.md`](active/microduck-HD1910软件方案.md) | 软件主方案（plant=kp8 部署、安全层、评估铁律、关节 ID 两套体系） |
| [`microduck-HD1910阶段C软件清单.md`](active/microduck-HD1910阶段C软件清单.md) | 阶段 C 软件交付清单 |
| [`microduck-HD1910工具整合评估.md`](active/microduck-HD1910工具整合评估.md) / [`…工具整合计划.md`](active/microduck-HD1910工具整合计划.md) | HD1910 工具整合可行性评估与计划 |
| [`microduck-2026-10-27裁决与场景纪要.md`](active/microduck-2026-10-27裁决与场景纪要.md) | 10-27 裁决与场景纪要 |
| [`microduck-板子设计备忘.md`](active/microduck-板子设计备忘.md) | 私人定板后置的板子设计备忘 |
| [`microduck-奖励与评测.md`](active/microduck-奖励与评测.md) | 奖励项与评测协议 |
| [`microduck-官方策略ONNX对照与缺口复核.md`](active/microduck-官方策略ONNX对照与缺口复核.md) | 官方 ONNX 策略对照与缺口复核 |
| [`microduck-开源对照地图.md`](active/microduck-开源对照地图.md) | 开源项目对照地图（含齿隙微调配方） |
| [`microduck-RL_duck教学仓对照.md`](active/microduck-RL_duck教学仓对照.md) | RL_duck 教学仓对照 |
| [`microduck-upstream摘录核对.md`](active/microduck-upstream摘录核对.md) | `.upstream` 摘录核对 |
| [`microduck-policy-bundle链.md`](active/microduck-policy-bundle链.md) | policy bundle 链路 |
| [`microduck-阶段3-自动跟随.md`](active/microduck-阶段3-自动跟随.md) | 阶段 3 自动跟随 |

## `hardware/` — 硬件

采购清单、HAT BOM、两版整机装配完整性核对、轮滑件核图对照、双版本推进（Radxa / OrangePi）、飞特版 3D 打印件、拼出完整鸭子、官方功能全景、最优方案（价格·硬件·软件）、完整功能压价方案、IMU 三方对照（666wsp / kissqy / DuckBuddy）、MicroDock 真机可行性预研、Radxa 上电验收清单、资料溯源与结论审计、路线 B 今日下单清单。

## `reference/` — 横向对照与资料溯源

XGO-Duck 对照、IsaacLab 可用性、replica 借鉴参考、mjlab-GPU 与三个新仓库、社区参考 2026-10、舵机与 BAM 验证、软件到硬件全链路资料地图、生态全景、横向对照、未核实项核查报告、开源资料全景、上游真实配置对照、开源对照地图。

## `sideline/` — 旁线（不挡主线）

joy / XL330 交付相关：A 路判决 iter1250、DuckEMW 对照 / 二次扫描、joy 策略实测、joy 训练落地、joy 踏步失败诊断与修法、joy 动作平滑税诊断、走起来的配方。

## `archive/` — 过时选型 + 早期编号笔记

- **过时硬件/方案选型**：低成本方案、国内自制方案、技术深挖、控制环与情感、最优方案、研究报告、硬件方案、软件路线。
- **早期编号笔记（Dance / stilts / DuckEMW 时代，2026-08~09，已迁此）**：[`01-rl-playbook-notes.md`](archive/01-rl-playbook-notes.md)、[`02-design-notes.md`](archive/02-design-notes.md)、[`03-training-log.md`](archive/03-training-log.md)、[`04-stilts-repro.md`](archive/04-stilts-repro.md)、[`05-flat-walk.md`](archive/05-flat-walk.md)。其中 `05-flat-walk.md` 仍被现行主线文档引用（§21/§22 等 kp 失配判据），属历史性交付记录。
