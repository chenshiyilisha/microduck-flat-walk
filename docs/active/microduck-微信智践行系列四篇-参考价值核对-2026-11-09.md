# 微信「智践行」Microduck 系列四篇 — 参考价值核对

_2026-11-09 · 来源：公众号「智践行」(gh_157cc95c7163) 手动提供的 5 条 mp.weixin.qq.com 链接_
_核对方式：本地 curl 抓 HTML → 解析 `#js_content` 全文 → 逐条与我们上游源码 / 已装 venv 实测比对_

## 0. 一句话结论

**四篇里有三篇值得看，且其中一篇（⑥真机软件栈 + 仿真鸭）是能直接补上我们"没有整机就无法验证 robotd 全链路"这个空白的方案。**
第五篇（LLM 书评）与本项目无关。四篇都不是"新知识"，而是**独立第三方把我们踩过的坑按部署链路分层复述了一遍** —— 它的价值不在于教会我们什么，而在于证明这些坑是这套栈的结构性问题，不是我们手抖。

## 1. 篇目清单

| # | 标题 | 发布 | 判定 |
|---|---|---|---|
| ① | 具身智能入门⑤：从跑通到真稳，Sim-to-Real 调优 | 2026-10-08 | 有价值（域随机化清单 + 奖励陷阱） |
| ② | 具身智能入门⑥：不买机器人，把真机软件栈在自己机器上跑一遍 | 2026-10-13 | **最高价值（仿真鸭 duck-sim）** |
| ③ | 具身智能入门⑦（上）：先看懂任务，再定义新动作 | 2026-10-24 | 有价值（六杠杆 / 61 维观测拆解） |
| ④ | 具身智能入门⑦（中）：俯身行礼复盘，五个坑再撞一堵墙 | 2026-10-30 | **高价值（五个部署坑 + 单轴弃考）** |
| ⑤ | 大语言模型应用设计：LLM 一体化全局方法论 | 2026-07-01 | 无关（书评，与机器人栈无交集） |

## 2. 逐篇判决

### ① Sim-to-Real 调优（2026-10-08）

作者用「一次只动一个旋钮」的做法跑了四组对照：基线 4000 轮、`air_time` 3.0→3.6、`upright` 2.0→6.0、关域随机化。

**可直接用的三个结论：**

1. **`push_robot` 只关开关 ≠ 关掉。** 基类 `make_velocity_env_cfg()` 自带一份更狠的 `push_robot`（1–3 s、±0.5 m/s、带角速度），Microduck 只是用温和参数（3–6 s、±0.3 m/s）**覆盖**它。把 `ENABLE_VELOCITY_PUSHES` 设 False 只是不再覆盖，等于换上了更狠的那份。作者实测：少了 `cfg.events.pop("push_robot", None)` 这一行，奖励 46.45；补上后 142.67 —— **实验方向完全反了**。
   → 与我们记忆里 `dict(DEFAULTS, **cfg)` 会把没写的键补回默认值，是**同一类语义差**。我们已装 venv 核实：`microduck_velocity_env_cfg.py:391-399` 确是 `if ENABLE_VELOCITY_PUSHES: cfg.events["push_robot"] = EventTermCfg(...)` 覆盖式写法。

2. **奖励不是越高越好，是"让你要的行为比躺平更划算"。** 仓库作者在配置注释里记过一次：收紧 `head_pose_tracking` 容差后，策略第 300 轮彻底不走，`air_time` 1.01→0.02，抬脚 15 mm→2 mm。
   → 与我们"奖励项恒为 0.83 / 0.79 像在走路"的静默 bug 同类：**总奖励上涨 ≠ 行为变好**（作者 `upright` 6.0 那组总奖励 91→188，因为权重从 2 放大的，腾空时间反而腰斩）。

3. **`num_envs` 不决定最终水平，总步数才决定。** "训练不够就加轮数，而不是加环境数。"

**对我们 P3 sweep 默认值的核对（重要）：**
- 作者：1024 envs × 4000 iters × 24 steps ≈ **9.8e7 步**（他自称"近一亿步"）
- 我们 `p3_sweep.sh`：4096 × 2000 × 24 = **1.97e8 步**，是作者的 2 倍
- **⇒ `WALK_ITERS=2000` 不需要提高到 4000**。总数已超；且 4096 envs 的经验批次更大、更新更稳，正合作者"envs 影响稳定性而非上限"的说法。这条是本次核对里唯一直接落到我们环境包参数上的结论，结论是**不用改**。

