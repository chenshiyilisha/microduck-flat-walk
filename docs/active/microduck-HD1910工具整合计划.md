# MicroDuck HD-1910 工具整合 — 分步执行计划

日期 2026-11-02。配套评估：[microduck-HD1910工具整合评估.md](microduck-HD1910工具整合评估.md)。

**本文档是执行计划**：一步步来，每步有产物、验收方式、门禁。估时按"我来做"计（AI agent，含验证）。

---

## 0. 总览

**目标**：在**新项目**里（不碰现有 `microduck-software/`），交付一个 `mduck` CLI + 共享库，收口 HD-1910 主线工具。

**形态**：仿上游 `mjlab`——`mduck/` 共享库 + `mduck/scripts/` 薄入口 + `[project.scripts]` 注册 + `tyro` 声明式解析。

**硬约束**（每步都要守住）：

1. 不碰现有项目任何文件（含 `.venv-mjlab`、`site-packages`）。
2. 新项目**自带独立** `.venv-mjlab`（`tools/hd1910/server_pack/README.md`：「不要拷本机 `.venv-mjlab`（~5 GB、路径/驱动绑定）」）。
3. 训练侧只**包装**，不改 `train` 的调用语义（AGENTS.md 铁律）。
4. 每步有**门禁**，过了才进下一步。
5. 所有读数强制带 `plant_fingerprint`。
6. **植物落点有两个**（不是"一个"）：
   - `<venv>/Lib/site-packages/mjlab_microduck/robot/microduck_constants.py`（`_BAM_ACTUATOR_KWARGS`）
   - `<venv>/Lib/site-packages/mjlab_microduck/hd1910_bam_register.py`（`apply_to_live._install_register()` 写入；P3 的 `gate_ok` 还要求它在位）

   两者都不是 git 文件、任何 `uv sync` / 重建 venv 都会静默退回 XL330 默认 ⇒ **bootstrap 后第一件事永远是 `mduck plant check --task velocity`**。

**阶段总表**

| 阶段 | 目标 | 估时 | 出门门禁 |
|---|---|---|---|
| 0 | 骨架 + `PlantContext` + `io`/`jobs` 契约 | 2.5 天 | plant round-trip + 负对照自检全绿 + 两任务期望值对账 |
| 1 | `check` + `eval` | 2–3 天 | eval 带指纹，低 CV 量数值与旧脚本对齐 |
| 2 | `train` / `export` / `parity` / `rehearse` / `record` | 3–4 天 | smoke + parity 通过 |
| 3 | `watch` / `dashboard` / `stage0` | 2–3 天 | 各子命令跑通 |
| 收尾 | README + CI + 旧入口冻结 + 干净克隆验证 | 1 天 | 新克隆可跑 |

**合计 10–13 个工作日 ≈ 2–2.5 周。**

> 估时口径：本文按「AI agent 执行，含自验证」计；评估文档的 1.5–2 周是「单人」口径。**两份文档的周数不可直接比**，排期以本文为准。
> 阶段 0 早期版本写「1–2 天」，与其子项加总（0.5+0.3+0.5+0.2~0.3+0.5+0.5）不符，已改正。

---

## 阶段 0：骨架 + 植物唯一真相

> 目的：把"植物身份四源 + 未隔离作用域"（评估 §2.1、§2.6）收口成一个东西，并埋好 UI 接缝（§8.3）。**这是后面所有阶段的地基。**

### 0.0 开工前必须先定的 5 件事（决策清单）

这 5 条不定，0.1 就会写错方向。**已按第 1 条的 A 方案定稿，其余按本文写的走**，要改请先说。

