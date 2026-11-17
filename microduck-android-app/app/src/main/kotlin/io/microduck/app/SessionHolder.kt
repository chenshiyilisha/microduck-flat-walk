package io.microduck.app

import io.microduck.app.core.BleForegroundPolicy
import io.microduck.app.core.ConnectTarget
import io.microduck.app.core.HardwareMonitor
import io.microduck.app.core.HealthSnapshot
import io.microduck.app.core.LinkState
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.MonitorSource
import io.microduck.app.core.RobotRepository
import io.microduck.app.core.RobotSession
import io.microduck.app.core.RobotTransport
import io.microduck.app.core.StateSnapshot
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

    /**
     * 会话/状态/健康/监控的单一真源（阶段 2 桥接）。由 [MicroDuckApp] 在 Application 启动时注入。
     * 会话方法（connect/connectWith/refreshHealth/refreshSessionInfo）委托给它，
     * 避免 [RobotRepository] 与 [SessionHolder] 各建一条会话导致双真源。
     * 驱动参数与本地遥测计数仍留在本对象（时间驱动，阶段 5 再迁移）。
     */
    @Volatile var robotRepository: RobotRepository? = null

    @Volatile var mode: ControlMode = ControlMode.MANUAL
    /** 会话实例 —— 委托给 [RobotRepository]（阶段 2：RobotRepository 成为会话单一真源）。 */
    val session: RobotSession? get() = robotRepository?.session()
    @Volatile var kind: String = "MOCK"
    @Volatile var note: String = ""
    @Volatile var sinkLabel: String = "-"
    @Volatile var lastState: StateSnapshot? = null
    @Volatile var stateFrameCount: Int = 0
    @Volatile var stateWindowFrames: Int = 0
    @Volatile var stateWindowStartMs: Long = System.currentTimeMillis()
    @Volatile var stateHz: Double = 0.0
    /** 最后一帧状态到达的墙钟时间 —— 供 UI 判断「冻结节是否仍在显示」(Falcon/TechnoLynx:
     *  最危险的是看起来仍实时的陈旧值)。无帧时恒 0。 */
    @Volatile var lastStateMs: Long = 0
    @Volatile var batteryText: String = "— 未读到"
    @Volatile var lastInput: String = "— 无输入"
    @Volatile var heartbeatRunning: Boolean = false

    /**
     * 连接输入的**显式错误**（A2）。空串 = 无错误；非空 = 用户填的地址不合法，UI 必须显示
     * 而不是悄悄改用默认值。旧实现 `toIntOrNull() ?: 7788` 会把 99999/abc/空端口全部吞掉。
     */
    @Volatile var connectError: String = ""

    /**
     * 链路状态横幅（A3）。**Pollen 原厂** `docs/design/mobile-app.md` §4（经 fanhao / BoBo
     * 副本核对，原厂当前版同文）：「Every screen tolerates the link dropping underneath it
     * and coming back」，§2 又说后台掉线是 *expected, not a fault* ⇒ 文案写「正在重连」
     * 而不是「错误」。空串 = 正常，不显示横幅。
     */
    @Volatile var linkStatus: String = ""
    /** 0=无 / 1=警告(重连中) / 2=错误(失败)。UI 据此选背景色。 */
    @Volatile var linkLevel: Int = 0

    /**
     * A4 控制者归属 / 会话活性。**null = 未知**（固件未提供 / 方法不支持 / 未查询），
     * 绝不默认成 false —— 项目铁律 `UNVERIFIED != PASS`，也符合 Wandelbots NOVA 合规文档
     * 「It must always be made clear by the UI which device is currently controlling the
     * robot」(DIN EN ISO 10218-1)：不知道就写不知道。
     * 一手：`duck-ipc-proto/src/lib.rs:589` `ROBOT_SESSION_ACTIVE = "robot.remoteSessionActive"`。
     */
    @Volatile var remoteSessionActive: Boolean? = null
    /** model API 版本，只读展示用；「—」= 未读到。绝不拿它做硬拒（A9 维持不做）。 */
    @Volatile var modelApiText: String = "—"

    /**
     * 板端在 GATT `read RPC_UUID` 时自报的 API_VERSION（[BleTransport.peerApiVersion]）。
     *
     * 🔴 2026-11-14 真机实证：PC 侧单次 read 稳定返回 `0x25`=**37**，而本 App 声明
     * `Wire.API_VERSION=40`。上游 `duck-ble/src/gatt.rs:34-39` 明写这次 read 的用途就是
     * 让版本 skew 在写任何东西之前可观测；旧实现读完就丢，等于删掉契约告警能力。
     * 这里把它抬到 UI 层共享单例，供 AI 调试通道 `status` 命令与后续状态页展示读取。
     * **只记录、不硬拒**：`duck-ipc-proto/src/lib.rs` 原文 "A version difference is
     * logged and served"，`PROTOCOL_MISMATCH` 已退役，方法缺失靠 -32601 逐方法降级。
     * 非 BLE 通道恒 null；断链/切通道时清空，绝不沿用上一条链路的陈旧读数。
     */
    @Volatile var peerApiVersion: Int? = null

    // ── 2026-11-15 硬件监控：状态真源已全部迁到 RobotRepository.snapshot()（阶段 5 删散列字段）──
    // lastHealthOkMs / lastHealthError / linkState / lastHealthSnapshot / lastMonitorReport
    // 五个 @Volatile 字段外部零引用且与快照双真源，已删；monitorSource()/monitorReport()/
    // healthSnapshot()/stateAgeMs() 均委托快照，保留为 AI 通道与 UI 的统一只读入口。

    /** 数据来源分层：阶段 2 委托给 [RobotRepository]（没读到 health 一律 NONE，Mock 一律 MOCK_FIXTURE）。 */
    fun monitorSource(): MonitorSource = robotRepository?.monitorSource() ?: MonitorSource.NONE

    /** 每次调用都从一手读数重新派生，不缓存 verdict。阶段 2 委托给 [RobotRepository] 快照。 */
    fun monitorReport(nowMs: Long = System.currentTimeMillis()): MonitorReport =
        robotRepository?.snapshot()?.monitorReport
            ?: HardwareMonitor.evaluate(null, MonitorSource.NONE, LinkState.UNKNOWN, nowMs, 0L)

    /** 最近一次 robot.health 成功快照；阶段 2 委托给 [RobotRepository] 快照（null = 未读到）。 */
    fun healthSnapshot(): HealthSnapshot? = robotRepository?.snapshot()?.lastHealth

    /** A5：链路恢复提示的时间戳，0 = 无提示。超时由 [tick] 清掉。 */
    @Volatile var recoveredAtMs: Long = 0L

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
     * 后台解析 + 建链；[onDone] 回调连接结果。
     * 阶段 2：委托给 [RobotRepository]（会话单一真源），避免双会话。
     * 解析失败/BLE/WebRtc 的显式错误由 [RobotRepository.connect] 写入其快照，UI 经 uiState 读取。
     */
    fun connect(raw: String, onDone: (Boolean) -> Unit) {
        val repo = robotRepository ?: run { onDone(false); return }
        onDone(repo.connect(raw))
    }

    /**
     * 通用建链入口：TCP / Mock / BLE 共用同一套会话、订阅与事件监听。
     * 阶段 2：委托给 [RobotRepository]（会话单一真源），避免双会话。
     * 保留后台线程（[RobotSession.connect] 对真 TCP 是阻塞 I/O），[onDone] 在后台线程回调，
     * 调用方需自行切主线程（与原行为一致）。
     */
    fun connectWith(transport: RobotTransport, target: ConnectTarget, onDone: (Boolean) -> Unit) {
        val repo = robotRepository ?: run { onDone(false); return }
        Thread { onDone(repo.connectWith(transport, target)) }.start()
    }

    // watchEvents / subscribe 已迁移到 [RobotRepository]（阶段 2 委托，避免双会话）。
    // 链路横幅映射、状态帧订阅逻辑见 RobotRepository.watchEvents / subscribe。

    /** A4：只读查询控制者归属 / 模型 API。阶段 2：委托给 [RobotRepository]。 */
    fun refreshSessionInfo() {
        robotRepository?.refreshSessionInfo()
    }

    /** robot.health 只读；[onDone] 回调文本。阶段 2：委托给 [RobotRepository]，结果经快照流反映到 UI。 */
    fun refreshHealth(onDone: (String) -> Unit) {
        val repo = robotRepository ?: run { onDone("未连接或调用失败：no session"); return }
        repo.refreshHealth()
        val snap = repo.snapshot()
        onDone(snap.lastHealth?.summary()
            ?: "未连接或调用失败：${snap.lastHealthError ?: "no session"}")
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
        // A5：恢复提示到期即清，不能永久占着横幅。放在采样去重之前，
        // 否则两 Activity 交替调用时第二次会 return、提示可能清不掉。
        if (recoveredAtMs > 0 && now - recoveredAtMs > BleForegroundPolicy.RECOVERY_NOTICE_MS) {
            recoveredAtMs = 0
            if (linkLevel == 0) linkStatus = ""
        }
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
     * 状态帧年龄(ms) —— 阶段 2 委托给 [RobotRepository] 快照。
     * 链路看似正常但很久没新帧时返回 >0，UI 据此打「状态停滞」告警。无帧 / 未订阅返回 -1。
     */
    fun stateAgeMs(): Long {
        val snap = robotRepository?.snapshot() ?: return -1
        return if (snap.stateFrameCount == 0 || snap.lastStateMs == 0L) -1
        else System.currentTimeMillis() - snap.lastStateMs
    }

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
