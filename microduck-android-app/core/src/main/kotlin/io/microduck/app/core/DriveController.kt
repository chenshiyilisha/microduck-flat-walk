package io.microduck.app.core

import java.util.Timer
import java.util.TimerTask
import kotlin.math.abs
import kotlin.math.hypot

/**
 * 驾驶控制核心 —— 纯 JVM（无 Android 依赖），摇杆 → [DriveCommand] → [DriveSink]。
 *
 * 设计依据（不是自推）：
 *  - **松手必须归零**：Android 官方 `ACTION_CANCEL` 语义（父容器拦截/系统抢焦点时
 *    最后一条事件是 CANCEL 而不是 UP，只处理 UP 会让控件卡在按下态）——
 *    developer.android.com 触控指南与社区一致结论；UI 层 `JoystickView` 把
 *    ACTION_UP / ACTION_CANCEL 都映射到 [release]。
 *  - **持续心跳**：`udp-pad.md` 「客户端静默 timeout_ms ⇒ robotd deadman 停止行走」；
 *    B 代 `robotd-params/src/lib.rs:914` deadman_ms=500、netpad timeout_ms=250。
 *    只在摇杆变化时发一次会让真机 250ms 后就断链，故心跳周期必须更短。
 *  - **deadman 兜底**：`stop()` 主动发一次零 + 停心跳；即使 App 被杀，
 *    robotd 500ms 后也会自己归零（上游测试 `main.rs:5267 "a stale twist must be zeroed"`）。
 *
 * 🔴 手感参数（maxVx/maxVyaw）**不在仿真里标定**：计划文档 §216 已写明
 *    「坐标系/单位/轴量双算法互算：驾驶手感标定(P1)必须整机测，仿真不作数」。
 *    这里的默认值只是可运行占位，等整机落地后按真机测量改。
 */
class DriveController(
    private val sink: DriveSink,
    /** 前进速度上限 m/s。占位值，等整机标定。 */
    var maxVx: Double = 0.35,
    /** 偏航角速度上限 rad/s（+ 左转）。占位值，等整机标定。 */
    var maxVyaw: Double = 1.2,
    var deadzone: Double = 0.08,
    private val heartbeatMs: Long = 100,
    /** 测试观察钩子：每次真正 send 都回调（含心跳），便于负对照断言。 */
    private val onSent: ((DriveCommand) -> Unit)? = null,
) {
    private val lock = Any()
    private var last: DriveCommand = DriveCommand(Twist.ZERO, 0.0, 0.0)
    private var heartbeat: Timer? = null
    private var running = false

    @Volatile var lastError: String? = null
        private set

    init {
        require(heartbeatMs > 0) { "heartbeatMs must be positive" }
        // 把一手数值约束写进代码门禁：心跳必须比 netpad 超时与 robotd deadman 都短。
        require(heartbeatMs < NetpadWire.TIMEOUT_MS) {
            "heartbeat ${heartbeatMs}ms must be < netpad timeout ${NetpadWire.TIMEOUT_MS}ms (udp-pad.md)"
        }
    }

    /** 当前意图（含心跳重发用的值）。 */
    fun current(): DriveCommand = synchronized(lock) { last }

    /**
     * 纯映射，可单测：圆形限幅 → 死区 → 物理量。
     *  - y 上为正 ⇒ vx 前进（Twist.vx 前进 m/s）
     *  - x 右为正 ⇒ vyaw 取负（`MoveParams` 注释 "+ 为左转"）
     *  - 单摇杆不做侧移 ⇒ vy = 0
     */
    fun map(x: Double, y: Double): DriveCommand {
        var nx = x.coerceIn(-1.0, 1.0)
        var ny = y.coerceIn(-1.0, 1.0)
        val r = hypot(nx, ny)
        if (r > 1.0) { nx /= r; ny /= r }          // 对角不超速（圆形限幅）
        if (abs(nx) < deadzone) nx = 0.0
        if (abs(ny) < deadzone) ny = 0.0
        val twist = Twist(vx = ny * maxVx, vy = 0.0, vyaw = -nx * maxVyaw)
        return DriveCommand(twist, nx, ny)
    }

    /** 摇杆移动：更新意图并**立即**发一帧（不等心跳，降低首帧延迟）。 */
    fun onAxes(x: Double, y: Double): DriveCommand {
        val cmd = synchronized(lock) { last = map(x, y); last }
        emit(cmd)
        return cmd
    }

    /**
     * 松手 / ACTION_CANCEL / 生命周期暂停：归零 + 立即发零帧 + 停心跳。
     * 🔴 必须发零帧：只把本地变量清零而不通知固件，真机会靠 deadman 再走 500ms。
     */
    fun release(): DriveCommand {
        val zero = synchronized(lock) {
            last = DriveCommand(Twist.ZERO, 0.0, 0.0)
            stopHeartbeatLocked()
            last
        }
        emit(zero)
        return zero
    }

    /** 启动周期心跳。重复调用幂等。 */
    fun startHeartbeat() {
        synchronized(lock) {
            if (heartbeat != null) return
            running = true
            heartbeat = Timer("microduck-drive-hb", true).also { t ->
                t.scheduleAtFixedRate(object : TimerTask() {
                    override fun run() {
                        val cmd = synchronized(lock) { if (running) last else return }
                        emit(cmd)
                    }
                }, heartbeatMs, heartbeatMs)
            }
        }
    }

    /** 完全停止：归零 + 停心跳 + 关闭通道。Activity.onStop / 会话断开时调用。 */
    fun stop() {
        release()
        sink.close()
    }

    private fun emit(cmd: DriveCommand) {
        val r = sink.send(cmd)
        lastError = r.exceptionOrNull()?.message
        onSent?.invoke(cmd)
    }

    private fun stopHeartbeatLocked() {
        running = false
        heartbeat?.cancel()
        heartbeat = null
    }
}
