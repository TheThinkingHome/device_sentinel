# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_page_words.py, Version: 0.27.16 (2026-10-31)

"""Every code the server sends to the device page has plain words there
(rule DASH-08): the Gaps table's LEARNED column, and why the 42-day
count started again (rule FRZ-05). A code the page has no words for is
drawn raw, so a reason added on the server without its words would show
a person "no (bridge down)" beside "No, it was unavailable"."""

from __future__ import annotations

import re
from pathlib import Path

from custom_components.device_sentinel import const

PANEL = Path(__file__).parent.parent / "custom_components" / "device_sentinel" / "frontend" / "panel.js"


def _keys(name: str) -> set[str]:
    text = PANEL.read_text(encoding="utf-8")
    block = re.search(rf"const {name} = \{{(.*?)\n\}};", text, re.S)
    assert block, name
    quoted = set(re.findall(r'"([^"]+)":', block.group(1)))
    bare = set(re.findall(r"(?:^|[\s,{])([a-z_]+):", block.group(1)))
    return quoted | bare


def test_every_learned_code_has_words():
    sent = {"yes", const.EPISODE_LEARNED_TRUNCATED}
    sent |= {
        value for name, value in vars(const).items()
        if name.startswith("LEARNED_") and isinstance(value, str)
    }
    reasons = set(const.TAINT_REASONS) | {const.TAINT_UPSTREAM_DOWN, const.TAINT_CLOCK_JUMP}
    sent |= {f"no ({reason})" for reason in reasons}
    missing = sent - _keys("LEARNED_WORDS")
    assert not missing, sorted(missing)


def test_every_restart_reason_has_words():
    assert _keys("RESTART_WORDS") == set(const.LOGNORMAL_RESTART_REASONS)
