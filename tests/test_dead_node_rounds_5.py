# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_5.py, Version: 0.26.5 (2026-10-16)

"""The fifth adversarial round on 0.26.5, 16 October 2026: a device whose
only enabled entity is its node status sensor, heard while Home
Assistant was down, is not left unavailable."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, rec, restart, walk
from .test_zwave_dead_node import _mine

DAY = 86400.0


async def test_status_only_device_heard_during_a_restart_is_not_left_unavailable(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", "4191921521-22")},
        name="P22 Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "switch", "zwave_js", "4191921521.22-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    status = reg.async_get_or_create(
        "sensor", "zwave_js", "4191921521.22.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    recoveries = record_events(hass, EVENT_RECOVERED)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def heard_while_home_assistant_was_down():
        # Z-Wave JS heard the node during the downtime and hands its
        # status back already alive, before Device Sentinel listens.
        hass.states.async_set(status, "alive")

    coord = await restart(
        hass, freezer, down=600, before_setup=heard_while_home_assistant_was_down
    )
    record = rec(coord, device.id)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 20 * 60)

    assert record.get(DEV_DOWN_SINCE) is None
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "a node Z-Wave calls alive was left unavailable", record[DEV_FROZEN_CATEGORY]
    )
    # Whether the return is announced across a restart follows the
    # existing restart rules; what matters here is that it is not stuck.
    assert len(_mine(recoveries, device.id)) <= 1
