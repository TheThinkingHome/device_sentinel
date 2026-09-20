# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: dashboard.py, Version: 0.22.10 (2026-09-20)

"""What the dashboard reads from the coordinator.

Two things, both small. The change marker is a counter that moves when
something a person would want to see has happened: a problem opened,
closed or changed, a system event was recorded, or midnight folded a
new day. The dashboard's Refresh button changes colour when the marker
has moved past the snapshot on screen. The header status is the same
facts the bridge, broker and Wi-Fi sensors show, read from the same
coordinator properties, so the dashboard and the entities can never
disagree.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from datetime import date, timedelta

from .const import (
    BATTERY_TREND_WINDOWS,
    SIGNAL_TREND_MIN_DAYS,
    DATA_INCIDENTS,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    REPEAT_WINDOW_DAYS,
    TODO_KINDS,
    TODO_UID,
    BATTERY_FALLING_SLOPE,
    BATTERY_TREND_MEANINGS,
    BATTERY_READABLE_MAX,
    BATTERY_SLOPE_DAYS,
    DEV_SIGNAL_DAILY_COUNT,
    STARTUP_GRACE_SECONDS,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_RESTART,
    SYS_UNCLEAN_RESTART,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LEARNED,
    EP_SINCE,
    EP_WINDOW,
    EPISODE_KEEP_DAYS,
    CONF_MUTED_INTEGRATIONS,
    DATA_ROUTERS_SEEN,
    DATA_STORM_DAYS,
    DATA_SYSTEM_EVENTS,
    FLOOD_WINDOW_DAYS,
    STACK_Z2M,
    STACK_ZHA,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WORST,
    TODO_DEVICE_ID,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_SENSOR_NAMES,
    BRIDGE_UNKNOWN,
    BROKER_SCOPE,
    BROKER_SENSOR_NAME,
    WIFI_KEY,
    WIFI_SENSOR_NAME,
)


class DashboardMixin:
    """The change marker and the header status."""

    _change_marker: int
    _change_listeners: list[Callable[[int], None]]

    @property
    def change_marker(self) -> int:
        """The count of changes a person would want to see."""
        return self._change_marker

    @callback
    def _mark_changed(self) -> None:
        """Move the marker and tell every subscriber."""
        self._change_marker += 1
        for listener in list(self._change_listeners):
            listener(self._change_marker)

    @callback
    def async_subscribe_changes(
        self, listener: Callable[[int], None]
    ) -> Callable[[], None]:
        """Call `listener` with the new marker whenever it moves."""
        self._change_listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._change_listeners:
                self._change_listeners.remove(listener)

        return _remove

    def dashboard_status(self) -> dict[str, Any]:
        """Return the header: each part the house has, and maintenance.

        A part appears only where the house has it, the way its sensor
        does: a bridge per stack with a reader, the broker where a
        broker reader runs, Wi-Fi where detection is possible.
        """
        parts: list[dict[str, str]] = []
        for stack in self.bridge_stacks:
            state = self.bridge_state(stack)
            parts.append({
                "key": stack,
                "name": BRIDGE_SENSOR_NAMES.get(stack, f"{stack} Bridge"),
                "state": state if state is not None else BRIDGE_UNKNOWN,
            })
        # The broker watch runs in every house and reads unknown where
        # there is no MQTT (ruling #224), so the header shows it only
        # where an MQTT integration is configured.
        if self._broker_reader is not None and self.hass.config_entries.async_entries(
            BROKER_SCOPE
        ):
            parts.append({
                "key": BROKER_SCOPE,
                "name": BROKER_SENSOR_NAME,
                "state": self.broker_state,
            })
        if self.wifi_capable:
            parts.append({
                "key": WIFI_KEY,
                "name": WIFI_SENSOR_NAME,
                "state": BRIDGE_DOWN if self.wifi_down_at is not None else BRIDGE_RUNNING,
            })
        now = dt_util.utcnow().timestamp()
        until = self._maintenance_until
        is_open = until is not None and now < until
        return {
            "parts": parts,
            "maintenance": {
                "open": is_open,
                "until": dt_util.utc_from_timestamp(until).isoformat() if is_open else None,
                "default_minutes": self.maintenance_minutes,
            },
            "marker": self._change_marker,
        }


# A bridge's outage belongs to the integration that carries it.
_STACK_DOMAIN = {STACK_Z2M: "mqtt", STACK_ZHA: "zha"}
_OPENERS = {
    SYS_BRIDGE_DOWN: SYS_BRIDGE_UP,
    SYS_BROKER_DOWN: SYS_BROKER_UP,
    SYS_INTEGRATION_DOWN: SYS_INTEGRATION_UP,
}
_CLOSERS = {closer: opener for opener, closer in _OPENERS.items()}
OUTAGE_WINDOW_DAYS = 14


class IntegrationViewMixin:
    """The Integrations tab and each integration's page."""

    def _outage_owner(self, kind: str, scope: Any) -> str | None:
        if kind in (SYS_BRIDGE_DOWN, SYS_BRIDGE_UP):
            return _STACK_DOMAIN.get(scope, scope)
        if kind in (SYS_BROKER_DOWN, SYS_BROKER_UP):
            return BROKER_SCOPE
        if kind in (SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP):
            return scope
        return None

    def _outage_label(self, kind: str, scope: Any) -> str:
        if kind in (SYS_BRIDGE_DOWN, SYS_BRIDGE_UP):
            return BRIDGE_SENSOR_NAMES.get(scope, f"{scope} Bridge")
        if kind in (SYS_BROKER_DOWN, SYS_BROKER_UP):
            return BROKER_SENSOR_NAME
        return f"{self._integration_title(str(scope))} integration"

    def integration_outages(self) -> dict[str, list[dict[str, Any]]]:
        """Every outage of the last fourteen days, by owning integration.

        Each down is paired with its own return by kind and scope. The
        return carries the length and, since ruling #442, how many
        devices the outage took; an outage with no return yet is open.
        Newest first.
        """
        now = dt_util.utcnow().timestamp()
        since = now - OUTAGE_WINDOW_DAYS * 86400.0
        rows = sorted(
            (row for row in self.data.get(DATA_SYSTEM_EVENTS) or [] if isinstance(row, dict)),
            key=lambda row: row.get(SYS_WHEN) or 0,
        )
        open_rows: dict[tuple[str, Any], dict[str, Any]] = {}
        found: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            kind, scope, when = row.get(SYS_KIND), row.get(SYS_SCOPE), row.get(SYS_WHEN)
            if not isinstance(when, (int, float)):
                continue
            if kind in _OPENERS:
                open_rows[(kind, scope)] = row
            elif kind in _CLOSERS:
                opened = open_rows.pop((_CLOSERS[kind], scope), None)
                duration = row.get(SYS_DURATION)
                went_down = (
                    opened[SYS_WHEN] if opened is not None
                    else when - duration if isinstance(duration, (int, float))
                    else when
                )
                owner = self._outage_owner(kind, scope)
                if owner is None or went_down < since:
                    continue
                found.append((owner, {
                    "went_down": dt_util.utc_from_timestamp(went_down).isoformat(),
                    "what": self._outage_label(kind, scope),
                    "duration": duration if isinstance(duration, (int, float)) else None,
                    "devices": row.get(SYS_DEVICES),
                    "worst": row.get(SYS_WORST),
                    "open": False,
                }))
        for (kind, scope), row in open_rows.items():
            owner = self._outage_owner(kind, scope)
            if owner is None or row[SYS_WHEN] < since:
                continue
            found.append((owner, {
                "went_down": dt_util.utc_from_timestamp(row[SYS_WHEN]).isoformat(),
                "what": self._outage_label(kind, scope),
                "duration": None, "devices": None, "worst": None, "open": True,
            }))
        by_owner: dict[str, list[dict[str, Any]]] = {}
        for owner, outage in sorted(found, key=lambda pair: pair[1]["went_down"], reverse=True):
            by_owner.setdefault(owner, []).append(outage)
        return by_owner

    def _integration_standing(self, domain: str, watched: int) -> str:
        if domain in self.excluded_integrations:
            return "excluded"
        if domain in set(self.entry.options.get(CONF_MUTED_INTEGRATIONS, [])):
            return "muted"
        return "watched" if watched else "service"

    def _problems_by_device(self) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for item in self.todo_items:
            name = item.get(TODO_SORT_NAME) or ""
            summary = item[TODO_SUMMARY]
            found[item[TODO_DEVICE_ID]] = {
                "problem": summary[len(name) + 2:] if summary.startswith(f"{name}: ") else summary,
                "acknowledged": item.get(TODO_STATUS) == "completed",
            }
        return found

    def _bursts(self, domain: str) -> int:
        earliest = (dt_util.now().date() - timedelta(days=FLOOD_WINDOW_DAYS)).isoformat()
        total = 0
        for row in self.data.get(DATA_STORM_DAYS) or []:
            if (
                isinstance(row, dict)
                and row.get(STORM_DAY_DOMAIN) == domain
                and str(row.get(STORM_DAY_DATE) or "") >= earliest
            ):
                total += int(row.get(STORM_DAY_COUNT) or 0)
        return total

    def dashboard_integrations(self) -> list[dict[str, Any]]:
        """One row per integration that owns a device, by name."""
        rows = self.classification_rows()
        problems = self._problems_by_device()
        outages = self.integration_outages()
        seen_routers = set(self.data.get(DATA_ROUTERS_SEEN) or [])
        domains: dict[str, dict[str, int]] = {}
        for row in rows:
            count = domains.setdefault(row["integration"], {
                "watched": 0, "muted": 0, "set_aside": 0, "problems": 0, "acknowledged": 0,
            })
            if row["watched"]:
                count["watched"] += 1
            else:
                count["set_aside"] += 1
            if row["muted"]:
                count["muted"] += 1
            problem = problems.get(row["device_id"])
            if problem is not None:
                count["acknowledged" if problem["acknowledged"] else "problems"] += 1
        result = []
        for domain, count in domains.items():
            standing = self._integration_standing(domain, count["watched"])
            result.append({
                "domain": domain,
                "name": self._integration_title(domain),
                "standing": standing,
                "first_seen": standing == "excluded" and domain in seen_routers,
                **count,
                "outages": len(outages.get(domain, [])),
            })
        result.sort(key=lambda row: row["name"].lower())
        return result

    def dashboard_integration(self, domain: str) -> dict[str, Any] | None:
        """One integration's page, or None if no device belongs to it."""
        devices = [row for row in self.classification_rows() if row["integration"] == domain]
        if not devices:
            return None
        problems = self._problems_by_device()
        listed = []
        for row in devices:
            problem = problems.get(row["device_id"])
            listed.append({
                "device_id": row["device_id"],
                "name": row["name"],
                "watched": row["watched"],
                "muted": row["muted"],
                "set_aside": row["set_aside"],
                "problem": problem["problem"] if problem else "",
                "acknowledged": bool(problem and problem["acknowledged"]),
            })
        listed.sort(key=lambda row: (
            0 if row["problem"] and not row["acknowledged"] else 1 if row["problem"] else 2,
            row["name"].lower(),
        ))
        title = self._integration_title(domain)
        watched = sum(1 for row in devices if row["watched"])
        return {
            "domain": domain,
            "name": title,
            "standing": self._integration_standing(domain, watched),
            "first_seen": domain in (self.data.get(DATA_ROUTERS_SEEN) or [])
            and domain in self.excluded_integrations,
            "devices": listed,
            "outages": self.integration_outages().get(domain, []),
            "bursts": self._bursts(domain),
            "recommendations": [
                line for line in self._recommendation_items()
                if f"the {domain} integration" in line or title in line
            ],
        }


