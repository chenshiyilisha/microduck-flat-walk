# MicroDuck 能不能用英伟达的仿真平台训练

> 结论时间：2026-10-25
> 触发问题：「训练可以用英伟达的仿真平台吗」
> 一句话答案：**能，而且 NVIDIA 的 Isaac Lab 官方仓库里已经有 MicroDuck 了（2026-10-15 合入）；
> 但你现在的 mjlab 训练链跑的物理内核本来就是英伟达的（MuJoCo Warp / warp-lang），
> 换过去解决的不是「物理更真」，而是「框架生态」。**

---

## 1. 先破除一个误会：你已经在用英伟达的平台了

当前训练环境（`.venv-mjlab`）实测：

| 包 | 版本 | 出品方 |
|---|---|---|
| `warp-lang` | 1.12.0 | **NVIDIA**（`developer.nvidia.com/warp-python`） |
| `mujoco_warp` | 3.7.0.1 | MuJoCo 官方 GPU 版，跑在 NVIDIA Warp 上 |
| `mujoco` | 3.7.0 | Google DeepMind |
| `mjlab` | 1.3.0 | mjlab 项目（MuJoCo 版 Isaac Lab API） |
| `rsl_rl` | 5.0.1 | ETH RSL |

`mujoco_warp` 就是把 MuJoCo 的求解器用 **NVIDIA Warp** 重写成 GPU kernel。所以：
**矩阵并行、接触求解、梯度回传全在 NVIDIA 的 Warp 上跑。** 不是「非英伟达方案」。

而 Isaac Lab 6.2 的 MicroDuck 任务用的是：

```python
# contrib/microduck/flat_env_cfg.py:10
from isaaclab_newton.physics import MJWarpSolverCfg, NewtonCfg, ...
```

`MJWarp` = **MuJoCo Warp**，同一个求解器。**不是 PhysX。**

> 这条要紧：以为「换到 Isaac 平台 = 换更真实的物理引擎」是错的。
> 两边是**同一个接触求解器**，只是一个在 mjlab 壳里、一个在 IsaacLab + Newton 壳里。

---

## 2. Isaac Lab 里确实已经有 MicroDuck（不用自己移植）

**出处核实**（GitHub API，非搜索引擎）：

- 仓库：`isaac-sim/IsaacLab`，default_branch = `main`，8457 ★
- 文件树命中 22 个路径（`git/trees/main?recursive=1`）
- 合并 PR：**#8270「[Newton] Add BAM servo actuator and MicroDuck walking tasks」**
  - 作者 `AntoineRichard`，`author_association: COLLABORATOR`
  - 合入时间 **2026-10-15T00:42:01Z**
  - 规模：4583 additions / 72 files / 96 commits
  - 前身：#8161 / #8265 / #8266 / #8267（四个 PR 合并而来）

关键路径：

```
source/isaaclab_assets/isaaclab_assets/robots/microduck.py        # 资产（141 行）
source/isaaclab_tasks/isaaclab_tasks/contrib/microduck/
    ├── __init__.py            # IsaacContrib-Velocity-Flat-MicroDuck / -Rough-MicroDuck
    ├── flat_env_cfg.py        # 478 行
    ├── rough_env_cfg.py       # 108 行
    ├── mdp/{actions,commands,events,observations,rewards,terminations,curriculums}.py
    └── agents/rsl_rl_ppo_cfg.py
examples/demos/microduck_warehouse.py
source/isaaclab_tasks/test/test_microduck_velocity.py
```

**部署契约与我们完全一致**（这是最重要的一条）：

| 项 | mjlab（我们） | Isaac Lab | 一致 |
|---|---|---|---|
| actor 观测 | 61 | 61（注释原话 "the 61-wide deploy contract"） | ✅ |
| critic 观测 | 76 | 76（"Privileged observations (76 values)"） | ✅ |
| 动作 | 14 关节位置 | 14，`preserve_order=True`，关节序 left leg→neck/head→right leg | ✅ |
| 控制频率 | 50 Hz | `dt=0.005 × decimation=4` = 50 Hz | ✅ |
| PPO 网络 | 512-256-128 / ELU | `hidden_dims=[512,256,128]` / elu | ✅ |
| 训练库 | rsl_rl | rsl_rl | ✅ |

PR 原文：

> Both keep its 14-joint action order, 61-value actor and 76-value critic inputs, 50 Hz control,
> rewards, command sampling, randomization, curricula, and PPO settings, **so existing checkpoints load.**

⇒ **我们训出来的 checkpoint 可以直接丢进 Isaac Lab 评。** 反过来也行。

---

## 3. 硬件：这台 8 GB 笔记本跑得动，比想象中轻

`docs/source/isaaclab/installation.rst` 原文要求：

| 项 | 要求 | 本机 | 判定 |
|---|---|---|---|
| Python | 3.12（uv 管理） | 需新建 | ✅ 可做 |
| 平台 | Ubuntu 22.04+ / **Windows 11 x86_64** | Windows | ✅ |
| GPU | Turing 或更新（compute cap ≥ 7.5） | RTX 4070 Laptop，**8.9** | ✅ |
| 驱动 | Windows x86_64：**595.97** | **621.01** | ✅ |
| 显存 | 按任务/并行数定 | 8188 MiB | 待实测 |

