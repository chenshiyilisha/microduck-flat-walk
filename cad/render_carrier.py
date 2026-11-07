"""Render cad/orangepi_zero3w_carrier.scad as a preview PNG (isometric + 2D top).

Pure matplotlib reconstruction of the OpenSCAD geometry -- no OpenSCAD/cadquery needed.
Geometry parameters MUST stay in sync with the .scad file.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Ellipse, Rectangle, Circle
import numpy as np
import math
import os

# 注册中文字体（避免方块）
for fp in [r"C:/Windows/Fonts/msyh.ttc", r"C:/Windows/Fonts/msyhbd.ttc"]:
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
        plt.rcParams["axes.unicode_minus"] = False
        break

# ---- geometry (kept in sync with orangepi_zero3w_carrier.scad) ----
BOARD_L, BOARD_W, BOARD_R, BOARD_T = 65.0, 32.0, 2.0, 1.2
wall, tol, base_t, rail_h, stand_h = 1.5, 0.3, 2.0, 4.0, 6.0
screw_d, standoff_d = 2.2, 5.0
lug_d, lug_slot, lug_w, lug_ext = 3.2, 8.0, 9.0, 10.0
standoffs = [
    (-(BOARD_L / 2 - 6.0), -(BOARD_W / 2 - 6.0)),
    (BOARD_L / 2 - 6.0, -(BOARD_W / 2 - 6.0)),
    (-(BOARD_L / 2 - 6.0), BOARD_W / 2 - 6.0),
    (BOARD_L / 2 - 6.0, BOARD_W / 2 - 6.0),
]
lugs = [
    (-(BOARD_L / 2 + wall + lug_ext / 2), 0),
    (BOARD_L / 2 + wall + lug_ext / 2, 0),
]
bx_out, by_out = BOARD_L / 2 + wall, BOARD_W / 2 + wall


def rect_corners(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def draw_3d(ax):
    # base plate
    c = rect_corners(-bx_out, -by_out, bx_out, by_out)
    for z in (0.0, base_t):
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        ax.plot(xs, ys, [z] * 5, color="gray", lw=1)
    for p in c[:-1]:
        ax.plot([p[0], p[0]], [p[1], p[1]], [0, base_t], color="gray", lw=0.8)
    # rail
    z2 = base_t + rail_h
    for z in (base_t, z2):
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        ax.plot(xs, ys, [z] * 5, color="lightgray", lw=0.8)
    # standoffs (M2)
    for cx, cy in standoffs:
        zz = base_t
        for ang in range(0, 360, 40):
            a = math.radians(ang)
            x = cx + standoff_d / 2 * math.cos(a); y = cy + standoff_d / 2 * math.sin(a)
            ax.plot([x, x], [y, y], [zz, zz + stand_h], color="gray", lw=0.4)
        th = np.linspace(0, 2 * math.pi, 24)
        ax.plot(cx + standoff_d / 2 * np.cos(th), cy + standoff_d / 2 * np.sin(th),
                [zz + stand_h] * 24, color="gray", lw=0.8)
        ax.plot(cx + screw_d / 2 * np.cos(th), cy + screw_d / 2 * np.sin(th),
                [zz + stand_h] * 24, color="red", lw=1.2)
    # lugs (rect ear + slot)
    for cx, cy in lugs:
        ex0, ex1 = cx - lug_ext / 2, cx + lug_ext / 2
        ey0, ey1 = cy - lug_w / 2, cy + lug_w / 2
        ce = rect_corners(ex0, ey0, ex1, ey1)
        for z in (0.0, base_t):
            xs = [p[0] for p in ce]; ys = [p[1] for p in ce]
            ax.plot(xs, ys, [z] * 5, color="gray", lw=1)
        for p in ce[:-1]:
            ax.plot([p[0], p[0]], [p[1], p[1]], [0, base_t], color="gray", lw=0.8)
        th = np.linspace(0, 2 * math.pi, 18)
        for exx in (cx - lug_slot / 2, cx + lug_slot / 2):
            ax.plot(exx + lug_d / 2 * np.cos(th), cy + lug_d / 2 * np.sin(th),
                    [base_t] * 18, color="blue", lw=1)
        ax.plot([cx - lug_slot / 2, cx + lug_slot / 2], [cy, cy],
                [base_t, base_t], color="blue", lw=1)
    # board ref (green, not printed)
    cb = rect_corners(-BOARD_L / 2, -BOARD_W / 2, BOARD_L / 2, BOARD_W / 2)
    zt = base_t + stand_h
    xs = [p[0] for p in cb]; ys = [p[1] for p in cb]
    ax.plot(xs, ys, [zt] * 5, color="green", lw=0.6, alpha=0.5)
    ax.plot(xs, ys, [zt + BOARD_T] * 5, color="green", lw=0.6, alpha=0.5)
    for p in cb[:-1]:
        ax.plot([p[0], p[0]], [p[1], p[1]], [zt, zt + BOARD_T], color="green", lw=0.4, alpha=0.5)
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)"); ax.set_zlabel("Z (mm)")
    ax.view_init(elev=22, azim=-58)


def draw_2d(ax):
    ax.add_patch(Rectangle((-bx_out, -by_out), 2 * bx_out, 2 * by_out,
                           facecolor="lightgray", edgecolor="gray", lw=1))
    for cx, cy in standoffs:
        ax.add_patch(Circle((cx, cy), standoff_d / 2, fill=False, edgecolor="gray", lw=1))
        ax.add_patch(Circle((cx, cy), screw_d / 2, fill=False, edgecolor="red", lw=1.5))
    for cx, cy in lugs:
        ax.add_patch(Ellipse((cx, cy), lug_slot + lug_d, lug_d,
                             fill=False, edgecolor="blue", lw=1.5))
    ax.set_xlim(-bx_out - 12, bx_out + 12)
    ax.set_ylim(-by_out - 6, by_out + 6)
    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)"); ax.set_ylabel("Y (mm)")
    ax.set_title("顶视图 (红=M2支柱孔 蓝=连接耳长圆孔)")


def main():
    fig = plt.figure(figsize=(13, 6))
    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax2 = fig.add_subplot(1, 2, 2)
    draw_3d(ax1)
    draw_2d(ax2)
    fig.suptitle("Orange Pi Zero 3W 载板 (开顶卡框 + M2支柱 + 通用长圆孔耳)",
                 fontsize=13)
    out = os.path.join(os.path.dirname(__file__), "build",
                       "orangepi_zero3w_carrier_preview.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
