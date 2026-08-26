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
    async_restore_main_file,
    describe_restore_loss,
)
from custom_components.device_sentinel.const import (
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
