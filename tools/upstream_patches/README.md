# upstream_patches — 把官方 `third_party/microduck_rl` 变成训练所用任务包

官方基线是 `pollen-robotics/microduck_rl@b02fdea`（develop，2026-10-12）。
本目录的工具把它补成**与 `artifacts/flat_walk/` 全部数字对应的任务包状态**。

## 一条命令

```bash
python tools/upstream_patches/replay_all.py --python .venv-mjlab/Scripts/python.exe
```

前置：submodule 已 checkout 在 `b02fdea`（脚本自检，不对就拒跑）：

```bash
git submodule update --init third_party/microduck_rl
git -C third_party/microduck_rl checkout b02fdea
```

## 验证结论（2026-10-26）

从干净 `b02fdea`（codeload tar.gz，254 个 blob 与官方 tree 逐 sha 相同）出发
重放整条链，与训练所用快照逐文件比 git blob sha1：

| 范围 | 结果 |
|---|---|
| **velocity 任务涉及的全部文件**（cfg / mdp / constants / 机器人 XML / 对称表 / `__init__`） | **逐字节一致** |
| joy 任务文件（`microduck_joy_env_cfg.py` 等） | 一致，**除下表 3 个工具的效果** |
| `mdp.py` / `microduck_joy_env_cfg.py` 的 joy 残差 | 见「已知缺口」 |

`replay_all.py` 末尾打印 velocity 关键文件的 sha1，与 `runmeta` 里记录的
`cfg_byte_identical_to_upstream` 哈希对得上即为复现成功。

## 工具清单与顺序

| 顺序 | 工具 | 作用 | 来源 |
|---|---|---|---|
| 1 | `apply_joy_patch.py` | 从 `rc_joy.patch`（裁剪自 ros-claw/microduck 的训练 patch，**第三方**，锚定旧 commit `5946fd9`）提取**纯新增行**：mdp 尾部 joy 函数、`__init__` 注册、新建 `microduck_joy_env_cfg.py` + `test_joy_cfg.py` | 本项目 |
| 2 | `patch_joy_plant_and_meta.py` | `constants.py` 的 `pd_actuators` PD 执行器 + `MICRODUCK_STANDUP_PD_ROBOT_CFG`（joy PD 任务用）；`export.py` 的 joy ONNX 元数据。块内容从训练快照**机械提取**，锚点唯一性有断言 | 本项目（反向重建） |
| 3-7 | `patch_joy_{action_rate,exploration,foot_sigma,gait_clock,phase_rsi}.py` | joy 任务迭代：动作速率表、探索噪声、落脚步宽容差、步态时钟进观测、时钟相位 RSI | 本项目 |
| 8 | `patch_joy_symmetry.py` | 左右镜像增广（需要 torch 的解释器） | 本项目 |
| — | `rc_joy.patch` | 15 KB 裁剪版输入 patch | **第三方**（ros-claw/microduck） |

所有补丁都是 **append-only 或带唯一锚点的插入**，幂等（重跑会跳过已应用的块），
锚点漂移时报错退出而不是静默错位。

## 已知缺口（如实声明）

`patch_joy_peak_linear.py` / `_peak_curriculum.py` / `_pair_min.py`（本目录里带但
`replay_all.py` 默认跳过）依赖 `tools/patch_joy_foot_peak.py`——**该工具已丢失**
（`mdp.py` 内的注释还引用着它）。这三个工具的效果（`joy_foot_peak` 类及其课程/
 payoff 改动）已在训练快照里，但重放链无法从官方基线重现它们；若要重训 joy 任务，
需要先重建丢失的工具。**velocity / 部署链完全不读这些代码**，flat-walk 的复现不受影响。

## 与训练环境的两个差异（不影响「文件逐字节一致」）

- 工具会把改动同步到 `.venv-mjlab/Lib/site-packages/`（`train.exe` 读的是安装副本）。
  `replay_all.py` 会现建这个骨架；只有要**跑训练**时才需要真装包（`uv sync`）。
- 工具用 text 模式写文件，Windows 下会把 LF 翻成 CRLF；`replay_all.py` 第 6 步
  统一归一回 LF（训练快照与官方 blob 都是 LF）。
