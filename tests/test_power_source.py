# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_power_source.py, Version: 0.24.11 (2026-10-07)

"""What powers each device (0.24.7, Project__0_24_7.md).

The owner's entry first, then the Battery Notes library shipped inside
Device Sentinel, otherwise "Not known". The pencil is on the device
page only; the report button opens Battery Notes' New Device form,
filled in.
"""

from __future__ import annotations

import json
import re
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


async def _setup(hass, hass_ws_client, maker="Unlisted Maker", model="Unlisted Sensor", model_id="UL-SENSOR-1", hw="1"):
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
    assert library.match("Aqara", "Door and window sensor", "MCCGQ11LM", "2").words == "CR2032"
    bad = tmp_path / "battery_library.json"
    bad.write_text("{ not json")
    assert load_library(bad) is None
    bad.write_text(json.dumps({"devices": "nope"}))
    assert load_library(bad) is None
    assert load_library(tmp_path / "missing.json") is None
    assert "cannot read its battery library" in caplog.text



def test_the_licence_line_counts_the_shipped_library():
    """The library is refreshed with every Latest (0.24.7, ruling 3), and
    the licence file's copy line is updated by hand at each refresh. A
    refresh that forgot the line would ship a notice that misstates
    what Device Sentinel carries (0.24.11)."""
    from pathlib import Path

    data = Path(power_source.__file__).parent / "data"
    count = len(json.loads((data / "battery_library.json").read_text(encoding="utf-8"))["devices"])
    notice = (data / "BATTERY_LIBRARY_LICENSE.md").read_text(encoding="utf-8")
    line = re.search(r"Copied for Device Sentinel (\S+) on .+?: ([\d,]+) devices\.", notice)
    assert line, "the licence file has no copy line"
    assert int(line.group(2).replace(",", "")) == count
    assert load_library().size == count

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
    assert (view["words"], view["source"], view["report_url"]) == ("CR2032", "library", None)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="AAA", quantity=2)
    assert reply["success"], reply
    view = coord.power_view(device.id)
    assert (view["words"], view["source"], view["library"]) == ("2× AAA", "owner", "CR2032")
    assert view["report_url"], "a correction is offered to Battery Notes"
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice=None)
    assert reply["success"], reply
    assert coord.power_view(device.id)["words"] == "CR2032"
    details = [r[SYS_DETAIL] for r in _page_rows(coord)]
    assert details == [
        "power set to 2× AAA, from its device page",
        "power entry removed, the library's CR2032 used, from its device page",
    ]
    other, _ = register_device(hass, "pw9", "Mystery")
    assert coord.power_view(other.id)["words"] == "Not known"
    assert coord.power_view(other.id)["source"] is None


async def test_mains_and_usb_take_no_quantity_and_no_report(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Aqara", "Presence sensor FP2", None, None)
    for choice in ("Mains Powered", "USB Powered", "PoE Powered"):
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
    coord, client, device = await _setup(hass, hass_ws_client)
    assert coord.power_view(device.id)["words"] == "Not known", "the library lacks this sensor"
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id,
                      choice="Other", other="CR2032 & co", quantity=1)
    assert reply["success"], reply
    url = coord.power_view(device.id)["report_url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == power_source.REPORT_FORM
    assert dict(parse_qsl(parts.query)) == {
        "template": "new_device_request.yaml",
        "title": "[Device]: Unlisted Maker Unlisted Sensor (UL-SENSOR-1)",
        "manufacturer": "Unlisted Maker",
        "model": "Unlisted Sensor",
        "model_id": "UL-SENSOR-1",
        "battery_type": "CR2032 & co",
        "battery_quantity": "1",
    }
    assert "&co" not in url and " " not in url, "values must be encoded"


async def test_no_link_without_a_maker_or_when_it_says_what_the_library_says(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client, "Aqara", "Door and window sensor", "MCCGQ11LM", "2")
    reply = await _ws(client, type="device_sentinel/device_power", device_id=device.id, choice="Other", other="CR2032")
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
        "Mains Powered", "USB Powered", "PoE Powered", "Other",
    ]
    assert power["quantity"] == [1, 8]
    assert power["library_home"] == "https://github.com/andrew-codechimp/HA-Battery-Notes"
    assert "battery_type" not in reply["result"]["identity"]


