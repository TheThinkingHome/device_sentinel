# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_foreign_entities.py, Version: 0.22.21 (2026-09-22)

"""Another integration's entity on a device is not the device speaking.

Battery Notes adds a battery entity to devices other integrations own,
and on the second fleet it refreshed them about every 26 minutes. On 65
devices with no Last Seen clock each refresh stamped the device as
heard, so a dead sensor could be kept looking alive, and each refresh
was counted as Battery Notes republishing its whole fleet. Since
0.22.21 a foreign entity still supplies a reading the device publishes
nowhere else (ruling #404) and does nothing else: it stamps no clock,
feeds no burst, ties the device to none of its reloads, and holds no
device up that is down.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_DEVICES,
    DATA_STORM_DAYS,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    FLOOD_MIN_DAYS,
    FLOOD_MIN_STORMS,
    FREEZE_CATEGORY_UNAVAILABLE,
    SET_ASIDE_NO_ENTITIES,
    STANDING_MEANINGS,
    STANDING_NO_HARDWARE,
    STARTUP_GRACE_SECONDS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
)

from .helpers import setup_coordinator

PANEL = (
    Path(__file__).parents[1]
    / "custom_components" / "device_sentinel" / "frontend" / "panel.js"
)


def _house(hass: HomeAssistant, *, own: bool = True):
    """A ZHA door sensor carrying a Battery Notes battery entity."""
    zha = MockConfigEntry(domain="zha", title="ZHA")
    zha.add_to_hass(hass)
    # Loaded, as in a running house: a device whose integration is
    # still starting is given the startup window (ruling #367).
    zha.mock_state(hass, ConfigEntryState.LOADED)
    notes = MockConfigEntry(domain="battery_notes", title="Battery Notes")
    notes.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha.entry_id,
        identifiers={("zha", "door")},
        name="Door Sensor",
    )
    entities = er.async_get(hass)
    contact = None
    if own:
        contact = entities.async_get_or_create(
            "binary_sensor", "zha", "door_contact",
            device_id=device.id, config_entry=zha,
        ).entity_id
    note = entities.async_get_or_create(
        "sensor", "battery_notes", "door_battery_plus",
        device_id=device.id, config_entry=notes,
        original_device_class="battery",
    ).entity_id
    return device, contact, note


async def test_a_foreign_update_does_not_stamp_the_device(hass: HomeAssistant):
    device, contact, note = _house(hass)
    hass.states.async_set(contact, "off")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    before = (record[DEV_LAST_ACTIVITY], record[DEV_EVENT_COUNT])
    for level in ("80", "79", "78"):
        hass.states.async_set(note, level, {"device_class": "battery", "unit_of_measurement": "%"})
        await hass.async_block_till_done()
    assert (record[DEV_LAST_ACTIVITY], record[DEV_EVENT_COUNT]) == before
    hass.states.async_set(contact, "on")
    await hass.async_block_till_done()
    assert record[DEV_EVENT_COUNT] == before[1] + 1


async def test_a_foreign_update_feeds_no_burst(hass: HomeAssistant):
    device, contact, note = _house(hass)
    coord = await setup_coordinator(hass)
    fed = []
    real = coord._storm_feed
    coord._storm_feed = lambda *args, **kwargs: fed.append(args) or real(*args, **kwargs)
    hass.states.async_set(note, "80", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert fed == []
    hass.states.async_set(contact, "on")
    await hass.async_block_till_done()
    assert len(fed) == 1


async def test_a_foreign_value_does_not_hold_up_a_down_device(
    hass: HomeAssistant, freezer
):
    """Every entity of its own unavailable, Battery Notes still holding
    a level: the device is down, not up."""
    device, contact, note = _house(hass)
    hass.states.async_set(contact, "off")
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    # It has reported, so it is judged on its present state rather
    # than as a device that never spoke.
    hass.states.async_set(contact, "on")
    await hass.async_block_till_done()
    hass.states.async_set(contact, "unavailable")
    hass.states.async_set(note, "80", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    now = dt_util.utcnow().timestamp()
    assert coord._live_entity_states(device.id) == ["unavailable"]
    assert coord._device_down_category(device.id, record, now) == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_foreign_absence_says_nothing(hass: HomeAssistant):
    device, contact, note = _house(hass)
    coord = await setup_coordinator(hass)
    hass.states.async_set(note, "unavailable")
    await hass.async_block_till_done()
    assert note not in coord._pending_unavailable
    hass.states.async_set(contact, "unavailable")
    await hass.async_block_till_done()
    assert contact in coord._pending_unavailable


async def test_a_foreign_reading_is_still_read(hass: HomeAssistant):
    """A device that publishes no battery of its own keeps Battery
    Notes' level: the reading stays, only the liveness goes."""
    device, contact, note = _house(hass)
    hass.states.async_set(note, "64", {"device_class": "battery", "unit_of_measurement": "%"})
    coord = await setup_coordinator(hass)
    assert coord._battery_entity[device.id][0] == note
    assert coord._battery_own[device.id] is False


