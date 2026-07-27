# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_email_brief.py, Version: 0.9.11 (2026-07-27)

"""The incident log and the daily brief: the memory and the report.

The incident log is a problem's whole life on one timeline, opened,
resolved with its duration and borrowed cause, acknowledged. The
composer turns those rows into two shapes: an event sentence that reads
as history and carries its time, and a device line that reads as
current status and carries none. The reconcile pass states what is
still true for a problem that predates the engine, idempotently and
skipping the acknowledged. The daily brief opens in that prose, history
oldest first then what is standing, in language that needs no knowledge
of the internals, and its grammar, its acknowledgment handling, its
intervention attribution, and its one-window-one-file naming all have
to stay honest. This file holds the log, the composer, the reconcile,
the prose, and those four honesty fixes; the window close, the
schedule, and the email delivery follow in the same file.
"""

import glob
import os

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIEF_TRIGGER,
    CONF_BRIEF_TARGETS,
    CONF_EXCLUDED_DEVICES,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EPISODE_ENDED_RECONNECT,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_WINDOW,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INCIDENT_ACKNOWLEDGED,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    PERSISTENT_TARGET,
    RECOVERY_CAUSE_UNOBSERVED,
    REMINDER_MODE_DAILY,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
)

from tests.helpers import setup_coordinator

DOMAIN = "device_sentinel"


def _register(hass, uid, name, battery=False, source=None):
    """A device with a plain sensor and, optionally, a battery entity.

    Returns (device, entity_id, source). The source is returned so a
    test can register a second device on the same integration, which
    the intervention-attribution tests rely on.
    """
    if source is None:
        source = MockConfigEntry(domain="test", title=f"Source {uid}")
        source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    if battery:
        reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, plain.entity_id, source


def _brief_text(hass):
    """Return the brief that was written, whatever its name.

    Named for the day its window opened, which is not today's date
    when the window began before the brief hour (0.7.5).
    """
    written = sorted(
        glob.glob(
            hass.config.path("device_sentinel", "daily_brief_*.md")
        )
    )
    assert written, "no daily brief was written"
    with open(written[0], encoding="utf-8") as handle:
        return handle.read()


def _freeze(coord, device_id, hours_ago=4.0):
    since = dt_util.utcnow().timestamp() - hours_ago * 3600.0
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


def _fault(coord, device_id, category, hours=4.0):
    """A stored down verdict of the given category, for the composer
    and grammar tests that read the standing device line."""
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = (
        dt_util.utcnow().timestamp() - hours * 3600.0
    )


