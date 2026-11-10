# Vottivott/microduck-playground 仓库研究

_2026-11-09。核对对象：`main@052a2494`（2026-11-05 push）；数据全部来自 GitHub 官方 API + `raw.githubusercontent.com` 按 sha 取文件，未走搜索引擎、未信镜像站。_

## 0. 结论先行

**它是什么**：`pollen-robotics/microduck_rl` 的**独立实验延续分支**（作者自述 "not an official Pollen Robotics release"），把一个 RL 训练场的全部产物——**46 个任务 id、7 组成品实验、5 套 3D 打印硬件**——放进一个可复现仓。软件 Apache-2.0，硬件 CC BY-NC-SA 4.0。131★，2026-09-02 建仓，最后 push 2026-11-05。全仓 1120 个文件 / 约 409 MB（大头是 `experiments/desk-climb/recording/*.npz` 86 MB、预览视频与 STL）。

**对我们的判断**：**不作训练底座，作方法论与部署契约的一手参考**。三条真正值钱的东西：

1. `AGENTS.md`（15.8 KB）——**一份"每条都写着'是这么踩出来的'"的规则清单**，比 README 有用得多，其中 60% 与我们在 flat-walk 上踩的坑同型或互补。
2. `Mjlab-Running-Flat-MicroDuck` 的**速度课程 + 三段 robustification**——直接对着我们「vx 只到指令一半」的痛点。
3. **部署图烘焙三件套**（normalizer / `action_clip` / `action_bounds`）+ 71 KB 的多策略热切换彩排台——比我们现在的彩排工具完整一个量级。

**同步状态（硬核对）**：我们 fork 在 `f010ef1`（2026-09-29），上游 `main` = `052a2494`。`compare` 结果：**ahead_by 20 / behind_by 0 / 77 文件变更**，目录分布 `hardware: 72, README: 1, tests: 2, .github: 1, NOTICE: 1`，**`src/` 一个文件都没动**。即上游这两个月新增的全是 MicroDock / MicroDock v2 打印硬件与其对接仿真，**RL 侧我们没有落后任何东西**。

**必须先确认的一件事（事实，不是猜测）**：`third_party/microduck-playground` 在本机是**空目录**（submodule 未初始化，`.git/modules/` 无对应数据）；`tug-of-war` 分支本机不存在；`chenshiyilisha/microduck-playground` 远端 **404**（该 fork 不存在）；`chenshiyilisha/microduck-flat-walk` 远端只有 `main` 和 `hd1910`。而 `AGENTS.md` 写着「我们的工作分支是 `tug-of-war`（本地、未推送）」。→ **这个分支在本机与已知远端都找不到**，可能在另一台机器（4070Ti 环境包）上，也可能已丢失。动任何 submodule 操作之前先确认这件事。

---

## 1. 仓库结构

```
src/mjlab_microduck/        任务、机器人模型、执行器、奖励（29 个 task cfg + 17 个 Backlash 变体）
  tasks/mdp.py              343 KB —— 所有自定义 MDP 函数（奖励/事件/观测/课程）
  tasks/microduck_velocity_env_cfg.py  44 KB —— 行走配方 = 全家族共享基座
  actuator/friction_dr_bam.py  BAM + 逐 env 摩擦 DR
scripts/                    导出/彩排/评估/选点/渲染（43 个）
experiments/                swing, running, stilts, desk-climb, chimney-climb, parkour, basketball
hardware/                   ladder, stilts, swing-seat, microdock, microdock-v2（含生成器 + STL + 打印盘）
tests/                      39 个 CPU 契约测试（cfg 不变量、ONNX 契约、NaN 防护、aarch64 torch 路由）
docs/                       running/stilt/roller-standup 策略总结 + superpowers/{plans,specs}
```

任务注册表（`tasks/__init__.py`）共 **29 个基础 id**，另有 `_BACKLASH_TASKS` 表把其中 17 个自动包成 `-Backlash-` 变体：

