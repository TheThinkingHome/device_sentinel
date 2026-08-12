# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_stats.py, Version: 0.12.19 (2026-08-12)

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

import glob
import os
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CLOCK_FIELDS,
    CONF_SIGNAL_ANOMALY_TRIM,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_MARGIN,
    CONF_SIGNAL_RED,
    DATA_DEVICES,
    DATA_SIGNAL_STRESS,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_LINE,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_VALUE,
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
    REPORT_SIGNAL_DWELL,
    REPORT_WWW_DIR,
    SIGNAL_RAIL_LQI,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import register_device, setup_coordinator, setup_entry


def _brief_text(hass: HomeAssistant) -> str:
    written = sorted(
        glob.glob(
            hass.config.path(REPORT_WWW_DIR, "daily_brief_2*.html")
        )
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

    for value in (100.0, 120.0, 110.0):
        coord._feed_signal(record, value, 1000.0)
    coord._feed_signal(record, float(SIGNAL_RAIL_LQI), 1000.0)

    assert record[DEV_SIGNAL_MEAN_RUN] == pytest.approx(110.0)
    # M2 is the sum of squared distances from the mean: 100+100+0.
    assert record[DEV_SIGNAL_M2] == pytest.approx(200.0)
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

    coord._roll_signal_stats(record, 86400.0)

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

    # Sliced to the charts block rather than to the word Yesterday,
    # which the headings stopped saying when they gained their dates
    # (ruling #190).
    anomaly_section = html[
        html.index("Anomalies") : html.index("<div class='charts'>")
    ]
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
    coord._roll_signal_stats(record, 86400.0)
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
    section = html[
        html.index("Anomalies") : html.index("<div class='charts'>")
    ]

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
    """17px per device with 12px labels (revised 2026-08-02), pinned
    so a sweep can neither re-inflate the page nor shrink the text
    back to unreadable."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "th1", "Thin Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [3.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    html = _read(hass)

    assert "height='13'" in html
    assert "height='22'" not in html
    assert "height='12'" not in html
    assert "font-size='12'" in html
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

async def test_the_brief_is_also_a_page_under_www(
    hass: HomeAssistant,
):
    """Rung one of the www ladder (#178): daily_brief.html.

    Rendered from the Markdown text itself so the two briefs cannot
    drift: the heading, the problem table, and the anomaly pointer
    all arrive as HTML, the pointer as a live link, and the page
    carries the same dark-mode stylesheet approach as the chart.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "bh1", "Anomalous Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [20.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")

    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
    )
    with open(path, encoding="utf-8") as handle:
        page = handle.read()

    assert "<h1>Device Sentinel Daily Brief</h1>" in page
    assert "<h2>In Short</h2>" in page
    assert "<table>" in page and "<th>DEVICE</th>" in page
    # The href is absolute where Home Assistant knows its URL, so
    # the assertion pins the path and the anchor rather than a host.
    assert "/local/device_sentinel/signal_dwell.html'>" in page
    assert "the signal dwell chart</a>" in page
    assert "prefers-color-scheme: dark" in page
    assert "Anomalous Device" in page


async def test_the_html_brief_tracks_the_markdown(
    hass: HomeAssistant,
):
    """The page is the current picture: a second write replaces it,
    and its content is the newest Markdown brief's content."""
    import glob as _glob

    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
    )
    with open(path, encoding="utf-8") as handle:
        page = handle.read()
    dated = sorted(
        _glob.glob(
            hass.config.path(REPORT_WWW_DIR, "daily_brief_2*.html")
        )
    )
    with open(dated[-1], encoding="utf-8") as handle:
        dated_page = handle.read()
    # The dated file and the current file are the same document.
    assert dated_page == page

