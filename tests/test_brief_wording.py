# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_brief_wording.py, Version: 0.19.12 (2026-09-02)

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
    DATA_SYSTEM_EVENTS,
    SYS_WHEN,
    SYS_KIND,
    SYS_SCOPE,
    SYS_DURATION,
    SYS_DETAIL,
    SYS_DEVICES,
    SYS_RESTART,
    SYS_OPTIONS_CHANGED,
    SYS_BRIDGE_UP,
    CONF_MUTED_DEVICES,
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
    ACTION_ACKNOWLEDGED,
    INCIDENT_ACTION,
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
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_NEVER_REPORTED,
)

from tests.helpers import register_device, setup_coordinator

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


async def test_muted_devices_never_reach_the_brief(
    hass: HomeAssistant,
):
    """It is a report, so exclusion suppresses it here."""
    device, entity_id, _ = _register(hass, "x1", "Hidden Sensor")
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [device.id]}
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
    assert "No device problems started or ended in this window." in text
    assert "Nothing needs attention right now." in text


async def test_a_standing_problem_is_never_called_nothing(
    hass: HomeAssistant,
):
    """The all-clear answers the sentence above it, so a brief that
    names a device standing right now cannot also say nothing needs
    attention. Every brief carrying a standing problem and no repeat
    offender said both, from 0.16.2 until this was written."""
    device, entity_id, _ = _register(hass, "n1", "Standing Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Right now: Standing Sensor" in text
    assert "Nothing needs attention right now." not in text


async def test_settings_with_commas_in_their_names_stay_countable(
    hass: HomeAssistant, read_brief
):
    """Two of the signal labels carry commas of their own, so a
    comma-separated list read as five settings where three were
    changed."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {
            SYS_WHEN: now - 1800.0,
            SYS_KIND: SYS_OPTIONS_CHANGED,
            SYS_SCOPE: "system",
            SYS_DURATION: None,
            SYS_DETAIL: "badday_drop_lqi, badday_drop_rssi",
            SYS_DEVICES: None,
        }
    ]
    await hass.async_add_executor_job(coord._write_reports, "test")
    short = read_brief(hass)
    assert "Bad Day Drop, LQI; Bad Day Drop, RSSI" in short


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
    assert "No device problems started or ended in this window." in text
    assert "| Quiet Please |" not in text


async def test_an_ordinary_restart_is_not_worth_a_sentence(
    hass: HomeAssistant, read_brief
):
    """In Short reports the abnormal; the table reports everything.

    This reverses ruling #230, which held that a second restart is a
    second event a person wants to see. It was decided when restarts
    were rare, and a day carrying sixteen house sentences that read
    almost identically to the table beneath them showed it was
    wrong. A restart of a few seconds is a quiet night, and the row
    stays in Last 24 Hours for anyone looking a time up.
    """
    _register(hass, "h1", "Untroubled")
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    short = text.split("## Last 24 Hours")[0]
    assert "The system restarted" not in short
    assert "The system was unwatched" not in short
    assert "No device problems started or ended in this window." in text
    # Not lost, only moved: the table still carries it.
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
    # The prose says it once, with the count and the total, because a
    # device that goes and returns twice is one thing happening
    # repeatedly (ruling #276). The pairing this test exists for is
    # asserted on the table, where each break keeps its own row and
    # its own duration: crossed pairing would show one 3.0h silence.
    assert prose.count("Twice Sensor") == 1
    assert "went silent twice" in prose
    assert "3.0h in total" in prose
    rows = text[text.index("## Last 24 Hours"):]
    assert "1.0h" in rows
    assert "2.0h" in rows


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
         {INC_KIND: TODO_KIND_NEVER_REPORTED}),
        ("d1", "Ghost Device", INCIDENT_RESOLVED,
         {INC_KIND: TODO_KIND_NEVER_REPORTED, INC_DURATION: 3600.0}),
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


async def test_a_noisy_day_reads_as_two_sentences(
    hass: HomeAssistant, read_brief
):
    """The day that prompted ruling #275, replayed.

    On 15 August the reference system restarted seven times, changed
    settings five times, and cycled its bridge twice, and In Short
    carried sixteen sentences that read almost identically to the
    table beneath them. Every restart was about thirty seconds and
    every bridge outage a reboot artefact, so under the abnormal-only
    rule none of them earns a sentence and the paragraph says the one
    thing a person can act on: what they changed.
    """
    coord = await setup_coordinator(hass)
    base = coord.data[DATA_SYSTEM_EVENTS] = []
    now = dt_util.utcnow().timestamp()
    for offset, span in enumerate((37.0, 30.0, 0.0, 27.0, 27.0, 29.0, 26.0)):
        base.append({
            SYS_WHEN: now - 3600.0 + offset * 60.0,
            SYS_KIND: SYS_RESTART,
            SYS_SCOPE: "system",
            SYS_DURATION: span,
            SYS_DETAIL: None,
            SYS_DEVICES: None,
        })
    for offset, detail in enumerate((
        "muted_integrations",
        "ignored_integrations, maintenance_minutes",
        "excluded_integrations",
        "muted_integrations",
        "excluded_integrations",
    )):
        base.append({
            SYS_WHEN: now - 1800.0 + offset * 60.0,
            SYS_KIND: SYS_OPTIONS_CHANGED,
            SYS_SCOPE: "system",
            SYS_DURATION: None,
            SYS_DETAIL: detail,
            SYS_DEVICES: None,
        })
    for offset, span in enumerate((60.0, 180.0)):
        base.append({
            SYS_WHEN: now - 900.0 + offset * 60.0,
            SYS_KIND: SYS_BRIDGE_UP,
            SYS_SCOPE: "z2m",
            SYS_DURATION: span,
            SYS_DETAIL: None,
            SYS_DEVICES: None,
        })

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = read_brief(hass)
    short = text[text.index("## In Short"): text.index("## Now")]

    # Nothing abnormal happened, so nothing about the house is said
    # beyond the one thing a person did.
    assert "The system was unwatched" not in short
    assert "The system restarted" not in short
    assert "bridge" not in short
    # Named by their screen labels, deduplicated, said once.
    assert "Settings changed 5 times:" in short
    assert "Globally Muted Integrations" in short
    assert "Integrations to Exclude" in short
    assert "Maintenance Window in Minutes" in short
    assert short.count("Settings changed") == 1
    assert "excluded_integrations" not in short


async def test_one_long_outage_is_the_only_thing_said(
    hass: HomeAssistant, read_brief
):
    """Silence is the default; length is what earns a sentence."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_WHEN: now - 3600.0, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system",
         SYS_DURATION: 28.0, SYS_DETAIL: None, SYS_DEVICES: None},
        {SYS_WHEN: now - 1800.0, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m",
         SYS_DURATION: 120.0, SYS_DETAIL: None, SYS_DEVICES: None},
        {SYS_WHEN: now - 900.0, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m",
         SYS_DURATION: 1020.0, SYS_DETAIL: None, SYS_DEVICES: None},
    ]
    await hass.async_add_executor_job(coord._write_reports, "test")
    short = read_brief(hass)
    short = short[short.index("## In Short"): short.index("## Now")]

    assert "The z2m bridge was down for 17m" in short
    # The two-minute artefact and the 28-second restart say nothing.
    assert short.count("bridge") == 1
    assert "The system was unwatched" not in short


