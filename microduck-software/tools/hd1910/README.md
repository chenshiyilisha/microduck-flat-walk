# HD1910 plant tools

Implements `docs/active/microduck-HD1910软件方案.md` §3.

| File | Role |
|---|---|
| `plant_spec.py` | Numbers + provenance (OpenMicroDuck m5 / XL330 official) |
| `apply_to_live.py` | Reversible edit of live `microduck_constants.py` |
| `smoke_train.sh` | 64×5 smoke after plant gate is green |
| `explore_train.sh` | GPU explore (default 4096×2000；本机勿用 8192) |
| `resume_train.sh` | 从 `model_*.pt` 续训（默认 4096→6000） |
| `parity_smoke.sh` | ONNX↔ckpt parity（C-prep-4） |
| `rehearse_hd1910.py` / `.sh` | 部署彩排：BAM **m5 / kp_fw=32**（patch `infer_policy`，不改上游文件） |
| `urt1_bench.py` | 阶段 0 URT-1 台架骨架（`--dry-run`；有口再 `--port`） |
| `deploy_import_checklist.md` | kissqy 上板勾选：镜像 / 方向 / P=32 / 部署缩放 |
| `ab_train.sh` | Phase B A/B m5 vs Feetech m6 |
| `bam_param_compare.md` | kt/R table: m5 / official m6 / Luwu ban |
| `stage0_software_prep.md` | 到货前：FD / 表征 JSON / kissqy 镜像入口 |
| `server_pack/` | **Windows 训练机打包**（4070 Ti）：`make_transfer.ps1` + `bootstrap.ps1`（勿拷 venv） |

```bash
# plants (do not switch while a train is mid-run)
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910            # OpenMicroDuck m5
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_ftservo_m6 # Feetech official m6
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check

# smoke / explore (GPU cuda:0; Windows MUJOCO_GL=glfw)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/smoke_train.sh
ENVS=4096 ITERS=2000 "D:/Program Files/Git/bin/bash.exe" tools/hd1910/explore_train.sh

# resume (no long train now — run when ready)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/resume_train.sh

# ONNX parity
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/parity_smoke.sh

# deploy rehearsal (HD1910 m5 plant; default = DR sweep)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/rehearse_hd1910.sh
# quick: ARGS='--condition nominal --seconds 4' bash tools/hd1910/rehearse_hd1910.sh

# stage-0 URT-1 skeleton (no hardware)
.venv-mjlab/Scripts/python.exe tools/hd1910/urt1_bench.py --dry-run

# Phase B A/B (switches plant; do not parallel with long train)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/ab_train.sh both

# restore XL330
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330
```

BAM pin for training: `.upstream/bam-62bd8ce…`（勿整包装 ftservo-bam）。
飞特仓 clone 在 `.upstream/ftservo-bam`（只取参数）。Case pit：`HD1910`/`hd1910`
双注册。Smoke 要求 log 含 `device=cuda:0`。**禁止**陆吾 `1910_m6.json`。

Windows 服务器（4070 Ti）复现环境：[`server_pack/README.md`](server_pack/README.md)。
