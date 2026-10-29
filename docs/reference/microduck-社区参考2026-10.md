# 第二轮社区参考（2026-10-23）：上游代码是公开的，而且国内整机只要 ¥2234

上一轮我们主要靠 MJCF + Rust 源码 + 文档反推上游配置。这一轮发现**上游训练代码本身就是公开的**，  
所以很多"推断"可以直接改成"引用原文"。同时找到一份国内实机复刻的完整成本清单，把我们之前的  
硬件预算砍掉一半以上。

检索方式：GitHub API（`/search/repositories` + `/git/trees`），不信搜索引擎给的仓库名。

## 一、成本：我们的估算错了 2.4 倍

`kissqy/Microduck-kissqy`（116★，飞特 HD1910 实机复刻，含购物链接与订单日期 2026-10-14）：

| 项                    | 金额           |
| -------------------- | ------------ |
| 鸭子本体（含备料）            | ¥2205.43     |
| HAT 整板（自制 PCB，元器件分摊） | ¥16.72       |
| IMU 整板（自制 PCB）       | ¥12.33       |
| **整机合计**             | **¥2234.49** |

其中最大的一项直接推翻了我之前的算盘：

| 件                                  | 单价         | 数量      | 小计           |
| ---------------------------------- | ---------- | ------- | ------------ |
|                                    |            |         |              |
|                                    |            |         |              |
|                                    |            |         |              |
| **飞特 HD1910 串口总线舵机**（HD-1910-C001） | **¥99.00** | 15      | **¥1485.00** |
| Radxa ZERO 3W（2 GB，无 eMMC，带排针）     | ¥309.00    | 1       | ¥309.00      |
| NP-F550 电池 + 双充套装（2200 mAh × 2）    | ¥84.59     | 1       | ¥84.59       |
| Radxa 8M 219 摄像头（IMX219）           | ¥129.99    | 1       | ¥129.99      |
| VL53L5X ToF（8×8）                   | ¥49.50     | 1       | ¥49.50       |
| 扬声器 3525 腔体 4 Ω 3 W                | ¥3.08      | 1       | ¥3.08        |
| 6700 轴承 10×15×3                    | ¥1.94      | 5       | ¥9.70        |
| ET2216 轴承 16×22×4                  | ¥2.91      | 12      | ¥34.92       |
| M2 自攻螺丝                            | ¥3.03      | 1 包 200 | ¥3.03        |

不计：3D 打印机、打印件与耗材、工具、焊接清洁耗材、TF 卡。

**对照我们之前的结论**：`microduck-硬件方案.md` 写的是「¥5000–6000 最小可行，实际 ¥7000–8000」，  
理由是 XL330-M288-T 单颗 ¥238–255 × 15 ≈ ¥3700。换成 HD1910 之后舵机这一项直接降到 ¥1485，  
**整机 ¥2234**。差价不在别处，只在舵机型号。

这和 XGO-Duck 的选择一致（同一个 BOM 也是 HD-1910-C001 × 15），所以这不是某一个人的省钱技巧，  
是这个机器人在国内的实际市场价格。

顺带两条：

- 舵机是**淘宝深圳飞特舵机工厂店**（`item.taobao.com/item.htm?id=1078248851201`），不是海淘。
- 摄像头和 ToF 是**可选项**：行走策略只吃 61 维本体感觉，这两件是给上层应用用的。

## 二、上游 `microduck_rl` 是公开的（2531★，Apache-2.0）

之前我们从 `duck_cfg/obs.rs` 和文档反推的配置，现在可以逐项核对。核对结果是：**大部分对，  
有一处我们说错了。**

### 我们说对的

| 我们的结论                                | 上游原文                                                                                                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 61 维尾部是 twist(3) + head(4) + body(6) | `microduck_velocity_env_cfg.py`：「Order matters for the runtime obs layout: `[twist(3), head_pose(4), body_pose(6)]`」                                    |
| body_pose 训练时禁用                      | 「body_pose tracking infra kept intact but DISABLED (weight 0)」                                                                                          |
| 动作延迟 = 3–6 **物理**步                   | `microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`：`delay_min_lag=3, delay_max_lag=6`（同一文件上面那段 `DelayedActuatorCfg(delay 0..3)` 是**被注释掉的旧 XML 执行器**，别拿错） |
| 质量随机化 ±5%                            | `MASS_INERTIA_RANDOMIZATION_RANGE = (0.95, 1.05)`：「applied to BOTH mass and inertia together」                                                           |
| 足底摩擦 0.7–1.3                         | `foot_friction ... ranges = (0.7, 1.3)`，注释：「Grippier footpad — narrowed from (0.3, 1.2)」                                                                |
| 推挤 ±0.3 m/s，每 3–6 s                  | `VELOCITY_PUSH_RANGE = (-0.3, 0.3)`，注释：「Was ±0.5 — an … nervous fall-recovery gait (2026-07 audit)」                                                     |
| kp/kd 随机化关闭                          | `ENABLE_KP_RANDOMIZATION=False`（但这轮看到能开，范围 kp ±15%、kd ±10%）                                                                                             |
| 齿隙是必需的而不是可选的                         | `microduck_constants.py` 对三个 `*_backlash.xml` 都有 `assert ...exists()`，是主路径                                                                              |

### 我们说错的一处：head 命令不是恒为 0

我们的 `README.md` 和 `export_mcu.py` 的注释都写着「`[51..55)` 头部命令，训练中全程为 0」。

这对**我们自己训出来的权重**是对的（我们的 env 把 head 固定在 home）。但对**上游**是错的：  
`microduck_velocity_env_cfg.py` 里 head pose 是**主要训练目标之一**：

```
cfg.commands["head_pose"] = UniformPoseCommandCfg(resampling_time_range=(2.0, 5.0))
cfg.rewards["head_pose_tracking"] = RewardTermCfg(std=0.5, ...)
cfg.curriculum["head_pose_bias_weight"] = ...  # OFF until iter 600, then 1.0 -> 3.0 by 1500
```

文件开头的自述也写着「head_pose_tracking as a primary objective」，而且 `ENABLE_HEAD_COM_RANDOMIZATION = True`（头部组件质心 ±3 mm 随机化，课程 ramp）。

所以正确的说法是：**我们的权重没有头部能力，不是因为上游没有，是因为我们没做这一层。**  
XGO-Duck 的运行时把 head 当真实指令通道（四个 rad，±1）也是这个原因——他们的策略是在前者之上  
训出来的。这一条直接对应一个具体的能力缺口：我们的机器人现在不能"转头看"。

### 我们完全没做、上游做了的：电压域随机化

```
_BAM_ACTUATOR_KWARGS = dict(
    motor_name="xl330",
    model="m6",
    kp_fw=200.0,                    # 上游固件刚度，microban 用 125
    vin_range=(6.5, 8.2),           # 逐环境电池电压，启动时采样
    vin_drop_gain_range=(0.0, 0.2), # 负载压降 V_drop = gain * sum(|tau|)
    vin_min=6.0,                    # 压降后的硬下限
    delay_min_lag=3, delay_max_lag=6,
)
```

这就是我们记忆里挂着的「接 BAM M6 电压模型」那条的**具体取值**。注意 `vin_range` 上限 8.2 V 和  
我们推的「真机喂 6.6–8.2 V」一致，而且它把「电池从满电掉到 6.5 V」当成训练分布的一部分。  
`max_current=1.75` 被注释掉了，这解释了 `plant.py` 里 `FORCE_CURRENT = kt × 1.75 A = 0.6405`。

### 奖励权重（我们只有 10 项，上游这一版是 20 项左右）

能直接读到的：`track_linear_velocity 2.0`、`track_angular_velocity 2.0`、`upright 2.0`、  
`air_time 3.0`、`pose 1.0`、`foot_slip -0.1`、`body_ang_vel -0.05`、`angular_momentum -0.02`、  
`action_rate_l2 -0.1`。

值得注意两点：

- **跟踪项权重是 2.0 不是 1.0**。我们试过 `--track-weight 3` 并且失败，但那是把 `track` 单拎出来  
  乘，没乘 `turn`，结果转向被相对压弱（README「负结果 4」）。上游是 track 和 turn 都 2.0，  
  同时靠 `air_time 3.0` 和 `foot_slip` 压住"站着不动"的退化解。**我们缺的不是权重，是那几项  
  反退化的奖励。**
