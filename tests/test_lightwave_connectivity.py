# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_lightwave_connectivity.py, Version: 0.30.0 (2026-11-21)

"""Lightwave devices judged by their Connectivity sensor (rule STACK-16).

Lightwave Smart gives each Smart Series device a Connectivity
sensor on its radio device ("<name> Device"), with the device's lights
and sockets registered via that radio device. The layout here is the
integration's own: the hub with its Cloud Link sensor, the radio device
with its LED indicator, firmware update and Connectivity sensor, and a
light registered via the radio device.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk

DOMAIN = "lightwave_smart"
HOUR = 3600.0


def _lightwave(hass, link_on=True):
    """Chris's layout: hub, radio device, and a dimmer registered via it."""
    source = MockConfigEntry(domain=DOMAIN)
    source.add_to_hass(hass)
    devices = dr.async_get(hass)
    reg = er.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(DOMAIN, "hub-fs")},
        name="LinkPlus",
        model="L2",
    )
    radio = devices.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(DOMAIN, "dev-1")},
        name="Office Light Device",
        model="L21",
    )
    # Set after creation: older Home Assistant takes no parent id here.
    radio = devices.async_update_device(radio.id, via_device_id=hub.id)
    light = devices.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(DOMAIN, "fs-1")},
        name="Office Light",
        model="L21",
    )
    light = devices.async_update_device(light.id, via_device_id=radio.id)
    ids = {}
    ids["cloud"] = reg.async_get_or_create(
        "binary_sensor", DOMAIN, "hub-fs_cloudLink",
        device_id=hub.id, config_entry=source, entity_category=EntityCategory.DIAGNOSTIC,
    ).entity_id
    ids["led"] = reg.async_get_or_create(
        "light", DOMAIN, "fs-1_rgbColor",
        device_id=radio.id, config_entry=source, entity_category=EntityCategory.CONFIG,
    ).entity_id
    ids["update"] = reg.async_get_or_create(
        "update", DOMAIN, "dev-1_firmware",
        device_id=radio.id, config_entry=source, entity_category=EntityCategory.DIAGNOSTIC,
    ).entity_id
    ids["link"] = reg.async_get_or_create(
        "binary_sensor", DOMAIN, "dev-1_connectivity",
        device_id=radio.id, config_entry=source, entity_category=EntityCategory.DIAGNOSTIC,
        disabled_by=None if link_on else er.RegistryEntryDisabler.USER,
    ).entity_id
    ids["dimmer"] = reg.async_get_or_create(
        "light", DOMAIN, "fs-1_switch", device_id=light.id, config_entry=source,
    ).entity_id
    return hub, radio, light, ids


async def _house(hass, freezer, link_on=True):
    freezer.move_to(PIN)
    hub, radio, light, ids = _lightwave(hass, link_on=link_on)
    hass.states.async_set(ids["cloud"], "on")
    hass.states.async_set(ids["led"], "on")
    hass.states.async_set(ids["update"], "off")
    hass.states.async_set(ids["dimmer"], "off")
    if link_on:
        hass.states.async_set(ids["link"], "on")
    coord = await setup_coordinator(hass)
    records = {
        "radio": arm(coord, radio.id, rhythm=2 * HOUR),
        "light": arm(coord, light.id, rhythm=2 * HOUR),
    }
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    # Each reports once, so each has a last report to be silent from.
    hass.states.async_set(ids["dimmer"], "on")
    hass.states.async_set(ids["led"], "off")
    await hass.async_block_till_done()
    return coord, {"hub": hub, "radio": radio, "light": light}, ids, records


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]


async def test_link_off_takes_down_the_device_and_its_light(hass: HomeAssistant, freezer):
    """A circuit switched off: both unavailable, then both back, dated from the change."""
    coord, dev, ids, records = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)
    heard = records["light"][DEV_LAST_ACTIVITY]

    assert coord._node_status_entity[dev["light"].id] == ids["link"]
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    for name in ("radio", "light"):
        assert records[name][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, name
        assert len(_mine(faults, dev[name].id)) == 1, name
    assert records["light"][DEV_LAST_ACTIVITY] == heard, "off was taken as the light speaking"

    await walk(hass, freezer, 45 * 60)
    hass.states.async_set(ids["link"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    for name in ("radio", "light"):
        assert records[name][DEV_FROZEN_CATEGORY] is None, name
        back = _mine(recoveries, dev[name].id)
        assert len(back) == 1, name
        assert 55 * 60 <= back[0]["down_for"] <= 65 * 60, name


async def test_unreadable_link_keeps_the_last_word(hass: HomeAssistant, freezer):
    """The hub's link lost, or Home Assistant's session down: off still stands."""
    coord, dev, ids, records = await _house(hass, freezer)
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert records["light"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_reachable_dimmer_is_never_called_frozen(hass: HomeAssistant, freezer):
    """A dimmer nobody uses, silent twice its window, its hub reaching it."""
    coord, dev, ids, records = await _house(hass, freezer)
    assert coord._freeze_window(records["light"]) < 4 * HOUR
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert records["light"][DEV_FROZEN_CATEGORY] is None
    assert records["radio"][DEV_FROZEN_CATEGORY] is None


async def test_freeze_rule_stands_when_the_link_says_nothing(hass: HomeAssistant, freezer):
    """A Connectivity sensor reading unavailable spares nothing."""
    coord, dev, ids, records = await _house(hass, freezer)
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert records["light"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_link_switched_off_says_nothing(hass: HomeAssistant, freezer):
    """A Connectivity sensor switched off: the light is judged by its clock."""
    coord, dev, ids, records = await _house(hass, freezer, link_on=False)
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert records["light"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_cloud_link_is_not_a_device_link(hass: HomeAssistant, freezer):
    """The hub's Cloud Link is not read as any device's link."""
    coord, dev, ids, records = await _house(hass, freezer)
    assert ids["cloud"] not in coord._node_status_ids
    hass.states.async_set(ids["cloud"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert records["light"][DEV_FROZEN_CATEGORY] is None
    assert records["radio"][DEV_FROZEN_CATEGORY] is None


async def test_no_z_wave_status_row_or_card(hass: HomeAssistant, freezer):
    """The page's Z-Wave status row and the switched-off card stay Z-Wave's."""
    coord, dev, ids, records = await _house(hass, freezer)
    assert coord._node_status_view(dev["radio"].id) is None
    assert coord._node_status_view(dev["light"].id) is None
    entry = er.async_get(hass).async_get(ids["link"])
    assert not coord._is_node_status_entry(entry)


async def test_a_radio_device_with_only_its_link_is_never_called_never_reported(hass: HomeAssistant, freezer):
    """The beta's radio device carries only its Connectivity sensor and a
    firmware notice. Its link reading on for two days is its hub hearing
    it, so it is not called never reported; off still takes it down
    (rule STACK-16)."""
    freezer.move_to(PIN)
    hub, radio, light, ids = _lightwave(hass)
    er.async_get(hass).async_remove(ids["led"])
    for key in ("cloud", "link"):
        hass.states.async_set(ids[key], "on")
    hass.states.async_set(ids["update"], "off")
    hass.states.async_set(ids["dimmer"], "off")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record = coord.data[DATA_DEVICES][radio.id]
    await walk(hass, freezer, 50 * HOUR, step=1800)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert coord.data[DATA_DEVICES][light.id][DEV_FROZEN_CATEGORY] is None
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
