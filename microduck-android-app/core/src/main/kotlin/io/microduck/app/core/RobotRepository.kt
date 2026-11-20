package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * 数据层 Repository —— `RobotSession` 的**唯一持有者与状态出口**（重构阶段 1）。
 *
 * ── 为什么有它（重构规划单一权威）──
 * 见 `docs/active/microduck-安卓App-整体重构与架构重新规划-2026-11-16.md` §3/§4 阶段 1。
 * 现状 `SessionHolder`（app 层 object 单例）用 20+ 个 `@Volatile var` 散列承载会话状态，
 * 两个 Activity 各调 `tick()` 轮询后 `renderAll()`——是「UI 主动拉」而非官方指南的 UDF。
 * 本 Repository 把「会话 + 由会话派生的不可变快照」收进数据层，成为单一真源（SSOT）：
 *  UI 层只观察快照、发动作，不再各自维护一份会话状态。
 *
 * ── 机制选型：为什么是「不可变快照 + 监听器」而非 `StateFlow`/`suspend` ──
 * 规划原文写的是 `StateFlow<RobotSnapshot>` + `suspend fun`。但 **core 是纯 Kotlin/JVM、
 * 刻意零协程依赖**：`RobotTransport` 接口注释与 `tools/selftest.sh` 都明确——core 只依赖
 * gson，能用 kotlinc 2.4.0 + JDK17 **脱离 Gradle/Android 独立真编译真测**。在 core 引入
 * `StateFlow`/`suspend` 会破坏这个被自检脚本保护的硬属性，还要改 fat 目录装配。
 * ⇒ 按项目「不引入不必要依赖、保护 core 纯 JVM 属性」的准则，这里用与 [RobotSession.onEvent]
 * 同构的**监听器 + 不可变快照**承载「状态向下流」。`StateFlow` 的封装留给 Phase 2 的
 * ViewModel 层（app 模块，本就有协程）：ViewModel 收集本 Repository 的快照再暴露 `uiState`，
 * 更贴合 Android 分层指南「数据层暴露数据、ViewModel 负责响应式流」。
 * **意图与规划一致，机制按 core 约束适配**，特此说明。
 *
 * ── 快照不可变 ──
 * [Snapshot] 是 `data class`，每次状态变化**整体替换**一个新实例，监听者拿到的是冻结的
 * 快照，杜绝「读到中途被改」的竞态（项目既有真机 bug：两 Activity 交替踩共享快照）。
 *
 * ── 线程模型 ──
 * 与 [SessionHolder] 一致：网络/握手在后台线程，快照发布经 [publish] 在锁内替换、锁外回调，
 * 监听器回调可自行切线程。动作（connect/disconnect/refreshHealth）是同步入口、内部托管线程。
 */