- `air_time` 的注释：「standing still at zero command is [not penalised]」——说明他们也是靠  
  命令门控处理零命令，和我们 `_unbiased` 里 `valid = span > 0.02` 是同一类做法。

## 三、其他值得看的仓库

| 仓库                                  |    星 | 许可          | 为什么值得看                                                                                                              |
| ----------------------------------- | ---: | ----------- | ------------------------------------------------------------------------------------------------------------------- |
| `fanhao375/microduck-replica`       | 1277 | NOASSERTION | 从官方 MJCF 与 Rust 源码**反推**出装配图、CAD 装配体、完整电控方案。和我们做的事方法论一致，可以互相校对                                                      |
| `AI-FanGe/Microduck-build-tutorial` | 1364 | MIT         | 软硬件搭建教程，MIT 许可最干净                                                                                                   |
| `Rhoban/bam`                        |  560 | Apache-2.0  | BAM 本体（「Identify and simulate extended friction models for servo-actuators」），`motor_name="xl330", model="m6"` 的参数来源 |
| `jonathanhawkins/microduck-lab`     |  141 | Apache-2.0  | 「在普通 Mac 上训 Microduck 策略，不需要 CUDA」。和我们 CPU + mjbatch 这条路最接近，值得对照它的吞吐与收敛速度                                           |
| `Vottivott/microduck-playground`    |   72 | Apache-2.0  | 可复现的 RL 实验与策略                                                                                                       |
| `kissqy/Microduck-kissqy`           |  116 | 无           | 国内 HD1910 实机复刻：成本清单、自制 HAT/IMU、系统镜像、中文中控、中文 FAQ                                                                     |
| `7757/fanduck`                      |   69 | 无           | 「超能花钱鸭」，实机演示 + BOM + 3D 镜像                                                                                          |
| `joeynyc/awesome-microduck`         |  162 | CC0-1.0     | 索引本身                                                                                                                |

`rokbenko/quackd`（270★，Apache-2.0）是「一个 CLI 管所有机器人」，与算法无关但若要做多机器人  
统一接口可以看。

## 四、这一轮该改的东西（按优先级）

1. ✅ **已改** —— `README.md` 里「head_cmd 训练恒为 0」已加限定，并补了一张三方对照表  
   （我们 / `HannesVonEssen/microduck-running` / 上游 velocity env）。查证时发现一个细节：  
   社区那份跑步权重的模型卡明确写 `head_pose[0:4] unused; zeros`，**和我们的做法一样**；  
   是上游的 *env 配置* 把 head_pose 当训练目标。所以三件事要分开说，不能笼统讲"上游会点头"。
2. ✅ **已改** —— `microduck-低成本方案.md` 的预算表重写为四条路线，新增 HD1910 ¥2234 与  
   §2.5 说明它为什么能推翻"便宜舵机必然放大整机"。§2 的 STS3215 论证保留（对它仍然成立）。
3. 若要接 BAM：`vin_range=(6.5, 8.2)`、`vin_drop_gain_range=(0, 0.2)`、`vin_min=6.0`、  
   `kp_fw=200`、`model="m6"` 是现成取值。  
   ⚠️ **接 BAM 时必须同时改摩擦 DR 的施加位置**：BAM 下 `dof_frictionloss` 被清零，  
   对它做随机化是**静默空操作**，要改成缩放执行器的 `friction_scale`。
4. 若要补奖励：先补 `air_time 3.0` 和 `foot_slip -0.1`，而不是继续调 `--track-weight`。
5. **（新增，优先级最高）先把训练指标修好再接奖励**：`track` 在 0.79–0.87 之间的分辨力不足以  
   判断"在走"还是"站着"，见 `README` 新增章节。上游原话是"总奖励可以只靠正则项上升，  
   主任务项一次都没发生"。

## 五、还没做的（2026-10-23 15:10 更新）

前几轮列的都没核项已全部核完，状态如下：

| 原本待核               | 结果                                             |
| ------------------ | ---------------------------------------------- |
| 齿隙取多少度             | **2.0° 峰峰（±1° 单侧）**，见 8.1                      |
| `microduck-lab` 吞吐 | **16.5k steps/s（32 env）/ 27k 峰值**，我们 30k，见 8.8 |
| swizzle 是什么序列      | roller 专属的对称"沙漏"步态，**不适用于腿式**，见 8.10           |

现在真正剩下的是这五件，按「值不值得做」排序：

1. **策略训好之前，其余都是次要的。** 奖励核/`air_time`/`foot` 三处刚修完，  
   `robust61_k1` 正在验证。在这条没出结果前加任何新机制，都是在挪动多个变量。
2. **BAM 参数实测**（台架 + `bam.fit`）。反推法被 xl330 自身数据否证（高估 1.6×），  
   没实测就只能标"估计值"。见 8.9。
3. **BAM 公式向量化**（约半天）。`MujocoController` 是单实例的，逐个调用会吃掉一半吞吐；  
   必须把 P 控制器 / 力矩 / 摩擦三块写成 numpy 批量形式。见 8.9。
4. **齿隙模型移植**（半天到一天）。规格和三条坑都清楚了（±1°、`nq` 变而 obs/act 仍 14 维、  
   `dof_pos_limits` 要缩到舵机关节），但会让我们的 `nq/nv` 布局与现有权重不兼容。  
   等策略定型再做，否则每次都要重训。
5. **`robotd --sim` 与观测分布对比**（上真机前）。上游的  
   `scripts/plot_observations_comparison_plotly.py` 是把真机观测录成 pkl 与仿真叠图，  
   这是**上真机的第一个诊断动作**，不是摔了再猜。我们还没有真机，所以只能先备着。

### 明确不该再做的

- **不再追加 plant-DR 变体**。`robust61_dr` / `dr5` / `drm` / `drmb` 四个全负，  
  且都是旧奖励核（0.25/0.25）下训的，已经作废。`drmb` 在 422/600 时被我终止  
  （`track +0.04`、`gait 0.83` 仍是旧的常数特征），没有再跑完的价值。
- **不再调 `--track-weight`**。权重在指数外面，改它只会整体缩放，不能改变  
  「站着 vs 走」的比值——这一点已被四次训练反复证明。

---

## 六、第三轮：上游自己写了一份错题本（`AGENTS.md`）

位置：`pollen-robotics/microduck_rl` 根目录。**默认分支是 `master` 不是 `main`** ——  
`raw.githubusercontent.com/.../main/AGENTS.md` 返回 404，我第一次就是这么撞的。  
17.8 KB / 269 行，开头一句就是它的用途：

> Sim2real transfer is the whole point: every convention below exists because breaking it  
> produced a policy that worked in the viewer and failed on hardware.

**这份文件应该在任何代码之前读。** 下面按"我们中没中招"分类。

### 6.1 我们已经做对的（不用改，但值得记下来）

| 上游不变量                                                            | 我们的状态                                                                                                   |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Obs 归一化必须烘进导出图，**绝不手工转 checkpoint**（"in-sim play hides the bug"） | ✅ `export_mcu.py` 把 `md_mean`/`md_inv_std` 写成 C 数组，`seq_forward` 与 C 都做 `(obs-mean)*inv_std`，自检向量本身带归一化 |
| DR 不得跨 reset 累积（上游：*"一个累积的 CoM 随机化器让每一个长跑都退化，持续数月"*）             | ✅ `_draw_plant` 是**绝对写入** `_base[axis]*scale`，不是在当前值上乘                                                  |
| 61 维观测全家族共享，不用的槽位**零填充**而不是删除                                    | ✅ 我们从 MJCF 推的布局与 `obs[55:61]=0` 一致                                                                      |
| 观测重映射到传感器视图后，同一量的**奖励**必须用同一视图                                   | ✅ `_unbiased` 用与 obs 相同的命令/速度量                                                                          |

### 6.2 我们踩了，而且被上游提前写出来的

**动作低通。** README 里"抄了但没用"的结论要收回，原文：

> **Policies are UNFILTERED** (no action low-pass in training). Don't add EMA filtering  
> without a matched runtime flag and a transfer test — trained-with / deployed-without  
> (either direction) breaks transfer.

我们是后者：给一个没带滤波训练的策略，在评估时加滤波。那组数字测的是不匹配，不是低通。

**总奖励可以只靠正则项上升，主任务项一次都没发生。** 原文：

> Watch per-iteration: mean reward rising AND episode length behaving as the task demands;  
> every penalty term ≤ 0; **the MAIN task term actually growing (total reward can rise  
> purely on regularizers while the trick never happens).**

