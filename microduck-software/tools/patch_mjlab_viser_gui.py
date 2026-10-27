"""Make mjlab's Viser viewer actually usable for MicroDuck (and safer by default).

Two independent upstream issues, both fatal for `play --viewer viser`:

1. `tasks/velocity/mdp/velocity_command.py` hard-codes `min=0.1` for the
   "Max <axis>" slider while passing `ranges.<axis>[1]` as its initial value.
   MicroDuck's joy task pins `lin_vel_x = (0., 0.)` (a gait clock, not a velocity
   command, drives the robot), so viser raises

       ValueError: add_slider: initial_value (0.0) is outside of [min, max] = [0.1, 10.0]

   and `ViserPlayViewer.setup()` dies outright. `NativeMujocoViewer` never calls
   `create_gui`, which is why `--viewer native` works while `--viewer viser` does not.

2. `viewer/viser/viewer.py` constructs `viser.ViserServer(label="mjlab")`, whose
   default host is `0.0.0.0` -- the viewer is reachable from the whole LAN, and
   loopback-only preview tooling refuses to proxy it.

Both edits are idempotent. If an anchor is missing (upstream refactor), the script
reports it and exits non-zero instead of writing a half-applied patch.
"""
from __future__ import annotations

import sys
from pathlib import Path

GUI_OLD = """      for label, max_val in axes:
        max_input = server.gui.add_slider(
          f"Max {label}",
          initial_value=max_val,
          step=0.1,
          min=0.1,
          max=10.0,
        )
        slider = server.gui.add_slider(
          label,
          min=-max_val,
          max=max_val,
          step=0.05,
          initial_value=0.0,
        )
"""

GUI_NEW = """      for label, max_val in axes:
        # A task may disable an axis entirely (MicroDuck joy pins lin_vel to 0).
        _span = max(abs(float(max_val)), 0.05)
        max_input = server.gui.add_slider(
          f"Max {label}",
          initial_value=_span,
          step=0.05,
          min=0.05,
          max=max(10.0, _span),
        )
        slider = server.gui.add_slider(
          label,
          min=-_span,
          max=_span,
          step=0.05,
          initial_value=0.0,
        )
"""
GUI_MARK = "_span = max(abs(float(max_val)), 0.05)"

HOST_OLD = """import time
from collections.abc import Callable"""
HOST_NEW = """import os
import time
from collections.abc import Callable"""

BIND_OLD = '    self._server = viser_server or viser.ViserServer(label="mjlab")'
BIND_NEW = """    # viser defaults to host 0.0.0.0, which serves the viewer to the whole LAN.
    # Bind loopback unless told otherwise; set MJLAB_VISER_HOST=0.0.0.0 to expose it.
    _host = os.environ.get("MJLAB_VISER_HOST", "127.0.0.1")
    _port = int(os.environ.get("MJLAB_VISER_PORT", "8080"))
    self._server = viser_server or viser.ViserServer(
      label="mjlab", host=_host, port=_port
    )"""
BIND_MARK = "MJLAB_VISER_HOST"


def _patch(path: Path, old: str, new: str, mark: str, label: str) -> bool:
    src = path.read_text(encoding="utf-8")
    if mark in src:
        print(f"  [skip] {label}: already patched")
        return True
    if old not in src:
        print(f"  [FAIL] {label}: anchor not found in {path}", file=sys.stderr)
        return False
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"  [ok]   {label}")
    return True


def main() -> int:
    import mjlab

    root = Path(mjlab.__file__).parent
    cmd = root / "tasks/velocity/mdp/velocity_command.py"
    vis = root / "viewer/viser/viewer.py"
    for p in (cmd, vis):
        if not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 1
    print("patching mjlab viser viewer:")
    ok = True
    ok &= _patch(cmd, GUI_OLD, GUI_NEW, GUI_MARK, "velocity slider bounds")
    ok &= _patch(vis, HOST_OLD, HOST_NEW, "import os\nimport time", "import os")
    ok &= _patch(vis, BIND_OLD, BIND_NEW, BIND_MARK, "loopback bind")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
