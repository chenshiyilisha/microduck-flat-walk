# `continuous_joy.onnx` 实测：它不是在走，但它的奖励结构能治我们的站桩

> **术语（2026-10-24）**：下文「Duckverse」= `ros-claw/microduck`（6★，纯仿真未上真机）。
> 这份 ONNX 和它的训练配方**都不是 Pollen 官方发布的** —— `pollen-robotics/microduck_rl`
> 全文 `joy` 出现 0 次。旧版称它「官方 joy」，已全文改名。

> 被测对象：`ros-claw/microduck`（Duckverse）的 `policies/continuous_joy.onnx`
> （794 KB，sha256 `dc09fc26…3de41`），元数据 `run_path = logs/rsl_rl/microduck_joy_smooth_pd/
> 2026-10-03_23-35-37_continuous-smooth-pd-v1/model_300.pt`。
> 全部数字来自本机实测，命令与脚本见 §7，可一键复现。

---

## 1. 结论先放

1. **它不是"会走"，它是"原地踏步"**。8 秒净位移 **14 mm**、平均 vx **−0.001 m/s**。
   我上一轮说"拿它量真实速度、对照我们的 0.035 m/s"是**错的**，已在
   `microduck-mjlab-GPU与三个新仓库.md` 里划掉。
   —— 它的命令通道是**位置反馈**（`twist = clamp(-2·pos, ±0.15)`），加上权重 100 的
   `joy_drift` 罚位移。**设计上就抗拒平移**，推不动。
2. **但它在我们这套植物上确实会踏步，而且踏得非常准**：周期 **0.860/0.870 s**
   vs 指令 1/1.15 = **0.870 s**（误差 1%），左右**交替**（峰间 0.420 s vs 半周期 0.435 s），
   **双足同时离地 0%**（不是蹦），8 秒**不摔**。BAM 植物（kp200 / 7.4 V）也照样不摔。
   —— 补测：按上游自己的 10 条门控（`joy.py:report`）+ Duckverse 物理契约（5 kHz / 50 Hz /
   `joint_vel_delay=1`）跑，**9/9 全 PASS，`joy_passed=True`**（见 §2.0）。
   这不是"我觉得它在踏步"，是**上游的验收函数判它通过**。
3. **最有价值的是负对照**：同一份 harness，只把相位时钟切断（`--no-clock`），
   这只策略**变成一尊完美的雕塑**——抬脚 0 mm、vx 峰值 0.001 m/s、偏航范围 0.07°、
   高度 117.1 mm。**说明"踏步"这个行为 100% 由指令相位驱动**，也说明我们的
   61 维契约 + 目标递推 + 植物这套链路是**对的**（错了的话时钟切不切不会有差别）。
4. **它的奖励结构让"踏步"成为"站桩"的严格超集**：权重 12 的抬脚项对站桩给
   **0.007 分（≈0）**，而踏步时 `balance`/`head`/`pose` 照样能拿满 ——
   **往上走不用拿任何别的分去换**，地形里没有局部最优。
   我们那张表里"走"要拿 pose/clearance/rate 的分去换 track，中间一定更差，
   所以站桩成了局部最优。这是"我们没有会走的策略"的**结构性修法**，
   比单纯加 `forward_progress` 更硬。

---

## 2. 实测数据

### 2.0 先对齐 Duckverse 验收口径（事后补的，之前那套是我自己编的）

上游 `src/microduck_lab/parkour/joy.py:report()` 本来就写了完整的门控，
比我上一轮自编的"抬脚 >10 mm / 周期 0.87±0.05 / 双足离地 <5%"严谨得多，
而且多出三个我完全没想到的维度：

- `target_rate_rms < 6`（目标速率均方根）—— 罚目标抖
- `max_target_step < 0.2 rad`（单步目标跳变）—— 罚目标突跳
- `pose_power_above_8hz_ratio < 0.01`（8 Hz 以上能量占比）—— **用 FFT 检测颤振**，
  这是"能站住/能踏步"和"在抖"的分界线

Duckverse `scripts/probe_joy_policy.py` 还钉死了物理契约：`physics_step_s=0.0002`（5 kHz）、
`controller_hz=50`、`joint_vel_delay=1`、target conditioner `alpha=.25 / max_step=.08 rad`。
我上一轮用的是 1 ms 物理步长、没做延迟——**数字不可直接比**。

