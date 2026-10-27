# 舵机仿真验证：我漏查了什么，以及查完之后数字怎么变

> 2026-10-23。这一轮的起点是用户一句质问：「有在网上做参考吗」。
> 答案是没有 —— 上一轮我用自己推的「测峰值关节速度代替建模」来回答换舵机风险。
> 查到现成方案后，那个做法有一半是错的，另一半的结论碰巧对。下面把两边都记清楚。

---

## 一、先认错：上一轮哪一步是自推的

| 做法 | 状态 | 查证后的判定 |
|---|---|---|
| 用 `plant.py` 加 HD1910 的 armature / frictionloss / 质量 | ✅ 方向对 | 参数本身没错，但**放进 MuJoCo `dof_frictionloss` 是错的**（见 §2.3） |
| 「MuJoCo 无原生速度上限，所以只测需求不建模」 | ❌ 自推 | 上游用的是 **BAM**，电压控制律里 `τ = kt·V/R − kt²·q̇/R` **天然含速度上限**，不需要另加限速器 |
| 「齿隙要自己建模型」 | ❌ 自推 | 上游有 **`add_backlash.py` + `BacklashEncoderBamActuator`** 现成实现，`-Backlash` 孪生任务 |
| 「BAM 库里有没有 HD1910 表」 | 上一轮判断过「有」→ 后又改口「无」 | **最终：BAM 公开库里无 HD1910**，但有 `feetech_sts3215_7_4V`（同厂），且支持自定义 JSON |

教训与用户 2026-10-21 定的规矩完全一致：**先翻官方实现和别人的代码，再自己推。**
这次交的学费是「已装好的库在 venv 里躺了几天没被用」—— `better-actuator-models 1.0.1`
在更早的会话里就装进了 `.venv`，而这两轮我一直在自己发明替代物。

---

## 二、网上有什么（都是可核的实体）

### 2.1 BAM = Better Actuator Models（不是 Bilinear）

- 仓库 `Rhoban/bam`（Rhoban 实验室，Apache-2.0，546★）
- 论文 **Duclusaud, Passault, Padois, Ly, "Extended Friction Models for the Physics
  Simulation of Servo Actuators", ICRA 2025, pp. 12091–12097**
- **PyPI 包名 `better-actuator-models`**（注意：`pip install bam` 装到的是别人的包）
- 已装：`1.0.2`，本机 `.venv`
- ⚠️ `requires-python = ">=3.12,<3.13"`，本机 3.13.14 → 必须
  `pip install --ignore-requires-python -i https://pypi.org/simple better-actuator-models==1.0.2`
  （**清华镜像没有这个包**，必须走官方源）。实测在 3.13 上能跑。
- 预辨识模型库：`xl330` / `xl320` / `mx64` / `mx106` / `feetech_sts3215_7_4V` /
  `erob80_50` / `erob80_100`。**没有 HD1910。**
- 六个摩擦模型变体 M1–M6，M6 最全（load-dependent + directional + Stribeck + quadratic）
- MuJoCo CPU 接口：`bam.mujoco.MujocoController(model, actuator_names, mj_model, mj_data)`

### 2.2 BAM 的 `xl330/m6.json` 真值（这就是我们一直在模仿的舵机）

```json
{"kt": 0.3660, "R": 2.811, "armature": 0.001808, "command_delay": 0.0102,
 "friction_base": 0.0119, "friction_stribeck": 0.00085, "friction_viscous": 0.0058,
 "load_friction_motor": 0.228, "load_friction_external": 0.107,
 "dtheta_stribeck": 0.261, "alpha": 8.53, "model": "m6", "actuator": "xl330"}
```

**两个意外**：
1. `armature 0.001808` 与 MJCF 里的 `0.0018` **几乎相同** —— 说明 MJCF 那个数本来就是从 BAM
   辨识结果抄来的，我们之前的 armature 不是错的。
2. `kp_fw = 400`（固件位置环增益），而我们 `train_ppo.KP = 5.0`。**差 80 倍**，这个差在本轮
   第一次被真正测出来（见 §3.2）。

### 2.3 齿隙：上游有现成实现，不要重写

- `src/mjlab_microduck/tasks/backlash.py` 的 `make_backlash_variant()`，
  模型由 `robot/add_backlash.py` 生成
- 每个舵机串一个**无驱动的 `passive_<joint>_backlash` hinge**，±1°（总行程 2°）
- 关键：真实 XL330 的磁编码器装在**齿轮箱输出侧**，所以固件 PD 和观测都要「读穿」间隙：
  `pos = cmd.pos + qpos[backlash]`（`BacklashEncoderBamActuator.get_command`）
