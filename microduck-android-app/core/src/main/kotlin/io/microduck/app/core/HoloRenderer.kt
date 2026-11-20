package io.microduck.app.core

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * 数字孪生全息渲染器（**纯 JVM 像素管线**，零 Android 依赖）。
 *
 * ── 为什么在 core，而不是塞进 View ──
 * 项目铁律：「只测内部函数不测 CLI = 假绿」。`android.graphics.Canvas` 在 JVM 自检里是
 * stub，View 的绘制无法被断言；而「模型像不像 / 状态色落没落在部件上」是纯视觉问题，
 * 文本门禁照不出。故把整条像素管线下沉到 core：输入网格 + 角度 + 状态表，输出 ARGB
 * 像素数组。View 只做 `Bitmap.setPixels` + `drawBitmap`，自检可直接对像素数组下断言。
 *
 * ── 管线（与 `tools/MeshPreview.java` 的 renderHolo 同一路线，改动需两侧同步）──
 *  ① 光栅化进超采样缓冲：z-buffer 精确遮挡 + 每像素部件 ID + 逐顶点 Fresnel；
 *  ② 图像空间提边：外轮廓 = 模型/背景交界，部件分界 = 部件 ID 变化交界，
 *     几何折痕 = 相邻像素法线夹角过大（镜头环、头罩分缝、脚底板等同一部件内的外形棱）
 *     —— 只画「屏幕上真实可见的边界」，内部零件被外壳精确剔除，不靠几何猜；
 *  ③ 覆盖率抗锯齿：线强度 = 命中子样本数 / SS²（能量守恒的连续渐变）；
 *  ④ HDR 发射 + 三级 bloom 金字塔 + Reinhard 色调映射 → 「亮芯 + 柔晕」
 *     （2026-11-20 收窄 bloom，避免细棱被柔晕糊掉）；
 *  ⑤ 合成：径向渐变背景 + 地面网格 + 暗角 + 半透明填充（Lambert 明暗）+ 加法发光。
 *
 * 关键设计依据（离线工具已实测收敛）：几何提边路线（Markosian / 零交叉 / 阈值）在
 * 38 个嵌套零件上必然漏线或涂鸦；图像空间提边对网格密度不敏感，是游戏引擎 outline
 * 后处理的标准路线。
 *
 * ── 状态色单一真源 ──
 * 逐部件 [Severity] 由调用方传入（来自 `MonitorReport.severityOf`），本类只做像素混合；
 * UNKNOWN/NO_PART 一律基色，**无证据不造状态色**。
 */
object HoloRenderer {

    /** 部件状态编码：0=UNKNOWN 1=OK 2=WARN 3=CRITICAL（与 MeshPreview 的 sevOfPart 同构）。 */
    private fun sevCode(s: Severity): Int = when (s) {
        Severity.CRITICAL -> 3
        Severity.WARN -> 2
        Severity.OK -> 1
        else -> 0
    }

    /**
     * 状态色 = [RobotParts.severityArgb] 单一真源归一化到 0..1（**禁止此处另写一套 RGB**）。
     * 全息风格只调「用在哪、多强」，不重定义语义色。
     */
    private fun statusRgb(s: Severity): FloatArray {
        val a = RobotParts.severityArgb(s)
        return floatArrayOf(
            ((a shr 16) and 255) / 255f,
            ((a shr 8) and 255) / 255f,
            (a and 255) / 255f,
        )
    }

    /** 核心线颜色：外轮廓亮青 / 分界中青；状态件取语义色（提亮后过曝趋白仍保留色相）。 */
    private fun kindRgb(kind: Int): FloatArray = when (kind) {
        3 -> statusRgb(Severity.CRITICAL)
        4 -> statusRgb(Severity.WARN)
        1 -> floatArrayOf(0.60f, 0.93f, 1.00f)
        2 -> floatArrayOf(0.34f, 0.72f, 0.84f)
        5 -> floatArrayOf(0.48f, 0.86f, 0.96f) // 几何折痕：介于外轮廓与分界之间的青
        else -> ZERO_RGB
    }

    /** 填充颜色：状态件取语义色（低饱和铺底），中性/无证据件用青系基色。 */
    private fun fillRgb(sev: Int): FloatArray = when (sev) {
        3 -> statusRgb(Severity.CRITICAL)
        2 -> statusRgb(Severity.WARN)
        1 -> statusRgb(Severity.OK)
        else -> floatArrayOf(0.18f, 0.50f, 0.63f)
    }

    private val ZERO_RGB = floatArrayOf(0f, 0f, 0f)

    /**
     * 图像空间几何折痕阈值：相邻像素法线点积绝对值低于此值（约 >78°）才提边。
     * 用绝对值是为了兼容 STL 面绕序不统一（对翻面的光滑邻接，abs(dot)≈1，不会误提）。
     * 0.50（约 60°）会把 QEM 壳体细分棱也画出来，看起来像乱线；收紧到硬边。
     * 再加近邻深度连续约束：同一部件前后遮挡不当成折痕。
     */
    private const val CREASE_DOT = 0.20f
    private const val CREASE_Z_FRAC = 0.03f
    private const val FILL_AMBIENT = 0.42f
    private val FILL_LIGHT = floatArrayOf(0.4472f, 0.7746f, 0.4472f)