| 家族 | task id（节选） | 备注 |
|---|---|---|
| 行走 | `Velocity-Flat/Rough`、`Running-Flat`、`RunningFlight-Flat` | Running 从 Velocity **派生**，契约完全相同 |
| 站立/起身 | `VelStand-Flat/Rough`、`StandUp-Flat/Rough`、`SitStand-Flat/Rough` | SitStand = 一个策略双向，可运行时热切换 |
| 技巧 | `GroundPick`、`BallKick`、`Roulade`、`Spin`、`SwingPump` | Spin 复用 ground-pick 的 command 槽 |
| 轮滑 | `Velocity-Rollers`、`Velocity-Swizzle`、`RollerCrouch`、`RollerSlope`、`RollerStandUp` | 被动轮 `passive_*` 关节，与舵机关节交错 |
| 地形/跳跃 | `Stilt`、`LongJump`、`PlatformJump`、`Flip`、`Chimney`、`Approach`、`Exit` | 高跷形态靠编译期环境变量 `MICRODUCK_STILT_HEIGHT_CM` |

设计上值得抄的一点：**Backlash 不是一个单独任务，而是"把任意 cfg 包一层"**（`tasks/backlash.py`）。它在每个舵机后串联一个 `passive_<joint>_backlash` 铰链（±1° 游隙），编码器**穿过**游隙读数——因为真舵机的编码器就在齿轮游隙的输出侧。观测/动作维度不变，所以导出与运行时零改动。

---

## 2. 可以立刻搬的规则（`AGENTS.md`，逐条标出处）

这些不是常识，是作者写在文件里的失败记录。按我们 flat-walk 的相关性排序：

**奖励符号（`AGENTS.md:115-121`）**：mdp 里有两种罚项风格——mjlab 自带代价函数返回 ≥0，配**负权重**；自取负的函数（`*_penalty`、`*_l1` 返回 ≤0）配**正权重**。给自取负的项再配负权重 = 双重取负 = 奖励违规行为，策略会去"刷"它（作者原话：butt-hopping、crash-sits）。**唯一可靠的检查：每次训练，wandb 里每个 `Episode_Reward/<penalty>` 都必须 ≤ 0。**

**"RL 优化的是奖励的字面意思"（`:122-125`）**：每个欠约束的自由度都会被利用（弹道甩动代替滚动、肩滚代替矢状翻滚、头三点支撑代替站立）。**把"什么算这个动作"写成基于状态的硬门（支撑接触、朝向轴检查、latch），不要写成小罚项。** —— 我们低速死区那条（`air_time` 阶跃窗口是唯一正激励）正是同一条规律的另一面。

**不许有 jackpot（`:126-130`）**：「到达 X」类奖励必须限速或斜坡化；提前到达后按步计费的目标态 = 用任意暴力换钱的 jackpot。命令式过渡要跟一个**斜坡内部目标**，超前不给钱，于是"慢"才是 argmax。

**不要把正奖励门控在坏状态上（`:131-136`）**：跌倒了/变矮了才给的奖励，策略会停在最便宜的那个姿势里刷。改用**势函数塑形**（付 Δprogress，例如 Δcos(tilt)：上升付钱、保持给零、无法刷）。rest 类任务要把每个正项对所有稳定倒伏姿态（仰/俯/侧）做审计。

**两类正则化器（`:141-147`）**：`body_ang_vel`/`angular_momentum`/`pose_std` 是**动作阻断器**（动态动作本来就需要的量），动态任务里给低；`action_rate`/`joint_torque_rate` 是**平滑器**，安全，但必须在**技能被探索出来之后**再引入（从 0 起 curriculum）——探索期任何"尝试税"都会让"什么都不做"赢。

**比权重更该比的是奖励质量（`:148-150`）**：PPO 看的是相对优势，同一个 `action_rate` 权重在 4 倍大的正奖励栈下弱 4 倍。

**跟踪高斯 std ≈ 你还在意的误差，不是最大误差（`:151-157`）**：「占体重 38% 的头走路时必然摆动；一个收紧的瞬时头部跟踪 std 把走路税到策略直接站住不动」（= 我们核宽那条 `tight std taxed walking so hard the policy stood still` 的原文出处）。**只给"策略能消除的那部分"定价**——例如对 1 s EMA 收 L1，只罚 DC 偏置，允许振荡抵消。

