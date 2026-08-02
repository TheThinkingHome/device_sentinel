# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_reports.py, Version: 0.10.15 (2026-08-02)

"""The diagnostic files: telemetry and classification.

Device Sentinel writes two diagnostic reports beside the daily brief:
device_telemetry.md, one row per device with its learned rhythm and
series, and classification.md, which sorts every registry device into
watched or set aside. Both are written at setup and rewritten at local
midnight when the daily epoch rolls, so they carry each device's fresh
daily maximum. The telemetry report marks its SIGNAL LOWS cell (bold
floor, struck trim, italic rail), carries a battery column and a
readable Written header, and holds a Reporting Devices section that
groups every standing fault by family. The STATUS cell reads one
grammar (Reported or Excluded with reasons), the Regenerate Reports
button judges then rewrites, and the whole learned state is available
in the diagnostics download. A third file, silence_episodes.md, records
each time a device passed its own basis: a row opens halfway from rhythm
to freeze line, closes as resumed when the device speaks for itself or
is stamped by an intervention when a reboot truncates it, with a lag
column that separates a wedge from a device that was merely quiet, and
a filter that keeps trivial fast-device silences and freeze-excluded
devices out of the file. This file holds the diagnostic reports, their
surface, and the silence episodes; the daily brief, which follows its
own window rather than the calendar day, has its own file.
"""

import os
from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_DEVICES,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_SIGNAL_ANOMALY_TRIM,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_MARGIN,
    DATA_EPISODES,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    EPISODE_ENDED_REBOOT,
    EPISODE_ENDED_RESUMED,
    EPISODE_OPEN_SHARE,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_DELTA_HIGH_HR_MAX,
    FREEZE_DELTA_HIGH_HR_MIN,
)
from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator,
    _new_device_record,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_coordinator, setup_entry

OPEN_TAG = "[\u25cb open]"
ACKED_TAG = "[\u2713 acknowledged]"
REMOVED_TAG = "[\u2717 removed from list]"


def _register(hass, uid, name, battery=False):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent_reg = er.async_get(hass)
    plain = ent_reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    if battery:
        ent_reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, plain.entity_id


def _telemetry_row(hass, name):
    text = open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md")
    ).read()
    return next(line for line in text.splitlines() if name in line)


def _freeze(coord, device_id, since=1_000_000.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


def _battery_low(coord, device_id, level=14.0,
                 since="2026-07-20T15:02:00+00:00"):
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_SINCE] = since


async def test_reports_written_at_setup_and_midnight(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "rpt")},
        name="Report Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rpt", device_id=device.id, config_entry=source
    )
    svc = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "svc")},
        name="Service Thing",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    assert svc

    await setup_entry(hass, {CONF_SIGNAL_MARGIN: 0})

    tele = hass.config.path("device_sentinel/diagnostics/device_telemetry.md")
    clas = hass.config.path("device_sentinel/diagnostics/classification.md")

    # Written at setup.
    assert os.path.isfile(tele)
    assert os.path.isfile(clas)
    tele_text = open(tele).read()
    clas_text = open(clas).read()
    assert "Report Device" in tele_text
    assert "Tunables:" in tele_text
    assert "trimmed maximum" in tele_text
    assert "| COPIES |" in clas_text
    assert "Report Device" in clas_text
    assert "Service Thing" in clas_text
    assert "SET ASIDE" in clas_text
    assert "WATCHED" in clas_text

    # Rewritten at midnight, carrying the new maxima.
    os.remove(tele)
    os.remove(clas)
    nxt = (dt_util.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    freezer.move_to(nxt + timedelta(seconds=1))
    async_fire_time_changed(hass)
    # Home Assistant runs time-change listeners as background tasks
    # (async_run_hass_job(..., background=True) in _TrackUTCTimeChange),
    # and async_block_till_done skips background tasks by default. So
    # the plain call returned while the rollover was still writing its
    # report, and the assert below raced the file: about one run in ten
    # lost. Waiting for background tasks is what makes the midnight
    # path deterministic here.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert os.path.isfile(tele)
    assert os.path.isfile(clas)


# ==================================================================
# The diagnostics download.
# ==================================================================

async def test_diagnostics_carry_the_learned_state(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "diag")},
        name="Diag Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "diag", device_id=device.id, config_entry=source
    )
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.mobile_app_private"], CONF_SIGNAL_MARGIN: 0})
    coordinator = entry.runtime_data

    # A seven-day history with one spike: the trim must show through.
    coordinator.data["devices"][device.id][DEV_DAILY_MAX] = [
        500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0,
    ]

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["version"]
    assert result["storage"]["setup_count"] >= 1
    assert result["tunables"]["taint_floor_minutes"] == 10
    assert result["tunables"]["taint_share_pct"] == 10
    assert result["tunables"]["trim_top_k"] == 1
    assert result["classification"]["watched"] == 1
    assert result["battery"]["low_count"] == 0
    assert result["todo_items"] == []

    entry_device = result["devices"][device.id]
    assert entry_device["name"] == "Diag Device"
    assert entry_device["integration"] == "test"
    assert entry_device["clock_source"] == "recorded"
    assert entry_device["excluded"] is None
    assert entry_device["window_basis"] == 600.0  # spike set aside
    assert entry_device["set_aside_indices"] == [4]

    # Notification targets are the user's own device names: redacted.
    assert (
        result["entry_options"][CONF_HIGH_PRIORITY_TARGETS] == "**REDACTED**"
    )


