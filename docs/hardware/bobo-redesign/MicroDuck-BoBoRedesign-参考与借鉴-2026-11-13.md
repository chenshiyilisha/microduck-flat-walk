# MicroDuck-BoBoRedesign 参考与借鉴（个人非商业复刻对照蓝图）

> 生成日期：2026-11-13
> 来源仓库：`AiBoBoMaker/MicroDuck-BoBoRedesign`（GitHub，非 fork，社区二次开发）
> 整仓镜像：`out/bobo-src/MicroDuck-BoBoRedesign-main/`（已 gitignore，**二进制不入库**）
> 用途：整机落地前的「对照蓝图」外部独立源，验证本项目采购 SSOT 与硬件路线合理性。
> 铁律：① 采购 SSOT 只读零改动；② STL/PCB/固件二进制不塞 git 主仓；③ 来源与 license 全标注。

---

## 0. 来源与许可证（全标注 · 铁律）

| 项 | 内容 |
|---|---|
| 上游溯源 | `pollen-robotics/microduck`（官方 0.15.1）→ `kissqy/Microduck-kissqy`（HD-1910 适配，**本项目底座**）→ `AiBoBoMaker/MicroDuck-BoBoRedesign`（再设计、独立分支） |
| 关联 fork | `fanhao375/microduck-replica`（早期模型参考）；fanhao 是 kissqy 的**叠层 fork**，与本项目/BoBo 同源但独立分支 |
| 代码与固件 | Apache-2.0（`03-DuckCode/microduck-hd1910/LICENSE`、`LICENSES/Apache-2.0.txt`） |
| 作者原创部分 | **Personal-NonCommercial**（个人非商业，`LICENSES/Personal-NonCommercial.txt`）— 商用需作者书面授权 |
| 3D 模型与设计 | CC BY-SA-NC（原始 MicroDuck 项目条款） |
| 根目录 | **无**独立 LICENSE 文件；许可见各子目录 |
| 本项目合规 | 个人复刻学习，已闭合；**商业使用 prohibited without author permission** |

---

## 1. 仓库结构（已整仓下载，不入 git 主仓）

| 目录 | 内容 | 对本项目价值 |
|---|---|---|
| `01-3DPrint/` | XL330-M288-T（28 STL）+ HD-1910-C001（已验证打印装配，主推）两套外壳；`0位支架.stp` | 打印工艺与分盘直接可参考 |
| `02-PCB/` | `01-IMU/`（`.epro2` 嘉立创专业版 + FT6 固件）、`02-HAT/`（Rev.A `.epro2`） | PCB 核对 / 替代货源 |
| `03-DuckCode/` | `microduck-hd1910/`（Rust 固件 + Python 中控，Apache-2.0 + Personal-NonCommercial） | 固件/中控对照 |
| `04-TrainCode/` | `training-console/`（R1.5.27，14 类动作 / 35 配方） | 训练栈对照 |
| `05-BOM/` | `MicroDuck购买清单.md` + 主板资料 + 飞特舵机手册 | BOM 双向核对源 |
| `06-tools/` | 飞特调试工具 / CH340 驱动 | 装配标定辅助 |

> 注意：`.epro2` 需**嘉立创 EDA 专业版**打开，标准版不兼容。

---

## 2. 版本与硬件一致性（已核对：与本项目 SSOT 完全对齐）

| 组件 | BoBo 版本 | 本项目 SSOT | 判读 |
|---|---|---|---|
| 机器人固件 | 官方 0.15.1 · control.43 · API40 | 同 | ✅ 一致 |
| 机器人中控 | R17 V167（1.0.167） | 同 | ✅ 一致 |
| 训练中控 | R1.5.27 | 同 | ✅ 一致 |
| HAT 驱动板 | Rev.A（2026-10-15）· 嘉立创 Pro · ≤15 舵机 + 电源 + IMU 口 | 人人 C1（Pollen ASE01187-C1 fork） | ✅ 同族 |
| IMU | imu_to_dxl（2026-10-15）· FT6 固件 | imu_to_dxl / imu-ft6 | ✅ 同固件 |
| 外壳 | HD-1910 版（已验证）/ XL330 版 | HD-1910 路线 | ✅ 一致 |
| 主控 | Radxa ZERO 3W（**2G** 无 eMMC） | Radxa ZERO 3W（**1GB** 无 eMMC，**已购**） | 🔴 规格差异（2026-11-13 拍板：不跟 2G） |

---

## 3. BOM 双向核对（本项目 SSOT 2026-11-10 vs BoBo 购买清单 2026-09-23）— 铁律：SSOT 零改动

