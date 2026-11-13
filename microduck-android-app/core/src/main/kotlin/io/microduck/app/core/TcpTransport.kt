package io.microduck.app.core

import com.google.gson.JsonParser
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.io.Writer
import java.net.ConnectException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * TCP 后端 —— P0 阶段 C1（连 PC 侧 unix→TCP relay，或本测试里的本地 relay）。
 *
 * 收发的是**同一份 NDJSON JSON-RPC 2.0 行协议**，与 Mock/Ble/WebRtc 完全一致，
 * 故上层 RobotSession 零改动（换后端只换这一层）。
 *
 * ── 为什么用 BufferedReader.readLine() 分帧（一手依据 Oracle JDK17 API）──
 *  - 行终止符：`\n` / `\r` / `\r\n` / EOF；返回的行不含终止符；**EOF 返回 null**。
 *  - 内部缓冲自动处理「半包」（一行跨多次底层 read 拼齐）与「粘包」（一次 read 多行拆开），
 *    不必自己写拼包/拆包状态机 —— TCP 是字节流、无消息边界，NDJSON 用换行做帧界正对症。
 *  - 读线程 `while ((line = readLine()) != null)`：**null 即对端关闭 ⇒ 断连检测**，
 *    唤醒所有 pending + 触发 onDisconnected，让会话层走重连。
 *
 * ── 线程模型（同步阻塞式接口适配真 I/O，见 RobotTransport 注释）──
 *  - 一个后台读线程 [readerLoop] 唯一负责 readLine，按行分流：
 *      · 有 `id` 的行 = 某 request 的响应 → 放进 [responses] 并 countDown 对应 latch
 *      · 无 `id` 有 `method` 的行 = 服务器通知 → 分发给 [subscriptions] 回调
 *  - request() 在调用线程：加 id 发一行 → 等自己的 latch（带超时）→ 取回响应行。
 *  - 断连/超时/未连接统一返回 Result.failure，绝不向会话层抛异常。
 *
 * ⚠️ 连接可重建：会话层重连时会再次调用 connect()，此时重建 socket + 读线程；
 *    旧 socket 的资源在 close()/断连时释放。所有共享状态并发保护（读线程 vs 调用线程）。
 */
