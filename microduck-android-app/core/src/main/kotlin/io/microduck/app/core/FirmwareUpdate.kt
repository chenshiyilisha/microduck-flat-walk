package io.microduck.app.core

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/**
 * 固件 OTA 的**纯 JVM 决策层**：解析 updaterd 的 JSON-RPC 响应/通知、构造写操作请求参数、
 * 判定「是否提示用户更新」。不含 Android API / 网络 API，能用 tools/selftest.sh 真编译真跑（含负对照）。
 *
 * ── 一手依据（kissqy v167 固件源码，逐字核对；非沿用记忆）──
 *  · `duck-ipc-proto/src/lib.rs`：`CheckResult`(state 三态) / `Phase`(13 值) /
 *    `ComponentStatus` / `Progress` / `ApplyResult`(outcome 内部标签) / `ApplyParams` /
 *    `Target`(外部标签) / `ApplyOptions` / `SelectParams` / `LogEntry` / 错误码。
 *  · `docs/design/updater-design.md`：health gate 自动回滚、minisign 验签、
 *    「robot pulls from CDN over its own wifi; phone is trigger+progress only」。
 *  · `docs/project/update-over-ble.md`：BLE 只透传 JSON-RPC；apply 后约 5s 断连属成功路径；
 *    subscribe 独占连接；进度每整百分比≤1 条、每秒≤4 条。
 *  · `btd/src/route.rs`：BLE 放行 check/apply/status/subscribe/log/show/listInstalled/
 *    rollback/select；拒绝 update.pin/resetToGolden。
 *
 * ── 铁律 ──
 *  · 缺字段 / 未知枚举一律落到明确的 Unknown/空，绝不「看起来合理就当成功」。
 *  · 版本提示只由 `check.state=available` 驱动；manifest 的 url/sha256 不在 IPC 上，不拿来拼 UI。
 *  · 写操作参数 deny_unknown_fields ⇒ 键名精确，可选键缺省不出现（不能多发 null）。
 *  · 真机项（apply 真的装成、health gate、BLE lane 分道）恒 UNVERIFIED，本层不翻状态。
 */
object FirmwareUpdate {

    /** updaterd 组件 id（来自 updater.toml `[component.<name>]`）。UI 默认聚焦主 daemon。 */
    const val COMPONENT_DAEMON = "daemon"

    /** Phase 全部 13 个值（lib.rs Phase enum，snake_case）。顺序即进度语义顺序。 */
    val PHASES = listOf(
        "idle", "preflight", "checking", "downloading", "verifying", "extracting",
        "running_pre_hook", "swapping", "running_post_hook", "applying",
        "health_gate", "committing", "rolling_back",
    )

    /** 终态 phase（用于判定「一次更新是否已结束」，未在此列的都在进行中）。 */
    private val TERMINAL_PHASES = setOf("idle", "health_gate", "committing", "rolling_back")

    /** 需要用户二次确认的 mutating 方法（写操作清单，门禁会核对）。 */
    val MUTATING_METHODS = listOf(Method.UPDATE_APPLY, Method.UPDATE_ROLLBACK, Method.UPDATE_SELECT)

    // ───────────────────────────── 解析：check ─────────────────────────────

    /** update.check 结果三态（ result.state 内部标签，snake_case）。 */
    sealed class CheckState {
        data class UpToDate(val installed: String?) : CheckState()
        data class Available(
            val installed: String?,
            val candidate: String?,
            val mandatory: Boolean,
            val changelog: String?,
        ) : CheckState()

        data class Incompatible(val candidate: String?, val reason: String?) : CheckState()
        /** 未知 state / 缺字段 / 无法解析 —— 不猜、不提示更新。 */
        data class Unknown(val raw: String?) : CheckState()
    }

    /**
     * 解析 update.check 的 result。只有 state=available 才应提示用户。
     * 负对照：state 缺失/拼错 → Unknown（绝不 fallback 成 up_to_date 掩盖问题）。
     */
    fun parseCheck(o: JsonObject?): CheckState {
        if (o == null) return CheckState.Unknown(null)
        val state = str(o, "state") ?: return CheckState.Unknown(null)
        return when (state) {
            "up_to_date" -> CheckState.UpToDate(str(o, "installed"))
            "available" -> CheckState.Available(
                installed = str(o, "installed"),
                candidate = str(o, "candidate"),
                mandatory = bool(o, "mandatory") ?: false,
                changelog = str(o, "changelog"),
            )
            "incompatible" -> CheckState.Incompatible(str(o, "candidate"), str(o, "reason"))
            else -> CheckState.Unknown(state)
        }
    }

