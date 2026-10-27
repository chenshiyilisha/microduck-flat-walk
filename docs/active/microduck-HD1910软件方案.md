# MicroDuck HD-1910 软件方案（采集开源长处）

日期 2026-10-26。硬件定案：**飞特 HD-1910-C001 ×15**（见 `../hardware/microduck-采购清单.md` §7、
`../archive/microduck-国内自制方案.md` 已证伪段）。本文只定**软件怎么拼**，不重复 BOM。

**工作区入口**：[根目录 `README.md`](../../README.md)（文档地图 + 命令）。  
**真机清单**：[阶段 C](microduck-HD1910阶段C软件清单.md)。**工具**：[tools/hd1910](../../microduck-software/tools/hd1910/README.md)。

### 当前进度（滚动）

| 项 | 状态 |
|---|---|
| 植物 live | OpenMicroDuck **m5**（`kp_fw=32`）；A/B 后已切回 |
| GPU smoke 64×5 | ✅ `hd1910_smoke_1026_gpu2` |
| 探索 1024×2000 | ✅；P-walk **未过**（ratio≈0.34） |
| 探索 4096×2000 | ✅；P-walk **过**（vx0.4 ratio≈**0.62**）；ONNX `out/hd1910_explore_4096x2000_1026_it1999.onnx` |
| 续训 4096→≈6000 | ✅ `model_5999.pt`（`…_to6000_1027`）；P-walk **过**（vx0.4 median/cmd≈**0.76**）；`translates_forward` ✅（1999 时否）；仍 `not_sideways` ❌ |
| A/B m5↔m6 1024×500 | ✅ 两腿 `cuda:0`；短训均 **100% fall**（500 不够判植物） |
| 探索 8192×2000 | ⛔ 已停（~13/2000）；本机 8GB 上 ~100 s/iter、显存顶满，非甜点 |
| 飞特 m6 | JSON+别名就绪；**勿整包装** ftservo-bam；长训仍主 **m5** |
| ONNX + parity（5999） | ✅ `out/hd1910_resume_4096_to6000_1027_it5999.onnx`；parity max\|Δ\|≈**2.5e−6** |
| 彩排（5999） | 名义/低电/高电 **过**；`train_lag3/4/6` 仍挂（与 1999 同类；CPU MuJoCo±delay 非训练同仪） |
| 下一步 | **人：阶段 0 下单**；软件侧当前交付物可用；暂不必要再长训 / 换 m6 |

---

## 0. 一页结论

| 层 | 采用谁的 | 不采用谁的 |
|---|---|---|
| **训练框架** | 官方 `pollen-robotics/microduck_rl`（mjlab 1.3 / PPO / 61×14） | `tailong-wu/microduck-mjbatch`（仅作历史脚手架） |
| **执行器植物** | **OpenMicroDuck 台架 m5**（已在本仓 `tools/bam_params/hd1910/`）作**当前可跑基线**；目标升级到 **飞特官方 BAM** `feetech_hd1910_7_4V` m6 | 陆吾 `1910_m6.json`（`actuator: sts3215` 错标） |
| **任务适配参考** | `qiaosiyi/microduck_rl_hd1910`（33 任务全改、质量 +3 g×15、公开 iter2000） | 其 DcMotor「规格书临时模型」——只作对照，不作主植物 |
| **真机运行时** | `kissqy/Microduck-kissqy` control.43 + R17 V167（或 fanhao 镜像 fork） | 官方 `pollen-robotics/microduck` 原版（只认 Dynamixel） |
| **机械/CAD/装配** | `fanhao375/microduck-replica` 飞特版 `-FT` | XL330 舵盘件 |
| **评估协议** | 本仓已有 `eval_velocity_in_sim` / 彩排 / parity（契约 61/14 不变） | 换植物后旧 XL330 ckpt **不可热插拔** |
| **部署契约** | obs 61 / act 14 / 50 Hz / ONNX + normalizer | 改 obs 维数的实验（Walk These Ways 式）— 二期再说 |

**原则**：契约不动；植物可换；改上游只做**可逆覆盖**，不永久 patch 官方 blob。

