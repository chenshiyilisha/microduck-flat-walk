# 走起来的配方：DuckEMW / Hannes running 逐项对照

> 2026-10-23 晚。起因：用户贴 `https://github.com/emwstudio/DuckEMW`，问有没有可参考的。
> 结论：**这是目前唯一一个有公开数据证明「从零训出会走的 microduck 策略」的仓库**，
> 而且它踩过的坑和我们 15:00 之后塌的每一个坑逐条对应。本文只留能直接落地的部分。
>
> 一手来源（全部用 GitHub API 取，未走搜索引擎）：
> - `emwstudio/DuckEMW` @ main（137★，2026-08-30 建，2026-09-29 最后 push，无 fork）
> - 其 submodule 上游 `Vottivott/microduck-playground`（Hannes von Essen）
> - 本地缓存：`.upstream/duckemw/DuckEMW-main/`、`.upstream/duckemw/pg_*.py`

---

## 1. 这个仓库做了什么

五个任务全在 4096 envs + mjlab + PPO(rsl_rl) 上从零训：

| 任务 | 关键数字 | 训练量 |
|---|---|---|
| 平地极速冲刺 | 0.4 → **1.659 m/s 均值 / 2.196 峰值**（直立门控） | 13,500 iter 从零 |
| 跟音乐跳 DJ | 踩点中位偏差 26 ms，91% 在 100 ms 内 | 1000 iter |
| 踩篮球平衡 | 60 s 存活 98.34%（3021/3072） | 续训 Hannes b11 |
| 踩高跷 10 cm→2 m | 8 个里程碑门禁全过 | 37 级课程，¥8.5 |
| 360° 刚性杆秋千 | 过顶 12/16，连续 7 圈 | 4000 iter |

对我们只有一个任务相关：**极速冲刺**——因为它就是「velocity 任务 + 走起来」。

**它没有实体机器人**（README 明写「纯仿真结果，未上真机」），所以它不是硬件答案，
是**训练配方答案**。

### 它自己的三条铁律（`AGENTS.md` / `README`）

1. **最终档 ≠ 最佳档**：篮球任务 3 个存档点评估后，冠军是中间档 7375，最终档 7498 回退到 95.74%。
2. **评估指标决定你能看见什么**：13250 早就有 2.196 的直立峰值，因为只盯均值/p90，两周后才发现纪录已破。
3. **配方结论一律以部署侧实测为准，不看训练指标**。

---

## 2. 我们自己的探针：站桩到底值多少分

新增 `tools/probe_argmax.py`（做法抄 DuckEMW 的「零成本探针确诊」：`docs/03-training-log.md:254`
「站桩报酬是前进报酬 38 倍（v12 日志 stance 0.87 vs progress 0.023 实锤）」）。

固定命令 `cmd=(0.4, 0, 0)`，512 envs × 100 步（2 s），把 `env.step()` 的每一项 term 记下来，
**在同一批 term 上套两套权重**各算一次总分。原始输出：`out/probe_argmax.txt`。

| 行为 | vx m/s | yaw 漂 | 摔 | **OURS 总分** | **HANNES 总分** |
|---|---:|---:|---:|---:|---:|
| 零动作站桩（ctrl = stand pose） | −0.000 | 1.5° | 0.1% | **7.357** | **3.561** |
| `robust61_u6` | 0.035 | 5.2° | 0.2% | 6.422 | 3.490 |
| `robust61_a` | 0.125 | 18.7° | 8.4% | 4.170 | 2.299 |

**站桩比我们所有 checkpoint 都高。** 这就是 15:00 之后每次训练都塌的答案。

### 7.357 分是怎么来的（OURS 逐项）

