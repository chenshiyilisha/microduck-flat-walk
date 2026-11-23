package io.microduck.app.ui

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.drawable.Drawable

/**
 * 设置页滑块的「危险阈值」轨道底色：前 [dangerFrom] 段为安全色，之后硬切为警示色。
 *
 * 一手依据与边界：
 *  - 设计来源 = 本项目最后一版 HTML 基准稿（2026-11-20）设置页 note：
 *    「滑块右侧超过 70% 的区域底色变红，提示操作者此区间的高风险」，
 *    CSS 为 `linear-gradient(90deg, primary 0%, primary 70%, bad 70%, bad 100%)`。
 *    ⇒ 轨道 70% 处**硬切**，不是柔和渐变；[DANGER_FROM] 固定 0.7f 与基准稿一致。
 *  - ⚠️ 这不是 Material 3 官方组件：m3.material.io Slider 只定义 active / inactive track，
 *    没有「危险区」token。本项目是基于 M3 色板的自定义视觉扩展，不冒充官方规范。
 *  - 危险段只用低透明度 [dangerColor]（构造方传入带 alpha 的 md_bad），避免盖过进度 fill；
 *    真正的数值安全上限由 SettingsStore 的 clamp 负责，UI 不重造判据（判据独立于被测量）。
 *  - 只画背景轨；进度 fill 由外层 LayerDrawable 的 ClipDrawable 叠加，因此拖动时
 *    能看到进度逼近红色警戒区，与基准稿交互意图一致。
 */
class ThresholdTrackDrawable(
    private val safeColor: Int,
    private val dangerColor: Int,
    private val dangerFrom: Float = DANGER_FROM,
) : Drawable() {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

    override fun draw(canvas: Canvas) {
        val b = bounds
        val h = b.height().toFloat()
        val w = b.width()
        if (h <= 0f || w <= 0) return
        val r = h / 2f
        // 胶囊裁剪：两段共用同一外轮廓，避免各自圆角在切点处出现凹陷缝。
        val capsule = Path().apply {
            addRoundRect(
                b.left.toFloat(), b.top.toFloat(), b.right.toFloat(), b.bottom.toFloat(),
                r, r, Path.Direction.CW,
            )
        }
        val split = b.left + w * dangerFrom
        canvas.save()
        canvas.clipPath(capsule)
        paint.color = safeColor
        canvas.drawRect(b.left.toFloat(), b.top.toFloat(), split, b.bottom.toFloat(), paint)
        paint.color = dangerColor
        canvas.drawRect(split, b.top.toFloat(), b.right.toFloat(), b.bottom.toFloat(), paint)
        canvas.restore()
    }

    override fun setAlpha(alpha: Int) { paint.alpha = alpha }

    override fun setColorFilter(colorFilter: android.graphics.ColorFilter?) {
        paint.colorFilter = colorFilter
    }

    @Deprecated("Deprecated in Java", ReplaceWith("PixelFormat.TRANSLUCENT", "android.graphics.PixelFormat"))
    override fun getOpacity(): Int = PixelFormat.TRANSLUCENT

    companion object {
        /** 基准稿 70% 硬切点；单一权威，门禁绑定此值，改动必须同步基准稿。 */
        const val DANGER_FROM = 0.7f

        /** 基准稿警示区 opacity≈0.3；取 0.35 保证深色主题下可见又不盖过进度。 */
        const val DANGER_ALPHA = 0.35f

        /** 把实色 md_bad 压成低透明度警示色，避免在深色轨道上过亮。 */
        fun dangerTint(solid: Int): Int = Color.argb(
            (DANGER_ALPHA * 255).toInt(),
            Color.red(solid), Color.green(solid), Color.blue(solid),
        )
    }
}