按 Duckverse 口径重测的结果：

| Duckverse 门槛（`joy.py:report`） | 判定 | 实测 |
|---|---|---|
| `duration_s >= 3.5` | PASS | 7.20 s |
| `min_upright > 0.9` | PASS | 0.9946 |
| `max_drift < 0.08 m` | PASS | 0.0326 |
| `both feet_peak > 0.008 m` | PASS | 16.36 / 17.34 mm |
| `end_upright > 0.95` | PASS | 0.994 |
| `foot_support` | PASS（近似） | 至少一脚在地 |
| `target_rate_rms < 6` | PASS | 2.597 |
| `max_target_step < 0.2 rad` | PASS | 0.080 |
| `pose_power_above_8hz < 0.01` | PASS | 0.00051 |

→ **9/9，`joy_passed = True`**。唯一没照抄的是 `foot_support`（定义在 `parkour/world.py`，
未取），用"脚 site 高度 < 8 mm"近似，已在脚本里标明是近似。

**`joint_vel_delay` 的实测影响很小**：同条件只切这一个开关，净位移 17.0 vs 14.8 mm、
抬脚 16.4/17.3 vs 16.5/16.6 mm、`target_rate_rms` 2.597 vs 2.496 —— 都在门槛内。
20 ms 的速度延迟不足以改变这个策略的行为。（这条是测出来的，不是推的。）

> ⚠️ 修正：下面的表是 **1 ms 物理步长**测的（抬脚 14.8/15.3 mm）。换成 Duckverse 0.2 ms 后是
> **16.36/17.34 mm**。定性的（周期、交替、不摔、原地踏步）全都不变，但**毫米数以 2.0 表为准**。
> 另外第一次加 `--joint-vel-delay` 时开关其实**没生效**（我在 `mj_step` 之后才更新缓冲，
> 取到的值和当步相同，两组结果逐位一样）—— 是"两组数字完全相同"这个异常暴露的。

### 2.1 三组条件对照（1 ms 步长，仅用于定性比较）

三组条件，同一份脚本、同一份 scene.xml、同一个初始状态。

| | servo 植物（匹配） | BAM 植物（kp200/7.4 V） | **无时钟（负对照）** |
|---|---:|---:|---:|
| 摔倒 | 否 | 否 | 否 |
| 最低高度 | 114.9 mm | 114.5 mm | 117.1 mm |
| 平均 vx | −0.0011 | −0.0016 | −0.0001 |
| 峰值 \|vx\| | 0.084 | 0.065 | **0.001** |
| 8 s 净位移 | 14.3 mm | 19.4 mm | 6.7 mm |
| 偏航范围 | 11.0° | 8.2° | **0.075°** |
| 左脚踏步周期 | **0.860 s**（8 峰） | 0.880 s（8 峰） | 无峰 |
| 右脚踏步周期 | **0.870 s**（9 峰） | 0.860 s（9 峰） | 无峰 |
| 左脚抬升（峰值中位） | **14.8 mm** | **8.2 mm** | **−0.1 mm** |
| 右脚抬升 | **15.3 mm** | **10.0 mm** | **+0.6 mm** |
| 左右峰间隔 | 0.420 s | 0.420 s | — |
| 双足同时 >3 mm | 0.0% | 0.0% | 0.0% |

三件事值得单独说：

- **周期误差 1%**：这是**开环时钟**（指令里的 `sin/cos` 由 `2π·1.15·t` 直接算出来），
  策略只是"跟着做"。它做到 0.86–0.88 s，说明它真的把相位吃进去了。
- **抬升只有指令的 60%**：奖励里的目标是 `0.0005 + 0.024 = 24.5 mm`，实测 14.8/15.3 mm。
  换成 BAM 植物掉到 **8.2/10.0 mm（指令的 33–41%）** ——
  **BAM 的软执行器把抬脚砍掉一半**。这直接说明"训练用 servo、部署换 BAM"会掉行为，
  和上游"这些模拟权重不能称作 BAM/硬件合格策略"的免责声明对得上。
- **它原地不动不是因为不会走，是因为被罚**：`joy_drift` 权重 **100**，
  `-(pos² + 0.05·vel²)`。站着不动这项是 0（不吃罚），移动反而吃罚。

