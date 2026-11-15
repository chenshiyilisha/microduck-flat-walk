package io.microduck.app.core

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * MicroDuck 真实外观网格 —— 从训练/仿真侧 mjlab MJCF 提取的 STL 三角形。
 *
 * ── 为什么不用程序化椭球 ──
 * 用户反馈原 `DuckModelGeometry` 的椭球+火柴人「不像鸭子」。训练侧
 * `microduck-hf/mjlab` 有真实 STL 网格（躯干壳/头壳/脚/脸等 18 个外观部件），
 * 是鸭子的真实外形。本类从 `duck_mesh.bin`（由 `tools/build_duck_mesh.py` 用 mujoco
 * 提取世界坐标三角形）加载，供 Canvas 2D 渲染真实三角形。
 *
 * ── 🔴 坐标系契约（2026-11-15 修复「一横一竖两个模型」）──
 * `duck_mesh.bin` 里存的是 **MuJoCo 世界坐标（Z-up）**，**不是** App 坐标。
 * 一手依据：
 *  · MuJoCo 平台文档「The default world orientation is Z-up: option.gravity defaults
 *    to `0 0 -9.81`」（mujoco_wasm / mjswan 坐标转换章节同述）。
 *  · 本项目 `robot_walk.xml`：`trunk_base pos="0 0 0.12"`（Z 为高度）、
 *    `neck`/`lens` 在 +X（喙方向）、`hip_l` 在 +Y（左）⇒ +X 前 / +Y 左 / +Z 上。
 *  · [DuckModelGeometry] 约定：+X 右 / +Y 上 / +Z 前（喙朝观察者）。
 *
 * 生成脚本此前只做「居中 + 归一化」，**从未做轴变换**，注释却写成「y 向上」——
 * 于是真实网格躺倒 90°，与竖立的示意骨架叠在同一 Canvas，形成「一横一竖两个模型」。
 * 本类在**加载时**统一做循环置换 `(x,y,z)_mjc → (y,z,x)_app`：
 *   app.y = mjc.z（上→上）、app.z = mjc.x（喙→朝观察者）、app.x = mjc.y（左→右）。
 * 面朝观察者的物体，其左侧本就落在观察者右边，故「左→右」是旋转结果而非镜像。
 * 该映射是 3-cycle 偶置换，det=+1（保持手性）；与通行做法 `(x,y,z)→(x,z,-y)`
 * （绕 X 轴 −90°，mujoco_wasm / mjswan）同族，仅再绕 Y 轴 −90° 令喙正对观察者。
 *
 * 变换后再按 [DuckModelGeometry.NODES] 的 y 范围做**均匀缩放 + 居中**，使真实网格
 * 与 15 个关节状态锚点落在同一坐标系、同一尺度 —— 这是「单一模型 + 叠加关节状态」
 * 的通行做法（ROCOS HMI「从控制器加载 URDF 及网格，随关节状态更新模型」、
 * Lucy Control Panel「3D viewer 与 /joint_states 同源」、Reachy Mini dashboard
 * 「MuJoCo + Three.js 实时镜像实体姿态」），而不是两套几何并列。
 *
 * ── 官方配色（2026-11-15「别人模型用什么颜色也参考一下」）──
 * 一手依据：ROBOTIS 产品页「REAL MICRODUCK COLORWAYS」与 Economic Times 规格文：
 *  · Cream   = 奶油白壳 + **橙 trim / 橙喙**（首发主色）
 *  · Graphite= 石墨灰壳 + 黄 trim/喙；Lavender= 薰衣草紫壳 + 黄；Sky= 天蓝壳 + 橙
 *  · 镜头/眼恒为黑色
 * 生成脚本写的是「语义色」（主橙 / 深橙 / 黑），本类在加载时重映射为 Cream 款：
 * 主橙→奶油白壳、深橙→橙 trim/喙、黑→镜头黑。**纯视觉层，不参与任何判据。**
 *
 * ── 二进制格式（见 build_duck_mesh.py）──
 *   header:  magic(4="DMSH") version(u32=1) n_verts(u32) n_tris(u32)
 *   vertices:  n_verts * 3 * float32 (x, y, z)  —— MuJoCo 世界坐标，已居中归一化
 *   triangles: n_tris * 3 * int32 (顶点索引)
 *   tri_colors: n_tris * uint32 (ARGB，生成期语义色)
 *
 * ── 纯 JVM，零 Android 依赖 ──
 * core 是 Kotlin/JVM 模块，资源通过 classpath 加载（`/duck_mesh.bin`）。
 * 旋转/投影复用 [DuckModelGeometry] 的同一套纯 JVM 算法，不引入新依赖。
 */
