# tools/flat_walk — 平地速度跟踪的可复用小工具

这里的脚本是从一次真实训练里留下来的**带注释的现场记录**，不是通用框架。
每个文件头部都写了「为什么需要它」和「源码事实在哪一行」，改路径即可复用。

| 文件 | 作用 | 为什么值得留 |
|---|---|---|
| `eval_velocity_in_sim.py` | 11 项闸门评估器（含 `command_frozen_ok` / `metric_window_ok` 两条协议自检）+ **逐 env 分布**（`per_env`）（`docs/05-flat-walk.md` §2 的全部数字都由它产出） | 「在走」需要可证伪的判据：前进位移、不侧滑、脚峰、落地交替、不摔。有些量之间会互相矛盾（同一 ckpt 三次重复里 `abs(dy)` 的 CV 是 31%），所以窗口均值必须配一份逐 env 分布，否则分不清「策略变了」和「抽样变了」 |
| `train_velocity.sh` | 训练包装：写 `runmeta`（含 **cfg/mdp 字节哈希** + **`rewards_effective`**）+ 求解器 CLI 覆盖 + **`EXTRA_ARGS` 实验透传** | `cfg_byte_identical_to_upstream` 是「没偷偷改奖励」的机器可验证证据；而 CLI 覆盖又不受哈希保护，所以必须用同一条 tyro 路径**回读解析**实际生效的 `std/std_sq/std_over_cmd_max`——声明式记录不算证据 |
| `resume_velocity.sh` | 续训包装：**目标绝对轮数**、GPU 双开保护、`DRY_RUN=1` | `--agent.max-iterations` 是**增量**不是总量，手滑一次多跑 10 小时 |
| `watch_milestones.py` | 里程碑守候：等 `model_N.pt` 落盘 → 同参评测 → 判读 → 可自动停训 | 判停阈值写死在代码里（`verdict()`），比「等我想起来看一眼」可靠 |
| `record_walk.py` | 无头录像：在训练环境内以固定协议录 mp4（`--distance/--elevation/--azimuth/--yaw-deg` 机位与朝向可钉） | `mjlab play --video` 永远以交互 viewer 循环收尾（`play.py:288-291`），录完不返回；这里复用同一套组件但把循环做成有限步 |
| `patch_issue46.py` | issue #46 三处改法的可回滚补丁（`--check/--apply/--revert`，幂等、带备份） | 当前**未应用**；前进门控复用上游 `_forward_progress_gate`，不是自己推导 |
| `check_onnx_parity.py` | 导出图与权重的 parity 闸门：**用 numpy 从 `actor_state_dict` 独立重建前向**，与 onnxruntime 输出逐元素比，并强制负对照（拆掉归一化）必须偏离 | 上游 `mjlab_microduck.export` 把「normalizer 已烘进图」写在注释里，但源码里 `parity`/`onnxruntime`/`allclose` 出现 **0 次**。而拿 `policy.act_inference()` 当参考也测不出来——normalizer 在同一个模块上，导出路径和参考路径的 bug 会互相抵消。**参考必须独立，否则它在测自己** |
| `rehearse_deploy.py` | **部署彩排**：把 ONNX 过一遍上游自己的栈（BAM M6 + XL330 电压模型 + 50 Hz 环），六条件 sweep → JSON | 与 `check_onnx_parity.py` 分工明确：parity 查「**图 == 数学**」，彩排查「**栈会不会活着**」。它不重写栈，而是加载上游 `infer_policy.py` 复用其实现、只换掉 viewer+键盘循环（`termios`/`tty` 用惰性 stub 绕过 Windows 缺失）——重写就是第二个意见，两个实现一致证明不了发出去的那份对。坑：摔倒后继续跑会把「躺地上」算成速度（实测 0.4627），截断后又因存活偏差报得比没摔的还高（0.5389）⇒ 摔倒的跑 vx 一律 `n/a` |

## 使用注意

- 原环境是 **Windows + `.venv-mjlab`**（`train_velocity.sh` 里写的是 `.venv-mjlab/Scripts/train.exe`）。
  本仓库其余部分用 `uv run`，两者等价，改成 `uv run train ...` 即可。
- `eval_velocity_in_sim.py` 依赖本仓库 `mjlab_microduck` 的任务注册；`--task` 默认
  `Mjlab-Velocity-Flat-MicroDuck`。
