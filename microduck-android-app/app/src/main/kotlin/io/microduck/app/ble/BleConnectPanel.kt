package io.microduck.app.ble

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import io.microduck.app.ControlMode
import io.microduck.app.R
import io.microduck.app.SessionHolder
import io.microduck.app.core.BleTransport
import io.microduck.app.core.ConnectTarget
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
 *  1. Android 官方 Bluetooth permissions：API31+ 的 SCAN/CONNECT 是运行时权限；
 *     不用扫描结果推位置可加 neverForLocation 并把 FINE_LOCATION 限到 maxSdkVersion=30。
 *  2. BoBo 本地 `docs/design/app-path-design.md` §3.3：**不要用 service UUID 硬件过滤**——
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

    fun requiredPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    private fun granted(): Boolean = requiredPermissions().all {
        activity.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasBleFeature(): Boolean =
        activity.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)

    private fun dp(v: Int): Int = (v * activity.resources.displayMetrics.density).toInt()

    private fun card(fill: Int) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(10).toFloat()
    }

    /** 生成可插入设置页的 View。放在设置页末尾，避免把既有控件挤出可见区。 */
    fun buildView(): View = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(10), dp(8), dp(10), dp(8))
        background = card(activity.getColor(R.color.md_card_alt))

        addView(TextView(activity).apply {
            text = "BLE 连接（运行时权限 · 真 GATT 未上板验证）"
            textSize = 12f; setTypeface(null, Typeface.BOLD)
            setTextColor(activity.getColor(R.color.md_text))
        })
        addView(TextView(activity).apply {
            text = "扫描不做 service UUID 硬件过滤，全量接收后软件判别；" +
                "身份按 serial，地址只是缓存，RSSI 只用于排序。\n" +
                "⚠ 真机固件未联调：连接失败会如实报错，不会显示「已连接」。"
            textSize = 10f; setTextColor(activity.getColor(R.color.md_text_dim))
            setPadding(0, dp(4), 0, dp(6))
        })

        scanButton = MaterialButton(activity).apply {
            text = "扫描附近 BLE 设备"; textSize = 12f; minimumHeight = dp(48)
            contentDescription = "扫描附近 BLE 设备"
            setTextColor(activity.getColor(R.color.md_bg))
            setOnClickListener { onScanClicked() }
        }
        addView(scanButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))

        statusText = TextView(activity).apply {
            text = "未扫描 · 需要先授予「附近的设备」权限"
            textSize = 11f; setTextColor(activity.getColor(R.color.md_text_dim))
            setPadding(0, dp(6), 0, dp(4))
        }
        addView(statusText)

        listCol = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL }
        val scroll = ScrollView(activity).apply { addView(listCol) }
        addView(scroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(160)))
    }

    private fun setStatus(s: String) { statusText?.text = s }

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
            setTextColor(activity.getColor(R.color.md_bg))
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

        // 🔴 传 null filters：官方 §3.3 与 DuckLink 实测都证明 service filter 会漏掉
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

    private fun renderCandidates() {
        val col = listCol ?: return
        val sorted = found.values.sortedWith(
            compareByDescending<Candidate> { it.matchedBy != "附近设备" }.thenByDescending { it.rssi }
        )
        setStatus("收到 $broadcasts 条广播 · 附近 ${found.size} 台 · " +
            "MicroDuck 候选 ${found.count { it.value.matchedBy != "附近设备" }} 台" +
            if (scanning) "\n扫描中（每 0.5s 刷新，不做一次性快照）" else "")
        col.removeAllViews()
        sorted.take(8).forEach { c ->
            val duck = c.matchedBy != "附近设备"
            col.addView(TextView(activity).apply {
                text = "${if (duck) "● " else "○ "}${c.name.ifEmpty { "(无名)" }} · ${c.address}\n" +
                    "${c.rssi} dBm · 判别=${c.matchedBy} · 地址仅作缓存"
                textSize = 10.5f
                setTextColor(if (duck) activity.getColor(R.color.md_accent)
                else activity.getColor(R.color.md_text_dim))
                background = card(if (duck) activity.getColor(R.color.md_card)
                else Color.TRANSPARENT)
                setPadding(dp(8), dp(5), dp(8), dp(5))
                minimumHeight = dp(40)
                gravity = Gravity.CENTER_VERTICAL
                if (duck) setOnClickListener { connect(c) }
                contentDescription = if (duck) "连接 BLE 设备 ${c.name}" else "非候选设备"
            })
        }
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
        setStatus("正在连接 ${c.name.ifEmpty { c.address }} …\n" +
            "⚠ 真 GATT 未上板验收：若握手失败会显示具体原因，不会显示已连接")
        val link = AndroidBleGattLink(activity.applicationContext, c.device)
        val transport = BleTransport(link)
        // serial 用广播名（BoBo §8.2：地址会变、serial 不变；当前固件未在广播里给 serial，
        // 这里以名字作为身份候选并明确标注，绝不把 address 当身份）。
        val serial = c.name.ifEmpty { "UNKNOWN-${c.address}" }
        SessionHolder.connectWith(transport, ConnectTarget.Ble(serial)) { ok ->
            ui.post {
                setStatus(if (ok) "已连接 BLE · $serial（会话 READY）"
                else "⚠ BLE 握手失败 · ${SessionHolder.note}。请确认设备是 MicroDuck 固件，" +
                    "或改用 TCP relay；真 GATT 上板验收仍 UNVERIFIED")
                SessionHolder.selectMode(ControlMode.MANUAL)
            }
        }
    }

    fun onDestroy() { stopScan(); ui.removeCallbacksAndMessages(null) }
}
