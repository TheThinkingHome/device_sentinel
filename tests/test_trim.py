# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_trim.py, Version: 0.16.7 (2026-08-20)

"""The trim choosers: erasing one device's history on purpose."""
from __future__ import annotations

import json
import os

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_MUTED_DEVICES,
    CONF_TRIM_DEVICES,
    CONF_TRIM_INTEGRATIONS,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DEV_SIGNAL_DAILY_P5,
    INC_DEVICE_ID,
    SYS_KIND,
    SYS_TRIMMED,
    TODO_DEVICE_ID,
    TRIM_BACKUP_DIR,
)

from tests.helpers import register_device, setup_entry


def _furnish(coord, device_id: str, name: str) -> None:
    """Give a device every kind of history a trim must remove."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_SIGNAL_DAILY_P5] = [120.0, 118.0]
    coord.data.setdefault(DATA_EPISODES, []).append(
        {INC_DEVICE_ID: device_id, "name": name, "since": 1.0}
    )
    coord.data.setdefault(DATA_INCIDENTS, []).append(
        {INC_DEVICE_ID: device_id, "name": name, "when": 1.0}
    )
    coord.data.setdefault(DATA_TODO_ITEMS, []).append(
        {TODO_DEVICE_ID: device_id, "summary": f"{name}: frozen"}
    )


async def _save_options(hass: HomeAssistant, entry, **changes) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, **changes}
    )
    await hass.async_block_till_done()


async def test_a_device_trim_removes_its_history_and_nothing_else(
    hass: HomeAssistant,
):
    """Records, episodes, incidents and list items go; the other
    device keeps all four (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr1", "Trim Me")
    keeper, _ = register_device(hass, "tr2", "Leave Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")
    _furnish(coord, keeper.id, "Leave Me")

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    # The record is not absent: the registry rebuild recreates it at
    # once, which is the designed outcome and is why the help text
    # says the device reappears. What must be gone is its history.
    assert coord.data[DATA_DEVICES][target.id][DEV_SIGNAL_DAILY_P5] == []
    assert coord.data[DATA_DEVICES][keeper.id][
        DEV_SIGNAL_DAILY_P5
    ] == [120.0, 118.0]
    for key, field in (
        (DATA_EPISODES, INC_DEVICE_ID),
        (DATA_INCIDENTS, INC_DEVICE_ID),
    ):
        owners = {row[field] for row in coord.data[key]}
        assert target.id not in owners
        assert keeper.id in owners
    # The problem list is not checked for the survivor here: the
    # options save rebuilds it from live verdicts, so a synthetic row
    # for a healthy device is correctly gone whether or not anything
    # was trimmed. That the trim removes the target's items is
    # covered by trim_devices itself.
    assert target.id not in {
        row[TODO_DEVICE_ID] for row in coord.data[DATA_TODO_ITEMS]
    }


async def test_the_pickers_empty_themselves(hass: HomeAssistant):
    """Otherwise the next save of any setting deletes again, and the
    person could never touch Advanced without re-erasing (ruling
    #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr3", "Trim Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    assert entry.options[CONF_TRIM_DEVICES] == []
    assert entry.options[CONF_TRIM_INTEGRATIONS] == []


async def test_the_copy_is_written_before_anything_is_deleted(
    hass: HomeAssistant,
):
    """The copy is the only way back, so it lands first and it holds
    what the deletion is about to remove (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr4", "Trim Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    folder = hass.config.path(TRIM_BACKUP_DIR)
    written = sorted(os.listdir(folder))
    assert any(name.endswith(".storage.json") for name in written)
    assert any(name.endswith(".clocks.json") for name in written)
    copy = json.load(
        open(
            os.path.join(
                folder,
                next(
                    n for n in written if n.endswith(".storage.json")
                ),
            )
        )
    )
    # The copy predates the deletion, so it still holds the history
    # that live storage no longer has.
    assert copy[DATA_DEVICES][target.id][DEV_SIGNAL_DAILY_P5] == [
        120.0,
        118.0,
    ]
    assert coord.data[DATA_DEVICES][target.id][DEV_SIGNAL_DAILY_P5] == []


async def test_trimming_keeps_the_exclusion(hass: HomeAssistant):
    """A trimmed device is rediscovered in seconds, and trimming data
    is not a statement about wanting the device gone (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr5", "Trim Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")

    await _save_options(
        hass,
        entry,
        **{
            CONF_MUTED_DEVICES: [target.id],
            CONF_TRIM_DEVICES: [target.id],
        },
    )

    assert entry.options[CONF_MUTED_DEVICES] == [target.id]
    assert coord.data[DATA_DEVICES][target.id][DEV_SIGNAL_DAILY_P5] == []


async def test_trimming_an_empty_device_is_allowed(
    hass: HomeAssistant,
):
    """Idempotent on purpose: a faulty record can read as empty, and
    that is the device a person will be told to pick (ruling #307).
    """
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr6", "Nothing Here")
    coord._rebuild_registry_view()
    coord.data[DATA_DEVICES].pop(target.id, None)

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    kinds = [row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]]
    assert SYS_TRIMMED in kinds


async def test_an_integration_trim_takes_every_device_on_it(
    hass: HomeAssistant,
):
    """And leaves other integrations untouched (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    one, _ = register_device(hass, "tr7", "First")
    two, _ = register_device(hass, "tr8", "Second")
    coord._rebuild_registry_view()
    _furnish(coord, one.id, "First")
    _furnish(coord, two.id, "Second")
    domain = coord._watched[one.id]

    await _save_options(
        hass, entry, **{CONF_TRIM_INTEGRATIONS: [domain]}
    )

    assert coord.data[DATA_DEVICES][one.id][DEV_SIGNAL_DAILY_P5] == []
    assert coord.data[DATA_DEVICES][two.id][DEV_SIGNAL_DAILY_P5] == []


async def test_the_trim_writes_a_system_event(hass: HomeAssistant):
    """It lands in the histories and the brief reports it, because it
    is the one destructive act done on a person's instruction
    (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr9", "Trim Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    events = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_TRIMMED
    ]
    assert len(events) == 1
    assert "Trim Me" in (events[0].get("detail") or "")
    sentence = coord._system_event_sentence(events[0])
    assert "erased" in sentence.lower()


async def test_system_events_survive_a_trim(hass: HomeAssistant):
    """They belong to the house, not to any device: a restart that
    happened is still a restart that happened (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr10", "Trim Me")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Trim Me")
    before = len(coord.data[DATA_SYSTEM_EVENTS])

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    # Nothing removed, and the trim's own event added.
    assert len(coord.data[DATA_SYSTEM_EVENTS]) > before


async def test_two_trims_in_one_second_keep_both_copies(
    hass: HomeAssistant,
):
    """The copy is the only way back, so it is never overwritten.

    Found adversarially: the first stamp was the clock to the second
    and the code comment said no person could collide it. The test
    collided it on the first attempt, and a person saving the screen
    twice in a hurry does the same, which is precisely when they are
    most likely to want the earlier copy (ruling #307).
    """
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "tr11", "Twice Over")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Twice Over")

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})
    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    folder = hass.config.path(TRIM_BACKUP_DIR)
    copies = [
        name
        for name in os.listdir(folder)
        if name.endswith(".storage.json")
    ]
    assert len(copies) == 2


async def test_the_section_arrives_nested_and_stores_flat(
    hass: HomeAssistant,
):
    """A real save sends the pair inside its Data Trim section.

    The screen groups them under a collapsed heading, so Home
    Assistant hands them back nested. The stored keys stay flat,
    because the coordinator reads them by name and a section is a way
    of drawing a screen rather than a change to what is stored
    (ruling #307).
    """
    from homeassistant.data_entry_flow import FlowResultType

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "sec1", "Sectioned")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Sectioned")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    assert result["step_id"] == "advanced"
    assert "data_trim" in result["data_schema"].schema

    current = dict(entry.options)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **{
                key: value
                for key, value in current.items()
                if key
                in (
                    "settle_share_pct",
                    "episode_share_pct",
                    "repeat_floor",
                    "taint_floor_minutes",
                    "taint_share_pct",
                    "storage_write_minutes",
                    "history_days",
                    "maintenance_minutes",
                )
            },
            "data_trim": {CONF_TRIM_DEVICES: [target.id]},
        },
    )
    assert result["type"] is FlowResultType.MENU
    await hass.async_block_till_done()

    # Flat in storage, emptied after the trim, and the history gone.
    assert entry.options[CONF_TRIM_DEVICES] == []
    assert "data_trim" not in entry.options
    assert coord.data[DATA_DEVICES][target.id][
        DEV_SIGNAL_DAILY_P5
    ] == []


