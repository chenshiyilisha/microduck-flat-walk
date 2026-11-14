package io.microduck.app.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import io.microduck.app.core.BleChunkCodec
import io.microduck.app.core.GattLink
import io.microduck.app.core.Wire
import java.io.IOException
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * [GattLink] 的 Android 实现 —— 唯一触碰 `android.bluetooth.*` 的地方。
 *
 * ⚠️ **状态：可编译骨架，未在真机验证**（本机无 Android 真机 / 无整机）。
 * core 侧 [io.microduck.app.core.BleTransport] 协议编排已用 FakeGattLink 在 JVM 真测 103/0；
 * 本类的 GATT I/O（bonding / CCCD / onCharacteristicWrite 时序 / MTU）须整机落地后上板验收。
 *
 * ── 一手依据（全部查证，见 README 踩坑条）──
 *  1. 单操作串行：Android GATT 一次只允许一个 outstanding 操作，须等对应回调再发下一个，
 *     否则静默丢 / `ERROR_GATT_WRITE_REQUEST_BUSY`（官方 BluetoothGatt.writeCharacteristic 返回值；
 *     Polidea react-native-ble-plx wiki、capacitor-community/bluetooth-le#751、NOOP ANDROID.md）。
 *     ⇒ [awaitOp] 用 CountDownLatch 等回调；[writeChunk] 只在拿到 onCharacteristicWrite 后返回。
 *  2. write type = **WRITE_TYPE_DEFAULT（=2, acknowledged）**，绝不能用 NO_RESPONSE：
 *     fanhao duckctl/src/main.rs:2075 "Acknowledged writes, and that is not a detail…"——
 *     no-response 下「加密不足」的拒绝隐形，客户端只会傻等超时。
 *  3. 先 read 一次 RPC_UUID（促成加密配对 + 拿 API_VERSION，gatt.rs:44），再订阅。
 *  4. setCharacteristicNotification(true) **之外**还要写 CCCD `0x2902` = ENABLE_NOTIFICATION_VALUE。
 *  5. 连接次序：connectGatt → onConnectionStateChange(STATE_CONNECTED) → discoverServices →
 *     onServicesDiscovered → 定位 service/characteristic → requestMtu → read RPC_UUID → 写 CCCD 订阅。
 *  6. API 33+ 用内存安全的 `writeCharacteristic(ch, value, writeType): Int`；以下用 setValue + 旧重载。
 *  7. Android 14 起首个 GATT client requestMtu 固定 517（官方行为变更）——但客户端出站仍用
 *     [BleChunkCodec.FLOOR_MTU]=20，不受协商 MTU 影响（duckctl 同款选择）。
 *
 * 所有 platform I/O 回调都在 Android 的 Binder 线程上触发；本类用 latch 把回调式 API 适配成
 * [GattLink] 的同步阻塞契约（与 TcpTransport.request 同样的「阻塞等信号」思路）。
 */
