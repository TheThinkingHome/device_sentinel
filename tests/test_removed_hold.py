"""Tests for the 30-day hold of a removed device's record (ruling #622).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_removed_hold.py, Version: 0.25.5 (2026-10-10)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Home Assistant keeps a removed device's id and gives it back when the
same hardware is added again. Device Sentinel holds the record for 30
days the same way: the rhythm, the answers and the mutes come back
with the device. The gap across the absence is refused, the signal
history starts over unless the device comes back before the next
midnight, and the fold after 30 days deletes the record and its
answers.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY, HELD_GONE
from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_DAILY_DATES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_REMOVED_NAME,
    DEV_REMOVED_SINCE,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
    FREEZE_CATEGORY_FROZEN,
    LEARNED_DISABLED,
    REMOVED_HOLD_DAYS,
    STORAGE_KEY,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.device_sentinel.normalise import check_records

from .helpers import MULTI_OWNER_GONE, MULTI_OWNER_POSSIBLE, registry_settled, setup_coordinator, setup_entry

DAY = 86400.0


class Hardware:
    """One piece of hardware that can be removed and added again."""

    def __init__(self, hass: HomeAssistant, uid: str, name: str) -> None:
        self.hass = hass
        self.uid = uid
        self.name = name
        self.source = MockConfigEntry(domain="test", title="Source")
        self.source.add_to_hass(hass)
        self.source.mock_state(hass, ConfigEntryState.LOADED)
        self.device_id = ""
        self.entity_id = ""
        self.add()

    def add(self) -> str:
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.source.entry_id,
            identifiers={("test", self.uid)},
            name=self.name,
        )
        entity = er.async_get(self.hass).async_get_or_create(
            "sensor", "test", self.uid, device_id=device.id, config_entry=self.source
        )
        self.device_id, self.entity_id = device.id, entity.entity_id
        return device.id

    def remove(self) -> None:
        dr.async_get(self.hass).async_remove_device(self.device_id)


def _learned(record: dict) -> None:
    """A record with a month of rhythm and a signal history."""
    record[DEV_DAILY_MAX] = [3600.0] * 30
    record[DEV_SIGNAL_SCALE] = "dbm"
    record[DEV_SIGNAL_VALUE] = -60.0
    record[DEV_SIGNAL_DAILY_P5] = [-70.0] * 10


async def _removed(hass: HomeAssistant, hardware: Hardware) -> None:
    hardware.remove()
    await registry_settled(hass)


async def _readded(hass: HomeAssistant, hardware: Hardware) -> str:
    device_id = hardware.add()
    await registry_settled(hass)
    return device_id


# ------------------------------------------------------------ the hold


async def test_a_removed_device_is_held_with_its_name(hass: HomeAssistant, caplog):
    hardware = Hardware(hass, "rh1", "Kitchen Motion")
    coord = await setup_coordinator(hass)
    _learned(coord.data[DATA_DEVICES][hardware.device_id])
    caplog.set_level(logging.INFO, logger="custom_components.device_sentinel")

    await _removed(hass, hardware)

    record = coord.data[DATA_DEVICES][hardware.device_id]
    assert record[DEV_REMOVED_SINCE] is not None
    assert record[DEV_REMOVED_NAME] == "Kitchen Motion"
    assert record[DEV_SET_ASIDE_SINCE] is not None, "the gap across the absence must be refused"
    assert record[DEV_DAILY_MAX] == [3600.0] * 30
    assert hardware.device_id not in coord._watched
    assert hardware.device_id not in dict(coord.watched_records())
    assert "held 30 days in case the device comes back" in caplog.text
    assert "Kitchen Motion" in caplog.text
    assert coord._device_name(hardware.device_id) == "Kitchen Motion"


async def test_the_hold_is_stamped_once(hass: HomeAssistant):
    """A second rebuild must not restart the 30 days."""
    hardware = Hardware(hass, "rh2", "Hall Door")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    record[DEV_REMOVED_SINCE] -= 5 * DAY
    first = record[DEV_REMOVED_SINCE]

    coord._rebuild_registry_view()

    assert record[DEV_REMOVED_SINCE] == first
    assert record[DEV_REMOVED_NAME] == "Hall Door"


async def test_a_held_record_drops_its_verdict(hass: HomeAssistant):
    """A held device is one nothing may be said about, as a set-aside
    one is: a frozen verdict kept would count it among a stack's
    casualties for 30 days."""
    hardware = Hardware(hass, "rh3", "Garage Leak")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600

    await _removed(hass, hardware)

    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] is None


async def test_a_held_record_is_kept_out_of_the_signal_lists(hass: HomeAssistant):
    hardware = Hardware(hass, "rh4", "Weak Plug")
    coord = await setup_coordinator(hass)
    _learned(coord.data[DATA_DEVICES][hardware.device_id])
    assert hardware.device_id in {row["device_id"] for row in coord.detected_signals}

    await _removed(hass, hardware)

    assert hardware.device_id not in {row["device_id"] for row in coord.detected_signals}
    assert hardware.device_id not in {row["device_id"] for row in coord.signal_weak_list}


async def test_a_held_record_passes_the_shape_check(hass: HomeAssistant):
    hardware = Hardware(hass, "rh5", "Shape Check")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    assert check_records(coord.data[DATA_DEVICES]) == []


async def test_the_hold_survives_a_restart(hass: HomeAssistant, hass_storage):
    hardware = Hardware(hass, "rh6", "Porch Light")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    _learned(coord.data[DATA_DEVICES][hardware.device_id])
    await _removed(hass, hardware)
    since = coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage[STORAGE_KEY]["data"][DATA_DEVICES][hardware.device_id]
    assert stored[DEV_REMOVED_SINCE] == since
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await registry_settled(hass)

    record = entry.runtime_data.data[DATA_DEVICES][hardware.device_id]
    assert record[DEV_REMOVED_SINCE] == since, "a restart restarted the hold"
    assert record[DEV_REMOVED_NAME] == "Porch Light"
    # The gaps are forgotten at load, being longer than this test's
    # install has watched (#403); the signal history shows the record
    # came back whole.
    assert record[DEV_SIGNAL_DAILY_P5] == [-70.0] * 10


async def test_a_device_gone_while_home_assistant_was_down_is_held(hass: HomeAssistant, hass_storage):
    """No remove event reaches a stopped Home Assistant: the rebuild at
    the next start finds the record with no device and holds it."""
    hardware = Hardware(hass, "rh7", "Bedroom Blind")
    entry = await setup_entry(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hardware.remove()
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await registry_settled(hass)

    record = entry.runtime_data.data[DATA_DEVICES][hardware.device_id]
    assert record[DEV_REMOVED_SINCE] is not None
    # Its name was never seen by this run, so it is held without one.
    assert record[DEV_REMOVED_NAME] is None


async def test_the_diagnostics_list_the_held_records(hass: HomeAssistant):
    hardware = Hardware(hass, "rh8", "Office Sensor")
    entry = await setup_entry(hass)
    await _removed(hass, hardware)

    found = await async_get_config_entry_diagnostics(hass, entry)

    held = found["held_records"]
    assert [row["device_id"] for row in held] == [hardware.device_id]
    assert held[0]["name"] == "Office Sensor"
    removed = dt_util.parse_datetime(held[0]["removed"])
    deleted = dt_util.parse_datetime(held[0]["deleted_after"])
    assert deleted - removed == timedelta(days=REMOVED_HOLD_DAYS)
    assert found["devices"][hardware.device_id]["name"] == "Office Sensor"


# ------------------------------------------------------------ coming back


async def test_a_device_added_again_keeps_its_rhythm(hass: HomeAssistant, caplog):
    hardware = Hardware(hass, "rb1", "Back Door")
    coord = await setup_coordinator(hass)
    old_id = hardware.device_id
    _learned(coord.data[DATA_DEVICES][old_id])
    await _removed(hass, hardware)
    caplog.set_level(logging.INFO, logger="custom_components.device_sentinel")

    new_id = await _readded(hass, hardware)

    assert new_id == old_id, "Home Assistant did not give the old id back"
    record = coord.data[DATA_DEVICES][new_id]
    assert record[DEV_REMOVED_SINCE] is None
    assert record[DEV_REMOVED_NAME] is None
    assert record[DEV_DAILY_MAX] == [3600.0] * 30
    assert new_id in coord._watched
    assert "came back and kept their records: Back Door" in caplog.text


async def test_the_gap_across_the_absence_is_refused(hass: HomeAssistant):
    hardware = Hardware(hass, "rb2", "Shed Door")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 3 * DAY
    await _removed(hass, hardware)
    await _readded(hass, hardware)
    episodes: list = []
    original = coord._close_episode

    def spy(device_id, stamp, learned, taint_seconds):
        episodes.append(learned)
        return original(device_id, stamp, learned, taint_seconds)

    coord._close_episode = spy
    hass.states.async_set(hardware.entity_id, "on")
    await hass.async_block_till_done()

    assert episodes == [LEARNED_DISABLED], episodes
    assert record[DEV_DAILY_MAX] == [3600.0] * 30
    assert record[DEV_SET_ASIDE_SINCE] is None, "the stamp is spent by the first report"


async def test_back_before_midnight_keeps_the_signal_history(hass: HomeAssistant):
    hardware = Hardware(hass, "rb3", "Same Day")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    await _removed(hass, hardware)

    await _readded(hass, hardware)

    assert record[DEV_SIGNAL_DAILY_P5] == [-70.0] * 10
    assert record[DEV_SIGNAL_SCALE] == "dbm"


async def test_back_on_a_later_day_starts_the_signal_history_again(hass: HomeAssistant):
    """A device away past midnight may have been moved: its signal
    history described a place it may no longer be."""
    hardware = Hardware(hass, "rb4", "Moved Plug")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    record[DEV_DAILY_DATES] = {
        "signal": {"last": "2026-10-01", "count": 10, "skipped": []},
        "daily_max": {"last": "2026-10-01", "count": 30, "skipped": []},
    }
    await _removed(hass, hardware)
    record[DEV_REMOVED_SINCE] -= 2 * DAY

    await _readded(hass, hardware)

    assert record[DEV_SIGNAL_DAILY_P5] == []
    assert record[DEV_SIGNAL_VALUE] is None
    assert record[DEV_SIGNAL_SCALE] is None
    assert "signal" not in (record[DEV_DAILY_DATES] or {})
    assert record[DEV_DAILY_MAX] == [3600.0] * 30, "the rhythm must stay"
    assert record[DEV_DAILY_DATES]["daily_max"]["count"] == 30
    assert check_records(coord.data[DATA_DEVICES]) == []


async def test_a_device_back_but_disabled_keeps_its_record_set_aside(hass: HomeAssistant):
    hardware = Hardware(hass, "rb5", "Back Disabled")
    coord = await setup_coordinator(hass)
    _learned(coord.data[DATA_DEVICES][hardware.device_id])
    await _removed(hass, hardware)
    device_id = hardware.add()
    dr.async_get(hass).async_update_device(device_id, disabled_by=dr.DeviceEntryDisabler.USER)
    await registry_settled(hass)

    record = coord.data[DATA_DEVICES][device_id]
    assert device_id in coord._set_aside
    assert record[DEV_REMOVED_SINCE] is None, "a device in the registry is not held"
    assert record[DEV_SET_ASIDE_SINCE] is not None
    assert record[DEV_DAILY_MAX] == [3600.0] * 30


# ------------------------------------------------------------ the purge


async def test_the_fold_keeps_a_hold_inside_30_days(hass: HomeAssistant):
    hardware = Hardware(hass, "rp1", "Inside Thirty")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 29.9 * DAY

    await coord._on_midnight(None)

    assert hardware.device_id in coord.data[DATA_DEVICES]


async def test_the_fold_deletes_a_hold_past_30_days(hass: HomeAssistant, caplog):
    hardware = Hardware(hass, "rp2", "Past Thirty")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 30 * DAY + 1
    caplog.set_level(logging.INFO, logger="custom_components.device_sentinel")

    await coord._on_midnight(None)

    assert hardware.device_id not in coord.data[DATA_DEVICES]
    assert "Deleted 1 record(s) of devices removed from Home Assistant more than 30 days ago: Past Thirty" in caplog.text
    assert coord.held_records() == []


async def test_the_purge_spares_a_device_back_in_the_registry(hass: HomeAssistant):
    """Belt and braces: a stamp left on a device that is back (a rebuild
    that has not run yet) never deletes its record."""
    hardware = Hardware(hass, "rp3", "Back In Time")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] = (
        dt_util.utcnow().timestamp() - 40 * DAY
    )

    coord._purge_held_records(dt_util.utcnow().timestamp())

    assert hardware.device_id in coord.data[DATA_DEVICES]


async def test_a_device_added_after_the_purge_starts_fresh(hass: HomeAssistant):
    hardware = Hardware(hass, "rp4", "Long Gone")
    coord = await setup_coordinator(hass)
    _learned(coord.data[DATA_DEVICES][hardware.device_id])
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 31 * DAY
    await coord._on_midnight(None)

    device_id = await _readded(hass, hardware)

    assert coord.data[DATA_DEVICES][device_id][DEV_DAILY_MAX] == []


# ------------------------------------------------------------ answers


async def _client(hass, hass_ws_client):
    return await hass_ws_client(hass)


async def _ws(client, **payload):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


async def test_answers_wait_for_a_held_device(hass: HomeAssistant, hass_ws_client):
    hardware = Hardware(hass, "ra1", "Answered Sensor")
    coord = await setup_coordinator(hass)
    client = await _client(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=hardware.device_id,
                      choice="CR2032", quantity=1)
    assert reply["success"], reply
    reply = await _ws(client, type="device_sentinel/device_type", device_id=hardware.device_id,
                      choice="Motion Sensor")
    assert reply["success"], reply
    assert hardware.device_id in coord._power_entries
    assert hardware.device_id in coord._type_entries

    await _removed(hass, hardware)

    assert hardware.device_id in coord._power_entries, "the power answer went with the removal"
    assert hardware.device_id in coord._type_entries, "the type answer went with the removal"
    held = coord.answers_held()
    assert {(row["device_id"], row["name"], row["why"]) for item in held for row in item["devices"]} >= {
        (hardware.device_id, "Answered Sensor", HELD_GONE)
    }

    await _readded(hass, hardware)
    assert coord.power_view(hardware.device_id)["words"] == "CR2032"
    assert coord.type_view(hardware.device_id)["words"] == "Motion Sensor"


async def test_answers_go_with_the_purge(hass: HomeAssistant, hass_ws_client, hass_storage):
    hardware = Hardware(hass, "ra2", "Purged Answers")
    coord = await setup_coordinator(hass)
    client = await _client(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=hardware.device_id,
              choice="AAA", quantity=2)
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 31 * DAY

    await coord._on_midnight(None)
    await hass.async_block_till_done()

    assert hardware.device_id not in coord._power_entries
    await hass.config_entries.async_unload(coord.entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[ANSWERS_STORE_KEY]["data"]["power"]["devices"]
    assert hardware.device_id not in saved


async def test_a_device_with_no_record_takes_its_answers_at_once(hass: HomeAssistant, hass_ws_client):
    """Only a held record holds answers: with none, the removal takes
    them as before (0.24.7)."""
    hardware = Hardware(hass, "ra3", "No Record")
    coord = await setup_coordinator(hass)
    client = await _client(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=hardware.device_id,
              choice="AA", quantity=2)
    del coord.data[DATA_DEVICES][hardware.device_id]

    await _removed(hass, hardware)

    assert hardware.device_id not in coord._power_entries


def _made_by(hass, device_id, maker, model, model_id):
    dr.async_get(hass).async_update_device(
        device_id, manufacturer=maker, model=model, model_id=model_id
    )


async def test_a_model_answer_passes_to_another_device_at_once(hass: HomeAssistant, hass_ws_client):
    first = Hardware(hass, "rm1", "Model One")
    second = Hardware(hass, "rm2", "Model Two")
    for hardware in (first, second):
        _made_by(hass, hardware.device_id, "Unlisted Maker", "Unlisted Sensor", "UL-1")
    coord = await setup_coordinator(hass)
    client = await _client(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=first.device_id,
              choice="AAA", quantity=2)
    (entry,) = coord._power_models.values()
    assert entry["device_id"] == first.device_id

    await _removed(hass, first)

    (entry,) = coord._power_models.values()
    assert entry["device_id"] == second.device_id
    assert coord.power_view(second.device_id)["words"] == "2× AAA"


async def test_the_last_of_a_model_holds_the_model_answer(hass: HomeAssistant, hass_ws_client):
    only = Hardware(hass, "rm3", "Model Only")
    _made_by(hass, only.device_id, "Unlisted Maker", "Lone Sensor", "UL-2")
    coord = await setup_coordinator(hass)
    client = await _client(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_power", device_id=only.device_id,
              choice="AAA", quantity=2)

    await _removed(hass, only)
    assert len(coord._power_models) == 1, "the model answer went before the hold ended"

    only.add()
    # The integration names the maker again as it adds the device.
    _made_by(hass, only.device_id, "Unlisted Maker", "Lone Sensor", "UL-2")
    await registry_settled(hass)
    assert coord.power_view(only.device_id)["words"] == "2× AAA"


# ------------------------------------------------------------ mutes


async def _save_freeze_screen(hass: HomeAssistant, entry) -> None:
    """Save the Freeze screen as a person would: the held device is not
    offered, so its pick is not in what the form sends."""
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "freeze"})
    assert result["step_id"] == "freeze", result
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            CONF_FREEZE_DELTA_LOW: 3.0,
            CONF_FREEZE_DELTA_HIGH: 8.0,
            "freeze_muting": {
                CONF_FREEZE_MUTED_INTEGRATIONS: [],
                CONF_FREEZE_MUTED_LABELS: [],
                CONF_FREEZE_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "menu", result


async def test_mutes_are_kept_while_a_device_is_held(hass: HomeAssistant, caplog):
    hardware = Hardware(hass, "rq1", "Muted Sensor")
    other = Hardware(hass, "rq2", "Other Sensor")
    keys = (CONF_BATTERY_MUTED_DEVICES, CONF_FREEZE_MUTED_DEVICES, CONF_SIGNAL_MUTED_DEVICES)
    entry = await setup_entry(hass, {**{key: [hardware.device_id] for key in keys}, CONF_MUTED_DEVICES: [other.device_id]})
    coord = entry.runtime_data
    caplog.set_level(logging.INFO, logger="custom_components.device_sentinel")

    await _removed(hass, hardware)
    await _removed(hass, other)
    assert "the muting is kept 30 days in case the device comes back" in caplog.text

    # A save of a screen, which used to drop the picks.
    await _save_freeze_screen(hass, entry)
    for key in keys:
        assert hardware.device_id in entry.options.get(key, []), key
    assert other.device_id in entry.options.get(CONF_MUTED_DEVICES, [])

    await _readded(hass, hardware)
    await _readded(hass, other)
    assert coord._muted_devices.get(other.device_id) == "device"
    assert coord._freeze_muted(hardware.device_id)


async def test_mutes_go_on_the_first_save_after_the_purge(hass: HomeAssistant):
    hardware = Hardware(hass, "rq3", "Muted Then Purged")
    entry = await setup_entry(hass, {CONF_FREEZE_MUTED_DEVICES: [hardware.device_id]})
    coord = entry.runtime_data
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 31 * DAY
    await coord._on_midnight(None)

    await _save_freeze_screen(hass, entry)

    assert hardware.device_id not in entry.options.get(CONF_FREEZE_MUTED_DEVICES, [])


# ------------------------------------------------------------ found by review


async def test_a_composite_id_does_not_keep_a_hold_for_ever(hass: HomeAssistant, monkeypatch):
    """From Home Assistant 2026.8 the registry answers a device id from
    before the split with a made-up composite device. Presence is read
    from the registry walk, so such a hold is still purged, has no page
    and takes no model answer."""
    hardware = Hardware(hass, "rc1", "Old Composite")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    held_id = hardware.device_id
    real = dr.DeviceRegistry.async_get
    ghost = dr.async_get(hass).async_get_or_create(
        config_entry_id=hardware.source.entry_id, identifiers={("test", "ghost")}, name="Ghost"
    )

    def answering(self, device_id, *args, **kwargs):
        return ghost if device_id == held_id else real(self, device_id, *args, **kwargs)

    monkeypatch.setattr(dr.DeviceRegistry, "async_get", answering)
    assert coord.dashboard_device(held_id) is None
    assert held_id not in coord._power_same_model("anything")
    assert coord._device_name(held_id) == "Old Composite"
    coord.data[DATA_DEVICES][held_id][DEV_REMOVED_SINCE] -= 31 * DAY
    coord._purge_held_records(dt_util.utcnow().timestamp())
    assert held_id not in coord.data[DATA_DEVICES]


async def test_no_purge_just_after_the_clock_was_set(hass: HomeAssistant):
    hardware = Hardware(hass, "rc2", "Clock Step")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id][DEV_REMOVED_SINCE] -= 31 * DAY
    now = dt_util.utcnow().timestamp()
    coord._clock_reset = (now - 3600, 90 * DAY)
    coord._purge_held_records(now)
    assert hardware.device_id in coord.data[DATA_DEVICES], "a clock step purged a hold"
    coord._clock_reset = (now - 3 * DAY, 90 * DAY)
    coord._purge_held_records(now)
    assert hardware.device_id not in coord.data[DATA_DEVICES]


async def test_a_returning_device_is_judged_from_its_return(hass: HomeAssistant):
    """Its clock restarts when it comes back, so the days it was gone
    are not a silence it is judged on before its first report."""
    hardware = Hardware(hass, "rc3", "Back Quiet")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 5 * DAY
    await _removed(hass, hardware)
    await _readded(hass, hardware)
    assert record[DEV_LAST_ACTIVITY] > dt_util.utcnow().timestamp() - 60
    assert record[DEV_SET_ASIDE_SINCE] is not None, "the first gap must still be refused"


async def test_a_stamp_carried_back_by_an_older_release_resets_nothing(hass: HomeAssistant):
    """0.25.4 keeps an unknown field, so a device that came back while
    it ran still carries its removal stamp, with reports after it."""
    hardware = Hardware(hass, "rc4", "Downgraded")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    now = dt_util.utcnow().timestamp()
    record[DEV_REMOVED_SINCE] = now - 3 * DAY
    record[DEV_REMOVED_NAME] = "Downgraded"
    record[DEV_SET_ASIDE_SINCE] = None
    record[DEV_LAST_ACTIVITY] = now - 600
    coord._rebuild_registry_view()
    assert record[DEV_REMOVED_SINCE] is None
    assert record[DEV_SIGNAL_DAILY_P5] == [-70.0] * 10, "signal history wiped on a device that was back"
    assert record[DEV_LAST_ACTIVITY] == now - 600


async def test_a_section_pick_the_global_mute_covers_stays_away(hass: HomeAssistant):
    hardware = Hardware(hass, "rc5", "Double Muted")
    entry = await setup_entry(hass, {
        CONF_MUTED_DEVICES: [hardware.device_id], CONF_FREEZE_MUTED_DEVICES: [hardware.device_id],
    })
    await _removed(hass, hardware)
    await _save_freeze_screen(hass, entry)
    assert hardware.device_id in entry.options.get(CONF_MUTED_DEVICES, [])
    assert hardware.device_id not in entry.options.get(CONF_FREEZE_MUTED_DEVICES, [])


async def test_a_clock_restart_while_held_still_resets_on_return(hass: HomeAssistant):
    """Device Sentinel's own clock restarts (a clock step, a lost clocks
    file) move a held record's clock past its removal without the
    device saying anything: it is still welcomed back as returning."""
    hardware = Hardware(hass, "rc6", "Restarted While Held")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _learned(record)
    await _removed(hass, hardware)
    now = dt_util.utcnow().timestamp()
    record[DEV_REMOVED_SINCE] = now - 9 * DAY
    record[DEV_LAST_ACTIVITY] = now - 7 * DAY
    await _readded(hass, hardware)
    assert record[DEV_SIGNAL_DAILY_P5] == []
    assert record[DEV_LAST_ACTIVITY] > now - 60


async def test_a_device_never_heard_stays_never_reported(hass: HomeAssistant):
    hardware = Hardware(hass, "rc7", "Never Heard")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    record[DEV_LAST_ACTIVITY] = None
    await _removed(hass, hardware)
    await _readded(hass, hardware)
    assert record[DEV_LAST_ACTIVITY] is None


# ------------------------------------------------------------ found by the adversarial round


def _sick(record) -> None:
    now = dt_util.utcnow().timestamp()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - 4 * 3600.0
    record["battery_low"] = True
    record["battery_value"] = 4.0
    record["battery_since"] = dt_util.utcnow().isoformat()
    record["flap_drops"] = [now - 600.0 * i for i in range(12)]
    record["flap_since"] = now - 7200.0


async def test_a_hold_carries_no_flap_or_low_battery_back(hass: HomeAssistant):
    """Each verdict is formed again from what the device says when it
    returns: a re-paired device is often one with a new battery."""
    hardware = Hardware(hass, "ra4", "Sick Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _sick(record)
    record["battery_daily_value"] = [90.0, 80.0]
    await _removed(hass, hardware)
    assert (record["flap_since"], record["flap_drops"], record["flap_back"]) == (None, [], None)
    assert (record["battery_low"], record["battery_value"], record["battery_since"]) == (False, None, None)
    assert record["battery_daily_value"] == [90.0, 80.0], "the history stays"
    flapping_before = record["flap_back"]
    coord._track_flaps([], dt_util.utcnow().timestamp())
    assert record["flap_back"] == flapping_before, "a held record was judged for flapping"


async def test_the_problem_list_drops_a_held_row_at_once(hass: HomeAssistant):
    hardware = Hardware(hass, "ra5", "Row Device")
    coord = await setup_coordinator(hass)
    _sick(coord.data[DATA_DEVICES][hardware.device_id])
    coord.data[DATA_DEVICES][hardware.device_id][DEV_DAILY_MAX] = [3600.0] * 40
    coord._grace_until = 0
    coord._sync_problem_list()
    assert any(r.get("device_id") == hardware.device_id for r in coord.data["todo_items"])
    hardware.remove()
    await hass.async_block_till_done()
    coord._rebuild_and_notify()
    assert not any(r.get("device_id") == hardware.device_id for r in coord.data["todo_items"])
    rows = [r for r in coord.data.get("incidents", []) if isinstance(r, dict) and r.get("device_id") == hardware.device_id]
    assert any(r.get("cause") == "removed" for r in rows), "the timeline says set aside for a removed device"


async def test_the_trimmed_maximum_button_refuses_a_held_device(hass: HomeAssistant):
    hardware = Hardware(hass, "ra6", "Button Target")
    coord = await setup_coordinator(hass)
    await _removed(hass, hardware)
    coord.data[DATA_DEVICES][hardware.device_id]["lognormal_days"] = 12
    assert coord.use_trimmed_maximum(hardware.device_id) is False
    assert coord.data[DATA_DEVICES][hardware.device_id]["lognormal_days"] == 12


def test_a_name_in_a_log_line_stays_on_one_line():
    from custom_components.device_sentinel.coordinator import _plain

    assert _plain("Kitchen\r\nINJECTED") == "Kitchen  INJECTED"
    assert len(_plain("x" * 10_000)) == 120


# ------------------------------------------------------------ ruled 10 October, afternoon


@pytest.mark.skipif(not MULTI_OWNER_POSSIBLE, reason=MULTI_OWNER_GONE)
async def test_the_record_goes_with_the_id_home_assistant_gives_back(hass: HomeAssistant):
    """Below Home Assistant 2026.8 a removed device's id goes to any
    device sharing one of its addresses, a router's tracker included,
    which Home Assistant treats as the same device. The record follows
    the id (James, 10 October 2026: follow Home Assistant); the first gap
    is refused either way."""
    esphome = MockConfigEntry(domain="esphome", title="ESPHome")
    router = MockConfigEntry(domain="tplink_router", title="Router")
    for source in (esphome, router):
        source.add_to_hass(hass)
        source.mock_state(hass, ConfigEntryState.LOADED)
    registry = dr.async_get(hass)
    mac = {("mac", "aa:bb:cc:dd:ee:01")}
    board = registry.async_get_or_create(
        config_entry_id=esphome.entry_id, identifiers={("esphome", "board1")}, connections=mac, name="Board"
    )
    er.async_get(hass).async_get_or_create("sensor", "esphome", "board1", device_id=board.id, config_entry=esphome)
    coord = await setup_coordinator(hass)
    _learned(coord.data[DATA_DEVICES][board.id])
    registry.async_remove_device(board.id)
    await registry_settled(hass)
    tracker = registry.async_get_or_create(config_entry_id=router.entry_id, connections=mac)
    er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "board1_tracker", device_id=tracker.id, config_entry=router
    )
    await registry_settled(hass)
    assert tracker.id == board.id
    record = coord.data[DATA_DEVICES][board.id]
    assert record[DEV_DAILY_MAX] == [3600.0] * 30 and record[DEV_REMOVED_SINCE] is None
    assert record[DEV_SET_ASIDE_SINCE] is not None, "the first gap must still be refused"


async def test_a_removal_noticed_at_startup_fires_its_withdrawal(hass: HomeAssistant):
    """Removed while Home Assistant was stopped: the fault an automation
    paired with the row gets its closing event, inside the startup grace."""
    hardware = Hardware(hass, "ro3", "Gone While Down")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _sick(record)
    record[DEV_DAILY_MAX] = [3600.0] * 40
    coord._sync_problem_list()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hardware.remove()
    await hass.async_block_till_done()
    fired = []
    hass.bus.async_listen("device_sentinel_withdrawn", lambda event: fired.append(dict(event.data)))
    hass.bus.async_listen("device_sentinel_recovered", lambda event: fired.append({"recovered": True}))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await registry_settled(hass)
    coord = entry.runtime_data
    assert coord._in_startup_grace()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert [event.get("reason") for event in fired] == ["removed"], fired


async def test_a_device_leaving_with_several_problems_is_told_once(hass: HomeAssistant, hass_ws_client):
    hardware = Hardware(hass, "ro4", "Three Problems")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0
    record = coord.data[DATA_DEVICES][hardware.device_id]
    _sick(record)
    record[DEV_DAILY_MAX] = [3600.0] * 40
    coord._sync_problem_list()
    await _removed(hass, hardware)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = str(getattr(coord, "_last_brief_text", "") or "")
    assert text.count("was removed from Home Assistant") == 1, text[:1200]
    assert text.count("| removed from Home Assistant |") == 1
    client = await _client(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/brief")
    assert [e["what"] for e in reply["result"]["events"]].count("removed from Home Assistant") == 1
