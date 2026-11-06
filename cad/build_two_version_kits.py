#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两版 MicroDuck 完整零件包生成器（Radxa Zero 3W / Orange Pi Zero 3W）

数据来源（均需先自行下载，脚本不联网）：
  - 打印几何: out/microduck_replica/打印/microduck-飞特版-BambuStudio2026-11-02.3mf
  - 零件清单: out/microduck_replica/BOM/README.md  (33 项打印件 + 24 项外购件)
  - 装配层级: 安装说明书 PDF 15 组件（已固化在报告中）

诚实边界（重要）：
  * 3MF 里 33 个网格都是「以零件自身中心为原点」的局部坐标（实测中心全为 0,0,0），
    build 里的 43 个 transform 是 Bambu 的「摊开陈列位姿」，不是整机装配位姿。
  * 因此本脚本产出的是【零件齐全性展示包 / 可逐件查看的零件包】，不是整机装配模型。
    整机精确位姿只存在于 SolidWorks .SLDASM（二进制，本机无法解析）。
  * 外购件除电池尺寸有 README 实测背书、轴承尺寸来自 BOM 规格外，
    其余占位体尺寸均为「推定」，仅用于表示"该件存在"，不可用于干涉检查。

用法:
  python cad/build_two_version_kits.py
  python cad/build_two_version_kits.py --3mf <path> --bom <path> --out <dir>
  python cad/build_two_version_kits.py --variant roller   # 轮滑变体清单（几何与 walk 同源）

--variant roller：43 实例 + 占位体几何与 walk 版完全一致（3MF 33 网格已含轮滑件
印刷网格≈物元），差异在清单层：
  * manifest 增"轮滑角色"列：停用 / 替换备选 / 轮滑本体 / 通用
  * 追加 2 行 roll-only 外购占位（合体轮×4、叶片×2，尺寸=object_297/301 bbox）
  口径详见 docs/hardware/microduck-两版轮滑变体组件与装配计划-2026-11-06.md §2