async def test_every_system_event_kind_has_a_sentence(
    hass: HomeAssistant,
):
    """No event kind may render as its own name (ruling #287).

    storage_shape was added to the events log by 0.15.2 and never
    given a branch in either renderer, so the brief read
    "storage_shape at Aug 17, 8:14 AM" in the one section written for
    a person, and the table below it read "The system | storage_shape".
    Both renderers end in a fallback that prints the raw kind, and
    nothing said which kinds were missing. This walks const.py, so a
    kind added tomorrow fails here rather than appearing in somebody's
    brief.
    """
    import custom_components.device_sentinel.const as const

    kinds = sorted(
        value
        for name, value in vars(const).items()
        if name.startswith("SYS_")
        and isinstance(value, str)
        and name
        not in (
            "SYS_WHEN",
            "SYS_KIND",
            "SYS_SCOPE",
            "SYS_SCOPE_SYSTEM",
            "SYS_DETAIL",
            "SYS_DURATION",
            "SYS_DEVICES",
        )
    )
    assert len(kinds) >= 15, "the kind list did not build"
    coord = await setup_coordinator(hass)
    writer = coord
    when = 1786970561.0
    missing_sentence = []
    missing_phrase = []
    for kind in kinds:
        row = {
            const.SYS_KIND: kind,
            const.SYS_SCOPE: "z2m",
            const.SYS_WHEN: when,
            const.SYS_DETAIL: "a detail",
            const.SYS_DURATION: 120.0,
            const.SYS_DEVICES: 3,
        }
        sentence = writer._system_event_sentence(row)
        phrase = writer._system_event_phrase(row)
        # The fallback has one shape, "<kind> at <when>.", so match
        # that rather than searching for the kind anywhere: "restart"
        # is a substring of the perfectly good sentence "The system
        # restarted at ...".
        if sentence.startswith(f"{kind} at "):
            missing_sentence.append(kind)
        if phrase == kind:
            missing_phrase.append(kind)
    assert not missing_sentence, (
        f"kinds rendering as their own name in prose: {missing_sentence}"
    )
    assert not missing_phrase, (
        f"kinds rendering as their own name in the table: {missing_phrase}"
    )


