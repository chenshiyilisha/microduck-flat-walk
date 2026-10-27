# joy 踏步失败：诊断、文献对照与修法

> 时间：2026-10-24 09:20  
> run：`joy_smooth_2048x600_1024_0757`（2048 envs × 600 iter，耗时 1:10:05）  
> 验收：`out/eval_joy_sim_model599_gpu.json`（512 envs × 8 s，GPU，训练同一 env cfg）

> **术语约定（2026-10-24 全文清洗后生效，请按这个读）**
>
> | 写法                | 指的是                                                                       | 能不能当权威                      |
> | ----------------- | ------------------------------------------------------------------------- | --------------------------- |
> | **`pollen` / 官方** | `pollen-robotics/microduck_rl`（框架）、HuggingFace 公开 policy manifest         | 只在它自己覆盖的范围内                 |
> | **`Duckverse`**   | `ros-claw/microduck`（**6★，纯仿真，README 明说没上真机**）发布的 joy patch / 训练产物 / ONNX | **不能当"官方背书"**，它是唯一来源 ≠ 它是对的 |
> | **`ours` / 我们**   | 本地照产物重建的 `microduck_joy_env_cfg.py` 等                                     | 需自证                         |
>
> 关键事实：**joy 的代码、配方、产物、ONNX，`pollen` 官方仓库里一个字都没有**  
> （全文 `joy` 出现 0 次，`microduck_joy_env_cfg.py` 不在官方仓库里）。  
> 本文档旧版把 Duckverse 的东西一律称作「官方 joy」，已全文改名
> （本文档 96 处；4 份 joy 文档合计 112 处）。  
> 凡是说「官方 joy 如何如何」，请自行替换成「Duckverse joy 如何如何」再读。
>
> ⚠️ 两个**历史命名**保留未改，内容都是 Duckverse 的，别被名字骗了：
> `.upstream/official-joy-2026-10/`（存档目录）、`out/probe_joy_official.json`（实测读数）。
> 改名会打断 9 处脚本/文档引用，故只在文档层面标注。

---

## 1. 验收结果：6/8 PASS，两条真差距

| gate                           | 值           | 门槛         |          | 含义                     |
| ------------------------------ | ----------- | ---------- | -------- | ---------------------- |
| duration_s                     | 8.000       | ≥3.5       | PASS     | 撑满全程                   |
| min_upright                    | 0.9948      | >0.9       | PASS     | 全程没倒                   |
| max_drift_m                    | 0.0139      | <0.08      | PASS     | 漂移 1.4 cm              |
| **feet_peak_m**                | **0.00616** | **>0.008** | **FAIL** | **抬脚 6.2 mm，够不到 8 mm** |
| end_upright                    | 0.9999      | >0.95      | PASS     | 收尾直立                   |
| target_rate_rms                | 1.754       | <6.0       | PASS     | 伺服目标速率正常               |
| max_target_step_rad            | 0.0800      | <0.2       | PASS     | 正好是钳位值（见 §5）           |
| **pose_power_above_8hz_ratio** | **0.01264** | **<0.01**  | **FAIL** | **有关节在 8 Hz 以上颤**      |

`joy_passed = False`。上下文：`fell_frac 0.0098`、`joy_foot_rhythm_mean 0.4868`、  
`joy_balance 0.938`、`joy_drift_cost −0.0005`、`final_xy_p50 [0.0078]`。

---

## 2. 它现在在做什么：不是踏步，是微颤

三条**互相独立**的证据都指向同一结论。

**① 抬脚 6.2 mm，而目标是 24.5 mm。**  
`joy_foot_rhythm` 的 target = `0.0005 + 0.024·relu(sin p)²`，峰值 24.5 mm。实测峰值 6.16 mm  
= 目标的 **25%**。

**② 膝盖在抖，脚没动。** `knee_ac_rms = 0.167 rad`（≈9.6° 的交流分量），而  
`foot_ac_rms = 0.00156 m`（1.56 mm）。腿在震，脚几乎没离地。`8hz_ratio_knee = 0.0001` 说明  
膝盖抖动是低频的（真在尝试周期性动作），但 `8hz_ratio_foot = 0.0126` 说明脚上有高频成分。  
`8hz_gate_interpretable = True` —— 这条 gate **不是**噪声误判。

> 这正是上游那条 gate 存在的理由：`joy.py:report()` 用 FFT 把「踏步（1–2 Hz）」和  
> 「颤振（>8 Hz）」分开。脚的高频占比 1.26% > 1%，判为颤振。

**③ 周期不对。** 实测 `step_period = 0.66 s`，而 1.15 Hz 对应 **0.87 s**。它没有跟上节拍。

**④ 数值积分给出的位置。** 用 `tools/analyze_joy_feet_floor.py` 积分一个完整相位周期：

| 策略              | 周期平均奖励 |
| --------------- | ------ |
| 静止站桩（lift 0%）   | 0.3501 |
| 抬到目标的 25%       | 0.4892 |
| 抬到目标的 50%       | 0.6836 |
| 抬到目标的 75%       | 0.8981 |
| 完美跟随（lift 100%） | 1.0000 |

实测 `joy_feet` raw = **0.4868**，几乎精确落在「抬到 25%」那一行。**它在正确方向的  
路上，但只走了四分之一**，而且 plateau 了（训练日志 400→500 轮只从 0.47 涨到 0.48）。

---

## 3. 文献：别人是怎么让机器人学踏步的

> 来源标注：① ② 是**读到的源码原文**；③④⑤ 是**检索摘要**（未读论文全文，只取其中明确  
> 写出的奖励公式）；⑥ 是综述条目。**凡是没能读到原文的，不作为设计依据，只作方向佐证。**

| 来源                                                                     | 度量对象            | 公式                                                                                             | 关键特征                                                                   |                                                                    |                              |
| ---------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------ | ---------------------------- |
| ① legged_gym `_reward_feet_air_time`<br />`legged_robot.py`（原文）        | 腾空**时长**        | `Σ(air_time − 0.5)·1[first_contact]` × `1[‖v_cmd,xy‖ > 0.1]`                                   | **线性**、只在首次触地时触发、零指令直接乘 0                                              |                                                                    |                              |
| ② mjlab `feet_air_time`<br />`velocity/mdp/rewards.py:209`（原文）         | 腾空**时长**        | `Σ 1[0.05 < air_time < 0.5]`（二值计数）<br />+ 可选 `1[‖cmd‖ > 0.5]`                                  | 二值，自带 `Metrics/air_time_mean` 日志                                       |                                                                    |                              |
| ③ arXiv 2408.02662<br />(MIT Humanoid)                                 | **接触序列**        | `r_cs = 9(1_r,contact − 1_l,contact)·φ_contact·exp(−‖p̂−p‖²/σ)`，σ=0.25                         | `φ_contact = sin(2πφ)/√(sin²+0.04)` 平滑相位                               |                                                                    |                              |
| ④ *Walk This Way*<br />(ACM ToG 2025)                                  | **接触序列**        | 期望接触 == 实际接触 → **+1**，否则 **−1**                                                                | 纯二值匹配，最简                                                               |                                                                    |                              |
| ⑤ arXiv 2506.08416<br />(ILEM-1)                                       | **接触序列**        | 比较实际接触态与规划器期望态；用 sigmoid 按归一化相位平滑过渡                                                            | 相位强制 + 足速/足力惩罚                                                         |                                                                    |                              |
| ⑥ 步态 RL 综述<br />(emergentmind)                                         | —               | —                                                                                              | 明确把 **"prevent local minima such as standing in place"** 列为多目标奖励要解决的问题 |                                                                    |                              |
| **我们 `joy_foot_rhythm`**<br />`microduck_joy_env_cfg.py:39`            | **脚 site 绝对高度** | `Π_feet exp(−((z − z_target)/9mm)²)`<br />`z_target = 0.5mm + 24mm·relu(±sin p)²`              | **连续高精度高度追踪**                                                          |                                                                    |                              |
| **⑦ 上游 walking 任务**<br />`microduck_velocity_env_cfg.py:330-336`（本机源码） | 腾空时长 + 抬脚高度     | `air_time` 权重 **3.0**，窗口 **[0.125, 0.300] s**<br />`command_threshold = 0.01`（压到默认 0.5 的 1/50） | 上游**真正训出「会走」**&#x7684;那套                                               |                                                                    |                              |
| **⑧ 上游 `foot_clearance`**<br />同上 `:352`                               | 抬脚高度            | \`                                                                                             | foot_height − 0.02                                                     | × 脚速`（**惩罚项**）<br>注释：`# Increased from 0.01 to penalize dragging\` | 上游**明确针对「抬不起脚/拖地」**&#x6539;过 |

### 上游配置里的三个硬事实（本机源码可核）

这是本轮最重要的发现，因为它是**上游自己训出可用策略时用的参数**，不是我推的：

**(i) 上游 walking 用 `air_time`，而我们在 joy 里把它 pop 掉了。**  
`microduck_joy_env_cfg.py:36` 一次 pop 掉 8 项，包括 `air_time`、`foot_clearance`、  
`foot_swing_height`。上游 walking 恰恰靠 `air_time` 来 "encourages a rhythmic stepping gait  
by rewarding feet in the air"。

**(ii) 上游把 `command_threshold` 从默认 0.5 压到 0.01。**  
我在上一版文档里写「legged_gym 的 `‖v_cmd‖ > 0.1` 门控不能照抄，joy 命令恒为零会被全灭」——  
**方向对，但上游的解法不是取消门控，是把它压到 0.01**。这说明在「小速度指令」场景下，  
上游选择保留门控结构、只改阈值。

**(iii) `action_rate` 的爬升节奏差了 7.5 倍。**

```
上游 walking (:347-349):  -0.1  →  -1.0  在 iter 1500 内爬完
我们 joy PD 档 (:49-50):  -0.1  →  -1.0  在 iter 200 就爬完
```

上游给策略 1500 轮先学会踏步，再逐步收紧平滑度；我们 200 轮就锁死。  
**这与 §4(a) 训练曲线里 250 轮动作收小的时间点精确吻合。**

### 差异点

**所有文献做法用的都是「二值 / 线性」量（接触状态、腾空时长、或「偏离目标高度的代价」），  
没有一个用「脚的高度精确追踪正弦曲线」。**

原因很直观：高度追踪要求策略同时学对**相位、幅度、波形**三件事，而且 `exp(−(e/9mm)²)`  
的核宽只有 9 mm —— 峰值误差 19 mm 时该项 = `exp(−4.46) = 0.0116`，梯度与奖励一起被压平。  
而「该抬的时候抬起来」只需学一件事，且目标一旦达成就有明确的一分。

三者对「站桩」的处理尤其不同：

- legged_gym：站桩时 `‖v_cmd‖ > 0.1` 为假 → 整项 **0 分**，站桩毫无收益
- 接触序列：站桩时「该抬没抬」→ **−1**，站桩是**负分**
- 我们：站桩拿 **0.35**，抬到 25% 拿 0.49 —— 站桩是**正分且不低**

> ⚠️ 但不能照抄 legged_gym 的 `‖v_cmd‖ > 0.1` 门控。joy 任务是**原地踏步**，  
> `joy_twist_command` 输出的是位置反馈 `clamp(−2·pos, ±0.15)`，站桩时恒为 0，接上标准门控  
> 会让奖励恒等于 0。**这一条是文献方案在「原地踏步」场景下必须改的地方**，也是我们和上游  
> 任务形态的真正差别。

---

## 4. 根因：奖励差 7.8 分，但被三件事埋住了

数值积分给出：站桩 0.3501 → 完美 1.0，权重 12，**杠杆 7.8 分**。理论上足够大。三件事把它埋了：

**(a) `action_rate_l2` 的课程在 200 轮把权重推到 −1.0。** 训练曲线证据：

| iter    | joy_feet | action_rate_l2 | mean_action_acc | mean_std |
| ------- | -------- | -------------- | --------------- | -------- |
| 100     | 4.88     | −0.76          | 0.97            | 0.45     |
| **250** | 5.21     | **−2.53**      | 0.54            | 0.32     |
| 400     | 5.67     | −1.56          | 0.42            | 0.25     |
| 500     | 5.78     | −1.37          | 0.40            | 0.23     |

罚分在 250 轮触顶（正是课程把权重推到 −1.0 的时刻），**之后罚分反而回落**——它不是学会了  
平滑踏步，而是**把动作收小退回静止**。同一时段 `mean_action_acc` 从 0.97 掉到 0.40。

对照上游（`microduck_velocity_env_cfg.py:347-349`）：**同样是 −0.1 → −1.0，但上游给了  
1500 轮**，我们 joy PD 档只给 200 轮（`:49-50`）。**节奏差 7.5 倍。**  
上游 BAM 档更松：只到 −0.3，且 150/300 轮。

**(b) `mean_std` 单调衰减 0.40 → 0.25。** PPO 自动退火，一旦早期没探索出抬腿，后期  
探索力度不够跳出去。

**(c) 600 轮远低于上游预算。** `AGENTS.md`：探索档 **1024×2000**、定稿 4096×4000。  
我们是 2048×600。

---

## 5. 一个测量 bug（值 1.43 rad 穿过 0.08 rad 硬钳位）

第一次跑出 `max_target_step_rad = 1.42873`，超门槛 7 倍。但  
`JoySmoothPositionAction.process_actions` 里 `delta = clamp(alpha*(target−previous), ±0.08)`，  
**物理上不可能产生 > 0.08 的步进**。

真因：mjlab 在 `step()` **内部**完成 reset，而 servo target 在 reset 时 snap 到实测姿态  
（`initialize_joy_servo_targets`）。这个跳变可能落在上报的 `done` **前一格或后一格**，只按  
`done` 做掩码会 off-by-one，把伪影留在里面。

修法（`tools/eval_joy_in_sim.py`）：**用硬约束本身识别伪影**，而不是猜 reset 落在哪一格。

```python
is_artefact = (dtgt_raw > 0.08 + 1e-3).any(dim=-1)   # 物理上不可能是策略
```

修完 `max_target_step_rad = 0.08000`（正好钳位值），同时把  
`max_target_step_raw = 1.41317` 和 `reset_artifact_frac = 0.0325` 一起报出来，  
**没有静默"修到通过"**。

> 教训复用：上一轮同一条 gate 也出过 0.222（第 0 帧读到全零缓冲）。  
> **被硬约束钳住的量一旦超限，先怀疑测量。**

---

## 6. 修法（按改动从小到大，标注证据强度）

### 改法 0：先把 `action_rate` 的爬升节奏改回上游的 1500 轮（**最便宜，只改一个数**）


```python
# microduck_joy_env_cfg.py:45  (BAM 档)
weight_stages=[{"step": 0,      "weight": -.05},
               {"step": 750*24, "weight": -.15},
               {"step": 1500*24,"weight": -.30}]
# microduck_joy_env_cfg.py:50  (PD 档，把 -1.0 的上限对齐上游)
weight_stages=[{"step": 0,      "weight": -.1},
               {"step": 750*24, "weight": -.5},
               {"step": 1500*24,"weight": -1.}]
```

依据 §3(iii)：上游 walking 用 1500 轮爬完，我们 joy PD 用 200 轮。  
配合 §4(a) 的曲线（250 轮 action_rate 触顶、动作随之收小），**这是最可能的单点病因**。  
代价最低，且是**单变量对照** —— 只动这一个数就能知道它是不是主因。

### 改法 A：把上游 walking 的 `air_time` + `foot_clearance` 接进来（**照抄，不要自己写**）

**不要手写新的奖励函数。** 上游 walking 已经用这套训出会走的策略，参数就在本机源码里：

```python
from mjlab.tasks.velocity.mdp import feet_air_time, feet_clearance

# 上游 microduck_velocity_env_cfg.py:333-336 的原参数
cfg.rewards["air_time"] = RewardTermCfg(
    func=feet_air_time, weight=3.0,
    params={"sensor_name": "feet_ground_contact",
            "threshold_min": 0.125, "threshold_max": 0.300,
            "command_name": None},      # ← 唯一要改的一处，见下
)
# 上游 :351-352 —— 这是惩罚项（|foot_height-0.02|×脚速），权重为负
cfg.rewards["foot_clearance"] = RewardTermCfg(
    func=feet_clearance, weight=-1.0,
    params={"target_height": 0.02, "height_sensor_name": "foot_height_scan",
            "command_name": None,
            "asset_cfg": SceneEntityCfg("robot", site_names=["left_foot", "right_foot"])},
)
```

**唯一偏离上游的地方**：`command_name=None`。  
上游 walking 保留门控、把 `command_threshold` 压到 0.01；但 joy 任务的  
`joy_twist_command` 站桩时**恒等于 0**（它是位置反馈 `clamp(−2·pos, ±0.15)`），  
0 永远小于任何阈值，接门控会让奖励恒为 0。**joy 的语义本就是「全程踏步」，不存在走/停切换，  
所以不该有门控。**

**可行性已实测确认**：

- `feet_ground_contact` ContactSensor 存在，`track_air_time=True`，  
  `current_air_time` / `last_air_time` 都是可用的 `(N, 2)` 张量
- `foot_height_scan` TerrainHeightSensor 存在（`foot_clearance` 依赖它）
- 两者都不需要新建传感器

### 改法 B：按上游预算重训

`AGENTS.md`：探索档 1024×2000、定稿 4096×4000。我们是 2048×600。  
若走改法 A，`air_time` 与 `joy_feet` 会同时存在，建议先 1024×1200 看方向再放量。

### 改法 C：接触序列奖励（文献主流，但对小舵机可能过刚）

④ 的 `+1/−1` 二值匹配最简：

```python
expected = (relu(sin p)**2 > 0.5)          # 该脚此刻该不该腾空
match = (expected == actual_airborne).all(-1)
return match.float() * 2 - 1                # +1 / -1
```

风险：二值奖励对 PPO 梯度稀疏，且小舵机可能做不到「该支撑时完全不动」，  
容易把策略推向「宁可不动」。**建议在 A 有效后再试。**

> 另有旁证（检索摘要，未读原文，仅作方向）：上游训练记录里有一个 **`expE gait-ramp`**  
> 阶段，描述为「让步态奖励随前进速度线性增长，同时惩罚原地高频抖动，50k 迭代重训中」。  
> 若属实，说明**上游自己也在为「在动但没走远」重训**，且手段正是「惩罚原地高频抖动」——  
> 与我们的 `8hz_ratio` 失败项指向同一个现象。

---

## 7. 两个被我自己推翻的假说（留档，避免重犯）

**(1) "target 基准偏了 5.2 mm"——错。**  
实测脚 site 静止高度 **5.7 mm**，而 `z_target` 低谷是 **0.5 mm**，看起来要求脚压进地面。  
但数值积分显示把 floor 改成 5.7 mm 后，站桩得分从 **0.3501 升到 0.3833**——**方向相反**，  
修了更糟。原因是 floor 抬高后 target 低谷更贴近实际高度，`exp` 更接近 1。  
→ **没改。** 假说是否成立必须靠数值算，不能靠"看起来合理"。

**(2) "6 s/iter 里 learner 是瓶颈，该调 num_mini_batches"——错。**  
TensorBoard 里现成两个标量：`Perf/collection_time = 5.99 s`（97%）、  
`Perf/learning_time = 0.178 s`（3%）。  
→ **框架已经把耗时拆好并写进 TensorBoard，先读现成指标，别自己写 bench。**

---

## 8. 下一步（待确认）

**方案已经收敛到「照抄上游」，不再有我自己发明的组件。**

1. **改法 0 单变量对照**：只把 `action_rate` 的爬升从 200 轮改回 1500 轮（对齐上游 walking），  
   其余一字不动，从零重训。约 1.1 h。
   - 判据：`feet_peak_m` 是否随罚分放开而上升；`mean_action_acc` 是否不再单调下降
   - **这是唯一能干净归因的实验**，因为其他一切不变
2. 若改法 0 不足，再上**改法 A**（照抄上游 `air_time` 3.0/[0.125,0.3] + `foot_clearance`  
   target 0.02，`command_name=None`），配合更大预算
3. 每次都跑 `eval_joy_in_sim.py --num-envs 512 --device cuda:0` 出同一张 gate 表再比较

> **纪律**（`AGENTS.md`）：改奖励必须**从零重训**，不能 resume。  
> 每次只动一个可变因素，否则又回到「说不清是哪个改动起了作用」。

> **纪律**（`AGENTS.md`）：改奖励必须**从零重训**，不能 resume。

---

## 9. 更正（2026-10-24 14:00）：§4 的根因判断错了，错在 plant

> 这一节**覆盖**前面所有关于「舵机带宽不够、应该降步频/降幅」的推论。前面的数据本身没错，  
> 错的是**在哪个 plant 上测的**。原文保留，便于对照。

### 9.1 先看上游自己的验收数字

`.upstream/rc_art/audit_smooth300.json` 的 `victory` 字段，就是**同一个 joy 任务、同一个  
`feet_peak > 0.008` gate** 的参考结果：

| 指标                           | 上游 shipped policy   | 我们 `model_599.pt` |
| ---------------------------- | ------------------- | ----------------- |
| `feet_peak_m`                | **0.0185 / 0.0200** | 0.00616           |
| `min_upright`                | 0.9941              | 0.9948            |
| `max_drift_m`                | 0.0332              | 0.0139            |
| `target_rate_rms_rad_s`      | **2.515**           | 1.754             |
| `max_target_step_rad`        | **0.0800**          | 0.0800            |
| `pose_power_above_8hz_ratio` | **0.000296**        | 0.01264           |

`actuation-check.json` 同时证明：`motor_count=14`、14 个电机限幅全是 **±0.6405 N·m**、  
`max_robot_applied_external_wrench = 0.0`（即没有从外部推机器人）。  
**"No servo overrides"** 这句在 `audit_smooth300.json` 的 `method` 字段里，不是这个文件  
（此前把两处出处写串了，此处更正）。  
`victory.target_conditioner` 是 `alpha=0.25 / max_step_rad=0.08 / hz=50 / init=previous actuator target`  
—— 与我们一字不差。

**结论：1.15 Hz、24.5 mm 目标是可达的，能到 18.5–20.0 mm（75–82%）。**  
而且上游的 `max_target_step_rad` **同样打满 0.08**（钳位饱和是正常状态），  
它的命令速率 2.52 rad/s 还比我们 1.75 更快。

### 9.2 旁证（未复验，仅记录，不作为依据）

曾从 HuggingFace Space `mishig/microduck-anatomy` 读到官方 walking policy 的周期常量，  
记录如下：

```
MICRODUCK_POLICY_CYCLE_SECONDS = 0.4061   // 50 Hz, vx = 0.25 m/s
MICRODUCK_WALK_CYCLE_SECONDS   = 0.4061*2 = 0.8122
```

若成立，全周期 0.81 s ≈ **每足 1.23 Hz**，和 joy 的 1.15 Hz 基本一致。

> ⚠️ **复验状态：失败。** 2026-10-24 14:10 重试该 URL，`raw` / `resolve` 两个路径 +  
> HuggingFace API 端点，带代理与直连全部超时（`curl code=000`，`out/ref/` 至今为空）。  
> 因此这三个数字**当前无法复现**，按本项目纪律（外部未复验数字不参与设计决策）  
> **已从论据中剔除**。
>
> 结论不受影响：9.1 的上游 `audit_smooth300.json` 是**本地文件**，逐字段已核对，  
> 单独就足以证伪「必须降步频」。9.2 原本只是锦上添花。

### 9.3 真因：`pd_actuators=True` 分支跑的是 BAM 电压模型，不是位置伺服

`rc_joy.patch` 的 joy cfg 第一行是

```python
cfg.scene.entities['robot'] = deepcopy(
    MICRODUCK_STANDUP_PD_ROBOT_CFG if pd_actuators else MICRODUCK_STANDUP_ROBOT_CFG)
