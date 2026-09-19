# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_stage3.py, Version: 0.22.3 (2026-09-19)

"""The Integrations tab and each integration's page.

One row per integration that owns a device: its standing, its counts,
and its outages. A bridge's outage belongs to the integration that
carries it, so a Zigbee2MQTT drop is counted against MQTT. The page
lists the integration's devices, problems first, its outages over the
last fourteen days, and any recommendation that names it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WORST,
)

from tests.helpers import setup_coordinator


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _device(hass, entry, uid, name):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(entry.domain, uid)}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "binary_sensor", entry.domain, uid, device_id=device.id, config_entry=entry
    )
    return device


async def _house(hass):
    mqtt = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt.add_to_hass(hass)
    ping = MockConfigEntry(domain="ping", title="Ping")
    ping.add_to_hass(hass)
    soil = _device(hass, mqtt, "soil", "Soil Irrigation (Monstera)")
    door = _device(hass, mqtt, "door", "Door Entryway")
    _device(hass, ping, "laptop", "James Laptop")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["ping"]})
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_WHEN: now - 20 * 86400, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"},
        {SYS_WHEN: now - 20 * 86400 + 60, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m", SYS_DURATION: 60.0},
        {SYS_WHEN: now - 3600, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"},
        {SYS_WHEN: now - 3600 + 2754, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m",
         SYS_DURATION: 2754.0, SYS_DEVICES: 77, SYS_WORST: 75},
    ]
    coord.data[DATA_TODO_ITEMS] = [{
        "uid": "u1", "device_id": soil.id, "summary": "Soil Irrigation (Monstera): battery 0%",
        "description": "", "status": "needs_action", "acked_at": None,
        "sort_name": "Soil Irrigation (Monstera)", "kinds": {"low_battery": now - 86400},
    }]
    return coord, soil, door


async def test_one_row_per_integration_with_its_standing(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/integrations")
    assert reply["success"], reply
    rows = {row["domain"]: row for row in reply["result"]["rows"]}
    mqtt = rows["mqtt"]
    assert mqtt["standing"] == "watched"
    assert mqtt["watched"] == 2
    assert mqtt["problems"] == 1
    assert mqtt["outages"] == 1, "the 20-day-old outage is outside fourteen days"
    assert rows["ping"]["standing"] == "excluded"
    assert rows["ping"]["set_aside"] == 1
    assert rows["ping"]["watched"] == 0


async def test_an_integrations_page(hass: HomeAssistant, hass_ws_client):
    _, soil, door = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/integration", domain="mqtt")
    assert reply["success"], reply
    page = reply["result"]
    assert page["domain"] == "mqtt"
    assert page["standing"] == "watched"
    names = [device["name"] for device in page["devices"]]
    assert names[0] == "Soil Irrigation (Monstera)", "problems first"
    assert page["devices"][0]["problem"] == "battery 0%"
    assert "Door Entryway" in names
    assert len(page["outages"]) == 1
    outage = page["outages"][0]
    assert outage["what"] == "Bridge: Zigbee2MQTT"
    assert outage["duration"] == 2754.0
    assert outage["devices"] == 77
    assert outage["worst"] == 75
    assert page["bursts"] == 0
    assert isinstance(page["recommendations"], list)


async def test_an_outage_still_open_is_listed_as_such(hass: HomeAssistant, hass_ws_client):
    coord, _, _ = await _house(hass)
    coord.data[DATA_SYSTEM_EVENTS].append(
        {SYS_WHEN: dt_util.utcnow().timestamp() - 120, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"}
    )
    client = await hass_ws_client(hass)
    outages = (await _call(client, type="device_sentinel/integration", domain="mqtt"))["result"]["outages"]
    assert outages[0]["duration"] is None
    assert outages[0]["open"] is True


async def test_an_unknown_integration_is_not_found(hass: HomeAssistant, hass_ws_client):
    await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/integration", domain="nothing_here")
    assert reply["error"]["code"] == "not_found"


async def test_both_are_admin_only(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await _house(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "device_sentinel/integrations"},
        {"type": "device_sentinel/integration", "domain": "mqtt"},
    ):
        assert (await _call(client, **message))["error"]["code"] == "unauthorized"