async def test_a_flapping_device_is_not_told_twice(hass: HomeAssistant):
    """A collapsed flood of flapping devices goes (ruling #304).

    Reproduced from 19 August. Two devices, SLZB-06 and Presence
    Guest, were revived by every one of the day's restarts, so each
    restart grouped them into "2 devices went unavailable at ...".
    The flapping collapse then dropped lines that started with a
    device name, which those do not, so the brief carried nine of
    them beside the two flapping sentences that already said it.
    Twelve sentences became three when the collapse was decided from
    the devices behind each line instead.
    """
    coord = await setup_coordinator(hass)
    first, _ = register_device(hass, "flap_a", name="SLZB-06")
    second, _ = register_device(hass, "flap_b", name="Presence Guest")
    coord._rebuild_registry_view()

    base = 1_787_000_000.0
    events = []
    pairs = []
    for index in range(3):
        at = base + index * 3600.0
        events.append(
            {SYS_WHEN: at, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system"}
        )
        for device in (first, second):
            opened = {
                INC_DEVICE_ID: device.id,
                INC_NAME: device.name,
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: at + 1.0,
                INC_DURATION: None,
            }
            closed = {
                INC_DEVICE_ID: device.id,
                INC_NAME: device.name,
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_RESOLVED,
                INC_WHEN: at + 61.0,
                INC_DURATION: 60.0,
            }
            pairs.append((opened, closed))

    told = coord._tell_episodes(pairs, events)

    # One sentence per flapping device and nothing else: the grouped
    # "2 devices ..." lines said the same thing in nine more.
    assert len(told) == 2
    assert not any(line.startswith("2 devices") for line in told)
    assert any(line.startswith("SLZB-06") for line in told)
    assert any(line.startswith("Presence Guest") for line in told)


async def test_a_real_outage_keeps_its_line(hass: HomeAssistant):
    """A flood is only dropped when every device in it is flapping.

    The other half of #304. An outage that took a steady device as
    well as a flapping one is news the flapping sentence does not
    carry, so its line stays.
    """
    coord = await setup_coordinator(hass)
    flapper, _ = register_device(hass, "flap_c", name="SLZB-06")
    steady, _ = register_device(hass, "steady_a", name="Door Laundry")
    coord._rebuild_registry_view()

    base = 1_787_000_000.0
    events = [{SYS_WHEN: base, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system"}]
    pairs = []
    for device in (flapper, steady):
        pairs.append((
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: device.name,
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: base + 1.0,
                INC_DURATION: None,
            },
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: device.name,
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_RESOLVED,
                INC_WHEN: base + 61.0,
                INC_DURATION: 60.0,
            },
        ))
    # The flapper alone goes down a second time, with no house event.
    pairs.append((
        {
            INC_DEVICE_ID: flapper.id,
            INC_NAME: flapper.name,
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: base + 7200.0,
            INC_DURATION: None,
        },
        {
            INC_DEVICE_ID: flapper.id,
            INC_NAME: flapper.name,
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_RESOLVED,
            INC_WHEN: base + 7260.0,
            INC_DURATION: 60.0,
        },
    ))

    told = coord._tell_episodes(pairs, events)
    assert any("2 devices" in line for line in told)
    assert any(line.startswith("SLZB-06") for line in told)


async def test_repeat_offenders_count_only_unexplained(
    hass: HomeAssistant,
):
    """A device revived by every restart earns no line (ruling #305).

    Counting every opening made the nightly reboot the loudest thing
    on the reference fleet: 71 devices at exactly two openings each.
    The filter is the detector, so an opening a restart covers must
    not count, and a device whose every interruption had no
    explanation must.
    """
    coord = await setup_coordinator(hass)
    explained, _ = register_device(hass, "ro1", name="Reboot Rider")
    flapper, _ = register_device(hass, "ro2", name="True Flapper")
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    incidents = []
    events = []
    for index in range(3):
        at = now - (index + 1) * 7200.0
        events.append(
            {SYS_WHEN: at, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system"}
        )
        # One opening inside the restart window: explained.
        incidents.append(
            {
                INC_DEVICE_ID: explained.id,
                INC_NAME: "Reboot Rider",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: at + 10.0,
                INC_DURATION: None,
            }
        )
        # One opening two hours from any event: unexplained.
        incidents.append(
            {
                INC_DEVICE_ID: flapper.id,
                INC_NAME: "True Flapper",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: at + 3600.0,
                INC_DURATION: None,
            }
        )
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = events

    rows = coord._repeat_offender_rows(now)

    assert len(rows) == 1
    assert rows[0]["name"] == "True Flapper"
    assert rows[0]["n"] == 3
    assert all(row["name"] != "Reboot Rider" for row in rows)


async def test_the_repeat_line_says_the_spread(hass: HomeAssistant):
    """"18 over 6 days" and "15 all on one day" read differently.

    The reader must not need arithmetic to tell a failing device
    from one bad afternoon (ruling #305), so the line carries the
    count, the days, and the worst day.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "ro3", name="One Bad Day")
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    incidents = [
        {
            INC_DEVICE_ID: device.id,
            INC_NAME: "One Bad Day",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: now - 90000.0 - index * 60.0,
            INC_DURATION: None,
        }
        for index in range(4)
    ]
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = []

    rows = coord._repeat_offender_rows(now)
    assert len(rows) == 1
    assert len(rows[0]["days"]) == 1


async def test_the_repeat_floor_is_the_slider(hass: HomeAssistant):
    """Below the floor a device is not named; the slider moves it."""
    from custom_components.device_sentinel.const import (
        CONF_REPEAT_FLOOR,
    )

    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "ro4", name="Twice Device")
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [
        {
            INC_DEVICE_ID: device.id,
            INC_NAME: "Twice Device",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: now - 40000.0 - index * 50000.0,
            INC_DURATION: None,
        }
        for index in range(2)
    ]
    coord.data[DATA_SYSTEM_EVENTS] = []

    # Default floor 2: two unexplained openings are named.
    assert len(coord._repeat_offender_rows(now)) == 1

    # Floor raised to 3: the same record earns no line.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_REPEAT_FLOOR: 3},
    )
    assert coord._repeat_offender_rows(now) == []


async def test_a_multi_day_pattern_earns_both_sentences(
    hass: HomeAssistant,
):
    """The suppression is for one-day patterns only (ruling #305).

    A device flapping today whose unexplained record spans several
    days is exactly what the repeat line exists to show, so it keeps
    its line beside today's flapping sentence, while a device whose
    whole record is today is said once.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "ro5", name="Week Flapper")
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    incidents = []
    # Two openings today, resolved, so the flapping sentence fires.
    for index in range(2):
        at = now - 3600.0 - index * 1800.0
        incidents.append(
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: "Week Flapper",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: at,
                INC_DURATION: None,
            }
        )
        incidents.append(
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: "Week Flapper",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_RESOLVED,
                INC_WHEN: at + 60.0,
                INC_DURATION: 60.0,
            }
        )
    # And two more openings three days ago.
    for index in range(2):
        incidents.append(
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: "Week Flapper",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: now - 3 * 86400.0 - index * 1800.0,
                INC_DURATION: None,
            }
        )
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = []

    prose = "\n".join(
        coord._brief_prose(
            [r for r in incidents if r[INC_WHEN] >= now - 86400.0],
            [],
            now - 86400.0,
            [],
        )
    )
    assert "went unavailable twice" in prose
    # The repeat offenders left In Short for their own section
    # (ruling #374), so the prose carries the flapping sentence only.
    assert "unexplained" not in prose
    # The multi-day pattern keeps its row beside today's sentence.
    rows = coord._repeat_offender_rows(now)
    assert len(rows) == 1
    assert rows[0]["n"] == 4


