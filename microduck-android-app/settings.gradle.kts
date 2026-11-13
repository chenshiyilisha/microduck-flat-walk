pluginManagement {
    repositories {
        google {
            content {
                // 官方 Android 模板的三组过滤（Android Studio 生成）。缺任一组都会让 AGP 的
                // 传递依赖解析失败：androidx.databinding.*、com.google.testing.platform:core-proto
                // 只在 Google Maven 有，被挡就会去 mavenCentral 找 → could not find。
                // 2026-11-12 实测踩坑：原先漏了 androidx.* 且把 com.google.* 写窄成 .developers.*。
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // 🔑 国内镜像优先（2026-11-12 真构建定位根因后加）：
        //    Kotlin 2.4.0 编译器主 jar kotlin-compiler-embeddable-2.4.0.jar = 60,351,320 B。
        //    之前 mavenCentral() 传输中断，只落了 .pom 没落 .jar → Gradle 认为 module 已解析，
        //    Kotlin daemon 启动即卡在重试这个大 jar，表现为 :core:compileKotlin 长时间无输出、
        //    硬超时杀 daemon 后报 "daemon disappeared unexpectedly"（无 OOM、无 hs_err）。
        //    四源 HEAD 实测均 200 且 content-length 完全一致（官方 Maven Central + 阿里云 +
        //    华为云 + 腾讯云），故用国内镜像下大 jar 更稳，mavenCentral/google 保留兜底。
        //    ⚠️ 别拿本地 /tmp/kotlin240/lib/kotlin-compiler.jar 顶替：那是非 embeddable 版
        //       （依赖未 relocation），Maven 坐标与 KGP 预期不符。
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        mavenCentral()
    }
}

rootProject.name = "microduck-android-app"
include(":core")      // 纯 Kotlin/JVM：协议 + 会话层，可脱离 Android 真编译真测
include(":app")       // Android UI（当前骨架，后续补）
