package io.microduck.app.update

import android.content.Intent
import android.os.Build
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.edit
import androidx.core.net.toUri
import io.microduck.app.core.Disposable
import io.microduck.app.core.UpdatePolicy
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 版本更新数据层 Repository —— 更新流程的**唯一持有者与状态出口**（重构阶段 1）。
 *
 * ── 为什么有它（重构规划单一权威）──
 * 见 `docs/active/microduck-安卓App-整体重构与架构重新规划-2026-11-16.md` §4 阶段 1。
 * 现状 `UpdateController` 在 View 层自管 `busy` / `available` / 状态文案，面板通过
 * `onState` 回调被动渲染。本 Repository 把「更新流程 + 由流程派生的不可变快照」收进
 * 数据层，成为单一真源（SSOT）：面板只观察快照、发动作，不再各自维护一份流程状态。
 *
 * ── 位置：app 模块（非 core）──
 * 规划原文把 `UpdateRepository` 画在 core，但更新依赖 Android API
 * （`PackageManager` / `PackageInstaller` / `Intent` / `SharedPreferences`）与
 * `GithubReleaseClient`（Android 侧网络），无法进纯 Kotlin/JVM、零 Android 依赖的 core。
 * 故按实际依赖落在 **app 模块**数据层，机制与 core `RobotRepository` 完全一致
 * （不可变快照 + 监听器 + 同步动作入口）。**意图与规划一致，位置按依赖适配**，特此说明。
 *
 * ── 决策逻辑仍在 core ──
 * 「检查 → 决策 → 下载 → 校验 → 安装」的**纯逻辑决策**（`UpdatePolicy.decide` /
 * `verifySha256`）本就在 core（纯 Kotlin/JVM），Repository 只负责编排与状态出口，
 * 不重复实现决策，避免两套逻辑漂移。
 *
 * ── 快照不可变 ──
 * [Snapshot] 是 `data class`，每次状态变化**整体替换**一个新实例，监听者拿到的是冻结的
 * 快照，杜绝「读到中途被改」的竞态。
 *
 * ── 线程模型 ──
 * 与 core `RobotRepository` 同构：网络/安装会话在后台线程，快照发布经 [publish] 在锁内
 * 替换、锁外回调，监听器回调可自行切线程。动作（check / downloadAndInstall）是同步入口、
 * 内部托管线程，并用 [busy] 防重入（借鉴 KaringX/clashmi 的 `_checking/_downloading` 防重入）。
 *
 * ── 双轨 ──
 * 阶段 1 只**新增**本 Repository，`UpdateController` / `UpdatePanel` 暂不切换（旧路径继续
 * 工作），门禁保持绿后再在阶段 3 把面板接到本 Repository。
 */
