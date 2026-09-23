# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_escalation_read.py, Version: 0.22.27 (2026-09-23)

"""What 0.22.26 wrote and no reader read.

0.22.26 marked a problem replaced by a worse one on its row and
stopped crediting the reboot, but the brief, its table, its counts and
the dashboard never looked at the mark: an escalation still read
"recovered after 31.0h", and so did a battery forecast in the second
it came true. 0.22.27 tells each as the change it is, in the owner's
words. Every test here but the guards fails on 0.22.26.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_CAUSE,
    INC_EVENT,
    INC_SUPERSEDED,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
)
from custom_components.device_sentinel.escalation import (
    ESCALATED_FROM,
    fold,
)
from custom_components.device_sentinel.normalise import (
    damaged_rows,
    fill_missing_row_fields,
    row_damage,
)

from .helpers import register_device, setup_coordinator

HOUR = 3600.0


@pytest.fixture(autouse=True)
def _away_from_the_brief_time(freezer):
    """Run at 1:00 PM Pacific, clear of the brief time and of midnight."""
    freezer.move_to("2026-09-23T20:00:00+00:00")


def _arm(coordinator, device_id: str, category: str | None, since: float) -> None:
    record = coordinator.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = since


async def _escalate(hass: HomeAssistant, name: str = "Watering Kit"):
    """The rig's night: frozen for 31 hours, then unavailable at a reboot.

    The freeze opened before the brief's window, as it did on the rig,
    so the window holds only the escalation's two rows.
    """
    device, _entities = register_device(hass, "w1", name=name)
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - 31 * HOUR)
    coordinator._sync_problem_list()
    for row in coordinator.data[DATA_INCIDENTS]:
        row[INC_WHEN] = now - 31 * HOUR
    _arm(coordinator, device.id, FREEZE_CATEGORY_UNAVAILABLE, now - 31 * HOUR)
    coordinator._sync_problem_list()
    return coordinator, device


async def _brief(hass: HomeAssistant, coordinator) -> str:
    await hass.async_add_executor_job(coordinator._write_reports, "test")
    return coordinator._last_brief_text


def _section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


async def test_in_short_tells_the_escalation_as_a_change(hass: HomeAssistant):
    coordinator, _device = await _escalate(hass)
    in_short = _section(await _brief(hass, coordinator), "## In Short")
    assert "Watering Kit was marked unavailable from frozen at" in in_short
    assert "recovered" not in in_short


async def test_the_table_tells_one_change_and_counts_nothing_ended(
    hass: HomeAssistant,
):
    coordinator, _device = await _escalate(hass)
    table = _section(await _brief(hass, coordinator), "## Last 24 Hours")
    assert "| marked unavailable from frozen |" in table
    assert "recovered" not in table
    assert "1 problem started, 0 ended." in table


async def test_the_dashboard_tab_agrees_with_the_file(
    hass: HomeAssistant, freezer
):
    coordinator, _device = await _escalate(hass)
    # Today's tab ends at this moment, exclusive, and the frozen clock
    # would otherwise hold the rows exactly on that edge.
    freezer.tick(60)
    day = coordinator.dashboard_brief(dt_util.now().date())
    whats = [row["what"] for row in day["events"] if row["who"] == "Watering Kit"]
    assert whats == ["marked unavailable from frozen"]
    assert day["counts"]["resolved"] == 0


async def test_a_real_recovery_still_reads_as_one(hass: HomeAssistant):
    """Guard: a freeze that clears on its own is still good news."""
    device, _entities = register_device(hass, "w2", name="Door Entryway")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - 2 * HOUR)
    coordinator._sync_problem_list()
    for row in coordinator.data[DATA_INCIDENTS]:
        row[INC_WHEN] = now - 30 * HOUR
    _arm(coordinator, device.id, None, now)
    coordinator._sync_problem_list()
    text = await _brief(hass, coordinator)
    assert "Door Entryway recovered at" in _section(text, "## In Short")
    assert "0 problems started, 1 ended." in _section(text, "## Last 24 Hours")


async def test_a_row_written_before_the_mark_reads_as_it_did(
    hass: HomeAssistant,
):
    """Guard: the rig's own row, from 0.22.25, is left as written."""
    coordinator, device = await _escalate(hass)
    for row in coordinator.data[DATA_INCIDENTS]:
        if row[INC_EVENT] == INCIDENT_RESOLVED:
            row.pop(INC_SUPERSEDED)
            row[INC_CAUSE] = "reboot"
    in_short = _section(await _brief(hass, coordinator), "## In Short")
    assert "recovered" in in_short


def _battery_rows(device_id: str, now: float) -> list[dict]:
    """A forecast that came true: running down for 12 days, then low."""
    base = {"device_id": device_id, "name": "Door 2nd Bedroom", "cause": None}
    return [
        {**base, "kind": TODO_KIND_FALLING_BATTERY, "event": INCIDENT_OPENED,
         "when": now - 12 * 86400.0, "duration": None},
        {**base, "kind": TODO_KIND_LOW_BATTERY, "event": INCIDENT_OPENED,
         "when": now, "duration": None},
        {**base, "kind": TODO_KIND_FALLING_BATTERY, "event": INCIDENT_RESOLVED,
         "when": now, "duration": 12 * 86400.0, "superseded": True},
    ]


