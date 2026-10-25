# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_action_source.py, Version: 0.27.4 (2026-10-25)

"""Each action is logged with where it was done (rules BRIEF-07, DEV-07).

A sensor turned on, a power answer or a type set from a
Recommendations card was logged "from its device page", since the three
commands carried no source. They carry it now, as mutes do, and the
log says "from the Recommendations tab" or "from its device page".
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_DEVICE_PAGE,
    SYS_KIND,
)

from tests.helpers import setup_coordinator

_ids = iter(range(1, 10_000))


def _device(hass):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "r1")}, name="Router Zi",
        manufacturer="Example Radio Co", model="Range extender Zi", model_id="WG001")
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "sensor", "test", "r1_0", device_id=device.id, config_entry=source,
        original_device_class="signal_strength")
    reg.async_get_or_create(
        "sensor", "test", "r1_v", device_id=device.id, config_entry=source,
        original_device_class="voltage", suggested_object_id="router_zi_voltage",
        disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    return device


async def _send(client, **msg):
    await client.send_json({"id": next(_ids), **msg})
    reply = await client.receive_json()
    assert reply["success"], reply
    return reply


def _last_said(coord):
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    return coord._system_event_phrase(rows[-1])


async def test_each_command_says_where_it_was_pressed(hass: HomeAssistant, hass_ws_client):
    device = _device(hass)
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)

    await _send(client, type="device_sentinel/device_type", device_id=device.id,
                choice="Plug", source="recommendations")
    assert _last_said(coord).endswith("type set to Plug, from the Recommendations tab")
    await _send(client, type="device_sentinel/device_type", device_id=device.id,
                choice="Light")
    assert _last_said(coord).endswith("type set to Light, from its device page")

    await _send(client, type="device_sentinel/device_power", device_id=device.id,
                choice="Mains Powered", source="recommendations")
    assert _last_said(coord).endswith(", from the Recommendations tab")
    await _send(client, type="device_sentinel/device_power", device_id=device.id,
                choice="USB Powered", source="device_page")
    assert _last_said(coord).endswith(", from its device page")

    reply = await _send(client, type="device_sentinel/device_turn_on", device_id=device.id,
                        kind="voltage", source="recommendations")
    assert reply["result"]["enabled"] == 1
    assert _last_said(coord).endswith("turned on, from the Recommendations tab")

    # A later act with no source is the device page's again.
    await _send(client, type="device_sentinel/device_type", device_id=device.id,
                choice="Plug")
    assert _last_said(coord).endswith(", from its device page")


async def test_an_unknown_source_is_refused(hass: HomeAssistant, hass_ws_client):
    device = _device(hass)
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": next(_ids), "type": "device_sentinel/device_type",
                            "device_id": device.id, "choice": "Plug", "source": "elsewhere"})
    reply = await client.receive_json()
    assert not reply["success"]
