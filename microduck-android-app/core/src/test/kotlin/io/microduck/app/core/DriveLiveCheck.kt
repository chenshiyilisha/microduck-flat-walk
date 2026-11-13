package io.microduck.app.core

import com.google.gson.JsonObject
import java.util.concurrent.atomic.AtomicInteger

/**
 * P1 驾驶**活体验证** —— 把 core 的 `DriveController` / `JsonRpcDriveSink` 接到真
 * `robotd --sim`（背后有 Windows `body_server` 驱动 50 Hz 控制循环），验证 `robot.move`
 * 不只是「发出去没报错」，而是真固件**真的接受并应用**了速度意图。
 *
 * 一手依据（阈值与判据全部来自源码，不从实测反推）：
 *  - `duck-ipc-proto` `ROBOT_MOVE`（B代 lib.rs:308 / fanhao :608）：
 *    "Velocity twist. Continuous; send as a notification."；`MoveParams{vx,vy,vyaw}` 带
 *    `deny_unknown_fields` ⇒ 恰好三键。
 *  - B代 `robotd/src/main.rs:3483-3489`：无 id 帧直接 `apply_intent` 且**不回响应**；
 *    `:3573-3577`：`robot.move` 带 id 的 request 路径同样 `apply_intent`，回
 *    `IntentResult{accepted:true}` ⇒ 两条路径都该生效。
 *  - `:2648-2649`：`applied` / `limited_by` 存在的意义就是让客户端区分
 *    「请求了什么」和「实际被限成什么」——否则看不出 limit 与 bug 的区别。
 *  - 上游自带测试 `:5220-5270` `the_state_stream_reports_why_a_command_was_refused`：
 *    `intents.set_twist([0.4,0,0])` 后静置 > deadman(500ms) ⇒
 *    `requested == [0.4,0,0]`（请求值存活）、`applied == [0,0,0]`（stale 归零）、
 *    `limited_by` 含 `"deadman"`。**本检查把它跨进程复现，但不照抄 `applied==0`**：
 *    上游是冷启动（`twist_ema` 初值 0），本检查先稳态驱动再停发，EMA 按
 *    `cmd_alpha=0.2` 指数衰减（见 F 段注释）。这是本轮真固件抓出的判据外推陷阱。
 *  - `robotd-params/src/lib.rs:914` `deadman_ms=500`；`udp-pad.md` `timeout_ms=250`。
 *
 * 证据边界（随结果一起读）：
 *  - 对端是 **B 代 API16 / daemon 0.10.0 + MuJoCo 仿真体**，不是 fanhao API40、不是真机总线；
 *    只证跨版本共通的 `robot.move` / 状态流契约。
 *  - relay 是 `c2_relay.py`，**纯字节 AF_UNIX↔TCP 转发、零 canned**。
 *  - 只验 JSON-RPC 驾驶通道；**netpad UDP 通道在 B 代固件上不存在**（fanhao 独有），
 *    其 wire 由 CoreSelfTest [17]/[19] 在 JVM + 真 UDP socket 上验证，不在此断言。
 *  - 真机 BLE GATT / bonding / CCCD 时序、驾驶手感标定仍未验（需整机）。
 *
 * 用法：java -cp build/fat io.microduck.app.core.DriveLiveCheck <host> <port>
 */
object DriveLiveCheck {
    private var passed = 0
    private var failed = 0

    private fun check(name: String, cond: Boolean, detail: () -> String = { "" }) {
        if (cond) { passed++; println("  PASS  $name") }
        else { failed++; println("  FAIL  $name  ${detail()}") }
    }

    private fun child(o: JsonObject?, key: String): JsonObject? = try {
        o?.getAsJsonObject(key)?.takeIf { !it.isJsonNull }
    } catch (_: Exception) { null }

    private fun num(o: JsonObject?, key: String): Double? = try {
        o?.get(key)?.takeIf { !it.isJsonNull }?.asDouble
    } catch (_: Exception) { null }

    private fun arr(o: JsonObject?, key: String): List<Double> = try {
        o?.getAsJsonArray(key)?.mapNotNull { runCatching { it.asDouble }.getOrNull() } ?: emptyList()
    } catch (_: Exception) { emptyList() }

