# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_mode.py, Version: 0.26.7 (2026-10-19)

"""Which dashboard a window opens in (ruling #693).

A setting on the Advanced screen: Simple on a new install, Advanced on
an install that upgrades to 0.26.7. The status reply carries it, and
the dashboard's own switch keeps nothing.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_DASHBOARD_MODE,
    DOMAIN,
    OPTIONS_MINOR_VERSION,
)

from .helpers import setup_entry


async def _status(hass, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/status"})
    reply = await client.receive_json()
    assert reply["success"], reply
    return reply["result"]


async def test_an_upgrade_opens_in_advanced(hass: HomeAssistant, hass_ws_client):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={}, version=1, minor_version=6, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == OPTIONS_MINOR_VERSION == 7
    assert entry.options[CONF_DASHBOARD_MODE] == "advanced"
    assert (await _status(hass, hass_ws_client))["dashboard"] == "advanced"


async def test_a_new_install_opens_in_simple(hass: HomeAssistant, hass_ws_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    if result["type"] is FlowResultType.FORM:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert CONF_DASHBOARD_MODE not in entry.options
    assert (await _status(hass, hass_ws_client))["dashboard"] == "simple"


async def test_a_choice_already_made_is_kept_at_the_upgrade(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, version=1, minor_version=6,
        options={CONF_DASHBOARD_MODE: "simple"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options[CONF_DASHBOARD_MODE] == "simple"


async def test_the_advanced_screen_sets_it(hass: HomeAssistant, hass_ws_client):
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "advanced"})
    assert CONF_DASHBOARD_MODE in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_DASHBOARD_MODE: "advanced"})
    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_DASHBOARD_MODE] == "advanced"
    assert (await _status(hass, hass_ws_client))["dashboard"] == "advanced"


async def test_a_hand_edited_value_reads_as_simple(hass: HomeAssistant):
    entry = await setup_entry(hass, {CONF_DASHBOARD_MODE: "fancy"})
    assert entry.runtime_data.dashboard_status()["dashboard"] == "simple"
