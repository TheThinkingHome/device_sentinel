# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_own_connection.py, Version: 0.23.1 (2026-09-24)

"""A device whose own connection fails is listed as itself.

SwitchBot, TP-Link and Brother make an integration entry per device.
On the second fleet two SwitchBot freezer sensors died with their
batteries, and each one's entry failed to start. Device Sentinel
counted them as casualties of their own entries' outages, so the
Problem List named no device, only "switchbot down: 2 of 14 total
devices unavailable"; at each restart the two went on the list and
came off a minute later, logged as recoveries; and outage rows
written before 0.22.23, which name no entry, never closed, so the
integration's page read "SwitchBot Bluetooth integration, still down"
for days. Every test here but the guards fails on 0.23.0.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    INC_EVENT,
    INC_NAME,
    INCIDENT_RESOLVED,
    STARTUP_GRACE_SECONDS,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    TODO_KINDS,
    TODO_SORT_NAME,
    UPSTREAM_KIND,
)

from .helpers import setup_coordinator

DOMAIN = "switchbot"


def _entry(hass: HomeAssistant, uid: str, names: list[str]):
    source = MockConfigEntry(domain=DOMAIN, title=names[0])
    source.add_to_hass(hass)
    made = []
    for index, name in enumerate(names):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(DOMAIN, f"{uid}{index}")}, name=name,
        )
        entity = er.async_get(hass).async_get_or_create(
            "sensor", DOMAIN, f"{uid}{index}",
            device_id=device.id, config_entry=source,
        )
        made.append((device, entity.entity_id))
    return source, made


async def _run(hass, coord, freezer, minutes: int) -> None:
    for _ in range(minutes):
        freezer.tick(60)
        now = dt_util.utcnow().timestamp()
        coord._sample_integrations(now)
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()


async def _tims_freezers(hass, freezer):
    """Two dead freezer sensors and one working one, an entry each."""
    dead = []
    for uid, name in (("a", "S43 Chest freezer"), ("b", "S44 Kitchen freezer")):
        source, [(device, entity_id)] = _entry(hass, uid, [name])
        hass.states.async_set(entity_id, "unavailable")
        dead.append((source, device))
    working, [(_device, entity_id)] = _entry(hass, "c", ["S10 Desk sensor"])
    hass.states.async_set(entity_id, "21.5")
    coord = await setup_coordinator(hass)
    _have_reported(coord, [device for _source, device in dead])
    for source, _device in dead:
        source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    working.mock_state(hass, ConfigEntryState.LOADED)
    minutes = int((STARTUP_GRACE_SECONDS + FREEZE_UNAVAILABLE_DEBOUNCE) // 60) + 6
    await _run(hass, coord, freezer, minutes)
    return coord, dead


def _have_reported(coord, devices) -> None:
    """Devices with a past: a device that never reported is its own case."""
    now = dt_util.utcnow().timestamp()
    for device in devices:
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_EVENT_COUNT] = 120
        record[DEV_LAST_ACTIVITY] = now - 3600


def _listed(coord) -> dict[str, list[str]]:
    return {
        item[TODO_SORT_NAME]: sorted(item[TODO_KINDS])
        for item in coord.data[DATA_TODO_ITEMS]
    }


async def test_each_dead_device_is_listed_as_itself(hass: HomeAssistant, freezer):
    coord, _dead = await _tims_freezers(hass, freezer)
    listed = _listed(coord)
    assert "unavailable" in listed.get("S43 Chest freezer", [])
    assert "unavailable" in listed.get("S44 Kitchen freezer", [])
    assert not any(UPSTREAM_KIND in kinds for kinds in listed.values()), listed
    assert DOMAIN not in coord.suppressed_down_counts


async def test_the_reason_names_the_connection(hass: HomeAssistant, freezer):
    coord, dead = await _tims_freezers(hass, freezer)
    phrase = coord.reachability_phrase(dead[0][1].id)
    assert phrase is not None and phrase.endswith("connection failed to start.")


async def test_a_restart_does_not_take_them_off(hass: HomeAssistant, freezer):
    coord, _dead = await _tims_freezers(hass, freezer)
    before = len(coord.data[DATA_INCIDENTS])
    # A restart: what memory held is gone, the events log is not.
    coord._integration_told.clear()
    coord._integration_detail.clear()
    coord._entry_down_at.clear()
    coord._entry_seen_loaded.clear()
    coord._integration_resumed = False
    coord._started_at = dt_util.utcnow().timestamp()
    await _run(hass, coord, freezer, int(STARTUP_GRACE_SECONDS // 60) + 4)
    listed = _listed(coord)
    assert "unavailable" in listed.get("S43 Chest freezer", [])
    assert not [
        row for row in coord.data[DATA_INCIDENTS][before:]
        if row[INC_EVENT] == INCIDENT_RESOLVED
    ], "a restart was logged as a recovery"


async def test_an_entry_of_many_devices_still_claims_them(
    hass: HomeAssistant, freezer
):
    """Guard: a hub behind several devices is an outage behind them."""
    source, made = _entry(hass, "h", ["Hub Node 1", "Hub Node 2"])
    for _device, entity_id in made:
        hass.states.async_set(entity_id, "unavailable")
    coord = await setup_coordinator(hass)
    _have_reported(coord, [device for device, _entity in made])
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    minutes = int((STARTUP_GRACE_SECONDS + FREEZE_UNAVAILABLE_DEBOUNCE) // 60) + 6
    await _run(hass, coord, freezer, minutes)
    assert coord.upstream_down_since(made[0][0].id) is not None
    assert "Hub Node 1" not in _listed(coord)


async def test_an_outage_that_names_no_entry_is_closed(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_KIND: SYS_INTEGRATION_DOWN, SYS_WHEN: now - 3 * 86400,
         SYS_SCOPE: DOMAIN, SYS_DETAIL: None, SYS_DURATION: None},
    ]
    assert coord.integration_outages().get(DOMAIN, []) == []


async def test_a_paired_old_outage_is_still_shown(hass: HomeAssistant):
    """Guard: an old outage that came back is history, and stays."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_KIND: SYS_INTEGRATION_DOWN, SYS_WHEN: now - 3 * 86400,
         SYS_SCOPE: "zwave_js", SYS_DETAIL: None, SYS_DURATION: None},
        {SYS_KIND: SYS_INTEGRATION_UP, SYS_WHEN: now - 3 * 86400 + 600,
         SYS_SCOPE: "zwave_js", SYS_DETAIL: None, SYS_DURATION: 600.0},
    ]
    shown = coord.integration_outages().get("zwave_js", [])
    assert len(shown) == 1 and shown[0]["open"] is False


def _unused() -> None:
    """Names kept for readers of this file."""
    _ = INC_NAME
