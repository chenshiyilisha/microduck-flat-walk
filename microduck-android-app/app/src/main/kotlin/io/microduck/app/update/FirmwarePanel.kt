package io.microduck.app.update

import android.app.AlertDialog
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import io.microduck.app.R
import io.microduck.app.core.FirmwareSnapshot
import io.microduck.app.core.FirmwareUpdate

/**
 * 设置页「固件更新」面板（纯代码构建，与 UpdatePanel 同风格；11-20 落地）。
 *
 * 一手依据：
 *  · updater-design.md：手机只做 trigger + progress + 查询，固件包由**板子自身 WiFi/HTTPS**
 *    拉取并 minisign 验签；BLE 只透传 JSON-RPC，不传大包。故本面板不提供「选包/上传」。
 *  · update-over-ble.md：apply reply 后约 5s btd 重启断连属成功路径 ⇒ 文案明确提示
 *    「重连后刷新确认」，绝不谎报「已安装成功」；rollout 结果只能由 status.last_attempt 证实。
 *  · OTA UX 最佳实践（WithIntent / Android in-app updates）：设置专区提供手动检查入口 +
 *    BottomSheet/Dialog 详情 + 二次确认 + 进度反馈；不做后台轮询、不打断用户当前操作。
 *
 * ── 真机边界 ──
 * 面板展示的是固件 RPC 的真实回执或 Mock 夹具；即便显示「已提交」也不等于整机升级落地，
 * 不翻 live_hardware_accessed / ship_verdict。写操作全部二次确认，绝不自动执行。
 */