```

`MICRODUCK_STANDUP_PD_ROBOT_CFG` 在 develop 上不存在（只在补丁基线 commit 上），  
上一轮把**整个三元表达式删掉**，理由写的是「紧跟的 `if pd_actuators: spec_fn = joy_pd_spec`  
已经做了同样的事」。**这句是错的**：

- `spec_fn = joy_pd_spec` 只改 MuJoCo spec 里的 `forcerange`/`solref`；
- **决定关节由 XML `<position kp=0.55 kv=0>` 驱动，还是由 BAM 电压律驱动，是  
  `articulation.actuators`**；
- 它一直指向 `FrictionDRBamActuatorCfg(kp_fw=200, motor="xl330", model="m6",
  vin_range=(6.5, 8.2), delay_min_lag=3..6, 负载相关摩擦 DR)`。

所以标签是 `Mjlab-JoySmoothPD-Flat-MicroDuck`、gate 和 conditioner 全对，  
**plant 却是 BAM**。任务名、奖励、验收表全都看不出来——又一个静默错误。

### 9.4 换 plant 前后的同一测量（`out/joint_bandwidth_xmlpd.json`）

`head_yaw`、A = 0.1 rad、绕开策略的开环正弦：

| f (Hz) | BAM gain  | XML-PD gain | BAM lag  | XML-PD lag |
| ------ | --------- | ----------- | -------- | ---------- |
| 0.4    | 0.73      | **0.824**   | −23~−29° | −17.8°     |
| 0.7    | 0.75      | **0.897**   | −33~−40° | −31.8°     |
| 1.15   | 0.56–0.74 | **0.831**   | −51~−58° | −42.8°     |
| 2.0    | 0.45–0.49 | **0.650**   | −82~−89° | −69.1°     |

−3 dB 从 1.0–1.2 Hz 抬到 **2.0 Hz**；力矩 ptp 0.200 N·m（限幅 ±0.6405，31%，不饱和）。  
**§2/§4 那张「gain 0.73 平台、带宽≈步频」的曲线，整条是 BAM 电压模型的频响，不是部署伺服的。**

### 9.5 修法与状态

- `microduck_constants.py`：按 develop 上被注释掉的  
  `# -- Old actuator (XML position, MuJoCo built-in PD + friction) --` 重建  
  `pd_actuators = XmlActuatorCfg(target_names_expr=(r"^(?!passive_).*",), delay_min_lag=0, delay_max_lag=3)`  
  （`delay_*_lag` 按**物理步**计，1 ms/步 ⇒ 0–3 ms），并新增 `MICRODUCK_STANDUP_PD_ROBOT_CFG`。
- `microduck_joy_env_cfg.py`：恢复三元表达式；`apply_joy_patch.py` 原来的两条改写规则换成断言，  
  并把 `robot/microduck_constants.py` 加进同步清单（train.exe 只读 site-packages 副本）。
- 从零重训 `joy_smooth_2048x600_xmlpd`：**只改 plant 一个变量**，σ/entropy/action_rate 全部保持原值。

### 9.6 为什么之前三次 A/B 全是空结果

`0757`（σ=0.4、entropy 0.01）、`ar03`（action_rate −0.3）、`std012`（σ=0.12）  
三条曲线都停在 5.3 mm —— 但**都是在 BAM plant 里做的**。  
所以它们「没有差异」并不能推出「σ / action_rate 不重要」，  
只能推出「在这个 plant 里它们都不重要」。

→ **先确认测量所在的 plant，再比较数字。** 这是本轮唯一的教训，也是最贵的一条。

---

## 10. `pose_power_above_8hz` 的两个更正（2026-10-24 14:30）

上游 0.000296、我们 0.012645，差 **42 倍**。这是与 `feet_peak` 并列的第二个 fail。  
下面两件事都是在训练跑着的时候查的，结论都和预期相反。

### 10.1 不是测量口径问题（我原本怀疑是）

两边的实现确实不同：

|      | 上游 `joy.py:154–165` | 我们 `eval_joy_in_sim.py:81–100` |
| ---- | ------------------- | ------------------------------ |
| 信号   | 14 个关节 `qpos`       | 足高 `foot_z` + 膝角，取 `max`       |
| 窗函数  | **Hann**            | **无窗（矩形）**                     |
| 频段边界 | `f > 8`             | `f >= 8`                       |
| 聚合   | 14 通道求和后取比值         | 每通道比值，再取 `max`                 |

矩形窗旁瓣 −13 dB 并按 1/f 衰减，会把 1.15 Hz 步态的强能量漏进 8 Hz 以上——  
听起来完全能解释 42 倍。用 `tools/probe_8hz_metric_convention.py` 把**同一批合成信号**  
喂进两套口径，实测：

| hf_amp | 真值      | 上游(Hann) | 我们(矩形)  |
| ------ | ------- | -------- | ------- |
| 0.00   | 0.00000 | 0.00003  | 0.00076 |
| 0.05   | 0.00229 | 0.00365  | 0.00273 |
| 0.10   | 0.00909 | 0.01432  | 0.00927 |
| 0.20   | 0.03540 | 0.05483  | 0.03526 |

**差异 <15%，不到 2 倍。口径解释不了 42 倍。**

负对照（纯 1.15 Hz 正弦，真值 0）：上游 **0.000000**、我们 **0.000373**。  
矩形窗确实漏，但漏得很少。

### 10.2 `0.0126` 正好是「命令每步翻转」的理论值

既然不是口径，就去看形状。命令被 `max_step=0.08` 限速，一个策略完全可以**待在钳位区间内侧  
却每步反向**——那是 25 Hz（Nyquist）的方波。把这种形状喂进两套口径：

| 形状               | 上游      | 我们          |
| ---------------- | ------- | ----------- |
| 每步翻转（25 Hz）      | 0.01120 | **0.01282** |
| 每 2 步翻转（12.5 Hz） | 0.01030 | 0.01064     |
| 每 5 步翻转（5 Hz）    | 0.00209 | 0.00294     |

我们实测 **0.012645**，落在「每步翻转」那一行上。  
→ 8hz 高是**真实的策略病理**（伺服目标在钳位边界来回打），不是测量假象。  
上游 0.000296 意味着它的命令几乎完全平滑，**同一条 1.15 Hz 正弦轨迹，它可以做到很干净。**

### 10.3 但这条 gate 当时对 `model_599` 是**不可解释**的（我自己的判据 bug）

`eval_joy_in_sim.py` 里原来写的是：

```python
fft_ratio = max(foot_ratio, knee_ratio)
"8hz_gate_interpretable": bool(foot_ac > 0.002 or knee_ac > 0.03)
```

gate 取的是 `max`，可解释性却用 `or`——**一个通道的"活着"能给另一个通道的"死了"背书**。  
`model_599` 的实测值正好踩中：

| 量                 | 值                                      |
| ----------------- | -------------------------------------- |
| `8hz_ratio_foot`  | **0.0126** ← 0.0126 全部来自这里             |
| `8hz_ratio_knee`  | 0.0001                                 |
| `foot_ac_rms_m`   | **0.00156 m（1.56 mm）** ← 低于自己定的 2 mm 线 |
| `knee_ac_rms_rad` | 0.167 rad                              |

膝角动了 9.6°，于是 `or` 判为 True，把一个「足高 AC 只有 1.56 mm」的读数当成了真 chatter。  
可 `1.56 mm` 正是这个模块 docstring 里警告的情况——*"0.2 mm of solver noise that happens to  
be high-frequency scores the same as 20 mm of real chatter"*。

**修法**：追到真正贡献 `max` 的那个通道再判。

```python
"8hz_gate_channel": "foot" if foot_ratio >= knee_ratio else "knee",
"8hz_foot_interpretable": bool(foot_ac > 0.002),
"8hz_knee_interpretable": bool(knee_ac > 0.03),
"8hz_gate_interpretable": bool(foot_ac > 0.002 if foot_ratio >= knee_ratio else knee_ac > 0.03),
```


用 `model_599` 的真实数值验算：旧判据 `True` → 新判据 **`False`**。

→ 含义：`model_599` 那条 8hz fail **是 feet_peak 只有 6 mm 的影子，不是独立的第二个病**。  
脚几乎不动时，残余的接触/求解器噪声在 8 Hz 以上占比自然高。**要解决的仍然只有抬脚高度一条。**

注意这个修正**不会**放过真问题：等新策略把脚抬到 18 mm，`foot_ac` 会远超 2 mm，  
`8hz_gate_interpretable` 就变 True，那时 0.0126 才是真 chatter、必须处理。上游 18–20 mm  
抬脚配 0.000296，说明「抬起来」和「平滑」可以同时成立。

### 10.4 顺带把 BAM 复测做成了单变量

想拿 BAM plant 就得换任务，但 `Mjlab-Joy-Flat-MicroDuck` 的动作项是  
`JointPositionActionCfg`——**没有 conditioner**。而策略是在 α=.25 / max_step=.08 下训出来的，  
直接换任务等于同时改 plant 和动作空间，数字无法归因。

`eval_joy_in_sim.py` 新增 `--plant {default,bam}`，只替换 plant 的两处定义  
（`articulation.actuators` + `spec_fn`：`joy_pd_spec` ↔ `get_standup_spec`），  
action term 原样保留；输出 json 强制记录 `actuators / spec_fn / action_term / conditioner`  
四项，用来自证 conditioner 没被顺手改掉。冒烟结果：

```
plant: bam   actuators=[FrictionDRBamActuatorCfg]   spec_fn=get_standup_spec
action_term=JoySmoothPositionActionCfg   conditioner={joy_alpha 0.25, joy_max_step 0.08}
```

`tools/eval_joy_plants.sh <ckpt>` 把它串成「同一权重 × 两个 plant」的并排表。  
跨 plant 加载已确认可行：两个任务的 obs 项完全一致（actor 8 项、critic 14 项）。

### 10.5 这一轮的三条方法论

1. **怀疑测量之前，先把测量本身量化。** 我本来笃定「无窗泄漏 = 42 倍」，写了个脚本之后  
   发现自己错了（<2 倍）。如果直接去改窗函数，就会把真实病理当成假象抹掉——  
   那比不查更糟，因为它会**让 gate 变绿**。
2. **`max` 和 `or` 是一对必须配套的东西。** 取 `max` 的指标，可解释性只能由产生 `max`  
   的那个通道决定。用 `or` 就等于让最活跃的通道替最安静的那个背书。
3. **一个数字要能归因，前提是只动一个变量。** `--plant` 只换 plant 不换 action term，  
   正是为了让「BAM 上摔了」这句话有意义——否则分不清是 plant 变了还是动作空间变了。

---

## 11. 验收表对齐：上游 10 项 vs 我们 8 项（2026-10-24 14:40）

### 11.1 逐条对表

上游 `joy.py:168–182` 的 `passed` 是 10 个条件：

```
finished_at is not None
duration >= 3.5
min_upright > 0.9
max_drift < 0.08
(feet_peak > 0.008).all()          <- 注意 .all()
xmat[trunk_body_id, 8] > 0.95      <- end_upright
foot_support(m, d)                 <- 我们缺这项
rms < 6
max_target_step < 0.2
motion_hf_ratio < 0.01
```

我们的 `GATES` 8 项与其中 8 条一一对应（`feet_peak > 0.008` 是上游原生的，不是自加标准）。  
**唯一缺的是 `foot_support`**，它 `from .world import foot_support`。

**这个模块取不到**：`api.github.com/repos/JoyandAI/microduck_rl/git/trees/develop?recursive=1`  
返回 1059 个文件，**其中没有 `world.py`，也没有 `parkour/` 目录**；raw 的 develop/main/master  
三条分支全部 404。也就是说 `joy.py` 依赖一个**未随仓库发布**的模块。

→ 因此我们只能保留 `~foot_support_proxy`（「至少一只脚在 8 mm 以内的时间占比」），  
并在 `_note` 里写明：**`joy_passed == True` 不等于「上游会发货这份策略」**，  
因为在最严格的意义上它还差一项无法复现的检查。

### 11.2 真 bug：`feet_peak` 混了两只脚

```python
# 旧
feet_peak_m = float(foot_z.max(dim=0).values.median())   # [T,N,2] -> 一个分布
```

`foot_z` 是 `[T, N, 2]`（时间、env、左右脚）。`max(dim=0)` 得到 `[N, 2]`，  
再 `.median()` 是把**所有 env 的所有脚**混成一个分布取中位数。  
而上游是 `self.feet_peak = np.zeros(2)` 分别记录，gate 为 `(feet_peak > 0.008).all()`  
——**两只脚都必须过 8 mm**。

负对照（60/64 个 env 右脚拖在 2 mm、左脚抬 20 mm，即「学会了一条腿拖行」）：

| 口径              | 值           | gate               |
| --------------- | ----------- | ------------------ |
| 旧：两脚混合取中位数      | **20.0 mm** | **PASS** ← 放过拖行的步态 |
| 新：每脚各自中位数，取较差那只 | **2.0 mm**  | FAIL               |

**危险方向**：拖地的 env 越多，抬高的那侧越容易占据中位数，旧口径越容易通过。

修法：

```python
peak_per_foot = foot_z.max(dim=0).values                    # [N, 2]
feet_peak_each = peak_per_foot.median(dim=0).values         # [2]
feet_peak_m = float(feet_peak_each.min())                   # gate 用较差那只
feet_peak_worst_env = float(peak_per_foot.min(dim=1).values.min())
```

context 里另报 `feet_peak_left_m` / `feet_peak_right_m` / `feet_peak_worst_env_m`。

> 顺带一条方法论：**第一次负对照没通过**。我用 50/50 构造（一脚 20 mm、一脚 2 mm 各半），  
> `torch.median` 在偶数长度时取较小的中间值，两侧都落回 2 mm，新旧口径都 FAIL。  
> 只有按真实情形「多数抬起、少数拖地」构造，差异才显出来。  
> **负对照的构造比例本身就是假设**，比例错了会得到「两边一样」的假结论。

### 11.3 假警报：`min_upright` 的 `mean` 不该改

`min_upright = up.mean(dim=1).min()` 看起来和上面同类——「先跨 env 平均，会把个别摔倒抹掉」。  
我按这个直觉改成了 per-env 中位数，**负对照直接推翻**：

| 摔倒数（64 env，0.995→0.10） | mean（原写法）      | median（我改的） |
| ---------------------- | -------------- | ----------- |
| 5/64                   | 0.925 PASS     | 0.995 PASS  |
| 10/64                  | **0.855 FAIL** | 0.995 PASS  |
| 33/64                  | 0.534 FAIL     | 0.100 FAIL  |

64 个 env 里一个从 0.995 掉到 0.1，只让均值掉 0.014——所以 **10/64 摔倒就跌破 0.9**。  
而中位数要 **33/64** 才跌破。**mean 才是最保守的口径，median 是放宽。**  
我是以「收紧」为名义把它改松的，已恢复，只额外报出  
`min_upright_worst_env` / `end_upright_worst_env`，让少数摔倒可见而不是被平均掉。

（注释第一版写「6/64 就跌破」也是错的：实测 6/64 时 mean = 0.911，仍 PASS。已改为 10/64。）

### 11.4 教训：看起来同类的两个 bug，必须各自做负对照

`feet_peak` 和 `min_upright` 的代码形状几乎一样（都是对大张量做 `max` 再 `median` / `mean` 再 `min`），  
但一个是**把两个不同物体混进同一个分布**（错），一个是**跨样本平均**（对，而且更保守）。

如果按同一个直觉批量改，结果会是**一个修好、另一个改坏**——而改坏的那个方向恰好是  
**让 gate 变绿**。这比不修更危险，因为它把「不合格」变成「合格」，且没有任何报错。

→ 判据：改任何聚合方式之前，先写下「我希望它在什么情况下变红」，然后**构造那个情况**。  
红不了就是改错了方向；红得太多（像 50/50 的 feet_peak）说明构造不具代表性。

---

## 12. Duckverse 参考实现拿到了，同时 §9 的结论被自己的实验否掉（2026-10-24 15:00）

### 12.1 一手资料：Isaac Lab 里就有 Microduck 任务

NVIDIA 那篇博客（`huggingface.co/blog/nvidia/microduck-isaac-lab-sim-to-real`）指向的  
不是论文，是**可直接读的配置**。`api.github.com/repos/isaac-sim/IsaacLab/git/trees/main?recursive=1`  
返回 5288 个文件，其中 **22 个含 `microduck`**：

```
source/isaaclab_assets/isaaclab_assets/robots/microduck.py        <- 执行器与齿隙
source/isaaclab_tasks/isaaclab_tasks/contrib/microduck/flat_env_cfg.py
source/isaaclab_tasks/isaaclab_tasks/contrib/microduck/mdp/{actions,commands,rewards,events,observations}.py
source/isaaclab_tasks/isaaclab_tasks/contrib/microduck/agents/rsl_rl_ppo_cfg.py
```

已全部落盘到 `.upstream/isaaclab_microduck/`（`raw.githubusercontent` 时通时断，改用  
`contents` API + base64，一次全成功）。

**官方执行器配置与我们仓库里那份逐字一致**：

```python
BamActuatorCfg(joint_names_expr=["^(?!passive_).*"], motor=_XL330_MOTOR_CFG,
               kp_fw=200.0, vin=7.4, vin_range=(6.5, 8.2),
               vin_drop_gain_range=(0.0, 0.2), vin_min=6.0,
               min_delay=3, max_delay=6)
```

`_XL330_MOTOR_CFG` 是 `model="m6"` + 14 个拟合参数（`kt=0.36601349688984386`、  
`resistance=2.8113923539223227`、`max_current=1.75`、各项摩擦…），注释写明  
`fit from Rhoban BAM revision 62bd8ce…`。→ **我们的 BAM 模型不是自造的，是官方同一个拟合。**

### 12.2 Duckverse vs 我们，逐项对照

| 项            | Isaac Lab 官方 walking                                                                               | 我们 `Mjlab-JoySmoothPD`                     | XML-PD         |
| ------------ | -------------------------------------------------------------------------------------------------- | ------------------------------------------ | -------------- |
| `sim.dt`     | **0.005（200 Hz）**                                                                                  | 0.002（500 Hz）                              | 0.001（1000 Hz） |
| `decimation` | 4                                                                                                  | 10                                         | 20             |
| 控制频率         | **50 Hz**                                                                                          | 50 Hz                                      | 50 Hz          |
| 执行器延迟        | `min_delay=3, max_delay=6`                                                                         | 同左                                         | `0..3`         |
| **折算成毫秒**    | **15–30 ms**                                                                                       | **6–12 ms**                                | **0–3 ms**     |
| 齿隙           | **±1°（`_backlash` 预设，passive hinge 串联）**                                                           | **无**                                      | **无**          |
| 脚部目标高度       | `0.02 + 0.0225 = 0.0425 m`（在 `ankle_*` body 上量）→ **离地 20 mm**                                      | 24 mm（在 `left_foot` site 上量）               | 同              |
| 脚部奖励         | `air_time_windowed(+3.0, 0.125–0.3 s)`、`foot_clearance(−2.0)`、`foot_swing_height(−0.25·(t/0.02)²)` | `joy_foot_rhythm(exp(−(Δ/9mm)²)·∏, +12.0)` | 同              |
| 步态时序         | **不指定**（自由学到）                                                                                      | **强制 1.15 Hz 正弦**                          | 同              |
| DR           | 摩擦 .7–1.3、编码器偏置 ±.015、躯干质量 ×.95–1.05、CoM ±3→±15 mm、armature/关节摩擦 ×.9–1.1、推力 3–6 s ±.3 m/s          | 见 velocity 模板                              | 去掉关节摩擦         |
| 终止           | `bad_orientation` 70°                                                                              | —                                          | —              |

三条**可以立刻量化**的差异：

1. **延迟短了 2.5–5 倍，而且原因是「数字照抄、时基不同」。**  
   `min_delay=3, max_delay=6` 在官方是**物理步**，`dt=5 ms` → 15–30 ms；  
   mjlab 这份移植 `dt=0.002` → 6–12 ms，XML-PD 更被设成 `dt=0.001` + `0..3` → **0–3 ms**。  
   同一组数字，物理含义差 5 倍。**这是移植时没改时基的典型静默错误**（不是我们引入的，  
   但我们在它上面训练）。
2. **齿隙 ±1° 完全没有。** 官方把它做成 `MICRODUCK_BACKLASH_CFG` 预设，14 个伺服各串一个  
   `passive_{name}_backlash` hinge，`_HEAD_PLAY_JOINT_CFG` 让头部奖励只惩罚伺服、  
   不惩罚靠死区的 play hinge。这是**官方认为 sim2real 必须有的**一项，我们的 BAM 里没有。
3. **我们规定的波形比官方狠**：官方只要求「峰值 20 mm + 滞空 0.125–0.3 s」，形状自由；  
   我们要求**逐个时刻贴着 24 mm 的半正弦凸包**，σ 只有 9 mm。
   > ⚠️ **此处原本写的「凸包峰值靠高次谐波、被一阶滞后削平」是错的**：  
   > 离线卷积实测只削掉 28%（17.75/24.49 mm），解释不了 79% 的损失。真正的放缩因子见 **§13**。

### 12.3 本轮实验：§9 的「真因是 plant」被否掉了

从零重训 `joy_smooth_2048x600_xmlpd`（600 轮，40:45，4.35 s/iter），然后用  
`tools/eval_joy_plants.sh` 把**同一份权重**过两个 plant（64 env × 8 s）：

| gate                     | XML-PD（训练所在）             | BAM               |
| ------------------------ | ------------------------ | ----------------- |
| `feet_peak_m`            | **0.00570** FAIL         | 0.04986 "PASS"    |
| `feet_peak_left / right` | 0.00583 / 0.00570        | 0.04986 / 0.05195 |
| `duration_s`             | 8.00                     | **0.90**          |
| `fell_frac`              | 0.0156                   | **0.7031**        |
| `reset_artifact_frac`    | 0.01                     | **0.5675**        |
| `pose_power_above_8hz`   | 0.01640 FAIL             | 0.04020 FAIL      |
| `max_drift_m`            | 0.01310                  | 0.17217 FAIL      |
| `8hz_gate_interpretable` | False（`foot_ac` 1.27 mm） | True              |

两件事：

- **换 plant 没有解决抬脚。** 在它自己训练的 XML-PD 上还是 **5.70 mm**，和换之前那三次  
  （5.64 / 5.32 / 5.36）在同一水平。§9 写的「真因是 plant 挂错」**是错的** ——  
  那个诊断当时只有频响数据、没有训练结果，现在有了。
- **BAM 那一行的 49.9 mm 是假象，一个字都不能用。** episode 只活 0.90 s、70% 的 env 摔倒、  
  56.75% 的样本是 reset 伪影——脚之所以「抬 5 cm」，是因为机器人在抽搐着倒地。  
  → 这条恰好证明 `reset_artifact_frac` / `fell_frac` 这两个字段是必须的：  
  否则 `feet_peak` 会**因为失败而变绿**。XML-PD 训练出的策略在 BAM 上**直接不迁移**。


同时 `feet_peak_left 5.83 / right 5.70` 几乎相等 → 不是 §11 里那种「一条腿拖行」，  
而是**两条腿都不抬**，所以 §11.2 那个 per-foot 修正这次不是关键。

### 12.4 现在的因果链（把三处测量接起来）

| 观测                 | 数值                                 | 出处                                         |
| ------------------ | ---------------------------------- | ------------------------------------------ |
| 策略命令的脚高（FK 反推）     | 24.7 mm                            | `trace_joy_foot_phase.py`，FK 负对照 0.0000 mm |
| 实际脚高               | 5.3–5.7 mm                         | 同上 + 本轮 eval                               |
| 关节跟踪 R² / 幅度比 / 滞后 | 0.73 / 0.55–0.59 / 130 ms          | `probe_joint_tracking.py`                  |
| 一阶滞后换算             | τ=0.13 s，−3 dB ≈1.2 Hz，cos54°=0.59 | 自洽                                         |
| 官方目标               | 20 mm 离地，**峰值口径**而非逐点口径            | 本节 12.2                                    |
|                    |                                    |                                            |

→ 「关节跟不上一阶滞后」这句**过头了**（见 §13.1）。实测是：四条腿各自的跟踪比 0.41–0.79，  
但**滞后相差 100–220 ms**，而脚高是「抬脚项 − 放脚项」之差，于是空中对消（§13.2）；  
并且策略命令的膝幅度只有 31.6°，而 FK 反解抬 24 mm 需要 70.9°，且膝在前 0.5 rad 是零/负贡献（§13.3）。  
官方绕开这件事的办法不是提高带宽，是**换口径**：只奖励「峰值到 20 mm」和「滞空 0.125–0.3 s」，  
不要求逐时刻贴合。

### 12.5 下一步（按性价比排序）

1. **把 `joy_foot_rhythm` 从「逐点贴合」改成「峰值 + 滞空」口径**（照 Duckverse 的  
   `foot_swing_height` + `air_time_windowed` 改写），保留 1.15 Hz 相位时钟。  
   这是唯一能直接解释「命令 24.7 / 实际 5.3」的改法，而且官方已经在真机上验过。
