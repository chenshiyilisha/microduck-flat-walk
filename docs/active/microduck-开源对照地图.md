# MicroDuck 开源对照地图

> 核验时间 2026-10-25。所有数字来自 GitHub API / HF API / 仓库原文，不是搜索结果摘要。
> 覆盖面：GitHub 搜 `microduck` 共 **487** 个仓库；HuggingFace 搜 `microduck` 共 **100+** 个权重。

## 0. 一句话

有，而且有**一个专门回答我们当前这个问题**的：上游 issue **#46** 加一个复现它的诊断仓，
作者用的是**单张 RTX 4070 Laptop 8GB + Windows**——和我们一模一样。

结论先说：**同一个 commit（`29e887e`）上，四拨人各跑了一遍，`error_vel_xy` 都卡在 0.42–0.43。
这不是「我们训不出来」，是这个配方的天花板。** 有人找到了打破它的方法（降到 0.21），
也有人证明这个指标本身高估约 3 倍。

## 1. 最该先看的：issue #46 + 诊断仓

### 1.1 上游 issue

[pollen-robotics/microduck_rl#46](https://github.com/pollen-robotics/microduck_rl/issues/46) —
**open**，2026-09-10，作者 `ysaima`，2 条评论，**至今没有官方回复**。

标题就是我们的症状：*「Velocity-family training converges to standing-in-place across all
reward/curriculum variants — full diagnostic matrix」*

他的环境：commit **`29e887e`**、`uv.lock` 固定（warp-lang 1.12.0 / mujoco 3.10.0 / mjlab 1.3.0 /
torch 2.9.1+cu128）、**4096 envs**、4×L4。

他的症状与我们的 joy 十版**逐项对应**：
`error_vel_xy` 卡在 ~0.43（≈ 平均 |cmd|）、20 s 位移 0.1–0.6 m、`air_time ≈ 0.002`（脚不离地）、
奖励分项里 `upright`(2.0) 与 `head_pose_tracking`(2.0) 是站着不动就能拿满的主导项。

他做了 **7 组对照**：关掉全部非跟踪奖励 / 奖励爬坡 / 抬脚奖励一开始就满权重 / 力矩翻倍 /
关掉推挤 + 强制恒定前进命令 / 拿官方 `alpha_walking.onnx` 当参照 / 版本漂移。全部没走出去。
其中「抬脚奖励满权重」那条：`error` 一度到 0.10、位移 0.52 m，**到 11300 轮又退回站立**。

### 1.2 诊断仓（同一个硬件）

[Qi-hub-dot/microduck-locomotion-diagnosis](https://github.com/Qi-hub-dot/microduck-locomotion-diagnosis)
（2★，2026-09-18，中文全记录）——他在 **RTX 4070 Laptop 8GB / Windows / 4096 envs / 5000 轮**上
复现了同一个失败（`error_vel_xy` 0.42 vs 报告人 0.43），然后找到三条前者没覆盖的东西：

**① `air_time` 的门控只看「有没有指令」，不看「有没有前进」。**

```python
# mjlab/tasks/velocity/mdp/rewards.py:L209  feet_air_time()
if command_name is not None:
    total_command = torch.norm(command[:, :2], dim=1) + torch.abs(command[:, 2])
    scale = (total_command > command_threshold).float()
    reward *= scale          # ← 只比较指令大小
```

而我们的配置把它设成 `0.01`（`microduck_velocity_env_cfg.py:334`），权重 **3.0**（`:333`，
全部正项里最大）。⇒ **被命令前进、却原地踏步的策略，照样收这份钱。**

**② 侧向漂移是前向的两倍，而跟踪奖励对两个轴等权。**
恒定指令 `(+0.30, 0.00)` 时 `root_link_lin_vel_b` 实测：

| step | 前向 | 侧向 |
|---|---|---|
| 3 | +0.044 | −0.056 |
| 5 | +0.072 | −0.149 |
| 7 | +0.112 | **−0.230** |

⇒ 它**不是不会走，是横着滑走**。他的原话：单独测位移，20 s 走 7–9.5 m、1000 步只摔一次、轨迹连续。
改法：侧向误差 ×3、`track_linear_velocity` 权重 2.0→4.0 ⇒ 侧向降到 1/5，`error_vel_xy` 0.35→**0.21**。

**③ `error_vel_xy` 高估约 3 倍。**

```python
# mjlab/tasks/velocity/mdp/velocity_command.py:L64
self.metrics["error_vel_xy"] += (
    norm(vel_command_b[:, :2] - root_link_lin_vel_b[:, :2], dim=-1) / max_command_step
)
```

两个都是体坐标系（没搞错），问题在口径：它把**五种指令模式**（standing / heading / world / forward /
plain）混在一起平均，而且是**整回合累积**，把 reset 的加速段（误差 ~0.30）和踉跄都算进去。
同一个 checkpoint 逐帧稳态测 **0.07**，日志读 **0.206**。

### 1.3 三条对我们直接的影响

| # | 事实 | 我们该做什么 |
|---|---|---|
| 1 | 同一 commit 上所有人的 `error_vel_xy` 都卡 0.42–0.43 | **跑出 0.42 不等于失败**，那是默认配方的天花板 |
| 2 | `error_vel_xy` 高估 ~3×，且分不清哪种模式在坏 | 判据改用**实测位移 / 分轴速度**，不用这个数 |
| 3 | 失败形态是「原地踏步收钱」或「横着滑」 | 必须**分轴**判，只看合速度看不出来 |

**评测脚本已按此改**（`tools/eval_velocity_in_sim.py`，本次改动）：

- 新增闸门 `translates_forward`（`dx/期望位移 ≥ 0.2`）——直接区分「原地踏步」与「真在走」
- 新增闸门 `not_sideways`（`|dy|中位 ≤ 0.5·|dx|`）——抓「横着滑」
- `error_vel_xy_le_0.15` → **`error_vel_xy_le_0.25`**，并在注释里写明 3× 偏差与 0.206 那个实测值；
  **0.15 会把一个确实会走的策略判成失败**

## 2. 同任务的完整训练档案（Datawhale）

HF **`Datawhale/Microduck-RL-4096x6000`** —— 这是我们能找到的、与当前这轮**逐项同构**的公开档案：

| 项 | 值 |
|---|---|
| 任务 | `Mjlab-Velocity-Flat-MicroDuck` |
| 上游 commit | `29e887e`（与 issue #46、DuckEMW 同一个 pin） |
| `provenance/microduck_rl.diff` | **`--- git diff ---` 为空**（未改一行上游代码） |
| 配置 | 4096 envs × 6000 iter，`iterations: 10` / `ls_iterations: 20`（上游默认，我们改成了 100/50） |
| 墙钟 | **01:27:41** |
| 末轮 | reward 119.57 / episode **972.52** / `error_vel_xy` 0.4167 / `air_time_mean` **0.1216** / `peak_height_mean` 0.0141 |
| 存档 | `model_0` … `model_5999`，**每 500 一个，共 15 个** |
| 其它 | `configs/env.yaml`（57 KB 完整配置）、`agent.yaml`、TensorBoard events、完整训练日志 gz、walk/编舞/milestone 视频、ONNX |

**注意**：它的 `error_vel_xy` 是 **0.4167**，和 issue #46 里「站着不动」的 0.43 几乎一样，
但它的 `air_time_mean` 是 0.1216（在抬脚）。⇒ 这份档案大概率正是 **「会走、但不按指令走」**
那个状态——§1 说的第二种失败形态。**不要把它当成「配置对了就自动会走」的证明。**

配套中文教程：**`datawhalechina/every-embodied`**（4213★）第 05 章
「OpenDuckMini与Microduck双足强化学习」，72 KB 正文，含训练/回放/ONNX 导出/RDK X5 部署/8 条常见失败排查。
其中引了官方经验：**「4096 个环境下约 1–2 小时可以看到可用步态」**。

## 3. 官方策略库

HF **`pollen-robotics/microduck-policies`**（30421 次下载，12 个 ONNX，**没有 .pt**）：

```
alpha_walking  alpha_stand  alpha_sitstand  alpha_ground_pick
ball_kick_left  ball_kick_right  roller  roller_crouch  roulade  velstand
manifest.json
```

已知实测（别人测的，不是官方声明）：

- `alpha_walking` 在 cmd 0.4 下 → **0.164 m/s**；cmd 1.0 → 0.63 m/s 且 yaw 漂 >50°（DuckEMW Phase 0）
- 部署侧（`duck-sim`，daemon-v0.15.0）：**几乎不转弯**（issue #46 第 2 条评论）

⇒ 所谓「出厂基线 0.4 m/s」是命令值，实际跟踪很差。**我们训出 0.15–0.2 m/s 属正常。**

## 4. 可续训的 `.pt`（想从别人肩膀上起步时）

| 权重 | 内容 | 备注 |
|---|---|---|
| `HannesVonEssen/microduck-running` | `checkpoint.pt` + `lineage/iteration-11748/{checkpoint.pt, policy.onnx, preview.mp4}` + 6 份 eval JSON（nominal/stress/high-grip × backlash）+ `SHA256SUMS` + `manifest.json` | 唯一带完整 lineage + 抗齿隙评估的 running 权重 |
| `zhoumiaosen/microduck-straight-running` / `microduck-running` | .pt | 社区直线跑 |
| `apirrone/microduck-walk-antoine` / `velstand` | .pt | apirrone 是 Pollen 联创 |
| `Brunocho/microduck-walk` / `arabellako22/microduck-walk-seed42` / `witcheer/microduck-walk-flat` / `cdeplanne/microduck-walk*` | .pt | 平走，未评估 |
| `HannesVonEssen/microduck-{climb,chimney-climb,long-jump,stilts,swing,basketball}` | .pt + eval | 技巧类 |

⚠️ **大量空壳**：`minjunglee27/mjlab-velocity-flat-microduck-*`、`huggsook/mjlab-velocity-flat-microduck-*`
等一批同名仓库**只有 `.gitattributes`，零文件**。按名字筛选会白下。

## 5. 换引擎（不是换配方）

| 仓 | 星 | 说明 |
|---|---|---|
| `Macmachi/microduck-rl-genesis` | 6 | Genesis + AMD ROCm，执行器模型与上游 **bit-exact** 对齐 |
| `kabilankb/isaaclab-microduck` | 14 | Isaac Lab 3.0 / Newton MJWarp，locomotion + ball-kick + 双鸭 |
| `5usu/IsaacLab`（`microduck-port` 分支） | — | Isaac Lab 扩展，walking/kicking/parkour |
| 另有 PhysX 版（37 个环境）、`microdux`（JAX/MJX）、`MotrixSim` 版 | — | 见 awesome 列表 |

⚠️ 前一轮已确认：这些大多和我们**同源**（MuJoCo Warp / MJWarp），换过去不是「物理更真」。

## 6. 没有 CUDA / 小显存的路（对我们最实用）

| 仓 | 星 | 说明 |
|---|---|---|
| `jonathanhawkins/microduck-lab` | 144 | **普通 Mac 无 CUDA** 训练 + 浏览器实时看学习过程 |
| `bsprenger/microduck-rl-torch` | 37 | PyTorch 原生重写（`mujoco-torch`），工作流与上游同 |
| `tailong-wu/microduck-mjbatch` | 2 | CPU 批处理 MuJoCo PPO（C++ 线程池），完全不用 GPU |
| `craigm26/duckbatch` | 0 | **4 GB 笔记本 GPU + 预注册 kill order 剪枝多次小尝试** ← 方法论最贴我们的处境 |
| `xinhuagu/my-microduck-journal` | 2 | 单张消费级 GPU 从零重训全部技能，**每个数字和死胡同都写下来** |

这些的价值不在「换栈更快」，而在**它们不占我们那张 8 GB 卡**——配方探索可以挪出去跑。

## 7. 索引仓

`joeynyc/awesome-microduck`（**173★**，2026-10-24 更新）：分类含
Simulation and Training（**50+** 条）、Policies and Skills、Datasets and Benchmarks、
Agent Tools and MCP、Community Hubs。想自己往下翻就从这里进。

---

## 8. 更正：上一条里 66.6 mm 的说法我讲错了

上一条说「平地行走的参照值要用 66.6 mm 那一档」。**撤回。** 核对上游配置后：

| 量 | 值 | 出处 |
|---|---|---|
| 上游 flat 的抬脚奖励目标 `foot_clearance.target_height` | **20 mm** | 我们 cfg `:352`（`foot_swing_height` 同为 0.02） |
| 实际训练出来的平地策略 `peak_height_mean` | **14.1 mm** | Datawhale `model_5999` |
| 爬 25 mm 台阶的策略脚 apex 净空 | 66.6 mm | DuckEMW FK 实测 |
| 我们的探针：**原地**抬腿（｜dx｜≤5 mm）天花板 | 25.3 mm | `tools/probe_leg_reach.py` |

⇒ **平地参照是 14–20 mm，不是 66.6 mm**（那是爬梯策略）。66.6 mm 只在「要跨台阶」时才适用。

而且这张表反而解释了我们一直觉得别扭的事：上游要 20 mm，而这台腿**原地不动**的极限是 25.3 mm——
**目标就压在天花板上**。这既解释了为什么抬 20 mm 这么费劲，也解释了为什么 joy（原地踏步）特别难：
它要的正是这个几乎贴着极限、且没有任何位移可以借力的动作。

## 9. 对当前这轮的判决点

现在的状态：iter ~1210/12000，3.1 s/iter，ETA 09:32。

按 §2 的官方经验（4096 envs 1–2 小时出可用步态）和 §1 的天花板证据，把判决点**提前**：

1. **iter ≈ 2400（约 10:25）** 跑一次评测，看三件事：
   - `air_time_mean` 是否离开 0（抬脚了吗）
   - `translates_forward`：`dx/期望位移` 是否 ≥ 0.2（真在走，还是原地踏步收钱）
   - `not_sideways`：`|dy|` 是否 ≤ 0.5·`|dx|`（是不是横着滑）
2. 若命中「原地踏步」或「横着滑」⇒ 按 §1.2 的三处改法（`air_time` 加 30% 前进门控 + 侧向 ×3 +
   track 4.0），重跑；**不要加步数**（issue #46 的 11300 轮、DuckEMW 的 ck4000 vs ck6200 都是零收益）。
3. 若三项都过但速度低 ⇒ 正常（出厂策略也只有 0.164 m/s），继续跑，但**在 6000 停**：
   再往后没有人拿到过增量。
