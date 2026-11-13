package io.microduck.app.core

/**
 * BLE GATT I/O 抽象 —— 把**唯一依赖 Android 的部分**隔离到接口后面，让 [BleTransport] 的
 * 协议编排（chunk 切分/重组/按 id 分流/断连）留在纯 Kotlin/JVM，可用 FakeGattLink 真测。
 *
 * ── 为什么需要这一层（一手依据）──
 * `robotd`/`btd` 的 GATT 面是「单一 characteristic 双向」：
 *   - service `6f5d2a10-…`、RPC `6f5d2a11-…`（duck-ble/src/gatt.rs:35/44）
 *   - client **写** NDJSON 请求到 RPC_UUID，并**订阅同一 UUID** 收响应/通知。
 * Android 的 `BluetoothGatt` 是回调式、且 **一次只允许一个 outstanding GATT 操作**；
 * 这些平台细节不该污染 core 的会话层，故收敛到本接口，实现方（app 模块）负责：
 *   1. connectGatt + onConnectionStateChange → discoverServices → onServicesDiscovered；
 *   2. **先 read 一次 RPC_UUID**（促成加密配对 + 拿 API_VERSION，gatt.rs:44-56 明说这是契约、
 *      不是可选项），再 subscribe；
 *   3. setCharacteristicNotification(true) **且**写 CCCD `0x2902` ENABLE_NOTIFICATION_VALUE
 *      （一手：NOOP Android Port Guide / Android 官方示例，只 setNotify 不够）；
 *   4. **串行化写**：把每次 [writeChunk] 变成「writeCharacteristic → 等 onCharacteristicWrite
 *      回调 → 再处理下一个」；Android GATT 一次一个操作，不能并发（一手：Polidea react-native-ble-plx
 *      wiki、capacitor-community/bluetooth-le#751、NOOP ANDROID.md、bota-dev 真实 bug 报告
 *      "writeCharacteristic() - prior command is not finished"）。
 *   5. write type 用 **WRITE_TYPE_DEFAULT（WithResponse / acknowledged）**：fanhao fork（非原厂）
 *      duckctl/src/main.rs:2075 "**Acknowledged writes, and that is not a detail.** An ATT Write
 *      Command (WithoutResponse) carries no reply, so a refusal — for insufficient encryption —
 *      is invisible: the request silently never arrives and the client waits out its timeout."。
 *      绝不能为「快」改用 NoResponse —— 加密不足的拒绝会变成隐形超时。
 *
 * [writeChunk] 的契约是**串行且已确认**：返回 Result.success 表示这一 chunk 已被 GATT 层确认
 * （WithResponse 的 onCharacteristicWrite(status=GATT_SUCCESS)）；因此 [BleTransport] 可以逐个
 * 调用而不必自己排队。实现方若违反（并发写/未等回调就返回）会导致后续写静默失败。
 */
interface GattLink {
    /** 建立 GATT 链路并发现服务、促成加密配对。返回 negotiated ATT MTU（失败返回 failure）。 */
    fun connect(): Result<Int>

    /**
     * read 一次 RPC_UUID，返回固件报的 API_VERSION（促成配对的契约动作，gatt.rs:44）。
     * 用 count 与 [BleTransport] 的 Wire.API_VERSION 比对；版本 skew 不致命（无 daemon 因版本拒答，
     * 靠 METHOD_NOT_FOUND 降级），但记录以便 UI 提示。
     */
    fun readApiVersion(): Result<Int>

    /** 订阅 RPC_UUID 的通知（含写 CCCD）。[onChunk] 每收到一个 notification payload 回调一次。 */
    fun setNotificationHandler(onChunk: (ByteArray) -> Unit): Result<Unit>

    /**
     * 写一个 chunk（≤ [BleChunkCodec.MAX_ATTRIBUTE_VALUE]，但 client 侧固定用 FLOOR_MTU=20）。
     * **实现方必须串行 + 等 onCharacteristicWrite 确认**，见类注释第 4/5 条。
     */
    fun writeChunk(chunk: ByteArray): Result<Unit>

    /** 当前 negotiated ATT MTU（connect 成功后的值；0=未连接/floor）。 */
    fun mtu(): Int

    /** 注册断连回调（onConnectionStateChange → STATE_DISCONNECTED）。 */
    fun onDisconnected(cb: () -> Unit)

    /** 关闭 GATT client（gatt.close()）。 */
    fun close()

    /** 当前是否连着。 */
    fun isConnected(): Boolean
}
