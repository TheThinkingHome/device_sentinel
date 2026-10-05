# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_absence_is_the_device.py, Version: 0.24.6 (2026-10-05)

"""An absence belongs to the device, not to one of its entities.

When an entity goes unavailable or unknown, Device Sentinel notes when,
and if the absence outlasts the device's tolerance the device's next
gap is not learned. Until 0.24.3 the absence was kept per entity and
measured only when that entity came back, so a device heard all the
while through its other entities was tainted anyway. On the reference
rig on 3 October, Button Randy Night Table's action entity sat at
unknown from the 15:04 restart until a press at 23:58, 8.9 hours, while
the button was heard through its other entities; the press tainted it
and its next gap was forgotten. And an event entity reads unknown after
every restart until its next event, which is no absence at all.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_TODAY_MAX,
)

from .helpers import register_device, registry_settled, setup_entry

HOUR = 3600.0


async def _button(hass, freezer, *, last_seen=True, kind="event"):
    hass.data["_zz_freezer"] = freezer
    """A device with a twelve-hour rhythm: its main entity, and optionally
    a Last seen entity the way Zigbee2MQTT gives one."""
    device, _entities = register_device(hass, "bt", name="Button Probe")
    ents = er.async_get(hass)
    main = ents.async_get_or_create(
        kind, "test", "bt_main", device_id=device.id, original_name="Action" if kind == "event" else "Contact"
    ).entity_id
    seen = None
    if last_seen:
        seen = ents.async_get_or_create(
            "sensor", "test", "bt_last_seen", device_id=device.id,
            original_name="Last seen", original_device_class="timestamp",
        ).entity_id
    now = dt_util.utcnow()
    hass.states.async_set(main, now.isoformat() if kind == "event" else "off")
    if seen:
        hass.states.async_set(seen, now.isoformat())
    entry = await setup_entry(hass)
    await registry_settled(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [12 * HOUR * (0.95 + 0.01 * (i % 5)) for i in range(20)]
    # A first report, so the device has a clock and the next one ends a gap.
    freezer = hass.data["_zz_freezer"]
    await _report(hass, freezer, 60, *([(seen, None)] if seen else []), (main, None if kind == "event" else "on"))
    assert record["last_activity"] is not None
    return coord, record, main, seen


async def _report(hass, freezer, after, *entity_values):
    freezer.tick(timedelta(seconds=after))
    stamp = dt_util.utcnow().isoformat()
    for entity_id, value in entity_values:
        hass.states.async_set(entity_id, stamp if value is None else value)
    await hass.async_block_till_done()


async def test_a_device_heard_through_another_entity_was_not_absent(hass, freezer):
    """Button Randy Night Table, 3 October."""
    # The run spans about fourteen hours. Started from the real clock, it
    # crossed the harness's local midnight on some afternoons, and the
    # fold then filed the gap this test reads into the day before. A
    # fixed start keeps the run inside one day.
    freezer.move_to("2026-10-01 12:00:00+00:00")
    coord, record, main, seen = await _button(hass, freezer)
    hass.states.async_set(main, "unavailable")
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    for hours in (1, 2, 3):
        await _report(hass, freezer, hours * HOUR, (seen, None))
    # The press: Zigbee2MQTT's one message updates Last seen first, then
    # the action, as at 23:58 on 3 October.
    await _report(hass, freezer, 2.9 * HOUR, (seen, None), (main, None))
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 5 * HOUR, (seen, None))
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 4.9 * HOUR, (
        "a device heard all along was tainted by one entity's unknown"
    )


async def test_an_event_entity_unknown_after_a_restart_is_no_absence(hass, freezer):
    """An event entity reads unknown until its next event."""
    coord, record, main, _seen = await _button(hass, freezer, last_seen=False)
    hass.states.async_set(main, "unavailable")
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    # The press ends a gap of 8.9 hours in which nobody pressed it: the
    # device's own silence, and learned.
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 8.9 * HOUR, (main, None))
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 8.8 * HOUR, (
        "an event entity waiting for its next event was taken for an absence"
    )


async def test_an_event_entity_unavailable_for_hours_still_taints(hass, freezer):
    coord, record, main, _seen = await _button(hass, freezer, last_seen=False)
    hass.states.async_set(main, "unavailable")
    await hass.async_block_till_done()
    # The gap spanning the absence, ending at the return, is the one not learned.
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 8.9 * HOUR, (main, None))
    assert record[DEV_TODAY_MAX] is None, "a real absence no longer tainted"



async def test_a_state_entity_unknown_with_nothing_heard_still_taints(hass, freezer):
    coord, record, main, _seen = await _button(hass, freezer, last_seen=False, kind="binary_sensor")
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    # The gap spanning the absence, ending at the return, is the one not learned.
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 3 * HOUR, (main, "on"))
    assert record[DEV_TODAY_MAX] is None, "a real absence no longer tainted"



async def test_a_whole_device_absent_still_taints(hass, freezer):
    coord, record, main, seen = await _button(hass, freezer)
    hass.states.async_set(main, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await hass.async_block_till_done()
    # The gap spanning the absence, ending at the return, is the one not learned.
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 3 * HOUR, (seen, None), (main, None))
    assert record[DEV_TODAY_MAX] is None, "a real absence no longer tainted"


async def test_a_state_entity_unknown_while_the_device_reports_does_not_taint(hass, freezer):
    """Part one alone: a device heard through Last seen while one of its
    state entities sat at unknown was never absent."""
    coord, record, main, seen = await _button(hass, freezer, kind="binary_sensor")
    hass.states.async_set(main, "unknown")
    await hass.async_block_till_done()
    for hours in (2, 2, 2, 2):
        await _report(hass, freezer, hours * HOUR, (seen, None))
    await _report(hass, freezer, 1 * HOUR, (seen, None), (main, "on"))
    record[DEV_TODAY_MAX] = None
    await _report(hass, freezer, 5 * HOUR, (seen, None))
    assert record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] > 4.9 * HOUR, (
        "a device heard all along was tainted by one state entity's unknown"
    )
