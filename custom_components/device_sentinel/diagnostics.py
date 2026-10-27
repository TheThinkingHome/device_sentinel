# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: diagnostics.py, Version: 0.27.10 (2026-10-27)

"""Diagnostics support for the Device Sentinel integration.

The Download Diagnostics button on the integration page produces one
JSON file carrying the integration's whole learned state: every
device's rhythm history and clock, its signal baseline, its battery
verdict, the classification, the muting, and the tunables in
effect. It exists so a bug report is one click rather than an SSH
session, and so a doubted detection can be judged from evidence
rather than description.

It complements device_telemetry.md rather than repeating it: the
Markdown file is human triage for the owner, this is the complete
machine-readable record for the maintainer. Device names are included
because a report without them is unreadable. Network addresses are
not: testers attach this file to public issues, so every MAC address
keeps only its maker's half and every home-network address becomes a
stand-in, the same one throughout the file (rule STOR-21). The config entry
is redacted as a matter of course, since it carries the user's
notification targets.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import os
import re
from collections.abc import Callable
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import DeviceSentinelConfigEntry, history_file
from .const import (
    DATA_SIGNAL_STRESS,
    BROKER_SCOPE,
    INFRASTRUCTURE_DEVICE_CAP,
    ROUTER_DOMAINS,
    CONF_STUDY_HARDWARE,
    DATA_STORMS,
    EP_LEARNED,
    BATTERY_CLEAR_MARGIN,
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DEV_HELD_VALUES,
    DATA_HISTORY_LINE,
    DATA_LAST_VERSION,
    DATA_BATTERY_FORECAST_TALLY,
    DATA_BATTERY_EMPTY_TALLY,
    DATA_BATTERY_LIVES,
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
    TAINT_FLOOR_MINUTES,
    TAINT_SHARE_PCT,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)
from .study import studied_domains
from .study_lutron import LUTRON_DOMAIN as LUTRON_STUDY_DOMAIN, lutron_study
from .study_stacks import (
    HUE_DOMAIN,
    MATTER_DOMAIN,
    SMARTTHINGS_DOMAIN,
    ZWAVE_DOMAIN,
    matter_study,
    zwave_study,
)
from .device_fields import device_field

# The notification targets are the user's own device names; they add
# nothing to a diagnosis and are redacted by default. The brief's
# targets are redacted too, because a notify service is often named
# after an email address, as notify.someone_gmail_com, and the
# diagnostics are what testers attach to public issues.
TO_REDACT = {
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
}


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


def _diagnostic_entities(
    hass: HomeAssistant, coordinator: Any, device_id: str
) -> list[dict[str, Any]]:
    """Return the device's diagnostic entities, enabled or not.

    Read live from the registry at download time and stored nowhere,
    the same matchers the Switched Off cards read (rule REC-05), so
    what this reports and what a card lists cannot drift apart.
    """
    ent_reg = er.async_get(hass)
    rows: list[dict[str, Any]] = []
    for ent in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=True
    ):
        if coordinator._is_signal(ent):
            kind = "signal"
        elif coordinator._is_battery(ent):
            kind = "battery"
        elif coordinator._is_last_seen(ent):
            kind = "last_seen"
        else:
            continue
        state = hass.states.get(ent.entity_id)
        rows.append(
            {
                "entity_id": ent.entity_id,
                "kind": kind,
                # Which integration published it, and whether that is
                # the device's own (rule WATCH-02). Without this a
                # series that changed which sensor it reads cannot be
                # told from a cell that was changed.
                "platform": ent.platform,
                "own": ent.platform == coordinator._watched.get(device_id),
                "elected": ent.entity_id
                in (
                    (coordinator._battery_entity.get(device_id) or ("",))[0],
                    coordinator._last_seen_entity.get(device_id),
                )
                or ent.entity_id in coordinator._signal_entities,
                "disabled_by": (
                    str(ent.disabled_by.value)
                    if ent.disabled_by is not None
                    else None
                ),
                "state": state.state if state else None,
            }
        )
    return rows


def _all_entities(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """Return every entity the registry holds for the device.

    What a device is can only be read from what it reports, since Home
    Assistant keeps no type for a device, and the rules that will name
    it (a camera entity, a cover, a moisture sensor) cannot be tested
    on a real house while the diagnostics carry only the battery,
    signal and Last seen entities. Each row is what those rules read:
    the domain, the integration that published it, its device class
    and unit, its category, and whether it is disabled. No state: the
    rules do not need one, and a state can say whether a door is open
    or someone is home.

    Read live from the registry at download time and stored nowhere
    (rule DEV-10).
    """
    ent_reg = er.async_get(hass)
    rows: list[dict[str, Any]] = []
    for ent in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=True
    ):
        rows.append(
            {
                "entity_id": ent.entity_id,
                "domain": ent.domain,
                "platform": ent.platform,
                # The person's choice over the integration's, as Home
                # Assistant itself resolves it.
                "device_class": ent.device_class or ent.original_device_class,
                "unit": ent.unit_of_measurement,
                "category": (
                    str(ent.entity_category.value)
                    if ent.entity_category is not None
                    else None
                ),
                "disabled_by": (
                    str(ent.disabled_by.value)
                    if ent.disabled_by is not None
                    else None
                ),
            }
        )
    return sorted(rows, key=lambda row: row["entity_id"])


def _infrastructure(
    hass: HomeAssistant, coordinator: Any
) -> dict[str, Any]:
    """Return what the house's plumbing is, not just how it behaves.

    Every other part of this file says what a coordinator, a broker
    or a router did. None of it says what any of them are, so a
    report describing a stack misbehaving cannot be matched against
    that hardware's own documentation, and the only way to learn the
    model has been to ask (rule DEV-16).

    Read live from the registry and the config entries, stored
    nowhere. One entry per domain that carries the house: the stacks
    the coordinator detected, the broker if MQTT is running, and any
    router integration whose device trackers the tie reader could be
    using.
    """
    device_registry = dr.async_get(hass)
    domains: set[str] = set(coordinator._stacks or ())
    domains.update(ROUTER_DOMAINS)
    domains.add(BROKER_SCOPE)

    out: dict[str, Any] = {}
    for domain in sorted(domains):
        entries = hass.config_entries.async_entries(domain)
        if not entries:
            continue
        hardware: list[dict[str, Any]] = []
        for entry in entries:
            for device in dr.async_entries_for_config_entry(
                device_registry, entry.entry_id
            ):
                hardware.append(
                    {
                        "name": device.name_by_user or device.name,
                        "manufacturer": device.manufacturer,
                        "model": device.model,
                        "sw_version": device.sw_version,
                        "hw_version": device.hw_version,
                        "via_device": device.via_device_id is not None,
                    }
                )
        out[domain] = {
            "entries": [entry.title for entry in entries],
            "state": [str(entry.state) for entry in entries],
            "devices": hardware[:INFRASTRUCTURE_DEVICE_CAP],
            "device_count": len(hardware),
        }
    return out


async def _studied(read: Callable[[], Any]) -> dict[str, Any]:
    """One stack's study for the download, or what stopped it.

    The study reads a library's live objects, and one that throws must
    not fail the whole download, which is how a tester sends what
    Extended Diagnostics found. The error is recorded in its place.
    """
    try:
        result = read()
        if inspect.isawaitable(result):
            result = await result
    except Exception as err:  # noqa: BLE001 - the download must still arrive
        return {"unreadable": f"{type(err).__name__}: {err}"}
    return result if isinstance(result, dict) else {}



# Network addresses are redacted from the download, because testers
# attach it to public GitHub issues. Each distinct address gets a
# numbered stand-in, the same wherever it appears, so a device still
# reads as the same device in every section and a fault can still be
# traced. A MAC keeps its first half, which names only the maker
# (20:F8:3B is Espressif) and often tells what a device is.
# Exactly six pairs: a pair and a separator before the first, or a
# separator and a pair after the sixth, means a longer run, such as
# ZHA's eight-pair Zigbee address, which is kept whole rather than
# half hidden (rule STOR-21).
_MAC = re.compile(
    r"(?<![0-9A-Fa-f]{2}[:-])\b([0-9A-Fa-f]{2})([:-])([0-9A-Fa-f]{2})\2([0-9A-Fa-f]{2})"
    r"(?:\2[0-9A-Fa-f]{2}){3}\b(?![:-][0-9A-Fa-f]{2})"
)
# The same address without separators, and in the dotted form, as some
# integrations register a device. A bare token counts only with a
# letter A to F in it, so a plain run of digits is never taken for one
# (rule STOR-21).
_MAC_BARE = re.compile(r"(?<![0-9A-Za-z])[0-9A-Fa-f]{12}(?![0-9A-Za-z])")
_MAC_DOTTED = re.compile(r"(?<![0-9A-Za-z.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Za-z.])")
# Only a home network's addresses, or the host of a web address: four
# dotted numbers are also how some firmware spells a version, and a
# version is the first thing a fault report needs.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IPV4 = re.compile(
    r"(?:(?<=://)" + _OCTET + r"(?:\." + _OCTET + r"){3}"
    r"|\b(?:10|127)(?:\." + _OCTET + r"){3}"
    r"|\b172\.(?:1[6-9]|2\d|3[01])(?:\." + _OCTET + r"){2}"
    r"|\b192\.168(?:\." + _OCTET + r"){2}"
    r"|\b169\.254(?:\." + _OCTET + r"){2})\b"
)


def _redact_addresses(payload: Any) -> Any:
    """Return the payload with every MAC address and every home-network
    or web-host IPv4 address replaced; a version that looks like an
    address is left alone."""
    macs: dict[str, str] = {}
    ips: dict[str, str] = {}

    def stand_in(hex12: str) -> str:
        """Every spelling of one address gets the one stand-in."""
        whole = ":".join(hex12[i:i + 2] for i in range(0, 12, 2)).upper()
        if whole not in macs:
            macs[whole] = f"MAC-{len(macs) + 1:02d}"
        return f"{whole[:8]}:{macs[whole]}"

    def mac(match: re.Match[str]) -> str:
        return stand_in(re.sub(r"[:-]", "", match.group(0)))

    def mac_bare(match: re.Match[str]) -> str:
        token = match.group(0)
        if not re.search(r"[A-Fa-f]", token):
            return token
        return stand_in(token)

    def mac_dotted(match: re.Match[str]) -> str:
        return stand_in(match.group(0).replace(".", ""))

    def ip(match: re.Match[str]) -> str:
        whole = match.group(0)
        if whole not in ips:
            ips[whole] = f"IP-{len(ips) + 1:02d}"
        return ips[whole]

    def text(value: str) -> str:
        value = _MAC.sub(mac, value)
        value = _MAC_DOTTED.sub(mac_dotted, value)
        value = _MAC_BARE.sub(mac_bare, value)
        return _IPV4.sub(ip, value)

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return text(value)
        if isinstance(value, dict):
            return {
                (text(k) if isinstance(k, str) else k): walk(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [walk(v) for v in value]
        return value

    return walk(payload)

def _addresses(device: Any, key: bytes) -> list[str]:
    """A device's addresses as "kind:fingerprint", sorted.

    Ten hex characters of an HMAC of the address under a key made for
    this download alone: two devices with the same address show the
    same fingerprint inside one file, which is all a reader needs. A
    plain hash could be reversed by trying every address a maker uses,
    and a fresh key means nothing outside the file can be looked up
    (rule STOR-21).
    """
    found = []
    for item in device_field(device, "connections", set()) or ():
        if isinstance(item, (tuple, list)) and len(item) == 2:
            kind, value = item
            digest = hmac.new(key, str(value).lower().encode("utf-8"), hashlib.sha256).hexdigest()[:10]
            found.append(f"{kind}:{digest}")
    return sorted(found)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceSentinelConfigEntry
) -> dict[str, Any]:
    """Return the integration's learned state as diagnostics."""
    coordinator = entry.runtime_data
    device_registry = dr.async_get(hass)
    # Fingerprints match inside this download only.
    address_key = os.urandom(16)

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
        devices[device_id] = {
            # A removed device whose record is held keeps the name it
            # had (rule WATCH-07).
            "name": (
                (device.name_by_user or device.name)
                if device
                else record.get("removed_name")
            ),
            # Read live from the registry, stored nowhere. Two
            # questions a report cannot answer without it: which
            # coordinator or router somebody runs when their stack
            # misbehaves, and whether a battery library would match
            # their fleet at all (rule DEV-16).
            # A child device carries none of these, and reads
            # None through device_field rather than a deprecation line.
            "manufacturer": device_field(device, "manufacturer"),
            "model": device_field(device, "model"),
            # Finer than the display name where a device gives it, and
            # what a model group is keyed on (rule DEV-14).
            "model_id": device_field(device, "model_id"),
            "sw_version": device_field(device, "sw_version"),
            "hw_version": device_field(device, "hw_version"),
            # A set-aside device's integration comes from why it was set
            # aside: the fourth fleet's excluded Spook devices read None.
            "integration": coordinator._watched.get(device_id)
            or (coordinator._set_aside.get(device_id) or (None, None, None))[1],
            # Entities other integrations added to this device, by
            # integration, counted over the whole registry rather than
            # only the entities read above. None of them counts as the
            # device reporting (rule WATCH-02).
            "foreign_entities": dict(
                coordinator._foreign_by_device.get(device_id) or {}
            ),
            "clock_source": (
                "last_seen"
                if device_id in coordinator._last_seen_entity
                else "recorded"
            ),
            "muted": coordinator._muted_devices.get(device_id),
            # Every diagnostic entity this device offers, enabled or
            # not, with its live state. This is what separates a
            # device that is switched off from one whose entities are
            # disabled from one the integration is deaf to: all three
            # read event_count 0 in the record, and cannot be told
            # apart without it.
            "entities": _diagnostic_entities(
                hass, coordinator, device_id
            ),
            # Every entity of the device, for working out what it is
            # (rule DEV-10).
            "all_entities": _all_entities(hass, device_id),
            # The record, less the values held while a verdict stands:
            # they are the device's own states, a lock or a presence
            # among them, and the download carries no states.
            # Only how many it holds (rule WATCH-12).
            "statistics": {k: v for k, v in record.items() if k != DEV_HELD_VALUES},
            "held_value_count": len(record.get(DEV_HELD_VALUES) or {}),
            # Weekly averages and the trend read from them (rule BAT-18).
            "battery_trend": coordinator.battery_trend_summary(record),
            # What powers it and where that came from (rule DEV-06).
            "power": coordinator.power_diagnostics(device_id),
            # What it is and where that came from (rule DEV-10).
            "type": coordinator.type_diagnostics(device_id),
            # Its addresses, each as a short fingerprint so no address
            # leaves the house, and the device it hangs from: what
            # ties one piece of hardware's copies together (rule WATCH-06).
            "addresses": _addresses(device, address_key),
            "via_device": device_field(device, "via_device_id"),
            "copy_of": (getattr(coordinator, "_copy_of", None) or {}).get(device_id),
            # Its integration's iot_class.
            "connects": coordinator.iot_class_of(
                coordinator._watched.get(device_id)
                or (coordinator._set_aside.get(device_id) or (None, None, None))[1]
            ),
            "window_basis": window_basis,
            "set_aside_indices": sorted(set_aside_indices),
            "signal_muted": coordinator._signal_muted(device_id),
            # A rail is a reading stuck at the protocol's fill value
            # (LQI 255, RSSI -128), which is a dead reading rather
            # than a perfect link. It is confirmed only when the
            # device spoke for three consecutive days and said
            # nothing but the fill value: a zero reading count
            # beside a rail count above zero (rule SIG-07).
            "signal_railed": coordinator.signal_railed(record),
            # The discharge soak: the daily battery level series and
            # the deltas derived from it (a positive delta is a drop).
            # A coin cell is flat for most of its life and then falls
            # away, so a level threshold can fire too late; this
            # series is what the falling and time-left judgments read
            # (rule BAT-05).
            "battery_daily_value": list(
                (record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:]
            ),
            "battery_daily_delta": [
                round(a - b, 2)
                for a, b in zip(
                    ((record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:])[:-1],
                    ((record.get("battery_daily_value") or [])[-DIAGNOSTIC_SERIES_CAP:])[1:],
                    strict=False,
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
    payload = {
        "version": coordinator.version,
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "infrastructure": _infrastructure(hass, coordinator),
        "storage": {
            "first_installed": coordinator.first_installed,
            "setup_count": coordinator.setup_count,
            "stats_epoch": coordinator.data.get(DATA_STATS_EPOCH),
            # How the house's battery forecasts came out (rule BAT-15);
            # each device's own rows are in its statistics.
            "battery_forecast_tally": coordinator.data.get(DATA_BATTERY_FORECAST_TALLY),
            "battery_empty_tally": coordinator.data.get(DATA_BATTERY_EMPTY_TALLY),
            # Each battery replaced, for a later survival model (rule BAT-08).
            "battery_lives": coordinator.battery_lives_view() if isinstance(coordinator.data.get(DATA_BATTERY_LIVES), list) else [],
            # The version that last wrote this file, so an upgrade
            # start is verifiable from a download (rule STOR-19).
            "last_version": coordinator.data.get(DATA_LAST_VERSION),
            # The history file (rule STOR-03): which copy the load joined, or
            # why none was, what it holds, and how often it was written
            # this session.
            "history": {
                **coordinator._history_state,
                "pairs_with": coordinator._history_generation,
                "line": coordinator.data.get(DATA_HISTORY_LINE),
                "size": await hass.async_add_executor_job(
                    history_file.file_size, hass
                ),
                "written_this_session": coordinator._history_writes,
            },
        },
        "tunables": {
            "startup_grace_seconds": STARTUP_GRACE_SECONDS,
            "storm_device_threshold": STORM_DEVICE_THRESHOLD,
            "storm_window_seconds": STORM_WINDOW_SECONDS,
            "storm_release_seconds": STORM_RELEASE_SECONDS,
            "storm_exempt_per_hour": STORM_EXEMPT_PER_HOUR,
            "taint_floor_minutes": TAINT_FLOOR_MINUTES,
            "taint_share_pct": TAINT_SHARE_PCT,
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
            # Integrations that own no device and only add entities to
            # devices other integrations own, and how many
            # such entities sit on watched devices in all.
            "no_hardware_integrations": sorted(
                coordinator._no_hardware_integrations
            ),
            "foreign_entities": sum(
                sum(counts.values())
                for counts in coordinator._foreign_by_device.values()
            ),
            # Coordinator stacks detected in this house. Derived from
            # the registry each rebuild rather than stored, so it is
            # never a stale truth, and it is the whole visible surface
            # of stack auto-detection; every later intervention
            # detector attaches only where its stack appears here
            # (rule STACK-01).
            "stacks": sorted(coordinator._stacks),
            # Each hub whose devices are judged by it, and whether its
            # connection reads up (rules STACK-09, STACK-10).
            "hubs": coordinator.hub_diagnostics(),
            # Devices keeping their last good values while a verdict
            # stands, and their entities on watch for a value handed
            # back (rule WATCH-12).
            "held_values": coordinator.held_diagnostics(),
            "storms": len(coordinator.data.get(DATA_STORMS) or []),
            "broker_state": coordinator.broker_state,
            "wifi": coordinator.wifi_diagnostics,
            "wifi_scan": coordinator.wifi_scan_diagnostics,
            "study_hardware": list(
                entry.options.get(CONF_STUDY_HARDWARE) or []
            ),
            "study": coordinator.study_diagnostics,
            # Stacks whose own words could carry a detector, for
            # detectors that cannot be built yet. Each is
            # gathered only behind its own Extended Diagnostics switch
            # (rule STACK-11), and each is empty where the stack is not
            # in the house.
            "lutron": (
                await _studied(lambda: lutron_study(hass))
                if LUTRON_STUDY_DOMAIN in studied_domains(entry.options)
                else {}
            ),
            "zwave": (
                await _studied(lambda: zwave_study(hass))
                if ZWAVE_DOMAIN in studied_domains(entry.options)
                else {}
            ),
            "matter": (
                await _studied(lambda: matter_study(hass))
                if MATTER_DOMAIN in studied_domains(entry.options)
                else {}
            ),
            # Each Hue bridge's event stream and each device's link, and
            # each SmartThings location's event stream and each device's
            # availability, as the minute check reads them (rule STACK-08).
            "hue": await _studied(lambda: coordinator.stack_diagnostics(HUE_DOMAIN)),
            "smartthings": await _studied(
                lambda: coordinator.stack_diagnostics(SMARTTHINGS_DOMAIN)
            ),
            "broker": coordinator.broker_attributes,
            # Each detected bridge's current state (running, binding,
            # down, unknown), so a gap discarded as a pairing is
            # auditable from a diagnostics download and not only from
            # the live sensor (rule STACK-03).
            "bridge_state": {
                stack: coordinator.bridge_state(stack)
                for stack in coordinator.bridge_stacks
            },
            "muted_devices": coordinator._muted_devices,
            "storm_exempt_entries": sorted(
                {
                    row.get("entry_id")
                    for row in (coordinator.data.get(DATA_STORMS) or [])
                    if row.get("entry_id")
                    and coordinator._is_polling_integration(
                        row["entry_id"], dt_util.utcnow().timestamp()
                    )
                }
            ),
        },
        # How many devices each Switched Off card lists, and how many
        # of those a person switched off themselves (rule REC-05), so a
        # card on a house can be supported from a download. Battery
        # Voltage Switched Off is counted from the card's own list, so
        # the count matches what the card shows (rule REC-09).
        "switched_off": {
            kind: {
                "devices": len(found),
                "by_user": sum(1 for who in found.values() if who == "user"),
            }
            for kind in ("last_seen", "node_status", "battery", "signal", "voltage")
            for found in (
                coordinator.switched_off_voltage()
                if kind == "voltage"
                else coordinator.switched_off_devices(kind),
            )
        },
        # The answers owners set on device pages (rule STOR-20): how many the
        # answers file holds, and the ones held for devices Device
        # Sentinel does not watch, in one place, so an excluded
        # device's answers can be seen before it is watched again.
        "answers": coordinator.answers_diagnostics(),
        # One piece of hardware shown as several devices: each group of
        # registry devices found to be one device, and each copy set
        # aside with the device it is watched through (rule WATCH-06).
        "same_hardware": {
            "groups": [sorted(g) for g in (getattr(coordinator, "_hardware_groups", None) or [])],
            "copies": dict(getattr(coordinator, "_copy_of", None) or {}),
        },
        # Watched devices read as groups of the same maker, model and
        # hardware version, with each firmware inside (rule DEV-14). Worked
        # out now from the registry and the records, stored nowhere,
        # and read by nothing that judges: it is here to be observed
        # before anything is built on it.
        "model_groups": coordinator.model_groups(),
        "battery": {
            "low_count": coordinator.battery_low_count,
            "low_list": coordinator.battery_low_list,
        },
        # What the house's muted gaps are actually made of. A
        # taint carries the reason it was set rather than a bare flag,
        # so a rhythm that skipped a gap can be traced to the cause
        # (rule FRZ-14).
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
        # raw timestamps the report renders. An episode is a silence
        # that passed the device's own learned basis, and it records
        # whether it ended because the device spoke or because
        # something made it speak (rule FRZ-08).
        "silence_episodes": coordinator.data.get(DATA_EPISODES, []),
        # The incident timeline every renderer reads. It is the
        # single memory: the push, the brief, the email and the card
        # are all renderings over it, and none derives its own truth
        # (rule NOTE-01).
        "incidents": coordinator.data.get(DATA_INCIDENTS, []),
        # The signal stress table: each silence's signal when it opened
        # and how it ended, the evidence a later signal alert needs,
        # carried in testers' files (rule SIG-11).
        "signal_stress": coordinator.data.get(DATA_SIGNAL_STRESS, []),
        # What the engine would have said, composed but never sent
        # while the dry run lasts. One composer serves every channel,
        # so an event cannot be described differently by two of them
        # (rule NOTE-10).
        # The storage split, so its state travels with an issue
        # report rather than needing a terminal. The split keeps the
        # fast-changing clock fields in a small companion file
        # written on every routine save, and everything learned in the
        # main file written only when it changes (rule STOR-01).
        "split": {
            "clock_fields": list(CLOCK_FIELDS),
            "clock_devices": len(coordinator.data.get(DATA_DEVICES, {})),
            # No phase field: the main file is always written without
            # the clock fields, so a field reporting which shape is in
            # use would have one answer forever.
            #
            # Both stamps, so this file can answer on its own whether
            # the split is healthy: the hot one should be the newer,
            # and the gap is how far the main file is behind.
            "storage_saved_at": coordinator.data.get(DATA_SAVED_AT),
            "clocks_saved_at": (hot or {}).get(DATA_SAVED_AT),
            "main_file_behind_seconds": behind,
        },
        # How the last stop went and what the record looked like on
        # the way back up: whether the last stop was asked for, and
        # how many silence episodes came back with no ending because
        # their closing died with the machine (rules FRZ-20, STOR-18).
        # Together these answer, from a
        # download alone, whether a fleet whose clocks all start at
        # one moment was reset deliberately, and whether any silence
        # episode lost its closing before it reached disk. The orphan
        # figures are observation only: nothing acts on them, and a
        # non-zero count is a finding to read rather than a fault the
        # integration has corrected behind you.
        "restart": {
            "unwatched_seconds": coordinator.downtime or None,
            "last_alive": coordinator.last_alive,
            "orphan_episodes": coordinator.orphan_episodes,
            # How long each bridge, broker and integration took to
            # load after this start (rule UP-04).
            "upstreams_loaded_after": dict(
                coordinator.upstreams_loaded_after
            ),
        },
        # Records of devices removed from Home Assistant, held 30 days
        # in case the device comes back (rule WATCH-07).
        "held_records": coordinator.held_records(),
        "devices": devices,
    }
    return _redact_addresses(payload)