**已核实文章数字与我们实际装的版本一致**（`.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_velocity_env_cfg.py`）：

| 项 | 文章 | 我们 venv 实测 |
|---|---|---|
| `upright` weight | 2.0 | `:300` = 2.0，`:301` std=√0.05 |
| `air_time` weight | 3.0 | `:333` = 3.0 |
| `air_time` 窗口 | 0.125–0.300 s | `:335-336` threshold_min/max 一致 |
| 域随机化开关数 | 默认 8 个 | `:31-41` 8 个 True（另 4 个 False，含 KP/KD `# Was True`） |
| `push_robot` 覆盖 | 覆盖而非新增 | `:395` `cfg.events["push_robot"] = ...` |

⇒ 文章写的是**同一上游版本系**，数值可当二手证据用，不是传闻。

### ② 真机软件栈 + 仿真鸭（2026-10-13）— 最高价值

**它做的事：** `scripts/duck-sim` 一条命令拉起**真机软件栈**（robotd / configd / tofd / updaterd / robotctl，Rust 二进制一行不改），只把最底层的**舵机总线**换成 TCP，接上一个 MuJoCo 仿真身体进程。守护进程分不清自己接的是真舵机还是仿真。

分层与"缝"的位置：
```
遥控器 robotctl / duck-sim ctl
      ↓（unix socket）
守护进程 robotd（50 Hz 回路、策略、安全、跌倒、odom）  ← 真机代码，一行不改
      ↓（TCP 127.0.0.1:7801，行分隔 JSON）              ← 缝在这里
仿真身体 body_server（Python + MuJoCo，CPU 即可）
```

**为什么这对我们是关键：** 我们的现状是**只有台架 PC + URT-2 + 单舵机，没有整机、没有上板**，所以 50 Hz 回路、安全检查、跌倒检测、策略槽位热替换、odom、health 报告、updater 门禁 —— 这些**一直无法验证**。仿真鸭正好只替换"身体"这一层，把这些全留住。

**最关键的一条实测：本地 Python 侧已经就绪。**

```
.venv-mjlab/Lib/site-packages/mjlab_microduck/sim/body_server.py   ← 已装
.venv-mjlab/Lib/site-packages/mjlab_microduck/sim/camera.py
.venv-mjlab/Lib/site-packages/mjlab_microduck/sim/tof.py
```
- `body_server.py:59  PROTOCOL = 1`
- CLI：`--port` / `--scene` / `--ducks`（`python -m mjlab_microduck.sim.body_server --port 7801`）
- 依赖只有 `mujoco` / `numpy` / `socketserver` / `threading` —— **无 torch、无 CUDA**
- 另有完整副本：`.upstream/microduck_rl-develop/src/mjlab_microduck/sim/body_server.py`、`.upstream/hd1910m/microduck_rl/src/...`

**缺的只有 Rust 侧，而且缺口是代次造成的（这是本次核对最重要的边界）：**

| 仓库 | `sim.rs` / `RemoteIo` | `robotd --sim` | 伺服后端 |
|---|---|---|---|
| `.upstream/ft1910`（= 官方 `pollen-robotics/microduck` 线） | **有** `duck-control/src/sim.rs:119` | **有** `robotd/src/main.rs:246,1235` | Dynamixel 1M (`model.rs:103`) / SCS 1M (`scs/mod.rs:53`) |
| `.upstream/DuckBuddy-main`（**我们的 B 代部署主线**） | **零命中** | **零命中** | HLS 500k |

⇒ 文章那一套落在**官方线**上；我们这条 `DuckBuddy-main` 没有这个能力。**不能照文章直接跑。**

