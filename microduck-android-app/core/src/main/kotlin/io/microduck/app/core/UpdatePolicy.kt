package io.microduck.app.core

import com.google.gson.JsonParser
import java.util.Locale

/**
 * GitHub Releases 自更新的「纯 JVM 决策层」：不含 Android API、不含网络 API，
 * 因此可脱离模拟器用 tools/selftest.sh 真编译真跑（含负对照）。
 *
 * 设计依据（逐条一手，见 docs/active/microduck-安卓App-GitHub发布更新设计依据-2026-11-13.md）：
 *  · GitHub Docs「REST API endpoints for releases」：GET /repos/{owner}/{repo}/releases/latest
 *    返回「the most recent non-prerelease, non-draft release」，响应含 tag_name / html_url /
 *    assets[].name / assets[].browser_download_url / assets[].size。
 *  · GitHub Docs「Best practices / Rate limits」：未认证 60 次/小时；403/429 不要重试到
 *    x-ratelimit-reset；反复 404 的资源不要每次轮询 ⇒ 本 App 只由用户手动点击触发。
 *  · javiersantos/AppUpdater 的 ParserJSON.java / app/update.json：latestVersion +
 *    latestVersionCode 双字段 ⇒ 这里用 versionCode 作主判据（Google《对应用进行版本控制》：
 *    「数字越大表示版本越新」「Android 系统使用 versionCode 值来防止降级」）。
 *  · ImranR98/Obtainium 的 lib/app_sources/github.dart：从 assets 里筛 .apk、
 *    把「无 release / 无 APK / 用户过滤掉」分成不同状态，不混成一个「检查失败」。
 *  · KaringX/clashmi 的 auto_update_utils.dart：清单里带 sha256，下载后比对，不符删文件。
 *  · Tobi823/ffupdater 的 VersionCompareHelper.kt：版本解析失败要兜底，不能因为解析不了
 *    就默认「已是最新」⇒ 这里返回 null 并转成 Failed，绝不静默当作 UpToDate。
 *
 * ⛔ 铁律：本文件所有结论都必须能从输入推出；无法判定一律 Failed / null，
 * 绝不「看起来合理就当成功」（UNVERIFIED != PASS）。
 */
object UpdatePolicy {

    /** 发布脚本生成的机器可读清单，作为 release asset 上传。 */
    const val MANIFEST_ASSET = "update.json"
    const val MANIFEST_SCHEMA = 1
    const val APK_EXTENSION = ".apk"
    const val SHA256_HEX_LENGTH = 64
    /** App 侧提交安装会话所需的特殊权限；core 自检会真读 Manifest 逐字核对。 */
    const val REQUIRED_MANIFEST_PERMISSION = "android.permission.REQUEST_INSTALL_PACKAGES"

    /** 只接受 GitHub 官方下载域；避免清单里塞任意 URL 变成任意来源的 APK 加载器。 */
    private val ALLOWED_ASSET_HOSTS = setOf("github.com", "www.github.com")

    data class Asset(val name: String, val downloadUrl: String, val size: Long)

    data class Release(
        val tagName: String,
        val name: String,
        val htmlUrl: String,
        val publishedAt: String,
        val prerelease: Boolean,
        val draft: Boolean,
        val assets: List<Asset>,
    )

    /**
     * update.json 的字段。versionCode 是权威新旧判据；sha256 是下载完整性判据；
     * apkAsset 精确指定本设备该装哪个包（ClashMi 按 abis 选包 + Obtainium 按名筛 .apk）。
     */
    data class Manifest(
        val schema: Int,
        val versionName: String,
        val versionCode: Int,
        val apkAsset: String,
        val sha256: String,
        val minSdk: Int,
        val abi: String,
    )

    /** 检查结果：每一类都是真实可观测量，不合并、不伪造。 */
    sealed class Decision {
        data class UpToDate(val versionName: String, val versionCode: Int) : Decision()
        data class Available(
            val manifest: Manifest,
            val asset: Asset,
            val htmlUrl: String,
        ) : Decision()

        /** HTTP 404：仓库还没有任何正式 release（本项目当前真实状态）。 */
        object NoRelease : Decision()
        data class RateLimited(val resetAtEpochSec: Long?) : Decision()
        data class Failed(val reason: String) : Decision()
    }