# ------------------------------------------------ one entry for the model (0.24.8)


async def _four_of_a_kind(hass, hass_ws_client):
    """Four of one model, and one other."""
    names = ("Button Doorbell", "Button Master Shower", "Button Randy Night Table", "Button Terrace Dining")
    devices = []
    for i, name in enumerate(names):
        device, _ = register_device(hass, f"mk{i}", name)
        _made_by(hass, device, "Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1", str(i))
        devices.append(device)
    stranger, _ = register_device(hass, "mk9", "Something Else")
    _made_by(hass, stranger, "Unlisted Maker", "Other Sensor", "HK-OTHER")
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    return coord, client, devices, stranger


async def test_one_entry_covers_every_device_of_the_model(hass: HomeAssistant, hass_ws_client):
    coord, client, devices, stranger = await _four_of_a_kind(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=devices[1].id, choice="AAA", quantity=2)
    assert reply["success"], reply
    for device in devices:
        view = coord.power_view(device.id)
        assert (view["words"], view["source"], view["covers"]) == ("2× AAA", "owner", 4), device.name
        assert view["set_on_name"] == "Button Master Shower"
    assert coord.power_view(stranger.id)["words"] == "Not known", "another model took the entry"
    # The same model written another way is another model: same means
    # exactly the same (0.24.8).
    lookalike, _ = register_device(hass, "mk8", "Lookalike")
    _made_by(hass, lookalike, "Unlisted Maker", "Unlisted Sensor", "UL SENSOR 1")
    assert coord.power_view(lookalike.id)["words"] == "Not known", "a model written another way took the entry"
    rows = [r[SYS_DETAIL] for r in _page_rows(coord)]
    assert rows == ["power set to 2× AAA, for all 4 devices of this model, from its device page"]


async def test_changing_or_clearing_it_anywhere_changes_it_for_all(hass: HomeAssistant, hass_ws_client):
    coord, client, devices, _stranger = await _four_of_a_kind(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=devices[1].id, choice="AAA", quantity=2)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=devices[3].id, choice="CR2032", quantity=1)
    assert reply["success"], reply
    assert {coord.power_view(d.id)["words"] for d in devices} == {"CR2032"}
    assert coord.power_view(devices[0].id)["set_on_name"] == "Button Terrace Dining"
    reply = await _ws(client, type="device_sentinel/device_power", device_id=devices[0].id, choice=None)
    assert reply["success"], reply
    assert {coord.power_view(d.id)["words"] for d in devices} == {"Not known"}


async def test_a_0_24_7_entry_becomes_the_models(hass: HomeAssistant, hass_storage):
    devices = []
    for i in range(3):
        device, _ = register_device(hass, f"mg{i}", f"Button {i}")
        _made_by(hass, device, "Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1", "1")
        devices.append(device)
    lonely, _ = register_device(hass, "mg9", "No Maker")
    hass_storage[POWER_STORE_KEY] = {"version": 1, "minor_version": 1, "key": POWER_STORE_KEY, "data": {"devices": {
        devices[0].id: {"kind": "battery", "type": "AA", "quantity": 4, "set": "2026-10-05T12:00:00+00:00"},
        lonely.id: {"kind": "mains", "type": "Mains Powered", "quantity": None, "set": "2026-10-05T12:00:00+00:00"},
    }}}
    coord = await setup_coordinator(hass)
    assert {coord.power_view(d.id)["words"] for d in devices} == {"4× AA"}
    assert coord.power_view(lonely.id)["words"] == "Mains Powered", "a device with no model keeps its own"
    payload = coord._power_payload()
    assert devices[0].id in payload["devices"] and payload["devices"][devices[0].id]["model"], "no copy for 0.24.7"
    assert payload["devices"][lonely.id] == {"kind": "mains", "type": "Mains Powered", "quantity": None,
                                             "set": "2026-10-05T12:00:00+00:00"}


