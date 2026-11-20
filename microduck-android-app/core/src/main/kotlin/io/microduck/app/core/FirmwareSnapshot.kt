package io.microduck.app.core

/**
 * 固件 OTA 的不可变快照（数据层 → UI）。缺数据一律 null/空，绝不伪造版本或进度（铁律）。
 *
 * 真机边界：本快照承载的是**从固件 RPC 读到的真实响应**或 Mock 夹具；
 * 即使字段齐全也不代表真机升级落地（live_hardware_accessed / ship_verdict 不受影响）。
 */
data class FirmwareSnapshot(
    /** update.check 三态；null=尚未检查。 */
    val check: FirmwareUpdate.CheckState? = null,
    /** update.status 各组件状态；空=未读。 */
    val components: List<FirmwareUpdate.ComponentStatus> = emptyList(),
    /** update.listInstalled 已装发布；空=未读。 */
    val installed: List<FirmwareUpdate.Installed> = emptyList(),
    /** update.log 最近日志；空=未读。 */
    val logs: List<FirmwareUpdate.LogEntry> = emptyList(),
    /** 最近一次进度通知；null=当前无进行中的更新。 */
    val progress: FirmwareUpdate.Progress? = null,
    /** 写操作（apply/rollback/select）进行中：按钮禁用，防重复提交。 */
    val busy: Boolean = false,
    /** 只读检查进行中。 */
    val checking: Boolean = false,
    /** 写操作结果文本（成功/失败/回滚），null=无。 */
    val resultText: String? = null,
    /** 操作是否成功（驱动 UI 颜色）；null=无结果。 */
    val resultOk: Boolean? = null,
    /** 最近错误的可读文案；null=无。 */
    val errorText: String? = null,
) {
    val isEmpty: Boolean get() = check == null && components.isEmpty() && installed.isEmpty() &&
        logs.isEmpty() && progress == null && resultText == null && errorText == null

    /** 聚焦组件（daemon）的当前已装版本；null=未读到。 */
    fun installedVersion(component: String = FirmwareUpdate.COMPONENT_DAEMON): String? =
        components.firstOrNull { it.component == component }?.installed
}
