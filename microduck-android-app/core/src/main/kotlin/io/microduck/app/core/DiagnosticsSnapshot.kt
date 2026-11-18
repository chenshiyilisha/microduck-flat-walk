package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * 系统只读诊断快照（A3 系统信息/服务/日志 + A6 策略/模型 + A7 更新状态）。
 *
 * ── 单一真源与缺数据语义 ──
 * 所有字段用 nullable / 空集合表示「未读到」，**绝不填 0、绝不给默认假值**
 * （项目铁律：缺数据≠零）。固件经 -32601 报不支持时，由会话层标 unsupported，
 * 这里对应字段保持 null，UI 显示「未读到 / 该固件不支持」，不伪造。
 *
 * ── 一手依据（fanhao 副本 API40，本 App 对接目标）──
 * · system.info → SystemInfoResult{name, serial:Option, uptime_seconds, simulated}
 *   lib.rs:4116；system.services → ServiceUnit{unit, state, identity?}:List lib.rs:4249；
 * · system.logs → LogsParams{unit, lines, boot}（deny_unknown_fields）/ LogsResult{unit, lines}
 *   lib.rs:4261/4298；robot.policies / robot.model 见 lib.rs:726-745；
 * · update.status / update.listInstalled / update.log 见 lib.rs updaterd 段。
 * 字段名可能因固件版本略有差异，解析器对每个量取「候选键第一个存在且类型正确」，
 * 全都不匹配就是 null —— 与 RobotRepository.refreshSessionInfo 的做法一致。
 *
 * 纯 JVM、零 Android 依赖 ⇒ 自检可真跑解析逻辑，不靠文本门禁猜。
 */
data class DiagnosticsSnapshot(
    // A3 系统信息
    val robotName: String? = null,
    val serial: String? = null,
    val uptimeSeconds: Long? = null,
    val simulated: Boolean? = null,
    // A3 服务（unit -> state 文本）；顺序保留固件返回序
    val services: List<ServiceState> = emptyList(),
    // A3 日志尾部（按 unit 分组的纯文本行）
    val logs: List<String> = emptyList(),
    val logsUnit: String? = null,
    // A6 策略 / 模型
    val policies: List<String> = emptyList(),
    val model: String? = null,
    // A7 更新状态 / 已装清单
    val updateStatus: String? = null,
    val installed: List<String> = emptyList(),
    // 每个来源的读取错误（null=成功读到；非 null=失败原因，UI 如实回显）
    val infoError: String? = null,
    val servicesError: String? = null,
    val logsError: String? = null,
    val policiesError: String? = null,
    val modelError: String? = null,
    val updateError: String? = null,
) {
    data class ServiceState(val unit: String, val state: String, val identity: String?)

    /** 没有任何实机数据（全默认）时为 true —— UI 据此显示「点击刷新」，不假装已有数据。 */
    val isEmpty: Boolean
        get() = robotName == null && serial == null && uptimeSeconds == null &&
            simulated == null && services.isEmpty() && logs.isEmpty() &&
            policies.isEmpty() && model == null && updateStatus == null && installed.isEmpty()

    companion object {
        /** 取第一个「存在且是 primitive」的键，转字符串；全不匹配返回 null。 */
        private fun str(obj: JsonObject, vararg keys: String): String? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive }
            ?.let { obj.get(it).asJsonPrimitive.asString }

        private fun long(obj: JsonObject, vararg keys: String): Long? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive && obj.get(it).asJsonPrimitive.isNumber }
            ?.let { obj.get(it).asJsonPrimitive.asLong }

        private fun bool(obj: JsonObject, vararg keys: String): Boolean? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive && obj.get(it).asJsonPrimitive.isBoolean }
            ?.let { obj.get(it).asJsonPrimitive.asBoolean }

        /** 从 JsonArray 的字符串元素取列表；非字符串元素跳过，不造假。 */
        private fun stringList(obj: JsonObject, vararg keys: String): List<String> {
            val key = keys.firstOrNull { obj.has(it) && obj.get(it).isJsonArray } ?: return emptyList()
            return obj.getAsJsonArray(key).mapNotNull { e ->
                if (e.isJsonPrimitive && e.asJsonPrimitive.isString) e.asString else null
            }
        }

        /** system.info 的解析结果；缺字段保持 null。 */
        data class Info(val name: String?, val serial: String?, val uptimeSeconds: Long?, val simulated: Boolean?)

        /** 解析 system.info 结果。名字/serial/uptime 三者全缺时返回 null（空对象不算读到）。 */
        fun fromInfo(o: JsonObject?): Info? {
            if (o == null) return null
            val name = str(o, "name")
            val serial = str(o, "serial")
            val uptime = long(o, "uptime_seconds")
            if (name == null && serial == null && uptime == null) return null
            return Info(name, serial, uptime, bool(o, "simulated"))
        }

        /** 解析 system.services 结果：数组键候选 services / units。 */
        fun parseServices(o: JsonObject?): List<ServiceState> {
            if (o == null) return emptyList()
            val key = listOf("services", "units").firstOrNull { o.has(it) && o.get(it).isJsonArray }
                ?: return emptyList()
            return o.getAsJsonArray(key).mapNotNull { e ->
                if (!e.isJsonObject) return@mapNotNull null
                val u = e.asJsonObject
                val unit = str(u, "unit", "name") ?: return@mapNotNull null
                val state = str(u, "state") ?: "未知"
                val identity = str(u, "identity")
                ServiceState(unit, state, identity)
            }
        }

        /** 解析 system.logs 结果：unit + lines[]。 */
        fun parseLogs(o: JsonObject?): Pair<String?, List<String>> {
            if (o == null) return null to emptyList()
            return str(o, "unit") to stringList(o, "lines")
        }

        /** 解析 robot.policies：策略名数组（候选键 policies / installed / names）。 */
        fun parsePolicies(o: JsonObject?): List<String> =
            o?.let { stringList(it, "policies", "installed", "names") } ?: emptyList()

        /** 解析 robot.model：模型信息取字符串字段（候选键 model / name / id）。 */
        fun parseModel(o: JsonObject?): String? = o?.let { str(it, "model", "name", "id") }

        /** 解析 update.status：状态文本（候选键 status / state / phase）。 */
        fun parseUpdateStatus(o: JsonObject?): String? = o?.let { str(it, "status", "state", "phase") }

        /** 解析 update.listInstalled：已装组件数组（候选键 installed / components / items）。 */
        fun parseInstalled(o: JsonObject?): List<String> =
            o?.let { stringList(it, "installed", "components", "items") } ?: emptyList()
    }
}
