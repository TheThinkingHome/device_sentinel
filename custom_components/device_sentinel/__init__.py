# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: __init__.py, Version: 0.23.5 (2026-09-25)

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

import hashlib
import shutil
from typing import Any
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.loader import async_get_integration

from .dashboard_api import async_register_dashboard_api
from .const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    DEAD_OPTION_KEYS,
    DOMAIN,
    IGNORE_KEY_RENAMES,
    MUTING_KEY_RENAMES,
    LOGGER,
    CONF_LOW_THRESHOLD,
    LEGACY_LOW_THRESHOLD,
    OPTIONS_MINOR_VERSION,
    PANEL_URL_PATH,
    CONF_PERSISTENT_ENABLED,
    RETIRED_SLIDER_KEYS,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    REPORT_WWW_DIR,
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
    if entry.minor_version < 3:
        options = _migrate_ignore_name(options)
    if entry.minor_version < 4:
        options = _migrate_retired_sliders(options)
    if entry.minor_version < 5:
        options = _migrate_persistent_default(options)
    hass.config_entries.async_update_entry(
        entry, options=options, minor_version=OPTIONS_MINOR_VERSION
    )
    return True


def _migrate_persistent_default(options: dict[str, Any]) -> dict[str, Any]:
    """Step 5: keep the persistent card for an install that never chose.

    Until 0.22.5 the card defaulted to on, and an install that never
    saved its Notifications screen was running with it on. The default
    is now off for new installs (ruling #462), so this writes the old
    default down where nothing was saved. A saved choice, either way,
    is left exactly as it is.
    """
    migrated = dict(options)
    migrated.setdefault(CONF_PERSISTENT_ENABLED, True)
    return migrated


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


def _migrate_retired_sliders(options: dict[str, Any]) -> dict[str, Any]:
    """Step 4: five sliders become constants, and the battery
    threshold keeps its old value for anybody who never set one.

    The five were only ever sliders because their numbers were
    guesses, and neither fleet moved one off its default in the
    months since (ruling #394). The stored keys go, so an entry
    carrying a hand-edited value cannot quietly keep behaving
    differently from the constant the code now states.

    The threshold is the other half and runs the other way. Its
    default moves from twenty to fifteen, so an entry that never
    stored one would silently start judging batteries differently
    on upgrade. It is pinned at twenty here instead: the new default
    is for new installs, and an existing house changes only when its
    owner asks.
    """
    dropped = [key for key in RETIRED_SLIDER_KEYS if key in options]
    for key in dropped:
        options.pop(key)
    if CONF_LOW_THRESHOLD not in options:
        options[CONF_LOW_THRESHOLD] = LEGACY_LOW_THRESHOLD
        pinned = f"; low_threshold pinned at {LEGACY_LOW_THRESHOLD}"
    else:
        pinned = ""
    LOGGER.info(
        "Options migration step 4, retired sliders: %s%s",
        ", ".join(dropped) if dropped else "nothing stored to drop",
        pinned,
    )
    return options


