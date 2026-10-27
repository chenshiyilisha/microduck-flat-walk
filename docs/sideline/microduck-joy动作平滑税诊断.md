# joy 踏步失败的真正原因：动作平滑罚分在惩罚探索噪声，不在惩罚步态

> 上一版文档（`microduck-joy踏步失败诊断与修法.md`）把病因定为「`action_rate` 课程太快」，
> 并建议「只把爬升从 200 轮改回 1500 轮」。**这个建议的方向对，机制错了。**
> 本文记录推翻它的三个测量，以及据此做的唯一一处改动。

---

## 0. 一句话

`action_rate_l2` 在权重 −1.0 下，实测值 = **−25·σ²（R² = 0.98）**，而 14 维动作的纯探索
噪声地板就是 **−28·σ²**。也就是说这一项 **89% 在测探索噪声**，与策略"动作是否平滑"几乎无关。
它的梯度不是"把步态做平滑"，而是"把 σ 调小"——σ 确实从 0.45 掉到 0.25，探索因此死掉。

---

## 1. 先查资料：三方独立证据都指向同一件事

### ① Hwangbo et al. 2019（Science Robotics，ANYmal）—— 原文写的就是我们这个模式

> "Low penalty on joint torque and velocity results in unnatural motions, whereas **high penalty on
> them results in a standing behavior. The main reason for the standing behavior is that such a
> behavior is already a good local minimum when there is high penalty associated with motion.**
> We solved this problem by introducing a curriculum … **The parameter k0 should be chosen to
> prevent the initial tendency to stand still. It can be easily tuned by observing the first 100
> iterations.**"

两个可以直接照做的操作指令：① 起步阶段的运动罚分必须小到"不诱发站桩"；② **看前 100 轮就能定 k0**。

### ② 上游自己踩过同一个坑，而且留了数字（本机源码，一手）

`microduck_velocity_env_cfg.py:730-741`：

> run `5yay13u4` tried `fine_std=0.1` and **the policy stopped walking entirely by iter 300**
> (air_time 1.01 → 0.02, **peak foot height 15 mm → 2 mm**, entropy collapsed 10.9 → 1.9).
> An instantaneous tight tolerance taxes walking 0.77/step — 76% of the whole air_time reward —
> and is **UNESCAPABLE** … **Standing still scored higher, so it stood still.**

"峰值脚高 15 mm → 2 mm"和我们的量级完全一样（我们从 6 mm 走向 3 mm）。

### ③ 跨项目的数值基准：`action_rate` 的合理量级是 −0.01

| 来源 | `action_rate` 权重 |
|---|---|
| legged_gym 原版 / Go1 / Go2 / R02 / Isaac Lab 迁移项目 | **−0.01** |
| 上游 microduck **joy 档（BAM）** | −0.05 → −0.15 @150 → **−0.30** @300 |
| 上游 microduck **PD 覆盖**（我们跑的） | −0.10 → −0.50 @100 → **−1.00** @200 |

**legged_gym 系是 −0.01，我们的 PD 变体是它的 100 倍**；即使上游自己的 joy 档也只有 −0.30。

---

## 2. 三个测量（都能重放）

### 2.1 脚根本没离地多久 —— `air_time` 改法是死的（幸好先测了）

`tools/probe_joy_feet_contact.py`（model_599，128 envs，8 s，训练 cfg）：

```
foot_z 绝对高度  p0 -0.1mm  p5 0.1mm  p50 1.6mm  p95 3.8mm  p100 8.6mm
stance(p5)       0.10 / 0.12 mm
抬脚量(相对站姿) p50 1.5mm  p95 3.7mm  max 8.5mm
腾空步占比        5.3%
单次腾空时长      平均 5.3 ms   ← 正好一个控制周期
落在 (0.125, 0.300) 窗口内  0.0%
接触断开次数      14.4 次/8 s（理论 1.15 Hz × 2 脚 × 8 s = 18.4）
```

