package io.microduck.app.core

/**
 * 连接地址解析 —— 把「用户输入的字符串」变成明确的 [ConnectTarget]，**任何不合法输入都显式报错**。
 *
 * 🔴 为什么要单独抽成可单测的纯 JVM 类（本项目踩过的坑，见 README 踩坑条）：
 * 旧实现是 `raw.substringAfter(":", "7788").toIntOrNull() ?: 7788`——端口填
 * `99999` / `abc` / `-1` / 空串，全部**悄悄回落**到 7788；host 空串、含空格、
 * 多个冒号也没校验。用户以为连的是自己填的地址，实际连到了默认端口 —— 典型的
 * 「输出落在看起来合理的区间里」的静默 bug，编译、UI 门禁都照不出来。
 *
 * 一手依据（BoBo 本地 `docs/design/mobile-app.md` §2「take as a rule」）：
 * 「every error carries **the step it recovers to**, so "try again" does not restart the flow」。
 * ⇒ 每条错误消息都要写清「怎么改」，而不是只写「格式错」。
 *
 * 与 `mobile-app.md` §6「握手版本地板 API_VERSION≥31」的取舍见项目对照文档：
 * 本 App 面向 fanhao API40 **与** B 代 API16 仿真链路，不在解析层/握手层硬拒低版本，
 * 靠 `RobotSession.isUnsupported()` / -32601 降级；照抄地板会让 C2/C2+ 活体链路全部失效。
 */
object ConnectInputParser {
    /** 旧代码悄悄回落的默认端口；现在仍允许省略端口，但必须在 [ParsedTarget.note] 里说清。 */
    const val DEFAULT_PORT: Int = 7788
    const val BLE_PREFIX: String = "ble:"

    private val HOST_RE = Regex("^[A-Za-z0-9._-]+$")
    private val DIGITS_RE = Regex("^[0-9]+$")

    data class ParsedTarget(
        val target: ConnectTarget,
        /** 空串 = 无提示；非空 = 必须显示给用户的事实（如用了默认端口 / Mock 演示）。 */
        val note: String = "",
    )

    fun parse(rawInput: String): Result<ParsedTarget> {
        val raw = rawInput.trim()

        if (raw.isEmpty() || raw.equals("mock", ignoreCase = true)) {
            return Result.success(ParsedTarget(ConnectTarget.Mock, "Mock 演示会话（非实机读数）"))
        }

        if (raw.startsWith(BLE_PREFIX, ignoreCase = true)) {
            val serial = raw.substring(BLE_PREFIX.length).trim()
            if (serial.isEmpty()) return fail("ble: 后面缺机身 serial。请填 ble:<serial>，或留空使用 Mock")
            return Result.success(ParsedTarget(ConnectTarget.Ble(serial), "BLE 身份按 serial 记录（地址只作缓存）"))
        }

        val colon = raw.indexOf(':')
        val host: String
        val portText: String?
        if (colon < 0) {
            host = raw
            portText = null
        } else {
            if (raw.indexOf(':', colon + 1) >= 0) {
                return fail("检测到多个冒号；本机暂不支持裸 IPv6。请改用 IPv4 或域名，例如 192.168.1.5:7788")
            }
            host = raw.substring(0, colon).trim()
            portText = raw.substring(colon + 1).trim()
        }

        if (host.isEmpty()) return fail("主机地址为空。请填 IPv4 或域名，或留空使用 Mock 演示")
        if (!HOST_RE.matches(host)) {
            return fail("主机地址含非法字符「$host」。只允许字母/数字/点/下划线/连字符，例如 192.168.1.5")
        }

        val port: Int
        val note: String
        if (portText == null) {
            port = DEFAULT_PORT
            note = "未写端口，使用默认 $DEFAULT_PORT（如需改请写 host:端口）"
        } else {
            if (portText.isEmpty()) return fail("端口为空。请写 host:端口，或只写 host 使用默认 $DEFAULT_PORT")
            if (!DIGITS_RE.matches(portText)) {
                return fail("端口「$portText」不是整数。请改成 1–65535 的十进制数字，例如 7788")
            }
            val parsed = portText.toIntOrNull()
                ?: return fail("端口「$portText」超出整数范围。请改成 1–65535，例如 7788")
            if (parsed !in 1..65535) {
                return fail("端口 $parsed 越界（允许 1–65535）。请改成例如 7788；留空地址则用 Mock")
            }
            port = parsed
            note = ""
        }
        return Result.success(ParsedTarget(ConnectTarget.Tcp(host, port), note))
    }

    private fun fail(message: String): Result<ParsedTarget> =
        Result.failure(IllegalArgumentException(message))
}
