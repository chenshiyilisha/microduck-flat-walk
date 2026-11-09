#!/usr/bin/env python3
"""probe_ch343_baud.py 的离线回归（不碰硬件）。

对应 `docs/active/microduck-Pi4B-完整部署方案-feetech_hls-2026-11-09.md` §12.1。
两条纪律：
- CLI 入口必须真的跑一遍（历史教训：只测内部函数会让 argparse 在 CI 里炸）。
- 自检必须有能删红的负对照：把「驱动接受」当成「芯片真发」必须让断言变红。
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
PROBE_DIR = HERE.parents[1] / "tools" / "hd1910" / "servo_probe"
PROBE = PROBE_DIR / "probe_ch343_baud.py"


def _load():
    if str(PROBE_DIR) not in sys.path:
        sys.path.insert(0, str(PROBE_DIR))
    spec = importlib.util.spec_from_file_location("probe_ch343_baud_under_test", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_cli_passes():
    r = subprocess.run([sys.executable, str(PROBE), "--selftest"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "20/20 passed" in r.stdout
    assert "FAIL " not in r.stdout


def test_frame_uses_single_authority():
    m = _load()
    import probe_bus_budget as pbb
    assert m.frame is pbb.frame
    assert m.rx_frame_len is pbb.rx_frame_len
    assert m.ping_frame(10) == bytes([0xFF, 0xFF, 0x0A, 0x02, 0x01, 0xF2])


def test_negative_control_only_echo_must_fail():
    """只看驱动回显就判 PASS => 自检必须变红（防 400000 式静默不发被漏检）。"""
    m = _load()

    def broken(*, open_ok, driver_echo, baud, replies, repeats):
        return {"status": "PASS", "reply_ratio": 1.0, "why": "只看回显"}

    m.classify = broken
    assert m.selftest() == 1