2. **补齿隙 ±1°**（`passive_*_backlash`），并**把延迟按毫秒校正**：BAM 用 `dt=0.005`  
   或把 `min/max_delay` 改成 8..15（0.002 s 下 = 16–30 ms）。这两项是 sim2real 正确性，  
   不指望它们提高抬脚高度。
3. 目标 24 mm 暂时保留（官方 20 mm，我们高 20%，不是主要矛盾）。

> 方法论：这一轮是「外部一手配置」第一次直接给出**可照抄的替代口径**。  
> 之前所有资料都只提供「应该是什么量」，这次提供的是「应该怎么算这个奖励」。  
> 而 §9 的错误也验证了同一条：**没有训练结果的诊断，只能算假设。**

---

## 13. 真正的放缩因子：膝盖在站立位是奇异的（2026-10-24 15:20）

### 13.1 我先提出的「谐波被一阶滞后削平」——**被自己的离线检验否掉了**

上一节把 5.3/24.7 解释成「凸包的峰值靠高次谐波，一阶滞后过不去」。这一条可以直接算：  
把真实目标 `0.5 + 24·relu(sin p)²` 用实测的一阶滞后（τ=0.13 s，50 Hz 离散）滤一遍。

| 波形                       | 命令峰值     | 经 τ=0.13 s 后 | 比值    |
| ------------------------ | -------- | ------------ | ----- |
| `relu(sin p)²` 凸包（我们的目标） | 24.49 mm | **17.75 mm** | 0.725 |
| 24 mm 正弦（同峰值的光滑替代）       | 24.50 mm | 22.02 mm     | 0.899 |
| `relu(sin p)⁴` 更窄的凸包     | 24.48 mm | 15.61 mm     | 0.638 |
| 负对照 τ=0                  | 24.49 mm | 24.49 mm     | 1.000 |

τ 扫描：要压到 5 mm 需要 **τ > 0.5 s**；τ=0.19 s（即 54° 滞后在 1.15 Hz 下的等价值）仍有 ~15 mm。  
**滞后只能解释 28%，解释不了 79% 的损失。这条假说作废。**

### 13.2 关节级数字：每条 41–79%，但滞后相差 100–220 ms

`out/joint_tracking.json`（model_599，最长无 reset 段，301 样本）：

| 关节               | 命令幅度  | 实际幅度  | 比值       | 滞后         |
| ---------------- | ----- | ----- | -------- | ---------- |
| `left_hip_pitch` | 63.0° | 49.5° | **0.79** | 120 ms     |
| `left_knee`      | 31.6° | 20.7° | 0.65     | **220 ms** |
| `left_hip_roll`  | 45.2° | 20.5° | 0.45     | 100 ms     |
| `left_ankle`     | 42.4° | 17.3° | 0.41     | 140 ms     |

**脚高是大项之差，不是大项之和。** 抬脚的贡献（hip_pitch）和放脚的贡献（ankle）滞后差 20 ms、  
knee 更晚 100 ms，这个组合在空中对消 —— 每条腿单看都有「一半以上跟上了」，  
合起来却是 5 mm。这是「逐时刻贴合」判据最怕的失败模式。

### 13.3 FK 硬数据：抬 24 mm 需要 70.9° 膝，策略只命令 31.6°

在官方 HOME 位（`robot_walk.xml` 的 `qpos0` + `MICRODUCK_CFG.init_state`，躯干 z=0.117），  
用 MuJoCo FK 量「左脚 site z − 右脚 site z」：

| 弯左膝   | −0.05 | −0.1  | −0.2  | −0.3  | −0.5  | −0.7      | −0.9  | −1.2       | −1.5   |
| ----- | ----- | ----- | ----- | ----- | ----- | --------- | ----- | ---------- | ------ |
| 高差 mm | −0.84 | −1.52 | −2.42 | −2.67 | −1.27 | **+2.63** | +8.87 | **+22.05** | +38.74 |

**膝的曲线先负后正，前 0.5 rad 完全是零/负贡献**（弯膝的同时小腿前摆，脚先往前下方走）。  
反解：抬 24 mm 单靠弯膝需要 **1.238 rad = 70.9°**。

而策略命令的膝幅度只有 **31.6°（0.55 rad）** —— 落在负贡献区。  
所以「膝盖跟不上」不是主因，**是命令本身就少了一半以上**。

更强的替代路径：

| 关节          | +0.3 rad  | +0.7 rad      | 抬 24 mm 约需   |
| ----------- | --------- | ------------- | ------------ |
| `hip_roll`  | +11.64 mm | —             | ~0.55 rad    |
| `hip_pitch` | +5.49 mm  | **+25.31 mm** | ~0.68 rad    |
| `knee`      | −2.67 mm  | +2.63 mm      | **1.24 rad** |

→ 膝是这台机器上**抬脚效率最差**的关节（在站立位近奇异），hip_roll / hip_pitch 只要 0.55–0.68 rad。  
策略选了最难的那条路（命令膝 0.55 rad），而且没走到位。

### 13.4 已做的改动与在跑的实验

`tools/patch_joy_foot_peak.py`：把 `joy_feet` 的判据从**逐时刻贴合**  
`exp(-((h(t)-target(t))/9mm)²)` 换成**摆动窗内运行峰值**  
`exp(-((peak-24mm)/9mm)²)`。权重 12、目标 24 mm、容差 9 mm、1.15 Hz 相位时钟、  
σ/entropy/action_rate/plant **全部不动**，单变量。

理由随之改成上面这条（而不是谐波）：峰值判据不计较「哪一刻到峰值」，  
对四条腿滞后不同造成的空中对消不敏感。

早期信号（第 18 轮，**不作结论**）：`Metrics/joy_peak_height_max` 0.0338→**0.0374 m**；  
旧 run 600 轮最终 `feet_peak` 是 0.0057 m。但这是 2048 个 env 里的 **max**，  
必须等完整 eval 的 median + per-foot 数字。

### 13.5 如果这次还不行，下一个变量已经明确

不是奖励，是**让策略走 hip_roll/hip_pitch 而不是膝**，或者**放宽站立位**（`joy_balance` 的  
躯干高度 0.117 固定，腿伸直 → 膝落在奇异点）。可查的量化判据：  
`out/joint_tracking.json` 里 `left_knee.target_range_deg` 若仍 ≈30°、而 `feet_peak` 不涨，  
就说明策略没换路径；若 `target_range_deg` 涨到 60°+ 但 `pos_range` 不动，那才是跟不动。

---

## 14. 连续三次改判据的实验记录（2026-10-24 15:30–15:50）

§13.4 那次「峰值判据」的实验**失败了**，而且失败方式有价值。这里把三版都记下来，  
因为其中两版**把情况变差了**，而变差的原因比成功更能定位问题。

### 14.1 尝试一：峰值判据（`joy_*_peak`）——奖励被饿死

判据 `exp(-((peak-24mm)/9mm)²)`，仍是**两足相乘**。结果：

- `Episode_Reward/joy_feet` 从第 ~30 轮到 **200 轮恒为 0.0000**
- 第 206 轮手动停止

原因是算术，不是调参：站立时两脚峰值各约 6 mm，单因子 `exp(-(18/9)²)=0.018`，  
乘积 `3e-4`，乘权重 12 得 0.004；而每个摆动窗**开始时**运行峰值为 0，  
因子 `exp(-7.1)=8e-4`。**乘积 + 容差中心离实际值 18 mm ⇒ 整项恒≈0，没有梯度。**

原判据没这个问题：站姿下目标是 0.5 mm、实际 ~5 mm，因子 `exp(-(4.5/9)²)=0.78`  
——老判据是**给站立发钱的**，所以它有 0.48 的基线，也因此一直有活梯度。

### 14.2 尝试二：Duckverse 三奖励加法结构（`joy_*_trio`）——任务失去自举

照官方搬 `feet_air_time(+3.0)` / `feet_clearance(-2.0)` / `foot_swing_height(-0.36)`：  
权重、结构、容差公式全部照抄，只把滞空窗从 (0.125,0.3) 改成 (0.25,0.55) 以匹配 1.15 Hz。  
结果：

- 第 **57** 轮 `Episode_Reward/joy_air_time` = **0.0000**
- `Metrics/joy_swing_peak_at_landing` = **0.0001 m（0.1 mm）** —— 机器人基本不抬脚
- 手动停止

原因：**官方的设计靠速度指令逼它迈步**（`track_lin_vel` 要求跟踪非零速度）。  
joy 任务把速度指令全置零（原地踏步），所以没有任何一项付钱给「动起来」。  
`foot_clearance` 是按脚速加权的，站着不动代价为 0；`air_time` 要滞空 0.25 s 才有分，  
而它连脚都不抬。  
→ **`joy_foot_rhythm` 在这个任务里不只是「高度指标」，它是唯一的驱动项。删掉它不是改判据，是删任务。**

### 14.3 尝试三：保留驱动项，只放宽容差（`joy_*_sig018`，在跑）

真正的量化原因：`exp(-((h-24)/σ)²)` 在**实测 h≈5.7 mm** 处

| σ            | 值          | 梯度 d/dh         |
| ------------ | ---------- | --------------- |
| **9 mm（原值）** | **0.0160** | **0.00723 /mm** |
| 12 mm        | 0.0977     | 0.02484 /mm     |
| **18 mm**    | **0.3557** | **0.04018 /mm** |

σ=9 时策略待在**高斯平尾巴**上：离峰值 18 mm，抬高 1 mm 只换来 0.7% 的奖励变化。  
这也解释了为什么之前换 σ_actor（0.4 / 0.12）、换 action_rate 全是空结果——  
那些改的是「在哪里采样」，不是「那里有没有梯度」。

**代价是明说的**：σ 放宽会让「站立 0.356 vs 完美 1.000」的对比度从 62× 降到 2.8×。  
所以这一轮检验的是一个**具体论断**：卡点是 6 mm 附近没梯度，而不是目标 24 mm 太高。  
若 `feet_peak` 动了，下一轮可以把 σ 收窄回去（那时策略已不在尾巴上）。

为什么取 18 而不是 12：18 mm 正好是**命令本身已经失效的位置**——  
命令膝 1.238 rad 在 1.15 Hz 下需要 ~8.9 rad/s，而部署用的条件器  
`joy_max_step=0.08 rad @ 50 Hz` 把每个关节卡在 **4.0 rad/s**：

| 路径          | 抬 24 mm 需要 | 往返峰值速度         | 被钳位？  |
| ----------- | ---------- | -------------- | ----- |
| `knee`      | 1.238 rad  | **8.94 rad/s** | **是** |
| `hip_pitch` | 0.680 rad  | 4.91 rad/s     | 边界    |
| `hip_roll`  | 0.550 rad  | 3.97 rad/s     | 否     |

钳位下单个摆动最多走 `4.0 × 0.435 / 2 = 0.870 rad` 单程 → **纯膝路径被卡在 0.87 rad，  
即 FK 表上的 ~8.8 mm**。这与实测 5.3–5.7 mm 同一量级。  
→ 抬脚**必须**走 hip_roll / hip_pitch；纯膝路线在条件器下到不了 24 mm。

早期信号（第 2 轮）：`joy_feet` = **0.6797**，同阶段老 run 是 0.1610 / 0.4546。  
只说明信号活了，不作结论；验收仍看 600 轮后的 `feet_peak`。

## 15. 真正的根因找到了：`target` 的时间平均撞上站姿高度（2026-10-24 16:05）

### 15.1 先报 `sig018` 的结果：**没有改善**

`joy_smooth_2048x600_sig018`（2048 env × 600 iter，39 min 33 s）验收：

| gate                          | value                                         | 结果   |
| ----------------------------- | --------------------------------------------- | ---- |
| `feet_peak_m`                 | **0.00533**（左 5.33 / 右 5.53 / worst-env 3.97） | FAIL |
| `pose_power_above_8hz_ratio`  | 0.01133                                       | FAIL |
| `min_upright` / `end_upright` | 0.9967 / 0.9999                               | PASS |
| `target_rate_rms`             | 1.255（上游 2.515）                               | PASS |
| `joy_foot_rhythm_mean`        | 0.4794                                        | —    |

**奖励从 0.16 涨到 8.5 分（训练日志 `joy_feet` 8.34–8.58，满分 12），物理抬脚  
5.33 mm，与四版全部同级（5.32 / 5.36 / 5.64 / 5.70）。实测脚高比站姿 5.7 mm 还低  
0.37 mm。**

这是典型的静默失效：**输出落在「看起来合理」的区间里**。奖励动了 50 倍，物理量一动  
不动 —— 说明奖励和物理量已经解耦。

### 15.2 §13.3 的「纯膝上限 8.8 mm」是**错的**，方向搞反了

我当时是沿 HOME 往**负方向**扫膝（−0.05…−1.5），看到前 0.5 rad 贡献为零，就推断  
「抬 24 mm 需膝 1.238 rad = 70.9°」。用 `tools/probe_foot_lift_ceiling.py` 重扫  
（躯干固定在 z=0.117、右腿锁 HOME、脚高按**支撑脚相对**度量）：

| 关节          | dq    | 脚高增量          | 备注                      |
| ----------- | ----- | ------------- | ----------------------- |
| `knee`      | +0.20 | **+4.86 mm**  |                         |
| `knee`      | +0.40 | **+11.97 mm** |                         |
| `knee`      | +0.60 | **+21.05 mm** | 34°，早就够了                |
| `knee`      | +0.80 | +31.74 mm     |                         |
| `hip_pitch` | +0.60 | +19.14 mm     |                         |
| `hip_roll`  | +0.40 | +17.34 mm     | 限位只到 +0.38&#x34;**，卡死** |
| `ankle`     | +0.80 | +7.20 mm      | 最弱                      |

按 `max|dq_i| ≤ C` 求四关节组合上限：

| 预算 C      | 脚高上限         | 说明               |
| --------- | ------------ | ---------------- |
| 0.870 rad | **115.2 mm** | 对称摆动、半周期 0.435 s |
| 1.740 rad | 197.1 mm     | 单调上升用满半周期        |
| 2.610 rad | 206.2 mm     | 用 75% 步态周期       |

反查「达到某高度最少要多少行程」：

| 目标        | 需要的 \`max    | dq | \` |
| --------- | ------------ | -- | -- |
| 8 mm      | 0.14 rad     |    |    |
| 12 mm     | 0.19 rad     |    |    |
| 18 mm     | 0.23 rad     |    |    |
| **24 mm** | **0.28 rad** |    |    |

**结论：24 mm 只需要任一关节动 0.28 rad，是 0.870 预算的 1/3。物理上毫无难度。**  
之前「纯膝卡在 8.8 mm」的结论作废 —— 它同时假设了「只用膝」和「对称正弦往返」，  
两个假设都不必要。

### 15.3 真正的根因：`target` 的时间平均 = 6.5 mm ≈ 站姿 5.7 mm

`joy_foot_rhythm` 是

```
target(t) = 0.5mm + 24mm · relu(sin p)²        （每足，交替）
r         = ∏_feet exp(−((actual − target)/σ)²)
```

`relu(sin)²` 的时间平均是 **1/4**，所以

**`target` 的时间平均 = 0.5 + 24×0.25 = 6.5 mm**，而实测站姿脚高 **5.7 mm**。

**站姿几乎正好落在 target 的均值上。** 这就是为什么站桩能拿分，也是为什么调 σ 没用：  
σ 只改变容差宽度，不改变「站姿 ≈ 均值」这个几何事实。

`tools/probe_joy_peak_payoff.py` 的离线周期均值（权重 12）：

| 策略            | σ=9   | **σ=18（在跑那版）** | 峰值高斯 24mm | 峰值线性 20mm |
| ------------- | ----- | -------------- | --------- | --------- |
| 静止站桩          | 4.19  | **8.19**       | 0.00      | 3.42      |
| **压脚到 1 mm**  | 4.75  | **7.53**       | 0.00      | **0.60**  |
| 高频小抖 5°/25 Hz | 4.14  | 8.13           | 0.02      | 4.59      |
| 正确抬脚 60%      | 9.26  | 11.19          | 0.01      | 8.00      |
| 完美跟随          | 12.00 | 12.00          | 0.01      | 9.46      |


三件事一眼可见：

1. **σ=18 让站桩白拿 8.19 分（68%）**，抬脚的全部收益只剩 3.81 分。σ=9 时站桩 4.19，  
   收益 7.81 分。**σ 加大不只是「梯度变大」，它把白送的分同时放大了** ——  
   净激励从 7.40 分掉到 4.61 分（−38%）。§14.3 的推理只算了梯度、没算基线。
2. **σ=18 下「压脚」（7.53）比「站桩」（8.19）只低 0.66，而正确抬脚要付平衡代价。**  
   策略实测脚高 5.33 < 站姿 5.7 mm，正是学成了「往下压」。
3. **「高频小抖」（8.13）≈「站桩」（8.19）**，所以「抖动刷分」假说不成立 ——  
   但 8hz 超标（0.01133）另有来源，见 15.5。

### 15.4 上游的 trio 不是思路错，是**触发条件**错

`microduck_joy_env_cfg.py:36` 把上游的 `air_time` / `foot_clearance` /  
`foot_swing_height` 全部 `pop` 掉了。查上游源码：

```python
# microduck_velocity_env_cfg.py
cfg.rewards["foot_clearance"].params["command_threshold"] = 0.01
cfg.rewards["foot_swing_height"].params["command_threshold"] = 0.01
cfg.rewards["foot_swing_height"].params["target_height"] = 0.02   # ← 20 mm
```

**这三项都以 `command_threshold`（速度指令）为门控**，而 joy 任务把  
`lin_vel_x/y`、`ang_vel_z` 全置零 → 恒不触发 → 上次照搬时 `joy_air_time = 0.0000`。

所以「删 `joy_foot_rhythm` 换 trio」是把任务删掉，&#x4F46;**「trio 思路」本身没错**。  
正确做法：**保留思路，把触发条件从速度指令换成相位钟**（joy 任务本来就有）。

顺带：官方 `target_height = 0.02` = **20 mm**，与 audit 的 18.46 / 20.03 完全吻合。  
之前我们一直用 24 mm，比官方高 20%。

> ⚠️ **2026-10-24 更正（§26.3）**："audit 的 18.46 / 20.03" 这个出处**不成立** ——  
> `audit_smooth300.json` 里没有 18–21 mm 的脚高字段，那对数字最像是从 `t`（秒）/`yaw`（弧度）  
> 读出来的。Duckverse 会抬脚的可用证据是 `out/probe_joy_official.json`：16.36 / 17.34 mm，**0.2 ms 工厂**。

### 15.5 两个 FAIL 很可能同源

| 指标                     | 上游 audit  | 我们 sig018        |
| ---------------------- | --------- | ---------------- |
| `target_rate_rms`      | **2.515** | 1.255            |
| `pose_power_above_8hz` | 0.000296  | **0.01133**（38×） |

上游是**低频大幅**（指令速率高 2 倍、8hz 能量低 38 倍），我们是**高频小幅**。  
`probe_joint_tracking` 实测腿的目标幅度：

| 关节               | `tgt_rng` | `pos_rng` | ratio | lag    |
| ---------------- | --------- | --------- | ----- | ------ |
| `left_knee`      | 27.1°     | 22.9°     | 0.84  | 120 ms |
| `left_hip_pitch` | 43.9°     | 31.1°     | 0.71  | 120 ms |
| `left_hip_roll`  | 25.8°     | 19.9°     | 0.77  | 100 ms |
| `left_ankle`     | 33.9°     | 15.9°     | 0.47  | 100 ms |

`ratio 0.84` 且 `R2@lag 0.88` = **能跟动，是策略自己只发了 27° 的指令**。  
27° 峰峰 ≈ ±0.24 rad，正是 FK 表上 5.3 mm 对应的量。

### 15.6 改法：摆动窗口内的**运行峰值** + **线性** payoff @ 20 mm

`tools/patch_joy_peak_linear.py`：

```
r = clamp(peak_in_swing_window / 0.020, 0, 1)     只评当前摆动的那只脚
```

两个实现细节（都踩过）：

- **不能 `prod(-1)`**。两足交替，任一时刻一只摆动、一只站在 5.7 mm（=0.285 of  
  target）。乘积永远把摆动足的得分乘 0.285，把 perfect-vs-stance 从 0.715 压到 0.204。  
  只评窗口内那只脚（`relu(+s)²` 与 `relu(−s)²` 互斥，分母恒为 1，已断言）。
- **`target_height` 从 24 mm 改 20 mm**，对齐官方。

为什么选峰值线性而不是「窗口内高斯」：两者对比度接近（6.04 vs 6.15），但窗口高斯的  
站姿基线 5.85（49%），峰值线性只有 3.42（28.5%）；且峰值语义是「窗口内达到过就算」，  
对轨迹形状不敏感，天然不奖励瞬时抖动 —— 正对 8hz 超标。

`joy_foot_peak` 上次死掉（第 30–200 轮恒 0.0000）的原因这次也查清了：那版是  
**24 mm 高斯 × 两足相乘**，在 h=5.7 mm 处付 `0.011 × 0.011 = 1.2e-4`，梯度  
1.7e-6 /mm，与零无法区分。新版同一点付 **0.285**，梯度 **0.050 /mm**（恒定、不随高度  
衰减），是 σ=18 高斯梯度（0.0402 /mm）的 1.24 倍。

### 15.7 训练前先埋了物理量监控

奖励里直接记三个 TensorBoard 量，不必等 600 轮验收：

```
Metrics/joy_peak_height_max      全部 env×足 的最大 peak
Metrics/joy_peak_swing_p50       摆动期 peak 的中位数  ← 就是抬脚高度
Metrics/joy_peak_swing_min       摆动期 peak 最小值
```

smoke（64 env × 5 iter，随机策略）读出 `p50 = 4.0 mm`、`max = 29.7 mm`，量纲合理。  
若 200 轮时 p50 仍停在 4–6 mm，说明这条判据也没用，**不必再花 40 分钟**。

### 15.8 仍未做

- 齿隙 ±1°（官方 `passive_*_backlash` hinge），我们完全没有
- 延迟按毫秒校正：官方 `dt=0.005` + `decimation=4` = 50 Hz，延迟 3–6 步 = 15–30 ms；  
  我们 BAM `dt=0.002` 同样的步数只有 6–12 ms
- `foot_support` 奖励：上游未发布（GitHub 全树 1059 文件无 `world.py` / `parkour/`）

## 16. 定位到「局部最优」：策略会主动抵消抬脚（2026-10-24 17:10）

### 16.1 `peaklin`（窗口峰值 + 线性 20 mm）的结果：仍 5.33 mm，但 8hz 转 PASS

`joy_peaklin_2048x200`（2048 env × 200 iter，13 min 14 s）：

| gate                         | sig018（600 轮）    | peaklin（200 轮）   |
| ---------------------------- | ---------------- | ---------------- |
| `feet_peak_m`                | 0.00533          | **0.00533**      |
| `pose_power_above_8hz_ratio` | 0.01133 **FAIL** | **0.00831 PASS** |
| `target_rate_rms`            | 1.255            | 0.965            |
| `min_upright`                | 0.9967           | 0.9967           |
| `joy_feet`（训练日志满分 12）        | **8.5**          | **1.30**         |

两件事：

1. **8hz 真的降下来了**（0.01133 → 0.00831），因为 `target_rate_rms` 从 1.255 降到  
   0.965 —— 指令更平滑。§15.5「低频大幅」的方向对了一半：新判据确实抑制了瞬时抖动。
2. **但 `feet_peak` 一字不差**。奖励从 8.5 分掉到 1.30 分，物理量纹丝不动。

`feet_peak` 的 5.33 并不是「精确锁定」—— 它是 `min(median_left, median_right)`，  
sig018 的右足 5.53 / 左足 5.33，peaklin 的左足 5.47 / 右足 5.33，**两次都是右脚落在  
5.33**，是巧合而非机制。但量级完全一致这件事本身就有信息量。

### 16.2 新埋的 DC 监控推翻了「站姿 5.7 mm」这个前提

新增 `foot_mean_z_m`，peaklin 实测 **0.00346 m**。

**站姿脚高是 3.46 mm，不是我一直在用的 5.7 mm。** 5.7 是早期在 `play` cfg、4 个 env 上  
量的，而训练 cfg 的 `reset_base` z 范围是 `(0.12, 0.125)`，条件不同。

这个更正的真实后果：**§15.3 里「站桩已经落在 target 时间均值 6.5 mm 上」的机制描述  
不成立**（3.46 而不是 5.7）。但**结论方向没变**，因为 `feet_peak` 本身只有 5.33 mm，  
而 `foot_ac_rms` 只有 1.46 mm —— 脚在整个 episode 里就几乎没有离开过地面。  
所谓「站桩白送」的量级需要重算，但「脚不动」是直接测出来的，不依赖那个前提。

教训：**跨 cfg 的测量值不能直接搬。** 5.7 mm 那个数在 §9–§15 里被引用了五轮，  
每次都拿它算「白送多少分」，全都偏了一倍。

### 16.3 开环探针：全部摔倒，数据不可用（探针本身设计错了）

`tools/probe_openloop_lift.py` 直接给关节阶跃，测脚高：

| case              | peak L   | peak R   | upright   |
| ----------------- | -------- | -------- | --------- |
| `knee +0.60`      | 5.17 mm  | 16.69 mm | **0.521** |
| `hip_pitch +0.85` | 28.41 mm | 8.15 mm  | **0.702** |
| `hip_roll +0.35`  | 10.20 mm | 14.78 mm | **0.523** |

`upright` 全部 0.42–0.71，远低于 0.9。**开环抬一只脚而没有反馈，机器人直接歪倒，  
脚高读数被躯干旋转污染**（`knee +0.60` 那行右脚 16.69 mm 就是躯干翻过去把右脚翘起来）。

这个探针回答错了问题：它问「关节能不能动那么远」（FK 早就说 115 mm 可达），  
而不是「策略能不能抬脚还不倒」。**结论作废，不要再引用它的数字。**

### 16.4 闭环探针（决定性的那张表）

`tools/probe_policy_bias_lift.py`：加载策略正常跑，只给左膝 action 加常值偏置。  
策略仍看到状态、仍努力平衡，所以 `upright` 测的是**控制器的余量**，不是「没有余量」。

```
 knee bias  foot mean  foot peak  right foot  upright med  upright min   fell
      0.00     2.55mm     5.94mm      1.39mm        1.000        0.996  False
      0.10     2.34mm     6.11mm      0.92mm        1.000        0.994  False
      0.20     2.23mm    38.85mm      0.87mm        1.000        0.350   True
      0.30     2.25mm    38.90mm      0.89mm        0.999        0.350   True
      0.40     2.13mm    38.73mm      0.69mm        0.999        0.349   True
      0.50     2.46mm    37.93mm      0.81mm        0.998        0.350   True
      0.60     3.53mm    37.41mm      2.42mm        0.997        0.346   True
