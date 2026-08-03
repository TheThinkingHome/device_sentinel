# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_signal_stats.py, Version: 0.10.19 (2026-08-03)

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
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
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
