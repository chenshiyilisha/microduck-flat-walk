package io.microduck.app.core

/**
 * 连续速度意图 —— 一比一映射 duck-ipc-proto 的 `MoveParams`。
 *
 * 一手依据：
 *  - fanhao `firmware/duck-ipc-proto/src/lib.rs:2120-2130`、B 代 `:1521-1532`
 *    ```rust
 *    #[serde(default, deny_unknown_fields)]
 *    pub struct MoveParams { vx: f64 /* 前进 m/s */, vy: f64 /* 左移 m/s */,
 *                            vyaw: f64 /* 偏航 rad/s，+ 为左转 */ }
 *    ```
 *  - `lib.rs:307-308`（B 代）/ `:608`（fanhao）：`ROBOT_MOVE = "robot.move"`，
 *    注释 "Velocity twist. Continuous; send as a notification."
 *
 * 🔴 `deny_unknown_fields` ⇒ [params] 只能有 vx/vy/vyaw 三个键，多一个键真固件回 -32602。
 * 这是「发出的 JSON 形状」必须被单测锁住的原因（CoreSelfTest [19]）。
 */
data class Twist(
    val vx: Double = 0.0,
    val vy: Double = 0.0,
    val vyaw: Double = 0.0,
) {
    fun isZero(): Boolean = vx == 0.0 && vy == 0.0 && vyaw == 0.0

    /** 恰好三键，顺序与 Rust struct 一致（顺序无关，但便于逐字节断言）。 */
    fun params(): Map<String, Any?> = linkedMapOf(
        "vx" to vx,
        "vy" to vy,
        "vyaw" to vyaw,
    )

    companion object {
        val ZERO = Twist()
    }
}
