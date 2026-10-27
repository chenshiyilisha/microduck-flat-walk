# Microduck 技术深挖 · 第二层

> 这一层不看文档、不看媒体报道，全部结论来自直接读 `pollen-robotics/microduck_rl` 的源码。
> 读过：`microduck_constants.py`、`microduck_velocity_env_cfg.py`（45 KB）、`friction_dr_bam.py`、
> `add_backlash.py`、`backlash.py`、`pyproject.toml`、`scripts/testbench_sim2real.py`、
> `xl330_test_bench/config.json`，以及 `CLAUDE.md` 全文。

---

## 1. 一句话

**Microduck 的配方不是"一堆随机化参数"，而是五个源头的 sim2real gap 各自对应的五个补丁**：
执行器物理（BAM 电压模型）、机械间隙（齿隙铰链）、指令延迟（3–6 拍）、传感器误差（IMU 安装 + 编码器偏置）、
和指标污染（观测/reward 视图不一致）。每一个都能在代码里指到具体实现。

---

## 2. 执行器：为什么"理想 PD"在这里一定失败

`microduck_constants.py` 里那颗舵机的完整配置：

```python
_BAM_ACTUATOR_KWARGS = dict(
    motor_name="xl330",
    model="m6",
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=200.0,                 # 固件刚度（microban 用 125）
    vin_range=(6.5, 8.2),        # 每 env 启动时采样电池电压
    vin_drop_gain_range=(0.0, 0.2),  # 负载相关压降 V_drop = gain * Σ|τ|
    vin_min=6.0,                 # 压降后的硬下限
    delay_min_lag=3,
    delay_max_lag=6,
)
```

逐条翻译：

| 参数 | 值 | 为什么 |
| :--- | :--- | :--- |
| `model="m6"` | BAM 的 M6 执行器模型 | 电压控制律 + 反电动势 + 库仑/Stribeck/负载相关摩擦，而不是 `torque = kp·e - kd·qdot` |
| `kp_fw=200` | 固件位置环刚度 | 这是**真机固件里跑的 PD**，不是训练用的；microban 同款舵机用 125，鸭子用 200 |
| `vin_range=(6.5, 8.2)` | 2S 锂电的放电区间 | 电池从满电 8.2 V 掉到 6.5 V 的过程中，同样的指令输出力矩不同。**每 env 采一个固定值**，一次 episode 内不变 |
| `vin_drop_gain=(0, 0.2)` | 负载压降增益 | 15 个舵机同时发力时母线会被拉低。这个建模的是"越用力电压越低、越低越没力" |
| `delay_lag=3–6` @ 50 Hz | **60–120 ms** | 总线传输 + 固件处理 + 调度。这个量级在 800 g 的双足上足以决定稳不稳 |

摩擦随机化有个坑值得单独说：

```python
# friction_dr_bam.py 的注释
# 在 BAM 下 MuJoCo 的 dof_frictionloss 被清零（BAM 自己在 compute() 里算摩擦），
# 所以标准的 dr.dof_frictionloss 在这里是个静默 no-op。
```

所以官方写了个 `FrictionDRBamActuator`，把 `friction_scale` 直接乘在 BAM 的**摩擦预算**上（库仑 + Stribeck + 负载相关，也就是静摩擦/齿轮箱那部分——sim2real 不确定性的主要来源），而粘性摩擦项保持标称值。而且每 episode 先 reset 到 1.0 再采样，**严格非累积**。

> 这条对任何用 BAM 或类似执行器模型的人都成立：**你以为在随机化摩擦，其实那行代码什么也没做。**

---

## 3. 齿隙：把"编码器装在哪一侧"也仿了

真机齿隙总 2°（±1°）。实现方式是给每个舵机串一个**不受驱动的被动铰链** `passive_<joint>_backlash`，伺服关节是电机输出端，被动铰链是它与连杆之间的间隙，连杆角 = 两者之和。

关键在 `BacklashEncoderBamActuator`：

```python
def get_command(self, data) -> ActuatorCmd:
    cmd = super().get_command(data)
    pos = cmd.pos + data.joint_pos[:, self._backlash_joint_ids] * self._backlash_mask
    return dataclasses.replace(cmd, pos=pos)
```

因为真舵机的磁编码器装在齿隙的**输出侧**，固件位置环闭合的是 main + backlash。所以当伺服在死区里"空转"时，它测到的位置不变、PD 误差不变——这正好复现了真机的行为。

两个细节很讲究：

- **`cmd.vel` 故意留在电机侧**。注释写得很清楚：vel 在 BAM 里驱动反电动势和摩擦，那是转子物理，不是编码器派生的固件信号。混在一起就错了。
- **`joint_pos` / `joint_vel` 观测也穿过齿隙读**（`backlash.py`）。理由在 CLAUDE.md 里一句话：**如果观测被重映射到某个传感器视图，那么同一个物理量的跟踪 reward 必须测同一个视图，否则策略会因为"纠正它看到的东西"而被惩罚。**