async def test_the_markdown_brief_is_retired(hass: HomeAssistant):
    """0.10.18: no new .md brief is written; the dated record is
    HTML under www, named as the Markdown files were, and trimmed."""
    import glob as _glob

    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert not _glob.glob(
        hass.config.path("device_sentinel", "daily_brief_*.md")
    )
    assert _glob.glob(
        hass.config.path(REPORT_WWW_DIR, "daily_brief_2*.html")
    )


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
    now takes a closing write, the text that write returned, and the
    dated file that write produced.
    """
    coord = await setup_coordinator(hass)
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    assert text is not None

    payload = coord._brief_payload("notify.mail", text)
    start, _end = coord._brief_close_bounds()
    closed = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.html")
    with open(
        os.path.join(hass.config.path(REPORT_WWW_DIR), closed),
        encoding="utf-8",
    ) as handle:
        page = handle.read()
    assert payload["data"]["html"] == page
    assert payload["message"] == text

async def test_every_www_file_is_dated_and_trimmed(
    hass: HomeAssistant,
):
    """One rule for the folder (ruled 2026-08-02): dated files as
    the record, an undated current file for the stable URL, and the
    brief's fourteen-day trim applied to every prefix alike."""
    import glob as _glob

    from custom_components.device_sentinel.const import BRIEF_KEEP_DAYS

    directory = hass.config.path(REPORT_WWW_DIR)
    os.makedirs(directory, exist_ok=True)
    for day in range(1, BRIEF_KEEP_DAYS + 5):
        name = f"signal_dwell_2026-06-{day:02d}.html"
        with open(
            os.path.join(directory, name), "w", encoding="utf-8"
        ) as handle:
            handle.write("stale")

    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "dt1", "Dated Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [3.0]
    await hass.async_add_executor_job(coord._write_reports, "manual")

    dated = sorted(
        _glob.glob(os.path.join(directory, "signal_dwell_2*.html"))
    )
    assert len(dated) == BRIEF_KEEP_DAYS
    # Today's dated file and the current file are the same document.
    with open(dated[-1], encoding="utf-8") as handle:
        newest = handle.read()
    with open(
        os.path.join(directory, "signal_dwell.html"), encoding="utf-8"
    ) as handle:
        current = handle.read()
    assert newest == current
    assert "Dated Device" in current

async def test_the_link_is_external_then_internal_never_relative(
    hass: HomeAssistant,
):
    """#183, amending #181: the link is never left relative.

    #181 preferred the external URL and let the link stay relative
    where none was configured, on the reasoning that a relative
    address still works for a browser already facing the instance.
    It does not work in a mail client, which has no host to resolve
    it against, so the relative case was a dead link in the one
    place the rule was written for. The order is now external, then
    internal, then nothing. This environment configures no external
    URL, so the rendered link must carry the internal host.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "ex1", "Anomalous Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [20.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
    )
    with open(path, encoding="utf-8") as handle:
        page = handle.read()

    assert "href='/local/device_sentinel/signal_dwell.html'" not in page
    assert (
        "href='http://10.10.10.10:8123"
        "/local/device_sentinel/signal_dwell.html'" in page
    )


async def test_the_chart_names_the_days_it_covers(
    hass: HomeAssistant,
):
    """Ruling #190, found by reading the live pages on 2026-08-03.

    Every heading said Yesterday, or Last 7 Days, with no date
    anywhere on the page, so a chart opened later could not say
    which days it was about.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "lbl1", "Labelled Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [20.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        os.path.join(hass.config.path(REPORT_WWW_DIR), REPORT_SIGNAL_DWELL),
        encoding="utf-8",
    ) as handle:
        page = handle.read()

    covered = dt_util.now().date() - timedelta(days=1)
    day = covered.strftime("%b %-d")
    week = (covered - timedelta(days=6)).strftime("%b %-d")
    month = (covered - timedelta(days=29)).strftime("%b %-d")

    assert f"<h2>{day}</h2>" in page
    assert f"<h2>7 Days, {week} to {day} (Mean)</h2>" in page
    assert f"<h2>30 Days, {month} to {day} (Mean)</h2>" in page
    # The bare words are gone, so nothing on the page is undated.
    assert "<h2>Yesterday</h2>" not in page
    assert "threshold yesterday" not in page
    assert f"threshold on {day}" in page


async def test_the_dated_chart_is_named_for_the_day_it_covers(
    hass: HomeAssistant,
):
    """The fault as found (ruling #190).

    Dwell rolls at midnight, so a chart written on the 3rd carries
    the 2nd's figures. It was named for the write, so the file called
    signal_dwell_2026-08-02 held the 1st, while the brief's dated
    file for the same date held the 2nd. Two files, one date, two
    days.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "dt2", "Dated Device")
    coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DWELL_DAILY] = [4.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")

    directory = hass.config.path(REPORT_WWW_DIR)
    covered = dt_util.now().date() - timedelta(days=1)
    assert os.path.isfile(
        os.path.join(
            directory,
            f"signal_dwell_{covered.strftime('%Y-%m-%d')}.html",
        )
    )
    # No dated chart for today, because today's dwell has not closed.
    today = dt_util.now().date().strftime("%Y-%m-%d")
    assert not os.path.isfile(
        os.path.join(directory, f"signal_dwell_{today}.html")
    )


# ------------------------------------ the good-state ceiling (#193)

def _seed_signal(coord, device_id, mins, mean, sd):
    """Give a device a signal history and yesterday's statistics."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_SIGNAL_DAILY_MIN] = list(mins)
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
    # 240 + 5% = 252.0 unbounded. The ceiling is the mean less the
    # larger of half a deviation (2.205) and the LQI clearance of 8
    # (ruling #244): 246.21 - 8 = 238.21. Before the clearance the
    # ceiling sat 2.2 points under the mean, inside the readings a
    # low-variance device makes every hour.
    assert line == pytest.approx(238.21, abs=0.01)
    assert line < 246.21
    assert coord._line_is_bounded(record) is True


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
        hass.config_entries.async_update_entry(
            coord.entry,
            options={**coord.entry.options, CONF_SIGNAL_MARGIN: pct},
        )
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
    record[DEV_SIGNAL_DAILY_MIN] = [240.0] * 14
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

