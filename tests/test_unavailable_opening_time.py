# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_unavailable_opening_time.py, Version: 0.27.3 (2026-10-24)

"""A device that became unavailable is dated from when it went.

James's rig on 24 October 2026: Last 24 Hours read "became unavailable"
at 3:10:46 and "recovered after 15m" at 3:22:03, eleven minutes apart.
The device went at 3:07:05; it is listed only once it has been gone past
the debounce and the sweep has seen it, and its recovery counts from
when it went (#644). The opening row now keeps when it went, and the
table, the dashboard and the sentence date it from there.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    INC_EVENT,
    INC_KIND,
    INC_SINCE,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
)

from .helpers import setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk


def _plug(hass, source, uid):
    reg = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("shelly", uid)}, name=f"Plug {uid}")
    main = reg.async_get_or_create("switch", "shelly", f"{uid}_main", device_id=device.id, config_entry=source).entity_id
    power = reg.async_get_or_create("sensor", "shelly", f"{uid}_pw", device_id=device.id, config_entry=source).entity_id
    return device, (main, power)


async def _went_and_came_back(hass, freezer):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="shelly", title="Shelly")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    plugs = [_plug(hass, source, f"p{i}") for i in range(3)]
    for _, ids in plugs:
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for device, _ in plugs:
        arm(coord, device.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for k in range(3):
        for _, ids in plugs:
            hass.states.async_set(ids[1], str(10 + k))
        await walk(hass, freezer, 600)
    device, ids = plugs[0]
    went = dt_util.utcnow().timestamp()
    for entity_id in ids:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    for k in range(15):
        for _, others in plugs[1:]:
            hass.states.async_set(others[1], str(20 + k))
        await walk(hass, freezer, 60)
    hass.states.async_set(ids[0], "on")
    hass.states.async_set(ids[1], "11")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    rows = [
        row for row in coord.data.get(DATA_INCIDENTS) or []
        if row.get("device_id") == device.id and row[INC_KIND] == "unavailable"
    ]
    return coord, device, went, rows


async def test_the_opening_keeps_when_the_device_went(hass: HomeAssistant, freezer):
    coord, _, went, rows = await _went_and_came_back(hass, freezer)
    opened = next(row for row in rows if row[INC_EVENT] == INCIDENT_OPENED)
    resolved = next(row for row in rows if row[INC_EVENT] == INCIDENT_RESOLVED)
    # Listed past the debounce, and the sweep sees it up to a minute late.
    assert opened[INC_WHEN] - went >= 180, rows
    assert abs(opened[INC_SINCE] - went) <= 1, rows
    # So the opening and the recovery agree: went plus its time down.
    assert abs(coord._began_at(opened) + resolved["duration"] - resolved[INC_WHEN]) <= 1, rows


async def test_the_table_and_the_sentence_say_when_it_went(hass: HomeAssistant, freezer):
    coord, _, went, rows = await _went_and_came_back(hass, freezer)
    opened = next(row for row in rows if row[INC_EVENT] == INCIDENT_OPENED)
    clock = coord._clock(went)
    assert clock != coord._clock(opened[INC_WHEN]), "the test needs the two minutes apart"
    assert coord._opening_clause(opened).endswith(f"became unavailable at {clock}")
    day = dt_util.as_local(dt_util.utcnow()).date()
    page = coord.dashboard_brief(day)
    told = [e for e in page["events"] if e["what"] == "became unavailable"]
    assert told and dt_util.parse_datetime(told[0]["when"]).timestamp() == coord._began_at(opened)


async def test_a_row_from_before_has_no_since_and_reads_as_it_did(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    row = {INC_EVENT: INCIDENT_OPENED, INC_KIND: "unavailable", INC_WHEN: 100000.0, "device_id": "x"}
    assert coord._began_at(row) == 100000.0
    # Nor is a since later than the row, far before it, or not a real
    # moment ever used (adversarial round).
    for since in (200000.0, 100000.0 - 4 * 86400, 0.0, float("-inf"), float("nan")):
        assert coord._began_at({**row, INC_SINCE: since}) == 100000.0, since
    assert coord._began_at({**row, INC_SINCE: 99800.0}) == 99800.0


async def test_a_start_held_under_a_mute_is_not_kept(hass: HomeAssistant):
    """A device unavailable and muted for unavailable since 20 October,
    whose mute is lifted on 24 October, is listed on the 24th: its
    opening keeps the listing time, not a start four days back, which
    the brief would read as today (adversarial round of 0.27.3)."""
    from custom_components.device_sentinel.const import DEV_DOWN_BEGAN_AS

    from .helpers import register_device

    device, _ = register_device(hass, "m1", "Plug Muted")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id][DEV_DOWN_BEGAN_AS] = "unavailable"
    now = dt_util.utcnow().timestamp()
    coord._record_incident(device.id, "Plug Muted", "unavailable", INCIDENT_OPENED, since=now - 4 * 86400)
    first = [r for r in coord.data[DATA_INCIDENTS] if r.get("device_id") == device.id][-1]
    assert INC_SINCE not in first
    coord.data[DATA_INCIDENTS].remove(first)
    coord._record_incident(device.id, "Plug Muted", "unavailable", INCIDENT_OPENED, since=now - 221)
    second = [r for r in coord.data[DATA_INCIDENTS] if r.get("device_id") == device.id][-1]
    assert second[INC_SINCE] == now - 221


async def test_a_group_is_told_from_when_the_first_went(hass: HomeAssistant):
    """The sentence for several devices dates them as the table does
    (adversarial round of 0.27.3): from when the first one went, not
    when the first one was listed."""
    from .test_attribution import BROKER_OUTAGE, T0, _incident

    coord = await setup_coordinator(hass)
    pairs = []
    for index in range(3):
        device_id = f"g{index}"
        coord._watched[device_id] = "mqtt"
        opened = {**_incident(device_id, f"Group {index}", T0 + 400), INC_SINCE: T0 + 30 + index}
        closed = _incident(device_id, f"Group {index}", T0 + 1024, event=INCIDENT_RESOLVED)
        pairs.append((opened, closed))
    told = coord._tell_episodes(pairs, BROKER_OUTAGE)
    assert coord._clock(T0 + 30) != coord._clock(T0 + 400)
    assert told[0].startswith(f"3 devices became unavailable at {coord._clock(T0 + 30)},"), told


async def test_a_group_never_reported_is_said_in_words(hass: HomeAssistant):
    """Tim Plas's brief read "13 devices never_reported at 9:58 AM"
    (found by the reports of 0.27.3)."""
    from custom_components.device_sentinel.const import TODO_KIND_NEVER_REPORTED

    from .test_attribution import BROKER_OUTAGE, T0, _incident

    coord = await setup_coordinator(hass)
    pairs = []
    for index in range(3):
        device_id = f"n{index}"
        coord._watched[device_id] = "mqtt"
        pairs.append(({**_incident(device_id, f"Never {index}", T0 + 60), INC_KIND: TODO_KIND_NEVER_REPORTED}, None))
    told = " ".join(coord._tell_episodes(pairs, BROKER_OUTAGE))
    assert "never_reported" not in told, told
    assert "3 devices were listed as never reported at " in told, told


async def test_a_group_with_a_low_battery_is_said_in_words(hass: HomeAssistant):
    """Lowering the threshold reloads Device Sentinel and can list several
    cells at once: "3 devices low_battery at ..." (adversarial round)."""
    from custom_components.device_sentinel.const import TODO_KIND_LOW_BATTERY

    from .test_attribution import BROKER_OUTAGE, T0, _incident

    coord = await setup_coordinator(hass)
    pairs = []
    for index in range(3):
        device_id = f"b{index}"
        coord._watched[device_id] = "mqtt"
        pairs.append(({**_incident(device_id, f"Cell {index}", T0 + 60), INC_KIND: TODO_KIND_LOW_BATTERY}, None))
    told = " ".join(coord._tell_episodes(pairs, BROKER_OUTAGE))
    assert "low_battery" not in told, told


@pytest.mark.parametrize(("kind", "words"), [
    ("railed_signal", "had a signal railed"),
    ("falling_battery", "had a battery running down"),
])
async def test_a_group_reads_after_its_count(hass: HomeAssistant, kind, words):
    """Not "3 devices signal railed" or "3 devices battery is running
    down" (adversarial round of 0.27.3)."""
    from custom_components.device_sentinel import const

    from .test_attribution import BROKER_OUTAGE, T0, _incident

    coord = await setup_coordinator(hass)
    real = {"railed_signal": const.TODO_KIND_RAILED_SIGNAL, "falling_battery": const.TODO_KIND_FALLING_BATTERY}[kind]
    pairs = []
    for index in range(3):
        device_id = f"k{index}"
        coord._watched[device_id] = "mqtt"
        pairs.append(({**_incident(device_id, f"Unit {index}", T0 + 60), INC_KIND: real}, None))
    told = " ".join(coord._tell_episodes(pairs, BROKER_OUTAGE))
    assert f"3 devices {words} at " in told, told
