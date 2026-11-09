# MicroDuck HD-1910 真机 3D 姿态查看器 · 使用说明

> 配套工具：`microduck-software/tools/hd1910/live_viewer.py`
> 上游对照依据：`docs/active/microduck-upstream-对照-2026-11-08.md` §4（可视化契约）

## 1. 它做什么

把真机实时上报的关节姿态画成一只可旋转的 3D 鸭子骨架，用于**不上真机也能肉眼核对
`robotd` 有没有在动、各关节角度/目标是否对、跟踪误差多大**，并叠加**体坐标重力箭头（红）+
原始陀螺箭头（青）+ 倾角 + 里程 + IMU 健康**。其中重力/陀螺/头姿/里程来自 `robotctl monitor
--json` 的 `RobotState`（lib.rs:2651 的 `safety.gravity` / `gyro` / `head` / `odom`，两条线
共用接口面，零改 robotd）；**IMU 健康来自独立的 `robot.health` RPC**（monitor 流不带它，
查看器后台轮询 `robotctl health --json` 合并，见 §4）。姿态数据来自真机的
`robotctl monitor --json`（服务端默认降采样 10 Hz），其 `RobotState.joints` / `targets` 是
裸角度数组，索引按 `JOINT_NAMES`（见 §5）。

## 2. 依赖

- **零重依赖即可跑**：FK 用纯 Python 四元数/矩阵；`--renderer headless` 只打印数值
  （含重力/IMU 健康）。
- 想要图形：装 `matplotlib`（`pip install matplotlib`）得本地 3D **真实 STL 外形 mesh +
  关节球 + 重力箭头**；装 `viser`（`pip install viser`）得浏览器里可旋转/缩放的实时
  **mesh** 画面（`--renderer auto` 会优先 viser，其次 matplotlib，最后 headless）。
- **真实外形（P3，默认开）**：只要仓库里 vendored 了训练版 MJCF
  `.upstream/hd1910m/microduck_rl/src/mjlab_microduck/robot/microduck/robot_walk.xml`
  （含 `assets/*.stl` 40 个 binary STL），查看器就自动解析并用 FK 把每个 STL 零件摆到对应
  体（零缩放、米制）。找不到该 MJCF 时才退化回占位圆柱（诚实降级，HUD 标 `[cylinder]`）。
  matplotlib 端会按三角面预算（≤~120k）自动降采样以保流畅（可用 `--mesh-stride` 调整，
  viser 端建议 `--mesh-stride 1` 拿全分辨率）。

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
python live_viewer.py --demo --renderer matplotlib     # 本地 3D 真实 STL 外形
python live_viewer.py --demo --renderer viser          # 浏览器 3D 真实 STL 外形（默认端口 8012）
python live_viewer.py --demo --renderer headless       # 只打印数值（含重力/IMU）
```

### P3：真实 STL 外形（mesh 替换占位圆柱）

```bash
# 默认行为：自动找 vendored 训练 MJCF，渲染真实 STL（找不到则退化圆柱）
python live_viewer.py --source mock-relay --renderer matplotlib

# 强制 mesh / 强制圆柱（--mesh-mode auto|mesh|cylinder）；mesh 无源时退化并告警
python live_viewer.py --demo --renderer viser --mesh-mode mesh --mesh-stride 1

# 指定其它 MJCF（含自有 mesh 资产）路径
python live_viewer.py --source robotctl --mesh-source /path/to/robot_walk.xml

