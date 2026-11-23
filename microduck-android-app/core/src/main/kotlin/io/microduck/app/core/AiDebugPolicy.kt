package io.microduck.app.core

/**
 * AI 调试通道的**唯一策略真源**（纯 JVM 常量 + 判定函数，零 Android 依赖）。
 *
 * ── 为什么要放在 core/main ──
 * 调试通道有三条消费链：① `app/src/debug/` 的 BroadcastReceiver；② core 一键自检
 * `CoreSelfTest`（Kotlin/JVM 真跑）；③ PC 侧 `tools/check_ai_debug_channel.py`（结构化静态核对）。
 * 项目铁律要求「两条消费链 import 同一函数」，否则白名单会在某一条链上悄悄漂移。
 * 把白名单放这里，①②③ 都指向同一个对象；它本身只是**惰性常量数据**，
 * 不含任何可执行入口、不开端口、不加权限 —— release 包里即使编进这些常量，
 * 也没有任何组件能触发它们（Receiver 只在 `app/src/debug/` 编译）。
 *
 * ── 为什么是「显式广播 + debug-only」而不是常驻服务 ──
 * 一手：Google Android 平台文档《后台执行限制》(developer.android.com/about/versions/oreo/background)
 *   「Apps can continue to register for **explicit broadcasts** in their manifests.」
 *   ⇒ `adb shell am broadcast -n <component>` 属于显式广播，不受 API26+ 隐式广播限制。
 * 一手：AOSP `ActivityManagerService.broadcastIntentLocked` 默认给广播加
 *   `FLAG_EXCLUDE_STOPPED_PACKAGES`（首次安装未启动 / force-stop 后的 App 收不到）
 *   ⇒ PC 侧 helper 固定带 `-f 32` = `FLAG_INCLUDE_STOPPED_PACKAGES`，或先手动启动一次 App。
 *   🔴 这是「最前置前提」，零应答时必须先查它，而不是先猜 GATT / 权限 / 蓝牙开关。
 * 一手：Google Android《BroadcastReceiver.goAsync()》官方参考 —— goAsync 后仍受约 10 s
 *   广播超时约束，必须调 `PendingResult.finish()` ⇒ 本通道所有耗时命令都设硬上限
 *   （scan 3 s / connect 6 s / mock 3 s），超时如实报 `ASYNC_PENDING` 让调用方轮询 `status`，
 *   绝不挂着 PendingResult 等一个可能不来的回调。
 *
 * ── 安全边界（写清楚，别让「AI 可控」被读成「AI 可随意驱动机器人」）──
 *  1. Receiver 只存在于 debug sourceSet ⇒ release 包 `aapt dump xmltree` 里没有这个组件。
 *  2. 命令白名单 + RPC 方法白名单；`rpc` 只发**只读**方法，禁止一切会让实体机器人动起来、
 *     改配置、发起网络连接的调用（`robot.move` / `robot.do` / `robot.enable` /
 *     `robot.loadPolicy` / `net.connect` / `system.authenticate` …）。
 *  3. 结果只写 Logcat（固定 TAG 单行 JSON），不建 socket、不监听端口、不新增权限。
 *  4. 通道本身**不产生验收结论**：`status/scan/rpc` 返回的是 `COLLECTED` 级观测值，
 *     绝不写 `PASS`；真机 GATT 握手成功与否仍由既有的 `BA-X-5` / `board_acceptance`
 *     证据链判定（项目铁律 `UNVERIFIED != PASS`、`COLLECTED != PASS`）。
 */
object AiDebugPolicy {

    /** Logcat 固定 TAG；`adb logcat -s MicroDuckAiDebug` 即可只读 AI 通道输出。 */
    const val TAG = "MicroDuckAiDebug"

    const val ACTION = "io.microduck.app.action.AI_DEBUG"
    const val RECEIVER_FQCN = "io.microduck.app.AiDebugReceiver"
    /** `am broadcast -n` 用的显式组件名（`applicationId/相对类名`）。 */
    const val COMPONENT = "io.microduck.app/.AiDebugReceiver"
    const val PACKAGE = "io.microduck.app"

    const val EXTRA_CMD = "cmd"
    const val EXTRA_RID = "rid"
    const val EXTRA_ARG = "arg"
    const val EXTRA_METHOD = "method"
    const val EXTRA_PARAMS_JSON = "params_json"

    /** 结构化结果契约版本；PC 侧 helper 据此拒收格式不认识的行。 */
    const val RESULT_SCHEMA = 1

    const val SCAN_WINDOW_MS = 3_000L
    const val CONNECT_GATT_TIMEOUT_MS = 6_000L
    const val CONNECT_WAIT_MS = 8_000L
    const val MOCK_WAIT_MS = 3_000L
    /** Logcat 单条上限（Android 约 4 KiB/条），超出即截断，避免 JSON 被逐段切开。 */
    const val MAX_RESULT_CHARS = 3_200