```

（`38.85 mm` 是摔倒瞬间的读数，不是抬脚 —— `upright min = 0.350` 是倾斜 69°，  
`fell = True` 是 episode 被终止。）

两个事实，合起来解释掉所有失败：

1. **0.10 rad 膝偏置只让脚涨 0.17 mm**（FK 说该涨 ~2.4 mm）。策略在**主动抵消**这个  
   抬脚 —— 它已经学到「脚必须保持低位」，并对任何扰动做反向修正。
2. **0.20 rad 就直接摔**（倾斜 69°、episode 终止）。当前站姿的平衡余量≈0。

所以卡点既不是 plant 也不是奖励形状，是**局部最优**：「站着不动」是探索能到达的唯一  
零风险策略。24 mm 抬脚需要 0.28 rad 的多关节协调（§15.2），而 `init_std = 0.12` 的  
动作噪声采样不到；任何部分尝试都会先把躯干弄翻，在拿到分之前就被终止。

**这解释了为什么五个奖励形状（点式 σ9 / σ18、峰值高斯 24 mm、官方 trio、峰值线性  
20 mm）全部落在 5.3–5.7 mm：它们要求的是同一个够不到的台阶。改一个够不到的目标的  
*形状*，不能让它变得够得到。**

另注：探针第一版有个 bug —— `site_pos_w[:, :, 2]` 取的是全部 7 个 site，列 0 是 `imu`  
（约 104 mm），读出来像「左脚在 104 mm」，而 `upright` 全 1.000 让这个荒谬值看着像  
正常结果。必须显式 `site_pos_w[:, foot_cfg.site_ids, 2]`。

### 16.5 改法：抬脚高度 curriculum（7 mm → 20 mm）

`tools/patch_joy_peak_curriculum.py`，只改目标高度这一件事：

| 迭代              | 0    | 80     | 160     | 240   | 320+      |
| --------------- | ---- | ------ | ------- | ----- | --------- |
| `target_height` | 7 mm | 9.5 mm | 12.5 mm | 16 mm | **20 mm** |

设计依据：

- **起点 7 mm 只比策略现在能做到的 5.94 mm 高一点**，第一阶段「站着几乎就能满足」——  
  梯度从第 0 步就存在，且指向一个**可平衡**的小幅动作。
- 每级 +27%，是「已经学会平衡上一级」的策略能吃下的增量。
- 终点 20 mm = 上游 `target_height = 0.02`，与 audit PASS 值（18.46 / 20.03）一致。  
  （⚠️ 2026-10-24 更正：那对数字在 audit json 里查不到，见 §26.3；只保留"上游 target=0.02"这一点。）
- 线性 payoff 保留，`clamp(peak/target, 0, 1)`，梯度 `1/target`。**target 是会动的，  
  所以早期梯度是 1/7mm = 0.143 /mm，是 σ=18 高斯（0.0402）的 3.6 倍，且不随高度衰减。**
- `24 = num_steps_per_env`，与既有 `action_rate_weight` 的 `150*24` 同一约定。

配套改动：

- `eval_joy_in_sim.py` 显式传 `target_height=0.020` —— 验收是一个固定契约，报告的  
  数字不能随 curriculum 阶段漂移。
- 日志加 `Metrics/joy_peak_target_m`，这样任何一轮都能对上它当时所处的阶段。

### 16.6 这一轮的纪律账

- 跨 cfg 搬测量值（5.7 mm）错了，**连累五轮的量级估算**。
- 开环探针设计错了（无反馈），产出的是垃圾数据 —— 但**产出「全是垃圾」这件事本身**  
  揭示了「抬脚必然破坏平衡」，算是有价值的失败。
- 闭环探针第一版有 site 索引 bug，读数荒谬但 `upright≈1.0` 让它看起来合理。  
  **又一次：静默 bug 的指纹是「输出落在看起来合理的区间」**，`104 mm 的左脚`之所以被  
  发现，是因为它和 `2.53 mm 的右脚` 摆在同一行。

## 17. 第七版（高度 curriculum）600 轮：左腿学会了，右腿没有（2026-10-24 17:50）

### 17.1 第一次贴近阈值，但形状和预期完全不同

| gate                   | sig018       | peaklin 200 | **curric 400** | **curric 599** |
| ---------------------- | ------------ | ----------- | -------------- | -------------- |
| `feet_peak_left_m`     | 0.00533      | 0.00547     | **0.02448**    | **0.02389**    |
| `feet_peak_right_m`    | 0.00553      | 0.00533     | **0.00580**    | **0.00725**    |
| `feet_peak_m`（=min）    | 0.00533      | 0.00533     | 0.00579        | **0.00725**    |
| `knee_ac_rms_rad`      | 0.063        | —           | **0.2967**     | **0.3474**     |
| `pose_power_above_8hz` | 0.01133 FAIL | 0.00831     | 0.00641        | 0.00988        |
| `target_rate_rms`      | 1.255        | 0.965       | 2.066          | 2.284          |
| `min_upright`          | 0.9967       | 0.9967      | 0.9966         | 0.9975         |
| `fell_frac`            | 0            | 0           | 0              | 0              |

gate 是 `feet_peak_m > 0.008`，现在 **0.00725，差 9.4%**。七版以来第一次进入这个量级  
（此前全部 0.0053–0.0058）。膝的摆动幅度涨了 **5.5 倍**（0.063 → 0.347 rad），  
`target_rate_rms` 从 1.255 涨到 2.284（上游 audit 是 2.515，**已接近**）。

右腿在 400→600 轮从 5.80 涨到 7.25 mm，但 `joy_feet` 只从 6.67 涨到 6.77  
（12 分制，约 +0.17 mm / 200 轮）→ **平台，不是慢速爬升**。

### 17.2 关键：这不是「两腿都抬不高」，是**单腿踏步**

只看 `min(left, right)` 会误读成「抬脚幅度不足」。`tools/probe_phase_profile.py`  
按 gait phase 分 24 个 bin 测脚高（`model_400`，64 env × 6 s）：

```
phase   left     right
 0.02  20.09 mm   0.45 mm      left foot highest at the START of its own window
 0.10  17.70      0.38
 0.27   8.18      1.94
 0.52   4.53      4.05        both low at the half-cycle boundary
 0.77   5.95      2.61
 0.98  18.47      0.56

left   mean 9.48 mm  sd 6.54 mm  r(sin p) = +0.301
right  mean 2.26 mm  sd 1.84 mm  r(sin p) = -0.220
```

左腿是一条完整的半正弦：在自己摆动窗（`sin p > 0`）里升到 20 mm、落地到 4.5 mm。  
右腿在**自己的摆动窗**（`sin p < 0`，phase 0.5–1.0）里反而**最低（0.45–1.0 mm）**，  
且相位相关性是**负的** —— 该抬的时候它在压。

**所以真实行为是：左脚周期性抬起，右脚被压到 0.45 mm 全程承重。策略学成了  
单腿踏步（one-leg march），不是交替踏踏。**


这重写了此前所有失败的解释。五个奖励形状 + curriculum 全部落在 `min ≈ 5.3–5.8 mm`，  
我一直读成「两脚都抬不高，所以是奖励/物理上限问题」。实际绑定约束**从来不是抬脚高度**，  
而是**把支撑交出去**：抬第二只脚要求第一只脚承重，而策略先学会了用右腿当支柱就不再撒手。  
这是协调问题，比「抬多高」难一级 —— 也解释了为什么 FK（24 mm 只需 `max|dq| = 0.28 rad`）  
和闭环偏置探针（0.2 rad 就翻）会给出看似矛盾的结论：**单腿状态下当然翻，因为它没打算换腿。**

### 17.3 参考资料（用户要求先查，这次的三条一手对照）

| 来源                                                | 内容                                                                                                                                                                                                | 对我们的意义                                                                                                                                   |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Booster Gym** arXiv 2506.15132, Table I         | `Gait Cycle 2` 维 `(cos 2πft, sin 2πft)` **同时进 actor 和 critic**；站立步态把 cycle 置零，站立/行走共用一个策略；明写「用脚-地面**高度差**而非接触力判断抬腿」；`Feet swing` 奖励 = `1_feet swing · 1_swing period`，weight **3.0**（指示函数，不是高度函数） | **我们的观测里没有这对时钟**（见 17.5）                                                                                                                 |
| **unitree_rl_mjlab / thanhndv212/walka_rl_mjlab** | gait-clock phase observation 驱动 `feet_gait`(+0.5, "match a fixed alternating stance/swing clock") 和 `stand_still`(−1.0, "hold default pose when no command")                                      | `stand_still` 的门控是「no command」，joy 速度指令恒 0 → **若继承它就会一直惩罚动作**。需确认我们没继承（`make_microduck_joy_env_cfg` 的 pop 列表未含 `stand_still`，但基础模板也没有此项） |
| **mjlab 官方**（deepwiki, oxkitsune/mjlab 6.3）       | `upright std=0.447`；`foot_clearance` / `foot_swing_height` 均 `target_height=0.1` 且 walking-only                                                                                                   | 我们 `upright` 是 `std²=0.05 → 0.2236`（陡 4 倍）。但这是 Microduck 上游自己改的（ball_kick 也是 `sqrt(0.05)`），不擅自改                                          |

另有两篇综述（vnrobo「Reward Engineering for Bipedal Walking」、ImChong 运控笔记）  
点名同一个模式：**「只奖励直立 → 站着一动不动」是 reward hacking 头号案例**；  
摆动相抬脚权重典型 0.1–0.5，**过强会变成高抬腿正步**。

### 17.4 顺带修正一个统计口径错误

`Metrics/joy_peak_swing_p50` 是 `self.peak[in_swing]` 在**所有 step** 上的中位数。  
但每个窗口刚开时 `peak = 当前脚高`（约 3 mm），只有窗口最后几帧才到达真峰值。  
所以 p50 落在**爬升段**，系统性低估。

实测：`joy_feet` 6.67/12 → raw 0.556 → 均值等效 11.1 mm，而日志 p50 只有 6.3 mm。  
**这两个数不是同一个统计量，也都不是 gate 报的那个**（gate 是 per-foot 窗口峰值跨 env 的  
中位数，然后取两脚较差）。

我在 §16 里拿 p50 = 6.3 mm 去对照 `joy_feet` 均值 11.1 mm、并据此判断「策略只抬 6 mm」，  
那个推断的**结论碰巧对**（右脚确实只有 7 mm），但**依据是错的**。  
`tools/probe_peak_spread.py` 改用「窗口末峰值」统计，把「env 间差异」和「窗口间波动」  
分开，才是能对上的量。

### 17.5 结构性不对称：每次 episode 都是左腿先摆

`joy_phase(env) = 2π·1.15·episode_length_buf·step_dt`，而 `episode_length_buf`  
在 reset 时归零。实测 reset 后：

```
episode_length_buf: [0,0,0,0,0,0,0,0]
phase p:            [0.0, ...]
sin(p):             [0.0, ...]   -> rises through positive -> LEFT (site 0) swings first
```

**2048 个 env 全部从 `p=0` 起步，没有一个是右腿先摆的。** 叠加 `ramp_s = 0.8`  
（前 0.8 s ≈ 0.92 个周期的奖励被线性缩放），左腿在每次 episode 开头都占一个  
「先发窗口」。这是**系统性偏差，不是随机性**，可以解释为什么是左腿而不是右腿学会。

部署侧同理：真机每次起播都从相位 0 开始 → 先抬左脚。这本身不算错，但训练时若  
随机化起始相位，策略会学到「任意相位起步」，更鲁棒，也不会偏袒某一条腿。

### 17.6 第八版：只加相位观测（已应用，正在训 `joy_clock_2048x600`）

`tools/patch_joy_gait_clock.py`，唯一改动是观测 +2 维：

```python
def joy_gait_clock(env):
    p = joy_phase(env)
    return torch.stack((torch.sin(p), torch.cos(p)), dim=-1)
```

依据与理由：

1. 相位目前只是**隐式**存在于跟踪指令里：`head_command = (..., .24 sin p, .12 sin p)`、  
   `body_command = (..., .006(1-cos 2p), .07 sin p, ...)`。**有 `sin p`，没有可用 `cos p`**  
   （`1-cos 2p` 周期是 `p/2`，`p` 与 `p+π` 通过它不可区分）→ 策略分不清  
   「正在抬向摆动」和「正在落回」，而这正是两条腿分工的那半个周期。
2. 用的 `joy_phase` 与奖励**同一个函数**，观测与评分窗口不可能漂移。
3. Booster Gym 的 Table I 就是这个形式；unitree_rl_mjlab 同。
4. **奖励、目标高度、curriculum 一律不动**，保持单变量 —— 第六版已经证明这个 payoff  
   能把第一只脚推到 24 mm，此时再改奖励会污染归因。

代价：actor 输入 +2 → 必须从零重训（`AGENTS.md` 对任何奖励/观测改动本来就这么要求）；  
部署侧 ONNX 输入宽度同步变化。

### 17.7 若第八版无效，第九版是**相位偏移随机化**

`joy_clock` 解决「看不见相位」，但解决不了「每次都是左腿先摆」。第九版做法：

```python
def joy_phase_offset(env):        # per-env 常量, 在 buf==0 时重采样
    ...  torch.rand(n) * 2*pi
def joy_phase(env, frequency=1.15):
    return 2*pi*frequency*env.episode_length_buf*env.step_dt + joy_phase_offset(env)
```

同时把 `joy_foot_peak.__call__` 里自己算的 `t = episode_length_buf * step_dt`  
换成 `joy_phase(env)`，这样 reward 与 obs 共用同一个带偏移的钟。

先跑第八版是因为它的依据更硬（任务可辨识性 vs 探索公平性）；  
两个都失败则说明问题在「支撑交接」这个动作本身，那时该上的是参考步态  
（Booster Gym 的 `Feet swing = 1_swing_period` 指示函数 + 显式 gait cycle 观测）  
而不是继续微调 payoff。

## 18. 第九版：镜像数据增强（2026-10-24 18:00–18:40）

### 18.1 三个自己「推」的点，两个查到了出处

| 我推的                            | 出处                                                                                                                                                             | 结论                          |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| 镜像时相位钟应移半个周期                   | **AAAI 2026「Coordinated Humanoid Robot Locomotion with Symmetry Equivariant RL Policy」**：`Phase input Φ: (Φsin,Φcos)→(−Φsin,−Φcos), a half-period phase shift` | **推导正确**，不用改                |
| 该用 augmentation 还是 mirror loss | **rsl_rl 文档**：augmentation = 扩充 mini-batch（样本效率，高维运动任务首选）；mirror loss = 轻量正则，专防「limps or asymmetric biases」                                                    | 选 **augmentation 单开**，保持单变量 |
| 镜像会不会破坏 critic                 | **PhoneBot**：`The critic is trained only on real trajectories because its privileged state contains world-frame quantities that are not directly mirrored`     | 我们的实现恰好如此（critic 段原样复制）     |

顺带确认 PhoneBot 的镜像定义原文：`swaps left and right legs **and gait phases**, reflects IMU-frame state, negates the relevant angular quantities, and applies the same transformation to the action and policy mean`。

### 18.2 坑一：镜像表是 61 维硬编码，而我们现在是 63 维

`mjlab_microduck/tasks/symmetry.py` 的 `_OBS_PERM` 恰好 61 个条目。加了 `gait_clock`（+2 维）后：

```python
actor_sym = actor_orig[:, obs_perm] * obs_sign   # 高级索引 → 静默只取 61 列
```

**高级索引不会报错，它只是丢掉最后两维。** 形状错误会飘到很远的 actor 前向才炸，或者干脆把相位那两维抹成别的量。已在函数入口加宽度守卫：

```python
if actor_orig.shape[-1] != len(_OBS_PERM):
    raise ValueError(f"actor obs is {..}-D but _OBS_PERM has {len(_OBS_PERM)} entries")
```

实测布局（`observation_manager._group_obs_term_{names,dim}` 读出，与文档逐字一致）：

```
[0:3] base_ang_vel    [48:51] command
[3:6] projected_gravity [51:55] head_command
[6:20] joint_pos      [55:61] body_command
[20:34] joint_vel     [61:63] gait_clock   ← 新增
[34:48] actions
```

### 18.3 坑二：`symmetry_cfg` 是 `.algorithm` 的字段，挂顶层静默无效

第一版补丁写的是

```python
MicroduckJoySmoothPdRlCfg.symmetry_cfg = {...}       # 错
```

dataclass **接受**这个属性赋值，跑起来也不报错，但 PPO 只读 `cfg.algorithm.symmetry_cfg`，于是永远是 `None`——训练会「正常」跑完，只是完全没增强。改成：

```python
MicroduckJoySmoothPdRlCfg.algorithm.symmetry_cfg = {...}   # 对
```

验证方式是开关双向检查（不是「不报错就算过」）：

```
MICRODUCK_JOY_SYMMETRY=1 → {'use_data_augmentation': True, ...}
MICRODUCK_JOY_SYMMETRY=0 → None
```

**这已是本项目的第 N 次同类错误：属性写在能被接受但没人读的地方。**  
判据只能是「我改的那个量，下游有没有真的读到」，不能是「没报错」。

### 18.4 三重校验 + 负对照（`tools/probe_symmetry_mirror.py`）

| 检查       | 内容                                              | 结果                           |
| -------- | ----------------------------------------------- | ---------------------------- |
| 1 对合性    | `perm(perm(x)) == x`，`sign²==1`                 | 63 维通过                       |
| 2 相位钟    | 槽位不动 `[61,62]`，符号 `[-1,-1]`                     | 通过                           |
| 2b 三块一致  | joint_pos / joint_vel / actions 共用同一 L↔R 模式     | 通过                           |
| 4 形状     | `B → 2B`，原始半段逐位不变                               | 通过                           |
| **3 物理** | 按表镜像关节角 → MuJoCo FK → **两脚位置必须互换**（z、x 互换，y 反号） | 200 组随机姿态，**最大误差 0.0000 mm** |

**负对照（把符号故意改错，检查必须变红）：**

| 改错                   | 检出误差      |
| -------------------- | --------- |
| `left_knee` 不取反      | 72.71 mm  |
| `right_knee` 不取反     | 75.83 mm  |
| `left_hip_roll` 不取反  | 82.54 mm  |
| `left_hip_pitch` 不取反 | 128.43 mm |

四个全被抓住，说明这个检查是活的，不是「只见过绿色的断言」。

### 18.5 顺带验掉的一个假设：动作通道顺序

镜像表对 obs 和 action 复用同一个 `_JOINT_PERM`，前提是两者同序。`action cfg` 写的是  
`actuator_names=('.*',)` 且 `preserve_order=False`，所以不能靠猜。

- 动作项的 `_target_names` = `['left_hip_yaw', ..., 'left_ankle', 'neck_pitch', ..., 'right_ankle']`，与 `robot.joint_names` **逐字同序**；`_target_ids` = 0..13。
- 全 14 通道注入 +0.5 后的 `_joy_target` 差分：**14/14 只动对应关节**。

中间有个假警报值得记：单步测试时通道 4/5/6/11 的差分是 `0.000`，看着像「这四个通道不映射」。  
实际是 `JoySmoothPositionAction` 的首步斜坡（`alpha=0.25`、`max_step=0.08`）还没把目标推起来；  
跑 10 步后四个通道分别只动 `left_ankle +0.352` / `neck_pitch +0.398` / `right_hip_pitch +0.351`（各自唯一）。  
**又一次：「看起来像 bug」的读数其实是测量时机错了。**

### 18.6 落地

- `tools/patch_joy_symmetry.py`：改写两个位置的 `symmetry.py`（`.venv-mjlab` 与 `.upstream`），  
  并在 joy cfg 里加 `MICRODUCK_JOY_SYMMETRY` 开关（默认关，不改变任何既有 run 的行为）。
- `tools/apply_joy_patch.py` 的同步清单加入 `tasks/symmetry.py` —— 否则下次 `apply_joy_patch`  
  会把 61 维表推回去，而 augmentation 会**静默截断**而不是报错。
- 奖励、目标高度、curriculum **一律不动**，与 `joy_clock` 保持单变量对照。

## 19. 第八版（相位观测）600 轮：8hz 修好了，左右分工一点没动（2026-10-24 18:40）

### 19.1 验收

| gate                            | curric 599 | **clock 599** | 变化              |
| ------------------------------- | ---------- | ------------- | --------------- |
| `feet_peak_left_m`              | 0.02389    | **0.02213**   | −7%             |
| `feet_peak_right_m`             | 0.00725    | **0.00563**   | **−22%**        |
| `feet_peak_m`（=min，gate >0.008） | 0.00725    | **0.00563**   | 更差              |
| `8hz_ratio`（gate <0.01）         | 0.00988    | **0.00347**   | **−65%，稳 PASS** |
| `target_rate_rms`               | 2.284      | 2.012         | 略降              |
| `knee_ac_rms_rad`               | 0.347      | 0.170         | 腰斩              |
| `min_upright` / `fell_frac`     | 0.9975 / 0 | 0.9927 / 0    | 未变差             |
| `joy_peak_height_p50_m`         | —          | 0.00477       | —               |


`8hz_gate_channel = foot` 且 `8hz_foot_interpretable = True`（`foot_ac_rms = 7.09 mm`，  
已越过 2 mm 的可解释阈值），所以这次的 0.00347 **是一条真读数**，不再是「脚不动」的影子。

### 19.2 结论：相位可见 ≠ 会换支撑腿

加 2 维 `(sin p, cos p)` 让策略能区分「正在抬」和「正在落」，动作确实变平滑了  
（8hz −65%、膝摆幅腰斩）。**但左脚 22.1 mm / 右脚 5.6 mm 的单腿踏步形态完整保留**，  
甚至比 curric 版右腿更差一点。

这否掉了「策略看不见相位所以不知道抬哪只脚」这个假设，同时**印证了 PhoneBot 的判断**：

> 该偏差是 `an avoidable bias`，修法是镜像增强，不是让策略更懂相位。

原因是结构性的：**每个 episode 都从相位 0 开始**（`episode_length_buf` reset 归零），  
2048 个 env 里没有一个「右腿先摆」的样本。可见相位只让策略更精确地执行它已经学到的  
那个单腿策略，样本分布里根本没有另一半。

### 19.3 第九版已启动（`joy_sym_2048x600`）

`MICRODUCK_JOY_SYMMETRY=1`，只开数据增强（`use_mirror_loss: False`），奖励/目标/curriculum 不动。  
存档 `params/agent.yaml` 已核：

```yaml
symmetry_cfg:
  use_data_augmentation: true
  use_mirror_loss: false
  mirror_loss_coeff: 0.5
  data_augmentation_func: mjlab_microduck.tasks.symmetry.microduck_vel_symmetry
