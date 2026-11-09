#!/usr/bin/env python3
"""Replay the `robotd --sim` port onto a clean `DuckBuddy-main` checkout.

`.upstream/` is gitignored on purpose, so the Rust changes made for the simulated-body seam
would otherwise vanish on a fresh clone. This directory is the part that *is* in VCS:

    sim.rs        -> duck-control/src/sim.rs          (new file)
    sim_e2e.rs    -> duck-control/tests/sim_e2e.rs   (new file)
    apply_sim_port.py -> six idempotent insertions into four existing files

Insertions are pure additions to upstream files: `lib.rs` (module), the two `Cargo.toml`
(serde_json dependency), and `robotd/src/main.rs` (the `--sim` CLI flag, one local binding,
and the control-thread branch). Comments attached to the `fake` flag mention `--sim` in our
copy; that cosmetic wording is deliberately NOT replayed, since it has no effect on behaviour.

Usage:
    python apply_sim_port.py --check     # verify only, no writes
    python apply_sim_port.py             # apply missing pieces (idempotent)
    python apply_sim_port.py --selftest  # negative control: strip -> check RED -> apply -> GREEN

`--root` overrides the upstream tree (used by --selftest, and by anyone who keeps the checkout
elsewhere). Overview and measured results:
`docs/active/microduck-仿真鸭移植-robotd--sim-2026-11-09.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[2]
DEFAULT_ROOT = SOFTWARE / ".upstream" / "DuckBuddy-main"

SIM_ARG_DOC = """    /// Run against a robot in MuJoCo, at `host:port`.
    ///
    /// **The same daemon, a simulated body.** Everything above `duck_control::io::RobotIo` — the
    /// loop, the policy, safety, fall detection, odometry, kinematics, every IPC call — is the
    /// code that runs on a robot, unchanged and unable to tell. `duck_control::sim` has the
    /// protocol and the reasons for its shape; the other half is
    /// `mjlab_microduck/sim/body_server.py`.
    ///
    /// Nothing is connected until the first tick, and a simulator that goes away is retried on
    /// every tick after — restarting MuJoCo must not mean restarting the duck.
    #[arg(long, conflicts_with = "fake")]
    sim: Option<String>,
"""

SIM_LOOP_BLOCK = """            // A simulated body, and nothing above the trait changes. No `open_bus_waiting` here,
            // deliberately: `RemoteIo` connects lazily and reconnects on every tick, so a duck
            // started before its simulator simply reports unhealthy until the simulator answers
            // - which is what a robot with no power on the bus does too, by a different route.
            if let Some(addr) = sim {
                tracing::warn!(%addr, "--sim: the body is in MuJoCo");
                runtime.block_on(control_loop(
                    duck_control::sim::RemoteIo::at(addr),
                    state,
                    intents,
                    params,
                    period,
                    poweroff,
                ));
                return;
            }