这个实现有个额外好处：观测/动作维度完全不变，所以 ONNX 导出和运行时都不用改。可以拿同一份代码 A/B 对比"有齿隙 vs 无齿隙"。

---

## 4. 域随机化全表（源码实际值）

`microduck_velocity_env_cfg.py` 顶部把开关全摊开了，这个比任何论文都清楚：

| 项 | 状态 | 范围 / 值 |
| :--- | :--- | :--- |
| 质心偏移 | ✅ 开 | ±3 mm 起步，课程**爬升到 ±8 mm** |
| 头部组件质心 | ✅ 开 | ±3 mm，逐 body 施加（neck→yaw_roll_motion→head shell） |
| 质量 + 惯量 | ✅ 开 | 0.95–1.05（±5%，两者联动） |
| 关节摩擦 | ✅ 开 | 0.9–1.1（乘 BAM 摩擦预算） |
| 反射转子惯量 | ✅ 开 | 0.9–1.1 |
| 速度推挤 | ✅ 开 | ±0.3 m/s，每 3–6 s 一次 |
| IMU 安装误差 | ✅ 开 | ≤6°，随机轴（零均值） |
| 编码器偏置 | ✅ 开 | ±0.015 rad = **±0.86°/关节**，每 env 恒定 |
| **kp 随机化** | ❌ **关**（注释：`Was True`） | 0.85–1.15 |
| **kd 随机化** | ❌ **关**（`Was True`） | 0.9–1.1 |
| 关节阻尼 | ❌ 关 | 0.9–1.1 |
| 初始姿态倾斜 | ❌ 关 | ±10° pitch / ±5° roll |
| 对称性镜像损失 | ❌ 关 | — |

三个反直觉的点，都是踩过坑才有的：

1. **推挤从 ±0.5 降到 ±0.3。** 注释：「比最大行走速度（0.4）还大的加法踢，每 3–6 秒来一次，训出来的是一个永久紧张的跌倒恢复步态。」±0.3 既保留鲁棒性，又让"更从容的步态"成为最优解。
2. **kp/kd 随机化被关掉了。** 这是教科书里的标准做法，他们开了又关——说明在这台机器上，随机化固件刚度会破坏别的什么东西（大概率是让策略无法依赖任何刚度假设，从而学不到精细的接触控制）。
3. **IMU 误差是零均值随机轴，不是固定俯仰。** 真板上那 ~5° 的系统性俯仰偏差**不在这里修**，而是在运行时用 `imu-pitch-offset` 从源头校正。训练只教"容忍任意方向的安装误差"，不教"补偿一个特定偏差"。

---

## 5. 指令设计：三个"不做课程"的决定

| 指令 | 范围 | 说明 |
| :--- | :--- | :--- |
| `lin_vel_x` | ±0.4 m/s | |
| `lin_vel_y` | ±0.3 m/s | |
| `ang_vel_z` | **±1.0 rad/s** | |
| 原地转 | **15% 的 env 强制** `lin=0, |ang|∈[0.4, 1.0]` | |
| 站立 | 2% 起步，课程爬升 | |

- **范围固定，不做课程放大。** 因为之前放大到 `ang ±2.0` 超出机器人能力，reward 和 episode 长度在第 1000 轮后开始双降（"追不上的课程"）。
- **±1.0 rad/s 是转折点**：「这让转向第一次变得可学。」
- **15% 原地转是补数据分布。** 2026-07 的审计发现：独立均匀采样的结果，原地转只占约 2% 的数据 → 等于没训练过。

---

## 6. 网络与 PPO（全表）

```python
actor  = RslRlModelCfg(hidden_dims=(512, 256, 128), activation="elu",
                       obs_normalization=True,
                       distribution_cfg={"class_name": "GaussianDistribution",
                                         "init_std": 1.0, "std_type": "scalar"})
critic = RslRlModelCfg(hidden_dims=(512, 256, 128), activation="elu",
                       obs_normalization=True)
```

| 超参 | 值 |
| :--- | :--- |
| 学习率 | 1e-3，`adaptive` 调度，`desired_kl=0.01` |
| γ / λ | 0.99 / 0.95 |
| clip / entropy | 0.2 / 0.01 |
| epochs / minibatches | 5 / 4 |
| 每 env 采样步数 | **24** |
| 最大迭代 | **50,000**（× 24 步 × 4096 env ≈ 49 亿步） |
| save_interval | 250 |
| 梯度裁剪 | 1.0 |