**命令槽不能是死的（`:170-178`）**：一个永远不为非零的命令输入 = 永久死权重。每个槽从第 0 步起就给极小的非零采样范围（即使权重为 0）。**零命令行为必须显式训练**（`zero_command_prob` 精确采零，因为均匀采样几乎永不产生全零）——而全零正是部署时的 idle 态。

**课程（`:182-197`）**：步数 = `iteration × 24`（`NUM_STEPS_PER_ENV = 24`）；用 `microduck_mdp.reward_weight` 做权重阶梯 + 专用 params-curriculum 做命令范围；**`mdp.reward_weight` 是阶跃不是插值**。🔴 **改 term 必须走 manager**：`env.event_manager.get_term_cfg(...)`，**直接写 `env.cfg.events[...]` 是静默 no-op**（manager 在 init 时 deepcopy 了 cfg）——这条正好打在我们「评估脚本强制 spawn 状态」的用法上。另外：**当 wandb 指标恰好在课程阶段边界向下跳一格，是节奏错了**，要拉长阶段或推后引入，绝不提前。

**物理假设先验证再训练（`:91-98`）**：目标/静止姿势必须是稳定平衡——从带噪初值保持 3 s 看 **TILT 不只 height**（只记 z 的 settle 测试会把摔倒报成"稳"）；目标高度必须在**当前模型的仿真里量**，不能跨模型版本搬（一个差 5 mm 的 `STAND_Z` 把目标变成不可能任务，耗了几天）。

**环境/供应链（`:221-234`）**：`uv sync` 全新建出来的环境才是真相（HF Jobs 就是那样的）；**wheel 是按架构分的**——linux-aarch64 上 PyPI 的 torch 是 `2.9.1+cpu`，`torch.cuda.device_count()==0` → mjlab `select_gpus()` 索引空列表 → 第 0 轮之前就 `IndexError`；`[tool.uv.sources]` 只对**直接依赖**生效（删掉那行看起来冗余的 `torch==` pin 会让路由静默失效），且 pin 必须是 `==`（`>=` 会把 2.9.1 拖到 2.13.0）。

**部署（`:235-245`）**：25 cm 的机器自然会以 3.5–5.5 rad/s 翻滚，别拿人类尺度的转速上限去管；反暴力压力应放在**冲击与抖动**（`|a_z|`、`action_rate`、支撑门），不是转速度。IMU 的 DR 是零中心，只能训练"对失配幅度的容忍"，**补不了系统性安装偏置**（那是运行时标定）。**姿态 flag 藏在 twist 的 vx 槽里——全零喂进去等于"站"，看起来像"策略不理按钮"**。

---

## 3. 部署契约：三个烘焙 + 一个适配器

这是全仓最"可验证"的部分，也最贴我们 `deploy61` 事故（归一化分母错 1157 倍）的教训。

**① normalizer 必须烤进图**：`export.py:440-447` 明确——mjlab 1.3.0 里 `EmpiricalNormalization` 是 `MLPModel` 的子模块（`obs_normalization=True`），所以 `export_policy_to_onnx` 天然输出 `actor(normalizer(obs))`。**但**：sim 内 play 会自己再套一遍 normalizer，所以 sim 里看不出漏烤；**永远不要手工转 checkpoint**。

**② `action_clip` 必须烤进图**（`onnx_policy_contract.py:13-86`，`export.py:454-457`）：训练走 `RslRlVecEnvWrapper`，它会在写动作前 clip actor 输出；部署运行时直接吃 ONNX 输出，所以这个 clip 必须在图里。实现是把产出节点改名，尾部追加一个 `Clip` 节点，并在 metadata 打 `action_clip_baked_into_onnx=true`。

**③ `action_bounds`**（`:88-139`）：给 `BoundedJointPositionAction` 用的逐关节 clamp——训练时是"命令被夹到行程内，且**夹后的值回填进动作历史**"，所以部署图必须做同样的 clamp（在策略输出单位里），否则运行时的 action history 与训练不一致。

