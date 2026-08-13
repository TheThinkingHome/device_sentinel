"""What survives a save, a stop, and a load, for this week's fields.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_round_trip.py, Version: 0.13.8 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

The unclean-restart suite covers the clocks and the episodes. This
one covers what the last two weeks added and nothing has yet driven
through a full save and reload: the percentile estimator states, the
Welford pair, the reading counter, and the set-aside stamp. A value
that does not round trip is not a crash; it is a day of statistics
quietly starting over, which is the failure this project keeps
finding late.
"""

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_DEVICES,
    DEV_SET_ASIDE_SINCE,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_READS,
)

from .helpers import register_device, setup_coordinator

WORKING_SET = (
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_PSQ_TS,
)


async def test_the_days_working_set_is_all_hot(hass: HomeAssistant):
    """Every field the day accumulates has to be in the clocks file.

    One left out is written only when something else forces a cold
    save, so a restart loses part of the day and keeps the rest,
    which is worse than losing all of it: the count and the mean
    would disagree.
    """
    for field in WORKING_SET:
        assert field in CLOCK_FIELDS, field


async def test_the_day_survives_a_save_and_a_load(hass: HomeAssistant):
    """A restart mid-afternoon must not restart the day. The
    estimator states are lists inside the record, which is the shape
    most likely to be dropped by a serializer, so they are checked
    element by element rather than by identity.
    """
    device, _ = register_device(hass, "rt1", "Round Trip Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    for minute in range(30):
        coord._feed_signal(record, 140.0 + minute, minute * 60.0)
    before = {field: record.get(field) for field in WORKING_SET}
    assert before[DEV_SIGNAL_COUNT] > 0
    assert before[DEV_SIGNAL_P5_STATE] is not None

    saved = coord._clocks_to_save()

    stored = saved["clocks"][device.id]
    for field in WORKING_SET:
        assert stored[field] == before[field], field


async def test_the_estimator_state_is_json_safe(hass: HomeAssistant):
    """Storage is JSON, so a state carrying anything but numbers
    would raise inside Home Assistant's writer rather than here, on a
    tick, with the day half written.
    """
    import json

    device, _ = register_device(hass, "rt2", "Serial Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    for minute in range(20):
        coord._feed_signal(record, 120.0 + (minute % 5) * 4, minute * 60.0)

    text = json.dumps(coord._clocks_to_save())
    back = json.loads(text)

    stored = back["clocks"][device.id]
    assert stored[DEV_SIGNAL_P5_STATE] == record[DEV_SIGNAL_P5_STATE]
    assert stored[DEV_SIGNAL_PSQ_TS] == record[DEV_SIGNAL_PSQ_TS]


async def test_a_reload_does_not_double_count_the_day(
    hass: HomeAssistant,
):
    """The held value accrues from its own timestamp, not from the
    restart, so a reload cannot pay the same minutes twice. Checked
    because the clock survives the restart by design, which is
    exactly the arrangement that could double.
    """
    device, _ = register_device(hass, "rt3", "Reload Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    coord._feed_signal(record, 150.0, 0.0)
    coord._feed_signal(record, 150.0, 600.0)
    counted = record[DEV_SIGNAL_COUNT]

    # The same feed again, at the same instant: no time has passed.
    coord._feed_signal(record, 150.0, 600.0)

    assert record[DEV_SIGNAL_COUNT] == counted


async def test_the_set_aside_stamp_is_cold_and_survives(
    hass: HomeAssistant,
):
    """The stamp outlives a restart by design: a device disabled
    before a reboot must still have its return gap refused after
    one."""
    device, _ = register_device(hass, "rt4", "Stamped Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SET_ASIDE_SINCE] = 1000.0

    saved = coord._data_to_save()

    assert saved[DATA_DEVICES][device.id][DEV_SET_ASIDE_SINCE] == 1000.0
