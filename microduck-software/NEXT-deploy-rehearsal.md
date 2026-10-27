# 明天执行：部署彩排（headless deployment rehearsal）

_准备于 2026-10-25 晚。工具已写好并干跑通过，明天只跑数据、写结论文档。_

> **本文件已并入上游仓库** `docs/05-flat-walk.md` **§14**（commit `35b28b3` / `d75c8a9`，
> PR #2），工具在 `tools/flat_walk/rehearse_deploy.py`。**唯一真相在仓库里**——这里只作
> 本地执行清单，两边不一致时以仓库为准。明天产出的 JSON 入库后，§14.4 那张「工具自检期
> 读数」表要换成正式读数。

---

## 0. 一句话目标

把 `walk_std004_1250.onnx` 过一遍**上游自己的部署栈**（BAM M6 + XL330 电压模型 + 50 Hz 控制环），
回答一个二元问题：**这个图在部署执行器上还站得住吗**。

**不是**为了产出可与训练评估横比的性能数字（理由见 §3）。

---

## 1. 命令（可直接复制）

```bash
cd /e/WorkBuddy/2026-10-23-08-26-15/microduck-software

# 主表：六条件 × 8 秒（约 2 分钟）
MUJOCO_GL=glfw .venv-mjlab/Scripts/python.exe tools/rehearse_deploy.py \
  --onnx out/walk_std004_1250.onnx \
  --cmd-vx 0.4 --seconds 8 --sweep --track-action \
  --out out/rehearse_1250_sweep.json

# 负对照：同一图、同一命令，换回 XML 位置伺服。
# 它回答的是"同一策略换一套被控对象会怎样"；"BAM 有没有接上"由 P3 的 ctrl 探针回答，
# 不再靠这条的 vx 差异（只差 10%，判不出来）。
MUJOCO_GL=glfw .venv-mjlab/Scripts/python.exe tools/rehearse_deploy.py \
  --onnx out/walk_std004_1250.onnx \
  --cmd-vx 0.4 --seconds 8 --condition nominal --no-bam \
  --out out/rehearse_1250_nobam.json

# 低速：部署下限 0.15 是否也成立（补 §11 的死区）
# 注意 0.0 **不是**低速点：上游 AGENTS.md:265-269 明说 "feeding all-zeros means stand"，
# cmd=0 是一个特殊的 posture 语义，不是"走得很慢"。真正的死区边界在 0.12 / 0.15。
# ⚠️ 每档必须扫 yaw：单机固定初态只等于一个样本，双稳态会被它掩盖（见 §3.6 的实测）。
for c in 0.12 0.15 0.20; do
  for y in 0 45 90 135 180; do
    MUJOCO_GL=glfw .venv-mjlab/Scripts/python.exe tools/rehearse_deploy.py \
      --onnx out/walk_std004_1250.onnx --cmd-vx $c --seconds 8 --condition nominal \
      --yaw-deg $y --out out/rehearse_1250_cmd${c}_yaw${y}.json
  done
done

# 零指令（= stand 语义）单独跑，单独解读，不与上面三点并列
MUJOCO_GL=glfw .venv-mjlab/Scripts/python.exe tools/rehearse_deploy.py \
  --onnx out/walk_std004_1250.onnx --cmd-vx 0.0 --seconds 8 --condition nominal \
  --out out/rehearse_1250_cmd0_standslot.json
```

六条件 = `nominal` / `low_batt`(6.5 V, sag 0.2) / `high_batt`(8.2 V, sag 0) /
`train_lag3` / `train_lag4` / `train_lag6`（后三个是训练同款执行器延迟）。

---

## 2. 事先固定的判据

| 判据 | 通过条件 | 含义 |
|---|---|---|
| **P1 站得住** | `nominal` 与 `high_batt` 都 `fell=n` 且 `dx > 2.0 m` | 部署栈能工作 |
| **P2 电压下限** | `low_batt` 的结论要如实记录（摔 or 不摔） | 决定部署时 vin 下限 |
| **P3 执行器路径** | `ctrl_path.max_abs_ctrl_minus_target`：BAM **> 1e-3**、`--no-bam` **< 1e-9** | 证明 BAM 真的在控制路径上 |
| **P4 形状** | `obs_dim == 61`、`nu == 14`、执行器顺序 == `DEFAULT_POSE` 顺序 | 已在准备阶段验过，明天复核 |
| **P5 延迟维度** | **不作结论，只记录** | 见 §3 第 3 条：彩排的延迟路径未与训练对齐 |
| **P6 覆盖窗口** | `window.valid_s >= 0.75 × seconds` | 摔了的跑窗口不足，数字不可引用 |
| **P7 低速维度** | **不作结论，只记录** | 见 §3.6：单机在低速只给一个样本，且方向与 0.4 相反 |

