package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * 上游「逐舵机遥测」纯新增补丁提案的可选字段（见
 * `docs/active/microduck-安卓App-硬件监控与3D仿真模型-2026-11-15.md` §固件补丁提案）。
 * 当前 `ft1910` 一手协议与板上 v40 镜像**都没有**这些字段；这里只是前向兼容解析，
 * 拿到就用、拿不到就空，绝不生成占位值。
 */
data class ServoTelemetry(
    val id: Int,
    val tempC: Double?,
    val volts: Double?,
    val load: Double?,
)

/**
 * `robot.health` 应答的安全解析 —— 一手字段来自 B 代 `duck-ipc-proto/src/lib.rs:2429+`
 * （`HealthResult` / `Battery:2603` / `LoopHealth:2492` / `BusHealth:2516` / `MotorThermal:2589`）。
 *
 * 🔴 **缺失 ≠ 零**（这是本文件存在的理由，不是可选的整洁度）：
 *  - `HealthResult::battery` 注释（:2453-2456）：
 *    "Absent means *not known yet* — the first second after startup, a bus that cannot
 *     answer, or an older robotd. **Absent is not zero volts, and a client must not render
 *     it as an empty battery.**"
 *  - `LoopHealth::achieved_hz`（:2496-2499）：`None` 是「第一个窗口还没闭合」，
 *    明写 "which is *unknown*, not zero ... printing that for the first second of every
 *    robot's uptime would be a lie."
 *  - `HealthResult::Battery`（:2596-2601）：客户端**不要**自己按电压算百分比，
 *    "the mapping was duplicated into the app — which is how two screens end up
 *     disagreeing about the same battery" ⇒ 直接显示固件给的 `percent`。
 *
 * 所以本类所有可选量都是 nullable，UI 渲染 null 为「— 未读到」，**不得用 0 兜底**。
 * 版本 skew：旧 daemon 可能整个字段都没有（lib.rs 明说靠 METHOD_NOT_FOUND 逐方法降级），
 * 故一律 null-safe，绝不 typed 反序列化。
 */