不算复杂——512-256-128 的 MLP，标准 PPO。**复杂度全在环境和执行器模型里，不在算法里。** 这个取舍值得记住：他们没有上 Transformer policy、没上蒸馏、没上多阶段训练。

---

## 7. 地形：参数是被机器人物理限制逼出来的

| 子地形 | 占比 | 参数 |
| :--- | :--- | :--- |
| 平地 | 25% | — |
| 金字塔台阶 | 25% | 台阶高 **0–1.5 cm**（默认是 10 cm） |
| 随机网格 | 30% | 网格 0.45 m，高度 0–1 cm |
| 缓坡 | 20% | slope 0.03–0.10（约 **1.7°–5.7°**） |

「机器人只能抬脚 1–2 cm，所以台阶封顶 1.5 cm。」

还有两个工程坑：

- **倒金字塔台阶被删了**，因为它把 `env_origin_z` 设成坑底（负值），reset 时机器人会在 `z ≈ −0.10 m` 出生——**直接穿地**。
- **随机网格的 `grid_width` 从 0.12 改到 0.45**：0.12 在 8 m 见方的地块上是 66×66 = 4356 个 box，全局约 26 万个 → OOM。0.45 降到约 1.7 万个。
- **地形接触柔化**：所有地形 geom 的 `solref` 从 0.02 加倍到 0.04，阻尼掉台阶边缘的接触法向不稳定（会在求解器里炸出脉冲式 NaN 力）。

---

## 8. 标定台：单个舵机的 sim2real A/B

这是整个仓库最被忽略、但对复刻党最有用的东西。`src/mjlab_microduck/robot/xl330_test_bench/` 是一台**只有一个 XL330 的台架**（Onshape 模型 + 配重块 + 摆臂），配套脚本能：

```bash
# 1) 仿真里跑：同一份 ONNX、同一串目标角
uv run python scripts/testbench_sim2real.py --mode sim  --onnx policy.onnx --out sim.npz
# 2) 真舵机插 USB，跑同样的序列
uv run python scripts/testbench_sim2real.py --mode real --onnx policy.onnx --out real.npz \
    --port /dev/ttyUSB0 --motor-id 1
# 3) 画对比曲线
uv run python scripts/testbench_sim2real.py --compare sim.npz real.npz --out-plot comparison.png
```

协议：目标角在 ±80° 内随机，每 4 秒换一个，控制 50 Hz（`decimation=4 × timestep=0.005`），日志 200 Hz。

**它的意义：在训整机之前，先单独验证"你那颗舵机的 BAM 参数标定对不对"。** 如果单舵机的 sim/real 轨迹对不上，整机一定对不上。这是一个可以隔离变量的最小闭环。

顺带一个实用数字：Dynamixel 的 `present_velocity` 返回的是**原始 tick**，不是弧度。换算 `rad/s = ticks × 0.229 × 2π/60 ≈ ticks × 0.02398`。这种细节不注意就是"仿真里好好的，真机速度差 40 倍"。

---

## 9. 依赖地狱：三个专门写的 override

`pyproject.toml` 里的 `[tool.uv] override-dependencies` 是血泪：

```toml
# bam 把 protobuf 钉在 <4.0，会导致 onnx 一路降级到 1.17.0（没有 wheel，只能源码编译）
"protobuf>=4.0,<7.0",
# 保 onnx 在 1.20.1+
"onnx>=1.20.1",
# bam 依赖 PyPI 上的假包 zmq==0.0.0，wheel 缺 .dist-info → 全新安装（HF Jobs）直接失败
"zmq ; python_version < '3.0'",
```

外加一条明确的警告：**不要 override mujoco**——之前有人这么干，把 mujoco 压到 3.4.0，缺少 `mjDSBL_MULTICCD`，`mujoco-warp` 一 import 就崩。

还有：`requires-python = ">=3.12, <3.13"`，因为 BAM 锁 `<3.13`；曾经因为上界浮动，HF Jobs 挑了 3.13.14 直接跑不起来。

**如果你打算复现这个环境，别自己拼依赖，直接用他们的 `uv.lock`（223 KB，锁死了全图）。**

---

## 10. 核心问题：这套配方能搬到别的机器人上吗

分开回答，因为答案不一样。

### 能直接拿走的（平台无关）

| 东西 | 为什么能带走 |
| :--- | :--- |
| **BAM 执行器库** | `Rhoban/bam` 是独立项目，支持多种舵机型号（M4/M6）和多种电机，microduck 只是其中一个调用者 |
| **`add_backlash.py` 后处理器** | 它的逻辑是"给每个受驱动关节插一个被动铰链"，跟具体机器人无关，改个正则就能用 |
| **`FrictionDRBamActuator`** | 薄子类，只加了 per-env 的 `friction_scale`。任何用 BAM 的机器人直接可用 |
| **`testbench_sim2real.py` 的方法论** | 单执行器 sim/real A/B 是通用做法，换个台架模型即可 |
| **mjlab + PPO 这套脚手架** | mjlab 本身就是通用框架（MuJoCo Warp + rsl_rl） |
| **CLAUDE.md 里的所有不变量** | 非累积 DR、obs/reward 同视图、ONNX 烘焙归一化、冒烟测试、先验证物理再训练——全是平台无关的纪律 |

