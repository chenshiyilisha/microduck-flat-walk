# DuckEMW（emwstudio）对照笔记

> 核验时间 2026-10-25。所有数字来自 GitHub API + 仓库内文件原文，不是搜索摘要。
> 仓库：https://github.com/emwstudio/DuckEMW

## 0. 一句话

同款 MicroDuck、同一套 mjlab/microduck_rl、**同一份 61 维部署契约**，从 2026-08-30 起做了六个项目
（极速 / 舞蹈 / 踩球 / 踩高跷 / 360°秋千 / 拔河），全部纯仿真、无真机。仓库里最重要的不是代码，
而是**两份完整的失败与迭代记录**，其中好几条正好命中我们当前的处境。

## 1. 核验到的仓库事实

| 项 | 值 |
|---|---|
| 星标 / fork | **138 / 23** |
| 创建 / 最后推送 | 2026-08-30 / **2026-09-29** |
| 体积 / 语言 | 34.6 MB / Shell |
| 默认分支 | `main` |
| 文件条目 | 87（其中 2 个是 submodule 指针） |
| License | 仓库未声明；README 称代码 Apache 2.0、模型 CC BY-SA-NC |

### ⚠️ 源码不在仓库里（这条决定它能怎么用）

`.gitmodules` 指向两个 fork：

```
third_party/microduck_rl          -> https://github.com/emwstudio/microduck_rl          (404)
third_party/microduck-playground  -> https://github.com/emwstudio/microduck-playground  (404)
third_party/microduck_rl          gitlink 8b4e1e5
third_party/microduck-playground  gitlink 80b3e8c
```

两个 URL 都是 **HTTP 404**（私有或已删）。所以：

- README 里那条 `git clone --recurse-submodules` **跑不通**；
- 他们自建的任务 `Mjlab-Sprint-Flat-MicroDuck`、`Mjlab-SimpleStairs-MicroDuck`，
  以及 `eval_sprint_speed.py` / `record_stilt_play.py` / `evaluate_swing360_checkpoint.py`
  **全部拿不到**；
- `autodl/setup.sh` 第 5 行的 `REPO_GIT=https://github.com/emwstudio/microduck_rl.git` 同样是死链。

**能拿到的**：`docs/`（三份记录）、`artifacts/`（checkpoint、评估 JSON、视频帧）、`autodl/`（脚本）、`dance/`。
**能跑的**：只有 `artifacts/simple_stairs/checkpoints/*.pt` 这三个权重是真实文件（各 4.84 MB，已入库）。

## 2. 权重契约：和我们完全一致（实测，不是推断）

下载 `artifacts/simple_stairs/checkpoints/v21c-stairs-ck1999.pt` 后直接 `torch.load`：

```
顶层键 : actor_state_dict, critic_state_dict, optimizer_state_dict, iter, infos
iter   : 1999
infos  : {'env_state': {'common_step_counter': 48000}}      # 2000×24，步进 24/iter 对得上

actor  : obs_normalizer._mean/_var/_std (1,61) → mlp 512-256-128 → distribution.std_param (14)
critic : obs_normalizer (1,76) → mlp 512-256-128 → 1
```

`61 / 76 / 14 / 512-256-128 / num_steps_per_env=24 / 带 obs normalizer / 带 optimizer state`——
与我们这轮 `Mjlab-Velocity-Flat-MicroDuck` **逐项相同**。也就是说这三个权重在**结构上**可以进我们的
`eval_velocity_in_sim.py`（它是爬梯策略，只在平地评，不保证会走）。

## 3. 可以直接拿走的东西

### 3.1 官方步态的实测标定（最有价值的一条）

他们用 FK 对**官方交替梯策略**做了全量统计（64 envs、1671 步）：

| 量 | 数值 |
|---|---|
| 脚 apex 净空 中位 | **66.6 mm** |
| p90 / max | 72.4 / 78.8 mm |
| 单脚最大抬升（关节限位 Monte Carlo） | **~170 mm**（策略只用了 ~46%） |
| 可靠迈步包络（全宽踏级、同侧间距 1 级） | **~25 mm**（24–26 mm） |

**这修正了我们自己探针的解读方式。** `tools/probe_leg_reach.py` 报「天花板 25.3 mm」，
它的提问是「脚在原地抬起、水平位移 ≤5 mm 时能升多高」——那是个**原地抬腿**问题，
不是抬脚上限。脚本 docstring 里其实早写了「直腿甩到 hip_pitch=90° 能抬 189 mm，但那不是一步」。
现在有了对照：真实步态 apex 净空 **66.6 mm**，是我们那个数字的 2.6 倍；运动学极限 ~170 mm。

