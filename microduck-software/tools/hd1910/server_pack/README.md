# Windows 训练服务器打包（RTX 4070 Ti）· P3 seed sweep

**结论：不要拷本机 `.venv-mjlab`（~5 GB、路径/驱动绑定）。**
拷一份 ~30 MB 的可复现安装包，在服务器上用 `bootstrap.ps1` 重装。

出处：本机成功栈 `torch 2.9.1+cu128` + `mjlab 1.3.0` + editable `bam-62bd8ce…`（2026-11-09 用本机 venv 逐项回读过）；Windows 渲染 `MUJOCO_GL=glfw`。版本钉扎见 [`pins.txt`](pins.txt)。

---

## 🔴 2026-11-09 修订摘要（相对 10-27 那版，务必看）

| # | 改动 | 为什么 |
|---|---|---|
| 1 | **默认 plant `hd1910_kp5` → `hd1910_kp8`** | 当前部署主线是 kp8（`apply_to_live.py --check` 本机实测 `detected hd1910_kp8 / kp_fw=8.0`），唯一走路级候选 `p8head_2999` / `model_7999` 都在 kp8；且 `explore_ground_pick.sh:35` **硬性要求 kp_fw=8.0**，旧包切 kp5 会直接红 |
| 2 | **打包清单补 `tools/train_heading_variant.py` 等 5 个顶层 .py** | 10-27 那份 zip **不含**它，而 `explore_heading.sh` / `smoke_heading.sh` 都调它 ⇒ 装完 5 GB venv 第一次开训就 file-not-found |
| 3 | **新增 `verify_pack.py` 打包前硬闸门** | 从包内所有 `.sh` 反推 `tools/*.py` 引用并逐个验存在（不是手抄清单）；带 3 条负对照自检，缺文件不许压缩 |
| 4 | **冒烟显式传 `PLANT=p8`** | `smoke_heading.sh` 默认 `PLANT=p3`(kp5)，若服务器已切 kp8 会误判植物闸门红 |
| 5 | **新增 P3 sweep 编排 `p3_sweep.sh` + 选点 `p3_select.py`** | 台账 #76：三动作各 ≥3 seed、同 plant 评测取中位数+sem 选点；`explore_heading.sh` 原先**没传 `--agent.seed`**，连跑 3 次会得到 3 份完全相同的 seed=42 run（已纯新增修好，默认 42 行为不变） |

> ⚠️ **「P3」在本项目有两个口径**，别混：
> - **本包默认配套的 P3 = 台账 #76 的「≥3 seed sweep 选点」**（行走 / 拾取 / 站起），跑在 **kp8**。
> - **11-02 那次「P3+heading 合并重训」是 plant `kp5` 的一次训练**（`explore_heading.sh PLANT=p3`）。要复现那条旧线的数字，用 `bootstrap.ps1 -Plant hd1910_kp5` + `PLANT=p3`，不要拿它的数字和 kp8 的比。
> 「换 plant = 换任务必须重训」，两者不是同一台机器。

---

## 0. 服务器前提

| 项 | 谁装 |
|---|---|
| OS | Windows 10/11 或 Windows Server（x64） |
| GPU | **RTX 4070 Ti（12 GB，Ada sm_89）** |
| GPU 驱动 | **你装**：Windows 驱动 **≥ 572.61**（CUDA 12.8 Update 1 下限，NVIDIA CUDA Toolkit Release Notes Table 3；12.8 GA 是 ≥570.65）。`nvidia-smi` 的 CUDA Version 行应 ≥12.8。一般不必装完整 CUDA Toolkit |
| **winget** | `bootstrap.ps1` 自动装（App Installer → WinGet.Client 修复 → GitHub msixbundle） |
| **Python 3.12** | 同上（已有则跳过；也可用 `$env:MICRODUCK_PYTHON` 指向现成解释器） |
| **Git for Windows** | 同上（给 `*.sh` 提供 `bash.exe`） |
| 磁盘 | ≥40 GB 空闲（venv + logs + ckpt） |

本机 8 GB 卡甜点 **4096**；Ti 12 GB **先 4096**，冒烟后再试 **6144 / 8192**。

---

## 1. 在本机打 zip

```powershell
cd microduck-software
powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\make_transfer.ps1
# -> out\hd1910_win_train_pack_YYYYMMDD.zip
```

包内含：`bam-62bd8ce…`、`microduck_rl-develop`、`tools/hd1910`（含本目录）、`tools/bam_params`、`tools/train_heading_variant.py`、`tools/eval_velocity_in_sim.py`、`tools/check_onnx_parity.py`、`tools/gate_p3_yaw.py`、`tools/plant_id.py`、顶层说明。
**不含** `.venv-mjlab`、`logs/`、大 ckpt（权重另用 `robocopy`/`rsync`）。

打包脚本在压缩前跑两道闸门：`verify_pack.py --root <stage>`（导数依赖检查）+ `p3_select.py selftest`（13/13，含负对照）。任一红就不生成 zip。

---

## 2. 在服务器安装