async def test_diagnostics_report_exclusions(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "diagx")},
        name="Excluded Diag Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "diagx", device_id=device.id, config_entry=source
    )
    entry = await setup_entry(hass, {CONF_EXCLUDED_DEVICES: [device.id], CONF_SIGNAL_MARGIN: 0})

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["devices"][device.id]["excluded"] == "device"
    assert result["classification"]["excluded_devices"] == {
        device.id: "device"
    }


# ==================================================================
# The marked report columns and the three buttons.
# ==================================================================

async def _marks_coordinator(hass, options=None):
    # These tests read the floor marks in the report, which were
    # written when the floor was the line, so the margin is pinned off
    # and they go on testing the floor. The margin has its own file.
    options = {CONF_SIGNAL_MARGIN: 0, **(options or {})}
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "marks")},
        name="Marks Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "marks",
        suggested_object_id="marks_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator(hass, options)
    return coord, device.id


async def test_signal_lows_shows_all_three_marks(hass: HomeAssistant):
    """One cell, all three states: the floor bold, the trimmed low
    struck, the rail value italic. Eight readings, one a rail (255)
    and one an anomaly (40); at a week the ladder trims the single
    lowest non-rail value, so 40 is struck and 87 is the floor."""
    coord, device_id = await _marks_coordinator(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        88.0, 90.0, 255.0, 40.0, 92.0, 89.0, 91.0, 87.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    assert "**87** 91 89 92 ~~40~~ *255* 90 88" in row


async def test_battery_column_summarises_rather_than_listing(
    hass: HomeAssistant,
):
    """Ninety levels will not fit in a cell, so the column carries the
    level and the changes the history supports (0.8.6). Five days is
    short of a week, so neither change appears yet, and the level is
    bold because it is at or below the threshold."""
    coord, device_id = await _marks_coordinator(hass)
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_DAILY] = [95.0, 60.0, 22.0, 18.0, 15.0]
    record[DEV_BATTERY_VALUE] = 15.0
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    assert "**15%**" in row
    assert "/wk" not in row and "/mo" not in row


async def test_battery_column_adds_each_change_when_earned(
    hass: HomeAssistant,
):
    """A fresh install shows a bare level, gains the weekly change
    after a week and the monthly one after a month."""
    coord, device_id = await _marks_coordinator(hass)
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_DAILY] = [90.0 - n * 0.5 for n in range(8)]
    record[DEV_BATTERY_VALUE] = record[DEV_BATTERY_DAILY][-1]
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    assert "-3.5/wk" in row
    assert "/mo" not in row

    record[DEV_BATTERY_DAILY] = [90.0 - n * 0.5 for n in range(31)]
    record[DEV_BATTERY_VALUE] = record[DEV_BATTERY_DAILY][-1]
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    assert "-3.5/wk" in row and "-15/mo" in row