**④ swing 的运行时适配器**（`integrations/pollen-microduck/README.md` + `swing_plane_cue.rs`，4825 B，`rustc --test` 可独立跑）：swing 策略**沿用 61D 形状但把 48..51 槽改成了 swing 平面提示**（写 `[0, body_y.x, body_y.z]`，其余 10 个命令槽置零）。官方运行时不会构造这个提示，所以**只加载 ONNX 不够**。适配器钉死在 `pollen-robotics/microduck@2c61dcc` 的四元数约定（scalar-first `[w,x,y,z]`），要求：`SflpDecoder::ready()` 为真 **且** 秋千静止在最低点时才 `capture` 一次，捕不到就拒绝 arm；50 Hz 每拍从 `Command::default()` 起写；`HOME + 0.7 * action`；**关掉官方控制器的头/腿低通**（训练无后置滤波）；disarm 时清掉锚点/上一动作/上一目标。

> **这条对我们直接有用**：它把「obs 形状不变 ≠ 语义不变」写成了工程契约。我们的 `deploy61` 事故就是把 61D 的某一段当成了别的语义。任何"复用槽位"的策略都必须配一份这样的书面契约 + 一个可独立编译测试的适配器。

**⑤ 彩排台 `scripts/infer_policy.py`（71 KB）**：比我们现用的多策略热切换彩排，键盘触发 `--walking / --standing / --sitstand / --ground-pick / --slope / --kick-left|right / --roulade`，自动 `--switch-threshold 0.05` 做 **walk↔stand 切换**（正是我们低速死区在真机上唯一的过渡手段，缺的就是 stand 策略），另有 `--delay MIN MAX`（执行器延迟）、`--save-csv`、`--record`（录观测做回放）、`--current-limit`、`--foot-friction/--foot-solref`。

---

## 4. 实证数字（都是仿真；来源见括号）

| 实验 | 结果 | 口径 |
|---|---|---|
| Running | **1.651 m/s**，99.22% 存活（512 env，nominal）；齿隙+扰动压力下 **1.612 m/s**，98.44%（256 env） | 命令 2.20 m/s，1 s 预热后跑 10 s（`experiments/running/README.md`） |
| Running 强化 | 从 iter 11,748 续训三段：±0.03→±0.06→±0.10 m/s 推、CoM 3→8 mm、初倾 1→2°，4096 env、seed 42 | 最终 iter 12,195 |
| Basketball | LSTM、**不看球状态**：60 s 内 3072 次试验存活 97.01% | 硬件未验证 |
| Swing | 100 seeds × 36 s：严格全程通过 71/100，中位峰峰 163.03°，最好 seed27 = 173.20° | 无相位钟、无脚本冲量、无特权摆角 |
| Stilts | 10/15/20/25/50 cm + 1.0/1.4/2.0 m 仿真高跷 | blend-0.50 |
| MicroDock / v2 | 30/30 对接（v1，用官方行走策略）、30/30 对接+退出（v2，专用 scoot 策略） | 硬件已打印，未上机 |

**评估方法论**（比数字更值得抄）：①每个实验旁都放**机器可读**的 `eval/*.json`，视频旁边放原始记录；②**交叉评估**——用普通执行器模型训练，再在 backlash 模型上测（1.636 m/s），而"单独用 backlash 续训"的版本**更差、未被选**；③同一条 rollout 同时跑 `verify_*_onnx_parity.py`，checkpoint↔ONNX 最大动作差 **7.63e-6**；④**拒绝不可信的更好数字**——60 s 版本达到 180.20°，但因为跑出了几何包络，**主动作废**。

---

## 5. 与我们项目的差异点（别直接照搬的地方）

