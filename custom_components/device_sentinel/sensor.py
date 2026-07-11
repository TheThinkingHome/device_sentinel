"""Sensor platform for the Device Sentinel integration.

Step 2 ships five entities: the Step 1 status sensor, the coverage
and learning-progress pair, and the two soak diagnostics
(classification and clock source) per ruling 14. Identity attributes
on all, per blueprint precedent.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_FIRST_INSTALLED,
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    ATTR_STORAGE_HEALTHY,
    DOMAIN,
    SENTINEL_TYPE_CLASSIFICATION,
    SENTINEL_TYPE_CLOCK_SOURCE,
    SENTINEL_TYPE_COVERAGE,
    SENTINEL_TYPE_LEARNING,
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
    async_add_entities(
        [
            DeviceSentinelStatusSensor(coordinator),
            DeviceSentinelCoverageSensor(coordinator),
            DeviceSentinelLearningSensor(coordinator),
            DeviceSentinelClassificationSensor(coordinator),
            DeviceSentinelClockSourceSensor(coordinator),
        ]
    )


class DeviceSentinelBaseSensor(SensorEntity):
    """Base class: identity attributes and coordinator refresh wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    sentinel_type: str = "base"

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self.sentinel_type}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator refreshes."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_refresh)
        )

    @callback
    def _handle_refresh(self) -> None:
        """Write the current state on a coordinator refresh."""
        self.async_write_ha_state()

    def _identity(self) -> dict[str, Any]:
        """Return the identity attributes every entity carries."""
        return {
            ATTR_SENTINEL_TYPE: self.sentinel_type,
            ATTR_SENTINEL_VERSION: self._coordinator.version,
        }


class DeviceSentinelStatusSensor(DeviceSentinelBaseSensor):
    """The status sensor: setup count as the persistence proof."""

    _attr_name = "Status"
    _attr_icon = "mdi:shield-check-outline"
    sentinel_type = SENTINEL_TYPE_STATUS

    @property
    def native_value(self) -> int:
        """Return the setup count as the state."""
        return self._coordinator.setup_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the identity and storage-proof attributes."""
        return {
            **self._identity(),
            ATTR_FIRST_INSTALLED: self._coordinator.first_installed,
            ATTR_STORAGE_HEALTHY: self._coordinator.storage_healthy,
        }


class DeviceSentinelCoverageSensor(DeviceSentinelBaseSensor):
    """The coverage sensor: watched X of Y devices with Z set aside."""

    _attr_name = "Coverage"
    _attr_icon = "mdi:radar"
    sentinel_type = SENTINEL_TYPE_COVERAGE

    @property
    def native_value(self) -> int:
        """Return the watched device count as the state."""
        return self._coordinator.watched_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the coverage breakdown."""
        return {
            **self._identity(),
            "total_devices": (
                self._coordinator.watched_count
                + self._coordinator.set_aside_count
            ),
            "set_aside": self._coordinator.set_aside_count,
            "deviceless_entities": self._coordinator.deviceless_count,
            "learning": self._coordinator.learning_buckets,
        }


class DeviceSentinelLearningSensor(DeviceSentinelBaseSensor):
    """The learning-progress sensor: devices past the arming floor."""

    _attr_name = "Learning progress"
    _attr_icon = "mdi:school-outline"
    sentinel_type = SENTINEL_TYPE_LEARNING

    @property
    def native_value(self) -> int:
        """Return the count of rhythm-established devices."""
        return self._coordinator.learning_buckets["established"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full learning buckets."""
        return {**self._identity(), **self._coordinator.learning_buckets}


class DeviceSentinelClassificationSensor(DeviceSentinelBaseSensor):
    """Soak diagnostic: the per-integration classification breakdown."""

    _attr_name = "Classification"
    _attr_icon = "mdi:filter-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    sentinel_type = SENTINEL_TYPE_CLASSIFICATION

    @property
    def native_value(self) -> int:
        """Return the set-aside count as the state."""
        return self._coordinator.set_aside_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the per-integration breakdown."""
        return {
            **self._identity(),
            "by_integration": self._coordinator.classification_breakdown,
        }


class DeviceSentinelClockSourceSensor(DeviceSentinelBaseSensor):
    """Soak diagnostic: watched devices without a last_seen entity."""

    _attr_name = "Clock source"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    sentinel_type = SENTINEL_TYPE_CLOCK_SOURCE

    @property
    def native_value(self) -> int:
        """Return the count of devices on the recorded clock."""
        return self._coordinator.clock_source_split["without_last_seen"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the clock-source split."""
        return {**self._identity(), **self._coordinator.clock_source_split}
