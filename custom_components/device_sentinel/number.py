# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: number.py, Version: 0.4.9 (2026-07-19)

"""Number platform for the Device Sentinel integration.

One entity: the battery low threshold as a dashboard-visible slider.
It exists because the options dialog is buried (the project's own
author could not find it); a knob belongs where the counts are seen.
The entity and the options dialog write the same setting, so either
door works and both stay in step.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    CONF_LOW_THRESHOLD,
    DOMAIN,
)
from .coordinator import DeviceSentinelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceSentinelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Device Sentinel numbers."""
    async_add_entities(
        [DeviceSentinelBatteryThresholdNumber(entry.runtime_data)]
    )


class DeviceSentinelBatteryThresholdNumber(NumberEntity):
    """The battery low threshold, adjustable from any dashboard."""

    _attr_has_entity_name = True
    _attr_name = "Battery: Threshold"
    _attr_icon = "mdi:battery-alert-variant"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_should_poll = False

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the threshold slider."""
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_battery_low_threshold"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )
        self._attr_extra_state_attributes = {
            ATTR_SENTINEL_TYPE: "battery_low_threshold",
            ATTR_SENTINEL_VERSION: coordinator.version,
        }

    async def async_added_to_hass(self) -> None:
        """Track coordinator refreshes so options-dialog edits show."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_refresh)
        )

    @callback
    def _handle_refresh(self) -> None:
        """Reflect the current setting."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return the configured threshold."""
        return self._coordinator.low_threshold

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting through the options mechanism, so the
        update listener re-judges the fleet exactly as the dialog
        path does. One setting, two doors, one behavior."""
        entry = self._coordinator.entry
        self.hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_LOW_THRESHOLD: int(value)},
        )
