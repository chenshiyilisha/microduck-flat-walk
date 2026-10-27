# XGO-Duck 对照：国内这条路已经有人走完了

这份文档不是为了介绍别人家的产品，是因为它**改写了我们前几轮得出的几条硬件结论**，并且把我们
标注为"最大保真度缺口"的东西直接给出了实现。

所有结论都来自三个仓库的代码与文档原文（2026-10-23 抓取），不是猜测。

## 三个仓库的实际状态

| 仓库 | 星 | 语言 | 许可 | 最后推送 |
|---|---:|---|---|---|
| [xgoduck_hardware](https://github.com/LuwuDynamics/xgoduck_hardware) | 983 | — | **无 LICENSE 文件**（见下） | 2026-10-22 |
| [xgoduck_runtime_arduino](https://github.com/LuwuDynamics/xgoduck_runtime_arduino) | 100 | Python + C++ | 无顶层许可 | 2026-10-22 |
| [xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | 79 | Python | **Apache-2.0** | 2026-10-21 |

硬件仓库 983 星、建库 2026-09-24、一天前还在推。这不是一个实验性 demo，是一个在活跃维护的
完整项目：25 页图解装配指南、Altium 原理图 + PCB 源文件、STL、BOM、故障排查文档。

## 和我们结论的逐条对照

| | 我们此前的结论 | XGO-Duck 的实际做法 | 影响 |
|---|---|---|---|
| 舵机 | Dynamixel XL330-M288-T，¥238–255/颗，官方店交期 10 天 | **Feetech HD-1910-C001 / HD1910M**，15 颗，有专门的「Microduck Servo Kit」 | 彻底换赛道 |
| 舵机电压 | XL330 规格 3.7–6.0 V，真机喂 6.6–8.2 V，是**超压 65%** | HD1910 工作范围 **4–8.4 V**，8.4 V 是**额定上限** | 上次那个"超压"的坑在这颗舵机上不存在 |
| 力矩 | `plant.py` 用 0.96 N·m 堵转（0.52 × 9.2/5） | 8.4 V 下堵转 **15 kgf·cm = 1.47 N·m**，2.0 A；额定 3.7 kgf·cm @ 900 mA | 比我们的植物强 53% |
| IMU | LSM6DSV16X + 自研 `imu_to_dxl` 板，总线 ID 200，芯片内 SFP4 fp16 四元数 | **QMI8658A**，I²C 0x6A/0x6B @400 kHz，**融合在 Linux 侧 Python 里算** | 省一块打样板 |
| 主控 | Radxa Zero 3W，50 Hz 定时器抖动是 ms 级（我们当成缺点） | **Arduino UNO Q = 两台计算机**：Qualcomm Linux 跑 50 Hz ONNX，STM32U585/Zephyr 跑 100 Hz 总线环 | 我们担心的抖动被架构解决了 |
| 齿隙 | 「目前最大的一处保真度缺口，只能标注不能假装」 | `add_backlash.py`：每个舵机关节后串一个未驱动 hinge，±1.0°（2.0° 峰峰） | **有现成实现可搬** |
| BAM | 「没有 BAM 电机模型：电压控制律、反电动势、库仑摩擦都没建」 | `1910_m6.json` + `friction_dr_bam.py`（逐环境摩擦缩放） | 有现成参数，但对应的是 1910 不是 XL330 |
| 起身 | 没做 | **独立 get-up 策略 + 手写状态机**，倾角 >55° 持续 0.15 s 切起身 | 不是训出来的，是工程解 |
| 动作滤波 | 把延迟塞进训练（`act_delay=(0,2)`） | 部署侧一阶低通：腿 α=0.45、头 α=0.2，**`prev_action` 存未滤波的原始输出** | 对我们最有用的一条 |
| 15 颗舵机 | 15 颗受控 | **14 受控 + 1 嘴部**（ID 34，不在动作里） | 口径澄清 |
| 61 维布局 | 我们推导出 `[51:55)` 头命令、`[55:61)` 体态命令且训练恒 0 | `rl_core.build_obs` 逐行一致，且 `obs[55:61] = 0.0` 写死 | **独立实现确认了我们的推导** |

### 双脑架构值得单独说

`xgoduck_runtime_arduino` 的 README 原文：

> The MCU loop does not wait for Linux. It publishes a 240-byte `duck_state` snapshot at 100 Hz.
> The host filters each snapshot on arrival and the 50 Hz thread reads the latest one. **A late
> cycle is skipped. There is no queued backlog of actions.**

这半句话解决了我们上一轮纠结的问题。我们当时的判断是「ESP32 裸机是 µs 级定时，比 Linux 的
ms 级抖动更适合跑控制环」——方向对，但结论下得太窄。真正的要点不是"谁定时更准"，而是：

**控制环的时序保证要放在 MCU 上，策略环被允许丢帧。**

策略算得慢一点、晚一点，就丢那一拍，读最新状态再算。这样 Linux 侧的抖动不进控制环，而策略
本身对"偶尔少一个周期"的容忍度远高于对"命令晚了 20 ms 还照发"的容忍度。我们的 `act_delay`
训练恰好证明了后者有多致命（40 ms 以内 0 摔倒，60 ms 摔 29 次）。

### 动作低通：一个我们没试过的旋钮

他们的 `policy.py`：

```python
self.prev_action[:] = action          # 原始网络输出进观测
for sl, alpha in ((slice(0, 5), 0.45), (slice(5, 10), 0.2), (slice(10, 14), 0.45)):
    self._act_filt[sl] *= alpha
    self._act_filt[sl] += action[sl] * (1 - alpha)
return self._act_filt.copy()          # 滤波后的才发给舵机
```

一阶低通，腿 α=0.45。这个滤波在**闭环里面**，但不在观测里面。用控制论的话说：它在开环增益
上滚降，用相位换带宽。而延迟裕度 `T_d,max ≈ PM_rad/ω_gc` 里的 ω_gc 正是被这个东西往下压的。

我们之前把这件事理解成"部署时的临时补丁"，所以没做。但它可能是比"训练里塞延迟"更划算的
解：不牺牲训练分布，还能额外拿到平滑。**这条应该马上在我们自己的闭环里验一遍。**

还有一个细节值得偷：`slice(5, 10)` 覆盖了头部 4 个关节 **加上右腿第 1 个关节**（ID 20），
他们的代码里明确写了"Keep the reference script's exact slices, including ID 20 in [5:10]"
——即上游参考实现里就带着这个 off-by-one，他们选择保持原样并注明。诚实，但也说明这类索引
错误在真机上活跃了很久没人发现。

## 可直接搬的三样东西（按性价比排序）

### 1. 动作低通 α=0.45 —— **已经试了，对我们没用**

已实现（`tools/robustness.py` 的 `act_alpha`，条件名 `lpf_leg45` / `lpf_leg70`），在
`robust61_a.pt` 上实测（0.3 m/s，8 s × 8 env，单 seed）：

| 条件 | 跟踪率 | 摔倒 | 倾角 |
|---|---:|---:|---:|
| nominal | 0.438 | 0/8 | 7.1° |
| lpf α=0.45 | 0.440 | 0/8 | 9.7° |
| lpf α=0.70 | 0.801 | **62/8** | **47.9°** |
| latency_40ms | 0.383 | 0/8 | 11.6° |
| latency_40ms + lpf0.45 | **0.278** | 0/8 | 14.6° |
| latency_60ms | 0.218 | 28/8 | 46.7° |
| latency_60ms + lpf0.45 | 0.328 | **40/8** | 47.0° |
| latency_60ms + lpf0.70 | 0.580 | **73/8** | 47.7° |

**假设被证伪。** α=0.45 在 40 ms 上让跟踪率从 0.383 掉到 0.278；在 60 ms 上跟踪率"上升"到
0.328 但摔倒从 28 次涨到 40 次；α=0.7 更极端——跟踪率 0.801、摔 73 次、倾角 47.7°，
又一次是"翻倒位移被读成跟踪率"。

所以低通**没有**给我们买到相位裕度。为什么 XGO-Duck 用它是有效的，这次测量回答不了：
他们的植物堵转力矩高 53%、有齿隙模型和 BAM 执行器，而且他们的 α 可能是用来平滑 100 Hz
状态流，不是用来补延迟裕度。**记为负结果，不记为"还缺一个旋钮"。**

顺带：这张表是第三次踩"高跟踪率 = 在摔"的坑，所以 `robustness.py` 现在给所有摔倒过的行
打 `*` 标记，脚注写明"先读 falls 和 tilt"。

### 2. `add_backlash.py`（Apache-2.0，可直接改）

140 行，插桩式：给每个 `class="chosen_actuator"` 的 joint 后面补一个同名 `passive_*_backlash`
hinge，范围 ±deg/2。它把踩过的坑写在注释里：

> with a range this small the default `solref (0.02,1)` lets the joint overshoot its limits ~2x
> under load. `0.01` = 2×sim_dt (mjlab velocity tasks run dt=0.005), the stiffest stable setting

代价要说清楚：**nq/nv 会变**。每加一个 hinge，`qpos` 布局就变成 `[free(7), j0, b0, j1, b1, …]`
交错，我们的 `Duck.joints = arange(7, 21)`、`STAND` keyframe、`batch.bind("qpos")` 的索引
全部要跟着改。这不是"跑个脚本"，是半天到一天的重构。但它是我们 README 里自己认定的最大
保真度缺口，值得。

### 3. BAM `1910_m6` 参数（只在换舵机时才有意义）

我们的植物是 XL330，参数不对口。除非按 XGO-Duck 的 BOM 换舵机，否则搬过来是错的。

## 不能直接搬的

- **硬件仓库没有 LICENSE 文件。** `LICENSING.md` 原文：

  > No top-level license file was found in the repository snapshot used for this documentation
  > update. Publication of files by itself does not establish a complete reuse grant.
  >
  > The maintainer intends to allow personal and educational replication and require separate
  > authorization for commercial use … **This statement records intent; it is not a finalized
  > replacement license** … File-level scope and final terms are pending.

  翻译：自己装一台、学校里用，是明确被鼓励的；量产要发邮件到 hello@xgorobot.com 单独授权；
  STL/PCBA 的最终条款"仍在待定"。**不能当成开源硬件直接用。** 只有 `xgoduck_rl` 是
  Apache-2.0，所以第 2 条建议（搬 `add_backlash.py`）在法律上是干净的。
- **他们的训练栈跑不了我们这条路线。** mjlab + MuJoCo Warp + CUDA GPU，4096 envs。我们是
  CPU + mjbatch，一个 batch 一个编译模型。他们的 recipe（BAM + 齿隙 + 逐环境摩擦）需要能
  逐环境改模型的运行时——我们刚用 `Batch.expand` 补上了这一步，但 BAM 本身是 PyTorch
  张量运算，塞进 mjbatch 是另一件事。
- **`HLS1910` 是仿真内部命名，不是采购 SKU。** `docs/BOM.md` 自己澄清了这点。

## 对我们"只有一块 ESP32"的重新回答

上一轮我说「ESP32 够做控制环，不够做视觉和对话」。看到 XGO-Duck 的运行时之后要修一句：

**他们的四个策略（走 / 起身 / 抓取 / 翻滚）全部只吃 61 维本体感觉，不吃视觉。**
所以"ESP32 砍掉 Linux 那一半"损失的**不是策略能力**，而是：

- 网页 UI 与摇杆（可以换成串口/蓝牙手柄，或者干脆固定命令）
- 四个模型热切换（ESP32 装一个够用，换要重烧）
- 校准与舵机配置界面（一次性工作，可以写死）

而且我们的 61 维观测契约和他们的 `rl_core.build_obs` **逐字节兼容**。这意味着：
如果哪天搞到一台 XGO-Duck，`python/xgoduck_walk.onnx` 可以用我们的 `export_mcu.py` 转成
C 头文件跑在 ESP32 上（需要给导出脚本加一条 ONNX 入口，现在是只吃 `.pt`）。

## 该做但还没做的

1. 动作低通 α=0.45，在我们的延迟阶梯上验一遍——**最便宜，先做这个**
2. 齿隙模型移植（半天到一天，改动面大）
3. 确认官方/陆吾是否有整机或半成品套件可买，价格多少（我们此前的判断是"国内买不到"，
   现在这条判断的主语要改：XL330 买不到，HD1910 买得到）
