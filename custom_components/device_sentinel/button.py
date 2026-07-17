# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.12 (2026-07-17)

"""Button platform for the Device Sentinel integration.

One button: the enable assist. Press it and Device Sentinel enables
every integration-disabled last_seen and signal entity on watched
devices, so protocol truth flows without hand-enabling entities one
by one. User-disabled entities are respected.
"""

from __future__ import annotations

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
    """Set up the Device Sentinel buttons."""
    async_add_entities([DeviceSentinelEnableSignalsButton(entry.runtime_data)])


class DeviceSentinelEnableSignalsButton(ButtonEntity):
    """Enable disabled last_seen and signal entities on watched devices.

    The name says scan and enable because that is both halves of what
    the press does: it walks the entity registry for signal and
    last_seen entities an integration shipped turned off, and turns
    them on. It does not discover devices; discovery is automatic and
    continuous through registry listeners, so a name promising a
    search would promise something that never needed asking for.

    Last-seen is named alongside signal deliberately. It is protocol
    truth, the clock freeze detection trusts most, and a user who
    reads only "signal" has no reason to press a button that would
    strengthen their freeze detection.
    """

    _attr_has_entity_name = True
    _attr_name = "Scan and Enable Signal and Last-Seen Entities"
    _attr_icon = "mdi:signal"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_enable_signal_entities"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )
        self._attr_extra_state_attributes = {
            ATTR_SENTINEL_TYPE: "enable_assist",
            ATTR_SENTINEL_VERSION: coordinator.version,
        }

    async def async_press(self) -> None:
        """Run the enable assist."""
        await self._coordinator.async_enable_signal_entities()
