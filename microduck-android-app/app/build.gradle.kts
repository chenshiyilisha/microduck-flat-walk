plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Kotlin 2.4.0：kotlinOptions DSL 已废弃（jvmTarget: String 直接报 error，非 warning），
// 必须用顶层 compilerOptions DSL。K2 + Kotlin Gradle Plugin 2.4 的正确写法。
kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

android {
    namespace = "io.microduck.app"
    // 本机装了 android-35 / android-36.1（见 C:/Users/hejih/AppData/Local/Android/Sdk/platforms）
    compileSdk = 35

    defaultConfig {
        applicationId = "io.microduck.app"
        minSdk = 26        // BLE 需 Android 8+（BluetoothGatt 稳定）
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-p0-skeleton"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(project(":core"))
    implementation("com.google.code.gson:gson:2.10.1")
    // P1+ 美化：Material Components（Views 体系），不用 Compose 重写整个 UI。
    // 用 MaterialCardView / MaterialButton，Activity 改 AppCompatActivity + M3 深色主题。
    implementation("com.google.android.material:material:1.12.0")
    // 显式声明而非依赖 material 的传递：MainActivity 直接用 AppCompatActivity /
    // ViewCompat / WindowInsetsCompat，传递依赖版本由 material 的 POM 决定会随升级漂移。
    implementation("androidx.appcompat:appcompat:1.6.1")
    // ViewCompat / WindowInsetsCompat 由 material + appcompat 传递依赖提供（Maven POM
    // compile scope ⇒ 对 compileClasspath 可见）。⚠️ 别显式写 androidx.core:core:1.13.1：
    // 新坐标会强制 Gradle 去 dl.google.com 校验元数据，国内超时导致整包构建失败；
    // 而缓存里虽已有该版本产物，Gradle 仍会先做仓库 HEAD 检查。
}