判据必须今晚定死，明天不许改口径。

**P3 为什么改了（这是今晚最重要的一处修正）**：原来的 P3 是"`--no-bam` 与 `--bam` 的 vx/tilt
**明显不同**"。实测 BAM 0.4626 / 9.1° vs no-BAM 0.4145 / 5.9°——**vx 只差 10%，落在条件之间的
散布里**，既没有阈值，也不能"为了正确的理由失败"。换成量纲判据：

```python
# infer_policy.PolicyInference.set_position_targets
if self.bam_ctrl is not None:
    self.bam_ctrl.q_target[:] = target_positions   # BAM: update() 写的是力矩
else:
    self.data.ctrl[:] = target_positions           # legacy: ctrl 逐位就是目标角
```

⇒ `max|data.ctrl − (default_pose + action×scale)|` 是天然的二值量。实测
**BAM = 0.407，no-BAM = 0.000e+00**，阈值取 1e-3 有 400 倍裕度。

`--no-bam` 的 vx/tilt 差异不再当判据，但**照旧记录**——它回答的是另一个问题
（"同一策略换一套被控对象会怎样"），不是"BAM 接上没有"。

---

## 3. 三个已知的"不可比"，必须写进结论

### ① 官方只说这是 rehearsal，没说数字可比

`microduck_rl/AGENTS.md:21`：

> `uv run scripts/infer_policy.py --walking out.onnx`  # CPU MuJoCo **deployment rehearsal**
> (BAM M6 actuators as in training; `--no-bam` = XML PD)

`AGENTS.md:265-269` 说明它的用途是：

> Real deployments hot-swap ONNX policies (walk / stand / trick) with a shared obs contract —
> **rehearse in `scripts/infer_policy.py` before touching the robot**, with the correct
> command-slot writes (a posture flag lives in the twist vx slot; feeding all-zeros means
> "stand", which looks like "policy ignores the button").

⇒ 资料把它定位成**接口与命令槽的验证**，不是性能测量。

### ② 执行器模型一致是有测试锁着的，性能一致没有

`tests/test_infer_policy_bam.py` 的 docstring：

> infer_policy.py drives the CPU MuJoCo rehearsal with the SAME BAM M6 actuator the policies
> are trained against in warp … These tests **lock the two halves together**.

它逐项断言（`test_cpu_bam_constants_mirror_training_cfg` / `test_actuators_converted_like_warp`）：

- `BAM_MOTOR_NAME == k["motor_name"]`、`BAM_MODEL == k["model"]`、`BAM_KP_FW == k["kp_fw"]`
- `BAM_VIN_RANGE == k["vin_range"]`、`BAM_VIN_DROP_GAIN_RANGE == k["vin_drop_gain_range"]`、`BAM_VIN_MIN == k["vin_min"]`
- `BAM_MAX_CURRENT == k.get("max_current")`，且 `assert bam_model.actuator.max_current is None  # training has no current limiter`
- 装配层面：`forcerange == 7.4·kt/R`、`dof_armature == get_extra_inertia()`、
  `dof_solref/solimp == BAM_STIFF_*`、`ctrl` 就是力矩、`dof_frictionloss > 0` 每步重写

**但它一个字都没断言轨迹/速度/是否摔倒。** 一致的只是执行器，不是动力学数值。

### ③ 训练有 3–6 步执行器延迟，彩排默认没有

`mjlab_microduck/robot/microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`：

```python
delay_min_lag=3,
delay_max_lag=6,      # 50 Hz -> 60-120 ms
```

而 `infer_policy.py` 的 `--delay` 默认是 `None`（关闭），
`tests/test_infer_policy_bam.py` 也**没有**把 delay 纳入断言。
延迟在 mjlab 里作用于 `cmd.position_target`（`mjlab/actuator/actuator.py` 的 `apply_delay`），
与 `infer_policy.apply_action` 延迟 `target_positions` 是同一层，语义一致。

**准备阶段的实测**（8 秒，cmd 0.4，单机）：

| 条件 | vx | ratio | 首次摔倒 |
|---|---|---|---|
| 无延迟 `nominal` | 0.463 | 1.16 | 不摔 |
| `train_lag3` | 0.053 | 0.13 | **1.86 s** |
| `train_lag4` | −0.018 | — | **1.32 s** |
| `train_lag6` | −0.012 | — | **0.82 s** |

延迟越大摔得越早，**单调**。但训练侧在同样 3–6 lag 下几乎不摔（评估终止率 0–7.3%）。
⇒ **彩排的延迟路径与训练不是同一件事**（最可能是 `last_action` 观测在延迟下与训练语义不同，
训练时策略看到的是延迟后的自身动作，彩排记录的是延迟前的）。
⇒ 延迟这一维在彩排里**不可作结论**，只记录为工具缺口。

