# proguard-rules.pro —— MicroDuck 安卓 App 发布构建（release 变体）专用
#
# 依据（一手）：
#  · Google Android《Keep rule use cases and examples》/《Use R8 in full mode》
#    https://developer.android.com/topic/performance/app-optimization/keep-rule-examples
#    https://developer.android.com/topic/performance/app-optimization/full-mode
#  · Gson 官方 consumer rules（gson 2.10.1 自带，但不完整，官方明确要求用户按自身类补充）
#    https://android.googlesource.com/platform/external/gson/+/refs/heads/upstream-main/gson/src/main/resources/META-INF/proguard/gson.pro
#
# 本项目 Gson 使用现状（已逐处核对源码）：
#  · Wire.kt / RobotSession.kt / MockTransport.kt 的 gson.toJson 参数均为
#    Map<String, Any?> 或 JsonObject（Map 的 key 是运行时字符串，不受字段混淆影响）。
#  · UpdatePolicy.kt 用 JsonParser.parseString(...).asJsonObject + 手动 getAsString/getAsInt，
#    不经 Gson 的 typed 反序列化。
#  ⇒ 没有业务数据类的字段名经 Gson 反射，无需给业务类加包范围 keep（官方不推荐长期维持）。

# ---- Gson 反射所需的属性（full mode 仅对命中 keep 规则的类保留这些属性）----
-keepattributes Signature
-keepattributes RuntimeVisibleAnnotations,AnnotationDefault

# ---- TypeToken 泛型信息（防御性：当前未用 TypeToken，保留以防后续引入）----
-keep,allowobfuscation,allowshrinking,allowoptimization class com.google.gson.reflect.TypeToken { *; }
-keep,allowobfuscation,allowshrinking,allowoptimization class * extends com.google.gson.reflect.TypeToken

# ---- Kotlin 元数据（R8 full mode 默认 strip @kotlin.Metadata；若用 kotlin.reflect 会崩）----
# 项目当前未用 kotlin.reflect，防御性保留，避免后续引入反射时静默崩溃。
-keep class kotlin.Metadata { *; }

# ---- 若未来给数据类加 @SerializedName 或改用 typed 反序列化，按官方条件规则补充 ----
# -if class * { @com.google.gson.annotations.SerializedName <fields>; }
# -keep,allowobfuscation class { @com.google.gson.annotations.SerializedName <fields>; (<init>); }
