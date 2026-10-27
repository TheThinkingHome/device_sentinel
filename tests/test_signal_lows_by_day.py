# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_lows_by_day.py, Version: 0.27.9 (2026-10-27)

"""Device Telemetry's signal lows read the last 30 calendar days, as the
device page does (rule SIG-06), not the last 30 stored rows."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import DATA_DEVICES, DEV_SIGNAL_DAILY_P5
from custom_components.device_sentinel.daily_dates import FAMILY_SIGNAL, set_dates

from .helpers import register_device, setup_coordinator


async def test_a_low_older_than_thirty_days_is_not_shown(hass: HomeAssistant):
    device, _ = register_device(hass, "sig6", name="Garden Sensor")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    yesterday = dt_util.now().date() - timedelta(days=1)
    # 10 rows from 60 to 51 days ago, then silent, then 20 rows ending yesterday.
    old_days = [yesterday - timedelta(days=60 - i) for i in range(10)]
    new_days = [yesterday - timedelta(days=19 - i) for i in range(20)]
    record[DEV_SIGNAL_DAILY_P5] = [-90.0] + [-70.0] * 9 + [-65.0, -66.0] + [-65.0] * 18
    set_dates(record, FAMILY_SIGNAL, old_days + new_days)
    cell = coord._format_signal_lows_cell(record)
    assert "-90" not in cell and "-70" not in cell
    assert "**-66**" in cell
    assert len(cell.split(" ")) == 20


async def test_consecutive_days_show_thirty(hass: HomeAssistant):
    device, _ = register_device(hass, "sig7", name="Hall Sensor")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [-60.0] * 40
    assert len(coord._format_signal_lows_cell(record).split(" ")) == 30
