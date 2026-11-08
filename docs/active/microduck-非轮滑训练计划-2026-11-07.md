# MicroDuck HD-1910 非轮滑动作训练计划（2026-11-07）

> 范围：**轮滑（Roller）延后**，本计划覆盖其余动作。目标：在**部署 plant（kp8 / kp_fw=8）**上把每个动作训到收敛，并用**同 plant 评测**判定，不靠单次最高迭代、不跨 plant 比较。
>
> 依据：已实读 `train_velocity.sh`、`resume_train.sh`、`resume_standup.sh`、`explore_heading.sh`、`explore_ground_pick.sh`、`explore_standup.sh`、`resume_heading_run.py`、`apply_to_live.py`、各 `env.yaml` 与 `params`。所有命令与 plant 名均来自真实脚本，非记忆推断。

---

## 0. 部署铁律（任何动作训练前必读）

1. **plant 是一等坐标，换 plant = 换任务。**
   - 部署目标 = **`hd1910_kp8`（kp_fw=8，`official_m6_stslaw.json`）**。当前 live 已是 `hd1910_kp8 / kp_fw=8.0`（已实测）。
   - `m5`（kp32）、`kp5`（kp_fw=5）只是 sim/对照基线，**不能直接上机器人**。任一动作若只在 m5/kp5 训过，上了 kp8 机器人就是跨 plant，结论无效。
   - 每次开训前显式 `apply_to_live.py --plant hd1910_kp8` 并 `--check` 断言 `detected=hd1910_kp8, kp_fw=8.0`。脚本里已有该断言（如 `explore_heading.sh` 的 `DET_EXPECT=hd1910_kp8 / KP_EXPECT=8.0`），缺失的脚本要补。
2. **评测必须同 plant。** 用已有 `--plant` 开关：行走 `eval_velocity_in_sim.py --plant hd1910_kp8`；地面拾取 `eval_ground_pick.py`（kp8 原生）；轮滑 `eval_roller_onnx.py`（延后）。**绝不**把 m5 训的策略拿去 kp8 测、或反之（此前已踩过此坑，86%/82% 摔的"黑箱"是跨 plant 误测，非策略坏）。
3. **checkpoint 抖动是常态 → 外层 sweep。** 上游同 seed 不保证轨迹一致；选点必须 ≥3 seed 复训 + 取中位数/sem，不能迷信"迭代数最高的那个"。每个动作最终选点前做 sweep。
4. **评测要带负对照 + 分布检查。** 门禁阈值不能取自被测策略本身；每个物理量先单独看 min/p50/max，确认随状态变化、量级合理，再判定"达标"。
5. **IMU 延迟带必须记录。** 真实舵机比 BAM 多 ~26–45 ms 延迟；`runmeta` 里 `delay_min/max_lag` 是台架复现与训练对不上的第一怀疑点，每次开训写入。
6. **TDR 风险。** `mujoco iterations=100 / ls=50` 在 Windows WDDM 下曾触发显卡超时重置（roller 那次崩成僵尸）。velocity/groundpick/standup 脚本目前都用 100/50，**开训要盯 log**，若出现 `CUDA error: unknown`/僵尸，降到 `MUJOCO_ITERS=10 MUJOCO_LS_ITERS=10`（roller 已验证安全）重跑。
7. **训练前先 `--check-only` / dry-run。** velocity 有 `check_velocity_ready.py`；heading resume 有 `--launch` 前的 dry-run；其余先小迭代 smoke 验证曲线再 formal。

---

## 1. 动作现状速查（已实测确认）

