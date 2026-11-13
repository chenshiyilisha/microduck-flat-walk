package io.microduck.app.core

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * 会话层 —— P0 真正的核心复杂度（官方 mobile-app.md §4 明说）。
 *
 * 职责：把「一次性 transport」变成「常驻、抗掉线的会话」：
 *   1. 握手状态机 DISCONNECTED → HELLO → [AUTH，仅 BLE] → READY
 *      （v4 起 **BLE client** 必过 system.authenticate，fanhao lib.rs:44；
 *        TCP/unix/WebRTC 链路发它会被真 robotd 回 -32601，见 [AuthPolicy]）
 *   2. 断连后**去重 + 退避重连 + 重认证（若该传输需要） + 重订阅**（btd 升级重启、OAuth 等签时后台化拆链都是预期掉线）
 *   3. pending 请求按**幂等性**决定是否重放：只读可在重连后重放一次，写类不重放（防重复执行 robot.do/update.apply）
 *   4. 错误码分类（14 / -32601 / -32602 / 传输错误）→ 确定的 UI 行为
 *   5. 身份以 **serial** 为 key（地址会变，serial 不变）
 *
 * 关键设计意图（lib.rs:58）：**没有 daemon 因 API_VERSION 不同拒答** → 不硬拒版本，
 * 遇 METHOD_NOT_FOUND(-32601) 就记「该方法此固件不支持」，UI 灰化，而不是崩。
 *
 * 只依赖 RobotTransport 接口 —— 换 BLE/TCP/WebRTC/Mock 后端，会话层零改动。
 * 同步阻塞式 API（见 RobotTransport 注释）：call() 在调用线程发请求；重连在后台线程做，
 * 用 [awaitReady] 供调用方/测试等待恢复。
 */
