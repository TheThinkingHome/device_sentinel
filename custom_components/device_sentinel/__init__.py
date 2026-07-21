# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: __init__.py, Version: 0.4.4 (2026-07-19)

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
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    DEAD_OPTION_KEYS,
    DOMAIN,
    LOGGER,
)
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


def _drop_dead_entities(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> None:
    """Remove registry entries for entities from retired surfaces.

    Deleting a platform's code does not delete its registry entry, so
    a retired sensor would sit on the device page forever showing
    unavailable, which reads as breakage rather than as removal. The
    unique id carries the sentinel type, which is what makes the
    retired ones findable without the classes still existing.
    """
    ent_reg = er.async_get(hass)
    for sentinel_type in DEAD_ENTITY_SENTINEL_TYPES:
        unique_id = f"{entry.entry_id}_{sentinel_type}"
        for domain in (Platform.SENSOR, Platform.BUTTON, Platform.NUMBER):
            entity_id = ent_reg.async_get_entity_id(
                domain, DOMAIN, unique_id
            )
            if entity_id is None:
                continue
            LOGGER.info(
                "Removing %s, an entity from a retired surface",
                entity_id,
            )
            ent_reg.async_remove(entity_id)


RENAMED_ENTITY_IDS: dict[str, str] = {
    "sensor.device_sentinel_coverage": (
        "sensor.device_sentinel_devices_watched"
    ),
    "sensor.device_sentinel_learning_progress": (
        "sensor.device_sentinel_devices_learned"
    ),
    "sensor.device_sentinel_classification": (
        "sensor.device_sentinel_service_devices_ignored"
    ),
    "button.device_sentinel_enable_signals": (
        "button.device_sentinel_scan_and_enable_signal_and_last_seen_entities"
    ),
    "todo.device_sentinel": "todo.device_sentinel_problem_list",
}


def _migrate_renamed_entities(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> None:
    """Move entities renamed at 0.3.12 onto their new entity ids.

    A rename changes the entity id a fresh install derives, but never
    one already in the registry. Left alone that splits the world:
    installs from before 0.3.12 keep sensor.device_sentinel_coverage
    while new ones get devices_watched, so no dashboard, wiki page, or
    example could name an id that is right for everyone. Migrating
    costs the few existing installs one round of fixing references,
    which is the price of every install thereafter agreeing (ruled
    2026-07-17, at one known user, when it is cheapest).

    A target id already in use is left alone rather than fought over,
    because clobbering someone's entity is worse than an inconsistent
    name.
    """
    ent_reg = er.async_get(hass)
    for old_entity_id, new_entity_id in RENAMED_ENTITY_IDS.items():
        existing = ent_reg.async_get(old_entity_id)
        if existing is None or existing.config_entry_id != entry.entry_id:
            continue
        if ent_reg.async_get(new_entity_id) is not None:
            LOGGER.info(
                "Not renaming %s: %s already exists",
                old_entity_id,
                new_entity_id,
            )
            continue
        LOGGER.info("Renaming %s to %s", old_entity_id, new_entity_id)
        ent_reg.async_update_entity(
            old_entity_id, new_entity_id=new_entity_id
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Set up Device Sentinel from a config entry."""
    # The manifest is the single source of the version string; a bump
    # touches one file. Read it at setup rather than duplicating it.
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)

    _drop_dead_options(hass, entry)
    _drop_dead_entities(hass, entry)
    _migrate_renamed_entities(hass, entry)

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
