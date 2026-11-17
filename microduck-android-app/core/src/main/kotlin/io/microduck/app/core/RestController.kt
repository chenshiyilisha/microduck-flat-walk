package io.microduck.app.core

/**
 * 一键休息 / 恢复站立 —— 纯 JVM（无 Android 依赖），可单测。
 *
 * ## 一手依据（ft1910 `duck-ipc-proto/src/lib.rs`，非自推）
 *  - `ROBOT_REST = "robot.rest"`（lib.rs:676）：坐下 → 缓入休息姿态 → 卸力 + 舵机重启，
 *    结束 limp、准备就绪等 `robot.init`。**无参**离散请求（`Call::RobotRest` 是单元变体，
 *    `#[serde(deny_unknown_fields)]` ⇒ 多带参数会被 INVALID_PARAMS=-32602 拒），
 *    响应 `IntentResult{accepted, reason}`（lib.rs:3738）。robotd `main.rs:5350`
 *    从不拒绝（"Never refused, like the shutdown it is the first half of"）。
 *  - `ROBOT_INIT = "robot.init"`（lib.rs:658）：上电 + ramp 到 home，是 rest 的逆操作。
 *  - `ROBOT_RELAX = "robot.relax"`（lib.rs:664）：只卸力不坐下（"The robot will collapse"），
 *    本类不暴露——一键休息的语义是完整的 rest 序列，不是裸卸力。
 *
 * ## ⚠️ BLE 不可达（必须如实回显，不造假）
 * `btd/src/route.rs:565-609` 的 BLE 放行白名单（`only_these_mutating_calls_are_reachable_over_ble`）
 * **不含** `robot.rest` / `robot.init` ⇒ BLE 通道下返回 `PERMISSION_DENIED=14`。
 * 调用方必须把失败原因原样回显，绝不把「没收到响应 / 权限被拒」渲染成「已休息」。
 *
 * ## 状态回显不靠本类
 * 休息是否生效看 `robot.state.safety.limp`（`StateSnapshot.limp`，一手
 * `robotd/src/main.rs` state 上报），本类只负责「发出去 + 解析应答」，不冒充状态判据。
 */
class RestController(private val session: RobotSession) {

    /** `IntentResult` 解析结果。`accepted` 缺字段时按 false（未确认接受），绝不假定 true。 */
    data class Outcome(val accepted: Boolean, val reason: String?)

    /** 发 `robot.rest`：让机器人坐下休息、卸力省电。 */
    fun requestRest(): Result<Outcome> = request(Method.ROBOT_REST)

    /** 发 `robot.init`：休息后恢复上电、回到 home 姿态。 */
    fun requestInit(): Result<Outcome> = request(Method.ROBOT_INIT)

    private fun request(method: String): Result<Outcome> = try {
        val r = session.call(method)
        val o = r.getOrNull()
        if (o == null) {
            Result.failure(r.exceptionOrNull() ?: IllegalStateException("REST_CALL_FAILED: $method"))
        } else {
            val acc = o.get("accepted")?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive
                ?.takeIf { it.isBoolean }?.asBoolean
            val reason = o.get("reason")?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive
                ?.takeIf { it.isString }?.asString
            // 缺 accepted 字段 ⇒ 响应结构不符契约 ⇒ 按「未确认接受」处理（UNVERIFIED != PASS）。
            Result.success(Outcome(acc == true, reason))
        }
    } catch (e: Exception) {
        Result.failure(e)
    }
}
