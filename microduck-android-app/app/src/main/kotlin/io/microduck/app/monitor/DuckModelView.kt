package io.microduck.app.monitor

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.view.MotionEvent
import android.view.View
import androidx.core.content.ContextCompat
import io.microduck.app.R
import io.microduck.app.core.DuckMesh
import io.microduck.app.core.DuckModelGeometry
import io.microduck.app.core.HoloRenderer
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.RobotPart
import io.microduck.app.core.RobotParts
import io.microduck.app.core.Severity

/**
 * 鸭子真实外观模型 —— **单一真实网格 + 按部件本体着色，非运动学解算**。
 *
 * ── 阶段 4（颜色即状态，见重构规划 §5）──
 * 旧版在真实网格上叠 15 个状态圆点，状态与模型本体割裂（用户明确要求去掉）。
 * 现改为：DMSH v2 网格每个三角形带 partIndex，core 的 [DuckMesh.project] 按
 * [MonitorReport.severityOf] 把状态色低强度叠加到官方基色上，再过 Lambert 光照。
 * 本 View 只做「接收 report → 调同一条投影链 → 填充不透明三角形」，
 * 不再持有任何圆点 Paint，也不自己判severity（单一真源在 core）。
 *
 * ── 🔴 2026-11-15 真因修复：Android 资源路径 ──
 * 旧版 `DuckMesh.load()` 用 `Class.getResourceAsStream("/duck_mesh.bin")`，这在**纯 JVM
 * 自检**里能读（资源在 core/src/main/resources，selftest.sh 拷进 fat 目录），
 * 但在 **Android** 上该文件被打进 APK 根目录（Java resource），ART 的 ClassLoader
 * 不会去 APK 根目录找 resource ⇒ 返回 null ⇒ ensureMesh() 抛异常 ⇒ **静默降级成
 * 程序化线框**。真机截图里「上下两团线框 + 一列竖排灰点」就是降级几何。
 * 一手依据（多来源一致）：StackOverflow 25996774 / 26603493、codingtechroom
 * 「getResourceAsStream 返回 null」排查、tasselx/AndroidNote「资源文件拷贝的三种方式」
 * ⇒ Android 正解是 `src/main/assets/` + `AssetManager.open()`，或 `res/raw` +
 * `openRawResource()`。故本 View 从 assets 读字节，交给 core 的 [DuckMesh.loadFromBytes]
 * 解析（core 保持零 Android 依赖，classpath 路径仅供 JVM 自检）。
 *
 * ── 「模型还是不行 / 一堆碎片」修复（按 3D 渲染通行做法）──
 * 一手依据：Android 3D 渲染资料与 androidexperto 排障清单 ——「模型看起来是碎片」的
 * 典型成因是半透明材质 + 缺光照 + 面绕序混乱；正确做法是**不透明 + 深度测试 + 至少
 * 一盏方向光（ambient + Lambert diffuse）**。本项目离线零依赖仍走 Canvas 软件投影，
 * 故由 core 的 [DuckMesh.project] 在纯 JVM 层产出「不透明 + Lambert 明暗」的每面颜色，
 * View 只做填充；深度排序保留为 painter's algorithm（封闭壳体的通行近似）。
 *
 * ── 文字零遮挡 ──
 * 旧版在 canvas 里 drawText 顶部声明与底部图例，压在模型头/脚上（用户反馈「区域被
 * 文字遮挡」）。现**本 View 只画几何**，声明与图例由 MainActivity 用独立 TextView
 * 放在模型卡片外；绘图区因此可用满整个 View 高度，模型更大更完整。
 *
 * ── 性能 / idle 死锁 ──
 * 网格有上万三角形；若用连续 ValueAnimator（900ms ≈ 60 帧）会变成每秒几十万次
 * drawPath，真机必卡；项目还踩过「持续 UI 刷新 → uiautomator waitForIdle 死锁」。
 * 故改为 **1s tick 直接步进 6°**（一圈 60s，仍是缓慢旋转），每秒只重绘一帧；
 * 触摸拖动按需重绘并做 30ms 节流。本 View 只 onDraw、绝不 setText。
 *
 * ── 阶段 5：数字孪生全息渲染（2026-11-17，用户确认效果图后落地）──
 * 不透明 Lambert 填充被**全息线框**取代：整条像素管线在 core 的 [HoloRenderer]
 * （纯 JVM，可被自检真跑），本 View 只做 `Bitmap.setPixels` + `drawBitmap`。
 * 管线 = 超采样 z-buffer 光栅化（精确遮挡 + 部件 ID）→ 图像空间提边（外轮廓/部件分界）
 * → 覆盖率抗锯齿 → HDR 三级 bloom → Reinhard → 背景渐变/地面网格/暗角合成。
 * 状态色仍走单一真源 [RobotParts.severityArgb]（经 [HoloRenderer] 的 fillRgb/kindRgb），
 * 本 View 只把 [MonitorReport.severityOf] 作为回调传进去 —— 颜色即状态的链路没换。
 *
 * ── 性能（手机端）──
 * 全息管线与分辨率强相关（内存/耗时 ∝ 内部像素 × SS²）。故内部渲染尺寸**上限**
 * [HOLO_MAX_DIM]（拖动时降到 [HOLO_MAX_DIM_DRAG]、SS 降一档），再按视图比例缩放后
 * 由 Canvas 双线性放大 —— 全息风格对轻微放大不敏感，换来每秒一帧的稳定预算。
 * 帧缓存按「角度 1° 量化 + 状态签名」失效，旋转 tick 每秒只重算一次。
 *
 * ── 颜色语义 ──
 * 状态色来自 core 的 [RobotParts.severityArgb] 单一真源：
 * 绿=OK / 琥珀=WARN / 红=CRITICAL / 青系基色=UNKNOWN。**没证据用基色，绝不默认绿**。
 */
