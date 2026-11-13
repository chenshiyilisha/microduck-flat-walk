package io.microduck.app.core

/**
 * NDJSON JSON-RPC 2.0 wire 模型 —— 严格对齐 fanhao 固件 `duck-ipc-proto/src/lib.rs`（API_VERSION=40）。
 *
 * 一手依据（本地 /tmp/fanhao/.../firmware/duck-ipc-proto/src/lib.rs）：
 *  - lib.rs:10  "Wire format: JSON-RPC 2.0, one object per line (NDJSON), over a unix socket."
 *  - lib.rs:437 `pub const API_VERSION: u32 = 40;`
 *  - lib.rs:44   v4 起 BLE 客户端必须先过 `system.authenticate` 才被服务
 *  - lib.rs:58   没有 daemon 因 API_VERSION 不同拒答；版本 skew 靠 METHOD_NOT_FOUND 命名方法降级
 *  - lib.rs:922+ 错误码：METHOD_NOT_FOUND=-32601、PERMISSION_DENIED=14、INVALID_PARAMS=-32602
 *  - `#[serde(deny_unknown_fields)]` 遍布所有 params ⇒ 我们发出的 JSON **不能多键**，否则 INVALID_PARAMS
 *
 * 这一层是纯数据 + 常量，不依赖 Android，能在 JVM 上真编译真测。
 */
object Wire {
    const val API_VERSION = 40
    const val JSONRPC = "2.0"

    // BLE GATT UUID —— 一手 fanhao duck-ble/src/gatt.rs:35/44。冻结契约，App 发出后不可改。
    // 单一 characteristic 双向：client 写 RPC_UUID、也订阅 RPC_UUID 收响应/通知。
    const val BLE_SERVICE_UUID = "6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019"
    const val BLE_RPC_UUID = "6f5d2a11-3b47-4c8e-9a1f-2d7e8c4b6019"
    /** 工厂 PIN，公开在仓库（route.rs:638 / mobile-app.md:229）；App 静默发送，无 PIN 屏幕。 */
    const val BLE_DEFAULT_PIN = "000000"
}

/** 方法名常量。字符串照抄 `duck-ipc-proto` 的 `pub mod method`，别自创。 */
object Method {
    const val HELLO = "hello"
    const val SYSTEM_AUTHENTICATE = "system.authenticate"
    const val SYSTEM_INFO = "system.info"
    const val ROBOT_HEALTH = "robot.health"
    const val ROBOT_STATE = "robot.state"
    const val ROBOT_SUBSCRIBE = "robot.subscribe"
    const val ROBOT_INIT = "robot.init"
    const val ROBOT_ENABLE = "robot.enable"
    const val ROBOT_DO = "robot.do"
    const val ROBOT_MOVE = "robot.move"
    /** 头部关节目标，弧度。连续意图，发 notification。一手：fanhao lib.rs:610。 */
    const val ROBOT_HEAD = "robot.head"
    /** 凝视点（trunk 坐标系，米），离散请求，daemon 跑 IK。一手：fanhao lib.rs:613。本版 UI 不用。 */
    const val ROBOT_LOOK = "robot.look"
    const val ROBOT_POLICIES = "robot.policies"
    const val ROBOT_LOAD_POLICY = "robot.loadPolicy"
    const val ROBOT_MODEL = "robot.model"
    /** 是否有遥在场会话（A4 控制者归属显示）。一手：fanhao 副本 lib.rs:589
     *  `pub const ROBOT_SESSION_ACTIVE: &str = "robot.remoteSessionActive";`
     *  路由 `Call::RobotRemoteSessionActive -> (Robot, Prompt)`（lib.rs:1367）。只读。 */
    const val ROBOT_REMOTE_SESSION_ACTIVE = "robot.remoteSessionActive"
    /** 该固件实现的 model API 版本；仅供只读展示，不用于硬拒（A9 维持不做）。
     *  一手：lib.rs:587 `ROBOT_MODEL_API`。 */
    const val ROBOT_MODEL_API = "robot.modelApi"
    const val NET_STATUS = "net.status"
    const val NET_SCAN = "net.scan"
    const val NET_CONNECT = "net.connect"
    const val UPDATE_CHECK = "update.check"
    const val UPDATE_STATUS = "update.status"
    const val SYSTEM_LOGS = "system.logs"
}

/** JSON-RPC 错误码（lib.rs `pub mod code`）。会话层按这三类做不同处理。 */
object RpcCode {
    const val METHOD_NOT_FOUND = -32601     // 版本 skew：该方法此固件不支持 → 能力降级、UI 灰化
    const val INVALID_PARAMS = -32602       // 契约 skew：我们多发/少发/类型错的字段 → 报 bug
    const val PERMISSION_DENIED = 14        // BLE 路由拒绝（低频白名单外，如 robot.move）→ 走别的传输
}

/**
 * 一条出站 JSON-RPC 请求。序列化成单行 NDJSON（换行即帧界）。
 * [id] 用于把响应对回 pending 请求；通知类（订阅后服务器推的 robot.state）没有 id。
 */
data class RpcRequest(
    val id: Long,
    val method: String,
    val params: Map<String, Any?> = emptyMap(),
) {
    /** deny_unknown_fields：params 为空时不写该键（hook/subscribe 期望无 params 或 {}）。 */
    fun toJsonLine(gson: com.google.gson.Gson): String = buildString {
        append("{\"jsonrpc\":\"").append(Wire.JSONRPC).append("\"")
        append(",\"id\":").append(id)
        append(",\"method\":\"").append(method).append("\"")
        if (params.isNotEmpty()) {
            append(",\"params\":").append(gson.toJson(params))
        }
        append("}")
    }
}

/**
 * 一条出站 JSON-RPC **notification**：与 [RpcRequest] 的唯一区别是**没有 id**。
 *
 * 一手依据：B 代 `robotd/src/main.rs:3483-3489`
 *   "Notifications get no reply, per the spec. Continuous intents arrive this way —
 *    at 50 Hz a response per message would be pure overhead, and there is nothing
 *    useful to say about a velocity that is superseded 20 ms later."
 *   无 id 时服务端直接 `apply_intent(...)` 并 `continue`（不写任何响应行）。
 * `robot.move` 契约注释（lib.rs:307 / fanhao :608）明写 "Continuous; send as a notification"。
 *
 * 🔴 少了 id 就是 notification，多了 id 就变成 request —— 二者语义不同，别用 RpcRequest 凑。
 */
data class RpcNotification(
    val method: String,
    val params: Map<String, Any?> = emptyMap(),
) {
    fun toJsonLine(gson: com.google.gson.Gson): String = buildString {
        append("{\"jsonrpc\":\"").append(Wire.JSONRPC).append("\"")
        append(",\"method\":\"").append(method).append("\"")
        if (params.isNotEmpty()) {
            append(",\"params\":").append(gson.toJson(params))
        }
        append("}")
    }
}

/** JSON-RPC 错误对象。会话层按 code 分类处理（14 / -32601 / -32602）。 */
data class RpcError(
    val code: Int,
    val message: String,
)

// 说明：入站响应/通知刻意用 Gson 的 JsonObject + null-safe 取值（见 RobotSession 的
// str/bool/int 辅助），而非声明一堆 typed data class。原因：响应字段多为可选且各 daemon
// 版本不一（lib.rs 明说版本 skew 靠 METHOD_NOT_FOUND 降级），typed class 的反序列化适配器
// 会把「缺字段」变成异常，反而不如 JsonObject 稳。曾声明 HelloResult/AuthResult/RpcMessage
// 三个未使用的 data class，已删，避免「看着像协议实现其实是死代码」误导。
