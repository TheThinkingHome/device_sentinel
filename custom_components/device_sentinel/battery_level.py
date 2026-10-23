# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: battery_level.py, Version: 0.27.1 (2026-10-23)

"""A battery level in words, the same on every surface (0.27.1).

James, 23 October 2026: Door 2nd Bedroom read 15.5% in the Daily Brief
and on the Simple dashboard, 16% on the Advanced device page, and 15% in
a phone push. The low verdict is made on the reading as reported, so a
level is shown as reported, to one decimal at most and with no ".0":
"15.5%", "16%", "100%". Rounded either way, 15.4 would read "15%" on a
cell the threshold of 15 did not call low. The dashboard's `levelText`
in panel.js says the same thing the same way.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def level_text(level: Any) -> str:
    """The level as "15.5%" or "16%"; empty for anything not a number."""
    if not isinstance(level, (int, float)) or isinstance(level, bool) or not math.isfinite(level):
        return ""
    return f"{level_number(level)}%"


def level_number(level: float) -> str:
    """The number alone: one decimal at most, and none when it is whole.

    Rounded half up on the number as written, 15.35 to 15.4, as the
    dashboard rounds it; Python's own round() makes 15.35 15.3."""
    tenth = Decimal(repr(float(level))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if tenth == tenth.to_integral_value():
        return str(int(tenth))
    return f"{tenth:f}"
