# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_cached_values_dashboard.py, Version: 0.29.1 (2026-11-14)

"""The dashboard's commands and the settings field for integrations and
models that report cached values after a restart (rule WATCH-12).

A model is set and a device confirmed back through the dashboard's own
commands, with the Home Assistant user who pressed named; and the
Advanced screen saves a person's ticks as changes to the list, never
the list itself.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    CONF_CACHED_ADDED,
    CONF_CACHED_INTEGRATIONS,
    CONF_CACHED_REMOVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_HELD_VALUES,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from custom_components.device_sentinel.restart_values import CASE_CONFIRMED

from tests.helpers import setup_coordinator
from tests.outage_helpers import entry_of, rec
from tests.test_cached_values_after_restart import LISTED, LIVE, device_on


async def _waiting_now(hass, hass_ws_client):
    """A device on the list, judged unavailable and on watch, with its
    values showing: the state the first note is for."""
    device, eids = device_on(hass, LISTED, "plug")
    other, other_eids = device_on(hass, LIVE, "speaker", maker="Bolt", model="Two")
    for eid in (*eids, *other_eids):
        hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    record = rec(coord, device.id)
    keys = {er.async_get(hass).async_get(eid).id: "on" for eid in eids}
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNAVAILABLE
    record[DEV_FROZEN_SINCE] = 1.0
    record[DEV_HELD_VALUES] = keys
    coord._on_watch[device.id] = set(keys)
    assert coord.restart_pending(device.id)
    return coord, await hass_ws_client(hass), device, other


async def _ws(client, **message):
    _ws.n = getattr(_ws, "n", 0) + 1
    await client.send_json({"id": _ws.n, **message})
    return await client.receive_json()


async def test_the_dashboard_sets_a_model_and_confirms_a_device(hass: HomeAssistant, hass_ws_client):
    coord, client, device, other = await _waiting_now(hass, hass_ws_client)
    page = await _ws(client, type="device_sentinel/device", device_id=device.id)
    restart = page["result"]["identity"]["actions"]["restart"]
    assert restart["note"]["name"] == "Back after a restart?" and restart["mode"] is None
    reply = await _ws(client, type="device_sentinel/device_restart", device_id=device.id, mode="sometimes")
    assert not reply["success"]
    reply = await _ws(client, type="device_sentinel/device_confirm_back", device_id=other.id)
    assert reply["error"]["code"] == "refused"
    assert reply["error"]["message"] == "This device is no longer waiting to be confirmed."
    reply = await _ws(client, type="device_sentinel/device_confirm_back", device_id="nope")
    assert reply["error"]["code"] == "not_found"
    reply = await _ws(client, type="device_sentinel/device_confirm_back", device_id=device.id)
    assert reply["success"], reply
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(coord._restart_cases(CASE_CONFIRMED)) == 1
    # The Home Assistant user who pressed it is the one named.
    assert coord.confirming(device.id) == "confirmed working by Mock User"
    reply = await _ws(client, type="device_sentinel/device_restart", device_id=other.id, mode="cached",
                      source="recommendations")
    assert reply["success"] and coord._reports_cached(other.id)
    reply = await _ws(client, type="device_sentinel/device_restart", device_id=other.id, mode="same")
    assert reply["success"] and not coord._reports_cached(other.id)
    cards = await _ws(client, type="device_sentinel/recommendations")
    assert cards["success"]


async def test_the_settings_screen_saves_changes_not_the_list(hass: HomeAssistant, hass_ws_client):
    coord, _client, device, other = await _waiting_now(hass, hass_ws_client)
    entry = entry_of(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "advanced"})
    schema = flow["data_schema"].schema
    field = next(key for key in schema if str(key) == CONF_CACHED_INTEGRATIONS)
    assert field.default() == [LISTED]
    assert {option["value"] for option in schema[field].config["options"]} == {LISTED, LIVE}
    await hass.config_entries.options.async_configure(flow["flow_id"], {CONF_CACHED_INTEGRATIONS: [LIVE]})
    await hass.async_block_till_done()
    assert entry.options[CONF_CACHED_ADDED] == [LIVE]
    assert entry.options[CONF_CACHED_REMOVED] == [LISTED]
    assert CONF_CACHED_INTEGRATIONS not in entry.options
    assert coord._reports_cached(other.id) and not coord._reports_cached(device.id)
    # Unticked, the device waiting on it is judged on what it shows.
    assert not coord._on_watch.get(device.id)