- **观测和动作维度不变**，ONNX 和 runtime 不用改
- 每个主任务都有 `-Backlash` 孪生，如 `Mjlab-Velocity-Flat-Backlash-MicroDuck`
- 上游原话：「标准 MuJoCo 摩擦（`dof_frictionloss`）被**清零**，因为 BAM 内部算摩擦」

⇒ **这一条直接否定了我上一轮往 `dof_frictionloss` 写 0.0136 的做法**：在接了 BAM 的模型里
那是双重计摩擦。只有在**不接 BAM** 的对照植物里，这个数才有意义。

### 2.4 速度上限从哪来

不用另加限速器。BAM 的电压控制律在空载（τ=0）时给出 `q̇_max = V / kt`：

| 舵机 | V | kt | `V/kt` (rad/s) | 规格空载 | 折算 rpm |
|---|---|---|---|---|---|
| XL330（我们的假定） | 7.5 V | 0.366 | **20.5** | 12.9 | 123 rpm |
| HD1910（实测参数） | 6.0 V | 0.692 | **8.67** | 9.63 | 92 rpm |
| HD1910 | 7.4 V | 0.692 | **10.69** | — | — |

`V/kt` 比规格偏高是正常的：真实舵机空载时摩擦也在吃掉扭矩，BAM 的摩擦预算会把实际值拉回
规格附近。**但两者同向**，所以可以用它做保守比较。

---

## 三、实测：换 HD1910 到底有没有风险

### 3.1 HD1910 参数逐轴回归（`tools/robustness.py`）

策略 `robust61_a`，8 s × 8 envs × 3 seeds，命令 0.3 m/s，开环（无航向闭环）。

| 条件 | tracking | vs nominal | falls | tilt | hdg | surv | pkJ |
|---|---|---|---|---|---|---|---|
| nominal | 0.173 | 1.00 | 0/8 | 6.7° | 31° | 1.00 | 7.6 |
| hd1910_armature | 0.199 | **1.15** | 0/8 | 6.5° | 28° | 1.00 | 6.6 |
| hd1910_friction | 0.172 | **0.99** | 0/8 | 6.5° | 31° | 1.00 | 7.6 |
| hd1910_mass | 0.184 | **1.06** | 0/8 | 6.7° | 29° | 1.00 | 7.6 |
| **hd1910（三项全开）** | 0.197 | **1.14** | 0/8 | 6.4° | 29° | 1.00 | **6.5** |
| real_effort（对照） | 0.187 | 1.08 | 0/8 | 6.5° | 27° | 1.00 | 6.2 |

**没有一个条件摔过，all 0/8，survival 1.00。** 质量增加的账面数：`+56 g`，整机
0.7372 → 0.7932 kg（**+7.6%**），比上一轮口头说的「+75 g / +10.2%」小 —— 因为按 22 g/舵机
（18 → 22）算，14 个舵机是 +56 g，不是 +75 g。

⚠️ **但这一列 tracking 的方差大到不能单独作证据**：`sd = 0.39~0.47`，**大于均值 0.17 本身**。
说明 8 s 窗口里一部分环境几乎没走起来，一部分走了。这批数字只能读「没摔」，
不能读「走得好」。

### 3.2 stock PD vs BAM：这才是「我们的仿真像不像真机」

`tools/probe_bam.py`：同一台机器人、同一正弦目标、逐关节驱动，测幅值增益与相位滞后。

| 频率 | stock PD（kp 5.0） | BAM xl330（kp_fw 400） |
|---|---|---|
| 0.5 Hz | gain 0.97 / lag 12.5° | gain 0.93 / lag 13.5° |
| 1.0 Hz | gain 0.92 / lag 23.8° | gain 0.95 / lag 24.0° |
| 2.0 Hz | gain 0.77 / lag 42.0° | gain 1.00 / lag 48.1° |
| 3.0 Hz | gain 0.63 / lag 54.7° | gain 0.85 / lag 76.3° |

**在读这段之前先知道它意味着什么：**

1. **在 1 Hz 以下两者几乎相同**（gain 差 <0.05，lag 差 <1.5°）。步态主频就在这个区间，
   所以**之前所有 checkpoint 的训练物理在低频是可信的**，「kp 差 80 倍」被力矩饱和抹平了。
2. **2 Hz 以上分叉**：stock PD 幅值衰减到 0.77 / 0.63（跟不上），BAM 保持 1.00 / 0.85。
   而 BAM 的相位滞后更大（48° / 76°）。
3. 一句话：**我们的仿真在低频偏「软」，在台面是「幅值对、相位钝」**。这不是灾难，但方向的
   确不同 —— 策略在仿真里被允许的关节摆幅，比真机小；而真机的滞后比仿真大。

### 3.3 速度：真正的边界，比上一轮说的更紧

