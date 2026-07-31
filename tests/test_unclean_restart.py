# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_unclean_restart.py, Version: 0.10.11 (2026-07-31)

"""What a restart with no clean-stop marker does to the clocks (#163).

The event this is built from is real. On 2026-07-31 the development
fleet took a deliberate thirty-minute power cut at 09:49 local. The
last clocks write before it landed at 09:35:05, so the newest stamp on
disk was fourteen minutes older than the cut and the system came back
crediting 46 minutes of unwatched time.

That credit is granted per device, and only to a device whose clock is
at or before the anchor (#160). Motion Bath Main's clock read 09:44:07,
nine minutes past the anchor, because it had reported inside the
unsaved window. It therefore failed the test, was charged the full
wall-clock silence, and was convicted frozen at 10:24:24 for an outage
it could not have reported through. Eight further devices with windows
of 22 to 32 minutes were convicted the same way at 10:21:32.

The second half of the same event: Window Living Room Left had been
silent since 09:35, resumed at 10:25, and learned the whole 50-minute
gap. Its today_max went to 3009 seconds against a rhythm near 600. The
resurrection cap could not help, correctly, because the device was
never convicted and the cap is scoped to the freeze family.

Both are cured by the same rule. The clock is reset, so the completing
gap measures from the restart and nothing learns the blackout; the
silence genuinely accumulated before the cut is banked as a lower
bound rather than thrown away; and a device already on the problem
list keeps its clock, because forgiving a known fault because the
lights went out is what the blueprints did.

The figures below are the real ones, so a regression here reads as the
event rather than as an abstraction.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_SAVED_AT,
    DATA_STATS_EPOCH,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EPISODE_ENDED_POWER_LOSS,
    EPISODE_LEARNED_TRUNCATED,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_TAINT_SECONDS,
    EP_WINDOW,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
    SYS_KIND,
    SYS_UNCLEAN_RESTART,
    TAINT_UNAVAILABLE,
    TODO_DEVICE_ID,
)

from .helpers import register_device, setup_entry

# The 31 July cut, in the clock the integration stores.
ANCHOR = 1785508505.0        # 09:35:05, the last clocks write
MOTION_BATH_MAIN = 1785509047.0   # 09:44:07, inside the unsaved window
WINDOW_LIVING_LEFT = 1785508500.0  # 09:35, just before the anchor


def _record(last_activity, today_max=None, tainted=False):
    """A device record carrying only what this rule touches."""
    return {
        DEV_LAST_ACTIVITY: last_activity,
        DEV_TODAY_MAX: today_max,
        DEV_EVENT_COUNT: 4200,
        DEV_FIRST_OBSERVED: 1784000000.0,
        DEV_TAINTED: tainted,
    }


def _on_disk(hass_storage, devices, episodes=None, todo=None, clean=False):
    """Write a storage pair as the cut left it.

    The main file is stamped a little older than the clocks file,
    which is the ordinary state under the split: the clocks file is
    written every interval and the main file only when a forensic row
    is waiting.
    """
    data = {
        DATA_DEVICES: devices,
        DATA_STATS_EPOCH: STATS_EPOCH,
        DATA_SAVED_AT: ANCHOR - 900.0,
        DATA_EPISODES: episodes or [],
        DATA_TODO_ITEMS: todo or [],
    }
    if clean:
        data[DATA_CLEAN_STOP] = True
    hass_storage[STORAGE_KEY] = {"version": 1, "data": data}
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "data": {
            DATA_SAVED_AT: ANCHOR,
            "clocks": {
                device_id: {DEV_LAST_ACTIVITY: record[DEV_LAST_ACTIVITY]}
                for device_id, record in devices.items()
            },
        },
    }


async def test_the_clock_that_postdated_the_anchor_is_reset(
    hass: HomeAssistant, hass_storage
):
    """Motion Bath Main, the device that proved the fault.

    Its clock read nine minutes past the last write, so the credit
    that would have excused the blackout did not apply to it and it
    was convicted. After the reset its clock starts at this boot and
    it is judged on what happens from here.
    """
    device, _ = register_device(hass, "mbm", "Motion Bath Main")
    _on_disk(hass_storage, {device.id: _record(MOTION_BATH_MAIN)})

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_LAST_ACTIVITY] > MOTION_BATH_MAIN
    assert record[DEV_LAST_ACTIVITY] >= entry.runtime_data.last_alive


async def test_a_clean_stop_changes_no_clock(
    hass: HomeAssistant, hass_storage
):
    """The same file with the marker on it is left entirely alone.

    This is the difference the whole rule turns on, so it is asserted
    against the identical fixture rather than a simpler one.
    """
    device, _ = register_device(hass, "mbm", "Motion Bath Main")
    _on_disk(
        hass_storage, {device.id: _record(MOTION_BATH_MAIN)}, clean=True
    )

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_LAST_ACTIVITY] == MOTION_BATH_MAIN


async def test_a_device_on_the_problem_list_keeps_its_clock(
    hass: HomeAssistant, hass_storage
):
    """The exception that carries all the weight.

    Vibration FJ40 Land Cruiser and Soil Irrigation (Monstera) were
    both on the list through the cut. Resetting them would forgive a
    fault already known, which is the blueprint behaviour the
    integration exists to replace.
    """
    flagged, _ = register_device(hass, "fj40", "Vibration FJ40")
    ordinary, _ = register_device(hass, "sw1", "Switch Kitchen")
    _on_disk(
        hass_storage,
        {
            flagged.id: _record(ANCHOR - 900000.0),
            ordinary.id: _record(ANCHOR - 600.0),
        },
        todo=[{TODO_DEVICE_ID: flagged.id}],
    )

    entry = await setup_entry(hass)
    devices = entry.runtime_data.data[DATA_DEVICES]

    assert devices[flagged.id][DEV_LAST_ACTIVITY] == ANCHOR - 900000.0
    assert devices[ordinary.id][DEV_LAST_ACTIVITY] > ANCHOR


async def test_the_pre_cut_silence_is_banked_as_a_lower_bound(
    hass: HomeAssistant, hass_storage
):
    """Window Living Room Left, the device that proved the second half.

    It had been quiet 50 minutes when it resumed, and learned all of
    it. Under the reset it learns only what was measured before the
    lights went out, which is a lower bound on the true gap and can
    only move the day's maximum toward the truth.
    """
    device, _ = register_device(hass, "wlrl", "Window Living Room Left")
    _on_disk(hass_storage, {device.id: _record(WINDOW_LIVING_LEFT)})

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_TODAY_MAX] == ANCHOR - WINDOW_LIVING_LEFT
    assert record[DEV_TODAY_MAX] < 3009.0


async def test_a_larger_maximum_already_earned_is_not_lowered(
    hass: HomeAssistant, hass_storage
):
    """The day's maximum keeps the larger of the two.

    A truncated gap is banked only where nothing longer was measured,
    so a device that had already recorded a real 40-minute gap that
    day keeps it.
    """
    device, _ = register_device(hass, "big", "Switch Hall Living")
    _on_disk(
        hass_storage,
        {device.id: _record(ANCHOR - 600.0, today_max=2400.0)},
    )

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_TODAY_MAX] == 2400.0


async def test_the_learned_series_and_identity_are_untouched(
    hass: HomeAssistant, hass_storage
):
    """Only the clock moves.

    The event count, the first-observed stamp and everything the
    device genuinely earned survive, because the outage tells us
    nothing about any of them.
    """
    device, _ = register_device(hass, "keep", "Leak Kitchen Sink")
    _on_disk(hass_storage, {device.id: _record(ANCHOR - 600.0)})

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_EVENT_COUNT] == 4200
    assert record[DEV_FIRST_OBSERVED] == 1784000000.0


async def test_a_taint_does_not_survive_a_reset_clock(
    hass: HomeAssistant, hass_storage
):
    """A taint waits for a gap that no longer exists.

    The flag suppresses learning for the one gap that completes next.
    Resetting the clock destroys that gap, so carrying the taint over
    would silently discard the first real measurement after the cut.
    """
    device, _ = register_device(hass, "taint", "Switch Bath Main")
    _on_disk(
        hass_storage,
        {device.id: _record(ANCHOR - 600.0, tainted=TAINT_UNAVAILABLE)},
    )

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert not record[DEV_TAINTED]


async def test_an_open_episode_closes_as_a_power_loss(
    hass: HomeAssistant, hass_storage
):
    """The episode and the clock must not contradict each other.

    Eight episodes were open across the 31 July cut. Each closes at
    the last known-alive moment, which is the latest instant the
    silence can be honestly claimed to have run to, and reads power
    loss rather than the reboot label a later restart would have
    stamped on it.
    """
    device, _ = register_device(hass, "open", "Door Master Closet 2")
    episode = {
        EP_DEVICE_ID: device.id,
        EP_NAME: "Door Master Closet 2",
        EP_SINCE: ANCHOR - 2600.0,
        EP_BASIS: 1200.0,
        EP_WINDOW: 3830.0,
        EP_ENDED: None,
        EP_AT: None,
        EP_LAG: None,
        EP_LEARNED: None,
        EP_TAINT_SECONDS: None,
    }
    _on_disk(
        hass_storage,
        {device.id: _record(ANCHOR - 2600.0)},
        episodes=[episode],
    )

    entry = await setup_entry(hass)
    stored = entry.runtime_data.data[DATA_EPISODES][0]

    assert stored[EP_ENDED] == EPISODE_ENDED_POWER_LOSS
    assert stored[EP_AT] == ANCHOR
    assert stored[EP_LEARNED] == EPISODE_LEARNED_TRUNCATED


async def test_a_closed_episode_is_not_restamped(
    hass: HomeAssistant, hass_storage
):
    """Only rows with no ending are touched."""
    device, _ = register_device(hass, "closed", "Leak Sink Laundry")
    episode = {
        EP_DEVICE_ID: device.id,
        EP_NAME: "Leak Sink Laundry",
        EP_SINCE: ANCHOR - 4000.0,
        EP_BASIS: 1200.0,
        EP_WINDOW: 3830.0,
        EP_ENDED: "resumed",
        EP_AT: ANCHOR - 3000.0,
        EP_LAG: None,
        EP_LEARNED: "yes",
        EP_TAINT_SECONDS: None,
    }
    _on_disk(
        hass_storage,
        {device.id: _record(ANCHOR - 600.0)},
        episodes=[episode],
    )

    entry = await setup_entry(hass)
    stored = entry.runtime_data.data[DATA_EPISODES][0]

    assert stored[EP_ENDED] == "resumed"
    assert stored[EP_AT] == ANCHOR - 3000.0


async def test_the_restart_is_recorded_as_a_system_event(
    hass: HomeAssistant, hass_storage
):
    """A clock that jumps with no explanation above it is the exact
    silent oddity this project exists to prevent."""
    device, _ = register_device(hass, "evt", "Switch Kitchen")
    _on_disk(hass_storage, {device.id: _record(ANCHOR - 600.0)})

    entry = await setup_entry(hass)
    kinds = [
        row[SYS_KIND]
        for row in entry.runtime_data.data[DATA_SYSTEM_EVENTS]
    ]

    assert SYS_UNCLEAN_RESTART in kinds


async def test_a_clean_stop_records_no_unclean_event(
    hass: HomeAssistant, hass_storage
):
    """The row appears only where it is true."""
    device, _ = register_device(hass, "evt2", "Switch Kitchen")
    _on_disk(
        hass_storage, {device.id: _record(ANCHOR - 600.0)}, clean=True
    )

    entry = await setup_entry(hass)
    kinds = [
        row[SYS_KIND]
        for row in entry.runtime_data.data[DATA_SYSTEM_EVENTS]
    ]

    assert SYS_UNCLEAN_RESTART not in kinds


async def test_an_unstamped_file_is_left_alone(
    hass: HomeAssistant, hass_storage
):
    """With no stamp there is no anchor, and every part of the rule is
    measured from one.

    Resetting here would destroy real clocks and buy nothing, because
    the credit the rule protects is itself inert without an anchor.
    Only a file written before 0.10.0 can be in this state.
    """
    device, _ = register_device(hass, "nostamp", "Old Install")
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            DATA_DEVICES: {device.id: _record(5000.0)},
            DATA_STATS_EPOCH: STATS_EPOCH,
        },
    }

    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_LAST_ACTIVITY] == 5000.0


async def test_the_marker_is_cleared_on_load(
    hass: HomeAssistant, hass_storage
):
    """A crash after a clean stop is detected as a crash.

    The marker is read and cleared in the same breath, so it can never
    describe anything but the stop immediately before this load.
    """
    device, _ = register_device(hass, "clear", "Switch Laundry")
    _on_disk(
        hass_storage, {device.id: _record(ANCHOR - 600.0)}, clean=True
    )

    entry = await setup_entry(hass)

    assert not entry.runtime_data.data.get(DATA_CLEAN_STOP)


async def test_an_orderly_unload_writes_the_marker(
    hass: HomeAssistant, hass_storage
):
    """A reload is not a power cut.

    Changing a setting, reloading the entry, or a HACS update all go
    through the unload path and fire no stop event. A marker written
    only on the stop event would make every options change read as a
    crash and reset the whole fleet.
    """
    device, _ = register_device(hass, "reload", "Switch Entryway")
    _on_disk(
        hass_storage, {device.id: _record(ANCHOR - 600.0)}, clean=True
    )
    entry = await setup_entry(hass)
    kept = entry.runtime_data.data[DATA_DEVICES][device.id][
        DEV_LAST_ACTIVITY
    ]

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    record = entry.runtime_data.data[DATA_DEVICES][device.id]

    assert record[DEV_LAST_ACTIVITY] == kept
