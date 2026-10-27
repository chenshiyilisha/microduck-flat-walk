# Microduck 第三层：奖励工程与可信评测

> 这一层读的是 `src/mjlab_microduck/tasks/mdp.py`（7,188 行 / 230 个函数 / 302 KB）
> 和 `pollen-robotics/microduck-arena` + `microduck-challenges`。
> 结论：**算法是标准 PPO，复杂度全在奖励函数里，而奖励函数的历史就是一部"被机器人钻空子"的编年史。**

---

## 0. 三个最有价值的发现

1. **`mdp.py` 一开头有 4 个 monkey patch，专门修上游库的 NaN 传染和导出崩溃。** 这不是炫技，是"不这么干就跑不完一次训练"。
2. **三个奖励函数的设计原则，全部来自"被刷爆"之后的重写**：躺着抖腿刷空中时间、坐着/躺平/拿头当三脚架刷分、把头部容差调紧导致机器人干脆不迈步。
3. **竞技场把"奖励调参"做成了公开竞技**：参赛者只调三个旋钮，服务端跑 33 次仿真定成绩，本地跑的成绩官方明说不算数。

---

## 1. 302 KB 里到底是什么

230 个函数，光看名字就能看出这台机器被"针对"得多细：

| 类别 | 代表函数 |
| :--- | :--- |
| 步态 | `feet_air_time_upright`、`air_time_adaptive`、`contact_frequency_penalty`、`gait_symmetry_penalty`、`single_support_reward` |
| 起身/恢复 | `upright_progress`、`height_progress`、`standing_composite_score`、`recovery_success`、`fallen_too_long`、`face_down_prob_curriculum` |
| 头部（重灾区） | `head_pose_tracking`、`head_pose_bias_penalty`、`neck_vel_descent_penalty`、`neck_action_rate_l2` |
| 叼取 | `mouth_ground_proximity_phased`、`mouth_perpendicular_to_ground`、`sample_mouth_payload`、`apply_mouth_payload_force` |
| 轮滑 | `wheel_glide_reward`、`coasting_reward`、`braking_reward`、`roller_*` 一整套 |
| 站立/坐 | `standing_composite_score`、`seated_stillness`、`stillness_at_zero_command` |
| 域随机化 | `randomize_bam_friction`、`randomize_imu_orientation`、`expand_bam_friction_fields`、`randomize_mass_and_inertia` |
| 课程 | `standing_envs_curriculum`、`com_range_curriculum`、`push_curriculum`、`velocity_command_ranges_curriculum`、`event_param_curriculum` |
| NaN 防护 | `robot_state_is_nan`、`foot_contact_forces_safe`、`foot_height_safe`、`foot_air_time_safe` |

注意最后一行：**有 4 个单独的 `_safe` 包装器**。这说明 NaN 在这里不是偶发，是常态。

---

## 2. 四个 monkey patch：NaN 的传染链

`mdp.py` 顶部直接改上游类的方法：

```python
_orig_reward_compute = _RewardManager.compute

def _nan_safe_reward_compute(self, dt: float) -> torch.Tensor:
    result = _orig_reward_compute(self, dt)
    for key in self._episode_sums:
        torch.nan_to_num_(self._episode_sums[key], nan=0.0)
    return torch.nan_to_num(result, nan=0.0)

_RewardManager.compute = _nan_safe_reward_compute
```

**为什么必须这么做**，注释里把整条链写清楚了：

```
mjlab 在 reset 之前算 reward
→ 任何作用在 NaN 物理状态上的奖励项返回 NaN
→ NaN reward → NaN advantage → NaN loss → NaN gradient
→ std 变 NaN 或负数 → 下一个 minibatch 在 torch.normal 里直接崩
```

而 reset 是**在算完 reward 之后**才发生的，所以"反正马上要 reset"救不了它。

Patch 2 修的是另一个场景，更阴险：

> 课程突然放大（比如奖励权重 ×2.5）时，值函数严重失准：所有 TD 误差同向偏移，`std(advantages) → 极小`，归一化 `(A − mean) / (std + 1e-8)` 直接炸成天文数字，把 std 的梯度打爆，优化器把 std 推成负数。

