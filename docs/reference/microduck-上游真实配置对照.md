# 上游真实配置对照（来自 kissqy 发布的 resolved task config）

## 这份东西是什么

`kissqy/Microduck-kissqy` 的 `docs/training/data/task-configs/` 下，每个任务一个 JSON，
`Mjlab-Velocity-Flat-MicroDuck.json` 有 **1.2 MB**。它不是配置文件，是**运行后导出的完整解**：

- `inspection.full.env` —— env 的全部 18 个字段，含 `events`（域随机化的实际范围）、
  `terminations`、`commands`、`sim`
- `inspection.model` —— 编译后模型的总质量、15 个 body、15 个 joint、齿轮齿隙、碰撞 geom
- `configuration_audit` —— 时序、观测项、关节映射（order / home / limits）、nu
- 顶层 —— PPO 超参、奖励权重、`source_revision`（= 生成它的上游 commit）

**这是我们第一次拿到"解得开的完整配置"，而不是靠读代码反推。** 之前每一轮我都在
`microduck_velocity_env_cfg.py` 里逐行找常量，现在可以直接对表。

`source_revision: 8d0db749…`，`reviewed_on: 2026-10-03`，`configuration_audit.passed: true`。

---

## A. 奖励：16 项，我们 14 项对上，2 项做不了

| 项 | 上游权重 | 我们 | 判定 |
|---|---|---|---|
| `track_linear_velocity` | 2.0 | 2.0 | ✅ |
| `track_angular_velocity` | 2.0 | 2.0 | ✅ |
| `upright` | 2.0 | 2.0 | ✅（去 0.5 之后） |
| `pose` | 1.0 | 1.0 | ✅ |
| `body_ang_vel` | −0.05 | −0.05 | ✅ |
| `dof_pos_limits` | −1.0 | −1.0 | ✅（曾误零） |
| `action_rate_l2` | −0.1 | −0.1→−1.0 课程 | ✅ |
| `air_time` | 3.0 | 3.0 | ✅ |
| `foot_clearance` | −2.0 | −2.0 | ✅ |
| `foot_swing_height` | −0.25 | −0.25 | ✅（后补） |
| `foot_slip` | −0.1 | −0.1 | ✅（后补） |
| `head_pose_tracking` | 2.0 | 2.0 | ✅（后拆出） |
| `body_pose_tracking` | 0.0 | 0.0 | ✅ |
| `head_pose_bias` | 0.0 | 0.0→负值课程 | ✅ |
| **`angular_momentum`** | **−0.02** | — | ❌ 需要全身角动量，我们没这个量 |
| **`self_collisions`** | **−1.0** | — | ❌ 需要碰撞过滤传感器 |

→ **奖励侧这条线到此可以结案**：12 个非零项逐项相等，剩下 2 项是缺传感器，不是写错。

## B. 物理与求解器：3 处不一致，其中 2 处该改

| | 上游 | 我们（`plant.build()` 默认） | 影响 |
|---|---|---|---|
| 物理步长 | **0.005 s** | 0.002 s | 我们细 2.5 倍，慢 2.5 倍 |
| decimation | 4 | 10 | 控制都是 50 Hz ✅ |
| **积分器** | **`implicitfast`** | **`Euler`** | 关键差异 |
| 求解器 | newton | newton ✅ | |
| iterations / ls | **10 / 20** | 100 / 50 | 我们 5–10 倍求解开销 |
| cone / impratio | pyramidal / 1.0 | pyramidal / 1.0 ✅ | |
| 终止角 | 1.2217 rad = **70.0°** | 70° ✅ | |

**积分器这条是最值得改的。** 上游能在 5 ms 步长下稳定，靠的就是 `implicitfast`
（对阻尼/armature 做隐式处理）；我们用 Euler 就必须把 dt 压到 2 ms 才不炸。
改成 `implicitfast` + 5 ms + (10,20) 之后，理论上既更接近上游，又快约 2.5 倍。
**这条还没验证**，属于下一步要测的（见文末）。

## C. 网络与 PPO：容量差 8 倍

