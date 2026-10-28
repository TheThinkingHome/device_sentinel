# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_stats.py, Version: 0.27.10 (2026-10-27)

"""The good-state statistics, what each signal day keeps, and the
signal sensors (rules SIG-05, SIG-07, SIG-09, SIG-10, SIG-11).

The running mean and standard deviation are recorded ahead of any alert
that uses them: a count, a running mean and M2 per device, weighed by
minutes held and rolled at midnight into one mean, one deviation, and
the day's maximum, then reset. They change with every reading, so they
live in the clocks file, and CLOCK_FIELDS membership is asserted here
because that single tuple drives the clocks write, the merge and the
strip all at once.

A weak signal raises no alert yet (rule SIG-10): rails and weak links
are counted on their own sensors, and the brief carries no weak-signal
line.
"""

from __future__ import annotations

import os

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CLOCK_FIELDS,
    CONF_SIGNAL_MUTED_DEVICES,
    DATA_DEVICES,
    DATA_SIGNAL_STRESS,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_BATTERY_VALUE,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_TODAY_MAX,
    DOMAIN,
    EP_AT,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_NAME,
    EP_SIG_MEAN,
    EP_SIG_VALUE,
    EP_SIGNAL,
    EP_SINCE,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    SIGNAL_RAIL_LQI,
)

from .helpers import registry_settled, register_device, setup_coordinator, setup_entry

# A real moment for the fixtures' stamps: the storage check refuses
# a time before 2020 as impossible (rule STOR-07).
TIME_BASE = 1_780_000_000.0


def _brief_path(hass: HomeAssistant) -> str:
    return os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML)


def _brief_text(hass: HomeAssistant) -> str:
    with open(_brief_path(hass), encoding="utf-8") as handle:
        return handle.read()


async def test_the_accumulators_live_in_the_clock_fields():
    """One tuple drives the clocks write, the merge, and the strip.

    The accumulators move with every reading, which makes them
    clock-shaped; membership here is what routes them to the clocks file
    and keeps them out of the stripped main file, with no further
    wiring anywhere.
    """
    for field in (
        DEV_SIGNAL_MEAN_RUN,
        DEV_SIGNAL_M2,
        DEV_SIGNAL_COUNT,
        DEV_SIGNAL_TODAY_MAX,
    ):
        assert field in CLOCK_FIELDS


async def test_readings_accumulate_and_rails_do_not(
    hass: HomeAssistant,
):

    """Welford's mean, M2, count, and the day's maximum track real readings.

    A rail value is the type's fill value, not a measurement, so it
    feeds none of them, for the same reason it never feeds the floor.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st1", "Stats Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]

    # A minute apart, because the mean and deviation weigh minutes
    # held rather than readings taken (rule SIG-05): a value fed at
    # the same instant as the last was held for no time and counts
    # for nothing. One minute each gives the three equal weight.
    for index, value in enumerate((100.0, 120.0, 110.0)):
        coord._feed_signal(record, value, 1000.0 + index * 60.0)
    coord._feed_signal(record, float(SIGNAL_RAIL_LQI), 1180.0)

    assert record[DEV_SIGNAL_MEAN_RUN] == pytest.approx(110.0)
    # M2 is the sum of squared distances from the mean: 100+100+0.
    assert record[DEV_SIGNAL_M2] == pytest.approx(200.0)
    # Two minutes counted, not three: the last value's minute is fed
    # by the next reading or by the fold, and the rail that follows
    # returns before the accumulators. The mean is unaffected here
    # because the unfed value is the mean.
    assert record[DEV_SIGNAL_COUNT] == 2
    assert record[DEV_SIGNAL_READS] == 3
    assert record[DEV_SIGNAL_TODAY_MAX] == 120.0


async def test_the_roll_produces_mean_deviation_and_maximum(
    hass: HomeAssistant,
):
    """Midnight turns the accumulators into one day of series.

    100, 120, 110 has mean 110 and a population deviation of about
    8.16, and the accumulators reset so the new day starts from
    nothing.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st2", "Stats Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    # A minute each, so the three weigh equally (rule SIG-05): the
    # fold feeds the last value's minute itself, which is why the
    # roll time is one minute past the last reading.
    for index, value in enumerate((100.0, 120.0, 110.0)):
        coord._feed_signal(record, value, 1000.0 + index * 60.0)

    coord._roll_signal_stats(record, 1180.0)

    assert record[DEV_SIGNAL_DAILY_MEAN][-1] == 110.0
    assert abs(record[DEV_SIGNAL_DAILY_SD][-1] - 8.16) < 0.01
    assert record[DEV_SIGNAL_DAILY_MAX][-1] == 120.0
    assert record[DEV_SIGNAL_COUNT] == 0
    assert record[DEV_SIGNAL_MEAN_RUN] == 0.0
    assert record[DEV_SIGNAL_M2] == 0.0
    assert record[DEV_SIGNAL_TODAY_MAX] is None


