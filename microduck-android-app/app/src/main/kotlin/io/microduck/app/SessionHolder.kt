package io.microduck.app

import io.microduck.app.core.ConnectInputParser
import io.microduck.app.core.ConnectTarget
import io.microduck.app.core.Disposable
import io.microduck.app.core.HealthSnapshot
import io.microduck.app.core.Method
import io.microduck.app.core.MockTransport
import io.microduck.app.core.RobotSession
import io.microduck.app.core.RobotTransport
import io.microduck.app.core.StateSnapshot
import io.microduck.app.core.TcpTransport
import java.util.concurrent.atomic.AtomicInteger

/**
 * 控制模式 —— 一手依据 NIST UTAP 标准 3.2.19 / Sheridan 自主等级：
 *  - MANUAL = direct / manual control：「all robot motion is specified by **continuous input
 *    from a human**, with no additional motion caused by a computer」⇒ 双摇杆连续意图。
 *  - AUTO = supervisory / monitoring 视图：「robot motion may be caused by either human inputs
 *    or computer generated inputs」。本版 App 在此模式**完全不发送 motion intent**，只订阅状态。
 *
 * 🔴 边界（项目铁律 UNVERIFIED != PASS）：fanhao 契约里确有 `robot.do` / `robot.loadPolicy`
 * / `robot.policies`（见 core/Wire.kt），但**无整机、未验证策略启停**，让 App 去触发自主
 * 行走是会让实体机器人动起来的未验证动作 ⇒ 自动模式**不调用这些方法**，也不宣称
 * 「已实现自主行走」。板上是否自主运行、由哪条策略驱动，由固件决定，App 只如实显示
 * `robot.state` 里上报的 policy 字段。
 */
enum class ControlMode { MANUAL, AUTO }

/**
 * 跨 Activity 共享的会话与遥测（object 单例，进程内）。
 *
 * 为什么要它：拆页后 MainActivity（竖屏控制台）与 DriveActivity（横屏遥控页）是两个
 * Activity，但 `RobotSession` 的 TCP/BLE 连接、`robot.state` 订阅、断链重连状态必须只有一份。
 * 放在 Application 级单例，避免两个页面各建一条链路导致重订阅互相覆盖。
 *
 * 🔴 安全：DriveController / HeadController **不放在这里**，只由 DriveActivity 持有。
 * 离开遥控页（onStop / finish）立刻归零并停心跳 ⇒ 用户退回控制台时机器人必停
 * （Weston Robot Teleop 文档：「the robot is sent a stop the moment you release」、
 *  「Teleoperation stops the robot when the connection ... degrades」）。
 */
object SessionHolder {

    @Volatile var mode: ControlMode = ControlMode.MANUAL
    @Volatile var session: RobotSession? = null
    @Volatile var kind: String = "MOCK"
    @Volatile var note: String = ""
    @Volatile var sinkLabel: String = "-"
    @Volatile var stateSub: Disposable? = null
    @Volatile var lastState: StateSnapshot? = null
    @Volatile var stateFrameCount: Int = 0
    @Volatile var stateWindowFrames: Int = 0
    @Volatile var stateWindowStartMs: Long = System.currentTimeMillis()
    @Volatile var stateHz: Double = 0.0
    @Volatile var batteryText: String = "— 未读到"
    @Volatile var lastInput: String = "— 无输入"
    @Volatile var heartbeatRunning: Boolean = false

    /**
     * 连接输入的**显式错误**（A2）。空串 = 无错误；非空 = 用户填的地址不合法，UI 必须显示
     * 而不是悄悄改用默认值。旧实现 `toIntOrNull() ?: 7788` 会把 99999/abc/空端口全部吞掉。
     */
    @Volatile var connectError: String = ""

    /**
     * 链路状态横幅（A3）。BoBo `mobile-app.md` §4：「Every screen tolerates the link dropping
     * underneath it and coming back」，§2 又说后台掉线是 *expected, not a fault* ⇒ 文案写
     * 「正在重连」而不是「错误」。空串 = 正常，不显示横幅。
     */
    @Volatile var linkStatus: String = ""
    /** 0=无 / 1=警告(重连中) / 2=错误(失败)。UI 据此选背景色。 */
    @Volatile var linkLevel: Int = 0
    private var eventSub: Disposable? = null