| # | 问题 | 现状证据 | 定稿 |
|---|---|---|---|
| 1 | 「两任务独立植物槽」能不能做 | `microduck_constants.py:163` 一个 `_BAM_ACTUATOR_KWARGS` → `:176` 一个 `actuators` 对象 → `:235`(WALK) 与 `:245`(standup) **引用同一对象** ⇒ 真隔离必须改 :245 一行。⚠️ 行号以**安装版**（`.venv-mjlab/Lib/site-packages/...`，371 行）为准；上游源码 `.upstream/microduck_rl-develop` 里是 `:237/:247`（373 行），差 2 行 | **A 方案：承认单植物**（零源码改动），用 runmeta 期望值 + `check` 对账替代隔离。B（双 venv）/C（改上游一行）见 0.3 后备 |
| 2 | 新项目用 editable 还是 non-editable 装 `mjlab_microduck` | 现状是 **non-editable**（`site-packages/mjlab_microduck/` 是真拷贝，`direct_url.json` 无 `editable`）；`plant_spec.py:27-35` 把 `LIVE_CONSTANTS` 硬编码到 `<venv>/site-packages/...` | **non-editable + vendor 快照**。editable 会让 plant 落源码树，`apply_to_live` 只改 site-packages ⇒ 改不到 |
| 3 | 新项目从哪拿源码 | `plant_spec.py:11` `ROOT = parents[2]` 算的是 `microduck-software/`，原样复制进新项目仍指旧目录 | **vendor 两份**：① 上游 `microduck_rl@b02fdea` 快照（进 `vendors/`）；② **HD-1910 本地独有资产**（进新项目根的 `tools/`，见 0.2.1）。**不引用**旧项目 `.upstream/` 路径 |
| 4 | 环境冒烟用哪个脚本 | `smoke_train.sh:26` 闸门是 `detected=='hd1910' and kp_fw==32.0`（m5 植物）；`smoke_heading.sh:32` 才是 `hd1910_kp5 / kp_fw==5.0` | **只用 P3 闸门那条**。⚠️ 在正确装了 P3 的机器上跑 `smoke_train.sh` **必然红**；能跑通的机器装的是 m5 植物 |
| 5 | `out/` 根目录归谁 | 旧项目 `microduck-software/out/` 里已有 ONNX/CSV/runmeta | 新项目写**自己的** `out/`；旧目录**只读**（迁移清单见收尾）。路径一律走配置，不写相对 cwd |

---
### 0.1 建新项目骨架（约 0.5 天）

| 项 | 内容 |
|---|---|
| 目录 | `<工作区>/microduck-tools/`（名字待定，占位）；内含 `vendors/microduck_rl@b02fdea/`（上游快照，见 0.0-#3）+ **根 `tools/`**（HD-1910 本地独有资产，见 0.2.1） |
| `pyproject.toml` | `name = "mduck"`；`requires-python = ">=3.12,<3.13"`；依赖 `mjlab==1.3.0` / `torch==2.9.1` / `tyro` / `warp-lang==1.12.0` / **`pyserial`**（阶段 3 的 `stage0` 台架要用，别那时才发现）/ 等；`[project.scripts]` 注册 `mduck = "mduck.cli:main"` |
| 包结构 | `mduck/`（共享库）+ `mduck/scripts/`（薄入口）+ `mduck/tests/` |
| 首批模块 | `cli.py`（tyro 入口）、`plant.py`、`contract.py`、`runner.py`、`jobs.py`、`metrics.py`、`io.py` |

**验收**：`uv run mduck --help` 能打印子命令列表（哪怕只有 `plant`）。

### 0.2 环境 bootstrap（串行，可后台跑）

| 项 | 内容 |
|---|---|
| 安装 | 从 **本项目 vendor 的快照**（`vendors/microduck_rl@b02fdea`）装 **non-editable** `mjlab_microduck`（给 `mjlab.tasks` 入口点）。⚠️ **不要 editable、不要指旧项目 `.upstream/`** —— 见 0.0-#2/#3 |
| BAM pin | `bam-62bd8ce…`（editable，勿整包装 ftservo-bam） |
| 渲染 | `MUJOCO_GL=glfw`（Windows） |
| 植物 | bootstrap 末尾**必须** `apply_to_live --plant p3` 并 `--check`（新 venv 的 site-packages 是全新的 XL330 默认，不 apply 就是错的植物） |
| 冒烟 | 走 P3 闸门那条（等价 `smoke_heading.sh`：64×5 + heading readback）。**不要用 `smoke_train.sh`** —— 它的闸门是 `kp_fw==32.0` |

**验收**（三条缺一不可）：
1. `python -c "import mjlab_microduck, torch; print(torch.cuda.is_available())"` → `True`
2. `mduck plant check --task velocity` → `detected=hd1910_kp5 / kp_fw=5.0` 且**退出 0**
3. 冒烟 log 含 `device=cuda:0`

