package io.microduck.app.ble

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.mlkit.vision.MlKitAnalyzer
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.appbar.MaterialToolbar
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import io.microduck.app.R
import io.microduck.app.ui.AppDialogs

/**
 * 配对码扫码页（2026-11-21，用户反馈「提示扫码，没有扫码功能」后的真实能力落地）。
 *
 * 一手依据：
 *  · Android 官方 CameraX ML Kit Analyzer：推荐 `CameraController + PreviewView
 *    + MlKitAnalyzer`，由 CameraX 处理 ImageAnalysis ↔ PreviewView 坐标变换。
 *  · ML Kit Barcode Scanning 官方：bundled 模型构建时静态链接、无需 Google Play
 *    services；国内机型不依赖 GMS 也能扫。只启用 QR 格式以加快识别。
 *
 * 边界：本页只把 QR 的原始字符串通过 [EXTRA_SCAN_VALUE] 回传给调用方，
 * 不解析、不存 PSK、不落盘、不上传；解析/保存继续走 BlePairingStore 单一权威。
 */
class PairScanActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_SCAN_VALUE = "io.microduck.app.pair.scan_value"
    }

    private lateinit var previewView: PreviewView
    private lateinit var statusText: TextView
    private var scanner: BarcodeScanner? = null
    private var finished = false

    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startCamera()
            } else {
                AppDialogs.confirm(
                    context = this,
                    title = "无法打开相机",
                    message = "扫码需要相机权限。也可以回到设置页用「手动输入配对码」。",
                    positiveLabel = "知道了",
                    negativeLabel = null,
                    tone = AppDialogs.Tone.WARN,
                    onDismiss = { finish() },
                )
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_pair_scan)

        findViewById<MaterialToolbar>(R.id.pair_scan_toolbar).apply {
            setNavigationIconTint(getColor(R.color.md_text))
            setNavigationOnClickListener { finish() }
        }
        previewView = findViewById(R.id.camera_preview)
        statusText = findViewById(R.id.pair_scan_status)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(android.R.id.content)) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(bars.left, 0, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        } else {
            statusText.text = "请求相机权限"
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        try {
            val options = BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
            scanner = BarcodeScanning.getClient(options)
            val activeScanner = scanner ?: return
            val analyzer = MlKitAnalyzer(
                listOf(activeScanner),
                ImageAnalysis.COORDINATE_SYSTEM_VIEW_REFERENCED,
                ContextCompat.getMainExecutor(this),
            ) { result ->
                val codes = result?.getValue(activeScanner)
                val raw = codes?.firstNotNullOfOrNull { it.rawValue }?.trim()
                if (!finished && !raw.isNullOrEmpty()) {
                    finished = true
                    setResult(RESULT_OK, Intent().putExtra(EXTRA_SCAN_VALUE, raw))
                    finish()
                }
            }
            val controller = LifecycleCameraController(this).apply {
                cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
                setImageAnalysisAnalyzer(ContextCompat.getMainExecutor(this@PairScanActivity), analyzer)
            }
            previewView.controller = controller
            controller.bindToLifecycle(this)
            statusText.text = "正在识别配对码…"
        } catch (e: Exception) {
            statusText.text = "扫码初始化失败，请手动输入"
            AppDialogs.confirm(
                context = this,
                title = "扫码不可用",
                message = "相机初始化失败：${e.message ?: "未知原因"}。可回到设置页手动输入配对码。",
                positiveLabel = "知道了",
                negativeLabel = null,
                tone = AppDialogs.Tone.WARN,
                onDismiss = { finish() },
            )
        }
    }

    override fun onDestroy() {
        scanner?.close()
        scanner = null
        super.onDestroy()
    }
}