**结论一**：脚只是"抖动式离地"，从不停留超过一个控制周期（20 ms）。上游 `air_time` 窗口
`[0.125, 0.300]` 在这里会给出**恒等于 0** 的奖励 —— 上一版文档的「改法 A：照抄 air_time 窗口」
如果直接跑，等于加了个空项。**这一条必须先测再改。**

**结论二**：节奏是对的（14.4 / 18.4 = 78%），**幅度只有 15%**。它学会了什么时候抬，没学会抬多高。

### 2.2 奖励曲线是单调的，问题不在悬崖

`tools/analyze_joy_feet_cliff.py`，用**训练 cfg 实测站高 0.1 mm**重新积分（上一版用的 5.7 mm 来自
`play=True` 的生成高度，不是训练时的站姿 —— 那个基线是错的）：

| 峰值抬脚 | joy_feet | ×权重 12 |
|---:|---:|---:|
| 0 mm（站桩） | 0.3694 | **4.43** |
| 4 mm | 0.4143 | 4.97 |
| 8 mm（当前） | 0.4826 | 5.79 |
| 12 mm | 0.5909 | 7.09 |
| 18 mm | 0.8318 | 9.98 |
| **24 mm（满幅）** | **0.9961** | **11.95** |

单调、无悬崖、满幅能到 0.996。**从 0.487 走到满幅有 +7.5 分的空间**，而它一分没拿。
所以问题不是"奖励设计得拿不到分"，而是"有东西把这 7.5 分抵掉了"。

### 2.3 ⭐ 抵掉它的那一项，测的是噪声

最后一次迭代的完整奖励分解（每步）：

```
joy_feet        +5.6372
joy_balance     +4.4119
joy_head        +2.6211
upright         +1.8291
action_rate_l2  -1.5456   ← 单项最大罚分
joy_drift       -0.0588
dof_pos_limits  -0.0197
body_ang_vel    -0.0143
```

`mdp.action_rate_l2` 的源码注释自己写着 **"Operates on raw policy output"**，即
`Σ_d (a_t − a_{t−1})²`，**作用在采样出来的动作上（含探索噪声）**。

两个独立同分布 N(0, σ²) 样本之差的平方的期望是 2σ²；14 维求和就是 **28σ²**。

把它和策略自己的 σ 回归（iter 210–599，权重已到 −1.0，n=390）：

```
action_rate_l2 = -25.0 · σ²        R² = 0.9799
实际值 / (28σ²)  均值 0.889   范围 0.770–0.978   标准差 0.029
```

**R² = 0.98，且数值就是理论噪声地板的 89%。** 这一项测的不是"动作平不平滑"，是"σ 有多大"。

配套的时间线完全吻合：

| iter | joy_feet | action_rate_l2 | mean_std |
|---:|---:|---:|---:|
| 60 | **4.36**（= 站桩基线） | −0.56 | 0.452 |
| 100 | 4.88 | −0.76 | 0.446 |
| 120 | 4.88 | **−2.45** | 0.389 |
| 250 | 5.21 | −2.57 | 0.323 |
| 400 | 5.67 | −1.56 | 0.250 |
| 599 | 5.64 | −1.55 | 0.250 |

- **iter 60 就跳到站桩基线 4.36，那时罚分只有 −0.56。** 所以"罚分逼它站桩"这个说法不成立。
- iter 120 罚分跳到 −2.45，同时 σ 从 0.45 一路掉到 0.25 —— **代价最小的一步是把 σ 关小，不是把腿抬起来**。
- σ 关小之后探索死掉，幅度就永远停在 15%。

---

## 3. 改动（唯一一处，单变量）

`microduck_joy_env_cfg.py` 里 PD 变体有一处**没有写理由**的覆盖，把 joy 自己的动作平滑课程
从 −0.30 抬到 −1.00：

