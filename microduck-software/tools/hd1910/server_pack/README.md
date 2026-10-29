# Windows 训练服务器打包（4070 Ti）

**结论：不要拷本机 `.venv-mjlab`（~5 GB、路径/驱动绑定）。**  
拷一份 ~50 MB 的可复现安装包，在服务器上用 `bootstrap.ps1` 重装。

出处：本机成功栈 `torch 2.9.1+cu128` + `mjlab 1.3.0` + editable `bam-62bd8ce…`；  
Windows 渲染 `MUJOCO_GL=glfw`（见 `tools/hd1910/smoke_train.sh`、`MEMORY.md`）。

---

## 0. 服务器前提

| 项 | 谁装 |
|---|---|
| OS | Windows 10/11 或 Windows Server（x64） |
| GPU 驱动 | **你装**：Game Ready / Studio（需能跑 CUDA 12.8 用户态；一般不必另装完整 CUDA Toolkit） |
| **winget** | **`bootstrap.ps1` 自动装**（注册 App Installer → WinGet.Client 修复 → GitHub msixbundle） |
| **Python 3.12** | 同上，经 winget 装（已有则跳过） |
| **Git for Windows** | 同上（给 `*.sh` 提供 `bash.exe`） |
| 磁盘 | 建议 ≥40 GB 空闲（venv + logs + ckpt） |

本机 8 GB 卡甜点 **4096**；Ti 12 GB **先 4096**，冒烟后再试 **6144 / 8192**。

---

## 1. 在本机打 zip

```powershell
cd microduck-software
powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\make_transfer.ps1
# → out\hd1910_win_train_pack_YYYYMMDD.zip
```

包内含：`bam-62bd8ce…`、`microduck_rl-develop`、`tools/hd1910`、`tools/bam_params`、本目录脚本。  
**不含** `.venv-mjlab`、`logs/`、大 ckpt（需要权重另 `rsync`/`robocopy`）。

---

## 2. 在服务器安装

```powershell
# 解压后（建议「以管理员身份」开 PowerShell，方便 winget 装 Python/Git）：
cd D:\train\microduck-software   # 任意路径
powershell -ExecutionPolicy Bypass -File tools\hd1910\server_pack\bootstrap.ps1
# 选项：
#   -SkipHostTools   已有 Python 3.12 + Git
#   -SkipSmoke       只装环境、不跑 64×5 冒烟
```

脚本会：缺则 **先装 winget** → 再装 **Python 3.12 + Git** → 建 `.venv-mjlab` → `torch==2.9.1`（cu128）→ mjlab 栈 → **editable bam-62bd8ce**（勿整包装 ftservo-bam）→ 装 microduck 任务包 → **补丁 `train.py` 在 win32 用 glfw** → `apply_to_live --plant hd1910_kp5`（默认，**P3 目标**；要复现旧数字加 `-Plant hd1910`）→ **默认跑 `smoke_train.sh`**（须 log 含 `device=cuda:0`）。
植物闸门不过会直接 `throw` 中断引导，不会带着错植物继续装。

国内可设：`$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"`（torch 仍走官方 cu128 索引）。  
**不把 winget/Python/Git 二进制打进 zip**；运行时从微软/GitHub 拉官方包。

---

## 3. 冒烟通过后开训

**bootstrap 冒烟仍是 Velocity**（验 GPU/`cuda:0`）。平地走已有 `model_5999` 时，下一场景用 **StandUp**：

```powershell
# 禁止： set CUDA_VISIBLE_DEVICES=   （空串 → CPU）
$env:MUJOCO_GL = "glfw"
# 1) StandUp 冒烟
& "C:\Program Files\Git\bin\bash.exe" tools/hd1910/smoke_standup.sh
# 2) 4070 Ti 探索（trick：1024×1000；勿用 velocity 5999 续）
$env:ENVS = "1024"; $env:ITERS = "1000"
& "C:\Program Files\Git\bin\bash.exe" tools/hd1910/explore_standup.sh
# 曲线像样后再正式：
# $env:ENVS="4096"; $env:ITERS="4000"; bash tools/hd1910/explore_standup.sh
```

仍训 Velocity 时：`explore_train.sh` / `resume_train.sh`。  
若用了 `-SkipSmoke`，先手动：`bash tools/hd1910/smoke_train.sh`。  
ckpt / ONNX 用 `robocopy` 拉回本机做 eval / parity / 彩排即可。

---

## 4. 铁律（与本仓一致）

1. **`MUJOCO_GL=glfw`**（Windows 上 `egl` 非法）  
2. **`--gpu-ids '[0]'`** → `cuda:0`；勿空 `CUDA_VISIBLE_DEVICES`  
3. BAM pin = **`bam-62bd8ce…`**；⚠️ 陆吾 `1910_m6.json` 的问题**不是**名字（旧的说法是误判），
   而是它写了 `max_velocity:100`（≈5730°/s）把官方 5.2155 rad/s 的内部限速悄悄拆掉了
4. 植物 live **默认 `hd1910_kp5`** = P3 训练目标（官方 m6 参数 + 官方 STS3215 控制律 + `kp_fw=5`）。
   要复现已归档数字用 `-Plant hd1910`（m5 / `kp_fw=32`）—— 二者不是同一台机器，别混读
5. 契约仍是 **obs 61 / act 14 / 50 Hz**

版本钉扎：[`pins.txt`](pins.txt)。  
Linux 服务器另写配方（`MUJOCO_GL=egl`）；本目录只服务 **Windows**。
