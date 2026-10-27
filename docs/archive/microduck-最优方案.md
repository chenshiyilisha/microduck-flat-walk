# Microduck 最优方案：六个项目互证后的单一选择

> ⛔ **已过时（2026-10-26）**：本文曾推 HL-2915。**现行定案 HD-1910**，见根目录 [`README.md`](../../README.md) 与 [`microduck-HD1910软件方案.md`](../active/microduck-HD1910软件方案.md)。下文仅作翻案档案。

日期 2026-10-23。本文只给**一个**方案，不给菜单。凡有争议处给出裁决与依据，
依据一律指向可核对的源码/实测，不指向印象。

---

## 0. 一页结论

| 层 | 决定 | 一句话依据 |
|---|---|---|
| 机械 | 官方打印件，**装齐腿部轴承** | DuckBuddy v12：装齐八颗腿部轴承后，v9 在实机上"走直、走稳" |
| 舵机 | **飞特 HL-2915-C001 ×15**（¥170/颗，¥2,550） | 全生态里唯一被实机录像证明能走的配置（纸面参数不占优，见 §2.2 更正） |
| 供电 | **3S**（11.1 V 标称，满电 12.6 V，14 V 上限） | HL-2915 额定 9–14 V；2S 会被 robotd 拒绝 |
| 主控 | Orange Pi Zero 3W | DuckBuddy 整套栈在这块板上跑通并有实机录像 |
| 训练 | **mjlab 1.3.0 + BAM**（上游原版，不自写移植） | 我们自写移植物引入 8 个 bug，无一是物理引擎的锅 |
| **训练地形** | **先学踏步（时钟化抬脚，600 iter），再学走（网络 512-256-128 + `forward_progress` + 砍「静止白拿」）** | 探针实测：零动作站桩拿 7.36/7.76（95%），我们所有 checkpoint 都低于它。Duckverse 的 `joy_feet`（权重 12、std 9 mm、两脚相乘、相位无条件）让站桩在主导项上只拿 **0.007 分**，而踏步是站桩的**严格超集**——地形里没有局部最优；实测该策略 200–600 iter 就训出 1.15 Hz 交替踏步（见 `microduck-joy策略实测.md`） |
| **网络容量** | **128-128 → 512-256-128 ELU**（⚠️ 只涉及自写 CPU 链；**mjlab 链本来就是 512-256-128**，见 §④ 更正，无需换） | 26,254 → 197,774 参数（7.53 倍）。官方/kissqy/Hannes 三个能走能跑的项目全是 512-256-128，只有我们不是；实测换网络吞吐只从 20k 降到 19.6k |
| 部署 | **DuckBuddy 的 Rust 栈**（= 官方栈 + Feetech 驱动） | 官方栈只支持 XL330；DuckBuddy 加了 38 KB 的 `feetech.rs` 和开源 IMU 固件 |
| 走不直 | **三层同时上**：腿部轴承 → `yaw_drift` 奖励 → 运行期 heading hold（gain 0.7） | 三者解决的是三个不同环节的漂移，互不替代 |
| 验收 | **checkpoint 扫描**，不看训练奖励 | 同一次训练里各 checkpoint 偏航从 −30 到 +42 °/s 不等 |

**总价 ≈ ¥3,315**（比 HD-1910 路线的 ¥2,485 多 ¥830）。
差价的 94% 是 15 颗舵机（+¥780），其余是 3S 电池。

> 唯一让我改主意的是这条：**¥830 买的是"别人已经在同一套硬件上走通了"，
> 不是买参数。** 全生态里 HD-1910 路线（kissqy / fanhao375 / OptiDuck / 陆吾）
> **没有任何一条实机稳定步行的证据**，而 HL-2915 有。

---

## 1. 十个项目各自拿出什么

