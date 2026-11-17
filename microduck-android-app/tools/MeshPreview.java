import io.microduck.app.core.DuckMesh;
import io.microduck.app.core.DuckModelGeometry;
import io.microduck.app.core.ModelPart;
import io.microduck.app.core.ProjectedPoint;
import io.microduck.app.core.ProjectedTriangle;
import io.microduck.app.core.RobotPart;
import io.microduck.app.core.Severity;
import io.microduck.app.core.Vec3;
import kotlin.jvm.functions.Function1;

import javax.imageio.ImageIO;
import java.awt.AlphaComposite;
import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 离线目视核验工具（诊断用，不是门禁，不参与 ship_verdict）。
 *
 * 为什么需要：模型「像不像 / 状态着色对不对」是**纯视觉**问题，真机 59/59 UI 门禁
 * 只读文本节点，全绿也照不出「散落碎片 / 整机刷绿 / 状态色没落在部件」。
 * 本工具调用与真机**相同的 core** `DuckMesh` / `DuckModelGeometry` 和同一份
 * duck_mesh.bin（DMSH v2 部件索引），不存在「预览好看、真机不一样」的偏差。
 *
 * 模式：
 *   base / unknown / alert —— 写实不透明 Lambert（阶段 4）
 *   holo / holo_alert      —— 数字孪生全息（图像空间提边，见下）
 *
 * ── 全息渲染路线（2026-11-16 第 9 版，取代所有几何提线方案）──
 *  前几版失败的根因：从三角形**几何**上挑「哪些边该画」（Markosian 边级 / Hertzmann
 *  零交叉 / EdgesGeometry 阈值），在 38 个零件嵌套的模型上可见性只能近似，内部零件
 *  的线从缝隙漏出来 → 越调越乱。
 *  本版改为**图像空间**做法（游戏引擎 outline 后处理的标准路线）：
 *   ① 先把全部三角形光栅化进像素缓冲（z-buffer 精确遮挡 + 每像素部件 ID + Fresnel 边缘亮度）
 *      —— 被外壳挡住的内部零件在像素层就被精确剔除，不需要猜；
 *   ② 再在图像上提边：外轮廓 = 模型与背景的像素交界；部件分界 = 部件 ID 变化的交界
 *      —— 线条即「屏幕上真实可见的边界」，与参考图一致；
 *   ③ Fresnel 边缘光（1-|n·v|）做全息辉光基底，边线外加盒式模糊做泛光；
 *   ④ 2x 超采样抗锯齿。
 *  该路线对网格密度不敏感 → 直接用原始 12000 面 DMSH v2，无需简化网格、无第二份产物。
 *
 * 用法： java -Djava.awt.headless=true -cp build/fat MeshPreview <mesh.bin> <tag> <mode>
 * 输出： build/mesh_preview_<tag>_{0,30,60,90}.png
 */
public class MeshPreview {
    private static final int GRID = 0xFF12313F;
    private static final float CAM_D = DuckModelGeometry.CAMERA_DISTANCE;
    private static final int EDGE_BOUNDARY = 0xFF5FC0DC; // 部件分界：中青（HUD 角框用）
    private static final int FILL_NEUTRAL = 0xFF2E7FA0;

