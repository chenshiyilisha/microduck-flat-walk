# -*- coding: utf-8 -*-
"""
渲染 cad/orangepi_zero3w_carrier.scad 定义的那块载板的"效果图"。
本机无 OpenSCAD/cadquery, 故用 matplotlib 按 scad 参数重建几何并做等距渲染。
输出: cad/orangepi_zero3w_carrier_preview.png
参数与 scad 文件保持一致 (改图先改 scad, 这里只是看效果)。
"""
import os
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# 注册一个系统中文字体 (避免标注乱码)
for fp in (r"C:/Windows/Fonts/msyh.ttc", r"C:/Windows/Fonts/msyhbd.ttc",
           r"C:/Windows/Fonts/simhei.ttf"):
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        break

# ---- 参数 (与 orangepi_zero3w_carrier.scad 同步) ----
BOARD_L, BOARD_W, BOARD_T, BOARD_R = 65.0, 32.0, 1.2, 2.0
wall, base_t, rail_h = 2.0, 2.0, BOARD_T + 1.0
stand_h, screw_d, tol = 2.0, 2.2, 0.3
# 坐标系: 板中心在原点; 四角内缩 6mm
standoffs = [(-(BOARD_L / 2 - 6.0), -(BOARD_W / 2 - 6.0)),
             (BOARD_L / 2 - 6.0, -(BOARD_W / 2 - 6.0)),
             (-(BOARD_L / 2 - 6.0), BOARD_W / 2 - 6.0),
             (BOARD_L / 2 - 6.0, BOARD_W / 2 - 6.0)]
lug_d = 3.2
# 连接耳: 左右伸出, 居中 (y=0)
lugs = [(-(BOARD_L / 2 + wall + 4.0), 0), (BOARD_L / 2 + wall + 4.0, 0)]

LIGHT = np.array([0.4, 0.5, 0.78]); LIGHT /= np.linalg.norm(LIGHT)


def rr_pts(l, w, r, seg=8):
    """圆角矩形轮廓, 闭合 (逆时针采样)。"""
    r2 = min(r, min(l, w) / 2 - 0.01)
    hw, hh = l / 2, w / 2
    corners = [(hw - r2, hh - r2), (-hw + r2, hh - r2),
               (-hw + r2, -hh + r2), (hw - r2, -hh + r2)]
    a0 = [0, 90, 180, 270]
    pts = []
    for (cx, cy), a in zip(corners, a0):
        for k in range(seg + 1):
            ang = (a + k * 90.0 / seg) * math.pi / 180
            pts.append((cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)))
    return pts


def extrude(pts, z0, z1):
    n = len(pts)
    out = []
    for i in range(n):
        j = (i + 1) % n
        out.append([(*pts[i], z0), (*pts[j], z0), (*pts[j], z1), (*pts[i], z1)])
    out.append([(*p, z1) for p in pts])
    out.append([(*p, z0) for p in pts])
    return out


def ring(pts_out, pts_in, z):
    n = len(pts_out)
    out = []
    for i in range(n):
        j = (i + 1) % n
        out.append([(*pts_out[i], z), (*pts_out[j], z), (*pts_in[j], z), (*pts_in[i], z)])
    return out


def cylinder(cx, cy, r, h, z0, seg=20):
    pts = [(cx + r * math.cos(2 * math.pi * k / seg),
            cy + r * math.sin(2 * math.pi * k / seg)) for k in range(seg)]
    return extrude(pts, z0, z0 + h)


# ---- 组装几何 (3D) ----
polys = []
out_base = rr_pts(BOARD_L + 2 * wall, BOARD_W + 2 * wall, BOARD_R + wall)
polys += [(p, (0.55, 0.57, 0.62)) for p in extrude(out_base, 0, base_t)]
out_rail = rr_pts(BOARD_L + 2 * wall, BOARD_W + 2 * wall, BOARD_R + wall)
in_rail = rr_pts(BOARD_L + 2 * tol, BOARD_W + 2 * tol, BOARD_R)
polys += [(p, (0.50, 0.52, 0.57)) for p in extrude(out_rail, base_t, base_t + rail_h)]
polys += [(p, (0.50, 0.52, 0.57)) for p in ring(out_rail, in_rail, base_t + rail_h)]
for sx, sy in standoffs:
    polys += [(p, (0.72, 0.74, 0.78)) for p in cylinder(sx, sy, 2.5, stand_h, base_t)]