| 来源 | 峰值关节角速度 |
|---|---|
| 策略 `robust61_a` 真实步态（robustness 实测） | **7.6 rad/s** |
| BAM xl330 在 2 Hz 满幅正弦下的峰值 | 7.71 rad/s |
| HD1910 @ 6 V 规格空载 | 9.63 rad/s |
| **HD1910 @ 6 V 按 BAM 电压律 `V/kt`** | **8.67 rad/s** |

⇒ 按规格算余量 **21%**，按 `V/kt` 算余量 **12%**。
上一轮我报的是「78.8%，余 20%」—— **方向对，但用了宽松的那个分母**。
真实的边界是 **12%**，不是 20%。这个必须改过来。

对比：XL330 按 `V/kt` 是 20.5 rad/s，需求 7.6 → **只用 37%**。所以「换 HD1910 会损失速度余量」
这句话是成立的，只是**损失的是余量，不是能不能走**。

---

## 四、结论

1. **「换 HD1910 后策略还能不能走」→ 能。** 三个物理轴逐项改、全开、6 个条件全 0/8 摔，
   质量 +7.6%，峰值速度需求 7.6 rad/s 低于 HD1910 的 8.67（BAM 律）~ 9.63（规格）。
2. **但余量只有 11–21%，不是宽裕。** 一旦真机电池电压掉到 6.0 V 以下、或加负载，
   这个余量就没了。**建议采购按 7.4 V 供电**（`V/kt` = 10.69，余量 41%）。
3. **齿隙不是可选项。** 上游为此专门做了整套孪生任务和读穿实现，说明它在 800 g 双足上
   是个真问题。我们现在完全没有。
4. **接 BAM 是正确路线，但代价是重训。** stock PD 在低频一致，意味着**现有 checkpoint
   不是废的**，可以作为 warm start。但真机上是 BAM 物理，**不接 BAM 训出来的策略，
   上机后低频行为可对，高频（落脚、触地冲击、齿隙回弹）行为不可对**。
5. **u6（2000 iter 纯上游配方）在 stock PD 下跑，它的收益到真机上会打折扣。**
   这轮跑完可以看 A/B 结论，但不要把它当成「上机前的最后一步」。

---

## 五、还没做的

- [ ] HD1910 的 `params/hd1910/m6.json`：kt 0.692 / R 3.75 / armature 0.00224 /
      command_delay 0.0253 是实测的；**摩擦六项（friction_base / stribeck / load_friction_*）
      没有台架数据**，只能用 `feetech_sts3215_7_4V`（同厂）做初值，等台架 `record_pendulum_bench.py`
      标定后替换。
- [ ] 把 `MujocoController` 接进 `train_ppo.Duck.step()`：actuator 必须是 motor 型，
      每步先 `q_target = ctrl` 再 `update()`，且 `dof_frictionloss` 必须清零。
- [ ] 齿隙：`passive_<j>_backlash` hinge（±1°）+ 观测读穿。观测/动作维度不变。
- [ ] `command_delay 25.3 ms` 我们已经用 `--act-delay 1,2`（20–40 ms）近似，但那是**整包**
      延迟，BAM 是**连续分数延迟**（`fractional_delay_shift`）。

## 六、晚间更正（同一天，两处）

写这份文档时用的是 BAM 自带的 `xl330/m6.json` 里的 `kp_fw = 400`。后来读到
`microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`，**上游实际训练用的是 `kp_fw = 200`**
（注释：`microduck's preserved firmware stiffness (microban uses 125)`）。
400 是 Dynamixel 出厂值，microduck 把它降了一半。用 200 重测：

| 3 Hz | 幅值增益 | 相位滞后 |
|---|---|---|
| stock PD（我们训练的植物，kp 5.0） | 0.63 | 54.6° |
| BAM xl330 @kp_fw 400 | 0.85 | 76.3° |
| **BAM xl330 @kp_fw 200（上游实际值）** | **0.43** | **100.1°** |

**含意变了**：不是"两者接近"，而是**上游的训练植物比我们的软得多**。本文第二节那句
"1 Hz 以下两者几乎一致，所以现有 checkpoint 的训练物理在低频可信"在 kp400 下成立，
在 kp200 下不成立（1 Hz 是 0.83 vs 0.92，3 Hz 是 0.43 vs 0.63）。现有 checkpoint
是在一个**比上游更硬**的植物里训出来的，这个方向的偏差比之前判断的更值得注意。

