package io.microduck.app

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.text.SpannableString
import android.text.Spanned
import android.text.TextUtils
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.ImageView
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
 * ## 布局的一手依据（均经 2026-11-13 WebSearch 一手核验，非凭空）
 *  - **双虚拟摇杆贴横屏两下角 + 双拇指**：arXiv:2110.08753（「Understanding Players'
 *    Interaction Patterns with Mobile Game App UI via Visualizations」）实测：横屏持机时
 *    左/右拇指最舒适点击区距屏幕左/下边 **9.8–19.4 mm**，且「most of the center of the
 *    joystick keeps at least a 10 mm distance from the left and lower corners」。本页摇杆中心
 *    距角 ≈13 mm（side 12dp + joySize/2，@560dpi），落在该舒适区内。
 *  - **全屏画面铺底 + 控件浮边缘**：同上论文把控制视图区定义为「lower left part of the
 *    screen when holding the phone horizontally」，与 FPV OSD「keep the feed clear / use
 *    logical placement without obstructing your view」（Oscar Liang, Betaflight OSD 权威教程）
 *    同构。
 *  - **多页拆分（模式选择 / 控制视图分离）**：teleop UX 通用原则——把「选模式/选目的地」与
 *    「连续驾驶控制」拆到不同页面，避免单屏过载（用户 2026-11-12「一个界面放不下这么多内容」）。
 *    此为通用设计取舍，非引用单一论文的特定章节。
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
 * ## 开源方案「取长补短」落点（2026-11-12，仓库均经 GitHub REST API（`api.github.com`）核验）
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
 *  - **第三轮强化（2026-11-13，参考资料：simplified.media / Godot / Unity-CSDN 虚拟摇杆手感、
 *    DJI Fly / Litchi 主屏遥测、FPV OSD / 户外可读性文献）**：
 *    · 摇杆**死区可视化**（虚线小环，比例来自 `SessionHolder.driveDeadzone/headDeadzone`）；
 *    · 摇杆**触觉反馈**（首触 + 满幅各一次短震，`Vibrator` + `VIBRATE` 权限）；
 *    · HUD 新增**常驻链路信号指示**（`linkLevel` + `stateHz`，真实数据，不伪造 RTT）；
 *    · 摇杆标签加投影（户外/亮画面可读性）。
 *    ⚠️ 以上均不改动门禁断言文本，`compileDebugKotlin` 已 PASS；**未真机复验**（设备断开），
 *      待重连后装包截图 + 重跑 `python tools/device_ui_check.py` 确认 59/59 与手感。
 *
 *  - **第四轮强化（2026-11-13，参考资料：Falcon「real-time design」、TechnoLynx「Remote
 *    Operator Console」读序表、ColorSift「outdoor interface contrast」、teach-pendant /
 *    deadman 文献、teleop haptic 文献）**——「各个方面和角度强化」：
 *    · **状态停滞告警**（Falcon/TechnoLynx 读序#3「frame age / freeze flag」）：链路看似正常
 *      却很久没新帧时，HUD 打「状态停滞 Xs」并组合进告警行——「看起来仍实时的陈旧值」是最危险的。
 *    · **控制接管状态药丸**（Teach-pendant enabling 状态须可见 + TechnoLynx 读序#4「who is in
 *      control」）：已接管(发送中)/已松手·已停/链路挂起/监督视图，常驻左上角、带描边。
 *    · **指令发送失败告警**（safety）：`drive.lastError` 此前捕获却从未显示，现进告警行——
 *      推了摇杆但帧没真正出去时操作员能立刻知道。
 *    · **低电量告警**（field-robot 安全）：解析固件给的 percent，<20% 进告警行（缺失不显示 0）。
 *    · **链路恶化触觉告警**（haptic 作非视觉通道）：链路 0→≥1 时三连短震，强光/分心也能感知。
 *    · **户外可读性**（ColorSift）：状态药丸/告警行/链路横幅均加 2px 同色描边，强光下色彩被
 *      压扁时靠轮廓保可读；摇杆增加**握持发光环**作「已激活」的视觉冗余确认。
 *    ⚠️ 仍不改动门禁断言文本；告警行/药丸为新增 TextView，门禁子串检查不受影响。
 *
 * ## 安全
 * 退出本页 ⇒ onStop 归零 + 停心跳（Weston Robot Teleop：松手即停 / 断链停车）。
 * 自动模式不创建任何 controller ⇒ App 零驾驶帧，也**不具备停车能力**（界面明写）。
 */