Patch 3（std clamp）在迁移到 mjlab 1.3.0 时被**删除**了——因为 rsl_rl 5.0.1 重构了 policy，那个补丁的挂载点没了。注释很诚实：

> 「如果 1.3.0 下 std 爆炸复发，就针对新的 GaussianDistribution 重新加上。」

Patch 4 修导出：

> 新模型有被动关节（下颌连杆靠等式约束闭合），它们属于 articulation 但没有 XML actuator。上游 exporter 遍历 16 个关节名去索引 14 个 ctrl id，撞上 `passive_*` 直接 KeyError。

**还有一层防御更讲究**：三个传感器派生的 critic 观测（射线高度、接触空中时间、接触力）单独包了 `_finite()`。理由写得很清楚——

> `robot_state_is_nan` 覆盖的是关节 + 根状态，所以所有由它们派生的观测都被那次 reset 保护了。这三个不是：它们读的是传感器数据，MuJoCo 可能在机器人状态还干净的时候就返回非有限值。它们只喂 critic，所以清洗一步对策略零成本；而放它过去，rsl_rl 的 check_nan 会杀掉整个训练。

并且特意说明：**这样做不掩盖真实的物理爆炸**——真的炸了还是会通过 `nan_state` 终止，在 wandb 里以 `Episode_Termination/nan_state` 露出来。

---

## 3. 核心案例：头部占了 38% 的质量

这是整份代码里最长的一段注释，值得完整复述，因为它把"奖励设计"的坑讲透了。

`head_pose_tracking` 用的是 per-joint 高斯 `exp(-(err/std)²)` 再取均值（而不是误差平方和）。理由：

> 均值形式在只有一个关节偏的时候梯度还活着；平方和形式下单个大误差会把整个奖励打死。

然后是那个致命的问题：

> 单用一个宽 std（0.5 rad ≈ 29°）会让小误差几乎免费——重脑袋上 10° 的重力下垂只花掉约 0.03 的奖励，于是策略就让它耷拉着。

于是加了第二个窄高斯混合：`(1-w)·exp(-(err/std)²) + w·exp(-(err/fine_std)²)`，`fine_std ≈ 0.1 rad`，用来给小误差定价。

**但紧容差会带来更大的灾难。** 他们另外写了 `head_pose_bias_penalty`，注释里留着事故记录：

> 走路不可避免地摇晃一个占机器人质量 38% 的头，所以一个瞬时紧容差项**是对走路的永久征税，任何策略都逃不掉**——实测约 **0.77/step**，而当时 air_time 奖励只有约 **1.01/step**。这直接导致 2026-08-20 那次 velocity 训练**彻底放弃迈步**（wandb run `5yay13u4`）。

解法是把误差拆成两部分：

| | 能不能逃脱 | 怎么处理 |
| :--- | :--- | :--- |
| **瞬时晃动** | 逃不掉（物理必然） | 宽高斯，容忍它 |
| **稳态下垂（DC 偏置）** | 能逃掉（策略可以抬脖子补偿） | **EMA 后取 L1 惩罚**，`tau_s = 1.0 s` |

- 为什么要 EMA：对 `tau_s` 秒做平均，让振荡自己抵消掉，只给偏置定价。
- 为什么用 **L1 不用高斯**：大偏置下梯度保持常数；紧高斯在大偏置处是平的，梯度死了。
- 最妙的一层是 **gate 乘在输入误差上，而不是输出上**：

> 倒下/起身过程中 EMA 看到的是零，会自己衰减。这样直立起来时偏置时钟从 ~0 开始，而不是在终点线一次性收走整个地面阶段累积的误差——那会形成一道"恢复完成前的奖励墙"，这正是被退役的 `head_impact_penalty` 的确切失败模式。

一句话：**把"可以努力修正的"和"物理上注定存在的"分开计价，并且别在恢复的最后一刻收账。**

---

## 4. 第二个原则：只奖励"进展"，不奖励"状态"

`upright_progress` 是潜在函数式塑形（potential-based shaping）：