for gx, gy in lugs:
    polys += [(p, (0.45, 0.47, 0.52)) for p in cylinder(gx, gy, 4.0, base_t, 0)]
br = rr_pts(BOARD_L, BOARD_W, BOARD_R)
board_polys = [(p, (0.10, 0.70, 0.25)) for p in
               extrude(br, base_t + stand_h, base_t + stand_h + BOARD_T)]


def shade(poly, base):
    p = np.array(poly, "float64")
    n = np.cross(p[1] - p[0], p[2] - p[0])
    ln = np.linalg.norm(n)
    if ln < 1e-9:
        n = np.array([0, 0, 1])
    else:
        n = n / ln
    intensity = 0.35 + 0.65 * abs(np.dot(n, LIGHT))
    return tuple(min(1.0, c * intensity) for c in base)


def add_coll(ax, plist, alpha=0.96):
    verts = [np.array(p) for p, _ in plist]
    cols = [shade(p, b) for p, b in plist]
    pc = Poly3DCollection(verts, alpha=alpha, facecolor=cols,
                          linewidths=0.25, edgecolors=(0.2, 0.2, 0.2, 0.8))
    ax.add_collection3d(pc)


span_x = BOARD_L + 2 * wall + 16
span_y = BOARD_W + 2 * wall + 16
span_z = base_t + stand_h + BOARD_T + 3

fig = plt.figure(figsize=(12, 5.4), dpi=150)
ax1 = fig.add_subplot(1, 2, 1, projection="3d")
ax2 = fig.add_subplot(1, 2, 2)

# 等距立体图
add_coll(ax1, polys, alpha=0.96)
add_coll(ax1, board_polys, alpha=0.38)
ax1.view_init(elev=24, azim=32)
ax1.set_box_aspect((span_x, span_y, span_z))
ax1.set_xlim(-span_x / 2, span_x / 2)
ax1.set_ylim(-span_y / 2, span_y / 2)
ax1.set_zlim(0, span_z)
ax1.set_axis_off()
ax1.set_title("Orange Pi Zero 3W 载板 - 等距预览", fontsize=11, pad=4)

# 2D 俯视图 (无遮挡, 精确标孔位)
ax2.set_aspect("equal")
ax2.axis("off")
bo = rr_pts(BOARD_L + 2 * wall, BOARD_W + 2 * wall, BOARD_R + wall)
ax2.plot([p[0] for p in bo] + [bo[0][0]], [p[1] for p in bo] + [bo[0][1]],
         color="gray", lw=1.6)
bb = rr_pts(BOARD_L, BOARD_W, BOARD_R)
ax2.plot([p[0] for p in bb] + [bb[0][0]], [p[1] for p in bb] + [bb[0][1]],
         color="green", lw=1.3, ls="--")
for (sx, sy) in standoffs:
    ax2.add_patch(Circle((sx, sy), 2.5, fill=False, ec="red", lw=1.0))
    ax2.add_patch(Circle((sx, sy), screw_d / 2, fill=False, ec="red", lw=1.8))
for (gx, gy) in lugs:
    ax2.add_patch(Circle((gx, gy), 4.0, fill=False, ec="blue", lw=1.0))
    ax2.add_patch(Circle((gx, gy), lug_d / 2, fill=False, ec="blue", lw=1.8))
ax2.set_xlim(-span_x / 2, span_x / 2)
ax2.set_ylim(-span_y / 2, span_y / 2)
ax2.set_title("俯视图 (红=M2支柱孔及外径, 蓝=M3连接耳及孔)", fontsize=11, pad=4)

fig.text(0.015, 0.06,
         "灰 = 打印托架 (底板+定位边轨+支柱+连接耳)\n"
         "绿(虚线) = Orange Pi 板轮廓 (参考)\n"
         "红 = 4x M2 支柱 (外圈 d5 / 孔 d2.2)\n"
         "蓝 = 2x M3 连接耳 (外圈 d8 / 孔 d3.2)",
         fontsize=8.5, va="bottom")
fig.text(0.50, 0.03,
         "注意: 尺寸待核对 - 板角倒圆 / 真实安装孔位 / 与机身螺接位, 见 scad 文件 CHECKLIST",
         fontsize=8, color="crimson", ha="center")

out_png = "cad/orangepi_zero3w_carrier_preview.png"
fig.savefig(out_png, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", out_png)
