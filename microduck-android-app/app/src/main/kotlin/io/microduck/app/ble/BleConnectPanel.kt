package io.microduck.app.ble

import android.app.AlertDialog
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import io.microduck.app.ControlMode
import io.microduck.app.R
import io.microduck.app.SessionHolder
import io.microduck.app.core.BleForegroundPolicy
import io.microduck.app.core.BleTransport
import io.microduck.app.core.ConnectTarget
import io.microduck.app.core.SerialGattLink
import io.microduck.app.core.Wire
import java.util.Locale

/**
 * BLE 连接面板 —— 把 A1 欠账补齐：运行时权限、设备发现、真实 [BleTransport] 入口。
 *
 * ⚠️ **边界（项目铁律 UNVERIFIED != PASS）**：本面板的**权限流程 / 拒绝降级 / 候选判别 /
 * 失败提示**能在无整机环境下用 Android 真机验证；但 `AndroidBleGattLink` 的真 GATT I/O
 * （bonding / CCCD / onCharacteristicWrite 串行 / MTU）**未上板验收**，点连接若失败必须如实
 * 显示失败，绝不能显示「已连接」。core 侧 `BleTransport` 协议编排已用 FakeGattLink 在 JVM 真测。
 *
 * ── 一手依据 ──
 *  1. Google Android 平台文档 Bluetooth permissions：API31+ 的 SCAN/CONNECT 是运行时权限；
 *     本 App 不用扫描结果推位置可加 neverForLocation，BLE 运行时权限集合不含位置权限。
 *     （`ACCESS_FINE_LOCATION` 仍全版本声明，但只用于设置页读手机当前 Wi-Fi 名称。）
 *  2. **Pollen 原厂** `docs/design/app-path-design.md` §3.3（经 BoBo 本地副本核对）：**不要用 service UUID 硬件过滤**——
 *     bonded peripheral 常以空 service list 广播，过滤后「not reported at all」；
 *     应「scan unfiltered and discriminate your own candidates」，且「poll until a candidate
 *     appears」，单次 sleep 后取快照不可靠。
 *     独立佐证：`Ley-WL/ducklink` 0.9.25「移除 Android 硬件 UUID 过滤，12 秒低延迟全量接收后
 *     以服务 UUID 或严格后缀广播名筛选」——两个独立来源同一结论。
 *  3. `app-path-design.md` §8.2：**serial 是身份**，peripheral 地址只是缓存，
 *     **RSSI 只做排序、绝不当身份**。⇒ 列表按 RSSI 排，文字明写地址不是身份。
 *  4. `mobile-app.md` §2：每条错误都要带「恢复到的那一步」；BLE 后台掉线是
 *     expected, not a fault。§4：BLE 是常驻通道，重连后要重新认证。
 *  5. `mobile-app.md` §6 的握手地板 API_VERSION≥31 **不采纳**：本 App 还需连 B 代 API16
 *     仿真链路（C2/C2+ 活体证据），硬拒会让既有验证全部失效；改用 `RobotSession` 的
 *     -32601 能力降级。
 */
class BleConnectPanel(private val activity: AppCompatActivity) {

    companion object {
        const val REQ_CODE = 4711
        /** 通知权限单独请求码：刻意与 BLE 权限分开，避免被 onPermissionResult 误判为扫描授权。 */
        const val REQ_CODE_NOTIF = 4712
        private const val SCAN_MS = 12_000L
        private const val REFRESH_MS = 500L
        private val DUCK_NAME = Regex("duck", RegexOption.IGNORE_CASE)
    }

    private data class Candidate(
        val device: BluetoothDevice,
        val name: String,
        val address: String,
        val rssi: Int,
        val matchedBy: String,
    )

    private val ui = Handler(Looper.getMainLooper())
    private val found = LinkedHashMap<String, Candidate>()
    private var scanning = false
    private var broadcasts = 0
    private var statusText: TextView? = null
    private var listCol: LinearLayout? = null
    private var scanButton: MaterialButton? = null