```python
"""Δcos(tilt) per step.
对朝直立方向的进展付钱，对朝跌倒方向的进展收钱，对"保持任何姿势"付 0。
"""
```

注释记录了它替代的是什么：

> 它替代的那个门控状态奖励，在**三次 velstand 训练里被刷过**：坐着刷、躺平刷、拿头当三脚架斜靠刷。

理论依据也点明了：**Ng et al. 的 potential-based shaping 是策略不变的（policy-invariant）——它加速学习恢复能力，但不会创造新的最优解。**

一个完整的前倒→站起能收到 Δ≈+1（×权重），摔下去的过程等额扣回。**所以没有中间状态可以囤分。**

这条比什么奖励权重都重要：**只要你的奖励是"处于某个状态就给分"，RL 一定会找到蹲在那不动的解。**

---

## 5. 第三个原则：一切用掩码门控，防止"在错误的状态下刷正确的行为"

`feet_air_time_upright` 的实现只有三行：

```python
reward = _template_air_time(env, **air_time_kwargs)
upright = 1.0 - _fallen_mask(env, asset, 0.0, gate_tilt_above_deg)  # 40°
return reward * upright
```

注释：

> velstand 任务里，一台躺在躯干上的机器人**仍然可以通过空中时间窗口有节奏地蹬腿**——这就是观测到的"躺在那儿抖一条腿"的钻空子行为。空中时间只在直立时才有意义。

`_fallen_mask` 本身也是双条件的：躯干高度低于阈值 **或** 倾角超过阈值（`cos(tilt) = 1 − 2(qx² + qy²)`）。用四元数直接算倾角，不经过欧拉角，避免奇异。

---

## 6. 奖励之外的自动转速控制

`air_time_adaptive` 会根据指令速度自动切换步态窗口：

| 指令总速度 | 窗口 |
| :--- | :--- |
| `< 0.01` | 0（站着不给钱） |
| `0.01 – 0.5` | 走路：摆动 **100–250 ms** |
| `> 0.5` | 奔跑：摆动 **50–250 ms** |

`contact_frequency_penalty` 则盯接触切换频率，超过 **4 次/秒**开始二次惩罚（`-excess²`），并且只在有指令时生效（站着不罚）。

这两条合起来做的事：**用"物理上可测的节奏指标"约束步态，而不是用"看起来像不像走"这种空洞的描述。**

---

## 7. 竞技场：把"可信"做进评测协议

`microduck-arena` 是个 Hugging Face Space，规则设计得相当严肃。几个关键决定：

### 7.1 一个参赛条目 = 33 次仿真跑

> 固定赛道 + **5 个扰动种子** + 事件声明的**全速度扫频**，取最好成绩。

sprint-2m 是前向指令 **0.20–1.20 m/s** 扫一遍。33 次 = 5 seeds × 约 7 个速度点（含扰动重跑）。

耗时也很诚实：**开发者笔记本上约 3 秒，共享 2-vCPU 的 Space 上按比例更久**，「能跑，但不是瞬时，而且没有队列」。

### 7.2 本地成绩不算数

> 浏览器里报的时间只是 devtools 里的一个数字；这个是可以复现的。
> 换台机器——Mac，或别的架构——同一个跑法会给出不同数字：**舵机模型混沌到仿真跑几秒后就会发散**，所以本地时间是参考值，不是榜上的数。

这是对"仿真结果"最诚实的态度：他们不是声称仿真准确，而是声称**在固定硬件上可复现**。

### 7.3 部署时重测基准跑，不复现就构建失败

> Space 每次上传都会重建自己。它自己的 Docker 构建会**重新测量基准跑**，如果物理不复现就失败——所以「构建失败」好过「一个静默错误的排行榜」。

这句话是整个项目里我最欣赏的一句工程决策。

### 7.4 排名永远重测，不读回

> 只恢复缺失的部分，以 Hub revision 为键……**而且成绩永远是重新测量的，从不读回：一个你无法重新验证的排名，不值得恢复。**

### 7.5 积分设计（赛季制）

| 行为 | 得分 |
| :--- | :--- |
| 某赛事首次发布 | 100 |
| 每次发布 | 10（每天上限 3 次） |
| 打破自己最好成绩 | 25（每赛事一次） |
| 守住领奖台 | 250 / 150 / 100 |

