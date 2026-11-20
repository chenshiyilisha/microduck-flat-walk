package io.microduck.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.microduck.app.core.ConnectTarget
import io.microduck.app.core.DiagnosticsSnapshot
import io.microduck.app.core.HealthSnapshot
import io.microduck.app.core.LinkState
import io.microduck.app.core.MonitorReport
import io.microduck.app.core.MonitorSource
import io.microduck.app.core.NetSnapshot
import io.microduck.app.core.RobotRepository
import io.microduck.app.core.RobotSession
import io.microduck.app.core.RestController
import io.microduck.app.core.StateSnapshot
import io.microduck.app.core.TofSnapshot
import io.microduck.app.core.RobotTransport
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 控制台首页 ViewModel —— 阶段 2 重构规划 §4。
 *
 * ── 职责（官方 UDF 模式，developer.android.com/topic/libraries/architecture/viewmodel 一手核验）──
 * 1. 持有 [RobotRepository]（Application 级单例，替代 [SessionHolder] 的全局性），
 *    订阅其不可变快照流，把数据层快照映射成 UI 层不可变 [UiState]。
 * 2. 暴露 [uiState] 为 `StateFlow`，UI 用 `lifecycleScope.launch { repeatOnLifecycle(STARTED)
 *    { viewModel.uiState.collect { 渲染 } } }` 观察 —— 单一真源，UI 不各自维护状态。
 * 3. 处理事件（切页、切模式、连接、休息、恢复、更新驱动参数）后更新状态。
 *
 * ── 两条更新路径（为什么）──
 * [RobotRepository.Snapshot] 覆盖**会话 / 状态 / 健康 / 监控**（状态驱动，由 onSnapshot 回调触发）。
 * 但**本地遥测计数**（sentCount/headSentCount/uiTickCount/heartbeatRunning/sinkLabel/lastInput）
 * 与**驱动参数**（mode/channelIndex/maxVx/…）不在 [RobotRepository.Snapshot] 里 —— 它们是
 * 时间驱动 / 用户输入驱动的，保留在 [SessionHolder]，由 1s tick 采样后经 [onTick] 更新进 UiState。
 * 规划原文：「保留 1s tick 仅用于 3D 模型旋转步进与遥测采样（这两项是时间驱动，不是状态驱动）」。
 * ⇒ [onSnapshot] 更新状态驱动字段，[onTick] 更新时间驱动字段，最终都汇入同一个 [_uiState]。
 *
 * ── 不引入 Hilt ──
 * 官方明确「never manually create a ViewModel outside of a ViewModelProvider.Factory」：
 * ViewModel 由工厂手动构造（见 [MainViewModelFactory]），[RobotRepository] 经
 * `APPLICATION_KEY` 从 [MicroDuckApp] 注入，不继承 AndroidViewModel（官方不推荐）。
 */