async def test_a_day_with_no_readings_appends_nothing(
    hass: HomeAssistant,
):
    """The series stay aligned with each other rather than padded."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st3", "Quiet Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]

    coord._roll_signal_stats(record, 86400.0)

    assert not record.get(DEV_SIGNAL_DAILY_MEAN)
    assert not record.get(DEV_SIGNAL_DAILY_SD)
    assert not record.get(DEV_SIGNAL_DAILY_P5)
    assert not record.get(DEV_SIGNAL_DAILY_P50)


async def test_a_held_value_cannot_fabricate_a_day(
    hass: HomeAssistant,
):
    """A silent day writes no row however long the value was held
    (rule SIG-05).

    The count is time-weighted and the held value accrues minutes
    through silence, so without this a device that reported once and
    went quiet would weigh a full day at every following fold, and the
    fold would write a row of statistics for a day that never
    happened, with None in the maximum.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st4", "Once Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]

    # One real reading on day one.
    coord._feed_signal(record, -60.0, 1000.0)
    coord._roll_signal_stats(record, 86400.0)
    assert len(record.get(DEV_SIGNAL_DAILY_MEAN) or []) == 1

    # Silence through day two: the held value accrues weight but no
    # reading arrives, the state that would fabricate a row.
    coord._roll_signal_stats(record, 2 * 86400.0)

    assert len(record.get(DEV_SIGNAL_DAILY_MEAN) or []) == 1
    assert len(record.get(DEV_SIGNAL_DAILY_MAX) or []) == 1
    assert None not in (record.get(DEV_SIGNAL_DAILY_MAX) or [])
    assert len(record.get(DEV_SIGNAL_DAILY_COUNT) or []) == 1