    /**
     * 权限集合**不在这里另写一份**，统一走 core 的 [BleForegroundPolicy]，
     * 让 JVM 自检与真机消费链共用同一判据（项目铁律：两条链 import 同一函数）。
     * ⚠️ 刻意不含 POST_NOTIFICATIONS：那只影响通知可见性，不该挡住 BLE 扫描入口。
     */
    fun requiredPermissions(): Array<String> =
        BleForegroundPolicy.bleRuntimePermissions(Build.VERSION.SDK_INT).toTypedArray()

    private fun granted(): Boolean = requiredPermissions().all {
        activity.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasBleFeature(): Boolean =
        activity.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)

    private fun dp(v: Int): Int = (v * activity.resources.displayMetrics.density).toInt()

    private fun card(fill: Int) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(16).toFloat()
    }

    /**
     * 生成可插入设置页的 View。
     * 2026-11-20 IA 对照 Android Settings + M3 Lists（见 docs/active/…连接配网UI设计依据）：
     * 标题 → 状态 → 一句 supporting → 扫描 CTA → 两行列表项；
     * **去掉内嵌 ScrollView**（父设置页已滚，嵌套曾导致门禁滚屏坑）。
     * 门禁硬串「BLE 连接」「扫描附近 BLE 设备」原样保留。
     */
    fun buildView(): View = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(0, 0, 0, 0)

        addView(TextView(activity).apply {
            text = "BLE 连接"
            textSize = 14f; setTypeface(null, Typeface.BOLD)
            setTextColor(activity.getColor(R.color.md_text))
        })
        statusText = TextView(activity).apply {
            text = "未扫描 · 需要先授予「附近的设备」权限"
            textSize = 12f; setTextColor(activity.getColor(R.color.md_text_dim))
            setPadding(0, dp(4), 0, dp(2))
        }
        addView(statusText)
        addView(TextView(activity).apply {
            text = "先用手机相机扫描机器人配对码 · 密钥由 Android Keystore 加密保存"
            textSize = 11f; setTextColor(activity.getColor(R.color.md_text_dim))
            setPadding(0, 0, 0, dp(10))
        })

        scanButton = MaterialButton(activity, null,
            com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
            text = "扫描附近 BLE 设备"; textSize = 13f; minimumHeight = dp(48)
            contentDescription = "扫描附近 BLE 设备"
            cornerRadius = dp(16)
            strokeWidth = dp(1)
            strokeColor = android.content.res.ColorStateList.valueOf(activity.getColor(R.color.md_outline))
            setTextColor(activity.getColor(R.color.md_text))
            setOnClickListener { onScanClicked() }
        }
        addView(scanButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))

        listCol = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(8), 0, 0)
        }
        addView(listCol, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
    }

    private fun setStatus(s: String) { statusText?.text = s }

    fun handlePairingIntent(intent: Intent?): Boolean {
        val uri = intent?.data ?: return false
        if (intent.action != Intent.ACTION_VIEW) return false
        val pairing = try {
            BlePairingStore.parsePairingUri(uri)
        } catch (_: Exception) {
            setStatus("⚠ 配对二维码无效。请在机器人重新生成配对码后再扫描")
            AlertDialog.Builder(activity)
                .setTitle("无法导入配对码")
                .setMessage("二维码格式无效或密钥长度不正确。")
                .setPositiveButton("知道了", null)
                .show()
            return true
        }
        val replacing = BlePairingStore.contains(activity, pairing.serial)
        AlertDialog.Builder(activity)
            .setTitle(if (replacing) "更换机器人配对密钥" else "保存机器人配对密钥")
            .setMessage("${pairing.name}\n序列号：${pairing.serial}\n\n密钥将加密保存在此设备上。")
            .setPositiveButton(if (replacing) "更换" else "保存") { _, _ ->
                try {
                    BlePairingStore.save(activity, pairing)
                    setStatus("配对密钥已安全保存 · 连接时仅匹配广播名称")
                } catch (_: Exception) {
                    setStatus("⚠ 配对密钥保存失败。请检查设备存储空间后重试")
                } finally {
                    pairing.psk.fill(0)
                }
            }
            .setNegativeButton("取消") { _, _ -> pairing.psk.fill(0) }
            .setOnCancelListener { pairing.psk.fill(0) }
            .show()
        return true
    }

    private fun onScanClicked() {
        if (!hasBleFeature()) {
            setStatus("⚠ 本机无 BLE 硬件。请改用 TCP relay：在上方地址栏填 host:port 后点「连接」")
            return
        }
        if (!granted()) {
            setStatus("⚠ 附近设备权限未授予。点下方「去授权」在系统弹窗允许后，会自动继续扫描")
            renderNeedPermission()
            return
        }
        startScan()
    }

    /** 用户拒绝权限后走这里：错误带恢复步骤，不自动重试、不假装连上。 */
    fun onPermissionResult(grantResults: IntArray) {
        val ok = grantResults.isNotEmpty() && grantResults.all {
            it == PackageManager.PERMISSION_GRANTED
        }
        if (ok) {
            setStatus("权限已授予 · 开始扫描")
            startScan()
        } else {
            setStatus("⚠ 权限被拒绝，BLE 不可用。可到「系统设置 → 应用 → MicroDuck → 权限」打开；" +
                "或改用 TCP relay（地址栏填 host:port）")
        }
    }

    private fun renderNeedPermission() {
        listCol?.removeAllViews()
        listCol?.addView(MaterialButton(activity).apply {
            text = "去授权"; textSize = 12f; minimumHeight = dp(48)
            contentDescription = "去授权 BLE 权限"
            setTextColor(activity.getColor(R.color.md_on_accent))
            setOnClickListener {
                activity.requestPermissions(requiredPermissions(), REQ_CODE)
            }
        })
    }

    @SuppressLint("MissingPermission")
    private fun startScan() {
        val mgr = activity.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter = mgr?.adapter
        if (adapter == null || !adapter.isEnabled) {
            setStatus("⚠ 蓝牙未开启。请先在系统设置打开蓝牙，再回来点「扫描附近 BLE 设备」")
            return
        }
        val scanner = adapter.bluetoothLeScanner
        if (scanner == null) {
            setStatus("⚠ 拿不到 BLE 扫描器。请确认蓝牙已开启，或改用 TCP relay")
            return
        }
        found.clear(); broadcasts = 0
        listCol?.removeAllViews()
        scanning = true
        setStatus("扫描中 · 全量接收（无 UUID 硬件过滤）…")

        // 🔴 传 null filters：Pollen 原厂 `app-path-design.md` §3.3 与 DuckLink 实测都证明 service filter 会漏掉
        // 以空 service list 广播的已绑定设备。判别放到下面的 discriminate()。
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        try {
            scanner.startScan(null, settings, scanCallback)
        } catch (e: SecurityException) {
            scanning = false
            setStatus("⚠ 扫描被系统拒绝（权限可能已被撤销）。请重新点「去授权」或用 TCP relay")
            return
        } catch (e: Exception) {
            scanning = false
            setStatus("⚠ 扫描启动失败：${e.message}。请重开蓝牙后重试，或改用 TCP relay")
            return
        }

        // 轮询刷新而非「sleep 后取一次快照」：广播是周期性的，候选要持续累积。
        ui.post(object : Runnable {
            override fun run() {
                if (!scanning) return
                renderCandidates()
                ui.postDelayed(this, REFRESH_MS)
            }
        })
        ui.postDelayed({
            if (!scanning) return@postDelayed
            stopScan()
            setStatus((statusText?.text?.toString() ?: "") + "\n扫描结束（12 秒窗口）")
        }, SCAN_MS)
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            broadcasts++
            val dev = result.device
            val addr = dev.address ?: return
            val advName = result.scanRecord?.deviceName
            val name = advName ?: safeName(dev) ?: ""
            val hit = discriminate(result, name, addr)
            // 每次都更新（RSSI 会变），但保留首次判别的理由，避免列表跳动。
            val old = found[addr]
            found[addr] = Candidate(dev, name, addr, result.rssi, old?.matchedBy ?: hit.first)
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>) {
            results.forEach { onScanResult(0, it) }
        }

        override fun onScanFailed(errorCode: Int) {
            scanning = false
            setStatus("⚠ 扫描失败 code=$errorCode。请确认蓝牙/定位开关已开，或改用 TCP relay")
        }
    }

    @SuppressLint("MissingPermission")
    private fun safeName(dev: BluetoothDevice): String? = try {
        dev.name
    } catch (_: SecurityException) { null }

    /** 软件判别（不强过滤）：UUID > 名字 > 已绑定；「能提供 RPC characteristic」才最终算数。 */
    @SuppressLint("MissingPermission")
    private fun discriminate(result: ScanResult, name: String, addr: String): Pair<String, Boolean> {
        val uuidHit = result.scanRecord?.serviceUuids?.any {
            it.uuid.toString().equals(Wire.BLE_SERVICE_UUID, ignoreCase = true)
        } == true
        val nameHit = DUCK_NAME.containsMatchIn(name)
        val bonded = try {
            (activity.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)
                ?.adapter?.bondedDevices?.any { it.address == addr } == true
        } catch (_: SecurityException) { false }
        val why = when {
            uuidHit -> "服务 UUID"
            nameHit -> "广播名"
            bonded -> "已绑定"
            else -> "附近设备"
        }
        return why to (uuidHit || nameHit || bonded)
    }

    /**
     * 呈现层只列 MicroDuck 候选，隐藏「附近设备」（用户反馈：无名蓝牙不该出现在列表里）。
     *
     * 🔴 扫描层**仍全量接收**，绝不加硬件 UUID 过滤或按设备名筛：原厂
     *    `app-path-design.md` §3.3 明确 bonded peripheral 常以空 service list 广播，
     *    硬件过滤会让它「not reported at all」；这类无名真板子靠「已绑定」判为候选。
     *    所以过滤只绑一手判别字段 [Candidate.matchedBy]（服务 UUID / 广播名 / 已绑定），
     *    隐藏的是 `matchedBy == "附近设备"` 的非目标项，不是「没有名字」的设备。
     *    状态行仍如实报「附近 N 台 / 候选 M 台 / 已隐藏 K 台」，不假装没扫到。
     */
    private fun renderCandidates() {
        val col = listCol ?: return
        val candidates = found.values.filter { it.matchedBy != "附近设备" }
            .sortedWith(compareByDescending<Candidate> { it.rssi })
        val hidden = found.size - candidates.size
        val tail = if (candidates.size > 8) " · 仅列前 8 台" else ""
        setStatus("收到 $broadcasts 条广播 · 附近 ${found.size} 台 · " +
            "MicroDuck 候选 ${candidates.size} 台$tail · 非目标 $hidden 台已隐藏" +
            if (scanning) "\n扫描中（每 0.5s 刷新，不做一次性快照）" else "")
        col.removeAllViews()
        if (candidates.isEmpty()) {
            col.addView(TextView(activity).apply {
                text = "未发现 MicroDuck 候选 · " +
                    (if (found.isEmpty()) "确认板子已通电并靠近后重扫"
                     else "$hidden 台非目标已隐藏")
                textSize = 12f
                setTextColor(activity.getColor(R.color.md_text_dim))
                setPadding(dp(4), dp(10), dp(4), dp(10))
                contentDescription = "无 MicroDuck 候选"
            })
            return
        }
        candidates.take(8).forEachIndexed { i, c ->
            // M3 Lists 两行：headline=名，supporting=RSSI·判别；地址非身份，降到 supporting。
            val shownName = c.name.ifEmpty { "(未广播名称)" }
            col.addView(deviceRow(
                headline = shownName,
                supporting = "${c.rssi} dBm · ${c.matchedBy} · 地址仅缓存",
                first = i == 0,
            ).also { row ->
                row.setOnClickListener { connect(c) }
                row.contentDescription = "连接 BLE 设备 ${c.name}"
            })
        }
    }

    /** M3 两行列表项：56dp 触控；表面略抬升，扫描列表可扫。 */
    private fun deviceRow(headline: String, supporting: String, first: Boolean): LinearLayout =
        LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            minimumHeight = dp(56)
            gravity = Gravity.CENTER_VERTICAL
            isClickable = true; isFocusable = true
            background = card(activity.getColor(R.color.md_card_alt))
            setPadding(dp(12), dp(10), dp(12), dp(10))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).also { if (!first) it.topMargin = dp(6) }
            addView(TextView(activity).apply {
                text = headline
                textSize = 14f
                setTextColor(activity.getColor(R.color.md_text))
                setTypeface(null, Typeface.BOLD)
                maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END
            })
            addView(TextView(activity).apply {
                text = supporting
                textSize = 11f
                setTextColor(activity.getColor(R.color.md_text_dim))
                setPadding(0, dp(2), 0, 0)
                maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END
            })
        }

    @SuppressLint("MissingPermission")
    private fun stopScan() {
        scanning = false
        try {
            (activity.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)
                ?.adapter?.bluetoothLeScanner?.stopScan(scanCallback)
        } catch (_: Exception) { /* 权限被撤/扫描器已关，忽略 */ }
        renderCandidates()
    }

    /** 点候选 ⇒ 构造真 BleTransport 走与 Mock/TCP 完全相同的 RobotSession 握手。 */
    @SuppressLint("MissingPermission")
    private fun connect(c: Candidate) {
        if (!granted()) {
            setStatus("⚠ 连接前权限已失效。请重新点「去授权」，或改用 TCP relay")
            renderNeedPermission()
            return
        }
        val pairing = try {
            BlePairingStore.findByAdvertisementName(activity.applicationContext, c.name)
        } catch (_: Exception) {
            setStatus("⚠ 此广播名称对应多个配对记录。请先移除重名设备的旧配对码")
            return
        } ?: run {
            setStatus("⚠ 此设备尚未配对。先用手机相机扫描该机器的配对码")
            return
        }
        setStatus("正在连接 ${c.name.ifEmpty { c.address }} …\n" +
            "正在验证设备身份并建立加密会话；握手失败不会回退到明文")
        val rawLink = AndroidBleGattLink(activity.applicationContext, c.device)
        // P0 ⑤：用 core 的 SerialGattLink 包装，强制 GATT 操作串行（等前一条回调再发下一条）。
        val link = SerialGattLink(rawLink)
        // A1：先交给前台服务持引用，Activity 退后台后 GATT 不会被回收。
        DuckBleService.attach(link)
        val transport = try {
            BleTransport(link, pairing.psk, expectedSerial = pairing.serial)
        } finally {
            pairing.psk.fill(0)
        }
        val serial = pairing.serial
        SessionHolder.connectWith(transport, ConnectTarget.Ble(serial)) { ok ->
            ui.post {
                if (ok) {
                    var fgsNote = " · 后台保活已启用"
                    // 🔴 必须在 Activity 可见时启动 FGS（API31+ 后台起会抛
                    // ForegroundServiceStartNotAllowedException）。回调在主线程、页面在前台。
                    try {
                        DuckBleService.start(activity, serial)
                    } catch (e: Throwable) {
                        fgsNote = " · ⚠ 保活服务启动失败(${e.javaClass.simpleName})，切后台可能断链"
                    }
                    // 通知权限单独按需请求：失败不影响 BLE 链路，只在通知栏看不到常驻通知。
                    val notif = BleForegroundPolicy.notificationPermission(Build.VERSION.SDK_INT)
                    if (notif != null && activity.checkSelfPermission(notif) !=
                        PackageManager.PERMISSION_GRANTED) {
                        activity.requestPermissions(arrayOf(notif), REQ_CODE_NOTIF)
                    }
                    setStatus("已连接 BLE · $serial（会话 READY$fgsNote）")
                } else {
                    DuckBleService.detach(link)
                    link.close()
                    setStatus("⚠ BLE 握手失败 · ${SessionHolder.note}。请确认设备是 MicroDuck 固件，" +
                        "或改用 TCP relay；真 GATT 上板验收仍 UNVERIFIED")
                }
                SessionHolder.selectMode(ControlMode.MANUAL)
            }
        }
    }

    /**
     * 刻意**不**在这里停前台服务：后台/锁屏保活正是 A1 的设计意图。
     * 用户可从常驻通知的「断开」action 显式停止（Google FGS 平台文档要求可停止）。
     */
    fun onDestroy() { stopScan(); ui.removeCallbacksAndMessages(null) }
}
