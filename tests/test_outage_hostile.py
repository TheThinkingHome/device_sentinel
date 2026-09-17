# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_hostile.py, Version: 0.21.12 (2026-09-17)

"""Hard cases for the 0.21.12 outage rules (#440, #441, #445, #446).

Every one of these rules reads a failure time a record carries and
does arithmetic on it. The storage check lets through any finite
number (ruling #370), so a number no writer produces is fed here, and
a clock can move backwards. None of it may raise, move an outage to a
moment that did not happen, or hold a row forever. Values the check
refuses are tested where they are refused, through the real load, in
`test_outage_boundary.py`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    INTEGRATION_DOWN_DWELL_SECONDS,
    WIFI_BURST_HOLD_SECONDS,
)
from tests.helpers import setup_coordinator
from tests.test_wifi_outage import _declared, _house

# Finite numbers the storage check accepts and no writer produces.
ODD_STAMPS = [-1.0, 0.0, 10.0**18, -(10.0**18)]


def _stamp(coord, device, value):
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = value


@pytest.mark.parametrize("value", ODD_STAMPS, ids=repr)
async def test_an_odd_failure_time_never_moves_an_outage(
    hass: HomeAssistant, freezer, value
):
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:6], freezer, count=6)
    for device in devices[:6]:
        _stamp(coord, device, value)
    coord._wifi_backdate()
    assert coord.wifi_down_at == first
    # And the readers that use it do not raise.
    coord.reportable_down_rows
    coord.suppressed_down_counts
    coord.wifi_burst_held()


@pytest.mark.parametrize("value", ODD_STAMPS, ids=repr)
async def test_an_odd_failure_time_is_never_held(
    hass: HomeAssistant, freezer, value
):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    for device in devices[:6]:
        _stamp(coord, device, value)
    assert coord.wifi_burst_held() == set()


async def test_a_clock_that_runs_backwards_holds_nothing_forever(
    hass: HomeAssistant, freezer
):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    now = dt_util.utcnow().timestamp()
    for device in devices[:6]:
        _stamp(coord, device, now)
    assert len(coord.wifi_burst_held()) == 6
    # The clock is set back an hour: the failures now lie in the
    # future, and a failure that has not happened holds nothing.
    freezer.move_to(dt_util.utcnow() - timedelta(hours=1))
    assert coord.wifi_burst_held() == set()
    freezer.move_to(dt_util.utcnow() + timedelta(hours=2))
    assert coord.wifi_burst_held() == set()


async def test_a_failure_in_the_future_cannot_date_an_outage(
    hass: HomeAssistant, freezer
):
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:6], freezer, count=6)
    for device in devices[:6]:
        _stamp(coord, device, first + 3600)
    coord._wifi_backdate()
    assert coord.wifi_down_at == first


async def test_the_hold_ends_even_if_nothing_else_happens(
    hass: HomeAssistant, freezer
):
    coord, _trackers, devices, _untied = await _house(hass, 14)
    now = dt_util.utcnow().timestamp()
    for device in devices[:6]:
        _stamp(coord, device, now)
    freezer.tick(timedelta(seconds=WIFI_BURST_HOLD_SECONDS + 1))
    assert coord.wifi_burst_held() == set()


async def test_a_restart_in_the_middle_of_an_outage(
    hass: HomeAssistant, freezer
):
    """The in-memory outage is gone after a restart. Nothing reads a
    declaration moment that no longer exists."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    await _declared(hass, coord, trackers[:6], freezer, count=6)
    coord._wifi_down_at = None
    coord._wifi_declared_from = None
    for device in devices[:6]:
        _stamp(coord, device, dt_util.utcnow().timestamp())
    coord._wifi_backdate()
    coord.wifi_burst_held()
    coord.reportable_down_rows


async def test_an_outage_standing_with_no_declaration_moment(
    hass: HomeAssistant, freezer
):
    """A state no writer produces, held to the same rule."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    await _declared(hass, coord, trackers[:6], freezer, count=6)
    coord._wifi_declared_from = None
    for device in devices[:6]:
        _stamp(coord, device, dt_util.utcnow().timestamp() - 7200)
    coord._wifi_backdate()
    assert coord.wifi_burst_held() == set()


async def test_an_integration_removed_inside_its_window(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="controller_hub", title="Hub")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("controller_hub", "n1")}, name="Node",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "controller_hub", "n1",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    coord._watched[device.id] = "controller_hub"
    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 5)
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 600)
    assert coord.upstream_recovering_at("controller_hub") is not None

    await hass.config_entries.async_remove(source.entry_id)
    await hass.async_block_till_done()
    assert coord.upstream_down_since(device.id) is None
    freezer.tick(timedelta(seconds=600))
    assert coord.upstream_recovering_at("controller_hub") is None
    coord.upstream_recovery_counts("controller_hub")


async def test_two_entries_of_one_integration_recover_apart(
    hass: HomeAssistant, freezer
):
    """One entry back and one still down: the domain's recovery is
    not over while the first's window holds, and the second's claim
    is untouched."""
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    made = []
    for index in range(2):
        source = MockConfigEntry(domain="controller_hub", title=f"Hub {index}")
        source.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("controller_hub", f"n{index}")}, name=f"Node {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", "controller_hub", f"n{index}",
            device_id=device.id, config_entry=source,
        )
        made.append((source, device))
    coord._rebuild_registry_view()
    now = dt_util.utcnow().timestamp()
    for source, device in made:
        coord._watched[device.id] = "controller_hub"
        source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    for source, _device in made:
        source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 5)
    made[0][0].mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 600)
    assert coord.upstream_down_since(made[0][1].id) is not None
    assert coord.upstream_down_since(made[1][1].id) is not None
    freezer.tick(timedelta(seconds=600))
    assert coord.upstream_down_since(made[0][1].id) is None
    assert coord.upstream_down_since(made[1][1].id) is not None
    for source, _device in made:
        source.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_peaks_for_an_upstream_that_never_went_down(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    assert coord._upstream_worst("nothing") == 0
    assert coord._upstream_ended("nothing") == {"devices": 0, "worst": 0}