    @Volatile private var lastSentSnapshot: Int = 0
    @Volatile private var lastSampleMs: Long = 0L
    val sentCount = AtomicInteger(0)
    val headSentCount = AtomicInteger(0)
    /** App 本地刷新计数：只证明 UI 在动，绝不冒充实机帧（主页遥测组标题已写非实机数据）。 */
    val uiTickCount = AtomicInteger(0)

    // 设置页写入、遥控页读取（两边不各自持有一份配置，避免「改了没生效」）。
    @Volatile var channelIndex: Int = 0
    @Volatile var headRadIndex: Int = 0
    @Volatile var invertY: Boolean = false
    @Volatile var maxVx: Double = 0.35
    @Volatile var maxVyaw: Double = 1.20
    /** 死区默认 0.08，与 core/DriveController、HeadController 默认一致；由 SettingsStore 持久化。 */
    @Volatile var driveDeadzone: Double = 0.08
    @Volatile var headDeadzone: Double = 0.08
    @Volatile var autoRefreshHealth: Boolean = false

    fun sessionState(): String = session?.state?.toString() ?: "NONE"

    /**
     * 后台解析 + 建链；[onDone] 在后台线程回调，调用方需自行切主线程。
     *
     * 🔴 解析失败**不拆现有会话**（BoBo `mobile-app.md` §2：错误要带可恢复的下一步，
     * 「try again does not restart the flow」）。只把错误写进 [connectError] 让 UI 显示。
     */
    fun connect(raw: String, onDone: (Boolean) -> Unit) {
        val parsed = ConnectInputParser.parse(raw)
        if (parsed.isFailure) {
            connectError = parsed.exceptionOrNull()?.message ?: "连接地址无效"
            note = "地址无效"
            onDone(false)
            return
        }
        val p = parsed.getOrNull()!!
        connectError = ""
        note = p.note
        val transport: RobotTransport = when (p.target) {
            is ConnectTarget.Mock -> MockTransport()
            is ConnectTarget.Tcp -> TcpTransport()
            // BLE 走 connectWith(AndroidBleGattLink → BleTransport)，见 BleConnectPanel。
            // 这里只可能由 BLE 扫描入口传入真正的 transport，不应从地址栏走到这个分支。
            is ConnectTarget.Ble -> {
                connectError = "请使用设置页的「BLE 连接」入口选择设备"
                onDone(false); return
            }
            is ConnectTarget.WebRtc -> {
                connectError = "WebRTC 通道尚未接入（P2）"
                onDone(false); return
            }
        }
        connectWith(transport, p.target, onDone)
    }

    /** 通用建链入口：TCP / Mock / BLE 共用同一套会话、订阅与事件监听，避免各写一份漂移。 */
    fun connectWith(transport: RobotTransport, target: ConnectTarget, onDone: (Boolean) -> Unit) {
        Thread {
            // 顺序要紧：先摘旧监听，再 close（close 会 emit DISCONNECTED，不该污染新会话）。
            eventSub?.dispose(); eventSub = null
            stateSub?.dispose(); stateSub = null
            session?.close()
            linkStatus = ""; linkLevel = 0

            val s = RobotSession(transport)
            watchEvents(s)
            val ok = s.connect(target)
            session = s
            kind = transport.kind.name
            note = when {
                ok -> "已连接 $kind"
                transport.kind.name == "BLE" -> "BLE 连接失败（真 GATT 尚未上板验证）"
                else -> "连接失败（检查 relay/地址）"
            }
            stateFrameCount = 0
            stateWindowFrames = 0
            stateWindowStartMs = System.currentTimeMillis()
            stateHz = 0.0
            lastState = null
            batteryText = "— 未读到"
            sinkLabel = "-"
            // subscribe() 内部同步发请求（真 TCP 是阻塞 I/O），必须在后台线程。
            Thread { subscribe(s, kind) }.start()
            onDone(ok)
        }.start()
    }

