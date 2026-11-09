# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: status_readings.py, Version: 0.28.6 (2026-11-08)

"""Readings a device gives about itself, recorded and shown, never judged.

Two of them. A Z-Wave controller's own Status (ready, unresponsive or
jammed, rule STACK-15), and the reason and time of each Tasmota restart
(rule DEV-17). Both explain what a person sees on a device's page; neither
starts, ends or shortens a verdict.

Each is kept on the device's record as a list of [reading, moment] pairs,
oldest first, the newest few kept. A reading that repeats the last one is
not recorded again, so a restart of Home Assistant, which hands every
sensor's value back, adds nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONTROLLER_STATUS_KEPT,
    DEV_CONTROLLER_STATUS,
    DEV_RESTARTS,
    RESTART_FRESH_SECONDS,
    RESTART_SAME_SECONDS,
    RESTARTS_KEPT,
)
from .normalise import MOMENT_HIGHEST, MOMENT_LOWEST

# Home Assistant's Tasmota integration names its status sensors
# `{mac}_{platform}_{endpoint}_{sensor}`; these two end the unique id
# whatever the person named the entity (rule DEV-17).
TASMOTA = "tasmota"
RESTART_REASON_SUFFIX = "_status_restart_reason"
RESTART_TIME_SUFFIX = "_last_restart_time"
CONTROLLER_READING = "controller"
RESTART_REASON = "reason"
RESTART_TIME = "time"
# The sensor not answering is not a reason.
NO_READING = ("", "unknown", "unavailable", "none")


def restart_sensor(ent: Any) -> str | None:
    """Which Tasmota restart sensor this entity is, or None (rule DEV-17)."""
    if getattr(ent, "platform", None) != TASMOTA:
        return None
    if not str(getattr(ent, "entity_id", "")).startswith("sensor."):
        return None
    unique_id = str(getattr(ent, "unique_id", "") or "")
    if unique_id.endswith(RESTART_REASON_SUFFIX):
        return RESTART_REASON
    if unique_id.endswith(RESTART_TIME_SUFFIX):
        return RESTART_TIME
    return None


def _pairs(record: dict[str, Any], field: str) -> list[list[Any]]:
    """The record's pairs, made a list if damage or age left something else."""
    pairs = record.get(field)
    if not isinstance(pairs, list):
        pairs = []
        record[field] = pairs
    return pairs


def record_controller_status(record: dict[str, Any], status: str | None, when: float) -> bool:
    """Record a controller status that differs from the last (rule STACK-15).

    Returns whether anything was recorded. None is no reading and records
    nothing.
    """
    if not status or not MOMENT_LOWEST <= when <= MOMENT_HIGHEST:
        return False
    pairs = _pairs(record, DEV_CONTROLLER_STATUS)
    if pairs and isinstance(pairs[-1], list) and pairs[-1][:1] == [status]:
        return False
    pairs.append([status, float(when)])
    del pairs[:-CONTROLLER_STATUS_KEPT]
    return True


def restart_moment(state: str | None) -> float | None:
    """The restart time a Last Restart Time sensor reads, or None."""
    if not state or state.lower() in NO_READING:
        return None
    parsed: datetime | None = dt_util.parse_datetime(state)
    if parsed is None:
        return None
    moment = dt_util.as_utc(parsed).timestamp()
    # A device whose clock was never set reports a restart in 1970; the
    # record's shape check would read that as damage, so it is no reading.
    return moment if MOMENT_LOWEST <= moment <= MOMENT_HIGHEST else None


def record_restart(
    record: dict[str, Any], reason: str | None, restarted_at: float | None, now: float | None = None
) -> bool:
    """Record a Tasmota restart not already recorded (rule DEV-17).

    Tasmota sends both readings once, each time the device connects.
    A restart within RESTART_SAME_SECONDS of the last one recorded is the
    same restart read again: its time is worked out from the device's
    uptime and can move by a second or two. Returns whether anything was
    recorded.
    """
    if not reason or reason.lower() in NO_READING or restarted_at is None:
        return False
    pairs = _pairs(record, DEV_RESTARTS)
    if pairs and isinstance(pairs[-1], list) and len(pairs[-1]) == 2:
        last_reason, last_at = pairs[-1]
        if isinstance(last_at, (int, float)) and abs(restarted_at - last_at) < RESTART_SAME_SECONDS:
            # The same restart read again. Its time follows the reading,
            # so a time that drifts a second or two at each reading never
            # adds up to a restart that did not happen; a reason that
            # arrived after its time, or was corrected, replaces the last.
            if last_reason == reason and restarted_at == last_at:
                return False
            # A new reason against a restart long past is the reason of a
            # new restart arriving before its time does: the time sensor
            # still holds the last restart's. It waits for the new time,
            # rather than rewriting why the last restart happened.
            moment = dt_util.utcnow().timestamp() if now is None else now
            if last_reason != reason and moment - float(last_at) > RESTART_FRESH_SECONDS:
                return False
            pairs[-1] = [reason, float(restarted_at)]
            return True
    pairs.append([reason, float(restarted_at)])
    del pairs[:-RESTARTS_KEPT]
    return True
