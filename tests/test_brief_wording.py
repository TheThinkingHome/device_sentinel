# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_wording.py, Version: 0.11.8 (2026-08-04)

"""How the brief says things: prose, device lines, pairing.

One of the files split out of test_email_brief.py, which had
grown larger than any source file in the project (ruling #203).
The seam is the subject, the same rule the source split followed.
Helpers are carried to every file that calls them rather than
pooled, so each file reads on its own.
"""




from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    DATA_INCIDENTS,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    RECOVERY_CAUSE_UNOBSERVED,
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
    """Return the composed brief text of the newest write.

    Since 0.10.18 the file on disk is the rendered HTML page; the
    composed text remains the product these tests assert on, because
    it is the message field, the persistent-notification body, and
    the source the page is rendered from, so its prose is the prose.
    """
    from custom_components.device_sentinel.const import DOMAIN

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    text = getattr(entry.runtime_data, "_last_brief_text", None)
    assert text, "no daily brief was written"
    return text


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
    # The device is gone from every surface. The house's own events
    # remain, because acknowledging one device is not a request to
    # stop hearing that the system restarted (0.10.6), so the table
    # is asserted free of the device rather than empty.
    assert "Nothing has happened since" in text
    assert "| Quiet Please |" not in text


async def test_the_house_speaks_even_on_an_empty_morning(
    hass: HomeAssistant, read_brief
):
    """A restart is worth knowing about with nothing else to report.

    It also explains the rest of the brief: a device revived by a
    reboot reads as a mystery unless the reboot is written down
    somewhere a reader will see it.
    """
    _register(hass, "h1", "Untroubled")
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    assert "The system restarted" in text
    assert "Nothing has happened since" in text
    assert "| The system |" in text


async def test_a_fresh_install_does_not_claim_a_statistics_reset(
    hass: HomeAssistant, read_brief
):
    """The epoch is set on a first install with nothing to wipe, and
    an event that reset nothing would be a fiction on day one."""
    _register(hass, "h2", "Brand New")
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")

    assert "statistics" not in read_brief(hass).lower()


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

    directory = hass.config.path("device_sentinel")
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
