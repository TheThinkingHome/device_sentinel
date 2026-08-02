# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_stats.py, Version: 0.10.16 (2026-08-02)

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

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    CONF_SIGNAL_RED,
    DATA_DEVICES,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_TODAY_MAX,
    REPORT_SIGNAL_DWELL,
    REPORT_WWW_DIR,
    SIGNAL_RAIL_LQI,
)

from .helpers import register_device, setup_coordinator


import glob


def _brief_text(hass: HomeAssistant) -> str:
    written = sorted(
        glob.glob(hass.config.path("device_sentinel", "daily_brief_*.md"))
    )
    assert written
    with open(written[-1], encoding="utf-8") as handle:
        return handle.read()


def _report_path(hass: HomeAssistant) -> str:
    return os.path.join(
        hass.config.path(REPORT_WWW_DIR), REPORT_SIGNAL_DWELL
    )


def _read(hass: HomeAssistant) -> str:
    with open(_report_path(hass), encoding="utf-8") as handle:
        return handle.read()


async def test_the_accumulators_live_in_the_clock_fields():
    """One tuple drives the hot write, the merge, and the strip.

    The accumulators move with every reading, which makes them
    clock-shaped; membership here is what routes them to the hot file
    and keeps them out of the stripped main file, with no further
    wiring anywhere.
    """
    for field in (
        DEV_SIGNAL_SUM,
        DEV_SIGNAL_SUM_SQ,
        DEV_SIGNAL_COUNT,
        DEV_SIGNAL_TODAY_MAX,
    ):
        assert field in CLOCK_FIELDS


async def test_readings_accumulate_and_rails_do_not(
    hass: HomeAssistant,
):
    """Sum, squares, count, and the day's maximum track real readings.

    A rail value is the type's fill value, not a measurement, so it
    feeds none of them, for the same reason it never feeds the floor.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st1", "Stats Device")
    record = coord.data[DATA_DEVICES][device.id]

    for value in (100.0, 120.0, 110.0):
        coord._feed_signal(record, value, 1000.0)
    coord._feed_signal(record, float(SIGNAL_RAIL_LQI), 1000.0)

    assert record[DEV_SIGNAL_SUM] == 330.0
    assert record[DEV_SIGNAL_SUM_SQ] == 100.0**2 + 120.0**2 + 110.0**2
    assert record[DEV_SIGNAL_COUNT] == 3
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
    for value in (100.0, 120.0, 110.0):
        coord._feed_signal(record, value, 1000.0)

    coord._roll_signal_stats(record)

    assert record[DEV_SIGNAL_DAILY_MEAN][-1] == 110.0
    assert abs(record[DEV_SIGNAL_DAILY_SD][-1] - 8.16) < 0.01
    assert record[DEV_SIGNAL_DAILY_MAX][-1] == 120.0
    assert record[DEV_SIGNAL_COUNT] == 0
    assert record[DEV_SIGNAL_SUM] == 0.0
    assert record[DEV_SIGNAL_TODAY_MAX] is None


async def test_a_day_with_no_readings_appends_nothing(
    hass: HomeAssistant,
):
    """The series stay aligned with each other rather than padded."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "st3", "Quiet Device")
    record = coord.data[DATA_DEVICES][device.id]

    coord._roll_signal_stats(record)

    assert not record.get(DEV_SIGNAL_DAILY_MEAN)
    assert not record.get(DEV_SIGNAL_DAILY_SD)


