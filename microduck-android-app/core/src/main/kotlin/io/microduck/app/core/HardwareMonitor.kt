package io.microduck.app.core

import com.google.gson.JsonArray
import com.google.gson.JsonObject

/**
 * 硬件状态监控 / 告警 / 异常部位判定的**唯一策略真源**（纯 JVM，零 Android 依赖）。
 *
 * ── 数据真实性分层（本项目铁律 `UNVERIFIED != PASS`、`COLLECTED != PASS`）──
 *  · [MonitorSource.REAL_HEALTH]：真机 `robot.health` 应答，判据可触发告警。
 *  · [MonitorSource.MOCK_FIXTURE]：App 自带演示夹具，**verdict 恒为 DEMO_ONLY**，
 *    每条告警带 `demo=true`，UI 必须标「非实机读数」，绝不冒充真机告警。
 *  · [MonitorSource.NONE]：未连接 / 调用失败 / 字段缺失 ⇒ 所有部位 UNKNOWN、**零告警**。
 *    没数据 ≠ 没故障，也 ≠ 正常；「不显示 0 V / 0°C」是 HealthSnapshot 已守住的底线。
 *
 * ── 阈值的一手依据（禁止凭感觉改数字）──
 *  1. 电池：`duck-control/src/model.rs:170-191` `BATTERY_FULL_V=8.2` / `BATTERY_EMPTY_V=6.6`，
 *     `battery_percent()` 线性 clamp；`robotd-design.md:735-741` 明确「客户端不要自己重算
 *     percent，无 fuel gauge，测的是舵机母线电压，负载下会下垂」。
 *     低电量警戒线参考 2S Li-ion 3.3 V/芯（=6.6 V）与行业 20% 告警惯例
 *     （Feetech/锂电池放电曲线资料），故 WARN=20%、CRITICAL=10%（或 volts<=6.6 直接判危急，
 *     因为那正是源码定义的 empty）。**这是本地显示策略阈值，不是固件判定** —— `robotd`
 *     `health()` 源码注释明写这些描述量 "consulted by none of the checks below"
 *     （Reported, never judged）。
 *  2. 舵机温度：Feetech STS3215 产品规格书 §7-11「过热 Over Hot 大于 70°C 关闭扭矩输出」，
 *     工作温度范围 -10~60°C ⇒ WARN>=60、CRITICAL>=70。
 *  3. CPU 温度：Radxa ZERO 3W Product Brief Rev1.8 §6.5「internal thermal management
 *     governor … CPU temperature does not exceed a threshold of 85°C」；第三方资料与项目
 *     实机踩坑文档记录 ~80°C 起降频、机身无风道实测 92°C ⇒ WARN>=80、CRITICAL>=85。
 *  4. 控制环：`LoopHealth.target_hz=50`（源码），`last_tick_age_ms` 超过 1 s 视为链路/控制停滞。
 *
 * ── 协议边界（诚实写清楚，别造字段）──
 *  `ft1910/duck-ipc-proto/src/lib.rs` 的 `HealthResult` **只有聚合温度**
 *  （`motors.hottest/max_c/mean_c`）。底层 `slow.temps_c: [f64; 15]` 在
 *  `robotd/src/main.rs:4046-4057` 被 fold 成 3 个标量后丢弃 ⇒ **逐舵机温度不可得**。
 *  `rssi` / `link_quality` 不在 health/state 里（`app-path-design.md:922-923`：
 *  "RSSI is a sort key, never identity"）；`net.status.signal` 是 WiFi 0-100 百分比，
 *  属于另一个 method。因此「通信状态」由 传输层状态 + health 轮询新鲜度 +
 *  `bus.*` 内部总线计数 + `control_loop.last_tick_age_ms` 组成，**不显示伪造的 RSSI 数值**。
 *  App 侧对未来的逐舵机补丁做前向兼容解析（[HealthSnapshot.servos]），字段缺失即 UNKNOWN。
 */

