package io.microduck.app.core

/**
 * 十六进制编码的**单一真源**（core 层，纯 JVM，可脱机自检）。
 *
 * 为什么收敛到这里（2026-11-13 发布前加固，非修 bug）：
 *   GithubReleaseClient.kt 与 UpdateInstaller.kt 原先各写一份私有的 ByteArray.toHex()，
 *   两条消费链复制同一段编码逻辑，但 core 自检只测「两个 hex 字符串是否相等」
 *   （UpdatePolicy.verifySha256），**测不到编码本身**——若哪天字符表被抄错，
 *   输出仍是一串合法 hex 字符、看起来完全合理，却能骗过全部字符串断言。
 *   收敛到 core 后，编码可被自检覆盖：用 JDK17 java.util.HexFormat 作独立实现
 *   互算 + 故意用错表做负对照，确认「抄错表」必然变红。
 *
 * 实现刻意不写字符表字面量：每位由 ASCII 码推算，杜绝「抄错一张表」。
 * core 跑在 Android（minSdk 26）上，因此不能用 JDK17 才有的 java.util.HexFormat；
 * 后者只在 core 自检里作为独立算法做互算核对。
 *
 * 一手依据：Google Android《为应用签名》要求更新包与已装包证书一致（本项目据此比对指纹）；
 * JDK17 标准库 `java.util.HexFormat.of().formatHex(ByteArray)`（自检侧独立实现）。
 *
 * ⛔ 两条消费链必须 import 同一个函数，不许各自复制实现；core 自检会跨文件静态核对。
 */
object Hex {
    private fun digit(nibble: Int): Char =
        if (nibble < 10) ('0'.code + nibble).toChar()
        else ('a'.code + nibble - 10).toChar()

    fun encode(bytes: ByteArray): String = buildString(bytes.size * 2) {
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            append(digit(v ushr 4))
            append(digit(v and 0x0F))
        }
    }
}