```python
if pd_actuators:
    cfg.rewards["action_rate_l2"].weight=-.1
    cfg.curriculum["action_rate_weight"].params["weight_stages"]=[
        {"step":0,"weight":-.1},{"step":100*24,"weight":-.5},{"step":200*24,"weight":-1.}]
```

**删除这两行**，让它继承 joy 档自己的课程（−0.05 → −0.15 @150 → −0.30 @300）。
补丁工具 `tools/patch_joy_action_rate.py`，幂等，同时改上游源树和 site-packages
（否则 `tools/apply_joy_patch.py` 会把改动覆盖回去）。

验证课程真的生效（直接调用 `mdp.reward_weight`，不是读源码）：

```
iter  实际生效 weight
0      -0.05
150    -0.05
300    -0.15
600    -0.30        ← 原来是 -1.00
```

**为什么这是单变量**：同一个 task、同一个植物（smooth PD）、同样 600 轮、同样 seed、
同样超参，只有动作平滑课程不同。`feet_peak` 上升 → 课程就是瓶颈；不动 → 幅度被别的东西
锁住，下一步该动步态奖励而不是罚分。

**为什么是 −0.30 而不是 legged_gym 的 −0.01**：−0.30 是上游**为 joy 这个任务亲自写过**的值，
不是我们的发明。−0.01 更接近 legged_gym 系，但那是四足、大力矩电机、1000 步 episode 的设定；
先取上游值，不够再往下走。

---

## 4. 验收方式（与上一轮同口径，可直接对比）

```bash
# 1) 正式 gate
.venv-mjlab/Scripts/python.exe tools/eval_joy_in_sim.py \
    --checkpoint logs/rsl_rl/microduck_joy_smooth/<run>/model_599.pt \
    --num-envs 512 --seconds 8 --device cuda:0 --out out/eval_ar03.json

# 2) 接触/幅度诊断
.venv-mjlab/Scripts/python.exe tools/probe_joy_feet_contact.py \
    --checkpoint <同上> --num-envs 128 --seconds 8 --device cuda:0
```

关键不是总分，是这三个数：

| 指标 | 旧 run（−1.0） | 目标 |
|---|---:|---:|
| `feet_peak_m` | 0.00616 | **> 0.008**，理想 0.020+ |
| 单次腾空时长 | 5.3 ms | **> 100 ms**（否则 `air_time` 永远用不了） |
| `mean_std` 末端 | 0.250 | **> 0.30**（探索没被压死） |
| `action_rate_l2` | −1.55 | 应落在 −0.4 附近（0.3 × 1.75） |

---

## 4.5 如果 ar03 还不够：下一轮的候选改法（按证据强度排序）

> ⚠️ **先读 §4.6。** ar03 跑完后，下面这四条**不是**下一步的首选 —— 首选是把 `init_std`
> 从 0.4 降到 0.12（理由在 §4.6.4/4.6.5：奖励容差 9 mm ÷ 灵敏度 54.5 mm/rad ≈ 0.165 rad，
> 一个 σ 不该超过一个容差）。这四条留作「σ 修正后仍然抬不起脚」时的后备，其中候选 1、2
> 届时很可能仍然需要，因为它们补的是**方向性**（主任务），与噪声幅度是两件事。

> 这一节是查资料后新增的。上一版列过"改法 A/B/C/D"，其中 A（照抄 `air_time` 窗口）已被
> §2.1 的测量否掉。下面四条是重新检索后剩下的，都本机可落地。

### 候选 1：`foot_clearance` 惩罚项 —— 最便宜，参数照抄上游

上游 `microduck_velocity_env_cfg.py:352` 已经把参数调过一轮：

```
foot_clearance:  weight = -2.0,  target_height = 0.02
                 # 注释原文: Increased from 0.01 to penalize dragging
```

形式是 **`|foot_height − 0.02| × 脚速`**（`mdp.feet_clearance`），是**惩罚**不是奖励。关键差别：

