# MicroDuck HD-1910 真机 3D 姿态查看器 · 使用说明

> 配套工具：`microduck-software/tools/hd1910/live_viewer.py`
> 上游对照依据：`docs/active/microduck-upstream-对照-2026-11-08.md` §4（可视化契约）

## 1. 它做什么

把真机实时上报的关节姿态画成一只可旋转的 3D 鸭子骨架，用于**不上真机也能肉眼核对
`robotd` 有没有在动、各关节角度/目标是否对、跟踪误差多大**，并叠加**体坐标重力箭头 +
倾角 + IMU 健康**（两条线共用 `robot.state.safety.gravity` 接口面，零改 robotd）。
姿态数据来自真机的 `robotctl monitor --json`（服务端默认降采样 10 Hz），其
`RobotState.joints` / `targets` 是裸角度数组，索引按 `JOINT_NAMES`（见 §5）。

## 2. 依赖

- **零重依赖即可跑**：FK 用纯 Python 四元数/矩阵；`--renderer headless` 只打印数值
  （含重力/IMU 健康）。
- 想要图形：装 `matplotlib`（`pip install matplotlib`）得本地 3D **圆柱 mesh + 关节球 +
  重力箭头**；装 `viser`（`pip install viser`）得浏览器里可旋转/缩放的实时 **mesh** 画面
  （`--renderer auto` 会优先 viser，其次 matplotlib，最后 headless）。

## 3. 用法

```bash
# A. 真机流：经 robotctl 走 WebRTC relay（robotctl 在 PATH + 网络；最贴近生产）
python live_viewer.py --source robotctl
python live_viewer.py --source robotctl --host robot-host   # 走 ssh 拉流

# A'. 等价：手动 ssh 管道（robotd 经 mediad 的 WebRTC relay 同链路）
ssh robot_host 'robotctl monitor --json' | python live_viewer.py --source stdin

# B. 本机无真机：静止站姿演示（含直立重力 + 健康 IMU）
python live_viewer.py --demo

# C. 本机无真机：模拟真机流（合成关节摆动 + 倾斜重力 + IMU 过期块），用于端到端验证整条管线
python live_viewer.py --source mock-relay --renderer matplotlib

# D. 渲染后端
python live_viewer.py --demo --renderer matplotlib     # 本地 3D 圆柱 mesh
python live_viewer.py --demo --renderer viser          # 浏览器 3D 圆柱 mesh（默认端口 8012）
python live_viewer.py --demo --renderer headless       # 只打印数值（含重力/IMU）
```

> 注意：`--source robotctl` / `mock-relay` 是 **2026-11-08 新增**。前者经 `robotctl monitor --json`
> 走 mediad 的 WebRTC relay 连真机（需要 operator PC 上 `robotctl` 在 PATH + 网络可达）；后者是
> 真机流的**本地仿真**（同 JSON 形状），用于没机器人时验证解析 + 重力/IMU + mesh 渲染。
> 真机实跑请用 A/A'，本沙箱无机器人，已用 `--source mock-relay` 验证全链路。

- `--host`：`--source robotctl` 时指定 ssh 远端主机。
- `--interval-ms`：matplotlib/viser 的刷新间隔（默认 100）。
- `Ctrl-C` 退出。

## 4. 它显示什么

- **headless**：逐帧打印每个关节的 `j`（实测角）、`tgt`（目标角）、`err`（跟踪误差），
  以及 `max_track_err`；并附 **`gravity` 体坐标重力向量 + 倾角 `tilt` + `fallen`/`limp` +
  IMU 过期块 `imu_stale` / `imu_healthy`**。一眼看谁没跟上、机器人是否要倒、IMU 是否过期。
- **matplotlib/viser**：按真实连杆树画**圆柱连杆 mesh + 关节球 + 体坐标红色重力箭头**
  （盆骨→髋→膝→踝→脚尖，颈/头/嘴同理）；躯干画粗、肢体画细。若某关节 `targets` 与
  `joints` 相差 >1e-3，会叠加一条绿色虚线表示目标姿态。viser 还提供浏览器内旋转/缩放。
- `velocities` / `currents_ma` 若真机上报则随帧携带，目前仅 headless 打印原始数组；
  空数组表示「该帧未上报」，查看器**绝不将其当作 0**。`safety.gravity` 缺失时标注
  `gravity=n/a`，`health` 不在 monitor 流里时标注 `imu_health=n/a(robot.health)`（需用
  `robot.health` RPC 单独查）。

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
- **连杆是占位圆柱，不是真实 mesh/skin**：matplotlib/viser 用**等半径圆柱**近似每段连杆
  （躯干粗、肢体细），足够姿态核对，但不反映各体自身 `quat` 决定的真实连杆截面/外观
  （无 mesh 皮肤）。要更真实的外观需另接 `robot_walk.xml` 的 mesh 资产。
- **重力箭头在体坐标系**：红色箭头锚在躯干原点、沿 `safety.gravity` 方向（直立 ≈ 指向 -Z），
  与 FK 同一 trunk 坐标系，直接看机器人相对“下”的偏移。
- **脚尖/嘴尖**是 MJCF 的 site，位置随父体世界变换移动，已纳入 FK。

## 7. 典型排错

- 画面里腿/头“穿模”或比例怪异：先确认 `--source stdin` 拿到的 `joints` 长度是否为 15；
  长度不符时查看器会截断补 0 并照常画（此时是数据线/旧帧问题，不是几何问题）。
- 完全不动：检查 `robotctl monitor --json` 是否真的在吐带 `joints` 的帧（连接横幅行
  会被查看器跳过）。
- 想要更准的几何：换用带 `mouth` hinge 的完整 `robot_walk.xml`（非 alpha）后，把对应
  `pos`/`quat`/`joint` 回填 `live_viewer.py` 的 `BONES` 即可，FK 无需改动。
