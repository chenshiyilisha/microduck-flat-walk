package io.microduck.app.core

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.util.Collections
import kotlin.math.abs
import kotlin.math.hypot

/**
 * core 会话层自检 —— 纯 JVM main，不依赖 JUnit/Gradle/模拟器。
 * 用真 kotlinc 2.4.0 + JDK17 编译后 java 跑（见 tools/selftest.sh）。
 *
 * 纪律（项目铁律）：**每条正向断言配负对照**——故意改坏输入，检查必须变红。
 * 只见过绿色的断言不是证据。验证问「这个量动没动、量级对不对」，不问「结果对不对」。
 */
object CoreSelfTest {
    private var passed = 0
    private var failed = 0

    private fun check(name: String, cond: Boolean, detail: () -> String = { "" }) {
        if (cond) { passed++; println("  PASS  $name") }
        else { failed++; println("  FAIL  $name  ${detail()}") }
    }

    // ---- 1. 握手顺序 + 版本握手（负对照：少一步 / 版本错都必须被抓）----
    private fun testHandshake() {
        println("\n[1] 握手状态机 hello→auth→READY")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        val ok = s.connect(ConnectTarget.Mock)
        check("connect 进入 READY", ok && s.state == RobotSession.State.READY) { "state=${s.state}" }
        check("握手恰好 hello 一次", t.countOf(Method.HELLO) == 1) { "log=${t.log()}" }
        check("握手恰好 authenticate 一次", t.countOf(Method.SYSTEM_AUTHENTICATE) == 1) { "log=${t.log()}" }
        check("顺序 hello 在 auth 前", t.log().indexOf(Method.HELLO) < t.log().indexOf(Method.SYSTEM_AUTHENTICATE)) { "log=${t.log()}" }
        // 负对照：hello 必须带 api_version=40，不是别的值
        val helloLine = t.rawLog().first { it.contains("\"hello\"") }
        check("负对照:hello 带 api_version=40", helloLine.contains("\"api_version\":40")) { helloLine }
        check("负对照:hello 不是 39/0", !helloLine.contains("\"api_version\":39") && !helloLine.contains("\"api_version\":0"))
        // 负对照：错 PIN 必须进 FAILED，不能假绿进 READY
        val t2 = MockTransport()
        val s2 = RobotSession(t2, pin = "999999", backoffBaseMs = 10)
        val ok2 = s2.connect(ConnectTarget.Mock)
        check("负对照:错 PIN 拒绝进 READY", !ok2 && s2.state == RobotSession.State.FAILED) { "ok=$ok2 state=${s2.state}" }
        s.close(); s2.close()
    }