class MainViewModel(
    private val robotRepository: RobotRepository,
) : ViewModel() {

    /**
     * 控制台首页不可变 UI 状态 —— 单一真源。
     *
     * 所有字段都是「展示用快照」：会话/状态/健康/监控来自 [RobotRepository.Snapshot]
     * （状态驱动），驱动参数与本地遥测来自 [SessionHolder]（时间驱动 / 用户输入驱动）。
     * 每次更新整体替换一个新实例（data class 语义），杜绝「读到中途被改」的竞态。
     */
    data class UiState(
        // ── 会话 / 连接（来自 RobotRepository.Snapshot，状态驱动）──
        val kind: String = "—",
        val sessionState: String = "NONE",
        val connected: Boolean = false,
        val note: String = "",
        val linkStatus: String = "",
        val linkLevel: Int = 0,
        val linkState: LinkState = LinkState.UNKNOWN,
        val connectError: String = "",
        // ── 状态帧（来自 RobotRepository.Snapshot）──
        val lastState: StateSnapshot? = null,
        val stateFrameCount: Int = 0,
        val stateHz: Double = 0.0,
        val lastStateMs: Long = 0L,
        // ── 健康 / 监控（来自 RobotRepository.Snapshot）──
        val lastHealth: HealthSnapshot? = null,
        val tof: TofSnapshot? = null,   // ToF 8×8 深度；null=未读到（Mock 夹具非实机）
        val monitorReport: MonitorReport? = null,
        val batteryText: String = "— 未读到",
        val monitorSource: MonitorSource = MonitorSource.NONE,
        val remoteSessionActive: Boolean? = null,
        val modelApiText: String = "—",
        val peerApiVersion: Int? = null,
        // ── A3/A6/A7 只读诊断（来自 RobotRepository.Snapshot，用户点刷新驱动）──
        val diagnostics: DiagnosticsSnapshot = DiagnosticsSnapshot(),
        // ── A2 Wi-Fi 配网（来自 RobotRepository.Snapshot，用户操作驱动）──
        val net: NetSnapshot = NetSnapshot(),
        val netBusy: Boolean = false,
        val netResultText: String? = null,
        // ── 驱动参数（来自 SessionHolder，用户输入驱动）──
        val mode: ControlMode = ControlMode.MANUAL,
        val channelIndex: Int = 0,
        val headRadIndex: Int = 0,
        val invertY: Boolean = false,
        val maxVx: Double = 0.35,
        val maxVyaw: Double = 1.20,
        val driveDeadzone: Double = 0.08,
        val headDeadzone: Double = 0.08,
        val autoRefreshHealth: Boolean = false,
        // ── 本地遥测（来自 SessionHolder，时间驱动）──
        val sinkLabel: String = "-",
        val sentCount: Int = 0,
        val headSentCount: Int = 0,
        val uiTickCount: Int = 0,
        val heartbeatRunning: Boolean = false,
        val lastInput: String = "— 无输入",
        // ── 页面 / 一次性回显 ──
        val currentPage: Int = 0,
        val restResultText: String? = null,
    )

    private val _uiState = MutableStateFlow(UiState())
    val uiState: StateFlow<UiState> = _uiState.asStateFlow()

    /** 订阅 RobotRepository 快照流：状态驱动字段随快照更新。 */
    private val snapshotDisposable = robotRepository.onSnapshot { snap ->
        // 快照回调可能在后台线程（网络/握手线程 publish）；StateFlow 本身线程安全，
        // 但为 UI 一致性与官方建议，切主线程更新。
        viewModelScope.launch(Dispatchers.Main.immediate) {
            _uiState.update { s ->
                s.copy(
                    kind = snap.kind,
                    sessionState = snap.sessionState,
                    connected = snap.connected,
                    note = snap.note,
                    linkStatus = snap.linkStatus,
                    linkLevel = snap.linkLevel,
                    linkState = snap.linkState,
                    connectError = snap.connectError,
                    lastState = snap.lastState,
                    stateFrameCount = snap.stateFrameCount,
                    stateHz = snap.stateHz,
                    lastStateMs = snap.lastStateMs,
                    lastHealth = snap.lastHealth,
                    tof = snap.tof,
                    monitorReport = snap.monitorReport,
                    batteryText = snap.batteryText,
                    monitorSource = robotRepository.monitorSource(),
                    remoteSessionActive = snap.remoteSessionActive,
                    modelApiText = snap.modelApiText,
                    peerApiVersion = snap.peerApiVersion,
                    diagnostics = snap.diagnostics,
                    net = snap.net,
                    netBusy = snap.netBusy,
                    netResultText = snap.netResultText,
                )
            }
        }
    }

    override fun onCleared() {
        snapshotDisposable.dispose()
        super.onCleared()
    }

    // ── 事件：切页 / 切模式 ──

    /** 切换目的地页（状态/健康/设置/终端）。 */
    fun onSwitchPage(index: Int) {
        _uiState.update { it.copy(currentPage = index) }
    }

    /** 切换控制模式（MANUAL/AUTO）。AUTO 绝不允许残留心跳帧。 */
    fun onSelectMode(m: ControlMode) {
        SessionHolder.selectMode(m)
        _uiState.update { it.copy(mode = m) }
    }

    // ── 事件：连接 ──

    /**
     * 由地址栏连接（Mock/TCP）；BLE 请用 [onConnectWith]。
     *
     * 🔴 ANR 修复（2026-11-17 skill 审计）：调用方 [MainActivity.connectFromUi] 在**主线程**
     * （onCreate / 按钮点击）调用本方法，而 `robotRepository.connect()` 内部
     * `connectWith()` → `RobotSession.connect()` → `TcpTransport.connect()`（socket
     * connect 超时 2s）+ `handshake()`（每请求 latch.await 5s）是**同步阻塞 I/O**。
     * 若在主线程直调，地址栏填真实 TCP 地址时最坏卡住主线程约 7s ⇒ ANR。
     * ⇒ 必须在 [Dispatchers.IO] 建链；结果经快照流（[snapshotDisposable]）回推，
     * UI 的 `connectFromUi()` 不依赖本方法返回值（它本来就忽略返回值）。
     */
    fun onConnect(raw: String) {
        viewModelScope.launch(Dispatchers.IO) {
            robotRepository.connect(raw)
        }
    }

    /**
     * 注入真实传输建链（BLE/TCP 共用）；[onDone] 在主线程回调连接结果。
     *
     * 与 [onConnect] 同因：`connectWith(transport, target)` 同步阻塞（socket + handshake），
     * 必须在 IO 线程执行；[onDone] 显式切回 [Dispatchers.Main] 供 UI 改 View。
     */
    fun onConnectWith(transport: RobotTransport, target: ConnectTarget, onDone: (Boolean) -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val ok = robotRepository.connectWith(transport, target)
            withContext(Dispatchers.Main) { onDone(ok) }
        }
    }

    /** 主动断开并释放会话。 */
    fun onDisconnect() {
        robotRepository.disconnect()
    }

    // ── 事件：健康刷新 ──

    /** 拉取 robot.health（只读）；结果经快照流反映到 UiState。 */
    fun onRefreshHealth() {
        robotRepository.refreshHealth()
    }

    /**
     * A3/A6/A7：拉取全部只读诊断（system.info/services/logs、robot.policies/model、
     * update.status/listInstalled）；结果经快照流反映到 UiState.diagnostics。
     * Repository 内部已放后台线程，这里直接转发。缺数据保持「未读到」，绝不造假。
     */
    fun onRefreshDiagnostics() {
        robotRepository.refreshDiagnostics()
    }

    // ── 事件：A2 Wi-Fi 配网 ──

    /** 拉取 net.status + net.scan（只读）。缺数据保持「未读到」。 */
    fun onRefreshNet() {
        robotRepository.refreshNet()
    }

    /**
     * 连接 Wi-Fi（net.connect，写操作，明文传输）。
     * 🔴 调用前 UI 必须先展示 [NetProvisioning.PLAINTEXT_TRANSPORT_WARNING] 并取得用户确认；
     *    本层不重复弹窗，只负责转发。psk 不进 UiState、不进日志。
     */
    fun onConnectWifi(ssid: String, psk: String?) {
        robotRepository.connectWifi(ssid, psk)
    }

    /** 忘记已存 Wi-Fi（net.forget，写操作）。 */
    fun onForgetWifi(ssid: String) {
        robotRepository.forgetWifi(ssid)
    }

    // ── 事件：休息 / 恢复站立 ──

    /** 会话是否就绪（供 UI 在执行写操作前预检，避免弹确认框后才发现不可执行）。 */
    fun isSessionReady(): Boolean =
        robotRepository.session()?.state == RobotSession.State.READY

    /**
     * 一键休息（robot.rest，写操作）。需会话 READY；结果写入 [UiState.restResultText] 回显。
     * BLE 通道下该方法不在放行白名单，会被拒绝（PERMISSION_DENIED=14），失败如实回显。
     */
    fun onRest() {
        val s = robotRepository.session()
        if (s == null || s.state != RobotSession.State.READY) {
            _uiState.update {
                it.copy(restResultText = "⚠ 会话未就绪，无法休息（${robotRepository.snapshot().sessionState}）")
            }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            val r = RestController(s).requestRest()
            val text = when {
                r.isFailure -> "⚠ 休息失败：${r.exceptionOrNull()?.message ?: "未知错误"}"
                r.getOrNull()?.accepted == true -> "✓ 休息已被板端接受"
                else -> "⚠ 休息未确认接受（accepted≠true）：${r.getOrNull()?.reason ?: "无 reason"}"
            }
            _uiState.update { it.copy(restResultText = text) }
        }
    }

    /** 恢复站立（robot.init，rest 的逆操作）；同样需会话 READY，结果回显。 */
    fun onWake() {
        val s = robotRepository.session()
        if (s == null || s.state != RobotSession.State.READY) {
            _uiState.update {
                it.copy(restResultText = "⚠ 会话未就绪，无法恢复（${robotRepository.snapshot().sessionState}）")
            }
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            val r = RestController(s).requestInit()
            val text = when {
                r.isFailure -> "⚠ 恢复失败：${r.exceptionOrNull()?.message ?: "未知错误"}"
                r.getOrNull()?.accepted == true -> "✓ 恢复已被板端接受"
                else -> "⚠ 恢复未确认接受（accepted≠true）：${r.getOrNull()?.reason ?: "无 reason"}"
            }
            _uiState.update { it.copy(restResultText = text) }
        }
    }

    // ── 事件：驱动参数更新（设置页）──

    /** 更新驱动参数并持久化；参数写入 [SessionHolder]（阶段 2 过渡，阶段 5 迁移）。 */
    fun onUpdateDriveParams(
        channelIndex: Int, headRadIndex: Int, invertY: Boolean,
        maxVx: Double, maxVyaw: Double, driveDeadzone: Double, headDeadzone: Double,
        autoRefreshHealth: Boolean,
    ) {
        SessionHolder.channelIndex = channelIndex
        SessionHolder.headRadIndex = headRadIndex
        SessionHolder.invertY = invertY
        SessionHolder.maxVx = maxVx
        SessionHolder.maxVyaw = maxVyaw
        SessionHolder.driveDeadzone = driveDeadzone
        SessionHolder.headDeadzone = headDeadzone
        SessionHolder.autoRefreshHealth = autoRefreshHealth
        _uiState.update {
            it.copy(
                channelIndex = channelIndex, headRadIndex = headRadIndex, invertY = invertY,
                maxVx = maxVx, maxVyaw = maxVyaw, driveDeadzone = driveDeadzone,
                headDeadzone = headDeadzone, autoRefreshHealth = autoRefreshHealth,
            )
        }
    }

    /**
     * 恢复驱动参数默认值 —— 同步内存状态进 UiState。
     *
     * 🔴 ViewModel 无 Context 约束（官方不推荐 AndroidViewModel），持久化（SettingsStore.reset）
     * 由 MainActivity 在调用本方法前完成：Activity 先 `SettingsStore.reset(ctx)` 清持久化并重载
     * 默认值到 SessionHolder，再调本方法把内存状态同步进 UiState。本方法不碰持久化，
     * 从 [SessionHolder] 读取（已由 SettingsStore.reset 设为默认值）。
     */
    fun onResetDriveParams() {
        _uiState.update {
            it.copy(
                channelIndex = SessionHolder.channelIndex,
                headRadIndex = SessionHolder.headRadIndex,
                invertY = SessionHolder.invertY,
                maxVx = SessionHolder.maxVx,
                maxVyaw = SessionHolder.maxVyaw,
                driveDeadzone = SessionHolder.driveDeadzone,
                headDeadzone = SessionHolder.headDeadzone,
                autoRefreshHealth = SessionHolder.autoRefreshHealth,
            )
        }
    }

    /** 切换自动刷新健康；写入 [SessionHolder]（阶段 2 过渡）并同步进 UiState。 */
    fun onSetAutoRefreshHealth(checked: Boolean) {
        SessionHolder.autoRefreshHealth = checked
        _uiState.update { it.copy(autoRefreshHealth = checked) }
    }

    /**
     * 时间驱动采样入口 —— 由 MainActivity 的 1s tick 调用。
     *
     * 更新本地遥测计数（sentCount/headSentCount/uiTickCount/heartbeatRunning/sinkLabel/lastInput）
     * 与驱动参数（mode 等）进 UiState。这些是时间驱动 / 用户输入驱动的，不在 RobotRepository.Snapshot 里，
     * 规划明确保留在 1s tick 里。同时触发 [RobotRepository.tick] 更新状态帧速率窗口。
     */
    fun onTick() {
        // 🔴 2026-11-17 真机实测回归修复：阶段 2 把会话委托给 Repository 时漏了这一行。
        // `uiTickCount`（本地刷新计数）、`heartbeatRunning`（心跳态）、A5 恢复提示清理
        // **只在 SessionHolder.tick() 里更新**；只调 repository.tick() 会让「本地刷新」
        // 永远停在 0 次、心跳态永远 false —— 文本门禁读不到，真机 UI 也静止。
        // 两者职责不同，不能互相替代：
        //   · RobotRepository.tick() = 状态帧速率窗口（实机帧）
        //   · SessionHolder.tick()   = App 自观测计数（非实机数据）
        SessionHolder.tick()
        robotRepository.tick()
        _uiState.update {
            it.copy(
                mode = SessionHolder.mode,
                sinkLabel = SessionHolder.sinkLabel,
                sentCount = SessionHolder.sentCount.get(),
                headSentCount = SessionHolder.headSentCount.get(),
                uiTickCount = SessionHolder.uiTickCount.get(),
                heartbeatRunning = SessionHolder.heartbeatRunning,
                lastInput = SessionHolder.lastInput,
            )
        }
    }

    /** 同步当前驱动参数进 UiState（设置页初始渲染时调用）。 */
    fun syncDriveParams() {
        _uiState.update {
            it.copy(
                mode = SessionHolder.mode,
                channelIndex = SessionHolder.channelIndex,
                headRadIndex = SessionHolder.headRadIndex,
                invertY = SessionHolder.invertY,
                maxVx = SessionHolder.maxVx,
                maxVyaw = SessionHolder.maxVyaw,
                driveDeadzone = SessionHolder.driveDeadzone,
                headDeadzone = SessionHolder.headDeadzone,
                autoRefreshHealth = SessionHolder.autoRefreshHealth,
            )
        }
    }
}
