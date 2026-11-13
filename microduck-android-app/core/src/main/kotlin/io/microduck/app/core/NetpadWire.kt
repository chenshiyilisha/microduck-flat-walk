package io.microduck.app.core

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.ceil
import kotlin.math.floor

/**
 * fanhao UDP 手柄（netpad）28 字节数据报 —— **一比一逐字节移植**
 * `firmware/padd/src/udp/wire.rs:1-186`（其自身注明移植自 Pollen microduck 0.17.1
 * `pad-map/src/wire.rs`，"Change nothing here that upstream has not changed first"）。
 *
 * 布局（全 little-endian，wire.rs:2 / :102-114）：
 * ```
 *  [0..4)   MAGIC  "DKPD"
 *  [4]      VERSION = 1
 *  [5]      reserved = 0
 *  [6..10)  seq   u32   +1/包，回绕；接收端丢弃不比当前新的包
 *  [10..14) t_ms  u32   发送方自己的毫秒钟，仅用于日志抖动
 *  [14..26) axes  6 × i16  [lx, ly, rx, ry, lt, rt]；±32767 = ±1（摇杆），0..32767 = 0..1（扳机）
 *  [26..28) buttons u16  位序即 wire 位序，KNOWN = 0x1FFF
 * ```
 * 🔴 每个数据报是手柄**全量状态**而非增量（wire.rs:8）⇒ 丢一个包无需重传，
 *   下一个直接覆盖。这也是 [NetpadDriveSink] 只需周期性重发、不必做可靠传输的依据。
 *
 * 一手边界：
 *  - `udp-pad.md`：默认端口 4210、`timeout_ms = 250`，且该值**必须小于**
 *    `[safety] deadman_ms`（B 代 `robotd-params/src/lib.rs:914` / `deploy/robotd.toml:233` = 500ms）。
 *  - 客户端静默超过 timeout_ms ⇒ `padd` 不再发意图，`robotd` deadman 把速度归零
 *    （`udp-pad.md` "The client silent for timeout_ms … robotd's deadman stops any walking"）。
 *  - ⚠️ 该通道**默认关**、无 JSON-RPC 开关，需板上 `service.sh netpad on`（R4，待拍板）。
 *    本文件只做 wire 编码，不假设它已开。
 */
object NetpadWire {
    /** "DKPD" —— wire.rs:18 `pub const MAGIC: [u8; 4] = *b"DKPD";` */
    val MAGIC: ByteArray = byteArrayOf(0x44, 0x4B, 0x50, 0x44)
    const val VERSION: Int = 1
    const val LEN: Int = 28
    const val FULL: Double = 32767.0
    const val DEFAULT_PORT: Int = 4210
    /** `udp-pad.md` 默认；必须 < DEADMAN_MS，否则整份 robotd.toml 失效、robotd 拒启动。 */
    const val TIMEOUT_MS: Int = 250
    /** B 代 `robotd-params/src/lib.rs:914` 默认值；fanhao 走同一 `[safety] deadman_ms`。 */
    const val DEADMAN_MS: Int = 500

    /** 位序即 wire 位序（wire.rs:29-45）。 */
    object Buttons {
        const val NONE: Int = 0
        const val A: Int = 1 shl 0
        const val B: Int = 1 shl 1
        const val X: Int = 1 shl 2
        const val Y: Int = 1 shl 3
        const val LB: Int = 1 shl 4
        const val RB: Int = 1 shl 5
        const val START: Int = 1 shl 6
        const val SELECT: Int = 1 shl 7
        const val UP: Int = 1 shl 8
        const val DOWN: Int = 1 shl 9
        const val LEFT: Int = 1 shl 10
        const val RIGHT: Int = 1 shl 11
        const val HOME: Int = 1 shl 12
        const val KNOWN: Int = 0x1FFF
    }

