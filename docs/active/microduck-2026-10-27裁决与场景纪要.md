# 2026-10-27 裁决与场景纪要

把当日讨论钉成可查记录。施工细节仍以各专项文档为准；本页只记**结论与出处**。

相关：[软件方案](microduck-HD1910软件方案.md) · [阶段 C](microduck-HD1910阶段C软件清单.md) · [采购 §7](../hardware/microduck-采购清单.md) · [upstream 摘录核对](microduck-upstream摘录核对.md) · [XGO 对照](../reference/microduck-XGO-Duck对照.md) · [tools/hd1910](../../microduck-software/tools/hd1910/README.md)

---

## 1. 硬件 / 台架

### 1.1 URT-2 接线（已写入施工文）

一手：`.upstream/r_踩坑记录.md`。落地：`tools/hd1910/stage0_software_prep.md`。

- 外电/电池 → **舵机 V、G**；URT 只接 **S + 共地**；**V1 空着**（勿灌 7.4 V）。
- 拨码是 TTL 电平，不是外电切换；空载改 ID 可用 USB 上 V1≈5 V。
- AMP2.0 常插不进 URT 白座 → PH2.0 转接/飞线；一次一颗设 ID。
- **勿用 U2D2**；HD-1910 接 **TTL**；FD 波特率 **1000000**。

### 1.2 IMU 两套怎么选（阶段 2 才决策）

| 方案 | 是什么 | 何时 |
|---|---|---|
| **kissqy HAT+IMU 成品** | 淘宝贴片板（AMP2.0）；与 kissqy 镜像成套 | 本仓阶段 2 **默认**（清单 §7.4 / §7.5） |
| **HAT + 总线 imu_to_dxl 类小板** | LSM6、**ID 200**、1 Mbps；商业兼容板或 fanhao 自制 | kissqy 一键镜像 **只认总线 ID 200（FT6 身份）** 时才必需；纯 I²C 模块会卡「ID 200 无应答」（踩坑记录） |

阶段 0 **不必**买总线 IMU。先定镜像版本，再定板，避免买重。

私人改板 / EasyEDA Copilot 工具链（**后置、现不启动**）→ 见 [板子设计备忘](microduck-板子设计备忘.md)（2026-10-29）。

### 1.3 「组装好的飞特鸭」能省什么

| 项 | 组装机 | 自建阶段 0 |
|---|---|---|
| HAT / IMU 选型、URT 接线 | 大体省掉 | 必须过闸 |
| **台供（15 V/5 A 数显）** | **可不买**（日常靠 2S 电池） | 阶段 0 单颗验货用 |
| 电流电压物理 | **仍要管**：放电 C 率、满电再站（≥8.0 V）、线径/保险、掉电先查供电 | 同左；踩坑：「走路掉电多半是供电」 |

官方 $399 整机：只发北美/欧/英；转运估 ≈¥3.4k–3.8k；**XL330** 不是本仓 HD1910 植物。出处：采购清单 §0。

### 1.4 阶段 0 配件（路线 B）

见采购清单 §7.5 / canvas `hd1910-bom`：HD1910×1 + URT-2/1 + 限流电源或电池+保险 + 万用表 + 建议转接线 ≈¥299+；过闸再买齐。

---

## 2. 训练场景（本仓计划）

**现行只钉 2 个量级**（不是上游全任务表）：

| # | 场景 | 任务 ID | 状态 |
|---|---|---|---|
| 1 | 平地速度走 | `Mjlab-Velocity-Flat-MicroDuck` | **主交付已完**：`model_5999.pt` → ONNX + parity；P-walk ≈0.76；**不必再长训** |
| 2 | 摔倒爬起 | `Mjlab-StandUp-Flat-MicroDuck` | **可选刚开**；脚本见下；**不能**从 5999 续训 |

上游另有 VelStand / Rough / Dance / desk-climb 等 → **本仓 HD1910 阶段未排期**。阶段 D = 死区/齿隙/head_pose 补强，不是新任务 ID。

### 2.1 环境包（4070 Ti server_pack）预设

- bootstrap 默认：植物 **m5 / kp_fw=32**，冒烟 **Velocity 64×5**，`MUJOCO_GL=glfw`，`cuda:0`。
- 下一步文档已改为：冒烟后可改跑 **StandUp**（平地走已有交付时）。
- 出处：`tools/hd1910/server_pack/README.md`、`pins.txt`。

### 2.2 StandUp 脚本与墙钟（4070 级）