def _middle(values: list[float]) -> float:
    """The median, the true one: an even count averages the two middles."""
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        return 0.0
    if count % 2:
        return ordered[count // 2]
    return (ordered[count // 2 - 1] + ordered[count // 2]) / 2.0


def _iso(stamp: Any) -> str | None:
    """A stored timestamp as ISO text, or None."""
    return dt_util.utc_from_timestamp(stamp).isoformat() if isinstance(stamp, (int, float)) else None


class DeviceViewMixin:
    """The Devices tab and each device's page."""

    def _device_rhythm(self, record: dict[str, Any]) -> tuple[float | None, list[int]]:
        gaps = (record.get(DEV_DAILY_MAX) or [])[-DAILY_MAX_KEEP:]
        rhythm, set_aside = self._trimmed_maximum(gaps)
        return rhythm, sorted(set_aside)

    def _page_status(self, record: dict[str, Any]) -> str:
        """The stored verdict the Problem List reads, or reporting."""
        return record.get(DEV_FROZEN_CATEGORY) or "reporting"

    def dashboard_devices(self) -> list[dict[str, Any]]:
        """One row per watched device, by name."""
        records = self.data.get(DATA_DEVICES) or {}
        problems = self._problems_by_device()
        rows = []
        for device_id, domain in self._watched.items():
            record = records.get(device_id) or {}
            rhythm, _ = self._device_rhythm(record) if record.get(DEV_DAILY_MAX) else (None, [])
            problem = problems.get(device_id)
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "integration": domain,
                "integration_name": self._integration_title(domain),
                "muted": self._muted_devices.get(device_id) or "",
                "status": self._page_status(record),
                "problem": problem["problem"] if problem else "",
                "acknowledged": bool(problem and problem["acknowledged"]),
                "last_activity": _iso(record.get(DEV_LAST_ACTIVITY)),
                "rhythm": rhythm,
                "window": self._freeze_window(record) if record.get(DEV_DAILY_MAX) else None,
            })
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    def dashboard_device(self, device_id: str) -> dict[str, Any] | None:
        """Everything known about one device, or None if it has no record.

        Read live from the registry where the registry is the truth
        (name, manufacturer, model, model id, hardware version, area,
        connections), because nothing of it is stored. The model id and
        hardware version are the fields a battery library matches on
        beside manufacturer and model; the battery type itself arrives
        with that lookup.
        """
        records = self.data.get(DATA_DEVICES) or {}
        record = records.get(device_id)
        if record is None:
            return None
        device = dr.async_get(self.hass).async_get(device_id)
        area_name = None
        if device is not None and device.area_id:
            area = ar.async_get(self.hass).async_get_area(device.area_id)
            area_name = area.name if area else None
        domain = self._watched.get(device_id) or (
            self._set_aside.get(device_id) or (None, None, None)
        )[1]
        readings = []
        for entity in er.async_get(self.hass).entities.values():
            if entity.device_id != device_id or entity.disabled_by is not None:
                continue
            for kind, test in (
                ("battery", self._is_battery_percentage),
                ("signal", self._is_signal),
                ("last_seen", self._is_last_seen),
            ):
                if test(entity):
                    readings.append({"kind": kind, "entity_id": entity.entity_id})
        rhythm, set_aside = self._device_rhythm(record)
        now = dt_util.utcnow().timestamp()
        since = now - EPISODE_KEEP_DAYS * 86400.0
        silences = [
            {
                "since": _iso(row.get(EP_SINCE)),
                "silence": (
                    row[EP_AT] - row[EP_SINCE]
                    if isinstance(row.get(EP_AT), (int, float))
                    and isinstance(row.get(EP_SINCE), (int, float))
                    else None
                ),
                "basis": row.get(EP_BASIS),
                "window": row.get(EP_WINDOW),
                "ended": row.get(EP_ENDED),
                "at": _iso(row.get(EP_AT)),
                "learned": row.get(EP_LEARNED),
            }
            for row in self.data.get(DATA_EPISODES) or []
            if isinstance(row, dict)
            and row.get(EP_DEVICE_ID) == device_id
            and isinstance(row.get(EP_SINCE), (int, float))
            and row[EP_SINCE] >= since
        ]
        silences.sort(key=lambda row: row["since"] or "", reverse=True)
        return {
            "identity": {
                "name": self._device_name(device_id),
                "device_id": device_id,
                # Read with getattr: the registry can also return a child
                # device entry (2026.9), which carries none of these.
                "manufacturer": getattr(device, "manufacturer", None),
                "model": getattr(device, "model", None),
                "model_id": getattr(device, "model_id", None),
                "hw_version": getattr(device, "hw_version", None),
                "area": area_name,
                "integration": domain,
                "integration_name": self._integration_title(domain) if domain else None,
                "connections": sorted(
                    [kind, value] for kind, value in getattr(device, "connections", None) or ()
                ),
                "first_observed": record.get(DEV_FIRST_OBSERVED),
                "event_count": record.get(DEV_EVENT_COUNT),
                "clock": "last_seen" if device_id in self._last_seen_entity else "recorded",
                "watched": device_id in self._watched,
                "set_aside": (self._set_aside.get(device_id) or (None, None, ""))[2],
                "muted": self._muted_devices.get(device_id) or "",
                # Filled by the battery library lookup, when it arrives.
                "battery_type": None,
            },
            "readings": readings,
            "status": {
                "category": self._page_status(record),
                "last_activity": _iso(record.get(DEV_LAST_ACTIVITY)),
                "rhythm": rhythm,
                "window": self._freeze_window(record),
            },
            "rhythm": {
                "gaps": list((record.get(DEV_DAILY_MAX) or [])[-DAILY_MAX_KEEP:]),
                "set_aside": set_aside,
                # The whole history, and the window each day had,
                # worked out from the days before it as the detector
                # worked it out then.
                "daily": list(record.get(DEV_DAILY_MAX) or []),
                "windows": [
                    self._freeze_window({DEV_DAILY_MAX: (record.get(DEV_DAILY_MAX) or [])[:index]})
                    if index else None
                    for index in range(len(record.get(DEV_DAILY_MAX) or []))
                ],
            },
            "silences": silences,
            "battery": self._page_battery(record),
            "signal": self._page_signal(record),
            "outages": self.device_outages(domain),
            # Every daily series ends on the last day the midnight roll
            # folded, which is yesterday.
            "series_end": (dt_util.now().date() - timedelta(days=1)).isoformat(),
            "history_days": self.retention_days,
        }

    def _page_battery(self, record: dict[str, Any]) -> dict[str, Any]:
        """The battery history and the report's own figures for it.

        The windows, the blocks, the reading and the time left are the
        battery report's, from the report's own functions, so the page
        and the report say the same thing about the same cell.
        """
        level = record.get(DEV_BATTERY_VALUE)
        series = [
            value for value in (record.get(DEV_BATTERY_DAILY) or [])
            if isinstance(value, (int, float))
        ]
        readable = isinstance(level, (int, float)) and float(level) <= BATTERY_READABLE_MAX
        page: dict[str, Any] = {
            "daily": list(record.get(DEV_BATTERY_DAILY) or []),
            "now": level,
            "threshold": self.low_threshold,
            "readable": readable,
        }
        if not isinstance(level, (int, float)) or not readable or not series:
            return page
        current = float(level)
        windows = self._battery_windows(series)
        slope = self._battery_slope(series[-BATTERY_SLOPE_DAYS:])
        falling = slope < BATTERY_FALLING_SLOPE and current > 0
        page.update({
            "windows": {str(days): value for days, value in windows.items()},
            "blocks": [[start, end, value] for start, end, value in self._battery_blocks(series)],
            "reading": self._battery_reading(windows, len(series)),
            "reading_meaning": BATTERY_TREND_MEANINGS.get(self._battery_reading(windows, len(series))),
            "falling": falling,
            "left": self.battery_time_left(current / -slope) if falling else None,
            "left_soon": falling and current / -slope <= self._battery_days(),
        })
        return page

    def _page_signal(self, record: dict[str, Any]) -> dict[str, Any]:
        """The signal history and each day's judgment, as the report
        makes it."""
        p5 = list(record.get(DEV_SIGNAL_DAILY_P5) or [])
        counts = [
            value for value in (record.get(DEV_SIGNAL_DAILY_COUNT) or [])[-DAILY_MAX_KEEP:]
            if isinstance(value, (int, float))
        ]
        middle = sorted(counts)[len(counts) // 2] if counts else None
        if counts and len(counts) % 2 == 0:
            ordered = sorted(counts)
            middle = (ordered[len(counts) // 2 - 1] + ordered[len(counts) // 2]) / 2
        return {
            "p5": p5,
            "p50": list(record.get(DEV_SIGNAL_DAILY_P50) or []),
            "railed_days": list(record.get(DEV_SIGNAL_DAILY_RAIL) or []),
            "scale": record.get(DEV_SIGNAL_SCALE),
            "now": record.get(DEV_SIGNAL_VALUE),
            "judged": [self.signal_day_judgment(record, index) for index in range(len(p5))],
            "readings_a_day": round(middle) if middle is not None else None,
        }

    def device_outages(self, domain: str | None) -> list[dict[str, Any]]:
        """Natural outages on this device's own path, oldest first.

        Its path is its integration, its stack's bridge and, for MQTT,
        the broker. An outage that began while Home Assistant was going
        down for a restart, was down, or was inside the startup grace
        after it was caused by the restart and is left out. One inside
        a maintenance window is kept and marked, so a deliberate test
        stays visible without reading as a surprise.
        """
        if not domain:
            return []
        stack = next((name for name, owner in _STACK_DOMAIN.items() if owner == domain), None)
        rows = sorted(
            (row for row in self.data.get(DATA_SYSTEM_EVENTS) or [] if isinstance(row, dict)),
            key=lambda row: row.get(SYS_WHEN) or 0,
        )
        restarts = [
            (row[SYS_WHEN], float(row.get(SYS_DURATION) or 0.0))
            for row in rows
            if row.get(SYS_KIND) in (SYS_RESTART, SYS_UNCLEAN_RESTART)
            and isinstance(row.get(SYS_WHEN), (int, float))
        ]
        windows: list[tuple[float, float]] = []
        opened: float | None = None
        for row in rows:
            if row.get(SYS_KIND) == SYS_MAINTENANCE_OPEN:
                opened = row.get(SYS_WHEN)
            elif row.get(SYS_KIND) == SYS_MAINTENANCE_CLOSED and opened is not None:
                windows.append((opened, row[SYS_WHEN]))
                opened = None
        if opened is not None:
            windows.append((opened, float("inf")))

        def on_path(kind: str, scope: Any) -> bool:
            if kind in (SYS_BRIDGE_DOWN, SYS_BRIDGE_UP):
                return stack is not None and scope == stack
            if kind in (SYS_BROKER_DOWN, SYS_BROKER_UP):
                return domain == BROKER_SCOPE
            if kind in (SYS_INTEGRATION_DOWN, SYS_INTEGRATION_UP):
                return scope == domain
            return False

        def caused_by_restart(start: float) -> bool:
            # From going down (its downtime, plus a margin for the
            # shutdown itself) to the end of the grace after it.
            return any(
                at - downtime - 120.0 <= start <= at + STARTUP_GRACE_SECONDS
                for at, downtime in restarts
            )

        found: list[dict[str, Any]] = []
        open_rows: dict[tuple[str, Any], float] = {}
        for row in rows:
            kind, scope, when = row.get(SYS_KIND), row.get(SYS_SCOPE), row.get(SYS_WHEN)
            if not isinstance(kind, str) or not isinstance(when, (int, float)):
                continue
            if not on_path(kind, scope):
                continue
            if kind in _OPENERS:
                open_rows[(kind, scope)] = when
                continue
            started = open_rows.pop((_CLOSERS[kind], scope), None)
            duration = row.get(SYS_DURATION)
            if isinstance(duration, (int, float)) and duration > 0:
                # The return knows how long it was down, which is truer
                # than a down row that may belong to another episode.
                started = when - duration
            if started is None or caused_by_restart(started):
                continue
            found.append({
                "start": dt_util.utc_from_timestamp(started).isoformat(),
                "minutes": max(1, round((when - started) / 60)),
                "what": self._outage_label(kind, scope),
                "devices": row.get(SYS_DEVICES),
                "worst": row.get(SYS_WORST),
                "maintenance": any(a <= started <= b for a, b in windows),
            })
        found.sort(key=lambda item: item["start"])
        return found


class BriefViewMixin:
    """The Daily Brief tab, by calendar day.

    A day that has finished runs midnight to midnight; today runs
    midnight to now. The written brief keeps its own window, brief
    time to brief time, because a file named for a day must not be
    rewritten at midnight; a page a person steps through is easier to
    read by the calendar. Everything shown comes from the records the
    written brief reads, rendered with its own phrasing.
    """

    def _brief_day_bounds(self, day: date) -> tuple[float, float, bool]:
        start = dt_util.as_utc(dt_util.start_of_local_day(day)).timestamp()
        now = dt_util.utcnow().timestamp()
        today = day == dt_util.now().date()
        end = now if today else start + 86400.0
        return start, end, today

    def _brief_earliest_day(self) -> date:
        """The oldest day the incidents still cover."""
        return dt_util.now().date() - timedelta(days=INCIDENT_KEEP_DAYS - 1)

    def _standing_at(self, moment: float) -> list[dict[str, Any]]:
        """The problems that were open at that moment, from the incidents.

        A problem is standing if it opened before the moment and
        nothing closed it after. Rebuilt rather than stored, so a past
        day reads with today's wording and nothing new is kept.
        """
        opened: dict[tuple[Any, Any], dict[str, Any]] = {}
        for row in sorted(
            (r for r in self.data.get(DATA_INCIDENTS) or [] if isinstance(r, dict)),
            key=lambda r: r.get(INC_WHEN) or 0,
        ):
            when = row.get(INC_WHEN)
            if not isinstance(when, (int, float)) or when > moment:
                continue
            key = (row.get(INC_DEVICE_ID), row.get(INC_KIND))
            if row.get(INC_EVENT) == INCIDENT_OPENED:
                opened[key] = row
            elif row.get(INC_EVENT) == INCIDENT_RESOLVED:
                opened.pop(key, None)
        rows = []
        for (device_id, kind), row in opened.items():
            if device_id in self._muted_devices:
                continue
            rows.append({
                "device_id": device_id,
                "name": row.get(INC_NAME) or self._device_name(device_id),
                # The words the brief used when it opened: a past day
                # has no record of the level it read that night.
                "problem": self._brief_phrase(row),
                "since": _iso(row.get(INC_WHEN)),
                "seconds": moment - row[INC_WHEN],
                "acknowledged": False,
                "uid": None,
            })
        rows.sort(key=lambda r: r["seconds"], reverse=True)
        return rows

    def _standing_now(self) -> list[dict[str, Any]]:
        """Today's standing problems, from the list itself, acknowledged
        ones included: the tab can tick them, which the written brief
        cannot (ruling #123 keeps them out of the file)."""
        now = dt_util.utcnow().timestamp()
        rows = []
        for item in self.todo_items:
            device_id = item.get(TODO_DEVICE_ID)
            if not device_id or device_id in self._muted_devices:
                continue
            name = item.get(TODO_SORT_NAME) or ""
            summary = item[TODO_SUMMARY]
            kinds = item[TODO_KINDS]
            since = min((v for v in kinds.values() if isinstance(v, (int, float))), default=None)
            rows.append({
                "device_id": device_id,
                "name": name,
                "problem": summary[len(name) + 2:] if summary.startswith(f"{name}: ") else summary,
                "since": _iso(since),
                "seconds": now - since if since is not None else None,
                "acknowledged": item.get(TODO_STATUS) == "completed",
                "uid": item.get(TODO_UID),
            })
        rows.sort(key=lambda r: (r["acknowledged"], -(r["seconds"] or 0)))
        return rows

    def dashboard_brief(self, day: date) -> dict[str, Any] | None:
        """One day of the brief, or None for a day no longer kept."""
        today = dt_util.now().date()
        earliest = self._brief_earliest_day()
        if day > today or day < earliest:
            return None
        start, end, is_today = self._brief_day_bounds(day)
        silenced = self._acknowledged_devices()
        incidents = [
            row
            for row in self.incident_rows()
            if start <= row[INC_WHEN] <= end
            and row[INC_DEVICE_ID] not in self._muted_devices
            and row[INC_DEVICE_ID] not in silenced
        ]
        system = [
            row
            for row in self.data.get(DATA_SYSTEM_EVENTS) or []
            if isinstance(row, dict)
            and isinstance(row.get(SYS_WHEN), (int, float))
            and start <= row[SYS_WHEN] <= end
        ]
        events = [
            {
                "when": _iso(row[INC_WHEN]),
                "who": self._told_name(row),
                "device_id": row.get(INC_DEVICE_ID),
                "what": self._brief_phrase(row),
            }
            for row in incidents
        ] + [
            {
                "when": _iso(row[SYS_WHEN]),
                "who": "The system",
                "device_id": None,
                "what": self._system_event_phrase(row),
            }
            for row in system
        ]
        events.sort(key=lambda row: row["when"] or "", reverse=True)
        # Repeat offenders look back seven days from the day shown, so
        # they can be told only while those days are still on record.
        held_from = dt_util.utcnow().timestamp() - INCIDENT_KEEP_DAYS * 86400.0
        covered = end - REPEAT_WINDOW_DAYS * 86400.0 >= held_from
        repeat: dict[str, Any] = {"available": covered, "lines": [], "words": ""}
        if covered:
            # The brief's own section, lines and all, so the tab and
            # the file say the same thing about the same devices.
            lines = [
                line for line in self._repeat_offenders_section(end)
                if line and not line.startswith("## ")
            ]
            repeat["lines"] = lines
            if not lines:
                repeat["words"] = (
                    "No device failed more than once in the seven days "
                    "before this one for no obvious reason."
                )
        else:
            repeat["words"] = (
                "Repeat offenders are counted over the seven days before the "
                "day shown, and those days are no longer on record."
            )
        return {
            "day": day.isoformat(),
            "is_today": is_today,
            "window": {"start": _iso(start), "end": _iso(end)},
            "earliest": earliest.isoformat(),
            "back": (day - timedelta(days=1)).isoformat() if day - timedelta(days=1) >= earliest else None,
            "forward": (day + timedelta(days=1)).isoformat() if day < today else None,
            "now": self._standing_now() if is_today else self._standing_at(end),
            "events": events,
            "counts": {
                "events": len(events),
                "opened": sum(1 for row in incidents if row[INC_EVENT] == INCIDENT_OPENED),
                "resolved": sum(1 for row in incidents if row[INC_EVENT] == INCIDENT_RESOLVED),
            },
            "repeat": repeat,
        }


class TrendsViewMixin:
    """The Battery Trends and Signal Trends tabs.

    Fleet views: which of a house's models eat cells, and which days
    several devices had a bad signal at once. Neither question can be
    answered from one device's page. Worked out when asked, from the
    reports' own functions and the daily series already kept.
    """

    def _battery_cells(self) -> list[tuple[str, dict[str, Any], list[float]]]:
        """Watched cells with a readable level and enough days to judge."""
        cells = []
        for device_id, record in self.watched_records():
            if device_id in self._muted_devices or self._battery_muted(device_id):
                continue
            level = record.get(DEV_BATTERY_VALUE)
            if not isinstance(level, (int, float)) or float(level) > BATTERY_READABLE_MAX:
                continue
            series = [
                value for value in (record.get(DEV_BATTERY_DAILY) or [])
                if isinstance(value, (int, float))
            ]
            if len(series) < BATTERY_TREND_WINDOWS[-1]:
                continue
            cells.append((device_id, record, series))
        return cells

    def battery_trends(self) -> dict[str, Any]:
        """The battery fleet: the bank, every model, and the report's groups."""
        registry = dr.async_get(self.hass)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        bank = [0] * 10
        for device_id, record, series in self._battery_cells():
            level = float(record[DEV_BATTERY_VALUE])
            bank[min(9, int(level // 10))] += 1
            device = registry.async_get(device_id)
            key = (
                getattr(device, "manufacturer", None) or "not reported",
                getattr(device, "model", None) or "not reported",
            )
            groups.setdefault(key, []).append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "level": level,
                # The same rate the battery report's 30-day column shows.
                "rate": self._battery_slope(series[-BATTERY_TREND_WINDOWS[0]:]),
            })
        models = []
        for (maker, model), cells in groups.items():
            lowest = min(cells, key=lambda cell: cell["level"])
            models.append({
                "maker": maker,
                "model": model,
                "cells": len(cells),
                "rate": _middle([cell["rate"] for cell in cells]),
                "typical": _middle([cell["level"] for cell in cells]),
                "lowest": lowest["level"],
                "lowest_name": lowest["name"],
                "lowest_id": lowest["device_id"],
            })
        models.sort(key=lambda row: (row["rate"], -row["cells"]))
        report = self._battery_rows()

        def listed(rows: list[dict[str, Any]], falling: bool = False) -> list[dict[str, Any]]:
            out = []
            for row in rows:
                item = {
                    "device_id": row.get("device_id"),
                    "name": row.get("name"),
                    "level": row.get("level"),
                    "since": row.get("since"),
                }
                if falling:
                    windows = row.get("windows") or {}
                    item.update({
                        "windows": {str(days): value for days, value in windows.items()},
                        "blocks": [[start, stop, value] for start, stop, value in (row.get("blocks") or [])],
                        "reading": row.get("reading"),
                        "left": self.battery_time_left(row["days"]),
                        "left_soon": row["days"] <= self._battery_days(),
                    })
                else:
                    item["days"] = len(row.get("series") or [])
                    series = row.get("series") or []
                    item["rate"] = (
                        self._battery_slope(series[-BATTERY_TREND_WINDOWS[0]:]) if series else None
                    )
                out.append(item)
            return out

        return {
            "cells": sum(model["cells"] for model in models),
            "bank": bank,
            "models": models,
            "falling": listed(report["falling"], falling=True),
            "low": listed(report["low"]),
            "steady": listed(report["flat"]),
            "unreadable": [
                {"device_id": row.get("device_id"), "name": row.get("name"), "level": row.get("level")}
                for row in report["unreadable"]
            ],
            "no_battery": len(report["absent"]),
            "threshold": self.low_threshold,
        }

    def signal_trends(self) -> dict[str, Any]:
        """The signal fleet: where each link sits against its own normal,
        and the days several devices had a bad one together."""
        devices = []
        scales: dict[str, int] = {}
        bad_by_day: dict[str, int] = {}
        today = dt_util.now().date()
        for device_id, record in self.watched_records():
            if device_id in self._muted_devices or self._signal_muted(device_id):
                continue
            daily = [
                value for value in (record.get(DEV_SIGNAL_DAILY_P50) or [])
                if isinstance(value, (int, float))
            ]
            if len(daily) < SIGNAL_TREND_MIN_DAYS:
                continue
            older = daily[:-7] or daily[-7:]
            now = _middle(daily[-7:])
            normal = _middle(older)
            # Its own spread, with a floor of one point: a link whose
            # readings never varied has none, and nothing can be
            # divided by nothing.
            middle = max(_middle([abs(value - normal) for value in older]), 1.0)
            judged = [
                self.signal_day_judgment(record, index)
                for index in range(len(record.get(DEV_SIGNAL_DAILY_P5) or []))
            ]
            bad = 0
            for index, day in enumerate(judged):
                if not day or not day["bad"]:
                    continue
                back = len(judged) - 1 - index
                when = (today - timedelta(days=back + 1)).isoformat()
                bad_by_day[when] = bad_by_day.get(when, 0) + 1
                if back < DAILY_MAX_KEEP:
                    bad += 1
            counts = [
                value for value in (record.get(DEV_SIGNAL_DAILY_COUNT) or [])[-DAILY_MAX_KEEP:]
                if isinstance(value, (int, float))
            ]

            scale = record.get(DEV_SIGNAL_SCALE) or "unknown"
            scales[scale] = scales.get(scale, 0) + 1
            last = next((day for day in reversed(judged) if day), None)
            devices.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "scale": scale,
                "now": record.get(DEV_SIGNAL_VALUE),
                "normal": normal,
                "line": last["line"] if last else None,
                "change": now - normal,
                # In the device's own spreads, so a steady link and a
                # jumpy one are judged by their own standards.
                "spreads": (now - normal) / middle,
                "bad_days": bad,
                "readings_a_day": _middle(counts) if counts else None,
                "days": len(daily),
            })
        devices.sort(key=lambda row: (row["spreads"] if row["spreads"] is not None else 0))
        unsteady = sum(1 for row in devices if row["bad_days"])
        return {
            "devices": devices,
            "scales": scales,
            "bad_days": sorted(
                ({"day": day, "devices": count} for day, count in bad_by_day.items() if count > 1),
                key=lambda row: row["day"],
                reverse=True,
            ),
            "counts": {"unsteady": unsteady, "steady": len(devices) - unsteady},
        }