object DuckMesh {

    private const val RESOURCE = "/duck_mesh.bin"
    private const val MAGIC = 0x48534D44  // "DMSH"（小端序下的 int 值）

    // ── 生成期语义色 → 官方 Cream 配色 ──
    private const val SEM_SHELL = 0xFFFF8A3D.toInt()   // 生成期主橙：躯干/头/脸/颈/腿
    private const val SEM_TRIM = 0xFFE0691F.toInt()    // 生成期深橙：喙/脚/底壳/sole
    private const val SEM_LENS = 0xFF2B2B2B.toInt()    // 生成期黑：镜头/眼
    private const val CREAM_SHELL = 0xFFF3E6D2.toInt() // 官方 Cream 壳
    private const val ORANGE_TRIM = 0xFFFF8A3D.toInt() // 官方橙 trim / 喙
    private const val LENS_BLACK = 0xFF2B2B2B.toInt()  // 官方镜头黑

    /** 与 [DuckModelGeometry.NODES] 的 y 范围对齐（脚踝 -1.48 … 头滚转 1.32）。 */
    private const val NODE_Y_MIN = -1.48f
    private const val NODE_Y_MAX = 1.32f

    /** 顶点表（**已转为 App Y-up 坐标系**并对齐到 NODES 尺度）+ 官方配色。 */
    data class MeshData(
        val verts: FloatArray,   // 长度 n_verts * 3
        val tris: IntArray,      // 长度 n_tris * 3
        val colors: IntArray,    // 长度 n_tris，ARGB（官方配色）
        val nVerts: Int,
        val nTris: Int,
    )

    @Volatile private var cached: MeshData? = null

    /**
     * 加载网格。优先从 classpath 资源读；失败抛异常（调用方决定降级策略）。
     * 带缓存：资源只解析一次。
     */
    fun load(): MeshData {
        cached?.let { return it }
        val data = parse(readResource())
        cached = data
        return data
    }

    /** 测试用：注入内存数据，绕过资源加载。 */
    fun loadFromBytes(bytes: ByteArray): MeshData = parse(bytes)

    private fun readResource(): ByteArray {
        val stream = DuckMesh::class.java.getResourceAsStream(RESOURCE)
            ?: error("classpath 资源 $RESOURCE 不存在 —— 先跑 tools/build_duck_mesh.py 生成")
        return stream.use { it.readBytes() }
    }

    /**
     * MuJoCo 世界坐标 → App 坐标的**轴置换**（det=+1 的循环置换，保持手性）。
     * 暴露给 core 自检做「两条独立算法互算」与负对照，禁止在此偷偷改成镜像。
     */
    fun toAppAxes(p: Vec3): Vec3 = Vec3(p.y, p.z, p.x)

    private fun parse(bytes: ByteArray): MeshData {
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val magic = buf.int
        if (magic != MAGIC) error("duck_mesh.bin 魔数不匹配: 0x$magic (期望 0x$MAGIC)")
        val version = buf.int
        if (version != 1) error("duck_mesh.bin 版本不支持: $version (期望 1)")
        val nVerts = buf.int
        val nTris = buf.int
        if (nVerts <= 0 || nTris <= 0) error("duck_mesh.bin 计数异常: n_verts=$nVerts n_tris=$nTris")

        val verts = FloatArray(nVerts * 3)
        buf.asFloatBuffer().get(verts)
        buf.position(buf.position() + nVerts * 3 * Float.SIZE_BYTES)
        val tris = IntArray(nTris * 3)
        buf.asIntBuffer().get(tris)
        buf.position(buf.position() + nTris * 3 * Int.SIZE_BYTES)
        val colors = IntArray(nTris)
        buf.asIntBuffer().get(colors)

        // 基本健全性：三角形索引不越界
        for (i in tris.indices) {
            if (tris[i] < 0 || tris[i] >= nVerts) {
                error("duck_mesh.bin 三角形索引越界: tris[$i]=${tris[i]} n_verts=$nVerts")
            }
        }
        val appVerts = toAppFrame(verts)
        val official = IntArray(nTris) { i -> officialColor(colors[i]) }
        return MeshData(appVerts, tris, official, nVerts, nTris)
    }

