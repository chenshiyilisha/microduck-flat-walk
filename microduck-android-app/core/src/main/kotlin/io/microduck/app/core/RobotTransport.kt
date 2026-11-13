package io.microduck.app.core

/**
 * 传输抽象 —— P0 的地基。四个后端实现同一接口，上层 RobotSession + 所有屏幕只面对它：
 *
 *   BleTransport      真机（P0 阶段 D）：GATT 515 / NDJSON 分帧 / PIN 认证
 *   TcpTransport      仿真+relay（P0 阶段 C）：连 PC 侧 unix→TCP relay（:7788）
 *   WebRtcTransport   驾驶+视频（P1/P2）：mediad:8443 control datachannel
 *   MockTransport     无后端自测（P0 阶段 A）：内存 canned + 可编程故障注入
 *
 * 之所以能换后端：四者收发的是**同一份 NDJSON JSON-RPC 2.0 行协议**（见 Wire.kt 注释）。
 * 这是 **Pollen 原厂**的设计意图（同一套 serde 消息类型复用在 BLE / WebRTC 数据通道上），不是我们臆断。
 *
 * 接口刻意用**同步阻塞式** request/connect（不用 suspend/coroutines）：
 *  - Mock / 会话层是纯内存状态机，无需挂起，纯 kotlinc + JDK17 即可真编译真测（零外部依赖）；
 *  - 真实 I/O 后端（Tcp/BLE）在 Android 上跑在后台线程，内部用 等待通知/CompletableFuture 封装成阻塞式，
 *    调用方用 Dispatchers.IO 切线程即可 —— 标准做法，不损失异步能力。
 */
interface RobotTransport {
    val kind: TransportKind

    /** 建立物理/逻辑链路。失败返回 Result.failure，不抛。 */
    fun connect(target: ConnectTarget): Result<Unit>

    /**
     * 发一条 NDJSON 请求行，等待对应 id 的响应行（阻塞直到响应/超时/断连）。
     * 传输层负责分帧/重组（BLE 512B chunk、TCP 行、WebRTC datachannel 消息），
     * 对上层暴露「一行进、一行出」。
     *
     * 🔴 **notification 契约**（B 代 `robotd/src/main.rs:3483-3489`）：
     * 行里**没有 id** 时是 JSON-RPC notification，服务端按 spec **不回响应**，
     * `robot.move` / `robot.pose` 这类 50 Hz 连续意图就走这条路。
     * 因此实现必须「写出后立刻返回 `Result.success`、绝不等待响应」——
     * [TcpTransport]、[BleTransport] 已如此；`RobotSession.notify()` 依赖这条契约。
     */
    fun request(line: String): Result<String>

    /**
     * 订阅服务器推送的通知流（如 robot.state / robot.startup）。
     * 返回 Disposable；**断连后该订阅即失效**，会话层负责重连后重订阅。
     */
    fun subscribe(onFrame: (String) -> Unit): Disposable

    /** 注册断连回调。会话层据此触发重连。注意：回调可能在 transport 的线程上触发，
     *  重连动作要丢到工作线程，别阻塞回调线程。 */
    fun onDisconnected(cb: () -> Unit): Disposable

    /** 主动关闭，释放资源。 */
    fun close()

    /** 当前是否连着（供会话层/UI 判断）。 */
    fun isConnected(): Boolean
}

enum class TransportKind { BLE, TCP, WEBRTC, MOCK }

/** 连接目标。不同后端只用其中一部分字段。 */
sealed class ConnectTarget {
    /** 仿真/relay：PC 上 unix→TCP relay 的地址。 */
    data class Tcp(val host: String, val port: Int) : ConnectTarget()
    /** 真机 BLE：按 serial 找回设备（地址会变，serial 不变）。 */
    data class Ble(val serial: String) : ConnectTarget()
    /** WebRTC：mediad 信令主机 + 端口。 */
    data class WebRtc(val host: String, val port: Int = 8443) : ConnectTarget()
    /** Mock：无需目标。 */
    object Mock : ConnectTarget()
}

/** 订阅/回调句柄，统一 dispose 语义。 */
fun interface Disposable {
    fun dispose()
}
