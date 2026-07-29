# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: diagnostics.py, Version: 0.10.7 (2026-07-29)

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
    EP_LEARNED,
    BATTERY_CLEAR_MARGIN,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_STATS_EPOCH,
    DATA_TODO_ITEMS,
    DATA_EPISODES,
    DATA_INCIDENTS,
    CLOCK_FIELDS,
    DIAGNOSTIC_SERIES_CAP,
    DATA_SAVED_AT,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_JOURNAL,
    LEARNING_MIN_DAYS,
    SIGNAL_ARMING_DAYS,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    STORM_RELEASE_SECONDS,
    STORM_WINDOW_SECONDS,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEFAULT_TAINT_SHARE_PCT,
    CONF_TAINT_FLOOR,
    CONF_TAINT_SHARE,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)

# The notification targets are the user's own device names; they add
# nothing to a diagnosis and are redacted by default.
TO_REDACT = {CONF_HIGH_PRIORITY_TARGETS, CONF_NORMAL_PRIORITY_TARGETS}


def _taint_reasons(episodes: list[dict[str, Any]]) -> dict[str, int]:
    """Count the retained episodes by why their gap went unlearned.

    Keyed by the reason as the report prints it, so a reader compares
    this against silence_episodes.md without translating. Episodes
    that fed learning are counted under "yes" for the denominator.
    """
    counts: dict[str, int] = {}
    for episode in episodes:
        learned = episode.get(EP_LEARNED)
        if learned is None:
            continue
        counts[learned] = counts.get(learned, 0) + 1
    return dict(sorted(counts.items()))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> dict[str, Any]:
    """Return the integration's learned state as diagnostics."""
    coordinator = entry.runtime_data
    device_registry = dr.async_get(hass)

    devices: dict[str, Any] = {}
    for device_id, record in coordinator.data[DATA_DEVICES].items():
        device = device_registry.async_get(device_id)
        # The judgment window, so the indices returned line up with
        # what a reader sees rather than with the whole series.
        daily_maximum_gaps = (record.get("daily_max") or [])[
            -DAILY_MAX_KEEP:
        ]
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
                (record.get("signal_dwell_daily_pct") or [])[-DIAGNOSTIC_SERIES_CAP:]
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
                (record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:]
            ),
            "battery_daily_delta": [
                round(a - b, 2)
                for a, b in zip(
                    ((record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:])[:-1],
                    ((record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:])[1:],
                )
            ],
        }

    hot = await coordinator._clock_store.async_load()
    cold_at = coordinator.data.get(DATA_SAVED_AT)
    hot_at = (hot or {}).get(DATA_SAVED_AT)
    behind = (
        round(hot_at - cold_at, 1)
        if isinstance(cold_at, (int, float)) and isinstance(hot_at, (int, float))
        else None
    )
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
            "taint_floor_minutes": entry.options.get(
                CONF_TAINT_FLOOR, DEFAULT_TAINT_FLOOR_MINUTES
            ),
            "taint_share_pct": entry.options.get(
                CONF_TAINT_SHARE, DEFAULT_TAINT_SHARE_PCT
            ),
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
            # Coordinator stacks detected in this house (#143). Derived
            # from the registry each rebuild, the whole visible surface
            # of stack auto-detection; every later intervention detector
            # attaches only where its stack appears here.
            "stacks": sorted(coordinator._stacks),
            # Each detected bridge's current state (running, binding,
            # down, unknown), so a pairing-discarded gap is auditable
            # from a diagnostics download and not only from the live
            # sensor (#149).
            "bridge_state": {
                stack: coordinator.bridge_state(stack)
                for stack in coordinator.bridge_stacks
            },
            "excluded_devices": coordinator._excluded_devices,
            "excluded_entities": coordinator._excluded_entities,
            "storm_exempt_entries": sorted(coordinator._storm_exempt),
        },
        "battery": {
            "low_count": coordinator.battery_low_count,
            "low_list": coordinator.battery_low_list,
        },
        # What the house's exclusions are actually made of (#164).
        # Counted from the episode record rather than from the live
        # flags, because a taint is spent the moment the device
        # speaks and the standing count is almost always zero, while
        # the question worth answering is whether a season of
        # unlearned gaps was the bridge or the devices.
        "taint_reasons": _taint_reasons(
            coordinator.data.get(DATA_EPISODES, [])
        ),
        "todo_items": coordinator.data.get(DATA_TODO_ITEMS, []),
        "todo_journal": coordinator.data.get(DATA_TODO_JOURNAL, []),
        "system_events": coordinator.data.get(
            DATA_SYSTEM_EVENTS, []
        ),
        # The silence episodes behind silence_episodes.md: a feed
        # belongs in the download, where a maintainer can read the
        # raw timestamps the report renders (#103).
        "silence_episodes": coordinator.data.get(DATA_EPISODES, []),
        # The incident timeline every renderer reads (#107).
        "incidents": coordinator.data.get(DATA_INCIDENTS, []),
        # What the engine would have said, composed but never sent
        # while the dry run lasts (#120).
        # The storage split, so its state travels with an issue
        # report rather than needing a terminal (0.8.8).
        "split": {
            "clock_fields": list(CLOCK_FIELDS),
            "clock_devices": len(coordinator.data.get(DATA_DEVICES, {})),
            "phase": "B: hot file written routinely and read on load",
            # Both stamps, so this file can answer on its own whether
            # the split is healthy: the hot one should be the newer,
            # and the gap is how far the main file is behind.
            "storage_saved_at": coordinator.data.get(DATA_SAVED_AT),
            "clocks_saved_at": (hot or {}).get(DATA_SAVED_AT),
            "main_file_behind_seconds": behind,
        },
        "devices": devices,
    }
