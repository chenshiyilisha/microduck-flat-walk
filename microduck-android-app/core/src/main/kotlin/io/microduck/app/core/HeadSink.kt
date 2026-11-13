package io.microduck.app.core

/**
 * 头部意图输出通道。与 [DriveSink] 平行但**刻意不复用**：两者是固件里两个独立 intent slot
 * （`robotd/src/intents.rs:7-9` "Twist and head are separate slots on purpose"），
 * 合并会让「头写不刷新 twist deadman」这条约束在类型层面消失。
 */
interface HeadSink {
    val name: String
    fun send(p: HeadParams): Result<Unit>
    fun close()
}

/**
 * `robot.head` JSON-RPC **notification**（无 id、无响应）。
 *
 * 一手依据：
 *  - fanhao `duck-ipc-proto/src/lib.rs:610` `ROBOT_HEAD = "robot.head"`，
 *    注释 "Head joint targets. Continuous; send as a notification."
 *  - `robotd/src/main.rs:4795-4796` `Call::RobotHead(p) => intents.set_head([...])`。
 *  - 无 id 帧不回响应：B 代 `main.rs:3483-3489`（同型契约，见 [RobotSession.notify]）。
 *
 * ⚠️ **BLE 不可用**：`btd/src/route.rs` 的 `teleop_stays_off_the_radio` 测试把
 * `RobotMove` 和 `RobotHead` 一起列为 `upstream_for == None`（PERMISSION_DENIED=14）。
 * 与 [JsonRpcDriveSink] 完全同因：真机上必须走 netpad/WebRTC/TCP relay。
 */
class JsonRpcHeadSink(private val session: RobotSession) : HeadSink {
    override val name: String = "JSON-RPC robot.head"

    override fun send(p: HeadParams): Result<Unit> =
        session.notify(Method.ROBOT_HEAD, p.params())

    override fun close() { /* 会话生命周期由 RobotSession 拥有，sink 不关链路 */ }
}
