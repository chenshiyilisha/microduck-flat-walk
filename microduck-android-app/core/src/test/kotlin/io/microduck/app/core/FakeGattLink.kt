package io.microduck.app.core

import com.google.gson.Gson
import com.google.gson.JsonObject
import java.io.IOException
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * [GattLink] 的 JVM 测试夹具 —— 在**无整机/无 Android** 下用真 chunk I/O 验证 [BleTransport] 的协议编排。
 *
 * ⚠️ 它不是真 BluetoothGatt，而是**协议语义等价的 GATT 对端**：
 *  - 模拟「单一 characteristic 双向」：writeChunk 收请求字节、按 NDJSON 行解析，回 canned 响应，
 *    并把响应**按 notification chunk 大小切碎**后经 setNotificationHandler 回调（验客户端重组）。
 *  - 模拟 fanhao 对端语义：hello(api_version=40) / system.authenticate(pin) / robot.health /
 *    robot.subscribe→robot.state 通知 / 错误码。
 *  - 可编程：notification 分片大小、连接即断、写失败、readApiVersion 失败。
 *  - [GattLink.writeChunk] 契约是「串行 + 已确认」；本夹具的 writeChunk 同步返回，等价于已 ack。
 *
 * 价值：验证「会话层零改动换 BLE 后端」+ 出站 20B 切块 + 入站跨 chunk 重组 + 按 id 分流 + 断连，
 * 这些是 Android GATT 真机之外唯一能在本机真测的部分。
 */
class FakeGattLink(
    /** 对端把每个响应切成这么大的 notification chunk（验客户端 for_replies 重组）。 */
    private val notifyChunkSize: Int = 20,
) : GattLink {
    private val gson = Gson()
    private val connected = AtomicBoolean(false)
    private val writtenChunks = ConcurrentLinkedQueue<ByteArray>()
    /** 对端观察到的客户端方法名序列（断连/重连断言用，对齐 LocalRelayServer.log）。 */
    private val methods = ConcurrentLinkedQueue<String>()
    private val inbound = BleChunkCodec.Reassembler.forRequests()   // 对端收客户端请求用紧边界
    private var handler: ((ByteArray) -> Unit)? = null
    private var disconnectCb: (() -> Unit)? = null
    private val apiVersion = AtomicInteger(Wire.API_VERSION)

    // 可编程故障
    @Volatile var failConnect: Boolean = false
    @Volatile var failReadApiVersion: Boolean = false
    @Volatile var failWrite: Boolean = false

    override fun connect(): Result<Int> {
        if (failConnect) { connected.set(false); return Result.failure(IOException("FAKE_GATT_CONNECT_FAIL")) }
        connected.set(true)
        return Result.success(notifyChunkSize * 3)   // 假装协商了个 MTU
    }

    override fun readApiVersion(): Result<Int> {
        if (!connected.get()) return Result.failure(IOException("FAKE_GATT_NOT_CONNECTED"))
        if (failReadApiVersion) return Result.failure(IOException("FAKE_GATT_READ_VERSION_FAIL"))
        return Result.success(apiVersion.get())
    }

    override fun setNotificationHandler(onChunk: (ByteArray) -> Unit): Result<Unit> {
        handler = onChunk
        return Result.success(Unit)
    }

    /**
     * 收一个 20B chunk → 喂对端重组器 → 每凑齐一行就回 canned 响应（切成 notification chunk 碎片）。
     */
    override fun writeChunk(chunk: ByteArray): Result<Unit> {
        if (!connected.get()) return Result.failure(IOException("FAKE_GATT_NOT_CONNECTED"))
        if (failWrite) return Result.failure(IOException("FAKE_GATT_WRITE_FAIL"))
        writtenChunks.add(chunk)
        val lines = try { inbound.push(chunk) } catch (_: BleChunkCodec.FramingError) {
            return Result.failure(IOException("FAKE_GATT_PEER_FRAMING_FAIL"))
        }
        lines.forEach { replyTo(it) }
        return Result.success(Unit)
    }

    private fun replyTo(line: String) {
        val o = try { gson.fromJson(line, JsonObject::class.java) } catch (_: Exception) { return } ?: return
        val id = if (o.has("id") && !o.get("id").isJsonNull) o.get("id").asLong else null
        val method = o.get("method")?.asString ?: return
        methods.add(method)
        val result = when (method) {
            Method.HELLO -> mapOf("api_version" to Wire.API_VERSION, "revision" to "fake-gatt", "serial" to "FAKE0001")
            Method.SYSTEM_AUTHENTICATE -> {
                val pin = o.getAsJsonObject("params")?.get("pin")?.asString ?: ""
                mapOf("authenticated" to (pin == Wire.BLE_DEFAULT_PIN), "attempts_remaining" to 3)
            }
            Method.ROBOT_HEALTH -> mapOf("servos" to (1..15).map { i -> mapOf("id" to i, "voltage" to 7.4) }, "fallen" to false)
            Method.ROBOT_SUBSCRIBE -> {
                // 先回订阅 ack，再推 1 条 robot.state 通知（无 id 有 method）
                emitNotification(notificationLine(Method.ROBOT_STATE, mapOf("vx" to 0.1, "policy" to "walk")))
                mapOf("accepted" to true)
            }
            else -> emptyMap()
        }
        emitNotification(okLine(id, result))
    }

    /**
     * 把一行切成 notification chunk 逐个回调，验客户端跨 chunk 重组。
     * ⚠️ 必须走 [BleChunkCodec.chunks]（与真 btd 出站 framing::chunks 同构）：它**自动补结尾 \n**。
     * 曾手写成 `line.toByteArray()` 直接切 → 没有帧界 \n → 客户端 Reassembler 永远凑不齐整行 →
     * request 超时卡 HELLO（首跑 [15] 抓到）。这反向证明「chunks 补换行」是 load-bearing 的。
     */
    private fun emitNotification(line: String) {
        for (chunk in BleChunkCodec.chunks(line, notifyChunkSize)) {
            handler?.invoke(chunk)
        }
    }

    /** 模拟对端拆链（断开 GATT）→ 触发客户端 onDisconnected。 */
    fun simulateDisconnect() {
        if (connected.compareAndSet(true, false)) disconnectCb?.invoke()
    }

    fun writtenBytes(): ByteArray {
        val all = writtenChunks.toList()
        val out = ByteArray(all.sumOf { it.size })
        var off = 0
        for (c in all) { System.arraycopy(c, 0, out, off, c.size); off += c.size }
        return out
    }
    fun writtenChunkCount(): Int = writtenChunks.size
    fun countOf(method: String): Int = methods.count { it == method }
    fun log(): List<String> = methods.toList()
    fun clearLog() { writtenChunks.clear(); methods.clear() }

    override fun mtu(): Int = if (connected.get()) notifyChunkSize * 3 else 0
    override fun onDisconnected(cb: () -> Unit) { disconnectCb = cb }
    override fun close() { connected.set(false) }
    override fun isConnected(): Boolean = connected.get()

    private fun okLine(id: Long?, result: Map<String, Any?>): String = gson.toJson(JsonObject().apply {
        addProperty("jsonrpc", Wire.JSONRPC)
        if (id != null) addProperty("id", id)
        add("result", gson.toJsonTree(result))
    })

    private fun notificationLine(method: String, params: Map<String, Any?>): String = gson.toJson(JsonObject().apply {
        addProperty("jsonrpc", Wire.JSONRPC)
        addProperty("method", method)
        add("params", gson.toJsonTree(params))
    })
}
