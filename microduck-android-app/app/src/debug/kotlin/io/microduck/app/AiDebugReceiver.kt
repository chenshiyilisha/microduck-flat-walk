package io.microduck.app

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.JsonPrimitive
import io.microduck.app.ble.AndroidBleGattLink
import io.microduck.app.ble.DuckBleService
import io.microduck.app.core.AiDebugPolicy
import io.microduck.app.core.BleForegroundPolicy
import io.microduck.app.core.BleTransport
import io.microduck.app.core.ConnectTarget
import io.microduck.app.core.SerialGattLink
import io.microduck.app.core.Wire
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * **debug-only 的 AI 可控调试通道**（本文件只在 `app/src/debug/` 编译，release 包无此组件）。
 *
 * 目的：2026-11-14 真机排障时抓到的真问题 —— App 里没有任何 `Log.*`，点 BLE 连接失败后
 * 真实 `IOException` 被 `RobotSession` 吞掉、再被 `SessionHolder` 换成通用文案，UI 和
 * logcat 都看不到是 GATT 超时还是 status 133，AI 只能靠 uiautomator 猜。
 * 这里补一条「AI 用 adb 发指令 → App 结构化回 JSON」的只读/受限通道，
 * 让下一次真机联调可以直接机器读状态、扫设备、发起连接、读失败原因，而不用人工看图。
 *
 * ── 契约（PC 侧 `tools/ai_debug_bridge.py` 是唯一配套发送方）──
 *   发送：`adb shell am broadcast -f 32 -n io.microduck.app/.AiDebugReceiver \
 *            --es rid <12hex> --es cmd status|scan|connect|mock|rpc|disconnect|help \
 *            [--es arg <MAC>] [--es method <只读方法>] [--es params_json <JSON 对象>]`
 *   接收：`adb logcat -s MicroDuckAiDebug` 里一条**单行 JSON**，含 `v/rid/cmd/ok/ts_ms/build`。
 *   `rid` 必须回填，PC 侧靠它把结果和指令对上；长命令（connect）会先回 `phase=accepted`，
 *   再回 `phase=result`（或超时回 `phase=timeout`，让调用方轮询 `status`）。
 *
 * ── 边界（写死，别扩权）──
 *  · 不建 socket / 不监听端口 / 不申请新权限；唯一出口是 Logcat。
 *  · `rpc` 只发 `AiDebugPolicy.READ_ONLY_METHODS`，一切写类/运动类方法拒绝。
 *  · **不启动前台服务**：Google FGS 平台文档规定 API31+ 后台起 FGS 会抛
 *    `ForegroundServiceStartNotAllowedException`，Receiver 没有可见 Activity ⇒ 不具备前置。
 *    需要后台保活请走设置页的 BLE 面板（那里在 Activity 可见回调里 `DuckBleService.start`）。
 *  · 所有返回值都是 `COLLECTED_ONLY_NOT_PASS` 级观测，**不产出 PASS/验收结论**。
 *
 * 一手依据见 `core/AiDebugPolicy.kt` 类注释（Android 8 显式广播、stopped package flag、
 * goAsync 10 s 预算、`android:exported` 与 manifest receiver 的关系）。
 */
class AiDebugReceiver : BroadcastReceiver() {