def _incident_row(device, kind, event, when, cause=None, duration=None):
    """One incident row shaped as the coordinator stores them."""
    return {
        INC_DEVICE_ID: device.id,
        INC_NAME: device.name,
        INC_KIND: kind,
        INC_EVENT: event,
        INC_WHEN: when,
        INC_CAUSE: cause,
        INC_DURATION: duration,
    }


async def test_an_acknowledgment_never_joins_a_flapping_count(
    hass: HomeAssistant,
):
    """An action row is not a going, and resolved is not still down.

    Reproduced from the 25 August brief. Three devices railed at
    7:28, were acknowledged at 7:29, and the rail resolved at the
    midnight fold; one also went unavailable for 22 seconds. The
    flapping collapse counted the acknowledgment as an unresolved
    opening, so a fully recovered device read "went silent 3 times
    and is still silent". The pairing already states the rule this
    asserts: an acknowledgment is not an opening at all.
    """
    coord = await setup_coordinator(hass)
    plug, _ = register_device(hass, "ack_plug", name="Plug Living Room Router")
    left, _ = register_device(hass, "ack_wdl", name="Window Dining Room Left")
    coord._rebuild_registry_view()

    open_at = 1_787_142_482.0
    fold_at = 1_787_202_000.0
    rows = []
    for device in (plug, left):
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_OPENED, open_at))
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_ACTION,
            open_at + 68.0, cause=ACTION_ACKNOWLEDGED))
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_RESOLVED,
            fold_at, duration=fold_at - open_at))
    rows.append(_incident_row(
        plug, TODO_KIND_UNAVAILABLE, INCIDENT_OPENED, open_at + 1140.0))
    rows.append(_incident_row(
        plug, TODO_KIND_UNAVAILABLE, INCIDENT_RESOLVED,
        open_at + 1162.0, duration=22.0))

    told = coord._tell_episodes(coord._pair_incidents(rows), [])
    joined = " ".join(told)

    assert "still silent" not in joined
    assert "still railed" not in joined
    assert "went silent" not in joined
    # Each episode reads as what happened, on its own.
    assert any(
        line.startswith("Plug Living Room Router signal railed")
        and "recovered" in line
        for line in told
    )
    assert any(
        line.startswith("Window Dining Room Left signal railed")
        and "recovered" in line
        for line in told
    )
    assert any(
        "went unavailable" in line and "recovered 22s later" in line
        for line in told
    )
    # The acknowledgments keep their own sentences rather than
    # riding into a count.
    assert sum("acknowledged" in line for line in told) == 2


