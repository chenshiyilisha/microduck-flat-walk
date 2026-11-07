# MicroDuck / HD-1910 复刻线 — 对比官方与社区项目的缺陷清单

_日期：2026-11-07 · 对照对象：`pollen-robotics/microduck`（运行时，13.5k★）、`pollen-robotics/microduck_rl@develop`（训练）、本仓库复刻线 `.upstream/hd1910m/microduck_rl` 与 `microduck_rl-develop`。_

> **方法纪律**：所有「官方有什么 / 我们没有」结论，均先查一手源码（GitHub API + 拉取 env cfg / tests）再下结论，不靠记忆。本清单里有一条上一轮误判，已在本轮查证后**纠正并标注**（见缺陷 3）。

---

## 0. 结论摘要

- 本项目在**仿真评测严谨度**和**plant 专用重训体系**上已经做得比官方某些环节更深，不是「全面落后」。
- 真正的缺口集中在三块：**① 真机部署闭环**（硬件未到 + publish 链对 HD-1910 失效）、**② 可复现性 / provenance 基础设施**、**③ 真机时序编排 + 齿隙在正确电压下验证**。
- 上一轮我提出的「缺陷 3：站起 head-mask 防御没做」是**误判**：官方修复机制不是 head-mask，且 **HD-1910 活动上游（`hd1910m`）已经包含正确的站起修复**。本轮已纠正，该条改为「已具备」。
- 「缺陷 4：缺 tests/ 回归套件」**已于 2026-11-07 补齐**（`tests/test_hd1910_configs.py`，9 项，CPU 可跑，live kp8 实测通过）。
- **缺陷 1（真机加载自检）与缺陷 2（训练 provenance）已于 2026-11-07 当晚补齐**：conductor `pre_deploy_check.py` 串起 contract/bundle/numeric/toml 四关，实测抓到参考 `robotd_hd1910_mode0.toml` 缺 `bus.joint_ids` 的真实 blocker；provenance 已并入 `heading_meta` 与所有 `runmeta`（含给 4 个启动器补固定 seed）。

---

## 1. 本项目已经比官方更扎实的地方（别重复造）

- **评测严谨度**：`plant_id` 指纹 + 同 plant 评测 + 负对照 + 物理量分布检查，比官方 `publish` 仅做 NaN/常量输出检查严得多。曾据此纠正「kp8 行走 82% 摔」的跨 plant 误测（实为 m5 模型错放到 kp8 评测）。
- **ONNX 契约校验**：`verify_policy_contract` / `policy_numeric_gate` 已兜住 `deploy61` 1157× 放大 bug，比官方更硬。
- **plant 一等坐标 + swap_plant**：复刻线必须、官方不需要，已闭环证明「官方策略不能直接移植 HD-1910」（groundpick 96.9% vs 官方 23.4%）。
- **plant 健康自检**：`apply_to_live.py --check` 带回读门禁（reg6/33/9/11、kp_fw、json sha），是官方没有的。

---

## 2. 缺陷清单（按严重度）