这正是 `robust61_drm` 的死法：总奖励 3.62 看着正常，`track` 0.79（≈站着的 0.698），  
评估时真实跟踪率 **0.002**。我们已经给 `train_ppo.rollout` 加了 `v`（对地速度/命令速度）  
直接打进进度条，就是为了这一条。

**"加难度 → 策略选择站着"是一个通用失效模式，不是我们特有的。** 上游在讲头部跟踪时  
说过一模一样的话：

> a 38%-of-body-mass head MUST oscillate while walking; a tight instantaneous head-tracking  
> std **taxed walking so hard the policy stood still**.

我们加 plant-DR，效果相同：额外难度让"站着"成为最优点。区别是上游归因到奖励设计，  
我们一开始归因到 DR 本身。

### 6.3 从上游直接读到的新事实

- **齿隙 2.0° 峰峰**（每关节 ±1°），且 `-Backlash-` 任务变体必须与其 base 任务用同一个  
  机体模型（walk / groundcontact / rollers），否则 A/B 对照被混淆。
- **头部 4 自由度**命名 `neck_pitch, head_pitch, head_yaw, head_roll` —— 这就是  
  `head_pose` 为 4 维的原因。关节布局：`0–4` 左腿、`5–8` 颈/头、`9–13` 右腿。
- **头占体重 38%** —— 这解释了为什么头部指令槽不能随便收紧 std。
- **BAM 下 `dof_frictionloss` 被清零**，所以对 `dof_frictionloss` 做摩擦 DR 是静默空操作；  
  必须去缩放执行器的 `friction_scale`。**如果我们以后接 BAM，这是一定会踩的坑。**
- **IMU 的 DR 是零均值的**，它只能训练"容忍多大偏差"，**无法补偿系统性安装偏置**——  
  后者必须运行时标定。
- 25 cm 机器人翻滚起来天然是 3.5–5.5 rad/s，不要用人的速度直觉去设上限。
- `warm start ≠ resume`：加载别的任务的 checkpoint 会把所有基于 step 的课程**直接跳到最后一阶**。  
  要用 `MICRODUCK_WARM_START=1`。

### 6.4 新的可搬项

| 项                                                | 为什么值得搬                           |
| ------------------------------------------------ | -------------------------------- |
| `scripts/infer_policy.py` 一次加载多个 ONNX 做**热切换彩排** | 键盘遥控、纯 CPU、上真机前先验多策略切换。我们完全没有这一环 |
| **VelStand**：行走 + 跌倒恢复训进**同一个**策略                | 部署时少一次切换窗口                       |
| `robotd --sim 127.0.0.1:7801`                    | 真守护进程驱动仿真鸭，除最底层 IO 外全是真的         |
| `--hf-jobs`                                      | 云端算力跑同一套任务                       |
| `uv run list-envs`（13+ 任务注册表）                    | 命名即文档                            |

### 6.5 授权红线（比之前记的更严）

- 软件 Apache-2.0 可商用。
- **但 `microduck_rl` 里的 3D 模型是 CC BY-SA-NC（非商业）。** 想做衍生硬件生意，这条先看。
- XGO-Duck 的 `xgoduck_hardware` **没有 LICENSE 文件**。

## 七、第三轮另两篇中文资料的增量


**知乎《国内复刻一只 Microduck 全流程》**（XL330 路线，BOM ¥6000–9500）：
- 官方 9 个 ONNX 策略随仓库附带 → **不碰 RL 也能走**，门槛从"会训 RL"降到"会焊板子"。
- `return_delay_time` 出厂值**白吃掉 40% 的总线时间预算**，必须先写 0。
- 自研门槛只剩两块板：`imu_to_dxl`（PCB+固件，**固件不在任何仓库里**）与电源 HAT（**无原理图**，
  但 `deploy/audio/` 的设备树配置透露了全部关键芯片）。
- `.part` 是 Onshape 私有格式，改结构只能按 STL 逆向重画。

**知乎《399 美元的 Sim2Real 教科书》**：
- 61 维 = 48 本体感知 + 3 twist + 4 head_pose + 6 body_pose —— 与我们的布局逐位一致，第三次独立确认。
- mjlab 把仿真步捕获成 **CUDA graph**，单卡 1–2 小时出步态，靠的是消掉 CPU-GPU 往返而不是更快的卡。
- **非对称 actor-critic 是标配**：actor 只看本体感知，critic 拿特权观测。我们是单网络，没有这一层。
- 双 IMU（躯干 + 头部）。

---

## 八、第四轮：直接读上游源码，不读二手描述

第三轮读的是上游的 `AGENTS.md`（人写的约定），这一轮直接读代码。四件事改变了结论。

**默认分支是 `develop`，不是 `main` 也不是 `master`。** `AGENTS.md` 在 `master` 上也有且内容
逐字节相同（17872 B，`diff` 无输出），但文件树只有 `develop` 拿得到 —— 用 `master` 拉
`git/trees` 会 404。以后按分支拿文件一律先查 `repos/<owner>/<repo>` 的 `default_branch`。

### 8.1 齿隙：±1° 单侧（= 2° 峰峰），以及三条容易被漏掉的移植细节

`tasks/backlash.py` 的模块字符串写明：每个舵机关节串一个无驱动的
`passive_<joint>_backlash` 铰链，**"±1° play"**。XGO-Duck 脚本里的默认 2.0° 是**峰峰**，
两者其实是同一个数 —— 之前待核的那条到此关闭。

真正值钱的是注释里那三条，它们决定移植会不会踩坑：

1. **编码器读数要"穿过"齿隙**。`BacklashEncoderBamActuator` 的固件 PD 闭环在
   `qpos[servo] + qpos[backlash]` 上，不是 `qpos[servo]`。理由是真实的舵机编码器装在**齿轮
   间隙的输出侧**。如果只在关节上串一个被动铰链、观测仍取舵机侧，模型就白做了。
2. **`nq` 会变，`obs`/`act` 维度不变**。齿隙关节是 qpos 的一部分（`nq: 14 → 28`），但观测
   仍是 14 个舵机关节，动作仍是 14 维 —— 所以**导出路径和运行时不用改**。这一点很重要：
   它意味着齿隙可以只加在训练侧，不会破坏我们已经验证过的 MCU 导出。
3. **`dof_pos_limits` 奖励必须缩到舵机关节**。齿隙关节"生来就贴着 ±1° 硬限位"（那正是齿隙
   的定义），默认的软限位惩罚会把每个齿隙关节都算成越界，产生一笔**永久性**的负奖励。
   上游为此专门给 `dof_pos_limits` 加了 `joint_names=(r"^(?!passive_).*",)`。

`pose`（变量姿态）奖励也有同样的坑：`passive_left_hip_yaw_backlash` 会同时匹配
`.*hip_yaw.*` 和 roller 任务的 `.*passive_.*`，上游的做法是给选择器前置一个
`^(?!passive_.*_backlash)` 排除。

### 8.2 61 维观测：逐槽位对上了，连部署语义也对上了

`scripts/infer_policy.py` 的 `get_observations()` 是**唯一**拼观测的地方，拼法：

```
3  base_ang_vel
3  projected_gravity（或 raw accelerometer，二选一）
14 joint_pos（相对 default）
14 joint_vel
14 last_action
13 command  →  [0:3] twist  [3:7] head_pose  [7:13] body_pose
```

3+3+14+14+14+13 = **61**，而 command 内部的 3/4/6 切分正好落在我们的
`[48..51)` / `[51..55)` / `[55..61)`。这是第四次独立确认，而且这次是从可执行代码读出来的，
不是从文档转述的。

顺带拿到两个部署常量，我们此前没有明确记录：

- `action_scale` 默认 **1.0**，目标角 = `default_pose + action * action_scale`
  （`infer_policy.py:873`）。所以策略输出就是**相对默认站姿的弧度增量**，没有额外缩放。
- `switch_threshold` 默认 **0.05 m/s**：命令模长 ≤ 0.05 时切到 standing 策略。

### 8.3 上游根本不指望一个策略既会走又会站

`_update_policy_session()` 里就是一句：

```python
new_policy = "standing" if magnitude <= self.switch_threshold else "walking"
```

**"站着不动"在上游是另一个 ONNX 负责的。** 走路策略只被要求在命令非零时走，静止由
standing 策略接管，两者在同一份 61 维观测布局上热切换（这也正是"所有任务共享布局、不用的
槽位补零"的用途）。