**铁律（2026-10-26 用户裁定）**：遇事先查资料，再改代码 / 下结论。
落地见 `.cursor/rules/look-up-first.mdc` 与 `workbuddy-history/memory/MEMORY.md` §0。

---

## 1. 开源长处对照（采什么）

| 来源 | ★ / 状态 | 采 | 弃 / 慎用 |
|---|---|---|---|
| **官方 microduck_rl** | 2645★ | 任务定义、奖励、课程、export/infer、AGENTS.md 方法论 | XL330 BAM kwargs（`motor_name=xl330`, `kp_fw=200`） |
| **qiaosiyi/microduck_rl_hd1910** | 10★ | 全任务 HD1910 接线清单、质量修正算法、smoke 矩阵、公开权重作**负对照** | `datasheet_based_provisional` 植物；HOME 开环 8/8 摔是已知事实 |
| **飞特 ftservo-bam** | Gitee 官方 | `feetech_hd1910_7_4V` m1–m6、`kp=32`、`error_gain=0.163`、mjlab 集成 | PyPI `better-actuator-models` **不含** HD1910，必须本地装 Gitee 克隆 |
| **OpenMicroDuck 辨识** | 本仓已镜像 | 72 摆锤 + 48 腿实测 → m5：`kt=0.692`, `R=3.75`, delay 25.3 ms | 5 V 台架口径；上 7.4 V 时 vin 改、kt/R 可沿用 |
| **kissqy** | 291★ | 真机镜像、中控、固件、采购账单、抖动修复（D=0） | 许可：原创部分**个人非商业**；陆吾参数勿当主植物 |
| **fanhao375/microduck-replica** | 1356★ | `-FT` CAD、BOM、装配教程、踩坑、训练工程打包 | 早期「待步态验收」记录；以当前 README 真机演示为准并自验 |
| **zhuoligetu123/hd1910m** | 28★ | 四模型 + APK 作部署对照 | **原始接线图作者自标有错**，勿照抄 |
| **本仓已有工具** | — | `tools/bam_actuators.py`、`tools/plant.py` HD1910 SPECS、`eval_velocity_in_sim`、`train_velocity.sh` | `walk_std004` XL330 权重（交付物归档，不上 HD1910 机） |

### BAM 参照链（纪律）

```
hd1910_our_measured_m*     # 终点：自己台架（阶段 0 之后）
hd1910_ftservo_official_m6 # 目标强先验：飞特 Gitee（装好后切换）
hd1910_openmicroduck_m5    # 当前基线：本仓 tools/bam_params/hd1910/m5.json  ← 先跑通
hd1910_luwu_1910_m6        # 历史对照 ONLY，禁止当训练主植物
```

---

## 2. 仓库布局（本工作区）

```
microduck-software/
  tools/
    bam_actuators.py          # 已有：注册 hd1910 / hl2915 到 BAM
    bam_params/hd1910/m5.json # 已有：OpenMicroDuck 台架
    plant.py                  # 已有：HD1910 SPECS（CPU 植物）
    hd1910/                   # ★ 本方案新增
      plant_spec.py           # 单一真相：数字 + 出处
      apply_to_live.py        # 可逆覆盖 site-packages 植物
      smoke_train.sh          # 64×5 冒烟
      restore_xl330.sh        # 一键恢复 XL330 植物
  .upstream/
    microduck_rl-develop/     # 官方任务包快照（对照用）
    j_hd1910_*.json           # 辨识原文
    kissqy/                   # 真机参考摘录
.upstream/dew_repo/           # 主线文档与 XL330 交付归档（flat-walk）
```

训练仍走 `.venv-mjlab` + `Mjlab-Velocity-Flat-MicroDuck`；换植物 = 换
`FrictionDRBamActuatorCfg` 的 `json_path` / `kp_fw` / `vin_*`，**不改任务 ID、不改 obs**。

---

## 3. 植物切换（当前可执行）

覆盖点：`site-packages/mjlab_microduck/robot/microduck_constants.py` 里
`_BAM_ACTUATOR_KWARGS`（与上游 `microduck_rl-develop` 同源）。