| 项目 | ★ | 提供的东西 | 可信度 |
|---|---|---|---|
| `pollen-robotics/microduck` | 10,286 | 官方**部署全栈**（robotd / duck-control / configd / mediad / updater），Rust，Apache-2.0，昨天还在更新 | 一手，但**只支持 Dynamixel XL330** |
| `pollen-robotics/microduck_rl` | 2,543 | mjlab 训练配方、61 维观测 / 14 维动作契约、11 项奖励定义 | 一手，`develop` 分支 |
| `pollen-robotics/elec_RPI_Robot_HAT` | — | **整块 HAT 开源**：KiCad 9 工程、Gerber、BOM、贴片坐标、STEP | 一手。**别自己画板**（我此前判"硬件不开源"是错的，见 `microduck-mjlab-GPU与三个新仓库.md`） |
| **`fanhao375/microduck-replica`** | **1,310** | **实机复刻全套**：装配 BOM（带采购链接）、CAD 双版本（XL330 / 飞特）、`imu_to_dxl` 全网唯一逆向、B 站 8 集装配教程、**`踩坑记录.md` 85 KB**（策略训练与真机迁移一章） | 一手，**飞特版已装机站起（09-18）**、14 关节 46.87 Hz 读通。⚠️ 站起 ≠ 会走 |
| `Animan-AI/DuckBuddy` | 43 | 官方栈的 **Feetech 分叉** + 20 个 ONNX + BAM 辨识参数（m1–m6）+ 40 个任务变体 + 920 g 实机 | 一手、极新（10-18 建仓），**有 2026-10-17 实机录像** |
| `Kehao`/`JoyandAI` OpenMicroDuck | — | HD-1910 可下单 BOM、¥118 单价、BAM 参数（5 V、72 摆锤） | 一手，硬件详实 |
| `Rhoban/bam` | — | BAM 本体（ICRA 2025），**mjlab 分支** `mjlab_frictionloss` | 一手。⚠️ 版本必须按 `uv.lock` 的 `62bd8ce`，不是分支 HEAD |
| `emwstudio/DuckEMW`（+ `Vottivott/microduck-playground`） | 137 | **唯一有公开数据证明「从零训出会走」的配方**：4096 envs、13.5k iter、0.4→1.659 m/s；`forward_progress` / `heading_hold` / 速度课程 / 站桩病历 | 一手，纯仿真未上真机，但训练配方可复现 |
| **`ros-claw/microduck`**（Duckverse） | 6 | **`training/microduck_rl.patch` 609 KB**（基线 `5946fd9`）+ **8 个 61 维 ONNX**，其中 `continuous_joy.onnx` 从 `alpha_walking` seed 出的**连续步态策略**；目标递推写在训练侧（alpha .25 / 0.08 rad/20 ms） | 一手，纯仿真**未上真机**。⚠️ 基线比我们旧 6 周，patch 不能直接 apply |
| `kissqy/Microduck-kissqy` | 125 | HD-1910 **实机复刻全套**：固件 `control.43`、R17 中控、系统镜像、训练中控（14 类动作 / 35 种官方 task cfg 快照） | 一手，**有实机**，但**无量化速度数据**；奖励表 16 项与官方逐项相同 |
| `qiaosiyi/microduck_rl_hd1910` | 9 | 唯一一份 HD-1910 的 **mjlab 正式适配**：`Hd1910Actuator`（DcMotor 派生 + rated torque 硬顶）、datasheet 参数（kt 0.7355、21 g、0.363 Nm@7.4V、backlash ≤0.5°）、8 项 `unknown` 清单 | fork，**建仓当天 28 分钟就停**；自证 `cpu_validation.json` **站桩 8/8 摔倒**（tilt 82.3°）；armature/friction/PD **全是 XL330 参考值**，标了未标定 |
| 我们自己（`robust61_*` + `.venv-mjlab`） | — | 62 条上游对齐修正、118 条自检、heading 闭环、采购清单、**GPU 全栈（mjlab 1.3.0 + BAM + 4096 envs / 3.08 s/iter）** | 二手移植 + 一手环境 |

### 关键：我们一直漏掉的四件事

**① 官方全栈 `pollen-robotics/microduck` 我们从来没看。** 我们只盯着 `microduck_rl`
（训练）。而部署侧早就有 10k★ 的现成 Rust 栈：50 Hz 环、过温/低电/失联保护、
带回滚的 OTA updater、WebRTC 控制台。DuckBuddy 就是在它上面改了 37 个文件 + 新增 724 个。

**② 齿隙我们准备自己建模，而上游早就有实现**（`add_backlash.py` + `BacklashEncoderBamActuator`），
且 DuckBuddy 已经把它量出来了（见 §3 D6）。

**③ 「我们没有会走的策略」不是训练不够，是地形错了 —— 这次有实测。**
`tools/probe_argmax.py` 在固定命令 0.4 m/s 下测：零动作站桩得 **7.357**，
`robust61_u6` 6.422，`robust61_a` 4.170。**站着不动拿满了 95% 的分**
（head 2.0 + upright 1.99 + turn 1.97 + pose 1.0 = 6.96，前进相关只有 track 一项给 0.40）。
所以走路的路线要先把分从 7.36 掉到 4–6 再爬回 12，PPO 不会先掉分。
Hannes 的 `forward_progress`（`clamp(vx,0,cap)/cap`，vx=0 时恒为 0）就是用来把这条路改成单增的。
细节与逐项对照见 **`microduck-走起来的配方.md`**。

**④ 我们的网络只有官方默认的 1/8。** 官方 `microduck_velocity_env_cfg.py:914-925` 是
`512-256-128` ELU，`max_iterations` 默认 **50,000**；kissqy 用的同一个，Hannes/DuckEMW 用的
同一个，**只有我们是 `128-128`**：26,254 → 197,774 参数，**差 7.53 倍**。
kissqy 的 16 项奖励与我们逐项相同却仍能实机跑，说明「奖励表抄错」可以被排除；
剩下的差异就是网络容量和训练量。而实测换网络几乎免费（1 iter 前向 0.031→0.129 s，
物理占 4.87 s，吞吐 20k→19.6k steps/s）。

