package io.microduck.app.core

/**
 * 摇杆手势状态机 —— 纯 JVM，零 Android 依赖。
 *
 * 为什么抽这一层：Android 自定义 View 无法在本地 JVM 真跑（android.jar 全是 Stub!），
 * 而 P1 的触控逻辑此前只有「编译 + 打包」证据。按 Fowler **Passive View / Humble Object**
 * 范式，把行为移进 framework-independent 的控制器，View 只剩「把 MotionEvent 翻译成事件」
 * 与绘制 —— 于是手势逻辑可以在 `selftest.sh` 里非插桩真测（无需 Robolectric / 模拟器）。
 *
 * 🔴 一手依据 `developer.android.com/training/gestures/multi`：
 *  - `ACTION_POINTER_UP` 是**非主指针**抬起；`ACTION_UP` 是最后一指离开。
 *  - **pointer index 会随事件变化，只有 pointer ID 保证稳定**；
 *    官方明确要求用 `getPointerId()` + `findPointerIndex()` 追踪活跃指针。
 *  - `ACTION_CANCEL` 表示整个手势（含所有指针）被取消，与 UP 一样是手势终点。
 *  ⇒ 旧实现恒用 `event.x/y`（index 0）且把 POINTER_UP 当 else 忽略：
 *    多指时主指抬起会让摇杆跟错手指、甚至卡在按下态 ⇒ 机器人继续走，属安全事故。
 *
 * 输出坐标：x 右为正、y **上为正**（Android 屏幕 y 向下，取负号），
 * 与 fanhao `padd/src/udp/wire.rs:78` "up positive" 及 `MoveParams.vx` 前进为正一致。
 */
data class Pointer(val id: Int, val x: Float, val y: Float)

sealed class TouchEvent {
    /** ACTION_DOWN：第一指，官方保证在 index 0。 */
    data class Down(val pointers: List<Pointer>) : TouchEvent()

    /** ACTION_MOVE / ACTION_POINTER_DOWN：携带当前所有活跃指针。 */
    data class Move(val pointers: List<Pointer>) : TouchEvent()

    /** ACTION_POINTER_UP：upId 为抬起指的 ID，pointers 仍含该指（官方语义）。 */
    data class PointerUp(val upId: Int, val pointers: List<Pointer>) : TouchEvent()

    /** ACTION_UP：最后一指离开。 */
    data object Up : TouchEvent()

    /** ACTION_CANCEL：整个手势被父容器/系统取消。 */
    data object Cancel : TouchEvent()
}

sealed class StickOutput {
    data class Move(val x: Double, val y: Double) : StickOutput()

    /** 按下态 → 松开态：调用方**必须**立即发零帧。 */
    data object Release : StickOutput()

    /** 已是松开态，无需重复发零帧（防重复帧 / 防抖）。 */
    data object Noop : StickOutput()
}

class JoystickModel(
    var centerX: Float = 0f,
    var centerY: Float = 0f,
    var radius: Float = 1f,
    /** 真机方向最终解释权在板上 R17 映射，客户端只提供开关，不硬编码。 */
    var invertY: Boolean = false,
) {
    /** 官方要求：按 ID 追踪，不按 index。 */
    private var activeId: Int? = null

    fun isPressed(): Boolean = activeId != null

    fun handle(e: TouchEvent): StickOutput = when (e) {
        is TouchEvent.Down -> {
            val p = e.pointers.firstOrNull()
            if (p == null) release() else { activeId = p.id; compute(p) }
        }
        is TouchEvent.Move -> {
            val id = activeId
            val p = if (id == null) e.pointers.firstOrNull() else e.pointers.firstOrNull { it.id == id }
            if (p == null) release() else {
                // 防御：若活跃 ID 已不在事件里（异常 ROM），改跟当前第一指而不是卡死
                if (p.id != activeId) activeId = p.id
                compute(p)
            }
        }
        is TouchEvent.PointerUp -> {
            if (e.upId != activeId) {
                // 抬起的是非活跃指：继续跟原活跃指（其 index 可能已变）
                val p = e.pointers.firstOrNull { it.id == activeId }
                if (p == null) release() else compute(p)
            } else {
                // 🔴 活跃指被抬起：切到仍活跃的另一指；没有则归零。
                // 官方：index 会重排，必须用 ID 找，不能用 index 0。
                val next = e.pointers.firstOrNull { it.id != e.upId }
                if (next == null) release() else { activeId = next.id; compute(next) }
            }
        }
        TouchEvent.Up, TouchEvent.Cancel -> release()
    }

    /** 生命周期归零（onStop 等）：不依赖触摸事件是否到达。 */
    fun forceRelease(): StickOutput = release()

    private fun release(): StickOutput {
        val wasPressed = activeId != null
        activeId = null
        return if (wasPressed) StickOutput.Release else StickOutput.Noop
    }

    private fun compute(p: Pointer): StickOutput {
        val dx = p.x - centerX
        val dy = p.y - centerY
        val d = kotlin.math.hypot(dx.toDouble(), dy.toDouble()).toFloat()
        val k = if (d > radius && d > 0f) radius / d else 1f
        val nx = ((dx * k) / radius).toDouble().coerceIn(-1.0, 1.0)
        val ny = (-(dy * k) / radius).toDouble().coerceIn(-1.0, 1.0)
        return StickOutput.Move(nx, if (invertY) -ny else ny)
    }
}