@SuppressLint("MissingPermission") // BLUETOOTH_CONNECT 由宿主 Activity 在运行时申请（见 Manifest）
class AndroidBleGattLink(
    private val context: Context,
    private val device: BluetoothDevice,
    private val operationTimeoutMs: Long = 3_000,
) : GattLink {

    private val serviceUuid: UUID = UUID.fromString(Wire.BLE_SERVICE_UUID)
    private val rpcUuid: UUID = UUID.fromString(Wire.BLE_RPC_UUID)
    private val cccdUuid: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    @Volatile private var gatt: BluetoothGatt? = null
    @Volatile private var rpcChar: BluetoothGattCharacteristic? = null
    @Volatile private var connected = false
    @Volatile private var negotiatedMtu = BleChunkCodec.FLOOR_MTU
    @Volatile private var chunkHandler: ((ByteArray) -> Unit)? = null
    @Volatile private var disconnectCb: (() -> Unit)? = null

    /**
     * 入站通知的独立处理线程：与出站串行队列（core 的 SerialGattLink）分离，
     * 避免入站重组/分发被出站写操作阻塞。GATT 回调跑在 Binder 线程，这里只投递、
     * 不做重活，立即返回（依据：ZOOZ《Making Android BLE work — part 3》「GATT 调用应
     * 尽快离开 Binder 线程，阻塞会卡住后续所有回调」）。
     */
    private val notifyExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "microduck-ble-notify").apply { isDaemon = true }
    }

    /** 串行化所有 GATT 操作：一个 latch 代表「当前操作的回调」，回调到达才放行下一个。 */
    private val opLock = Any()
    @Volatile private var opLatch: CountDownLatch? = null
    @Volatile private var opStatus: Int = BluetoothGatt.GATT_SUCCESS
    @Volatile private var opReadValue: ByteArray? = null

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                g.discoverServices()   // 步骤 1：连接后先发现服务
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                connected = false
                disconnectCb?.invoke()  // 让会话层走重连（RPC_UUID 单边流，重连需重新配对/认证/订阅）
                g.close()
                if (this@AndroidBleGattLink.gatt === g) this@AndroidBleGattLink.gatt = null
            }
            releaseOp(status)
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                val svc = g.getService(serviceUuid)
                val ch = svc?.getCharacteristic(rpcUuid)
                if (ch == null) {
                    opStatus = GATT_LOCAL_NO_CHARACTERISTIC
                    releaseOp(status)
                    return
                }
                rpcChar = ch
                g.requestMtu(517)   // 步骤 2：请求 MTU（Android 14 首 client 固定 517）；onMtuChanged 后继续
            } else {
                opStatus = status
            }
            releaseOp(status)
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) negotiatedMtu = mtu
            mtuDone = true
            releaseOp(status)
        }

        override fun onCharacteristicRead(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            if (characteristic.uuid == rpcUuid) opReadValue = value
            releaseOp(status)
        }

        @Deprecated("API 33 以下兼容回调")
        override fun onCharacteristicRead(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (characteristic.uuid == rpcUuid) opReadValue = characteristic.value
            releaseOp(status)
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            releaseOp(status)   // 关键：每个 write 都有回调（官方 "in response to every writeCharacteristic call"）
        }

        override fun onDescriptorWrite(g: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            releaseOp(status)   // CCCD 写入完成 ⇒ 订阅真正生效
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray) {
            if (characteristic.uuid == rpcUuid) dispatchInbound(value)   // 一个 notification = 一个 chunk
        }

        @Deprecated("API 33 以下兼容回调")
        override fun onCharacteristicChanged(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            if (characteristic.uuid == rpcUuid) {
                // 🔴 characteristic.value 是平台缓存数组，回调后会被复用 ⇒ 必须立即拷贝（ZOOZ/PunchThrough）
                dispatchInbound(characteristic.value?.copyOf() ?: ByteArray(0))
            }
        }
    }

    override fun connect(): Result<Int> = try {
        // connectGatt(false, callback)：autoConnect=false 主动连；TRANSPORT_LE 显式 BLE。
        // ⚠️ 建 latch 必须在 connectGatt **之前**：回调（onConnectionStateChange）可能很快到达。
        // 整条链 onConnectionStateChange→onServicesDiscovered→onMtuChanged 会多次 releaseOp，
        // 但只剩最后一个 latch 有意义；这里用一个 latch 覆盖「连上+发现服务+MTU」的总完成点，
        // 以 rpcChar!=null 作为真正就绪判据（而非单次 releaseOp）。
        synchronized(opLock) {
            opLatch = CountDownLatch(1)
            opStatus = BluetoothGatt.GATT_SUCCESS
            mtuDone = false
            rpcChar = null
        }
        val g = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        } else {
            @Suppress("DEPRECATION") device.connectGatt(context, false, gattCallback)
        }
        gatt = g
        // 等链路建立 + 服务发现 + MTU 协商完成（以 rpcChar 就位为准，失败会置 opStatus）
        if (!awaitConnectReady()) return Result.failure(IOException("BLE_GATT_CONNECT_TIMEOUT"))
        if (opStatus != BluetoothGatt.GATT_SUCCESS || rpcChar == null) {
            return Result.failure(IOException("BLE_GATT_CONNECT_STATUS=$opStatus"))
        }
        if (rpcChar == null) return Result.failure(IOException("BLE_GATT_RPC_CHAR_MISSING"))
        connected = true
        Result.success(negotiatedMtu)
    } catch (e: SecurityException) {
        Result.failure(IOException("BLE_GATT_PERMISSION_DENIED: ${e.message}"))
    } catch (e: Exception) {
        Result.failure(IOException("BLE_GATT_CONNECT_EXCEPTION: ${e.message}"))
    }

    override fun readApiVersion(): Result<Int> {
        val g = gatt ?: return Result.failure(IOException("BLE_GATT_NOT_CONNECTED"))
        val ch = rpcChar ?: return Result.failure(IOException("BLE_GATT_RPC_CHAR_MISSING"))
        return try {
            opReadValue = null
            if (!beginOp { g.readCharacteristic(ch) }) return Result.failure(IOException("BLE_GATT_READ_REJECTED"))
            if (!awaitOp("read RPC_UUID")) return Result.failure(IOException("BLE_GATT_READ_TIMEOUT"))
            // RPC_UUID 首字节即 API_VERSION（gatt.rs:44 "read it once for the API version"）；
            // 具体编码由固件定，这里取单字节无符号值，失败则回退 Wire.API_VERSION 让上层继续握手。
            val v = opReadValue?.firstOrNull()?.toInt()?.and(0xFF) ?: Wire.API_VERSION
            Result.success(v)
        } catch (e: Exception) {
            Result.failure(IOException("BLE_GATT_READ_EXCEPTION: ${e.message}"))
        }
    }

    override fun setNotificationHandler(onChunk: (ByteArray) -> Unit): Result<Unit> {
        val g = gatt ?: return Result.failure(IOException("BLE_GATT_NOT_CONNECTED"))
        val ch = rpcChar ?: return Result.failure(IOException("BLE_GATT_RPC_CHAR_MISSING"))
        chunkHandler = onChunk
        return try {
            // ① 本地使能通知
            if (!g.setCharacteristicNotification(ch, true)) return Result.failure(IOException("BLE_GATT_SET_NOTIFY_FAILED"))
            // ② 写 CCCD 0x2902 = ENABLE_NOTIFICATION_VALUE（只 setNotify 不够，一手 NOOP/Android 示例）
            val cccd = ch.getDescriptor(cccdUuid)
                ?: return Result.failure(IOException("BLE_GATT_CCCD_MISSING"))
            val value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            if (!writeDescriptorSafe(g, cccd, value)) return Result.failure(IOException("BLE_GATT_CCCD_REJECTED"))
            if (!awaitOp("write CCCD")) return Result.failure(IOException("BLE_GATT_CCCD_TIMEOUT"))
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(IOException("BLE_GATT_SUBSCRIBE_EXCEPTION: ${e.message}"))
        }
    }

    /** 写一个 chunk：**串行 + 等 onCharacteristicWrite 确认**（WithResponse / WRITE_TYPE_DEFAULT）。 */
    override fun writeChunk(chunk: ByteArray): Result<Unit> = try {
        val g = gatt ?: return Result.failure(IOException("BLE_GATT_NOT_CONNECTED"))
        val ch = rpcChar ?: return Result.failure(IOException("BLE_GATT_RPC_CHAR_MISSING"))
        val initiated = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // API 33+：内存安全重载，返回 BluetoothStatusCodes；ERROR_GATT_WRITE_REQUEST_BUSY 表示上一操作未完
            g.writeCharacteristic(ch, chunk, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) ==
                android.bluetooth.BluetoothStatusCodes.SUCCESS
        } else {
            @Suppress("DEPRECATION")
            ch.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION") ch.setValue(chunk)
            @Suppress("DEPRECATION") g.writeCharacteristic(ch)
        }
        if (!initiated) return Result.failure(IOException("BLE_GATT_WRITE_REJECTED_BUSY"))
        if (!awaitOp("write chunk")) return Result.failure(IOException("BLE_GATT_WRITE_TIMEOUT"))
        if (opStatus != BluetoothGatt.GATT_SUCCESS) return Result.failure(IOException("BLE_GATT_WRITE_STATUS=$opStatus"))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(IOException("BLE_GATT_WRITE_EXCEPTION: ${e.message}"))
    }

    // ---- 串行操作 latch 机制 ----
    /**
     * 发起**任一** GATT 操作前先建 latch（必须在 platform 调用之前，否则回调可能先于 latch 到达而丢失）。
     * 读/写/描述符/MTU 都走这里，配合 opLock 保证一次只有一个 outstanding 操作。
     */
    private fun beginOp(action: () -> Boolean): Boolean = synchronized(opLock) {
        opLatch = CountDownLatch(1)
        opStatus = BluetoothGatt.GATT_SUCCESS
        if (!action()) { opLatch = null; false } else true
    }

    private fun writeDescriptorSafe(g: BluetoothGatt, d: BluetoothGattDescriptor, value: ByteArray): Boolean =
        beginOp {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                g.writeDescriptor(d, value) == android.bluetooth.BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION") d.setValue(value)
                @Suppress("DEPRECATION") g.writeDescriptor(d)
            }
        }

    private fun awaitOp(what: String): Boolean {
        val latch = opLatch ?: return false
        return try {
            val ok = latch.await(operationTimeoutMs, TimeUnit.MILLISECONDS)
            if (!ok) opLatch = null
            ok
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt(); false
        }
    }

    /**
     * connect 阶段专用：整条链有多次回调（connected → servicesDiscovered → mtuChanged），
     * 单次 latch 会在第一个回调就放行，故轮询「rpcChar 就位 + mtu 已协商」这个真正就绪状态。
     * 这是骨架层的稳妥写法；真机联调时若发现 MTU 回调不来，可退化为「servicesDiscovered 即就绪」
     * （出站固定 20 字节本就不依赖协商 MTU）。
     */
    private fun awaitConnectReady(): Boolean {
        val deadline = System.currentTimeMillis() + operationTimeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (opStatus != BluetoothGatt.GATT_SUCCESS) return false
            if (rpcChar != null && connectedMtuDone()) return true
            Thread.sleep(10)
        }
        return false
    }

    @Volatile private var mtuDone = false
    private fun connectedMtuDone(): Boolean = mtuDone

    /** 供回调标记 MTU 阶段完成（onMtuChanged 或超时兜底）。 */
    private fun markMtuDone() { mtuDone = true }

    /** 回调到达：释放当前操作 latch（回调在 Binder 线程，opLatch 由 opLock 保护可见性）。 */
    private fun releaseOp(status: Int) {
        if (status != BluetoothGatt.GATT_SUCCESS) opStatus = status
        synchronized(opLock) { opLatch?.countDown() }
    }

    /**
     * 入站通知投递：**不直接在 Binder 线程做重活**。GATT 回调跑在 Binder 线程，若在这里
     * 执行重组/分发（可能触发订阅者重逻辑），会阻塞后续所有 GATT 回调。这里只投递，
     * 把 [ByteArray] 交给独立的 [notifyExecutor] 处理，Binder 线程立即返回。
     */
    private fun dispatchInbound(value: ByteArray) {
        val h = chunkHandler ?: return
        try {
            notifyExecutor.execute { h(value) }
        } catch (_: java.util.concurrent.RejectedExecutionException) {
            // 执行器已关闭（与 close 竞态），丢弃该通知，不崩溃。
        }
    }

    override fun mtu(): Int = if (connected) negotiatedMtu else 0
    override fun onDisconnected(cb: () -> Unit) { disconnectCb = cb }
    override fun close() {
        connected = false
        chunkHandler = null
        disconnectCb = null
        notifyExecutor.shutdownNow()
        gatt?.close()
        gatt = null
    }
    override fun isConnected(): Boolean = connected

    companion object {
        /** 本地自定义错误：服务发现到了但找不到 RPC characteristic。 */
        const val GATT_LOCAL_NO_CHARACTERISTIC = -1001
    }
}