data class HealthSnapshot(
    val healthy: Boolean,
    val degraded: Boolean,
    val reason: String?,
    val volts: Double?,
    val percent: Double?,
    val pack: String?,
    val batteryProblem: String?,
    val hottest: String?,
    val maxC: Double?,
    val meanC: Double?,
    val cpuTempC: Double?,
    val targetHz: Double?,
    val achievedHz: Double?,
    val ticks: Long?,
    val missed: Long?,
    val lastTickAgeMs: Long?,
    val busErrors: Int?,
    val startupFailures: Int?,
    // ── 以下为 2026-11-15 硬件监控扩展，**纯新增且全带默认值**，不破坏既有构造/自检 ──
    /** `BusHealth.missing`：协议在空数组时 `skip_serializing_if` 省略，故要区分「缺失」与「显式空」。 */
    val missingIds: List<Int> = emptyList(),
    val missingFieldPresent: Boolean = false,
    val imuReady: Boolean? = null,
    val imuStaleBlocks: Long? = null,
    val imuConsecutiveStaleBlocks: Long? = null,
    val cpuThrottleLevel: Int? = null,
    val cpuThrottleMaxLevel: Int? = null,
    val cpuThrottleKhz: Int? = null,
    /**
     * 前向兼容：上游纯新增补丁提案里的逐舵机遥测。**当前板上 v40 镜像未提供**，
     * 字段缺失即空列表 ⇒ 14 个关节温度保持 UNKNOWN，绝不填 0 / 造数。
     */
    val servos: List<ServoTelemetry> = emptyList(),
) {
    /** 缺电池时绝不显示 0.00 V。 */
    fun batteryText(): String {
        val v = volts ?: return "— 未读到（不是 0 V）"
        val p = percent
        return if (p != null) "%.2f V · %.0f%%".format(v, p) else "%.2f V".format(v)
    }

    /** achieved_hz 为 null 时绝不显示 0 Hz。 */
    fun loopText(): String {
        val hz = achievedHz ?: return "— 首个统计窗口未闭合（不是 0 Hz）"
        val target = targetHz?.let { " / 目标 %.0f".format(it) } ?: ""
        return "%.2f Hz%s · ticks=%s · missed=%s".format(
            hz, target, ticks?.toString() ?: "—", missed?.toString() ?: "—",
        )
    }

    fun summary(): String = buildString {
        append(if (healthy) "HEALTHY" else if (degraded) "DEGRADED（板级问题）" else "UNHEALTHY")
        reason?.let { append(" · ").append(it) }
        appendLine()
        append("电池：").append(batteryText())
        batteryProblem?.let { append(" ⚠ ").append(it) }
        appendLine()
        append("控制环：").append(loopText())
        appendLine()
        append("总线：连续错误=").append(busErrors?.toString() ?: "—")
        append(" · 启动失败=").append(startupFailures?.toString() ?: "—")
        if ((startupFailures ?: 0) > 0) append(" ⚠ 舵机可能未上电（BusHealth 注释）")
        appendLine()
        append("舵机温度：").append(
            hottest?.let { "$it ${maxC?.let { c -> "%.1f".format(c) } ?: "—"}°C" } ?: "— 未读到",
        )
        append(" · CPU：").append(cpuTempC?.let { "%.1f°C".format(it) } ?: "— 未读到")
    }

    companion object {
        fun from(o: JsonObject): HealthSnapshot {
            val battery = obj(o, "battery")
            val motors = obj(o, "motors")
            val loop = obj(o, "control_loop")
            val bus = obj(o, "bus")
            val imu = obj(o, "imu")
            val throttle = obj(o, "cpu_throttle")
            val missingEl = try { bus?.get("missing") } catch (_: Exception) { null }
            val missingPresent = missingEl != null && missingEl.isJsonArray
            return HealthSnapshot(
                healthy = bool(o, "healthy", false),
                degraded = bool(o, "degraded", false),
                reason = str(o, "reason"),
                volts = num(battery, "volts"),
                percent = num(battery, "percent"),
                pack = str(battery, "pack"),
                batteryProblem = str(battery, "problem"),
                hottest = str(motors, "hottest"),
                maxC = num(motors, "max_c"),
                meanC = num(motors, "mean_c"),
                cpuTempC = num(o, "cpu_temp_c"),
                targetHz = num(loop, "target_hz"),
                achievedHz = num(loop, "achieved_hz"),
                ticks = lng(loop, "ticks"),
                missed = lng(loop, "missed"),
                lastTickAgeMs = lng(loop, "last_tick_age_ms"),
                busErrors = integer(bus, "consecutive_errors"),
                startupFailures = integer(bus, "startup_failures"),
                missingIds = if (missingPresent) intArray(missingEl) else emptyList(),
                missingFieldPresent = missingPresent,
                imuReady = nullableBool(imu, "ready"),
                imuStaleBlocks = lng(imu, "stale_blocks"),
                imuConsecutiveStaleBlocks = lng(imu, "consecutive_stale_blocks"),
                cpuThrottleLevel = integer(throttle, "level"),
                cpuThrottleMaxLevel = integer(throttle, "max_level"),
                cpuThrottleKhz = integer(throttle, "khz"),
                servos = parseServos(o),
            )
        }

        /** 逐舵机补丁的前向兼容解析：字段名与补丁提案一致，两个别名都接受，缺一不可读即丢弃该行。 */
        private fun parseServos(o: JsonObject): List<ServoTelemetry> {
            val arr = try {
                (o.get("servo_telemetry") ?: o.get("servos"))
                    ?.takeIf { it.isJsonArray }?.asJsonArray
            } catch (_: Exception) { null } ?: return emptyList()
            val out = mutableListOf<ServoTelemetry>()
            for (el in arr) {
                if (!el.isJsonObject) continue
                val e = el.asJsonObject
                val id = integer(e, "id") ?: continue
                if (RobotParts.partOfId(id) == null) continue   // 未知 ID 不猜部位
                out += ServoTelemetry(
                    id = id,
                    tempC = num(e, "temp_c") ?: num(e, "temperature"),
                    volts = num(e, "volts") ?: num(e, "voltage"),
                    load = num(e, "load"),
                )
            }
            return out
        }

        private fun nullableBool(o: JsonObject?, key: String): Boolean? = try {
            primitive(o, key)?.asBoolean
        } catch (_: Exception) { null }

        private fun intArray(el: com.google.gson.JsonElement?): List<Int> = try {
            el?.asJsonArray?.mapNotNull {
                if (it.isJsonPrimitive && !it.isJsonNull) it.asInt else null
            } ?: emptyList()
        } catch (_: Exception) { emptyList() }

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

        private fun integer(o: JsonObject?, key: String): Int? = try {
            primitive(o, key)?.asInt
        } catch (_: Exception) { null }

        private fun bool(o: JsonObject?, key: String, default: Boolean): Boolean = try {
            primitive(o, key)?.asBoolean ?: default
        } catch (_: Exception) { default }
    }
}
