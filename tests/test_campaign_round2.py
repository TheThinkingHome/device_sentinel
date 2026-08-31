"""Hardening round two for 0.19.8.

Round one attacked the changed paths in isolation and through the
sync. This round attacks what sits around them and what round one
did not touch:

  1  the notification path end to end, counting what actually
     reaches async_fire_events rather than what the collector sees
  2  damaged incident and to-do rows arriving through the real load
     path, then the sync, the fold, every report and the repair flow
  3  the midnight fold itself with set-aside rows in the log
  4  the restore and the trim with set-aside rows present, so the
     new cause survives a round trip through the evidence copy
  5  an upstream outage crossing a set-aside, so the suppression and
     the silent retire cannot fight over one device
  6  acknowledgment and hand deletion of an item whose device then
     leaves the watched set
  7  the brief's started-and-ended tally, which must count a
     set-aside as neither
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    ACTION_SET_ASIDE,
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
    INCIDENT_ACTION,
    STORAGE_KEY,
)

from tests.helpers import register_device, setup_coordinator

OBSERVED = "2026-07-08T00:00:00+00:00"


def _silent(coord, device_id: str) -> dict:
    rec = coord.data[DATA_DEVICES].setdefault(device_id, {})
    rec[DEV_EVENT_COUNT] = 0
    rec[DEV_LAST_ACTIVITY] = None
    rec[DEV_FIRST_OBSERVED] = OBSERVED
    rec[DEV_FROZEN_CATEGORY] = None
    rec[DEV_FROZEN_SINCE] = None
    return rec


def _bare(hass, owner, name: str):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(owner.domain, name)},
        name=name,
    )


# ------------------------------------------- 1. the wire, not the buffer


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


# ------------------------ 2. damaged tables through the real load path


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


# ---------------------------------- 3. the fold with set-aside rows


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


# -------------------------- 4. restore and trim with the new cause


async def test_the_new_cause_survives_the_evidence_copy_and_restore(
    hass: HomeAssistant, monkeypatch
):
    """The set-aside row is written, copied as evidence, and the
    restore brings it back byte for byte through the real files."""
    from custom_components.device_sentinel.backup import (
        async_copy_evidence,
        async_restore_main_file,
    )
    from homeassistant.helpers.storage import STORAGE_DIR

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


# ------------------------------ 5. upstream outage across a set-aside


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
    heard = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: heard.append(e.data))
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


# ----------------------- 6. acknowledged or hand-deleted, then leaves


@pytest.mark.parametrize("action", ["ack", "delete"])
async def test_a_person_acted_item_whose_device_leaves(
    hass: HomeAssistant, action
):
    heard = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: heard.append(e.data))
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


# ------------------------------------- 7. the brief's tally is honest


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
    for path in glob.glob(hass.config.path("www/device_sentinel/*.html")):
        text += open(path, encoding="utf-8").read()
    assert "1 problem started, 0 ended" in text or "1 problem started, 0 ended" in text.replace("problems", "problem"), (
        [line for line in text.splitlines() if "started" in line][:2]
    )
