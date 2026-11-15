package io.microduck.app.ssh

import android.app.AlertDialog
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.text.InputType
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.jcraft.jsch.Session
import io.microduck.app.R
import io.microduck.app.ssh.SshClient

/**
 * SSH 远程控制界面（主板命令行）。
 *
 * ── 为什么是「终端」这个顶层目的地 ──
 * 用户 2026-11-15：「三个界面都有顶部控制台卡片和底部通道卡片，重复了，还缺少
 * SSH 远程控制界面」。M3 navigation bar 允许 3–5 个目的地，故新增第 4 个「终端」，
 * 与状态（运动监测）/ 健康（硬件诊断）/ 设置（配置）分工互不重叠。
 *
 * ── 安全边界（项目铁律）──
 *  · 凭据**默认不落盘**：密码只在进程内存里短暂存在，只有用户显式勾选「记住凭据」
 *    才写进 [SshCredentialStore]（EncryptedSharedPreferences + Android Keystore，
 *    落盘是密文）。任何情况下都不写日志 / 文档 / git。
 *  · 主机密钥：调试场景用 StrictHostKeyChecking=no，但**把实际指纹显示出来**
 *    供肉眼核对，绝不静默信任（[SshClient.ConnectResult.hostKeyFingerprint]）。
 *  · 快捷命令**默认只读**：`robotctl health --json` 有一手实机依据（见
 *    `docs/active/microduck-主板到货-SSH只读实机验收与App适配-2026-11-14.md`）；
 *    `systemctl is-active` / `uptime` / `df -h` 是 Linux 平台通用只读命令。
 *  · 🔴 **唯一写操作「启动 updaterd」必须显式二次确认**，绝不自动执行：
 *    一手依据（验收文档 §4.3 / 优化候选 §8.3）：实机 `updaterd` 为
 *    `inactive`/`disabled`，drop-in `zzzz-r17-manual.conf` 是镜像**故意设为手动**，
 *    `/run/updaterd.sock` 不存在是设计结果，不是故障。
 *    `updaterd.service` 一手源码 `[Install] WantedBy=multi-user.target`（可启动）；
 *    命令取 `sudo -S -p '' systemctl start updaterd`：
 *      - `-S`：sudo 官方手册「Write the prompt to the standard error and read the
 *        password from the standard input instead of using the terminal device」。
 *        [SshClient.exec] 是无 PTY 的一次性 exec，普通 sudo 读不到 tty 会挂住；
 *        本项目为此给 exec 增加 `stdin` 参数，把当前登录密码在内存中送入一次，
 *        不拼进命令行、不回显、不写日志、不落盘。
 *      - `-p ''`：把 sudo 的密码提示串置空，避免提示文本混进输出区。
 *      - `start` 而非 `enable --now`：systemd「enable 管开机自启、start 管当下」两者
 *        正交；start 只在本次运行生效，**不改镜像故意手动的设计**，重启回 disabled
 *        属预期。改为开机自启会动镜像策略，不擅自做。
 *    ⇒ 不编造控制命令，也不把「默认被关」误判成故障。
 *  · 交互式 PTY shell（[SshClient.shell]）与 [TerminalEmulator] 已就绪，但本页先用
 *    一次性 `exec`：每条命令才刷一次 UI，不做持续刷新 —— 避免真机门禁
 *    `uiautomator waitForIdle` 被 1s tick 的 AccessibilityEvent 卡死（项目既有坑）。
 *    ⇒ 交互式终端接入状态：UNVERIFIED，不声称已实现。
 *
 * ── 线程 ──
 * 所有 SSH 网络操作在后台线程执行，UI 更新一律 `post {}` 回主线程（Android 主线程
 * 禁止网络 I/O）。页面销毁时断开 session。
 */
class SshPanel(context: Context) : MaterialCardView(context) {

    private val d = resources.displayMetrics.density
    private fun dp(v: Int) = (v * d).toInt()

    private val hostEdit: EditText
    private val portEdit: EditText
    private val userEdit: EditText
    private val passEdit: EditText
    private val rememberBox: CheckBox
    private val connectBtn: MaterialButton
    private val disconnectBtn: MaterialButton
    private val fingerprintText: TextView
    private val cmdEdit: EditText
    private val outputText: TextView
    private val outputScroll: ScrollView
    private val statusText: TextView