    private val gson = Gson()
    private val macRe = Regex("^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

    private data class Command(
        val rid: String,
        val cmd: String?,
        val arg: String?,
        val method: String?,
        val paramsJson: String?,
        val action: String?,
    )

    override fun onReceive(context: Context, intent: Intent) {
        // Intent 不在线程间共享：把所有 extras 一次读出来再交给后台线程。
        val c = Command(
            rid = intent.getStringExtra(AiDebugPolicy.EXTRA_RID) ?: "missing-rid",
            cmd = intent.getStringExtra(AiDebugPolicy.EXTRA_CMD),
            arg = intent.getStringExtra(AiDebugPolicy.EXTRA_ARG),
            method = intent.getStringExtra(AiDebugPolicy.EXTRA_METHOD),
            paramsJson = intent.getStringExtra(AiDebugPolicy.EXTRA_PARAMS_JSON),
            action = intent.action,
        )
        val pending = goAsync()
        Thread({
            try {
                dispatch(context.applicationContext, c)
            } catch (t: Throwable) {
                val o = base(c)
                o.fail("RECEIVER_EXCEPTION: ${t.javaClass.simpleName}: ${clip(t.message, 200)}")
                emit(o)
            } finally {
                // goAsync 的硬契约：无论成功/异常/超时都必须 finish，否则广播 ANR。
                pending.finish()
            }
        }, "microduck-ai-debug").start()
    }

    private fun dispatch(ctx: Context, c: Command) {
        val o = base(c)
        when {
            c.action != null && c.action != AiDebugPolicy.ACTION -> {
                o.fail("ACTION_NOT_ALLOWED", "只接受空 action 或 ${AiDebugPolicy.ACTION} 的显式广播")
                emit(o); return
            }
            !AiDebugPolicy.isCommandAllowed(c.cmd) -> {
                o.fail("CMD_NOT_ALLOWED", "cmd 必须在白名单 ${AiDebugPolicy.COMMANDS}")
                emit(o); return
            }
        }
        when (c.cmd) {
            "help" -> doHelp(o)
            "status" -> doStatus(o)
            "scan" -> doScan(ctx, o)
            "connect" -> doConnect(ctx, c, c.arg)
            "mock" -> doMock(c)
            "rpc" -> doRpc(c, c.method, c.paramsJson)
            "disconnect" -> doDisconnect(o)
            else -> { o.fail("UNREACHABLE_BRANCH"); emit(o) }
        }
    }

    // ---------------------------------------------------------------- 命令实现

    private fun doHelp(o: JsonObject) {
        o.add("commands", gson.toJsonTree(AiDebugPolicy.COMMANDS.toList()))
        o.add("read_only_methods", gson.toJsonTree(AiDebugPolicy.READ_ONLY_METHODS.toList()))
        o.add("forbidden_methods", gson.toJsonTree(AiDebugPolicy.FORBIDDEN_METHODS.toList()))
        o.addProperty("component", AiDebugPolicy.COMPONENT)
        o.addProperty("tag", AiDebugPolicy.TAG)
        o.addProperty("usage", "adb shell am broadcast -f 32 -n ${AiDebugPolicy.COMPONENT} " +
            "--es rid <id> --es cmd <cmd> [--es arg <MAC>] [--es method <method>]")
        o.addProperty("note", "release 不含本组件；本通道只回观测值，不写 PASS")
        emit(o)
    }

    /**
     * 状态快照。特意把**板端自报 API_VERSION** 和 App 声明值并排放出来：
     * 2026-11-14 真机 PC 侧单次 read 稳定拿到 `0x25`=37，而 App `Wire.API_VERSION=40`，
     * 这个 skew 以前完全不可见（读到的值被丢掉）。`api_version_skew=true` 是观测事实，
     * 不是失败判决 —— 上游 `duck-ipc-proto` 明写版本差异「logged and served」。
     */
    private fun doStatus(o: JsonObject) {
        val s = SessionHolder.session
        val sess = JsonObject()
        sess.addProperty("state", SessionHolder.sessionState())
        sess.addProperty("kind", SessionHolder.kind)
        sess.addProperty("note", clip(SessionHolder.note, 240))
        sess.addProperty("mode", SessionHolder.mode.name)
        sess.addProperty("link_status", clip(SessionHolder.linkStatus, 240))
        sess.addProperty("link_level", SessionHolder.linkLevel)
        sess.addProperty("connect_error", clip(SessionHolder.connectError, 200))
        sess.addProperty("last_connect_error", clip(s?.lastConnectError, 240))
        sess.putNullable("peer_api_version", SessionHolder.peerApiVersion)
        sess.addProperty("app_api_version", Wire.API_VERSION)
        sess.addProperty("api_version_skew",
            SessionHolder.peerApiVersion?.let { it != Wire.API_VERSION } ?: false)
        sess.putNullable("remote_session_active", SessionHolder.remoteSessionActive)
        sess.addProperty("model_api_text", clip(SessionHolder.modelApiText, 60))
        sess.addProperty("state_frame_count", SessionHolder.stateFrameCount)
        sess.addProperty("state_hz", (SessionHolder.stateHz * 100).toLong() / 100.0)
        sess.addProperty("state_age_ms", SessionHolder.stateAgeMs())
        sess.addProperty("battery_text", clip(SessionHolder.batteryText, 60))
        sess.addProperty("heartbeat_running", SessionHolder.heartbeatRunning)
        sess.addProperty("sent_count", SessionHolder.sentCount.get())
        sess.addProperty("ui_tick_count", SessionHolder.uiTickCount.get())
        sess.addProperty("last_state", clip(SessionHolder.lastState?.toString(), 400))
        o.add("session", sess)
        o.addProperty("ble_service_uuid", Wire.BLE_SERVICE_UUID)
        o.addProperty("ble_rpc_uuid", Wire.BLE_RPC_UUID)
        o.addProperty("next", "status 只回报观测值；判 PASS 走既有 board_acceptance 证据链")
        emit(o)
    }

    /**
     * 有界 BLE 扫描。沿用设置页的**无硬件 UUID 过滤 + 软件判别**（Pollen 原厂
     * `app-path-design.md` §3.3：bonded peripheral 常以空 service list 广播，硬件过滤会漏）。
     *
     * 🔴 前提逐条机械核对，任一不成立回 `PRECONDITION_FAIL` 而不是「空列表」：
     * 项目 SOP 里踩过「空卡当已烧卡」「netsh 只读缓存当主动扫描」的坑，零应答必须先问
     * 「接收方听不听得懂 / 蓝牙开没开 / 权限有没有 / 扫描器拿没拿到」，再谈设备。
     */
    @SuppressLint("MissingPermission")
    private fun doScan(ctx: Context, o: JsonObject) {
        if (!ctx.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)) {
            o.fail("PRECONDITION_FAIL: NO_BLE_FEATURE", "本机无 BLE 硬件"); emit(o); return
        }
        val mgr = ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter = mgr?.adapter
        if (adapter == null || !adapter.isEnabled) {
            o.fail("PRECONDITION_FAIL: BT_OFF", "先在系统设置打开蓝牙"); emit(o); return
        }
        val missing = BleForegroundPolicy.bleRuntimePermissions(Build.VERSION.SDK_INT)
            .filter { ctx.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) {
            o.fail("PRECONDITION_FAIL: PERMISSION_MISSING ${missing.joinToString(",")}",
                "在系统设置授予「附近的设备」，或在设置页点「去授权」")
            emit(o); return
        }
        val scanner = adapter.bluetoothLeScanner
        if (scanner == null) {
            o.fail("PRECONDITION_FAIL: NO_SCANNER", "蓝牙已开但拿不到 bluetoothLeScanner"); emit(o); return
        }

        val found = Collections.synchronizedMap(LinkedHashMap<String, JsonObject>())
        val broadcasts = AtomicInteger(0)
        val scanError = AtomicReference<String?>(null)
        val stop = CountDownLatch(1)

        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                broadcasts.incrementAndGet()
                record(result)
            }
            override fun onBatchScanResults(results: MutableList<ScanResult>) {
                broadcasts.addAndGet(results.size)
                results.forEach { record(it) }
            }
            override fun onScanFailed(errorCode: Int) {
                scanError.set("code=$errorCode")
                stop.countDown()
            }