⇒ 以后别再拿 25.3 mm 当「抬脚上限」来设奖励或判据。**平地行走的参照值要用 66.6 mm 那一档**，
「迈步能上多高的台阶」才用 25 mm 那一档。两个数是两个问题。

### 3.2 「站桩盆地」的四因诊断（和我们上一轮一模一样）

他们 sprint v1：**站桩 0.006 m/s**。归因四条：

1. **25% standing envs 白拿奖励质量**
2. **`air_time` 用 0.20 s 硬下限（阶跃函数）**——0.05 s 的行走步态永远够不到，全程奖励 ≈0.0001
3. **`action_rate` 权重 −1.0 摆腿税**
4. **upright 项过紧**

修法（v2→v3，实测 0.006 → 1.43 m/s）：

- `air_time` **前向门控**：× clamp(vx/cmd, 0, 1)，原地腾空不付钱（治「原地高抬腿刷 air_time」）
- track 权重提到 **4.0**，让它主导
- `init_velocity_prob=0.3` 逆向出生（高速前沿需要有在策略数据）
- track std 放宽到 sqrt(0.25) 保高速梯度

我们的 joy 那十版就是第 1、2、3 条的组合。**这轮 A 路跑的是上游原版 velocity 任务**，是否也踩了，
看 2000 iter 之后那一次评测就知道（见 §5）。

### 3.3 预算纪律：他们的「配方探索」档比我们便宜一个量级

AGENTS.md 第 3 条（他们自己的约定，归纳自上游用法）：

| 阶段 | 配置 | 用途 |
|---|---|---|
| 配方探索 | **1024 envs × 2000 iter** | 快速试；trick 类任务先 500–1000 看曲线 |
| 配方定稿 | 4096 envs × 4000 iter | 才用官方主训默认 |
| 评估 | 64–512 envs | 电池 |

而他们的纪录大训实际是 **512 envs × 13500 iter ≈ 7 h ≈ ¥13**（AutoDL 4090D ¥1.88/h）。
我们现在这轮是 **4096 × 12000 ≈ 11 h**，作为**第一次**跑——按他们的纪律，这个配置是「定稿后」才用的。
（不是说要立刻停：A 路是上游原版配置，没改过奖励，属于「照配方跑」而非「探索」。但下一轮换配方时，
1024×2000 起步。）

### 3.4 成本实录（可直接抄的价格锚点）

AutoDL 4090D ¥1.88/h：极速项目全程（基线+4轮迭代+13.5k大训+评估出片）**≈¥70**；
舞蹈 11 轮 **≈¥35**；篮球续训+验收 **≈¥5**；高跷 37 级课程 4.5h **≈¥8.5**；秋千 360 约 4000 轮 **≈¥12**。
教训：评估/渲染/导出优先挪 CPU 或无卡模式；一轮实验尽量一次开机干完。

### 3.5 度量设计：按出生条件分桶

他们的评估 JSON 每个 level 给三份：`ladder_spawn` / `floor_spawn` / `all`。
`floor_spawn_prob=0.5` 混在一起平均会把两种完全不同的难度抹平——我们评 `Mjlab-Velocity-Flat-MicroDuck`
时同理（站桩 envs 与跟踪 envs 混平均就没意义）。这个分桶口径值得照抄。

另外两条测量纪律，和我们这几天撞出来的完全一致：

- **评估指标决定你能看见什么**（他们的速度纪录是「早就破了才发现」，因为只盯均值/p90 没看瞬时峰值）
- **峰值要门控**：倾斜 <45° 才算，否则「摔倒前扑」会被记成高速

## 4. 三个静默坑（其中一个我们刚踩）

### 4.1 `--agent.max-iterations` 是**增量**，不是目标

`rsl_rl 5.0.1   runners/on_policy_runner.py:77-79`：

```python
start_it = self.current_learning_iteration      # 从 ckpt 恢复
total_it = start_it + num_learning_iterations
for it in range(start_it, total_it):
```

⇒ 从 `model_10000.pt` 续训、传 `--agent.max-iterations 12000`，会跑到 **22000**。无报错、无警告。
他们踩过（Phase 3 记录：「`--agent.max_iterations` 是「再训 N 轮」不是总数」）。

**我们自己的 `tools/resume_velocity.sh` 原来是错的**（`--agent.max-iterations ${ITERS:-12000}`），
等于「中断一次就多烧 10 小时」。已改成 `TARGET` 绝对目标、传余量，实测输出：

