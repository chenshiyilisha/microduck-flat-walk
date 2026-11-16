package io.microduck.app.ssh

import com.jcraft.jsch.Session
import io.microduck.app.core.Disposable

/**
 * SSH 会话数据层 Repository —— 主板 SSH 连接的**唯一持有者与状态出口**（重构阶段 1）。
 *
 * ── 为什么有它（重构规划单一权威）──
 * 见 `docs/active/microduck-安卓App-整体重构与架构重新规划-2026-11-16.md` §4 阶段 1。
 * 现状 `SshPanel` 在 View 层自管 `SshClient` / `Session` / 状态文案，属「UI 自管数据」。
 * 本 Repository 把「SSH 会话 + 由会话派生的不可变快照」收进数据层，成为单一真源（SSOT）：
 * 面板只观察快照、发动作，不再各自维护一份连接状态。
 *
 * ── 位置：app 模块（非 core）──
 * 规划原文把 `SshRepository` 画在 core，但 SSH 依赖 JSch（`com.jcraft.jsch`）与
 * `SshCredentialStore`（Android EncryptedSharedPreferences），无法进纯 Kotlin/JVM、
 * 零 Android 依赖的 core。故按实际依赖落在 **app 模块**数据层，机制与 core
 * [io.microduck.app.core.RobotRepository] 完全一致（不可变快照 + 监听器 + 同步动作入口）。
 * **意图与规划一致，位置按依赖适配**，特此说明。
 *
 * ── 快照不可变 ──
 * [Snapshot] 是 `data class`，每次状态变化**整体替换**一个新实例，监听者拿到的是冻结的
 * 快照，杜绝「读到中途被改」的竞态。
 *
 * ── 线程模型 ──
 * 与 core `RobotRepository` 同构：网络/握手在后台线程，快照发布经 [publish] 在锁内替换、
 * 锁外回调，监听器回调可自行切线程。动作（connect/disconnect/exec）是同步入口、内部托管线程。
 *
 * ── 凭据安全（项目铁律）──
 * 凭据**不落进 Repository**：[connect] 的 [SshCredentialStore.Creds] 只在建链时用一次，
 * 不存字段、不写日志、不落盘；[exec] 的 `stdin`（如 sudo 密码）同样只用一次即随栈回收。
 * 明文仅在进程内存短暂存在（与 `SshClient` / `SshPanel` 现有约定一致）。
 *
 * ── 双轨 ──
 * 阶段 1 只**新增**本 Repository，`SshPanel` 暂不切换（旧路径继续工作），门禁保持绿后
 * 再在阶段 3 把面板接到本 Repository。
 */
