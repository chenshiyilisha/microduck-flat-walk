#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 mjlab MJCF 提取 MicroDuck 真实外观网格，输出紧凑二进制供 Android Canvas 2D 渲染。

为什么需要它：当前 App 的 DuckModelGeometry 是程序化椭球+火柴人，用户反馈「不像鸭子」。
训练/仿真侧 (microduck-hf/mjlab) 有真实 STL 网格（躯干壳/头壳/脚/脸等），是鸭子的真实外形。
本脚本用 mujoco 加载 MJCF，跑运动学，把每个外观 geom 的 mesh 顶点应用世界变换，
输出世界坐标三角形，供 core 模块用纯 JVM Canvas 2D 渲染。

设计要点：
  · 🔴 外观集合**以 MJCF 官方分组为准，不按 mesh 名字挑**（2026-11-15 第 5 轮真因）。
    本 MJCF 由 onshape-to-robot 生成，所有外观 geom 都标 class="visual" ⇒ group=2；
    MuJoCo 默认只渲染 group 0–2，group=3 是 self_collision_only（不可见）。
    旧版用「按名字挑 18 种」的白名单，把 group=2 中几十个**连接骨架**
    （upper_leg_*/ankle_*/yaw2roll/yaw_roll_motion/xl330/seeed_bearing* 等）全丢了，
    又多画了 group=3 自碰撞体 ⇒ 头、躯干、腿、脚在画面上悬空分离。
    离线 PNG 目视实证：修好 stride 抽样后仍是「悬空的几块壳」，不是一只鸭子。
  · 应用 geom_xpos/geom_xmat 世界变换，输出绝对坐标，Kotlin 侧只做旋转+投影。
  · 🔴 简化**必须保连通**：用「顶点聚类」而不是「每隔 N 个面取一个」的 stride 抽样。
    stride 抽样只留 ~2% 且三角形彼此不相邻 ⇒ Canvas 上是一堆散落碎片
    （2026-11-15 离线 PNG 目视实证），加不透明/Lambert 光照也救不回来。
    顶点聚类让相邻三角形共享簇顶点 ⇒ 连成闭合表面。
    二分搜索 cell 尺寸把三角形数压到 [TARGET_TRIS] 预算内，MJCF 换版也不会爆量。
  · 输出二进制格式：顶点表 + 三角形索引 + 每三角形颜色，core 模块纯 JVM 解析。
  · 两类产物级判据（都直接读产物字节，不复用生成器的自报数字）：
      surface_metrics  —— 表面连通（共享边 / 退化面 / 中位面积），防退回碎片；
      vertical_coverage —— 竖直方向三角形覆盖，防「只留外壳、丢掉连杆」的悬空分离。
    每条都带负对照（改坏必红）。

依赖（项目现成环境，勿用系统 Python 3.13 —— 它连 mujoco 都装不上）：
    microduck-software/.venv-mjlab/Scripts/python.exe   (Python 3.12 + mujoco 3.7.0 + numpy)

用法：
    <mjlab-python> tools/build_duck_mesh.py
    <mjlab-python> tools/build_duck_mesh.py --selftest
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
MJCF = BASE.parent / "microduck-hf" / "src" / "mjlab_microduck" / "robot" / "microduck" / "robot_walk.xml"
OUT = BASE / "core" / "src" / "main" / "resources" / "duck_mesh.bin"
# 🔴 2026-11-15 修真因：Android 的 ART ClassLoader 读不到 APK 根目录的 Java resource，
# `Class.getResourceAsStream("/duck_mesh.bin")` 在真机返回 null ⇒ View 静默降级线框。
# 一手依据：StackOverflow 25996774 / 26603493、tasselx/AndroidNote「资源文件拷贝的三种方式」
# ⇒ Android 必须放 src/main/assets/ 用 AssetManager.open()，或 res/raw + openRawResource()。
# 故同一份网格写两处：core/resources 供纯 JVM 自检(classpath)，app/assets 供真机。
# 两处必须字节一致，由 extract() 写完立即校验，并由本脚本 selftest() 与
# check_hardware_monitor.py 各自再判一次（三道独立判据，任一漂移都会红）。
ANDROID_OUT = BASE / "app" / "src" / "main" / "assets" / "duck_mesh.bin"

# 🔴 2026-11-15 第 5 轮真因：外观集合不能用「按 mesh 名字挑」的白名单。
# 一手事实（本机真跑 robot_walk.xml）：共 75 个 mesh geom；其中 group=2（class=visual，
# MuJoCo 默认可见）70 个 / 38 种 mesh，group=3（self_collision_only，不可见）5 个。
# 旧白名单只命中 group=2 的 21 个 geom（18 种 mesh），却把另外 49 个连接骨架全丢了，
# 还多画了 4 个 group=3 自碰撞体 ⇒ 头/躯干/腿/脚悬空分离（离线 PNG 目视实证）。
# ⇒ 唯一权威 = MJCF 的 geom_group；颜色则按下表给语义色（MJCF material 全是占位灰 0.5）。
VISUAL_GROUP = 2
DEFAULT_STRUCT_COLOR = 0xFF2B2B2B   # 未登记的结构件：镜头黑语义色（舵机/轴承/电子件）

# 3D 打印连杆/结构件 → 奶油白（用主橙语义色，core officialColor() 会重映射成 Cream 壳色）。
# 判据来自官方 Cream 配色：奶油白壳 + 橙 trim/喙 + 深色舵机，镜头恒黑。
WHITE_LINKS = {
    "upper_leg_left", "upper_leg_right", "upper_leg_rigidity_plate",
    "ankle_left", "ankle_right", "yaw2roll", "yaw_roll_motion",
}