这对我们是**架构层面的解释**，不是新的旋钮：我们的 env 只有一个策略，它必须在
"命令 0.3 m/s"和"命令 0"之间自己选策略，而 `exp(-err²/σ)` 这个核天然让"不动"在低命令下
便宜。四个 plant-DR 变体全部站死，除了奖励核太宽（见 8.4），还有这一层原因 —— 我们让一个
网络同时背了两个互相拉扯的目标。

### 8.4 奖励核：我们两个方向都错了（本条已修，是所有历史权重的分界线）

上游（`microduck_velocity_env_cfg.py:342-345`）：

```python
cfg.rewards["track_linear_velocity"].weight  = 2.0
cfg.rewards["track_linear_velocity"].params["std"] = math.sqrt(0.1)
cfg.rewards["track_angular_velocity"].weight = 2.0
cfg.rewards["track_angular_velocity"].params["std"] = math.sqrt(0.5)
```

而 mjlab 的公式（`mjlab/tasks/velocity/mdp/rewards.py`，**读代码确认，不是看文档猜的**）是：

```python
return torch.exp(-lin_vel_error / std**2)
```

所以上游的分母是 **0.10（线速度）/ 0.50（角速度）**，不是我们一直用的单一 0.25：

| | 上游 | 我们（改前） | 后果 |
|---|---|---|---|
| 线速度核 | 0.10 | 0.25 | 宽 2.5× —— 站着不动对 0.3 m/s 得 **0.698**，上游是 **0.407** |
| 角速度核 | 0.50 | **0.25** | **窄 2 倍 —— 转向项直接饱和** |
| turn 权重 | 2.0 | 0.5 | 0.25× |

角速度这条是这轮最硬的发现。yaw 误差的单位是 rad/s，实际动起来经常到 0.5–1.0：

| yaw 误差 | 旧核 0.25 | 新核 0.50 |
|---:|---:|---:|
| 0.25 rad/s | 0.368 | 0.607 |
| 0.50 rad/s | 0.135 | 0.368 |
| 1.00 rad/s | **0.018** | **0.135** |

误差 1.0 时相差 **7.5 倍**，而 0.018 已经等于没有梯度。这解释了那个一直没想明白的实验：
`--track-weight 3` 之后 `turn` 0.24→0.08、yaw +0.78→-0.03、"策略完全不转了"。当时的结论是
"加大 track 权重把转向挤掉了"，**真实原因是转向项早就被窄核压平了，加大 track 只是让本就不
存在的项更无关**。

代码已改成 `SIGMA_LIN=0.10 / SIGMA_ANG=0.50`，新增 `--sigma-lin` / `--sigma-ang`，
`--sigma` 保留但只用于复现拆分前的跑批。**`robust61_a` 及之后所有权重都是 0.25/0.25 训的**，
所以它们从没被正确地奖励过转向。比较它们时只看评估的 `tracking_ratio`（与核无关），
任何"它不会转"的结论先当作奖励缺陷处理。

### 8.5 两个我们完全缺失的奖励项，以及缺失 `air_time` 为什么是致命的

上游行走任务的完整正/负项（论坛第 05 集，与源码一致）：

| 项 | 权重 | 作用 |
|---|---:|---|
| `track_linear_velocity` | 2.0 | 高斯，std²=0.1 |
| `track_angular_velocity` | 2.0 | 高斯，std²=0.5 |
| `pose` | 1.0 | 腿部接近默认姿态（**只含腿**，头颈由指令驱动） |
| `upright` | 2.0 | 躯干竖直（"曾调强过：防止走路时前倾"） |
| **`air_time`** | **3.0** | **抬脚时间必须落在 0.125–0.3 s** |
| `head_pose_tracking` | 主目标 | std=0.5 |
| **`foot_slip`** | **−0.1** | 支撑脚滑动（**故意调弱**：调强会妨碍原地转向） |
| `action_rate_l2` | −0.1 | 抖动，课程升到 −1.0（iter 1500） |
| `self_collisions` | 负 | 腿撞躯干电池仓 |
| `foot_clearance` / `foot_swing_height` | 负 | 抬脚高度不达标 |
| `head_pose_bias` | 负 | 只罚"可避免的"头部直流下垂（EMA 处理） |

`air_time` 权重 **3.0** 是这里第三大的正项，而我们**没有这一项**。它是"必须真正抬脚交替"
的唯一强制力：没有它，拖脚、蹭地、乃至站着不动都不会被扣分。结合 8.4 的宽核，这两条合起来
就是"站着能拿高分"的完整解释。

另两条采样细节也是现成的：

- 转向 ±1.0 rad/s，其中**15% 的环境专门采样原地转**（线速度=0）。理由写得很直白：独立均匀
  采样下原地转只占约 2% 的经验，"永远学不会"。
- 头部/躯干姿态指令每 **2–5 s** 重采样。

### 8.6 域随机化表：质量/惯量是"启动时"采样，不是每回合

| 随机化 | 范围 | 时机 |
|---|---|---|
| 躯干质心偏移 | ±3 mm 起步 → 课程升到 ±8 mm | 每回合 |
| 头部组件质心 | ±3 mm 起 | 每回合 |
| **质量/惯量** | **±5%** | **启动** |
| 关节摩擦（BAM friction_scale） | ±10% | 每回合 |
| 转子惯量（armature） | ±10% | 每回合 |
| 脚底摩擦系数 | 随机 | 启动 |
| 编码器零位偏差 | 每环境固定偏置 | 启动 |
| IMU 安装姿态偏差 | 零均值 | 观测层 |
| 外力推搡 | ±0.3 m/s，每 3–6 s | 运行中 |
| 电池电压 / 压降 / 指令延迟 | 6.5–8.2 V / 3–6 步 | 电机模型内部 |

注意质量/惯量是**启动时**采样并跨 reset 保持的。这和 `AGENTS.md` 那条"DR 不得跨 reset **累积**"
不矛盾：累积是乘法累乘（每次 reset 乘一次），保持是"开局抽一次然后固定"。我们的 `_draw_plant`
是绝对写入 `_base * scale`，属于后者，行为一致。

我们此前的 `--plant-dr "0.95,1.05::"` 就是照这条做的（±5% 质量），方向没错 —— 错的是
配套的奖励核（8.4）和缺失的 `air_time`（8.5）。

另外上游**故意关掉**了两项，源码里有 `ENABLE_*` 开关：kp/kd 随机化、初始姿态倾斜。

### 8.7 真机模型核对：四个数字全中

社区复刻者的 `调试记录.md` 报了真机实测值，拿我们手里的 `repo/microduck/robot_walk.xml`
用 MuJoCo 直接算，逐项对：

| 量 | 真机记录 | 我们的模型 | |
|---|---|---|---|
| 整机质量 | 744 g | **737.2 g** | 差 6.8 g，正好是 ToF + 摄像头 + 螺丝 |
| 颈+头子树质量占比 | "头占三分之一"、`AGENTS.md` 写 38% | **38.0%** (279.9/737.2 g) | 精确命中 |
| 大腿长 | 42 mm | **42.2 mm** | — |
| 小腿长 | 49 mm | **49.4 mm** | — |

关节限位也逐项一致（髋 yaw 左 −25/+30°、右 −30/+25° 镜像；hip_roll ±22°；hip_pitch / knee /
ankle 各 ±90°；neck_pitch −90/+60°；head_pitch ±90°；head_yaw ±170°；head_roll ±25°）。

**结论：我们手里的模型就是真机模型，不是某个示意性玩具。** 这是第一次有外部实测数据能验证
这一点，值得写进 README —— 它意味着仿真里量出来的重心、支撑域、质量占比都可以直接用来
判断真机行为。

顺带三条硬件事实（装机时才用得上，先记）：

- HD-1910 是 **4096 步 / 360°，1° ≈ 11.4 步**，零点 2048 = MJCF 全 0 = 笔直站立。
  **站姿不是零点**：官方 `DEFAULT_POSITION` 是髋 pitch ±26°、踝 ∓26°、颈/头 pitch +20°。
- **HD-1910 的位置计数方向跟 XL330 相反，15 颗全反**，运行时方向全部取 −1。这是"仿真里走得
  好好的、真机往反方向动"最可能的来源。
- 出厂**过流保护、过压保护都是关的**，装机后堵转是常事，不开就是烧舵机。电池满电 8.4 V 正好
  等于 HD-1910 的上限（零余量），带载压降到 6.6–8.2 V 才回到安全区 —— **和上游
  `vin_range=(6.5, 8.2)` 是同一件事**，那个范围就是照着这块电池定的。

