package io.microduck.app

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.SpannableString
import android.text.Spanned
import android.text.TextUtils
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.button.MaterialButton
import io.microduck.app.core.DriveController
import io.microduck.app.core.DriveSink
import io.microduck.app.core.HeadController
import io.microduck.app.core.JsonRpcDriveSink
import io.microduck.app.core.JsonRpcHeadSink
import io.microduck.app.core.NetpadDriveSink

/**
 * 横屏全屏遥控 / 监督视图 —— 用户 2026-11-12「打开遥控界面应该横屏」「一个界面放不下这么多内容」。
 *
 * ## 布局的一手依据
 *  - Uni Bonn, RoMan 2012, §B.1：**drive control UI 用全屏相机画面铺满 control view，
 *    「We overlay two virtual joystick panels at the lower left and lower right corner」**，
 *    「the user ... hold the mobile device with two hands ... control ... with left and right thumb」。
 *    同文 §A 明写「The user's selection in this list defines the content of the control view」⇒
 *    模式/页面选择与控制视图分离，正是拆页依据。
 *  - arXiv:2110.08753 横屏实测：摇杆中心距左/下边 9.8–19.4mm 为推荐设计区（@160dpi ≈ 62–122dp）。
 *    本页摇杆为**正方形**浮层贴底部两角，中心距边 = side + joySize/2 ≈ 12+82..100dp，落在区间内。
 *  - M3 snackbar 规范：半透明容器文字必须清晰 ⇒ 浮层 alpha 238（近乎不透明）。
 *  - m3.material.io/foundations/designing/structure：交互控件 ≥48dp 触控目标。
 *
 * ## 方向（AndroidManifest 逐 Activity 声明）
 * 官方 `<activity>` 文档：`screenOrientation` 是 **per-Activity** 属性，故只有本页声明
 * `sensorLandscape`（允许正反两个横屏方向、跟随传感器），主页保持竖屏。
 * ⚠️ 边界：Android 16 (API36) 在 **sw>=600dp 大屏**会忽略该限制（官方 behavior-changes-16），
 * 本项目 targetSdk=35、目标设备是手机（sw<600dp）暂不受影响；未来上大屏必须改响应式布局。
 * 官方「自适应注意事项」建议不锁方向 —— 这里是有意的**沉浸式操控例外**（同文档把游戏列为
 * Android 16 忽略规则的例外），已在 README 记录取舍，不是随手加锁。
 *
 * ## 为什么不隐藏系统栏
 * 官方 immersive 文档（developer.android.com/training/system-ui/immersive）说
 * 「use immersive mode only when the benefit ... goes beyond simply using extra screen space」。
 * 本页收益主要来自横屏 + 拆页；隐藏系统栏会让底部 home 手势区与摇杆冲突（官方明确 home 手势
 * 不可 opt out），且长时间遥控看不到电量。故采用 **edge-to-edge 透明栏 + 状态栏 scrim +
 * insets 让开交互控件**，不 hide systemBars。
 *
 * ## 开源方案「取长补短」落点（2026-11-12，仓库均经 GitHub 官方 API 核验）
 *  - QGroundControl Fly View（官方 User Guide）：顶部 Status Indicators + 「configurable
 *    Telemetry Values」只读仪表、Video/Map 主显示切换；Fly / Plan / Analyze / Setup 分离
 *    ⇒ 本页顶部只读 HUD + 取景框铺底，设置全放控制台页。
 *  - FPV OSD 社区共识（Betaflight / DJI / Walksnail）：遥测 overlay 应「几乎隐形、只在需要时出现」，
 *    且「keep the center frame clean」——绝不用卡片盖住你要飞过的画面；文字叠投影即可读。
 *    ⇒ 本页 HUD 改为**无背景的紧凑单行文字条**（label+value 同行），并**锚定左上角**而非
 *      浮在顶部正中（FPV/drone + 拇指热区研究：遥测贴边角、中央留给画面、离双手最远）；
 *      横屏顶部占用从约 140dp 降到约 48dp（用户 2026-11-13「太占地方 / 不需要背景」）。
 *  - 移动游戏拇指热区研究（arXiv:2110.08753）+ Spot / drone UI：双摇杆贴横屏**两下角**、
 *    画面铺底、控件浮于边缘 ⇒ 摇杆浮层去掉外层卡片（JoystickView 已自绘环/十字/旋钮），
 *    只留自绘环 + 一行极简标签，无任何背景。链路告警单独置顶居中（alert 才需横跨视线）。
 *  - `Lukaszm94/AndroidROSRobotTeleoperation`：SP/PV 速度曲线 ⇒ HUD 新增「命令→实际」。
 *  - `livekit-examples/teleop` web/README：「Animated degree scales showing current yaw and
 *    pitch angles」「View/Operator mode toggle」⇒ HUD 新增「头部 °」+ 自动页「切回手动」。
 *  - `ohho-robotics/ohho.apk` README「What is real in this build」：LIVE/DEMO 显式标注
 *    ⇒ HUD 底部新增「数据来源标签」，Mock 夹具绝不冒充实机。
 *  - OpenBot `robot/android/app/README.md`：「The controls that are sent to the robot are
 *    displayed on the right side」+ DISCLAIMERS 的随时停车要求 ⇒ 计数条第二行显示最后输入，
 *    自动页给出一键手动接管入口并写明「App 无停车能力」。
 *  - `NextGTI/ble-rc-controller`：Settings 的 dead zone ⇒ 死区改为可调并持久化。
 *
 * ## 安全
 * 退出本页 ⇒ onStop 归零 + 停心跳（Weston Robot Teleop：松手即停 / 断链停车）。
 * 自动模式不创建任何 controller ⇒ App 零驾驶帧，也**不具备停车能力**（界面明写）。
 */
