# tools/flat_walk — 平地速度跟踪的可复用小工具

这里的脚本是从一次真实训练里留下来的**带注释的现场记录**，不是通用框架。
每个文件头部都写了「为什么需要它」和「源码事实在哪一行」，改路径即可复用。

| 文件 | 作用 | 为什么值得留 |
|---|---|---|
| `eval_velocity_in_sim.py` | 11 项闸门评估器（含 `command_frozen_ok` 协议自检）（`docs/05-flat-walk.md` §2 的全部数字都由它产出） | 「在走」需要可证伪的判据：前进位移、不侧滑、脚峰、落地交替、不摔 |
| `train_velocity.sh` | 训练包装：写 `runmeta`（含 **cfg/mdp 字节哈希**）+ 求解器 CLI 覆盖 | `cfg_byte_identical_to_upstream` 是「没偷偷改奖励」的机器可验证证据 |
| `resume_velocity.sh` | 续训包装：**目标绝对轮数**、GPU 双开保护、`DRY_RUN=1` | `--agent.max-iterations` 是**增量**不是总量，手滑一次多跑 10 小时 |
| `watch_milestones.py` | 里程碑守候：等 `model_N.pt` 落盘 → 同参评测 → 判读 → 可自动停训 | 判停阈值写死在代码里（`verdict()`），比「等我想起来看一眼」可靠 |
| `record_walk.py` | 无头录像：在训练环境内以固定协议录 mp4（`--distance/--elevation/--azimuth/--yaw-deg` 机位与朝向可钉） | `mjlab play --video` 永远以交互 viewer 循环收尾（`play.py:288-291`），录完不返回；这里复用同一套组件但把循环做成有限步 |
| `patch_issue46.py` | issue #46 三处改法的可回滚补丁（`--check/--apply/--revert`，幂等、带备份） | 当前**未应用**；前进门控复用上游 `_forward_progress_gate`，不是自己推导 |

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