async def test_a_rail_only_day_writes_the_rail_and_nulls(
    hass: HomeAssistant,
):
    """A day of nothing but rails keeps its evidence (rule SIG-05).

    Three consecutive rail days are what confirms a rail (rule SIG-07),
    so the day cannot be dropped; and there is no statistic to record,
    so the row carries the rail count, a zero reading count, and
    null in every statistic, keeping the seven series aligned.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st5", "Railed Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_SCALE] = "lqi"

    coord._feed_signal(record, 255.0, 1000.0)
    coord._feed_signal(record, 255.0, 2000.0)
    coord._roll_signal_stats(record, 86400.0)

    assert record.get(DEV_SIGNAL_DAILY_RAIL) == [2]
    assert record.get(DEV_SIGNAL_DAILY_COUNT) == [0]
    assert record.get(DEV_SIGNAL_DAILY_MEAN) == [None]
    assert record.get(DEV_SIGNAL_DAILY_MAX) == [None]

    # And the shape check accepts what the fold just wrote.
    from custom_components.device_sentinel.normalise import (
        check_records,
    )

    faults = check_records({device.id: record})
    signal_faults = [f for f in faults if "signal_daily" in f[1]]
    assert signal_faults == []


async def test_the_load_leaves_zero_count_rows_alone(
    hass: HomeAssistant, hass_storage
):
    """An old zero-count, zero-rail row is left alone at load.

    The guarded fold cannot write a fabricated row, and the rail
    verdict requires rail above zero, so such a row is inert: it is
    neither repaired nor read as evidence. The erased series are swept
    by the reconciler on the same load.
    """
    from custom_components.device_sentinel.const import (
        DATA_LAST_VERSION,
        DATA_SIGNAL_DAY_REPAIR,
        DATA_SIGNAL_WEIGHTING,
        DATA_STATS_EPOCH,
        SIGNAL_DAY_REPAIR_MARK,
        SIGNAL_WEIGHTING_MARK,
        STATS_EPOCH,
        STORAGE_KEY,
    )

    from custom_components.device_sentinel.records import (
        _new_device_record,
    )

    record = _new_device_record("2026-08-01T00:00:00+00:00", None)
    record.update(
        {
            DEV_SIGNAL_DAILY_MEAN: [-65.0, -65.0, None, -64.0],
            DEV_SIGNAL_DAILY_SD: [0.5, 0.0, None, 0.4],
            DEV_SIGNAL_DAILY_P5: [-66.0, -66.0, None, -65.0],
            DEV_SIGNAL_DAILY_P50: [-65.0, -65.0, None, -64.0],
            DEV_SIGNAL_DAILY_MAX: [-64.0, None, None, -63.0],
            "signal_daily_line": [-70.0, -70.0, None, -70.0],
            DEV_SIGNAL_DAILY_COUNT: [12, 0, 0, 9],
            DEV_SIGNAL_DAILY_RAIL: [0, 0, 3, 0],
        }
    )
    device, _ = register_device(hass, "st6", "Trim Target")
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            DATA_DEVICES: {device.id: record},
            DATA_LAST_VERSION: "0.16.2",
            DATA_STATS_EPOCH: STATS_EPOCH,
            DATA_SIGNAL_WEIGHTING: SIGNAL_WEIGHTING_MARK,
            DATA_SIGNAL_DAY_REPAIR: SIGNAL_DAY_REPAIR_MARK,
        },
    }
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    stored = coord.data[DATA_DEVICES][device.id]

    # Every row survives, fabricated or not; the erased line series
    # is swept.
    assert stored[DEV_SIGNAL_DAILY_COUNT] == [12, 0, 0, 9]
    assert stored[DEV_SIGNAL_DAILY_RAIL] == [0, 0, 3, 0]
    assert stored[DEV_SIGNAL_DAILY_MEAN] == [-65.0, -65.0, None, -64.0]
    assert "signal_daily_line" not in stored
    # And the inert row is not rail evidence: rail needs rail > 0.
    assert coord.signal_railed(stored) is False


async def test_the_brief_carries_no_signal_anomaly_line(
    hass: HomeAssistant,
):
    """The brief carries no signal line (rule SIG-10).

    The bad-day sentence lives on the signal report until its
    thresholds have earned the brief, so even a screaming device
    puts nothing about signal in the morning prose.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "b1", "Anomalous Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [
        160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0,
    ]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = _brief_text(hass)
    assert "Signal dwell anomalies" not in brief
    assert "Signal fell sharply" not in brief


