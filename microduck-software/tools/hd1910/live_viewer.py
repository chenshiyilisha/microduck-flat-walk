#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroDuck HD-1910 真机 3D 姿态查看器
===================================

依据（见 docs/active/microduck-upstream-对照-2026-11-08.md §4 与
docs/active/microduck-三个开源硬件项目研究-2026-11-08.md）：
  * 真机状态经 ``robotctl monitor --json`` 吐出 ``RobotState``（服务端默认降采样 10 Hz）。
    ``robotctl`` 通过 mediad 的 **WebRTC relay** 连到机器人（*.webclient/index.html）。
  * ``RobotState.joints`` / ``targets`` 是裸角度数组（弧度），**索引按 JOINT_NAMES**。
  * ``RobotState.safety.gravity`` 是 **体坐标系（trunk frame）重力单位向量**，直立 ≈ ``[0,0,-1]``
    （lib.rs:4008，``#[serde(default)]``，fallen 判定同源）。这是两条线（HD-1910 / ft1910）
    共用的接口面，`live_viewer` 直接复用，零改 robotd。
  * IMU 健康：``robot.health`` 是 **独立 RPC**（与 monitor 不同一条流），``robotctl health --json``
    返回 ``robot.imu.consecutive_stale_blocks``（过期块计数，lib.rs:2544 ImuHealth）。
    monitor 流（RobotState）**不含 health**，所以 --source robotctl 会另起后台线程周期性跑
    ``robotctl health --json`` 并把结果合并进每帧；缺失/失败时标注 "n/a (robot.health)"。
  * 真流里还有这些字段，查看器一并显示：``RobotState.gyro``（原始陀螺，体坐标 rad/s，
    lib.rs:2674）、``RobotState.head``（头部四元数，lib.rs:2659）、``RobotState.odom``
    （躯干世界坐标 + 航向，lib.rs:2729）。重力（红）/ 陀螺（青）箭头均锚在 trunk 原点。
  * JOINT_NAMES（左腿优先，15 个）：
        left_hip_yaw(0) left_hip_roll(1) left_hip_pitch(2) left_knee(3) left_ankle(4)
        neck_pitch(5) head_pitch(6) head_yaw(7) head_roll(8) mouth(9)
        right_hip_yaw(10) right_hip_roll(11) right_hip_pitch(12) right_knee(13) right_ankle(14)
    —— 与 ft1910/duck-ipc-proto/src/lib.rs:536 完全一致。

运动学几何（真实，非占位）
--------------------------
  * 连杆树 / 各体平移旋转 / 关节轴 **烘焙自 ft1910 的 MJCF**
    ``.upstream/ft1910/kinematics/assets/alpha/robot_walk.xml``（逐体 pos/quat 与
    joint axis="0 0 1"，6–108 行），由一次性脚本解析，本文件只烘焙结果，零依赖也能跑。
  * 坐标约定：MJCF 本就 **Z 向上 / X 向前 / Y 向左**，与查看器一致，无需轴交换。
  * FK 严格按 MuJoCo 帧组合（纯 Python 四元数），零角度下各关节原点与 MJCF rest pivot 逐项吻合。
  * mouth 在 alpha MJCF 无 hinge，作 head_roll 下固定偏移节点（诚实标注）。

