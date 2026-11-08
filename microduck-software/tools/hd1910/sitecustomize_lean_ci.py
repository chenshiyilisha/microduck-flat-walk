r"""Simulate the lean deploy-gate CI interpreter on this workstation.

The GitHub Actions job installs ONLY tools/hd1910/requirements.txt
(onnx / onnxruntime / numpy / pytest) on a fresh Python 3.12. It has NO
mjlab_microduck, torch, mujoco, warp, scipy OR bam. Creating that venv locally
is often impossible (the configured pip mirror may have no onnx wheels), so we
hide exactly those packages from an interpreter that already has them. Two
independent mechanisms are needed:

  * a meta_path finder that makes `import <blocked>` raise ModuleNotFoundError
  * a wrapper over importlib.util.find_spec that returns None for blocked
    names (tests use find_spec(...) is None as their "lean env" predicate)

Usage (Git Bash / POSIX)::

    mkdir -p /tmp/lean_ci
    cp tools/hd1910/sitecustomize_lean_ci.py /tmp/lean_ci/sitecustomize.py
    PYTHONPATH=/tmp/lean_ci .venv-mjlab/Scripts/python.exe -m pytest tests/ -q -rs

Windows PowerShell::

    mkdir $env:TEMP\lean_ci
    copy tools\hd1910\sitecustomize_lean_ci.py $env:TEMP\lean_ci\sitecustomize.py
    $env:PYTHONPATH = "$env:TEMP\lean_ci"
    .venv-mjlab\Scripts\python.exe -m pytest tests\ -q -rs

WHY THIS IS COMMITTED
----------------------
Pass19 (2026-11-08): this script originally lived only in a temp directory and
its BLOCKED set omitted `bam`, which exists solely in a gitignored .upstream
snapshot on this workstation. The local "lean CI" simulation therefore passed
7 rehearsal tests that the real GitHub Actions run failed with
`ModuleNotFoundError: No module named 'bam'`. A simulation that under-blocks
its own dependencies is itself a source of false greens. Keep BLOCKED in sync
with the REAL CI environment, and see the regression test that pins it.

This is a stand-in, NOT the authoritative verification: a real push + workflow
run is the only proof that CI actually works.
"""
import importlib.abc
import importlib.util
import sys

# Every third-party package the real lean CI interpreter does NOT have.
# Derived from tools/hd1910/requirements.txt and the real Actions log.
BLOCKED = {"mjlab_microduck", "mjlab", "torch", "mujoco", "warp", "scipy", "bam"}

_original_find_spec = importlib.util.find_spec


def _lean_find_spec(name, package=None):
    if name.split(".")[0] in BLOCKED:
        return None
    return _original_find_spec(name, package)


importlib.util.find_spec = _lean_find_spec


class _BlockMissingDeps(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(
                "lean-CI simulation: %s is not installed (only "
                "tools/hd1910/requirements.txt is)" % fullname,
                name=fullname,
            )
        return None


sys.meta_path.insert(0, _BlockMissingDeps())