async def test_a_railed_device_flaps_in_rail_words(hass: HomeAssistant):
    """Two rail episodes read as railed, never as silent.

    A railed device reports the whole time, so the freeze verbs say
    the opposite of what happened.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "rail_flap", name="Window Office")
    coord._rebuild_registry_view()

    base = 1_787_000_000.0
    rows = []
    for index in range(2):
        at = base + index * 7200.0
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_OPENED, at))
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_RESOLVED,
            at + 3600.0, duration=3600.0))

    told = coord._tell_episodes(coord._pair_incidents(rows), [])

    assert told == [
        "Window Office signal railed twice and recovered each time, "
        "railed for 2.0h in total."
    ]


async def test_kinds_flap_separately_on_one_device(hass: HomeAssistant):
    """A device flapping in two kinds gets one sentence per kind.

    Buckets carry the kind beside the device, so a rail and an
    unavailability no longer share one sentence and one verb.
    """
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "two_kinds", name="Plug Office")
    coord._rebuild_registry_view()

    base = 1_787_000_000.0
    rows = []
    for index in range(2):
        at = base + index * 7200.0
        rows.append(_incident_row(
            device, TODO_KIND_UNAVAILABLE, INCIDENT_OPENED, at))
        rows.append(_incident_row(
            device, TODO_KIND_UNAVAILABLE, INCIDENT_RESOLVED,
            at + 60.0, duration=60.0))
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_OPENED, at + 300.0))
        rows.append(_incident_row(
            device, TODO_KIND_RAILED_SIGNAL, INCIDENT_RESOLVED,
            at + 3900.0, duration=3600.0))

    told = coord._tell_episodes(coord._pair_incidents(rows), [])

    assert len(told) == 2
    assert any(
        line.startswith("Plug Office went unavailable twice")
        and "unavailable for 2m in total" in line
        for line in told
    )
    assert any(
        line.startswith("Plug Office signal railed twice")
        and "railed for 2.0h in total" in line
        for line in told
    )


# 0.19.12: the daily brief improvement update (rulings #373 to #377).


async def test_the_brief_prints_the_current_name(hass: HomeAssistant):
    """A renamed device is named as it is now (ruling #373).

    The stored name stays in the record, because it is what was true
    then, and nothing shown to a reader uses it.
    """
    device, _entity_id, _ = _register(hass, "rn1", "Old Name")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [
        {
            INC_DEVICE_ID: device.id,
            INC_NAME: "Old Name",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: now - 3600.0,
            INC_DURATION: None,
        }
    ]
    dr.async_get(hass).async_update_device(
        device.id, name_by_user="New Name"
    )
    coord._rebuild_registry_view()

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "New Name" in text
    assert "Old Name" not in text


async def test_a_gone_device_keeps_its_stored_name(
    hass: HomeAssistant,
):
    """A device the registry no longer knows falls back to the
    stored name, because what was true then still beats a hex id
    (ruling #373)."""
    coord = await setup_coordinator(hass)
    row = {
        INC_DEVICE_ID: "gone0123456789abcdef",
        INC_NAME: "Departed Sensor",
        INC_KIND: TODO_KIND_UNAVAILABLE,
        INC_EVENT: INCIDENT_OPENED,
        INC_WHEN: dt_util.utcnow().timestamp() - 100.0,
        INC_DURATION: None,
    }
    assert coord._told_name(row) == "Departed Sensor"


async def test_repeat_offenders_are_a_table_below_now(
    hass: HomeAssistant,
):
    """The section takes its own heading with the ruled columns and
    the verbatim paragraph beneath (ruling #374)."""
    device, _entity_id, _ = _register(hass, "rt1", "Closet Switch")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    incidents = []
    for index in range(2):
        at = now - 40000.0 - index * 90000.0
        incidents.append(
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: "Closet Switch",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: at,
                INC_DURATION: None,
            }
        )
        incidents.append(
            {
                INC_DEVICE_ID: device.id,
                INC_NAME: "Closet Switch",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_RESOLVED,
                INC_WHEN: at + 720.0,
                INC_DURATION: 720.0,
            }
        )
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = []

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "## Repeat Offenders" in text
    assert text.index("## Now") < text.index("## Repeat Offenders")
    assert (
        "| DEVICE | WHAT HAPPENED | TIMES | WHEN | TYPICAL | WITH |"
        in text
    )
    assert "| Closet Switch | went unavailable | 2 |" in text
    assert "| 12m | alone |" in text
    assert "This table lists repeat offenders." in text
    # The paragraph states the same number the code reads, so one
    # cannot drift from the other (ruling #378).
    assert "the last seven days" in text
    assert "fourteen" not in text
    assert "Keeps failing on its own" not in text


async def test_with_says_every_time_only_when_it_matched(
    hass: HomeAssistant,
):
    """WITH names the device that failed in the same second, and
    says "every time" only when it matched every time (#374)."""
    first, _e1, source = _register(hass, "wp1", "Motion J")
    second, _e2, _ = _register(hass, "wp2", "Wave J", source=source)
    third, _e3, _ = _register(hass, "wp3", "Loner", source=source)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    base = now - 90000.0
    incidents = []
    for device, name in ((first, "Motion J"), (second, "Wave J")):
        for index in range(3):
            incidents.append(
                {
                    INC_DEVICE_ID: device.id,
                    INC_NAME: name,
                    INC_KIND: TODO_KIND_UNAVAILABLE,
                    INC_EVENT: INCIDENT_OPENED,
                    INC_WHEN: base + index * 7000.0,
                    INC_DURATION: None,
                }
            )
    for index in range(2):
        incidents.append(
            {
                INC_DEVICE_ID: third.id,
                INC_NAME: "Loner",
                INC_KIND: TODO_KIND_UNAVAILABLE,
                INC_EVENT: INCIDENT_OPENED,
                INC_WHEN: base + 3000.0 + index * 11111.0,
                INC_DURATION: None,
            }
        )
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = []

    rows = {
        row["name"]: row for row in coord._repeat_offender_rows(now)
    }
    assert rows["Motion J"]["with"] == "Wave J, every time"
    assert rows["Wave J"]["with"] == "Motion J, every time"
    assert rows["Loner"]["with"] == "alone"


async def test_one_shared_second_is_not_a_partner(
    hass: HomeAssistant,
):
    """A device matching once out of many is a coincidence, not a
    shared cause, and is not named (ruling #374)."""
    first, _e1, source = _register(hass, "cf1", "Steady Failer")
    second, _e2, _ = _register(hass, "cf2", "Passer By", source=source)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    base = now - 300000.0
    incidents = [
        {
            INC_DEVICE_ID: first.id,
            INC_NAME: "Steady Failer",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: base + index * 9000.0,
            INC_DURATION: None,
        }
        for index in range(4)
    ]
    # Two openings, one of which lands on the other device's second.
    incidents += [
        {
            INC_DEVICE_ID: second.id,
            INC_NAME: "Passer By",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: when,
            INC_DURATION: None,
        }
        for when in (base, base + 4500.0)
    ]
    coord.data[DATA_INCIDENTS] = incidents
    coord.data[DATA_SYSTEM_EVENTS] = []

    rows = {
        row["name"]: row for row in coord._repeat_offender_rows(now)
    }
    assert rows["Steady Failer"]["with"] == "alone"


async def test_a_storm_inside_a_restart_is_the_restart(
    hass: HomeAssistant,
):
    """The storm rows a restart explains leave the summary and the
    table; a storm on its own keeps them (ruling #375)."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    events = [
        # A storm running into a restart: the last seconds before
        # Home Assistant went down.
        {
            SYS_WHEN: now - 646.0,
            SYS_KIND: "storm_open",
            SYS_SCOPE: "mqtt",
        },
        {
            SYS_WHEN: now - 638.0,
            SYS_KIND: "storm_closed",
            SYS_SCOPE: "mqtt",
            SYS_DEVICES: 74,
        },
        {
            SYS_WHEN: now - 600.0,
            SYS_KIND: SYS_RESTART,
            SYS_SCOPE: "system",
            SYS_DURATION: 28.0,
        },
        # A storm hours from any restart: its own event.
        {
            SYS_WHEN: now - 7200.0,
            SYS_KIND: "storm_open",
            SYS_SCOPE: "zha",
        },
        {
            SYS_WHEN: now - 7190.0,
            SYS_KIND: "storm_closed",
            SYS_SCOPE: "zha",
            SYS_DEVICES: 12,
        },
    ]
    coord.data[DATA_SYSTEM_EVENTS] = events

    suppressed = coord._storms_inside_restart(events)
    kept = [row for row in events if row not in suppressed]
    scopes = {row.get(SYS_SCOPE) for row in suppressed}
    assert scopes == {"mqtt"}
    assert len(suppressed) == 2
    assert sum(
        1 for row in kept if row.get(SYS_KIND) == "storm_open"
    ) == 1

    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "The mqtt integration reloaded" not in text
    assert "The zha integration reloaded" in text


async def test_a_clean_stop_is_named_clean(hass: HomeAssistant):
    """The gap ends at the time given, and a clean stop says so
    (ruling #376)."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {
            SYS_WHEN: now - 3600.0,
            SYS_KIND: SYS_RESTART,
            SYS_SCOPE: "system",
            SYS_DURATION: 960.0,
        }
    ]
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert (
        "The system was shut down cleanly and was unwatched for "
        "16m, ending" in text
    )
    assert "was unwatched for 16m at " not in text