"""

import argparse
import csv
import json
import math
import os
import re
import struct
import zipfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_3MF = os.path.join(ROOT, "out", "microduck_replica", "打印",
                     "microduck-飞特版-BambuStudio2026-11-02.3mf")
D_BOM = os.path.join(ROOT, "out", "microduck_replica", "BOM", "README.md")
D_OUT = os.path.join(ROOT, "out", "microduck_replica", "assembly")

VERTEX_RE = re.compile(
    r'<vertex\s+x="([-\d.eE+]+)"\s+y="([-\d.eE+]+)"\s+z="([-\d.eE+]+)"')
TRI_RE = re.compile(
    r'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"')


# ---------------------------------------------------------------- BOM ----
def parse_qty(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def parse_bom(path):
    printed, purchased, section = [], [], None
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.startswith("## 一、"):
            section = "printed"
        elif line.startswith("## 二、"):
            section = "purchased"
        elif line.startswith("## 三、"):
            section = None
        if not line.startswith("|"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if not c or not c[0].isdigit():
            continue
        if section == "printed" and len(c) >= 6:
            printed.append(dict(no=int(c[0]), name=c[1], file=c[2],
                                material=c[3], qty=parse_qty(c[4]),
                                note=c[5] if len(c) > 5 else ""))
        elif section == "purchased" and len(c) >= 7:
            purchased.append(dict(no=int(c[0]), name=c[1], category=c[2],
                                  qty=parse_qty(c[3]), price=c[4],
                                  note=c[6] if len(c) > 6 else ""))
    return printed, purchased


# ---------------------------------------------------------------- 3MF ----
def parse_3mf(path):
    z = zipfile.ZipFile(path)
    main = z.read("3D/3dmodel.model").decode("utf-8")

    meshes = {}
    for name in z.namelist():
        if not re.match(r"3D/Objects/object_\d+\.model$", name):
            continue
        xml = z.read(name).decode("utf-8")
        verts = [(float(a), float(b), float(c))
                 for a, b, c in VERTEX_RE.findall(xml)]
        tris = [tuple(int(i) for i in t) for t in TRI_RE.findall(xml)]
        if verts and tris:
            meshes[name] = (verts, tris)

    obj_to_mesh, build_items = {}, []
    for attrs, body in re.findall(r"<object\b([^>]*)>(.*?)</object>", main, re.S):
        oid = re.search(r'id="(\d+)"', attrs)
        cp = re.search(r'p:path="([^"]+)"', body)
        if oid and cp:
            obj_to_mesh[int(oid.group(1))] = cp.group(1).lstrip("/")
    for tag in re.findall(r"<item\b([^>]*?)/>", main, re.S):
        oid = re.search(r'objectid="(\d+)"', tag)
        tr = re.search(r'transform="([^"]*)"', tag)
        if oid and tr:
            build_items.append((int(oid.group(1)),
                                [float(x) for x in tr.group(1).split()]))

    refcount = Counter(obj_to_mesh[o] for o, _ in build_items
                       if o in obj_to_mesh)
    return meshes, obj_to_mesh, build_items, refcount


def xform(p, t):
    """3MF row-major 3x3 + translation (12 numbers)."""
    return (t[0]*p[0] + t[1]*p[1] + t[2]*p[2] + t[9],
            t[3]*p[0] + t[4]*p[1] + t[5]*p[2] + t[10],
            t[6]*p[0] + t[7]*p[1] + t[8]*p[2] + t[11])


# ------------------------------------------------------------ geometry ----
class Mesh:
    def __init__(self):
        self.v = []
        self.t = []

    def add(self, verts, tris, t=None):
        base = len(self.v)
        if t is not None:
            self.v.extend(xform(p, t) for p in verts)
        else:
            self.v.extend(verts)
        self.t.extend((base+a, base+b, base+c) for a, b, c in tris)

    def write(self, path):
        with open(path, "wb") as f:
            f.write(b"\0" * 80)
            f.write(struct.pack("<I", len(self.t)))
            pack = struct.pack
            for a, b, c in self.t:
                pa, pb, pc = self.v[a], self.v[b], self.v[c]
                ux, uy, uz = (pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2])
                wx, wy, wz = (pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2])
                nx, ny, nz = (uy*wz-uz*wy, uz*wx-ux*wz, ux*wy-uy*wx)
                ln = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
                f.write(pack("<3f", nx/ln, ny/ln, nz/ln))
                for p in (pa, pb, pc):
                    f.write(pack("<3f", *p))
                f.write(pack("<H", 0))
        return len(self.t)


def box(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0):
    hx, hy = sx/2.0, sy/2.0
    v = [(cx-hx, cy-hy, cz), (cx+hx, cy-hy, cz),
         (cx+hx, cy+hy, cz), (cx-hx, cy+hy, cz),
         (cx-hx, cy-hy, cz+sz), (cx+hx, cy-hy, cz+sz),
         (cx+hx, cy+hy, cz+sz), (cx-hx, cy+hy, cz+sz)]
    t = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
         (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
         (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v, t


def cylinder(d, h, cx=0.0, cy=0.0, cz=0.0, seg=16):
    r = d/2.0
    v = [(cx, cy, cz), (cx, cy, cz+h)]
    for i in range(seg):
        a = 2*math.pi*i/seg
        v.append((cx+r*math.cos(a), cy+r*math.sin(a), cz))
    for i in range(seg):
        a = 2*math.pi*i/seg
        v.append((cx+r*math.cos(a), cy+r*math.sin(a), cz+h))
    t = []
    for i in range(seg):
        j = (i+1) % seg
        lo, lj = 2+i, 2+j
        hi, hj = 2+seg+i, 2+seg+j
        t += [(0, lj, lo), (1, hi, hj), (lo, lj, hj), (lo, hj, hi)]
    return v, t


def ring(outer_d, inner_d, h, cx=0.0, cy=0.0, cz=0.0, seg=16):
    ro, ri = outer_d/2.0, inner_d/2.0
    v = []
    for z in (cz, cz+h):
        for r in (ro, ri):
            for i in range(seg):
                a = 2*math.pi*i/seg
                v.append((cx+r*math.cos(a), cy+r*math.sin(a), z))
    # rings: 0=outer bottom, 1=inner bottom, 2=outer top, 3=inner top
    def idx(r, i, top):
        return (top*2 + r)*seg + i % seg
    t = []
    for i in range(seg):
        j = (i+1) % seg
        ob, ib, ot, it = idx(0, i, 0), idx(1, i, 0), idx(0, i, 1), idx(1, i, 1)
        obj, ibj, otj, itj = idx(0, j, 0), idx(1, j, 0), idx(0, j, 1), idx(1, j, 1)
        t += [(ob, obj, otj), (ob, otj, ot)]                 # outer wall
        t += [(ibj, ib, itj), (ib, it, itj)]                 # inner wall
        t += [(ot, otj, itj), (ot, itj, it)]                 # top face
        t += [(obj, ob, ibj), (ob, ib, ibj)]                 # bottom face
    return v, t


# ------------------------------------------- purchased-part placeholders ----
# (BOM no, label, qty, shape, params, size_source)
# 只有电池与轴承的尺寸有据；其余均为「推定占位」，仅表示该件存在。
PLACEHOLDERS = [
    (2,  "64GB TF 卡",       1,  "box", (15, 11, 1),      "microSD 标准规格（推定）"),
    (3,  "HAT 拓展板",       1,  "box", (65, 30, 1.6),    "RPi Zero HAT 板型（推定）"),
    (4,  "imu_to_dxl 模块",  1,  "box", (25, 25, 1.6),    "推定"),
    (5,  "hub 分线板",       1,  "box", (30, 30, 1.6),    "推定"),
    (7,  "飞特 HD1910M 舵机", 15, "box", (24, 12, 24),     "推定（未查到官方外形尺寸）"),
    (9,  "NP-F550 电池",     1,  "box", (70.8, 38.6, 20.6), "README：上游网格实测 70.8×38.6×20.6"),
    (11, "IMX219 摄像头",    1,  "box", (25, 25, 8),      "推定"),
    (12, "VL53L5X ToF",      1,  "box", (20, 15, 3),      "推定"),
    (13, "扬声器",           1,  "cyl", (20, 5),          "推定 Ø20×5"),
    (14, "轴承 10×15×3",     3,  "ring", (15, 10, 3),     "BOM 规格"),
    (15, "轴承 16×22×4",     11, "ring", (22, 16, 4),     "BOM 规格"),
    (16, "轴承 6×12×3",      4,  "ring", (12, 6, 3),      "BOM 规格"),
]

# 不做几何的外购项，理由写进 manifest
NO_GEOM = {
    6:  ("替代件", "替换部分强度不足的打印件，不额外增加实体"),
    8:  ("外置", "URT-2 调试板，调试时外接，不装入机体"),
    10: ("线束", "AMP2.0 双头转接线，调试用线缆"),
    17: ("耗材", "自攻螺丝 M2×5（1 包）"),
    18: ("耗材", "自攻螺丝 M2×6（1 包）"),
    19: ("耗材", "自攻螺丝 M2×8（1 包）"),
    20: ("耗材", "自攻螺丝 M2.5×6（1 包）"),
    21: ("耗材", "自攻螺丝 M2.5×8（1 包）"),
    22: ("耗材", "乐泰螺纹胶 243"),
    23: ("耗材", "鞋底防滑垫"),
    24: ("外置", "盖世小鸡无线手柄，装机外设备"),
}

CONFIG_DIFF = [
    ("总线波特率", "1 Mbps（Radxa UART2_M0 / /dev/ttyS2）",
     "500 kbps（A733 UART 分频限制）", "软件/寄存器：15 颗舵机 reg6=1"),
    ("串口与 I2C 使能", "系统默认",
     "需开 UART0(Pin8/10) + TWI0(Pin3/5) overlay", "Orange Pi 特有"),
    ("HAT 40-pin", "RPi 兼容", "与 RPi 同脚位（已核），可直插", "两版一致，非差异"),
]


# 轮滑变体角色（依据 docs/hardware/microduck-两版轮滑变体组件与装配计划 §2.1）
def roller_status(no, category):
    """按 BOM 号 + 类别给出该件在轮滑变体中的角色（walk 变体返回空串）。
    注意：打印件与外购件编号空间重叠（外购 20=螺丝 ≠ 打印 20=左脚），必须带类别。"""
    if category == "printed":
        if no in (20, 21):
            return "停用（轮滑版不装左/右脚，由 26/27 V1 踝 + 叶片+轮组取代）"
        if no in (22, 23):
            return "停用（轮滑版保留轮组几何，脚底件退出）"
        if no in (24, 25):
            return "被 26/27 替换（走路踝仅在走路版使用）"
        if no in (26, 27):
            return "轮滑必装（替换走路踝，踝下须配叶片+轮组）"
        if no == 28:
            return "轮滑必装（合体轮胎 TPU×4；轮辋/轮胎合并状态以 3MF 对号为准）"
        if no == 29:
            return "轮滑必装（滚轮叶片×2）"
        if no in (30, 31, 32, 33):
            return "通用（轮滑版沿用）"
    else:  # purchased
        if no == 16:
            return "轮滑必装（轮轴轴承 6×12×3 ×4，外购的轮滑鞋轴承）"
    return "通用"


def build_manifest_rows(printed, purchased, cn, roller_mode):
    """57 项逐行 + 配置差异补充行；roller_mode 时追加「轮滑角色」列。"""
    rows = []
    def col(row, st):
        # 行宽对齐：walk=10 列，roller=11 列（末列空串不写）
        if roller_mode:
            row.append(st)
        return row
    for p in printed:
        st = roller_status(p["no"], "printed") if roller_mode else ""
        rows.append(col(["打印件", p["no"], p["name"], p["qty"], "件",
                     "飞特版 v2.2 通用", "飞特版 v2.2 通用",
                     "真实网格（3MF 33 唯一件 / 43 实例）",
                     "BOM 11-02 版", p["note"] or p["file"]], st))
    for p in purchased:
        no = p["no"]
        rad = cn if no == 1 else p["name"]
        opi = ("Orange Pi Zero 3W（A733）" if no == 1 else p["name"])
        if no in NO_GEOM:
            state, why = NO_GEOM[no]
            src = "不做几何：%s" % why
        elif no == 1:
            state = "占位几何（主控板，两版尺寸不同）"
            src = ("Radxa 65×30 / Orange Pi 65×32（官方中文参数页上限）")
        else:
            state = "占位几何"
            hit = [x for x in PLACEHOLDERS if x[0] == no]
            src = hit[0][5] if hit else "占位"
        st = roller_status(no, "purchased") if roller_mode else ""
        rows.append(col(["外购件", p["no"], p["name"], p["qty"], "件/包",
                     rad, opi, state, src, p["note"]], st))
    for k, (name, r, o, why) in enumerate(CONFIG_DIFF, 1):
        rows.append(col(["配置差异(补充,不计57项)", f"C{k}", name, "-", "-",
                     r, o, "非几何项", why, "软件/电气层，不占 STL 实体"],
                        "轮滑变体：软件 usage 不变"))
    if roller_mode:
        rows.append(["轮滑变体配置(补充)", "Δ1", "走路踝→V1 踝（24/25→26/27）",
                     "1对1", "代换", cn, cn,
                     "非几何项（几何已在 43 实例中）",
                     "轮滑计划 §2.1；禁止与走路件混装",
                     "机械零改动换件", "见各打印行角色"])
        rows.append(["轮滑变体配置(补充)", "Δ2", "action_scale 0.9→0.8 + 轮滑策略",
                     "—", "—", "同左", "同左",
                     "非几何项", "docs/hardware-teardown.en.md:564",
                     "换策略即用，部署链不变", "软件层"])
    return rows


HEADER_WALK = ["类别", "序号", "名称", "数量", "单位",
               "Radxa版", "OrangePi版", "几何状态", "尺寸/依据", "备注"]
HEADER_ROLLER = HEADER_WALK + ["轮滑角色"]


def build_placeholder_mesh(version, include_main=True):
    m = Mesh()
    # 主控板占位体：唯一的两版几何差异（Radxa 65×30 / OrangePi 保守取 65×32）
    boards = {
        "radxa": (65, 30, 1.2, "Radxa Zero 3W：Pi Zero 2W 板型 65×30"),
        "orangepi": (65, 32, 1.2, "Orange Pi Zero 3W：官方中文参数页 65×32（多源写 65×30，取保守上限）"),
    }
    items = []
    if include_main:
        sx, sy, sz, _ = boards[version]
        items.append((1, "主控板", 1, "box", (sx, sy, sz)))
    items += [(no, label, qty, shape, params)
              for no, label, qty, shape, params, _ in PLACEHOLDERS]

    # 摆在 43 个打印实例阵列（X 17..816）右侧，7 列 × 网格 55mm
    cols, step = 6, 55.0
    x0, y0 = 870.0, -280.0
    slot = 0
    for no, label, qty, shape, params in items:
        for k in range(qty):
            cx = x0 + (slot % cols)*step
            cy = y0 + (slot // cols)*step
            slot += 1
            if shape == "box":
                v, t = box(params[0], params[1], params[2],
                           cx-params[0]/2, cy-params[1]/2, 0)
            elif shape == "cyl":
                v, t = cylinder(params[0], params[1], cx, cy, 0)
            else:
                v, t = ring(params[0], params[1], params[2], cx, cy, 0)
            m.add(v, t)
    return m, slot


# ------------------------------------------------------------- output ----
def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--3mf", dest="p3mf", default=D_3MF)
    ap.add_argument("--bom", default=D_BOM)
    ap.add_argument("--out", default=D_OUT)
    ap.add_argument("--variant", choices=["walk", "roller"], default="walk")
    a = ap.parse_args()
    roller_mode = (a.variant == "roller")
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(os.path.join(a.out, "parts"), exist_ok=True)

    printed, purchased = parse_bom(a.bom)
    meshes, obj_to_mesh, items, refcount = parse_3mf(a.p3mf)
    print(f"BOM: printed {len(printed)} items / {sum(p['qty'] for p in printed)} entities"
          f"  | purchased {len(purchased)} items / {sum(p['qty'] for p in purchased)} entities")
    print(f"3MF: {len(meshes)} unique meshes / {len(items)} build instances")

    # 1) 33 个唯一件独立 STL（真实局部几何，逐件可查看）
    index_rows = []
    for path, (v, t) in sorted(meshes.items()):
        short = os.path.basename(path).replace(".model", "")
        m = Mesh()
        m.add(v, t)
        n = m.write(os.path.join(a.out, "parts", short + ".stl"))
        xs, ys, zs = [p[0] for p in v], [p[1] for p in v], [p[2] for p in v]
        index_rows.append([short, len(v), n, refcount.get(path, 0),
                           f"{max(xs)-min(xs):.1f}", f"{max(ys)-min(ys):.1f}",
                           f"{max(zs)-min(zs):.1f}"])
    write_csv(os.path.join(a.out, "PARTS_INDEX.csv"),
              ["网格文件", "顶点数", "三角面数", "3MF引用次数",
               "X尺寸mm", "Y尺寸mm", "Z尺寸mm"], index_rows)

    # 2) 两版 kit：43 个真实打印实例 + 外购件占位体
    base = Mesh()
    for oid, t in items:
        path = obj_to_mesh.get(oid)
        if path in meshes:
            base.add(*meshes[path], t=t)
    allv = base.v
    bb = ([p[0] for p in allv], [p[1] for p in allv], [p[2] for p in allv])
    print(f"43 instances bbox X[{min(bb[0]):.1f},{max(bb[0]):.1f}] "
          f"Y[{min(bb[1]):.1f},{max(bb[1]):.1f}] Z[{min(bb[2]):.1f},{max(bb[2]):.1f}]")

    version_stats = {}
    for version, cn in (("radxa", "Radxa Zero 3W"), ("orangepi", "Orange Pi Zero 3W")):
        kit = Mesh()
        kit.v.extend(base.v)
        kit.t.extend(base.t)
        ph, nslot = build_placeholder_mesh(version)
        off = len(kit.v)
        kit.v.extend(ph.v)
        kit.t.extend((off+x, off+y, off+z) for x, y, z in ph.t)
        out = os.path.join(a.out, f"kit_{version}.stl")
        ntri = kit.write(out)
        version_stats[version] = dict(board=cn, stl=os.path.basename(out),
                                      triangles=ntri, placeholder_entities=nslot,
                                      size_MB=round(os.path.getsize(out)/1e6, 2))

        # 3) manifest：57 项逐项 + 配置差异补充行（+ roller 轮滑角色列）
        rows = build_manifest_rows(printed, purchased, cn, roller_mode)
        write_csv(os.path.join(a.out, f"manifest_{version}.csv"),
                  HEADER_ROLLER if roller_mode else HEADER_WALK, rows)

    # 4) 完整性与边界判定
    check = {
        "variant": a.variant,
        "variant_note": "roller=轮滑变体清单：几何与 walk 完全同源（3MF 33 网格已含轮件），差异在 manifest 轮滑角色列与 Δ1/Δ2 配置行",
        "source": {
            "3mf": os.path.relpath(a.p3mf, ROOT).replace("\\", "/"),
            "bom": os.path.relpath(a.bom, ROOT).replace("\\", "/"),
            "manual": "安装说明书/microduck装配安装说明书.pdf（21页，15组件/34安装步骤）",
        },
        "counts": {
            "bom_items_total": len(printed) + len(purchased),
            "printed_items": len(printed),
            "printed_entities_by_bom_qty": sum(p["qty"] for p in printed),
            "purchased_items": len(purchased),
            "purchased_entities_by_bom_qty": sum(p["qty"] for p in purchased),
            "unique_meshes_in_3mf": len(meshes),
            "build_instances_in_3mf": len(items),
            "assembly_groups_in_3mf": 34,
            "readme_bambu_objects": 52,
            "solidworks_sldprt_files": 59,
            "solidworks_sldasm_files": 18,
            "components_from_manual": 15,
            "servos": 15,
        },
        "count_mismatch": {
            "3mf_instances_vs_bom_entities": len(items) - sum(p["qty"] for p in printed),
            "note": "43 个打印实例 vs BOM 42 个打印实体，差 1；README 另记 52 个 Bambu 对象 / 59 个 SLDPRT。"
                    "口径不同（含 V1 备选踝、独立轮辋+轮胎、辅助对象），逐项映射需按打印盘图人工对号。",
        },
        "versions": version_stats,
        "completeness_verdict": {
            "radxa": "BOM 57 项齐全、33 项打印件零改动；作者 2026-09-13 实机装成，15 颗舵机全在位 → 可装配（有实机背书）",
            "orangepi": "BOM 57 项齐全；打印件与 23 项外购件 100% 沿用，仅替换主控板 1 项 + 3 项软件配置差异 → 可装配（无实机背书）",
        },
        "geometry_limitations": {
            "whole_machine_pose_available": False,
            "reason": "3MF 的 33 个网格中心全为 (0,0,0)，是零件局部坐标；43 个 build transform 与 "
                      "assembly_model.json 的 assemble_transform 均为 Bambu 摊开陈列位姿（X 49~816mm），"
                      "offset_to_assembly 全为 [0,0,0]。整机位姿只在 SolidWorks .SLDASM 二进制里，本机无法解析。",
            "kit_is": "零件齐全性展示包（43 个真实打印实例 + 外购件占位体），不是整机装配模型",
            "placeholder_sizes": "电池/轴承有据，其余为推定；不可用于干涉检查或制造",
            "deprecated_artifact": "microduck_assembled.stl（33 件全部叠在原点的错误合并）作废",
        },
        "solidworks_pack": {
            "release": "v2.2 / SolidWorks-FT2026-10-20.zip / 417656282 bytes",
            "fetch": "github release asset 直连被本地代理 502 挡；gh-proxy.com 镜像与 api.github.com asset 端点可通",
            "contents": "18 SLDASM + 59 SLDPRT + 10 单件 STEP + 贴图；无整机 STEP/STL",
        },
    }
    with open(os.path.join(a.out, "assembly_check.json"), "w", encoding="utf-8") as f:
        json.dump(check, f, ensure_ascii=False, indent=2)

    print("\n=== output ===")
    for version, s in version_stats.items():
        print(f"  kit_{version}.stl  {s['triangles']} tris  {s['size_MB']} MB  "
              f"placeholders={s['placeholder_entities']}")
    print(f"  parts/            {len(meshes)} standalone STL")
    print(f"  PARTS_INDEX.csv / manifest_*.csv / assembly_check.json")


if __name__ == "__main__":
    main()