| 动作 | 任务 id | 现有最佳 ckpt | plant | 同 plant 评测结论 | 缺口 |
|---|---|---|---|---|---|
| 行走/速度 | `Mjlab-Velocity-Flat-MicroDuck` | m5 线 `model_5999`（5999 步） | **m5/kp32** | 0% 摔、vx 0.32 ✅（但非部署 plant） | 部署 kp8 线欠训 |
| 行走/速度（部署） | 同上 | **kp8 线 `p8head/model_2999`（2999 步）** | **kp8/kp8** | 0% 摔但慢（vx 0.167）⚠️ | **需加迭代** |
| 地面拾取 | `Mjlab-GroundPick-Flat-MicroDuck` | `model_3999`（4096×4000） | kp8/kp8 | **未做同 plant 评测** | 需评测；若欠训则续训 |
| 站起 | `Mjlab-StandUp-Flat-MicroDuck` | 仅 smoke `model_4` | **m5/kp32** | 无 | **需从零训 kp8** |
| VelStand（走+站合一） | `Mjlab-VelStand-Flat-MicroDuck` | 无（官方有 `velstand` ONNX） | — | — | 未训，可选 |
| 手柄遥操作 | `Mjlab-JoySmoothPD-Flat-MicroDuck` | `model_599`（XL330 线） | xl330/kp200 | 不适用 | HD1910 遥操作未做，低优先 |

---

## 2. 行走 kp8（**最高优先级**）

**为什么最优先**：部署 plant 上唯一会走的策略只有 kp8 线，且只训到 2999 步（≈12M env-steps），而可走基准（m5 线、XL330 同行）需要 393–590M env-steps（`train_velocity.sh` 注释）。kp8 现在能走但偏慢，是"欠训"不是"配方坏"——补迭代即可。

**启动方式**：
- kp8 行走当初由 `explore_heading.sh PLANT=p8`（= `train_heading_variant.py` + heading 奖励配方）从零启的，分 `p8head`（heading reward 变体）与 `p8ctl`（控制变体）。
- **续训入口已补齐（2026-11-07）**：`resume_heading_run.py` 已加 `--plant p8`（默认仍 `p3`，向后兼容），干跑已验证能锁定 `p8head` 线、算出续 5001 步、`train_heading_variant.py --dry-run` 通过。

**续训命令（推荐用脚本）**：
```bash
# 先确保 live 是 kp8（脚本内 plant_check 会断言；也可 --skip-plant-check 仅验算术）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant hd1910_kp8
# 干跑（不烧 GPU，验证命令与计数）：
.venv-mjlab/Scripts/python.exe tools/hd1910/resume_heading_run.py --plant p8 --target 8000
# 真跑（续到 8000，从 2999 起 +5001）：
.venv-mjlab/Scripts/python.exe tools/hd1910/resume_heading_run.py --plant p8 --target 8000 --launch
```
> 脚本已内置 rsl_rl 的"增量 max-iters"减法（从 checkpoint 读 `iter`，自动算剩余），并保留 counter 漂移闸门、heading 奖励闸门、plant 断言——优先用它而非手传。

**收敛判据（同 plant 评测）**：`eval_velocity_in_sim.py --task Mjlab-Velocity-Flat-MicroDuck --checkpoint <kp8 ckpt> --plant hd1910_kp8 --num-envs 64 --seconds 8.0 --device cuda:0`
- 放行：`terminated ≈ 0%`、`vx_mean ≥ 0.30`（追平 m5 线）、`upright > 0.99`、`translates_forward`/`no_fall`/`stays_upright` 全 PASS。
- 未达则继续加迭代，不要换配方。

**完美化（sweep）**：最终选点前，对 kp8 线跑 **≥3 个 seed**（p8head/p8ctl 已是两种配方起点，可再加 1–2 seed），各自训到 ~8000，评测取中位数 + sem；选 `vx` 高且 `terminated` 低者。

---

## 3. 地面拾取 kp8

**现状**：formal 已是 `4096×4000 → model_3999`，plant 正确（kp8），`eval_ground_pick.py` 已就绪（kp8 原生，支持 `--seeds` 出 iqr）。**最大缺口是"还没评测"**。

**第一步——同 plant 评测（先别急着续训）**：
```bash
.venv-mjlab/Scripts/python.exe tools/hd1910/eval_ground_pick.py \
  --checkpoint logs/rsl_rl/microduck_groundpick_hd1910/2026-11-06_22-17-10_hd1910_groundpick_4096x4000_1106_2216/model_3999.pt \
  --envs 64 --seeds 3 --device cuda:0 --json out/eval_gp_kp8_model3999.json
```
- 若成功率/到位率达标 → **动作完成**，进入 sweep 选点（≥3 seed 复训 4096×4000 取中位）。
- 若欠训（成功率低、曲线仍在爬）→ 续训（见下）。

