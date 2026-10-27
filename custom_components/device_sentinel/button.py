# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: button.py, Version: 0.27.10 (2026-10-27)

"""Button platform for the Device Sentinel integration.

Two buttons, each touching only Device Sentinel's own state, so any
user, automation or script may press them.

Regenerate Reports rewrites every report on demand, for a person
mid-investigation who wants them to reflect a fix now rather than at
the next tick, or an automation that sends a fresh Daily Brief.

Maintenance Mode opens and closes the maintenance window: pressed once it declares that a person is working on the
hardware, pressed again it ends the declaration early. While the
window is open, any device that recovers is attributed to the person's
hands and its silence is not learned (rule FRZ-18).

No button turns on other integrations' entities, because any user,
automation or script can press a button, and it would turn on entities
a person had switched off on purpose. A sensor is switched on one
device at a time, by an administrator, from the device's page or its
Recommendations card; the retired-entity sweep removes the three old
Enable buttons from the registry (rule REC-05).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import ATTR_SENTINEL_TYPE, ATTR_SENTINEL_VERSION, DOMAIN
from .coordinator import DeviceSentinelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceSentinelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Regenerate Reports and Maintenance Mode buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DeviceSentinelActionButton(
                coordinator,
                key="regenerate_reports",
                icon="mdi:file-refresh-outline",
                action=coordinator.async_regenerate_reports,
            ),
            DeviceSentinelActionButton(
                coordinator,
                key="maintenance_mode",
                icon="mdi:progress-wrench",
                action=coordinator.async_toggle_maintenance,
            ),
        ]
    )


class DeviceSentinelActionButton(ButtonEntity):
    """A Device Sentinel button that runs one coordinator action.

    Each button is a thin wrapper around the async action it is given;
    the action carries the behavior, and touches only Device Sentinel's
    own state.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeviceSentinelCoordinator,
        key: str,
        icon: str,
        action: Callable[[], Awaitable[dict[str, int]]],
    ) -> None:
        """Initialize one button around its coordinator action."""
        self._coordinator = coordinator
        self._action = action
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )
        self._attr_extra_state_attributes = {
            # Each button names its own kind (rule REL-16).
            ATTR_SENTINEL_TYPE: key,
            ATTR_SENTINEL_VERSION: coordinator.version,
        }

    async def async_press(self) -> None:
        """Run this button's action."""
        await self._action()
