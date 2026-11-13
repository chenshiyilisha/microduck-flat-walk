package io.microduck.app.core

/**
 * `robot.head` 参数 —— 一手 fanhao `duck-ipc-proto/src/lib.rs:2132-2145`（API_VERSION=40）。
 *
 * ```rust
 * #[serde(default, deny_unknown_fields)]
 * pub struct HeadParams {
 *     pub neck_pitch: f64, pub head_pitch: f64,
 *     pub head_yaw: f64,   pub head_roll: f64,
 * }
 * ```
 *
 * 🔴 `deny_unknown_fields` ⇒ 发出的 JSON **只能有这四个键**，多一个键就是 INVALID_PARAMS(-32602)。
 * 虽然 `#[serde(default)]` 允许少发（缺的按 0），但刻意**四键全发**：省略会让「回中」与
 * 「未指定」无法区分，也让 `neck_pitch` 这类姿态位依赖固件默认值，属于隐式契约。
 *
 * `robot.head` 是 **continuous intent**（lib.rs:610 注释 "Continuous; send as a notification"），
 * 与 `robot.move` 同型：走 [RobotSession.notify] 发无 id 帧，服务端不回响应。
 *
 * ⚠️ 通道限制（一手 `btd/src/route.rs` 的 `teleop_stays_off_the_radio` 测试）：
 * 该测试**逐项**断言 `RobotMove` 与 `RobotHead` 的 `upstream_for(&call) == None`，
 * 即 BLE 低频白名单把两者都挡在 radio 之外。⇒ 头部控制与驾驶一样，**不能走 BLE**，
 * 只能走 TCP relay / WebRTC datachannel。真机上和 `robot.move` 用同一条链路。
 */
data class HeadParams(
    val neckPitch: Double,
    val headPitch: Double,
    val headYaw: Double,
    val headRoll: Double,
) {
    /** 四键全发，键名逐字对齐 Rust 字段名（snake_case），不多不少。 */
    fun params(): Map<String, Any?> = mapOf(
        "neck_pitch" to neckPitch,
        "head_pitch" to headPitch,
        "head_yaw" to headYaw,
        "head_roll" to headRoll,
    )

    /** 全零 = 回中。head 意图不过期（见 [HeadController]），松手必须显式发这一帧。 */
    companion object {
        val NEUTRAL = HeadParams(0.0, 0.0, 0.0, 0.0)
    }
}
