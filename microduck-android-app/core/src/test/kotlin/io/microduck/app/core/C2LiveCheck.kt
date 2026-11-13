package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * C2 活体验证 —— 把 core 会话层接到**真** `robotd --sim` 的 unix socket（经纯字节 relay）。
 *
 * 与 LocalRelayServer / MockTransport 的本质区别：这里没有任何 canned 响应，每条应答都由
 * WSL2 里编译好的 Rust `robotd` 真进程产生。relay 只做 AF_UNIX ↔ TCP 字节转发，不改协议。
 *
 * 证据边界（必须随结果一起读，别外推）：
 *  - WSL2 里的是 **B 代 DuckBuddy-main，API_VERSION=16 / daemon 0.10.0**；App 目标固件是
 *    fanhao `hd1910-v167-trunk-imu-i2c`（API 40）。这里验证的是**跨版本共通的传输/会话语义**
 *    （NDJSON 分帧、版本差异不硬拒、错误码、只读业务调用、订阅端点、认证归属），
 *    **不证明** fanhao 特有方法面，也不证明真机 BLE GATT 时序。
 *  - 未起 body_server ⇒ 控制循环不跑（control_loop.ticks=0），robot.state 通知流不可达，
 *    标 `INCONCLUSIVE_LIVE_STATE_STREAM`，**不**计入 PASS。
 *  - 无整机 / 无 Android 真机 ⇒ 不涉及 BLE、驾驶、视频。
 *
 * 用法：java -cp build/fat io.microduck.app.core.C2LiveCheck <host> <port>
 */
object C2LiveCheck {
    private var passed = 0
    private var failed = 0

    private fun check(name: String, cond: Boolean, detail: () -> String = { "" }) {
        if (cond) { passed++; println("  PASS  $name") }
        else { failed++; println("  FAIL  $name  ${detail()}") }
    }

    private fun intOrNull(o: JsonObject?, key: String): Int? = try {
        o?.get(key)?.takeIf { !it.isJsonNull }?.asInt
    } catch (_: Exception) { null }

    @JvmStatic
    fun main(args: Array<String>) {
        val host = args.getOrNull(0) ?: "127.0.0.1"
        val port = args.getOrNull(1)?.toIntOrNull() ?: 7788
        println("=" * 68)
        println("C2 LIVE CHECK  |  core -> TCP relay -> real robotd --sim (AF_UNIX)")
        println("target=$host:$port  |  expected firmware: B-gen API_VERSION=16")
        println("=" * 68)

        // ① 正常会话：AUTO 策略应按 TCP 链路跳过 BLE 专属的 PIN 认证。
        val s = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            maxReconnectAttempts = 2)
        val ok = s.connect(ConnectTarget.Tcp(host, port))
        check("真固件握手到 READY(TCP/AUTO 跳过 BLE 认证)", ok && s.state == RobotSession.State.READY) {
            "ok=$ok state=${s.state}"
        }
        if (!ok) {
            println("RESULT: $passed passed, ${failed + 1} failed (abi-fatal: no handshake)")
            kotlin.system.exitProcess(1)
        }

        val events = mutableListOf<RobotSession.Event>()
        s.onEvent { events.add(it) }

        // ② 版本差异被 logged and served：App 发 api_version=40，真固件答 16 且不拒。
        //    一手：B 代 lib.rs:552「a version difference is logged and served」；fanhao lib.rs 顶注同。
        val hello = s.call(Method.HELLO, mapOf("api_version" to Wire.API_VERSION))
        val helloBody = hello.getOrNull()
        check("真固件应答 hello(api_version=40 不被硬拒)",
            hello.isSuccess && intOrNull(helloBody, "api_version") == 16) { "resp=$helloBody" }
        check("负对照:版本不是 40(确由真固件回自己的版本)",
            intOrNull(helloBody, "api_version") != 40 && helloBody?.has("daemon_version") == true) {
            "resp=$helloBody"
        }
        check("负对照:HelloResult 无 serial(与夹具不同,会话层不得依赖)",
            helloBody?.has("serial") != true) { "resp=$helloBody" }

        // ③ 只读业务调用：真 health 结构（没起 body_server ⇒ healthy=false 是预期的，不是故障）
        val health = s.call(Method.ROBOT_HEALTH)
        val hb = health.getOrNull()
        check("真 robot.health 可达且含真实结构", health.isSuccess &&
            hb?.has("control_loop") == true && hb?.has("bus") == true && hb?.has("healthy") == true) { "resp=$hb" }
        check("负对照:无仿真体时 healthy=false(不是夹具的假健康)",
            hb?.get("healthy")?.takeIf { !it.isJsonNull }?.asBoolean == false) { "resp=$hb" }

        // ④ 错误码真透传 + 会话层版本 skew 分类
        val bogus = "c2.method.does.not.exist"
        val bogusResult = s.call(bogus)
        check("负对照:未知方法真回 -32601",
            bogusResult.isFailure && events.any {
                it is RobotSession.Event.CapabilityUnsupported && it.method == bogus
            }) { "r=$bogusResult events=$events" }
        check("负对照:未知方法被标 unsupported 并短路", s.isUnsupported(bogus))

        // ⑤ 真订阅端点：result.accepted=true + 策略名，证明 robot.subscribe 契约在真固件上成立。
        val sub = s.call(Method.ROBOT_SUBSCRIBE, mapOf("hz" to 4))
        val sb = sub.getOrNull()
        check("真 robot.subscribe 被接受", sub.isSuccess &&
            sb?.get("accepted")?.takeIf { !it.isJsonNull }?.asBoolean == true) { "resp=$sb" }
        check("负对照:订阅后 request/响应分流未被通知污染",
            s.call(Method.ROBOT_HEALTH).isSuccess) { "session=${s.state}" }

        s.close()

        // ⑥ 核心负对照：强制走 BLE 的 REQUIRED 认证策略，在真固件上必须失败。
        //    若这条变绿（也连上了），说明 relay 在偷偷造 canned 认证应答 ⇒ 整轮证据作废。
        val s2 = RobotSession(TcpTransport(requestTimeoutMs = 5_000), backoffBaseMs = 20,
            authPolicy = RobotSession.AuthPolicy.REQUIRED, maxReconnectAttempts = 1)
        val ok2 = s2.connect(ConnectTarget.Tcp(host, port))
        check("负对照:强制 REQUIRED 在真 robotd 上握手失败(证明认证只属于 BLE)",
            !ok2 && s2.state != RobotSession.State.READY) { "ok=$ok2 state=${s2.state}" }
        s2.close()

        println("\n--- 证据边界 ---")
        println("INCONCLUSIVE_LIVE_STATE_STREAM: 未起 body_server，控制循环 ticks=0，")
        println("  真 robot.state 通知流 / 重连后重订阅推送未验证（需 Windows 侧 body_server + 双鸭门禁）。")
        println("NOT_VERIFIED: fanhao API40 特有方法面、真机 BLE GATT/bonding/CCCD 时序、驾驶与视频。")
        println("=" * 68)
        println("C2 RESULT: $passed passed, $failed failed")
        println("=" * 68)
        if (failed > 0) kotlin.system.exitProcess(1)
    }

    private operator fun String.times(n: Int) = repeat(n)
}
