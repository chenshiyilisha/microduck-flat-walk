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
import android.util.Log
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
 *  8. 🔴 `requestMtu` 是**可选优化，不是建链前置**（一手 Android 平台文档 `connect-gatt-server`
 *     只要求 connect → onConnectionStateChange → discoverServices → onServicesDiscovered；MTU 不在
 *     必需链上，出站固定 20B 也不依赖协商 MTU）。🔴 **2026-11-15 真机修正**：MTU 不能再在
 *     `onServicesDiscovered` 里 fire-and-forget——那样它会作为 untracked outstanding 操作与后续
 *     `readApiVersion`/hello 写竞争 Android「单 outstanding 操作」约束，导致首条 hello 写被
 *     `ERROR_GATT_WRITE_REQUEST_BUSY` 拒绝（真机实测）。改为由 `BleTransport.connect()` 显式调
 *     `GattLink.requestMtu()`，经 `beginOp/awaitOp` 串行发出、等 `onMtuChanged` 回调后再放行协议帧；
 *     失败/超时非致命（保持 `FLOOR_MTU`）。
 *
 * 所有 platform I/O 回调都在 Android 的 Binder 线程上触发；本类用 latch 把回调式 API 适配成
 * [GattLink] 的同步阻塞契约（与 TcpTransport.request 同样的「阻塞等信号」思路）。
 */
