# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.5 (2026-07-19)

"""0.4.5 tests: the refined SIGNAL LOWS marks and the report-count
frozen judgment.

The marks: the floor's earliest occurrence is bold, and a value equal
to the floor is never struck. The frozen rule: five identical reports
on a device lively by its own rhythm, counting reports rather than
elapsed time so it fits fast and slow reporters alike, and surviving a
restart because the counter is stored.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_REPEAT_COUNT,
    DEV_SIGNAL_VALUE,
    SIGNAL_FROZEN_REPEAT_COUNT,
    SIGNAL_RAIL_LQI,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "m45")},
        name="Marks45 Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "m45",
        suggested_object_id="m45_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id


# The marks: earliest floor bold, never strike a value equal to floor.


async def test_repeated_floor_bolds_the_earliest_and_strikes_none_equal(
    hass: HomeAssistant,
):
    """A flat run at the floor value: the earliest occurrence is bold,
    the rest are plain, and none of the equal values is struck. This
    is the flat-button case that read as one bold, one struck, two
    plain before the fix."""
    coord, device_id = await _coordinator(hass)
    # Stored oldest-to-newest; displayed newest-first. Four 48s, k=0
    # under a week so floor is 48. Earliest 48 (index 1) bolds.
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        68.0, 48.0, 48.0, 48.0, 52.0, 48.0, 56.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "Marks45 Device" in line
    )
    # Exactly one bold, and it is a 48; no struck values at all
    # (nothing is strictly below the floor of 48).
    assert row.count("**") == 2  # one bold pair
    assert "**48**" in row
    assert "~~" not in row


async def test_below_floor_is_struck_but_equal_is_not(hass: HomeAssistant):
    """A value strictly below the floor is struck; an equal one is
    not. Floor is 112 here (k=1 at a week trims the 84)."""
    coord, device_id = await _coordinator(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        116.0, 116.0, 116.0, 120.0, 112.0, 112.0, 116.0, 84.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(
        line for line in text.splitlines() if "Marks45 Device" in line
    )
    assert "~~84~~" in row      # strictly below floor 112: struck
    assert "**112**" in row     # earliest 112: bold
    # The other 112 is plain, not struck (equal to the floor).
    assert "~~112~~" not in row


# The frozen counter and its persistence.


async def test_counter_survives_a_restart(hass: HomeAssistant):
    """The repeat counter is stored, so a restart mid-freeze does not
    reset it: a genuinely stuck signal stays caught across the nightly
    reboot rather than needing five fresh reports each morning."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    # Drive the counter to the threshold.
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT):
        coord._feed_signal(rec, 80.0, 1000.0 + tick)
    assert rec[DEV_SIGNAL_REPEAT_COUNT] == SIGNAL_FROZEN_REPEAT_COUNT

    # Persist, then reload as a restart would.
    await coord._store.async_save(coord.data)
    loaded = await coord._store.async_load()
    restored = loaded["devices"][device_id]
    assert restored[DEV_SIGNAL_REPEAT_COUNT] == SIGNAL_FROZEN_REPEAT_COUNT


async def test_slow_reporter_freezes_on_five_reports_not_time(
    hass: HomeAssistant,
):
    """A device reporting hours apart is judged on five identical
    reports, not elapsed time: the same rule that catches a seconds
    reporter catches it, with no time threshold to tune."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_DAILY_MAX] = [3600.0, 3500.0, 3400.0, 3600.0, 3550.0,
                          3400.0, 3600.0]
    import homeassistant.util.dt as dt_util
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60
    # Five identical reports spaced hours apart (timestamps far apart).
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT):
        coord._feed_signal(rec, 116.0, 1000.0 + tick * 6 * 3600)
    assert coord.signal_frozen(rec) is True


async def test_rail_repeats_reach_the_count_and_flag_rail(
    hass: HomeAssistant,
):
    """A rail value repeated reaches the count like any other, and is
    flagged as a rail freeze, the clearest fault."""
    coord, device_id = await _coordinator(hass)
    rec = coord.data["devices"][device_id]
    rec[DEV_DAILY_MAX] = [3600.0, 3500.0, 3400.0, 3600.0, 3550.0,
                          3400.0, 3600.0]
    import homeassistant.util.dt as dt_util
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60
    for tick in range(SIGNAL_FROZEN_REPEAT_COUNT):
        coord._feed_signal(rec, SIGNAL_RAIL_LQI, 1000.0 + tick)
    assert rec[DEV_SIGNAL_VALUE] == SIGNAL_RAIL_LQI
    assert coord.signal_frozen(rec) is True
    assert coord.signal_frozen_at_rail(rec) is True
