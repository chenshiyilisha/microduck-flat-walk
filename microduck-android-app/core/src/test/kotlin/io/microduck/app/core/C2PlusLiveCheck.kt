package io.microduck.app.core

import com.google.gson.JsonObject
import java.net.Socket
import java.util.concurrent.atomic.AtomicInteger

/**
 * C2+ 活体验证 —— 把 core 会话层接到**真** `robotd --sim`，且背后有 Windows `body_server`
 * 驱动 50 Hz 控制循环，因此 `robot.state` 通知流是真的（C2 没起 body_server ⇒ ticks=0、无流）。
 *
 * 与 C2LiveCheck 的差别：C2 只验「跨版本共通的传输/会话语义」，这里验**会话层最核心的
 * 订阅能力**：真通知帧的结构/时序/量级、订阅过滤、重复订阅不叠加、以及**断链→重连→
 * 自动重订阅→通知流恢复**。
 *
 * 证据边界（必须随结果一起读，别外推）：
 *  - 对端是 **B 代 DuckBuddy-main，API_VERSION=16 / daemon 0.10.0**（WSL2 里已编译好的真 Rust
 *    进程），不是 fanhao API40；body 是 Windows 的 MuJoCo `body_server`，不是真机总线。
 *    ⇒ 证明的是「会话层 ↔ 真固件的 NDJSON 状态流契约」，**不证明** fanhao 特有方法面、
 *    真机 BLE GATT 时序、真机 50 Hz 抖动或传感器真实性。
 *  - relay 数据面**零 canned**：只做 AF_UNIX↔TCP 字节转发。断链由**独立控制端口**注入，
 *    只关 socket、不注入任何字节/应答（一手依据 Shopify Toxiproxy 的独立控制面 +
 *    `reset_peer`/`limit_data` toxic；同型于本项目 LocalRelayServer.dropTimes）。
 *  - 固件的订阅是 **per-connection**（`robotd/src/main.rs:3366-3371` 里 `states`/`decimate`
 *    是 `handle()` 的局部变量；`main.rs:3499-3506` 再次订阅=替换速率不叠加）。
 *    所以连接一断订阅即失效：重连后若会话层没有重发 `robot.subscribe`，一帧都不会有。
 *    这条硬事实让「重连后通知流恢复」成为重订阅逻辑的真证据，而不是夹具的善意应答。
 *
 * 用法：java -cp build/fat io.microduck.app.core.C2PlusLiveCheck <host> <port> <controlPort>
 */
object C2PlusLiveCheck {
    private var passed = 0
    private var failed = 0

    private fun check(name: String, cond: Boolean, detail: () -> String = { "" }) {
        if (cond) { passed++; println("  PASS  $name") }
        else { failed++; println("  FAIL  $name  ${detail()}") }
    }

    // Gson JsonObject 没有 opt*（真编译踩过）；一律走带 JsonNull 防护的辅助函数。
    private fun num(o: JsonObject?, key: String): Double? = try {
        o?.get(key)?.takeIf { !it.isJsonNull }?.asDouble
    } catch (_: Exception) { null }

    private fun child(o: JsonObject?, key: String): JsonObject? = try {
        o?.getAsJsonObject(key)?.takeIf { !it.isJsonNull }
    } catch (_: Exception) { null }

    private fun arrLen(o: JsonObject?, key: String): Int = try {
        o?.getAsJsonArray(key)?.size() ?: -1
    } catch (_: Exception) { -1 }

    private fun text(o: JsonObject?, key: String): String? = try {
        o?.get(key)?.takeIf { !it.isJsonNull }?.asString
    } catch (_: Exception) { null }

    /** 线程安全快照收集器（通知回调在 transport 读线程，不能裸 ArrayList）。 */
    private class Frames {
        private val lock = Any()
        private val list = ArrayList<JsonObject>()
        fun add(o: JsonObject) { synchronized(lock) { list.add(o) } }
        fun snapshot(): List<JsonObject> = synchronized(lock) { list.toList() }
        fun size(): Int = synchronized(lock) { list.size }
    }

    private class Events {
        private val lock = Any()
        private val list = ArrayList<RobotSession.Event>()
        fun add(e: RobotSession.Event) { synchronized(lock) { list.add(e) } }
        fun snapshot(): List<RobotSession.Event> = synchronized(lock) { list.toList() }
        fun stateNotifications(): Int = snapshot().count {
            it is RobotSession.Event.Notification && it.method == Method.ROBOT_STATE
        }
        fun sawReconnecting(): Boolean = snapshot().any {
            it is RobotSession.Event.StateChanged && it.to == RobotSession.State.RECONNECTING
        }
    }

