#!/usr/bin/env python3
# ============================================================================
# Orange Pi Zero 3W 载板 STL 生成器 (纯 Python, 无外部依赖)
# ----------------------------------------------------------------------------
# 动机: 本机 Windows 沙箱无 OpenSCAD, 且 files.openscad.org 的 Linux 包跑不了。
#       这份脚本用最朴素的"盒体 + 圆柱/管 + 挤出多边形"拼出与
#       orangepi_zero3w_carrier.scad 同参数的可打印网格, 直接写二进制 STL。
#
# 与 scad 的偏差 (均为打印友好 / 可接受的简化):
#   1. 底板为实心圆角板, 不穿透 M2 通孔 —— 支柱(管)自带 M2 孔, 螺丝穿过支柱
#      即可压紧板; 若需贯穿底板可自行打孔。
#   2. 连接耳长圆孔用"矩形框"实现 (4 盒拼成框), 端部为直角而非半圆 —— M3 适配。
#   3. 定位边轨用 4 个盒体近似 (开顶、不挡顶部接插件)。
#
# 参数全部抄自 orangepi_zero3w_carrier.scad, 改 scad 时同步改此处。
# ============================================================================

import struct
import math

# ---------- 参数 (与 scad 一致) ----------
BOARD_L = 65.0
BOARD_W = 32.0
BOARD_T = 1.2
BOARD_R = 2.0

wall    = 2.0
base_t  = 2.0
rail_h  = BOARD_T + 1.0   # 2.2
stand_h = 2.0
screw_d = 2.2
tol     = 0.3

standoffs = [
    [-(BOARD_L/2 - 6.0), -(BOARD_W/2 - 6.0)],
    [ (BOARD_L/2 - 6.0), -(BOARD_W/2 - 6.0)],
    [-(BOARD_L/2 - 6.0),  (BOARD_W/2 - 6.0)],
    [ (BOARD_L/2 - 6.0),  (BOARD_W/2 - 6.0)],
]

lug_d    = 3.2
lug_slot = 8.0
lug_w    = 9.0
lug_ext  = 10.0
lugs = [
    [-(BOARD_L/2 + wall + lug_ext/2), 0],
    [ (BOARD_L/2 + wall + lug_ext/2), 0],
]

# ---------- 网格容器 ----------
# 每项: (normal_xyz_tuple, a_xyz, b_xyz, c_xyz)
TRIS = []

def vsub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def vcross(a, b):
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])

def vdot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def vnorm(a):
    ln = math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2])
    if ln < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0]/ln, a[1]/ln, a[2]/ln)

def _orient(a, b, c, hint):
    """返回 (a,b,c) 或 (a,c,b), 使法线 dot hint > 0。"""
    n = vcross(vsub(b, a), vsub(c, a))
    if vdot(n, hint) < 0:
        return (a, c, b)
    return (a, b, c)

def add_tri(a, b, c, hint):
    a, b, c = _orient(a, b, c, hint)
    n = vnorm(vcross(vsub(b, a), vsub(c, a)))
    TRIS.append((n, a, b, c))

def add_quad(a, b, c, d, hint):
    add_tri(a, b, c, hint)
    add_tri(a, c, d, hint)

def add_box(cx, cy, cz, sx, sy, sz):
    """居中盒体, 朝外法线。"""
    hx, hy, hz = sx/2, sy/2, sz/2
    x0, x1 = cx-hx, cx+hx
    y0, y1 = cy-hy, cy+hy
    z0, z1 = cz-hz, cz+hz
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    add_quad(v[4], v[5], v[6], v[7], (0,0, 1))
    add_quad(v[0], v[3], v[2], v[1], (0,0,-1))
    add_quad(v[1], v[5], v[6], v[2], ( 1,0,0))
    add_quad(v[0], v[4], v[7], v[3], (-1,0,0))
    add_quad(v[3], v[7], v[6], v[2], (0, 1,0))
    add_quad(v[0], v[1], v[5], v[4], (0,-1,0))