| 脚本 | 默认 | 预估墙钟（本机 4070 Laptop 吞吐外推） |
|---|---|---|
| `smoke_standup.sh` | 64×5 | ~1 min（2026-10-27 已过） |
| `explore_standup.sh` | **1024×1000** | ~35–45 min |
| 正式 | 4096×4000 | ~3.5–4.5 h |
| 上游 cfg 上限 | 4096×15000 | ~12–15 h（先看 1000/4000） |

实验名：`microduck_standup_hd1910`。续训：`resume_standup.sh`（须 `LOAD_RUN`/`LOAD_CKPT`）。  
吞吐依据：`out/train_hd1910_ab_m5_1024x500_*.log`（~1.7 s/iter）、`out/train_hd1910_explore_4096x2000_*.log`（~3.2–3.8 s/iter）。

4070 Ti 命令：

```powershell
$env:MUJOCO_GL = "glfw"
& "C:\Program Files\Git\bin\bash.exe" tools/hd1910/smoke_standup.sh
$env:ENVS = "1024"; $env:ITERS = "1000"
& "C:\Program Files\Git\bin\bash.exe" tools/hd1910/explore_standup.sh
```

---

## 3. kissqy vs 陆吾 XGO-Duck

公众号摘要：[买不到 MicroDuck？…升级版机器鸭](https://mp.weixin.qq.com/s/8bCXHcHy1onvZ8H93aNaBA)（陆吾 XGO-Duck；外形致谢 Pollen；Uno Q 双脑；飞特 1910；自带走/起身/拣选 ONNX）。

| 维度 | kissqy（本仓主推荐） | 陆吾 XGO-Duck |
|---|---|---|
| 定位 | 官方 MicroDuck 栈飞特适配 | 另起炉灶升级版 |
| 主控 | Radxa + 镜像/中控 | Arduino Uno Q（Linux 50 Hz + STM32 100 Hz） |
| 感知 | 可跟官方相机/ToF 路线 | 砍视觉，纯运动 + IMU |
| 现成策略 | 多配方；V167 修抖动 | 走+爬起+叼开箱有 |
| 许可 | 原创部分**个人非商业** | 硬件许可待定；**`xgoduck_rl` = Apache-2.0** |
| 植物 | 本仓 **m5**；禁陆吾 `1910_m6` | 默认 `1910_m6`（STS3215 错标风险） |

**本仓裁决（阶段 C）**：真机部署跟 **kissqy V167 / fanhao**；训练植物不用陆吾 m6。

**若只比「开箱成套运动鸭」**（忽略本仓沉没成本）：XGO-Duck **产品打包更完整**（手册/双脑/三策略）。  
**若比「自己训策略对齐 MicroDuck 生态」**：kissqy 更贴。

### 3.1 在 XGO-Duck 上自己训练？

**可以。** 仓：[`LuwuDynamics/xgoduck_rl`](https://github.com/LuwuDynamics/xgoduck_rl)。

```bash
uv run train Mjlab-Velocity-Flat-XgoDuck --env.scene.num-envs 4096
# StandUp / GroundPick / … 任务 ID 带 XgoDuck
uv run python scripts/export.py Mjlab-Velocity-Flat-XgoDuck …
```

- 任务/MJCF 是 **XgoDuck**，不是本仓 `*MicroDuck`；**勿**直接拿 `model_5999` 当 XGO 专用权重硬上。
- 建议换掉默认 `1910_m6`，用实测/官方 BAM 再训再上板。
- 摘录：`.upstream/xgo-2026-10/rl/README.md`；对照：`docs/reference/microduck-XGO-Duck对照.md`。

---

## 4. 当前优先级（钉死）

1. **人：阶段 0 下单**（路线 B；URT 勿灌 V1）。  
2. Velocity **不再长训**；交付物可用。  
3. 软件可选：4070 Ti 跑 StandUp 探索 1024×1000。  
4. 不切换主线到陆吾 Uno Q；陆吾资料只作对照与「可自训」备案。

---

## 5. 文档落地清单（本轮已改）

| 路径 | 改动 |
|---|---|
| `tools/hd1910/stage0_software_prep.md` | URT 接线图 |
| `tools/hd1910/smoke_standup.sh` 等 | StandUp 冒烟/探索/续训 |
| `tools/hd1910/server_pack/README.md` | Ti 上改跑 StandUp |
| `docs/active/microduck-HD1910软件方案.md` | 下一步含 StandUp |
| `docs/active/microduck-upstream摘录核对.md` | `.upstream` 核对 |
| **本页** | 当日总纪要 |

检索日：2026-10-27。