真实视觉外形（STL mesh，P3）
---------------------------
  * alpha 运动学 MJCF 只有 pos/quat/joint，**不含视觉几何**。真实外形在训练版 MJCF
    ``.upstream/hd1910m/microduck_rl/src/mjlab_microduck/robot/microduck/robot_walk.xml``
    （含 ``<geom type="mesh">`` + ``assets/*.stl`` 40 个 binary STL，单位米）。
  * 该训练 MJCF 的体树与 BONES 只在 3 个体名不同（upper_leg_left↔left_upper_leg、
    upper_leg_right↔right_upper_leg、jaw_soft↔bottom_head_shell），共享 body 的
    pos/quat/joint 完全一致 ⇒ FK(body) 世界帧可直接套用，零缩放摆真实 STL。
  * 每个 geom 的世界顶点 = FK(body).R·(geom局部.R·stl顶点 + geom局部.pos) + FK(body).t。
    默认 --mesh-source auto 自动定位该 vendored MJCF；找不到则退化回占位圆柱（--mesh-mode
    可强制 mesh/cylinder）。--mesh-stride 降采样三角面数（matplotlib 默认 2 以保流畅）。

用法
----
  # 1) 真机流：经 robotctl 走 WebRTC relay（最贴近生产的路径；需 robotctl 在 PATH + 网络）
  python live_viewer.py --source robotctl
  python live_viewer.py --source robotctl --host robot-host   # 走 ssh 拉流

  # 2) 从真机经 ssh 管道（等价 --source robotctl --host，手动控制）
  ssh robot-host 'robotctl monitor --json' | python live_viewer.py --source stdin

  # 3) 本地无机器人：模拟真机流（合成关节摆动 + 倾斜重力 + IMU 过期块），验证整条管线
  python live_viewer.py --source mock-relay --renderer matplotlib

  # 4) 静止站姿演示 FK（不需要任何依赖）
  python live_viewer.py --demo

  # 5) 渲染后端：auto(默认, viser→matplotlib→headless) / matplotlib / viser / headless

  # 6) 真实 STL 外形（P3）：默认 auto 自动找 vendored 训练 MJCF；找不到→占位圆柱
  python live_viewer.py --source mock-relay --renderer matplotlib --mesh-mode mesh
  python live_viewer.py --source robotctl --mesh-source /path/to/robot_walk.xml
  #    --mesh-mode auto|mesh|cylinder   --mesh-stride 2(降采样三角面)

设计要点
--------
  * 零重依赖也能跑：FK 用纯 Python 四元数，headless 只打印。matplotlib/viser 可选（lazy import）。
  * matplotlib 用 Poly3DCollection 画真实 STL 零件（无源时退化为连杆圆柱）+ 关节球 + 体坐标
    重力箭头（红）/陀螺箭头（青）（本体现）；viser 用 add_mesh 真实零件（无源时退化圆柱）+ 关节点
    + 重力线 + 陀螺线（浏览器可旋转缩放）。HUD 同时显示 gravity/tilt/gyro/odom/IMU 健康等标量。
  * 关节 ID 体系严格用我们的「1–15 物理 ID + 左腿优先名序」，不混入官方 10–14/20–24/30–34。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

# ───────────────────────────────────────────────────────────────────────────
# 1. 关节名序（左腿优先，与 wire 完全一致；下标 = joints[] 数组下标）
# ───────────────────────────────────────────────────────────────────────────
JOINT_NAMES: list[str] = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]
N = len(JOINT_NAMES)

# ft1910/duck-control/src/model.rs:37 的 DEFAULT_POSITION（弧度），作为演示静止姿。
# 下标顺序左腿优先，与 JOINT_NAMES 对齐。
REST_POSITION: list[float] = [
    0.0, -0.0873, -0.4579, -0.0049, 0.4530,   # 左腿
    0.3491, 0.3491, 0.0, 0.0, 0.0,             # 颈/头/嘴
    0.0, 0.0873, 0.4579, 0.0049, -0.4530,      # 右腿
]

# ───────────────────────────────────────────────────────────────────────────
# 2. 运动学树（烘焙自 ft1910/kinematics/assets/alpha/robot_walk.xml，6–108 行）
#    坐标系：Z 向上 / X 向前 / Y 向左（与 MJCF 一致）。
#    每个体：parent 体名、相对父体的平移 pos、相对父体的旋转 quat(wxyz)、
#           若含关节则 joint=关节名、axis=关节轴（父体坐标系下，本模型均为 0 0 1）。
# ───────────────────────────────────────────────────────────────────────────
BONES: list[dict] = [
    {"name": "trunk_base",       "parent": None,                "pos": (0.0, 0.0, 0.12),      "quat": (1.0, 0.0, 0.0, 0.0)},
    {"name": "yaw2roll",         "parent": "trunk_base",        "pos": (0.006, 0.0175, -0.005), "quat": (0.0, -0.707107, -0.707107, -0.0), "joint": "left_hip_yaw", "axis": (0, 0, 1)},
    {"name": "hip_l",            "parent": "yaw2roll",          "pos": (-0.0, 0.0165, 0.0125),  "quat": (0.707107, -0.707107, -0.0, 0.0), "joint": "left_hip_roll", "axis": (0, 0, 1)},
    {"name": "left_upper_leg",   "parent": "hip_l",             "pos": (0.025, 0.0, -0.0185),   "quat": (0.5, -0.5, 0.5, -0.5), "joint": "left_hip_pitch", "axis": (0, 0, 1)},
    {"name": "leg",              "parent": "left_upper_leg",    "pos": (0.022, 0.0357771, -0.004), "quat": (0.0, 0.707107, 0.707107, -0.0), "joint": "left_knee", "axis": (0, 0, 1)},
    {"name": "ankle_left",       "parent": "leg",               "pos": (-0.0, 0.042, -0.026),   "quat": (0.0, 1.0, 0.0, -0.0), "joint": "left_ankle", "axis": (0, 0, 1)},
    {"name": "neck",             "parent": "trunk_base",        "pos": (0.026, 0.0145011, 0.0324424), "quat": (0.0, -0.0, -0.707107, 0.707107), "joint": "neck_pitch", "axis": (0, 0, 1)},
    {"name": "neck_pitch",       "parent": "neck",              "pos": (0.0, -0.05, 0.0),       "quat": (0.0, 1.0, 0.0, 0.0), "joint": "head_pitch", "axis": (0, 0, 1)},
    {"name": "yaw_roll_motion",  "parent": "neck_pitch",        "pos": (-0.0, 0.0186931, -0.0145), "quat": (0.0, -0.0, -0.707107, -0.707107), "joint": "head_yaw", "axis": (0, 0, 1)},
    {"name": "bottom_head_shell","parent": "yaw_roll_motion",   "pos": (-0.0179, 0.0, 0.0145),   "quat": (0.707107, -0.0, -0.707107, 0.0), "joint": "head_roll", "axis": (0, 0, 1)},
    {"name": "bearing_roll",     "parent": "trunk_base",        "pos": (0.006, -0.0175, -0.005), "quat": (0.0, -0.707107, -0.707107, -0.0), "joint": "right_hip_yaw", "axis": (0, 0, 1)},
    {"name": "hip_l_2",          "parent": "bearing_roll",      "pos": (-0.0, 0.0165, 0.0125),   "quat": (0.0, -0.0, 0.707107, 0.707107), "joint": "right_hip_roll", "axis": (0, 0, 1)},
    {"name": "right_upper_leg",  "parent": "hip_l_2",           "pos": (0.025, 0.0, -0.0185),    "quat": (0.5, -0.5, 0.5, -0.5), "joint": "right_hip_pitch", "axis": (0, 0, 1)},
    {"name": "leg_2",            "parent": "right_upper_leg",   "pos": (-0.022, 0.0357771, -0.004), "quat": (0.0, 1.0, -0.0, -0.0), "joint": "right_knee", "axis": (0, 0, 1)},
    {"name": "ankle_right",      "parent": "leg_2",             "pos": (-0.042, -0.0, -0.026),   "quat": (0.0, -0.707107, 0.707107, 0.0), "joint": "right_ankle", "axis": (0, 0, 1)},
    # 脚尖（site，无关节）：left_foot / right_foot，pos 取自 robot_walk.xml 的 site
    {"name": "left_foot",        "parent": "ankle_left",        "pos": (-0.0, -0.0237879, -0.0140852), "quat": (1.0, 0.0, 0.0, 0.0)},
    {"name": "right_foot",       "parent": "ankle_right",       "pos": (-0.0, 0.0237879, -0.0140852),  "quat": (1.0, 0.0, 0.0, 0.0)},
    # 嘴尖（site，无关节）：mouth_tip pos 取自 robot_walk.xml；alpha 运动学无 mouth hinge
    {"name": "mouth",            "parent": "bottom_head_shell", "pos": (-0.00829334, 0.0, -0.0777383), "quat": (1.0, 0.0, 0.0, 0.0)},
]
BONE_BY_NAME: dict[str, dict] = {b["name"]: b for b in BONES}
JOINT_TO_BONE: dict[str, str] = {b["joint"]: b["name"] for b in BONES if b.get("joint")}
EDGES: list[tuple[str, str]] = [(b["name"], b["parent"]) for b in BONES if b["parent"]]
# 躯干（trunk_base→neck 与左右髋）画粗一点，肢体细一点
TORSO_EDGES = {"yaw2roll", "bearing_roll", "neck"}
LINK_RADIUS = 0.022          # 肢体半径 (m)
TORSO_RADIUS = 0.045         # 躯干半径 (m)

# —— IMU 装后朝向自检（移植自 build-tutorial imu_orientation_check.py 思路）——
# 机器人水平静止时，robotd 的 safety.gravity 应≈[0,0,-1]（直立）。
# 若静止且偏离超容差 → 怀疑安装四元数（imu_mount_quat）配错（负对照：配错必被抓出）。
MOUNT_CHECK_TILT_TOL_DEG = 20.0   # 水平静止下 gravity 偏离 -Z 的允许容差
GYRO_STILL_RAD_S = 0.15           # 角速度低于此值视为“静止”，可下朝向结论


# ───────────────────────────────────────────────────────────────────────────
# 3. 纯 Python 四元数 + 旋转（不依赖 numpy）
# ───────────────────────────────────────────────────────────────────────────
def _quat_to_mat(w: float, x: float, y: float, z: float) -> list[list[float]]:
    R = [
        [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)],
    ]
    return R


def _axis_angle_to_mat(axis: tuple[float, float, float], ang: float) -> list[list[float]]:
    x, y, z = axis
    n = math.sqrt(x*x + y*y + z*z)
    if n < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    x, y, z = x/n, y/n, z/n
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return [
        [c + x*x*C,     x*y*C - z*s,   x*z*C + y*s],
        [y*x*C + z*s,   c + y*y*C,     y*z*C - x*s],
        [z*x*C - y*s,   z*y*C + x*s,   c + z*z*C],
    ]


def _mmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mat_vec(M: list[list[float]], p: tuple[float, float, float]) -> tuple[float, float, float]:
    return (M[0][0]*p[0] + M[0][1]*p[1] + M[0][2]*p[2],
            M[1][0]*p[0] + M[1][1]*p[1] + M[1][2]*p[2],
            M[2][0]*p[0] + M[2][1]*p[1] + M[2][2]*p[2])


def forward_frames(angles: list[float]) -> dict[str, tuple[list, tuple]]:
    """angles: 长度 15，下标对应 JOINT_NAMES。返回每个 BONE 的 (R, t) 世界帧（绝对，
    未减 trunk_base 原点）。R 为 3x3 旋转（body 坐标系 → 世界，list[list[float]]），
    t 为 body 原点的世界平移 (tuple)。纯 Python 四元数，零依赖；与 MuJoCo 帧组合严格一致
    （零角度下各 body 原点与 MJCF rest pivot 逐项吻合）。P3 的 mesh 渲染复用本函数拿每体的
    世界 R/t，再叠加 geom 局部 pos/quat 把 STL 顶点摆到世界。"""
    assert len(angles) == N, f"需要 {N} 个关节角，收到 {len(angles)}"
    ang = {JOINT_NAMES[i]: angles[i] for i in range(N)}
    frames: dict[str, tuple[list, tuple]] = {}
    for b in BONES:
        if b["parent"] is None:
            R = _quat_to_mat(*b["quat"])
            t = list(b["pos"])
        else:
            PR, PT = frames[b["parent"]]
            Rq = _axis_angle_to_mat(b["axis"], ang[b["joint"]]) if b.get("joint") else [[1,0,0],[0,1,0],[0,0,1]]
            R = _mmul(PR, _mmul(Rq, _quat_to_mat(*b["quat"])))
            rp = _mat_vec(Rq, b["pos"])           # 关节先转，再平移（MuJoCo：parent·R(q)·T(pos)·R(quat)）
            t = [PT[i] + sum(PR[i][k]*rp[k] for k in range(3)) for i in range(3)]
        frames[b["name"]] = (R, tuple(t))
    return frames


def forward_kinematics(angles: list[float]) -> dict[str, tuple[float, float, float]]:
    """angles: 长度 15，下标对应 JOINT_NAMES。返回每个 BONE 原点的世界坐标（相对 trunk_base）。
    等价于 forward_frames 后减去 trunk_base 原点，供连杆圆柱 / 关节球等纯位置渲染使用。"""
    frames = forward_frames(angles)
    origin = frames["trunk_base"][1]
    return {name: (f[1][0]-origin[0], f[1][1]-origin[1], f[1][2]-origin[2]) for name, f in frames.items()}


# ───────────────────────────────────────────────────────────────────────────
# 3b. 真实 MJCF 几何（STL mesh，P3）
# ───────────────────────────────────────────────────────────────────────────
# 真实视觉几何不在 alpha 运动学 MJCF（只有 pos/quat/joint，无 geom/mesh），而在训练版
# MJCF（hd1910m/microduck_rl/.../microduck/robot_walk.xml）：每个 <body> 内若干
# ``<geom type="mesh" pos=.. quat=.. mesh=.. material=../>``，局部 pos/quat 相对“该 body
# 坐标系”。运动学树与 alpha 烘焙出的 BONES 完全一致（仅 3 个体名不同，见 MESH_BODY_MAP），
# 所以 FK 拿到的 body 世界帧可直接套用。STL 为 binary（80B 头 + uint32 面数 + 每面 50B：
# 3f 法向 + 9f 三顶点 + 2B 属性字节），单位已实测为米（trunk_base≈0.057×0.036×0.003 m，
# foot_left≈0.040×0.054×0.017 m），与 MJCF 帧一致，零缩放接入。
#
# 几何世界变换（每个 geom）：
#     world_vertex = FK(body).R · (geom_local.R · stl_vertex + geom_local.pos) + FK(body).t
# 其中 geom_local 相对 body 坐标系；FK(body) 来自 forward_frames。查看器整体以 trunk_base
# 为原点显示（forward_kinematics 已减原点），故 mesh 世界点也减去 trunk_base 原点以对齐。
#
# MJCF 体名 ↔ BONES 体名（仅 3 处不同；其余同名）。BONES 多出的 left_foot/right_foot/mouth
# 在 MJCF 里是 <site>，无 mesh，自然不会被映射。
MESH_BODY_MAP: dict[str, str] = {
    "upper_leg_left": "left_upper_leg",
    "upper_leg_right": "right_upper_leg",
    "jaw_soft": "bottom_head_shell",
}


def _parse_vec3(s: str | None) -> tuple[float, float, float]:
    p = (s or "0 0 0").split()
    if len(p) >= 3:
        return (float(p[0]), float(p[1]), float(p[2]))
    return (0.0, 0.0, 0.0)


def _parse_quat(s: str | None) -> tuple[float, float, float, float]:
    """MJCF quat 属性格式为 'w x y z'（与 BONES quat 元组约定一致）。"""
    p = (s or "1 0 0 0").split()
    if len(p) >= 4:
        return (float(p[0]), float(p[1]), float(p[2]), float(p[3]))
    return (1.0, 0.0, 0.0, 0.0)


def load_stl_binary(path: str) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """解析 binary STL。返回 (vertices, faces)：vertices 按三角形平铺（每面 3 个），
    faces 为 (i, i+1, i+2)。纯 Python（struct），零依赖。"""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 84:
        raise ValueError(f"STL 太短：{path} ({len(data)} 字节)")
    ntri = struct.unpack("<I", data[80:84])[0]
    expected = 84 + ntri * 50
    if len(data) != expected:
        sys.stderr.write(f"[mesh] 警告：{path} 大小 {len(data)} 与预期 {expected} 不符，按 50B/面尽力解析\n")
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for i in range(ntri):
        o = 84 + i * 50
        if o + 48 > len(data):
            break
        tri = struct.unpack("<9f", data[o + 12:o + 48])   # 跳过 3f 法向
        base = len(verts)
        verts.append((tri[0], tri[1], tri[2]))
        verts.append((tri[3], tri[4], tri[5]))
        verts.append((tri[6], tri[7], tri[8]))
        faces.append((base, base + 1, base + 2))
    return verts, faces


@dataclass
class MeshGeom:
    """单个 visual geom：归属 BONES 体、相对 body 的局部 pos/quat、mesh 名、材质颜色。"""
    body: str
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]
    mesh: str
    rgba: tuple[float, float, float, float]


@dataclass
class MeshModel:
    """训练 MJCF 解析结果：geom 列表 + STL 资产目录。提供按 FK 帧变换到世界的接口。"""
    geoms: list[MeshGeom]
    asset_dir: str
    _stl_cache: dict = field(default_factory=dict)        # mesh 名 -> (verts, faces)
    _local_cache: dict = field(default_factory=dict)      # (gi, stride) -> (local_verts, faces)

    def _load_stl(self, mesh_name: str) -> tuple[list, list]:
        if mesh_name in self._stl_cache:
            return self._stl_cache[mesh_name]
        path = os.path.join(self.asset_dir, mesh_name + ".stl")
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        v, f = load_stl_binary(path)
        self._stl_cache[mesh_name] = (v, f)
        return v, f

    def local_geom(self, gi: int, stride: int = 1) -> tuple[list, list]:
        """把 geom 的 STL 顶点经局部 geom_R·v + geom_pos 变换到 body 坐标系（缓存）。"""
        key = (gi, stride)
        if key in self._local_cache:
            return self._local_cache[key]
        g = self.geoms[gi]
        sv, sf = self._load_stl(g.mesh)
        Rg = _quat_to_mat(*g.quat)
        lv: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int]] = []
        for i in range(0, len(sf), stride):
            f = sf[i]
            for idx in f:
                v = sv[idx]
                lv.append((Rg[0][0]*v[0]+Rg[0][1]*v[1]+Rg[0][2]*v[2]+g.pos[0],
                           Rg[1][0]*v[0]+Rg[1][1]*v[1]+Rg[1][2]*v[2]+g.pos[1],
                           Rg[2][0]*v[0]+Rg[2][1]*v[1]+Rg[2][2]*v[2]+g.pos[2]))
            faces.append((len(lv)-3, len(lv)-2, len(lv)-1))
        self._local_cache[key] = (lv, faces)
        return lv, faces

    def world_geom(self, frames: dict, gi: int, stride: int = 1):
        """返回 (world_verts, faces, rgba)：把 body 坐标系下的局部顶点经 FK(body) 摆到世界。"""
        lv, faces = self.local_geom(gi, stride)
        g = self.geoms[gi]
        R, T = frames[g.body]
        wv = _world_points(R, T, lv)
        return wv, faces, g.rgba

    def triangle_count(self, stride: int = 1) -> int:
        total = 0
        for gi in range(len(self.geoms)):
            total += len(self.local_geom(gi, stride)[1])
        return total


def _world_points(R: list, T: tuple, local: list | "object"):
    """world = R·local + T。local 为 list[(x,y,z)] 或 np.ndarray(N,3)。优先 numpy 加速，
    回退纯 Python（无 numpy 时）。返回类型与输入一致（numpy 进 numpy 出，否则 list）。"""
    try:
        import numpy as np
        L = np.asarray(local, dtype=np.float64)
        Rm = np.asarray(R, dtype=np.float64)
        Tm = np.asarray(T, dtype=np.float64)
        return (L @ Rm.T) + Tm
    except Exception:
        out = []
        for (x, y, z) in local:
            out.append((R[0][0]*x+R[0][1]*y+R[0][2]*z+T[0],
                        R[1][0]*x+R[1][1]*y+R[1][2]*z+T[1],
                        R[2][0]*x+R[2][1]*y+R[2][2]*z+T[2]))
        return out


def _subtract_origin(points, origin):
    """把世界点（或 list）平移回以 trunk_base 为原点的显示坐标系，与 forward_kinematics 一致。"""
    ox, oy, oz = origin
    if hasattr(points, "tolist"):   # numpy
        import numpy as np
        return points - np.array([ox, oy, oz], dtype=points.dtype)
    return [(x-ox, y-oy, z-oz) for (x, y, z) in points]


def parse_mjcf_meshes(path: str) -> MeshModel:
    """解析训练版 MJCF，提取 body→geom(mesh) 列表 + asset 材质颜色。

    只取 ``<geom type="mesh">``（视觉几何）；忽略 collision/self_collision 同类 geom
    （它们复用同一 mesh，纯渲染不需要重复画）。body 名经 MESH_BODY_MAP 映射到 BONES 体名。
    """
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    root = ET.parse(path).getroot()
    compiler = root.find("compiler")
    meshdir = (compiler.get("meshdir") if compiler is not None else None) or "assets"
    asset_dir = os.path.join(os.path.dirname(os.path.abspath(path)), meshdir)
    materials: dict[str, tuple[float, float, float, float]] = {}
    asset = root.find("asset")
    if asset is not None:
        for m in asset.findall("material"):
            name = m.get("name")
            rgba_s = m.get("rgba")
            if name and rgba_s:
                try:
                    materials[name] = tuple(float(x) for x in rgba_s.split())
                except Exception:
                    pass
    geoms: list[MeshGeom] = []

    def walk(body):
        bname = body.get("name")
        for g in body.findall("geom"):
            if g.get("type") != "mesh":
                continue
            mname = g.get("mesh")
            if not mname:
                continue
            mat = g.get("material")
            rgba = materials.get(mat, (0.7, 0.7, 0.7, 1.0))
            bones_name = MESH_BODY_MAP.get(bname, bname)
            geoms.append(MeshGeom(bones_name, _parse_vec3(g.get("pos")),
                                  _parse_quat(g.get("quat")), mname, rgba))
        for child in body.findall("body"):
            walk(child)

    wb = root.find("worldbody")
    if wb is not None:
        for top in wb.findall("body"):
            walk(top)
    return MeshModel(geoms, asset_dir)


# ───────────────────────────────────────────────────────────────────────────
# 4. 状态解析（只取查看器需要的字段；空数组/缺失按「未上报」处理，绝不当 0）
# ───────────────────────────────────────────────────────────────────────────
def _as_floats(obj, n: int) -> list[float]:
    v = obj or []
    if len(v) != n:
        v = (list(v) + [0.0]*n)[:n]   # 长度不符：前 n 个保留、其余补 0（解析器标注异常）
    return [float(x) for x in v]


@dataclass
class RobotStateView:
    t: float = 0.0
    policy: str = "?"
    joints: list[float] = field(default_factory=lambda: [0.0]*N)
    targets: list[float] = field(default_factory=lambda: [0.0]*N)
    velocities: list[float] = field(default_factory=list)
    currents_ma: list[float] = field(default_factory=list)
    # —— IMU / 安全（两条线共用接口面；缺失 = None，绝不假装静止） ——
    gravity: tuple[float, float, float] | None = None   # 体坐标重力单位向量 (lib.rs:4008)
    fallen: bool | None = None
    limp: bool | None = None
    imu_stale_blocks: int | None = None                 # robot.health.imu.consecutive_stale_blocks
    imu_healthy: bool | None = None
    # —— 真流里额外可用、monitor 不一定带的字段（缺失 = None） ——
    gyro: tuple[float, float, float] | None = None       # RobotState.gyro: Option<[f64;3]> 原始陀螺, 体坐标 rad/s (lib.rs:2674)
    head: tuple[float, float, float, float] | None = None  # RobotState.head: [f64;4] 头部四元数 (lib.rs:2659)
    odom_pos: tuple[float, float, float] | None = None   # RobotState.odom.position 躯干世界坐标 m (lib.rs:2731)
    odom_yaw: float | None = None                        # RobotState.odom.yaw 航向 rad (lib.rs:2733)
    # —— 装后朝向自检（需在“水平静止”条件下解读；moving/fallen 时不下结论） ——
    mount_check: str | None = None                       # 'ok'/'suspect_mount'/'moving'/'fallen'/'insufficient'


def _gravity_from(obj: dict) -> tuple[float, float, float] | None:
    safety = obj.get("safety")
    if isinstance(safety, dict):
        g = safety.get("gravity")
        if isinstance(g, (list, tuple)) and len(g) == 3:
            return (float(g[0]), float(g[1]), float(g[2]))
    return None


def _imu_health_from(obj: dict) -> tuple[int | None, bool | None]:
    """从 health 报告解析 IMU 健康。兼容两种形状：

    * 真机 ``robotctl health --json`` 输出（HealthReport）：``obj["robot"]["imu"]["consecutive_stale_blocks"]``
      + ``obj["robot"]["healthy"]``（lib.rs:2429 HealthResult / 2544 ImuHealth）。
    * 旧式/demo 把 health 直接放在 monitor 帧顶层 ``obj["health"]["imu"]``（仅 demo/mock 兼容）。
    """
    robot = obj.get("robot")
    if isinstance(robot, dict):                      # 真机 health 报告形状
        imu = robot.get("imu") or {}
        stale = imu.get("consecutive_stale_blocks")
        healthy = robot.get("healthy")
        return (int(stale) if isinstance(stale, (int, float)) else None,
                bool(healthy) if isinstance(healthy, bool) else None)
    health = obj.get("health")                        # 旧式/demo 顶层 health
    if isinstance(health, dict):
        imu = health.get("imu") or {}
        stale = imu.get("consecutive_stale_blocks")
        healthy = health.get("healthy")
        return (int(stale) if isinstance(stale, (int, float)) else None,
                bool(healthy) if isinstance(healthy, bool) else None)
    return None, None


def _gyro_from(obj: dict) -> tuple[float, float, float] | None:
    """RobotState.gyro: Option<[f64;3]>（lib.rs:2674），原始陀螺，体坐标 rad/s。"""
    g = obj.get("gyro")
    if isinstance(g, (list, tuple)) and len(g) == 3:
        return (float(g[0]), float(g[1]), float(g[2]))
    return None


def _head_from(obj: dict) -> tuple[float, float, float, float] | None:
    """RobotState.head: [f64;4]（lib.rs:2659），头部四元数（顺序见真机）。"""
    h = obj.get("head")
    if isinstance(h, (list, tuple)) and len(h) == 4:
        return (float(h[0]), float(h[1]), float(h[2]), float(h[3]))
    return None


def _odom_from(obj: dict) -> tuple[tuple[float, float, float] | None, float | None]:
    """RobotState.odom: {position:[f64;3], yaw:f64}（lib.rs:2729/2731/2733）。"""
    o = obj.get("odom")
    if not isinstance(o, dict):
        return None, None
    p = o.get("position")
    pos = (float(p[0]), float(p[1]), float(p[2])) if isinstance(p, (list, tuple)) and len(p) == 3 else None
    yaw = o.get("yaw")
    yaw = float(yaw) if isinstance(yaw, (int, float)) else None
    return pos, yaw


def parse_state(obj: dict) -> RobotStateView:
    safety = obj.get("safety") if isinstance(obj.get("safety"), dict) else {}
    odom_pos, odom_yaw = _odom_from(obj)
    gravity = _gravity_from(obj)
    gyro = _gyro_from(obj)
    fallen = bool(safety["fallen"]) if isinstance(safety.get("fallen"), bool) else None
    return RobotStateView(
        t=float(obj.get("t", 0.0)),
        policy=str(obj.get("policy", "?")),
        joints=_as_floats(obj.get("joints"), N),
        targets=_as_floats(obj.get("targets"), N),
        velocities=list(obj.get("velocities") or []),
        currents_ma=list(obj.get("currents_ma") or []),
        gravity=gravity,
        fallen=fallen,
        limp=bool(safety.get("limp")) if isinstance(safety.get("limp"), bool) else None,
        imu_stale_blocks=_imu_health_from(obj)[0],
        imu_healthy=_imu_health_from(obj)[1],
        gyro=gyro,
        head=_head_from(obj),
        odom_pos=odom_pos,
        odom_yaw=odom_yaw,
        mount_check=imu_mount_sanity(gravity, gyro, fallen),
    )


def gravity_tilt_deg(gravity: tuple[float, float, float] | None) -> float | None:
    """偏离直立（重力 = [0,0,-1]）的倾角，单位度。缺失返回 None。"""
    if gravity is None:
        return None
    n = math.sqrt(sum(x*x for x in gravity))
    if n < 1e-9:
        return None
    u = [x/n for x in gravity]
    cosang = max(-1.0, min(1.0, u[2] * -1.0))   # dot(g, [0,0,-1])
    return math.degrees(math.acos(cosang))


def imu_mount_sanity(gravity: tuple[float, float, float] | None,
                     gyro: tuple[float, float, float] | None,
                     fallen: bool | None,
                     tilt_tol_deg: float = MOUNT_CHECK_TILT_TOL_DEG,
                     still_thresh: float = GYRO_STILL_RAD_S) -> str | None:
    """装后朝向自检（负对照）。移植自 build-tutorial 的 imu_orientation_check.py：
    该工具在“水平静止”姿态下录 BNO08x 样本，核对 projected_gravity 是否指向 -Z。

    这里用 robotd 已经算好的体坐标 ``safety.gravity`` 做等价判断：

    * gravity 缺失                          → ``insufficient``（数据不足，不当 0）
    * 已倒下 fallen                          → ``fallen``（不是 mount 问题）
    * 无陀螺 / |gyro| 超阈值（运动中）        → ``moving``（动力学倾斜会污染重力，不下结论）
    * 静止且 tilt ≤ 容差                     → ``ok``
    * 静止但 tilt > 容差                     → ``suspect_mount``（安装四元数很可能配错）

    注意：本函数只负责“水平静止”这一前提下的判断；机器人被故意倾斜持握时也会
    显示 suspect_mount，那不是 bug——由操作员结合现场解读。它的价值是抓“配错 mount
    四元数”这类静默错误：配错时即使机器人水平静止，gravity 也会偏。
    """
    if gravity is None:
        return "insufficient"
    if fallen:
        return "fallen"
    if gyro is None:
        return "moving"                       # 无陀螺，无法判断是否静止
    if math.sqrt(sum(x*x for x in gyro)) > still_thresh:
        return "moving"                       # 运动中，重力被动力学倾斜，不能据此判 mount
    tilt = gravity_tilt_deg(gravity)
    if tilt is None:
        return "insufficient"
    return "ok" if tilt <= tilt_tol_deg else "suspect_mount"


# ───────────────────────────────────────────────────────────────────────────
# 5. 本体现网格（纯 Python 圆柱，渲染后端无关；matplotlib/viser 各取所需）
# ───────────────────────────────────────────────────────────────────────────
def cylinder_between(p0: tuple[float, float, float], p1: tuple[float, float, float],
                     radius: float = LINK_RADIUS, segments: int = 12):
    """返回 (vertices, faces)，构成连接 p0→p1 的圆柱。纯 Python，零依赖。"""
    d = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
    L = math.sqrt(sum(x*x for x in d)) or 1e-9
    axis = (d[0]/L, d[1]/L, d[2]/L)
    up = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0)
    # 与 axis 正交的两个基向量
    ux = up[1]*axis[2] - up[2]*axis[1]
    uy = up[2]*axis[0] - up[0]*axis[2]
    uz = up[0]*axis[1] - up[1]*axis[0]
    un = math.sqrt(ux*ux + uy*uy + uz*uz) or 1.0
    u = (ux/un, uy/un, uz/un)
    vx = axis[1]*u[2] - axis[2]*u[1]
    vy = axis[2]*u[0] - axis[0]*u[2]
    vz = axis[0]*u[1] - axis[1]*u[0]
    v = (vx, vy, vz)
    verts: list[tuple[float, float, float]] = []
    for center in (p0, p1):
        for i in range(segments):
            ang = 2.0*math.pi*i/segments
            c, s = math.cos(ang), math.sin(ang)
            verts.append((center[0] + radius*(c*u[0] + s*v[0]),
                          center[1] + radius*(c*u[1] + s*v[1]),
                          center[2] + radius*(c*u[2] + s*v[2])))
    faces: list[tuple[int, int, int]] = []
    n = segments
    for i in range(segments):
        j = (i+1) % segments
        faces.append((i, j, j+n))          # 侧面三角形
        faces.append((i, j+n, i+n))
    bc = len(verts); verts.append(p0)      # 底盖
    tc = len(verts); verts.append(p1)      # 顶盖
    for i in range(segments):
        j = (i+1) % segments
        faces.append((bc, j, i))           # 底盖
        faces.append((tc, n+i, n+j))       # 顶盖
    return verts, faces


def link_meshes(positions: dict[str, tuple[float, float, float]]) -> list[tuple[list, list, float]]:
    """返回 [(vertices, faces, radius), ...] 每条边一个圆柱。"""
    out = []
    for child, parent in EDGES:
        if child not in positions or parent not in positions:
            continue
        r = TORSO_RADIUS if child in TORSO_EDGES else LINK_RADIUS
        verts, faces = cylinder_between(positions[parent], positions[child], r)
        out.append((verts, faces, r))
    return out


# ───────────────────────────────────────────────────────────────────────────
# 6. 渲染后端（可插拔）
# ───────────────────────────────────────────────────────────────────────────
def _fmt_imu(st: RobotStateView) -> str:
    g = st.gravity
    tilt = gravity_tilt_deg(g)
    parts = []
    if g is not None:
        parts.append(f"gravity=({g[0]:+.2f},{g[1]:+.2f},{g[2]:+.2f})")
        parts.append(f"tilt={tilt:.1f}°" if tilt is not None else "tilt=?")
    else:
        parts.append("gravity=n/a")
    if st.fallen is not None:
        parts.append(f"fallen={st.fallen}")
    if st.limp is not None:
        parts.append(f"limp={st.limp}")
    if st.imu_stale_blocks is not None:
        parts.append(f"imu_stale={st.imu_stale_blocks}")
    elif st.imu_healthy is not None:
        parts.append(f"imu_healthy={st.imu_healthy}")
    else:
        parts.append("imu_health=n/a(robot.health)")
    if st.gyro is not None:
        parts.append(f"gyro=({st.gyro[0]:+.1f},{st.gyro[1]:+.1f},{st.gyro[2]:+.1f})rad/s")
    if st.odom_pos is not None:
        p = st.odom_pos
        parts.append(f"odom=({p[0]:+.2f},{p[1]:+.2f},{p[2]:+.2f})m")
    if st.odom_yaw is not None:
        parts.append(f"yaw={math.degrees(st.odom_yaw):.0f}°")
    if st.mount_check is not None:
        tag = "⚠MOUNT?" if st.mount_check == "suspect_mount" else st.mount_check
        parts.append(f"mount={tag}")
    return "  ".join(parts)


class HeadlessViewer:
    """无图形依赖：每帧打印关节角/目标/误差 + 重力/IMU 健康。"""
    def __init__(self): pass
    def frame(self, st: RobotStateView) -> None:
        print(f"t={st.t:.2f} policy={st.policy}  (headless)")
        max_err = 0.0
        for i, name in enumerate(JOINT_NAMES):
            err = st.targets[i] - st.joints[i]
            max_err = max(max_err, abs(err))
            print(f"  {name:16s} j={st.joints[i]:+7.3f} tgt={st.targets[i]:+7.3f} "
                  f"err={err:+7.3f}")
        print(f"  max_track_err={max_err:.3f} rad")
        print(f"  {_fmt_imu(st)}")
    def close(self): pass


class MatplotlibViewer:
    """matplotlib 3D 本体现：真实 STL 零件（无源时退化为连杆圆柱）+ 关节球 + 体坐标重力箭头 + HUD。"""
    def __init__(self, interval_ms: int = 100, mesh_model=None, mesh_stride: int = 4):
        import matplotlib.pyplot as plt  # noqa: PLC0415
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: F401, PLC0415
        self.plt = plt
        self.Poly3DCollection = Poly3DCollection
        self.fig = plt.figure(figsize=(8, 7))
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.ax.set_title("MicroDuck HD-1910 live pose")
        self.text = self.ax.text2D(0.02, 0.96, "", transform=self.ax.transAxes, fontsize=9)
        self.interval = interval_ms
        self._agg = self.plt.get_backend().lower() == "agg"
        self.mesh_model = mesh_model
        # matplotlib 3D 非 GPU 加速：三角形过多会掉帧。按预算自动提高 stride，
        # 保证 matplotlib 端总三角面 ≤ ~120k（用户 --mesh-stride 更低也不会更细，
        # viser 端不受影响，仍可用 --mesh-stride 1 拿全分辨率）。
        if mesh_model is not None:
            budget = 120000
            total1 = mesh_model.triangle_count(1)
            auto = max(1, (total1 + budget - 1) // budget)
            self.mesh_stride = max(mesh_stride, auto)
        else:
            self.mesh_stride = mesh_stride

    def _add_mesh_collection(self, wv, faces, rgba):
        # 向量化：numpy 时直接用 wv[faces] 得到 (n,3,3)，避免 Python 层逐面建列表。
        try:
            import numpy as np
            wv_np = np.asarray(wv, dtype=np.float64)
            faces_np = np.asarray(faces, dtype=np.int64)
            tris = wv_np[faces_np]          # (n_tri, 3, 3)
            poly = self.Poly3DCollection(tris, facecolors=rgba,
                                         edgecolors=(rgba[0], rgba[1], rgba[2], 0.25),
                                         linewidths=0.15)
        except Exception:
            poly = self.Poly3DCollection(
                [[wv[a], wv[b], wv[c]] for a, b, c in faces],
                facecolors=rgba, edgecolors=(rgba[0], rgba[1], rgba[2], 0.25), linewidths=0.15)
        self.ax.add_collection3d(poly)

    def frame(self, st: RobotStateView) -> None:
        import numpy as np  # noqa: PLC0415
        pos = forward_kinematics(st.joints)
        self.ax.cla()
        self.ax.set_box_aspect((1, 1, 1.4))
        self.ax.set_xlim(-0.2, 0.2); self.ax.set_ylim(-0.2, 0.2); self.ax.set_zlim(-0.15, 0.25)
        if self.mesh_model is not None:
            # 真实 STL 外形：用 FK 世界帧把每个 geom 摆到世界，再减 trunk_base 原点对齐显示
            frames = forward_frames(st.joints)
            origin = frames["trunk_base"][1]
            total = 0
            for gi in range(len(self.mesh_model.geoms)):
                wv, faces, rgba = self.mesh_model.world_geom(frames, gi, self.mesh_stride)
                wv = _subtract_origin(wv, origin)
                self._add_mesh_collection(wv, faces, rgba)
                total += len(faces)
            self._mesh_total = total
        else:
            # 占位圆柱（本体现）
            for verts, faces, _ in link_meshes(pos):
                poly = self.Poly3DCollection(
                    [[verts[a] for a in f] for f in faces],
                    facecolors=(0.30, 0.55, 0.85, 0.85), edgecolors=(0.1, 0.2, 0.4, 0.4), linewidths=0.3)
                self.ax.add_collection3d(poly)
        # 关节球
        xs = [pos[n][0] for n in pos]; ys = [pos[n][1] for n in pos]; zs = [pos[n][2] for n in pos]
        self.ax.scatter(xs, ys, zs, c="orange", s=22, depthshade=True)
        # 目标姿态细线叠加（若有偏差）
        if any(abs(st.targets[i]-st.joints[i]) > 1e-3 for i in range(N)):
            pt = forward_kinematics(st.targets)
            xt, yt, zt = _draw_edges(pt)
            self.ax.plot(xt, yt, zt, "--", color="green", lw=1, alpha=0.5)
        # 体坐标重力箭头（红），锚在 trunk 原点
        g = st.gravity
        if g is not None:
            n = math.sqrt(sum(x*x for x in g)) or 1.0
            L = 0.18
            self.ax.quiver(0, 0, 0, g[0]/n*L, g[1]/n*L, g[2]/n*L,
                           color="red", lw=2.5, arrow_length_ratio=0.18)
        # 原始陀螺箭头（青），体坐标角速度方向（限幅，避免大角速度撑爆画面）
        gy = st.gyro
        if gy is not None:
            gm = math.sqrt(sum(x*x for x in gy)) or 1e-9
            Lg = min(0.14, 0.03 * gm)
            if Lg > 1e-4:
                self.ax.quiver(0, 0, 0, gy[0]/gm*Lg, gy[1]/gm*Lg, gy[2]/gm*Lg,
                               color="cyan", lw=1.8, arrow_length_ratio=0.2)
        self.ax.set_xlabel("X (forward)"); self.ax.set_ylabel("Y (left)")
        self.ax.set_zlabel("Z (up)")
        mesh_tag = ""
        if self.mesh_model is not None:
            mesh_tag = f"  [mesh {getattr(self, '_mesh_total', 0)} tris]"
        else:
            mesh_tag = "  [cylinder]"
        self.text.set_text(f"policy={st.policy} t={st.t:.2f}s{mesh_tag}\n{_fmt_imu(st)}")
        if not self._agg:
            self.plt.pause(self.interval/1000.0)

    def close(self):
        if not self._agg:
            self.plt.show(block=False)


class ViserViewer:
    """浏览器 3D（viser，若已装）：真实 STL 零件（无源时退化为圆柱）+ 关节点 + 重力线 + 可旋转缩放。"""
    def __init__(self, port: int = 8012, mesh_model=None, mesh_stride: int = 1):
        import viser  # noqa: PLC0415
        self.sv = viser.ViserServer(port=port)
        self.mesh_handles: dict[str, object] = {}
        self.joint_handles: dict[str, object] = {}
        self.grav_handle = None
        self.gyro_handle = None
        self.mesh_model = mesh_model
        self.mesh_stride = mesh_stride

    def _ensure(self, name, parent, p):
        jh = self.joint_handles.get(name)
        if jh is None:
            try:
                jh = self.sv.scene.add_point(name + "_j", color=(1.0, 0.6, 0.1))
                self.joint_handles[name] = jh
            except Exception:
                jh = None
        if jh is not None:
            try:
                jh.position = (p[0], p[1], p[2])
            except Exception:
                pass

    def frame(self, st: RobotStateView) -> None:
        import numpy as np  # noqa: PLC0415
        pos = forward_kinematics(st.joints)
        if self.mesh_model is not None:
            # 真实 STL 外形：FK 世界帧摆每个 geom，减 trunk_base 原点对齐显示
            frames = forward_frames(st.joints)
            origin = frames["trunk_base"][1]
            for gi in range(len(self.mesh_model.geoms)):
                wv, faces, rgba = self.mesh_model.world_geom(frames, gi, self.mesh_stride)
                wv = _subtract_origin(wv, origin)
                verts_np = np.array(wv, dtype=np.float32)
                faces_np = np.array(faces, dtype=np.int32)
                key = f"mesh_{gi}"
                h = self.mesh_handles.get(key)
                try:
                    if h is None:
                        h = self.sv.scene.add_mesh(key, vertices=verts_np, faces=faces_np,
                                                  color=rgba[:3])
                        self.mesh_handles[key] = h
                    else:
                        h.vertices = verts_np
                        h.faces = faces_np
                except Exception:
                    pass  # viser API 差异时静默跳过网格，不影响关节点
        else:
            # 占位圆柱（无 mesh 源）
            for child, parent in EDGES:
                if child not in pos or parent not in pos:
                    continue
                r = TORSO_RADIUS if child in TORSO_EDGES else LINK_RADIUS
                verts, faces = cylinder_between(pos[parent], pos[child], r)
                verts_np = np.array(verts, dtype=np.float32)
                faces_np = np.array(faces, dtype=np.int32)
                h = self.mesh_handles.get(child)
                try:
                    if h is None:
                        h = self.sv.scene.add_mesh(child, vertices=verts_np, faces=faces_np,
                                                  color=(0.30, 0.55, 0.85))
                        self.mesh_handles[child] = h
                    else:
                        h.vertices = verts_np
                        h.faces = faces_np
                except Exception:
                    pass  # viser API 差异时静默跳过网格，不影响关节点
        # 关节点（始终画，帮助看关节）
        for name in pos:
            self._ensure(name, None, pos[name])
        # 重力线（红），trunk 原点 → 重力方向
        g = st.gravity
        if g is not None:
            try:
                n = math.sqrt(sum(x*x for x in g)) or 1.0
                L = 0.18
                end = (g[0]/n*L, g[1]/n*L, g[2]/n*L)
                if self.grav_handle is None:
                    self.grav_handle = self.sv.scene.add_line(
                        "gravity", start=(0.0, 0.0, 0.0), end=end, color=(1.0, 0.1, 0.1), width=4)
                else:
                    self.grav_handle.end = end
            except Exception:
                pass
        # 原始陀螺线（青），体坐标角速度方向（限幅）
        gy = st.gyro
        if gy is not None:
            try:
                gm = math.sqrt(sum(x*x for x in gy)) or 1e-9
                Lg = min(0.14, 0.03 * gm)
                if Lg > 1e-4:
                    end = (gy[0]/gm*Lg, gy[1]/gm*Lg, gy[2]/gm*Lg)
                    if self.gyro_handle is None:
                        self.gyro_handle = self.sv.scene.add_line(
                            "gyro", start=(0.0, 0.0, 0.0), end=end, color=(0.1, 0.9, 0.9), width=3)
                    else:
                        self.gyro_handle.end = end
            except Exception:
                pass
        # HUD
        try:
            self.sv.scene.add_label("imu", _fmt_imu(st), position=(0.0, 0.0, 0.26))
        except Exception:
            pass

    def close(self): pass


def _draw_edges(positions: dict[str, tuple[float, float, float]]):
    xs, ys, zs = [], [], []
    for child, parent in EDGES:
        if child not in positions or parent not in positions:
            continue
        a = positions[parent]; b = positions[child]
        xs += [a[0], b[0], None]; ys += [a[1], b[1], None]; zs += [a[2], b[2], None]
    return xs, ys, zs


def make_viewer(kind: str, interval_ms: int, mesh_model=None, mesh_stride: int = 4) -> "object":
    if kind == "headless":
        return HeadlessViewer()
    if kind == "matplotlib":
        return MatplotlibViewer(interval_ms, mesh_model=mesh_model, mesh_stride=mesh_stride)
    if kind == "viser":
        return ViserViewer(mesh_model=mesh_model, mesh_stride=mesh_stride)
    # auto
    try:
        return ViserViewer(mesh_model=mesh_model, mesh_stride=mesh_stride)
    except Exception:
        pass
    try:
        return MatplotlibViewer(interval_ms, mesh_model=mesh_model, mesh_stride=mesh_stride)
    except Exception:
        return HeadlessViewer()


# ───────────────────────────────────────────────────────────────────────────
# 7. 数据源
# ───────────────────────────────────────────────────────────────────────────
def run_stdin(viewer) -> None:
    """从 stdin 读逐行 JSON（robotctl monitor --json 的逐帧输出，或 ssh 管道）。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "joints" not in obj:   # 可能是连接横幅等非状态行
            continue
        viewer.frame(parse_state(obj))


def _apply_health(st: "RobotStateView", store: dict) -> None:
    """把 health 轮询结果合并进当前帧（robot.health 是独立 RPC，不在 monitor 流里）。"""
    if store.get("stale") is not None or store.get("healthy") is not None:
        st.imu_stale_blocks = store.get("stale")
        st.imu_healthy = store.get("healthy")


def _health_collector(cmd: list[str], store: dict, stop: "threading.Event",
                      period: float = 1.5) -> None:
    """后台线程：周期性跑 `robotctl health --json`（或 ssh 变体），解析后写入 store。

    monitor 流（RobotState）不含 health，IMU 健康必须经这条独立 RPC 取到
    （lib.rs:2429 HealthResult / 2544 ImuHealth）。解析失败/超时则保留上一帧值。
    """
    while not stop.is_set():
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, timeout=5)
            if proc.returncode == 0:
                try:
                    rep = json.loads(proc.stdout)
                    stale, healthy = _imu_health_from(rep)
                    store["stale"] = stale
                    store["healthy"] = healthy
                except Exception:
                    pass
        except Exception:
            pass
        stop.wait(period)


def run_robotctl(viewer, host: str | None = None) -> None:
    """经 robotctl 走 WebRTC relay 拉真机流（robotctl monitor --json）。

    生产路径：operator PC 上 ``robotctl`` 通过 mediad 的 WebRTC relay 连到机器人，
    吐降采样 10 Hz 的 RobotState（含 safety.gravity / gyro / head / odom，lib.rs:2651）。
    IMU 健康（robot.health）是 **独立 RPC**，monitor 流不带它，所以另起后台线程周期性
    跑 ``robotctl health --json`` 并把 ``robot.imu.consecutive_stale_blocks`` /
    ``robot.healthy`` 合并进每帧（lib.rs:2429/2544）。
    --host 指定时走 ``ssh <host> 'robotctl monitor --json'``（需在 ~/.ssh 配置好）。
    """
    if host:
        monitor_cmd = ["ssh", host, "robotctl monitor --json"]
        health_cmd = ["ssh", host, "robotctl health --json"]
    else:
        rc = shutil.which("robotctl")
        if rc is None:
            sys.exit("robotctl 不在 PATH：请先装好 robotctl，"
                     "或改用 `ssh <host> 'robotctl monitor --json' | python live_viewer.py --source stdin`")
        monitor_cmd = ["robotctl", "monitor", "--json"]
        health_cmd = ["robotctl", "health", "--json"]
    print(f"启动真机流：{' '.join(monitor_cmd)}  (Ctrl-C 退出)", file=sys.stderr)
    print(f"后台轮询健康：{' '.join(health_cmd)}  (1.5s)", file=sys.stderr)
    health_store: dict = {"stale": None, "healthy": None}
    stop = threading.Event()
    th = threading.Thread(target=_health_collector, args=(health_cmd, health_store, stop),
                         daemon=True)
    th.start()
    proc = subprocess.Popen(monitor_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "joints" not in obj:
                continue
            st = parse_state(obj)
            _apply_health(st, health_store)
            viewer.frame(st)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        proc.terminate()
        th.join(timeout=2)


def iter_mock_frames(seconds: float = 6.0, dt: float = 0.1):
    """生成合成“真机流”帧（与 ``robotctl monitor --json`` 同 JSON 形状，**不含 health**）。

    纯生成器，yield 每个 monitor 帧的 dict。供 ``run_mock_relay``（实时渲染）与
    ``capture_live.py``（落盘）共用，确保合成数据只有一份真相。
    关键点：monitor 流 **不带 health**（health 是独立 robot.health RPC），所以这里也不放。
    合成内容：关节缓慢摆动（类行走）+ 倾斜重力 + 原始陀螺 + 头部四元数 + 里程。
    """
    t = 0.0
    while t < seconds:
        w = 0.18 * math.sin(t * 1.3)
        angles = list(REST_POSITION)
        # 左/右腿相位相反的摆动
        angles[2] += w; angles[3] += -w*0.6; angles[4] += w*0.5
        angles[12] += -w; angles[13] += w*0.6; angles[14] += -w*0.5
        # 倾斜重力：绕 Y 轴缓慢偏，再绕 X 轻微偏，保持单位向量
        ay, ax = 0.25*math.sin(t*0.7), 0.12*math.cos(t*0.5)
        g = (math.sin(ax), math.sin(ay)*math.cos(ax), -math.cos(ay)*math.cos(ax))
        fallen = bool(abs(ay) > 0.9)
        # 原始陀螺（体坐标，rad/s）：随摆动产生绕 X 的角速度
        gyro = (0.18*1.3*math.cos(t*1.3), 0.0, 0.0)
        # 头部四元数（绕 Z 缓慢偏航，wxyz）
        hy = 0.3*math.sin(t*0.4)
        head = (math.cos(hy/2), 0.0, 0.0, math.sin(hy/2))
        # 里程：躯干沿 X 缓慢前进 + 航向
        odom = {"position": [0.05*t, 0.0, 0.0], "yaw": 0.1*math.sin(t*0.3)}
        # monitor 帧：只含 RobotState 真实字段（无 health）
        yield {
            "t": round(t, 2), "policy": "walk",
            "joints": angles, "targets": list(REST_POSITION),
            "safety": {"gravity": list(g), "fallen": fallen, "limp": False},
            "gyro": list(gyro), "head": list(head), "odom": odom,
        }
        t += dt


def mock_health_report(stale: int = 2, healthy: bool = True) -> dict:
    """合成一条 ``robotctl health --json`` 报告（真实形状：report.robot.imu...）。"""
    return {"robot": {"healthy": healthy,
                      "imu": {"ready": True, "stale_blocks": stale,
                              "consecutive_stale_blocks": stale}},
            "software": {}, "camera": {}}


def run_mock_relay(viewer, seconds: float = 6.0) -> None:
    """本地无机器人时，合成一套“真机流”帧（与 robotctl monitor --json 同 JSON 形状），
    用于端到端验证解析 + 重力/IMU 健康 + gyro/head/odom + mesh 渲染。

    注意：这是 **真机流的仿真**，不是真机。真机用 --source robotctl（见 run_robotctl）。
    关键点：monitor 流 **不带 health**（health 是独立 robot.health RPC），所以这里也不在
    monitor 帧里放 health；IMU 健康改为模拟“health 轮询结果”直接合并进帧，走与
    run_robotctl 完全相同的 _apply_health 合并路径。周期性出现 0..3 个过期块。
    """
    print("MOCK relay（仿真真机流，非真机）：合成关节摆动 + 倾斜重力 + gyro/head/odom + IMU 过期块",
          file=sys.stderr)
    for obj in iter_mock_frames(seconds, 0.1):
        st = parse_state(obj)
        # 模拟 health 轮询结果（真实路径由 run_robotctl 后台线程写入，这里直接给）
        stale = int((obj["t"] // 1.5) % 4)        # 周期性出现 0..3 个过期块
        st.imu_stale_blocks = stale
        st.imu_healthy = True
        viewer.frame(st)
        time.sleep(0.1 * 0.05)   # 加速演示，不必等满 6s 实时


def run_demo(viewer) -> None:
    """无真机：循环演示静止姿（含直立重力 + 健康 IMU）。"""
    st = parse_state({
        "joints": list(REST_POSITION), "targets": list(REST_POSITION),
        "policy": "stand", "t": 0.0,
        "safety": {"gravity": [0.0, 0.0, -1.0], "fallen": False, "limp": False},
        "health": {"healthy": True, "imu": {"consecutive_stale_blocks": 0}},
    })
    for _ in range(3):
        viewer.frame(st)
        time.sleep(0.3)


# ───────────────────────────────────────────────────────────────────────────
# 8. 入口
# ───────────────────────────────────────────────────────────────────────────
def _default_mjcf_path() -> str | None:
    """自动定位 vendored 训练版 MJCF（含真实 mesh）。找不到返回 None（退化圆柱）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(here, "..", "..", ".upstream", "hd1910m", "microduck_rl",
                        "src", "mjlab_microduck", "robot", "microduck", "robot_walk.xml")
    if os.path.exists(cand):
        return os.path.abspath(cand)
    import glob as _glob
    matches = _glob.glob(os.path.join(here, "..", "..", ".upstream", "hd1910m", "**",
                                      "robot", "microduck", "robot_walk.xml"), recursive=True)
    return os.path.abspath(matches[0]) if matches else None


def _load_mesh_model(a) -> object:
    """按 --mesh-source / --mesh-mode 解析并返回 MeshModel；不适用时返回 None（退化圆柱）。"""
    if a.mesh_mode == "cylinder":
        return None
    src = a.mesh_source
    if src in ("auto", None):
        mjcf = _default_mjcf_path()
    else:
        mjcf = src
    if not mjcf or not os.path.exists(mjcf):
        if src not in ("auto", None):
            print(f"[mesh] 指定 MJCF 不存在：{mjcf}，退化圆柱", file=sys.stderr)
        else:
            print("[mesh] 未找到 vendored 训练 MJCF，退化圆柱（占位）", file=sys.stderr)
        return None
    try:
        model = parse_mjcf_meshes(mjcf)
        print(f"已加载真实 MJCF mesh：{mjcf}\n"
              f"  geom 数={len(model.geoms)} 全分辨率三角面≈{model.triangle_count(1)} "
              f"（stride={a.mesh_stride} → ≈{model.triangle_count(a.mesh_stride)}）",
              file=sys.stderr)
        return model
    except Exception as e:  # 解析/读 STL 失败：诚实退化，不静默假装成功
        print(f"[mesh] 解析失败，退化圆柱：{e}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="MicroDuck HD-1910 真机 3D 姿态查看器")
    ap.add_argument("--source", choices=["stdin", "demo", "robotctl", "mock-relay"], default="demo",
                    help="stdin=从 robotctl monitor --json 管道读; demo=静止姿; "
                         "robotctl=经 WebRTC relay 拉真机流; mock-relay=本地仿真真机流(验证用)")
    ap.add_argument("--demo", action="store_true", help="等价于 --source demo")
    ap.add_argument("--host", default=None, help="robotctl 经 ssh 的远端主机（--source robotctl）")
    ap.add_argument("--renderer", default="auto",
                    choices=["auto", "matplotlib", "viser", "headless"])
    ap.add_argument("--interval-ms", type=int, default=100)
    ap.add_argument("--mesh-source", default="auto",
                    help="训练版 MJCF 路径（含真实 STL）；auto=自动找 vendored；none=禁用 mesh")
    ap.add_argument("--mesh-mode", default="auto", choices=["auto", "mesh", "cylinder"],
                    help="auto=有源用 mesh 否则圆柱; mesh=强制 mesh(无源则警告); cylinder=强制圆柱")
    ap.add_argument("--mesh-stride", type=int, default=4,
                    help="STL 三角面降采样步长(每 N 个面取 1)；越大越省算力(matplotlib 默认 4)")
    a = ap.parse_args()
    if a.demo:
        a.source = "demo"
    if a.mesh_source == "none":
        a.mesh_mode = "cylinder"

    mesh_model = _load_mesh_model(a)
    viewer = make_viewer(a.renderer, a.interval_ms, mesh_model=mesh_model, mesh_stride=a.mesh_stride)
    try:
        if a.source == "stdin":
            print("从 stdin 读取 robotctl monitor --json 帧… (Ctrl-C 退出)", file=sys.stderr)
            run_stdin(viewer)
        elif a.source == "robotctl":
            run_robotctl(viewer, a.host)
        elif a.source == "mock-relay":
            run_mock_relay(viewer)
        else:
            run_demo(viewer)
    except KeyboardInterrupt:
        pass
    finally:
        viewer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