> ⚠️ **2026-10-24 更正：这一条只对自写 CPU 链成立。**
> `128-128` 是 `repo/train_ppo.py` 的网络；**mjlab GPU 链的
> `MicroduckRlCfg.actor.hidden_dims` 与 `critic.hidden_dims` 本来就是 `(512, 256, 128)`**，
> 与上面引用的官方第 914–925 行一致。实测确认见 `out/velocity_ready.json`。
> → 「换网络」在 mjlab 链上是**空操作**，A 路第一批实验不必再为此单列一批。
> 另外 §P0-1 提到的部署侧成本（`export_mcu.py:204` 的 `MD_HIDDEN` 单宽度宏）
> **也不是 mjlab 链的问题** —— 理由不是「ONNX 恰好匹配」，而是**两条链的部署路径根本不同**：
> `export_mcu.py` 只服务自写链（它 `import train_ppo as T`、读 `c["obs_dim"]/c["model"]`，
> 无法读 rsl_rl 的 ckpt）；mjlab 链走 `export.py` 出 **`.onnx`**，部署端用 **ONNX Runtime**
> 加载（见 `microduck-控制环与情感.md` §3），宽度由 ONNX 自带 shape 描述，
> 加载时校验的是 **obs 61 / action 14**，不是隐藏层宽度。`MD_HIDDEN` 那条 C 头文件路径
> 在 mjlab 链上不出现。

---

## 2. 舵机裁决（唯一真正花钱的决定）

### 2.1 官方数据（feetech.cn / lxrcmodel 一手）

| | XL330-M288-T | **HD-1910-C001** | **HL-2915-C001** |
|---|---|---|---|
| 电压 | 4.8–7.4 V | 4–8.4 V（典型 6 V） | **9–14 V**（典型 12 V） |
| 堵转扭矩 | 0.60 N·m @6 V | 1.18 @6 V / 1.47 @7.4 V | **1.39 @12 V** |
| 空载转速 | 123 rpm = 12.9 rad/s | 92 rpm @6 V = 9.63 / 113 @7.4 V = 11.83 | **110 rpm @12 V = 11.52 rad/s** |
| 质量 | 18 g | 21±2 g | 27.8±2 g |
| 尺寸 | 34×20×23 | 34×20×23 | 34×20×23 |
| 输出轴 | 25T / Ø4.95 | 25T / Ø4.95 | 25T / Ø4.95 |
| 齿隙（厂标） | — | ≤1° | ≤1° |
| 单价 | ¥340 | **¥118** | **¥170** |
| 15 颗 | ¥5,100 | ¥1,770 | ¥2,550 |

**三者机械完全兼容**：DuckBuddy 明写"HL-2915 外形、孔位、输出轴和 XL330 一样，
M2×6 自攻螺丝，打印件直接装"。HD-1910 尺寸相同，OpenMicroDuck 就是用原版打印件。
→ **换舵机不产生任何机械成本**，这是整个决定能成立的前提。

### 2.2 转速余量（**更正：这条不成立**）

我们 `robust61_a` 实测峰值关节速度 **7.6 rad/s**。按 BAM 电压律 τ=kt·V/R−kt²·q̇/R，
空载 q̇ = V/kt。

⚠️ **更正**：上一版这张表用的 kt 是 `hl2915/m6.json`（0.848，推算 135 rpm），
**用错了文件**。DuckBuddy 实际部署的是 **m4**（`hl2915_constants.py:10,46` 明写
"BAM m4 fitted on the pendulum bench"，`training/bam/` 下所有评估脚本默认 `m4.json`）。
m4 的 kt = **1.0861**，推算 106 rpm，和厂标 110 rpm 对得上；m6 的 135 rpm 明显是
在台架上把 kt 当自由参数放跑了。

用 m4 重算：

| | kt（实测） | 满电 | 空载 rad/s | 余量 | 名义电压 | 空载 | 余量 | 低电 | 空载 | 余量 |
|---|---|---|---|---|---|---|---|---|---|---|
| HL-2915 3S | **1.0861**（m4） | 12.6 | 11.60 | +53% | 11.1 | 10.22 | +34% | 9.9 | 9.11 | **+20%** |
| HD-1910 2S | 0.692（`hd1910_characterization.json`） | 8.4 | 12.14 | **+60%** | 7.4 | 10.69 | **+41%** | 6.6 | 9.54 | **+26%** |

