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

# 三角形预算：Canvas 2D 每帧对每个三角形 drawPath 一次（1s tick 旋转 + 30ms 拖动节流）。
# 旧版 stride 抽样是 7500 面但全是碎片；顶点聚类用相同量级预算画出**闭合表面**。
# 二分搜索最细的聚类 cell，使输出 <= TARGET_TRIS，MJCF/STL 面数漂移时也不会爆量。
TARGET_TRIS = 12000
CELL_MIN = 0.002
CELL_MAX = 0.030
CELL_ITERS = 20


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
    all_verts: list[np.ndarray] = []
    all_faces: list[np.ndarray] = []
    all_colors: list[np.ndarray] = []
    face_codes: list[np.ndarray] = []
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

    if not all_verts:
        raise RuntimeError("未提取到任何 group=2 visual 网格，请检查 MJCF 的 geom_group")

    v = np.concatenate(all_verts, axis=0)
    f = np.concatenate(all_faces, axis=0)
    c = np.concatenate(all_colors, axis=0)
    codes = np.concatenate(face_codes, axis=0)
    raw_faces = int(f.shape[0])

    # 🔴 二分搜索最细的 cell，使聚类后三角形数 <= TARGET_TRIS。
    # 比固定 cell 稳：MJCF/STL 换版本导致原始面数变化时，输出规模仍受控。
    lo, hi = CELL_MIN, CELL_MAX
    centers, cf, cc, keep = _cluster(v, f, c, hi)
    for _ in range(CELL_ITERS):
        mid_cell = (lo + hi) / 2.0
        t_centers, t_faces, t_colors, t_keep = _cluster(v, f, c, mid_cell)
        if t_faces.shape[0] > TARGET_TRIS:
            lo = mid_cell                       # 太细 ⇒ 面太多 ⇒ 放大 cell
        else:
            hi = mid_cell                       # 够粗 ⇒ 试着更细
            centers, cf, cc, keep = t_centers, t_faces, t_colors, t_keep
    cell_used = hi

    if cf.shape[0] == 0:
        raise RuntimeError("顶点聚类后无有效三角形")
    if cf.shape[0] > TARGET_TRIS:
        raise RuntimeError(f"聚类后三角形 {cf.shape[0]} 超出预算 {TARGET_TRIS}")

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
    for code, cnt in zip(*np.unique(codes[keep], return_counts=True)):
        part_tri_counts[inv_code[int(code)]] = int(cnt)

    # 写二进制：header / 顶点表 / 三角形索引 / 每三角形颜色
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fp:
        fp.write(struct.pack("<4sIII", b"DMSH", 1, n_verts, n_tris))
        fp.write(centered.tobytes())
        fp.write(cf.astype(np.int32).tobytes())
        fp.write(cc.astype(np.uint32).tobytes())

    # 🔴 双写 + 字节级一致性校验：两份资源一旦漂移，真机与 JVM 自检看到的就不是
    # 同一个模型（这正是「core 自检全绿、真机降级」这类假绿的温床）。
    ANDROID_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = out_path.read_bytes()
    ANDROID_OUT.write_bytes(payload)
    if ANDROID_OUT.read_bytes() != payload:
        raise RuntimeError("duck_mesh.bin 双写字节不一致：core/resources 与 app/assets")

    return {
        "n_verts": n_verts, "n_tris": n_tris,
        "parts": part_tri_counts, "out": str(out_path),
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
    """第二条独立算法：直接 struct 解析字节，不复用 extract() 自己的计数变量。"""
    try:
        magic, ver, nv, nt = struct.unpack_from("<4sIII", buf, 0)
        # header(16) + 顶点(3*f32) + 三角形索引(3*i32) + 每三角形颜色(u32)
        expected_len = 16 + nv * 3 * 4 + nt * 3 * 4 + nt * 4
        return (magic == b"DMSH" and ver == 1
                and nv == stats["n_verts"] and nt == stats["n_tris"]
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
    _, _, nv, nt = struct.unpack_from("<4sIII", buf, 0)
    off = 16
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
    return (struct.pack("<4sIII", b"DMSH", 1, nv, nt)
            + v.tobytes() + t.tobytes() + c.tobytes())


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
    _, _, nv, nt = struct.unpack_from("<4sIII", buf, 0)
    off = 16
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
    _, ver, nv, nt = struct.unpack_from("<4sIII", buf, 0)
    off = 16
    vbytes = buf[off:off + nv * 3 * 4]
    off_t = off + nv * 3 * 4
    t = np.frombuffer(buf, dtype="<i4", count=nt * 3, offset=off_t).reshape(-1, 3).copy()
    c = np.frombuffer(buf, dtype="<u4", count=nt, offset=off_t + nt * 3 * 4).copy()
    v = np.frombuffer(vbytes, dtype="<f4").reshape(-1, 3)
    z = v[:, 2]
    lo, hi = float(z.min()), float(z.max())
    zc = (z[t].mean(axis=1) - lo) / (hi - lo) if hi > lo else np.zeros(len(t))
    keep = (zc < 0.35) | (zc > 0.65)
    tk, ck = t[keep], c[keep]
    return (struct.pack("<4sIII", b"DMSH", ver, nv, len(tk))
            + vbytes + tk.astype("<i4").tobytes() + ck.astype("<u4").tobytes())


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