**最重要的一句**（同文档）：

> **Isaac Lab installs Newton by default.** The standard installation runs **without Isaac Sim**.
> … Isaac Sim's workstation memory requirements **do not apply to a Newton-only installation**.
>
> Optional Isaac Sim：plan for at least **32 GB RAM, 16 GB VRAM**.

⇒ 那套「32 GB 内存 / 16 GB 显存」是**装 Isaac Sim + PhysX 才需要**的。
Newton-only 训练根本不用装 Isaac Sim，8 GB 卡够。

已知 Windows 坑（两个 issue 均已 closed 修复）：
- 「[Bug Report] Windows: Newton CUDA graph capture hangs in a Warp allocation」
- 「Fix Windows hangs by warming up Newton before CUDA graph capture」
- 另外安装前必须开 Windows **long path** 支持。

启动命令形态（文档给的）：

```
uv run isaaclab train --rl_library rsl_rl --task IsaacContrib-Velocity-Flat-MicroDuck physics=newton_mjwarp
```

---

## 4. 判决实验：Isaac Lab 那条改动，救不了抬脚

### 4.1 动机

Isaac Lab 版最显眼的一条差异，是**求解器预算**从 microduck_rl 的 10/20 提到 100/50。
它的注释点名了我们的处境：

```python
# contrib/microduck/flat_env_cfg.py:441-444
# microduck_rl's 10 iterations stop some contact solves short;
# MJWarp exits once every world converges.
iterations=100,
# The original 20-step budget exhausts line search with the current MJWarp solver.
ls_iterations=50,
```

而**我们的 flat 任务用的是 10/20**。证据 —— `mjlab_microduck/tasks/microduck_velocity_env_cfg.py:745-769`：

```python
if not rough:
    cfg.scene.terrain.terrain_type = "plane"     # ← 我们走这条，下面加固全部跳过
else:
    cfg.sim.nconmax = 200                        # was 35
    cfg.sim.mujoco.iterations = 30               # was 10
    cfg.sim.mujoco.ls_iterations = 50            # was 20
```

**加固只写在 `rough` 分支里**。我们跑 flat，所以 `iterations=10`、`ls_iterations=20`、`nconmax=35` 原封不动。
（讽刺的是同一套加固，上游自己在 `microduck_sitstand_env_cfg.py:673-679` 也写过，理由是
"Default nconmax=35 and solver iters=10 overflow the contact solver → NaN"。）

于是有个很诱人的假设：**抬不起脚 = 脚掌接触解算不足 = 加迭代就好**。
这个假设**零训练成本**可判，只需同一 checkpoint 重放两次。

### 4.2 做法

给 `tools/eval_velocity_in_sim.py` 加了 `--solver-iters` / `--solver-ls` / `--solver-ncon`
（`override_solver()`，打印 before/after，写进 JSON 的 `solver` 字段）。

- checkpoint：`logs/rsl_rl/microduck_joy_smooth/2026-10-24_07-57-43_.../model_599.pt`
  （就是那个「站得住但抬不起脚」的策略）
- 规模：64 envs × 8 s，`vx=+0.40`，`cuda:0`，其余全同
- 变量：只有 `sim.mujoco.iterations` 与 `ls_iterations`

### 4.3 结果

| 指标 | 基线 10 / 20 | 对照 100 / 50 | 变化 |
|---|---|---|---|
| 左脚摆动峰值（中位） | 2.11 mm | 1.82 mm | **−14%** |
| 右脚摆动峰值（中位） | 3.25 mm | 3.05 mm | **−6%** |
| 落地频率 / 脚 | 5.84 Hz | 6.20 Hz | +6% |
| 落地事件数 | 5976 | 6348 | +6% |
| `vx` 均值 | −0.034 m/s | −0.012 m/s | 噪声级 |
| `error_vel_xy` | 0.038 | 0.040 | 不变 |
| `mean_action_acc` | 0.0572 | 0.0592 | 不变 |
| upright 均值 | 0.9395 | 0.9409 | 不变 |
| 终止率 | 100% | 100% | 都摔 |
| `feet_clear_8mm` | **FAIL** | **FAIL** | 不变 |
| **墙钟耗时** | **45 s** | **43 s** | **≈ 0** |

### 4.4 结论（两条，都很实用）

1. **求解器精度不是抬脚的杠杆。** 迭代加 10 倍，脚峰反而略降（都在 2–3 mm 噪声带内）。
   脚高是被**策略与奖励**决定的，不是被接触解算精度决定的。
   ⇒ 「换 Isaac Lab 就能走起来」的期待，**在这一条上不成立**。