def _migrate_ignore_name(options: dict[str, Any]) -> dict[str, Any]:
    """Step 3: the ignore list takes the word muting vacated.

    Same shape as step 2 and deliberately not folded into it: a
    person on this fleet ran step 2 a day before this one, while a
    person on the public release runs both in a single load, and one
    numbered chain makes those the same code rather than two.
    """
    moved: list[str] = []
    for old, new in IGNORE_KEY_RENAMES.items():
        if old not in options:
            continue
        value = options.pop(old)
        if new not in options:
            options[new] = value
        moved.append(f"{old} -> {new} ({len(value)})")
    if moved:
        LOGGER.info(
            "Options migration step 3, the exclude list: %s", "; ".join(moved)
        )
    else:
        LOGGER.info(
            "Options migration step 3, the exclude list: nothing stored to move"
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


def _retire_www_folder(hass: HomeAssistant) -> str | None:
    """Delete www/device_sentinel after moving the current brief out.

    Ruled 23 and 25 September 2026 (#470), built as 0.23.5. Home
    Assistant serves config/www at /local to anyone who asks, signed in
    or not, and the files there named devices, battery levels and
    outage times: all six returned 200 to a client that had not signed
    in. The battery and signal reports and the brief's dated copies are
    retired with the folder, and the brief lives on beside the other
    reports in config/device_sentinel, which Home Assistant does not
    serve.

    The whole folder goes, whatever else is in it: the owner ruled it
    so, and the release note tells a person to copy it first. The
    current brief is carried across unless one is already there, so
    the first read after the upgrade finds a brief. Runs in the
    executor, once per start, and does nothing once the folder is
    gone. Returns what it did for the log, or None when there was
    nothing to do.
    """
    folder = Path(hass.config.path(REPORT_WWW_DIR))
    if not folder.is_dir():
        return None
    moved = False
    brief = folder / REPORT_BRIEF_HTML
    target_dir = Path(hass.config.path(REPORT_DIR))
    target = target_dir / REPORT_BRIEF_HTML
    if brief.is_file() and not target.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(brief, target)
        moved = True
    files = sum(1 for path in folder.rglob("*") if path.is_file())
    shutil.rmtree(folder)
    return (
        f"deleted {REPORT_WWW_DIR} and the {files} file(s) in it"
        + (f", after moving the current brief to {REPORT_DIR}" if moved else "")
    )


async def _async_retire_www_folder(hass: HomeAssistant) -> None:
    """Run the retirement off the event loop; never fail the setup.

    A folder that cannot be deleted leaves the old files where they
    were, which is how every earlier release left them, so it is
    logged and the start goes on.
    """
    try:
        done = await hass.async_add_executor_job(_retire_www_folder, hass)
    except OSError as err:
        LOGGER.warning(
            "Device Sentinel could not delete %s, which it no longer "
            "writes; remove it by hand (%s)",
            REPORT_WWW_DIR,
            err,
        )
        return
    if done:
        LOGGER.info("Device Sentinel %s", done)


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
    # Before the first report write, so the brief the folder held is
    # in its new home when the writer looks for it (0.23.5).
    await _async_retire_www_folder(hass)

    coordinator = DeviceSentinelCoordinator(hass, entry, version)
    await coordinator.async_setup()
    async_register_dashboard_api(hass)
    await _async_register_panel(hass)

    entry.runtime_data = coordinator
    # Options changes (the battery threshold today) apply live: the
    # listener re-judges the fleet without a reload or restart.
    entry.async_on_unload(
        entry.add_update_listener(_async_options_updated)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


PANEL_ELEMENT = "device-sentinel-panel"
PANEL_STATIC_ROOT = "/device_sentinel_panel"
_PANEL_SERVED = f"{DOMAIN}_panel_served"


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Put the dashboard in the sidebar, for admins only.

    The module's address carries a hash of its contents: the frontend's
    service worker serves a stale copy of an address it has seen before,
    whatever query string is added, so a changed file needs a new name.
    A static path cannot be removed once registered, so each address is
    registered once per run and a reload reuses it. Registration writes
    to Home Assistant's panel table and needs nothing else loaded, which
    is why `frontend` is an after-dependency rather than a requirement.
    """
    module = Path(__file__).parent / "frontend" / "panel.js"
    digest = await hass.async_add_executor_job(
        lambda: hashlib.sha256(module.read_bytes()).hexdigest()[:12]
    )
    url = f"{PANEL_STATIC_ROOT}/panel.{digest}.js"
    served: set[str] = hass.data.setdefault(_PANEL_SERVED, set())
    try:
        if url not in served:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(url, str(module), True)]
            )
            served.add(url)
    except Exception as err:  # noqa: BLE001 - the dashboard never stops setup
        # A dashboard that cannot be served is a missing page, not a
        # broken integration: detection, reports and alerts carry on.
        LOGGER.warning("Device Sentinel could not serve its dashboard: %s", err)
        return
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Device Sentinel",
        sidebar_icon="mdi:shield-check-outline",
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_ELEMENT,
                "module_url": url,
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=True,
        update=True,
    )


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
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
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