| 物料 | 本项目 SSOT（2026-11-10） | BoBo 清单（2026-09-23） | 判读 |
|---|---|---|---|
| 主控 Radxa 3W | 1GB / 无 eMMC ¥179（用户国内一手，**2026-11-13 已购**） | 2G / 无 eMMC ¥299（历史 ¥309） | 🔴 规格差异（非错误）：决策文档 §8 四源互证定 1GB 足够；BoBo 选 2G。**2026-11-13 用户已购 1GB，决策收口：不升 2G** |
| 舵机 HD-1910-C001 | ¥99×15（项目基准=团购价） | ¥119×15（团购 ¥99） | ✅ 对齐（均到团购价） |
| HAT | 人人 C1 ¥140（fanhao Pollen ASE01187-C1 fork） | Hat 驱动板 ¥119（kissqy-derived，官方精简） | ✅ 同族（≤15 舵机+电源+IMU 口），货源不同 |
| IMU | imu_to_dxl ¥80（fanhao 自绘，总线） | BoBo IMU 板 ¥89（总线）/ I2C ¥26（自动切换） | ✅ 同协议族（总线 FT6）；BoBo 另给便宜 I2C 版 |
| HUB / 电源 | 人人 HUB ¥36（含 banana PCB）+ PATH A 配电并入供电行 | 舵机 Hub 电源优化板 ¥69（4 路合并 + 大电容防重启） | ⚠️ 方案差异：都含 ≥1000µF 缓冲，功能等价；我们不单列独立 HUB 板 |
| 结构金属件 | ¥45（共 7 个，受力件改金属） | 未单列（隐含在装配） | ➕ 本项目独有 |
| 电池 NP-F550 | 唯卓仕 2200mAh 项目占位 ¥118（强调放电 ≥8A） | 沣标 2200mAh 套装 ¥84.59 | ✅ 同容量同外形；口径差 |
| 摄像头 IMX219 160° | ¥64.35 | ¥64.35 | ✅ 同 |
| ToF VL53L5CX V2 | ¥49.5 | ¥49.5（写 VL53L5X V2） | ✅ 同 |
| 扬声器 3525 4Ω3W | ¥3.08 | ¥3.08 | ✅ 同 |
| 手柄 启明星 2 | ¥89.91 | ¥89.91 | ✅ 同 |
| 舵机线 AMP2.0 3P | ¥1.5 | ¥1.5 | ✅ 同 |
| 轴承 10×15×3 / 16×22×4 / 623ZZ | 有，价近 | 有，价近 | ✅ 同 |
| TF 卡 | 已有 64G ¥0 | 32G ¥30 | 口径差（已拥有） |
| 螺丝 | M2 系列 + M2.5×8 + M2.6×8 | M2×7 沉头 + M2.5×8 内六角 | 小差异，以打印件清单定长度 |
| OpenRB150 / 总线驱动板 | 不采用（HAT 覆盖） | 列 ¥265 / ¥26.73 | 不同架构，不选 |

**核对结论：**
- 在 **HD-1910 路线**上，本项目 SSOT 与 BoBo 清单**高度对齐**（同舵机 / 同 IMU 协议族 / 同 HAT 概念 / 同光声电电池线）。
- **唯一实质差异 = 主控 RAM（1GB vs 2GB）**，由本项目决策文档 §8 拍板 1GB，非 SSOT 错误。
- 其余为货源 / 架构选择差异，均已在 SSOT 判决。
- **未发现 SSOT 任何错误**；外部独立源佐证了本项目物料 / 价格 / 协议选型的合理性。
- ⚠️ 本核对**仅整理差异建议，不回写 xlsx**（铁律：采购域零改动）。

---

## 4. 值得借鉴 4 项 + 不能盲抄 4 项

**值得借鉴：**
1. 整仓目录组织清晰（3DPrint / PCB / DuckCode / TrainCode / BOM / tools 分目录）— 可作整机落地目录参考。
2. HD-1910 STL 已验证打印装配 + **分色分盘**（TPU 部分 / 支撑 / 橙 / 躯体 / 黑）+ 打印参数（PLA·PETG 0.2mm ≥20% 填充；TPU 85A–95A 15–20%；树状支撑）— 直接可参考打印工艺。
3. HAT Rev.A + IMU（FT6）硬件设计文件（`.epro2`）— 我们走人人现货，但可作 PCB 核对 / 替代源。
4. **制作顺序 SOP**（买料 → 打印 → 打板 → 烧 IMU → 装配 → 系统 → 调试 → 训练）— 可作整机落地 SOP 骨架。