# 外壳部件语义色（ARGB）：主橙→Cream 壳、深橙→橙 trim/喙、黑→镜头黑。
# 这张表只管**颜色**，不作几何取舍；未列出的 group=2 mesh 走 DEFAULT_STRUCT_COLOR。
PART_COLORS = {
    "trunk_base": 0xFFFF8A3D,   # 主橙：躯干
    "left_shell": 0xFFFF8A3D,   # 主橙：左壳
    "right_shell": 0xFFFF8A3D,  # 主橙：右壳
    "top_head_shell": 0xFFFF8A3D,
    "bottom_head_shell": 0xFFE0691F,  # 深橙：头壳底
    "face_part": 0xFFFF8A3D,    # 主橙：脸
    "foot_left": 0xFFE0691F,    # 深橙：脚
    "foot_right": 0xFFE0691F,
    "jaw": 0xFFE0691F,          # 深橙：喙
    "jaw_soft": 0xFFE0691F,
    "neck": 0xFFFF8A3D,
    "neck_pitch": 0xFFFF8A3D,
    "lens": 0xFF2B2B2B,          # 黑：镜头/眼
    "leg": 0xFFFF8A3D,
    "hip_l": 0xFFFF8A3D,
    "sole_left": 0xFFE0691F,
    "sole_right": 0xFFE0691F,
    "soft_mouth_top": 0xFFE0691F,
}
for _name in WHITE_LINKS:
    PART_COLORS[_name] = 0xFFFF8A3D

# ── DMSH v2 部件索引（阶段 4：颜色即状态）──
# 每个三角形带一个 part index，与 core 的 RobotPart 序号一一对应：
#   0..14  = 15 关节（顺序 = lib.rs JOINT_NAMES，即 RobotParts.JOINT_PARTS 顺序）
#   15..20 = 系统部件（TORSO/BATTERY/CPU/IMU/BUS/LINK，RobotPart.entries 中 JOINT 之后的顺序）
#   255    = NO_PART（纯外观件：壳/脸/喙/脚/镜头/PCB 等，无对应健康读数 ⇒ 保持官方基色）
#
# 🔴 映射唯一权威 = MJCF 的 joint→body 归属（一手，实测 15 joint 名 == lib.rs JOINT_NAMES）：
#   对每个 group=2 geom，取其 body；body 若恰好是某语义关节的 jnt_bodyid，则该 geom 的
#   **结构/舵机件**归该关节部件。系统件按 mesh 名的一手语义归 BATTERY/CPU/IMU。
#   纯外观壳件一律 NO_PART。禁止手写关节↔mesh 猜测。
MESH_SYSTEM_PART = {
    "np_f970": 16,                       # BATTERY（NP-F970 电池，一手 mesh 名）
    "pcb__raspberry_pi_zero_2_w": 17,    # CPU（RPi Zero 2W 主板）
    "elec_rpi_robot_hat_pcb": 17,        # CPU（robot HAT 板）
    "noenoeil": 18,                      # IMU（头部传感器模组；读数由 health 的 imu_ready 决定）
}
# 结构/舵机件 mesh：这些归其 body 对应的语义关节；其余 mesh 视为外观件 → NO_PART。
# 判据来自 mesh 的一手机械语义（onshape-to-robot 导出的连杆/轴承/舵机/支架）。
STRUCTURAL_MESH_PREFIXES = (
    "xl330", "seeed_bearing", "upper_leg", "ankle", "hip_l",
    "yaw2roll", "yaw_roll_motion", "bearing_roll", "leg",
    "motor_support",
)
# 15 关节顺序 = lib.rs JOINT_NAMES = RobotParts.JOINT_PARTS（一手，禁止重排）。
JOINT_ORDER = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]
NO_PART = 255
DMSH_VERSION = 2

# 三角形预算：Canvas 2D 每帧对每个三角形 drawPath 一次（1s tick 旋转 + 30ms 拖动节流）。
# 旧版 stride 抽样是 7500 面但全是碎片；顶点聚类用相同量级预算画出**闭合表面**。
# 二分搜索最细的聚类 cell，使输出 <= TARGET_TRIS，MJCF/STL 面数漂移时也不会爆量。
TARGET_TRIS = 12000
CELL_MIN = 0.002
CELL_MAX = 0.030
CELL_ITERS = 20
# 🔴 2026-11-16：聚类路线已废弃（保留 _cluster 仅作 QEM 失败时的兜底）。
# 聚类把大 geom 压到 ~9% 面数时曲面向质心塌缩（head_pitch z 跨度实测被压扁 96%），
# 整机高宽比从 1.26 拉成 1.85 —— 「渲染不像真鸭」的真因是几何本身失真。
# 现行路线 = pymeshlab QECD 逐 geom 保形简化 + 生成期 bbox 跨度守恒校验。
# 🔴 2026-11-17 后端实测：fast_simplification（trimesh simplify_quadric_decimation）
# 与 pyfqmr 是同一受限 C++ 内核，对 CAD 网格有「质量地板」——塌边提前停手
# （np_f970 请求 80 面实际输出 14044 面，agg=10 也不动；yaw2roll 地板 2484 面
# 且 z 主体塌 71%）。pymeshlab 的 QECD（MeshLab 参考实现）对同样网格全部
# 精确到目标面数且保形 0%（实测 7 个代表块 req300 全部 out=300, shk<=3%）。
# 判据：请求面数 vs 实际输出面数，非单调 = 后端不可信。