    private fun limits(o: JsonObject?, key: String): List<String> = try {
        o?.getAsJsonArray(key)?.mapNotNull { runCatching { it.asString }.getOrNull() } ?: emptyList()
    } catch (_: Exception) { emptyList() }

    /** 通知回调在 transport 读线程 ⇒ 快照收集，不能裸 ArrayList。 */
    private class Frames {
        private val lock = Any()
        private val list = ArrayList<JsonObject>()
        fun add(o: JsonObject) { synchronized(lock) { list.add(o) } }
        fun size(): Int = synchronized(lock) { list.size }
        fun since(index: Int): List<JsonObject> = synchronized(lock) {
            if (index >= list.size) emptyList() else list.subList(index, list.size).toList()
        }
        fun last(): JsonObject? = synchronized(lock) { list.lastOrNull() }
    }

    private fun requestedVx(f: JsonObject) = arr(child(f, "move"), "requested").firstOrNull()
    private fun appliedVx(f: JsonObject) = arr(child(f, "move"), "applied").firstOrNull()
    private fun limitedBy(f: JsonObject) = limits(child(f, "move"), "limited_by")

    private fun sleepCollect(ms: Long) { Thread.sleep(ms) }

    @JvmStatic
    fun main(args: Array<String>) {
        val host = args.getOrNull(0) ?: "127.0.0.1"
        val port = args.getOrNull(1)?.toIntOrNull() ?: 7788
        println("=" * 72)
        println("P1 DRIVE LIVE CHECK  |  DriveController -> robot.move -> REAL robotd --sim")
        println("target=$host:$port  |  firmware: B-gen API16 (not fanhao API40)")
        println("=" * 72)

        val s = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            maxReconnectAttempts = 3)
        val ok = s.connect(ConnectTarget.Tcp(host, port))
        check("真固件握手到 READY", ok && s.state == RobotSession.State.READY) {
            "ok=$ok state=${s.state}"
        }
        if (!ok) {
            println("DRIVE RESULT: $passed passed, ${failed + 1} failed (abi-fatal: no handshake)")
            kotlin.system.exitProcess(1)
        }

        // ---- A. 通道自检：控制循环真在跑，否则「没帧」会是假绿 ----
        val health = s.call(Method.ROBOT_HEALTH)
        val hb = health.getOrNull()
        val ticks = num(child(hb, "control_loop"), "ticks")
        val hz = num(child(hb, "control_loop"), "achieved_hz")
        check("通道自检:robot.health 有应答", health.isSuccess && hb != null) { "r=$health" }
        check("body_server 真驱动控制循环(ticks>0)", ticks != null && ticks > 0.0) { "ticks=$ticks" }
        check("50 Hz 量级对(40..60)", hz != null && hz in 40.0..60.0) { "hz=$hz" }

