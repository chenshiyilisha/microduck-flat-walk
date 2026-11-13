package io.microduck.app.update

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import android.provider.Settings
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import java.io.File
import java.security.MessageDigest

/**
 * 安装权限、签名证书校验、安装会话。
 *
 * 一手依据（逐条核验 2026-11-13）：
 *  · Google Android《Publish your app / User opt-in for unknown apps and sources》：
 *    Android 8.0 (API 26)+ 用户必须在「Install unknown apps」按来源授权；
 *    「a source that installs unknown apps should always call canRequestPackageInstalls()」。
 *    该权限是特殊权限，不能用 requestPermissions() 动态授予 ⇒ 跳
 *    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES + "package:<本包名>"。
 *  · Android Intent reference / AOSP Intent.java：`ACTION_INSTALL_PACKAGE`
 *    「Deprecated in API level 29. use PackageInstaller instead」。
 *    ⚠️ Tobi823/ffupdater 的 IntentInstaller.kt 仍用这个 deprecated action（加 @Suppress）。
 *    这里按官方推荐改用 PackageInstaller.Session：MODE_FULL_INSTALL + setAppPackageName
 *    + setSize + openWrite/fsync/commit(IntentSender)，并用 EXTRA_STATUS 观察结果。
 *  · Google Android《为应用签名 / 签名注意事项》：
 *    「当安装应用的更新时，系统会比较新版本和现有版本中的证书。如果证书匹配，系统就会
 *    允许更新。如果使用不同的证书为新版本签名，您必须为应用分配另一个软件包名称」。
 *    ⇒ 安装前把下载 APK 的签名证书指纹与已安装 App 比对（借鉴
 *    Tobi823/ffupdater `installer/impl/CertificateVerifier.kt` 的 FingerprintValidator 思路）。
 *  · PackageInstaller 常量经本机 android-35/android.jar `javap -constants` 实证：
 *    STATUS_SUCCESS=0 / STATUS_PENDING_USER_ACTION=-1 / EXTRA_STATUS / EXTRA_STATUS_MESSAGE。
 *
 * ⛔ 不引入 Root/Shizuku/厂商定制结果解码器（Obtainium / FFUpdater 有，本项目单设备场景不需要）。
 */
class UpdateInstaller(private val activity: AppCompatActivity) {

    sealed class VerifyResult {
        object Match : VerifyResult()
        data class Mismatch(val detail: String) : VerifyResult()
        data class Error(val detail: String) : VerifyResult()
    }

    companion object {
        private const val ACTION_INSTALL_RESULT = "io.microduck.app.UPDATE_INSTALL_RESULT"
        private const val RESULT_REQ_CODE = 4701
        private const val HEX_CHARS = "0123456789abcdef"
    }

    private var receiver: BroadcastReceiver? = null

    /** 特殊权限：每次操作前都重新查，用户随时可能在系统设置里关掉。
     *  minSdk=26 正好是 API O，canRequestPackageInstalls() 全版本可用，
     *  不需要 SDK_INT 分支（lint ObsoleteSdkInt：写 < O 分支是永远不走的死代码）。 */
    fun canRequestInstalls(): Boolean = activity.packageManager.canRequestPackageInstalls()

