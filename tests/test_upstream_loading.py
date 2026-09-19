# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_upstream_loading.py, Version: 0.22.0 (2026-09-18)

"""An upstream that has not loaded yet is loading, not down (#445).

The second fleet's ZHA takes a minute or two to load after Home
Assistant starts. Its reader allows sixty seconds before an unloaded
entry counts as down, so on 20 of 21 restarts the brief recorded "zha
bridge went down" and, a minute later, "came back": at the upgrade
restart of 16 September, down at 16:22:45 and back at 16:23:46.

Inside the startup grace, a bridge or integration that has not loaded
since Home Assistant started is loading, and nothing is recorded.
Once the grace is over, one still not loaded is down, dated from the
start. The broker already reads unknown until it is first heard, so it
has no down to suppress. Every upstream records how long it took to
load.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    DATA_SYSTEM_EVENTS,
    INTEGRATION_DOWN_DWELL_SECONDS,
    STARTUP_GRACE_SECONDS,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_INTEGRATION_DOWN,
    SYS_KIND,
    ZHA_DOWN_DWELL_SECONDS,
)
from tests.helpers import setup_coordinator


def _kinds(coord):
    return [row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]]


async def _zha_house(hass):
    entry = MockConfigEntry(domain="zha", title="ZHA")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    coord = await setup_coordinator(hass)
    coord._bridge_readers["zha"] = stack_zha.make_reader(hass)
    # The state the last run left: running.
    coord._bridge_seen["zha"] = BRIDGE_RUNNING
    return coord, entry


async def test_zha_loading_late_is_not_an_outage(hass: HomeAssistant, freezer):
    coord, entry = await _zha_house(hass)
    assert coord._in_startup_grace()
    coord._sample_bridges()
    freezer.tick(ZHA_DOWN_DWELL_SECONDS + 15)
    coord._sample_bridges()
    freezer.tick(60)
    coord._sample_bridges()
    assert SYS_BRIDGE_DOWN not in _kinds(coord)

    entry.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_bridges()
    assert SYS_BRIDGE_DOWN not in _kinds(coord)
    assert SYS_BRIDGE_UP not in _kinds(coord)
    assert 130 <= coord.upstreams_loaded_after["zha"] <= 140
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_zha_that_never_loads_is_down_from_the_start(
    hass: HomeAssistant, freezer
):
    coord, entry = await _zha_house(hass)
    started = coord._started_at
    coord._sample_bridges()
    freezer.tick(STARTUP_GRACE_SECONDS + 5)
    coord._sample_bridges()
    assert _kinds(coord).count(SYS_BRIDGE_DOWN) == 1
    assert coord._bridge_down_at["zha"] == started
    assert "zha" not in coord.upstreams_loaded_after
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_an_outage_after_loading_is_an_outage(
    hass: HomeAssistant, freezer
):
    coord, entry = await _zha_house(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_bridges()
    freezer.tick(30)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_bridges()
    freezer.tick(ZHA_DOWN_DWELL_SECONDS + 15)
    coord._sample_bridges()
    assert _kinds(coord).count(SYS_BRIDGE_DOWN) == 1
    assert coord._bridge_down_at["zha"] > coord._started_at
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_z2m_not_yet_online_is_loading(hass: HomeAssistant, freezer):
    coord = await setup_coordinator(hass)
    reader = SimpleNamespace(
        state=BRIDGE_DOWN, pairing_open=False, loaded=False,
        async_stop=lambda: None,
    )
    coord._bridge_readers["z2m"] = reader
    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    coord._sample_bridges()
    assert SYS_BRIDGE_DOWN not in _kinds(coord)

    reader.state, reader.loaded = BRIDGE_RUNNING, True
    freezer.tick(20)
    coord._sample_bridges()
    assert SYS_BRIDGE_UP not in _kinds(coord)
    assert 19 <= coord.upstreams_loaded_after["z2m"] <= 21


def _plant_integration(hass, domain="controller_hub"):
    source = MockConfigEntry(domain=domain, title="Hub")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, "n1")},
        name="Node",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, "n1", device_id=device.id, config_entry=source,
    )
    return source, device


async def test_an_integration_loading_late_is_not_an_outage(
    hass: HomeAssistant, freezer
):
    source, device = _plant_integration(hass)
    source.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    coord = await setup_coordinator(hass)
    coord._watched[device.id] = "controller_hub"
    now = dt_util.utcnow().timestamp()
    coord._sample_integrations(now)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 30)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert SYS_INTEGRATION_DOWN not in _kinds(coord)
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert SYS_INTEGRATION_DOWN not in _kinds(coord)
    assert coord.upstreams_loaded_after["controller_hub"] >= 90


async def test_an_integration_that_never_loads_is_down_from_the_start(
    hass: HomeAssistant, freezer
):
    source, device = _plant_integration(hass)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord = await setup_coordinator(hass)
    coord._watched[device.id] = "controller_hub"
    started = coord._started_at
    coord._sample_integrations(dt_util.utcnow().timestamp())
    freezer.tick(STARTUP_GRACE_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _kinds(coord).count(SYS_INTEGRATION_DOWN) == 1
    assert coord.upstream_down_since(device.id) == ("controller_hub", started)


async def test_diagnostics_carry_the_load_times(hass: HomeAssistant, freezer):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    from tests.helpers import setup_entry

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.upstreams_loaded_after["zha"] = 75.0
    found = await async_get_config_entry_diagnostics(hass, entry)
    assert found["restart"]["upstreams_loaded_after"] == {"zha": 75.0}


def _broker(state, loaded):
    return SimpleNamespace(
        state=state, loaded=loaded, started_at=None, stopped_at=None,
        regressed_since=lambda known: False, async_stop=lambda: None,
    )


async def test_the_broker_follows_the_same_rule(hass: HomeAssistant, freezer):
    """A reader that could read down before the broker was ever heard
    is held to the bridges' rule, so the four paths read alike."""
    from custom_components.device_sentinel.const import (
        BROKER_DOWN,
        BROKER_LABEL,
        BROKER_RUNNING,
        DATA_BROKER_SEEN,
        SYS_BROKER_DOWN,
    )

    coord = await setup_coordinator(hass)
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING}
    started = coord._started_at
    coord._broker_reader = _broker(BROKER_DOWN, False)
    coord._sample_bridges()
    assert SYS_BROKER_DOWN not in _kinds(coord)

    freezer.tick(STARTUP_GRACE_SECONDS + 5)
    coord._sample_bridges()
    assert _kinds(coord).count(SYS_BROKER_DOWN) == 1
    assert coord._broker_down_at == started
    assert BROKER_LABEL not in coord.upstreams_loaded_after


async def test_the_broker_records_when_it_was_first_heard(
    hass: HomeAssistant, freezer
):
    from custom_components.device_sentinel.const import (
        BROKER_LABEL,
        BROKER_RUNNING,
    )

    coord = await setup_coordinator(hass)
    freezer.tick(12)
    coord._broker_reader = _broker(BROKER_RUNNING, True)
    coord._sample_bridges()
    assert 11 <= coord.upstreams_loaded_after[BROKER_LABEL] <= 13


async def test_a_reader_that_faults_saying_is_taken_as_established(
    hass: HomeAssistant,
):
    class _Faulty:
        state = BRIDGE_RUNNING
        pairing_open = False

        @property
        def loaded(self):
            raise RuntimeError("radio gone")

        def async_stop(self):
            return None

    coord = await setup_coordinator(hass)
    coord._bridge_readers["z2m"] = _Faulty()
    coord._sample_bridges()
    assert "z2m" in coord.upstreams_loaded_after