    /**
     * 诊断用分阶段计时槽（null=关闭，生产路径零影响）。
     * 索引：0 投影 1 光栅 2 边缘掩码 3 聚合 4 发射 5 模糊 6 bloom 7 合成。
     * 只由离线工具 `tools/HoloPreview.kt` 打开；不要在产品代码里设它。
     */
    @JvmStatic
    var profileSink: LongArray? = null

    /** 背景缓存：同一尺寸只算一次（径向渐变 + 地面网格 + 暗角）。 */
    private class Background(val w: Int, val h: Int, val argb: IntArray, val vignette: FloatArray)

    @Volatile private var bg: Background? = null

    /**
     * 渲染一帧。
     *
     * @param supersample 超采样倍数（2..4）：细线抗锯齿 + 小圆件圆滑，默认 3。
     *   内存/耗时随 SS² 增长：480×360×3 ≈ 1.5M 子样本 ×3 缓冲 ≈ 18 MB。
     * @return `width*height` ARGB（不透明），可直接 `Bitmap.setPixels`。
     */
    fun render(
        mesh: DuckMesh.MeshData,
        angleDegrees: Double,
        width: Int,
        height: Int,
        severityOf: (RobotPart) -> Severity,
        supersample: Int = 3,
    ): IntArray = renderWithCoverage(mesh, angleDegrees, width, height, severityOf, supersample).first

