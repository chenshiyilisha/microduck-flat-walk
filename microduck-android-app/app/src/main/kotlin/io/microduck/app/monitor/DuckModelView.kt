package io.microduck.app.monitor

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.View
import android.view.animation.LinearInterpolator
import io.microduck.app.core.DuckModelGeometry
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.RobotPart
import io.microduck.app.core.RobotParts
import io.microduck.app.core.Severity

/**
 * 缓慢旋转的鸭子仿真模型（**示意几何，不是运动学解算**）。
 *
 * ── 平台依据 ──
 * Google Android 平台文档 `android.graphics.Camera`：「A camera instance can be used to
 * compute 3D transformations and generate a matrix that can be applied … on a Canvas」；
 * 本 View 用同一路径（软件透视投影 → 2D Canvas 绘制），零 OpenGL ES / 第三方 3D 引擎、
 * 零新增 Gradle 依赖，离线可编译。几何/旋转/投影全部在 core 的
 * [DuckModelGeometry] 里纯 JVM 实现，便于自检真跑（app 层 Canvas 在 JVM 里是 stub）。
 *
 * ── 为什么不用无限 ValueAnimator ──
 * 项目真机门禁踩过「持续 UI 刷新 → uiautomator waitForIdle 死锁」的坑（修法=1500ms 节流
 * + setTextIfChanged）。这里改成**由 MainActivity 的 1s tick 驱动的有限补间**：
 * 每次 advanceFrame() 只转 6°、动画 900ms，之后主线程有 100ms 空窗，
 * 且本 View 只 onDraw、绝不 setText（不发 AccessibilityEvent）。
 * 一圈 60s，符合「缓慢旋转」。
 *
 * ── 颜色语义 ──
 * 部位圆点颜色来自 [RobotParts.severityArgb]（core 单一真源）：
 * 绿=OK / 琥珀=WARN / 红=CRITICAL / 灰=UNKNOWN。**没证据一律灰，绝不默认绿**。
 */
class DuckModelView(context: Context) : View(context) {

    private val d = resources.displayMetrics.density
    private fun dp(v: Float) = v * d

    private val hullPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(1f); color = Color.parseColor("#3E6F9B")
    }
    private val bonePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = dp(2f); color = Color.parseColor("#7FB6DE")
    }
    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = dp(2f) }
    private val groundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL; color = Color.parseColor("#1B3552")
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = dp(10f); color = Color.parseColor("#8FA9C4"); typeface = Typeface.MONOSPACE
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = dp(9f); typeface = Typeface.DEFAULT_BOLD
    }

    @Volatile private var report: MonitorReport? = null
    private var angleDeg: Float = 0f
    private var animator: ValueAnimator? = null
    private var rotating = true

    init {
        contentDescription = "鸭子仿真模型（缓慢旋转，异常部位着色）"
        isClickable = false
    }

    /** 健康页每次刷新后调用；只更新数据，不直接改 UI 文本。 */
    fun setReport(r: MonitorReport?) {
        report = r
        invalidate()
    }

    /** 页面不可见时暂停，避免后台空转。 */
    fun setRotating(on: Boolean) {
        rotating = on
        if (!on) animator?.cancel()
    }

    /** 由 MainActivity 的 1s tick 调一次：900ms 内转 6°，一圈 60s。 */
    fun advanceFrame() {
        if (!rotating || width <= 0 || height <= 0) return
        animator?.cancel()
        val from = angleDeg
        animator = ValueAnimator.ofFloat(from, from + DEG_PER_TICK).apply {
            duration = TICK_ANIM_MS
            interpolator = LinearInterpolator()
            addUpdateListener { a ->
                angleDeg = (a.animatedValue as Float) % 360f
                invalidate()
            }
            start()
        }
    }

    override fun onDetachedFromWindow() {
        animator?.cancel(); animator = null
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat(); val h = height.toFloat()
        if (w <= 0f || h <= 0f) return
        val r = report
        val sevOf = { p: RobotPart -> r?.severityOf(p) ?: Severity.UNKNOWN }

        // 地面投影（椭圆只是视觉锚，不参与任何判据）
        canvas.drawOval(w * 0.28f, h * 0.86f, w * 0.72f, h * 0.93f, groundPaint)

        val f = DuckModelGeometry.frame(angleDeg.toDouble(), w, h * 0.92f)

        // ① 壳体线框（远→近，已按 depth 排序）
        for (l in f.hull) {
            hullPaint.alpha = depthAlpha(l.avgDepth)
            canvas.drawLine(l.a.x, l.a.y, l.b.x, l.b.y, hullPaint)
        }
        // ② 骨架
        for (l in f.bones) {
            bonePaint.alpha = depthAlpha(l.avgDepth) + 40
            canvas.drawLine(l.a.x, l.a.y, l.b.x, l.b.y, bonePaint)
        }
        // ③ 部位圆点 + 异常光晕
        for ((node, p) in f.nodes) {
            val s = sevOf(node.part)
            val color = RobotParts.severityArgb(s)
            val radius = when (s) {
                Severity.CRITICAL -> dp(6.5f)
                Severity.WARN -> dp(5.5f)
                else -> dp(3.5f)
            }
            if (s == Severity.CRITICAL || s == Severity.WARN) {
                glowPaint.color = color
                glowPaint.alpha = if (s == Severity.CRITICAL) 150 else 100
                canvas.drawCircle(p.x, p.y, radius + dp(4f), glowPaint)
            }
            dotPaint.color = color
            dotPaint.alpha = if (s == Severity.UNKNOWN) 150 else 255
            canvas.drawCircle(p.x, p.y, radius, dotPaint)
        }
        // ④ 异常部位标签：只标 CRITICAL，最多 8 个，避免糊成一片（点名清单在下方文字里）
        labelPaint.color = RobotParts.severityArgb(Severity.CRITICAL)
        f.nodes.filter { (n, _) -> sevOf(n.part) == Severity.CRITICAL }
            .take(8).forEach { (node, p) ->
                canvas.drawText(node.label, p.x + dp(9f), p.y - dp(7f), labelPaint)
            }
        // ⑤ 图例 + 数据来源声明（canvas.drawText，不发 AccessibilityEvent）
        var x = dp(10f)
        val y = h - dp(9f)
        for ((s, name) in listOf(
            Severity.OK to "正常", Severity.WARN to "警告",
            Severity.CRITICAL to "严重", Severity.UNKNOWN to "未读到",
        )) {
            textPaint.color = RobotParts.severityArgb(s)
            canvas.drawText("● $name", x, y, textPaint)
            x += dp(52f)
        }
        textPaint.color = Color.parseColor("#8FA9C4")
        canvas.drawText("示意几何 · 非运动学解算", w - dp(180f), dp(14f), textPaint)
    }

    /** 近的线更亮：depth ∈ [-1.5,1.5] → alpha ∈ [70,190]。 */
    private fun depthAlpha(depth: Float): Int =
        (70f + (depth + 1.5f) / 3f * 120f).toInt().coerceIn(40, 210)

    private companion object {
        const val DEG_PER_TICK = 6f
        const val TICK_ANIM_MS = 900L
    }
}