---

## 3.5 摔倒的跑怎么读（今晚实测出来的两个坑，都已修进脚本）

### 坑一：原来的脚本摔倒后继续跑，把"躺在地上"算进了速度

训练侧的终止条件是四条（`cfg.terminations`）：

```
time_out               time_out=True
fell_over              time_out=False   func=bad_orientation   limit_angle=1.2217 rad
out_of_terrain_bounds  time_out=True
nan_state              time_out=False
```

也就是**训练时一摔倒 episode 立刻结束并 reset**，倒地状态永远进不了它的统计。
而彩排脚本原来只在 NaN 时 break ⇒ `low_batt` 在 2.64 s 摔倒，之后 5.4 s 继续躺在地上跑，
全部计入 8 秒均值，报出 `vx=0.4627 / ratio 1.157`，和没摔倒的 `nominal`（0.4626）几乎一样。
**两个数不可能同时成立**，这就是它的破绽。

修法：`TRUNCATE_AT_FALL = True`，摔倒那一步即 break，且触发样本不计入。

### 坑二：截断之后，摔倒跑的均速仍然系统性偏高（存活偏差）

截断后 `low_batt` 的 vx 变成 **0.5389**，比没摔倒的 `nominal`（0.4632）**还高**。
因为剩下的窗口恰好是它跑得最好的那一段——活下来的时间越短，均值越乐观。

⇒ 结论：**摔倒的跑，vx 一个数都不能引用**。脚本现在直接输出 `vx=n/a(fell)`，
JSON 里 `speed.comparable=false` 并附原因。表里只允许出现 `fell_at_s`。

### 判据对齐：60° → 70°

原脚本 `FALL_TILT_DEG = 60.0` 是拍的，训练是 `limit_angle = 1.2217304763960306 rad = 70.0000°`。
两者实现是同一个量（`degrees(acos(-projected_gravity_z))`），所以阈值直接照抄。改后实测：

| 条件 | `tilt_at_fall` | `valid_s` | 摔倒前最后一步 `max_tilt` |
|---|---|---|---|
| `low_batt` | 71.87° | 2.64 s | 67.0° |
| `train_lag3` | 81.54° | 1.88 s | 66.2° |
| `train_lag4` | 72.26° | 1.36 s | 66.4° |
| `train_lag6` | 73.32° | 0.84 s | 65.8° |

注意最后一列：**触发摔倒的那一步没有进 `tilt_hist`**，所以只报 `max_tilt_deg` 会显示
66–67°，看起来像"判据没到就判摔了"。为此新增 `window.tilt_at_fall_deg` 记录触发值。
这也是"派生量要单独验一遍"的一个实例——`max` 和"触发值"不是同一个东西。

---

## 3.6 坑三：单机在低速区只给一个样本，而这件事本身就是结论

`cmd=0.15` 扫 5 个初始朝向（yaw 0/45/90/135/180），**五个全部站着不动**：

| yaw | vx | dx | max tilt |
|---|---|---|---|
| 0° | −0.0000 | +0.008 m | 3.3° |
| 45° | −0.0000 | +0.006 m | 3.3° |
| 90° | −0.0000 | +0.000 m | 3.3° |
| 135° | −0.0000 | −0.006 m | 3.3° |
| 180° | −0.0000 | −0.008 m | 3.3° |

而 32-env 评估侧同一 ckpt、同一 `cmd=0.15` 是 **ratio 0.533、`frac站` 0.06**。
**这两组数不能同时成立**——不是"抽到了站的这一支"，是彩排在低速稳定收敛到"站"。

与 `cmd=0.4` 的方向**相反**（彩排 0.463 vs 评估 0.312，彩排快 49%），所以这不是整体标定
偏移，而是**低速区的行为不同**。最可能的解释：彩排是单机、确定性初态、无摩擦随机化、
无延迟；训练/评估侧 32 台带 3–6 lag 与摩擦 DR，扰动会把一部分 env 推过死区边界。
这与 §11 「死区是行为选择、不是噪声」的结论一致。

⇒ **明天低速段只作定性记录，不作结论**。它能回答"0.15 在单机上站不站得住"，
**不能**回答"部署下限是多少"。后者只有 32-env 扫描能答（已有的答案是 0.15 m/s）。

另外发现 `moves_forward` 闸门在低速是**假 FAIL**：`cmd=0.12/0.15` 的 `dx≈0` 是策略的正確
行为，不是 obs 布局坏了。已改成 `cmd < 0.2` 时该闸门记 `not_applicable` 而不计失败。

---

## 4. 明天预期会看到的"矛盾"（先写下来，免得误读）

**无延迟彩排 vx ≈ 0.46，而 32-env 评估是 0.312。差 49%。**

