# joy 配方落地：不重写，直接 apply 上游补丁

> 2026-10-24。上一轮结论是「joy 的奖励结构能治站桩」，这一轮把它变成能跑的代码。
> 关键决定：**不把 4 项奖励手工搬进我们自己的 `train_ppo.py`，而是把 Duckverse 的
> `continuous_joy.patch` 直接落到 mjlab 环境里** —— 因为上游写好了、带测试、
> 而且 `continuous_joy.onnx` 就是从这个任务训出来的，可以直接对照。

---

## 1. 为什么改路线

上一轮的计划是「6 处改动、约 60 行、搬进 `train_ppo.py`」。改主意有两个理由：

1. **我们自己的 `train_ppo.py` 观测里没有 head/body 指令通道**，而 joy 的相位是通过
   这两个通道喂给策略的（`joy_head_command` 4 维 + `joy_body_command` 6 维）。
   硬搬要改 OBS_DIM、网络输入、ONNX 导出契约 + MCU 侧 `MD_HIDDEN`。
2. **mjlab 环境已经装好了**，而且它的 `Mjlab-Velocity-Flat-MicroDuck` **观测项就是
   `base_ang_vel, projected_gravity, joint_pos, joint_vel, actions, command,
   head_command, body_command`** —— 与 joy 的 61 维契约**逐项相同**，连维度都一致。
   缺的只是把这三个 term 的 `func` 换成 `joy_*` 版本，而上游补丁正是这么做的。

顺带修正一个我上一轮的说法：**mjlab 这边的网络本来就是 `(512, 256, 128)`**
（`MicroduckRlCfg.actor.hidden_dims`），不是我说的「我们只有 128-128」。128-128 是
我们自己那套 numpy 实现的。所以走 mjlab 路线**不需要换网络**。

---

## 2. 落地过程（`tools/apply_joy_patch.py`）

`git apply` / `patch -p1` 都不行：补丁锚在 `5946fd9`（09-01），我们的 `develop` 快照
`mdp.py` 是 **7706 行**，补丁期望 **8248 行**，每个 hunk 都对不上。

但看 hunk 的形状就清楚了 —— 全是两种情况：
- **文件末尾追加**（`mdp.py`、`__init__.py`）
- **整个新文件**（`microduck_joy_env_cfg.py`、`tests/test_joy_cfg.py`）

**都不需要缺失的上下文**，只需要「新增行，按顺序」。所以脚本从补丁里**解析**出 `+` 行
（而不是我手抄 200 行奖励代码，那是最容易出静默 bug 的方式）：

| 文件 | 处理 | 结果 |
|---|---|---|
| `tasks/mdp.py` | 末尾追加 | +87 行（7 个 reward/command 函数 + `JoySmoothPositionAction` + `initialize_joy_servo_targets`） |
| `tasks/__init__.py` | 末尾追加 | +9 行（注册 `Mjlab-Joy-Flat` / `-JoyPD-` / `-JoySmoothPD-` 三个任务） |
| `tasks/microduck_joy_env_cfg.py` | 新建 | 102 行 |
| `tests/test_joy_cfg.py` | 新建 | 64 行 |
| `scripts/export.py` | **故意跳过** | hunk 在函数中间，追加会破坏语法；它只加 ONNX metadata，导出时再单独处理 |

### 两处 baseline-only 符号

上游 joy cfg 引用了 `MICRODUCK_STANDUP_PD_ROBOT_CFG`，这个常量**在 develop 上不存在**。
两处：import 行、`deepcopy(...)` 表达式。都要改，否则 import 就炸。

替代是现成的：`MICRODUCK_STANDUP_ROBOT_CFG` + 紧跟的
`if pd_actuators: cfg.scene.entities['robot'].spec_fn = joy_pd_spec`，而 `joy_pd_spec()`
本身就做了「forcelimited + ±0.6405 Nm + solref」这件事。所以直接删掉那个三元分支。

### 一个安装陷阱