async def test_the_trim_is_one_reading_per_full_week(
    hass: HomeAssistant,
):
    """Ruling #196. A count that does not grow with the window
    thins as the window does: two rungs discarded fourteen percent
    of a fortnight and would discard nine percent of a month,
    lowering every floor on the fleet as a side effect of a change
    meant to be about stability.
    """
    coord = await setup_coordinator(hass)
    assert coord._signal_effective_k(6) == 0
    assert coord._signal_effective_k(7) == 1
    assert coord._signal_effective_k(13) == 1
    assert coord._signal_effective_k(14) == 2
    assert coord._signal_effective_k(21) == 3
    assert coord._signal_effective_k(28) == 4
    # The window caps at thirty, so the ladder caps with it.
    assert coord._signal_effective_k(30) == 4


async def test_the_slider_still_shifts_the_rung(
    hass: HomeAssistant,
):
    """Anomaly Trim keeps working on top of the ladder, and the
    clamp still leaves one reading to be the floor."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_ANOMALY_TRIM: 1})
    assert coord._signal_effective_k(28) == 5
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_SIGNAL_ANOMALY_TRIM: -2},
    )
    assert coord._signal_effective_k(28) == 2
    assert coord._signal_effective_k(1) == 0


async def test_the_telemetry_report_shows_the_floor_moving(
    hass: HomeAssistant,
):
    """The floor is what dwell is measured against, so a floor that
    moves makes dwell unreadable across days. On the reference fleet
    forty-three of seventy-nine were moving a point a week or more
    and one was moving thirty-four (ruling #196).
    """
    coord = await setup_coordinator(hass)
    sinking, _ = register_device(hass, "fd1", "Sinking Floor")
    steady, _ = register_device(hass, "fd2", "Steady Floor")
    # A floor walking down two points a day.
    coord.data[DATA_DEVICES][sinking.id][DEV_SIGNAL_DAILY_MIN] = [
        float(120 - n * 2) for n in range(20)
    ]
    coord.data[DATA_DEVICES][steady.id][DEV_SIGNAL_DAILY_MIN] = [
        100.0
    ] * 20

    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(
        hass.config.path("device_sentinel/device_telemetry.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()

    assert "FLOOR/WK" in text
    sinking_row = next(
        line for line in text.splitlines() if "Sinking Floor" in line
    )
    steady_row = next(
        line for line in text.splitlines() if "Steady Floor" in line
    )
    assert "/wk" in sinking_row
    # The series falls two points a day, so its floor walks down
    # fourteen a week, and the cell carries the current floor with it.
    assert "86 -14/wk" in sinking_row
    assert "flat" in steady_row
    assert "/wk" not in steady_row


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
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    weak, _ = register_device(hass, "sp1", "Weak Link")
    fine, _ = register_device(hass, "sp2", "Fine Link")
    coord.data[DATA_DEVICES][weak.id][DEV_SIGNAL_DWELL_DAILY] = [4.0, 35.0]
    coord.data[DATA_DEVICES][fine.id][DEV_SIGNAL_DWELL_DAILY] = [0.0, 2.0]

    rows = coord.signal_weak_list
    assert [row["name"] for row in rows] == ["Weak Link"]
    assert coord.signal_weak_count == 1
    assert rows[0]["device_id"] == weak.id
    assert rows[0]["dwell"] == 35.0

    # And it stays off the list that notifies, which is the whole
    # point of the split (rulings #59 and #210).
    assert coord.signal_problem_list == []
    assert coord.signal_problem_count == 0
    assert not any(
        row["device_id"] == weak.id for row in coord._current_problems()
    )


async def test_a_signal_excluded_device_is_not_counted_low(
    hass: HomeAssistant,
):
    """Exclusion suppresses judgment, so it suppresses this too."""
    coord = await setup_coordinator(
        hass, {CONF_SIGNAL_RED: 10, CONF_SIGNAL_EXCLUDED_DEVICES: []}
    )
    weak, _ = register_device(hass, "sp3", "Excluded Link")
    coord.data[DATA_DEVICES][weak.id][DEV_SIGNAL_DWELL_DAILY] = [4.0, 35.0]
    assert coord.signal_weak_count == 1

    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            CONF_SIGNAL_EXCLUDED_DEVICES: [weak.id],
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
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "sp4", "Recovering Link")
    record = coord.data[DATA_DEVICES][device.id]

    record[DEV_SIGNAL_DWELL_DAILY] = [4.0, 35.0]
    assert coord.signal_weak_count == 1

    record[DEV_SIGNAL_DWELL_DAILY] = [4.0, 35.0, 2.0]
    assert coord.signal_weak_count == 0


async def test_a_railed_device_is_not_counted_twice(
    hass: HomeAssistant,
):
    """A rail dwells below its own line by construction, so without
    the guard a stuck device would appear in both counts and a person
    adding them would see one fault as two.
    """
    coord = await setup_coordinator(hass, {CONF_SIGNAL_RED: 10})
    device, _ = register_device(hass, "sp5", "Railed Link")
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_MIN] = [255.0] * 4
    record[DEV_SIGNAL_DWELL_DAILY] = [4.0, 35.0]

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
    """Ruling #245: the day folds three more series beside the mean.

    The count says how much weight the day's statistics deserve, the
    line says what the day's dwell was measured against (read before
    the fold moves the ceiling), and the rail count says why a day's
    real statistics are thin. All three trim on the same retention
    as the series beside them.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "gs7", "Recorded Link")
    record = _seed_signal(
        coord, device.id, [100.0] * 14, 140.0, 20.0
    )
    line_before = coord._danger_line(record)
    for value in (140.0, 144.0, 255.0, 136.0, 255.0):
        coord._feed_signal(record, value, 1000.0)

    coord._roll_signal_stats(record, 86400.0)

    assert record[DEV_SIGNAL_DAILY_COUNT][-1] == 3
    assert record[DEV_SIGNAL_DAILY_RAIL][-1] == 2
    assert record[DEV_SIGNAL_DAILY_LINE][-1] == pytest.approx(
        line_before, abs=0.01
    )
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
    for value in (140.0, 136.0):
        coord._feed_signal(record, value, 1000.0)

    snapshot = coord._signal_snapshot(record)
    assert snapshot[EP_SIG_VALUE] == 136.0
    assert snapshot[EP_SIG_MEAN] == pytest.approx(138.0, abs=0.01)
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