@SuppressLint("MissingPermission") // BLUETOOTH_CONNECT 由宿主 Activity 在运行时申请（见 Manifest）
class AndroidBleGattLink(
    private val context: Context,
    private val device: BluetoothDevice,
    /** 建链总超时。真机首连含扫描停止 + 配对协商，3 s 偏紧；给 12 s（不等于降低判据强度）。 */
    private val operationTimeoutMs: Long = 12_000,
    /** MTU 协商超时：可选优化，回调不来也不致命，给 2 s 即放行后续协议帧（不等于降低判据强度）。 */
    private val mtuTimeoutMs: Long = 2_000,
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
    /**
     * 当前在飞的 GATT 操作标签（"connect"/"read"/"MTU"/"cccd"/"write"）。
     * 🔴 2026-11-15 真机根因修复：Android 的 GATT 回调（尤其 [onMtuChanged]）**不带 op id**，
     * 且在重连（栈缓存了先前协商的 MTU）时会于 [onConnectionStateChange] 之后**自动触发**，
     * 并非只响应你发的 requestMtu。旧 `releaseOp(status)` 不分标签直接 countDown 当前 latch，
     * 错位回调会**提前释放错误的 latch** → 上层误以为在飞 op 已完成 → 抢发下一条 → 平台报
     * `ERROR_GATT_WRITE_REQUEST_BUSY`（真机实测 hello 写被拒）。改为按 `opKind` 路由：只有
     * 回调的标签与当前在飞 op 匹配才释放；错位回调被忽略（写 STRAY 日志供排查）。
     */
    @Volatile private var opKind: String? = null

    // 🔴 诊断：GATT 操作/回调时间戳环形缓冲，定位「hello 写 BUSY」时哪个 op 仍 outstanding。
    private val gattTrace = ArrayDeque<String>()
    /** 最近一次建链失败原因（TIMEOUT/STATUS=n/NO_CHAR），成功清空。debug 通道可读。 */
    @Volatile private var lastConnectFailure: String = ""

    private fun trace(s: String) {
        val t = (System.currentTimeMillis() % 100000) / 1000.0f
        synchronized(gattTrace) {
            gattTrace.addLast("%.2f $s".format(t))
            while (gattTrace.size > 48) gattTrace.removeFirst()
        }
        Log.i("DuckGatt", s)
    }

    /**
     * 建链失败收尾：先记录轨迹，再 close 当前 client 并置空（官方 close() 语义），
     * 同时清掉在飞 latch 状态，保证下次 connect() 从干净状态开始。
     */
    private fun abortConnect(g: BluetoothGatt) {
        trace("ABORT_CONNECT lastFailure=$lastConnectFailure")
        synchronized(opLock) {
            opLatch?.countDown()
            opLatch = null
            opKind = null
        }
        runCatching { g.close() }
        if (this.gatt === g) this.gatt = null
        rpcChar = null
        connected = false
    }

    /** 只读诊断：GATT 轨迹 + 最近失败原因 + 当前状态，供 debug-only AI 通道导出。 */
    override fun diagnostics(): String = synchronized(gattTrace) {
        buildString {
            append("lastConnectFailure=$lastConnectFailure")
            append("; connected=$connected")
            append("; negotiatedMtu=$negotiatedMtu")
            append("; gattAlive=").append(gatt != null)
            append("; opKind=").append(opKind ?: "none")
            gattTrace.forEach { append("\n").append(it) }
        }
    }

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
            releaseOp("connect", status)
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                val svc = g.getService(serviceUuid)
                val ch = svc?.getCharacteristic(rpcUuid)
                if (ch == null) {
                    opStatus = GATT_LOCAL_NO_CHARACTERISTIC
                    releaseOp("connect", status)
                    return
                }
                rpcChar = ch
                // 🔴 2026-11-15：requestMtu 移出此处。原 fire-and-forget 调 requestMtu 未走 beginOp/awaitOp，
                // 会在 connect() 返回后仍 outstanding，与后续协议帧竞争「单 outstanding 操作」→ 首条 hello 写
                // 被 ERROR_GATT_WRITE_REQUEST_BUSY 拒绝（真机实测）。现改为 BleTransport.connect() 显式调
                // 本类的 requestMtu()（经 beginOp/awaitOp 串行），确保无 outstanding op 再发协议帧。
            } else {
                opStatus = status
            }
            releaseOp("connect", status)
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            // 可选优化：只更新协商值，不再作为 connect() 的就绪条件（见类注释第 8 条）。
            // 🔴 关键：onMtuChanged **不带 op id**，重连时栈会**自动**触发（缓存 MTU），并非只响应你发的
            // requestMtu。若此刻在飞的是 CCCD/hello 写，错位回调会误释放其 latch → 抢发 → BUSY。
            // 故仅当当前在飞 op 确为 "MTU" 时才释放；否则忽略（写 STRAY 供排查），绝不碰其它 latch。
            if (status == BluetoothGatt.GATT_SUCCESS) negotiatedMtu = mtu
            trace("onMtuChanged mtu=$mtu status=$status pending=${opKind ?: "none"}")
            releaseOp("MTU", status)
        }

        override fun onCharacteristicRead(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            if (characteristic.uuid == rpcUuid) opReadValue = value
            releaseOp("read", status)
        }

        @Deprecated("API 33 以下兼容回调")
        override fun onCharacteristicRead(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (characteristic.uuid == rpcUuid) opReadValue = characteristic.value
            releaseOp("read", status)
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            releaseOp("write", status)   // 关键：每个 write 都有回调（官方 "in response to every writeCharacteristic call"）
        }

        override fun onDescriptorWrite(g: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
            releaseOp("cccd", status)   // CCCD 写入完成 ⇒ 订阅真正生效
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
            opKind = "connect"
            rpcChar = null
        }
        val g = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        } else {
            @Suppress("DEPRECATION") device.connectGatt(context, false, gattCallback)
        }
        gatt = g
        // 等链路建立 + 服务发现 + MTU 协商完成（以 rpcChar 就位为准，失败会置 opStatus）
        // 🔴 2026-11-21 真机根因修复：以下任一失败分支都**必须 close()** 再返回 failure。
        // 官方 BluetoothGatt.close()：「Application should call this method as early as possible
        // after it is done with this GATT client」。原实现只 return failure 不 close，栈内旧
        // client 仍占着该 device；会话层随即按指数退避重连又 connectGatt() 新建 client，
        // 多个 client 叠加 → 后续连接全部失败（真机 logcat 十几次重复 connect、掉线连不上）。
        // 断链回调路径（onConnectionStateChange→DISCONNECTED）本就有 g.close()，唯独建链失败
        // 路径漏了，这里补齐；gatt 置 null 保证下次 connect 干净建链。
        if (!awaitConnectReady()) {
            lastConnectFailure = "TIMEOUT"
            abortConnect(g)
            return Result.failure(IOException("BLE_GATT_CONNECT_TIMEOUT"))
        }
        if (opStatus != BluetoothGatt.GATT_SUCCESS || rpcChar == null) {
            lastConnectFailure = "STATUS=$opStatus"
            abortConnect(g)
            return Result.failure(IOException("BLE_GATT_CONNECT_STATUS=$opStatus"))
        }
        if (rpcChar == null) {
            lastConnectFailure = "NO_CHAR"
            abortConnect(g)
            return Result.failure(IOException("BLE_GATT_RPC_CHAR_MISSING"))
        }
        lastConnectFailure = ""
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
            if (!beginOp("read") { g.readCharacteristic(ch) }) return Result.failure(IOException("BLE_GATT_READ_REJECTED"))
            if (!awaitOp("read RPC_UUID")) return Result.failure(IOException("BLE_GATT_READ_TIMEOUT"))
            // RPC_UUID 首字节即 API_VERSION（gatt.rs:44 "read it once for the API version"）；
            // 具体编码由固件定，这里取单字节无符号值，失败则回退 Wire.API_VERSION 让上层继续握手。
            val v = opReadValue?.firstOrNull()?.toInt()?.and(0xFF) ?: Wire.API_VERSION
            Result.success(v)
        } catch (e: Exception) {
            Result.failure(IOException("BLE_GATT_READ_EXCEPTION: ${e.message}"))
        }
    }

    /**
     * 协商 ATT MTU（可选优化）。🔴 2026-11-15 真机修正：原实现在 [onServicesDiscovered] 里
     * fire-and-forget 调 requestMtu（未走 [beginOp]/[awaitOp]），该请求在 connect() 返回后仍
     * outstanding，与后续 readApiVersion/hello 写竞争 Android「单 outstanding 操作」约束 →
     * 首条 hello 写被 ERROR_GATT_WRITE_REQUEST_BUSY 拒绝（真机实测）。现经 [beginOp]/[awaitOp]
     * 串行发出，等 onMtuChanged 回调后才放行后续协议帧。失败/超时非致命：出站固定 20B 不依赖协商 MTU。
     */
    override fun requestMtu(): Result<Unit> = try {
        val g = gatt ?: return Result.failure(IOException("BLE_GATT_NOT_CONNECTED"))
        if (!beginOp("MTU") { g.requestMtu(517) }) return Result.failure(IOException("BLE_GATT_MTU_REJECTED"))
        // 超时（回调没来）非致命：保持 FLOOR_MTU，出站不受影响。
        awaitOp("request MTU", mtuTimeoutMs)
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(IOException("BLE_GATT_MTU_EXCEPTION: ${e.message}"))
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
        // 🔴 **必须走 [beginOp] 建 latch**：否则 [onCharacteristicWrite] 回调无 latch 可释放，
        // [awaitOp] 拿到 null latch 会**立即返回 false** → 被误报成 "WRITE_TIMEOUT"（真机实测：hello 写
        // 被栈接受 initiated=true，但回调永远等不到 → 秒超时）。beginOp 同时保证「单 outstanding 操作」。
        val initiated = beginOp("write") {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                // API 33+：内存安全重载，返回 BluetoothStatusCodes；ERROR_GATT_WRITE_REQUEST_BUSY 表示上一操作未完
                g.writeCharacteristic(ch, chunk, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) ==
                    android.bluetooth.BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                ch.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                @Suppress("DEPRECATION") ch.setValue(chunk)
                @Suppress("DEPRECATION") g.writeCharacteristic(ch)
            }
        }
        if (!initiated) {
            trace("WRITE_BUSY kind=write pending=${opKind ?: "none"}")
            return Result.failure(IOException("BLE_GATT_WRITE_REJECTED_BUSY"))
        }
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
    private fun beginOp(kind: String, action: () -> Boolean): Boolean = synchronized(opLock) {
        opLatch = CountDownLatch(1)
        opStatus = BluetoothGatt.GATT_SUCCESS
        opKind = kind
        trace("BEGIN $kind")
        if (!action()) { opLatch = null; opKind = null; false } else true
    }

    private fun writeDescriptorSafe(g: BluetoothGatt, d: BluetoothGattDescriptor, value: ByteArray): Boolean =
        beginOp("cccd") {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                g.writeDescriptor(d, value) == android.bluetooth.BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION") d.setValue(value)
                @Suppress("DEPRECATION") g.writeDescriptor(d)
            }
        }

    private fun awaitOp(what: String, timeoutMs: Long = operationTimeoutMs): Boolean {
        val latch = opLatch ?: return false
        return try {
            val ok = latch.await(timeoutMs, TimeUnit.MILLISECONDS)
            if (!ok) {
                trace("TIMEOUT $what pending=${opKind ?: "none"}")
                synchronized(opLock) { opLatch = null; opKind = null }
            }
            ok
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt(); false
        }
    }

    /**
     * connect 阶段专用：就绪判据 = **RPC characteristic 就位**（`onServicesDiscovered` 里赋值）。
     * MTU 回调是可选优化，不阻塞建链（见类注释第 8 条）：它到了就更新 `negotiatedMtu`，
     * 不来也不影响出站（固定 20B）。
     *
     * 仍带两层硬守卫：① `opStatus` 一旦非 GATT_SUCCESS 立即失败；② 超时必失败，
     * 不会无限等。⇒ 修的是「把可选回调当必需」，不是放宽或取消判据。
     */
    private fun awaitConnectReady(): Boolean {
        val deadline = System.currentTimeMillis() + operationTimeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (opStatus != BluetoothGatt.GATT_SUCCESS) return false
            if (rpcChar != null) return true
            Thread.sleep(10)
        }
        return false
    }

    /**
     * 回调到达：🔴 **按 `opKind` 路由**，只有标签匹配的回调才释放对应 latch。
     * 错位回调（重连时栈自动触发的 onMtuChanged、重复 onConnectionStateChange 等）
     * 不再能 countDown 当前在飞 op 的 latch —— 这正是一手 BUSY 错误的根因（详见 `opKind` 注释）。
     * 返回 true 表示本回调匹配并释放了在飞 op。
     */
    private fun releaseOp(kind: String, status: Int): Boolean = synchronized(opLock) {
        if (opKind != kind) {
            trace("STRAY $kind ignored (pending=${opKind ?: "none"})")
            false
        } else {
            if (status != BluetoothGatt.GATT_SUCCESS) opStatus = status
            opLatch?.countDown()
            opLatch = null
            opKind = null
            trace("RELEASE $kind status=$status")
            true
        }
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
