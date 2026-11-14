package io.microduck.app

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.text.SpannableString
import android.text.Spanned
import android.text.TextUtils
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.widget.CheckBox
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.graphics.Insets
import androidx.core.net.toUri
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.google.android.material.textfield.TextInputLayout
import io.microduck.app.ble.BleConnectPanel
import io.microduck.app.core.StateSnapshot
import io.microduck.app.update.GithubReleaseClient
import io.microduck.app.update.UpdateController
import io.microduck.app.update.UpdatePanel

/**
 * 竖屏控制台首页 —— 用户 2026-11-12「一个界面放不下这么多内容，应该合理的拆分界面，
 * 不同界面显示不同内容」「打开遥控界面应该横屏」「可以选择自动模式、手动模式」。
 *
 * ## 拆页依据（不是拍脑袋）
 *  - M3 Navigation bar 规范（m3.material.io/components/navigation-bar/guidelines）：
 *    「Navigation bars provide access to **three to five destinations**」「Use navigation for
 *    **distinct pages** and tabs for related content within a page」「Don't use a navigation bar
 *    for fewer than three destinations」。⇒ 状态 / 健康 / 设置 三个独立页，
 *    而全屏沉浸的遥控页不放导航栏，改由独立 Activity 承载。
 *  - Weston Robot Teleop 文档（docs.westonrobot.com/.../robot-teleoperation，2026-11-13 一手核验
 *    原文「The driving view has **its own arrangement** — a primary feed filling the screen ...
 *    **kept separately from the dashboard's**」）：驾驶视图与仪表盘分离；速度/死区等参数属于 settings。
 *  - NIST UTAP 3.2.19（NIST 工作草案 ws680.nist.gov，2026-11-13 一手核验原文：telerobotics
 *    methods ... manual control, supervisory control, and fully automatic control；manual =
 *    人的连续输入，supervisory = 人或计算机均可产生运动）：本页「自动模式」按**监督视图**实现 ——
 *    App 零驾驶帧、只监测，详见 SessionHolder 注释。
 *  - 用户 2026-11-12「一个界面放不下这么多内容，应该合理的拆分界面」——拆页的直接产品需求。
 *
 * ## 数据来源不许串源（项目铁律 UNVERIFIED != PASS）
 * 「实机状态帧」只读 `robot.state` 订阅帧；Mock 不推帧 ⇒ 保持「— 未读到」，绝不拿本地计数填。
 * 「App 本地遥测」是 App 自观测（会话/通道/发帧数/帧率/最后输入/心跳），标题明写非实机。
 * Mock 的 health fixture 是演示夹具，健康页标题标注「非实机读数」。
 */
class MainActivity : AppCompatActivity() {

    /** 每个目的地页面的全局状态显示控件（AppBar 状态串 / 来源标签 / 链路横幅）。
     *  三个目的地各持一套，切换页面时整体跟随 —— 符合 M3 navigation bar
     *  「Use navigation for distinct pages」语义：每个目的地是完整页面，
     *  全局状态（连接/模式/链路）在每个页面都可见。 */
    private class PageChrome(
        val statusText: TextView,
        val sourceChip: TextView,
        val linkBanner: TextView,
    )
    private val pageChromes = mutableListOf<PageChrome>()

    private lateinit var hostEdit: EditText
    // 连接行渐进式披露：已连接时折叠输入、显示摘要行（点「修改」展开）
    private lateinit var connectionSummary: LinearLayout
    private lateinit var connectionSummaryText: TextView
    private lateinit var connectionInputRow: LinearLayout
    private var connectionExpanded = false
    private lateinit var modeManual: MaterialButton
    private lateinit var modeAuto: MaterialButton
    private lateinit var modeHint: TextView
    private lateinit var launchButton: MaterialButton
    private lateinit var bottomStatus: TextView
    private lateinit var stateSourceText: TextView
    private lateinit var healthText: TextView
    private lateinit var healthSourceText: TextView
    private lateinit var autoRefreshBox: CheckBox
    // M3 exposed dropdown menu：不再是 android.widget.Spinner（平台老式弹窗）。
    // 持有 MaterialAutoCompleteTextView 以便 restoreSettingsUi() 用 setText(text, false) 回写选中值。
    private lateinit var channelDropdown: MaterialAutoCompleteTextView
    private lateinit var headRadDropdown: MaterialAutoCompleteTextView
    private lateinit var invertBox: CheckBox
    private lateinit var vxBar: SeekBar
    private lateinit var yawBar: SeekBar
    private lateinit var driveDzBar: SeekBar
    private lateinit var headDzBar: SeekBar
    private lateinit var vxLabel: TextView
    private lateinit var yawLabel: TextView
    private lateinit var driveDzLabel: TextView
    private lateinit var headDzLabel: TextView
    private lateinit var topScrim: View
    private lateinit var blePanel: BleConnectPanel
    private lateinit var updateController: UpdateController
    private lateinit var updatePanel: UpdatePanel
    private lateinit var statePage: View
    private lateinit var healthPage: View
    private lateinit var settingsPage: View
    private val stateValues = mutableListOf<TextView>()
    private val telemetryValues = mutableListOf<TextView>()
    private val tabButtons = mutableListOf<MaterialButton>()
    private var currentPage = 0
    private val ui = Handler(Looper.getMainLooper())

