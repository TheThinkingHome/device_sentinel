# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v070_incidents_brief.py, Version: 0.7.5 (2026-07-23)

"""0.7.0 tests: the incident log and the daily brief document.

The memory first: a problem's whole life on one timeline, opened,
resolved with its duration and cause, acknowledged. Then the one
report written for a person, which reads that timeline and says what
is wrong now and what happened in the last 24 hours, in language
that needs no knowledge of the integration's internals.
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
    INCIDENT_ACKNOWLEDGED,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
)

DOMAIN = "device_sentinel"


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


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _brief_text(hass):
    """Return the brief that was written, whatever its name.

    Named for the day its window opened, which is not today's date
    when the window began before the brief hour (0.7.5).
    """
    import glob

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


async def test_opening_and_resolution_land_on_the_timeline(
    hass: HomeAssistant,
):
    """A problem's whole life: opened when detected, resolved when it
    clears, with the duration computed from its own opening."""
    device, entity_id = _register(hass, "t1", "Timeline Sensor")
    coord = await _coordinator(hass)
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
    device, entity_id = _register(hass, "a1", "Acked Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    assert len(_events(coord, INCIDENT_ACKNOWLEDGED)) == 1


async def test_resolution_borrows_its_cause(hass: HomeAssistant):
    """A silence that ended on its own says so; the cause comes from
    the episode record rather than a guess."""
    device, entity_id = _register(hass, "c1", "Caused Sensor")
    coord = await _coordinator(hass)
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
    assert resolved[-1][INC_CAUSE] == "on its own"


async def test_battery_resolution_has_no_cause(hass: HomeAssistant):
    """Only a silence has a lever to credit."""
    device, entity_id = _register(hass, "b1", "Battery Sensor", True)
    coord = await _coordinator(hass)
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


async def test_brief_has_both_sections_in_plain_language(
    hass: HomeAssistant,
):
    device, entity_id = _register(hass, "w1", "Brief Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = _brief_text(hass)
    assert "# Device Sentinel daily brief" in text
    assert "## Now" in text and "## Last 24 hours" in text
    assert "Brief Sensor" in text
    assert "stopped reporting" in text     # never the raw category
    assert "frozen" not in text
    assert "basis" not in text and "window" not in text


async def test_regenerated_brief_says_it_is_incomplete(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _brief_text(hass)
    assert "(incomplete)" in text
    assert "Nothing needs attention." in text


async def test_excluded_devices_never_reach_the_brief(
    hass: HomeAssistant,
):
    """It is a report, so exclusion suppresses it here."""
    device, entity_id = _register(hass, "x1", "Hidden Sensor")
    coord = await _coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    hass.states.async_set(entity_id, "21.5")
    coord._record_incident(
        device.id, "Hidden Sensor", "frozen", INCIDENT_OPENED
    )
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = _brief_text(hass)
    assert "Hidden Sensor" not in text


async def test_incidents_reach_diagnostics(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, entity_id = _register(hass, "d1", "Diag Sensor")
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

    device, entity_id = _register(hass, "s1", "Restart Sensor")
    coord = await _coordinator(hass)
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
    device, entity_id = _register(hass, "g1", "Grace Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 8 * 3600
    coord._grace_until = dt_util.utcnow().timestamp() + 60.0
    coord._judge_all_devices()
    assert coord.data["silence_episodes"] == []
