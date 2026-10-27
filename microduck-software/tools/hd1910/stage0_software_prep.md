# 阶段 0 · 到货前软件准备（无硬件）

对应 `docs/active/microduck-HD1910阶段C软件清单.md` §3 与采购清单 §7.6。

## 0.1 / 0.2 / 0.4 — 总线闸门（到货用）

| 项 | 工具 | 准备 |
|---|---|---|
| ping / 改 ID / 1 Mbps | 飞特 **FD 调试软件** + **URT-1** | 本机安装 FD；确认能枚举 USB-UART |
| 50 Hz、事务 ≤5 ms | FD 连续读写或本仓 STS 骨架 | 不必自写 daemon |
| 固件 P（reg 50）= 32 | FD 或骨架 gate 0.4 | 与训练 `kp_fw` 一致 |

本仓骨架（无硬件可先 dry-run；有口再 `--port COMx`）：

```bash
.venv-mjlab/Scripts/python.exe tools/hd1910/urt1_bench.py --dry-run
# .venv-mjlab/Scripts/python.exe tools/hd1910/urt1_bench.py --port COM5 --id 1
```

Live 后端未内嵌 FTServo SDK：先 FD 过闸；若本机已装 `scservo_sdk`，再把 `PortHandler` 接到 `urt1_bench.try_open_live()`。

**不要**用 U2D2。

## 0.3 — kt/R 对照（资料已在仓）

本仓已有 OpenMicroDuck 台架表征（对照用，不是你的新测）：

- `.upstream/j_hd1910_calibration_params_hd1910_characterization.json`
- 训练用汇总：`tools/bam_params/hd1910/m5.json`
- 对照表：`bam_param_compare.md`

采购文曾写 `record_pendulum_bench.py`：**公开树里未检索到同名文件**（2026-10-26）。到货后优先：

1. FD / 官方协议读电流·速度做简易估计，或  
2. 复用 BAM / 社区摆锤流程（有脚本再链进本目录）  

测完与上表比对即可，不必等「同名脚本」。

## 0.4 — 固件 P=32

FD 读寄存器 **50**，应与训练 `kp_fw=32` 一致。

## 部署镜像入口（有板再刷；现在可收藏）

来源：本地 `.upstream/kissqy/README.md` / [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)

| 件 | 链接 |
|---|---|
| 系统镜像 R1 | https://github.com/kissqy/Microduck-kissqy/releases/tag/public-image-r1 （`microduck-zero3w-0.15.1-R1.img.xz`） |
| 机器人中控 V167 | https://github.com/kissqy/Microduck-kissqy/raw/refs/heads/main/release-assets/Microduck-Console-R17-V167.zip |
| 训练中控（可选） | `release-assets/Microduck-Training-Studio-R1.5.27.zip` |

许可：作者原创部分**个人非商业**。不自写 robotd。

## 上板导入勾选（有板）

见 **`deploy_import_checklist.md`**（镜像 V167、方向表、P=32、运行端 0.9/0.5/0.7）。

## 本仓已跑通的软件闸门

```bash
# ONNX parity（obs 61 → act 14）
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/parity_smoke.sh

# 回头续训（默认接到 6000 iter）
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/resume_train.sh
```