每天 3 次的上限，防的是"暴力刷提交"。打破自己记录才给分，防的是"重复发布同一份"。

### 7.6 社交片段：每次发布自动生成两个视频

- 发布完成后 Space 起一个 HF Job，跑 `arena clip <run>`
- headless Chromium **逐帧拍摄**竞技场舞台 → ffmpeg 编码
- 实测：386 帧的冲刺片段，`t4-small` 上 **75 秒**；同样的事用 SwiftShader 在 Space 自己的 8 核上是 **588 秒**；16 核机器 553 秒
- 成本约**一美分一条**

如果 Jobs API 拒绝启动，不会在别处渲染——这个 run 会「欠着」（`clips/<run>/pending.json` 是欠条），下次启动补。

---

## 8. 挑战赛：把奖励调参变成三旋钮竞技

`microduck-challenges` 的 `sprint_2m/challenge.toml` 把整个训练配方摊开了：

```toml
event = "sprint-2m"
task  = "Mjlab-Sprint2m-MicroDuck"
kind  = "perpetual"

[recipe]                  # 第一次训练，原样
num_envs       = 4096
max_iterations = 3000
seed           = 1

[params.forward_reward]
value = 2.0    # 范围 0.5 – 5.0
[params.upright_reward]
value = 2.0    # 范围 0.5 – 5.0
[params.step_reward]
value = 3.0    # 范围 0.0 – 6.0
```

**参赛者不用从零写代码——只调三个奖励权重。** 而且每个参数都声明了 `min`/`max`，超范围提交是无效的。这是"把奖励工程这个玄学环节变成可比的竞技"的干净做法。

四个赛事：

| 赛事 | 任务 | 性质 |
| :--- | :--- | :--- |
| `sprint-2m` | 平地 2 米冲刺 | 竞速 |
| `hill-climb-1m5` | 爬 1.5 米坡 | 竞速 |
| `roller-sprint-2m` | 轮滑冲刺 | 竞速 |
| `got-a-talent` | 才艺表演，20 秒，观众投票 | 非竞速，可群鸭（最多 8 只同场） |

每个挑战文件夹里还塞了 `AGENTS.md`，直接告诉 AI 编码助手「改哪些文件、怎么跑、怎么判定、规则是什么」。

---

## 9. 这一层的可迁移结论

如果你在做任何 RL 控制任务（不一定是机器人），这三条是直接能用的：

1. **奖励分两类计价**：物理上注定无法消除的扰动（用宽容忍），和策略有能力修正的稳态偏差（用 EMA + L1 精确计价）。混在一个项里，要么给策略永久征税，要么让它学会摆烂。
2. **只奖励进展，不奖励状态**。任何"处于状态 X 就给分"的项，RL 都会找到一个最省力的姿势长期待在那里。用 potential-based shaping（Δ势能），并且确认它对保持动作付 0。
3. **每个行为奖励都要问一句"这个行为在错误状态下还成立吗"**，然后用掩码门控掉。空中时间在躺着时没意义、接触力在下颌着地时没意义——这些都得显式屏蔽。

以及两条工程纪律：

4. **NaN 要从奖励入口就清洗**，别等它在 advantage → loss → std 里滚一圈。同时保证真实物理爆炸仍能从终止条件里看到（别把 bug 也一起静音了）。
5. **评测的可信度来自"可重新测量"，不是来自"跑得更久"**。固定硬件、固定种子集、固定速度扫频，并且承认本地机器上的数字不可比。

---

## 10. 一句话收尾

看完这三层，我的判断变了一点：

**Microduck 真正稀缺的东西，不是"能训出一个走路策略"——那篇论文很多。是它把"策略被机器人钻空子"的每一次事故都留在了代码注释里，还附上 wandb run id。**

那些注释（`wandb 5yay13u4`、`2026-08-20`、`三次 velstand 训练`）是任何教程都不会有的东西。它们是**失败的账本**——而这恰恰是复现一个 sim2real 系统时最贵、最难买到的部分。