- 它**不要求腾空**，只要脚在移动，就必须在 20 mm 高 —— 所以 §2.1 那个「单次腾空只有 5.3 ms」
  的问题不影响它。
- 它**在 0 mm 处罚得最重**（`|0 − 0.02| × 速度`），正好对着我们「贴地蹭」的失效模式。
- 传感器 `foot_height_scan`（`TerrainHeightSensor`）**现成可用**：joy cfg 里出现 **0 次**
  （`grep -c` 实测），它来自 velocity 基础 cfg 的 `cfg.scene.sensors`（`velocity_env_cfg:267`）
  继承下来的。`env.scene.sensors` 里能直接看到 `foot_height_scan`，不用新建。
  另两个传感器 `feet_ground_contact`（`track_air_time=True`）与 `self_collision` 同样在。

注意两个参数要改：`command_name` 必须设 `None`（理由同 §3：joy 的 twist 恒为 0），
`asset_cfg.site_names` 取 `["left_foot","right_foot"]`（joy 的 `joy_feet` 用的就是这两个 site）。

### 候选 2：相位接触奖励 —— 补上「支撑脚要承重」这半边

MDPI Sensors 2023（Wang et al., 哈工大 Roban 人形）给出的周期奖励结构里，有四个相位指示函数：
`I_grf_left(φ) / I_grf_right(φ)`（地面反力）与 `I_speed_left(φ) / I_speed_right(φ)`（脚速），
符号 ∈ [−1, 1]。原文的约束是**双向**的：

> "In the single-support phase … **punishes the ground reaction force exerted on the swing foot**.
> At the same time, **the relative sliding between the supporting foot and the ground is punished**.
> Additionally, **the ground reaction force exerted on the supporting foot is stimulated**."

我们的 `joy_foot_rhythm` 只约束了「脚的高度追正弦」，**没有约束支撑脚承重**。后果是：
「两只脚都虚点着地、膝盖高频乱震」这个解不被罚（§2.3 的 `8hz_ratio` FAIL 与
`knee_ac_rms 0.167 rad` vs `foot_ac_rms 1.56 mm` 就是它）。候选 1 只压「贴地蹭」，
压不住「膝盖震」，两者需要一起上。

实现用现成的 `feet_ground_contact`：`found` 是 `(N,2)` 布尔，按相位取符号即可。
注意它同样是**二值**量，梯度稀疏，建议做成 `±1` 的有界项而不是硬 gate。

### 候选 3：rsl_rl 对称性 —— 本机已写好，joy 只是没接

`mjlab_microduck/tasks/symmetry.py` 是一份**为 61 维观测 / 14 维动作量身写好的**镜像表：

- `_OBS_PERM` / `_OBS_SIGN` 覆盖全部 61 维，逐维注释说明为什么取反（`hip_yaw`/`hip_roll` 反号、
  `neck_pitch`/`head_pitch` 不反号等），并明确按 `left 0-4 / midline 5-8 / right 9-13` 的关节序。
- 文件头写着 2026-08-13 从 51 维迁到 61 维，同时修了 `"policy"` → `"actor"` 的 KeyError。
- `microduck_roulade_env_cfg.py:46` 是**唯一开着它的任务**，注释：
  `# the mirror loss directly fights the sideways-collapse failure seen in run 2`。
- `microduck_velocity_env_cfg.py:28` 是 `ENABLE_SYMMETRY = False`；joy 继承 velocity，所以没开。

⚠️ **但要小心它的默认配置**：`SYMMETRY_CFG = {use_data_augmentation: False, use_mirror_loss: True,
mirror_loss_coeff: 0.5}`。而 ABEJA 的实测经验（Tech Blog，2025 advent）正好相反：

> "symmetric loss を入れると学習中に崩壊することが多く、augmentation のみ利用するのが良さそうでした"
> （加 symmetric loss 时训练经常崩，只用 augmentation 比较好）