async def test_a_reading_outside_the_scale_says_so(
    hass: HomeAssistant,
):
    """LUX Outdoors reports around 198. That is recorded like any
    other value (#128) and classified here, at rendering."""
    coord, device_id = await _marks_coordinator(hass)
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_DAILY] = [198.0, 194.0, 198.0]
    record[DEV_BATTERY_VALUE] = 198.0
    await hass.async_add_executor_job(coord._write_reports)
    assert "198 out of range" in _telemetry_row(hass, "Marks Device")


async def test_headers_show_k_and_threshold(hass: HomeAssistant):
    """The column headers carry the tunables: GAPS its fixed trim k,
    SIGNAL the sensitivity as a word, BAT LEVEL the live threshold."""
    coord, _ = await _marks_coordinator(hass, {CONF_SIGNAL_ANOMALY_TRIM: 1})
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md")
    ).read()
    header = next(line for line in text.splitlines() if "DEVICE (INTEGRATION) | STATUS" in line)
    # Slider at +1 renders as the word Deep, not a number.
    assert "SIGNAL (Deep)" in header
    assert "GAPS (K=" in header
    assert "BAT LEVEL (floor 20%)" in header
    # The retired columns are gone.
    assert "LINE" not in header
    assert "FAMILY" not in header
    assert "SIG MIN" not in header
    assert "SIG FROZEN" not in header

    # Every data row must have exactly as many cells as the header,
    # nine since 0.10.15 added MEAN±SD, so a dropped column can
    # never leave the rows misaligned.
    def _cells(line: str) -> int:
        return len([c for c in line.strip().strip("|").split("|")])

    header_cells = _cells(header)
    assert header_cells == 9, header_cells
    data_rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ")
        and "DEVICE (INTEGRATION) | STATUS" not in line
        and not line.startswith("|---")
    ]
    for line in data_rows:
        assert _cells(line) == header_cells, line


async def test_three_enable_buttons_exist_and_press(hass: HomeAssistant):
    """The enable assist is three buttons now, one per diagnostic
    kind, each pressable without error."""
    await _marks_coordinator(hass)
    for entity_id in (
        "button.device_sentinel_enable_signals",
        "button.device_sentinel_enable_last_seen",
        "button.device_sentinel_enable_battery",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
        await hass.services.async_call(
            "button", "press",
            {"entity_id": entity_id},
            blocking=True,
        )


# ==================================================================
# The regenerate-reports button and the STATUS wording.
# ==================================================================

def _plain_device(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )


async def test_status_grammar(hass: HomeAssistant):
    """Reported when nothing excludes; Excluded (GLB) alone for a
    global exclude; Excluded (BAT, SIG, FRZ) in column order when
    sections combine."""
    d = _plain_device(hass, "st", "Status Device")
    entry = await setup_entry(hass, {CONF_SIGNAL_MARGIN: 0})
    coord = entry.runtime_data
    assert coord._device_status(d.id) == "Reported"

    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_BATTERY_EXCLUDED_DEVICES: [d.id],
            CONF_SIGNAL_EXCLUDED_DEVICES: [d.id],
            CONF_FREEZE_EXCLUDED_DEVICES: [d.id],
        },
    )
    assert coord._device_status(d.id) == "Excluded (BAT, SIG, FRZ)"

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_EXCLUDED_DEVICES: [d.id]}
    )
    coord._excluded_devices[d.id] = "device"
    assert coord._device_status(d.id) == "Excluded (GLB)"


def test_readable_timestamp_format():
    """The report time is a readable local phrase, not an ISO
    string."""
    import datetime

    when = datetime.datetime(2026, 7, 21, 7, 19, 5)
    out = DeviceSentinelCoordinator._format_report_time(when)
    assert out == "July 21, 2026 at 7:19 AM"
    # Afternoon crosses to PM with a 12-hour clock.
    pm = datetime.datetime(2026, 12, 3, 15, 5, 0)
    assert DeviceSentinelCoordinator._format_report_time(pm) == (
        "December 3, 2026 at 3:05 PM"
    )
    # Midnight and noon read 12, not 0.
    midnight = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert "12:00 AM" in DeviceSentinelCoordinator._format_report_time(
        midnight
    )


