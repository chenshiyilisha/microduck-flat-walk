#!/usr/bin/env bash
# 离线目视核验（诊断用，不是门禁）：用**真机同一份 Kotlin 管线**（core HoloRenderer）
# 渲染 PNG，证明移植与参考实现一致、且真机路径本身能出图。
#
# 前置：build/fat 由 tools/selftest.sh 生成（含 core class + stdlib + duck_mesh.bin）。
# 用法：bash tools/render_holo_preview.sh
set -euo pipefail

cd "$(dirname "$0")/.."
JDK17="${JDK17:-E:/软件工具/OpenJdk17}"

# 编译器 classpath 与 tools/selftest.sh 的 build_k2_cp 同源（同一套 2.4.0 jar 集合）。
# 不 source selftest.sh 是为了不触发它的全量编译/自检（这里只需要已生成的 build/fat）。
build_k2_cp() {
  local out="" f
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
if [ -z "$K2_CP" ]; then
  echo "FAIL: 找不到 Kotlin 2.4.0 compiler jars（见 tools/selftest.sh 的 build_k2_cp）"
  exit 2
fi

if [ ! -f build/fat/io/microduck/app/core/HoloRenderer.class ]; then
  echo "FAIL: build/fat 缺 HoloRenderer，先跑 bash tools/selftest.sh"
  exit 2
fi

echo "=== 编译 HoloPreview.kt（对 build/fat 里的 core 类）==="
# 注意：是 java.exe 跑 K2JVMCompiler 主类，不是 javac（javac 不认 -jvm-target）。
"$JDK17/bin/java.exe" -cp "$K2_CP" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
  -jvm-target 17 -no-reflect -cp build/fat tools/HoloPreview.kt -d build/fat
echo "compile ok"

echo "=== 渲染（normal / alert）==="
"$JDK17/bin/java.exe" -Djava.awt.headless=true -cp build/fat HoloPreview
"$JDK17/bin/java.exe" -Djava.awt.headless=true -cp build/fat HoloPreview alert
ls -la build/holo_kotlin_*.png
