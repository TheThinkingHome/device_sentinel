"""The Device Sentinel integration.

Watches hardware liveness: frozen devices, unavailable devices, and
low batteries, with per-device freeze windows learned from each
device's own reporting rhythm.

This is the Step 1 backbone: config flow, storage round-trip, and one
status sensor proving the entity pipeline. It detects nothing yet.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, LOGGER
from .coordinator import DeviceSentinelCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type DeviceSentinelConfigEntry = ConfigEntry[DeviceSentinelCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Set up Device Sentinel from a config entry."""
    # The manifest is the single source of the version string; a bump
    # touches one file. Read it at setup rather than duplicating it.
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)

    coordinator = DeviceSentinelCoordinator(hass, entry, version)
    await coordinator.async_setup()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Unload a Device Sentinel config entry."""
    LOGGER.info("Device Sentinel unloading")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
