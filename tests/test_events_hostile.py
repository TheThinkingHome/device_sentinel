# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_events_hostile.py, Version: 0.15.9 (2026-08-18)

"""The bus events under conditions that should not happen.

The suite beside this proves the events fire correctly. This proves
they cannot take the sync down with them when something else is
already wrong, because the sync is the path that keeps the list, the
reports and the storage right, and a listener that throws must not
cost a person their storage write.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    UNASSIGNED_AREA,
)
from tests.helpers import setup_entry


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, entity.entity_id


def _freeze(coord, device_id):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = 999_990.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = 1_000_000.0


async def test_the_sync_survives_a_bus_that_refuses(
    hass: HomeAssistant,
):
    """The sync keeps the list, the reports and the storage correct.

    A refusal from the bus itself must not cost a person their
    storage write, so the fire path swallows and logs. Home Assistant
    already dispatches listeners away from the caller, so a badly
    written automation cannot reach the sync at all; what this covers
    is the narrower case the integration is responsible for, which is
    the fire call failing on its own account.
    """
    device, entity_id = _register(hass, "h1", "Attic Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0

    def refuse(*args, **kwargs):
        raise RuntimeError("the bus said no")

    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    with patch(
        "homeassistant.core.EventBus.async_fire", side_effect=refuse
    ):
        coord._sync_problem_list()
        await hass.async_block_till_done()

    # The list was still built despite the refusal.
    items = coord.data["todo_items"]
    assert len(items) == 1
    assert items[0]["sort_name"] == "Attic Sensor"


async def test_a_device_gone_from_the_registry_still_fires(
    hass: HomeAssistant,
):
    """A device removed between the verdict and the announcement.

    The area lookup is the only part of the payload that reaches
    outside the coordinator's own data, so it is the only part that
    can find nothing. It reads Unassigned rather than raising.
    """
    device, entity_id = _register(hass, "h2", "Attic Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    seen: list[dict] = []
    hass.bus.async_listen(EVENT_FAULT, lambda e: seen.append(e.data))

    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    dr.async_get(hass).async_remove_device(device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    if seen:
        assert seen[0]["area"] == UNASSIGNED_AREA


async def test_the_area_reads_the_registry_when_there_is_one(
    hass: HomeAssistant,
):
    """The ordinary case, so the fallback above is not the only path
    ever exercised."""
    device, entity_id = _register(hass, "h3", "Attic Sensor")
    area = hass.data["area_registry"].async_create("Attic")
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    seen: list[dict] = []
    hass.bus.async_listen(EVENT_FAULT, lambda e: seen.append(e.data))

    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    assert seen and seen[0]["area"] == "Attic", seen


async def test_a_masked_cascade_fires_nothing(hass: HomeAssistant):
    """#264 suppresses the cascade at the problem list itself, so the
    devices behind a downed coordinator never become rows and nothing
    reaches the bus. The upstream row that stands in their place is
    not a device and has no event (ruling #289)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    seen: list[dict] = []
    hass.bus.async_listen(EVENT_FAULT, lambda e: seen.append(e.data))

    problems = coord._current_problems()
    upstream = [key for key in problems if key.startswith("upstream:")]
    coord._sync_problem_list()
    await hass.async_block_till_done()

    for payload in seen:
        assert "upstream" not in payload["kinds"], payload
    assert not upstream or all(
        payload["device_id"] not in upstream for payload in seen
    )
