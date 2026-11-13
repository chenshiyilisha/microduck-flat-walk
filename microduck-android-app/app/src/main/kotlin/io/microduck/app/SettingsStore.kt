package io.microduck.app

import android.content.Context

/**
 * 遥控参数持久化 —— 一手依据（2026-11-12「多找点开源app设计方案，取长补短」）：
 *  - `SuhasDissa/ROS_Robot_Controller` README「⚙️ Customization → **Settings Management:
 *    Persistent user preferences**」；配置页单独存在，URL / 播放器选择跨启动保留。
 *  - `ohho-robotics/ohho.apk` README「What is real in this build」表：「Settings IP and port
 *    **Saved in DataStore**. On launch MainViewModel reads them and connects」。
 *  - `NextGTI/ble-rc-controller` README：Settings 里有 **dead zone**、on-screen buttons、
 *    controllers、language，并且「automatic reconnection to your last car」。
 *
 * ⇒ 我们此前把全部参数放在 `SessionHolder` 的 `@Volatile` 内存字段里，进程一死就回默认，
 * 是这几个项目共同没有的短板。这里用 SharedPreferences（零新依赖）补上。
 *
 * ## 🔴 刻意「不」持久化的两项（安全取舍，不是漏做）
 *  - `ControlMode`：**每次冷启动强制回 MANUAL**。OpenBot
 *    `robot/android/app/README.md` DISCLAIMERS 原文：「Make sure you always have a game
 *    controller connected and are familiar with the key mapping, so you can stop the vehicle
 *    at any time.」记住「自动/监督」档会让下次启动失去显著的手动接管入口；
 *    且本版自动模式 App 零驾驶帧、**没有停车能力**，不该默认进入。
 *  - `host:port`：不自动连上次地址。连接必须由用户主动点「连接」发起，
 *    避免冷启动即建链（ble-rc-controller 的重连是「链路断了重连同一台车」，
 *    本项目 `RobotSession` 的 reconnect guard + jitter 已覆盖会话内重连，两者不是一回事）。
 *
 * 只持久化纯参数；每条写入都 clamp，防止手改 prefs 或旧版本残留值把摇杆映射推到危险区间。
 */
object SettingsStore {
    private const val FILE = "microduck_drive_settings"

    private const val K_CHANNEL = "channel"
    private const val K_HEAD_RAD = "head_rad"
    private const val K_INVERT_Y = "invert_y"
    private const val K_MAX_VX = "max_vx"
    private const val K_MAX_VYAW = "max_vyaw"
    private const val K_DRIVE_DZ = "drive_deadzone"
    private const val K_HEAD_DZ = "head_deadzone"
    private const val K_AUTO_HEALTH = "auto_refresh_health"

    /** 与 Settings 页 SeekBar 的 max 一致，load 时全部夹回合法区间。 */
    const val MAX_VX = 0.80f
    const val MAX_VYAW = 2.50f
    const val MAX_DEADZONE = 0.30f

    const val DEF_CHANNEL = 0
    const val DEF_HEAD_RAD = 0
    const val DEF_INVERT_Y = false
    const val DEF_MAX_VX = 0.35f
    const val DEF_MAX_VYAW = 1.20f
    const val DEF_DRIVE_DZ = 0.08f
    const val DEF_HEAD_DZ = 0.08f
    const val DEF_AUTO_HEALTH = false

    private fun prefs(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun load(ctx: Context) {
        val p = prefs(ctx)
        SessionHolder.channelIndex = p.getInt(K_CHANNEL, DEF_CHANNEL).coerceIn(0, 1)
        SessionHolder.headRadIndex = p.getInt(K_HEAD_RAD, DEF_HEAD_RAD).coerceIn(0, 2)
        SessionHolder.invertY = p.getBoolean(K_INVERT_Y, DEF_INVERT_Y)
        SessionHolder.maxVx = p.getFloat(K_MAX_VX, DEF_MAX_VX).coerceIn(0f, MAX_VX).toDouble()
        SessionHolder.maxVyaw = p.getFloat(K_MAX_VYAW, DEF_MAX_VYAW).coerceIn(0f, MAX_VYAW).toDouble()
        SessionHolder.driveDeadzone =
            p.getFloat(K_DRIVE_DZ, DEF_DRIVE_DZ).coerceIn(0f, MAX_DEADZONE).toDouble()
        SessionHolder.headDeadzone =
            p.getFloat(K_HEAD_DZ, DEF_HEAD_DZ).coerceIn(0f, MAX_DEADZONE).toDouble()
        SessionHolder.autoRefreshHealth = p.getBoolean(K_AUTO_HEALTH, DEF_AUTO_HEALTH)
    }

    fun save(ctx: Context) {
        prefs(ctx).edit()
            .putInt(K_CHANNEL, SessionHolder.channelIndex)
            .putInt(K_HEAD_RAD, SessionHolder.headRadIndex)
            .putBoolean(K_INVERT_Y, SessionHolder.invertY)
            .putFloat(K_MAX_VX, SessionHolder.maxVx.toFloat())
            .putFloat(K_MAX_VYAW, SessionHolder.maxVyaw.toFloat())
            .putFloat(K_DRIVE_DZ, SessionHolder.driveDeadzone.toFloat())
            .putFloat(K_HEAD_DZ, SessionHolder.headDeadzone.toFloat())
            .putBoolean(K_AUTO_HEALTH, SessionHolder.autoRefreshHealth)
            .apply()
    }

    /** 「恢复默认」按钮：给持久化一条可观察的负对照，避免「存了但读不回」的假绿。 */
    fun reset(ctx: Context) {
        prefs(ctx).edit().clear().apply()
        load(ctx)
    }
}