```

对照 `joy_clock` 的同一字段是 `null`，单变量成立。前 2 轮 `joy_feet` 0.089 → 0.424，增强路径无异常。

**判定先看一个数**：第 200 轮左右的 `feet_peak_right_m`（或 `probe_phase_profile` 里右腿在  
自己摆动窗的高度）。若右腿从 5.6 mm 开始跟着涨，说明镜像生效；若仍是 5–6 mm 而左腿也掉下来，  
说明增强把两侧一起平均成了「都不抬」，那是另一种失败，要换 mirror loss 而不是继续等。

---

## 20. 等第九版时做的三件事（2026-10-24 18:45–19:00）

训练在跑，GPU 不能抢，于是只做读代码 / 读文献 / CPU 侧负对照。

### 20.1 `Mean symmetry loss` 是个会误导人的数：它不参与梯度

第九版日志里第一眼看到的是这一行：

```
Learning iteration 73/600
  Mean symmetry loss: 0.0486
```

而 `agent.yaml` 明明写着 `use_mirror_loss: false`。如果只按配置读，会以为「镜像损失没开，  
这个数不该存在 / 或者开了却没人发现」。查 `rsl_rl/algorithms/ppo.py`：

```python
# 315-346
if self.symmetry:
    if not self.symmetry["use_data_augmentation"]:
        batch.observations, _ = data_augmentation_func(...)   # 只在没做增强时才再镜一次
    mean_actions = self.actor(batch.observations.detach().clone())
    ...
    symmetry_loss = mse_loss(mean_actions[original_batch_size:],
                             actions_mean_symm.detach()[original_batch_size:])
    if self.symmetry["use_mirror_loss"]:
        loss += self.symmetry["mirror_loss_coeff"] * symmetry_loss
    else:
        symmetry_loss = symmetry_loss.detach()    # ← 这里：只观测，不进 loss
```

`use_data_augmentation=True` 时它照样算，只是 `detach()` 掉。所以它是个**免费的诊断量**，  
配置没问题。但「免费」不等于「无用」——它正好是一个**左右不对称的独立标量**，而且不依赖  
脚高探针、不依赖 checkpoints：

| 迭代  | `Loss/symmetry` |
| --- | --------------- |
| 1   | 0.023           |
| ~40 | 0.039           |
| ~90 | 0.057           |
| 119 | 0.115           |
| 217 | **0.291**       |

**从 0.023 涨到 0.291，涨了 12 倍。** 方向和我原本的期待（对称增强 → 该趋近 0）相反。  
MSE 0.29 在 14 维动作上折 RMS ≈ 0.54 rad —— 这不是数值噪声，是**策略在持续地变不对称**。  
这与 `probe_phase_profile.py` 量到的「左腿在自己窗内抬 20 mm、右腿被压到 0.45 mm」是同一件  
事的两种测法：**策略不是在逼近对称步态，是在逼近一个明确的单腿支撑解。**

（注意：这个数上升本身**不能判坏**。真正的判据仍是右腿脚高。它只能说明「镜像增强的对称压力  
没有赢过奖励」，而这一点对决定下一步很重要。）

### 20.2 反过来，`gait_clock` 的镜像处理经核查是对的

怀疑链是：`_OBS_PERM` 只是列置换，而 (sin p, cos p) 的正确镜像需要**符号翻转**（相移 π），  
若当普通通道置换，增强会教出「同一相位两条腿一起摆」。查 `tasks/symmetry.py` 的 `_OBS_SIGN`  
末两维：

```python
+ [-1.0, -1.0]   # gait_clock: (−sin p, −cos p) = 相移 +π
```

并且 `_OBS_PERM` 末两位是 `[61, 62]`（原地不动）。置换恒等 + 双符号翻转 = 纯相移 π，**正确**。  
所以 20.1 的 loss 上升不是实现 bug，是策略真的在分化左右。这一条排除掉，才敢往下找起点问题。

### 20.3 文献里早写好了这个失败模式的名字

Yu / Turk / Liu, *On Learning Symmetric Locomotion*（arXiv 1801.08093）：

> "**Symmetry can sometimes be harmful**, especially when the character begins from or otherwise  
> arrives at a **neutral pose** ... a **symmetric policy is incapable of escaping from a neutral  
> pose** since the action that it takes would also be symmetric ... a character that starts from  
> the T-pose will likely perform **some kind of hopping gait** ... **The breaking symmetry problem  
> is most severe when enforcing symmetry** through network architecture ... A simple workaround is  
> to **always start the character from a non-neutral position**."


LORM（PeerJ CS-927）在双足步态 RL 里给同一味药，并命名为 **RSI（random state  
initialisation)**：每个 episode 把环境初始化到「参考步态周期的随机相位」，这样策略同时见到  
早期和后期子任务，而不是学一个「串行、依赖起步相位」的策略。

### 20.4 我们恰好同时满足这三个条件

论文的三个前提，我们一个不差：

| 条件             | 我们的现状                                                                                                     |
| -------------- | --------------------------------------------------------------------------------------------------------- |
| 起点是对称的中性**姿态** | reset 到 HOME 站姿，左右完全对称                                                                                    |
| 起点是对称的中性**相位** | `joy_phase = 2π·1.15·episode_length_buf·dt`，reset 时 buf=0 → **2048 个 env 全部从 p=0 起步**，而且 p=0 正好是「左腿起摆」那一刻 |
| 施加对称约束         | 第九版 `use_data_augmentation=true`                                                                          |

这解释了此前几件原本孤立的事：

- **为什么第八版「把相位观测进去」没用**：策略在训练里几乎只见过「p 从 0 开始、左腿先摆」的  
  轨迹形状。给它 (sin p, cos p) 两维并不会凭空造出「右腿先摆」的样本 —— 相反 offset 恒 0 时，  
  sin/cos 与 episode 内的绝对时间是一一对应的，相当于又给了一个「计时器」。8hz 高频抖动  
  确实被压下去了（0.00988→0.00347，且 `foot_ac_rms=7.09 mm` 能解释这个读数，是真读数），  
  但左右分工没动。
- **为什么右膝 +0.10 rad 就摔、左膝 +0.10 不摔**：策略是在「左腿永远先动」的分布上拟合出来的，  
  右腿从来没有当过第一支撑腿，它的平衡能力自然没被训练到。
- **为什么六版奖励都卡在 5.3–5.7 mm**：奖励改的是「值多少分」，改不动「从哪个状态出发」。  
  起点固定 → 局部最优也固定。

### 20.5 第十版的后手已写好：`MICRODUCK_JOY_PHASE_RSI=1`

`tools/patch_joy_phase_rsi.py`：

- `joy_phase` 增加一个 per-env 常量 offset，**每次 reset 从 U[0, 2π) 重采样**；
- offset 挂在 env 实例上（`env._joy_gait_phase_offset`），不用模块全局 —— 同进程两个 env 不会  
  互相踩；
- 奖励项、`joy_head_command`、`joy_body_command`、`joy_gait_clock` 全都调 `joy_phase`，所以  
  **必然共用同一个被偏移的钟**，不存在观测与打分错相位的可能；
- 开关关闭时 **reset event 根本不注册**，`joy_phase` 走的是逐位相同的旧路径。

负对照 `tools/probe_phase_rsi.py`（纯 CPU，不占训练 GPU），5 项全 PASS：

```
[PASS] OFF: joy_phase bit-identical to pre-patch formula (t range 0.000..57.516 rad)
[PASS] ON: offset min 0.012 max 6.256 sd 1.803 (expect uniforms sd~1.814), unique 512/512
[PASS] ON: p(t=0) sd 1.814 rad, 93.2% of envs start >0.5 rad from the old p=0
[PASS] ON: partial reset left envs 16..511 untouched; the 16 reset envs changed
[PASS] shared clock: head_command moved 0.10296, gait_clock moved 0.79552
```

第 4 项是专门防一个静默 bug：如果每次**任一** env 终止都重采样全部 offset，钟就变成非马尔可夫  
噪声而不是「起步相位」，训练会莫名其妙不收敛。第 5 项防的是「观测用了偏移、奖励没用」。  
配置层也双向验过：`MICRODUCK_JOY_PHASE_RSI=0` 时 12 个 event，`=1` 时 13 个（多出的  
`initialize_joy_gait_phase_offset` 是 `mode='reset'`）。

**如实记一笔**：写这个负对照时我自己踩了一次同类语义差 —— 中途把 `env` 重新赋值成新实例，  
却还在读第一个实例的 `off` 去做「部分 reset 不污染其他 env」的比较，于是这条检查**红得毫无  
道理**（红的原因不是实现错了）。这类「检查本身写错」比「实现写错」更危险，因为它会诱导你去  
改一个本来正确的实现。

### 20.6 第十版怎么排，以及为什么不是现在就上

两个改动（对称增强、随机起步相位）**叠加和单上的效果必须分开**，否则第九版就算失败了也说  
不清是「增强没用」还是「增强被中性起点抵消了」。所以顺序是：

1. 等 `joy_sym_2048x600` 跑完（约 19:23），按 19.3 的判据验收右腿；
2. 若右腿起涨 → 保留增强，再单独评估要不要叠 RSI；
3. 若右腿不动、左腿同时下降 → 增强把两侧平均掉了，第十版 = **RSI 单独上**（关增强），  
   这是最干净的验证：「右腿不抬」到底是起点分布问题还是奖励问题；
4. 若 RSI 也不动 → 那问题就不在探索分布上，回到支撑手递（support hand-over）本身。

`AGENTS.md` 的规矩照旧：改观测/奖励必须从零重训，所以每一版都要 40 分钟，不能省。

### 20.7 一次自己制造的假警报：把第 73 轮的读数当成了当前值

中途看到日志里 `Metrics/joy_peak_target_m: 0.0070`，而当时已跑到第 233 轮。按  
`JOY_PEAK_TARGET_STAGES`（`0/80/160/240/320` 轮切换 7→9.5→12.5→16→20 mm）那时应该是  
**12.5 mm**，于是判断「课程卡在 7 mm 没切换」—— 如果成立，第九版其实是在第七版 1/3 的目标下  
训练，所有对照都作废。

查证路径（不猜）：

1. `common_step_counter` 在 `manager_based_rl_env.py:230` 置 0、`:424` 每次 `step()` `+= 1`，  
   全库没有第二处置 0 → 它是全局累计，不是 per-env episode 计数，语义没错；
2. 直接读 tfevents 里这条曲线的**全集**，而不是某一个点：

```
joy_sym_2048x600:    n=278 distinct=[0.007, 0.0095, 0.0125, 0.016]
joy_curric_2048x600: n=600 distinct=[0.007, 0.0095, 0.0125, 0.016, 0.020]
```

四档全在、顺序正确 → **课程完全正常**。那个 0.0070 是我第一次 `tail -c 3000` 看到第 73 轮  
日志时留下的印象，后来 `grep` 的模式里根本没包含 `joy_peak_target_m`，于是把一个**早已过时的  
读数**当成了当前状态。

两次同型错误的对照很有意思：

- 20.1 的 `Loss/symmetry`（0.023→0.291）是**读了全集**，所以能下结论「策略在分化左右」；
- 20.7 这次的 0.0070 是**读了单点**，所以得出了相反且错误的结论。

同一份日志，读法不同，结论相反。**判据要写成「这个量动没动、量级是多少」，而不是「这个数  
是多少」** —— 因为单点读数无法区分「恒定」和「我读到的是哪一刻」。

---

## 21. 第九版验收：镜像增强**完全生效**，把角色对调了 —— 然后卡在同一个地方

`joy_sym_2048x600` / `model_599`，600 轮 41 分 42 秒跑完（EXIT=0）。

### 21.1 两脚高低整个互换

| 读数（`eval_joy_in_sim.py`，64 env × 8 s） | 第七版 `joy_curric` | 第九版 `joy_sym`                                 |
| ------------------------------------- | ---------------- | --------------------------------------------- |
| `feet_peak_left_m`                    | **23.89 mm**     | **5.37 mm**                                   |
| `feet_peak_right_m`                   | 7.25 mm          | **23.46 mm**                                  |
| `feet_peak_m`（= min of two）           | 7.25（FAIL）       | 5.37（FAIL）                                    |
| `min_upright`                         | —                | 0.987 PASS                                    |
| `fell_frac`                           | —                | 3.1%                                          |
| `max_drift_m`                         | —                | 0.037 PASS                                    |
| `joy_foot_peak_mean`                  | —                | **0.529**                                     |
| `8hz_ratio_foot`                      | —                | 0.0142 FAIL（但 `8hz_foot_interpretable=False`） |

`probe_phase_profile` 的相位分箱（mm），右腿在自己窗口（phase 0.5–1.0）内：

```
  phase     left    right
   0.02     2.89     0.42      ← 左腿应该在摆，实际 2.89 mm 起、越走越低
   0.19     2.30     0.63
   0.35     0.90     1.35
   0.44     0.10     5.18      ← 右腿窗口开始
   0.65    -0.35    21.90      ← 峰值，超过 20 mm 目标
   0.90     0.97     5.58
   0.98     2.30     0.79
```

`left mean 0.96 mm r=+0.531` / `right mean 7.64 mm **r=−0.814**`。

右腿的相位锁定（|r|=0.814）**比第七版左腿（r=+0.301）强得多** —— 增强 + 相位观测确实让摆动腿  
跟时钟跟得更准了。它只是把「哪条腿当摆动腿」换了一侧。

### 21.2 为什么这不是「增强失败」，而是「增强对这一类解无效」

`joy_foot_peak_mean = 0.529` 这个数一算就通：

- `joy_foot_peak` 每步只评**正在摆动的那只脚**（`w = in_swing`，`denom = w.sum()` = 1）；
- 单腿踏步时，摆动脚在自己窗口拿满 1.0，站立脚在自己窗口拿 `5.37/20 ≈ 0.27`…… 实测平均  
  0.529 ≈ (1.0 + 0.05)/2，即站立脚那半个周期几乎拿 0 —— 与 phase 分箱里左腿 0.10–2.89 mm 一致；
- **交替步态应该拿 ~1.0。所以交替在奖励上值 2 倍，策略却选了 0.529 的那条。**

关键在于：**单腿踏步这个解本身是镜像自对称的。** 「左腿摆、右腿撑」的镜像是「右腿摆、左腿撑」，  
两者互为镜像，**所以它们在对称数据增强下都是不动点**。增强把这两端之间的等价性钉死了，但它  
永远不会凭空造出「两腿都摆」——因为那个解不是镜像对称的，它需要 L↔R **在时间上交替**，而  
镜像增强只覆盖空间对称。

回头看 `Loss/symmetry` 一路涨到 0.49，现在有了明确含义：**它就是「左摆」和「右摆」两个解之间  
的差异量**。策略越接近其中一端，这个数越大。它涨，恰恰说明增强在起作用（两端被拉平了），  
而不是没起作用。所以它不能当失败判据 —— 这条以后也不会再误读。

### 21.3 排除掉的一整条路

至此可以确定：**对称性这一类方法（augmentation / mirror loss / 对称网络）对本问题是无效的**，  
理由不是实现错，而是数学上：它保的是「空间左右等价」，而我们要的是「时间上交替」。  
继续在对称性上加码（换 `use_mirror_loss=True`、调 `mirror_loss_coeff`）不会改结果。

真正缺的是奖励里**没有任何一项要求两只脚都参与**：

```python
per_foot = clamp(self.peak / target_height, 0, 1)
w = in_swing                      # 每步只有一只脚为 True
denom = w.sum(-1).clamp(min=1)    # → 恒等于 1
out = (per_foot * w).sum(-1) / denom
```

摆动的脚拿满分、站着的脚那半步拿 0，两者互不相干。**站着不动是零风险的**，因为 `joy_feet`  
从不因为「这只脚整窗没抬」而扣分。这不是 bug，是奖励形状缺了一项。

### 21.4 第十版方向（待实现）

把评分从「当前摆动脚」改成「**两只脚各自上一个完整窗口的末峰值的最小值**」：

```
score = min(end_peak_left, end_peak_right) / target_height
```

- 两条腿都抬到 20 mm 才拿满；
- 单腿踏步会掉到 min(20, 5.4)/20 = 0.27，**比现在的 0.529 更差** → 有动力改；
- 不受「当前哪只脚在摆」影响，所以不会重蹈点式 `prod(-1)` 把摆动脚乘上 0.285 的覆辙  
  （那是按步评分才有的问题，按窗口末峰值没有）；
- 需要新增 per-foot 的 `end_peak` buffer，在窗口切换时锁存。

同一版再叠加 **RSI 随机起步相位**（`MICRODUCK_JOY_PHASE_RSI=1`，已实现并通过 5 项负对照），  
因为「所有 env 从 p=0 起步」的问题与「奖励不要求两脚参与」是两个独立缺陷，都该补。

---

## 22. 第十版：奖励改成「两脚窗口末峰值的 min」+ 修掉一个静默的时钟分叉

代码已落地（**未起训**）。`tools/patch_joy_pair_min.py` + `tools/probe_pair_min.py`。

### 22.1 缺的那一项，用实测轨迹量出来了

`probe_pair_min.py` 把 `out/probe_phase_sym.log` 的 24 点相位分箱表逐点插值，重建出  
model_599 的**真实**单腿踏步轨迹（不是"一条腿 20 mm、一条腿 3 mm"的玩具模型），喂给  
`joy_foot_peak`：

| 步态                 | 旧评分       | `pair_min` |
| ------------------ | --------- | ---------- |
| 交替（两脚各自窗内都到 20 mm） | 0.823     | **0.998**  |
| 单腿踏步（实测分箱表）        | **0.528** | **0.144**  |
| 站姿不动（两脚 2.9 mm）    | 0.145     | 0.145      |

**旧评分下 0.528 与实测 `joy_foot_peak_mean = 0.529` 吻合到 0.001** —— 说明重建的轨迹是  
对的，下面这行才有意义：

> **旧规则下，单腿踏步（0.528）比站着不动（0.145）高 3.6 倍。**  
> 所以策略选踏步而不是站着，完全合理 —— 踏步是当时最便宜的买分方式。  
> 而交替（0.823）只比踏步（0.528）高 0.295，**这点差距抵消不了多抬一条腿的成本。**

新评分下踏步掉到 0.144，**和站着不动一模一样**。唯一还能往上走的路只剩"两脚都抬"，  
交替与踏步的差距从 0.295 拉大到 **0.854（6.9 倍）**。

这也顺带解释了旧评分为什么在交替上只有 0.823 而不是 1.0：它按**步**评 running peak，  
摆动窗刚开启时峰值还没爬升完，早段一律偏低。`pair_min` 取**窗末峰值**，没有这个偏差。

### 22.2 一个静默的时钟分叉（必须先修，否则第十版必错）

`joy_foot_peak.__call__` 里原本是自算相位：

```python
t = env.episode_length_buf * step_dt
p = 2 * math.pi * frequency * t          # 没有 RSI offset
```

而 `joy_phase(env)` 返回同一个式子**再加** `env._joy_gait_phase_offset`。  
`joy_gait_clock`、`joy_head_command`、`joy_body_command` 全都调 `joy_phase`。

RSI 关闭时没有 offset 属性，两者**逐位相同** —— 这就是第九版没暴露它的原因。一旦第十版  
开 RSI，观测钟和奖励钟就相差最多 π，策略会被按**错误的半周期**评分，而且全程无报错。

改成 `p = joy_phase(env, frequency=frequency)`：RSI 关时逐位不变，开时正确。  
负对照在 `probe_pair_min.py` §5：交替轨迹 + env 上挂 π 偏移 → 分数从 **0.998 崩到 0.000**。  
若奖励还在用自己的钟，这个数会纹丝不动。这是"下游真的读到了"的判据。

### 22.3 为什么不做 Teach Biped 的双支撑时长惩罚

arXiv 1910.10194 用"连续双支撑超过 100 步 → −2.0 并终止 episode"处理同一症状。没采用：

1. **与 `pair_min` 完全冗余。** "两脚同时着地"就是单腿踏步，`pair_min` 已经把它从 0.528  
   压到 0.144（等于站姿）。再叠一个项，两个机制作用在同一现象上，无法归因。
2. **硬阈值 + 终止比连续评分粗暴得多。** 课程前几档（7 mm）本来就要靠"两脚都贴地"打底，  
   一上来就给终止惩罚会把 stage 0 直接打散。

对应地实现了 `joy_foot_stance` —— 但它防的是**另一件事**（hopping）：  
在对方的摆动窗内，本脚必须贴地。`pair_min` 罚「都不抬」，`joy_foot_stance` 罚「都抬」，  
两者从两侧夹住交替步态。默认 **不注册**（`MICRODUCK_JOY_DS_WEIGHT=0`），  
让第十版保持两个变量（`pair_min` + RSI）而不是三个。

顺手量了它的量级，免得以后高估它：整跳时支撑脚超出阈值 14 mm，代价 **0.014/步**，  
而 `joy_feet` 满额 12/步 —— 要靠它单独压住 hop 需要权重约 850，那会把训练搞崩。  
它的定位是**连续提示信号**（权重 50–200），主要防线仍是"没有支撑就会摔"。

### 22.4 验证（`tools/probe_pair_min.py`，全 CPU）

```
1. cfg 开关（双向）            OFF 无 pair_min 键 / 无 joy_ds；ON 均为真
   真实调用链                  inspect.isclass → 实例化 → params 展开 → shape (2,)
2. 三种步态分离                见 22.1 表
3. end_peak 按窗口锁存          300 步只变 12 次（半周期 22 步 ≈ 13 次）
4. 单 env 重置只清自己           两个 env 喂不同轨迹；env0 → [0,0]，env1 逐位不变
5. 奖励读 joy_phase             π 偏移下 0.998 → 0.000
6. joy_foot_stance             交替 0 / 踏步 −0.000129 / 整跳 −0.014
```

第 4 项特意给两个 env 喂了**不同**轨迹。第一版这里写的是  
`or True` —— 一个永远通过的假断言，等于没测。已改成真检查。

第 6 项里踏步不是恰好 0 而是 −0.000129，也不是 bug：实测表里右腿在 phase 0.48 已达  
8.42 mm，跨过了相位边界、开始离地。真实轨迹就是这样。

### 22.5 起训命令（暂不执行）

```bash
MICRODUCK_JOY_PAIR_MIN=1 MICRODUCK_JOY_PHASE_RSI=1 MICRODUCK_JOY_SYMMETRY=1 \
  bash tools/train_joy.sh smooth 2048 600 joy_pair_2048x600
```

保留第九版的对称增强：它已经证明能让**某一条**腿抬到 23 mm（能力存在），而 `pair_min`  
要求两条腿都达到这个能力；增强让左右样本互补，两者是协同不是冲突。  
`train_joy.sh` 现在会把四个开关打进日志头，run 之间不会再出现"日志一样、配置不同"。

**验收判据（单一）**：`Metrics/joy_end_peak_left_m` 与 `_right_m` 是否**同时**超过 18 mm。  
只涨一侧 = `pair_min` 被单侧解绕过（那时才需要开 `joy_foot_stance`）。  
两侧都涨但 `8hz` 恶化 = 抬脚变成了抖，要看 `8hz_foot_interpretable`。

⚠️ `tools/apply_joy_patch.py` 会用 `.upstream` 的**未打补丁** `mdp.py` 覆盖 site-packages。  
重跑它之后必须重放补丁链：`patch_joy_peak_linear` → `patch_joy_peak_curriculum` →  
`patch_joy_gait_clock` → `patch_joy_phase_rsi` → `patch_joy_pair_min`。  
新脚本会在 anchor 缺失时直接报错退出，而不是静默什么都不做。

---

## 23. 执行器清单（顺带纠正我在第 22 节之后的错误说法）

### 23.1 先纠错

上一轮答「还要训练多少次」时我说：「官方 18.5/20.0 mm 是 **No servo overrides**，我们的重训  
是为了保留 smooth-Pd 执行器」。**这句是错的**，读代码后事实正好相反：

```python
# microduck_joy_env_cfg.py:11-13
def make_microduck_joy_env_cfg(play=False, pd_actuators=False):
    cfg.scene.entities['robot'] = deepcopy(
        MICRODUCK_STANDUP_PD_ROBOT_CFG if pd_actuators else MICRODUCK_STANDUP_ROBOT_CFG)

