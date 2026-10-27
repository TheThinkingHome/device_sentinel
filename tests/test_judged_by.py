# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_judged_by.py, Version: 0.27.10 (2026-10-27)

"""How a device never judged for freezing is judged (rules FRZ-07, STACK-10).

A device a hub controls, a hub itself, and an ESPHome device judged by
its connection alone are never judged for freezing. Its page and its
Devices row carry "judged_by" in place of a window: by its hub, named,
with whether the hub has a Device Sentinel page, or by its connection.
A device judged by a window, or by being available, carries None.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .helpers import register_device, setup_coordinator
from .outage_helpers import arm, past_grace
from .test_esphome_connection import PIN as ESP_PIN
from .test_esphome_connection import _Runtime, _source
from .test_lutron_hub import _house, _past_grace


def _row(coord, device_id):
    return next(r for r in coord.dashboard_devices() if r["device_id"] == device_id)


async def test_a_device_a_watched_hub_controls_is_judged_by_it(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    arm(h.coord, h.kitchen.id)
    want = {"how": "hub", "hub_id": h.b_hub.id, "hub_name": "Basement Lutron Caseta", "hub_page": True}
    assert h.coord.dashboard_device(h.kitchen.id)["status"]["judged_by"] == want
    row = _row(h.coord, h.kitchen.id)
    assert row["judged_by"] == want
    assert (row["window"], row["window_learning"]) == (None, False)


async def test_a_hub_not_watched_still_judges_and_has_no_page_here(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer, hub_entity=False)
    await _past_grace(hass, freezer)
    assert h.b_hub.id not in h.coord._watched
    arm(h.coord, h.kitchen.id)
    judged = h.coord.dashboard_device(h.kitchen.id)["status"]["judged_by"]
    assert judged["how"] == "hub" and judged["hub_id"] == h.b_hub.id and judged["hub_page"] is False
    # Learned days, yet no window: the freeze check never judges it.
    row = _row(h.coord, h.kitchen.id)
    assert row["judged_by"]["hub_page"] is False
    assert (row["window"], row["window_learning"]) == (None, False)


async def test_a_hub_is_judged_by_its_connection(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    assert h.coord.dashboard_device(h.g_hub.id)["status"]["judged_by"] == {"how": "connection"}
    assert _row(h.coord, h.g_hub.id)["judged_by"] == {"how": "connection"}


async def test_an_esphome_device_judged_by_its_connection_with_learned_days(hass: HomeAssistant, freezer):
    freezer.move_to(ESP_PIN)
    source = _source(hass, _Runtime(False))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", "jb1")}, name="Proxy jb1")
    upd = er.async_get(hass).async_get_or_create(
        "update", "esphome", "jb1_u", device_id=device.id, config_entry=source,
        entity_category=EntityCategory.CONFIG).entity_id
    hass.states.async_set(upd, "off")
    coord = await setup_coordinator(hass)
    arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert coord._connection_only(device.id)
    status = coord.dashboard_device(device.id)["status"]
    assert status["judged_by"] == {"how": "connection"}
    assert status["window"] is None
    row = _row(coord, device.id)
    assert row["judged_by"] == {"how": "connection"} and row["window_learning"] is False


async def test_an_ordinary_device_carries_none(hass: HomeAssistant):
    device, _ = register_device(hass, "jb_plain", name="Door Plain")
    coord = await setup_coordinator(hass)
    assert coord.dashboard_device(device.id)["status"]["judged_by"] is None
    row = _row(coord, device.id)
    assert row["judged_by"] is None and row["window_learning"] is True


async def test_a_device_its_hub_judges_is_never_called_never_reported(hass: HomeAssistant, freezer):
    """A Pico nobody has pressed has no report, and is fine: its page
    reads reporting, never never reported (the device-page plan)."""
    from custom_components.device_sentinel.const import DATA_DEVICES, DEV_LAST_ACTIVITY

    h = await _house(hass, freezer)
    await _past_grace(hass, freezer)
    record = h.coord.data[DATA_DEVICES].setdefault(h.pico.id, {})
    record[DEV_LAST_ACTIVITY] = None
    assert h.coord._page_status(h.pico.id, record) != "never_reported"
