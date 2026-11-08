# MicroDuck 官方/社区项目全景可挖掘清单（自充电之外）

> 日期：2026-11-08
> 触发：用户「先记录下来，再看看除自充电外其他方面还有没有可挖掘的」+「继续」
> 方法：先**列全 `.upstream` 目录树**再逐条读真源（吸取 MicroDock 四步反转的教训：不列全目录就下「没有」的结论 = 错）。
> 本文件只记**已核实的真源**；凡是「看起来可以去找 X」但没当场读的，一律进 §5「未查」，不算结论。

## 0. 前情（已记录，不重复展开）

- 自充电官方方案 = **MicroDock / MicroDock-v2**，权威文档：`docs/hardware/microduck-MicroDock官方深度挖掘-2026-11-08.md`（源码级，含 v1/v2 全部仿真脚本、训练 patch、几何、7 份结果 JSON）。
- 最终定性：真·官方 Playground 实验项目，但**不在 main 发布分支、不进已发布策略 manifest、sim-only 真机从未测过**；HD-1910 移植五门槛 R1~R5（R4 延迟耦合、R5 磁吸 ≤~6N 为深挖新增）。
- 项目日志 `.workbuddy/memory/2026-11-08.md` 第 105–114 行已完整记录。

## 1. 结论速览（按「贴本项目现状 × 可落地性」排序）

| # | 方向 | 真源 | 与本项目关系 | 要不要动手 |
|---|---|---|---|---|
| A1 | **hd1910m 的发布/部署闸门** | `.upstream/hd1910m/scripts/*.py` | 另一条独立实现，365+ 测试、标定联锁、诚实边界清单 | **强烈建议对照**（不烧 GPU）|
| A2 | **loco-diag 的行走训练诊断** | `.upstream/loco-diag/` | issue #46 的 air_time 门控/侧漂/指标高估，与本项目踩过的 gait bug 同源 | **强烈建议静态对照 cfg**（不烧 GPU）|
| A3 | **666wsp HD-1910 IMU 模组手册** | `.upstream/666wsp-microduck-hd1910/imu_dev_guide.md` | 给出硬件 IMU 延迟 8.3ms / 120Hz，可核观测时序假设 | 建议读全（不烧 GPU）|
| A4 | **awesome-microduck 生态索引** | `.upstream/awesome-microduck/` | 策略注册表 + `revocations.json` 撤销机制 = 本项目没有 | 记录为工程治理参照 |
| A5 | **microduck-lumi 中文复刻 SOP** | `.upstream/microduck-lumi/docs/调试/` | 硬件到货后逐关节配 ID/零位/方向的现成手册 | 到货时启用 |
| A6 | **esp-duck（ESP32-S3 跑 9 策略）** | `.upstream/esp-duck/` | 三重量化精度关卡；「别买板」之外的 MCU 级路线 | 记录为选型线索 |
| B1 | official-joy 手柄训练配方 | `.upstream/official-joy-2026-10/` | **正好是暂缓的 P4**，现成 checkpoint 选择依据 + 全套 diff | 仅当启动 P4 |
| B2 | playground/experiments 7 能力 | `.upstream/playground/experiments/` | 全部 sim-only；ONNX 契约/齿隙建模可借方法论 | 需训练时再看 |
| B3 | superpowers 7 plans + 8 specs | `.upstream/playground/docs/superpowers/` | 官方「如何设计一个 RL 任务」的一手模板 | 需训练时再看 |
| C | ft1910 / imu-displace / avanx-imu / replica* / build-tutorial / community-kit / mdlab / hf-policies | `.upstream/` 各目录 | 硬件/协议/复刻一手资料 | 硬件阶段再挖 |

---

## 2. A1 —— hd1910m：另一条独立的 HD-1910 复刻部署链（**最值得对照**）

`hd1910m` = Radxa ZERO 3W + 飞特 HD1910M ×15 + BNO08x 的第三方复刻线（**与本项目记忆里的「hd191m 线 / FT-SCS 原生协议」同源，不是 DuckBuddy-main 那条 OrangePi + feetech_hls 线**）。它自带一套**与本项目 conductor 同构但独立实现**的发布闸门，四个脚本已全部读完：