    /**
     * 稳定态判据，不取瞬时 READY：重连中间态可能短暂 READY 又掉，瞬时断言会 flaky。
     * 一手依据（项目内已查）：K8s successThreshold / Jitsi stable-connection-threshold /
     * Apollo stability=5×delay ⇒ 连续 8×100ms 稳定 READY 才算恢复。
     */
    private fun waitStable(s: RobotSession, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        var stable = 0
        while (System.currentTimeMillis() < deadline) {
            if (s.state == RobotSession.State.READY) stable++ else stable = 0
            if (stable >= 8) return true
            Thread.sleep(100)
        }
        return false
    }

    private fun sleepCollect(ms: Long) { Thread.sleep(ms) }

    @JvmStatic
    fun main(args: Array<String>) {
        val host = args.getOrNull(0) ?: "127.0.0.1"
        val port = args.getOrNull(1)?.toIntOrNull() ?: 7788
        val controlPort = args.getOrNull(2)?.toIntOrNull() ?: 7789
        println("=" * 72)
        println("C2+ LIVE CHECK  |  core -> zero-canned relay -> REAL robotd --sim + body_server")
        println("target=$host:$port  control=$controlPort  |  firmware: B-gen API16 / daemon 0.10.0")
        println("=" * 72)

        // ---- A. 主会话：握手 + 真控制循环 ----
        val sA = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            maxReconnectAttempts = 4)
        val evA = Events()
        sA.onEvent { evA.add(it) }
        val okA = sA.connect(ConnectTarget.Tcp(host, port))
        check("真固件握手到 READY(TCP/AUTO 跳过 BLE 认证)", okA && sA.state == RobotSession.State.READY) {
            "ok=$okA state=${sA.state}"
        }
        if (!okA) {
            println("C2PLUS RESULT: $passed passed, ${failed + 1} failed (abi-fatal: no handshake)")
            kotlin.system.exitProcess(1)
        }

        val health = sA.call(Method.ROBOT_HEALTH)
        val hb = health.getOrNull()
        val loop = child(hb, "control_loop")
        val ticks = num(loop, "ticks")
        val achievedHz = num(loop, "achieved_hz")
        check("探针通道自检:真 robot.health 有应答", health.isSuccess && hb != null) { "r=$health" }
        check("body_server 真驱动控制循环(ticks>0，非 C2 空跑)", ticks != null && ticks > 0.0) { "ticks=$ticks resp=$hb" }
        check("负对照:有仿真体时 healthy=true(与 C2 的 false 形成对照)",
            hb?.get("healthy")?.takeIf { !it.isJsonNull }?.asBoolean == true) { "resp=$hb" }
        check("50 Hz 量级对(40..60，问量级不问对错)", achievedHz != null && achievedHz in 40.0..60.0) {
            "achieved_hz=$achievedHz"
        }

        // ---- B. 订阅前负对照 ----
        sleepCollect(800)
        val before = evA.stateNotifications()
        check("订阅前零 robot.state(对齐 upstream no_subscribers_means_no_frames)", before == 0) {
            "notifications=$before"
        }