| 键 | XL330（现状） | HD1910（目标基线） |
|---|---|---|
| `motor_name` / `json_path` | `xl330` + bundled m6 | **`json_path` → `tools/bam_params/hd1910/m5.json`** |
| `kp_fw` | 200 | **32** |
| `vin_range` | (6.5, 8.2) | (6.5, 8.2) 保持 |
| `delay_*_lag` | 3–6 | 3–6（25.3 ms ≈ 1.3 控制拍，落在区间内） |

质量 +3 g×15、齿隙 XML：**二期**（对照 qiaosiyi），冒烟不阻塞。

命令（实现见 `tools/hd1910/`）：

```bash
cd microduck-software
# 切到 HD1910 植物（写 live + 留 .xl330.bak）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910

# 冒烟：64 env × 5 iter —— **必须 GPU**（cuda:0）；Windows 固定 MUJOCO_GL=glfw（勿 egl）
bash tools/hd1910/smoke_train.sh

# 评估（沿用现有脚本，checkpoint 换成 HD1910 run）
.venv-mjlab/Scripts/python.exe tools/eval_velocity_in_sim.py \
  --checkpoint logs/.../model_*.pt --num-envs 32 --seconds 8 --cmd-vx 0.4

# 恢复 XL330（对照实验用）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant xl330
```

训练铁律：正式训练走 **GPU `cuda:0`**；CPU 只做探针。见 `.cursor/rules/look-up-first.mdc`。


---

## 4. 分阶段交付

### 阶段 A — 今天～2 天（仿真植物跑通）

1. ~~`apply_to_live.py --plant hd1910` + smoke 64×5~~ **已过（2026-10-26）**  
   - plant gate：`detected=hd1910`，`kp_fw=32`，live sha16 `f3d62a7a51de2bfe`  
   - GPU smoke：`hd1910_smoke_1026_gpu2`，`device=cuda:0`（RTX 4070），64×5，iter≈1.34s，无 NaN  
   - 戳记：`out/plant_*.json` / `out/runmeta_hd1910_smoke_1026_gpu2.json`  
   - Windows 坑：mjlab `train.py` 曾硬编码 `MUJOCO_GL=egl`（本机非法）→ 已改 win32→glfw；空 `CUDA_VISIBLE_DEVICES` 会逼 CPU，smoke 脚本会 unset  
2. 探索档  
   - ~~1024×2000~~ **已完** `hd1910_explore_1024x2000_1026`（`cuda:0`，model_1999）——摸底，**未过 P-walk**  
   - ~~4096×2000~~ **已完** `hd1910_explore_4096x2000_1026`——**P-walk 过**（ratio≈0.62）  
   - **8192×2000**（RL_duck §2.1 甜点）——进行中 `hd1910_explore_8192x2000_1026`  
   - 量级对照仍是 ~590 M 环境步（RL_duck §3.1）；本轮 8192×2000 ≈ 393 M step（24×8192×2000）  
3. 同协议评估 32env×8s：  

   | run | vx=0.4 ratio | no_fall | 备注 |
   |---|---|---|---|
   | 1024×2000 | 0.34 | ✅ | 未过 P-walk |
   | **4096×2000** | **0.62** | ✅ | **过闸**；yaw 仍漂；ONNX 已导出 |
   | A/B m5/m6 ×500 | ~0.13 / 0.14 | ❌ 100% | 短训不可比植物 |

4. 文档：runmeta 写 `plant=hd1910_openmicroduck_m5`（smoke / explore 已写）

### 阶段 B — 本周（对齐官方 BAM）

1. ~~克隆 `gitee.com/ftservo/ftservo-bam`~~ **已做**（`.upstream/ftservo-bam` @ `4f7c0b0`）  
   - ⚠️ **不能**把 ftservo-bam 整包 editable 盖掉训练用 bam：官方 `BamActuatorCfg` 把  
     `vin_drop_gain_range` 改成了 `vin_drop_resistance_range`，microduck 植物立刻  
     `unexpected keyword`（2026-10-26 实测）。  
   - **现行 pin**：`.venv-mjlab` editable → `.upstream/bam-62bd8ce…`（`vin_drop_gain_range`，与 4096 训一致）  
   - 官方仓只取：**参数 JSON + 对照**；控制类暂走本仓 `tools/bam_actuators.HD1910Actuator`  