第二处：HL-2915 的辨识文件用 **m4**（`hl2915_constants.py:10,46` 指向
`hl2915_m4.json`，"fitted on the pendulum bench (two loads, Kp 8–32, 0.53 deg mean error)"），
不是 `fit_hl2915.py` 命令行里写的 m6。m4 = "Stribeck load-dependent"，比 m6 少 8 个自由参数；
m6 的 kt 0.848 推 135 rpm，与厂标 110 rpm 矛盾，m4 的 1.086 推 106 rpm 与厂标吻合。
→ `tools/bam_params/hl2915/m4.json` 已补上，`probe_bam.py` 改用 m4。

---

## 七、HD-1910 的第七个来源：`qiaosiyi/microduck_rl_hd1910`（2026-10-24）

用户贴了这个 fork。它是 `pollen-robotics/microduck_rl` 的 fork，分支 `hd1910`，
9★，**2026-09-09 建仓，当天 10:58 之后就没再更新**（28 分钟就停）。
它是目前唯一一份「HD-1910 在 mjlab 上的正式适配」。

### 它给了什么（都值得拿）

1. **`hd1910_profile.json`** —— 来自 FEETECH HD-1910-C001 数据手册 A/0（2026-09-07）：
   `kt_output 0.7355 Nm/A`、`mass 21 g`、`gear 320:1`、`encoder 4096 cnt/rev`、
   `backlash ≤0.5°`、7.4 V 下 `stall 1.471 / rated 0.363 Nm / no-load 113 rpm`。
2. **`Hd1910Actuator`** —— 从 mjlab `DcMotorActuator` 派生，「输出侧位置 PD + 直流电机
   力矩-转速包络」，**rated torque 硬顶**。文档明说：
   *"The nominal torque constant is not inserted into the XL330 BAM back-EMF equation."*
   —— 这一点比我们自拼的 `HD1910Actuator`（`tools/bam_actuators.py`，无源头）**更有依据**。
3. **一份罕见的诚实清单**（profile 的 `unknown` 8 项 + `hd1910_adaptation.md` §仍待测量 4 行）：
   Mode 4 固件 P/D 单位与换算、电流限幅与热包络、转子惯量、Stribeck 摩擦、
   端到端延迟与速度滤波、每关节安装零位/方向、8.4 V 表现、编码器相对齿隙的位置。
4. `agent.yaml` 证实：**HD-1910 版也是 `512-256-128` / lr 1e-3 / init_std 1.0**（上游默认），
   `max_iterations 6000`，发布的是 `model_2000.pt`。

### ⚠️ 但它的自证数据打自己脸

`models/hd1910-walking-iter-2000/cpu_validation.json` 里 **8 次站桩试验全部摔倒**：

```
final_tilt_deg: 82.34 / 82.35 / 82.29 / 82.34 / 82.34 / 82.34 / 82.34 / 82.33
stable_under_15_deg: false × 8
root_z_m: 0.0316（躺在地上）
```

那个 `final_tilt_deg 0.589°` 的记录是 **2 秒 ONNX rollout**，而且它自己注明
*"checks numerical execution, not successful walking or hardware transfer"*。

README 说的是「训练后能抗随机扰动并恢复平衡」，视频 `hd1900.mp4` 是那一段；
但**验证文件里的 8 次站桩全摔**。两者对不上 —— 要么视频是挑出来的瞬间，要么站桩试验
用的配置与视频不同。**无论哪种，都不能当作「HD-1910 能站住」的证据。**

所以之前那句判断不变，而且是它自己的文件坐实的：
**HD-1910 侧仍然没有稳定站立/步行的可复现实证。**

### 一个容易搞错的点：不能因为"专用 fork"就更可信

它的执行器动力学里，**`armature 0.0018077 kg·m²`、`coulomb 0.00477 Nm`、
`viscous 0.00536`、`PD 0.55/0`、`delay 15–30 ms` 全部是 XL330 的参考值**，
profile 自己标了 `"Uncalibrated XL330 BAM reference"` / `"explicitly uncalibrated"`。
**它的真实增量只有：datasheet 的 kt / rated torque / 质量修正（+3 g × 15 处，
0.73724 → 0.78224 kg）+ 力矩-转速包络。**
这一点上，我们手里 OpenMicroDuck 的 m5 摆锤辨识（72 组试验）**信息量更大**。

### 对我们的处置

- **主路线不变**（HL-2915 + joy 配方）。这个仓库不构成换舵机的理由。
- **要拿的两样**：① `kt 0.7355 / rated 0.363 Nm@7.4V / 质量 21 g / backlash 0.5°` 用来
  校 `tools/bam_actuators.py` 里自拼的 `HD1910Actuator`；② 那 8 项 `unknown` 就是
  HD-1910 路线要付的测量成本清单，写进选型表当风险项。
- **不要拿的**：`model_2000.pt` 不是「会走的策略」，它是 velocity 任务 + 未标定植物 +
  上游默认奖励的 2000 iter 中间产物，而且站桩 8/8 摔。
