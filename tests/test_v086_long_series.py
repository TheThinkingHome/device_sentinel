# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v086_long_series.py, Version: 0.8.9 (2026-07-24)

"""0.8.6 tests: ninety days kept, a fortnight judged.

A fortnight is right for a rhythm and wrong for a battery: on a real
fleet nothing measurably discharges in two weeks. Signal rides along
at the same length so a season of dwell and floor history can be
studied. What must not change is any judgment made today, so the
floor and both signal columns go on reading only the most recent
fortnight however much is stored.
"""

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DAILY_MAX_KEEP,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEFAULT_RETENTION_DAYS,
    REPORT_DIAGNOSTIC_DIR,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


# --------------------------------------------- storage, not judgment

async def test_the_floor_ignores_history_beyond_a_fortnight(
    hass: HomeAssistant,
):
    """The guard that matters. The floor is the third lowest reading
    it can see, and the third lowest of ninety days is lower than the
    third lowest of fourteen, so reading the whole series would
    quietly slacken every floor on the fleet."""
    device = _register(hass, "f1", "Floor Sensor")
    coord = await _coordinator(hass)
    record = coord.data["devices"][device.id]

    fortnight = [100.0 - n for n in range(DAILY_MAX_KEEP)]
    record[DEV_SIGNAL_DAILY_MIN] = list(fortnight)
    with_a_fortnight = coord._danger_line(record)

    # The same fortnight, preceded by far worse older days.
    record[DEV_SIGNAL_DAILY_MIN] = [10.0] * 40 + list(fortnight)
    with_a_season = coord._danger_line(record)

    assert with_a_season == with_a_fortnight
    assert 10.0 not in coord._signal_history(record)


async def test_the_signal_series_keeps_ninety_days(
    hass: HomeAssistant,
):
    device = _register(hass, "s1", "Series Sensor")
    coord = await _coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [float(n) for n in range(200)]
    # The trim happens when a day is appended, so roll one.
    record[DEV_SIGNAL_TODAY_MIN] = 42.0
    await coord._on_midnight(None)
    assert len(record[DEV_SIGNAL_DAILY_MIN]) == DEFAULT_RETENTION_DAYS
    assert record[DEV_SIGNAL_DAILY_MIN][-1] == 42.0


async def test_the_columns_show_the_same_fortnight_as_before(
    hass: HomeAssistant,
):
    """A season of history must not widen the report's columns."""
    device = _register(hass, "c1", "Column Sensor")
    coord = await _coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [50.0 + n for n in range(DEFAULT_RETENTION_DAYS)]
    cell = coord._format_signal_lows_cell(record)
    assert len(cell.split()) == DAILY_MAX_KEEP


# ------------------------------------------------- where files live

async def test_the_maintainer_files_live_in_a_subfolder(
    hass: HomeAssistant,
):
    """The folder a person opens holds the briefs and nothing else."""
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    top = hass.config.path("device_sentinel")
    below = os.path.join(top, REPORT_DIAGNOSTIC_DIR)
    for name in (
        "device_telemetry.md",
        "classification.md",
        "silence_episodes.md",
    ):
        assert os.path.isfile(os.path.join(below, name)), name
        assert not os.path.isfile(os.path.join(top, name)), name
    assert any(
        name.startswith("daily_brief_") for name in os.listdir(top)
    )
