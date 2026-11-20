package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * Wi-Fi 配网写路径（A2：`net.connect` / `net.forget`）的请求构造与回执解析。
 *
 * ── 🔴 安全交付判定（一手，不改写成可交付）──
 * 目标固件 fanhao fork 的 `btd/src/route.rs:139-155` 逐字写明：Wi-Fi passphrase **明文跨 BLE**，
 * `--require-pairing` 默认 off，bond 是 just-works 无认证，「passphrase crosses in clear …
 * a known, accepted, pre-shipping cost … §8.1 is the blocker that has to close before a robot
 * goes to anyone」。原厂 `app-path-design.md` §8.1 把加密列为 pre-shipping blocker，三候选皆需
 * **固件端**改动（修链路层 / 应用层封密 / 会话封密）——固件端当前零应用层加解密实现，
 * App 单侧加密无法互操作。⇒ 本模块：
 *   1. 功能上完整实现配网调用（内部/台架自测可用）；
 *   2. `PLAINTEXT_TRANSPORT_WARNING` 是必须随请求展示的警示常量，UI 强制显性化；
 *   3. `psk` 永不进日志、不进数据类 toString / Debug，只在出站 JSON 里出现一次。
 * 不可把明文配网包装成「安全可交付功能」；整机落地前 ship_verdict=NOT_SHIPPABLE。
 *
 * ── 一手契约（fanhao 副本 API40，lib.rs）──
 * · `NetConnectParams{ssid, psk?}` deny_unknown_fields；psk=None 时**不写该键**（开放网络）
 *   lib.rs:2957；`NetForgetParams{ssid}` lib.rs:2986。
 * · `ConnectResult` tag=outcome：`connected{ssid, ip4?}` / `failed{reason, detail?}` lib.rs:4086；
 *   `ConnectFailure`=bad_key|not_found|timeout|unsupported|other lib.rs:4071。
 * · `ForgetResult{removed}` lib.rs:4102。
 *
 * 纯 JVM、零 Android 依赖 ⇒ 自检真跑请求构造/解析/脱敏/负对照。
 */
object NetProvisioning {
    /** 必须随配网请求展示的原厂风险警示（UI 逐字显示，不可省略或软化）。 */
    const val PLAINTEXT_TRANSPORT_WARNING =
        "注意：当前固件经 BLE 明文传输 Wi-Fi 密码（原厂 §8.1 列为交付前阻塞项）。" +
            "本功能仅供内部/台架自测，整机对外交付前必须完成固件端加密，切勿在公开场合输入真实密码。"

    /** 连接结果：解析成不可变值，缺字段保持 null，不猜 IP。 */
    data class ConnectOutcome(
        val connected: Boolean,
        val ssid: String? = null,
        val ip4: String? = null,
        /** bad_key|not_found|timeout|unsupported|other|未知 */
        val failure: String? = null,
        val detail: String? = null,
    ) {
        /** 给用户的一句话提示：按 ConnectFailure 分类，不对密码错误给假原因。 */
        val userMessage: String
            get() = if (connected) {
                "已连接${ssid?.let { " $it" } ?: ""}${ip4?.let { "（$it）" } ?: ""}"
            } else when (failure) {
                "bad_key" -> "密码错误，请重新输入"
                "not_found" -> "未找到该网络，请靠近路由器或核对名称"
                "timeout" -> "连接超时（多为 DHCP），可重试"
                "unsupported" -> "该网络类型不受支持（如 802.1X 或缺少密码）"
                else -> "连接失败${detail?.let { "：$it" } ?: ""}"
            }
    }

    data class ForgetOutcome(val removed: Boolean)

    /**
     * 构造 `net.connect` 的 params。严格只带 ssid 与可选 psk（deny_unknown_fields ⇒ 多键被 -32602 拒）。
     * 开放网络传 psk=null ⇒ 不写该键，与固件的 skip_serializing_if 对齐。
     */
    fun connectParams(ssid: String, psk: String?): Map<String, Any?> {
        val m = linkedMapOf<String, Any?>("ssid" to ssid)
        if (!psk.isNullOrEmpty()) m["psk"] = psk
        return m
    }

    fun forgetParams(ssid: String): Map<String, Any?> = linkedMapOf("ssid" to ssid)

    /** 解析 net.connect 回执。outcome 缺失或非法 → connected=false/failure=未知，不伪造成功。 */
    fun parseConnect(o: JsonObject?): ConnectOutcome {
        if (o == null) return ConnectOutcome(false, failure = "未知")
        val outcome = o.takeIf { it.has("outcome") && it.get("outcome").isJsonPrimitive }
            ?.getAsJsonPrimitive("outcome")?.asString
        return when (outcome) {
            "connected" -> {
                val ssid = o.takeIf { it.has("ssid") && it.get("ssid").isJsonPrimitive }
                    ?.getAsJsonPrimitive("ssid")?.asString
                val ip4 = o.takeIf { it.has("ip4") && it.get("ip4").isJsonPrimitive }
                    ?.getAsJsonPrimitive("ip4")?.asString
                ConnectOutcome(true, ssid = ssid, ip4 = ip4)
            }
            "failed" -> {
                val reason = o.takeIf { it.has("reason") && it.get("reason").isJsonPrimitive }
                    ?.getAsJsonPrimitive("reason")?.asString ?: "未知"
                val detail = o.takeIf { it.has("detail") && it.get("detail").isJsonPrimitive }
                    ?.getAsJsonPrimitive("detail")?.asString
                ConnectOutcome(false, failure = reason, detail = detail)
            }
            else -> ConnectOutcome(false, failure = "未知")
        }
    }

    /**
     * 配网成功后可回填到 IP 输入框的地址（一次性事件真值）。
     * 只有「connected 且固件回执带非空 ip4」才返回该 IP；失败 / 缺 ip4 / 空串一律 null。
     *
     * 🔴 一手：真实 `NetworkManager::connect`（configd/src/nm.rs:713-721）在 D-Bus 激活
     * ACTIVATED 后用 `status().ip4` 回执——真实读到的 DHCP 地址；不是 FakeNet 测试桩
     * 写死的 `192.168.50.63`（net.rs:164/231，仅 `--fake`/测试用）。故回执 ip4 可作回填真值。
     * 纯函数、无副作用 ⇒ core 自检直接覆盖正/负对照。
     */
    fun backfillIp(outcome: ConnectOutcome): String? =
        if (outcome.connected && !outcome.ip4.isNullOrBlank()) outcome.ip4!! else null

    /** 解析 net.forget 回执。removed 缺失 → false（未读到，不假装已删除）。 */
    fun parseForget(o: JsonObject?): ForgetOutcome {
        val removed = o?.takeIf { it.has("removed") && it.get("removed").isJsonPrimitive && it.get("removed").asJsonPrimitive.isBoolean }
            ?.getAsJsonPrimitive("removed")?.asBoolean ?: false
        return ForgetOutcome(removed)
    }
}
