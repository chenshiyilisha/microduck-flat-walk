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
  * 零重依赖也能跑：FK 用纯 Python 矩阵，headless 模式只打印。matplotlib 常见即启用，
    viser（浏览器 3D）若已装则优先（需 pip install viser）。
  * 关节 ID 体系严格用我们的「1–15 物理 ID + 左腿优先名序」（见对照文档 §1），
    不混入官方 10–14/20–24/30–34。
  * 链路平移/长度是**占位值**，最终应从 MJCF（robot_walk.xml）读真实几何，见 LINKS。
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
# 2. 运动学骨架（占位几何 —— 真实值请从 robot_walk.xml 读）
#    每个关节：parent 关节名、相对父关节的平移 (dx,dy,dz, 米)、旋转轴、符号。
#    坐标：Z 向上，X 向前，Y 向左（右腿为 -Y）。角度绕轴旋转后再叠加平移。
#    ⚠️ 这些平移/长度是按鸭子大致比例估的，仅用于骨架可视化；要精确必须回填 MJCF。
# ───────────────────────────────────────────────────────────────────────────
LINKS: dict[str, dict] = {
    # 盆骨为根
    "pelvis":          {"parent": None,     "pos": (0.0, 0.0, 0.0),  "axis": None, "sign": 1.0},
    # 左腿（Y 为正 = 左）
    "left_hip_yaw":    {"parent": "pelvis", "pos": (0.0, 0.06, 0.10), "axis": "z", "sign": 1.0},
    "left_hip_roll":   {"parent": "left_hip_yaw",   "pos": (0,0,0),     "axis": "x", "sign": 1.0},
    "left_hip_pitch":  {"parent": "left_hip_roll",  "pos": (0,0,0),     "axis": "y", "sign": 1.0},
    "left_knee":       {"parent": "left_hip_pitch", "pos": (0,-0.10,0), "axis": "y", "sign": 1.0},
    "left_ankle":      {"parent": "left_knee",      "pos": (0,-0.10,0), "axis": "y", "sign": 1.0},
    "left_foot":       {"parent": "left_ankle",     "pos": (0.05,-0.03,0), "axis": None, "sign": 1.0},
    # 右腿（Y 为负 = 右）
    "right_hip_yaw":   {"parent": "pelvis", "pos": (0.0, -0.06, 0.10), "axis": "z", "sign": 1.0},
    "right_hip_roll":  {"parent": "right_hip_yaw",  "pos": (0,0,0),     "axis": "x", "sign": 1.0},
    "right_hip_pitch": {"parent": "right_hip_roll", "pos": (0,0,0),     "axis": "y", "sign": 1.0},
    "right_knee":      {"parent": "right_hip_pitch","pos": (0,-0.10,0), "axis": "y", "sign": 1.0},
    "right_ankle":     {"parent": "right_knee",     "pos": (0,-0.10,0), "axis": "y", "sign": 1.0},
    "right_foot":      {"parent": "right_ankle",    "pos": (0.05,-0.03,0), "axis": None, "sign": 1.0},
    # 颈 / 头 / 嘴（向上 +Z）
    "neck_pitch":      {"parent": "pelvis", "pos": (0,0,0.12),  "axis": "y", "sign": 1.0},
    "head_pitch":      {"parent": "neck_pitch", "pos": (0,0,0.06), "axis": "y", "sign": 1.0},
    "head_yaw":        {"parent": "head_pitch", "pos": (0,0,0.04), "axis": "z", "sign": 1.0},
    "head_roll":       {"parent": "head_yaw",   "pos": (0,0,0),    "axis": "x", "sign": 1.0},
    "mouth":           {"parent": "head_roll",  "pos": (0.06,0,0),  "axis": "y", "sign": 1.0},
}


# ───────────────────────────────────────────────────────────────────────────
# 3. 纯 Python 3x3 旋转 + 平移（不依赖 numpy）
# ───────────────────────────────────────────────────────────────────────────
def _rot(axis: str, ang: float) -> list[list[float]]:
    c, s = math.cos(ang), math.sin(ang)
    if axis == "x":
        return [[1,0,0],[0,c,-s],[0,s,c]]
    if axis == "y":
        return [[c,0,s],[0,1,0],[-s,0,c]]
    if axis == "z":
        return [[c,-s,0],[s,c,0],[0,0,1]]
    return [[1,0,0],[0,1,0],[0,0,1]]


def _apply(M: list[list[float]], p: tuple[float,float,float]) -> tuple[float,float,float]:
    return (M[0][0]*p[0]+M[0][1]*p[1]+M[0][2]*p[2],
            M[1][0]*p[0]+M[1][1]*p[1]+M[1][2]*p[2],
            M[2][0]*p[0]+M[2][1]*p[1]+M[2][2]*p[2])


def _mmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def forward_kinematics(angles: list[float]) -> dict[str, tuple[float,float,float]]:
    """angles: 长度 15，下标对应 JOINT_NAMES。返回每个 LINKS 节点的世界坐标。"""
    assert len(angles) == N, f"需要 {N} 个关节角，收到 {len(angles)}"
    world: dict[str, tuple[float,float,float]] = {}
    # 拓扑序：先 pelvis，再其余（LINKS 已按依赖顺序定义）
    order = ["pelvis"] + [k for k in LINKS if k != "pelvis"]
    for name in order:
        spec = LINKS[name]
        parent = spec["parent"]
        p_world = world[parent] if parent else (0.0, 0.0, 0.0)
        if parent is None:
            world[name] = (0.0, 0.0, 0.0)
            continue
        p_spec = LINKS[parent]
        # 父节点自身先旋转（用父关节角），再平移到本关节
        parent_ang = 0.0
        if parent in JOINT_NAMES:
            parent_ang = angles[JOINT_NAMES.index(parent)] * (p_spec.get("sign", 1.0))
        R = _rot(p_spec["axis"], parent_ang) if p_spec["axis"] else [[1,0,0],[0,1,0],[0,0,1]]
        local = _apply(R, spec["pos"])
        world[name] = (p_world[0]+local[0], p_world[1]+local[1], p_world[2]+local[2])
    return world


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
def _draw_edges(positions: dict[str, tuple[float,float,float]], color="C0"):
    edges = [(c, LINKS[c]["parent"]) for c in LINKS if LINKS[c]["parent"]]
    xs, ys, zs = [], [], []
    for child, parent in edges:
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
            parent = LINKS[c]["parent"]
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
