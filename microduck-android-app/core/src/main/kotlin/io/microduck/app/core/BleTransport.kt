package io.microduck.app.core

import com.google.gson.JsonParser
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * BLE 后端 —— P0 阶段 D。**协议编排层**（纯 Kotlin/JVM，零 Android 依赖），
 * 真正的 GATT I/O（BluetoothGatt/CCCD/bonding/MTU/串行写）在 app 模块的 [GattLink] 实现里。
 *
 * 收发的是**同一份 NDJSON JSON-RPC 2.0 行协议**，与 Mock/Tcp/WebRtc 完全一致 ⇒ 会话层零改动。
 *
 * ── 出站（App → robot）── 一手 duckctl/src/main.rs:1779-1784 / 2070-2090
 *  · `chunks(line, FLOOR_MTU)`：**固定 20 字节**，不是协商 MTU。duckctl 注释原文
 *    "btleplug does not expose the negotiated MTU, so 20 bytes — the floor every BLE link
 *    guarantees — is the safe assumption. Slower than necessary on a good link, and correct on
 *    every link."（btleplug 拿不到协商 MTU；Android 虽拿得到，但用 floor 依然正确且对齐官方客户端）
 *  · 逐 chunk 调 [GattLink.writeChunk]（实现方保证串行 + WithResponse 确认），一行写完即完整帧。
 *
 * ── 入站（robot → App）── 一手 duckctl/src/main.rs:1787-1790
 *  · `Reassembler.forReplies()`：客户端收的是机器人回复，用 64KiB 松边界（非 forRequests 紧边界）。
 *  · notification 每次回调一个 [ByteArray] chunk → push 重组出整行 → 按有无 id 分流：
 *      有 id = 某 request 的响应（唤醒 pending latch）；无 id 有 method = 通知流（分发给 subscribe）。
 *    这与 TcpTransport.dispatchLine 完全同构，只是数据源从 readLine 换成 notification chunk。
 *
 * ── 连接次序 ── 一手 duck-ble/src/gatt.rs:44-56
 *  · connect() 先让 GattLink 建链 + 发现服务；再 **read 一次 RPC_UUID**（促成加密配对 + 拿
 *    API_VERSION），然后订阅通知。read 是契约的一部分：它需要已认证加密链路，正是它让 central
 *    在 write 前完成配对 —— 否则「先 subscribe 再 write」会让首次 write 被静默拒绝。
 *
 * ⚠️ 无整机/无 Android 真机：本类用 FakeGattLink 在 JVM 上真测协议编排；真实 GATT I/O
 *    （onCharacteristicWrite 串行、CCCD、bonding、MTU）由 app 模块实现，仅 Gradle 编译验证。
 */