### 8.8 `microduck-lab` 吞吐：我们比它快，不用为 CPU 训练发愁

之前待核的那条：`jonathanhawkins/microduck-lab`（141★，M 系列 Mac 纯 CPU 训练）
README 写 **~16.5k env-steps/s**（32 环境配方，约 1 分钟 1M 步），吞吐配置下峰值
**~27k steps/s**。

我们 `mjbatch` 在 2048 环境下是 **30k steps/s**（开 plant-DR 后 18k）。所以我们的
CPU 吞吐已经是它的 **1.8 倍**，那台 Mac 能在几分钟内训出一条"会走"的策略，说明瓶颈不在
算力，而在奖励设计 —— 这和 8.4 / 8.5 的结论一致。

同一份 README 也自己划了界线：lab 是 **99 维**观测的**原型**契约，"not a sim2real one"，
要上真机必须回上游用 GPU 重训。所以它的 99 维布局不用照搬，能借的只有工程手段。

### 8.9 BAM 是独立 PyPI 包，而且有纯 CPU 版

上游反复强调"这个尺度下执行器保真度占了 sim2real 差距的大部分"，用的就是 BAM
（`Rhoban/bam`）。之前以为它绑死在 mjlab + warp 上，实际不是：

```bash
pip install better-actuator-models[mujoco]     # 纯 CPU MuJoCo
pip install better-actuator-models[mjlab]      # mjlab / warp
```

CPU 版的入口是 `bam.mujoco.MujocoController`，每步做三件事：

1. 按**上一步**负载降压（`V_eff = V_in − R_drop·I`，`I = max(0, (1/K_t)·Σ d_i·τ_i)`）
2. 用 firmware 式 P 控制器算力矩，写 `mj_data.ctrl`
3. 评测 BAM 摩擦模型，写进 `mj_model.dof_frictionloss` 和 `mj_model.dof_damping`

**但「每个 env 一个 BAM 控制器」这条路走不通**（实测，2026-10-23 15:05）：

`MujocoController.update()` 的源码是逐步单实例的——读 `self.mujoco_data.qpos[qpos_indexes]`、
`qvel[dof_indexes]`、`qfrc_bias[dof_indexes]`、`qfrc_constraint[...]`，算完写
`self.mujoco_data.ctrl[act_indexes]`。它没有任何批量维度，一个 controller 绑定一个
`mjModel`+`mjData`。2048 个环境就要 2048 个 Python 对象，每个控制步循环 2048 次方法调用；
一次 `update()` 里十几项小数组 numpy 运算，固定开销 ~100 µs，则每迭代（2048×24）
光 BAM 就是约 5 s——而当前整个迭代才 7 s。**吞吐会掉一半以上，等于白扔 mjbatch 的优势。**

正确的接法是**把 BAM 的公式向量化重写**，而不是逐个实例调用。要重写的只有三块：

| 原函数 | 向量化后写入 |
|---|---|
| `actuator.compute_control`（firmware P + 电压限） | `ctrl`（14 列一起算） |
| `actuator.compute_torque`（`K_t(V − K_t·dq)/R`） | 同上 |
| 摩擦模型评测（Stribeck + 负载相关 + 粘性） | `dof_frictionloss` / `dof_damping`，配合 `set_const()` |

`Batch.expand()` 已经验证过能给每个仿真独立 `mjModel` 并重建常量，所以**字段**这一侧没问题；
卡住的是**计算**这一侧，必须自己写成 numpy 批量形式。工作量约半天，前提是策略先能走。

两个前置条件要记住：MJCF 里执行器必须声明成 **`<motor>`**（不是 `position`/`velocity`），
因为 BAM 自己算力矩；`frictionloss` / `damping` / `armature` 会被 BAM 覆盖，XML 里写什么
都不算数。

常用取值（与上游 `microduck_constants.py` 一致）：`motor_name="xl330"`、`model="m6"`、
`kp_fw=200`、`vin_range=(6.5, 8.2)`、`vin_drop_gain_range=(0.0, 0.2)`、`vin_min=6.0`、
`max_current=None`（训练时不启用固件限流）。

⚠️ 内置电机列表里有 `feetech_sts3215_7_4V`，但**没有 HD-1910**。要走这条线得自己做
identification（`bam.fit`）出一份 `params.json`。

**别指望从数据手册反推参数**——这条我试过，被数据自己否证了。用 xl330 的 BAM `m6`
参数（`kt=0.366`、`R=2.81`）算它 5 V 下的堵转：`I = 5/2.81 = 1.78 A`，
`τ = 0.366 × 1.78 = 0.651 N·m`，而 XL330 标称堵转是 **0.40 N·m**，高估 **1.6 倍**。
所以 `kt` 不是简单的「输出扭矩/电流」，标称值也不等于模型里的电磁力矩。同一套算法套到
HD-1910（`1.47/2.0 = 0.735`、`8.4/2.0 = 4.2`）只会把这个 1.6 倍误差一起带进去。

结论：**BAM 参数只能实测**（需要一台能测电流-扭矩的台架），这跟上游那句"执行器保真度
占 sim2real 差距大部分"是配套的——它重要到不能靠猜。过渡方案是用
`feetech_sts3215_7_4V` 的 `m1` 参数按扭矩比例缩放，并明确标注是估计值。

⚠️ `AGENTS.md` 那条警告要一起看：**BAM 会把 `dof_frictionloss` 清零**，所以对它做摩擦
DR 是静默空操作，必须改缩放 `friction_scale`。

### 8.10 `robot_walk.xml` 故意删碰撞体，以及 swizzle 不适用于我们

上游针对**不同任务**用不同机器人模型：

| 模型 | 用途 |
|---|---|
| `robot_walk.xml` | 走路。**删掉了躯干/头的部分碰撞体** |
| `robot_groundcontact.xml` | 站立/翻滚/捡拾等身体触地任务（精选碰撞集） |
| `robot_groundcontact_rollers.xml` | 轮滑（脚下被动轮） |
| `*_backlash.xml` | 齿隙孪生版 |

删碰撞体的理由值得单独记一句：走路训练里摔倒是高频事件，每次摔倒都触发一大堆碰撞约束，
策略会学到"**别摔**"而不是"**学会走**"。把摔倒变便宜，探索才放得开。

**swizzle 那条要小心别错套。** `microduck_velocity_swizzle_env_cfg.py` 是 **roller（轮滑）**
任务专用的：保留 `wheel_speed`、删掉 `single_support`/`glide`/`skating_air_time`/
`gait_symmetry`/`hip_roll_neutral` 这组"反 swizzle"项、加 `leg_symmetry` + `grounded`。
文档里那句"交替步态在真机上 transfer 不好"**是针对 roller 平台的**，不是对腿式行走的判决。
我们是 `robot_walk` 路线，这条只作参考，不能拿它否定自己的步态。


顺带两条 roller 侧的可搬细节：`lin_vel_x` 对称到 ±0.6（负值=倒着走，不是刹车）；
`ang_vel_z` 从 ±1.0 收到 **±0.5**，因为"±1.0 训出来的策略转向太猛，得用
`--max-angular-vel 0.3` 才压得住" —— 和 8.4 的核宽问题是一类现象的两面。

### 8.11 一个方法论提醒：这轮搜索结果里 4/5 是 AI 洗稿站

搜"microduck HD1910 sim2real 调试"返回 5 条，其中 4 条是同一模板生成的伪技术文，特征：

- 引用不存在的文件（`configs/domain_randomization.yaml`，上游没有这个文件）
- 把**串行总线**的 HD-1910 说成"模拟舵机，50 Hz PWM 持续微小修正" —— HD-1910 是 1 Mbps
  数字总线舵机，运行模式 4 是纯位置 PD，根本没有 PWM 概念
- 说"给正动作轮子反着转"，把腿式和轮滑混为一谈
- 通篇"我踩过的坑"但没有任何可核对的数字

唯一有价值的是第 5 条指向的 GitHub 原文（`chenkui164/microduck-replica` 的
`调试记录.md` / `踩坑记录.md`），那是真人写的、带日期、带实测值的装配记录。

**以后搜这类小众项目，先看命中里有没有 github/huggingface 原始链接，再判断其余的是不是
二手洗稿。** 洗稿站的数字一个都不能用来做设计决策。

