# MicroDuck HD-1910 工具整合评估

日期 2026-11-02。对象：把 `microduck-software/tools/` 里零散的 HD-1910 主线工具整合成一个统一软件工具（先纯 CLI）的**可行性评估**，含后续接 UI 的扩展性（§7 开源参照、§8 UI 扩展性）。

**入口**：[根目录 README](../../README.md) · 软件主方案 [microduck-HD1910软件方案.md](microduck-HD1910软件方案.md) · 工具说明 [tools/hd1910/README.md](../../microduck-software/tools/hd1910/README.md)。

> 本文档**只评估，不施工**。结论与分阶段计划在这里；执行到哪一步由用户定。

> **已定的执行计划见** [microduck-HD1910工具整合计划.md](microduck-HD1910工具整合计划.md)：新项目、分步、每步有产物+门禁。

---

## 0. 一页结论

**能整合，但只值得做"主线壳"，不值得做"全量合并"。**

- 主线工具量可控：`tools/hd1910/` 约 25 个文件 + 主线依赖的 `tools/` 约 15 个，去掉 joy 侧线和旧栈，真正要收口的是 **~30 个入口**，不是 70+。
- 建议形态：**纯 CLI（`mduck`）+ 一个共享库**，把现有脚本当后端包起来，**不重写业务逻辑**。真正的障碍是语义接缝，不是代码量。
- **两个最大风险，都不是工程量**：
  1. **开工时机**（§4.1）。阶段 0 要动的四个文件全在训练进程的 import 闭包里，`apply_to_live` 改的就是训练正在读的那个 `microduck_constants.py`。在有训练跑着的时候动手，等于把正在跑的实验静默作废，且不会报错。
  2. **"植物身份"有 4 个真相源 + 1 个未隔离的作用域**（§2.1、§2.6）。这个不先钉死，整合出来的工具会安静地给出错误数字——正是本项目踩过的坑（`plant_id.py` 的注释记录了换植物时 cfg/mdp 哈希全绿、vx 从 0.316 掉到 0.109 的事故）。
- 不建议**现在**做 UI：主线使用者是训练/评估/CI 场景，CLI 足够。但 UI 是后期再加的一层，**第一版就要为它埋好接缝**（见 §8）：CLI 必须做薄、作业生命周期与事件契约必须现在就定，否则 UI 期要返工。
- **这条路已被上游验证**：本仓库的上游框架 `mjlab` 自己就是"薄 CLI + 共享库 + 可插拔后端"（`scripts/` 薄入口 + `src/mjlab/` 库 + `[project.scripts]` + `tyro`），它的 `play` 就是"同一份 `run_play(task, cfg)`、viewer 是可换后端"（见 §7）。我们不是发明架构，是把上游已验证的形态落到本项目。

**一句话：值得做，先做 7 个接缝的收口，不做大爆炸；同时把 CLI/UI 分层和作业契约在阶段 0 一次埋好，为后续 UI 留门（§8）。**

---

## 1. 范围（用户已定）

| | 内容 |
|---|---|
| **in** | `tools/hd1910/` 全部；主线依赖的 `tools/`：`eval_velocity_in_sim`、`eval_tracking`、`plant_id`、`check_velocity_ready`、`export_onnx`、`check_onnx_parity`、`make_manifest`、`record_walk`、`train_velocity_variant`、`train_heading_variant`、`watch_milestones`、`make_train_dashboard`、`convert_ckpt_stdtype`、`rehearse_deploy`、`bam_actuators` |
| **out（保留遗留）** | `repo/` 的 `train_ppo/train_official/train_robust`；依赖它们的 `robustness`、`envelope`、`ab_compare`、`eval_policy`、`deploy_sim`、`plant.py`、大多数 `probe_*`、`patch_joy_*`；joy 侧线全套（`eval_joy_in_sim`、`probe_joy_*`、`trace_joy_foot_phase` 等） |

---

## 2. 现状与七个整合接缝

### 2.1 植物身份有 4 个真相源 —— 最高优先级

