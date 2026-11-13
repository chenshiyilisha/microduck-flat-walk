import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.File;

/**
 * 临时工具：用 JDK 自带 java.awt 在 headless 下把中文字「控」渲染成
 * 不透明品牌深蓝底(#0E2A4A) + 白字的 PNG 图标（legacy 图标，绕过 vivo 透明图标模板）。
 * 不依赖 Pillow / ImageMagick / 任何额外安装。参数: <size> <outpath>
 */
public class MakeIcon {
    public static void main(String[] args) throws Exception {
        int S = Integer.parseInt(args[0]);
        File out = new File(args[1]);
        // 不透明 RGB（无 alpha）：满铺深蓝，launcher 圆角遮罩会裁边角
        BufferedImage img = new BufferedImage(S, S, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_FRACTIONALMETRICS, RenderingHints.VALUE_FRACTIONALMETRICS_ON);

        g.setColor(new Color(0x0E, 0x2A, 0x4A)); // 品牌深蓝底
        g.fillRect(0, 0, S, S);

        int fs = Math.round(S * 0.62f); // 字占 ~62% 边长，留边被圆角裁
        Font font = Font.createFont(Font.TRUETYPE_FONT, new File("C:/Windows/Fonts/simhei.ttf"))
                        .deriveFont(Font.BOLD, fs);
        g.setFont(font);
        g.setColor(Color.WHITE);
        FontMetrics fm = g.getFontMetrics();
        int tw = fm.stringWidth("控");
        int th = fm.getAscent() + fm.getDescent();
        g.drawString("控", (S - tw) / 2, (S - th) / 2 + fm.getAscent());
        g.dispose();

        ImageIO.write(img, "png", out);
        System.out.println("WROTE " + out.getAbsolutePath() + " S=" + S + " tw=" + tw + " th=" + th);
    }
}