class DriveActivity : AppCompatActivity() {

    private lateinit var hud: LinearLayout
    private lateinit var hudStack: LinearLayout
    private lateinit var linkBanner: TextView
    private lateinit var exitButton: MaterialButton
    private lateinit var autoNotice: TextView
    private lateinit var counterText: TextView
    private lateinit var sourceRow: TextView
    private lateinit var toManualButton: MaterialButton
    private lateinit var leftOverlay: View
    private lateinit var rightOverlay: View
    private lateinit var topScrim: View
    private lateinit var driveJoystick: JoystickView
    private lateinit var headJoystick: JoystickView
    private val hudValues = mutableListOf<TextView>()
    private var drive: DriveController? = null
    private var head: HeadController? = null
    private var joySize = 0
    private val ui = Handler(Looper.getMainLooper())

    private val d: Float by lazy { resources.displayMetrics.density }
    private fun dp(v: Int): Int = (v * d).toInt()
    private fun c(id: Int): Int = getColor(id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val manual = SessionHolder.mode == ControlMode.MANUAL
        val screenW = resources.displayMetrics.widthPixels
        val screenH = resources.displayMetrics.heightPixels
        // 正方形浮层：横屏按屏高取 40%，夹在 [140dp, 200dp]，避免把取景框挤成窄缝。
        joySize = minOf(dp(200), maxOf(dp(140), (screenH * 0.40f).toInt()))
        val side = dp(12)

        val root = FrameLayout(this).apply { setBackgroundColor(c(R.color.md_bg)) }
        root.addView(PreviewPlaceholderView(this), FrameLayout.LayoutParams(MATCH, MATCH))

        // 顶部信息：**HUD 锚定左上角**（FPV/drone 与拇指热区研究：遥测贴边角、中央留给画面，
        // 不浮在顶部正中）。链路告警单独置顶居中（alert 才需要横跨视线，平时 GONE 不占位）。
        hud = buildHud()
        hudStack = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(hud, LinearLayout.LayoutParams(WRAP, WRAP))
        }
        root.addView(hudStack, FrameLayout.LayoutParams(
            WRAP, WRAP, Gravity.TOP or Gravity.START))
        linkBanner = buildLinkBanner()
        root.addView(linkBanner, FrameLayout.LayoutParams(
            WRAP, WRAP, Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        autoNotice = buildAutoNotice()
        root.addView(autoNotice, FrameLayout.LayoutParams(
            minOf(dp(420), (screenW * 0.62f).toInt()), WRAP, Gravity.CENTER))
        exitButton = MaterialButton(this).apply {
            text = "退出"; textSize = 12f; minimumHeight = dp(48)
            contentDescription = "退出遥控"
            setOnClickListener { finish() }
        }
        root.addView(exitButton, FrameLayout.LayoutParams(WRAP, WRAP, Gravity.TOP or Gravity.END))

        // 手动接管入口 —— 取自 OpenBot「R1 触发键重新取得控制」原文（网络运行时
        // 「the game controller is disabled ... toggle this switch with the R1 trigger button
        // to regain control」）与 LiveKit teleop「View/Operator mode toggle」。
        // 🔴 本版自动模式 App 零驾驶帧、无停车能力 ⇒ 必须能在同一页一键切回手动，
        // 而不是先退回主页再点模式按钮（那样等于把接管路径藏在两级之后）。
        toManualButton = MaterialButton(this).apply {
            text = "切回手动"; textSize = 12f; minimumHeight = dp(48)
            contentDescription = "切回手动"
            visibility = if (manual) View.GONE else View.VISIBLE
            setOnClickListener {
                SessionHolder.selectMode(ControlMode.MANUAL)
                recreate()   // 重新走 onCreate：自动页没有摇杆，必须重建才有 controller
            }
        }
        root.addView(toManualButton, FrameLayout.LayoutParams(WRAP, WRAP,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL))

        // 底部中央：只保留一条可观测的发帧计数，既是驾驶页的极简遥测，
        // 也是真机门禁读「心跳在不在跑」的行为观测量（不能用内部变量自证）。
        // 无卡片底（用户「不需要背景」）：用文字投影在画面上浮现，与 HUD 同款风格。
        counterText = TextView(this).apply {
            textSize = 11f
            setTextColor(c(R.color.md_text))
            gravity = Gravity.CENTER
            contentDescription = "驾驶计数"
            paint.setShadowLayer(2f, 1f, 1f, Color.argb(190, 0, 0, 0))
            setPadding(dp(6), dp(2), dp(6), dp(2))
        }
        root.addView(counterText, FrameLayout.LayoutParams(WRAP, WRAP,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL))

        if (manual) {
            leftOverlay = joystickOverlay(colorId = R.color.md_accent, label = "方向", drive = true)
            rightOverlay = joystickOverlay(colorId = R.color.md_warn, label = "头部", drive = false)
            root.addView(leftOverlay, FrameLayout.LayoutParams(joySize, WRAP,
                Gravity.START or Gravity.BOTTOM))
            root.addView(rightOverlay, FrameLayout.LayoutParams(joySize, WRAP,
                Gravity.END or Gravity.BOTTOM))
        } else {
            leftOverlay = View(this); rightOverlay = View(this)
            autoNotice.visibility = View.VISIBLE
        }
        if (manual) autoNotice.visibility = View.GONE

        topScrim = View(this).apply { setBackgroundColor(Color.argb(190, 0x06, 0x12, 0x22)) }
        root.addView(topScrim, FrameLayout.LayoutParams(MATCH, 0, Gravity.TOP))
        setContentView(root)

        // 🔑 取景框铺满整屏（内容画到系统栏下），只让交互控件避开 insets。
        // 横屏刘海在侧边 ⇒ 左右摇杆、退出按钮都必须让开 displayCutout。
        ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
            val types = WindowInsetsCompat.Type.systemBars() or
                WindowInsetsCompat.Type.displayCutout()
            val b = insets.getInsets(types)
            topScrim.layoutParams = FrameLayout.LayoutParams(MATCH, b.top, Gravity.TOP)
            (hudStack.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top + dp(8)
                leftMargin = b.left + dp(8); rightMargin = 0
                hudStack.layoutParams = this
            }
            (linkBanner.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top + dp(8)
                leftMargin = b.left; rightMargin = b.right
                linkBanner.layoutParams = this
            }
            (exitButton.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top + dp(8)
                rightMargin = b.right + side
                exitButton.layoutParams = this
            }
            (leftOverlay.layoutParams as? FrameLayout.LayoutParams)?.apply {
                leftMargin = b.left + side; bottomMargin = b.bottom + side
                leftOverlay.layoutParams = this
            }
            (rightOverlay.layoutParams as? FrameLayout.LayoutParams)?.apply {
                rightMargin = b.right + side; bottomMargin = b.bottom + side
                rightOverlay.layoutParams = this
            }
            (counterText.layoutParams as FrameLayout.LayoutParams).apply {
                bottomMargin = b.bottom + dp(8)
                counterText.layoutParams = this
            }
            (toManualButton.layoutParams as FrameLayout.LayoutParams).apply {
                bottomMargin = b.bottom + dp(56)   // 让开底部计数条与 home 手势区
                toManualButton.layoutParams = this
            }
            WindowInsetsCompat.Builder(insets).setInsets(types, Insets.NONE).build()
        }

        if (manual) setupControllers()
        ui.post(tick)
    }

