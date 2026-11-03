"""Diff two finished training runs' effective recipe, leaf by leaf.

Why this exists
---------------
"Only the reward differs" is the entire premise of the heading A/B, and it is
the kind of premise that decays quietly: the first attempt at this comparison
(2026-11-02 21:26 vs the 2026-11-03 arm) was believed to be
`rel_heading_envs 0.3, no rewards` vs `rel_heading_envs 0.3, rewards`, i.e. one
variable. It is not. `--ang-vel-z-clip` was ignored on the reward-free run
because the flag was only read inside the reward branch, so that run also
trained with a +-1.0 turn range instead of +-0.5. Two variables, and the run
name did not say so.

So the comparison here is mechanical: flatten both `params/env.yaml` and
`params/agent.yaml` to leaf paths and print every path whose value differs.
The caller declares which paths are ALLOWED to differ (`--expect`, a path
prefix); anything else exits non-zero. A diff that nobody pre-declared is the
signal, not the noise.

Usage
    # the two arms of the heading A/B (the only allowed diffs are the rewards)
    python tools/hd1910/diff_run_recipes.py \\
        --a 2026-11-03_08-33-18_p8head_030_4096x3000 \\
        --b logs/rsl_rl/microduck_velocity_hd1910/2026-11-03_21-00-00_p8ctl_030_4096x3000 \\
        --expect rewards --expect curriculum \\
        --expect commands.twist.ranges.ang_vel_z --expect agent.run_name
    python tools/hd1910/diff_run_recipes.py --selftest
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

LOGS = Path("logs/rsl_rl/microduck_velocity_hd1910")
# `!!python/name:` drops to a bare '' with a naive strip, which makes "absent"
# and "present but empties to ''" indistinguishable. Keep the tag identity.
# mjlab writes `!!python/name:foo ''` (trailing empty scalar), so the trailing
# quotes have to go with the tag or the line becomes two scalars.
NAME_RE = re.compile(r"!!python/name:(\S+)(?:\s+'')?")
APPLY_RE = re.compile(r"!!python/object/apply:(\S+?)(?=\s|$)")
TUPLE_RE = re.compile(r"!!python/tuple")
STRIP_RE = re.compile(r"!!python/[A-Za-z0-9_./]+(?::[^\s]*)?")


def _read(text: str, *, keep_tags: bool) -> object:
    if keep_tags:
        t = NAME_RE.sub(lambda m: f"'<name:{m.group(1)}>'", text)
        t = APPLY_RE.sub(lambda m: f"'<apply:{m.group(1)}>'", t)
        t = TUPLE_RE.sub("", t)
    else:
        t = STRIP_RE.sub("", text)
    return yaml.safe_load(t)


def load_flat(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    try:
        obj = _read(raw, keep_tags=True)
    except yaml.YAMLError:
        # Some tag shape we do not model yet: fall back to stripping tags, which
        # loses function identity but keeps every scalar/vs-absent comparison.
        obj = _read(raw, keep_tags=False)
    out: dict[str, object] = {}

    def walk(x, pre: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{pre}.{k}" if pre else str(k))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{pre}[{i}]")
        else:
            out[pre] = x

    walk(obj, "")
    return out


def resolve(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p
    hits = sorted(LOGS.glob(f"*_{arg}")) + sorted(LOGS.glob(f"*{arg}*"))
    if not hits:
        raise SystemExit(f"no run directory matches {arg!r} under {LOGS}")
    return hits[-1]


def same(va, vb) -> bool:
    if isinstance(va, float) and isinstance(vb, float):
        return abs(va - vb) <= 1e-9 * max(1.0, abs(va), abs(vb))
    return va == vb


def diff_runs(a: Path, b: Path) -> list[tuple[str, str, object, object]]:
    """[(file, path, a_val, b_val)] for every differing leaf."""
    diffs = []
    for fname in ("env.yaml", "agent.yaml"):
        fa, fb = a / "params" / fname, b / "params" / fname
        if not fa.exists() or not fb.exists():
            raise SystemExit(f"missing {fa if not fa.exists() else fb}")
        la, lb = load_flat(fa), load_flat(fb)
        for k in sorted(set(la) | set(lb)):
            va, vb = la.get(k, "<absent>"), lb.get(k, "<absent>")
            if not same(va, vb):
                diffs.append((fname, k, va, vb))
    return diffs


def covered(path: str, prefixes: list[str]) -> bool:
    for p in prefixes:
        if path == p or path.startswith(p + ".") or path.startswith(p + "["):
            return True
    return False


def report(a: Path, b: Path, diffs, expect: list[str]) -> int:
    print(f"A: {a.name}")
    print(f"B: {b.name}")
    if not diffs:
        print("no differences in params/env.yaml or params/agent.yaml")
        return 0
    unexpected = [d for d in diffs if not covered(d[1], expect)]
    print(f"{len(diffs)} differing leaf/leaves "
          f"({len(diffs) - len(unexpected)} declared, {len(unexpected)} unexpected)")
    for fname, path, va, vb in diffs:
        flag = "  " if covered(path, expect) else "!!"
        print(f" {flag} {fname:10s} {path}: {va!r} -> {vb!r}")
    if unexpected:
        print("\nUNDECLARED DIFFERENCES -- the two arms differ in more than the "
              "recipe claims.\nEither they are not comparable, or the expectation "
              "list is incomplete. Both need a human, not a silent pass.")
        return 2
    print("\nok: every difference was declared with --expect")
    return 0


def selftest() -> int:
    fails = 0

    def one(label: str, a: Path, b: Path, expect: list[str], want_rc: int) -> list:
        nonlocal fails
        diffs = diff_runs(a, b)
        rc = report_dry(diffs, expect)
        ok = rc == want_rc
        if not ok:
            fails += 1
        print(f"[{'ok' if ok else 'FAIL'}] {label}")
        return diffs

    def report_dry(diffs, expect) -> int:
        return 0 if all(covered(d[1], expect) for d in diffs) else 2

    reward = resolve("2026-11-03_08-33-18_p8head_030_4096x3000")
    wide = resolve("2026-11-02_21-26-53_p8head_030_4096x3000")
    if not reward.is_dir() or not wide.is_dir():
        print("[FAIL] 找不到对照用的两个 run")
        return 3

    # 1) a run against itself: zero diffs, and that must be accepted
    d1 = one("t1 同一个 run 自比 ⇒ 0 差异、放行", reward, reward, [], 0)
    if d1:
        fails += 1
        print("[FAIL] t1 自比居然有差异")

    # 2) 11-02 vs 11-03: rewards + curriculum + turn range. Declared ⇒ accepted.
    d2 = one("t2 声明了 rewards/curriculum/转向范围 ⇒ 放行",
             wide, reward,
             ["rewards", "curriculum", "commands.twist.ranges.ang_vel_z"], 0)
    if len(d2) != 29:
        fails += 1
        print(f"[FAIL] t2 期望 29 处差异（1 处范围 x2 + 27 处奖励/课程），实测 {len(d2)}")

    # 3) same pair, but the rewards were NOT declared ⇒ must be refused.
    #    This is the "one variable" claim being caught when it is false.
    one("t3 同一对 run，未声明 rewards ⇒ 必须拒", wide, reward,
        ["commands.twist.ranges.ang_vel_z"], 2)

    # 4) turn range alone is not enough either: declare only rewards, the range
    #    still shows up as undeclared. Guards the direction I got wrong before.
    one("t4 只声明 rewards、漏掉转向范围 ⇒ 必须拒", wide, reward,
        ["rewards", "curriculum"], 2)

    print(f"\nselftest: {'all green' if fails == 0 else f'{fails} check(s) FAILED'}")
    return 0 if fails == 0 else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--expect", action="append", default=[],
                    help="path prefix allowed to differ; repeatable")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.selftest:
        return selftest()
    if not ns.a or not ns.b:
        ap.error("--a and --b are required (or --selftest)")
    return report(resolve(ns.a), resolve(ns.b), diff_runs(resolve(ns.a), resolve(ns.b)),
                  ns.expect)


if __name__ == "__main__":
    sys.exit(main())