    public static void main(String[] args) throws Exception {
        String meshPath = args.length > 0 ? args[0] : "app/src/main/assets/duck_mesh.bin";
        String tag = args.length > 1 ? args[1] : "preview";
        String mode = args.length > 2 ? args[2] : "base";
        byte[] bytes = Files.readAllBytes(Paths.get(meshPath));
        DuckMesh.MeshData mesh = DuckMesh.INSTANCE.loadFromBytes(bytes);
        System.out.println("mesh=" + meshPath + " nVerts=" + mesh.getNVerts()
                + " nTris=" + mesh.getNTris() + " version=" + mesh.getVersion()
                + " mode=" + mode);

        final boolean alert = mode.equals("alert") || mode.equals("holo_alert");
        final Function1<RobotPart, Severity> sevOf = part -> {
            if (!alert) return Severity.UNKNOWN;
            if (part == RobotPart.BATTERY || part == RobotPart.IMU) return Severity.CRITICAL;
            if (part == RobotPart.CPU || part == RobotPart.LEFT_KNEE) return Severity.WARN;
            return Severity.UNKNOWN;
        };

        int W = 720, H = 480;
        for (double ang : new double[]{0, 30, 60, 90}) {
            BufferedImage img = new BufferedImage(W, H, BufferedImage.TYPE_INT_ARGB);
            Graphics2D g = img.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            if (mode.startsWith("holo")) {
                renderHolo(g, img, mesh, sevOf, ang, W, H);
            } else {
                renderSolid(g, mesh, mode, sevOf, ang, W, H);
            }
            g.dispose();
            File out = new File("build/mesh_preview_" + tag + "_" + (int) ang + ".png");
            ImageIO.write(img, "png", out);
            System.out.println("wrote " + out.getPath());
        }
    }

    private static void renderSolid(Graphics2D g, DuckMesh.MeshData mesh, String mode,
                                    Function1<RobotPart, Severity> sevOf,
                                    double ang, int W, int H) {
        g.setColor(new Color(0x0D1015));
        g.fillRect(0, 0, W, H);
        g.setColor(new Color(0x1B2028));
        g.fillOval((int) (W * 0.22f), (int) (H * 0.88f), (int) (W * 0.56f), (int) (H * 0.07f));
        List<ProjectedTriangle> tris = mode.equals("base")
                ? DuckMesh.INSTANCE.project(mesh, ang, (float) W, (float) H)
                : DuckMesh.INSTANCE.project(mesh, ang, (float) W, (float) H, sevOf);
        for (ProjectedTriangle t : tris) {
            int[] xs = {(int) t.getA().getX(), (int) t.getB().getX(), (int) t.getC().getX()};
            int[] ys = {(int) t.getA().getY(), (int) t.getB().getY(), (int) t.getC().getY()};
            g.setColor(new Color(t.getColorArgb(), true));
            g.fillPolygon(xs, ys, 3);
        }
    }

