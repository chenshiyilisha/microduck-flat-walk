package io.microduck.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

/**
 * 取景框占位 —— 由 MainActivity（如需预览）与 DriveActivity 共用。
 *
 * 🔴 视频通道未接入（P2 待接 WebRTC / media.frame，一手 fanhao `duck-ipc-proto/src/lib.rs:560`
 * 把 video 归 WebRTC drive 通道；`docs/design/mobile-app.md:29`）。所以这里**只居中显示一行
 * 提示文字，绝不画假取景框 / 网格 / 角标**——FPV/无人机 HUD 的第一铁律是 "keep the center
 * frame clean" 且 "feed is king"：没有真实画面时，画一个带边框的占位框反而是多余的视觉噪音，
 * 还会误导用户以为这里有画面。占位语义由 contentDescription 保留（门禁据此断言「摄像头取景框占位」）。
 */
internal class PreviewPlaceholderView(ctx: Context) : View(ctx) {
    private val den = ctx.resources.displayMetrics.density
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; textSize = 13f * den; color = Color.argb(150, 0xEA, 0xF4, 0xFF)
    }
    private val subPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; textSize = 10f * den; color = Color.argb(120, 0x8F, 0xA9, 0xC4)
    }
    init { contentDescription = "摄像头取景框占位：视频通道未接入" }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cx = width / 2f; val cy = height / 2f
        canvas.drawText("摄像头画面 · 未接入", cx, cy - 4f * den, textPaint)
        canvas.drawText("占位区域，非实时视频（P2 待接 WebRTC / media.frame）",
            cx, cy + 16f * den, subPaint)
    }
}
