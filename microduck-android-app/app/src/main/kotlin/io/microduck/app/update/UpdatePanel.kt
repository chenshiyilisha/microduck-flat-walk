package io.microduck.app.update

import android.graphics.drawable.GradientDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import io.microduck.app.R

/**
 * 设置页末尾的「版本与更新」面板（纯代码构建，与既有 UI 同风格）。
 *
 * 逐元素依据（一手）：
 *  · 细描边 + 20dp 圆角卡片：项目《现代化科技感视觉设计依据》统一 token
 *    （MDC 1.12.0 colorOutline / 本地 AAR 圆角量级 + HUD「Borders Over Fills」）。
 *  · 「检查更新」手动按钮：GitHub Docs「Avoid polling」「Do not ignore errors」——
 *    未认证 60 次/小时，反复 404 的资源不要每次轮询 ⇒ 不做自动后台检查。
 *  · 「开启安装权限」：Google Android《Publish your app / Install unknown apps》
 *    API 26+ 按来源授权，须调 canRequestPackageInstalls() 并引导到系统设置。
 *  · 「下载并安装」：用户选择的侧载路径 + Android《为应用签名》签名一致性要求
 *    （App 在装前比对证书，见 UpdateInstaller）。
 *  · 「打开发布页」：ImranR98/Obtainium `github.dart` 用 release 的 html_url 让用户
 *    看到原始发布资产；不把「无 APK」伪装成「检查失败」。
 *  · 状态行用 tnum 等宽数字（AndroidX FontSetting.tabularNum() 一手源码），
 *    下载百分比跳动不推歪整行；所有状态文本来自真实 HTTP 结果，不伪造。
 *  · 面板放在设置页**最末尾**：真机 uiautomator 只 dump 视口内节点，
 *    往上插会把「方向摇杆死区」推出首屏（门禁 59 条实测踩过）。
 */
class UpdatePanel(
    private val activity: AppCompatActivity,
    private val controller: UpdateController,
) {
    val view: LinearLayout
    private lateinit var statusText: TextView
    private lateinit var checkButton: MaterialButton
    private lateinit var downloadButton: MaterialButton
    private lateinit var permissionButton: MaterialButton
    private lateinit var releaseButton: MaterialButton
    private var lastState = controller.idleState()
    private var releaseUrl: String? = null

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()
    private fun color(res: Int) = ContextCompat.getColor(activity, res)

    init {
        view = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply {
                setColor(color(R.color.md_card))
                cornerRadius = activity.resources.getDimension(R.dimen.m3_corner_large)
                setStroke(
                    activity.resources.getDimensionPixelSize(R.dimen.m3_stroke_hairline),
                    color(R.color.md_outline_variant),
                )
            }
            val p = dp(12)
            setPadding(p, dp(10), p, dp(10))
        }
        view.addView(TextView(activity).apply {
            text = "版本与更新 · GitHub Releases"
            textSize = 13f; setTextColor(color(R.color.md_text))
            setTypeface(null, android.graphics.Typeface.BOLD)
            letterSpacing = 0.05f
        })
        view.addView(TextView(activity).apply {
            text = "手动检查 · 不做后台轮询（GitHub REST API 未认证 60 次/小时）"
            textSize = 10f; setTextColor(color(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
        })
        view.addView(TextView(activity).apply {
            text = "当前版本 " + controller.versionLabel()
            textSize = 11f; setTextColor(color(R.color.md_accent))
            fontFeatureSettings = "tnum"
            setPadding(0, dp(6), 0, dp(2))
        })
        statusText = TextView(activity).apply {
            textSize = 11f; setTextColor(color(R.color.md_text))
            fontFeatureSettings = "tnum"
            setLineSpacing(0f, 1.2f)
            minLines = 2
        }
        view.addView(statusText)

        val row1 = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        checkButton = actionButton("检查更新") { controller.check { render(it) } }
        releaseButton = actionButton("打开发布页") {
            releaseUrl?.let { controller.openReleasePage(it) }
        }
        row1.addView(checkButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row1.addView(releaseButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row1, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(8) })

        val row2 = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        downloadButton = actionButton("下载并安装") { controller.downloadAndInstall { render(it) } }
        permissionButton = actionButton("开启安装权限") { controller.openInstallPermissionSettings() }
        row2.addView(downloadButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row2.addView(permissionButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row2, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(4) })

        render(lastState)
    }

    private fun actionButton(label: String, onClick: () -> Unit) = MaterialButton(activity).apply {
        text = label; textSize = 11f; minimumHeight = dp(44)
        contentDescription = label
        gravity = Gravity.CENTER
        setOnClickListener { onClick() }
    }

    fun render(state: UpdateController.State) {
        lastState = state
        releaseUrl = state.releaseUrl
        statusText.text = state.text
        checkButton.isEnabled = !state.busy
        downloadButton.visibility = if (state.canDownload) View.VISIBLE else View.GONE
        permissionButton.visibility = if (state.needsInstallPermission) View.VISIBLE else View.GONE
        releaseButton.visibility = if (state.releaseUrl != null) View.VISIBLE else View.GONE
    }

    /** 用户从「安装未知应用」设置页返回后重新查权限，不把「返回」当作「已授权」。 */
    fun onResume() {
        if (lastState.needsInstallPermission && controller.canRequestInstalls()) {
            render(UpdateController.State(
                text = "安装权限已开启，可继续「下载并安装」",
                canDownload = true,
                releaseUrl = lastState.releaseUrl,
            ))
        }
    }
}
