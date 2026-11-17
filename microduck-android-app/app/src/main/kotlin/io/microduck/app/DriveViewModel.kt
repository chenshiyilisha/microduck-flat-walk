package io.microduck.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.microduck.app.core.LinkState
import io.microduck.app.core.RobotRepository
import io.microduck.app.core.StateSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 遥控页 ViewModel —— 阶段 2 重构规划 §4。
 *
 * 与 [MainViewModel] 同构：持有 [RobotRepository]（Application 级单例），订阅其不可变快照流，
 * 把数据层快照映射成 UI 层不可变 [UiState]，暴露为 `StateFlow` 供 [DriveActivity] 用
 * `uiState.collect` 渲染。
 *
 * ── 两条更新路径 ──
 * [onSnapshot] 回调更新**状态驱动**字段（会话/状态帧/链路/健康，来自 [RobotRepository.Snapshot]）；
 * [onTick] 更新**时间驱动**字段（本地遥测计数、控制模式、状态帧年龄，来自 [SessionHolder]，
 * 由 1.5s tick 采样）。规划明确保留 tick 用于遥测采样。
 *
 * ── 不引入 Hilt ── ViewModel 由工厂手动构造（见 [DriveViewModelFactory]）。
 */
class DriveViewModel(
    private val robotRepository: RobotRepository,
) : ViewModel() {

    /**
     * 遥控页不可变 UI 状态 —— 单一真源。
     *
     * 覆盖 [DriveActivity.renderHud] / [DriveActivity.renderLinkBanner] 所需的全部展示字段：
     * 会话/状态/链路来自 [RobotRepository.Snapshot]（状态驱动），本地遥测与控制模式来自
     * [SessionHolder]（时间驱动）。
     */
    data class UiState(
        // ── 会话 / 链路（来自 RobotRepository.Snapshot，状态驱动）──
        val kind: String = "—",
        val sessionState: String = "NONE",
        val connected: Boolean = false,
        val linkStatus: String = "",
        val linkLevel: Int = 0,
        val linkState: LinkState = LinkState.UNKNOWN,
        val connectError: String = "",
        // ── 状态帧（来自 RobotRepository.Snapshot）──
        val lastState: StateSnapshot? = null,
        val stateFrameCount: Int = 0,
        val stateHz: Double = 0.0,
        val lastStateMs: Long = 0L,
        // ── 健康 ──
        val batteryText: String = "— 未读到",
        val remoteSessionActive: Boolean? = null,
        // ── 控制模式 / 本地遥测（来自 SessionHolder，时间驱动）──
        val mode: ControlMode = ControlMode.MANUAL,
        val sentCount: Int = 0,
        val headSentCount: Int = 0,
        val heartbeatRunning: Boolean = false,
        val lastInput: String = "— 无输入",
        /** 状态帧年龄(ms)；-1 = 无帧。时间驱动，由 [onTick] 刷新。 */
        val stateAgeMs: Long = -1L,
    )

    private val _uiState = MutableStateFlow(UiState())
    val uiState: StateFlow<UiState> = _uiState.asStateFlow()

    private val snapshotDisposable = robotRepository.onSnapshot { snap ->
        viewModelScope.launch(Dispatchers.Main.immediate) {
            _uiState.update { s ->
                s.copy(
                    kind = snap.kind,
                    sessionState = snap.sessionState,
                    connected = snap.connected,
                    linkStatus = snap.linkStatus,
                    linkLevel = snap.linkLevel,
                    linkState = snap.linkState,
                    connectError = snap.connectError,
                    lastState = snap.lastState,
                    stateFrameCount = snap.stateFrameCount,
                    stateHz = snap.stateHz,
                    lastStateMs = snap.lastStateMs,
                    batteryText = snap.batteryText,
                    remoteSessionActive = snap.remoteSessionActive,
                )
            }
        }
    }

    override fun onCleared() {
        snapshotDisposable.dispose()
        super.onCleared()
    }

    /** 切回手动模式（自动页的一键接管入口）。AUTO→MANUAL 绝不允许残留心跳帧。 */
    fun onSwitchToManual() {
        SessionHolder.selectMode(ControlMode.MANUAL)
        _uiState.update { it.copy(mode = ControlMode.MANUAL) }
    }

    /**
     * 时间驱动采样入口 —— 由 DriveActivity 的 1.5s tick 调用。
     *
     * 更新本地遥测计数、控制模式、状态帧年龄进 UiState。这些是时间驱动的，不在
     * [RobotRepository.Snapshot] 里，规划明确保留在 tick 里。同时触发 [RobotRepository.tick]
     * 更新状态帧速率窗口。
     */
    fun onTick() {
        robotRepository.tick()
        _uiState.update {
            it.copy(
                mode = SessionHolder.mode,
                sentCount = SessionHolder.sentCount.get(),
                headSentCount = SessionHolder.headSentCount.get(),
                heartbeatRunning = SessionHolder.heartbeatRunning,
                lastInput = SessionHolder.lastInput,
                stateAgeMs = SessionHolder.stateAgeMs(),
            )
        }
    }
}
