# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_router_entry_disabled.py, Version: 0.27.9 (2026-10-27)

"""A router integration the person ignored or disabled is not sighted,
so it is never added to the exclusion list (rule MUTE-02)."""

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_SYSTEM_EVENTS,
    SYS_FIRST_SEEN_EXCLUDED,
    SYS_KIND,
)

from .test_first_seen_exclusions import _existing_house


def _tracker(hass, source, disabled):
    er.async_get(hass).async_get_or_create(
        "device_tracker", "fritz", f"aa:bb:cc:dd:ee:{source.entry_id[-2:]}", config_entry=source,
        disabled_by=er.RegistryEntryDisabler.CONFIG_ENTRY if disabled else None,
    )


async def test_a_disabled_router_entry_is_not_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="fritz", title="FRITZ!Box", disabled_by=ConfigEntryDisabler.USER)
    source.add_to_hass(hass)
    _tracker(hass, source, True)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]
    assert not [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]


async def test_an_ignored_router_entry_is_not_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="fritz", title="FRITZ!Box", source=SOURCE_IGNORE)
    source.add_to_hass(hass)
    _tracker(hass, source, False)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]


async def test_a_running_router_entry_is_still_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="fritz", title="FRITZ!Box")
    source.add_to_hass(hass)
    _tracker(hass, source, False)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "fritz"]