# :114
def make_microduck_joy_pd_env_cfg(play=False):     return make_...(play, pd_actuators=True)
# :127  smooth 任务也走 pd_actuators=True
def make_microduck_joy_smooth_pd_env_cfg(play=False): ...
```

`smooth` 任务用的是 `MICRODUCK_STANDUP_PD_ROBOT_CFG` → `pd_actuators` = **`XmlActuatorCfg`**，  
也就是 **XML 自带的位置伺服**，`delay_min_lag=0/max=3`。而 `microduck_constants.py:184-190`  
的注释写得很明白：

> 「This is the plant the shipped joy policy was audited in …  
> 「No servo overrides」, feet_peak 18.5 / 20.0 mm against a 24.5 mm target」

**所以 18.5/20.0 mm 与我们训练时是同一个 plant。** 执行器差异**不是**我们和官方的差距来源。  
「No servo overrides」指的是审计时把**动作侧平滑器**关掉了，不是换了执行器。

### 23.2 三层清单：什么在用、什么在库里没启用

| 层                                                     | 状态     | 关键参数                                                                                                                                                                               |
| ----------------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JoySmoothPositionAction`（动作平滑）                       | **在用** | `joy_alpha=0.25`、`joy_max_step=0.08 rad/步`、reset 时以当前 `ctrl` 为起点（`_joy_pending`）                                                                                                   |
| `XmlActuatorCfg` → XML `chosen_actuator`              | **在用** | `kp=0.55`、`kv=0`、`forcerange=±0.96 N·m`、`damping=0.053`、`frictionloss=0.0048`、`armature=0.0018`、`ctrlrange=±10`、延迟 0–3 物理步（dt=1 ms → 0–3 ms）                                       |
| `FrictionDRBamActuator`（BAM 电压模型）                     | 在库未启用  | `motor=xl330/model=m6`、`kp_fw=200`、`vin 6.5–8.2 V`（每 env 采样）、电压 sag gain 0–0.2、`vin_min=6.0`、延迟 3–6 物理步、Coulomb+Stribeck+负载相关摩擦、`friction_scale` 每 episode 重采样                     |
| `BacklashEncoderBamActuator` + `robot_*_backlash.xml` | 在库未启用  | 每关节串一个 `passive_<joint>_backlash` 铰，`range=±0.0174533` = **±1.0°**；`solreflimit="0.01 1"` 特意收紧防过冲；**编码器读在齿轮副输出侧**（`get_command` 里 `cmd.pos += qpos[backlash]`），所以伺服在死区内打滑时 PD 误差不变 |

注意 `kp_fw=200` 是固件刚度（BAM 的电机域），**不要和 XML 的 `kp=0.55 N·m/rad` 直接比大小**，  
两者不是同一个量纲。

### 23.3 这条纠正带来的实际后果

既然 plant 相同、BAM/齿隙/摩擦 DR 都没启用，那么**当前唯一"官方那次没有、我们这次有"的  
差别就是动作平滑器**（其余差别在奖励/观测/起点，那些是第 22 节的 `pair_min`+RSI 在处理的）。

而平滑器本身会**限速抬脚**：FK 算过从 HOME 抬到 20 mm 只需 `max|dq|=0.28 rad`，按  
`max_step=0.08` + `alpha=0.25` 算时间常数约 4 步、半周期 22 步，**名义上够**；但它让关节指令  
整体滞后，与策略自身的反馈叠加后可能形成「抬不起来」的稳态——这正是我们九版都卡在  
5 mm 附近的一个未排除嫌疑。

**因此下一步最便宜的不是起训，而是补一个 `--no-conditioner` 开关**（`eval_joy_in_sim.py`  
现在只有 `--plant {default,bam}`，会换执行器但**保留**平滑器），把 v9 checkpoint（右腿  
23.46 mm）在平滑开/关两格各跑一次，约 4 分钟。若关掉平滑后两脚都抬起来，九版以来一直在  
调的奖励就是白调的。

---

## 24. 现成参考在哪：我们哪三段是重复造轮子

用户的直觉是对的。分区如下。

### 24.1 有现成，我们也确实该用：动作平滑三件套

**① IsaacLab 内置 `EMAJointPositionToLimitsAction`（几乎是逐条同构）**

公式 `applied = α·processed + (1−α)·previous`，**reset 时 `previous` 初始化为当前关节位置**——  
这与我们的 `JoySmoothPositionAction`（`joy_alpha` + `_joy_pending` 从当前 `ctrl` 起步）  
是同一件事。差别：

- IsaacLab 的 `alpha` 支持**按正则的 per-joint dict**，默认 `1.0` 即关闭；我们的 `0.25` 写死、**没有关闭开关**；
- 我们多一个 `joy_max_step=0.08` 斜率钳位（IsaacLab 的 EMA 没有）。

→ **mjlab 没有这个 action term**（只有 JointPosition / Velocity / Effort / Relative /  
Tendon / Site / IK 七种），所以自己写是**必要的**。错的不是"写"，而是**没对齐语义、没留开关**。  
出处：<https://isaac-sim.github.io/IsaacLab/develop/\\\\\\\_modules/isaaclab/envs/mdp/actions/joint_actions_to_limits.html>

**② `JointPositionLowPassAction`：用截止频率而不是 α**

`LocoWheeledLegged`（Isaac Lab 系）实现的是真低通：  
`_compute_lowpass_weights(control_frequency, cut_off_frequency, order)`，支持 1/2 阶，  
系数由**截止频率 Hz** 算出来。这比我们的 α 强的地方很具体：**它说得清压掉了多少 Hz**。

我们的 α=0.25 说不清带宽，而验收门偏偏是 `8hz_ratio`（按 Hz 定义的能量比）——  
用一个连带宽都说不清的低通去影响一个按 Hz 定义的门，这是我们反复误读这条指标的根源之一。  
出处：<https://github.com/zhaozijie2022/LocoLeggedWheel>

**③ `active_adaptation`（MotionTracking）：把平滑做成域随机化**

`alpha ∈ [0.5, 1.0]` **每个 env 随机采样** + action delay queue。也就是说：如果怀疑平滑是  
元凶，标准做法不是把它固定成某个值，而是**让它随机**，使策略对平滑强度鲁棒。  
出处：<https://deepwiki.com/xiaohu-art/MotionTracking/6.3-actuator-models>

### 24.2 层次错了：真机的平滑在舵机固件里，不在策略侧

XL330 控制表（ROBOTIS 官方）：

| 地址      | 名称                        | 说明                                               |
| ------- | ------------------------- | ------------------------------------------------ |
| 108     | `Profile Acceleration`    | 加速度剖面（4B）                                        |
| 112     | `Profile Velocity`        | 速度上限（4B）。**默认 0 = 不做 profile（Step Instruction）** |
| 116     | `Goal Position`           | 目标位置                                             |
| 123     | `Moving Status`           | 记录当前选中的剖面类型                                      |
| **140** | **`Position Trajectory`** | **伺服自己算出的目标轨迹，可读回**                              |

即"目标平滑"在真机上属于 **plant**，不属于 policy。官方 sim 的 `<position kp kv>` 没有  
轨迹发生器——这与 `Profile Velocity=0` 的默认行为**一致**。我们却在 action 侧加了一个 EMA，  
把 plant 的事放到了策略上。

后果可以推得很具体：**如果真机 runtime 打开了 profile（112≠0），部署时就是"固件平滑 + 我们的  
EMA"双重平滑**，比训练时更迟钝——而这恰好是我们一直在担心的方向的加剧版。

可验证（有实机时）：读 112/108 是否非零；再读 140 与 116 是否逐拍相同（相同 = 无剖面）。  
出处：<https://docs.robotis.com/docs/dxl/model_reference/x_series/xc_series/xc330-m288/>

### 24.3 奖励层：Duckverse 现成的 trio 我们 pop 掉了，然后自己发明了 pair_min

`feet_air_time` / `foot_clearance` / `foot_swing_height` 是 upstream 现成的，  
我们 pop 掉它们的理由是 `command_threshold=0.01` 的速度门在 joy 恒 0 速度下永不触发。  
**正确的修法是把速度门换成相位门，而不是另造一个 `min(end_peak_L, end_peak_R)`。**

`pair_min` 是推导出来的（第 22 节已标注"未找到现成实现"），而 trio 是 Duckverse 有的。  
从"减少自研面积"的角度，v11 应该优先试"相位门控的 trio"，而不是继续在 pair_min 上加权重。

### 24.4 结论：哪些必须自己推，哪些不该

| 事项                       | 判断                                                   |
| ------------------------ | ---------------------------------------------------- |
| mjlab 上的 EMA action term | **必须自己写**（mjlab 没有），但语义应对齐 IsaacLab、α=1.0 可关闭        |
| 低通截止频率参数化                | **有现成**，应换成 Hz + 阶数，别用裸 α                            |
| 平滑强度不确定性                 | **有现成**，随机化 α（0.5–1.0）而不是写死 0.25                     |
| 目标轨迹平滑属于哪一层              | **有现成答案**：舵机 Profile（108/112），不是 policy              |
| "两脚都要抬"的奖励               | Duckverse trio 是现成的，但需换门控；`pair_min` 才是真自研           |
| 观测里的相位钟 / RSI            | 有现成（LORM / GeCCo / IsaacLab PhaseGaitCommand），我们实现正确 |

---

## 25. 对照 Duckverse：六处可测偏离、五处我此前判断错、以及"同分不同步态"的量化

### 25.1 先把"官方"分清楚——有三份东西，不是一份

| 来源                                                                  | 是什么                                                          | 关键事实                                                                                                                                                                                                      |
| ------------------------------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pollen-robotics/microduck_rl` @ `b02fdea4`（`develop` 头，2026-10-12） | 仿真/训练**框架**                                                  | 本地 `.upstream` 254 个文件**一个不缺**，与官方逐文件对齐。但全文 **`joy` 出现 0 次**，`microduck_joy_env_cfg.py` **不在官方仓库里**                                                                                                       |
| `ros-claw/microduck`（Duckverse）`artifacts/neon-escape-v6/training/` | Duckverse 发布的 joy **训练产物**                                   | `selected-env.yaml`(49 KB) / `selected-agent.yaml` / `run.json` / `selected-run-git.diff`(474 KB) / `joy-smooth-train.log.gz`；外加 `policies/continuous_joy.onnx`                                           |
| `.upstream/rc_art/audit_smooth300.json`                             | ~~18.46 / 20.03 mm 的出处~~ **（2026-10-24 更正：该文件无此字段，见 §26.3）** | 只证明 Duckverse joy 流水在游戏里跑过：`victory.mode = continuous_joy_smooth_pd_v1`，`skills` 里 `joy` 与 stand/run/roulade/jump 并列，`stage = CELEBRATE`。**抬脚高度请用 `out/probe_joy_official.json`（16.36/17.34 mm @0.2 ms）** |

Duckverse 产物已存到 `microduck-software/.upstream/official-joy-2026-10/`（553 KB）。  
**「官方 joy 任务」这个说法不成立：这套 joy 代码根本不在 `microduck_rl` 里**，它是 `ros-claw/microduck` 的一份 patch  
（`src/mjlab_microduck/tasks/{mdp,__init__,microduck_joy_env_cfg}.py` + `scripts/export.py`

- `tests/test_joy_cfg.py`，见 `patch-application.json`）。我们那份 `microduck_joy_env_cfg.py`  
  是**照产物重建**的。

### 25.2 数值对照：Duckverse selected-env / selected-agent vs 我们的运行时

| 项                                                                           | Duckverse                                                                                                                                                    | 我们                                                 | 判断                                  |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- | ----------------------------------- |
| 抬脚项                                                                         | `joy_foot_rhythm`（`exp(-((h-target)/0.009)^2).prod(-1)`，target=`0.0005+0.024·relu(±sin p)²·e`）                                                               | `joy_foot_peak`（linear `clamp(窗口末峰值/0.020)`，只评摆动脚） | **已偏离**                             |
| 其余 11 项权重                                                                   | upright 2.0 / pose 0.15 / body_ang_vel −0.05 / angmom −0.02 / dof_limits −1.0 / foot_slip −0.1 / self_coll −1.0 / joy_head 3 / joy_balance 5 / joy_drift 100 | **完全一致**                                           | ✓                                   |
| `action_rate_l2` 课程                                                         | −0.1 → −0.5 @2400 → **−1.0** @4800                                                                                                                           | −0.05 → −0.15 @3600 → **−0.3** @7200               | **松 3.3×**                          |
| actor 观测                                                                    | **61 维**（9 项，无 gait_clock）                                                                                                                                   | **63 维**（+`gait_clock`）                            | **已偏离**                             |
| `init_std` / `std_type`                                                     | **0.4 / scalar**                                                                                                                                             | **0.12 / log**                                     | **小 3.3×**                          |
| `entropy_coef`                                                              | **0.01**                                                                                                                                                     | **0.002**                                          | **小 5×**                            |
| 训练起点                                                                        | **`resume: true`，`load_run: pd200-seed`**，`--agent.resume True`                                                                                              | **从零**                                             | **本地 `microduck_joy_pd` run 数 = 0** |
| `symmetry_cfg`                                                              | `null`                                                                                                                                                       | 可选开                                                | 我们是新增                               |
| RSI（相位随机偏移）                                                                 | 无                                                                                                                                                            | 可选开                                                | 我们是新增                               |
| episode / decimation / timestep                                             | 8.0 s / 20 / 0.001                                                                                                                                           | 8.0 / 20 / 0.001                                   | ✓                                   |
| PPO 其余（epochs 5、mb 4、lr 2e-4、γ.99、λ.95、KL.01、clip.2、hidden 512-256-128 elu） | —                                                                                                                                                            | **全部一致**                                           | ✓                                   |

### 25.3 五处我此前说错的（每条都有 Duckverse 文件打脸）

1. **"Duckverse 现成的 trio（`air_time`/`foot_clearance`/`foot_swing_height`）被我们 pop 掉，应该换相位门复用"**  
   —— `selected-run-git.diff` 里Duckverse joy patch pop 的正是**同一批 8 项**  
   （`track_linear_velocity/track_angular_velocity/air_time/foot_clearance/foot_swing_height/
   head_pose_tracking/head_pose_bias/body_pose_tracking`）。这不是我们扔了 Duckverse 的东西，  
   **Duckverse 自己也扔了**。v11「相位门控 trio」这个方向因此作废。
2. **"两脚乘积会把摆动脚的得分乘上 0.285"** —— 0.285 来自我们自己的 `clamp(peak/20mm)` 口径。  
   Duckverse 是 **per-foot target**（支撑脚目标 **0.5 mm**，要求它踩下去）+ 高斯。实测：站姿 **0.378**  
   不是 0.04。**我们因为误读这个乘积，才放弃 Duckverse 奖励、自造 linear + pair_min。**（§22 的推导链  
   在这一步断了。）
3. **"2048 env 全从 p=0 起步 → 系统性不对称，是根因"** —— Duckverse `joy_phase` 同一实现，也全从 p=0  
   起步，照样训出交替（ONNX 实测 16.36/17.34 mm）。**RSI 不是必需**，最多算加固。
4. **"`action_rate` 终点 −1.0 没有注释、莫名更紧，改成 −0.3"** —— −0.1/−0.5@2400/−1.0@4800  
   **就是 Duckverse 的课程值**（`selected-env.yaml: curriculum.action_rate_weight`）。我们在  
   `patch_joy_action_rate.py` 里凭"没有 justification"把它放松了 3.3 倍，而 justification 一直在 Duckverse 的 `selected-env.yaml` 里。
5. **"entropy 0.01 会让任务梯度消失"** —— Duckverse 就是 0.01。那条结论是在 σ=18 的坏奖励下测的，  
   换了奖励就失效。

### 25.4 决定性的一组数：**同一个分数位上，交替和单腿踏步并存**

同一份奖励（Duckverse σ=9 高斯）的两条训练曲线：

|                                       | `joy_feet` 轨迹                                                 |
| ------------------------------------- | ------------------------------------------------------------- |
| 我们 `0757`（从零，std 0.4）                 | 0.17 → **4.88@100** → 5.18@200 → **5.64@599**                 |
| Duckverse smooth（resume 自 pd200-seed） | **0.166@iter200** → 4.x@250 → **6.0@iter349**（selected 是 300） |

两条曲线几乎重合，末端都停在 **≈6/12 = 0.5**。而 `tools/probe_official_rhythm.py` 把四套口径  
放到**同一条实测轨迹**（`probe_phase_sym.log` 的 24 点分箱，model_599 的真实踏步）上：

```
  scorer                                    alternating   march   standing     hop
  official joy_foot_rhythm σ=9mm                0.903      0.441    0.378    0.213
  official, σ=18mm (我们 patch_joy_foot_sigma)   0.974      0.724    0.651    0.552
  ours joy_foot_peak linear 20mm                0.823      0.528    0.145    0.823
  ours + pair_min                               0.998      0.145    0.145    0.998