    // ---------------------------------------------------------------- 解析

    /** 解析 GitHub release JSON；任何字段缺失/类型错误都返回 null，不抛异常到 UI。 */
    fun parseRelease(body: String): Release? = try {
        val root = JsonParser.parseString(body).asJsonObject
        val assets = root.getAsJsonArray("assets")?.mapNotNull { el ->
            val o = el.asJsonObject
            val name = o.str("name") ?: return@mapNotNull null
            val url = o.str("browser_download_url") ?: return@mapNotNull null
            Asset(name, url, o.longOrZero("size"))
        } ?: emptyList()
        Release(
            tagName = root.str("tag_name") ?: return null,
            name = root.str("name") ?: "",
            htmlUrl = root.str("html_url") ?: "",
            publishedAt = root.str("published_at") ?: "",
            prerelease = root.boolOrFalse("prerelease"),
            draft = root.boolOrFalse("draft"),
            assets = assets,
        )
    } catch (_: Exception) {
        null
    }

    /** 解析发布脚本生成的 update.json，字段必须齐全且类型正确。 */
    fun parseManifest(body: String): Manifest? = try {
        val o = JsonParser.parseString(body).asJsonObject
        Manifest(
            schema = o.intOrMinusOne("schema"),
            versionName = o.str("versionName") ?: return null,
            versionCode = o.intOrMinusOne("versionCode"),
            apkAsset = o.str("apkAsset") ?: return null,
            sha256 = o.str("sha256") ?: return null,
            minSdk = o.intOrMinusOne("minSdk"),
            abi = o.str("abi") ?: "",
        )
    } catch (_: Exception) {
        null
    }

    /**
     * 主判据：manifest.versionCode 必须严格大于当前 versionCode。
     * 次判据：versionName 数值比较（仅用于显示/兜底，解析不了返回 null）。
     * tag 与 manifest.versionName 必须一致（发布脚本写错时早失败，不装错包）。
     */
    fun decide(
        currentVersionCode: Int,
        currentVersionName: String,
        httpCode: Int,
        rateLimitRemaining: Int?,
        rateLimitReset: Long?,
        releaseBody: String?,
        manifestBody: String?,
        /** 仅用于 debug 端到端验证（PC 本地服务）；生产路径恒为 emptySet()。 */
        extraAllowedHosts: Set<String> = emptySet(),
    ): Decision {
        when {
            httpCode == 404 -> return Decision.NoRelease
            httpCode == 403 || httpCode == 429 -> {
                // GitHub Docs：403/429 且 x-ratelimit-remaining=0 才是主限流，此时才按
                // x-ratelimit-reset 退避；其它 403/429 不编造可重试时间。
                val reset = if (rateLimitRemaining == 0) rateLimitReset else null
                return Decision.RateLimited(reset)
            }
            httpCode != 200 -> return Decision.Failed("HTTP $httpCode")
        }
        val release = releaseBody?.let { parseRelease(it) }
            ?: return Decision.Failed("release JSON 无法解析")
        // latest 端点按文档排除 draft / prerelease；若出现说明数据源异常，不能当正式发布。
        if (release.draft || release.prerelease) {
            return Decision.Failed("latest 返回了 draft/prerelease，不视为正式发布")
        }
        val manifestAsset = release.assets.firstOrNull { it.name == MANIFEST_ASSET }
            ?: return Decision.Failed("release 缺少 $MANIFEST_ASSET，无法判定版本与校验值")
        val manifest = manifestBody?.let { parseManifest(it) }
            ?: return Decision.Failed("update.json 无法解析")
        val validation = validate(manifest, release.tagName)
        if (validation != null) return Decision.Failed(validation)
        val apk = release.assets.firstOrNull { it.name == manifest.apkAsset }
            ?: return Decision.Failed("清单指定的 APK asset 不存在：${manifest.apkAsset}")
        if (!apk.name.endsWith(APK_EXTENSION, ignoreCase = true)) {
            return Decision.Failed("清单指定的 asset 不是 .apk：${apk.name}")
        }
        if (!isAllowedAssetUrl(apk.downloadUrl, extraAllowedHosts)) {
            return Decision.Failed("APK 下载地址不是允许的域：${apk.downloadUrl}")
        }
        // Google《对应用进行版本控制》：versionCode 必须单调递增。若 versionName 已变但
        // versionCode 没涨，说明发布脚本漏改，装上去系统会静默拒绝（防降级）⇒ 早失败。
        val nameCmp = compareVersionName(currentVersionName, manifest.versionName)
        if (manifest.versionCode <= currentVersionCode && nameCmp != null && nameCmp < 0) {
            return Decision.Failed("versionName 已变但 versionCode 未递增，拒绝当作更新")
        }
        return if (manifest.versionCode > currentVersionCode) {
            Decision.Available(manifest, apk, release.htmlUrl)
        } else {
            Decision.UpToDate(manifest.versionName, manifest.versionCode)
        }
    }

