package io.microduck.app

import android.content.Intent
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
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.CheckBox
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import io.microduck.app.ble.BleConnectPanel
import io.microduck.app.core.StateSnapshot

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

    private lateinit var statusText: TextView
    private lateinit var sourceChip: TextView
    private lateinit var hostEdit: EditText
    private lateinit var modeManual: MaterialButton
    private lateinit var modeAuto: MaterialButton
    private lateinit var modeHint: TextView
    private lateinit var launchButton: MaterialButton
    private lateinit var bottomStatus: TextView
    private lateinit var stateSourceText: TextView
    private lateinit var healthText: TextView
    private lateinit var healthSourceText: TextView
    private lateinit var autoRefreshBox: CheckBox
    private lateinit var channelSpinner: Spinner
    private lateinit var headRadSpinner: Spinner
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
    private lateinit var linkBanner: TextView
    private lateinit var blePanel: BleConnectPanel
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
        val root = FrameLayout(this).apply { setBackgroundColor(c(R.color.md_bg)) }
        // 视觉节奏按 M1「Metrics & keylines」一手数值：8dp 基线网格、移动端左右 16dp
        // 边距、内容组之间 8dp。旧版 10dp 边距 / 6dp 组距不在网格上，截图显得散。
        val content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        fun section(v: View, topGap: Int = 8) = content.addView(
            v, LinearLayout.LayoutParams(MATCH, WRAP).also { it.topMargin = dp(topGap) })
        section(buildAppBar(), 0)
        linkBanner = buildLinkBanner()
        section(linkBanner, 8)
        section(buildConnectionRow())
        section(buildModeRow())
        section(buildLaunchRow())
        section(buildTabRow())

        val pages = FrameLayout(this)
        statePage = buildStatePage()
        healthPage = buildHealthPage()
        settingsPage = buildSettingsPage()
        pages.addView(statePage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(healthPage, FrameLayout.LayoutParams(MATCH, MATCH))
        pages.addView(settingsPage, FrameLayout.LayoutParams(MATCH, MATCH))
        content.addView(pages, LinearLayout.LayoutParams(MATCH, 0, 1f).also {
            it.topMargin = dp(8)
        })
        content.addView(buildBottomStatus(), LinearLayout.LayoutParams(MATCH, WRAP).also {
            it.topMargin = dp(8)
        })
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

    private fun buildAppBar() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = roundedCard(c(R.color.md_card), 16)
        setPadding(dp(12), dp(10), dp(12), dp(10))
        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            addView(TextView(this@MainActivity).apply {
                text = "MicroDuck  控制台"
                textSize = 16f; setTextColor(c(R.color.md_text))
                setTypeface(null, Typeface.BOLD)
            })
            statusText = TextView(this@MainActivity).apply {
                // 🔴 真机截图实测：状态串一长就折成两行、把 appBar 撑歪。
                // 单行 + 末尾省略；完整信息分流到上面的来源标签和下面的遥测卡。
                textSize = 11f; setTextColor(c(R.color.md_text_dim))
                setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            }
            addView(statusText)
        }, LinearLayout.LayoutParams(0, WRAP, 1f).also { it.marginStart = dp(12) })
        sourceChip = TextView(this@MainActivity).apply {
            text = "● 演示会话"; textSize = 11f; setTextColor(c(R.color.md_warn))
            background = roundedCard(c(R.color.md_card_alt), 10)
            setPadding(dp(8), dp(4), dp(8), dp(4))
        }
        addView(sourceChip)
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
        if (msg.isEmpty()) {
            linkBanner.visibility = View.GONE
            return
        }
        linkBanner.visibility = View.VISIBLE
        linkBanner.text = msg
        val level = if (inputError.isNotEmpty()) 2 else SessionHolder.linkLevel
        // 亮底配深字：MaterialButton 那个「只换背景不换字色」的坑不能在这里重演。
        linkBanner.setBackgroundColor(if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn))
        linkBanner.setTextColor(c(R.color.md_bg))
        linkBanner.background = roundedCard(
            if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn), 12)
    }

    private fun buildConnectionRow() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, 0, 0, 0)
        hostEdit = EditText(this@MainActivity).apply {
            hint = "host:port（留空 = Mock 演示）"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            textSize = 13f; minimumHeight = dp(48)
            setTextColor(c(R.color.md_text)); setHintTextColor(c(R.color.md_text_dim))
            background = roundedCard(c(R.color.md_card), 12)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            layoutParams = LinearLayout.LayoutParams(0, WRAP, 1f)
        }
        addView(hostEdit)
        addView(MaterialButton(this@MainActivity).apply {
            text = "连接"; textSize = 12f; minimumHeight = dp(48)
            setOnClickListener { connectFromUi() }
        }, LinearLayout.LayoutParams(WRAP, WRAP).also { it.marginStart = dp(8) })
    }

    /** 模式选择：NIST UTAP 的 manual / supervisory 两档，当前档显著标注。 */
    private fun buildModeRow() = MaterialCardView(this).apply {
        radius = dp(16).toFloat(); cardElevation = 0f; strokeWidth = 0
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
            contentDescription = "手动模式"
            setOnClickListener { switchMode(ControlMode.MANUAL) }
        }
        modeAuto = MaterialButton(this@MainActivity).apply {
            text = "自动模式"; textSize = 12f; minimumHeight = dp(48)
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
        addView(col, FrameLayout.LayoutParams(MATCH, WRAP))
    }

    private fun buildLaunchRow() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        launchButton = MaterialButton(this@MainActivity).apply {
            textSize = 14f; minimumHeight = dp(52)
            // 主 CTA 亮底必须配深字；主题默认 colorOnPrimary 偏暗紫，真机截图对比度不足。
            setTextColor(c(R.color.md_bg))
            contentDescription = "进入遥控界面"
            setOnClickListener { startActivity(Intent(this@MainActivity, DriveActivity::class.java)) }
        }
        addView(launchButton, LinearLayout.LayoutParams(MATCH, WRAP))
    }

    /** 三个顶层目的地（M3 3–5 destinations），固定位置、不滚动。 */
    private fun buildTabRow() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        // M3 navigation bar 三个目的地应共用一个容器；旧版只有选中项有底，
        // 截图里「状态」像独立胶囊、另两个像裸文字，视觉重心失衡。
        background = roundedCard(c(R.color.md_card), 12)
        setPadding(dp(4), dp(4), dp(4), dp(4))
        listOf("状态", "健康", "设置").forEachIndexed { i, label ->
            val b = MaterialButton(this@MainActivity).apply {
                text = label; textSize = 12f; minimumHeight = dp(48)
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
        radius = dp(16).toFloat(); cardElevation = 0f; strokeWidth = 0
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(16), dp(12), dp(16), dp(12))
        contentDescription = "监测数据卡：实机状态帧与App本地遥测"
        val scroll = ScrollView(this@MainActivity)
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        stateSourceText = TextView(this@MainActivity).apply {
            textSize = 12f; setTextColor(c(R.color.md_accent))
            setTypeface(null, Typeface.BOLD)
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
        background = roundedCard(c(R.color.md_card_alt), 8)
        setPadding(dp(8), dp(4), dp(8), dp(4))
        setLineSpacing(0f, 1.1f)
        maxLines = 2; ellipsize = TextUtils.TruncateAt.END
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
        setBackgroundColor(Color.argb(50, 0x8F, 0xA9, 0xC4))
        layoutParams = LinearLayout.LayoutParams(MATCH, dp(1)).also {
            it.topMargin = dp(16); it.bottomMargin = dp(12)
        }
    }

    private fun buildHealthPage() = MaterialCardView(this).apply {
        radius = dp(14).toFloat(); cardElevation = 0f
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
        radius = dp(14).toFloat(); cardElevation = 0f
        setCardBackgroundColor(c(R.color.md_card))
        setContentPadding(dp(10), dp(8), dp(10), dp(8))
        val scroll = ScrollView(this@MainActivity)
        val col = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        col.addView(TextView(this@MainActivity).apply {
            text = "遥控参数（进入横屏遥控页时生效 · 已本地持久化）"
            textSize = 12f; setTextColor(c(R.color.md_text)); setTypeface(null, Typeface.BOLD)
        })
        col.addView(TextView(this@MainActivity).apply {
            text = "取自 ROS_Robot_Controller / ohho.apk 的 persistent preferences；" +
                "控制模式与连接地址刻意不持久化（每次冷启动回手动，保留手动接管入口）"
            textSize = 10f; setTextColor(c(R.color.md_text_dim))
            setPadding(0, 0, 0, dp(6))
        })
        channelSpinner = Spinner(this@MainActivity).apply {
            minimumHeight = dp(48)
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_item,
                listOf("JSON-RPC（TCP/仿真）", "UDP netpad（真机 :4210）")).also {
                it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            }
            setSelection(SessionHolder.channelIndex)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    SessionHolder.channelIndex = pos
                    persist()
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        col.addView(channelSpinner, LinearLayout.LayoutParams(MATCH, WRAP))
        headRadSpinner = Spinner(this@MainActivity).apply {
            minimumHeight = dp(48)
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_item,
                listOf("头部幅度 0.5 rad", "头部幅度 1.0 rad", "头部幅度 2.5 rad")).also {
                it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            }
            setSelection(SessionHolder.headRadIndex)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    SessionHolder.headRadIndex = pos
                    persist()
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        col.addView(headRadSpinner, LinearLayout.LayoutParams(MATCH, WRAP))
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
        scroll.addView(col)
        addView(scroll, FrameLayout.LayoutParams(MATCH, MATCH))
    }

    /** 把 SessionHolder 的当前值写回设置页控件（load / reset 后用）。 */
    private fun restoreSettingsUi() {
        channelSpinner.setSelection(SessionHolder.channelIndex)
        headRadSpinner.setSelection(SessionHolder.headRadIndex)
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
        background = roundedCard(c(R.color.md_card), 10)
        setPadding(dp(10), dp(6), dp(10), dp(6))
        setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
    }

    private fun roundedCard(fill: Int, radiusDp: Int) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(radiusDp).toFloat()
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
                sourceChip.text = when {
                    ok -> "● ${SessionHolder.kind}"
                    SessionHolder.connectError.isNotEmpty() -> "● 地址无效"
                    else -> "● 未连接"
                }
                sourceChip.setTextColor(
                    if (ok) c(R.color.md_ok) else c(R.color.md_bad))
                refreshModeUi()
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
        // 单行状态串：完整信息在来源标签 / 状态卡里，不再让 appBar 折成两行。
        statusText.text = if (SessionHolder.connectError.isNotEmpty())
            "地址无效 · 会话=${SessionHolder.sessionState()}"
        else buildString {
            if (SessionHolder.note.isNotEmpty() && SessionHolder.note != "地址无效")
                append(SessionHolder.note).append(" · ")
            append(if (SessionHolder.mode == ControlMode.MANUAL) "手动" else "自动")
            append(" · ").append(SessionHolder.sessionState())
            append(" · ").append(SessionHolder.stateFrameCount).append(" 帧")
        }
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

    override fun onDestroy() {
        ui.removeCallbacks(tick)
        blePanel.onDestroy()
        // 🔴 不 close session：SessionHolder 拥有它，DriveActivity 返回后仍要复用。
        super.onDestroy()
    }

    private companion object {
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT
        val STATE_LABELS = listOf("策略", "控制环", "命令→实际", "限幅",
            "安全", "头部", "电流", "航向·时间")
        val TELEMETRY_LABELS = listOf("会话状态", "驱动通道", "驾驶帧 / 心跳",
            "头部帧", "状态帧 / 帧率", "最后输入", "本地刷新")
    }
}
