# Tests for 0.18.8, Verify Offers Restore (rulings #353 through #357).
#
# A file that will not parse restores automatically (ruling #345,
# unchanged). A file that loads but verifies faulty raises one
# fixable card offering Restore Backup, Trim Record, and Ignore
# (rulings #353, #354, #355). The load survives what Verify finds
# (quarantine and held records), and a damaged clocks file is
# discarded, not repaired (ruling #356).

import json

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DOMAIN,
    REPAIR_STORAGE_SHAPE,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_KIND,
    SYS_STORAGE_REPAIR,
)

from .helpers import register_device, setup_coordinator


def _flow(hass, coord):
    from custom_components.device_sentinel import repairs as rmod

    ir.async_create_issue(
        hass,
        DOMAIN,
        REPAIR_STORAGE_SHAPE,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=REPAIR_STORAGE_SHAPE,
        data={"entry_id": coord.entry.entry_id},
    )
    flow = rmod.StorageRepairFlow(coord.entry.entry_id)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = REPAIR_STORAGE_SHAPE
    return flow


def _fake_copies(monkeypatch):
    """The harness holds storage in memory, so the real evidence
    copier finds no files and the actions correctly refuse to run.
    Flow tests fake the copies to reach the action itself."""
    from custom_components.device_sentinel import coordinator as cmod

    async def copies(_hass):
        return "2026-08-27_test", ["the storage file"]

    monkeypatch.setattr(cmod, "async_copy_evidence", copies)


# ------------------------------------------------- the fixable card


async def test_the_card_on_a_clean_file_touches_nothing(
    hass: HomeAssistant,
) -> None:
    """The named fear: Fix pressed on a card whose faults all
    cleared. Nothing runs and not one byte moves."""
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    before = json.dumps(coord.data, sort_keys=True, default=str)
    flow = _flow(hass, coord)
    step = await flow.async_step_init()
    assert step["type"] == "create_entry"
    assert json.dumps(coord.data, sort_keys=True, default=str) == before
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_STORAGE_SHAPE)
        is None
    )


async def test_the_menu_offers_only_what_would_work(
    hass: HomeAssistant,
) -> None:
    """No usable backup in the harness and no damaged device record:
    a scalar fault alone offers ignore, never a restore that would
    fail or a trim with nothing to erase (ruling #353)."""
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord.data["setup_count"] = "many"
    flow = _flow(hass, coord)
    step = await flow.async_step_init()
    assert step["type"] == "menu"
    assert step["menu_options"] == ["ignore"]


async def test_a_damaged_record_offers_the_trim(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A damaged device record puts Trim Record on the menu, the trim
    asks by name, and only the named device is erased (#354)."""
    device, _eids = register_device(hass, "trim_dev", name="Doomed Sensor")
    other, _o = register_device(hass, "safe_dev", name="Safe Sensor")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    _fake_copies(monkeypatch)
    record = coord.data[DATA_DEVICES].get(device.id)
    assert record is not None
    record["daily_max"] = "rotten"
    coord._shape_faults = coord._gather_current_faults()
    flow = _flow(hass, coord)
    step = await flow.async_step_init()
    assert step["type"] == "menu"
    assert "trim" in step["menu_options"]
    step = await flow.async_step_trim()
    assert step["type"] == "form"
    assert "Doomed Sensor" in step["description_placeholders"]["names"]
    assert "Safe Sensor" not in step["description_placeholders"]["names"]
    step = await flow.async_step_trim({})
    assert step["type"] == "create_entry"
    await hass.async_block_till_done()
    assert device.id not in coord.data[DATA_DEVICES]
    assert other.id in coord.data[DATA_DEVICES]
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_STORAGE_SHAPE)
        is None
    )