**结论反过来了：论转速余量，HD-1910 在每一个电压点都略优于 HL-2915。** 扭矩也是
（kt×Imax：HD-1910 0.692×3.25 = **2.25 N·m**，HL-2915 1.086×1.3 = **1.41 N·m**，
与厂标 1.39 一致）。**所以"HL-2915 余量更足"这句话是错的，本文档不再使用它。**

两者真正的共同事实是：满电都宽裕，**低电都紧（+20% / +26%）**，而机器人最需要力矩的
时刻（起身、爬坡、急停）恰恰是电量不高的时候。这一条对两颗舵机同样成立。

### 2.2b 实测带宽（`tools/probe_bam.py`，用 m4 重测）

把舵机都做成 BAM 模型（`tools/bam_actuators.py` 注册），逐关节打正弦、其余关节保持：

| 3 Hz | 幅值增益 | 相位滞后 | 峰值 rad/s | 空载 rad/s |
|---|---|---|---|---|
| stock PD（kp 5.0，我们的训练植物） | 0.63 | 54.6° | 4.19 | — |
| XL330（**kp_fw 200，上游实际值**） | 0.43 | 100.1° | 5.41 | 20.49 |
| **HL-2915 @12.6 V（kp_fw 16）** | 0.70 | 63.6° | 5.18 | **11.60** |
| HL-2915 @9.9 V（低电） | 0.58 | 72.2° | 4.60 | 9.11 |
| HD-1910 @5.0 V（辨识电压） | 1.04 | 35.2° | 7.47 | 7.23 |
| **HD-1910 @7.4 V** | **1.07** | **22.5°** | 8.27 | 10.69 |

**三件事，两件与直觉相反**：

1. **上游的训练植物比我们的更软，不是更硬。** BAM 的 XL330 在 `kp_fw=200`
   （`microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`）下，3 Hz 增益只有 0.43、
   滞后 100°；我们的 stock PD 是 0.63 / 55°。也就是说**现有 checkpoint 是在一个
   比上游更硬的植物里训出来的**。上一版拿 BAM 自带 m6.json 的 `kp_fw=400` 比，
   得出"两者接近"——那个 400 是 Dynamixel 出厂值，不是 microduck 用的值。
2. **决定小信号带宽的是固件增益档，不是电机。** HL-2915 在 kp16 下有效
   `duty/rad = kp × error_gain × error_gain_ratio` = 16 × 0.05 × 1.82 = **1.46**；
   HD-1910 是 32 × 0.163 = **5.22**，硬 3.6 倍。这就是表里增益/滞后的全部差异。
3. **kp16 是刻意的折中，不是缺陷。** DuckBuddy `hl2915_constants.py:53-56` 的原话：
   "in simulation the stock policies kick at 32 once the command delay reaches 15 ms,
   and 16 stays stable at 25 ms while still having four times the stiffness the XL330
   policies were trained on"。**我们的训练延迟是 25 ms**，正好落在这句话覆盖的区间里。
   拿 kp32 换带宽会换来"延迟一来就踢"。

**这条也不改变裁决**，但它把裁决的理由清干净了：**HL-2915 在纸面参数上不占优**
（转速、扭矩、带宽三项都略逊），选它的全部理由是 §2.3 的实机证据和 §2.4 的生态。

### 2.2c 为什么是 m4 而不是 m6（模型阶数的官方定义）

BAM 自己的 `bam/model.py:248-278` 就是这张表，不是我推的：

| 模型 | 标题（原文） | 在 m(i−1) 之上新增 |
|---|---|---|
| m1 | Coulomb (M1) | — |
| m2 | Stribeck (M2) | `stribeck=True` |
| m3 | Load-dependent (M3) | `load_dependent=True` |
| **m4** | **Stribeck load-dependent (M4)** | 同时开 stribeck + load_dependent |
| m5 | … directional (M5) | `directional=True`（电机侧/外部侧分开） |
| m6 | … quadratic (M6) | **再加 `quadratic=True`**（6 个额外自由项） |

m6 比 m4 多 8 个可优化参数（`load_friction_motor/external(_stribeck/_quad)`）。
台架数据如果覆盖不到这些自由度，优化器就把误差摊进 kt——**正是这里发生的**：
m6 的 kt 0.848 推 135 rpm，m4 的 1.086 推 106 rpm，厂标 110。
判据不是"谁的拟合残差更小"，而是"谁的**可测量物理量**与台架/厂标对得上"。




### 2.3 实机证据（决定性）

| 项目 | 舵机 | 实机状态 |
|---|---|---|
| **DuckBuddy** | HL-2915 | **2026-10-17 实机录像**：语音连续下指令、走、坐、翻滚；v12 明确"v9 走直、走稳" |
| kissqy | HD-1910 | 栈跑通、V167 修"鸭身抖动" |
| fanhao375/microduck-replica | HD-1910 | 自述"仍待实机步态验收" |
| OptiDuck/sim336 | HD-1910 | 上板后抖动/翻倒 |
| 陆吾 xgoduck_rl | 1910 | 执行器参数是 STS3215 借来的（`"actuator":"sts3215"`），不可用 |