class DriveActivity : AppCompatActivity() {

    private lateinit var hudStack: LinearLayout
    private lateinit var rightTop: LinearLayout
    private lateinit var topCenter: LinearLayout
    private lateinit var linkBanner: TextView
    private lateinit var exitButton: ImageButton
    private lateinit var autoNotice: TextView
    private lateinit var counterText: TextView
    private lateinit var sourceRow: TextView
    private lateinit var signalRow: TextView
    /** 控制接管/已停/挂起 状态药丸（Teach-pendant enabling 状态可见化 + TechnoLynx 读序#4）。 */
    private lateinit var armedPill: TextView
    /** 组合告警行：状态停滞 / 指令发送失败 / 低电量（Falcon 实时设计：失败是第一态）。 */
    private lateinit var alertLine: TextView
    private lateinit var toManualButton: MaterialButton
    private lateinit var leftOverlay: View
    private lateinit var rightOverlay: View
    private lateinit var driveJoystick: JoystickView
    private lateinit var headJoystick: JoystickView
    private val hudValues = mutableListOf<TextView>()
    private var drive: DriveController? = null
    private var head: HeadController? = null
    private var joySize = 0
    private val ui = Handler(Looper.getMainLooper())
    /** 链路恶化触觉告警（haptic 作为非视觉告警通道，见 teleop/marionette 文献）。 */
    private val vibrator by lazy { getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator }
    private var lastLinkLevel = 0

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

