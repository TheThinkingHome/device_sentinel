# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: __init__.py, Version: 0.27.10 (2026-10-27)

"""The Device Sentinel integration.

Watches hardware liveness: frozen devices, unavailable devices, low
batteries, and weak radio links, with per-device freeze windows
learned from each device's own reporting rhythm rather than
hand-assigned tiers.

It tells a person through a problem list, a dashboard, pushes and a
daily brief, raises Repairs for what needs their hand, and fires bus
events an automation can trigger on. This file sets it up, migrates a
stored entry's options, and cleans up after it when it is deleted.
"""

from __future__ import annotations

import hashlib
import shutil
from typing import Any
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.loader import async_get_integration

from .dashboard_api import async_register_dashboard_api
from .const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_LABELS,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_LABELS,
    DATA_PANEL_FILE,
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
    CONF_DASHBOARD_MODE,
    CONF_PERSISTENT_ENABLED,
    DASHBOARD_ADVANCED,
    RETIRED_SLIDER_KEYS,
    PROBE_FILE_ROLLS,
    REPORT_BRIEF_HTML,
    REPORT_CLASSIFICATION,
    REPORT_DIAGNOSTIC_DIR,
    REPORT_DIR,
    REPORT_EPISODES,
    REPORT_STACK_PROBE,
    REPORT_STALE_FILES,
    REPORT_TELEMETRY,
    REPORT_WWW_DIR,
    TRIM_BACKUP_DIR,
    STORAGE_CLOCKS_KEY,
    STORAGE_HISTORY_KEY,
    STORAGE_KEY,
)
from .answers_store import ANSWERS_STORE_KEY, LEGACY_POWER_KEY
from .coordinator import DeviceSentinelCoordinator
from .repairs import async_clear_all

# No NUMBER platform. The battery threshold is set in the options
# dialog with the setting beside it, so there is one place for both
# rather than a slider for one of them.
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

    The steps are numbered rather than applied as a set, because a house
    that upgrades one release at a time and one that jumps several
    arrive differently. Numbering makes those the same code path,
    applied in order from wherever the entry sits (rule STOR-19).
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
    if entry.minor_version < 6:
        options = _migrate_unavailable_mutes(options)
    if entry.minor_version < 7:
        options = _migrate_dashboard_mode(options)
    hass.config_entries.async_update_entry(
        entry, options=options, minor_version=OPTIONS_MINOR_VERSION
    )
    return True


def _migrate_unavailable_mutes(options: dict[str, Any]) -> dict[str, Any]:
    """Step 6: a label or device muted for freeze is muted for unavailable.

    A freeze mute once also silenced unavailable. The two are separate
    now, so for nothing to change on an upgraded house, each label and
    device muted for freeze is given the unavailable mute as well, once.
    An integration muted for freeze stays freeze only, the one change of
    behavior. Lists already set are kept, with the freeze picks added to
    them (rule MUTE-06).
    """
    migrated = dict(options)
    for freeze_key, unavailable_key in (
        (CONF_FREEZE_MUTED_LABELS, CONF_UNAVAILABLE_MUTED_LABELS),
        (CONF_FREEZE_MUTED_DEVICES, CONF_UNAVAILABLE_MUTED_DEVICES),
    ):
        picks = _string_list(options.get(freeze_key))
        if not picks:
            continue
        merged = _string_list(options.get(unavailable_key))
        for pick in picks:
            if pick not in merged:
                merged.append(pick)
        migrated[unavailable_key] = merged
    return migrated


def _string_list(value: Any) -> list[str]:
    """The strings of a stored list, once each, in order.

    Anything that is not a list (a hand-edited string, a mapping) gives
    nothing, rather than its characters or keys.
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item not in out:
            out.append(item)
    return out


def _migrate_dashboard_mode(options: dict[str, Any]) -> dict[str, Any]:
    """Step 7: an install that upgrades keeps the dashboard it knows.

    Simple is the default dashboard for a new install. An install that
    upgrades opens in Advanced,
    the dashboard as it was, until someone changes the setting
    (rule DASH-03).
    """
    migrated = dict(options)
    migrated.setdefault(CONF_DASHBOARD_MODE, DASHBOARD_ADVANCED)
    return migrated


def _migrate_persistent_default(options: dict[str, Any]) -> dict[str, Any]:
    """Step 5: keep the persistent card for an install that never chose.

    The card once defaulted to on, and an install that never saved its
    Notifications screen was running with it on. The default is now off
    for new installs (rule NOTE-11), so this writes the old default down
    where nothing was saved. A saved choice, either way,
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
        LOGGER.debug(
            "Options migration step 2, muting names: nothing stored to move"
        )
    return options


