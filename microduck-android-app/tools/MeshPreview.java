import io.microduck.app.core.DuckMesh;
import io.microduck.app.core.DuckModelGeometry;
import io.microduck.app.core.ModelFrame;
import io.microduck.app.core.ModelNode;
import io.microduck.app.core.ProjectedPoint;
import io.microduck.app.core.ProjectedTriangle;
import kotlin.Pair;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

/**
 * 离线目视核验工具（诊断用，不是门禁，不参与 ship_verdict）。
 *
 * 为什么需要：模型「像不像鸭子」是**纯视觉**问题，真机 59/59 UI 门禁只读文本节点，
 * 全绿也照不出「散落碎片」。本项目连续几轮靠猜改渲染参数，直到把
 * DuckMesh.project() 的真实输出画成 PNG 才发现 stride 抽样只留了 2% 的面。
 * 手机拔线期间也能核验几何，是这条链最短的观测面。
 *
 * 关键：调用的是 **与真机完全相同的** core `DuckMesh.project()` / `DuckModelGeometry.frame()`
 * 和同一份 duck_mesh.bin，不是另写一套投影算法，因此不存在「预览好看但真机不一样」的偏差。
 * 局限：只证明 core 几何 + 配色 + 光照正确，**不证明 Android assets 加载成功、
 * 不证明 onDraw 真的画出来、不替代真机截图**（那几项仍需 adb + contentDescription 判据）。
 *
 * 用法（由 tools/render_mesh_preview.sh 调用）：
 *   java -Djava.awt.headless=true -cp build/fat MeshPreview <mesh.bin> <tag>
 * 输出：build/mesh_preview_<tag>_{0,30,60,90}.png
 */
public class MeshPreview {
    public static void main(String[] args) throws Exception {
        String meshPath = args.length > 0 ? args[0] : "app/src/main/assets/duck_mesh.bin";
        String tag = args.length > 1 ? args[1] : "preview";
        byte[] bytes = Files.readAllBytes(Paths.get(meshPath));
        DuckMesh.MeshData mesh = DuckMesh.INSTANCE.loadFromBytes(bytes);
        System.out.println("mesh=" + meshPath + " nVerts=" + mesh.getNVerts()
                + " nTris=" + mesh.getNTris());

        // 健康页 View 约 360x240dp，这里按 2x 像素近似；View 用全高绘制，无文字遮挡
        int W = 720, H = 480;
        for (double ang : new double[]{0, 30, 60, 90}) {
            BufferedImage img = new BufferedImage(W, H, BufferedImage.TYPE_INT_ARGB);
            Graphics2D g = img.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(new Color(0x0A1626));           // md_bg
            g.fillRect(0, 0, W, H);
            g.setColor(new Color(0x1B3552));           // 地面投影
            g.fillOval((int) (W * 0.22f), (int) (H * 0.88f), (int) (W * 0.56f), (int) (H * 0.07f));

            List<ProjectedTriangle> tris = DuckMesh.INSTANCE.project(mesh, ang, (float) W, (float) H);
            for (ProjectedTriangle t : tris) {
                int[] xs = {(int) t.getA().getX(), (int) t.getB().getX(), (int) t.getC().getX()};
                int[] ys = {(int) t.getA().getY(), (int) t.getB().getY(), (int) t.getC().getY()};
                g.setColor(new Color(t.getColorArgb(), true));
                g.fillPolygon(xs, ys, 3);
            }

            // 15 个关节状态点（无 report ⇒ 全部 UNKNOWN 灰），位置与真机同源
            ModelFrame f = DuckModelGeometry.INSTANCE.frame(ang, (float) W, (float) H);
            for (Pair<ModelNode, ProjectedPoint> p : f.getNodes()) {
                ProjectedPoint q = p.getSecond();
                g.setColor(new Color(0xAA9AA7B8, true));
                g.fillOval((int) (q.getX() - 6), (int) (q.getY() - 6), 12, 12);
            }
            g.dispose();

            File out = new File("build/mesh_preview_" + tag + "_" + (int) ang + ".png");
            ImageIO.write(img, "png", out);
            System.out.println("wrote " + out.getPath() + " tris=" + tris.size());
        }
    }
}
