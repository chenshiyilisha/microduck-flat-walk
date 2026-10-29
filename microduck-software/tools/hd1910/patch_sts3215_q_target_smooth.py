"""Patch editable BAM STS3215Actuator for mjlab (q_target_smooth lazy init).

Upstream only sets ``q_target_smooth`` in ``load_log()``. mjlab's BamActuator
never calls that, so the first ``compute_control`` crashes with
AttributeError. Apply once after installing the pinned editable bam tree.

Usage (from microduck-software/):

    .venv-mjlab/Scripts/python.exe tools/hd1910/patch_sts3215_q_target_smooth.py
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "mjlab never calls load_log()"

OLD = '''    def compute_control(
        self, q_target: ArrayLike, q: ArrayLike, dq: ArrayLike, dt: float
    ) -> ArrayLike | None:
        """
        Assumes the motor is using a kp controller
        This can be overloaded if more custom behaviour is used
        """

        # Internal target position is clipped using maximum velocity
        self.q_target_smooth = self.backend.clamp(
'''

NEW = '''    def compute_control(
        self, q_target: ArrayLike, q: ArrayLike, dq: ArrayLike, dt: float
    ) -> ArrayLike | None:
        """
        Assumes the motor is using a kp controller
        This can be overloaded if more custom behaviour is used
        """

        # mjlab never calls load_log(); seed the slew state on first use / shape change.
        # (Upstream only sets q_target_smooth inside load_log.)
        need = not hasattr(self, "q_target_smooth")
        if not need:
            prev = self.q_target_smooth
            need = getattr(prev, "shape", None) != getattr(q_target, "shape", None)
        if need:
            if hasattr(q_target, "detach"):
                self.q_target_smooth = q_target.detach() * 0
            else:
                self.q_target_smooth = np.zeros_like(np.asarray(q_target, dtype=float))

        # Internal target position is clipped using maximum velocity
        self.q_target_smooth = self.backend.clamp(
'''


def _candidates(root: Path) -> list[Path]:
    out: list[Path] = []
    up = root / ".upstream"
    if up.is_dir():
        out.extend(up.glob("bam-*/bam/feetech/actuator.py"))
    try:
        import bam

        p = Path(bam.__file__).resolve().parent / "feetech" / "actuator.py"
        if p.is_file():
            out.append(p)
    except Exception:
        pass
    # de-dupe
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    paths = _candidates(root)
    if not paths:
        print("FAIL: no bam feetech/actuator.py found", file=sys.stderr)
        return 2
    n_ok = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            print(f"already patched: {path}")
            n_ok += 1
            continue
        if OLD not in text:
            print(f"FAIL: expected block missing in {path}", file=sys.stderr)
            return 3
        path.write_text(text.replace(OLD, NEW), encoding="utf-8", newline="\n")
        print(f"patched: {path}")
        n_ok += 1
    print(f"ok ({n_ok} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