**续训入口缺口**：地面拾取**没有 resume 脚本**。formal 是用 `explore_ground_pick.sh ENVS=4096 ITERS=4000` 从零启的。加迭代需手传 resume：
```bash
.venv-mjlab/Scripts/python.exe .venv-mjlab/Scripts/train.exe Mjlab-GroundPick-Flat-MicroDuck \
  --agent.resume True \
  --agent.load-run 2026-11-06_22-17-10_hd1910_groundpick_4096x4000_1106_2216 \
  --agent.load-checkpoint model_3999.pt \
  --env.scene.num-envs 4096 --agent.max-iterations <增量> \
  --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50 \
  --agent.save-interval 250 --gpu-ids '[0]' --agent.logger tensorboard \
  --agent.experiment-name microduck_groundpick_hd1910 --agent.run-name hd1910_groundpick_resume
```
> 建议补一个 `resume_groundpick.sh`（仿 `resume_standup.sh` 结构，但 plant 改 kp8）以固化入口，避免每次手传出错。

---

## 4. 站起 kp8（**部署一致性关键缺口**）

**现状**：站起**只有 m5（kp32）的 smoke**（`microduck_standup_hd1910` 唯一 run 是 `model_4`）。`explore_standup.sh` / `resume_standup.sh` **都硬编码 m5（kp32）**，断言 `kp_fw==32`。若照此训，站起会是 m5 策略，与 kp8 行走同机运行即跨 plant。

**决策**：部署要的是 kp8 站起。两条路：
- **A（推荐，plant 一致）**：在 kp8 从零训站起。`explore_standup.sh` / `resume_standup.sh` 已加 `PLANT=p8` 变体（默认仍 m5，向后兼容；`PLANT=p8` 时 `apply_to_live --plant p8` + 断言 kp_fw=8.0 + `official_m6_stslaw.json`）。走 "explore 1024×1000 → 看曲线 → formal 4096×4000" 流程。
- **B（快速兜底）**：直接用官方 `alpha_stand.onnx`（官方 plant ≈ kp8，部署一致）。先验证它在本机 kp8 上 get-up 成功率，达标就省掉自训。

**A 路线命令（脚本已就绪）**：
```bash
# explore（1024×1000，曲线检查）
PLANT=p8 ENVS=1024 ITERS=1000 bash tools/hd1910/explore_standup.sh
# 看曲线（reward、get-up 成功率）后，formal：
PLANT=p8 ENVS=4096 ITERS=4000 bash tools/hd1910/explore_standup.sh
# 续训（如需加迭代）：
PLANT=p8 LOAD_RUN=<run> LOAD_CKPT=model_*.pt ENVS=4096 MAX_ITERS=4000 \
  bash tools/hd1910/resume_standup.sh
```

**站起评测已就绪（2026-11-07）**：新建 `tools/hd1910/eval_standup.py`（照 `eval_ground_pick.py` 的物理闸门结构，带 plant 指纹防跨 plant）。闸门：没摔 + 躯干 z-up 峰值 >0.90（起身）+ 末态 z-up >0.85（站定），输出成功率/中位/iqr。用法：
```bash
.venv-mjlab/Scripts/python.exe tools/hd1910/eval_standup.py \
  --checkpoint logs/rsl_rl/microduck_standup_hd1910/<run>/model_XXXX.pt \
  --envs 64 --seeds 3 --json out/eval_standup_kp8.json
```
或先用官方 `alpha_stand.onnx` 在 `Mjlab-StandUp-Flat-MicroDuck` 上手工验证成功率（B 路线）。**在缺评测前，站起动作不算完成。**

---

## 5. VelStand（走+站合一，可选）