/** 阈值集中在这里，静态检查器会锁住它们并带负对照。 */
object HwThresholds {
    const val BATTERY_WARN_PERCENT = 20.0
    const val BATTERY_CRITICAL_PERCENT = 10.0
    /** 源码 `BATTERY_EMPTY_V=6.6`；到这个电压 percent 已是 0。 */
    const val BATTERY_CRITICAL_VOLTS = 6.6
    /** 从源码线性映射反推 20%：6.6 + 0.2*(8.2-6.6)。 */
    const val BATTERY_WARN_VOLTS = 6.92

    /** Feetech STS3215 规格书：工作上限 60°C、>70°C 关扭矩。 */
    const val SERVO_WARN_C = 60.0
    const val SERVO_CRITICAL_C = 70.0

    /** Radxa ZERO 3W Product Brief：85°C thermal governor；实测 ~80°C 起降频。 */
    const val CPU_WARN_C = 80.0
    const val CPU_CRITICAL_C = 85.0

    const val LOOP_DEGRADE_RATIO = 0.9
    const val LOOP_STALE_TICK_MS = 1_000L
    /** 超过这个时间没拿到新的 health，链路判 UNKNOWN 并提示「数据陈旧」。 */
    const val HEALTH_STALE_MS = 6_000L
}

enum class MonitorSource { REAL_HEALTH, MOCK_FIXTURE, NONE }

enum class LinkState { CONNECTED, CONNECTING, DOWN, UNKNOWN }

/** 注意：这里**没有** PASS —— 监控报告是观测值，不是验收结论。 */
enum class MonitorVerdict { NO_DATA, DEMO_ONLY, NOMINAL, WARNING, CRITICAL }

data class HwAlert(
    val severity: Severity,
    val part: RobotPart,
    val message: String,
    /** 判据的一手依据，写进 UI/JSON 让任何人能追溯，不留「凭什么报」的黑箱。 */
    val basis: String,
    val demo: Boolean,
)

data class MonitorReport(
    val parts: Map<RobotPart, Severity>,
    val alerts: List<HwAlert>,
    val source: MonitorSource,
    val link: LinkState,
    val lastHealthOkMs: Long,
    val nowMs: Long,
    val verdict: MonitorVerdict,
    val notes: List<String>,
) {
    /** 部位着色查表：没有证据的部位一律 UNKNOWN（灰），绝不默认绿。 */
    fun severityOf(part: RobotPart): Severity = parts[part] ?: Severity.UNKNOWN

    fun flaggedParts(): List<RobotPart> = RobotParts.ALL.filter {
        severityOf(it) == Severity.WARN || severityOf(it) == Severity.CRITICAL
    }

    /** UI 摘要行；MOCK 必须自带免责标注，不能靠调用方记得加。 */
    fun headline(): String = when (verdict) {
        MonitorVerdict.NO_DATA -> "○ 无数据 · 未连接或 robot.health 调用失败"
        MonitorVerdict.DEMO_ONLY -> "◈ 演示夹具 · 非实机读数（告警仅用于验收 UI）"
        MonitorVerdict.NOMINAL -> "● 各项读数正常（仅表示已读到的字段）"
        MonitorVerdict.WARNING -> "⚠ ${alerts.size} 项告警"
        MonitorVerdict.CRITICAL -> "⛔ ${alerts.count { it.severity == Severity.CRITICAL }} 项严重 · 共 ${alerts.size} 项告警"
    }

    fun summaryLines(): List<String> = buildList {
        add(headline())
        add("数据来源=${source} · 链路=${link} · 读数年龄=${ageMs()}ms")
        notes.forEach { add("· $it") }
        alerts.forEach { a ->
            add("${if (a.severity == Severity.CRITICAL) "⛔" else "⚠"} [${a.part.label}] ${a.message}")
            add("    依据：${a.basis}")
        }
        if (alerts.isEmpty() && verdict != MonitorVerdict.NO_DATA && verdict != MonitorVerdict.DEMO_ONLY) {
            add("· 无告警（未读到的字段仍为「未读到」，不是正常）")
        }
    }

    fun ageMs(): Long = if (lastHealthOkMs > 0L) (nowMs - lastHealthOkMs).coerceAtLeast(0L) else -1L

    /** 供 AI 调试通道 `monitor` 命令输出；字段名固定，PC 桥可解析。 */
    fun toJson(): JsonObject = JsonObject().apply {
        addProperty("source", source.name)
        addProperty("link", link.name)
        addProperty("verdict", verdict.name)
        addProperty("last_health_ok_ms", lastHealthOkMs)
        addProperty("age_ms", ageMs())
        addProperty("headline", headline())
        val p = JsonObject()
        parts.forEach { (k, v) -> p.addProperty(k.name, v.name) }
        add("parts", p)
        val a = JsonArray()
        alerts.forEach { x ->
            a.add(JsonObject().apply {
                addProperty("severity", x.severity.name)
                addProperty("part", x.part.name)
                addProperty("message", x.message)
                addProperty("basis", x.basis)
                addProperty("demo", x.demo)
            })
        }
        add("alerts", a)
        val n = JsonArray(); notes.forEach { n.add(it) }; add("notes", n)
    }
}