class FirmwarePanel(
    private val activity: AppCompatActivity,
    private val onRefresh: () -> Unit,
    private val onCheck: () -> Unit,
    private val onApply: (version: String?, dryRun: Boolean) -> Unit,
    private val onRollback: () -> Unit,
) {
    val view: LinearLayout
    private val statusText: TextView
    private val versionText: TextView
    private val progressBar: ProgressBar
    private val progressText: TextView
    private val checkButton: MaterialButton
    private val refreshButton: MaterialButton
    private val applyButton: MaterialButton
    private val rollbackButton: MaterialButton
    private var state = FirmwareSnapshot()

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()
    private fun color(res: Int) = ContextCompat.getColor(activity, res)

    init {
        view = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(2), dp(6), dp(2), dp(4))
        }
        view.addView(TextView(activity).apply {
            text = "固件更新"
            textSize = 12f; setTextColor(color(R.color.md_text))
            setTypeface(null, android.graphics.Typeface.BOLD)
            letterSpacing = 0.05f
        })
        view.addView(TextView(activity).apply {
            text = "板子自身 WiFi 拉取并验签 · BLE 仅触发/看进度"
            textSize = 10f; setTextColor(color(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
        })
        versionText = TextView(activity).apply {
            text = "当前固件 · 未读到"; textSize = 11f
            setTextColor(color(R.color.md_accent)); fontFeatureSettings = "tnum"
            setPadding(0, dp(6), 0, dp(2))
        }
        view.addView(versionText)
        statusText = TextView(activity).apply {
            text = "尚未检查 · 点「检查更新」"; textSize = 11f
            setTextColor(color(R.color.md_text)); fontFeatureSettings = "tnum"
            setLineSpacing(0f, 1.2f); minLines = 2
        }
        view.addView(statusText)

        progressBar = ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100; isIndeterminate = false
        }
        progressText = TextView(activity).apply {
            textSize = 10f; setTextColor(color(R.color.md_text_dim)); visibility = View.GONE
            fontFeatureSettings = "tnum"
        }
        view.addView(progressBar, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(4) })
        view.addView(progressText)

        val row1 = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        checkButton = actionButton("检查更新") { onCheck() }
        refreshButton = actionButton("刷新状态") { onRefresh() }
        row1.addView(checkButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row1.addView(refreshButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row1, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(8) })

        val row2 = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        applyButton = actionButton("立即更新") { confirmApply() }
        rollbackButton = actionButton("回滚") { confirmRollback() }
        row2.addView(applyButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row2.addView(rollbackButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row2, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(4) })

        render(FirmwareSnapshot())
    }

    private fun actionButton(label: String, onClick: () -> Unit) = MaterialButton(activity, null,
        com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
        text = label; textSize = 11f; minimumHeight = dp(44)
        contentDescription = label; gravity = Gravity.CENTER
        cornerRadius = activity.resources.getDimensionPixelSize(R.dimen.m3_corner_large)
        strokeWidth = activity.resources.getDimensionPixelSize(R.dimen.m3_stroke_hairline)
        strokeColor = android.content.res.ColorStateList.valueOf(color(R.color.md_outline))
        setTextColor(color(R.color.md_text))
        setOnClickListener { onClick() }
    }

    /** 写操作二次确认（一手：apply/rollback 是 mutating，绝不自动执行）。 */
    private fun confirmApply() {
        val available = state.check as? FirmwareUpdate.CheckState.Available
        val version = available?.candidate
        val title = if (version != null) "安装固件 $version？" else "安装最新固件？"
        val msg = buildString {
            append("板子将通过自身 WiFi 下载并验签固件，随后重启（BLE 会短暂断连，属正常）。\n\n")
            append("更新期间请勿断电。安装结果需在重连后点「刷新状态」确认；健康检查失败会自动回滚。")
            if (available?.mandatory == true) append("\n\n⚠ 这是一个强制更新（mandatory）。")
        }
        AlertDialog.Builder(activity).setTitle(title).setMessage(msg)
            .setNegativeButton("取消", null)
            .setPositiveButton("确认更新") { _, _ -> onApply(version, false) }
            .show()
    }

    private fun confirmRollback() {
        AlertDialog.Builder(activity).setTitle("回滚到上一版本？")
            .setMessage("只重指向已安装的上一个 release，不下载。回滚后需确认机器人健康状态。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认回滚") { _, _ -> onRollback() }
            .show()
    }

    /** 由 MainActivity 的 uiState 收集循环调用（主线程）。 */
    fun render(s: FirmwareSnapshot) {
        state = s
        versionText.text = "当前固件 · ${s.installedVersion() ?: "未读到"}"

        statusText.text = buildString {
            s.check?.let { c ->
                append("检查：").append(when (c) {
                    is FirmwareUpdate.CheckState.UpToDate -> "已是最新（${c.installed ?: "未知版本"}）"
                    is FirmwareUpdate.CheckState.Available ->
                        "发现新版本 ${c.candidate ?: "?"}" + if (c.mandatory) " · 强制" else ""
                    is FirmwareUpdate.CheckState.Incompatible -> "不兼容：${c.reason ?: "未知原因"}"
                    is FirmwareUpdate.CheckState.Unknown -> "检查结果未知${c.raw?.let { "($it)" } ?: ""}"
                }).append("\n")
            }
            s.progress?.let { append("进度：").append(FirmwareUpdate.progressLabel(it)).append("\n") }
            s.resultText?.let { append(it).append("\n") }
            s.errorText?.let { append("⚠ $it") }
        }.trim().ifEmpty {
            if (s.isEmpty) "尚未检查 · 点「检查更新」" else ""
        }
        statusText.setTextColor(when (s.resultOk) {
            true -> color(R.color.md_ok)
            false -> color(R.color.md_bad)
            null -> color(R.color.md_text)
        })

        val p = s.progress
        val pct = p?.percent
        if (s.busy || (p != null && pct == null)) {
            progressBar.isIndeterminate = true
            progressBar.visibility = View.VISIBLE
        } else if (pct != null) {
            progressBar.isIndeterminate = false
            progressBar.progress = pct
            progressBar.visibility = View.VISIBLE
        } else {
            progressBar.visibility = View.GONE
        }
        progressText.visibility = if (p != null || s.busy) View.VISIBLE else View.GONE
        progressText.text = p?.let { FirmwareUpdate.progressLabel(it) } ?: if (s.busy) "操作中…" else ""

        checkButton.isEnabled = !s.checking && !s.busy
        refreshButton.isEnabled = !s.busy
        // 只在「确实有可用更新」时允许点更新；busy 时禁用防重复提交。
        applyButton.isEnabled = s.check is FirmwareUpdate.CheckState.Available && !s.busy
        // 有已装组件时才允许回滚（至少 1 个组件在）。
        rollbackButton.isEnabled = s.components.isNotEmpty() && !s.busy
    }
}
