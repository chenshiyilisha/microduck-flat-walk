package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * `robot.state` 通知帧的安全解析 —— 一手字段来自 fanhao
 * `duck-ipc-proto/src/lib.rs:3721-3800`（`RobotState`）与 `:3982-4020`（`MoveState` /
 * `SafetyState` / `LoopState`）。
 *
 * 🔴🔴 **空数组 ≠ 零**（本文件存在的首要理由，与 [HealthSnapshot] 同源但更狠）：
 *  - `RobotState::velocities` 注释（:3754-3766）：「Empty means *not reported*, which is not
 *    the same as a robot at rest — **a client must not render it as zero velocity**」；
 *  - `RobotState::currents_ma` 注释（:3776-3783）：「empty is *not reported*, never zero load」；
 *  - `LoopState::hz`（:4014-4018）：「Zero until the first window closes」——0 Hz 是
 *    「首个统计窗口未闭合」，**不是**「控制环停了」；
 *  - `MoveState::limited_by`（:3982-3990）：「Empty when the command went through untouched」
 *    ——这里空是「未限幅」，与上面「未上报」语义相反，**不能统一处理**。
 * ⇒ 所有可选量一律 nullable，数组区分 `null`（字段缺失）与 `empty`（明确未上报/无限幅），
 *   UI 渲染 null/empty 为「— 未读到」，**绝不用 0 兜底**。
 *
 * 🔑 为什么同时保留 `requested` 和 `applied`：`RobotState` 类注释（:3723-3726）明写
 * 「**It reports what was refused, not just what happened.** Safety clamps things constantly,
 * and a client watching the robot ignore its command with no explanation cannot tell a bug
 * from a limit.」⇒ 状态面板要显示「命令 vs 实际 + 限幅原因」，只显示实际速度等于掩盖故障。
 *
 * 版本 skew：B 代 API16 与 fanhao API40 的 `RobotState` 字段集不完全相同（lib.rs 明说
 * 逐方法降级），故一律 null-safe、绝不 typed 反序列化。
 */
