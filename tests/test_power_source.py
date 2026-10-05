# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_power_source.py, Version: 0.24.7 (2026-10-05)

"""What powers each device (0.24.7, Project__0_24_7.md).

The owner's entry first, then the Battery Notes library shipped inside
Device Sentinel, otherwise "Not known". The pencil is on the device
page only; the report button opens Battery Notes' New Device form,
filled in.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlsplit

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel import power_source
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_BATTERY_VALUE,
    EVENT_FAULT,
    SYS_DETAIL,
    SYS_DEVICE_PAGE,
    SYS_KIND,
    TODO_DEVICE_ID,
    TODO_KIND_LOW_BATTERY,
    TODO_KINDS,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
)
from custom_components.device_sentinel.power_source import (
    POWER_STORE_KEY,
    BatteryLibrary,
    clean_other,
    load_library,
)

from .helpers import register_device, setup_coordinator, setup_entry

_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


def _made_by(hass, device, maker, model, model_id=None, hw=None):
    dr.async_get(hass).async_update_device(
        device.id, manufacturer=maker, model=model, model_id=model_id, hw_version=hw
    )


async def _setup(hass, hass_ws_client, maker="Third Reality", model="Smart button", model_id="3RSB22BZ", hw="0"):
    device, _entities = register_device(hass, "pw0", "Button Randy Night Table")
    _made_by(hass, device, maker, model, model_id, hw)
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    return coord, client, device


def _page_rows(coord):
    return [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r[SYS_KIND] == SYS_DEVICE_PAGE]


# ------------------------------------------------------------ the matcher

LIB = BatteryLibrary([
    {"manufacturer": "Aqara", "model": "Door and window sensor", "model_id": "MCCGQ11LM",
     "hw_version": "2", "battery_type": "CR1632"},
    {"manufacturer": "IKEA", "model": "TRADFRI remote", "battery_type": "CR2032"},
    {"manufacturer": "Apple", "model": "iPad", "battery_type": "Rechargeable", "model_match_method": "startswith"},
    {"manufacturer": "Acme", "model": "Twin", "battery_type": "AAA", "battery_quantity": 2},
    {"manufacturer": "Acme", "model": "Twin", "battery_type": "AA", "battery_quantity": 2},
    {"manufacturer": "Acme", "model": "Same", "battery_type": "AAA", "battery_quantity": 3},
    {"manufacturer": "Acme", "model": "Same", "battery_type": "AAA", "battery_quantity": 3},
    {"manufacturer": "Acme", "model": "Variants", "battery_type": "MANUAL"},
    {"manufacturer": "Zed", "model": "Plug", "model_id": "Z1", "battery_type": "CR2"},
    {"manufacturer": "Zed", "model": "Plug", "battery_type": "CR2450"},
])


def test_the_matcher_follows_battery_notes_rules():
    assert LIB.match("aqara", "door AND window sensor", "mccgq11lm", "2").words == "CR1632"
    assert LIB.match("Aqara", "Door and window sensor", "MCCGQ11LM", None) is None, "its entry needs version 2"
    assert LIB.match("Aqara", "Door and window sensor", "MCCGQ11LM", "1") is None
    assert LIB.match("IKEA", "TRADFRI remote").words == "CR2032"
    assert LIB.match("IKEA", "TRADFRI remote", "E1524") .words == "CR2032", "a generic entry is a fallback"
    assert LIB.match("Apple", "iPad Pro 11").words == "Rechargeable"
    assert LIB.match("Acme", "Twin") is None, "two answers that disagree give none"
    assert LIB.match("Acme", "Same").words == "3× AAA", "identical duplicates still answer"
    assert LIB.match("Acme", "Variants") is None, "MANUAL is skipped, as in Battery Notes"
    assert LIB.match("Zed", "Plug", "Z1").words == "CR2"
    assert LIB.match("Zed", "Plug").words == "CR2450"
    assert LIB.match(None, "Plug") is None and LIB.match("Nobody", "Plug") is None


def test_the_shipped_library_loads_and_a_damaged_one_does_not_stop(tmp_path, caplog):
    library = load_library()
    assert library is not None and library.size > 2000
    assert library.match("Aqara", "Door and window sensor", "MCCGQ11LM", "2").words == "CR1632"
    bad = tmp_path / "battery_library.json"
    bad.write_text("{ not json")
    assert load_library(bad) is None
    bad.write_text(json.dumps({"devices": "nope"}))
    assert load_library(bad) is None
    assert load_library(tmp_path / "missing.json") is None
    assert "cannot read its battery library" in caplog.text


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "Type the battery"),
        ("   ", "Type the battery"),
        ("A" * 41, "40 characters"),
        ("CR2032\u0000", "cannot be shown"),
        ("CR\u202e2032", "cannot be shown"),
        ("CR\u200b2032", "cannot be shown"),
    ],
)
def test_other_text_is_refused_with_a_reason(text, reason):
    with pytest.raises(ValueError, match=reason):
        clean_other(text)


def test_other_text_is_tidied_and_markup_stays_text():
    assert clean_other("  9V   lithium ") == "9V lithium"
    assert clean_other("<b>LR44</b>") == "<b>LR44</b>"


# ------------------------------------------------------------ the order


async def test_the_library_answers_then_the_owner_then_not_known(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Aqara", "Door and window sensor", "MCCGQ11LM", "2")
    view = coord.power_view(device.id)
    assert (view["words"], view["source"], view["report_url"]) == ("CR1632", "library", None)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="AAA", quantity=2)
    assert reply["success"], reply
    view = coord.power_view(device.id)
    assert (view["words"], view["source"], view["library"]) == ("2× AAA", "owner", "CR1632")
    assert view["report_url"], "a correction is offered to Battery Notes"
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice=None)
    assert reply["success"], reply
    assert coord.power_view(device.id)["words"] == "CR1632"
    details = [r[SYS_DETAIL] for r in _page_rows(coord)]
    assert details == [
        "power set to 2× AAA, from its device page",
        "power entry removed, the library's CR1632 used, from its device page",
    ]
    other, _ = register_device(hass, "pw9", "Mystery")
    assert coord.power_view(other.id)["words"] == "Not known"
    assert coord.power_view(other.id)["source"] is None


async def test_mains_and_usb_take_no_quantity_and_no_report(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Aqara", "Presence sensor FP2", None, None)
    for choice in ("Mains Powered", "USB Powered"):
        reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice=choice, quantity=3)
        assert reply["success"], reply
        view = coord.power_view(device.id)
        assert view["words"] == choice and view["entry"]["quantity"] is None
        assert view["report_url"] is None


async def test_choices_out_of_bounds_are_refused(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    for payload in (
        {"choice": "AAAA"},
        {"choice": "AAA", "quantity": 0},
        {"choice": "AAA", "quantity": 9},
        {"choice": "Other", "other": ""},
        {"choice": "Other", "other": "x" * 200},
        {"choice": "Other", "other": "AA\u202e"},
    ):
        reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, **payload)
        assert reply["error"]["code"] == "refused", (payload, reply)
    assert coord.power_view(device.id)["source"] is None, "a refusal saved something"
    assert _page_rows(coord) == []
    reply = await _ws(client, type="device_sentinel/device_power", device_id="no-such-device", choice="AA")
    assert reply["error"]["code"] == "not_found"


async def test_a_non_admin_cannot_set_power(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    coord, _client, device = await _setup(hass, hass_ws_client)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="AA")
    assert reply["error"]["code"] == "unauthorized"
    assert coord.power_view(device.id)["source"] is None


# ------------------------------------------------------------ the report link


async def test_the_report_link_fills_battery_notes_form(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Third Reality", "Smart button", "3RSB22BZ", "0")
    assert coord.power_view(device.id)["words"] == "Not known", "the library lacks this button"
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id,
                      choice="Other", other="CR2032 & co", quantity=1)
    assert reply["success"], reply
    url = coord.power_view(device.id)["report_url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == power_source.REPORT_FORM
    assert dict(parse_qsl(parts.query)) == {
        "template": "new_device_request.yaml",
        "manufacturer": "Third Reality",
        "model": "Smart button",
        "model_id": "3RSB22BZ",
        "battery_type": "CR2032 & co",
        "battery_quantity": "1",
    }
    assert "&co" not in url and " " not in url, "values must be encoded"


async def test_no_link_without_a_maker_or_when_it_says_what_the_library_says(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Aqara", "Door and window sensor", "MCCGQ11LM", "2")
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="Other", other="CR1632")
    assert reply["success"], reply
    assert coord.power_view(device.id)["report_url"] is None, "nothing new to report"
    _made_by(hass, device, None, None)
    await hass.async_block_till_done()
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="AA")
    assert reply["success"], reply
    assert coord.power_view(device.id)["report_url"] is None, "the form refuses a device with no maker"


# ------------------------------------------------------------ its own file


async def test_entries_live_in_their_own_file_and_survive_a_restart(hass: HomeAssistant, hass_storage, hass_ws_client, freezer):
    device, _ = register_device(hass, "pw1", "Door Bath Main")
    entry = await setup_entry(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="CR2032", quantity=2)
    assert reply["success"], reply
    freezer.tick(5)
    await hass.async_block_till_done()
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    saved = hass_storage[POWER_STORE_KEY]["data"]["devices"][device.id]
    assert (saved["kind"], saved["type"], saved["quantity"]) == ("battery", "CR2032", 2)
    main = json.dumps(hass_storage.get("device_sentinel.storage", {}))
    assert "CR2032" not in main, "owner entries leaked into the main storage file"
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.power_view(device.id)["words"] == "2× CR2032"


async def test_a_damaged_entry_is_left_out_and_the_rest_kept(hass: HomeAssistant, hass_storage, caplog):
    good, _ = register_device(hass, "pw2", "Good")
    bad, _ = register_device(hass, "pw3", "Bad")
    hass_storage[POWER_STORE_KEY] = {"version": 1, "minor_version": 1, "key": POWER_STORE_KEY, "data": {"devices": {
        good.id: {"kind": "battery", "type": "AA", "quantity": 4, "set": "2026-10-05T12:00:00+00:00"},
        bad.id: {"kind": "battery", "type": "AA", "quantity": 99},
        "x": "not an entry",
    }}}
    coord = await setup_coordinator(hass)
    assert coord.power_view(good.id)["words"] == "4× AA"
    assert coord.power_view(bad.id)["source"] is None
    assert "left out 2 owner battery entries" in caplog.text


async def test_a_removed_device_takes_its_entry_with_it(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="AAA", quantity=2)
    assert reply["success"], reply
    dr.async_get(hass).async_remove_device(device.id)
    await hass.async_block_till_done()
    assert device.id not in coord._power_entries


# ------------------------------------------------------------ elsewhere


async def test_the_brief_problem_list_event_and_diagnostics_carry_it(hass: HomeAssistant, hass_ws_client, monkeypatch):
    coord, client, device = await _setup(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id,
                      choice="Other", other="CR2|32")
    assert reply["success"], reply
    coord.data[DATA_DEVICES][device.id][DEV_BATTERY_VALUE] = 12
    assert coord._brief_battery_text(device.id) == "battery 12%, CR2\\|32", "a pipe would split the brief's table"
    other, _ = register_device(hass, "pw8", "Unknown Cell")
    assert coord._brief_battery_text(other.id) == "battery low", "nothing is added when nothing is known"

    item = {TODO_UID: "u1", TODO_DEVICE_ID: device.id, TODO_SORT_NAME: "Button Randy Night Table",
            TODO_SUMMARY: "Button Randy Night Table: battery 12%", TODO_KINDS: {TODO_KIND_LOW_BATTERY: 1.0},
            TODO_STATUS: "needs_action"}
    monkeypatch.setattr(type(coord), "todo_items", property(lambda _self: [item]))
    reply = await _ws(client, type="device_sentinel/problem_list")
    assert reply["result"]["rows"][0]["power"] == "CR2|32"

    seen = []
    coord._grace_until = 0.0  # events are held through the startup grace
    hass.bus.async_listen(EVENT_FAULT, lambda event: seen.append(event.data))
    coord.fire_fault(device.id, "Button Randy Night Table", [TODO_KIND_LOW_BATTERY], "2026-10-05T12:00:00+00:00")
    await hass.async_block_till_done()
    assert seen and seen[0]["battery_type"] == "CR2|32"

    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    power = diagnostics["devices"][device.id]["power"]
    assert (power["words"], power["source"]) == ("CR2|32", "owner")


async def test_the_page_carries_the_power_block(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device", device_id=device.id)
    assert reply["success"], reply
    power = reply["result"]["identity"]["power"]
    assert power["words"] == "Not known"
    assert power["choices"] == [
        "AA", "AAA", "CR2032", "CR2450", "Rechargeable", "CR123A", "CR2", "CR2477", "CR1632", "CR2430",
        "Mains Powered", "USB Powered", "Other",
    ]
    assert power["quantity"] == [1, 8]
    assert power["library_home"] == "https://github.com/andrew-codechimp/HA-Battery-Notes"
    assert "battery_type" not in reply["result"]["identity"]
