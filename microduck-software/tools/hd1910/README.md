# HD1910 plant tools

Implements `docs/active/microduck-HD1910软件方案.md` §3.

**新环境 / 新克隆 / 挪过目录，第一件事（其他的往后排）：**

```bash
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check
# 期望：detected=hd1910  kp_fw=32.0  register=True  gate_ok=True
```

> **切哪个取决于你要干什么**（别默认照抄上面那条）：
>
> | 目的 | plant |
> |---|---|
> | **复现已归档的 HD1910 数字**（`model_5999` 那批） | `hd1910`（m5 + `kp_fw=32`） |
> | **P3 正式重训**（已裁决，对齐 kissqy） | **`hd1910_kp5`** |
>
> 二者不是同一台机器：`kp_fw` 32（出厂 ROM 默认）vs 5（训练/部署实际生效值）相差 6.4 倍。
> 详见 [`docs/active/microduck-HD1910软件方案.md` §3](../../../docs/active/microduck-HD1910软件方案.md)。

不切＝在 XL330（`kp_fw=200`）上训练：loss 照降、曲线照好看，产物对 HD1910 无效
（同一个 ckpt 实测 vx **0.318** / 摔倒 0% ↔ **0.109** / 摔倒 100%）。
每次评测记得回读 JSON 里的 `plant_fingerprint.name`。

⚠️ `apply` 会把**本机绝对路径**写进 site-packages：换机器 / 挪工作区后必须在**新位置**重跑上面两条。
⚠️ `--plant xl330` 恢复若报回收站/权限错（`SHFileOperationW 0x78`），手工 `cp microduck_constants.py.xl330.bak`
覆盖同名文件 + 删 `__pycache__/` 里对应 `.pyc`。

---

## ⚠️ 两个与植物无关的通用陷阱（都不是 plant 问题，别查错方向）

| 症状 | 真因 | 修法 |
|---|---|---|
| 训练在打印完 `device=cuda:0` 和 `[BamActuator]` 横幅之后炸，报 wandb `ValidationError … start_method Extra inputs are not permitted` | 这个 venv 的默认 logger 是**坏的**：`rsl_rl/utils/wandb_utils.py:46` 构造 `wandb.Settings(start_method="thread")`，已装的 wandb 不再接受这个键 | **任何训练都要显式传 `--agent.logger tensorboard`**（`tools/train_velocity.sh:243` 也是为此） |
| 改了命令侧的效果没出现 | tyro 能覆盖的大多是 reward 项的 dict，**curriculum 的 stage table 是 `list[dict]`，tyro 根本不暴露成 flag** | 用 `tools/train_velocity_variant.py`（stage 表）或 `tools/../tools/train_heading_variant.py`（command 字段）在进程内改 live cfg |
| `hd1910_kp5` / `actuator: sts3215` 在 reset 炸 `AttributeError: q_target_smooth` | 上游 `STS3215Actuator` 只在 `load_log()` 里建该字段；mjlab 不走那条路 | `.venv-mjlab/Scripts/python.exe tools/hd1910/patch_sts3215_q_target_smooth.py`（改 editable bam；`.upstream` 不进 git） |

## heading 闭环（治偏航）— `probe_heading_loop.py`

偏航的根子是 `microduck_velocity_env_cfg.py:643` 的 `rel_heading_envs = 0.0`
（训练中零个 env 练过航向闭环）。**其余部件都已就位**，必须回读对象才知道
（`heading_command` 在源码里一次都不出现）：

```
heading_command=True   heading_control_stiffness=0.5   ranges.heading=(-pi, pi)
rel_heading_envs=0.0   <-- 唯一被关的那个
```

改的完整依据、代价（`rel_*` 是独立伯努利，与 forward 桶重叠 0.30×0.20=6%）与
sweep 建议见 [`docs/active/microduck-HD1910软件方案.md` §8.2「P3 附」](../../../docs/active/microduck-HD1910软件方案.md)。

机制验证（**先跑它、再谈重训**，CPU 几秒、不需要 policy）：

```bash
MUJOCO_GL=glfw .venv-mjlab/Scripts/python.exe tools/hd1910/probe_heading_loop.py
# 期望：8/8 PASS；cmd[2] 与闭式逐位相符 0.000e+00，负对照 1.737
```

改的上层开关在同级的 `../tools/train_heading_variant.py`（同样三道护栏，
不改 site-packages）。

---

