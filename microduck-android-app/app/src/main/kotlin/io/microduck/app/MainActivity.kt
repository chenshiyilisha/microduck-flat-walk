package io.microduck.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.ConnectivityManager
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
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
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.graphics.Insets
import androidx.core.net.toUri
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.google.android.material.textfield.TextInputLayout
import io.microduck.app.ble.BleConnectPanel
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.MonitorVerdict
import io.microduck.app.core.DiagnosticsSnapshot
import io.microduck.app.core.NetSnapshot
import io.microduck.app.core.NetProvisioning
import io.microduck.app.core.RobotPart
import io.microduck.app.core.RobotParts
import io.microduck.app.core.Severity
import io.microduck.app.core.StateSnapshot
import io.microduck.app.core.TofSnapshot
import io.microduck.app.core.TofZone
import io.microduck.app.core.HealthSnapshot
import io.microduck.app.core.HwThresholds
import io.microduck.app.monitor.DuckModelView
import io.microduck.app.ssh.SshPanel
import io.microduck.app.ssh.SshRepository
import io.microduck.app.update.GithubReleaseClient
import io.microduck.app.update.UpdateRepository
import io.microduck.app.update.FirmwarePanel
import io.microduck.app.update.UpdatePanel
import kotlinx.coroutines.launch

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

    /** 全局唯一的 AppBar 状态控件（状态串 / 来源标签 / 链路横幅）。
     *  2026-11-15 去重：旧版**每个目的地各持一套**（pageChromes 三份），切换页面时
     *  顶部「MicroDuck 控制台」卡片与链路横幅在三页反复出现，用户反馈重复。
     *  现收敛为框架层常驻一份，标题随目的地变化；底部「通道=…」状态条与状态页
     *  「App 本地遥测」完全重复，一并移除。 */
    private class PageChrome(
        val titleText: TextView,
        val statusText: TextView,
        val sourceChip: TextView,
        val linkBanner: TextView,
    )
    private lateinit var chrome: PageChrome

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
    // 一键休息 / 恢复站立（robot.rest / robot.init，无参离散请求）。
    // 状态回显分两层：关节 limp 状态（robot.state.safety.limp，常驻）+ 请求结果（点击后更新）。
    private lateinit var restButton: MaterialButton
    private lateinit var wakeButton: MaterialButton
    private lateinit var restLimpText: TextView
    private lateinit var restResultText: TextView
    private lateinit var stateSourceText: TextView
    private lateinit var healthText: TextView
    private lateinit var healthSourceText: TextView
    // 2026-11-15 硬件监控：旋转仿真模型 + 告警 + 结构化状态卡片
    private lateinit var duckModelView: DuckModelView
    private lateinit var monitorAlertText: TextView
    /** A3/A6/A7 只读诊断文本（健康页底部，点按钮刷新，缺数据显示「未读到」）。 */
    private lateinit var diagnosticsText: TextView
    /** A2 配网：状态文本 + 扫描结果可点选列表 + SSID/密码输入（设置页，写操作需二次确认）。 */
    private lateinit var netStatusText: TextView
    /** net.scan 结果的可点选列表容器：点一项自动填 SSID，取代手录（手输仍保留兜底）。 */
    private lateinit var netScanList: LinearLayout
    /** 上次渲染的扫描签名：renderAll 每 1s tick 都调 renderNet，内容没变不重建 View。 */
    private var netScanSignature: String? = null
    private lateinit var netSsidEdit: EditText
    /** 手机当前连接的 Wi-Fi 名称（本机读取，不是板端 net.status 的读数）。 */
    private var phoneSsid: String? = null
    private var phoneSsidNote = "尚未读取"
    /** 上次自动填入的值：只在输入框空或等于该值时更新，绝不覆盖用户手输。 */
    private var autoFilledPhoneSsid: String? = null
    private lateinit var netPskEdit: EditText
    private lateinit var netResultText: TextView
    private lateinit var autoRefreshBox: CheckBox
    // 结构化状态卡片（电量/板级状态/舵机温度/总线/IMU/控制环）：值文本 + 状态色点。
    // 取代原先「原始 JSON 长文本 + 部位统计 + 告警 + 模型」四重重复呈现（用户反馈杂乱）。
    private val healthCardVals = mutableListOf<TextView>()
    private val healthCardDots = mutableListOf<View>()
    // 15 舵机逐点状态网格（5×3）：每格 = 状态色点 + 舵机 ID + 关节名。
    // 协议边界：robot.health 对舵机只给聚合温度，逐点数据来自 bus.missing（缺失点名）；
    // 缺失=红、在线=绿、无数据=灰，绝不造数、不默认绿。
    private val servoCells = mutableListOf<LinearLayout>()
    private lateinit var servoGridCard: View
    // 11-20 参照设计稿 .grp：三组「部位整体健康度」徽章（左腿/颈头喙/右腿），
    // 从 missingIds 真实派生，缺字段=未读到不造数。渐进式披露：先看组，再看逐点网格。
    private val partBadges = mutableListOf<TextView>()
    // ToF 8×8 深度网格（头部测距雷达）：64 格 TextView，三态着色（量程/空/失败）。
    // 数据来源 tof.frame：Mock 夹具非实机、真机需 mediad WebRTC（btd 拒 tof.stream）。
    private val tofCells = mutableListOf<TextView>()
    private lateinit var tofSourceText: TextView
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
    private lateinit var firmwarePanel: FirmwarePanel
    private lateinit var updateRepository: UpdateRepository
    private lateinit var updatePanel: UpdatePanel
    private lateinit var statePage: View
    private lateinit var healthPage: View
    private lateinit var settingsPage: View
    private lateinit var sshPage: View
    private lateinit var sshPanel: SshPanel
    /** 已回填到终端 IP 框的配网序号；只在固件回执产生新序号时才再次回填。 */
    private var appliedProvisionedIpSeq: Long = 0L
    /** 阶段 3：SSH 会话单一真源，跨终端页重建存活（面板只订阅，不持有 session）。 */
    private val sshRepository = SshRepository()
    private val stateValues = mutableListOf<TextView>()
    private val telemetryValues = mutableListOf<TextView>()
    // 2026-11-19 去卡片化：底部导航从「MaterialButton 填充块」改为「图标+文字文本标签」，
    // 容器类型随之从 MaterialButton 改为 TextView（uiautomator 仍按 content-desc 定位）。
    private val tabButtons = mutableListOf<View>()
    /** 底部导航每格的 2px 选中指示条（未选中透明），与文字/图标同色。 */
    private val tabIndicators = mutableListOf<View>()
    private var currentPage = 0
    private val ui = Handler(Looper.getMainLooper())

    /** 阶段 2：控制台首页 ViewModel，聚合四页 uiState，状态出口统一为 StateFlow（UDF 单一真源）。 */
    private val viewModel: MainViewModel by viewModels { AppViewModelFactory.main }

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
        updateRepository = UpdateRepository(this, overrideBase ?: GithubReleaseClient.API_BASE, extraHosts)
        updatePanel = UpdatePanel(this, updateRepository)
        // 固件 OTA：回调转发到 ViewModel → RobotRepository（写操作二次确认在面板内）。
        firmwarePanel = FirmwarePanel(
            this,
            onRefresh = { viewModel.onRefreshFirmware() },
            onCheck = { viewModel.onCheckFirmware() },
            onApply = { v, dry -> viewModel.onApplyFirmware(v, dry) },
            onRollback = { viewModel.onRollbackFirmware() },
        )
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
        // 2026-11-15 去重重构：AppBar / 链路横幅收敛为**框架层全局唯一一份**，
        // 不再每个目的地各复制一套；底部「通道=…」状态条与状态页遥测重复，已移除。
        // 依据 M3 navigation bar「Use navigation for distinct pages」：常驻框架层
        // 只承载会话级状态，页面专属内容各自独立，避免三页顶部/底部同款卡片重复。
        chrome = PageChrome(
            titleText = TextView(this).apply {
                // 对齐 HTML .brand 18px；hero 仍留给主动作「进入遥控」。
                textSize = 18f; setTextColor(c(R.color.md_text))
                setTypeface(null, Typeface.BOLD); letterSpacing = 0.02f
                setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            },
            statusText = TextView(this).apply {
                textSize = 11f; setTextColor(c(R.color.md_text_dim))
                setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
                fontFeatureSettings = TABULAR_FIGURES
            },
            sourceChip = TextView(this).apply {
                // 状态 pill：小圆角 + 细描边；Mock=警示 / Real=绿。文案由 renderSourceChip 写入。
                text = "● 演示会话"; textSize = 11f
                setTypeface(null, Typeface.BOLD)
                fontFeatureSettings = TABULAR_FIGURES
                setPadding(dp(10), dp(4), dp(10), dp(4))
                background = roundedCard(c(R.color.md_card_alt), CORNER_CHIP_DP, stroked = true)
            },
            linkBanner = buildLinkBanner(),
        )
        content.addView(buildAppBar(chrome), LinearLayout.LayoutParams(MATCH, WRAP))
        content.addView(chrome.linkBanner, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(8)
        })
        val pages = FrameLayout(this)
        statePage = buildPage(0)
        healthPage = buildPage(1)
        settingsPage = buildPage(2)
        sshPage = buildPage(3)
        pages.addView(statePage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(healthPage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(settingsPage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(sshPage, FrameLayout.LayoutParams(MATCH, MATCH))
        content.addView(pages, LinearLayout.LayoutParams(MATCH, 0, 1f).also {
            it.topMargin = dp(8)
        })
        // M3 navigation bar 规范：容器固定在窗口底部、目的地位置不滚动。
        section(buildTabRow())
        root.addView(content, FrameLayout.LayoutParams(MATCH, MATCH))

        topScrim = View(this).apply { setBackgroundColor(Color.argb(190, 0x09, 0x0A, 0x0C)) }
        root.addView(topScrim, FrameLayout.LayoutParams(MATCH, 0, Gravity.TOP))
        setContentView(root)

        // Android 15+ 强制 edge-to-edge：insets 转 padding + 状态栏 scrim；
        // 返回置零 insets 防后代重复 padding（官方 webview insets 文档同型）。
        ViewCompat.setOnApplyWindowInsetsListener(content) { v, insets ->
            val types = WindowInsetsCompat.Type.systemBars() or
                WindowInsetsCompat.Type.displayCutout()
            val b = insets.getInsets(types)
            val p = dp(16)       // M1 官方：mobile screen edge margins 16dp（左/右/底）
            // 顶部：状态栏 scrim（topScrim）已是天然分隔线，其下只需小留白，
            // 不再套 16dp 全向边距，否则状态栏到 AppBar 会空出 24dp（用户反馈 2026-11-14）。
            val top = dp(8)
            v.setPadding(p + b.left, top + b.top, p + b.right, p + b.bottom)
            topScrim.layoutParams = FrameLayout.LayoutParams(MATCH, b.top, Gravity.TOP)
            WindowInsetsCompat.Builder(insets).setInsets(types, Insets.NONE).build()
        }

        showPage(0)
        blePanel.handlePairingIntent(intent)
        connectFromUi()                    // 默认 Mock：触发连接，结果经 uiState 渲染
        // 阶段 2 UDF（官方 repeatOnLifecycle 模式）：订阅 uiState 渲染，状态驱动字段
        // 全部来自 ViewModel，不再各自读 SessionHolder。初始值立即发射，覆盖首次渲染。
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.uiState.collect { state -> renderAll(state) }
            }
        }
        ui.post(tick)
    }

    /**
     * 构建一个目的地页面 —— **只含该页专属内容**（AppBar / 链路横幅已提到框架层全局唯一）。
     *
     * 依据：M3 navigation bar「Use navigation for **distinct pages**」。四个目的地分工：
     *  · 状态 = 运动控制实时监测（连接行 + 控制卡片 + 实机状态帧/本地遥测）
     *  · 健康 = 机器人健康诊断（robot.health + 真实外观模型 + 15 舵机状态）
     *  · 设置 = 配置（遥控参数 + BLE + 更新）
     *  · 终端 = SSH 远程控制（SshPanel，主板命令行）
     *
     * 2026-11-15 去重：旧版每页都 addView 一份 buildAppBar + linkBanner，
     * 三页切换时顶部「控制台」卡片和底部「通道」条反复出现，用户反馈重复。
     * 现在全局状态只由 [chrome] 一份承载，页面内容互不重叠。
     */
    private fun buildPage(index: Int): View {
        val page = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        when (index) {
            0 -> page.addView(buildStatePage(), LinearLayout.LayoutParams(MATCH, MATCH))
            1 -> page.addView(buildHealthPage(), LinearLayout.LayoutParams(MATCH, MATCH).also {
                it.topMargin = dp(8)
            })
            2 -> page.addView(buildSettingsPage(), LinearLayout.LayoutParams(MATCH, MATCH).also {
                it.topMargin = dp(8)
            })
            3 -> {
                sshPanel = SshPanel(this, sshRepository)
                page.addView(sshPanel, LinearLayout.LayoutParams(MATCH, MATCH).also {
                    it.topMargin = dp(8)
                })
            }
        }
        return page
    }

    /**
     * 顶部标题区 —— 安静仪表盘（2026-11-20）：
     * 无营销方块 logo、无厚渐变；标题 + 状态行 + pill，底部分隔线。
     * 依据：M3 Expressive「hero 留给关键动作」；standoutmcp 反对模板化品牌块。
     * 标题/状态/chip 字段与刷新逻辑不变（门禁硬串零改动）。
     */
    private fun buildAppBar(chrome: PageChrome) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(4), dp(8), dp(4), dp(10))
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.VERTICAL
                addView(chrome.titleText)
                addView(chrome.statusText.apply { setPadding(0, dp(2), 0, 0) })
            }, LinearLayout.LayoutParams(0, WRAP, 1f))
            addView(chrome.sourceChip)
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        addView(rule(top = 10))
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

    private fun renderLinkBanner(connectError: String, linkStatus: String, linkLevel: Int) {
        val msg = if (connectError.isNotEmpty()) "⚠ 地址无效 · $connectError" else linkStatus
        // 全局唯一一份链路横幅（框架层常驻），任何目的地下断链信息都可见。
        val banner = chrome.linkBanner
        if (msg.isEmpty()) {
            banner.visibility = View.GONE
        } else {
            banner.visibility = View.VISIBLE
            banner.text = msg
            val level = if (connectError.isNotEmpty()) 2 else linkLevel
            // 对齐 HTML .banner：浅底 + 状态色文字/描边，避免实心色块。
            val bad = level >= 2
            banner.setTextColor(c(if (bad) R.color.md_bad else R.color.md_warn))
            banner.background = GradientDrawable().apply {
                setColor(if (bad) Color.argb(38, 0xFF, 0x45, 0x3A) else Color.argb(38, 0xFF, 0xB0, 0x20))
                cornerRadius = dp(CORNER_LARGE_DP).toFloat()
                setStroke(dp(STROKE_HAIRLINE_DP),
                    if (bad) Color.argb(77, 0xFF, 0x45, 0x3A) else Color.argb(77, 0xFF, 0xB0, 0x20))
            }
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
                background = roundedCard(c(R.color.md_surface), CORNER_CELL_DP)
                setPadding(dp(10), dp(8), dp(10), dp(8))
                layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
            }
            addView(hostEdit)
            // 次级按钮：描边而非填充（每屏只留「进入遥控」一个主填充按钮）。
            addView(outlineButton("连接", "连接机器人", ::connectFromUi),
                LinearLayout.LayoutParams(WRAP, WRAP).also { it.marginStart = dp(8) })
        }
        addView(connectionInputRow)
        // ② 摘要行（已连接且未展开时可见）：类型 + 修改入口
        connectionSummary = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            // 去卡片化：已连接摘要只是一行文本 + 次级按钮，不再套整块圆角卡。
            setPadding(dp(2), dp(8), dp(2), dp(8))
            minimumHeight = dp(48)
            visibility = View.GONE
            connectionSummaryText = TextView(this@MainActivity).apply {
                textSize = 13f; setTextColor(c(R.color.md_text))
                layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
            }
            addView(connectionSummaryText)
            addView(outlineButton("修改", "修改连接地址") {
                connectionExpanded = true
                val s = viewModel.uiState.value
                renderConnectionRow(s.kind, s.connectError)
            })
        }
        addView(connectionSummary)
        addView(rule())
        val s = viewModel.uiState.value
        renderConnectionRow(s.kind, s.connectError)
    }

    /** 按连接状态 + 展开标志切换输入行 / 摘要行的可见性。 */
    private fun renderConnectionRow(kind: String, connectError: String) {
        val connected = kind.isNotEmpty() && connectError.isEmpty()
        val showInput = connectionExpanded || !connected
        connectionInputRow.visibility = if (showInput) View.VISIBLE else View.GONE
        connectionSummary.visibility = if (showInput) View.GONE else View.VISIBLE
        if (!showInput) {
            connectionSummaryText.text = "已连接 · $kind"
        }
    }

    /**
     * 控制区 —— M3 Usability「每屏一个主任务」+ Color roles「surfaceContainer 分组」：
     * 整块放在 surfaceContainer 里；模式=分段；**唯一 filled = 进入遥控**（hero）；
     * 休息=outlined 次级，不抢主 CTA。门禁「手动/自动/进入遥控界面」硬串不动。
     */
    private fun buildControlCard() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = roundedCard(c(R.color.md_surface), CORNER_LARGE_DP, stroked = true)
        setPadding(dp(14), dp(14), dp(14), dp(14))
        addView(sectionTitle("控制"))
        val row = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            background = roundedCard(c(R.color.md_card_alt), CORNER_SM_DP, stroked = false)
            setPadding(dp(4), dp(4), dp(4), dp(4))
            layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) }
        }
        modeManual = MaterialButton(this@MainActivity, null,
            com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = "手动模式"; textSize = 13f; minimumHeight = dp(48)
            cornerRadius = dp(CORNER_NAV_DP)
            contentDescription = "手动模式"
            setOnClickListener { switchMode(ControlMode.MANUAL) }
        }
        modeAuto = MaterialButton(this@MainActivity, null,
            com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = "自动模式"; textSize = 13f; minimumHeight = dp(48)
            cornerRadius = dp(CORNER_NAV_DP)
            contentDescription = "自动模式"
            setOnClickListener { switchMode(ControlMode.AUTO) }
        }
        row.addView(modeManual, LinearLayout.LayoutParams(0, WRAP, 1f))
        row.addView(modeAuto, LinearLayout.LayoutParams(0, WRAP, 1f))
        addView(row)
        modeHint = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, dp(8), 0, 0)
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.25f)
        }
        addView(modeHint)
        // M3 Expressive / Usability：主 CTA 是本屏 hero（尺寸与 primary 填充强调）。
        launchButton = MaterialButton(this@MainActivity).apply {
            textSize = 15f; minimumHeight = dp(52)
            cornerRadius = dp(CORNER_LARGE_DP)
            setTextColor(c(R.color.md_on_accent))
            contentDescription = "进入遥控界面"
            layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(14) }
            setOnClickListener { startActivity(Intent(this@MainActivity, DriveActivity::class.java)) }
        }
        addView(launchButton)
        addView(rule(top = 16, bottom = 12))
        addView(sectionTitle("一键休息"))
        val restRow = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(6) }
        }
        restButton = outlineButton("一键休息", "一键休息：让机器人坐下卸力省电", ::confirmRest)
        wakeButton = outlineButton("恢复站立", "恢复站立：结束休息，重新上电回 home 姿态", ::confirmWake)
        restRow.addView(restButton, LinearLayout.LayoutParams(0, WRAP, 1f))
        restRow.addView(wakeButton, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(8) })
        addView(restRow)
        restLimpText = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, dp(8), 0, 0)
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
        }
        addView(restLimpText)
        restResultText = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.2f)
        }
        addView(restResultText)
    }

    /** 常驻回显关节 limp 状态（robot.state.safety.limp）；无帧时不造数。 */
    private fun renderRestLimp(limp: Boolean?) {
        if (!::restLimpText.isInitialized) return
        restLimpText.text = when {
            limp == null -> "关节状态：— 未读到（无状态帧）"
            limp == true -> "关节状态：⚠ 已卸力（休息中）"
            else -> "关节状态：站立（未卸力）"
        }
    }

    /** 一键休息：robot.rest 会让实体机器人坐下卸力 ⇒ 写操作二次确认，绝不静默执行。 */
    private fun confirmRest() {
        if (!viewModel.isSessionReady()) {
            viewModel.onRest()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("一键休息（写操作）")
            .setMessage("将向板端发送 robot.rest（无参）：\n坐下 → 缓入休息姿态 → 卸力 + 舵机重启省电。\n\n" +
                "⚠ BLE 通道下该方法不在放行白名单，会被拒绝（PERMISSION_DENIED=14），失败将如实回显。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认休息") { _, _ -> viewModel.onRest() }
            .show()
    }

    /** 恢复站立：robot.init（rest 的逆操作：上电 + 回 home），同样二次确认。 */
    private fun confirmWake() {
        if (!viewModel.isSessionReady()) {
            viewModel.onWake()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("恢复站立（写操作）")
            .setMessage("将向板端发送 robot.init（无参）：\n重新上电 + 回到 home 站立姿态，结束休息。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认恢复") { _, _ -> viewModel.onWake() }
            .show()
    }

    /**
     * M3 Navigation bar（compact）：3–5 destinations、底栏固定不滚动、
     * 容器用 surfaceContainer；选中态 = primary 圆角指示 pill 衬在图标后
     * （m3.material.io/components/navigation-bar/guidelines）。
     * content-desc 仍为「标签页X」，门禁零改动。
     */
    private fun buildTabRow() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = GradientDrawable().apply {
            setColor(c(R.color.md_surface))
        }
        addView(rule())
        val tabs = listOf(
            "状态" to R.drawable.ic_tab_state,
            "健康" to R.drawable.ic_tab_health,
            "设置" to R.drawable.ic_tab_settings,
            "终端" to R.drawable.ic_tab_terminal,
        )
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(6), 0, dp(4))
            tabs.forEachIndexed { i, (label, iconRes) ->
                val cell = LinearLayout(this@MainActivity).apply {
                    orientation = LinearLayout.VERTICAL
                    gravity = Gravity.CENTER_HORIZONTAL
                    minimumHeight = dp(56)
                    contentDescription = "标签页$label"
                    isClickable = true
                    isFocusable = true
                    setOnClickListener { showPage(i) }
                }
                // 图标叠在选中指示 pill 上（FrameLayout），符合 M3 active indicator。
                val iconWrap = FrameLayout(this@MainActivity).apply {
                    layoutParams = LinearLayout.LayoutParams(dp(64), dp(32))
                }
                val indicator = View(this@MainActivity).apply {
                    layoutParams = FrameLayout.LayoutParams(dp(56), dp(28), Gravity.CENTER)
                    background = roundedCard(Color.TRANSPARENT, 16, stroked = false)
                }
                tabIndicators.add(indicator)
                iconWrap.addView(indicator)
                val icon = ImageView(this@MainActivity).apply {
                    setImageResource(iconRes)
                    imageTintList = ColorStateList.valueOf(c(R.color.md_text_dim))
                    layoutParams = FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER)
                }
                iconWrap.addView(icon)
                cell.addView(iconWrap)
                val tv = TextView(this@MainActivity).apply {
                    text = label
                    textSize = 12f
                    gravity = Gravity.CENTER
                    setTextColor(c(R.color.md_text_dim))
                    setPadding(0, dp(2), 0, 0)
                    layoutParams = LinearLayout.LayoutParams(WRAP, WRAP)
                }
                cell.addView(tv)
                cell.tag = Pair(icon, tv)
                tabButtons.add(cell)
                addView(cell, LinearLayout.LayoutParams(0, WRAP, 1f))
            }
        }, LinearLayout.LayoutParams(MATCH, WRAP))
    }

    /**
     * 状态页 —— 2026-11-19 用户反馈「底部信息还要在那么一小块区域滑动，不合理」。
     *
     * 🔴 根因：旧版把「实机状态 + 遥测」塞进一个 weight=1f 的小 ScrollView，
     * 其余（连接/控制）在滚动区外 —— 形成「页面里套一个滚动小窗」的割裂交互。
     * 一手依据 Android 官方 ScrollView 文档「Never add a scrollable view inside another
     * scroll view」(developer.android.com/reference/android/widget/ScrollView) 与
     * Material scrolling patterns：一个目的地就是**一个连续滚动面**，内容从上到下自然流动。
     *
     * 修法：整页单一 ScrollView，连接 / 控制 / 实机状态 / 遥测依次铺在同一个滚动列里，
     * 不再有内层小滚动窗。门禁首屏断言（手动/自动、进入遥控、实机状态帧）与「遥测需滚动
     * 才可见」的负对照保持不变：遥测组仍位于自然折叠线以下，滚动整页即可读到。
     */
    private fun buildStatePage() = ScrollView(this).apply {
        contentDescription = "状态页：连接、控制与监测数据"
        val col = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(2), dp(6), dp(2), dp(10))
        }
        // M3 Usability：主任务（控制）在前；连接次之；监测只读；本地遥测压到折线下。
        // 门禁：首屏须含手动/自动、进入遥控、实机状态帧；遥测须滚动才见。
        col.addView(buildControlCard(), LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(sectionTitle("连接").also { it.setPadding(0, dp(16), 0, dp(4)) })
        col.addView(buildConnectionRow(), LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(rule(top = 8, bottom = 4))
        // 🔴 标题含门禁硬串「实机状态帧」——写在 stateSourceText，本节不再套冗长副标题。
        stateSourceText = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            letterSpacing = TRACKING_LABEL
            fontFeatureSettings = TABULAR_FIGURES
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setLineSpacing(0f, 1.2f)
            setPadding(0, dp(8), 0, dp(4))
        }
        col.addView(stateSourceText)
        col.addView(metricGrid(2, STATE_LABELS, stateValues),
            LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(sectionTitle("App 本地遥测（非实机数据 · 会话/心跳/输入计数）",
            R.color.md_warn).also { it.setPadding(0, dp(16), 0, dp(4)) })
        col.addView(metricGrid(2, TELEMETRY_LABELS, telemetryValues),
            LinearLayout.LayoutParams(MATCH, WRAP))
        addView(col, FrameLayout.LayoutParams(MATCH, WRAP))
    }

    private fun metricCell(label: String, value: String) = TextView(this).apply {
        gravity = Gravity.TOP
        minimumHeight = dp(68)
        setPadding(dp(16), dp(14), dp(16), dp(14))
        setLineSpacing(0f, 1.1f)
        maxLines = 2; ellipsize = TextUtils.TruncateAt.END
        fontFeatureSettings = TABULAR_FIGURES
        background = roundedCard(c(R.color.md_card), CORNER_CELL_DP, stroked = true)
        setMetric(this, label, value)
    }

    /**
     * 标签保持克制，突出读数。
     * 空态「未读到」降字号降对比，避免整屏被占位字抢眼；文案本身门禁硬串不动。
     */
    private fun setMetric(v: TextView, label: String, value: String) {
        val full = "$label\n$value"
        val sp = SpannableString(full)
        val cut = label.length + 1
        val flags = Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        val empty = value.contains("未读到") || value == "—"
        sp.setSpan(AbsoluteSizeSpan(dp(12)), 0, label.length, flags)
        sp.setSpan(ForegroundColorSpan(c(R.color.md_text_dim)), 0, label.length, flags)
        sp.setSpan(AbsoluteSizeSpan(dp(if (empty) 14 else 16)), cut, full.length, flags)
        sp.setSpan(ForegroundColorSpan(
            c(if (empty) R.color.md_text_dim else R.color.md_text)), cut, full.length, flags)
        if (!empty) sp.setSpan(StyleSpan(Typeface.BOLD), cut, full.length, flags)
        v.text = sp
    }

    /** HTML `.rows`：两列圆角卡片，行列间距均为 12dp，小屏保持两列。 */
    private fun metricGrid(cols: Int, labels: List<String>, sink: MutableList<TextView>) =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val rows = labels.chunked(cols)
            rows.forEachIndexed { rowIdx, chunk ->
                val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
                chunk.forEachIndexed { colIdx, label ->
                    val v = metricCell(label, "— 未读到")
                    sink.add(v)
                    row.addView(v, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                        if (colIdx > 0) it.marginStart = dp(12)
                    })
                }
                repeat(cols - chunk.size) {
                    row.addView(View(this@MainActivity),
                        LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(12) })
                }
                addView(row, LinearLayout.LayoutParams(MATCH, WRAP).also {
                    if (rowIdx > 0) it.topMargin = dp(12)
                })
            }
        }

    private fun divider() = rule(top = 12, bottom = 8)

    /**
     * 1px 分隔线 —— 去卡片化后**替代层层卡边框**建立分组节奏。
     * 一手依据 standoutmcp「Group with whitespace and 1px rules. Cards only for real elevation」
     * 与 skillcraft「Borders > shadows」；颜色取 M3 `outlineVariant` 语义角色。
     */
    private fun rule(top: Int = 0, bottom: Int = 0) = View(this).apply {
        setBackgroundColor(c(R.color.md_outline_variant))
        layoutParams = LinearLayout.LayoutParams(MATCH, dp(STROKE_HAIRLINE_DP)).also {
            it.topMargin = dp(top)
            it.bottomMargin = dp(bottom)
        }
    }

    /**
     * 次级按钮用 MDC **官方 outlined 样式**：1px 描边 + 文字色，不做填充块。
     * 每屏只保留一个填充主按钮（进入遥控），解决旧版「6 个填充按钮抢同一层级」。
     */
    private fun outlineButton(label: String, desc: String, onClick: () -> Unit) =
        MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = label
            textSize = 12f
            minimumHeight = dp(44)
            cornerRadius = dp(CORNER_CELL_DP)
            contentDescription = desc
            strokeWidth = dp(STROKE_HAIRLINE_DP)
            strokeColor = ColorStateList.valueOf(c(R.color.md_outline))
            setTextColor(c(R.color.md_text))
            setOnClickListener { onClick() }
        }

    /**
     * M3 filled button：每屏只给一个主操作（连接/扫描/确认），其余保持描边或文字按钮。
     * 依据 M3 Buttons「Filled buttons have the highest emphasis」与 Android Settings
     * 「primary action only」：一屏多个同权重描边按钮正是「看起来杂乱」的主因。
     */
    private fun primaryButton(label: String, desc: String, onClick: () -> Unit) =
        MaterialButton(this, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = label
            textSize = 13f
            minimumHeight = dp(48)
            cornerRadius = dp(CORNER_CELL_DP)
            contentDescription = desc
            strokeWidth = 0
            backgroundTintList = ColorStateList.valueOf(c(R.color.md_accent))
            setTextColor(c(R.color.md_on_accent))
            setTypeface(null, Typeface.BOLD)
            setOnClickListener { onClick() }
        }

    /**
     * 分段：选中 = 白底黑字（对齐 HTML .seg span.on）；未选中 = 透明 + dim。
     * 门禁「手动模式/自动模式」文案 / content-desc 不动。
     */
    private fun styleSegment(b: MaterialButton, selected: Boolean, accent: Int) {
        b.strokeWidth = 0
        b.backgroundTintList = ColorStateList.valueOf(
            if (selected) Color.WHITE else Color.TRANSPARENT)
        b.setTextColor(if (selected) c(R.color.md_bg) else c(R.color.md_text_dim))
        b.setTypeface(null, if (selected) Typeface.BOLD else Typeface.NORMAL)
    }

    /**
     * 分区标题：小字 + 字距，无彩条（Oura domain label 安静；彩条易显模板）。
     * 文本原样保留（门禁硬串）。
     */
    private fun sectionTitle(label: String, colorRes: Int = R.color.md_text_dim) =
        TextView(this).apply {
            text = label
            textSize = 11f
            setTextColor(c(colorRes))
            setTypeface(null, Typeface.BOLD)
            letterSpacing = 0.06f
            setPadding(0, dp(10), 0, dp(4))
        }

    /** 健康页：robot.health 字段 + 3D 模型 + 15 舵机 + 只读诊断。
     *  2026-11-19 去卡片化：外层大卡撤掉，页内改分区标题 + 1px 分隔线；
     *  顶部两行门禁断言文本（healthSourceText / robot.health 声明）位置保持不变。 */
    private fun buildHealthPage() = ScrollView(this).apply {
        isFillViewport = true
        val col = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(2), dp(6), dp(2), dp(4))
        }
        healthSourceText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_warn))
        }
        col.addView(healthSourceText)
        col.addView(TextView(this@MainActivity).apply {
            text = "robot.health 真字段：缺失=未读到"
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, 0, 0, dp(6))
        })
        // ── 2026-11-15 硬件监控：真实外观网格（Cream 官方配色）+ 15 舵机状态点 ──
        // 顶部两行断言文本（healthSourceText / 上面这行）刻意保持在最前，
        // 真机门禁 uiautomator 只 dump 视口内节点，插到它们前面会把断言挤红。
        // 🔴 「模型区域被文字遮挡」修复：声明/图例从 Canvas drawText 移到卡片外的
        // 独立 TextView；DuckModelView 现在只画几何，模型可用全高（净绘图区 +8%）。
        // 11-20 照 HTML `.model-container`：模型套渐变圆角底座（视觉锚点）。
        // DuckModelView 只画几何，容器负责渐变背景/圆角，模型可用全高不变。
        duckModelView = DuckModelView(this@MainActivity).apply {
            layoutParams = FrameLayout.LayoutParams(MATCH, MATCH)
        }
        col.addView(modelContainer(duckModelView, 216).also {
            it.layoutParams = LinearLayout.LayoutParams(MATCH, dp(216)).also { lp ->
                lp.topMargin = dp(6)
            }
        })
        col.addView(TextView(this@MainActivity).apply {
            text = "拖动旋转模型"
            textSize = 10f; setTextColor(c(R.color.md_text_dim))
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(2), 0, dp(2))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        // ── 11-20 照 HTML 健康页：模型之后直接进「硬件状态」三组 .grp（颈/左/右）──
        col.addView(sectionTitle("硬件状态 · robot.health 字段").apply {
            setPadding(0, dp(10), 0, dp(8))
        })
        col.addView(buildPartGroups(), LinearLayout.LayoutParams(MATCH, WRAP))
        // 5 项子系统状态卡（电量/主板/舵机温度/总线/IMU）——本项目真实数据，保留在分组徽章之后。
        col.addView(View(this@MainActivity).apply { layoutParams = LinearLayout.LayoutParams(MATCH, dp(12)) })
        col.addView(buildHealthCards(), LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(2)
        })
        // 15 舵机逐点状态网格：聚合温度在「舵机温度」行，逐点缺失/在线状态在此网格。
        servoGridCard = buildServoGrid()
        col.addView(servoGridCard, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(10)
        })
        // ── ToF 8×8 深度网格（头部测距雷达 · tof.frame）──
        col.addView(rule(top = 12))
        col.addView(sectionTitle("头部 ToF · 8×8 深度（tof.frame）"))
        tofSourceText = TextView(this@MainActivity).apply {
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            setPadding(0, 0, 0, dp(6))
        }
        col.addView(tofSourceText)
        col.addView(buildTofGrid(), LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(TextView(this@MainActivity).apply {
            text = "近暖远冷 · <10cm 不可信"
            textSize = 10f; setTextColor(c(R.color.md_text_dim))
            maxLines = 2; setLineSpacing(0f, 1.15f)
            setPadding(0, dp(4), 0, dp(2))
        })
        // 11-20 参照设计稿 .legend：近[渐变bar]远，渐变色带直观解读 8×8 网格颜色。
        col.addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(4))
            addView(TextView(this@MainActivity).apply {
                text = "近"; textSize = 10f; setTextColor(c(R.color.md_text_dim))
            }, LinearLayout.LayoutParams(WRAP, WRAP))
            addView(View(this@MainActivity).apply {
                val near = Color.parseColor("#FF453A")
                val mid = Color.parseColor("#FFB020")
                val farBlue = Color.parseColor("#4A8BFF")
                val dark = Color.parseColor("#2E4A57")
                background = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                    intArrayOf(near, mid, farBlue, dark)).apply { cornerRadius = dp(4).toFloat() }
            }, LinearLayout.LayoutParams(0, dp(8), 1f).also {
                it.marginStart = dp(8); it.marginEnd = dp(8)
            })
            addView(TextView(this@MainActivity).apply {
                text = "远"; textSize = 10f; setTextColor(c(R.color.md_text_dim))
            }, LinearLayout.LayoutParams(WRAP, WRAP))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        monitorAlertText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_text))
            setPadding(0, dp(4), 0, dp(4)); maxLines = 6
        }
        col.addView(monitorAlertText)
        val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(outlineButton("刷新", "刷新健康数据", ::refreshHealth),
            LinearLayout.LayoutParams(WRAP, WRAP))
        autoRefreshBox = CheckBox(this@MainActivity).apply {
            text = "每秒自动刷新"; minimumHeight = dp(48)
            setTextColor(c(R.color.md_text_dim))
            setOnCheckedChangeListener { _, checked ->
                viewModel.onSetAutoRefreshHealth(checked)
                persist()
            }
        }
        row.addView(autoRefreshBox)
        col.addView(row)
        healthText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_text_dim))
            setTypeface(Typeface.MONOSPACE); setPadding(0, dp(8), 0, dp(8))
            maxLines = 30
        }
        // 原始读数（调试用）直接铺在末尾，不再单独套 ScrollView —— 避免嵌套滚动。
        col.addView(healthText, LinearLayout.LayoutParams(MATCH, WRAP))
        // ── A3/A6/A7 只读诊断区（系统信息/服务/日志、策略/模型、更新状态）──
        // 放在健康页视口下方：顶部两行门禁断言文本（healthSourceText 等）不受影响；
        // 需主动点「刷新系统信息」才查（真 TCP/BLE 同步 I/O，ViewModel 已切后台线程）。
        col.addView(TextView(this@MainActivity).apply {
            text = "系统诊断 · 只读"
            textSize = 11f; setTextColor(c(R.color.md_accent))
            setPadding(0, dp(10), 0, dp(2))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        diagnosticsText = TextView(this@MainActivity).apply {
            text = "尚未查询"
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setTypeface(Typeface.MONOSPACE)
            setPadding(0, dp(4), 0, dp(4)); maxLines = 40
            contentDescription = "系统诊断只读信息"
        }
        col.addView(diagnosticsText, LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(outlineButton("刷新系统信息", "刷新系统信息") {
            viewModel.onRefreshDiagnostics()
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        // 🔴 整页可滚动：模型放大后「15 舵机网格」第 3 行（ID 10–14 右腿）会被挤出视口，
        // 用户 2026-11-15 反馈「只有 20 到 34」。外层 ScrollView 保证 15 个 ID 都能滚到。
        // 顶部两行断言文本仍在最前，真机门禁 uiautomator dump 视口内节点不受影响。
        addView(col, FrameLayout.LayoutParams(MATCH, WRAP))
    }

    /**
     * 5 张状态卡片（2 列：2+2+1）：电量 / 主板 / 舵机温度 / 总线 / IMU。
     * 每张卡片 = 状态色点 + 标题 + 数值；数值来自 [HealthSnapshot]，色点来自
     * [MonitorReport.severityOf]（没证据一律灰，绝不默认绿）。
     *
     * ── 控制环为什么不在此页 ──
     * 控制环频率是**运动状态**指标（robot.state 的 `loopHz`），已完整呈现在「状态」页。
     * 健康页专注**硬件健康**（电池/主板/舵机/总线/IMU），避免与状态页重复呈现同一量。
     */
    private fun buildHealthCards() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val labels = listOf("电量", "主板状态", "舵机温度", "总线/舵机", "IMU")
        val rows = labels.chunked(2)
        rows.forEachIndexed { rowIdx, chunk ->
            val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEachIndexed { i, label ->
                val card = healthCard(label)
                row.addView(card, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                    if (i > 0) it.marginStart = dp(12)
                })
            }
            addView(row, LinearLayout.LayoutParams(MATCH, WRAP))
            if (rowIdx < rows.size - 1) {
                addView(View(this@MainActivity).apply {
                    layoutParams = LinearLayout.LayoutParams(MATCH, dp(10))
                })
            }
        }
    }

    /** 健康读数行：色点 + 标题 + 数值；ruled 浅底，非 20dp 浮卡。 */
    private fun healthCard(label: String) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = roundedCard(c(R.color.md_surface), CORNER_CELL_DP, stroked = true)
        setPadding(dp(12), dp(12), dp(12), dp(12))
        val head = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
        head.gravity = Gravity.CENTER_VERTICAL
        val dot = View(this@MainActivity).apply {
            val s = dp(8); layoutParams = LinearLayout.LayoutParams(s, s).also {
                it.marginEnd = dp(6); it.gravity = Gravity.CENTER_VERTICAL
            }
            background = roundedCard(c(R.color.md_text_dim), s / 2)
        }
        head.addView(dot)
        head.addView(TextView(this@MainActivity).apply {
            text = label; textSize = 11f; setTextColor(c(R.color.md_text_dim))
        })
        addView(head)
        val v = TextView(this@MainActivity).apply {
            textSize = 16f; setTextColor(c(R.color.md_text))
            setTypeface(null, Typeface.BOLD); setPadding(0, dp(4), 0, 0)
            maxLines = 2; ellipsize = TextUtils.TruncateAt.END
            fontFeatureSettings = TABULAR_FIGURES
            text = "— 未读到"
        }
        addView(v)
        healthCardVals.add(v)
        healthCardDots.add(dot)
    }

    /**
     * 15 舵机逐点状态网格（5 列 × 3 行）。
     *
     * ── 协议边界（为什么不是逐舵机温度）──
     * `ft1910/duck-ipc-proto` 的 `HealthResult` 对舵机只给**聚合温度**
     * （`motors.hottest/max_c/mean_c`），底层 `slow.temps_c: [f64; 15]` 在 robotd
     * 被 fold 成 3 个标量后丢弃，逐舵机温度当前**不可得**。但 `bus.missing`
     * （`missingIds`）能**逐一点名**哪些舵机 ID 总线没读到 —— 这是真实可得的逐舵机数据。
     *
     * 每格状态色点语义（core 单一真源 [RobotParts.severityArgb]，没证据一律灰）：
     *  - ID ∈ missingIds → CRITICAL 红（总线缺失，一手点名）
     *  - ID ∉ missingIds 且 missing 字段已返回 → OK 绿（总线在线）
     *  - missing 字段未返回 → UNKNOWN 灰（没数据，不猜、不默认绿）
     * 温度列只显示聚合 maxC（协议只提供这个），不造逐舵机温度。
     */
    /**
     * ToF 8×8 深度网格：64 格 TextView（row-major），每格显示距离米数。
     * 三态着色在 [renderToF]：Range 近暖远冷 / NoTarget 暗格 / Unusable 告警格。
     * 无帧时全部显示「·」+ 暗格，绝不默认绿或填 0（UNVERIFIED != PASS）。
     */
    private fun buildTofGrid() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        tofCells.clear()
        val grid = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            background = roundedCard(c(R.color.md_surface), CORNER_CELL_DP, stroked = true)
            setPadding(dp(4), dp(4), dp(4), dp(4))
        }
        for (r in 0 until TofSnapshot.ROWS) {
            val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            for (col in 0 until TofSnapshot.COLS) {
                val cell = TextView(this@MainActivity).apply {
                    text = "·"; textSize = 10f; gravity = Gravity.CENTER
                    setTextColor(c(R.color.md_text_dim))
                    minHeight = dp(26)
                    background = roundedCard(c(R.color.md_outline_variant), 4, stroked = false)
                    fontFeatureSettings = TABULAR_FIGURES
                }
                tofCells.add(cell)
                row.addView(cell, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                    if (col > 0) it.marginStart = dp(2)
                })
            }
            grid.addView(row, LinearLayout.LayoutParams(MATCH, WRAP).also {
                if (r > 0) it.topMargin = dp(2)
            })
        }
        addView(grid, LinearLayout.LayoutParams(MATCH, WRAP))
    }

    /**
     * 把 ToF 帧填进 8×8 网格。只写文本变化，避免 1s tick 连发 AccessibilityEvent。
     * 三态判据完全复用 core [TofSnapshot.zone]（status 决定含义），UI 不重造阈值。
     */
    private fun renderToF(state: MainViewModel.UiState) {
        if (!::tofSourceText.isInitialized || tofCells.size != TofSnapshot.ZONES) return
        val snap = state.tof
        tofSourceText.text = when {
            snap == null -> "未读到 ToF 帧 · 真机需 mediad WebRTC 链路（btd 拒绝 tof.stream）"
            state.kind == "MOCK" -> "⚠ Mock 演示夹具 · 非实机 · 第 ${snap.seq ?: "?"} 帧 · 有效 ${snap.validCount}/64"
            else -> "实机 tof.frame · 第 ${snap.seq ?: "?"} 帧 · 有效 ${snap.validCount}/64"
        }
        tofSourceText.setTextColor(c(if (snap != null && state.kind == "MOCK") R.color.md_warn
            else if (snap != null) R.color.md_accent else R.color.md_text_dim))
        val zones = snap?.zones
        for (i in 0 until TofSnapshot.ZONES) {
            val cell = tofCells[i]
            val z = zones?.getOrNull(i)
            val (txt, col) = when (z) {
                is TofZone.Range -> {
                    // 近=暖(ok/warn) 远=冷(accent)，纯定性色阶，具体距离写在格内
                    val m = z.meters
                    val color = if (m < 0.3) R.color.md_bad else if (m < 0.7) R.color.md_warn else R.color.md_accent
                    "%.2f".format(m) to color
                }
                TofZone.NoTarget -> "·" to R.color.md_outline
                is TofZone.Unusable -> "!" to R.color.md_bad
                null -> "·" to R.color.md_outline_variant
            }
            cell.setTextIfChanged(txt)
            cell.setTextColor(c(col))
        }
    }

    /**
     * 三组「部位整体健康度」徽章 —— 照 HTML 健康页 `.grp`（模型之后、硬件状态区）。
     *
     * 🔴 展示顺序 vs 存储顺序解耦（2026-11-20 重构，务必保持）：
     *  - **展示**：HTML 稿顺序 = 颈·头·喙 / 左腿 / 右腿 ⇒ [DISPLAY_ORDER] = [1,0,2]。
     *  - **存储**：[partBadges] 索引必须严格对齐 RobotParts.JOINT_IDS =
     *    [左腿20–24, 颈头喙30–34, 右腿10–14]（各 5 个），因为 [updateServoGrid]
     *    用 `ids.drop(g*5).take(5)` 派生每组缺失数。故先按索引建 badge 再按展示顺序 addView。
     *  - 结果：用户看到的顺序贴稿，数据派生链一字未改，不造数。
     */
    private fun buildPartGroups() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val groupNames = listOf("左腿 20–24", "颈·头·喙 30–34", "右腿 10–14")
        val displayOrder = listOf(1, 0, 2)   // HTML：颈头喙 / 左腿 / 右腿；索引仍按 JOINT_IDS
        val badges = arrayOfNulls<TextView>(groupNames.size)
        val groups = arrayOfNulls<View>(groupNames.size)
        groupNames.forEachIndexed { gi, gname ->
            val badge = TextView(this@MainActivity).apply {
                text = "— 未读到"; textSize = 12f
                setTypeface(null, Typeface.BOLD)
                setTextColor(c(R.color.md_text_dim))
                fontFeatureSettings = TABULAR_FIGURES
            }
            badges[gi] = badge
            groups[gi] = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(12), dp(12), dp(12), dp(12))
                background = roundedCard(c(R.color.md_surface), CORNER_CELL_DP, stroked = true)
                addView(TextView(this@MainActivity).apply {
                    text = gname; textSize = 13f
                    setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
                }, LinearLayout.LayoutParams(0, WRAP, 1f))
                addView(badge, LinearLayout.LayoutParams(WRAP, WRAP))
            }
        }
        partBadges.addAll(badges.map { it!! })   // 存储顺序 = JOINT_IDS，供 updateServoGrid 派生
        displayOrder.forEachIndexed { pos, gi ->
            addView(groups[gi]!!, LinearLayout.LayoutParams(MATCH, WRAP).also {
                it.topMargin = if (pos == 0) 0 else dp(10)
            })
        }
    }

    private fun buildServoGrid() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(2), dp(6), dp(2), dp(4))
        val col = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(8), 0, 0)
        }
        col.addView(TextView(this@MainActivity).apply {
            text = "15 舵机状态"
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, 0, 0, dp(6))
        })
        val grid = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        val cols = 5
        val parts = RobotParts.JOINT_PARTS
        val ids = RobotParts.JOINT_IDS
        // 三组标题仍按 JOINT_IDS 顺序（左腿/颈头喙/右腿），与逐点网格 chunk 一一对应。
        val groupNames = listOf("左腿 20–24", "颈·头·喙 30–34", "右腿 10–14")
        parts.chunked(cols).forEachIndexed { groupIdx, chunk ->
            grid.addView(TextView(this@MainActivity).apply {
                text = groupNames.getOrElse(groupIdx) { "第 ${groupIdx + 1} 组" }
                textSize = 9.5f; setTextColor(c(R.color.md_text_dim))
                setPadding(0, if (groupIdx == 0) 0 else dp(6), 0, dp(2))
            }, LinearLayout.LayoutParams(MATCH, WRAP))
            val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEachIndexed { i, part ->
                val idx = parts.indexOf(part)
                val cell = servoCell(part, ids[idx])
                row.addView(cell, LinearLayout.LayoutParams(0, WRAP, 1f).also {
                    if (i > 0) it.marginStart = dp(6)
                })
            }
            grid.addView(row, LinearLayout.LayoutParams(MATCH, WRAP))
        }
        col.addView(grid)
        addView(col)
    }

    /** 单个舵机格：状态色点 + 舵机 ID + 关节名。色点先置灰（没证据），刷新时才改色。
     *  去卡片化：无圆角小卡背景（updateServoGrid 依赖 getChildAt(0/1/2)，子节点数不变）。 */
    private fun servoCell(part: RobotPart, id: Int) = LinearLayout(this@MainActivity).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(4), dp(6), dp(4), dp(6))
        val dot = View(this@MainActivity).apply {
            val s = dp(7); layoutParams = LinearLayout.LayoutParams(s, s)
            background = roundedCard(c(R.color.md_text_dim), s / 2)
        }
        addView(dot)
        val idTv = TextView(this@MainActivity).apply {
            text = id.toString(); textSize = 11f
            setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(2), 0, 0)
        }
        addView(idTv)
        val nameTv = TextView(this@MainActivity).apply {
            text = part.label; textSize = 8.5f
            setTextColor(c(R.color.md_text_dim)); setPadding(0, 0, 0, 0)
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
        }
        addView(nameTv)
        servoCells.add(this)
        // 存色点引用：用 tag 挂在 cell 上，刷新时取
        tag = dot
    }

    /** 把一手读数填进 15 舵机网格。只改变化才写，避免 1s tick 持续发无障碍事件。 */
    private fun updateServoGrid(snap: HealthSnapshot?) {
        val missing = snap?.missingIds ?: emptyList()
        val missingPresent = snap?.missingFieldPresent ?: false
        for (cell in servoCells) {
            val dot = cell.tag as View
            val idTv = cell.getChildAt(1) as TextView
            val nameTv = cell.getChildAt(2) as TextView
            val id = idTv.text.toString().toIntOrNull() ?: continue
            val sev = when {
                id in missing -> Severity.CRITICAL
                missingPresent -> Severity.OK
                else -> Severity.UNKNOWN
            }
            val color = RobotParts.severityArgb(sev)
            dot.background = roundedCard(color, dp(4))
            // 温度列：协议只给聚合 maxC，不造逐舵机温度，故不在此格显示温度
            nameTv.setTextColor(if (sev == Severity.UNKNOWN) c(R.color.md_text_dim) else color)
        }
        // 11-20 三组整体徽章：组内缺失数>0=警告、missing 字段读到且无缺失=良好、否则未读到。
        // 严格从 missingIds 派生（JOINT_IDS 顺序：左腿/颈头喙/右腿，各 5 个）。
        val ids = RobotParts.JOINT_IDS
        for (g in partBadges.indices) {
            val groupIds = ids.drop(g * 5).take(5)
            val missCount = groupIds.count { it in missing }
            val (text, tone) = when {
                !missingPresent -> "— 未读到" to R.color.md_text_dim
                missCount > 0 -> "▲ 警告 $missCount" to R.color.md_warn
                else -> "● 良好" to R.color.md_ok
            }
            if (partBadges[g].text != text) {
                partBadges[g].text = text
                partBadges[g].setTextColor(c(tone))
            }
        }
    }

    /** 把一手读数 + 监控报告填进 6 张卡片。只改变化才写（避免 1s tick 持续发无障碍事件）。 */
    private fun updateHealthCards(snap: HealthSnapshot?, r: MonitorReport) {
        val busVal = when {
            snap == null -> "— 未读到"
            snap.missingIds.isNotEmpty() -> "缺失 ${snap.missingIds.size}/15"
            snap.missingFieldPresent -> "已读到 · 无缺失"
            else -> "字段未返回"
        }
        val imuVal = when (snap?.imuReady) {
            true -> "就绪"; false -> "未就绪"; null -> "— 未读到"; else -> "—"
        }
        val boardVal = snap?.let { if (it.degraded) "DEGRADED" else "HEALTHY" } ?: "— 未读到"
        val items = listOf(
            (snap?.batteryText() ?: "— 未读到") to r.severityOf(RobotPart.BATTERY),
            boardVal to r.severityOf(RobotPart.TORSO),
            (snap?.maxC?.let { "%.1f°C".format(it) } ?: "— 未读到") to motorSev(snap),
            busVal to r.severityOf(RobotPart.BUS),
            imuVal to r.severityOf(RobotPart.IMU),
        )
        for (i in healthCardVals.indices) {
            val (value, sev) = items.getOrNull(i) ?: ("— 未读到" to Severity.UNKNOWN)
            val color = RobotParts.severityArgb(sev)
            healthCardVals[i].setTextIfChanged(value)
            healthCardVals[i].setTextColor(if (sev == Severity.UNKNOWN) c(R.color.md_text_dim) else color)
            healthCardDots[i].background = roundedCard(color, dp(4))
        }
    }

    /** 舵机温度色点：复用 HardwareMonitor 的同组阈值常量（本地显示阈值，非固件判定）。 */
    private fun motorSev(snap: HealthSnapshot?): Severity {
        val maxC = snap?.maxC ?: return Severity.UNKNOWN
        return when {
            maxC >= HwThresholds.SERVO_CRITICAL_C -> Severity.CRITICAL
            maxC >= HwThresholds.SERVO_WARN_C -> Severity.WARN
            else -> Severity.OK
        }
    }

    /**
     * A2 Wi-Fi 配网卡片（设置页）。
     *
     * 2026-11-21：板载 btd 已刷 Noise 会话版，原 §8.1 阻塞由固件端关闭；
     * 传输说明改为 [NetProvisioning.SECURE_TRANSPORT_NOTICE]，连接仍是写操作、仍二次确认，
     * 但不再把已关闭的历史风险显示成当前告警。Mock 会话不写真网络（Repository 隔离）。
     *
     * 2026-11-20 IA（docs/active/…连接配网UI设计依据）：
     * 标题 → 紧凑状态 → Banner → 刷新 → 两行网络列表 → Outlined 输入 → 写操作。
     * PLAINTEXT 常量已随 11-21 刷板替换为 SECURE_TRANSPORT_NOTICE；「Wi-Fi 配网」标题零改字。
     */
    private fun buildNetPanel() = LinearLayout(this@MainActivity).apply {
        orientation = LinearLayout.VERTICAL
        // M3 设置模式：标题 + 状态常驻；长说明按需展开，不占首屏。
        var noticeExpanded = false
        val noticeView = TextView(this@MainActivity).apply {
            text = "ⓘ " + NetProvisioning.SECURE_TRANSPORT_NOTICE
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(dp(12), dp(10), dp(12), dp(10))
            background = GradientDrawable().apply {
                setColor(Color.argb(30, 0x4A, 0x8B, 0xFF))
                cornerRadius = dp(CORNER_LARGE_DP).toFloat()
                setStroke(dp(1), Color.argb(70, 0x4A, 0x8B, 0xFF))
            }
            visibility = View.GONE
        }
        var noticeBtn: MaterialButton? = null
        val noticeButton = outlineButton("传输说明", "查看传输说明") {
            noticeExpanded = !noticeExpanded
            noticeView.visibility = if (noticeExpanded) View.VISIBLE else View.GONE
            noticeBtn?.text = if (noticeExpanded) "收起" else "传输说明"
        }
        noticeBtn = noticeButton
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(TextView(this@MainActivity).apply {
                text = "Wi-Fi 配网"
                textSize = 14f; setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
            }, LinearLayout.LayoutParams(0, WRAP, 1f))
            addView(noticeButton)
        })
        addView(noticeView, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(6) })
        netStatusText = TextView(this@MainActivity).apply {
            text = "尚未查询"
            textSize = 12f; setTextColor(c(R.color.md_text_dim))
        }
        addView(netStatusText, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(6); it.bottomMargin = dp(8)
        })

        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(outlineButton("刷新", "刷新网络状态") {
                viewModel.onRefreshNet()
            }, LinearLayout.LayoutParams(0, WRAP, 1f))
            addView(outlineButton("取手机网络", "读取手机当前 Wi-Fi 名称") {
                loadPhoneSsid(requestIfNeeded = true)
            }, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(8) })
        }, LinearLayout.LayoutParams(MATCH, WRAP))

        // net.scan → 可点选列表（configd nm.rs:567：从扫描结果选比手录更稳）。
        addView(TextView(this@MainActivity).apply {
            text = "附近网络"
            textSize = 12f; setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(14), 0, dp(2))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        netScanList = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
        }
        addView(netScanList, LinearLayout.LayoutParams(MATCH, WRAP))

        // M3 Outlined Dense 输入（与驾驶通道下拉同族）。
        val ssidField = LayoutInflater.from(this@MainActivity)
            .inflate(R.layout.widget_outlined_field, this, false) as TextInputLayout
        ssidField.hint = "SSID"
        netSsidEdit = ssidField.findViewById(R.id.field_input)
        netSsidEdit.inputType = InputType.TYPE_CLASS_TEXT
        netSsidEdit.contentDescription = "网络名称输入"
        addView(ssidField, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(10) })

        val pskField = LayoutInflater.from(this@MainActivity)
            .inflate(R.layout.widget_outlined_field, this, false) as TextInputLayout
        pskField.hint = "密码（可空）"
        netPskEdit = pskField.findViewById(R.id.field_input)
        netPskEdit.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        netPskEdit.contentDescription = "Wi-Fi 密码输入"
        addView(pskField, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) })

        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(primaryButton("连接网络", "连接 Wi-Fi", ::confirmConnectWifi),
                LinearLayout.LayoutParams(0, WRAP, 1f))
            addView(outlineButton("忘记网络", "忘记 Wi-Fi 网络") {
                val ssid = netSsidEdit.text.toString().trim()
                if (ssid.isEmpty()) {
                    netResultText.setTextIfChanged("请先填写要忘记的网络名称（SSID）")
                } else confirmForgetWifi(ssid)
            }, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(8) })
        }, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(10) })

        netResultText = TextView(this@MainActivity).apply {
            text = "—"; textSize = 11f; setTextColor(c(R.color.md_text_dim))
            contentDescription = "配网操作结果"
        }
        addView(netResultText, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(6) })
        // 自动取手机当前网络：只填 SSID，手动输入永不覆盖；权限不足时弹一次说明。
        post { loadPhoneSsid(requestIfNeeded = true) }
    }

    /** 连接 Wi-Fi 前的二次确认：展示 Noise 传输说明，用户确认后才发写请求。 */
    private fun confirmConnectWifi() {
        val ssid = netSsidEdit.text.toString().trim()
        if (ssid.isEmpty()) {
            netResultText.setTextIfChanged("请先填写网络名称（SSID）")
            return
        }
        // 读密码到局部变量，确认回调后立即用；不写任何字段/日志。
        val psk = netPskEdit.text.toString().ifEmpty { null }
        AlertDialog.Builder(this)
            .setTitle("连接 Wi-Fi（写操作）")
            .setMessage("目标网络：$ssid\n密码只在 Noise 会话中发送。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认连接") { _, _ -> viewModel.onConnectWifi(ssid, psk) }
            .show()
    }

    /** 忘记网络二次确认（写操作）。 */
    private fun confirmForgetWifi(ssid: String) {
        AlertDialog.Builder(this)
            .setTitle("忘记网络（写操作）")
            .setMessage("将删除板端已存网络「$ssid」。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认忘记") { _, _ -> viewModel.onForgetWifi(ssid) }
            .show()
    }

    /**
     * 设置页整体重做（2026-11-20）—— 对照
     * [Android Settings](https://developer.android.com/design/ui/mobile/guides/patterns/settings)：
     * list + 分组标题/supporting、组用视觉 containment、滑块行 primary label + 右侧 status、
     * 标签不复读 section 词、常用项靠前。
     * 结构：① 遥控参数 → ② 速度与死区 → ③ 连接 → ④ 关于。
     * 门禁：`已本地持久化` + `方向摇杆死区` 同处首屏；BLE/扫描硬串由子面板保留。
     */
    private fun buildSettingsPage() = ScrollView(this).apply {
        val col = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(4), dp(2), dp(4), dp(20))
        }

        // ── ① 遥控参数 ──
        // 🔴 supporting 含门禁硬串「已本地持久化」，不可改写。
        col.addView(settingsSectionHeader(
            "遥控参数",
            "已本地持久化",
            first = true,
        ))
        val driveGroup = settingsGroup()
        val (channelView, channelInput) =
            buildDropdown(driveGroup, "驾驶通道", CHANNEL_ITEMS, SessionHolder.channelIndex) { pos ->
                SessionHolder.channelIndex = pos
                persist()
            }
        channelDropdown = channelInput
        driveGroup.addView(channelView, LinearLayout.LayoutParams(MATCH, WRAP))
        val (headRadView, headRadInput) = buildDropdown(driveGroup, "头部幅度", HEAD_RAD_ITEMS,
            SessionHolder.headRadIndex) { pos ->
            SessionHolder.headRadIndex = pos
            persist()
        }
        headRadDropdown = headRadInput
        driveGroup.addView(headRadView, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(10)
        })
        invertBox = CheckBox(this@MainActivity).apply {
            text = "反转前后"
            textSize = 14f; minimumHeight = dp(48)
            setTextColor(c(R.color.md_text))
            isChecked = SessionHolder.invertY
            setOnCheckedChangeListener { _, checked -> SessionHolder.invertY = checked; persist() }
        }
        driveGroup.addView(invertBox, LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(6)
        })
        col.addView(driveGroup, LinearLayout.LayoutParams(MATCH, WRAP))

        // ── ② 速度与死区（首屏须含「方向摇杆死区」）──
        col.addView(settingsSectionHeader("速度与死区"))
        vxLabel = TextView(this@MainActivity)
        yawLabel = TextView(this@MainActivity)
        driveDzLabel = TextView(this@MainActivity)
        headDzLabel = TextView(this@MainActivity)
        vxBar = SeekBar(this@MainActivity).apply {
            max = 80; progress = (SessionHolder.maxVx * 100).toInt()
        }
        yawBar = SeekBar(this@MainActivity).apply {
            max = 250; progress = (SessionHolder.maxVyaw * 100).toInt()
        }
        driveDzBar = SeekBar(this@MainActivity).apply {
            max = 30; progress = (SessionHolder.driveDeadzone * 100).toInt()
        }
        headDzBar = SeekBar(this@MainActivity).apply {
            max = 30; progress = (SessionHolder.headDeadzone * 100).toInt()
        }
        val sliderGroup = settingsGroup()
        // 组内用间距节奏，不用每条 1px 线（官方：Group with whitespace，避免三明治线）。
        sliderGroup.addView(settingSliderRow("前进上限", "m/s", vxLabel, vxBar, false))
        sliderGroup.addView(settingSliderRow("转向上限", "rad/s", yawLabel, yawBar, false))
        sliderGroup.addView(settingSliderRow("方向摇杆死区", "", driveDzLabel, driveDzBar, false))
        sliderGroup.addView(settingSliderRow("头部摇杆死区", "", headDzLabel, headDzBar, false))
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
        listOf(vxBar, yawBar, driveDzBar, headDzBar).forEach { it.setOnSeekBarChangeListener(listener) }
        sliderGroup.addView(outlineButton("恢复默认设置", "恢复默认设置") {
            SettingsStore.reset(applicationContext)
            restoreSettingsUi()
            updateSettingLabels()
            viewModel.onResetDriveParams()
        }, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(8) })
        col.addView(sliderGroup, LinearLayout.LayoutParams(MATCH, WRAP))
        updateSettingLabels()

        // ── ③ 连接（子面板自带「BLE 连接 / Wi-Fi 配网」，外层只写分组名）──
        col.addView(settingsSectionHeader("连接", "BLE → Wi-Fi"))
        col.addView(settingsGroup().also { g ->
            g.addView(blePanel.buildView(), LinearLayout.LayoutParams(MATCH, WRAP))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(settingsGroup().also { g ->
            g.addView(buildNetPanel(), LinearLayout.LayoutParams(MATCH, WRAP))
        }, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(10) })

        // ── ④ 固件与 App 更新 ──
        col.addView(settingsSectionHeader("更新", "检查更新"))
        col.addView(settingsGroup().also { g ->
            g.addView(firmwarePanel.view, LinearLayout.LayoutParams(MATCH, WRAP))
        }, LinearLayout.LayoutParams(MATCH, WRAP))
        col.addView(settingsGroup().also { g ->
            g.addView(updatePanel.view, LinearLayout.LayoutParams(MATCH, WRAP))
        }, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(10) })

        addView(col, FrameLayout.LayoutParams(MATCH, WRAP))
    }

    /**
     * Settings 分区头：title（onSurfaceVariant）+ 可选 supporting。
     * 一手：[Android Settings] layout — headings between groups；supporting 给状态/生效说明。
     */
    private fun settingsSectionHeader(
        title: String,
        supporting: String? = null,
        first: Boolean = false,
    ): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(4), if (first) dp(6) else dp(18), dp(4), dp(8))
        addView(TextView(this@MainActivity).apply {
            text = title
            textSize = 13f
            setTextColor(c(R.color.md_text_dim))
            setTypeface(null, Typeface.BOLD)
            letterSpacing = 0.02f
        })
        if (!supporting.isNullOrEmpty()) {
            addView(TextView(this@MainActivity).apply {
                text = supporting
                textSize = 11f
                setTextColor(c(R.color.md_text_dim))
                setPadding(0, dp(2), 0, 0)
            })
        }
    }

    /** Material Settings 分组容器：surfaceContainer + 细描边；组内项不再各自套卡。 */
    private fun settingsGroup() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = roundedCard(c(R.color.md_surface), CORNER_LARGE_DP, stroked = true)
        setPadding(dp(16), dp(14), dp(16), dp(14))
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

    /**
     * 单条设置滑块行（Material Settings 常见形态）：
     * 上行 = 左 label（onSurfaceVariant）+ 右实时值（tabular onSurface）；
     * 下行 = 全宽 SeekBar；组内用 1px 线分隔，不每项套卡。
     * @param name 左侧固定名（可含门禁硬串，如「方向摇杆死区」）
     * @param unit 右侧单位后缀；空串表示无单位
     * @param valueView 只写数值的 TextView（由 [updateSettingLabels] 刷新）
     */
    private fun settingSliderRow(
        name: String,
        unit: String,
        valueView: TextView,
        bar: SeekBar,
        showDivider: Boolean,
    ): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(0, dp(6), 0, dp(6))
        layoutParams = LinearLayout.LayoutParams(MATCH, WRAP)
        val head = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        head.addView(TextView(this@MainActivity).apply {
            text = name
            textSize = 14f
            setTextColor(c(R.color.md_text))
            layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
        })
        valueView.apply {
            textSize = 13f
            setTextColor(c(R.color.md_accent))
            setTypeface(null, Typeface.BOLD)
            fontFeatureSettings = TABULAR_FIGURES
            gravity = Gravity.END
            tag = unit
        }
        head.addView(valueView, LinearLayout.LayoutParams(WRAP, WRAP))
        addView(head)
        bar.apply {
            minimumHeight = dp(28)
            splitTrack = false
            progressDrawable = accentSeekDrawable()
            // 拇指：浅底 + 描边，避免与进度条同色「看不见把手」。
            thumb = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(c(R.color.md_text))
                setStroke(dp(2), c(R.color.md_accent))
                setSize(dp(18), dp(18))
            }
            thumbOffset = dp(9)
            setPadding(dp(8), dp(6), dp(8), dp(6))
        }
        addView(bar, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(2) })
        if (showDivider) addView(rule(top = 6))
    }

    /** 只刷新右侧数值；左侧名在 [settingSliderRow] 里固定（含门禁硬串）。 */
    private fun updateSettingLabels() {
        fun setVal(v: TextView, n: Double, digits: Int = 2) {
            val unit = (v.tag as? String).orEmpty()
            v.text = if (unit.isEmpty()) "%.${digits}f".format(n)
            else "%.${digits}f %s".format(n, unit)
        }
        setVal(vxLabel, SessionHolder.maxVx)
        setVal(yawLabel, SessionHolder.maxVyaw)
        setVal(driveDzLabel, SessionHolder.driveDeadzone)
        setVal(headDzLabel, SessionHolder.headDeadzone)
    }

    /** 细轨道 + primary 进度（高度约 4dp），拇指另设，避免「粗条无把手」发糊。 */
    private fun accentSeekDrawable(): android.graphics.drawable.LayerDrawable {
        val h = dp(4)
        val track = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            setColor(c(R.color.md_outline_variant))
            cornerRadius = (h / 2f)
            setSize(-1, h)
        }
        val fill = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            setColor(c(R.color.md_accent))
            cornerRadius = (h / 2f)
            setSize(-1, h)
        }
        val clip = android.graphics.drawable.ClipDrawable(
            fill, Gravity.START, android.graphics.drawable.ClipDrawable.HORIZONTAL)
        return android.graphics.drawable.LayerDrawable(arrayOf(track, clip)).apply {
            setId(0, android.R.id.background)
            setId(1, android.R.id.progress)
            // 轨道在垂直方向居中于 SeekBar 高度，拇指压在中间。
            setLayerGravity(0, Gravity.CENTER_VERTICAL)
            setLayerGravity(1, Gravity.CENTER_VERTICAL)
            setLayerHeight(0, h)
            setLayerHeight(1, h)
        }
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

    /** 3D 模型底座：对齐 HTML .model-container（24dp、深灰径向到底）。不改模型渲染器。 */
    private fun modelContainer(child: View, heightDp: Int) = FrameLayout(this).apply {
        background = GradientDrawable(
            GradientDrawable.Orientation.TL_BR,
            intArrayOf(Color.parseColor("#1E2229"), c(R.color.md_surface)),
        ).apply {
            cornerRadius = dp(CORNER_XL_DP).toFloat()
            setStroke(dp(STROKE_HAIRLINE_DP), c(R.color.md_outline_variant))
        }
        addView(child, FrameLayout.LayoutParams(MATCH, MATCH).also {
            it.gravity = Gravity.CENTER
            it.setMargins(dp(4), dp(4), dp(4), dp(4))
        })
        layoutParams = LinearLayout.LayoutParams(MATCH, dp(heightDp))
    }

    /**
     * 状态 pill：小圆角 + 半透明同色底/描边（非全胶囊 999，避免模板 pill 感）。
     * @param argb 实色（警示/成功/危险），由此派生底与描边。
     */
    private fun pillBackground(argb: Int) = GradientDrawable().apply {
        setColor(argb and 0x00FFFFFF or 0x1F000000)
        cornerRadius = dp(CORNER_CHIP_DP).toFloat()
        setStroke(dp(1), argb and 0x00FFFFFF or 0x4D000000)
    }

    /** 每次改动立刻落盘；不依赖 onStop，避免进程被杀丢设置。 */
    private fun persist() = SettingsStore.save(applicationContext)

    private fun showPage(i: Int) {
        currentPage = i
        if (::duckModelView.isInitialized) duckModelView.setRotating(i == 1)
        statePage.visibility = if (i == 0) View.VISIBLE else View.GONE
        healthPage.visibility = if (i == 1) View.VISIBLE else View.GONE
        settingsPage.visibility = if (i == 2) View.VISIBLE else View.GONE
        sshPage.visibility = if (i == 3) View.VISIBLE else View.GONE
        // 🔴 AppBar 全局唯一一份：标题随目的地变化，体现「当前在哪个页面」，
        // 而不是三页都印着同一个「控制台」造成重复（用户 2026-11-15 反馈）。
        // 收简标题（11-20 融合裁决）：去「MicroDuck ·」前缀；门禁断言不依赖此串。
        chrome.titleText.text = when (i) {
            0 -> "状态"
            1 -> "健康"
            2 -> "设置"
            else -> "终端"
        }
        tabButtons.forEachIndexed { idx, b ->
            val selected = idx == i
            val color = c(if (selected) R.color.md_accent else R.color.md_text_dim)
            @Suppress("UNCHECKED_CAST")
            val (icon, label) = b.tag as Pair<ImageView, TextView>
            icon.imageTintList = ColorStateList.valueOf(color)
            label.setTextColor(color)
            label.setTypeface(null, if (selected) Typeface.BOLD else Typeface.NORMAL)
            // M3 active indicator：选中 = primaryContainer 圆角 pill；未选中透明。
            tabIndicators.getOrNull(idx)?.background = roundedCard(
                if (selected) c(R.color.md_accent_container) else Color.TRANSPARENT,
                16, stroked = false)
        }
    }

    private fun switchMode(m: ControlMode) {
        viewModel.onSelectMode(m)
    }

    private fun refreshModeUi(state: MainViewModel.UiState) {
        val manual = state.mode == ControlMode.MANUAL
        // 去卡片化：模式不再用填充块切换，改 2px 描边 + 强调文字（单强调色）。
        styleSegment(modeManual, manual, c(R.color.md_accent))
        styleSegment(modeAuto, !manual, c(R.color.md_accent))
        // 副文案缩短（M3：supporting text 短句）；门禁不依赖 modeHint 全文。
        modeHint.text = if (manual)
            "手动：双摇杆发送 move/head · 退出即归零停车"
        else
            "自动：零驾驶帧 · 未验证策略启停，≠ 已启动自主行走"
        // 🔴 冷启动门禁断言含「进入遥控驾驶」子串，手动态文案必须保留该短语。
        launchButton.text = if (manual) "进入遥控驾驶（横屏全屏）" else "进入监测视图（横屏全屏）"
        healthSourceText.text = if (state.kind == "MOCK")
            "⚠ 当前为 Mock 演示夹具，非实机读数" else "robot.health 实机应答"
        renderMonitor(state)
    }

    /**
     * 硬件监控渲染。由 uiState 驱动；[MainViewModel.UiState.monitorReport] 为 null
     * （尚未拉取 health）时只显示无数据说明，不调用 [DuckModelView.setReport]。
     * 必须 `setTextIfChanged`：真机门禁曾因「1s setText 连发 AccessibilityEvent」
     * 导致 uiautomator waitForIdle 死锁。
     */
    private fun renderMonitor(state: MainViewModel.UiState) {
        if (!::duckModelView.isInitialized) return
        val r = state.monitorReport
        if (r == null) {
            monitorAlertText.setTextIfChanged("○ 无数据 · 未连接或 robot.health 调用失败")
            return
        }
        duckModelView.setReport(r)
        // 告警：只列真实告警（不含 notes），无告警时给一句诚实说明。
        val alertColor = when {
            r.alerts.any { it.severity == Severity.CRITICAL } -> c(R.color.md_bad)
            r.alerts.isNotEmpty() -> c(R.color.md_warn)
            r.verdict == MonitorVerdict.NO_DATA -> c(R.color.md_text_dim)
            else -> c(R.color.md_ok)
        }
        monitorAlertText.setTextColor(alertColor)
        monitorAlertText.setTextIfChanged(
            if (r.alerts.isEmpty()) {
                when (r.verdict) {
                    MonitorVerdict.NO_DATA -> "○ 无数据 · 未连接或 robot.health 调用失败"
                    MonitorVerdict.DEMO_ONLY -> "◈ 演示夹具 · 非实机读数（无告警）"
                    else -> "● 已读到的字段无告警；未读到的仍「未读到」，不是正常"
                }
            } else {
                r.alerts.joinToString("\n") { a ->
                    "${if (a.severity == Severity.CRITICAL) "⛔" else "⚠"} [${a.part.label}] ${a.message}"
                }
            },
        )
        updateHealthCards(state.lastHealth, r)
        updateServoGrid(state.lastHealth)
    }

    /** 来源标签（连接类型 / 地址无效 / 未连接），全局唯一一份。
     *  11-20 参照设计稿 .pill：Mock=琥珀警示、真实链路=绿、异常=红，胶囊底 + 实色文字。 */
    private fun renderSourceChip(state: MainViewModel.UiState) {
        val isMock = state.kind.contains("MOCK", ignoreCase = true)
        val (chipText, tone) = when {
            state.connectError.isNotEmpty() -> "● 地址无效" to c(R.color.md_bad)
            state.connected && !isMock -> "● ${state.kind}" to c(R.color.md_ok)
            isMock -> "● MOCK" to c(R.color.md_warn)
            else -> "● 未连接" to c(R.color.md_bad)
        }
        chrome.sourceChip.text = chipText
        chrome.sourceChip.setTextColor(tone)
        chrome.sourceChip.background = pillBackground(tone)
    }

    /** 休息/恢复请求结果回显（来自 ViewModel 写操作，null = 无新结果不覆盖）。 */
    private fun renderRestResult(text: String?) {
        if (text != null) restResultText.setTextIfChanged(text)
    }

    /** 原始 health 读数文本（调试用）；来自 uiState.lastHealth，缺失时如实说明。 */
    private fun renderHealthText(state: MainViewModel.UiState) {
        if (!::healthText.isInitialized) return
        healthText.setTextIfChanged(state.lastHealth?.summary() ?: "— 未读到 health")
    }

    /**
     * A3/A6/A7 只读诊断文本：把 [DiagnosticsSnapshot] 逐项铺开，缺数据一律「未读到」，
     * 错误字段（不支持/失败）如实回显。用 setTextIfChanged 避免 1s tick 反复发无障碍事件。
     */
    private fun renderDiagnostics(d: DiagnosticsSnapshot) {
        if (!::diagnosticsText.isInitialized) return
        val text = if (d.isEmpty && d.infoError == null && d.servicesError == null) {
            "尚未查询 · 点下方按钮拉取 system.info / 服务 / 日志 / 策略 / 更新状态"
        } else buildString {
            append("【系统信息 system.info】\n")
            append("  名称：").append(d.robotName ?: "未读到").append("\n")
            append("  序列号：").append(d.serial ?: "未读到").append("\n")
            d.uptimeSeconds?.let { append("  运行时间：").append(it).append(" 秒\n") }
                ?: append("  运行时间：未读到\n")
            append("  仿真机：").append(d.simulated?.let { if (it) "是" else "否" } ?: "未读到")
            d.infoError?.let { append("（").append(it).append("）") }; append("\n")

            append("【守护服务 system.services】\n")
            if (d.services.isEmpty()) append("  未读到").append(d.servicesError?.let { "（$it）" } ?: "").append("\n")
            else d.services.forEach { append("  ").append(it.unit).append(" → ").append(it.state)
                .append(it.identity?.let { " · $it" } ?: "").append("\n") }

            append("【日志 system.logs").append(d.logsUnit?.let { " · $it" } ?: "").append("】\n")
            if (d.logs.isEmpty()) append("  未读到").append(d.logsError?.let { "（$it）" } ?: "").append("\n")
            else d.logs.takeLast(20).forEach { append("  ").append(it).append("\n") }

            append("【策略 robot.policies】\n")
            if (d.policies.isEmpty()) append("  未读到").append(d.policiesError?.let { "（$it）" } ?: "").append("\n")
            else d.policies.forEach { append("  ").append(it).append("\n") }

            append("【模型 robot.model】").append(d.model ?: "未读到")
            d.modelError?.let { append("（$it）") }; append("\n")

            append("【更新状态 update.status】").append(d.updateStatus ?: "未读到")
            d.updateError?.let { append("（$it）") }; append("\n")
            append("【已装组件 update.listInstalled】\n")
            if (d.installed.isEmpty()) append("  未读到\n")
            else d.installed.forEach { append("  ").append(it).append("\n") }
        }
        diagnosticsText.setTextIfChanged(text)
    }

    /** A2 配网渲染：状态用 Settings 式 primary+secondary；附近网络走两行列表。缺字段「未读到」。 */
    private fun renderNet(n: NetSnapshot, busy: Boolean, result: String?) {
        if (!::netStatusText.isInitialized || !::netScanList.isInitialized) return
        val text = when {
            n.isEmpty && n.statusError == null -> "尚未查询"
            else -> buildString {
                append("当前连接 · ").append(n.state ?: "未读到")
                append(" · ").append(n.ssid ?: "未读到")
                append("\n")
                append(n.signal?.let { "信号 $it/100" } ?: "信号 未读到")
                append(" · ").append(n.ip4 ?: "IPv4 未读到")
                n.statusError?.let { append("\n（").append(it).append("）") }
            }
        }
        // 板端 net.status 与本机 Wi-Fi 分源呈现：本机行只是读取结果，不冒充板子已连该网络。
        val localLine = "手机当前网络 · " + (phoneSsid ?: phoneSsidNote)
        netStatusText.setTextIfChanged("$text\n$localLine")
        // 1s tick 节流：扫描内容没变就不重建 View（否则持续发 AccessibilityEvent、列表抖动）。
        val sig = n.networks.take(10).joinToString("|") {
            "${it.ssid}/${it.signal}/${it.security}/${it.saved}"
        } + "/" + (n.scanError ?: "")
        if (sig != netScanSignature) {
            netScanSignature = sig
            rebuildNetScanList(n)
        }
        netResultText.setTextIfChanged(if (busy) "处理中…" else (result ?: "—"))
    }

    /** 依 net.scan 重建 M3 两行可点选列表；点选填 SSID（手输兜底仍保留）。 */
    private fun rebuildNetScanList(n: NetSnapshot) {
        netScanList.removeAllViews()
        if (n.networks.isEmpty()) {
            netScanList.addView(TextView(this@MainActivity).apply {
                text = "未读到" + (n.scanError?.let { "（$it）" } ?: "") + " · 可手动填写 SSID"
                textSize = 12f; setTextColor(c(R.color.md_text_dim))
                setPadding(dp(4), dp(8), dp(4), dp(8))
            }, LinearLayout.LayoutParams(MATCH, WRAP))
            return
        }
        n.networks.take(10).forEachIndexed { i, net ->
            val supporting = buildString {
                append(net.signal).append("/100 · ").append(net.security)
                if (net.saved) append(" · 已存")
                if (net.security.equals("enterprise", ignoreCase = true)) append(" · 802.1X 不可连")
            }
            netScanList.addView(connectListRow(net.ssid, supporting, first = i == 0).also { row ->
                row.contentDescription = "选择网络 ${net.ssid}"
                row.setOnClickListener { selectScannedSsid(net.ssid) }
            })
        }
    }

    /** M3 Lists 两行项：headline + supporting；56dp 触控。BLE/Wi‑Fi 共用节奏。 */
    private fun connectListRow(
        headline: String,
        supporting: String,
        first: Boolean,
    ): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        minimumHeight = dp(56)
        gravity = Gravity.CENTER_VERTICAL
        isClickable = true; isFocusable = true
        background = roundedCard(c(R.color.md_card_alt), CORNER_CELL_DP, stroked = false)
        setPadding(dp(12), dp(10), dp(12), dp(10))
        layoutParams = LinearLayout.LayoutParams(MATCH, WRAP).also {
            if (!first) it.topMargin = dp(6)
        }
        addView(TextView(this@MainActivity).apply {
            text = headline
            textSize = 14f; setTextColor(c(R.color.md_text))
            setTypeface(null, Typeface.BOLD)
            maxLines = 1; ellipsize = TextUtils.TruncateAt.END
        })
        addView(TextView(this@MainActivity).apply {
            text = supporting
            textSize = 11f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, dp(2), 0, 0)
            maxLines = 1; ellipsize = TextUtils.TruncateAt.END
        })
    }

    /**
     * 点选扫描项：只写 SSID 输入框，绝不碰密码框（用户可能已输入密码，覆盖即丢失）。
     * 反馈就是输入框里出现该名称；不写 netResultText——它会被 renderNet 每 tick 覆盖成「—」。
     */
    private fun selectScannedSsid(ssid: String) {
        netSsidEdit.setText(ssid)
        netSsidEdit.setSelection(ssid.length)
    }

    /**
     * 自动读取**手机当前连接**的 Wi-Fi 名称并填入配网输入框。
     *
     * 一手依据（developer.android.com，2026-11-21）：
     *  · Android 10 隐私变更把 `WifiManager.getConnectionInfo()` 列入必须持有
     *    `ACCESS_FINE_LOCATION` 的方法；Android 9 还要求系统定位开关打开，否则只能拿到
     *    `UNKNOWN_SSID`。Android 13 的 `NEARBY_WIFI_DEVICES` 不覆盖 SSID 读取。
     *  · API31+ 官方把 WifiInfo 移到 `ConnectivityManager.getNetworkCapabilities(network)
     *    .transportInfo`；`getConnectionInfo()` 仍可用但 deprecated，故两条路都取，先新后旧。
     * 只读本机网络名，不采集位置、不上传；权限不足/定位关闭时如实回显且保留手输兜底。
     */
    private fun loadPhoneSsid(requestIfNeeded: Boolean) {
        if (!::netSsidEdit.isInitialized) return
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            phoneSsid = null
            phoneSsidNote = "未授权 · 点「取手机网络」或手填"
            refreshNetStatusOnly()
            if (requestIfNeeded) showSsidPermissionRationale()
            return
        }
        val raw = try {
            readConnectedSsid()
        } catch (_: SecurityException) {
            phoneSsid = null
            phoneSsidNote = "权限被系统拒绝 · 可手填"
            refreshNetStatusOnly()
            return
        }
        val normalized = raw?.trim()?.trim('"')
        if (normalized.isNullOrBlank() || normalized == WifiManager.UNKNOWN_SSID) {
            phoneSsid = null
            phoneSsidNote = "未读到 · 开定位/连 Wi-Fi 或手填"
        } else {
            phoneSsid = normalized
            val current = netSsidEdit.text?.toString()?.trim().orEmpty()
            val autoFill = current.isEmpty() || current == autoFilledPhoneSsid
            if (autoFill) {
                netSsidEdit.setText(normalized)
                netSsidEdit.setSelection(normalized.length)
                autoFilledPhoneSsid = normalized
            }
            phoneSsidNote = if (autoFill) "已自动填入" else "已读到 · 保留手输"
        }
        refreshNetStatusOnly()
    }

    /** 先读 API31+ 官方 NetworkCapabilities.transportInfo，失败再回退 deprecated 的 WifiManager。 */
    @SuppressLint("MissingPermission")
    private fun readConnectedSsid(): String? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val cm = getSystemService(ConnectivityManager::class.java)
            val transport = cm?.activeNetwork?.let { cm.getNetworkCapabilities(it)?.transportInfo }
            (transport as? WifiInfo)?.ssid?.let { return it }
        }
        @Suppress("DEPRECATION")
        return getSystemService(WifiManager::class.java)?.connectionInfo?.ssid
    }

    private fun showSsidPermissionRationale() {
        AlertDialog.Builder(this)
            .setTitle("读取手机当前 Wi-Fi")
            .setMessage("Android 要求定位权限才能读取已连接的 Wi-Fi 名称（App 不采集位置）。" +
                "授权后会自动填入配网输入框；也可以手动填写。")
            .setNegativeButton("手动填写", null)
            .setPositiveButton("去授权") { _, _ ->
                requestPermissions(
                    arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),
                    REQ_CODE_WIFI_SSID,
                )
            }
            .show()
    }

    /** 权限回调后立刻刷新本机网络行，不等 1s tick。 */
    private fun refreshNetStatusOnly() {
        if (!::netStatusText.isInitialized) return
        val s = viewModel.uiState.value
        renderNet(s.net, s.netBusy, s.netResultText)
    }

    /** 只有内容真变了才写，避免 1s tick 持续发 AccessibilityEvent。 */
    private fun TextView.setTextIfChanged(s: CharSequence) {
        if (text.toString() != s.toString()) text = s
    }

    /** 阶段 2：连接动作交给 ViewModel，结果经 uiState 反映，渲染由 collect 统一负责。 */
    private fun connectFromUi() {
        val raw = hostEdit.text?.toString()?.trim().orEmpty()
        viewModel.onConnect(raw)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == BleConnectPanel.REQ_CODE) blePanel.onPermissionResult(grantResults)
        if (requestCode == REQ_CODE_WIFI_SSID) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                phoneSsidNote = "权限已授予 · 读取中"
                loadPhoneSsid(requestIfNeeded = false)
            } else {
                phoneSsid = null
                phoneSsidNote = "权限未授予 · 可手填 SSID"
                refreshNetStatusOnly()
            }
        }
    }

    /** 阶段 2：健康刷新交给 ViewModel，结果经 uiState 反映，渲染由 collect 统一负责。 */
    private fun refreshHealth() {
        viewModel.onRefreshHealth()
    }

    /** 实机 8 项：null = 无帧，一律「未读到」，绝不写 0、绝不拿本地计数填。 */
    private fun renderState(s: StateSnapshot?, kind: String, frameCount: Int) {
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
        if (s == null) {
            stateSourceText.setTextColor(c(R.color.md_text_dim))
            stateSourceText.setTypeface(null, Typeface.NORMAL)
            stateSourceText.text =
                "实机状态帧 · robot.state · 当前无状态帧\nMock 不推流 / 真机未连接，不伪造"
        } else {
            stateSourceText.setTextColor(c(R.color.md_accent))
            stateSourceText.setTypeface(null, Typeface.BOLD)
            stateSourceText.text = "实机状态帧 · robot.state [$kind] · 第 $frameCount 帧"
        }
    }

    private fun renderTelemetry(state: MainViewModel.UiState) {
        val localVals = listOf(
            state.sessionState,
            state.sinkLabel,
            "%d 帧 · %s".format(state.sentCount,
                if (state.heartbeatRunning) "心跳中" else "已停"),
            "%d 帧".format(state.headSentCount),
            if (state.stateFrameCount == 0) "0 帧 · 无流"
            else "%d 帧 · %.1f Hz".format(state.stateFrameCount, state.stateHz),
            state.lastInput,
            // 拆页后主页不持有 controller ⇒ 驾驶帧恒 0 是正确行为。
            // 这一项给「本地遥测面板真的在刷新」提供可观测量，且明确属于 App 自观测。
            "%d 次".format(state.uiTickCount),
        )
        TELEMETRY_LABELS.forEachIndexed { i, label ->
            telemetryValues.getOrNull(i)?.let { setMetric(it, label, localVals[i]) }
        }
    }

    /**
     * 由 uiState 驱动渲染（UDF 单一真源）。状态驱动字段全部来自 [MainViewModel.UiState]，
     * 不再各自读 [SessionHolder]。每次 [MainViewModel.uiState] 发射新值时由 collect 调用。
     */
    private fun renderAll(state: MainViewModel.UiState) {
        renderState(state.lastState, state.kind, state.stateFrameCount)
        renderTelemetry(state)
        renderRestLimp(state.lastState?.limp)
        renderLinkBanner(state.connectError, state.linkStatus, state.linkLevel)
        renderConnectionRow(state.kind, state.connectError)
        renderSourceChip(state)
        renderRestResult(state.restResultText)
        renderHealthText(state)
        renderToF(state)   // 独立于 monitorReport：即使 health 未读，ToF 帧仍要如实渲染/显示未读到
        renderDiagnostics(state.diagnostics)
        renderNet(state.net, state.netBusy, state.netResultText)
        if (::firmwarePanel.isInitialized) firmwarePanel.render(state.firmware)
        applyProvisionedIp(state)
        refreshModeUi(state)
        // M3 Settings / Status 文案准则：顶栏只放**当前状态**，不放描述性 note 与帧计数。
        // 连接详情在链路横幅，帧计数在状态页遥测网格；顶栏保持两三项可扫读的状态。
        val statusText = if (state.connectError.isNotEmpty())
            "连接异常 · ${state.sessionState}"
        else buildString {
            append(if (state.mode == ControlMode.MANUAL) "手动" else "自动")
            append(" · ").append(state.sessionState)
        }
        chrome.statusText.text = statusText
    }

    /**
     * 配网成功后回填终端 IP 框（11-20 需求）。序号驱动的一次性事件：
     * 只有固件回执产生**新序号**（provisionedIpSeq 自增）才回填，1s tick 重复渲染不再覆盖。
     * 换链路时 core 把 ip 清空但保留序号，这里也不会把旧 IP 写回去。
     * 真正的「是否覆盖用户输入」判断在 [SshPanel.applyProvisionedIp]。
     */
    private fun applyProvisionedIp(state: MainViewModel.UiState) {
        if (state.provisionedIpSeq <= appliedProvisionedIpSeq) return
        if (!::sshPanel.isInitialized) return   // 页面未建时不记录，创建后下次渲染补填
        appliedProvisionedIpSeq = state.provisionedIpSeq
        sshPanel.applyProvisionedIp(state.provisionedIp)
    }

    private val tick = object : Runnable {
        override fun run() {
            // 时间驱动：遥测采样经 ViewModel.onTick 更新 uiState（渲染由 collect 负责），
            // 3D 模型旋转步进是纯时间驱动，不经状态。
            viewModel.onTick()
            // 只在健康页可见时推进模型旋转；有限补间（900ms）而非无限动画，
            // 每 1s 留 100ms 主线程空窗，避免 uiautomator waitForIdle 被持续 invalidate 卡住。
            if (currentPage == 1 && ::duckModelView.isInitialized) duckModelView.advanceFrame()
            if (viewModel.uiState.value.autoRefreshHealth && currentPage == 1) viewModel.onRefreshHealth()
            ui.postDelayed(this, 1_000)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (::blePanel.isInitialized) blePanel.handlePairingIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        // 从「安装未知应用」系统设置返回后复查权限：返回动作本身不等于已授权。
        if (::updatePanel.isInitialized) updatePanel.onResume()
    }

    override fun onDestroy() {
        ui.removeCallbacks(tick)
        blePanel.onDestroy()
        updatePanel.release()       // 退订 Repository 快照，避免持有已销毁面板
        updateRepository.release()  // 注销安装结果接收器
        if (::sshPanel.isInitialized) sshPanel.release()   // 断开 SSH 会话，避免后台连接泄漏
        // 🔴 不 close session：SessionHolder 拥有它，DriveActivity 返回后仍要复用。
        super.onDestroy()
    }

    private companion object {
        /** 仅 debug 端到端验证用：adb shell am start -e update_api_base http://127.0.0.1:PORT */
        const val EXTRA_UPDATE_API_BASE = "update_api_base"
        /** 读取手机当前 Wi-Fi 名称（不同于 BLE 的授权，避免误触发扫描回调）。 */
        const val REQ_CODE_WIFI_SSID = 4713
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT

        // ── 视觉 token（2026-11-13 现代化改造）──
        // 视觉 token 具名化（项目约定值，非官方 token 数值）：
        //  · 20dp 圆角量级参照 MDC 1.12.0 AAR 实测组件圆角 16dp / 28dp（见 roundedCard KDoc）；
        //  · 1dp 细描边对应 M3「Color roles」的 outline = borders/dividers 语义。
        // 🔴 不再把 20 / 1 / "tnum" 等字面量散落在十几个调用点：token 必须具名，
        //    改一处即可全局生效。XML 侧的 @dimen/m3_corner_large 与这里同源，
        //    数值改动须两处同步（见设计依据文档「token 单一真源」条目）。
        // 2026-11-20 科技感稿：圆角对齐 HTML --radius-sm/md/lg = 12 / 16 / 24。
        // XML @dimen/m3_corner_* 与这里同源，改动须两处同步。
        const val CORNER_SM_DP = 12          // 次级控件 / 分段外框（--radius-sm）
        const val CORNER_LARGE_DP = 16       // 主按钮 / 输入框 / 卡片（--radius-md）
        const val CORNER_XL_DP = 24          // 大容器：3D 模型底座（--radius-lg）
        const val CORNER_NAV_DP = 8          // 底部导航图标底 / 分段内项
        const val CORNER_CELL_DP = 16        // 数据单元格 / 次级按钮（与 radius-md 对齐）
        const val CORNER_CHIP_DP = 12        // 状态 chip
        const val STROKE_HAIRLINE_DP = 1      // 1px 分隔线 / 描边（Borders > Shadows）
        const val STROKE_SELECTED_DP = 2      // 选中态描边
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
