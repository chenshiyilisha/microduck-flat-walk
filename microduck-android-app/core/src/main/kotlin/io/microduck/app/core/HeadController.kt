package io.microduck.app.core

import kotlin.math.abs
import kotlin.math.hypot

/**
 * 头部视角控制核心 —— 纯 JVM（无 Android 依赖），右摇杆 → [HeadParams] → [HeadSink]。
 *
 * ## 映射的一手依据（不是自推）
 * fanhao `firmware/padd/src/main.rs:1438-1445`，`Mode::Head` 的 alpha 原型映射，注释明写
 * 「its head_pitch/head_yaw joint axes are inverted relative to stick direction —
 * **verified on hardware there**, kept verbatim here」：
 * ```
 * neck_pitch: right_y * head_rad,
 * head_pitch: -left_y * head_rad,
 * head_yaw:   -left_x * head_rad,
 * head_roll:  right_x * head_rad,
 * ```
 * 我们只用**一根**摇杆控视角，故只取其中 `head_pitch` / `head_yaw` 两路，符号逐字照抄
 * （`x` 右为正、`y` 上为正，与 padd 的 gilrs 轴、`JoystickModel` 输出一致）：
 *  - `head_pitch = -y * headRad`（上推 → 负 pitch = 抬头，因关节轴反）
 *  - `head_yaw   = -x * headRad`（右推 → 负 yaw）
 *  - `neck_pitch = 0`、`head_roll = 0`
 *
 * 为什么另外两路固定为 0：一手 `firmware/kinematics/src/head.rs:117-119`：
 * 「**Two of the four joints do the aiming — head_pitch and head_yaw** — while neck_pitch
 * is posture the caller chooses and head_roll stays level」；同文件 :310 单测断言
 * `gaze.joints[3] == 0.0`（head_roll stays level）。单摇杆视角恰好就是这两路瞄准关节。
 * 这不是"少实现两路"，而是照官方的凝视语义分工。
 *
 * ## 幅度 headRad（R17 live input limits）
 * 一手 `padd/src/input_settings.rs:18` 校验 `![0.5, 1.0, 2.5].contains(&head_rad)` 即报错，
 * :90 默认值 0.5（rad）。三档都是板上合法值；App 默认取最保守的 0.5，UI 可切换。
 * 🔴 别自造 0.8 之类中间值：那是 `deny_unknown_fields` 之外的**板级**校验，会被拒。
 *
 * ## 🔴 与 padd 的有意偏离（必须说明，不能默默忽略一手资料）
 * `padd/src/main.rs:1424-1438` 的 `Mode::Head` 在发 `RobotHead` 的**同一帧**还会发一条
 * `RobotMove(MoveParams::default())`，理由是「The body must not keep its last velocity while
 * the sticks are posing the head」。但 padd 是**互斥模式**（Drive / Head / BodyPose 三选一），
 * 而我们这版 UI 是**左方向摇杆 + 右头部摇杆同时活跃**：照抄会让右摇杆每帧把左摇杆的
 * 速度清成 0，两根摇杆互相打架。故此处**只发 head**，速度由 [DriveController] 独立拥有。
 * 代价：用户同时推两根摇杆时，身体会继续走 —— 这是双摇杆遥控的预期语义，不是漏实现。
 *
 * ## 🔴 松手必须回中，但**没有心跳**（与 DriveController 相反）
 * 一手 `robotd/src/intents.rs:255-261`：
 * 「Age of the most recent *twist*, which is what the deadman guards.
 *   **A stale head pose is harmless**; a stale velocity walks the robot into a wall.」
 * 即 head 槽**不参与 deadman 过期**，写一次就一直保持。所以：
 *  - 松手 / ACTION_CANCEL / onStop 必须**显式发一帧全零** [HeadParams.NEUTRAL] 才能回中，
 *    否则头会永远停在最后的角度（不像速度会被 500ms deadman 自动清零）；
 *  - **不需要周期心跳**：head 不会过期，重发只会白白占用 50 Hz 意图带宽。
 *  - `intents.rs:841-860` 单测另证 "a head write must not refresh the twist's deadman clock"，
 *    即 head 与 twist 是**两个独立 slot**，互不刷新 → 双摇杆各自发各自的，不会互相续命。
 * 这正是「不能把 DriveController 的心跳逻辑照抄到 head」的硬依据。
 */
class HeadController(
    private val sink: HeadSink,
    /** 摇杆满偏对应的关节角（rad）。板上合法档位 0.5 / 1.0 / 2.5，默认最保守的 0.5。 */
    var headRad: Double = DEFAULT_HEAD_RAD,
    var deadzone: Double = 0.08,
    /** 测试观察钩子：每次真正 send 都回调（含回中帧），便于负对照断言。 */
    private val onSent: ((HeadParams) -> Unit)? = null,
) {
    private val lock = Any()
    @Volatile private var last: HeadParams = HeadParams.NEUTRAL

    @Volatile var lastError: String? = null
        private set

    init {
        require(headRad in VALID_HEAD_RADS) {
            "headRad=$headRad 不是板上合法档位 $VALID_HEAD_RADS (padd/src/input_settings.rs:18)"
        }
        require(deadzone in 0.0..1.0) { "deadzone must be in [0,1]" }
    }

    /** 当前意图（松手后恒为 NEUTRAL）。 */
    fun current(): HeadParams = synchronized(lock) { last }

    /**
     * 纯映射，可单测：圆形限幅 → 死区 → 关节角。
     * 单摇杆只驱动 head_pitch / head_yaw；neck_pitch / head_roll 恒 0（见类注释）。
     */
    fun map(x: Double, y: Double): HeadParams {
        var nx = x.coerceIn(-1.0, 1.0)
        var ny = y.coerceIn(-1.0, 1.0)
        val r = hypot(nx, ny)
        if (r > 1.0) { nx /= r; ny /= r }          // 对角不超幅度（圆形限幅）
        if (abs(nx) < deadzone) nx = 0.0
        if (abs(ny) < deadzone) ny = 0.0
        return HeadParams(
            neckPitch = 0.0,
            headPitch = -ny * headRad,
            headYaw = -nx * headRad,
            headRoll = 0.0,
        )
    }

    /** 摇杆移动：更新意图并**立即**发一帧（不等任何定时，降低首帧延迟）。 */
    fun onAxes(x: Double, y: Double): HeadParams {
        val p = synchronized(lock) { last = map(x, y); last }
        emit(p)
        return p
    }

    /**
     * 松手 / ACTION_CANCEL / 生命周期暂停：**显式发全零帧回中**。
     * 🔴 head 不 deadman 过期，这一帧是回中的唯一手段，绝不能省（intents.rs:259）。
     */
    fun release(): HeadParams {
        val neutral = synchronized(lock) { last = HeadParams.NEUTRAL; last }
        emit(neutral)
        return neutral
    }

    /** 完全停止：回中 + 关通道。Activity.onStop / 会话断开时调用。 */
    fun stop() {
        release()
        sink.close()
    }

    private fun emit(p: HeadParams) {
        val r = sink.send(p)
        lastError = r.exceptionOrNull()?.message
        onSent?.invoke(p)
    }

    companion object {
        const val DEFAULT_HEAD_RAD = 0.5
        /** 板上 R17 输入限制的合法档位（padd/src/input_settings.rs:18）。 */
        val VALID_HEAD_RADS = listOf(0.5, 1.0, 2.5)
    }
}