async def test_welford_migration_is_exact(hass: HomeAssistant):
    """A record carrying a pre-#254 partial day (naive sum and sum of
    squares) continues under Welford with the identical mean and
    deviation: the migration is arithmetic, not approximation."""
    coord = await setup_coordinator(hass)
    values = [140.0, 136.0, 148.0, 132.0]
    legacy = {
        DEV_SIGNAL_COUNT: len(values),
        DEV_SIGNAL_SUM: sum(values),
        DEV_SIGNAL_SUM_SQ: sum(v * v for v in values),
        DEV_SIGNAL_VALUE: values[-1],
    }
    coord._feed_signal(legacy, 144.0, 1000.0)
    everything = values + [144.0]
    exact_mean = sum(everything) / len(everything)
    exact_var = sum((v - exact_mean) ** 2 for v in everything) / len(everything)
    assert legacy[DEV_SIGNAL_MEAN_RUN] == pytest.approx(exact_mean)
    assert (legacy[DEV_SIGNAL_M2] / legacy[DEV_SIGNAL_COUNT]) == pytest.approx(
        exact_var
    )


async def test_the_fold_records_p5_and_p50_and_sheds_legacy_fields(
    hass: HomeAssistant
):
    """Midnight appends the day's percentiles beside mean and sd,
    resets the trackers, and removes the naive accumulators from a
    migrated record so storage sheds them at the first fold."""
    coord = await setup_coordinator(hass)
    record = {DEV_SIGNAL_SUM: 1.0, DEV_SIGNAL_SUM_SQ: 1.0}
    coord._feed_signal(record, 120.0, 0.0)
    coord._feed_signal(record, 120.0, 3600.0)
    coord._roll_signal_stats(record, 7200.0)
    assert record[DEV_SIGNAL_DAILY_P5][-1] == pytest.approx(120.0, abs=1.0)
    assert record[DEV_SIGNAL_DAILY_P50][-1] == pytest.approx(120.0, abs=1.0)
    assert DEV_SIGNAL_SUM not in record
    assert DEV_SIGNAL_SUM_SQ not in record
    assert record[DEV_SIGNAL_P5_STATE] is None