**但移植成本很低，且是纯新增：**
1. `ft1910/duck-control/src/sim.rs` 与 Python 侧 `PROTOCOL` 都是 **1**，协议对得上，可原样复制；
2. 两代 `RobotIo` trait 前三个方法同构（`io.rs:113-127` 两处 `read` / `write` / `set_gain` 完全一致），ft1910 多出的 `measures_velocity` 等有默认实现；
3. 协议是**行分隔 JSON**，作者自己写明"一个 tick 15 关节进 15 出约 1 KB，50 KB/s，`nc` 能读、二十行 Python 能写另一半"；断连按错误返回、下次调用重连，控制回路本身就是重试定时器（`sim.rs` 头注释）；
4. 第三方已证明协议可被独立实现：`awesome-microduck/readme.md:124` 收录 `green-creeper/microduck_genesis`，是 Genesis 物理做的 drop-in TCP `duck-body` server，同样用 `--sim` 接真守护进程。

**⇒ 落地形态：`duck-control/src/sim.rs`（新增）+ `robotd` 加 `--sim <addr>` 分支 + 直接跑我们 venv 里的 `body_server`。零硬件、零买板、零 GPU。**

**必须记住它验不了什么**（文章自己划的边界，与我们 R3 结论同向）：舵机总线时序、蓝牙、摄像头成像、NPU、硬件编码器**根本没进来**。所以仿真鸭**不能消 R3**（500k 位宽/16 设备总线预算），它消的是"软件栈是否自洽"。

### ③ 六杠杆 / 61 维观测（2026-10-24）

**任务 = 六根杠杆**，各占 `cfg` 一个字典：`commands` / `rewards` / `observations` / `terminations` / `curriculum` / `events`。舞台（本体、地形、道具）跨任务不变。

**接口铁律与我们部署链一致：**
- 观测 61 = 指令 13（`twist` 3 + `body_pose` 6 + `head_pose` 4）+ 本体感知 48
- 动作 14
- `robotctl` 守卫：不是 61 进 14 出直接拒载
→ 与我们 `obs61 / act14 / 50 Hz` 完全对齐。

**非对称 actor-critic 的分法（对我们做新动作时选观测有用）：**
- 两拨都给：`projected_gravity`（有开关可换 `raw_accelerometer`，本项目默认不开）
- **只进 critic**：`base_lin_vel` —— 机器人没有速度计，选手学了也白学
- **两拨都删**：`height_scan` —— 身上没这个传感器，绝不伪造
- `base_ang_vel` / `projected_gravity` 带 **0–20 ms 延迟建模**

**一个会直接坑到我们的细节：课程档位 `step` 的单位是累计步数，不是轮数。**
`common_step_counter = num_steps_per_env(24) × iteration`。想第 1000 轮换档要填 `1000 × 24 = 24000`，直接写 1000 是错的。→ 我们若在 P3 里写课程（`pose_command_range_curriculum` 这类），必须按这个口径。

**其他可对照的常量：** `air_time` 窗口 [0.125, 0.300] s；`foot_slip` -0.1；`action_rate_l2` 课程 -0.1→-1.0（500→1500 轮）；`COM` 随机 ±3 mm → 封顶 ±15 mm；`rel_standing_envs` 2% → 25%；`push_robot` interval 3–6 s。

**BallKick 对照标本（做"新动作"的第二个范本）：** 删掉全部速度追踪奖励，换 `ball_forward_velocity`（线性封顶 1 m/s）+ `ball_speed_overshoot_penalty` -4.0；**actor 里零球观测，球只进 critic**（真机没球传感器，靠 ±1.5 cm 球位随机化兜鲁棒性）；`KICK_FOOT` 一个 flag 派生两个任务。

### ④ 俯身行礼复盘 — 五个坑（2026-10-30）

这篇的五个坑**全部落在部署链路层，没有一个是训练的错**。逐条对我们：

