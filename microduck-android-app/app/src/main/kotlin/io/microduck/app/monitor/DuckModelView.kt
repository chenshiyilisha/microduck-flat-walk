package io.microduck.app.monitor

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.view.MotionEvent
import android.view.View
import androidx.core.content.ContextCompat
import io.microduck.app.R
import io.microduck.app.core.DuckMesh
import io.microduck.app.core.DuckModelGeometry
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.RobotPart
import io.microduck.app.core.RobotParts
import io.microduck.app.core.Severity

/**
 * 鸭子真实外观模型 —— **单一真实网格 + 15 舵机状态点叠加，非运动学解算**。
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
 * ── 颜色语义 ──
 * 15 个舵机状态圆点来自 [RobotParts.severityArgb]（core 单一真源）：
 * 绿=OK / 琥珀=WARN / 红=CRITICAL / 灰=UNKNOWN。**没证据一律灰，绝不默认绿**。
 */
class DuckModelView(context: Context) : View(context) {

    private val d = resources.displayMetrics.density
    private fun dp(v: Float) = v * d

    /** 真实网格三角形填充：颜色由 core 给出（已含不透明 alpha + Lambert 明暗）。 */
    private val triFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }
    /** 复用 Path：每帧对每个三角形 reset 重用，避免为每个面分配对象。 */
    private val triPath = Path()

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

    // ── 15 舵机状态点（叠在真实模型上）──
    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val dotHaloPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        // 🔴 不用 `alpha = 170`：AGP lint 的 Range 检测器会把 Paint.setAlpha(Int 0..255)
        // 误判成 View.setAlpha(Float 0..1)，报「Value must be ≤ 1.0」。
        // 一手依据：Google Android 注解文档明确 setAlpha(@IntRange(0,255) int)。
        // 把 alpha 直接编进 ARGB 颜色，既正确又避开误报。
        // RGB 与 md_bg 同源（去 AI 味改版 2026-11-16），仅叠半透明光晕。
        style = Paint.Style.FILL; color = Color.argb(170, 0x0D, 0x10, 0x15)
    }
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(2f)
    }
    private val groundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL; color = ContextCompat.getColor(context, R.color.md_card)
    }

    @Volatile private var report: MonitorReport? = null
    private var angleDeg: Float = 0f
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

    init {
        // 🔴 加载状态写进 contentDescription：真机 uiautomator dump 可直接观测，
        // 不再靠「core 自检绿」推断真机也加载成功（这正是上一轮的假绿来源）。
        contentDescription = "鸭子外观模型（加载中）· 15 舵机状态点 · 可拖动旋转"
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
        val sevOf = { p: RobotPart -> r?.severityOf(p) ?: Severity.UNKNOWN }

        // 地面投影（椭圆只是视觉锚，不参与任何判据）
        canvas.drawOval(w * 0.22f, h * 0.88f, w * 0.78f, h * 0.95f, groundPaint)

        // 全高都可用于模型：文字已移出 canvas，模型比旧版更大更完整。
        val f = DuckModelGeometry.frame(angleDeg.toDouble(), w, h)
        val m = ensureMesh()

        if (m != null) {
            // ── 单一真实模型：不透明填充 + Lambert 明暗 + 深度排序 ──
            val tris = DuckMesh.project(m, angleDeg.toDouble(), w, h)
            for (t in tris) {
                triFillPaint.color = t.colorArgb
                triPath.reset()
                triPath.moveTo(t.a.x, t.a.y)
                triPath.lineTo(t.b.x, t.b.y)
                triPath.lineTo(t.c.x, t.c.y)
                triPath.close()
                canvas.drawPath(triPath, triFillPaint)
            }
        } else {
            // ── 降级：网格缺失时才画程序化鸭身 + 外观表面线 + 示意骨架 ──
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

        // ── 15 舵机状态点：叠在真实模型上（同一套旋转/投影，不会错位）──
        for ((node, p) in f.nodes) {
            if (node.part.kind != RobotPart.PartKind.JOINT) continue
            val s = sevOf(node.part)
            val color = RobotParts.severityArgb(s)
            val radius = when (s) {
                Severity.CRITICAL -> dp(7f)
                Severity.WARN -> dp(6f)
                else -> dp(4.5f)
            }
            canvas.drawCircle(p.x, p.y, radius + dp(2.5f), dotHaloPaint)
            if (s == Severity.CRITICAL || s == Severity.WARN) {
                val a = if (s == Severity.CRITICAL) 170 else 120
                glowPaint.color = Color.argb(a, Color.red(color), Color.green(color), Color.blue(color))
                canvas.drawCircle(p.x, p.y, radius + dp(5f), glowPaint)
            }
            val dotA = if (s == Severity.UNKNOWN) 190 else 255
            dotPaint.color = Color.argb(dotA, Color.red(color), Color.green(color), Color.blue(color))
            canvas.drawCircle(p.x, p.y, radius, dotPaint)
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
                "鸭子真实外观网格已加载 · ${loaded.nTris} 三角形 · 15 舵机状态点 · 可拖动旋转"
            loaded
        } catch (e: Exception) {
            meshFailed = true
            android.util.Log.w(TAG, "真实网格 assets 加载失败，降级示意几何: ${e.message}")
            contentDescription = "鸭子示意几何(真实网格未加载) · 15 舵机状态点 · 可拖动旋转"
            null
        }
    }

    private companion object {
        const val TAG = "DuckModelView"
        const val MESH_ASSET = "duck_mesh.bin"
        const val DEG_PER_TICK = 6f
    }
}