async def test_regenerate_judges_then_writes(hass: HomeAssistant):
    """The regenerate action judges every device, then writes a fresh
    report that shows a device already down."""
    d = _plain_device(hass, "ghost", "Ghost Device")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    record = _new_device_record("2026-07-08T00:00:00+00:00", None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    coord.data["devices"][d.id] = record

    result = await coord.async_regenerate_reports()
    assert result == {"regenerated": 2}

    text = open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md")
    ).read()
    # Judgment ran, so the ghost is flagged and shows in the report.
    assert "Reporting Devices (1)" in text
    assert "As of" in text
    # STATUS column carries the new grammar.
    assert "Reported" in text


async def test_regenerate_button_present_and_presses(hass: HomeAssistant):
    """The Regenerate Reports button exists on the Device Sentinel
    device and its press runs without error."""
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    reg = er.async_get(hass)
    buttons = [
        e
        for e in reg.entities.values()
        if e.platform == "device_sentinel" and e.domain == "button"
    ]
    # regenerate_reports gives a unique_id ending in "reports".
    assert any("reports" in e.unique_id for e in buttons)
    # Pressing it does not raise.
    await coord.async_regenerate_reports()


# ==================================================================
# The report Written header is a readable local time.
# ==================================================================

async def test_written_header_is_readable_on_both_reports(
    hass: HomeAssistant,
):
    """Both report headers read a readable local time with the trigger
    tag, not a raw ISO timestamp."""
    _plain_device(hass, "wh", "Written Device")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    await hass.async_add_executor_job(coord._write_reports, "manual")
    for name in ("device_telemetry.md", "classification.md"):
        text = open(
            hass.config.path(f"device_sentinel/diagnostics/{name}")
        ).read()
        written = next(
            line
            for line in text.splitlines()
            if line.startswith("Written")
        )
        assert "(manual)" in written
        assert " at " in written
        # No ISO 'T' date-time separator in the timestamp portion.
        assert "T" not in written.split("(")[0]


# ==================================================================
# The Reporting Devices section and the STATUS revert.
# ==================================================================

async def test_all_three_families_grouped_and_sorted(
    hass: HomeAssistant,
):
    """Freeze then battery, alphabetical inside each group, the
    header counting distinct devices."""
    d1, e1 = _register(hass, "r1", "Zebra Frozen")
    d2, e2 = _register(hass, "r2", "Apple Frozen")
    d3, e3 = _register(hass, "r3", "Mango Battery", battery=True)
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    for eid in (e1, e2, e3):
        hass.states.async_set(eid, "on")
    _freeze(coord, d1.id)
    _freeze(coord, d2.id)
    _battery_low(coord, d3.id)
    coord._sync_problem_list()

    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (3)" in text
    assert text.index("### Freeze") < text.index("### Battery")
    assert text.index("Apple Frozen") < text.index("Zebra Frozen")
    assert "(14%)" in text
    assert text.count(OPEN_TAG) == 3


async def test_acknowledged_item_still_shows_tagged(
    hass: HomeAssistant,
):
    """The whole reason for the section: the checkbox silences the
    phone, never the diagnostics."""
    device, eid = _register(hass, "a1", "Acked Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")

    text = "\n".join(coord._reporting_lines())
    assert "Acked Sensor" in text
    assert ACKED_TAG in text


