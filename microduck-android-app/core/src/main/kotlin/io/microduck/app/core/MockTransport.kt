package io.microduck.app.core

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/**
 * 内存 Mock 后端 —— 阶段 A 的核心工具。
 *
 * 价值：会话层的重连逻辑最容易被「看起来连上了」的假象蒙混。Mock 能**精确控制断连时机、延迟、错误码、丢帧**，
 * 让「断线后是否真的重新 hello+auth+重订阅」变成可断言的测试，而不是靠真机偶发掉线碰运气。
 * 这直接落实项目准则「验证带负对照：故意改坏必红」。不依赖 Android，纯 JVM。
 *
 * ⚠️ 线程安全：会话层的重连在**后台线程**调用 request()/connect()，而测试断言在主线程读 log/countOf，
 * simulateDisconnect() 的回调又会再启线程。所有共享可变状态必须在 [lock] 下访问、读取返回快照，
 * 否则 ConcurrentModificationException（真测试已抓到一次，这正是真测试的价值）。
 */
class MockTransport(
    private val gson: Gson = Gson(),
) : RobotTransport {

    override val kind: TransportKind = TransportKind.MOCK

    data class Fault(
        val dropNextRequest: Boolean = false,       // 丢下一条请求（返回 failure，模拟链路断）
        val disconnectAfterRequest: Boolean = false,// 回完这条就断连
        val dropAndDisconnect: Boolean = false,     // 丢请求且断连（call 发到一半掉线）
        val errorOnMethod: Pair<String, Int>? = null, // 对指定方法返回指定错误码
        val errorOnMethodMessage: String = "injected fault", // 该错误的 message（验 message 判据用）
        val delayMs: Long = 0,                      // 人为延迟
    )

    private val lock = Any()
    @Volatile private var connected = false
    @Volatile private var authenticated = false
    private val requestLog = mutableListOf<String>()      // 只记方法名，断言顺序/次数
    private val rawLog = mutableListOf<String>()           // 记完整 NDJSON 行，断言 params
    private val subscribers = mutableListOf<(String) -> Unit>()
    private val disconnectCbs = mutableListOf<() -> Unit>()
    private val faults = java.util.ArrayDeque<Fault>()
    /**
     * 活跃「逻辑订阅 lane」，断连清空、重连重订阅。用 Set：
     * 一手依据 robotd:4759「Subscribing again replaces the rate rather than opening a second stream」
     * ⇒ 重复订阅是替换速率、不叠加第二条流，lane 数不随重连增长。
     */
    private val activeLanes = mutableSetOf<String>()

    // ---- 测试用控制面 ----
    fun injectFaults(vararg f: Fault) = synchronized(lock) { faults.addAll(f) }

    /** 主动断连（模拟 btd 重启 / BLE 拆链）。回调在锁外触发，防死锁。 */
    fun simulateDisconnect() {
        val cbs = synchronized(lock) {
            if (!connected) return
            connected = false
            authenticated = false
            activeLanes.clear()
            disconnectCbs.toList()
        }
        cbs.forEach { it() }
    }

    /** 读取调用日志/计数：返回快照，避免并发改。 */
    fun log(): List<String> = synchronized(lock) { requestLog.toList() }
    fun rawLog(): List<String> = synchronized(lock) { rawLog.toList() }
    fun clearLog() = synchronized(lock) { requestLog.clear(); rawLog.clear() }
    fun laneCount(): Int = synchronized(lock) { activeLanes.size }
    fun isAuthenticated(): Boolean = authenticated
    fun countOf(method: String): Int = synchronized(lock) { requestLog.count { it == method } }
    fun pushFrame(line: String) {
        val subs = synchronized(lock) { subscribers.toList() }
        subs.forEach { it(line) }
    }

    // ---- RobotTransport 实现 ----
    override fun connect(target: ConnectTarget): Result<Unit> = synchronized(lock) {
        connected = true
        authenticated = false
        activeLanes.clear()
        Result.success(Unit)
    }

    override fun request(line: String): Result<String> {
        // 整个请求临界区加锁：读 faults、写 log、改 authenticated/activeLanes 都在这
        return synchronized(lock) {
            if (!connected) return Result.failure(IllegalStateException("MOCK_NOT_CONNECTED"))

            // 🔴 notification（无 id）：按 RobotTransport 契约写出后立即成功、不回响应。
            // 一手 B 代 robotd/src/main.rs:3483-3489：无 id 帧直接 apply_intent 后 continue，
            // 既不回响应也不产生任何请求侧状态。Mock 必须同型：否则连续意图会被当成
            // parse error，且每次 notify 都会消耗一个 fault，令后续故障注入用例整体错位。
            val head = try {
                JsonParser.parseString(line).asJsonObject
            } catch (_: Exception) { null }
            if (head != null && !head.has("id")) {
                requestLog.add(head.get("method")?.asString ?: "")
                rawLog.add(line)
                return@synchronized RequestOutcome(Result.success(""), false)
            }

            val req = parseRequest(line)
                ?: return Result.success(err(-32700, "parse error"))

            requestLog.add(req.method)
            rawLog.add(line)

            val fault = faults.pollFirst()
            if (fault != null) {
                if (fault.delayMs > 0) Thread.sleep(fault.delayMs)
                if (fault.dropNextRequest || fault.dropAndDisconnect) {
                    // 不回响应：模拟链路断。dropAndDisconnect 需要断连，但回调须在锁外触发 →
                    // 标记后跳出 synchronized 块再处理（见下方 shouldDisconnect）。
                    return@synchronized RequestOutcome(null, fault.dropAndDisconnect)
                }
                if (fault.errorOnMethod?.first == req.method) {
                    return@synchronized RequestOutcome(
                        Result.success(err(fault.errorOnMethod.second, fault.errorOnMethodMessage)),
                        fault.disconnectAfterRequest,
                    )
                }
                val resp = cannedResponseLocked(req)
                RequestOutcome(resp, fault.disconnectAfterRequest)
            } else {
                RequestOutcome(cannedResponseLocked(req), false)
            }
        }.let { outcome ->
            // 锁外触发断连回调（回调会启重连线程，持锁会死锁）
            if (outcome.disconnectAfter) simulateDisconnect()
            outcome.response
                ?: Result.failure(java.io.IOException("MOCK_DROPPED"))
        }
    }

    private data class RequestOutcome(val response: Result<String>?, val disconnectAfter: Boolean)

    /** 按方法返回真实结构的 canned 响应。调用方须持有 [lock]。 */
    private fun cannedResponseLocked(req: ParsedReq): Result<String> {
        val resp = when (req.method) {
            Method.HELLO -> ok(mapOf(
                "api_version" to Wire.API_VERSION,
                "revision" to "mock-rev",
            ))
            Method.SYSTEM_AUTHENTICATE -> {
                val pin = req.params["pin"] as? String ?: ""
                if (pin == "000000") {
                    authenticated = true
                    ok(mapOf("authenticated" to true, "attempts_remaining" to 3))
                } else {
                    ok(mapOf("authenticated" to false, "attempts_remaining" to 2))
                }
            }
            Method.ROBOT_SUBSCRIBE -> {
                activeLanes.add(req.method)   // Set：重复订阅不叠加（robotd:4759）
                ok(mapOf("accepted" to true, "walk" to "p8head_2999.onnx"))
            }
            // ToF 订阅：Mock 推一帧 8×8 深度夹具（明确非实机），供 UI 展示三态着色。
            // 一手：ft1910 lib.rs:917 TOF_STREAM，帧结构 lib.rs:4838-4865。
            // ⚠️ 真机 tof.stream 走 mediad WebRTC（btd 拒绝，route.rs:494）；Mock 夹具不是实机证据。
            Method.TOF_STREAM -> {
                activeLanes.add(req.method)
                Thread {
                    Thread.sleep(60) // 让订阅回调先挂上再推帧
                    pushFrame(gson.toJson(mapOf(
                        "jsonrpc" to "2.0",
                        "method" to Method.TOF_FRAME,
                        "params" to tofFixture(),
                    )))
                }.start()
                ok(mapOf("accepted" to true))
            }
            Method.ROBOT_HEALTH -> ok(healthFixture())
            Method.ROBOT_STATE -> ok(stateFixture())
            // 一键休息 / 恢复站立：对齐 ft1910 `IntentResult{accepted, reason}`（lib.rs:3738）。
            // robotd 对 rest/init 从不拒绝，夹具如实返回 accepted=true。
            Method.ROBOT_REST -> ok(mapOf("accepted" to true))
            Method.ROBOT_INIT -> ok(mapOf("accepted" to true))
            Method.SYSTEM_INFO -> ok(mapOf("name" to "duck-mock", "serial" to "MOCK0001"))
            Method.ROBOT_POLICIES -> ok(mapOf("policies" to listOf("walk", "p8head_2999")))
            Method.NET_STATUS -> ok(mapOf("mode" to "sta", "ssid" to "mock-net", "ipv4" to "192.168.1.42"))
            else -> ok(emptyMap<String, Any?>())
        }
        return Result.success(resp)
    }

    /**
     * 15 舵机健康报告 fixture。
     *
     * 🔴 纯新增字段，不删旧键：旧键 `voltage/percentage/servos/fallen/policy` 是早期
     * B 代 fixture，C2/C2+ 活体自检只断言 `call(...).isSuccess`，但删键可能让别的用例
     * 的 `result` 结构断言漂移，故保留。新增键贴 fanhao `HealthResult` 一手字段名
     * （`healthFixture` 见 HealthSnapshot.kt 类注释）：`battery.volts/percent/pack`、
     * `control_loop.target_hz/achieved_hz/ticks/missed`、`bus.consecutive_errors`、
     * `motors.hottest/max_c/mean_c`、`cpu_temp_c`、`healthy/degraded`。
     * ⚠️ 这些是 **Mock 演示夹具**，App 健康页必须标注「非实机读数」，不得当成真机数据。
     */
    private fun healthFixture(): Map<String, Any?> {
        val servos = (1..15).map { i ->
            mapOf("id" to i, "voltage" to 7.4 - i * 0.01, "temperature" to 30.0 + i, "load" to i * 2)
        }
        return mapOf(
            "servos" to servos,
            "battery" to mapOf(
                "voltage" to 7.4, "percentage" to 82,          // 旧键，保留兼容
                "volts" to 7.4, "percent" to 82.0, "pack" to "2S LiPo (MOCK)",
            ),
            "fallen" to false,
            "policy" to "walk",
            "healthy" to true,
            "degraded" to false,
            "control_loop" to mapOf(
                "target_hz" to 50.0, "achieved_hz" to 49.8,
                "ticks" to 4980L, "missed" to 2L, "last_tick_age_ms" to 18L,
            ),
            "bus" to mapOf("consecutive_errors" to 0, "startup_failures" to 0),
            "motors" to mapOf("hottest" to "ID-07 (MOCK)", "max_c" to 41.5, "mean_c" to 36.2),
            "cpu_temp_c" to 52.0,
        )
    }

    private fun stateFixture(): Map<String, Any?> = mapOf(
        "vx" to 0.31, "vy" to 0.0, "vyaw" to 0.0, "policy" to "walk", "tilt_deg" to 2.1,
    )

    /**
     * ToF 8×8 演示夹具（**非实机**）。造一个「正前方有物体、边缘空、个别测量失败」的场景，
     * 让三态着色（Range / NoTarget / Unusable）都能在 UI 上看到。
     * - status 5/9 + 正距离 → Range（近处物体用较小 mm）；
     * - status 255 → NoTarget（空空间）；
     * - status 4 → Unusable（测量失败，带原始码）。
     * 一手格式：ft1910 lib.rs:4838-4865；三态判据 tof/src/lib.rs:74-108。
     */
    private fun tofFixture(): Map<String, Any?> {
        val rows = TofSnapshot.ROWS; val cols = TofSnapshot.COLS
        val dist = MutableList(rows * cols) { 0 }
        val status = MutableList(rows * cols) { TofSnapshot.STATUS_NO_TARGET }
        // 正前方中央 3×3 有个约 0.6m 的物体（status 5 有效）
        for (r in 2..4) for (cc in 2..4) {
            val i = r * cols + cc
            dist[i] = 600 + (r - 2) * 45 + (cc - 2) * 30
            status[i] = 5
        }
        // 两格测量失败（status 4），展示 Unusable 告警色
        status[1 * cols + 6] = 4; dist[1 * cols + 6] = 800
        status[6 * cols + 1] = 4; dist[6 * cols + 1] = 750
        return mapOf(
            "seq" to 1L, "at_us" to 66_000L, "t_ns" to 66_000_000L,
            "rows" to rows, "cols" to cols,
            "distance_mm" to dist, "status" to status,
        )
    }

    private fun ok(result: Map<String, Any?>): String {
        val o = JsonObject().apply {
            addProperty("jsonrpc", Wire.JSONRPC)
            add("result", gson.toJsonTree(result))
        }
        return gson.toJson(o)
    }

    private fun err(code: Int, msg: String): String {
        val o = JsonObject().apply {
            addProperty("jsonrpc", Wire.JSONRPC)
            add("error", JsonObject().apply {
                addProperty("code", code)
                addProperty("message", msg)
            })
        }
        return gson.toJson(o)
    }

    private data class ParsedReq(val id: Long, val method: String, val params: Map<String, Any?>)

    private fun parseRequest(line: String): ParsedReq? = try {
        val o = JsonParser.parseString(line).asJsonObject
        val id = o.get("id")?.asLong ?: return null
        val method = o.get("method")?.asString ?: return null
        val params = mutableMapOf<String, Any?>()
        o.getAsJsonObject("params")?.entrySet()?.forEach { (k, v) ->
            params[k] = when {
                v.isJsonPrimitive && v.asJsonPrimitive.isString -> v.asString
                v.isJsonPrimitive && v.asJsonPrimitive.isNumber -> v.asNumber
                v.isJsonPrimitive && v.asJsonPrimitive.isBoolean -> v.asBoolean
                else -> v.toString()
            }
        }
        ParsedReq(id, method, params)
    } catch (e: Exception) { null }

    override fun subscribe(onFrame: (String) -> Unit): Disposable {
        synchronized(lock) { subscribers.add(onFrame) }
        return Disposable { synchronized(lock) { subscribers.remove(onFrame) } }
    }

    override fun onDisconnected(cb: () -> Unit): Disposable {
        synchronized(lock) { disconnectCbs.add(cb) }
        return Disposable { synchronized(lock) { disconnectCbs.remove(cb) } }
    }

    override fun close() = synchronized(lock) {
        connected = false
        authenticated = false
        activeLanes.clear()
    }

    override fun isConnected(): Boolean = connected
}