    fun openInstallPermissionSettings() {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            ("package:" + activity.packageName).toUri(),
        )
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
    }

    /** 已声明但未授权时给 UI 的准确提示（不把「未授权」伪装成「安装失败」）。 */
    fun permissionDeclared(): Boolean =
        activity.packageManager.checkPermission(
            Manifest.permission.REQUEST_INSTALL_PACKAGES, activity.packageName,
        ) == PackageManager.PERMISSION_GRANTED

    /**
     * 比对下载 APK 与已安装 App 的签名证书 SHA-256 指纹集合。
     * 多签名场景用集合相等（单签名时退化为单值比较），空集合直接判失败不假绿。
     */
    fun verifySignature(apk: File): VerifyResult = try {
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            PackageManager.GET_SIGNING_CERTIFICATES
        } else {
            @Suppress("DEPRECATION") PackageManager.GET_SIGNATURES
        }
        val installed = signingHashes(
            activity.packageManager.getPackageInfo(activity.packageName, flags),
        )
        val downloaded = signingHashes(
            activity.packageManager.getPackageArchiveInfo(apk.absolutePath, flags),
        )
        when {
            installed.isEmpty() || downloaded.isEmpty() ->
                VerifyResult.Error("无法读取签名证书（已安装 ${installed.size} / 下载 ${downloaded.size}）")
            installed != downloaded ->
                VerifyResult.Mismatch("下载包签名与已安装 App 不一致，覆盖安装会被系统当成新应用")
            else -> VerifyResult.Match
        }
    } catch (e: Exception) {
        VerifyResult.Error(e.javaClass.simpleName + ": " + (e.message ?: ""))
    }

    private fun signingHashes(info: PackageInfo?): Set<String> {
        if (info == null) return emptySet()
        val sigs: Array<Signature> = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.signingInfo?.apkContentsSigners ?: emptyArray()
        } else {
            @Suppress("DEPRECATION") info.signatures ?: emptyArray()
        }
        return sigs.map { sig ->
            MessageDigest.getInstance("SHA-256").digest(sig.toByteArray()).toHex()
        }.toSet()
    }

    /**
     * 创建并提交安装会话；结果通过广播回传，每一类状态都给真实文案。
     * onStatus 在主线程回调（registerReceiver 未指定 Handler 时走主线程）。
     */
    fun install(apk: File, onStatus: (String) -> Unit) {
        if (!canRequestInstalls()) {
            onStatus("需要「安装未知应用」权限，请先在系统设置里开启")
            return
        }
        unregister()
        val filter = IntentFilter(ACTION_INSTALL_RESULT)
        val r = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, Int.MIN_VALUE)
                val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()
                when (status) {
                    PackageInstaller.STATUS_SUCCESS -> onStatus("安装完成")
                    PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                        // 系统要求用户确认：这是正常状态，不是失败（见 raylabs 架构文与
                        // PackageInstaller 文档的 STATUS_PENDING_USER_ACTION 语义）。
                        @Suppress("DEPRECATION")
                        val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                        if (confirm != null) {
                            confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            context.startActivity(confirm)
                            onStatus("等待用户在系统弹窗中确认安装…")
                        } else {
                            onStatus("等待用户确认（系统未提供确认 Intent）")
                        }
                    }
                    Int.MIN_VALUE -> onStatus("安装结果缺失 STATUS 字段")
                    else -> onStatus("安装失败：status=$status $msg")
                }
            }
        }
        receiver = r
        ContextCompat.registerReceiver(
            activity, r, filter, ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        try {
            val installer = activity.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(
                PackageInstaller.SessionParams.MODE_FULL_INSTALL,
            ).apply {
                setAppPackageName(activity.packageName)
                setSize(apk.length())
            }
            val sessionId = installer.createSession(params)
            // 🔴 真机实测（vivo V2338A / Android 16，2026-11-13）：用 FLAG_IMMUTABLE 时
            //    commit() 直接抛 IllegalArgumentException「The commit() status receiver
            //    should come from a mutable PendingIntent」。一手依据：
            //    developer.android.com/reference/android/content/pm/PackageInstaller.Session
            //    commit(IntentSender) 原文「Throws IllegalArgumentException if the statusReceiver
            //    from an immutable PendingIntent when caller has a target SDK of API version
            //    35 or above」——本项目 targetSdk=35 正好命中；AOSP PackageInstaller.java
            //    的 commitSessionAfterInstallConstraintsAreMet 亦同（VANILLA_ICE_CREAM）。
            //    原因：系统要往这个 Intent 里填 EXTRA_STATUS / EXTRA_STATUS_MESSAGE，
            //    不可变 PendingIntent 不允许 fillIn。
            //    安全性：Intent 显式 setPackage(本包名) + receiver 注册为
            //    RECEIVER_NOT_EXPORTED，外部 App 无法伪造或截获该状态广播。
            val pending = android.app.PendingIntent.getBroadcast(
                activity, RESULT_REQ_CODE,
                Intent(ACTION_INSTALL_RESULT).setPackage(activity.packageName),
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or
                    android.app.PendingIntent.FLAG_MUTABLE,
            )
            installer.openSession(sessionId).use { session ->
                session.openWrite("base.apk", 0, apk.length()).use { out ->
                    apk.inputStream().use { input -> input.copyTo(out) }
                    session.fsync(out)
                }
                session.commit(pending.intentSender)
            }
            onStatus("安装会话已提交，等待系统处理…")
        } catch (e: Exception) {
            onStatus("安装会话创建失败：" + e.javaClass.simpleName + " " + (e.message ?: ""))
        }
    }

    fun unregister() {
        receiver?.let {
            try { activity.unregisterReceiver(it) } catch (_: IllegalArgumentException) { }
        }
        receiver = null
    }

    private fun ByteArray.toHex(): String = buildString(size * 2) {
        for (b in this@toHex) {
            val v = b.toInt() and 0xFF
            append(HEX_CHARS[v ushr 4]); append(HEX_CHARS[v and 0x0F])
        }
    }
}