async def test_hand_deleted_item_shows_removed_tag(
    hass: HomeAssistant,
):
    """Still reporting, removed from the list by a human: the fault
    stays visible here with the removed tag until the sync re-adds."""
    device, eid = _register(hass, "x1", "Orphan Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_delete([uid])

    text = "\n".join(coord._reporting_lines())
    assert "Orphan Sensor" in text
    assert REMOVED_TAG in text


async def test_two_family_device_appears_in_both(hass: HomeAssistant):
    """One device, two lines, each family carrying its own age, both
    wearing the device's single todo tag."""
    device, eid = _register(hass, "b1", "Doubled Sensor", battery=True)
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    _battery_low(coord, device.id)
    coord._sync_problem_list()

    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (1)" in text  # distinct devices
    assert text.count("Doubled Sensor") == 2
    assert "### Freeze" in text and "### Battery" in text
    assert text.count(OPEN_TAG) == 2


async def test_empty_section_is_all_clear(hass: HomeAssistant):
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    coord._sync_problem_list()
    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (0)" in text
    assert "low on battery" in text


async def test_status_cell_reverted_to_plain_grammar(
    hass: HomeAssistant,
):
    """The 0.6.1 icon is gone from STATUS: a faulted device reads
    plain Reported there, and the icon lives in Reporting Devices."""
    device, eid = _register(hass, "s1", "Plain Status")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    assert coord._device_status(device.id) == "Reported"


async def test_section_reaches_the_written_report(hass: HomeAssistant):
    device, eid = _register(hass, "w1", "Written Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "diagnostics", "device_telemetry.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "## Reporting Devices (1)" in text
    assert OPEN_TAG in text
    assert "Down devices" not in text


# ==================================================================
# Silence episodes and the widened delta-high range.
# ==================================================================

def _armed_and_silent(coord, device_id, hours_silent):
    """Give a device an hourly rhythm and a silence past its basis.

    Startup grace is closed first: these tests are about a running
    system, and a stamp inside grace is correctly excluded from
    learning, which would mask what the episode columns are proving.
    """
    coord._grace_until = 0.0
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - hours_silent * 3600.0
    )


def _episodes(coord):
    return coord.data[DATA_EPISODES]


def _rhythm(coord, device_id, basis_seconds, silent_seconds):
    coord._grace_until = 0.0
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [basis_seconds] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - silent_seconds
    )


async def test_delta_high_range_widened(hass: HomeAssistant):
    """#102: the asymmetric 2-to-8 range becomes 4 to 12, default 8."""
    assert FREEZE_DELTA_HIGH_HR_MIN == 4
    assert FREEZE_DELTA_HIGH_HR_MAX == 12
    assert DEFAULT_FREEZE_DELTA_HIGH_HR == 8


