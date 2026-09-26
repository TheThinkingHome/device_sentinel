# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: model_groups.py, Version: 0.23.9 (2026-09-26)

"""Devices read as groups of the same maker, model and hardware (0.23.4).

Device Sentinel learns each device on its own. Devices of the same
maker, model and hardware behave alike: the same heartbeat, the same
battery steps, the same signal scale. Twenty cells on the reference
rig read "Not enough data" under Steps because they had never moved,
and five of them had siblings on the same firmware that had. The owner
ruled on 25 September that the first release records and changes no
behaviour: the data is observed in the diagnostics download before
anything is built on it.

Two things are recorded. Each device's firmware history is stored,
because Home Assistant keeps only the current version and a change is
otherwise lost. Everything else is worked out when the diagnostics are
downloaded, from the device registry and the records already kept, and
stored nowhere.

What makes a group, as ruled: the maker, the model (Home Assistant's
model id where the device gives one, since it is finer than the
display name; the display name otherwise), and the hardware version.
A device that gives no hardware version joins its model's only given
version, since it cannot be told apart from it; where the model gives
several or none, it stands with the others that give none. Firmware is
shown inside a group rather than splitting it: on the three houses a
model splitting across firmware was rare, and 86 of the second fleet's
243 devices and 63 of the fourth's 112 give no firmware at all.

Who counts: every watched device, muted ones included, because muting
stops judgment and not recording. An excluded device is recorded
nowhere, so it is in no group.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_READABLE_MAX,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_FIRMWARE_HISTORY,
    FIRMWARE_FLICKER_SECONDS,
    FIRMWARE_HOLD_SECONDS,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_SCALE,
    MODEL_GROUP_NOT_GIVEN,
    MODEL_GROUP_WINDOW_DAYS,
)
from .device_fields import device_field

SECONDS_PER_DAY = 86400.0


def _given(value: Any) -> str | None:
    """Return a registry value as trimmed text, or None when empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def identity_of(device: Any) -> dict[str, str | None]:
    """Return the identity fields a group is built from.

    Read through device_field, so a child device, which carries none
    of them, reads empty rather than raising.
    """
    return {
        "maker": _given(device_field(device, "manufacturer")),
        "model": _given(device_field(device, "model")),
        "model_id": _given(device_field(device, "model_id")),
        "hardware": _given(device_field(device, "hw_version")),
        "firmware": _given(device_field(device, "sw_version")),
    }


def note_firmware(record: dict[str, Any], firmware: str | None, now: float) -> bool:
    """Append a firmware version the record has not seen last.

    Returns whether the record changed. An empty version is not a
    version: a device that stops giving one keeps its last. A device
    going back to a version it ran before is a change and is recorded,
    since the history is of what it ran, in order.
    """
    if firmware is None:
        return False
    history = record.get(DEV_FIRMWARE_HISTORY)
    if not isinstance(history, list):
        history = []
        record[DEV_FIRMWARE_HISTORY] = history
    if history and history[-1][0] == firmware:
        return False
    history.append([firmware, now])
    return True


def unflicker_firmware(record: dict[str, Any]) -> bool:
    """Remove flickers from a history written before 0.23.9.

    A version replaced within FIRMWARE_FLICKER_SECONDS by the version
    before it was never run: the registry held a stale value for a
    moment. It is dropped, and the repeat of the version before it is
    merged into that version's first entry, so the history reads as
    the device ran. Returns whether anything changed.
    """
    history = record.get(DEV_FIRMWARE_HISTORY)
    if not isinstance(history, list) or len(history) < 3:
        return False
    cleaned: list[list[Any]] = []
    index = 0
    while index < len(history):
        pair = history[index]
        if (
            cleaned
            and index + 1 < len(history)
            and history[index + 1][0] == cleaned[-1][0]
            and history[index + 1][1] - pair[1] <= FIRMWARE_FLICKER_SECONDS
        ):
            index += 2
            continue
        if cleaned and cleaned[-1][0] == pair[0]:
            index += 1
            continue
        cleaned.append(pair)
        index += 1
    if len(cleaned) == len(history):
        return False
    record[DEV_FIRMWARE_HISTORY] = cleaned
    return True


