package io.microduck.app.core

/**
 * 机器人「硬件部位」的**唯一命名真源**（纯 JVM，零 Android 依赖）。
 *
 * ── 为什么这张表必须来自一手源码，不能自己编 ──
 * `microduck-software/.upstream/ft1910/duck-ipc-proto/src/lib.rs:536-564`：
 *   `JOINT_NAMES: [&str; 15]` 与 `JOINT_IDS: [u8; 15]`，
 *   注释明写「**robot.health names a missing servo by its ID and a client has to say
 *   which joint it is**」。`BusHealth::missing: Vec<u8>` 携带的是**舵机 ID**，
 *   客户端要靠这张表把它翻译成关节名/身体部位。
 * 实机 `docs/active/microduck-主板到货-SSH只读实机验收与App适配-2026-11-14.md:79`
 * 的 `missing IDs [10,11,12,13,14,20,21,22,23,24,30,31,32,33,34]` 正是这 15 个 ID
 * 全缺 —— 所以「异常部位着色」可以直接落在真数据上，不需要等固件补丁。
 *
 * ── 状态语义（项目铁律）──
 * `UNKNOWN` **不等于** `OK`：字段缺失、Mock 未覆盖、协议未提供逐舵机读数时一律 UNKNOWN，
 * 且 UNKNOWN 不产生任何告警。只有拿到一手证据才允许判 OK/WARN/CRITICAL。
 */
enum class RobotPart(val label: String, val kind: PartKind) {
    // 15 个关节，顺序严格对齐 lib.rs JOINT_NAMES / JOINT_IDS（位置索引即 wire 索引）
    LEFT_HIP_YAW("左髋偏航", PartKind.JOINT),
    LEFT_HIP_ROLL("左髋滚转", PartKind.JOINT),
    LEFT_HIP_PITCH("左髋俯仰", PartKind.JOINT),
    LEFT_KNEE("左膝", PartKind.JOINT),
    LEFT_ANKLE("左踝", PartKind.JOINT),
    NECK_PITCH("颈俯仰", PartKind.JOINT),
    HEAD_PITCH("头俯仰", PartKind.JOINT),
    HEAD_YAW("头偏航", PartKind.JOINT),
    HEAD_ROLL("头滚转", PartKind.JOINT),
    MOUTH("喙", PartKind.JOINT),
    RIGHT_HIP_YAW("右髋偏航", PartKind.JOINT),
    RIGHT_HIP_ROLL("右髋滚转", PartKind.JOINT),
    RIGHT_HIP_PITCH("右髋俯仰", PartKind.JOINT),
    RIGHT_KNEE("右膝", PartKind.JOINT),
    RIGHT_ANKLE("右踝", PartKind.JOINT),

    // 系统部件：不在 15 关节表里，来自 HealthResult 的其它真字段
    TORSO("躯干", PartKind.SYSTEM),
    BATTERY("电池", PartKind.SYSTEM),
    CPU("主板 SoC", PartKind.SYSTEM),
    IMU("头部 IMU", PartKind.SYSTEM),
    BUS("舵机总线", PartKind.SYSTEM),
    LINK("通信链路", PartKind.SYSTEM),
    ;

    enum class PartKind { JOINT, SYSTEM }
}

/** 严重度。`UNKNOWN` 是「无证据」，不是「正常」。 */
enum class Severity { OK, WARN, CRITICAL, UNKNOWN }

object RobotParts {
    /** lib.rs:536-552，位置索引即 `joints[]`/`targets[]` 的 wire 索引，禁止重排。 */
    val JOINT_NAMES: List<String> = listOf(
        "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
        "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
        "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
    )

    /** lib.rs:560-564：左腿 20-24 / 颈头喙 30-34 / 右腿 10-14。 */
    val JOINT_IDS: List<Int> = listOf(
        20, 21, 22, 23, 24,
        30, 31, 32, 33, 34,
        10, 11, 12, 13, 14,
    )

    /** 与 [JOINT_NAMES] 一一对应的部位，靠构造而非手写映射，避免两张表漂移。 */
    val JOINT_PARTS: List<RobotPart> = RobotPart.entries
        .filter { it.kind == RobotPart.PartKind.JOINT }

    init {
        require(JOINT_NAMES.size == 15) { "JOINT_NAMES must be 15 (ft1910 NUM_JOINTS)" }
        require(JOINT_IDS.size == JOINT_NAMES.size) { "JOINT_IDS/JOINT_NAMES length mismatch" }
        require(JOINT_PARTS.size == JOINT_NAMES.size) { "JOINT_PARTS/JOINT_NAMES length mismatch" }
        require(JOINT_IDS.distinct().size == 15) { "JOINT_IDS must be unique" }
    }

    /** 舵机 ID → 部位。未知 ID 返回 null（不猜、不映射到默认部位）。 */
    fun partOfId(id: Int): RobotPart? {
        val i = JOINT_IDS.indexOf(id)
        return if (i >= 0) JOINT_PARTS[i] else null
    }

    /** `motors.hottest` 的关节名 → 部位。未知名字返回 null。 */
    fun partOfName(name: String?): RobotPart? {
        if (name == null) return null
        val i = JOINT_NAMES.indexOf(name.trim())
        return if (i >= 0) JOINT_PARTS[i] else null
    }

    fun idOf(part: RobotPart): Int? {
        val i = JOINT_PARTS.indexOf(part)
        return if (i >= 0) JOINT_IDS[i] else null
    }

    /** 多个判据落在同一部位时取最严重者；全 UNKNOWN 才是 UNKNOWN。 */
    fun merge(parts: Collection<Severity>): Severity = when {
        Severity.CRITICAL in parts -> Severity.CRITICAL
        Severity.WARN in parts -> Severity.WARN
        Severity.OK in parts -> Severity.OK
        else -> Severity.UNKNOWN
    }

    /**
     * 深底主题下的语义色（0xAARRGGBB，与 `app/src/main/res/values/styles.xml`
     * 的 md_ok/md_warn/md_bad/md_text_dim 同值；core 不依赖 Android，故这里显式给数值）。
     * 供 3D 视图标记异常部位；自检断言四色互不相同（改重复必红）。
     */
    fun severityArgb(s: Severity): Int = when (s) {
        Severity.OK -> 0xFF5FAE7A.toInt()
        Severity.WARN -> 0xFFD8A23E.toInt()
        Severity.CRITICAL -> 0xFFDD6A6A.toInt()
        Severity.UNKNOWN -> 0xFF868D97.toInt()
    }

    /** 无证据时的部位底色；所有部位都从这里起步，绝不默认绿。 */
    val ALL: List<RobotPart> = RobotPart.entries.toList()
}