### 带不走的（绑定这只鸭子）

| 东西 | 为什么 |
| :--- | :--- |
| **61 维观测契约** | 48 维本体感知的具体构成 + 关节顺序（左腿 0–4 / 头 5–8 / 右腿 9–13）完全是这只鸭子的拓扑 |
| **14 维动作空间** | 同上 |
| **HOME 姿态那组角度** | `hip_pitch -0.4579 / ankle 0.4530 / neck_pitch 0.3491`……这是为了让质心正好落在踝轴上方。换机器人得重新求 |
| **所有 DR 范围** | ±3 mm CoM、±0.86° 编码器偏置、1.5 cm 台阶——全部是 800 g / 25 cm / 抬脚 1–2 cm 推导出来的 |
| **reward 权重** | 跟小步幅、支点式转向强相关（连 `foot_slip` 都特意压到 -0.1，因为更强的约束会禁掉这台机器的转向方式） |
| **`kp_fw=200`** | 这是固件常数 |

### 所以迁移的真实工作量

如果目标是**另一台舵机驱动的小型双足**，我的判断是：

```
1. MJCF 建模 ────────── ████████████ 最难（质量/惯量必须准，否则后面全白干）
2. 执行器标定 ──────── ████████ 用 testbench 那套跑 sim/real 对齐
3. obs/action 契约重定义 ███ 机械工作
4. reward 重调 ─────── ██████████ 玄学部分，文档说 2–5 轮迭代
5. DR 重标定 ───────── ██████ 从保守值开始，看真机
```

**结论：工具链和方法论可以 100% 复用，参数一行都不能抄。**

这其实也是它最大的价值——它给你的不是"一只会走的鸭子"，是**一份带完整踩坑记录的 sim2real 作业流程**。鸭子随时可以换，流程很难得。

---

## 11. 飞特（HD-1910）路线的真实代价

上一份报告里说"约 2900 元能把硬件搞出来"。深挖之后要补一句更重要的：**硬件只是第一步，重训才是真成本。**

为什么必须重训，不是改改参数就行：

| 差异 | 后果 |
| :--- | :--- |
| 总线协议不同 | `robotd` 用的 Dynamixel 协议要换成飞特的；官方 `microduck` 运行时直接跑不了 |
| 电压工作点不同 | XL330 额定 6 V 实跑 6.6–8.2 V（超压 37%）；HD-1910 额定 4–8.4 V，满电正好顶格 |
| **BAM 模型没有 HD-1910** | 这是最硬的墙。整个执行器模型（`model="m6", motor_name="xl330"`）得重新辨识，或者至少用 M4 近似 + 重标 `kp_fw` |
| 力矩大 2.5 倍 | 同样的 `kp_fw` 下响应完全不同，策略学到的接触动力学整体失效 |
| 关节行程/零位可能不同 | HOME 姿态和软限位都得重算 |

所以飞特路线 = **换硬件 + 换协议 + 重辨识执行器 + 重训全部策略 + 重调 reward**。社区里"已装机并站起"的那台，走的就是这条路。

**如果你没有 CUDA GPU，这条路线走不通**——`microduck_rl` 训练必须走 MuJoCo Warp（CUDA），没有 GPU 只能上 Hugging Face Jobs 租。

替代判断：**要么买整机（399 美元，省掉全部重训），要么走原版 XL330 + 开源 HAT（贵，但策略现成）。飞特路线只在"你本来就想学 RL 训练"的前提下才划算。**

---

## 12. 补三个上一份没说的事实

1. **`microduck_rl` 的创建时间是 2025-12-06**，比机器鸭预售（2026-08-27）早了 8 个多月。也就是说**训练栈是先做出来的，产品是后包装的**——这也解释了为什么它的工程规范成熟得不像一个消费级新品。
2. **仓库里有 `microduck_emotions` 之外的情感设计历史**（git tag `workshop-2026-10-07`），14 种情绪每种都是"一段动作关键帧 + 一段配套声音 + 精确到 0.1 s 的采样"一起设计的。鸭子"倒下"（devastated）那个情绪，声音要延后 0.3 s 才播。
3. **主仓 `microduck` 有 47 个 open issue、`microduck_rl` 有 49 个**——它不是"发布即冻结"的项目，还在高频迭代（主仓最后一次 push 是 2026-10-22，昨天）。**现在 fork 会在几周内落后一大截。**