`uv pip install --no-deps .upstream/microduck_rl-develop` 是**复制**安装，改动源码目录
不生效（`ModuleNotFoundError: microduck_joy_env_cfg`）。没有重装，而是用
`PYTHONPATH=.upstream/microduck_rl-develop/src` 让源码目录在 `sys.path` 上优先 ——
两份是同一份代码，可逆、不用碰 site-packages（重装会走 `uv_build`，而这个项目钉了
`requires-python <3.13`，本 venv 是 3.13）。

---

## 3. 验证：用上游自己的测试

```bash
PYTHONPATH=.upstream/microduck_rl-develop/src \
  .venv-mjlab/Scripts/python.exe -m pytest tests/test_joy_cfg.py -q
# 4 passed in 20.19s
```

这 4 条断言比我自己写的任何检查都硬，尤其第 10 行：

```python
assert list(c.observations['actor'].terms) == [
    'base_ang_vel','projected_gravity','joint_pos','joint_vel',
    'actions','command','head_command','body_command']
```

**顺带更正一处引用错误**：我上一轮在 `probe_joy_policy.py` 和文档里写「obs 顺序来自
`tests/test_joy_cfg.py:242`」——那个文件总共 **64 行**，断言在**第 10 行**。已改。
（这类「引用一个不存在的行号」和之前「引用不存在的配置文件」是同一种毛病。）

另外三条断言覆盖了：`decimation × timestep = 0.02`、`pose commands` 连续且有界
（`|Δh| < 0.04`、`|h| ≤ 0.24`）、PD 传输的 `±0.6405 Nm` 力限与 `geom_margin == 0`、
以及 smooth conditioner 的逐帧递推 `previous + clip(.25(raw-previous), ±.08)`。

---

## 4. 冒烟实测（2048 envs，6 iter）

| 任务 | 执行器 | 物理/控制 | s/iter | 600 iter 预计 |
|---|---|---|---:|---:|
| `Mjlab-Joy-Flat-MicroDuck` | **BAM** | 0.002 s / 100 Hz | **3.65** | ≈ 37 min |
| `Mjlab-JoySmoothPD-Flat-MicroDuck` | **位置伺服**（±0.6405 Nm, kp 0.55）+ conditioner | 0.001 s / 50 Hz | **5.82** | ≈ 58 min |

奖励项**确实在算而且在变**（这是必须单独看的一项，不能只看总奖励）：

```
Episode_Reward/joy_feet:     0.7383 → 0.7606     (权重 12)
Episode_Reward/joy_head:     0.2337 → 0.2438     (权重 3)
Episode_Reward/joy_balance:  0.1954 → 0.2062     (权重 5)
Episode_Reward/joy_drift:   -0.0429              (权重 100)
Episode_Reward/pose:         0.0059              (权重 0.15，被压到底)
```

**8 项被删的确实不在了**：`track_linear_velocity` / `track_angular_velocity` / `air_time` /
`foot_clearance` / `foot_swing_height` / `head_pose_tracking` / `head_pose_bias` /
`body_pose_tracking` 全部消失，剩下 `body_ang_vel` / `angular_momentum` / `dof_pos_limits` /
`action_rate_l2` / `foot_slip` / `self_collisions` / `upright` / `pose` + 4 项 joy。

---

## 5. ⚠️ 一处必须更正的数值：站桩在 `joy_feet` 上不是 0 分

我上一轮说「`joy_feet` 对站桩给 ≈0.0006，权重 12 → 丢 12 分」。**错了。**
逐字照抄 `joy_foot_rhythm` 做解析积分（20 万点一个周期）才看清：

| 行为 | `joy_feet` | ×12 |
|---|---:|---:|
| 零动作站桩（双脚 h=0） | **0.3656** | **4.39** |
| 完美踏步（各自跟自己的相位） | **1.0000** | **12.00** |
| 原地一起蹦（双脚同相） | 0.3833 | 4.60 |
| **只抬右脚、左脚永不抬** | **0.6818** | **8.18** |
| 双脚恒定 5 mm | 0.3754 | 4.51 |
| 双脚恒定 12 mm | 0.0970 | 1.16 |

