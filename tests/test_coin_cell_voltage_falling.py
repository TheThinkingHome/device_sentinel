# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_coin_cell_voltage_falling.py, Version: 0.30.12 (2026-11-28)

"""A coin cell whose voltage is falling is a state of its own (rule BAT-03).

A thermometer with a CR2032 read 2.6 V and 59%: its percentage over the
threshold, its voltage near the end. It is listed as voltage falling and
counted on Battery: falling, never as low, and it sends no push, at its
start or at its end. Its history says to replace it whatever the
percentage reads. A cell low by its percentage stays low, and says its
voltage beside its level. A new battery clears the mark.
"""

from __future__ import annotations

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DEV_BATTERY_LOW,
    DEV_BATTERY_VOLTS_FALLING_SINCE,
    DEV_BATTERY_VOLTS_TODAY_HIGH,
    DEV_BATTERY_VOLTS_TODAY_LOW,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_VOLTS,
    INCIDENT_OPENED,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    TODO_KIND_FALLING_BATTERY,
)

from .helpers import registry_settled, setup_coordinator

WORDS = "voltage is falling, 2.6 V (new 3.0, spent 2.0)"


async def _thermometer(hass: HomeAssistant):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", "thermo")}, name="Thermometer",
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", "thermo_battery", device_id=device.id, config_entry=source,
        original_device_class="battery", suggested_object_id="thermo_battery",
    ).entity_id
    hass.states.async_set(entity, "100", {"device_class": "battery", "unit_of_measurement": "%"})
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    coord._grace_until = 0.0
    coord.page_set_power(device.id, "CR2032", 1)
    return coord, device, entity


async def _read(hass, coord, device, entity, level, volts):
    record = coord.data["devices"][device.id]
    record[DEV_BATTERY_VOLTS_TODAY_LOW] = volts
    record[DEV_BATTERY_VOLTS_TODAY_HIGH] = volts
    hass.states.async_set(entity, str(level), {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return record


def _pushes(coord) -> list[tuple[str, str, bool]]:
    """One sync, and what the dispatch would have sent to the phone."""
    seen: list[list[tuple[str, str, bool]]] = []
    original = coord._dispatch_notifications

    def spy() -> None:
        seen.append(list(coord._pending_events))
        original()

    coord._dispatch_notifications = spy
    coord._sync_problem_list()
    coord._dispatch_notifications = original
    return seen[-1] if seen else []


async def test_a_falling_voltage_is_listed_and_counted_but_not_low(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    record = await _read(hass, coord, device, entity, 59, 2.6)
    assert not record.get(DEV_BATTERY_LOW)
    assert record[DEV_BATTERY_VOLTS_FALLING_SINCE]
    assert coord.battery_low_count == 0
    assert coord.battery_falling_count == 1
    problems = coord._current_problems()
    assert TODO_KIND_FALLING_BATTERY in problems[device.id]["kinds"]
    assert problems[device.id]["left"] == WORDS
    summary, _ = coord._problem_item_text(
        "Thermometer", problems[device.id]["kinds"], problems[device.id]["level"],
        problems[device.id]["left"], device.id,
    )
    assert summary == f"Thermometer: battery {WORDS}"
    assert coord._brief_falling_text(device.id).startswith(f"battery {WORDS}")


async def test_a_falling_voltage_sends_no_push_at_its_start_or_its_end(hass: HomeAssistant, freezer):
    coord, device, entity = await _thermometer(hass)
    coord._notification_delay = lambda device_id: 0
    sent: list[tuple[str, str, bool]] = []
    original = coord._dispatch_notifications

    def spy() -> None:
        sent.extend(coord._pending_events)
        original()

    coord._dispatch_notifications = spy
    record = await _read(hass, coord, device, entity, 59, 2.6)
    coord._sync_problem_list()
    assert TODO_KIND_FALLING_BATTERY in coord._current_problems()[device.id]["kinds"]
    await _read(hass, coord, device, entity, 95, 3.0)
    assert record[DEV_BATTERY_VOLTS_FALLING_SINCE] is None
    # Its item leaves a minute after it cleared (rule LIST-06).
    freezer.tick(90)
    coord._sync_problem_list()
    assert device.id not in coord._current_problems()
    assert sent == []


async def test_an_accelerating_cell_still_pushes(hass: HomeAssistant):
    """The suppression is the voltage's alone: the same kind, from an
    accelerating decay, reaches the phone (rule BAT-14)."""
    coord, device, entity = await _thermometer(hass)
    coord._notification_delay = lambda device_id: 0
    await _read(hass, coord, device, entity, 59, 2.6)
    coord._volts_falling_items.discard(device.id)
    coord._collect_event(TODO_KIND_FALLING_BATTERY, "Thermometer", False, device.id, "decay is accelerating")
    assert [line for _, line, _ in coord._pending_events][-1].endswith("Thermometer battery decay is accelerating.")


async def test_its_history_says_to_replace_it(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    await _read(hass, coord, device, entity, 59, 2.6)
    coord._sync_problem_list()
    opened = next(
        row for row in coord.data[DATA_INCIDENTS]
        if row.get(INC_DEVICE_ID) == device.id and row.get(INC_KIND) == TODO_KIND_FALLING_BATTERY
        and row.get(INC_EVENT) == INCIDENT_OPENED
    )
    assert opened[INC_VOLTS] == "2.6"
    sentence = coord._compose_event(opened)
    assert "Thermometer battery voltage is falling: 2.6 V since " in sentence
    assert sentence.endswith("The cell is near its end; replace it regardless of its percentage.")
    assert coord._flap_verbs(opened) == ("battery voltage began falling", "voltage falling")


async def test_the_brief_names_it_on_its_own_line(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    await _read(hass, coord, device, entity, 59, 2.6)
    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML), encoding="utf-8") as handle:
        brief = handle.read()
    assert "Battery voltage falling: Thermometer (2.6 V)." in brief


async def test_low_wins_and_says_its_voltage(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    record = await _read(hass, coord, device, entity, 9, 2.4)
    assert record.get(DEV_BATTERY_LOW)
    assert record[DEV_BATTERY_VOLTS_FALLING_SINCE] is None
    assert coord.battery_falling_count == 0
    problems = coord._current_problems()
    summary, _ = coord._problem_item_text(
        "Thermometer", problems[device.id]["kinds"], problems[device.id]["level"],
        problems[device.id]["left"], device.id,
    )
    assert summary == "Thermometer: battery 9%, 2.4 V"


async def test_a_new_battery_clears_the_mark(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    record = await _read(hass, coord, device, entity, 59, 2.6)
    assert record[DEV_BATTERY_VOLTS_FALLING_SINCE]
    await _read(hass, coord, device, entity, 100, 3.05)
    assert record[DEV_BATTERY_VOLTS_FALLING_SINCE] is None


async def test_battery_trends_lists_it_as_a_problem(hass: HomeAssistant):
    coord, device, entity = await _thermometer(hass)
    await _read(hass, coord, device, entity, 59, 2.6)
    page = coord.battery_trends()
    row = next(row for row in page["problems"] if row["device_id"] == device.id)
    assert row["state"] == "volts"
    assert row["volts"] == "2.6" and row["coin"] is True
    assert row["left"] is None
    assert not any(other["device_id"] == device.id for other in page["others"])