---

## 3. 它到底是什么任务（源码级）

`training/continuous_joy.patch` 里 `make_microduck_joy_env_cfg` 只做了五件事：

```python
# 1) 把速度指令全部清零 —— 根本没有"走多快"这个目标
cfg.commands['twist'].ranges.lin_vel_x = (0., 0.)
cfg.commands['twist'].ranges.lin_vel_y = (0., 0.)
cfg.commands['twist'].ranges.ang_vel_z = (0., 0.)

# 2) 把训练目标换成"按 1.15 Hz 时钟抬脚"
cfg.rewards['joy_feet']    = weight 12.0    # 抬脚节拍
cfg.rewards['joy_balance'] = weight  5.0    # 高度 117 mm + roll/pitch/yaw≈0
cfg.rewards['joy_head']    = weight  3.0    # 头跟着指令摆
cfg.rewards['joy_drift']   = weight 100.0   # 别跑   ← 主导项

# 3) 把原来的速度奖励全删掉
for name in ['track_linear_velocity','track_angular_velocity','air_time',
             'foot_clearance','foot_swing_height','head_pose_tracking',
             'head_pose_bias','body_pose_tracking']:
    cfg.rewards.pop(name)
cfg.rewards['pose'].weight = .15            # 1.0 → 0.15

# 4) 相位通过"头/身姿态指令"这两个观测通道进策略（不是隐藏通道）
#    head_command 4 维、body_command 6 维、twist 3 维 → 3+3+14+14+14+3+4+6 = 61
```

台阶形状是关键：

```python
target = 0.0005 + 0.024 * relu(±sin p)**2      # 24.5 mm，半波整流
reward = exp(-((height - target)/0.009)**2).prod(-1)   # 两只脚相乘，std 仅 9 mm
```

**训练量小得惊人**：`max_iterations` 三个版本分别是 **600 / 400 / 200**，
lr 3e-4→2e-4，`init_std 0.4`，2048 envs。对比 Hannes 的 12,195 轮，
对比我们 2000 轮只训出站桩。

---

## 4. 为什么这套结构能治站桩（手算，标注了哪部分是估算）

先看**站桩能拿到什么**。两套奖励下，一个"完全不动、姿态完美"的机器人：

| 项 | 我们的表（满分 ≈12.0） | joy 的表（满分 ≈20.2） |
|---|---:|---:|
| 任务定义项 | `track` 0.40（\|cmd\|≈0.2 时） | `joy_feet` **≈0.007** |
| 姿态类 | head 2.00 + upright 1.99 + turn 1.97 + pose 1.00 | pose 0.15 + `joy_balance` ≈5.0 |
| 其他 | — | `joy_head` ≈1.8（头不动，指令本身 ≤0.24 rad） |
| `joy_drift` | — | 0（站着不动不罚） |
| **合计** | **7.36（61%）** | **≈7.0（35%）** |

（joy 那一列：balance/pose 按 §2 实测的 117.1 mm、roll/pitch/yaw≈0 算，是**估**；
`joy_feet` 是算出来的而不是估的，见下。）

**仅看"35% vs 61%"会得出错误的结论**。真正决定行为的是两件事：

**① 主导项（权重 12 的 `joy_feet`）对站桩给 0.007，等于 0。**

```python
exp(-((0 - 0.0245)/0.009)**2) * exp(-((0 - 0.0005)/0.009)**2)   # 两脚相乘
= exp(-7.41) * exp(-0.0031) = 6.0e-4                            # × 权重 12 = 0.007 分
```

**② 关键是：踏步不是"用别的分换来的"，它是站桩的严格超集。**

`joy_balance` / `joy_head` / `pose` 这三项在踏步时**照样能拿满**（重心高度 117 mm、
头照样能跟指令摆、姿态照样能保持），所以踏步得分 = 站桩得分 **+ 最多 12 分**，
**不存在取舍**。上帝视角看这个地形**没有局部最优**：往上走的每一步都白赚。

反过来看我们的表，为什么站桩成为局部最优：