差值是 **7.61 分**，不是 12 分。我错在只看了「半个周期」：左脚 `target` 在
`sin p < 0` 的那半周期只有 0.5 mm，而站桩 `h=0` 对 0.5 mm 的误差是
`exp(-(0.5/9)²) ≈ 0.997`，所以**一半时间是满分的**；只有 `sin p > 0` 那半周期
（target 抬到 24.5 mm）才掉到 0.0006。两脚取乘积、整周期平均 = 0.366。

### 但这不影响结论，反而说明为什么它是好的

1. **差 7.61 分足够决定行为**（整套表总分约 20），而且**没有别的项因为这些动作被扣**：
   踏步时 `joy_balance`（站桩/踏步都满分）、`joy_head`（跟自己的指令，不是跟常量）、
   `pose`（被压到 0.15）、`upright` 都不冲突。这就是「严格超集」的实际含义。
2. **「原地一起蹦」只有 4.60**（和站桩 4.39 几乎一样）—— 设计对了：蹦不是踏步。
3. **「双脚恒定 12 mm」掉到 1.16** —— 悬空不算踏步，也对。

### 顺带发现一个真实漏洞

**「只抬右脚、左脚永不抬」拿 8.18 = 满分的 68%。** 因为左脚 `target` 一半时间就是 0，
`h=0` 就满分；右脚老老实实跟相位就满分；乘积 = 0.68。

也就是说 **`joy_feet` 不惩罚「一只脚一直举着」**。挡住它的是**验收门槛**
`(feet_peak > 0.008).all()`（双足都要求）。所以那 10 条门槛不是可选项 ——
**没有它们，"踏步"可以退化成"金鸡独立"而奖励仍然很高。**

---

## 6. 现在的状态与下一步

**已启动**：`Mjlab-JoySmoothPD-Flat-MicroDuck`，2048 envs，600 iter，约 58 min。
选 SmoothPD 而不是 BAM 的理由：
- 与 `continuous_joy.onnx` 同族（它的 `run_path` 是 `microduck_joy_smooth_pd/model_300.pt`）
- 与真机一致（位置伺服、±0.6405 Nm、kp 0.55、target conditioner α=.25 / ±.08 rad）
- 训完可以直接用 `tools/probe_joy_policy.py` 的**Duckverse 9 条门槛**评测，并与 Duckverse ONNX 对照

**验收（三条一起看，缺一条都不算数）**：

1. `out/probe_joy_official.txt` 那 9 条 gate 全 PASS（`joy_passed=True`）
2. 与 Duckverse `continuous_joy.onnx` 同口径对照：抬脚 16.36/17.34 mm、周期 0.86-0.87 s、
   净位移 ~17 mm（**都是原地踏步，不是走**）
3. 训练日志里 `joy_feet` 从 ~0.74 爬到 **>0.95**，且 `Episode_Termination/fell_over`
   明显下降（初始 45/iter @ 2048 envs）

**过了这三条，才轮到 P0 的 `forward_progress`** —— 那时「第一步」已经跨过去了。

---

## 7. 复现

```bash
# 1) 落地补丁（幂等，重复运行会跳过）
.venv-mjlab/Scripts/python.exe tools/apply_joy_patch.py

# 2) 上游测试
cd .upstream/microduck_rl-develop
PYTHONPATH=$(pwd)/src ../../.venv-mjlab/Scripts/python.exe -m pytest tests/test_joy_cfg.py -q

# 3) 训练
bash tools/train_joy.sh smooth 2048 600     # 位置伺服，部署一致
bash tools/train_joy.sh bam    2048 600     # BAM 植物，快 1.6 倍

# 4) 验收（训练产出的 ONNX/pt 用 Duckverse 9 条门槛测）
python tools/probe_joy_policy.py --onnx <exported.onnx> --plant servo \
    --seconds 8 --joint-vel-delay 1 --json-out out/probe_joy_trained.json
```
