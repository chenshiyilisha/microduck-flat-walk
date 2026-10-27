#!/usr/bin/env bash
# Finish the mjlab stack that upstream's `uv sync` would have produced, without `uv sync`.
#
# Why not `uv sync`: pyproject binds bam to a git branch, and `git clone` from this machine is
# blocked by the proxy ("Empty reply from server") while `codeload.github.com` tarballs work.
# So bam and mjlab-microduck are installed from the extracted tarballs at .upstream/, and
# every version constraint still comes from upstream's own pyproject -- no version guessing.
set -u
cd "$(dirname "$0")/.." || exit 1
UV=../tooling/uvpkg/bin/uv.exe
PY=.venv-mjlab/Scripts/python.exe

# 官方 PyPI 走代理实测 88 KB/s，清华镜像 8.8 MB/s（差 100 倍，2026-10-23 实测）。
# warp-lang 单个 wheel 就 114 MB，用官方源要 20+ 分钟且频繁超时重试。
IDX=https://pypi.tuna.tsinghua.edu.cn/simple

echo "=== 0) core stack, versions from upstream pyproject ==="
# warp-lang: bam 只要求 >=1.12,<1.13，但 microduck_rl/pyproject.toml:18 精确钉 ==1.12.0。
# 取严格的那个（1.12.1 是后出的补丁版，上游没验过）。
$UV pip install --python $PY --index-url $IDX \
  "mjlab>=1.3,<1.4" "mujoco-warp>=3.7,<3.8" "mujoco>=3.7,<3.8" "warp-lang==1.12.0" \
  2>&1 | tail -6

echo "=== 1) bam (mjlab_frictionloss branch, local tarball, deps already satisfied) ==="
$UV pip install --python $PY --no-deps .upstream/bam-mjlab_frictionloss 2>&1 | tail -5

echo "=== 2) upstream's remaining declared deps ==="
$UV pip install --python $PY --index-url $IDX \
  "onnxruntime>=1.24.4" "rustypot>=1.4.2" "huggingface_hub>=0.27.0" "matplotlib>=3.10.9" \
  2>&1 | tail -8

echo "=== 3) mjlab_microduck itself (gives the mjlab.tasks entry point) ==="
$UV pip install --python $PY --no-deps .upstream/microduck_rl-develop 2>&1 | tail -8

echo "=== 4) verify ==="
$PY - <<'PY'
import importlib.metadata as md
for p in ("torch", "mjlab", "mujoco", "mujoco-warp", "warp-lang", "better-actuator-models",
          "mjlab-microduck", "onnxruntime"):
    try:
        print(f"  {p:<24} {md.version(p)}")
    except Exception as e:
        print(f"  {p:<24} MISSING ({e})")
PY