| | 站桩 | 走起来 | 差 |
|---|---:|---:|---:|
| `track`（权重 2） | 0.40 | 最多 2.0 | **+1.6** |
| `pose`（走时 std 收紧） | 1.00 | ≈0.7 | −0.3 |
| `foot_clearance` / `rate` / `slip` | 0 | 吃罚 | −0.5~−1 |
| `air_time`（权重 3） | 0 | 落地才给 | +0~3 |
| **合计** | **7.36** | 12.0（且**必须途经 4~6**） | |

也就是说：**我们的表里"走"要拿别项的分去换，而中间那段一定更差**——PPO 不会先掉分。

还有两处机制上的细节，缺一不可：

1. **我们的 `phase` 乘了 `moving()`**（`train_ppo.py:609`，`|cmd|>0.01` 才有相位）：
   站桩时相位项归零，抬脚项直接变成"随便"，站着不吃罚。joy 的相位**无条件**，
   0.8 s 淡入后一直有。
2. **exp 的 std 差 2.2 倍**：我们 `WIDTH=0.02` 对 2 cm 目标，站桩还有
   `exp(−sin²)≈0.37`；joy 用 **0.009** 对 24.5 mm 目标，站桩是 **6e-4**。
   再加"两脚相乘"，只要有一只脚没按节拍抬起，整项归零。

> ⚠️ 一个必须承认的弱点：站桩点距离目标 2.7σ，**该点的梯度已经很小**
> （`d/dh ≈ 4e-4 /mm`）。所以 joy 也不是"梯度天然指向踏步"，
> 它靠的是**值本身够低 + 探索噪声够大**（`init_std=0.4 rad`）：
> 随机抖动一旦抬到 8–12 mm，立刻从 0.007 分跳到 0.9–4 分。
> 这正对应 DuckEMW 病历里那句"`air_time` 阶跃无梯度"——
> **它们的解法不是加梯度，是把站桩那端的值压到 0，让"抖出去"一定变好。**

→ 这就是我们和"会走"之间那道坎的**结构性解释**：不是奖励漏了哪一项，
是**站桩在我们表里仍然拿 60% 的分，在他的表里拿 3%**。

---

## 5. 负对照为什么重要（这一轮的方法论收获）

我原本的计划是"跑一下看会不会走"，但"会不会走"这种事**看错的风险极高**
（抬个脚、晃动一下都像在走）。所以加了 `--no-clock`：

> 同一份代码、同一个初始状态、同一个模型，**只把 `head_command` / `body_command`
> 六个通道置零**（相位信息就进不去了）。

结果：抬脚 **0 mm**、峰值 vx **0.001 m/s**、偏航范围 **0.075°**、高度 117.1 mm。

- 如果切断相位它**还在踏步**，说明我读错了契约（相位不是从这两个通道进的），
  那 §2 里所有"它在踏 1.15 Hz"的结论都无效；
- 现在它**立刻静止**，说明相位通道、obs 拼接顺序、执行器映射**全对**。

顺带得到一件副产品：**这就是"一个能站住的策略"该有的样子**——
117.1 mm、脚在 0、8 秒偏航漂 0.07°。我们自己的 checkpoint 站桩时
`v≈0.02–0.03`、`clearance=0`，可以拿这组数当参照。

> 反思：这一轮我先怀疑"抬脚 15 mm 是不是测错了"，差点去查 site 定义。
> 判据是——**先做负对照，不先怀疑测量**。负对照跑一次 8 秒，比翻半小时 XML 便宜。

---

## 6. 为什么它仍然不能替代"会走"（限制，别高估）

1. **它不会平移**，而且不是"还没学会"，是**目标函数不允许**。
   要它走，必须改奖励（加 `forward_progress`、把 `joy_drift` 的权重降下来或改成
   "有指令时才罚"）。改完就得重训，不能直接微调这只。
2. **它是 servo 训练的**。同一只策略在 BAM 植物上抬脚从 15 mm 掉到 8–10 mm
   （⚠️ 这组是 1 ms 物理步长测的，**没有按 Duckverse 5 kHz 重测**；方向可信，毫米数不可直接比）。
   我们最终要跑 BAM（要对齐真机舵机），这块**必须重训**，不能照搬。
3. **相位是外部喂的**。它是"命令跟随器"，不是"自主节律发生器"。
   真机部署必须自己算 `2π·1.15·t` 并按 `joy_target_alpha=0.25`、
   `±0.08 rad/20 ms` 做目标递推 —— 这两个数写在 ONNX metadata 里，少一个行为就变。