def prune_firmware(record: dict[str, Any], now: float, keep_days: int) -> bool:
    """Drop versions replaced before the History window opened.

    The current version always stays. An older one goes once the
    version that followed it was first seen before the window: by then
    it describes a device older than anything else the record keeps.
    Returns whether anything was dropped.
    """
    history = record.get(DEV_FIRMWARE_HISTORY)
    if not isinstance(history, list) or len(history) < 2:
        return False
    cutoff = now - keep_days * SECONDS_PER_DAY
    kept = [
        pair
        for index, pair in enumerate(history)
        if index == len(history) - 1 or history[index + 1][1] >= cutoff
    ]
    if len(kept) == len(history):
        return False
    record[DEV_FIRMWARE_HISTORY] = kept
    return True


def _numbers(values: Any) -> list[float]:
    """Return the numeric members of a series, in order."""
    return [
        float(value)
        for value in (values or [])
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def _battery_cell(
    record: dict[str, Any], slope: Callable[[list[float]], float]
) -> dict[str, Any] | None:
    """Return a cell's level, 30-day rate and whether it ever moved."""
    level = record.get(DEV_BATTERY_VALUE)
    if not isinstance(level, (int, float)) or level > BATTERY_READABLE_MAX:
        return None
    series = _numbers(record.get(DEV_BATTERY_DAILY))
    if len(series) < 2:
        return None
    return {
        "level": float(level),
        "rate": round(slope(series[-MODEL_GROUP_WINDOW_DAYS:]), 3),
        "days": len(series),
        "never_moved": len(set(series)) == 1,
    }


def _signal_reading(
    record: dict[str, Any], railed: Callable[[dict[str, Any]], bool]
) -> dict[str, Any] | None:
    """Return a device's typical signal, its railed days, and whether
    its rail is confirmed.

    A day with a rail reading is common and says little on its own:
    on the reference rig 8 of 15 identical door sensors had one in
    the window. The confirmed rail is the integration's own test
    (rulings #78, #322), three days of nothing else.
    """
    scale = record.get(DEV_SIGNAL_SCALE)
    daily = _numbers(record.get(DEV_SIGNAL_DAILY_P50))[-MODEL_GROUP_WINDOW_DAYS:]
    rails = [
        value
        for value in (record.get(DEV_SIGNAL_DAILY_RAIL) or [])[-MODEL_GROUP_WINDOW_DAYS:]
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    rail_days = sum(1 for value in rails if value > 0)
    if not scale or (not daily and not rail_days):
        return None
    return {
        "scale": scale,
        "typical": round(statistics.median(daily), 1) if daily else None,
        "rail_days": rail_days,
        "railed": railed(record),
    }


def _group_key(
    identity: dict[str, str | None], only_hardware: dict[tuple[str, str], str]
) -> tuple[str, str, str | None] | None:
    """Return a device's group, or None when it names no model."""
    maker = identity["maker"]
    model = identity["model_id"] or identity["model"]
    if maker is None or model is None:
        return None
    hardware = identity["hardware"]
    if hardware is None:
        hardware = only_hardware.get((maker, model))
    return (maker, model, hardware)


def build_model_groups(
    records: dict[str, dict[str, Any]],
    identities: dict[str, dict[str, str | None]],
    names: dict[str, str | None],
    muted: set[str],
    slope: Callable[[list[float]], float],
    railed: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Return the Model Groups section for the watched devices given.

    Pure: the registry is read by the caller, so the fleets' own
    diagnostics can stand in for it in a test. Each group of two or
    more devices is listed; a device alone in its group is counted,
    and so is one that names no maker or no model.
    """
    given: dict[tuple[str, str], set[str]] = {}
    for identity in identities.values():
        maker = identity["maker"]
        model = identity["model_id"] or identity["model"]
        if maker is not None and model is not None and identity["hardware"]:
            given.setdefault((maker, model), set()).add(identity["hardware"])
    only_hardware = {
        key: next(iter(versions))
        for key, versions in given.items()
        if len(versions) == 1
    }

    members: dict[tuple[str, str, str | None], list[str]] = {}
    unidentified = 0
    for device_id, identity in identities.items():
        key = _group_key(identity, only_hardware)
        if key is None:
            unidentified += 1
            continue
        members.setdefault(key, []).append(device_id)

    groups = []
    alone = 0
    for key, device_ids in members.items():
        if len(device_ids) < 2:
            alone += 1
            continue
        groups.append(
            _describe_group(
                key, sorted(device_ids), records, identities, names, muted, slope, railed
            )
        )
    groups.sort(key=lambda group: (-group["size"], group["maker"], group["model"]))
    return {
        "key": "maker, model id or model, hardware version",
        "window_days": MODEL_GROUP_WINDOW_DAYS,
        "watched": len(identities),
        "grouped": sum(group["size"] for group in groups),
        "alone": alone,
        "unidentified": unidentified,
        "groups": groups,
    }


def _describe_group(
    key: tuple[str, str, str | None],
    device_ids: list[str],
    records: dict[str, dict[str, Any]],
    identities: dict[str, dict[str, str | None]],
    names: dict[str, str | None],
    muted: set[str],
    slope: Callable[[list[float]], float],
    railed: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Return one group: its members, battery, signal and quirks."""
    maker, model, hardware = key
    firmware: dict[str, int] = {}
    devices = []
    cells: dict[str, dict[str, Any]] = {}
    signals: dict[str, dict[str, Any]] = {}
    for device_id in device_ids:
        identity = identities[device_id]
        record = records.get(device_id) or {}
        version = identity["firmware"] or MODEL_GROUP_NOT_GIVEN
        firmware[version] = firmware.get(version, 0) + 1
        devices.append(
            {
                "device_id": device_id,
                "name": names.get(device_id),
                "firmware": identity["firmware"],
                "hardware_given": identity["hardware"] is not None,
                "muted": device_id in muted,
            }
        )
        cell = _battery_cell(record, slope)
        if cell is not None:
            cells[device_id] = cell
        reading = _signal_reading(record, railed)
        if reading is not None:
            signals[device_id] = reading

    battery = None
    if cells:
        middle = round(statistics.median(cell["rate"] for cell in cells.values()), 3)
        battery = {
            "cells": len(cells),
            "median_rate": middle,
            "devices": [
                {
                    "device_id": device_id,
                    **cell,
                    "from_median": round(cell["rate"] - middle, 3),
                }
                for device_id, cell in cells.items()
            ],
        }

    by_scale: dict[str, dict[str, Any]] = {}
    for scale in sorted({reading["scale"] for reading in signals.values()}):
        on_scale = {
            device_id: reading
            for device_id, reading in signals.items()
            if reading["scale"] == scale
        }
        typicals = [
            reading["typical"]
            for reading in on_scale.values()
            if reading["typical"] is not None
        ]
        middle = round(statistics.median(typicals), 1) if typicals else None
        by_scale[scale] = {
            "median": middle,
            "devices": [
                {
                    "device_id": device_id,
                    "typical": reading["typical"],
                    "from_median": (
                        round(reading["typical"] - middle, 1)
                        if reading["typical"] is not None and middle is not None
                        else None
                    ),
                    "rail_days": reading["rail_days"],
                    "railed": reading["railed"],
                }
                for device_id, reading in on_scale.items()
            ],
        }

    return {
        "maker": maker,
        "model": model,
        "model_name": identities[device_ids[0]]["model"],
        "hardware": hardware or MODEL_GROUP_NOT_GIVEN,
        "size": len(device_ids),
        "firmware": dict(sorted(firmware.items())),
        "devices": devices,
        "battery": battery,
        "signal": by_scale,
        "quirks": {
            "railed": sum(1 for reading in signals.values() if reading["railed"]),
            "some_rail_days": sum(
                1 for reading in signals.values() if reading["rail_days"]
            ),
            "battery_never_moved": sum(
                1 for cell in cells.values() if cell["never_moved"]
            ),
        },
    }


class ModelGroupMixin:
    """Record each watched device's firmware; describe its model group."""

    hass: Any
    data: dict[str, Any]
    _watched: dict[str, Any]
    _muted_devices: dict[str, Any]
    _firmware_candidates: dict[str, tuple[str, float]]

    def _note_firmware(self, device_ids: Any) -> None:
        """Hold each changed firmware version as a candidate (0.23.9).

        Runs with every rebuild of the registry view, each start and
        each registry change. A version different from the one
        recorded is held in memory with the time it first appeared,
        and written only at the midnight fold (_confirm_firmware). A
        device that goes back to its recorded version drops its
        candidate, and a restart forgets every candidate, so the
        stale values a restart shows for a moment never reach the
        history. Nothing new is stored.
        """
        registry = dr.async_get(self.hass)
        devices = self.data.get(DATA_DEVICES) or {}
        now = dt_util.utcnow().timestamp()
        candidates = self._firmware_candidates
        for device_id in device_ids:
            record = devices.get(device_id)
            if not isinstance(record, dict):
                continue
            firmware = identity_of(registry.async_get(device_id))["firmware"]
            if firmware is None:
                continue
            history = record.get(DEV_FIRMWARE_HISTORY) or []
            if history and history[-1][0] == firmware:
                candidates.pop(device_id, None)
                continue
            held = candidates.get(device_id)
            if held is None or held[0] != firmware:
                candidates[device_id] = (firmware, now)

    def _confirm_firmware(self, now: float) -> None:
        """Write the candidates that held, at the midnight fold.

        A candidate is written when the registry still reports it and
        it first appeared at least FIRMWARE_HOLD_SECONDS earlier, with
        the time it first appeared. A newer one waits for the next
        fold; one the device has left is dropped.
        """
        registry = dr.async_get(self.hass)
        devices = self.data.get(DATA_DEVICES) or {}
        changed = False
        for device_id, (firmware, first_seen) in list(self._firmware_candidates.items()):
            record = devices.get(device_id)
            current = identity_of(registry.async_get(device_id))["firmware"]
            if not isinstance(record, dict) or current != firmware:
                self._firmware_candidates.pop(device_id, None)
                continue
            if now - first_seen < FIRMWARE_HOLD_SECONDS:
                continue
            changed = note_firmware(record, firmware, first_seen) or changed
            self._firmware_candidates.pop(device_id, None)
        if changed:
            self._mark_cold_dirty()  # type: ignore[attr-defined]

    def _unflicker_firmware(self) -> None:
        """Clean the flickers recorded before 0.23.9, once per start."""
        changed = False
        for record in (self.data.get(DATA_DEVICES) or {}).values():
            if isinstance(record, dict):
                changed = unflicker_firmware(record) or changed
        if changed:
            self._mark_cold_dirty()  # type: ignore[attr-defined]

    def _prune_firmware(self, record: dict[str, Any], now: float) -> None:
        """Drop firmware replaced before the History window, at the fold."""
        if prune_firmware(record, now, self.retention_days):  # type: ignore[attr-defined]
            self._mark_cold_dirty()  # type: ignore[attr-defined]

    def model_groups(self) -> dict[str, Any]:
        """Return the Model Groups section of the diagnostics download."""
        registry = dr.async_get(self.hass)
        identities = {
            device_id: identity_of(registry.async_get(device_id))
            for device_id in self._watched
        }
        return build_model_groups(
            self.data.get(DATA_DEVICES) or {},
            identities,
            {device_id: self._device_name(device_id) for device_id in identities},  # type: ignore[attr-defined]
            {device_id for device_id in identities if self._muted_devices.get(device_id)},
            self._battery_slope,  # type: ignore[attr-defined]
            self.signal_railed,  # type: ignore[attr-defined]
        )