```
budget 750 -> 12000   (passing --agent.max-iterations 11250, NOT 12000)
```

**同时撤回我 08:20 那次的说法**：「续训时它会从 checkpoint 读出 current_learning_iteration 接上，
不会多跑」——前半句对，后半句错。读的是 `current_learning_iteration`，但它是**起点**，不是上限。

### 4.2 `--agent.load-run/load-checkpoint` 不带 `--agent.resume` 是**静默零操作**

他们 v15 以来所有「暖启动」其实都是**从零重训**，直到 v20c 才发现，白烧 ~¥3，且 v16–v18 的诊断
要打折重估。修法是启动时打三标记（`Loading checkpoint` / `Patch5 WARM START` / 无 `FROM SCRATCH` 警告），
并在 mjlab 里加了警告（他们 fork 的 commit 66e0587）。

我们的 `resume_velocity.sh` 一直显式带 `--agent.resume True`，没这个风险；但**手工敲命令时**要检查日志里
真的出现了 Loading checkpoint。

### 4.3 「加步数」会被证伪——但只在配方错了的时候

两处实证：
- `v2r`：`ck4000` vs `ck6200` **零进步**（「加步数」证伪）
- `v21` vs `v21c`：同配方再续 2000 迭代，12 级课表爬升 p50 8.8→8.8，「零回退也无增量」

含义：**如果 2000 iter 时评测显示行为没有起步，继续烧到 12000 不会有救**。这是 §5 那条判据的依据。

## 5. 对当前这轮 A 路的直接影响

当前状态：`vel_4096x12000_1025`，iter **989/12000**，3.1 s/iter，ETA ~09:46，显存 3.6 GB。

他们给的判据，可以直接用：

1. **在 2000 iter 左右做一次部署侧评测**（不看训练里的 reward 曲线）。看两件事：
   - 脚峰净空是否离开 2–3 mm 区间（参照 66.6 mm 那一档，至少该到 20–30 mm 量级）
   - 净位移是否 > 0.05 m/s（官方 walking 策略在 cmd 0.4 下实测只有 **0.164 m/s**——**别拿 0.4 当及格线**）
2. 若两项都没动 ⇒ 按他们的实证，这不是「步数不够」，是配方问题，应停掉改配方（1024×2000 探索档）。
3. 若已开始成型 ⇒ 继续，但**别指望 12000 是必须的**：他们 4000 iter 就到平台期了。

**一个校准警告**：官方出厂行走策略 `alpha_walking.onnx` 在 cmd 0.4 下实测 **0.164 m/s**，
cmd 1.0 下 0.63 m/s 且 yaw 漂移 >50°。也就是说这个机器人的「官方会走」本身就严重欠跟踪。
我们如果训出 0.15–0.2 m/s，那是**正常**，不是失败。

## 6. 不建议照抄的

| 项 | 原因 |
|---|---|
| 他们的自研 sprint 配方（v1–v4） | 自己放弃了（plateau ≤1.43），改抄 Hannes `running_forward_progress`（线性 clamp(vx,0,cap)/cap，权重 5.0 + 命令速度双升课程 +0.15/750 轮 + 3% 站立桶 + 12195 轮） |
| `simple_stairs` 的 21 版奖励手术 | 该线到 v21c 仍未成：25 级末级「果断前扑」不稳、台面持续行走未成型。可读过程，不可当结论 |
| 他们的 `autodl/setup.sh` 直接跑 | `REPO_GIT` 是 404 死链；有用的是里面的环境细节：`UV_HTTP_TIMEOUT=600`、清华镜像、`HF_ENDPOINT=hf-mirror.com`、`uv python install 3.12`、headless 渲染用 `MUJOCO_GL=osmesa`（容器里 EGL 不可用）、`git clone` 被杀会留僵尸进程 `rm -rf` 目标目录 |
| 把 `artifacts/*.pt` 当「能走的起点」 | 它是**爬梯**策略，平地上 512 env 评估 fall≈0.29、爬升 p50 8.8 级；能走多远未知，必须实测 |

## 7. 结论

这个仓库对我们的价值排序是：**失败诊断 > 度量标定 > 成本/运维纪律 > 权重 > 代码**（代码为零）。

三条立刻可用的：

1. **66.6 mm** —— 官方步态真实抬脚净空；我们那个 25.3 mm 是「原地抬腿」口径，不是上限。
2. **max_iterations 是增量** —— 我们续训脚本已修（否则中断一次多烧 10 小时）。
3. **2000 iter 判决** —— 行为不起步就不是步数问题。别用 12000 去赌一个可能错的配方。
