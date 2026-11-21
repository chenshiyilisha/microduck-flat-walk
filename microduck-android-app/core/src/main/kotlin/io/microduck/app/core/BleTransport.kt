package io.microduck.app.core

import com.google.gson.JsonParser
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
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
 *  · `Reassembler.forReplies()`：客户端收的是加密 envelope，用 96KiB 松边界。
 *  · notification 每次回调一个 [ByteArray] chunk → push 重组出 envelope → 解密后按 id 分流：
 *      有 id = 某 request 的响应（唤醒 pending latch）；无 id 有 method = 通知流（分发给 subscribe）。
 *    这与 TcpTransport.dispatchLine 完全同构，只是数据源从 readLine 换成 notification chunk。
 *
 * ── 连接次序 ── 一手 duck-ble/src/gatt.rs:44-56
 *  · connect() 先让 GattLink 建链 + 发现服务；再 **read 一次 RPC_UUID**（促成加密配对 + 拿
 *    API_VERSION），然后订阅通知。read 是契约的一部分：它需要已认证加密链路，正是它让 central
 *    在 write 前完成配对 —— 否则「先 subscribe 再 write」会让首次 write 被静默拒绝。
 *
 * 每条 GATT 会话先完成 Noise_NNpsk0 握手；握手后只接受认证密文 envelope，绝不回退到明文。
 * ⚠️ 无整机/无 Android 真机：本类用 FakeGattLink 在 JVM 上真测协议编排；真实 GATT I/O
 *    （onCharacteristicWrite 串行、CCCD、bonding、MTU）由 app 模块实现，仅 Gradle 编译验证。
 */
