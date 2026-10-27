# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_study_live_entries.py, Version: 0.27.8 (2026-10-27)

"""The Z-Wave and Matter studies read only entries set up to run (rule
STACK-12): an ignored discovery or a disabled entry is not a network."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE, STUDIABLE
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
from custom_components.device_sentinel.study_stacks import _thread_network, matter_study, zwave_study

from .helpers import setup_coordinator


async def test_ignored_and_disabled_entries_are_not_studied(hass: HomeAssistant):
    MockConfigEntry(domain="zwave_js", source=SOURCE_IGNORE, title="ign").add_to_hass(hass)
    MockConfigEntry(domain="zwave_js", disabled_by=ConfigEntryDisabler.USER, title="off").add_to_hass(hass)
    MockConfigEntry(domain="matter", source=SOURCE_IGNORE, title="ign").add_to_hass(hass)
    MockConfigEntry(domain="otbr", source=SOURCE_IGNORE, title="ign").add_to_hass(hass)
    assert zwave_study(hass) == {}
    assert await matter_study(hass) == {}
    assert _thread_network(hass)["border_routers"] == 0


async def test_an_ignored_entry_is_not_in_the_download(hass: HomeAssistant):
    MockConfigEntry(domain="zwave_js", source=SOURCE_IGNORE, title="ign").add_to_hass(hass)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["zwave_js"]]})
    diag = await async_get_config_entry_diagnostics(hass, coord.entry)
    assert diag["classification"]["zwave"] == {}
