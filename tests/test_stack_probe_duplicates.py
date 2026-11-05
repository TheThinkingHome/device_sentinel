# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stack_probe_duplicates.py, Version: 0.28.3 (2026-11-04)

"""A stack probe line is written only when something changes, even
where one node is seen twice (rule STACK-12).

From a tester's house: each Tuya device appeared twice,
once in a live entry and once as an empty copy left by an older one,
and two dimmers shared the first eight characters of their Tuya id.
Keyed by the stack and those eight characters, the two views of each
node took turns, and the probe wrote 2,310 lines in three and a half
hours.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    PROBE_DEVICE_ID,
    PROBE_NOW,
    STUDIABLE,
)
from custom_components.device_sentinel.study_stacks import TUYA_DOMAIN

from .helpers import probe_lines, setup_coordinator

SCREEN_PORCH = "80154855aa01"
ENTRYWAY = "80154855bb02"
GARAGE = "eb7f8efe0001"


def _manager(*ids):
    return SimpleNamespace(
        device_map={node: SimpleNamespace(id=node, online=True, sub=False, category="tgq") for node in ids},
        mq=SimpleNamespace(client=SimpleNamespace(is_connected=lambda: True)),
    )


def _entry(hass, manager, title):
    entry = MockConfigEntry(domain=TUYA_DOMAIN, title=title)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(manager=manager)
    return entry


def _device(hass, entry, identifier, name, *, entity=True):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={identifier}, name=name,
    )
    if entity:
        er.async_get(hass).async_get_or_create(
            "sensor", TUYA_DOMAIN, f"{identifier[1]}-reading", device_id=device.id, config_entry=entry,
        )
    return device


async def _probe(hass):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[TUYA_DOMAIN]]})


async def test_two_devices_sharing_an_id_prefix_each_keep_their_own_line(hass: HomeAssistant):
    entry = _entry(hass, _manager(SCREEN_PORCH, ENTRYWAY), "Tuya")
    _device(hass, entry, (TUYA_DOMAIN, SCREEN_PORCH), "Screen Porch")
    _device(hass, entry, (TUYA_DOMAIN, ENTRYWAY), "Entryway")
    coord = await _probe(hass)
    coord.probe_tick(1000.0)
    first = len(probe_lines(coord))
    assert {row[PROBE_DEVICE_ID] for row in probe_lines(coord)} >= {"Screen Porch", "Entryway"}
    for minute in range(1, 6):
        coord.probe_tick(1000.0 + 60 * minute)
    assert len(probe_lines(coord)) == first


async def test_a_device_listed_by_two_entries_writes_nothing_while_nothing_changes(hass: HomeAssistant):
    """The live entry's device and the empty copy an older entry left
    each have their own line once, then nothing."""
    live = _entry(hass, _manager(GARAGE), "Tuya")
    old = _entry(hass, _manager(GARAGE), "Tuya (old)")
    _device(hass, live, (TUYA_DOMAIN, GARAGE), "Garage Temp and Humidity")
    # The copy carries the same Tuya id, registered in another shape, as
    # the registry keeps two devices apart only by their identifiers.
    _device(hass, old, (TUYA_DOMAIN, GARAGE, "copy"), "Garage Temp and Humidity (copy)", entity=False)
    coord = await _probe(hass)
    coord.probe_tick(1000.0)
    named = [row[PROBE_DEVICE_ID] for row in probe_lines(coord) if row[PROBE_DEVICE_ID].startswith("Garage")]
    assert sorted(named) == ["Garage Temp and Humidity", "Garage Temp and Humidity (copy)"]
    first = len(probe_lines(coord))
    for minute in range(1, 6):
        coord.probe_tick(1000.0 + 60 * minute)
    assert len(probe_lines(coord)) == first


async def test_a_change_on_one_copy_is_still_written(hass: HomeAssistant):
    manager = _manager(SCREEN_PORCH, ENTRYWAY)
    entry = _entry(hass, manager, "Tuya")
    _device(hass, entry, (TUYA_DOMAIN, SCREEN_PORCH), "Screen Porch")
    _device(hass, entry, (TUYA_DOMAIN, ENTRYWAY), "Entryway")
    coord = await _probe(hass)
    coord.probe_tick(1000.0)
    first = len(probe_lines(coord))
    manager.device_map[ENTRYWAY].online = False
    coord.probe_tick(1060.0)
    added = probe_lines(coord)[first:]
    assert [(row[PROBE_DEVICE_ID], row[PROBE_NOW]) for row in added] == [("Entryway", "offline")]
