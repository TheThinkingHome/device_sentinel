# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_stats.py, Version: 0.23.5 (2026-09-25)

"""The good-state statistics and the dwell chart (0.10.15).

Two features that exist for different futures. The running mean and
standard deviation are what the Bayesian successor to percentile
thresholding needs (#172), recorded ahead of the method: sum, sum of
squares, and count, three floats per device, rolled at midnight into
one mean, one deviation, and the day's maximum, then reset. They are
clock-shaped, so they live in the hot file, and CLOCK_FIELDS
membership is asserted here because that single tuple drives the hot
write, the merge, and the Phase C strip all at once.

The dwell chart is the human surface: a static HTML file under www,
so a browser, an email client, and a dashboard Webpage card all
render it, colored by band. Green to 5 percent always, yellow to the
Red Threshold slider, red above it, and every red device is pulled
out as an anomaly and described in full. It is report coloring only:
nothing alerts from it (#59).
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
    EP_SIG_LINE,
    EP_SIG_MEAN,
    EP_SIG_VALUE,
    EP_SIGNAL,
    EP_SINCE,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    SIGNAL_RAIL_LQI,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_coordinator, setup_entry


def _brief_path(hass: HomeAssistant) -> str:
    return os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML)


def _brief_text(hass: HomeAssistant) -> str:
    with open(_brief_path(hass), encoding="utf-8") as handle:
        return handle.read()


def _trimmed(coordinator, depth):
    """Return the coordinator with a chosen trim depth.

    The trim is a constant since ruling #311, so a test
    that needs a different depth patches the accessor
    rather than saving an option nothing reads.
    """
    coordinator._signal_trim = lambda: depth
    return coordinator


async def test_the_accumulators_live_in_the_clock_fields():
    """One tuple drives the hot write, the merge, and the strip.

    The accumulators move with every reading, which makes them
    clock-shaped; membership here is what routes them to the hot file
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
    record = coord.data[DATA_DEVICES][device.id]

    # A minute apart, because the mean and deviation weigh minutes
    # held rather than readings taken (ruling #259): a value fed at
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
    record = coord.data[DATA_DEVICES][device.id]
    # A minute each, so the three weigh equally (ruling #259): the
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
    record = coord.data[DATA_DEVICES][device.id]

    coord._roll_signal_stats(record, 86400.0)

    assert not record.get(DEV_SIGNAL_DAILY_MEAN)
    assert not record.get(DEV_SIGNAL_DAILY_SD)
    assert not record.get(DEV_SIGNAL_DAILY_P5)
    assert not record.get(DEV_SIGNAL_DAILY_P50)