def _migrate_retired_sliders(options: dict[str, Any]) -> dict[str, Any]:
    """Step 4: five sliders become constants, and the battery
    threshold keeps its old value for anybody who never set one.

    The stored keys go, so an entry carrying a hand-edited value cannot
    quietly behave differently from the constant the code states.

    The threshold is the other half and runs the other way. Its
    default moves from twenty to fifteen, so an entry that never
    stored one would silently start judging batteries differently
    on upgrade. It is pinned at twenty here instead: the new default
    is for new installs, and an existing house changes only when its
    owner asks (rule BAT-03).
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

    Same shape as step 2 and kept apart from it, because an entry may
    have run step 2 alone, and one numbered chain makes that and a load
    running both the same code rather than two.
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
        LOGGER.debug(
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

    Home Assistant serves config/www at /local to anyone who asks,
    signed in or not, and the files there name devices, battery levels
    and outage times. The brief lives beside the other reports in
    config/device_sentinel, which Home Assistant does not serve
    (rule BRIEF-14).

    The whole folder goes, whatever else is in it. The current brief is
    carried across unless one is already there, so the first read after
    the upgrade finds a brief. Runs in the executor, once per start, and
    does nothing once the folder is gone. Returns what it did for the
    log, or None when there was nothing to do.
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
    were, so it is logged and the start goes on.
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
    # in its new home when the writer looks for it.
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

    The hash is kept for the dashboard (rule DASH-14). A tab left open across
    an update runs the file it loaded, and Home Assistant hands it the
    new one, which cannot register the same element a second time; the
    tab compares the hash it was loaded with against the one served and
    offers a reload when they differ.
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
    hass.data[DATA_PANEL_FILE] = digest
    # Registered the way a custom panel is meant to be (rule DASH-01), through
    # panel_custom, which builds the same "custom" panel underneath.
    # panel_custom offers no update flag and refuses a path already
    # registered, so a panel left from an earlier setup is taken down
    # first; the unload does that too, and this covers a setup that
    # runs again without one.
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="Device Sentinel",
        sidebar_icon="mdi:shield-check-outline",
        module_url=url,
        embed_iframe=False,
        trust_external=False,
        require_admin=True,
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
    # Nothing this integration raised may outlive it (rules STOR-24,
    # REP-04). The issues are not persistent, so a restart clears them
    # on its own; this covers the reload and the uninstall, where
    # there is no restart to do it and a badge would otherwise stay
    # lit over an integration that is no longer running.
    async_clear_all(hass)
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _own_report_files() -> list[str]:
    """Every file name Device Sentinel writes in its reports folder (rule STOR-24):
    the three maintainer reports, the brief, the stack probe file and its
    rolled copies, and the names older releases wrote."""
    probe = [REPORT_STACK_PROBE] + [
        f"{REPORT_STACK_PROBE}.{n}" for n in range(1, PROBE_FILE_ROLLS + 1)
    ]
    return [
        REPORT_TELEMETRY,
        REPORT_CLASSIFICATION,
        REPORT_EPISODES,
        REPORT_BRIEF_HTML,
        *probe,
        *REPORT_STALE_FILES,
    ]


async def async_remove_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove everything the integration ever wrote (rule STOR-24).

    Runs when a person deletes the integration, after the unload. A
    tool whose pitch is that it costs almost nothing must also cost
    nothing to leave: every storage file with every backup copy taken
    beside them, every file it wrote in the reports folder, and the www
    folder all go, so an uninstall leaves no trace for the person to
    find later and wonder about. Only its own: the reports folder goes
    once it is empty, so a file another tool or a person keeps there
    stays. Deliberately not part of unload, which also runs on every
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
        # (older pre-strip and epoch copies among them): the glob catches
        # whatever suffixes exist rather than a list somebody must
        # remember to extend. The answers file, and the older power
        # file it replaced, which older releases left behind on uninstall.
        for key in (STORAGE_KEY, STORAGE_CLOCKS_KEY, STORAGE_HISTORY_KEY, ANSWERS_STORE_KEY, LEGACY_POWER_KEY):
            for path in storage.glob(f"{key}*"):
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError as err:
                    LOGGER.warning(
                        "Uninstall could not remove %s: %s", path, err
                    )
        # The reports folder holds only what Device Sentinel names, so
        # only that goes: other tools may keep files beside it, and a
        # person may too.
        # The folder itself goes only once it is empty. The www folder
        # is Device Sentinel's alone and goes whole.
        for name in _own_report_files():
            for path in (report_dir / name, report_dir / f"{name}.tmp"):
                if not path.is_file():
                    continue
                try:
                    path.unlink()
                    removed.append(f"{report_dir.name}/{path.name}")
                except OSError as err:
                    LOGGER.warning("Uninstall could not remove %s: %s", path, err)
        for folder in (
            report_dir / REPORT_DIAGNOSTIC_DIR,
            Path(hass.config.path(TRIM_BACKUP_DIR)),
            www_dir,
        ):
            if not folder.is_dir():
                continue
            try:
                shutil.rmtree(folder)
                removed.append(f"{folder.name}/")
            except OSError as err:
                LOGGER.warning(
                    "Uninstall could not remove %s: %s", folder, err
                )
        if report_dir.is_dir():
            left = sorted(p.name for p in report_dir.iterdir())
            if not left:
                try:
                    report_dir.rmdir()
                    removed.append(f"{report_dir.name}/")
                except OSError as err:
                    LOGGER.warning("Uninstall could not remove %s: %s", report_dir, err)
            else:
                LOGGER.info(
                    "Uninstall left %s in place: it holds files Device "
                    "Sentinel did not write (%s)",
                    report_dir,
                    ", ".join(left[:10]),
                )
        return removed

    removed = await hass.async_add_executor_job(_remove_all)
    LOGGER.info(
        "Device Sentinel removed; deleted %d item(s): %s",
        len(removed),
        ", ".join(removed) or "nothing was on disk",
    )
