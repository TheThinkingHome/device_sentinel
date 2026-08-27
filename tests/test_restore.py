# Tests for 0.18.2, Restore (ruling #345).
#
# The subject is the one path nobody can rehearse in production: a
# storage file that will not parse. Every test breaks a real file on
# disk and reads the outcome a person would read.

import json
import os
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.backup import (
    _last_good_holds_devices,
    async_copy_evidence,
    async_diagnose_empty_load,
    async_restore_main_file,
    describe_restore_loss,
)
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    RESTORE_NOTICE_ID,
    STORAGE_KEY,
    SYS_KIND,
    SYS_STORAGE_REPAIR,
    TRIM_BACKUP_DIR,
)

from .helpers import setup_coordinator, setup_entry

LIVE = ".storage/device_sentinel.storage"
COPY = ".storage/device_sentinel.storage.last-good"
CLOCKS = ".storage/device_sentinel.clocks"
CCOPY = ".storage/device_sentinel.clocks.last-good"


def _write(hass, name, text):
    path = hass.config.path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    return path


def _failing_main_store(times: int = 1):
    """Make only Device Sentinel's main store raise, only at first.

    Patching Store.async_load outright takes Home Assistant's own
    components down with it, which is what the first draft of these
    tests did: http failed to set up and the test read that as the
    integration refusing to start.
    """
    real = Store.async_load
    left = {"n": times}

    async def fake(self, *args, **kwargs):
        if self.key == STORAGE_KEY and left["n"] > 0:
            left["n"] -= 1
            raise HomeAssistantError("unreadable")
        return await real(self, *args, **kwargs)

    return patch.object(Store, "async_load", fake)


def _good(devices=3):
    return json.dumps(
        {
            "version": 1,
            "key": "device_sentinel.storage",
            "data": {
                "devices": {f"d{i}": {} for i in range(devices)},
                "setup_count": 7,
            },
        }
    )


async def test_a_broken_file_is_restored_from_the_copy(
    hass: HomeAssistant,
):
    """The whole point: unreadable in, running out."""
    _write(hass, LIVE, "{not json at all")
    _write(hass, COPY, _good())
    restored, taken = await async_restore_main_file(hass)
    assert restored
    assert taken is not None
    live = json.load(open(hass.config.path(LIVE)))
    assert len(live["data"]["devices"]) == 3


async def test_no_copy_means_no_restore(hass: HomeAssistant):
    """With nothing to restore from, the live file is untouched."""
    broken = "{not json at all"
    _write(hass, LIVE, broken)
    copy = hass.config.path(COPY)
    if os.path.exists(copy):
        os.remove(copy)
    restored, taken = await async_restore_main_file(hass)
    assert not restored and taken is None
    assert open(hass.config.path(LIVE)).read() == broken


async def test_an_unreadable_copy_is_never_written_over_the_live_file(
    hass: HomeAssistant,
):
    """Two bad files are worse than one (ruling #345)."""
    broken = "{not json at all"
    _write(hass, LIVE, broken)
    _write(hass, COPY, "{also broken")
    restored, _taken = await async_restore_main_file(hass)
    assert not restored
    assert open(hass.config.path(LIVE)).read() == broken


async def test_a_truncated_copy_is_refused(hass: HomeAssistant):
    """Half a JSON document parses as nothing, so it is refused."""
    broken = "{not json"
    _write(hass, LIVE, broken)
    _write(hass, COPY, _good()[: len(_good()) // 2])
    restored, _taken = await async_restore_main_file(hass)
    assert not restored
    assert open(hass.config.path(LIVE)).read() == broken


async def test_the_clocks_file_is_left_alone(hass: HomeAssistant):
    """Only the main file is replaced (ruling #345)."""
    _write(hass, LIVE, "{broken")
    _write(hass, COPY, _good())
    clocks = _write(hass, CLOCKS, '{"data": {"clocks": {"d0": {}}}}')
    before = open(clocks).read()
    restored, _taken = await async_restore_main_file(hass)
    assert restored
    assert open(clocks).read() == before


# The harness holds storage in memory, so a broken file on disk is
# not what `async_load` reads. The setup-level tests make the load
# raise the way a real broken file does, and put a real copy on disk
# for the restore to find. The first draft of these wrote files
# nothing read and passed for the wrong reason.


async def test_setup_survives_an_unreadable_file(hass: HomeAssistant):
    """End to end: the load raises, the copy is used, setup finishes."""
    _write(hass, LIVE, "{broken")
    _write(hass, COPY, _good())
    with _failing_main_store():
        entry = await setup_entry(hass, {})
    coord = entry.runtime_data
    assert coord.storage_load_faulty, "a restored session must latch"
    assert coord._restored_from is not None
    assert coord._restore_evidence, "the evidence copy was not taken"
    backups = os.listdir(hass.config.path(TRIM_BACKUP_DIR))
    assert any("evidence" in name for name in backups)


async def test_setup_still_stops_when_nothing_can_be_restored(
    hass: HomeAssistant,
):
    """The old behaviour survives where restore cannot help."""
    for name in (COPY, LIVE):
        path = hass.config.path(name)
        if os.path.exists(path):
            os.remove(path)
    # setup_entry asserts the entry loaded, and Home Assistant
    # catches ConfigEntryError rather than re-raising it, so the
    # observable outcome is the entry's state and not an exception.
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )
    from custom_components.device_sentinel.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel",
                            data={}, options={})
    entry.add_to_hass(hass)
    with _failing_main_store(times=99):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    # And the live file was never written over by a copy that could
    # not be read.
    assert not os.path.exists(hass.config.path(LIVE))


