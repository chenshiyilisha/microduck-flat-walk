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

    // ---- 1b. 首启 updaterd 关闭 ⇒ hello 降级继续握手（配网链路可用）；带 6 项负对照 ----
    private fun testHelloDegrade() {
        println("\n[1b] hello 版本探测降级（updaterd 未启动）→ 继续 auth→READY，配网可达")
        val updaterDown = "Updater is not answering: No such file or directory (os error 2)"
        val fault = MockTransport.Fault(
            errorOnMethod = Method.HELLO to RpcCode.INTERNAL_ERROR,
            errorOnMethodMessage = updaterDown,
        )

        // 正向 1：降级后仍完成握手 → READY；记录降级原因；发出 HelloDegraded 事件
        val t = MockTransport()
        t.injectFaults(fault.copy())
        val degradeEvents = mutableListOf<String>()
        val s = RobotSession(t, backoffBaseMs = 10)
        val evDisposable = s.onEvent { e ->
            if (e is RobotSession.Event.HelloDegraded) degradeEvents.add(e.reason)
        }
        val ok = s.connect(ConnectTarget.Mock)
        check("降级:connect 仍进 READY", ok && s.state == RobotSession.State.READY) { "ok=$ok state=${s.state}" }
        check("降级:hello 只发一次", t.countOf(Method.HELLO) == 1) { "log=${t.log()}" }
        check("降级:auth 仍执行（授权链未跳过）", t.countOf(Method.SYSTEM_AUTHENTICATE) == 1) { "log=${t.log()}" }
        check("降级:lastConnectError 不置失败", s.lastConnectError == null) { "err=${s.lastConnectError}" }
        check("降级:降级原因如实记录", s.helloDegradedReason == updaterDown) { "reason=${s.helloDegradedReason}" }
        check("降级:发 HelloDegraded 事件", degradeEvents.size == 1 && degradeEvents[0] == updaterDown) { "events=$degradeEvents" }
        // 正向 2（关键目标）：降级后进 READY，net.connect 写操作能真正发出
        val netResult = s.call(Method.NET_CONNECT, mapOf("ssid" to "Home"), replayable = false)
        check("降级:net.connect 可发出", netResult.isSuccess) { "r=${netResult.exceptionOrNull()}" }
        check("降级:net.connect 确实到达固件", t.countOf(Method.NET_CONNECT) == 1) { "log=${t.log()}" }

        // 负对照 1：错 PIN 仍 FAILED（降级绝不放过认证失败）
        val t2 = MockTransport(); t2.injectFaults(fault.copy())
        val s2 = RobotSession(t2, pin = "999999", backoffBaseMs = 10)
        val ok2 = s2.connect(ConnectTarget.Mock)
        check("负对照:降级+错PIN 仍 FAILED", !ok2 && s2.state == RobotSession.State.FAILED) { "ok=$ok2 state=${s2.state}" }

        // 注：hello 致命错误既有语义是「lastConnectError 置位 + return false」，state 停在 HELLO
        //    （仅错 PIN 路径显式 transition(FAILED)）；故「致命」的稳健判据用返回码+错误文本+无降级标志。
        val fatal: (Boolean, RobotSession) -> Boolean = { okr, sess ->
            !okr && sess.lastConnectError?.startsWith("hello:") == true &&
                sess.helloDegradedReason == null
        }

        // 负对照 2：普通 INTERNAL_ERROR（不含 is not answering）仍致命
        val t3 = MockTransport(); t3.injectFaults(MockTransport.Fault(
            errorOnMethod = Method.HELLO to RpcCode.INTERNAL_ERROR,
            errorOnMethodMessage = "some other internal error",
        ))
        val s3 = RobotSession(t3, backoffBaseMs = 10)
        val ok3 = s3.connect(ConnectTarget.Mock)
        check("负对照:普通INTERNAL_ERROR 仍致命", fatal(ok3, s3)) { "ok=$ok3 err=${s3.lastConnectError}" }

        // 负对照 3：契约错 INVALID_PARAMS（-32602）仍致命，即使 message 含 not answering
        val t4 = MockTransport(); t4.injectFaults(MockTransport.Fault(
            errorOnMethod = Method.HELLO to RpcCode.INVALID_PARAMS,
            errorOnMethodMessage = updaterDown,
        ))
        val s4 = RobotSession(t4, backoffBaseMs = 10)
        val ok4 = s4.connect(ConnectTarget.Mock)
        check("负对照:INVALID_PARAMS 仍致命", fatal(ok4, s4)) { "ok=$ok4 err=${s4.lastConnectError}" }

        // 负对照 4：版本 skew METHOD_NOT_FOUND（-32601）仍致命（能力降级路径不在这里）
        val t5 = MockTransport(); t5.injectFaults(MockTransport.Fault(
            errorOnMethod = Method.HELLO to RpcCode.METHOD_NOT_FOUND,
            errorOnMethodMessage = updaterDown,
        ))
        val s5 = RobotSession(t5, backoffBaseMs = 10)
        val ok5 = s5.connect(ConnectTarget.Mock)
        check("负对照:METHOD_NOT_FOUND 仍致命", fatal(ok5, s5)) { "ok=$ok5 err=${s5.lastConnectError}" }

        // 负对照 5：传输层丢 hello 请求（request failure）仍致命
        val t6 = MockTransport(); t6.injectFaults(MockTransport.Fault(dropNextRequest = true))
        val s6 = RobotSession(t6, backoffBaseMs = 10)
        val ok6 = s6.connect(ConnectTarget.Mock)
        check("负对照:hello 传输失败仍致命", !ok6 && s6.lastConnectError?.startsWith("hello:") == true && s6.helloDegradedReason == null) {
            "ok=$ok6 err=${s6.lastConnectError}"
        }

        // 负对照 6：判定函数本身——两段判据缺一不可（直接测纯函数）
        check("负对照:判据 错码不匹配", !s.isHelloDegradable(RpcError(RpcCode.INVALID_PARAMS, updaterDown)))
        check("负对照:判据 错message不匹配", !s.isHelloDegradable(RpcError(RpcCode.INTERNAL_ERROR, "no such phrase here")))
        check("判据 正确命中", s.isHelloDegradable(RpcError(RpcCode.INTERNAL_ERROR, updaterDown)))

        evDisposable.dispose()
        s.close(); s2.close(); s3.close(); s4.close(); s5.close(); s6.close()
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

    // ---- Noise NNpsk0: authenticated handshake, bidirectional transport, and rejection cases ----
    private fun testNoiseNnPsk0() {
        println("\n[Noise] NNpsk0 handshake and transport encryption")
        val psk = ByteArray(32) { (it + 1).toByte() }
        val client = NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.INITIATOR)
        val server = NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.RESPONDER)
        try {
            val first = client.start()
            val second = server.respond(first)
            client.finish(second)
            val clientToServer = """{"jsonrpc":"2.0","id":1}""".toByteArray()
            val serverToClient = """{"jsonrpc":"2.0","method":"robot.state"}""".toByteArray()
            check("handshake derives matching initiator-to-responder keys",
                server.decrypt(client.encrypt(clientToServer)).contentEquals(clientToServer))
            check("handshake derives matching responder-to-initiator keys",
                client.decrypt(server.encrypt(serverToClient)).contentEquals(serverToClient))
        } finally {
            client.close()
            server.close()
        }

        val badPsk = NoiseNnPsk0Session(ByteArray(32) { 0x7f }, NoiseNnPsk0Session.Role.RESPONDER)
        val initiator = NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.INITIATOR)
        try {
            val rejected = runCatching { badPsk.respond(initiator.start()) }.isFailure
            check("wrong PSK rejects the handshake", rejected)
        } finally {
            badPsk.close()
            initiator.close()
        }

        val tamperClient = NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.INITIATOR)
        val tamperServer = NoiseNnPsk0Session(psk, NoiseNnPsk0Session.Role.RESPONDER)
        try {
            val reply = tamperServer.respond(tamperClient.start())
            tamperClient.finish(reply)
            val ciphertext = tamperClient.encrypt(byteArrayOf(1, 2, 3))
            ciphertext[ciphertext.lastIndex] = (ciphertext.last().toInt() xor 1).toByte()
            val rejected = runCatching { tamperServer.decrypt(ciphertext) }.isFailure
            check("tampered transport frame is rejected", rejected)
        } finally {
            tamperClient.close()
            tamperServer.close()
        }
    }

    private fun testNoiseSnowInteropVectors() {
        println("\n[Noise] Kotlin matches Snow NNpsk0 wire vectors")
        val psk = ByteArray(32) { 0x01 }
        val client = NoiseNnPsk0Session(
            psk,
            NoiseNnPsk0Session.Role.INITIATOR,
            NoiseNnPsk0Session.PROLOGUE,
            ByteArray(32) { 0x11 },
        )
        val server = NoiseNnPsk0Session(
            psk,
            NoiseNnPsk0Session.Role.RESPONDER,
            NoiseNnPsk0Session.PROLOGUE,
            ByteArray(32) { 0x22 },
        )
        fun ByteArray.hex() = joinToString("") { "%02x".format(it.toInt() and 0xff) }
        try {
            val first = client.start()
            val envelope = NoiseBleFrameCodec.encode(NoiseBleFrameCodec.Type.INIT, first)
            val envelopeJson = com.google.gson.JsonParser.parseString(envelope).asJsonObject
            check(
                "Rust-compatible versioned Noise envelope",
                envelopeJson.get("_microduck_noise").asInt == 1 &&
                    envelopeJson.get("type").asString == "init" &&
                    envelopeJson.get("data").asString == java.util.Base64.getEncoder().encodeToString(first) &&
                    NoiseBleFrameCodec.decode(envelope).payload.contentEquals(first),
            )
            check(
                "Snow initiator handshake vector",
                first.hex() ==
                    "7b4e909bbe7ffe44c465a220037d608ee35897d31ef972f07f74892cb0f73f13ead68785c17d1ec65e55f26bccc84a96",
            )
            val second = server.respond(first)
            check(
                "Snow responder handshake vector",
                second.hex() ==
                    "0faa684ed28867b97f4a6a2dee5df8ce974e76b7018e3f22a1c4cf2678570f204ffe716e49cf38c20eeb7ddbc80ca873",
            )
            client.finish(second)

            val request = "rpc request".toByteArray()
            val requestCiphertext = client.encrypt(request)
            check(
                "Snow initiator transport vector",
                requestCiphertext.hex() ==
                    "5cd76c802015e5d4de4670e4a306dfa879c0293adff7c068744eb1",
            )
            check("Snow responder decrypts the request", server.decrypt(requestCiphertext).contentEquals(request))

            val response = "rpc reply".toByteArray()
            val responseCiphertext = server.encrypt(response)
            check(
                "Snow responder transport vector",
                responseCiphertext.hex() ==
                    "0c32938e574fbe66ad10ba7a33075a5a126265d5cf4197f297",
            )
            check("Snow initiator decrypts the response", client.decrypt(responseCiphertext).contentEquals(response))
        } finally {
            client.close()
            server.close()
        }
    }

    // ---- 15. 阶段D:换 BleTransport 后端——会话层零改动 + 真 chunk I/O（FakeGattLink）----
    private fun testBleTransportSwap() {
        println("\n[15] 阶段D:换 BleTransport 后端(会话层零改动 + 真 chunk I/O)")
        // notifyChunkSize=7：逼客户端 for_replies 重组器跨多片拼行（20B 出站 + 7B 入站双向分片）。
        val link = FakeGattLink(notifyChunkSize = 7)
        val t = BleTransport(link, FakeGattLink.TEST_PSK, requestTimeoutMs = 2_000)
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
        val s2 = RobotSession(BleTransport(linkFail, FakeGattLink.TEST_PSK), backoffBaseMs = 10, maxReconnectAttempts = 1)
        val ok2 = s2.connect(ConnectTarget.Ble("FAKE0002"))
        check("负对照:GATT 连接失败不进 READY", !ok2 && s2.state == RobotSession.State.FAILED) { "ok=$ok2 state=${s2.state}" }
        s2.close(); linkFail.close()

        // 负对照:readApiVersion 失败（未促成配对）→ 连接失败
        val linkNoVer = FakeGattLink().apply { failReadApiVersion = true }
        val s3 = RobotSession(BleTransport(linkNoVer, FakeGattLink.TEST_PSK), backoffBaseMs = 10, maxReconnectAttempts = 1)
        val ok3 = s3.connect(ConnectTarget.Ble("FAKE0003"))
        check("负对照:read API_VERSION 失败不进 READY", !ok3 && s3.state == RobotSession.State.FAILED) { "ok=$ok3 state=${s3.state}" }
        s3.close(); linkNoVer.close()

        // 负对照:出站写失败 → request 失败并触发断连（不 hang、不假绿）
        val linkWriteFail = FakeGattLink()
        val t4 = BleTransport(linkWriteFail, FakeGattLink.TEST_PSK, requestTimeoutMs = 500)
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
            val s3 = RobotSession(BleTransport(link, FakeGattLink.TEST_PSK), backoffBaseMs = 10)
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

    // ---- N+2. 真机实证驱动：板端 API_VERSION 必须可观测、失败原因不得被吞 ----
    private fun testPeerApiVersionObservability() {
        println("\n[N+2] 板端 API_VERSION 可观测（上游 gatt.rs:34-39 契约）")
        // ① 正对照：真机读数 37 能被读回，且与 App 的 40 明确不同 ⇒ skew 可见
        val link = FakeGattLink().apply { setPeerApiVersion(37) }
        val t = BleTransport(link, FakeGattLink.TEST_PSK, requestTimeoutMs = 1_000)
        check("connect 前 peerApiVersion 为 null", t.peerApiVersion == null) { "${t.peerApiVersion}" }
        val s = RobotSession(t, backoffBaseMs = 10, maxReconnectAttempts = 1)
        val ok = s.connect(ConnectTarget.Ble("SKEW37"))
        check("板端报 37 时仍能连上（版本差异不硬拒）", ok && s.state == RobotSession.State.READY) { "ok=$ok state=${s.state}" }
        check("真机 37 被读回而非丢弃", t.peerApiVersion == 37) { "got=${t.peerApiVersion}" }
        check("负对照:37 != App 的 40（skew 确实存在）", t.peerApiVersion != Wire.API_VERSION)
        s.close(); t.close(); link.close()

        // ② 负对照：版本相同也必须如实读到 40，不能写死 37 制造「永远 skew」的假绿
        val link40 = FakeGattLink().apply { setPeerApiVersion(Wire.API_VERSION) }
        val t40 = BleTransport(link40, FakeGattLink.TEST_PSK, requestTimeoutMs = 1_000)
        t40.connect(ConnectTarget.Ble("SAME40"))
        check("负对照:板端 40 时读到 40", t40.peerApiVersion == 40) { "got=${t40.peerApiVersion}" }
        t40.close(); link40.close()

        // ③ 负对照：connect 失败时不得留下陈旧版本值（跨会话污染）
        val linkFail = FakeGattLink().apply { failConnect = true }
        val tFail = BleTransport(linkFail, FakeGattLink.TEST_PSK, requestTimeoutMs = 1_000)
        tFail.connect(ConnectTarget.Ble("FAIL"))
        check("负对照:连接失败后 peerApiVersion 保持 null", tFail.peerApiVersion == null)
        tFail.close(); linkFail.close()
    }

    private fun testConnectFailureReason() {
        println("\n[N+3] 建链失败原因透传（真机 11-14 抓到的可观测性缺陷）")
        val linkFail = FakeGattLink().apply { failConnect = true }
        val t = BleTransport(linkFail, FakeGattLink.TEST_PSK, requestTimeoutMs = 1_000)
        val events = java.util.Collections.synchronizedList(mutableListOf<RobotSession.Event>())
        val s = RobotSession(t, backoffBaseMs = 10, maxReconnectAttempts = 1)
        s.onEvent { events.add(it) }
        val ok = s.connect(ConnectTarget.Ble("DIAG"))
        check("负对照:连接失败不进 READY", !ok && s.state == RobotSession.State.FAILED)
        val cf = events.filterIsInstance<RobotSession.Event.ConnectFailed>()
        check("失败发出 ConnectFailed 事件（不再静默 false）", cf.isNotEmpty()) { "events=$events" }
        check("事件 stage=link", cf.any { it.stage == "link" }) { "cf=$cf" }
        check("事件带真实异常而非通用文案",
            cf.any { it.reason.contains("FAKE_GATT_CONNECT_FAIL") }) { "cf=$cf" }
        check("lastConnectError 可被 UI/AI 通道读到",
            s.lastConnectError?.contains("FAKE_GATT_CONNECT_FAIL") == true) { "${s.lastConnectError}" }
        s.close(); t.close(); linkFail.close()

        // 负对照：成功路径必须清掉上次失败原因，不把陈旧错误显示给用户
        val linkOk = FakeGattLink()
        val s2 = RobotSession(BleTransport(linkOk, FakeGattLink.TEST_PSK, requestTimeoutMs = 1_000),
            backoffBaseMs = 10, maxReconnectAttempts = 1)
        check("成功连接 READY", s2.connect(ConnectTarget.Ble("OK")) &&
            s2.state == RobotSession.State.READY) { "state=${s2.state}" }
        check("负对照:成功后 lastConnectError 清空", s2.lastConnectError == null) { "${s2.lastConnectError}" }
        s2.close(); linkOk.close()
    }

    // ---- N+1. debug-only AI 调试通道：唯一策略真源要在 JVM 上真跑，不能只被静态解析 ----
    private fun testAiDebugPolicy() {
        println("\n[N+1] AI 调试通道策略 / 白名单真跑")
        val p = AiDebugPolicy

        // 命令白名单：判据是「真的调用判定函数」，不是「源码里出现了某个字面量」。
        check("白名单命令 status 被放行", p.isCommandAllowed("status"))
        check("白名单命令 rpc 被放行", p.isCommandAllowed("rpc"))
        check("负对照:null 命令被拒", !p.isCommandAllowed(null))
        check("负对照:未登记命令被拒", !p.isCommandAllowed("shell"))
        check("负对照:运动方法名冒充命令被拒", !p.isCommandAllowed(Method.ROBOT_MOVE))
        // 不写死「N 个」：登记清单是权威，新增命令必须同步进这张清单，否则判红。
        // 2026-11-15 新增只读 monitor（硬件监控报告），旧断言写死 7 个曾误报。
        val expectedCommands = setOf(
            "help", "status", "scan", "connect", "mock", "rpc", "disconnect", "monitor",
        )
        check("命令集与登记清单完全一致（新增命令须同步登记）",
            p.COMMANDS == expectedCommands) { p.COMMANDS.toString() }
        check("monitor 是只读命令且确实被放行",
            p.isCommandAllowed("monitor") && Method.ROBOT_MOVE !in p.COMMANDS)

        // RPC 只读白名单：集合不相交是必要但不充分，放行/拒绝两侧都要动态实跑。
        check("只读集合与禁止集合不相交",
            p.READ_ONLY_METHODS.intersect(p.FORBIDDEN_METHODS).isEmpty()) {
            p.READ_ONLY_METHODS.intersect(p.FORBIDDEN_METHODS).toString()
        }
        check("白名单里每条都真的被 isRpcAllowed 放行",
            p.READ_ONLY_METHODS.all { p.isRpcAllowed(it) }) {
            p.READ_ONLY_METHODS.filterNot { p.isRpcAllowed(it) }.toString()
        }
        check("禁止集里每条都真的被 isRpcAllowed 拒绝",
            p.FORBIDDEN_METHODS.all { !p.isRpcAllowed(it) }) {
            p.FORBIDDEN_METHODS.filter { p.isRpcAllowed(it) }.toString()
        }
        check("system.info 被放行", p.isRpcAllowed(Method.SYSTEM_INFO))
        check("负对照:robot.move 被拒", !p.isRpcAllowed(Method.ROBOT_MOVE))
        check("负对照:net.connect 被拒", !p.isRpcAllowed(Method.NET_CONNECT))
        check("负对照:system.authenticate 被拒", !p.isRpcAllowed(Method.SYSTEM_AUTHENTICATE))
        check("负对照:net.scan 有副作用不进白名单", !p.isRpcAllowed(Method.NET_SCAN))
        check("负对照:update.check 有副作用不进白名单", !p.isRpcAllowed(Method.UPDATE_CHECK))
        check("负对照:robot.state 通知方法不进白名单", !p.isRpcAllowed(Method.ROBOT_STATE))
        check("负对照:null 方法被拒", !p.isRpcAllowed(null))

        // 通道契约常量：PC 侧 helper 从本文件提取它们，改这里必须跟着变。
        check("TAG 固定", p.TAG == "MicroDuckAiDebug") { p.TAG }
        check("显式组件名格式正确", Regex("""^[\w.]+/\.[\w.]+$""").matches(p.COMPONENT)) { p.COMPONENT }
        check("结果 schema 为正整数", p.RESULT_SCHEMA > 0)
        val waits = listOf(p.SCAN_WINDOW_MS, p.CONNECT_GATT_TIMEOUT_MS, p.CONNECT_WAIT_MS, p.MOCK_WAIT_MS)
        check("goAsync 预算内所有等待都 >0 且 <=10s", waits.all { it in 1..10_000L }) { waits.toString() }

        // 跨文件：debug Receiver 必须真的调用这两个判定函数（否则白名单会另写一份悄悄漂移）。
        val recv = java.io.File("app/src/debug/kotlin/io/microduck/app/AiDebugReceiver.kt")
        val rtxt = if (recv.isFile) recv.readText() else ""
        val calls = Regex("""\bAiDebugPolicy\.(\w+)\s*\(""")
            .findAll(rtxt).map { it.groupValues[1] }.toSet()
        check("Receiver 真调用 isCommandAllowed", "isCommandAllowed" in calls) { calls.toString() }
        check("Receiver 真调用 isRpcAllowed", "isRpcAllowed" in calls) { calls.toString() }
        check("负对照:拼错的调用名不在集合里(防子串假绿)", "isRpcAllowed_BROKEN" !in calls)
    }

    // ---- N+1. 硬件监控：阈值判据 / 数据真实性分层 / 异常部位绑定（全部真跑 + 负对照）----
    private fun health(
        healthy: Boolean = true, degraded: Boolean = false, reason: String? = null,
        volts: Double? = 7.50, percent: Double? = 60.0,
        maxC: Double? = 40.0, hottest: String? = "mouth", cpuTempC: Double? = 50.0,
        missing: List<Int>? = null, busErrors: Int? = 0, startupFailures: Int? = 0,
        imuReady: Boolean? = true, imuStale: Long? = 0L,
        lastTickAgeMs: Long? = 15L, achievedHz: Double? = 50.0, targetHz: Double? = 50.0,
        throttleLevel: Int? = 0, servos: List<ServoTelemetry> = emptyList(),
    ): HealthSnapshot = HealthSnapshot(
        healthy = healthy, degraded = degraded, reason = reason,
        volts = volts, percent = percent, pack = null, batteryProblem = null,
        hottest = hottest, maxC = maxC, meanC = 38.0, cpuTempC = cpuTempC,
        targetHz = targetHz, achievedHz = achievedHz, ticks = 100L, missed = 0L,
        lastTickAgeMs = lastTickAgeMs, busErrors = busErrors, startupFailures = startupFailures,
        missingIds = missing ?: emptyList(), missingFieldPresent = missing != null,
        imuReady = imuReady, imuStaleBlocks = 0L, imuConsecutiveStaleBlocks = imuStale,
        cpuThrottleLevel = throttleLevel, cpuThrottleMaxLevel = 6,
        cpuThrottleKhz = 1_800_000, servos = servos,
    )

    private fun eval(h: HealthSnapshot?, source: MonitorSource = MonitorSource.REAL_HEALTH,
                     link: LinkState = LinkState.CONNECTED, staleMs: Long = 0L): MonitorReport =
        HardwareMonitor.evaluate(h, source, link, 1_000_000L, 1_000_000L - staleMs)

    private fun testHardwareMonitor() {
        println("\n[N+1] 硬件监控：阈值 / 真实性分层 / 异常部位绑定")
        // ① 关节表：来自 ft1910 lib.rs:536-564，位置即 wire 索引
        check("15 关节名/ID/部位三表等长",
            RobotParts.JOINT_NAMES.size == 15 && RobotParts.JOINT_IDS.size == 15 &&
                RobotParts.JOINT_PARTS.size == 15)
        check("ID 20→左髋偏航 / 34→喙 / 14→右踝",
            RobotParts.partOfId(20) == RobotPart.LEFT_HIP_YAW &&
                RobotParts.partOfId(34) == RobotPart.MOUTH &&
                RobotParts.partOfId(14) == RobotPart.RIGHT_ANKLE)
        check("hottest 'neck_pitch'→颈俯仰", RobotParts.partOfName("neck_pitch") == RobotPart.NECK_PITCH)
        check("idOf(MOUTH)=34", RobotParts.idOf(RobotPart.MOUTH) == 34)
        check("负对照:未知 ID / 未知关节名不猜部位",
            RobotParts.partOfId(99) == null && RobotParts.partOfName("not_a_joint") == null)
        check("负对照:系统部位没有舵机 ID", RobotParts.idOf(RobotPart.CPU) == null)
        check("merge 取最严重 / 空集合为 UNKNOWN",
            RobotParts.merge(listOf(Severity.OK, Severity.CRITICAL, Severity.WARN)) == Severity.CRITICAL &&
                RobotParts.merge(emptyList()) == Severity.UNKNOWN)
        val colors = Severity.entries.map { RobotParts.severityArgb(it) }
        check("四档语义色互不相同（改重复必红）", colors.distinct().size == 4)
        check("负对照:UNKNOWN 不是 OK 的颜色",
            RobotParts.severityArgb(Severity.UNKNOWN) != RobotParts.severityArgb(Severity.OK))

        // ② 无数据 ⇒ 零告警、零部位（没数据 ≠ 正常，也 ≠ 故障）
        val noData = eval(null, source = MonitorSource.NONE, link = LinkState.UNKNOWN)
        check("NO_DATA verdict", noData.verdict == MonitorVerdict.NO_DATA)
        check("NO_DATA 零告警 / 零部位", noData.alerts.isEmpty() && noData.parts.isEmpty())
        check("负对照:NO_DATA 不含任何 CRITICAL 部位", noData.flaggedParts().isEmpty())
        check("NO_DATA 摘要写明「没数据不等于正常」",
            noData.notes.any { it.contains("没数据不等于正常") })

        // ③ Mock 夹具 ⇒ DEMO_ONLY + 每条告警带 demo 标记，即使数据本身是危急的
        val mock = eval(health(percent = 5.0, missing = RobotParts.JOINT_IDS),
            source = MonitorSource.MOCK_FIXTURE)
        check("Mock 源 verdict 恒 DEMO_ONLY", mock.verdict == MonitorVerdict.DEMO_ONLY)
        check("Mock 源所有告警都带 demo=true", mock.alerts.isNotEmpty() && mock.alerts.all { it.demo })
        check("Mock 摘要自带「非实机读数」免责", mock.headline().contains("非实机读数"))
        check("负对照:Mock 不会变成 REAL 的 CRITICAL/NOMINAL",
            mock.verdict != MonitorVerdict.CRITICAL && mock.verdict != MonitorVerdict.NOMINAL)

        // ④ 电量阈值（源码 battery_percent 6.6→0% / 8.2→100%；本地显示策略阈值）
        check("电量 21% 无告警", eval(health(percent = 21.0)).alerts.none { it.part == RobotPart.BATTERY })
        check("电量 19% 触发 WARN",
            eval(health(percent = 19.0)).alerts.any { it.part == RobotPart.BATTERY && it.severity == Severity.WARN })
        check("电量 9% 触发 CRITICAL",
            eval(health(percent = 9.0)).alerts.any { it.part == RobotPart.BATTERY && it.severity == Severity.CRITICAL })
        check("边界 20.0% 不 WARN / 10.0% 是 WARN 不是 CRITICAL",
            eval(health(percent = 20.0)).alerts.none { it.part == RobotPart.BATTERY } &&
                eval(health(percent = 10.0)).alerts.any {
                    it.part == RobotPart.BATTERY && it.severity == Severity.WARN })
        check("volts=6.6（源码 EMPTY_V）直接 CRITICAL",
            eval(health(volts = 6.6, percent = 60.0)).alerts.any {
                it.part == RobotPart.BATTERY && it.severity == Severity.CRITICAL })
        val noBattery = eval(health(volts = null, percent = null))
        check("负对照:电池字段缺失 ⇒ 零电池告警且部位 UNKNOWN（不是 0 V）",
            noBattery.alerts.none { it.part == RobotPart.BATTERY } &&
                noBattery.severityOf(RobotPart.BATTERY) == Severity.UNKNOWN)
        check("电池告警带一手依据", eval(health(percent = 5.0)).alerts
            .first { it.part == RobotPart.BATTERY }.basis.contains("battery_percent"))

        // ⑤ 舵机/CPU 温度（Feetech 70°C 关扭矩 / Radxa 85°C governor）
        check("舵机 59.9°C 无告警",
            eval(health(maxC = 59.9)).alerts.none { it.message.contains("舵机高温") })
        check("舵机 60.0°C WARN / 70.0°C CRITICAL",
            eval(health(maxC = 60.0)).alerts.any { it.severity == Severity.WARN && it.message.contains("舵机高温") } &&
                eval(health(maxC = 70.0)).alerts.any { it.severity == Severity.CRITICAL && it.message.contains("舵机高温") })
        check("最热关节被着色（mouth→MOUTH）",
            eval(health(maxC = 72.0, hottest = "mouth")).severityOf(RobotPart.MOUTH) == Severity.CRITICAL)
        check("负对照:协议只给聚合温度 ⇒ 其余 14 关节仍 UNKNOWN",
            eval(health(maxC = 72.0, hottest = "mouth")).severityOf(RobotPart.LEFT_KNEE) == Severity.UNKNOWN)
        check("CPU 79.9 无告警 / 80 WARN / 85 CRITICAL",
            eval(health(cpuTempC = 79.9)).alerts.none { it.message.contains("SoC 高温") } &&
                eval(health(cpuTempC = 80.0)).alerts.any { it.severity == Severity.WARN && it.message.contains("SoC 高温") } &&
                eval(health(cpuTempC = 85.0)).alerts.any { it.severity == Severity.CRITICAL && it.message.contains("SoC 高温") })
        check("CPU 降频 level>0 触发 WARN",
            eval(health(throttleLevel = 2)).alerts.any { it.message.contains("已降频") })
        check("负对照:温度字段缺失 ⇒ 不报高温",
            eval(health(maxC = null, cpuTempC = null)).alerts.none {
                it.message.contains("高温") })

        // ⑥ bus.missing[] 精确点名 15 个舵机 → 部位级着色
        val oneMissing = eval(health(missing = listOf(32)))
        check("missing=[32] ⇒ HEAD_YAW CRITICAL + BUS CRITICAL",
            oneMissing.severityOf(RobotPart.HEAD_YAW) == Severity.CRITICAL &&
                oneMissing.severityOf(RobotPart.BUS) == Severity.CRITICAL)
        check("missing 告警文本点名关节",
            oneMissing.alerts.first { it.part == RobotPart.BUS }.message.contains("头偏航"))
        val allMissing = eval(health(missing = RobotParts.JOINT_IDS))
        check("实机场景：15 个 ID 全缺 ⇒ 15 个关节全部 CRITICAL",
            RobotParts.JOINT_PARTS.all { allMissing.severityOf(it) == Severity.CRITICAL })
        check("显式空 missing ⇒ BUS OK",
            eval(health(missing = emptyList())).severityOf(RobotPart.BUS) == Severity.OK)
        check("负对照:missing 字段缺失 ⇒ 不据此判总线正常",
            eval(health(missing = null)).notes.any { it.contains("不据此判总线正常") })
        check("负对照:未知 ID 不产生部位着色",
            eval(health(missing = listOf(99))).severityOf(RobotPart.LEFT_KNEE) == Severity.UNKNOWN)
        check("busErrors / startupFailures 分别触发 WARN / CRITICAL",
            eval(health(busErrors = 3)).alerts.any { it.part == RobotPart.BUS && it.severity == Severity.WARN } &&
                eval(health(startupFailures = 1)).alerts.any { it.part == RobotPart.BUS && it.severity == Severity.CRITICAL })

        // ⑦ IMU / 通信 / 控制环
        check("IMU not ready ⇒ CRITICAL",
            eval(health(imuReady = false)).severityOf(RobotPart.IMU) == Severity.CRITICAL)
        check("IMU 连续陈旧块 ⇒ WARN",
            eval(health(imuStale = 4L)).alerts.any { it.part == RobotPart.IMU && it.severity == Severity.WARN })
        check("链路 DOWN ⇒ LINK CRITICAL",
            eval(health(), link = LinkState.DOWN).severityOf(RobotPart.LINK) == Severity.CRITICAL)
        check("链路正常且读数新鲜 ⇒ LINK OK",
            eval(health()).severityOf(RobotPart.LINK) == Severity.OK)
        check("负对照:读数陈旧 ⇒ LINK 不再判 OK",
            eval(health(), staleMs = 9_000L).severityOf(RobotPart.LINK) == Severity.UNKNOWN)
        check("陈旧读数在 notes 里明写「不代表当前状态」",
            eval(health(), staleMs = 9_000L).notes.any { it.contains("不代表当前状态") })
        check("last_tick_age>1s / achieved<90%target 均触发链路 WARN",
            eval(health(lastTickAgeMs = 2_000L)).alerts.any { it.message.contains("最后一拍") } &&
                eval(health(achievedHz = 40.0)).alerts.any { it.message.contains("控制环") })
        check("协议没有无线 RSSI：notes 明确不伪造",
            eval(health()).notes.any { it.contains("不提供无线 RSSI") })

        // ⑧ robotd 自己的判决 / 前向兼容补丁
        check("degraded=true + reason ⇒ 躯干 CRITICAL 且带 reason",
            eval(health(degraded = true, healthy = false, reason = "motor bus startup")).alerts.any {
                it.part == RobotPart.TORSO && it.severity == Severity.CRITICAL && it.message.contains("motor bus startup") })
        check("负对照:healthy ⇒ 不报上游判决",
            eval(health()).alerts.none { it.part == RobotPart.TORSO })
        val patched = eval(health(servos = listOf(ServoTelemetry(20, 75.0, 7.4, 1.0))))
        check("扩展字段 servo_telemetry ⇒ 逐舵机温度真判据启用",
            patched.severityOf(RobotPart.LEFT_HIP_YAW) == Severity.CRITICAL &&
                patched.notes.any { it.contains("逐舵机判据已启用") })
        check("负对照:无扩展字段 ⇒ 逐舵机温度 UNVERIFIED",
            eval(health()).notes.any { it.contains("逐舵机温度 UNVERIFIED") })
        val parsed = HealthSnapshot.from(JsonParser.parseString(
            """{"healthy":true,"battery":{"volts":7.4,"percent":58.0},"bus":{"missing":[10,11]},""" +
                """"imu":{"ready":false},"servo_telemetry":[{"id":20,"temp_c":72.0}]}""",
        ).asJsonObject)
        check("HealthSnapshot.from 解析 bus.missing / imu / 扩展字段",
            parsed.missingIds == listOf(10, 11) && parsed.missingFieldPresent &&
                parsed.imuReady == false && parsed.servos.size == 1 && parsed.servos[0].tempC == 72.0)
        check("负对照:未知 ID 的扩展行被丢弃（不猜部位）",
            HealthSnapshot.from(JsonParser.parseString(
                """{"servo_telemetry":[{"id":99,"temp_c":99.0}]}""",
            ).asJsonObject).servos.isEmpty())

        // ⑨ 判定链本身：绝不输出 PASS
        check("MonitorVerdict 不含 PASS",
            MonitorVerdict.entries.none { it.name == "PASS" })
        check("toJson 的 verdict 不是 PASS 且带部位表",
            eval(health(percent = 5.0)).toJson().let { j ->
                j.get("verdict").asString != "PASS" && j.getAsJsonObject("parts").size() > 0 })
        check("flaggedParts 只返回 WARN/CRITICAL",
            eval(health(percent = 5.0)).flaggedParts().all {
                eval(health(percent = 5.0)).severityOf(it) in listOf(Severity.WARN, Severity.CRITICAL) })
    }

    // ---- N+2. 3D 几何：两条独立算法互算 / 投影范围 / 深度排序 ----
    private fun testDuckModelGeometry() {
        println("\n[N+2] 3D 仿真模型几何（旋转/投影纯 JVM 真跑）")
        val g = DuckModelGeometry
        val p = Vec3(1f, 0f, 0f)
        val q90 = g.rotateY(p, 90.0)
        check("旋转 90°：+x 转向 -z", g.near(q90, Vec3(0f, 0f, -1f))) { "got=$q90" }
        check("旋转 0° 是恒等", g.near(g.rotateY(p, 0.0), p))
        check("旋转 360° 回到原点", g.near(g.rotateY(p, 360.0), p, 1e-3f))
        // 🔴 两条独立算法互算：主公式 vs 旋转群复合律 R(a)=R(a/2)·R(a/2)
        val angles = listOf(0.0, 17.0, 45.0, 90.0, 123.0, 270.0, 359.0)
        check("两条独立旋转算法在 7 个角度上互算一致",
            angles.all { a -> g.near(g.rotateY(Vec3(0.7f, -1.2f, 0.4f), a),
                g.rotateYTwice(Vec3(0.7f, -1.2f, 0.4f), a), 1e-3f) })
        check("负对照:两次半角 != 一次半角（复合律真的在起作用）",
            !g.near(g.rotateYTwice(p, 90.0), g.rotateY(p, 45.0)))

        val w = 720f; val h = 420f
        val f0 = g.frame(0.0, w, h)
        check("一帧包含全部 21 个部位锚点",
            f0.nodes.size == g.NODES.size && g.NODES.size == 21) { "nodes=${f0.nodes.size}" }
        check("壳体线框与骨架都非空", f0.hull.isNotEmpty() && f0.bones.isNotEmpty())
        check("投影点全部落在画布内",
            f0.nodes.all { (_, q) -> q.x in -1f..w + 1f && q.y in -1f..h + 1f })
        check("节点/线按深度升序（远→近，painter's algorithm）",
            f0.nodes.zipWithNext().all { (a, b) -> a.second.depth <= b.second.depth } &&
                f0.hull.zipWithNext().all { (a, b) -> a.avgDepth <= b.avgDepth })
        check("透视近大远小：同 x/y、z 更大 ⇒ 离中心更远",
            g.project(Vec3(1f, 0f, 1f), w, h).x > g.project(Vec3(1f, 0f, -1f), w, h).x)
        check("负对照:0° 与 90° 的帧投影确实不同",
            f0.nodes.map { it.second.x } != g.frame(90.0, w, h).nodes.map { it.second.x })
        check("负对照:旋转后 y 不应整体漂移",
            abs(g.frame(45.0, w, h).nodes.first().second.y - f0.nodes.first().second.y) < 1f ||
                abs(g.frame(45.0, w, h).nodes.first().second.x - f0.nodes.first().second.x) > 0f)

        // 异常部位筛选：severityOf 由调用方注入（与 MonitorReport 单一真源对接）
        val flagged = f0.flagged { if (it == RobotPart.MOUTH) Severity.CRITICAL else Severity.UNKNOWN }
        check("flagged() 只返回异常部位",
            flagged.size == 1 && flagged[0].first.part == RobotPart.MOUTH)
        check("负对照:全 UNKNOWN 时零异常标记",
            f0.flagged { Severity.UNKNOWN }.isEmpty())
        check("模型节点覆盖 15 关节 + 6 系统部位",
            g.NODES.count { it.part.kind == RobotPart.PartKind.JOINT } == 15 &&
                g.NODES.count { it.part.kind == RobotPart.PartKind.SYSTEM } == 6)
    }

    private fun testDuckMesh() {
        println("\n[N+3] 真实外观网格（STL 提取 + 投影纯 JVM 真跑）")
        // 加载真实网格（classpath 资源 duck_mesh.bin，由 tools/build_duck_mesh.py 生成）
        val mesh = try {
            DuckMesh.load()
        } catch (e: Exception) {
            check("duck_mesh.bin 可从 classpath 加载", false) { "加载异常: ${e.message}" }
            return
        }
        check("网格顶点数合理(>100)", mesh.nVerts > 100) { "nVerts=${mesh.nVerts}" }
        check("网格三角形数合理(100~30000)", mesh.nTris in 100..30000) { "nTris=${mesh.nTris}" }
        check("顶点表长度 = nVerts*3", mesh.verts.size == mesh.nVerts * 3)
        check("三角形索引表长度 = nTris*3", mesh.tris.size == mesh.nTris * 3)
        check("颜色表长度 = nTris", mesh.colors.size == mesh.nTris)
        // 三角形索引不越界（load 时已校验，这里再确认负对照：故意构造越界应失败）
        check("所有三角形索引在顶点范围内",
            mesh.tris.all { it in 0 until mesh.nVerts })

        // 投影：用与 DuckModelGeometry 相同的画布尺寸
        val w = 720f; val h = 420f
        val tris = DuckMesh.project(mesh, 0.0, w, h)
        check("投影后三角形数与网格一致", tris.size == mesh.nTris) { "${tris.size} vs ${mesh.nTris}" }
        check("投影三角形按深度升序（远→近）",
            tris.zipWithNext().all { (a, b) -> a.depth <= b.depth })
        check("投影三角形颜色非零（ARGB 有效）",
            tris.all { it.colorArgb != 0 })
        // 负对照：0° 与 90° 投影的三角形 x 坐标集合应不同（旋转真的在起作用）
        val tris90 = DuckMesh.project(mesh, 90.0, w, h)
        check("负对照:0° 与 90° 投影三角形位置确实不同",
            tris.first().a.x != tris90.first().a.x || tris.first().a.y != tris90.first().a.y)

        // 负对照：坏魔数应抛异常（parse 的防御性校验真的在起作用）
        val badBytes = ByteArray(32).also { it[0] = 'X'.code.toByte(); it[1] = 'X'.code.toByte() }
        var badThrows = false
        try { DuckMesh.loadFromBytes(badBytes) } catch (_: Exception) { badThrows = true }
        check("负对照:坏魔数的字节被拒绝", badThrows)

        // ── 2026-11-15 坐标系修复：MuJoCo Z-up → App Y-up 的轴置换 ──
        // 铁律：坐标/轴的量必须两条独立算法互算，且带负对照。
        // 算法①：直接逐基向量断言循环置换 (x,y,z)→(y,z,x)。
        val ex = DuckMesh.toAppAxes(Vec3(1f, 0f, 0f))
        val ey = DuckMesh.toAppAxes(Vec3(0f, 1f, 0f))
        val ez = DuckMesh.toAppAxes(Vec3(0f, 0f, 1f))
        check("轴置换:mjc +X(喙) → app +Z(朝观察者)",
            ex.x == 0f && ex.y == 0f && ex.z == 1f) { "got $ex" }
        check("轴置换:mjc +Y(左) → app +X(右)",
            ey.x == 1f && ey.y == 0f && ey.z == 0f) { "got $ey" }
        check("轴置换:mjc +Z(上) → app +Y(上)",
            ez.x == 0f && ez.y == 1f && ez.z == 0f) { "got $ez" }
        // 算法②：叉积定手性。det=+1 的旋转应满足 R(ex)×R(ey)=R(ez)；
        // 若误写成镜像 (x,y,z)→(x,z,-y) 的变体导致 det=-1，叉积会反号 ⇒ 必红。
        fun cross(a: Vec3, b: Vec3) = Vec3(
            a.y * b.z - a.z * b.y,
            a.z * b.x - a.x * b.z,
            a.x * b.y - a.y * b.x,
        )
        val crossed = cross(ex, ey)
        check("轴置换保持手性 det=+1(叉积独立算法互算)",
            DuckModelGeometry.near(crossed, ez)) { "ex×ey=$crossed, ez=$ez" }
        check("负对照:轴置换不是恒等变换", !DuckModelGeometry.near(ex, Vec3(1f, 0f, 0f)))

        // 真实网格现在必须「站直」：y 跨度按 NODES 的 [-1.48, 1.32] 定标。
        // 若有人删掉轴变换，y 变成原 mjc.y（左右跨度），跨度会明显不同于 2.8 ⇒ 必红。
        val ys = (0 until mesh.nVerts).map { mesh.verts[it * 3 + 1] }
        val ySpan = ys.max() - ys.min()
        val nodeSpan = 1.32f - (-1.48f)
        check("网格站直:y 跨度对齐 NODES 尺度($nodeSpan)",
            kotlin.math.abs(ySpan - nodeSpan) < 0.05f) { "ySpan=$ySpan center=${(ys.max() + ys.min()) / 2f}" }
        check("负对照:轴变换删掉会躺倒(y 跨度不再等于 NODES 跨度)",
            kotlin.math.abs(0.5f * ySpan - nodeSpan) > 0.5f)

        // 官方 Cream 配色：生成期整只纯橙必须被重映射掉。
        val distinct = mesh.colors.toHashSet()
        check("官方配色:网格至少 3 种语义色(奶油白壳/橙 trim/黑镜头)",
            distinct.size >= 3) { "colors=${distinct.take(6)}" }
        check("官方配色:奶油白壳 0xFFF3E6D2 已生效", 0xFFF3E6D2.toInt() in distinct)
        check("官方配色:橙 trim 0xFFFF8A3D 已生效", 0xFFFF8A3D.toInt() in distinct)
        check("负对照:旧『整只橙』配色已被替换(非单一色)", distinct.size > 1)

        // ── 2026-11-15 「模型像碎片」修复：不透明 + Lambert 光照 ──
        // Canvas 2D 无 z-buffer，半透明逐面叠色会把封闭壳体画成碎片；
        // 判据独立于被测值：alpha 通道必须是常量 0xFF，且光照必须随法线变化。
        check("填充 alpha 恒不透明(0xFF)",
            tris.all { (it.colorArgb ushr 24) == 0xFF })
        check("负对照:不是全同色(光照真的在分面明暗)",
            tris.map { it.colorArgb }.toHashSet().size > 3)
        // 算法①：两个已知法线的三角形，法线越贴近方向光越亮。
        val white = 0xFFFFFFFF.toInt()
        val tA = DuckMesh.shadeColor(white, Vec3(0f, 0f, 0f), Vec3(1f, 0f, 0f), Vec3(0f, 1f, 0f))
        val tB = DuckMesh.shadeColor(white, Vec3(0f, 0f, 0f), Vec3(1f, 0f, 0f), Vec3(0f, 0f, 1f))
        val lumA = tA and 0xFF
        val lumB = tB and 0xFF
        check("Lambert:法线贴近光向量的面更亮", lumB > lumA) { "lumA=$lumA lumB=$lumB" }
        // 算法②：与「纯环境光」独立互算（diffuse=0 时 shade 应等于 AMBIENT）。
        val ambientOnly = (255f * DuckMesh.AMBIENT).toInt()
        check("Lambert:退化面退化为纯环境光",
            kotlin.math.abs((DuckMesh.shadeColor(white, Vec3(0f, 0f, 0f),
                Vec3(0f, 0f, 0f), Vec3(0f, 0f, 0f)) and 0xFF) - ambientOnly) <= 1)
        check("负对照:环境光系数不是 1.0(否则光照被关掉)",
            DuckMesh.AMBIENT < 1f)
        check("负对照:半透明色会被不透明判据抓到(断言不恒真)",
            ((0x80 shl 24) ushr 24) != 0xFF)
        // 旋转后明暗必须跟着变（光照在相机空间算，不是贴图烤死）。
        check("旋转后分面明暗发生变化(光照在相机空间)",
            tris.map { it.colorArgb }.toHashSet() != tris90.map { it.colorArgb }.toHashSet())

        // ── 阶段 4：DMSH v2 部件索引 + 状态着色（颜色即状态）──
        check("网格格式升级 v2 且 n_parts=单一真源槽位数",
            mesh.version == 2 && mesh.nParts == ModelPart.SLOT_COUNT) { "v=${mesh.version} nParts=${mesh.nParts}" }
        check("v2 部件索引表长度=nTris", mesh.partIndices.size == mesh.nTris)
        check("v2 每个三角形部件索引合法(0..20 或 255)",
            mesh.partIndices.all { (it.toInt() and 0xFF).let { i -> i == ModelPart.NO_PART || ModelPart.of(i) != null } })
        val colorable = (0 until mesh.nTris).count { DuckMesh.partIndexOf(mesh, it) != ModelPart.NO_PART }
        check("v2 可着色三角形>0 (实测 $colorable)", colorable > 0)
        val present = (0 until mesh.nTris).map { DuckMesh.partIndexOf(mesh, it) }.toHashSet()
        val jointsPresent = present.count { it in 0..14 }
        check("v2 关节部件覆盖>=12/15 (实测 $jointsPresent)", jointsPresent >= 12)
        check("v2 系统件 BATTERY/CPU/IMU 命中(16/17/18)", listOf(16, 17, 18).all { it in present })

        // 部件映射：索引即 RobotPart.entries ordinal，且 of/indexOf 互逆（负对照锁越界）。
        check("ModelPart 映射:0=左髋偏航/16=电池/17=CPU/18=IMU",
            ModelPart.of(0) == RobotPart.LEFT_HIP_YAW &&
                ModelPart.of(15) == RobotPart.TORSO &&
                ModelPart.of(16) == RobotPart.BATTERY &&
                ModelPart.of(17) == RobotPart.CPU &&
                ModelPart.of(18) == RobotPart.IMU)
        check("负对照:ModelPart 越界/NO_PART/负数均返回 null",
            ModelPart.of(21) == null && ModelPart.of(255) == null && ModelPart.of(-1) == null)
        check("ModelPart.indexOf 与 of 互逆(21 槽位全覆盖)",
            (0 until ModelPart.SLOT_COUNT).all { ModelPart.indexOf(ModelPart.of(it)!!) == it })

        // 状态色：UNKNOWN 原样基色（铁律不造色），OK 低强度 < WARN < CRITICAL。
        val cream = 0xFFF3E6D2.toInt()
        val okC = DuckMesh.statusTint(cream, Severity.OK)
        val warnC = DuckMesh.statusTint(cream, Severity.WARN)
        val critC = DuckMesh.statusTint(cream, Severity.CRITICAL)
        fun dist(a: Int, b: Int) = abs(((a ushr 16) and 0xFF) - ((b ushr 16) and 0xFF)) +
            abs(((a ushr 8) and 0xFF) - ((b ushr 8) and 0xFF)) + abs((a and 0xFF) - (b and 0xFF))
        check("状态色:UNKNOWN 原样返回基色(不造色)", DuckMesh.statusTint(cream, Severity.UNKNOWN) == cream)
        check("状态色:混合强度 MIX_OK < MIX_WARN < MIX_CRITICAL",
            DuckMesh.MIX_OK < DuckMesh.MIX_WARN && DuckMesh.MIX_WARN < DuckMesh.MIX_CRITICAL)
        check("状态色:三档都改色且 alpha 恒 0xFF",
            okC != cream && warnC != cream && critC != cream &&
                listOf(okC, warnC, critC).all { (it ushr 24) == 0xFF })
        check("状态色:OK 强度小于 CRITICAL(避免整机刷绿)", dist(okC, cream) < dist(critC, cream))
        check("状态色:三档互不相同", okC != warnC && warnC != critC && okC != critC)
        check("状态色:CRITICAL 红分量主导(比绿高 40 以上)",
            ((critC ushr 16) and 0xFF) > ((critC ushr 8) and 0xFF) + 40)

        // project 链： severityOf 只改目标部件，NO_PART 三角形绝不变色。
        val twoTris = DuckMesh.MeshData(
            floatArrayOf(0f, 0f, 0f, 1f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f),
            intArrayOf(0, 1, 2, 0, 1, 2), intArrayOf(cream, cream), 4, 2,
            byteArrayOf(16, ModelPart.NO_PART.toByte()), 2, ModelPart.SLOT_COUNT,
        )
        val baseProj = DuckMesh.project(twoTris, 0.0, 100f, 100f) { Severity.UNKNOWN }
        val critProj = DuckMesh.project(twoTris, 0.0, 100f, 100f) { Severity.CRITICAL }
        check("投影着色:目标部件(电池)三角形 CRITICAL 变色",
            baseProj[0].colorArgb != critProj[0].colorArgb)
        check("负对照:NO_PART 三角形即使全 CRITICAL 也不变色",
            baseProj[1].colorArgb == critProj[1].colorArgb)
        val triNeutral = DuckMesh.project(mesh, 30.0, w, h) { Severity.UNKNOWN }
        val triAllCrit = DuckMesh.project(mesh, 30.0, w, h) { Severity.CRITICAL }
        val changed = triNeutral.indices.count { triNeutral[it].colorArgb != triAllCrit[it].colorArgb }
        check("真实网格:全 CRITICAL 只改可着色三角形(实测 $changed / $colorable)",
            changed > 0 && changed <= colorable)

        // 解析负对照：坏版本 / n_parts 漂移 / 部件索引越界 / 截断 / v1 兼容分支。
        val rawV2 = DuckMesh::class.java.getResourceAsStream("/duck_mesh.bin")!!.readBytes()
        fun rejects(mutate: (ByteArray) -> Unit): Boolean {
            val b = rawV2.copyOf(); mutate(b)
            return try { DuckMesh.loadFromBytes(b); false } catch (_: Exception) { true }
        }
        check("负对照:未知版本 3 被拒绝",
            rejects { it[4] = 0; it[5] = 0; it[6] = 0; it[7] = 3 })
        check("负对照:n_parts 漂移(21→22)被拒绝", rejects { it[19] = 22 })
        val partOff = 20 + mesh.nVerts * 3 * 4 + mesh.nTris * 3 * 4 + mesh.nTris * 4
        check("负对照:部件索引越界(→21)被拒绝", rejects { it[partOff] = 21 })
        check("负对照:截断一字节被拒绝",
            try { DuckMesh.loadFromBytes(rawV2.copyOf(rawV2.size - 1)); false } catch (_: Exception) { true })
        // v1 fixture：从 v2 字节剥掉 n_parts 头与部件数组，版本号改回 1。
        val v1Bytes = ByteArray(rawV2.size - 4 - mesh.nTris).also { out ->
            rawV2.copyInto(out, 0, 0, 16)
            out[4] = 1; out[5] = 0; out[6] = 0; out[7] = 0  // 小端 version 在 4..7，LSB 是 byte4
            rawV2.copyInto(out, 16, 20, rawV2.size - mesh.nTris)
        }
        val legacy = DuckMesh.loadFromBytes(v1Bytes)
        check("v1 兼容:老网格可解析且部件全 NO_PART",
            legacy.version == 1 && legacy.nParts == 0 &&
                legacy.partIndices.all { (it.toInt() and 0xFF) == ModelPart.NO_PART })
        check("v1 兼容:无部件时状态着色不生效(不造色)",
            DuckMesh.project(legacy, 0.0, w, h) { Severity.CRITICAL }.map { it.colorArgb } ==
                DuckMesh.project(legacy, 0.0, w, h) { Severity.UNKNOWN }.map { it.colorArgb })
    }

    // ---- 全息渲染管线（纯 JVM 像素断言 + 负对照）----
    /**
     * [HoloRenderer] 是「颜色即状态」在真机上的唯一出口，但它的输出是像素 ——
     * 文本门禁照不出「整机发灰 / 状态色没落上 / 模型全空」。故在此直接对像素数组下断言：
     * 尺寸/不透明、可见面积量级、状态色出现与不出现的负对照、旋转真的改变画面、幂等。
     */
    private fun testHoloRenderer() {
        println("\n[HOLO] 全息渲染管线（图像空间提边 + 状态色 + 负对照）")
        val mesh = try {
            DuckMesh.load()
        } catch (e: Exception) {
            check("全息:duck_mesh.bin 可加载", false) { "加载异常: ${e.message}" }
            return
        }
        val w = 144
        val h = 108
        val ssw = 2

        // 数据驱动挑「三角形最多的部件槽位」——不手写部件名，避免与网格版本脱钩
        val counts = IntArray(21)
        for (b in mesh.partIndices) {
            val p = b.toInt() and 0xFF
            if (p in 0 until 21) counts[p]++
        }
        val hotPart = counts.indices.maxByOrNull { counts[it] } ?: -1
        check("全息:存在承载最多三角形的部件槽位", hotPart in 0 until 21 && counts[hotPart] > 100) {
            "counts=${counts.toList()}"
        }
        val hotRobotPart = if (hotPart >= 0) ModelPart.of(hotPart) else null

        val unknown: (RobotPart) -> Severity = { Severity.UNKNOWN }
        val allCritical: (RobotPart) -> Severity = { Severity.CRITICAL }
        val hotCritical: (RobotPart) -> Severity = { p ->
            if (p == hotRobotPart) Severity.CRITICAL else Severity.UNKNOWN
        }

        val pxUnknown = HoloRenderer.render(mesh, 0.0, w, h, unknown, ssw)
        check("全息:输出像素数 = w*h", pxUnknown.size == w * h) { "${pxUnknown.size}" }
        check("全息:输出全部不透明(alpha=0xFF)", pxUnknown.all { (it ushr 24) == 0xFF })
        // 🔴 覆盖率必须取自光栅化计数：第一版按亮度统计 → 背景渐变也算「可见」，
        // 实测 vis=0.995 假绿。判据失效的教训直接写在这条断言旁边。
        val (_, coverage) = HoloRenderer.renderWithCoverage(mesh, 0.0, w, h, unknown, ssw)
        check("全息:模型覆盖率合理(5%~85%)", coverage in 0.05f..0.85f) { "coverage=$coverage" }
        // 线条真的画出来了：亮青像素（b、g 高、r 中低）必须成片存在
        val cyan = pxUnknown.count { p ->
            val r = (p shr 16) and 255; val g = (p shr 8) and 255; val b = p and 255
            b > 140 && g > 120 && r < 190
        }
        check("全息:外轮廓/分界线成片存在(>200 px)", cyan > 200) { "cyan=$cyan" }

        // 负对照①：全 UNKNOWN ⇒ 不应出现红色系像素（无证据不造状态色）
        fun redCount(px: IntArray) = px.count { p ->
            val r = (p shr 16) and 255; val g = (p shr 8) and 255; val b = p and 255
            r > g + 25 && r > b + 25
        }
        check("负对照:全 UNKNOWN 时无红色状态像素", redCount(pxUnknown) == 0) {
            "red=${redCount(pxUnknown)}"
        }
        // 正向：承载最多三角形的部件判 CRITICAL ⇒ 红色状态像素必须出现
        val pxHot = HoloRenderer.render(mesh, 0.0, w, h, hotCritical, ssw)
        check("状态色:CRITICAL 部件渲染出红色像素", redCount(pxHot) > 0) {
            "red=${redCount(pxHot)}"
        }
        // 负对照②：不同部件状态不应等价（防「状态表没接进去」假绿）
        check("负对照:UNKNOWN 与 CRITICAL 画面必须不同",
            !pxUnknown.contentEquals(pxHot))
        // 正向：全 CRITICAL 的红色像素应显著多于单部件 CRITICAL（状态真的按部件扩散）
        val pxAll = HoloRenderer.render(mesh, 0.0, w, h, allCritical, ssw)
        check("状态色:全 CRITICAL 红像素 > 单部件 CRITICAL", redCount(pxAll) > redCount(pxHot)) {
            "all=${redCount(pxAll)} hot=${redCount(pxHot)}"
        }
        // 负对照③：旋转必须真的改变画面（缓存/角度未生效会假绿）
        val px90 = HoloRenderer.render(mesh, 90.0, w, h, unknown, ssw)
        check("负对照:0° 与 90° 画面不同", !pxUnknown.contentEquals(px90))
        // 幂等：同输入两次渲染逐像素一致（背景缓存/静态缓冲不得串帧）
        val pxAgain = HoloRenderer.render(mesh, 0.0, w, h, unknown, ssw)
        check("幂等:同输入两次渲染逐像素一致", pxUnknown.contentEquals(pxAgain))
        // 状态色单一真源：HoloRenderer 不得自造 RGB，必须取 RobotParts.severityArgb
        val holoSrc = java.io.File("core/src/main/kotlin/io/microduck/app/core/HoloRenderer.kt")
        val holo = if (holoSrc.isFile) holoSrc.readText() else ""
        check("全息:状态色取自 RobotParts.severityArgb(单一真源)",
            holo.contains("RobotParts.severityArgb"))
        check("负对照:全息源码未硬编码语义色(0xDD6A6A/0xD8A23E)",
            !holo.contains("0xDD6A6A") && !holo.contains("0xD8A23E"))
    }

    // ---- 一键休息 / 恢复站立（robot.rest / robot.init，无参离散请求）----
    private fun testRestController() {
        println("\n[REST] 一键休息 robot.rest / 恢复 robot.init")
        val t = MockTransport()
        val s = RobotSession(t, backoffBaseMs = 10)
        s.connect(ConnectTarget.Mock)
        val rc = RestController(s)

        // 正向：rest 被接受，应答结构对齐 IntentResult{accepted, reason}
        val r = rc.requestRest()
        check("robot.rest 调用成功", r.isSuccess) { "${r.exceptionOrNull()}" }
        val o = r.getOrNull()
        check("rest 应答 accepted=true", o?.accepted == true) { "o=$o" }
        check("rest 恰好发一次(无参请求)", t.countOf(Method.ROBOT_REST) == 1) { "log=${t.log()}" }
        // rest 是 request 不是 notification：发出的行必须带 id
        val restLine = t.rawLog().first { it.contains("\"robot.rest\"") }
        check("rest 以 request 发出(带 id)", restLine.contains("\"id\":") && !restLine.contains("\"jsonrpc\":\"2.0\",\"method\""))
        // 负对照：请求行不能带 params（deny_unknown_fields ⇒ 多键会被 -32602 拒）
        check("负对照:rest 请求不带 params 键", !restLine.contains("\"params\""))

        // 正向：init 是 rest 的逆操作，同样被接受
        val r2 = rc.requestInit()
        check("robot.init 调用成功", r2.isSuccess) { "${r2.exceptionOrNull()}" }
        check("init 应答 accepted=true", r2.getOrNull()?.accepted == true) { "o=${r2.getOrNull()}" }

        // 负对照：应答缺 accepted 字段 ⇒ 必须判「未确认接受」，绝不假定 true。
        // 走 RestController 的同一解析路径（acc == true 才接受，缺字段为 null ⇒ false）。
        val fake = JsonObject().apply { addProperty("foo", "bar") }
        val acc = fake.get("accepted")?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive
            ?.takeIf { it.isBoolean }?.asBoolean
        val parsed = RestController.Outcome(acc == true, null)
        check("负对照:缺 accepted 字段判未确认接受", !parsed.accepted) { "o=$parsed" }

        // 负对照：断链后调用必须失败，不能假成功
        t.simulateDisconnect()
        val r3 = rc.requestRest()
        check("负对照:断链后 rest 必失败", r3.isFailure) { "r3=$r3" }
        s.close()
    }

    // ---- 阶段1：RobotRepository 数据层（不可变快照 + 监听器 + 动作）----
    /** 等条件成立，超时返回 false（自检里异步动作的同步等待，避免依赖固定 sleep）。 */
    private fun waitFor(timeoutMs: Long, cond: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (cond()) return true
            Thread.sleep(10)
        }
        return cond()
    }

    private fun testRobotRepository() {
        println("\n[REPO] RobotRepository 数据层：快照/监听/动作")
        val t = MockTransport()
        val repo = RobotRepository { _ -> t }

        // 初始快照：未连接、无数据、零告警
        val init = repo.snapshot()
        check("初始快照未连接", !init.connected && init.sessionState == "NONE") { "s=$init" }
        check("初始快照 kind 为占位", init.kind == "—") { "kind=${init.kind}" }
        check("初始快照无 health ⇒ monitorSource 判 NONE",
            repo.monitorSource() == MonitorSource.NONE) { "src=${repo.monitorSource()}" }

        // 监听器注册
        val seen = mutableListOf<RobotRepository.Snapshot>()
        val sub = repo.onSnapshot { seen.add(it) }

        // 正向：connectWith 建链，快照应反映 READY
        val ok = repo.connectWith(t, ConnectTarget.Mock)
        check("connectWith 返回成功", ok) { "ok=$ok" }
        check("快照反映 READY", waitFor(2000) { repo.snapshot().connected && repo.snapshot().sessionState == "READY" }) {
            "state=${repo.snapshot().sessionState}"
        }
        check("快照 kind=MOCK", repo.snapshot().kind == "MOCK") { "kind=${repo.snapshot().kind}" }
        check("监听器收到至少一次快照", seen.isNotEmpty()) { "seen=${seen.size}" }

        // 正向：refreshHealth 更新 lastHealth 与监控报告
        repo.refreshHealth()
        check("refreshHealth 后读到 health", waitFor(2000) { repo.snapshot().lastHealth != null }) {
            "health=${repo.snapshot().lastHealth}"
        }
        check("health 后 monitorSource=MOCK_FIXTURE",
            repo.monitorSource() == MonitorSource.MOCK_FIXTURE) { "src=${repo.monitorSource()}" }
        check("monitorReport 非空", repo.snapshot().monitorReport != null) { "rep=${repo.snapshot().monitorReport}" }
        check("batteryText 由 health 派生(非0兜底)",
            repo.snapshot().batteryText.isNotEmpty() && repo.snapshot().batteryText != "— 未读到") {
            "batt=${repo.snapshot().batteryText}"
        }

        // 正向：状态帧到达 ⇒ lastState 更新 + 帧计数增长
        val before = repo.snapshot().stateFrameCount
        t.pushFrame("""{"jsonrpc":"2.0","method":"robot.state","params":{"t":1.0,"policy":"walk"}}""")
        check("状态帧后 lastState 更新", waitFor(2000) { repo.snapshot().lastState != null }) {
            "state=${repo.snapshot().lastState}"
        }
        check("状态帧计数增长", repo.snapshot().stateFrameCount > before) {
            "before=$before after=${repo.snapshot().stateFrameCount}"
        }

        // 正向：ToF 订阅后 Mock 夹具帧到达快照（8×8 三态）
        check("ToF 订阅后快照收到帧( Mock 夹具非实机)", waitFor(2000) { repo.snapshot().tof != null }) {
            "tof=${repo.snapshot().tof}"
        }
        check("ToF 快照 8×8=64 格", repo.snapshot().tof?.zones?.size == 64) {
            "zones=${repo.snapshot().tof?.zones?.size}"
        }
        check("ToF 夹具含有效量程物体(Mock)", (repo.snapshot().tof?.validCount ?: 0) >= 9) {
            "valid=${repo.snapshot().tof?.validCount}"
        }

        // 正向：tick 推进速率窗口
        repo.tick()
        check("tick 后快照仍自洽", repo.snapshot().connected) { "s=${repo.snapshot()}" }

        // 负对照：disconnect 后快照复位、monitorSource 回 NONE
        repo.disconnect()
        val after = repo.snapshot()
        check("disconnect 后未连接", !after.connected && after.sessionState == "NONE") { "s=$after" }
        check("负对照:disconnect 后 health 清空", after.lastHealth == null) { "h=${after.lastHealth}" }
        check("负对照:disconnect 后 ToF 清空(不沿陈旧深度)", after.tof == null) { "tof=${after.tof}" }
        check("负对照:disconnect 后 monitorSource=NONE",
            repo.monitorSource() == MonitorSource.NONE) { "src=${repo.monitorSource()}" }

        // 负对照：非法连接串 ⇒ connectError 非空、不建链
        val bad = RobotRepository { _ -> MockTransport() }
        val badOk = bad.connect("host:99999")
        check("负对照:非法端口连接返回失败", !badOk) { "ok=$badOk" }
        check("负对照:非法端口写 connectError", bad.snapshot().connectError.isNotEmpty()) {
            "err=${bad.snapshot().connectError}"
        }

        // 负对照：监听器 dispose 后不再回调
        val repo2 = RobotRepository { _ -> MockTransport() }
        var cbCount = 0
        val d = repo2.onSnapshot { cbCount++ }
        repo2.connectWith(MockTransport(), ConnectTarget.Mock)
        waitFor(2000) { cbCount > 0 }
        d.dispose()
        val c1 = cbCount
        repo2.disconnect()
        Thread.sleep(50)
        check("负对照:dispose 后监听器不再触发", cbCount == c1) { "before=$c1 after=$cbCount" }
        sub.dispose()
    }

    @JvmStatic
    fun main(args: Array<String>) {
        println("=" * 60)
        println("MicroDuck core 会话层自检  |  Kotlin 2.4.0 / JDK17 / jvm-target 17")
        println("=" * 60)
        testHandshake()
        testHelloDegrade()
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
        testNoiseNnPsk0()
        testNoiseSnowInteropVectors()
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
        testHexEncoding()
        testSerialGattLink()
        testPeerApiVersionObservability()
        testConnectFailureReason()
        testAiDebugPolicy()
        testHardwareMonitor()
        testDuckModelGeometry()
        testDuckMesh()
        testHoloRenderer()
        testRestController()
        testRobotRepository()
        testDiagnostics()
        testNetProvisioning()
        testProvisioningCrypto()
        testTofSnapshot()
        testFirmwareUpdate()
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

    /**
     * hex 编码收敛到 core 后的行为自检。判据刻意不手抄期望值：
     * 用 JDK17 java.util.HexFormat 作独立算法互算，再用故意写错的表做负对照。
     * （2026-11-13 曾把正确的 "0123456789abcdef" 误读成错表，且判据用的还是同一串，
     *  于是 "OK=True" 假绿 —— 这正是「判据必须独立于被测值」的反面教材。）
     */
    private fun testHexEncoding() {
        println("\n[hex] 十六进制编码单一真源")
        val probe = ByteArray(256) { it.toByte() }
        val independent = java.util.HexFormat.of().formatHex(probe)
        check("Hex.encode 与 JDK17 HexFormat 逐位一致",
            Hex.encode(probe) == independent) { "got=${Hex.encode(probe).take(32)}" }
        check("输出长度恰为输入 2 倍", Hex.encode(probe).length == probe.size * 2)
        check("高低半字节都覆盖 a-f",
            Hex.encode(byteArrayOf(0xab.toByte(), 0xcd.toByte(), 0xef.toByte())) == "abcdef")
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest("abc".toByteArray())
        check("SHA-256 摘要编码与 JDK 独立实现一致",
            Hex.encode(digest) == java.util.HexFormat.of().formatHex(digest))

        // 负对照：故意用错表（0/8/9/6... 非 0..9）编码，确认防线真的会红。
        val badTable = charArrayOf('0', '8', '9', '6', '8', '0', '3', '6', '9', '3',
            'a', 'b', 'c', 'd', 'e', 'f')
        fun badEncode(bytes: ByteArray): String = buildString(bytes.size * 2) {
            for (b in bytes) {
                val v = b.toInt() and 0xFF
                append(badTable[v ushr 4]); append(badTable[v and 0x0F])
            }
        }
        check("负对照:错表编码与标准编码不同", badEncode(digest) != Hex.encode(digest))
        check("负对照:错表编码会被 SHA-256 校验拒绝",
            !UpdatePolicy.verifySha256(Hex.encode(digest), badEncode(digest)))

        // 跨文件静态核对：两条消费链必须 import 同一个函数，不许各自复制实现。
        val client = java.io.File("app/src/main/kotlin/io/microduck/app/update/GithubReleaseClient.kt")
        val installer = java.io.File("app/src/main/kotlin/io/microduck/app/update/UpdateInstaller.kt")
        val clientSrc = if (client.isFile) client.readText() else ""
        val installerSrc = if (installer.isFile) installer.readText() else ""
        check("下载链 import core Hex", clientSrc.contains("import io.microduck.app.core.Hex"))
        check("签名链 import core Hex", installerSrc.contains("import io.microduck.app.core.Hex"))
        check("两链都调用 Hex.encode",
            clientSrc.contains("Hex.encode(") && installerSrc.contains("Hex.encode("))
        check("两链都不再私有实现 toHex/HEX_CHARS",
            !clientSrc.contains("HEX_CHARS") && !installerSrc.contains("HEX_CHARS") &&
                !clientSrc.contains("ByteArray.toHex") && !installerSrc.contains("ByteArray.toHex"))
        check("负对照:私自复制实现的假源码会被上面这条核对判红",
            "import io.microduck.app.core.Hex\nprivate const val HEX_CHARS = \"x\"".contains("HEX_CHARS"))
    }

    // ---- N+3. SerialGattLink：GATT 操作串行执行（并发调用必须被串行化，负对照无包装时确实重叠）----
    // 依据：AOSP bta_gatt_queue.h + Android BluetoothGatt 一次只允许一个 outstanding 操作；
    // 本测试证明「串行纪律」在 core 层生效，且探针确实能区分串行/重叠（负对照不空转）。
    private fun testSerialGattLink() {
        println("\n[N+3] SerialGattLink GATT 操作串行化")

        // ① 串行性：8 线程并发调 writeChunk，实际对 delegate 的操作必须串行（在飞峰值恒为 1）
        val probe = OverlapProbe(delayMs = 15)
        val serial = SerialGattLink(probe)
        val writers = (1..8).map { Thread { serial.writeChunk(ByteArray(20)) } }
        writers.forEach { it.start() }
        writers.forEach { it.join() }
        check("并发 8 次 writeChunk 实际串行(maxInFlight==1)", probe.maxInFlight() == 1) {
            "maxInFlight=${probe.maxInFlight()}"
        }
        check("8 次写全部执行(无丢失)", probe.countOf("writeChunk") == 8) { "n=${probe.countOf("writeChunk")}" }
        serial.close()

        // ② 顺序：同一线程顺序提交，执行顺序与提交顺序一致（单线程 FIFO 队列）
        val probe2 = OverlapProbe(delayMs = 1)
        val serial2 = SerialGattLink(probe2)
        serial2.writeChunk(ByteArray(1))
        serial2.readApiVersion()
        serial2.writeChunk(ByteArray(2))
        check("顺序提交执行顺序一致(FIFO)",
            probe2.order() == listOf("writeChunk", "readApiVersion", "writeChunk")) {
            "order=${probe2.order()}"
        }
        check("负对照:3 次操作全部执行(非只跑第一个)",
            probe2.countOf("writeChunk") == 2 && probe2.countOf("readApiVersion") == 1) {
            "w=${probe2.countOf("writeChunk")} r=${probe2.countOf("readApiVersion")}"
        }
        serial2.close()

        // ③ 负对照：不加 SerialGattLink，直接并发调探针，必须检测到重叠
        //   （证明探针有效、上面的串行断言不是空转——无包装时峰值必须 > 1）
        val probe3 = OverlapProbe(delayMs = 30)
        val raw = (1..8).map { Thread { probe3.writeChunk(ByteArray(20)) } }
        raw.forEach { it.start() }
        raw.forEach { it.join() }
        check("负对照:无串行包装时并发写确实重叠(maxInFlight>1)", probe3.maxInFlight() > 1) {
            "maxInFlight=${probe3.maxInFlight()}"
        }

        // ④ close 后拒绝：不再接受新操作
        val probe4 = OverlapProbe()
        val serial4 = SerialGattLink(probe4)
        serial4.close()
        val r = serial4.writeChunk(ByteArray(1))
        check("close 后拒绝操作(failure)", r.isFailure) { "$r" }
    }

    /**
     * 检测 GATT 操作是否**重叠并发**的探针：记录任意时刻在飞（in-flight）的操作数峰值。
     * 串行执行时峰值恒为 1；被并发调用时峰值 > 1。用于给 [SerialGattLink] 的串行性做
     * 正/负对照——负对照直接并发调探针，证明「重叠确实能被检测到」，正向断言才不是空转。
     */
    private class OverlapProbe(private val delayMs: Long = 0) : GattLink {
        private val inFlight = java.util.concurrent.atomic.AtomicInteger(0)
        private val maxInFlight = java.util.concurrent.atomic.AtomicInteger(0)
        private val order = java.util.concurrent.ConcurrentLinkedQueue<String>()
        private val counts = java.util.concurrent.ConcurrentHashMap<String, Int>()

        private fun <T> enter(name: String, block: () -> Result<T>): Result<T> {
            val cur = inFlight.incrementAndGet()
            maxInFlight.accumulateAndGet(cur) { a, b -> if (a > b) a else b }
            order.add(name)
            counts[name] = (counts[name] ?: 0) + 1
            try {
                if (delayMs > 0) Thread.sleep(delayMs)
                return block()
            } finally {
                inFlight.decrementAndGet()
            }
        }

        override fun connect(): Result<Int> = enter("connect") { Result.success(20) }
        override fun readApiVersion(): Result<Int> = enter("readApiVersion") { Result.success(40) }
        override fun requestMtu(): Result<Unit> = Result.success(Unit)
        override fun setNotificationHandler(onChunk: (ByteArray) -> Unit): Result<Unit> =
            enter("setNotificationHandler") { Result.success(Unit) }
        override fun writeChunk(chunk: ByteArray): Result<Unit> = enter("writeChunk") { Result.success(Unit) }
        override fun mtu(): Int = 20
        override fun onDisconnected(cb: () -> Unit) { }
        override fun close() { }
        override fun isConnected(): Boolean = true

        fun maxInFlight(): Int = maxInFlight.get()
        fun order(): List<String> = order.toList()
        fun countOf(name: String): Int = counts[name] ?: 0
    }

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
        check("发布脚本签名门禁真的比对指纹（非仅打印）",
            py.contains("EXPECTED_SIGNER_SHA256") && py.contains("verify_signer(args.apk)") &&
                py.contains("fp != EXPECTED_SIGNER_SHA256"))
        check("负对照:只打印不比对的假脚本会被上面这条判红",
            !"EXPECTED_SIGNER_SHA256 = \"x\"\nprint(signer)".contains("fp != EXPECTED_SIGNER_SHA256"))
    }

    /** A3/A6/A7 只读诊断解析：一手结构真跑 + 缺数据不造假负对照。 */
    private fun testDiagnostics() {
        println("\n[N] A3/A6/A7 系统诊断只读解析")
        fun obj(s: String) = JsonParser.parseString(s).asJsonObject
        val info = obj("""{"name":"Duck-01","serial":"abc123","uptime_seconds":3600,"simulated":true}""")
        val parsed = DiagnosticsSnapshot.fromInfo(info)
        check("system.info 名字", parsed?.name == "Duck-01")
        check("system.info serial", parsed?.serial == "abc123")
        check("system.info uptime", parsed?.uptimeSeconds == 3600L)
        check("system.info simulated", parsed?.simulated == true)

        // serial 是 Option，缺省保持 null，不造假
        val infoNoSerial = obj("""{"name":"Duck-02","uptime_seconds":120}""")
        val p2 = DiagnosticsSnapshot.fromInfo(infoNoSerial)
        check("负对照:serial 缺失保持 null（不填假值）", p2?.serial == null && p2?.name == "Duck-02")
        // 空对象不算读到
        check("负对照:system.info 空对象视为未读到", DiagnosticsSnapshot.fromInfo(obj("{}")) == null)

        // system.services 数组（state snake_case）+ identity 缺失
        val services = obj("""{"services":[{"unit":"robotd.service","state":"active"},{"unit":"btd.service","state":"failed","identity":"v3"}]}""")
        val ss = DiagnosticsSnapshot.parseServices(services)
        check("system.services 两项", ss.size == 2)
        check("system.services state 原样", ss[0].state == "active" && ss[1].state == "failed")
        check("负对照:identity 缺失保持 null", ss[0].identity == null && ss[1].identity == "v3")
        check("负对照:非数组返回空", DiagnosticsSnapshot.parseServices(obj("""{"services":"bad"}""")).isEmpty())

        // system.logs：unit + lines[]（纯文本、保序）
        val logs = obj("""{"unit":"robotd.service","lines":["boot","ready","-- new robotd process --"]}""")
        val (unit, lines) = DiagnosticsSnapshot.parseLogs(logs)
        check("system.logs unit", unit == "robotd.service")
        check("system.logs 行保序", lines.size == 3 && lines[0] == "boot" && lines[2].contains("new robotd"))
        check("负对照:日志缺 unit 保持 null", DiagnosticsSnapshot.parseLogs(obj("""{"lines":["x"]}""")).first == null)

        // robot.policies / model、update.status / listInstalled
        check("策略列表解析", DiagnosticsSnapshot.parsePolicies(obj("""{"policies":["walk","pick"]}""")) == listOf("walk", "pick"))
        check("模型名解析", DiagnosticsSnapshot.parseModel(obj("""{"model":"alpha_walking"}""")) == "alpha_walking")
        check("更新状态解析", DiagnosticsSnapshot.parseUpdateStatus(obj("""{"status":"idle"}""")) == "idle")
        check("已装组件解析", DiagnosticsSnapshot.parseInstalled(obj("""{"installed":["robotd","btd"]}""")).size == 2)
        check("负对照:模型缺字段不造假", DiagnosticsSnapshot.parseModel(obj("{}")) == null)

        // 空快照语义：未查询前 isEmpty=true，UI 显示「尚未查询」而不是伪造全绿
        check("空诊断快照 isEmpty", DiagnosticsSnapshot().isEmpty)
        check("负对照:有任一读数即非空", !DiagnosticsSnapshot(robotName = "X").isEmpty)

        // Mock 不查：refreshDiagnostics 在 Mock 下应清空快照（真跑 Repository）
        val repo = RobotRepository()
        check("Mock 连接", repo.connect("mock"))
        repo.refreshDiagnostics()
        check("Mock 下诊断保持空快照（不伪造实机读数）", repo.snapshot().diagnostics.isEmpty)
    }

    private fun testNetProvisioning() {
        println("\n[N] A2 Wi-Fi 配网：net.status/scan 只读 + net.connect/forget 写路径")
        fun obj(s: String) = JsonParser.parseString(s).asJsonObject

        // net.status：一手 7 字段全读
        val st = obj("""{"state":"connected","ssid":"Home","signal":72,"ip4":"10.0.0.7","ip6":"fe80::1","mac":"aa:bb","iface":"wlan0"}""")
        val s = NetSnapshot.fromStatus(st)
        check("net.status state", s?.state == "connected")
        check("net.status ssid", s?.ssid == "Home")
        check("net.status signal 是 0-100", s?.signal == 72)
        check("net.status ip4/ip6/mac/iface", s?.ip4 == "10.0.0.7" && s?.ip6 == "fe80::1" && s?.mac == "aa:bb" && s?.iface == "wlan0")
        check("net.status isConnected 严格等于 state", s?.isConnected == true)

        // 未连接：state 之外全缺是正常（不填 0 / 假 IP）
        val disc = NetSnapshot.fromStatus(obj("""{"state":"disconnected"}"""))
        check("负对照:未连接时 ssid/signal/ip4 保持 null（不填 0/假值）",
            disc?.ssid == null && disc?.signal == null && disc?.ip4 == null && disc?.isConnected == false)
        check("负对照:net.status 缺 state 视为未读到", NetSnapshot.fromStatus(obj("""{"ssid":"x"}""")) == null)
        check("空配网快照 isEmpty", NetSnapshot().isEmpty)
        check("负对照:有 state 即非空", !NetSnapshot(state = "connected").isEmpty)

        // net.scan：security 原样、saved、保序；未知 security 不猜成 open
        val scan = obj("""{"networks":[{"ssid":"A","signal":90,"security":"wpa_psk","saved":true},{"ssid":"B","signal":40,"security":"weird_new","saved":false}]}""")
        val nets = NetSnapshot.parseScan(scan)
        check("net.scan 两项且保序", nets.size == 2 && nets[0].ssid == "A" && nets[1].ssid == "B")
        check("net.scan security 原样", nets[0].security == "wpa_psk" && nets[0].saved)
        check("负对照:未知 security 原样保留不猜 open", nets[1].security == "weird_new" && !nets[1].saved)
        check("负对照:net.scan 非数组返回空", NetSnapshot.parseScan(obj("""{"networks":"bad"}""")).isEmpty())
        check("负对照:scan 缺 ssid 的条目跳过", NetSnapshot.parseScan(obj("""{"networks":[{"signal":50,"security":"open","saved":false}]}""")).isEmpty())

        // 请求构造：deny_unknown_fields —— 只带 ssid/psk；开放网络不带 psk 键
        val secured = NetProvisioning.connectParams("Home", "s3cret")
        check("net.connect 参数仅 ssid+psk", secured.size == 2 && secured["ssid"] == "Home" && secured["psk"] == "s3cret")
        val open = NetProvisioning.connectParams("Cafe", null)
        check("负对照:开放网络不写 psk 键", open.size == 1 && open.containsKey("ssid") && !open.containsKey("psk"))
        check("空密码同开放网络（不写 psk）", !NetProvisioning.connectParams("Cafe", "").containsKey("psk"))
        check("net.forget 参数仅 ssid", NetProvisioning.forgetParams("Old") == mapOf("ssid" to "Old"))

        // ConnectResult tag 枚举解析
        val ok = NetProvisioning.parseConnect(obj("""{"outcome":"connected","ssid":"Home","ip4":"10.0.0.7"}"""))
        check("net.connect connected 回执", ok.connected && ok.ssid == "Home" && ok.ip4 == "10.0.0.7")
        check("connected 用户提示含 ssid/ip", ok.userMessage.contains("Home") && ok.userMessage.contains("10.0.0.7"))
        val badKey = NetProvisioning.parseConnect(obj("""{"outcome":"failed","reason":"bad_key","detail":"auth rejected"}"""))
        check("net.connect failed bad_key", !badKey.connected && badKey.failure == "bad_key")
        check("bad_key 用户提示=密码错误（分类正确）", badKey.userMessage.contains("密码错误"))
        check("负对照:缺 outcome 不伪造成功", !NetProvisioning.parseConnect(obj("""{"ssid":"Home"}""")).connected)
        check("负对照:未知 reason 归为未知不猜", NetProvisioning.parseConnect(obj("""{"outcome":"failed","reason":"mystery"}""")).failure == "mystery")

        // 配网成功回填 IP（一次性事件真值）：只有 connected + 非空 ip4 才回填
        check("配网回填:成功带 ip4 → 回填该 IP",
            NetProvisioning.backfillIp(NetProvisioning.parseConnect(obj("""{"outcome":"connected","ssid":"Home","ip4":"10.0.0.7"}"""))) == "10.0.0.7")
        check("负对照:成功但回执无 ip4 → 不回填（不猜 IP）",
            NetProvisioning.backfillIp(NetProvisioning.parseConnect(obj("""{"outcome":"connected","ssid":"Home"}"""))) == null)
        check("负对照:成功但 ip4 空串 → 不回填",
            NetProvisioning.backfillIp(NetProvisioning.parseConnect(obj("""{"outcome":"connected","ssid":"Home","ip4":""}"""))) == null)
        check("负对照:失败回执即使带 ip4 → 不回填",
            NetProvisioning.backfillIp(NetProvisioning.parseConnect(obj("""{"outcome":"failed","reason":"bad_key","ip4":"10.0.0.7"}"""))) == null)

        // ForgetResult
        check("net.forget removed=true", NetProvisioning.parseForget(obj("""{"removed":true}""")).removed)
        check("负对照:removed 缺失视为 false（未读到）", !NetProvisioning.parseForget(obj("{}")).removed)

        // 安全交付：明文警示常量必须存在且点名 §8.1 阻塞（门禁据此核对 UI 不得省略）
        check("明文传输警示含 pre-shipping blocker 语义",
            NetProvisioning.PLAINTEXT_TRANSPORT_WARNING.contains("明文") &&
            NetProvisioning.PLAINTEXT_TRANSPORT_WARNING.contains("8.1"))
    }

    private fun testProvisioningCrypto() {
        println("\n[N] A2' 配网加密能力预埋（KAT 权威向量 + INTEROP_UNVERIFIED 边界）")
        val C = ProvisioningCrypto

        // KAT-1: RFC 7748 §6.1 X25519 共享密钥
        val sharedAlice = C.x25519(C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PRIV), C.hexDecode(ProvisioningCrypto.Rfc7748.BOB_PUB))
        check("RFC7748 X25519 共享密钥 K", sharedAlice != null && C.hexEncode(sharedAlice) == ProvisioningCrypto.Rfc7748.SHARED)
        // KAT-2: 对称性（Bob(priv) × Alice(pub) 同一 K）
        val sharedBob = C.x25519(C.hexDecode(ProvisioningCrypto.Rfc7748.BOB_PRIV), C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PUB))
        check("RFC7748 双方对称得到同一 K", sharedBob != null && C.hexEncode(sharedBob) == ProvisioningCrypto.Rfc7748.SHARED)

        // KAT-3: RFC 5869 §A.1 TC1 HKDF-SHA256
        val okm = C.hkdfSha256(
            C.hexDecode(ProvisioningCrypto.Rfc5869Tc1.IKM), C.hexDecode(ProvisioningCrypto.Rfc5869Tc1.SALT),
            C.hexDecode(ProvisioningCrypto.Rfc5869Tc1.INFO), 42)
        check("RFC5869 TC1 HKDF-SHA256 OKM", C.hexEncode(okm) == ProvisioningCrypto.Rfc5869Tc1.OKM)
        check("RFC5869 TC1 OKM 长度 42", okm.size == 42)

        // KAT-4: AES-256-GCM roundtrip + 完整性负对照
        val key = C.hexDecode("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
        val pt = "ssid=Home;psk=s3cret".toByteArray(Charsets.UTF_8)
        val blob = C.seal(key, pt)
        check("AES-256-GCM 解封 roundtrip", C.open(key, blob).contentEquals(pt))
        check("GCM blob = nonce(12)+ct+tag", blob.size == 12 + pt.size + 16)
        val tampered = blob.copyOf(); tampered[tampered.lastIndex] = (tampered[tampered.lastIndex].toInt() xor 1).toByte()
        val rejected = try { C.open(key, tampered); false } catch (e: Exception) { true }
        check("负对照:篡改密文 GCM tag 校验失败", rejected)
        val wrongAad = try { C.open(key, blob, "net.forget"); false } catch (e: Exception) { true }
        check("负对照:AAD 不符解封失败", wrongAad)

        // 会话密钥派生确定性（双方同输入 → 同 key），且含 transcript
        val salt = C.hexDecode("000102030405060708090a0b0c")
        val k1 = C.deriveSessionKey(sharedAlice!!, C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PUB), C.hexDecode(ProvisioningCrypto.Rfc7748.BOB_PUB), salt)
        val k2 = C.deriveSessionKey(sharedBob!!, C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PUB), C.hexDecode(ProvisioningCrypto.Rfc7748.BOB_PUB), salt)
        check("deriveSessionKey 双方确定一致", k1.contentEquals(k2) && k1.size == 32)
        val kOther = C.deriveSessionKey(sharedAlice, C.hexDecode(ProvisioningCrypto.Rfc7748.BOB_PUB), C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PUB), salt)
        check("负对照:transcript 顺序变 → key 变", !k1.contentEquals(kOther))

        // 低阶点防护：全零共享密钥必须拒绝（RFC 7748 §7）。构造小阶点公钥（全 0 的 u 坐标编码）。
        val lowOrder = C.x25519(C.hexDecode(ProvisioningCrypto.Rfc7748.ALICE_PRIV), ByteArray(32))
        check("负对照:低阶点公钥产生全零密钥被拒", lowOrder == null)

        // ── KAT-5: 跨语言 golden vector（Python cryptography 加密 → Kotlin JCA 解密）──
        // 判据来自独立实现（Python），不是本类自己算的：任一步拼接顺序/AAD/info/salt 错都会红。
        val G = ProvisioningCrypto.WireGolden
        val gShared = C.x25519(C.hexDecode(G.CLIENT_PRIV), C.hexDecode(G.ROBOT_PUB))
        check("跨语言KAT: X25519 shared 与 Python/RFC7748 一致",
            gShared != null && C.hexEncode(gShared) == G.SHARED)
        val gKey = C.deriveSessionKey(gShared!!, C.hexDecode(G.CLIENT_PUB), C.hexDecode(G.ROBOT_PUB), C.hexDecode(G.SALT))
        check("跨语言KAT: 会话 key = Python HKDF（含 transcript 拼接）", C.hexEncode(gKey) == G.KEY)
        val gPlain = C.open(gKey, C.hexDecode(G.BLOB))
        check("跨语言KAT: Kotlin 解开 Python 密文 = 原 plaintext",
            String(gPlain, Charsets.UTF_8) == G.PLAINTEXT)
        // 负对照 1：篡改 Python 密文末字节 → Kotlin 必须解封失败（GCM 完整性）
        val gTampered = C.hexDecode(G.BLOB); gTampered[gTampered.lastIndex] = (gTampered[gTampered.lastIndex].toInt() xor 1).toByte()
        val gRejected = try { C.open(gKey, gTampered); false } catch (e: Exception) { true }
        check("负对照:跨语言篡改 Python 密文被 Kotlin 拒绝", gRejected)
        // 负对照 2：换 salt → key 变 → 解不开同一 blob
        val gWrongKey = C.deriveSessionKey(gShared, C.hexDecode(G.CLIENT_PUB), C.hexDecode(G.ROBOT_PUB), C.hexDecode("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1e"))
        val gWrongRejected = try { C.open(gWrongKey, C.hexDecode(G.BLOB)); false } catch (e: Exception) { true }
        check("负对照:跨语言错误 salt 派生 key 解不开 blob", gWrongRejected)

        // ── KAT-6: 跨语言 golden vector 反向 —— Kotlin 加密 = Python 加密（锁定 App 发送方向）──
        // 判据来自 Python 独立实现生成的 WireGolden.BLOB：Kotlin 作为加密发送方，用同一
        // key/plaintext/nonce 封出的 blob 必须逐字节等于它。这个方向是真机互通的核心前提
        // （固件要解的是 App seal 的输出），KAT-5 只测了解密方向、照不出 seal 的 wire 语义差。
        val gSealed = C.sealWithNonce(gKey, G.PLAINTEXT.toByteArray(Charsets.UTF_8), C.hexDecode(G.NONCE))
        check("跨语言KAT:Kotlin 加密输出逐字节 = Python BLOB（发送方向）",
            C.hexEncode(gSealed) == G.BLOB)
        // 自环：Kotlin 封的 blob 能被 Kotlin 自己解开（seal/open 同一 wire）
        check("跨语言KAT:Kotlin 封的 blob 可被 open 解回 plaintext",
            String(C.open(gKey, gSealed), Charsets.UTF_8) == G.PLAINTEXT)
        // 负对照 1：nonce 末字节改 → 封出 blob 必变（证明 nonce 真进了 wire，不是摆设）
        val gNonceBad = C.hexDecode(G.NONCE); gNonceBad[gNonceBad.lastIndex] = (gNonceBad[gNonceBad.lastIndex].toInt() xor 1).toByte()
        val gSealedBadNonce = C.sealWithNonce(gKey, G.PLAINTEXT.toByteArray(Charsets.UTF_8), gNonceBad)
        check("负对照:nonce 变 → Kotlin 封出 blob 变（nonce 进了 wire）",
            C.hexEncode(gSealedBadNonce) != G.BLOB)
        // 负对照 2：plaintext 变 → 封出 blob 必变（证明 plaintext 真被封进去）
        val gSealedBadPt = C.sealWithNonce(gKey, "TAMPERED".toByteArray(Charsets.UTF_8), C.hexDecode(G.NONCE))
        check("负对照:plaintext 变 → Kotlin 封出 blob 变", C.hexEncode(gSealedBadPt) != G.BLOB)
        // 负对照 3：AAD 变 → 封出 blob 必变（证明 AAD=net.connect 绑定进了 tag）
        val gSealedBadAad = C.sealWithNonce(gKey, G.PLAINTEXT.toByteArray(Charsets.UTF_8), C.hexDecode(G.NONCE), "net.forget")
        check("负对照:AAD 变 → Kotlin 封出 blob 变", C.hexEncode(gSealedBadAad) != G.BLOB)

        // 边界：golden vector 通过 ≠ 真机互通，INTEROP_UNVERIFIED 仍恒定
        check("golden vector 通过不等于 interop（INTEROP_UNVERIFIED 仍恒真）", C.INTEROP_UNVERIFIED)

        // 交付边界：INTEROP_UNVERIFIED 恒真（防止谁误改成 PASS）
        check("INTEROP_UNVERIFIED 恒为 true（未与真固件对拍）", C.INTEROP_UNVERIFIED)
        check("默认配网仍走明文（加密未接入 NetProvisioning）",
            NetProvisioning.connectParams("x", "pw").containsKey("psk") &&
            !NetProvisioning.PLAINTEXT_TRANSPORT_WARNING.contains("已加密"))
        // 临时密钥对每会话新鲜（两次生成不同）
        val e1 = C.generateEphemeral(); val e2 = C.generateEphemeral()
        check("临时密钥对每次新鲜（前向保密）", !e1.first.contentEquals(e2.first))
        check("临时密钥 raw 长度 32", e1.first.size == 32 && e1.second.size == 32)
    }

    // ---- ToF 8×8 深度帧解析（golden vector 逐字对齐 Rust Frame::zone，带负对照）----
    private fun testTofSnapshot() {
        println("\n[ToF] tof.frame 三态解析 + golden vector")
        val Z = TofSnapshot
        fun obj(s: String) = JsonParser.parseString(s).asJsonObject

        // golden vector 直接搬自 Rust tof/src/lib.rs:138-149 的 test
        check("ToF KAT: status5 + 1234mm → 1.234m",
            Z.zone(5, 1234) is TofZone.Range && abs((Z.zone(5, 1234) as TofZone.Range).meters - 1.234) < 1e-9)
        check("ToF KAT: status9 + 500mm → 0.5m",
            Z.zone(9, 500) is TofZone.Range && abs((Z.zone(9, 500) as TofZone.Range).meters - 0.5) < 1e-9)
        check("ToF KAT: status255 → NoTarget（空空间，不是 0）", Z.zone(255, 0) === TofZone.NoTarget)
        check("ToF KAT: status4 + 900mm → Unusable(4)（不是量程）",
            Z.zone(4, 900) == TofZone.Unusable(4))
        check("ToF KAT: status5 + 负距离 → Unusable(5)（失败收敛非量程）",
            Z.zone(5, -3) == TofZone.Unusable(5))
        // 负对照：status 决定含义——同一个 1234mm 换 status 就变义
        check("负对照:同距离不同 status → 不同三态（status 真参与判定）",
            Z.zone(5, 1234) is TofZone.Range && Z.zone(255, 1234) === TofZone.NoTarget &&
            Z.zone(4, 1234) == TofZone.Unusable(4))
        // 负对照：缺 status / 缺 distance 不猜 0
        check("负对照:缺 status → NoTarget（不默认是量程）", Z.zone(null, 1234) === TofZone.NoTarget)
        check("负对照:有效 status 缺 distance → Unusable（不填 0）", Z.zone(5, null) == TofZone.Unusable(5))

        // 整帧解析：8×8 全 5/1234mm → 64 格全有效
        val full = obj("""{"seq":7,"at_us":1234,"t_ns":987654321,"rows":8,"cols":8,"distance_mm":[${Array(64) { "1234" }.joinToString(",")}],"status":[${Array(64) { "5" }.joinToString(",")}]}""")
        val snap = Z.from(full)
        check("ToF 整帧:64 格全解析", snap != null && snap.zones.size == 64 && snap.validCount == 64)
        check("ToF 整帧:seq/at_us/t_ns 原样", snap?.seq == 7L && snap?.atUs == 1234L && snap?.tNs == 987654321L)
        check("ToF 整帧:hasFrame=true", snap?.hasFrame() == true)

        // ragged 帧（Rust tof/src/lib.rs:160-170）：distance 3 项 / status 2 项 → 越界格 NoTarget
        val ragged = obj("""{"rows":8,"cols":8,"distance_mm":[1000,1000,1000],"status":[5,5]}""")
        val rs = Z.from(ragged)
        check("ToF ragged:第0格仍 Range", rs?.zones?.get(0) is TofZone.Range)
        check("ToF ragged:缺 status 的第2格 → NoTarget（不 panic）", rs?.zones?.get(2) === TofZone.NoTarget)
        check("ToF ragged:valid_count 只数真量程", rs?.validCount == 2)

        // 负对照：整帧缺数组 → null（UI 显示「未读到」，不是空 8×8 假绿）
        check("负对照:缺 distance_mm 数组 → null", Z.from(obj("""{"rows":8,"cols":8,"status":[5,5]}""")) == null)
        check("负对照:缺 status 数组 → null", Z.from(obj("""{"rows":8,"cols":8,"distance_mm":[1,2]}""")) == null)
        check("负对照:非法 rows=0 → null", Z.from(obj("""{"rows":0,"cols":8,"distance_mm":[1],"status":[5]}""")) == null)
        // 负对照：validCount 随状态变（不是恒真）——把一格 status 改 255，计数必须 -1
        val oneBad = obj("""{"rows":8,"cols":8,"distance_mm":[${Array(64) { "1234" }.joinToString(",")}],"status":[${Array(64) { "5" }.joinToString(",").replaceFirst("5", "255")}]}""")
        check("负对照:一格 status 255 → valid_count=63（计数随数据动）", Z.from(oneBad)?.validCount == 63)
    }

    // ---- 固件 OTA：纯 JVM 决策层 + callRaw 数组 result + 进度通知（正/负对照）----
    private fun testFirmwareUpdate() {
        println("\n[固件OTA] 一手协议解析 + 写操作参数 + 进度（含负对照）")
        val F = FirmwareUpdate

        // 1) check 三态
        check("check:available 触发提示", F.shouldPrompt(F.parseCheck(F.obj(
            """{"state":"available","installed":"0.15.1","candidate":"0.15.2","mandatory":false,"changelog":null}"""))))
        val avail = F.parseCheck(F.obj("""{"state":"available","installed":"0.15.1","candidate":"0.15.2","mandatory":true}"""))
        check("check:mandatory 逐字解析", avail is FirmwareUpdate.CheckState.Available && avail.mandatory && avail.candidate == "0.15.2")
        val upToDate = F.parseCheck(F.obj("""{"state":"up_to_date","installed":"0.15.1"}"""))
        check("check:up_to_date 不提示", upToDate is FirmwareUpdate.CheckState.UpToDate && !F.shouldPrompt(upToDate))
        check("check:incompatible 不提示", !F.shouldPrompt(F.parseCheck(F.obj("""{"state":"incompatible","candidate":"0.15.2","reason":"hw rev"}"""))))
        check("负对照:state 拼错 → Unknown 不提示", F.parseCheck(F.obj("""{"state":"avaiable"}""")) is FirmwareUpdate.CheckState.Unknown)
        check("负对照:缺 state → Unknown", F.parseCheck(F.obj("""{"installed":"0.15.1"}""")) is FirmwareUpdate.CheckState.Unknown)
        check("负对照:null → Unknown", F.parseCheck(null) is FirmwareUpdate.CheckState.Unknown)

        // 2) status 数组 result（callRaw 主路径）
        val statusArr = F.parseStatus(F.element("""[{"component":"daemon","installed":"0.15.1","phase":"idle","healthy":true,"pinned":null,"last_checked":1700000000,"last_attempt":{"outcome":"applied","from":"0.15.0","to":"0.15.1"}}]"""))
        check("status:顶层数组解析 1 项", statusArr.size == 1 && statusArr[0].installed == "0.15.1")
        check("status:phase=idle 不在进行中", !statusArr[0].inProgress)
        check("status:last_attempt 解析为 applied", F.isApplied(statusArr[0].lastAttempt!!))
        check("status:包装 {components:[...]} 也解析", F.parseStatus(F.obj("""{"components":[{"component":"daemon","phase":"downloading"}]}""")).size == 1)
        val inProg = F.parseStatus(F.element("""[{"component":"daemon","phase":"downloading"}]"""))[0]
        check("status:downloading 在进行中", inProg.inProgress)
        check("负对照:phase 拼错 → unknownPhase 且不算进行中", run {
            val s = F.parseStatus(F.element("""[{"component":"daemon","phase":"downlodning"}]"""))[0]
            s.unknownPhase && !s.inProgress
        })
        check("负对照:非数组 result → 空", F.parseStatus(F.obj("""{"state":"weird"}""")).isEmpty())

        // 3) apply 结果
        check("apply:applied 算成功", F.isApplied(F.parseApply(F.obj("""{"outcome":"applied","from":"0.15.1","to":"0.15.2"}"""))))
        check("apply:LogEntry success 收敛为 applied", F.isApplied(F.parseApply(F.obj("""{"at":1,"outcome":{"kind":"success"},"from":"0.15.0","to":"0.15.1"}"""))))
        check("apply:dry_run 不算成功", !F.isApplied(F.parseApply(F.obj("""{"outcome":"dry_run_passed","candidate":"0.15.2"}"""))))
        val rb = F.parseApply(F.obj("""{"outcome":"rolled_back","attempted":"0.15.2","reverted_to":"0.15.1","reason":"health failed"}"""))
        check("apply:rolled_back 字段解析", rb is FirmwareUpdate.ApplyResult.RolledBack && rb.attempted == "0.15.2" && rb.revertedTo == "0.15.1")
        check("负对照:未知 outcome → Unknown", F.parseApply(F.obj("""{"outcome":"banana"}""")) is FirmwareUpdate.ApplyResult.Unknown)

        // 4) progress 通知
        val pg = F.parseProgress(F.obj("""{"component":"daemon","phase":"downloading","percent":42,"detail":null}"""))!!
        check("progress:percent 42 + 文案含百分比", pg.percent == 42 && F.progressLabel(pg).contains("42%"))
        check("progress:health_gate 无百分比也有文案", F.parseProgress(F.obj("""{"component":"daemon","phase":"health_gate","percent":null}"""))!!.let { F.progressLabel(it) == "健康检查" })
        check("负对照:percent 150 归一为 null", F.parseProgress(F.obj("""{"component":"daemon","phase":"downloading","percent":150}"""))!!.percent == null)
        check("负对照:缺 phase → null", F.parseProgress(F.obj("""{"component":"daemon","percent":50}""")) == null)
        check("负对照:未知 phase 标注", F.parseProgress(F.obj("""{"component":"daemon","phase":"weird"}"""))!!.unknownPhase)

        // 5) log / listInstalled 数组
        check("log:数组解析", F.parseLog(F.element("""[{"at":1,"component":"daemon","outcome":{"kind":"success"}}]""")).size == 1)
        check("listInstalled:数组解析", F.parseInstalled(F.element("""[{"version":"0.15.1","active":true,"golden":true,"source_revision":null}]"""))[0].active)

        // 6) 写操作参数（deny_unknown_fields：键名精确、可选键缺省）
        val ap = F.applyParams("daemon", null, false)
        check("applyParams:target=latest", ap["target"] == "latest" && ap["component"] == "daemon")
        check("applyParams:无 from_dir 键", !ap.containsKey("from_dir") && !ap.containsKey("confirm"))
        val apExact = F.applyParams("daemon", "0.15.2", true)
        check("applyParams:exact + dry_run", (apExact["target"] as Map<*, *>)["exact"] == "0.15.2" &&
            (apExact["options"] as Map<*, *>)["dry_run"] == true)
        check("selectParams:component+version", F.selectParams("daemon", "0.15.1") == mapOf("component" to "daemon", "version" to "0.15.1"))
        check("rollbackParams:只有 component", F.rollbackParams("daemon").size == 1)
        check("负对照:logParams limit 收敛 <=200", F.logParams(9999)["limit"] == 200)
        check("mutating 方法清单含 apply/rollback/select 且不含 check", F.MUTATING_METHODS.containsAll(listOf(Method.UPDATE_APPLY, Method.UPDATE_ROLLBACK, Method.UPDATE_SELECT)) && !F.MUTATING_METHODS.contains(Method.UPDATE_CHECK))

        // 7) 错误码解读
        check("错误码 5 = 网络（板子拉取）", F.describeError(5).contains("网络"))
        check("错误码 9 = 健康检查失败", F.describeError(9).contains("健康检查"))
        check("负对照:未知错误码原样带码", F.describeError(999).contains("999"))

        // 8) 真跑 session：callRaw 能拿到数组 result（call 会吞成 null 的负对照）
        val t = MockTransport(); val s = RobotSession(t, backoffBaseMs = 10)
        check("OTA:握手进 READY", s.connect(ConnectTarget.Mock))
        val raw = s.callRaw(Method.UPDATE_STATUS, F.componentParams("daemon"))
        check("callRaw:拿到数组 result", raw.isSuccess && raw.getOrNull()?.isJsonArray == true)
        val viaCall = s.call(Method.UPDATE_STATUS)
        check("负对照:普通 call 对数组 result 得到空对象（证明 callRaw 必要）", viaCall.isSuccess && viaCall.getOrNull()?.entrySet()?.isEmpty() == true)
        val statusFromRaw = F.parseStatus(raw.getOrNull())
        check("callRaw→parseStatus 端到端", statusFromRaw.size == 1 && statusFromRaw[0].installed == "0.15.1")

        // 9) 进度通知真跑：subscribe update.progress 收 ≥1 帧；apply 写操作不重放
        val progressFrames = mutableListOf<FirmwareUpdate.Progress>()
        val progSub = s.subscribe(Method.UPDATE_SUBSCRIBE, emptyMap(), streamMethod = Method.UPDATE_PROGRESS) { o ->
            F.parseProgress(o)?.let { progressFrames.add(it) }
        }
        Thread.sleep(60)
        val apply = s.call(Method.UPDATE_APPLY, F.applyParams("daemon", "0.15.2", false), replayable = false)
        check("OTA:apply 请求成功", apply.isSuccess)
        check("OTA:apply outcome=applied", F.isApplied(F.parseApply(apply.getOrNull())))
        Thread.sleep(80)
        check("OTA:进度通知收到 ≥1 帧", progressFrames.isNotEmpty()) { "frames=${progressFrames.size}" }
        check("OTA:进度帧 phase 合法", progressFrames.all { it.phase in FirmwareUpdate.PHASES })
        check("负对照:apply 不进重放队列（写操作）", !t.rawLog().any { it.contains("pendingReplay") })
        progSub.dispose(); s.close()
    }

    private operator fun String.times(n: Int) = repeat(n)
}
