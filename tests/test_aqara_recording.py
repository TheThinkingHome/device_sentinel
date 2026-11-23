# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_aqara_recording.py, Version: 0.30.3 (2026-11-23)

"""Aqara hubs in Extended Diagnostics (rule STACK-11).

Offered where an Aqara device reaches Home Assistant through Matter or
HomeKit Device. Each Aqara entity is recorded as it turns unavailable or
comes back, each burst of three or more Aqara devices reporting together,
and once a day how long since each one reported and the hub it sits
behind. Nothing is asked of a hub, and nothing is detected.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import _studiable
from custom_components.device_sentinel.const import (
    AQARA_KEY,
    CONF_STUDY_HARDWARE,
    PROBE_DETAIL,
    PROBE_NOW,
    PROBE_WAS,
    STUDIABLE,
)

from .helpers import probe_lines, setup_coordinator


def _house(hass: HomeAssistant, count: int = 4):
    entry = MockConfigEntry(domain="matter", title="Matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    devices = dr.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("matter", "hub")}, name="Aqara Hub M3",
        manufacturer="Aqara", model="Aqara Hub M3",
    )
    sensors = []
    for index in range(count):
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("matter", f"leak{index}")}, name=f"Leak {index}",
            manufacturer="Aqara", model="Aqara Water Leak Sensor",
        )
        devices.async_update_device(device.id, via_device_id=hub.id)
        entity = er.async_get(hass).async_get_or_create(
            "binary_sensor", "matter", f"leak{index}", device_id=device.id, config_entry=entry,
        ).entity_id
        hass.states.async_set(entity, "off")
        sensors.append((device, entity))
    return hub, sensors


async def test_offered_only_where_an_aqara_device_is_on_matter(hass: HomeAssistant):
    assert STUDIABLE[AQARA_KEY] not in _studiable(hass)
    _house(hass)
    assert STUDIABLE[AQARA_KEY] in _studiable(hass)


async def test_lines_for_a_device_gone_a_burst_and_the_day(hass: HomeAssistant):
    hub, sensors = _house(hass)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[AQARA_KEY]]})
    now = dt_util.utcnow().timestamp()
    coord._aqara_tick(now)
    # The four reported together when they were set: one burst line.
    together = probe_lines(coord, node="together")
    assert len(together) == 1 and together[0][PROBE_NOW] == "4 devices together"
    assert together[0][PROBE_DETAIL].endswith("through matter")
    # The same burst is not told twice, and a first sighting is no change.
    coord._aqara_tick(now + 60)
    assert len(probe_lines(coord, node="together")) == 1
    assert probe_lines(coord, node="entity") == []
    # One sensor turns unavailable behind the hub.
    hass.states.async_set(sensors[0][1], "unavailable")
    coord._aqara_tick(now + 120)
    gone = probe_lines(coord, node="entity")
    assert len(gone) == 1 and gone[0][PROBE_WAS] == "available" and gone[0][PROBE_NOW] == "unavailable"
    coord._aqara_fold(now + 200)
    day = probe_lines(coord, node="day")
    assert len(day) == 5, "each Aqara device, the hub too"
    assert sum(
        line[PROBE_NOW].startswith("last reported ") and line[PROBE_DETAIL].endswith("behind Aqara Hub M3")
        for line in day
    ) == 3, "the three still reporting, each behind its hub"
    assert sum(line[PROBE_NOW] == "no report held" for line in day) == 2, "the one gone, and the hub with no entity"
    told = coord.aqara_diagnostics()["devices"]
    assert told[hub.id]["devices_behind_it"] == 4
    assert told[sensors[0][0].id]["entities"] == {sensors[0][1]: "unavailable"}


async def test_devices_reporting_apart_are_no_burst(hass: HomeAssistant, freezer):
    _hub, sensors = _house(hass, count=3)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[AQARA_KEY]]})
    for index, (_device, entity) in enumerate(sensors):
        freezer.tick(timedelta(seconds=30))
        hass.states.async_set(entity, "on" if index % 2 else "off", force_update=True)
    coord._aqara_tick(dt_util.utcnow().timestamp())
    assert probe_lines(coord, node="together") == []


async def test_the_download_carries_it_when_chosen(hass: HomeAssistant):
    _house(hass)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[AQARA_KEY]]})
    study = coord.study_diagnostics
    assert "aqara" in (study() if callable(study) else study)
