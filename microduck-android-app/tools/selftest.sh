#!/usr/bin/env bash
# core 会话层一键自检：真编译 + 真运行，带负对照。
# 锁定 Kotlin 2.4.0 + JDK17 + jvm-target 17 —— 不用 IDEA 自带的 1.9.0。
#
# 关键坑（已踩并解决，写在这里防复发）—— 机制已查一手，非试错猜测：
#  1) Git Bash 是 MSYS2，会把以 '/' 开头的参数**自动改写**成 Windows 路径：
#     /tmp/x → "C:/Program Files/Git/tmp/x"（git-for-windows discussion #3038 / MSYS2
#     POSIX-to-Windows path conversion）。Windows java.exe 拿到改写后的错路径 → 找不到类。
#     ✅ 产物一律输出到项目 build/，运行时用相对路径（不以 '/' 开头 ⇒ 不触发改写）。
#  2) classpath 分隔符：Oracle java man 页 "On Windows, semicolons (;) separate entities;
#     on other platforms a colon (:)"。Windows java.exe 要 ';'，但 bash 里写 ';' 要引号、
#     且冒号分隔的路径列表本身又会触发 MSYS 改写 → 两个坑叠加。
#     ✅ 把 gson + selftest 类解压进同一个 build/fat/ 目录，classpath **只给单个目录**，
#     既没有分隔符、也没有 POSIX 路径，两个坑一起绕开（这就是 fat 目录法的真正原理）。
#
# 用法：bash tools/selftest.sh
set -u

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE" || exit 2

JDK17="E:/软件工具/OpenJdk17"
K240="/tmp/kotlin240/kotlinc/bin/kotlinc"
IDEA_KC="D:/Program Files/JetBrains/IntelliJ IDEA 2023.2.3/plugins/Kotlin/kotlinc/bin/kotlinc"
GSON="C:/Users/hejih/.gradle/caches/modules-2/files-2.1/com.google.code.gson/gson/2.10.1/b3add478d4382b78ea20b1671390a858002feb6c/gson-2.10.1.jar"
JAR="$JDK17/bin/jar.exe"
JAVAC="$JDK17/bin/java.exe"

# 🔴 2026-11-14 修：/tmp/kotlin240 是上次下载的**空目录**（只剩 kotlinc/ 壳），
# 旧脚本会静默回退到 IDEA 的 1.9.0，而本项目源码用 K2 2.4.0 语法
# （expression body 里的 Elvis return / inline lambda continue），1.9.0 直接编译报错。
# 「WARN + 降级」在这里是假绿：根本跑不出 RESULT，却让人以为有证据。
# ⇒ 改用 Gradle 缓存里**已完整落盘**的 Kotlin 2.4.0 工具链直接跑 K2JVMCompiler：
#   kotlin-compiler-embeddable-2.4.0.jar 是 KGP 实际用的同一个编译器（60,351,320 B），
#   配上同版本 stdlib/script-runtime + reflect/coroutines/intellij-core/trove4j。
# 这是「先穷尽现成环境」，不是重装、不是手工降级；Gradle :core:compileKotlin 已独立证明
# 这套依赖图能编译本项目 main 源码。
KCACHE="C:/Users/hejih/.gradle/caches/modules-2/files-2.1"
build_k2_cp() {
  local out=""
  local f
  while IFS= read -r f; do out="$out;$(cygpath -w "$f")"; done < <(
      find "/c/Users/hejih/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin" \
           -path "*2.4.0*" -name "*.jar" 2>/dev/null)
  for d in "org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0" \
           "com.android.tools.external.com-intellij/intellij-core/31.9.1" \
           "org.jetbrains.kotlin/kotlin-reflect/2.1.0"; do
    f=$(find "/c/Users/hejih/.gradle/caches/modules-2/files-2.1/$d" -name "*.jar" 2>/dev/null | head -1)
    [ -n "$f" ] && out="$out;$(cygpath -w "$f")"
  done
  f=$(find /c/Users/hejih/.gradle/caches -name "instrumented-trove4j*.jar" 2>/dev/null | head -1)
  [ -n "$f" ] && out="$out;$(cygpath -w "$f")"
  printf '%s' "${out#;}"
}
K2_CP="$(build_k2_cp)"
K2_EMBEDDABLE="$(find /c/Users/hejih/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin \
                     -path '*2.4.0*' -name 'kotlin-compiler-embeddable-2.4.0.jar' 2>/dev/null | head -1)"

echo "=== 环境自检 ==="
"$JAVAC" -version 2>&1 | head -1
if [ -x "$K240" ]; then
  KC="$K240"; KC_MODE="cli"
elif [ -n "$K2_EMBEDDABLE" ] && [ -n "$K2_CP" ]; then
  KC_MODE="gradle-cache-2.4.0"
  "$JAVAC" -cp "$K2_CP" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -version 2>&1 | head -1
else
  echo "FAIL: 找不到 Kotlin 2.4.0 编译器，且 Gradle 缓存里也没有完整 2.4.0 工具链。"
  echo "      🔴 绝不回退 IDEA 1.9.0：它编译不了本项目，会给『好像跑过』的假证据。"
  echo "      先跑: bash tools/fetch-kotlinc.sh 或 ./gradlew :core:compileKotlin"
  exit 2
