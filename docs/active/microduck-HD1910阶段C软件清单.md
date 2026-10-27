# HD1910 阶段 C · 真机软件清单（并行草稿）

日期 2026-10-26。**无整机前只准备入口与闸门，不宣称能走。**  
依据：`microduck-HD1910软件方案.md` §4.C、`../hardware/microduck-采购清单.md` §7、  
`.upstream/replica-2026-10/software_飞特适配架构.md`、kissqy / fanhao 公开说明（本仓摘录）。

---

## 0. 一句话

**不自写 robotd。** 部署链跟 `kissqy/Microduck-kissqy`（control.43 + R17/V167 镜像）  
或 fanhao 的 Feetech fork；策略侧继续 **obs 61 / act 14 / 50 Hz / ONNX+normalizer**。

---

## 1. 运行时选型（只选一条主链）

| 选项 | 来源 | 拿什么 | 许可 / 坑 |
|---|---|---|---|
| **主推荐：kissqy 镜像** | `kissqy/Microduck-kissqy` | 预编译镜像、中控、固件 control.43、R17→**V167**（修鸭身抖动 / D 相关） | 作者原创部分**个人非商业**；陆吾 BAM 勿当训练主植物 |
| 备选：fanhao Feetech 适配 | `fanhao375/microduck-replica` + 其 kissqy fork | `-FT` CAD/BOM；`feetech-sts` 总线层、方向表、`robotd.toml` 协议键 | 自编 daemon 上板要**自签开发密钥**（官方私钥拿不到） |
| 明确不用 | `pollen-robotics/microduck` 原版 | — | 只认 Dynamixel / XL330 |
| 明确不用 | 自写 Feetech daemon | — | 方案 §5 禁止；与 50 Hz 环、安全、IPC 重复造轮 |

**判据（有板之后）：** `robotctl health` bus 绿、loop **50 Hz 0 missed**；  
`protocol = "feetech-sts"`；P/D/转矩与训练合同一致（V167：上力写 D=0 等——以当时镜像说明为准）。

---

## 2. 部署契约（训练侧必须对齐，已有）

| 项 | 值 | 出处 |
|---|---|---|
| obs | **61** | 官方 velocity；`microduck_rl` AGENTS / export |
| act | **14** | 同上 |
| 频率 | **50 Hz** | 同上 |
| 导出 | ONNX **烘焙 normalizer** | `scripts/export.py` / 本仓 export 链 |
| 热切换 | 多策略同观测布局 | 官方 playbook；勿改 obs 维数 |

本仓已有彩排工具（XL330 交付物）：`tools/rehearse_deploy.py`、`NEXT-deploy-rehearsal.md`。  
**HD1910**：同一套契约 + 植物指纹 — `tools/hd1910/rehearse_hd1910.py`（patch BAM→m5/`kp_fw=32`，默认探索 ONNX）。不要换 obs 布局。

---

## 3. 阶段 0 台架（硬件到了才跑；软件准备现在可写）

采购口径见 `../hardware/microduck-采购清单.md` §7（HD1910 路线 ≈¥299 台架）：

| 步 | 动作 | 闸门 |
|---|---|---|
| 0.1 | HD-1910 ×1 + **URT-1**（不是 U2D2）+ 限流电源 | ping / 改 ID / 1 Mbps |
| 0.2 | 50 Hz 连续读写 | **事务 ≤5 ms**；0 CRC |
| 0.3 | 辨识 kt/R（OpenMicroDuck 摆锤脚本可复用） | 与 m5 / 飞特 m6 对照表比对（`../../microduck-software/tools/hd1910/bam_param_compare.md`） |
| 0.4 | 确认固件 P（reg 50）= **32**（训练 `kp_fw`） | 与 BAM 一致 |

未过 0.2 之前：**不要买齐 15 颗。**

---

## 4. 上板软件顺序（有 Radxa + 镜像之后）

1. 刷 kissqy 镜像（下载入口见 `../../microduck-software/tools/hd1910/stage0_software_prep.md`）；记下 **确切版本号**（R17 / V164 / V167…）。  
2. 确认中控 / robotd 认 Feetech；方向表逐颗核对（fanhao：HD1910 读数方向常与 XL330 相反，多为 −1）。  
3. 写入舵机 RAM：P / D / 转矩限制与该镜像合同一致（V164 曾不写 D→出厂 40 发颤；V167 有修——**以你刷到的版本 release note 为准**）。  
4. 导出本仓 HD1910 策略 ONNX → 板上热加载；跑本仓 **parity**（若有）+ 短站立，再谈走路。  
5. sim2real 结论必须带：**植物指纹（m5 或 ftservo m6）+ 镜像版本 + P/D**。

---

## 5. 现在就能做的（无硬件）

| # | 动作 | 状态 |
|---|---|---|
| C-prep-1 | 本文清单入库 | ✅ 本文件 |
| C-prep-2 | 参数对照 m5↔飞特 m6↔陆吾禁 | ✅ `../../microduck-software/tools/hd1910/bam_param_compare.md` |
| C-prep-3 | A/B 短训脚本（训完切植物） | ✅ `../../microduck-software/tools/hd1910/ab_train.sh` |
| C-prep-4 | 确认 export/ONNX 路径对 HD1910 run 可用 | ✅ ONNX + **parity 过**（`max|Δ|=1.6e−6`，`out/parity_hd1910_explore_4096x2000_1026_it1999.json`） |
| C-prep-5 | 采购阶段 0 四项是否下单 | 人决策（清单 §7） |
| C-prep-6 | 续训脚本 | ✅ `tools/hd1910/resume_train.sh`（默认接到 6000） |
| C-prep-7 | 阶段 0 / 镜像软件入口 | ✅ `tools/hd1910/stage0_software_prep.md`（FD、表征 JSON、kissqy R1/V167 链接） |
| C-prep-8 | HD1910 部署彩排入口 | ✅ `tools/hd1910/rehearse_hd1910.py` / `.sh`（m5 / kp 32；跑 sweep 写 `out/rehearse_hd1910_*.json`） |
| C-prep-9 | URT-1 台架脚本骨架 | ✅ `tools/hd1910/urt1_bench.py`（`--dry-run`；live 待 SDK/FD） |
| C-prep-10 | kissqy 上板导入勾选清单 | ✅ `tools/hd1910/deploy_import_checklist.md`（镜像/方向/P=32/缩放 0.9·0.5·0.7） |

---

## 6. 明确不做（阶段 C）

1. 不把 XL330 的 `walk_std004_*` 部署到 HD1910 真机  
2. 不自写飞特总线 daemon  
3. 不以仿真 ratio 单独宣称「真机已会走」  
4. 不用陆吾 `1910_m6`（`actuator: sts3215`）做上机模型  

---

*草稿；有板后把「镜像版本 / robotctl 截图 / 事务时延」补进日记忆。*