    /**
     * 把会话层状态机映射成 UI 可见的横幅。core 的 `onEvent` 本来就有 StateChanged /
     * ReconnectFailed / AuthFailed，只是此前 App 没订阅 —— 断链时摇杆还在发帧、用户却看不到
     * 「已断链 / 重连中 / 驾驶已停」，这是安全信息而不是锦上添花。
     */
    private fun watchEvents(s: RobotSession) {
        eventSub = s.onEvent { e ->
            when (e) {
                is RobotSession.Event.StateChanged -> when (e.to) {
                    RobotSession.State.READY -> { linkStatus = ""; linkLevel = 0 }
                    RobotSession.State.RECONNECTING -> {
                        linkStatus = "⚠ 链路已断 · 正在重连（驾驶帧已停）"; linkLevel = 1
                    }
                    RobotSession.State.FAILED -> {
                        linkStatus = "⚠ 连接失败 · 请检查地址/权限后重新连接"; linkLevel = 2
                    }
                    RobotSession.State.DISCONNECTED -> { linkStatus = ""; linkLevel = 0 }
                    else -> { /* HELLO / AUTH 是瞬时中间态，不刷横幅 */ }
                }
                is RobotSession.Event.ReconnectFailed -> {
                    linkStatus = "⚠ 重连 ${e.attempts} 次仍失败 · 请检查链路后重新连接"; linkLevel = 2
                }
                is RobotSession.Event.AuthFailed -> {
                    linkStatus = "⚠ PIN 认证失败 · 剩余 ${e.attemptsRemaining} 次"; linkLevel = 2
                }
                else -> { /* CapabilityUnsupported / PermissionDenied / Notification 不占横幅 */ }
            }
        }
    }

    private fun subscribe(s: RobotSession, k: String) {
        stateSub = s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 5),
            streamMethod = Method.ROBOT_STATE) { o ->
            lastState = StateSnapshot.from(o)
            stateFrameCount++
            stateWindowFrames++
            kind = k
        }
    }

    /** robot.health 只读；[onDone] 在后台线程回调。 */
    fun refreshHealth(onDone: (String) -> Unit) {
        Thread {
            val r = session?.call(Method.ROBOT_HEALTH)
            val snap = r?.getOrNull()?.let { HealthSnapshot.from(it) }
            val text = snap?.summary()
                ?: "未连接或调用失败：${r?.exceptionOrNull()?.message ?: "no session"}"
            batteryText = snap?.let { h ->
                h.volts?.let { v -> "%.1f V · %s%%".format(v,
                    h.percent?.let { "%.0f".format(it) } ?: "—") } ?: "— 未读到"
            } ?: "— 未读到"
            onDone(text)
        }.start()
    }

    /**
     * 由**两个** Activity 的 Handler 每秒各调一次（MainActivity 的 tick 在 onStop 不停，
     * DriveActivity 前台也在跑）。
     *
     * 🔴 真机实测抓到的 bug：原来每次调用都写 `lastSentSnapshot`，两个 Handler 交替踩
     * ⇒ 后一个算出 `nowSent == lastSentSnapshot` ⇒ `heartbeatRunning` 被误判为 false，
     * 界面在心跳明明持续发帧时闪「已停」。修法：**状态判定按时间窗去重**，
     * 同一 ~900ms 窗口内只有第一次调用的采样生效；刷新计数则每次都加（语义是本地采样次数）。
     */
    fun tick() {
        val now = System.currentTimeMillis()
        uiTickCount.incrementAndGet()      // 本地活跃度，永远不依赖谁先调
        if (now - lastSampleMs < 900) return
        lastSampleMs = now
        val elapsed = now - stateWindowStartMs
        if (elapsed >= 900) {
            stateHz = stateWindowFrames * 1000.0 / elapsed
            stateWindowFrames = 0
            stateWindowStartMs = now
        }
        val nowSent = sentCount.get()
        heartbeatRunning = mode == ControlMode.MANUAL && nowSent > lastSentSnapshot
        lastSentSnapshot = nowSent
    }

    fun markInput(s: String) { lastInput = s }

    /**
     * 模式切换：自动模式绝不允许残留心跳帧。
     *
     * 🔴 不能叫 setMode(...)：`@Volatile var mode` 会自动生成 JVM setter
     * `setMode(Lio/microduck/app/ControlMode;)V`，与同名手写函数产生
     * "Platform declaration clash"。改名 selectMode 规避 JVM 签名冲突。
     */
    fun selectMode(m: ControlMode) {
        mode = m
        if (m == ControlMode.AUTO) heartbeatRunning = false
    }
}
