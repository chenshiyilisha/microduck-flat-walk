# xgoduck_rl 任务定义 与 整机质量口径 核对（2026-11-09）

_起因：`docs/active/microduck-开源参考索引-2026-11-09.md` 的行动建议 1「抄 xgoduck_rl 的 `roller_standup` + `sitstand`」与建议 5「核 737.1 g vs 744 g 口径」。两条都按「先查全、再判决」重做，结论：**两条建议的前提都不成立**。_
_方法：GitHub tree 的 git blob sha 做同源判定（不是看文件名）；质量用两份独立加总复算；所有数字可本机重跑。_

---

## Part A — 任务定义：代码不缺，行动建议 1 撤销

### A1. 本地训练包里全都已注册，且是我们训练链里在用的

`.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/__init__.py`（**实际训练 import 的包**）注册了 20+ 个任务，与本议题相关的：

| task id | 干什么 |
|---|---|
| `Mjlab-Velocity-Flat-MicroDuck` | 走路（P3 主任务） |
| `Mjlab-GroundPick-Flat-MicroDuck` | 嘴触地 |
| `Mjlab-StandUp-Flat-MicroDuck` | **跌倒后自己起来** |
| `Mjlab-SitStand-Flat-MicroDuck` | 坐 ↔ 站 |
| `Mjlab-RollerStandUp-Flat-MicroDuck` | 滚轮版起身 |

工具链也齐：`tools/hd1910/explore_standup.sh`、`resume_standup.sh`、`smoke_standup.sh`、`eval_standup.py`（`TASK = "Mjlab-StandUp-Flat-MicroDuck"`）、`explore_ground_pick.sh`。

🔴 **记忆里「P3 = walk / ground_pick / standup」说的是训练时选用的任务集合，不是「文件缺失」。** 真正管「跌倒后自己起来」的是 `standup`，P3 本来就有。

### A2. `roller_standup` 是带轮版，HD-1910 不适用

`microduck_roller_standup_env_cfg.py` 文件头自述：继承 `make_microduck_velocity_rollers_env_cfg`，**带四个被动轮**、轮子插进关节顺序导致索引重映射（`_LEG_JOINTS`）、有「滚动摩擦反向课程」（先锁轮后放开）。xgoduck 的 `xgoduck_roller_standup_env_cfg.py` 更直白：

> Current XgoDuck StandUp recipe on the latest four-passive-wheel skates. … The actor still controls 14 servos, never the four passive wheels.

⇒ HD-1910 无轮、关节顺序不同，**不可搬**。

### A3. `sitstand` 是坐↔站，不是跌倒起身

v1.5 文件头：posture command `sit_flag`（0=站 / 1=坐）、SIT/STAND 关键帧（SIT trunk z 0.060 / STAND 0.115）、双向「gentleness」限速、静止质量奖励。与「跌倒后起身」是两件事。

### A4. 与 xgoduck_rl 的同源判定（git blob sha）

用 `sha1("blob <len>\0" + bytes)` 对齐 GitHub tree 的 blob sha，逐文件比三份本地副本：

| 本地副本 | SAME | DIFF | LOCAL-ONLY |
|---|---|---|---|
| LIVE `.venv-mjlab/.../tasks/` | 7 | 11 | 3 |
| `.upstream/hd1910m/microduck_rl/.../tasks/` | 8 | 10 | 6 |
| 官方 `.upstream/microduck_rl-develop/.../tasks/` | 7 | 11 | 3 |

- `microduck_roller_standup_env_cfg.py`：LIVE 与 develop **字节完全一致**（SAME）⇒ 同一份上游，没有「新东西可抄」。
- `microduck_sitstand_env_cfg.py`：三份都 DIFF（版本演进）。
- xgoduck_rl 独有、本地没有的 10 个文件：`standup_training_rewards.py`、`standup_hip_home.py`、`kick_ground_contact.py`、`kick_hip_roll.py`、`startup_velocity_command.py`、`xgoduck_physics.py`、`xgoduck_roller_standup_env_cfg.py`、`xgoduck_tricks_env_cfg.py`、`xgoduck_velocity_swizzle_env_cfg.py`、`xgoduck_walk_rewards.py`。
- 结果里同时出现 SAME 与 DIFF ⇒ 判定不是「恒等」也不是「全不同」，比对有效。

### A5. xgoduck 自己的训练链也是三阶段、不共享 checkpoint

`scripts/train_xgoduck_pick_standup_velocity.sh`：

```
Mjlab-GroundPick-*-XgoDuck → Mjlab-StandUp-*-XgoDuck → Mjlab-Velocity-*-XgoDuck
```

文件头第一句：**"The three tasks do not share checkpoints — each stage starts from scratch."** 与我们做法一致，没有可搬的「配方结构」。

### A6. 判决与剩下的可执行项

🔴 **撤销行动建议 1**。四条理由：代码不缺 / `roller_standup` 硬件不适用 / `sitstand` 目标不对 / 跌倒起身 `standup` 本就在 P3。

若将来仍要借 xgoduck 的东西，只剩两项，且都是**对照**而非「搬」：