class UpdateRepository(
    private val activity: AppCompatActivity,
    private val apiBase: String = GithubReleaseClient.API_BASE,
    private val extraAllowedHosts: Set<String> = emptySet(),
) {

    /**
     * 不可变更新流程快照 —— 数据层对外的**唯一状态出口**。
     *
     * 字段与 `UpdateController.State` 对齐（面板渲染所需），外加流程阶段与版本信息。
     * 所有可选量 nullable，缺数据 ≠ 零（项目铁律）。
     */
    data class Snapshot(
        /** 面向 UI 的状态文案（真实 HTTP 结果，不伪造）。 */
        val text: String,
        /** 是否有流程在执行（检查 / 下载 / 安装），用于禁用按钮。 */
        val busy: Boolean,
        /** 是否可点「下载并安装」（发现了可用新版本）。 */
        val canDownload: Boolean,
        /** 是否需要先开「安装未知应用」权限。 */
        val needsInstallPermission: Boolean,
        /** Release 页面 URL；null = 无。 */
        val releaseUrl: String?,
        /** 当前版本标签 `name (code)`。 */
        val versionLabel: String,
        /** 流程阶段名（IDLE/CHECKING/AVAILABLE/…），供调试与未来着色。 */
        val phase: String,
    )

    // ── 内部状态（唯一真源）──
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

    @Volatile private var text = ""
    @Volatile private var canDownload = false
    @Volatile private var needsInstallPermission = false
    @Volatile private var releaseUrl: String? = null
    @Volatile private var phase = "IDLE"

    /** 当前版本标签 `name (code)`。 */
    val versionLabel: String get() = "$currentVersionName ($currentVersionCode)"

    // ── 快照出口（声明在版本信息之后，确保 initialSnapshot 读到已初始化的 versionLabel）──
    private val lock = Any()
    private val listeners = mutableListOf<(Snapshot) -> Unit>()
    @Volatile private var current: Snapshot = initialSnapshot()

    /** 当前快照（只读快照，不暴露可变内部状态）。 */
    fun snapshot(): Snapshot = current

    /** 订阅快照变化；返回 [Disposable]。与 core `RobotRepository.onSnapshot` 同构。 */
    fun onSnapshot(cb: (Snapshot) -> Unit): Disposable {
        synchronized(lock) { listeners.add(cb) }
        return Disposable { synchronized(lock) { listeners.remove(cb) } }
    }

    /**
     * 由当前所有 [@Volatile] 字段**重建**一个不可变快照。
     *
     * 🔴 与 core `RobotRepository.build` 同一条铁律：状态分散在多个 `@Volatile` 字段里，
     * 若 `publish` 直接把上一次存的 `current` 再存回去，更新了字段也不会反映到快照
     * （读数 vs 实际矛盾）。⇒ 发布时**从字段重建**，保证快照与内部状态始终一致。
     */
    private fun build(): Snapshot = Snapshot(
        text = text,
        busy = busy.get(),
        canDownload = canDownload,
        needsInstallPermission = needsInstallPermission,
        releaseUrl = releaseUrl,
        versionLabel = versionLabel,
        phase = phase,
    )

    /** 重建快照、存储、锁外回调监听者。 */
    private fun publish() {
        val s = build()
        current = s
        val cbs = synchronized(lock) { listeners.toList() }
        cbs.forEach { it(s) }
    }

    private fun initialSnapshot() = Snapshot(
        text = "当前版本 $versionLabel · 尚未检查",
        busy = false, canDownload = false, needsInstallPermission = false,
        releaseUrl = null, versionLabel = versionLabel, phase = "IDLE",
    )

    /** 只由用户点击触发；防重入，不自动轮询（GitHub Docs「Avoid polling」）。 */
    fun check() {
        if (!busy.compareAndSet(false, true)) return
        text = "正在检查 GitHub Releases…"
        phase = "CHECKING"
        publish()
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
                render(decision, release.code, release.body)
            } catch (e: Exception) {
                text = "检查异常：" + e.javaClass.simpleName + " " + (e.message ?: "")
                phase = "ERROR"
            } finally {
                busy.set(false)
                publish()
            }
        }.start()
    }

    private fun render(decision: UpdatePolicy.Decision, code: Int, rawBody: String?) {
        when (decision) {
            is UpdatePolicy.Decision.Available -> {
                available = decision
                val mb = decision.asset.size / 1024.0 / 1024.0
                text = "发现新版本 ${decision.manifest.versionName} (${decision.manifest.versionCode}) · " +
                    "APK %.1f MB · 当前 $versionLabel".format(mb)
                canDownload = true
                releaseUrl = decision.htmlUrl
                phase = "AVAILABLE"
            }
            is UpdatePolicy.Decision.UpToDate -> {
                text = "已是最新版本 ${decision.versionName} (${decision.versionCode})"
                canDownload = false
                releaseUrl = null
                phase = "UP_TO_DATE"
            }
            UpdatePolicy.Decision.NoRelease -> {
                // 本项目仓库当前真实状态：0 release / 0 tag，不能伪造成「已是最新」。
                text = "暂无正式发布（GitHub REST API 返回 404）· 仓库尚无 release/tag"
                canDownload = false
                releaseUrl = null
                phase = "NO_RELEASE"
            }
            is UpdatePolicy.Decision.RateLimited -> {
                text = "GitHub REST API 限流（未认证 60 次/小时）· " +
                    (decision.resetAtEpochSec?.let { "重置于 $it（UTC 秒）" } ?: "请稍后再试")
                canDownload = false
                releaseUrl = null
                phase = "RATE_LIMITED"
            }
            is UpdatePolicy.Decision.Failed -> {
                // 网络层用 -1 表示连不上；把 body 里的异常类名带出来，不吞掉真实原因。
                text = if (code == -1) "网络不可用：" + (rawBody ?: "未知错误")
                else "检查失败：" + decision.reason
                canDownload = false
                releaseUrl = null
                phase = "FAILED"
            }
        }
        publish()
    }

    /** 下载 → 流式 SHA-256 比对 → 签名证书比对 → 安装会话。任一步失败都给真实状态。 */
    fun downloadAndInstall() {
        val target = available ?: run {
            text = "请先检查更新，没有待下载的版本"
            phase = "IDLE"
            publish()
            return
        }
        // Google《Publish your app》：用户可随时关掉该特殊权限 ⇒ 每次安装前重新查，
        // 未授权就先引导，不要下载完再失败（也不把「未授权」写成「安装失败」）。
        if (!installer.canRequestInstalls()) {
            text = "需要开启「安装未知应用」权限（Android 8+ 按来源授权）"
            canDownload = true
            needsInstallPermission = true
            releaseUrl = target.htmlUrl
            phase = "NEEDS_PERMISSION"
            publish()
            return
        }
        if (!busy.compareAndSet(false, true)) return
        text = "准备下载…"
        canDownload = false
        releaseUrl = target.htmlUrl
        phase = "DOWNLOADING"
        publish()
        Thread {
            val dir = File(activity.cacheDir, "updates")
            val dest = File(dir, target.asset.name)
            // ClashMi：安装前清掉历史 APK，避免残留文件被误当作有效更新。
            dir.listFiles()?.filter { it.name.endsWith(".apk") || it.name.endsWith(".part") }
                ?.forEach { it.delete() }
            try {
                val result = client.download(target.asset.downloadUrl, dest, target.asset.size) { done, total ->
                    val pct = if (total > 0) (done * 100 / total).toInt() else -1
                    text = if (pct >= 0) "下载中 $pct%（${done / 1024} / ${total / 1024} KB）"
                    else "下载中 ${done / 1024} KB"
                    releaseUrl = target.htmlUrl
                    phase = "DOWNLOADING"
                    publish()
                }
                // 单一出口、不用非局部 return：失败路径必须和成功路径一样走到 finally 释放 busy。
                val downloadError = (result as? GithubReleaseClient.DownloadResult.Failure)?.reason
                if (downloadError != null) {
                    text = "下载失败：$downloadError"
                    canDownload = true
                    releaseUrl = target.htmlUrl
                    phase = "DOWNLOAD_FAILED"
                } else {
                    val success = result as GithubReleaseClient.DownloadResult.Success
                    if (!UpdatePolicy.verifySha256(target.manifest.sha256, success.sha256)) {
                        dest.delete()
                        text = "SHA-256 校验不符，已删除下载文件（不安装）"
                        canDownload = true
                        releaseUrl = target.htmlUrl
                        phase = "SHA_MISMATCH"
                    } else {
                        text = "下载完成，正在校验签名证书…"
                        releaseUrl = target.htmlUrl
                        phase = "VERIFYING"
                        publish()
                        when (val verify = installer.verifySignature(dest)) {
                            is UpdateInstaller.VerifyResult.Match -> {
                                text = "签名一致，提交安装会话…"
                                phase = "INSTALLING"
                                publish()
                                // Session 写入在后台线程做；receiver 未指定 Handler ⇒
                                // onReceive 走主线程，系统确认弹窗的 startActivity 也在主线程。
                                installer.install(dest) { msg ->
                                    text = msg
                                    phase = "INSTALL_RESULT"
                                    publish()
                                }
                            }
                            is UpdateInstaller.VerifyResult.Mismatch -> {
                                dest.delete()
                                text = "拒绝安装：" + verify.detail
                                releaseUrl = target.htmlUrl
                                phase = "SIGNATURE_MISMATCH"
                            }
                            is UpdateInstaller.VerifyResult.Error -> {
                                dest.delete()
                                text = "签名校验出错，不安装：" + verify.detail
                                releaseUrl = target.htmlUrl
                                phase = "SIGNATURE_ERROR"
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                text = "更新异常：" + e.javaClass.simpleName + " " + (e.message ?: "")
                phase = "ERROR"
            } finally {
                busy.set(false)
                publish()
            }
        }.start()
    }

    fun openInstallPermissionSettings() = installer.openInstallPermissionSettings()

    fun canRequestInstalls(): Boolean = installer.canRequestInstalls()

    fun openReleasePage(url: String) {
        activity.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
    }

    /** 页面销毁时注销安装结果接收器，避免泄漏。 */
    fun release() {
        installer.unregister()
    }

    private companion object {
        const val KEY_LAST_CHECK = "last_check_epoch_ms"
    }
}
