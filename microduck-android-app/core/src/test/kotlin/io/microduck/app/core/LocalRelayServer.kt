package io.microduck.app.core

import com.google.gson.Gson
import com.google.gson.JsonObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.io.Writer
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * 本地 NDJSON relay 测试服务器 —— P0 阶段 C1 的对端夹具，模拟 fanhao robotd 的 unix→TCP 面。
 *
 * ⚠️ 这不是「真 robotd」（那是 Rust，Windows 编不过，须 WSL2），而是**协议语义等价的测试对端**：
 * 收发同一份 NDJSON JSON-RPC 2.0 行协议，握手/订阅/通知/错误码行为照 fanhao 一手契约。
 * 价值：让 [TcpTransport] 的真实 socket I/O（分帧、粘包、断连检测、重连重建）在无整机/无 WSL 的
 * 本机可被真测；C2 再把 relay 后端换成真 `robotd --sim`，Transport 与会话层都不用改。
 *
 * 🔑 **C2 修正（2026-11-12，真固件探针抓出）**：`system.authenticate` 不是通用握手步骤，
 * 它只由 **BLE 传输层 btd** 回答（fanhao `btd/src/pairing.rs:24`、`route.rs:987`；真 robotd
 * 实测回 `-32601 "system.authenticate is not served by robotd"`）。
 * 因此本夹具**默认模拟真 robotd 的 unix/TCP 面**（[serveAuthenticate]=`false`：不服务认证、
 * HelloResult 不带 serial、所有方法无需认证即可访问）；设 `true` 才切回「BLE 会话面」。
 * 所有 TCP 用例都走默认值——否则又是「夹具自带 canned 认证」的假绿（Mock 103/103 漏检同型）。
 *
 * 可编程对端行为（造真实 I/O 边界，而非 mock 内存直返）：
 *  - [dropNextAfter] 收到第 N 条请求后主动关闭该连接（模拟 btd 重启 / relay 掉线）→ 客户端 readLine 得 EOF
 *  - [coalesceResponses] 把 N 条响应合并成**一次 write**（粘包）→ 验客户端 readLine 正确拆帧
 *  - [splitEveryByte] 把每行拆成**单字节分次 write+flush**（半包）→ 验客户端 readLine 正确拼帧
 *  - [pushStateFrames] 订阅后主动推 robot.state 通知（无 id 有 method）→ 验通知/响应分流
 *
 * 线程安全：每个 accept 连接一个处理线程；日志/计数用并发集合；控制面在锁/volatile 下。
 */
