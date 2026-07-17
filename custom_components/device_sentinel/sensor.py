# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.12 (2026-07-17)

"""Sensor platform for the Device Sentinel integration.

Every name here has to stand alone: Home Assistant gives entities no
helper text on the device page, so a label and its state are the
whole explanation a user gets. Names are title-cased per ruling 48,
counts carry a unit so a card reads "125 devices" rather than "125",
and any sensor whose state a user could not act on was renamed or
retired at 0.3.12.

Clock source was retired there. It counted watched devices lacking a
last_seen entity, so a higher number read as better while meaning
worse, and it existed to answer a soak question that closed on
2026-07-18. Its registry entry is removed at setup rather than left
to linger unavailable.

Identity attributes on all, per blueprint precedent.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_FIRST_INSTALLED,
    ATTR_SENTINEL_TYPE,
    ATTR_SETUP_COUNT,
    ATTR_SENTINEL_VERSION,
    ATTR_STORAGE_HEALTHY,
    BATTERY_CLEAR_MARGIN,
    DOMAIN,
    SENTINEL_TYPE_BATTERY_COUNT,
    SENTINEL_TYPE_BATTERY_LIST,
    SENTINEL_TYPE_CLASSIFICATION,
    SENTINEL_TYPE_COVERAGE,
    SENTINEL_TYPE_LEARNING,
    SENTINEL_TYPE_STATUS,
    STATUS_LEARNING,
    STATUS_PROBLEM,
    STATUS_WATCHING,
    UNIT_BATTERIES,
    UNIT_DEVICES,
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
            DeviceSentinelBatteryLowCountSensor(coordinator),
            DeviceSentinelBatteryLowListSensor(coordinator),
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
    """The status sensor: is Device Sentinel alive and fine.

    Through 0.3.11 this published the setup count, which proved the
    Step 1 storage round-trip and meant nothing to anyone else. A
    sensor named Status must answer its own name, so the count moved
    to an attribute, where it still proves persistence.

    Learning shows only until the first device establishes a rhythm.
    Partial learning is permanent rather than a phase (every new
    device starts unlearned), so keying the word to "any device
    unlearned" would read Learning forever and mean nothing. Devices
    Learned carries the per-device detail.
    """

    _attr_name = "Status"
    _attr_icon = "mdi:shield-check-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_WATCHING, STATUS_LEARNING, STATUS_PROBLEM]
    sentinel_type = SENTINEL_TYPE_STATUS

    @property
    def native_value(self) -> str:
        """Return the state a person would want to read."""
        if not self._coordinator.storage_healthy:
            return STATUS_PROBLEM
        if self._coordinator.learning_buckets["established"] == 0:
            return STATUS_LEARNING
        return STATUS_WATCHING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the identity and storage-proof attributes."""
        return {
            **self._identity(),
            ATTR_FIRST_INSTALLED: self._coordinator.first_installed,
            ATTR_STORAGE_HEALTHY: self._coordinator.storage_healthy,
            ATTR_SETUP_COUNT: self._coordinator.setup_count,
        }


class DeviceSentinelCoverageSensor(DeviceSentinelBaseSensor):
    """How many devices Device Sentinel is watching.

    Named for what it counts rather than for the abstraction:
    "Coverage: 125" left a user to guess the unit and the population.
    The rest of the split rides in attributes.
    """

    _attr_name = "Devices Watched"
    _attr_icon = "mdi:radar"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
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
    """Devices whose rhythm is established, past the arming floor.

    An integer rather than "115 of 125" by ruling: a string state
    cannot be compared in an automation and forfeits the state class.

    This is not expected to reach Devices Watched. Devices with no
    heartbeat (buttons, remotes) never establish a rhythm and are
    never judged frozen, by design, so a permanent gap between the
    two counts is the system working.
    """

    _attr_name = "Devices Learned"
    _attr_icon = "mdi:school-outline"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
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

    _attr_name = "Service Devices Ignored"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
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


class DeviceSentinelBatteryLowCountSensor(DeviceSentinelBaseSensor):
    """Step 3 detection: how many devices are battery-low right now.

    Value-only by ruling: an unavailable battery is Step 4's business,
    so this count never folds liveness in and stays clean for
    dashboards and automations.
    """

    _attr_name = "Battery Low Count"
    _attr_icon = "mdi:battery-alert"
    _attr_native_unit_of_measurement = UNIT_BATTERIES
    _attr_state_class = SensorStateClass.MEASUREMENT
    sentinel_type = SENTINEL_TYPE_BATTERY_COUNT

    @property
    def native_value(self) -> int:
        """Return the number of battery-low devices."""
        return self._coordinator.battery_low_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return identity plus the thresholds in effect."""
        return {
            **self._identity(),
            "low_threshold": self._coordinator.low_threshold,
            "clear_margin": BATTERY_CLEAR_MARGIN,
        }


class DeviceSentinelBatteryLowListSensor(DeviceSentinelBaseSensor):
    """The battery low list: one row per device, area then name.

    Row shape follows the Battery Sentinel 1.2.0 contract (name,
    entity_id, area, level, since, last_seen, age, kind) so any
    dashboard or notifier written against the blueprint reads this
    list unchanged.
    """

    _attr_name = "Battery Low List"
    _attr_icon = "mdi:battery-alert-variant-outline"
    _attr_native_unit_of_measurement = UNIT_BATTERIES
    _attr_state_class = SensorStateClass.MEASUREMENT
    sentinel_type = SENTINEL_TYPE_BATTERY_LIST

    @property
    def native_value(self) -> int:
        """Return the row count as the state."""
        return self._coordinator.battery_low_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return identity plus the device rows."""
        return {
            **self._identity(),
            "devices": self._coordinator.battery_low_list,
        }
