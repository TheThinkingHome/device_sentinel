# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_small_fixes.py, Version: 0.23.0 (2026-09-24)

"""The first 0.23.x fixes, from Tim Plas's review of 0.22.25.

The dashboard's Daily Brief tab printed the Repeat Offenders table as
rows of pipes. The Devices tab called ZHA "Zigbee Home Automation"
while the status boxes and the outage lines called it ZHA. MQTT's page
listed its own devices and not the Tasmota devices that reach Home
Assistant through the same broker. And a lost clocks file still left
a device that had reported but had no learned day without a clock,
which the simulation of 23 September found on the fourth fleet. Every
test but the guards fails on 0.22.28.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_NEVER_REPORTED,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    STARTUP_GRACE_SECONDS,
    STORAGE_CLOCKS_KEY,
    TODO_KIND_UNAVAILABLE,
)

from .helpers import register_device, setup_coordinator, setup_entry


@pytest.fixture(autouse=True)
def _mid_afternoon(freezer):
    freezer.move_to("2026-09-24T20:00:00+00:00")


def _twice_unavailable(device_id: str, name: str, now: float) -> list[dict]:
    rows = []
    for index in range(2):
        at = now - 40000.0 - index * 90000.0
        base = {INC_DEVICE_ID: device_id, INC_NAME: name, INC_KIND: TODO_KIND_UNAVAILABLE}
        rows.append({**base, INC_EVENT: INCIDENT_OPENED, INC_WHEN: at, INC_DURATION: None})
        rows.append({**base, INC_EVENT: INCIDENT_RESOLVED, INC_WHEN: at + 720.0, INC_DURATION: 720.0})
    return rows


async def test_the_tab_gets_the_repeat_rows_not_markdown(hass: HomeAssistant):
    device, _entities = register_device(hass, "rp1", name="Closet Switch")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    now = dt_util.utcnow().timestamp()
    coordinator.data[DATA_INCIDENTS] = _twice_unavailable(device.id, "Closet Switch", now)
    coordinator.data[DATA_SYSTEM_EVENTS] = []
    day = coordinator.dashboard_brief(dt_util.now().date())
    repeat = day["repeat"]
    assert "lines" not in repeat
    assert [row["name"] for row in repeat["rows"]] == ["Closet Switch"]
    row = repeat["rows"][0]
    assert row["device_id"] == device.id and row["times"] == 2
    assert not any("|" in str(value) for value in row.values())
    assert repeat["paragraph"].startswith("This table lists repeat offenders.")


async def test_the_file_keeps_its_table(hass: HomeAssistant):
    """Guard: the written brief still carries the Markdown table."""
    device, _entities = register_device(hass, "rp2", name="Closet Switch")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    now = dt_util.utcnow().timestamp()
    coordinator.data[DATA_INCIDENTS] = _twice_unavailable(device.id, "Closet Switch", now)
    coordinator.data[DATA_SYSTEM_EVENTS] = []
    await hass.async_add_executor_job(coordinator._write_reports, "test")
    assert "| DEVICE | WHAT HAPPENED | TIMES | WHEN | TYPICAL | WITH |" in (
        coordinator._last_brief_text
    )


async def test_zha_is_called_zha(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    assert coordinator._integration_title("zha") == "ZHA"


async def test_other_integrations_keep_home_assistants_name(hass: HomeAssistant):
    """Guard: only a name the status boxes already give is replaced."""
    coordinator = await setup_coordinator(hass)
    assert coordinator._integration_title("no_such_integration") == "no_such_integration"


def _device(hass, domain: str, key: str, name: str):
    entry = MockConfigEntry(domain=domain, title=name)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, key)}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, key, device_id=device.id, config_entry=entry
    )
    return device


async def test_mqtts_page_lists_tasmota_devices(hass: HomeAssistant):
    _device(hass, "mqtt", "m1", "Door Laundry")
    relay = _device(hass, "tasmota", "t1", "Stove Vent Relays")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    page = coordinator.dashboard_integration("mqtt")
    assert [row["name"] for row in page["devices"]] == ["Door Laundry"]
    riders = page["behind_broker"]
    assert [row["name"] for row in riders] == ["Stove Vent Relays"]
    assert riders[0]["device_id"] == relay.id
    assert riders[0]["integration"]


async def test_other_pages_list_no_riders(hass: HomeAssistant):
    """Guard: the section belongs to MQTT's page alone."""
    _device(hass, "tasmota", "t2", "Stove Vent Relays")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    page = coordinator.dashboard_integration("tasmota")
    assert page["behind_broker"] == []


async def _lose_clocks(hass, hass_storage, freezer, entry):
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    del hass_storage[STORAGE_CLOCKS_KEY]
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _settle(hass, freezer, minutes: int) -> None:
    for _ in range(minutes):
        freezer.tick(60)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_a_device_that_reported_without_a_learned_day_keeps_a_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """The fourth fleet's case: 22 events, three days old, no fold yet."""
    device, entities = register_device(hass, "nc1", name="Pico Remote")
    hass.states.async_set(entities[0] if isinstance(entities, list) else entities, "1")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(days=3)).isoformat()
    record[DEV_EVENT_COUNT] = 22
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 3600
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is not None
    await _settle(hass, freezer, int(STARTUP_GRACE_SECONDS // 60) + 2)
    assert coordinator.data[DATA_DEVICES][device.id].get(DEV_FROZEN_CATEGORY) != (
        FREEZE_CATEGORY_NEVER_REPORTED
    )


async def test_a_device_stored_as_never_reported_stays_so(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: the verdict it carries is kept, and so is its empty clock."""
    device, _entities = register_device(hass, "nc2", name="Dead On Arrival")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(days=5)).isoformat()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_NEVER_REPORTED
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is None


async def test_a_young_device_keeps_no_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: under 48 hours it still has its whole window to speak."""
    device, _entities = register_device(hass, "nc3", name="New Sensor")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(hours=10)).isoformat()
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is None