async def test_a_battery_forecast_coming_true_is_a_change(hass: HomeAssistant):
    device, _entities = register_device(hass, "b1", name="Door 2nd Bedroom")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coordinator.data[DATA_DEVICES][device.id][DEV_BATTERY_VALUE] = 14.0
    coordinator.data[DATA_INCIDENTS] = _battery_rows(device.id, now)
    text = await _brief(hass, coordinator)
    in_short = _section(text, "## In Short")
    table = _section(text, "## Last 24 Hours")
    assert (
        "Door 2nd Bedroom's battery was marked low (14%) from running down at"
        in in_short
    )
    assert "| battery marked low (14%) from running down |" in table
    assert "recovered" not in in_short + table
    assert "1 problem started, 0 ended." in table


async def test_the_level_is_left_out_once_the_cell_reads_full(
    hass: HomeAssistant,
):
    """The low battery rule: no level a row cannot vouch for (#346)."""
    device, _entities = register_device(hass, "b2", name="Door 2nd Bedroom")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coordinator.data[DATA_DEVICES][device.id][DEV_BATTERY_VALUE] = 100.0
    coordinator.data[DATA_INCIDENTS] = _battery_rows(device.id, now)
    table = _section(await _brief(hass, coordinator), "## Last 24 Hours")
    assert "| battery marked low from running down |" in table


def test_a_silence_is_not_a_worse_signal():
    """Guard: only the same family pairs."""
    rows = [
        {"device_id": "a", "name": "A", "kind": TODO_KIND_FROZEN,
         "event": INCIDENT_OPENED, "when": 100.0, "cause": None,
         "duration": None},
        {"device_id": "a", "name": "A", "kind": TODO_KIND_RAILED_SIGNAL,
         "event": INCIDENT_RESOLVED, "when": 100.0, "cause": None,
         "duration": 9.0, "superseded": True},
    ]
    assert fold(rows) == rows


def test_the_fold_pairs_within_a_family_and_keeps_its_distance():
    rows = [
        {"device_id": "a", "name": "A", "kind": TODO_KIND_UNAVAILABLE,
         "event": INCIDENT_OPENED, "when": 100.0, "cause": None,
         "duration": None},
        {"device_id": "a", "name": "A", "kind": TODO_KIND_LOW_BATTERY,
         "event": INCIDENT_RESOLVED, "when": 100.0, "cause": None,
         "duration": 5.0, "superseded": True},
        {"device_id": "a", "name": "A", "kind": TODO_KIND_FROZEN,
         "event": INCIDENT_RESOLVED, "when": 100.0, "cause": None,
         "duration": 9.0, "superseded": True},
        # Another device in the same second is not part of it.
        {"device_id": "b", "name": "B", "kind": TODO_KIND_FROZEN,
         "event": INCIDENT_RESOLVED, "when": 100.0, "cause": None,
         "duration": 9.0, "superseded": True},
        # The same device an hour later is not part of it either.
        {"device_id": "a", "name": "A", "kind": TODO_KIND_UNAVAILABLE,
         "event": INCIDENT_OPENED, "when": 3700.0, "cause": None,
         "duration": None},
    ]
    before = [dict(row) for row in rows]
    folded = fold(rows)
    assert rows == before, "the stored rows were changed"
    # The frozen closing folds into the unavailable opening; the low
    # battery is another family and stays as it was written.
    assert [row.get(ESCALATED_FROM) for row in folded] == [
        TODO_KIND_FROZEN, None, None, None,
    ]
    assert [row["kind"] for row in folded] == [
        TODO_KIND_UNAVAILABLE, TODO_KIND_LOW_BATTERY, TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
    ]


def test_the_storage_check_reads_the_mark():
    row = {
        "device_id": "a" * 32, "name": "A", "kind": TODO_KIND_FROZEN,
        "event": INCIDENT_RESOLVED, "when": 100.0, "cause": None,
        "duration": 9.0,
    }
    assert row_damage(DATA_INCIDENTS, row) is None, "an older row is refused"
    assert row_damage(DATA_INCIDENTS, {**row, "superseded": True}) is None
    assert row_damage(DATA_INCIDENTS, {**row, "superseded": "yes"}) is not None


async def test_in_short_names_every_device(hass: HomeAssistant):
    """Guard, the owner's ruling of 23 September: In Short is never capped.

    It is the paragraph meant one day to be spoken aloud whole. The
    three-name limit belongs to the phone push alone.
    """
    devices = [
        register_device(hass, f"s{i}", name=f"Sensor {i:02d}")[0]
        for i in range(12)
    ]
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    for index, device in enumerate(devices):
        _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - (index + 1) * HOUR)
    coordinator._sync_problem_list()
    in_short = _section(await _brief(hass, coordinator), "## In Short")
    line = next(
        part for part in in_short.splitlines() if part.startswith("Right now:")
    )
    assert all(f"Sensor {i:02d}" in line for i in range(12))
    assert "more device" not in line


def test_a_row_written_before_the_mark_survives_the_load():
    """The load fills a missing field with None and must keep the row.

    A plain boolean kind refused the None it had just filled, and the
    first load of 0.22.27 dropped every incident written before
    0.22.26: the rig's whole record.
    """
    data = {
        DATA_INCIDENTS: [
            {"device_id": "a" * 32, "name": "A", "kind": TODO_KIND_FROZEN,
             "event": INCIDENT_RESOLVED, "when": 100.0, "cause": "reboot",
             "duration": 9.0},
        ]
    }
    fill_missing_row_fields(data)
    assert data[DATA_INCIDENTS][0]["superseded"] is None
    assert damaged_rows(data) == {}