    private val client = SshClient()
    @Volatile private var session: Session? = null
    private var terminal = TerminalEmulator(cols = 80, rows = 40) { }

    /** 快捷只读命令：不编造控制命令，只放一手实机依据或 Linux 平台通用只读命令。 */
    private val quickCommands = listOf(
        "robotctl health --json" to "健康检查",
        "uptime" to "负载",
        "df -h" to "磁盘",
        "systemctl is-active updaterd; systemctl is-enabled updaterd" to "更新服务状态",
    )

    /**
     * 🔴 唯一写操作：启动默认被关的 `updaterd`。
     * 命令含 `sudo -S`（从 stdin 读密码）而非纯 `sudo`：[SshClient.exec] 无 PTY，
     * 普通 sudo 会挂住；密码由当前登录凭据经 stdin 送入一次，不出现在命令行、
     * 不回显、不写日志、不落盘。`-p ''` 去掉密码提示串，避免混进输出。
     * `start` 而非 `enable --now`：只本次生效，不改镜像故意手动的设计。
     */
    private val START_UPDATERD_CMD =
        "sudo -S -p '' systemctl start updaterd"
    private val UPDATERD_NOTE =
        "实机 updaterd 为 inactive/disabled，镜像 drop-in zzzz-r17-manual.conf " +
            "故意设为手动（非故障）。执行 start 仅本次生效，重启回 disabled 属设计预期。\n\n" +
            "需要 radxa 具备 sudo 权限；密码用当前登录凭据经 stdin 送入一次，不保存。\n" +
            "启动后请点「更新服务状态」复核 is-active=active（负对照：启动前为 inactive）。"

    init {
        radius = dp(20).toFloat(); cardElevation = 0f
        strokeWidth = dp(1); setStrokeColor(context.getColor(R.color.md_outline_variant))
        setCardBackgroundColor(context.getColor(R.color.md_card))
        setContentPadding(dp(12), dp(10), dp(12), dp(10))

        val root = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }

        root.addView(TextView(context).apply {
            text = "SSH 远程终端 · 主板命令行"
            textSize = 13f; setTypeface(null, Typeface.BOLD)
            setTextColor(context.getColor(R.color.md_text))
        })
        root.addView(TextView(context).apply {
            text = "凭据默认不保存 · 主机指纹需肉眼核对 · 只读快捷命令"
            textSize = 10.5f; setTextColor(context.getColor(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(2), 0, dp(6))
        })

        // ── 凭据区（2×2）──
        val saved = try { SshCredentialStore.load(context) } catch (_: Exception) {
            SshCredentialStore.Creds("192.168.50.216", 22, "radxa", "")
        }
        val row1 = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        hostEdit = credEdit(saved.host, "主机地址", InputType.TYPE_CLASS_TEXT or
            InputType.TYPE_TEXT_VARIATION_URI)
        portEdit = credEdit(saved.port.toString(), "端口", InputType.TYPE_CLASS_NUMBER)
        row1.addView(hostEdit, LinearLayout.LayoutParams(0, WRAP, 1f))
        row1.addView(portEdit, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(6) })
        root.addView(row1)