### 缺陷 1 — 真机部署闭环 ⚠️ 战略级（部署链待硬件到货端到端，但「加载自检」已补齐）
- **官方**：`pollen-robotics/microduck` 有一套 `publish → robotctl policy add/load → robotctl robot do` 部署流；`policy-manifest.md` 定义 61 维观测契约，运行时热插拔 walk/recover/trick。
- **本项目**：硬件还在下单（Radxa 线）；且本项目文档已承认 **`publish` 与这一代 HD-1910 的 robotd 不是一条链**——manifest 字段一个都不生效，`robotctl policy load` 对 HD-1910 是另一套系统。当前所有「部署」只是 `rehearse_deploy.py` 的仿真彩排。**部署链本身要等硬件到货才能端到端验证，这一半仍是 OPEN。**
- **后果**：sim 再完美，真机上 ONNX+manifest 格对不对得上、能不能跑全是未知。
- **补后（2026-11-07 当晚）——「加载自检」已补齐，部署契约已定**：
  - **契约**：`tools/hd1910/deploy_import_checklist.md` 已把 HD-1910 真机部署契约写成 B/C/H 三段（obs 61 / act 14 / 50 Hz；normaliser 下限；manifest 不生效、B 代 robotd 真实吃哪些键；reg6/33/9/11 硬校验；`joint_ids` 必需等），无需另起文档。
  - **一键加载自检 conductor**：新增 `tools/hd1910/pre_deploy_check.py`，把现有 4 道独立守卫串成**一个 verdict**：
    - `contract`（`verify_policy_contract.py`）：obs/act 布局、关节序、HOME、action 映射 ↔ robotd `obs.rs`；
    - `bundle`（`verify_policy_bundle.py`）：normaliser 下限 + 元数据 + 无 EXTERNAL 权重 + joint_names；
    - `numeric`（`policy_numeric_gate.py`）：G1–G4 绝对量级门禁（兜住 `deploy61` 1157× 放大）；
    - `toml`（`audit_robotd_toml.py`，`--expect-kp 16` 匹配项目既定 reg50）：robotd.toml 增益标度一致性。
  - **已实测验证**：`--selftest` 四关全绿；对真实策略 `hd1910_resume_5999.onnx` ONNX 三关 PASS；对已知坏策略 `deploy61.onnx` 正确 FAIL（bundle+numeric 抓到 normaliser 地板击穿）；对参考 `robotd_hd1910_mode0.toml` 抓到 **`bus.joint_ids` 为空**——飞特总线拒绝打开，是真实 pre-deploy blocker（见下）。
  - **conductor 新暴露的 blocker**：参考 `robotd_hd1910_mode0.toml` **缺 `bus.joint_ids`（15 条）**。B12/H11 已写明这是必需的（空则总线拒绝打开，`robotd/src/main.rs:5495`），但参考 toml 一直空着。硬件到货前必须按 HD-1910 映射填 15 个 ID（B 代 schema：右腿 10–14 / 左腿 20–24 / 头 30–34；或 HD-1910 1–15 体系——需先定 schema 再填，不能照抄别的项目 `installation.json`）。conductor 现在会在这步判 FAIL，挡住「看起来能加载其实起不来」的静默事故。

### 缺陷 2 — 训练可复现性 / provenance 基础设施缺失 ✅ 已于 2026-11-07 当晚补齐
- **官方（2026-10-27 新增）**：`share-training` 把每次训练打成 HF bundle，带 git commit + 未提交 diff + 精确命令 + 父 ckpt + wandb 配置；`export.py` 把 `run_path/task_id/checkpoint/sha256` 烤进 ONNX 元数据。
- **本项目（补前）**：训练产物是本地 `.pt`，只有 ad-hoc 的 `out/runmeta_*.json`（含 plant/kp_fw/json sha/envs/iters）。**缺 git sha / diff / 精确命令 / seed**。目标「训练完美」但无法复现一个好 run，也无法从社区 ckpt 干净起步。
- **补后（2026-11-07 当晚）**：
  - 新增共享模块 `tools/hd1910/_provenance.py`：捕获 git commit / branch / dirty / **uncommitted-diff 指纹（sha256）** / 训练 seed / 精确命令 / 依赖版本（torch·rsl_rl·mjlab·onnxruntime·onnx·numpy）。
  - **heading 路径**：`train_heading_variant.py` 在写 `heading_meta_*.json` 时直接并入 `provenance` 块（覆盖所有 heading 训练 incl. `explore_heading.sh` / `resume_heading_run.py`）。
  - **standup / roller / groundpick 路径**：新增 `tools/hd1910/log_run_provenance.py`，把 `provenance` 合并进 `out/runmeta_<RUN>.json`；已接入 `resume_standup.sh` / `explore_standup.sh` / `train_roller.sh` / `explore_ground_pick.sh`（每个 run 一行）。
  - **固定 seed**：4 个启动器原本不传 `--agent.seed`（rsl_rl 默认，不可复现）——现在统一加 `SEED="${SEED:-42}"` 并传 `--agent.seed`，provenance 因此能捕获真实 seed；历史 runmeta 也可用 `log_run_provenance.py` 回填。
  - **实测**：对一个历史 runmeta 回填，正确拿到 `git 77de78d dirty=True diff指纹` + 依赖版本；`_versions` 经 `importlib.metadata` 兜底解析到 `mjlab 1.3.0`（rsl_rl 在本 venv 不可 import，如实记 `<absent>`，运行时经 `train.exe` 仍可用）。