        // ---- C. 真通知流 ----
        val framesA = Frames()
        val wrong = AtomicInteger(0)
        val hSub = sA.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 5),
            streamMethod = Method.ROBOT_STATE) { framesA.add(it) }
        sleepCollect(2_000)
        val n1 = framesA.size()
        check("订阅后收到真 robot.state 帧(2s @5Hz，量级 >=5)", n1 >= 5) { "frames=$n1" }

        // 同 key 再注册一个「错误 streamMethod」监听：会再发一次 robot.subscribe，
        // 真固件语义是「替换速率不叠加」（main.rs:3499-3506），所以速率不该翻倍；
        // 同时该回调必须一帧收不到 ⇒ 证明 streamMethod 过滤不是全量乱发。
        val hWrong = sA.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 5),
            streamMethod = "robot.not_a_real_state") { wrong.incrementAndGet() }
        sleepCollect(2_000)
        val n2 = framesA.size() - n1
        check("重复订阅不叠加(2s 帧数未翻倍)", n2 <= (n1 * 1.6).toInt() + 2) {
            "first_window=$n1 second_window=$n2 (叠加应约 ${n1 * 2})"
        }
        check("负对照:错误 streamMethod 的回调收不到帧", wrong.get() == 0) { "wrong=${wrong.get()}" }
        check("事件流与过滤后帧数一致(过滤没丢帧)",
            evA.stateNotifications() == framesA.size()) {
            "events=${evA.stateNotifications()} frames=${framesA.size()}"
        }

        val snap = framesA.snapshot()
        val first = snap.firstOrNull()
        check("状态帧结构含 t/loop/move/joints/policy/odom", first != null &&
            num(first, "t") != null && child(first, "loop") != null &&
            child(first, "move") != null && arrLen(first, "joints") > 0 &&
            text(first, "policy") != null && child(first, "odom") != null) { "first=$first" }
        check("状态帧 joints=15(真固件 NUM_JOINTS，量级对)", arrLen(first, "joints") == 15) {
            "joints=${arrLen(first, "joints")}"
        }
        val ts = snap.mapNotNull { num(it, "t") }
        check("t 单调递增(问「动没动」而非「对不对」)",
            ts.size >= 5 && ts.zipWithNext().all { (a, b) -> a < b }) { "ts=$ts" }
        val frameHz = num(child(first, "loop"), "hz")
        check("帧内 loop.hz ≈ 50(控制循环真在跑)", frameHz != null && frameHz in 40.0..60.0) {
            "loop.hz=$frameHz"
        }
        check("负对照:policy 不是空串(真固件填了策略标签)",
            !text(first, "policy").isNullOrEmpty()) { "policy=${text(first, "policy")}" }

        // ---- D. 对照会话：连同一 relay，但**不订阅** ----
        val sB = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            maxReconnectAttempts = 4)
        val evB = Events()
        sB.onEvent { evB.add(it) }
        val okB = sB.connect(ConnectTarget.Tcp(host, port))
        check("对照会话 sB 连上真固件(不订阅)", okB && sB.state == RobotSession.State.READY) {
            "ok=$okB state=${sB.state}"
        }
        sleepCollect(500)
        check("负对照:sB 未订阅 ⇒ 零 robot.state", evB.stateNotifications() == 0) {
            "sB_notifications=${evB.stateNotifications()}"
        }

        // ---- E. 拔网线 → 重连 → 重订阅 → 通知流恢复 ----
        val dropped = try {
            Socket(host, controlPort).use { }   // 独立控制面：连一下即关，relay 只关 socket
            true
        } catch (e: Exception) { println("  (control trigger failed: $e)"); false }
        check("断链注入触发成功(控制端口可达)", dropped)

        val stableA = waitStable(sA, 9_000)
        val stableB = waitStable(sB, 9_000)
        check("sA 断链后稳定恢复到 READY", stableA && sA.state == RobotSession.State.READY) {
            "stable=$stableA state=${sA.state} events=${evA.snapshot().takeLast(8)}"
        }
        check("sB 也稳定恢复 READY(对照有效)", stableB && sB.state == RobotSession.State.READY) {
            "stable=$stableB state=${sB.state}"
        }
        check("负对照:会话层确实走过 RECONNECTING(不是没断)", evA.sawReconnecting()) {
            "events=${evA.snapshot().map { it::class.simpleName }}"
        }

        // 基线取在「稳定 READY 之后」：断链瞬间内核缓冲里可能还有几帧迟到帧，
        // 若用断链前的计数当基线，这些旧帧可能被误算成「恢复」。只统计恢复后的新帧。
        val afterStable = framesA.size()
        sleepCollect(2_500)
        val recovered = framesA.size() - afterStable
        check("🔑 重连后真通知流恢复(>=5 帧/2.5s)", recovered >= 5) {
            "afterStable=$afterStable now=${framesA.size()} delta=$recovered — " +
                "真固件订阅是 per-connection，不重发 robot.subscribe 就会是 0 帧"
        }
        check("🔑 负对照:sB 没订阅 ⇒ 重连后仍零帧(证明不是无差别广播)",
            evB.stateNotifications() == 0) { "sB_notifications=${evB.stateNotifications()}" }

        // ---- F. relay 没偷造 canned 认证的负对照（沿用 C2 的硬门槛）----
        val sC = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            authPolicy = RobotSession.AuthPolicy.REQUIRED, maxReconnectAttempts = 1)
        val okC = sC.connect(ConnectTarget.Tcp(host, port))
        check("负对照:强制 REQUIRED 在真 robotd 上握手失败", !okC &&
            sC.state != RobotSession.State.READY) { "ok=$okC state=${sC.state}" }
        sC.close()

        hSub.dispose(); hWrong.dispose()
        sA.close(); sB.close()

        println("\n--- 证据边界 ---")
        println("VERIFIED_LIVE_STATE_STREAM: 真 robotd + body_server 的 robot.state 通知流、")
        println("  帧结构/时序/50Hz 量级、streamMethod 过滤、重复订阅替换速率、")
        println("  断链→重连→自动重订阅→通知流恢复，全部由真固件产生（零 canned）。")
        println("NOT_VERIFIED: fanhao API40 特有方法面、真机 BLE GATT/bonding/CCCD 时序、")
        println("  真机总线/传感器/50Hz 抖动、驾驶与视频。B 代 API16 + MuJoCo 仿真体 ≠ 真机。")
        println("=" * 72)
        println("C2PLUS RESULT: $passed passed, $failed failed")
        println("=" * 72)
        if (failed > 0) kotlin.system.exitProcess(1)
    }

    private operator fun String.times(n: Int) = repeat(n)
}
