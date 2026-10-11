# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_exclude_device.py, Version: 0.25.6 (2026-10-11)

"""Excluding one device (0.25.6, ruling #625, from Tim Plas).

The integration exclusion's rules for a single device: set aside with
the same reason, its record, episodes and incidents discarded at the
next midnight's fold, and taking it back before then loses nothing.
Picked in Settings beside the integrations, or from the device page,
and both paths write the same option.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_MUTED_DEVICES,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    SET_ASIDE_EXCLUDED,
    SYS_DETAIL,
    SYS_DEVICE_PAGE,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    TODO_KINDS,
)

from .helpers import flat_schema, register_device, setup_entry

_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


def _rows(coord, kind):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row[SYS_KIND] == kind]


async def _two(hass, options=None):
    keep, _ = register_device(hass, "keep", "Door Master")
    drop, _ = register_device(hass, "drop", "Old Plug")
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: [], **(options or {})})
    return entry, entry.runtime_data, keep, drop


async def _set(hass, entry, **options):
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()


async def test_an_excluded_device_is_set_aside_alone(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert keep.id in coord._watched
    assert drop.id not in coord._watched
    assert coord._set_aside[drop.id][2] == SET_ASIDE_EXCLUDED
    row = next(r for r in coord.classification_rows() if r["device_id"] == drop.id)
    assert row["set_aside"] == "excluded (device)"
    # Its integration is not excluded, and no other device is.
    assert coord._set_aside.get(keep.id) is None


async def test_its_record_goes_at_the_fold_and_not_before(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert drop.id in coord.data[DATA_DEVICES], "the record went before midnight"
    # Taken back before midnight: nothing lost.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: []})
    coord._discard_excluded_records()
    assert drop.id in coord.data[DATA_DEVICES] and drop.id in coord._watched
    # Excluded through midnight: gone, and the other device kept.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    coord._discard_excluded_records()
    assert drop.id not in coord.data[DATA_DEVICES]
    assert keep.id in coord.data[DATA_DEVICES]


async def test_the_page_excludes_and_takes_back_with_one_row_each(hass: HomeAssistant, hass_ws_client):
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    assert coord.page_actions(drop.id)["excluded"] == {"here": False, "integration": False}
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_DEVICES] == [drop.id]
    assert drop.id not in coord._watched
    assert coord.page_actions(drop.id)["excluded"] == {"here": True, "integration": False}
    page = _rows(coord, SYS_DEVICE_PAGE)
    assert [r[SYS_DETAIL] for r in page] == ["excluded, from its device page"]
    assert _rows(coord, SYS_OPTIONS_CHANGED) == [], "the page act also wrote a Settings changed row"
    # The same act twice changes nothing and writes nothing.
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["success"] and len(_rows(coord, SYS_DEVICE_PAGE)) == 1
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=False)
    await hass.async_block_till_done()
    assert reply["success"] and entry.options[CONF_EXCLUDED_DEVICES] == []
    assert drop.id in coord._watched
    assert _rows(coord, SYS_DEVICE_PAGE)[-1][SYS_DETAIL] == "no longer excluded, from its device page"


async def test_the_page_says_when_the_integration_is_excluded(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    assert coord.page_actions(drop.id)["excluded"] == {"here": False, "integration": True}
    row = next(r for r in coord.classification_rows() if r["device_id"] == drop.id)
    assert row["set_aside"] == "excluded (integration: test)"


async def test_the_page_refuses_an_unknown_device_and_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
):
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id="no-such-device", on=True)
    assert reply["error"]["code"] == "not_found"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(reader, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["error"]["code"] == "unauthorized"
    assert CONF_EXCLUDED_DEVICES not in entry.options


async def test_a_hand_edited_list_names_only_devices(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id, 7, None, ["x"]]})
    assert coord.excluded_devices == frozenset({drop.id})
    assert drop.id not in coord._watched and keep.id in coord._watched
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: "not a list"})
    assert coord.excluded_devices == frozenset()
    assert drop.id in coord._watched


async def test_settings_offers_watched_and_excluded_devices(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass, {CONF_EXCLUDED_DEVICES: []})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    schema = flat_schema(result["data_schema"].schema)
    field = next(k for k in schema if str(k) == CONF_EXCLUDED_DEVICES)
    labels = {opt["value"]: opt["label"] for opt in schema[field].config["options"]}
    assert labels[keep.id] == "Door Master (test)"
    assert labels[drop.id] == "Old Plug (test, excluded)"
    assert field.default() == [drop.id]


async def test_saving_settings_excludes_and_keeps_its_mutes(hass: HomeAssistant):
    """Taking an exclusion back before midnight gives back everything,
    mutes included, whatever screen was saved meanwhile (found by
    review)."""
    entry, coord, keep, drop = await _two(
        hass, {CONF_MUTED_DEVICES: [], CONF_FREEZE_MUTED_DEVICES: []}
    )
    await _set(hass, entry, **{CONF_FREEZE_MUTED_DEVICES: [drop.id, keep.id]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"exclude": {CONF_EXCLUDED_INTEGRATIONS: [], CONF_EXCLUDED_DEVICES: [drop.id]},
         "muting": {CONF_MUTED_DEVICES: [keep.id]}},
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_DEVICES] == [drop.id]
    assert drop.id not in coord._watched
    assert entry.options[CONF_FREEZE_MUTED_DEVICES] == [drop.id], "the excluded device's mute was dropped"
    # The global mute added in the same save took keep's section mute,
    # as it always has; the exclusion took nothing.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: []})
    assert drop.id in coord._watched
    assert drop.id in entry.options[CONF_FREEZE_MUTED_DEVICES]


@pytest.mark.parametrize("how", ["device", "integration"])
async def test_an_excluded_device_removed_is_not_held(hass: HomeAssistant, hass_ws_client, how):
    """Removed from Home Assistant after it was excluded, its record and
    answers would have been held for 30 days; the person asked for them
    to go, so they go with the removal (found by review)."""
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=drop.id, choice="AAA", quantity=2)
    assert reply["success"], reply
    reply = await _ws(client, type="device_sentinel/device_type", device_id=drop.id, choice="Plug")
    assert reply["success"], reply
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    if how == "device":
        await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    else:
        other, _ = register_device(hass, "other", "Other Source Device")
        await _set(hass, entry, **{CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    assert drop.id in coord.data[DATA_DEVICES]
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert drop.id not in coord.data[DATA_DEVICES], "the record was held"
    assert drop.id not in {row["device_id"] for row in coord.held_records()}
    assert drop.id not in coord._power_entries and drop.id not in coord._type_entries
    assert keep.id in coord.data[DATA_DEVICES]


async def test_a_watched_device_removed_is_still_held(hass: HomeAssistant):
    """The control: ruling #622's hold is unchanged for a device that was
    never excluded."""
    entry, coord, keep, drop = await _two(hass)
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert drop.id in {row["device_id"] for row in coord.held_records()}


async def test_an_integration_whose_devices_are_all_excluded_reads_excluded(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id, keep.id]})
    assert coord._integration_standing("test", 0) == "excluded"
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert coord._integration_standing("test", 1) == "watched"


async def test_a_device_removed_from_home_assistant_leaves_the_list(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"exclude": {CONF_EXCLUDED_INTEGRATIONS: []}, "muting": {}},
    )
    await hass.async_block_till_done()
    assert entry.options.get(CONF_EXCLUDED_DEVICES) == []


# An exclusion is a person's act, not a recovery, as a mute is (#537).


@pytest.mark.parametrize("option", [CONF_EXCLUDED_DEVICES, CONF_EXCLUDED_INTEGRATIONS])
async def test_excluding_a_device_in_trouble_is_not_a_recovery(hass: HomeAssistant, freezer, option):
    source = MockConfigEntry(domain="zwave_js", title="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={("zwave_js", "p")}, name="Probe")
    ents = er.async_get(hass)
    value = ents.async_get_or_create("sensor", "zwave_js", "v", device_id=device.id, config_entry=source).entity_id
    battery = ents.async_get_or_create(
        "sensor", "zwave_js", "b", device_id=device.id, config_entry=source, original_device_class="battery"
    ).entity_id
    hass.states.async_set(value, "40")
    hass.states.async_set(battery, "5", {"unit_of_measurement": "%", "device_class": "battery"})
    bus: list[tuple[str, object]] = []
    for name in ("device_sentinel_fault", "device_sentinel_recovered", "device_sentinel_withdrawn"):
        hass.bus.async_listen(name, lambda e, n=name: bus.append((n.rsplit("_", 1)[-1], e.data.get("reason"))))
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"], CONF_EXCLUDED_INTEGRATIONS: []})
    heard = dt_util.utcnow() - timedelta(hours=10)

    async def minutes(count):
        for _ in range(count):
            freezer.tick(60)
            c = entry.runtime_data
            c._grace_until = 0.0
            record = c.data[DATA_DEVICES].get(device.id)
            if record is not None:
                record[DEV_EVENT_COUNT] = 5000
                if len(record.get(DEV_DAILY_MAX) or []) < LEARNING_MIN_DAYS + 5:
                    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
                record[DEV_LAST_ACTIVITY] = min(record.get(DEV_LAST_ACTIVITY) or 9e18, heard.timestamp())
            c._evaluate_all_batteries()
            await c._on_render_tick(None)
            await hass.async_block_till_done()

    await minutes(6)
    coord = entry.runtime_data
    listed = next((sorted(i.get(TODO_KINDS) or {}) for i in coord.todo_items if i.get("device_id") == device.id), [])
    assert "frozen" in listed and "low_battery" in listed, listed
    bus.clear()
    phone.clear()
    chosen = [device.id] if option == CONF_EXCLUDED_DEVICES else ["zwave_js"]
    hass.config_entries.async_update_entry(entry, options={**entry.options, option: chosen})
    await hass.async_block_till_done()
    await minutes(3)
    coord = entry.runtime_data
    assert not [i for i in coord.todo_items if i.get("device_id") == device.id]
    assert not [b for b in bus if b[0] == "recovered"], bus
    assert [b for b in bus if b[0] == "withdrawn"], bus
    about_it = [c.data.get("message") for c in phone if "Probe" in str(c.data.get("message"))]
    assert not about_it, about_it