"""


@dataclass(frozen=True)
class Edit:
    path: str
    marker: str  # if already present, this edit is a no-op
    find: str  # unique substring locating the region
    insert: str
    after: str | None = None  # insert after this substring, searched from `find` onwards


EDITS = (
    Edit(
        "duck-control/src/lib.rs",
        "pub mod sim;",
        "pub mod servo_bus;\n",
        "pub mod sim;\n",
    ),
    Edit(
        "duck-control/Cargo.toml",
        "serde_json = { workspace = true }",
        "serde = { workspace = true }\n",
        "# `sim::RemoteIo` speaks the simulator's line-delimited JSON. The same crate `robotd` already\n"
        "# depends on, so this adds no new transitive weight to the workspace.\n"
        "serde_json = { workspace = true }\n",
    ),
    Edit(
        "Cargo.toml",
        'serde_json = "1"',
        'serde = { version = "1", features = ["derive"] }\n',
        'serde_json = "1"\n',
    ),
    Edit(
        "robotd/src/main.rs",
        "sim: Option<String>,",
        "    fake: bool,\n",
        "\n" + SIM_ARG_DOC,
    ),
    Edit(
        "robotd/src/main.rs",
        "let sim = args.sim.clone();",
        "    let fake = args.fake;\n",
        "    let sim = args.sim.clone();\n",
    ),
    Edit(
        "robotd/src/main.rs",
        "--sim: the body is in MuJoCo",
        "FakeIo::at(DEFAULT_POSITION),",
        "\n" + SIM_LOOP_BLOCK,
        after="                ));\n                return;\n            }\n",
    ),
)

COPIES = (
    ("sim.rs", "duck-control/src/sim.rs"),
    ("sim_e2e.rs", "duck-control/tests/sim_e2e.rs"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_text(path: Path) -> str:
    # `newline=""` matters here: Path.write_text on Windows silently turns every \n into
    # \r\n, and read_text silently turns it back — so a text-level diff looks clean while the
    # replayed tree differs from the live one byte for byte. Upstream is LF-only; normalize
    # any CRLF a Windows editor or checkout introduced so anchors still match.
    with path.open("r", encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def content_digest(path: Path) -> str:
    """Compare sources by content, so a CRLF checkout of this directory still matches LF upstream."""
    return hashlib.sha256(read_text(path).encode("utf-8")).hexdigest()


def inspect(root: Path) -> list[str]:
    problems: list[str] = []
    for src, rel in COPIES:
        dst = root / rel
        if not dst.exists():
            problems.append(f"MISSING {rel}")
        elif content_digest(dst) != content_digest(HERE / src):
            problems.append(f"MISMATCH {rel} (differs from the port in VCS)")
    for path in sorted({e.path for e in EDITS}):
        target = root / path
        if not target.exists():
            problems.append(f"MISSING {path}")
            continue
        text = read_text(target)
        for edit in (e for e in EDITS if e.path == path):
            if edit.marker not in text:
                problems.append(f"NOT APPLIED {path}: {edit.marker!r}")
    return problems


def apply(root: Path) -> tuple[int, list[str]]:
    changed = 0
    problems: list[str] = []
    for src, rel in COPIES:
        dst = root / rel
        if not dst.exists() or content_digest(dst) != content_digest(HERE / src):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / src, dst)
            changed += 1
            print(f"  wrote {rel}")
    by_path: dict[str, list[Edit]] = {}
    for edit in EDITS:
        by_path.setdefault(edit.path, []).append(edit)
    for path, edits in by_path.items():
        target = root / path
        if not target.exists():
            problems.append(f"MISSING {path} — unpack DuckBuddy-main first")
            continue
        text = read_text(target)
        original = text
        for edit in edits:
            if edit.marker in text:
                continue
            pos = text.find(edit.find)
            if pos < 0:
                problems.append(f"ANCHOR NOT FOUND in {path}: {edit.find!r}")
                continue
            if edit.after:
                tail = text.find(edit.after, pos + len(edit.find))
                if tail < 0:
                    problems.append(f"END ANCHOR NOT FOUND in {path}: {edit.after!r}")
                    continue
                at = tail + len(edit.after)
            else:
                at = pos + len(edit.find)
            text = text[:at] + edit.insert + text[at:]
            print(f"  patched {path}: +{edit.marker!r}")
        if text != original:
            write_text(target, text)
            changed += 1
    return changed, problems


def selftest() -> int:
    """Strip our insertions from a scratch copy, prove --check goes red, then reapply."""
    live = DEFAULT_ROOT
    with tempfile.TemporaryDirectory(prefix="sim_port_") as td:
        root = Path(td)
        for path in sorted({e.path for e in EDITS}):
            src, dst = live / path, root / path
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = read_text(src)
            for edit in (e for e in EDITS if e.path == path):
                if edit.insert not in text:
                    print(f"SELFTEST ERROR: cannot strip {edit.marker!r} from {path}")
                    return 2
                text = text.replace(edit.insert, "", 1)
            write_text(dst, text)

        stripped = inspect(root)
        print(f"1. stripped tree: {len(stripped)} problems (expect >0)")
        if not stripped:
            print("   NEGATIVE CONTROL FAILED: a clean tree passed --check")
            return 1

        _, problems = apply(root)
        print(f"2. apply: {len(problems)} errors (expect 0)")
        if problems:
            for p in problems:
                print("   " + p)
            return 1
        after = inspect(root)
        print(f"3. check after apply: {len(after)} problems (expect 0)")
        if after:
            for p in after:
                print("   " + p)
            return 1

        paths = sorted({e.path for e in EDITS})
        # The point of the whole package: replaying it must reproduce the tree we actually
        # compiled and tested against, not merely a tree that satisfies our own markers.
        diverged = [p for p in paths if digest(root / p) != digest(live / p)]
        print(f"4. replayed tree vs live tree: {len(diverged)} differing files (expect 0)")
        for p in diverged:
            print(f"   DIVERGED {p}")
        if diverged:
            return 1

        before_hashes = [digest(root / p) for p in paths]
        changed, _ = apply(root)
        after_hashes = [digest(root / p) for p in paths]
        print(f"5. second apply: {changed} files rewritten (expect 0)")
        if changed or before_hashes != after_hashes:
            print("   IDEMPOTENCE FAILED")
            return 1
        print("SELFTEST PASS: clean tree red, replayed tree byte-identical to live,")
        print("               all markers green, reapply is a no-op")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify only, write nothing")
    ap.add_argument("--selftest", action="store_true", help="run the negative-control roundtrip")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.root.is_dir():
        print(f"MISSING upstream tree: {args.root}")
        return 2
    if args.check:
        problems = inspect(args.root)
        if problems:
            for p in problems:
                print("FAIL " + p)
            print(f"CHECK: {len(problems)} problem(s)")
            return 1
        print(f"CHECK PASS: {len(COPIES)} sources match, {len(EDITS)} insertions present")
        return 0
    changed, problems = apply(args.root)
    if problems:
        for p in problems:
            print("ERROR " + p)
        return 1
    remaining = inspect(args.root)
    if remaining:
        for p in remaining:
            print("FAIL " + p)
        return 1
    print(f"APPLY PASS: {changed} file(s) written/updated, all insertions verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