class BleTransport(
    private val link: GattLink,
    psk: ByteArray,
    /**
     * 配对码里的 serial：**PSK 归属标签**，仅作诊断/日志，绝不作为 wire 上的身份校验。
     *
     * 🔴 2026-11-21 真机翻案（一手，别再加回硬校验）：`fc0382b` 曾在此加「hello 响应必须
     * 回 `result.serial == expectedSerial`，否则 [markDisconnected]」——这是**自造协议**，
     * 与固件不互操作，刷加密 btd 后 100% 断链，真机症状 `hello: BLE_REQUEST_DROPPED id=1`。
     * 一手三份固件（kissqy v167 / DuckBuddy-main / ft1910 的 `duck-ipc-proto`）`HelloResult`
     * **只有 api_version/daemon_version/revision，没有 serial 字段**；官方 duckctl 也从不校验
     * hello serial。身份由 Noise NNpsk0 的 **PSK 持钥证明**承担（`secure.rs:Config::load(&path, id)`
     * 的 id = SoC serial 派生的 first name ⇒ 每机一把 PSK，握上手即证明对端是那台机器人）。
     * 保留此参数只为调用方兼容与诊断artifact，[dispatchLine] 不得据它拒连。
     */
    private val expectedSerial: String? = null,
    private val requestTimeoutMs: Long = 5_000,
) : RobotTransport {

    override val kind: TransportKind = TransportKind.BLE

    private val psk = psk.copyOf().also { require(it.size == 32) { "BLE_PSK_LENGTH" } }
    /**
     * 板端自报的 API_VERSION（GATT `read RPC_UUID` 首字节），connect() 成功后可读；
     * 未连接 / 非 BLE 通道为 null。
     *
     * 🔴 为什么必须有：上游一手 `duck-ble/src/gatt.rs:34-39` 明写该 read 不是可选优化，
     * 而是「read it once for the API version … a client that finds a version it does not know
     * can say so before writing anything」—— 目的就是让版本 skew 可观测。旧实现读完只判
     * isFailure 就把值丢了，等于把契约里的告警能力删掉。
     *
     * 2026-11-14 真机实证：PC 侧单次 read 稳定返回 `0x25`=**37**，而 App `Wire.API_VERSION=40`
     * （SSH 侧另见 `robotctl` v37 CLI / `robotd` v40 daemon）。skew 真实存在且此前完全不可见。
     *
     * 语义：**只记录、不硬拒**。一手 `duck-ipc-proto/src/lib.rs:961` 原文
     * "A version difference is logged and served"；`PROTOCOL_MISMATCH` 已退役，
     * 方法缺失靠 -32601 逐方法降级。故这里绝不因 skew 断链。
     */
    @Volatile
    var peerApiVersion: Int? = null
        private set

    private val lock = Any()
    @Volatile private var connected = false
    @Volatile private var closing = false
    @Volatile private var secureReady = false
    @Volatile private var handshakeFailure: String? = null
    private val cryptoLock = Any()
    private var secureSession: NoiseNnPsk0Session? = null
    private var handshakeLatch: CountDownLatch? = null
    private val handshakeTimeoutMs = 5_000L

    /** id → 响应行 + 一次性 latch（与 TcpTransport 同构）。 */
    private val responses = ConcurrentHashMap<Long, PendingResponse>()
    private class PendingResponse(
        val latch: CountDownLatch,
    ) {
        @Volatile var line: String? = null
    }

    private val frameSubs = mutableListOf<(String) -> Unit>()
    private val disconnectCbs = mutableListOf<() -> Unit>()
    private val writeLock = Any()
    private val generation = AtomicLong(0)

    /** 客户端入站重组器：for_replies（96KiB 松边界），非 forRequests 紧边界。 */
    private var inbound = BleChunkCodec.Reassembler.forReplies()
    @Volatile private var lastDisconnectReason: String = ""

    // ---- connect ----
    override fun connect(target: ConnectTarget): Result<Unit> {
        if (target !is ConnectTarget.Ble) {
            return Result.failure(IllegalArgumentException("BleTransport 只接受 ConnectTarget.Ble，收到 $target"))
        }
        closing = false
        secureReady = false
        handshakeFailure = null
        peerApiVersion = null
        synchronized(cryptoLock) {
            secureSession?.close()
            secureSession = null
        }
        inbound = BleChunkCodec.Reassembler.forReplies()
        val linked = link.connect()
        if (linked.isFailure) return Result.failure(linked.exceptionOrNull() ?: IOException("BLE_LINK_CONNECT_FAILED"))

        // 🔴 **不请求 MTU 协商**（一手依据见 [GattLink.requestMtu] 注释）：Android 14 起首个 GATT client 的
        // requestMtu 由系统固定为 517，且本机/板端对该请求的 onMtuChanged 回调常延迟或缺失；一旦发出却未收到
        // 回调，该请求在 Android 蓝牙栈层面会一直「outstanding」，与后续 read/hello 写竞争「单 outstanding
        // 操作」约束 → 首条 hello 写被 ERROR_GATT_WRITE_REQUEST_BUSY 拒绝（真机实测：无论把 requestMtu 放在
        // onServicesDiscovered 还是这里、是否 await，只要发出就可能 BUSY）。而客户端出站固定 FLOOR_MTU=20、
        // 不依赖协商 MTU（duckctl 同款），入站 chunk 由板端按自身 MTU 切、与本地协商无关 ⇒ 请求 MTU 在此链路
        // 是净负收益。故直接不请求；[GattLink.requestMtu] 保留为可选能力但本连接路径不调用。

        // 契约动作：先 read 一次 RPC_UUID，促成加密配对 + 拿 API_VERSION（gatt.rs:44-56）。
        // 值必须留下来：见 peerApiVersion 注释（版本 skew 是契约要求可观测的）。
        val apiVersion = link.readApiVersion()
        if (apiVersion.isFailure) {
            link.close()
            return Result.failure(apiVersion.exceptionOrNull() ?: IOException("BLE_READ_API_VERSION_FAILED"))
        }
        synchronized(lock) { peerApiVersion = apiVersion.getOrNull() }
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
        val latch = CountDownLatch(1)
        handshakeLatch = latch
        val session = try {
            NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.INITIATOR)
        } catch (e: Exception) {
            link.close()
            synchronized(lock) { connected = false }
            return Result.failure(IOException("BLE_NOISE_INIT_FAILED", e))
        }
        synchronized(cryptoLock) { secureSession = session }
        val firstMessage = try {
            session.start()
        } catch (e: Exception) {
            failHandshake("Noise initiator failed: ${e.message}")
            return Result.failure(IOException("BLE_NOISE_INIT_FAILED", e))
        }
        val sent = writeLine(NoiseBleFrameCodec.encode(NoiseBleFrameCodec.Type.INIT, firstMessage))
        if (sent.isFailure) {
            failHandshake("Noise handshake write failed")
            return Result.failure(sent.exceptionOrNull() ?: IOException("BLE_NOISE_WRITE_FAILED"))
        }
        val handshakeCompleted = try {
            latch.await(handshakeTimeoutMs, TimeUnit.MILLISECONDS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            failHandshake("Noise handshake interrupted")
            return Result.failure(IOException("BLE_NOISE_HANDSHAKE_INTERRUPTED", e))
        }
        if (!handshakeCompleted) {
            failHandshake("Noise handshake timed out")
            return Result.failure(IOException("BLE_NOISE_HANDSHAKE_TIMEOUT"))
        }
        val failure = handshakeFailure
        if (failure != null || !secureReady) {
            failHandshake(failure ?: "Noise handshake did not complete")
            return Result.failure(IOException("BLE_NOISE_HANDSHAKE_FAILED: ${failure ?: "incomplete"}"))
        }
        return Result.success(Unit)
    }

    // ---- request：切 20B chunk 串行写，等 id 响应 ----
    override fun request(line: String): Result<String> {
        if (!connected || !secureReady || !link.isConnected()) {
            return Result.failure(IOException("BLE_NOT_CONNECTED_OR_UNSECURED"))
        }
        val id = parseId(line)
        val plaintext = line.removeSuffix("\n").removeSuffix("\r")
        if (plaintext.contains('\n') || plaintext.contains('\r')) {
            return Result.failure(IllegalArgumentException("BLE_MULTILINE_REQUEST"))
        }
        val pending = PendingResponse(CountDownLatch(1))
        if (id != null) responses[id] = pending

        return try {
            synchronized(writeLock) {
                if (!connected || !secureReady || !link.isConnected()) {
                    throw IOException("BLE_DROPPED_BEFORE_WRITE")
                }
                val ciphertext = synchronized(cryptoLock) {
                    checkNotNull(secureSession).encrypt(plaintext.toByteArray(Charsets.UTF_8))
                }
                val frame = NoiseBleFrameCodec.encode(NoiseBleFrameCodec.Type.DATA, ciphertext)
                val written = writeLine(frame)
                if (written.isFailure) {
                    throw IOException("BLE_WRITE_FAILED: ${written.exceptionOrNull()?.message}")
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
        } catch (e: Exception) {
            if (id != null) responses.remove(id)
            markDisconnected("secure BLE request failed: ${e.message}")
            Result.failure(e)
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
        lines.forEach { line ->
            try {
                val frame = NoiseBleFrameCodec.decode(line)
                when (frame.type) {
                    NoiseBleFrameCodec.Type.REPLY -> {
                        check(!secureReady) { "BLE_UNEXPECTED_HANDSHAKE_REPLY" }
                        synchronized(cryptoLock) { checkNotNull(secureSession).finish(frame.payload) }
                        secureReady = true
                        handshakeFailure = null
                        handshakeLatch?.countDown()
                    }
                    NoiseBleFrameCodec.Type.DATA -> {
                        check(secureReady) { "BLE_DATA_BEFORE_HANDSHAKE" }
                        val plaintext = synchronized(cryptoLock) {
                            checkNotNull(secureSession).decrypt(frame.payload)
                        }
                        val decoded = Charsets.UTF_8.newDecoder()
                            .onMalformedInput(CodingErrorAction.REPORT)
                            .onUnmappableCharacter(CodingErrorAction.REPORT)
                            .decode(ByteBuffer.wrap(plaintext))
                            .toString()
                        check(!decoded.contains('\n') && !decoded.contains('\r')) {
                            "BLE_MULTILINE_PLAINTEXT"
                        }
                        dispatchLine(decoded)
                    }
                    NoiseBleFrameCodec.Type.INIT -> error("BLE_UNEXPECTED_HANDSHAKE_INIT")
                }
            } catch (e: Exception) {
                failHandshake("invalid Noise frame: ${e.message}")
                return
            }
        }
    }

    /** 一行进来：有 id → 唤醒对应 request；无 id 有 method → 通知流。 */
    private fun dispatchLine(line: String) {
        if (line.isEmpty()) return
        val id = parseId(line)
        if (id != null) {
            val p = responses.remove(id)
            if (p != null) {
                // 🔴 不做 hello serial 硬校验：一手 HelloResult 无 serial 字段（见构造参数注释）。
                // 身份 = Noise PSK 持钥证明；握手完成即已认证，这里只按 id 分流。
                p.line = line
                p.latch.countDown()
            }
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
                secureReady = false
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
        handshakeFailure = reason
        handshakeLatch?.countDown()
        synchronized(cryptoLock) {
            secureSession?.close()
            secureSession = null
        }
        cbs.forEach { safeInvoke { it() } }   // 锁外回调：会话层会重连 → 再调 connect()
        link.close()
    }

    private fun failHandshake(reason: String) {
        handshakeFailure = reason
        secureReady = false
        handshakeLatch?.countDown()
        if (connected) markDisconnected(reason) else link.close()
    }

    private fun writeLine(line: String): Result<Unit> {
        for (chunk in BleChunkCodec.chunks(line, BleChunkCodec.FLOOR_MTU)) {
            val result = link.writeChunk(chunk)
            if (result.isFailure) return result
        }
        return Result.success(Unit)
    }

    override fun close() {
        closing = true
        generation.incrementAndGet()
        synchronized(lock) {
            connected = false
            secureReady = false
            responses.values.forEach { it.latch.countDown() }
            responses.clear()
            frameSubs.clear(); disconnectCbs.clear()
        }
        handshakeLatch?.countDown()
        synchronized(cryptoLock) {
            secureSession?.close()
            secureSession = null
        }
        psk.fill(0)
        inbound = BleChunkCodec.Reassembler.forReplies()
        link.close()
    }

    override fun isConnected(): Boolean = connected && secureReady && link.isConnected()

    /** 从 NDJSON 行取 id（Gson 解析；与 TcpTransport 同样的 null-safe）。 */
    private fun parseId(line: String): Long? = try {
        val o = JsonParser.parseString(line).asJsonObject
        if (o.has("id") && !o.get("id").isJsonNull) o.get("id").asLong else null
    } catch (_: Exception) { null }

    private fun safeInvoke(fn: () -> Unit) { try { fn() } catch (_: Throwable) { /* 回调异常不影响其他订阅者 */ } }

    /** 仅供测试/诊断：最近断连原因。 */
    fun lastDisconnectReason(): String = lastDisconnectReason
}
