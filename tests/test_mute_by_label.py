# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_mute_by_label.py, Version: 0.27.10 (2026-10-27)

"""Mute by label from the device page, in Advanced (rule MUTE-09).

The label goes on the device and onto the kind's label list, the list
Settings writes, so every device carrying it is muted for that kind;
the picker says how many devices carry each label.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_LABELS,
    CONF_UNAVAILABLE_MUTED_LABELS,
)

from .helpers import register_device, setup_coordinator

_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


async def test_an_existing_label_mutes_every_device_carrying_it(hass: HomeAssistant, hass_ws_client):
    device, _ = register_device(hass, "lm0", "Porch Sensor")
    other, _ = register_device(hass, "lm1", "Shed Sensor")
    label = lr.async_get(hass).async_create("Outdoor")
    dr.async_get(hass).async_update_device(other.id, labels={label.label_id})
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    choices = (await _ws(client, type="device_sentinel/device_choices"))["result"]
    assert next(x for x in choices["labels"] if x["id"] == label.label_id)["devices"] == 1
    reply = await _ws(client, type="device_sentinel/device_label_mute", device_id=device.id, kind="battery",
                      label_id=label.label_id)
    assert reply["success"] and reply["result"] == {"label_id": label.label_id, "devices": 2}, reply
    await hass.async_block_till_done()
    assert label.label_id in dr.async_get(hass).async_get(device.id).labels
    assert coord.entry.options[CONF_BATTERY_MUTED_LABELS] == [label.label_id]
    assert coord.page_mutes(other.id)["battery"]["on"] is True
    assert coord.label_meaning(label.label_id) == "mutes battery"


async def test_a_new_label_is_made_and_muted(hass: HomeAssistant, hass_ws_client):
    device, _ = register_device(hass, "lm2", "Garage Door")
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_label_mute", device_id=device.id, kind="unavailable",
                      name="Seasonal")
    assert reply["success"], reply
    await hass.async_block_till_done()
    made = lr.async_get(hass).async_get_label_by_name("Seasonal")
    assert made is not None and coord.entry.options[CONF_UNAVAILABLE_MUTED_LABELS] == [made.label_id]


async def test_a_label_or_a_name_is_needed_and_a_reader_cannot(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
):
    device, _ = register_device(hass, "lm3", "Hall Sensor")
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_label_mute", device_id=device.id, kind="freeze")
    assert not reply["success"]
    reply = await _ws(client, type="device_sentinel/device_label_mute", device_id=device.id, kind="freeze", label_id="nope")
    assert reply["error"]["code"] == "refused"
    reply = await _ws(client, type="device_sentinel/device_label_mute", device_id="nobody", kind="freeze", name="X")
    assert reply["error"]["code"] == "not_found"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(reader, type="device_sentinel/device_label_mute", device_id=device.id, kind="freeze", name="X")
    assert not reply["success"]