同一个"现在跑的是哪台机器人"，目前由四处各说各的：

| 来源 | 说的是什么 | 位置 |
|---|---|---|
| `tools/hd1910/plant_spec.py` | m5 / m6 / `hd1910_kp5` / xl330 的数字 + 出处 | `tools/hd1910/plant_spec.py` |
| `tools/plant_id.py` | 回读 live `_BAM_ACTUATOR_KWARGS` 的指纹 | `tools/plant_id.py:66` |
| `tools/eval_joy_in_sim.swap_plant` | `default` vs `bam`（joy 自己的植物轴） | `tools/eval_joy_in_sim.py:126` |
| `tools/plant.py` | 旧 CPU 栈的 SPECS | legacy，不迁 |

`plant_id.py` 的模块 docstring 记录了这次事故的机理：换植物时 `microduck_velocity_env_cfg.py` 与 `mdp.py` 的 sha **仍然匹配**，`curriculum_counter_before_pin` 也照样是 30024——因为植物藏在**再深一层的 import**里（cfg 从 `microduck_constants` 导入 `MICRODUCK_WALK_ROBOT_CFG`，该模块用 `_BAM_ACTUATOR_KWARGS` 建执行器）。哈希说"cfg 文件没变"，完全不覆盖它的传递闭包。

**评估结论**：整合的第一块必须是**唯一的 `PlantContext`**，其它三处都改成它的调用方。否则整合工具无法回答"这个数是在哪个植物上测的"，而这是本项目的第一纪律。

### 2.2 主线 eval 依赖 joy 侧线模块 —— 耦合错位

`eval_velocity_in_sim.py` 和 `eval_tracking.py` 都从 **joy 侧线**导入植物切换：

```python
from eval_joy_in_sim import PLANT_CHOICES, swap_plant   # eval_velocity_in_sim.py:58
```

而 `swap_plant` 在 `plant == "bam"` 时替换 `articulation.actuators` + `spec_fn`，来源是 **joy 自己的 `MICRODUCK_STANDUP_ROBOT_CFG`**；`--plant` 默认是 `"default"`，此时它**什么也不换**（继承 live 状态）。

⚠️ **这里最容易下错结论。** 直觉会说"joy 侧线用的是另一套植物模型"，实测不是：

```
--- STANDUP ---
  FrictionDRBamActuatorCfg  kp_fw=5.0 | json=official_m6_stslaw.json | vin_range=(6.5,8.2)
--- WALK(velocity) ---
  FrictionDRBamActuatorCfg  kp_fw=5.0 | json=official_m6_stslaw.json | vin_range=(6.5,8.2)
```

**不是两套模型，是同一个模型、两个任务共享一个模块级常量。** `apply_to_live.py` 只改 `_BAM_ACTUATOR_KWARGS`（在 `microduck_constants.py` 里，第 61–82 行就干这一件事），而 `MICRODUCK_WALK_ROBOT_CFG` 与 `MICRODUCK_STANDUP_ROBOT_CFG` **都从这里取值**。

后果分两层，必须分开说：

| 层面 | 现状 |
|---|---|
| **此刻的行为** | **无害**：`--plant default` 与 `--plant bam` 给出相同植物（都是 P3 hd1910_kp5） |
| **契约** | **耦合**：换 velocity 的植物会顺带改 standup，反之亦然。将来若只改 WALK（做 velocity 专属植物实验），`--plant bam` 会静默把 standup 的植物塞进 velocity 评估，而**没有任何指纹会报警** |

**评估结论**：整合时必须把 `swap_plant` 从侧线**提取到主线共享库**，让 eval 不再 import 侧线代码。但接缝的正确定性是「**植物作用域没有按任务隔离**」，不是「合并两套模型」——后者会把人引向错误修法。真正的修法是给 `PlantContext` 加**任务级 scope**（`velocity` / `standup` 各自独立），并让 `apply_to_live` 必须显式指定作用到哪个任务（§2.6）。