fi
echo "kotlin compiler mode = $KC_MODE"
[ -f "$GSON" ] || { echo "FAIL: 找不到 gson jar: $GSON"; exit 2; }

echo "=== 1) 编译 vendored Java crypto primitives → build/classes ==="
# 🔴 2026-11-14 修：两种模式统一编译成 class 目录，绝不用 -include-runtime。
# embeddable CLI 没有 kotlin-home，-include-runtime 会抛
# "Couldn't find kotlin-stdlib at <no_path>\lib\kotlin-stdlib.jar"（源码已编译完才炸），
# 看起来像编译失败其实是打包失败。stdlib 改由第 2 步 fat 目录并入，语义等价且更可控。
rm -rf build/classes && mkdir -p build/classes build/fat
JAVA_SRC=$(find core/src/main/java -name '*.java' | tr '\n' ' ')
if [ -n "$JAVA_SRC" ]; then
  JAVA_HOME="$JDK17" PATH="$JDK17/bin:$PATH" "$JDK17/bin/javac.exe" \
    -d build/classes $JAVA_SRC 2>&1
  rc=$?
  echo "javac_rc=$rc"
  [ $rc -ne 0 ] && exit $rc
fi

echo "=== 2) 编译 core + harness → build/classes ==="
SRC=$(find core/src/main/kotlin core/src/test/kotlin -name '*.kt' | tr '\n' ' ')
if [ "$KC_MODE" = "cli" ]; then
  JAVA_HOME="$JDK17" PATH="$JDK17/bin:$PATH" "$KC" \
    -jvm-target 17 -cp "$GSON;$(cygpath -w build/classes)" \
    $SRC -d build/classes 2>&1
else
  # 同一套 Kotlin 2.4.0 编译器，走 embeddable 的 CLI 入口。
  # 🔴 不能加 -no-stdlib：那会连**编译期** built-in 声明一起去掉（kotlin.Any/Int 全报
  # 「cannot access built-in declaration」）。stdlib 必须显式进编译器的 -cp。
  # -no-reflect 只抑制「kotlin-home 里找不到 reflect」的无害告警（reflect 已在 K2_CP）。
  K2_STDLIB="$(find /c/Users/hejih/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin \
                    -path '*2.4.0*' -name 'kotlin-stdlib-2.4.0.jar' 2>/dev/null | head -1)"
  [ -n "$K2_STDLIB" ] || { echo "FAIL: 缺 kotlin-stdlib-2.4.0.jar"; exit 2; }
  KC_CP="$GSON;$(cygpath -w "$K2_STDLIB");$(cygpath -w build/classes)"
  JAVA_HOME="$JDK17" PATH="$JDK17/bin:$PATH" "$JAVAC" \
    -cp "$K2_CP" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
    -jvm-target 17 -no-reflect -cp "$KC_CP" \
    $SRC -d build/classes 2>&1
fi
rc=$?
echo "compile_rc=$rc"
[ $rc -ne 0 ] && exit $rc
K2_STDLIB="${K2_STDLIB:-$(find /c/Users/hejih/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin \
                    -path '*2.4.0*' -name 'kotlin-stdlib-2.4.0.jar' 2>/dev/null | head -1)}"

echo "=== 3) 组装 fat 目录（selftest 类 + gson + stdlib + duck_mesh.bin，绕开 classpath 分隔符）==="
rm -rf build/fat && mkdir -p build/fat
cp -r build/classes/. build/fat/
(cd build/fat && "$JAR" xf "$GSON")
[ -n "$K2_STDLIB" ] && (cd build/fat && "$JAR" xf "$(cygpath -w "$K2_STDLIB")")
# 🔴 duck_mesh.bin 是 core classpath 资源，裸 kotlinc 不会自动带上 resources，
# 必须手动拷进 fat 根目录，否则 DuckMesh.load() 在自检里找不到资源。
if [ -f core/src/main/resources/duck_mesh.bin ]; then
  cp core/src/main/resources/duck_mesh.bin build/fat/duck_mesh.bin
else
  echo "WARN: core/src/main/resources/duck_mesh.bin 不存在 —— DuckMesh 自检会因缺资源失败"
fi
[ -f build/fat/com/google/gson/Gson.class ] || { echo "FAIL: fat 目录缺 gson"; exit 2; }
[ -f build/fat/io/microduck/app/core/CoreSelfTest.class ] || { echo "FAIL: fat 目录缺主类"; exit 2; }
[ -f build/fat/kotlin/Unit.class ] || { echo "FAIL: fat 目录缺 kotlin stdlib"; exit 2; }
echo "fat 目录就绪 ($(find build/fat -name '*.class' | wc -l) classes)"

echo "=== 4) 运行自检（负对照内建，任一失败 exit 1）==="
"$JAVAC" -Dfile.encoding=UTF-8 -cp "build/fat" io.microduck.app.core.CoreSelfTest
exit $?
