# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: diagnostics.py, Version: 0.7.0 (2026-07-22)

"""Diagnostics support for the Device Sentinel integration.

The Download Diagnostics button on the integration page produces one
JSON file carrying the integration's whole learned state: every
device's rhythm history and clock, its signal baseline, its battery
verdict, the classification, the exclusions, and the tunables in
effect. It exists so a bug report is one click rather than an SSH
session, and so a doubted detection can be judged from evidence
rather than description.

It complements device_telemetry.md rather than repeating it: the
Markdown file is human triage for the owner, this is the complete
machine-readable record for the maintainer. Device names are included
because a report without them is unreadable; nothing here is
sensitive, but the config entry is redacted as a matter of course
since it carries the user's notification targets.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import DeviceSentinelConfigEntry
from .const import (
    BATTERY_CLEAR_MARGIN,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_STATS_EPOCH,
    DATA_TODO_ITEMS,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_TODO_JOURNAL,
    LEARNING_MIN_DAYS,
    SIGNAL_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    TAINT_DEBOUNCE_SECONDS,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)

# The notification targets are the user's own device names; they add
# nothing to a diagnosis and are redacted by default.
TO_REDACT = {CONF_HIGH_PRIORITY_TARGETS, CONF_NORMAL_PRIORITY_TARGETS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> dict[str, Any]:
    """Return the integration's learned state as diagnostics."""
    coordinator = entry.runtime_data
    device_registry = dr.async_get(hass)

    devices: dict[str, Any] = {}
    for device_id, record in coordinator.data[DATA_DEVICES].items():
        device = device_registry.async_get(device_id)
        daily_maximum_gaps = record.get("daily_max") or []
        window_basis, set_aside_indices = coordinator._trimmed_maximum(
            daily_maximum_gaps
        )
        # The floor is the line (0.4.3): one computation, rails
        # filtered, the trim ladder applied. signal_floor is kept as
        # a key for reader continuity and equals the line.
        signal_line = coordinator._danger_line(record)
        devices[device_id] = {
            "name": (
                (device.name_by_user or device.name)
                if device
                else None
            ),
            "integration": coordinator._watched.get(device_id),
            "clock_source": (
                "last_seen"
                if device_id in coordinator._last_seen_entity
                else "recorded"
            ),
            "excluded": coordinator._excluded_devices.get(device_id),
            "statistics": record,
            "window_basis": window_basis,
            "set_aside_indices": sorted(set_aside_indices),
            "signal_floor": signal_line,
            # The dwell soak (0.4.0): the danger line the timer runs
            # against, yesterday's percent-below history, and the
            # stuck flag. RSSI rows (negative floors) are provisional:
            # eleven devices and barely-seen floors do not yet justify
            # trusting the offset.
            "signal_danger_line": signal_line,
            "signal_dwell_daily_pct": list(
                record.get("signal_dwell_daily_pct") or []
            ),
            "signal_below_today_seconds": record.get(
                "signal_below_today_seconds"
            ),
            "signal_excluded": coordinator._signal_excluded(device_id),
            # A rail is confirmed when the daily low sits at the fill
            # value for three consecutive days (0.4.8).
            "signal_railed": coordinator.signal_railed(record),
            # The discharge soak (0.4.2): the daily level series and
            # the deltas derived from it (a positive delta is a drop).
            # Provisional and short until it has depth; the velocity
            # flag reads it in a later release.
            "battery_daily_value": list(
                record.get("battery_daily_value") or []
            ),
            "battery_daily_delta": [
                round(a - b, 2)
                for a, b in zip(
                    (record.get("battery_daily_value") or [])[:-1],
                    (record.get("battery_daily_value") or [])[1:],
                )
            ],
        }

    return {
        "version": coordinator.version,
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "storage": {
            "first_installed": coordinator.first_installed,
            "setup_count": coordinator.setup_count,
            "stats_epoch": coordinator.data.get(DATA_STATS_EPOCH),
        },
        "tunables": {
            "startup_grace_seconds": STARTUP_GRACE_SECONDS,
            "storm_device_threshold": STORM_DEVICE_THRESHOLD,
            "storm_window_seconds": STORM_WINDOW_SECONDS,
            "storm_release_seconds": STORM_RELEASE_SECONDS,
            "storm_exempt_per_hour": STORM_EXEMPT_PER_HOUR,
            "taint_debounce_seconds": TAINT_DEBOUNCE_SECONDS,
            "daily_max_keep": DAILY_MAX_KEEP,
            "learning_min_days": LEARNING_MIN_DAYS,
            "trim_top_k": TRIM_TOP_K,
            "trim_min_samples": TRIM_MIN_SAMPLES,
            "signal_arming_days": SIGNAL_ARMING_DAYS,
            "battery_low_threshold": coordinator.low_threshold,
            "battery_clear_margin": BATTERY_CLEAR_MARGIN,
        },
        "classification": {
            "watched": len(coordinator._watched),
            "set_aside": len(coordinator._set_aside),
            "deviceless_entities": coordinator.deviceless_count,
            "excluded_devices": coordinator._excluded_devices,
            "excluded_entities": coordinator._excluded_entities,
            "storm_exempt_entries": sorted(coordinator._storm_exempt),
        },
        "battery": {
            "low_count": coordinator.battery_low_count,
            "low_list": coordinator.battery_low_list,
        },
        "todo_items": coordinator.data.get(DATA_TODO_ITEMS, []),
        "todo_journal": coordinator.data.get(DATA_TODO_JOURNAL, []),
        # The silence episodes behind silence_episodes.md: a feed
        # belongs in the download, where a maintainer can read the
        # raw timestamps the report renders (#103).
        "silence_episodes": coordinator.data.get(DATA_EPISODES, []),
        # The incident timeline every renderer reads (#107).
        "incidents": coordinator.data.get(DATA_INCIDENTS, []),
        "devices": devices,
    }