    /** 允许的命令。任何未列在这里的 cmd 一律拒绝（不是「忽略」，要回一条结构化错误）。 */
    val COMMANDS: Set<String> = linkedSetOf(
        "help", "status", "scan", "connect", "mock", "rpc", "disconnect",
        // 2026-11-15：只读硬件监控报告（温度/电量/通信/异常部位），不发 RPC、不改状态。
        "monitor",
        // 2026-11-21 调试能力补齐（全部只读，不产出 PASS）：
        //  gatttrace   = GATT 环形轨迹 + 最近建链失败原因（定位掉线/连不上）
        //  rootcause   = 连接失败聚合诊断（会话/lastError/GATT 轨迹/板端 logs 提示）
        //  wifidiag    = 本机 Wi-Fi SSID/定位开关/权限诊断（定位"取手机网络"读不到）
        //  snapshot    = 会话+监控+网络+更新聚合快照，一次拿全少往返
        "gatttrace", "rootcause", "wifidiag", "snapshot",
    )

    /** `scan` 命令允许的最大扫描窗口（ms）；AI 可传 --es arg <ms> 加长以抓间歇广播。 */
    const val SCAN_WINDOW_MAX_MS = 20_000L

    /**
     * `rpc` 命令允许调用的 JSON-RPC 方法：**只读白名单**。
     * 全部取自 [Method] 常量（不是手写字符串），避免方法名漂移后白名单变成死字符串。
     * 注意：`Method.NET_SCAN` / `Method.UPDATE_CHECK` / `Method.HELLO` 虽在
     * `RobotSession.isReadOnly()` 里被判为可重放，但它们会触发扫描/网络/握手副作用，
     * 故**刻意不进**调试白名单。
     */
    val READ_ONLY_METHODS: Set<String> = linkedSetOf(
        Method.SYSTEM_INFO,
        Method.ROBOT_HEALTH,
        Method.ROBOT_POLICIES,
        Method.ROBOT_MODEL,
        Method.ROBOT_MODEL_API,
        Method.ROBOT_REMOTE_SESSION_ACTIVE,
        Method.NET_STATUS,
        Method.UPDATE_STATUS,
        Method.SYSTEM_LOGS,
    )

    /**
     * `snapshot` 聚合快照实际读取的只读方法**子集**。
     *
     * 🔴 为什么不是直接用 [READ_ONLY_METHODS] 全集：广播 goAsync 硬预算约 10 s，
     * snapshot 对每个方法做一次 6 s 有界 RPC；全集 9 个方法在慢链路上会撑爆预算触发 ANR。
     * 这里冻结 4 个最关键诊断面（系统信息/健康/网络/更新状态），逐项仍经 isRpcAllowed 复核。
     * 不变式（门禁锁死）：SNAPSHOT_METHODS ⊆ READ_ONLY_METHODS，也不得含任何 FORBIDDEN_METHODS。
     */
    val SNAPSHOT_METHODS: List<String> = listOf(
        Method.SYSTEM_INFO,
        Method.ROBOT_HEALTH,
        Method.NET_STATUS,
        Method.UPDATE_STATUS,
    )

    /**
     * 明确禁止的高风险方法。**不参与放行判定**（放行只看 [READ_ONLY_METHODS]），
     * 它是负对照锚：core 自检与静态检查器都断言「禁止集合 ∩ 放行集合 == ∅」，
     * 一旦有人把 `robot.move` 加进白名单，检查必须变红。
     */
    val FORBIDDEN_METHODS: Set<String> = linkedSetOf(
        Method.ROBOT_DO,
        Method.ROBOT_MOVE,
        Method.ROBOT_ENABLE,
        Method.ROBOT_INIT,
        Method.ROBOT_HEAD,
        Method.ROBOT_LOOK,
        Method.ROBOT_LOAD_POLICY,
        Method.NET_CONNECT,
        Method.SYSTEM_AUTHENTICATE,
        Method.UPDATE_CHECK,
        Method.NET_SCAN,
        Method.ROBOT_SUBSCRIBE,
        Method.ROBOT_STATE,
    )

    fun isCommandAllowed(cmd: String?): Boolean = cmd != null && cmd in COMMANDS
    fun isRpcAllowed(method: String?): Boolean = method != null && method in READ_ONLY_METHODS

    /** 结构化结果的固定字段；两条输出链（Receiver / PC helper）共用，避免字段名漂移。 */
    object Field {
        const val SCHEMA = "v"
        const val RID = "rid"
        const val CMD = "cmd"
        const val OK = "ok"
        const val PHASE = "phase"
        const val REASON = "reason"
        const val TS_MS = "ts_ms"
        const val BUILD = "build"
        const val EVIDENCE = "evidence"
        const val NEXT = "next"
    }
}