| File | Role |
|---|---|
| `plant_spec.py` | Numbers + provenance for **4** plants (m5/kp32, Feetech m6, **`hd1910_kp5` = P3 target**, XL330) |
| `apply_to_live.py` | Reversible edit of live `microduck_constants.py`; `--check` gates each plant |
| **`probe_plant_law.py`** | Print what a params JSON **actually** resolves to (`law_class`/`kp`/`max_velocity`/`max_pwm`). Reading the JSON cannot tell you this |
| **`selftest_plant_switch.py`** | Round-trip + **negative control** for the switch; restores the original plant at the end |
| `smoke_train.sh` | Velocity 64×5 smoke after plant gate is green |
| `explore_train.sh` | Velocity GPU explore（默认 4096×2000；本机勿用 8192） |
| `resume_train.sh` | Velocity 续训（默认 4096→6000） |
| `smoke_standup.sh` | **StandUp** 64×5 冒烟（摔倒爬起） |
| `explore_standup.sh` | **StandUp** 探索（默认 **1024×1000**；正式再 4096×4000） |
| `resume_standup.sh` | StandUp 同配方续训（须 `LOAD_RUN`/`LOAD_CKPT`） |
| `parity_smoke.sh` | ONNX↔ckpt parity（C-prep-4） |
| `rehearse_hd1910.py` / `.sh` | 部署彩排：BAM **m5 / kp_fw=32**（patch `infer_policy`，不改上游文件） |
| `urt1_bench.py` | 阶段 0 URT-2/URT-1 台架骨架（`--dry-run`；有口再 `--port`） |
| `deploy_import_checklist.md` | kissqy 上板勾选：镜像 / 方向 / P=32 / 部署缩放 |
| `ab_train.sh` | Phase B A/B m5 vs Feetech m6 |
| `bam_param_compare.md` | kt/R table: m5 / official m6 / Luwu ban |
| `stage0_software_prep.md` | 到货前：FD / **URT 接线（勿灌 V1）** / 表征 JSON / kissqy 镜像入口 |
| `server_pack/` | **Windows 训练机打包**（4070 Ti）：`make_transfer.ps1` + `bootstrap.ps1`（勿拷 venv） |

```bash
# plants (do not switch while a train is mid-run)
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910            # OpenMicroDuck m5, kp_fw=32 — to REPRODUCE archived numbers
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_ftservo_m6 # Feetech official m6, kp_fw=32
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_kp5        # ★ P3 training target: official m6 + official law + kp_fw=5
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check

# what a params file really becomes (do not infer this from the JSON text)
.venv-mjlab/Scripts/python.exe tools/hd1910/probe_plant_law.py \
    --json tools/bam_params/hd1910/official_m6_stslaw.json --kp-fw 5
# switch regression — must end with ALL CHECKS PASSED and restore the plant it found
.venv-mjlab/Scripts/python.exe tools/hd1910/selftest_plant_switch.py

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

# stage-0 URT-2/URT-1 skeleton (no hardware)
.venv-mjlab/Scripts/python.exe tools/hd1910/urt1_bench.py --dry-run

# StandUp / fall recovery (new task — from zero; not resume of velocity 5999)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/smoke_standup.sh
# 4070 Ti explore:
ENVS=1024 ITERS=1000 "D:/Program Files/Git/bin/bash.exe" tools/hd1910/explore_standup.sh
# formal after curve looks ok:
# ENVS=4096 ITERS=4000 bash tools/hd1910/explore_standup.sh

# Phase B A/B (switches plant; do not parallel with long train)
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/ab_train.sh both

# restore XL330
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330
```

BAM pin for training: `.upstream/bam-62bd8ce…`（勿整包装 ftservo-bam）。
飞特仓 clone 在 `.upstream/ftservo-bam`（只取参数）。Case pit：`HD1910`/`hd1910`
双注册。Smoke 要求 log 含 `device=cuda:0`。

⚠️ 2026-10-29 纠正：~~禁止陆吾 `1910_m6.json`~~ —— 旧理由是「`actuator` 误标 sts3215」，属误判
（BAM 的 Feetech 合法键**本来就是** `sts3215`）。它真正的问题在别处：写了 `max_velocity: 100`
（≈5730°/s），把官方 5.2155 rad/s 的内部限速**悄悄覆盖掉了**。用 `probe_plant_law.py` 一眼可见，
读 json 文本看不见。

Windows 服务器（4070 Ti）复现环境：[`server_pack/README.md`](server_pack/README.md)。