data class StateSnapshot(
    val t: Double?,
    val policy: String?,
    /** 请求的 [vx, vy, vyaw]；null = 帧里没有该块。 */
    val requested: List<Double>?,
    /** 实际生效的 [vx, vy, vyaw]；null = 帧里没有该块。 */
    val applied: List<Double>?,
    /** 限幅原因；空 = 命令未被限幅（语义是「没有限幅」，不是「没读到」）。 */
    val limitedBy: List<String>,
    /** [neck_pitch, head_pitch, head_yaw, head_roll]，弧度。 */
    val head: List<Double>?,
    val fallen: Boolean?,
    val limp: Boolean?,
    /** 控制环实测速率；0 表示首个窗口未闭合，不是停环。 */
    val loopHz: Double?,
    val missedTicks: Long?,
    /** 舵机电流 mA；null / empty 都表示「未上报」，不是 0 mA。 */
    val currentsMa: List<Double>?,
    val odomYaw: Double?,
) {
    /**
     * 是否收到了任何可显示的字段（用于区分「无帧」与「帧里字段都缺」）。
     * 🔴 不能用 `listOfNotNull(...).isNotEmpty()`：`limitedBy` 是空 List（非 null），
     *    会把「一帧全空」误判成「有数据」⇒ 恒真断言。这里逐项显式判非空。
     */
    fun hasAny(): Boolean = t != null || policy != null || requested != null || applied != null ||
        head != null || fallen != null || limp != null || loopHz != null ||
        missedTicks != null || !currentsMa.isNullOrEmpty() || odomYaw != null ||
        limitedBy.isNotEmpty()

    /** 循环速率：0 是「窗口未闭合」，必须如实说明，不能渲染成 0 Hz 停环。 */
    fun loopText(): String {
        val hz = loopHz ?: return "— 未读到"
        if (hz <= 0.0) return "0 Hz（首个统计窗口未闭合，非停环）"
        return "%.1f Hz".format(hz) + (missedTicks?.let { " · 超时 %d".format(it) } ?: "")
    }

    /** 速度：缺失不写 0。 */
    fun velocityText(): String {
        val r = requested?.takeIf { it.size >= 3 }
        val a = applied?.takeIf { it.size >= 3 }
        if (requested == null && applied == null) return "— 未读到"
        val fmt = { v: List<Double>? -> v?.let { "(%.2f, %.2f, %.2f)".format(it[0], it[1], it[2]) } ?: "—" }
        return buildString {
            append("命令 ").append(fmt(r)).append(" → 实际 ").append(fmt(a))
            if (limitedBy.isNotEmpty()) append("  ⚠ 限幅: ").append(limitedBy.joinToString(","))
            else append("  · 未限幅")
        }
    }

    /** 电流：空数组 = 未上报，绝不显示零负载。 */
    fun currentText(): String {
        val c = currentsMa
        if (c.isNullOrEmpty()) return "— 未上报（非零负载）"
        val max = c.maxOrNull() ?: return "— 未上报（非零负载）"
        return "峰值 %.0f mA / %d 关节".format(max, c.size)
    }

    fun summary(): String = buildString {
        append("策略 ").append(policy ?: "— 未读到")
        append(" · 时间 ").append(t?.let { "%.2f s".format(it) } ?: "—")
        appendLine()
        append("控制环 ").append(loopText())
        appendLine()
        append(velocityText())
        appendLine()
        append("安全 ").append(
            when {
                fallen == null && limp == null -> "— 未读到"
                else -> buildList {
                    fallen?.let { add(if (it) "⚠ 已摔倒" else "站立") }
                    limp?.let { if (it) add("⚠ 已卸力") }
                }.joinToString(" · ").ifEmpty { "正常" }
            },
        )
        appendLine()
        append("头部 ").append(
            head?.takeIf { it.size == 4 }
                ?.let { "[%.2f, %.2f, %.2f, %.2f] rad".format(it[0], it[1], it[2], it[3]) }
                ?: "— 未读到",
        )
        appendLine()
        append("电流 ").append(currentText())
        append(" · 航向 ").append(odomYaw?.let { "%.1f°".format(Math.toDegrees(it)) } ?: "—")
    }

    companion object {
        fun from(o: JsonObject): StateSnapshot = StateSnapshot(
            t = num(o, "t"),
            policy = str(o, "policy"),
            requested = arr(obj(o, "move"), "requested"),
            applied = arr(obj(o, "move"), "applied"),
            limitedBy = strings(obj(o, "move"), "limited_by"),
            head = arr(o, "head"),
            fallen = bool(obj(o, "safety"), "fallen"),
            limp = bool(obj(o, "safety"), "limp"),
            loopHz = num(obj(o, "loop"), "hz"),
            missedTicks = lng(obj(o, "loop"), "missed"),
            currentsMa = arr(o, "currents_ma")?.takeIf { it.isNotEmpty() },
            odomYaw = num(obj(o, "odom"), "yaw"),
        )

        private fun obj(o: JsonObject?, key: String): JsonObject? = try {
            o?.get(key)?.takeIf { it.isJsonObject }?.asJsonObject
        } catch (_: Exception) { null }

        private fun primitive(o: JsonObject?, key: String) = try {
            o?.get(key)?.takeIf { it.isJsonPrimitive && !it.isJsonNull }
        } catch (_: Exception) { null }

        private fun str(o: JsonObject?, key: String): String? = try {
            primitive(o, key)?.asString
        } catch (_: Exception) { null }

        private fun num(o: JsonObject?, key: String): Double? = try {
            primitive(o, key)?.asDouble
        } catch (_: Exception) { null }

        private fun lng(o: JsonObject?, key: String): Long? = try {
            primitive(o, key)?.asLong
        } catch (_: Exception) { null }

        private fun bool(o: JsonObject?, key: String): Boolean? = try {
            primitive(o, key)?.asBoolean
        } catch (_: Exception) { null }

        /** null = 字段缺失；empty = 明确未上报。两者都不许当 0 用。 */
        private fun arr(o: JsonObject?, key: String): List<Double>? = try {
            o?.getAsJsonArray(key)?.takeIf { !it.isJsonNull }?.mapNotNull { e ->
                e.takeIf { it.isJsonPrimitive }?.asDouble
            }
        } catch (_: Exception) { null }

        private fun strings(o: JsonObject?, key: String): List<String> = try {
            o?.getAsJsonArray(key)?.mapNotNull { e ->
                e.takeIf { it.isJsonPrimitive }?.asString
            } ?: emptyList()
        } catch (_: Exception) { emptyList() }
    }
}