```

（乘 12 即实际分。`alternating` 是理想弧线，`march` 是实测轨迹，`hop` 是两脚同起。）

三条结论：

- **0.5 这个分位上，交替（0.90）拿不到，踏步（0.44）拿得到** —— Duckverse 与我们的 `joy_feet≈0.5`  
  既可能是"低幅交替"，也可能是"单腿踏步"，**这条均值曲线无法区分两者**。所以拿它对标  
  "谁更接近成功"是无效的；只有相位剖面能分。
- **σ=18 是我们所有版本里最差的一版**：站姿 0.651（白送 65%），交替/踏步只有 1.35×。  
  §15 判它错，这里是同一条轨迹上的复核。
- **`pair_min` 修好了踏步（0.145），但把 hop 也给了满分（0.998）**；Duckverse 口径下 hop 只有 0.213  
  （交替的 24%）——**因为 Duckverse 支撑脚目标是 0.5 mm，两脚同起时支撑脚因子直接塌掉。**  
  `pair_min` 丢掉了这层保护，而 `joy_foot_stance` 默认权重 0、量级又太弱（§22.3）。

### 25.5 顺带一条陷阱：脚高 50 mm 那次是摔了

`out/eval_joy_xmlpd599_bam.json` 读到 `feet_peak 49.86 / 51.95 mm` —— 同一 checkpoint 换 BAM 植物。  
但 `min_upright_worst_env = 0.334`、`8hz_ratio_foot = 0.0402`、`max_drift` 全线 FAIL。  
**这是摔倒过程中脚被甩起来的读数，不是抬脚。** 只看 `feet_peak` 会被骗，必须同时看 upright。

### 25.6 结论与建议（仍未起训）

九版之所以越走越远，是因为我在 `patch_joy_peak_linear.py` 那一步把 Duckverse 奖励**误读**成"两脚乘积会  
压分"，之后每一版都在补一个自己造出来的洞。现在有 Duckverse 的 resolved 配置在手，正确做法不是继续加项，  
而是**把基线复现出来，再谈改进**：

1. `joy_feet` 回到 `joy_foot_rhythm`（σ=9 默认、per-foot target、两脚乘积），撤掉  
   linear / 7→20mm 课程 / `pair_min`；
2. actor 观测回 61 维，撤 `gait_clock`；
3. `init_std 0.4 / std_type scalar / entropy_coef 0.01`；
4. `action_rate` 课程回 Duckverse −0.1 / −0.5@2400 / −1.0@4800；
5. **两段式**：先 `joy_pd` 200 轮（无条件器）→ `--agent.resume` 到 `joy_smooth_pd` 再 100–150 轮；
6. 先不叠 RSI / 对称增强（Duckverse 两者都没有）。

第 5 条是唯一一条我们**完全没试过**的：本地 `logs/rsl_rl/` 下 `microduck_joy_pd` 的 run 数 = 0。  
而 `run.json` 写明 Duckverse 是 `resume_index: 200 → selected 300`，`matched_fine_tune_updates_through_selected: 101`。

---

## 26. 再检查：把 §25 的每个数字换成机器读数（2026-10-24 21:00）

用户要求"再检查一下"。§25 是人工比对的结果，而本项目此前**五次自我否定全部源于人工读数**，  
所以这一轮不再靠眼睛，改成一个可重跑的脚本 `microduck-software/tools/verify_vs_official.py`，  
它把 Duckverse resolved 配置、我们每个 run 的 `params/*.yaml`、以及**当前装着的 live 配置**三者  
做机械 diff。下面每个数都是它打出来的。

```bash
cd microduck-software
.venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --table   # 每个 run 一行
.venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --live    # 现在起训会用到的配置
.venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --stack   # 两份拷件各装了哪些补丁
.venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --sync    # installed -> .upstream
```

### 26.1 全部 run 的机器读数（`--table`）

```
                                                run last actor_in init_std std_type entropy max_it        joy_feet ar_w0 gait_clock diff_vs_off
-------------------------------------------------- ---- -------- -------- -------- ------- ------ --------------- ----- ---------- -----------
  2026-10-24_07-57-43_joy_smooth_2048x600_1024_0757  599       61      0.4   scalar    0.01    600 joy_foot_rhythm  -0.1         no           0
  2026-10-24_09-45-54_joy_smooth_2048x600_1024_ar03  599       61      0.4   scalar    0.01    600 joy_foot_rhythm -0.05         no           1
2026-10-24_11-24-29_joy_smooth_2048x600_1024_std012  599       61     0.12      log   0.002    600 joy_foot_rhythm -0.05         no           1
      2026-10-24_14-06-41_joy_smooth_2048x600_xmlpd  599       61     0.12      log   0.002    600 joy_foot_rhythm -0.05         no           1
       2026-10-24_15-05-41_joy_smooth_2048x600_peak  200       61     0.12      log   0.002    600   joy_foot_peak -0.05         no           2
       2026-10-24_15-26-37_joy_smooth_2048x600_trio    0       61     0.12      log   0.002    600               - -0.05         no           5
     2026-10-24_15-33-54_joy_smooth_2048x600_sig018  599       61     0.12      log   0.002    600 joy_foot_rhythm -0.05         no           2
               2026-10-24_16-33-50_smoke_peaklinear    4       61     0.12      log   0.002      5   joy_foot_peak -0.05         no           2
           2026-10-24_16-34-53_joy_peaklin_2048x200  199       61     0.12      log   0.002    200   joy_foot_peak -0.05         no           2
                   2026-10-24_17-03-27_smoke_curric    3       61     0.12      log   0.002      4   joy_foot_peak -0.05         no           2
            2026-10-24_17-04-17_joy_curric_2048x600  599       61     0.12      log   0.002    600   joy_foot_peak -0.05         no           2
                    2026-10-24_17-50-47_smoke_clock    2       63     0.12      log   0.002      3   joy_foot_peak -0.05        yes           2
             2026-10-24_17-51-36_joy_clock_2048x600  599       63     0.12      log   0.002    600   joy_foot_peak -0.05        yes           2
                      2026-10-24_18-39-31_smoke_sym    2       63     0.12      log   0.002      3   joy_foot_peak -0.05        yes           2
               2026-10-24_18-40-46_joy_sym_2048x600  599       63     0.12      log   0.002    600   joy_foot_peak -0.05        yes           2
```

两件事一眼可见，且都不需要信我的话：

- `actor_in` 只有最后两个 run（clock / sym）是 63，其余全是 61 —— 与 `state_dict` 里  
  `actor.0.weight` 的形状一致，不是从日志推的。
- **`0757` 的 `diff_vs_off = 0`**：12 项奖励、3 项课程、8/13 个观测项、`init_std/std_type/entropy`  
  与 Duckverse **逐项相同**。

### 26.2 更正一：`0757` 就是 Duckverse 配方，而它失败了

这是本轮最重要的一条，§25 里没有写清楚。`0757` 不只是"用了 Duckverse 奖励"，它是**逐项等于 Duckverse 配置**  
的一次 600 轮从零训练：plant 也一样（`joy_pd_spec`、`ts=0.001`、`dec=20`、2048 envs、  
事件集合 12 项完全相同），`action_rate_l2` 权重 −0.1 与课程 0/2400/4800 也一样。

结果：`feet_peak 6.16 mm`、`joy_feet≈0.487`、`8hz_ratio 0.0126` FAIL。

也就是说 **"回 Duckverse 基线"本身不是一个新实验 —— 它 07:57 已经跑过一遍了，失败。**  
那么 §25.6 那 6 条建议里，只有第 5 条（两段式 warm start）是**真正没有测过的变量**，  
其余 5 条单独回退都不会改变 `0757` 的结论。建议顺序应当是：**先做第 5 条**，把  
`joy_pd 200 → resume` 跑通，再谈要不要动奖励形状。

### 26.3 更正二：18.46 / 20.03 mm 的出处是错的

§9、§15、§25 里多处写"Duckverse audit 的 18.46 / 20.03 mm，与 `target_height=0.02` 吻合"，  
并注明出处 `.upstream/rc_art/audit_smooth300.json`。**该文件里没有这个量级的脚高字段。**

把整个 json 递归扫一遍，落在 18–21 区间的浮点数只有两个：

```
/audit/contacts/playball/first = 19.4876      # 秒
/props/_boss_body              = 19           # 整数
```

而 18.46 / 20.03 最像是从这个文件里**另一类字段**读出来的：`"t": 18.46`（时间，秒）与  
`"yaw": 0.02002`（弧度）。同一文件里 `"t"` 从 18.42 一路排到 20.10，`"yaw"` 从 0.01805 排到  
0.02066 —— 把它们当成 mm 就是**量纲错**，不是"改写"。

**真正可用于「Duckverse 会抬脚」的证据**是 `microduck-software/out/probe_joy_official.json`：

```
lfoot_z peak 16.315 mm   rfoot_z peak 16.970 mm   joy_feet_peak_mm [16.36, 17.34]
min_upright 0.9946   max_drift 0.0326 m   hf_ratio 5.14e-4   9/9 gates PASS
plant = servo   physics_step_s = 0.0002   joint_vel_delay = 1
```

注意它的工厂是 **0.2 ms**（Duckverse 部署步长），而我们所有 `eval_joy_sim_*.json` 跑的是  
**1 ms**（训练步长）。§25 拿"Duckverse 16–17 mm"对"我们 6 mm"时**混了两个时间步**，这个对比当时就不严。

### 26.4 更正三：同一个 0.2 ms 工厂下，Duckverse 过、我们倒

既然 `tools/probe_joy_policy.py` 能跑任意 ONNX（`ALPHA=0.25` / `max_step=0.08` 写死，与两个策略  
的训练条件一致），就可以把"Duckverse vs 我们"放进**同一个工厂**。三个策略、同一组参数  
（`--plant servo --seconds 8 --joint-vel-delay 1`）：

| 策略                              | feet_peak (mm) | min_upright | max_drift | hf_ratio | passed   |
| ------------------------------- | -------------- | ----------- | --------- | -------- | -------- |
| Duckverse `continuous_joy.onnx` | 16.36 / 17.34  | **0.9946**  | 0.0326    | 5.1e-4   | **True** |
| 我们 `0757`（Duckverse 配方）         | 35.96 / 15.89  | **−0.0684** | 0.0310    | 8.9e-6   | False    |
| 我们 `curric_599`                 | 38.67 / 38.03  | **0.0402**  | 0.1382    | 1.9e-5   | False    |

`upright` 为负 / 0.04 说明**翻倒**，那些 35–38 mm 的"抬脚"是摔倒甩腿（§25.5 同一个陷阱）。

这条比 §25 的任何一条都强：**两次从零训练（含完全照 Duckverse 配方的那次）在 5× 细的时间步上都翻，  
Duckverse checkpoint 不翻。** 它把问题从"奖励形状"推到两处：

1. **两段式 warm start**（唯一没试过的变量，§26.2）；
2. **1 ms 训练出的接触刚度不足以迁移到 0.2 ms** —— Duckverse description 里那句  
   "four CPU deployment tuning probes" 现在有了具体读数支撑。

需要说明的边界：探针的 reset 姿态/伺服目标初值与训练 reset 不一定逐位相同，所以这不能证明  
"策略本身不行"，只能证明"换到 Duckverse 声明的部署步长后，我们现在的 ckpt 都不行"。

### 26.5 更正四：live 配置与 Duckverse 只差 6 项（`--live`）

用 `Mjlab-JoySmoothPD` 任务（真正在训的那个）构建，而不是 `pd_actuators=True` 的粗构型 ——  
后者少了 `initialize_joy_servo_targets`，会误报"事件缺失"。机器输出：

```
[rewards]    same=10 diff=2
  DIFF action_rate_l2  weight: official=-0.1   ours=-0.05
  DIFF joy_feet        func:   official=joy_foot_rhythm   ours=joy_foot_peak
[curriculum] same=2 diff=1
  action_rate_weight  official=[0:-0.1, 2400:-0.5, 4800:-1.0]
                      ours    =[0:-0.05, 3600:-0.15, 7200:-0.3]
[obs/actor]  official 8 terms / ours 9 (+gait_clock)   → 61 vs 63
[obs/critic] official 13 terms / ours 14 (+gait_clock)
[agent]  XX init_std 0.4→0.12   XX std_type scalar→log   XX entropy_coef 0.01→0.002
         XX resume True→False
         == lr / epochs / mini-batches / gamma / lam / kl / clip / hidden / steps / max_it 全部相同
```

于是 §25.6 的第 3、4、6 条被**修正为 5 项偏离**（原来写"11/12 权重一致"是错的，  
`action_rate_l2` 的权重也是偏离项）。同时 `lr` 与 `max_iterations` **不在**偏离里 ——  
`MicroduckJoySmoothPdRlCfg` 已经把 lr 钉回 2e-4、`max_iterations` 是 200，  
和 Duckverse 一致；600 是我们每次用 `--agent.max-iterations` 在命令行盖上去的。

> 但 **`JoyPd`（第一段）会继承 base 的 `lr=3e-4`**（Duckverse 两段都是 2e-4）。做两段式之前  
> 必须先把这一行改回 2e-4，否则第一段就是 off-spec 的。已在 cfg 里加了注释。

### 26.6 更正五：`.upstream/mdp.py` 落后 4 层补丁，ONNX 缺 joy 元数据

`--stack` 的原始读数（修之前）：

```
== installed: 10/10 层 PRESENT（peak_linear / curriculum / gait_clock / rsi / pair_min / stance）
== upstream : peak_linear / curriculum / gait_clock / pair_min / stance 全部 absent，只有 rsi 在
== mdp.py: installed == upstream ? False
```

原因是编辑路径不对称：cfg 类补丁写 `.upstream` 再拷进 site-packages，**mdp 类补丁只写  
site-packages**。而 `.upstream` 才是重装包时的源 —— 一重装就静默掉 4 层。  
已执行 `--sync`（installed → upstream，备份 `mdp.py.pre-sync`），现在两份逐字节相同、10/10 层。

顺带查出导出链的缺陷（这一条与训练无关，但会影响实机）：

| onnx                            | `joint_stiffness` | `joy_target_alpha` / `joy_max_step` / `joy_frequency_hz` |
| ------------------------------- | ----------------- | -------------------------------------------------------- |
| Duckverse `continuous_joy.onnx` | 0.550 ×14         | 有                                                        |
| 我们 `0757/ar03/std012`           | **1.000 ×14**     | **缺**                                                    |
| 我们 `xmlpd` 之后                   | 0.550 ×14         | **缺**                                                    |

`apply_joy_patch.py` 的 `SKIP = ["scripts/export.py"]` 里写着"metadata 另作处理"，  
**但没有任何脚本做过**。缺 metadata 的 onnx 交给部署端，条件器参数就只能靠猜。

> **更正（见 §27.7）**：本节写的"缺 4 个 `joy_*` 键"数少了 —— 按 Duckverse `continuous_joy.onnx` 的 13 个键全量对，  
> 我们 14 个 run 都是 **8 个键、缺 5 个**（多了 `joy_commands` 与 `joy_target_conditioner`）。  
> Duckverse 原值也读出来了：`joy_target_alpha=0.25`、`joy_target_max_step_rad=0.08`、`joy_frequency_hz=1.15`、  
> `action_scale=1.0`。其中 α 与 max_step **与我们 `JoySmoothPositionAction` 的构造参数完全一致**，  
> 也就是说不是"参数选错了"，纯粹是导出脚本没把这些数写出去。

### 26.7 结论（替代 §25.6）

| # | 动作                                                                                                       | 依据                                                                        |
| - | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| 1 | **先跑两段式**：`Mjlab-JoyPD` 200 轮（先把 base lr 改回 2e-4）→ `--agent.resume/load_run` 到 `JoySmoothPD` 再 100–150 轮 | §26.2 唯一没试过的变量；`run.json` resume_index 200 / selected 300 / fine-tune 101 |
| 2 | 2–4 项偏离（`joy_feet` / `action_rate` / `gait_clock` / `init_std` / `entropy`）**等第 1 步结果再动**，一次只改一项         | `0757` 已证明全回 Duckverse 配方也会卡在 6 mm                                        |
| 3 | 任何"通过"结论都必须跑 `probe_joy_policy.py --plant servo`（0.2 ms）                                                 | §26.4：1 ms 上 6/8 PASS 的 ckpt 在 0.2 ms 直接翻                                 |
| 4 | 导出 ONNX 后立刻验 `joint_stiffness=0.550` 与 4 个 `joy_*` 键                                                     | §26.6                                                                     |

全文再没有"Duckverse joy 是 18.46/20.03 mm"这个说法；引用 Duckverse 抬脚请用 `out/probe_joy_official.json`  
的 16.36/17.34 mm（0.2 ms），并注明工厂。

---

## 27. 第四个来源：`fanhao375/microduck-replica`（2026-10-24 21:45）

用户给了仓库地址。查法与之前一致：`api.github.com/repos/...` 取 `default_branch`（= **`master`**），  
再拉 `git/trees/master?recursive=1`（1290 个 blob，未截断）。**1317★ / 227 fork**，  
`pushed_at 2026-10-24T06:13Z`（今天下午），最近 15 个提交全是文档/镜像/IMU，没有 RL 提交。

**它是谁**：硬件复刻项目（3D 打印 + 电控 + 镜像），但 `software/training/` 是 **`mjlab_microduck`  
的一个完整 fork**，底子是官方 **0.15.1**，换成了飞特 HD-1910 舵机（1.47 N·m、320:1）。  
**有实机**——这是它相对前三个来源唯一不可替代的价值：它记录的是**官方策略真机跑起来长什么样**。

**它没有 joy**：函数集机械对比 —— 他们 `mdp.py` 229 个 `def`，我们 246 个；  
「只有他们有」的 10 个全是 `balance_*`，「只有我们有」的 27 个是 `joy_*` / `seated_*` / `servo_*`。  
所以**代码一行都抄不到**，能拿的是判据和数字。存档在 `.upstream/replica-2026-10/`。

### 27.1 他们的 `AGENTS.md` 有三条 hard invariant 直接判我们现有改动

原文标题就是 "Invariants — do not break these"。

**(1) 61 维是运行时的契约，不是口味。**

> Obs layout is 61D (actor) and shared across the whole policy family so policies are  
> hot-swappable in the runtime: 48 base proprioception + 13D command block  
> `[twist(3), head_pose(4), body_pose(6)]`, in that order. An env that doesn't use a  
> command slot ZERO-PADS it (keep the obs term, sample tiny ranges) — **never delete a slot**.

配一个实测：Duckverse `continuous_joy.onnx` 的图输入是 **`[1,61]` → `[1,14]`**（`onnx.load` 读的，不是猜的）。  
→ `gait_clock` 把它变成 63。**这不是"偏离 Duckverse 配方"，是"官方运行时加载不了"。**  
§24/§25 里"gait_clock 是第 3 项偏离"的说法要升级为**必须撤**。

**(2) 训练带滤波，部署必须带同一个滤波。**

> **Policies are UNFILTERED** (no action low-pass in training). Don't add EMA filtering  
> without a **matched runtime flag** and a transfer test — trained-with / deployed-without  
> (either direction) breaks transfer.

我们的 `JoySmoothPositionAction(α=0.25, max_step=0.08)` 属于"训练带滤波"。那部署端必须带同一个。  
Duckverse ONNX 有 `joy_target_alpha` / `joy_max_step` / `joy_frequency_hz` 三个键，**我们一个都没有**（§26.6）。  
→ §26.6 那条"ONNX 缺元数据"从**工程整洁问题**升级为**直接违反这条不变量**。

**(3) 对称损失默认关。**

> Symmetry mirror-loss is available (61D table in `symmetry.py`) — **OFF by default**,  
> never for asymmetric tasks.

独立第三方把它当可选、默认关。与第九版实测（镜像增强把 `5.37/23.46` 完全对调成 `23.46/5.37`）同向。

### 27.2 他们的奖励设计清单里，两条命中我们的病

**(a) 乘法组合的代价 —— 这条把 §24 的量化结论变成通用定律。**

> Multiplicative composites beat additive sums at goal states ... **a product of Gaussians  
> collapses on any single deficient factor — but pick stds wide enough that the CURRENT  
> policy scores visibly, or the gradient is invisible and nothing changes.**

Duckverse `joy_foot_rhythm` 就是**两脚乘积**，σ=9 mm，而我们卡在 6 mm。  
→ 结论不是"乘积错了"，而是：**乘积的每个因子，σ 必须按"当前策略已经能拿到的值"定，不能按目标值定。**  
这与 §24 的量化（旧规则踏步 0.528、交替 0.998，均值曲线分不开）是同一件事的两种说法。

**(b) 平滑项必须在技能出现之后才上 —— 这是"两段式"的原理级支持。**

> Smoothness (action_rate, joint_torque_rate) damps jitter without blocking slow big motions —  
> safe to weight, but **introduce it AFTER skill discovery (curriculum from ~0)**: any  
> attempt-tax active while a hard skill is being explored makes "**do nothing**" win.

Duckverse 两段式正是这条：第一段 `joy_pd` 200 轮在轻税下先把踏步学出来，第二段 resume 到  
`joy_smooth_pd` 再把 `action_rate` 爬到 −1.0。  
→ 这比"Duckverse 就是这么干的"更强：它给出了**为什么不能一步到位**的机制（税会奖励"不动"）。

### 27.3 训练预算：我们的 600 轮约等于他们最便宜预算的三分之一

| 来源                                     | 环境数 × 迭代 × 24 步  | 环境步           |
| -------------------------------------- | ---------------- | ------------- |
| 他们的口径「simple episodic tricks」          | 4096 × 1000      | **98 M**      |
| 他们的口径「gaits / curriculum-heavy」        | 4096 × 4000–6000 | **393–590 M** |
| **我们每版跑的**                             | 2048 × 600       | **29.5 M**    |
| Duckverse joy（pd 200 + smooth 100–150） | 2048 × 300–350   | **15–17 M**   |

→ Duckverse 300 多轮就成，所以"轮数不够"**不能单独解释**我们的失败。  
但它给了一个刻度：**600 轮 ≈ 他们最便宜预算的 1/3。**  
含义很实际：600 轮可以当**筛子**，不足以当**判决**。我们前十版里有几版是在 600 轮就下结论的，  
那些结论的置信度要往下调。

### 27.4 一条被排除、一条被量化、一条方向相反

**排除 —— 评测没有"托住机身"。** 他们踩坑记录里有一条「测行走模型别用手托着机身」：

> 手托机身时给 0 / 0.05 / 0.15 m/s 都只换一下姿势，之后几秒不动；放到地上不扶，0.4 秒内  
> 两腿就开始交替屈伸。原因：这类模型输入里没有「节拍」，迈步靠身体晃动、重心转移，  
> 再经 IMU 和关节反馈带出来。机身被托住，身体不晃，输出很快停在一个静止姿势上。

我去查了我们两条评测链：`probe_joy_policy.py` 直接写 `qpos[0:3]=[0,0,0.122]`、`qpos[3:7]` 四元数  
（自由基座）；`eval_joy_in_sim.py` 用 `root_link_pos_w`。**都没有固定或托住机身 → 排除。**  
顺带：这条也说明"输入里没有节拍"是这类模型的正常设计 —— Duckverse 61 维没有 clock 也能踏步，  
我们加 `gait_clock` 是想用外部时钟替代自激振荡，方向本来就是反的。

**量化 —— 部署端三个折扣加起来就是"真机只抬仿真一半"。**

他们真机实测（官方 walk 策略 + `tools/gait-analysis/foot_clear.py`）：两只脚只抬 **3～6 mm**，  
同条件仿真 11～12 mm。拆出来三个来源，**全部在部署端，训练里一个都没有**：

| 折扣    | 值                                                                         | 单项影响（他们仿真）                                                       |
| ----- | ------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 动作缩放  | **0.83**（0.9 × 电压补偿 7.4/V≈0.925）                                          | 离地 12.7/11.9 → **9.6/8.9 mm**（−25%）；撑地膝盖 +3.5/+6.5° → −0.6/+1.5° |
| 腿低通   | **α=0.7**（新目标 = 0.7×模型目标 + 0.3×上一拍，头 0.5）                                 | 步频 3.1→2.8 Hz（步子变大变慢）                                            |
| 运行时增益 | `robotd-params` 的 `gain=200`，站立乘 `standing_gain_ratio=0.8` → **P=160 上力** | 未单独测                                                             |

→ 顺带查出一个**必须写清的对照错误**：他们的腿低通 α=0.7 是他们自己那套飞特运行时的值，  
**不能拿来跟我们比**。我读了 Duckverse ONNX 的元数据（见 §27.7），Duckverse 是：

```
joy_target_alpha        = 0.25
joy_target_max_step_rad = 0.08
action_scale            = 1.0
```

**我们的 `JoySmoothPositionAction(α=0.25, max_step=0.08)` 就是 Duckverse 值，一分不差。**  
所以"α=0.25 偏重"这条怀疑**不成立**，撤掉。真正的问题不在参数值，在于它没写进导出的 ONNX（§27.7）。

**方向相反 —— 他们自训建议里的抬脚目标是 25～30 mm。**

> 自训时：舵机参数用哪份（先做单关节阶跃响应）、**抬脚目标 25～30 mm**、用实测的整鸭重量、  
> 脚底摩擦的随机范围要盖住我们的鞋底、训练时就带上真机要用的缩放和滤波。  
> —— `docs/HD1910-20261014-白天-仿真找原因与新版放开参数.md` §10.7

性质要写清：这是**建议，不是他们验证过的结论**（同一页也写了 kissqy 训练时是 1/1/1、部署才  
0.9/0.5/0.7，即"训练时带上滤波"这条他们自己也没做）。但"25～30 mm"这个数的依据是实的：  
真机只有仿真的 40–50%，要真机抬 10 mm，仿真就得抬 25 mm。  
→ 我们第九/十版一直在**往下压**目标（linear clamp 到 20 mm、`pair_min` 取两脚窗末峰值的 min，  
把摆动脚吞掉），方向相反。

### 27.5 顺带确认/存疑

- **61 维 / 14 维 / 50 Hz**：三个独立来源一致（官方上游、这个 fork 的不变量、官方 ONNX 形状）。**只有我们 63 维。**
- 他们物理步长 **5 ms**、控制延迟 3–6 步（15–30 ms），因为换了 1.47 N·m 的飞特舵机；我们用官方  
  1 ms + dec 20。**不需要跟**，但注意：他们同样没解决"训练步长 ≠ 部署步长"的迁移问题，  
  而是靠换硬件对齐。§26.4 那个 1 ms 训练 / 0.2 ms 就翻的现象，在他们的路线里也是未解项。
- 他们同样卡在"仿真有、真机没有的高频颤"（对齐条件后仿真 **96% 高频、4.1 Hz**，真机 **6%、3.0 Hz**），  
  原文写"原因没查"。与我们的现象不同、困境相同：**接触/摩擦层面仿真和真机没对齐。**

### 27.6 对当前决策的净影响

§26.7 的顺序不变，四处强度变化：

| # | 动作                                             | 变化                                                   |
| - | ---------------------------------------------- | ---------------------------------------------------- |
| 1 | 先跑两段式 `JoyPD 200 → resume JoySmoothPD 100–150` | **加强**：§27.2(b) 给出原理（税要在技能之后）                        |
| 2 | 撤 `gait_clock` 回 61 维                          | **从"建议"升为"必须"**：§27.1(1) 运行时契约，63 维官方运行时加载不了         |
| 3 | 补 ONNX 四键 + `joint_stiffness=0.550`            | **从"整洁"升为"必须"**：§27.1(2) 训练带滤波/部署不带 = 转移破坏           |
| 4 | 不用 `pair_min` 吞摆动脚；抬脚目标往上留余量                   | **新增**：外部实机数据（真机 = 仿真 40–50%）支持"往上留"，`pair_min` 方向相反 |
| 5 | 600 轮只当筛子，不当判决                                 | **新增**：§27.3 预算刻度                                    |

### 27.7 Duckverse ONNX 的 13 个元数据键，我们导出 8 个（这才是"缺什么"的完整答案）

§26.6 说"缺 4 个 `joy_*` 键、`joint_stiffness` 早期是 1.000"，实际按全部键对一遍是  
**Duckverse 13 个、我们 8 个、缺 5 个**。Duckverse `continuous_joy.onnx` 的原值（`onnx.load` 读的）：

```
run_path                = logs/rsl_rl/microduck_joy_smooth_pd/2026-10-03_23-35-37_continuous-smooth-pd-v1/model_300.pt
joint_names             = left_hip_yaw,...,right_ankle            (14)
joint_stiffness         = 0.550 ×14
joint_damping           = 0.000 ×14
default_joint_pos       = 0,-0.087,-0.458,-0.005,0.453, 0.349,0.349,0,0, 0,0.087,0.458,0.005,-0.453
command_names           = twist,head_pose,body_pose
observation_names       = base_ang_vel,projected_gravity,joint_pos,joint_vel,actions,command,head_command,body_command
action_scale            = 1.0
joy_commands            = v1
joy_frequency_hz        = 1.15
joy_target_conditioner  = v1
joy_target_alpha        = 0.25
joy_target_max_step_rad = 0.08
```

我们 14 个 run 的逐项比对（每个 run 都是 `keys=8`）：

| 项                       | 结果                                                                                                              |
| ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| **缺 5 个**               | `joy_commands` / `joy_frequency_hz` / `joy_target_conditioner` / `joy_target_alpha` / `joy_target_max_step_rad` |
| **`joint_stiffness`**   | 前三个 run（`0757` / `ar03` / `std012`）= **1.000**；从 `14-06-41_xmlpd` 起 = **0.550**，已修好                             |
| **`observation_names`** | 只有 `clock` / `sym` 四个 run 不同（多 `gait_clock`），其余与 Duckverse 一致                                                            |
| 其余 7 键                  | 键名全有；`run_path` 值本来就是本地的，不算缺陷                                                                                   |

两件事因此确定：

1. **要补的是 5 个键，不是 4 个**。且值是**契约常量**，不是随便填：`joy_frequency_hz=1.15`  
   与 `mdp.joy_phase(frequency=1.15)` 的默认值一致（我们没改频率，这点是对的），  
   `joy_target_alpha=0.25` / `max_step=0.08` 与 `JoySmoothPositionAction` 的构造参数一致。  
   也就是说**训练侧和元数据侧本来就该是同一组数，只是导出脚本没写出去**。
2. **这不是"顺手美化"，是 §27.1(2) 那条不变量的直接违反**：策略是"训练带滤波"训出来的，  
   交给一个没有 `joy_target_alpha` 的部署端，它就会**不带滤波**跑 —— 训练/部署条件不一致。  
   Duckverse 把这三个键当接口发出来，正是为了让运行时能复现训练条件。

---

## 28. 四个复刻项目 + Pollen/NVIDIA 两套流程，与两个推翻前文的读数（2026-10-24 22:10）

这一轮用户连续给了三个仓库（`kissqy/Microduck-kissqy`、`zhuoligetu123/microduck-hd1910m`、  
`Animan-AI/DuckBuddy`），加此前已查的 `fanhao375/microduck-replica`，并要求把 Pollen 的  
训练/运行流程与 NVIDIA 10-23 的新教程拆开。查法照旧：`api.github.com` 取 `default_branch`  
→ `git/trees/<branch>?recursive=1`；`kissqy` 的本地快照 `b5371d9` 已是最新（head `eccc2fd`  
只改了 README 排版，compare 显示 2 个文件 +12/−7）。

### 28.1 四个项目的定位（**没有一个做 joy**）

| 项目                                |    ★ | 是什么                                                          | 有自训 locomotion？                                              | 有 joy？ | 真正可用的东西                                               |
| --------------------------------- | ---: | ------------------------------------------------------------ | ------------------------------------------------------------ | ------ | ----------------------------------------------------- |
| `fanhao375/microduck-replica`     | 1317 | 硬件复刻 + `software/training`（mjlab fork，官方 0.15.1 底，换 HD-1910） | 是（自述未验收）                                                     | 否      | `AGENTS.md` 三条不变量；BAM 对拍                              |
| `kissqy/Microduck-kissqy`         |  138 | 实机 + 固件 `control.43` + Armbian 镜像 + 训练中控（35 个官方 task cfg 快照） | 是（到 **14000 轮**）                                             | 否      | `runtime-audit.md`（commit 级运行时证据）；部署端三个折扣；训练量刻度       |
| `Animan-AI/DuckBuddy`             |   47 | Feetech + Orange Pi Zero 3W，`policies/` 直接放官方 9 个 onnx       | 否（训的是 `pet-detect` 视觉）                                       | 否      | `training/bam/`（BAM 拟合、checkpoint sweep、`feet_check`） |
| `zhuoligetu123/microduck-hd1910m` |   27 | Radxa ZERO 3W + HD1910M ×15 + BNO08x，发布 4 个固定 ONNX           | 否（`README` 明说"发布默认模型是未修改的 Reference 四个 ONNX，不是本机 PPO 续训检查点"） | 否      | `diagnose_clearance_reachability.py`（抬脚可达性静态 IK）      |

用户那句"好像都不太一样"是对的，但差异不在方向：**四个都是"换硬件 + 复用官方策略"**，  
两条腿一条腿都没踢进 joy。`microduck_rl` 的 **33 个**注册任务（实跑 `list_tasks()` 数出来的，见 `microduck-RL_duck教学仓对照.md` §4.1；旧版写 35 是错的）、HuggingFace  
`pollen-robotics/microduck-policies` manifest 的 8 个 active onnx  
（`velstand / alpha_sitstand / alpha_ground_pick / ball_kick_left / ball_kick_right / roulade / roller / roller_crouch`）  
里都没有 joy。**joy 只在 duckverse（`ros-claw/microduck`）的 `artifacts/neon-escape-v6/`**——  
也就是说我们训 joy 这件事，全世界没有第二份可对照的实现。

`zhuoligetu123` 那个仓库里有一个工具值得单独记：  
`diagnose_clearance_reachability.py` 用静态 IK 解"抬脚 8/15/25 mm、支撑脚水平、COM 在支撑  
多边形内留 2 mm、躯干可滚 ±0.35 rad"是否**运动学可达**，并在 report 里写死免责："Optimizer  
failure is not proof of geometric impossibility; success is not gait stability." 这正好可以  
回答"抬脚目标定 25–30 mm 到底可不可达"——比继续调奖励便宜得多，列入待做。

### 28.2 更正六：物理步长**不是**变量（推翻 §26.4 的解释）

上一轮说"1 ms 训练出的接触刚度不足以迁移到 0.2 ms"。用同一探针、同一 ckpt、只改  
`--timestep/--decimation` 各跑一遍（0.2 ms/dec 100 与 1 ms/dec 20，都是 50 Hz 控制）：

| 策略                              | 0.2 ms feet   | 1 ms feet         | upright (0.2 / 1 ms)  | 结论       |
| ------------------------------- | ------------- | ----------------- | --------------------- | -------- |
| Duckverse `continuous_joy.onnx` | 16.36 / 17.34 | **16.48 / 16.86** | 0.9946 / **0.9949**   | 两档都 PASS |
| 我们 `0757`                       | 35.96 / 15.89 | **35.96 / 16.05** | −0.0684 / **−0.0684** | 两档一模一样   |
| 我们 `curric_599`                 | 38.67 / 38.03 | **38.79 / 38.07** | 0.0402 / **0.0392**   | 两档一模一样   |

5 倍步长差，读数几乎逐位相同。而Duckverse joy 训练本身就是 **1 ms / dec 20**  
（`selected-env.yaml`: `sim.mujoco.timestep=0.001`, `decimation=20`），0.2 ms 只是它部署探针的  
声明。**所以"训练 1 ms → 部署 0.2 ms"这个跨越 Duckverse 自己也做了，且站得住。§26.4 的解释②作废。**

### 28.3 更正七：探针与训练后端不是同一个物理引擎，"翻倒"是后端产物

这是本轮最重要的一条。两条评测链对**同一个 ckpt** 给出相反结论：

| 链                     | 后端                                                                      | 规模       | `min_upright`   | `feet_peak`   | 判定       |
| --------------------- | ----------------------------------------------------------------------- | -------- | --------------- | ------------- | -------- |
| `eval_joy_in_sim.py`  | **MuJoCo Warp**（`mjlab/sim/sim.py: import mujoco_warp`，`device=cuda:0`） | 512 envs | **0.9948 PASS** | 6.16 mm FAIL  | 站得住、抬脚不够 |
| `probe_joy_policy.py` | **CPU `mujoco`**（`mujoco.MjSpec.from_file(XML)` + 只加力矩限幅）               | 1 env    | **−0.0684 翻**   | 35.96 / 16.05 | 翻倒       |

`eval` 的其余读数：`max_drift 0.0139`、`fell_frac 0.98%`、`end_upright 0.9999`、  
`joy_foot_rhythm_mean 0.487`。也就是说在训练同构后端上，0757 **不翻**，只是抬脚 6 mm。

于是 §26.4 那张"Duckverse 16–17 mm / 我们翻倒"表的正确读法是：

- 它证明的是"**在 CPU 标量后端上**，我们的 ckpt 站不住、Duckverse 站得住"；
- 它**不能**证明"我们的策略在训练/部署后端上会翻"——`eval` 说不会；
- 探针的价值回到**相对比较**（同一后端下 Duckverse vs 我们），不能再当绝对判决。

附带一个可检的假设：CPU `mujoco` 与 `mujoco_warp` 在接触求解/solver 迭代上不同，  
而步态对接触极敏感。若要继续用探针下结论，必须先做**后端一致性自检**：  
把 Duckverse `continuous_joy.onnx` 放进 `eval_joy_in_sim.py` 跑一遍，看两条链对 **Duckverse** 是否给同样的数。

### 28.4 核实**通过**的五条接口契约（这次是读代码，不是读文档）

官方运行时的契约（`kissqy` 的 `recovery-teacher11000-check.json` 给出了机器可读的一份）逐条对：

| 契约         | 官方                                                               | 我们                                                                                             | 结论              |
| ---------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------- |
| 观测里的动作历史   | `previous_action_observation: raw_policy_output`                 | `last_action` → `action_manager.action` → `self._action`，在 per-term `process_actions` **之前**写入 | ✅ 同             |
| 平滑位置       | `stage: joint_position_target_after_home_and_scale`              | `super().process_actions()` 之后才滤（= 已含 scale+offset）                                            | ✅ 同             |
| 公式 / reset | `a*target+(1-a)*prev`；`first_target_passthrough_per_environment` | 同式；`_joy_pending` 首拍直通 `ctrl+encoder_bias`                                                     | ✅ 同             |
| 更新节拍       | `once_per_policy_step`，`control_hz=50`                           | 每控制步一次，`step_dt=0.02`                                                                          | ✅ 同             |
| 61 维布局     | gyro3+gravity3+q14+qdot14+act14+twist3+head4+**body6**           | 逐项函数核对：`joy_body_command` 返回 **6** 维；`3+3+14+14+14+3+4+6=61`，+`gait_clock`(**2**) = 63         | ✅ 撤 clock 即回 61 |

另两条：

- `action_rate_l2` 的 docstring 明写 "Operates on raw policy output (before per-term scale/offset)"  
  → 平滑器改的是 `_processed_actions`，**罚不到它**，两者互不抵消（§26 那条结论仍成立）。
- `joint_vel_rel` 减 `default_joint_vel`，而 `HOME_FRAME` 的 `joint_vel={'.*': 0.0}`  
  → 等价于官方的绝对 `qdot`。✅

我们与官方**唯一**的差异是 `max_step` 钳位——但 Duckverse ONNX 元数据里就有  
`joy_target_max_step_rad = 0.08`，同值。这条不是偏离。

### 28.5 把训练/运行流程拆开：官方是**两套软件**，NVIDIA 是**一条平行支线**

用户原话"两套软件各管一段"基本准确，需要补两处。准确的结构是 **2 官方 + 1 第三方**：

|       | 仓库 / 产品                                        | 语言                                                       | 负责                           | 关键事实                                                                                        |
| ----- | ---------------------------------------------- | -------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------- |
| A 板载  | `pollen-robotics/microduck`                    | Rust（`robotd` / `duck-control` / `robotctl` / `updater`） | 加载 ONNX、50 Hz 控制循环、通信、相机、OTA | `duck-control/src/obs.rs` 固定 61 元素；`policy.rs` 声明归一化**烘进 ONNX 一次**                          |
| B 训练  | `pollen-robotics/microduck_rl`                 | Python（mjlab + **MuJoCo Warp** + PPO）                    | 定义任务/观测/奖励/随机化，训练并导出 ONNX    | 0.15.1 pin 的 **33 个**注册任务用 **5 ms/dec 4**；develop（joy 用的）改成了 **1 ms/dec 20**；两者控制频率都是 **50 Hz** |
| C 第三方 | NVIDIA（Isaac Lab 3.0 + **Newton** + Omniverse） | Python                                                   | 平行实现，训练 + 评测                 | 与 B **不共享配置**，只共享 ONNX 契约（61/14）                                                            |
|       |                                                |                                                          |                              |                                                                                             |

A/B 之间真正绑死的接口只有六个：**61 维观测顺序**、**14 维动作顺序**、**HOME**、  
**动作缩放**（`Home + scale × raw`）、**归一化**（烘进图里）、**50 Hz**。  
`fanhao375` 的不变量、`zhuoligetu123` 的 README、`kissqy` 的 `runtime-audit` 三份独立  
文档说的是同一件事，只是措辞不同（"hot-swappable" / "EMA 与部署一致" / "Exact 61/14 layout and HOME required"）。

五段流程：

1. **定义任务**（env cfg：obs terms / action term / rewards / events(DR) / curriculum / terminations）
2. **训练**（PPO，GPU 并行；域随机化覆盖质量与质心、地面摩擦、关节惯量、编码器偏移、电压跌落、指令延迟、逐关节齿隙）
3. **导出**（TorchScript + ONNX；归一化烘进图；13 个元数据键；检查 14 关节顺序/HOME/scale）
4. **部署**（`robotd` 50 Hz：装配 61 维 → 推理 → `HOME + scale×raw` → **全局 head/legs 低通**（在 scale 之后）→ 电压适配 → 总线）
5. **迭代**（HuggingFace Hub 分发 `.onnx`；Microduck Arena 要求 61/14/≤64 MiB）

### 28.6 用户材料里需要改的三处

1. **"两套软件"→ 2 官方 + 1 平行支线**。NVIDIA 那条不是官方的第三段，而是第三方重做；  
   而且它的 4096 并行环境 + RTX PRO 6000 Blackwell **是"在已预训练的 locomotion 策略上再做  
   ramp/障碍适配"的二次训练**（原文："A locomotion policy pretrained in that environment  
   receives **additional training** for traversing ramps and obstacles, using head-camera  
   depth"），不是从零训。拿"4096 envs"去估我们从零训 joy 的预算会高估。
2. **价格与预售对，交付要补**：$399 是 introductory price、不含税运，8-27 开预售都对；  
   但 Pollen 已不再承诺圣诞前交付，新订单 4–6 个月（10-23 复核）。CEO 说"2 万+ 预订单"  
   是 CEO 的说法，不是审计数字。
3. **开源范围原文比转述更硬**：press kit 写"mechanical and electronic design files are not  
   (open source), so please do **not** describe the robot as open-source hardware"。  
   软件是 Apache-2.0。这条与我们直接相关——BD 里再回"开源硬件"是错的。

另外补一条用户没提但影响判断的：**NVIDIA 教程 6 个阶段里前 5 个都是"准备 + 训练 + 评测"，  
原文明确"Detailed hardware deployment is outside the scope"**。它的产出是"能在 Isaac Sim 里  
跑完障碍的 61/14 策略"，不是"上机可用的鸭子"。

### 28.7 这一轮对主线（joy 踏步）的净影响

| # | 变化                                                        | 依据                                     |
| - | --------------------------------------------------------- | -------------------------------------- |
| 1 | **删掉"步长不匹配"这个解释**，它不成立                                    | §28.2：5× 步长差读数逐位相同；Duckverse 也是 1 ms 训         |
| 2 | **删掉"我们的 ckpt 会翻倒"这个判决**，它只在 CPU 后端成立                     | §28.3：Warp 后端 `min_upright 0.9948`     |
| 3 | 主问题收敛成一句话：**站得住，但抬脚只有 6.16 mm（要 >8 mm）**                  | 两条评测链在这点上一致                            |
| 4 | 接口层**没有**发现新 bug（六条契约全过）                                  | §28.4                                  |
| 5 | 下一步仍是**两段式**，但理由只剩两条：Duckverse 唯一没被我们试过的变量 + 三条独立来源的机制支持          | §27.2(b)、§27.3、`kissqy` 的"技能被后续模仿破坏"记载 |
| 6 | 新的便宜实验：`diagnose_clearance_reachability.py` 测我们机器人的可达抬脚上限 | 决定"20 mm 目标"是否本身就不可达                   |

---

## 29. 第五个来源（`LuwuDynamics`）+ 把 ONNX 元数据这件事真正修完（2026-10-24 22:20）

用户问「有官方 + 这么多其他复刻参考，不会再有问题了吧」，并给了  
`https://github.com/LuwuDynamics/xgoduck_hardware`。答案是不能。这一节给出为什么，  
同时把上一节留下的「ONNX 缺 5 键」从"待办"变成"已改并验证"。

### 29.1 这个仓库：硬件，一行软件都没有

`api.github.com` 取 `default_branch = master`，`trees/master?recursive=1` 共 **66 个 blob、未截断**：

```
stl 30   md 14   pdf 2   jpg 4   pcbdoc/schdoc/dwg/step/xlsx/csv/png/svg/webp 各 1~2
py / onnx / ipynb / yaml / xml = 0
```

1238★ / 161 fork，`created 2026-09-24`，`pushed 2026-10-23`。内容是 3D 打印件、PCB、  
BOM、装配手册。它的 `UPSTREAM.md` 自己写得很清楚：

> XGO-Duck is a **substantial adaptation** of the Microduck ecosystem, not an independently  
> originated robot concept. ... "Adaptation" here describes the engineering work visible in the  
> XGO-Duck source. **It does not establish exclusive ownership of every file.**

它列出的"继承/参考"里确实把 `microduck_rl` 的「task recipes and PPO/ONNX workflow」算进去了，  
但**这个仓库里没有那份 work**。同一组织的另一个仓库才是：

### 29.2 真正的训练仓库 `xgoduck_rl`（85★，429 blob）—— 12 个任务，**没有 joy**

```
Mjlab-Velocity-{Flat,Rough}-XgoDuck      Mjlab-StandUp-{Flat,Rough}-XgoDuck
Mjlab-GroundPick-{Flat,Rough}-XgoDuck    Mjlab-SitStand-{Flat,Rough}-XgoDuck
Mjlab-BallKick-{Flat,Left}-XgoDuck       Mjlab-Roulade-Flat-XgoDuck
Mjlab-Velocity-Swizzle-XgoDuck
```

`tasks/` 里没有 `joy_*`，`mdp.py` 也没有 joy 函数。所以这是第 **6** 个复刻仓库，  
第 **6** 个没有 joy 的。累计查过的：`fanhao375/microduck-replica`、`kissqy/Microduck-kissqy`、  
`Animan-AI/DuckBuddy`、`zhuoligetu123/microduck-hd1910m`、`LuwuDynamics/xgoduck_hardware`、  
`LuwuDynamics/xgoduck_rl` —— **0 个做 joy**。

### 29.3 「两段式」这个词有歧义，必须分开写

`scripts/train_xgoduck_getup_then_velocity.sh` 第 3 行，原文：

> \# The two tasks do not share checkpoints — **velocity always starts from scratch**.

它做的是「起身训完 → 速度**从零**再训」，**不共享权重**。而 duckverse 的 joy 两段式是  
`--agent.resume True`，`run.json` 里 `resume_index: 200 → selected 300`  
（`matched_fine_tune_updates_through_selected: 101`），**共享权重**。

两者都叫"两段"，机制相反。含义：

- 不能拿这个仓库当「两段式 warm start 有第三方先例」的证据 —— 它不是；
- warm start 的唯一直接证据仍然是 duckverse 那一条 `run.json`，加三条原理级支持  
  （§27.2(b) 税要在技能之后、`kissqy` 的"行走被模仿更新破坏"、`xgoduck_rl` 的 `AGENTS` 式不变量）；
- 反而说明：**"分两段训不同任务"是常见做法，"第二段从第一段权重接着训"不是**。  
  这让第 5 条建议（warm start）的置信度**下调一档**，它仍是唯一没试过的变量，但不是"大家都这么干"。

### 29.4 新拿到的一条**官方原文**：交替步态本身 sim2real 就差

`src/mjlab_microduck/tasks/microduck_velocity_swizzle_env_cfg.py` 的 docstring ——  
这个文件**我们自己的 site-packages 里就有**（`Mjlab-Velocity-Swizzle-MicroDuck` 在我们  
注册表里），不是我原先以为的 xgoduck 自创：

> A separate roller task producing a CLASSIC SWIZZLE: both blades stay on the ground, the legs  
> spread out and pull back in SYMMETRICALLY (hourglass pattern) ... Simpler / more stable  
> alternative to the alternating stride (`Mjlab-Velocity-Flat-MicroDuck-Rollers`),  
> **which does not transfer well to the real robot**.

读法要克制：这是 **roller（轮子）** 任务、说的是"交替滑步"，不是 joy 的踏步。但它确实说明  
**官方在遇到"交替步态上不了真机"时的解法是换一种步态（swizzle），不是调奖励**。  
对 joy 这条线是反向证据：我们一直在奖励上找，而官方在同类问题上的先例是**承认这个步态难迁移**。

### 29.5 一条嫌疑被关掉：求解器参数逐项相同

xgoduck 的 tricks 配置里有 `cfg.sim.mujoco.iterations = 30`、`ls_iterations = 50`、`nconmax = 200`，  
像是被调过的。逐项对比 Duckverse `selected-env.yaml` 与我们的 live 配置：

```
              official                          ours
timestep      0.001                             0.001
integrator    implicitfast                      implicitfast
solver        newton                            newton
iterations    30                                30
ls_iterations 20                                20
cone          pyramidal                         pyramidal
nconmax       200                               200
```

**完全一致**（xgoduck 那个 `ls_iterations=50` 是他们自己的改动，官方是 20）。  
接触求解参数不是我们的问题来源，这条关掉。

### 29.6 ONNX 元数据：已改，并端到端验证 13/13

先确认了「原来那 8 键就是 mjlab 核心给的」：`mjlab/rl/exporter_utils.py::get_base_metadata`  
返回的正好是这 8 个键、且**顺序与我们 14 个 run 的元数据逐位一致**  
（`run_path, joint_names, joint_stiffness, joint_damping, default_joint_pos,
command_names, observation_names, action_scale`）。所以问题从来不是"我们没走官方导出链"，  
而是**Duckverse joy 那 5 个键是在 base 之上额外追加的任务专属键，我们没追加**。

改动（`mjlab_microduck/export.py`，installed 与 `.upstream` 两份已同步、编译通过）：

```python
def joy_metadata_from_cfg(env_cfg) -> dict[str, str]:
    """The 5 extra ONNX metadata keys an official joy policy carries. ..."""
    action_cfg = (getattr(env_cfg, "actions", None) or {}).get("joint_pos")
    alpha = getattr(action_cfg, "joy_alpha", None)
    max_step = getattr(action_cfg, "joy_max_step", None)
    if alpha is None or max_step is None:
        return {}                     # 非 joy 任务：joint_pos 没有 joy_* 字段
    ...
    return {"joy_commands": "v1", "joy_frequency_hz": ..., "joy_target_conditioner": "v1",
            "joy_target_alpha": ..., "joy_target_max_step_rad": ...}

# run_export 里
metadata = get_base_metadata(...)
metadata.update(joy_metadata_from_cfg(env_cfg))
attach_metadata_to_onnx(onnx_path, metadata)
```

设计要点：**值从 live 配置读，不写死**，否则又是一种"改了配置、元数据静默过期"的静默 bug  
（正是 §26 那类）。`JoyPD` 段没有 conditioner，函数自然返回 `{}` —— 语义也对：  
不带滤波训出来的策略，部署端本来就不该滤。

**端到端验证**（不是单测）：用真实导出链重导 `joy_sym_2048x600/model_599.pt`：

```
Duckverse 13 键 / 重导 13 键
joint_names / joint_stiffness(0.550×14) / joint_damping / default_joint_pos /
command_names / action_scale / joy_commands / joy_frequency_hz(1.15) /
joy_target_conditioner / joy_target_alpha(0.25) / joy_target_max_step_rad(0.08)
                                              → 11 项逐字相同
observation_names                             → 只多 gait_clock（应当撤）
run_path                                      → 本就是不同 checkpoint，不算差异
```

产物：`out/onnx_meta_check/sym_599_with_meta.onnx`。

### 29.7 **新暴露一个阻塞**：现在的 live 配置加载不了任何 61 维 checkpoint

想给 `0757`（61 维）也重导一份时，导出直接失败：

```
RuntimeError: Error(s) in loading state_dict for MLPModel:
  Missing key(s): "distribution.log_std_param".  Unexpected: "distribution.std_param".
  size mismatch for obs_normalizer._mean: copying shape [1,61] ... current model [1,63]
  size mismatch for mlp.0.weight: copying [512,61] ... current model [512,63]
```

原因不是 bug，是**状态**：live 配置里 `gait_clock` 还在（+2 维 → 63），所以任何 61 维  
ckpt 都加载不了；`0757` 又是 `std_type=scalar`，与当前 `log` 不匹配。

含义很实际：**"从 `0757` resume 到 smooth 再训"这个动作现在根本跑不起来**，  
而 `0757` 恰好是唯一一个"逐项等于 Duckverse 配方"的 run。撤 `gait_clock`（`patch_joy_gait_clock.py --revert`）  
不是整洁问题，是解这个阻塞的前提。

### 29.8 回答「不会再有问题了吧」

不能。理由按硬度排：

1. **参考再多，覆盖不到 joy。** 7 个仓库 + 官方 **33** 个任务 + HuggingFace 8 个 active policy，  
   **一份 joy 都没有**。joy 只存在于 duckverse 的 `artifacts/neon-escape-v6/`。这不是"参考不够多"，  
   是"这个问题没有同行者"。
2. **这一轮本身又查出两个问题**（不是在参考里找到的，是在用参考时撞出来的）：  
   live 配置与 61 维 ckpt 不兼容（§29.7）、导出元数据缺 5 键（§29.6，已修）。  
   两者都是静默的 —— 不导出、不 resume 就不会报错。
3. **官方自己也承认交替步态难迁移**（§29.4）。这不是我们能靠"多查资料"绕开的结论。

真正把问题关掉的只有三类动作，都不是"再找资料"：

| 类型         | 具体                                                | 状态        |
| ---------- | ------------------------------------------------- | --------- |
| 能用机器判定的    | `verify_vs_official.py --live/--table/--stack`    | 已有，四个模式   |
| 一次改动能关掉的   | ONNX 5 键                                          | **本轮已关闭** |
| 必须做实验才能关掉的 | ① 撤 clock 解阻塞 → ② 两段式 warm start → ③ 抬脚可达性（静态 IK） | 未做        |

第 ③ 条最便宜且信息量最大：它回答的&#x662F;**"20 mm 目标是否运动学上本来就不可达"**。  
如果不可达，前面九版都在追一个取不到的数，那才是这一整条线最该先知道的事。
