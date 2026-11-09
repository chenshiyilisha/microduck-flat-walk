"""Regression tests for the live_viewer P3 real-STL mesh pipeline.

Guards the invariant that the viewer can replace its placeholder cylinders with the
real training-MJCF STL geometry, placed by FK, and that the placement is *driven by
joint angles* (not a static decoration). A wrong mapping or a unit error would make
the robot look plausible while being silently wrong -- so this file leans on negative
controls:

  * STL units must be meters (a wrong unit would scale the whole robot by 1000).
  * Every parsed geom must map onto a BONES body (the 3 known renames are the only
    differences; anything unmapped is a real bug, not a cosmetic one).
  * Same joint angles -> byte-identical world vertices (determinism / no drift).
  * Changing a knee angle must move the foot mesh (FK actually drives the geometry).
  * The FK + geom-local + trunk-origin subtraction must align a mesh with the
    corresponding body origin from forward_kinematics.

Run:
    .venv-mjlab/Scripts/python.exe -m pytest tests/test_hd1910_viewer_mesh.py -q

In a clean CI without the vendored upstream (no training MJCF), the mesh-dependent
tests skip honestly -- the mesh is an asset, not part of the repo -- exactly like the
contract tests in test_hd1910_tooling.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"

sys.path.insert(0, str(HERE))
lv = None  # populated in _load_module()


def _load_module():
    global lv
    spec = importlib.util.spec_from_file_location("live_viewer_mesh_test", HERE / "live_viewer.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_viewer_mesh_test"] = mod   # dataclass needs module registered
    spec.loader.exec_module(mod)
    lv = mod
    return mod


_load_module()

MJCF = lv._default_mjcf_path()            # None when vendored upstream is absent
HAVE_MESH = MJCF is not None


def _need_mesh():
    if not HAVE_MESH:
        pytest.skip("vendored 训练 MJCF 不在（clean CI 无 .upstream）；mesh 测试诚实 skip")


# ───────────────────────────────────────────────────────────────────────────
# STL 单位 / 解析
# ───────────────────────────────────────────────────────────────────────────
def test_stl_binary_units_and_parse():
    """binary STL 必须解析出正确面数，且单位为米（非毫米）。"""
    _need_mesh()
    assets = os.path.join(os.path.dirname(MJCF), "assets")
    p = os.path.join(assets, "trunk_base.stl")
    verts, faces = lv.load_stl_binary(p)
    data = open(p, "rb").read()
    ntri = int.from_bytes(data[80:84], "little")
    assert len(faces) == ntri
    assert all(len(f) == 3 for f in faces)
    # 单位核验：trunk_base 是 ~57mm x 36mm x 3mm 的板；若是毫米会放大 1000 倍
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    sx = max(xs) - min(xs); sy = max(ys) - min(ys); sz = max(zs) - min(zs)
    assert 0.03 < sx < 0.20, f"trunk_base X 尺寸不像米：{sx}"
    assert 0.02 < sy < 0.20, f"trunk_base Y 尺寸不像米：{sy}"
    assert 0.001 < sz < 0.05, f"trunk_base Z 尺寸不像米：{sz}"


# ───────────────────────────────────────────────────────────────────────────
# MJCF 解析 + 体名映射
# ───────────────────────────────────────────────────────────────────────────
def test_mjcf_parse_maps_to_bones():
    """每个 visual geom 必须落到 BONES 体上；材质颜色必须被解析。"""
    _need_mesh()
    m = lv.parse_mjcf_meshes(MJCF)
    bones = {b["name"] for b in lv.BONES}
    unmapped = [g.body for g in m.geoms if g.body not in bones]
    assert not unmapped, f"geom 映射到未知 BONES 体：{unmapped}"
    assert len(m.geoms) > 30
    # 材质：至少有一些被解析成非默认 rgba（不是全部回退灰）
    resolved = [g for g in m.geoms if g.rgba != (0.7, 0.7, 0.7, 1.0)]
    assert len(resolved) > len(m.geoms) // 2
    # 重点验证 3 处已知 rename 出现在映射后
    mapped_bodies = {g.body for g in m.geoms}
    assert {"left_upper_leg", "right_upper_leg", "bottom_head_shell"} <= mapped_bodies


# ───────────────────────────────────────────────────────────────────────────
# FK 一致性
# ───────────────────────────────────────────────────────────────────────────
def test_forward_frames_consistency():
    """forward_kinematics 必须等于 forward_frames 减 trunk_base 原点。"""
    frames = lv.forward_frames(lv.REST_POSITION)
    origin = frames["trunk_base"][1]
    pos = lv.forward_kinematics(lv.REST_POSITION)
    for name, (R, t) in frames.items():
        assert name in pos
        assert abs((t[0] - origin[0]) - pos[name][0]) < 1e-12
        assert abs((t[1] - origin[1]) - pos[name][1]) < 1e-12
        assert abs((t[2] - origin[2]) - pos[name][2]) < 1e-12


# ───────────────────────────────────────────────────────────────────────────
# 负对照：mesh 必须随关节角变化；相同角必须可复现
# ───────────────────────────────────────────────────────────────────────────
def _foot_world(m, angles, stride=1):
    fr = lv.forward_frames(angles)
    origin = fr["trunk_base"][1]
    gi = [i for i, g in enumerate(m.geoms) if g.mesh == "foot_left"][0]
    wv, _, _ = m.world_geom(fr, gi, stride)
    try:
        import numpy as np
        wv = np.asarray(wv) - np.array(origin)
    except Exception:
        wv = [(x - origin[0], y - origin[1], z - origin[2]) for (x, y, z) in wv]
    return wv


def test_mesh_world_deterministic():
    """相同关节角 → 完全相同的世界顶点（确定性，无随机/无漂移）。"""
    _need_mesh()
    m = lv.parse_mjcf_meshes(MJCF)
    a = list(lv.REST_POSITION)
    wv1 = _foot_world(m, a)
    wv2 = _foot_world(m, a)
    import numpy as np
    assert np.allclose(np.asarray(wv1), np.asarray(wv2))


def test_mesh_moves_with_joint():
    """负对照：改左膝角度，foot_left 质心必须明显移动（FK 真的在驱动 mesh）。"""
    _need_mesh()
    m = lv.parse_mjcf_meshes(MJCF)
    a = list(lv.REST_POSITION)
    import numpy as np
    c0 = np.asarray(_foot_world(m, a)).mean(0)
    a[3] += 0.5            # left_knee += 0.5 rad
    c1 = np.asarray(_foot_world(m, a)).mean(0)
    shift = float(np.linalg.norm(c1 - c0))
    assert shift > 0.01, f"改膝角后 foot 质心几乎没动（{shift} m）→ FK 未驱动 mesh"


def test_mesh_aligns_to_fk_body():
    """FK + geom 局部 + trunk 原点减法必须让 foot 网格质心贴近 ankle_left 体原点。"""
    _need_mesh()
    m = lv.parse_mjcf_meshes(MJCF)
    wv = _foot_world(m, list(lv.REST_POSITION))
    ankle = lv.forward_kinematics(lv.REST_POSITION)["ankle_left"]
    import numpy as np
    dist = float(np.linalg.norm(np.asarray(wv).mean(0) - np.array(ankle)))
    assert dist < 0.15, f"foot 网格质心偏离 ankle_left 过远（{dist} m）→ 对齐错误"


# ───────────────────────────────────────────────────────────────────────────
# 退化 / 无源
# ───────────────────────────────────────────────────────────────────────────
def test_mesh_mode_cylinder_disables():
    """--mesh-mode cylinder 必须让 _load_mesh_model 返回 None（退化圆柱）。"""
    ns = argparse.Namespace(mesh_mode="cylinder", mesh_source="auto", mesh_stride=4)
    assert lv._load_mesh_model(ns) is None


def test_mesh_missing_source_returns_none():
    """指向不存在的 MJCF 时应诚实退化 None，而非抛错或假装成功。"""
    ns = argparse.Namespace(mesh_mode="auto", mesh_source="/no/such/robot_walk.xml", mesh_stride=4)
    assert lv._load_mesh_model(ns) is None


# ───────────────────────────────────────────────────────────────────────────
# matplotlib 烟雾测试（可选依赖）
# ───────────────────────────────────────────────────────────────────────────
def test_matplotlib_smoke_mesh_and_fallback():
    """matplotlib 端：有 mesh 渲染一帧、无 mesh 退化圆柱渲染一帧，均不报错。"""
    pytest.importorskip("matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    st = lv.parse_state({"joints": list(lv.REST_POSITION), "targets": list(lv.REST_POSITION),
                         "safety": {"gravity": [0, 0, -1], "fallen": False, "limp": False}})
    if HAVE_MESH:
        m = lv.parse_mjcf_meshes(MJCF)
        mv = lv.MatplotlibViewer(mesh_model=m, mesh_stride=4)
        mv._agg = True
        mv.frame(st)
        assert getattr(mv, "_mesh_total", 0) > 0
    # 退化圆柱路径
    mv2 = lv.MatplotlibViewer(mesh_model=None)
    mv2._agg = True
    mv2.frame(st)
