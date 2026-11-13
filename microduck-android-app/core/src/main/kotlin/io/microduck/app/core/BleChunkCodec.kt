package io.microduck.app.core

/**
 * BLE GATT 分帧编解码 —— **一比一移植** fanhao `duck-ble/src/framing.rs`（hd1910-v167-trunk-imu-i2c）。
 * 纯 Kotlin/JVM，零 Android 依赖，可在 tools/selftest.sh 用真 2.4.0 + JDK17 真编译真测。
 *
 * ── 为什么存在（一手依据 framing.rs 顶部注释）──
 * NDJSON（一行一个 JSON 对象）在 unix socket/WebRTC 上一次 write 就是一帧；**BLE 是唯一一条
 * 消息装不进单次 write 的链路**：可用 payload = ATT_MTU - 3，从不重协商的手机是 20 字节，
 * 好链路几百字节。所以一行要拆成多 chunk 发、也要从多 chunk 拼回来。
 *
 * ── 无帧头：换行就是帧界 ──
 * "There is no framing header. The newline that already separates messages is the frame
 * delimiter, in both directions. `serde_json` escapes a newline inside a string as `\n`, so a raw
 * `0x0A` never appears inside a serialised JSON object."（framing.rs:11-16）
 * ⇒ 我们绝不在 JSON 内部制造裸 0x0A（Gson 同样把串内换行转义），帧界安全。
 *
 * ── 调用方向语义（最容易搞错、必须钉死，见 session.rs / bluez.rs / duckctl 一手调用点）──
 *  · client 出站（我们 App → robot）：`chunks(line, FLOOR_MTU)` 固定 20 —— duckctl/src/main.rs:1781
 *    注释原文 "20 bytes — the floor every BLE link guarantees — is the safe assumption"，不用协商 MTU。
 *  · client 入站（robot → 我们 App）：`Reassembler.forReplies()` 松边界 64KiB —— duckctl:1790。
 *  · robot 入站：`Reassembler()` 紧边界 8KiB（防 radio range 内任何人） —— session.rs:40。
 *  · robot 出站：`chunks(line, link.mtu())` + bluez 层 `notification_payload(req.mtu)` clamp 512
 *    —— session.rs:311 / bluez.rs:440。注意 [chunks] 与 [notificationPayload] 是**两个独立函数**，
 *    chunks 内部**不** clamp 512，clamp 只发生在 notificationPayload。别把两者混成一个。
 */
object BleChunkCodec {
    /** framing.rs:40 — 机器人重组「客户端请求」的上限：安全紧边界，防 radio 范围内任何人 pin 内存。 */
    const val MAX_LINE: Int = 8 * 1024

    /** framing.rs:54 — 客户端重组「机器人回复」的上限：信任已连接 robot，松边界，曾因共用 8KiB 卡死 system.logs。 */
    const val MAX_REPLY_LINE: Int = 64 * 1024

    /** framing.rs:66 — 每条 BLE 链路必支持的最小 payload（ATT MTU 23 - 3）。 */
    const val FLOOR_MTU: Int = 20

    /** framing.rs:72 — GATT characteristic value 硬上限 512（Core spec Vol3/F §3.2.9），与 ATT MTU 不同一个数。 */
    const val MAX_ATTRIBUTE_VALUE: Int = 512

    /**
     * framing.rs:86 — 这条链路实际能承载的 notification payload。
     * `(mtu - 3).clamp(20, 512)`：减 3 是 ATT 头；clamp 上界 512 是 CoreBluetooth 517 MTU 的回归修复
     * （framing.rs:74-84：517-3=514 比特征值上限多 2 字节，central 静默丢掉，`{"security":…}` 变
     * `{"serity":…}`，或丢换行致调用永不返回 —— 这个 App 一手发现的 bug，见 mobile-app.md:224）。
     */
    fun notificationPayload(mtu: Int): Int =
        (mtu - 3).coerceIn(FLOOR_MTU, MAX_ATTRIBUTE_VALUE)

    /**
     * framing.rs:180 — 把一行（含结尾换行）切成 notification 大小的 chunk。
     * - `mtu = max(mtu, FLOOR_MTU)`：0/荒谬 MTU 防除零、防一字节一 chunk（framing.rs:182-183）。
     * - 换行**计入 payload**、且绝不重复：没有就补一个，已有就原样（framing.rs:184-187）。
     *   "a client that reassembles until newline then needs no notion of end of message beyond
     *   the one it already has."
     * - ⚠️ 与 [notificationPayload] 是两件事：调用方若传协商 MTU，需自行保证 ≤ 特征值上限；
     *   duckctl 客户端直接传 [FLOOR_MTU]=20 规避这个问题。
     */
    fun chunks(line: String, mtu: Int): List<ByteArray> {
        val size = mtu.coerceAtLeast(FLOOR_MTU)
        val bytes = line.toByteArray(Charsets.UTF_8).toMutableList()
        if (bytes.isEmpty() || bytes.last() != '\n'.code.toByte()) {
            bytes.add('\n'.code.toByte())
        }
        return bytes.chunked(size) { it.toByteArray() }
    }

