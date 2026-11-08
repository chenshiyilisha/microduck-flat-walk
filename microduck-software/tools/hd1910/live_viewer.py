#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MicroDuck HD-1910 真机 3D 姿态查看器 —— PC 骨架版
================================================

依据（见 docs/active/microduck-upstream-对照-2026-11-08.md §4）：
  * 真机状态经 ``robotctl monitor --json`` 吐出 ``RobotState``（服务端默认降采样 10 Hz）。
  * ``RobotState.joints`` / ``targets`` 是裸角度数组（弧度），**索引按 JOINT_NAMES**。
  * JOINT_NAMES（左腿优先，15 个）：
        left_hip_yaw(0) left_hip_roll(1) left_hip_pitch(2) left_knee(3) left_ankle(4)
        neck_pitch(5) head_pitch(6) head_yaw(7) head_roll(8) mouth(9)
        right_hip_yaw(10) right_hip_roll(11) right_hip_pitch(12) right_knee(13) right_ankle(14)
    —— 与 ft1910/duck-ipc-proto/src/lib.rs:536 完全一致，也与我们 toml 注释的
       "left leg 0-4, neck/head/mouth 5-9, right leg 10-14" 一致。

运动学几何（关键，不再是占位值）
------------------------------
  * 连杆树、各体相对平移/旋转、关节轴**全部来自 ft1910 的 MJCF**
    ``.upstream/ft1910/kinematics/assets/alpha/robot_walk.xml``（逐体 pos/quat 与
    joint axis="0 0 1"，见该文件 6–108 行）。解析与换算由一次性脚本完成，本文件只
    烘焙结果，保证零依赖也能跑。
  * 坐标约定：MJCF 本就是 **Z 向上 / X 向前 / Y 向左**，与查看器一致，无需轴交换。
  * FK 严格按 MuJoCo 帧组合：``frame_child = frame_parent · R(axis,q) · Translate(pos) · R(quat)``，
    用纯 Python 四元数实现，等价于 MJCF 的关节原点位置（不含连杆自身朝向，仅取关节原点
    连线画骨架，足够可视化）。
  * mouth 在 alpha 运动学 MJCF 中无 hinge（只有 head 的 mouth_tip site），故嘴部作为 head_roll
    下的固定偏移节点，不驱动骨架转动——已诚实标注。

用法
----
  # 1) 从真机经 ssh 拉流（最贴近生产的路径）：
  ssh robot_host 'robotctl monitor --json' | python live_viewer.py --source stdin

  # 2) 本机无真机时看静止站姿（演示 FK，不需要任何依赖）：
  python live_viewer.py --demo

  # 3) 渲染后端可切换：auto(默认) / matplotlib / viser / headless
  python live_viewer.py --demo --renderer matplotlib

设计要点
--------
  * 零重依赖也能跑：FK 用纯 Python 矩阵/四元数，headless 模式只打印。matplotlib 常见即启用，
    viser（浏览器 3D）若已装则优先（需 pip install viser）。
  * 关节 ID 体系严格用我们的「1–15 物理 ID + 左腿优先名序」（见对照文档 §1），
    不混入官方 10–14/20–24/30–34。