async def test_the_chart_bands_by_the_red_threshold(
    hass: HomeAssistant,
):
    """Green to 5 fixed, yellow to the slider, red above it.

    Three devices at 3, 8, and 15 percent against a red threshold of
    10 paint one bar of each color, and the file says where the
    threshold is set, which was ruled into the footer.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    for key, name, pct in (
        ("g", "Green Device", 3.0),
        ("y", "Yellow Device", 8.0),
        ("r", "Red Device", 15.0),
    ):
        device, _ = register_device(hass, key, name)
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [pct]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    charts = html.index("class='charts'")
    green = html.index("Green Device", charts)
    assert "#1D9E75" in html[green : green + 400]
    yellow = html.index("Yellow Device", charts)
    assert "#EDA100" in html[yellow : yellow + 400]
    red = html.index("Red Device", charts)
    assert "#D03B3B" in html[red : red + 400]
    assert "Red Threshold slider" in html
    assert "configuration screen" in html


async def test_every_red_device_is_an_anomaly(hass: HomeAssistant):
    """Red is the cut (ruled 2026-08-02, revised from red plus five).

    A device over the threshold appears in the anomaly table with its
    streak of consecutive days over red, and a device under it does
    not.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    hot, _ = register_device(hass, "an1", "Anomalous Device")
    coord.data[DATA_DEVICES][hot.id][DEV_SIGNAL_DWELL_DAILY] = [
        2.0,
        12.0,
        14.0,
        13.0,
    ]
    calm, _ = register_device(hass, "an2", "Calm Device")
    coord.data[DATA_DEVICES][calm.id][DEV_SIGNAL_DWELL_DAILY] = [8.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    anomaly_section = html[html.index("Anomalies") : html.index(
        "Yesterday"
    )]
    assert "Anomalous Device" in anomaly_section
    assert "3 day(s)" in anomaly_section
    assert "Calm Device" not in anomaly_section
    assert "Calm Device" in html


async def test_a_quiet_fleet_writes_no_anomaly_section(
    hass: HomeAssistant,
):
    """The section exists only when there is something to say."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "q1", "Quiet Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [1.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    assert "Anomalies" not in html
    assert "Quiet Device" in html


async def test_the_brief_points_at_the_chart_only_with_anomalies(
    hass: HomeAssistant,
):
    """One line, only on mornings it is true."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "b1", "Anomalous Device")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DWELL_DAILY] = [20.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    brief = _brief_text(hass)
    assert "Signal dwell anomalies" in brief
    assert "Anomalous Device" in brief

    record[DEV_SIGNAL_DWELL_DAILY] = [1.0]
    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert "Signal dwell anomalies" not in _brief_text(hass)


async def test_the_mean_column_reads_dash_until_a_day_rolls(
    hass: HomeAssistant,
):
    """The telemetry cell is honest about an empty series."""
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "m1", "Mean Device")
    record = coord.data[DATA_DEVICES][device.id]

    assert coord._format_signal_mean_cell(record) == "-"
    for value in (100.0, 120.0, 110.0):
        coord._feed_signal(record, value, 1000.0)
    coord._roll_signal_stats(record)
    assert coord._format_signal_mean_cell(record) == "110\u00b18.16"

async def test_the_anomaly_row_carries_type_trend_and_room(
    hass: HomeAssistant,
):
    """The additions ruled 2026-08-02, asserted on the file.

    The floor carries its type tag, because a table mixing 176 and
    -68 is unreadable without one; the prior day and its arrow say
    which way the link is moving; and the first day before any mean
    has rolled reads "from tonight" rather than a question mark that
    looks like a lookup failure.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "tt1", "Trending Device")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DWELL_DAILY] = [8.0, 14.0]
    record["signal_daily_min"] = [100.0] * 14
    falling, _ = register_device(hass, "tt2", "Falling Device")
    coord.data[DATA_DEVICES][falling.id][DEV_SIGNAL_DWELL_DAILY] = [
        14.0,
        12.0,
    ]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)
    section = html[html.index("Anomalies") : html.index("Yesterday")]

    assert "LQI" in section
    assert "8.0% \u2191" in section
    assert "14.0% \u2193" in section
    assert "from tonight" in section
    assert "Prior Day" in section


async def test_the_chart_label_carries_the_room(hass: HomeAssistant):
    """A bar reads name and area, so room clustering shows in the
    chart itself rather than only in the anomaly table."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "rm1", "Roomed Device")
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    area = ar.async_get(hass).async_get_or_create("Boiler Room")
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [3.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    assert "Roomed Device (Boiler Room)" in html


async def test_the_bars_are_thin(hass: HomeAssistant):
    """15px per device (ruled 2026-08-02), pinned so a padding sweep
    cannot quietly re-inflate the page."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "th1", "Thin Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [3.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    assert "height='12'" in html
    assert "height='22'" not in html
    assert "charts" in html

async def test_a_globally_excluded_device_is_not_charted(
    hass: HomeAssistant,
):
    """Both exclusion ladders apply to the chart and its anomalies.

    Found live on 2026-08-02: two devices excluded globally by
    integration were charted, one as an anomaly. The global ladder
    suppresses judgment and reporting everywhere, and this page is
    reporting.
    """
    from custom_components.device_sentinel.const import (
        CONF_EXCLUDED_INTEGRATIONS,
    )

    coord = await setup_coordinator(
        hass,
        {
            CONF_SIGNAL_RED: 10,
            CONF_EXCLUDED_INTEGRATIONS: ["test"],
        },
    )
    device, _ = register_device(hass, "gx1", "Ghost Tablet")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [20.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    assert "Ghost Tablet" not in html