### 8.12 硬件路线和我们完全一致的两个仓库（这一轮最有用的发现）

**`zhuoligetu123/microduck-hd1910m`（26★，2026-10-22 更新）** —— Radxa Zero 3W + 飞特
HD1910M ×15 + BNO08x，Rust 后端（`duck-control` / `robotd`），含 MuJoCo 仿真、训练环境、
ARM64 部署脚本和 APK。**它已经踩完了 HD1910 这条路的全部硬件坑**，而且用的是上游四个官方
ONNX（walk / pick / getup / roulade），不是自己重训的权重 —— 所以它报出的问题，就是我们
迟早会遇到的。

三条直接可用的事实：

1. **舵机 ID 是自由配置，不是规范。** 这个仓库用的是 `1/2/3/4/5 = 右踝/右膝/右髋俯仰/
   右髋侧倾/右髋偏航`（从末端往躯干数），11/12 = 上颈/下颈，13/14/15 = 侧头/转头/嘴。
   而 `chenkui164` 那份调试记录用的是 `10/20 = 右/左髋 yaw`、30–34 = 颈头嘴（从躯干往末端数）。
   两套方案完全不同，但都能跑 —— 因为 ID 只要和运行时配置一致就行。**别把任何一份 ID 表
   当成"官方规范"抄，选一套并写进自己的标定文件。**
2. **零位换算公式**：`q = direction × (ticks − zero_ticks) × 2π/4096`。4096 这个分辨率与
   前面读到的行程表一致（1° ≈ 11.4 步）。
3. **`HOME` 是模型站姿，不是舵机编码器零位**，且**每个 ONNX 有自己的 `default_joint_pos`**：
   观测输入用 `q − HOME`，输出经本地 ID/方向/零位映射写给舵机。它明确写了一句
   "**不得把 HOME 再校成硬件零位**" —— 和调试记录那份的"站姿不是零点"是同一件事，独立两人
   都强调了，说明这是最容易搞错的一处。

**它自认的缺陷，比它的成绩更有价值**：

> "仍有直行偏航，拾取回稳待完善，嘴部仅显示动画。"
> "翻滚并非双脚始终同时着地的静态站姿，其他倒地初态未全部通过，不能据此宣称实机验收。"

**"仍有直行偏航"是拿上游官方权重、在完全适配的 HD1910 硬件上跑出来的。** 也就是说：
直行偏航大概率不是我们的训练 bug，而是这台小机器的固有特性。这直接改变了我们对
"训出一个能笔直走的策略"的期望，也解释了上游为什么要在策略里单独做 `heading_hold` 课程
（先直线、再加转向跟踪）和 `heading_tracking`（`ang_vel_z` 从 ±1.0 收到 ±0.5 才压得住）。

还有一条藏在它的训练环境名里：`Mjlab-Velocity-Flat-MicroDuck-HD1910-**XgoBam-P6-Slew**`。
`XgoBam` = 用 XGO-Duck 那套 BAM 参数，`P6` = BAM 的 m6 摩擦模型，`**Slew**` = **限斜率**。
配合它文档里那句"训练环境与部署必须逐项核对：关节名称顺序、61 维观测、14 维动作、各模型
HOME、动作历史、EMA、**目标限幅**及 50 Hz 时序" ——**HD1910 需要限制指令的变化率**。
这是舵机的电气/机械特性（响应跟不上），不是策略缺陷，所以它在**环境层**就限了，不是靠后处理。

它文档里还切了一刀，很值得抄进我们的部署清单：

> "舵机 ID/方向/零位和 IMU 安装变换属于**实机配置**，不是 BAM `q_offset`。"

**`Ley-WL/microduck-rl`（4★）** —— HD1910 + 复刻 STL + 行走/起身/十拍舞蹈。星少但方向一致，
可作第二参考。

这两个仓库都比 `zhou...` 之外的所有中文资料更接近我们的实际情况：**同样的舵机、同样的主控、
同样的 61 维布局、同样的上游权重**。以后遇到"真机上表现不对"的问题，先查这两个仓库有没有
记录过，再去翻通用资料。

---

## 九、第五轮：`pose` 与 `upright` 的实现细节（这才是"站着划算"的最后一环）

前几轮只核对了 `track` / `turn` 的核宽度和各项权重，**没有核对正则项的公式本身**。
这一轮把 `src/mjlab_microduck/tasks/mdp.py`（**7706 行**）里对应的实现读出来，发现两处都缺了分母。

### 9.1 `pose`：`mean` 不是 `sum`，而且要逐关节除以 std

上游（`mdp.py:5442-5449`）：

```python
speed = torch.norm(command[:, :2], dim=1) + torch.abs(command[:, 2])
standing = speed < walking_threshold          # 0.01
std = (self.std_standing * standing.float().unsqueeze(1)
       + self.std_walking * walking.float().unsqueeze(1))
err2 = torch.square(joint_pos[:, ids] - default_joint_pos[:, ids])
return torch.exp(-torch.mean(err2 / (std ** 2), dim=1))
```

逐关节 std（`microduck_velocity_env_cfg.py:199-217`，**只有下肢**）：

| 关节 | `std_standing` | `std_walking` |
|---|---|---|
| `hip_yaw` | 0.1 | 0.3 |
| `hip_roll` | **0.05** | **0.05** |
| `hip_pitch` | 0.15 | 0.4 |
| `knee` | 0.15 | 0.4 |
| `ankle` | 0.1 | 0.25 |

`hip_roll` 在两档里都是 **0.05 rad**——站立和行走都要求脚掌放平、不许外八。这是全套里最紧的
一个数，也是"站着的时候腿不该张开"这条要求的唯一强制力。

我们原来是 `exp(-sum(err²))`。两处不同：`mean` 而非 `sum`，以及**没有除以 std**。
测同一个姿态（`robust61_a`）：上游公式给 **0.64**，我们的给 **0.9**。

### 9.2 `upright`：指数小了 5 倍，而修正时又超了 4 倍

上游（`microduck_velocity_env_cfg.py:301`）：`std = math.sqrt(0.05)`，配 `exp(-err/std²)`。
那里的 `err` 是 `tilt_sq = 2(qx²+qy²)`，等价于 **`1 − cos(tilt)`**。

我们写的是 `exp(-2(up_x²+up_y²))`。注意 `up_x²+up_y² = sin²(tilt)`，和上游的 `1−cos(tilt)`
**差整整 2 倍**（10° 时 0.0302 对 0.0152）。两端一比：

| 倾斜 | 上游 `exp(-(1−cos)/0.05)` | 旧版 `exp(-2sin²)` |
|---|---|---|
| 5° | 0.927 | 0.985 |
| 10° | **0.738** | **0.941** |
| 15° | 0.506 | 0.918 |

指数上是 0.06 对 0.30，**松 5 倍**。不是完全失效，但方向是"越歪越不算事"。

**修正时我第一版做过头了**：只补 `/0.05`、保留了那个 `2`，即 `exp(-2·sin²/0.05)`，
等于 `exp(-4·tilt_sq/0.05)`，**比上游严 4 倍**，10° 只给 0.299。实测 `robust61_u1`
因此把跟踪率压到 8%、`air_time` 压到 0.02，比改之前还保守。正确写法是
`exp(-0.5·sin²(tilt)/0.05)`，10° 给 0.740，与上游 0.738 相差 0.3%。

教训在自检上：我给这处写的断言是"10° 必须 < 0.35"——**它确实变严了，所以通过了**。
"朝正确方向变化"抓不到过度修正，必须断言**与参考公式数值等价**。


### 9.3 权重，以及正负项的比例

| | 上游 | 我们（旧） |
|---|---|---|
| `track_linear` | 2.0 | 1.0 |
| `track_angular` | 2.0 | 0.5 |
| `pose` | 1.0 | 0.5 |
| `upright` | 2.0 | 1.0 |
| `air_time` | 3.0 | 0（缺项） |

正项合计 4.5、负项 −1.605 → **2.8**；上游 10.0 对 −1.27 → **7.9**。
**惩罚相对重 2.8 倍**，再叠加 9.1/9.2 两处"正则几乎不起作用"，"不动"就是唯一稳赚的策略。

### 9.4 一个副产品：`air_time` 可以被"原地踏步"刷满

`robust61_k1`（只修核、没改权重）跑到 238 iter 的实测：

