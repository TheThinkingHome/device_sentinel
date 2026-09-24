# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_entry_outages.py, Version: 0.23.1 (2026-09-24)

"""An integration outage is one config entry's, and survives a restart.

SwitchBot, TP-Link and Brother make one config entry per device. On
the second fleet one freezer sensor with a dead battery read as "the
switchbot integration went down", two could not be told apart, and a
TP-Link entry that never came back was recorded down afresh after
every restart. Since 0.22.23 each outage carries its entry, one that
carries a single device names that device as offline, and an outage
still open at a restart is resumed rather than recorded again.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    INTEGRATION_DOWN_DWELL_SECONDS,
    STARTUP_GRACE_SECONDS,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    SYS_KIND,
)
from custom_components.device_sentinel.outage_detail import parse_detail

from .helpers import setup_coordinator

DOMAIN = "switchbot"


def _entry(hass: HomeAssistant, uid: str, name: str, devices: int = 1):
    """One config entry, as SwitchBot makes per device."""
    source = MockConfigEntry(domain=DOMAIN, title=name)
    source.add_to_hass(hass)
    made = []
    for index in range(devices):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(DOMAIN, f"{uid}{index}")},
            name=name if devices == 1 else f"{name} {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", DOMAIN, f"{uid}{index}",
            device_id=device.id, config_entry=source,
        )
        made.append(device)
    return source, made


def _rows(coord, kind):
    return [row for row in coord.data[DATA_SYSTEM_EVENTS] if row[SYS_KIND] == kind]


async def _past_grace(coord, freezer):
    coord._sample_integrations(dt_util.utcnow().timestamp())
    freezer.tick(STARTUP_GRACE_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())


async def test_a_single_device_entry_names_the_device(hass: HomeAssistant, freezer):
    source, (freezer2,) = _entry(hass, "f2", "Freezer 2")
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord = await setup_coordinator(hass)
    await _past_grace(coord, freezer)
    (down,) = _rows(coord, SYS_INTEGRATION_DOWN)
    assert parse_detail(down[SYS_DETAIL]) == (source.entry_id, freezer2.id, "failed")
    sentence = coord._system_event_sentence(down)
    assert sentence.startswith("Freezer 2 is offline: its ")
    assert " connection failed to start at " in sentence
    assert "integration" not in sentence
    assert coord._system_event_phrase(down).startswith("Freezer 2 offline, its ")
    outages = coord.integration_outages()[DOMAIN]
    assert outages[0]["what"].startswith("Freezer 2 (")
    assert outages[0]["open"] is True


async def test_an_entry_of_many_devices_still_reads_as_the_integration(
    hass: HomeAssistant, freezer
):
    source, _devices = _entry(hass, "h", "Hub", devices=3)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord = await setup_coordinator(hass)
    await _past_grace(coord, freezer)
    (down,) = _rows(coord, SYS_INTEGRATION_DOWN)
    assert parse_detail(down[SYS_DETAIL])[1] is None
    assert coord._system_event_sentence(down).startswith(f"The {DOMAIN} integration went down at ")


async def test_two_entries_of_one_integration_are_two_outages(
    hass: HomeAssistant, freezer
):
    one, _ = _entry(hass, "f1", "Freezer 1")
    two, _ = _entry(hass, "f2", "Freezer 2")
    one.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    two.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord = await setup_coordinator(hass)
    await _past_grace(coord, freezer)
    assert len(_rows(coord, SYS_INTEGRATION_DOWN)) == 2
    one.mock_state(hass, ConfigEntryState.LOADED)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    outages = coord.integration_outages()[DOMAIN]
    by_name = {row["what"].split(" (")[0]: row for row in outages}
    assert by_name["Freezer 1"]["open"] is False
    assert by_name["Freezer 2"]["open"] is True


async def test_an_outage_open_at_a_restart_is_resumed_not_repeated(
    hass: HomeAssistant, freezer
):
    source, (device,) = _entry(hass, "v", "Robot Vacuum")
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord = await setup_coordinator(hass)
    await _past_grace(coord, freezer)
    (down,) = _rows(coord, SYS_INTEGRATION_DOWN)
    # Read from the outage itself: an entry that carries one device no
    # longer claims it as a casualty (0.23.1).
    since = coord.upstream_down_since_for(DOMAIN)

    # A restart: everything held in memory is gone, the events log is
    # not, and the run starts again with its own grace.
    freezer.tick(3600)
    coord._integration_told.clear()
    coord._integration_detail.clear()
    coord._entry_down_at.clear()
    coord._entry_seen_loaded.clear()
    coord._integration_resumed = False
    coord._started_at = dt_util.utcnow().timestamp()
    await _past_grace(coord, freezer)
    assert len(_rows(coord, SYS_INTEGRATION_DOWN)) == 1, "recorded again after a restart"
    assert coord.upstream_down_since_for(DOMAIN) == since

    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    (up,) = _rows(coord, SYS_INTEGRATION_UP)
    assert up[SYS_DURATION] >= 3600
    assert parse_detail(up[SYS_DETAIL])[0] == source.entry_id
    assert coord._system_event_sentence(up).startswith("Robot Vacuum is back: its ")
