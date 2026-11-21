package io.microduck.app.ui

import android.content.Context
import android.text.InputType
import android.view.Gravity
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import io.microduck.app.R

/**
 * 全 App 唯一的对话框入口。
 *
 * 一手依据：Material 3 Dialogs 规范（m3.material.io/components/dialogs/specs）：
 * 容器 28dp 圆角、surfaceContainerHigh、24dp 内边距；图标 24dp；标题/正文/
 * 按钮用 M3 语义色；Dialog 只用于阻断型确认，不是常规信息展示。
 * Android Views 对应实现是 [MaterialAlertDialogBuilder]，而不是平台
 * `android.app.AlertDialog.Builder`（后者在深色主题里仍是旧式默认弹窗）。
 *
 * 项目约束：写操作必须二次确认，确认框统一从这里出，避免八个面板各写一套
 * 主题/按钮顺序。回调只持有必要参数，不持有 Activity 之外的长生命周期对象。
 */
object AppDialogs {

    enum class Tone { INFO, WARN, DANGER }

    /**
     * 显示一张 M3 确认框。返回 [AlertDialog] 只为个别调用点需要在 show 后补充行为；
     * 正常情况下不需要持有返回值。
     *
     * @param onDismiss 取消、点外部或关闭时触发一次；配对密钥清理用这个兜底。
     */
    fun confirm(
        context: Context,
        title: String,
        message: String,
        positiveLabel: String,
        negativeLabel: String? = "取消",
        tone: Tone = Tone.INFO,
        onPositive: (() -> Unit)? = null,
        onNegative: (() -> Unit)? = null,
        onDismiss: (() -> Unit)? = null,
    ): AlertDialog {
        val dp = context.resources.displayMetrics.density
        fun px(v: Int) = (v * dp).toInt()
        val toneColor = context.getColor(when (tone) {
            Tone.DANGER -> R.color.md_bad
            Tone.WARN -> R.color.md_warn
            Tone.INFO -> R.color.md_accent
        })
        val iconRes = when (tone) {
            Tone.DANGER, Tone.WARN -> R.drawable.ic_dialog_warning_24
            Tone.INFO -> R.drawable.ic_dialog_info_24
        }

        // MaterialAlertDialogBuilder 已经提供 M3 容器/按钮；这里只加 M3 规范里的
        // 24dp 状态图标 + body，让弹窗有明确语义色，而不是系统默认文字框。
        val body = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(px(24), px(16), px(24), px(8))
            addView(ImageView(context).apply {
                setImageResource(iconRes)
                imageTintList = android.content.res.ColorStateList.valueOf(toneColor)
                contentDescription = null
                layoutParams = LinearLayout.LayoutParams(px(24), px(24)).also {
                    it.marginEnd = px(16)
                }
            })
            addView(TextView(context).apply {
                text = message
                textSize = 14f
                setTextColor(context.getColor(R.color.md_text_dim))
                setLineSpacing(0f, 1.35f)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
        }

        var dismissFired = false
        val fireDismiss = {
            if (!dismissFired) {
                dismissFired = true
                onDismiss?.invoke()
            }
        }

        val builder = MaterialAlertDialogBuilder(context)
            .setTitle(title)
            .setView(body)
            .setPositiveButton(positiveLabel) { _, _ -> onPositive?.invoke() }
        if (negativeLabel != null) {
            builder.setNegativeButton(negativeLabel) { _, _ -> onNegative?.invoke() }
        }
        return builder.show().also { dialog ->
            dialog.setOnDismissListener { fireDismiss() }
        }
    }

    /**
     * M3 输入框弹窗：仅用于「扫码不可用时手动粘贴配对码」这类一次性短输入。
     * 输入内容只在回调期间存在于本EditText，不写日志、不持久化。
     */
    fun input(
        context: Context,
        title: String,
        message: String,
        hint: String,
        positiveLabel: String,
        onInput: (String) -> Unit,
    ): AlertDialog {
        val dp = context.resources.displayMetrics.density
        fun px(v: Int) = (v * dp).toInt()
        val edit = TextInputEditText(context).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            setSingleLine(true)
            textSize = 14f
        }
        val field = TextInputLayout(context).apply {
            this.hint = hint
            isCounterEnabled = false
            addView(edit, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        }
        val body = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(24), px(16), px(24), px(4))
            addView(TextView(context).apply {
                text = message
                textSize = 14f
                setTextColor(context.getColor(R.color.md_text_dim))
                setLineSpacing(0f, 1.3f)
            })
            addView(field, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).also {
                it.topMargin = px(12)
            })
        }
        return MaterialAlertDialogBuilder(context)
            .setTitle(title)
            .setView(body)
            .setNegativeButton("取消", null)
            .setPositiveButton(positiveLabel) { _, _ -> onInput(edit.text?.toString().orEmpty()) }
            .show()
    }

    private const val MATCH_PARENT = android.view.ViewGroup.LayoutParams.MATCH_PARENT
    private const val WRAP_CONTENT = android.view.ViewGroup.LayoutParams.WRAP_CONTENT
}
