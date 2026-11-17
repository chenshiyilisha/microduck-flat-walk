#!/usr/bin/env bash
# 离线渲染鸭子真实网格 PNG —— 手机拔线期间也能目视核验「模型像不像 / 状态着色对不对」。
#
# 为什么需要：真机 device_ui_check.py 59/59 只读 UI 文本节点，全绿也照不出
# 「散落碎片 / 躺倒 / 整机刷绿 / 状态色没落在目标部件」。本脚本调用与真机**同一份**
# core DuckMesh.project()（含 severityOf 着色重载）把 0/30/60/90 四帧画成 PNG，
# 是最短的纯视觉观测面。
# ⚠️ 只证明 core 几何 + 状态着色正确，不证明 Android assets 加载成功，不替代真机截图。
#
# 用法： bash tools/render_mesh_preview.sh [tag]
# 输出三组（各 4 帧）：
#   build/mesh_preview_<tag>_base_{0,30,60,90}.png    官方基色基准
#   build/mesh_preview_<tag>_unknown_{...}.png        全 UNKNOWN（须与 base 视觉一致）
#   build/mesh_preview_<tag>_alert_{...}.png          模拟 WARN/CRITICAL 部件着色
set -u

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE" || exit 2

JDK17="E:/软件工具/OpenJdk17"
MESH="app/src/main/assets/duck_mesh.bin"
TAG="${1:-preview}"

if [ ! -f "$MESH" ]; then
  echo "PRECONDITION_FAIL: $MESH 不存在 —— 先用 .venv-mjlab 跑 build_duck_mesh.py"
  exit 2
fi

# build/fat 由 selftest.sh 生成（含全部 core class + kotlin stdlib + duck_mesh.bin）。
# 先真跑一次 core 自检，既拿到产物也顺带确认几何/着色判据没退化。
echo "=== 1/3 core JVM 自检（生成 build/fat）==="
bash tools/selftest.sh > /dev/null 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: tools/selftest.sh rc=$rc，中止（不拿陈腐 class 画图）"
  exit "$rc"
fi
cp "$MESH" build/fat/duck_mesh.bin

echo "=== 2/3 编译离线渲染器 ==="
"$JDK17/bin/javac.exe" -encoding UTF-8 -cp build/fat -d build/fat tools/MeshPreview.java
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "FAIL: javac rc=$rc"
  exit "$rc"
fi

echo "=== 3/3 渲染三组各四帧（base / unknown / alert）==="
for mode in base unknown alert; do
  "$JDK17/bin/java.exe" -Djava.awt.headless=true -cp build/fat \
    MeshPreview "$MESH" "${TAG}_${mode}" "$mode"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "FAIL: java MeshPreview mode=$mode rc=$rc"
    exit "$rc"
  fi
done
echo "RENDER_RC=$rc"
ls -la build/mesh_preview_"${TAG}"_*.png 2>/dev/null
exit "$rc"
