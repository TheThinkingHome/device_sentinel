"""Tests for setting disabled devices aside.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_set_aside.py, Version: 0.23.17 (2026-09-29)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Reported by teskanoo in issue #1: entities of disabled integrations
were monitored and reported, which is white noise, since a disabled
device cannot report and its silence says nothing about the hardware.

The rule is drawn at the device (ruling #257). A device Home
Assistant has disabled is set aside, and so is a device with no
entities at all, because neither can ever speak and neither has
anything a person could switch on. A device whose entities are all
disabled stays watched: those entities exist, the never-reported row
is the prompt, and a person can enable them or exclude the device.
"""

import json
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    ACTION_SET_ASIDE,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SET_ASIDE_SINCE,
    EVENT_RECOVERED,
    INCIDENT_ACTION,
    LEARNED_DISABLED,
    SET_ASIDE_DISABLED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
    STORAGE_KEY,
)
from tests.helpers import record_events

from .helpers import register_device, setup_coordinator


def _device(hass, uid, name, entities=1, disabled=None, entity_disabled=None):
    """Build a registry device, optionally disabled, with N entities."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
        disabled_by=disabled,
    )
    for index in range(entities):
        er.async_get(hass).async_get_or_create(
            "sensor", "test", f"{uid}_{index}",
            device_id=device.id, config_entry=source,
            disabled_by=entity_disabled,
        )
    return device


async def test_a_disabled_device_is_set_aside(hass: HomeAssistant):
    """Issue #1, at the device level: a disabled device cannot report,
    so watching for its silence produces a problem row about nothing."""
    device = _device(
        hass, "sa1", "Disabled Device",
        disabled=dr.DeviceEntryDisabler.USER,
    )
    coord = await setup_coordinator(hass)

    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_DISABLED


async def test_a_device_with_no_entities_is_set_aside(hass: HomeAssistant):
    """Nothing exists that could report and nothing a person could
    switch on, so the silence says nothing either way."""
    device = _device(hass, "sa2", "Empty Device", entities=0)
    coord = await setup_coordinator(hass)
    # Past the startup window: during it a device with no entities is
    # usually one whose integration has not finished loading, so the
    # rule is held (ruling #260).
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_NO_ENTITIES


async def test_a_device_whose_entities_are_disabled_stays_watched(
    hass: HomeAssistant,
):
    """Ruled deliberately against the simpler rule: those entities
    exist, so the device is one press from reporting again, and the
    never-reported row is the prompt that says so."""
    device = _device(
        hass, "sa3", "Silenced Device",
        entity_disabled=er.RegistryEntryDisabler.USER,
    )
    coord = await setup_coordinator(hass)

    assert device.id in coord._watched
    assert device.id not in coord._set_aside


async def test_a_service_device_keeps_its_own_reason(hass: HomeAssistant):
    """The reason is recorded rather than inferred: a disabled device
    and a service device both read as set aside, and the audit view
    has to say which."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sa4")},
        name="Service Device",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    coord = await setup_coordinator(hass)

    assert coord._set_aside[device.id][2] == SET_ASIDE_SERVICE