    private val d: Float by lazy { resources.displayMetrics.density }
    private fun dp(v: Int): Int = (v * d).toInt()
    private fun c(id: Int): Int = getColor(id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 🔑 先读持久化参数，再建 Settings 页 —— 顺序反了会拿默认值覆盖用户上次的选择。
        // 取自 ROS_Robot_Controller / ohho.apk 的 persistent preferences；mode 与 host 刻意不持久化。
        SettingsStore.load(applicationContext)
        blePanel = BleConnectPanel(this)
        // 更新源默认固定 GitHub REST API（api.github.com）。仅 debuggable 包允许通过显式
        // Intent extra 指向 PC 本地服务，用于真机端到端验证下载/安装链路；不暴露在 UI 上，
        // 生产包（FLAG_DEBUGGABLE=0）完全忽略该 extra。项目已有同型先例：
        // core/src/test 的 LocalRelayServer 用 PC 本地服务做真机 C2 联调。
        val overrideBase = if ((applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            intent.getStringExtra(EXTRA_UPDATE_API_BASE)
        } else {
            null
        }
        val extraHosts = overrideBase?.let { setOfNotNull(it.toUri().host?.lowercase()) }
            ?: emptySet()
        updateController = UpdateController(this, overrideBase ?: GithubReleaseClient.API_BASE, extraHosts)
        updatePanel = UpdatePanel(this, updateController)
        val root = FrameLayout(this).apply { setBackgroundColor(c(R.color.md_bg)) }
        // 视觉节奏按 M1「Metrics & keylines」一手数值：8dp 基线网格、移动端左右 16dp
        // 边距、内容组之间 8dp。旧版 10dp 边距 / 6dp 组距不在网格上，截图显得散。
        val content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        fun section(v: View, topGap: Int = 8) = content.addView(
            v, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(topGap) })
        // M3 navigation bar：「Use navigation for distinct pages」—— 每个目的地是完整页面，
        // 切换时上方整个区域（AppBar + 链路横幅 + 页面内容）整体跟随，只有导航栏与全局
        // 状态条常驻。三个目的地分工明确、边界清晰、无功能重叠：
        //  · 状态 = 运动控制实时监测（连接 + 控制模式 + 实机状态帧/本地遥测）
        //  · 健康 = 机器人健康诊断（robot.health 字段）
        //  · 设置 = 配置（遥控参数 + BLE + 更新）
        val pages = FrameLayout(this)
        statePage = buildPage(0)
        healthPage = buildPage(1)
        settingsPage = buildPage(2)
        pages.addView(statePage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(healthPage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(settingsPage, FrameLayout.LayoutParams(MATCH, MATCH))
        content.addView(pages, LinearLayout.LayoutParams(MATCH, 0, 1f).also {
            it.topMargin = dp(8)
        })
        // 全局遥测状态条：通道/发帧数等会话级信息，属框架层，常驻不随目的地切换。
        content.addView(buildBottomStatus(), LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(8)
        })
        // M3 navigation bar 规范：容器固定在窗口底部、目的地位置不滚动。
        section(buildTabRow())
        root.addView(content, FrameLayout.LayoutParams(MATCH, MATCH))

        topScrim = View(this).apply { setBackgroundColor(Color.argb(190, 0x06, 0x12, 0x22)) }
        root.addView(topScrim, FrameLayout.LayoutParams(MATCH, 0, Gravity.TOP))
        setContentView(root)

        // Android 15+ 强制 edge-to-edge：insets 转 padding + 状态栏 scrim；
        // 返回置零 insets 防后代重复 padding（官方 webview insets 文档同型）。
        ViewCompat.setOnApplyWindowInsetsListener(content) { v, insets ->
            val types = WindowInsetsCompat.Type.systemBars() or
                WindowInsetsCompat.Type.displayCutout()
            val b = insets.getInsets(types)
            val p = dp(16)       // M1 官方：mobile screen edge margins 16dp
            v.setPadding(p + b.left, p + b.top, p + b.right, p + b.bottom)
            topScrim.layoutParams = FrameLayout.LayoutParams(MATCH, b.top, Gravity.TOP)
            WindowInsetsCompat.Builder(insets).setInsets(types, Insets.NONE).build()
        }

        showPage(0)
        refreshModeUi()
        connectFromUi()                    // 默认 Mock：无整机也能看到完整交互
        ui.post(tick)
    }

    /**
     * 构建一个目的地页面 —— AppBar + 链路横幅 + 该页专属内容，整体随导航切换。
     *
     * 依据：M3 navigation bar「Use navigation for **distinct pages**」—— 每个目的地是
     * 完整页面，切换时上方整块（含 AppBar 与链路横幅）整体跟随，只有底部导航栏与全局
     * 状态条常驻。三个目的地分工：
     *  · 状态 = 运动控制实时监测（连接行 + 控制卡片 + 实机状态帧/本地遥测）
     *  · 健康 = 机器人健康诊断（robot.health）
     *  · 设置 = 配置（遥控参数 + BLE + 更新）
     *
     * 全局状态控件（状态串 / 来源标签 / 链路横幅）每个页面各持一套（PageChrome），
     * renderAll() 统一刷新，保证任何目的地下连接/模式/链路信息都可见。
     */
    private fun buildPage(index: Int): View {
        val chrome = PageChrome(
            statusText = TextView(this).apply {
                // 🔴 真机截图实测：状态串一长就折成两行、把 appBar 撑歪。
                // 单行 + 末尾省略；完整信息分流到来源标签和监测卡。
                textSize = 11f; setTextColor(c(R.color.md_text_dim))
                setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
                fontFeatureSettings = TABULAR_FIGURES
            },
            sourceChip = TextView(this).apply {
                text = "● 演示会话"; textSize = 11f; setTextColor(c(R.color.md_warn))
                background = roundedCard(c(R.color.md_card_alt), CORNER_LARGE_DP)
                setPadding(dp(8), dp(4), dp(8), dp(4))
            },
            linkBanner = buildLinkBanner(),
        )
        pageChromes.add(chrome)

        val page = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        page.addView(buildAppBar(chrome), LinearLayout.LayoutParams(MATCH, WRAP))
        page.addView(chrome.linkBanner, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(8)
        })
        when (index) {
            0 -> {
                page.addView(buildConnectionRow(), LinearLayout.LayoutParams(MATCH, WRAP).also {
                    it.topMargin = dp(8)
                })
                page.addView(buildControlCard(), LinearLayout.LayoutParams(MATCH, WRAP).also {
                    it.topMargin = dp(8)
                })
                page.addView(buildStatePage(), LinearLayout.LayoutParams(MATCH, 0, 1f).also {
                    it.topMargin = dp(8)
                })
            }
            1 -> page.addView(buildHealthPage(), LinearLayout.LayoutParams(MATCH, MATCH).also {
                it.topMargin = dp(8)
            })
            2 -> page.addView(buildSettingsPage(), LinearLayout.LayoutParams(MATCH, MATCH).also {
                it.topMargin = dp(8)
            })
        }
        return page
    }