    /**
     * 轴置换 + 均匀缩放 + 居中，使真实网格与 [DuckModelGeometry.NODES] 的
     * 15 个关节锚点落在同一坐标系同一尺度（这样状态圆点才能叠在真实模型上）。
     *
     * 🔴 均匀缩放（三轴同一 s）—— 不能用各轴独立缩放，否则鸭子会被拉变形。
     * y 用 NODES 的 [NODE_Y_MIN], [NODE_Y_MAX] 定标，x/z 只做居中不额外定标。
     */
    private fun toAppFrame(v: FloatArray): FloatArray {
        val out = FloatArray(v.size)
        var i = 0
        while (i < v.size) {
            val p = toAppAxes(Vec3(v[i], v[i + 1], v[i + 2]))
            out[i] = p.x; out[i + 1] = p.y; out[i + 2] = p.z
            i += 3
        }
        var xMin = Float.MAX_VALUE; var xMax = -Float.MAX_VALUE
        var yMin = Float.MAX_VALUE; var yMax = -Float.MAX_VALUE
        var zMin = Float.MAX_VALUE; var zMax = -Float.MAX_VALUE
        i = 0
        while (i < out.size) {
            val x = out[i]; val y = out[i + 1]; val z = out[i + 2]
            if (x < xMin) xMin = x; if (x > xMax) xMax = x
            if (y < yMin) yMin = y; if (y > yMax) yMax = y
            if (z < zMin) zMin = z; if (z > zMax) zMax = z
            i += 3
        }
        val spanY = (yMax - yMin).coerceAtLeast(1e-6f)
        val s = (NODE_Y_MAX - NODE_Y_MIN) / spanY
        val cx = -(xMin + xMax) / 2f * s
        val cy = (NODE_Y_MIN + NODE_Y_MAX) / 2f - (yMin + yMax) / 2f * s
        val cz = -(zMin + zMax) / 2f * s
        i = 0
        while (i < out.size) {
            out[i] = out[i] * s + cx
            out[i + 1] = out[i + 1] * s + cy
            out[i + 2] = out[i + 2] * s + cz
            i += 3
        }
        return out
    }

    /** 生成期语义色 → 官方 Cream 配色。未知颜色原样保留（不造色）。 */
    private fun officialColor(argb: Int): Int = when (argb) {
        SEM_SHELL -> CREAM_SHELL
        SEM_TRIM -> ORANGE_TRIM
        SEM_LENS -> LENS_BLACK
        else -> argb
    }

