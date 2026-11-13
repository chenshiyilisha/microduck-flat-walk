// 顶层构建脚本。版本集中声明在这里，子模块 apply 不写版本号。
//
// 🔑 Kotlin 版本 = 2.4.0（用户 2026-11-12 指定；官方 2026-07-14 发布稳定版，K2 唯一引擎）。
//    不用 IDEA 2023.2.3 自带的 1.9.0 —— 那是本机现成编译器，仅用于早期 smoke；
//    2.4.0 起已不能回滚 K1 / -language-version=1.9，故交付基线必须真用 2.4.0 编译。
//
// 🔑 版本组合已查全三条交叉约束（2026-11-12 一手核，别只查一条就拍）：
//    ① KGP 2.4.0–2.4.10 ⇒ Gradle 7.6.3–9.5.0、AGP 8.5.2–9.1.0
//       (kotlinlang.org/docs/gradle-configure-project.html 官方兼容表)
//    ② AGP 8.9.x ⇒ Gradle 最低/默认 8.11.1、JDK 17、最高 compileSdk/API 35、Build Tools 35.0.0
//       (developer.android.com/build/releases/agp-8-9-0-release-notes 官方发布说明)
//    ③ Gradle 8.11.1 运行需 JDK 17–(docs.gradle.org compatibility.html)
//    交集 ⇒ Gradle 8.11.1(wrapper) + AGP 8.9.1 + Kotlin 2.4.0 + JDK17 + compileSdk 35。
//    ⚠️ 曾把 Gradle 写成 8.9（只查了①没查②）→ Gradle 构建报「AGP 要求最低 8.11.1」失败，真构建抓出。
//       改版本前必须三条一起回查。
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
    id("org.jetbrains.kotlin.jvm") version "2.4.0" apply false
}