class RobotSession(
    private val transport: RobotTransport,
    private val pin: String = "000000",
    private val gson: Gson = Gson(),
    private val maxReconnectAttempts: Int = 5,
    private val backoffBaseMs: Long = 300,
    private val backoffMaxMs: Long = 5_000,
    private val authPolicy: AuthPolicy = AuthPolicy.AUTO,
) {
    enum class State { DISCONNECTED, HELLO, AUTH, READY, RECONNECTING, FAILED }

    /**
     * PIN 认证只在 **BLE 链路**上存在，不是协议层的通用握手步骤。
     *
     * 一手依据（fanhao `hd1910-v167-trunk-imu-i2c` 全量源码，2026-11-12 核）：
     *  - `duck-ipc-proto/src/lib.rs:44` —「v4 added `system.authenticate`, which **a BLE client**
     *    must now pass before anything else is served」
     *  - `btd/src/pairing.rs:24` —「the PIN via `system.authenticate`, which is why **that call is
     *    answered by the transport** rather than [a service]」；`btd/src/route.rs:987`
     *    「system.authenticate must be answered by btd itself」
     *  - `updater/src/ipc.rs:879` —「answered by the **BLE transport**, not by updaterd」；
     *    `mediad/src/session.rs:21` / `route.rs:304` — mediad 也按名字拒绝该调用
     *  - `lib.rs:5584` —「The `None` arm is a single deliberate case — `system.authenticate`,
     *    whose check belongs to the transport」
     *  - **实测**（C2 探针，WSL2 真 `robotd --sim` unix socket）：发 `system.authenticate`
     *    得到 `{"code":-32601,"message":"system.authenticate is not served by robotd"}`。
     *
     * ⚠️ 旧版无条件发认证 ⇒ TCP relay / 真 robotd 仿真链路上握手必然失败，且 Mock 103/103
     *    全绿也照不出来（Mock 自带 canned 认证应答）。阶段 C2 真固件探针抓出。
     *
     * [AUTO] 只对 BLE 要求认证；`MockTransport` 是**有意模拟 BLE 会话**的 canned 夹具，
     * 故也走认证以保留会话层认证路径的断言覆盖（不是产品配置）。TCP / WEBRTC 一律跳过。
     * [REQUIRED]/[SKIP] 供测试显式注入，制造负对照。
     */
    enum class AuthPolicy { AUTO, REQUIRED, SKIP }

    private val requireAuth: Boolean
        get() = when (authPolicy) {
            AuthPolicy.REQUIRED -> true
            AuthPolicy.SKIP -> false
            AuthPolicy.AUTO -> transport.kind == TransportKind.BLE || transport.kind == TransportKind.MOCK
        }

    sealed class Event {
        data class StateChanged(val from: State, val to: State) : Event()
        data class CapabilityUnsupported(val method: String) : Event()   // -32601 版本 skew → UI 灰化
        data class ContractSkew(val method: String, val message: String) : Event() // -32602 我们发错字段
        data class PermissionDenied(val method: String) : Event()        // 14 BLE 白名单外 → 换传输
        data class AuthFailed(val attemptsRemaining: Int) : Event()
        data class ReconnectFailed(val attempts: Int) : Event()
        data class Notification(val method: String, val params: JsonObject) : Event()
    }

    @Volatile
    var state: State = State.DISCONNECTED
        private set
    private fun transition(to: State) {
        val from = state
        state = to
        emit(Event.StateChanged(from, to))
    }

    private val eventLock = Any()
    private val listeners = mutableListOf<(Event) -> Unit>()
    private val frameListeners = mutableListOf<(JsonObject, String?) -> Unit>()
    private val reconnectLock = Any()
    /**
     * 单一重连拥有者（in-flight guard）：保证同一时刻**只有一个** reconnectLoop 在跑。
     *
     * 🔑 为什么不能用 state==RECONNECTING 判重（阶段 C1 真 socket 测试抓到的真 bug，
     *    Mock 层 30/30 全绿也覆盖不到）：
     *   handshake() 会把 state 从 RECONNECTING 改成 HELLO→AUTH。弱网下「刚建连、
     *   握手**中途**又断」时 state 不是 RECONNECTING，旧代码就又启动一个 loop →
     *   多个 loop 并发 transport.connect() → 后建的连接拆掉前一个刚握到一半的链路 →
     *   指数级重连风暴（日志刷几百条 hello、卡在 AUTH、最终 hang）。
     *   这与 Reachy Mini 官方 App 的坑同构：stopSession 作用在「刚 connect 的同名
     *   session」，mid-handshake 调用会拆掉自己刚建的 peer state（connection-controller.ts:480）。
     *
     * 🔑 修法有一手依据：社区连接去重共识是用「连接锁 / isConnecting / in-flight 标志」
     *   而非可变 state 判重（SynqOS websocket fix、Reachy session.guard/expectedStop）；
     *   CAS 保证「要么没有 loop，要么恰好一个 loop」。
     */
    private val reconnectInFlight = AtomicBoolean(false)
    /**
     * 保护 subscriptions / pendingReplay / unsupported 三个集合。
     * ⚠️ 线程模型：UI/调用线程在 call()/subscribe()/handleError() 写，重连后台线程在
     * afterReconnect() 读+清空。MockTransport 已因同类竞态抛过 ConcurrentModificationException，
     * 这里不锁会重演。约定：锁内**只做集合增删/取快照**，绝不在持锁时调 transport.request()
     * （那会回调 onDisconnected→triggerReconnect，形成锁环）。
     */
    private val stateLock = Any()

    private val idGen = AtomicLong(1)
    @Volatile private var serial: String = ""
    @Volatile private var lastTarget: ConnectTarget? = null
    /** 逻辑订阅：key → 原始请求行。重连后逐条重新建立（断连即失效）。 */
    private val subscriptions = LinkedHashMap<String, String>()
    /** 断连期失败、且幂等的请求：重连成功后重放一次。写类不进这里。 */
    private val pendingReplay = mutableListOf<PendingCall>()
    private data class PendingCall(val line: String, val method: String)
    /** 探测到 METHOD_NOT_FOUND 的方法，后续直接短路。 */
    private val unsupported = mutableSetOf<String>()

    private var disconnectHandle: Disposable? = null
    private var frameHandle: Disposable? = null

    fun onEvent(cb: (Event) -> Unit): Disposable {
        synchronized(eventLock) { listeners.add(cb) }
        return Disposable { synchronized(eventLock) { listeners.remove(cb) } }
    }
    private fun emit(e: Event) {
        synchronized(eventLock) { listeners.toList() }.forEach { it(e) }
    }

    /** 建连 + 完整握手。记住 target 供重连复用。 */
    fun connect(target: ConnectTarget): Boolean {
        lastTarget = target
        detachTransportCallbacks()
        if (transport.connect(target).isFailure) {
            transition(State.FAILED)
            return false
        }
        attachTransportCallbacks()
        return handshake()
    }

    /** 握手 hello →（仅 BLE 时）system.authenticate → READY。成功即 afterReconnect（首次为空操作）。 */
    private fun handshake(): Boolean {
        transition(State.HELLO)
        val helloResp = transport.request(
            newRequest(Method.HELLO, mapOf("api_version" to Wire.API_VERSION))
        ).getOrElse { return false }
        errorOf(helloResp)?.let { handleError(Method.HELLO, it); return false }
        // 版本差异不硬拒：B 代 lib.rs:552 / fanhao lib.rs 顶注都写明「a version difference is
        // logged and served」，实测 App 发 api_version=40 给 API16 真 robotd 仍回 result(api_version=16)。
        readResult(helloResp)?.let {
            serial = str(it, "serial") ?: serial   // 真 robotd 的 HelloResult 无 serial（只有
                                                  // api_version/daemon_version/revision）；保留旧值。
        }

        if (requireAuth) {
            transition(State.AUTH)
            val authResp = transport.request(
                newRequest(Method.SYSTEM_AUTHENTICATE, mapOf("pin" to pin))
            ).getOrElse { return false }
            errorOf(authResp)?.let { handleError(Method.SYSTEM_AUTHENTICATE, it); return false }
            val r = readResult(authResp)
            if (r == null || bool(r, "authenticated") != true) {
                emit(Event.AuthFailed(int(r, "attempts_remaining") ?: 0))
                transition(State.FAILED)
                return false
            }
        }

        transition(State.READY)
        afterReconnect()   // 重订阅 + 幂等重放（首次为空）
        return true
    }

    /**
     * 发业务请求。仅 READY 可发；不支持的方法直接短路。
     * [replayable] 默认按只读白名单判定：只读在断连后可重放一次，写类不重放。
     */
    fun call(
        method: String,
        params: Map<String, Any?> = emptyMap(),
        replayable: Boolean = isReadOnly(method),
    ): Result<JsonObject> {
        if (state != State.READY) return Result.failure(IllegalStateException("SESSION_NOT_READY: $state"))
        if (method in unsupported) return Result.failure(IllegalStateException("CAPABILITY_UNSUPPORTED: $method"))
        val line = newRequest(method, params)
        val resp = transport.request(line).getOrElse {
            if (replayable) synchronized(stateLock) { pendingReplay.add(PendingCall(line, method)) }
            triggerReconnect("transport dropped on call: $method")
            return Result.failure(IOException("TRANSPORT_DROPPED: $method"))
        }
        val err = errorOf(resp)
        if (err != null) {
            handleError(method, err)
            return Result.failure(IllegalStateException("RPC_ERROR: ${err.code} ${err.message}"))
        }
        return Result.success(readResult(resp) ?: JsonObject())
    }

    /**
     * 发一条 JSON-RPC **notification**（无 id、无响应）——`robot.move` 等连续意图的通道。
     *
     * 一手依据：B 代 `robotd/src/main.rs:3483-3489`（notifications get no reply /
     * continuous intents arrive this way / 无 id 时直接 apply_intent），
     * `duck-ipc-proto` `ROBOT_MOVE` 注释 "Continuous; send as a notification"。
     *
     * 实现依赖 [RobotTransport.request] 的显式契约：**无 id 行写出后立即返回成功、不等响应**
     * （TcpTransport / BleTransport 已如此）。不用 `call()`：它会同步等一个永远不会来的响应，
     * 50 Hz 驾驶流会全部超时；也不会把连续意图塞进 pending 重放队列（写类不该重放）。
     */
    fun notify(method: String, params: Map<String, Any?>): Result<Unit> {
        if (state != State.READY) {
            return Result.failure(IllegalStateException("SESSION_NOT_READY: $state"))
        }
        val line = RpcNotification(method, params).toJsonLine(gson)
        val r = transport.request(line)
        return if (r.isSuccess) {
            Result.success(Unit)
        } else {
            triggerReconnect("transport dropped on notify: $method")
            Result.failure(r.exceptionOrNull() ?: IOException("NOTIFY_FAILED: $method"))
        }
    }

    /**
     * 订阅服务器通知流。重连后自动重订阅。
     * [method] = 订阅动作（如 robot.subscribe），[params] 可带 hz。
     * [streamMethod] = 期望收到的通知 method（如 robot.state）；为空则不过滤、全量回调。
     *   一手依据(fanhao duck-ipc-proto)：method::ROBOT_SUBSCRIBE="robot.subscribe"(lib.rs:794,订阅动作),
     *   method::ROBOT_STATE="robot.state"(lib.rs:804,通知 method); robotd Request::notify_state 里
     *   method=ROBOT_STATE(lib.rs:1884)且断言非此即错(1891)。两者不同字符串,必须分开,否则回调永不匹配。
     *   另 robotd:4759「Subscribing again replaces the rate rather than opening a second stream」
     *   ⇒ 重连重订阅是替换不叠加,lane 数不随重连增长(见 MockTransport.activeLanes 用 Set)。
     */
    fun subscribe(
        method: String,
        params: Map<String, Any?> = emptyMap(),
        streamMethod: String? = null,
        onFrame: (JsonObject) -> Unit,
    ): Disposable {
        val key = "$method:$params"
        val line = newRequest(method, params)
        synchronized(stateLock) { subscriptions[key] = line }
        val h = addFrameListener { o, m -> if (streamMethod == null || m == streamMethod) onFrame(o) }
        if (state == State.READY) transport.request(line)
        return Disposable {
            h.dispose()
            synchronized(stateLock) { subscriptions.remove(key) }
        }
    }

    private fun attachTransportCallbacks() {
        disconnectHandle = transport.onDisconnected { triggerReconnect("transport disconnected") }
        frameHandle = transport.subscribe(::parseNotification)
    }
    private fun detachTransportCallbacks() {
        disconnectHandle?.dispose(); disconnectHandle = null
        frameHandle?.dispose(); frameHandle = null
    }

    private fun addFrameListener(cb: (JsonObject, String?) -> Unit): Disposable {
        synchronized(frameListeners) { frameListeners.add(cb) }
        return Disposable { synchronized(frameListeners) { frameListeners.remove(cb) } }
    }
    private fun parseNotification(line: String) {
        try {
            val o = JsonParser.parseString(line).asJsonObject
            if (o.has("method") && !o.has("id")) {
                val m = o.get("method").asString
                val p = o.getAsJsonObject("params") ?: JsonObject()
                emit(Event.Notification(m, p))
                synchronized(frameListeners) { frameListeners.toList() }.forEach { it(p, m) }
            }
        } catch (_: Exception) { /* 忽略畸形通知 */ }
    }

    /**
     * 触发重连：**同步置 RECONNECTING 去重**（断连回调与 call() 失败可能同时触发），
     * 真正的 connect+handshake+退避在后台线程做，不阻塞调用方/回调线程。
     */
    private fun triggerReconnect(reason: String) {
        // 终态不重连：FAILED（次数耗尽放弃）/ DISCONNECTED（用户主动 close）。
        if (state == State.FAILED || state == State.DISCONNECTED) return
        // 单一拥有者 CAS：onDisconnected 回调、call() 失败、handshake 中间态再断三路可能并发，
        // 只有第一个拿到的启动 loop；其余直接返回。不靠 mutable state 判重（见 reconnectInFlight 注释）。
        if (!reconnectInFlight.compareAndSet(false, true)) return
        transition(State.RECONNECTING)
        Thread({ reconnectLoop(reason) }, "robot-session-reconnect").start()
    }

    private fun reconnectLoop(reason: String) {
        var attempt = 0
        var ok = false
        try {
            while (attempt < maxReconnectAttempts) {
                attempt++
                val target = lastTarget
                if (target == null) break
                detachTransportCallbacks()
                val connected = transport.connect(target).isSuccess
                if (connected) {
                    attachTransportCallbacks()
                    if (handshake()) { ok = true; break }   // handshake 成功已在 READY 调 afterReconnect()
                    detachTransportCallbacks()
                }
                // 指数退避 + ±20% jitter：AWS Builders Library「Timeouts, retries, backoff with
                // jitter」指出无 jitter 的指数退避是 clear loser；jitter 打散同时重连、防风暴。
                val base = minOf(backoffBaseMs * (1L shl (attempt - 1)), backoffMaxMs)
                val jitter = (base * 0.2).toLong()
                val delay = if (jitter > 0) base - jitter + (Math.random() * (2 * jitter + 1)).toLong() else base
                try { Thread.sleep(maxOf(1L, delay)) } catch (_: InterruptedException) { Thread.currentThread().interrupt(); break }
            }
        } finally {
            // 终态守卫：只有仍在 RECONNECTING 时才判失败。若期间被 close() 置成 DISCONNECTED，
            // 或用户主动重连改变了 state，别把新状态覆盖成 FAILED。
            if (!ok && state == State.RECONNECTING) {
                emit(Event.ReconnectFailed(attempt))
                transition(State.FAILED)
            }
            // guard 必须最后释放：否则 loop 未真正结束就有新断连进来，又能起第二个 loop。
            reconnectInFlight.set(false)
            // 补洞：guard 释放前若链路又断，那条断连回调会被上面的 CAS 吞掉（当时 inFlight=true）。
            // 复查 transport 实连状态，发现「state=READY 但链路已断」就补一次重连，避免悬死。
            // 这是串行新 loop（guard 已释放），不是并发，安全。
            if (state == State.READY && !transport.isConnected()) {
                triggerReconnect("link dropped within reconnect guard window")
            }
        }
    }

    /** 重连成功后：重订阅 + 重放一次幂等 pending。锁内只取快照+清空，锁外才调 transport。 */
    private fun afterReconnect() {
        val (subLines, toReplay) = synchronized(stateLock) {
            val subs = subscriptions.values.toList()
            val replay = pendingReplay.toList()
            pendingReplay.clear()
            subs to replay
        }
        subLines.forEach { line -> transport.request(line) }
        toReplay.forEach { transport.request(it.line) }
    }

    /** 等待状态机回到 READY（供 UI/测试），超时返回当前状态。 */
    fun awaitReady(timeoutMs: Long = 5_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (state == State.READY) return true
            if (state == State.FAILED) return false
            Thread.sleep(10)
        }
        return state == State.READY
    }

    /** 供 UI 判断：某方法是否因固件版本不支持而应灰化。 */
    fun isUnsupported(method: String): Boolean = synchronized(stateLock) { method in unsupported }

    private fun handleError(method: String, err: RpcError) {
        when (err.code) {
            RpcCode.METHOD_NOT_FOUND -> {
                synchronized(stateLock) { unsupported.add(method) }
                emit(Event.CapabilityUnsupported(method))   // emit 在锁外，避免锁环
            }
            RpcCode.INVALID_PARAMS -> emit(Event.ContractSkew(method, err.message))
            RpcCode.PERMISSION_DENIED -> emit(Event.PermissionDenied(method))
        }
    }

    private fun newRequest(method: String, params: Map<String, Any?>): String =
        RpcRequest(idGen.getAndIncrement(), method, params).toJsonLine(gson)

    private fun errorOf(line: String): RpcError? = try {
        val o = JsonParser.parseString(line).asJsonObject
        val e = o.getAsJsonObject("error") ?: return null
        RpcError(e.get("code").asInt, str(e, "message") ?: "")
    } catch (_: Exception) { null }

    private fun readResult(line: String): JsonObject? = try {
        JsonParser.parseString(line).asJsonObject.getAsJsonObject("result")
    } catch (_: Exception) { null }

    // Gson JsonObject 的 null-safe 取值（JsonObject 没有 org.json 的 opt* 方法）
    private fun str(o: JsonObject?, k: String): String? =
        o?.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asString
    private fun bool(o: JsonObject?, k: String): Boolean? =
        o?.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asBoolean
    private fun int(o: JsonObject?, k: String): Int? =
        o?.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asInt

    /** 只读方法白名单：断连重连后可安全重放。写类一律不自动重放。 */
    private fun isReadOnly(method: String): Boolean = method in setOf(
        Method.HELLO, Method.SYSTEM_INFO, Method.ROBOT_HEALTH, Method.ROBOT_STATE,
        Method.ROBOT_POLICIES, Method.ROBOT_MODEL, Method.NET_STATUS, Method.NET_SCAN,
        Method.UPDATE_STATUS, Method.UPDATE_CHECK, Method.SYSTEM_LOGS,
    )

    fun close() {
        // 顺序要紧：先置 DISCONNECTED（triggerReconnect 的终态守卫据此拒绝重连），
        // 再 detach 回调、关 transport。若反过来，transport.close() 触发的残断连回调
        // 可能趁 state 还是 READY 抢到 CAS guard 起一个重连 loop，与 close 打架。
        transition(State.DISCONNECTED)
        detachTransportCallbacks()
        transport.close()
    }
}