class TcpTransport(
    private val connectTimeoutMs: Int = 2_000,
    /**
     * 读超时，默认 0=不设（无限阻塞）。
     * ⚠️ read 超时 ≠ 断连：idle 长连接读超时是正常现象，把它当断连会误触发重连
     * （这一层 semantic gap 必须显式钉死）。断连只靠 EOF(readLine()==null)/IOException 检测。
     * half-open（拔网线）的检出属 C2+ 应用层心跳 / TCP keepalive，C1 不引入。
     *
     * 一手依据（Oracle JDK17 `Socket.setSoTimeout(int)` 官方文档）：
     *   "If the timeout expires, a java.net.SocketTimeoutException is raised, **though the
     *   Socket is still valid**." + "A timeout of zero is interpreted as an infinite timeout."
     * ⇒ 超时后底层流并未损坏、socket 可继续读；[readerLoop] 捕获后必须回到循环继续读，
     *   绝不能据此判定断连（曾有一版注释写「超时后底层流进入不确定态，稳妥起见按断连处理」，
     *   是**未经查证的推断**，与官方语义相反，已纠正）。
     */
    private val socketTimeoutMs: Int = 0,
    private val requestTimeoutMs: Long = 5_000,
) : RobotTransport {

    override val kind: TransportKind = TransportKind.TCP

    private val lock = Any()
    @Volatile private var connected = false
    /** 本地主动关闭：区分于对端断链，避免 close() 误触发会话层重连。 */
    @Volatile private var closing = false
    @Volatile private var socket: Socket? = null
    @Volatile private var writer: Writer? = null
    @Volatile private var reader: BufferedReader? = null
    @Volatile private var readerThread: Thread? = null

    /** 本代连接代次：重连后递增，旧读线程退出前不得再动新连接的状态。 */
    private val generation = AtomicLong(0)

    /** id → 响应行 + 一次性 latch。用 ConcurrentHashMap 免读线程/调用线程竞态。 */
    private val responses = ConcurrentHashMap<Long, PendingResponse>()
    private class PendingResponse(val latch: CountDownLatch) {
        @Volatile var line: String? = null
    }

    private val frameSubs = mutableListOf<(String) -> Unit>()
    private val disconnectCbs = mutableListOf<() -> Unit>()
    /** 写锁：重连会换 writer/socket 实例，锁必须绑在稳定的 this 上，不能锁 writer。 */
    private val writeLock = Any()
    /** 最近一次断连原因，纯测试/诊断用（负对照可断言断连确实被检测到）。 */
    @Volatile private var lastDisconnectReason: String = ""

    // ---- connect ----
    override fun connect(target: ConnectTarget): Result<Unit> {
        val addr = when (target) {
            is ConnectTarget.Tcp -> InetSocketAddress(target.host, target.port)
            else -> return Result.failure(IllegalArgumentException("TcpTransport 只接受 ConnectTarget.Tcp，收到 $target"))
        }
        // 先关掉上一代（若会话层重连前忘了），避免socket泄漏/双读线程
        teardownSocket()

        closing = false   // 新一次 connect（含重连）清除上次 close 的标志
        return try {
            val s = Socket()
            s.connect(addr, connectTimeoutMs)
            if (socketTimeoutMs > 0) s.soTimeout = socketTimeoutMs   // 默认 0 → 不设，靠 EOF 检测断连
            val r = BufferedReader(InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8))
            val w = OutputStreamWriter(s.getOutputStream(), StandardCharsets.UTF_8)
            val gen = generation.incrementAndGet()

            synchronized(lock) {
                socket = s
                reader = r
                writer = w
                connected = true
            }
            val t = Thread({ readerLoop(gen, s, r) }, "tcp-transport-reader-$gen").apply { isDaemon = true }
            synchronized(lock) { readerThread = t }
            t.start()
            Result.success(Unit)
        } catch (e: ConnectException) {
            teardownSocket()
            Result.failure(IOException("TCP_CONNECT_REFUSED ${addr.hostString}:${addr.port}: ${e.message}"))
        } catch (e: SocketTimeoutException) {
            teardownSocket()
            Result.failure(IOException("TCP_CONNECT_TIMEOUT ${addr.hostString}:${addr.port}"))
        } catch (e: IOException) {
            teardownSocket()
            Result.failure(IOException("TCP_CONNECT_FAILED: ${e.message}"))
        }
    }

    // ---- request：发一行，按 id 等对应响应行 ----
    override fun request(line: String): Result<String> {
        val w = writer
        if (!connected || w == null || socket == null) {
            return Result.failure(IOException("TCP_NOT_CONNECTED"))
        }
        val id = parseId(line)
        val pending = PendingResponse(CountDownLatch(1))
        if (id != null) responses[id] = pending

        return try {
            synchronized(writeLock) {
                // 用当前 writer（重连后会换实例），但锁绑在稳定的 writeLock 上
                val cur = connected
                if (!cur) throw IOException("TCP_DROPPED_BEFORE_WRITE")
                w.write(line)
                w.write("\n")          // NDJSON 帧界 = 换行（一侧写，读线程另一侧 readLine 拆）
                w.flush()
            }
            if (id == null) {
                // 无 id 的请求（本协议里业务请求都带 id）不等响应，直接成功
                Result.success("")
            } else if (!pending.latch.await(requestTimeoutMs, TimeUnit.MILLISECONDS)) {
                responses.remove(id)
                Result.failure(IOException("TCP_REQUEST_TIMEOUT id=$id"))
            } else {
                pending.line?.let { Result.success(it) }
                    ?: Result.failure(IOException("TCP_REQUEST_DROPPED id=$id"))
            }
        } catch (e: IOException) {
            if (id != null) responses.remove(id)
            // 写失败通常意味着链路已断，主动走一遍断连处理
            markDisconnected("write failed: ${e.message}")
            Result.failure(IOException("TCP_WRITE_FAILED: ${e.message}"))
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            if (id != null) responses.remove(id)
            Result.failure(IOException("TCP_INTERRUPTED"))
        }
    }

    // ---- 读线程：唯一 readLine，按 id 分流响应 / 通知 ----
    private fun readerLoop(gen: Long, s: Socket, r: BufferedReader) {
        try {
            while (generation.get() == gen && s.isConnected && !s.isClosed) {
                // 超时捕获必须放在 readLine **内层**：一手依据 Oracle JDK17 Socket.setSoTimeout —
                // "If the timeout expires, a SocketTimeoutException is raised, though the Socket
                // is still valid" ⇒ 超时后底层流没坏、socket 可继续读，必须回到 while 下一轮，
                // 绝不能 fall-through 到外层 finally 当成断连（那样 idle 超时会误触发重连）。
                // 只有调用方显式设 socketTimeoutMs>0 才会抛；默认 0 → readLine 无限阻塞。
                val line = try {
                    r.readLine()
                } catch (_: SocketTimeoutException) {
                    continue   // 超时 ≠ 断连，继续读（negative-control 见 CoreSelfTest [13]）
                } ?: break     // EOF ⇒ 对端关闭（断连的唯一正向判据）
                if (line.isEmpty()) continue
                dispatchLine(line)
            }
        } catch (_: IOException) {
            // 连接被对端重置/关闭（RST）/本端 teardown → 交给 finally 统一判断连
        } finally {
            if (generation.get() == gen) markDisconnected("reader exited", gen)
        }
    }

    /** 一行进来：有 id → 唤醒对应 request；无 id 有 method → 通知流。 */
    private fun dispatchLine(line: String) {
        val id = parseId(line)
        if (id != null) {
            val p = responses.remove(id)
            if (p != null) {
                p.line = line
                p.latch.countDown()
            }
            // 未知 id（如重连前旧请求的迟到响应）直接丢弃，不打扰上层
            return
        }
        // 通知：有 method 且无 id（对齐 RobotSession.parseNotification 的判据）
        val isNotification = try {
            val o = JsonParser.parseString(line).asJsonObject
            o.has("method") && !o.has("id")
        } catch (_: Exception) { false }
        if (isNotification) {
            val cbs = synchronized(lock) { frameSubs.toList() }
            cbs.forEach { safeInvoke { it(line) } }
        }
    }

    /** 断连时要在锁外触发的回调快照。用显式类型，避免 mixed-type 推断成 Any 后强转。 */
    private class DisconnectSnapshot(
        val disconnectCbs: List<() -> Unit>,
        val fired: Boolean,
    )

    /** 断连：置位、唤醒所有 pending（失败）、回调会话层、清理 socket。**幂等**。 */
    private fun markDisconnected(reason: String, expectedGen: Long? = null) {
        val snap = synchronized(lock) {
            // 三种情况不重复触发：已断连 / 代次不匹配（旧读线程迟到）/ active
            if (!connected || (expectedGen != null && generation.get() != expectedGen)) {
                DisconnectSnapshot(emptyList(), false)
            } else {
                connected = false
                lastDisconnectReason = reason
                // 唤醒所有还在等的 request：line 保持 null ⇒ request 侧拿到 TCP_REQUEST_DROPPED
                responses.values.forEach { it.latch.countDown() }
                responses.clear()
                // 本地主动 close 不回调会话层，避免误触发重连；对端断链才回调。
                DisconnectSnapshot(
                    if (closing) emptyList() else disconnectCbs.toList(),
                    true,
                )
            }
        }
        if (snap.fired) {
            // 回调必须在锁外：onDisconnected → 会话层 triggerReconnect → 再调 connect()，持锁会死锁
            snap.disconnectCbs.forEach { safeInvoke { it() } }
            teardownSocket()
        }
    }

    /** 仅供测试/诊断读取断连原因（负对照：断言断连检测真的触发过）。 */
    fun lastDisconnectReason(): String = lastDisconnectReason

    // ---- subscribe / onDisconnected / close / isConnected ----
    override fun subscribe(onFrame: (String) -> Unit): Disposable =
        synchronized(lock) { frameSubs.add(onFrame) }.let { Disposable { synchronized(lock) { frameSubs.remove(onFrame) } } }

    override fun onDisconnected(cb: () -> Unit): Disposable =
        synchronized(lock) { disconnectCbs.add(cb) }.let { Disposable { synchronized(lock) { disconnectCbs.remove(cb) } } }

    override fun close() {
        closing = true                 // 先置位：markDisconnected 据此不触发重连回调
        generation.incrementAndGet()   // 让旧读线程失效
        markDisconnected("local close")
        synchronized(lock) { frameSubs.clear(); disconnectCbs.clear() }
    }

    override fun isConnected(): Boolean = connected

    // ---- 内部工具 ----
    /** 关 socket/流，不回调（避免与 markDisconnected 的回调重复）。 */
    private fun teardownSocket() {
        val s = synchronized(lock) {
            val cur = socket
            socket = null; writer = null; reader = null
            cur
        }
        try { s?.close() } catch (_: IOException) { }
    }

    private fun parseId(line: String): Long? = try {
        val o = JsonParser.parseString(line).asJsonObject
        if (o.has("id") && !o.get("id").isJsonNull) o.get("id").asLong else null
    } catch (_: Exception) { null }

    private inline fun safeInvoke(body: () -> Unit) {
        try { body() } catch (_: Exception) { /* 单个回调异常不影响其他回调/读线程 */ }
    }
}
