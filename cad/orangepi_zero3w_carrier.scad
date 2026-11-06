// ============================================================================
// Orange Pi Zero 3W 载板 / 托架  —  参数化 OpenSCAD 源
// ============================================================================
// 性质: 本仓"从零自建"的新零件, 不修改 fanhao375/microduck-replica-cad 的
//       原始 SolidWorks/STEP (本机也无 SW/FreeCAD). 输出 .scad -> OpenSCAD 渲染 -> STL 可打印.
//
// 板尺寸来源: 香橙派官网参数页 (orangepi.cn/.../Orange-Pi-Zero-3W.html)
//   PCB 65 x 32 x 1.2 mm. 英文详情页有一处写 "30mm x 65mm", 以参数页 65x32 为准,
//   该 2mm 差异列为待核对项.
//
// 用途: 替代飞特版 (v2.2) 原本按 Raspberry Pi Zero 2W 做的机内托架, 把 Orange Pi
//       Zero 3W (A733) 固定到 MicroDuck 机身. 飞特版原托架按 RPi 引脚/板型建模,
//       与 Orange Pi 不兼容, 故重建.
//
// 重要接口警告 (已反复确认):
//   Orange Pi 的 40-pin 不是 Raspberry Pi 引脚定义 -> 之前方案里的 "RPi 形态 HAT
//   (kissqy / DuckBuddy)" 在引脚上不 drop-in. 这块载板按 "直接固定 + 飞线/转接载板"
//   思路做, 不预设原 HAT 能插上. 是否保留 HAT 由后续硬件决策定.
//
// 待核对 / 待定 (改前必须确认, 见文件末尾 CHECKLIST):
//   1. 板角倒圆半径 BOARD_R (官网未给, 暂估 2.0)
//   2. 真实安装孔位 (本件用四角内缩支柱, 非官方孔位; Pi Zero 兼容孔位待核)
//   3. 载板与机身的螺接接口 (lugs 位置/数量) 需对照飞特版躯干结构 STEP 后定
//   4. 各接插件 (Mini HDMI / USB-C / TF / CSI FPC / PCIe FPC / 风扇) 的精确位置
// ============================================================================

// ---------- 板参数 (官方, 已核对) ----------
BOARD_L = 65.0;   // X 方向长度 mm
BOARD_W = 32.0;   // Y 方向宽度 mm
BOARD_T = 1.2;    // 板厚 mm
BOARD_R = 2.0;    // 板角倒圆 (估算, 待核对官方顶视图)

// ---------- 载板参数 (可调) ----------
wall    = 2.0;    // 边框壁厚
base_t  = 2.0;    // 底板厚
rail_h  = BOARD_T + 1.0;  // 定位边轨高 (仅包住板边, 不挡顶部接插件)
stand_h = 2.0;    // 支柱高 (板底离底板)
screw_d = 2.2;    // M2 通孔直径 (间隙)
tol     = 0.3;    // 板与框配合间隙

// 坐标系: 板中心在原点 (rounded_rect 以原点为中心), 故 standoffs/lugs 用 ±半宽.
// 支柱位置: 四角内缩 6mm. 真实安装孔位待核对 (Pi Zero 兼容 or 官方顶视图)
standoffs = [
  [ -(BOARD_L/2 - 6.0), -(BOARD_W/2 - 6.0) ],
  [  (BOARD_L/2 - 6.0), -(BOARD_W/2 - 6.0) ],
  [ -(BOARD_L/2 - 6.0),  (BOARD_W/2 - 6.0) ],
  [  (BOARD_L/2 - 6.0),  (BOARD_W/2 - 6.0) ]
];

// 与机身连接耳: 左右伸出, 居中 (y=0). 位置 TBD, 见末尾 CHECKLIST. 默认左右各一, M3
lug_d = 3.2;      // M3 孔
lugs = [
  [ -(BOARD_L/2 + wall + 4.0), 0 ],
  [  (BOARD_L/2 + wall + 4.0), 0 ]
];

// ---------- 基础形状 ----------
module rounded_rect(l, w, r) {
  r2 = min(r, min(l, w) / 2 - 0.01);
  hull() {
    for (x = [-1, 1]) for (y = [-1, 1])
      translate([x * (l/2 - r2), y * (w/2 - r2)]) circle(r = r2, $fn = 24);
  }
}

