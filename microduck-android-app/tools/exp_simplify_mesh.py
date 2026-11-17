#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验：把 DMSH v2 网格用 trimesh QEM 简化到不同面数，导出临时 bin 供线框目视对比。

只写 build/ 下的临时文件，绝不覆盖 core/resources 或 app/assets 的正式产物。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
import trimesh

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "app" / "src" / "main" / "assets" / "duck_mesh.bin"
BUILD = BASE / "build"


def read_dmsh(path: Path):
    b = path.read_bytes()
    magic, ver, nv, nt, nparts = struct.unpack_from("<4sIIII", b, 0)
    assert magic == b"DMSH" and ver == 2, (magic, ver)
    off = 20
    verts = np.frombuffer(b, dtype="<f4", count=nv * 3, offset=off).reshape(nv, 3).copy()
    off += nv * 3 * 4
    tris = np.frombuffer(b, dtype="<i4", count=nt * 3, offset=off).reshape(nt, 3).copy()
    off += nt * 3 * 4
    colors = np.frombuffer(b, dtype="<u4", count=nt, offset=off).copy()
    off += nt * 4
    parts = np.frombuffer(b, dtype=np.uint8, count=nt, offset=off).copy()
    return verts, tris, colors, parts


def write_dmsh(path: Path, verts, tris, colors, parts):
    nv, nt = len(verts), len(tris)
    with path.open("wb") as f:
        f.write(struct.pack("<4sIIII", b"DMSH", 2, nv, nt, 21))
        f.write(verts.astype("<f4").tobytes())
        f.write(tris.astype("<i4").tobytes())
        f.write(colors.astype("<u4").tobytes())
        f.write(parts.astype(np.uint8).tobytes())


def main():
    verts, tris, colors, parts = read_dmsh(SRC)
    print(f"src: {len(verts)} verts, {len(tris)} tris")
    mesh = trimesh.Trimesh(vertices=verts, faces=tris, process=False)

    # 原始每个面的重心 + 其 part，供简化后最近邻映射
    tri_centers = verts[tris].mean(axis=1)  # (nt,3)
    from scipy.spatial import cKDTree
    tree = cKDTree(tri_centers)

    targets = [int(x) for x in (sys.argv[1:] or ["800", "1500", "3000"])]
    for tgt in targets:
        simp = mesh.simplify_quadric_decimation(face_count=tgt)
        sv = np.asarray(simp.vertices, dtype=np.float32)
        sf = np.asarray(simp.faces, dtype=np.int32)
        sc = simp.vertices[simp.faces].mean(axis=1)  # 简化后重心
        _, idx = tree.query(sc)
        sp = parts[idx]
        # 颜色：沿用最近原面的颜色
        scol = colors[idx]
        out = BUILD / f"exp_simp_{tgt}.bin"
        write_dmsh(out, sv, sf, scol, sp)
        uv, uf = np.unique(sf, return_inverse=True)
        print(f"target={tgt}: got {len(sf)} tris, {len(uv)} verts -> {out.name}")


if __name__ == "__main__":
    main()
