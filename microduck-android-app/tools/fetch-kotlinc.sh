#!/usr/bin/env bash
# 下载 Kotlin 2.4.0 独立编译器到 /tmp/kotlin240/，供 selftest.sh 用真 2.4.0 编译 core。
# 为什么不用 IDEA/Android Studio 自带的 kotlinc：版本可能旧（IDEA 2023.2.3 是 1.9.0），
# 而 Kotlin 2.4.0 起 K2 是唯一引擎、不能回滚 K1 —— 旧编译器编译通过不算 2.4.0 的证据。
# 已下载过会跳过。用法：bash tools/fetch-kotlinc.sh
set -u
K240="/tmp/kotlin240/kotlinc/bin/kotlinc"
if [ -x "$K240" ]; then
  echo "已存在: $("$K240" -version 2>&1 | head -1)"
  exit 0
fi
echo "=== 下载 Kotlin 2.4.0 编译器 (官方 GitHub release, ~87MB) ==="
mkdir -p /tmp/kotlin240 && cd /tmp/kotlin240
curl -sL --retry 3 -o k240.zip \
  "https://github.com/JetBrains/kotlin/releases/download/v2.4.0/kotlin-compiler-2.4.0.zip" \
  || { echo "下载失败。备用：从 Kotlin 官网或镜像下 kotlin-compiler-2.4.0.zip 放到 /tmp/kotlin240/"; exit 2; }
unzip -q -o k240.zip && echo "完成: $(./kotlinc/bin/kotlinc -version 2>&1 | head -1)"