**HD-1910 侧 4 个项目，0 条稳定步行证据；HL-2915 侧 1 个项目，1 条实机录像。**
这不是"HL-2915 更好"，是"HD-1910 还没有人走通过"。

### 2.4 质量代价（被夸大过，实际可接受）

- XL330 15 颗 = 270 g → 整机 737 g
- HD-1910 15 颗 = 315 g → **≈782 g**
- HL-2915 15 颗 = 417 g → **≈884 g**，加腿部轴承 + ToF + 相机 = **920 g**

DuckBuddy 的模型训练在 **850 g ±5%**，然后为 920 g 专门微调（`-Mass920-`）。
→ 920 g 有对应配方，不是未知领域。

---

## 3. 七个决策点

### D1 训练框架：mjlab，停止自写移植

**争议**：上游是 mjlab（GPU / MuJoCo-Warp），我们自己移植成纯 MuJoCo CPU。
**裁决：切 mjlab。** 理由不是快，是**移植这件事本身消失**：

| 我们自写移植物引入的错误 | 上游原值 |
|---|---|
| `upright` 多乘 0.5 | 无系数 |
| `dof_pos_limits` 误零 | −1.0 |
| jpos 噪声高斯 σ0.005 | 均匀半宽 0.001（差 8.7 倍） |
| 终止 45.6° | 70° |
| 缺 `foot_slip` / `foot_swing_height` / `head_pose_bias` | −0.1 / −0.25 / 存在 |
| `turn` 系数 0.55 | 0.17 |
| 缺两条课程表 | iter 0/500/750/1000/1250/1500 与 0/500/750/1000/1500/2000 |

**八个 bug，没有一个是物理引擎的锅，全部是"重写"引入的。**
DuckBuddy 在上面加一个消融就是一个任务注册项（40 个）；我们加一个开关要改 4 处代码。

**Windows 可行性已验证**：`mjlab` / `mujoco-warp` 是 `py3-none-any` 纯 Python 轮，
`warp-lang` 有 `win_amd64` 轮。Python 3.12.13 + `torch==2.9.1+cu128` 已装。

### D2 部署栈：用 DuckBuddy 的 Rust 栈，不自写、不用 kissqy 镜像

官方栈只支持 XL330（595 个文件里没有 feetech）。DuckBuddy 补了：
- `duck-control/src/feetech.rs`（38 KB 协议驱动）
- `firmware/imu-feetech/`（开源 IMU 固件，同一条总线上答话）

且它带了我们正好缺的东西：50 Hz 环、过温保护、带自动回滚的 OTA、heading hold、
WebRTC 控制台。**这和我们"不重写"的原则完全一致。**
许可 Apache-2.0（kissqy 的是"个人非商业"）。

### D3 舵机：HL-2915（见 §2）

### D4 走不直：三层，不是一层

这是全项目最关键的一条，因为**我们和 DuckBuddy 走了不同解法，而两者不冲突**。

| 层 | 做法 | 证据 | 能解决什么 | 不能解决什么 |
|---|---|---|---|---|
| 硬件 | **装齐八颗腿部轴承** | DuckBuddy v12：装齐后 v9 "走直、走稳" | 打印件关节的间隙/摩擦不对称 → 每步偏航踢 | 控制律造成的系统性偏航 |
| 训练 | **`yaw_drift` 奖励项** | 同一次训练 checkpoint 偏航 −30→+42 °/s；加了 drift 项后实机保住航向 | 策略本身不产生偏航 | 模型/地面偏差导致的长时漂移 |
| 运行 | **heading hold，gain 0.7 / τ0.5 s / 死区 5°** | 我们零样本：27.8°→**4.3°**，lateral 0.448→**0.089 m** | 长时累积漂移 | 每步的踢（会跟着抖） |

**运行期的参数是被两边同时钉死的**：
- 我们的延迟扫描：k=1.0 在 40 ms 时比开环**更差**（24.1° vs 开环）；
- DuckBuddy 实机：gain 1 追着步子晃动，"一秒内 ±30° 直到摔倒"，最终**默认关到 0**，
  并加 τ0.5 s 低通 + 5° 死区。
→ **两个独立来源得出同一结论：直接闭环会追噪声。取 k=0.7 + 低通 + 死区。**

### D5 延迟：15–30 ms → **10–50 ms，中心 40 ms**

我们原来 `act_delay=(1,2)` = 15–30 ms。DuckBuddy **实测实机等效延迟 ≈40 ms**，
并专门训了 `-Delay50-` 任务（10–50 ms）。延迟扫描显示：50/60 ms 下老策略 1/8、2/8 摔。
→ 我们的区间**上限不够**，必须扩到 50 ms。

