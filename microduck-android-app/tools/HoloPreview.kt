import io.microduck.app.core.DuckMesh
import io.microduck.app.core.HoloRenderer
import io.microduck.app.core.RobotPart
import io.microduck.app.core.Severity
import java.awt.image.BufferedImage
import java.io.File
import javax.imageio.ImageIO

/**
 * 离线目视核验：**真机同一份代码**（core `HoloRenderer.render`）出 PNG。
 *
 * 与 `tools/MeshPreview.java` 的区别：那个是 Java 参考实现（桌面调参用），
 * 这个直接调 App 里跑的 Kotlin 管线 —— 用来证明「移植没走样」，
 * 而不是「参考实现好看」。诊断工具，不参与 ship_verdict。
 *
 * 用法：java -cp build/fat HoloPreviewKt [alert]
 * 输出：build/holo_kotlin_{normal|alert}_{0,30,90}.png + 单帧耗时
 */
object HoloPreview {
    @JvmStatic
    fun main(args: Array<String>) {
        val meshFile = File("core/src/main/resources/duck_mesh.bin")
        if (!meshFile.isFile) {
            println("FAIL: 缺 core/src/main/resources/duck_mesh.bin")
            return
        }
        val mesh = DuckMesh.loadFromBytes(meshFile.readBytes())
        val alert = args.contains("alert")
        val sevOf: (RobotPart) -> Severity = { p ->
            if (!alert) Severity.UNKNOWN
            else when (p) {
                RobotPart.BATTERY, RobotPart.IMU -> Severity.CRITICAL
                RobotPart.CPU, RobotPart.LEFT_KNEE -> Severity.WARN
                else -> Severity.UNKNOWN
            }
        }
        val w = 480
        val h = 360
        val tag = if (alert) "alert" else "normal"
        for (ang in intArrayOf(0, 30, 90)) {
            val (px, cov) = HoloRenderer.renderWithCoverage(mesh, ang.toDouble(), w, h, sevOf, 3)
            val img = BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB)
            img.setRGB(0, 0, w, h, px, 0, w)
            val out = File("build/holo_kotlin_${tag}_$ang.png")
            out.parentFile?.mkdirs()
            ImageIO.write(img, "png", out)
            println("wrote ${out.path}  coverage=${"%.3f".format(cov)}")
        }
        // 单帧耗时：JVM 前几帧是解释执行（冷 JIT），必须分开报「冷/热」两个数，
        // 否则会把预热成本当成真机预算（手机也有 ART 预热，但量级不同）。
        repeat(5) { HoloRenderer.render(mesh, 30.0, 480, 360, sevOf, 3) }
        val t0 = System.nanoTime()
        val n = 10
        repeat(n) { HoloRenderer.render(mesh, 30.0, 480, 360, sevOf, 3) }
        val hot = (System.nanoTime() - t0) / n / 1_000_000
        println("render 480x360 ss=3: warm avg ${hot}ms/frame (desktop JVM, 5 帧预热后)")

        // 分阶段计时：投影/光栅/边缘/聚合/发射/模糊/bloom/合成（哪一段最贵，别猜）
        val names = arrayOf("(无效槽)", "光栅+Rim", "边缘掩码", "聚合", "发射", "模糊", "bloom", "合成", "顶点投影", "法线累加")
        val sink = LongArray(10)
        HoloRenderer.profileSink = sink
        repeat(5) { HoloRenderer.render(mesh, 30.0, 480, 360, sevOf, 3) }
        sink.fill(0)
        repeat(5) { HoloRenderer.render(mesh, 30.0, 480, 360, sevOf, 3) }
        HoloRenderer.profileSink = null
        for (i in names.indices) {
            println("  stage ${names[i]}: ${sink[i] / 5 / 1_000_000}ms")
        }
    }
}