| 项 | 权重 | 站桩得分 | 说明 |
|---|---:|---:|---|
| head | 2.0 | **2.000** | 头不动 = 满分，满值 |
| upright | 2.0 | **1.993** | 站着 = 不倾斜 = 满分 |
| turn | 2.0 | **1.969** | 不转 = yaw 误差 0 = 满分 |
| pose | 1.0 | 0.997 | 站在 stand pose = 满分 |
| track | 2.0 | 0.401 | **唯一扣分的项**，但只扣到 0.2（`exp(-0.4²/0.10)`） |
| air_time / clearance / slip / swing / angvel / rate / limits | — | −0.003 | 站着不抬脚，全都不罚 |

**7.36 分里 6.96 分（94.6%）来自四项「不动即满分」。** 前进相关的只有 `track` 一项，
而它对「完全不动、命令 0.4 m/s」只扣 60%，也就是**站着不动能拿 7.36/7.76 = 95% 的分数**。

### 一个必须纠正的说法

我前几轮说「站桩是奖励的 argmax」，**这个说法不准确**。算一下「完美走路」（vx 精确等于命令，
姿态/头全对，步态在 air_time 窗口内）：

| 配方 | 站桩 | 完美走路 | 差 |
|---|---:|---:|---:|
| OURS | 7.36 | ≈12.0（track 2 + air_time 3 + head 2 + turn 2 + pose 1 + upright 2） | **+4.6** |
| HANNES | 3.56 | ≈6.6（forward 1.67 + track 2 + turn 0.5 + heading 1.5 + pose 0.15 + upright 0.75） | **+3.0** |

两套表下完美走路都远高于站桩。所以站桩**不是 argmax，是「零技能可达的局部最优」**：
从零动作出发，去走路的路要先从 7.36 掉到 4–6，再爬回 12。PPO 不会先掉分。
**我们把一半分数白送给了「什么都不做」，于是任何让策略偏离站姿的探索在短期都是亏的。**

这就是为什么：改配方 → 中间过程更差 → 策略退回站桩 → 每次「上游配方微调」都塌。

---

## 3. Hannes running 配方 vs 我们（逐项，带源码行号）

来源：`Vottivott/microduck-playground` @ main
`src/mjlab_microduck/tasks/microduck_running_env_cfg.py:262-305` +
`tasks/mdp.py`。

| 项 | 我们（`--upstream-rewards`） | Hannes running | 差别 |
|---|---:|---:|---|
| **forward_progress** | **无** | **5.0**（`clamp(vx,0,cap)/cap`，cap 2.4） | **决定性** |
| track 高斯 | 2.0 / std² 0.10 | 2.0 / std² **0.15** | 中 |
| turn 高斯 | 2.0 / std² 0.50 | **0.5** / std² 0.50 | 大 |
| **heading_hold** | **无** | **1.5** / std 0.4 | **治走不直** |
| **planar_drift** | **无** | **−0.05**（横向 ×4） | **治走不直** |
| pose | 1.0 | **0.15** | 大 |
| upright | 2.0 / std² 0.05 | **0.75** / std² 0.15 | 大 |
| head | 2.0 | **0.0** | 大 |
| head_bias | 0.0 | 0.0 | — |
| air_time | 3.0 | **0.0**（整项关） | 大 |
| clearance | −2.0（target 0.02） | 同权重，target **0.015** | 小 |
| swing | −0.25 | 同权重，target **0.015** | 小 |
| slip | −0.1 | **−0.05** | 小 |
| angvel | −0.05 | **−0.01** | 中 |
| angular_momentum | 无 | −0.005 | 小 |
| rate | −0.1 | **−0.02** → 课程 −0.10 | 中 |
| **rel_standing_envs** | 0.02 → 课程 **0.25** | **0.03** 固定 | **大** |
| 命令范围 | lin_x ±0.4 / lin_y ±0.3 / yaw ±1（固定） | **课程**：0.20–0.45 起步，每 1000 iter 抬一档 | **决定性** |
| 训练量 | 2000 iter | **12,195 – 13,500 iter** | **决定性** |

### forward_progress 的完整实现（`mdp.py:1279-1304`）