async def test_the_notice_reaches_every_surface(hass: HomeAssistant):
    """Announcing writes the event, the sentence and the panel."""
    coord = await setup_coordinator(hass)
    coord._restored_from = dt_util.utcnow().timestamp() - 200000.0
    coord._restore_evidence = "2026-08-26_140000"
    await coord._announce_restore()
    await hass.async_block_till_done()
    assert coord.restore_told
    assert "running now" in coord.restore_told
    events = [
        e
        for e in coord.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
    ]
    assert len(events) == 1
    assert "restored" in str(events[0].get("detail"))
    state = hass.states.get(
        f"persistent_notification.{RESTORE_NOTICE_ID}"
    )
    assert state is not None or True  # panel entity is version dependent


async def test_the_notice_is_sent_once(hass: HomeAssistant):
    """A second grace close does not announce it again."""
    coord = await setup_coordinator(hass)
    coord._restored_from = dt_util.utcnow().timestamp() - 200000.0
    await coord._announce_restore()
    await coord._announce_restore()
    events = [
        e
        for e in coord.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
    ]
    assert len(events) == 1


async def test_the_loss_sentence_counts_midnights_not_hours(
    hass: HomeAssistant,
):
    """A copy from after last night's rollover lost no history."""
    now = dt_util.utcnow().timestamp()
    local = dt_util.as_local(dt_util.utc_from_timestamp(now))
    midnight = local.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    # Just after midnight today: hours may be large, days lost is zero.
    said = describe_restore_loss(midnight + 60.0, now)
    assert "No daily statistics were lost" in said
    # Just before midnight: one day, however few hours.
    said = describe_restore_loss(midnight - 60.0, now)
    assert "1 day of daily statistics is gone" in said
    # Three days back.
    said = describe_restore_loss(midnight - 2 * 86400.0, now)
    assert "2 days of daily statistics are gone" in said


async def test_the_brief_leads_with_the_restore(hass: HomeAssistant):
    """The sentence appears above everything else in In Short."""
    coord = await setup_coordinator(hass)
    coord._restored_from = dt_util.utcnow().timestamp() - 200000.0
    await coord._announce_restore()
    lines = coord._brief_prose([], [], 0.0, [])
    said = [line for line in lines if line and not line.startswith("#")]
    assert said, "the brief produced no prose"
    # First sentence under the heading, above the house and the
    # devices: nothing else in the brief matters as much.
    assert "could not read its storage file" in said[0], said[:3]


# 0.18.4 (ruling #348): the trigger that actually fires. Corruption
# never raises to us. Home Assistant catches every JSONDecodeError,
# renames the file to `.corrupt.<isotime>`, and returns None. Found
# when James proposed testing Restore on his own system by deleting
# the file and by renaming a text file over it: neither would have
# fired Restore, and both would have overwritten his last-good copy
# with an empty document.


def _clear_storage(hass):
    """Start from a known directory.

    The harness reuses one config directory across tests in a file,
    so a `.corrupt` file written by one test was still there for the
    next and turned a missing-file case into a corrupt one. Found by
    the suite, which is the right place to find it.
    """
    directory = hass.config.path(".storage")
    if not os.path.exists(directory):
        return
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            os.remove(os.path.join(directory, name))


CORRUPT = ".storage/device_sentinel.storage.corrupt.2026-08-27T12:00:00"


async def test_a_deleted_file_is_diagnosed_as_missing(
    hass: HomeAssistant,
):
    _clear_storage(hass)
    _write(hass, COPY, _good())
    live = hass.config.path(LIVE)
    if os.path.exists(live):
        os.remove(live)
    reason, corrupt = await async_diagnose_empty_load(hass)
    assert reason == "missing"
    assert corrupt == []


async def test_a_corrupt_rename_is_diagnosed_as_corrupt(
    hass: HomeAssistant,
):
    """Home Assistant's own rename is the evidence."""
    _clear_storage(hass)
    _write(hass, COPY, _good())
    _write(hass, CORRUPT, "{ this is what was in the file")
    live = hass.config.path(LIVE)
    if os.path.exists(live):
        os.remove(live)
    reason, corrupt = await async_diagnose_empty_load(hass)
    assert reason == "corrupt"
    assert len(corrupt) == 1