    /**
     * 全息层：图像空间提边（z-buffer + 部件 ID 缓冲 + Fresnel + 泛光 + 2x 超采样）。
     * 关键：内部零件被外壳遮挡发生在①的光栅化阶段（精确），②只在可见像素上提边。
     */
    private static void renderHolo(Graphics2D g, BufferedImage img, DuckMesh.MeshData mesh,
                                   Function1<RobotPart, Severity> sevOf,
                                   double ang, int W, int H) {
        // ── 背景层：径向渐变（模型后方环境微光）→ 地面网格（模型半透明会透出）──
        java.awt.RadialGradientPaint rgp = new java.awt.RadialGradientPaint(
                new java.awt.geom.Point2D.Float(W * 0.5f, H * 0.44f), W * 0.72f,
                new float[]{0f, 0.55f, 1f},
                new Color[]{new Color(0x123246), new Color(0x0B1C2B), new Color(0x050A11)});
        g.setPaint(rgp);
        g.fillRect(0, 0, W, H);
        drawGroundGrid(g, W, H);

        float[] v = mesh.getVerts();
        int[] t = mesh.getTris();
        byte[] parts = mesh.getPartIndices();
        int nv = mesh.getNVerts(), nt = mesh.getNTris();

        // 部件 → 状态查表（0=UNKNOWN 1=OK 2=WARN 3=CRITICAL），图像层只认这张表
        byte[] sevOfPart = new byte[256];
        for (int p = 0; p < 21; p++) {
            Severity s = sevOf.invoke(ModelPart.INSTANCE.of(p));
            sevOfPart[p] = (byte) (s == Severity.CRITICAL ? 3 : s == Severity.WARN ? 2
                    : s == Severity.OK ? 1 : 0);
        }

        // ── ① 光栅化（4x 超采样：细线抗锯齿 + 小圆件圆滑）──
        final int SS = 4, SW = W * SS, SH = H * SS;
        float[] zbuf = new float[SW * SH];
        int[] idbuf = new int[SW * SH];
        float[] rbuf = new float[SW * SH]; // Fresnel 边缘亮度（逐像素，顶点插值）
        Arrays.fill(zbuf, -Float.MAX_VALUE);
        Arrays.fill(idbuf, -1);

        float[] sx = new float[nv], sy = new float[nv], sd = new float[nv];
        float[] wx = new float[nv], wy = new float[nv], wz = new float[nv];
        for (int k = 0; k < nv; k++) {
            Vec3 w = DuckModelGeometry.INSTANCE.rotateY(
                    new Vec3(v[3 * k], v[3 * k + 1], v[3 * k + 2]), ang);
            wx[k] = w.getX(); wy[k] = w.getY(); wz[k] = w.getZ();
            ProjectedPoint p = DuckModelGeometry.INSTANCE.project(w, (float) SW, (float) SH);
            sx[k] = p.getX(); sy[k] = p.getY(); sd[k] = p.getDepth();
        }

        // 逐顶点 Fresnel（法线只在**同一零件内**平均，避免跨零件接缝串色）：
        // 键 = (vertex << 8) | part，值 = 法线累加器。插值后填充是连续渐变而非棱面。
        Map<Long, float[]> vnorm = new HashMap<>(nv * 4);
        int[] faceV = new int[3];
        float[] faceRim = new float[3];
        for (int i = 0; i < nt; i++) {
            int i0 = i * 3, a = t[i0], b = t[i0 + 1], c = t[i0 + 2];
            faceV[0] = a; faceV[1] = b; faceV[2] = c;
            int part = parts[i] & 0xFF;
            float ux = wx[b] - wx[a], uy = wy[b] - wy[a], uz = wz[b] - wz[a];
            float rx = wx[c] - wx[a], ry = wy[c] - wy[a], rz = wz[c] - wz[a];
            float nx = uy * rz - uz * ry, ny = uz * rx - ux * rz, nz2 = ux * ry - uy * rx;
            float nl = (float) Math.sqrt(nx * nx + ny * ny + nz2 * nz2);
            if (nl < 1e-9f) continue;
            nx /= nl; ny /= nl; nz2 /= nl;
            for (int j = 0; j < 3; j++) {
                long key = ((long) faceV[j] << 8) | part;
                float[] acc = vnorm.get(key);
                if (acc == null) { acc = new float[4]; vnorm.put(key, acc); }
                acc[0] += nx; acc[1] += ny; acc[2] += nz2; acc[3] += 1f;
            }
        }
        for (int i = 0; i < nt; i++) {
            int i0 = i * 3, a = t[i0], b = t[i0 + 1], c = t[i0 + 2];
            faceV[0] = a; faceV[1] = b; faceV[2] = c;
            int part = parts[i] & 0xFF;
            boolean degenerate = false;
            for (int j = 0; j < 3; j++) {
                long key = ((long) faceV[j] << 8) | part;
                float[] acc = vnorm.get(key);
                if (acc == null) { degenerate = true; break; }
                float l = (float) Math.sqrt(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2]);
                if (l < 1e-9f) { degenerate = true; break; }
                float vvx = wx[faceV[j]], vvy = wy[faceV[j]], vvz = wz[faceV[j]];
                float cx = -vvx, cy = -vvy, cz = CAM_D - vvz;
                float cl = (float) Math.sqrt(cx * cx + cy * cy + cz * cz);
                if (cl < 1e-9f) { degenerate = true; break; }
                cx /= cl; cy /= cl; cz /= cl;
                float dot = (acc[0] / l) * cx + (acc[1] / l) * cy + (acc[2] / l) * cz;
                faceRim[j] = 1f - Math.abs(dot); // 掠射边 → 1
            }
            if (degenerate) continue;
            rasterFace(zbuf, idbuf, rbuf, SW, SH,
                    sx[a], sy[a], sd[a], sx[b], sy[b], sd[b], sx[c], sy[c], sd[c],
                    part, faceRim);
        }

