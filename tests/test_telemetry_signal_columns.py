# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_telemetry_signal_columns.py, Version: 0.22.16 (2026-09-21)

"""device_telemetry.md reads signal the way the judge does.

The report measured each device's daily lows against a floor-based
line and printed the floor's weekly drift and the mean and spread of
every reading. That line judges nothing: weak links are raised by the
bad-day model, which the dashboard draws. On the reference rig the two
lines for Temperature Main Bath sat 26 points apart, 104.3 against
78.6. Ruled 21 September 2026: the report carries the dashboard's
figures, its normal and the bad-day line, and marks the bad days.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P5,
    SIGNAL_DAYS_KEEP,
)

from tests.helpers import register_device, setup_coordinator

# Twenty-four steady days, one deep dip, five steady days after it.
SERIES = [120.0 + (n % 3) for n in range(24)] + [40.0] + [121.0] * 5


def _text(hass: HomeAssistant) -> str:
    with open(hass.config.path("device_sentinel/device_telemetry.md"), encoding="utf-8") as handle:
        return handle.read()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


async def _written(hass: HomeAssistant):
    device, _ = register_device(hass, "sig1", "Dip Sensor")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = list(SERIES)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _text(hass)
    header = next(line for line in text.splitlines() if line.startswith("| DEVICE (INTEGRATION)"))
    row = next(line for line in text.splitlines() if line.startswith("| Dip Sensor"))
    return coord, coord.data[DATA_DEVICES][device.id], text, _cells(header), _cells(row)


async def test_the_floor_columns_give_way_to_the_bad_day_model(hass: HomeAssistant):
    _coord, _record, _text_, header, row = await _written(hass)
    assert "FLOOR/WK" not in header
    assert "MEAN\u00b1SD" not in header
    assert header[6:8] == ["ITS NORMAL", "BAD-DAY LINE"]
    assert len(header) == len(row) == 9


async def test_its_normal_and_line_are_the_judges_own(hass: HomeAssistant):
    coord, record, _text_, header, row = await _written(hass)
    today = coord.signal_day_judgment(record, len(SERIES) - 1)
    assert today is not None
    assert row[header.index("ITS NORMAL")] == f"{today['normal']:.1f}"
    assert row[header.index("BAD-DAY LINE")] == f"{today['line']:.1f}"


async def test_exactly_the_bad_days_are_struck(hass: HomeAssistant):
    coord, record, _text_, header, row = await _written(hass)
    shown = row[header.index("SIGNAL")].split()
    assert len(shown) == min(len(SERIES), SIGNAL_DAYS_KEEP)
    # Newest first, as every series in the file reads.
    days = list(range(len(SERIES)))[-SIGNAL_DAYS_KEEP:][::-1]
    bad = {i for i in days if (coord.signal_day_judgment(record, i) or {}).get("bad")}
    assert bad, "the fixture must hold at least one bad day"
    struck = {i for i, cell in zip(days, shown) if cell.startswith("~~")}
    assert struck == bad


async def test_the_lowest_day_stays_bold(hass: HomeAssistant):
    _coord, _record, _text_, header, row = await _written(hass)
    shown = row[header.index("SIGNAL")].split()
    assert [cell for cell in shown if "**" in cell] == ["~~**40**~~"]


async def test_the_opening_paragraph_describes_the_bad_day_line(hass: HomeAssistant):
    _coord, _record, text, _header, _row = await _written(hass)
    intro = text[: text.index("## ")]
    assert "bad-day line" in intro
    assert "sensitivity margin above it" not in intro
    assert "floor is the lowest" not in intro