    /**
     * framing.rs:101 — 对端字节被拒的原因；两者都意味着「关连接」，但日志不同（乱帧的 peer vs 潜在攻击）。
     * Rust 版 impl Display + std::error::Error（framing.rs:105-113）；Kotlin 侧继承 Exception 才能 throw，
     * message 照抄 rust Display 的文案。
     */
    sealed class FramingError : Exception() {
        /** 在 [limit] 字节内没等到换行。变体携带 limit，因为两方向上限不同。 */
        class LineTooLong(val limit: Int) : FramingError() {
            override val message: String get() = "no newline within $limit bytes"
        }
        /** 非合法 UTF-8，更不可能是 JSON。 */
        object NotUtf8 : FramingError() {
            override val message: String get() = "not valid UTF-8"
        }
    }

    /**
     * framing.rs:95 — 把入站 chunk 重组为整行。
     * 方向由 [limit] 区分：[forRequests] 用 8KiB 紧边界、[forReplies] 用 64KiB 松边界。
     */
    class Reassembler private constructor(private val limit: Int) {
        private val buf = ByteArrayOutputStreamCompat()

        companion object {
            /** 机器人侧重组客户端请求：8KiB 紧边界（framing.rs:118-121 Default）。 */
            fun forRequests(): Reassembler = Reassembler(MAX_LINE)
            /** 客户端侧重组机器人回复：64KiB 松边界（framing.rs:130-136 for_replies）。 */
            fun forReplies(): Reassembler = Reassembler(MAX_REPLY_LINE)
        }

        /**
         * framing.rs:145 — 喂一个 chunk，返回它补完整的**所有**行。
         * 返回 List 而非单行：一次 write 可能 legitimately 带多个短行
         * （客户端把 hello + update.status 打包进一个 40 字节 write 是高效，不是错）。
         * @throws FramingError 超长 / 非 UTF-8；任一情况都**清空 buf**（防 peer 靠重发 pin 内存）。
         */
        fun push(chunk: ByteArray): List<String> {
            if (buf.size() + chunk.size > limit) {
                buf.reset()   // framing.rs:148 — 清掉半行，后续无论如何不可解析，还可能被 pin 内存
                throw FramingError.LineTooLong(limit)
            }
            buf.write(chunk)

            val lines = mutableListOf<String>()
            var at: Int
            while (buf.indexOfNewline().also { at = it } >= 0) {
                val lineBytes = buf.drainThrough(at)   // 含 \n
                var content = lineBytes.copyOfRange(0, lineBytes.size - 1)  // 去 \n
                if (content.isNotEmpty() && content.last() == '\r'.code.toByte()) {
                    content = content.copyOfRange(0, content.size - 1)       // 容忍 CRLF
                }
                if (content.isEmpty()) continue                               // 空行跳过
                val text = String(content, Charsets.UTF_8)
                // Kotlin/JVM 的 String(ByteArray, UTF_8) 对非法字节替换为 U+FFFD，不会抛；
                // 故按 framing.rs:167 的语义显式校验，非法 UTF-8 必须拒收而非静默替换。
                if (!isValidUtf8(content)) {
                    buf.reset()
                    throw FramingError.NotUtf8
                }
                lines.add(text)
            }
            return lines
        }

        /** framing.rs:175 — 待换行的数据字节数（用于日志一个中途静默的 peer）。 */
        fun pending(): Int = buf.size()
    }
}

/**
 * 极简可增长字节缓冲：只需 append / 找第一个 \n / 取走到 \n（含）/ 清空 / size。
 * 不用 java.io.ByteArrayOutputStream 是因为要按 \n 定位并 drain 前段，自己维护更直白、无额外拷贝语义坑。
 */
private class ByteArrayOutputStreamCompat {
    private var data = ByteArray(0)

    fun size(): Int = data.size

    fun write(chunk: ByteArray) {
        val merged = ByteArray(data.size + chunk.size)
        System.arraycopy(data, 0, merged, 0, data.size)
        System.arraycopy(chunk, 0, merged, data.size, chunk.size)
        data = merged
    }

    fun indexOfNewline(): Int {
        for (i in data.indices) if (data[i] == '\n'.code.toByte()) return i
        return -1
    }

    /** 取 [0..at]（含 at 处的 \n），并从缓冲移除；返回该段拷贝。 */
    fun drainThrough(at: Int): ByteArray {
        val head = data.copyOfRange(0, at + 1)
        data = data.copyOfRange(at + 1, data.size)
        return head
    }

    fun reset() { data = ByteArray(0) }
}

/** 严格 UTF-8 校验（CharsetDecoder REPORT），对应 rust `std::str::from_utf8` 的拒绝语义。 */
private fun isValidUtf8(bytes: ByteArray): Boolean = try {
    java.nio.charset.StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
        .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
        .decode(java.nio.ByteBuffer.wrap(bytes))
    true
} catch (_: java.nio.charset.CharacterCodingException) {
    false
}