async def test_a_held_value_cannot_fabricate_a_day(
    hass: HomeAssistant,
):
    """A silent day writes no row however long the value was held.

    The fault this pins (ruling #305): the Welford count is
    time-weighted and the held value accrues minutes through silence
    (#253), so a device that reported once and went quiet weighed a
    full day at every following fold and the fold wrote a row of
    statistics for a day that never happened, with None in the
    maximum. Nine such rows on the first external fleet.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st4", "Once Device")
    record = coord.data[DATA_DEVICES][device.id]

    # One real reading on day one.
    coord._feed_signal(record, -60.0, 1000.0)
    coord._roll_signal_stats(record, 86400.0)
    assert len(record.get(DEV_SIGNAL_DAILY_MEAN) or []) == 1

    # Silence through day two: the held value accrues weight but no
    # reading arrives, which is the exact state that fabricated rows.
    coord._roll_signal_stats(record, 2 * 86400.0)

    assert len(record.get(DEV_SIGNAL_DAILY_MEAN) or []) == 1
    assert len(record.get(DEV_SIGNAL_DAILY_MAX) or []) == 1
    assert None not in (record.get(DEV_SIGNAL_DAILY_MAX) or [])
    assert len(record.get(DEV_SIGNAL_DAILY_COUNT) or []) == 1


async def test_a_rail_only_day_writes_the_rail_and_nulls(
    hass: HomeAssistant,
):
    """A day of nothing but rails keeps its evidence (ruling #305).

    Three consecutive rail days are what confirms a rail (#78), so
    the day cannot be dropped; and there is no statistic to record,
    so the row carries the rail count, a zero reading count, and
    null in every statistic, keeping the eight series aligned.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st5", "Railed Device")
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
    """The #305 load repair left with the rows it repaired (#322).

    The guarded fold cannot write a fabricated row, and the rail
    verdict requires rail above zero, so a legacy zero-count
    zero-rail row is inert: it is neither repaired nor read as
    evidence. The erased series are swept by the reconciler on the
    same load.
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
    """Dwell's brief line is retired with dwell (ruling #310).

    The bad-day sentence lives on the signal report until its
    thresholds have earned the brief, so even a screaming device
    puts nothing about signal in the morning prose.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "b1", "Anomalous Device")
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
    """daily_brief.html (#178), in the reports folder since 0.23.5.

    Rendered from the Markdown text itself so the two cannot drift:
    the heading and the problem table arrive as HTML, and the page
    carries its dark-mode stylesheet.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "bh1", "Anomalous Device")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_VALUE] = 40.0
    # Falling in small steps: a cell that falls only in steps of five
    # or more is judged by the low threshold alone and never
    # forecast (0.23.1), and this test needs one in the brief.
    record["battery_daily_value"] = [52.0, 50.0, 48.0, 46.0, 44.0, 42.0, 40.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _brief_text(hass)

    assert "<h1>Device Sentinel Daily Brief</h1>" in page
    assert "<h2>In Short</h2>" in page
    assert "<table>" in page and "<th>DEVICE</th>" in page
    assert "prefers-color-scheme: dark" in page


async def test_the_brief_is_one_file(hass: HomeAssistant):
    """No Markdown brief since 0.10.18, and no dated copies since
    0.23.5: one daily_brief.html, and nothing written under www."""
    import glob as _glob

    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert not _glob.glob(hass.config.path("device_sentinel", "daily_brief_*"))
    assert os.path.isfile(_brief_path(hass))
    assert not os.path.exists(hass.config.path("www", "device_sentinel"))


async def test_the_diagnostics_live_one_level_up(hass: HomeAssistant):
    """0.10.18: the maintainer files write to device_sentinel itself,
    and a leftover set in the old diagnostics subfolder is cleaned
    while anything else in that folder is left alone."""
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
    """#135 as amended: the html payload is the exact string written
    to the brief file, one rendering for disk and mail.

    Rewritten in 0.10.19. As first written this test took an
    in-progress write and any text at all, and asserted the payload
    matched the current file, which is what the fault of #184 did
    every morning: it paired the closed day's text with a page
    belonging to another window. The rule it was meant to hold is
    that the mail carries the page of the document being sent, so it
    now takes a closing write and the text that write returned. Since
    0.23.5 there is no dated file to hold the closed day, so the page
    is rendered from that text, which is exactly what the writer
    wrote before it opened the new day.
    """
    coord = await setup_coordinator(hass)
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    assert text is not None

    payload = coord._brief_payload("notify.mail", text)
    assert payload["data"]["html"] == coord._render_brief_html(text)
    assert payload["message"] == text


# ------------------------------------ the good-state ceiling (#193)

def _seed_signal(coord, device_id, p5_days, mean, sd):
    """Give a device a P5 history and yesterday's statistics."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_SIGNAL_DAILY_P5] = list(p5_days)
    record[DEV_SIGNAL_DAILY_MEAN] = [mean]
    record[DEV_SIGNAL_DAILY_SD] = [sd]
    return record


async def test_the_line_can_never_cross_into_the_normal_readings(
    hass: HomeAssistant,
):
    """Ruling #193, from Window Dining Room Right on 2026-08-03.

    Its floor was 240, so a 5 percent margin was 12 points and put
    the line at 252, above its own mean of 246.2. A device whose
    line sits above its average reading is below that line nearly
    all day by arithmetic, and it read 97 percent while running one
    of the strongest links on the fleet. LQI stops at 255, so a
    percentage of a high floor is the widest margin exactly where
    there is least room for it.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs1", "Strong Link")
    record = _seed_signal(
        coord,
        device.id,
        [240.0, 240.0, 240.0, 248.0, 244.0, 244.0, 236.0,
         248.0, 244.0, 224.0, 248.0, 248.0, 240.0, 244.0],
        246.21,
        4.41,
    )

    line = coord._danger_line(record)
    assert line is not None
    # The plain-minimum floor (ruling #323) is 224, the margin is
    # 5 percent of the distance from perfect, and the unbounded
    # line sits at 225.55, under the ceiling of 238.21 (the mean
    # less the LQI clearance, ruling #244). The ceiling no longer
    # binds this device; it stays as the cap for one whose floor
    # climbs toward its mean.
    assert line == pytest.approx(225.55, abs=0.01)
    assert line < 246.21
    assert coord._line_is_bounded(record) is False


async def test_a_device_with_room_is_left_alone(
    hass: HomeAssistant,
):
    """The guard must not touch the fleet it was not written for.

    Door Gate Garage: floor 124, so the anchored margin is 6.55
    points (five percent of the 131-point headroom) and the line
    130.55, while its mean is 192.8. The ceiling sits far above the
    line and never fires.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs2", "Ordinary Link")
    record = _seed_signal(
        coord,
        device.id,
        [124.0] * 7 + [160.0, 180.0, 200.0, 200.0, 208.0, 212.0, 216.0],
        192.8,
        16.41,
    )

    assert coord._danger_line(record) == pytest.approx(130.55, abs=0.01)
    assert coord._line_is_bounded(record) is False


async def test_the_margin_becomes_a_maximum_on_a_bounded_device(
    hass: HomeAssistant,
):
    """What the change does to the setting, pinned so it is not a
    surprise later: past the point where the ceiling bites, moving
    the slider does nothing to that device."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs3", "Bounded Link")
    record = _seed_signal(
        coord, device.id, [240.0] * 14, 246.21, 4.41
    )

    lines = []
    for pct in (0, 2, 5, 10):
        coord._signal_margin = lambda pct=pct: pct / 100.0
        lines.append(coord._danger_line(record))
    # This device's floor (240) sits within the LQI clearance of its
    # mean (246.21), so the ceiling (238.21, ruling #244) is below the
    # floor itself and holds at every slider position, zero included.
    # A floor inside the noise band is exactly what the clearance
    # exists to keep the line out of, and min() only ever makes a
    # device less sensitive.
    assert lines[0] == lines[1] == lines[2] == lines[3]
    assert lines[0] == pytest.approx(238.21, abs=0.01)


async def test_no_statistics_means_no_ceiling(
    hass: HomeAssistant,
):
    """A fresh install has no mean and deviation yet, so nothing is
    bounded and the line is the anchored formula alone: floor 240
    plus five percent of the 15-point headroom."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs4", "New Link")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = [240.0] * 14
    record[DEV_SIGNAL_DAILY_MEAN] = []
    record[DEV_SIGNAL_DAILY_SD] = []

    assert coord._danger_line(record) == pytest.approx(240.75, abs=0.01)
    assert coord._line_is_bounded(record) is False