```powershell
# 解压后（建议「以管理员身份」开 PowerShell，方便 winget 装 Python/Git）
cd D:\train\microduck-software   # 任意路径
powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1
# 选项：
#   -SkipHostTools   已有 Python 3.12 + Git
#   -SkipSmoke       只装环境、不跑 64x5 冒烟
#   -Plant hd1910_kp5  复现 11-02 的 P3/kp5 线（默认 hd1910_kp8）
```

脚本会：缺则装 winget → Python 3.12 + Git → 建 `.venv-mjlab` → `torch==2.9.1`(cu128) → mjlab 栈 → editable bam → microduck 任务包 → 补丁 `train.py` 在 win32 用 glfw → **preflight 验 8 个关键文件**（缺就早退，不再等装完才发现）→ `apply_to_live --plant hd1910_kp8` → **默认跑 `smoke_heading.sh` 并传 `PLANT=p8`**（须 log 含 `device=cuda:0`）。植物闸门不过直接 `throw`，不会带着错植物继续装。

国内可设 `$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"`（torch 仍走官方 cu128 索引）。**不把 winget/Python/Git 二进制打进 zip**。

---

## 3. P3 seed sweep 训练（本包主要用途）

Git Bash 里（训练脚本自己会 `export MUJOCO_GL=glfw`、unset 空 `CUDA_VISIBLE_DEVICES`、查 `device=cuda:0`）：

```bash
# 三动作 x 3 seed = 9 次训练；默认 envs/iters 是各脚本的探索规模
bash tools/hd1910/server_pack/p3_sweep.sh

# 只跑行走、放大规模
TASKS="walk" SEEDS="42 43 44" WALK_ENVS=4096 WALK_ITERS=3000 \
  bash tools/hd1910/server_pack/p3_sweep.sh

# 只打印命令、不烧 GPU
DRY_RUN=1 bash tools/hd1910/server_pack/p3_sweep.sh
```

- 每次 run 名带 `task/seed/envs/iters`，不会同分钟覆盖；`out/p3_sweep_manifest.jsonl` 逐行记录成功/失败，**失败即停**，重跑自动跳过已 `status=ok` 的 `(task,seed,envs,iters)`。
- 三个任务的植物要求不同：`explore_heading.sh` 用 `PLANT=p8`、`explore_ground_pick.sh` 硬查 kp_fw=8、`explore_standup.sh` 用 `PLANT=p8` 并自己 apply —— 编排脚本已分别处理。

选点（**同 plant、固定仪器**：64 envs × 8 s、cmd 0.4、eval seed 0，缓存复用）：

```bash
PY=.venv-mjlab/Scripts/python.exe
$PY tools/hd1910/server_pack/p3_select.py select \
    --manifest out/p3_sweep_manifest.jsonl --out out/p3_sweep_summary.json
# 只打印评测命令：加 --dry-run
```

输出每个 run 的 `primary / risk`（walk = `vx_median_of_env_means` / `terminated_frac`；拾取与站起 = `success_rate` / `fall_rate`）、按任务的中位数+sem、以及**双轴排序**（primary 降序、risk 升序）后的推荐 run。缺字段直接报错而不是当 0。`selftest` 13/13 含 3 条负对照（高风险不得胜出 / 缺字段必须抛 / `status=ok` 无 ckpt 必须红）。

> ⚠️ 这是**跨训练 seed 的选点**，不是因果比较；按项目铁律「checkpoint 抖动要外层 sweep 选点」，**不能用单次评测翻案**。评测仪器一旦改变（envs / seconds / cmd / plant / seed），旧缓存数字不得与新数字相除——`compare_sweeps.py` 会拒绝打印这种 delta。

---

## 4. 回传与边界

- ckpt / ONNX 用 `robocopy` 拉回本机做 eval / parity / 部署链彩排（`check_onnx_parity.py` 验 ONNX 与 ckpt 是否同一颗）。
- **没有做**：500k 真机 16 设备总线预算（需整机 + IMU 板）、示波器位宽、目标板推理耗时。台架 R3 仍冻结（用户拍板不切 `reg6`），本包与硬件 EEPROM 无关。
- Linux 服务器另写配方（`MUJOCO_GL=egl`）；本目录只服务 **Windows**。

---

## 5. 铁律（与本仓一致）

1. **`MUJOCO_GL=glfw`**（Windows 上 `egl` 非法）
2. **`--gpu-ids '[0]'`** → `cuda:0`；勿空 `CUDA_VISIBLE_DEVICES`
3. BAM pin = **`bam-62bd8ce…`**；陆吾 `1910_m6.json` 的问题不是名字，而是 `max_velocity:100` 把官方 5.2155 rad/s 内部限速拆掉了
4. **默认植物 `hd1910_kp8`**（官方 m6 参数 + 官方 STS3215 控制律 + `kp_fw=8`）。`-Plant hd1910_kp5` 是旧 P3 重训线，`-Plant hd1910` 是 m5/kp32 归档线 —— 三者数字不可混读
5. 契约仍是 **obs 61 / act 14 / 50 Hz**
6. **训练 seed 必须显式传**：`--agent.seed`（`explore_heading.sh` 现在通过 `SEED=` 暴露），否则 3 次 sweep 会退化成同一份结果
