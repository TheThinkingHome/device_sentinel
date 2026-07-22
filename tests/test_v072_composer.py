# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v072_composer.py, Version: 0.7.2 (2026-07-22)

"""0.7.2 tests: the message composer and the dry run.

Two shapes from one module. An event sentence is history, carrying
its time and, for a recovery, how long it lasted and what ended it.
A device line is status, carrying no timestamp because a phone holds
one line per device and replaces it in place. Nothing is sent; every
composed message lands in the outbox to be read and argued with.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_OUTBOX,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    OUTBOX_SHAPE_DEVICE,
    OUTBOX_SHAPE_EVENT,
    OUT_SHAPE,
    OUT_TEXT,
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
    return device, plain.entity_id


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


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


async def test_event_sentences_read_as_history(hass: HomeAssistant):
    coord = await _coordinator(hass)
    text = _row(coord, "d", "Door Master", "frozen", INCIDENT_OPENED)
    assert text.startswith("Door Master stopped reporting at ")
    assert text.endswith(".")

    text = _row(coord, "d", "Temperature LR", "unavailable", INCIDENT_OPENED)
    assert "went unavailable at " in text


async def test_recovery_sentence_carries_span_and_cause(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    text = _row(
        coord, "d", "Door Master", "frozen", INCIDENT_RESOLVED,
        duration=7200.0, cause="bridge reconnect",
    )
    assert "recovered at " in text
    assert "after 2.0h" in text
    assert "revived by a bridge reconnect" in text

    text = _row(
        coord, "d", "Leak Washer", "frozen", INCIDENT_RESOLVED,
        duration=1320.0, cause="on its own",
    )
    assert "after 22m, on its own." in text

    # A problem that predates the log resolves without a duration.
    text = _row(
        coord, "d", "Old Problem", "frozen", INCIDENT_RESOLVED,
    )
    assert "after" not in text


async def test_device_line_is_status_without_a_timestamp(
    hass: HomeAssistant,
):
    device, entity_id = _register(hass, "s1", "Door Master")
    coord = await _coordinator(hass)
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
    device, entity_id = _register(hass, "m1", "Motion Closet", True)
    coord = await _coordinator(hass)
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
    device, entity_id = _register(hass, "b1", "Motion Bath", True)
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = 14.0
    record[DEV_BATTERY_SINCE] = "2026-07-21T15:02:00+00:00"
    coord._sync_problem_list()
    assert coord._compose_device_line(device.id) == (
        "Motion Bath battery is at 14%."
    )


async def test_nothing_sends_but_everything_is_composed(
    hass: HomeAssistant,
):
    """The dry run: an incident produces both shapes in the outbox
    and no service call anywhere."""
    device, entity_id = _register(hass, "o1", "Outbox Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    calls = []
    hass.bus.async_listen("call_service", lambda event: calls.append(event))
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    coord._sync_problem_list()
    await hass.async_block_till_done()

    shapes = [row[OUT_SHAPE] for row in coord.data[DATA_OUTBOX]]
    assert OUTBOX_SHAPE_EVENT in shapes
    assert OUTBOX_SHAPE_DEVICE in shapes
    assert all("Outbox Sensor" in row[OUT_TEXT] for row in coord.data[DATA_OUTBOX])
    assert not [
        call for call in calls
        if call.data.get("domain") == "notify"
    ]


async def test_outbox_is_bounded(hass: HomeAssistant):
    coord = await _coordinator(hass)
    for index in range(60):
        coord._note_outbox("d", f"line {index}", OUTBOX_SHAPE_EVENT)
    assert len(coord.data[DATA_OUTBOX]) == 50
    assert coord.data[DATA_OUTBOX][-1][OUT_TEXT] == "line 59"


async def test_outbox_reaches_diagnostics(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data._note_outbox("d", "a line", OUTBOX_SHAPE_EVENT)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["outbox"][-1][OUT_TEXT] == "a line"
