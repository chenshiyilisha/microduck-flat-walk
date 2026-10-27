#!/usr/bin/env python3
"""Ensure mjlab train.py uses MUJOCO_GL=glfw on win32 (egl is illegal on Windows).

Upstream hardcodes egl. Local successful trains require glfw — see
workbuddy-history/memory/MEMORY.md and tools/hd1910/smoke_train.sh.
Idempotent: safe to re-run after mjlab reinstall.
"""
from __future__ import annotations

import pathlib
import sys

MARKER = "Upstream default is egl (Linux headless). On Windows egl raises"

PATCH = '''\
  # Upstream default is egl (Linux headless). On Windows egl raises at mujoco
  # import — use glfw (same as every successful MicroDuck velocity run here).
  import sys as _sys

  if _sys.platform == "win32":
    if os.environ.get("MUJOCO_GL", "egl") == "egl":
      os.environ["MUJOCO_GL"] = "glfw"
  else:
    os.environ["MUJOCO_GL"] = "egl"
'''

# Stock mjlab 1.3.0 fragment we replace (may already be patched).
STOCK = '  os.environ["MUJOCO_GL"] = "egl"\n'


def main() -> int:
    if len(sys.argv) > 1:
        train = pathlib.Path(sys.argv[1])
    else:
        import mjlab

        root = pathlib.Path(mjlab.__file__).resolve().parent
        train = root / "scripts" / "train.py"
    text = train.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"already patched: {train}")
        return 0
    if STOCK not in text:
        print(f"FAIL: expected stock MUJOCO_GL=egl assign missing in {train}", file=sys.stderr)
        return 2
    # Replace only the launch_training assignment (last occurrence is the one
    # after CUDA_VISIBLE_DEVICES wiring in mjlab 1.3.0).
    idx = text.rfind(STOCK)
    new = text[:idx] + PATCH + text[idx + len(STOCK) :]
    train.write_text(new, encoding="utf-8", newline="\n")
    print(f"patched: {train}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