async def test_the_copy_for_0_24_7_is_never_read_back_as_an_entry(hass: HomeAssistant, hass_storage, hass_ws_client):
    coord, client, devices, _stranger = await _four_of_a_kind(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=devices[1].id, choice="AAA", quantity=2)
    hass_storage[POWER_STORE_KEY] = {"version": 1, "minor_version": 1, "key": POWER_STORE_KEY,
                                     "data": coord._power_payload()}
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass_storage[POWER_STORE_KEY]["data"] = json.loads(json.dumps(hass_storage[POWER_STORE_KEY]["data"]))
    # The device that set it now reports another model: its copy must not
    # turn into an entry for that model.
    _made_by(hass, devices[1], "Unlisted Maker", "Renamed Sensor", "HK-RENAMED", "1")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert coord._power_entries == {}, "the copy came back as a device's own entry"
    assert len(coord._power_models) == 1
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=devices[2].id, choice=None)
    assert reply["success"], reply
    assert coord.power_view(devices[1].id)["words"] == "Not known", "the copy became an entry for its new model"
    assert {coord.power_view(d.id)["words"] for d in devices} == {"Not known"}, "a copy outlived the clear"


async def test_a_removed_setter_hands_the_entry_to_another_of_the_model(hass: HomeAssistant, hass_ws_client):
    coord, client, devices, _stranger = await _four_of_a_kind(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=devices[1].id, choice="AAA", quantity=2)
    dr.async_get(hass).async_remove_device(devices[1].id)
    await hass.async_block_till_done()
    survivors = [d for i, d in enumerate(devices) if i != 1]
    assert {coord.power_view(d.id)["words"] for d in survivors} == {"2× AAA"}
    assert coord.power_view(survivors[0].id)["set_on"] in {d.id for d in survivors}
    for d in survivors:
        dr.async_get(hass).async_remove_device(d.id)
    await hass.async_block_till_done()
    assert coord._power_models == {}, "the last of the model left its entry behind"


async def test_an_entry_set_on_a_device_since_gone_names_no_ghost(hass: HomeAssistant, hass_storage):
    device, _ = register_device(hass, "gh1", "Survivor")
    _made_by(hass, device, "Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1")
    key = json.dumps(["Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1"])
    hass_storage[POWER_STORE_KEY] = {"version": 1, "minor_version": 1, "key": POWER_STORE_KEY, "data": {"models": {
        key: {"kind": "battery", "type": "AA", "quantity": 3, "set": "2026-10-05T12:00:00+00:00", "device_id": "gone"},
    }, "devices": {}}}
    coord = await setup_coordinator(hass)
    view = coord.power_view(device.id)
    assert (view["words"], view["set_on_name"]) == ("3× AA", None), view



async def test_a_reload_inside_the_save_second_keeps_the_entry(hass: HomeAssistant, hass_storage):
    """A pencil save is written a second later; a reload or a stop inside
    that second lost it (0.24.9, found before Latest)."""
    device, _ = register_device(hass, "rs1", "Saved Then Reloaded")
    _made_by(hass, device, "Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1")
    entry = await setup_entry(hass)
    entry.runtime_data.page_set_power(device.id, "AAA", 2)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.power_view(device.id)["words"] == "2× AAA"
    entry.runtime_data.page_set_power(device.id, "CR2032", 1)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    models = hass_storage[POWER_STORE_KEY]["data"]["models"]
    assert [m["type"] for m in models.values()] == ["CR2032"]


# ------------------------------------------------------------ malformed input (0.24.11)


def _registry_with_numbers(hass, hass_storage, device_id, **fields):
    """The device list as Home Assistant 2026.5 saved it when an integration
    gave a number for a text field, loaded again. Every version reads a saved
    number as a number; only a new registration from 2026.6 on is turned into
    text."""
    import orjson

    registry = dr.async_get(hass)
    data = json.loads(orjson.dumps(registry._data_to_save()))
    for row in data["devices"]:
        if row["id"] == device_id:
            row.update(fields)
    hass_storage["core.device_registry"] = {
        "version": registry._store.version, "minor_version": registry._store.minor_version,
        "key": "core.device_registry", "data": data,
    }
    return dr.DeviceRegistry(hass)