| | 上游 | 我们 |
|---|---|---|
| Actor | **512 → 256 → 128**，ELU | 128 → 128，ELU |
| Critic | 512 → 256 → 128 | 128 → 128 |
| 参数量（估） | ≈ 195 k | ≈ 24 k |
| lr | 1e-3 | 1e-3 → 5e-4（1000 iter 线性） |
| gamma / lambda | 0.99 / — | 0.99 / 0.95 |
| clip | 0.2 | 0.2 ✅ |
| **entropy** | **0.01** | **0.005** |
| steps_per_env | 24 | 24 ✅ |
| episode | 20 s | 20 s ✅ |

**容量差 8 倍这件事以前完全没被纳入考虑。** 我们从 `deploy61.pt` 一路 warm start，
每一代都是 128 宽。所有"走不直"的讨论都默认"网络够用，是奖励/控制律的问题"，
而这个文件第一次给出了反证的可能性。
⚠️ 换宽度意味着**现有 checkpoint 全部不能 warm start**（形状不匹配），
所以这是一次"要不要推倒重来"的决定，不是顺手改的。

## D. 域随机化：11 项实测范围（此前我猜的 ±5% 是错的）

| 事件 | 模式 | 实际范围 |
|---|---|---|
| `randomize_mass_inertia` | startup | alpha **−0.02565 ~ +0.02440**（≈ ±2.5%，**不是 ±5%**） |
| `randomize_com` | reset | ±0.003 m |
| `randomize_head_com` | reset | ±0.003 m |
| `base_com` | startup | ±0.025 / ±0.025 / ±0.030 m |
| `randomize_joint_friction` | reset | scale 0.9 – 1.1 |
| `randomize_armature` | reset | 0.9 – 1.1 |
| `foot_friction` | startup | 0.7 – 1.3 |
| `encoder_bias` | startup | **±0.015 rad（±0.86°）** |
| `push_robot` | interval | ±0.3 m/s（x、y） |
| `reset_base` | reset | x/y ±0.5 m，z 0.12–0.13，yaw ±π |
| `reset_robot_joints` | reset | 位置/速度都 0 |

这 11 项可以直接照抄进我们的 `plant_dr`——之前关着是因为不知道范围。

## E. 命令采样

```
heading_command: true            heading_control_stiffness: 0.5
rel_heading_envs: 0.0            （所以实际上没启用，和之前判断一致）
rel_standing_envs: 0.02
rel_forward_envs: 0.2            ← 我们没有这一项
rel_turn_in_place_envs: 0.15
resampling_time_range: [3.0, 8.0] s
ranges: lin_x ±0.4, lin_y ±0.3, ang_z ±1.0, heading ±π
```

`rel_forward_envs = 0.2` 是**我们漏掉的一条**：20% 的环境专抽纯前进指令。
它的作用是把"走直线"变成一个独立的训练目标，而不是总在混合指令里顺带学。
这可能和"走不直"直接相关——**而且是奖励无关、纯采样侧的一条**。

## F. 观测噪声（再次确认）

`base_ang_vel ±0.03 / projected_gravity ±0.01 / joint_pos ±0.001 / joint_vel ±0.25`，
全部均匀，`enable_corruption` 见 `inspection`。与我们改后的一致 ✅。
观测项 8 个：`base_ang_vel, projected_gravity, joint_pos, joint_vel, actions,
command, head_command, body_command` —— 无 `base_lin_vel` ✅。

---

## 结论：这条链接的价值

不是"又一个复刻项目"，而是**唯一公开了可解配置的项目**。它把我们的工作从
"照代码抄常量"升级成"对配置查差异"，并且一次查出三件此前不可能发现的事：

1. **积分器/步长/迭代次数三处不一致** → 可能白花 2.5 倍算力
2. **网络容量差 8 倍** → 所有"走不直"的归因都少考虑了一个变量
3. **`rel_forward_envs = 0.2` 漏了** → 采样侧就少了一种纯直线样本
4. 顺带纠正：质量随机化是 ±2.5% 不是 ±5%

⚠️ **许可**：`microduck-hd1910/LICENSE` 是 MIT，但**根目录没有 LICENSE**，
模型沿用官方 CC BY-SA-NC（非商业）。引用其配置做技术对照没问题，
**照抄进产品要注意非商业条款**。

## 待测（不算结论）

- [ ] `plant` 改 `implicitfast` + dt 0.005 + (10,20)：吞吐应该 ≈2.5×，且策略行为要重新验
- [ ] `rel_forward_envs 0.2` 加进 `resample()`，与 yaw_drift 做二因素对照
- [ ] 网络 128 → 512/256/128：需放弃现有 checkpoint 的 warm start