async def test_the_brief_is_a_page_in_the_reports_folder(
    hass: HomeAssistant,
):
    """daily_brief.html, in the reports folder (rule BRIEF-14).

    Rendered from the Markdown text itself so the two cannot drift:
    the heading and the problem table arrive as HTML, and the page
    carries its dark-mode stylesheet.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "bh1", "Anomalous Device")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_VALUE] = 40.0
    # Falling in small steps: a cell that falls only in steps of five
    # or more is judged by the low threshold alone and never
    # forecast (rule BAT-09), and this test needs one in the brief.
    record["battery_daily_value"] = [52.0, 50.0, 48.0, 46.0, 44.0, 42.0, 40.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _brief_text(hass)

    assert "<h1>Device Sentinel Daily Brief</h1>" in page
    assert "<h2>In Short</h2>" in page
    assert "<table>" in page and "<th>DEVICE</th>" in page
    assert "prefers-color-scheme: dark" in page


async def test_the_brief_is_one_file(hass: HomeAssistant):
    """No Markdown brief and no dated copies: one daily_brief.html, and
    nothing written under www (rule BRIEF-14)."""
    import glob as _glob

    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert not _glob.glob(hass.config.path("device_sentinel", "daily_brief_*"))
    assert os.path.isfile(_brief_path(hass))
    assert not os.path.exists(hass.config.path("www", "device_sentinel"))


async def test_the_diagnostics_live_one_level_up(hass: HomeAssistant):
    """The maintainer files write to device_sentinel itself, and a
    leftover set in the old diagnostics subfolder is cleaned while
    anything else in that folder is left alone (rule BRIEF-14)."""
    old_dir = hass.config.path("device_sentinel", "diagnostics")
    os.makedirs(old_dir, exist_ok=True)
    for name in ("device_telemetry.md", "not_ours.txt"):
        with open(
            os.path.join(old_dir, name), "w", encoding="utf-8"
        ) as handle:
            handle.write("old")

    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert os.path.isfile(
        hass.config.path("device_sentinel", "device_telemetry.md")
    )
    assert not os.path.isfile(
        os.path.join(old_dir, "device_telemetry.md")
    )
    assert os.path.isfile(os.path.join(old_dir, "not_ours.txt"))


async def test_the_email_body_is_the_page(hass: HomeAssistant):
    """The html payload is the exact string written to the brief file,
    one rendering for disk and mail (rules BRIEF-11, BRIEF-12).

    The mail carries the page of the document being sent, so the test
    takes a closing write and the text that write returned. Pairing
    the closed day's text with the current file would send a page
    belonging to another window. There is no dated file to hold the
    closed day, so the page is rendered from that text, which is what
    the writer wrote before it opened the new day.
    """
    coord = await setup_coordinator(hass)
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    assert text is not None

    payload = coord._brief_payload("notify.mail", text)
    assert payload["data"]["html"] == coord._render_brief_html(text)
    assert payload["message"] == text


# --------------------------------------------------- the signal history

def _seed_signal(coord, device_id, p5_days, mean, sd):
    """Give a device a P5 history and yesterday's statistics."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_SIGNAL_DAILY_P5] = list(p5_days)
    record[DEV_SIGNAL_DAILY_MEAN] = [mean]
    record[DEV_SIGNAL_DAILY_SD] = [sd]
    return record


# ------------------------------------------------- rails and weak links

async def test_weak_links_are_counted_apart_from_rails(
    hass: HomeAssistant,
):
    """Rails and weak links are counted apart (rule SIG-09).

    One number for both would mean two things, and the two are not
    alike: a rail is a broken measurement confirmed over three days, a
    weak link is a live reading that moves. So they are counted apart,
    the way Battery: Low and Battery: Falling are, and the weak rule is
    the bad signal day Signal Trends shows (rule SIG-08).
    """
    coord = await setup_coordinator(hass, {})
    weak, _ = register_device(hass, "sp1", "Weak Link")
    fine, _ = register_device(hass, "sp2", "Fine Link")
    await registry_settled(hass)
    coord.data[DATA_DEVICES][weak.id][DEV_SIGNAL_DAILY_P5] = [
        160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0,
    ]
    coord.data[DATA_DEVICES][fine.id][DEV_SIGNAL_DAILY_P5] = [
        150.0, 151.0, 149.0, 150.0, 152.0, 150.0, 151.0,
    ]

    rows = coord.signal_weak_list
    assert [row["name"] for row in rows] == ["Weak Link"]
    assert coord.signal_weak_count == 1
    assert rows[0]["device_id"] == weak.id
    assert rows[0]["fall"] == 60.0

    # And it stays off the list that notifies, which is the point of
    # the split (rules SIG-09, SIG-10).
    assert coord.signal_problem_list == []
    assert coord.signal_problem_count == 0
    assert not any(
        row["device_id"] == weak.id for row in coord._current_problems()
    )