| iter | `air_time` | 真实前向速度 `v` |
|---|---|---|
| 1 | 0.00 | +0.055 |
| 77 | 0.02 | +0.005 |
| 153 | 0.04 | +0.020 |
| 238 | **0.07** | +0.026 |

`air_time` 单调上升，`v` 零趋势。**策略学会了原地反复抬脚**——`air_time` 只要求单脚离地
125–300 ms，不需要位移。这说明 `air_time` 必须和足够强的 `track` 配对使用（上游 3.0 配 2.0），
单开它就是送一个可以刷的分。

**通用教训**：每加一个奖励项，先问"有没有一种退化行为能单独把它刷满"。
和之前那条"先测这个量动没动"是同一件事的两个方向——前者防"项是死的"，后者防"项是活的但奖励了错的东西"。

### 9.5 落地

`train_robust.py --upstream-rewards` 一次切换全部：权重照抄、`pose` 换 mean/std 版、
`upright` 补 `/0.05`、**上游没有的项清零**（`gait` / `height` / `slab` / `torque` / `limits`）。
头 4 个关节的 std 上游没有（`head_pose` 在那边是活动目标），我们补 0.3 防止头漂移。

`gait` 清零是唯一有代价的：它是那个 667 ms 参考时钟，去掉后步态形状只能从 `air_time` 涌现，
而那是每步 0/1/2 的稀疏信号。这是已知风险，不是疏忽。



## 十、第六轮：这些数值根本不用推，它们就在包里

前几轮我一直在**从文字反推**权重和 std。这一轮换了个做法：不读描述，直接装/下载源码。
结论是**全部数值都可以逐字抄**，而且抄出来以后发现我们有三处是错的。

### 10.1 数据在哪（两个包，都公开）

| 内容 | 位置 |
|---|---|
| 任务级权重与 std | `pollen-robotics/microduck_rl` @ **`develop`** → `src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py:275-356` |
| 奖励核实现 | PyPI `mjlab==1.3.0` sdist → `src/mjlab/tasks/velocity/mdp/rewards.py` |
| 基础奖励表 | 同上 → `src/mjlab/tasks/velocity/velocity_env_cfg.py:275-371` |
| 动作延迟 / BAM | `microduck_constants.py:163-175` |
| 执行器辨识参数 | PyPI `better-actuator-models` → `bam/params/xl330/m6.json` |

⚠️ **默认分支是 `develop`**。`master` / `main` 在 raw 主机上都是 404。
⚠️ `mjlab` 在 PyPI 上有，`1.3.0` 就是上游 `pyproject.toml` 钉的版本，`uv sync` 可复现。

完整对照表见 `microduck-software/.upstream/UPSTREAM_REWARD_SPEC.md`。

### 10.2 我们错的三处

**① `upright` 多了个 0.5，方向还搞反了。**
我原先认定上游是 `exp(-tilt_sq/std²)`、`tilt_sq = 2(qx²+qy²) = 1−cos(tilt)`，
于是认为我们的 `sin²(tilt)` 比它大 2 倍，乘 0.5「换算」。源码里既没有四元数也没有 1−cos：

```python
gravity_w = asset.data.gravity_vec_w            # = [0, 0, -1.0]   entity/entity.py:787
projected_gravity_b = quat_apply_inverse(body_quat_w, gravity_w)
xy_squared = torch.sum(torch.square(projected_gravity_b[:, :2]), dim=1)
return torch.exp(-xy_squared / std**2)
```

投影重力的 xy 平方**就是** `sin²θ`。那个 0.5 让该项比上游**宽松一倍**
（10° 时 0.740 vs 上游 0.547），和我推理的方向相反，而 `u1/u2/u3` 三轮全跑在这个版本上。

自检当时是绿的，因为它断言的是 `ours == exp(-(1-cos)/0.05)` —— **和我的描述比，不是和上游比**。
现在改成断言复现上游数值，并加了一条「不得等于 1−cos 模型」的反向断言。

**② 有两条课程表我们不知道存在。**
`action_rate_l2` 从 −0.1 阶梯到 −1.0（iter 0/500/750/1000/1250/1500），
`rel_standing_envs` 从 0.02 阶梯到 0.25（iter 0/500/750/1000/1500/2000）。
**600 iter 时 smoothing 还在 −0.2、standing 只有 5%。** 我们把 `rate` 冻在 −0.1 跑了每一轮，
然后把半成品当成「上游配方」来评估。

**③ `dof_pos_limits` 被误零。** 上游是 −1.0。只有 `gait`/`height`/`slab`/`torque` 是上游没有的。

### 10.3 「走不直」不是移植 bug，是配方本来就不管

mjlab 有完整的航向闭环（`mdp/velocity_command.py:117-122`）：

```python
self.heading_error = wrap_to_pi(self.heading_target - self.robot.data.heading_w)
env_ids = self.is_heading_env.nonzero()
command[env_ids, 2] = self.cfg.heading_control_stiffness * self.heading_error[env_ids]
```

对 `is_heading_env` 那部分环境，命令第 3 维从「目标偏航角速度」换成「航向误差 × 刚度」，
于是 `track_angular_velocity` 自动变成「把航向误差压到 0」的奖励。
**奖励侧一行不用改，观测也不用加** —— command 第 3 维自己携带这个信息。

上游对 walk 任务把 `rel_heading_envs` 设成 **0.0**。

所以：直行偏航在这套配方里**不是被奖励约束的量**，只是角速度跟踪的副产品。
这也解释了「用上游官方权重、在完全适配的 HD1910 上仍有直行偏航」的复刻报告 ——
那不是谁调错了，是配方本身的取舍。
如果我们要走直，正确做法是开 `rel_heading_envs > 0`（上游现成机制），而不是继续调 `turn` 权重。

### 10.4 我们早就该补的三项

| 项 | 上游 | 我们之前 |
|---|---|---|
| `foot_slip` | −0.1，`Σ‖v_xy‖²·in_contact` | 没有 |
| `foot_swing_height` | −0.25，落地时 `Σ((peak/0.02)−1)²·first_contact` | 没有 |
| `dof_pos_limits` | −1.0 | 被零掉了 |

另外两项**已有但缺了一半**：

- `track_linear_velocity` 还有一项 `v_bz²`（垂直速度也要罚），我们只罚了 xy；
- `track_angular_velocity` 还罚 `ω_x²+ω_y²`（横滚/俯仰角速度），我们只罚了 yaw。

第二项影响很大：`robust61_a` 的 `turn` 项读 0.55，把 roll/pitch 算进去后只剩 **0.17**。
也就是说这个策略一直在横滚/俯仰上抖，而旧奖励完全不介意。

### 10.5 命令采样也不一样

| | 我们 | 上游 |
|---|---|---|
| lin_x | ±0.5，90% 概率非零 | ±0.4，连续 |
| lin_y | ±0.3，25% | ±0.3，连续 |
| yaw | ±1.2，50% | ±1.0，连续 |
| 原地转配额 | 无 | 15%（lin=0，\|yaw\| 取 40–100%） |
| standing 配额 | 无 | 课程 2%→25% |

上游注释原文：「independent uniform sampling makes spin-on-the-spot ~2% of data → untrained」。
我们连这 2% 都没有。

## 十一、第七轮：走不直是一行控制律的事，不是训练的事

这一轮做了上一轮结论指出的那件事：把上游实现了但**从未启用**的航向闭环打开。
结果是本轮最重要的一个数据。

### 11.1 零样本就生效（没有重训）

拿 `robust61_a` 直接测——它的训练里 `rel_heading_envs = 0`，**从没见过这个控制律**：

| 指标（8 s，16 envs × 3 seeds，0 ms 延迟） | 开环 | 闭环 k=1 |
|---|---|---|
| `heading_error_deg_median` | 27.8° | **4.3°** |
| `lateral_m_median` | 0.448 m | **0.089 m** |
| `yaw_rate_median` | −0.116 rad/s | **−0.016** |
| `tracking_ratio` | 0.359 | **0.491** |
| `push_0.3mps` 下的 `heading_error` | 26.8° | **4.1°** |

**不需要重训，偏航误差降 6.5 倍，横向漂移降 5 倍，被推之后也能把航向收回来。**

所以「走不直」既不是容量问题，也不是奖励塑形问题，是**缺了一条控制律**。
这句话值得写在任何一次「再跑 2000 iter」的冲动之前。

### 11.2 我一直在错误地引用那个 22.4°

