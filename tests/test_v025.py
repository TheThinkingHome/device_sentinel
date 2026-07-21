# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v025.py, Version: 0.3.14 (2026-07-17)

"""0.2.5 tests: the diagnostic files."""

import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

DOMAIN = "device_sentinel"


async def test_reports_written_at_setup_and_midnight(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "rpt")},
        name="Report Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rpt", device_id=device.id, config_entry=source
    )
    svc = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "svc")},
        name="Service Thing",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    assert svc

    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    tele = hass.config.path("device_sentinel/device_telemetry.md")
    clas = hass.config.path("device_sentinel/classification.md")

    # Written at setup.
    assert os.path.isfile(tele)
    assert os.path.isfile(clas)
    tele_text = open(tele).read()
    clas_text = open(clas).read()
    assert "Report Device" in tele_text
    assert "Tunables:" in tele_text
    assert "trimmed maximum" in tele_text
    assert "| COPIES |" in clas_text
    assert "Report Device" in clas_text
    assert "Service Thing" in clas_text
    assert "Set aside" in clas_text

    # Rewritten at midnight, carrying the new maxima.
    os.remove(tele)
    os.remove(clas)
    nxt = (dt_util.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    freezer.move_to(nxt + timedelta(seconds=1))
    async_fire_time_changed(hass)
    # Home Assistant runs time-change listeners as background tasks
    # (async_run_hass_job(..., background=True) in _TrackUTCTimeChange),
    # and async_block_till_done skips background tasks by default. So
    # the plain call returned while the rollover was still writing its
    # report, and the assert below raced the file: about one run in ten
    # lost. Waiting for background tasks is what makes the midnight
    # path deterministic here.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert os.path.isfile(tele)
    assert os.path.isfile(clas)
