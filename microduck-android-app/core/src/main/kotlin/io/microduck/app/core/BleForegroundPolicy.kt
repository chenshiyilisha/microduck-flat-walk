package io.microduck.app.core

/**
 * BLE 前台服务策略 —— **纯 Kotlin，零 Android 依赖**。
 *
 * 为什么放在 core：app 层的 [DuckBleService] / BleConnectPanel 与 JVM 自检
 * (`tools/selftest.sh`) 必须消费**同一份**定义，否则「Manifest 声明了但代码用另一个字符串」
 * 这类漂移编译照样过、真机才炸。项目铁律：两条消费链 import 同一个函数/常量。
 *
 * 一手依据（Google Android 平台文档，非本项目原厂）：
 *  - `developer.android.com/develop/connectivity/bluetooth/bt-permissions`：
 *    API31+ 的 BLUETOOTH_SCAN / BLUETOOTH_CONNECT 是运行时权限；API30 及以下靠
 *    ACCESS_FINE_LOCATION。
 *  - `developer.android.com/develop/background-work/services/fgs` +
 *    `.../fgs-service-types`：API34+ 必须为前台服务声明 `android:foregroundServiceType`，
 *    `connectedDevice` 类型要求先持有 BLUETOOTH_CONNECT / SCAN / ADVERTISE 之一；
 *    API31+ 从后台启动 FGS 会抛 `ForegroundServiceStartNotAllowedException`
 *    ⇒ **只能在 Activity 可见时启动**（BleConnectPanel 的连接回调在主线程且页面在前台）。
 *  - `developer.android.com/develop/ui/views/notifications`：API33+ 通知需
 *    POST_NOTIFICATIONS 运行时权限；未授权时 FGS 仍运行，只是通知栏不可见。
 * 社区一手佐证：`Ley-WL/ducklink`（Java 原生）用前台服务持 `BluetoothGatt`，
 * 使后台 / 锁屏时链路不断 —— 这正是本项目真 GATT 上板前的硬前置。
 */
object BleForegroundPolicy {

    /** 必须与 AndroidManifest 中 `<service android:foregroundServiceType>` 逐字一致。 */
    const val FGS_TYPE = "connectedDevice"
    const val CHANNEL_ID = "microduck_ble_link"
    const val CHANNEL_NAME = "MicroDuck 蓝牙链路"
    const val NOTIFICATION_ID = 4201
    const val ACTION_DISCONNECT = "io.microduck.app.ble.DISCONNECT"
    const val EXTRA_DEVICE = "io.microduck.app.ble.DEVICE"

    /** A5：链路恢复后「不自动续动」提示的显示时长。超过后由 SessionHolder.tick 清掉。 */
    const val RECOVERY_NOTICE_MS = 4_000L

    /**
     * Manifest 里必须**作为完整权限名**声明的三项。自检会真读 XML、用正则取出所有
     * `android:name` 的值再做集合包含判定 —— 光编译通过证明不了权限声明齐全
     * （缺 FGS 权限时 Service 能编译、运行才崩）。
     *
     * 🔴 别用 `xml.contains(name)` 裸子串：把权限名改成
     * `FOREGROUND_SERVICE_CONNECTED_DEVICE_BROKEN` 时原串仍是子串，检查会假绿
     * （2026-11-13 真负对照实测命中）。必须用**完整值相等**的集合判据。
     */
    val REQUIRED_PERMISSION_NAMES = listOf(
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
        "android.permission.POST_NOTIFICATIONS",
    )

    /** 扫描 / 连接 BLE 前必须已授予的运行时权限（按 API 分档）。 */
    fun bleRuntimePermissions(sdk: Int): List<String> =
        if (sdk >= 31) listOf(
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_CONNECT",
        )
        else listOf("android.permission.ACCESS_FINE_LOCATION")

    /** API33+ 才存在的通知权限；低版本返回 null（不向用户索要系统里没有的权限）。 */
    fun notificationPermission(sdk: Int): String? =
        if (sdk >= 33) "android.permission.POST_NOTIFICATIONS" else null
}