所以如果要上，**先用 `use_data_augmentation=True, use_mirror_loss=False`** —— 既拿到双倍样本，
又不引入会崩的辅助 loss。这条与 roulade 的用法相反，需要单变量验证。

### 候选 4：参考轨迹 + 残差动作（最重，但最可能一次成功）

arXiv 1903.01390（Sim-to-Real Transfer for Biped Locomotion）的做法：

> "we use a reference trajectory of robot **stepping in place** … The action of the policy is to
> apply adjustment to the reference trajectory: `q_target = q_ref + δ·π(s)`, δ = 0.2 (backward) / 0.3"

而且原文特意写明 **"the reference trajectory does not need to be dynamically feasible, as tracking
our stepping-in-place reference trajectory causes the robot to fall immediately"** —— 它只是给策略
一个「抬脚」的初始方向，不要求自己能站住。

对我们是现成条件：joy 的相位已经从 `head_command` / `body_command` 通道喂进观测
（`ref_relu(sin φ)²` 那条），可以据此解析生成 `q_ref`（髋+膝各一条正弦）。代价是**改动作空间**，
会影响 ONNX 导出（`tools/export_mcu.py`）和 MCU 侧推理 —— 要动就要和部署一起动。

### 调参顺序（这条是纪律，不是改法）

两份资料都把顺序讲得很硬：

- Norofwave 的超参指南：**"先调任务奖励，再调正则惩罚：确认策略能完成任务后再加惩罚项；
  惩罚项权重从小开始 0.01–0.05，观察是否抑制主任务学习"**
- Menlo 的 reward engineering tutorial：**"start with the main task rewards first … then based on
  the behavior of the robot, add feet air time to encourage foot lifting … then to make it robust
  and smooth, regularization and safety"**

我们现在的顺序是反的：正则（`action_rate` −1.0）先于主任务（抬脚）成型。ar03 把正则退到 −0.30
是往回走的第一步；如果还不够，**下一步应该是加主任务奖励（候选 1+2），而不是继续调正则**。

---

## 4.6 ⚠️ ar03 实测：我的改动方向是错的，真正的病根是探索噪声幅度

### 4.6.1 结果：更稳、更静、抬脚更少

600/600 跑完，与旧 run 同 cfg、同 512 envs、同 8 s（`tools/compare_joy_runs.py` 输出）：

| gate | old(−1.0) | ar03(−0.30) | |
|---|---:|---:|---|
| `feet_peak_m` | 0.00619 | **0.00580** | 都 FAIL，**更差** |
| `pose_power_above_8hz_ratio` | 0.01206 | **0.04540** | 都 FAIL，**看起来更差 3.8 倍** |
| `knee_ac_rms_rad` | 0.1669 | **0.0519** | 膝盖绝对震动**降 3.2 倍** |
| `foot_ac_rms_m` | 0.00160 | **0.00099** | 脚更不动 |
| `step_period_s` | 0.647 | 0.320 | 周期缩短一半 |
| `fell_frac` | 0.0137 | 0.0059 | 更稳 |
| `joy_foot_rhythm_mean` | 0.487 | 0.455 | 略低 |

两条 FAIL 和旧 run 一样，而且数值都更差。**`8hz_ratio` 涨到 0.045 是比值陷阱**：分子（脚的
高频成分）和分母（总功率）同时下降，而分母降得更多 —— 绝对值 `foot_ac_rms` 已经从 1.6 mm
掉到 1.0 mm。这条 gate 在这个信号量级下不可解读（脚本已同时报 `*_ac_rms`）。

顺带否掉一个假设：`joy_balance` / `joy_head` **不是抬脚的代价**。
在 ar03 的 600 个迭代点上，`corr(joy_feet, joy_balance) = +0.996`、
`corr(joy_feet, joy_head) = +0.994` —— 三项几乎完全同向，测的是同一条学习曲线上的整体活性。
"抬脚会牺牲 balance" 这个想法是错的。