```python
def running_forward_progress_from_velocity(velocity_x, speed_cap=1.2):
    velocity_x = torch.nan_to_num(velocity_x, nan=0.0, posinf=speed_cap, neginf=0.0)
    return torch.clamp(velocity_x, min=0.0, max=speed_cap) / speed_cap
```

三行。要点：
- **vx ≤ 0 → 0 分**（站着、后退、原地抬腿一分不得）
- 线性到 cap，**无高斯天花板** —— 每一步前进都换到分，不会在 vx≈cmd 处饱和
- cap 截断防单个物理异常值变成 jackpot

这是 Hannes 从 0.4 走到 1.66 的骨架。DuckEMW 自己的 sprint v1–v4 全部 plateau ≤1.43，
**换了这个配方才破 1.65**（`docs/03-training-log.md:100-102`）。

### heading_hold（`mdp.py:5009-5041`）

```python
yaw = torch.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))
# 出生后前两步记录 yaw_spawn，之后每步重算
err = torch.atan2(torch.sin(yaw - ref), torch.cos(yaw - ref))   # wrap 到 [-π,π]
return torch.exp(-(err ** 2) / std ** 2)                        # std = 0.4
```

源码注释写得很直白：

> This is the RIGHT way to go straight (vs penalising yaw-RATE, which just tells the policy
> 'never turn' → it can't steer back and drifts open-loop). Here a drift lowers the reward,
> and the policy is free to yaw back to recover it.

**这正好打在我们 `yaw_drift` 的软肋上**：`yaw_drift` 是「一个步幅内 yaw 速率的均值」，
零均值摆动也能拿 1.000（我们自检里有这条断言），而且**没有「往哪边转回来」的信号**。
`heading_hold` 是**绝对角度**锚定，漂了就扣分，转回来就加分 —— 有方向。

但注意 Hannes 自己实测：**mean heading error 名义 31.33°、backlash+stress 43.81°**。
也就是说**他也没解决走不直**，只是把它压到「能走但会偏」。这印证我们之前的结论：
走不直是这类 14 舵机鸭子的共性，不是我们实现错。

### planar_drift（`mdp.py:1346-1356`）

```python
return (wz - cmd_yaw)**2 + 4.0 * (vy - cmd_y)**2   # 横向误差罚 4 倍
```

配套，权重 −0.05。

### 速度课程（`microduck_running_env_cfg.py:85-93`）

```
iter    0 : 0.20 – 0.45
iter 1000 : 0.30 – 0.55
iter 2000 : 0.40 – 0.65
iter 3000 : 0.50 – 0.75
iter 4000 : 0.60 – 0.85
iter 5000 : 0.70 – 0.95
iter 6000 : 0.90 – 1.20      ← 12195/13500 的前置
iter 8750 起：每 750 iter 抬 0.15，到 2.2
```

**下界也一起抬**，源码注释：「zero-command behavior comes from the explicit standing
bucket, rather than consuming most running samples near zero」。

我们从零训时命令固定 ±0.4，**等于一直在跑第一档，却指望它走到 0.4**。

---

## 3.5 kissqy 的排除法：奖励表不是问题，网络和训练量才是

用户随后贴了 `kissqy/Microduck-kissqy`（125★，今天中午还在 push，344 MB）。它和 DuckEMW
是**两个方向完全不同的项目**，放在一起才形成裁决：

| | kissqy | DuckEMW / Hannes |
|---|---|---|
| 定位 | **实机复刻 + 固件 + 系统镜像 + 中控**（Rust，`control.43`） | **训练配方**（纯仿真，无实机） |
| 奖励表 | 16 项，**与我们逐项相同**（见下） | 16 项 + `forward_progress` + `heading_hold` + `planar_drift` |
| 网络 | **512-256-128 ELU**（= 官方默认） | 512-256-128 ELU（= 官方默认） |
| 训练量 | 约 2000 轮（作者自述「2000 轮就达到顶峰」） | 12,195 – 13,500 轮 |
| 走路数据 | **一个数字都没有** | 1.659 m/s 均值 / 2.196 峰值 |
| 有实体机器人 | **有**（实机演示、镜像、中控） | 无 |

### kissqy 的 16 项奖励（`Mjlab-Velocity-Flat-MicroDuck.json`，一手快照）

```
track_linear_velocity 2.0    track_angular_velocity 2.0   upright 2.0
pose 1.0                     body_ang_vel -0.05            angular_momentum -0.02
dof_pos_limits -1.0          action_rate_l2 -0.1           air_time 3.0
foot_clearance -2.0          foot_swing_height -0.25       foot_slip -0.1
self_collisions -1.0         head_pose_tracking 2.0        body_pose_tracking 0.0
head_pose_bias 0.0
```

**这就是官方原表，和我们 `--upstream-rewards` 逐项一致，没有任何前进奖励项。**
kissqy 的 `training_adapter_revision` 是 `R1.5.21-verified-actions-no-ema`，
`source_revision 8d0db749...` —— 它没有改奖励，也没有加项。

### 于是三个变量被拆开了

同一个 16 项官方奖励表：

- **kissqy**：官方表 + 512-256-128 + ~2000 轮 → 有实机、**无量化速度**
- **我们（自写 CPU 植物）**：官方表 + **128-128** + 2000 轮 → 站桩 0.035 m/s
- **官方自己**：官方表 + 512-256-128 + 主训 → 出厂 `alpha_walking.onnx` 实测
  **cmd 0.4 → 0.164 m/s，高命令下 yaw 漂 > 50°**（DuckEMW Phase 0 亲测，`03-training-log.md:86`）

- **Hannes**：官方表 **+ `forward_progress`** + 512-256-128 + **12195 轮** → 1.659 m/s

> ⚠️ 上表的「我们 = 128-128」是**自写 CPU 植物链**。**mjlab GPU 链的 `MicroduckRlCfg`
> 本来就是 `(512, 256, 128)`**（2026-10-24 实测，见下方 P0 更正块），所以
> 「网络容量是差异来源」这一条**对 mjlab 链不成立**——两条链相同宽度，差距只能在训练量。

结论：
1. **奖励表抄错不是原因** —— kissqy 逐项相同，我们逐项相同。
2. **官方那套配方的设计上限就是 0.164 m/s**（cmd 0.4 时），它不是「走起来」，是「挪动」。
   官方自己在注释里承认 standing_envs 课程就是用来「让零命令下站住」的。
3. 我们 **0.035 m/s 低于官方 5 倍**，这一段落差只能由**网络容量**和**训练量**解释：
   - 网络 `128-128` = **26,254** 参数；官方 `512-256-128` = **197,774**，**差 7.53 倍**
   - 官方 `max_iterations` 默认 **50,000**（`microduck_velocity_env_cfg.py:948`），我们 2000
4. 要超过官方 0.164，**必须加 `forward_progress`** —— 这是 Hannes 唯一改掉奖励结构的地方，
   也是它从 0.4 走到 1.659 的唯一杠杆。

**所以 P0 里要加一条：把网络换成 512-256-128 ELU。** 这一条我上一轮排在「次要」，
kissqy 的证据把它提到了 P0 —— 因为它是「官方默认 vs 我们」之间唯一没被排除的差异。

### kissqy 真正值得拿的东西（不是训练）

它的价值在别处，而且对我们的**采购与部署**有直接用处：

- `hardware.json` / `servo_references.json`：HD-1910 的实机参数字典
- `docs/BASELINE.md`：发布版本的**验证范围声明**（哪些验过、哪些没验）
- `microduck-hd1910/docs/design/policy-channel-design.md`（52 KB）：策略通道设计
- 训练中控 R1.5.27：**14 类动作、35 种任务配方**，全是官方 task config 的快照 ——
  可以当作「官方到底有哪些任务、每个任务的 cfg 长什么样」的索引
- 它证明了一件我们不能假设的事：**官方 0.15.1 + HD-1910 在实机上确实能跑起来**
  （不是「走得好」，是「跑得起来」）

---

## 3.6 Duckverse 的 `continuous_joy`：把"站桩"从地形里挖掉，而不是绕着它走

实测与完整数据见 **`microduck-joy策略实测.md`**（含负对照）。这里只留结论和可落地的部分。

**一句话**：那只 794 KB 的 `continuous_joy.onnx` **不是在走，是在原地踏步**
（1.15 Hz、抬脚 15 mm、8 秒净位移 14 mm）—— 它的命令通道是**位置反馈**
`clamp(-2·pos, ±0.15)` 加权重 100 的 `joy_drift`，**设计上就抗拒平移**。
但它给了我们一个比 `forward_progress` 更硬的治站桩手段。

**它的奖励表（`training/continuous_joy.patch`）做了三件事**：

1. **把速度目标和 8 项奖励全删**：`track_linear_velocity` / `track_angular_velocity` /
   `air_time` / `foot_clearance` / `foot_swing_height` / `head_pose_tracking` /
   `head_pose_bias` / `body_pose_tracking`；`pose` 1.0 → **0.15**；twist 指令全清零。
2. **加一个时钟化的抬脚项**（权重 **12**，全场最大）：
   ```python
   target = 0.0005 + 0.024 * relu(±sin(2π·1.15·t))**2       # 24.5 mm，半波整流
   reward = exp(-((height - target)/0.009)**2).prod(-1)      # 两脚相乘，std 仅 9 mm
   ```
   注意 **std 9 mm**（我们 `WIDTH=0.02`）、**两脚相乘**、**相位无条件**
   （我们 `train_ppo.py:609` 的 `phase` 乘了 `moving()`，站桩时相位归零）。
3. **站桩在主导项上拿 0.007 分**（`exp(-7.41)`），而踏步时
   `joy_balance`/`joy_head`/`pose` 照样满 —— **踏步是站桩的严格超集，没有取舍**。
   我们的表里"走"要拿 pose/clearance/rate 去换 track，中间一定更差，
   所以站桩成了局部最优（7.36 → 4~6 → 12）。

**训练量：600 / 400 / 200 iter**（三个 joy 版本），lr 3e-4→2e-4，`init_std 0.4`。
对比我们的 2000 iter 只训出站桩、Hannes 的 12,195 iter。

**它的正确用途是 teacher + 配方，不是终点**：它不会平移（目标函数不允许），
且是 servo 训的 —— 同一只策略换到 BAM 植物（kp200/7.4 V）抬脚从 15 mm 掉到 **8–10 mm**。

---

## 4. DuckEMW 的 v1→v3 站桩病历（和我们一模一样）

`docs/03-training-log.md:94-96`：

> **v1**：站桩 0.006 m/s。机制：25% standing envs 白拿奖励质量 + air_time 固定 0.20s 下限
> （阶跃函数，0.05s 行走步态永远够不到，全程奖励 ≈0.0001）+ action_rate −1.0 摆腿税 +
> upright 过紧 → 「无视命令站桩」是 argmax。
>
> **v2**：腾空相出来了（air_time_mean 0.17s）但 error_vel_xy 2.1 m/s 不动，实测 0.04–0.11 m/s
> —— 原地高抬腿刷 air_time，无推进。**加性奖励的未约束项必被 hack。**
>
> **v3**：air_time **前向门控**（`× clamp(vx/cmd, 0, 1)`，原地腾空支付 0）+ track 权重 4.0
> 主导 + `init_velocity_prob=0.3` 逆向出生（高速前沿要有在策略数据）。
> 实测：error_vel_xy 2.1→1.18，**最快 env 1.43 m/s**。

三个机制我们全中：
- 25% standing（我们课程到 0.25）→ 白拿分
- air_time 阶跃无梯度（我们 weight 3.0 但没有前向门控，所以原地抬腿就能刷 —— 只是我们连抬腿都没学会）
- **「加性奖励的未约束项必被 hack」**

v3 的「前向门控」对我们最有价值：**任何正奖励项都要乘 `clamp(vx/cmd,0,1)`**，
否则原地做动作就能收钱。

---

## 5. 可以直接落地的改动清单

按「改动量 / 预期收益」排序，全部有源码依据。

### P-1（比 P0 更短的路径：先学会"踏步"，再学"走"）

这是 Duckverse 验证过、而且**只要 200–600 iter** 的路径，值得排在 P0 前面先试一次：

- **把 §3.6 的四项 joy 奖励 + 1.15 Hz 时钟搬进来**（约 60 行；`self.foot[:,:,2]`
  和 `self.clock` 我们已经有了，`GAIT_HZ` 现在是 1.5），**先不管前进**。
- 验收判据（照抄实测口径，不是"看起来在动"）：抬脚 **>10 mm**、
  周期 **0.87±0.05 s**、**双足同时离地 <5%**、8 秒不摔、左右峰间隔 **≈0.435 s**。
- 成了之后再上 P0 的 `forward_progress` —— 那时"第一步"已经跨过去，
  不用再从 7.36 掉到 4 再爬回来。**Duckverse 自己就是这么走的**
  （先 seed `alpha_walking`，再训 joy，不是反过来）。

> 若 P-1 一次就成了，P0 的第 2–5 项（奖励地形）可以简化；第 1 项（网络）仍然独立先验。

### P0（不动就没救）

> ⚠️ **2026-10-24 更正：P0 第 1 项（换网络）已核销，不需要执行。**
> 本文档里的「我们 = `128-128`」指的是**自写 CPU 植物链**（`repo/train_ppo.py`）。
> **mjlab GPU 链的 `MicroduckRlCfg.actor.hidden_dims` 本来就是 `(512, 256, 128)`**，
> 与官方 `microduck_velocity_env_cfg.py:913-925` 逐字相同，`critic` 也是。
> 实测确认（`out/velocity_ready.json`，`tools/check_velocity_ready.py`）：
> `actor_hidden_dims: [512, 256, 128]`、`actor obs = 61`（与部署契约 8 项同序）、`action = 14`。
> → A 路**不必再单独分「换网络」这一批**，可直接按满预算跑。
> 第 2–5 项（奖励地形）不受影响，仍然有效。

1. **网络 `128-128` → `512-256-128` ELU**。（✅ 已核销：mjlab 链本来就是，见上）26,254 → 197,774 参数（**7.53 倍**）。
   这是官方 `microduck_velocity_env_cfg.py:914-925` 的原值，kissqy 用的也是它，
   Hannes/DuckEMW 用的也是它。**三个能走/能跑的项目全是 512-256-128，只有我们是 128-128。**
   这是 kissqy 的排除法之后唯一没被排除的差异，优先级最高。
   **实测代价：几乎为零。** 4096 envs × 24 步（= 1 iter）的纯前向：
   `128-128` **0.031 s**，`512-256-128` **0.129 s**，差 **0.098 s/iter**；
   而当前 1 iter 实测 **4.9 s**（物理占 4.87 s）→ 换网络后吞吐 **20k → 19.6k steps/s**，
   可以忽略。（我先猜「会掉到 12–15k」，实测否掉了 —— 物理仿真是唯一瓶颈。）
   ⚠️ 唯一真实成本在**部署侧**：`tools/export_mcu.py:204` 的 `MD_HIDDEN` 是单宽度宏，
   换三层网络要同步改 MCU 侧的内存布局与导出。上机前要单独验这一环。
   （**补充 2026-10-24**：这条只对**自写链**成立。`export_mcu.py` 是自写链工具
   —— 它 `import train_ppo as T`、只读自写 ckpt 的 `c["obs_dim"]/c["model"]`，
   读不了 rsl_rl 的 ckpt。mjlab 链走 `export.py` 出 `.onnx`，部署端用 **ONNX Runtime**
   加载，宽度由 ONNX 自带 shape 描述，**没有 `MD_HIDDEN` 这一环**。）
2. **加 `forward_progress`**：`clamp(vx_body, 0, cap)/cap × 5.0`，`cap = 2.4`。
   新增一项，三行代码，`terms` 里加 `forward_progress`。
3. **把「静止白拿」四项砍到 Hannes 水平**：head 2.0→0、upright 2.0→0.75（std² 0.05→0.15）、
   turn 2.0→0.5、pose 1.0→0.15。站桩底分 7.36 → 约 3.6。
4. **`rel_standing_envs` 0.25 → 0.03**。站着不动的环境不该占四分之一。
5. **命令课程**：0.20–0.45 起步，每 1000 iter 抬一档，到 0.9–1.2。
   现在是固定 ±0.4，等于永远在第一档。

> **分两批上，不要一次全改。** 第 1 项（网络）单独一批 —— 它只影响容量，不改奖励地形，
> 所以「128-128 vs 512-256-128」的差异能干净地量出来。第 2–5 项（奖励地形）作为第二批。
> 如果第一批就把网络换了还能走起来，说明我们之前只是容量不够；如果换了还是站桩，
> 才轮到奖励地形。**这样每一步都有归因，不会又出现「改了八处塌了不知道是谁」。**

### P1（治走不直）

6. **加 `heading_hold`**（`exp(-wrap(yaw-yaw_spawn)²/0.4²)` × 1.5），替代或叠加 `yaw_drift`。
7. **加 `planar_drift`**（`(wz-cmd_yaw)² + 4(vy-cmd_y)²` × −0.05）。

### P2（配方卫生）

8. `air_time` 3.0 → 0（或至少加前向门控），`slip` −0.1→−0.05，`angvel` −0.05→−0.01，
   `rate` −0.1→−0.02（课程到 −0.10），`clearance/swing` target 0.02→0.015。
9. **训练量 2000 → 12000 iter**（20k steps/s × 4096 envs → 约 3.3 小时/万轮，CPU 可接受）。

### 明确不要抄的

- **`foot_swing_height` 我没建议改**：我一度以为我们把它 port 成了 exp 形式导致符号反了
  （`terms["swing"]` 越小越好却给负权重），核对 `train_ppo.py:670-673` 后确认
  **是 cost 形式，符号正确**。这是我自己的误判，不要写进任何结论。
- **Hannes 的 `rel_heading_envs=0`**：他关掉了 heading 命令，我们还得留（部署契约要）。
- **24k→ 更快的仿真步长**：他配 `implicitfast` + 5 ms + (10,20)，我们 `Euler` + 2 ms + 100/50。
  这个改动和上面的奖励改动**不要同时上**，否则塌了分不清是谁的责任。

---

## 6. 训练量预算（这台机器，全部实测）

**两条链路现在都能跑**：自写 CPU 植物（`repo/train_ppo.py`，20 核吃满）
和官方 mjlab 栈（`.venv-mjlab`，GPU）。

| 链路 | envs | 1 iter | steps/s | 600 iter（P-1） | 12,000 iter（P0） |
|---|---:|---:|---:|---:|---:|
| CPU 植物（我们） | 4096 | 4.90 s | ≈20.0k | 0.8 h | **16.3 h** |
| **mjlab GPU** | **4096** | **3.08 s** | **≈31.8k** | **0.51 h** | **10.3 h** |
| mjlab GPU | 8192 | 14.13 s | ≈13.9k ❌ | — | — |

- **8192 反而慢 4.6 倍**：8 GB 显存撑不住，**4096 是甜点**。
- GPU 的真实收益不是快 1.6 倍，是**把 20 核 CPU 腾出来**——两个实验这才真并行。
- ⚠️ **2026-10-24 更正：上面的排法不再适用。** joy 已降级为探针（它是 fine-tune 任务，
  我们却从零训了十版）；而「网络对照」只对**自写 CPU 植物**有意义 ——
  **mjlab 链本来就是 512-256-128，没有对照可做**。
  现在 GPU 直接跑 `Mjlab-Velocity-Flat-MicroDuck`，用本表 12000 iter 那一行（≈10.3 h）。