def _cluster(v: np.ndarray, f: np.ndarray, c: np.ndarray,
             cell: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """顶点聚类：量化→簇 id→丢弃塌陷面。返回 (簇中心, 面, 颜色, 保留掩码)。

    相邻三角形会共享同一个簇顶点，因此简化后表面仍是**连通**的；这是与 stride
    抽样最本质的区别（stride 抽样的三角形互不相邻，画出来就是散落碎片）。
    """
    mn = v.min(axis=0)
    q = np.floor((v - mn) / cell).astype(np.int64)
    uniq_q, inv = np.unique(q, axis=0, return_inverse=True)
    cf = inv[f]
    keep = (cf[:, 0] != cf[:, 1]) & (cf[:, 1] != cf[:, 2]) & (cf[:, 0] != cf[:, 2])
    cf = cf[keep]
    cc = c[keep]
    n = len(uniq_q)
    sums = np.zeros((n, 3), dtype=np.float64)
    cnts = np.zeros(n, dtype=np.int64)
    np.add.at(sums, inv, v)
    np.add.at(cnts, inv, 1)
    centers = (sums / cnts[:, None]).astype(np.float32)
    return centers, cf, cc, keep


def extract(mjcf_path: Path, out_path: Path) -> dict:
    import mujoco

    m = mujoco.MjModel.from_xml_path(str(mjcf_path))
    data = mujoco.MjData(m)
    mujoco.mj_kinematics(m, data)
    mujoco.mj_comPos(m, data)

    # 收集全部外观 geom 的**原始**三角形（不做 stride 抽样）。
    # 🔴 一手映射：joint 语义名 → jnt_bodyid。15 个 joint 名 == lib.rs JOINT_NAMES，
    # 故 body→joint 反查是权威的关节归属（零手写猜测），供 v2 部件索引使用。
    body_to_joint: dict[int, str] = {}
    for j in range(m.njnt):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j)
        if name in JOINT_ORDER:
            body_to_joint[int(m.jnt_bodyid[j])] = name

    all_verts: list[np.ndarray] = []
    all_faces: list[np.ndarray] = []
    all_colors: list[np.ndarray] = []
    face_codes: list[np.ndarray] = []
    face_parts: list[np.ndarray] = []       # v2：每三角形部件索引
    geom_blocks: list[dict] = []            # 分件聚类用：每个 visual geom 的块边界
    code_of_name: dict[str, int] = {}
    visual_geom_count = 0
    visual_mesh_kinds: set[str] = set()
    used_mesh_kinds: set[str] = set()

    for i in range(m.ngeom):
        g = m.geom(i)
        # 🔴 唯一权威 = MJCF 的 group：group=2 是官方 visual（MuJoCo 默认可见），
        # group=3 是 self_collision_only（不可见）。**不再按 mesh 名字挑外观**。
        gt = int(np.asarray(g.type).ravel()[0])
        if gt != int(mujoco.mjtGeom.mjGEOM_MESH):
            continue
        if int(m.geom_group[i]) != VISUAL_GROUP:
            continue
        mid = int(m.geom_dataid[i])
        mname = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MESH, mid)
        visual_geom_count += 1
        visual_mesh_kinds.add(mname)
        vadr, vnum = int(m.mesh_vertadr[mid]), int(m.mesh_vertnum[mid])
        fadr, fnum = int(m.mesh_faceadr[mid]), int(m.mesh_facenum[mid])
        if vnum == 0 or fnum == 0:
            continue
        used_mesh_kinds.add(mname)

        local_verts = m.mesh_vert[vadr:vadr + vnum].copy()   # (n,3)
        local_faces = m.mesh_face[fadr:fadr + fnum].copy()   # (n,3) 局部索引

        # 应用 geom 世界变换：xmat(3x3) + xpos(3)
        xmat = data.geom_xmat[i].reshape(3, 3).astype(np.float64)
        xpos = data.geom_xpos[i].astype(np.float64)
        world_verts = local_verts @ xmat.T + xpos

        valid = (local_faces >= 0) & (local_faces < vnum)
        local_faces = local_faces[valid.all(axis=1)]
        base = sum(x.shape[0] for x in all_verts)

        all_verts.append(world_verts.astype(np.float64))
        all_faces.append(local_faces.astype(np.int64) + base)
        all_colors.append(
            np.full(local_faces.shape[0],
                    PART_COLORS.get(mname, DEFAULT_STRUCT_COLOR), dtype=np.uint32))
        code = code_of_name.setdefault(mname, len(code_of_name))
        face_codes.append(np.full(local_faces.shape[0], code, dtype=np.int32))
        # v2 部件索引：系统件按 mesh 名语义；结构件按 body→joint 归属；其余 NO_PART。
        part = MESH_SYSTEM_PART.get(mname)
        if part is None:
            joint = body_to_joint.get(int(m.geom_bodyid[i]))
            is_structural = any(mname.startswith(pre) for pre in STRUCTURAL_MESH_PREFIXES)
            if joint is not None and is_structural:
                part = JOINT_ORDER.index(joint)
            else:
                part = NO_PART
        face_parts.append(np.full(local_faces.shape[0], part, dtype=np.uint8))
        geom_blocks.append({
            "v0": base, "vn": int(world_verts.shape[0]),
            "f0": sum(x.shape[0] for x in all_faces) - int(local_faces.shape[0]),
            "fn": int(local_faces.shape[0]), "name": mname,
        })

    if not all_verts:
        raise RuntimeError("未提取到任何 group=2 visual 网格，请检查 MJCF 的 geom_group")

    v = np.concatenate(all_verts, axis=0)
    f = np.concatenate(all_faces, axis=0)
    c = np.concatenate(all_colors, axis=0)
    codes = np.concatenate(face_codes, axis=0)
    parts = np.concatenate(face_parts, axis=0)
    raw_faces = int(f.shape[0])

    # 🔴 QEM 保形简化（2026-11-16 取代顶点聚类；2026-11-17 换 pymeshlab 后端）：
    # 聚类把大 geom 压到 ~9% 面数时，格子只能并成大块 → 曲面向质心塌缩
    # （实测 head_pitch z 跨度被压扁 96%、整机高宽比 1.26 被拉成 1.85），
    # 这正是「渲染不像真鸭」的真因 —— 几何本身就歪了，渲染风格救不回来。
    # QECD（Garland-Heckbert 二次误差度量）按「简化后形状误差最小」折叠边，
    # 是保形简化的标准算法；低面数下形状/比例保持远优于格子聚类。
    # 预算按 sqrt(世界表面积) 分配 —— 原始面数被镶嵌密度支配（轴承 23 万个微三角），
    # 表面积才对应屏幕占比；clamp 后迭代重分配逼近 TARGET_TRIS。
    # 形状自适应：某块在预算下 bbox 跨度塌缩 > SHAPE_TOL 时倍增预算重试
    # （pymeshlab 后端保形性好，升级极少触发）；仍不过则原样保留整块。
    # 最后若总量超 TARGET，按预算余量反哺收缩（缩完重测形状，失败回退）。
    import pymeshlab

    MIN_FACES = 80
    MAX_FACES = 1500
    # 小件原样保留：复杂小件（如 banana_pcb_locker）低面数也表达不了，QEM 会压扁；
    # ≤KEEP_SMALL_FACES 的块不动，QEM 预算只在剩余额度内按 sqrt(面积) 分配。
    KEEP_SMALL_FACES = 1500
    SHAPE_TOL = 0.20

    def _qem(bv: np.ndarray, bf: np.ndarray, target: int):
        """pymeshlab QECD 到 target 面。失败抛异常；成功返回 (verts, faces)。"""
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(
            vertex_matrix=bv.astype(np.float64),
            face_matrix=bf.astype(np.int32)), "blk")
        ms.meshing_decimation_quadric_edge_collapse(
            targetfacenum=int(target), preservenormal=True)
        mm = ms.current_mesh()
        return (np.asarray(mm.vertex_matrix(), dtype=np.float64),
                np.asarray(mm.face_matrix(), dtype=np.int64))

    def _shape_shrink(pre_v: np.ndarray, post_v: np.ndarray) -> float:
        """各轴 bbox 跨度最大收缩率（>0 表示压扁）。"""
        pre = pre_v.max(axis=0) - pre_v.min(axis=0)
        post = post_v.max(axis=0) - post_v.min(axis=0)
        return float(max((pre - post) / np.maximum(pre, 1e-9)))

    def _simplify_with_gate(bv, bf, budget_g):
        """带形状门禁的简化：预算下塌了就倍增重试；不过则原样保留。
        返回 (verts, faces, used_budget, shrink)。"""
        pre_lo, pre_hi = bv.min(axis=0), bv.max(axis=0)
        pre_span = pre_hi - pre_lo
        try_fc = int(budget_g)
        while try_fc < bf.shape[0]:
            try:
                cand_v, cand_f = _qem(bv, bf, try_fc)
            except Exception as e:
                print(f"WARN QECD 失败 {try_fc} 面: {type(e).__name__} {e}")
                break
            post_span = cand_v.max(axis=0) - cand_v.min(axis=0)
            shrink = float(max((pre_span - post_span)
                               / np.maximum(pre_span, 1e-9)))
            if shrink <= SHAPE_TOL:
                return cand_v, cand_f, try_fc, shrink
            try_fc = min(try_fc * 2, bf.shape[0])  # 塌了→加预算重试
        return bv, bf, int(bf.shape[0]), 0.0  # 原样保留

    areas = []
    for blk in geom_blocks:
        bv = v[blk["v0"]:blk["v0"] + blk["vn"]]
        bf = f[blk["f0"]:blk["f0"] + blk["fn"]] - blk["v0"]
        tri = bv[bf]
        cross = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        areas.append(float(cross.sum()) / 2.0)
    w = np.sqrt(np.maximum(np.array(areas), 1e-9))
    small_mask = np.array([blk["fn"] <= KEEP_SMALL_FACES for blk in geom_blocks])
    big_idx = [k for k, blk in enumerate(geom_blocks) if not small_mask[k]]
    small_sum = int(sum(blk["fn"] for blk, s in zip(geom_blocks, small_mask) if s))
    avail = TARGET_TRIS - small_sum
    w_q = np.where(small_mask, 0.0, w)
    w_sum = w_q.sum()
    if w_sum <= 0 or avail <= 0:
        raise RuntimeError("没有可 QECD 的大 geom 或预算耗尽")
    budget = np.clip(avail * w_q / w_sum, MIN_FACES, MAX_FACES).astype(np.float64)
    for _ in range(8):  # clamp 后迭代重分配：把封顶块的余额分给未封顶块
        over = budget > MAX_FACES
        budget[over] = MAX_FACES
        rest = avail - budget[over].sum()
        free = (~over) & (~small_mask)
        free_idx = np.where(free)[0]
        if free_idx.size == 0 or rest <= MIN_FACES * free_idx.size:
            break
        budget[free_idx] = np.clip(
            rest * w[free_idx] / w[free_idx].sum(), MIN_FACES, MAX_FACES)
    budget = budget.astype(int)
    budget = np.where(small_mask, np.array([blk["fn"] for blk in geom_blocks]), budget)

    # 第一轮：按预算逐块 QECD（带形状门禁）
    results = []  # (t_v, t_f, shrink, budget_used) 按块序
    total_faces = 0
    for blk, budget_g in zip(geom_blocks, budget):
        bv = v[blk["v0"]:blk["v0"] + blk["vn"]]
        bf = f[blk["f0"]:blk["f0"] + blk["fn"]] - blk["v0"]
        if budget_g < blk["fn"]:
            t_v, t_f, used, shr = _simplify_with_gate(bv, bf, budget_g)
        else:
            t_v, t_f, used, shr = bv, bf, blk["fn"], 0.0
        results.append([t_v, t_f, shr, used])
        total_faces += int(t_f.shape[0])

    # 预算再平衡：总量超 TARGET 时，从形状余量大的块反哺收缩（缩完重测，
    # 塌了就回退到上一次合格结果）。最多 4 轮；仍超则诚实报错不放宽。
    for _ in range(4):
        if total_faces <= TARGET_TRIS:
            break
        reducible = [k for k in big_idx
                     if results[k][3] > MIN_FACES
                     and results[k][3] < geom_blocks[k]["fn"]]
        if not reducible:
            break
        excess = total_faces - TARGET_TRIS
        w_r = np.array([max(results[k][3], 1) for k in reducible], dtype=np.float64)
        for k, wk in zip(reducible, w_r):
            blk = geom_blocks[k]
            bv = v[blk["v0"]:blk["v0"] + blk["vn"]]
            bf = f[blk["f0"]:blk["f0"] + blk["fn"]] - blk["v0"]
            cut = int(excess * wk / w_r.sum()) + 1
            new_fc = max(results[k][3] - cut, MIN_FACES)
            try:
                cand_v, cand_f = _qem(bv, bf, new_fc)
            except Exception:
                continue
            shrink = _shape_shrink(bv, cand_v)
            if shrink <= SHAPE_TOL and cand_f.shape[0] < results[k][1].shape[0]:
                total_faces += int(cand_f.shape[0]) - int(results[k][1].shape[0])
                results[k] = [cand_v, cand_f, shrink, new_fc]
            # 塌了/没变小 → 保留原结果，下一轮换别的块
    if total_faces > TARGET_TRIS:
        raise RuntimeError(
            f"简化后三角形 {total_faces} 超出预算 {TARGET_TRIS} 且无余量可收 "
            f"(保形优先于预算；如需更低预算请调 TARGET_TRIS)")

    out_v, out_f, out_c, out_p, out_k, cells = [], [], [], [], [], []
    v_off = 0
    for blk, res in zip(geom_blocks, results):
        t_v, t_f, shr, _used = res
        bv = v[blk["v0"]:blk["v0"] + blk["vn"]]
        bc = c[blk["f0"]:blk["f0"] + blk["fn"]]
        bp = parts[blk["f0"]:blk["f0"] + blk["fn"]]
        bk = codes[blk["f0"]:blk["f0"] + blk["fn"]]
        out_v.append(t_v)
        out_f.append(t_f + v_off)
        out_c.append(np.full(t_f.shape[0], int(bc[0]), dtype=np.uint32))
        out_p.append(np.full(t_f.shape[0], int(bp[0]), dtype=np.uint8))
        out_k.append(np.full(t_f.shape[0], int(bk[0]), dtype=np.int32))
        cells.append((blk["name"], int(t_f.shape[0]), int(blk["fn"]),
                      round(float(shr), 3)))
        v_off += int(t_v.shape[0])

    centers = np.concatenate(out_v, axis=0)
    cf = np.concatenate(out_f, axis=0).astype(np.int64)
    cc = np.concatenate(out_c, axis=0)
    cparts = np.concatenate(out_p, axis=0)
    kept_codes = np.concatenate(out_k, axis=0)
    cell_used = 0.0  # QEM 路线不再有聚类 cell；字段保留供报告兼容
    total_faces = int(cf.shape[0])
    worst = max((c[3] for c in cells), default=0.0)
    print(f"QEM: {raw_faces} -> {total_faces} faces (budget {TARGET_TRIS})")
    print("QEM 各块面数/原始/最大收缩率：")
    for nm, fn, raw_fn, shr in sorted(cells, key=lambda x: -x[3])[:8]:
        print(f"  {nm[:34]:<34} {fn:>5}/{raw_fn:>6}  收缩 {shr:.0%}")
    print(f"QEM 最大部件收缩率 = {worst:.0%}")

    if cf.shape[0] == 0:
        raise RuntimeError("简化后无有效三角形")
    if cf.shape[0] > TARGET_TRIS:
        raise RuntimeError(f"简化后三角形 {cf.shape[0]} 超出预算 {TARGET_TRIS}")

    # 居中 + 均匀归一化（Kotlin DuckMesh 再做 Z-up→Y-up 轴置换与 NODES 尺度对齐）
    mins = centers.min(axis=0).astype(np.float64)
    maxs = centers.max(axis=0).astype(np.float64)
    center = (mins + maxs) / 2.0
    max_extent = float((maxs - mins).max())
    scale = 2.0 / max_extent if max_extent > 0 else 1.0
    centered = ((centers.astype(np.float64) - center) * scale).astype(np.float32)

    n_verts, n_tris = int(centered.shape[0]), int(cf.shape[0])
    inv_code = {code: name for name, code in code_of_name.items()}
    part_tri_counts: dict[str, int] = {}
    for code, cnt in zip(*np.unique(kept_codes, return_counts=True)):
        part_tri_counts[inv_code[int(code)]] = int(cnt)

    # v2 部件分布统计（从实际写出的索引派生，供自检/文档核对，不手写）
    part_index_counts: dict[int, int] = {}
    for idx, cnt in zip(*np.unique(cparts, return_counts=True)):
        part_index_counts[int(idx)] = int(cnt)
    # 不变量：部件索引必须是 0..20 或 NO_PART(255)，不能越界到 21..254。
    bad = [i for i in part_index_counts if not (0 <= i <= 20 or i == NO_PART)]
    if bad:
        raise RuntimeError(f"部件索引越界: {bad}")

    # 写二进制 v2：header / 顶点表 / 三角形索引 / 每三角形颜色 / 每三角形部件索引
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fp:
        fp.write(struct.pack("<4sIIII", b"DMSH", DMSH_VERSION, n_verts, n_tris, 21))
        fp.write(centered.tobytes())
        fp.write(cf.astype(np.int32).tobytes())
        fp.write(cc.astype(np.uint32).tobytes())
        fp.write(cparts.astype(np.uint8).tobytes())

    # 🔴 双写 + 字节级一致性校验：两份资源一旦漂移，真机与 JVM 自检看到的就不是
    # 同一个模型（这正是「core 自检全绿、真机降级」这类假绿的温床）。
    ANDROID_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = out_path.read_bytes()
    ANDROID_OUT.write_bytes(payload)
    if ANDROID_OUT.read_bytes() != payload:
        raise RuntimeError("duck_mesh.bin 双写字节不一致：core/resources 与 app/assets")

    return {
        "n_verts": n_verts, "n_tris": n_tris,
        "parts": part_tri_counts, "part_index_counts": part_index_counts,
        "n_parts": 21, "out": str(out_path),
        "bbox_min": mins.tolist(), "bbox_max": maxs.tolist(),
        "center": center.tolist(), "scale": scale,
        "raw_faces": raw_faces, "cell": cell_used,
        # 🔴 覆盖率读数从 MJCF 派生，不写死数字：selftest 用它判「有没有把
        # 连接骨架又漏掉」，MJCF 换版本也会跟着变，不会像写死 18/25 那样漂移。
        "visual_geom_count": visual_geom_count,
        "visual_mesh_kinds": len(visual_mesh_kinds),
        "used_mesh_kinds": len(used_mesh_kinds),
    }