// 仅作装配参考, 不打印
module board_ref() {
  color("lime") translate([0, 0, base_t + stand_h])
    linear_extrude(BOARD_T) rounded_rect(BOARD_L, BOARD_W, BOARD_R);
}

// ---------- 载板主体 ----------
module carrier() {
  // 底板 + 定位边轨 (开顶, 板从上方落入, 不挡接插件)
  difference() {
    union() {
      linear_extrude(base_t) rounded_rect(BOARD_L + 2*wall, BOARD_W + 2*wall, BOARD_R + wall);
      translate([0, 0, base_t]) linear_extrude(rail_h)
        difference() {
          rounded_rect(BOARD_L + 2*wall, BOARD_W + 2*wall, BOARD_R + wall);
          rounded_rect(BOARD_L + 2*tol, BOARD_W + 2*tol, BOARD_R);
        }
    }
    // 支柱 M2 通孔
    for (s = standoffs)
      translate([s[0], s[1], -0.1]) cylinder(d = screw_d, h = base_t + stand_h + 0.2, $fn = 16);
    // 连接耳 M3 通孔
    for (g = lugs)
      translate([g[0], g[1], -0.1]) cylinder(d = lug_d, h = base_t + 0.2, $fn = 16);
  }
  // 支柱实体 (带通孔)
  for (s = standoffs)
    difference() {
      translate([s[0], s[1], base_t]) cylinder(d = 5.0, h = stand_h, $fn = 20);
      translate([s[0], s[1], base_t - 0.1]) cylinder(d = screw_d, h = stand_h + 0.2, $fn = 16);
    }
  // 连接耳实体 (带通孔)
  for (g = lugs)
    difference() {
      translate([g[0], g[1], 0]) cylinder(d = 8.0, h = base_t, $fn = 24);
      translate([g[0], g[1], -0.1]) cylinder(d = lug_d, h = base_t + 0.2, $fn = 16);
    }
}

// ---------- 预览 ----------
carrier();
board_ref();

// ============================================================================
// CHECKLIST — 打印 / 装机前必须核对 (逐项填实后再出 STL)
// ----------------------------------------------------------------------------
// [ ] 1. BOARD_R: 打开官网 "产品详细图 / 正面视图", 量板四角倒圆半径, 改 BOARD_R.
// [ ] 2. 安装孔: 第三方评测确认 Orange Pi Zero 3W 与 Pi Zero 2W "identical hole spacing" (孔距一致),
//        板宽仅差 2mm (65x32 vs 65x30). 作者 CAD 的板模型是 Pi Zero 板型 (实机 Radxa Zero 3W).
//        => 机械层大概率免改; 本载板仅在 trunk_base 卡位放不下 32mm 板时才需要.
//        若要用真实孔位: 把 standoffs 改到 Pi Zero 四孔坐标, 并确认 Orange Pi 孔数/孔径 (待实物核).
//        无孔时当前四角摩擦+支柱方案可用, 但需实测紧固.
// [ ] 3. 机身接口: 拉取 fanhao375/microduck-replica-cad Releases 的 SolidWorks-FT2026-10-20.zip,
//        读原 RPi 托架的螺接位, 据此定 lugs 的位置/数量/孔径, 使本载板能拧到飞特版躯干.
// [ ] 4. 接插件禁布: 若后续要加侧开口 (Mini HDMI/USB-C/TF/CSI/PCIe), 依官方顶视图补 cutout,
//        位置坐标填到对应 translate 处.
// [ ] 5. HAT 决策(真正的不兼容在电气层, 不在机械): Orange Pi 40-pin 定义 != RPi => 树莓派机器人HAT
//        不能直插. 三条出路见 docs/hardware/microduck-飞特版3D打印件-OrangePi适配清单-2026-11-06.md §3:
//        A 主板改回 Radxa Zero 3W (与作者 CAD 完全对齐, 零机械改动) / B 重做 HAT 接口 / C 绕开 HAT
//        用 URT2 + imu_to_dxl 小板. 选 A 则本载板不需要; 选 B/C 则本载板直接固定 Orange Pi.
// 渲染: OpenSCAD 打开本文件 -> Design -> Render -> Export STL. 无需本机装 CAD 即可由你本地渲染.
// ============================================================================