- 任务 `Mjlab-VelStand-Flat-MicroDuck` 已注册，但**无任何训练脚本**（仅在 `audit_robotd_toml.py` 的检查清单里出现）。
- 价值：一个策略同时处理"站起→行走→站定"，部署更简洁；官方已有 `velstand` ONNX 可对标。
- 优先级低：等 ② 行走 kp8、③ 地面拾取、④ 站起 kp8 都就绪后再考虑。若做，仿 `explore_heading.sh` 起 kp8 变体，formal 前先探索奖励权重。

---

## 6. 手柄遥操作 HD1910（低优先）

- 现有 `train_joy.sh` 训的是 **XL330 线**（`joy_pd_spec`，motor=xl330/kp200），`model_599`。非 HD1910 实体。
- HD1910 遥操作若要，需用 `apply_to_live --plant hd1910_kp8` + 对应 joy 任务（`Mjlab-JoySmoothPD-Flat-MicroDuck` 在 kp8 上重训）。属"开发期调试便利"，不是自主能力，排到最后。

---

## 7. 工具链补齐状态（2026-11-07 准备阶段已收口）

| 缺口 | 影响动作 | 状态 | 做法 |
|---|---|---|---|
| `resume_heading_run.py` 只支持 p3(kp5) | 行走 kp8 续训 | ✅ **已补** | 加 `--plant p8`（默认 p3 向后兼容），干跑验证锁定 `p8head`、续 5001 步、`--dry-run` 通过 |
| 站起脚本只有 m5 | 站起 kp8 | ✅ **已补** | `explore_standup.sh` / `resume_standup.sh` 加 `PLANT=p8`（默认 m5），`--plant p8` 时断言 kp_fw=8.0 + `official_m6_stslaw.json` |
| 站起无评测脚本 | 站起 | ✅ **已建** | 新建 `eval_standup.py`（没摔+峰值直立+末态站定，带 plant 指纹），编译+任务注册校验通过 |
| 地面拾取无 resume 脚本 | 地面拾取续训 | ⬜ 仍待补（可选） | 若 `model_3999` 评测欠训需加迭代，再补 `resume_groundpick.sh`（仿 `resume_standup.sh`，plant=kp8）；当前 `model_3999` 已训满，大概率只需评测 |

---

## 8. 执行顺序与里程碑

1. **P0 行走 kp8 续训**：补 resume 入口 → 从 `p8head/model_2999` 续到 ~8000 → 同 plant 评测达标（vx≥0.30, terminated≈0）。
2. **P1 地面拾取评测**：先评 `model_3999`（kp8）；达标即完成，欠训则续训 + sweep。
3. **P2 站起 kp8**：补 kp8 站起脚本 + 站起评测 → explore → formal → 同 plant 成功率评测（或官方 `alpha_stand.onnx` 兜底）。
4. **P3 sweep 选点**：行走/拾取/站起各 ≥3 seed，评测取中位数 + sem，定最终部署候选。
5. **P4（可选）VelStand / 手柄遥操作 HD1910**。

> 每个动作"完成"的硬标准：**同 plant（kp8）评测 + 负对照 + ≥3 seed sweep 选点**，缺一不可。

---

## 9. 风险与回退

- **TDR 崩溃**（100/50 求解器）：log 出现 `CUDA error: unknown`/僵尸 → 降 `MUJOCO_ITERS=10 MUJOCO_LS_ITERS=10` 重跑（roller 已验证安全）。
- **cross-plant 误判**：任何"摔得多/走不动"的结论，**先确认评测 plant == 训练 plant** 再下判断（此前 86%/82% 摔就是跨 plant 误测）。
- **plant 漂移**：每次开训前 `apply_to_live --check` 断言；机器人侧用 `robotd_hd1910_mode0.toml`（已固化 `cells=[2]`+`max_volts=8.4`，非 `[2,3]` 雷）。
- **checkpoint 抖动**：不要只信最高迭代；sweep 后才定候选。
- **站起跨 plant**：若站起只在 m5 训，上 kp8 机器人无效——坚持 A 路线或官方 kp8 ONNX。
