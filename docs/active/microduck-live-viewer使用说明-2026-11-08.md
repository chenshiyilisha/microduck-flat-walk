# MicroDuck HD-1910 真机 3D 姿态查看器 · 使用说明

> 配套工具：`microduck-software/tools/hd1910/live_viewer.py`
> 上游对照依据：`docs/active/microduck-upstream-对照-2026-11-08.md` §4（可视化契约）

## 1. 它做什么

把真机实时上报的关节姿态画成一只可旋转的 3D 鸭子骨架，用于**不上真机也能肉眼核对
`robotd` 有没有在动、各关节角度/目标是否对、跟踪误差多大**。姿态数据来自真机的
`robotctl monitor --json`（服务端默认降采样 10 Hz），其 `RobotState.joints` / `targets`
是裸角度数组，索引按 `JOINT_NAMES`（见 §5）。

## 2. 依赖

- **零重依赖即可跑**：FK 用纯 Python 四元数/矩阵；`--renderer headless` 只打印数值。
- 想要图形：装 `matplotlib`（`pip install matplotlib`）得本地 3D 折线图；
  装 `viser`（`pip install viser`）得浏览器里可旋转/缩放的实时画面（`--renderer auto`
  会优先 viser，其次 matplotlib，最后 headless）。

## 3. 用法

```bash
# A. 最贴近生产：从真机经 ssh 拉流（robotd 经 WebRTC relay 的 mediad 同链路）
ssh robot_host 'robotctl monitor --json' | python live_viewer.py --source stdin

# B. 本机无真机：看静止站姿（演示 FK，不需要任何依赖）
python live_viewer.py --demo

# C. 切换渲染后端
python live_viewer.py --demo --renderer matplotlib     # 本地 3D 折线
python live_viewer.py --demo --renderer viser          # 浏览器 3D（默认端口 8012）
python live_viewer.py --demo --renderer headless       # 只打印数值

# D. 实时帧（等价写法）
robotctl monitor --json | python live_viewer.py --source stdin --renderer viser
```

- `--interval-ms`：matplotlib/viser 的刷新间隔（默认 100）。
- `Ctrl-C` 退出。

## 4. 它显示什么

- **headless**：逐帧打印每个关节的 `j`（实测角）、`tgt`（目标角）、`err`（跟踪误差），
  以及 `max_track_err`。一眼看谁没跟上。
- **matplotlib/viser**：按真实连杆树画关节原点连线（盆骨→髋→膝→踝→脚尖，颈/头/嘴同理）。
  若某关节 `targets` 与 `joints` 相差 >1e-3，会叠加一条虚线表示目标姿态。
- `velocities` / `currents_ma` 若真机上报则随帧携带，目前仅 headless 打印原始数组；
  空数组表示「该帧未上报」，查看器**绝不将其当作 0**。

## 5. 数据契约（务必对齐）

`JOINT_NAMES`（左腿优先，15 个，下标 = `joints[]` 数组下标）：

```
0 left_hip_yaw   1 left_hip_roll   2 left_hip_pitch   3 left_knee   4 left_ankle
5 neck_pitch     6 head_pitch      7 head_yaw        8 head_roll   9 mouth
10 right_hip_yaw 11 right_hip_roll 12 right_hip_pitch 13 right_knee 14 right_ankle
```

与 `ft1910/duck-ipc-proto/src/lib.rs:536` 完全一致。机器人 ID 体系仍是我们自己的
「1–15 物理 ID + 左腿优先名序」（见对照文档 §1），**不混入官方 10–14/20–24/30–34**。

## 6. 几何从哪来（可追溯）

连杆树、各体相对平移/旋转、关节轴**全部烘焙自 ft1910 的 MJCF**
`.upstream/ft1910/kinematics/assets/alpha/robot_walk.xml`（逐体 `pos`/`quat` 与
`joint axis="0 0 1"`，见该文件 6–108 行）。FK 严格按 MuJoCo 帧组合实现：

```
frame_child = frame_parent · R(axis, q) · Translate(pos) · R(quat)
```

坐标约定 MJCF 本就是 **Z 向上 / X 向前 / Y 向左**，与查看器一致，无需轴交换。
**已做正确性验证**：零角度下查看器算出的所有关节原点、脚尖、嘴尖世界坐标，与从
MJCF 独立解析出的 rest pivot 逐项吻合（误差 < 1e-4 m）。

### 已知边界（诚实标注）

- **嘴部**：alpha 运动学 MJCF 里 `mouth` 没有 hinge（只有 `head_roll` 下的 `mouth_tip`
  site），故嘴部作为 `head_roll` 下的固定偏移节点，**不驱动骨架转动**。真机若上报
  `mouth` 角，查看器只记录不旋转该节点。
- **无连杆实体/网格**：只看关节原点连线（骨架），不含连杆几何体或 mesh；不反映各体
  自身 `quat` 决定的连杆朝向（仅取关节原点位置画骨架，足够姿态核对）。
- **脚尖/嘴尖**是 MJCF 的 site，位置随父体世界变换移动，已纳入 FK。

## 7. 典型排错

- 画面里腿/头“穿模”或比例怪异：先确认 `--source stdin` 拿到的 `joints` 长度是否为 15；
  长度不符时查看器会截断补 0 并照常画（此时是数据线/旧帧问题，不是几何问题）。
- 完全不动：检查 `robotctl monitor --json` 是否真的在吐带 `joints` 的帧（连接横幅行
  会被查看器跳过）。
- 想要更准的几何：换用带 `mouth` hinge 的完整 `robot_walk.xml`（非 alpha）后，把对应
  `pos`/`quat`/`joint` 回填 `live_viewer.py` 的 `BONES` 即可，FK 无需改动。