| 坑 | 现象 | 根因（文章 `file:line`） | 对我们的对应 |
|---|---|---|---|
| 1 注册表漏同步 | 产物落在 `logs/rsl_rl/velocity/` 而非 `pose_track_bow/` | `tasks/__init__.py` 的 `rl_cfg` 没同步，`experiment_name` 仍指旧任务 | 与 `export_iteration=2999` 是 heading_meta **陈旧字段**同型：元数据没跟着换，产物"看起来对" |
| 2 粘性槽位 | 脚本退出后鸭子保持躬姿不回直 | `intents.rs`：`head`/`pose` 只 `set_head/set_pose` 存值，**无过期**；只有 `twist` 带 deadman | **我们已实测同一条**：`deadman_ms=500` 只归零 twist |
| 3 stand 抢班 | 换了策略行为一点没变 | `control.rs` `will_stand() = (twist==0) && stand 槽有策略` → 每帧走 stand 分支；日志 `policy` 字段全程 `stand` | "换了东西没生效，第一怀疑是它到底上没上场"，与"读数 vs 算术矛盾 ⇒ 错的是读数"同法 |
| 4 二连摔 | 装载中直接摔 | `main.rs`：换正在驱动的槽 → `change_disturbs → Bringup::Homing`，**无平衡**位置控制挪回 home；`robot enable --off` 的 `hold = DEFAULT_POSITION`（帮助写 "holds its pose"，实为 home 蹲姿，连 ramp 都没有） | 文章结论："平衡不是独立模块，它就是策略推理本身"；**唯一安全门 = 先 `sit_toggle` 坐下再换网** |
| 5 符号写反 | 命令俯身，实际后仰 | `robot_walk.xml`：`neck` quat (0,0,0.707,−0.707) 绕对角轴 180°，z 轴指向 (0,−1,0)；`neck_pitch` 连杆 quat (0,1,0,0) 绕 x 180°，z 轴指向 (0,0,−1) ⇒ **两关节轴左右相反**：`neck_pitch` 取负是低头，`head_pitch` 取**正**才是低头 | **与我们"头 13/14 `head_yaw`/`head_roll` 相反"完全同类**；`joint_signs`/`joint_offsets` 是唯一杠杆 |

坑 5 给出的两个独立验证手段，正是我们准则的实例：**① 拿官方策略发同款命令看关节响应；② 读模型文件里 joint 的 `axis`。两条独立证据对上了符号约定才作数。**

文章对奖励的判词值得抄进准则：**"奖励函数是符号假设的放大器，不是纠错器。"** 假设错了，奖励照常满分，错误原样训进权重。另：**对称区间采样对符号错误有容错，单侧区间零容错** —— 我们做新动作时若只采单侧区间，符号必须先验。

**那堵墙（对我们最有用的一段）：**
- 命令 60°，实测 8.4° → 8000 轮仍 2° 以内 → top 模式每局 15% 强制全幅，pitch 依旧不动
- 训练指标 0.65 → 0.897 **过了 0.85 健康线**，但拆开看：`(1+1+0+1+0+1)/6 ≈ 0.667` —— **四轴满分、pitch 和 z 两轴弃考**，均值把弃考藏进了分母

→ 这正是我们 `model_7999` 的处境：**vx +14.11%、`error_vel_xy` 转 PASS，但 `not_sideways` 4 次 3 FAIL**。同一课：**验收看每个自由度的单项分，不看合成均值；多轴平均会让单轴弃考隐身。** 我们 `p3_select.py` 的双轴排序（primary 降序 / risk 升序）方向对，但需要补一条**分轴硬闸门**：任一轴低于阈值即拒，不参与均值。

- 作者的下一步是**不做第六个补丁，先花十分钟做一次不训练的物理学实验，验 60° 这个角度本身物理上够不够得着**。→ 与我们"换 plant = 换任务必须重训""先算预算再动手"同向：**先验可达性，再谈训练。**

### ⑤ LLM 书评（2026-07-01）

《Designing LLM Applications: A Holistic Approach》章节摘要，全文与机器人栈零交集。**本项目的结论：不参考。**

## 3. 与本项目已有判决的交叉验证

| 我们已知 | 文章独立确认 | 意义 |
|---|---|---|
| `deadman_ms=500` 只归零 twist | 坑 2：只有 twist 带过期，head/pose 粘性 | 结构性，不是实现疏漏 |
| 头 13/14 `head_yaw`/`head_roll` 相反 | 坑 5：neck_pitch / head_pitch 轴相反 | 同类符号雷，验证手段可复用 |
| `dict(DEFAULTS, **cfg)` 会补回默认键 | ①：`push_robot` 只关开关等于换上更狠的基类版 | 同类覆盖语义差 |
| model_7999 vx 过线但 `not_sideways` 退化 | ④：0.897 均值掩盖 pitch 弃考 | **必须分轴验收** |
| 奖励项恒 0.83 像健康步态 | ①：总奖励涨 91→188 但腾空腰斩 | 总奖励不是验收指标 |
| obs61 / act14 / 50 Hz | ③：61 = 13 + 48，14 动作，robotctl 守卫 | 接口口径一致 |
| R3 未消：仿真验不了总线 | ②：舵机总线/蓝牙/相机/NPU/编码器"根本没有" | 仿真鸭不能替代台架 |

