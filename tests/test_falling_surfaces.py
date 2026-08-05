# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_falling_surfaces.py, Version: 0.12.2 (2026-08-05)

"""The falling battery on the phone and the card, and the crossing.

Ruling #215 fixed five tables that turn a kind into words and left
three the notifier owns: the family map, the push line, and the card,
which is not a table at all and reads list properties. A kind absent
from a list property is invisible with nothing to assert against,
which is why the card guard here drives every kind through the
summary rather than checking a table for its key.

The crossing is the case that only exists once the family map is
right. A cell already low is absent from the falling source (#213),
so at the threshold the item swaps one kind for the other in a single
pass, both are battery, and one push per family survives.
"""

from __future__ import annotations

import time
from unittest.mock import PropertyMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    NOTIFY_KIND_FAMILY,
    TODO_KIND_BATTERY,
    TODO_KIND_BATTERY_FALLING,
    TODO_KINDS_ALL,
)
from tests.helpers import setup_coordinator

# Every kind, and the list row that puts it on the card. Iterated
# against TODO_KINDS_ALL below, so a kind added without a route to
# the card fails here rather than showing a person an all-clear
# while the list says otherwise (ruling #220).
CARD_SOURCE = {
    "frozen": ("frozen_devices_list", {"category": "frozen"}),
    "unavailable": ("frozen_devices_list", {"category": "unavailable"}),
    "unknown": ("frozen_devices_list", {"category": "unknown"}),
    "not_reported": ("frozen_devices_list", {"category": "not_reported"}),
    "signal": ("signal_problem_list", {"kind": "rail"}),
    "battery": ("battery_low_list", {"level": 4.0}),
    "battery_falling": (
        "battery_falling_list",
        {"level": 24.0, "left": "about 2 weeks"},
    ),
}


def _battery_device(hass: HomeAssistant, name: str, level: float):
    """Register a device carrying a real battery entity.

    The low list is read from the battery entity's state rather than
    the stored record, so a fixture that writes only the record can
    never cross the threshold. That is exactly what defeated the
    first attempt to reproduce the crossing.
    """
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "faller")},
        name=name,
    )
    entry = er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "faller_battery",
        device_id=device.id,
        config_entry=source,
        original_device_class="battery",
        suggested_object_id="faller_battery",
    )
    hass.states.async_set(
        entry.entity_id, str(level), {"device_class": "battery"}
    )
    return device, entry.entity_id


def _seed(coord, device_id: str, level: float):
    """Give a device a fourteen-day fall ending at level."""
    now = time.time()
    record = coord.data[DATA_DEVICES].setdefault(device_id, {})
    record[DEV_EVENT_COUNT] = 500
    record[DEV_FIRST_OBSERVED] = now - 86400 * 40
    record[DEV_LAST_ACTIVITY] = now - 60
    record[DEV_BATTERY_DAILY] = [
        round(level + 2.25 * day, 1) for day in range(13, -1, -1)
    ]


def _events(coord) -> list[tuple[str, str, bool]]:
    """Run one sync and return what the dispatch would have sent."""
    seen: list[list[tuple[str, str, bool]]] = []
    original = coord._dispatch_notifications

    def spy() -> None:
        seen.append(list(coord._pending_events))
        original()

    coord._dispatch_notifications = spy
    coord._sync_problem_list()
    coord._dispatch_notifications = original
    return seen[-1] if seen else []


