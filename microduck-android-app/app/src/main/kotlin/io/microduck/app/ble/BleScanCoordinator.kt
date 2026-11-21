package io.microduck.app.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.ScanCallback

/**
 * App 内 BLE 扫描互斥闸。
 *
 * 🔴 一手依据：Android `ScanCallback.SCAN_FAILED_ALREADY_STARTED`（常量值 **1**）的官方定义是
 *    “Fails to start scan as BLE scan with the same settings is already started **by the app**”。
 *    所以真机上的「扫描失败 code=1」不是板子不在、也不是蓝牙/定位开关没开，而是**本 App**
 *    已有同设置扫描在跑。设置页 12s 扫描与 AI 调试 scan 若各持一个 ScanCallback，任何一方
 *    残留（Activity 重建 / 用户连点 / 调试命令 + UI 同时点）都会让另一方必然拿到 code=1。
 *
 * 本对象只做一件事：**同一时刻最多允许一个 callback 处于 active**。
 *   · 新扫描开始前停掉旧 callback；
 *   · 调用方在收到 code=1 时做一次有界重试（等系统侧异步收敛）；
 *   · 不把 code=1 误报成硬件/权限故障。
 *
 * 这是 App 内协调，不声称能接管系统其他进程的扫描；那种情况由失败码文案如实提示。
 */
object BleScanCoordinator {

    /** 官方常量值；不依赖运行时 API 反射，且可用门禁锁住。 */
    const val SCAN_FAILED_ALREADY_STARTED: Int = 1

    @Volatile
    private var current: ScanCallback? = null

    @SuppressLint("MissingPermission")
    @Synchronized
    fun begin(adapter: BluetoothAdapter, cb: ScanCallback) {
        val prev = current
        if (prev === cb) return
        if (prev != null) {
            runCatching { adapter.bluetoothLeScanner?.stopScan(prev) }
            current = null
        }
        // 不在这里自动重试：调用方必须亲自收到 onScanFailed(code=1) 才能确认收敛完成。
        current = cb
    }

    @SuppressLint("MissingPermission")
    @Synchronized
    fun end(cb: ScanCallback) {
        if (current !== cb) return
        runCatching {
            BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner?.stopScan(cb)
        }
        current = null
    }

    /** 失败码 → 可恢复动作文案；未知码保留原码，不假装知道原因。 */
    fun explain(errorCode: Int): String = when (errorCode) {
        SCAN_FAILED_ALREADY_STARTED ->
            "扫描已被本 App 的另一次扫描占用（code=1 = ALREADY_STARTED），已自动停旧扫描；" +
                "请重试一次。若反复出现，关掉 AI 调试扫描后再试"
        2 -> "扫描注册失败（code=2）。请重启蓝牙或重装 App"
        3 -> "蓝牙内部错误（code=3）。请开关一次蓝牙后重试"
        4 -> "不支持该扫描模式（code=4）。请升级系统或改用 TCP relay"
        5 -> "硬件资源不足（code=5，Android 13+）。请关闭其他占用 BLE 的 App 后重试"
        6 -> "扫描过于频繁（code=6，Android 13+）。请稍等几秒再试"
        else -> "扫描失败 code=$errorCode。请确认蓝牙/定位开关已开，或改用 TCP relay"
    }
}
