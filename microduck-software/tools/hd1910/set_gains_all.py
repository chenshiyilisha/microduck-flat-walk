#!/usr/bin/env python
"""Audit / set the firmware position gain on all 15 HD1910 joints.

Why this exists
---------------
docs/05-flat-walk.md §22.4: the P8 policy's +83% only holds when reg 50 == 8 on
*every* servo (§21.3: at kp=5 it falls 7/8). Doing that by hand, one servo at a
time, with a GUI, is how you end up with 14 at 8 and one at 32 — and that machine
is unusable, not degraded.

Two writers, not one
--------------------
The gain that is actually in effect is **RAM reg 50/51**. EEPROM reg 21/22 is
what the firmware loads into RAM at power-up. So:

  * writing only 50  -> correct until the next power cycle, then silently reverts
  * writing only 21  -> survives power-up, but the running servo keeps the old P

Both must be written, and both read back. `--persist` does 21/22 (unlock reg 55,
write, re-lock); without it only the RAM pair is touched.

⚠️ A third writer may exist off this machine: the robot runtime does not live in
this repo (no `microduck_playground` in this venv), so "who else writes reg 50 at
boot" is UNVERIFIED. If that stack writes 5, a bench-set 8 is overwritten on the
next power-up. Check on the Radxa before trusting a real robot.

Registers that must NOT drift (all four cause silent behaviour changes)
-----------------------------------------------------------------------
  41 accel   0   writing 10 doubles the step settle time (580 -> 1115 ms, §20.3)
  46 speed   0   speed cap; 0 = no cap. The old "must write 300" advice is wrong
  48 torque  1000
  33 mode    4

Usage
-----
  # read-only audit of the 15 joints; exit 1 if any does not match --expect
  python tools/hd1910/set_gains_all.py --port COM3

  # actually set them (RAM + EEPROM), then verify by readback
  python tools/hd1910/set_gains_all.py --port COM3 --write --kp 8 --kd 0 --persist --yes

  # no hardware needed: exercises the call sequence against a fake bus
  python tools/hd1910/set_gains_all.py --selftest
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "servo_probe"))

REG_P_GAIN, REG_D_GAIN = 21, 22          # EEPROM, survives power cycle
REG_MODE, REG_ACCEL, REG_SPEED = 33, 41, 46
REG_TORQUE_ENABLE = 40                   # 1 B; EEPROM writes want torque off
REG_TORQUE_LIMIT = 48                    # 2 B
REG_P_RAM, REG_D_RAM = 50, 51            # in effect now, reloaded from 21/22
REG_LOCK = 55                            # 0 = EEPROM writable, 1 = locked

#: Inter-packet pause after *every* EEPROM-region write, including the two lock
#: writes. STS3215 commits an EEPROM byte in ~10 ms; a packet that arrives
#: mid-commit is rejected (error -6) or, worse, ACKed while the commit is torn —
#: the register then reads back the new value from a RAM shadow and reverts at
#: the next power-up. 50 ms = 10 ms commit + margin, matching the 30 ms floor
#: used by robotic-companion/motor/bus.py ("EEPROM commit timing").
#: This constant is the fix for the 2026-11-03 finding: EEPROM read back 8,
#: survived as 32 (§22.5). Readback alone can never prove persistence.
EEPROM_COMMIT_S = 0.05

#: Hard floor from the same source: below this the next packet lands in the
#: commit window. Kept separate from EEPROM_COMMIT_S on purpose — a gate that
#: compares a value against a threshold derived from itself passes when both
#: are zero (caught by the negative control on 2026-11-03).
EEPROM_COMMIT_FLOOR_S = 0.03

#: 15 joints: legs 10-14 / 20-24 / 30-34 (docs §11: factory IDs are all 1 and
#: must be assigned one at a time; these are the slots this build uses).
DEFAULT_IDS = [f"{base}{i}" for base in (10, 20, 30) for i in range(5)]


def audit(bus, ids, expect: dict) -> tuple[list, bool]:
    """Read every joint. Returns (rows, ok). Never writes."""
    rows, ok = [], True
    for sid in ids:
        if bus.ping(sid) is False:
            rows.append(dict(id=sid, present=False))
            continue
        r = dict(id=sid, present=True,
                 p_eeprom=bus.read_u8(sid, REG_P_GAIN),
                 d_eeprom=bus.read_u8(sid, REG_D_GAIN),
                 p_ram=bus.read_u8(sid, REG_P_RAM),
                 d_ram=bus.read_u8(sid, REG_D_RAM),
                 mode=bus.read_u8(sid, REG_MODE),
                 accel=bus.read_u8(sid, REG_ACCEL),
                 speed=bus.read_u16(sid, REG_SPEED),
                 torque=bus.read_u16(sid, REG_TORQUE_LIMIT))
        r["mismatch"] = [k for k, want in expect.items() if r.get(k) != want]
        if r["mismatch"]:
            ok = False
        rows.append(r)
    return rows, ok


def apply(bus, ids, kp: int, kd: int, accel: int, persist: bool, expect: dict):
    """Write, then read back. Returns (rows, ok) — never trusts the write ack."""
    rows, ok = [], True
    for sid in ids:
        if bus.ping(sid) is False:
            rows.append(dict(id=sid, present=False))
            ok = False
            continue

        # Order matters: accel first, so the servo is never left at a stale ramp.
        if accel is not None:
            bus.write_u8(sid, REG_ACCEL, accel)
        bus.write_u8(sid, REG_P_RAM, kp)
        bus.write_u8(sid, REG_D_RAM, kd)
        if persist:
            # EEPROM is committed one byte at a time: pause after each write or
            # the next packet lands inside the commit window (§22.5).
            was_torque = bus.read_u8(sid, REG_TORQUE_ENABLE)
            if was_torque:
                bus.write_u8(sid, REG_TORQUE_ENABLE, 0)
                time.sleep(EEPROM_COMMIT_S)
            for reg, val in ((REG_LOCK, 0), (REG_P_GAIN, kp),
                             (REG_D_GAIN, kd), (REG_LOCK, 1)):
                bus.write_u8(sid, reg, val)
                time.sleep(EEPROM_COMMIT_S)
            if was_torque:
                bus.write_u8(sid, REG_TORQUE_ENABLE, was_torque)
        time.sleep(0.05)

        r = dict(id=sid, present=True,
                 p_eeprom=bus.read_u8(sid, REG_P_GAIN),
                 d_eeprom=bus.read_u8(sid, REG_D_GAIN),
                 p_ram=bus.read_u8(sid, REG_P_RAM),
                 d_ram=bus.read_u8(sid, REG_D_RAM),
                 mode=bus.read_u8(sid, REG_MODE),
                 accel=bus.read_u8(sid, REG_ACCEL),
                 speed=bus.read_u16(sid, REG_SPEED),
                 torque=bus.read_u16(sid, REG_TORQUE_LIMIT))
        r["mismatch"] = [k for k, want in expect.items() if r.get(k) != want]
        if r["mismatch"]:
            ok = False
        rows.append(r)
    return rows, ok


def report(rows, expect: dict) -> None:
    cols = ["p_eeprom", "d_eeprom", "p_ram", "d_ram", "mode", "accel", "speed", "torque"]
    print(f"{'id':>4} {'seen':>4} " + " ".join(f"{c:>8}" for c in cols) + "  mismatch")
    for r in rows:
        if not r["present"]:
            print(f"{r['id']:>4} {'-':>4} " + " ".join(f"{'':>8}" for _ in cols)
                  + "  NOT PRESENT")
            continue
        print(f"{r['id']:>4} {'ok':>4} " + " ".join(f"{str(r.get(c)):>8}" for c in cols)
              + f"  {','.join(r['mismatch']) or 'ok'}")
    want = " ".join(f"{k}={v}" for k, v in expect.items())
    print(f"\nexpected: {want}")


class FakeBus:
    """In-memory bus for --selftest. `drop_writes` is the negative control."""

    def __init__(self, regs: dict, present=(), drop_writes=False):
        self.regs = {sid: dict(v) for sid, v in regs.items()}
        self.present = set(present) or set(regs)
        self.drop_writes = drop_writes
        self.log: list[tuple] = []

    def ping(self, sid):
        return sid in self.present

    def read_u8(self, sid, addr):
        return self.regs.get(sid, {}).get(addr)

    def read_u16(self, sid, addr):
        return self.regs.get(sid, {}).get(addr)

    def write_u8(self, sid, addr, v):
        self.log.append(("w8", sid, addr, v, time.monotonic()))
        if self.drop_writes:
            return False
        self.regs.setdefault(sid, {})[addr] = v
        return True


def selftest() -> int:
    """Prove the write sequence and the readback gate, without hardware."""
    ok = True
    good = {10: {21: 32, 22: 40, 50: 5, 51: 0, 33: 4, 41: 0, 46: 0, 48: 1000}}

    # 1. audit on a joint that does not match => must report not-ok, and not write.
    bus = FakeBus(good, present={10})
    rows, passed = audit(bus, [10], {"p_ram": 8, "accel": 0})
    same = not bus.log
    print(f"selftest 1 audit-mismatch   ok={passed} writes={len(bus.log)} "
          f"{'ok' if (not passed and same) else 'FAIL'}")
    ok &= (not passed) and same

    # 2. apply => RAM and EEPROM both end at 8/0, and 55 is re-locked.
    bus = FakeBus(good, present={10})
    rows, passed = apply(bus, [10], 8, 0, 0, True, {"p_ram": 8, "p_eeprom": 8,
                                                   "d_ram": 0, "d_eeprom": 0,
                                                   "accel": 0})
    r = bus.regs[10]
    good2 = passed and r[50] == 8 and r[21] == 8 and r[51] == 0 and r[22] == 0 and r[55] == 1
    print(f"selftest 2 apply-persist   ok={passed} reg50={r[50]} reg21={r[21]} "
          f"lock={r[55]} {'ok' if good2 else 'FAIL'}")
    ok &= good2

    # 3. negative control: writes silently dropped => the readback gate must FAIL.
    #    Without this, "I sent it" would pass as "it took".
    bus = FakeBus(good, present={10}, drop_writes=True)
    rows, passed = apply(bus, [10], 8, 0, 0, True, {"p_ram": 8, "p_eeprom": 8})
    print(f"selftest 3 dropped-writes  ok={passed} (must be False) "
          f"{'ok' if not passed else 'FAIL'}")
    ok &= not passed

    # 4. a missing joint must fail the run, not be skipped.
    bus = FakeBus(good, present={10})
    rows, passed = apply(bus, [10, 11], 8, 0, 0, False, {"p_ram": 8})
    print(f"selftest 4 missing-joint   ok={passed} (must be False) "
          f"{'ok' if not passed else 'FAIL'}")
    ok &= not passed

    # 5. EEPROM commit rhythm (§22.5). Two things must hold, and both were false
    #    on 2026-11-03: every EEPROM-region write is separated by >= commit time,
    #    and torque is switched off around the write and left as it was found.
    #    A dropped sleep here is invisible in the readback — only this catches it.
    joint = dict(good[10])
    joint[40] = 1
    bus = FakeBus({10: joint}, present={10})
    rows, passed = apply(bus, [10], 8, 0, 0, True,
                         {"p_ram": 8, "p_eeprom": 8, "d_ram": 0, "d_eeprom": 0})
    eeprom_writes = [e for e in bus.log if e[2] in (21, 22, 55)]
    gaps = [b[4] - a[4] for a, b in zip(eeprom_writes, eeprom_writes[1:])]
    # Threshold is the independent floor (30 ms), never EEPROM_COMMIT_S itself:
    # Windows' monotonic clock resolves to ~15.6 ms, so a 50 ms sleep measures
    # low, and a self-derived threshold would pass when the sleep is removed.
    rhythm_ok = (EEPROM_COMMIT_S >= EEPROM_COMMIT_FLOOR_S
                 and bool(gaps) and min(gaps) >= EEPROM_COMMIT_FLOOR_S)
    torque_off = any(e[2] == 40 and e[3] == 0 for e in bus.log)
    torque_back = bus.regs[10][40] == 1
    print(f"selftest 5 commit-rhythm  min_gap={min(gaps) * 1000 if gaps else 0:.0f}ms "
          f"writes={len(eeprom_writes)} torque_off={torque_off} restored={torque_back} "
          f"{'ok' if (rhythm_ok and torque_off and torque_back) else 'FAIL'}")
    ok &= rhythm_ok and torque_off and torque_back

    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--ids", nargs="+", type=int, default=DEFAULT_IDS)
    ap.add_argument("--kp", type=int, default=8, help="target reg 50/21 (default 8, §22)")
    ap.add_argument("--kd", type=int, default=0)
    ap.add_argument("--accel", type=int, default=0,
                    help="reg 41; 0 = no ramp. Do NOT write 10 (§20.3: 2x slower)")
    ap.add_argument("--persist", action="store_true",
                    help="also write EEPROM 21/22 (survives power cycle)")
    ap.add_argument("--write", action="store_true", help="actually write; default is audit")
    ap.add_argument("--yes", action="store_true", help="confirm writing gains to hardware")
    ap.add_argument("--selftest", action="store_true", help="run without hardware")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.write and not args.yes:
        sys.exit("refusing to write gains without --yes (audit is the default)")

    # What a correct joint looks like. p_eeprom only when --persist, because an
    # audit must not demand EEPROM == kp on a joint that was only ever set in RAM.
    expect = {"p_ram": args.kp, "d_ram": args.kd, "accel": args.accel, "mode": 4}
    if args.persist:
        expect.update(p_eeprom=args.kp, d_eeprom=args.kd)

    from hd1910_ident import Bus  # noqa: E402  (needs servo_probe on sys.path)

    bus = Bus(args.port)
    try:
        if args.write:
            rows, ok = apply(bus, args.ids, args.kp, args.kd, args.accel,
                             args.persist, expect)
        else:
            rows, ok = audit(bus, args.ids, expect)
    finally:
        bus.close()

    report(rows, expect)
    seen = sum(1 for r in rows if r["present"])
    print(f"\n{seen}/{len(args.ids)} joints answered; "
          f"{'ALL MATCH' if ok else 'MISMATCH'}")
    if args.write and args.persist and ok:
        print("\n⚠️  readback PASS is NOT persistence. The servo answers 21/22 out of "
              "a RAM shadow,\n    so a torn EEPROM commit also reads back correct "
              "(observed 2026-11-03: 8 -> 32).\n    Only a power cycle proves it: "
              "re-run this audit after unplugging the bus.")
    if not ok:
        print("⇒ this machine is NOT usable for the P8 policy: one mismatched "
              "joint is enough to fall (§21.3, 7/8 falls at kp=5).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