> 只验 1、3 是不够的：plant 错了照样能跑出 `device=cuda:0`，而这正是本项目踩过的坑（cfg/mdp 哈希全绿、vx 从 0.316 掉到 0.109）。

> **并行建议**：0.2 的下载（torch cu128 ~2GB）是串行长 pole，**先在后台启动**，同时做 0.3–0.5 的代码。

### 0.2.1 vendor 清单（HD-1910 本地独有资产，必须随新项目带走）

> 这是 0.2 验收第 2 条能过的前提。**只 vendor `microduck_rl` 快照是不够的**：HD-1910 植物依赖三个上游没有的本地资产。

| 资产 | 旧位置 | 新项目落点 | 谁在用 |
|---|---|---|---|
| `tools/bam_params/hd1910/m5.json` | `microduck-software/tools/bam_params/hd1910/` | **新项目根 `tools/bam_params/hd1910/m5.json`** | `kwargs_block()` 生成的 `json_path`；`_readback` 的 m5 闸门 |
| `tools/bam_params/hd1910/ftservo_official_m6.json` | 同上 | **新项目根 `tools/bam_params/hd1910/`** | `kwargs_block()`；m6 闸门 |
| `tools/bam_params/hd1910/official_m6_stslaw.json` | 同上 | **新项目根 `tools/bam_params/hd1910/`** | `kwargs_block()`；P3 闸门 |
| `tools/bam_actuators.py` | `microduck-software/tools/` | **新项目根 `tools/bam_actuators.py`** | `apply_to_live._install_register()` 生成的 wrapper 指向 `parents[4]/tools/bam_actuators.py`；`rehearse_hd1910.py:29` 直接 import |

**落点为什么必须是"新项目根的 `tools/`"（不是 `vendors/`）**：

- `kwargs_block()` 生成的 `json_path` 是 `Path(__file__).resolve().parents[5] / "tools" / "bam_params" / ...`，`__file__` 是 **site-packages 里那份** `microduck_constants.py`，`parents[5]` 自动等于"装了 venv 的那个项目根"。所以新项目根必须真的有 `tools/bam_params/hd1910/*.json`，否则 `load_model` 找不到参数。
- `_install_register()` 生成的 wrapper 用 `parents[4] / 'tools' / 'bam_actuators.py'`，同理指向新项目根的 `tools/bam_actuators.py`。
- 证据：`apply_to_live.py:105-115`、`plant_spec.py:159-160 / 173-174 / 186-187`。

**不补的后果**：`mduck plant apply --plant p3` 会在 `_install_register` 处 `SystemExit("missing register source: .../tools/bam_actuators.py")`，或 `gate_ok=False` → exit 1。**会响，但计划没预判，实现者会以为是别的问题。**

> **已定案（2026-11-02）：原表里的 `tools/bam_api.py` 已删除，不迁。** 它是 16 行 `print(inspect...)` 的 REPL 草稿（无 SPDX / 无 docstring / 无 `__main__`），全仓零 import、零 `python tools/bam_api.py` 调用，`.upstream/` 里也没有同名文件（非上游产物）。它当年要回答的问题（`bam.model.load_model` 的签名与 params 目录）已固化在 `tools/bam_actuators.py` 的 docstring 里。

> ⚠️ 上游 `microduck_rl` 里**没有** `bam_params` 目录（全仓只搜到一条陈旧注释），`bam_actuators.py` 也是本地独有 —— 这两样不会随 `microduck_rl` 快照自动出现。

### 0.3 `mduck/plant.py` — 唯一 `PlantContext`（约 0.5 天）

吸收四处，**带任务期望值（不承诺物理隔离）**：

| 吸收自 | 内容 |
|---|---|
| `tools/hd1910/plant_spec.py` | m5 / m6 / `hd1910_kp5` / xl330 的数字 + 出处（**4 个植物**）；`LIVE_CONSTANTS` 的硬编码路径改为 `venv_root` 参数 |
| `tools/plant_id.py` | 回读 live `_BAM_ACTUATOR_KWARGS` 的指纹 |
| `tools/eval_joy_in_sim.swap_plant` | 植物切换（`default`/`bam` 两档；改 mduck 后统一叫 `--plant`，语义等同） |
| `tools/hd1910/apply_to_live.py` | 可逆覆盖 `site-packages/…/microduck_constants.py` 的实现（含 `.bak` 备份） |

