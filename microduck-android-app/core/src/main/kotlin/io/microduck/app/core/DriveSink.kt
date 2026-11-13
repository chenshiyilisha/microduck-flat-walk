package io.microduck.app.core

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * 一次驾驶输出。
 *
 * 为什么要同时带物理量和归一化摇杆：两个通道的语义不同，且都来自同一根摇杆——
 *  - [JsonRpcDriveSink] 要物理速度 `robot.move`（m/s、rad/s，Twist）；
 *  - [NetpadDriveSink] 要游戏手柄轴 netpad（-1..1），**速度由板上 R17 映射决定**。
 * 若 sink 只收 Twist，netpad 端就得反推上限；若只收摇杆，JSON-RPC 端就得复制一份映射。
 * 两者都错 ⇒ 一次输出两种表示，由各自 sink 取用（单一数据源仍是 [DriveController.map]）。
 */
data class DriveCommand(
    val twist: Twist,
    /** 左摇杆 X，-1..1，右为正。 */
    val lx: Double,
    /** 左摇杆 Y，-1..1，**上为正**（wire.rs:78 "up positive"）。 */
    val ly: Double,
)

/** 驾驶输出通道。R4（netpad 预开 vs WebRTC/JSON-RPC）待拍板 ⇒ 两条都实现，运行时切换。 */
interface DriveSink {
    val name: String
    fun send(cmd: DriveCommand): Result<Unit>
    fun close()
}

/**
 * 通道 A：`robot.move` JSON-RPC **notification**（无 id、无响应）。
 *
 * 一手依据：
 *  - fanhao `duck-ipc-proto/src/lib.rs:608` `ROBOT_MOVE = "robot.move"`；B 代 `:308`
 *    注释 "Velocity twist. Continuous; **send as a notification**."
 *  - B 代 `robotd/src/main.rs:3483-3489`：
 *    "Notifications get no reply, per the spec. Continuous intents arrive this way —
 *     at 50 Hz a response per message would be pure overhead"；无 id 时直接
 *    `apply_intent(&intents, &call)`，其中 `RobotMove(p) => intents.set_twist([p.vx,p.vy,p.vyaw])`。
 *  - `apply_intent` 注释（:3522）明确 request 路径（带 id）也接受，即跨版本兼容。
 *
 * ⚠️ **BLE 后端不能用**：fanhao BLE 低频白名单把 `robot.move` 挡在外面
 *    （Wire.kt `RpcCode.PERMISSION_DENIED=14` 注释）。驾驶在真机上走 netpad 或 WebRTC，
 *    本 sink 用于 TCP 仿真 / 真固件活体验证 / WebRTC datachannel。
 */
class JsonRpcDriveSink(private val session: RobotSession) : DriveSink {
    override val name: String = "JSON-RPC robot.move"

    override fun send(cmd: DriveCommand): Result<Unit> =
        session.notify(Method.ROBOT_MOVE, cmd.twist.params())

    override fun close() { /* 会话生命周期由 RobotSession 拥有，sink 不关链路 */ }
}

/**
 * 通道 B：fanhao UDP 手柄（netpad）——28 字节 datagram 发到板上 :4210。
 *
 * 一手依据：`firmware/docs/robot/udp-pad.md`（默认端口/timeout/预开要求）、
 * `firmware/padd/src/udp/wire.rs`（见 [NetpadWire]）。
 *
 * 🔴 关键行为约束（udp-pad.md / wire.rs:8）：
 *  - 每个包是**全量状态**，丢了不用重传；
 *  - 客户端静默超过 `timeout_ms=250` ⇒ `padd` 断开，`robotd` deadman(500ms) 归零速度；
 *    ⇒ [DriveController] 必须持续心跳重发，不能只在摇杆变化时发一次。
 *  - 该通道**默认关**、无 JSON-RPC 开关，需板上 `service.sh netpad on`（R4）。
 *  - 速度方向的最终解释权在板上 R17 映射；`udp-pad.md` 明说「若推前杆却倒退，
 *    客户端加 `--invert-y`」⇒ UI 必须提供反转开关，**不得在客户端硬编码方向**。
 */
class NetpadDriveSink(
    private val host: String,
    private val port: Int = NetpadWire.DEFAULT_PORT,
    private val clock: () -> Long = System::currentTimeMillis,
) : DriveSink {
    override val name: String = "UDP netpad $host:$port"

    private val lock = Any()
    private var seq = 0L
    private var socket: DatagramSocket? = null
    private var closed = false

    override fun send(cmd: DriveCommand): Result<Unit> = try {
        val packet = synchronized(lock) {
            if (closed) throw IllegalStateException("NETPAD_SINK_CLOSED")
            NetpadWire.fromAxes(
                seq = seq++,
                tMs = clock(),
                sticks = doubleArrayOf(cmd.lx, cmd.ly, 0.0, 0.0),
                triggers = doubleArrayOf(0.0, 0.0),
                buttons = NetpadWire.Buttons.NONE,
            )
        }
        val bytes = packet.encode()
        val target = InetAddress.getByName(host)
        val s = synchronized(lock) {
            if (socket == null) socket = DatagramSocket()
            socket!!
        }
        s.send(DatagramPacket(bytes, bytes.size, target, port))
        Result.success(Unit)
    } catch (e: Exception) {
        Result.failure(e)
    }

    override fun close() = synchronized(lock) {
        closed = true
        socket?.close()
        socket = null
    }
}
