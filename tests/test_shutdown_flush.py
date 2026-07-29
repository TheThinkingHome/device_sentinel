# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_shutdown_flush.py, Version: 0.10.8 (2026-07-29)

"""What a clean stop writes, and that it always writes it.

Stopping does two things: it stamps any silence still running as
truncated by the restart, and it flushes both storage files so the
next start reads the exact moment the system went down.

The fault pinned here: the stamp reaches _mark_cold_dirty, whose last
act is to clear the routine dirty flag, because a delayed write has
been scheduled to carry the change. The flush was gated on that same
flag, so a stop with any silence running skipped its own flush. Both
files were then written by Home Assistant's final-write stage from
their separately scheduled payloads, each stamped at its own schedule
time, in no fixed order, and the small file could come out the older
of the two. The next start then refused to merge it. On 29 July the
one shutdown that stamped an episode was followed by the one start
that refused the clocks, 941 seconds apart.

Every test here advances the frozen clock between phases, because
both files stamp with utcnow at serialize time: under a pinned clock
every write carries the same stamp and nothing can be told apart.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_SAVED_AT,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    EPISODE_ENDED_REBOOT,
    EP_ENDED,
    FREEZE_ARMING_DAYS,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from .helpers import register_device, setup_coordinator


def _stamps(hass_storage):
    """Return (large file saved_at, small file saved_at) as written.

    Read from the storage fixture rather than through async_load,
    which serves the store's in-memory copy and would report a write
    that never happened.
    """
    big = (hass_storage.get(STORAGE_KEY) or {}).get("data") or {}
    small = (hass_storage.get(STORAGE_CLOCKS_KEY) or {}).get("data") or {}
    return big.get(DATA_SAVED_AT), small.get(DATA_SAVED_AT)


def _with_a_silence_running(coord, device_id):
    """Put a watched device past its basis so a sweep opens its episode."""
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 7200.0
    coord._judge_all_devices()


async def test_a_stop_with_a_silence_running_still_flushes(
    hass: HomeAssistant, freezer, hass_storage
):
    """Both files are written by the stop itself.

    This is the regression: the stamp cleared the flag the flush was
    gated on, so a stop with an episode open wrote nothing.
    """
    device, _ = register_device(hass, "flushdev", "Flush Device")
    coord = await setup_coordinator(hass)
    _with_a_silence_running(coord, device.id)
    assert len(coord.data[DATA_EPISODES]) == 1
    before_big, before_small = _stamps(hass_storage)

    freezer.tick(timedelta(seconds=30))
    await coord._on_hass_stop(None)

    big, small = _stamps(hass_storage)
    assert big != before_big, "the stop did not write the large file"
    assert small != before_small, "the stop did not write the small file"


async def test_a_stop_leaves_the_small_file_the_newer_of_the_two(
    hass: HomeAssistant, freezer, hass_storage
):
    """The order is what the next start's merge decision reads."""
    device, _ = register_device(hass, "orderdev", "Order Device")
    coord = await setup_coordinator(hass)
    _with_a_silence_running(coord, device.id)

    freezer.tick(timedelta(seconds=30))
    await coord._on_hass_stop(None)

    big, small = _stamps(hass_storage)
    assert big is not None and small is not None
    assert small >= big, (
        f"the small file is {big - small:.3f}s older than the large one; "
        "the next start will refuse to merge it"
    )


async def test_a_stop_with_nothing_outstanding_also_flushes(
    hass: HomeAssistant, freezer, hass_storage
):
    """Unconditional means unconditional.

    With nothing dirty the old gate also skipped the flush, which was
    harmless only because nothing had changed; the saved stamp still
    went stale. The stamp is what #160 measures observed silence
    against, so it should always be the true moment of stopping.
    """
    coord = await setup_coordinator(hass)
    coord._dirty = False
    coord._critical = False
    before_big, before_small = _stamps(hass_storage)

    freezer.tick(timedelta(seconds=30))
    await coord._on_hass_stop(None)

    big, small = _stamps(hass_storage)
    assert big != before_big and small != before_small
    assert small >= big


async def test_the_intervention_stamp_survives_the_flush(
    hass: HomeAssistant, freezer, hass_storage
):
    """Fixing the flush must not cost the stamp it exists to flush."""
    device, _ = register_device(hass, "stampdev", "Stamp Device")
    coord = await setup_coordinator(hass)
    _with_a_silence_running(coord, device.id)

    freezer.tick(timedelta(seconds=30))
    await coord._on_hass_stop(None)

    episode = coord.data[DATA_EPISODES][0]
    assert episode[EP_ENDED] == EPISODE_ENDED_REBOOT
    # And the stamped episode reached the large file on disk.
    big = (hass_storage.get(STORAGE_KEY) or {}).get("data") or {}
    assert big[DATA_EPISODES][0][EP_ENDED] == EPISODE_ENDED_REBOOT