def rounded_rect_polygon(l, w, r, seg=8):
    """返回凸多边形点列表 [(x,y),...], 中心在原点。"""
    r = min(r, min(l, w)/2 - 1e-3)
    pts = []
    hw, hh = l/2 - r, w/2 - r
    corner_centers = [( hw, hh), (-hw, hh), (-hw,-hh), ( hw,-hh)]
    angles = [(0, math.pi/2), (math.pi/2, math.pi),
              (math.pi, math.pi*1.5), (math.pi*1.5, math.pi*2)]
    for (cx, cy), (a0, a1) in zip(corner_centers, angles):
        for i in range(seg+1):
            t = a0 + (a1-a0)*i/seg
            pts.append((cx + r*math.cos(t), cy + r*math.sin(t)))
    return pts

def add_extruded_polygon(poly, z0, z1):
    """凸多边形挤出 (用扇形三角化)。"""
    n = len(poly)
    cx = sum(p[0] for p in poly)/n
    cy = sum(p[1] for p in poly)/n
    cen = (cx, cy)
    for i in range(n):
        a = poly[i]
        b = poly[(i+1) % n]
        add_tri((a[0],a[1],z0), (b[0],b[1],z0), (cen[0],cen[1],z0), (0,0,-1))
        add_tri((a[0],a[1],z1), (cen[0],cen[1],z1), (b[0],b[1],z1), (0,0, 1))
        mid = ((a[0]+b[0])/2, (a[1]+b[1])/2, 0)
        hint = (mid[0]-cen[0], mid[1]-cen[1], 0)
        add_quad((a[0],a[1],z0), (b[0],b[1],z0), (b[0],b[1],z1), (a[0],a[1],z1), hint)

def add_cylinder(cx, cy, z0, z1, r, seg=24):
    for i in range(seg):
        a0 = 2*math.pi*i/seg
        a1 = 2*math.pi*(i+1)/seg
        p0 = (cx + r*math.cos(a0), cy + r*math.sin(a0))
        p1 = (cx + r*math.cos(a1), cy + r*math.sin(a1))
        hint = (math.cos((a0+a1)/2), math.sin((a0+a1)/2), 0)
        add_quad((p0[0],p0[1],z0), (p1[0],p1[1],z0), (p1[0],p1[1],z1), (p0[0],p0[1],z1), hint)
    cen1 = (cx, cy, z1)
    cen0 = (cx, cy, z0)
    for i in range(seg):
        a0 = 2*math.pi*i/seg; a1 = 2*math.pi*(i+1)/seg
        p0 = (cx + r*math.cos(a0), cy + r*math.sin(a0), z1)
        p1 = (cx + r*math.cos(a1), cy + r*math.sin(a1), z1)
        add_tri(cen1, p0, p1, (0,0, 1))
        p0b = (cx + r*math.cos(a0), cy + r*math.sin(a0), z0)
        p1b = (cx + r*math.cos(a1), cy + r*math.sin(a1), z0)
        add_tri(cen0, p1b, p0b, (0,0,-1))

def add_tube(cx, cy, z0, z1, r_out, r_in, seg=24):
    """管: 外壁(+), 内壁(-), 顶/底环。"""
    for i in range(seg):
        a0 = 2*math.pi*i/seg; a1 = 2*math.pi*(i+1)/seg
        o0 = (cx + r_out*math.cos(a0), cy + r_out*math.sin(a0))
        o1 = (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1))
        i0 = (cx + r_in*math.cos(a0),  cy + r_in*math.sin(a0))
        i1 = (cx + r_in*math.cos(a1),  cy + r_in*math.sin(a1))
        hout = (math.cos((a0+a1)/2), math.sin((a0+a1)/2), 0)
        add_quad((o0[0],o0[1],z0),(o1[0],o1[1],z0),(o1[0],o1[1],z1),(o0[0],o0[1],z1), hout)
        add_quad((i0[0],i0[1],z0),(i0[0],i0[1],z1),(i1[0],i1[1],z1),(i1[0],i1[1],z0), (-hout[0],-hout[1],-hout[2]))
    for i in range(seg):
        a0 = 2*math.pi*i/seg; a1 = 2*math.pi*(i+1)/seg
        o0 = (cx + r_out*math.cos(a0), cy + r_out*math.sin(a0))
        o1 = (cx + r_out*math.cos(a1), cy + r_out*math.sin(a1))
        i0 = (cx + r_in*math.cos(a0),  cy + r_in*math.sin(a0))
        i1 = (cx + r_in*math.cos(a1),  cy + r_in*math.sin(a1))
        add_quad((o0[0],o0[1],z1),(i0[0],i0[1],z1),(i1[0],i1[1],z1),(o1[0],o1[1],z1), (0,0, 1))
        add_quad((o0[0],o0[1],z0),(o1[0],o1[1],z0),(i1[0],i1[1],z0),(i0[0],i0[1],z0), (0,0,-1))