| 脚本 | 真源里读到的硬事实 | 对本项目可对照点 |
|---|---|---|
| `configure.py` | ① 默认 `--allow-motion` 关闭 = **只读模式**；② 只有 `calibration_verified` **且** `imu_pose_verified` 都为真才允许动，否则 `raise ValueError`；③ 四个 ONNX 逐个 SHA256 校验后才写配置；④ 文档字符串明写「Never changes servo EEPROM or enables torque」 | 🔴 **本项目 `calibration_verified=false` 目前只是注释/待办标记，没有做成硬联锁**。这是可直接借鉴的安全 gate——参照它把「标定未验证 ⇒ 拒绝上电运动」写进部署链 |
| `validate_artifacts.py` | 生成 `docs/release_validation.json`：`hardware_tested_this_release: False`、`rust_tests` 分项计数（duck_control 128 / robotd 145 / integration 7 / params 87 / backend 7）、`python_contract_tests: 12`、`four_graph_hash_contract_and_scheduler: passed with real ONNX graphs and native ORT`、**`limits[]` 逐条列出 5 条未验证边界**（无新实机测试、无新长训、固定基座仿真不是步态验收、起身/翻滚只是单次成功样本、其他初态仍失败） | 与 Pass15 的 `PASS*` 同一思想，但它把「诚实边界」做成了**结构化 JSON 证据**，比一句 verdict 更可机读 |
| `fetch_models.py` | 按 `manifest.json` 固定 `commit` + `source_directory` 拉四个权重，逐个 SHA256 校验，不一致直接 `RuntimeError` | 与 Pass13 provenance 互补：它管**下载时**校验，本项目管**导出后**溯源 |
| `audit_release.py` | 扫 git index：阻断 `target/.venv/logs/training_runs`、APK/MP4/PT 等大文件、正则扫 `ghp_/hf_/PRIVATE KEY` 凭据、symlink，生成 `docs/source_manifest.json`（全文件内容哈希清单） | 本项目 Pass12 只补了 `requirements.txt` 依赖清单，**没有发布审计/凭据扫描** |

**交叉印证（重要）**：`hd1910m/docs/training.md` 原文要求「训练环境与部署必须逐项核对：关节名称顺序、61 维观测、14 维动作、各模型 HOME、动作历史、EMA、目标限幅及 50Hz 时序；舵机 ID/方向/零位和 IMU 安装变换属于实机配置，不是 BAM `q_offset`」——这正是本项目 `verify_policy_contract.py` 在做的事。**两条独立实现收敛到同一份契约清单**，是难得的第三方验证（不是自己说自己绿）。

另：`hd1910m/radxa/installation.json` 实测 `calibration_verified: False`、`imu_pose_verified: False`、`mapping_confirmed: True`、`imu_mount_wxyz: [0.5,-0.5,0.5,-0.5]`——与本项目「标定未验证、IMU 变换待核」状态一致。

## 3. A2 —— loco-diag：官方 issue #46 的完整诊断（**与本项目踩过的坑同源**）

`.upstream/loco-diag/README.md` 是社区对 `pollen-robotics/microduck_rl` issue #46「走路训不出来」的复现+修复报告（RTX 4070 单卡、4096 env、5000 iter），三条结论都有源码行号：

1. **`air_time` 门控漏洞**：`feet_air_time`（`rewards.py:L209`）只判断 `total_command > threshold`，**不问实际有没有前进** ⇒ 被命令前进却原地踏步照样拿满权重 3.0 的抬脚奖励。报告人测得 `air_time≈0.002`（脚不离地），复现得 `0.9997`（脚一直抬但不走）。加「实际水平速度达指令 30%」门控后 `error_vel_xy` 0.43→0.35。
2. **侧向漂移**：逐帧身体系速度显示侧漂达前向 **2 倍**（第 7 步 前向 +0.112 / 侧向 −0.230），因跟踪奖励对两轴等权。侧向误差 ×3 + 跟踪权重 2→4 后侧漂降到 1/5，误差 0.35→0.21。
3. **`error_vel_xy` 指标高估约 3×**：混合五类指令模式 + 整回合累积平均（含起步 ramp-up），逐帧稳态 0.07 vs 日志 0.206。

