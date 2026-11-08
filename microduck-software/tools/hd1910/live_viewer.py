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
  * IMU 健康：``robot.health`` RPC 返回 ``imu.consecutive_stale_blocks``（过期块计数）。
    monitor 流不一定带 ``health``，查看器防御性解析 ``state.health.imu.consecutive_stale_blocks``，
    缺失时标注 "n/a (use robot.health)"。
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

设计要点
--------
  * 零重依赖也能跑：FK 用纯 Python 四元数，headless 只打印。matplotlib/viser 可选（lazy import）。
  * matplotlib 用 Poly3DCollection 画连杆圆柱 + 关节球 + 体坐标重力箭头（本体现）；
    viser 用 add_mesh 圆柱 + 关节点 + 重力线（浏览器可旋转缩放）。
  * 关节 ID 体系严格用我们的「1–15 物理 ID + 左腿优先名序」，不混入官方 10–14/20–24/30–34。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
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


def forward_kinematics(angles: list[float]) -> dict[str, tuple[float, float, float]]:
    """angles: 长度 15，下标对应 JOINT_NAMES。返回每个 BONE 原点的世界坐标（相对 trunk_base）。"""
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
    origin = frames["trunk_base"][1]
    return {name: (f[1][0]-origin[0], f[1][1]-origin[1], f[1][2]-origin[2]) for name, f in frames.items()}


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


def _gravity_from(obj: dict) -> tuple[float, float, float] | None:
    safety = obj.get("safety")
    if isinstance(safety, dict):
        g = safety.get("gravity")
        if isinstance(g, (list, tuple)) and len(g) == 3:
            return (float(g[0]), float(g[1]), float(g[2]))
    return None


def _imu_health_from(obj: dict) -> tuple[int | None, bool | None]:
    health = obj.get("health")
    if not isinstance(health, dict):
        return None, None
    imu = health.get("imu") or {}
    stale = imu.get("consecutive_stale_blocks")
    healthy = health.get("healthy")
    return (int(stale) if isinstance(stale, (int, float)) else None,
            bool(healthy) if isinstance(healthy, bool) else None)