**关键设计（A 方案：单植物 + 期望值对账）**

现状是**一个**执行器对象被两个任务共用，见 0.0-#1 的证据链。因此阶段 0 **不承诺物理隔离**，改为：

**期望值要分两层（P3：别混成一个字段）**

| 层 | runmeta 字段 | 谁写 | 谁校验 | 用途 |
|---|---|---|---|---|
| 任务期望植物 | `task_expected_plant` | `apply --task` | `check --task`、`train` 前 | "这个任务此刻该用什么植物训练" |
| ckpt 训练植物 | `ckpt_trained_plant` | `export` / ckpt 元数据 | `eval` / `rehearse` / `deploy` 前 | "这个 checkpoint 是拿什么植物训出来的" |

> 为什么分两层：`rehearse` 要匹配的是**被彩排 ckpt 的训练植物**（阶段 2.3），不是"任务期望植物"。混成一个字段，阶段 2 会拿 velocity 的期望去套 standup 的 ckpt。

1. `PlantContext(venv_root=...)` —— **venv 根显式传入**，禁止 `Path(__file__).parents[N]` 推。理由：`plant_spec.py:11` 的 `ROOT = parents[2]` 复制进新项目后仍指向旧的 `microduck-software/`，会去改旧项目的 site-packages，直接违反硬约束 1。
2. `apply --task velocity|standup|both` 的 `--task` **只写进 runmeta 的 `task_expected_plant`**，不改变物理事实（物理上只有一个植物）。
3. `check` 打印三行：**实际植物 / velocity 期望 / standup 期望**；退出码按 `--task` 判（见 0.5）。
4. 每次 `train` / `eval` 在 runmeta 里写 `plant_fingerprint`（实际）+ `task_expected_plant`；`export` / `rehearse` 额外写 `ckpt_trained_plant`。

**后备（阶段 0 不做，记录在此）**

| 方案 | 做法 | 何时才值得 |
|---|---|---|
| B. 双 venv | velocity / standup 各一套 venv，plant 落各自 site-packages | 真需要**同时**跑两种植物的任务（如并行对照实验）。代价 2×5 GB + torch 装两次 |
| C. 改上游一行 | `:245` 指向第二个 actuator 对象 | 需要长期双植物共存。代价：改上游文件一行 ⇒ 重走 pristine 审计（当前 254 文件中 249 逐字节相同），并记进「本项目对上游的唯一修改」清单 |

**验收**：
- 单元测试覆盖 4 种植物（m5 / FTSERVO_M6 / M6_KP5 / XL330）× 2 种期望 scope 的 round-trip；
- 植物是 P3 时，`--task standup` 期望留 m5 ⇒ `check --task standup` **必红**、`check --task velocity` 绿（对账生效的负对照）；
- `venv_root` 传错路径时 `check` 报错退出，不静默改文件。

### 0.4 `mduck/io.py` + `mduck/jobs.py` + 单卡锁（约 0.2–0.3 天）

> 按评估 §8.6 的三条保留收紧：**不写没被真实执行过的接口**。

| 模块 | 阶段 0 做到什么程度 |
|---|---|
| `io.py` | **只定静态读数文件契约**：所有读数落 `out/*.json`；每个文件必含 `plant_fingerprint` / `run_name` / `ts`；文件名模式固定。**不**定义 schema 版本号 / 事件类型枚举 / 流式推送格式（§8.6-②）。另：`out/` **根由配置给出**（默认新项目 `out/`，旧 `microduck-software/out/` 只读），禁止相对 cwd 解析 |
| `jobs.py` | **只写签名 + 语义进文档**（`start / poll / stop` 的契约），**不实现**。实现推到阶段 2（接 `train` 时才有真实长时作业）——§8.6-① |
| 单卡锁 | 加最简 `out/.gpu0.lock`，约 0.1 天。**现在做**，不等 UI：现状是仓库无任何锁机制，多窗口跑训练/评估就会撞卡（§8.6-③）。内容 `{pid, host, run_name, ts}`；**Windows 无 `flock`** ⇒ `os.open(..., O_CREAT|O_EXCL)` 创建；**必须做陈旧锁回收**：pid 不存在（且 host 是本机）即视为可抢占，另给 `--force` 破锁。没有回收的锁，一次崩溃会永久锁死全部任务 |