class RobotRepository(
    /** 由 [ConnectTarget] 造传输；默认 Mock，app 层注入真实传输（BLE/TCP）。 */
    private val transportFactory: (ConnectTarget) -> RobotTransport = { MockTransport() },
) {

    /**
     * 不可变会话快照 —— 数据层对外的**唯一状态出口**。
     *
     * 字段与规划一致：kind / 连接状态 / lastState / lastHealth / 遥测计数，外加 UI 需要的
     * 链路横幅与只读会话信息。所有可选量 nullable，缺数据 ≠ 零（项目铁律，见 [StateSnapshot]
     * / [HealthSnapshot] 的「缺失 ≠ 零」注释）。
     */
    data class Snapshot(
        /** 传输类型名（MOCK/TCP/BLE/WEBRTC）；未连接为 "—"。 */
        val kind: String,
        /** [RobotSession.State] 名；无会话为 "NONE"。 */
        val sessionState: String,
        /** 是否已连接并握手完成（READY）。 */
        val connected: Boolean,
        /** 连接备注（成功=「已连接 X」，失败=带真实原因，见 [RobotSession.lastConnectError]）。 */
        val note: String,
        /** 链路横幅文案；空串 = 正常不显示。 */
        val linkStatus: String,
        /** 0=无 / 1=警告(重连中) / 2=错误(失败)。 */
        val linkLevel: Int,
        /** 传输层链路状态，只由会话事件派生，绝不从读数反推。 */
        val linkState: LinkState,
        /** 连接输入的显式错误；空串 = 无错误。 */
        val connectError: String,
        /** 最近一帧 `robot.state`；null = 未收到。 */
        val lastState: StateSnapshot?,
        /** 最近一次 `robot.health` 成功快照；null = 未读到。 */
        val lastHealth: HealthSnapshot?,
        /** 最近一次 health 成功的墙钟时间；0 = 从未成功。 */
        val lastHealthOkMs: Long,
        /** 最近一次 health 失败原因；null = 无错误。 */
        val lastHealthError: String?,
        /** 最近一帧 `tof.frame` 8×8 深度；null = 未收到（绝不填 0 假绿）。 */
        val tof: TofSnapshot?,
        /** 由一手读数派生的监控报告；null = 从未评估。 */
        val monitorReport: MonitorReport?,
        /** 收到的状态帧计数（遥测活性，非实机帧证据）。 */
        val stateFrameCount: Int,
        /** 状态帧实测速率；0 表示窗口未闭合，不是停环。 */
        val stateHz: Double,
        /** 最后一帧状态的墙钟时间；0 = 无帧。 */
        val lastStateMs: Long,
        /** 电池摘要文本；「— 未读到」= 未读到（不是 0）。 */
        val batteryText: String,
        /** 控制者归属；null = 未知（绝不默认 false）。 */
        val remoteSessionActive: Boolean?,
        /** 模型 API 版本文本；「—」= 未读到。 */
        val modelApiText: String,
        /** 板端自报 API_VERSION（仅 BLE）；null = 非 BLE 或未读。 */
        val peerApiVersion: Int?,
        /** A3/A6/A7 只读诊断（系统信息/服务/日志、策略/模型、更新状态）；空快照=未读。 */
        val diagnostics: DiagnosticsSnapshot,
        /** A2 Wi-Fi 配网状态/扫描快照；空快照=未读。 */
        val net: NetSnapshot,
        /** A2 配网写操作进行中（按钮禁用 + UI 提示，防重复提交）。 */
        val netBusy: Boolean,
        /** A2 配网最近一次写操作结果文本；null=无。含明文风险警示的展示由 UI 负责。 */
        val netResultText: String?,
        /**
         * 配网成功经 BLE 回执拿到的板子 IPv4（一次性回填事件）。
         * 只承载**固件回执的真实 ip4**，缺/失败恒 null；不猜、不填默认。
         * 序号只增不减：UI 据此判断「这是一次新的成功回填」，避免 1s tick 反复回填覆盖手工输入。
         */
        val provisionedIp: String?,
        val provisionedIpSeq: Long,
        /** 固件 OTA 状态/进度快照；空快照=未读。 */
        val firmware: FirmwareSnapshot,
    )

    private val lock = Any()
    private val listeners = mutableListOf<(Snapshot) -> Unit>()
    @Volatile private var current: Snapshot = initialSnapshot()

    /** 当前快照（只读快照，不暴露可变内部状态）。 */
    fun snapshot(): Snapshot = current

    /** 订阅快照变化；返回 [Disposable]。与 [RobotSession.onEvent] 同构。 */
    fun onSnapshot(cb: (Snapshot) -> Unit): Disposable {
        synchronized(lock) { listeners.add(cb) }
        return Disposable { synchronized(lock) { listeners.remove(cb) } }
    }

    /**
     * 由当前所有 [@Volatile] 字段**重建**一个不可变快照。
     *
     * 🔴 为什么必须每次重建：状态分散在多个 `@Volatile` 字段里（kind/note/linkStatus/…），
     * 若 `publish` 直接把上一次存的 `current` 再存回去，更新了字段也不会反映到快照——
     * 自检「快照反映 READY」抓到的正是这个：字段改了、快照还是旧的（读数 vs 实际矛盾）。
     * ⇒ 发布时**从字段重建**，保证快照与内部状态始终一致。
     */
    private fun build(): Snapshot = Snapshot(
        kind = kind,
        sessionState = session?.state?.toString() ?: "NONE",
        connected = session?.state == RobotSession.State.READY,
        note = note,
        linkStatus = linkStatus,
        linkLevel = linkLevel,
        linkState = linkState,
        connectError = connectError,
        lastState = lastState,
        lastHealth = lastHealth,
        lastHealthOkMs = lastHealthOkMs,
        lastHealthError = lastHealthError,
        tof = tof,
        monitorReport = monitorReport,
        stateFrameCount = stateFrameCount,
        stateHz = stateHz,
        lastStateMs = lastStateMs,
        batteryText = batteryText,
        remoteSessionActive = remoteSessionActive,
        modelApiText = modelApiText,
        peerApiVersion = peerApiVersion,
        diagnostics = diagnostics,
        net = net,
        netBusy = netBusy,
        netResultText = netResultText,
        provisionedIp = provisionedIp,
        provisionedIpSeq = provisionedIpSeq,
        firmware = firmware,
    )

    /** 重建快照、存储、锁外回调监听者。 */
    private fun publish() {
        val s = build()
        current = s
        val cbs = synchronized(lock) { listeners.toList() }
        cbs.forEach { it(s) }
    }

    private fun initialSnapshot() = Snapshot(
        kind = "—", sessionState = "NONE", connected = false, note = "",
        linkStatus = "", linkLevel = 0, linkState = LinkState.UNKNOWN, connectError = "",
        lastState = null, lastHealth = null, lastHealthOkMs = 0L, lastHealthError = null,
        tof = null,
        monitorReport = null, stateFrameCount = 0, stateHz = 0.0, lastStateMs = 0L,
        batteryText = "— 未读到", remoteSessionActive = null, modelApiText = "—",
        peerApiVersion = null, diagnostics = DiagnosticsSnapshot(),
        net = NetSnapshot(), netBusy = false, netResultText = null,
        provisionedIp = null, provisionedIpSeq = 0L,
        firmware = FirmwareSnapshot(),
    )

    // ── 会话与订阅（唯一持有者）──
    private var session: RobotSession? = null
    private var stateSub: Disposable? = null
    private var tofSub: Disposable? = null
    private var eventSub: Disposable? = null
    @Volatile private var kind = "—"
    @Volatile private var note = ""
    @Volatile private var linkStatus = ""
    @Volatile private var linkLevel = 0
    @Volatile private var linkState = LinkState.UNKNOWN
    @Volatile private var connectError = ""
    @Volatile private var lastState: StateSnapshot? = null
    @Volatile private var lastHealth: HealthSnapshot? = null
    @Volatile private var lastHealthOkMs = 0L
    @Volatile private var lastHealthError: String? = null
    @Volatile private var tof: TofSnapshot? = null
    @Volatile private var monitorReport: MonitorReport? = null
    @Volatile private var stateFrameCount = 0
    @Volatile private var stateWindowFrames = 0
    @Volatile private var stateWindowStartMs = System.currentTimeMillis()
    @Volatile private var stateHz = 0.0
    @Volatile private var lastStateMs = 0L
    @Volatile private var batteryText = "— 未读到"
    @Volatile private var remoteSessionActive: Boolean? = null
    @Volatile private var modelApiText = "—"
    @Volatile private var peerApiVersion: Int? = null
    @Volatile private var diagnostics: DiagnosticsSnapshot = DiagnosticsSnapshot()
    @Volatile private var net: NetSnapshot = NetSnapshot()
    @Volatile private var netBusy = false
    @Volatile private var netResultText: String? = null
    @Volatile private var provisionedIp: String? = null
    @Volatile private var provisionedIpSeq: Long = 0L
    @Volatile private var firmware: FirmwareSnapshot = FirmwareSnapshot()

    /** 由 `raw` 连接串解析并建链（Mock/TCP）；BLE/WebRTC 请用 [connectWith] 注入真实传输。 */
    fun connect(raw: String): Boolean {
        val parsed = ConnectInputParser.parse(raw)
        if (parsed.isFailure) {
            connectError = parsed.exceptionOrNull()?.message ?: "连接地址无效"
            note = "地址无效"
            publish()
            return false
        }
        val p = parsed.getOrNull()!!
        connectError = ""
        note = p.note
        val transport: RobotTransport = when (p.target) {
            is ConnectTarget.Mock -> MockTransport()
            is ConnectTarget.Tcp -> TcpTransport()
            is ConnectTarget.Ble -> {
                // BLE 需 Android 侧 GATT 链路，app 层经 connectWith 注入，不从地址栏走。
                connectError = "请使用设置页的「BLE 连接」入口选择设备"
                publish()
                return false
            }
            is ConnectTarget.WebRtc -> {
                connectError = "WebRTC 通道尚未接入（P2）"
                publish()
                return false
            }
        }
        return connectWith(transport, p.target)
    }

    /**
     * 通用建链入口：TCP / Mock / BLE 共用同一套会话、订阅与事件监听，避免各写一份漂移。
     * [transport] 由调用方注入（BLE 走 AndroidBleGattLink → BleTransport）。
     */
    fun connectWith(transport: RobotTransport, target: ConnectTarget): Boolean {
        // 先摘旧监听再 close，避免旧会话的 DISCONNECTED 事件污染新会话。
        eventSub?.dispose(); eventSub = null
        stateSub?.dispose(); stateSub = null
        tofSub?.dispose(); tofSub = null
        session?.close()
        // 换链路 = 换数据源：旧读数/旧报告/旧成功时间一律清空，绝不沿用陈旧遥测。
        linkStatus = ""; linkLevel = 0
        peerApiVersion = null
        lastHealth = null; lastHealthOkMs = 0L; lastHealthError = null
        tof = null   // 换链路 = 换数据源：旧 ToF 帧作废，绝不沿用陈旧深度
        monitorReport = null; linkState = LinkState.CONNECTING
        lastState = null; stateFrameCount = 0; stateWindowFrames = 0
        stateWindowStartMs = System.currentTimeMillis(); stateHz = 0.0; lastStateMs = 0L
        batteryText = "— 未读到"
        diagnostics = DiagnosticsSnapshot()   // 换链路 = 换数据源：旧诊断读数一律作废
        net = NetSnapshot(); netBusy = false; netResultText = null   // 配网状态同理作废
        provisionedIp = null   // 换链路作废上一次配网回填；序号保留单调，UI 不会误判为新事件
        firmware = FirmwareSnapshot()   // 固件 OTA 读数同理作废：不沿用旧链路的版本/进度

        val s = RobotSession(transport)
        watchEvents(s)
        val ok = s.connect(target)
        // 必须在 connect() 之后读：peerApiVersion 是 BleTransport.connect() 内 read 成功后才写入。
        peerApiVersion = (transport as? BleTransport)?.peerApiVersion
        session = s
        kind = transport.kind.name
        note = when {
            ok && s.helloDegradedReason != null ->
                "已连接 · hello 版本探测降级（updaterd 未启动，配网/认证链路可用）：${s.helloDegradedReason!!.take(80)}"
            ok -> "已连接 $kind"
            transport.kind == TransportKind.BLE ->
                "BLE 连接失败 · ${s.lastConnectError ?: "无原因（真 GATT 尚未上板验证）"}"
            else -> "连接失败 · ${s.lastConnectError ?: "检查 relay/地址"}"
        }
        // subscribe() 内部同步发请求（真 TCP 是阻塞 I/O），必须在后台线程。
        Thread { subscribe(s) }.start()
        if (ok) refreshSessionInfo()
        publish()
        return ok
    }

    /** 把会话层状态机映射成链路横幅 + 链路状态，只由会话事件写，绝不从读数猜。 */
    private fun watchEvents(s: RobotSession) {
        eventSub = s.onEvent { e ->
            linkState = when {
                e is RobotSession.Event.StateChanged && e.to == RobotSession.State.READY -> LinkState.CONNECTED
                e is RobotSession.Event.StateChanged && e.to == RobotSession.State.RECONNECTING -> LinkState.DOWN
                e is RobotSession.Event.StateChanged && e.to == RobotSession.State.FAILED -> LinkState.DOWN
                e is RobotSession.Event.StateChanged && e.to == RobotSession.State.DISCONNECTED -> LinkState.DOWN
                e is RobotSession.Event.ReconnectFailed || e is RobotSession.Event.AuthFailed ||
                    e is RobotSession.Event.ConnectFailed -> LinkState.DOWN
                else -> linkState
            }
            when (e) {
                is RobotSession.Event.StateChanged -> when (e.to) {
                    RobotSession.State.READY -> {
                        val wasDown = linkLevel > 0
                        linkStatus = if (wasDown)
                            "✓ 链路已恢复 · 驾驶不自动续动，需重新主动接管" else ""
                        linkLevel = 0
                        if (wasDown) refreshSessionInfo()
                    }
                    RobotSession.State.RECONNECTING -> {
                        linkStatus = "⚠ 链路已断 · 正在重连（驾驶帧已停）"; linkLevel = 1
                    }
                    RobotSession.State.FAILED -> {
                        linkStatus = "⚠ 连接失败 · 请检查地址/权限后重新连接"; linkLevel = 2
                    }
                    RobotSession.State.DISCONNECTED -> { linkStatus = ""; linkLevel = 0 }
                    else -> { /* HELLO / AUTH 瞬时中间态，不刷横幅 */ }
                }
                is RobotSession.Event.ReconnectFailed -> {
                    linkStatus = "⚠ 重连 ${e.attempts} 次仍失败 · 请检查链路后重新连接"; linkLevel = 2
                }
                is RobotSession.Event.AuthFailed -> {
                    linkStatus = "⚠ PIN 认证失败 · 剩余 ${e.attemptsRemaining} 次"; linkLevel = 2
                }
                is RobotSession.Event.ConnectFailed -> {
                    linkStatus = "⚠ ${e.stage} 失败 · ${e.reason.take(160)}"; linkLevel = 2
                }
                else -> { /* CapabilityUnsupported / PermissionDenied / Notification 不占横幅 */ }
            }
            publish()
        }
    }

    private fun subscribe(s: RobotSession) {
        stateSub = s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 5),
            streamMethod = Method.ROBOT_STATE) { o ->
            lastState = StateSnapshot.from(o)
            stateFrameCount++
            stateWindowFrames++
            lastStateMs = System.currentTimeMillis()
            publish()
        }
        // ToF 8×8 深度流。Mock 路径推夹具帧；真机路径只有 mediad WebRTC 才会真回帧
        // （btd 的 BLE/TCP 会拒 tof.stream，route.rs:494）——无帧就保持 tof=null，UI 显示「未读到」。
        // 一手订阅动作 = tof.stream，通知 method = tof.frame（lib.rs:917/934），分开传不能混。
        tofSub = s.subscribe(Method.TOF_STREAM, emptyMap(),
            streamMethod = Method.TOF_FRAME) { o ->
            TofSnapshot.from(o)?.let {
                tof = it
                publish()
            }
        }
    }

    /**
     * 时间驱动遥测采样：更新状态帧速率窗口。与 [SessionHolder.tick] 同语义——
     * 保留窗口去重，避免两 Activity 交替调用时速率被踩乱。返回是否在采样窗口内（未采样）。
     */
    fun tick(): Boolean {
        val now = System.currentTimeMillis()
        val elapsed = now - stateWindowStartMs
        if (elapsed >= 900) {
            stateHz = stateWindowFrames * 1000.0 / elapsed
            stateWindowFrames = 0
            stateWindowStartMs = now
            publish()
        }
        return elapsed < 900
    }

    /**
     * A4：只读查询控制者归属 / 模型 API（一手 lib.rs:587/589）。
     * Mock 夹具不查（不是实机）；缺字段/不支持 ⇒ null/「—」（未知，绝不默认 false）。
     */
    fun refreshSessionInfo() {
        val s = session
        if (s == null || kind == "MOCK") {
            remoteSessionActive = null; modelApiText = "—"; publish(); return
        }
        Thread {
            val o = s.call(Method.ROBOT_REMOTE_SESSION_ACTIVE)?.getOrNull()
            remoteSessionActive = o?.let { obj ->
                val key = listOf("active", "session_active", "remote_session_active", "value")
                    .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive }
                val prim = key?.let { obj.get(it).takeIf { p -> p.isJsonPrimitive }?.asJsonPrimitive }
                when {
                    prim == null -> null
                    prim.isBoolean -> prim.asBoolean
                    prim.isNumber -> prim.asInt != 0
                    else -> null
                }
            }
            val m = s.call(Method.ROBOT_MODEL_API)?.getOrNull()
            modelApiText = m?.let { obj ->
                listOf("api_version", "model_api", "version")
                    .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive }
                    ?.let { obj.get(it).asJsonPrimitive.asString } ?: "—"
            } ?: "—"
            publish()
        }.start()
    }

    /** `robot.health` 只读；成功才推进「最后一次成功时间」，失败不清空上次快照但记错误。 */
    fun refreshHealth() {
        val s = session
        if (s == null) {
            lastHealthError = "no session"
            publish()
            return
        }
        Thread {
            val r = s.call(Method.ROBOT_HEALTH)
            val snap = r?.getOrNull()?.let { HealthSnapshot.from(it) }
            if (snap != null) {
                lastHealth = snap
                lastHealthOkMs = System.currentTimeMillis()
                lastHealthError = null
            } else {
                lastHealthError = r?.exceptionOrNull()?.message ?: "no session"
            }
            batteryText = snap?.let { h ->
                h.volts?.let { v -> "%.1f V · %s%%".format(v,
                    h.percent?.let { "%.0f".format(it) } ?: "—") } ?: "— 未读到"
            } ?: "— 未读到"
            monitorReport = HardwareMonitor.evaluate(
                lastHealth, monitorSource(), linkState, System.currentTimeMillis(), lastHealthOkMs,
            )
            publish()
        }.start()
    }

    /**
     * A3/A6/A7：后台拉取全部只读诊断方法，合并进 [diagnostics] 快照。
     *
     * 🔴 与 refreshHealth 同构的三条铁律：
     *  · Mock 不查（不是实机，查了会伪造读数）；未 READY 不查。
     *  · 每个方法独立 try-catch：一个 -32601/-32602 只影响自己那个字段，不拖垮其余；
     *    失败记对应 `xxxError`，界面如实回显「不支持/失败」，绝不填 0 或默认假值。
     *  · 全部从 @Volatile 字段重建快照（[build]），不做增量 patch。
     *
     * system.logs 带 `LogsParams{unit,lines,boot}` 且 `deny_unknown_fields` ⇒ 键名精确、
     * 不可多带；unit 取固件知道的 `robotd`（lib.rs:4263 注释：服务解析 robotd/robotd.service）。
     */
    fun refreshDiagnostics() {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            // 未连接/Mock：清空为未读快照，不沿用陈旧数据。
            diagnostics = DiagnosticsSnapshot()
            publish()
            return
        }
        Thread {
            // 先各自拉取，异常收敛到 error 字段；Result 非 null，直接 getOrNull()。
            // runCatching 兜住任何意外抛出，单个方法失败不影响其余。
            val info = runCatching { s.call(Method.SYSTEM_INFO).getOrNull() }.getOrNull()
            val services = runCatching { s.call(Method.SYSTEM_SERVICES).getOrNull() }.getOrNull()
            val logs = runCatching {
                s.call(Method.SYSTEM_LOGS, mapOf("unit" to "robotd", "lines" to 80, "boot" to 0)).getOrNull()
            }.getOrNull()
            val policies = runCatching { s.call(Method.ROBOT_POLICIES).getOrNull() }.getOrNull()
            val model = runCatching { s.call(Method.ROBOT_MODEL).getOrNull() }.getOrNull()
            val status = runCatching { s.call(Method.UPDATE_STATUS).getOrNull() }.getOrNull()
            val installed = runCatching { s.call(Method.UPDATE_LIST_INSTALLED).getOrNull() }.getOrNull()

            val infoParsed = DiagnosticsSnapshot.fromInfo(info)
            val (logsUnit, logLines) = DiagnosticsSnapshot.parseLogs(logs)
            diagnostics = DiagnosticsSnapshot(
                robotName = infoParsed?.name,
                serial = infoParsed?.serial,
                uptimeSeconds = infoParsed?.uptimeSeconds,
                simulated = infoParsed?.simulated,
                services = DiagnosticsSnapshot.parseServices(services),
                logs = logLines,
                logsUnit = logsUnit,
                policies = DiagnosticsSnapshot.parsePolicies(policies),
                model = DiagnosticsSnapshot.parseModel(model),
                updateStatus = DiagnosticsSnapshot.parseUpdateStatus(status),
                installed = DiagnosticsSnapshot.parseInstalled(installed),
                infoError = if (infoParsed == null) "system.info 未读到/不支持" else null,
                servicesError = if (DiagnosticsSnapshot.parseServices(services).isEmpty()) "system.services 未读到/不支持" else null,
                logsError = if (logLines.isEmpty()) "system.logs 未读到/不支持" else null,
                policiesError = if (DiagnosticsSnapshot.parsePolicies(policies).isEmpty()) "robot.policies 未读到/不支持" else null,
                modelError = if (DiagnosticsSnapshot.parseModel(model) == null) "robot.model 未读到/不支持" else null,
                updateError = if (DiagnosticsSnapshot.parseUpdateStatus(status) == null) "update.status 未读到/不支持" else null,
            )
            publish()
        }.start()
    }

    // ── A2 Wi-Fi 配网（net.status / net.scan 只读 + net.connect / net.forget 写）──
    // 🔴 安全边界：Mock 不写真网络；psk 只进出站 JSON、不进日志/快照/UI 回显；
    //    明文传输风险由 UI 的 PLAINTEXT_TRANSPORT_WARNING 强制展示，本层不软化。
    //    固件端当前明文传密码（route.rs:139-155 / 原厂 §8.1 blocker），见
    //    docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md。

    /** 拉取 net.status + net.scan（只读，可重放）。Mock/未连接 → 清空为未读。 */
    fun refreshNet() {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            net = NetSnapshot()
            if (kind == "MOCK") netResultText = "演示模式：不查询真实网络"
            publish()
            return
        }
        netBusy = true; publish()
        Thread {
            val statusObj = runCatching { s.call(Method.NET_STATUS).getOrNull() }.getOrNull()
            val scanObj = runCatching { s.call(Method.NET_SCAN).getOrNull() }.getOrNull()
            val status = NetSnapshot.fromStatus(statusObj)
            val scanned = NetSnapshot.parseScan(scanObj)
            net = NetSnapshot(
                state = status?.state, ssid = status?.ssid, signal = status?.signal,
                ip4 = status?.ip4, ip6 = status?.ip6, mac = status?.mac, iface = status?.iface,
                networks = scanned,
                statusError = if (status == null) "net.status 未读到/不支持" else null,
                scanError = if (scanned.isEmpty()) "net.scan 未读到/不支持" else null,
            )
            netBusy = false
            publish()
        }.start()
    }

    /**
     * 连接 Wi-Fi（net.connect，写操作，不可自动重放）。psk 仅用于出站请求，不落任何日志/快照。
     * 回执按 outcome 解析，用户提示由 [NetProvisioning.ConnectOutcome.userMessage] 生成。
     */
    fun connectWifi(ssid: String, psk: String?) {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            netResultText = if (kind == "MOCK") "演示模式：不写真实网络配置" else "未连接，无法配网"
            publish()
            return
        }
        if (netBusy) return
        netBusy = true; publish()
        Thread {
            val params = NetProvisioning.connectParams(ssid, psk) // psk 只在这里出现，之后不保留引用
            val result = runCatching {
                s.call(Method.NET_CONNECT, params, replayable = false).getOrNull()
            }.getOrNull()
            val outcome = NetProvisioning.parseConnect(result)
            netResultText = outcome.userMessage
            // 配网成功且固件回执带真实 ip4 → 发一次性回填事件（序号自增，供 UI 填入 IP 框）。
            // 回执没带 ip4（固件允许省略）时不猜、不回填。真值判定见 NetProvisioning.backfillIp。
            NetProvisioning.backfillIp(outcome)?.let { ip ->
                provisionedIp = ip
                provisionedIpSeq += 1
            }
            netBusy = false
            publish()
            if (outcome.connected) refreshNet() // 连上后刷新状态
        }.start()
    }

    /** 忘记已存 Wi-Fi（net.forget，写操作）。removed=false 如实回显，不假装删除。 */
    fun forgetWifi(ssid: String) {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            netResultText = if (kind == "MOCK") "演示模式：不写真实网络配置" else "未连接，无法配网"
            publish()
            return
        }
        if (netBusy) return
        netBusy = true; publish()
        Thread {
            val result = runCatching {
                s.call(Method.NET_FORGET, NetProvisioning.forgetParams(ssid), replayable = false).getOrNull()
            }.getOrNull()
            val outcome = NetProvisioning.parseForget(result)
            netResultText = if (outcome.removed) "已忘记网络 $ssid" else "未找到已存网络 $ssid（或已删除）"
            netBusy = false
            publish()
            refreshNet()
        }.start()
    }

    // ── 固件 OTA（update.* JSON-RPC）──
    // 🔴 边界：手机只做「检查/触发/读进度/查询」，固件包由板子自身 WiFi/HTTPS 拉取并验签
    //    （updater-design.md）。apply/rollback/select 是写操作，replayable=false 绝不重放，
    //    UI 必须二次确认。真机升级落地/health gate/lane 分道恒 UNVERIFIED。
    // 🔴 进度不长期订阅 update.subscribe：它独占整条连接（update-over-ble.md §lane），
    //    会把 robot.state/health 通道挤掉。改用 apply 调用期间临时监听 Event.Notification
    //    ——一手明确 apply 会在自己连接上先推 update.progress 再回 reply。

    /** 只读刷新 update.status / listInstalled / log（数组 result 走 callRaw）。 */
    fun refreshFirmware() {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            if (kind == "MOCK") firmware = firmware.copy(errorText = "演示模式：不查询真实固件更新")
            publish(); return
        }
        Thread {
            val statusRaw = runCatching { s.callRaw(Method.UPDATE_STATUS).getOrNull() }.getOrNull()
            val installedRaw = runCatching { s.callRaw(Method.UPDATE_LIST_INSTALLED).getOrNull() }.getOrNull()
            val logRaw = runCatching { s.callRaw(Method.UPDATE_LOG, FirmwareUpdate.logParams(20)).getOrNull() }.getOrNull()
            val components = FirmwareUpdate.parseStatus(statusRaw)
            val installed = FirmwareUpdate.parseInstalled(installedRaw)
            val logs = FirmwareUpdate.parseLog(logRaw)
            val anyRead = components.isNotEmpty() || installed.isNotEmpty() || logs.isNotEmpty()
            firmware = firmware.copy(
                components = components, installed = installed, logs = logs,
                errorText = if (!anyRead) "update.status/listInstalled/log 未读到或不支持" else null,
            )
            publish()
        }.start()
    }

    /** 只读检查新版本：解析 check 三态，驱动「发现新版本」提示。 */
    fun checkFirmwareUpdate(component: String = FirmwareUpdate.COMPONENT_DAEMON) {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            firmware = firmware.copy(errorText = if (kind == "MOCK") "演示模式：不检查真实固件" else "未连接，无法检查更新")
            publish(); return
        }
        if (firmware.checking || firmware.busy) return
        firmware = firmware.copy(checking = true, errorText = null); publish()
        Thread {
            val r = runCatching { s.call(Method.UPDATE_CHECK, FirmwareUpdate.componentParams(component)).getOrNull() }.getOrNull()
            val state = FirmwareUpdate.parseCheck(r)
            val err = if (state is FirmwareUpdate.CheckState.Unknown)
                "update.check 未读到/未知状态${state.raw?.let { "($it)" } ?: ""}" else null
            firmware = firmware.copy(check = state, checking = false, errorText = err)
            publish()
        }.start()
    }

    /**
     * 触发安装（写操作）。进度经 apply 连接上的 update.progress 通知实时更新（不独占连接）。
     *
     * 🔴 断连语义：固件在 apply reply 后约 5s 重启 btd，属成功路径。若 call 因断连失败，
     *    但期间收到过 progress/applied，回显「已提交，板子正在安装并将重启；重连后刷新确认」，
     *    绝不假装「已安装成功」。最终落地只能由重连后的 update.status.last_attempt 证实（COLLECTED）。
     */
    fun applyFirmware(component: String, version: String?, dryRun: Boolean) {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            firmware = firmware.copy(resultText = if (kind == "MOCK") "演示模式：不写真实固件" else "未连接，无法更新",
                resultOk = false); publish(); return
        }
        if (firmware.busy) return
        firmware = firmware.copy(busy = true, progress = null, resultText = null, resultOk = null, errorText = null)
        publish()
        Thread {
            var sawProgress = false
            val notificationSub = s.onEvent { e ->
                if (e is RobotSession.Event.Notification && e.method == Method.UPDATE_PROGRESS) {
                    FirmwareUpdate.parseProgress(e.params)?.let { p ->
                        sawProgress = true
                        firmware = firmware.copy(progress = p)
                        publish()
                    }
                }
            }
            val call = runCatching {
                s.call(Method.UPDATE_APPLY, FirmwareUpdate.applyParams(component, version, dryRun), replayable = false)
            }.getOrNull()
            notificationSub.dispose()
            val result = call?.getOrNull()?.let { FirmwareUpdate.parseApply(it) }
            when {
                result is FirmwareUpdate.ApplyResult.Applied ->
                    firmware = firmware.copy(resultText = if (dryRun)
                        "预检通过（未真正安装）：候选 ${result.to ?: "?"}" else "已提交安装：${result.from ?: "?"} → ${result.to ?: "?"}。板子将重启断连；重连后点「刷新状态」确认。",
                        resultOk = true, progress = null)
                result is FirmwareUpdate.ApplyResult.RolledBack ->
                    firmware = firmware.copy(resultText = "更新失败已自动回滚：${result.reason ?: "健康检查未通过"}（回到 ${result.revertedTo ?: "上一版本"}）",
                        resultOk = false, progress = null)
                result is FirmwareUpdate.ApplyResult.DryRunPassed ->
                    firmware = firmware.copy(resultText = "预检通过：候选 ${result.candidate ?: "?"}（未真正安装）", resultOk = true, progress = null)
                sawProgress || (call?.isFailure == true) ->
                    firmware = firmware.copy(resultText = "安装已提交，板子正在下载/安装并将重启（BLE 断连属正常）。重连后点「刷新状态」读取最终结果；本机不谎报成功。",
                        resultOk = null, progress = null)
                else ->
                    firmware = firmware.copy(resultText = "update.apply 未返回可判定结果${call?.exceptionOrNull()?.message?.let { "（$it）" } ?: ""}",
                        resultOk = false, progress = null)
            }
            firmware = firmware.copy(busy = false)
            publish()
        }.start()
    }

    /** 回滚到上一 release（写操作，replayable=false）。 */
    fun rollbackFirmware(component: String) = firmwareWrite(Method.UPDATE_ROLLBACK, FirmwareUpdate.rollbackParams(component), "回滚")

    /** 指向某个已装版本（写操作，不下载）。 */
    fun selectFirmware(component: String, version: String) =
        firmwareWrite(Method.UPDATE_SELECT, FirmwareUpdate.selectParams(component, version), "切换版本")

    /** apply 之外的写操作共用逻辑（无进度流场景）。 */
    private fun firmwareWrite(method: String, params: Map<String, Any?>, label: String) {
        val s = session
        if (s == null || kind == "MOCK" || s.state != RobotSession.State.READY) {
            firmware = firmware.copy(resultText = if (kind == "MOCK") "演示模式：不写真实固件" else "未连接，无法操作",
                resultOk = false); publish(); return
        }
        if (firmware.busy) return
        firmware = firmware.copy(busy = true, resultText = null, resultOk = null, errorText = null); publish()
        Thread {
            val call = runCatching { s.call(method, params, replayable = false) }.getOrNull()
            val result = call?.getOrNull()?.let { FirmwareUpdate.parseApply(it) }
            firmware = when (result) {
                is FirmwareUpdate.ApplyResult.Applied -> firmware.copy(
                    resultText = "$label 成功：→ ${result.to ?: "?"}（需确认健康状态）", resultOk = true)
                is FirmwareUpdate.ApplyResult.RolledBack -> firmware.copy(
                    resultText = "$label 失败已回滚：${result.reason ?: "未知原因"}", resultOk = false)
                else -> firmware.copy(
                    resultText = "$label 未返回可判定结果${call?.exceptionOrNull()?.message?.let { "（$it）" } ?: ""}", resultOk = false)
            }.copy(busy = false)
            publish()
        }.start()
    }

    /** 数据来源分层：没读到 health 一律 NONE（零告警），Mock 一律 MOCK_FIXTURE，其余 REAL_HEALTH。 */
    fun monitorSource(): MonitorSource = when {        lastHealth == null -> MonitorSource.NONE
        kind == "MOCK" -> MonitorSource.MOCK_FIXTURE
        else -> MonitorSource.REAL_HEALTH
    }

    /** 主动断开并释放会话。 */
    fun disconnect() {
        eventSub?.dispose(); eventSub = null
        stateSub?.dispose(); stateSub = null
        tofSub?.dispose(); tofSub = null
        session?.close(); session = null
        kind = "—"; note = ""; linkStatus = ""; linkLevel = 0
        linkState = LinkState.UNKNOWN; connectError = ""
        lastState = null; lastHealth = null; lastHealthOkMs = 0L; lastHealthError = null
        tof = null   // 换链路 = 换数据源：旧 ToF 帧作废（负对照抓到的回灌 bug）
        monitorReport = null; stateFrameCount = 0; stateHz = 0.0; lastStateMs = 0L
        batteryText = "— 未读到"; remoteSessionActive = null; modelApiText = "—"; peerApiVersion = null
        firmware = FirmwareSnapshot()   // 断开 = 数据源消失，固件读数作废
        publish()
    }

    /** 供 UI/调试读取当前会话（只读用途；写操作请走 Repository 动作或 core 控制器）。 */
    fun session(): RobotSession? = session
}