    /**
     * 与 [render] 相同，但同时返回**模型覆盖率**（被网格覆盖的输出像素占比）。
     *
     * 为什么不从像素亮度反推：背景径向渐变本身就亮，按亮度阈值统计会把背景算成模型
     * （自检实测 vis=0.995 —— 判据失效）。覆盖率只能取自光栅化的样本计数。
     */
    fun renderWithCoverage(
        mesh: DuckMesh.MeshData,
        angleDegrees: Double,
        width: Int,
        height: Int,
        severityOf: (RobotPart) -> Severity,
        supersample: Int = 3,
    ): Pair<IntArray, Float> {
        val w = max(width, 2)
        val h = max(height, 2)
        val ss = supersample.coerceIn(2, 4)
        val bgc = background(w, h)
        val prof = profileSink
        var tMark = System.nanoTime()

        // 部件 → 状态码查表（图像层只认这张表，不反复回调）
        val sevOfPart = ByteArray(256)
        for (p in 0 until 21) {
            val part = ModelPart.of(p) ?: continue
            sevOfPart[p] = sevCode(severityOf(part)).toByte()
        }

        val v = mesh.verts
        val t = mesh.tris
        val parts = mesh.partIndices
        val nv = mesh.nVerts
        val nt = mesh.nTris

        // ── ① 光栅化（超采样缓冲）──
        val sw = w * ss
        val sh = h * ss
        val zbuf = FloatArray(sw * sh) { -Float.MAX_VALUE }
        val idbuf = IntArray(sw * sh) { -1 }
        val rbuf = FloatArray(sw * sh)
        val nxbuf = FloatArray(sw * sh)
        val nybuf = FloatArray(sw * sh)
        val nzbuf = FloatArray(sw * sh)

        val sx = FloatArray(nv); val sy = FloatArray(nv); val sd = FloatArray(nv)
        val wx = FloatArray(nv); val wy = FloatArray(nv); val wz = FloatArray(nv)
        // 🔴 内联旋转+投影（绕 Y 轴 + 透视）：DuckModelGeometry.rotateY/project 每顶点
        // 各分配一个对象（5729 顶点 ⇒ 每帧 ~1.2 万次小对象分配，实测占投影段大头）。
        // 公式与 DuckModelGeometry 逐符号相同（自检 testDuckMesh 锁两算法互算）。
        val angRad = Math.toRadians(angleDegrees)
        val cosA = kotlin.math.cos(angRad).toFloat()
        val sinA = kotlin.math.sin(angRad).toFloat()
        val focal = min(sw, sh) * DuckModelGeometry.FOCAL_RATIO
        val camD = DuckModelGeometry.CAMERA_DISTANCE
        for (k in 0 until nv) {
            val px = v[3 * k]; val py = v[3 * k + 1]; val pz = v[3 * k + 2]
            val rx = px * cosA + pz * sinA
            val rz = -px * sinA + pz * cosA
            wx[k] = rx; wy[k] = py; wz[k] = rz
            val denom = (camD - rz).coerceAtLeast(0.1f)
            val scale = camD / denom
            sx[k] = sw / 2f + rx * focal * scale
            sy[k] = sh / 2f - py * focal * scale
            sd[k] = rz
        }

        if (prof != null) { prof[8] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // 逐顶点 Fresnel：法线只在**同一零件内**平均（避免跨零件接缝串色）。
        // 键 = (vertex shl 8) or part。🔴 用开放寻址平铺数组而非 HashMap<Long,FloatArray>：
        // 后者每帧 ~1.5 万个装箱 Long + FloatArray 分配（GC 压力占光栅段大头，实测）。
        var cap = 1
        while (cap < nv * 4) cap = cap shl 1
        val mask = cap - 1
        val keys = LongArray(cap) { -1L } // -1 = 空（part<256、vertex≥0 ⇒ 合法键 ≥0）
        val nX = FloatArray(cap); val nY = FloatArray(cap)
        val nZ = FloatArray(cap); val nC = FloatArray(cap)
        val faceRim = FloatArray(3)
        for (i in 0 until nt) {
            val i0 = i * 3
            val a = t[i0]; val b = t[i0 + 1]; val c = t[i0 + 2]
            val part = parts[i].toInt() and 0xFF
            val ux = wx[b] - wx[a]; val uy = wy[b] - wy[a]; val uz = wz[b] - wz[a]
            val rx = wx[c] - wx[a]; val ry = wy[c] - wy[a]; val rz = wz[c] - wz[a]
            var nx = uy * rz - uz * ry
            var ny = uz * rx - ux * rz
            var nz = ux * ry - uy * rx
            val nl = sqrt(nx * nx + ny * ny + nz * nz)
            if (nl < 1e-9f) continue
            nx /= nl; ny /= nl; nz /= nl
            for (j in 0 until 3) {
                val key = (t[i0 + j].toLong() shl 8) or part.toLong()
                var slot = (key * -0x61C8864680B583EBL ushr 32).toInt() and mask
                while (true) {
                    val k = keys[slot]
                    if (k == key) break
                    if (k == -1L) { keys[slot] = key; break }
                    slot = (slot + 1) and mask
                }
                nX[slot] += nx; nY[slot] += ny; nZ[slot] += nz; nC[slot] += 1f
            }
        }
        if (prof != null) { prof[9] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        for (i in 0 until nt) {
            val i0 = i * 3
            val a = t[i0]; val b = t[i0 + 1]; val c = t[i0 + 2]
            val part = parts[i].toInt() and 0xFF
            var degenerate = false
            for (j in 0 until 3) {
                val key = (t[i0 + j].toLong() shl 8) or part.toLong()
                var slot = (key * -0x61C8864680B583EBL ushr 32).toInt() and mask
                var accSlot = -1
                while (true) {
                    val k = keys[slot]
                    if (k == key) { accSlot = slot; break }
                    if (k == -1L) break
                    slot = (slot + 1) and mask
                }
                if (accSlot < 0) { degenerate = true; break }
                val ax = nX[accSlot]; val ay = nY[accSlot]; val az = nZ[accSlot]
                val l = sqrt(ax * ax + ay * ay + az * az)
                if (l < 1e-9f) { degenerate = true; break }
                val vvx = wx[t[i0 + j]]; val vvy = wy[t[i0 + j]]; val vvz = wz[t[i0 + j]]
                var cx = -vvx; var cy = -vvy; var cz = DuckModelGeometry.CAMERA_DISTANCE - vvz
                val cl = sqrt(cx * cx + cy * cy + cz * cz)
                if (cl < 1e-9f) { degenerate = true; break }
                cx /= cl; cy /= cl; cz /= cl
                val dot = (ax / l) * cx + (ay / l) * cy + (az / l) * cz
                faceRim[j] = 1f - abs(dot) // 掠射边 → 1
            }
            if (degenerate) continue
            val e1x = wx[b] - wx[a]; val e1y = wy[b] - wy[a]; val e1z = wz[b] - wz[a]
            val e2x = wx[c] - wx[a]; val e2y = wy[c] - wy[a]; val e2z = wz[c] - wz[a]
            var fnx = e1y * e2z - e1z * e2y
            var fny = e1z * e2x - e1x * e2z
            var fnz = e1x * e2y - e1y * e2x
            val fnl = sqrt(fnx * fnx + fny * fny + fnz * fnz)
            if (fnl < 1e-9f) continue
            fnx /= fnl; fny /= fnl; fnz /= fnl
            rasterFace(
                zbuf, idbuf, rbuf, nxbuf, nybuf, nzbuf, sw, sh,
                sx[a], sy[a], sd[a], sx[b], sy[b], sd[b], sx[c], sy[c], sd[c],
                part, faceRim, fnx, fny, fnz,
            )
        }

        if (prof != null) { prof[1] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // Fresnel 亮度缓冲轻模糊（r=1）：抹平跨三角形插值残差
        boxBlurH(rbuf, sw, sh, 1)
        boxBlurV(rbuf, sw, sh, 1)

        if (prof != null) { prof[2] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // 深度范围先算：折痕要判断近邻是否同一层表面，不能把前后遮挡画成棱。
        var zmin = Float.MAX_VALUE
        var zmax = -Float.MAX_VALUE
        for (i in 0 until sw * sh) {
            if (idbuf[i] >= 0 && zbuf[i] > -1e30f) {
                zmin = min(zmin, zbuf[i]); zmax = max(zmax, zbuf[i])
            }
        }
        val zSpan = max(zmax - zmin, 1e-6f)
        val creaseZ = CREASE_Z_FRAC * zSpan

        // 边缘掩码：1=外轮廓 2=部件分界（超采样下 1 个子样本 ≈ 1/SS 输出像素宽）
        val emask = ByteArray(sw * sh)
        fun isCrease(i: Int, j: Int): Boolean =
            abs(zbuf[i] - zbuf[j]) <= creaseZ &&
                abs(nxbuf[i] * nxbuf[j] + nybuf[i] * nybuf[j] + nzbuf[i] * nzbuf[j]) < CREASE_DOT
        for (y in 0 until sh) {
            val row = y * sw
            for (x in 0 until sw) {
                val i = row + x
                val id = idbuf[i]
                if (id < 0) continue
                var outer = false
                var bnd = false
                var crease = false
                if (x > 0) {
                    val n = idbuf[i - 1]
                    if (n < 0) outer = true
                    else if (n != id) bnd = true
                    else if (isCrease(i, i - 1)) crease = true
                }
                if (x < sw - 1) {
                    val n = idbuf[i + 1]
                    if (n < 0) outer = true
                    else if (n != id) bnd = true
                    else if (isCrease(i, i + 1)) crease = true
                }
                if (y > 0) {
                    val n = idbuf[i - sw]
                    if (n < 0) outer = true
                    else if (n != id) bnd = true
                    else if (isCrease(i, i - sw)) crease = true
                }
                if (y < sh - 1) {
                    val n = idbuf[i + sw]
                    if (n < 0) outer = true
                    else if (n != id) bnd = true
                    else if (isCrease(i, i + sw)) crease = true
                }
                emask[i] = if (outer) 1 else if (bnd) 2 else if (crease) 3 else 0
            }
        }
        // 去掉孤立折痕像素，避免壳体细分留下的噪点和短划。
        for (y in 0 until sh) {
            val row = y * sw
            for (x in 0 until sw) {
                val i = row + x
                if (emask[i] != 3.toByte()) continue
                val hasAdj =
                    (x > 0 && emask[i - 1] == 3.toByte()) ||
                        (x < sw - 1 && emask[i + 1] == 3.toByte()) ||
                        (y > 0 && emask[i - sw] == 3.toByte()) ||
                        (y < sh - 1 && emask[i + sw] == 3.toByte())
                if (!hasAdj) emask[i] = 0
            }
        }

        if (prof != null) { prof[3] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // ── ② 聚合到输出分辨率 + 覆盖率抗锯齿 ──
        val coreI = FloatArray(w * h)
        val coreKind = ByteArray(w * h)
        val rimBuf = FloatArray(w * h)
        val znBuf = FloatArray(w * h)
        val covBuf = FloatArray(w * h)
        val sevBuf = ByteArray(w * h)
        val pidBuf = IntArray(w * h) { -1 }
        val shadeBuf = FloatArray(w * h)
        val samplesPerPx = (ss * ss).toFloat()
        for (y in 0 until h) {
            for (x in 0 until w) {
                val o = y * w + x
                var idAny = -1
                var edgePart = -1
                var rimSum = 0f
                var zSum = 0f
                var nxSum = 0f
                var nySum = 0f
                var nzSum = 0f
                var samples = 0
                var edgeCount = 0
                var edgeType = 0
                for (dy in 0 until ss) {
                    val base = (y * ss + dy) * sw + x * ss
                    for (dx in 0 until ss) {
                        val si = base + dx
                        val id = idbuf[si]
                        if (id >= 0) {
                            idAny = id; samples++
                            rimSum += rbuf[si]; zSum += zbuf[si]
                            nxSum += nxbuf[si]; nySum += nybuf[si]; nzSum += nzbuf[si]
                        }
                        val em = emask[si].toInt()
                        if (em != 0) {
                            edgeCount++
                            edgePart = id
                            if (em == 1) edgeType = 1
                            else if (em == 2 && edgeType != 1) edgeType = 2
                            else if (em == 3 && edgeType == 0) edgeType = 3
                        }
                    }
                }
                pidBuf[o] = idAny
                rimBuf[o] = if (samples > 0) rimSum / samples else 0f
                znBuf[o] = if (samples > 0) (zSum / samples - zmin) / zSpan else 0f
                covBuf[o] = samples / samplesPerPx
                sevBuf[o] = if (idAny in 0..255) sevOfPart[idAny] else 0
                val nlen = sqrt(nxSum * nxSum + nySum * nySum + nzSum * nzSum)
                shadeBuf[o] = if (nlen < 1e-8f) FILL_AMBIENT
                else FILL_AMBIENT + (1f - FILL_AMBIENT) * abs(
                    (nxSum * FILL_LIGHT[0] + nySum * FILL_LIGHT[1] + nzSum * FILL_LIGHT[2]) / nlen,
                )
                if (edgeCount > 0) {
                    val es = if (edgePart in 0..255) sevOfPart[edgePart].toInt() else 0
                    coreKind[o] = when {
                        es >= 2 -> (if (es == 3) 3 else 4).toByte()
                        edgeType == 1 -> 1
                        edgeType == 3 -> 5
                        else -> 2
                    }
                    val baseI = when (coreKind[o].toInt()) {
                        1 -> 4.6f // 外轮廓
                        2 -> 2.3f // 部件分界
                        5 -> 3.1f // 几何折痕（外形棱）
                        else -> 3.6f // 状态线
                    }
                    val cov = edgeCount / samplesPerPx
                    coreI[o] = baseI * cov * (0.55f + 0.45f * znBuf[o])
                }
            }
        }

        if (prof != null) { prof[4] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // 发射 RGB = 核心线 + Fresnel 内辉光
        val eR = FloatArray(w * h); val eG = FloatArray(w * h); val eB = FloatArray(w * h)
        for (o in 0 until w * h) {
            val df = 0.55f + 0.45f * znBuf[o]
            if (coreI[o] > 0f) {
                val rgb = kindRgb(coreKind[o].toInt())
                eR[o] += rgb[0] * coreI[o]; eG[o] += rgb[1] * coreI[o]; eB[o] += rgb[2] * coreI[o]
            }
            val rim = rimBuf[o]
            if (rim > 0.01f) {
                val fc = fillRgb(sevBuf[o].toInt())
                val glowI = rim * 0.22f * df
                eR[o] += fc[0] * glowI; eG[o] += fc[1] * glowI; eB[o] += fc[2] * glowI
            }
        }
        // 轮廓线保持清晰：只把一份拷贝拿去模糊/光晕，避免细棱被抹掉
        val sR = eR.copyOf(); val sG = eG.copyOf(); val sB = eB.copyOf()
        gaussBlur(sR, w, h, 0.22f)
        gaussBlur(sG, w, h, 0.22f)
        gaussBlur(sB, w, h, 0.22f)

        if (prof != null) { prof[5] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // ── ③ 多尺度 bloom：1/1、1/2、1/4（只作用于柔光层）──
        val bR = FloatArray(w * h); val bG = FloatArray(w * h); val bB = FloatArray(w * h)
        bloomLevel(sR, sG, sB, w, h, 1, 0.16f, bR, bG, bB)
        bloomLevel(sR, sG, sB, w, h, 2, 0.09f, bR, bG, bB)
        bloomLevel(sR, sG, sB, w, h, 4, 0.05f, bR, bG, bB)

        if (prof != null) { prof[6] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        // ── ④ 合成：背景(渐变+网格+暗角) → 半透明填充 → 加法发光 → Reinhard ──
        val out = IntArray(w * h)
        var covered = 0
        val bgArgb = bgc.argb
        val vigArr = bgc.vignette
        for (o in 0 until w * h) {
            val vig = vigArr[o]
            val bgPixel = bgArgb[o]
            var br = ((bgPixel shr 16) and 255) / 255f * vig
            var bg2 = ((bgPixel shr 8) and 255) / 255f * vig
            var bb = (bgPixel and 255) / 255f * vig
            val idAny = pidBuf[o]
            if (idAny >= 0) {
                covered++
                val sev = sevBuf[o].toInt()
                val fc = fillRgb(sev)
                var fa = ((if (sev >= 2) 0.16f else 0.11f) * shadeBuf[o] + rimBuf[o] * 0.45f) *
                    (0.62f + 0.38f * znBuf[o]) * covBuf[o]
                fa = min(fa, 0.8f)
                br = fc[0] * fa + br * (1 - fa)
                bg2 = fc[1] * fa + bg2 * (1 - fa)
                bb = fc[2] * fa + bb * (1 - fa)
            }
            val er = eR[o] + bR[o] * 0.58f
            val eg = eG[o] + bG[o] * 0.58f
            val eb = eB[o] + bB[o] * 0.58f
            out[o] = (0xFF shl 24) or
                (toSrgb(br + er / (1f + er)) shl 16) or
                (toSrgb(bg2 + eg / (1f + eg)) shl 8) or
                toSrgb(bb + eb / (1f + eb))
        }
        if (prof != null) { prof[7] += System.nanoTime() - tMark; tMark = System.nanoTime() }
        return out to (covered.toFloat() / (w * h))
    }

    /**
     * 可见像素占比（**历史工具，按亮度统计**）：仅作粗略观感指标。
     * 判据用途请用 [renderWithCoverage] 的覆盖率 —— 背景渐变本身亮，亮度阈值会假绿。
     */
    @Deprecated("亮度统计会把背景算成模型；请用 renderWithCoverage 的覆盖率")
    fun visibleFraction(pixels: IntArray, minLuma: Int = 6): Float {
        var n = 0
        for (px in pixels) {
            val r = (px shr 16) and 255
            val g = (px shr 8) and 255
            val b = px and 255
            if (max(r, max(g, b)) > minLuma + 12) n++
        }
        return n.toFloat() / pixels.size
    }

    // ── 背景（缓存）──
    private fun background(w: Int, h: Int): Background {
        bg?.let { if (it.w == w && it.h == h) return it }
        val argb = IntArray(w * h)
        val vig = FloatArray(w * h)
        val cxm = w * 0.5f
        val cym = h * 0.44f
        val rad = w * 0.72f
        val invR = 1f / max(rad, 1f)
        val vx = w / 2f
        val vy = h * 0.66f
        val mcx = w * 0.5f
        val mcy = h * 0.5f
        val maxD = sqrt(mcx * mcx + mcy * mcy)
        // 径向渐变三段色
        val c0r = 0x12; val c0g = 0x32; val c0b = 0x46
        val c1r = 0x0B; val c1g = 0x1C; val c1b = 0x2B
        val c2r = 0x05; val c2g = 0x0A; val c2b = 0x11
        val gridR = 0x12; val gridG = 0x31; val gridB = 0x3F
        for (y in 0 until h) {
            for (x in 0 until w) {
                val o = y * w + x
                val dx = (x - cxm) * invR
                val dy = (y - cym) * invR
                val t = min(1f, sqrt(dx * dx + dy * dy))
                val r: Int; val g2: Int; val b2: Int
                if (t < 0.55f) {
                    val u = t / 0.55f
                    r = lerpInt(c0r, c1r, u); g2 = lerpInt(c0g, c1g, u); b2 = lerpInt(c0b, c1b, u)
                } else {
                    val u = (t - 0.55f) / 0.45f
                    r = lerpInt(c1r, c2r, u); g2 = lerpInt(c1g, c2g, u); b2 = lerpInt(c1b, c2b, u)
                }
                var pr = r; var pg = g2; var pb = b2
                // 地面网格：水平线（平方分布）+ 透视扇形线
                var onGrid = false
                if (y >= vy) {
                    for (j in 1..6) {
                        val f = j / 6f
                        val y0 = vy + (h - vy) * f * f
                        if (abs(y - y0) <= 0.7f) { onGrid = true; break }
                    }
                    if (!onGrid) {
                        for (i in -6..6) {
                            val x0 = vx + i * w / 6f
                            if (distToSegment(x, y, x0, h.toFloat(), vx, vy) <= 0.7f) {
                                onGrid = true; break
                            }
                        }
                    }
                }
                if (onGrid) { pr = gridR; pg = gridG; pb = gridB }
                argb[o] = (0xFF shl 24) or (pr shl 16) or (pg shl 8) or pb
                val ddx = (x - mcx) / maxD
                val ddy = (y - mcy) / maxD
                vig[o] = 1f - 0.34f * min(1f, ddx * ddx + ddy * ddy)
            }
        }
        val b = Background(w, h, argb, vig)
        bg = b
        return b
    }

    private fun lerpInt(a: Int, b: Int, u: Float): Int =
        (a + (b - a) * u).toInt().coerceIn(0, 255)

    private fun distToSegment(px: Int, py: Int, x1: Float, y1: Float, x2: Float, y2: Float): Float {
        val dx = x2 - x1
        val dy = y2 - y1
        val len2 = dx * dx + dy * dy
        if (len2 < 1e-6f) return sqrt((px - x1) * (px - x1) + (py - y1) * (py - y1))
        val t = (((px - x1) * dx + (py - y1) * dy) / len2).coerceIn(0f, 1f)
        val qx = x1 + t * dx
        val qy = y1 + t * dy
        return sqrt((px - qx) * (px - qx) + (py - qy) * (py - qy))
    }

    // ── 光栅化（增量式边函数，屏幕空间线性插值深度与 Fresnel）──
    // 🔴 2026-11-17 性能：原先每像素 8 次乘法算重心坐标，光栅段实测 28ms（分阶段
    // 计时定位）。λa/λb/z/rim 都是 (x,y) 的仿射函数 ⇒ 沿扫描线增量累加即可，
    // 每像素降到 6 次加法 + 一次 z 比较。数学与旧版逐符号相同（λc=1-λa-λb）。
    private fun rasterFace(
        zbuf: FloatArray, idbuf: IntArray, rbuf: FloatArray,
        nxbuf: FloatArray, nybuf: FloatArray, nzbuf: FloatArray,
        sw: Int, sh: Int,
        ax: Float, ay: Float, az: Float,
        bx: Float, by: Float, bz: Float,
        cx: Float, cy: Float, cz: Float,
        part: Int, rim3: FloatArray,
        fnx: Float, fny: Float, fnz: Float,
    ) {
        val minX = max(0, floor(min(ax, min(bx, cx))).toInt())
        val maxX = min(sw - 1, ceil(max(ax, max(bx, cx))).toInt())
        val minY = max(0, floor(min(ay, min(by, cy))).toInt())
        val maxY = min(sh - 1, ceil(max(ay, max(by, cy))).toInt())
        if (minX > maxX || minY > maxY) return
        val det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if (abs(det) < 1e-6f) return
        val invDet = 1f / det
        // λa = A*x + B*y + Ca；λb = D*x + E*y + Cb（对 px 中心取 +0.5 偏移并入常数项，
        // 与旧版 floor 像素遍历同一采样点集）
        val A = (by - cy) * invDet
        val B = (cx - bx) * invDet
        val D = (cy - ay) * invDet
        val E = (ax - cx) * invDet
        val x0 = minX + 0.5f
        val Ca = -(A * cx + B * cy)
        val Cb = -(D * cx + E * cy)
        // z = az*λa + bz*λb + cz*λc = cz + λa*(az-cz) + λb*(bz-cz)（仿射）
        val da = az - cz
        val db = bz - cz
        val ZA = A * da + D * db
        val ZB = B * da + E * db
        val ZC = cz + Ca * da + Cb * db
        val ra = rim3[0] - rim3[2]
        val rb = rim3[1] - rim3[2]
        val RA = A * ra + D * rb
        val RB = B * ra + E * rb
        val RC = rim3[2] + Ca * ra + Cb * rb
        val eps = 0.001f
        for (py in minY..maxY) {
            // 🔴 行基值必须用**本行**的 y（py+0.5 像素中心）。首版曾把 y0 写成
            // 循环外常数 —— 每行都拿第一行的 λ 值，整帧碎成竖条纹（视觉负对照抓出）。
            val y = py + 0.5f
            var la = A * x0 + B * y + Ca
            var lb = D * x0 + E * y + Cb
            var z = ZA * x0 + ZB * y + ZC
            var r = RA * x0 + RB * y + RC
            val row = py * sw
            for (px in minX..maxX) {
                if (la >= -eps && lb >= -eps && la + lb <= 1f + eps) {
                    val idx = row + px
                    if (z > zbuf[idx]) {
                        zbuf[idx] = z
                        idbuf[idx] = part
                        rbuf[idx] = r
                        nxbuf[idx] = fnx
                        nybuf[idx] = fny
                        nzbuf[idx] = fnz
                    }
                }
                la += A; lb += D; z += ZA; r += RA
            }
        }
    }

    // ── 模糊 / bloom ──
    private fun boxBlurH(a: FloatArray, w: Int, h: Int, r: Int) {
        val tmp = FloatArray(w)
        for (y in 0 until h) {
            val row = y * w
            for (x in 0 until w) {
                var s = 0f; var n = 0
                for (k in -r..r) {
                    val xx = x + k
                    if (xx in 0 until w) { s += a[row + xx]; n++ }
                }
                tmp[x] = s / n
            }
            System.arraycopy(tmp, 0, a, row, w)
        }
    }

    private fun boxBlurV(a: FloatArray, w: Int, h: Int, r: Int) {
        val tmp = FloatArray(h)
        for (x in 0 until w) {
            for (y in 0 until h) {
                var s = 0f; var n = 0
                for (k in -r..r) {
                    val yy = y + k
                    if (yy in 0 until h) { s += a[yy * w + x]; n++ }
                }
                tmp[y] = s / n
            }
            for (y in 0 until h) a[y * w + x] = tmp[y]
        }
    }

    private fun gaussBlur(a: FloatArray, w: Int, h: Int, sigma: Float) {
        val r = max(1, ceil(sigma * 2.5f).toInt())
        val k = FloatArray(r + 1)
        var sum = 0f
        for (i in 0..r) {
            k[i] = exp(-(i * i).toDouble() / (2.0 * sigma * sigma)).toFloat()
            sum += if (i == 0) k[i] else 2f * k[i]
        }
        for (i in 0..r) k[i] /= sum
        val line = FloatArray(max(w, h))
        val tmp = FloatArray(max(w, h))
        for (y in 0 until h) {
            System.arraycopy(a, y * w, line, 0, w)
            for (x in 0 until w) {
                var acc = 0f
                for (i in -r..r) acc += line[clamp(x + i, w)] * k[abs(i)]
                tmp[x] = acc
            }
            System.arraycopy(tmp, 0, a, y * w, w)
        }
        for (x in 0 until w) {
            for (y in 0 until h) line[y] = a[y * w + x]
            for (y in 0 until h) {
                var acc = 0f
                for (i in -r..r) acc += line[clamp(y + i, h)] * k[abs(i)]
                tmp[y] = acc
            }
            for (y in 0 until h) a[y * w + x] = tmp[y]
        }
    }

    private fun bloomLevel(
        eR: FloatArray, eG: FloatArray, eB: FloatArray, w: Int, h: Int,
        scale: Int, weight: Float, bR: FloatArray, bG: FloatArray, bB: FloatArray,
    ) {
        // 🔴 2026-11-17 性能：模糊核原先用逐像素 (2r+1) 抽头高斯，9 次调用实测占整帧
        // 60ms（分阶段计时定位，非猜）。换成前缀和盒式模糊（O(1)/像素，盒式与高斯
        // 在辉光用途上无视觉差）。scale=1 时 down/upsample 是恒等映射，直接跳过。
        val radius = max(1, (max(1.5f, scale * 1.6f)).toInt())
        if (scale == 1) {
            for (ch in 0 until 3) {
                val e = if (ch == 0) eR else if (ch == 1) eG else eB
                val b = if (ch == 0) bR else if (ch == 1) bG else bB
                val copy = e.copyOf()
                boxBlurClamped(copy, w, h, radius)
                for (i in 0 until w * h) b[i] += copy[i] * weight
            }
            return
        }
        val sw2 = max(2, w / scale)
        val sh2 = max(2, h / scale)
        val r = FloatArray(sw2 * sh2)
        val g = FloatArray(sw2 * sh2)
        val b = FloatArray(sw2 * sh2)
        downsample(eR, w, h, r, sw2, sh2)
        downsample(eG, w, h, g, sw2, sh2)
        downsample(eB, w, h, b, sw2, sh2)
        boxBlurClamped(r, sw2, sh2, radius)
        boxBlurClamped(g, sw2, sh2, radius)
        boxBlurClamped(b, sw2, sh2, radius)
        val up = FloatArray(w * h)
        upsampleBilinearTable(r, sw2, sh2, up, w, h)
        for (i in 0 until w * h) bR[i] += up[i] * weight
        upsampleBilinearTable(g, sw2, sh2, up, w, h)
        for (i in 0 until w * h) bG[i] += up[i] * weight
        upsampleBilinearTable(b, sw2, sh2, up, w, h)
        for (i in 0 until w * h) bB[i] += up[i] * weight
    }

    /**
     * 前缀和盒式模糊（水平+垂直各一遍，边界取 clamp 扩展）。
     * 前缀和数组复用调用方不持有的临时 buffer，避免每帧分配两份 w×h。
     */
    private val prefixBuf = ThreadLocal.withInitial { FloatArray(0) }

    private fun boxBlurClamped(a: FloatArray, w: Int, h: Int, r: Int) {
        if (w <= 0 || h <= 0) return
        val n = max(w, h) + 1
        var pre = prefixBuf.get()
        if (pre.size < n) { pre = FloatArray(n); prefixBuf.set(pre) }
        val inv = 1f / (2 * r + 1)
        // 水平
        val line = FloatArray(w)
        for (y in 0 until h) {
            val row = y * w
            pre[0] = 0f
            for (x in 0 until w) pre[x + 1] = pre[x] + a[row + x]
            val last = a[row + w - 1]
            val first = a[row]
            for (x in 0 until w) {
                val x0 = max(0, x - r)
                val x1 = min(w, x + r + 1)
                var s = pre[x1] - pre[x0]
                if (x - r < 0) s += first * (r - x)
                if (x + r >= w) s += last * (x + r - w + 1)
                line[x] = s * inv
            }
            System.arraycopy(line, 0, a, row, w)
        }
        // 垂直（列扫描，缓存不友好但 w×h 小；prefix 按列构建）
        val col = FloatArray(h)
        for (x in 0 until w) {
            pre[0] = 0f
            for (y in 0 until h) pre[y + 1] = pre[y] + a[y * w + x]
            val last = a[(h - 1) * w + x]
            val first = a[x]
            for (y in 0 until h) {
                val y0 = max(0, y - r)
                val y1 = min(h, y + r + 1)
                var s = pre[y1] - pre[y0]
                if (y - r < 0) s += first * (r - y)
                if (y + r >= h) s += last * (y + r - h + 1)
                col[y] = s * inv
            }
            for (y in 0 until h) a[y * w + x] = col[y]
        }
    }

    private fun downsample(src: FloatArray, w: Int, h: Int, dst: FloatArray, dw: Int, dh: Int) {
        for (dy in 0 until dh) {
            val y0 = dy * h / dh
            val y1 = max(y0 + 1, (dy + 1) * h / dh)
            for (dx in 0 until dw) {
                val x0 = dx * w / dw
                val x1 = max(x0 + 1, (dx + 1) * w / dw)
                var s = 0f
                for (y in y0 until y1) for (x in x0 until x1) s += src[y * w + x]
                dst[dy * dw + dx] = s / ((y1 - y0) * (x1 - x0))
            }
        }
    }

    private fun upsampleBilinear(src: FloatArray, sw: Int, sh: Int, dst: FloatArray, dw: Int, dh: Int) {
        for (y in 0 until dh) {
            val fy = (y + 0.5f) * sh / dh - 0.5f
            val y0 = clamp(floor(fy).toInt(), sh)
            val y1 = min(sh - 1, y0 + 1)
            val ty = (fy - y0).coerceIn(0f, 1f)
            for (x in 0 until dw) {
                val fx = (x + 0.5f) * sw / dw - 0.5f
                val x0 = clamp(floor(fx).toInt(), sw)
                val x1 = min(sw - 1, x0 + 1)
                val tx = (fx - x0).coerceIn(0f, 1f)
                val a = src[y0 * sw + x0] * (1 - tx) + src[y0 * sw + x1] * tx
                val b = src[y1 * sw + x0] * (1 - tx) + src[y1 * sw + x1] * tx
                dst[y * dw + x] = a * (1 - ty) + b * ty
            }
        }
    }

    /**
     * [upsampleBilinear] 的查表版：x 向插值参数与 y 无关，y 向与 x 无关，
     * 全部预计算成表（实测把 bloom 段从 32ms 拉回 ~8ms —— floor/clamp 从
     * 每像素 4 次降到每行 1 次）。
     */
    private fun upsampleBilinearTable(
        src: FloatArray, sw: Int, sh: Int, dst: FloatArray, dw: Int, dh: Int,
    ) {
        val x0t = IntArray(dw); val x1t = IntArray(dw); val txt = FloatArray(dw)
        for (x in 0 until dw) {
            val fx = (x + 0.5f) * sw / dw - 0.5f
            val x0 = clamp(floor(fx).toInt(), sw)
            x0t[x] = x0
            x1t[x] = min(sw - 1, x0 + 1)
            txt[x] = (fx - x0).coerceIn(0f, 1f)
        }
        for (y in 0 until dh) {
            val fy = (y + 0.5f) * sh / dh - 0.5f
            val y0 = clamp(floor(fy).toInt(), sh)
            val y1 = min(sh - 1, y0 + 1)
            val ty = (fy - y0).coerceIn(0f, 1f)
            val row0 = y0 * sw
            val row1 = y1 * sw
            val dstRow = y * dw
            val ity = 1f - ty
            for (x in 0 until dw) {
                val tx = txt[x]
                val itx = 1f - tx
                val a = src[row0 + x0t[x]] * itx + src[row0 + x1t[x]] * tx
                val b = src[row1 + x0t[x]] * itx + src[row1 + x1t[x]] * tx
                dst[dstRow + x] = a * ity + b * ty
            }
        }
    }

    private fun clamp(v: Int, n: Int): Int = if (v < 0) 0 else if (v >= n) n - 1 else v

    private fun toSrgb(v: Float): Int =
        min(255, (max(0f, min(1f, v)) * 255f + 0.5f).toInt())
}
