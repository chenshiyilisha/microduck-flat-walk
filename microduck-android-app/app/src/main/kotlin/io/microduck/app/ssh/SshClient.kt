package io.microduck.app.ssh

import com.jcraft.jsch.ChannelExec
import com.jcraft.jsch.ChannelShell
import com.jcraft.jsch.HostKey
import com.jcraft.jsch.JSch
import com.jcraft.jsch.Session
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * 主板 SSH 客户端（mwiede JSch 分支 0.2.19）。
 *
 * 设计要点：
 *  · 凭据来自 [SshCredentialStore]，明文仅在内存中短暂存在，不落盘、不进日志。
 *  · 主机密钥：开发/调试工具面向已知 LAN 内的板子，采用 `StrictHostKeyChecking=no`，
 *    但会把实际呈现的指纹回传给调用方显示（让用户肉眼核对，而非静默信任）。
 *  · 提供两类能力：`exec`（一次性命令，用于「一键休息」等按钮）与 `shell`
 *    （交互式 PTY，用于 SSH 终端 Activity）。
 */
class SshClient {

    data class ConnectResult(
        val session: Session,
        /** 实际呈现的主机公钥指纹（SHA256，OpenSSH 格式），供 UI 显示核对。 */
        val hostKeyFingerprint: String,
    )

    private var jsch: JSch = JSch()

    /**
     * 建立 SSH 会话。失败抛异常（调用方捕获后展示）。
     * @param acceptNewHost 是否接受未知主机密钥（LAN 调试默认 true，但指纹仍会上报）。
     */
    @Throws(Exception::class)
    fun connect(
        creds: SshCredentialStore.Creds,
        acceptNewHost: Boolean = true,
    ): ConnectResult {
        jsch = JSch()
        val session = jsch.getSession(creds.user, creds.host, creds.port)
        session.setPassword(creds.password)
        // 不依赖磁盘 known_hosts：LAN 内板子可能重刷镜像换密钥；接受但上报指纹。
        session.setConfig("StrictHostKeyChecking", if (acceptNewHost) "no" else "yes")
        // mwiede 分支已支持现代 KEX；显式收窄到安全算法，避免回退到弱算法。
        session.setConfig(
            "kex",
            "curve25519-sha256,ecdh-sha2-nistp256,diffie-hellman-group14-sha256," +
                "diffie-hellman-group-exchange-sha256",
        )
        session.setConfig("ServerHostKey", "ssh-ed25519,ecdsa-sha2-nistp256,rsa-sha2-512,rsa-sha2-256")
        session.timeout = 10_000
        session.connect(10_000)
        // jsch 0.2.19：session.hostKey 返回 HostKey 对象，取其 base64 公钥自算 SHA-256，
        // 转成 OpenSSH 风格 SHA256 指纹（便于与 `ssh-keygen -lf` 输出核对）。
        val hk: HostKey? = session.hostKey
        val fingerprint = if (hk != null) sha256Fingerprint(hk.getKey()) else "unknown"
        return ConnectResult(session, fingerprint)
    }

    /** 由 base64 公钥字符串算 OpenSSH `SHA256:<base64>` 指纹。失败时回退 "unknown"。 */
    private fun sha256Fingerprint(base64Key: String): String {
        return try {
            val bytes = android.util.Base64.decode(base64Key, android.util.Base64.DEFAULT)
            val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
            "SHA256:${android.util.Base64.encodeToString(digest, android.util.Base64.NO_WRAP)}"
        } catch (_: Exception) {
            "unknown"
        }
    }

    /**
     * 一次性执行命令，返回 stdout + stderr + exit code。
     *
     * 🔴 2026-11-15 修静默 bug：旧版 `channel.setErrStream(channel.outputStream)`
     * 把 stderr 定向到**远端进程的 stdin**（JSch 的 outputStream = 写给远端 stdin），
     * 注释却写「合并到 stdout 读取流」。这既丢了 stderr，又会污染 stdin —— 正好会
     * 挡住 `sudo -S` 的密码通道。现改为独立 ByteArrayOutputStream 收集 stderr，
     * 末尾与 stdout 合并返回。
     *
     * @param stdin 可选：连接后写入远端 stdin 后立即 flush。用于 `sudo -S` 传密码；
     *              凭据只在调用方进程内存里存在一次，**不写日志、不落盘、不回显**。
     *              密码本身不出现在 command 字符串里，故 `$ command` 输出不含凭据。
     */
    @Throws(Exception::class)
    fun exec(
        session: Session,
        command: String,
        timeoutMs: Long = 15_000,
        stdin: String? = null,
    ): String {
        val channel = session.openChannel("exec") as ChannelExec
        channel.setCommand(command)
        val errBuf = java.io.ByteArrayOutputStream()
        channel.setErrStream(errBuf)
        channel.connect(8_000)
        if (!stdin.isNullOrEmpty()) {
            val os: OutputStream = channel.outputStream
            os.write(stdin.toByteArray(Charsets.UTF_8))
            if (!stdin.endsWith("\n")) os.write('\n'.code)
            os.flush()
        }
        val out = StringBuilder()
        val buf = ByteArray(4_096)
        val input: InputStream = channel.inputStream
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!channel.isClosed) {
            while (input.available() > 0) {
                val n = input.read(buf)
                if (n < 0) break
                out.append(String(buf, 0, n, Charsets.UTF_8))
            }
            if (System.currentTimeMillis() > deadline) break
            Thread.sleep(30)
        }
        // 收尾剩余输出
        while (input.available() > 0) {
            val n = input.read(buf)
            if (n < 0) break
            out.append(String(buf, 0, n, Charsets.UTF_8))
        }
        val exit = channel.exitStatus
        channel.disconnect()
        val err = errBuf.toString(Charsets.UTF_8.name())
        return buildString {
            append(out)
            if (err.isNotBlank()) {
                if (isNotEmpty()) append('\n')
                append("[stderr] ").append(err.trimEnd())
            }
            if (exit >= 0) append("\n[exit=$exit]")
        }.trimEnd()
    }

    /**
     * 打开交互式 PTY shell，返回 (输入流, 输出流)。调用方负责泵数据 + 关闭 channel/session。
     */
    @Throws(Exception::class)
    fun shell(session: Session, termType: String = "xterm-256color", cols: Int = 80, rows: Int = 40):
        ShellHandle {
        val channel = session.openChannel("shell") as ChannelShell
        channel.setPty(true)
        channel.setPtyType(termType)
        // 设置窗口尺寸（部分程序依赖列宽做换行 / 进度条）。
        channel.setPtySize(cols, rows, 0, 0)
        channel.connect(8_000)
        return ShellHandle(
            input = channel.inputStream,
            output = channel.outputStream,
            channel = channel,
        )
    }

    data class ShellHandle(
        val input: InputStream,
        val output: OutputStream,
        private val channel: ChannelShell,
    ) {
        fun resize(cols: Int, rows: Int) {
            try { channel.setPtySize(cols, rows, 0, 0) } catch (_: Exception) {}
        }
        fun close() {
            try { channel.disconnect() } catch (_: Exception) {}
        }
    }
}
