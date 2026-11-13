package io.microduck.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Rect
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import androidx.core.view.ViewCompat
import io.microduck.app.core.JoystickModel
import io.microduck.app.core.Pointer
import io.microduck.app.core.StickOutput
import io.microduck.app.core.TouchEvent
import kotlin.math.min

/**
 * 摇杆 —— **Passive View 薄壳**（零新依赖）。
 *
 * 行为逻辑全部在纯 JVM 的 [JoystickModel]（core 模块，可非插桩真测）；
 * 本类只做三件事：把 MotionEvent 翻译成 [TouchEvent]、按输出画 knob、转发回调。
 * 依据：Fowler Passive View / Humble Object —— framework 耦合层要做到几乎没有逻辑。
 *
 * 一手依据（Android 官方触控语义，详见 JoystickModel 类注释）：
 *  - `ACTION_CANCEL` 是整个手势被父容器拦截/系统抢焦点后取消，收到的是 CANCEL 而非 UP；
 *    只处理 UP 会让摇杆卡在按下态 ⇒ 机器人继续走。故 UP 与 CANCEL 走同一套归零。
 *  - pointer **index 会变、ID 才稳定** ⇒ 必须按 ID 追踪活跃指（旧版恒用 event.x/y 是真 bug）。
 *  - `onTouchEvent` 对 DOWN 返回 true，否则后续 MOVE/UP 不再分发给本 View。
 *  - Activity.onStop 还要主动 [forceRelease]，生命周期切换时触摸事件可能根本不到达。
 *
 * 输出坐标：x 右为正、y 上为正（屏幕 y 向下 ⇒ 取负号），
 * 与 fanhao `padd/src/udp/wire.rs:78` "up positive"、MoveParams.vx 前进为正一致。
 *
 * P1+ 变化：仅**绘制与可配置项**（accent / label / 半径按密度），
 * 触控状态机、回调契约、类名 `android.view.View`（真机门禁按此定位）一字未改。
 */