async def test_the_diagnostics_say_whether_the_line_was_bounded(
    hass: HomeAssistant,
):
    """Recorded rather than derived, so a download answers it."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs5", "Strong Link")
    _seed_signal(coord, device.id, [240.0] * 14, 246.21, 4.41)

    payload = await async_get_config_entry_diagnostics(hass, coord.entry)
    row = payload["devices"][device.id]
    assert row["signal_line_bounded"] is True


# ------------------------------- the window and the ladder (#196)

async def test_weak_links_are_counted_apart_from_rails(
    hass: HomeAssistant,
):
    """Ruling #211. Signal: Problems counted one kind under a plural
    name, so a fleet with no rails read zero and looked inert. Adding
    weak links to it would have made one number mean two things, and
    the two are not alike: a rail is a broken measurement confirmed
    over three days, a weak link is a live reading that moves.

    So they are counted apart, the way Battery: Low and Battery:
    Falling are, and the weak rule is the one the brief and the chart
    already use.
    """
    coord = await setup_coordinator(hass, {})
    weak, _ = register_device(hass, "sp1", "Weak Link")
    fine, _ = register_device(hass, "sp2", "Fine Link")
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

    # And it stays off the list that notifies, which is the whole
    # point of the split (rulings #59 and #210).
    assert coord.signal_problem_list == []
    assert coord.signal_problem_count == 0
    assert not any(
        row["device_id"] == weak.id for row in coord._current_problems()
    )


async def test_a_signal_muted_device_is_not_counted_low(
    hass: HomeAssistant,
):
    """Exclusion suppresses judgment, so it suppresses this too."""
    coord = await setup_coordinator(
        hass, {CONF_SIGNAL_MUTED_DEVICES: []}
    )
    weak, _ = register_device(hass, "sp3", "Excluded Link")
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
    """A rail dwells below its own line by construction, so without
    the guard a stuck device would appear in both counts and a person
    adding them would see one fault as two.
    """
    coord = await setup_coordinator(hass, {})
    device, _ = register_device(hass, "sp5", "Railed Link")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_COUNT] = [0] * 4
    record[DEV_SIGNAL_DAILY_RAIL] = [7] * 4

    assert coord.signal_problem_count == 1
    assert coord.signal_weak_count == 0


async def test_the_retired_signal_problems_sensor_is_swept(
    hass: HomeAssistant,
):
    """Signal: Problems became two sensors, so its registry entry is
    removed rather than left as an unavailable row (ruling #211).
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


async def test_the_clearance_frees_a_near_constant_device(
    hass: HomeAssistant,
):
    """Ruling #244, from Master City Blinds on 2026-08-07.

    A motion-blind holding an RSSI inside 2 dB for days: mean -50.92,
    deviation 1.43. Half a deviation put the ceiling at -51.64,
    inside the two values the device alternates between, and a day
    of ordinary -50/-52 chatter read 94.89 percent dwell. With the
    3 dB RSSI clearance the ceiling sits at -53.92 and both readings
    are healthy.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs5", "Near Constant Blind")
    record = _seed_signal(
        coord, device.id, [-54.0] * 14, -50.92, 1.43
    )

    line = coord._danger_line(record)
    assert line is not None
    assert line == pytest.approx(-53.92, abs=0.01)
    assert -52.0 > line
    assert coord._line_is_bounded(record) is True


async def test_a_zero_deviation_day_cannot_put_the_line_on_the_mean(
    hass: HomeAssistant,
):
    """Dining Shades: deviation exactly 0.00 across a whole day.

    Half of zero is zero, so before ruling #244 the ceiling was the mean
    itself, and dwell counts at-or-below: a device reading its own
    mean all day read 100 percent. The clearance makes zero
    deviation the strongest case rather than the degenerate one.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs6", "Constant Shade")
    record = _seed_signal(coord, device.id, [-64.0] * 14, -60.0, 0.0)

    line = coord._danger_line(record)
    assert line is not None
    assert line == pytest.approx(-63.0, abs=0.01)
    assert -60.0 > line


async def test_the_fold_records_count_line_and_rail(
    hass: HomeAssistant,
):
    """Rulings #245, #322: the day folds the count and the rail.

    The count says how much weight the day's statistics deserve,
    and the rail count says why a day's real statistics are thin.
    Both trim on the same retention as the series beside them. The
    line series left with the dwell record (ruling #322).
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs7", "Recorded Link")
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
    """Ruling #246: the join is captured when the silence begins.

    The anchor is the correlation between signal level and rhythm
    stress, and the statistics have moved on by the time anyone
    analyzes them, so the episode row stamps the last reading, the
    day's running mean and deviation, and the line in effect at its
    open. A completed episode folds a compact row into the
    signal_stress series, which rides the history retention rather
    than the fourteen-day episode trim.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs8", "Stressed Link")
    record = _seed_signal(
        coord, device.id, [100.0] * 14, 140.0, 20.0
    )
    # A minute apart so the first value is weighed (ruling #259).
    for index, value in enumerate((140.0, 136.0)):
        coord._feed_signal(record, value, 1000.0 + index * 60.0)

    snapshot = coord._signal_snapshot(record)
    assert snapshot[EP_SIG_VALUE] == 136.0
    # 140 for its one held minute; the 136 that follows has been held
    # for no time yet, so the day's mean is 140 rather than the
    # average of the two readings (ruling #259).
    assert snapshot[EP_SIG_MEAN] == pytest.approx(140.0, abs=0.01)
    assert snapshot[EP_SIG_LINE] is not None

    episode = {
        EP_DEVICE_ID: device.id,
        EP_NAME: "Stressed Link",
        EP_SINCE: 1000.0,
        EP_ENDED: "resumed",
        EP_AT: 5000.0,
        EP_SIGNAL: snapshot,
    }
    coord._fold_signal_stress(episode, 5000.0)
    rows = coord.data[DATA_SIGNAL_STRESS]
    assert len(rows) == 1
    assert rows[0][EP_SIGNAL][EP_SIG_VALUE] == 136.0

    # A row older than the retention window is trimmed by the fold.
    old_row = dict(episode, **{EP_SINCE: 5000.0 - 400 * 86400.0})
    coord.data[DATA_SIGNAL_STRESS].append(old_row)
    coord._fold_signal_stress(episode, 5000.0)
    assert all(
        (row.get(EP_SINCE) or 0) >= 5000.0 - coord.retention_days * 86400.0
        for row in coord.data[DATA_SIGNAL_STRESS]
    )

# ------------------------------------ the percentile recording (#253)

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
    """Ruling #253's whole point: a sparse reporter's held value
    counts by duration. Two readings, one held for 95 minutes at 100
    and one for 5 minutes at 40, must give a P50 near 100, where a
    reading-weighted median of the two values would sit at 70."""
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
    """Ruling #256: the conversion runs at load, before the
    reconciler deletes the legacy pair, and is arithmetic rather
    than approximation. Written after the 0.12.19 build shipped the
    same conversion inside the reading path, where it could never
    run: by then the reconciler had already removed the sums it
    needed and inserted the running mean it tested for, so the day
    restarted at zero against a full count and every running mean on
    the fleet drifted toward a tenth of its value.
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
    """The repair half of #256, and its one-shot gate.

    A record from 0.12.19 or 0.12.20 carries a full count with a
    running mean built from only the readings since the upgrade, and
    the sums that could rebuild it are gone. The day in progress is
    dropped so the fold cannot write a false mean into the ninety-day
    series, and the marker stops a later restart dropping another.
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
    """Midnight appends the day's percentiles beside mean and sd,
    resets the trackers, and removes the naive accumulators from a
    migrated record so storage sheds them at the first fold."""
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
    """The ceiling, the line, and the reports survive a null day.

    The 20 August outage: the first fold under the #305 guard wrote a
    rail-only row with null statistics, exactly as designed, and
    _good_state_ceiling read means[-1] unguarded, so the morning
    report write took the whole integration down. The ceiling now
    rests on the most recent day that has statistics, and a record
    whose every day is rail-only has no ceiling rather than a crash.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st8", "Railed All Day")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_SCALE] = "lqi"

    # Day one: real readings, so the ceiling has something to rest on.
    coord._feed_signal(record, 180.0, 1000.0)
    coord._feed_signal(record, 184.0, 2000.0)
    coord._roll_signal_stats(record, 86400.0)
    ceiling_before = coord._good_state_ceiling(record)
    assert ceiling_before is not None

    # Day two: nothing but rails, the row the outage was made of.
    coord._feed_signal(record, 255.0, 86400.0 + 1000.0)
    coord._roll_signal_stats(record, 2 * 86400.0)
    assert (record.get(DEV_SIGNAL_DAILY_MEAN) or [])[-1] is None

    # The readers all survive, and the ceiling rests on day one.
    assert coord._good_state_ceiling(record) == ceiling_before
    coord._danger_line(record)

    # Every reader at once: the whole report pipeline renders over
    # the null day. The outage had two readers with the same fault
    # and the sweep that fixed the first was truncated and missed
    # the second, so this test stops trusting sweeps: a reader
    # anywhere in the render path that cannot read a rail-only row
    # fails here rather than on a fleet.
    await hass.async_add_executor_job(coord._write_reports)
    telemetry = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    assert "Railed All Day" in telemetry

    # A record that has only ever railed has no ceiling.
    other, _ = register_device(hass, "st9", "Born Railed")
    fresh = coord.data[DATA_DEVICES][other.id]
    fresh[DEV_SIGNAL_SCALE] = "lqi"
    coord._feed_signal(fresh, 255.0, 1000.0)
    coord._roll_signal_stats(fresh, 86400.0)
    assert coord._good_state_ceiling(fresh) is None
