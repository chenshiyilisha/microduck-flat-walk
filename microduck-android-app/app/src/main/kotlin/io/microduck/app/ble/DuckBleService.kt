package io.microduck.app.ble

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.os.Build
import android.os.IBinder
import io.microduck.app.MainActivity
import io.microduck.app.R
import io.microduck.app.SessionHolder
import io.microduck.app.core.BleForegroundPolicy

/**
 * A1：BLE 链路前台服务 —— 真机 GATT 上板的**硬前置**。
 *
 * 解决的问题：`AndroidBleGattLink` 原先只由 `BleConnectPanel`（Activity 局部变量）持有，
 * Activity 退到后台 / 锁屏后，进程若无前台组件就可能被回收，GATT 引用随之丢失、链路断开。
 * 本服务以 `connectedDevice` 类型保持前台，并**持有同一份 GATT link 引用**，
 * 使切后台 / 锁屏 / 回到控制台页时链路不断（`Ley-WL/ducklink` 的做法）。
 *
 * 一手依据（Google Android 平台文档，非本项目原厂）：
 *  - `developer.android.com/develop/background-work/services/fgs`：API31+ 从后台启动 FGS 抛
 *    `ForegroundServiceStartNotAllowedException` ⇒ [start] **只能在 Activity 可见时调用**；
 *    `onStartCommand` 必须立刻 `startForeground()`，否则系统会在数秒内停掉服务并抛异常。
 *  - `.../fgs-service-types`：API34+ 需 `foregroundServiceType=connectedDevice`，且该类型
 *    要求先持有 BLUETOOTH_CONNECT / SCAN / ADVERTISE 之一（扫描面板已保证）。
 *  - `.../notifications`：API33+ 通知需 POST_NOTIFICATIONS；未授权时服务仍运行，只是通知
 *    栏不可见 —— 所以该权限刻意不并入扫描入口的 requiredPermissions()。
 *
 * 🔴 诚实边界：真 GATT 上板仍未验证（`UNVERIFIED != PASS`）。本服务提供的是**保活机制**，
 *    不等于证明后台链路在真固件上可用；真机验收见
 *    `docs/active/microduck-安卓App-整机落地验收清单-2026-11-13.md` §1。
 *
 * 设计选择：`START_NOT_STICKY`。进程被杀后系统若重建服务，intent 为 null 且 heldLink 已丢，
 * 显示「连接保持中」会是**假状态**；宁可让用户重新连接，也不伪造一条已存在的链路。
 */
class DuckBleService : Service() {

    companion object {
        /** 服务持有 GATT link 的强引用；attach/detach 按实例比对，避免误关新连接。 */
        @Volatile private var heldLink: AndroidBleGattLink? = null

        fun attach(link: AndroidBleGattLink) { heldLink = link }
        fun detach(link: AndroidBleGattLink) {
            if (heldLink === link) heldLink = null
        }

        /** 必须在 Activity 可见时调用（见类注释的 FGS 启动限制）。 */
        fun start(ctx: Context, deviceLabel: String) {
            val i = Intent(ctx, DuckBleService::class.java).putExtra(
                BleForegroundPolicy.EXTRA_DEVICE, deviceLabel)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i)
            else ctx.startService(i)
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, DuckBleService::class.java))
        }
    }

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == BleForegroundPolicy.ACTION_DISCONNECT) {
            // 用户从通知点「断开」：GATT 与会话一起收，不留半开连接。
            Thread { releaseLink(); stopSelf() }.start()
            return START_NOT_STICKY
        }
        val label = intent?.getStringExtra(BleForegroundPolicy.EXTRA_DEVICE).orEmpty()
        // FGS 必须在本方法内立刻 startForeground，不能推迟到异步回调。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                BleForegroundPolicy.NOTIFICATION_ID, buildNotification(label),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
            )
        } else {
            startForeground(BleForegroundPolicy.NOTIFICATION_ID, buildNotification(label))
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        releaseLink()
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    /** 关 GATT + 关会话；两边都吞异常，避免单个 close 失败挡住服务退出。 */
    private fun releaseLink() {
        val link = heldLink
        heldLink = null
        try { link?.close() } catch (_: Throwable) { }
        try { SessionHolder.session?.close() } catch (_: Throwable) { }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = getSystemService(NotificationManager::class.java) ?: return
        if (mgr.getNotificationChannel(BleForegroundPolicy.CHANNEL_ID) == null) {
            mgr.createNotificationChannel(NotificationChannel(
                BleForegroundPolicy.CHANNEL_ID,
                BleForegroundPolicy.CHANNEL_NAME,
                NotificationManager.IMPORTANCE_LOW,   // 常驻链路通知不做声音/heads-up
            ))
        }
    }

    private fun buildNotification(label: String): Notification {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), flags)
        val disconnect = PendingIntent.getService(
            this, 1,
            Intent(this, DuckBleService::class.java)
                .setAction(BleForegroundPolicy.ACTION_DISCONNECT),
            flags)
        // minSdk=26 ⇒ 必须走带 channelId 的构造器（旧单参构造器已弃用且永不会被执行）。
        return Notification.Builder(this, BleForegroundPolicy.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_ble_link)
            .setContentTitle(BleForegroundPolicy.CHANNEL_NAME)
            .setContentText(if (label.isEmpty()) "连接保持中 · 点此返回控制台"
                else "$label · 连接保持中")
            .setContentIntent(open)
            .setOngoing(true)
            // Google 平台文档：前台服务应给用户一个明确的停止入口。
            .addAction(Notification.Action.Builder(
                Icon.createWithResource(this, R.drawable.ic_ble_link), "断开", disconnect
            ).build())
            .build()
    }
}
