import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

/**
 * 固定签名：所有对外发布的 APK 必须用同一证书（Google《为应用签名》——
 * 不同证书签名的新版本无法覆盖安装）。密钥与密码只从本机 local.properties 读取，
 * 该文件已被 .gitignore 忽略，绝不入库；缺配置时回退 AGP 默认 debug 证书，
 * 并由 tools/publish_release.py 的证书指纹门禁拒绝发布（不静默放行）。
 */
val localProperties = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.isFile) f.inputStream().use { load(it) }
}
val fixedKeystore = localProperties.getProperty("microduck.keystore")?.let { file(it) }
val fixedSigningReady = fixedKeystore?.isFile == true &&
    listOf("microduck.storePassword", "microduck.keyAlias", "microduck.keyPassword")
        .all { !localProperties.getProperty(it).isNullOrBlank() }
if (!fixedSigningReady) {
    println("WARN: 未配置 microduck.* 固定签名，本包用 AGP 默认 debug 证书；publish_release.py 会拒发")
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
        versionCode = 2
        versionName = "0.2.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // 两条构建类型共用同一个固定证书：debug 包就是可发布的包，避免「测试机装 debug、
    // 发布用 release」两套证书导致覆盖安装失败。缺配置时不创建该 signingConfig。
    val fixedConfig = if (fixedSigningReady) {
        signingConfigs.create("fixed") {
            storeFile = fixedKeystore
            storePassword = localProperties.getProperty("microduck.storePassword")
            keyAlias = localProperties.getProperty("microduck.keyAlias")
            keyPassword = localProperties.getProperty("microduck.keyPassword")
            enableV1Signing = true
            enableV2Signing = true
        }
    } else null

    buildTypes {
        getByName("debug") { if (fixedConfig != null) signingConfig = fixedConfig }
        getByName("release") { if (fixedConfig != null) signingConfig = fixedConfig }
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