class SshRepository(
    private val client: SshClient = SshClient(),
) {

    /** 连接状态机。只由本 Repository 的动作推进，UI 只读。 */
    enum class State { IDLE, CONNECTING, CONNECTED, FAILED }

    /**
     * 不可变 SSH 会话快照 —— 数据层对外的**唯一状态出口**。
     *
     * 所有可选量 nullable / 空串，缺数据 ≠ 零（项目铁律）。
     */
    data class Snapshot(
        /** 连接状态机当前态。 */
        val state: State,
        /** 端点摘要 `user@host:port`；未连接为「—」。**不含密码**。 */
        val endpoint: String,
        /** 主机公钥指纹（SHA256，OpenSSH 格式）；未连接为「未连接」。 */
        val fingerprint: String,
        /** 最近一次错误（连接/校验/执行）；空串 = 无错误。 */
        val error: String,
        /** 最近一次执行的命令；空串 = 未执行。 */
        val lastCommand: String,
        /** 最近一次命令的输出（已截断至 [MAX_OUTPUT_CHARS]）；空串 = 无输出。 */
        val lastOutput: String,
        /** 是否有命令在执行中（防重入 / 按钮态）。 */
        val busy: Boolean,
    )

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
        state = state,
        endpoint = endpoint,
        fingerprint = fingerprint,
        error = error,
        lastCommand = lastCommand,
        lastOutput = lastOutput,
        busy = busy,
    )

    /** 重建快照、存储、锁外回调监听者。 */
    private fun publish() {
        val s = build()
        current = s
        val cbs = synchronized(lock) { listeners.toList() }
        cbs.forEach { it(s) }
    }

    private fun initialSnapshot() = Snapshot(
        state = State.IDLE, endpoint = "—", fingerprint = "未连接",
        error = "", lastCommand = "", lastOutput = "", busy = false,
    )

    // ── 内部状态（唯一真源）──
    private var session: Session? = null
    @Volatile private var state = State.IDLE
    @Volatile private var endpoint = "—"
    @Volatile private var fingerprint = "未连接"
    @Volatile private var error = ""
    @Volatile private var lastCommand = ""
    @Volatile private var lastOutput = ""
    @Volatile private var busy = false

    /** 输出累积上限：只保留尾部，避免长会话把快照撑爆（终端命令是一次性刷，不流式）。 */
    private companion object {
        const val MAX_OUTPUT_CHARS = 32_000
    }

    /**
     * 建立 SSH 会话。校验非空后在后台线程建链，成功/失败都发布快照。
     *
     * @param creds 只用于本次建链，**不留存**（凭据安全铁律）。
     * @return 校验通过并已发起建链返回 true；校验失败 / 已在连接中返回 false。
     */
    fun connect(creds: SshCredentialStore.Creds): Boolean {
        if (creds.host.isEmpty() || creds.user.isEmpty() || creds.password.isEmpty()) {
            error = "主机 / 用户名 / 密码不能为空"
            state = State.FAILED
            publish()
            return false
        }
        if (state == State.CONNECTING || state == State.CONNECTED) {
            error = "已建立会话，请先断开"
            publish()
            return false
        }
        state = State.CONNECTING
        endpoint = "${creds.user}@${creds.host}:${creds.port}"
        error = ""
        publish()
        Thread {
            try {
                val result = client.connect(creds)
                session = result.session
                fingerprint = result.hostKeyFingerprint
                state = State.CONNECTED
                error = ""
            } catch (e: Exception) {
                session = null
                state = State.FAILED
                error = e.message?.take(80) ?: "未知错误"
            }
            publish()
        }.start()
        return true
    }

    /** 主动断开并释放会话，状态回到 IDLE。 */
    fun disconnect() {
        val s = session
        session = null
        Thread { try { s?.disconnect() } catch (_: Exception) {} }.start()
        state = State.IDLE
        endpoint = "—"
        fingerprint = "未连接"
        error = ""
        publish()
    }

    /**
     * 在已连接会话上执行一次性命令，输出累积进快照。
     *
     * @param stdin 用于 `sudo -S` 之类从 stdin 读密码的场景，**只用一次、不留存、不回显**。
     *              未连接或忙时发布错误快照，不执行。
     */
    fun exec(command: String, stdin: String? = null) {
        val s = session
        if (s == null || !s.isConnected) {
            error = "请先连接"
            state = State.FAILED
            publish()
            return
        }
        if (busy) {
            error = "上一条命令仍在执行"
            publish()
            return
        }
        lastCommand = command
        busy = true
        error = ""
        publish()
        Thread {
            try {
                val out = client.exec(s, command, stdin = stdin)
                appendOutput(out)
            } catch (e: Exception) {
                appendOutput("[error] ${e.message?.take(120) ?: "执行失败"}")
            }
            busy = false
            publish()
        }.start()
    }

    /** 累积输出，只保留尾部 [MAX_OUTPUT_CHARS] 字符。 */
    private fun appendOutput(s: String) {
        lastOutput = if (s.length > MAX_OUTPUT_CHARS) {
            s.substring(s.length - MAX_OUTPUT_CHARS)
        } else {
            s
        }
    }

    /** 页面销毁时释放连接（与 `SshPanel.release` 同语义）。 */
    fun release() = disconnect()
}