2. ~~大小写别名~~ **已做**：表键 `HD1910` vs JSON `hd1910` → `bam_actuators` 双注册  
   - 本地参数：`tools/bam_params/hd1910/ftservo_official_m6.json`（actuator=`HD1910`）  
   - ftservo clone 内 `actuators.py` 亦补了小写键（仅参考，未装进 venv）  
3. ~~切植物 m6~~ **A/B 时已切过**；长训主线 **切回 m5**（`apply_to_live.py --plant hd1910`）  
4. ~~A/B 短训~~ **已完** `ab_train.sh both`（1024×500，seed 42）  
   - 结果：m5/m6 **均 100% fall、ratio~0.13**——500 iter 不够分离植物；**不以短训改主植物**  
   - 参数表：`tools/hd1910/bam_param_compare.md`  
   - 待 8192/加长后再做 **同量级** m6 对照  

### 阶段 C — 与硬件并行（真机栈）

清单正文：`microduck-HD1910阶段C软件清单.md`（2026-10-26 并行起草）。

1. 部署侧跟 kissqy V167 / fanhao 镜像（不自写 robotd）——入口与许可已写入清单 §1  
2. 阶段 0 台架：URT-1 + 1 颗，事务 ≤5 ms，复核 kt/R——闸门见清单 §3；软件骨架 `tools/hd1910/urt1_bench.py`（`--dry-run`）；待硬件  
3. ONNX export + parity ✅；部署彩排入口 `tools/hd1910/rehearse_hd1910.py`（m5 / kp_fw=32）  
4. 有整机后再做 sim2real；仿真结论不得单独宣称「真机已会走」

### 阶段 D — 能力补强（可选，植物稳定后）

- 低速死区：QRC 式接触计数 + 自适应 σ（见既有参考资料清单）  
- 质量/齿隙：合并 qiaosiyi XML 修正  
- head_pose 冻结评估：补交互维度

---

## 5. 明确不做

1. 不把现有 `walk_std004_1250`（XL330）部署到 HD1910 真机  
2. 不用陆吾 m6 当训练主植物  
3. 不改 obs_len / action_len（一期）  
4. 不自写飞特总线 daemon（用 kissqy/fanhao）  
5. 不以 qiaosiyi 规格书 DcMotor 替代 BAM  

---

## 6. 成功判据（软件侧）

| 闸门 | 通过条件 |
|---|---|
| P-plant | `apply_to_live --check` 回读 `json_path` 含 `hd1910` 且 `kp_fw==32` |
| P-smoke | 64×5 结束、无 NaN、写出 ckpt |
| P-walk | 32env×8s cmd 0.4：`no_fall` 且 ratio≥0.5（探索档下限，非交付线） |
| P-meta | runmeta 含 plant 指纹 + bam 参数 sha256 |
| P-revert | `--plant xl330` 后 cfg sha 回到官方 XL330 口径 |

交付线（ratio≥0.75 等）等阶段 A 出数后再钉，避免空定门槛。

---

## 7. 与旧文档的关系

| 文档 | 关系 |
|---|---|
| `../archive/microduck-国内自制方案.md` | 硬件选型已过时（S288）；**软件跟本文** |
| `../hardware/microduck-采购清单.md` §7 | 硬件花钱顺序；本文管软件 |
| `microduck-最优方案.md` | 曾推 HL-2915；**用户已定 HD1910**，HL 仅作对照 |
| `.upstream/dew_repo/docs/05-flat-walk.md` | XL330 交付档案保留；新实验进 HD1910 runmeta |

---

*依据：本仓 `tools/plant.py` / `bam_actuators.py` / OpenMicroDuck 表征 JSON；
qiaosiyi、kissqy、fanhao、ftservo-bam、LuwuDynamics 公开 README；检索日 2026-10-26。*