class JoystickView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    /** 归一化摇杆位置，x/y ∈ [-1,1]，y 上为正。 */
    var onMove: ((Double, Double) -> Unit)? = null
    /** 松手 / 手势被取消 / 生命周期停止：调用方必须发零帧。 */
    var onRelease: (() -> Unit)? = null

    /** 主色：左摇杆（方向）用青蓝，右摇杆（头部）用琥珀，一眼区分两条通道。 */
    var accent: Int = Color.rgb(0x4F, 0xD1, 0xFF)
        set(value) { field = value; rebuildPaints(); invalidate() }

    /** 画在摇杆下方的短标签（如「方向 / 头部视角」）。 */
    var label: String = ""
        set(value) { field = value; invalidate() }

    /**
     * 死区可视化比例（0~1，相对摇杆半径）。参考 simplified.media / Godot 摇杆文档：
     * 把「中心死区」画出来，用户才看得到「推到多小算没动」。由 DriveActivity 从
     * SessionHolder.driveDeadzone / headDeadzone 注入，默认 0.08。
     */
    var deadzoneFraction: Float = 0.08f
        set(value) { field = value; invalidate() }

    /**
     * 🔴 方向反转开关：`firmware/docs/robot/udp-pad.md` 明确「若推前杆却倒退，
     * 客户端加 `--invert-y`」——真机速度方向的最终解释权在板上 R17 映射，
     * **不得在客户端硬编码**。此开关只影响送出的归一化 y，不碰 core 的映射逻辑。
     */
    var invertY: Boolean
        get() = model.invertY
        set(value) { model.invertY = value }

    private val model = JoystickModel()
    private var cx = 0f
    private var cy = 0f
    private var radius = 1f
    private var knobX = 0f
    private var knobY = 0f
    private val density = resources.displayMetrics.density

    /** 触觉反馈：engaged（首触）与满幅（magnitude≥0.95）各震一次（Unity/CSDN 摇杆文档）。 */
    private val vibrator by lazy { context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator }
    private var hapticEngaged = false
    private var hapticMax = false
    /** 触控中：画一圈外发光环，给操作员明确的「已握持 / 已激活」视觉确认（触觉之外的冗余通道）。 */
    private var engaged = false
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 6f * density
    }

    private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 3f * density
    }
    private val dashPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1.5f * density
        pathEffect = DashPathEffect(floatArrayOf(4f * density, 6f * density), 0f)
    }
    private val crossPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1.5f * density
    }
    /** 死区边界：虚线小环，标示「推到多小算没动」（simplified.media / Godot 摇杆文档）。 */
    private val deadzonePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1.5f * density
        pathEffect = DashPathEffect(floatArrayOf(3f * density, 4f * density), 0f)
    }
    private val knobPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val knobGlossPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL; color = Color.argb(70, 255, 255, 255)
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; textSize = 11f * density
    }

    init { rebuildPaints() }

    private fun rebuildPaints() {
        val a = accent
        trackPaint.color = Color.argb(26, Color.red(a), Color.green(a), Color.blue(a))
        ringPaint.color = Color.argb(190, Color.red(a), Color.green(a), Color.blue(a))
        dashPaint.color = Color.argb(110, Color.red(a), Color.green(a), Color.blue(a))
        crossPaint.color = Color.argb(70, 0x8F, 0xA9, 0xC4)
        deadzonePaint.color = Color.argb(110, 0x8F, 0xA9, 0xC4)
        knobPaint.color = a
        labelPaint.color = Color.rgb(0x8F, 0xA9, 0xC4)
        // 户外/亮画面可读性：摇杆标签加投影（FPV OSD / sunlight-readability 文献：高对比+描边）。
        labelPaint.setShadowLayer(2f * density, 1f, 1f, Color.argb(180, 0, 0, 0))
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        cx = w / 2f
        cy = h / 2f
        // 三栏窄屏也能画出可用半径：以前固定减 24px，在 ~110dp 宽的列里几乎归零。
        radius = min(w, h) / 2f - 12f * density
        if (radius < 12f * density) radius = 12f * density
        model.centerX = cx
        model.centerY = cy
        model.radius = radius
        resetKnob()

        // 🔴 摇杆贴左右边缘时，横向拖动会被系统「从边缘内滑 = 返回」手势吞掉。
        // 一手：developer.android.com/guide/navigation/gesturenav
        // 「To maintain functionality of elements on the left and right edges ... opt out of
        //  the back gesture selectively ... View.setSystemGestureExclusionRects()」，
        // 且「Games must make sure to only exclude these areas when necessary」。
        // ⇒ 只排除摇杆圆形外接矩形（不整块浮层）；底部 home 手势官方明确「Apps can't opt
        //    out」，故不碰底部，改由 Activity 的 systemBars bottom padding 让开。
        // View 处于 GONE（健康页）时不在视图树中，排除区自然失效，符合「仅必要时」。
        // 🔴 2026-11-13 实测排除：曾怀疑 onSizeChanged 内调用会触发 layout 重派 → 永不 idle
        // （uiautomator dump 报 could not get idle state）。经对照实验（注释掉仍 13/8 失败）
        // 已证伪该假设；idle 真因是 DriveActivity 每秒改写 TextView 发射无障碍事件（见
        // DriveActivity.tick 节流说明）。排除区不发射无障碍事件、不触发重绘循环，故恢复。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val pad = (radius + 6f * density).toInt()
            ViewCompat.setSystemGestureExclusionRects(
                this,
                listOf(Rect((cx - pad).toInt(), (cy - pad).toInt(),
                    (cx + pad).toInt(), (cy + pad).toInt())),
            )
        }
    }

    private fun resetKnob() {
        knobX = cx
        knobY = cy
        invalidate()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val pointers = (0 until event.pointerCount).map { i ->
            Pointer(event.getPointerId(i), event.getX(i), event.getY(i))
        }
        val te: TouchEvent? = when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> TouchEvent.Down(pointers)
            MotionEvent.ACTION_MOVE, MotionEvent.ACTION_POINTER_DOWN -> TouchEvent.Move(pointers)
            MotionEvent.ACTION_POINTER_UP ->
                TouchEvent.PointerUp(event.getPointerId(event.actionIndex), pointers)
            MotionEvent.ACTION_UP -> TouchEvent.Up
            MotionEvent.ACTION_CANCEL -> TouchEvent.Cancel
            else -> null
        }
        if (te != null) when (val out = model.handle(te)) {
            is StickOutput.Move -> {
                // knob 跟真实手指；invertY 只改送出的方向，不改视觉位置
                val rawY = if (invertY) -out.y else out.y
                knobX = cx + (out.x * radius).toFloat()
                knobY = cy - (rawY * radius).toFloat()
                // 触觉：首触一次 + 满幅一次（magnitude≥0.95）
                if (!hapticEngaged) { buzz(VibrationEffect.EFFECT_TICK); hapticEngaged = true }
                val mag = kotlin.math.hypot(out.x, out.y)
                if (mag >= 0.95 && !hapticMax) { buzz(VibrationEffect.EFFECT_CLICK); hapticMax = true }
                onMove?.invoke(out.x, out.y)
                engaged = true
                invalidate()
            }
            StickOutput.Release -> {
                resetKnob()
                engaged = false
                hapticEngaged = false; hapticMax = false
                onRelease?.invoke()
            }
            StickOutput.Noop -> Unit   // 已是松开态，不重复发零帧
        }
        return true   // 消费 DOWN，才能持续收到 MOVE / UP / CANCEL
    }

    /** 生命周期归零：不依赖触摸事件是否到达；幂等，不重复发零帧。 */
    fun forceRelease() {
        if (model.forceRelease() == StickOutput.Release) {
            resetKnob()
            onRelease?.invoke()
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawCircle(cx, cy, radius, trackPaint)
        canvas.drawCircle(cx, cy, radius * 0.62f, dashPaint)
        canvas.drawCircle(cx, cy, radius, ringPaint)
        canvas.drawLine(cx - radius, cy, cx + radius, cy, crossPaint)
        canvas.drawLine(cx, cy - radius, cx, cy + radius, crossPaint)
        canvas.drawLine(cx, cy, knobX, knobY, crossPaint)
        canvas.drawCircle(knobX, knobY, radius * 0.24f, knobPaint)
        canvas.drawCircle(knobX - radius * 0.07f, knobY - radius * 0.07f,
            radius * 0.09f, knobGlossPaint)
        // 死区边界环：标示「推到多小算没动」，半径 = 摇杆半径 × 死区比例
        if (deadzoneFraction > 0f && deadzoneFraction < 1f) {
            canvas.drawCircle(cx, cy, radius * deadzoneFraction, deadzonePaint)
        }
        // 握持发光环：触控中亮起，明确「已激活」——户外/强光下比仅靠 knob 位移更易察觉。
        if (engaged) {
            glowPaint.color = Color.argb(95, Color.red(accent), Color.green(accent), Color.blue(accent))
            canvas.drawCircle(cx, cy, radius + 5f * density, glowPaint)
        }
        if (label.isNotEmpty()) {
            canvas.drawText(label, cx, cy + radius + 18f * density, labelPaint)
        }
    }

    /** 短促触觉：API29+ 用预定义效果，API26–28 退化成单次短震（minSdk=26）。 */
    private fun buzz(effectId: Int) {
        val v = vibrator ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            v.vibrate(VibrationEffect.createPredefined(effectId))
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            v.vibrate(VibrationEffect.createOneShot(12, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }
}
