plugins {
    id("org.jetbrains.kotlin.jvm")
}

// core 是纯 Kotlin/JVM 模块：协议模型 + 会话层，不依赖任何 Android API。
// 因此它能脱离 Gradle/模拟器，用 kotlinc 2.4.0 + JDK17 直接真编译真测（见 tools/selftest.sh）。
kotlin {
    jvmToolchain(17)
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        // 2.4.0 起 K2 是唯一前端，不能回滚 K1 / -language-version=1.9
    }
}

dependencies {
    implementation("com.google.code.gson:gson:2.10.1")
    testImplementation(kotlin("test"))   // kotlin-test，供 Gradle 跑 JUnit 风格测试
}

tasks.test {
    useJUnitPlatform()
}