### D6 齿隙：**±0.3–1.0°，不是 ±1°**

DuckBuddy 2026-10-08 在实机上量的（腿吊在空中、Kp 32、手掰）：
每关节总行程 0.6–1.2°（含舵机自身间隙），折算到脚尖全腿约 5 mm，即每关节 ±0.3–0.4°。
**上游 `add_backlash.py` 固定 ±1° 是实测值的 2–3 倍。**
→ 用 `BACKLASH_HALF_DEG = (0.3, 1.0)`，逐关节逐回合抽，且**对称抽**（上游的
`joint_limits` 两边界独立抽，会抽出歪的）。

### D7 checkpoint：扫描，不取最后一个

DuckBuddy：**同一次训练里各 checkpoint 直走偏航从 −30 到 +42 °/s 不等，训练指标看不出**。
更反直觉的：`v5bl` "2000 轮 0.2 m/s 走 0.97 m，后期 checkpoint 0.2 m/s 原地不动"。
→ **训练奖励不能用来选模型。** 这印证我们自己的结论（不要看 `track`，看
`heading_error_deg_median` / `lateral_m`）。选型用 3 seeds 扫 checkpoint。

---

## 4. 方案本体

### L1 硬件

| 项 | 规格 | 数量 | 单价 | 小计 | 变化 |
|---|---|---|---|---|---|
| 舵机 | 飞特 **HL-2915-C001** | 15 +1 备 | ¥170 | ¥2,720 | ← 换 |
| 主控 | Orange Pi Zero 3W（2 GB） | 1 | ¥309\* | ¥309 | ← 换（DuckBuddy 验证过） |
| TF 卡 | 64 GB A2 | 1 | ¥110 | ¥110 | — |
| HAT + IMU | Zero Robot HAT + IMU_to_servo（LSM6DSV16X，AMP2.0） | 1 | ¥150 | ¥150 | — |
| **轴承** | 6700K ×3 + ET2216 ×11（**装齐腿部轴承位**） | 14 | — | ¥60 | **新增** |
| 电池 | **3S LiPo 1500 mAh** | 2 | ¥65 | ¥130 | ← 换 |
| 打印件 | PLA/PETG + TPU，官方 47 STL（或用 DuckBuddy 的 2.3mf，头壳带散热孔+麦克风孔） | — | — | ¥120 | — |
| 相机 + ToF | IMX219 ¥30 + VL53L8CX ¥66 | 1 | — | ¥96 | 可延后 |
| 台架 | URT-1 ¥45 + 限流电源 ¥120 + 万用表 ¥35 | 1 | — | ¥200 | 阶段 0 先买 |
| | | | **合计** | **≈¥3,315** | +¥830 |

**三条硬约束**
0. \*¥309 是 OpenMicroDuck BOM 里 **Radxa ZERO 3W** 的价，Orange Pi Zero 3W 未核价。
   选 Orange Pi 的唯一理由是 **DuckBuddy 的栈假定 `/dev/ttyS7` = UART7 在 A733 上**；
   若改用 Radxa，`bus.port` 与设备树要重验。**两个板子别混用配置。**
1. **不能用 2S LiHV**：满电 8.7 V，超 HD-1910 的 8.4 V 额定；HL-2915 则根本不吃 2S
   （robotd 会拒绝上扭矩）。
2. HAT 选 **3S 版**（2S/3S 两块板外观相同，背面标 2S，插错欠压锁定失效）。
3. 电源入口并 **1000 µF**，ZERO 用 **5 GHz** Wi-Fi（kissqy 的装机提醒，与舵机无关但通用）。

### L2 训练

```
基线 = pollen-robotics/microduck_rl @ develop
  + BAM（mjlab_frictionloss 分支）+ HL-2915 参数 m6
  + DuckBuddy 的随机化清单
```

**舵机模型**（BAM `hl2915/m6.json`，直接可用）

| 参数 | 值 |
|---|---|
| kt | 0.8478 N·m/A |
| R | 5.297 Ω |
| armature | 0.002096 kg·m² |
| friction_base / viscous | 0.006644 / 0.011117 |
| load_friction_motor / external | 0.2563 / 9.1e-5 |
| alpha / dtheta_stribeck | 0.5007 / 0.5207 |

**随机化**（照抄，都是实测量的）

| 项 | 范围 | 来源 |
|---|---|---|
| 齿轮间隙 | 逐关节逐回合 ±0.3–1.0°，对称 | 2026-10-08 实测 |
| 指令延迟 | 10–50 ms（实机 ≈40） | 实机测量 |
| IMU 观测延迟 | 0–40 ms | — |
| 腿部刚度 | ×0.6–1.2 | — |
| 动作增益 | ×0.75–1.05 | — |
| 脚底摩擦 | 0.15–1.3 | 硬地+硅胶垫最好 |
| 头部质量 | ×0.95–1.3 | — |
| 质心 | 前移 5 mm | — |
| 整机质量 | 920 g ±5% | 称重 |

