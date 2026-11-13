package io.microduck.app.update

import android.content.Intent
import android.os.Build
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.edit
import androidx.core.net.toUri
import io.microduck.app.core.UpdatePolicy
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 更新流程编排：单次手动触发 → GitHub REST API → 决策 → 下载 → SHA-256 → 签名 → 安装。
 *
 * 状态分层借鉴 KaringX/clashmi `auto_update_manager.dart`（_checking / _downloading 防重入、
 * 缓存检查状态）与 ImranR98/Obtainium（把「无 release / 无 APK / 网络失败」分成不同状态）。
 * 但不做后台轮询：GitHub Docs「Avoid polling」明确写反复 404 的资源不要每次轮询，
 * 本项目仓库当前就是 404，自动轮询只会白烧 60 次/小时的额度。
 */
class UpdateController(
    private val activity: AppCompatActivity,
    private val apiBase: String = GithubReleaseClient.API_BASE,
    private val extraAllowedHosts: Set<String> = emptySet(),
) {
    data class State(
        val text: String,
        val busy: Boolean = false,
        val canDownload: Boolean = false,
        val needsInstallPermission: Boolean = false,
        val releaseUrl: String? = null,
    )

    private val prefs = activity.getSharedPreferences("microduck_update", AppCompatActivity.MODE_PRIVATE)
    private val packageInfo = activity.packageManager.getPackageInfo(activity.packageName, 0)
    private val currentVersionName = packageInfo.versionName ?: "unknown"
    private val currentVersionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        packageInfo.longVersionCode.toInt()
    } else {
        @Suppress("DEPRECATION") packageInfo.versionCode
    }
    private val client = GithubReleaseClient("io.microduck.app/$currentVersionName (Android ${Build.VERSION.RELEASE})")
    private val installer = UpdateInstaller(activity)
    private val busy = AtomicBoolean(false)
    private var available: UpdatePolicy.Decision.Available? = null

    fun versionLabel(): String = "$currentVersionName ($currentVersionCode)"

    fun idleState(): State = State(
        text = "当前版本 ${versionLabel()} · " +
            (lastCheckText() ?: "尚未检查"),
    )

    private fun lastCheckText(): String? {
        val at = prefs.getLong(KEY_LAST_CHECK, 0L)
        if (at <= 0L) return null
        return "上次检查 " + java.text.SimpleDateFormat("MM-dd HH:mm", java.util.Locale.getDefault())
            .format(java.util.Date(at))
    }

    /** 只由用户点击触发；防重入，不自动轮询。 */
    fun check(onState: (State) -> Unit) {
        if (!busy.compareAndSet(false, true)) return
        ui(onState, State("正在检查 GitHub Releases…", busy = true))
        Thread {
            try {
                val release = client.latestRelease(apiBase)
                var manifestBody: String? = null
                if (release.code == 200 && release.body != null) {
                    val parsed = UpdatePolicy.parseRelease(release.body)
                    val manifestAsset = parsed?.assets?.firstOrNull {
                        it.name == UpdatePolicy.MANIFEST_ASSET &&
                            (UpdatePolicy.isAllowedAssetUrl(it.downloadUrl, extraAllowedHosts))
                    }
                    if (manifestAsset != null) {
                        manifestBody = client.asset(manifestAsset.downloadUrl).body
                    }
                }
                val decision = UpdatePolicy.decide(
                    currentVersionCode = currentVersionCode,
                    currentVersionName = currentVersionName,
                    httpCode = release.code,
                    rateLimitRemaining = release.remaining,
                    rateLimitReset = release.reset,
                    releaseBody = release.body,
                    manifestBody = manifestBody,
                    extraAllowedHosts = extraAllowedHosts,
                )
                prefs.edit { putLong(KEY_LAST_CHECK, System.currentTimeMillis()) }
                ui(onState, render(decision, release.code, release.body))
            } catch (e: Exception) {
                ui(onState, State("检查异常：" + e.javaClass.simpleName + " " + (e.message ?: "")))
            } finally {
                busy.set(false)
            }
        }.start()
    }

    private fun render(decision: UpdatePolicy.Decision, code: Int, rawBody: String?): State = when (decision) {
        is UpdatePolicy.Decision.Available -> {
            available = decision
            val mb = decision.asset.size / 1024.0 / 1024.0
            State(
                text = "发现新版本 ${decision.manifest.versionName} (${decision.manifest.versionCode}) · " +
                    "APK %.1f MB · 当前 ${versionLabel()}".format(mb),
                canDownload = true,
                releaseUrl = decision.htmlUrl,
            )
        }
        is UpdatePolicy.Decision.UpToDate -> State(
            text = "已是最新版本 ${decision.versionName} (${decision.versionCode})",
            releaseUrl = null,
        )
        UpdatePolicy.Decision.NoRelease -> State(
            // 本项目仓库当前真实状态：0 release / 0 tag，不能伪造成「已是最新」。
            text = "暂无正式发布（GitHub REST API 返回 404）· 仓库尚无 release/tag",
        )
        is UpdatePolicy.Decision.RateLimited -> State(
            text = "GitHub REST API 限流（未认证 60 次/小时）· " +
                (decision.resetAtEpochSec?.let { "重置于 $it（UTC 秒）" } ?: "请稍后再试"),
        )
        is UpdatePolicy.Decision.Failed -> State(
            // 网络层用 -1 表示连不上；把 body 里的异常类名带出来，不吞掉真实原因。
            text = if (code == -1) "网络不可用：" + (rawBody ?: "未知错误")
            else "检查失败：" + decision.reason,
        )
    }

    /** 下载 → 流式 SHA-256 比对 → 签名证书比对 → 安装会话。任一步失败都给真实状态。 */
    fun downloadAndInstall(onState: (State) -> Unit) {
        val target = available ?: run {
            ui(onState, State("请先检查更新，没有待下载的版本"))
            return
        }
        // Google《Publish your app》：用户可随时关掉该特殊权限 ⇒ 每次安装前重新查，
        // 未授权就先引导，不要下载完再失败（也不把「未授权」写成「安装失败」）。
        if (!installer.canRequestInstalls()) {
            ui(onState, State(
                text = "需要开启「安装未知应用」权限（Android 8+ 按来源授权）",
                canDownload = true,
                needsInstallPermission = true,
                releaseUrl = target.htmlUrl,
            ))
            return
        }
        if (!busy.compareAndSet(false, true)) return
        ui(onState, State("准备下载…", busy = true, canDownload = false, releaseUrl = target.htmlUrl))
        Thread {
            val dir = File(activity.cacheDir, "updates")
            val dest = File(dir, target.asset.name)
            // ClashMi：安装前清掉历史 APK，避免残留文件被误当作有效更新。
            dir.listFiles()?.filter { it.name.endsWith(".apk") || it.name.endsWith(".part") }
                ?.forEach { it.delete() }
            try {
                val result = client.download(target.asset.downloadUrl, dest, target.asset.size) { done, total ->
                    val pct = if (total > 0) (done * 100 / total).toInt() else -1
                    ui(onState, State(
                        text = if (pct >= 0) "下载中 $pct%（${done / 1024} / ${total / 1024} KB）"
                        else "下载中 ${done / 1024} KB",
                        busy = true, releaseUrl = target.htmlUrl,
                    ))
                }
                // 单一出口、不用非局部 return：SAM lambda 的标签语义容易踩坑，
                // 且失败路径必须和成功路径一样走到 finally 释放 busy 标志。
                val downloadError = (result as? GithubReleaseClient.DownloadResult.Failure)?.reason
                if (downloadError != null) {
                    ui(onState, State("下载失败：$downloadError",
                        canDownload = true, releaseUrl = target.htmlUrl))
                } else {
                    val success = result as GithubReleaseClient.DownloadResult.Success
                    if (!UpdatePolicy.verifySha256(target.manifest.sha256, success.sha256)) {
                        dest.delete()
                        ui(onState, State("SHA-256 校验不符，已删除下载文件（不安装）",
                            canDownload = true, releaseUrl = target.htmlUrl))
                    } else {
                        ui(onState, State("下载完成，正在校验签名证书…", busy = true,
                            releaseUrl = target.htmlUrl))
                        when (val verify = installer.verifySignature(dest)) {
                            is UpdateInstaller.VerifyResult.Match -> {
                                ui(onState, State("签名一致，提交安装会话…", busy = true,
                                    releaseUrl = target.htmlUrl))
                                // Session 写入在后台线程做；receiver 未指定 Handler ⇒
                                // onReceive 走主线程，系统确认弹窗的 startActivity 也在主线程。
                                installer.install(dest) { msg ->
                                    ui(onState, State(msg, releaseUrl = target.htmlUrl))
                                }
                            }
                            is UpdateInstaller.VerifyResult.Mismatch -> {
                                dest.delete()
                                ui(onState, State("拒绝安装：" + verify.detail,
                                    releaseUrl = target.htmlUrl))
                            }
                            is UpdateInstaller.VerifyResult.Error -> {
                                dest.delete()
                                ui(onState, State("签名校验出错，不安装：" + verify.detail,
                                    releaseUrl = target.htmlUrl))
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                ui(onState, State("更新异常：" + e.javaClass.simpleName + " " + (e.message ?: "")))
            } finally {
                busy.set(false)
            }
        }.start()
    }

    fun openInstallPermissionSettings() = installer.openInstallPermissionSettings()

    fun canRequestInstalls(): Boolean = installer.canRequestInstalls()

    fun openReleasePage(url: String) {
        activity.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
    }

    fun release() {
        installer.unregister()
    }

    private fun ui(onState: (State) -> Unit, state: State) {
        activity.runOnUiThread {
            if (!activity.isFinishing && !activity.isDestroyed) onState(state)
        }
    }

    private companion object {
        const val KEY_LAST_CHECK = "last_check_epoch_ms"
    }
}