### 缺陷 3 — 站起「冻背」固定点防御 ✅ 已具备（上一轮误判，本轮纠正）
- **上一轮误述**：我说官方用「head-masked teacher + head 50%/SO(3) 25% 加宽 spawn」。**查证后这是错的**——官方源码里没有 head-mask teacher，也没有这些概率。
- **官方真实修复**（`microduck_standup_env_cfg.py`，`improve_standup_velstand` 提交）：
  1. `set_ground_state` 事件里 `face_up_prob`（仰面/背朝地）从 **0.00 渐进到 0.35** 的反向课程（`ground_state_mix` 课程，step 0 → 600×24 → 1500×24 → 2500×24）；
  2. `face_up_roll_max = 90°` 的部分翻滚噪声，给「平躺→俯卧」这段无梯度的恢复提供中间起点（built-in reverse curriculum）；
  3. 基于 tilt 的奖励门控（`arrival_damping`、`head_pose_bias`，`tilt_full_deg=20`、`tilt_zero_deg=45`），且权重严格在 iter 3000×24 才从 0 引入——避免运动惩罚阻断恢复动作的「发现期」。
- **关键**：本项目活动上游 **`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/tasks/microduck_standup_env_cfg.py` 已经包含以上全部**（grep 实证 `ground_state_mix`、`face_up_prob` 0→0.35、`face_up_roll_max` 均存在）。所以 **P2 的 kp8 站起从零训会直接继承这套修复，无需单独移植**。
- **本轮新增保险**：`tests/test_hd1910_configs.py::test_standup_has_face_up_recovery_curriculum` 锁死 `ground_state_mix` 存在且末态 `face_up_prob>0`，防止后续某次上游合并把它弄丢。

### 缺陷 4 — 自定义任务缺回归测试套件 ✅ 已于 2026-11-07 补齐
- **官方**：`tests/`（CPU 回归）锁死关节索引映射、奖励符号约定、servo geom 命名、NaN 守卫；如 `test_velstand_cfg.py`。
- **本项目（补前）**：80+ 个 probe/eval 脚本，但根目录无 `tests/`。「关节 ID 两套体系不能混用」恰恰是静默回归最易炸的点。
- **补后**：新增 `microduck-software/tests/test_hd1910_configs.py`（9 项，CPU-only，build cfg + compile MuJoCo，不步进 env），live `hd1910_kp8` 实测 9 passed：
  - 驱动关节数 == 14、关节顺序 == 规范 HD-1910 顺序（防跨编号体系静默 remap）；
  - allcollisions / walk / standup 三套 spec 关节运动学一致；
  - servo collision geom ≥ 14；
  - velocity 奖励符号约定（pose/track_*/upright/air_time 正，foot_slip/self_collisions/dof_pos_limits/action_rate_l2 负）；
  - velocity / standup cfg 能正常构建；
  - 站起 `ground_state_mix` 反向课程存在且末态 `face_up_prob>0`。
- **运行**：`.venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_configs.py -q`（需先 `apply_to_live --plant` 任一 HD-1910 变体；非 HD-1910 plant 时整套 skip）。

### 缺陷 5 — 齿隙（backlash）仿真未在正确电压下验证
- **官方**：齿隙建模为串联无驱动被动铰链，编码器/固件 PD 透过齿隙读数，obs 也读透过齿隙——sim2real 关键。
- **本项目**：HD-1910 是飞特舵机（非 XL330/BAM），有 `check_backlash_task.py` + Backlash 任务，但：① 是否「透过齿隙读数」未确认；② 台架是 4.6 V 欠压取的数，不可靠。
- **补法**：换 7.4 V 正确电压重测飞特齿隙，确认仿真模型与真机齿隙一致、编码器读透过齿隙。

### 缺陷 6 — 多策略热插拔彩排工具对 HD-1910 是坏的
- 官方 `infer_policy.py` 一套键盘热插拔 walk/stand/sitstand/roulade + sim2real CSV。
- 本项目 `rehearse_deploy.py` **写死 XL330/kp200**，文档明说「不要用它跑 HD1910」。HD-1910 没有可用的多策略彩排。
- **补法**：参数化 servo 类型 / kp（读 `apply_to_live` 的 live 值），或新增 HD-1910 专用 rehearsal。

### 缺陷 7 — 真机缺 phase / 姿态 flag 的时序编排器
- 官方由 daemon 驱动「地面拾取」的相位命令和「坐↔站」的姿态 flag。
- 本项目 groundpick 在 sim 里用相位命令，但**真机上没有控制器去驱动相位/flag**——phase 类策略上真机就没人喂时序。
- **补法**：随 SitStand + VelStand 一起做真机时序编排（缺陷 8 的动作补全项）。

### 缺陷 8 — 上游非 plant 专属改进需 re-sync（元缺陷）
- 上游自上次对照后新增：站起/velstand 鲁棒性修复（**已在 hd1910m**）、provenance 基础设施、pickup detector（PR #70）、转向改进。
- 其中**站起鲁棒性已确认在 hd1910m**；pickup detector / 转向改进是否已在 hd1910m 需再核（建议下次对照时逐条 grep `microduck_ground_pick_env_cfg.py` 与 velstand 转向项）。
- 与 plant 无关、又能直接提升质量的，优先 cherry-pick / re-sync。