async def test_the_falling_push_reads_as_a_sentence(hass: HomeAssistant):
    """The line a person gets, with the projection in it."""
    device, _ = _battery_device(hass, "Door 2nd Bedroom", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    _seed(coord, device.id, 24.0)

    events = _events(coord)
    assert len(events) == 1
    family, line, recovery = events[0]
    assert family == "battery"
    assert recovery is False
    assert "_" not in line
    assert line.endswith(
        "Door 2nd Bedroom battery is running down, empty in about 2 weeks."
    )


async def test_the_falling_recovery_names_the_kind_that_lifted(
    hass: HomeAssistant,
):
    """Not "recovered", which would not say which of two ended."""
    device, _ = _battery_device(hass, "Door 2nd Bedroom", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    _seed(coord, device.id, 24.0)
    _events(coord)

    # The fall flattens: still 24 percent, no longer heading for empty.
    coord.data[DATA_DEVICES][device.id][DEV_BATTERY_DAILY] = [24.0] * 14
    events = _events(coord)
    assert [
        line for _, line, recovery in events if recovery
    ] == [
        events[0][1]
    ]
    assert events[0][1].endswith(
        "Door 2nd Bedroom battery is no longer running down."
    )


async def test_the_crossing_announces_the_level_and_not_a_recovery(
    hass: HomeAssistant,
):
    """The case that only exists once both kinds are one family.

    At the threshold the item loses the forecast and gains the level
    in one pass. Both are battery, one push per family survives, and
    the recovery is collected second, so without the crossing rule
    the phone reads "no longer running down" at the moment the cell
    went low (ruling #220).
    """
    device, entity_id = _battery_device(hass, "Door 2nd Bedroom", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    _seed(coord, device.id, 24.0)
    opened = _events(coord)
    assert opened and opened[0][2] is False

    # The battery entity's own state change drives the detector, which
    # syncs the list itself. Watching an explicit sync afterwards sees
    # nothing, because the crossing has already happened by then.
    collected: list[tuple] = []
    original = coord._dispatch_notifications

    def spy() -> None:
        collected.extend(coord._pending_events)
        original()

    coord._dispatch_notifications = spy
    hass.states.async_set(entity_id, "16", {"device_class": "battery"})
    await hass.async_block_till_done()
    coord._dispatch_notifications = original

    kinds = {
        record["device_id"]: set(record["kinds"])
        for record in coord.data["todo_items"]
    }
    assert kinds[device.id] == {TODO_KIND_BATTERY}

    assert [recovery for _, _, recovery in collected] == [False]
    assert "no longer" not in collected[0][1]
    assert collected[0][1].endswith("Door 2nd Bedroom was detected low.")


async def test_the_card_names_a_falling_cell(hass: HomeAssistant):
    """The card said all clear while the list said otherwise."""
    device, _ = _battery_device(hass, "Door 2nd Bedroom", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    _seed(coord, device.id, 24.0)
    coord._sync_problem_list()

    calls = async_mock_service(hass, "persistent_notification", "create")
    await coord.async_update_card()
    assert calls
    message = calls[-1].data["message"]
    assert message == (
        "Battery: Door 2nd Bedroom empty in about 2 weeks."
    )


async def test_a_device_with_both_kinds_reads_as_one_clause(
    hass: HomeAssistant,
):
    """Level then direction, in one entry rather than two (#216)."""
    coord = await setup_coordinator(hass)
    row_low = [{"device_id": "d1", "name": "Door 2nd Bedroom", "level": 16.0}]
    row_fall = [
        {
            "device_id": "d1",
            "name": "Door 2nd Bedroom",
            "left": "about 2 weeks",
        }
    ]
    with patch.object(
        type(coord), "battery_low_list", new_callable=PropertyMock
    ) as low, patch.object(
        type(coord), "battery_falling_list", new_callable=PropertyMock
    ) as falling:
        low.return_value = row_low
        falling.return_value = row_fall
        assert coord._family_summary("battery") == (
            "Door 2nd Bedroom 16%, empty in about 2 weeks."
        )


async def test_every_kind_has_a_family_and_a_sentence(hass: HomeAssistant):
    """The two tables the notifier owns, which #215 did not reach.

    Read from TODO_KINDS_ALL rather than a list here, so a kind
    added without a family or without a line fails on this test
    instead of arriving on a phone titled Device with an underscore
    in it, which is precisely what shipped in 0.11.11.
    """
    coord = await setup_coordinator(hass)
    for kind in TODO_KINDS_ALL:
        assert kind in NOTIFY_KIND_FAMILY, kind
        assert NOTIFY_KIND_FAMILY[kind] in ("battery", "signal", "freeze")
        for recovery in (False, True):
            line = coord._event_line(
                kind, "Probe", "5:29 pm", recovery, "about 2 weeks"
            )
            assert "_" not in line, (kind, recovery)
            assert line.startswith("At 5:29 pm, Probe")
            assert line.endswith(".")


async def test_every_kind_reaches_the_card(hass: HomeAssistant):
    """The guard the card could not have, being no table.

    Each kind is driven through the summary on the list that carries
    it. A kind with no route to the card is the fault this release
    corrects, and it was invisible because there was nothing to
    compare a missing key against.
    """
    coord = await setup_coordinator(hass)
    assert set(CARD_SOURCE) == set(TODO_KINDS_ALL), (
        set(CARD_SOURCE) ^ set(TODO_KINDS_ALL)
    )
    for kind, (prop, extra) in CARD_SOURCE.items():
        row = {"device_id": "d1", "name": "Probe"}
        row.update(extra)
        with patch.object(
            type(coord), prop, new_callable=PropertyMock
        ) as source:
            source.return_value = [row]
            family = NOTIFY_KIND_FAMILY[kind]
            summary = coord._family_summary(family)
        assert "Probe" in summary, (kind, summary)
        assert "_" not in summary, (kind, summary)


async def test_an_acknowledged_falling_cell_leaves_the_card(
    hass: HomeAssistant,
):
    """Acknowledgment silences the phone for the new kind too (#109)."""
    device, _ = _battery_device(hass, "Door 2nd Bedroom", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0})
    _seed(coord, device.id, 24.0)
    coord._sync_problem_list()
    assert TODO_KIND_BATTERY_FALLING in coord.data["todo_items"][0]["kinds"]

    for item in coord.data["todo_items"]:
        item["status"] = "completed"
        item["acked_at"] = "2026-08-05T00:00:00+00:00"

    calls = async_mock_service(hass, "persistent_notification", "create")
    await coord.async_update_card()
    assert calls[-1].data["message"] == "All devices reporting."
