package io.microduck.app.ssh

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/**
 * 主板 SSH 凭据安全存储。
 *
 * 项目铁律（2026-11-14《SSH 只读实机验收》）：凭据只在进程内存用一次即删，
 * 永不写文件 / 日志 / git。本类把「用户显式要保存的登录信息」存进
 * EncryptedSharedPreferences —— 底层由 Android Keystore 主密钥加密，落盘内容仍是密文，
 * 不违反「明文不落盘」原则（明文仅在内存中短暂存在）。
 *
 * 默认主机/用户/端口按本机板子真实环境预填（192.168.50.216 / radxa / 22），
 * 用户可在设置页修改；密码默认空（首次需输入）。
 */
object SshCredentialStore {

    private const val FILE = "microduck_ssh_creds"
    private const val K_HOST = "host"
    private const val K_PORT = "port"
    private const val K_USER = "user"
    private const val K_PASS = "password"

    private const val DEFAULT_HOST = "192.168.50.216"
    private const val DEFAULT_PORT = 22
    private const val DEFAULT_USER = "radxa"

    private fun prefs(ctx: Context): SharedPreferences {
        // security-crypto 1.0.0：无 MasterKey 类，用 MasterKeys.getOrCreate 生成
        // AES256_GCM 主密钥文件，返回其路径（String），作为 create 的第 2 参。
        val masterKeyFile = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            FILE,
            masterKeyFile,
            ctx,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    data class Creds(
        val host: String,
        val port: Int,
        val user: String,
        val password: String,
    )

    fun load(ctx: Context): Creds {
        val p = prefs(ctx)
        return Creds(
            host = p.getString(K_HOST, DEFAULT_HOST) ?: DEFAULT_HOST,
            port = (p.getString(K_PORT, null) ?: DEFAULT_PORT.toString()).toIntOrNull()
                ?: DEFAULT_PORT,
            user = p.getString(K_USER, DEFAULT_USER) ?: DEFAULT_USER,
            password = p.getString(K_PASS, "") ?: "",
        )
    }

    fun save(ctx: Context, creds: Creds) {
        prefs(ctx).edit().apply {
            putString(K_HOST, creds.host)
            putString(K_PORT, creds.port.toString())
            putString(K_USER, creds.user)
            putString(K_PASS, creds.password)
            apply()
        }
    }
}