### 缺陷 9 — HD-1910 打印件许可风险
- 官方把 STL 网格钉死在 **CC BY-NC-SA 4.0（非商用）**。若 HD-1910 飞特版 3D 打印件派生自官方网格，商用受限。下单前先核 CAD 来源许可。

---

## 3. 动作覆盖对比（官方有 / 我们没有）

| 动作 | 官方 | 本项目 | 优先级 |
|---|---|---|---|
| **SitStand**（坐↔站指令） | ✅ Flat/Rough | ❌ 无 | **高** |
| **VelStand**（走+摔倒恢复合一） | ✅ v7 + lineage | 仅注册，未训 | **高**（对应 P4，建议提前） |
| **Rough 地形变体** | ✅ 多数任务有 | ❌ 只有 Flat+DR | 中 |
| **Roulade**（前滚翻） | ✅ | ❌ | 低 |
| **BallKick**（踢球） | ✅ | ❌ | 低 |
| **Swizzle / Spin**（轮滑花样） | ✅ | 只有 plain Rollers | 低 |
| **Running**（跑） | 社区有 | ❌ | 低 |

> 本项目已注册 Rollers / RollerCrouch / RollerSlope / RollerStandUp 四个轮滑任务，但 kp8 轮滑重训 89% 摔（欠训），按用户决策延后。

---

## 4. 下一步（接 P0–P4 训练计划）

1. **硬件到货前**：真机部署契约已定 + 加载自检 conductor 已落地（缺陷 1 后半）；剩余 = 部署链端到端验证（待硬件）+ rehearsal 工具（缺陷 6）。✅ **参考 `robotd_hd1910_mode0.toml` 已补 `bus.joint_ids` + `joint_signs`**：取自权威 `.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`），ID 顺序 `[10,9,8,7,6,12,11,14,13,15,5,4,3,2,1]`，**不同于** XL330 参考 `[20-24,30-34,10-14]`。审计由 FAIL(空)→WARN(非参考集，预期内)，conductor toml 关转 PASS。真机到货仍需 `servo_probe/identify_joints.py` 逐关节复核（`calibration_verified=false`）。
2. **本次已落**：tests/ 套件（缺陷 4）+ 站起修复保险（缺陷 3 的测试化）+ 加载自检 conductor（缺陷 1 后半）+ provenance（缺陷 2）。
3. **provenance（缺陷 2）**：✅ 已落 —— heading_meta 与所有 runmeta 已含 git/diff 指纹/seed（4 个启动器补固定 seed）。
4. **动作补全**：优先 SitStand + VelStand（缺陷 7 时序编排一起做），tricks 类最后。
5. **齿隙（缺陷 5）**：硬件/电源到位后换 7.4 V 重测。
6. **re-sync（缺陷 8）**：下次对照逐条 grep 上游 pickup detector / 转向改进是否已进 hd1910m。

---

## 5. 证据索引（本轮查证）

- 官方站起修复：`pollen-robotics/microduck_rl@develop` → `src/mjlab_microduck/tasks/microduck_standup_env_cfg.py`（`set_ground_state`、`ground_state_mix`、`face_up_roll_max`）。
- HD-1910 已含修复：`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/tasks/microduck_standup_env_cfg.py` grep 命中 `ground_state_mix` / `face_up_prob` 0.00→0.35 / `face_up_roll_max=math.radians(90)`。
- 官方 tests 范式：`.upstream/microduck_rl-develop/tests/test_velstand_cfg.py`（CPU，build cfg + compile spec，锁 servo geom / joint 名 / 奖励符号）。
- 本仓库新 tests：`microduck-software/tests/test_hd1910_configs.py`（9 passed @ live hd1910_kp8）。
- 关节映射规范（14 驱动关节，free joint 除外）：live kp8 模型实测顺序已硬编码进测试。
- HD-1910 真实 bus ID 来源：`.upstream/hd1910m/radxa/installation.json`（`mapping_confirmed=true`，15 关节 ID 与方向）；JOINT_NAMES 顺序见 `duck-ipc-proto/src/lib.rs:368`；XL330 参考 map 见 `duck-control/src/model.rs:15`（仅参考，不适用于本机体）；`bus.joint_ids` 必填/拒绝开总线见 `robotd/src/main.rs:5495` + `audit_robotd_toml.py`。