`tools/robustness.py` 里的 `heading_error_deg_median` 是
`atan2(|lateral|, |progress|)`，即**轨迹偏角**，不是偏航角。
前三轮反复引用的「22.4°」意思是「净位移方向偏离命令方向 22.4°」。

航向保持恰好就是压这个量（朝向不变 → 轨迹就直），所以它有效；
但这意味着那个数字**从来不是「姿态角错了」的证据**。

而且 22.4° 是**一个种子**。同样口径下 16 envs × 3 seeds 重测是 **27.8°**。
之前所有单种子数字都乐观了约 25%——`--seeds` 这个参数存在的理由就是这个，
我却一直在读单种子那一列。以后引用 3 种子数字，且 1 种子下 5° 以内的差当噪声。

### 11.3 但它只撑到 20 ms，所以还是要训

比例环叠在本来就有延迟的对象上，正是延迟最惩罚的结构。扫 0/20/40 ms：

| k | 0 ms | 20 ms | 40 ms |
|---|---|---|---|
| 0.4 | 10.1° | 18.9° | 18.6° |
| 0.7 | 6.4° | 17.4° | 22.2° |
| 1.0 | **4.3°** | **16.4°** | 24.1° |

**40 ms 时 k=1 的环比不开环还差**（16.4°）。两条出路：降增益，或者让策略学会**预判**
这个修正——后者只能靠训练。实测部署延迟 6–12 ms，所以台面上 k=1.0 可用，
真机上诚实的默认是 k=0.7。

### 11.4 实现

- 训练：`--heading-envs F`（默认 0，老结果全可复现）
- 评估：`--heading-hold` + `--heading-stiffness`（同样默认关）

目标航向是**相对**当前航向抽 ±45°，不是 IsaacLab 的绝对 U(−π, π)：
k=1 时绝对目标有 68% 的步数把修正打满到 clip，那是在训「全速原地转」，
而不是我们缺的「20–30° 小误差修正」。这条偏离是**有意的**，并且配了负对照——
把相对抽样换成绝对抽样，断言必须变红。

### 11.5 两个我自己的设计错，同一个形状

**(a) 目标不能抽在 `resample()` 里。** `reset()` 是先 `resample()` 后 `batch.forward()`，
所以那一刻 `rot` 还是**上一集**的姿态，目标会锚在过期的朝向上。拆成「先打标记，后抽」，
两个调用点都在 forward 之后。

**(b) 评估侧每步重锚定。** 第一版 `pin()` 每步把 `heading_target` 设成当前朝向，
等于**每步把误差清零**——环看起来是闭的，实际输出恒为 0。
它之所以被发现，是因为第一次测量结果**逐位不变**。

两个都成了负对照。通用规则：**看到一条控制律像是什么都没做，先查它是不是在起作用之前
被重置成零了。**

### 11.6 自检 71 → 90

训练侧控制器 11 条、评估侧 5 条、目标分布 1 条、锚定 1 条，加 4 条新负对照
（符号翻反、目标改绝对、每步重锚定）。

---

## 第三轮（2026-10-29）：公众号《Microduck中国复刻图鉴》→ 只当作线索，逐个用 GitHub API 验过

线索来源：铁卫士公众号 2026-10-28 的盘点文章（"5 条路线"）。**文章本身不采信**，
五条路线里的仓库全部走 `api.github.com/repos/<o>/<r>` 核实了真实性、许可与活跃度。

| 仓库 | ★ | 许可 | 最近 push | 对本仓的价值 | 处理 |
|---|---|---|---|---|---|
| `fanhao375/microduck-replica` | 1447 | NOASSERTION | 10-28 | **已在用**（FD 舵机配置、`.upstream/replica-2026-10/`） | 保持 |
| `kissqy/Microduck-kissqy` | 377 | NOASSERTION（个人非商业） | 10-28 | **已在用**（部署镜像 V167/R1、训练中控） | 保持；注意许可不能进 commercial |
| `7757/fanduck` | 78 | **无 LICENSE** | 10-03 | 四个带 SHA256 的资料包，结构友好 | **只读参考，一行都别抄进本仓**（无许可 = 不能二次分发） |
| `jyg9/microduck-community-kit` | 24 | **Apache-2.0** | 10-28 | 见下 | 新，值得 |
| `jyg9/microduck_ft1910` | 0 | **Apache-2.0** | 10-09 | 见下 | 新，作备选跟踪 |
| WhatDuck 学习站 `duck.whatled.com` | — | — | — | 逐源文件中文拆解 fanhao 仓库；适合"读不懂某行为什么这么写"时查 | 未核验内容质量，需要时再用 |

### jyg9/microduck-community-kit —— 最值得收进工具箱的

Apache-2.0（每块板还单独带 `LICENCE.txt`），194 个文件，昨天还在更新。内容：

- `hardware/`：**`imu_to_dxl`**（身体传感器板，KiCad + `production/` 打样文件，还有个 10p 版）、
  `banana_pcb`（电池上方转接小板）、`dxl_hub`（腹部集线器板）→ 都有可直接下单的生成文件
- `firmware/v1/`：GD32F303CC 固件 + `patches/` + `host/`（`upgrade.py` 支持 `--port /dev/ttyS2 --baud 1000000`，
  双 slot A/B 烧写），官方 GDLib 作 submodule（clone 要 `--recurse-submodules`）
- `software/hls_servo_debugger/`：Python(Flask)+pyserial+纯前端，**浏览器里调飞特 HLS 舵机**——
  扫描/PING、**按 microduck 关节表把出厂 ID1 批量编成 20–24/30–34/10–14**、实时反馈（位置/速度/负载/电压/温度/电流）、
  0–86 全内存表读写、SYNC_READ/WRITE、原始帧收发。依据 `FTServo_Linux` 的 `HLSCL.cpp`/`SCS.cpp` + 官方内存表
- `docs/飞特通讯协议说明.md`

**对我们的直接影响两条**：
1. 阶段 0 SOP 现在依赖 **Windows 版 FD 软件**（第三方镜像里的 exe）。这个调试器是**有源码、跨平台**的备选，
   `urt1_bench.py` 缺的协议层实现正好有现成参考（而不是自己解协议）。
2. ID 表 10–14/20–24/30–34 与上游 `duck-control/src/model.rs` 一致 ⇒ 可作为我们 §3 ID 表的第三方交叉验证。

README 自称"批量验证过，XL330 与 HD1910 均适配良好""硬件纯手绘、软件全部由 AI 编写调试" ⇒ **优点是对口语气，
缺点是这三条没有第三方复核**；用之前先对自己的一颗舵机跑一遍。

### jyg9/microduck_ft1910 —— 解除"不自写 robotd"的另一条路

官方 `pollen-robotics/microduck` 的完整参考源码，**基于 0.16.0 打飞特总线补丁**，IMU 适配上面那个零件箱，
README 说"可直接编译运行"。仓库 0★、自述"目前还不完善，持续迭代中"。

本仓现行决策仍是 **跟 kissqy 镜像、不自写 daemon**（阶段C §1）。它的意义在于：等到真机那天，如果 kissqy 的
闭源升级包走不通（要求先刷官方 0.15.1、只认总线 IMU ID200、缺失 partnership key 自签），
**这是一条 Apache-2.0、能自己编译的退路**，不是只能干瞪眼。**当前只登记，不投入。**

### 顺带试手敲定的一件事：`kp_fw` 冲突已写进方案 §3

公众号文章本身没新信息，但它把我们拽回 `fanhao375` 那份**上机实测**（本仓早就有一份副本），
才发现它明写着 kissqy 模型 **训练 `kp_fw = 5`**，而本仓 m5 植株写的是 **32**；
接着在本仓 `.upstream/kissqy-2026-10/..._official-studio-config-diff.json` 里找到同源证据：
**XL330 配 200.0 ↔ HD1910 配 5.0**。

⇒ 已在 `docs/active/microduck-HD1910软件方案.md` §3 挂上新警告：**P3 重训前必须先追出 32 的出处**。
（详见该文件，别在这里重复推导。）

### 本轮方法论沉淀

公众号/盘点文的正确用法是**当索引**（它可能知道有哪个仓库），**不是当结论**
（"某某已完成实机行走""¶适配良好"这类描述一概无出处，得自己进仓库找证据）。
这篇文章五条路线里，我们已经用了两条；真正新的是两个 Apache-2.0 的 jyg9 仓库——
筛选条件是三条：**(1) 许可干净、(2) 近 30 天还在动、(3) 有可打样或可跑的产物**，
过完筛就只剩它俩。