**它的正确用途是 teacher + 配方，不是终点。**

---

## 7. 可复现

新增 `tools/probe_joy_policy.py`（Windows 可用；上游 `scripts/infer_policy.py`
第 13 行 `import termios`，Linux/macOS 专用，Windows 直接 ImportError）。

> 上游另有一个 `scripts/probe_joy_policy.py`（2.3 KB），但它是给 `microduck_lab.parkour`
> 那套**游戏关卡**（`build_level` / `JoyDance`）用的，跑的是关卡里的机器人，不是
> `microduck_rl` 的 mjlab 植物。**验收门槛（`joy.py:report` 那 10 条）可以照抄，
> 运行框架不能直接用。**

```bash
# 【Duckverse 契约】5 kHz 物理 / 50 Hz 控制 / joint_vel_delay=1（默认值已改成这套）
python tools/probe_joy_policy.py --onnx .upstream/policies/continuous_joy.onnx \
    --plant servo --seconds 8 --joint-vel-delay 1 \
    --json-out out/probe_joy_official.json

# 对照：关掉 20 ms 速度延迟
python tools/probe_joy_policy.py --onnx .upstream/policies/continuous_joy.onnx \
    --plant servo --seconds 8 --joint-vel-delay 0 \
    --json-out out/probe_joy_delay0.json

# BAM 植物（kp_fw 200，vin 7.4）
python tools/probe_joy_policy.py --onnx .upstream/policies/continuous_joy.onnx \
    --plant bam --vin 7.4 --kp-fw 200 --seconds 8 --json-out out/probe_joy_bam.json

# 负对照（切断相位时钟）
python tools/probe_joy_policy.py --onnx .upstream/policies/continuous_joy.onnx \
    --plant servo --seconds 8 --no-clock --json-out out/probe_joy_noclock.json
```

`--timestep 0.0002 --decimation 100` 是默认值，改它们会改变毫米级结果（1 ms 步长下抬脚
14.8 mm，0.2 ms 下 16.4 mm），比数的时候要同口径。

契约里每个数都有出处（写在脚本头部注释）：obs 顺序来自补丁里的
`tests/test_joy_cfg.py:10` 断言（⚠️ 早先这里写的 `:242` 是错的，那个文件总共 64 行）；
`head_command` 4 维 / `body_command` 6 维来自
`joy_head_command` / `joy_body_command` 的返回形状；`scale=1.0` + 默认偏置来自
`microduck_velocity_env_cfg.py:273` 与 `JointPositionActionCfg.use_default_offset`；
执行器 ±0.6405 来自 `joy_pd_spec`；相位与递推来自 ONNX metadata。

---

## 8. 下一步（按"能不能立刻做"排）

1. **零成本：用 `tools/probe_argmax.py` 的同一套做法，先算"站桩"在 joy 配方下的得分。**
   不训练、不装环境，把 §4 那张手算表变成实测（同一批 term 套 joy 权重）。
   判据：站桩总分必须显著低于"踏步"；否则说明我手算哪一项错了。
2. **移植 4 项 joy 奖励 + 时钟**（约 60 行；`self.foot[:,:,2]` 和 `self.clock` 我们已经有了，
   只差把 `moving()` 门控去掉、换成 1.15 Hz + 半波整流目标 + 9 mm std + 两脚相乘）。
3. **600 iter 看是否出现踏步**。验收判据用**上游那 10 条**（`joy.py:report`，见 §2.0），
   不是"看起来在动"，也不是我自编的那套：
   `duration≥3.5 s`、`min_upright>0.9`、`max_drift<0.08 m`、`双足峰值>8 mm`、
   `结束 upright>0.95`、`有脚着地`、`target_rate_rms<6`、`max_target_step<0.2 rad`、
   `8 Hz 以上能量占比<0.01`。其中**最后一条最容易漏**：踏步和颤振在波形上很像，
   但 8 Hz 能量占比会把它们分开。
4. **有了踏步再加 `forward_progress`**。这时"第一步"已经跨过去，
   不用再从 7.36 掉到 4 再爬回来 —— 这也是 Duckverse 自己的路径
   （先 seed `alpha_walking`，再训 joy，不是反过来）。
