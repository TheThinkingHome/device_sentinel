"""Sensor platform for the Device Sentinel integration.

Step 1 ships one entity: the status sensor. Its state is the setup
count from storage, so a restart visibly ticks it up by one while
first_installed holds still, proving the storage round-trip on a
dashboard with no tooling.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_FIRST_INSTALLED,
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    ATTR_STORAGE_HEALTHY,
    DOMAIN,
    SENTINEL_TYPE_STATUS,
)
from .coordinator import DeviceSentinelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceSentinelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Device Sentinel sensors."""
    coordinator = entry.runtime_data
    async_add_entities([DeviceSentinelStatusSensor(coordinator)])


class DeviceSentinelStatusSensor(SensorEntity):
    """The Device Sentinel status sensor."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:shield-check-outline"
    _attr_should_poll = False

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the status sensor."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )

    @property
    def native_value(self) -> int:
        """Return the setup count as the state."""
        return self._coordinator.setup_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the identity and storage-proof attributes."""
        return {
            ATTR_SENTINEL_TYPE: SENTINEL_TYPE_STATUS,
            ATTR_SENTINEL_VERSION: self._coordinator.version,
            ATTR_FIRST_INSTALLED: self._coordinator.first_installed,
            ATTR_STORAGE_HEALTHY: self._coordinator.storage_healthy,
        }