- `resume_velocity.sh` 里的三条坑（增量迭代数、`MICRODUCK_WARM_START`、ckpt 排序）都有源码行号，
  注释比代码长——那些注释就是它的主要价值。
- `watch_milestones.py` 的评测不会打断训练（独立进程）；`--stop-pid` 只在**所有里程碑都判 flat**
  时才会发 `taskkill`，评测崩溃（`eval-failed`）不会误停。
- `watch_milestones.py` 要在**训练工作区**里跑（需要 `logs/rsl_rl/microduck_velocity/` 与 `out/`）；
  只 clone 了本仓库时它会直接报「训练产物不在本仓库」并退出，此时用 `eval_velocity_in_sim.py`
  对已入库的 checkpoint 做单次判读即可。
- `record_walk.py` 默认 `--yaw-deg 0`：`reset_base` 的 `yaw` 是 `(-3.14, 3.14)` 全随机
  （`mjlab/tasks/velocity/velocity_env_cfg.py:209`），世界系固定机位下同一 `--azimuth` 每次拍到的朝向都不同，
  「侧视」不可复现。要训练分布的样子就加 `--random-yaw`。Windows 上 `MUJOCO_GL=glfw`（脚本里默认设好），
  `egl` 不可用；离屏渲染走 `mujoco.Renderer`（`mjlab/viewer/offscreen_renderer.py:57`）。
- `train_velocity.sh` 的 `EXTRA_ARGS` 是**给单变量实验用的**，例：
  `EXTRA_ARGS="--env.rewards.track-linear-velocity.params.std 0.2" bash tools/flat_walk/train_velocity.sh 4096 2000 myrun`。
  它按空格切分后原样透传给 `train`，所以**不要放带空格的值**。走这条路而不是改
  `site-packages` 里的 cfg，是为了让 `velocity_cfg_pristine`（blocking）保持绿——
  改文件会逼你 `--no-check`，等于拿掉保护换实验能力。
- 一个只会在负对照里现形的坑：`tyro` 遇未知参数抛 **`SystemExit(2)`**，它继承 `BaseException`，
  所以 `except Exception` 抓不到 ⇒ 进程在写 runmeta **之前**就死，发车确实被拒但**一行证据都没留**。
  这里用 `except BaseException` 才记下 `FATAL` + `SystemExit: 2` 并 exit 1。
  凡是 try/except 包住 tyro / argparse / 任何内部 `sys.exit()` 的地方，都要先问这一句。
- `check_onnx_parity.py` 的两个常量是从源码读的，不是猜的：`EmpiricalNormalization.forward`
  是 `(x − _mean) / (_std + eps)`（除**存储的 std buffer**，不是 `sqrt(_var)`），且
  `eps` 默认 **1e-2**（`rsl_rl/modules/normalization.py`）。老导出器常见的 1e-5 会让每个输出都偏移，
  看起来像真不匹配；`--norm-eps` 可覆盖。
- 导出图带**静态 batch 1**（`get_dummy_inputs` 就是一行，正是控制器每次发的形状）。
  检查脚本按静态 batch 分块喂，不假设动态轴——否则 ort 报的是 shape 错误，看起来像策略有问题。
- `rehearse_deploy.py` 依赖三件**不在本仓库**的东西：上游 `microduck_rl` 的
  `scripts/infer_policy.py`（`--infer-policy` 指过去）、`mjlab_microduck` 任务包（scene XML
  从它解析，保证用的是训练那个资产而不是长得像的）、`mujoco`。所以它支持的说法是
  「给定同一任务包与环境，输出里的每个数能按 `settings` 复算」，不是「clone 即跑」（同 §7.0）。
  它的数字**不能**与 `eval_velocity_in_sim.py` 并排：单机/无延迟/CPU 求解器/固定摩擦
  vs 32 台/3–6 lag/warp/摩擦 DR，两台仪器（`docs/05-flat-walk.md` §14.5）。
- `rehearse_deploy.py` 的判据是「先定死再跑」的，七条里 **P5（延迟）与 P7（低速）只记录、
  不作结论**：延迟路径与训练语义不一致（实测 lag 3/4/6 → 摔在 1.88/1.36/0.84 s，而训练侧
  同 lag 几乎不摔），低速单机固定初态只等于一个样本（扫五个 yaw 全站，与评估侧 ratio 0.53
  相反）。**不是所有维度都该有结论**——硬给结论比留缺口更糟。