这不是 bug，是**两个仪器**：

| | 彩排 | 评估 |
|---|---|---|
| 机器人 | 1 台，初态确定（yaw=0） | 32 台，`reset_base` yaw ∈ (−π, π) |
| 执行器延迟 | 0（默认） | 3–6 步 |
| 求解器 | CPU Newton/implicitfast，100/50 | warp/MJX，训练时 100/50 |
| 碰撞 | XML 的 `self_collision_only` | `collisions=(FULL_COLLISION,)` |
| 摩擦 | 固定 XML 值 | `FrictionDRBamActuatorCfg` 每 env 随机 |
| 统计窗 | 后 75% 控制步，**且截止到摔倒** | 全 8 秒；摔倒则 episode 终止后 reset 继续 |

**结论只能在同一仪器内部做纵向比较**（BAM vs no-BAM、高压 vs 低压），
不能与 §10/§12 的 0.312 / 0.1592 放同一张表。这条与 `docs/05-flat-walk.md` §12.5
的"跨版本评估脚本不可混用"是同一条纪律的延伸。

---

## 5. 准备阶段已经验掉的事（明天不用重做）

- `nu == 14`，执行器顺序逐项 == `DEFAULT_POSE` 顺序（left_hip_yaw … right_ankle）
- BAM M6 / xl330 可加载：`kt=0.3660 R=2.8114`，`forcerange ±0.963 Nm`，`armature 1.81e-03`
- obs 布局指纹正确（静止站姿 + cmd 0.4）：
  `[0:3]=0`、`[3:6]=[0,0,-1]`、`[6:20]=0`、`[20:34]=0`、`[34:48]=0`、
  `[48:51]=[0.4,0,0]`、`[51:55]=0`、`[55:61]=0` ⇒ 与训练 cfg 的 8 个 term
  （3+3+14+14+14+3+4+6=61）逐段吻合
- `scene.xml`(groundcontact) 与 `scene_walk.xml`(walk) 结果**逐位相同** ⇒ 多出的 6 个碰撞体不参与接地接触
- 求解器：训练显式传 `iterations=100 ls_iterations=50`，正好等于 MuJoCo 编译默认 ⇒ 这一维不存在差异
- `episode_length_s = 20 s` ⇒ 8 秒内不会 reset（排除"reset 拖低均值"这个假说）
- `USE_PROJECTED_GRAVITY = True` ⇒ 彩排**不要**加 `--raw-accelerometer`
- `cfg.actions["joint_pos"].scale = 1.0` ⇒ 彩排 `--action-scale 1.0` 是对的（默认值）
- **摔倒判据已对齐训练**：`FALL_TILT_DEG` 60 → **70**（= `fell_over` 的 `limit_angle`
  1.2217304763960306 rad）；高度不再触发摔倒
- **P3 的 ctrl 探针已实测**：BAM `max|ctrl−target|` = **0.407**、no-BAM = **0.000e+00**
- **摔倒后截断已实装**：`TRUNCATE_AT_FALL=True`，`low_batt` 从"跑到 8 s 报 0.4627"
  变成"valid=2.64 s、vx=n/a"

---

## 6. 跑完之后做什么

1. 把六条件表 + 负对照表写进 `docs/05-flat-walk.md` **§14**，标题明确写
   "部署彩排：执行器栈能工作，数字不可与评估横比"。
   **必须同时写进 §3.5 的两个坑**（摔倒后继续跑 → 假装 0.4627；截断后存活偏差 → 0.5389
   反而比没摔的高），否则下一个读表的人一定会把 `low_batt` 那行当成"低电压更好"。
2. `rehearse_deploy.py` 复制进 `tools/flat_walk/`，README 里补一句它和
   `check_onnx_parity.py` 的分工：parity 查**图 == 数学**，彩排查**栈是否会活着**。
3. 产物入 `artifacts/flat_walk/evals/`：`rehearse_1250_sweep.json`、
   `rehearse_1250_nobam.json`、`rehearse_1250_cmd{12,15,20}.json`、`rehearse_1250_cmd0_standslot.json`。
4. `.gitignore` 逐项放行（沿用 §13 的写法，`*.json` 在 evals 下被忽略）。
5. 提交进 PR #2，**Merge 仍要用户点**。

---

## 7. 时间预算

| 步骤 | 时长 |
|---|---|
| 六条件 sweep × 8 s | ~2 min |
| 负对照 | ~20 s |
| 低速 3 档 × 5 个 yaw + 零指令（16 跑） | ~1 min |
| 写 §14 + README + 复制入库 | ~20 min |
| 提交推送 + 确认 PR | ~5 min |

**总计不到 30 分钟**，其中真正跑仿真不到 4 分钟。