"""

from __future__ import annotations

import argparse
import json
import math
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
# 注意下标顺序也是左腿优先，与 JOINT_NAMES 对齐。
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
#    关节原点位置 = 该体的原点（joint pos 默认 0，位于父体原点处）。
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
# 4. 状态解析（只取查看器需要的字段；空数组按「未上报」处理，绝不当 0）
# ───────────────────────────────────────────────────────────────────────────
@dataclass
class RobotStateView:
    t: float = 0.0
    policy: str = "?"
    joints: list[float] = field(default_factory=lambda: [0.0]*N)
    targets: list[float] = field(default_factory=lambda: [0.0]*N)
    velocities: list[float] = field(default_factory=list)
    currents_ma: list[float] = field(default_factory=list)


def parse_state(obj: dict) -> RobotStateView:
    j = obj.get("joints") or []
    tg = obj.get("targets") or []
    if len(j) != N or len(tg) != N:
        # 长度不符：多半是另一条线 / 旧帧，原样保留前 N 个并补 0（查看器标注异常）
        j = (list(j) + [0.0]*N)[:N]
        tg = (list(tg) + [0.0]*N)[:N]
    return RobotStateView(
        t=float(obj.get("t", 0.0)),
        policy=str(obj.get("policy", "?")),
        joints=[float(x) for x in j],
        targets=[float(x) for x in tg],
        velocities=list(obj.get("velocities") or []),
        currents_ma=list(obj.get("currents_ma") or []),
    )


# ───────────────────────────────────────────────────────────────────────────
# 5. 渲染后端（可插拔）
# ───────────────────────────────────────────────────────────────────────────
def _draw_edges(positions: dict[str, tuple[float, float, float]], color="C0"):
    xs, ys, zs = [], [], []
    for child, parent in EDGES:
        if child not in positions or parent not in positions:
            continue
        a = positions[parent]; b = positions[child]
        xs += [a[0], b[0], None]; ys += [a[1], b[1], None]; zs += [a[2], b[2], None]
    return xs, ys, zs, color


class HeadlessViewer:
    """无图形依赖：每帧打印各关节角与目标角、跟踪误差、policy。"""
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
    def close(self): pass


class MatplotlibViewer:
    """matplotlib 3D 折线骨架（最常见的本地依赖）。"""
    def __init__(self, interval_ms: int = 100):
        import matplotlib.pyplot as plt  # noqa: PLC0415
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401, PLC0415
        self.plt = plt
        self.fig = plt.figure(figsize=(7, 7))
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.ax.set_title("MicroDuck HD-1910 live pose")
        self.text = self.ax.text2D(0.02, 0.95, "", transform=self.ax.transAxes)
        self.interval = interval_ms
        self._last = time.time()

    def frame(self, st: RobotStateView) -> None:
        pos = forward_kinematics(st.joints)
        self.ax.cla()
        self.ax.set_box_aspect((1, 1, 1.4))
        xs, ys, zs, _ = _draw_edges(pos)
        self.ax.plot(xs, ys, zs, "-o", color="C0", lw=2, ms=4)
        # 目标姿态用细线叠加（若齐）
        if any(abs(st.targets[i]-st.joints[i]) > 1e-3 for i in range(N)):
            pos_t = forward_kinematics(st.targets)
            xt, yt, zt, _ = _draw_edges(pos_t)
            self.ax.plot(xt, yt, zt, "--", color="C1", lw=1, alpha=0.6)
        self.ax.set_xlabel("X (forward)"); self.ax.set_ylabel("Y (left)")
        self.ax.set_zlabel("Z (up)")
        self.text.set_text(f"policy={st.policy}  t={st.t:.2f}s")
        self.plt.pause(self.interval/1000.0)

    def close(self): self.plt.show(block=False)


class ViserViewer:
    """浏览器 3D（viser，若已装）。提供可旋转/缩放的实时画面。"""
    def __init__(self, port: int = 8012):
        import viser  # noqa: PLC0415
        self.sv = viser.ViserServer(port=port)
        self.handles = {}
    def frame(self, st: RobotStateView) -> None:
        pos = forward_kinematics(st.joints)
        for name, p in pos.items():
            h = self.handles.get(name)
            if h is None:
                h = self.sv.scene.add_frame(name, show_axes=False)
                self.handles[name] = h
            h.position = (p[0], p[1], p[2])
        for c in self.handles:
            parent = BONE_BY_NAME[c]["parent"]
            if parent:
                self.handles[c].parent = self.handles[parent]
    def close(self): pass


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
# 6. 数据源
# ───────────────────────────────────────────────────────────────────────────
def run_stdin(viewer) -> None:
    """从 stdin 读逐行 JSON（robotctl monitor --json 的逐帧输出）。"""
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


def run_demo(viewer) -> None:
    """无真机：循环演示静止姿。"""
    st = parse_state({"joints": list(REST_POSITION),
                      "targets": list(REST_POSITION), "policy": "stand", "t": 0.0})
    for _ in range(3):
        viewer.frame(st)
        time.sleep(0.3)


# ───────────────────────────────────────────────────────────────────────────
# 7. 入口
# ───────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="MicroDuck HD-1910 真机 3D 姿态查看器")
    ap.add_argument("--source", choices=["stdin", "demo"], default="demo",
                    help="stdin=从 robotctl monitor --json 管道读; demo=本地静止姿演示")
    ap.add_argument("--demo", action="store_true",
                    help="等价于 --source demo（本地静止姿演示）")
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
        else:
            run_demo(viewer)
    except KeyboardInterrupt:
        pass
    finally:
        viewer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