**奖励**（上游 11 项 + 3 项）

| 我们新增 | 权重 | 作用 | 注意 |
|---|---|---|---|
| `yaw_drift` | 半权重（DriftLite） | 压每步偏航踢 | 全权重要用步幅换航向 |
| `lin_tight` | — | 让"速度不够"真的掉分 | 否则半速仍拿 84% |
| `head_band` | 强/软两档 | 只罚超出 ±2.9° 的头部摆动 | **不要用 HeadCalm**（罚速度会连平衡小动作一起罚，实机上因此摔倒） |

**采样与选择**
- 左右镜像（`symmetry`）：v7 起证明"每块地面步幅更长、步态对称"；起身策略没加镜像时
  实机右脚前 1°、右髋 roll 吃 621 mA 而左髋 67 mA。
- **命令上限降到 0.2–0.3 m/s**：DuckBuddy 全部实机数据在 0.2 m/s；我们的
  `COMMAND_RANGE_UPSTREAM = 0.4` 超出他们的验证范围，也超出舵机余量。
- 选模型：3 seeds 扫 checkpoint，看 `yaw_rate` / 前进距离，不看 `track`。

### L3 部署

**用 DuckBuddy 的栈**，只改 `deploy/robots/*.toml`：

| 键 | 值 | 依据 |
|---|---|---|
| `bus.port` | `/dev/ttyS7`（UART7） | Orange Pi Zero 3W |
| `bus.servo` | `feetech_hls`，**500 kbit/s** | UART7 上不了 1 Mbit/s |
| `bus.position_kp` | **16** | DuckBuddy 策略部署值 |
| `bus.position_kp_head` | 16 | 同上 |
| `bus.position_kd` | 8 | — |
| `bus.current_limit_ma` | 2925 | — |
| `control.hz` | 50 | 原型机沿用，未重新推导 |
| `heading_hold_gain` | **0.7**（默认 0；1.0 会抖到摔） | 见 D4 |
| `heading_hold_tau_s` / `deadband_deg` | 0.5 / 5.0 | — |
| `thermal.warn_c` / `walk_max_c` | 55 / 65 | 实机 58–61 °C，舵机自己 80 °C 跳闸 |
| `battery.cells` / `max_volts` | `[3]` / 14.0 | HL-2915 |

⚠️ **舵机自身 Kp 32 是训练侧的 ~15 倍硬**，会让走路策略"把自己踢倒"。必须降到 16
（腿测试可降到 8）。

**导出**：ONNX `obs[1,61] → actions[1,14]`，`action_scale = 1.0`，
`standing_gain_ratio = 1.0`（起身/坐站/翻滚）。

### L4 验收（不达标就不往下走）

| 阶段 | 判据 | 数据来源 |
|---|---|---|
| 单颗 | 事务 ≤5 ms @500 kbps；量 kt/R/死区/齿隙/最高速 | 台架 |
| 温升 | 额定 0.36 N·m 连续 60 s，壳温 <60 °C | 台架（HL-2915 额定 4.5 kg·cm=0.44 N·m，别按堵转 1.39 设计） |
| 单腿 | 5 颗同步；零位重复性 <1°；正反向齿隙写进模型 | 吊架 |
| 整机 | 一次 `sync_read` 读 15 台；母线 ≥9.9 V 不掉；**p99 周期 <22 ms** | 上电 |
| 站立 | 低增益站立 60 s 不抖 | 实机 |
| 步行 | 0.2 m/s 走 8 s，**航向偏角中位数 <10°、结束偏航 <30°、不摔**（3 次） | 实机 |
| 提速 | 0.3 m/s 同上 | 实机 |

**注意读数陷阱**：我们 `heading_error_deg_median` 是**轨迹偏角** `atan2(|lateral|,|progress|)`，
不是偏航角；两者不能混。`tracking_ratio` 的 sd（0.39–0.47）大于均值（0.17）时，
只能读"没摔"，不能读"走得好"。

---

## 5. 与现有成果的关系（不推翻，归档为对照）

| 资产 | 处置 |
|---|---|
| `robust61_a` / `robust61_u6*` | **保留**。作为"纯 MuJoCo CPU + XL330 物理"对照，不再续训 |
| `tools/selfcheck.py` 90 条 | **保留**。切 mjlab 后多数断言变成"核对上游"，仍有用 |
| `.upstream/UPSTREAM_REWARD_SPEC.md` | **保留**。移植时的对照表，切 mjlab 后用于验证"我们理解对了" |
| `microduck-采购清单.md` §1–§6（XL330 路线） | 保留原文 |
| `microduck-采购清单.md` §7（HD-1910 路线） | 保留，降级为**预算硬上限**时的退路 |
| heading 闭环 + 延迟扫描 | **直接进部署配置**（gain 0.7 有实机印证） |
| 62 条上游修正 | 转为验收清单，逐条核对 mjlab 版本是否符合 |