def _unfreeze(coord, device_id):
    record = coord.data["devices"][device_id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()


def _events(coord, event_type):
    return [
        row
        for row in coord.data[DATA_INCIDENTS]
        if row[INC_EVENT] == event_type
    ]


def _row(coord, device_id, name, kind, event, **extra):
    row = {
        INC_DEVICE_ID: device_id,
        INC_NAME: name,
        INC_KIND: kind,
        INC_EVENT: event,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_CAUSE: extra.get("cause"),
        INC_DURATION: extra.get("duration"),
    }
    return coord._compose_event(row)


def _open_episode(coord, device_id, name):
    coord.data[DATA_EPISODES].append(
        {
            EP_DEVICE_ID: device_id,
            EP_NAME: name,
            EP_SINCE: dt_util.utcnow().timestamp() - 7200.0,
            EP_BASIS: 3600.0,
            EP_WINDOW: 7200.0,
            EP_ENDED: None,
            EP_AT: None,
            EP_LAG: None,
            EP_LEARNED: None,
        }
    )


# ==================================================================
# The incident log timeline.
# ==================================================================

async def test_opening_and_resolution_land_on_the_timeline(
    hass: HomeAssistant,
):
    """A problem's whole life: opened when detected, resolved when it
    clears, with the duration computed from its own opening."""
    device, entity_id, _ = _register(hass, "t1", "Timeline Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    assert len(_events(coord, INCIDENT_OPENED)) == 1
    assert _events(coord, INCIDENT_OPENED)[0][INC_NAME] == (
        "Timeline Sensor"
    )

    _unfreeze(coord, device.id)
    coord._sync_problem_list()
    resolved = _events(coord, INCIDENT_RESOLVED)
    assert len(resolved) == 1
    assert resolved[0][INC_KIND] == "frozen"
    assert resolved[0][INC_DURATION] is not None


async def test_acknowledgement_is_recorded(hass: HomeAssistant):
    device, entity_id, _ = _register(hass, "a1", "Acked Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    assert len(_events(coord, INCIDENT_ACKNOWLEDGED)) == 1


async def test_resolution_borrows_its_cause(hass: HomeAssistant):
    """A silence that ended on its own says so; the cause comes from
    the episode record rather than a guess."""
    device, entity_id, _ = _register(hass, "c1", "Caused Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    coord._grace_until = 0.0
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 8 * 3600
    coord._judge_all_devices()          # opens the episode and freezes
    coord._sync_problem_list()
    coord._record_activity(device.id, None, entity_id, "2")  # resumes
    coord._sync_problem_list()

    resolved = _events(coord, INCIDENT_RESOLVED)
    assert resolved
    # 0.7.6: not "on its own". We saw no lever, which is not the same
    # as there having been none.
    assert resolved[-1][INC_CAUSE] == RECOVERY_CAUSE_UNOBSERVED


async def test_battery_resolution_has_no_cause(hass: HomeAssistant):
    """Only a silence has a lever to credit."""
    device, entity_id, _ = _register(hass, "b1", "Battery Sensor", True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 14.0
    record[DEV_BATTERY_SINCE] = "2026-07-21T15:02:00+00:00"
    coord._sync_problem_list()
    record[DEV_BATTERY_LOW] = False
    coord._sync_problem_list()
    resolved = _events(coord, INCIDENT_RESOLVED)
    assert resolved[-1][INC_KIND] == "battery"
    assert resolved[-1][INC_CAUSE] is None


async def test_incidents_reach_diagnostics(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, entity_id, _ = _register(hass, "d1", "Diag Sensor")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "incidents" in diag
    assert diag["incidents"][0][INC_NAME] == "Diag Sensor"


async def test_startup_storm_is_named_a_restart(hass: HomeAssistant):
    """The folded 0.6.9 fix: every device reporting at once after a
    restart looks like a bridge reconnect, and is not one."""
    from custom_components.device_sentinel.const import (
        EPISODE_ENDED_RESTART,
        EP_ENDED,
    )

    device, entity_id, _ = _register(hass, "s1", "Restart Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    # An episode open from before the restart.
    coord.data["silence_episodes"].append(
        {
            "device_id": device.id,
            "name": "Restart Sensor",
            "since": dt_util.utcnow().timestamp() - 7200.0,
            "basis": 3600.0,
            "window": 7200.0,
            "ended": None,
            "at": None,
            "lag": None,
            "learned": None,
        }
    )
    # Inside startup grace, a storm is the restart.
    coord._grace_until = dt_util.utcnow().timestamp() + 60.0
    coord._stamp_intervention(
        EPISODE_ENDED_RESTART, dt_util.utcnow().timestamp()
    )
    assert coord.data["silence_episodes"][-1][EP_ENDED] == (
        EPISODE_ENDED_RESTART
    )


async def test_no_episodes_open_during_startup_grace(
    hass: HomeAssistant,
):
    """The other folded fix: stale clocks after a restart must not
    manufacture a batch of rows about the restart."""
    device, entity_id, _ = _register(hass, "g1", "Grace Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 8 * 3600
    coord._grace_until = dt_util.utcnow().timestamp() + 60.0
    coord._judge_all_devices()
    assert coord.data["silence_episodes"] == []


async def test_scheduled_roll_opens_todays_in_progress_brief(
    hass: HomeAssistant, freezer
):
    """The 7 AM roll closes yesterday and opens today (#116, 0.9.9).

    Before this, the scheduled write completed the day that ended and
    left the day just beginning with no file until the next startup,
    so from the roll onward the file named for today was absent and
    the outside witness reported the brief missing. The roll now
    writes today's in-progress brief too, so both files exist."""
    from custom_components.device_sentinel.const import (
        BRIEF_TRIGGER,
        CONF_REMINDER_TIME,
    )

    # A moment just after the 7 AM brief hour, so the closing window is
    # yesterday and the newly opened window is today. Pin the zone so
    # the dates do not depend on the test default: 12:00:01Z is
    # 07:00:01 local at UTC-5, just past the 07:00 brief hour.
    await hass.config.async_set_time_zone("America/Guayaquil")  # UTC-5
    freezer.move_to("2026-07-26T12:00:01+00:00")  # 07:00:01 local
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})

    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)

    written = sorted(
        glob.glob(hass.config.path("device_sentinel", "daily_brief_*.md"))
    )
    names = [p.rsplit("/", 1)[-1] for p in written]
    assert "daily_brief_2026-07-25.md" in names, names  # closed day
    assert "daily_brief_2026-07-26.md" in names, names  # opened day

    with open(
        hass.config.path("device_sentinel", "daily_brief_2026-07-25.md"),
        encoding="utf-8",
    ) as handle:
        completed = handle.read()
    with open(
        hass.config.path("device_sentinel", "daily_brief_2026-07-26.md"),
        encoding="utf-8",
    ) as handle:
        today = handle.read()

    assert "Covering the 24 hours" in completed  # the closed brief
    assert "(in progress)" in today              # today's open brief


# ==================================================================
# The message composer.
# ==================================================================

async def test_event_sentences_read_as_history(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    text = _row(coord, "d", "Door Master", "frozen", INCIDENT_OPENED)
    assert text.startswith("Door Master stopped reporting at ")
    assert text.endswith(".")

    text = _row(coord, "d", "Temperature LR", "unavailable", INCIDENT_OPENED)
    assert "went unavailable at " in text


async def test_recovery_sentence_carries_span_and_cause(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    text = _row(
        coord, "d", "Door Master", "frozen", INCIDENT_RESOLVED,
        duration=7200.0, cause="bridge reconnect",
    )
    assert "recovered at " in text
    assert "after 2.0h" in text
    assert "revived by a bridge reconnect" in text

    text = _row(
        coord, "d", "Leak Washer", "frozen", INCIDENT_RESOLVED,
        duration=1320.0, cause=RECOVERY_CAUSE_UNOBSERVED,
    )
    assert "after 22m, no intervention recorded." in text

    # A problem that predates the log resolves without a duration.
    text = _row(
        coord, "d", "Old Problem", "frozen", INCIDENT_RESOLVED,
    )
    assert "after" not in text


async def test_device_line_is_status_without_a_timestamp(
    hass: HomeAssistant,
):
    device, entity_id, _ = _register(hass, "s1", "Door Master")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 4 * 3600
    coord._sync_problem_list()
    line = coord._compose_device_line(device.id)
    assert line == "Door Master stopped reporting 4.0h ago."
    assert "AM" not in line and "PM" not in line


async def test_device_line_names_the_worst_and_counts_the_rest(
    hass: HomeAssistant,
):
    device, entity_id, _ = _register(hass, "m1", "Motion Closet", True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 14.0
    record[DEV_BATTERY_SINCE] = "2026-07-21T15:02:00+00:00"
    coord._sync_problem_list()
    line = coord._compose_device_line(device.id)
    # Silence outranks battery, and the battery is counted, not named.
    assert line.startswith("Motion Closet stopped reporting")
    assert line.endswith(", and 1 more problem.")


async def test_battery_line_carries_the_level(hass: HomeAssistant):
    device, entity_id, _ = _register(hass, "b1", "Motion Bath", True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 14.0
    record[DEV_BATTERY_SINCE] = "2026-07-21T15:02:00+00:00"
    coord._sync_problem_list()
    assert coord._compose_device_line(device.id) == (
        "Motion Bath battery is at 14%."
    )


# ==================================================================
# The reconcile pass: restating what is already true.
# ==================================================================

# ==================================================================
# The brief opens in prose.
# ==================================================================

async def test_brief_has_both_sections_in_plain_language(
    hass: HomeAssistant,
):
    device, entity_id, _ = _register(hass, "w1", "Brief Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = _brief_text(hass)
    assert "# Device Sentinel Daily Brief" in text
    assert "## Now" in text and "## Last 24 Hours" in text
    assert "Brief Sensor" in text
    assert "stopped reporting" in text     # never the raw category
    assert "frozen" not in text
    assert "basis" not in text and "window" not in text


async def test_regenerated_brief_says_it_is_incomplete(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _brief_text(hass)
    assert "(in progress)" in text
    assert "Nothing needs attention." in text


async def test_excluded_devices_never_reach_the_brief(
    hass: HomeAssistant,
):
    """It is a report, so exclusion suppresses it here."""
    device, entity_id, _ = _register(hass, "x1", "Hidden Sensor")
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "21.5")
    coord._record_incident(
        device.id, "Hidden Sensor", "frozen", INCIDENT_OPENED
    )
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Hidden Sensor" not in text


async def test_brief_opens_with_prose(hass: HomeAssistant):
    device, entity_id, _ = _register(hass, "p1", "Prose Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)

    assert text.index("## In Short") < text.index("## Now")
    assert "Prose Sensor stopped reporting at " in text   # history
    assert "Prose Sensor stopped reporting 1.0h ago." in text  # standing
    assert "Right now:" in text


async def test_quiet_day_says_so_plainly(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Nothing has happened since" in text
    assert "Nothing needs attention right now." in text


async def test_history_reads_oldest_first(hass: HomeAssistant):
    """The prose is a narrative, so it runs forward in time even
    though the table below stays newest first for scanning."""
    first, first_entity, _ = _register(hass, "h1", "Early Sensor")
    second, second_entity, _ = _register(hass, "h2", "Later Sensor")
    coord = await setup_coordinator(hass)
    for entity_id in (first_entity, second_entity):
        hass.states.async_set(entity_id, "on")
    now = dt_util.utcnow().timestamp()
    for device, ago in ((first, 4 * 3600), (second, 3600)):
        record = coord.data["devices"][device.id]
        record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
        record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
        record[DEV_FROZEN_SINCE] = now - ago
        coord._sync_problem_list()

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert prose.index("Early Sensor") < prose.index("Later Sensor")


async def test_acknowledged_devices_are_absent_from_the_prose(
    hass: HomeAssistant,
):
    """#123: acknowledging a problem is the statement that the person
    knows about it, so it leaves the brief rather than being listed
    with a mark."""
    device, entity_id, _ = _register(hass, "a1", "Acked Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Acked Sensor" not in text
    assert "acknowledged" not in text
    assert "Nothing needs attention right now." in text


async def test_battery_level_agrees_everywhere(hass: HomeAssistant):
    """#120: the table said 'battery fell low' while the composer
    said 'battery fell to 0%'. One composer, one wording."""
    device, entity_id, _ = _register(hass, "b1", "Battery Sensor", True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 0.0
    record[DEV_BATTERY_SINCE] = "2026-07-22T20:07:00+00:00"
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "battery fell to 0%" in text      # history, prose and table
    assert "battery fell low" not in text
    assert "battery is at 0%" in text        # standing state


# ==================================================================
# Four ways the reports were telling small lies.
# ==================================================================

async def test_present_perfect_kinds_take_for_not_ago(
    hass: HomeAssistant,
):
    """"has been unavailable 4.0h ago" reached a live brief. Three of
    the four wordings are present perfect and need "for"."""
    device, entity_id, _ = _register(hass, "g1", "Grammar Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_UNAVAILABLE)
    coord._sync_problem_list()
    line = coord._compose_device_line(device.id)
    assert line == "Grammar Sensor has been unavailable for 4.0h."
    assert "ago" not in line


async def test_past_tense_kind_still_takes_ago(hass: HomeAssistant):
    device, entity_id, _ = _register(hass, "g2", "Past Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()
    assert coord._compose_device_line(device.id) == (
        "Past Sensor stopped reporting 4.0h ago."
    )


async def test_acknowledged_device_leaves_the_whole_brief(
    hass: HomeAssistant, read_brief
):
    """Standing state and history alike, while it stays acknowledged."""
    device, entity_id, _ = _register(hass, "a1", "Quiet Please")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()          # opens an incident
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    assert "Quiet Please" not in text
    assert "Nothing needs attention." in text
    assert "Nothing happened." in text


async def test_recovery_of_an_acknowledged_device_is_news(
    hass: HomeAssistant, read_brief
):
    """#114 with #123: acknowledgment ends at recovery, because the
    item is deleted, so the recovery is reported."""
    device, entity_id, _ = _register(hass, "a2", "Came Back")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")

    record = coord.data["devices"][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()          # deletes the item
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    assert "Came Back" in text
    assert "recovered" in text


async def test_a_storm_only_stamps_its_own_integration(
    hass: HomeAssistant,
):
    """A Zigbee reconnect cannot revive a HomeKit accessory, and
    crediting it with one put a false cause in a live brief."""
    zigbee, _, zigbee_entry = _register(hass, "z1", "Zigbee Thing")
    homekit, _, _ = _register(hass, "h1", "HomeKit Thing")
    coord = await setup_coordinator(hass)
    _open_episode(coord, zigbee.id, "Zigbee Thing")
    _open_episode(coord, homekit.id, "HomeKit Thing")

    coord._stamp_intervention(
        EPISODE_ENDED_RECONNECT,
        dt_util.utcnow().timestamp(),
        entry_id=zigbee_entry.entry_id,
    )
    by_name = {
        row[EP_NAME]: row[EP_ENDED] for row in coord.data[DATA_EPISODES]
    }
    assert by_name["Zigbee Thing"] == EPISODE_ENDED_RECONNECT
    assert by_name["HomeKit Thing"] is None


async def test_a_restart_stamps_everything(hass: HomeAssistant):
    """No entry_id means the whole system, which is what a restart is."""
    first, _, _ = _register(hass, "r1", "One")
    second, _, _ = _register(hass, "r2", "Two")
    coord = await setup_coordinator(hass)
    _open_episode(coord, first.id, "One")
    _open_episode(coord, second.id, "Two")

    coord._stamp_intervention(
        EPISODE_ENDED_RECONNECT, dt_util.utcnow().timestamp()
    )
    assert all(
        row[EP_ENDED] == EPISODE_ENDED_RECONNECT
        for row in coord.data[DATA_EPISODES]
    )


async def test_one_window_writes_one_file(hass: HomeAssistant):
    """Naming by the moment of writing renamed the in-progress brief
    at midnight, so a single window left two overlapping files."""
    coord = await setup_coordinator(hass)
    for _ in range(3):
        await hass.async_add_executor_job(coord._write_reports, "test")
    written = glob.glob(
        hass.config.path("device_sentinel", "daily_brief_*.md")
    )
    assert len(written) == 1


async def test_the_file_is_named_for_the_window_start(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    start = coord._brief_window_start(dt_util.utcnow().timestamp())
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    written = glob.glob(
        hass.config.path("device_sentinel", "daily_brief_*.md")
    )
    assert os.path.basename(written[0]) == expected


# ==================================================================
# Closing the window, the schedule, and the email delivery.
# ==================================================================

def _briefs(hass):
    return sorted(
        glob.glob(hass.config.path("device_sentinel", "daily_brief_*.md"))
    )


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _seed(coord, rows):
    """Place incidents inside the current brief window, in order.

    Offsets are measured forward from the window's own start rather
    than back from now, because the window runs brief-to-brief and a
    row placed an hour ago falls outside it whenever the test runs
    within an hour of the brief time.
    """
    now = dt_util.utcnow().timestamp()
    start = coord._brief_window_start(now)
    seeded = []
    for step, (device_id, name, event, extra) in enumerate(rows, start=1):
        row = {
            INC_DEVICE_ID: device_id,
            INC_NAME: name,
            INC_KIND: TODO_KIND_FROZEN,
            INC_EVENT: event,
            INC_WHEN: min(start + step, now),
            INC_CAUSE: None,
            INC_DURATION: None,
        }
        row.update(extra)
        seeded.append(row)
    coord.data[DATA_INCIDENTS] = seeded


def _capture(hass, service="brief_mail"):
    """Register a notify service that records what it was sent."""
    calls = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", service, handler)
    return calls


# ----------------------------------------------- closing the window

async def test_a_scheduled_write_completes_the_brief(
    hass: HomeAssistant,
):
    """The fault: nothing ever passed the closing trigger, so every
    brief said "in progress" forever."""
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    closed = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    text = _text(hass.config.path("device_sentinel", closed))
    assert "(in progress)" not in text
    assert "Covering the 24 hours since" in text


async def test_a_manual_write_stays_in_progress(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _text(_briefs(hass)[0])
    # One marker, not two: the line used to open "In progress" and
    # close "(incomplete)", saying the same thing twice (0.8.10).
    assert "(in progress)" in text
    assert "In progress" not in text


async def test_the_closed_window_is_the_one_that_just_ended(
    hass: HomeAssistant,
):
    """It finishes the day behind it rather than the one starting, so
    the completed brief covers brief hour to brief hour."""
    coord = await setup_coordinator(hass)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0
    hour, minute = coord._brief_hour_minute()
    for edge in (start, end):
        local = dt_util.as_local(dt_util.utc_from_timestamp(edge))
        assert (local.hour, local.minute) == (hour, minute)
    assert end <= dt_util.utcnow().timestamp()


async def test_the_completed_brief_is_named_for_the_day_it_covers(
    hass: HomeAssistant,
):
    """A completed brief and the window that follows it must not
    collide, which is what produced two files for one window."""
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, BRIEF_TRIGGER)
    start, _end = coord._brief_close_bounds()
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    assert os.path.basename(_briefs(hass)[0]) == expected

    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert len(_briefs(hass)) == 2      # yesterday closed, today open


async def test_the_schedule_follows_the_configured_time(
    hass: HomeAssistant,
):
    """The brief time is a live option, so changing it re-arms."""
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "06:30:00"})
    assert coord._brief_hour_minute() == (6, 30)
    assert coord._brief_unsub is not None

    first = coord._brief_unsub
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_REMINDER_TIME: "21:15:00"}
    )
    await coord.async_options_updated()
    assert coord._brief_hour_minute() == (21, 15)
    assert coord._brief_unsub is not first


async def test_a_nonsense_time_falls_back_rather_than_raising(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "not a time"})
    assert coord._brief_hour_minute() == (8, 0)
    start, end = coord._brief_close_bounds()
    assert end - start == 86400.0


async def test_the_scheduled_write_survives_a_day_boundary(
    hass: HomeAssistant, freezer
):
    """Whatever the clock says when the callback lands, the window it
    closes is the one that ended at the configured hour."""
    coord = await setup_coordinator(hass, {CONF_REMINDER_TIME: "07:00:00"})
    freezer.tick(timedelta(seconds=2))
    start, end = coord._brief_close_bounds()
    local_end = dt_util.as_local(dt_util.utc_from_timestamp(end))
    assert (local_end.hour, local_end.minute) == (7, 0)
    assert end - start == 86400.0


# --------------------------------------------- not overclaiming

async def test_an_unobserved_recovery_says_so_plainly(
    hass: HomeAssistant,
):
    """A rebind by hand read as "on its own" in a live brief. We can
    say we saw no intervention; we cannot say there was none."""
    coord = await setup_coordinator(hass)
    row = {
        INC_DEVICE_ID: "d",
        INC_NAME: "Door Master",
        INC_KIND: "frozen",
        INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_CAUSE: RECOVERY_CAUSE_UNOBSERVED,
        INC_DURATION: 4.3 * 3600,
    }
    text = coord._compose_event(row)
    assert "no intervention recorded" in text
    assert "on its own" not in text
    assert "revived by" not in text


async def test_a_known_lever_is_still_credited(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    row = {
        INC_DEVICE_ID: "d",
        INC_NAME: "Door Master",
        INC_KIND: "frozen",
        INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_CAUSE: "bridge reconnect",
        INC_DURATION: 7200.0,
    }
    assert "revived by a bridge reconnect" in coord._compose_event(row)


# ----------------------------------- episodes paired in the prose

async def test_a_stop_and_its_recovery_are_one_sentence(
    hass: HomeAssistant, read_brief
):
    """#134: the brief told them four sentences apart in a live file."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "Presence Guest", INCIDENT_OPENED, {}),
        ("d1", "Presence Guest", INCIDENT_RESOLVED,
         {INC_DURATION: 4.1 * 3600, INC_CAUSE: "reboot"}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert (
        "Presence Guest stopped reporting at" in prose
        and "and recovered 4.1h later, revived by a reboot." in prose
    )
    # One sentence, so the name is said once rather than twice.
    assert prose.count("Presence Guest") == 1


async def test_the_recovery_clock_time_is_dropped_from_a_pair(
    hass: HomeAssistant, read_brief
):
    """The opening time plus the span gives it, and the table below
    carries exact times for anyone looking one up."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "Paired Sensor", INCIDENT_OPENED, {}),
        ("d1", "Paired Sensor", INCIDENT_RESOLVED, {INC_DURATION: 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    prose = read_brief(hass)
    prose = prose[prose.index("## In Short"): prose.index("## Now")]
    assert "and recovered 1.0h later." in prose
    assert "recovered at" not in prose


async def test_a_pair_holds_together_across_other_devices(
    hass: HomeAssistant, read_brief
):
    """The failure this fixes: strict time order split every pair as
    soon as a second device broke in between."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "First Device", INCIDENT_OPENED, {}),
        ("d2", "Second Device", INCIDENT_OPENED, {}),
        ("d1", "First Device", INCIDENT_RESOLVED, {INC_DURATION: 4 * 3600.0}),
        ("d2", "Second Device", INCIDENT_RESOLVED,
         {INC_DURATION: 4 * 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    sentences = [
        part.strip()
        for part in prose.split(". ")
        if "Device" in part
    ]
    assert len(sentences) == 2, prose
    # Ordered by when each episode began, so the narrative still
    # runs forward without splitting a pair.
    assert prose.index("First Device") < prose.index("Second Device")
    assert prose.count("First Device") == 1
    assert prose.count("Second Device") == 1


async def test_two_breaks_in_one_window_give_two_episodes(
    hass: HomeAssistant, read_brief
):
    """Each resolution matches the most recent unmatched opening, so
    a device that breaks twice is not crossed into one long silence."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "Twice Sensor", INCIDENT_OPENED, {}),
        ("d1", "Twice Sensor", INCIDENT_RESOLVED, {INC_DURATION: 3600.0}),
        ("d1", "Twice Sensor", INCIDENT_OPENED, {}),
        ("d1", "Twice Sensor", INCIDENT_RESOLVED,
         {INC_DURATION: 2 * 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert prose.count("Twice Sensor") == 2
    assert "and recovered 1.0h later." in prose
    assert "and recovered 2.0h later." in prose


async def test_a_recovery_older_than_the_window_stands_alone(
    hass: HomeAssistant, read_brief
):
    """Door Master's case: the silence began before the window opened,
    so there is no opening to pair with and the lone wording stays."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "Door Master", INCIDENT_RESOLVED,
         {INC_DURATION: 4.3 * 3600, INC_CAUSE: RECOVERY_CAUSE_UNOBSERVED}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert "Door Master recovered at" in prose
    assert "after 4.3h, no intervention recorded." in prose


async def test_a_never_reported_device_is_never_paired(
    hass: HomeAssistant, read_brief
):
    """It has no moment of failure, so joining its opening to a
    recovery would read "had never reported and recovered 3.6d
    later". Two sentences instead."""
    coord = await setup_coordinator(hass)
    _seed(coord, [
        ("d1", "Ghost Device", INCIDENT_OPENED,
         {INC_KIND: TODO_KIND_NOT_REPORTED}),
        ("d1", "Ghost Device", INCIDENT_RESOLVED,
         {INC_KIND: TODO_KIND_NOT_REPORTED, INC_DURATION: 3600.0}),
    ])
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    prose = text[text.index("## In Short"): text.index("## Now")]
    assert "has never reported since it was discovered." in prose
    assert "Ghost Device recovered at" in prose


# --------------------------------------------------------- title case

async def test_every_generated_heading_is_title_case(
    hass: HomeAssistant, read_brief
):
    """#133: one file fixed and three left would be worse than none."""
    _register(hass, "t1", "Title Sensor")
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    brief = read_brief(hass)
    assert "# Device Sentinel Daily Brief" in brief
    assert "## In Short" in brief
    assert "## Last 24 Hours" in brief

    directory = hass.config.path("device_sentinel", "diagnostics")
    for name, heading in (
        ("device_telemetry.md", "Learned Statistics"),
        ("classification.md", "Classification"),
        ("silence_episodes.md", "Silence Episodes"),
    ):
        with open(f"{directory}/{name}", encoding="utf-8") as handle:
            text = handle.read()
        assert heading in text, name
        assert heading.lower() not in text.replace(
            heading.lower().replace(" ", "_"), ""
        ), f"{name} still carries a sentence-case heading"


# --------------------------------------------------------- the email

async def test_the_brief_is_emailed_whole(hass: HomeAssistant):
    """The document, not a summary of it: the same text the file
    carries, with the In Short prose leading it."""
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert len(calls) == 1
    sent = calls[0]
    assert sent["title"] == "Device Sentinel Daily Brief"
    assert sent["message"].startswith("# Device Sentinel Daily Brief")
    assert "## In Short" in sent["message"]
    assert "## Last 24 Hours" in sent["message"]
    assert "<h2>In Short</h2>" in sent["data"]["html"]


async def test_an_in_progress_brief_is_never_sent(hass: HomeAssistant):
    """#135: a regenerate or a midnight rewrite produces an unfinished
    document, and mailing those would deliver one day several times.

    The guard has to return before the send loop, not merely produce a
    zero count. If a None text reached the loop, building its payload
    would raise and the bare except would swallow it, leaving sent at
    zero and a broken guard looking healthy. So this pins the loop is
    never entered: _brief_payload is never called for an unfinished
    brief.
    """
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    text = await hass.async_add_executor_job(coord._write_reports, "test")
    assert text is None

    payloads = []
    original = coord._brief_payload
    coord._brief_payload = lambda target, body: payloads.append(body) or original(
        target, body
    )
    try:
        assert await coord.async_send_brief(text) == 0
    finally:
        coord._brief_payload = original
    # The loop was never entered, so no payload was ever built. Under
    # the whole guard this holds; drop the not-text half and the loop
    # runs, _brief_payload is called with None, and this fails.
    assert payloads == []
    assert not calls


async def test_never_means_never(hass: HomeAssistant):
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_NONE,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert not calls


async def test_problems_only_stays_quiet_on_a_clear_day(
    hass: HomeAssistant,
):
    """The mode says only when something needs attention, and the
    brief is still written to disk either way."""
    calls = _capture(hass)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_OVERNIGHT,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert not calls


async def test_problems_only_sends_when_something_is_wrong(
    hass: HomeAssistant,
):
    calls = _capture(hass)
    device, entity_id, _ = _register(hass, "p1", "Problem Sensor")
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_OVERNIGHT,
            CONF_BRIEF_TARGETS: ["notify.brief_mail"],
        },
    )
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "Problem Sensor" in calls[0]["message"]


async def test_one_dead_target_does_not_silence_the_others(
    hass: HomeAssistant,
):
    """A brief that cannot reach one mail server must still reach the
    rest, and must still be on disk either way."""
    good = _capture(hass, "good_mail")

    async def broken(call):
        raise OSError("no route to host")

    hass.services.async_register("notify", "dead_mail", broken)
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: ["notify.dead_mail", "notify.good_mail"],
        },
    )
    text = await hass.async_add_executor_job(
        coord._write_reports, BRIEF_TRIGGER
    )
    assert await coord.async_send_brief(text) == 1
    assert len(good) == 1


async def test_the_persistent_notification_gets_no_html(
    hass: HomeAssistant,
):
    """It takes a title and a message and nothing else, so offering
    it a data key it does not know would fail the whole send."""
    coord = await setup_coordinator(
        hass,
        {
            CONF_REMINDER_MODE: REMINDER_MODE_DAILY,
            CONF_BRIEF_TARGETS: [PERSISTENT_TARGET],
        },
    )
    payload = coord._brief_payload(PERSISTENT_TARGET, "# Title")
    assert "data" not in payload
    assert coord._brief_payload("notify.mail", "# Title")["data"]


# ------------------------------------------------------ the rendering

async def test_the_renderer_makes_tables_and_escapes_content(
    hass: HomeAssistant,
):
    """A mail client shows a pipe table as a wall of text, so the
    tables are rendered; anything a device name could carry is
    escaped rather than injected."""
    coord = await setup_coordinator(hass)
    html = coord._brief_html(
        "# Device Sentinel Daily Brief\n"
        "\n"
        "Jul 24, 7:00 AM.\n"
        "\n"
        "## Now\n"
        "\n"
        "| DEVICE | PROBLEM |\n"
        "|---|---|\n"
        "| Sensor <script> | stopped reporting |\n"
    )
    assert "<h1>Device Sentinel Daily Brief</h1>" in html
    assert "<h2>Now</h2>" in html
    assert "<p>Jul 24, 7:00 AM.</p>" in html
    assert "<th" in html and "DEVICE</th>" in html
    assert "<td" in html and "stopped reporting</td>" in html
    # The separator row is grammar, not data.
    assert "---" not in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