class BleTransport(
    private val link: GattLink,
    private val requestTimeoutMs: Long = 5_000,
) : RobotTransport {

    override val kind: TransportKind = TransportKind.BLE

    private val lock = Any()
    @Volatile private var connected = false
    @Volatile private var closing = false

    /** id → 响应行 + 一次性 latch（与 TcpTransport 同构）。 */
    private val responses = ConcurrentHashMap<Long, PendingResponse>()
    private class PendingResponse(val latch: CountDownLatch) {
        @Volatile var line: String? = null
    }

    private val frameSubs = mutableListOf<(String) -> Unit>()
    private val disconnectCbs = mutableListOf<() -> Unit>()
    private val writeLock = Any()
    private val generation = AtomicLong(0)

    /** 客户端入站重组器：for_replies（64KiB 松边界），非 forRequests 紧边界。 */
    private var inbound = BleChunkCodec.Reassembler.forReplies()
    @Volatile private var lastDisconnectReason: String = ""

    // ---- connect ----
    override fun connect(target: ConnectTarget): Result<Unit> {
        if (target !is ConnectTarget.Ble) {
            return Result.failure(IllegalArgumentException("BleTransport 只接受 ConnectTarget.Ble，收到 $target"))
        }
        closing = false
        val linked = link.connect()
        if (linked.isFailure) return Result.failure(linked.exceptionOrNull() ?: IOException("BLE_LINK_CONNECT_FAILED"))

        // 契约动作：先 read 一次 RPC_UUID，促成加密配对 + 拿 API_VERSION（gatt.rs:44-56）。
        val apiVersion = link.readApiVersion()
        if (apiVersion.isFailure) {
            link.close()
            return Result.failure(apiVersion.exceptionOrNull() ?: IOException("BLE_READ_API_VERSION_FAILED"))
        }
        val gen = generation.incrementAndGet()

        // 订阅通知：每来一个 chunk 交给 for_replies 重组器，整行按 id 分流。
        val sub = link.setNotificationHandler { chunk ->
            onNotification(gen, chunk)
        }
        if (sub.isFailure) {
            link.close()
            return Result.failure(sub.exceptionOrNull() ?: IOException("BLE_SUBSCRIBE_FAILED"))
        }

        link.onDisconnected { markDisconnected("gatt disconnected") }
        synchronized(lock) { connected = true }
        return Result.success(Unit)
    }

    // ---- request：切 20B chunk 串行写，等 id 响应 ----
    override fun request(line: String): Result<String> {
        if (!connected || !link.isConnected()) return Result.failure(IOException("BLE_NOT_CONNECTED"))
        val id = parseId(line)
        val pending = PendingResponse(CountDownLatch(1))
        if (id != null) responses[id] = pending

        return try {
            synchronized(writeLock) {
                if (!connected || !link.isConnected()) throw IOException("BLE_DROPPED_BEFORE_WRITE")
                // 出站固定 FLOOR_MTU=20（duckctl 一手）；writeChunk 由 GattLink 保证串行 + WithResponse 确认。
                for (chunk in BleChunkCodec.chunks(line, BleChunkCodec.FLOOR_MTU)) {
                    val r = link.writeChunk(chunk)
                    if (r.isFailure) throw IOException("BLE_WRITE_FAILED: ${r.exceptionOrNull()?.message}")
                }
            }
            if (id == null) {
                Result.success("")   // 本协议业务请求都带 id；无 id 不等响应
            } else if (!pending.latch.await(requestTimeoutMs, TimeUnit.MILLISECONDS)) {
                responses.remove(id)
                Result.failure(IOException("BLE_REQUEST_TIMEOUT id=$id"))
            } else {
                pending.line?.let { Result.success(it) }
                    ?: Result.failure(IOException("BLE_REQUEST_DROPPED id=$id"))
            }
        } catch (e: IOException) {
            if (id != null) responses.remove(id)
            markDisconnected(e.message ?: "write failed")
            Result.failure(e)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            if (id != null) responses.remove(id)
            Result.failure(IOException("BLE_WRITE_INTERRUPTED"))
        }
    }

    /** notification chunk → for_replies 重组 → 整行按 id 分流（与 TcpTransport.dispatchLine 同构）。 */
    private fun onNotification(gen: Long, chunk: ByteArray) {
        if (generation.get() != gen || closing) return
        val lines = try {
            synchronized(lock) { inbound.push(chunk) }
        } catch (e: BleChunkCodec.FramingError) {
            // framing 失败 = 对端不会分帧（或攻击）⇒ 关连接（fanhao session.rs:56-60 同语义）
            markDisconnected("framing failed: ${e.message}")
            return
        }
        lines.forEach { dispatchLine(it) }
    }

    /** 一行进来：有 id → 唤醒对应 request；无 id 有 method → 通知流。 */
    private fun dispatchLine(line: String) {
        if (line.isEmpty()) return
        val id = parseId(line)
        if (id != null) {
            val p = responses.remove(id)
            if (p != null) { p.line = line; p.latch.countDown() }
            return    // 未知 id（如重连前旧请求迟到响应）直接丢弃
        }
        // 无 id：通知（如 robot.state）→ 分发给所有订阅者
        val subs = synchronized(lock) { frameSubs.toList() }
        subs.forEach { safeInvoke { it(line) } }
    }

    override fun subscribe(onFrame: (String) -> Unit): Disposable {
        synchronized(lock) { frameSubs.add(onFrame) }
        return Disposable { synchronized(lock) { frameSubs.remove(onFrame) } }
    }

    override fun onDisconnected(cb: () -> Unit): Disposable {
        synchronized(lock) { disconnectCbs.add(cb) }
        return Disposable { synchronized(lock) { disconnectCbs.remove(cb) } }
    }

    /** 断连：置位、唤醒所有 pending、回调会话层、关 link。**幂等**，close() 除外不发回调。 */
    private fun markDisconnected(reason: String) {
        // 显式 data class 固定返回类型：两个分支的 emptyList()/toList() 会被推断成
        // List<Nothing> vs List<() -> Unit>，Kotlin 只能推成 Any 导致后面 cbs.forEach 解不出
        // （TcpTransport 当初踩过同一个坑，见其 DisconnectSnapshot）。
        data class Snap(val fired: Boolean, val cbs: List<() -> Unit>)
        val snap: Snap = synchronized(lock) {
            if (!connected) Snap(false, emptyList())
            else {
                connected = false
                lastDisconnectReason = reason
                responses.values.forEach { it.latch.countDown() }   // line=null ⇒ failure
                responses.clear()
                Snap(true, disconnectCbs.toList())
            }
        }
        val fired = snap.fired
        val cbs = snap.cbs
        if (!fired) return
        generation.incrementAndGet()
        cbs.forEach { safeInvoke { it() } }   // 锁外回调：会话层会重连 → 再调 connect()
        link.close()
    }

    override fun close() {
        closing = true
        generation.incrementAndGet()
        synchronized(lock) {
            connected = false
            responses.values.forEach { it.latch.countDown() }
            responses.clear()
            frameSubs.clear(); disconnectCbs.clear()
        }
        inbound = BleChunkCodec.Reassembler.forReplies()
        link.close()
    }

    override fun isConnected(): Boolean = connected && link.isConnected()

    /** 从 NDJSON 行取 id（Gson 解析；与 TcpTransport 同样的 null-safe）。 */
    private fun parseId(line: String): Long? = try {
        val o = JsonParser.parseString(line).asJsonObject
        if (o.has("id") && !o.get("id").isJsonNull) o.get("id").asLong else null
    } catch (_: Exception) { null }

    private fun safeInvoke(fn: () -> Unit) { try { fn() } catch (_: Throwable) { /* 回调异常不影响其他订阅者 */ } }

    /** 仅供测试/诊断：最近断连原因。 */
    fun lastDisconnectReason(): String = lastDisconnectReason
}