            private fun record(r: ScanResult) {
                val dev = r.device
                val addr = dev.address ?: return
                val name = try { r.scanRecord?.deviceName ?: dev.name ?: "" } catch (_: Throwable) { "" }
                val uuidHit = r.scanRecord?.serviceUuids?.any {
                    it.uuid.toString().equals(Wire.BLE_SERVICE_UUID, ignoreCase = true)
                } == true
                val nameHit = name.contains("duck", ignoreCase = true)
                val bonded = try {
                    adapter.bondedDevices?.any { it.address == addr } == true
                } catch (_: Throwable) { false }
                val why = when {
                    uuidHit -> "服务 UUID"
                    nameHit -> "广播名"
                    bonded -> "已绑定"
                    else -> "附近设备"
                }
                val item = JsonObject()
                item.addProperty("name", clip(name, 60))
                item.addProperty("address", addr)
                item.addProperty("rssi", r.rssi)
                item.addProperty("matched_by", why)
                found[addr] = item
            }
        }

        try {
            scanner.startScan(null,
                ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), cb)
        } catch (t: Throwable) {
            o.fail("SCAN_START_FAILED: ${t.javaClass.simpleName}: ${clip(t.message, 160)}")
            emit(o); return
        }
        stop.await(AiDebugPolicy.SCAN_WINDOW_MS, TimeUnit.MILLISECONDS)
        try { scanner.stopScan(cb) } catch (_: Throwable) { }

        val snapshot = synchronized(found) { found.values.toList() }
        val candidates = snapshot.count { it.get("matched_by")?.asString != "附近设备" }
        o.addProperty("window_ms", AiDebugPolicy.SCAN_WINDOW_MS)
        o.addProperty("broadcasts", broadcasts.get())
        o.addProperty("devices_seen", snapshot.size)
        o.addProperty("candidates", candidates)
        o.addProperty("scan_error", scanError.get() ?: "")
        o.add("devices", gson.toJsonTree(snapshot))
        // 🔴 扫描命中 ≠ 连接成功 ≠ 握手成功；verdict 绝不出现 PASS。
        o.addProperty("verdict", when {
            scanError.get() != null -> "SCAN_FAILED"
            broadcasts.get() == 0 -> "INCONCLUSIVE_NO_ADVERTISEMENTS"
            snapshot.isEmpty() -> "INCONCLUSIVE_NO_DEVICES_WITH_ADDRESS"
            candidates == 0 -> "NO_CANDIDATE_OBSERVED"
            else -> "CANDIDATES_OBSERVED"
        })
        o.addProperty("next", "命中后用 connect --es arg <MAC> 发起连接；扫描结果不作验收结论")
        emit(o)
    }

    /**
     * 按 MAC 连真板。与设置页 [io.microduck.app.ble.BleConnectPanel.connect] 走**同一条**
     * `SerialGattLink → BleTransport → SessionHolder.connectWith → RobotSession` 链，
     * 不另写一份握手，避免「AI 通道连得上、UI 连不上」的假绿。
     *
     * ⚠️ 刻意不 `DuckBleService.start(...)`（Receiver 没有可见 Activity，见类注释）；
     *    只 `attach(link)` 保住强引用，避免调试期间 GATT 被 GC。
     */
    @SuppressLint("MissingPermission")
    private fun doConnect(ctx: Context, c: Command, address: String?) {
        val addr = address?.trim()
        val first = base(c)
        if (addr == null || !macRe.matches(addr)) {
            first.fail("INVALID_ARGUMENT", "arg 必须是 MAC（如 CC:C8:37:E3:7C:90）；先跑 scan 取地址")
            emit(first); return
        }
        val missing = BleForegroundPolicy.bleRuntimePermissions(Build.VERSION.SDK_INT)
            .filter { ctx.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) {
            first.fail("PRECONDITION_FAIL: PERMISSION_MISSING ${missing.joinToString(",")}")
            emit(first); return
        }
        val adapter = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter
        if (adapter == null || !adapter.isEnabled) {
            first.fail("PRECONDITION_FAIL: BT_OFF", "先打开蓝牙再 connect"); emit(first); return
        }
        val device = try {
            adapter.getRemoteDevice(addr)
        } catch (t: Throwable) {
            first.fail("GET_REMOTE_DEVICE_FAILED: ${clip(t.message, 160)}"); emit(first); return
        }

        val raw = AndroidBleGattLink(ctx, device, AiDebugPolicy.CONNECT_GATT_TIMEOUT_MS)
        val link = SerialGattLink(raw)
        DuckBleService.attach(link)
        val transport = BleTransport(link, requestTimeoutMs = 4_000)

        first.addProperty(AiDebugPolicy.Field.PHASE, "accepted")
        first.addProperty("address", addr)
        first.addProperty("next", "等 phase=result；超时会回 phase=timeout，可跑 status 轮询。本通道不启动前台服务")
        emit(first)

        val done = CountDownLatch(1)
        SessionHolder.connectWith(transport, ConnectTarget.Ble("AI-$addr")) { ok ->
            val late = base(c)
            late.addProperty(AiDebugPolicy.Field.PHASE, "result")
            late.addProperty(AiDebugPolicy.Field.OK, ok)
            late.addProperty("address", addr)
            late.addProperty("session_state", SessionHolder.sessionState())
            late.addProperty("note", clip(SessionHolder.note, 240))
            late.addProperty("last_connect_error", clip(SessionHolder.session?.lastConnectError, 240))
            late.putNullable("peer_api_version", SessionHolder.peerApiVersion)
            late.addProperty("api_version_skew",
                SessionHolder.peerApiVersion?.let { it != Wire.API_VERSION } ?: false)
            if (!ok) {
                DuckBleService.detach(link)
                try { link.close() } catch (_: Throwable) { }
            }
            emit(late)
            done.countDown()
        }
        if (!done.await(AiDebugPolicy.CONNECT_WAIT_MS, TimeUnit.MILLISECONDS)) {
            val t = base(c)
            t.addProperty(AiDebugPolicy.Field.PHASE, "timeout")
            t.addProperty(AiDebugPolicy.Field.OK, false)
            t.addProperty(AiDebugPolicy.Field.REASON, "ASYNC_PENDING")
            t.addProperty(AiDebugPolicy.Field.NEXT,
                "跑 status 轮询；回调若晚到会另发一条 phase=result（rid 相同）")
            emit(t)
        }
    }

    /** 一键接 Mock 夹具，让 AI 在没有真板时也能检查会话层是否活着。Mock 绝不冒充实机。 */
    private fun doMock(c: Command) {
        val o = base(c)
        val done = CountDownLatch(1)
        val result = AtomicReference<Boolean?>(null)
        SessionHolder.connect("mock") { ok -> result.set(ok); done.countDown() }
        if (!done.await(AiDebugPolicy.MOCK_WAIT_MS, TimeUnit.MILLISECONDS)) {
            o.fail("MOCK_TIMEOUT"); emit(o); return
        }
        o.addProperty(AiDebugPolicy.Field.OK, result.get() == true)
        o.addProperty("session_state", SessionHolder.sessionState())
        o.addProperty("note", clip(SessionHolder.note, 160))
        o.addProperty("warning", "Mock 夹具不是实机读数，不能充当任何验收结论")
        emit(o)
    }

    /** 只读 RPC。`FutureTask.get(6s)` 兜住阻塞式 transport.request，不让 goAsync 超时 ANR。 */
    private fun doRpc(c: Command, method: String?, paramsJson: String?) {
        val o = base(c)
        if (!AiDebugPolicy.isRpcAllowed(method)) {
            o.fail("RPC_METHOD_DENIED",
                "只允许 ${AiDebugPolicy.READ_ONLY_METHODS}；明确禁止 ${AiDebugPolicy.FORBIDDEN_METHODS.take(5)}")
            emit(o); return
        }
        val params = parseParams(paramsJson)
        if (params == null) {
            o.fail("INVALID_PARAMS_JSON", "params_json 必须是 JSON 对象（或留空）"); emit(o); return
        }
        val s = SessionHolder.session
        if (s == null) {
            o.fail("SESSION_NOT_READY: no session", "先跑 mock 或 connect"); emit(o); return
        }
        o.addProperty("method", method)
        o.addProperty("params_json", clip(paramsJson, 200))
        val task = FutureTask { s.call(method!!, params) }
        val worker = Thread(task, "microduck-ai-debug-rpc").apply { isDaemon = true }
        worker.start()
        val r = try {
            task.get(6, TimeUnit.SECONDS)
        } catch (_: TimeoutException) {
            task.cancel(true)
            o.fail("RPC_TIMEOUT", "6 s 内 transport.request 未返回；跑 status 看链路状态")
            emit(o); return
        } catch (t: Throwable) {
            o.fail("RPC_EXCEPTION: ${t.javaClass.simpleName}: ${clip(t.message, 160)}")
            emit(o); return
        }
        if (r.isSuccess) {
            o.addProperty("result_text", clip(r.getOrNull()?.toString(), 900))
        } else {
            o.addProperty(AiDebugPolicy.Field.OK, false)
            o.addProperty(AiDebugPolicy.Field.REASON,
                clip(r.exceptionOrNull()?.message, 240))
        }
        o.addProperty("session_state", s.state.name)
        emit(o)
    }

    private fun doDisconnect(o: JsonObject) {
        val s = SessionHolder.session
        if (s == null) {
            o.addProperty("already", true)
            o.addProperty("session_state", "NONE")
            emit(o); return
        }
        try { s.close() } catch (t: Throwable) {
            o.addProperty("close_exception", t.javaClass.simpleName)
        }
        SessionHolder.note = "已断开（AI 调试通道）"
        SessionHolder.linkStatus = ""
        SessionHolder.linkLevel = 0
        SessionHolder.peerApiVersion = null
        o.addProperty("session_state", SessionHolder.sessionState())
        emit(o)
    }

    // ---------------------------------------------------------------- 工具

    private fun base(c: Command): JsonObject = JsonObject().apply {
        addProperty(AiDebugPolicy.Field.SCHEMA, AiDebugPolicy.RESULT_SCHEMA)
        addProperty(AiDebugPolicy.Field.RID, c.rid)
        addProperty(AiDebugPolicy.Field.CMD, c.cmd ?: "")
        addProperty(AiDebugPolicy.Field.TS_MS, System.currentTimeMillis())
        addProperty(AiDebugPolicy.Field.BUILD, "debug")
        addProperty(AiDebugPolicy.Field.OK, true)
        addProperty(AiDebugPolicy.Field.EVIDENCE, "COLLECTED_ONLY_NOT_PASS")
    }

    private fun JsonObject.fail(reason: String, next: String? = null) {
        addProperty(AiDebugPolicy.Field.OK, false)
        addProperty(AiDebugPolicy.Field.REASON, clip(reason, 320))
        if (next != null) addProperty(AiDebugPolicy.Field.NEXT, clip(next, 320))
    }

    private fun JsonObject.putNullable(k: String, v: Any?) {
        when (v) {
            null -> add(k, JsonNull.INSTANCE)
            is Number -> addProperty(k, v)
            is Boolean -> addProperty(k, v)
            is String -> addProperty(k, v)
            is JsonPrimitive -> add(k, v)
            else -> add(k, gson.toJsonTree(v))
        }
    }

    /** 结果只写 Logcat 固定 TAG 的**单行 JSON**；过长则回退成一条小错误行，绝不切坏 JSON。 */
    private fun emit(o: JsonObject) {
        val line = gson.toJson(o)
        if (line.length <= AiDebugPolicy.MAX_RESULT_CHARS) {
            Log.i(AiDebugPolicy.TAG, line)
            return
        }
        val small = JsonObject()
        small.addProperty(AiDebugPolicy.Field.SCHEMA, AiDebugPolicy.RESULT_SCHEMA)
        small.addProperty(AiDebugPolicy.Field.RID, o.get(AiDebugPolicy.Field.RID)?.asString ?: "")
        small.addProperty(AiDebugPolicy.Field.CMD, o.get(AiDebugPolicy.Field.CMD)?.asString ?: "")
        small.addProperty(AiDebugPolicy.Field.OK, false)
        small.addProperty(AiDebugPolicy.Field.REASON, "RESULT_TOO_LARGE")
        Log.i(AiDebugPolicy.TAG, gson.toJson(small))
    }

    /** 参数只允许 JSON 对象；标量/null/嵌套对象原样交给 Gson，绝不拼字符串。 */
    private fun parseParams(text: String?): Map<String, Any?>? {
        if (text.isNullOrBlank()) return emptyMap()
        return try {
            val obj = JsonParser.parseString(text).asJsonObject
            obj.entrySet().associate { (k, v) ->
                k to when {
                    v.isJsonNull -> null
                    v.isJsonPrimitive && v.asJsonPrimitive.isBoolean -> v.asBoolean
                    v.isJsonPrimitive && v.asJsonPrimitive.isNumber -> v.asNumber
                    v.isJsonPrimitive -> v.asString
                    else -> v
                }
            }
        } catch (_: Throwable) { null }
    }

    private fun clip(s: String?, n: Int): String = when {
        s == null -> ""
        s.length <= n -> s
        else -> s.take(n) + "…(clipped)"
    }
}
