package io.microduck.app

import android.app.Application
import io.microduck.app.core.RobotRepository

/**
 * Application 级单例 —— 持有 [RobotRepository]（阶段 2 重构规划 §4）。
 *
 * ── 为什么用 Application 子类而非 object 单例 ──
 * 重构规划原文：「Repository 由 Application 级单例提供（替代 SessionHolder 的全局性，
 * 但状态出口统一为 Flow）」。`SessionHolder` 是 `object` 单例，其「全局性」是隐式、不可注入、
 * 不可测试的；换成 Application 持有的显式单例后，ViewModel 经工厂从 [MicroDuckApp] 取到
 * 同一个 [RobotRepository] 实例，状态出口统一为 [RobotRepository.onSnapshot] 的不可变快照流，
 * ViewModel 再转成 `StateFlow` 供 UI 观察（官方 UDF 模式）。
 *
 * ── 为什么 [RobotRepository] 用 `by lazy` ──
 * 只在首次访问时构造，避免 Application 构造期就触发网络/线程初始化（Application.onCreate
 * 应尽量轻量，官方性能指南明确）。ViewModel 工厂在 Activity 创建时访问，时机恰当。
 *
 * ── 与 [SessionHolder] 的关系（阶段 2 渐进迁移）──
 * [RobotRepository] 接管**会话 / 状态 / 健康 / 监控**（connect/connectWith/disconnect/
 * refreshHealth/refreshSessionInfo/tick/session），成为这些领域的单一真源。
 * [SessionHolder] 在阶段 2 退化为只承载**驱动参数**（mode/channelIndex/maxVx/…）与
 * **本地遥测计数**（sentCount/headSentCount/uiTickCount/heartbeatRunning），这些是
 * 时间驱动的，保留在 1s tick 里，阶段 5 再彻底删除。
 */
class MicroDuckApp : Application() {

    /** 会话 / 状态 / 健康 / 监控的单一真源，进程内唯一。 */
    val robotRepository: RobotRepository by lazy { RobotRepository() }

    override fun onCreate() {
        super.onCreate()
        // 阶段 2 桥接：把 RobotRepository 注入 SessionHolder，让 SessionHolder 的会话方法
        // （connect/connectWith/refreshHealth/refreshSessionInfo）委托给它，避免双会话。
        // 驱动参数与本地遥测计数仍留在 SessionHolder（时间驱动，阶段 5 迁移）。
        SessionHolder.robotRepository = robotRepository
    }
}