async def test_an_unclean_stop_says_what_it_cost(
    hass: HomeAssistant,
):
    """The unclean line names the shutdown moment, the gap and the
    timers restarted, and stops (ruling #376). The clean sentence is
    not said of it."""
    from custom_components.device_sentinel.const import (
        SYS_UNCLEAN_RESTART,
    )

    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {
            SYS_WHEN: now - 3600.0,
            SYS_KIND: SYS_RESTART,
            SYS_SCOPE: "system",
            SYS_DURATION: 120.0,
        },
        {
            SYS_WHEN: now - 3600.0,
            SYS_KIND: SYS_UNCLEAN_RESTART,
            SYS_SCOPE: "system",
            SYS_DURATION: 120.0,
            SYS_DETAIL: "96 devices reset",
        },
    ]
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Home Assistant did not shut down cleanly at " in text
    assert (
        "2m went unwatched and 96 devices had their silence "
        "timers restarted." in text
    )
    assert "shut down cleanly and was unwatched" not in text
    assert "That restart followed an unclean shutdown" not in text


async def test_no_repeat_offenders_prints_no_section(
    hass: HomeAssistant,
):
    """An empty table shows nothing at all, not an all-clear
    (ruling #374 as ruled on 2 September)."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_INCIDENTS] = []
    coord.data[DATA_SYSTEM_EVENTS] = []
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Repeat Offenders" not in text
    assert "This table lists repeat offenders" not in text


async def test_the_repeat_window_matches_its_paragraph(
    hass: HomeAssistant,
):
    """An opening older than the window is not on the table, and the
    paragraph names the same number the code reads (ruling #378)."""
    from custom_components.device_sentinel.const import (
        REPEAT_WINDOW_DAYS,
    )
    from custom_components.device_sentinel.report_brief import (
        _REPEAT_PARAGRAPH,
    )

    assert REPEAT_WINDOW_DAYS == 7.0
    assert "seven days" in _REPEAT_PARAGRAPH

    device, _entity_id, _ = _register(hass, "rw1", "Old Noise")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_INCIDENTS] = [
        {
            INC_DEVICE_ID: device.id,
            INC_NAME: "Old Noise",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: now - (REPEAT_WINDOW_DAYS + 1.0) * 86400.0
            - index * 3600.0,
            INC_DURATION: None,
        }
        for index in range(3)
    ]
    coord.data[DATA_SYSTEM_EVENTS] = []
    assert coord._repeat_offender_rows(now) == []