async def test_a_signal_muted_device_is_not_counted_low(
    hass: HomeAssistant,
):
    """A signal mute suppresses judgment, so it suppresses this too."""
    coord = await setup_coordinator(
        hass, {CONF_SIGNAL_MUTED_DEVICES: []}
    )
    weak, _ = register_device(hass, "sp3", "Excluded Link")
    await registry_settled(hass)
    coord.data[DATA_DEVICES][weak.id][DEV_SIGNAL_DAILY_P5] = [
        160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0,
    ]
    assert coord.signal_weak_count == 1

    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_SIGNAL_MUTED_DEVICES: [weak.id],
        },
    )
    assert coord.signal_weak_count == 0


async def test_a_low_clears_the_moment_its_dwell_falls_back(
    hass: HomeAssistant,
):
    """It is a reading rather than an incident, so it needs no
    acknowledgment and leaves no record: a dashboard shows the fleet
    as it stands and the device drops off when it recovers.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "sp4", "Recovering Link")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]

    record[DEV_SIGNAL_DAILY_P5] = [
        160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0,
    ]
    assert coord.signal_weak_count == 1

    # The next folded day holds its level, so the fall is no longer
    # news and the device drops off.
    record[DEV_SIGNAL_DAILY_P5] = [
        160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0, 158.0,
    ]
    assert coord.signal_weak_count == 0


async def test_a_railed_device_is_not_counted_twice(
    hass: HomeAssistant,
):
    """Without the guard a railed device could appear in both counts,
    and a person adding them would see one fault as two (rule SIG-09).
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "sp5", "Railed Link")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_COUNT] = [0] * 4
    record[DEV_SIGNAL_DAILY_RAIL] = [7] * 4

    assert coord.signal_problem_count == 1
    assert coord.signal_weak_count == 0


async def test_the_retired_signal_problems_sensor_is_swept(
    hass: HomeAssistant,
):
    """Signal: Problems became two sensors, so its registry entry is
    removed rather than left as an unavailable row (rule SIG-09).
    """
    from homeassistant.helpers import entity_registry as er

    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_signal_problems"
        )
        is None
    )


async def test_the_fold_records_count_line_and_rail(
    hass: HomeAssistant,
):
    """The day folds the count and the rail (rule SIG-05).

    The count says how much weight the day's statistics deserve,
    and the rail count says why a day's real statistics are thin.
    Both trim on the same retention as the series beside them. No
    line series is kept (rule SIG-13).
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs7", "Recorded Link")
    await registry_settled(hass)
    record = _seed_signal(
        coord, device.id, [100.0] * 14, 140.0, 20.0
    )
    for value in (140.0, 144.0, 255.0, 136.0, 255.0):
        coord._feed_signal(record, value, 1000.0)

    coord._roll_signal_stats(record, 86400.0)

    assert record[DEV_SIGNAL_DAILY_COUNT][-1] == 3
    assert record[DEV_SIGNAL_DAILY_RAIL][-1] == 2
    assert "signal_daily_line" not in record
    assert record[DEV_SIGNAL_RAIL_COUNT] == 0
    assert record[DEV_SIGNAL_COUNT] == 0


async def test_an_episode_carries_its_signal_snapshot(
    hass: HomeAssistant,
):
    """The join is captured when the silence begins (rule SIG-11).

    The anchor is the correlation between signal level and rhythm
    stress, and the statistics have moved on by the time anyone
    analyzes them, so the episode row stamps the last reading and the
    day's running mean and deviation at its open. A completed episode
    folds a compact row into the signal_stress series, which rides the
    history retention rather than the fourteen-day episode trim.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs8", "Stressed Link")
    await registry_settled(hass)
    record = _seed_signal(
        coord, device.id, [100.0] * 14, 140.0, 20.0
    )
    # A minute apart so the first value is weighed (rule SIG-05).
    for index, value in enumerate((140.0, 136.0)):
        coord._feed_signal(record, value, 1000.0 + index * 60.0)

    snapshot = coord._signal_snapshot(record)
    assert snapshot[EP_SIG_VALUE] == 136.0
    # 140 for its one held minute; the 136 that follows has been held
    # for no time yet, so the day's mean is 140 rather than the
    # average of the two readings (rule SIG-05).
    assert snapshot[EP_SIG_MEAN] == pytest.approx(140.0, abs=0.01)
    # No line: the reading and the good state are what is kept
    # (rules SIG-11, SIG-13).
    assert "line" not in snapshot

    episode = {
        EP_DEVICE_ID: device.id,
        EP_NAME: "Stressed Link",
        EP_SINCE: TIME_BASE + 1000.0,
        EP_ENDED: "resumed",
        EP_AT: TIME_BASE + 5000.0,
        EP_SIGNAL: snapshot,
    }
    coord._fold_signal_stress(episode, 5000.0)
    rows = coord.data[DATA_SIGNAL_STRESS]
    assert len(rows) == 1
    assert rows[0][EP_SIGNAL][EP_SIG_VALUE] == 136.0

    # A row older than the retention window is trimmed by the fold.
    old_row = dict(episode, **{EP_SINCE: TIME_BASE + 5000.0 - 400 * 86400.0})
    coord.data[DATA_SIGNAL_STRESS].append(old_row)
    coord._fold_signal_stress(episode, 5000.0)
    assert all(
        (row.get(EP_SINCE) or 0) >= 5000.0 - coord.retention_days * 86400.0
        for row in coord.data[DATA_SIGNAL_STRESS]
    )