    /**
     * 顶部监测 HUD —— **无背景的紧凑文字条**（2026-11-13 重做）。
     *
     * ## 为什么要去掉背景 / 做紧凑
     *  - FPV OSD 共识（Betaflight / DJI / Walksnail 社区）：遥测 overlay 应「几乎隐形、
     *    只在需要时出现」，且「**keep the center frame clean**」——把数据放边缘、绝不铺卡片盖住
     *    你要飞过的画面。本页取景框铺底，旧版 2×3 双层卡片占去横屏顶部约 140dp（横屏仅 360dp 高），
     *    既挡视野又显笨重，正是用户说的「太占地方」。
     *  - QGC Fly View 的 Telemetry Values 也是**紧凑只读条**，不是卡片网格。
     *  - 故改为：去掉外层卡片 + 每个读数单元格的内层表面色，仅用细微文字投影
     *    (`setShadowLayer`) 保证在任意相机/占位画面上可读；label+value 由两行堆叠改为单行
     *    「标签  值」，两行三列总高从约 140dp 降到约 48dp，横屏顶部基本不占地方。
     *  - 标签文字（模式/连接、实际速度、命令→实际、头部°）是门禁固定断言文本，保持不变。
     */
    private fun buildHud(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        contentDescription = "顶部监测HUD"
        HUD_LABELS.chunked(3).forEachIndexed { rowIdx, chunk ->
            val row = LinearLayout(this@DriveActivity).apply { orientation = LinearLayout.HORIZONTAL }
            chunk.forEachIndexed { colIdx, label ->
                val v = metricCell(label, "— 未读到")
                hudValues.add(v)
                row.addView(v, LinearLayout.LayoutParams(WRAP, WRAP).also {
                    if (colIdx > 0) it.marginStart = dp(16)
                })
            }
            addView(row, LinearLayout.LayoutParams(WRAP, WRAP).also {
                if (rowIdx > 0) it.topMargin = dp(3)
            })
        }
        // LIVE / DEMO 数据源标签 —— ohho.apk README「What is real in this build」、
        // 「Home metrics are labelled demo data」「The camera has no frame」的诚实标注；
        // ble-rc-controller 的 connection dot 同型。Mock 夹具读数绝不被误认成实机数据。
        // 同样无卡片底色，仅靠投影保证可读。
        sourceRow = TextView(this@DriveActivity).apply {
            textSize = 9f
            gravity = Gravity.START
            contentDescription = "数据来源标签"
            setPadding(dp(2), dp(1), dp(2), dp(1))
            paint.setShadowLayer(2f, 1f, 1f, Color.argb(180, 0, 0, 0))
        }
        addView(sourceRow, LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(3) })
    }

    /** 单个只读读数：无背景，单行「标签  值」，细微投影保可读（FPV OSD 风格）。 */
    private fun metricCell(label: String, value: String) = TextView(this).apply {
        setTextColor(c(R.color.md_text))
        gravity = Gravity.START or Gravity.CENTER_VERTICAL
        setSingleLine(true)
        ellipsize = TextUtils.TruncateAt.END
        setLineSpacing(0f, 1.0f)
        setPadding(dp(2), dp(1), dp(2), dp(1))
        // 🔴 用户要求「不需要背景」：去掉单元格的内层表面色卡片，改用文字投影在画面上浮现。
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(180, 0, 0, 0))
        setHudMetric(this, label, value)
    }

    /** 单行渲染：label(dim, 9dp) + 两空格 + value(近白加粗, 12dp)。 */
    private fun setHudMetric(v: TextView, label: String, value: String) {
        val sep = "  "
        val full = label + sep + value
        val cut1 = label.length
        val cut2 = cut1 + sep.length
        val sp = SpannableString(full)
        val flags = Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        sp.setSpan(AbsoluteSizeSpan(dp(9)), 0, cut1, flags)
        sp.setSpan(ForegroundColorSpan(c(R.color.md_text_dim)), 0, cut1, flags)
        sp.setSpan(AbsoluteSizeSpan(dp(12)), cut2, full.length, flags)
        sp.setSpan(ForegroundColorSpan(c(R.color.md_text)), cut2, full.length, flags)
        sp.setSpan(StyleSpan(Typeface.BOLD), cut2, full.length, flags)
        v.text = sp
    }

    /** 与主页同一条链路状态；驾驶页尤其要看得见「链路已断 · 驾驶帧已停」。 */
    private fun buildLinkBanner() = TextView(this).apply {
        contentDescription = "链路状态横幅"
        textSize = 12f; setTypeface(null, Typeface.BOLD)
        gravity = Gravity.CENTER
        setPadding(dp(12), dp(8), dp(12), dp(8))
        minimumHeight = dp(40)
        visibility = View.GONE
    }

    private fun renderLinkBanner() {
        val inputError = SessionHolder.connectError
        val msg = if (inputError.isNotEmpty()) "⚠ 地址无效 · $inputError"
        else SessionHolder.linkStatus
        if (msg.isEmpty()) { linkBanner.visibility = View.GONE; return }
        linkBanner.visibility = View.VISIBLE
        linkBanner.text = msg
        val level = if (inputError.isNotEmpty()) 2 else SessionHolder.linkLevel
        linkBanner.background = roundedCard(
            if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn), 12)
        linkBanner.setTextColor(c(R.color.md_bg))
    }

    /** 自动模式说明：把「没有启停策略」这个边界写进界面，不制造假自主。 */
    private fun buildAutoNotice() = TextView(this).apply {
        text = "自动模式 · 仅监测\n" +
            "App 不发送 robot.move / robot.head（零驾驶帧）\n" +
            "板上自主行为由固件策略决定；本版未验证策略启停，不等于已启动自主行走\n" +
            "⚠ 本页 App 无停车能力：需要随时停车请点「切回手动」或由固件/物理手段处理"
        textSize = 12f
        setTextColor(c(R.color.md_warn))
        gravity = Gravity.CENTER
        setLineSpacing(0f, 1.4f)
        background = roundedCard(Color.argb(238, 0x0B, 0x1B, 0x30), 12)
        setPadding(dp(14), dp(10), dp(14), dp(10))
        contentDescription = "自动模式说明：仅监测，App不发送驾驶命令"
    }

    /**
     * 摇杆浮层 —— **去卡片化**（2026-11-13 二次重做）。
     *
     * ## 为什么去掉外层卡片
     *  - `JoystickView` 自身已绘制环形 / 十字 / 旋钮 / 投影（见 `JoystickView.onDraw`），
     *    旧版再套一层深底描边卡片 + 标题行 + 提示行是**重复镀铬**，正是用户说的
     *    「太占地方 / 不需要背景」。
     *  - 移动游戏拇指热区研究（arXiv:2110.08753）与 Spot / drone UI 一致结论：
     *    **双摇杆贴横屏两下角**、画面铺底、控件浮于边缘。故这里只保留自绘环 + 一行极简标签，
     *    无任何卡片背景，靠 ring 的半透明描边在画面上浮现。
     *  - 标签用外部 TextView（不用 `JoystickView.label`，因其画在环下沿会被方形裁切）。
     */
    private fun joystickOverlay(
        colorId: Int, label: String, drive: Boolean,
    ): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val accent = c(colorId)
        val joy = JoystickView(this@DriveActivity).apply {
            this.accent = accent
            this.label = ""
            invertY = if (drive) SessionHolder.invertY else false
            contentDescription = if (drive) "方向摇杆" else "头部摇杆"
            layoutParams = LinearLayout.LayoutParams(joySize, joySize)
            if (drive) {
                onMove = { x, y ->
                    this@DriveActivity.drive?.onAxes(x, y)
                    this@DriveActivity.drive?.startHeartbeat()
                    SessionHolder.markInput("方向 x=%+.2f y=%+.2f".format(x, y))
                }
                onRelease = {
                    this@DriveActivity.drive?.release()
                    SessionHolder.markInput("方向松手（归零）")
                }
            } else {
                onMove = { x, y ->
                    head?.onAxes(x, y)
                    SessionHolder.markInput("头部 x=%+.2f y=%+.2f".format(x, y))
                }
                onRelease = {
                    head?.release()
                    SessionHolder.markInput("头部回中")
                }
            }
        }
        if (drive) driveJoystick = joy else headJoystick = joy
        addView(joy)
        addView(TextView(this@DriveActivity).apply {
            text = label; textSize = 11f; setTextColor(accent)
            setTypeface(null, Typeface.BOLD); gravity = Gravity.CENTER
            setSingleLine(true); ellipsize = TextUtils.TruncateAt.END
            setPadding(0, dp(2), 0, 0)
        })
    }

    private fun roundedCard(fill: Int, radiusDp: Int) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(radiusDp).toFloat()
    }

    private fun setupControllers() {
        val s = SessionHolder.session ?: return
        val sink: DriveSink = if (SessionHolder.channelIndex == 1) {
            NetpadDriveSink("127.0.0.1")
        } else {
            JsonRpcDriveSink(s)
        }
        SessionHolder.sinkLabel = sink.name
        drive = DriveController(
            sink = sink,
            maxVx = SessionHolder.maxVx,
            maxVyaw = SessionHolder.maxVyaw,
            deadzone = SessionHolder.driveDeadzone,
            onSent = { SessionHolder.sentCount.incrementAndGet() },
        ).also { it.startHeartbeat() }
        head = HeadController(
            sink = JsonRpcHeadSink(s),
            headRad = HeadController.VALID_HEAD_RADS.getOrElse(SessionHolder.headRadIndex) {
                HeadController.DEFAULT_HEAD_RAD
            },
            deadzone = SessionHolder.headDeadzone,
            onSent = { SessionHolder.headSentCount.incrementAndGet() },
        )
    }

    private fun renderHud() {
        val s = SessionHolder.lastState
        val applied = s?.applied?.takeIf { it.size >= 3 }
        val requested = s?.requested?.takeIf { it.size >= 3 }
        // SP/PV（setpoint / process variable）—— Lukaszm94/AndroidROSRobotTeleoperation
        // README「viewing linear and angular velocity plots (setpoint (SP) and process
        // variable (PV))」。本项目 E3 实测低层 vx 命令跟随欠调 ~45%，把「命令→实际」
        // 直接摆在驾驶页顶部，比只显示实际速度更容易看出跟随问题。
        // 🔴 两值都只能来自 robot.state，缺一个就显示「— 未读到」，绝不用本地意图补。
        val tracking = if (requested != null && applied != null)
            "%.2f→%.2f".format(requested[0], applied[0]) else "— 未读到"
        // LiveKit teleop「Animated degree scales showing current yaw and pitch angles」
        // 的轻量版：头部角度同样只取 robot.state.head（实机上报），不拿 App 指令冒充。
        val headDeg = s?.head?.takeIf { it.size >= 4 }?.let {
            "p%.0f° y%.0f°".format(Math.toDegrees(it[1]), Math.toDegrees(it[2]))
        } ?: "— 未读到"
        val vals = listOf(
            if (SessionHolder.mode == ControlMode.AUTO) "自动 · 仅监测"
            else "${SessionHolder.kind} · ${SessionHolder.sessionState()}",
            if (SessionHolder.stateFrameCount == 0) "0 帧 · 未订阅"
            else "${SessionHolder.stateFrameCount} 帧 · %.1f Hz".format(SessionHolder.stateHz),
            applied?.let { "%.2f m/s".format(it[0]) } ?: "— 未读到",
            SessionHolder.batteryText,
            tracking,
            headDeg,
        )
        HUD_LABELS.forEachIndexed { i, label ->
            hudValues.getOrNull(i)?.let { setHudMetric(it, label, vals[i]) }
        }
        // ohho.apk 的 LIVE/DEMO 标注：数据源必须在驾驶页可见，不能只在控制台页。
        val real = SessionHolder.session != null && SessionHolder.kind != "MOCK"
        sourceRow.text = if (real) "● 实机 [${SessionHolder.kind}] · robot.state / robot.health"
            else if (SessionHolder.session != null) "● MOCK 演示夹具 · 非实机读数"
            else "● 未连接 · 无数据源"
        sourceRow.setTextColor(if (real) c(R.color.md_ok) else c(R.color.md_warn))
        // 门禁可观测的驾驶帧计数：手动模式心跳在跑时增长，松手/自动模式应停止。
        // 第二行把「发给机器人的控制」显示出来（OpenBot robot app README：
        // 「The controls that are sent to the robot are displayed on the right side」）。
        counterText.text = "已发 %d 帧 · 头 %d 帧 · %s\n最后输入 %s".format(
            SessionHolder.sentCount.get(), SessionHolder.headSentCount.get(),
            if (SessionHolder.mode == ControlMode.AUTO) "自动·零驾驶帧"
            else if (SessionHolder.heartbeatRunning) "心跳中" else "已停",
            SessionHolder.lastInput,
        )
    }

    private val tick = object : Runnable {
        override fun run() {
            SessionHolder.tick()
            renderHud()
            renderLinkBanner()
            ui.postDelayed(this, 1_000)
        }
    }

    override fun onStart() {
        super.onStart()
        drive?.startHeartbeat()
    }

    override fun onStop() {
        // 🔴 退出遥控页立即停车：不依赖触摸事件是否到达（ACTION_CANCEL 可能根本不来）。
        // head 意图不 deadman 过期，必须显式发全零帧回中（robotd/src/intents.rs:255-261）。
        if (::driveJoystick.isInitialized) driveJoystick.forceRelease()
        if (::headJoystick.isInitialized) headJoystick.forceRelease()
        drive?.stop()
        head?.stop()
        super.onStop()
    }

    override fun onDestroy() {
        ui.removeCallbacks(tick)
        super.onDestroy()
    }

    private companion object {
        const val MATCH = LinearLayout.LayoutParams.MATCH_PARENT
        const val WRAP = LinearLayout.LayoutParams.WRAP_CONTENT
        // 6 格 = 2 行 × 3 列；「模式 / 连接」「实际速度」是真机门禁的固定断言文本，勿改。
        val HUD_LABELS = listOf("模式 / 连接", "状态帧 / 帧率", "实际速度",
            "电池", "命令→实际", "头部 °")
    }
}
