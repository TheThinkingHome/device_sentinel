# Tests for 0.18.0, Detection and Protection.
#
# The subjects: the withheld refresh (#339), the Status latch (#341),
# the banking repair (#338), the evidence copies (#340), the action
# record (#342), retention pruning (#343), and the addressable fault
# identity (#338). Each test breaks the code's input, not its
# internals, and reads the outcome a person would read.

import os
import time

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.backup import (
    async_copy_evidence,
    async_prune_backups,
)
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    SYS_DETAIL,
    SYS_KIND,
    SYS_STORAGE_REPAIR,
    TRIM_BACKUP_DIR,
)
from custom_components.device_sentinel.normalise import fault_id

from .helpers import register_device, setup_coordinator


def _write_live_files(hass):
    """The harness stores in memory, so the disk pair is written by
    hand for the tests that exercise real file copying."""
    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)
    for name in ("device_sentinel.storage", "device_sentinel.clocks"):
        with open(os.path.join(directory, name), "w") as handle:
            handle.write('{"data": {}}')


async def test_a_clean_load_refreshes_and_a_faulty_one_withholds(
    hass: HomeAssistant,
):
    """The refresh follows the load, not the latest check (#339)."""
    coord = await setup_coordinator(hass)
    assert not coord.storage_load_faulty
    _write_live_files(hass)
    # A clean fold-moment check refreshes the copy.
    await coord._check_storage_shape("fold")
    good = hass.config.path(
        ".storage/device_sentinel.storage.last-good"
    )
    assert os.path.exists(good)
    first_taken = coord.last_good_taken
    assert first_taken is not None

    # Damage a record and run the fold-moment check: the session
    # latches and the copy does not advance.
    device, _ = register_device(hass, "wf", name="WF")
    coord._rebuild_registry_view()
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record["window_basis"] = "not a number"
    await coord._check_storage_shape("fold")
    assert coord.storage_load_faulty
    assert coord.last_good_taken == first_taken

    # Repair the damage by hand and check again: still withheld,
    # because repaired is not the same as untouched (#339, #341).
    record["window_basis"] = None
    await coord._check_storage_shape("fold")
    assert coord.storage_load_faulty, "the latch cleared without a restart"
    assert coord.last_good_taken == first_taken, (
        "the copy refreshed in a session whose load was not clean"
    )


async def test_the_banking_repair_restarts_a_damaged_clock(
    hass: HomeAssistant,
):
    """A damaged activity clock is banked, recorded, and stands (#338,
    #342)."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "bank", name="BANK")
    coord._rebuild_registry_view()
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_LAST_ACTIVITY] = ["not", "a", "stamp"]
    record[DEV_TAINTED] = True

    before = dt_util.utcnow().timestamp()
    faults = coord._gather_shape_faults("fold")
    assert any(f[1] == DEV_LAST_ACTIVITY for f in faults)
    repaired = coord._bank_damaged_clocks(faults)
    assert repaired == 1
    assert isinstance(record[DEV_LAST_ACTIVITY], float)
    assert record[DEV_LAST_ACTIVITY] >= before
    assert record[DEV_TAINTED] is False
    assert coord.repairs_at_load == 1
    events = [
        e
        for e in coord.data.get("system_events", [])
        if e.get(SYS_KIND) == SYS_STORAGE_REPAIR
    ]
    assert len(events) == 1
    assert "banked" in str(events[0].get(SYS_DETAIL))
    # The repaired record now verifies clean on that field.
    remaining = coord._gather_shape_faults("fold")
    assert not any(f[1] == DEV_LAST_ACTIVITY for f in remaining)


async def test_evidence_copies_all_four_files(hass: HomeAssistant):
    """The copy is raw bytes of whatever exists, stamped (#340)."""
    coord = await setup_coordinator(hass)
    _write_live_files(hass)
    await coord._check_storage_shape("fold")  # makes the last-good pair
    stamp = await async_copy_evidence(hass)
    assert stamp
    directory = hass.config.path(TRIM_BACKUP_DIR)
    names = sorted(os.listdir(directory))
    kinds = [n.split(".", 1)[1] for n in names if stamp in n]
    assert "storage.evidence" in kinds
    assert "clocks.evidence" in kinds
    # The last-good pair exists after a clean setup, so it rode along.
    assert "storage.last-good" in kinds
    assert "clocks.last-good" in kinds
    # Raw bytes: the evidence equals the live file exactly.
    live = open(
        hass.config.path(".storage/device_sentinel.storage"), "rb"
    ).read()
    copy = open(
        os.path.join(
            directory, f"device_sentinel_{stamp}.storage.evidence"
        ),
        "rb",
    ).read()
    assert copy == live


async def test_two_evidence_copies_in_one_second_both_survive(
    hass: HomeAssistant,
):
    """The stamp collision rule trim learned the hard way (#340)."""
    await setup_coordinator(hass)
    _write_live_files(hass)
    first = await async_copy_evidence(hass)
    second = await async_copy_evidence(hass)
    assert first and second and first != second


async def test_pruning_respects_the_window_and_names(
    hass: HomeAssistant,
):
    """Old files go, young files stay, foreign files are never
    touched (#343)."""
    await setup_coordinator(hass)
    directory = hass.config.path(TRIM_BACKUP_DIR)
    os.makedirs(directory, exist_ok=True)
    old = os.path.join(directory, "device_sentinel_old.storage.json")
    young = os.path.join(directory, "device_sentinel_new.storage.json")
    foreign = os.path.join(directory, "somebody_elses_file.json")
    for path in (old, young, foreign):
        open(path, "w").write("{}")
    ancient = time.time() - 91 * 86400
    os.utime(old, (ancient, ancient))
    os.utime(foreign, (ancient, ancient))

    removed = await async_prune_backups(hass, 90)
    assert removed == 1
    assert not os.path.exists(old)
    assert os.path.exists(young)
    assert os.path.exists(foreign), "pruning touched a foreign file"


async def test_fault_ids_name_the_right_file(hass: HomeAssistant):
    """The identity derives its file from the field (#338)."""
    assert fault_id(("abc", "last_activity", "x")) == (
        "clocks:abc:last_activity"
    )
    assert fault_id(("abc", "window_basis", "x")) == (
        "main:abc:window_basis"
    )
    assert fault_id(("incidents[3]", "duration", "x")) == (
        "main:incidents[3]:duration"
    )