        // Fresnel 亮度缓冲轻模糊（r=1）：抹平跨三角形的插值残差，填充渐变更平滑
        blurH(rbuf, SW, SH, 1); blurV(rbuf, SW, SH, 1);

        // 边缘掩码：1=外轮廓(与背景交界) 2=部件分界(ID 变化)。4x 超采样下 1 超采样像素
        // 宽 ≈ 0.25 输出像素，天然细线。
        byte[] emask = new byte[SW * SH];
        for (int y = 0; y < SH; y++) {
            for (int x = 0; x < SW; x++) {
                int i = y * SW + x;
                int id = idbuf[i];
                if (id < 0) continue;
                boolean outer = false, bnd = false;
                if (x > 0)      { int n = idbuf[i - 1];  if (n < 0) outer = true; else if (n != id) bnd = true; }
                if (x < SW - 1) { int n = idbuf[i + 1];  if (n < 0) outer = true; else if (n != id) bnd = true; }
                if (y > 0)      { int n = idbuf[i - SW]; if (n < 0) outer = true; else if (n != id) bnd = true; }
                if (y < SH - 1) { int n = idbuf[i + SW]; if (n < 0) outer = true; else if (n != id) bnd = true; }
                emask[i] = outer ? (byte) 1 : bnd ? (byte) 2 : 0;
            }
        }
        // 深度归一化范围（可见像素），远处线条/填充调暗 → 景深暗示
        float zmin = Float.MAX_VALUE, zmax = -Float.MAX_VALUE;
        for (int i = 0; i < SW * SH; i++) {
            if (idbuf[i] >= 0 && zbuf[i] > -1e30f) {
                zmin = Math.min(zmin, zbuf[i]); zmax = Math.max(zmax, zbuf[i]);
            }
        }
        float zSpan = Math.max(zmax - zmin, 1e-6f);

