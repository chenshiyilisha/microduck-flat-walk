package io.microduck.app.update

import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * GitHub REST API 读取 + APK 下载（Android 侧；core/UpdatePolicy 只做纯逻辑决策）。
 *
 * 一手依据：
 *  · GitHub Docs「REST API endpoints for releases」：GET /repos/{owner}/{repo}/releases/latest；
 *    assets[].browser_download_url 是「浏览器中用于获取资产二进制内容的下载位置」。
 *  · GitHub Docs「Troubleshooting the REST API / User agent required」：
 *    「Requests without a valid `User-Agent` header will be rejected. You should use your
 *    username or the name of your application for the `User-Agent` value.」⇒ 必须带 UA。
 *  · GitHub Docs「Best practices」：读 x-ratelimit-* 退避、跟随重定向、不要忽略 4xx/5xx。
 *    ⚠️ 这里**不写 X-GitHub-Api-Version**：官方文档说指定不存在的版本会 400，
 *    而本项目未核验当前可用的版本字面值，不写则使用服务端默认版本（实测 GET 正常）。
 *  · KaringX/clashmi `auto_update_manager.dart`：下载后算 SHA-256，不符就删文件。
 *  · Tobi823/ffupdater `network/exceptions/ApiRateLimitExceededException.kt`：限流是
 *    独立状态，不能混进「网络失败」。
 *
 * ⛔ 不做后台轮询：GitHub Docs「Avoid polling」+「Do not ignore errors」明确说反复 404
 * 的资源不要每次轮询 ⇒ 所有请求只由用户点击「检查更新 / 下载并安装」触发。
 */
class GithubReleaseClient(private val userAgent: String) {

    data class Response(
        val code: Int,
        val remaining: Int?,
        val reset: Long?,
        val body: String?,
    )

    sealed class DownloadResult {
        data class Success(val sha256: String, val bytes: Long) : DownloadResult()
        data class Failure(val reason: String) : DownloadResult()
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MS = 20_000
        private const val MAX_JSON_BYTES = 2 * 1024 * 1024L
        private const val MAX_APK_BYTES = 200L * 1024 * 1024
        private const val BUFFER_BYTES = 16 * 1024
        const val REPO_OWNER = "chenshiyilisha"
        const val REPO_NAME = "microduck-flat-walk"
        const val API_BASE = "https://api.github.com"
        private const val HEX_CHARS = "0123456789abcdef"
    }

    fun latestRelease(apiBase: String): Response =
        get("$apiBase/repos/$REPO_OWNER/$REPO_NAME/releases/latest")

    fun asset(urlText: String): Response = get(urlText)

    private fun get(urlText: String): Response = try {
        val conn = (URL(urlText).openConnection() as HttpURLConnection).apply {
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            instanceFollowRedirects = true       // GitHub Docs「Follow redirects」
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", userAgent)
            requestMethod = "GET"
        }
        try {
            val code = conn.responseCode
            val remaining = conn.getHeaderField("x-ratelimit-remaining")?.toIntOrNull()
            val reset = conn.getHeaderField("x-ratelimit-reset")?.toLongOrNull()
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.let { readBounded(it, MAX_JSON_BYTES) }
            Response(code, remaining, reset, body)
        } finally {
            conn.disconnect()
        }
    } catch (e: Exception) {
        // 真实网络异常不伪造 HTTP 码：用 -1 让上层明确显示「网络不可用」。
        Response(-1, null, null, e.javaClass.simpleName + ": " + (e.message ?: ""))
    }

    /**
     * 流式下载 + 流式 SHA-256；先写 .part 再原子改名，失败/校验不符删临时文件。
     * expectedSize 来自 release asset 的 size 字段，用于「量动没动」的完整性对照。
     */
    fun download(
        urlText: String,
        dest: File,
        expectedSize: Long,
        onProgress: (downloaded: Long, total: Long) -> Unit,
    ): DownloadResult {
        val part = File(dest.parentFile, dest.name + ".part")
        try {
            dest.parentFile?.mkdirs()
            val conn = (URL(urlText).openConnection() as HttpURLConnection).apply {
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = true
                setRequestProperty("Accept", "application/vnd.android.package-archive")
                setRequestProperty("User-Agent", userAgent)
                requestMethod = "GET"
            }
            try {
                if (conn.responseCode !in 200..299) {
                    return DownloadResult.Failure("下载 HTTP ${conn.responseCode}")
                }
                val total = if (expectedSize > 0) expectedSize else conn.contentLength.toLong()
                val digest = MessageDigest.getInstance("SHA-256")
                var written = 0L
                BufferedInputStream(conn.inputStream, BUFFER_BYTES).use { input ->
                    FileOutputStream(part).use { out ->
                        val buf = ByteArray(BUFFER_BYTES)
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            if (written + n > MAX_APK_BYTES) {
                                return DownloadResult.Failure("APK 超过上限 $MAX_APK_BYTES B")
                            }
                            out.write(buf, 0, n)
                            digest.update(buf, 0, n)
                            written += n
                            onProgress(written, total)
                        }
                    }
                }
                if (!part.renameTo(dest)) {
                    return DownloadResult.Failure("临时文件改名失败")
                }
                // size 为 0 视为「未提供」，不能拿 0 去否定实际下载量。
                if (expectedSize > 0 && written != expectedSize) {
                    dest.delete()
                    return DownloadResult.Failure("大小不符：期望 $expectedSize，实得 $written")
                }
                return DownloadResult.Success(digest.digest().toHex(), written)
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            part.delete()
            dest.delete()
            return DownloadResult.Failure(e.javaClass.simpleName + ": " + (e.message ?: ""))
        }
    }

    private fun readBounded(stream: java.io.InputStream, limit: Long): String {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(BUFFER_BYTES)
        var total = 0L
        while (true) {
            val n = stream.read(buf)
            if (n < 0) break
            total += n
            if (total > limit) throw IllegalStateException("响应超过 $limit B 上限")
            out.write(buf, 0, n)
        }
        return out.toString("UTF-8")
    }

    private fun ByteArray.toHex(): String = buildString(size * 2) {
        for (b in this@toHex) {
            val v = b.toInt() and 0xFF
            append(HEX_CHARS[v ushr 4]); append(HEX_CHARS[v and 0x0F])
        }
    }
}