async def test_an_ignored_device_is_named_not_numbered(
    hass: HomeAssistant,
):
    """The event names a set-aside device, not its id (ruling #307).

    Found on the first live trim: an ignored television was erased
    and the brief recorded a thirty-two character hex id, because the
    name lookup read the watched map alone while the picker had been
    widened to every detected device. An event naming a device by id
    answers nothing a month later.
    """
    from homeassistant.helpers import device_registry as dr

    from custom_components.device_sentinel.const import (
        CONF_EXCLUDED_INTEGRATIONS,
    )

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "ig1", "The Television")
    coord._rebuild_registry_view()
    domain = coord._watched[target.id]

    # Ignore its integration, which sets the device aside and takes
    # it out of the watched name map.
    await _save_options(
        hass, entry, **{CONF_EXCLUDED_INTEGRATIONS: [domain]}
    )
    assert target.id in coord._set_aside

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    event = next(
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_TRIMMED
    )
    detail = event.get("detail") or ""
    assert "The Television" in detail
    assert target.id not in detail
    # Ignoring sets a device aside at once but its record survives
    # until the next fold discards it, so this trim did have
    # something to take.
    assert "1 records" in detail
    assert dr.async_get(hass).async_get(target.id) is not None


async def test_a_trim_with_nothing_to_take_says_why(
    hass: HomeAssistant,
):
    """On the first live trim an ignored television whose record had
    already gone at a fold produced "nothing recorded", which reads
    as a failed tool rather than a completed no-op (ruling #307)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "empty1", "Already Gone")
    coord._rebuild_registry_view()
    coord.data[DATA_DEVICES].pop(target.id, None)

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    event = next(
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_TRIMMED
    )
    detail = event.get("detail") or ""
    assert "Already Gone" in detail
    assert "nothing was recorded for it" in detail


async def test_the_trim_pickers_are_not_a_settings_change(
    hass: HomeAssistant,
):
    """One deed, one row. The pickers move twice per trim, once when
    picked and once when the save empties them, so naming them put
    three events in the brief for one action (ruling #307)."""
    from custom_components.device_sentinel.const import (
        SYS_OPTIONS_CHANGED,
    )

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    target, _ = register_device(hass, "noise1", "Quiet Trim")
    coord._rebuild_registry_view()
    _furnish(coord, target.id, "Quiet Trim")
    before = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_OPTIONS_CHANGED
    ]

    await _save_options(hass, entry, **{CONF_TRIM_DEVICES: [target.id]})

    after = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_OPTIONS_CHANGED
    ]
    assert len(after) == len(before)
    assert (
        len(
            [
                row
                for row in coord.data[DATA_SYSTEM_EVENTS]
                if row[SYS_KIND] == SYS_TRIMMED
            ]
        )
        == 1
    )