    /**
     * 对应 wire.rs:164 `from_axes`：摇杆 -1..1（**上为正**）、扳机 0..1。
     * `q(v, lo) = (v.clamp(lo, 1.0) * 32767.0).round() as i16`
     *
     * 🔴 **逐字节移植陷阱**：Rust `f64::round()` 官方语义是
     * "If a value is half-way between two integers, **round away from 0.0**"
     * （doc.rust-lang.org/std/primitive.f64.html）；Kotlin `roundToInt()` 走
     * `Math.round` = floor(x+0.5)，**负半值偏向 +∞**。
     * `-0.5 * 32767 = -16383.5`：Rust 给 -16384(0xC000)，Kotlin roundToInt 给 -16383(0xC001)
     * ⇒ 用错函数会让「上/下半杆」的数据报差 1 LSB，且一般 roundtrip 测试看不出来。
     * 这里显式实现 half-away-from-zero，并由 CoreSelfTest [17] 逐字节断言锁住。
     */
    fun fromAxes(
        seq: Long,
        tMs: Long,
        sticks: DoubleArray,
        triggers: DoubleArray,
        buttons: Int = Buttons.NONE,
    ): NetpadPacket {
        require(sticks.size == 4 && triggers.size == 2) { "sticks=4 triggers=2" }
        fun q(v: Double, lo: Double): Int {
            val scaled = v.coerceIn(lo, 1.0) * FULL
            val rounded = if (scaled >= 0.0) floor(scaled + 0.5) else ceil(scaled - 0.5)
            return rounded.toInt().coerceIn(-32768, 32767)
        }
        val axes = listOf(
            q(sticks[0], -1.0), q(sticks[1], -1.0), q(sticks[2], -1.0), q(sticks[3], -1.0),
            q(triggers[0], 0.0), q(triggers[1], 0.0),
        )
        return NetpadPacket(seq, tMs, axes, buttons)
    }

    /** 对应 wire.rs:116 `decode`：短包 / magic 错 / 版本错三类错误都要显式拒绝。 */
    fun decode(b: ByteArray): NetpadPacket {
        if (b.size < LEN) throw NetpadWireException("SHORT:${b.size}")
        for (i in 0..3) {
            if (b[i] != MAGIC[i]) throw NetpadWireException("MAGIC")
        }
        if (b[4].toInt() != VERSION) throw NetpadWireException("VERSION:${b[4].toInt()}")
        val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
        bb.position(6)
        val seq = bb.int.toLong() and 0xFFFF_FFFFL
        val tMs = bb.int.toLong() and 0xFFFF_FFFFL
        val axes = (0 until 6).map { bb.short.toInt() }
        val buttons = bb.short.toInt() and 0xFFFF
        return NetpadPacket(seq, tMs, axes, buttons)
    }
}

/** 一个完整手柄状态。axes 用 [List] 而非数组，便于 data class 值相等断言。 */
data class NetpadPacket(
    val seq: Long,
    val tMs: Long,
    val axes: List<Int>,
    val buttons: Int,
) {
    init { require(axes.size == 6) { "a pad datagram carries 6 axes" } }

    /** 对应 wire.rs:102 `encode`。 */
    fun encode(): ByteArray = ByteBuffer.allocate(NetpadWire.LEN)
        .order(ByteOrder.LITTLE_ENDIAN)
        .apply {
            put(NetpadWire.MAGIC)
            put(NetpadWire.VERSION.toByte())
            put(0.toByte())                // [5] reserved
            putInt(seq.toInt())            // u32 回绕 = 取低 32 位
            putInt(tMs.toInt())
            axes.forEach { putShort(it.toShort()) }
            putShort(buttons.toShort())
        }.array()

    /** 对应 wire.rs:149 `values`：摇杆 -1..1（上正）、扳机 0..1。 */
    fun values(): DoubleArray {
        val stick = { v: Int -> (v / NetpadWire.FULL).coerceIn(-1.0, 1.0) }
        val trigger = { v: Int -> (v / NetpadWire.FULL).coerceIn(0.0, 1.0) }
        return doubleArrayOf(
            stick(axes[0]), stick(axes[1]), stick(axes[2]), stick(axes[3]),
            trigger(axes[4]), trigger(axes[5]),
        )
    }

    fun held(): Int = buttons and NetpadWire.Buttons.KNOWN
    fun reserved(): Int = buttons and (NetpadWire.Buttons.KNOWN.inv() and 0xFFFF)
}

class NetpadWireException(message: String) : Exception(message)