object HardwareMonitor {

    private const val B_BATTERY = "源码 battery_percent 6.6V→0%/8.2V→100%；2S Li-ion 3.3V/芯警戒线；本地显示阈值，非固件判定"
    private const val B_SERVO = "Feetech STS3215 规格书 §7-11：>70°C 关扭矩，工作范围 -10~60°C"
    private const val B_CPU = "Radxa ZERO 3W Product Brief Rev1.8 §6.5：thermal governor 上限 85°C"
    private const val B_BUS = "ft1910 HealthResult.BusHealth.missing[]（点名缺失舵机 ID）"
    private const val B_IMU = "ft1910 HealthResult.ImuHealth.ready / consecutive_stale_blocks"
    private const val B_LOOP = "ft1910 HealthResult.LoopHealth.target_hz / last_tick_age_ms"
    private const val B_UPSTREAM = "ft1910 HealthResult.healthy / degraded / reason（robotd 自己的判决）"
    private const val B_LINK = "传输层事件 + robot.health 轮询新鲜度；协议不提供无线 RSSI"

    /**
     * 由一手读数派生报告。**不修改任何状态字段**、不输出 PASS、不把 COLLECTED 当 PASS。
     * [demo] 由调用方按 SessionHolder.kind 判定，不在这里猜。
     */
    fun evaluate(
        h: HealthSnapshot?,
        source: MonitorSource,
        link: LinkState,
        nowMs: Long,
        lastHealthOkMs: Long,
    ): MonitorReport {
        val demo = source == MonitorSource.MOCK_FIXTURE
        val notes = mutableListOf<String>()
        val alerts = mutableListOf<HwAlert>()
        val marks = mutableMapOf<RobotPart, MutableList<Severity>>()

        fun mark(part: RobotPart, sev: Severity) {
            marks.getOrPut(part) { mutableListOf() }.add(sev)
        }

        fun alert(part: RobotPart, sev: Severity, message: String, basis: String) {
            alerts += HwAlert(sev, part, message, basis, demo)
            mark(part, sev)
        }

        if (demo) notes += "⚠ 当前为 Mock 演示夹具，非实机读数（App 既有 healthSourceText 口径）"
        if (source == MonitorSource.NONE || h == null) {
            notes += "未连接或 robot.health 调用失败 ⇒ 所有部位 UNKNOWN、零告警；没数据不等于正常"
            return MonitorReport(emptyMap(), emptyList(), source, link, lastHealthOkMs, nowMs,
                MonitorVerdict.NO_DATA, notes)
        }

        // ── ① 电池（服务端已算好 percent，App 不重算）──
        val pct = h.percent
        val volts = h.volts
        if (pct == null && volts == null) {
            notes += "电池：协议未返回 battery（缺失 ≠ 0 V）"
        } else {
            val sev = when {
                (pct != null && pct < HwThresholds.BATTERY_CRITICAL_PERCENT) ||
                    (volts != null && volts <= HwThresholds.BATTERY_CRITICAL_VOLTS) -> Severity.CRITICAL
                (pct != null && pct < HwThresholds.BATTERY_WARN_PERCENT) ||
                    (volts != null && volts <= HwThresholds.BATTERY_WARN_VOLTS) -> Severity.WARN
                else -> Severity.OK
            }
            mark(RobotPart.BATTERY, sev)
            if (sev != Severity.OK) alert(RobotPart.BATTERY, sev,
                "电量低 ${pct?.let { "%.0f%%".format(it) } ?: "—"} / ${volts?.let { "%.2f V".format(it) } ?: "—"}", B_BATTERY)
        }

        // ── ② 舵机温度：协议只有聚合量，只给 hottest 部位着色，其余 14 关节保持 UNKNOWN ──
        val maxC = h.maxC
        if (maxC == null) {
            notes += "舵机温度：协议未返回 motors.max_c（缺失 ≠ 0°C）"
        } else {
            val sev = when {
                maxC >= HwThresholds.SERVO_CRITICAL_C -> Severity.CRITICAL
                maxC >= HwThresholds.SERVO_WARN_C -> Severity.WARN
                else -> Severity.OK
            }
            val hottestPart = RobotParts.partOfName(h.hottest) ?: RobotPart.TORSO
            mark(hottestPart, sev)
            if (sev != Severity.OK) alert(hottestPart, sev,
                "舵机高温 ${"%.1f".format(maxC)}°C · 最热=${h.hottest ?: "—"}", B_SERVO)
            notes += "协议仅提供聚合温度（hottest/max_c/mean_c），其余 14 个关节温度未提供 ⇒ 保持「未读到」"
        }

        // ── ③ CPU 温度 / 降频 ──
        val cpuC = h.cpuTempC
        if (cpuC == null) {
            notes += "CPU 温度：协议未返回 cpu_temp_c"
        } else {
            val sev = when {
                cpuC >= HwThresholds.CPU_CRITICAL_C -> Severity.CRITICAL
                cpuC >= HwThresholds.CPU_WARN_C -> Severity.WARN
                else -> Severity.OK
            }
            mark(RobotPart.CPU, sev)
            if (sev != Severity.OK) alert(RobotPart.CPU, sev,
                "主板 SoC 高温 ${"%.1f".format(cpuC)}°C", B_CPU)
        }
        if ((h.cpuThrottleLevel ?: 0) > 0) {
            alert(RobotPart.CPU, Severity.WARN,
                "CPU 已降频 level=${h.cpuThrottleLevel}/${h.cpuThrottleMaxLevel ?: "?"}", B_CPU)
        }

        // ── ④ 总线 / 缺失舵机 ID → 精确部位着色 ──
        if (h.missingFieldPresent) {
            if (h.missingIds.isEmpty()) {
                mark(RobotPart.BUS, Severity.OK)
            } else {
                val named = h.missingIds.mapNotNull { id -> RobotParts.partOfId(id)?.let { id to it } }
                named.forEach { (_, part) -> mark(part, Severity.CRITICAL) }
                alert(RobotPart.BUS, Severity.CRITICAL,
                    "舵机总线缺失 ${h.missingIds.size}/15 个 ID：${h.missingIds.joinToString(",")}" +
                        "（${named.joinToString("、") { it.second.label }}）", B_BUS)
            }
        } else {
            notes += "bus.missing 字段未出现（协议在空数组时省略）⇒ 不据此判总线正常"
        }
        if ((h.busErrors ?: 0) > 0) alert(RobotPart.BUS, Severity.WARN,
            "总线连续错误 ${h.busErrors} 次", B_BUS)
        if ((h.startupFailures ?: 0) > 0) alert(RobotPart.BUS, Severity.CRITICAL,
            "总线启动失败 ${h.startupFailures} 次（舵机可能未上电）", B_BUS)

        // ── ⑤ IMU ──
        when (h.imuReady) {
            null -> notes += "IMU：协议未返回 imu.ready"
            false -> alert(RobotPart.IMU, Severity.CRITICAL, "IMU not ready", B_IMU)
            true -> {
                if ((h.imuConsecutiveStaleBlocks ?: 0L) > 0L) {
                    alert(RobotPart.IMU, Severity.WARN,
                        "IMU 连续陈旧块 ${h.imuConsecutiveStaleBlocks}", B_IMU)
                } else mark(RobotPart.IMU, Severity.OK)
            }
        }

        // ── ⑥ 通信 / 控制环（没有 RSSI，用真实可得的量）──
        notes += "通信状态由传输层 + health 新鲜度 + bus/loop 计数组成；协议不提供无线 RSSI，本地 BLE 扫描 rssi 只作排序键"
        val age = if (lastHealthOkMs > 0L) nowMs - lastHealthOkMs else -1L
        val stale = age < 0L || age > HwThresholds.HEALTH_STALE_MS
        if (stale) notes += "⚠ robot.health 读数" +
            (if (age < 0L) "从未成功" else "已陈旧 ${age}ms") +
            "；下列判断基于最后一次成功快照，不代表当前状态"
        if (link == LinkState.DOWN) {
            alert(RobotPart.LINK, Severity.CRITICAL, "链路已断", B_LINK)
        } else if (link == LinkState.CONNECTED && !stale) {
            mark(RobotPart.LINK, Severity.OK)
        } else {
            notes += "链路读数不新鲜或状态未确认 ⇒ LINK 保持 UNKNOWN"
        }
        val tickAge = h.lastTickAgeMs
        if (tickAge != null && tickAge > HwThresholds.LOOP_STALE_TICK_MS) {
            alert(RobotPart.LINK, Severity.WARN, "控制环最后一拍已过 ${tickAge}ms", B_LOOP)
        }
        val achieved = h.achievedHz
        val target = h.targetHz
        if (achieved != null && target != null && target > 0.0 &&
            achieved < target * HwThresholds.LOOP_DEGRADE_RATIO) {
            alert(RobotPart.LINK, Severity.WARN,
                "控制环 ${"%.1f".format(achieved)}Hz < 目标 ${"%.1f".format(target)}Hz 的 90%", B_LOOP)
        }

        // ── ⑦ robotd 自己的判决（不是我们推的）──
        if (!h.healthy || h.degraded) {
            alert(RobotPart.TORSO, Severity.CRITICAL,
                "robotd 自报 ${if (h.degraded) "DEGRADED" else "UNHEALTHY"}：${h.reason ?: "无 reason"}",
                B_UPSTREAM)
        } else {
            mark(RobotPart.TORSO, Severity.OK)
        }

        // ── ⑧ 前向兼容：未来上游补丁提供逐舵机遥测时，直接给 15 个部位真实状态 ──
        if (h.servos.isNotEmpty()) {
            notes += "检测到扩展字段 servo_telemetry（${h.servos.size} 路）⇒ 逐舵机判据已启用"
            h.servos.forEach { s ->
                val part = RobotParts.partOfId(s.id) ?: return@forEach
                val c = s.tempC
                if (c == null) return@forEach
                val sev = when {
                    c >= HwThresholds.SERVO_CRITICAL_C -> Severity.CRITICAL
                    c >= HwThresholds.SERVO_WARN_C -> Severity.WARN
                    else -> Severity.OK
                }
                mark(part, sev)
                if (sev != Severity.OK) alert(part, sev,
                    "舵机 ID ${s.id} 温度 ${"%.1f".format(c)}°C", B_SERVO)
            }
        } else {
            notes += "扩展字段 servo_telemetry 未提供（板上 v40 镜像未含纯新增补丁）⇒ 逐舵机温度 UNVERIFIED"
        }

        val parts = RobotParts.ALL.associateWith { part ->
            marks[part]?.let { RobotParts.merge(it) } ?: Severity.UNKNOWN
        }
        val verdict = when {
            demo -> MonitorVerdict.DEMO_ONLY
            alerts.any { it.severity == Severity.CRITICAL } -> MonitorVerdict.CRITICAL
            alerts.isNotEmpty() -> MonitorVerdict.WARNING
            else -> MonitorVerdict.NOMINAL
        }
        return MonitorReport(parts, alerts, source, link, lastHealthOkMs, nowMs, verdict, notes)
    }
}