    /**
     * 投影一帧网格：把每个三角形的三个顶点旋转+投影，按深度排序（远→近）。
     * 返回投影三角形列表，View 只负责画**不透明**填充。
     *
     * ── 2026-11-15 「模型还是不行 / 一堆碎片」修复（查证后按平台通行做法）──
     * 旧版 View 给每个三角形设 alpha 165~240 的半透明填充，上万个面层层叠加；
     * 而 Canvas 2D 没有 z-buffer，只能靠 painter's algorithm 近似遮挡。
     * 一手依据（Android 3D 渲染资料 / androidexperto 3D 排障清单）：
     *  · 真实 3D 渲染必须 `glEnable(GL_DEPTH_TEST)` 或等价的不透明深度排序；
     *  · 「模型看起来是碎片/线框」的典型成因 = 半透明材质 + 缺光照 + 面绕序混乱；
     *  · 最小 shader 也需要 position + normal + 一盏方向光（ambient + Lambert diffuse）。
     * 本项目离线零依赖，仍走 Canvas 软件投影，故在 core 纯 JVM 层补齐等价三要素：
     *  ① **不透明**：alpha 强制 0xFF，靠深度排序正确遮挡（不再半透明叠色）；
     *  ② **Lambert 光照**：由旋转后的世界坐标算法线，|n·L| 双面漫反射 + 环境光，
     *     让奶油白壳有明暗立体感；双面取绝对值可避开 STL 面绕序不统一的坑；
     *  ③ 深度排序仍保留（painter's algorithm，封闭壳体的通行近似）。
     *
     * @param angleDegrees 绕 Y 轴旋转角（与 DuckModelGeometry.rotateY 同约定）
     * @param width 画布宽（像素）
     * @param height 画布高（像素，已扣除顶部/底部文字带）
     */
    fun project(mesh: MeshData, angleDegrees: Double, width: Float, height: Float): List<ProjectedTriangle> {
        val out = ArrayList<ProjectedTriangle>(mesh.nTris)
        val v = mesh.verts
        val t = mesh.tris
        val c = mesh.colors
        for (i in 0 until mesh.nTris) {
            val i0 = i * 3
            val aIdx = t[i0] * 3
            val bIdx = t[i0 + 1] * 3
            val cIdx = t[i0 + 2] * 3
            // 先旋转到「相机空间」（App 世界系），法线/光照都在这里算，
            // 这样模型旋转时明暗跟着变，符合真实光照而不是贴图烤死。
            val wa = DuckModelGeometry.rotateY(Vec3(v[aIdx], v[aIdx + 1], v[aIdx + 2]), angleDegrees)
            val wb = DuckModelGeometry.rotateY(Vec3(v[bIdx], v[bIdx + 1], v[bIdx + 2]), angleDegrees)
            val wc = DuckModelGeometry.rotateY(Vec3(v[cIdx], v[cIdx + 1], v[cIdx + 2]), angleDegrees)
            val pa = DuckModelGeometry.project(wa, width, height)
            val pb = DuckModelGeometry.project(wb, width, height)
            val pc = DuckModelGeometry.project(wc, width, height)
            val depth = (pa.depth + pb.depth + pc.depth) / 3f
            out.add(ProjectedTriangle(pa, pb, pc, depth, shadeColor(c[i], wa, wb, wc)))
        }
        out.sortBy { it.depth }
        return out
    }

    /** 环境光系数：保证背光面不是纯黑（官方奶油白壳仍需可辨）。 */
    const val AMBIENT = 0.48f
    /** 固定方向光（世界系，从左上前方打来），已归一化。 */
    val LIGHT: Vec3 = Vec3(0.4472f, 0.7746f, 0.4472f)

    /**
     * 单面 Lambert 明暗：由三角形两叉积求法线 n，diffuse = |n·L|（双面），
     * shade = AMBIENT + (1-AMBIENT)·diffuse，再把 RGB 乘上 shade、alpha 强制不透明。
     * 暴露给 core 自检做「光照真的在起作用」的正/负对照。
     */
    fun shadeColor(argb: Int, a: Vec3, b: Vec3, c: Vec3): Int {
        val ux = b.x - a.x; val uy = b.y - a.y; val uz = b.z - a.z
        val vx = c.x - a.x; val vy = c.y - a.y; val vz = c.z - a.z
        val nx = uy * vz - uz * vy
        val ny = uz * vx - ux * vz
        val nz = ux * vy - uy * vx
        val len = kotlin.math.sqrt(nx * nx + ny * ny + nz * nz)
        // 退化三角形（面积≈0）法线不可用 ⇒ 只给环境光，不引入 NaN。
        val diffuse = if (len < 1e-8f) 0f
        else kotlin.math.abs((nx * LIGHT.x + ny * LIGHT.y + nz * LIGHT.z) / len).coerceIn(0f, 1f)
        val shade = AMBIENT + (1f - AMBIENT) * diffuse
        val r = (((argb ushr 16) and 0xFF) * shade).toInt().coerceIn(0, 255)
        val g = (((argb ushr 8) and 0xFF) * shade).toInt().coerceIn(0, 255)
        val bl = ((argb and 0xFF) * shade).toInt().coerceIn(0, 255)
        // 🔴 alpha 恒 0xFF：不透明是深度排序能正确遮挡的前提（不再半透明叠色）。
        return (0xFF shl 24) or (r shl 16) or (g shl 8) or bl
    }
}

/** 投影后的三角形：三个屏幕坐标 + 平均深度 + ARGB 颜色。 */
data class ProjectedTriangle(
    val a: ProjectedPoint,
    val b: ProjectedPoint,
    val c: ProjectedPoint,
    val depth: Float,
    val colorArgb: Int,
)
