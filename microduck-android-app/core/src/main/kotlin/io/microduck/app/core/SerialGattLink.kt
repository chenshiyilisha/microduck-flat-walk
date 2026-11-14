package io.microduck.app.core

import java.io.IOException
import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.RejectedExecutionException

/**
 * [GattLink] 的**串行执行包装器** —— 把「GATT 一次只允许一个 outstanding 操作、
 * 必须等前一个操作的回调完成再发下一个」这条纪律，从 app 层（`AndroidBleGattLink` 的 latch）
 * 下沉到 core，使其可用 [FakeGattLink] 在 JVM 真测，并对**所有**调用方强制生效。
 *
 * ── 依据（一手，多源一致）──
 *  · **AOSP 蓝牙栈源码** `bta/include/bta_gatt_queue.h`：BTA GATTC「does not allow for
 *    multiple commands queuing」，`ReadCharacteristic / WriteCharacteristic / WriteCharDescr /
 *    ConfigureMtu` 必须**等回调**再发下一个；该头文件本身就是「pending 队列 + 正在执行标记 +
 *    回调完成后 `gatt_execute_next_op` 取下一条」的官方范本。
 *  · Android `BluetoothGatt` 同源行为：一次只允许一个 outstanding 操作，第二个调用返回 false
 *    （`ERROR_GATT_WRITE_REQUEST_BUSY`）；Stack Overflow 高赞（Rob Gorman / devunwired / Emil）
 *    一致：「you cannot initiate two operations at the same time … wait for the callback」。
 *  · ZOOZ《Making Android BLE work — part 3》+ Punch Through《Android BLE: The Ultimate Guide》：
 *    reads/writes/notifications 交错会互相干扰，须「queue operations and execute them serially,
 *    and always wait for a callback for a previous operation before you initiate a new one」。
 *
 * ── 为什么需要这一层（读 `AndroidBleGattLink` 现状得出）──
 *  `AndroidBleGattLink` 虽已有 `beginOp/awaitOp/releaseOp` 的 latch 骨架，但其 `beginOp`
 *  **直接覆盖**尚未完成的 `opLatch`——若两个操作同时进入，后一个会覆盖前一个的 latch，
 *  前一个的 `awaitOp` 永远等不到正确回调，且 GATT 层第二个调用本就应返回 BUSY。该逻辑在
 *  app 层、依赖 Android，无法用 FakeGattLink 在 JVM 验证。
 *
 *  本类用**单线程执行器**把操作排队：[runSerial] 提交任务后阻塞等结果，单线程保证
 *  **前一个操作的 [delegate] 方法返回（= 其回调已到达）之前，不会开始下一个**。任意调用方
 *  （`BleTransport` 或未来其他）即使并发调用，实际对 GATT 的操作都串行。
 *
 *  ⚠️ 非操作方法（[mtu] / [onDisconnected] / [isConnected] / [close]）**不入队**，直接转发——
 *  它们不发起 GATT 操作，无需串行；[close] 负责先停执行器再关 delegate，避免操作进行中被关闭。
 *
 *  🔴 边界：本类只强制「出站 GATT 操作串行」，不改变 [GattLink] 的契约（[writeChunk] 仍由
 *  delegate 负责等 `onCharacteristicWrite` 确认）。入站通知的线程纪律在 app 层
 *  `AndroidBleGattLink` 处理（不在 Binder 线程做重活），与本类互补。
 */
class SerialGattLink(
    private val delegate: GattLink,
    private val executor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "microduck-gatt-serial").apply { isDaemon = true }
    },
) : GattLink {

    @Volatile private var closed = false

    /**
     * 把一次 GATT 操作提交到串行执行器并**阻塞等结果**。
     * 单线程执行器保证：前一个操作的 [delegate] 方法返回（回调已到达）前，不会开始下一个。
     */
    private fun <T> runSerial(what: String, block: () -> Result<T>): Result<T> {
        if (closed) return Result.failure(IOException("GATT_SERIAL_CLOSED: $what"))
        val future: Future<Result<T>> = try {
            executor.submit(Callable { block() })
        } catch (e: RejectedExecutionException) {
            // 执行器已关闭（close 后仍被调用）⇒ 明确拒绝，不静默丢操作。
            return Result.failure(IOException("GATT_SERIAL_REJECTED: $what"))
        }
        return try {
            future.get()
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            Result.failure(IOException("GATT_SERIAL_INTERRUPTED: $what"))
        } catch (e: ExecutionException) {
            // delegate 抛出未捕获异常（不应发生，因 GattLink 方法都返回 Result）；如实转成 failure。
            Result.failure(IOException("GATT_SERIAL_EXECUTION: $what: ${e.cause?.message}"))
        }
    }

    // —— 发起 GATT 操作的方法：全部串行 ——
    override fun connect(): Result<Int> = runSerial("connect") { delegate.connect() }

    override fun readApiVersion(): Result<Int> =
        runSerial("readApiVersion") { delegate.readApiVersion() }

    override fun setNotificationHandler(onChunk: (ByteArray) -> Unit): Result<Unit> =
        runSerial("setNotificationHandler") { delegate.setNotificationHandler(onChunk) }

    override fun writeChunk(chunk: ByteArray): Result<Unit> =
        runSerial("writeChunk") { delegate.writeChunk(chunk) }

    // —— 非操作方法：直接转发，不入队 ——
    override fun mtu(): Int = delegate.mtu()

    override fun onDisconnected(cb: () -> Unit) { delegate.onDisconnected(cb) }

    override fun isConnected(): Boolean = delegate.isConnected()

    /** 先停执行器（中断执行中的操作），再关 delegate，避免操作进行中被关闭导致资源泄漏。 */
    override fun close() {
        closed = true
        executor.shutdownNow()
        delegate.close()
    }
}