1. **执行器模型不是一回事**：上游全程 **XL330 + BAM**（`microduck_constants.py:286-300`，`kp_fw=200.0`，注释写"microduck's preserved firmware stiffness，microban 用 125"）。我们是 **HD-1910 飞特 + `hd1910_kp8`**。`kp_fw` 在两套舵机上不是同一量纲，**不能直接对照 200 vs 8**；但"用 BAM 电压控制 + 负载相关摩擦"这套建模思路可以直接照抄。
2. **`dof_frictionloss` 在 BAM 下被清零**（`friction_dr_bam.py:1-15`）→ 标准 `dr.dof_frictionloss` 是**静默 no-op**。要随机化关节摩擦必须改执行器的 `friction_scale`。同型于我们「第二个写者是 robotd」那条：**改一个量之前先问还有谁在写它**。
3. **BAM 来自未合并分支**：`pyproject.toml:84` 用 `Rhoban/bam@mjlab_frictionloss`（git 分支，不是 tag 不是 release）。供应链上是个活口子——上游一改分支，`uv sync` 结果就变。我们环境若要用，应锁定 commit sha。
4. **运行时契约钉在官方 C 端**：`integrations/pollen-microduck` 明确写"未合并进 Pollen 运行时、未上机验证"，且 `Net::Swing` 是示意。它是**参考适配器**，不是可用组件。
5. **协作面极小**：全仓只有 1 个 issue（"how to make mp4"）+ 4 个自合并 PR，作者单人节奏。**不要期待它响应 issue 或维护兼容性**。

---

## 6. 建议动作（按性价比排序）

1. **先确认 `tug-of-war` 分支的生死**（0 成本，但涉及数据可能已丢）。本机与已知远端都没有，先问是不是在另一台机器上；没有的话要决定是重建还是放弃。
2. **同步 submodule 到 `052a2494`**：由于 `src/` 零变更，冲突面为零，只是把 `hardware/microdock*` 拉下来。顺手把 `AGENTS.md` 与我们 `docs/active/` 的规则做一次交叉引用（哪些我们已经踩过、哪些是新坑）。**这一步会改仓库状态，需你点头再动。**
3. **把三件套搬进我们的导出链**：`bake_action_clip` + `bake_action_bounds` 是纯函数、不依赖 microduck 任何东西，可以直接复制进我们的 `export.py` 之后跑一次；配我们现在已有的 parity 闸门（`check_onnx_parity.py`，max|Δ|=2.65e-06）做负对照。
4. **重训速度，不重训配方**：running 的办法是"从 velocity 派生 + 速度课程阶梯 + 三段 robustification"，不改观测/动作/DR。我们对 7999 的处置可以照搬：**用普通执行器训出的模型去 backlash/换档模型上交叉评估**，而不是换档再训一遍（上游实测换档续训更差）。
5. **低速死区的正解在运行时**：我们缺的是 stand/sitstand 的**权重**（配方代码本地 LIVE 包里已有 `Mjlab-StandUp-*`/`SitStand-*`，见 2026-11-09 Pass60），配 `--switch-threshold` 式热切换。playground 的 `SitStand`（一个策略双向）是可直接照抄的配方形状；但**必须在我们自己的 plant 上重训**，HF 上的 ONNX 是 XL330 线的。
6. **暂不碰**：stilts / swing / basketball / chimney / microdock——这些依赖我们没有的硬件（高跷、秋千架、球、12.5 cm 竖井、充电坞），只有方法价值，没有工程价值。

---

## 附：核对用的原始命令

```bash
curl -s "https://api.github.com/repos/Vottivott/microduck-playground"                     # 131★ / Apache-2.0 / 2026-11-05
curl -s "https://api.github.com/repos/Vottivott/microduck-playground/git/trees/052a2494dd?recursive=1"
curl -s "https://api.github.com/repos/Vottivott/microduck-playground/compare/f010ef1...052a2494"   # 20 commits / 77 files / src 零变更
curl -s "https://api.github.com/repos/chenshiyilisha/microduck-playground"                 # 404：该 fork 不存在
curl -s "https://api.github.com/repos/chenshiyilisha/microduck-flat-walk/branches"         # 只有 main, hd1910
```

本地取下的文本副本（临时，已 gitignore）：`_stage/duckpg/files/`。