    /**
     * 是否应向用户弹「发现新版本」提示：只对 available 为真；incompatible/up_to_date/
     * unknown 一律 false。mandatory 只影响提示强度，不影响「是否提示」。
     */
    fun shouldPrompt(c: CheckState): Boolean = c is CheckState.Available

    // ───────────────────────────── 解析：status ─────────────────────────────

    /** update.status 单个组件状态。installed 是当前版本（null=未安装），phase 是 13 值之一。 */
    data class ComponentStatus(
        val component: String?,
        val installed: String?,
        val phase: String,
        val healthy: Boolean?,
        val degraded: Boolean,
        val reason: String?,
        val pinned: String?,
        val lastAttempt: ApplyResult?,
        val lastChecked: Long?,
        val unknownPhase: Boolean,   // phase 不在 13 值内 = 固件版本 skew，UI 如实标注
    ) {
        /** 该组件当前是否处于「更新进行中」。 */
        val inProgress: Boolean get() = !unknownPhase && phase in PHASES && phase !in TERMINAL_PHASES
    }

    /**
     * 解析 update.status 的 result —— 它是一个 **Vec<ComponentStatus> 数组**，不是单个对象。
     * 入参是 [RobotSession.callRaw] 返回的 result JsonElement（顶层即数组）；
     * 也兼容 {components:[...]} / {status:[...]} 包装形态。
     */
    fun parseStatus(result: JsonElement?): List<ComponentStatus> =
        asArray(result, "components", "status").mapNotNull { el ->
            if (el.isJsonObject) parseComponent(el.asJsonObject) else null
        }

    /** 从单个组件对象解析。phase 未知时保留原文并置 unknownPhase=true。 */
    fun parseComponent(o: JsonObject): ComponentStatus {
        val phase = str(o, "phase") ?: "idle"
        val healthy = bool(o, "healthy")
        val lastAttemptObj = o.get("last_attempt")?.takeIf { it.isJsonObject }?.asJsonObject
        return ComponentStatus(
            component = str(o, "component"),
            installed = str(o, "installed"),
            phase = phase,
            healthy = healthy,
            degraded = bool(o, "degraded") ?: false,
            reason = str(o, "reason"),
            pinned = str(o, "pinned"),
            lastAttempt = lastAttemptObj?.let { parseApply(it) },
            lastChecked = long(o, "last_checked"),
            unknownPhase = phase !in PHASES,
        )
    }

    // ───────────────────────────── 解析：apply 结果 ─────────────────────────────

    /** update.apply / rollback / select 的 result.outcome（内部标签）。 */
    sealed class ApplyResult {
        data class Applied(val from: String?, val to: String?) : ApplyResult()
        data class AlreadyCurrent(val version: String?, val stale: Boolean) : ApplyResult()
        data class DryRunPassed(val candidate: String?) : ApplyResult()
        data class RolledBack(val attempted: String?, val revertedTo: String?, val reason: String?) : ApplyResult()
        data class Stuck(val version: String?, val reason: String?) : ApplyResult()
        data class Unknown(val raw: String?) : ApplyResult()
    }