1. `standup_training_rewards.py` 的 `upright_linear_angle_gate()` —— 直接读 free-joint 四元数算倾角门控，文件头说明是为了**避开 projected gravity 滞后一个物理子步**。可对照我们 `standup` 的 tilt gating 有没有同样的滞后。
2. `backlash.py` 对照我们齿隙设定（≤0.5°）—— 原建议 2，仍有效。

⚠️ 两条都不要直接改冻结的 P3：`hd1910_kp8` 部署档已冻结，且记忆准则「换 plant / 换任务必须重训」。

---

## Part B — 整机质量：两份不同 MJCF，不是「待核的 7 g」

### B1. 两个数字的一手出处

| 数字 | 出处 | 是什么 |
|---|---|---|
| **744.36 g** | `.upstream/replica/software/studio/web/model/model.json`，`notes` 明写「**质量 744 g 来自官方 `robot_walk.xml`，重心按它算**」；`source` = `apirrone/microduck_rl robot_allcollisions.xml` | 官方 MJCF 逐刚体质量。把 16 个 body 的 `mass` 加总 = **0.744361 kg** |
| **737.1 g** | `.upstream/replica/docs/HD-1910训练前数据清单.md` §2「【MJCF】XL330 版仿真值」 | 逐刚体加总。复算 `199.2 + 23.0×2 + 6.2×2 + (48.2+21.6+30.0)×2 + 279.9 = 737.1`，**精确命中** |
| 737.2 g | `执行器选型.md:258`、`docs/reference/microduck-社区参考2026-10.md` §8.7（用 `repo/microduck/robot_walk.xml` 由 MuJoCo 直接算） | 与 737.1 同一量，0.1 g 舍入 |

⇒ **两个都是仿真 MJCF 质量，都不是真机称重。** `社区参考2026-10.md:459` 把 744 g 写成「真机记录」，措辞不准。

### B2. 逐刚体对照：净差是几十克级重新分配互相抵消

| body | 744 版 (g) | 737 版 (g) | 差 |
|---|---|---|---|
| `trunk_base` | 264.38 | 199.2 | **+65.18** |
| `yaw2roll`(+`bearing_roll`) ×2 | 47.02 | 46.0 | +1.02 |
| `hip_l` ×2 | 10.42 | 12.4 | −1.98 |
| `upper_leg` ×2 | 86.30 | 96.4 | −10.10 |
| `leg` ×2 | 43.16 | 43.2 | −0.04 |
| `ankle` ×2 | 52.94 | 60.0 | −7.06 |
| `neck` + `neck_pitch` | 42.56 | 42.5 | +0.06 |
| `yaw_roll_motion` | 24.92 | 48.6 | **−23.68** |
| `jaw_soft` | 172.65 | 188.8 | **−16.15** |
| `jaw_hinge` | 0.00 | — | 0 |
| **合计** | **744.36** | **737.1** | **+7.26** |

🔴 `社区参考2026-10.md:459` 那句「**差 6.8 g，正好是 ToF + 摄像头 + 螺丝**」**无一手佐证，且与一手资料冲突**：fanhao 清单里 `jaw_soft` 自注「含头壳、**摄像头**、HAT 那颗 BMI088」——摄像头已经算在 737 g 里，不能再拿去解释差额。**该解释作废**。

### B3. 电池口径（唯一仍不确定的，标为推断）

- fanhao 清单明写：「电池 NP-F550 *待称*（典型 ~100 g；**是否已含在 `trunk_base` 里待核**）」。
- 744 版 `model.json` 的 `trunk_base` geoms 里**有 `np_f970` 电池 mesh**，且它的 `trunk_base` 比 737 版重 65.18 g。
- ⇒ 倾向「744 版把电池质量并进 `trunk_base`、737 版没有」，但 65 g ≠ 典型 100 g，**没有一手称重证据，这是推断**。

### B4. 对项目的实际影响

- 两份都是 **XL330 版** MJCF；HD-1910 实机不同（单只舵机 18→21 g，15 颗约 +45 g），fanhao 自己就标了「换飞特四处不同」。
- ⇒ **不要拿 737/744 去核 HD-1910 真机，也不要据此改训练 plant**。真要核，应核 `hd1910_kp8` plant 实际加载的 MJCF 总质量。
- 行动建议 5 由「待核口径」改判为：**已判定是两份不同 MJCF 的仿真质量；差额小零件解释作废；电池是否含入仍无实称**。

---

## 附带更正（已同步到原文）

- `docs/active/microduck-开源参考索引-2026-11-09.md`：§A1 的「差 7 g 待核口径」→ 已判决；行动建议 1 → 撤销；行动建议 5 → 已闭环。
- `docs/reference/microduck-社区参考2026-10.md` §8.7：加订正批注（744 g 非真机称重 / 6.8 g 解释作废）。

## 方法与负对照

- 同源判定用 git blob sha 而不是肉眼/文件名，避免「同名即同源」误判；结果同时含 SAME 与 DIFF，不是恒等函数。
- 质量用两条独立算法：① `model.json` 逐 body 加总 → 744.36 g；② fanhao 表格逐项加总 → 737.1 g。两者各自自洽，差异落在**逐 body 分布**上，故不是舍入或单位错误。
- 「两个来源互相矛盾」是这次的抓手：一句「差 6.8 g = 几个小零件」与一组「trunk_base 差 65 g、头颈差 −40 g」不可能同时成立 ⇒ 错的是那句解释，不是读数。
