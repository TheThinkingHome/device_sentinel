# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_actions.py, Version: 0.24.5 (2026-10-04)

"""Acting from the device page (0.24.5, Project__Device_Page_Actions.md).

Each act writes Home Assistant's registry or Device Sentinel's own
options, shows at once on the page, and records exactly one row in the
brief on the device's own line.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_LABELS,
    DATA_SYSTEM_EVENTS,
    SYS_DEVICE_ID,
    SYS_DEVICE_PAGE,
    SYS_DETAIL,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
)

from .helpers import register_device, setup_coordinator

_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


def _rows(coord, kind):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row[SYS_KIND] == kind]


async def _setup(hass, hass_ws_client, key="pa0", name="Button Randy Night Table"):
    device, _entities = register_device(hass, key, name)
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    return coord, client, device


async def test_a_rename_is_written_shown_at_once_and_recorded_once(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_rename", device_id=device.id, name="Randy's Button")
    assert reply["success"], reply
    assert dr.async_get(hass).async_get(device.id).name_by_user == "Randy's Button"
    assert coord._device_name(device.id) == "Randy's Button", "the page waited for the debouncer"
    rows = _rows(coord, SYS_DEVICE_PAGE)
    assert len(rows) == 1 and rows[0][SYS_DEVICE_ID] == device.id
    assert rows[0][SYS_DETAIL] == "renamed Randy's Button, from its device page"


async def test_a_name_in_use_is_held_for_a_yes(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    other, _ = register_device(hass, "pa1", "Hall Button")
    living = ar.async_get(hass).async_create("Living Room")
    dr.async_get(hass).async_update_device(other.id, area_id=living.id)
    reply = await _ws(client, type="device_sentinel/device_rename", device_id=device.id, name="hall button")
    assert reply["error"]["code"] == "name_in_use"
    assert reply["error"]["message"] == "Another device is already named Hall Button (in the Living Room)."
    assert dr.async_get(hass).async_get(device.id).name_by_user is None, "saved without a yes"
    reply = await _ws(client, type="device_sentinel/device_rename", device_id=device.id, name="hall button", confirm=True)
    assert reply["success"] and dr.async_get(hass).async_get(device.id).name_by_user == "hall button"


async def test_an_empty_name_resets_to_the_integrations(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    dr.async_get(hass).async_update_device(device.id, name_by_user="Something")
    reply = await _ws(client, type="device_sentinel/device_rename", device_id=device.id, name="")
    assert reply["success"], reply
    assert dr.async_get(hass).async_get(device.id).name_by_user is None


async def test_an_area_is_set_and_an_unknown_one_refused(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    laundry = ar.async_get(hass).async_create("Laundry")
    reply = await _ws(client, type="device_sentinel/device_area", device_id=device.id, area_id=laundry.id)
    assert reply["success"] and dr.async_get(hass).async_get(device.id).area_id == laundry.id
    reply = await _ws(client, type="device_sentinel/device_area", device_id=device.id, area_id="nowhere")
    assert reply["error"]["code"] == "refused" and reply["error"]["message"] == "Home Assistant has no such area"
    assert dr.async_get(hass).async_get(device.id).area_id == laundry.id, "a refusal changed the area"
    reply = await _ws(client, type="device_sentinel/device_area", device_id=device.id, area_id=None)
    assert reply["success"] and dr.async_get(hass).async_get(device.id).area_id is None


async def test_a_label_goes_on_and_off_and_is_never_deleted(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    garage = lr.async_get(hass).async_create("Garage")
    reply = await _ws(client, type="device_sentinel/device_label", device_id=device.id, label_id=garage.label_id, add=True)
    assert reply["success"] and garage.label_id in dr.async_get(hass).async_get(device.id).labels
    reply = await _ws(client, type="device_sentinel/device_label", device_id=device.id, label_id=garage.label_id, add=False)
    assert reply["success"] and garage.label_id not in dr.async_get(hass).async_get(device.id).labels
    assert lr.async_get(hass).async_get_label(garage.label_id) is not None, "the label was deleted from Home Assistant"


async def test_a_labels_meaning_is_read_from_the_mute_settings(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    garage = lr.async_get(hass).async_create("Garage")
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_FREEZE_MUTED_LABELS: [garage.label_id]}
    )
    await hass.async_block_till_done()
    reply = await _ws(client, type="device_sentinel/device_choices")
    assert {"id": garage.label_id, "name": "Garage", "meaning": "mutes freeze"} in reply["result"]["labels"]


async def test_last_seen_is_turned_on_for_this_device_alone(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    other, _ = register_device(hass, "pa2", "Other Button")
    ent = er.async_get(hass)
    off = er.RegistryEntryDisabler.INTEGRATION

    def owner(d):
        # Each entity on its device's own config entry, as an
        # integration registers it, so switching one on schedules that
        # entry's reload as on a real house. config_entry_id where the
        # version has it (2026.10 deprecates config_entries).
        found = dr.async_get(hass).async_get(d.id)
        entry_id = getattr(found, "config_entry_id", None) or next(iter(found.config_entries))
        return hass.config_entries.async_get_entry(entry_id)

    mine = ent.async_get_or_create("sensor", "test", "pa0_ls", device_id=device.id, config_entry=owner(device),
                                   original_name="Last seen", disabled_by=off)
    theirs = ent.async_get_or_create("sensor", "test", "pa2_ls", device_id=other.id, config_entry=owner(other),
                                     original_name="Last seen", disabled_by=off)
    coord._rebuild_registry_view()
    assert coord.page_actions(device.id)["last_seen_off"] is True
    reply = await _ws(client, type="device_sentinel/device_last_seen", device_id=device.id)
    assert reply["success"] and reply["result"] == {"enabled": 1}, reply
    assert ent.async_get(mine.entity_id).disabled_by is None
    assert ent.async_get(theirs.entity_id).disabled_by is off, "another device's Last Seen was turned on"


async def test_a_page_mute_equals_a_settings_mute_with_one_row(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    other, _ = register_device(hass, "pa3", "Settings Button")
    coord._rebuild_registry_view()
    reply = await _ws(client, type="device_sentinel/device_mute", device_id=device.id, kind="freeze", on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    # The same mute set in Settings, for the other device.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_FREEZE_MUTED_DEVICES: [*coord.entry.options[CONF_FREEZE_MUTED_DEVICES], other.id]},
    )
    await hass.async_block_till_done()
    assert coord.page_mutes(device.id)["freeze"] == {"on": True, "source": "device", "here": True}
    assert coord.page_mutes(other.id)["freeze"] == coord.page_mutes(device.id)["freeze"], "the two paths differ"
    assert coord.mute_text(device.id) == coord.mute_text(other.id)
    page_rows = _rows(coord, SYS_DEVICE_PAGE)
    settings_rows = _rows(coord, SYS_OPTIONS_CHANGED)
    assert len(page_rows) == 1 and page_rows[0][SYS_DETAIL] == "freeze muted, from its device page"
    assert len(settings_rows) == 1, "the page mute also wrote a Settings changed row, or Settings wrote none"
    reply = await _ws(client, type="device_sentinel/device_mute", device_id=device.id, kind="freeze", on=False)
    await hass.async_block_till_done()
    assert reply["success"] and coord.page_mutes(device.id)["freeze"]["on"] is False


async def test_a_mute_from_a_label_cannot_be_lifted_here(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    quiet = lr.async_get(hass).async_create("Quiet")
    dr.async_get(hass).async_update_device(device.id, labels={quiet.label_id})
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_FREEZE_MUTED_LABELS: [quiet.label_id]}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    state = coord.page_mutes(device.id)["freeze"]
    assert state["on"] is True and state["here"] is False and state["source"] == "label: Quiet"


async def test_every_act_answers_not_found_for_an_unknown_device(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    for payload in (
        {"type": "device_sentinel/device_rename", "name": "x"},
        {"type": "device_sentinel/device_area", "area_id": None},
        {"type": "device_sentinel/device_label", "label_id": "x", "add": True},
        {"type": "device_sentinel/device_last_seen"},
        {"type": "device_sentinel/device_mute", "kind": "freeze", "on": True},
    ):
        reply = await _ws(client, device_id="no-such-device", **payload)
        assert reply["error"]["code"] == "not_found", (payload, reply)


async def test_a_non_admin_cannot_act(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    coord, _client, device = await _setup(hass, hass_ws_client)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(client, type="device_sentinel/device_rename", device_id=device.id, name="x")
    assert reply["error"]["code"] == "unauthorized"


async def test_the_brief_puts_a_page_act_on_the_devices_line(hass: HomeAssistant, hass_ws_client):
    coord, client, device = await _setup(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_mute", device_id=device.id, kind="battery", on=True)
    await hass.async_block_till_done()
    row = _rows(coord, SYS_DEVICE_PAGE)[0]
    assert coord._system_event_who(row) == "Button Randy Night Table"
    assert coord._system_event_phrase(row) == "battery muted, from its device page"
    assert row not in [r for r in coord.data[DATA_SYSTEM_EVENTS] if coord._system_event_who(r) == "The system"]