    /** 解析 ApplyResult（也用于 status.last_attempt —— 同一结构）。 */
    fun parseApply(o: JsonObject?): ApplyResult {
        if (o == null) return ApplyResult.Unknown(null)
        // last_attempt 是 LogEntry{outcome:{kind:...}}；apply reply 直接是 {outcome:"..."}。
        // getAsJsonObject 遇到 primitive 会抛 ClassCastException ⇒ 必须先 takeIf 判类型（负对照抓到）。
        val outcomeObj = o.get("outcome")?.takeIf { it.isJsonObject }?.asJsonObject
        val kind = str(o, "outcome") ?: outcomeObj?.let { str(it, "kind") }
            ?: return ApplyResult.Unknown(null)
        return when (kind) {
            // "applied" = apply reply；"success" = LogEntry.outcome.kind（历史记录），同义收敛。
            "applied", "success" -> ApplyResult.Applied(str(o, "from"), str(o, "to"))
            "already_current" -> ApplyResult.AlreadyCurrent(str(o, "version"), bool(o, "stale") ?: false)
            "dry_run_passed" -> ApplyResult.DryRunPassed(str(o, "candidate"))
            "rolled_back" -> ApplyResult.RolledBack(
                attempted = str(o, "attempted") ?: outcomeObj?.let { str(it, "attempted") },
                revertedTo = str(o, "reverted_to") ?: outcomeObj?.let { str(it, "reverted_to") },
                reason = str(o, "reason") ?: outcomeObj?.let { str(it, "reason") },
            )
            "stuck" -> ApplyResult.Stuck(str(o, "version"), str(o, "reason"))
            else -> ApplyResult.Unknown(kind)
        }
    }

    /** 一次 apply 是否「成功落地」（只有 outcome=applied 算；dry_run/rollback/未知都不算）。 */
    fun isApplied(r: ApplyResult): Boolean = r is ApplyResult.Applied

    // ───────────────────────────── 解析：progress 通知 ─────────────────────────────

    /** update.progress 通知的 params。 */
    data class Progress(
        val component: String?,
        val phase: String,
        val percent: Int?,      // 0..100；无效值归一为 null
        val detail: String?,
        val unknownPhase: Boolean,
    )

    /** 解析进度通知；percent 越界归一为 null（不把 150% 塞进进度条）。 */
    fun parseProgress(o: JsonObject?): Progress? {
        if (o == null) return null
        val component = str(o, "component")
        val phase = str(o, "phase") ?: return null
        val rawPct = int(o, "percent")
        val pct = rawPct?.takeIf { it in 0..100 }
        return Progress(component, phase, pct, str(o, "detail"), phase !in PHASES)
    }

    /** 进度文案：phase 中文标签 + 百分比（有则显示）。未知 phase 如实标注。 */
    fun progressLabel(p: Progress): String {
        val label = PHASE_LABELS[p.phase]
            ?: if (p.unknownPhase) "未知阶段(${p.phase})" else p.phase
        return if (p.percent != null) "$label ${p.percent}%" else label
    }

    private val PHASE_LABELS = mapOf(
        "idle" to "空闲", "preflight" to "前置检查", "checking" to "检查版本",
        "downloading" to "下载中", "verifying" to "校验签名", "extracting" to "解压",
        "running_pre_hook" to "运行前脚本", "swapping" to "切换版本",
        "running_post_hook" to "运行后脚本", "applying" to "应用中",
        "health_gate" to "健康检查", "committing" to "提交", "rolling_back" to "回滚中",
    )

    // ───────────────────────────── 解析：log / listInstalled ─────────────────────────────

    data class LogEntry(val at: Long?, val component: String?, val from: String?, val to: String?, val outcome: ApplyResult)

    /** update.log 的 result 是 Vec<LogEntry>；入参为 callRaw 的 result（顶层数组）或 {logs:[...]} 包装。 */
    fun parseLog(result: JsonElement?): List<LogEntry> =
        asArray(result, "logs").mapNotNull { el ->
            if (!el.isJsonObject) null else {
                val o = el.asJsonObject
                LogEntry(long(o, "at"), str(o, "component"), str(o, "from"), str(o, "to"), parseApply(o))
            }
        }

    /** update.listInstalled 的 result 是 Vec<InstalledRelease>{version,active,golden,source_revision}。 */
    data class Installed(val version: String?, val active: Boolean, val golden: Boolean, val sourceRevision: String?)

    fun parseInstalled(result: JsonElement?): List<Installed> =
        asArray(result, "installed").mapNotNull { el ->
            if (!el.isJsonObject) null else {
                val o = el.asJsonObject
                Installed(str(o, "version"), bool(o, "active") ?: false, bool(o, "golden") ?: false, str(o, "source_revision"))
            }
        }