# ============================================================================
# 组装
# ============================================================================
# 1) 底板 (圆角矩形, 实心)
base_poly = rounded_rect_polygon(BOARD_L + 2*wall, BOARD_W + 2*wall, BOARD_R + wall, seg=6)
add_extruded_polygon(base_poly, 0.0, base_t)

# 2) 定位边轨 (4 盒近似开顶框)
outer_hL, outer_hW = (BOARD_L + 2*wall)/2, (BOARD_W + 2*wall)/2
inner_hL, inner_hW = (BOARD_L + 2*tol)/2, (BOARD_W + 2*tol)/2
zc = base_t + rail_h/2
# 左右壁 (x 方向长条)
add_box(0,  (outer_hW + inner_hW)/2, zc, (outer_hL-inner_hL)*2 + 0.001, outer_hW-inner_hW, rail_h)
add_box(0, -(outer_hW + inner_hW)/2, zc, (outer_hL-inner_hL)*2 + 0.001, outer_hW-inner_hW, rail_h)
# 上下壁 (y 方向长条)
add_box( (outer_hL + inner_hL)/2, 0, zc, outer_hL-inner_hL, (outer_hW-inner_hW)*2 + 0.001, rail_h)
add_box(-(outer_hL + inner_hL)/2, 0, zc, outer_hL-inner_hL, (outer_hW-inner_hW)*2 + 0.001, rail_h)

# 3) 四角支柱 (管, 带 M2 通孔)
for (sx, sy) in standoffs:
    add_tube(sx, sy, base_t, base_t + stand_h, r_out=2.5, r_in=screw_d/2, seg=20)

# 4) 左右连接耳 (矩形框 = 长圆孔)
for (lx, ly) in lugs:
    x0e, x1e = lx - lug_ext/2, lx + lug_ext/2
    y0e, y1e = ly - lug_w/2,   ly + lug_w/2
    s0x, s1x = lx - lug_slot/2, lx + lug_slot/2   # 槽 x 范围
    sy0, sy1 = ly - lug_d/2,    ly + lug_d/2       # 槽 y 范围
    cz = base_t/2
    add_box(lx, (sy1 + y1e)/2, cz, lug_ext, y1e - sy1, base_t)   # 上条
    add_box(lx, (y0e + sy0)/2, cz, lug_ext, sy0 - y0e, base_t)   # 下条
    add_box((x0e + s0x)/2, ly, cz, s0x - x0e, sy1 - sy0, base_t) # 左条
    add_box((s1x + x1e)/2, ly, cz, x1e - s1x, sy1 - sy0, base_t) # 右条

# ============================================================================
# 写二进制 STL
# ============================================================================
def write_binary_stl(path, tris):
    with open(path, 'wb') as f:
        f.write(b'\0' * 80)
        f.write(struct.pack('<I', len(tris)))
        for (n, a, b, c) in tris:
            f.write(struct.pack('<3f', *n))
            f.write(struct.pack('<3f', *a))
            f.write(struct.pack('<3f', *b))
            f.write(struct.pack('<3f', *c))
            f.write(struct.pack('<H', 0))

OUT = 'cad/orangepi_zero3w_carrier.stl'
write_binary_stl(OUT, TRIS)

xs = [p[0] for t in TRIS for p in t[1:]]
ys = [p[1] for t in TRIS for p in t[1:]]
zs = [p[2] for t in TRIS for p in t[1:]]
print(f"written {OUT}: {len(TRIS)} triangles; "
      f"bbox X[{min(xs):.1f},{max(xs):.1f}] "
      f"Y[{min(ys):.1f},{max(ys):.1f}] "
      f"Z[{min(zs):.1f},{max(zs):.1f}] mm")