        // FPV 角落法则：数据分角、中心清空；退出箭头按 Material 惯例置左上角最顶（不与其他
        // 信息争地）。左上=控制/信号/数据源（视线第一落点），右上=驾驶读数，底部=帧数/输入。
        val cells = buildHudCells()
        sourceRow = buildSourceRow()
        signalRow = buildSignalRow()
        // 左上角：退出箭头（48dp 触控目标、无背景纯箭头）+ 控制/信号/数据源
        hudStack = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        exitButton = buildExitButton()
        hudStack.addView(exitButton, LinearLayout.LayoutParams(dp(48), dp(48)).also { it.bottomMargin = dp(2) })
        hudStack.addView(cells[0], LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(2) })  // 模式/连接
        armedPill = buildArmedPill()
        hudStack.addView(armedPill, LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(2) })
        hudStack.addView(sourceRow, LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(2) })
        hudStack.addView(signalRow, LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(2) })
        root.addView(hudStack, FrameLayout.LayoutParams(WRAP, WRAP, Gravity.TOP or Gravity.START))
        // 右上角：驾驶读数（实际速度/命令→实际/头部°/电量/状态帧率）——避开左上角的控制组
        rightTop = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        cells.subList(1, 6).forEach { v ->
            rightTop.addView(v, LinearLayout.LayoutParams(WRAP, WRAP).also { it.topMargin = dp(2) })
        }
        root.addView(rightTop, FrameLayout.LayoutParams(WRAP, WRAP, Gravity.TOP or Gravity.END))
        // 顶部中央：链路横幅 + 告警（垂直堆叠，触发时横跨，平时 GONE 不占位）
        linkBanner = buildLinkBanner()
        alertLine = buildAlertLine()
        topCenter = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
        }
        topCenter.addView(linkBanner, LinearLayout.LayoutParams(WRAP, WRAP).also { it.bottomMargin = dp(2) })
        topCenter.addView(alertLine, LinearLayout.LayoutParams(WRAP, WRAP))
        root.addView(topCenter, FrameLayout.LayoutParams(WRAP, WRAP, Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        autoNotice = buildAutoNotice()
        root.addView(autoNotice, FrameLayout.LayoutParams(
            minOf(dp(420), (screenW * 0.62f).toInt()), WRAP, Gravity.CENTER))

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
            leftOverlay = joystickOverlay(colorId = R.color.md_accent, label = "方向", drive = true,
                deadzone = SessionHolder.driveDeadzone)
            rightOverlay = joystickOverlay(colorId = R.color.md_warn, label = "头部", drive = false,
                deadzone = SessionHolder.headDeadzone)
            root.addView(leftOverlay, FrameLayout.LayoutParams(joySize, WRAP,
                Gravity.START or Gravity.BOTTOM))
            root.addView(rightOverlay, FrameLayout.LayoutParams(joySize, WRAP,
                Gravity.END or Gravity.BOTTOM))
        } else {
            leftOverlay = View(this); rightOverlay = View(this)
            autoNotice.visibility = View.VISIBLE
        }
        if (manual) autoNotice.visibility = View.GONE

        setContentView(root)

        // 🔑 取景框铺满整屏（内容画到系统栏下），只让交互控件避开 insets。
        // 横屏刘海在侧边 ⇒ 左右摇杆、退出按钮都必须让开 displayCutout。
        ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
            val types = WindowInsetsCompat.Type.systemBars() or
                WindowInsetsCompat.Type.displayCutout()
            val b = insets.getInsets(types)
            // 🔴 只调整**直接挂在 root(FrameLayout) 上的容器/控件**的 margin；嵌套子元素
            // （退出箭头在 hudStack 内、linkBanner 在 topCenter 内）由父容器的 margin 统一
            // 让开系统栏/刘海，避免把 LinearLayout.LayoutParams 误当 FrameLayout.LayoutParams
            // 强转 → ClassCastException 崩页（之前 linkBanner/exitButton 强转必崩）。
            // 🔴 用户 2026-11-13「两边的内容太靠下，往上靠一点点」= 顶部左右两组 HUD
            // （含左上角返回键 hudStack、右上角读数 rightTop、顶部横幅 topCenter）离顶栏还有
            // 8dp 间隙，整体偏低；去掉间隙让其紧贴系统栏下沿、整体上移。摇杆不动（用户明确
            // 「不是双摇杆上移」）。
            (hudStack.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top; leftMargin = b.left + dp(8); rightMargin = 0
                hudStack.layoutParams = this
            }
            (rightTop.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top; leftMargin = 0; rightMargin = b.right + dp(8)
                rightTop.layoutParams = this
            }
            (topCenter.layoutParams as FrameLayout.LayoutParams).apply {
                topMargin = b.top
                topCenter.layoutParams = this
            }
            (leftOverlay.layoutParams as? FrameLayout.LayoutParams)?.apply {
                leftMargin = b.left + side; bottomMargin = b.bottom + dp(12)
                leftOverlay.layoutParams = this
            }
            (rightOverlay.layoutParams as? FrameLayout.LayoutParams)?.apply {
                rightMargin = b.right + side; bottomMargin = b.bottom + dp(12)
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
     * 6 个只读读数单元（无背景单行 label+value），逐格加入 `hudValues` 供 `renderHud` 更新。
     *
     * ## 为什么从「2×3 卡片网格」改成「扁平 6 格分角」
     *  - FPV OSD 共识（Betaflight / DJI / Walksnail）：遥测 overlay 应「几乎隐形、只在需要时
     *    出现」，且「**keep the center frame clean**」——数据放边缘、绝不铺卡片盖住画面。
     *    本页取景框铺底，旧版 2×3 双层卡片占去横屏顶部约 140dp（横屏仅 360dp 高），既挡视野
     *    又显笨重，正是用户说的「太占地方 / 不需要背景」。
     *  - QGC Fly View 的 Telemetry Values 也是**紧凑只读条**，不是卡片网格。
     *  - 故 6 格拆成扁平单元：第 0 格（模式/连接）进左上角 `hudStack`、其余 5 格进右上角
     *    `rightTop`，中心留给取景框。`metricCell` 已是无背景单行 + 文字投影（见下）。
     *  - 标签文字（模式/连接、实际速度、命令→实际、头部°）是门禁固定断言文本，保持不变。
     */
    private fun buildHudCells(): List<TextView> {
        val cells = mutableListOf<TextView>()
        HUD_LABELS.forEach { label ->
            val v = metricCell(label, "— 未读到")
            hudValues.add(v)
            cells.add(v)
        }
        return cells
    }

    /** LIVE / DEMO 数据源标签 —— ohho.apk README「What is real in this build」、
     *  「Home metrics are labelled demo data」「The camera has no frame」的诚实标注；
     *  ble-rc-controller 的 connection dot 同型。Mock 夹具读数绝不被误认成实机数据。
     *  无卡片底色，仅靠投影保证可读。 */
    private fun buildSourceRow() = TextView(this).apply {
        textSize = 9f
        gravity = Gravity.START
        contentDescription = "数据来源标签"
        setPadding(dp(2), dp(1), dp(2), dp(1))
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(180, 0, 0, 0))
    }

    /** 常驻链路/信号指示（DJI Fly / Litchi：信号强度持续可见，而非仅出错时弹横幅）。
     *  只用真实数据：linkLevel（0 正常 / 1 重连中 / 2 失败）+ stateHz（状态订阅速率），
     *  绝不伪造 RTT/延迟（本 App 当前无该后端指标）。 */
    private fun buildSignalRow() = TextView(this).apply {
        textSize = 9f
        gravity = Gravity.START
        contentDescription = "链路信号指示"
        setPadding(dp(2), dp(1), dp(2), dp(1))
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(180, 0, 0, 0))
    }

    /**
     * 退出按钮 —— 左上角返回箭头（Material 惯例：返回导航固定在 top-left，48dp 触控目标、
     * 24dp 图标）。纯箭头、无卡片背景（用户「不需要背景」）。
     *
     * ## 依据
     *  - material.io「App bars: top」：导航（返回）图标放置于栏**最左**；社区与 UX 研究
     *    （ux.stackexchange「Back button on the left or right?」、eathealthy365 等）一致结论：
     *    **Never Place It on the Right**——返回箭头放右侧会与 iOS 习惯冲突、造成误操作。
     *  - Material 2/3 明确：触控目标 ≥48dp、图标 24dp（md3.material.io foundations / material.io）。
     *  - 退出即 `finish()`，并触发 `onStop` 停车（NIST UTAP / Weston Robot Teleop 安全铁律）。
     *  - content-description 固定为「退出遥控」，供真机门禁按描述定位（59/59 断言之一）。
     */
    private fun buildExitButton() = ImageButton(this).apply {
        contentDescription = "退出遥控"
        setImageResource(R.drawable.ic_arrow_back)
        background = null
        scaleType = ImageView.ScaleType.FIT_CENTER
        setOnClickListener { finish() }   // 退出遥控页 ⇒ onStop 停心跳/归零（安全）
    }

    /** 单个只读读数：无背景，单行「标签  值」，细微投影保可读（FPV OSD 风格）。 */
    private fun metricCell(label: String, value: String) = TextView(this).apply {
        setTextColor(c(R.color.md_text))
        gravity = Gravity.START or Gravity.CENTER_VERTICAL
        setSingleLine(true)
        ellipsize = TextUtils.TruncateAt.END
        setLineSpacing(0f, 1.0f)
        // HUD 微排版：小标签字距 + 等宽数字（遥控页数值高频刷新，比例数字会左右抖动）。
        // 依据同 MainActivity.metricCell（Android tnum OpenType / 控制站排版一手资料）。
        letterSpacing = TRACKING_HUD
        fontFeatureSettings = TABULAR_FIGURES
        setPadding(dp(2), dp(1), dp(2), dp(1))
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(180, 0, 0, 0))
        setHudMetric(this, label, value)
    }

    /**
     * 仅在文本**真正变化**时才 setText —— 双保险（参考 usespectra.dev 对
     * `could not get idle state` 的权威归因：App 每秒刷新 UI 会持续发射
     * TYPE_VIEW_TEXT_CHANGED 无障碍事件，uiautomator 永远凑不满 1000ms 静默窗）。
     * 差异更新同时消除静态格（如「— 未读到」）的无谓重排（StackOverflow 实测每秒
     * setText 占 ~40% CPU），是无障碍 + 性能的双重改进。
     */
    private fun setTextIfChanged(v: TextView, text: CharSequence) {
        if (v.text.toString() != text.toString()) v.text = text
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
        setTextIfChanged(v, sp)
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

    /** 控制接管状态药丸（Teach-pendant 的 enabling 设备状态需可见；TechnoLynx 读序#4
     *  「Control owner and mode — who is in control right now? Always shown」）。 */
    private fun buildArmedPill() = TextView(this).apply {
        textSize = 10f; gravity = Gravity.START; visibility = View.GONE
        setPadding(dp(5), dp(2), dp(5), dp(2))
        // 户外可读性（ColorSift）：除投影外再加 2px 描边，强光下色彩对比被压扁时仍有轮廓可辨。
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(190, 0, 0, 0))
        contentDescription = "控制接管状态"
    }

    /** 组合告警行：状态停滞 / 指令发送失败 / 低电量 —— Falcon 实时设计「失败是第一态」。 */
    private fun buildAlertLine() = TextView(this).apply {
        textSize = 10f; gravity = Gravity.START; visibility = View.GONE
        setPadding(dp(5), dp(2), dp(5), dp(2))
        paint.setShadowLayer(2f, 1f, 1f, Color.argb(190, 0, 0, 0))
        contentDescription = "告警行"
    }

    /** 带描边的药丸（户外可读性：颜色被强光压扁时靠描边保轮廓，ColorSift 技巧#4）。 */
    private fun borderedCard(fill: Int, stroke: Int, radiusDp: Int) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(radiusDp).toFloat(); setStroke(dp(2), stroke)
    }

    /** 从 batteryText("12.34 V · 56%") 解析电量百分比；解析不到返回 null（绝不用 0 兜底）。 */
    private fun parseBatteryPct(text: String): Int? {
        val m = Regex("""(\d+)%""").find(text) ?: return null
        return m.groupValues[1].toIntOrNull()
    }

    /** 链路恶化触觉告警：三连短震（marionette 文献：双/单震区分状态；这里用三连表告警）。
     *  haptic 是非视觉告警通道，强光/分心时仍能提醒操作员（teleop 文献）。 */
    private fun buzzLinkLost() {
        val v = vibrator ?: return
        val pattern = longArrayOf(0L, 45, 70, 45, 70, 45)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            v.vibrate(VibrationEffect.createWaveform(pattern, -1))
        } else {
            @Suppress("DEPRECATION")
            v.vibrate(pattern, -1)
        }
    }

    private fun renderLinkBanner() {
        val inputError = SessionHolder.connectError
        val msg = if (inputError.isNotEmpty()) "⚠ 地址无效 · $inputError"
        else SessionHolder.linkStatus
        if (msg.isEmpty()) { linkBanner.visibility = View.GONE; lastLinkLevel = SessionHolder.linkLevel; return }
        linkBanner.visibility = View.VISIBLE
        // 差异更新：A5 的恢复提示会持续数秒，若每 1.5s 无条件 setText 会持续发射
        // TYPE_VIEW_TEXT_CHANGED，重新触发 uiautomator "could not get idle state" 死锁。
        setTextIfChanged(linkBanner, msg)
        val level = if (inputError.isNotEmpty()) 2 else SessionHolder.linkLevel
        // 户外可读性：深底 + 同色描边，强光下仍清晰（ColorSift 技巧#4）。
        linkBanner.background = borderedCard(
            if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn),
            if (level >= 2) c(R.color.md_bad) else c(R.color.md_warn), 12)
        linkBanner.setTextColor(c(R.color.md_bg))
        // 链路恶化（0→≥1）时触觉告警：非视觉通道，强光/分心也能感知（teleop/marionette 文献）。
        if (level > lastLinkLevel && level >= 1) buzzLinkLost()
        lastLinkLevel = level
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
        colorId: Int, label: String, drive: Boolean, deadzone: Double,
    ): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val accent = c(colorId)
        val joy = JoystickView(this@DriveActivity).apply {
            this.accent = accent
            this.label = ""
            this.deadzoneFraction = deadzone.toFloat()
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
        val sourceText = if (real) "● 实机 [${SessionHolder.kind}] · robot.state / robot.health"
            else if (SessionHolder.session != null) "● MOCK 演示夹具 · 非实机读数"
            else "● 未连接 · 无数据源"
        setTextIfChanged(sourceRow, sourceText)
        sourceRow.setTextColor(if (real) c(R.color.md_ok) else c(R.color.md_warn))
        // 常驻链路信号（真实数据）：linkLevel 映射「强/弱/断」+ 状态订阅速率。
        val lvl = SessionHolder.linkLevel
        val quality = when {
            lvl >= 2 -> "断"
            lvl == 1 -> "弱·重连中"
            SessionHolder.stateFrameCount == 0 -> "无"
            else -> "强"
        }
        val hz = if (SessionHolder.stateFrameCount == 0) "—" else "%.0f".format(SessionHolder.stateHz)
        // A4 控制者归属（Wandelbots NOVA 合规文档 / DIN EN ISO 10218-1：
        // 「It must always be made clear by the UI which device is currently controlling
        //  the robot」）。只展示 `robot.remoteSessionActive` 的真实读回值；
        // null 一律写「未知」，绝不把「没读到」画成「无遥在场」（UNVERIFIED != PASS）。
        // 合并进已有 signalRow 而不新增 View：零布局变化，避免把下方内容挤出
        // uiautomator 视口（门禁工具自身第 5 坑）。
        val telepresence = when (SessionHolder.remoteSessionActive) {
            true -> "有遥在场"
            false -> "无遥在场"
            null -> "未知"
        }
        val signalText = "链路 $quality · 状态 $hz Hz · 遥在场 $telepresence"
        setTextIfChanged(signalRow, signalText)
        signalRow.setTextColor(when {
            lvl >= 2 -> c(R.color.md_bad)
            lvl == 1 -> c(R.color.md_warn)
            else -> c(R.color.md_text_dim)
        })

        // ---- 控制接管状态药丸（Teach-pendant enabling 状态可见化 + TechnoLynx 读序#4）----
        //  谁在控制、控制是否激活，必须常驻可见；链路挂起时驾驶帧已停也要点明。
        val armedText: String
        val armedColor: Int
        when {
            SessionHolder.mode == ControlMode.AUTO -> {
                armedText = "○ 监督视图 · 零驾驶帧"; armedColor = c(R.color.md_text_dim)
            }
            SessionHolder.linkLevel >= 2 -> {
                armedText = "⚠ 链路失败 · 控制挂起"; armedColor = c(R.color.md_bad)
            }
            SessionHolder.linkLevel == 1 -> {
                armedText = "⚠ 重连中 · 控制挂起"; armedColor = c(R.color.md_warn)
            }
            SessionHolder.heartbeatRunning -> {
                armedText = "● 已接管（指令发送中）"; armedColor = c(R.color.md_ok)
            }
            else -> {
                armedText = "○ 已松手 · 已停"; armedColor = c(R.color.md_text_dim)
            }
        }
        // 仅在文本真正变化时重设文字/颜色/描边背景，避免每秒重建（差异更新·双保险）。
        if (armedPill.text.toString() != armedText) {
            armedPill.text = armedText
            armedPill.setTextColor(armedColor)
            armedPill.background = borderedCard(
                Color.argb(70, 0x06, 0x12, 0x22), armedColor, 8)
        }
        armedPill.visibility = View.VISIBLE

        // ---- 组合告警行（Falcon：失败/停滞是第一态，必须立刻可见）----
        val alerts = mutableListOf<String>()
        // (1) 状态停滞：链路看似正常但很久没新帧 —— 最危险的是「看起来仍实时」的陈旧值。
        val age = SessionHolder.stateAgeMs()
        if (SessionHolder.mode == ControlMode.MANUAL && SessionHolder.linkLevel == 0 && age >= 1500) {
            alerts.add("状态停滞 %.1f s".format(age / 1000.0))
        }
        // (2) 指令发送失败：推了摇杆但帧没真正出去（drive.lastError 此前捕获却从未显示）。
        if (SessionHolder.mode == ControlMode.MANUAL) {
            val de = drive?.lastError
            if (!de.isNullOrEmpty()) alerts.add("指令发送失败")
        }
        // (3) 低电量：field robot 安全 —— 解析固件给的百分比（缺失不显示 0）。
        val pct = parseBatteryPct(SessionHolder.batteryText)
        if (pct != null && pct < 20 && SessionHolder.kind != "MOCK") alerts.add("电量低 $pct%")
        if (alerts.isNotEmpty()) {
            val alertText = "⚠ " + alerts.joinToString(" · ")
            alertLine.visibility = View.VISIBLE
            if (alertLine.text.toString() != alertText) {
                alertLine.text = alertText
                alertLine.setTextColor(c(R.color.md_bad))
                alertLine.background = borderedCard(
                    Color.argb(70, 0x2A, 0x08, 0x08), c(R.color.md_bad), 8)
            }
        } else {
            alertLine.visibility = View.GONE
        }
        // 门禁可观测的驾驶帧计数：手动模式心跳在跑时增长，松手/自动模式应停止。
        // 第二行把「发给机器人的控制」显示出来（OpenBot robot app README：
        // 「The controls that are sent to the robot are displayed on the right side」）。
        // 文本必然随时间变化（心跳计数在涨），故每秒一次 setText 不可避免会发射
        // TYPE_VIEW_TEXT_CHANGED；tick 已节流到 1500ms，使相邻事件间隔稳定 >1000ms，
        // 给 uiautomator dump 留出 1000ms 静默窗（否则报 could not get idle state）。
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
            // 🔴 节流到 1500ms：uiautomator dump 要求连续 1000ms 无无障碍事件才能取层级
            // （UiAutomation.waitForIdle(1000,10000)，usespectra.dev 一手核验）。1000ms 的心跳
            // 计数每秒刷新会恰好卡在边界、抖动即失败；1500ms 稳定留出 >1000ms 静默窗，
            // 既不影响真机可读性（遥测 1.5Hz 足够），又让门禁可稳定 dump。
            ui.postDelayed(this, 1_500)
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
        // 视觉 token：与 MainActivity 的同名常量同值、同一手依据（见其 companion 注释）。
        const val TRACKING_HUD = 0.04f
        const val TABULAR_FIGURES = "tnum"
        // 6 格 = 2 行 × 3 列；「模式 / 连接」「实际速度」是真机门禁的固定断言文本，勿改。
        val HUD_LABELS = listOf("模式 / 连接", "状态帧 / 帧率", "实际速度",
            "电池", "命令→实际", "头部 °")
    }
}
