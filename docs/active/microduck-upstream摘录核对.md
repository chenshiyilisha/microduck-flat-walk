# `.upstream` 文档核对（阶段 0 视角）

日期 2026-10-27。范围：工作区根目录 `.upstream/` 里与 **HD1910 台架 / 上板**相关的摘录；**不是**全文通读 `dew_repo` / `duckemw` 等旁线大树。  
训练钉扎在 `microduck-software/.upstream/`（另册），本页不重复。  
当日总裁决另见：[microduck-2026-10-27裁决与场景纪要.md](microduck-2026-10-27裁决与场景纪要.md)。  
当日总裁决（场景 / XGO / StandUp）见 [microduck-2026-10-27裁决与场景纪要.md](microduck-2026-10-27裁决与场景纪要.md)。

## 0. 结论（对现在）

| 项 | 裁决 |
|---|---|
| 阶段 0 仍买：HD1910×1 + URT-2/1 + 限流供电（或电池+保险） | ✅ 与踩坑记录一致 |
| URT 接线 | **已修正本仓**：外电→舵机 V/G；URT 共地+S；**勿灌 V1** |
| 训练契约 61/14、植物 m5 | ✅ 不必因这些文档重开长训 |
| 陆吾 `1910_m6` / qiaosiyi 规格书植物 | 仍 **禁止当主植物**（与本仓铁律一致） |
| 整机掉电、D 颤、样机标定误拷 | **有板后再办**；记在阶段 C |

## 1. 已读（摘录）

| 文件 | 用途 | 对本仓影响 |
|---|---|---|
| `r_踩坑记录.md` | 买东西 / 舵机 / 主板真坑 | **接线、FD 1 Mbps、方向全 −1、D=0、勿灌 V1** → 已写入 `stage0_software_prep.md` |
| `r_README.md` | fanhao 复刻总览 / BOM 警告 | NP-F550 非 F970；CAD 走 replica-cad；飞特 BAM 与陆吾差大、未判真假 |
| `r_PROGRESS.md` | 2026-09 进度档 | 历史；不挡阶段 0 |
| `hd_readme.md` / `hd1910/*` | qiaosiyi 式规格书适配说明 | 对照用；本仓主植物仍是 OpenMicroDuck **m5** |
| `replica-2026-10/software_飞特适配架构.md` | 官方 runtime 换飞特接缝 | 支持「不自写 robotd、跟 kissqy/fanhao」 |
| `replica-2026-10/software_training_docs_hd1910-baseline.md` | 陆吾 M6 + kp_fw=5 基线 | **与本仓 m5/kp32 不同**；勿混 |
| `replica-2026-10/docs_HD-1910训练前数据清单.md` | 几何/质量待实测表 | 装机后覆盖；阶段 0 单颗可先做 kt/R |
| `replica-2026-10/docs_HD1910-20261011-kissqy-walk上机实测.md` | 供电余量、0.9/0.5/0.7 | 上板部署缩放对照 |
| `kissqy-2026-10/*` 若干 training-console docs | 中控/审计摘录 | 刷镜像前再对 V167 release |

## 2. 未通读（需要时再开）

- `dew_repo/`、`duckemw/`（XL330 flat-walk 大树）  
- `microduck-replica-cad/` 全量 CAD  
- `xgo-2026-10/`、`zh-2026-10/` 全文  
- 踩坑记录后半「软件 / 策略训练」每一条长实验（上板前再扫 IMU、镜像、手柄相关条）

## 3. 阶段 0 操作清单（摘自踩坑 + 本仓）

1. 装 URT 驱动 → FD 最新 → 波特率 **1000000**  
2. 接线按 `stage0_software_prep.md`（勿灌 V1）  
3. **一次一颗**改 ID；AMP2.0 插不上就转接/飞线  
4. 闸门：ping → 50 Hz ≤5 ms / 0 CRC → 可选温升与 kt/R → 确认 reg50  
5. 不过 → **停、换货**，不买齐 15  

出处：`.upstream/r_踩坑记录.md`；本仓落地：`tools/hd1910/stage0_software_prep.md`。