### 4.6.2 回归：σ 越大，抬脚越少（方向与我上轮的判断相反）

合并两个 run（iter ≥ 200，n=800）：**`joy_feet = 5.835 − 1.180·σ`，R² = 0.601**。
σ 每增加 0.1，`joy_feet` 掉 0.118 分。逐点看：

| iter | old σ / joy_feet | ar03 σ / joy_feet |
|---|---|---|
| 300 | 0.269 / 5.365 | 0.594 / 5.235 |
| 450 | 0.242 / 5.676 | 0.538 / 5.310 |
| 599 | 0.253 / 5.637 | 0.524 / 5.317 |

**σ 更大的 run，抬脚更少。** 我上一轮保住 σ 的做法，方向是反的。

### 4.6.3 机制：奖励容差只有 9 mm，而一个 σ 能推 28 mm

`joy_foot_rhythm` 是 `exp(−((z − z_target)/9mm)²)`。PPO 优化的是**带探索噪声的期望**，
而期望值对凹函数会被拉到峰值以下。用 `tools/probe_noise_vs_reward.py` 实测映射
（纯运动学：写关节角 → `mj_forward` → 读脚 site 高度，512 样本）：

| σ (rad) | 脚高 std (mm) | E@peak | E@stand | gap | **gap×12** |
|---:|---:|---:|---:|---:|---:|
| 0.10 | 3.33 | 0.886 | 0.585 | 0.301 | **3.62** |
| 0.15 | 5.45 | 0.759 | 0.541 | 0.219 | **2.62** |
| 0.20 | 7.96 | 0.624 | 0.483 | 0.142 | 1.70 |
| **0.25** | 10.83 | 0.507 | 0.420 | 0.086 | **1.04** |
| 0.30 | 13.96 | 0.415 | 0.363 | 0.052 | 0.62 |
| 0.40 | 20.63 | 0.295 | 0.274 | 0.021 | 0.25 |
| **0.52** | 28.34 | 0.219 | 0.210 | 0.009 | **0.11** |

`E@peak` = 策略精确瞄准目标时能达到的期望奖励（无噪声为 1.0）；`E@stand` = 完全不抬脚。
**`gap×12` 就是「抬脚」这个行为在训练时值多少钱。** σ=0.52 时只有 **0.11 分**（满分 12）——
梯度几乎不存在，这就是学不动的直接原因。

### 4.6.4 但「降 σ」没那么简单：目标限速把有效噪声封顶了

拿实测 `joy_feet` 反推「有效脚高噪声」（假设策略在瞄准目标，是上界）：

| run | 名义 σ | `joy_feet` | 反推有效脚高 std | **等效 σ** |
|---|---:|---:|---:|---:|
| old(−1.0) | 0.25 | 5.60 | 12.1 mm | **0.22** |
| ar03(−0.30) | 0.52 | 5.24 | 13.1 mm | **0.24** |

**两个 run 的等效噪声几乎一样（0.22 vs 0.24），尽管名义 σ 差了 2.1 倍。** 原因是
`JoySmoothPositionAction` 的限速：`target += clamp(0.25·(desired − target), ±0.08)`，
每控制周期 target 最多动 **0.08 rad = 4.4 mm 脚高**。而 σ=0.52 的相邻步差值
`√2 × 0.52 = 0.74 rad`，被这个 clamp 削到 0.08。**限速把大 σ 的噪声几乎全部吃掉了。**

所以：
- 把 σ 从 0.52 降到 0.25 **没有意义**（0.24 → 0.22，gap 1.04 → 1.04）—— 这正是 ar03 白跑的原因。
- **必须降到限速以下**才有效：σ ≈ 0.10–0.15 → gap 2.6–3.6 分（2.5–3.5 倍）。

