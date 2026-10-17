# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_zwave_dead_node.py, Version: 0.26.5 (2026-10-16)

"""The Z-Wave dead-node check (ruling #670).

Home Assistant keeps a dead Z-Wave node's entities available; only its
node status sensor says "dead". Tim Plas unplugged P03 on 15 October
2026: Z-Wave marked it dead at 18:53:06, after a failed command, and
alive at 20:13:02, and Device Sentinel saw nothing. These reproduce
that and the edges around it. Every test here fails on 0.26.4.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INTEGRATION_DOWN_DWELL_SECONDS,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk

DAY = 86400.0


def _zwave(hass, node=10, last_seen=True, status_on=True, state=ConfigEntryState.LOADED, source=None):
    """A Z-Wave plug: a switch, a signal, maybe a Last Seen, and its node status."""
    if source is None:
        source = MockConfigEntry(domain="zwave_js")
        source.add_to_hass(hass)
        source.mock_state(hass, state)
    reg = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", f"4191921521-{node}")},
        name=f"P{node:02d} Z-Wave Smart plug",
    )
    ids = {}
    ids["switch"] = reg.async_get_or_create(
        "switch", "zwave_js", f"4191921521.{node}-37-0-currentValue",
        device_id=device.id, config_entry=source,
    ).entity_id
    ids["rssi"] = reg.async_get_or_create(
        "sensor", "zwave_js", f"4191921521.{node}.statistics_rssi",
        device_id=device.id, config_entry=source, original_name="Signal strength",
    ).entity_id
    if last_seen:
        ids["last_seen"] = reg.async_get_or_create(
            "sensor", "zwave_js", f"4191921521.{node}.last_seen",
            device_id=device.id, config_entry=source, original_name="Last seen",
        ).entity_id
    status = reg.async_get_or_create(
        "sensor", "zwave_js", f"4191921521.{node}.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
        disabled_by=None if status_on else er.RegistryEntryDisabler.INTEGRATION,
    )
    ids["status"] = status.entity_id
    return source, device, ids


def _set(hass, ids, status="alive", value="on"):
    hass.states.async_set(ids["switch"], value)
    hass.states.async_set(ids["rssi"], "-42")
    if "last_seen" in ids:
        hass.states.async_set(ids["last_seen"], "2026-10-15T05:59:08+00:00")
    if status is not None:
        hass.states.async_set(ids["status"], status)


async def _house(hass, freezer, **kwargs):
    freezer.move_to(PIN)
    source, device, ids = _zwave(hass, **kwargs)
    _set(hass, ids, status=None if not kwargs.get("status_on", True) else "alive")
    coord = await setup_coordinator(hass)
    # P03's real wait: a Trimmed Maximum of about three days.
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    return coord, device, ids, record


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]


async def test_p03_dead_opens_and_alive_closes(hass: HomeAssistant, freezer):
    """Tim's test of 15 October, end to end."""
    coord, device, ids, record = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)
    heard = record[DEV_LAST_ACTIVITY]

    # Unplugged: nothing changes for twelve minutes.
    await walk(hass, freezer, 12 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    # A command fails and Z-Wave marks it dead.
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(_mine(faults, device.id)) == 1
    assert record[DEV_LAST_ACTIVITY] == heard, "dead was taken as the device speaking"

    # Plugged back in 80 minutes later: alive, then its values.
    await walk(hass, freezer, 65 * 60)
    hass.states.async_set(ids["status"], "alive")
    hass.states.async_set(ids["rssi"], "-44")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None
    back = _mine(recoveries, device.id)
    assert len(back) == 1
    # Down for the whole dead stretch, not from the last report.
    assert 75 * 60 <= back[0]["down_for"] <= 85 * 60


async def test_sleep_and_wake_say_nothing(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    heard = record[DEV_LAST_ACTIVITY]
    for state in ("asleep", "awake", "unknown", "asleep", "awake"):
        hass.states.async_set(ids["status"], state)
        await hass.async_block_till_done()
        await walk(hass, freezer, 300)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)
    assert record[DEV_LAST_ACTIVITY] == heard


async def test_a_status_change_is_the_device_speaking_only_when_it_comes_back(
    hass: HomeAssistant, freezer
):
    """Finding 5 of Project__Stack_Readers.md, on a device with no Last
    Seen sensor, whose clock is its entities' own writes. Asleep, awake
    and dead are not the device speaking; dead to alive is, because
    Z-Wave JS calls a dead node alive only once it has heard it."""
    coord, device, ids, record = await _house(hass, freezer, last_seen=False)
    heard = record[DEV_LAST_ACTIVITY]
    for state in ("asleep", "awake", "asleep", "dead"):
        await walk(hass, freezer, 600)
        hass.states.async_set(ids["status"], state)
        await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == heard
    await walk(hass, freezer, 600)
    hass.states.async_set(ids["status"], "alive")
    await hass.async_block_till_done()
    now = record[DEV_LAST_ACTIVITY]
    assert now is not None and (heard is None or now > heard)


async def test_alive_does_not_hold_up_a_device_whose_readings_are_gone(
    hass: HomeAssistant, freezer
):
    """Every reading unavailable while the status sensor reads alive is
    the device down; the status sensor is not a reading."""
    coord, device, ids, record = await _house(hass, freezer)
    for key in ("switch", "rssi", "last_seen"):
        hass.states.async_set(ids[key], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_frozen_verdict_moves_to_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_node_dead_at_start(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source, device, ids = _zwave(hass)
    _set(hass, ids, status="dead")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_DOWN_SINCE] is not None


async def test_a_switched_off_status_sensor_says_nothing(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer, status_on=False)
    # Home Assistant writes no state for a disabled entity; a stray one
    # must still not be read.
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert device.id in coord._node_status_entity


async def test_another_integration_s_node_status_is_not_read(hass: HomeAssistant, freezer):
    """Only Z-Wave's own sensor counts; a look-alike on another stack does not."""
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("mqtt", "x1")}, name="Look-alike")
    reg = er.async_get(hass)
    value = reg.async_get_or_create("sensor", "mqtt", "x1_t", device_id=device.id, config_entry=source).entity_id
    status = reg.async_get_or_create("sensor", "mqtt", "x1.node_status", device_id=device.id, config_entry=source).entity_id
    hass.states.async_set(value, "20")
    hass.states.async_set(status, "dead")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 30 * 60)
    assert device.id not in coord._node_status_entity
    assert record[DEV_FROZEN_CATEGORY] is None


