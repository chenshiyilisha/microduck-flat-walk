# MicroDuck 工作区导航（2026-10-26）

**当前主线：HD-1910 仿真植物 + GPU 训练 → 再接真机。**

铁律：遇事先查资料（`.cursor/rules/look-up-first.mdc`）。  
长期结论：`workbuddy-history/memory/MEMORY.md`。  
文档总索引：[`docs/README.md`](docs/README.md)。

---

## 1. 今天先读（现行）

| 用途 | 文件 |
|---|---|
| **软件主方案 / 阶段 A–D** | [`docs/active/microduck-HD1910软件方案.md`](docs/active/microduck-HD1910软件方案.md) |
| **真机软件清单（阶段 C）** | [`docs/active/microduck-HD1910阶段C软件清单.md`](docs/active/microduck-HD1910阶段C软件清单.md) |
| **花钱 / 阶段 0 BOM** | [`docs/hardware/microduck-采购清单.md`](docs/hardware/microduck-采购清单.md) **§7** |
| **算力刻度** | [`docs/active/microduck-RL_duck教学仓对照.md`](docs/active/microduck-RL_duck教学仓对照.md) |
| **BAM 参数对照** | [`microduck-software/tools/hd1910/bam_param_compare.md`](microduck-software/tools/hd1910/bam_param_compare.md) |
| **日记忆** | [`workbuddy-history/memory/2026-10-26.md`](workbuddy-history/memory/2026-10-26.md) |
| **10-27 裁决纪要** | [`docs/active/microduck-2026-10-27裁决与场景纪要.md`](docs/active/microduck-2026-10-27裁决与场景纪要.md)（IMU/组装机/场景/XGO） |
| **2026-10-27 裁决纪要** | [`docs/active/microduck-2026-10-27裁决与场景纪要.md`](docs/active/microduck-2026-10-27裁决与场景纪要.md)（台架/IMU/场景/kissqy↔XGO） |
| **10-27 裁决纪要**（场景/IMU/XGO/StandUp） | [`docs/active/microduck-2026-10-27裁决与场景纪要.md`](docs/active/microduck-2026-10-27裁决与场景纪要.md) |

### 训练命令

```bash
cd microduck-software
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/smoke_train.sh
ENVS=4096 ITERS=2000 "D:/Program Files/Git/bin/bash.exe" tools/hd1910/explore_train.sh
# 续训（默认 4096→6000；本机勿用 8192）：
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/resume_train.sh
# StandUp（可选；从零训，勿续 5999）：
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/smoke_standup.sh
ENVS=1024 ITERS=1000 "D:/Program Files/Git/bin/bash.exe" tools/hd1910/explore_standup.sh
# ONNX parity / 阶段0软件入口：
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/parity_smoke.sh
# 见 tools/hd1910/stage0_software_prep.md
# A/B（短训对照，勿与长训并行热换植物）：
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/ab_train.sh both
```

工具说明：[`microduck-software/tools/hd1910/README.md`](microduck-software/tools/hd1910/README.md)。  
Windows 训练机打包（4070 Ti，勿拷 venv）：[`microduck-software/tools/hd1910/server_pack/README.md`](microduck-software/tools/hd1910/server_pack/README.md)。  
StandUp（可选）：`tools/hd1910/smoke_standup.sh` → `explore_standup.sh`（默认 1024×1000）。

---

## 2. 目录职责

| 路径 | 干什么 |
|---|---|
| `docs/active/` | 现行方案与评测口径 |
| `docs/hardware/` | 采购 / BOM |
| `docs/sideline/` | joy、XL330 交付旁线 |
| `docs/archive/` | 过时选型档案 |
| `docs/reference/` | 社区对照（可查） |
| `microduck-software/` | 代码、`.venv-mjlab`、HD1910 工具、日志 |
| `.upstream/dew_repo/` | XL330 flat-walk 交付档案 |
| `workbuddy-history/` | 会话记忆 |

---

## 3. 当前进度（一句话）

- 植物 live：**OpenMicroDuck m5**；BAM pin：`bam-62bd8ce`  
- 续训 **≈6000 完成**：P-walk ratio≈**0.76**；ONNX `out/hd1910_resume_4096_to6000_1027_it5999.onnx` + parity ✅  
- 下一步：**阶段 0 下单**（URT-2 优先 / URT-1 + HD1910×1 + 电源；勿 U2D2）

细节：[`docs/active/microduck-HD1910软件方案.md`](docs/active/microduck-HD1910软件方案.md) 头顶进度表。

---

## 4. 明确不做

1. 不用陆吾 `1910_m6.json`（`actuator: sts3215`）训练  
2. 不把 XL330 `walk_std004_*` 部署到 HD1910  
3. 不自写飞特 robotd  
4. 正式训练不走 `microduck-software/repo`（mjbatch 脚手架）

---

## 5. 本仓还保留的 XL330 / DuckEMW 交付（旁线）

main 合并了原先 flat-walk 交付树：docs/05-flat-walk.md、	ools/flat_walk/、rtifacts/flat_walk/、	hird_party/ 等。  
那是 **XL330 平地速度跟踪** 档案；**现行施工以 HD-1910 为主**（见上文）。旁线入口：[docs/sideline/](docs/sideline/)。

