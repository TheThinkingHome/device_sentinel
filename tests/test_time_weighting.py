"""Tests for weighing the day by minutes rather than readings.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_time_weighting.py, Version: 0.13.8 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Ruling #259. The percentiles have weighed minutes since 0.12.19 while
the mean and deviation counted readings, so a day's four figures
answered two different questions and could not be read side by side.
On this reference fleet reporting rates differ by two orders of
magnitude, which let a device's busy hours outvote its quiet ones in
the mean while the median ignored the difference.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SIGNAL_WEIGHTING,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_READS,
    SIGNAL_WEIGHTING_MARK,
)

from .helpers import register_device, setup_coordinator


async def test_a_held_value_outweighs_a_brief_one(hass: HomeAssistant):
    """The point of the change, in one device.

    Ninety minutes at 200 and ten at 100 is a day that mostly ran at
    200, and the mean now says so. Counting readings would have made
    the two values equal and put the mean at 150, describing a day
    that did not happen.
    """
    device, _ = register_device(hass, "tw1", "Weighted Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._feed_signal(record, 200.0, 0.0)
    coord._feed_signal(record, 100.0, 90 * 60.0)
    coord._feed_signal(record, 200.0, 100 * 60.0)

    assert record[DEV_SIGNAL_COUNT] == 100
    assert record[DEV_SIGNAL_MEAN_RUN] == pytest.approx(190.0)
    assert record[DEV_SIGNAL_READS] == 3


async def test_the_mean_and_the_median_now_agree_on_a_flat_day(
    hass: HomeAssistant,
):
    """Both weigh minutes, so a day at one level puts them on the
    same number. Before the change a chatty hour could separate
    them for no reason in the hardware."""
    device, _ = register_device(hass, "tw2", "Flat Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._feed_signal(record, 150.0, 0.0)
    for minute in range(1, 60):
        coord._feed_signal(record, 150.0, minute * 60.0)
    coord._roll_signal_stats(record, 60 * 60.0)

    assert record[DEV_SIGNAL_DAILY_MEAN][-1] == 150.0
    assert record[DEV_SIGNAL_DAILY_SD][-1] == 0.0
    assert record[DEV_SIGNAL_DAILY_P50][-1] == 150.0


async def test_a_reading_held_for_no_time_counts_for_nothing(
    hass: HomeAssistant,
):
    """Two readings in the same minute describe one minute. Recorded
    because it is the behaviour most likely to look like a fault: a
    device can report and the mean not move."""
    device, _ = register_device(hass, "tw3", "Chatty Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._feed_signal(record, 120.0, 0.0)
    coord._feed_signal(record, 80.0, 1.0)
    coord._feed_signal(record, 120.0, 2.0)

    assert record[DEV_SIGNAL_COUNT] == 0
    assert record[DEV_SIGNAL_READS] == 3


async def test_the_daily_count_still_counts_reports(hass: HomeAssistant):
    """The count series answers how often a device spoke, which no
    time-weighted figure can, so it keeps its own counter rather than
    inheriting the minute count."""
    device, _ = register_device(hass, "tw4", "Counting Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    for minute in range(4):
        coord._feed_signal(record, 140.0, minute * 60.0)
    coord._roll_signal_stats(record, 4 * 60.0)

    from custom_components.device_sentinel.const import (
        DEV_SIGNAL_DAILY_COUNT,
    )

    assert record[DEV_SIGNAL_DAILY_COUNT][-1] == 4
    assert record[DEV_SIGNAL_READS] == 0


async def test_the_upgrade_clears_the_two_series_it_changed(
    hass: HomeAssistant,
):
    """The recorded mean and deviation are not comparable across the
    change, and a series holding both weightings could not be
    separated later, so the old days go once. Everything else stays:
    the minima, the percentiles, and the dwell are the same figures
    they were yesterday.
    """
    device, _ = register_device(hass, "tw5", "Upgraded Device")
    coord = await setup_coordinator(hass)
    loaded = {
        DATA_DEVICES: {
            device.id: {
                DEV_SIGNAL_DAILY_MEAN: [110.0, 112.0],
                DEV_SIGNAL_DAILY_SD: [8.0, 9.0],
                DEV_SIGNAL_DAILY_MIN: [80.0, 84.0],
                DEV_SIGNAL_DWELL_DAILY: [3.0, 4.0],
            }
        }
    }

    coord._clear_reading_weighted_series(loaded)

    record = loaded[DATA_DEVICES][device.id]
    assert record[DEV_SIGNAL_DAILY_MEAN] == []
    assert record[DEV_SIGNAL_DAILY_SD] == []
    assert record[DEV_SIGNAL_DAILY_MIN] == [80.0, 84.0]
    assert record[DEV_SIGNAL_DWELL_DAILY] == [3.0, 4.0]
    assert loaded[DATA_SIGNAL_WEIGHTING] == SIGNAL_WEIGHTING_MARK


async def test_the_clearing_happens_once(hass: HomeAssistant):
    """Marked, so a later restart cannot throw away days recorded
    under the new weighting."""
    device, _ = register_device(hass, "tw6", "Settled Device")
    coord = await setup_coordinator(hass)
    loaded = {
        DATA_DEVICES: {
            device.id: {DEV_SIGNAL_DAILY_MEAN: [150.0], DEV_SIGNAL_DAILY_SD: [2.0]}
        },
        DATA_SIGNAL_WEIGHTING: SIGNAL_WEIGHTING_MARK,
    }

    coord._clear_reading_weighted_series(loaded)

    assert loaded[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_MEAN] == [150.0]


async def test_the_deviation_measures_the_spread_of_time(
    hass: HomeAssistant,
):
    """Half a day at 100 and half at 200 is a deviation of 50,
    whatever the reporting rate. Under reading weighting the same
    hardware could read anything between zero and 50 depending on
    which half it happened to talk during.
    """
    device, _ = register_device(hass, "tw7", "Split Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._feed_signal(record, 100.0, 0.0)
    coord._feed_signal(record, 200.0, 60 * 60.0)
    coord._feed_signal(record, 200.0, 120 * 60.0)

    variance = record[DEV_SIGNAL_M2] / record[DEV_SIGNAL_COUNT]
    assert record[DEV_SIGNAL_COUNT] == 120
    assert variance**0.5 == pytest.approx(50.0)

async def test_the_clearing_takes_the_day_in_progress(
    hass: HomeAssistant,
):
    """The accumulator carried across the upgrade too (ruling #260).

    Built by counting readings, continued by counting minutes, it
    would have folded one hybrid row at the first midnight: exactly
    the mixed figure the clearing exists to prevent, on the one day
    it can happen. The day restarts from the upgrade instead.
    """
    device, _ = register_device(hass, "tw8", "Mid-day Device")
    coord = await setup_coordinator(hass)
    loaded = {
        DATA_DEVICES: {
            device.id: {
                DEV_SIGNAL_DAILY_MEAN: [120.0],
                DEV_SIGNAL_COUNT: 240,
                DEV_SIGNAL_MEAN_RUN: 118.0,
                DEV_SIGNAL_M2: 900.0,
            }
        }
    }

    coord._clear_reading_weighted_series(loaded)

    record = loaded[DATA_DEVICES][device.id]
    assert record[DEV_SIGNAL_COUNT] == 0
    assert record[DEV_SIGNAL_MEAN_RUN] == 0.0
    assert record[DEV_SIGNAL_M2] == 0.0


async def test_a_device_whose_integration_is_still_loading_is_kept(
    hass: HomeAssistant,
):
    """Ruling #260. Integrations register their entities as they
    load, so during the startup window a device with none is usually
    one whose owner has not finished. Setting it aside then and
    bringing it back a second later cost eighteen devices their first
    gap on every restart of the reference system, each discarded as
    administrative by the rule written for a disabling.
    """
    coord = await setup_coordinator(hass)
    source = MockConfigEntry(domain="test", title="Loading Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "loading")},
        name="Still Loading",
    )
    coord._grace_until = dt_util.utcnow().timestamp() + 300.0

    coord._rebuild_registry_view()

    assert device.id in coord._watched
    assert device.id not in coord._set_aside

async def test_the_clearing_runs_again_for_an_install_past_the_first_mark(
    hass: HomeAssistant,
):
    """Ruling #261. The first marker was set by a version that
    cleared the recorded days but left the day accumulating, so an
    install that had already passed it would have folded the hybrid
    row anyway. The marker's value changes, which runs the clearing
    once more, this time taking the day with it.
    """
    device, _ = register_device(hass, "tw9", "Half-cleared Device")
    coord = await setup_coordinator(hass)
    loaded = {
        DATA_DEVICES: {
            device.id: {
                DEV_SIGNAL_COUNT: 293,
                DEV_SIGNAL_MEAN_RUN: 108.0,
            }
        },
        DATA_SIGNAL_WEIGHTING: "minutes",
    }

    coord._clear_reading_weighted_series(loaded)

    assert loaded[DATA_DEVICES][device.id][DEV_SIGNAL_COUNT] == 0
    assert loaded[DATA_SIGNAL_WEIGHTING] == SIGNAL_WEIGHTING_MARK


async def test_the_grace_close_re_reads_the_registry(
    hass: HomeAssistant,
):
    """The second half of ruling #260: the no-entities rule is held
    during startup, so something has to look again when the window
    shuts, or a device that genuinely has none stays watched until an
    unrelated registry change.
    """
    coord = await setup_coordinator(hass)
    source = MockConfigEntry(domain="test", title="Bare Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "bare_after_grace")},
        name="Bare After Grace",
    )
    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    coord._rebuild_registry_view()
    assert device.id in coord._watched

    coord._grace_until = 0.0
    coord._on_grace_closed(None)

    assert device.id not in coord._watched
    assert device.id in coord._set_aside

async def test_a_held_value_costs_the_same_whatever_it_lasts(
    hass: HomeAssistant,
):
    """Ruling #262. Welford for a repeated value has a closed form,
    so a value held for a full day is one arithmetic step rather than
    1440. The figures must match the loop exactly, which is what this
    pins: a day at one level, then a second level, against the
    textbook running update.
    """
    device, _ = register_device(hass, "cf1", "Closed Form Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._feed_signal(record, 120.0, 0.0)
    coord._feed_signal(record, 180.0, 600 * 60.0)
    coord._feed_signal(record, 180.0, 900 * 60.0)

    count = 0
    mean = 0.0
    m2 = 0.0
    for value in [120.0] * 600 + [180.0] * 300:
        count += 1
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)

    assert record[DEV_SIGNAL_COUNT] == count
    assert record[DEV_SIGNAL_MEAN_RUN] == pytest.approx(mean)
    assert record[DEV_SIGNAL_M2] == pytest.approx(m2)


async def test_the_bulk_percentile_feed_matches_the_loop(
    hass: HomeAssistant,
):
    """The estimator has no closed form for a repeat, so the bulk
    feed still iterates; what it drops is the per-observation state
    slicing. Identical results rather than an approximation, which is
    the only reason it is allowed to exist.
    """
    from custom_components.device_sentinel.psquare import (
        psquare_feed,
        psquare_feed_many,
        psquare_new,
    )

    for quantile in (0.05, 0.5):
        one_at_a_time = psquare_new()
        in_bulk = psquare_new()
        for value in (140.0, 96.0, 168.0, 120.0, 152.0, 108.0):
            psquare_feed(one_at_a_time, quantile, value)
            psquare_feed(in_bulk, quantile, value)
        for _ in range(500):
            psquare_feed(one_at_a_time, quantile, 132.0)
        psquare_feed_many(in_bulk, quantile, 132.0, 500)

        assert one_at_a_time == in_bulk


async def test_the_bulk_feed_bootstraps_the_same_way(
    hass: HomeAssistant,
):
    """A fresh estimator handed a long repeat has to bootstrap first,
    which the bulk path defers to the single feed rather than
    reimplementing."""
    from custom_components.device_sentinel.psquare import (
        psquare_feed,
        psquare_feed_many,
        psquare_new,
    )

    one_at_a_time = psquare_new()
    in_bulk = psquare_new()
    for _ in range(40):
        psquare_feed(one_at_a_time, 0.05, 144.0)
    psquare_feed_many(in_bulk, 0.05, 144.0, 40)

    assert one_at_a_time == in_bulk


async def test_a_day_of_readings_with_no_held_minute_is_dropped(
    hass: HomeAssistant,
):
    """Ruling #262. A device can report several times inside one
    minute at the very end of a day, which weighs nothing, so the day
    folds nothing. The reads counter has to go with it: carried
    forward, it put one device's report count on the following day's
    row.
    """
    device, _ = register_device(hass, "cf2", "Late Reporter")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    coord._feed_signal(record, 140.0, 86_399.0)
    coord._feed_signal(record, 144.0, 86_399.5)
    assert record[DEV_SIGNAL_READS] == 2

    coord._roll_signal_stats(record, 86_400.0)

    assert record[DEV_SIGNAL_READS] == 0
    assert not record.get(DEV_SIGNAL_DAILY_COUNT)

