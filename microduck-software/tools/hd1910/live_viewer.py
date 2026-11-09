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
  * matplotlib 用 Poly3DCollection 画连杆圆柱 + 关节球 + 体坐标重力箭头（红）/陀螺箭头（青）（本体现）；
    viser 用 add_mesh 圆柱 + 关节点 + 重力线 + 陀螺线（浏览器可旋转缩放）。HUD 同时显示
    gravity/tilt/gyro/odom/IMU 健康等标量。
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
    # —— 真流里额外可用、monitor 不一定带的字段（缺失 = None） ——
    gyro: tuple[float, float, float] | None = None       # RobotState.gyro: Option<[f64;3]> 原始陀螺, 体坐标 rad/s (lib.rs:2674)
    head: tuple[float, float, float, float] | None = None  # RobotState.head: [f64;4] 头部四元数 (lib.rs:2659)
    odom_pos: tuple[float, float, float] | None = None   # RobotState.odom.position 躯干世界坐标 m (lib.rs:2731)
    odom_yaw: float | None = None                        # RobotState.odom.yaw 航向 rad (lib.rs:2733)


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
        gyro=_gyro_from(obj),
        head=_head_from(obj),
        odom_pos=odom_pos,
        odom_yaw=odom_yaw,
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
    if st.gyro is not None:
        parts.append(f"gyro=({st.gyro[0]:+.1f},{st.gyro[1]:+.1f},{st.gyro[2]:+.1f})rad/s")
    if st.odom_pos is not None:
        p = st.odom_pos
        parts.append(f"odom=({p[0]:+.2f},{p[1]:+.2f},{p[2]:+.2f})m")
    if st.odom_yaw is not None:
        parts.append(f"yaw={math.degrees(st.odom_yaw):.0f}°")
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
        self.gyro_handle = None

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