async def test_dead_while_z_wave_is_not_loaded_raises_no_device_fault(
    hass: HomeAssistant, freezer
):
    """An integration outage is one problem (#445), not one per node."""
    freezer.move_to(PIN)
    source, device, ids = _zwave(hass)
    _other_source, other, other_ids = _zwave(hass, node=11, source=source)
    _set(hass, ids)
    _set(hass, other_ids)
    coord = await setup_coordinator(hass)
    arm(coord, device.id, rhythm=3.05 * DAY)
    arm(coord, other.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    now = dt_util.utcnow().timestamp()
    coord._sample_integrations(now + 1)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 2)
    await hass.async_block_till_done()
    assert coord.upstream_down_since(device.id) is not None
    for key in ("switch", "rssi", "last_seen"):
        hass.states.async_set(ids[key], "unavailable")
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert not _mine(faults, device.id)


async def test_the_brief_says_became_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer)
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    words = coord.unavailable_words(device.id)
    assert words == ("became unavailable", "unavailable")
    assert coord.unavailable_words("not-a-device") is None


async def test_a_muted_node_is_recorded_and_not_reported(hass: HomeAssistant, freezer):
    from custom_components.device_sentinel.const import CONF_MUTED_DEVICES

    freezer.move_to(PIN)
    source, device, ids = _zwave(hass)
    _set(hass, ids)
    coord = await setup_coordinator(hass, {CONF_MUTED_DEVICES: [device.id]})
    arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert not _mine(faults, device.id)

    assert device.id in coord._watched


# ------------------------------------------------- ruling #671


async def test_a_switched_off_status_sensor_is_on_the_card(hass: HomeAssistant, freezer):
    """The card names it, Enable Last Seen turns it on, and the Status
    sensor's Last Seen count includes it."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.device_sentinel.const import (
        DOMAIN,
        REPAIR_ENTITIES_DISABLED,
        REPAIR_MOMENT_BRIEF,
    )
    from custom_components.device_sentinel.repairs import entities_disabled_detail

    coord, device, ids, record = await _house(hass, freezer, status_on=False)
    counts = coord.awaiting_enable_counts()
    assert counts["node_status"] == 1 and counts["last_seen"] == 0
    assert coord.awaiting_enable_devices()["node_status"] == [device.id]
    detail = entities_disabled_detail(
        counts, coord.awaiting_enable_devices(), coord._device_name
    )
    assert detail == "1 Z-Wave status on P10 Z-Wave Smart plug"
    coord._evaluate_repairs(REPAIR_MOMENT_BRIEF)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_ENTITIES_DISABLED) is not None

    found = await coord.async_enable_last_seen_entities()
    assert found.get("enabled") == 1
    entry = er.async_get(hass).async_get(ids["status"])
    assert entry.disabled_by is None


async def test_the_device_page_turns_it_on_and_shows_it(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _house(hass, freezer, status_on=False)
    assert coord.dashboard_device(device.id)["identity"]["node_status"] == "off"
    assert coord.page_enable_last_seen(device.id) == 1
    assert er.async_get(hass).async_get(ids["status"]).disabled_by is None
    hass.states.async_set(ids["status"], "dead")
    await hass.async_block_till_done()
    assert coord.dashboard_device(device.id)["identity"]["node_status"] == "dead"


async def test_a_device_without_one_shows_no_row(hass: HomeAssistant, freezer):
    from .helpers import register_device

    freezer.move_to(PIN)
    other, _ids = register_device(hass, "plain")
    coord = await setup_coordinator(hass)
    assert coord.dashboard_device(other.id)["identity"]["node_status"] is None
    assert coord.awaiting_enable_counts()["node_status"] == 0