🔴 **为什么这条最该看**：本项目记忆里明确记着「为了对齐上游 `air_time` 才去测脚高、才撞出 gait bug」、以及「世界系 vs 体坐标系」那个语义差——**A2 是同一族问题的第三方完整诊断 + 4 份可提 PR 的 diff**（`patches/air-time-fix.diff`、`all-changes.diff`、`vision-task.diff`、`windows-fix.diff`）。可直接静态对照本项目训练 cfg 的 air_time 门控、侧向权重、评测指标口径，**不需要烧 GPU**。

报告自列局限「没有多种子重复，每套配置只跑一次」——与本项目铁律「同 seed 不保证轨迹一致 ⇒ 需 N 次重复 + sem」及 P3 暂缓完全呼应。

## 4. A3~A6（已核实要点）

- **A3 `666wsp-microduck-hd1910`**：HD-1910 专用 IMU 模组 IMU_TO_DXL v1.2 开发手册（另有 SCH 原理图 PDF、固件 `.bin`、OTA 工具、使用指导手册 PDF）。硬参数：CH32V203 + **LSM6DSV16X**（内置 SFLP 硬件融合）、从站 **ID 200**、**1 Mbps**、单线半双工 TTL 3.3V、四元数+陀螺、**120 Hz**、姿态延迟**最坏 8.3 ms**、总线 OTA；FT 紧凑块起始地址 56 / 15 字节，Dynamixel 兼容块 124 / 12 字节。→ 本项目「训练侧 IMU 延迟包络 0–20ms、`imu_median=false`（中值=纯一拍 20ms 延迟）」可与这份硬件延迟实测对齐核一次。
- **A4 `awesome-microduck`**：生态总索引，`readme.md` 有 20+ 分类（含 *Agent Tools and MCP*、*Community Hubs and Registries*、*Ports to Other Simulators*）。**`policies.json` + `revocations.json`（撤销清单，当前为空）+ 两份 schema** = 策略注册表治理，本项目无对应物。
- **A5 `microduck-lumi`**：中文复刻文档库。`docs/调试/常见坑位.md` 十类（舵机/电源/主控/3D打印/装配/策略/训练/采购/紧急回退/求助），`docs/调试/舵机配ID与方向校正.md` 含 HD-1910-C001 参数、逐颗配 ID（每次只接 1 颗）、零位方向校正、`calibration.json` 结构、飞特协议层自检。→ **硬件到货后 `bus.joint_ids` 逐关节复核的现成 SOP**。
- **A6 `esp-duck`**：ESP32-S3 上 50Hz 跑官方 9 策略，逐通道 INT8 权重 + FP32 激活，单次 9.61ms（2× 余量），9 策略运行时热切换，BMI270 接观测；**宿主机 / 板端 / 每次开机三重量化精度关卡**，官方 9/9 PASS；README 有一节「硬件与 IDF 的坑（每条都付出过一次刷机代价，别清理它们）」。→ 本项目 SBC 选型结论是「此刻最优是别买板（台架 PC + URT-2 ¥0）」，esp-duck 是 MCU 级备选，仅记录为线索。

## 5. 诚实标注：本轮**没查**的方向（写在这里 ≠ 查过了）

按项目铁律「『下一步』里写的资料线索 ≠ 已经查过」，以下只列目录/首行，**未读内容、未下结论**：

