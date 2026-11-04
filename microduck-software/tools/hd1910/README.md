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
| `sts_bench.py` | 阶段 0 URT-2/URT-1 台架骨架（`--dry-run`；有口再 `--port`） |
| `deploy_import_checklist.md` | kissqy 上板勾选：镜像 / 方向 / P=32 / 部署缩放 |
| `ab_train.sh` | Phase B A/B m5 vs Feetech m6 |
| `bam_param_compare.md` | kt/R table: m5 / official m6 / Luwu ban |
| `stage0_software_prep.md` | 到货前：FD / **URT 接线（勿灌 V1）** / 表征 JSON / kissqy 镜像入口 |
| **`explore_heading_control.sh`** | heading A/B 的**无奖励控制臂**（kp8 / seed 42 / 4096×3000 / `ang_vel_z ±0.5`，零奖励项）。`DRY=1` 只看解析、`SMOKE=1` 跑 64×5。**不要**在 `explore_heading.sh` 上加 flag 来当控制臂：那个脚本的默认值就是**有**奖励，漏一个环境变量就变成另一条奖励 run |
| **`check_control_arm.py`** | 读 run 自己的 `params/`，断言"确实没有 heading 奖励、转向范围 ±0.5、envs/iters/seed 与奖励臂相同"。`--selftest` 6 项含两条负对照（奖励臂必须红、±1.0 无奖励臂必须红）与一条正对照（改成 ±0.5 后必须绿） |
| **`diff_run_recipes.py`** | 两 run 的 `params/*.yaml` 逐叶比对；只有 `--expect` 声明过的差异才放行。就是它查出"11-02 那条不止少奖励，还多 `ang_vel_z ±1.0`" |
| `sweep_heading_arms.sh` | 两臂按 stride 扫 checkpoint 走同一套 eval（32env×8s / cmd 0.4 / seed 11 / solver 100/50，与 `--baseline-set kp8` 同口径）；eval 自身 gates 红不算失败，没写出 JSON 才算 |
| `summarize_heading_ab.py` | **配对判决**：同 seed 同迭代的 `model_k` 成对，判 `median(Δerr_yaw)` 是否 ≤ −10% 且 ≥80% 同号，外加 vx ≥ 97% 护栏；exit 0 判定 / 2 判不了 / 3 完整性坏（两目录不是两臂、混了 eval 设置） |
| `sweep_cmd_envelope.sh` | **P4 前置：cmd 包线扫点**（0.15/0.2/0.3/0.4 × seed 11·22·33，与冻结基线同口径）。kp8 候选在 0.4 只到 cmd 的 41% ⇒ 部署前必须知道哪档开始塌；汇总只报 mean±sem 不作判决（判决归 `gate_p3_yaw.py`）。`TASK=` / `DEVICE=` 可换域（齿隙域跑同一脚本） |
| **`check_backlash_task.py`** | **齿隙域开训闸门**：断言 14 根 `passive_*_backlash` 铰链都在、范围 = ±deg/2、`limited`（死区必须是硬限位）、执行器是 `BacklashEncoder*`（PD 读输出侧）、奖励/命令与基础任务逐键一致、**obs/act 仍 61/14**、执行器仍是 hd1910（`kp_fw=8`）。`--selftest` 6 项：基础任务必须判红、反向断言下必须绿、期望 3° 时必须红 |
| `server_pack/` | **Windows 训练机打包**（4070 Ti）：`make_transfer.ps1` + `bootstrap.ps1`（勿拷 venv） |
| **`servo_probe/hd1910_ident.py baud` / `mode`** | **robotd 开机硬校验的两项 EEPROM**：reg6 要 `1`(500 kbps)、reg33 要 `0`；出厂是 `0`(1 Mbps) 和 `4`。`feetech.rs:386` 不符就拒绝打开总线，而"波特率错的舵机根本读不到"⇒ 症状与没上电一样。写入用**唯一验证过的时序**（解锁 0.25 → 写 0.50 → 上锁 0.50 → **断电回读**）；`set-id` 一并改用它（原来 0.05 s 窗口是假成功） |
| **`servo_probe/identify_joints.py`** | **只读**解 `[bus] joint_ids`：逐关节提示"扳哪个、怎么扳"，每 ID 采 3 s 峰峰值，阈值 8 步(≈0.7°)、第二名须 < 第一名一半，否则判"分不清"——不猜。最后打印可粘贴的 `joint_ids = [...]`，并与 `model.rs:15` 参考表逐项对照。`--selftest` 10 项 |
| **`servo_probe/set_protection.py`** | **保护开关（reg19 卸力条件）落盘 + 断电复核**。判决 `13 = 电压+过热+过流`；**过载位(32)刻意不开**（kp8 带载稳态误差会被判成"被挡住"⇒ 卸力 2 s ⇒ 走路必摔）。`--apply` 写、`--verify` 断电后复核、`--selftest` 9 项。15 颗装机时逐颗跑 |

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
.venv-mjlab/Scripts/python.exe tools/hd1910/sts_bench.py --dry-run

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