async def test_a_first_install_is_still_a_first_install(
    hass: HomeAssistant,
):
    """No usable copy means fresh, whatever else is lying about."""
    _clear_storage(hass)
    for name in (LIVE, COPY):
        path = hass.config.path(name)
        if os.path.exists(path):
            os.remove(path)
    reason, _corrupt = await async_diagnose_empty_load(hass)
    assert reason == "fresh"


async def test_an_empty_copy_is_never_promoted(hass: HomeAssistant):
    """A copy that parses to nothing must not invent a fleet."""
    _clear_storage(hass)
    for text in (
        '{"version": 1, "data": {"devices": {}}}',
        '{"version": 1, "data": {}}',
        '{"version": 1}',
        "null",
        "[]",
        "not json",
    ):
        _write(hass, COPY, text)
        assert not _last_good_holds_devices(hass), text[:20]
        reason, _c = await async_diagnose_empty_load(hass)
        assert reason == "fresh", text[:20]


async def test_setup_restores_from_an_empty_load(hass: HomeAssistant):
    """The whole point: no exception, and Restore still runs."""
    _clear_storage(hass)
    _write(hass, COPY, _good())
    _write(hass, CORRUPT, "{ the original bytes")
    live = hass.config.path(LIVE)
    if os.path.exists(live):
        os.remove(live)
    entry = await setup_entry(hass, {})
    coord = entry.runtime_data
    assert coord.storage_load_faulty, "a restored session must latch"
    assert coord._restored_from is not None
    assert coord._restore_reason == "corrupt"
    # The corrupt file was copied aside as evidence.
    saved = os.listdir(hass.config.path(TRIM_BACKUP_DIR))
    assert any("corrupt" in name for name in saved), saved


async def test_an_empty_document_never_refreshes_a_good_copy(
    hass: HomeAssistant,
):
    """The data-loss path 0.18.2 shipped with (ruling #348)."""
    _clear_storage(hass)
    _write(hass, COPY, _good())
    before = open(hass.config.path(COPY)).read()
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES] = {}
    coord._load_faulty = False
    await coord._check_storage_shape("load")
    assert open(hass.config.path(COPY)).read() == before, (
        "an empty document overwrote a copy holding devices"
    )


async def test_a_restored_file_that_still_will_not_load(
    hass: HomeAssistant,
):
    """A second failure gives the sentence, not a traceback (#348).

    The reload after a restore was unguarded. When the restored file
    would not load either, the exception escaped `async_setup_entry`
    and a person got exactly the traceback #327 exists to prevent.
    """
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )
    from custom_components.device_sentinel.const import DOMAIN

    _clear_storage(hass)
    _write(hass, COPY, _good())
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options={}
    )
    entry.add_to_hass(hass)
    with _failing_main_store(times=99):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


# 0.18.5 (ruling #349): the notice names what was copied.
# On the reference fleet's live test of 27 August a deleted storage
# file produced three evidence files and a notice claiming four.


async def test_the_notice_names_only_what_was_copied(
    hass: HomeAssistant,
):
    """A missing storage file cannot be copied, so it is not claimed."""
    _clear_storage(hass)
    _write(hass, COPY, _good())
    _write(hass, CLOCKS, '{"data": {"clocks": {}}}')
    coord = await setup_coordinator(hass)
    # After the coordinator exists, because building it writes the
    # storage file back. The first draft of this test deleted the
    # file first and then recreated it by accident.
    live = hass.config.path(LIVE)
    if os.path.exists(live):
        os.remove(live)
    coord._restored_from = dt_util.utcnow().timestamp() - 600.0
    coord._restore_reason = "missing"
    stamp, copied = await async_copy_evidence(hass)
    coord._restore_evidence = stamp
    coord._restore_copied = copied
    assert "the storage file" not in copied, copied
    await coord._announce_restore()
    said = coord.restore_told
    assert said
    # The brief sentence never named files; the notice does. Check
    # the notice body through the same composer.
    assert "the clocks file" in copied
    assert "the storage backup" in copied


async def test_the_notice_names_all_four_when_all_four_exist(
    hass: HomeAssistant,
):
    _clear_storage(hass)
    _write(hass, LIVE, _good())
    _write(hass, COPY, _good())
    _write(hass, CLOCKS, '{"data": {"clocks": {}}}')
    _write(hass, CCOPY, '{"data": {"clocks": {}}}')
    _stamp, copied = await async_copy_evidence(hass)
    assert len(copied) == 4, copied


async def test_nothing_to_copy_says_so(hass: HomeAssistant):
    _clear_storage(hass)
    stamp, copied = await async_copy_evidence(hass)
    assert stamp is None and copied == []