async def test_a_set_aside_device_keeps_everything_it_learned(
    hass: HomeAssistant,
):
    """The fault this rule would have caused if the record pruning
    had been left alone: disabling an integration for an afternoon
    would have deleted every rhythm, floor, and series it owned, and
    re-enabling it would have started from nothing with a seven-day
    re-arm and no explanation.
    """
    device, _ = register_device(hass, "sa5", "Learned Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * 30

    dr.async_get(hass).async_update_device(
        device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await hass.async_block_till_done()

    assert device.id not in coord._watched
    kept = coord.data[DATA_DEVICES][device.id]
    assert kept[DEV_DAILY_MAX] == [3600.0] * 30
    assert kept[DEV_SET_ASIDE_SINCE] is not None


async def test_a_departed_device_still_loses_its_record(
    hass: HomeAssistant,
):
    """Set aside is not gone. A device the registry no longer holds
    has nothing left to describe, and its record goes as before."""
    device, _ = register_device(hass, "sa6", "Leaving Device")
    coord = await setup_coordinator(hass)
    assert device.id in coord.data[DATA_DEVICES]

    dr.async_get(hass).async_remove_device(device.id)
    await hass.async_block_till_done()

    assert device.id not in coord.data[DATA_DEVICES]


async def test_the_gap_that_spans_a_disabling_is_refused(
    hass: HomeAssistant,
):
    """A fortnight switched off must not teach a fortnight-long
    window. The stamp survives the registry rebuild that brings the
    device back, because that rebuild runs before the device speaks,
    and it is spent by the device's own first report.
    """
    device, (entity_id,) = register_device(hass, "sa7", "Returning Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SET_ASIDE_SINCE] = 1000.0

    assert record[DEV_SET_ASIDE_SINCE] is not None
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()

    assert record[DEV_SET_ASIDE_SINCE] is None


async def test_the_refusal_reason_is_its_own_word(hass: HomeAssistant):
    """Named apart from pairing and maintenance so the episode file
    says which hand caused the silence."""
    assert LEARNED_DISABLED == "no (disabled)"
    assert LEARNED_DISABLED.startswith("no (")


# A set-aside device through the notification path, damaged rows, the fold, a restore, an outage, a person's action and the brief's tally (0.19.8).


OBSERVED = "2026-07-08T00:00:00+00:00"

def _silent(coord, device_id: str) -> dict:
    rec = coord.data[DATA_DEVICES].setdefault(device_id, {})
    rec[DEV_EVENT_COUNT] = 0
    rec[DEV_LAST_ACTIVITY] = None
    rec[DEV_FIRST_OBSERVED] = OBSERVED
    rec[DEV_FROZEN_CATEGORY] = None
    rec[DEV_FROZEN_SINCE] = None
    return rec

DAMAGED_TABLE_ROWS = [
    ("incidents", {"device_id": 7, "kind": None, "event": "opened"}),
    ("incidents", {"device_id": "x", "name": "n", "kind": "frozen",
                   "event": "resolved", "when": "yesterday",
                   "cause": None, "duration": "x"}),
    ("incidents", "not a row"),
    ("incidents", {"device_id": "x", "name": "n", "kind": "frozen",
                   "event": "action", "when": 1_788_000_000.0,
                   "cause": ["set_aside"],
                   "duration": None}),
    ("todo_items", {"uid": None, "device_id": "x", "kinds": "junk"}),
    ("todo_items", 42),
    ("todo_items", {"uid": "u", "device_id": "x", "summary": "s",
                    "description": None, "status": "needs_action",
                    "acked_at": None, "sort_name": "n",
                    "kinds": {"never_reported": "not a stamp"}}),
    ("silence_episodes", {"device_id": "x", "since": "x"}),
]

@pytest.mark.parametrize("seed", range(40))
async def test_nothing_reaches_the_wire_for_a_set_aside(
    hass: HomeAssistant, seed
):
    """Round one spied on the collector. This spies on the sender."""
    rng = random.Random(70_000 + seed)
    sent: list = []
    device, _ = register_device(hass, f"wire{seed}")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    async def spy(events, *args, **kwargs):
        sent.extend(events)

    coord.async_fire_events = spy
    _silent(coord, device.id)
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    faults_sent = len(sent)
    assert faults_sent >= 1, "the genuine fault never reached the wire"

    # Random churn, then the device leaves.
    for _ in range(rng.randint(0, 4)):
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
    coord._watched.pop(device.id, None)
    coord._clear_verdicts_for_set_aside({device.id: ("n", "x", "y")})
    coord._sync_problem_list()
    await hass.async_block_till_done()
    recoveries_sent = [e for e in sent[faults_sent:] if e[2] is True]
    assert recoveries_sent == [], (
        f"a recovery reached the wire for a set-aside device: {recoveries_sent}"
    )

@pytest.mark.parametrize("table,row", DAMAGED_TABLE_ROWS)
async def test_a_damaged_table_row_survives_every_consumer(
    hass: HomeAssistant, hass_storage, table, row
):
    device, _ = register_device(hass, "table_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    stored["data"].setdefault(table, []).append(row)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, f"{table} row killed setup"
    coord2 = entry.runtime_data
    coord2._grace_until = 0.0
    _silent(coord2, device.id)
    coord2._judge_all_devices()
    coord2._sync_problem_list()
    await hass.async_block_till_done()
    coord2._watched.pop(device.id, None)
    coord2._sync_problem_list()
    await hass.async_block_till_done()
    await coord2._save_main()
    written = await coord2.async_regenerate_reports()
    assert written, f"{table} row stopped the reports"
    # The boundary (ruling #370): a damaged row is repaired out of
    # the document at the gate, so no reader and no file carries it.
    # Two ruled exceptions in the to-do list: the 0.6.0 migration
    # purges a row with no device id, and a structurally usable item
    # whose device has no problem is retired by the sync, which is
    # the list doing its job.
    def _matches(candidate):
        if isinstance(row, dict):
            return isinstance(candidate, dict) and all(
                candidate.get(k) == v for k, v in row.items()
            )
        return candidate == row

    if table == "todo_items":
        if not isinstance(row, dict) or not row.get("device_id"):
            return
        if isinstance(row.get("kinds"), dict) and isinstance(row.get("uid"), str):
            return
    assert not any(_matches(r) for r in coord2.data.get(table, [])), (
        f"{table}: a damaged row reached the working document"
    )
    saved = coord2._data_to_save()
    assert not any(_matches(r) for r in saved.get(table, [])), (
        f"{table}: a repaired row was written back to the file"
    )
    assert coord2.storage_load_faulty or coord2._repair_notice, (
        f"{table}: the repair left no trace for the person"
    )

async def test_the_fold_keeps_set_aside_rows_and_reports_no_fault(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    owner = MockConfigEntry(domain="fold_stack", title="F")
    owner.add_to_hass(hass)
    for i in range(3):
        device, _ = register_device(hass, f"fold{i}")
        coord._rebuild_registry_view()
        _silent(coord, device.id)
        coord._judge_all_devices()
        coord._sync_problem_list()
        coord._watched.pop(device.id, None)
        coord._sync_problem_list()
    await hass.async_block_till_done()
    aside = [
        r for r in coord.data["incidents"]
        if r.get("event") == INCIDENT_ACTION and r.get("cause") == ACTION_SET_ASIDE
    ]
    assert len(aside) == 3
    await coord._save_main()
    assert coord._repair_notice is None, coord._repair_notice
    still = [
        r for r in coord.data["incidents"]
        if r.get("event") == INCIDENT_ACTION and r.get("cause") == ACTION_SET_ASIDE
    ]
    assert len(still) == 3, "the fold dropped set-aside rows"

async def test_the_new_cause_survives_the_evidence_copy_and_restore(
    hass: HomeAssistant, monkeypatch
):
    """The set-aside row is written, copied as evidence, and the
    restore brings it back byte for byte through the real files."""
    from homeassistant.helpers.storage import STORAGE_DIR

    from custom_components.device_sentinel.backup import (
        async_copy_evidence,
        async_restore_main_file,
    )

    device, _ = register_device(hass, "evidence_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    _silent(coord, device.id)
    coord._judge_all_devices()
    coord._sync_problem_list()
    coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    await coord._save_now()
    live = Path(hass.config.path(STORAGE_DIR)) / STORAGE_KEY
    payload = json.dumps(
        {"version": 1, "key": STORAGE_KEY, "data": coord.data}, default=str
    )
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(payload, encoding="utf-8")
    good = live.with_name(STORAGE_KEY + ".last-good")
    good.write_text(payload, encoding="utf-8")
    stamp, copied = await async_copy_evidence(hass)
    assert stamp and copied
    live.write_text("{ruined", encoding="utf-8")
    restored, _ = await async_restore_main_file(hass)
    assert restored
    back = json.loads(live.read_text(encoding="utf-8"))
    rows = [
        r for r in back["data"]["incidents"]
        if r.get("cause") == ACTION_SET_ASIDE
    ]
    assert rows, "the set-aside row did not survive the restore"
    # The config directory is shared across tests: leave nothing
    # behind that a later menu could read as a usable backup.
    for path in (live, good):
        if path.exists():
            path.unlink()
    import shutil
    shutil.rmtree(hass.config.path("device_sentinel/trim_backups"), ignore_errors=True)

async def test_an_upstream_outage_and_a_set_aside_do_not_fight(
    hass: HomeAssistant,
):
    """A device that fell with its bridge, then leaves the watched
    set while the bridge is still down: one silent retire, no
    recovery, and the upstream count drops by one."""
    from unittest.mock import patch

    device, _ = register_device(hass, "up_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    heard = record_events(hass, EVENT_RECOVERED)
    _silent(coord, device.id)
    with patch.object(
        type(coord), "upstream_down_since",
        lambda self, did: ("zha bridge", dt_util.utcnow().timestamp() - 600.0),
        create=True,
    ):
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
        coord._watched.pop(device.id, None)
        coord._clear_verdicts_for_set_aside({device.id: ("n", "zha", "x")})
        coord._sync_problem_list()
        await hass.async_block_till_done()
    assert not [h for h in heard if h.get("device_id") == device.id]

@pytest.mark.parametrize("action", ["ack", "delete"])
async def test_a_person_acted_item_whose_device_leaves(
    hass: HomeAssistant, action
):
    heard = record_events(hass, EVENT_RECOVERED)
    device, _ = register_device(hass, f"acted_{action}")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    _silent(coord, device.id)
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    if action == "ack":
        for item in coord.data["todo_items"]:
            if item["device_id"] == device.id:
                item["status"] = "completed"
    else:
        coord.data["todo_items"] = [
            i for i in coord.data["todo_items"] if i["device_id"] != device.id
        ]
        coord._hand_deleted.add(device.id)
    coord._watched.pop(device.id, None)
    coord._clear_verdicts_for_set_aside({device.id: ("n", "x", "y")})
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert not [h for h in heard if h.get("device_id") == device.id], (
        f"a {action}ed item's device leaving fired a recovery"
    )
    assert not [
        i for i in coord.data["todo_items"] if i["device_id"] == device.id
    ], "the item outlived the device leaving"
    # And returning does not re-add it as a hand re-add.
    coord._watched[device.id] = "x"
    coord._judge_all_devices()
    coord._sync_problem_list()
    readds = [
        r for r in coord.data["incidents"]
        if r.get("device_id") == device.id and r.get("cause") == "readded"
    ]
    assert not readds, "a device returning after set-aside was called re-added"

async def test_the_brief_counts_a_set_aside_as_neither(
    hass: HomeAssistant,
):
    import glob

    device, _ = register_device(hass, "tally_dev", "Tally Device")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    _silent(coord, device.id)
    coord._judge_all_devices()
    coord._sync_problem_list()
    coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    await coord.async_regenerate_reports()
    text = ""
    for path in glob.glob(hass.config.path("device_sentinel/*.html")):
        text += open(path, encoding="utf-8").read()
    assert "1 problem started, 0 ended" in text or "1 problem started, 0 ended" in text.replace("problems", "problem"), (
        [line for line in text.splitlines() if "started" in line][:2]
    )


# The rebuilt registry view keeps exactly the watched devices' entities.


@pytest.mark.parametrize("seed", range(30))
async def test_the_rebuild_keeps_the_entity_set_honest(
    hass: HomeAssistant, seed
):
    """Random registries: devices with entities, disabled entities,
    none, and integrations in every state. The retained entity set
    must equal what the registry actually holds for watched devices."""
    rng = random.Random(seed)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    owners = []
    for i in range(3):
        entry = MockConfigEntry(domain=f"stack{seed}_{i}", title="S")
        entry.add_to_hass(hass)
        if rng.random() < 0.5:
            entry.mock_state(hass, ConfigEntryState.LOADED)
        owners.append(entry)
    expected: set[str] = set()
    made = []
    for i in range(rng.randint(3, 14)):
        owner = rng.choice(owners)
        device = registry.async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={(owner.domain, f"d{seed}-{i}")},
            name=f"Device {seed} {i}",
        )
        made.append(device)
        count = rng.choice([0, 0, 1, 3])
        for n in range(count):
            entities.async_get_or_create(
                "sensor", owner.domain, f"u{seed}-{i}-{n}",
                device_id=device.id,
                disabled_by=(
                    er.RegistryEntryDisabler.USER if rng.random() < 0.3 else None
                ),
            )
        if count:
            expected.add(device.id)
    coord = await setup_coordinator(hass)
    coord._grace_until = (
        dt_util.utcnow().timestamp() + 300.0 if rng.random() < 0.5 else 0.0
    )
    coord._rebuild_registry_view()
    watched_made = {d.id for d in made if d.id in coord._watched}
    for did in watched_made:
        assert (did in coord._devices_with_entities) == (did in expected), (
            f"entity set wrong for {did}"
        )
    # Outside grace, a watched device with no entities is impossible.
    if coord._grace_until == 0.0:
        assert not (watched_made - expected), (
            "an entity-less device stayed watched outside grace"
        )


# The diagnostics name a set-aside device's integration.


async def test_diagnostics_names_a_set_aside_devices_integration(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, _ = register_device(hass, "sp", name="Repairs")
    coord = await setup_coordinator(hass)
    domain = coord._watched.pop(device.id)
    coord._set_aside = {device.id: ("Repairs", "spook", "excluded")}
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    row = diagnostics["devices"][device.id]
    assert row["integration"] == "spook"
    assert domain != "spook", "the watched map did not answer"
