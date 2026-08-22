# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: __init__.py, Version: 0.16.0 (2026-08-19)

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

import os
import shutil
from functools import partial
from typing import Any
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.loader import async_get_integration

from .const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    DEAD_OPTION_KEYS,
    DOMAIN,
    MUTING_KEY_RENAMES,
    LOGGER,
    OPTIONS_MINOR_VERSION,
    REPORT_DIR,
    REPORT_WWW_DIR,
    REPORT_WWW_PARENT,
    REPORT_WWW_URL,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from .coordinator import DeviceSentinelCoordinator
from .repairs import async_clear_all

# No NUMBER platform since 0.11.10. It carried one entity, the
# battery threshold as a dashboard slider, put there because the
# options dialog was buried and the author could not find it.
# The dialog is documented now and the threshold has a second
# setting beside it that never got a knob, so the device page
# held one control out of two and no others at all. One door
# rather than one and a half (ruling #209).
PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.TODO,
]

type DeviceSentinelConfigEntry = ConfigEntry[DeviceSentinelCoordinator]


async def async_migrate_entry(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> bool:
    """Bring an entry's options up to the current minor version.

    Home Assistant runs this before setup and, if it returns False or
    raises, marks the entry as needing attention and does not start
    the integration. That is the behaviour this migration wants. An
    entry whose muting lists could not be carried across is better
    dark and saying so than started with twelve empty lists, which
    would put a person's whole muted fleet into tomorrow's brief with
    nothing to explain it.

    The steps are numbered rather than applied as a set, because the
    two audiences arrive differently (ruling #316): this fleet and
    the beta fleet take one step at a time, while a person on the
    public release jumps several at once. Numbering makes those the
    same code path, applied in order from wherever the entry sits.
    """
    if entry.minor_version >= OPTIONS_MINOR_VERSION:
        return True
    options = dict(entry.options)
    if entry.minor_version < 2:
        options = _migrate_muting_names(options)
    hass.config_entries.async_update_entry(
        entry, options=options, minor_version=OPTIONS_MINOR_VERSION
    )
    return True


def _migrate_muting_names(options: dict[str, Any]) -> dict[str, Any]:
    """Step 2: the exclude lists take their muting names.

    A key that is not present produces nothing rather than an empty
    list, so an entry that never had a picker touched does not gain
    twelve keys it did not have. A key already renamed is left alone,
    so a second run changes nothing.
    """
    moved: list[str] = []
    for old, new in MUTING_KEY_RENAMES.items():
        if old not in options:
            continue
        value = options.pop(old)
        if new not in options:
            options[new] = value
        moved.append(f"{old} -> {new} ({len(value)})")
    if moved:
        LOGGER.info(
            "Options migration step 2, muting names: %s", "; ".join(moved)
        )
    else:
        LOGGER.info(
            "Options migration step 2, muting names: nothing stored to move"
        )
    return options


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
            LOGGER.debug(
                "Removing %s, an entity from a retired surface",
                entity_id,
            )
            ent_reg.async_remove(entity_id)


async def _async_serve_www_folder(hass: HomeAssistant) -> None:
    """Serve this integration's www folder on the boot that creates it.

    Home Assistant registers /local only where config/www already
    exists as a directory when the frontend sets up, and it checks
    that once. Device Sentinel creates www/device_sentinel at its
    first report write, which happens later, so on a system that
    never had a www folder the very first boot after installing
    leaves the daily brief and the dwell chart on disk at addresses
    that return nothing. It heals at the next restart and says
    nothing about why, which is the first impression the integration
    makes on somebody who has just installed it.

    Registering the folder for ourselves closes that boot rather
    than explaining it. The test is deliberately for the parent
    folder, not our own: where config/www already existed the
    frontend has /local covered and a second overlapping route would
    be a route we do not need. Where it did not, /local is absent
    for this whole boot and only our own registration can serve the
    files.

    Any failure here is logged and swallowed. A brief that cannot be
    reached over HTTP is a worse brief, not a broken integration,
    and the files are still on disk (ruling #186).
    """
    if os.path.isdir(hass.config.path(REPORT_WWW_PARENT)):
        return
    folder = hass.config.path(REPORT_WWW_DIR)
    try:
        await hass.async_add_executor_job(
            partial(os.makedirs, folder, exist_ok=True)
        )
        await hass.http.async_register_static_paths(
            [StaticPathConfig(REPORT_WWW_URL, folder, False)]
        )
    except Exception as err:  # noqa: BLE001 - a link is not the integration
        LOGGER.warning(
            "Device Sentinel could not serve %s at %s, so the daily "
            "brief and the dwell chart will not open until Home "
            "Assistant restarts once (%s)",
            REPORT_WWW_DIR,
            REPORT_WWW_URL,
            err,
        )
        return
    LOGGER.info(
        "Device Sentinel registered %s at %s for this session, because "
        "no www folder existed when the frontend started",
        REPORT_WWW_DIR,
        REPORT_WWW_URL,
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
    # Before anything writes into www, because the test is whether
    # the parent existed when the frontend looked.
    await _async_serve_www_folder(hass)

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
    LOGGER.debug("Device Sentinel unloading")
    # Nothing this integration raised may outlive it (rulings #240 and
    # #294). The issues are not persistent, so a restart clears them
    # on its own; this covers the reload and the uninstall, where
    # there is no restart to do it and a badge would otherwise stay
    # lit over an integration that is no longer running.
    async_clear_all(hass)
    await entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove everything the integration ever wrote (ruling #240).

    Runs when a person deletes the integration, after the unload. A
    tool whose pitch is that it costs almost nothing must also cost
    nothing to leave: both storage files with every backup copy taken
    beside them, the reports folder, and the www folder all go, so an
    uninstall leaves no trace for the person to find later and wonder
    about. Deliberately not part of unload, which also runs on every
    restart and reconfiguration; only deletion reaches here.

    Each target is removed on its own and a failure is logged rather
    than raised, because a folder that cannot be deleted must not
    abort the removal of the rest, and Home Assistant ignores errors
    from this hook anyway.
    """
    storage = Path(hass.config.path(STORAGE_DIR))
    report_dir = Path(hass.config.path(REPORT_DIR))
    www_dir = Path(hass.config.path(REPORT_WWW_DIR))

    def _remove_all() -> list[str]:
        removed: list[str] = []
        # The two live files and every suffixed backup beside them
        # (the pre-strip pair of ruling #130, the epoch copies of
        # ruling #204): the glob catches whatever suffixes exist
        # rather than a list somebody must remember to extend.
        for key in (STORAGE_KEY, STORAGE_CLOCKS_KEY):
            for path in storage.glob(f"{key}*"):
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError as err:
                    LOGGER.warning(
                        "Uninstall could not remove %s: %s", path, err
                    )
        for folder in (report_dir, www_dir):
            if not folder.exists():
                continue
            try:
                shutil.rmtree(folder)
                removed.append(f"{folder.name}/")
            except OSError as err:
                LOGGER.warning(
                    "Uninstall could not remove %s: %s", folder, err
                )
        return removed

    removed = await hass.async_add_executor_job(_remove_all)
    LOGGER.info(
        "Device Sentinel removed; deleted %d item(s): %s",
        len(removed),
        ", ".join(removed) or "nothing was on disk",
    )
