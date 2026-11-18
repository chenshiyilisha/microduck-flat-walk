package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * Wi-Fi 配网快照（A2：`net.status` / `net.scan` 只读 + `net.connect` / `net.forget` 写回执）。
 *
 * ── 单一真源与缺数据语义 ──
 * 所有字段用 nullable / 空集合表示「未读到」，**绝不填 0、绝不伪造 SSID/IP**
 * （项目铁律：缺数据≠零；UNVERIFIED≠PASS）。固件经 -32601 报不支持 → 会话层标
 * unsupported → 这里保持 null，UI 显示「未读到 / 该固件不支持」。
 *
 * ── 一手依据（fanhao 副本 API40，本 App 对接目标；逐字核自 duck-ipc-proto/src/lib.rs）──
 * · `NetStatusResult{state, ssid?, signal?(0-100 非 dBm), ip4?, ip6?, mac?, iface?}` lib.rs:4019
 *   注释明写「Every field beyond `state` is absent when not connected」⇒ 未连接时这些字段缺失是正常的，
 *   不是读取失败，UI 不得据此显示 0 或假 IP。
 * · `NetScanResult{networks: Vec<Network>}` lib.rs:4060；`Network{ssid, signal:u8, security, saved}`
 *   lib.rs:4048；`Security` = open|wep|wpa_psk|wpa3_sae|enterprise（snake_case）lib.rs:4036。
 * · `ConnectResult` 是 `#[serde(tag="outcome", rename_all="snake_case")]` 枚举：
 *   `connected{ssid, ip4?}` / `failed{reason: ConnectFailure, detail?}` lib.rs:4086。
 * · `ConnectFailure` = bad_key|not_found|timeout|unsupported|other lib.rs:4071。
 * · `NetForgetParams{ssid}` / `ForgetResult{removed: bool}` lib.rs:2986/4102。
 * · `NetConnectParams{ssid, psk?}` 是 `deny_unknown_fields`，`psk` 为 passphrase 或 64-hex PSK，
 *   `skip_serializing_if=Option::is_none`（开放网络不带 psk）lib.rs:2957。
 *
 * 🔴 安全边界：本快照只承载**解析后的状态**，永不持有密码明文。
 * `psk` 的构造与脱敏在 [NetProvisioning]（写路径）里单独处理，且 MAC/IP 是可选展示字段，
 * 不是身份权威（serial 才是身份，见 §8.2）。纯 JVM、零 Android 依赖 ⇒ 自检真跑。
 */
data class NetSnapshot(
    // net.status
    val state: String? = null,
    val ssid: String? = null,
    val signal: Int? = null,
    val ip4: String? = null,
    val ip6: String? = null,
    val mac: String? = null,
    val iface: String? = null,
    // net.scan，保留固件返回序（最强在前）
    val networks: List<Network> = emptyList(),
    // 每个来源的读取错误（null=成功；非 null=失败原因，UI 如实回显）
    val statusError: String? = null,
    val scanError: String? = null,
) {
    data class Network(
        val ssid: String,
        val signal: Int,
        /** open / wep / wpa_psk / wpa3_sae / enterprise / 未知（不猜） */
        val security: String,
        val saved: Boolean,
    )

    /** 状态是否显示「已连接」——严格等于固件 state 文本，不从 ip4 反推。 */
    val isConnected: Boolean get() = state.equals("connected", ignoreCase = true)

    /** 全默认（没读过）时为 true —— UI 显示「点击刷新」，不假装已有数据。 */
    val isEmpty: Boolean
        get() = state == null && ssid == null && signal == null && ip4 == null &&
            ip6 == null && mac == null && iface == null && networks.isEmpty()

    companion object {
        private fun str(obj: JsonObject, vararg keys: String): String? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive && obj.get(it).asJsonPrimitive.isString }
            ?.let { obj.get(it).asJsonPrimitive.asString }

        /** 数字字段：只接受 primitive number，转 Int；缺失/类型不符返回 null。 */
        private fun int(obj: JsonObject, vararg keys: String): Int? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive && obj.get(it).asJsonPrimitive.isNumber }
            ?.let { obj.get(it).asJsonPrimitive.asInt }

        private fun bool(obj: JsonObject, vararg keys: String): Boolean? = keys
            .firstOrNull { obj.has(it) && obj.get(it).isJsonPrimitive && obj.get(it).asJsonPrimitive.isBoolean }
            ?.let { obj.get(it).asJsonPrimitive.asBoolean }

        /**
         * 解析 net.status。state 是唯一必填字段，缺 state 视为没读到（返回 null）。
         * 未连接时其余字段本就缺失——保留 null，不填默认。
         */
        fun fromStatus(o: JsonObject?): NetSnapshot? {
            if (o == null) return null
            val state = str(o, "state") ?: return null
            return NetSnapshot(
                state = state,
                ssid = str(o, "ssid"),
                signal = int(o, "signal"),
                ip4 = str(o, "ip4"),
                ip6 = str(o, "ip6"),
                mac = str(o, "mac"),
                iface = str(o, "iface"),
            )
        }

        /** 解析 net.scan 的 networks 数组；未知 security 原样保留为字符串，不猜成 open。 */
        fun parseScan(o: JsonObject?): List<Network> {
            if (o == null) return emptyList()
            val key = listOf("networks", "results", "items").firstOrNull {
                o.has(it) && o.get(it).isJsonArray
            } ?: return emptyList()
            return o.getAsJsonArray(key).mapNotNull { e ->
                if (!e.isJsonObject) return@mapNotNull null
                val n = e.asJsonObject
                val ssid = str(n, "ssid") ?: return@mapNotNull null
                val signal = int(n, "signal") ?: return@mapNotNull null
                val security = str(n, "security") ?: "未知"
                val saved = bool(n, "saved") ?: false
                Network(ssid, signal, security, saved)
            }
        }
    }
}