    /**
     * 把 result JsonElement 归一成数组：顶层就是 JsonArray（callRaw 主路径），
     * 或在 JsonObject 里按候选键取（兼容包装形态）。任何异常/非数组 → 空。
     */
    private fun asArray(result: JsonElement?, vararg objectKeys: String): JsonArray {
        if (result == null || result.isJsonNull) return JsonArray()
        if (result.isJsonArray) return result.asJsonArray
        if (result.isJsonObject) {
            val o = result.asJsonObject
            for (k in objectKeys) {
                val v = o.get(k)
                if (v != null && v.isJsonArray) return v.asJsonArray
            }
        }
        return JsonArray()
    }

    // ───────────────────────────── 构造：写操作请求参数 ─────────────────────────────

    /**
     * update.apply 的 params。deny_unknown_fields ⇒ 只写固件认得的键。
     * [dryRun]=true 只跑检查不切换 symlink（一手 ApplyOptions.dry_run）。
     * from_dir 绝不下发（sideload 本地目录是另一条链路，且 deny_unknown_fields）。
     */
    fun applyParams(component: String, version: String?, dryRun: Boolean): Map<String, Any?> {
        val target: Any = if (version.isNullOrBlank()) "latest" else mapOf("exact" to version)
        val options = linkedMapOf<String, Any>("dry_run" to dryRun)
        return linkedMapOf<String, Any?>(
            "component" to component,
            "target" to target,
            "options" to options,
        )
    }

    /** update.rollback 的 params（ComponentParams，只有 component）。 */
    fun rollbackParams(component: String): Map<String, Any?> = mapOf("component" to component)

    /** update.select 的 params（SelectParams{component,version}，精确 semver，不下载）。 */
    fun selectParams(component: String, version: String): Map<String, Any?> =
        mapOf("component" to component, "version" to version)

    /** update.check / listInstalled 的（唯一）参数 component。 */
    fun componentParams(component: String): Map<String, Any?> = mapOf("component" to component)

    /** update.log 的 params（LogParams{limit}）。 */
    fun logParams(limit: Int): Map<String, Any?> = mapOf("limit" to limit.coerceIn(1, 200))

    /** update.show 的 params（ShowParams{run}，run=null 取最近一次）。 */
    fun showParams(run: Long?): Map<String, Any?> =
        if (run == null) mapOf("run" to null) else mapOf("run" to run)

    // ───────────────────────────── 错误码解读 ─────────────────────────────

    /** updaterd 业务错误码（lib.rs pub mod code）；-32xxx 是 JSON-RPC 标准码。 */
    fun describeError(code: Int): String = when (code) {
        1 -> "更新进行中，请稍后重试"
        2 -> "未知组件"
        4 -> "前置检查失败"
        5 -> "网络错误（板子自身拉取失败，检查板子 WiFi）"
        6 -> "校验失败（签名/哈希不符）"
        7 -> "版本不兼容"
        8 -> "Hook 脚本失败"
        9 -> "健康检查失败（会自动回滚）"
        10 -> "回滚失败"
        11 -> "未安装"
        12 -> "拒绝降级"
        13 -> "归档过大"
        14 -> "权限不足（BLE 路由拒绝）"
        -32601 -> "此固件不支持该方法"
        -32602 -> "参数不被接受（协议版本不匹配）"
        -32603 -> "固件内部错误（updaterd 可能未启动）"
        else -> "错误码 $code"
    }

    // ───────────────────────────── Gson null-safe 取值 ─────────────────────────────

    private fun str(o: JsonObject, k: String): String? =
        o.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asString

    private fun bool(o: JsonObject, k: String): Boolean? =
        o.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asBoolean

    private fun int(o: JsonObject, k: String): Int? = try {
        o.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asInt
    } catch (_: Exception) { null }

    private fun long(o: JsonObject, k: String): Long? = try {
        o.get(k)?.takeUnless { it.isJsonNull }?.takeIf { it.isJsonPrimitive }?.asLong
    } catch (_: Exception) { null }

    /** 供自检/门禁使用：把 JSON 字符串解析成 JsonObject（null-safe）。 */
    fun obj(json: String): JsonObject? = try {
        JsonParser.parseString(json).asJsonObject
    } catch (_: Exception) { null }

    /** 同 [obj]，但返回 JsonElement —— 顶层是数组（Vec 类 result）时用。 */
    fun element(json: String): JsonElement? = try {
        JsonParser.parseString(json)
    } catch (_: Exception) { null }
}