# matplotlib 卡顿就调大 --mesh-stride（viser 端可调到 1 全分辨率）
python live_viewer.py --source mock-relay --renderer matplotlib --mesh-stride 8
```

> 注意：`--source robotctl` / `mock-relay` 是 **2026-11-08 新增**。前者经 `robotctl monitor --json`
> 走 mediad 的 WebRTC relay 连真机（需要 operator PC 上 `robotctl` 在 PATH + 网络可达）；后者是
> 真机流的**本地仿真**（同 JSON 形状），用于没机器人时验证解析 + 重力/IMU + mesh 渲染。
> 真机实跑请用 A/A'，本沙箱无机器人，已用 `--source mock-relay` 验证全链路。
> 首跑前建议先走 §8 的 `capture_live.py` + `verify_capture.py` 对真实字节做静态对照。
> `mock-relay` 的 matplotlib 渲染此前有一个 targets 偏差绿线的拆包 bug（2026-11-09 修复），
> 现 `--source mock-relay --renderer matplotlib` 可正常跑。

- `--host`：`--source robotctl` 时指定 ssh 远端主机。
- `--interval-ms`：matplotlib/viser 的刷新间隔（默认 100）。
- `Ctrl-C` 退出。

## 4. 它显示什么

- **headless**：逐帧打印每个关节的 `j`（实测角）、`tgt`（目标角）、`err`（跟踪误差），
  以及 `max_track_err`；并附 **`gravity` 体坐标重力向量 + 倾角 `tilt` + `fallen`/`limp` +
  `gyro` 原始陀螺（rad/s）+ `odom` 躯干世界坐标（m）+ 航向 `yaw` + IMU 过期块 `imu_stale` /
  `imu_healthy` + `mount` 装后朝向自检**。一眼看谁没跟上、机器人是否要倒、IMU 是否过期、
  安装四元数是否疑似配错。
- **matplotlib/viser**：默认画**真实 STL 外形 mesh**（每个训练 MJCF 的视觉零件，米制、
  零缩放，由 FK 摆到对应体）+ **关节球** + 体坐标**红色重力箭头** + **青色陀螺箭头**
  （盆骨→髋→膝→踝→脚尖，颈/头/嘴同理）；躯干画粗、肢体画细。若某关节
  `targets` 与 `joints` 相差 >1e-3，会叠加一条绿色虚线表示目标姿态。找不到 mesh 源时
  退化画**占位圆柱**（HUD 标 `[cylinder]`）。viser 还提供浏览器内旋转/缩放。
- `velocities` / `currents_ma` 若真机上报则随帧携带，目前仅 headless 打印原始数组；
  空数组表示「该帧未上报」，查看器**绝不将其当作 0**。`safety.gravity` 缺失时标注
  `gravity=n/a`。
- **IMU 健康来自独立 RPC**：monitor 流（`RobotState`）**不带 health**，所以 `--source
  robotctl` 会另起一个**后台线程**，每 1.5 s 跑一次 `robotctl health --json`（或 `--host`
  时的 `ssh <host> 'robotctl health --json'`），把 `robot.imu.consecutive_stale_blocks`
  / `robot.healthy` 合并进每帧（lib.rs:2429 HealthResult / 2544 ImuHealth）。该 RPC
  取不到/报错时，对应字段保持 `None`，HUD 标注 `imu_health=n/a(robot.health)`——这是
  **正常状态，不是 bug**。
- **装后朝向自检 `mount=`**：移植自 `AI-FanGe/Microduck-build-tutorial` 的
  `imu_orientation_check.py` 思路。机器人**水平静止**时，robotd 的 `safety.gravity` 应
  ≈ `[0,0,-1]`（直立）；若静止且偏离超 20° 则显示 **`mount=⚠MOUNT?`**，提示
  `imu_mount_quat`（部署档）很可能配错（负对照：配错必被抓出）。运动中（`|gyro|` 大）、
  已倒下、无数据分别显示 `mount=moving` / `fallen` / `insufficient`，**不下结论**。
  价值：抓「装错 IMU 朝向四元数」这类静默错误——真机上配错时即使水平静止，gravity 也会偏。

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

### 6.1 真实 STL mesh（P3）

**为什么之前只有占位圆柱**：alpha 运动学 MJCF（§6 烘焙来源）只有 `pos`/`quat`/`joint`，
**不含视觉几何**。真实外形在**训练版 MJCF**
`.upstream/hd1910m/microduck_rl/src/mjlab_microduck/robot/microduck/robot_walk.xml`
里：每个 `<body>` 内若干 `<geom type="mesh" pos=.. quat=.. mesh=.. material=../>`，外加
`<asset>` 里 40 个 binary STL（单位已实测为**米**，trunk_base≈0.057×0.036×0.003 m、
foot_left≈0.040×0.054×0.017 m），与 MJCF 帧一致，**零缩放**接入。

**体名映射**：该训练 MJCF 的体树与 `BONES` 只在 3 个体名不同，共享 body 的 `pos`/`quat`/
`joint` 完全一致（逐行核对），故 FK 算出的 body 世界帧可直接套用：

```
upper_leg_left ↔ left_upper_leg
upper_leg_right ↔ right_upper_leg
jaw_soft       ↔ bottom_head_shell        # 头部所有零件（lens/face_part/jaw/…）都挂在 jaw_soft 体下
```

**几何世界变换**（每个 geom）：

```
world_vertex = FK(body).R · (geom_local.R · stl_vertex + geom_local.pos) + FK(body).t
```

其中 `geom_local` 是 geom 相对其 body 的局部 `pos`/`quat`，`FK(body)` 来自 `forward_frames`
（与 §6 同源的纯 Python 四元数 FK）。查看器整体以 `trunk_base` 为原点显示，所以 world 点再
减 `trunk_base` 原点以对齐关节球。

**降采样 / 性能**：总三角面约 87 万（75 个 geom）。matplotlib 3D 非 GPU 加速，故 matplotlib
端按 ~12 万三角面预算自动提高 `--mesh-stride`（本模型约 stride 8，~11 万面，~10 FPS）；
viser（WebGL）可 `--mesh-stride 1` 取全分辨率。`--mesh-stride` 调大更省算力。

**正确性验证（见 `tests/test_hd1910_viewer_mesh.py`）**：
- STL 单位必须是米（错单位会把整只机器人放大 1000 倍）；
- 每个 parsed geom 必须落到 `BONES` 体（`MESH_BODY_MAP` 之外的未映射即真 bug）；
- 相同关节角 → 完全相同世界顶点（确定性）；改左膝角 → foot 网格质心明显移动（FK 真在驱动
  mesh，负对照）；foot 网格质心贴近 `ankle_left` 体原点（FK+geom+原点减法对齐正确）。

### 已知边界（诚实标注）

- **嘴部**：alpha 运动学 MJCF 里 `mouth` 没有 hinge（只有 `head_roll` 下的 `mouth_tip`
  site），故嘴部作为 `head_roll` 下的固定偏移节点，**不驱动骨架转动**。真机若上报
  `mouth` 角，查看器只记录不旋转该节点。
- **真实外形是 STL mesh，占位圆柱只是退化**：默认（vendored 训练 MJCF 在）渲染真实 STL
  零件；**只有当 MJCF 找不到**时才退化成等半径占位圆柱（躯干粗、肢体细）。要换用其它/自有
  mesh 资产，传 `--mesh-source /path/to/robot_walk.xml`（其 `meshdir` 指向的 `assets/*.stl`）。
  几何来源与正确性见 §6.1。
- **重力箭头在体坐标系**：红色箭头锚在躯干原点、沿 `safety.gravity` 方向（直立 ≈ 指向 -Z），
  与 FK 同一 trunk 坐标系，直接看机器人相对“下”的偏移。
- **IMU 健康是独立 RPC，不是 monitor 字段**：`robotctl monitor --json` 的 `RobotState`
  （lib.rs:2651）只有 `safety.gravity` / `gyro` / `head` / `odom`，**没有 `health`**。
  `imu_stale` / `imu_healthy` 必须经 `robotctl health --json`（HealthReport →
  `robot.imu.consecutive_stale_blocks`，lib.rs:2544）单独取。该协议形态已对照
  **DuckBuddy-main**（即我们的 HD-1910 robotd 代码基）逐字段核对，`monitor` 与 `health` 两条
  IPC 共用此源码，接入方式成立；两条线协议不同导致的字段错位风险已排除。
- **脚尖/嘴尖**是 MJCF 的 site，位置随父体世界变换移动，已纳入 FK。

## 7. 典型排错

- 画面里腿/头“穿模”或比例怪异：先确认 `--source stdin` 拿到的 `joints` 长度是否为 15；
  长度不符时查看器会截断补 0 并照常画（此时是数据线/旧帧问题，不是几何问题）。
- 完全不动：检查 `robotctl monitor --json` 是否真的在吐带 `joints` 的帧（连接横幅行
  会被查看器跳过）。
- 想要更准的几何：默认已是真实 STL 外形（见 §6.1）；若显示成占位圆柱，说明 vendored 训练
  MJCF 没被找到——检查 `.upstream/hd1910m/microduck_rl/.../robot/microduck/robot_walk.xml`
  是否存在，或用 `--mesh-source` 指向含 mesh 资产的 MJCF。matplotlib 卡顿就调大
  `--mesh-stride`（见 §6.1）。

## 8. 真机首跑：抓取 + 字节级对照（强烈建议先做）

查看器的解析路径此前从没对**真实 robotctl 字节**验证过（本开发环境无 `robotctl` 二进制 /
无机器人主机 / 无 WebRTC relay 访问）。直接 `--source robotctl` 可能“防御性解析不崩，但
静默显示 n/a”。所以首跑前，先用下面两个工具把真实字节抓下来、**静态对照**，确认
HD-1910 robotd 的 `monitor` 流到底暴露了哪些字段、`health` RPC 形状对不对。

```bash
# 1) 抓真机：monitor 流落盘 ndjson + health 落盘 JSON（operator PC，robotctl 在 PATH 或经 ssh）
python capture_live.py --source robotctl --seconds 8 \
    --out monitor.ndjson --health-out health.json
python capture_live.py --source robotctl --host robot-host --seconds 8 \
    --out monitor.ndjson --health-out health.json      # 无需本机装 robotctl

# 2) 对照：用查看器真实 parse_state 逐帧解析，报字段覆盖率 + 合理性 + health 形状
python verify_capture.py --monitor monitor.ndjson --health health.json
cat monitor.ndjson | python verify_capture.py --monitor -      # 也支持 stdin
```

`verify_capture.py` 会明确给出类似结论（决定首跑前是否补齐）：

```
✓ monitor 流暴露 safety.gravity → 查看器重力/倾角显示可用
⚠ gyro 未上报 → 查看器陀螺箭头显示 n/a（不崩，仅缺该箭头）
✓ health RPC 形状正确（report.robot.imu.consecutive_stale_blocks 可解析）
```

**本地无硬件也能验证工具本身**（合成帧，不连真机）：

```bash
python capture_live.py --source mock --out monitor.ndjson --health-out health.json
python verify_capture.py --monitor monitor.ndjson --health health.json
```

> 两个工具仅依赖 Python 标准库 + 同目录 `live_viewer`（`capture_live.py` mock 模式、
> `verify_capture.py` 才会 import `live_viewer`）；真机模式不 import 任何第三方包。