**验收**：写 runmeta → 回读一致（`plant_fingerprint` 在位）；单卡锁互斥生效（第二个进程被拒）；**手工 kill 持锁进程后新进程能接管**（陈旧锁回收的负对照）；**不**要求有可跑的 `start/poll/stop`。

### 0.5 CLI + `plant` 子命令（约 0.5 天）

| 子命令 | 行为 |
|---|---|
| `mduck plant show` | 打印实际植物 + 指纹 + 各任务期望值 |
| `mduck plant apply --plant <name> [--task <scope>]` | 写前备份 → 覆盖 → `--check` 回读 → 写 runmeta（`plant_fingerprint` 实际值 + `task_expected_plant` 期望值；`--task` **不改变物理事实**） |
| `mduck plant check [--task velocity|standup|both]` | 打印「实际 / velocity 期望 / standup 期望」三行；**退出码按 `--task` 判**（见下） |
| `mduck plant selftest` | 负对照：故意改坏 → 必须变红 → 恢复 |

**`check` 的退出码（P2：按 `--task` 判，消除"永远红"）**

`check` 永远打印三行，但**只按 `--task` 指定的任务判退出码**：

| `--task` | 退出 2 的条件 |
|---|---|
| `velocity`（默认） | 实际植物 ≠ velocity 期望 |
| `standup` | 实际植物 ≠ standup 期望 |
| `both` | 实际植物 ≠ velocity 期望 **或** ≠ standup 期望 |

> 为什么不默认 `both`：P3 下 standup 期望是 m5，`both` 会永远红 ⇒ "bootstrap 后 plant check 是绿门"无法成立。`both` 留给 CI / 发车前的严格检查。

**验收**：
- 切到 `hd1910_kp5`：`check --task velocity` 退出 0（报 velocity ✓、standup ⚠）；`check --task both` 退出 2 —— **这不是 bug，是 A 方案的正常输出**（物理上只有一个植物），它把评估 §2.6 的隐式连带从"静默发生"变成"每次都看见"；
- 期望值写进 runmeta，后续 `train`/`eval` 会自动带上。

### 0.6 负对照自检（约 0.5 天）

仿 `selftest_plant_switch.py`：故意把植物改坏 → 所有闸门必须变红 → 再恢复 → 全绿。

**阶段 0 门禁**：plant round-trip 全绿 + 负对照全绿 + `check` 能报出「实际 vs 两任务期望」并**按 `--task` 判退出码**（P3 下 `--task velocity` 绿、`--task both` 红）。

---

## 阶段 1：`check` + `eval`（约 2–3 天）

### 1.1 `mduck check` ← `check_velocity_ready.py`

把发车前静态检查收进 CLI（obs 61 / act 14 / cfg 字节哈希 / 求解器 / 磁盘 / GPU）。

### 1.2 提取 `swap_plant` 到共享库

`eval_velocity_in_sim.py` / `eval_tracking.py` 目前 `from eval_joy_in_sim import swap_plant`（评估 §2.2）。改为从 `mduck/plant.py` 导入，**主线不再 import 侧线**。

### 1.3 `mduck eval gates` ← `eval_velocity_in_sim.py`

### 1.4 `mduck eval tracking` ← `eval_tracking.py`

**阶段 1 门禁**：
- eval 输出**必须**带 `plant_fingerprint`；
- 同 checkpoint、同命令、**同仪器**，新工具读数 vs 旧脚本：`error_vel_xy` 相对差 **< 2%**、`vx_median` **< 3%**（实测 CV 0.54% / 1.82%，N≥3 次取中位数并报 sem）；
- ⚠️ **禁止**用位移类量做判据（`abs_dy_body_median` CV 31.4% ⇒ 单跑不可复现，`|dy|` 闸门在本项目已作废）；**禁止**跨版本评估脚本互相比较（历史数字不可混用）；
- 主线工具不再 import joy 侧线。