    private fun buildAppBar(chrome: PageChrome) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = roundedCard(c(R.color.md_card), CORNER_LARGE_DP)
        setPadding(dp(12), dp(10), dp(12), dp(10))
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            addView(TextView(this@MainActivity).apply {
                text = "MicroDuck  控制台"
                textSize = 16f; setTextColor(c(R.color.md_text))
                setTypeface(null, Typeface.BOLD)
                // 标题微字距（项目约定 0.08f）：参照 HUD 设计参考里「小标签加字距」的方向。
                // ⚠️ 具体 0.05–0.1em 数值未能从该页逐字核验，故只作项目取值，不声称规范值。
                // 纯视觉，不改文本，门禁零影响。
                letterSpacing = TRACKING_TITLE
            })
            addView(chrome.statusText)
        }, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(12) })
        addView(chrome.sourceChip)
    }

    /**
     * 链路状态横幅（A3）。一手依据：**Pollen 原厂**（唯一官方）`pollen-robotics/microduck@main`
     * 的 `docs/design/mobile-app.md` §4:156-157 原文（fanhao fork 副本同源，见《来源术语约定》）
     * 「Every screen tolerates the link dropping underneath it and coming back — including
     *  during an update, where `btd` restarts five seconds after the reply goes out」。
     * BLE 是**常驻通道**（不是一次性配网向导）：btd 断链即丢弃会话，重连后手机处于未认证态，
     * 故断链/重连是安全信息，必须在每个页面可见。
     * 本横幅默认 GONE，正常态不占视觉空间，异常时整条着色，不靠小字暗示。
     *
     * ⚠️ 2026-11-13 复核纠正：上一轮曾把这条引用判为「无法证实」并降级为通用共识，
     * 实因当时只 Grep 了工作区、漏查本地 `/tmp/fanhao` 一手源码；现逐字命中，恢复一手引用。
     */
    private fun buildLinkBanner() = TextView(this).apply {
        contentDescription = "链路状态横幅"
        textSize = 12f; setTypeface(null, Typeface.BOLD)
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(12), dp(8), dp(12), dp(8))
        minimumHeight = dp(40)
        visibility = View.GONE
    }

    private fun renderLinkBanner() {
        val inputError = SessionHolder.connectError
        val link = SessionHolder.linkStatus
        val msg = if (inputError.isNotEmpty()) "⚠ 地址无效 · $inputError" else link
        // 三个目的地各持一套链路横幅，统一刷新，保证任何页面下断链信息都可见。
        pageChromes.forEach { chrome ->
            if (msg.isEmpty()) {
                chrome.linkBanner.visibility = View.GONE
                return@forEach
            }
            chrome.linkBanner.visibility = View.VISIBLE
            chrome.linkBanner.text = msg
            val level = if (inputError.isNotEmpty()) 2 else SessionHolder.linkLevel
            // 亮底配深字：MaterialButton 那个「只换背景不换字色」的坑不能在这里重演。
            chrome.linkBanner.setBackgroundColor(if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn))
            chrome.linkBanner.setTextColor(c(R.color.md_bg))
            chrome.linkBanner.background = roundedCard(
                if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn), CORNER_LARGE_DP,
                stroked = false)   // 告警是纯状态色块，不再叠低对比描边（Color is purely functional）
        }
    }

    /**
     * 连接行 —— **渐进式披露**：未连接时展开显示 host 输入 + 连接按钮；
     * 已连接时折叠为一行摘要（类型 + 「修改」），点「修改」重新展开。
     *
     * 依据：渐进式披露（NNG 2006 / Apple HIG / Material expansion panel 同型）——
     * 低频/高级选项按需展开，不常驻首屏。host:port 是低频配置，已连接后不必常驻。
     *
     * 门禁约束：home 页断言只查模式按钮 / 三目的地 / 状态页文本，不查本行文案，
     * 故折叠/展开不影响 59 条门禁；hostEdit 始终保留为字段，connectFromUi 仍可读取。
     */
    private fun buildConnectionRow() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        // ① 输入行（未连接 / 展开时可见）
        connectionInputRow = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, 0)
            hostEdit = EditText(this@MainActivity).apply {
                hint = "host:port（留空 = Mock 演示）"
                setSingleLine(true)
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                textSize = 13f; minimumHeight = dp(48)
                setTextColor(c(R.color.md_text)); setHintTextColor(c(R.color.md_text_dim))
                background = roundedCard(c(R.color.md_card), CORNER_LARGE_DP)
                setPadding(dp(12), dp(10), dp(12), dp(10))
                layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
            }
            addView(hostEdit)
            addView(MaterialButton(this@MainActivity).apply {
                text = "连接"; textSize = 12f; minimumHeight = dp(48)
                cornerRadius = dp(CORNER_LARGE_DP)
                setOnClickListener { connectFromUi() }
            }, LinearLayout.LayoutParams(WRAP, WRAP).also { it.marginStart = dp(8) })
        }
        addView(connectionInputRow)
        // ② 摘要行（已连接且未展开时可见）：类型 + 修改入口
        connectionSummary = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = roundedCard(c(R.color.md_card), CORNER_LARGE_DP)
            setPadding(dp(12), dp(8), dp(8), dp(8))
            minimumHeight = dp(44)
            visibility = View.GONE
            connectionSummaryText = TextView(this@MainActivity).apply {
                textSize = 13f; setTextColor(c(R.color.md_text))
                layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
            }
            addView(connectionSummaryText)
            addView(MaterialButton(this@MainActivity).apply {
                text = "修改"; textSize = 12f; minimumHeight = dp(36)
                cornerRadius = dp(CORNER_LARGE_DP)
                setOnClickListener { connectionExpanded = true; renderConnectionRow() }
            })
        }
        addView(connectionSummary)
        renderConnectionRow()
    }

    /** 按连接状态 + 展开标志切换输入行 / 摘要行的可见性。 */
    private fun renderConnectionRow() {
        val connected = SessionHolder.kind.isNotEmpty() && SessionHolder.connectError.isEmpty()
        val showInput = connectionExpanded || !connected
        connectionInputRow.visibility = if (showInput) View.VISIBLE else View.GONE
        connectionSummary.visibility = if (showInput) View.GONE else View.VISIBLE
        if (!showInput) {
            connectionSummaryText.text = "已连接 · ${SessionHolder.kind}"
        }
    }

    /**
     * 控制卡片 —— 把「控制模式」与「进入遥控」合并为一张紧凑卡片，减少首屏独立区块数。
     *
     * 依据：M3 Expressive *connected button group* 用于单选切换（替代 segmented button）。
     * ⚠️ 如实标注：本项目用 MDC **1.12.0（baseline）**，不含 Expressive 组件，**不能**直接用
     * 官方 button group，这里借鉴其「单选按钮紧凑并排」的思路，用现有 MaterialButton 实现，
     * 不声称用了官方组件。模式按钮保留门禁断言文本「手动模式 / 自动模式」。
     */
    private fun buildControlCard() = MaterialCardView(this).apply {
        radius = dp(CORNER_LARGE_DP).toFloat(); cardElevation = 0f
        strokeWidth = dp(STROKE_HAIRLINE_DP); setStrokeColor(c(R.color.md_outline_variant))
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(16), dp(12), dp(16), dp(12))
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        col.addView(TextView(this@MainActivity).apply {
            text = "控制模式"; textSize = 13f; setTextColor(c(R.color.md_text))
            setTypeface(null, Typeface.BOLD)
        })
        val row = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) }
        }
        modeManual = MaterialButton(this@MainActivity).apply {
            text = "手动模式"; textSize = 12f; minimumHeight = dp(48)
            cornerRadius = dp(CORNER_LARGE_DP)
            contentDescription = "手动模式"
            setOnClickListener { switchMode(ControlMode.MANUAL) }
        }
        modeAuto = MaterialButton(this@MainActivity).apply {
            text = "自动模式"; textSize = 12f; minimumHeight = dp(48)
            cornerRadius = dp(CORNER_LARGE_DP)
            contentDescription = "自动模式"
            setOnClickListener { switchMode(ControlMode.AUTO) }
        }
        row.addView(modeManual, LinearLayout.LayoutParams(0, WRAP, 1f))
        row.addView(modeAuto, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(8) })
        col.addView(row)
        modeHint = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, dp(10), 0, 0)
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.2f)
        }
        col.addView(modeHint)
        // 进入遥控按钮并入同一张卡片（原独立启动行），减少一个区块。
        launchButton = MaterialButton(this@MainActivity).apply {
            textSize = 14f; minimumHeight = dp(52)
            cornerRadius = dp(CORNER_LARGE_DP)
            // 主 CTA 亮底必须配深字；主题默认 colorOnPrimary 偏暗紫，真机截图对比度不足。
            setTextColor(c(R.color.md_bg))
            contentDescription = "进入遥控界面"
            layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) }
            setOnClickListener { startActivity(Intent(this@MainActivity, DriveActivity::class.java)) }
        }
        col.addView(launchButton)
        addView(col, FrameLayout.LayoutParams(MATCH, WRAP))
    }

    /** 三个顶层目的地（M3 3–5 destinations），固定位置、不滚动。 */
    private fun buildTabRow() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        // M3 navigation bar 三个目的地应共用一个容器；旧版只有选中项有底，
        // 截图里「状态」像独立胶囊、另两个像裸文字，视觉重心失衡。
        background = roundedCard(c(R.color.md_card), CORNER_LARGE_DP)
        setPadding(dp(4), dp(4), dp(4), dp(4))
        listOf("状态", "健康", "设置").forEachIndexed { i, label ->
            val b = MaterialButton(this@MainActivity).apply {
                text = label; textSize = 12f; minimumHeight = dp(48)
                cornerRadius = dp(CORNER_NAV_DP)
                contentDescription = "标签页$label"
                setOnClickListener { showPage(i) }
            }
            tabButtons.add(b)
            addView(b, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                if (i > 0) it.marginStart = dp(4)
            })
        }
    }

    /** 状态页：实机 robot.state 8 项 + App 本地遥测 6 项，标题写死数据来源。 */
    private fun buildStatePage() = MaterialCardView(this).apply {
        radius = dp(CORNER_LARGE_DP).toFloat(); cardElevation = 0f
        strokeWidth = dp(STROKE_HAIRLINE_DP); setStrokeColor(c(R.color.md_outline_variant))
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(16), dp(12), dp(16), dp(12))
        contentDescription = "监测数据卡：实机状态帧与App本地遥测"
        val scroll = ScrollView(this@MainActivity)
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        stateSourceText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_accent))
            setTypeface(null, Typeface.BOLD)
            letterSpacing = TRACKING_LABEL     // HUD 微排版：小标签字距
            fontFeatureSettings = TABULAR_FIGURES
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.2f)
        }
        col.addView(stateSourceText)
        // 🔴 截图实测：4 列×11sp 把「命令→实际」「航向·时间」挤成折行、行高不齐；
        // 改 2 列并给每格独立表面色（M3 surface container 层级表达），label/value 分色分层。
        // 🔴 真机门禁硬约束：vivo/Android 的 uiautomator 只 dump 视口内节点（off-screen
        // 不吐，与 OEM 无关，是 uiautomator 固有行为）。状态页若用 2 列(8 行 ≈ 480dp)
        // 会超出 ~370dp 的可用高度，遥测区被推到折叠线以下 ⇒ 门禁读不到「本地刷新」。
        // 改 4 列(4 行 ≈ 240dp)让全部内容单屏可见；每格仍保留独立表面色 + label/value
        // 分色分层（A4 的层级表达保留），只是更紧凑 —— 这是窄屏单屏容纳全部监测指标的
        // 通用高密度做法（Material 3 compact window < 600dp + 信息密度权衡），并非退回旧版挤成一团。
        col.addView(metricGrid(4, STATE_LABELS, stateValues),
            LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) })
        col.addView(divider())
        col.addView(TextView(this@MainActivity).apply {
            text = "App 本地遥测（非实机数据 · 会话/心跳/输入计数）"
            textSize = 12f; setTextColor(c(R.color.md_warn))
            setTypeface(null, Typeface.BOLD)
            maxLines = 1; ellipsize = TextUtils.TruncateAt.END
        })
        col.addView(metricGrid(4, TELEMETRY_LABELS, telemetryValues),
            LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) })
        scroll.addView(col)
        addView(scroll, FrameLayout.LayoutParams(MATCH, MATCH))
    }

    private fun metricCell(label: String, value: String) = TextView(this).apply {
        gravity = Gravity.CENTER_VERTICAL
        minimumHeight = dp(40)          // 4 列紧凑栅格：单屏容下全部 15 项
        background = roundedCard(c(R.color.md_card_alt), CORNER_CELL_DP)
        setPadding(dp(8), dp(4), dp(8), dp(4))
        setLineSpacing(0f, 1.1f)
        maxLines = 2; ellipsize = TextUtils.TruncateAt.END
        // 🔑 等宽数字（tabular figures）：状态帧/帧率/计数每秒刷新，比例数字会让
        // 「9 → 10」时宽度跳动、整格左右晃动。一手依据：
        //  · Android 平台 TextView.setFontFeatureSettings / android:fontFeatureSettings
        //    支持 `tnum` OpenType 特性；
        //  · AndroidX `LayoutElementBuilders.FontSetting.tabularNum()` 官方 API 文档 +
        //    cs.android.com 一手源码原文：「all numeral characters will have the same width.
        //    This corresponds to tnum OpenType feature.」
        // ⚠️ 2026-11-13 纠偏：上一版这里挂了「Falcon 控制站排版文献」并附一句引文，
        //    复核 falcon.so/resources/design-basics/real-time-design 原文**没有**该句
        //    （该文献讲「make loss visible immediately / frozen value」，用于 DriveActivity
        //    的状态停滞告警，不是数字排版）⇒ 删除张冠李戴的引文，只留可逐字核验的源码。
        // 只影响字形宽度，不改文本 ⇒ 真机门禁 59/59 断言文本零改动。
        fontFeatureSettings = TABULAR_FIGURES
        setMetric(this, label, value)
    }

    /** label 小字 dim / value 大字近白加粗：M3 type scale 的层级，靠 Span 而非堆 TextView。 */
    private fun setMetric(v: TextView, label: String, value: String) {
        val full = "$label\n$value"
        val sp = SpannableString(full)
        val cut = label.length + 1
        val flags = Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        // 4 列格宽 ~49dp：label 9dp / value 12dp 在窄格里不被挤换行（"命令→实际" 5 字 ≈ 45dp）。
        sp.setSpan(AbsoluteSizeSpan(dp(9)), 0, label.length, flags)
        sp.setSpan(ForegroundColorSpan(c(R.color.md_text_dim)), 0, label.length, flags)
        sp.setSpan(AbsoluteSizeSpan(dp(12)), cut, full.length, flags)
        sp.setSpan(ForegroundColorSpan(c(R.color.md_text)), cut, full.length, flags)
        sp.setSpan(StyleSpan(Typeface.BOLD), cut, full.length, flags)
        v.text = sp
    }

    private fun metricGrid(cols: Int, labels: List<String>, sink: MutableList<TextView>) =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            labels.chunked(cols).forEachIndexed { rowIdx, chunk ->
                val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
                chunk.forEachIndexed { colIdx, label ->
                    val v = metricCell(label, "— 未读到")
                    sink.add(v)
                    row.addView(v, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                        if (colIdx > 0) it.marginStart = dp(4)
                    })
                }
                repeat(cols - chunk.size) {
                    row.addView(View(this@MainActivity), LinearLayout.LayoutParams(0, WRAP, 1f))
                }
                addView(row, LinearLayout.LayoutParams(MATCH, WRAP).also {
                    if (rowIdx > 0) it.topMargin = dp(4)
                })
            }
        }

    private fun divider() = View(this).apply {
        // M3 `outlineVariant` = borders & dividers 的语义角色（不再用临时拼的半透明色）。
        setBackgroundColor(c(R.color.md_outline_variant))
        layoutParams = LinearLayout.LayoutParams(MATCH, dp(STROKE_HAIRLINE_DP)).also {
            it.topMargin = dp(16); it.bottomMargin = dp(12)
        }
    }

    private fun buildHealthPage() = MaterialCardView(this).apply {
        radius = dp(CORNER_LARGE_DP).toFloat(); cardElevation = 0f
        strokeWidth = dp(STROKE_HAIRLINE_DP); setStrokeColor(c(R.color.md_outline_variant))
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(10), dp(8), dp(10), dp(8))
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        healthSourceText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_warn))
        }
        col.addView(healthSourceText)
        col.addView(TextView(this@MainActivity).apply {
            text = "robot.health 真字段：缺失显示「未读到」，绝不渲染成 0"
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
        })
        val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(MaterialButton(this@MainActivity).apply {
            text = "刷新"; minimumHeight = dp(48)
            setOnClickListener { refreshHealth() }
        })
        autoRefreshBox = CheckBox(this@MainActivity).apply {
            text = "每秒自动刷新"; minimumHeight = dp(48)
            setTextColor(c(R.color.md_text_dim))
            setOnCheckedChangeListener { _, checked ->
                SessionHolder.autoRefreshHealth = checked
                persist()
            }
        }
        row.addView(autoRefreshBox)
        col.addView(row)
        healthText = TextView(this@MainActivity).apply {
            textSize = 13f; setTextColor(c(R.color.md_text))
            setTypeface(Typeface.MONOSPACE); setPadding(0, dp(8), 0, dp(8))
        }
        val scroll = ScrollView(this@MainActivity).apply { addView(healthText) }
        col.addView(scroll, LinearLayout.LayoutParams(MATCH, 0, 1f))
        addView(col, FrameLayout.LayoutParams(MATCH, MATCH))
    }

    /** 设置页：所有参数写 SessionHolder，DriveActivity 启动时读取，避免「改了没生效」。 */
    private fun buildSettingsPage() = MaterialCardView(this).apply {
        radius = dp(CORNER_LARGE_DP).toFloat(); cardElevation = 0f
        strokeWidth = dp(STROKE_HAIRLINE_DP); setStrokeColor(c(R.color.md_outline_variant))
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(10), dp(8), dp(10), dp(8))
        val scroll = ScrollView(this@MainActivity)
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        col.addView(TextView(this@MainActivity).apply {
            text = "遥控参数（进入横屏遥控页时生效 · 已本地持久化）"
            textSize = 12f; setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
            letterSpacing = TRACKING_LABEL
        })
        // 完整依据：取自 ROS_Robot_Controller / ohho.apk 的 persistent preferences；
        // 控制模式与连接地址刻意不持久化 —— 每次冷启动回手动，保留手动接管入口
        // （安全原则见《首页界面设计依据》§10 与《功能缺口清单》）。
        // 🔴 这里压成单行：真机 uiautomator 只 dump 视口内节点，两行说明会把下方
        // 「方向摇杆死区」标签推出设置页首屏（门禁 59 条实测 FAIL），依据不丢只是移到注释。
        col.addView(TextView(this@MainActivity).apply {
            text = "取自 ROS_Robot_Controller / ohho.apk；模式与地址不持久化"
            textSize = 10f; setTextColor(c(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, 0, 0, dp(6))
        })
        val (channelView, channelInput) =
            buildDropdown(col, "驾驶通道", CHANNEL_ITEMS, SessionHolder.channelIndex) { pos ->
                SessionHolder.channelIndex = pos
                persist()
            }
        channelDropdown = channelInput
        col.addView(channelView, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(4)
        })

        val (headRadView, headRadInput) = buildDropdown(col, "头部幅度", HEAD_RAD_ITEMS,
            SessionHolder.headRadIndex) { pos ->
            SessionHolder.headRadIndex = pos
            persist()
        }
        headRadDropdown = headRadInput
        col.addView(headRadView, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(4)
        })
        invertBox = CheckBox(this@MainActivity).apply {
            text = "反转前后（真机 R17 映射决定，客户端不硬编码）"
            textSize = 11f; minimumHeight = dp(48)
            setTextColor(c(R.color.md_text_dim))
            isChecked = SessionHolder.invertY
            setOnCheckedChangeListener { _, checked -> SessionHolder.invertY = checked; persist() }
        }
        col.addView(invertBox)
        vxLabel = TextView(this@MainActivity).apply { textSize = 11f; setTextColor(c(R.color.md_text_dim)) }
        yawLabel = TextView(this@MainActivity).apply { textSize = 11f; setTextColor(c(R.color.md_text_dim)) }
        driveDzLabel = TextView(this@MainActivity).apply { textSize = 11f; setTextColor(c(R.color.md_text_dim)) }
        headDzLabel = TextView(this@MainActivity).apply { textSize = 11f; setTextColor(c(R.color.md_text_dim)) }
        vxBar = SeekBar(this@MainActivity).apply {
            max = 80; progress = (SessionHolder.maxVx * 100).toInt(); minimumHeight = dp(36)
        }
        yawBar = SeekBar(this@MainActivity).apply {
            max = 250; progress = (SessionHolder.maxVyaw * 100).toInt(); minimumHeight = dp(36)
        }
        // 死区可调取自 ble-rc-controller 的 Settings「dead zone」；core 两个 Controller 本就有 deadzone 字段。
        driveDzBar = SeekBar(this@MainActivity).apply {
            max = 30; progress = (SessionHolder.driveDeadzone * 100).toInt(); minimumHeight = dp(36)
        }
        headDzBar = SeekBar(this@MainActivity).apply {
            max = 30; progress = (SessionHolder.headDeadzone * 100).toInt(); minimumHeight = dp(36)
        }
        val listener = object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, p: Int, fromUser: Boolean) {
                SessionHolder.maxVx = vxBar.progress / 100.0
                SessionHolder.maxVyaw = yawBar.progress / 100.0
                SessionHolder.driveDeadzone = driveDzBar.progress / 100.0
                SessionHolder.headDeadzone = headDzBar.progress / 100.0
                updateSettingLabels()
                persist()
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        }
        // 🔑 监听器注册在 progress 初值之后：setProgress 也会回调 onProgressChanged，
        // 早注册会在 onCreate 里把刚 load 出来的用户设置又写回默认值。
        vxBar.setOnSeekBarChangeListener(listener)
        yawBar.setOnSeekBarChangeListener(listener)
        driveDzBar.setOnSeekBarChangeListener(listener)
        headDzBar.setOnSeekBarChangeListener(listener)
        col.addView(vxLabel); col.addView(vxBar)
        col.addView(yawLabel); col.addView(yawBar)
        col.addView(driveDzLabel); col.addView(driveDzBar)
        col.addView(headDzLabel); col.addView(headDzBar)
        updateSettingLabels()
        col.addView(MaterialButton(this@MainActivity).apply {
            text = "恢复默认设置"; textSize = 12f; minimumHeight = dp(48)
            cornerRadius = dp(CORNER_LARGE_DP)
            contentDescription = "恢复默认设置"
            setOnClickListener {
                SettingsStore.reset(applicationContext)
                restoreSettingsUi()
                updateSettingLabels()
                renderAll()
            }
        }, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) })
        // A1：BLE 运行时权限 + unfiltered 扫描 + 真 BleTransport 入口。
        // 放设置页最末尾，避免把上面的反转开关/滑杆挤出可见区（真机门禁靠 UI dump 定位）。
        col.addView(blePanel.buildView(), LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(16)
        })
        // GitHub Releases 自更新面板放**最末尾**：uiautomator 只 dump 视口内节点，
        // 往上插会把「方向摇杆死区」推出首屏（门禁 59 条实测踩过）；门禁的
        // scroll_until("扫描附近 BLE 设备") 在到达这里之前就停，也不受新增节点影响。
        col.addView(updatePanel.view, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(16)
        })
        scroll.addView(col)
        addView(scroll, FrameLayout.LayoutParams(MATCH, MATCH))
    }

    /**
     * M3「Exposed dropdown menu」—— 替换 `android.widget.Spinner` 的现代化选择控件。
     *
     * 一手依据（material-components-android 仓库 `docs/components/Menu.md`，2026-11-13
     * 经 raw.githubusercontent.com 逐字核验；本地 javap 对 material-1.12.0.aar 实证 API）：
     *  · 「The exposed dropdown menu is implemented through the TextInputLayout.」⇒ 用
     *    `Widget.Material3.TextInputLayout.OutlinedBox.ExposedDropdownMenu` 样式，
     *    而不是平台 `Spinner`（后者弹窗是纯黑直角矩形、无圆角/无选中标记、不吃 M3 主题色，
     *    见本次改造前的真机截图 `_settings_popup.png`）。
     *  · 「For a non-editable menu, disable the user input ... android:inputType="none"」
     *    ⇒ **仅** XML 设 `none`；不再自行禁 focusable / keyListener，也不自定义 showDropDown，
     *    弹窗开关完全交给 MDC 的 DropdownMenuEndIconDelegate（一手依据见函数内注释）。
     *    官方文档「Non editable variation」整节也只有这一条要求。
     *  · 「call setText(CharSequence text, boolean filter) ... with the filter set to false」
     *    ⇒ 预选值与回写值都用 `setText(text, false)`；`filter=true` 会触发自动补全过滤导致
     *    默认值显示不出来，且不会触发 onItemClick，不会误写 SessionHolder / 误触发 persist。
     *  · `setSimpleItems(String[])`、`setDropDownBackgroundTint`、`simpleItemSelectedColor`、
     *    `popupElevation=3dp` 让弹窗吃 M3 `colorSurfaceContainer*` 分层表面（深蓝而非纯黑）。
     *
     * ⚠️ 门禁约束：`uiautomator` 只 dump 视口内节点，故下拉高度受控（label 浮在描边线上，
     * 不额外占一行）；下方「反转前后」CheckBox 仍需留在首屏视口内，真机 59/59 已复验。
     */
    private fun buildDropdown(
        parent: LinearLayout,
        label: String,
        items: List<String>,
        selected: Int,
        onPick: (Int) -> Unit,
    ): Pair<TextInputLayout, MaterialAutoCompleteTextView> {
        // 🔴 Android lint InflateParams：inflate 必须给非 null parent + attachToRoot=false，
        // 否则根元素的 layout_width/height 无法解析成对应类型的 LayoutParams。
        val root = LayoutInflater.from(this)
            .inflate(R.layout.widget_exposed_dropdown, parent, false) as TextInputLayout
        val input = root.findViewById<MaterialAutoCompleteTextView>(R.id.dropdown_input)
        root.hint = label
        input.setSimpleItems(items.toTypedArray())
        // 官方「Setting a default value」：setText(text, filter=false)。filter=true 会触发
        // 自动补全过滤，预选值显示不出来，且不会误触发 onItemClick / persist。
        input.setText(items[selected.coerceIn(items.indices)], false)
        // 🔴 非编辑态**只**靠 XML 的 android:inputType="none"，不要额外写
        // keyListener=null / isFocusable=false / 自定义 OnClickListener(showDropDown)。
        // 一手依据：material-components-android `DropdownMenuEndIconDelegate.java`
        // （2026-11-13 经 raw.githubusercontent.com 抓取逐行核验）：
        //  · setUpDropdownShowHideBehavior() 已给 AutoCompleteTextView 注册 OnTouchListener，
        //    ACTION_UP 时调 showHideDropdown() —— 整个输入框可点，且是「开/关切换」；
        //  · onIconClickListener 复用同一个 showHideDropdown()；
        //  · showHideDropdown() 内部 autoCompleteTextView.requestFocus() + showDropDown()：
        //    若把 isFocusable 设成 false，焦点态（editTextHasFocus / endIcon activated /
        //    无障碍 TYPE_VIEW_CLICKED 路径）会被破坏；再挂一个「只弹不关」的 OnClickListener
        //    还会与框架的 toggle 语义打架（一次点击两条路径）。
        //  · onInitializeAccessibilityNodeInfo() 把非编辑下拉伪装成 Spinner 供 TalkBack 识别，
        //    也是框架职责，不需要 App 侧补。
        // 结论：App 只负责业务回调（选中项 → SessionHolder），交互一律交给 MDC。
        input.setOnItemClickListener { _, _, pos, _ -> onPick(pos) }
        return root to input
    }

    /** 把 SessionHolder 的当前值写回设置页控件（load / reset 后用）。 */
    private fun restoreSettingsUi() {
        channelDropdown.setText(
            CHANNEL_ITEMS[SessionHolder.channelIndex.coerceIn(CHANNEL_ITEMS.indices)], false)
        headRadDropdown.setText(
            HEAD_RAD_ITEMS[SessionHolder.headRadIndex.coerceIn(HEAD_RAD_ITEMS.indices)], false)
        invertBox.isChecked = SessionHolder.invertY
        autoRefreshBox.isChecked = SessionHolder.autoRefreshHealth
        vxBar.progress = (SessionHolder.maxVx * 100).toInt()
        yawBar.progress = (SessionHolder.maxVyaw * 100).toInt()
        driveDzBar.progress = (SessionHolder.driveDeadzone * 100).toInt()
        headDzBar.progress = (SessionHolder.headDeadzone * 100).toInt()
    }

    private fun updateSettingLabels() {
        vxLabel.text = "前进上限 %.2f m/s（占位，待整机标定）".format(SessionHolder.maxVx)
        yawLabel.text = "转向上限 %.2f rad/s（占位，待整机标定）".format(SessionHolder.maxVyaw)
        driveDzLabel.text = "方向摇杆死区 %.2f（占位，待整机标定）".format(SessionHolder.driveDeadzone)
        headDzLabel.text = "头部摇杆死区 %.2f（占位，待整机标定）".format(SessionHolder.headDeadzone)
    }

    private fun buildBottomStatus() = TextView(this).apply {
        bottomStatus = this
        textSize = 11f; setTextColor(c(R.color.md_text_dim))
        background = roundedCard(c(R.color.md_card), CORNER_LARGE_DP)
        setPadding(dp(10), dp(6), dp(10), dp(6))
        setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
        fontFeatureSettings = TABULAR_FIGURES   // 帧数逐秒变化时数字不抖动
    }

    /**
     * 统一表面容器：细描边 + 项目圆角 token。
     *
     * 一手依据：
     *  · 形状量级：解包 material-1.12.0.aar/res/values/values.xml 实证组件大圆角
     *    `m3_navigation_drawer_layout_corner_size=16dp`、
     *    `m3_carousel_small_item_default_corner_size=28dp`；本项目取 20dp 落在同一量级。
     *    ⚠️ 2026-11-13 纠偏：此前注释写「M3 Expressive 官方 Large token = 20dp」并附引文，
     *    但 m3.material.io Shape 页为 JS 渲染抓不到原文、本地 AAR 也无 20dp 通用 shape
     *    token ⇒ 不再声称官方数值，降级为**本项目约定值**，见设计依据文档。
     *  · Google Material Design 3「Color roles」：`outline` / `outlineVariant` 用于
     *    「Borders, dividers」；配合本项目采用的 HUD 设计参考（Chris Lemke, Sci-Fi Interface）
     *    「**Borders Over Fills** — Thin luminous borders define panels and create the skeletal
     *    structure of the HUD」「Hierarchy Through Luminance」⇒ 卡片用 1dp 低对比描边取代
     *    纯色块堆叠，层级靠亮度而非色相。
     *  · ⚠️ 该 HUD 参考同时建议扫描线 / 雷达动画，本项目**不采纳**：M3「Don't compromise
     *    clarity for the sake of visual design」+ 真机门禁 `uiautomator` 要求 1000ms 静默窗
     *    （持续动画会触发无障碍事件导致 dump 死锁），详见设计依据文档「负向决策」章节。
     */
    private fun roundedCard(fill: Int, radiusDp: Int, stroked: Boolean = true) =
        GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(radiusDp).toFloat()
            if (stroked) setStroke(dp(STROKE_HAIRLINE_DP), c(R.color.md_outline_variant))
        }

    /** 每次改动立刻落盘；不依赖 onStop，避免进程被杀丢设置。 */
    private fun persist() = SettingsStore.save(applicationContext)

    private fun showPage(i: Int) {
        currentPage = i
        statePage.visibility = if (i == 0) View.VISIBLE else View.GONE
        healthPage.visibility = if (i == 1) View.VISIBLE else View.GONE
        settingsPage.visibility = if (i == 2) View.VISIBLE else View.GONE
        tabButtons.forEachIndexed { idx, b ->
            val selected = idx == i
            b.setBackgroundColor(if (selected) c(R.color.md_card_alt) else Color.TRANSPARENT)
            // 🔴 MaterialButton 的文字色来自主题 colorOnPrimary(深色)，只换背景不换文字
            // ⇒ 未选中态「深底 + 深字」几乎不可读（真机截图实测「健康/设置」发暗紫）。
            // 选中/未选中都要显式给文字色：深底配浅字、选中态再用 accent 高亮。
            b.setTextColor(if (selected) c(R.color.md_accent) else c(R.color.md_text_dim))
            b.setTypeface(null, if (selected) Typeface.BOLD else Typeface.NORMAL)
        }
    }

    private fun switchMode(m: ControlMode) {
        SessionHolder.selectMode(m)
        refreshModeUi()
        renderAll()
    }

    private fun refreshModeUi() {
        val manual = SessionHolder.mode == ControlMode.MANUAL
        modeManual.setBackgroundColor(if (manual) c(R.color.md_accent) else c(R.color.md_card_alt))
        modeAuto.setBackgroundColor(if (!manual) c(R.color.md_warn) else c(R.color.md_card_alt))
        // 亮底(accent/warn)配深字、深底(card_alt)配近白字；只用主题默认深色字会在
        // 未选中态暗到看不清。与 showPage() 的 tab 配色同型修复。
        modeManual.setTextColor(if (manual) c(R.color.md_bg) else c(R.color.md_text))
        modeAuto.setTextColor(if (!manual) c(R.color.md_bg) else c(R.color.md_text))
        modeHint.text = if (manual)
            "手动：双摇杆连续发送 robot.move / robot.head；退出遥控页立即归零停车"
        else
            "自动：App 零驾驶帧、只监测 robot.state；未验证策略启停，不等于已启动自主行走"
        launchButton.text = if (manual) "进入遥控驾驶（横屏全屏）" else "进入监测视图（横屏全屏）"
        healthSourceText.text = if (SessionHolder.kind == "MOCK")
            "⚠ 当前为 Mock 演示夹具，非实机读数" else "robot.health 实机应答"
    }

    private fun connectFromUi() {
        val raw = hostEdit.text?.toString()?.trim().orEmpty()
        SessionHolder.connect(raw) { ok ->
            runOnUiThread {
                val chipText = when {
                    ok -> "● ${SessionHolder.kind}"
                    SessionHolder.connectError.isNotEmpty() -> "● 地址无效"
                    else -> "● 未连接"
                }
                val chipColor = if (ok) c(R.color.md_ok) else c(R.color.md_bad)
                // 三个目的地各持一套来源标签，统一刷新。
                pageChromes.forEach { chrome ->
                    chrome.sourceChip.text = chipText
                    chrome.sourceChip.setTextColor(chipColor)
                }
                refreshModeUi()
                renderConnectionRow()
                renderAll()
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == BleConnectPanel.REQ_CODE) blePanel.onPermissionResult(grantResults)
    }

    private fun refreshHealth() {
        SessionHolder.refreshHealth { text ->
            runOnUiThread { healthText.text = text; renderAll() }
        }
    }

    /** 实机 8 项：null = 无帧，一律「未读到」，绝不写 0、绝不拿本地计数填。 */
    private fun renderState(s: StateSnapshot?) {
        val vals: List<String> = if (s == null) List(STATE_LABELS.size) { "— 未读到" } else listOf(
            s.policy ?: "— 未读到",
            s.loopHz?.let { if (it <= 0.0) "0 Hz·窗口未闭合" else "%.1f Hz".format(it) } ?: "— 未读到",
            s.applied?.takeIf { it.size >= 3 }?.let { a ->
                val r = s.requested?.takeIf { it.size >= 3 }
                "${r?.let { "%.2f".format(it[0]) } ?: "—"}→%.2f m/s".format(a[0])
            } ?: "— 未读到",
            when {
                s.limitedBy.isNotEmpty() -> "⚠ " + s.limitedBy.joinToString(",").take(14)
                s.requested == null && s.applied == null -> "— 未读到"
                else -> "未限幅"
            },
            when {
                s.fallen == true -> "⚠ 已摔倒"
                s.limp == true -> "⚠ 已卸力"
                s.fallen == null -> "— 未读到"
                else -> "站立"
            },
            s.head?.takeIf { it.size >= 4 }?.let { "p%.2f y%.2f".format(it[1], it[2]) } ?: "— 未读到",
            s.currentText(),
            s.odomYaw?.let { "%.1f° · t=%s".format(Math.toDegrees(it),
                s.t?.let { "%.1fs".format(it) } ?: "—") } ?: "— 未读到",
        )
        stateValues.forEachIndexed { i, v -> setMetric(v, STATE_LABELS[i], vals[i]) }
        stateSourceText.text = if (s == null)
            "实机状态帧 · robot.state · 当前无状态帧\nMock 不推流 / 真机未连接，不伪造"
        else "实机状态帧 · robot.state [${SessionHolder.kind}] · 第 ${SessionHolder.stateFrameCount} 帧"
    }

    private fun renderTelemetry() {
        val localVals = listOf(
            SessionHolder.sessionState(),
            SessionHolder.sinkLabel,
            "%d 帧 · %s".format(SessionHolder.sentCount.get(),
                if (SessionHolder.heartbeatRunning) "心跳中" else "已停"),
            "%d 帧".format(SessionHolder.headSentCount.get()),
            if (SessionHolder.stateFrameCount == 0) "0 帧 · 无流"
            else "%d 帧 · %.1f Hz".format(SessionHolder.stateFrameCount, SessionHolder.stateHz),
            SessionHolder.lastInput,
            // 拆页后主页不持有 controller ⇒ 驾驶帧恒 0 是正确行为。
            // 这一项给「本地遥测面板真的在刷新」提供可观测量，且明确属于 App 自观测。
            "%d 次".format(SessionHolder.uiTickCount.get()),
        )
        TELEMETRY_LABELS.forEachIndexed { i, label ->
            telemetryValues.getOrNull(i)?.let { setMetric(it, label, localVals[i]) }
        }
    }

    private fun renderAll() {
        renderState(SessionHolder.lastState)
        renderTelemetry()
        renderLinkBanner()
        renderConnectionRow()
        // 单行状态串：完整信息在来源标签 / 状态卡里，不再让 appBar 折成两行。
        // 三个目的地各持一套状态串，统一刷新，保证任何页面下连接/模式/帧数都可见。
        val statusText = if (SessionHolder.connectError.isNotEmpty())
            "地址无效 · 会话=${SessionHolder.sessionState()}"
        else buildString {
            if (SessionHolder.note.isNotEmpty() && SessionHolder.note != "地址无效")
                append(SessionHolder.note).append(" · ")
            append(if (SessionHolder.mode == ControlMode.MANUAL) "手动" else "自动")
            append(" · ").append(SessionHolder.sessionState())
            append(" · ").append(SessionHolder.stateFrameCount).append(" 帧")
        }
        pageChromes.forEach { chrome -> chrome.statusText.text = statusText }
        bottomStatus.text = buildString {
            append("通道=").append(SessionHolder.sinkLabel)
            append(" · 已发 ").append(SessionHolder.sentCount.get()).append(" 帧")
            append(" · 头 ").append(SessionHolder.headSentCount.get()).append(" 帧")
            append(" · 状态帧 ").append(SessionHolder.stateFrameCount)
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            SessionHolder.tick()
            renderAll()
            if (SessionHolder.autoRefreshHealth && currentPage == 1) refreshHealth()
            ui.postDelayed(this, 1_000)
        }
    }

    override fun onResume() {
        super.onResume()
        // 从「安装未知应用」系统设置返回后复查权限：返回动作本身不等于已授权。
        if (::updatePanel.isInitialized) updatePanel.onResume()
    }

    override fun onDestroy() {
        ui.removeCallbacks(tick)
        blePanel.onDestroy()
        updateController.release()
        // 🔴 不 close session：SessionHolder 拥有它，DriveActivity 返回后仍要复用。
        super.onDestroy()
    }

    private companion object {
        /** 仅 debug 端到端验证用：adb shell am start -e update_api_base http://127.0.0.1:PORT */
        const val EXTRA_UPDATE_API_BASE = "update_api_base"
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT

        // ── 视觉 token（2026-11-13 现代化改造）──
        // 视觉 token 具名化（项目约定值，非官方 token 数值）：
        //  · 20dp 圆角量级参照 MDC 1.12.0 AAR 实测组件圆角 16dp / 28dp（见 roundedCard KDoc）；
        //  · 1dp 细描边对应 M3「Color roles」的 outline = borders/dividers 语义。
        // 🔴 不再把 20 / 1 / "tnum" 等字面量散落在十几个调用点：token 必须具名，
        //    改一处即可全局生效。XML 侧的 @dimen/m3_corner_large 与这里同源，
        //    数值改动须两处同步（见设计依据文档「token 单一真源」条目）。
        const val CORNER_LARGE_DP = 20        // 主容器 / 按钮 / 输入框
        const val CORNER_NAV_DP = 16          // 导航栏内层按钮
        const val CORNER_CELL_DP = 12         // 遥测单元格
        const val STROKE_HAIRLINE_DP = 1      // 细描边（Borders Over Fills）
        const val TABULAR_FIGURES = "tnum"    // OpenType tabular figures
        const val TRACKING_TITLE = 0.08f      // 标题字距（HUD machine-stamped）
        const val TRACKING_LABEL = 0.05f      // 小标签字距

        val STATE_LABELS = listOf("策略", "控制环", "命令→实际", "限幅",
            "安全", "头部", "电流", "航向·时间")
        val TELEMETRY_LABELS = listOf("会话状态", "驱动通道", "驾驶帧 / 心跳",
            "头部帧", "状态帧 / 帧率", "最后输入", "本地刷新")

        /** 下拉候选项：文案一字不改（真机门禁与用户既有认知依赖这些子串）。
         *  🔴 用不可变 List 而非 arrayOf：Kotlin 官方命名约定要求持有 mutable data
         *  的属性用 camelCase，全大写只给 deeply immutable 常量；Array 是可变的。 */
        val CHANNEL_ITEMS = listOf("JSON-RPC（TCP/仿真）", "UDP netpad（真机 :4210）")
        val HEAD_RAD_ITEMS = listOf("头部幅度 0.5 rad", "头部幅度 1.0 rad",
            "头部幅度 2.5 rad")
    }
}