        // ── ② 图像空间提边 → HDR 发射缓冲 ──
        // 边缘判定在 4x 超采样上做（精确到 1/4 像素），发射强度聚合到输出分辨率。
        // 依据（UE/three.js bloom 管线）：线条进 HDR（强度>1），核心过曝后经 Reinhard
        // 色调映射自然趋白 —— 「白色亮芯 + 线色柔晕」正是全息发光线的视觉特征。
        float[] coreI = new float[W * H];   // 核心线强度（HDR，>1）
        byte[] coreKind = new byte[W * H];  // 0无 1外轮廓 2分界 3crit 4warn
        float[] rimBuf = new float[W * H];  // Fresnel（0..1）
        float[] znBuf = new float[W * H];   // 归一化深度（1 近 0 远）
        float[] covBuf = new float[W * H];  // 填充覆盖率（0..1，填充边缘抗锯齿）
        byte[] sevBuf = new byte[W * H];
        int[] pidBuf = new int[W * H];
        int visPx = 0, edgePx = 0;
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                int o = y * W + x;
                int idAny = -1, edgePart = -1;
                float rimSum = 0f, zSum = 0f;
                int samples = 0, edgeCount = 0, edgeType = 0;
                for (int dy = 0; dy < SS; dy++) {
                    for (int dx = 0; dx < SS; dx++) {
                        int si = (y * SS + dy) * SW + (x * SS + dx);
                        int id = idbuf[si];
                        if (id >= 0) { idAny = id; samples++; rimSum += rbuf[si]; zSum += zbuf[si]; }
                        byte em = emask[si];
                        if (em != 0) {
                            edgeCount++;
                            edgePart = id;
                            if (em == 1) edgeType = 1; else if (edgeType == 0) edgeType = 2;
                        }
                    }
                }
                if (samples > 0) visPx++;
                pidBuf[o] = idAny;
                rimBuf[o] = samples > 0 ? rimSum / samples : 0f;
                znBuf[o] = samples > 0 ? (zSum / samples - zmin) / zSpan : 0f;
                covBuf[o] = samples / (float) (SS * SS);
                int sev = idAny >= 0 && idAny < 256 ? sevOfPart[idAny] : 0;
                sevBuf[o] = (byte) sev;
                if (edgeCount > 0) {
                    edgePx++;
                    int es = edgePart >= 0 && edgePart < 256 ? sevOfPart[edgePart] : 0;
                    if (es >= 2) coreKind[o] = (byte) (es == 3 ? 3 : 4);
                    else coreKind[o] = (byte) (edgeType == 1 ? 1 : 2);
                    // 全动态范围覆盖率抗锯齿：cov = 命中子样本/16（16 级渐变）。
                    // 能量守恒 ⇒ 斜线/圆弧上相邻像素亮度连续过渡，不再锯齿跳变；
                    // baseI 取大让线芯过曝（Reinhard 后趋白），亮度由 cov 自然调回。
                    float baseI = coreKind[o] == 1 ? 4.6f : coreKind[o] == 2 ? 2.3f : 3.6f;
                    float cov = edgeCount / (float) (SS * SS);
                    coreI[o] = baseI * cov * (0.55f + 0.45f * znBuf[o]);
                }
            }
        }

        // 发射 RGB（输出分辨率）= 核心线 + Fresnel 内辉光（全息「由内发光」）
        float[] eR = new float[W * H], eG = new float[W * H], eB = new float[W * H];
        for (int o = 0; o < W * H; o++) {
            float df = 0.55f + 0.45f * znBuf[o];          // 深度衰减
            if (coreI[o] > 0f) {
                float[] rgb = kindRgb(coreKind[o]);
                eR[o] += rgb[0] * coreI[o]; eG[o] += rgb[1] * coreI[o]; eB[o] += rgb[2] * coreI[o];
            }
            float rim = rimBuf[o];
            if (rim > 0.01f) {
                float[] fc = fillRgb(sevBuf[o]);
                float glowI = rim * 0.32f * df;           // 掠射面更亮 → 体积感（过重会发雾）
                eR[o] += fc[0] * glowI; eG[o] += fc[1] * glowI; eB[o] += fc[2] * glowI;
            }
        }
        // 发射图轻度高斯（σ=0.6px）：等效按高斯点扩散画线 —— 16 级覆盖率之外的
        // 残余阶梯（亚像素级）一并平滑；能量守恒不改变总亮度。
        gaussBlur(eR, W, H, 0.6f);
        gaussBlur(eG, W, H, 0.6f);
        gaussBlur(eB, W, H, 0.6f);

        // ── ③ 多尺度 bloom 金字塔（1/1、1/2、1/4 三级可分离高斯）──
        // 单级小半径只有紧晕；多级叠加才同时有「紧密亮核 + 中距柔晕 + 宽域环境辉光」。
        float[] bR = new float[W * H], bG = new float[W * H], bB = new float[W * H];
        addPyramidLevel(eR, eG, eB, W, H, 1, 0.42f, bR, bG, bB);
        addPyramidLevel(eR, eG, eB, W, H, 2, 0.30f, bR, bG, bB);
        addPyramidLevel(eR, eG, eB, W, H, 4, 0.20f, bR, bG, bB);

        // ── ④ 合成：背景(渐变+暗角) → 半透明填充 → 加法发光 → Reinhard 色调映射 ──
        int[] back = img.getRGB(0, 0, W, H, null, 0, W);
        int[] out = new int[W * H];
        float cxm = W * 0.5f, cym = H * 0.5f;
        float maxD = (float) Math.sqrt(cxm * cxm + cym * cym);
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                int o = y * W + x;
                float ddx = (x - cxm) / maxD, ddy = (y - cym) / maxD;
                float vig = 1f - 0.34f * Math.min(1f, ddx * ddx + ddy * ddy);
                int bg = back[o];
                float br = ((bg >> 16) & 255) / 255f * vig;
                float bgc = ((bg >> 8) & 255) / 255f * vig;
                float bb = (bg & 255) / 255f * vig;
                int idAny = pidBuf[o];
                if (idAny >= 0) {
                    int sev = sevBuf[o];
                    float[] fc = fillRgb(sev);
                    // 填充 alpha × 覆盖率：轮廓边缘 16 级渐变，不再硬边锯齿
                    float fa = ((sev >= 2 ? 0.16f : 0.11f) + rimBuf[o] * 0.45f)
                            * (0.62f + 0.38f * znBuf[o]) * covBuf[o];
                    fa = Math.min(fa, 0.8f);
                    br = fc[0] * fa + br * (1 - fa);
                    bgc = fc[1] * fa + bgc * (1 - fa);
                    bb = fc[2] * fa + bb * (1 - fa);
                }
                // 加法合成发射（bloom 0.95 增益）+ Reinhard：f/(1+f) 只压发光项不压背景
                float er = eR[o] + bR[o] * 0.95f;
                float eg = eG[o] + bG[o] * 0.95f;
                float eb = eB[o] + bB[o] * 0.95f;
                out[o] = 0xFF000000
                        | (toSrgb(br + er / (1f + er)) << 16)
                        | (toSrgb(bgc + eg / (1f + eg)) << 8)
                        | toSrgb(bb + eb / (1f + eb));
            }
        }
        img.setRGB(0, 0, W, H, out, 0, W);
        if (System.getenv("MESH_PREVIEW_DIAG") != null) {
            System.out.println("DIAG visPx=" + visPx + " edgePx=" + edgePx);
        }

        // ── 扫描线 + 四角 HUD（叠在模型上，克制）──
        g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER, 0.05f));
        g.setColor(new Color(0x9FEFFF, true));
        for (int y = 0; y < H; y += 9) g.drawLine(0, y, W, y);
        g.setComposite(AlphaComposite.getInstance(AlphaComposite.SRC_OVER));
        drawCorners(g, W, H);
    }

    /** 核心线颜色（归一化线性 RGB）：外轮廓亮青 / 分界中青 / 告警红·琥珀。 */
    private static float[] kindRgb(int kind) {
        switch (kind) {
            case 3: return new float[]{1.00f, 0.45f, 0.38f};
            case 4: return new float[]{0.95f, 0.72f, 0.32f};
            case 1: return new float[]{0.60f, 0.93f, 1.00f};
            case 2: return new float[]{0.34f, 0.72f, 0.84f};
            default: return new float[]{0f, 0f, 0f};
        }
    }

    /** 填充颜色（归一化线性 RGB）：状态件比中性件饱和，其余同色系。 */
    private static float[] fillRgb(int sev) {
        switch (sev) {
            case 3: return new float[]{0.75f, 0.29f, 0.25f};
            case 2: return new float[]{0.75f, 0.54f, 0.20f};
            case 1: return new float[]{0.18f, 0.62f, 0.49f};
            default: return new float[]{0.18f, 0.50f, 0.63f};
        }
    }

    /** 一个 bloom 金字塔级：1/scale 面积下采样 → 可分离高斯 → 双线性上采样 → 加权并入。 */
    private static void addPyramidLevel(float[] eR, float[] eG, float[] eB,
                                        int W, int H, int scale, float weight,
                                        float[] bR, float[] bG, float[] bB) {
        int SW2 = Math.max(2, W / scale), SH2 = Math.max(2, H / scale);
        float[] r = new float[SW2 * SH2], g = new float[SW2 * SH2], b = new float[SW2 * SH2];
        downsample(eR, W, H, r, SW2, SH2);
        downsample(eG, W, H, g, SW2, SH2);
        downsample(eB, W, H, b, SW2, SH2);
        float sigma = Math.max(1.5f, scale * 1.6f);
        gaussBlur(r, SW2, SH2, sigma);
        gaussBlur(g, SW2, SH2, sigma);
        gaussBlur(b, SW2, SH2, sigma);
        float[] up = new float[W * H];
        upsampleBilinear(r, SW2, SH2, up, W, H);
        for (int i = 0; i < W * H; i++) bR[i] += up[i] * weight;
        upsampleBilinear(g, SW2, SH2, up, W, H);
        for (int i = 0; i < W * H; i++) bG[i] += up[i] * weight;
        upsampleBilinear(b, SW2, SH2, up, W, H);
        for (int i = 0; i < W * H; i++) bB[i] += up[i] * weight;
    }

    /** 面积平均下采样（DW×DH ← W×H）。 */
    private static void downsample(float[] src, int W, int H, float[] dst, int DW, int DH) {
        for (int dy = 0; dy < DH; dy++) {
            int y0 = dy * H / DH, y1 = Math.max(y0 + 1, (dy + 1) * H / DH);
            for (int dx = 0; dx < DW; dx++) {
                int x0 = dx * W / DW, x1 = Math.max(x0 + 1, (dx + 1) * W / DW);
                float s = 0f;
                for (int y = y0; y < y1; y++) {
                    for (int x = x0; x < x1; x++) s += src[y * W + x];
                }
                dst[dy * DW + dx] = s / ((y1 - y0) * (x1 - x0));
            }
        }
    }

    /** 双线性上采样（DW×DH ← SW×SH）。 */
    private static void upsampleBilinear(float[] src, int SW, int SH, float[] dst, int DW, int DH) {
        for (int y = 0; y < DH; y++) {
            float fy = (y + 0.5f) * SH / (float) DH - 0.5f;
            int y0 = clamp((int) Math.floor(fy), SH), y1 = Math.min(SH - 1, y0 + 1);
            float ty = Math.max(0f, Math.min(1f, fy - y0));
            for (int x = 0; x < DW; x++) {
                float fx = (x + 0.5f) * SW / (float) DW - 0.5f;
                int x0 = clamp((int) Math.floor(fx), SW), x1 = Math.min(SW - 1, x0 + 1);
                float tx = Math.max(0f, Math.min(1f, fx - x0));
                float a = src[y0 * SW + x0] * (1 - tx) + src[y0 * SW + x1] * tx;
                float b = src[y1 * SW + x0] * (1 - tx) + src[y1 * SW + x1] * tx;
                dst[y * DW + x] = a * (1 - ty) + b * ty;
            }
        }
    }

    /** 可分离高斯模糊（sigma 像素，边界 clamp）。 */
    private static void gaussBlur(float[] a, int W, int H, float sigma) {
        int r = Math.max(1, (int) Math.ceil(sigma * 2.5f));
        float[] k = new float[r + 1];
        float sum = 0f;
        for (int i = 0; i <= r; i++) {
            k[i] = (float) Math.exp(-(double) (i * i) / (2 * sigma * sigma));
            sum += (i == 0 ? k[i] : 2f * k[i]);
        }
        for (int i = 0; i <= r; i++) k[i] /= sum;
        float[] line = new float[Math.max(W, H)];
        float[] tmp = new float[Math.max(W, H)];
        for (int y = 0; y < H; y++) {
            System.arraycopy(a, y * W, line, 0, W);
            for (int x = 0; x < W; x++) {
                float acc = 0f;
                for (int i = -r; i <= r; i++) acc += line[clamp(x + i, W)] * k[Math.abs(i)];
                tmp[x] = acc;
            }
            System.arraycopy(tmp, 0, a, y * W, W);
        }
        for (int x = 0; x < W; x++) {
            for (int y = 0; y < H; y++) line[y] = a[y * W + x];
            for (int y = 0; y < H; y++) {
                float acc = 0f;
                for (int i = -r; i <= r; i++) acc += line[clamp(y + i, H)] * k[Math.abs(i)];
                tmp[y] = acc;
            }
            for (int y = 0; y < H; y++) a[y * W + x] = tmp[y];
        }
    }

    private static int clamp(int v, int n) { return v < 0 ? 0 : v >= n ? n - 1 : v; }

    /** [0,1) 浮点 → 0..255。 */
    private static int toSrgb(float v) {
        return Math.min(255, (int) (Math.max(0f, Math.min(1f, v)) * 255f + 0.5f));
    }

    /** 三角形光栅化（重心坐标，屏幕空间线性插值深度与 Fresnel），通过 z 测试写入三缓冲。 */
    private static void rasterFace(float[] zbuf, int[] idbuf, float[] rbuf, int SW, int SH,
                                   float ax, float ay, float az,
                                   float bx, float by, float bz,
                                   float cx, float cy, float cz,
                                   int part, float[] rim3) {
        int minX = Math.max(0, (int) Math.floor(Math.min(ax, Math.min(bx, cx))));
        int maxX = Math.min(SW - 1, (int) Math.ceil(Math.max(ax, Math.max(bx, cx))));
        int minY = Math.max(0, (int) Math.floor(Math.min(ay, Math.min(by, cy))));
        int maxY = Math.min(SH - 1, (int) Math.ceil(Math.max(ay, Math.max(by, cy))));
        if (minX > maxX || minY > maxY) return;
        float det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
        if (Math.abs(det) < 1e-6f) return;
        for (int py = minY; py <= maxY; py++) {
            for (int px = minX; px <= maxX; px++) {
                float w0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det;
                float w1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det;
                float w2 = 1f - w0 - w1;
                if (w0 < -0.001f || w1 < -0.001f || w2 < -0.001f) continue;
                float z = w0 * az + w1 * bz + w2 * cz;
                int idx = py * SW + px;
                if (z > zbuf[idx]) {
                    zbuf[idx] = z;
                    idbuf[idx] = part;
                    rbuf[idx] = w0 * rim3[0] + w1 * rim3[1] + w2 * rim3[2];
                }
            }
        }
    }

    private static void blurH(float[] a, int W, int H, int r) {
        float[] tmp = new float[W];
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                float s = 0f; int n = 0;
                for (int k = -r; k <= r; k++) {
                    int xx = x + k;
                    if (xx >= 0 && xx < W) { s += a[y * W + xx]; n++; }
                }
                tmp[x] = s / n;
            }
            System.arraycopy(tmp, 0, a, y * W, W);
        }
    }

    private static void blurV(float[] a, int W, int H, int r) {
        float[] tmp = new float[H];
        for (int x = 0; x < W; x++) {
            for (int y = 0; y < H; y++) {
                float s = 0f; int n = 0;
                for (int k = -r; k <= r; k++) {
                    int yy = y + k;
                    if (yy >= 0 && yy < H) { s += a[yy * W + x]; n++; }
                }
                tmp[y] = s / n;
            }
            for (int y = 0; y < H; y++) a[y * W + x] = tmp[y];
        }
    }

    private static void drawGroundGrid(Graphics2D g, int W, int H) {
        g.setColor(new Color(GRID, true));
        float vy = H * 0.66f, vx = W / 2f;
        for (int i = -6; i <= 6; i++) {
            g.drawLine((int) (vx + i * W / 6f), H, (int) vx, (int) vy);
        }
        for (int j = 1; j <= 6; j++) {
            float f = j / 6f;
            int y = (int) (vy + (H - vy) * f * f);
            g.drawLine(0, y, W, y);
        }
    }

    private static void drawCorners(Graphics2D g, int W, int H) {
        g.setColor(new Color(EDGE_BOUNDARY, true));
        g.setStroke(new BasicStroke(1f));
        int m = 14, len = 26;
        g.drawLine(m, m, m + len, m); g.drawLine(m, m, m, m + len);
        g.drawLine(W - m, m, W - m - len, m); g.drawLine(W - m, m, W - m, m + len);
        g.drawLine(m, H - m, m + len, H - m); g.drawLine(m, H - m, m, H - m - len);
        g.drawLine(W - m, H - m, W - m - len, H - m); g.drawLine(W - m, H - m, W - m, H - m - len);
    }
}
