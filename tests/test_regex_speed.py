# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_regex_speed.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: regular expressions against 50 kB adversarial strings.

Names, models, attributes and stored text can be set by a device, and
several patterns run on Home Assistant's event loop. Safe: every
module-level pattern in the integration finishes a search, a full scan
and a substitution of each hostile string in under half a second.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import time

import pytest

import custom_components.device_sentinel as package

N = 50_000
HOSTILE = {
    "brackets": "[" * N,
    "nested": "[(" * (N // 2),
    "backslashes": "\\" * N,
    "escaped_brackets": "\\[" * (N // 2),
    "hex_colon": "a1:" * (N // 3),
    "hex_colon_tail": "a:" * (N // 2) + "!",
    "digit_colon": "1:" * (N // 2),
    "hex": "a" * N,
    "colons": ":" * N,
    "dotted": "1." * (N // 2),
    "hex_dotted": "abcd." * (N // 5),
    "hex_dash": "ab-" * (N // 3),
    "pipes": "|" * N,
    "angles": "<" * N,
    "spaces": " " * N,
    "percent_zone": "fe80::" + "%" + "a" * N + "!",
    "ipv4ish": "192.168." * (N // 8),
}


def _patterns() -> list[tuple[str, re.Pattern]]:
    found: dict[int, tuple[str, re.Pattern]] = {}
    for module in pkgutil.iter_modules(package.__path__):
        loaded = importlib.import_module(f"{package.__name__}.{module.name}")
        for name, value in vars(loaded).items():
            if isinstance(value, re.Pattern):
                found.setdefault(id(value), (f"{module.name}.{name}", value))
    return sorted(found.values(), key=lambda item: item[0])


@pytest.mark.parametrize("label,pattern", _patterns(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_pattern_is_fast_on_hostile_text(label, pattern):
    slow = []
    for name, text in HOSTILE.items():
        started = time.perf_counter()
        pattern.search(text)
        for _ in pattern.finditer(text):
            pass
        pattern.sub("", text)
        took = time.perf_counter() - started
        if took > 0.5:
            slow.append((name, round(took, 2)))
    assert slow == [], (label, slow)