---

## 阶段 2：`train` / `export` / `parity` / `rehearse` / `record`（约 3–4 天）

### 2.1 `mduck train smoke / explore / resume`（+ `standup`）

包住 `tools/hd1910/{smoke,explore,resume}_train.sh` 与 `{smoke,explore,resume}_standup.sh`，以及 `train_velocity_variant.py` / `train_heading_variant.py`。env 变量收敛成 CLI 参数。

**验收**：`mduck train smoke` 与旧脚本等价（runmeta 内容一致）。

### 2.2 `mduck export onnx / mcu / manifest` + `mduck parity`

包住 `export_onnx.py`、`make_manifest.py`、`check_onnx_parity.py`。

**验收**：parity max|Δ| 与归档值同级（历史值 ≈2.5e−6）。

### 2.3 `mduck rehearse` ← `tools/hd1910/rehearse_hd1910.py` / `tools/rehearse_deploy.py`

⚠️ 两个文件不在同一目录：`rehearse_hd1910.py` 在 `tools/hd1910/`，`rehearse_deploy.py` 在 `tools/` 根。

⚠️ **植物陷阱**：`rehearse_hd1910.py:35-36` 写死 `PLANT = HD1910_OPENMICRODUCK_M5`、`KP_FW = 32.0`（旧稿引 `:20,30-31`，行号有误）；另外 `:33-34` 还写死了 `DEFAULT_ONNX = ROOT/"out"/hd1910_explore_4096x2000_1026_it1999.onnx` 与 `DEFAULT_OUT`。照抄进 CLI 就会拿 **P3 训出来的 ONNX 用 m5 植物彩排**，且默认指向旧项目的 `out/` —— 正是「换 plant = 换任务」换个地方复发。

**必做**：rehearse 的植物取自被彩排 ckpt 的 `plant_fingerprint`，不一致**直接拒跑**并打印两边的 plant 名。P3 的 ckpt 只能配 P3 植物彩排。

**验收**：六条件 sweep 跑通（`CONDITIONS` 实测 6 条：`nominal` / `low_batt` / `high_batt` / `train_lag3` / `train_lag4` / `train_lag6`）；P3 执行器路径判据通过；拿 m5 指纹的 ckpt 去配 P3 植物时必须报错退出（负对照）。

> 注：`tools/rehearse_deploy.py:477` 的 help 文案写「run all four training-DR conditions」，实际是 6 条 —— 旧工具的陈旧文案，别照抄。

### 2.4 `mduck record` ← `record_walk.py`

**阶段 2 门禁**：smoke + parity + rehearse 全过；训练侧调用语义**逐字不变**。

---

## 阶段 3：`watch` / `dashboard` / `stage0`（约 2–3 天）

### 3.1 `mduck watch` ← `watch_milestones.py`

### 3.2 `mduck dashboard` ← `make_train_dashboard.py`

（这俩就是最早的"作业控制/监控看板"UI，§8.2 第二类。）

### 3.3 `mduck stage0` ← `sts_bench.py` / `probe_heading_loop.py` / `check_step_vs_sim.py`

**阶段 3 门禁**：各子命令跑通；`watch` 的判停阈值与旧脚本一致。

---

## 收尾（约 1 天）

- `README.md`：安装、子命令表、门禁说明、**植物落点那一节（硬约束 6）**。
- CI：`uv run --with pytest pytest`（至少阶段 0 的 plant 单测）。**必须给无 GPU / 无串口的用例打 skip**（CI 上 `cuda`、`pyserial` 都不可用），否则 CI 从第一天就是红的。
- **旧入口冻结（低成本、高价值）**：在旧 `tools/` 的 plant 相关入口（`apply_to_live.py` / `plant_id.py` / `plant_spec.py` 的 CLI 入口）各加一行 banner：「已迁移到 `mduck`，这里的结果不再有指纹保证」。**只 print，不改逻辑**——否则收口期真相源从 4 个变 5 个，旧工具还在给出没指纹的数。
- **`out/` 迁移说明（P5：必须回答"新工具读不读旧产物"）**：**定稿为"新工具只写新 `out/`、不读旧 `out/`；旧数据一律人工搬到新 `out/`"**。理由：跨目录只读依赖会让"旧目录只读"的承诺变成假的（新工具偷偷读旧目录）。若确实要读（如阶段 1 的 eval 要喂历史 ckpt），必须显式写成配置项 `--legacy-out <path>`，并声明它**只读、可能随时失效**。这决定"旧数据能不能被新工具读"，阶段 1 第一天就会撞到。
- **干净克隆验证**：新机器 clone → bootstrap → `mduck plant check --task velocity`（须 `hd1910_kp5/kp_fw=5.0`、退出 0）→ 冒烟含 `device=cuda:0`。