    /** 返回错误原因；null 表示清单自洽。 */
    fun validate(manifest: Manifest, tagName: String): String? {
        if (manifest.schema != MANIFEST_SCHEMA) return "update.json schema=${manifest.schema}，期望 $MANIFEST_SCHEMA"
        if (manifest.versionCode <= 0) return "versionCode 必须为正整数（Android 官方要求单调递增）"
        if (manifest.minSdk <= 0) return "minSdk 缺失"
        if (!isSha256Hex(manifest.sha256)) return "sha256 不是 64 位十六进制"
        if (!manifest.apkAsset.endsWith(APK_EXTENSION, ignoreCase = true)) return "apkAsset 不是 .apk"
        // tag 约定 v<versionName>（发布脚本保证）；去掉 v 后必须逐字相等。
        if (tagName.removePrefix("v").removePrefix("V") != manifest.versionName) {
            return "tag($tagName) 与 versionName(${manifest.versionName}) 不一致"
        }
        return null
    }

    fun isSha256Hex(value: String): Boolean =
        value.length == SHA256_HEX_LENGTH && value.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }

    fun isAllowedAssetUrl(url: String, extraAllowedHosts: Set<String> = emptySet()): Boolean = try {
        val host = java.net.URI(url).host?.lowercase(Locale.ROOT)
        host != null && (host in ALLOWED_ASSET_HOSTS || host in extraAllowedHosts)
    } catch (_: Exception) {
        false
    }

    /** 下载后比对：大小写/trim 归一，但不接受空值（空校验值等于没有校验）。 */
    fun verifySha256(expected: String, actual: String): Boolean =
        isSha256Hex(expected) && expected.trim().equals(actual.trim(), ignoreCase = true)

    /**
     * 语义化数值比较；解析失败返回 null（调用方必须转成 Failed，不能当 UpToDate）。
     * 兼容 `v` 前缀与 `-p0-skeleton` 这类预发布后缀：数值段相等时，无后缀者更新。
     */
    fun compareVersionName(left: String, right: String): Int? {
        val a = numericParts(left) ?: return null
        val b = numericParts(right) ?: return null
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return if (x < y) -1 else 1
        }
        val pa = hasSuffix(left)
        val pb = hasSuffix(right)
        return when {
            pa == pb -> 0
            pa -> -1      // 有预发布后缀的更旧
            else -> 1
        }
    }

    private fun numericParts(raw: String): List<Int>? {
        val core = raw.trim().removePrefix("v").removePrefix("V").substringBefore('-')
        val parts = core.split('.')
        if (parts.isEmpty() || parts.any { it.isEmpty() }) return null
        return parts.map { it.toIntOrNull() ?: return null }
    }

    private fun hasSuffix(raw: String): Boolean = raw.trim().contains('-')

    // ---------------------------------------------------------------- Gson 取值小工具

    private fun com.google.gson.JsonObject.str(key: String): String? =
        if (has(key) && !get(key).isJsonNull) get(key).asString else null

    private fun com.google.gson.JsonObject.intOrMinusOne(key: String): Int = try {
        if (has(key) && get(key).isJsonPrimitive) get(key).asInt else -1
    } catch (_: Exception) {
        -1
    }

    private fun com.google.gson.JsonObject.longOrZero(key: String): Long = try {
        if (has(key) && get(key).isJsonPrimitive) get(key).asLong else 0L
    } catch (_: Exception) {
        0L
    }

    private fun com.google.gson.JsonObject.boolOrFalse(key: String): Boolean = try {
        has(key) && get(key).isJsonPrimitive && get(key).asBoolean
    } catch (_: Exception) {
        false
    }
}