async def test_restore_bars_the_damaged_session_from_saving(
    hass: HomeAssistant, monkeypatch
) -> None:
    """The one write a confirmed restore must prevent: the unload
    flush putting this session's damaged document back over the
    restored file (ruling #353)."""
    from custom_components.device_sentinel import coordinator as cmod

    device, _eids = register_device(hass, "restore_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    _fake_copies(monkeypatch)

    async def fake_restore(_hass):
        return True, 1000.0

    monkeypatch.setattr(cmod, "async_restore_main_file", fake_restore)
    record = coord.data[DATA_DEVICES].get(device.id)
    assert record is not None
    record["daily_max"] = "rotten"
    saved = []

    async def spy_save():
        saved.append(True)

    monkeypatch.setattr(coord, "_save_now", spy_save)
    assert await coord.async_restore_from_card() is True
    assert coord._restore_pending is True
    await coord.async_shutdown()
    assert saved == [], "the damaged session flushed over the restore"


async def test_restore_that_cannot_run_changes_nothing(
    hass: HomeAssistant, monkeypatch
) -> None:
    """No pre-action copies means no action (ruling #340)."""
    from custom_components.device_sentinel import coordinator as cmod

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    async def no_copies(_hass):
        return None, []

    monkeypatch.setattr(cmod, "async_copy_evidence", no_copies)
    assert await coord.async_restore_from_card() is False
    assert coord._restore_pending is False


# ------------------------------------------- the load-path companions


async def test_a_non_dict_record_no_longer_kills_setup(
    hass: HomeAssistant, hass_storage
) -> None:
    """Reproduced on 27 August: a registered device's record corrupted
    to a string died in the clocks merge with a TypeError before the
    shape check ran. Quarantine (ruling #353) keeps setup alive,
    reports the fault, deletes nothing."""
    device, _eids = register_device(hass, "victim")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    stored["data"].setdefault(DATA_DEVICES, {})[device.id] = "garbage"
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    assert any(
        holder == device.id and field == "*"
        for holder, field, _why in coord2.shape_faults
    )


async def test_a_damaged_clocks_file_is_discarded_not_healed(
    hass: HomeAssistant, hass_storage
) -> None:
    """Ruling #356: a clocks file that fails its shape is treated as
    missing. The session latches, the event says so, and the fault
    never reaches the card."""
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    clocks = hass_storage.get(STORAGE_CLOCKS_KEY)
    assert clocks, "no clocks file written"
    # A record that is not a record is damage; a missing field is
    # not (an upgrade adding a clock field looks exactly like that
    # on its first boot) and must never trigger the discard.
    clocks["data"]["clocks"] = {"someone": "garbage"}
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    assert coord2.shape_faults == []
    events = [
        e
        for e in coord2.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
        and "clocks" in str(e.get("detail"))
    ]
    assert len(events) == 1
    assert "discarded" in str(events[0].get("detail"))


async def test_a_clocks_file_missing_a_field_is_not_discarded(
    hass: HomeAssistant, hass_storage
) -> None:
    """The other half of ruling #356: schema evolution merges."""
    device, _eids = register_device(hass, "evolve_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    clocks = hass_storage.get(STORAGE_CLOCKS_KEY)
    assert clocks
    stored = clocks["data"].get("clocks") or {}
    target = stored.get(device.id)
    assert isinstance(target, dict) and target, "no clock record to thin"
    field = sorted(target)[0]
    del target[field]
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    coord2 = entry.runtime_data
    events = [
        e
        for e in coord2.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
        and "discarded" in str(e.get("detail"))
    ]
    assert events == [], "a missing field triggered the discard"


# ---------------------- from the second adversarial round, 27 August


async def test_a_faulted_record_is_held_and_setup_survives(
    hass: HomeAssistant, hass_storage
) -> None:
    """The check reports and touches nothing (ruling #278), so the
    poison stays in the record, and the second round proved the setup
    report crashes on it: SETUP_ERROR, no card, no Heal. A record
    with a standing fault is now held out of watched_records and the
    fold; Heal is its exit."""
    device, _eids = register_device(hass, "held_dev")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    record = stored["data"][DATA_DEVICES].get(device.id)
    assert isinstance(record, dict)
    record["daily_max"] = "rotten"
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED, (
        "a reported fault still killed setup"
    )
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty
    held = [d for d, _r in coord2.watched_records() if d == device.id]
    assert held == [], "a faulted record reached the watched surfaces"


async def test_the_fold_skips_a_held_record(hass: HomeAssistant) -> None:
    """A poisoned series must not crash the whole fleet's midnight."""
    device, _eids = register_device(hass, "fold_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].get(device.id)
    assert record is not None
    record["daily_max"] = "rotten"
    record["today_max"] = 5.0
    coord._fault_held = frozenset({device.id})
    await coord._on_midnight(None)
    assert record["daily_max"] == "rotten", "the fold wrote into it"