## 4. 可执行建议

**P0 — 仿真鸭移植（零硬件、零成本，补上 robotd 全链路验证空白）**
1. `ft1910/duck-control/src/sim.rs` → `DuckBuddy-main/duck-control/src/sim.rs`（纯新增，`PROTOCOL=1` 两边一致）
2. `DuckBuddy-main/robotd` 加 `--sim <addr>` 参数分支（照 `ft1910/robotd/src/main.rs:246,1235`）
3. 起身体：`.venv-mjlab/Scripts/python.exe -m mjlab_microduck.sim.body_server --port 7801`
4. 先只验"栈能不能起来 + 50 Hz 回路 + health"，**不碰策略**
5. 负对照：故意不启 `body_server`，robotd 必须报错而不是静默跑空转

**P1 — 给 `p3_select.py` 加分轴硬闸门**
现有双轴排序保留，但新增：任一分轴（如 `not_sideways`、`tracks_half_command`）低于阈值直接淘汰，不进中位数。理由见 ④ 的 0.897。

**P2 — 若 P3 要写课程**
`step` 一律写 `轮数 × 24`，并加一条断言：`step % 24 == 0`。

**P3 — 常识补强（不改代码）**
- 做新动作时优先**对称区间**采样，避开单侧符号零容错
- 新任务上线前先做"可达性/物理可行性"验算，再决定训练

## 5. 边界（本次没做的）

- **没有移植 `sim.rs`**，没有改 `DuckBuddy-main`，没有任何 Rust 代码变更。
- **没有跑起仿真鸭**，只核实了 Python 侧文件存在、协议版本一致、trait 同构。
- **没有在 Windows 上实测 `body_server`**：它用 `mujoco.viewer`，Windows 需 `MUJOCO_GL=glfw`（与我们训练环境同一条约束）；文章只在 Mac/Linux 验过。
- 未验证 `DuckBuddy-main` 的 `--sim` 移植后 `SlowSensors` / `tof` 缺失路径是否如 ft1910 那样容忍（`sim.rs` 声称控制回路把 read 失败当作跳过一个 tick）。
- 文章数字只核对了 `microduck_velocity_env_cfg.py` 一处；`mdp.py`、`tasks/__init__.py` 未逐条核。
- 未处理我们 500k / HLS 与 ft1910 1M / Dynamixel·SCS 的 backend 差异 —— **仿真鸭在总线之下，所以这个差异不影响它**，但真机仍是 500k。

## 6. 证据

| 结论 | 证据 |
|---|---|
| venv 装的 cfg 与文章数值一致 | `.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_velocity_env_cfg.py:28-42, 292-301, 330-336, 391-399` |
| Python 侧 body_server 已就绪 | `.venv-mjlab/Lib/site-packages/mjlab_microduck/sim/body_server.py:59` (`PROTOCOL=1`)、`:506-509` (CLI) |
| ft1910 有 sim，DuckBuddy 无 | `.upstream/ft1910/duck-control/src/sim.rs:119`、`.upstream/ft1910/robotd/src/main.rs:246,1235`；`.upstream/DuckBuddy-main/` grep `--sim`/`7801`/`RemoteIo` 零命中 |
| trait 同构 | `.upstream/DuckBuddy-main/duck-control/src/io.rs:113-127` vs `.upstream/ft1910/duck-control/src/io.rs:115-129` |
| 协议为行分隔 JSON | `.upstream/ft1910/duck-control/src/sim.rs:1-40`（头注释）、`:229-246`（`to_string`+`write_all`+`read_line`） |
| 第三方独立实现存在 | `.upstream/awesome-microduck/readme.md:124` (`microduck_genesis`) |
| 官方栈波特率 1M | `.upstream/ft1910/duck-control/src/model.rs:103`、`.upstream/ft1910/duck-control/src/scs/mod.rs:53`、`scs/tests.rs:938` |
| 全文原文留档 | `out/_wx_fetch/a1..a5.txt`（`out/*` 已 gitignore，不入库） |