        val frames = Frames()
        val hSub = s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 10),
            streamMethod = Method.ROBOT_STATE) { frames.add(it) }
        sleepCollect(900)
        val nSub = frames.size()
        check("订阅后真状态流可达(0.9s @10Hz >=5 帧)", nSub >= 5) { "frames=$nSub" }

        // ---- B. 基线：完全没有驾驶意图 ⇒ requested/applied 都是 0 ----
        val base = frames.since(0)
        check("基线帧非空(负对照:防没帧假绿)", base.isNotEmpty())
        check("基线 requested 全 0", base.isNotEmpty() && base.all { (requestedVx(it) ?: -1.0) == 0.0 }) {
            "req=${base.mapNotNull { requestedVx(it) }.distinct()}"
        }
        check("基线 applied 全 0", base.isNotEmpty() && base.all { (appliedVx(it) ?: -1.0) == 0.0 })

        // ---- C. 产品代码驱动：DriveController + JsonRpcDriveSink（notification + 100ms 心跳）----
        val VX = 0.3          // maxVx=0.4 × 杆 0.75；阈值由「我们发了什么」定，不从实测取
        val sent = AtomicInteger(0)
        val drive = DriveController(
            sink = JsonRpcDriveSink(s),
            maxVx = 0.4,
            maxVyaw = 1.0,
            onSent = { sent.incrementAndGet() },
        )
        val cmd = drive.onAxes(0.0, 0.75)
        check("DriveController 映射出 vx=0.3", kotlin.math.abs(cmd.twist.vx - VX) < 1e-9) {
            "twist=${cmd.twist}"
        }
        drive.startHeartbeat()
        val atDrive = frames.size()
        sleepCollect(1_500)
        val driven = frames.since(atDrive)
        check("驱动期状态帧持续增长(1.5s @10Hz)", driven.size >= 8) { "frames=${driven.size}" }
        check("🔑 真固件收到 notification:requested≈0.3(>=3 帧)",
            driven.count { kotlin.math.abs((requestedVx(it) ?: -1.0) - VX) < 0.02 } >= 3) {
            "req=${driven.mapNotNull { requestedVx(it) }.distinct().take(8)}"
        }
        check("🔑 真固件应用了意图:applied>0.05(不是只记录不执行)",
            driven.any { (appliedVx(it) ?: 0.0) > 0.05 }) {
            "applied=${driven.mapNotNull { appliedVx(it) }.distinct().take(8)}"
        }
        check("负对照:持续刷新期不含 deadman limit", driven.none { "deadman" in limitedBy(it) }) {
            "limits=${driven.flatMap { limitedBy(it) }.distinct()}"
        }
        check("心跳确实在发包(>=8 帧/1.5s)", sent.get() >= 8) { "sent=${sent.get()}" }
        check("负对照:驱动期最后一帧 requested 仍非零",
            (driven.lastOrNull()?.let { requestedVx(it) } ?: 0.0) > 0.2)

        // ---- D. 松手归零：零帧必须被真固件接受 ----
        drive.release()
        // 🔴 基线不能取在动作瞬间：状态帧 10Hz 异步推送，发零帧时可能还有一帧 0.3
        // 在途，会被算进「松手后」窗口（连跑 3 次抓到 1 次 flaky：req=[0.3, 0.0]）。
        // 与 C2+ 同一稳定态判据（Jitsi stable-connection-threshold / K8s
        // successThreshold）：先等 >2 个帧周期让在途帧落地，再取基线。
        sleepCollect(250)
        val atRelease = frames.size()
        sleepCollect(650)
        val released = frames.since(atRelease)
        check("release 后仍有状态帧(>=3)", released.size >= 3) { "frames=${released.size}" }
        check("🔑 松手后 requested 归零(零 notification 生效)",
            released.isNotEmpty() && released.all { (requestedVx(it) ?: -1.0) == 0.0 }) {
            "req=${released.mapNotNull { requestedVx(it) }.distinct()}"
        }
        drive.stop()
        check("负对照:stop 后通道不再被 sink 关闭(会话仍 READY)",
            s.state == RobotSession.State.READY) { "state=${s.state}" }

        // ---- E. 带 id 的 request 路径（一手 :3522 / :3573-3577 双路径兼容）----
        val reqResult = s.call(Method.ROBOT_MOVE, Twist(vx = 0.2).params(), replayable = false)
        check("带 id 的 robot.move request 也成功且 accepted=true",
            reqResult.isSuccess && reqResult.getOrNull()?.get("accepted")?.asBoolean == true) {
            "r=$reqResult"
        }
        val atReq = frames.size()
        sleepCollect(450)
        val afterReq = frames.since(atReq)
        check("🔑 request 路径同样改变 requested≈0.2",
            afterReq.any { kotlin.math.abs((requestedVx(it) ?: -1.0) - 0.2) < 0.02 }) {
            "req=${afterReq.mapNotNull { requestedVx(it) }.distinct()}"
        }

        // ---- F. deadman：把上游单测 :5220-5270 搬成跨进程活体断言 ----
        // 关键：**只停发、不发零**。若发零，requested 也会变 0，就分不清是客户端归零
        // 还是固件 deadman 归零 —— 正是 lib.rs:2648 说 applied/limited_by 存在的原因。
        val stale = Twist(vx = VX).params()
        repeat(8) { s.notify(Method.ROBOT_MOVE, stale); Thread.sleep(100) }
        val atStale = frames.size()
        sleepCollect(950)   // > deadman_ms(500) + 帧窗口余量
        // 🔴 判据陷阱（本轮真固件实测抓出）：上游单测 :5267 断言 `applied == [0,0,0]` 只在
        // **冷启动**成立——它先 `set_twist(0.4)` 却从没驱动过控制循环，`twist_ema` 初值就是 0。
        // 本检查是「稳态驱动到 0.3 之后才停发」，EMA 已有历史值；deadman 把 target 置 0 后
        // 按 `ema += cmd_alpha * (0 - ema)` 递推（main.rs:2444，`cmd_alpha=0.2`，
        // robotd-params/src/lib.rs:1111）⇒ 每 20ms tick ×0.8，是**指数衰减**而非瞬间归零。
        // 实测 0.0403→0.0132→0.0035→0.0011，比值 ≈0.8^5=0.328（状态帧 10Hz = 5 ticks/帧）。
        // 故断言取「单调衰减 + 衰减比 + 最终量级」，并把 `limited_by` 点名 deadman 作为
        // 固件确实进入限幅状态的证据。把冷启动单测的 ==0 外推到这里是判据错误，不是产品 bug。
        val deadmanFrames = frames.since(atStale).filter { "deadman" in limitedBy(it) }
        check("deadman 窗口有状态帧(>=4)", deadmanFrames.size >= 4) {
            "frames=${deadmanFrames.size} all=${frames.since(atStale).size}"
        }
        val ap = deadmanFrames.mapNotNull { appliedVx(it) }
        check("🔑 requested 仍是 0.3(客户端请求值存活到流里)",
            deadmanFrames.isNotEmpty() && deadmanFrames.all {
                kotlin.math.abs((requestedVx(it) ?: -1.0) - VX) < 0.02
            }) { "req=${deadmanFrames.mapNotNull { requestedVx(it) }.distinct()}" }
        check("🔑 applied 单调衰减(cmd_alpha=0.2 的 EMA，不是瞬间归零)",
            ap.size >= 4 && ap.zipWithNext().all { (a, b) -> b < a }) { "applied=$ap" }
        check("🔑 衰减比符合 0.8^5≈0.328(50Hz tick / 10Hz 状态帧)",
            ap.size >= 4 && ap.zipWithNext().all { (a, b) -> a <= 0.0 || b / a < 0.6 }) {
            "ratios=${ap.zipWithNext().map { (a, b) -> if (a > 0) b / a else 0.0 }}"
        }
        check("🔑 applied 衰减 >99%(0.8^47≈2.8e-5，950ms 窗口)",
            ap.isNotEmpty() && ap.last() < VX * 0.01) { "last=${ap.lastOrNull()} vx=$VX" }
        check("🔑 limited_by 点名 deadman(不是静默忽略)",
            deadmanFrames.isNotEmpty()) { "frames=${deadmanFrames.size}" }
        check("负对照:驱动期 applied 不衰减到近零(与 deadman 期形成对照)",
            driven.any { (appliedVx(it) ?: 0.0) > VX * 0.1 }) {
            "driven_applied=${driven.mapNotNull { appliedVx(it) }.distinct().take(6)}"
        }
        // 负对照：把意图显式清零后，requested 也必须跟着变 0 ⇒ 证明前面 0.3 不是固件常量
        s.notify(Method.ROBOT_MOVE, Twist.ZERO.params())
        sleepCollect(250)   // 同上：让在途的 0.3 帧落地后再取基线
        val atZero = frames.size()
        sleepCollect(450)
        val zeroed = frames.since(atZero)
        check("负对照:显式发零帧后 requested 变 0",
            zeroed.isNotEmpty() && zeroed.all { (requestedVx(it) ?: -1.0) == 0.0 }) {
            "req=${zeroed.mapNotNull { requestedVx(it) }.distinct()}"
        }

        hSub.dispose()
        s.close()

        println("\n--- 证据边界 ---")
        println("VERIFIED_LIVE_DRIVE: 真 robotd 通过 notification 与 request 两条路径接受 robot.move，")
        println("  requested/applied 随意图变化、松手零帧生效、deadman 在固件侧限幅并点名原因")
        println("NOT_VERIFIED: fanhao API40 特有方法面、netpad UDP 通道(B 代没有)、真机 BLE GATT")
        println("  bonding/CCCD 时序、真机传感器与 50Hz 抖动、驾驶手感标定(必须整机测)。")
        println("=" * 72)
        println("DRIVE RESULT: $passed passed, $failed failed")
        println("=" * 72)
        if (failed > 0) kotlin.system.exitProcess(1)
    }

    private operator fun String.times(n: Int) = repeat(n)
}