        val row2 = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        userEdit = credEdit(saved.user, "用户名", InputType.TYPE_CLASS_TEXT)
        passEdit = credEdit(saved.password, "密码", InputType.TYPE_CLASS_TEXT or
            InputType.TYPE_TEXT_VARIATION_PASSWORD)
        row2.addView(userEdit, LinearLayout.LayoutParams(0, WRAP, 1f))
        row2.addView(passEdit, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(6) })
        root.addView(row2, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(6) })

        rememberBox = CheckBox(context).apply {
            text = "记住凭据（加密存储）"; textSize = 11f
            setTextColor(context.getColor(R.color.md_text_dim))
            isChecked = false   // 默认不落盘
        }
        root.addView(rememberBox)

        val btnRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        connectBtn = MaterialButton(context).apply {
            text = "连接"; textSize = 12f; minimumHeight = dp(44)
            setOnClickListener { connect() }
        }
        disconnectBtn = MaterialButton(context).apply {
            text = "断开"; textSize = 12f; minimumHeight = dp(44)
            isEnabled = false
            setOnClickListener { disconnect() }
        }
        btnRow.addView(connectBtn, LinearLayout.LayoutParams(0, WRAP, 1f))
        btnRow.addView(disconnectBtn, LinearLayout.LayoutParams(0, WRAP, 1f).also {
            it.marginStart = dp(6)
        })
        root.addView(btnRow)

        fingerprintText = TextView(context).apply {
            text = "主机指纹：未连接"
            textSize = 10f; setTextColor(context.getColor(R.color.md_accent))
            setTypeface(Typeface.MONOSPACE)
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(4), 0, dp(2))
        }
        root.addView(fingerprintText)

        statusText = TextView(context).apply {
            text = "● 未连接"
            textSize = 11f; setTextColor(context.getColor(R.color.md_text_dim))
            setPadding(0, 0, 0, dp(4))
        }
        root.addView(statusText)

        // ── 快捷只读命令 ──
        val quickRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        quickCommands.forEachIndexed { idx, (cmd, label) ->
            val b = MaterialButton(context).apply {
                text = label; textSize = 10.5f; minimumHeight = dp(38)
                contentDescription = "快捷命令 $label"
                setOnClickListener { runCommand(cmd) }
            }
            quickRow.addView(b, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                if (idx > 0) it.marginStart = dp(4)
            })
        }
        root.addView(quickRow)

        // ── 写操作：启动 updaterd（默认被关），必须二次确认，绝不自动执行 ──
        // 单独一行 + 警示色，与上面的只读快捷命令区视觉隔离，避免误触。
        val writeBtn = MaterialButton(context).apply {
            text = "启动 updaterd（默认关闭 · 需确认）"
            textSize = 11f; minimumHeight = dp(40)
            contentDescription = "写操作 启动 updaterd"
            setBackgroundColor(context.getColor(R.color.md_warn))
            setTextColor(context.getColor(R.color.md_bg))
            setOnClickListener { confirmStartUpdaterd() }
        }
        root.addView(writeBtn, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(6)
        })
        root.addView(TextView(context).apply {
            text = "镜像故意把 updaterd 设为手动；start 只本次生效，不改开机自启"
            textSize = 9.5f; setTextColor(context.getColor(R.color.md_text_dim))
            setPadding(0, dp(2), 0, 0)
        })

        // ── 命令输入 + 执行 ──
        val cmdRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        cmdEdit = EditText(context).apply {
            hint = "输入命令后点执行"
            textSize = 11f; setSingleLine(true)
            setTextColor(context.getColor(R.color.md_text))
            setHintTextColor(context.getColor(R.color.md_text_dim))
            inputType = InputType.TYPE_CLASS_TEXT
        }
        val execBtn = MaterialButton(context).apply {
            text = "执行"; textSize = 11f; minimumHeight = dp(42)
            contentDescription = "执行命令"
            setOnClickListener {
                val cmd = cmdEdit.text?.toString()?.trim().orEmpty()
                if (cmd.isNotEmpty()) runCommand(cmd)
            }
        }
        cmdRow.addView(cmdEdit, LinearLayout.LayoutParams(0, WRAP, 1f))
        cmdRow.addView(execBtn, LinearLayout.LayoutParams(WRAP, WRAP).also {
            it.marginStart = dp(6)
        })
        root.addView(cmdRow, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(6) })

        // ── 输出区（等宽 + 可滚动）──
        outputText = TextView(context).apply {
            text = ""; textSize = 10.5f
            setTypeface(Typeface.MONOSPACE)
            setTextColor(Color.parseColor("#E6EDF3"))
            setPadding(dp(8), dp(8), dp(8), dp(8))
        }
        outputScroll = ScrollView(context).apply {
            setBackgroundColor(Color.parseColor("#0A1626"))
            addView(outputText, LinearLayout.LayoutParams(MATCH, WRAP))
        }
        root.addView(outputScroll, LinearLayout.LayoutParams(MATCH, 0, 1f).also {
            it.topMargin = dp(6)
        })

        addView(root, LayoutParams(MATCH, MATCH))
    }

    private fun credEdit(value: String, hint: String, inputType: Int) = EditText(context).apply {
        setText(value); this.hint = hint
        textSize = 11f; setSingleLine(true); this.inputType = inputType
        setTextColor(context.getColor(R.color.md_text))
        setHintTextColor(context.getColor(R.color.md_text_dim))
        background = roundedCard(context.getColor(R.color.md_card_alt), 12)
        setPadding(dp(10), dp(8), dp(10), dp(8))
    }

    private fun roundedCard(fill: Int, radiusDp: Int) =
        android.graphics.drawable.GradientDrawable().apply {
            setColor(fill); cornerRadius = dp(radiusDp).toFloat()
            setStroke(dp(1), context.getColor(R.color.md_outline_variant))
        }

    private fun currentCreds() = SshCredentialStore.Creds(
        host = hostEdit.text?.toString()?.trim().orEmpty(),
        port = portEdit.text?.toString()?.trim()?.toIntOrNull() ?: 22,
        user = userEdit.text?.toString()?.trim().orEmpty(),
        password = passEdit.text?.toString().orEmpty(),
    )

    private fun connect() {
        val creds = currentCreds()
        if (creds.host.isEmpty() || creds.user.isEmpty() || creds.password.isEmpty()) {
            setStatus("● 主机 / 用户名 / 密码不能为空", error = true)
            return
        }
        if (rememberBox.isChecked) {
            try { SshCredentialStore.save(context, creds) } catch (_: Exception) { /* 存储失败不阻塞连接 */ }
        }
        connectBtn.isEnabled = false
        setStatus("● 正在连接 ${creds.host}:${creds.port} …")
        Thread {
            try {
                val result = client.connect(creds)
                session = result.session
                post {
                    fingerprintText.text = "主机指纹：${result.hostKeyFingerprint}"
                    disconnectBtn.isEnabled = true
                    setStatus("● 已连接 ${creds.host}")
                    appendOutput("[connected] ${creds.user}@${creds.host}:${creds.port}\n")
                }
            } catch (e: Exception) {
                post {
                    connectBtn.isEnabled = true
                    setStatus("● 连接失败：${e.message?.take(80) ?: "未知错误"}", error = true)
                }
            }
        }.start()
    }

    private fun disconnect() {
        val s = session
        session = null
        Thread { try { s?.disconnect() } catch (_: Exception) {} }.start()
        connectBtn.isEnabled = true
        disconnectBtn.isEnabled = false
        fingerprintText.text = "主机指纹：未连接"
        setStatus("● 已断开")
    }

    /** 写操作二次确认：把命令全文与一手依据摊开给用户看，绝不静默执行。 */
    private fun confirmStartUpdaterd() {
        AlertDialog.Builder(context)
            .setTitle("启动 updaterd（写操作）")
            .setMessage("$UPDATERD_NOTE\n\n将执行：\n$START_UPDATERD_CMD")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认启动") { _, _ ->
                // 🔴 凭据只在进程内存里取一次，直接交给后台线程的 stdin；
                // 不写日志、不落盘、不回显、不拼进命令字符串。
                val sudoPassword = passEdit.text?.toString().orEmpty()
                runCommand(START_UPDATERD_CMD, stdin = sudoPassword)
            }
            .show()
    }

    private fun runCommand(command: String, stdin: String? = null) {
        val s = session
        if (s == null || !s.isConnected) {
            setStatus("● 请先连接", error = true)
            return
        }
        appendOutput("\n$ $command\n")
        Thread {
            try {
                val out = client.exec(s, command, stdin = stdin)
                post { appendOutput(out + "\n") }
            } catch (e: Exception) {
                post { appendOutput("[error] ${e.message?.take(120) ?: "执行失败"}\n") }
            }
            // stdin 引用的局部字符串随栈帧回收；不做任何持久化。
        }.start()
    }

    private fun appendOutput(s: String) {
        // 用 TerminalEmulator 处理 ANSI/VT100（远端 robotctl/journalctl 会带颜色码），
        // 只在命令返回时刷一次 TextView，不做持续刷新（门禁 idle 约束）。
        terminal.write(s)
        outputText.text = terminal.render()
        outputText.setTextColor(Color.parseColor("#E6EDF3"))
        outputScroll.post { outputScroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun setStatus(msg: String, error: Boolean = false) {
        statusText.text = msg
        statusText.setTextColor(context.getColor(if (error) R.color.md_bad else R.color.md_ok))
    }

    /** 页面销毁时断开，避免后台连接泄漏。 */
    fun release() {
        val s = session
        session = null
        Thread { try { s?.disconnect() } catch (_: Exception) {} }.start()
    }

    private companion object {
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT
    }
}