结论是一个可以直接写进配置的数：**奖励容差 9 mm ÷ 灵敏度 54.5 mm/rad ≈ 0.165 rad。
`init_std` 应当取在这个量级（0.10–0.15），即「一个 σ 不超过一个奖励容差」。**

### 4.6.5 那么 `action_rate` 到底该多少

我上轮的推理在这里错了一环：`action_rate_l2 = 25σ²`（R²=0.98）这个测量是对的，
**但它压 σ 这件事对这个任务是有益的**，不是有害的。它不是"交白卷的税"，而是
"唯一在管探索幅度的东西"——只是管理方式太间接、太晚（σ 已经被推高才开始罚）。

所以正确做法不是放它，而是**把 σ 直接从源头设对**：

- `init_std`: **0.4 → 0.12**（按 §4.6.4 的原则）
- `action_rate_l2`: **留 −0.30**（上游亲写的值）。σ=0.12 时它的噪声地板是
  `−0.30 × 25 × 0.0144 = −0.108`，几乎为零，**这时它才真正在测"动作平不平滑"**而不是测噪声。

上一轮的四条「我错在哪」要再加一条：

5. **"σ 崩溃导致动作收小、所以抬脚少"这个因果链断了。** σ 收小确实让动作幅度降（`mean_action_acc`
   0.41），但 `joy_feet` 反而**更高**（5.60 vs 5.24）。真正的因果是反的：**σ 大 → 抬脚在期望上不值钱
   → 策略去优化更容易的项（balance/head）**。我把"症状"（动作收小）当成了"原因"。

---

## 5. 这一轮我错在哪（留档）

1. **上一版说"改法 0 = 把爬升放慢到 1500 轮"** —— 方向对，但机制说错了：我以为罚分在抑制幅度，
   实际它在抑制 σ。如果照上一版做，课程只是变慢，终点仍是 −1.0，σ 照样会被压死，多半重演。
2. **上一版说"站桩白拿 0.3501"** —— 那个 0.3501 用的是 `play=True` 的脚高 5.7 mm。
   训练 cfg 里站姿只有 0.1 mm，站桩实际拿 0.3694。数字接近纯属巧合，**推理用错了基线**。
3. **上一版说"改法 A：照抄 air_time 窗口是可行、推荐先做"** —— 测完才发现脚从不停留
   > 20 ms，`[0.125, 0.30]` 窗口恒为 0。**先测再改，这次省了一个空跑。**
4. **"被硬约束钳住的量超限先怀疑测量"这条再次生效**：`max_target_step_rad` 这次 1.41 → 0.08000。
5. **（§4.6 新增）"σ 崩溃 → 动作收小 → 抬脚少"这条因果链是断的。** σ 收小确实让
   `mean_action_acc` 从 0.96 降到 0.41，但 `joy_feet` 反而**更高**（5.60 vs 5.24）。
   真正的因果反过来：**σ 大 → 抬脚在期望上不值钱（gap 0.11 分）→ 策略转去优化更容易的项
   （balance/head，两者与 joy_feet 相关系数 +0.996）**。我把症状当成了原因，还据此做了一次
   1.2 小时的对照实验，方向是反的。
6. **还有一个测量局限要记住**：`probe_noise_vs_reward.py` 是纯运动学映射（写关节角 → forward），
   不含 PD 与限速，所以对 σ=0.52 高估了 2.2 倍（预估等效 0.52，实测 0.24）。
   **方向可用，绝对值不可直接用** —— 所以才要用实测 `joy_feet` 反推校准（§4.6.4）。

### 方法论小结

Hwangbo 那句 "tune by observing the first 100 iterations" 是**可执行的**，而且比看最终奖励
有效得多：**局部最优在 iter 60 就形成了**，看 600 轮的最终数字只会看到"它站得很稳"。
以后每轮训练的头 100 轮要单独拉表，专门看"有没有掉进站桩"。
