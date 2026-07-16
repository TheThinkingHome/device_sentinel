# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.11 (2026-07-16)

"""The Device Sentinel integration.

Watches hardware liveness: frozen devices, unavailable devices, low
batteries, and weak radio links, with per-device freeze windows
learned from each device's own reporting rhythm rather than
hand-assigned tiers.

Battery detection is live. The telemetry recorder learns rhythms and
signal baselines continuously. Freeze and unavailability detection,
signal detection, and the notification engine arrive in later steps;
their configuration surfaces and the problem list are already built
and inert.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DEAD_OPTION_KEYS, DOMAIN, LOGGER
from .coordinator import DeviceSentinelCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.TODO,
]

type DeviceSentinelConfigEntry = ConfigEntry[DeviceSentinelCoordinator]


def _drop_dead_options(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> None:
    """Remove option keys from retired surfaces.

    A key no code reads is worse than absent: it survives in
    diagnostics and in the options JSON, where it reads as a live
    setting that is quietly doing nothing. Removing it at setup keeps
    the stored options honest about what the running build supports.
    """
    dead = [key for key in DEAD_OPTION_KEYS if key in entry.options]
    if not dead:
        return
    remaining = {
        key: value
        for key, value in entry.options.items()
        if key not in dead
    }
    LOGGER.info(
        "Clearing options from retired surfaces: %s", ", ".join(dead)
    )
    hass.config_entries.async_update_entry(entry, options=remaining)


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Set up Device Sentinel from a config entry."""
    # The manifest is the single source of the version string; a bump
    # touches one file. Read it at setup rather than duplicating it.
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)

    _drop_dead_options(hass, entry)

    coordinator = DeviceSentinelCoordinator(hass, entry, version)
    await coordinator.async_setup()

    entry.runtime_data = coordinator
    # Options changes (the battery threshold today) apply live: the
    # listener re-judges the fleet without a reload or restart.
    entry.async_on_unload(
        entry.add_update_listener(_async_options_updated)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> None:
    """Apply changed options to the running coordinator."""
    await entry.runtime_data.async_options_updated()


async def async_unload_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Unload a Device Sentinel config entry."""
    LOGGER.info("Device Sentinel unloading")
    await entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
