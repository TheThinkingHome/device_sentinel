# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: button.py, Version: 0.5.5 (2026-07-21)

"""Button platform for the Device Sentinel integration.

Three enable-assist buttons, one per diagnostic kind: signals, last
seen, and battery. Each walks the entity registry for entities of its
kind that an integration shipped turned off, and turns them on, on
watched devices only. User-disabled entities are respected.

Three buttons rather than one so a user can enable exactly the
diagnostic they want. Battery is its own match rule (a percentage
sensor with device_class battery), not a widening of the signal
filter, and it earns its own press because a user reading only
"signals" has no reason to expect a battery button to be hiding there.

A fourth button regenerates both nightly report files on demand, for a
person mid-investigation who wants the report to reflect a fix now
rather than at the next tick.
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
    """Set up the Device Sentinel enable-assist buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DeviceSentinelActionButton(
                coordinator,
                key="enable_signal_entities",
                name="Enable Signals",
                icon="mdi:signal",
                action=coordinator.async_enable_signal_entities,
            ),
            DeviceSentinelActionButton(
                coordinator,
                key="enable_last_seen_entities",
                name="Enable Last Seen",
                icon="mdi:clock-check-outline",
                action=coordinator.async_enable_last_seen_entities,
            ),
            DeviceSentinelActionButton(
                coordinator,
                key="enable_battery_entities",
                name="Enable Battery",
                icon="mdi:battery-heart-variant",
                action=coordinator.async_enable_battery_entities,
            ),
            DeviceSentinelActionButton(
                coordinator,
                key="regenerate_reports",
                name="Regenerate Reports",
                icon="mdi:file-refresh-outline",
                action=coordinator.async_regenerate_reports,
            ),
        ]
    )


class DeviceSentinelActionButton(ButtonEntity):
    """A Device Sentinel button that runs one coordinator action.

    The enable buttons each walk the entity registry for entities of
    their kind that an integration shipped turned off, and turn them
    on, on watched devices only, leaving user-disabled entities alone.
    The regenerate button judges every device and rewrites both report
    files on demand. Each button is a thin wrapper around the async
    action it is given; the action carries the behavior.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DeviceSentinelCoordinator,
        key: str,
        name: str,
        icon: str,
        action: Callable[[], Awaitable[dict[str, int]]],
    ) -> None:
        """Initialize one enable button around its coordinator action."""
        self._coordinator = coordinator
        self._action = action
        self._attr_name = name
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
            ATTR_SENTINEL_TYPE: "enable_assist",
            ATTR_SENTINEL_VERSION: coordinator.version,
        }

    async def async_press(self) -> None:
        """Run this button's enable assist."""
        await self._action()