> **⚠️ 2026-11-02 修正（实施后回看）**：上面这个「任务级 scope」修法**做不出来**。`microduck_constants.py:163` 只有一个 `_BAM_ACTUATOR_KWARGS`，`:176` 只有一个 `actuators` 对象，`:235`(WALK) 与 `:245`(standup) **引用同一个对象** ⇒ 想让两任务不同植物，必须编辑 `:245` 一行，那是改上游文件、不是纯新增。
> 执行计划 [0.0-#1](microduck-HD1910工具整合计划.md) 因此改为 **A 方案：承认单植物 + 每任务期望值对账**（`check` 打印「实际 / velocity 期望 / standup 期望」，不一致即红）。物理隔离要另走双 venv 或改上游一行，见计划 §0.3 后备表。
> 本节结论的**定性**（作用域未隔离、静默连带）仍然成立，变的是修法。

### 2.3 双 venv 并存

- `.venv-mjlab`（GPU，mjlab / MuJoCo Warp）—— 主线
- `.venv`（CPU，mjbatch）—— legacy

**评估结论**：既然 legacy 不迁，CLI 只需**锁定 `.venv-mjlab`**，并在启动时校验 `torch.cuda` 与 plant 闸门，把"用哪个 python"从人脑挪进工具。低风险高收益。

### 2.4 全局副作用 —— 必须"可逆 + 记录 + 不隐式触发"

- `apply_to_live.py` 直接写 `site-packages/mjlab_microduck/robot/microduck_constants.py`（含本机绝对路径）
- `patch_sts3215_q_target_smooth.py` 改 editable bam

`tools/hd1910/README.md` 明确警告"别在另一个训练跑着时热换植物"。

**评估结论**：这两类操作**不能**被整合成一个隐式动作。必须：显式子命令、写前备份、写后 `--check` 回读、记录到 runmeta。整合的价值之一正是把这个纪律机器化。

### 2.5 入口是 `.sh` + Python 混的，参数散在环境变量

训练入口是 shell（`smoke_train.sh` 用 `RUN`/`DEVICE` 环境变量、内部再拼 `--agent.*`），评估入口是 Python argparse。没有 `pyproject`、没有 console_scripts，工具间靠 34 处 `sys.path.insert` 硬拼。

**评估结论**：CLI 应该**包住**这些 shell，而不是重写它们——`mduck train smoke` 内部 `bash tools/hd1910/smoke_train.sh`，同时把 env 变量收敛成 CLI 参数。

### 2.6 一次换植物会改两个任务 —— 隐式副作用（§2.2 的推论）

`apply_to_live.py` 只操作模块级 `_BAM_ACTUATOR_KWARGS`，而 WALK 与 STANDUP 两个 `ROBOT_CFG` 都从它取值 ⇒ **一条 `apply_to_live --plant p3` 同时改掉 velocity 和 standup 的植物**，命令本身不会告诉用户这件事。

现有闸门也看不见：`apply_to_live --check` 报的是共享 kwargs 的 `detected`，两个任务都"通过"。`smoke_heading.sh` / `explore_heading.sh` 的 plant 闸门读的也是同一处 ⇒ 闸门绿了不等于"只改了我想改的那个任务"。

**评估结论**：这条与 §2.4（全局副作用）同级，但它比 §2.4 更隐蔽——§2.4 至少是"改了一个文件"，这里是"改了一个文件、影响了两个任务"。整合后必须：`PlantContext` 带任务 scope，`apply_to_live` 强制 `--task velocity|standup|both`，`--check` 分别回读两个任务的指纹，`both` 要求显式确认。

### 2.7 收口即再分发 —— 许可要跟着走

附录把 `servo_probe/` 列进 in 范围，但它不是纯自研代码：`hd1910_readonly.py` 与上游 `sxyseo/microduck-replica@master` **逐字节相同**（sha256 `9cf2d21a…b4f06ee`，commit `062f4d59`，作者 abel）。

该文件的许可状态是**"未明确声明"**，不是 Apache-2.0：
- 该仓根 `LICENSE` 是**按路径分配**的双许可证，Apache-2.0 一栏只覆盖 `scripts/` 与 `tools/`
- `rl-series/scripts/` **不在任何一栏**，`NOTICE.md` 的原创内容表也未列入
- 第二处独立证据：`rl-series/README.md` 全文零许可字样，目录下也没有自己的 `LICENSE`（对比父仓 `software/training/` 是有 `LICENSE` 的）

现状处理见 `tools/hd1910/servo_probe/ATTRIBUTION.md`（保留逐字节副本 + 标注出处 + 不改一行 + 再分发前须向上游确认）。

**评估结论**：把 `servo_probe/` 从 `tools/` 移进新包 `mduck/` 是**再分发动作**，不是内部重构。整合清单里必须为它保留 `ATTRIBUTION.md` 与上游出处，并在发布包（`make_manifest`）里携带。这条不影响工期，但漏了会在发布环节卡住。

---

## 3. 建议的整合形态

**一个 CLI + 一个共享库，引擎不动。**

```
mduck/                         # 新包（= 共享库）
  plant.py                     # ★ 唯一植物真相：吸收 plant_spec + plant_id + swap_plant（带任务 scope）
  contract.py                  # obs 61 / act 14 / schema-2 / runmeta 指纹
  runner.py                    # env 构建与回放后端
  jobs.py                      # ★ 作业生命周期：start / poll / stop（CLI 前台、UI 后台共用）
  metrics.py                   # 跟踪率/摔倒/倾角/位移 统一口径
  io.py                        # runmeta / JSON 事件契约 / manifest
  cli.py                       # 薄层：tyro 解析子命令，只做「参数 → 调用 → 打印」
  scripts/                     # 薄入口，仿 mjlab 的 src/mjlab/scripts/（每子命令一个 main()）
```

`pyproject.toml` 里注册 console scripts（仿 mjlab 的 `[project.scripts]`），如 `mduck = "mduck.cli:main"`。

> **形态依据（见 §7）**：上游 `mjlab` 就是这样分的——`src/mjlab/scripts/` 放薄 CLI、`src/mjlab/` 放库、`[project.scripts]` 注册入口、用 `tyro` + dataclass 做声明式解析（`PlayConfig` + `run_play(task, cfg)`）。`.venv-mjlab` 已装 `tyro`，沿用它而不是引入新框架。

子命令（只收主线）：

| 子命令 | 吸收现有入口 |
|---|---|
| `mduck plant show / apply / check / selftest` | `plant_spec` / `apply_to_live` / `plant_id` / `selftest_plant_switch` |
| `mduck check` | `check_velocity_ready`（发车前静态检查） |
| `mduck train smoke / explore / resume`（+ `standup`） | `hd1910/*.sh`、`train_velocity_variant`、`train_heading_variant` |
| `mduck eval gates / tracking` | `eval_velocity_in_sim`、`eval_tracking` |
| `mduck export onnx / mcu / manifest` + `mduck parity` | `export_onnx`、`make_manifest`、`check_onnx_parity` |
| `mduck rehearse` | `rehearse_hd1910` |
| `mduck record` | `record_walk` |
| `mduck watch` / `dashboard` | `watch_milestones`、`make_train_dashboard` |
| `mduck stage0` | `sts_bench`、`probe_heading_loop`、`check_step_vs_sim` |

**硬原则**：

1. 训练侧只做**包装**，不改 `train` 的调用语义（AGENTS.md：改训练代码必须重训）。
2. 植物切换**显式、可逆、回读**，绝不隐式。
3. 植物**作用域按任务隔离**：`velocity` / `standup` 各有独立植物槽，`apply_to_live` 必须指定作用域，`--check` 分别回读（§2.6）。
4. 主线 eval **不再 import 侧线**（§2.2）。
5. 所有读数强制带 `plant_fingerprint`（机器化，不靠人记）。
6. 第三方副本随包携带 `ATTRIBUTION.md`（§2.7）。

---

## 4. 工作量与风险（估）

| 阶段 | 内容 | 估时 | 风险 |
|---|---|---|---|
| 0 | 建包 + 唯一 `PlantContext` + 指纹/runmeta + 自检；包住 `plant` 子命令；**定下 `io.py` JSON 契约与 `jobs.py` 作业接口**（为 UI 埋接缝，§8.3） | 1–2.5 天 | 低，不动训练 |
| 1 | `check` + `eval` 统一入口；把 `swap_plant` 从侧线提取到共享库 | 2–3 天 | 中（要动 eval 的 import） |
| 2 | `train` / `export` / `parity` / `rehearse` / `record` 归一 | 3–5 天 | 中（shell 包装，语义不能变） |
| 3 | `watch` / `dashboard` / `stage0` 收口 | 2–3 天 | 低 |

**合计约 1.5–2 周**（单人，无 GPU 等待）。

### 4.1 开工前置条件（比工期更硬）

阶段 0 要动的四个文件 —— `plant_spec.py`、`plant_id.py`、`apply_to_live.py`、`eval_joy_in_sim.swap_plant` —— **全部在训练进程的 import 闭包里**。尤其 `apply_to_live.py` 改的就是训练正在读的 `site-packages/mjlab_microduck/robot/microduck_constants.py`。

⇒ **有训练在跑时动手 = 把正在跑的实验静默作废**，而且不报错、不下线、loss 曲线照常。这比"工具给出错数"严重一档：

| 风险 | 后果 | 可发现性 |
|---|---|---|
| 植物 4 源未统一 | 工具给出错数 | 可发现，重跑即可 |
| 训练期间改植物文件 | **正在跑的实验作废** | **不可发现**（日志正常，指纹是在训练启动时拍的） |

⇒ **前置条件：当前训练结束 + checkpoint 选点评估完成 + 无 GPU 任务在跑**。三者同时满足才开工。

### 4.2 风险排序（修正后）

① **开工时机不对**（§4.1）——先看有没有训练在跑，再谈别的；② 植物语义四源 + 作用域未隔离（§2.1、§2.6）没统一就先写壳；③ 包装训练时改了调用语义触发重训；④ `apply_to_live` 的全局副作用被隐式触发（§2.4）。

前三条都能在"先做阶段 0"里化解；第 ① 条不能靠设计化解，只能靠**等**。

---

## 5. 明确不做

- 不合并 `repo/` 旧栈（已定：保留遗留）。
- 不把 joy 侧线并入主线（只提取 `swap_plant` 这个函数）。
- 不**现在**做 UI；但第一版必须为它埋接缝（§8）。
- 不做"把所有 70+ 脚本塞进一个文件"。

---

## 6. 建议的第一步（如果要推进）

先做**阶段 0**：一个 `mduck plant` 子命令 + 唯一 `PlantContext`（带任务 scope），把 `plant_spec` / `plant_id` / `apply_to_live` / `swap_plant` 四个植物源收口到一处，并加负对照自检（仿 `selftest_plant_switch.py` 的手法：故意改坏 → 检查必须变红）。

同时把 `io.py` 的 runmeta/JSON 事件契约和 `jobs.py` 的 `start/poll/stop` 接口一并定下（§8.3），为 UI 留门——成本约 0.5 天，不做的话 UI 期要返工。

这一步不动训练代码语义、不烧 GPU、风险最低，且正好治本项目最大的坑。

**但先过 §4.1 的前置条件**：当前无训练在跑、无 GPU 任务、上一轮实验的选点评估已完成。否则收口动作会污染正在跑的实验，而且不会有任何报错。

---

## 7. 开源社区参照：上游自己就是这套架构

整合方案不是凭空设计——**本仓库的上游框架 `mjlab` 用的正是"薄 CLI + 共享库 + 可插拔后端"**。源码在 `microduck-software/.upstream/mjlab-1.3.0/`（`.venv-mjlab` 里装的就是它），逐项对照：

| 我们的主张 | mjlab 1.3.0 的实际做法 | 证据 |
|---|---|---|
| 薄 CLI 包在共享库外 | `src/mjlab/scripts/` 放薄入口，`src/mjlab/` 放库 | `pyproject.toml` `[project.scripts]` 注册 `train/play/demo/list-envs/viz-nan/export-scene` |
| 声明式参数解析 | 用 `tyro`（不是 Typer/Click），`PlayConfig` dataclass | `mjlab/scripts/play.py:33` `@dataclass PlayConfig` + `tyro.cli(...)` |
| 逻辑不写在 argparse 回调里 | `main()` 只解析，`run_play(task_id, cfg)` 干活 | `mjlab/scripts/play.py:57,298-325` |
| CLI 之间共享小工具 | 专门的 `_cli.py` | `mjlab/scripts/_cli.py`（`maybe_print_top_level_help`） |
| **UI 是另一个后端** | viewer 可插拔：`Literal["auto","native","viser"]` → `NativeMujocoViewer` / `ViserPlayViewer` | `mjlab/scripts/play.py:49,280-293` |
| 任务注册表 | `mjlab.tasks.registry`（`list_tasks` / `load_env_cfg` / `load_rl_cfg`） | `mjlab/scripts/play.py:17` |
| **顶层命令名的代价（反面）** | `train` 与 mjlab 的 `train` **同名冲突**，last-writer-wins；删掉自己的反而两边都没有 | `microduck_rl-develop/pyproject.toml:44-52` |

**本仓库更近一层的上游 `pollen-robotics/microduck_rl` 也一样**：`scripts/` 目录（`export.py`、`infer_policy.py`、`play_latest.py`、`testbench_sim2real.py`、`wandb_utils.py`…）+ `src/mjlab_microduck/` 库 + `[project.scripts]`（`train` / `duck-body` / `publish`）。

**结论**：

1. 我们的整合形态**不是发明，是把上游已验证的形态落到本项目**——这大幅降低了设计风险。
2. 沿用 `tyro` 而不是引入新框架：`.venv-mjlab` 已装，训练侧也在用（`mjlab.TYRO_FLAGS`），`PlayConfig` dataclass 模式可直接抄。
3. 最值得抄的一处是 **`play.py` 的 viewer 后端抽象**：它证明"同一份逻辑、换一个后端"在本领域是被接受的成熟做法（§8）。
4. **但有一样不要抄：顶层命令名。** `microduck_rl-develop/pyproject.toml:44-52` 留了一段很长的注释，记着 `train` 与 mjlab 的 `train` 同名冲突的坑：同名 console script 是 last-writer-wins，两个 dist-info 的 RECORD 都声称拥有 `bin/train`，**删掉自己那行并不会把名字还给 mjlab** —— `uv sync` 会按自己的 RECORD 卸载它，而没有任何东西重建 mjlab 的，于是 `uv run train` 落到 PATH 上一个不相干的 `train`（liblinear 的，2026-08-31）。

   ⇒ 这从反面支持本文档采用的 **`mduck <subcommand>`** 形态：父命令 `mduck` 不与任何上游命令撞名，子命令在 `mduck` 命名空间内，天生免疫这个坑。若按 mjlab 那样"每个命令一个顶层入口"（`mduck-train`、`mduck-eval`…），就会重复上游踩过的坑，而且一旦撞名几乎无法干净回退。

> 注：`web_search` 在当前环境不可用（缺 `DEEPSEEK_API_KEY`），`web_fetch` 对 GitHub 直连不稳定；以上证据全部取自**本地已 clone 的上游源码**，比网页更权威。

---

## 8. UI 扩展性（先 CLI、后 UI）

**问题**：第一版做纯 CLI，以后加 UI 方便吗？**答：方便，但有条件。**

### 8.1 前提：CLI 做薄

```
                 ┌──────────────┐
   阶段0 先做    │  共享库 mduck │   plant / contract / runner / jobs / metrics / io
                 └──────┬───────┘
                        │  同一套 API
              ┌─────────┴─────────┐
              ▼                   ▼
        ┌───────────┐        ┌──────────┐
        │  CLI 薄层  │        │  UI 薄层  │   ← 以后加
        │ tyro 解析  │        │ web / 看板 │
        └───────────┘        └──────────┘
```

如果 `mduck plant apply` 的实现直接写在 tyro 回调里，将来 UI 要**重写一遍**。如果实现全在共享库、CLI 只做"参数 → 调用 → 打印"，UI 就是**再加一个薄前端**。

### 8.2 两个 UI 类别要分开

"接 UI"在本仓库里其实有两类，不要混：

| 类别 | 是什么 | 现状 |
|---|---|---|
| **3D 可视化** | 看机器人跑（viser 式 3D 窗口） | **上游已有**：`ViserPlayViewer`；本仓库已 patch（`tools/patch_mjlab_viser_gui.py`、`tools/patch_viser_zh.py`）并有 `tools/run_viser.sh`。依赖实测在位：`viser 1.1.1` + `mjviser 0.0.14` |
| **作业控制/监控看板** | 启动/停止/监控训练、看指标 | 脚本版已有：`make_train_dashboard.py`、`watch_milestones.py`（本质就是最早的 UI） |

第一类**已经存在**，不需要"接"。第二类才是"未来接 UI"的主力，也是 §8.3 要埋的接缝。

### 8.3 三个必须现在埋好的接缝

**1. 作业抽象（`jobs.py`）** —— 训练是长时间子进程（`train.exe`），不是函数调用。CLI 前台跑、UI 后台跑，要共用同一套 `start / poll / stop`。不做的话 UI 只能去解析 stdout。

**2. 事件/结果契约统一成 JSON（`io.py`）** —— 这一条不是"预防性设计"，是**已经在还债**。

实测两个看板读的**都不是 JSON，而且彼此毫无关系**：

| 脚本 | 实际数据源 |
|---|---|
| `tools/make_train_dashboard.py:19,47,52` | **tensorboard 二进制**（`EventAccumulator` + `events.out.tfevents*`） |
| `tools/watch_milestones.py:134,146` | **正则解析 `train_*.log` 文本** |

而 `watch_milestones.py:146` 那个 `open(log_path)` 逐行正则，正是本文档警告过的"解析 stdout 的脆弱东西"—— **它已经存在了**。所以这条接缝的真实理由是：两套临时方案已经并存，UI 再来就是第三套，且三者对"训练跑到哪了"给出的口径互不可比。

把 `runmeta` + 读数 JSON 定成唯一事件源，UI 的"训练进度页"就是读这些文件，不用新造协议。**但只定"静态读数文件"，不定义事件流协议**（见 §8.6-②）。

**3. 状态与副作用集中** —— `apply_to_live`（写 site-packages）、`patch_sts3215`（改 editable bam）必须只走共享库的一个入口，UI 才不会绕过"显式 + 可逆 + 回读"的纪律（§2.4）。

### 8.4 成本与坑

| | |
|---|---|
| 好消息 | 若按上面分层，**UI 是纯增量**：不动训练/评估逻辑、不触发重训、不烧 GPU |
| 代价 | 阶段 0 要多花约 0.5 天把 `jobs.py` 接口和 JSON 契约定好；不做的话 UI 期返工更多 |
| 真正的坑 | GPU 独占：UI 后台跑训练时前台再点"评估"会抢卡 → 需要在共享库加**单卡互斥锁**（CLI 和 UI 共用） |
| 形态选择 | 本地 web（viser 式）比桌面 GUI 划算：复用现有栈、跨平台、不用打包 |

### 8.5 结论

阶段 0 的 `mduck` 骨架里，**把 `io.py`（runmeta/JSON 契约）和 `jobs.py`（作业生命周期）当 UI 的地基来设计**，即使第一版只有 CLI。这样后续加 UI：

- 纯增量，不改语义 → 不触发重训纪律
- 估时：本地 web 看板 + 作业控制约 **+1 周**
- 不做的代价：UI 期大概率返工，且"看训练进度"会做成解析 stdout 的脆弱东西（**注：这件事已经发生了，见 §8.3-2**）

### 8.6 三点保留（建议，非结论）

以下是复核本文档时提出的不同意见，与上面的结论**不矛盾，是细化**。留在这里供决策时取舍。

**① `jobs.py` 阶段 0 只定签名，不写实现。**

阶段 0 只有 `mduck plant`，而 plant 操作是**秒级同步调用**——没有长时作业可管。给一个同步命令套 `start / poll / stop`，会写出一套从没被真实执行过的接口，等于空壳，而且大概率设计偏了（作业抽象的真实约束只有在接 `train` 时才会暴露）。

真正需要它的是阶段 2 的 `train`（长时子进程 + 中断/续跑）。⇒ 阶段 0 只把签名与语义写进文档，实现推到阶段 2。这把 §4 表里阶段 0 的 "+0.5 天"压到约 0.1 天，且不损失任何 UI 扩展性。

**② JSON 契约只定"静态读数文件"，不定"事件流协议"。**

建议只要求三件事：所有读数落 `out/*.json`；每个文件必含 `plant_fingerprint` / `run_name` / `ts`；文件名模式固定。**不要**在阶段 0 定义 schema 版本号、事件类型枚举、流式推送格式——那是协议设计工程，而且没有真实消费者时必然设计错。

UI 的"训练进度页"读这些静态文件已经够用（轮询 1 Hz），真需要推送时再演进。

**③ GPU 互斥锁建议现在做，不等 UI 期。**

实测：仓库里**没有任何锁机制**（`flock` / `msvcrt.locking` / `LockFileEx` / `.lock` 在 `tools/` 下零匹配）。而互斥这件事已经踩过一次：FD 工具与探针抢 COM3，只能靠人记得"开一个必须先关另一个"（`tools/hd1910/README.md` 用警告文字兜着）。

⇒ 现状是**多窗口跑训练/评估就会撞卡**，不需要等到 UI。建议阶段 0 顺手加一个最简的单卡锁（`out/.gpu0.lock` + pid 与 run_name 内容），成本约 0.1 天，比 UI 期再补便宜。

---

## 附：主线工具清单（in 范围）

**`tools/hd1910/`**（新增层，相对自洽）：

| 文件 | 角色 |
|---|---|
| `plant_spec.py` / `apply_to_live.py` / `probe_plant_law.py` / `selftest_plant_switch.py` | 植物数字 + 可逆覆盖 site-packages + 回读 + 负对照 |
| `smoke_train.sh` / `explore_train.sh` / `resume_train.sh` | Velocity 训练包装（写 runmeta、plant 闸门） |
| `smoke_standup.sh` / `explore_standup.sh` / `resume_standup.sh` | StandUp 训练包装 |
| `parity_smoke.sh` | ONNX↔ckpt parity |
| `rehearse_hd1910.py` / `.sh` | 部署彩排（包 `rehearse_deploy.py`） |
| `probe_heading_loop.py` | heading 闭环机制验证 |
| `sts_bench.py` / `check_step_vs_sim.py` / `servo_probe/` | 阶段 0 台架/实测。⚠️ `servo_probe/hd1910_readonly.py` 是上游逐字节副本、**许可未明确声明**，收口时必须带上 `ATTRIBUTION.md`（§2.7） |
| `patch_sts3215_q_target_smooth.py` | 给 editable bam 打补丁（全局副作用） |

**`tools/` 共享层**：`eval_velocity_in_sim`（评估）、`eval_tracking`（跟踪）、`plant_id`（指纹）、`check_velocity_ready`（发车前静态检查）、`export_onnx` + `check_onnx_parity`（导出）、`make_manifest`（发布包）、`record_walk`（录像）、`train_velocity_variant` / `train_heading_variant`（进程内改 cfg）、`watch_milestones`（守候）、`make_train_dashboard`（看板）。