---

## 6. 下一步（按顺序，每步有出口判据）

1. **装完 `.venv-mjlab`**（进行中：Python 3.12.13 ✅、torch 2.9.1+cu128 下载中）
   → 出口：`cuda.is_available()` 为 True、warp 认到 4070
2. **跑通上游 `microduck_rl` 最小训练**（`uv pip install` 依赖 + `-e .`，不走 `uv sync`）
   → 出口：1 个 iter 不报错、`mjlab.tasks` 里能列出 `Mjlab-Velocity-Flat`
3. **接 HL-2915 的 BAM 参数 + 随机化清单**，把任务改名为 `-MicroDuck-HL2915`
   → 出口：`plant` 打印出的 armature/friction 与 **`m4.json`** 一致
   （⚠️ 用 m4，不是 m6：m4 = "Stribeck load-dependent"，是 `hl2915_constants.py` 指向的
   部署模型；m6 多了 directional + quadratic 六个自由项，把 kt 拟合到 0.848（135 rpm），
   与厂标 110 rpm 矛盾）
4. **改奖励**（`yaw_drift` / `lin_tight` / `head_band`）+ 镜像 + 命令上限 0.3
   → 出口：自检能复现上游数值（沿用"必须复现参考实现自身数值"的规矩）
5. **训一轮 4000 iter**，然后 **3 seeds 扫 checkpoint**
   → 出口：sweep 给出偏航排名，不是取最后一个
6. **导 ONNX → 空跑 robotd（台架，不上电）→ 上电站立 → 步行**
7. 阶段 0 台架（买 HL-2915 单颗 ¥170 + URT-1 ¥45）可与 1–5 并行

**采购可立刻下的只有三样**：HL-2915-C001 ×1（¥170）、URT-1（¥45）、
限流电源+万用表（¥155）。**其余等阶段 0 台架过了再下。**

---

## 7. 我改口的地方（留档，方便下次对账）

| 之前说 | 现在 |
|---|---|
| "¥2,235 走 HD-1910" | **¥3,315 走 HL-2915**。差 ¥830，买"有人走通过" |
| "速度余量 12%，建议 7.4 V" | 那是 **HD-1910 在 6 V 下**的数。HL-2915 3S 满电 +53%、低电 +20%（§2.2） |
| "HL-2915 转速余量 43%、扭矩更大，所以更好" | **错**。用 m4 实测参数算，HD-1910 在每一项都略优（余量 +26% vs +20%，扭矩 2.25 vs 1.41 N·m）。选 HL-2915 的理由只有实机证据与生态 |
| "HL-2915 用 m6.json" | 用 **m4.json**。m6 多 8 个自由项把 kt 放跑到 135 rpm（厂标 110） |
| "齿隙要自己建模" | 上游有实现；且**不是 ±1°，是 ±0.3–1.0°** |
| "建议 k=0.7 是因为担心延迟" | k=0.7 现在有**实机印证**（gain 1 会抖到摔） |
| "走不直是控制律问题" | 还有**硬件一半**：腿部轴承 |
| "官方栈没有 Feetech，要自己写驱动" | DuckBuddy 写好了（`feetech.rs` 38 KB + IMU 固件） |
| "部署栈用 kissqy 的镜像" | 用 DuckBuddy 的（Apache-2.0 vs 个人非商业） |

---

## 8. 来源

- `pollen-robotics/microduck` @ main（10,286★，Apache-2.0，2026-10-22 推送）
- `pollen-robotics/microduck_rl` @ **develop**（`pip` 名 `mjlab-microduck`）
- `Animan-AI/DuckBuddy` @ main：`training/policies/README.md`、
  `training/hl2915/hl2915_tasks.py`、`training/bam/params/hl2915/m{1,3,4,5,6}.json`、
  `deploy/robotd.toml`、`deploy/robots/opi-hl2915-rev-a.toml`、
  `docs/hardware/INTERFACE-CN.md`、`hardware/print/README.md`、`UPSTREAM-CHANGES.md`
- `Kehao/OpenMicroDuck`、`JoyandAI/OpenMicroDuck`：BOM（HD-1910 ¥118、Radxa ¥309）、
  `hd1910_calibration/params/hd1910_characterization.json`
- `Rhoban/bam`：`bam/params/xl330/m6.json`、分支 `mjlab_frictionloss`
- feetech.cn 产品页（HL-2915-C001 / HD-1910-C001 厂标）、lxrcmodel（HL-2915 完整规格）
- 本项目实测：`tools/probe_bam.py`、`tools/robustness.py`、`tools/selfcheck.py`（90 条）
