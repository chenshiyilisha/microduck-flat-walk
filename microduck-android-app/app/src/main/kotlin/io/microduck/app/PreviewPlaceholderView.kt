package io.microduck.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

/**
 * 取景框占位 —— 由 MainActivity（如需预览）与 DriveActivity 共用。
 *
 * 🔴 只画框线 / 网格 / 说明文字，**绝不画假帧**。
 * 一手 fanhao `duck-ipc-proto/src/lib.rs:560`：`media.frame` 是 mediad 本地 Unix socket 上的
 * 「JSON header + 二进制帧尾」，注释明写 "Deliberately not a Call: its binary tail must never
 * enter Service/Lane routing or the WebRTC control datachannel"；
 * `docs/design/mobile-app.md:29` 把 video 归 WebRTC drive 通道（P2）。本版两者都未接入。
 */
internal class PreviewPlaceholderView(ctx: Context) : View(ctx) {
    private val den = ctx.resources.displayMetrics.density
    private val framePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2f * den; color = Color.rgb(0x8F, 0xA9, 0xC4)
    }
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1f * den; color = Color.argb(40, 0x8F, 0xA9, 0xC4)
    }
    private val cornerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 3f * den; color = Color.rgb(0xFF, 0xB0, 0x20)
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; textSize = 13f * den; color = Color.rgb(0xEA, 0xF4, 0xFF)
    }
    private val subPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; textSize = 10f * den; color = Color.rgb(0x8F, 0xA9, 0xC4)
    }
    init { contentDescription = "摄像头取景框占位：视频通道未接入" }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val l = 8f * den; val t = 4f * den
        val r = width - 8f * den; val b = height - 4f * den
        if (r <= l || b <= t) return
        canvas.drawRect(l, t, r, b, framePaint)
        for (i in 1..2) {
            val x = l + (r - l) * i / 3f
            val y = t + (b - t) * i / 3f
            canvas.drawLine(x, t, x, b, gridPaint)
            canvas.drawLine(l, y, r, y, gridPaint)
        }
        val k = 18f * den
        canvas.drawLines(floatArrayOf(
            l, t + k, l, t, l + k, t,
            r - k, t, r, t, r, t + k,
            l, b - k, l, b, l + k, b,
            r - k, b, r, b, r, b - k,
        ), cornerPaint)
        val cx = width / 2f; val cy = height / 2f
        canvas.drawText("摄像头画面 · 未接入", cx, cy - 4f * den, textPaint)
        canvas.drawText("占位区域，非实时视频（P2 待接 WebRTC / media.frame）",
            cx, cy + 16f * den, subPaint)
    }
}