---

## 里程碑验收

| 里程碑 | 判据 |
|---|---|
| M0 | 新项目骨架 + 独立 venv + **`plant check --task velocity` 报 hd1910_kp5/kp_fw=5.0 且退出 0** + 冒烟含 `device=cuda:0` |
| M1 | `mduck plant` 全绿 + 负对照全绿 + `check` 报出实际/两任务期望并**按 `--task` 判退出码**（A 方案，非物理隔离） |
| M2 | `mduck check` / `mduck eval` 跑通 + **低 CV 量**对齐旧脚本（`error_vel_xy` <2%、`vx_median` <3%，N≥3）+ 主线不 import 侧线 |
| M3 | `mduck train` / `export` / `parity` / `rehearse` / `record` 跑通 + 语义不变 + **rehearse 植物跟 ckpt 指纹** |
| M4 | `mduck watch` / `dashboard` / `stage0` 跑通 |
| M5 | README + CI（skip 标记齐全）+ 旧入口冻结 + 干净克隆可跑 |

---

## 执行顺序与依赖

```
0.0 决策清单（先定，别边做边改）
 │
0.2 环境 bootstrap ─────┐（后台先跑）
                       ├──► 0.3 PlantContext ──► 0.5 plant CLI ──► 0.6 负对照  [M1]
0.1 骨架 ──────────────┘        │
                                 ├──► 1.1 check / 1.3 eval / 1.4 tracking  [M2]
                                 │         （1.2 提取 swap_plant 在 1.3 前）
                                 ├──► 2.x train/export/parity/rehearse/record  [M3]
                                 └──► 3.x watch/dashboard/stage0 ──► 收尾  [M4][M5]
```

- **串行关键路径**：0.0 决策 → 0.2.1 vendor（本地资产落新项目根 `tools/`）→ 0.2 环境（含 plant apply + check）→ 0.3 → 0.5 → 0.6 → 1.x → 2.x → 3.x → 收尾。
- **可并行**：0.1 骨架、0.4 io/jobs 可与 0.2 下载并行；3.x 与 2.x 可部分并行。
- **不可并行的硬点**：0.2 的 `plant apply` 必须在任何 `train`/`eval` 之前完成；0.2 的冒烟必须在 plant check 通过之后才跑（否则验的是错的植物）。
- **0.2.1 必须在 0.2 的 `plant apply` 之前完成**：本地资产（`tools/bam_params/hd1910/*.json`、`tools/bam_actuators.py`）没就位，`apply` 会在 `_install_register` 处直接失败。

---

## 明确不做（每步都要复查）

- 不碰 `repo/` 旧栈、joy 侧线（只提取 `swap_plant` 函数）。
- 不合并 70+ 脚本进一个文件。
- 不改 `train` 调用语义（触发重训纪律）。
- 不做 GUI（第一版只埋接缝）。
- **不动正在跑的实验**：改动 `plant` / `microduck_constants.py` / `train` 相关文件前，先确认没有训练或评估在跑（当前这类改动会静默作废实验：日志正常、指纹是启动时拍的、不可发现）。
- **不承诺两任务物理隔离**（A 方案）：真正的隔离要走 0.3 的 B/C 后备，不由 `--task` 参数假装实现。
- **`check` 不默认 `--task both`**：P3 下 standup 期望是 m5，默认 `both` 会永远红，门禁就废了。`both` 只用于 CI / 发车前。
- **新工具不读旧 `out/`**（P5）：只写新 `out/`；要读历史产物必须显式 `--legacy-out` 并声明只读。