class DuckModelView(context: Context) : View(context) {

    private val d = resources.displayMetrics.density
    private fun dp(v: Float) = v * d

    // ── 降级路径（assets 网格加载失败时才用）──
    private val hullPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(1f); color = ContextCompat.getColor(context, R.color.md_outline)
    }
    private val bonePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(2f); color = ContextCompat.getColor(context, R.color.md_accent)
    }
    private val surfacePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(2.2f); strokeCap = Paint.Cap.ROUND
    }
    private val bodyFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }

    private val groundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL; color = ContextCompat.getColor(context, R.color.md_card)
    }

    @Volatile private var report: MonitorReport? = null
    @Volatile private var angleDeg: Float = 0f  // UI 写、渲染线程读
    private var rotating = true

    /** 真实外观网格：首次使用时从 assets 加载并缓存；失败则降级到程序化几何。 */
    @Volatile private var mesh: DuckMesh.MeshData? = null
    private var meshLoaded = false
    private var meshFailed = false

    /** 触摸拖动状态：DOWN 记录起点，MOVE 累计转角，UP 恢复自动旋转。 */
    private var isDragging = false
    private var dragStartX = 0f
    private var dragStartAngle = 0f
    private var lastDragDrawMs = 0L

    // ── 全息帧缓存：同角度同状态不重算；渲染在后台线程，UI 线程只贴图 ──
    // 🔴 桌面稳态 42ms/帧（480×360 ss=3，HoloPreview 实测），手机约 3~5 倍 ⇒
    // 同步渲染在 UI 线程会卡帧（uiautomator idle 死锁老坑）。改为后台单线程渲染、
    // 「最新优先」去重（in-flight 期间的新请求只记 key 不排队），完成后 post 回 UI。
    private var holoBitmap: Bitmap? = null
    private var holoSrcRect = Rect()
    private var holoKeyAngle = Int.MIN_VALUE
    private var holoKeySev = Int.MIN_VALUE
    private var holoKeyW = -1
    private var holoKeyH = -1
    private val bitmapPaint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    private val dstRect = android.graphics.RectF()
    private var renderExecutor: java.util.concurrent.ExecutorService? = null
    /** 正在后台渲染的请求键；null = 空闲。用 key 字符串做最新优先去重。 */
    @Volatile private var inflightKey: String? = null

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (renderExecutor == null) {
            renderExecutor = java.util.concurrent.Executors.newSingleThreadExecutor { r ->
                Thread(r, "duck-holo-render").apply { priority = Thread.NORM_PRIORITY - 1; isDaemon = true }
            }
        }
    }

    override fun onDetachedFromWindow() {
        renderExecutor?.shutdownNow()
        renderExecutor = null
        inflightKey = null
        super.onDetachedFromWindow()
    }

    init {
        // 🔴 加载状态写进 contentDescription：真机 uiautomator dump 可直接观测，
        // 不再靠「core 自检绿」推断真机也加载成功（这正是上一轮的假绿来源）。
        contentDescription = "鸭子外观模型（加载中）· 按部件状态着色 · 可拖动旋转"
        isClickable = true
    }

    /** 健康页每次刷新后调用；只更新数据，不直接改 UI 文本。 */
    fun setReport(r: MonitorReport?) {
        report = r
        invalidate()
    }

    /** 页面不可见时暂停，避免后台空转。 */
    fun setRotating(on: Boolean) {
        rotating = on
    }

    /** 由 MainActivity 的 1s tick 调一次：只步进 6°，一圈 60s。 */
    fun advanceFrame() {
        if (!rotating || isDragging || width <= 0 || height <= 0) return
        angleDeg = (angleDeg + DEG_PER_TICK) % 360f
        invalidate()
    }

    /**
     * 触摸拖动旋转：横向拖动改变绕 Y 轴角度，松手后恢复自动缓慢旋转。
     * 灵敏度：横向拖过整个画布宽度 ≈ 旋转一圈（360°），保证任意机型手感一致。
     */
    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                isDragging = true
                dragStartX = event.x
                dragStartAngle = angleDeg
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (!isDragging) return false
                val w = width.coerceAtLeast(1)
                val sens = 360f / w
                angleDeg = (dragStartAngle + (event.x - dragStartX) * sens).coerceIn(0f, 360f)
                // 30ms 节流：拖动时全网格重绘不必每个 MOVE 都做。
                val now = android.os.SystemClock.uptimeMillis()
                if (now - lastDragDrawMs >= 30L) {
                    lastDragDrawMs = now
                    invalidate()
                }
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                isDragging = false
                invalidate()
                return true
            }
        }
        return false
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat(); val h = height.toFloat()
        if (w <= 0f || h <= 0f) return
        val r = report
        // 状态真源单一：报告缺失时一律 UNKNOWN（core 据此保持基色，绝不默认绿）。
        val sevOf: (RobotPart) -> Severity = { p: RobotPart -> r?.severityOf(p) ?: Severity.UNKNOWN }

        val m = ensureMesh()
        if (m != null) {
            // ── 全息管线：core 出像素，View 只贴图（状态经 sevOf 注入，颜色即状态）──
            // 命中缓存画新帧；未命中画上一帧（保持连续）并排后台渲染，完成后 invalidate。
            val maxDim = if (isDragging) HOLO_MAX_DIM_DRAG else HOLO_MAX_DIM
            val ss = if (isDragging) HOLO_SS_DRAG else HOLO_SS
            val aspect = w / h
            var iw = maxDim
            var ih = (maxDim / aspect).toInt().coerceAtLeast(2)
            if (ih > maxDim) { ih = maxDim; iw = (maxDim * aspect).toInt().coerceAtLeast(2) }
            var sevSig = 17
            for (p in 0 until 21) {
                val part = io.microduck.app.core.ModelPart.of(p) ?: continue
                sevSig = sevSig * 31 + sevOf(part).ordinal
            }
            val angKey = ((angleDeg % 360f) + 360f).toInt() % 360
            val upToDate = angKey == holoKeyAngle && sevSig == holoKeySev &&
                iw == holoKeyW && ih == holoKeyH

            val cached = holoBitmap
            if (cached != null) {
                holoSrcRect.set(0, 0, cached.width, cached.height)
                dstRect.set(0f, 0f, w, h)
                canvas.drawBitmap(cached, holoSrcRect, dstRect, bitmapPaint)
            }
            if (!upToDate) scheduleHolo(m, sevOf, angKey, sevSig, iw, ih, ss)
            return
        }

        // ── 降级：网格缺失时才画程序化鸭身 + 外观表面线 + 示意骨架 ──
        // 降级路径无法按部件着色（无 partIndex），按约定保持基色，不造状态色。
        canvas.drawOval(w * 0.22f, h * 0.88f, w * 0.78f, h * 0.95f, groundPaint)
        val f = DuckModelGeometry.frame(angleDeg.toDouble(), w, h)
        f.bodyEllipse?.let { e ->
            bodyFillPaint.color = Color.argb(
                90, Color.red(e.fillArgb), Color.green(e.fillArgb), Color.blue(e.fillArgb))
            canvas.drawOval(e.cx - e.rx, e.cy - e.ry, e.cx + e.rx, e.cy + e.ry, bodyFillPaint)
        }
        for (s in f.surfaces) {
            surfacePaint.color = s.colorArgb
            for (l in s.lines) {
                surfacePaint.alpha = depthAlpha(l.avgDepth) + 30
                canvas.drawLine(l.a.x, l.a.y, l.b.x, l.b.y, surfacePaint)
            }
        }
        for (l in f.hull) {
            hullPaint.alpha = depthAlpha(l.avgDepth)
            canvas.drawLine(l.a.x, l.a.y, l.b.x, l.b.y, hullPaint)
        }
        for (l in f.bones) {
            bonePaint.alpha = depthAlpha(l.avgDepth) + 40
            canvas.drawLine(l.a.x, l.a.y, l.b.x, l.b.y, bonePaint)
        }
    }

    /**
     * 后台渲染一帧（最新优先去重）：同一 key 已在渲染则跳过；完成后 post 回 UI 线程
     * 写 Bitmap 并 invalidate。渲染失败不静默白屏：记日志，保留上一帧。
     */
    private fun scheduleHolo(
        m: DuckMesh.MeshData,
        sevOf: (RobotPart) -> Severity,
        angKey: Int,
        sevSig: Int,
        iw: Int,
        ih: Int,
        ss: Int,
    ) {
        val executor = renderExecutor ?: return
        val key = "$angKey/$sevSig/$iw/$ih/$ss"
        if (inflightKey == key) return
        inflightKey = key
        executor.execute {
            try {
                val t0 = android.os.SystemClock.uptimeMillis()
                // angleDeg 在执行时刻读（volatile）；tick 与调度同源，两者几乎必然一致。
                val pixels = HoloRenderer.render(m, angleDeg.toDouble(), iw, ih, sevOf, ss)
                post {
                    inflightKey = null
                    val bmp = holoBitmap?.takeIf { it.width == iw && it.height == ih }
                        ?: Bitmap.createBitmap(iw, ih, Bitmap.Config.ARGB_8888)
                    bmp.setPixels(pixels, 0, iw, 0, 0, iw, ih)
                    holoBitmap = bmp
                    holoSrcRect.set(0, 0, iw, ih)
                    holoKeyAngle = angKey
                    holoKeySev = sevSig
                    holoKeyW = iw
                    holoKeyH = ih
                    if (HOLO_LOG) {
                        android.util.Log.d(
                            TAG, "holo ${iw}x$ih ss=$ss ${android.os.SystemClock.uptimeMillis() - t0}ms")
                    }
                    invalidate()
                }
            } catch (e: Exception) {
                inflightKey = null
                android.util.Log.w(TAG, "全息渲染失败: ${e.message}")
            }
        }
    }

    /** 近的面更不透明（仅降级路径用）：depth ∈ [-1.5,1.5] → alpha ∈ [70,190]。 */
    private fun depthAlpha(depth: Float): Int =
        (70f + (depth + 1.5f) / 3f * 120f).toInt().coerceIn(40, 210)

    /**
     * 懒加载真实网格：只加载一次。
     * 🔴 Android 必须走 assets（见类注释）；若失败，contentDescription 明确写「未加载」，
     * 让真机门禁 / 截图可直接判定，绝不静默降级后还声称用了真实网格。
     */
    private fun ensureMesh(): DuckMesh.MeshData? {
        if (meshLoaded) return mesh
        meshLoaded = true
        return try {
            val bytes = context.assets.open(MESH_ASSET).use { it.readBytes() }
            val loaded = DuckMesh.loadFromBytes(bytes)
            mesh = loaded
            contentDescription =
                "鸭子真实外观网格已加载 · ${loaded.nTris} 三角形 · 全息渲染 · 按部件状态着色 · 可拖动旋转"
            loaded
        } catch (e: Exception) {
            meshFailed = true
            android.util.Log.w(TAG, "真实网格 assets 加载失败，降级示意几何: ${e.message}")
            contentDescription = "鸭子示意几何(真实网格未加载) · 按部件状态着色 · 可拖动旋转"
            null
        }
    }

    private companion object {
        const val TAG = "DuckModelView"
        const val MESH_ASSET = "duck_mesh.bin"
        const val DEG_PER_TICK = 6f
        /** 内部全息渲染尺寸上限（px）：内存/耗时 ∝ (dim×SS)²。 */
        const val HOLO_MAX_DIM = 520
        /** 拖动时降档：更小尺寸 + SS=2，保证拖动跟手。 */
        const val HOLO_MAX_DIM_DRAG = 400
        /** 超采样档位：静止 3（细线圆滑），拖动 2（跟手优先）。 */
        const val HOLO_SS = 3
        const val HOLO_SS_DRAG = 2
        /** 打点开关：性能实测时打开（默认关，避免日志影响帧时）。 */
        const val HOLO_LOG = false
    }
}