async def test_a_device_with_only_foreign_entities_is_set_aside(
    hass: HomeAssistant,
):
    device, _contact, _note = _house(hass, own=False)
    coord = await setup_coordinator(hass)
    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_NO_ENTITIES


async def test_battery_notes_stands_as_no_hardware(hass: HomeAssistant):
    device, contact, _note = _house(hass)
    coord = await setup_coordinator(hass)
    rows = {row["domain"]: row for row in coord.dashboard_integrations()}
    assert rows["battery_notes"]["standing"] == STANDING_NO_HARDWARE
    assert rows["battery_notes"]["adds_to"] == 1
    assert rows["zha"]["standing"] == "watched"
    assert coord.dashboard_integration("battery_notes") is None

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = Path(hass.config.path("device_sentinel", "classification.md")).read_text()
    assert "## Integrations With No Hardware (1)" in text
    assert "| battery_notes | 1 |" in text
    assert "no entities of its own" in text


async def test_an_excluded_integration_with_no_hardware_reads_excluded(
    hass: HomeAssistant,
):
    _house(hass)
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["battery_notes"]})
    rows = {row["domain"]: row for row in coord.dashboard_integrations()}
    assert rows["battery_notes"]["standing"] == "excluded"


async def test_the_brief_never_advises_excluding_it(hass: HomeAssistant):
    """Bursts Battery Notes logged before 0.22.21 would keep the advice
    alive for the whole window; it owns no device, so excluding it
    could do nothing."""
    _house(hass)
    coord = await setup_coordinator(hass)
    today = dt_util.now().date()
    coord.data[DATA_STORM_DAYS] = [
        {
            STORM_DAY_DOMAIN: "battery_notes",
            STORM_DAY_DATE: (today - timedelta(days=offset)).isoformat(),
            STORM_DAY_COUNT: FLOOD_MIN_STORMS + 5,
        }
        for offset in range(FLOOD_MIN_DAYS + 1)
    ]
    assert not any("battery_notes" in line or "Battery Notes" in line
                   for line in coord._noisy_integration_advice())


async def test_the_diagnostics_count_foreign_entities(hass: HomeAssistant):
    device, _contact, _note = _house(hass)
    coord = await setup_coordinator(hass)
    dump = await diagnostics.async_get_config_entry_diagnostics(hass, coord.entry)
    assert dump["devices"][device.id]["foreign_entities"] == {"battery_notes": 1}
    assert dump["classification"]["no_hardware_integrations"] == ["battery_notes"]
    assert dump["classification"]["foreign_entities"] == 1


def test_the_standing_key_is_one_text():
    """The Integrations tab and classification.md say the same thing."""
    panel = PANEL.read_text(encoding="utf-8")
    for standing, meaning in STANDING_MEANINGS:
        assert f"[{json.dumps(standing)}, {json.dumps(meaning)}]" in panel