def parse_state(obj: dict) -> RobotStateView:
    safety = obj.get("safety") if isinstance(obj.get("safety"), dict) else {}
    return RobotStateView(
        t=float(obj.get("t", 0.0)),
        policy=str(obj.get("policy", "?")),
        joints=_as_floats(obj.get("joints"), N),
        targets=_as_floats(obj.get("targets"), N),
        velocities=list(obj.get("velocities") or []),
        currents_ma=list(obj.get("currents_ma") or []),
        gravity=_gravity_from(obj),
        fallen=bool(safety["fallen"]) if isinstance(safety.get("fallen"), bool) else None,
        limp=bool(safety.get("limp")) if isinstance(safety.get("limp"), bool) else None,
        imu_stale_blocks=_imu_health_from(obj)[0],
        imu_healthy=_imu_health_from(obj)[1],
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
    """matplotlib 3D 本体现：连杆圆柱 + 关节球 + 体坐标重力箭头 + HUD。"""
    def __init__(self, interval_ms: int = 100):
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

    def frame(self, st: RobotStateView) -> None:
        import numpy as np  # noqa: PLC0415
        pos = forward_kinematics(st.joints)
        self.ax.cla()
        self.ax.set_box_aspect((1, 1, 1.4))
        self.ax.set_xlim(-0.2, 0.2); self.ax.set_ylim(-0.2, 0.2); self.ax.set_zlim(-0.15, 0.25)
        # 连杆圆柱（本体现）
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
            xt, yt, zt, _ = _draw_edges(pt)
            self.ax.plot(xt, yt, zt, "--", color="green", lw=1, alpha=0.5)
        # 体坐标重力箭头（红），锚在 trunk 原点
        g = st.gravity
        if g is not None:
            n = math.sqrt(sum(x*x for x in g)) or 1.0
            L = 0.18
            self.ax.quiver(0, 0, 0, g[0]/n*L, g[1]/n*L, g[2]/n*L,
                           color="red", lw=2.5, arrow_length_ratio=0.18)
        self.ax.set_xlabel("X (forward)"); self.ax.set_ylabel("Y (left)")
        self.ax.set_zlabel("Z (up)")
        self.text.set_text(f"policy={st.policy} t={st.t:.2f}s\n{_fmt_imu(st)}")
        if not self._agg:
            self.plt.pause(self.interval/1000.0)

    def close(self):
        if not self._agg:
            self.plt.show(block=False)


class ViserViewer:
    """浏览器 3D（viser，若已装）：圆柱网格 + 关节点 + 重力线 + 可旋转缩放。"""
    def __init__(self, port: int = 8012):
        import viser  # noqa: PLC0415
        self.sv = viser.ViserServer(port=port)
        self.mesh_handles: dict[str, object] = {}
        self.joint_handles: dict[str, object] = {}
        self.grav_handle = None

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
            self._ensure(child, parent, pos[child])
            self._ensure(parent, None, pos[parent])
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


def make_viewer(kind: str, interval_ms: int) -> "object":
    if kind == "headless":
        return HeadlessViewer()
    if kind == "matplotlib":
        return MatplotlibViewer(interval_ms)
    if kind == "viser":
        return ViserViewer()
    # auto
    try:
        return ViserViewer()
    except Exception:
        pass
    try:
        return MatplotlibViewer(interval_ms)
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


def run_robotctl(viewer, host: str | None = None) -> None:
    """经 robotctl 走 WebRTC relay 拉真机流（robotctl monitor --json）。

    生产路径：operator PC 上 ``robotctl`` 通过 mediad 的 WebRTC relay 连到机器人，
    吐降采样 10 Hz 的 RobotState。本函数把它作为子进程拉起、逐行喂给查看器。
    --host 指定时走 ``ssh <host> 'robotctl monitor --json'``（需在 ~/.ssh 配置好）。
    """
    if host:
        cmd = ["ssh", host, "robotctl monitor --json"]
    else:
        rc = shutil.which("robotctl")
        if rc is None:
            sys.exit("robotctl 不在 PATH：请先用 `pip install`/官方方式装好 robotctl，"
                     "或改用 `ssh <host> 'robotctl monitor --json' | python live_viewer.py --source stdin`")
        cmd = ["robotctl", "monitor", "--json"]
    print(f"启动真机流：{' '.join(cmd)}  (Ctrl-C 退出)", file=sys.stderr)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
            viewer.frame(parse_state(obj))
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


def run_mock_relay(viewer, seconds: float = 6.0) -> None:
    """本地无机器人时，合成一套“真机流”帧（与 robotctl monitor --json 同 JSON 形状），
    用于端到端验证解析 + 重力/IMU 健康 + mesh 渲染。

    注意：这是 **真机流的仿真**，不是真机。真机用 --source robotctl（见 run_robotctl）。
    合成内容：关节缓慢摆动（类行走）+ 重力随姿态倾斜 + IMU 周期性出现过期块。
    """
    print("MOCK relay（仿真真机流，非真机）：合成关节摆动 + 倾斜重力 + IMU 过期块", file=sys.stderr)
    t = 0.0
    dt = 0.1
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
        stale = int((t // 1.5) % 4)        # 周期性出现 0..3 个过期块
        obj = {
            "t": round(t, 2), "policy": "walk",
            "joints": angles, "targets": list(REST_POSITION),
            "safety": {"gravity": list(g), "fallen": fallen, "limp": False},
            "health": {"healthy": True, "imu": {"consecutive_stale_blocks": stale}},
        }
        viewer.frame(parse_state(obj))
        t += dt
        time.sleep(dt * 0.05)   # 加速演示，不必等满 6s 实时


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
    a = ap.parse_args()
    if a.demo:
        a.source = "demo"

    viewer = make_viewer(a.renderer, a.interval_ms)
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
