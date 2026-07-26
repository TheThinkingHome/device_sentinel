# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_classification.py, Version: 0.9.9 (2026-07-26)

"""How devices are counted and attributed to integrations.

Every registry device is sorted into watched or set aside, and a
device that belongs to more than one config entry is attributed to its
primary one, so a camera also seen by a router tracker counts once,
under the camera. This file holds that classification behaviour.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.helpers import setup_coordinator


async def test_attribution_uses_primary_config_entry(hass: HomeAssistant):
    """A multi-homed device attributes to its primary entry's domain."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    tracker = MockConfigEntry(domain="router_tracker")
    tracker.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("camera_brand", "cam1")},
        name="Multi-homed Camera",
    )
    dev_reg.async_update_device(
        device.id, add_config_entry_id=tracker.entry_id
    )
    er.async_get(hass).async_get_or_create(
        "camera", "camera_brand", "cam1_uid",
        device_id=device.id, config_entry=owner,
    )

    coord = await setup_coordinator(hass)
    breakdown = coord.classification_breakdown
    assert breakdown.get("camera_brand", {}).get("watched", 0) == 1
    assert breakdown.get("router_tracker", {}).get("watched", 0) == 0