- `playground/experiments/` 七个能力（basketball 单 LSTM 无球状态 / chimney-climb / desk-climb / parkour 后空翻 / running iter-12195 / stilts / swing 自泵秋千）：只 grep 了 README 的 checkpoint 与 sim-only 声明，**未读训练源码、未核权重**。已确认共性是全部明确标注「Simulation only; not hardware validated」且多数带 HF 权重 + RUNTIME 契约 + CPU/ONNX 数值对拍（desk-climb 报 2.63e-6 / 9.54e-7）。
- `playground/docs/superpowers/plans/`(7 份 10–65KB) + `specs/`(8 份 5–23KB)：只列了文件名（roller-crouch-glide / roller-slope / ground-pick-pose-following / shoot / swizzle-head-control / roller-standup / spin-env），**未读正文**。
- `official-joy-2026-10/`：读了 `run.json`(task `Mjlab-JoySmoothPD-Flat-MicroDuck`、selected index 300、`target_conditioner alpha=0.25/max_step_rad=0.08`、training dt 0.001 vs deploy dt 0.0002、scope 明写「Development tuning, not an unseen-game cohort or hardware validation」)、`patch-application.json`、`selected-agent.yaml` 头部；**474KB 的 `selected-run-git.diff` 与 49KB `selected-env.yaml` 未读**。
- `ft1910` / `imu-displace` / `avanx-imu` / `ftservo-bam` / `bam-mjlab_frictionloss` / `mdlab` / `replica` / `hw-replica` / `replica-kit` / `build-tutorial` / `community-kit` / `hf-policies` / `policies/continuous_joy.onnx`：只列了顶层文件名。
- `playground/src/mjlab_microduck/`：只读了 `onnx_policy_contract.py` 前 120 行与 `add_backlash.py` 前 60 行，其余未读。

## 6. 一条被**负对照否掉**的疑似缺口（记录免得以后重挖）

看到 `playground/src/mjlab_microduck/onnx_policy_contract.py` 的 `bake_action_clip` / `bake_action_bounds`，文档字符串写得很硬：「`RslRlVecEnvWrapper` 训练时 clip actor 输出，部署 runtime 直接吃 ONNX 输出 ⇒ 必须把 clamp 烤进导出图，否则 action history 与训练不一致」——第一反应像是本项目部署链的真缺口。

**当场核完否掉**：
- 本项目 `logs/rsl_rl/*/params/agent.yaml` **全部 `clip_actions: null`**（28 份逐份 grep），训练时本就不 clamp；
- 本项目动作是 `JointPositionActionCfg`（`repo/train_ppo.py` `ACTION_SCALE=1.0`），**不是** `BoundedJointPositionAction`；
- 本项目 `eval_ground_pick.py` 里那段 `clip = float(getattr(agent_cfg,"clip_actions",0.0) or 0.0)` 对 null 恒为 0，等于不执行；
- 三个部署闸门脚本 grep `clip` 只有 `verify_policy_bundle.py:707` 一处 `np.clip(o,-1,1)`（obs 裁剪，非动作）。

⇒ 那工具是给 playground 自己那些**有界动作/LSTM 实验**（篮球、爬桌、秋千）用的，对三个 kp8 主线策略**不适用**。**不是缺口，不要改代码**。这条再次印证「读数与算术上下界矛盾 ⇒ 先怀疑结论而不是急着改」。

## 6.1 Pass17 回填（2026-11-08）：A3 已核实，§5 那条「未查」销项

> 按铁律「『下一步』里写的资料线索 ≠ 已经查过」，本轮把 §7 第 4 条**当场查完并写结果**，不再挂账。

