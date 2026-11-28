# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_router_bbox.py, Version: 0.30.12 (2026-11-27)

"""A Bbox router is a router integration (rule MUTE-02).

Bouygues Telecom's Bbox publishes a tracker for each client on the
network: a house had 61, phones and laptops among them. It is excluded
when first seen, as the other router integrations are.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONF_EXCLUDED_INTEGRATIONS, ROUTER_INTEGRATIONS

from .test_first_seen_exclusions import _existing_house


async def test_a_bbox_router_is_excluded_when_first_seen(hass: HomeAssistant):
    assert "bbox" in ROUTER_INTEGRATIONS
    source = MockConfigEntry(domain="bbox", title="Bbox")
    source.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "device_tracker", "bbox", "aa:bb:cc:dd:ee:01", config_entry=source,
    )
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "bbox"]
