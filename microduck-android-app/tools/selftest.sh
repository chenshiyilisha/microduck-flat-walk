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

echo "=== 环境自检 ==="
"$JAVAC" -version 2>&1 | head -1
if [ -x "$K240" ]; then
  KC="$K240"
elif [ -x "$IDEA_KC" ]; then
  echo "WARN: 未找到 Kotlin 2.4.0 编译器，退回 IDEA 版（版本不符，证据降级！请重下 2.4.0）"
  KC="$IDEA_KC"
else
  echo "FAIL: 找不到 kotlinc。先跑: bash tools/fetch-kotlinc.sh"
  exit 2
fi
JAVA_HOME="$JDK17" PATH="$JDK17/bin:$PATH" "$KC" -version 2>&1 | head -1
[ -f "$GSON" ] || { echo "FAIL: 找不到 gson jar: $GSON"; exit 2; }

echo "=== 1) 编译 core + harness → build/selftest.jar ==="
mkdir -p build/fat
SRC=$(find core/src/main/kotlin core/src/test/kotlin -name '*.kt' | tr '\n' ' ')
JAVA_HOME="$JDK17" PATH="$JDK17/bin:$PATH" "$KC" \
  -jvm-target 17 -include-runtime -cp "$GSON" \
  $SRC -d build/selftest.jar 2>&1
rc=$?
echo "compile_rc=$rc"
[ $rc -ne 0 ] && exit $rc

echo "=== 2) 组装 fat 目录（selftest 类 + gson 类，绕开 classpath 分隔符）==="
rm -rf build/fat && mkdir -p build/fat
(cd build/fat && "$JAR" xf ../selftest.jar && "$JAR" xf "$GSON")
[ -f build/fat/com/google/gson/Gson.class ] || { echo "FAIL: fat 目录缺 gson"; exit 2; }
[ -f build/fat/io/microduck/app/core/CoreSelfTest.class ] || { echo "FAIL: fat 目录缺主类"; exit 2; }
echo "fat 目录就绪 ($(find build/fat -name '*.class' | wc -l) classes)"

echo "=== 3) 运行自检（负对照内建，任一失败 exit 1）==="
"$JAVAC" -Dfile.encoding=UTF-8 -cp "build/fat" io.microduck.app.core.CoreSelfTest
exit $?
