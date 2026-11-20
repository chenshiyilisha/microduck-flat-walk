package io.microduck.app.core

import com.google.gson.JsonObject

/**
 * `tof.frame` 通知帧的安全解析 —— 一手字段来自 ft1910
 * `duck-ipc-proto/src/lib.rs:4838-4865`（`TofFrame`）与 `tof/src/lib.rs:74-119`（`Frame::zone`）。
 *
 * 🔴 **status 决定一格距离的含义，不能只看 distance_mm**（本文件存在的首要理由）：
 *  - ST 原始 status 字节是三态：`5/9` = 有效量程；`255` = 看了但没目标（空空间，是信息）；
 *    其他 = 测量失败（carries raw code，对建图有意义）。把后两者折成「距离 0」会丢失
 *    「空空间」与「测不到」的相反语义（tof/src/lib.rs:70-72 原文）。
 *  - 即使 status 有效，**distance ≤ 0 也不是量程**（失败收敛偶发负值，:97-102）。
 *  - 缺字段（数组短/越界）按 NoTarget，绝不 panic（:158-170 的 ragged 帧测试）。
 *  - 单位是**毫米**，展示时转米；t_ns/at_us 是 tofd 单调时钟，不是墙钟。
 *
 * 真机可达性：`tof.stream` 被 `btd` 明确拒绝（`btd/src/route.rs:494`），只能走
 * `mediad` 的 WebRTC datachannel（`mediad/src/route.rs:213`）。本解析层对传输无关，
 * 但 UI 必须如实标注「Mock 非实机读数」或「未读到」，不得把 Mock 帧当实机。
 */
data class TofSnapshot(
    val seq: Long?,
    val atUs: Long?,
    val tNs: Long?,
    val rows: Int,
    val cols: Int,
    /** row-major，长度 = rows*cols；每格三态之一，无「假测量」。 */
    val zones: List<TofZone>,
) {
    /** 含有效量程的格数（对应 Rust `valid_count()`，tof/src/lib.rs:115-119）。 */
    val validCount: Int get() = zones.count { it is TofZone.Range }

    fun hasFrame(): Boolean = rows > 0 && cols > 0 && zones.isNotEmpty()

    companion object {
        const val ROWS = 8
        const val COLS = 8
        const val ZONES = ROWS * COLS
        /** ST status：有效量程（valid / valid-large-pulse）。tof/src/lib.rs:87 */
        val STATUS_VALID = setOf(5, 9)
        /** ST status：看了没目标（空空间）。tof/src/lib.rs:89 */
        const val STATUS_NO_TARGET = 255

        /**
         * 一格的解释 —— 逐字对齐 Rust `Frame::zone`（tof/src/lib.rs:93-108）。
         * [status] null = 该格 status 缺失；[distanceMm] null = 距离缺失。
         */
        fun zone(status: Int?, distanceMm: Int?): TofZone {
            val s = status ?: return TofZone.NoTarget
            if (s in STATUS_VALID) {
                val d = distanceMm ?: return TofZone.Unusable(s)
                if (d > 0) return TofZone.Range(d / 1000.0)
                return TofZone.Unusable(s) // 负/零距离：失败收敛，不是量程
            }
            if (s == STATUS_NO_TARGET) return TofZone.NoTarget
            return TofZone.Unusable(s)
        }

        /** 安全解析一条 `tof.frame` 通知的 params；整帧非法返回 null（UI 显示「未读到」）。 */
        fun from(o: JsonObject): TofSnapshot? = try {
            val d = intArray(o, "distance_mm")
            val s = intArray(o, "status")
            val rows = num(o, "rows")?.toInt() ?: ROWS
            val cols = num(o, "cols")?.toInt() ?: COLS
            val n = (rows * cols).coerceAtMost(ZONES * 4) // 防恶意超大 rows*cols
            if (rows <= 0 || cols <= 0 || d == null || s == null) return null
            TofSnapshot(
                seq = lng(o, "seq"),
                atUs = lng(o, "at_us"),
                tNs = lng(o, "t_ns"),
                rows = rows,
                cols = cols,
                zones = (0 until n).map { i -> zone(s.getOrNull(i), d.getOrNull(i)) },
            )
        } catch (_: Exception) {
            null
        }

        private fun primitive(o: JsonObject?, key: String) = try {
            o?.get(key)?.takeIf { it.isJsonPrimitive && !it.isJsonNull }
        } catch (_: Exception) { null }

        private fun num(o: JsonObject?, key: String): Double? = try {
            primitive(o, key)?.asDouble
        } catch (_: Exception) { null }

        private fun lng(o: JsonObject?, key: String): Long? = try {
            primitive(o, key)?.asLong
        } catch (_: Exception) { null }

        private fun intArray(o: JsonObject?, key: String): List<Int>? = try {
            o?.getAsJsonArray(key)?.takeIf { !it.isJsonNull }?.map { e ->
                e.takeIf { it.isJsonPrimitive }?.asInt ?: Int.MIN_VALUE
            }
        } catch (_: Exception) { null }
    }
}

/** 一格 ToF 的三态（对齐 Rust `enum Zone`，tof/src/lib.rs:74-83）。 */
sealed class TofZone {
    /** 有效量程，单位米。status 5/9 且 distance_mm>0。 */
    data class Range(val meters: Double) : TofZone()
    /** status 255：传感器看了，范围内没目标（空空间，是有效信息）。 */
    object NoTarget : TofZone()
    /** 其余 status：测量失败，携带原始码（不解释成距离）。也用于有效 status + 非正距离。 */
    data class Unusable(val code: Int) : TofZone()
}
