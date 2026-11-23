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
 * 一手/社区实证的 stopScan 语义（决定本实现不能用「同一 callback 就跳过 stop」）：
 *   · stopScan 是**异步**的，挂起的扫描结果会继续投递一段时间（需 flush/等待收敛），
 *     因此 stop 之后立刻 start 仍可能拿到 code=1；重试前留 500ms 收敛间隔。
 *   · 必须用**同一个 ScanCallback 实例**做 stop/start：传不同 instance 不会移除旧 callback
 *     的注册，反而导致旧回调继续收到结果。设置页用单例 scanCallback 正是为此。
 *   · Android 7.0+ 限制「每 30 秒最多 5 次 start/stop」，反复重试会触发 code=6
 *     (SCAN_FAILED_SCANNING_TOO_FREQUENTLY)，所以重试必须**有界一次**，不可循环。
 *
 * 这是 App 内协调，不声称能接管系统其他进程的扫描；那种情况由失败码文案如实提示。
 */
object BleScanCoordinator {

    /** 官方常量值；不依赖运行时 API 反射，且可用门禁锁住。 */
    const val SCAN_FAILED_ALREADY_STARTED: Int = 1

    @Volatile
    private var current: ScanCallback? = null
    /**
     * begin 时实际使用的 adapter。🔴 end() 必须用它，不能用 [BluetoothAdapter.getDefaultAdapter()]：
     * 多卡/双 SIM 设备上默认卡未必是 begin 的那张，stop 错 adapter 会让旧扫描残留 → 下次必然 code=1。
     * 单一权威：一次扫描的 start/stop 必须落在同一个 adapter 实例上。
     */
    @Volatile
    private var activeAdapter: BluetoothAdapter? = null

    @SuppressLint("MissingPermission")
    @Synchronized
    fun begin(adapter: BluetoothAdapter, cb: ScanCallback) {
        val prev = current
        // 🔴 真机复现（2026-11-21）：设置页用的是单例 scanCallback，code=1 重试/连点时，
        // 系统侧旧扫描正是这个 cb 在跑。若因 prev === cb 提前 return，本次 start 前就
        // 一次 stopScan 都没做 → 再 start 同一个 cb 必然再次 code=1（重试永远失败）。
        // 所以即使同一 callback，也必须先真正 stop，让系统侧释放后再 start。
        if (prev != null) {
            runCatching { adapter.bluetoothLeScanner?.stopScan(prev) }
            current = null
        }
        // 不在这里自动重试：调用方必须亲自收到 onScanFailed(code=1) 才能确认收敛完成。
        activeAdapter = adapter
        current = cb
    }

    /**
     * 只停当前扫描、**不立即重启**。供 code=1 重试路径用：先 stop，等系统侧异步收敛
     * （500ms），再由调用方 startScan。与 [begin] 分开是为了不在 start 前夹第二次 stop
     * —— 那会吃掉收敛间隔，且 30s 内多次 start/stop 会撞 SCAN_FAILED_SCANNING_TOO_FREQUENTLY(6)。
     */
    @SuppressLint("MissingPermission")
    @Synchronized
    fun stop(cb: ScanCallback) {
        if (current !== cb) return
        runCatching { activeAdapter?.bluetoothLeScanner?.stopScan(cb) }
        current = null
    }

    @SuppressLint("MissingPermission")
    @Synchronized
    fun end(cb: ScanCallback) {
        if (current !== cb) return
        runCatching { activeAdapter?.bluetoothLeScanner?.stopScan(cb) }
        current = null
        activeAdapter = null
    }

    /** 失败码 → 可恢复动作文案；未知码保留原码，不假装知道原因。 */
    fun explain(errorCode: Int): String = when (errorCode) {
        SCAN_FAILED_ALREADY_STARTED -> "重复扫描（code=1 · ALREADY_STARTED），已停旧扫描；请重试"
        2 -> "扫描注册失败（code=2），请重启蓝牙"
        3 -> "蓝牙内部错误（code=3），请开关蓝牙重试"
        4 -> "扫描模式不支持（code=4）"
        5 -> "BLE 资源不足（code=5），请关闭其他占用设备"
        6 -> "扫描过于频繁（code=6），请稍后再试"
        else -> "扫描失败 code=$errorCode"
    }
}
