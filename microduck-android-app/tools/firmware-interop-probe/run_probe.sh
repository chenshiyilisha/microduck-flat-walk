#!/usr/bin/env bash
# 固件侧 §4 wire 参考实现：真编译 + 真跑，与 Python golden vector 对拍。
# rc=0 且 6/6 passed = 固件端所需 crypto 原语在现成 crate 下可用且 wire 实现正确。
set -u
SRC="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"
command -v cargo >/dev/null 2>&1 || { echo "PRECONDITION_FAIL: cargo 不在 PATH"; exit 2; }

# 🔴 两个环境坑（本轮实测）：
#  1) Windows 默认 MSVC toolchain 缺 C++ build tools ⇒ link.exe 失败；已装 GNU toolchain 则用它。
#  2) E:/WorkBuddy 是 junction(实指向 E:/WorkBuddyData)，rustc 在其下编译 subtle 时
#     STATUS_ACCESS_VIOLATION(0xc0000005)。⇒ 拷到非 junction 的临时目录编译，源码仍在项目内。
TOOLCHAIN=""
if rustup target list --installed 2>/dev/null | grep -q "windows-msvc" &&
   rustup toolchain list 2>/dev/null | grep -q "windows-gnu"; then
  TOOLCHAIN="+stable-x86_64-pc-windows-gnu"
fi

# 契约校验（准则 8：正向提取完整值，不用裸子串）：探针必须与固件 workspace 的
# edition/rust-version 约束一致（固件 rust-toolchain.toml channel=1.99.0、edition 2024），
# 否则"固件侧可行性"的编译条件不可比。缺字段/改回旧值即 rc=3 拒。
PY="$(cd "$SRC/../.." && pwd)/../microduck-software/.venv-mjlab/Scripts/python.exe"
[ -x "$PY" ] || PY="python"
"$PY" - "$SRC/Cargo.toml" <<'PYEOF'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
def val(key):
    m = re.search(r'^\s*' + re.escape(key) + r'\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else None
edition, rustv = val("edition"), val("rust-version")
if edition != "2024" or rustv != "1.99":
    print(f"CONTRACT_FAIL: edition={edition!r} rust-version={rustv!r} (期望 2024 / 1.99)")
    sys.exit(3)
print(f"[contract] edition={edition} rust-version={rustv} OK")
PYEOF
[ $? -eq 0 ] || exit 3

BUILD="$(mktemp -d)/fw-crypto-probe"
mkdir -p "$BUILD/src"
cp "$SRC/Cargo.toml" "$SRC/Cargo.lock" "$BUILD/"
cp "$SRC/src/main.rs" "$BUILD/src/"
echo "[env] build in $BUILD (避开 junction); toolchain=${TOOLCHAIN:-default}"
cd "$BUILD" || exit 2
# shellcheck disable=SC2086
cargo $TOOLCHAIN run --offline 2>&1
rc=$?
echo "rc=$rc"
exit $rc