async def test_a_device_saved_with_a_numeric_maker_keeps_its_page_and_the_brief(hass: HomeAssistant, hass_storage):
    """Since 0.24.9 the brief's recommendation lines ask the library about
    every device. A maker saved as the number 7 failed that lookup, so the
    whole brief, the device's page and the Recommendations tab failed with it
    (0.24.11). The device reads as the text Home Assistant itself would give
    it today."""
    device, _ = register_device(hass, "num", "Numbered Plug")
    numbers = {"manufacturer": 7, "model": 1234, "model_id": 56, "hw_version": 2}
    if hasattr(dr, "_validate_str"):
        # 2026.6 and later turn a new number into text, but load a saved one as it is.
        reloaded = _registry_with_numbers(hass, hass_storage, device.id, **numbers)
        await reloaded.async_load()
        hass.data[dr.DATA_REGISTRY] = reloaded
    else:
        # 2026.5 stores the integration's number as it is.
        dr.async_get(hass).async_update_device(device.id, **numbers)
    assert dr.async_get(hass).async_get(device.id).manufacturer == 7, "the number is held as a number"
    coord = await setup_coordinator(hass)
    assert coord._power_device_fields(device.id) == ("7", "1234", "56", "2")
    assert coord.power_view(device.id)["words"] == "Not known"
    assert coord.dashboard_device(device.id)["identity"]["power"]["words"] == "Not known"
    coord.device_recommendations()
    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = hass.config.path("device_sentinel", "daily_brief.html")
    assert "</html>" in await hass.async_add_executor_job(
        lambda: open(brief, encoding="utf-8").read()
    ), "the brief is written whole"


def test_a_question_that_is_not_text_gets_no_answer():
    """Whatever reaches the lookup, it answers or says nothing; it never fails."""
    for maker, model, model_id, hw in (
        (7, "TRADFRI remote", None, None), ("IKEA", 7, None, None), ("Aqara", "Door and window sensor", 7, "2"),
        ("Aqara", "Door and window sensor", "MCCGQ11LM", ["2"]), (True, None, None, None), ({}, [], 1.5, float("nan")),
    ):
        assert LIB.match(maker, model, model_id, hw) is None
    assert LIB.match("IKEA", "TRADFRI remote").words == "CR2032", "text still answers"


def test_a_malformed_library_entry_is_skipped_and_the_rest_kept(caplog):
    """A battery type or quantity the pencil would refuse is never shown from
    the library either: no hidden or control characters, 1 to 40 characters,
    a quantity of 1 to 8. The entry is left out with one warning; the good
    entries beside it still answer (0.24.11)."""
    good = {"manufacturer": "Acme", "model": "Good", "battery_type": "AAA", "battery_quantity": 2}
    bad = [
        {"battery_type": "AA‮A"}, {"battery_type": "AA\nA"}, {"battery_type": ""}, {"battery_type": "   "},
        {"battery_type": "x" * 41}, {"battery_quantity": 0}, {"battery_quantity": 9}, {"battery_quantity": True},
        {"battery_quantity": 2**63}, {"battery_quantity": "2"}, {"battery_quantity": 1.5},
        {"model_id": 7}, {"hw_version": ["2"]}, {"model_match_method": 5},
    ]
    entries = [good, {**good, "model": "Single", "battery_quantity": None}]
    entries += [{**good, "model": f"Bad{i}", **change} for i, change in enumerate(bad)]
    library = BatteryLibrary(entries)
    assert library.size == 2
    assert library.match("Acme", "Good").words == "2× AAA"
    assert library.match("Acme", "Single").words == "AAA"
    for i in range(len(bad)):
        assert library.match("Acme", f"Bad{i}") is None, bad[i]
    warnings = [r for r in caplog.records if "battery library" in r.getMessage()]
    assert len(warnings) == 1 and "14" in warnings[0].getMessage()


def test_the_shipped_library_has_no_malformed_entry(caplog):
    """The rules above leave out none of the entries Battery Notes ships, so
    a refresh that brings a malformed one is seen before release."""
    entries = json.loads(power_source.LIBRARY_PATH.read_text(encoding="utf-8"))["devices"]
    assert load_library().size == len(entries)
    assert not [r for r in caplog.records if "battery library" in r.getMessage()]
