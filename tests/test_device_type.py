# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_type.py, Version: 0.25.1 (2026-10-08)

"""What each device is (0.25.1, Project__Device_Type.md).

The rules read a device's own entities, first match wins, in the order
James approved on 8 October 2026 after they were run on the reference
rig's 103 devices. The owner's answer wins and covers the model, as the
Power row's does. Where it is stored is tested in test_answers_store.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import device_type
from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    SYS_DEVICE_PAGE,
    SYS_KIND,
)
from custom_components.device_sentinel.device_type import type_from_entities
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from .helpers import setup_coordinator

_ids = iter(range(1, 10_000))


def _e(domain, device_class=None, category=None, disabled=None):
    return SimpleNamespace(domain=domain, device_class=None, original_device_class=device_class,
                           entity_category=category, disabled_by=disabled)


# ---------------------------------------------------------------- the rules

@pytest.mark.parametrize(("entities", "expected"), [
    # Seen on the reference rig, 8 October 2026.
    ([_e("camera"), _e("switch"), _e("binary_sensor", "motion")], "Camera"),
    ([_e("assist_satellite"), _e("light"), _e("media_player", "speaker")], "Voice Assistant"),
    ([_e("cover", "shade"), _e("sensor", "signal_strength")], "Cover"),
    ([_e("cover", "blind")], "Cover"),
    ([_e("cover")], "Cover"),
    ([_e("binary_sensor", "moisture"), _e("switch", category=EntityCategory.CONFIG)], "Leak Sensor"),
    ([_e("binary_sensor", "door"), _e("sensor", "temperature")], "Door/Window Sensor"),
    ([_e("binary_sensor", "window")], "Door/Window Sensor"),
    ([_e("binary_sensor", "vibration")], "Vibration Sensor"),
    ([_e("binary_sensor", "occupancy"), _e("sensor", "illuminance")], "Motion Sensor"),
    ([_e("binary_sensor", "motion")], "Motion Sensor"),
    ([_e("binary_sensor", "presence")], "Presence Sensor"),
    ([_e("binary_sensor", "smoke"), _e("binary_sensor", "carbon_monoxide")], "Smoke Alarm"),
    ([_e("binary_sensor", "carbon_monoxide")], "CO Alarm"),
    ([_e("switch"), _e("sensor", "power"), _e("sensor", "energy")], "Plug"),
    ([_e("switch"), _e("select", category=EntityCategory.CONFIG)], "Switch"),
    ([_e("light")], "Switch"),
    ([_e("sensor", "moisture"), _e("sensor", "temperature")], "Soil Sensor"),
    ([_e("sensor", "temperature"), _e("sensor", "humidity")], "Temperature Sensor"),
    ([_e("event", "button"), _e("sensor", "battery", category=EntityCategory.DIAGNOSTIC)], "Button"),
    # The SLZB-06's settings switches say nothing about what it is.
    ([_e("switch", "switch", category=EntityCategory.CONFIG), _e("binary_sensor", "connectivity",
      category=EntityCategory.DIAGNOSTIC)], None),
    ([_e("sensor", "signal_strength")], None),
    ([_e("binary_sensor", "moisture", disabled="user"), _e("switch")], "Switch"),
    ([], None),
])
def test_a_type_is_read_from_the_main_entities_first_match_wins(entities, expected):
    assert type_from_entities(entities) == expected


# ---------------------------------------------------------------- the house

_SOURCE = {}


def _device(hass, uid, name, entities, maker="Third Reality", model="Zigbee / BLE smart plug", model_id="3RSP019BZ"):
    if "source" not in _SOURCE or _SOURCE["source"][0] is not hass:
        entry = MockConfigEntry(domain="test", title="Source")
        entry.add_to_hass(hass)
        _SOURCE["source"] = (hass, entry)
    source = _SOURCE["source"][1]
    from homeassistant.config_entries import ConfigEntryState
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=name,
        manufacturer=maker, model=model, model_id=model_id,
    )
    registry = er.async_get(hass)
    for index, (domain, device_class) in enumerate(entities):
        registry.async_get_or_create(domain, "test", f"{uid}_{index}", device_id=device.id,
                                     config_entry=source, original_device_class=device_class)
    return device


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


async def _plugs(hass, hass_ws_client):
    first = _device(hass, "p1", "Plug Master Router", [("switch", None), ("sensor", "signal_strength")])
    second = _device(hass, "p2", "Plug Laundry Router", [("switch", None)])
    leak = _device(hass, "l1", "Leak Kitchen Sink", [("binary_sensor", "moisture")], maker="Aqara",
                   model="Water leak sensor", model_id="SJCGQ11LM")
    radio = _device(hass, "r1", "Router Aotec Zi", [("sensor", "signal_strength")], maker="Aeotec",
                    model="Range extender Zi", model_id="WG001")
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    return coord, client, first, second, leak, radio


async def test_the_page_and_the_devices_tab_show_what_the_entities_say(hass: HomeAssistant, hass_ws_client):
    coord, _client, first, _second, leak, radio = await _plugs(hass, hass_ws_client)
    assert coord.dashboard_device(first.id)["identity"]["type"]["words"] == "Switch"
    assert coord.dashboard_device(first.id)["identity"]["type"]["source"] == "entities"
    unknown = coord.dashboard_device(radio.id)["identity"]["type"]
    assert unknown["words"] is None and unknown["source"] is None and "Other" in unknown["choices"]
    rows = {row["device_id"]: row["type"] for row in coord.dashboard_devices()}
    assert rows[leak.id] == "Leak Sensor" and rows[radio.id] is None


async def test_the_pencil_covers_the_model_and_says_so_in_the_brief(hass: HomeAssistant, hass_ws_client):
    coord, client, first, second, _leak, _radio = await _plugs(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_type", device_id=first.id, choice="Plug")
    assert reply["success"], reply
    for device in (first, second):
        view = coord.dashboard_device(device.id)["identity"]["type"]
        assert (view["words"], view["source"], view["auto"]) == ("Plug", "owner", "Switch")
    assert coord.dashboard_device(second.id)["identity"]["type"]["set_on_name"] == "Plug Master Router"
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    assert coord._system_event_phrase(rows[-1]) == "type set to Plug, for all 2 devices of this model, from its device page"
    reply = await _ws(client, type="device_sentinel/device_type", device_id=second.id, choice=None)
    assert reply["success"], reply
    assert coord.dashboard_device(first.id)["identity"]["type"]["words"] == "Switch"
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    assert coord._system_event_phrase(rows[-1]).startswith("type entry removed, Switch from its entities used")


async def test_own_words_are_tidied_and_bad_answers_refused(hass: HomeAssistant, hass_ws_client):
    coord, client, _first, _second, _leak, radio = await _plugs(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_type", device_id=radio.id, choice="Other", other="  Zigbee   router ")
    assert reply["success"], reply
    assert coord.type_words(radio.id) == "Zigbee router"
    for other, words in (("", "Type what the device is."), ("x" * 41, "Keep it to 40 characters."),
                         ("bad‮word", "That text holds characters that cannot be shown."),
                         # The page's own words for no type (found by testing).
                         ("Not known", "Type what the device is."), ("  not   KNOWN ", "Type what the device is.")):
        reply = await _ws(client, type="device_sentinel/device_type", device_id=radio.id, choice="Other", other=other)
        assert reply["error"]["code"] == "refused" and reply["error"]["message"] == words
    reply = await _ws(client, type="device_sentinel/device_type", device_id=radio.id, choice="Toaster")
    assert reply["error"]["message"] == "Choose from the list."
    reply = await _ws(client, type="device_sentinel/device_type", device_id="nope", choice="Plug")
    assert reply["error"]["code"] == "not_found"


async def test_a_non_admin_cannot_set_a_type(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    _coord, _client, first, *_ = await _plugs(hass, hass_ws_client)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(client, type="device_sentinel/device_type", device_id=first.id, choice="Plug")
    assert reply["error"]["code"] == "unauthorized"


async def test_a_removed_device_takes_its_own_answer_and_passes_on_the_models(hass: HomeAssistant, hass_ws_client):
    coord, client, first, second, _leak, radio = await _plugs(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_type", device_id=first.id, choice="Plug")
    await _ws(client, type="device_sentinel/device_type", device_id=radio.id, choice="Other", other="Zigbee router")
    coord._type_forget(first.id)
    coord._type_forget(radio.id)
    key = coord._power_key(second.id)
    assert coord._type_models[key]["device_id"] == second.id
    assert radio.id not in coord._type_entries


async def test_the_diagnostics_carry_each_devices_type_and_its_source(hass: HomeAssistant, hass_ws_client):
    coord, client, first, _second, leak, radio = await _plugs(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_type", device_id=first.id, choice="Plug")
    payload = await async_get_config_entry_diagnostics(hass, coord.entry)
    devices = payload["devices"]
    assert devices[first.id]["type"] == {"words": "Plug", "source": "owner", "from_entities": "Switch"}
    assert devices[leak.id]["type"] == {"words": "Leak Sensor", "source": "entities", "from_entities": "Leak Sensor"}
    assert devices[radio.id]["type"] == {"words": None, "source": None, "from_entities": None}


def test_the_choices_are_the_approved_types_then_other():
    assert device_type.TYPE_CHOICES[-1] == "Other"
    assert set(device_type.TYPE_CHOICES[:-1]) == {
        "Camera", "Voice Assistant", "Cover", "Leak Sensor", "Door/Window Sensor",
        "Vibration Sensor", "Motion Sensor", "Presence Sensor", "Smoke Alarm", "CO Alarm",
        "Switch", "Plug", "Soil Sensor", "Temperature Sensor", "Button",
    }


async def test_clearing_a_devices_own_answer_leaves_the_models(hass: HomeAssistant, hass_ws_client):
    """An answer set before the device reported a model is its own; clearing
    it cleared the model's answer for every device too (found by review)."""
    coord, _client, first, second, _leak, radio = await _plugs(hass, hass_ws_client)
    coord.page_set_type(radio.id, "Other", "Range extender")
    coord._type_entries[first.id] = {"type": "Lamp", "set": None}
    coord.page_set_type(second.id, "Button")
    assert coord.type_words(first.id) == "Lamp"
    coord.page_set_type(first.id, None)
    assert coord.type_words(first.id) == "Button" and coord.type_words(second.id) == "Button"
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    assert coord._system_event_phrase(rows[-1]) == "type entry removed, the model's Button used, from its device page"
    coord.page_set_type(first.id, None)
    assert coord.type_words(second.id) == "Switch", "a second clear leaves the model's answer"


async def test_lists_never_count_the_model_per_row(hass: HomeAssistant, hass_ws_client, monkeypatch):
    """Each row with an owner answer counted every device of its model and
    threw the count away: the square of the house per Devices tab, brief
    and download (found by review). Only the device page counts."""
    coord, _client, first, *_ = await _plugs(hass, hass_ws_client)
    coord.page_set_type(first.id, "Plug")
    coord.page_set_power(first.id, "Mains Powered")
    calls = []
    original = type(coord)._power_same_model
    monkeypatch.setattr(type(coord), "_power_same_model", lambda self, *a, **k: calls.append(1) or original(self, *a, **k))
    coord.dashboard_devices()
    coord.device_recommendations()
    await async_get_config_entry_diagnostics(hass, coord.entry)
    assert calls == []
    assert coord.dashboard_device(first.id)["identity"]["type"]["covers"] == 2
    assert coord.dashboard_device(first.id)["identity"]["power"]["covers"] == 2