2. **但这个加固本身几乎免费，值得无条件加上。**
   100/50 比 10/20 只慢 0 s（45 s vs 43 s，差异在测量噪声内）—— 因为 MJWarp 是
   **"exits once every world converges"**，100 是上限不是实际次数，收敛早退。
   花 0 成本买「接触解算不足 → NaN」的保险，是纯赚。

   > 建议动作：把 `microduck_velocity_env_cfg.py` 里那三行从 `else:` 分支提到
   > `if/else` 之外，让 **flat 也用 `iterations=100 / ls_iterations=50`**。
   > 注意这是改 site-packages 里的上游文件，要同步写进 `tools/train_velocity.sh` 的
   > cfg sha256 记录，否则 runmeta 对不上。

---

## 5. Isaac Lab 版真正多出来的东西（逐条判定）

| 增量 | 内容 | 对我们值不值 |
|---|---|---|
| **rough 地形 NaN 防护** | "a termination guard against non-finite MJWarp states, which microduck_rl's rough velocity task hit under heavy contact" | ⚠️ 只影响 rough；我们走 flat，影响小 |
| **三角网格地形 + 自定义 solref** | Lab 建三角网格而非 box，用 `solref=(0.04,1.0)` 复现 MuJoCo 的软接触 | ⚠️ 只对 rough 有意义 |
| **rough 接触预算** | 200 contacts / 1024 constraint rows per env | ⚠️ 同上 |
| **BAM 原生进 Newton** | `DriveBam` 跑 Warp kernel，CUDA-graph safe，**per-env delay stream 与 supply sag** | 🟡 我们也有 BAM（`FrictionDRBamActuator` 子类）+ 齿隙读穿（`BacklashEncoderBamActuator`），功能对齐；差别在实现层 |
| **齿隙变体** | `*_backlash.usd`，14 个 ±1° play hinge | ❌ 不是增量：我们有 `robot_groundcontact_backlash.xml` |
| **头部 pose 命令** | `head_pose` / `body_pose` 命令项（body_pose 奖励关闭但观测保留） | 🟡 我们的 joy 链有头部，velocity 链没有；属于额外功能 |
| **求解器预算 100/50** | 见 §4 | ❌ **实测无效**（但免费，该加） |
| **物理真实性** | — | ❌ 同一个 MJWarp 求解器 |
| **观测/动作/频率契约** | — | ❌ 完全一致 |
| **Isaac Sim 渲染 / 相机** | 可选 `--extra isaacsim` | ✅ **这才是真差别**：视觉策略、数字孪生、Omniverse 同步 |

---

## 6. 该不该换：判断清单

**现在不换。** 理由：

1. **A 路（走路）还没起训。** 换平台要先装环境（uv + Py3.12 + Warp 1.17 + CUDA 13 + long path + 拉 Nucleus 上的 USD），
   这会把「起训」再推一天，而收益是 §5 里那几条 ⚠️/🟡。
2. **物理不变。** 同一个求解器，训出来的策略不会有本质差别。
3. **契约不变。** 61/76/14/50Hz 一致，意味着**随时可以换**——不存在「现在不换就锁死」的沉没成本。
   真要换，拿 mjlab 训出来的 `.pt` 直接在 Isaac Lab 里 `play` 就行，PR 明确说 "existing checkpoints load"。

**什么时候值得换**（任一成立）：

- 要做**视觉/相机策略** → 必须 Isaac Sim（那时才需要 16 GB 显存，本机不够，得上云）。
- 要做**数字孪生/Omniverse 同步/真机可视化**。
- 要走 **rough 地形**（Isaac Lab 的地形与 NaN 防护比我们完整）。
- mjlab 链在某个 bug 上卡死且上游不修。

**如果决定换，最小路径**：

```powershell
# 1) 开 Windows long path（管理员 PowerShell）
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force

# 2) uv + 克隆 + Newton-only（不装 Isaac Sim）
uv run isaaclab train --rl_library rsl_rl `
  --task IsaacContrib-Velocity-Flat-MicroDuck physics=newton_mjwarp --num_envs 4096
```

预期显存：4096 envs 在 8 GB 上**很可能不够**（Isaac Lab 官方 MicroDuck 默认 `num_envs=4096`、
`env_spacing=2.0`、Newton 侧 `max_triangle_pairs=2500000`）。降到 1024–2048 试，先跑通再谈预算。

---

## 7. 参考（全部一手来源）

- `isaac-sim/IsaacLab` @ `main`，PR **#8270**（2026-10-15 合入）
- `docs/source/isaaclab/installation.rst`（系统要求 / Newton-only / 可选 Isaac Sim 32 GB RAM + 16 GB VRAM）
- `source/isaaclab_tasks/isaaclab_tasks/contrib/microduck/flat_env_cfg.py:436-478`
- `source/isaaclab_assets/isaaclab_assets/robots/microduck.py`（`BamMotorCfg(model="m6")`，Rhoban BAM `62bd8ce`）
- 本地对照：`mjlab_microduck/tasks/microduck_velocity_env_cfg.py:745-769`、`actuator/friction_dr_bam.py`
- 实测数据：`microduck-software/out/solver_ab_base.json`、`out/solver_ab_100_50.json`