async def test_quiet_device_never_opens_an_episode(hass: HomeAssistant):
    """The filter that keeps the file readable: a device inside its
    rhythm produces no row."""
    device, entity_id = _register(hass, "q1", "Quiet Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 0.5)  # half its basis
    coord._judge_all_devices()
    assert _episodes(coord) == []


async def test_episode_opens_past_basis_and_resumes(
    hass: HomeAssistant,
):
    """Past its rhythm opens a row; speaking for itself closes it as
    resumed, with the gap learned."""
    device, entity_id = _register(hass, "r1", "Resuming Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    assert len(_episodes(coord)) == 1
    assert _episodes(coord)[0][EP_ENDED] is None
    assert _episodes(coord)[0][EP_NAME] == "Resuming Sensor"

    coord._record_activity(device.id, None, entity_id, "2")
    episode = _episodes(coord)[0]
    assert episode[EP_ENDED] == EPISODE_ENDED_RESUMED
    assert episode[EP_LEARNED] == "yes"
    assert episode[EP_LAG] is None  # nothing to measure against


async def test_reboot_truncates_and_lag_fills_later(
    hass: HomeAssistant, freezer
):
    """A restart stamps the open episode; the lag arrives with the
    device's first genuine report, which is the wedge discriminator."""
    device, entity_id = _register(hass, "i1", "Levered Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 3.0)
    coord._judge_all_devices()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    episode = _episodes(coord)[0]
    assert episode[EP_ENDED] == EPISODE_ENDED_REBOOT
    assert episode[EP_LAG] is None  # still awaiting the resume

    freezer.tick(timedelta(seconds=90))
    coord._record_activity(device.id, None, entity_id, "2")
    episode = _episodes(coord)[0]
    assert 80 <= episode[EP_LAG] <= 100
    assert episode[EP_ENDED] == EPISODE_ENDED_REBOOT  # unchanged


async def test_second_silence_is_a_new_row(hass: HomeAssistant):
    """One row per occurrence, so a nightly wedge reads as a pattern."""
    device, entity_id = _register(hass, "s2", "Repeating Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    coord._record_activity(device.id, None, entity_id, "2")
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    assert len(_episodes(coord)) == 2


async def test_report_written_and_readable(hass: HomeAssistant):
    """The file exists, names the device, and shows the columns."""
    device, entity_id = _register(hass, "we1", "Episode Written Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "diagnostics", "silence_episodes.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "Silence Episodes" in text
    assert "Episode Written Sensor" in text
    assert "| SILENT SINCE | DEVICE |" in text
    assert "open" in text


async def test_empty_report_says_so(hass: HomeAssistant):
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "diagnostics", "silence_episodes.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "No device has been silent past its own rhythm" in text


async def test_episodes_reach_diagnostics(hass: HomeAssistant):
    device, entity_id = _register(hass, "de1", "Episode Diag Sensor")
    entry = await setup_entry(hass, {CONF_SIGNAL_MARGIN: 0})
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "silence_episodes" in diag
    assert diag["silence_episodes"][0][EP_NAME] == "Episode Diag Sensor"


# ==================================================================
# What earns a silence-episode row.
# ==================================================================

async def test_share_is_half(hass: HomeAssistant):
    """#105: a row opens halfway from rhythm to freeze line."""
    assert EPISODE_OPEN_SHARE == 0.5


async def test_fast_device_ignores_a_trivial_silence(
    hass: HomeAssistant,
):
    """The 0.6.7 noise case: a 36-second rhythm silent for 50
    seconds is a device behaving normally, not an episode."""
    device, entity_id = _register(hass, "fd1", "Fast Sensor")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 36.0, 50.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_fast_device_opens_once_it_spends_its_patience(
    hass: HomeAssistant,
):
    """The same device silent well into its grace does open a row,
    so the filter suppresses noise without going blind."""
    device, entity_id = _register(hass, "fd2", "Fast Sensor Two")
    coord = await setup_coordinator(hass, {CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [36.0] * (FREEZE_ARMING_DAYS + 2)
    window = coord._freeze_window(record)
    coord._grace_until = 0.0
    # Silence at three quarters of the way to the freeze line.
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - (36.0 + 0.75 * (window - 36.0))
    )
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1


async def test_globally_excluded_device_is_skipped(
    hass: HomeAssistant,
):
    """#106: no verdict is possible, so no episode explains one."""
    device, entity_id = _register(hass, "ge1", "Global Excluded")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_DEVICES: [device.id], CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_freeze_excluded_device_is_skipped(hass: HomeAssistant):
    device, entity_id = _register(hass, "ze1", "Freeze Excluded")
    coord = await setup_coordinator(hass, {CONF_FREEZE_EXCLUDED_DEVICES: [device.id], CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert coord.data[DATA_EPISODES] == []


async def test_battery_excluded_device_still_counts(
    hass: HomeAssistant,
):
    """Excluded for battery only: still judged for freeze, so its
    silences still belong in the file."""
    device, entity_id = _register(hass, "be1", "Battery Excluded")
    coord = await setup_coordinator(hass, {CONF_BATTERY_EXCLUDED_DEVICES: [device.id], CONF_SIGNAL_MARGIN: 0})
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _rhythm(coord, device.id, 3600.0, 8 * 3600.0)
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1


# ==================================================================
# The refined SIGNAL marks: earliest floor bold, equal never struck.
# ==================================================================

async def test_repeated_floor_bolds_the_earliest_and_strikes_none_equal(
    hass: HomeAssistant,
):
    """A flat run at the floor value: the earliest occurrence is bold,
    the rest are plain, and none of the equal values is struck. This
    is the flat-button case that read as one bold, one struck, two
    plain before the fix."""
    coord, device_id = await _marks_coordinator(hass)
    # Stored oldest-to-newest; displayed newest-first. Four 48s, k=0
    # under a week so floor is 48. Earliest 48 (index 1) bolds.
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        68.0, 48.0, 48.0, 48.0, 52.0, 48.0, 56.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    # Exactly one bold, and it is a 48; no struck values at all
    # (nothing is strictly below the floor of 48).
    assert row.count("**") == 2  # one bold pair
    assert "**48**" in row
    assert "~~" not in row


async def test_below_floor_is_struck_but_equal_is_not(hass: HomeAssistant):
    """A value strictly below the floor is struck; an equal one is
    not. Floor is 112 here (k=1 at a week trims the 84)."""
    coord, device_id = await _marks_coordinator(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        116.0, 116.0, 116.0, 120.0, 112.0, 112.0, 116.0, 84.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    row = _telemetry_row(hass, "Marks Device")
    assert "~~84~~" in row      # strictly below floor 112: struck
    assert "**112**" in row     # earliest 112: bold
    # The other 112 is plain, not struck (equal to the floor).
    assert "~~112~~" not in row