# -------------------------------------------- the percentile recording

async def test_psquare_matches_ground_truth_on_a_dense_stream(
    hass: HomeAssistant
):
    """The estimator against numpy-style exact percentiles on a dense
    day: 1440 minute samples of a two-state (bimodal) link. The
    tolerance is loose because P-Square is a heuristic, but it must
    land in the right neighbourhood or the recording is decoration."""
    import random

    from custom_components.device_sentinel.psquare import (
        psquare_feed,
        psquare_new,
        psquare_read,
    )
    rng = random.Random(41)
    values = [rng.gauss(180, 8) if rng.random() < 0.8 else rng.gauss(90, 6)
              for _ in range(1440)]
    p5 = psquare_new()
    p50 = psquare_new()
    for v in values:
        psquare_feed(p5, 0.05, v)
        psquare_feed(p50, 0.50, v)
    exact = sorted(values)
    exact_p5 = exact[int(0.05 * len(exact))]
    exact_p50 = exact[len(exact) // 2]
    assert abs(psquare_read(p5, 0.05) - exact_p5) < 6.0
    assert abs(psquare_read(p50, 0.50) - exact_p50) < 6.0


async def test_percentiles_are_time_weighted_not_reading_weighted(
    hass: HomeAssistant
):
    """A sparse reporter's held value counts by duration (rule SIG-05).
    Two readings, one held for 95 minutes at 100 and one for 5 minutes
    at 40, must give a P50 near 100, where a reading-weighted median of
    the two values would sit at 70."""
    coord = await setup_coordinator(hass)
    record = {}
    coord._feed_signal(record, 100.0, 0.0)
    coord._feed_signal(record, 40.0, 95 * 60.0)
    coord._roll_signal_stats(record, 100 * 60.0)
    p50 = record[DEV_SIGNAL_DAILY_P50][-1]
    assert p50 > 90.0


async def test_the_load_path_converts_a_legacy_day_exactly(
    hass: HomeAssistant
):
    """The conversion runs at load, before the reconciler deletes the
    old pair, and is arithmetic rather than approximation
    (rule STOR-19). Inside the reading path it could never run: the
    reconciler would already have removed the sums it needs, so the
    day would restart at zero against a full count and every running
    mean would drift toward a tenth of its value.
    """
    coord = await setup_coordinator(hass)
    readings = [140.0, 136.0, 148.0, 132.0]
    legacy = {
        DEV_SIGNAL_COUNT: len(readings),
        DEV_SIGNAL_SUM: sum(readings),
        DEV_SIGNAL_SUM_SQ: sum(v * v for v in readings),
    }

    converted, reset = coord._migrate_signal_accumulators(
        {"dev": legacy}, repair=True
    )

    exact_mean = sum(readings) / len(readings)
    exact_var = sum(
        (v - exact_mean) ** 2 for v in readings
    ) / len(readings)
    assert (converted, reset) == (1, 0)
    assert legacy[DEV_SIGNAL_MEAN_RUN] == pytest.approx(exact_mean)
    assert legacy[DEV_SIGNAL_M2] / legacy[DEV_SIGNAL_COUNT] == pytest.approx(
        exact_var
    )


async def test_a_day_a_broken_release_corrupted_is_dropped_once(
    hass: HomeAssistant
):
    """The repair after a broken conversion, and its one-shot gate
    (rule STOR-19).

    A record with a full count and a running mean built from only the
    readings since an upgrade has lost the sums that could rebuild it.
    The day in progress is dropped so the fold cannot write a false
    mean into the ninety-day series, and the marker stops a later
    restart dropping another.
    """
    coord = await setup_coordinator(hass)
    damaged = {
        DEV_SIGNAL_COUNT: 126,
        DEV_SIGNAL_MEAN_RUN: 9.97,
        DEV_SIGNAL_M2: 119831.0,
    }

    converted, reset = coord._migrate_signal_accumulators(
        {"dev": damaged}, repair=True
    )

    assert (converted, reset) == (0, 1)
    assert damaged[DEV_SIGNAL_COUNT] == 0
    assert damaged[DEV_SIGNAL_MEAN_RUN] == 0.0
    assert damaged[DEV_SIGNAL_P5_STATE] is None

    healthy = {DEV_SIGNAL_COUNT: 40, DEV_SIGNAL_MEAN_RUN: 118.6}
    assert coord._migrate_signal_accumulators(
        {"dev": healthy}, repair=False
    ) == (0, 0)
    assert healthy[DEV_SIGNAL_COUNT] == 40


async def test_the_fold_records_p5_and_p50_and_resets(
    hass: HomeAssistant
):
    """Midnight appends the day's percentiles beside mean and sd and
    resets the trackers (rule SIG-05)."""
    coord = await setup_coordinator(hass)
    record = {}
    coord._feed_signal(record, 120.0, 0.0)
    coord._feed_signal(record, 120.0, 3600.0)
    coord._roll_signal_stats(record, 7200.0)
    assert record[DEV_SIGNAL_DAILY_P5][-1] == pytest.approx(120.0, abs=1.0)
    assert record[DEV_SIGNAL_DAILY_P50][-1] == pytest.approx(120.0, abs=1.0)
    assert record[DEV_SIGNAL_P5_STATE] is None


async def test_a_rail_day_does_not_crash_the_readers(
    hass: HomeAssistant,
):
    """The readers and the reports survive a null day.

    A rail-only row with null statistics is written as designed, and a
    reader that crashes on it takes the whole integration down, so
    every reader must survive the row (rule SIG-05).
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st8", "Railed All Day")
    await registry_settled(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_SCALE] = "lqi"

    # Day one: real readings, so the ceiling has something to rest on.
    coord._feed_signal(record, 180.0, 1000.0)
    coord._feed_signal(record, 184.0, 2000.0)
    coord._roll_signal_stats(record, 86400.0)

    # Day two: nothing but rails.
    coord._feed_signal(record, 255.0, 86400.0 + 1000.0)
    coord._roll_signal_stats(record, 2 * 86400.0)
    assert (record.get(DEV_SIGNAL_DAILY_MEAN) or [])[-1] is None

    # The bad-day judgment reads the null day as no reading.
    assert coord.signal_badday(record) is None

    # Every reader at once: the whole report pipeline renders over
    # the null day, so a reader anywhere in the render path that
    # cannot read a rail-only row fails here rather than on a house.
    await hass.async_add_executor_job(coord._write_reports)
    telemetry = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    assert "Railed All Day" in telemetry

    # A record that has only ever railed has no reading either.
    other, _ = register_device(hass, "st9", "Born Railed")
    await registry_settled(hass)
    fresh = coord.data[DATA_DEVICES][other.id]
    fresh[DEV_SIGNAL_SCALE] = "lqi"
    coord._feed_signal(fresh, 255.0, 1000.0)
    coord._roll_signal_stats(fresh, 86400.0)
    assert coord.signal_badday(fresh) is None