- **读全三条独立一手资料**：`666wsp.../imu_dev_guide.md` 全文（LSM6DSV16X SFLP / 120 Hz / 最坏 8.3 ms / ID 200 / 1 Mbps / 15 B 飞特块含 status+sequence / Dynamixel 兼容块 addr124/12 B / STALE>30 ms / READER_SLOW≥5 样本 / 建议读取 ≥50 Hz）；`avanx-imu/README.md`（同款芯片、挂总线冒充 ID 200、**直接引用本项目 `imu.rs` 的 `DEFAULT_MOUNT`**，第三方交叉印证）；`imu-displace/IMU-MODULE.md`（独立实现，实测 100 Hz / 0.92 ms / 全零块 1–2% / 「50 Hz 周期不被拖慢」验收项）。
- **本项目侧真跑** `verify_imu_chain.py`：训练 cfg 延迟窗口实读 **`0–1 steps = 0–20 ms`**、median ON = **+20 ms** / OFF = **0**、`ready()` = 50 Hz 下 **500 ms**，13 项全 PASS / 15 条负对照一致。
- 🔑 **关键差异（之前不知道）**：手册的 15 B 块带 `status`/`sequence`，而本项目 `imu.rs` 的 `IMU_BLOCK_LEN=12` 是手册的 **Dynamixel 兼容块** ⇒ `STALE`/`READER_SLOW` 三个状态位在本部署链**根本不可见**，`ready()` + 全零哨兵是 robotd 自有替代。120 Hz 是芯片 SFLP 输出率，与 50 Hz 同步读**不矛盾**（手册明写建议 ≥50 Hz）。
- **量化结论**：median OFF ≈ 0–8.3 ms（落在训练窗口内）；median ON = 20 + [0, 8.3] = **20–28.3 ms**，超窗口上界 20 ms。toml 注释的「20–30 ms」是保守近似，方向正确。⇒ **`imu_median=false` 的结论成立，不需改配置**。
- **负对照否掉一条疑似缺口**：`audit_robotd_toml.py` R14 只把 `imu_median=true` 判 WARN（不影响退出码），看似「危险配置不拦」；但 checklist B20 明写「台架若真看到单块尖峰，改回 true 并记录原因」= **故意的人工豁免通道**，与「只建议不强制」不是同类 ⇒ **不改代码**，只记录 20–28.3 ms 边界。
- **副产物**：`verify_imu_chain.py`（13 项检查 / 15 负对照、覆盖策略最前 6 个观测数）此前**只被 README/checklist 提及，从未被 conductor / CI / pytest 调用**——本轮已接进 `pytest tests/`，缺完整栈时诚实 SKIP 并显式列出。

## 7. 建议的下一步（按性价比，均不烧 GPU）

1. **A2 静态对照**：✅ Pass16 已完成（结论：本项目 `error_vel_xy` 口径早已独立修得更彻底，air_time/侧漂为第三方反向印证，不需改训练）。
2. **A1 借鉴标定联锁**：Pass16 已借鉴其语义写入 `verification_boundary`，**未接进 robotd**（两线不同代，不可混用）；若将来要硬联锁须单独评估。
3. **A1 借鉴诚实边界清单**：✅ Pass16 已完成（`verification_boundary` 块 + `--verify` 交叉核对）。
4. **A3 核 IMU 时序**：✅ **Pass17 已完成，见 §6.1**。

> 硬件端到端验证仍未启动（硬件未到货）；P3（≥3 seed sweep）用户暂缓；P4 可选。以上均不改变该状态。
>
> ✅ **Pass18 已解决（2026-11-08，用户裁定「按最优的来」→ 入库并打通）**：证据资产已纳入 VCS（`git add -f` 3 个部署 onnx 2.27 MiB + 9 个只读契约源 450 KiB；补 `!out/runmeta_*.json` 后 add 34 个伴随 meta）。`assert_clean_checkout.py --strict` 升级为 CI 硬门禁，探针输入清单由 5 项补全为实测的 9 项，verdict 拆成 `ci_scope_gate_possible`（CI 四关）与 `ci_full_gate_possible`（五关含训练栈）；workflow 首次真跑 `pytest tests/` 与三策略真闸门。用 `sitecustomize` 模拟 lean CI 实测：36 passed / 26 skipped、三份 `PASS*`（contract 显式 SKIP，其余四关真 PASS）、`provenance --verify` rc=0。详见 `docs/active/microduck-对比缺陷清单-2026-11-07.md` §4.8。
>
> 唯一仍在 CI 之外的 `contract` 关（需 torch/mujoco/mjlab_microduck）保留**显式 SKIP**，本地 `.venv-mjlab` 五关全 PASS 为发货前权威验证；workflow 末尾打印该边界。