**不能盲抄：**
1. 主控用 **2G** — 我们已论证 1GB 够（决策 §8），不跟。
2. IMU 走 **I2C 便宜版（¥26）** — 我们走总线 imu_to_dxl（与人人 / 驭芯 / kissqy 同契约 ID200/1M/15 字节），不跟 I2C 分支。
3. **OpenRB150 / 总线驱动板**替代 HAT — 我们已定 HAT 路线。
4. **XL330 路线** — 我们已定 HD-1910（价格 / 供货），两套外壳不混用（BoBo 明确两套不混用）。

---

## 5. 硬件兼容性核对（已核一手）

- **版本链：** BoBo 系统镜像 = **kissqy `public-image-r1`**（其 `03-DuckCode/microduck-hd1910/README.md` 明确指向 `kissqy/Microduck-kissqy/releases/tag/public-image-r1`）。佐证本项目 SSOT「**镜像随硬件同源**」：BoBo 硬件（基于 kissqy）→ kissqy R1 镜像；若本项目走 fanhao 硬件则需 fanhao 复刻镜像，走人人 / kissqy 硬件则 kissqy R1。✅ 与 SSOT 订正㉔ 一致。
- **IMU 固件：** BoBo `imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin` = 本项目 `imu-ft6`。✅ 固件级兼容。
- **HAT：** BoBo Rev.A（预留 I2C IMU 口，对接 Radxa 40pin）vs 我们人人 C1（Pollen ASE01187-C1 fork，AMP2.0 接口）。两种 IMU 挂载方式（HAT I2C / 舵机总线）均受固件支持（程序自动切换）。⚠️ 上机须 identify 实测（真机未接触，关节 ID 表与 IMU 挂载方式待上板验收确认）。
- **共享 ID200/1M 不互认提醒：** 同版本号不保证跨 fork 板互认；三家 IMU 板只共享 ID200/1M/15 字节契约，认板须带店家 + 价。
- **外壳强绑定舵机：** BoBo 明确 XL330 / HD-1910 两套不混用 — 我们已定 HD-1910，一致。

---

## 6. 整机落地 SOP 骨架（整合 BoBo 制作顺序 + 本项目到货执行单）

阶段 0 台架（过闸判据）→ 阶段 1 单腿 → 阶段 2 整机：

1. **买料** — 按 `docs/active/MicroDuck-照着买采购执行清单-2026-11-10.xlsx`；别买板直到过闸。
2. **打印外壳** — HD-1910 STL；先打 1 关节试配合（Ø2.2 孔 FDM 偏小 0.1–0.3mm）；TPU 件改软料。
3. **打板 / 现货** — HAT + IMU + HUB 人人现货即发。
4. **烧录 IMU FT6** — 用 `02-PCB/01-IMU/firmware/imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin`（或人人同契约固件）。
5. **装配** — 舵机 ID / 零点 / 限位用 `06-tools/02-feite/` 调试；每机须自核标定。
6. **系统镜像** — kissqy R1 或 fanhao 复刻镜像（随硬件同源）刷 TF（Armbian Imager）。
7. **调试** — HOME → 保持 → 行走；identify 实测关节 ID 表。
8. **训练（可选）** — R1.5.27。

> 详细填空见 `docs/active/microduck-主板到货上板执行单-2026-11-12.md`（§8 本机红灯 ≠ 交付缺陷）。

---

## 7. 二进制处理（铁律）

- `out/bobo-src/`（119MB，含 STL / PCB / 固件二进制）已 gitignore，**不入主仓**。
- 如需引用具体 STL / PCB，从 `out/bobo-src/` 取，不得 `cp` 进 git 跟踪区。
- 知识文本（本文件）入 `docs/hardware/bobo-redesign/`，已标 license。

---

## 8. 当前态与待办

- ✅ 仓库整仓下载 + 结构梳理（Task #317）
- ✅ BOM 双向核对（Task #318）：SSOT 与 BoBo 高度对齐，唯一差异主控 RAM，**2026-11-13 用户已购 1GB，决策收口不升 2G**，不回写 xlsx
- ✅ 知识源吸收 + license 标注（Task #319）
- ✅ 硬件兼容性核对 + 整机落地 SOP 骨架（Task #320）
- ✅ 已拍板：用户 2026-11-13 已购 1GB 主控，不升 2G（BoBo 选 2G 仅作对照记录，不跟）
- ⏳ 整机落地前不堆新评测；A2 七悬案 / D1 重开 / 安卓线入库仍卡整机或用户拍板
