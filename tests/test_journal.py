# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_journal.py, Version: 0.16.2 (2026-08-19)

"""The forensic record: incidents, episodes, and system events.

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
    TODO_KIND_LOW_BATTERY,
    ACTION_ACKNOWLEDGED,
    ACTION_DELETED,
    ACTION_READDED,
    ACTION_UNACKNOWLEDGED,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
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
    INCIDENT_ACKNOWLEDGED,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    RECOVERY_CAUSE_UNOBSERVED,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_EPOCH_RESET,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_SCOPE_SYSTEM,
    SYS_UNCLEAN_RESTART,
    SYS_WHEN,
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


def _causes(coord, cause):
    return [
        row
        for row in coord.data[DATA_INCIDENTS]
        if row[INC_EVENT] == INCIDENT_ACTION
        and row.get(INC_CAUSE) == cause
    ]


async def test_the_unclean_restart_reads_as_english(
    hass: HomeAssistant
):
    """The brief must not print the storage key.

    0.10.11 added the event and not its wording, so the composer fell
    through to its last line and the brief read a bare
    "unclean_restart" in both the prose and the table. Harmless to
    judgment, and the first thing anyone reads on the morning after a
    real one, which is exactly when the wording should be working.
    """
    coord = await setup_coordinator(hass)
    coord.data[DATA_SYSTEM_EVENTS] = [
        {
            SYS_WHEN: dt_util.utcnow().timestamp() - 300.0,
            SYS_KIND: SYS_UNCLEAN_RESTART,
            SYS_SCOPE: SYS_SCOPE_SYSTEM,
            SYS_DETAIL: "120 devices reset",
            SYS_DURATION: 2640.0,
        }
    ]
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _brief_text(hass)

    assert SYS_UNCLEAN_RESTART not in text
    assert "unclean shutdown" in text
    assert "120 devices reset" in text
    # Asserted against the sentence itself, not the file. The table
    # row carries the count too, so a whole-file search passes even
    # when the prose has dropped it, and the prose is what gets read
    # first on the morning after.
    sentence = coord._system_event_sentence(
        coord.data[DATA_SYSTEM_EVENTS][0]
    )
    assert "120 devices reset" in sentence
    assert "unclean shutdown" in sentence


async def test_every_system_event_kind_has_wording(
    hass: HomeAssistant
):
    """The gate that would have caught 0.10.11's omission.

    The composer names each kind and falls through to the raw key for
    anything it does not know, so a kind added without wording is
    silent until it appears in somebody's brief. This walks every kind
    the integration can write and fails on any that still reads as its
    own storage key.
    """
    coord = await setup_coordinator(hass)
    kinds = (
        SYS_RESTART,
        SYS_UNCLEAN_RESTART,
        SYS_BRIDGE_DOWN,
        SYS_BRIDGE_UP,
        SYS_PAIRING_OPEN,
        SYS_PAIRING_CLOSED,
        SYS_EPOCH_RESET,
        SYS_OPTIONS_CHANGED,
    )
    for kind in kinds:
        row = {
            SYS_WHEN: dt_util.utcnow().timestamp(),
            SYS_KIND: kind,
            SYS_SCOPE: SYS_SCOPE_SYSTEM,
            SYS_DETAIL: None,
            SYS_DURATION: 60.0,
        }
        sentence = coord._system_event_sentence(row)
        cell = coord._system_event_phrase(row)
        # The fallbacks the composer uses for a kind it does not
        # know, matched exactly rather than as substrings: "restart"
        # lives inside the perfectly good sentence "The system
        # restarted", so a substring test would fail on wording that
        # is correct.
        assert not sentence.startswith(f"{kind} at "), (
            f"{kind} has no sentence"
        )
        assert cell != kind, f"{kind} has no table wording"


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
    """The check lands on the timeline as an action, not as a
    problem event. Rewritten in 0.10.4: it used to assert the
    retired INCIDENT_ACKNOWLEDGED event."""
    device, entity_id, _ = _register(hass, "a1", "Acked Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    assert len(_causes(coord, ACTION_ACKNOWLEDGED)) == 1
    assert _events(coord, INCIDENT_ACKNOWLEDGED) == []


async def test_unacknowledgement_is_recorded_too(hass: HomeAssistant):
    """Unticking the box is a thing a person did and the record has
    to say so. Recording only the check left a brief saying a device
    was acknowledged with nothing to say it had been taken back."""
    device, entity_id, _ = _register(hass, "u1", "Unacked Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await coord.async_todo_update(uid=uid, status="needs_action")

    assert len(_causes(coord, ACTION_UNACKNOWLEDGED)) == 1
    assert coord.todo_items[0]["status"] == "needs_action"
    assert coord.todo_items[0]["acked_at"] is None


async def test_the_brief_says_the_acknowledgment_was_removed(
    hass: HomeAssistant,
):
    """The sentence, not just the row: an event the composer has no
    branch for falls through to the kind wording and would announce
    a discovery that never happened."""
    device, entity_id, _ = _register(hass, "u2", "Sentence Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await coord.async_todo_update(uid=uid, status="needs_action")

    row = _causes(coord, ACTION_UNACKNOWLEDGED)[0]
    line = coord._compose_event(row)
    assert "acknowledgment removed" in line
    assert "stopped reporting" not in line
    assert "discovered" not in line


async def test_a_hand_deletion_is_recorded(hass: HomeAssistant):
    """Deleting a row is a thing a person did, and without it on the
    record the same device simply appears twice."""
    device, entity_id, _ = _register(hass, "d1", "Deleted Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]

    await coord.async_todo_delete([uid])

    assert len(_causes(coord, ACTION_DELETED)) == 1
    assert coord.todo_items == []


async def test_the_re_add_is_a_re_add_and_not_a_new_detection(
    hass: HomeAssistant,
):
    """The fault never stopped, so nothing opened. Calling the return
    an opening put a second opening on a key that already had one
    pending, which orphaned the first and left a real episode
    rendering as though it had never resolved."""
    device, entity_id, _ = _register(hass, "d2", "Readded Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    opened_before = len(_events(coord, INCIDENT_OPENED))
    uid = coord.todo_items[0]["uid"]

    await coord.async_todo_delete([uid])
    coord._sync_problem_list()

    assert len(coord.todo_items) == 1, "the row did not come back"
    assert len(_causes(coord, ACTION_READDED)) == 1
    assert len(_events(coord, INCIDENT_OPENED)) == opened_before


async def test_a_deletion_and_its_re_add_are_one_sentence(
    hass: HomeAssistant,
):
    """Told the way an opening and its recovery are, and it says why
    the row came back, because that is the moment a reader wants to
    know that deleting does not silence anything."""
    device, entity_id, _ = _register(hass, "d3", "Folded Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_delete([uid])
    coord._sync_problem_list()

    rows = [
        row
        for row in coord.data[DATA_INCIDENTS]
        if row[INC_EVENT] == INCIDENT_ACTION
    ]
    units = coord._pair_incidents(rows)
    assert len(units) == 1, "the deletion and its re-add did not fold"
    opened, second = units[0]
    assert second is not None
    line = coord._compose_episode(opened, second)
    assert "deleted from the list" in line
    assert "re-added because the problem is still there" in line


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
    assert resolved[-1][INC_KIND] == TODO_KIND_LOW_BATTERY
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


async def test_diagnostics_carry_the_support_fields(
    hass: HomeAssistant,
):
    """last_version, the awaiting counts, and per-device entities.

    The three additions of ruling #305, each closing a question the
    first external fleet's files could not answer: whether an
    upgrade start was detected, whether the enable buttons have work
    waiting, and whether a silent device is off, disabled, or
    unheard.
    """
    from homeassistant.helpers import entity_registry as er

    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, entity_id, _ = _register(hass, "d2", "Support Sensor")
    ent_reg = er.async_get(hass)
    ent_reg.async_update_entity(
        entity_id, device_class="battery", unit_of_measurement="%"
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "77")

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["storage"]["last_version"] == coord.version
    assert set(diag["awaiting_enable"]) == {
        "signal",
        "last_seen",
        "battery",
    }
    rows = diag["devices"][device.id]["entities"]
    battery_rows = [r for r in rows if r["kind"] == "battery"]
    assert battery_rows and battery_rows[0]["entity_id"] == entity_id
    assert battery_rows[0]["disabled_by"] is None
    assert battery_rows[0]["state"] == "77"
