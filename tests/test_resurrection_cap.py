# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_resurrection_cap.py, Version: 0.10.10 (2026-07-30)

"""What a convicted device's recovery may teach (#166).

A gap completing while the device stands convicted of a freeze is a
silent-then-speaks recovery that neither the taint nor the pairing
window can see, so it may be a hand-fix the integration cannot
detect. It is learned at most as rhythm plus the ratchet allowance, a
power curve that lets fast devices step half their rhythm and slow
ones a tenth. Judgment and every human-facing surface keep the true
duration; only what learning stores is capped. Found live on 30 July:
a pulled battery taught a ten-minute device a seventy-four minute
maximum, and the trim was the only thing standing between that and a
widened window.
"""

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EP_LEARNED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    TAINT_UNAVAILABLE,
)

from .helpers import register_device, setup_coordinator


def _armed(coord, device_id, rhythm):
    """Give a device a learned rhythm and a fresh clock."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [rhythm] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    record[DEV_TODAY_MAX] = None
    return record


async def _recover_after(hass, coord, eid, record, silence, frozen=True):
    """Complete a gap of the given silence, convicted or not."""
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - silence
    record[DEV_FROZEN_CATEGORY] = (
        FREEZE_CATEGORY_FROZEN if frozen else None
    )
    hass.states.async_set(eid, str(dt_util.utcnow().timestamp()))
    await hass.async_block_till_done()
    return record


async def test_a_convicted_recovery_learns_at_most_the_cap(
    hass: HomeAssistant, freezer
):
    """The 30 July case: 74 minutes may not teach a 10-minute device."""
    device, eid = register_device(hass, "cap1", "Capped Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)
    cap = coord._resurrection_cap(record)
    assert cap is not None and 900 < cap < 940  # 615 + ~50% falling

    await _recover_after(hass, coord, eid[0], record, 4446.0, frozen=True)

    assert record[DEV_TODAY_MAX] == cap
    # The label is asserted through the close path in its own test.


async def test_the_label_names_both_figures(hass: HomeAssistant, freezer):
    """The LEARNED cell reads capped with witnessed and kept."""
    device, eid = register_device(hass, "cap2", "Labelled Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)
    coord._grace_until = 0.0
    # Open a real episode first, then recover past the cap.
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4446.0
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES], "no episode opened"
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN

    hass.states.async_set(eid[0], "1")
    await hass.async_block_till_done()

    row = coord.data[DATA_EPISODES][-1]
    assert row[EP_LEARNED].startswith("capped (74m -> ")


async def test_below_the_cap_learns_in_full(hass: HomeAssistant, freezer):
    """A convicted gap under the cap is genuine evidence and teaches."""
    device, eid = register_device(hass, "cap3", "Under Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)
    cap = coord._resurrection_cap(record)

    await _recover_after(hass, coord, eid[0], record, cap - 60.0, frozen=True)

    assert abs(record[DEV_TODAY_MAX] - (cap - 60.0)) < 1.0


async def test_unconvicted_life_is_untouched(hass: HomeAssistant, freezer):
    """The same long gap without a conviction learns whole (#104)."""
    device, eid = register_device(hass, "cap4", "Ordinary Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)

    await _recover_after(hass, coord, eid[0], record, 4446.0, frozen=False)

    assert record[DEV_TODAY_MAX] == 4446.0


async def test_taint_outranks_the_cap(hass: HomeAssistant, freezer):
    """An attributed outage is discarded whole, never capped (#166)."""
    device, eid = register_device(hass, "cap5", "Tainted Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)
    record[DEV_TAINTED] = TAINT_UNAVAILABLE
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4446.0

    hass.states.async_set(eid[0], "1")
    await hass.async_block_till_done()

    assert record[DEV_TODAY_MAX] is None  # nothing learned at all
    assert record[DEV_TAINTED] is False   # and the taint was consumed


async def test_a_slow_device_steps_gently(hass: HomeAssistant, freezer):
    """Twelve hours may step about a tenth, not half."""
    device, eid = register_device(hass, "cap6", "Slow Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 43200.0)
    cap = coord._resurrection_cap(record)
    assert cap is not None
    assert 1.08 < cap / 43200.0 < 1.12

    await _recover_after(
        hass, coord, eid[0], record, 24 * 3600.0, frozen=True
    )
    assert record[DEV_TODAY_MAX] == cap


async def test_an_unarmed_device_has_no_cap(hass: HomeAssistant, freezer):
    """Too few learned days: no rhythm, no conviction, no cap."""
    device, eid = register_device(hass, "cap7", "Young Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * 2  # under the arming gate

    assert coord._resurrection_cap(record) is None