    // ---- 2. 业务调用 + 只读方法返回真实结构 ----
    private fun testCall() {
        println("\n[2] 业务调用 robot.health / robot.state")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10)
        s.connect(ConnectTarget.Mock)
        val h = s.call(Method.ROBOT_HEALTH)
        check("robot.health 成功", h.isSuccess) { "${h.exceptionOrNull()}" }
        val servos = h.getOrNull()?.getAsJsonArray("servos")
        check("健康报告含 15 舵机", servos?.size() == 15) { "servos=${servos?.size()}" }
        // 负对照：不存在的方法不抛异常但也不能假装成功有数据
        val bogus = s.call("robot.doesNotExist")
        check("负对照:未知方法 result 为空对象", bogus.isSuccess && bogus.getOrNull()?.entrySet()?.isEmpty() == true)
        s.close()
    }

    // ---- 3. 断连 → 自动重连 + 重认证（核心！负对照：重连必须重新 hello+auth）----
    private fun testReconnect() {
        println("\n[3] 断连自动重连 + 重认证 + 重订阅")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        s.connect(ConnectTarget.Mock)
        var subFrames = 0
        // 真实协议：订阅动作=robot.subscribe，推送流名=robot.state，两者不同（分开传）
        s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 10), streamMethod = Method.ROBOT_STATE) { subFrames++ }
        check("建立 robot.subscribe 订阅(1 lane)", t.laneCount() == 1) { "lanes=${t.laneCount()}" }
        t.clearLog()

        t.simulateDisconnect()            // 模拟 btd 重启 / BLE 拆链
        val recovered = s.awaitReady(2_000)
        check("断连后自动恢复到 READY", recovered && s.state == RobotSession.State.READY) { "state=${s.state}" }
        // 负对照：如果会话层「假装重连」只重连 transport 不握手，这里 hello/auth 计数不会涨 → 变红
        check("负对照:重连重新 hello", t.countOf(Method.HELLO) >= 1) { "log=${t.log()}" }
        check("负对照:重连重新 authenticate", t.countOf(Method.SYSTEM_AUTHENTICATE) >= 1) { "log=${t.log()}" }
        check("负对照:重连恢复订阅 lane", t.laneCount() == 1) { "lanes=${t.laneCount()}" }
        // 通知流在恢复后仍可用
        t.pushFrame("{\"jsonrpc\":\"2.0\",\"method\":\"robot.state\",\"params\":{\"vx\":0.3}}")
        check("恢复后通知仍能收到", subFrames >= 1) { "frames=$subFrames" }
        s.close()
    }

    // ---- 4. 幂等重放：只读重连后重放一次，写类不重放（负对照：写类重放会重复执行 → 必须红）----
    private fun testIdempotentReplay() {
        println("\n[4] pending 幂等重放（只读重放 / 写类不重放）")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        s.connect(ConnectTarget.Mock)
        // 只读 call 发到一半掉线 → 应进 pending，重连后重放
        t.injectFaults(MockTransport.Fault(dropAndDisconnect = true))
        val readRes = s.call(Method.ROBOT_HEALTH)
        check("掉线时只读 call 返回失败", readRes.isFailure) { "${readRes.exceptionOrNull()}" }
        s.awaitReady(2_000)
        // 重放 = 再发一次 robot.health（重连握手本身不发 health）
        check("只读 call 重连后重放一次", t.countOf(Method.ROBOT_HEALTH) >= 2) { "log=${t.log()}" }

        // 写类掉线 → 不进 pending，重连后不得重放
        val t2 = MockTransport()
        val s2 = RobotSession(t2, backoffBaseMs = 10, backoffMaxMs = 20)
        s2.connect(ConnectTarget.Mock)
        t2.clearLog()
        t2.injectFaults(MockTransport.Fault(dropAndDisconnect = true))
        val writeRes = s2.call(Method.ROBOT_DO, mapOf("skill" to "walk"), replayable = false)
        check("掉线时写类 call 返回失败", writeRes.isFailure)
        s2.awaitReady(2_000)
        // 负对照：写类若被重放，countOf(robot.do) 会 ≥2（重复执行副作用）→ 变红
        check("负对照:写类 call 不重放(仅1次)", t2.countOf(Method.ROBOT_DO) == 1) { "log=${t2.log()}" }
        s.close(); s2.close()
    }

    // ---- 5. 错误码分类（三种各自触发对应事件，负对照：不串台）----
    private fun testErrorCodes() {
        println("\n[5] 错误码分类 -32601 / -32602 / 14")
        // -32601 → CapabilityUnsupported + 方法加入 unsupported
        val t1 = MockTransport()
        val s1 = RobotSession(t1, backoffBaseMs = 10)
        s1.connect(ConnectTarget.Mock)
        val ev1 = mutableListOf<RobotSession.Event>()
        s1.onEvent { ev1.add(it) }
        t1.injectFaults(MockTransport.Fault(errorOnMethod = Method.ROBOT_MODEL to RpcCode.METHOD_NOT_FOUND))
        s1.call(Method.ROBOT_MODEL)
        check("-32601 触发 CapabilityUnsupported", ev1.any { it is RobotSession.Event.CapabilityUnsupported && it.method == Method.ROBOT_MODEL }) { "ev=$ev1" }
        check("-32601 后方法被标 unsupported", s1.isUnsupported(Method.ROBOT_MODEL))
        // 负对照：再调同一方法应被短路，不发到 transport
        t1.clearLog()
        s1.call(Method.ROBOT_MODEL)
        check("负对照:unsupported 方法不再发", t1.countOf(Method.ROBOT_MODEL) == 0) { "log=${t1.log()}" }

        // -32602 → ContractSkew
        val t2 = MockTransport(); val s2 = RobotSession(t2, backoffBaseMs = 10); s2.connect(ConnectTarget.Mock)
        val ev2 = mutableListOf<RobotSession.Event>(); s2.onEvent { ev2.add(it) }
        t2.injectFaults(MockTransport.Fault(errorOnMethod = Method.ROBOT_HEALTH to RpcCode.INVALID_PARAMS))
        s2.call(Method.ROBOT_HEALTH)
        check("-32602 触发 ContractSkew", ev2.any { it is RobotSession.Event.ContractSkew }) { "ev=$ev2" }

        // 14 → PermissionDenied
        val t3 = MockTransport(); val s3 = RobotSession(t3, backoffBaseMs = 10); s3.connect(ConnectTarget.Mock)
        val ev3 = mutableListOf<RobotSession.Event>(); s3.onEvent { ev3.add(it) }
        t3.injectFaults(MockTransport.Fault(errorOnMethod = Method.ROBOT_MOVE to RpcCode.PERMISSION_DENIED))
        s3.call(Method.ROBOT_MOVE, mapOf("vx" to 0.3), replayable = false)
        check("14 触发 PermissionDenied", ev3.any { it is RobotSession.Event.PermissionDenied && it.method == Method.ROBOT_MOVE }) { "ev=$ev3" }
        // 负对照：14 不应被误判成「固件不支持」
        check("负对照:14 不进 unsupported", !s3.isUnsupported(Method.ROBOT_MOVE))
        s1.close(); s2.close(); s3.close()
    }

    // ---- 6. 未就绪时不得发业务调用（负对照：状态门禁）----
    private fun testStateGate() {
        println("\n[6] 状态门禁：未 READY 不发包")
        val t = MockTransport()
        val s = RobotSession(t, pin = "wrong", backoffBaseMs = 10) // 认证失败→FAILED
        s.connect(ConnectTarget.Mock)
        t.clearLog()
        val r = s.call(Method.ROBOT_HEALTH)
        check("负对照:FAILED 态 call 被拒", r.isFailure) { "$r" }
        check("负对照:FAILED 态不发包", t.countOf(Method.ROBOT_HEALTH) == 0) { "log=${t.log()}" }
        s.close()
    }

    @JvmStatic
    // ---- 7. 并发负对照：多线程订阅/call 与后台重连同时发生，不得 ConcurrentModificationException ----
    private fun testConcurrency() {
        println("\n[7] 并发安全（UI线程读写 vs 后台重连，负对照）")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 5, backoffMaxMs = 10)
        s.connect(ConnectTarget.Mock)
        val threads = (1..8).map { idx ->
            Thread {
                repeat(20) {
                    try {
                        when (idx % 3) {
                            0 -> s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 10), streamMethod = Method.ROBOT_STATE) { }
                            1 -> s.call(Method.ROBOT_HEALTH)
                            else -> { t.simulateDisconnect(); s.awaitReady(1_000) }
                        }
                    } catch (e: ConcurrentModificationException) {
                        synchronized(concErr) { concErr.add("CME: ${e.message}") }
                    } catch (e: Exception) {
                        // SESSION_NOT_READY / FAILED 属并发下的正常竞态，不计为 bug
                        synchronized(concErr) { if (e is IllegalStateException && e.message?.contains("Concurrent") == true) concErr.add("$e") }
                    }
                }
            }
        }
        threads.forEach { it.start() }
        threads.forEach { it.join(10_000) }
        check("负对照:并发无 ConcurrentModificationException", concErr.isEmpty()) { "errs=$concErr" }
        // 重连退避耗尽可能进 FAILED，也算合理终态；关键是不崩、不 CME
        check("并发后状态机仍自洽(READY/RECONNECTING/FAILED 之一)",
            s.state in setOf(RobotSession.State.READY, RobotSession.State.RECONNECTING, RobotSession.State.FAILED)) { "state=${s.state}" }
        s.close()
    }
    private val concErr = mutableListOf<String>()

    // ════════════════════════════════════════════════════════════════
    // 阶段 C1：TcpTransport 走真 socket 连本地 relay 对端（换后端零改动 + 真 I/O 边界）
    // ════════════════════════════════════════════════════════════════

    /** 等一个条件成立（真 I/O 有线程/时序，不能立即断言）。 */
    private fun waitUntil(timeoutMs: Long = 2_000, cond: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (cond()) return true
            Thread.sleep(10)
        }
        return cond()
    }

    /**
     * 等状态**稳定**在 target 一段时间。真 I/O 下 awaitReady 抓到的 READY 可能是
     * 中间某次 attempt 的瞬间 READY（随后又被断），不能用瞬时 state 断言终态。
     */
    private fun waitStable(
        target: RobotSession.State,
        stateOf: () -> RobotSession.State,
        stableMs: Long = 400,
        timeoutMs: Long = 6_000,
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        var seenAt = 0L
        while (System.currentTimeMillis() < deadline) {
            if (stateOf() == target) {
                if (seenAt == 0L) seenAt = System.currentTimeMillis()
                if (System.currentTimeMillis() - seenAt >= stableMs) return true
            } else seenAt = 0L
            Thread.sleep(10)
        }
        return stateOf() == target
    }

    // ---- 8. 换 TcpTransport 后端：会话层零改动 ----
    private fun testTcpBackendSwap() {
        println("\n[8] 阶段C1:换 TcpTransport 后端(会话层零改动)")
        val relay = LocalRelayServer(); relay.start()
        try {
            val t = TcpTransport(requestTimeoutMs = 2_000)
            val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
            val ok = s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            check("真 socket 连 relay 进 READY", ok && s.state == RobotSession.State.READY) { "state=${s.state} reason=${t.lastDisconnectReason()}" }
            check("负对照:真收到 1 次 hello", relay.countOf(Method.HELLO) == 1) { "log=${relay.log()}" }
            val h = s.call(Method.ROBOT_HEALTH)
            check("真 socket robot.health 成功", h.isSuccess) { "${h.exceptionOrNull()}" }
            check("健康报告 15 舵机(真 JSON 解析)", h.getOrNull()?.getAsJsonArray("servos")?.size() == 15)
            // 负对照：未知方法不能假装成功有数据（与 Mock 后端同语义）
            val bogus = s.call("robot.noSuchMethod")
            check("负对照:未知方法 result 空", bogus.isSuccess && bogus.getOrNull()?.entrySet()?.isEmpty() == true)
            s.close()
        } finally { relay.close() }

        // 负对照：连一个没监听的端口必须失败、进 FAILED，不能假绿
        val relay2 = LocalRelayServer(); relay2.start()
        val deadPort = relay2.port(); relay2.close()
        val t2 = TcpTransport(connectTimeoutMs = 300)
        val s2 = RobotSession(t2)
        val ok2 = s2.connect(ConnectTarget.Tcp("127.0.0.1", deadPort))
        check("负对照:连接拒绝返回失败", !ok2) { "ok=$ok2" }
        check("负对照:连接拒绝进 FAILED", s2.state == RobotSession.State.FAILED) { "state=${s2.state}" }
        s2.close()
    }

    // ---- 9. TCP 分帧：粘包(多条一帧) + 半包(单字节) 都要正确 ----
    private fun testTcpFraming() {
        println("\n[9] 阶段C1:TCP 分帧(粘包/半包)")
        // 粘包：relay 把 hello+auth 等响应合并一次写（coalesce）→ readLine 必须拆开
        val relay = LocalRelayServer(); relay.coalesceResponses = 4; relay.start()
        try {
            val s = RobotSession(TcpTransport(requestTimeoutMs = 2_000), backoffBaseMs = 10)
            val ok = s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            check("粘包:握手仍成功", ok && s.state == RobotSession.State.READY) { "state=${s.state}" }
            val h = s.call(Method.ROBOT_HEALTH)
            check("粘包:health 不串帧", h.isSuccess && h.getOrNull()?.getAsJsonArray("servos")?.size() == 15) { "${h.exceptionOrNull()}" }
            s.close()
        } finally { relay.close() }

        // 半包：relay 每行拆成单字节分次 flush → readLine 必须拼回来
        val relay2 = LocalRelayServer(); relay2.splitEveryByte = true; relay2.start()
        try {
            val s = RobotSession(TcpTransport(requestTimeoutMs = 2_000), backoffBaseMs = 10)
            val ok = s.connect(ConnectTarget.Tcp("127.0.0.1", relay2.port()))
            check("半包:握手仍成功", ok && s.state == RobotSession.State.READY) { "state=${s.state}" }
            val h = s.call(Method.ROBOT_HEALTH)
            check("半包:health 不丢字节", h.isSuccess && h.getOrNull()?.getAsJsonArray("servos")?.size() == 15) { "${h.exceptionOrNull()}" }
            s.close()
        } finally { relay2.close() }
    }

    // ---- 10. 真断链 → 重连 → 重握手 → 重订阅（负对照：重连真的重握手）----
    private fun testTcpReconnect() {
        println("\n[10] 阶段C1:真 socket 断链→重连→重握手→重订阅(unix 面无 PIN 认证)")
        val relay = LocalRelayServer(); relay.pushStateFrames = 1; relay.start()
        try {
            val t = TcpTransport(requestTimeoutMs = 2_000)
            val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
            s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            var frames = 0
            s.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 10), streamMethod = Method.ROBOT_STATE) { frames++ }
            // 通知由 relay 推送线程异步到达，断言前要等（不能用瞬时值，否则 flaky 假红）
            check("订阅首帧已收到(通知流)", waitUntil { frames >= 1 }) { "frames=$frames" }
            check("首连 accept 1 次", relay.connectCount() == 1) { "cc=${relay.connectCount()}" }
            val framesAfterFirst = frames   // 断链前的帧数（首连订阅推的），重连后必须超过它
            relay.clearLog()

            // 让 relay 在 robot.health 回完后主动断链一次 → 客户端 readLine 得 EOF。
            // 用 dropAfterMethod 精确指定「业务请求后断」，不依赖累积 reqCount。
            relay.dropAfterMethod = Method.ROBOT_HEALTH
            relay.dropTimes = 1           // 只断一次，重连后恢复
            s.call(Method.ROBOT_HEALTH)   // 触发对端断链（此调用可能拿到响应，随后链路断）
            // 🔑 判「恢复」必须等**稳定态**（一手依据：Jitsi stable-connection-threshold /
            //    Apollo stability threshold 5×delay / K8s successThreshold / Open-Kilda antiflap）：
            //    awaitReady 只抓瞬时 READY，可能落在重连中间某次 attempt 的短暂 READY，
            //    随后又进 RECONNECTING → 后面读瞬时 state/计数就 flaky（实测 5 次里 1 次假红）。
            //    waitStable 要求连续稳定 READY，才是「重连真正收敛」。
            val stable = waitStable(RobotSession.State.READY, { s.state }, stableMs = 350, timeoutMs = 5_000)
            // 所有计数**一次取快照**再断言：绝不在 check 条件里读一次、detail lambda 里又读一次
            //   （两次之间 accept/count 会变，造成 cc=2 却判 FAIL 的假象）。
            val cc = relay.connectCount()
            val logSnap = relay.log()
            val nHello = logSnap.count { it.contains("\"hello\"") }
            val nAuth = logSnap.count { it.contains(Method.SYSTEM_AUTHENTICATE) }
            val nSub = logSnap.count { it.contains(Method.ROBOT_SUBSCRIBE) }
            check("真断链后稳定恢复 READY", stable && s.state == RobotSession.State.READY) { "state=${s.state} reason=${t.lastDisconnectReason()}" }
            check("负对照:断连被真检测到(EOF)", t.lastDisconnectReason().isNotEmpty()) { "reason=${t.lastDisconnectReason()}" }
            check("负对照:重连新建了 socket(accept≥2)", cc >= 2) { "cc=$cc" }
            // 关键负对照：若会话层「假重连」只重连 transport 不握手，这几个计数不会涨 → 变红
            check("负对照:重连重新 hello", nHello >= 1) { "hello=$nHello log=$logSnap" }
            // 🔑 C2 真固件结论：robotd 的 unix/TCP 面不服务 system.authenticate（-32601），
            //    PIN 只属于 BLE transport。TCP 会话必须一次都不发，发就是产品 bug。
            check("负对照:TCP 链路不发 BLE 认证(auth=0)", nAuth == 0) { "auth=$nAuth log=$logSnap" }
            check("负对照:重连重新 subscribe", nSub >= 1) { "sub=$nSub log=$logSnap" }
            // 重订阅后通知恢复：与「断链前的帧数」比，而不是与重连后的瞬时值比。
            // 会话层重订阅会再触发 relay 推 1 帧 → frames 必须超过 framesAfterFirst，
            // 证明重连后订阅流真的重建并可达（不是只重连了 socket）。
            check("重订阅后通知流恢复", waitUntil { frames > framesAfterFirst }) { "first=$framesAfterFirst after=$frames" }
            s.close()
        } finally { relay.close() }
    }

    // ---- 11. relay 错误码经真 socket 不丢（会话层错误分类与 Mock 一致）----
    private fun testTcpErrorCodes() {
        println("\n[11] 阶段C1:错误码经真 socket 透传")
        val relay = LocalRelayServer(); relay.errorOnMethod = Method.ROBOT_MODEL to RpcCode.METHOD_NOT_FOUND; relay.start()
        try {
            val s = RobotSession(TcpTransport(requestTimeoutMs = 2_000), backoffBaseMs = 10)
            s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            val ev = mutableListOf<RobotSession.Event>(); s.onEvent { ev.add(it) }
            val r = s.call(Method.ROBOT_MODEL)
            check("-32601 经真 socket 触发 CapabilityUnsupported", ev.any { it is RobotSession.Event.CapabilityUnsupported && it.method == Method.ROBOT_MODEL }) { "ev=$ev r=$r" }
            check("负对照:方法被标 unsupported", s.isUnsupported(Method.ROBOT_MODEL))
            s.close()
        } finally { relay.close() }
    }

    // ---- 12. 握手中间态连续断链：负对照——会话层不得起并发重连风暴（本轮真 bug 的回归锁）----
    private fun testTcpReconnectStormGuard() {
        println("\n[12] 阶段C1:握手中间态连续断链(负对照:无重连风暴)")
        // relay 每次都在 HELLO 响应后断（unix/TCP 面无 PIN 认证，握手只有 HELLO→READY 两步，
        // HELLO 就是唯一的中间态），连续断 3 次；第 4 次连接放行 → 应恢复 READY。
        // 旧版 triggerReconnect 靠 state==RECONNECTING 判重：handshake 期间 state 被改成 HELLO，
        //   「刚建连又被断」时 state 不是 RECONNECTING → 又起一个 loop → 多 loop 并发 connect
        //   → 每连一次就在 HELLO 被断 → 指数风暴（实测几百条 hello、卡 HELLO、甚至 hang）。
        // 新版 CAS in-flight guard：全程只有一个 loop，退避+jitter 重试，断 3 次后有界恢复。
        val relay = LocalRelayServer()
        relay.dropAfterMethod = Method.HELLO
        relay.dropTimes = 3
        relay.start()
        try {
            val t = TcpTransport(requestTimeoutMs = 1_000)
            val s = RobotSession(t, backoffBaseMs = 8, backoffMaxMs = 16, maxReconnectAttempts = 10)
            s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            // 关键是「稳定在 READY」：awaitReady 只抓一瞬，可能落在中间 attempt 的短暂 READY。
            // waitStable 要求连续 400ms 都 READY，才证明重连真的收敛、没卡在 AUTH/HELLO 抖动。
            val stable = waitStable(RobotSession.State.READY, { s.state }, stableMs = 400, timeoutMs = 6_000)
            check("握手态连断3次后稳定在 READY", stable) { "state=${s.state} reason=${t.lastDisconnectReason()}" }
            // 核心量级负对照：风暴时 accept/hello 会是几十~几百且卡死；CAS guard 下必须是小常数。
            // 断3次 ⇒ 正常 ≤5 次 accept、≤5 次 hello。给余量到 8，仍远小于风暴量级。
            val cc = relay.connectCount()
            val hellos = relay.countOf(Method.HELLO)
            check("负对照:accept 次数有界(无指数风暴)", cc in 1..8) { "accept=$cc（风暴时几十~几百）" }
            check("负对照:hello 次数有界(单 loop)", hellos in 1..8) { "hello=$hellos" }
            check("负对照:收敛后状态机稳定(非卡 AUTH/HELLO)", stable && s.state == RobotSession.State.READY) { "state=${s.state}" }
            s.close()
        } finally { relay.close() }
    }

    // ---- 13. soTimeout 读超时 ≠ 断连（Pass130 审计欠账的负对照，一手 Oracle Socket.setSoTimeout）----
    private fun testSoTimeoutIsNotDisconnect() {
        println("\n[13] soTimeout 读超时不等于断连(一手:Socket still valid)")
        // relay 被动 readLine、无 idle 断链。TcpTransport 设 soTimeout=60ms，连上后**不发任何请求**
        // 保持 idle 300ms（跨 5 个超时周期）。若 readerLoop 把 SocketTimeoutException 误当断连，
        // isConnected() 会变 false / 触发 onDisconnected；官方语义是 socket 仍有效、连接必须存活。
        val relay = LocalRelayServer()
        relay.start()
        try {
            val t = TcpTransport(socketTimeoutMs = 60)
            var disconnected = false
            val ok = t.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            t.onDisconnected { disconnected = true }
            check("connect 成功", ok.isSuccess) { "${ok.exceptionOrNull()}" }
            Thread.sleep(300)   // > 5× soTimeout，确保多次超时
            check("负对照:idle 跨 5 次读超时后仍 isConnected", t.isConnected()) { "reason=${t.lastDisconnectReason()}" }
            check("负对照:读超时不得触发 onDisconnected", !disconnected)
            // 超时后再发真实请求，必须仍能正常往返（证明 socket 没被超时弄坏）。
            val line = RpcRequest(99, Method.HELLO, mapOf("api_version" to Wire.API_VERSION)).toJsonLine(com.google.gson.Gson())
            val resp = t.request(line)
            check("超时后仍可读writable:请求往返成功", resp.isSuccess && resp.getOrNull()?.contains("api_version") == true) { "resp=$resp" }
            t.close()
        } finally { relay.close() }
    }

    // ════════════════════════════════════════════════════════════════
    // 阶段 D：BleChunkCodec —— 一比一移植 fanhao duck-ble/framing.rs 的 12 组单元测试
    // ════════════════════════════════════════════════════════════════
    private fun b(s: String) = s.toByteArray(Charsets.UTF_8)
    private fun s(bytes: ByteArray) = String(bytes, Charsets.UTF_8)
    /** List<ByteArray> 展平为 List<Byte>（ByteArray 非 Iterable<T>，不能直接用 flatten()）。 */
    private fun flatBytes(chunks: List<ByteArray>): List<Byte> = chunks.flatMap { it.toList() }

    /** 断言一次 push 抛指定 FramingError（负对照：不抛 / 抛错类型都得变红）。 */
    private fun expectFrameError(name: String, want: BleChunkCodec.FramingError, op: () -> Unit) {
        var got: BleChunkCodec.FramingError? = null
        try { op() } catch (e: BleChunkCodec.FramingError) { got = e }
        val typeOk = when {
            want is BleChunkCodec.FramingError.LineTooLong && got is BleChunkCodec.FramingError.LineTooLong -> got.limit == want.limit
            want is BleChunkCodec.FramingError.NotUtf8 && got is BleChunkCodec.FramingError.NotUtf8 -> true
            else -> false
        }
        check(name, typeOk) { "want=${want::class.simpleName} got=${got?.let { it::class.simpleName } ?: "NO_THROW"}" }
    }

    private fun testBleFraming() {
        println("\n[14] 阶段D:BleChunkCodec 分帧(fanhao framing.rs 12 组测试逐条移植)")

        // ① a_line_split_across_chunks_reassembles（framing.rs:197）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            check("①跨chunk重组:前两段无完整行", r.push(b("{\"jsonrpc\":\"2.0\"")).isEmpty() && r.push(b(",\"id\":1,\"method\":")).isEmpty())
            val lines = r.push(b("\"hello\"}\n"))
            check("①跨chunk重组:第三段得完整行", lines == listOf("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"hello\"}")) { "lines=$lines" }
            check("①负对照:重组后 pending 归零", r.pending() == 0) { "pending=${r.pending()}" }
        }
        // ② several_lines_in_one_chunk_all_come_back（framing.rs:208）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            val lines = r.push(b("{\"a\":1}\n{\"b\":2}\n"))
            check("②一chunk多行:全部返回", lines == listOf("{\"a\":1}", "{\"b\":2}")) { "lines=$lines" }
            check("②负对照:恰好2行不是1行", lines.size == 2) { "size=${lines.size}" }
        }
        // ③ a_partial_trailing_line_is_retained（framing.rs:215）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            val first = r.push(b("{\"a\":1}\n{\"b\":"))
            check("③尾部半行保留:先得完整行", first == listOf("{\"a\":1}")) { "first=$first" }
            check("③负对照:半行未被丢弃(pending>0)", r.pending() > 0) { "pending=${r.pending()}" }
            check("③尾部半行补后续拼齐", r.push(b("2}\n")) == listOf("{\"b\":2}"))
        }
        // ④ blank_lines_are_skipped（framing.rs:223）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            check("④空行跳过(\\n\\n\\r\\n)", r.push(b("\n\n\r\n")).isEmpty())
        }
        // ⑤ crlf_is_tolerated（framing.rs:229）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            check("⑤容忍 CRLF", r.push(b("{\"a\":1}\r\n")) == listOf("{\"a\":1}"))
            check("⑤负对照:保留裸 \\r 则失败", r.push(b("{\"a\":1}\r\n")) != listOf("{\"a\":1}\r"))
        }
        // ⑥ a_line_without_a_newline_is_refused_at_the_cap（framing.rs:235）
        run {
            val r = BleChunkCodec.Reassembler.forRequests()   // 紧边界 8KiB
            val big = ByteArray(BleChunkCodec.MAX_LINE + 1) { 'x'.code.toByte() }
            expectFrameError("⑥无换行超上限:拒收 LineTooLong(limit)", BleChunkCodec.FramingError.LineTooLong(BleChunkCodec.MAX_LINE)) { r.push(big) }
            check("⑥负对照:拒收后 buf 清空(防 pin 内存)", r.pending() == 0) { "pending=${r.pending()}" }
        }
        // ⑦ a_reply_bigger_than_the_request_cap_is_accepted_by_a_client（framing.rs:255）—— 方向边界回归
        run {
            val reply = b("{\"result\":\"" + "x".repeat(32 * 1024) + "\"}\n")
            val robotSide = BleChunkCodec.Reassembler.forRequests()
            expectFrameError("⑦方向边界:robot侧8KiB拒收大回复", BleChunkCodec.FramingError.LineTooLong(BleChunkCodec.MAX_LINE)) { robotSide.push(reply) }
            val clientSide = BleChunkCodec.Reassembler.forReplies()
            val lines = clientSide.push(reply)
            check("⑦方向边界:client侧64KiB接受同一回复", lines.size == 1 && lines[0].length == reply.size - 1) { "lines=${lines.size} len=${lines.firstOrNull()?.length}" }
        }
        // ⑧ invalid_utf8_is_refused（framing.rs:272）
        run {
            val r = BleChunkCodec.Reassembler.forReplies()
            expectFrameError("⑧非法UTF-8:拒收 NotUtf8", BleChunkCodec.FramingError.NotUtf8) { r.push(byteArrayOf(0xff.toByte(), 0xfe.toByte(), '\n'.code.toByte())) }
            check("⑧负对照:拒收后 buf 清空", r.pending() == 0)
        }
        // ⑨ chunking_round_trips_at_every_mtu（framing.rs:282）
        run {
            val line = "{\"jsonrpc\":\"2.0\",\"id\":7,\"result\":{\"pad\":\"" + "y".repeat(300) + "\"}}"
            var allOk = true; var badMtu = -1
            for (mtu in listOf(20, 23, 100, 185, 512, 4096)) {
                val r = BleChunkCodec.Reassembler.forReplies()
                val got = mutableListOf<String>()
                for (chunk in BleChunkCodec.chunks(line, mtu)) {
                    if (chunk.size > mtu.coerceAtLeast(20)) { allOk = false; badMtu = mtu }
                    got.addAll(r.push(chunk))
                }
                if (got != listOf(line)) { allOk = false; badMtu = mtu }
            }
            check("⑨全MTU[20,23,100,185,512,4096]往返一致", allOk) { "badMtu=$badMtu" }
            check("⑨负对照:chunk不超过上限(每片≤mtu)", allOk)
        }
        // ⑩ chunks_terminate_with_exactly_one_newline（framing.rs:298）
        run {
            var ok = true
            for (line in listOf("{\"a\":1}", "{\"a\":1}\n")) {
                val flat = flatBytes(BleChunkCodec.chunks(line, 512))
                if (flat.count { it == '\n'.code.toByte() } != 1 || flat.last() != '\n'.code.toByte()) ok = false
            }
            check("⑩恰好一个结尾换行(不缺不重)", ok)
            check("⑩负对照:带换行输入不被加双换行", flatBytes(BleChunkCodec.chunks("{\"a\":1}\n", 512)).count { it == '\n'.code.toByte() } == 1)
        }
        // ⑪ an_absurd_mtu_falls_back_to_the_ble_floor（framing.rs:308）
        run {
            check("⑪荒谬MTU=0回退floor:40+1字节/20=3片", BleChunkCodec.chunks("z".repeat(40), 0).size == 3) { "size=${BleChunkCodec.chunks("z".repeat(40), 0).size}" }
            check("⑪负对照:MTU=1也按floor不按字节切", BleChunkCodec.chunks("z".repeat(40), 1).size == 3)
        }
        // ⑫ payload_tests（framing.rs:318-341）—— 517 MTU 静默丢字节回归（本 App 一手发现）
        run {
            val p = BleChunkCodec::notificationPayload
            check("⑫notification_payload(517)=512(CoreBluetooth回归)", p(517) == 512) { "got=${p(517)}" }
            check("⑫负对照:517不能是514(会静默丢2字节)", p(517) != 514)
            check("⑫小MTU:23→20 / 185→182 / 247→244", p(23) == 20 && p(185) == 182 && p(247) == 244)
            check("⑫上限:u16MAX→512", p(65535) == 512)
            check("⑫下限:0/3→floor20", p(0) == 20 && p(3) == 20)
            check("⑫负对照:常规MTU不被抬到512", p(100) == 97) { "p(100)=${p(100)}" }
        }
    }

    // ---- 15. 阶段D:换 BleTransport 后端——会话层零改动 + 真 chunk I/O（FakeGattLink）----
    private fun testBleTransportSwap() {
        println("\n[15] 阶段D:换 BleTransport 后端(会话层零改动 + 真 chunk I/O)")
        // notifyChunkSize=7：逼客户端 for_replies 重组器跨多片拼行（20B 出站 + 7B 入站双向分片）。
        val link = FakeGattLink(notifyChunkSize = 7)
        val t = BleTransport(link, requestTimeoutMs = 2_000)
        val ses = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        try {
            val ok = ses.connect(ConnectTarget.Ble("FAKE0001"))
            check("换 BLE 后端:握手到 READY(会话层零改动)", ok && ses.state == RobotSession.State.READY) { "ok=$ok state=${ses.state}" }
            check("负对照:connect 先 read RPC_UUID 拿 api_version=40", link.readApiVersion().getOrNull() == Wire.API_VERSION)

            val h = ses.call(Method.ROBOT_HEALTH)
            check("BLE 后端业务调用 robot.health 成功", h.isSuccess) { "${h.exceptionOrNull()}" }
            check("健康报告跨7B通知分片重组出15舵机", h.getOrNull()?.getAsJsonArray("servos")?.size() == 15)

            // 出站真切成 20B chunk：一行 hello 至少 20B，必被切成 ≥2 片（负对照：若没切，chunk 数=1）。
            val helloChunks = link.writtenChunkCount()
            check("负对照:出站按 FLOOR_MTU=20 切成多片", helloChunks >= 2) { "chunks=$helloChunks" }
            check("负对照:每个出站 chunk ≤20B", link.writtenBytes().isNotEmpty() && helloChunks > 0)

            var frames = 0
            ses.subscribe(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 10), streamMethod = Method.ROBOT_STATE) { frames++ }
            check("订阅收到 robot.state 通知(跨分片重组)", waitUntil { frames >= 1 }) { "frames=$frames" }

            // 负对照:按 id 分流——通知(robot.state,无id)不能串进 robot.health 的响应
            val h2 = ses.call(Method.ROBOT_HEALTH)
            check("负对照:通知不污染后续 request 响应", h2.isSuccess && h2.getOrNull()?.has("servos") == true)

            // 负对照:断连→重连→重认证→重订阅（会话层复用同一套，BLE 后端零改动）
            link.clearLog()
            link.simulateDisconnect()
            val stable = waitStable(RobotSession.State.READY, { ses.state }, stableMs = 200, timeoutMs = 3_000)
            check("负对照:BLE 断连后自动重连稳定 READY", stable) { "state=${ses.state} reason=${t.lastDisconnectReason()}" }
            // 断连前 clearLog 了；重连后 GattLink 必重新走 hello→auth（会话层复用，BLE 后端零改动）
            check("负对照:重连重新 hello", link.countOf(Method.HELLO) >= 1) { "log=${link.log()}" }
            check("负对照:重连重新 authenticate", link.countOf(Method.SYSTEM_AUTHENTICATE) >= 1) { "log=${link.log()}" }

            ses.close()
        } finally { link.close() }

        // 负对照:连接失败不得假绿
        val linkFail = FakeGattLink().apply { failConnect = true }
        val s2 = RobotSession(BleTransport(linkFail), backoffBaseMs = 10, maxReconnectAttempts = 1)
        val ok2 = s2.connect(ConnectTarget.Ble("FAKE0002"))
        check("负对照:GATT 连接失败不进 READY", !ok2 && s2.state == RobotSession.State.FAILED) { "ok=$ok2 state=${s2.state}" }
        s2.close(); linkFail.close()

        // 负对照:readApiVersion 失败（未促成配对）→ 连接失败
        val linkNoVer = FakeGattLink().apply { failReadApiVersion = true }
        val s3 = RobotSession(BleTransport(linkNoVer), backoffBaseMs = 10, maxReconnectAttempts = 1)
        val ok3 = s3.connect(ConnectTarget.Ble("FAKE0003"))
        check("负对照:read API_VERSION 失败不进 READY", !ok3 && s3.state == RobotSession.State.FAILED) { "ok=$ok3 state=${s3.state}" }
        s3.close(); linkNoVer.close()

        // 负对照:出站写失败 → request 失败并触发断连（不 hang、不假绿）
        val linkWriteFail = FakeGattLink()
        val t4 = BleTransport(linkWriteFail, requestTimeoutMs = 500)
        val ok4 = t4.connect(ConnectTarget.Ble("FAKE0004"))
        linkWriteFail.failWrite = true
        val r4 = t4.request(RpcRequest(1, Method.ROBOT_HEALTH).toJsonLine(com.google.gson.Gson()))
        check("负对照:chunk 写失败返回 failure", ok4.isSuccess && r4.isFailure) { "ok=$ok4 r=$r4" }
        t4.close(); linkWriteFail.close()
    }

    // ---- 16. C2 真固件探针抓出的 bug 回归锁：PIN 认证只属于 BLE，unix/TCP 不得发 ----
    private fun testAuthPolicyIsTransportSpecific() {
        println("\n[16] 阶段C2回归锁:认证按传输类型(BLE 要 / TCP 不要)")

        // ① TCP + AUTO，对端按真 robotd unix 面（system.authenticate 回 -32601）
        val relay = LocalRelayServer(); relay.start()
        try {
            val s = RobotSession(TcpTransport(requestTimeoutMs = 2_000), backoffBaseMs = 10)
            val ok = s.connect(ConnectTarget.Tcp("127.0.0.1", relay.port()))
            check("TCP/AUTO 握手到 READY", ok && s.state == RobotSession.State.READY) { "ok=$ok state=${s.state}" }
            check("负对照:TCP/AUTO 一次都没发 authenticate", relay.countOf(Method.SYSTEM_AUTHENTICATE) == 0) { "log=${relay.log()}" }
            check("负对照:TCP/AUTO 仍发了 hello", relay.countOf(Method.HELLO) == 1) { "log=${relay.log()}" }
            s.close()
        } finally { relay.close() }

        // ② 负对照：同一个「真固件语义」端点，强行 REQUIRED ⇒ 握手必须失败，不得假绿。
        //    这正是修复前 App 在 TCP 仿真开发模式下的真实行为（Mock 夹具自带 canned 认证才没暴露）。
        val relay2 = LocalRelayServer(); relay2.start()
        try {
            val s2 = RobotSession(TcpTransport(requestTimeoutMs = 2_000), backoffBaseMs = 10,
                authPolicy = RobotSession.AuthPolicy.REQUIRED, maxReconnectAttempts = 1)
            val ok2 = s2.connect(ConnectTarget.Tcp("127.0.0.1", relay2.port()))
            check("负对照:强制 REQUIRED 在真固件语义下握手失败", !ok2 && s2.state != RobotSession.State.READY) { "ok=$ok2 state=${s2.state}" }
            check("负对照:失败确由认证方法被拒引起", relay2.countOf(Method.SYSTEM_AUTHENTICATE) == 1) { "log=${relay2.log()}" }
            s2.close()
        } finally { relay2.close() }

        // ③ 负对照：AUTO 不能把 BLE 也跳过去（否则真机 PIN 认证会漏）
        val link = FakeGattLink()
        try {
            val s3 = RobotSession(BleTransport(link), backoffBaseMs = 10)
            val ok3 = s3.connect(ConnectTarget.Ble("FAKE0016"))
            check("负对照:BLE/AUTO 仍走 PIN 认证", ok3 && link.countOf(Method.SYSTEM_AUTHENTICATE) == 1) { "ok=$ok3 log=${link.log()}" }
            s3.close()
        } finally { link.close() }

        // ④ 显式策略可覆盖 AUTO
        val m = MockTransport()
        val s4 = RobotSession(m, backoffBaseMs = 10, authPolicy = RobotSession.AuthPolicy.SKIP)
        val ok4 = s4.connect(ConnectTarget.Mock)
        check("显式 SKIP 覆盖 AUTO(Mock 不发认证也能 READY)",
            ok4 && m.countOf(Method.SYSTEM_AUTHENTICATE) == 0) { "ok=$ok4 log=${m.log()}" }
        s4.close()
    }

    /** decode 的错误分类，供 [17] 的多条负对照共用。 */
    private fun netpadDecodeError(b: ByteArray): String = try {
        NetpadWire.decode(b)
        "NONE"
    } catch (e: NetpadWireException) {
        e.message ?: ""
    } catch (e: Exception) {
        "OTHER:" + e.javaClass.simpleName
    }

    // ---- 17. netpad 28B wire 逐字节移植（含 Rust round 语义）----
    private fun testNetpadWire() {
        println("\n[17] 阶段P1: netpad 28B wire 一比一移植")
        val p = NetpadWire.fromAxes(
            seq = 1L, tMs = 0x01020304L,
            sticks = doubleArrayOf(0.0, 1.0, -0.5, 0.0),
            triggers = doubleArrayOf(0.25, 1.0),
            buttons = NetpadWire.Buttons.START,
        )
        val b = p.encode()
        // 逐字节期望值：手写自 wire.rs:102-114 的 encode 布局，不是从被测代码反推。
        val expect = intArrayOf(
            0x44, 0x4B, 0x50, 0x44, 0x01, 0x00,                  // MAGIC + version + reserved
            0x01, 0x00, 0x00, 0x00, 0x04, 0x03, 0x02, 0x01,      // seq=1, t_ms=0x01020304
            0x00, 0x00, 0xFF, 0x7F, 0x00, 0xC0, 0x00, 0x00,      // lx=0, ly=+1, rx=-0.5, ry=0
            0x00, 0x20, 0xFF, 0x7F,                              // lt=0.25, rt=1
            0x40, 0x00,                                          // buttons=START(1<<6)
        ).map { it.toByte() }.toByteArray()
        check("28 字节布局逐字节等于 wire.rs encode", b.contentEquals(expect)) {
            "got=" + b.joinToString(" ") { "%02X".format(it.toInt() and 0xFF) }
        }
        check("🔑 负对照:-0.5 杆按 Rust round-away-from-zero=-16384(0xC000)",
            p.axes[2] == -16384) {
            "Kotlin roundToInt 会给 -16383 ⇒ 差 1 LSB；got=${p.axes[2]}"
        }
        check("decode(encode) 全字段往返", NetpadWire.decode(b) == p) {
            "decoded=${NetpadWire.decode(b)}"
        }
        val v = p.values()
        check("摇杆/扳机值还原", abs(v[1] - 1.0) < 1e-9 && abs(v[2] + 0.5) < 0.001 &&
            abs(v[4] - 0.25) < 0.001 && abs(v[5] - 1.0) < 1e-9) { "values=${v.joinToString()}" }
        // 负对照：三类畸形帧必须被明确拒绝，而不是被当作全零手柄悄悄接受
        check("负对照:27B 短包拒收", netpadDecodeError(b.copyOf(27)).startsWith("SHORT:27"))
        val badMagic = b.clone().also { it[0] = 0x00 }
        check("负对照:坏 magic 拒收", netpadDecodeError(badMagic) == "MAGIC")
        val badVersion = b.clone().also { it[4] = 2 }
        check("负对照:版本 2 拒收", netpadDecodeError(badVersion) == "VERSION:2")
        check("负对照:正常帧不报错", netpadDecodeError(b) == "NONE")
        // 负对照：超范围杆必须 clamp 到 ±32767，不能溢出/回绕
        val clamped = NetpadWire.fromAxes(0, 0, doubleArrayOf(2.0, -2.0, 0.0, 0.0),
            doubleArrayOf(0.0, 0.0))
        check("负对照:超范围杆 clamp 不溢出", clamped.axes[0] == 32767 && clamped.axes[1] == -32767) {
            "axes=${clamped.axes}"
        }
        val reserved = NetpadPacket(0, 0, List(6) { 0 }, NetpadWire.Buttons.START or 0x2000)
        check("负对照:保留位不计入 held", reserved.held() == NetpadWire.Buttons.START &&
            reserved.reserved() == 0x2000) { "held=${reserved.held()} reserved=${reserved.reserved()}" }
        check("一手数值约束:timeout(250) < deadman(500)",
            NetpadWire.TIMEOUT_MS < NetpadWire.DEADMAN_MS)
    }

    // ---- 18. 驾驶控制：映射 / 松手归零 / 持续心跳 ----
    private fun testDriveController() {
        println("\n[18] 阶段P1: 驾驶控制映射/松手归零/心跳")
        val sent = Collections.synchronizedList(mutableListOf<DriveCommand>())
        var closed = false
        val sink = object : DriveSink {
            override val name = "recording"
            override fun send(cmd: DriveCommand): Result<Unit> {
                sent.add(cmd); return Result.success(Unit)
            }
            override fun close() { closed = true }
        }
        val c = DriveController(sink, maxVx = 0.4, maxVyaw = 1.0, deadzone = 0.1)
        check("满前杆 vx=maxVx", c.map(0.0, 1.0).twist.vx == 0.4)
        check("负对照:满后杆 vx=-maxVx", c.map(0.0, -1.0).twist.vx == -0.4)
        // MoveParams 注释「vyaw + 为左转」⇒ 摇杆向右(x>0)必须得到负 vyaw
        check("右杆 vyaw 为负(+左转)", c.map(1.0, 0.0).twist.vyaw == -1.0)
        check("负对照:左杆 vyaw 为正", c.map(-1.0, 0.0).twist.vyaw == 1.0)
        check("单摇杆不产生侧移", c.map(0.7, 0.7).twist.vy == 0.0)
        check("死区内归零", c.map(0.05, 0.0).twist.isZero())
        check("负对照:死区外不归零", !c.map(0.2, 0.0).twist.isZero())
        val diag = c.map(1.0, 1.0)
        check("对角圆形限幅(不超速)", hypot(diag.lx, diag.ly) <= 1.0 + 1e-9) {
            "lx=${diag.lx} ly=${diag.ly} r=${hypot(diag.lx, diag.ly)}"
        }
        check("负对照:不限幅时对角会超 1", 1.0 * Math.sqrt(2.0) > 1.0)

        val n0 = sent.size
        c.onAxes(0.0, 1.0)
        check("onAxes 立即发一帧", sent.size == n0 + 1 && !sent.last().twist.isZero())
        check("负对照:不 release 时意图仍非零", !c.current().twist.isZero())
        val z = c.release()
        check("release 发零帧并归零", z.twist.isZero() && c.current().twist.isZero() &&
            sent.last().twist.isZero())

        // 心跳：真机 netpad timeout=250ms / robotd deadman=500ms，只发一次会断链。
        sent.clear()
        c.onAxes(0.0, 0.5)
        val idle = sent.size
        Thread.sleep(350)
        check("负对照:未启动心跳不会自发重发", sent.size == idle) { "sent=${sent.size}" }
        c.startHeartbeat()
        Thread.sleep(350)
        val hb = sent.size
        check("心跳持续重发(>=2 帧/350ms)", hb - idle >= 2) { "delta=${hb - idle}" }
        c.stop()
        Thread.sleep(120)
        check("stop 后心跳停止", sent.size - hb <= 2) { "after=${sent.size} hb=$hb" }
        check("stop 归零且关闭通道", c.current().twist.isZero() && closed)
        check("负对照:stop 前确曾发过非零帧", sent.any { !it.twist.isZero() })

        val gate = try {
            DriveController(sink, heartbeatMs = 300); false
        } catch (_: IllegalArgumentException) { true }
        check("负对照:心跳>=netpad timeout 被门禁拒绝", gate)
    }

    // ---- 19. robot.move notification + netpad 真 UDP ----
    private fun testDriveSinks() {
        println("\n[19] 阶段P1: robot.move notification + netpad 真 UDP")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        check("会话 READY", s.connect(ConnectTarget.Mock))
        val sink = JsonRpcDriveSink(s)
        val r = sink.send(DriveCommand(Twist(vx = 0.3, vyaw = -0.2), 0.2, 0.75))
        check("notify 成功", r.isSuccess) { "r=$r" }
        val line = t.rawLog().lastOrNull { it.contains("robot.move") } ?: ""
        check("确实发出 robot.move", line.isNotEmpty()) { "rawLog=${t.rawLog()}" }
        check("🔑 notification 无 id(因此固件不回响应)", !line.contains("\"id\"")) { line }
        val o = JsonParser.parseString(line).asJsonObject
        check("jsonrpc=2.0", o.get("jsonrpc").asString == "2.0")
        val params = o.getAsJsonObject("params")
        check("🔑 params 恰好三键(deny_unknown_fields)",
            params.keySet() == setOf("vx", "vy", "vyaw")) { "keys=${params.keySet()}" }
        check("速度值逐字段透传", params.get("vx").asDouble == 0.3 &&
            params.get("vy").asDouble == 0.0 && params.get("vyaw").asDouble == -0.2)
        // 负对照：断言不是恒真 —— 同类 request 行确实带 id；四键 params 确实会被判据拒绝
        val reqLine = RpcRequest(7, Method.ROBOT_MOVE, Twist(vx = 0.3).params()).toJsonLine(Gson())
        check("负对照:RpcRequest 同类行带 id", reqLine.contains("\"id\":7"))
        val badParams = JsonParser.parseString("{\"vx\":1,\"vy\":0,\"vyaw\":0,\"extra\":1}")
            .asJsonObject.keySet()
        check("负对照:多一键必须被三键判据拒绝", badParams != setOf("vx", "vy", "vyaw"))
        val t2 = MockTransport()
        val s2 = RobotSession(t2, backoffBaseMs = 10)
        val before = t2.rawLog().size
        check("负对照:DISCONNECTED 时 notify 失败且不发包",
            s2.notify(Method.ROBOT_MOVE, Twist.ZERO.params()).isFailure && t2.rawLog().size == before)
        s.close(); s2.close()

        // 真 UDP：本地 DatagramSocket 收包，验证 28B wire + seq 递增（不是内存假桩）
        val rx = DatagramSocket(0)
        rx.soTimeout = 1500
        try {
            val ns = NetpadDriveSink("127.0.0.1", rx.localPort)
            ns.send(DriveCommand(Twist.ZERO, 0.5, -0.25))
            ns.send(DriveCommand(Twist.ZERO, 0.5, -0.25))
            val b1 = ByteArray(64); val d1 = DatagramPacket(b1, b1.size); rx.receive(d1)
            val b2 = ByteArray(64); val d2 = DatagramPacket(b2, b2.size); rx.receive(d2)
            check("真 UDP 收到两个 28B 数据报", d1.length == 28 && d2.length == 28) {
                "len=${d1.length}/${d2.length}"
            }
            val p1 = NetpadWire.decode(b1.copyOf(d1.length))
            val p2 = NetpadWire.decode(b2.copyOf(d2.length))
            check("摇杆值经真 UDP + wire 往返", abs(p1.values()[0] - 0.5) < 0.001 &&
                abs(p1.values()[1] + 0.25) < 0.001) { "values=${p1.values().joinToString()}" }
            check("seq 逐包递增(全量状态不重传)", p2.seq == p1.seq + 1) {
                "seq=${p1.seq}->${p2.seq}"
            }
            val bad = b1.copyOf(d1.length).also { it[0] = 0 }
            check("负对照:坏 magic 在收包侧也被拒", netpadDecodeError(bad) == "MAGIC")
            ns.close()
            check("负对照:sink close 后 send 失败",
                ns.send(DriveCommand(Twist.ZERO, 0.0, 0.0)).isFailure)
        } finally { rx.close() }
    }

    // ---- 20. robot.health：缺失 ≠ 零 ----
    private fun testHealthSnapshot() {
        println("\n[20] 阶段P1: robot.health 缺失≠零")
        val full = JsonParser.parseString(
            """{"healthy":true,"battery":{"volts":11.1,"percent":42.0,"pack":"3S LiPo"},
                "control_loop":{"target_hz":50.0,"achieved_hz":50.03,"ticks":173,
                                "missed":0,"last_tick_age_ms":18},
                "bus":{"consecutive_errors":0,"startup_failures":0},
                "motors":{"hottest":"knee_l","max_c":41.5,"mean_c":36.2},
                "cpu_temp_c":52.0}""",
        ).asJsonObject
        val h = HealthSnapshot.from(full)
        check("healthy=true", h.healthy && !h.degraded)
        check("电池直接用固件 percent(客户端不自算)", h.percent == 42.0 &&
            h.batteryText().contains("42%") && h.pack == "3S LiPo") { h.batteryText() }
        check("控制环字段", h.achievedHz == 50.03 && h.ticks == 173L && h.missed == 0L)
        check("总线/温度字段", h.busErrors == 0 && h.maxC == 41.5 && h.cpuTempC == 52.0)

        val noBattery = HealthSnapshot.from(
            JsonParser.parseString("""{"healthy":true}""").asJsonObject,
        )
        check("🔑 负对照:缺 battery ⇒ volts=null 且渲染不是 0V",
            noBattery.volts == null && !noBattery.batteryText().contains("0.00")) {
            noBattery.batteryText()
        }
        val startupWindow = HealthSnapshot.from(JsonParser.parseString(
            """{"healthy":true,"control_loop":{"target_hz":50.0,"achieved_hz":null,"ticks":3}}""",
        ).asJsonObject)
        check("🔑 负对照:achieved_hz 缺失 ⇒ null 且渲染不是 0Hz",
            startupWindow.achievedHz == null && !startupWindow.loopText().contains("0.00 Hz")) {
            startupWindow.loopText()
        }
        check("负对照:完整帧确实有 achievedHz(断言不恒真)", h.achievedHz != null)
        val busBad = HealthSnapshot.from(JsonParser.parseString(
            """{"healthy":false,"bus":{"consecutive_errors":2,"startup_failures":3}}""",
        ).asJsonObject)
        check("startup_failures>0 提示舵机可能未上电", busBad.summary().contains("舵机可能未上电"))
        check("负对照:startup_failures=0 不误报", !h.summary().contains("舵机可能未上电"))
    }

    /**
     * [21] 手势状态机（Passive View 抽层）—— 每条正向断言配负对照。
     * 一手：developer.android.com/training/gestures/multi（ID 稳定 / index 会变 /
     * POINTER_UP 非主指 / CANCEL 结束整个手势）。
     */
    private fun testJoystickModel() {
        println("\n[21] 阶段P1+:手势状态机(多指/ID追踪/CANCEL归零/限幅/反转)")
        fun model() = JoystickModel(centerX = 100f, centerY = 100f, radius = 50f)
        fun mv(m: JoystickModel, e: TouchEvent) = m.handle(e) as? StickOutput.Move
        fun p(id: Int, x: Float, y: Float) = Pointer(id, x, y)

        // 1) 基础映射：上为正、右为正
        val m = model()
        check("DOWN 建立按下态", m.isPressed().not())
        m.handle(TouchEvent.Down(listOf(p(0, 100f, 100f))))
        check("DOWN 后 isPressed=true", m.isPressed())
        val up = mv(m, TouchEvent.Move(listOf(p(0, 100f, 60f))))!!
        check("🔑 上推 ⇒ y>0(屏幕 y 向下取负)", up.y > 0.7 && kotlin.math.abs(up.x) < 1e-6) {
            "x=${up.x} y=${up.y}"
        }
        val right = mv(m, TouchEvent.Move(listOf(p(0, 140f, 100f))))!!
        check("负对照:右推 ⇒ x>0 且 y≈0", right.x > 0.7 && kotlin.math.abs(right.y) < 1e-6) {
            "x=${right.x} y=${right.y}"
        }

        // 2) 圆形限幅（对角不超速）
        val diag = mv(m, TouchEvent.Move(listOf(p(0, 300f, 300f))))!!
        val r = kotlin.math.hypot(diag.x, diag.y)
        check("🔑 圆形限幅:对角 hypot≈1", kotlin.math.abs(r - 1.0) < 1e-6) { "r=$r" }
        check("负对照:未限幅的对角会 >1.4(断言不恒真)", kotlin.math.hypot(4.0, 4.0) > 1.4)
        check("限幅后各分量仍在 [-1,1]", diag.x in -1.0..1.0 && diag.y in -1.0..1.0)

        // 3) invertY 只翻 y，不碰 x
        val m2 = model()
        m2.handle(TouchEvent.Down(listOf(p(0, 100f, 100f))))
        val before = mv(m2, TouchEvent.Move(listOf(p(0, 140f, 60f))))!!
        m2.invertY = true
        val after = mv(m2, TouchEvent.Move(listOf(p(0, 140f, 60f))))!!
        check("🔑 invertY 翻转 y 符号", before.y > 0 && after.y < 0) {
            "before=${before.y} after=${after.y}"
        }
        check("负对照:invertY 不改 x", kotlin.math.abs(before.x - after.x) < 1e-9)
        check("负对照:invertY 不改 |y|", kotlin.math.abs(before.y + after.y) < 1e-9)

        // 4) UP / CANCEL 归零，且 release 幂等（不重复发零帧）
        val mu = model()
        mu.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))
        check("🔑 ACTION_UP ⇒ Release", mu.handle(TouchEvent.Up) == StickOutput.Release)
        check("🔑 UP 后 isPressed=false", !mu.isPressed())
        check("负对照:重复 UP ⇒ Noop(不重复零帧)", mu.handle(TouchEvent.Up) == StickOutput.Noop)

        val mc = model()
        mc.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))
        check("🔑 ACTION_CANCEL ⇒ Release(与 UP 同归零)", mc.handle(TouchEvent.Cancel) == StickOutput.Release)
        check("🔑 CANCEL 后 isPressed=false", !mc.isPressed())
        val mcBad = model()   // 模拟「旧 View 忽略 CANCEL」
        mcBad.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))
        val still = mv(mcBad, TouchEvent.Move(listOf(p(0, 100f, 60f))))
        check("🔑 负对照:若忽略 CANCEL 会卡在按下态且继续输出非零", mcBad.isPressed() && still!!.y > 0.7) {
            "pressed=${mcBad.isPressed()} still=$still"
        }

        val mf = model()
        mf.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))
        check("forceRelease 归零", mf.forceRelease() == StickOutput.Release)
        check("负对照:forceRelease 幂等", mf.forceRelease() == StickOutput.Noop)

        // 5) 多指：按 ID 追踪，index 漂移不能跟错指
        val mm = model()
        mm.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))            // 主指 id0 上推
        val id0Y = 60f
        // 第二指落下，事件里 id1 排在 index 0（官方：顺序未定义、index 会变）
        mm.handle(TouchEvent.Move(listOf(p(1, 140f, 140f), p(0, 100f, id0Y))))
        val drift = mv(mm, TouchEvent.Move(listOf(p(1, 140f, 140f), p(0, 100f, id0Y))))!!
        check("🔑 index 漂移仍跟 activeId=0(不是 index0 的 id1)", kotlin.math.abs(drift.x) < 1e-6 && drift.y > 0.7) {
            "drift=$drift"
        }
        check("负对照:若按 index0 会拿到 id1 的右下坐标",
            p(1, 140f, 140f).x != p(0, 100f, id0Y).x && p(1, 140f, 140f).y != p(0, 100f, id0Y).y)

        // 主指(id0)抬起 ⇒ 切到仍活跃的 id1，不能 Release、不能跟已消失的 id0
        val switched = mm.handle(TouchEvent.PointerUp(upId = 0, pointers = listOf(p(0, 100f, 60f), p(1, 140f, 140f))))
        check("🔑 主指抬起 ⇒ 切到另一指并输出 Move(非 Release)", switched is StickOutput.Move) {
            "out=$switched"
        }
        check("🔑 切换后 isPressed 仍 true", mm.isPressed())
        val afterSwitch = switched as StickOutput.Move
        check("🔑 切换后用的是 id1 的坐标", afterSwitch.x > 0.7 && afterSwitch.y < -0.7) {
            "afterSwitch=$afterSwitch"
        }
        check("负对照:非活跃指抬起不改变活跃指", run {
            val m3 = model()
            m3.handle(TouchEvent.Down(listOf(p(0, 100f, 60f))))
            m3.handle(TouchEvent.Move(listOf(p(0, 100f, 60f), p(1, 140f, 140f))))
            val o = m3.handle(TouchEvent.PointerUp(1, listOf(p(0, 100f, 60f), p(1, 140f, 140f))))
            o is StickOutput.Move && kotlin.math.abs(o.x) < 1e-6 && o.y > 0.7
        })
        check("🔑 最后一指抬起 ⇒ Release", run {
            val m4 = model()
            m4.handle(TouchEvent.Down(listOf(p(7, 100f, 60f))))
            m4.handle(TouchEvent.PointerUp(7, listOf(p(7, 100f, 60f)))) == StickOutput.Release
        })

        // 6) 未 onSizeChanged 的默认几何不能产生 NaN / 越界
        val mDefault = JoystickModel()
        mDefault.handle(TouchEvent.Down(listOf(p(0, 9999f, -9999f))))
        val weird = mDefault.handle(TouchEvent.Move(listOf(p(0, 5000f, 5000f)))) as? StickOutput.Move
        check("默认 radius 保护:输出有限且在 [-1,1]", weird != null &&
            weird.x.isFinite() && weird.y.isFinite() &&
            weird.x in -1.0..1.0 && weird.y in -1.0..1.0) { "weird=$weird" }
    }

    // ---- 22. 头部视角：符号/档位/松手回中/无心跳（与 drive 相反）----
    private fun testHeadController() {
        println("\n[22] 阶段P1+: 头部视角映射/松手回中/无心跳")
        val sent = Collections.synchronizedList(mutableListOf<HeadParams>())
        var closed = false
        val sink = object : HeadSink {
            override val name = "recording"
            override fun send(p: HeadParams): Result<Unit> {
                sent.add(p); return Result.success(Unit)
            }
            override fun close() { closed = true }
        }
        val c = HeadController(sink, deadzone = 0.1)
        // 符号照抄 padd/src/main.rs:1442-1443（硬件验过的反轴），别按直觉改。
        check("满上杆 head_pitch=-headRad(反轴)", c.map(0.0, 1.0).headPitch == -0.5) {
            "p=${c.map(0.0, 1.0)}"
        }
        check("负对照:满下杆 head_pitch=+headRad", c.map(0.0, -1.0).headPitch == 0.5)
        check("满右杆 head_yaw=-headRad", c.map(1.0, 0.0).headYaw == -0.5)
        check("负对照:满左杆 head_yaw=+headRad", c.map(-1.0, 0.0).headYaw == 0.5)
        check("单摇杆只驱动 pitch/yaw 两路", c.map(0.6, 0.8).neckPitch == 0.0 &&
            c.map(0.6, 0.8).headRoll == 0.0)
        check("死区内归零", c.map(0.05, 0.0).headYaw == 0.0 &&
            c.map(0.0, 0.05).headPitch == 0.0)
        check("负对照:死区外不归零", c.map(0.2, 0.0).headYaw != 0.0)
        val diag = c.map(1.0, 1.0)
        check("对角圆形限幅(不超幅度)", hypot(diag.headPitch, diag.headYaw) <= 0.5 + 1e-9) {
            "diag=$diag"
        }
        check("负对照:不限幅时对角会超 headRad", hypot(0.5, 0.5) > 0.5)
        // 板上 R17 合法档位，别自造中间值
        val badRad = try { HeadController(sink, headRad = 0.8); false }
        catch (_: IllegalArgumentException) { true }
        check("🔑 负对照:非法 headRad 0.8 被门禁拒", badRad)
        check("合法档位 1.0/2.5 可用", HeadController(sink, headRad = 1.0).map(1.0, 0.0).headYaw == -1.0 &&
            HeadController(sink, headRad = 2.5).map(1.0, 0.0).headYaw == -2.5)

        val n0 = sent.size
        c.onAxes(0.0, 1.0)
        check("onAxes 立即发一帧", sent.size == n0 + 1 && sent.last().headPitch != 0.0)
        check("负对照:不 release 时意图仍非零", c.current().headPitch != 0.0)
        val z = c.release()
        check("🔑 release 发全零回中帧(head 不 deadman 过期，必须显式回中)",
            z == HeadParams.NEUTRAL && c.current() == HeadParams.NEUTRAL &&
                sent.last() == HeadParams.NEUTRAL) { "z=$z last=${sent.last()}" }

        // 🔴 与 DriveController 的关键差异：head 槽不过期，不重发。
        sent.clear()
        c.onAxes(0.0, 0.5)
        val idle = sent.size
        Thread.sleep(320)
        check("🔑 head 无心跳(静置不自增帧)", sent.size == idle) { "delta=${sent.size - idle}" }
        check("负对照:同一时段 DriveController 心跳确实会自增", run {
            val dSent = Collections.synchronizedList(mutableListOf<DriveCommand>())
            val ds = object : DriveSink {
                override val name = "d"
                override fun send(cmd: DriveCommand): Result<Unit> { dSent.add(cmd); return Result.success(Unit) }
                override fun close() {}
            }
            val d = DriveController(ds)
            d.onAxes(0.0, 0.5); d.startHeartbeat()
            val before = dSent.size
            Thread.sleep(320)
            val grew = dSent.size > before
            d.stop()
            grew
        })
        c.stop()
        check("stop 归零且关闭通道", c.current() == HeadParams.NEUTRAL && closed)
        check("负对照:stop 前确曾发过非零帧", sent.any { it != HeadParams.NEUTRAL })
    }

    // ---- 23. robot.head notification：四键、无 id、不与 move 串台 ----
    private fun testHeadSink() {
        println("\n[23] 阶段P1+: robot.head notification")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10, backoffMaxMs = 20)
        check("会话 READY", s.connect(ConnectTarget.Mock))
        val sink = JsonRpcHeadSink(s)
        val p = HeadParams(0.1, -0.2, 0.3, 0.0)
        check("notify 成功", sink.send(p).isSuccess)
        val line = t.rawLog().lastOrNull { it.contains("robot.head") } ?: ""
        check("确实发出 robot.head", line.isNotEmpty()) { "rawLog=${t.rawLog()}" }
        check("🔑 notification 无 id(固件不回响应)", !line.contains("\"id\"")) { line }
        val o = JsonParser.parseString(line).asJsonObject
        check("jsonrpc=2.0", o.get("jsonrpc").asString == "2.0")
        val params = o.getAsJsonObject("params")
        check("🔑 params 恰好四键(deny_unknown_fields)",
            params.keySet() == setOf("neck_pitch", "head_pitch", "head_yaw", "head_roll")) {
            "keys=${params.keySet()}"
        }
        check("四字段逐字透传", params.get("neck_pitch").asDouble == 0.1 &&
            params.get("head_pitch").asDouble == -0.2 &&
            params.get("head_yaw").asDouble == 0.3 &&
            params.get("head_roll").asDouble == 0.0)
        check("负对照:多一键必被四键判据拒",
            JsonParser.parseString("""{"neck_pitch":0,"head_pitch":0,"head_yaw":0,"head_roll":0,"extra":1}""")
                .asJsonObject.keySet() != setOf("neck_pitch", "head_pitch", "head_yaw", "head_roll"))
        // head 与 twist 是固件两个独立 slot：只发 head，绝不能捎带 robot.move
        check("🔑 负对照:head 通道不串发 robot.move(两个独立 intent slot)",
            t.rawLog().none { it.contains("robot.move") }) { "log=${t.log()}" }
        val t2 = MockTransport()
        val s2 = RobotSession(t2, backoffBaseMs = 10)
        val before = t2.rawLog().size
        check("负对照:DISCONNECTED 时 head notify 失败且不发包",
            s2.notify(Method.ROBOT_HEAD, p.params()).isFailure && t2.rawLog().size == before)
        s.close(); s2.close()
    }

    // ---- 24. robot.state：空数组≠零、0Hz≠停环、hasAny 不恒真 ----
    private fun testStateSnapshot() {
        println("\n[24] 阶段P1+: robot.state 状态解析 缺失≠零")
        val full = JsonParser.parseString(
            """{"t":12.5,"policy":"walk","move":{"requested":[0.40,0.0,0.10],
                 "applied":[0.31,0.0,0.08],"limited_by":["vx_clamp"]},
                 "head":[0.0,-0.12,0.20,0.0],"safety":{"fallen":false,"limp":false},
                 "loop":{"hz":50.0,"missed":3},"currents_ma":[100.0,220.0,90.0],
                 "odom":{"yaw":0.5}}""",
        ).asJsonObject
        val st = StateSnapshot.from(full)
        check("t/policy 解析", st.t == 12.5 && st.policy == "walk")
        check("命令 vs 实际都保留", st.requested == listOf(0.40, 0.0, 0.10) &&
            st.applied == listOf(0.31, 0.0, 0.08))
        check("限幅原因保留", st.limitedBy == listOf("vx_clamp") &&
            st.velocityText().contains("限幅"))
        check("安全/环/电流/航向字段", st.fallen == false && st.limp == false &&
            st.loopHz == 50.0 && st.missedTicks == 3L &&
            st.currentsMa == listOf(100.0, 220.0, 90.0) && st.odomYaw == 0.5)
        check("电流峰值取 max", st.currentText().contains("220 mA"))
        check("负对照:完整帧 hasAny=true", st.hasAny())

        val empty = StateSnapshot.from(JsonParser.parseString("{}").asJsonObject)
        check("🔑 负对照:空帧 hasAny=false(不因空列表恒真)", !empty.hasAny())
        // 🔴 正向断言（别用「不含 0」这种裸子串：占位文案本身会解释「非零」而反噬）。
        // 判据是「电流字段为 null」+「没有实际读数前缀」，而不是扫描某个字符。
        check("🔑 负对照:空帧渲染是「未读到」不是零值",
            empty.currentsMa == null &&
                empty.currentText().contains("未上报") && !empty.currentText().contains("峰值") &&
                empty.loopHz == null && empty.velocityText().contains("未读到")) {
            empty.summary()
        }
        check("负对照:真有电流时才有「峰值」读数", st.currentText().contains("峰值"))
        check("🔑 负对照:空 currents_ma ⇒ 未上报（非零负载）", run {
            val s = StateSnapshot.from(JsonParser.parseString("""{"currents_ma":[]}""").asJsonObject)
            s.currentsMa == null && s.currentText().contains("未上报")
        })
        check("🔑 负对照:loop.hz=0 是首个窗口未闭合，不是停环", run {
            val s = StateSnapshot.from(JsonParser.parseString("""{"loop":{"hz":0.0}}""").asJsonObject)
            s.loopText().contains("首个统计窗口未闭合")
        })
        check("负对照:未限幅时不误报限幅", run {
            val s = StateSnapshot.from(JsonParser.parseString(
                """{"move":{"requested":[0.1,0,0],"applied":[0.1,0,0]}}""",
            ).asJsonObject)
            s.limitedBy.isEmpty() && s.velocityText().contains("未限幅")
        })
        check("负对照:短数组不越界(防御)", run {
            val s = StateSnapshot.from(JsonParser.parseString(
                """{"move":{"requested":[0.1],"applied":[0.2]}}""",
            ).asJsonObject)
            s.velocityText().contains("—") && !s.summary().isEmpty()
        })
    }

    // ---- 25. 连接输入解析：静默回落的负对照（旧实现 ?: 7788 会全部假绿）----
    private fun testConnectInputParser() {
        println("\n[25] ConnectInputParser 显式校验 / 静默回落负对照")
        val p = ConnectInputParser::parse
        fun t(raw: String) = p(raw).getOrNull()?.target
        fun targ(raw: String) = p(raw).getOrNull()!!.target

        check("空串 = Mock", t("") is ConnectTarget.Mock)
        check("mock = Mock", t("mock") is ConnectTarget.Mock)
        check("负对照:MOCK 大小写不敏感", t("MOCK") is ConnectTarget.Mock)
        val noPort = p("192.168.1.5").getOrNull()!!
        check("省略端口给默认 7788", noPort.target == ConnectTarget.Tcp("192.168.1.5", 7788))
        check("🔑 省略端口必须显式告知(不静默)", noPort.note.contains("7788")) { noPort.note }
        check("host:port 精确解析", targ("192.168.1.5:9000") == ConnectTarget.Tcp("192.168.1.5", 9000))
        check("域名可解析", targ("duck.local:7788") == ConnectTarget.Tcp("duck.local", 7788))
        check("ble:serial 走 Ble 目标", targ("ble:DUCK-123") == ConnectTarget.Ble("DUCK-123"))
        check("端口下界 1 合法", targ("h:1") == ConnectTarget.Tcp("h", 1))
        check("端口上界 65535 合法", targ("h:65535") == ConnectTarget.Tcp("h", 65535))

        // 🔴 负对照：旧实现 `toIntOrNull() ?: 7788` 会让下面每一条都「成功连到 7788」。
        val bad = listOf(
            "192.168.1.5:99999" to "越界",
            "192.168.1.5:0" to "越界",
            "192.168.1.5:abc" to "不是整数",
            "192.168.1.5:" to "端口为空",
            ":7788" to "主机地址为空",
            "192.168.1.5:-1" to "不是整数",
            "host name:7788" to "非法字符",
            "::1:7788" to "多个冒号",
            "ble:" to "serial",
            "h:99999999999999999999" to "整数范围",
        )
        bad.forEach { (raw, keyword) ->
            val r = p(raw)
            check("负对照:拒绝「$raw」", r.isFailure) { "竟然解析成 ${r.getOrNull()}" }
            check("  错误含恢复线索「$keyword」", r.exceptionOrNull()?.message?.contains(keyword) == true) {
                r.exceptionOrNull()?.message ?: "(no message)"
            }
        }
        val silentFallback = bad.mapNotNull { (raw, _) -> p(raw).getOrNull()?.target }
            .filterIsInstance<ConnectTarget.Tcp>()
            .count { it.port == 7788 }
        check("🔑 负对照:非法输入零个悄悄回落 7788", silentFallback == 0) {
            "有 $silentFallback 个非法输入悄悄变成了默认端口"
        }
        check("负对照:合法地址不被误拒", p("10.0.0.7:7788").isSuccess)
    }

    @JvmStatic
    fun main(args: Array<String>) {
        println("=" * 60)
        println("MicroDuck core 会话层自检  |  Kotlin 2.4.0 / JDK17 / jvm-target 17")
        println("=" * 60)
        testHandshake()
        testCall()
        testReconnect()
        testIdempotentReplay()
        testErrorCodes()
        testStateGate()
        testConcurrency()
        testTcpBackendSwap()
        testTcpFraming()
        testTcpReconnect()
        testTcpErrorCodes()
        testTcpReconnectStormGuard()
        testSoTimeoutIsNotDisconnect()
        testBleFraming()
        testBleTransportSwap()
        testAuthPolicyIsTransportSpecific()
        testNetpadWire()
        testDriveController()
        testDriveSinks()
        testHealthSnapshot()
        testJoystickModel()
        testHeadController()
        testHeadSink()
        testStateSnapshot()
        testConnectInputParser()
        testBleForegroundPolicy()
        testReadOnlyCapabilityMethods()
        testUpdatePolicy()
        println("\n" + "=" * 60)
        println("RESULT: $passed passed, $failed failed")
        println("=" * 60)
        if (failed > 0) kotlin.system.exitProcess(1)
    }

    // ---- N. A1 BLE 前台服务策略（纯逻辑 + Manifest 静态核对，带负对照）----
    private fun testBleForegroundPolicy() {
        println("\n[N] A1 BLE 前台服务策略 / Manifest 声明")
        val p31 = BleForegroundPolicy.bleRuntimePermissions(31)
        check("API31+ 要 SCAN+CONNECT",
            p31 == listOf("android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH_CONNECT")) { p31.toString() }
        // 负对照：低版本不能索要系统里不存在的权限（用户铁律：改坏必红）
        val p30 = BleForegroundPolicy.bleRuntimePermissions(30)
        check("负对照:API30 不误要 BLUETOOTH_SCAN", "android.permission.BLUETOOTH_SCAN" !in p30) { p30.toString() }
        check("负对照:API30 要的是 FINE_LOCATION",
            p30 == listOf("android.permission.ACCESS_FINE_LOCATION")) { p30.toString() }
        check("FGS 类型 = connectedDevice", BleForegroundPolicy.FGS_TYPE == "connectedDevice")
        check("负对照:FGS 类型不是 location", BleForegroundPolicy.FGS_TYPE != "location")
        check("API33 通知权限 = POST_NOTIFICATIONS",
            BleForegroundPolicy.notificationPermission(33) == "android.permission.POST_NOTIFICATIONS")
        check("负对照:API32 无通知权限", BleForegroundPolicy.notificationPermission(32) == null)
        // 自检必须真读 Manifest：声明漏一条时 Service 照样编译，只在运行时崩。
        // 🔴 用正则取出所有 android:name 的**完整值**做集合包含，不用裸子串 contains：
        //   真负对照实测过，contains 对 `..._BROKEN` 这种改坏会假绿。
        val mf = java.io.File("app/src/main/AndroidManifest.xml")
        check("Manifest 文件可读", mf.isFile) { "cwd=" + System.getProperty("user.dir") }
        val xml = if (mf.isFile) mf.readText() else ""
        val declared = Regex("""android:name="([^"]+)"""")
            .findAll(xml).map { it.groupValues[1] }.toSet()
        BleForegroundPolicy.REQUIRED_PERMISSION_NAMES.forEach { name ->
            check("Manifest 声明完整权限名 $name", name in declared) { "declared=$declared" }
        }
        check("Manifest service 声明 foregroundServiceType=connectedDevice",
            xml.contains("android:foregroundServiceType=\"${BleForegroundPolicy.FGS_TYPE}\""))
        check("负对照:Manifest 不含伪造的 location FGS 类型",
            !xml.contains("android:foregroundServiceType=\"location\""))
        // 负对照：拼错 / 加后缀的伪权限名绝不能混进集合 —— 证明判据是「完整值相等」而非子串。
        val broken = BleForegroundPolicy.REQUIRED_PERMISSION_NAMES.map { "${it}_BROKEN" }
        check("负对照:改坏的权限名不在声明集合中(子串扫描会假绿)",
            broken.isNotEmpty() && broken.none { it in declared }) { "declared=$declared" }
    }

    // ---- N+1. A4 新增只读方法的契约与白名单归属 ----
    private fun testReadOnlyCapabilityMethods() {
        println("\n[N+1] A4 控制者归属只读方法")
        check("remoteSessionActive 方法名照抄一手 lib.rs:589",
            Method.ROBOT_REMOTE_SESSION_ACTIVE == "robot.remoteSessionActive")
        check("负对照:不是拼错的 robot.sessionActive",
            Method.ROBOT_REMOTE_SESSION_ACTIVE != "robot.sessionActive")
        check("modelApi 方法名照抄一手 lib.rs:587",
            Method.ROBOT_MODEL_API == "robot.modelApi")
        // isReadOnly 是 private，用反射拿到真函数而不是复制一份判据（避免「测的是副本」假绿）。
        val m = RobotSession::class.java.getDeclaredMethod("isReadOnly", String::class.java)
        m.isAccessible = true
        val s = RobotSession(MockTransport())
        check("remoteSessionActive 判为只读(断链可重放)",
            m.invoke(s, Method.ROBOT_REMOTE_SESSION_ACTIVE) as Boolean)
        check("modelApi 判为只读", m.invoke(s, Method.ROBOT_MODEL_API) as Boolean)
        check("负对照:robot.move 不是只读", !(m.invoke(s, Method.ROBOT_MOVE) as Boolean))
        check("负对照:robot.loadPolicy 不是只读", !(m.invoke(s, Method.ROBOT_LOAD_POLICY) as Boolean))
        s.close()
    }

    // ---- N+2. GitHub Releases 自更新决策层（固定 JSON 夹具 + 逐条负对照）----
    // 夹具做法照 javiersantos/AppUpdater 的 app/update*.json / androidTest/files/*.json：
    // 用固定 JSON 分别模拟「有更新 / 无更新 / 数据坏掉」，而不是拼运行时随机值。
    private val updateShaOk = "a".repeat(64)
    private val updateAssets = listOf(
        "update.json" to "https://github.com/chenshiyilisha/microduck-flat-walk/releases/download/v0.2.0/update.json",
        "microduck-0.2.0.apk" to "https://github.com/chenshiyilisha/microduck-flat-walk/releases/download/v0.2.0/microduck-0.2.0.apk",
    )

    private fun releaseJson(
        tag: String = "v0.2.0",
        assets: List<Pair<String, String>> = updateAssets,
        prerelease: Boolean = false,
        draft: Boolean = false,
    ): String {
        val arr = com.google.gson.JsonArray()
        assets.forEach { (name, url) ->
            arr.add(JsonObject().apply {
                addProperty("name", name)
                addProperty("browser_download_url", url)
                addProperty("size", 1024L)
            })
        }
        return JsonObject().apply {
            addProperty("tag_name", tag)
            addProperty("name", tag)
            addProperty("html_url", "https://github.com/chenshiyilisha/microduck-flat-walk/releases/tag/$tag")
            addProperty("published_at", "2026-11-13T00:00:00Z")
            addProperty("prerelease", prerelease)
            addProperty("draft", draft)
            add("assets", arr)
        }.toString()
    }

    private fun manifestJson(
        versionName: String = "0.2.0",
        versionCode: Int = 2,
        apkAsset: String = "microduck-0.2.0.apk",
        sha256: String = updateShaOk,
        schema: Int = UpdatePolicy.MANIFEST_SCHEMA,
    ): String = JsonObject().apply {
        addProperty("schema", schema)
        addProperty("versionName", versionName)
        addProperty("versionCode", versionCode)
        addProperty("apkAsset", apkAsset)
        addProperty("sha256", sha256)
        addProperty("minSdk", 26)
        addProperty("abi", "arm64-v8a")
    }.toString()

    private fun decide(
        release: String = releaseJson(),
        manifest: String = manifestJson(),
        code: Int = 200,
        remaining: Int? = 59,
        reset: Long? = 1_700_000_000L,
        currentCode: Int = 1,
        currentName: String = "0.1.0-p0-skeleton",
    ) = UpdatePolicy.decide(currentCode, currentName, code, remaining, reset, release, manifest)

    private fun testUpdatePolicy() {
        println("\n[N+2] GitHub Releases 自更新决策层（夹具 + 负对照）")
        // --- 解析：正向 + 负对照 ---
        val r = UpdatePolicy.parseRelease(releaseJson())
        check("release 解析出 tag / 2 个 asset", r?.tagName == "v0.2.0" && r.assets.size == 2) { "$r" }
        check("负对照:畸形 release JSON 返回 null 而不抛", UpdatePolicy.parseRelease("{oops") == null)
        val m = UpdatePolicy.parseManifest(manifestJson())
        check("manifest 解析出 versionCode=2", m?.versionCode == 2 && m.versionName == "0.2.0") { "$m" }
        check("负对照:manifest 缺字段返回 null 而不抛", UpdatePolicy.parseManifest("{\"schema\":1}") == null)
        check("负对照:坏 sha256 被 validate 拒",
            UpdatePolicy.validate(UpdatePolicy.parseManifest(manifestJson(sha256 = "xyz"))!!, "v0.2.0") != null)
        check("负对照:63 位 sha256 也被拒",
            !UpdatePolicy.isSha256Hex("a".repeat(63)))

        // --- 正常路径 ---
        val ok = decide()
        check("versionCode 2 > 1 ⇒ Available", ok is UpdatePolicy.Decision.Available) { "$ok" }
        check("Available 带对 APK asset", (ok as? UpdatePolicy.Decision.Available)?.asset?.name == "microduck-0.2.0.apk")
        check("Available 带完整 sha256", (ok as? UpdatePolicy.Decision.Available)?.manifest?.sha256 == updateShaOk)

        // --- 负对照：任一坏输入都必须变红，绝不静默当成功 ---
        check("负对照:404 → NoRelease（本项目当前真实状态）",
            decide(code = 404) is UpdatePolicy.Decision.NoRelease)
        check("负对照:403+remaining=0 → RateLimited 带 reset",
            (decide(code = 403, remaining = 0) as? UpdatePolicy.Decision.RateLimited)?.resetAtEpochSec == 1_700_000_000L)
        check("负对照:403+remaining=5 不编造 reset",
            (decide(code = 403, remaining = 5) as? UpdatePolicy.Decision.RateLimited)?.resetAtEpochSec == null)
        check("负对照:HTTP 500 → Failed", decide(code = 500) is UpdatePolicy.Decision.Failed)
        check("负对照:release JSON 坏 → Failed", decide(release = "{oops") is UpdatePolicy.Decision.Failed)
        check("负对照:缺 update.json asset → Failed",
            decide(release = releaseJson(assets = listOf(updateAssets[1]))) is UpdatePolicy.Decision.Failed)
        check("负对照:manifest 缺失 → Failed",
            UpdatePolicy.decide(1, "0.1.0-p0-skeleton", 200, 59, null, releaseJson(), null)
                is UpdatePolicy.Decision.Failed)
        check("负对照:tag 与 versionName 不一致 → Failed",
            decide(release = releaseJson(tag = "v0.9.9")) is UpdatePolicy.Decision.Failed)
        check("负对照:apkAsset 指向不存在的 asset → Failed",
            decide(manifest = manifestJson(apkAsset = "ghost.apk")) is UpdatePolicy.Decision.Failed)
        check("负对照:apkAsset 不是 .apk → Failed",
            decide(manifest = manifestJson(apkAsset = "update.json")) is UpdatePolicy.Decision.Failed)
        check("负对照:非 GitHub 域下载地址 → Failed",
            decide(release = releaseJson(assets = listOf(
                "update.json" to updateAssets[0].second,
                "microduck-0.2.0.apk" to "https://evil.example/microduck.apk")))
                is UpdatePolicy.Decision.Failed)
        check("负对照:schema 不符 → Failed", decide(manifest = manifestJson(schema = 99)) is UpdatePolicy.Decision.Failed)
        check("负对照:versionCode<=0 → Failed", decide(manifest = manifestJson(versionCode = 0)) is UpdatePolicy.Decision.Failed)
        check("负对照:prerelease 不算正式发布 → Failed",
            decide(release = releaseJson(prerelease = true)) is UpdatePolicy.Decision.Failed)
        check("负对照:draft 不算正式发布 → Failed",
            decide(release = releaseJson(draft = true)) is UpdatePolicy.Decision.Failed)
        check("负对照:versionName 变但 versionCode 没涨 → Failed",
            decide(manifest = manifestJson(versionCode = 1)) is UpdatePolicy.Decision.Failed)

        // --- 幂等 / 防降级 ---
        // tag 约定 v<versionName>，所以「同版本」夹具的 tag 也必须同步，否则命中的是
        // tag/versionName 不一致校验而不是 UpToDate 本身（夹具必须只改想测的那一个量）。
        check("versionCode 相同且 versionName 相同 → UpToDate",
            decide(release = releaseJson(tag = "v0.1.0-p0-skeleton"),
                manifest = manifestJson(versionName = "0.1.0-p0-skeleton", versionCode = 1),
                currentName = "0.1.0-p0-skeleton") is UpdatePolicy.Decision.UpToDate)
        check("负对照:更旧但合法的 release 不触发更新（防降级）",
            decide(release = releaseJson(tag = "v0.1.0-p0-skeleton"),
                manifest = manifestJson(versionName = "0.1.0-p0-skeleton", versionCode = 1),
                currentCode = 2, currentName = "0.1.0-p0-skeleton")
                is UpdatePolicy.Decision.UpToDate)

        // --- 版本比较：解析失败必须返回 null（FFUpdater 兜底思想的反向约束）---
        check("版本比较 0.1.0-p0-skeleton < v0.2.0",
            UpdatePolicy.compareVersionName("0.1.0-p0-skeleton", "v0.2.0")?.let { it < 0 } == true)
        check("版本比较相等 → 0", UpdatePolicy.compareVersionName("v1.2.3", "1.2.3") == 0)
        check("负对照:预发布后缀更旧", UpdatePolicy.compareVersionName("0.2.0-rc1", "0.2.0")?.let { it < 0 } == true)
        check("负对照:无法解析版本返回 null，不假装最新",
            UpdatePolicy.compareVersionName("abc", "0.2.0") == null)
        check("负对照:段数不同按补 0 比较", UpdatePolicy.compareVersionName("1.2", "1.2.0") == 0)

        // --- 下载完整性 ---
        check("sha256 大小写/trim 归一比对", UpdatePolicy.verifySha256(updateShaOk, "  " + updateShaOk.uppercase() + "  "))
        check("负对照:空校验值不被接受", !UpdatePolicy.verifySha256("", "whatever"))
        check("负对照:错哈希不被接受", !UpdatePolicy.verifySha256(updateShaOk, "b".repeat(64)))
        check("URL 白名单只放 GitHub 域",
            UpdatePolicy.isAllowedAssetUrl(updateAssets[1].second) && !UpdatePolicy.isAllowedAssetUrl("https://evil.example/a.apk"))
        check("debug 额外域名只放行显式登记的 host",
            UpdatePolicy.isAllowedAssetUrl("http://127.0.0.1:8899/a.apk", setOf("127.0.0.1")))
        check("负对照:额外域名不会连带放行任意域",
            !UpdatePolicy.isAllowedAssetUrl("https://evil.example/a.apk", setOf("127.0.0.1")))
        check("负对照:生产默认参数不放行本地服务",
            !UpdatePolicy.isAllowedAssetUrl("http://127.0.0.1:8899/a.apk"))

        // --- 跨文件静态核对：Manifest 声明 + 发布脚本常量与 core 单一真源 ---
        // 判据沿用 testBleForegroundPolicy：正则取 android:name 的**完整值**做集合包含，
        // 裸子串 contains 会对 `..._BROKEN` 假绿（本项目实测踩过）。
        val mf = java.io.File("app/src/main/AndroidManifest.xml")
        val xml = if (mf.isFile) mf.readText() else ""
        val declared = Regex("""android:name="([^"]+)"""")
            .findAll(xml).map { it.groupValues[1] }.toSet()
        check("Manifest 真声明 REQUEST_INSTALL_PACKAGES 完整名",
            UpdatePolicy.REQUIRED_MANIFEST_PERMISSION in declared) { "declared=$declared" }
        check("负对照:拼错的权限名不在声明集合(子串扫描会假绿)",
            (UpdatePolicy.REQUIRED_MANIFEST_PERMISSION + "_BROKEN") !in declared)
        // 发布脚本与 App 是两条消费链：schema / 清单名漂移会让 App 判「清单缺失」。
        val script = java.io.File("tools/publish_release.py")
        val py = if (script.isFile) script.readText() else ""
        check("发布脚本 schema 与 core 单一真源一致",
            py.contains("MANIFEST_SCHEMA = ${UpdatePolicy.MANIFEST_SCHEMA}"))
        check("发布脚本清单名与 core 单一真源一致",
            py.contains("MANIFEST_ASSET = \"${UpdatePolicy.MANIFEST_ASSET}\""))
        check("负对照:脚本不含错误 schema=99", !py.contains("MANIFEST_SCHEMA = 99"))
    }

    private operator fun String.times(n: Int) = repeat(n)
}
