package io.microduck.app.update

import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton
import io.microduck.app.R
import io.microduck.app.core.Disposable

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
 *
 * ── 阶段 3：纯展示 + 回调 ──
 * 流程状态（busy / canDownload / needsInstallPermission / 文案）的单一真源是
 * [UpdateRepository]，本面板**不再自管** lastState / releaseUrl，改为订阅仓库快照
 * 渲染；按钮只发事件给仓库。这消除了旧 `UpdateController` 与 `UpdateRepository`
 * 两套并行真源。布局代码（本文件 98% 篇幅）保持不动，真机视觉零回归。
 */
class UpdatePanel(
    private val activity: AppCompatActivity,
    private val repository: UpdateRepository,
) {
    val view: LinearLayout
    private val statusText: TextView
    private val checkButton: MaterialButton
    private val downloadButton: MaterialButton
    private val permissionButton: MaterialButton
    private val releaseButton: MaterialButton
    private var snapshot: UpdateRepository.Snapshot = repository.snapshot()
    private var snapshotDisposable: Disposable? = null

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()
    private fun color(res: Int) = ContextCompat.getColor(activity, res)

    init {
        // 2026-11-19 去乱：撤自带圆角卡底（外层已用细分隔线分区），标题由
        // 「版本与更新 · GitHub Releases」收为「版本与更新」——外层原「软件更新·GitHub Releases」
        // 套娃标题已删，来源收进下方说明行，不再三层同义标题。
        view = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(2), dp(4), dp(2), dp(4))
        }
        view.addView(TextView(activity).apply {
            text = "版本与更新"
            textSize = 12f; setTextColor(color(R.color.md_text))
            setTypeface(null, android.graphics.Typeface.BOLD)
            letterSpacing = 0.05f
        })
        view.addView(TextView(activity).apply {
            text = "GitHub Releases · 手动检查，不做后台轮询"
            textSize = 10f; setTextColor(color(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
        })
        view.addView(TextView(activity).apply {
            text = "当前版本 " + repository.versionLabel
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
        checkButton = actionButton("检查更新") { repository.check() }
        releaseButton = actionButton("打开发布页") {
            snapshot.releaseUrl?.let { repository.openReleasePage(it) }
        }
        row1.addView(checkButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row1.addView(releaseButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row1, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(8) })

        val row2 = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        downloadButton = actionButton("下载并安装") { repository.downloadAndInstall() }
        permissionButton = actionButton("开启安装权限") { repository.openInstallPermissionSettings() }
        row2.addView(downloadButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row2.addView(permissionButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        view.addView(row2, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(4) })

        render(snapshot)
        // 订阅仓库快照：Repository 的 publish 在后台线程回调，render 必须切主线程
        // （Android 禁止非主线程改 View；旧 UpdateController 用 runOnUiThread 包回调）。
        snapshotDisposable = repository.onSnapshot { s ->
            activity.runOnUiThread { render(s) }
        }
    }

    /** 次级按钮统一描边（2026-11-19 去乱）：原来默认填充态在设置页里是唯一亮蓝块，
     *  与 BLE/BLE-Wi-Fi/恢复默认等描边按钮不同层级。本项目每屏只保留一个主填充按钮。 */
    private fun actionButton(label: String, onClick: () -> Unit) = MaterialButton(activity, null,
        com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
        text = label; textSize = 11f; minimumHeight = dp(44)
        contentDescription = label
        gravity = Gravity.CENTER
        cornerRadius = activity.resources.getDimensionPixelSize(R.dimen.m3_corner_large)
        strokeWidth = activity.resources.getDimensionPixelSize(R.dimen.m3_stroke_hairline)
        strokeColor = android.content.res.ColorStateList.valueOf(color(R.color.md_outline))
        setTextColor(color(R.color.md_text))
        setOnClickListener { onClick() }
    }

    fun render(state: UpdateRepository.Snapshot) {
        snapshot = state
        statusText.text = state.text
        checkButton.isEnabled = !state.busy
        downloadButton.visibility = if (state.canDownload) View.VISIBLE else View.GONE
        permissionButton.visibility = if (state.needsInstallPermission) View.VISIBLE else View.GONE
        releaseButton.visibility = if (state.releaseUrl != null) View.VISIBLE else View.GONE
    }

    /** 用户从「安装未知应用」设置页返回后重新查权限，不把「返回」当作「已授权」。 */
    fun onResume() {
        // 权限状态迁移已搬进 Repository（单一真源），面板只发事件；
        // 状态变化会通过 onSnapshot 推回 render。
        repository.onInstallPermissionGranted()
    }

    /** 页面销毁时退订，避免 Repository 持有已销毁面板的回调。 */
    fun release() {
        snapshotDisposable?.dispose()
        snapshotDisposable = null
    }
}