class LocalRelayServer(
    private val gson: Gson = Gson(),
) : AutoCloseable {

    /** 收到的请求行（完整 NDJSON），供断言重连是否重发 hello/auth/subscribe。 */
    private val received = ConcurrentLinkedQueue<String>()
    /** 活跃连接数（测试等待「连接已建立」用）。 */
    private val connects = AtomicInteger(0)
    private val accepted = AtomicBoolean(false)
    @Volatile private var serverSocket: ServerSocket? = null
    @Volatile private var running = false
    @Volatile private var acceptThread: Thread? = null
    private val clientThreads = mutableListOf<Thread>()

    // ---- 可编程对端行为 ----
    /**
     * 收到第 N 条请求后断链（1-based）；0=不断。
     * ⚠️ **只对第一条连接生效一次**（[firstDropDone] 置位后不再断）——模拟「一次性网络抖动」。
     *   这样重连后的新连接能握手成功，才能测「断→重连→重认证→重订阅」完整恢复。
     *   若每条连接都断，重连永远握不完（这正是初次跑测试时的夹具缺陷，制造了假风暴）。
     */
    @Volatile var dropNextAfter: Int = 0
    private val firstDropDone = AtomicBoolean(false)
    /**
     * 专测「握手中间态断链」：在指定方法回完响应后断链（如 AUTH 后断），逼会话层重连重入。
     * 配合 [dropTimes] 全局断前 N 次（跨连接累计），第 N+1 次连接不再断 → 能完成恢复。
     * 这是逼出「重连风暴」的关键：每条重连都在握手中间态断，旧版靠 state 判重会起并发 loop。
     */
    @Volatile var dropAfterMethod: String? = null
    @Volatile var dropTimes: Int = 1
    private val methodDropCount = AtomicInteger(0)
    /** 把连续 N 条响应合并成一次 write（粘包）；1=正常逐条。 */
    @Volatile var coalesceResponses: Int = 1
    /** 每行拆成单字节分次 write+flush（半包）。 */
    @Volatile var splitEveryByte: Boolean = false
    /** 收到 robot.subscribe 后推送的 robot.state 通知条数。 */
    @Volatile var pushStateFrames: Int = 0
    /** 对指定方法返回指定错误码（模拟 -32601/-32602/14）。 */
    @Volatile var errorOnMethod: Pair<String, Int>? = null
    /**
     * `false`（默认）=模拟真 robotd unix/TCP 面（认证返回 -32601，且无需认证）；
     * `true`=模拟 BLE 会话面（服务 system.authenticate）。C2 真固件探针结论，见类注释。
     */
    @Volatile var serveAuthenticate: Boolean = false

    fun port(): Int = serverSocket?.localPort ?: -1
    fun isRunning(): Boolean = running
    fun connectCount(): Int = connects.get()
    fun log(): List<String> = received.toList()
    fun countOf(method: String): Int = received.count { line ->
        try { gson.fromJson(line, JsonObject::class.java)?.get("method")?.asString == method } catch (_: Exception) { false }
    }
    fun clearLog() = received.clear()

    fun start(): Int {
        if (running) return port()
        val ss = ServerSocket(0, 50, java.net.InetAddress.getLoopbackAddress()) // 端口 0 = OS 自动分配
        serverSocket = ss
        running = true
        val t = Thread({
            while (running) {
                try {
                    val c = ss.accept()
                    connects.incrementAndGet()
                    val ct = Thread({ handleClient(c) }, "relay-client-${connects.get()}").apply { isDaemon = true }
                    synchronized(clientThreads) { clientThreads.add(ct) }
                    ct.start()
                } catch (_: IOException) {
                    if (!running) break
                }
            }
        }, "relay-accept").apply { isDaemon = true }
        acceptThread = t
        t.start()
        accepted.set(true)
        return ss.localPort
    }

    private fun handleClient(socket: Socket) {
        val reader = BufferedReader(InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8))
        val writer = OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8)
        var reqCount = 0
        val lanes = mutableSetOf<String>()   // 每连接重置：断连后重订阅即失效
        // 真 robotd 的 unix 面不需要 PIN ⇒ 所有方法直接可访问；BLE 面必须先认证。
        var authenticated = !serveAuthenticate
        val writeLock = Any()
        try {
            while (running && !socket.isClosed) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) continue
                received.add(line)
                reqCount++
                val o = try { gson.fromJson(line, JsonObject::class.java) } catch (_: Exception) { null } ?: continue
                val id = if (o.has("id") && !o.get("id").isJsonNull) o.get("id").asLong else null
                val method = o.get("method")?.asString ?: continue

                // 可编程错误码
                errorOnMethod?.let { (m, code) ->
                    if (m == method && id != null) {
                        writeLine(writer, writeLock, errorLine(id, code, "injected relay fault"))
                        continue
                    }
                }

                val responses = mutableListOf<String>()
                when (method) {
                    Method.HELLO -> responses.add(okLine(id, if (serveAuthenticate) mapOf(
                        "api_version" to Wire.API_VERSION, "revision" to "relay-test", "serial" to "RELAY0001",
                    ) else mapOf(
                        // 真 robotd HelloResult：api_version / daemon_version / revision，无 serial。
                        "api_version" to 16, "daemon_version" to "0.10.0", "revision" to null,
                    )))
                    Method.SYSTEM_AUTHENTICATE -> {
                        if (!serveAuthenticate) {
                            // 真固件实测原文（C2 探针）：认证由 BLE transport 回答，robotd 不服务。
                            responses.add(errorLine(id, RpcCode.METHOD_NOT_FOUND,
                                "system.authenticate is not served by robotd"))
                        } else {
                            val pin = o.getAsJsonObject("params")?.get("pin")?.asString ?: ""
                            authenticated = pin == "000000"
                            responses.add(okLine(id, mapOf(
                                "authenticated" to authenticated, "attempts_remaining" to if (authenticated) 3 else 2,
                            )))
                        }
                    }
                    Method.ROBOT_SUBSCRIBE -> {
                        lanes.add(method)   // Set：robotd:4759 重复订阅替换速率、不叠加
                        responses.add(okLine(id, mapOf("accepted" to true)))
                        // 订阅后主动推通知（无 id 有 method）
                        if (authenticated) repeat(pushStateFrames) { k ->
                            responses.add(notificationLine(Method.ROBOT_STATE, mapOf("vx" to 0.1 + k, "policy" to "walk")))
                        }
                    }
                    Method.ROBOT_HEALTH -> responses.add(okLine(id, mapOf(
                        "servos" to (1..15).map { i -> mapOf("id" to i, "voltage" to 7.4, "temperature" to 30 + i, "load" to i) },
                        "battery" to mapOf("voltage" to 7.4, "percentage" to 82), "fallen" to false,
                    )))
                    Method.ROBOT_STATE -> responses.add(okLine(id, mapOf("vx" to 0.31, "vy" to 0.0, "vyaw" to 0.0)))
                    else -> responses.add(okLine(id, emptyMap<String, Any?>()))
                }

                // 粘包：合并 N 条一次性 write（只合并「响应」，让通知/响应混在一帧里更狠）
                if (coalesceResponses > 1 && responses.size >= 1) {
                    val chunk = responses.joinToString("\n") + "\n"
                    writeRaw(writer, writeLock, chunk, splitEveryByte)
                } else {
                    responses.forEach { writeLine(writer, writeLock, it, splitEveryByte) }
                }

                // 可编程断链：① 首连回完第 N 条后断一次（一次性抖动）；
                // ② 每次在指定方法（如 AUTH 握手中间态）回完断，跨连接累计 dropTimes 次。
                val byCount = dropNextAfter > 0 && reqCount >= dropNextAfter
                val byMethod = dropAfterMethod == method && methodDropCount.get() < dropTimes
                val shouldDrop = (byCount && firstDropDone.compareAndSet(false, true)) ||
                    (byMethod && methodDropCount.incrementAndGet() <= dropTimes)
                if (shouldDrop) {
                    try { socket.close() } catch (_: IOException) { }
                    break
                }
            }
        } catch (_: IOException) {
            // 客户端断开
        } finally {
            try { socket.close() } catch (_: IOException) { }
        }
    }

    private fun writeLine(w: Writer, lock: Any, line: String, split: Boolean = false) =
        writeRaw(w, lock, line + "\n", split)

    private fun writeRaw(w: Writer, lock: Any, chunk: String, split: Boolean) {
        synchronized(lock) {
            if (split) {
                // 半包：逐字节 write+flush，逼客户端 readLine 跨多次底层 read 拼帧
                for (ch in chunk) { w.write(ch.code); w.flush() }
            } else {
                w.write(chunk); w.flush()
            }
        }
    }

    private fun okLine(id: Long?, result: Map<String, Any?>): String {
        val o = JsonObject().apply {
            addProperty("jsonrpc", Wire.JSONRPC)
            if (id != null) addProperty("id", id)
            add("result", gson.toJsonTree(result))
        }
        return gson.toJson(o)
    }

    private fun errorLine(id: Long?, code: Int, msg: String): String {
        val o = JsonObject().apply {
            addProperty("jsonrpc", Wire.JSONRPC)
            if (id != null) addProperty("id", id)
            add("error", JsonObject().apply { addProperty("code", code); addProperty("message", msg) })
        }
        return gson.toJson(o)
    }

    private fun notificationLine(method: String, params: Map<String, Any?>): String {
        val o = JsonObject().apply {
            addProperty("jsonrpc", Wire.JSONRPC)
            addProperty("method", method)
            add("params", gson.toJsonTree(params))
        }
        return gson.toJson(o)
    }

    override fun close() {
        running = false
        try { serverSocket?.close() } catch (_: IOException) { }
        acceptThread?.join(1_000)
        synchronized(clientThreads) { clientThreads.forEach { it.join(500) } }
    }
}