def header_ok(buf: bytes, stats: dict) -> bool:
    """第二条独立算法：直接 struct 解析字节，不复用 extract() 自己的计数变量。

    v2 header = 4s + 5×u32（magic/version/n_verts/n_tris/n_parts）= 20 字节；
    part 数组 = n_tris × u8 追加在颜色表之后。
    """
    try:
        magic, ver, nv, nt, nparts = struct.unpack_from("<4sIIII", buf, 0)
        # header(20) + 顶点(3*f32) + 三角形索引(3*i32) + 颜色(u32) + 部件索引(u8)
        expected_len = 20 + nv * 3 * 4 + nt * 3 * 4 + nt * 4 + nt
        return (magic == b"DMSH" and ver == DMSH_VERSION
                and nv == stats["n_verts"] and nt == stats["n_tris"]
                and nparts == stats["n_parts"]
                and len(buf) == expected_len)
    except Exception:
        return False


def parity_ok(a: bytes, b: bytes) -> bool:
    """两份网格产物必须非空且字节完全相同。"""
    return len(a) > 0 and a == b


def surface_metrics(buf: bytes) -> tuple[float, float, float]:
    """**产物级**连通性读数，独立于生成过程。返回 (共享边比例, 退化面比例, 中位面积)。

    判据思路（项目铁律：判据必须独立于被测值）：直接读产物字节，把每条无向边
    归一化后统计「被 >=2 个三角形共用的边」占比。
      · 顶点聚类（连通表面）⇒ 接近 1.0；
      · stride 抽样（散落碎片）⇒ 约 0.25。
    这个量不来自 extract() 的自报数字，改坏生成逻辑它就会掉下来。
    """
    _, _, nv, nt, _ = struct.unpack_from("<4sIIII", buf, 0)
    off = 20
    v = np.frombuffer(buf, dtype="<f4", count=nv * 3, offset=off).reshape(-1, 3).astype(np.float64)
    off += nv * 3 * 4
    t = np.frombuffer(buf, dtype="<i4", count=nt * 3, offset=off).reshape(-1, 3)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    edges = np.sort(np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [0, 2]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return (float((counts >= 2).mean()),
            float((area < 1e-6).mean()),
            float(np.median(area)))


def scattered_fixture() -> bytes:
    """负对照夹具：每个三角形用自己独立的 3 个顶点 ⇒ 表面完全不连通。"""
    nv, nt = 300, 100
    rng = np.random.default_rng(0)
    v = rng.normal(size=(nv, 3)).astype(np.float32)
    t = np.arange(nt * 3, dtype=np.int32).reshape(-1, 3)
    c = np.zeros(nt, dtype=np.uint32)
    p = np.full(nt, NO_PART, dtype=np.uint8)
    return (struct.pack("<4sIIII", b"DMSH", DMSH_VERSION, nv, nt, 21)
            + v.tobytes() + t.tobytes() + c.tobytes() + p.tobytes())


def vertical_coverage(buf: bytes, bins: int = 128) -> tuple[float, float]:
    """产物级「竖直方向每个高度有没有实体表面」读数，独立于生成过程。

    返回 (最长连续未覆盖段占比, 未覆盖箱总占比)。
    为什么需要它：shared-edge 连通性只能证明「面与面共享顶点」，证明不了
    「头/躯干/腿之间连起来了」。旧版按名字挑外壳时，产物连通性读数仍是
    1.000（每块壳自身闭合），但画面上是几块悬空分离的壳。
    这里用每个三角形的 z 区间做**差分覆盖**（O(三角面数)，不逐箱循环）：
    真实完整鸭子 ⇒ 全程有面覆盖；丢掉连杆 ⇒ 中段出现明显空档。
    实测（128 箱）：旧白名单网格 0.039 / 0.109；补全 group=2 后 0.000 / 0.000。
    """
    _, _, nv, nt, _ = struct.unpack_from("<4sIIII", buf, 0)
    off = 20
    v = np.frombuffer(buf, dtype="<f4", count=nv * 3, offset=off).reshape(-1, 3).astype(np.float64)
    off += nv * 3 * 4
    t = np.frombuffer(buf, dtype="<i4", count=nt * 3, offset=off).reshape(-1, 3)
    z = v[:, 2]
    lo, hi = float(z.min()), float(z.max())
    if hi <= lo:
        return (1.0, 1.0)
    zt = z[t]
    zmin = np.clip(((zt.min(axis=1) - lo) / (hi - lo) * (bins - 1)).astype(np.int64), 0, bins - 1)
    zmax = np.clip(((zt.max(axis=1) - lo) / (hi - lo) * (bins - 1)).astype(np.int64), 0, bins - 1)
    delta = np.zeros(bins + 1, dtype=np.int32)
    np.add.at(delta, zmin, 1)
    np.add.at(delta, zmax + 1, -1)
    cover = np.cumsum(delta)[:bins] > 0
    best = cur = 0
    for c in cover:
        cur = cur + 1 if not c else 0
        best = max(best, cur)
    return (best / bins, float((~cover).mean()))


def gapped_fixture(buf: bytes) -> bytes:
    """负对照夹具：删掉竖直中段 [0.35, 0.65] 的全部三角形 ⇒ 头/躯干/腿断开。"""
    _, ver, nv, nt, nparts = struct.unpack_from("<4sIIII", buf, 0)
    off = 20
    vbytes = buf[off:off + nv * 3 * 4]
    off_t = off + nv * 3 * 4
    t = np.frombuffer(buf, dtype="<i4", count=nt * 3, offset=off_t).reshape(-1, 3).copy()
    c = np.frombuffer(buf, dtype="<u4", count=nt, offset=off_t + nt * 3 * 4).copy()
    off_p = off_t + nt * 3 * 4 + nt * 4
    p = np.frombuffer(buf, dtype="<u1", count=nt, offset=off_p).copy()
    v = np.frombuffer(vbytes, dtype="<f4").reshape(-1, 3)
    z = v[:, 2]
    lo, hi = float(z.min()), float(z.max())
    zc = (z[t].mean(axis=1) - lo) / (hi - lo) if hi > lo else np.zeros(len(t))
    keep = (zc < 0.35) | (zc > 0.65)
    tk, ck, pk = t[keep], c[keep], p[keep]
    return (struct.pack("<4sIIII", b"DMSH", ver, nv, len(tk), nparts)
            + vbytes + tk.astype("<i4").tobytes() + ck.astype("<u4").tobytes()
            + pk.astype("<u1").tobytes())


def selftest() -> int:
    """自检：真跑提取，验证二进制结构与两份产物字节一致；带负对照。

    🔴 结论行必须遵守 check_all_app_gates.py 的契约：只打印
       `SELFTEST: ... — PASS` 会被判「无结论行(静默成功不算绿)」而误红。
       这里按其他工具的统一格式输出 `RESULT: N passed, M failed`，N/M 为
       下面 checks 的真实计数（不写死数字，避免权威漂移）。
    """
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    if not MJCF.exists():
        print("PRECONDITION_FAIL: MJCF 不存在，无法真跑提取")
        print("RESULT: 0 passed, 1 failed")
        return 1

    try:
        stats = extract(MJCF, OUT)
        check("提取真跑成功", True)
    except Exception as e:
        print(f"提取异常: {e}")
        print("RESULT: 0 passed, 1 failed")
        return 1

    check("顶点数 >= 100", stats["n_verts"] >= 100)
    check("三角形数 >= 100", stats["n_tris"] >= 100)
    check("三角形数 <= 30000（Canvas 2D 可承受）", stats["n_tris"] <= 30000)
    check(f"三角形数在聚类预算内(<= {TARGET_TRIS})", stats["n_tris"] <= TARGET_TRIS)
    check("外观部件非空", len(stats["parts"]) > 0)
    check("确实做了简化（原始面数 > 输出面数）", stats["raw_faces"] > stats["n_tris"])

    payload = OUT.read_bytes()
    check("二进制结构自洽（独立 struct 解析）", header_ok(payload, stats))

    # 🔴 v2 部件索引产物级判据（阶段 4）：直接从产物字节读，不复用生成器计数。
    _, ver, nv, nt, nparts = struct.unpack_from("<4sIIII", payload, 0)
    p_off = 20 + nv * 3 * 4 + nt * 3 * 4 + nt * 4
    p_arr = np.frombuffer(payload, dtype="<u1", count=nt, offset=p_off)
    check(f"v2 版本号={DMSH_VERSION}", ver == DMSH_VERSION)
    check(f"v2 n_parts={nparts} 合理(21)", nparts == 21)
    check(f"v2 部件数组长度={nt} 对齐三角形数", p_arr.shape[0] == nt)
    check("v2 部件索引不越界(<=20 或 255)",
          bool(np.all((p_arr <= 20) | (p_arr == NO_PART))))
    colorable = int(np.sum(p_arr != NO_PART))
    check(f"v2 可着色三角形>0 (实测 {colorable})", colorable > 0)
    present = set(int(x) for x in np.unique(p_arr))
    # 15 关节至少覆盖多数（舵机/连杆都在）；系统件至少电池/CPU/IMU 命中。
    joints_present = len([i for i in present if 0 <= i <= 14])
    check(f"v2 关节部件覆盖 >= 12/15 (实测 {joints_present})", joints_present >= 12)
    check("v2 系统部件 BATTERY/CPU/IMU 命中",
          {16, 17, 18}.issubset(present))
    # 负对照：把 part 数组一字节改越界(200)，必须被不越界判据拒绝。
    drift_p = bytearray(payload)
    drift_p[p_off] = 200
    bad_arr = np.frombuffer(bytes(drift_p), dtype="<u1", count=nt, offset=p_off)
    check("负对照:部件索引越界必被拒绝",
          not bool(np.all((bad_arr <= 20) | (bad_arr == NO_PART))))
    # 负对照：版本号改成 1，header 判据必须拒绝（v1 解析器另行保留在 core）。
    ver1 = bytearray(payload)
    struct.pack_into("<I", ver1, 4, 1)
    check("负对照:版本号降级为1必被 header 拒绝", not header_ok(bytes(ver1), stats))
    # 负对照：改坏魔数 / 截掉一字节，必须被同一个 header 判据拒绝。
    check("负对照:坏魔数必被 header 判据拒绝",
          not header_ok(b"XXXX" + payload[4:], stats))
    check("负对照:截断一字节必被 header 判据拒绝",
          not header_ok(payload[:-1], stats))

    # 🔴 连通性判据：这是「模型是闭合表面还是散落碎片」的产物级防线。
    # 旧版 stride 抽样实测 shared=0.254 / degenerate=20.9% / median_area=5.5e-6，
    # 三条都会被这里判红；加光照/不透明都救不了几何本身。
    shared, degenerate, median_area = surface_metrics(payload)
    check(f"表面连通(共享边比例 >= 0.90, 实测 {shared:.3f})", shared >= 0.90)
    check(f"退化三角形占比 < 1% (实测 {degenerate:.3f})", degenerate < 0.01)
    check(f"中位三角形面积 >= 1e-4 (实测 {median_area:.3g})", median_area >= 1e-4)
    s_shared, s_degenerate, s_area = surface_metrics(scattered_fixture())
    check("负对照:散落碎片必被连通性判据拒绝",
          not (s_shared >= 0.90 and s_degenerate < 0.01 and s_area >= 1e-4))

    # 🔴 第二条防线：官方 group=2 的 visual mesh 必须**全部**进产物。
    # 旧版按名字挑 18 种外壳时，连通性读数照样是 1.000（每块壳自身闭合），
    # 但连接骨架全丢 ⇒ 头/躯干/腿/脚悬空分离。数量从 MJCF 派生，不写死。
    kinds = stats["visual_mesh_kinds"]
    check(f"官方 visual mesh 全覆盖({stats['used_mesh_kinds']}/{kinds} 种, "
          f"{stats['visual_geom_count']} 个 geom)",
          kinds > 0
          and stats["used_mesh_kinds"] == kinds
          and len(stats["parts"]) == kinds)
    long_gap, total_gap = vertical_coverage(payload)
    check(f"竖直连续覆盖(最长断开 <= 0.01, 实测 {long_gap:.3f})", long_gap <= 0.01)
    check(f"竖直空档总量 <= 0.02 (实测 {total_gap:.3f})", total_gap <= 0.02)
    g_long, g_total = vertical_coverage(gapped_fixture(payload))
    check("负对照:挖掉中段三角形必被竖直覆盖判据拒绝",
          not (g_long <= 0.01 and g_total <= 0.02))

    # 🔴 core JVM 自检与 Android 真机必须看到同一个模型，否则又是一次「自检全绿、
    # 真机降级」的假绿。extract() 写完已校验一次，这里在产物层面再校验一次。
    app_bytes = ANDROID_OUT.read_bytes() if ANDROID_OUT.exists() else b""
    check("core/resources 与 app/assets 字节一致", parity_ok(payload, app_bytes))
    drifted = bytearray(payload)
    drifted[-1] ^= 0xFF
    check("负对照:assets 一字节漂移必被 parity 判据拒绝",
          not parity_ok(payload, bytes(drifted)))

    # 负对照：不存在的 MJCF 必须抛异常；且这条负对照不能污染已生成的产物。
    try:
        extract(Path("/nonexistent.xml"), OUT)
        check("负对照:不存在的 MJCF 应抛异常", False)
    except Exception:
        check("负对照:不存在的 MJCF 应抛异常", True)
    check("负对照未污染已生成产物", OUT.read_bytes() == payload)

    failed = sum(1 for _, ok in checks if not ok)
    for name, ok in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name)
    print(f"SELFTEST: {stats['n_verts']} verts, {stats['n_tris']} tris, "
          f"{len(stats['parts'])} parts")
    print(f"RESULT: {len(checks) - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    stats = extract(MJCF, OUT)
    print(f"提取完成: {stats['n_verts']} 顶点, {stats['n_tris']} 三角形, "
          f"{len(stats['parts'])} 部件")
    print(f"输出: {stats['out']}")
    for name, cnt in sorted(stats["parts"].items()):
        print(f"  {name:25s} {cnt:5d} 三角形")
    return 0


if __name__ == "__main__":
    sys.exit(main())
