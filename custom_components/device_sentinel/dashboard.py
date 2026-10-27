# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: dashboard.py, Version: 0.27.10 (2026-10-27)

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

import re
from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from datetime import date, timedelta

from .daily_dates import FAMILY_GAP, FAMILY_SIGNAL, dates_for, on_calendar
from .device_addresses import addresses, shown
from .battery_projection import battery_projection
from .report_battery import (
    battery_calendar,
    battery_heard_days,
    battery_month_drop,
    battery_sentence,
    battery_trend,
)
from . import stacks
from .const import (
    BATTERY_STEPS_COARSE,
    BATTERY_MODEL_PACE_MIN_OTHERS,
    BATTERY_FIT_MIN_DAYS,
    CLIP_START_DAYS,
    CONF_DASHBOARD_MODE,
    DASHBOARD_MODES,
    DEFAULT_DASHBOARD_MODE,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_NOTICES_ONLY,
    STANDING_NOTICES_ONLY,
    SET_ASIDE_EXCLUDED,
    RULE_LOGNORMAL,
    STACK_DISPLAY_NAMES,
    DEV_LOGNORMAL_DAYS,
    CONNECTS_WORDS,
    BATTERY_STEPS_SMOOTH,
    BATTERY_WEEK_DAYS,
    TODO_KIND_FLAPPING,
    BATTERY_STEPS_WORDS,
    BROKER_RIDER_DOMAINS,
    SYS_DETAIL,
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
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_UID,
    BATTERY_READABLE_MAX,
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
    DEV_BATTERY_RAW_SCALE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRMWARE_HISTORY,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    FREEZE_CATEGORY_FROZEN,
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
    EP_LAG,
    EP_LEARNED,
    EPISODE_ENDED_RESUMED,
    EP_SINCE,
    EP_WINDOW,
    EPISODE_KEEP_DAYS,
    CONF_MUTED_INTEGRATIONS,
    STANDING_HELPER,
    STATUS_NEVER_REPORTED,
    STATUS_REPORTING,
    STATUS_SET_ASIDE,
    STANDING_NO_HARDWARE,
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
    WIFI_BAND_NAME,
    READING_ACCELERATING,
    RELEASE_NOTES_URL,
)
from .escalation import fold, withdrawals_once
from .outage_detail import pair_key
from .report_brief import REPEAT_PARAGRAPH
from .device_fields import device_field


class DashboardMixin:
    """The change marker and the header status."""

    def same_hardware(self, device_id: str) -> dict[str, Any] | None:
        """The device's copies, if it is one piece of hardware shown as
        several devices: which copy is watched, and the rest, each with
        its integration. None for a device with no copies (rule WATCH-06)."""
        groups = getattr(self, "_hardware_groups", None) or []
        members = next((g for g in groups if device_id in g), None)
        if not members:
            return None
        copy_of = getattr(self, "_copy_of", None) or {}
        kept = [d for d in members if d in copy_of.values()]
        watching = sorted(d for d in members if d in self._watched)  # type: ignore[attr-defined]
        # The device the hardware is watched through: the one kept when
        # copies are set aside, or the only watched member. With two
        # watched (restart grace, or one whose entities are all
        # disabled) or none, there is no single answer, so the page
        # words its line from each row instead.
        watched_through = copy_of.get(device_id) or (kept[0] if kept else None) or (
            watching[0] if len(watching) == 1 else None
        )
        records = (self.data or {}).get(DATA_DEVICES, {})  # type: ignore[attr-defined]
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]

        def row(other: str) -> dict[str, Any]:
            device = registry.async_get(other)
            domain = self._primary_domain(device) if device is not None else None  # type: ignore[attr-defined]
            return {
                "device_id": other,
                "name": self._device_name(other),  # type: ignore[attr-defined]
                # The name shown elsewhere on the page, "UniFi Network",
                # not the domain "unifi".
                "integration": self._integration_name_of(other, domain) if domain else None,
                "domain": domain,
                "watched": other in self._watched,  # type: ignore[attr-defined]
                # Why a clone is not watched: "clone", or the reason it
                # would be set aside anyway, such as an exclusion.
                "set_aside": (self._set_aside.get(other) or (None, None, None))[2],  # type: ignore[attr-defined]
                # A device never watched has no page, so the panel shows
                # its name without a link.
                "has_page": other in records,
            }

        return {
            "watched_through": watched_through,
            "devices": [row(d) for d in sorted(members, key=lambda d: (d != watched_through, d))],
        }

    def iot_class_of(self, domain: str | None) -> str | None:
        """How an integration talks to its devices: its manifest's
        iot_class, read through Home Assistant's public loader, with
        nothing added to Device Sentinel's own manifest."""
        if not domain:
            return None
        try:
            return async_get_loaded_integration(self.hass, domain).iot_class  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - not loaded, or no manifest
            return None

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
        # there is no MQTT, so the header shows it only where an MQTT
        # integration is configured (rule UP-02).
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
                # "Wi-Fi" in the band; the sensor keeps its entity name,
                # so no automation reading it breaks (rule DASH-16).
                "name": WIFI_BAND_NAME,
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
            # The view the dashboard opens in (rule DASH-03).
            "dashboard": self.dashboard_mode,
            # The release running, for the dashboard's foot (rule DASH-15).
            "release": self.dashboard_release(),
        }

    def dashboard_release(self) -> dict[str, str | None]:
        """The release running: its name, and a link to its notes.

        The link only where the version reads as a release tag, digits
        and dots, so an odd manifest value prints plain rather than
        building an address from it.
        """
        version = self.version if isinstance(self.version, str) else ""
        tagged = re.fullmatch(r"\d+(?:\.\d+){1,3}", version) is not None
        return {
            "words": f"Device Sentinel {version}".strip(),
            "url": RELEASE_NOTES_URL.format(version=version) if tagged else None,
        }

    @property
    def dashboard_mode(self) -> str:
        """Simple or Advanced, as the Advanced settings screen holds it."""
        mode = self.entry.options.get(CONF_DASHBOARD_MODE, DEFAULT_DASHBOARD_MODE)
        return mode if mode in DASHBOARD_MODES else DEFAULT_DASHBOARD_MODE


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

    def _outage_label(self, kind: str, scope: Any, detail: Any = None) -> str:
        if kind in (SYS_BRIDGE_DOWN, SYS_BRIDGE_UP):
            return BRIDGE_SENSOR_NAMES.get(scope, f"{scope} Bridge")
        if kind in (SYS_BROKER_DOWN, SYS_BROKER_UP):
            return BROKER_SENSOR_NAME
        # One device's own entry: named by the device, whose connection
        # it is, rather than as the whole integration.
        device = self.outage_device_name(detail)
        if device is not None:
            return f"{device} ({self._integration_title(str(scope))} connection)"
        return f"{self._integration_title(str(scope))} integration"

    def integration_outages(self) -> dict[str, list[dict[str, Any]]]:
        """Every outage of the last fourteen days, by owning integration.

        Each down is paired with its own return by kind and scope. The
        return carries the length and how many devices the outage took;
        an outage with no return yet is open. Newest first (rule UP-11).
        """
        now = dt_util.utcnow().timestamp()
        since = now - OUTAGE_WINDOW_DAYS * 86400.0
        rows = sorted(
            (row for row in self.data.get(DATA_SYSTEM_EVENTS) or [] if isinstance(row, dict)),
            key=lambda row: row.get(SYS_WHEN) or 0,
        )
        open_rows: dict[tuple[str, Any, Any], dict[str, Any]] = {}
        found: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            kind, scope, when = row.get(SYS_KIND), row.get(SYS_SCOPE), row.get(SYS_WHEN)
            if not isinstance(when, (int, float)):
                continue
            # Paired by entry too, so two entries of one integration
            # are two outages.
            entry = pair_key(kind, scope, row.get(SYS_DETAIL))[2]
            if kind in _OPENERS:
                open_rows[(kind, scope, entry)] = row
            elif kind in _CLOSERS:
                opened = open_rows.pop((_CLOSERS[kind], scope, entry), None)
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
                    "what": self._outage_label(kind, scope, row.get(SYS_DETAIL)),
                    "duration": duration if isinstance(duration, (int, float)) else None,
                    "devices": row.get(SYS_DEVICES),
                    "worst": row.get(SYS_WORST),
                    "open": False,
                }))
        for (kind, scope, entry), row in open_rows.items():
            owner = self._outage_owner(kind, scope)
            if owner is None or row[SYS_WHEN] < since:
                continue
            # An older integration outage names no entry, and a run
            # recorded one afresh after each restart, so it never meets
            # its return and read "still down" for days while its
            # devices reported. Closed at the upgrade without a word,
            # because the entry-named rows tell its outages since.
            if kind == SYS_INTEGRATION_DOWN and entry is None:
                continue
            found.append((owner, {
                "went_down": dt_util.utc_from_timestamp(row[SYS_WHEN]).isoformat(),
                "what": self._outage_label(kind, scope, row.get(SYS_DETAIL)),
                "duration": None, "devices": None, "worst": None, "open": True,
            }))
        by_owner: dict[str, list[dict[str, Any]]] = {}
        for owner, outage in sorted(found, key=lambda pair: pair[1]["went_down"], reverse=True):
            by_owner.setdefault(owner, []).append(outage)
        return by_owner

    def _is_helper(self, domain: str) -> bool:
        """Return whether Home Assistant marks this integration a helper.

        Read from the integration's own manifest, so no list of helpers
        is kept here and one added next year is told apart too. An
        integration not loaded, or unknown, reads as no helper.
        """
        try:
            integration = async_get_loaded_integration(self.hass, domain)
        except Exception:  # noqa: BLE001 - an unknown domain is not a helper
            return False
        return getattr(integration, "integration_type", None) == "helper"

    def _rider_devices(self, domain: str) -> list[dict[str, Any]]:
        """The watched devices an integration with no hardware adds
        entities to, each with its area and those entities."""
        areas = ar.async_get(self.hass)
        devices = dr.async_get(self.hass)
        listed = []
        for device_id, by_platform in self._foreign_ids.items():
            entities = by_platform.get(domain)
            if not entities or device_id not in self._watched:
                continue
            device = devices.async_get(device_id)
            area = (
                areas.async_get_area(device.area_id)
                if device is not None and device.area_id
                else None
            )
            listed.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "area": area.name if area else None,
                "entities": sorted(entities),
            })
        listed.sort(key=lambda row: str(row["name"]).lower())
        return listed

    def _integration_standing(self, domain: str, watched: int) -> str:
        if domain in self.excluded_integrations:
            return "excluded"
        if domain in set(self.entry.options.get(CONF_MUTED_INTEGRATIONS, [])):
            return "muted"
        if not watched and domain in self._no_hardware_integrations:
            return STANDING_HELPER if self._is_helper(domain) else STANDING_NO_HARDWARE
        if not watched:
            # Every one of its devices excluded on its own reads
            # excluded, not service only (rule MUTE-03).
            reasons = {
                reason for _name, owner, reason in self._set_aside.values()  # type: ignore[attr-defined]
                if owner == domain
            }
            if reasons == {SET_ASIDE_EXCLUDED}:
                return "excluded"
            # Every device set aside for having nothing but firmware
            # notices or command buttons switched on, which "service
            # only" would misdescribe (rule WATCH-04).
            if reasons and reasons <= {SET_ASIDE_NOTICES_ONLY, SET_ASIDE_NO_ENTITIES}:
                # Either reason, alone or together.
                return STANDING_NOTICES_ONLY
        return "watched" if watched else "service"

    # Which kind a phrase in a problem summary came from.
    # The summary words each kind through `_kind_word`, so a phrase is
    # matched back by the word that kind always carries. A phrase that
    # matches nothing, or matches a kind the item does not hold, is
    # left without an age rather than given a wrong one.
    _PROBLEM_TOKENS: tuple[tuple[str, str], ...] = (
        ("never reported", TODO_KIND_NEVER_REPORTED),
        ("unavailable", TODO_KIND_UNAVAILABLE),
        ("frozen", TODO_KIND_FROZEN),
        ("stopped reporting", TODO_KIND_FROZEN),
        ("unknown", TODO_KIND_UNKNOWN),
        ("signal", TODO_KIND_RAILED_SIGNAL),
        ("empty in", TODO_KIND_FALLING_BATTERY),
        ("reaches", TODO_KIND_FALLING_BATTERY),
        ("battery", TODO_KIND_LOW_BATTERY),
    )

    def _problem_since(self, part: str, kinds: dict[str, Any]) -> float | None:
        """When the problem this phrase describes began, or None."""
        lowered = part.lower()
        for token, kind in self._PROBLEM_TOKENS:
            if token in lowered:
                since = kinds.get(kind)
                return since if isinstance(since, (int, float)) else None
        return None

    def _problem_text(self, item: dict[str, Any]) -> str:
        """One device's problems, each with its own age.

        One row dated from the older problem hid the newer one, so a
        short freeze on a device with an old battery fault appeared
        nowhere.
        """
        name = item.get(TODO_SORT_NAME) or ""
        summary = item[TODO_SUMMARY]
        text = summary[len(name) + 2:] if summary.startswith(f"{name}: ") else summary
        kinds = item.get(TODO_KINDS) or {}
        if len(kinds) < 2:
            return text
        now = dt_util.utcnow().timestamp()
        aged = []
        for part in text.split(", "):
            since = self._problem_since(part, kinds)
            aged.append(
                f"{part} {self._human_span(now - since)}"
                if since is not None
                else part
            )
        return ", ".join(aged)

    def _problems_by_device(self) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for item in self.todo_items:
            found[item[TODO_DEVICE_ID]] = {
                "problem": self._problem_text(item),
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
        # Excluded by Device Sentinel when first seen, not by the person
        # from a card.
        seen_routers = set(self.data.get(DATA_ROUTERS_SEEN) or []) - set(self.exclusion_offers())
        domains: dict[str, dict[str, int]] = {}
        for row in rows:
            count = domains.setdefault(row["integration"], {
                "watched": 0, "muted": 0, "set_aside": 0, "problems": 0, "acknowledged": 0,
            })
            if row["watched"]:
                count["watched"] += 1
            else:
                count["set_aside"] += 1
            # The global mute alone: the MUTED cell also carries the
            # battery, signal and freeze mutes, and a phone muted for
            # battery only is not a muted device.
            if row["muted_global"]:
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
        # An integration with no hardware owns no row above; it is
        # listed so a person can see it and why its entities are not
        # counted. "adds_to" is how many watched devices carry its
        # entities.
        for domain in sorted(self._no_hardware_integrations - set(domains)):
            adds_to = len([
                device_id
                for device_id, counts in self._foreign_by_device.items()
                if domain in counts and device_id in self._watched
            ])
            result.append({
                "domain": domain,
                "name": self._integration_title(domain),
                "standing": self._integration_standing(domain, 0),
                "first_seen": False,
                "watched": 0, "muted": 0, "set_aside": 0,
                "problems": 0, "acknowledged": 0, "outages": 0,
                "adds_to": adds_to,
            })
        result.sort(key=lambda row: row["name"].lower())
        return result

    def dashboard_integration(self, domain: str) -> dict[str, Any] | None:
        """One integration's page, or None if no device belongs to it.

        An integration with no hardware of its own owns no device, so
        its page is the devices it adds entities to, and those entities
        by id, for a person to open.
        """
        devices = [row for row in self.classification_rows() if row["integration"] == domain]
        if not devices and domain in self._no_hardware_integrations:
            return {
                "domain": domain,
                "name": self._integration_title(domain),
                "standing": self._integration_standing(domain, 0),
                "rider": True,
                "devices": self._rider_devices(domain),
            }
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
                # The global mute alone, which the Integrations tab
                # counts (rule DASH-16).
                "muted_global": row["muted_global"],
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
        # The devices another integration owns that reach Home
        # Assistant through the broker, listed on MQTT's page beneath
        # its own.
        behind_broker: list[dict[str, Any]] = []
        if domain == BROKER_SCOPE:
            for row in self.classification_rows():
                if row["integration"] not in BROKER_RIDER_DOMAINS:
                    continue
                problem = problems.get(row["device_id"])
                behind_broker.append({
                    "device_id": row["device_id"],
                    "name": row["name"],
                    "integration": self._integration_title(row["integration"]),
                    "watched": row["watched"],
                    "muted": row["muted"],
                    "set_aside": row["set_aside"],
                    "problem": problem["problem"] if problem else "",
                    "acknowledged": bool(problem and problem["acknowledged"]),
                })
            behind_broker.sort(key=lambda row: row["name"].lower())
        return {
            "domain": domain,
            "name": title,
            "standing": self._integration_standing(domain, watched),
            "first_seen": domain in (self.data.get(DATA_ROUTERS_SEEN) or [])
            and domain not in self.exclusion_offers()
            and domain in self.excluded_integrations,
            "devices": listed,
            # On the exclusion list, so the page offers to take it back;
            # otherwise it offers to exclude it (rule MUTE-03).
            "excluded": domain in self.excluded_integrations,
            "behind_broker": behind_broker,
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


def _count_types(kinds: Any) -> dict[str, int]:
    """How many of each type, "" for no type."""
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind or ""] = counts.get(kind or "", 0) + 1
    return counts


def _iso(stamp: Any) -> str | None:
    """A stored timestamp as ISO text, or None."""
    return dt_util.utc_from_timestamp(stamp).isoformat() if isinstance(stamp, (int, float)) else None


def _firmware(device: Any, record: dict[str, Any]) -> dict[str, Any] | None:
    """The device's firmware for its page: the version now, and its history.

    The version now is the registry's; a version not yet held ten
    minutes is not in the history, and the page should still show what
    the device runs. A device that stops giving one keeps its last
    recorded, as the record does. The history is oldest first, each
    version with the moment it was first seen. None when there is
    neither, so the page leaves the row out. The panel draws it in
    Advanced only (rule DEV-15).
    """
    history = [
        {"version": str(pair[0]), "since": _iso(pair[1])}
        for pair in (record.get(DEV_FIRMWARE_HISTORY) or [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] is not None
    ]
    current = shown(device_field(device, "sw_version")) or (history[-1]["version"] if history else None)
    if current is None:
        return None
    return {"current": current, "history": history}


class DeviceViewMixin:
    """The Devices tab and each device's page."""

    def _device_rhythm(self, record: dict[str, Any]) -> tuple[float | None, list[int]]:
        gaps = (record.get(DEV_DAILY_MAX) or [])[-DAILY_MAX_KEEP:]
        rhythm, set_aside = self._trimmed_maximum(gaps)
        return rhythm, sorted(set_aside)

    def _rhythm_in_use(self, record: dict[str, Any]) -> float | None:
        """The rhythm of the rule the wait is built from.

        Showing the Trimmed Maximum's rhythm beside a window built from
        the Log-Normal Percentile made a plug read "rhythm 3.2h" beside
        "window 34m". Young devices, with only the Trimmed Maximum, read
        as before.
        """
        found = self._freeze_rhythm(record)  # type: ignore[attr-defined]
        if found:
            return found.get("rhythm")
        rhythm, _ = self._device_rhythm(record)
        return rhythm

    def _integration_name_of(self, device_id: str, domain: str | None = None) -> str:
        """The name shown for a device's integration.

        A Zigbee2MQTT device reaches Home Assistant through the MQTT
        integration, but its faults are Zigbee's. So it is named for the
        stack that owns it, the same on the Problem List, the Devices
        tab and its page; every other device for its integration. The
        domain still opens the integration's page (rule GEN-07).
        """
        domain = domain or self._watched.get(device_id)  # type: ignore[attr-defined]
        if not domain:
            return ""
        device = dr.async_get(self.hass).async_get(device_id)  # type: ignore[attr-defined]
        # A child device entry (2026.9) carries no identifiers of its
        # own, so it keeps its integration's name.
        if isinstance(device, dr.DeviceEntry) and stacks.radio_owner(domain, device) == STACK_Z2M:
            return STACK_DISPLAY_NAMES[STACK_Z2M]
        return str(self._integration_title(domain))  # type: ignore[attr-defined]

    def _both_rules(self, record: dict[str, Any]) -> dict[str, Any]:
        """Both freeze rules as the device page draws them."""
        daily = record.get(DEV_DAILY_MAX) or []
        found = self._freeze_rhythm(record)  # type: ignore[attr-defined]
        out: dict[str, Any] = {
            "trimmed": None, "trimmed_days": None, "lognormal": None,
            "lognormal_days": None, "lognormal_gaps": [], "lognormal_set_aside": [],
            "in_use": None, "counting_again": None,
        }
        # The Log-Normal Percentile counting again after a reset:
        # where its chart stood, the page says since when and how many
        # days are left, rather than leaving the space empty.
        since_reset = record.get(DEV_LOGNORMAL_DAYS)
        if (
            isinstance(since_reset, (int, float))
            and not isinstance(since_reset, bool)
            and 0 <= since_reset < CLIP_START_DAYS
            and len(daily) > since_reset
        ):
            since_reset = int(since_reset)
            # The first day counted since, by the history's own dates, so
            # a day with no learned gap does not move it (adversarial
            # round); today when none is counted yet.
            yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
            dates = dates_for(record, FAMILY_GAP, len(daily), yesterday)
            restarted = dates[-since_reset] if since_reset and len(dates) >= since_reset else dt_util.now().date()
            out["counting_again"] = {
                "since": restarted.isoformat(),
                "to_go": CLIP_START_DAYS - since_reset,
            }
        if not found:
            return out
        out["trimmed"] = found.get("trimmed")
        out["trimmed_days"] = found.get("trimmed_days")
        out["in_use"] = "lognormal" if found.get("rule") == RULE_LOGNORMAL else "trimmed"
        fit = found.get("fit")
        days = found.get("lognormal_days")
        if fit and isinstance(days, int) and days > 0:
            start = max(0, len(daily) - days)
            out["lognormal"] = found.get("lognormal")
            out["lognormal_days"] = days
            out["lognormal_gaps"] = list(daily[start:])
            out["lognormal_set_aside"] = sorted(
                i - start for i in fit.get("set_aside", []) if isinstance(i, int) and i >= start
            )
        return out

    def _rhythm_on_days(self, record: dict[str, Any]) -> dict[str, list[Any]]:
        """The rhythm chart's history laid out one slot a day.

        The gap history writes nothing on a day with no learned gap, so
        the chart, which reads by position, drew those days away. Each
        entry moves to its day's slot, with an empty slot for a skipped
        day, and the deciding and set-aside marks, which are positions
        in the history, move with their entries.
        """
        out = dict(self._rhythm_history(record))
        out["daily"] = list(record.get(DEV_DAILY_MAX) or [])
        daily = out["daily"]
        end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
        dates = dates_for(record, FAMILY_GAP, len(daily), end)
        if not dates:
            return out
        start = min(dates[0], end)
        span = (end - start).days + 1
        slot = [(when - start).days for when in dates]

        def moved(values: list[Any]) -> list[Any]:
            laid: list[Any] = [None] * span
            for index, value in enumerate(values[: len(slot)]):
                if 0 <= slot[index] < span:
                    laid[slot[index]] = value
            return laid

        laid = {key: moved(values) for key, values in out.items() if key not in ("deciding", "aside")}
        laid["deciding"] = moved(
            [None if d is None or not 0 <= d < len(slot) else slot[d] for d in out.get("deciding") or []]
        )
        laid["aside"] = moved(
            [[slot[j] for j in (a or []) if 0 <= j < len(slot)] for a in out.get("aside") or []]
        )
        laid["aside"] = [a if a is not None else [] for a in laid["aside"]]
        return laid

    def _rhythm_history(self, record: dict[str, Any]) -> dict[str, list[Any]]:
        """Each day's two waits, the rule in use, and the Trimmed
        Maximum's deciding and set-aside days.

        Worked out from the days before each day, as the detector
        worked them out then. The count since a reset is worked back
        from today's: a reset more than 42 days old has let go of its
        count, so days before it are drawn as if none happened, which
        changes only how old days are drawn, never today's wait.
        """
        # Worked out on each request and kept nowhere, because a device
        # page asks only while it is open, once a minute, and everyday
        # running matters more than browsing. A year of history costs
        # about 71 ms per request; with no page open it costs nothing,
        # and no history sits in memory.
        source = record.get(DEV_DAILY_MAX)
        since = record.get(DEV_LOGNORMAL_DAYS)
        daily = list(source or [])
        out: dict[str, list[Any]] = {
            "windows": [], "trimmed": [], "lognormal": [], "rule": [],
            "deciding": [], "aside": [],
        }
        for index in range(len(daily)):
            prefix = daily[:index]
            back = len(daily) - index
            then = (
                None
                if not isinstance(since, (int, float)) or isinstance(since, bool)
                else max(0, int(since) - back)
            )
            found = (
                self._compute_freeze_rhythm({DEV_DAILY_MAX: prefix, DEV_LOGNORMAL_DAYS: then})
                if index
                else None
            )
            if found is None:
                for key in out:
                    out[key].append(None)
                continue
            out["windows"].append(found["rhythm"] + self._freeze_grace(found["rhythm"]))
            out["trimmed"].append(found["trimmed"] + self._freeze_grace(found["trimmed"]))
            out["lognormal"].append(
                found["lognormal"] + self._freeze_grace(found["lognormal"])
                if found["lognormal"] is not None
                else None
            )
            out["rule"].append(self.rule_label(found))
            window = prefix[-DAILY_MAX_KEEP:]
            offset = len(prefix) - len(window)
            _rhythm, aside = self._trimmed_maximum(window)
            survivors = [i for i in range(len(window)) if i not in aside]
            deciding = max(survivors, key=lambda i: window[i]) if survivors else None
            out["deciding"].append(None if deciding is None else deciding + offset)
            out["aside"].append(sorted(i + offset for i in aside))
        return out

    def _rhythm_scale(self, record: dict[str, Any]) -> float | None:
        """The tallest figure worth drawing a rhythm chart against."""
        daily = [
            value
            for value in (record.get(DEV_DAILY_MAX) or [])
            if isinstance(value, (int, float))
        ]
        if not daily:
            return None
        # The days the two rules read, less the days each sets aside,
        # so one very long old day does not set the scale of every
        # chart after it.
        _rhythm, aside = self._trimmed_maximum(daily[-DAILY_MAX_KEEP:])
        recent = daily[-DAILY_MAX_KEEP:]
        kept = [value for index, value in enumerate(recent) if index not in aside]
        rules = self._both_rules(record)
        gaps = rules.get("lognormal_gaps") or []
        set_aside = set(rules.get("lognormal_set_aside") or [])
        kept += [
            value for index, value in enumerate(gaps)
            if index not in set_aside and isinstance(value, (int, float))
        ]
        window = self._freeze_window(record)
        return max([*kept, window] if window is not None else kept or [0.0])

    def _page_status(self, device_id: str, record: dict[str, Any]) -> str:
        """The stored verdict the Problem List reads, or what else is
        true of the device.

        Not everything without a freeze verdict is reporting: a device
        nobody watches has no verdict to give, and one that has never
        reported has not reported.
        """
        # A device in a flap reads as the flap, the same word the list
        # gives it, whether or not it is down this minute. A device
        # muted for unavailable, or for everything, is off the list and
        # reads no flap either (rule MUTE-06).
        if (
            device_id in self._watched
            and device_id not in self._muted_devices
            and not self._unavailable_muted(device_id)  # type: ignore[attr-defined]
            and self.is_flapping(device_id)
        ):
            return TODO_KIND_FLAPPING
        verdict = record.get(DEV_FROZEN_CATEGORY)
        # A verdict held behind a down upstream is kept while the device
        # is not judged, but one its mutes cover is not shown.
        if verdict and device_id not in self._muted_devices and self._muted_away(  # type: ignore[attr-defined]
            verdict,
            self._freeze_muted(device_id),  # type: ignore[attr-defined]
            self._unavailable_muted(device_id),  # type: ignore[attr-defined]
        ):
            return verdict
        if device_id not in self._watched:
            return STATUS_SET_ASIDE
        if self._connection_only(device_id) or self.judged_by_hub(device_id):  # type: ignore[attr-defined]
            # Its connection is its report, and it is not down.
            # A device its hub judges is never called never reported,
            # because a Pico nobody has pressed is fine (rule FRZ-01).
            return STATUS_REPORTING
        if record.get(DEV_LAST_ACTIVITY) is None:
            return STATUS_NEVER_REPORTED
        return STATUS_REPORTING

    def _judged_available(self, device_id: str, record: dict[str, Any]) -> bool:
        """Whether the device is judged by being available rather than by
        a window: a Matter device of a type that reports only on use,
        with no frozen verdict standing (rule STACK-06)."""
        return bool(
            self._matter_available_now(device_id)  # type: ignore[attr-defined]
            and record.get(DEV_FROZEN_CATEGORY) != FREEZE_CATEGORY_FROZEN
        )

    def _judged_by(self, device_id: str) -> dict[str, Any] | None:
        """How a device never judged for freezing is judged, for its page
        and its Devices row: by its hub, named, or by its connection.
        None for a device judged by a window, or by being available
        (rule STACK-06), which keeps its own words.

        A device a hub controls is never frozen whether or not the hub
        is watched (judged_by_hub); "hub_page" says whether the hub has
        a Device Sentinel page, else the link opens Home Assistant's.
        A hub itself is judged by its connection (rule STACK-10).
        """
        hub = self.hub_of(device_id)  # type: ignore[attr-defined]
        if hub is not None:
            return {
                "how": "hub",
                "hub_id": hub,
                "hub_name": self._device_name(hub),
                "hub_page": hub in self._watched,
            }
        if self.judged_by_hub(device_id) or self._connection_only(device_id):  # type: ignore[attr-defined]
            return {"how": "connection"}
        return None

    def dashboard_devices(self) -> list[dict[str, Any]]:
        """One row per watched device, by name."""
        records = self.data.get(DATA_DEVICES) or {}
        problems = self._problems_by_device()
        rows = []
        for device_id, domain in self._watched.items():
            record = records.get(device_id) or {}
            rhythm = self._rhythm_in_use(record) if record.get(DEV_DAILY_MAX) else None
            problem = problems.get(device_id)
            # No window for a device judged by being available, or by
            # its connection alone, as its page has it. Nor a hub, or a
            # device a hub controls, watched or not: neither is judged
            # by a window, and the row says how it is judged (rules
            # STACK-06, STACK-10).
            judged_by = self._judged_by(device_id)
            judged_by_window = not self._judged_available(device_id, record) and judged_by is None
            # A device with no learned day yet is learning too, as its
            # page says.
            window = (
                self._freeze_window(record)
                if judged_by_window and record.get(DEV_DAILY_MAX) else None
            )
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "integration": domain,
                "integration_name": self._integration_name_of(device_id, domain),
                "muted": self.mute_text(device_id),
                "status": self._page_status(device_id, record),
                "problem": problem["problem"] if problem else "",
                "acknowledged": bool(problem and problem["acknowledged"]),
                "last_activity": _iso(record.get(DEV_LAST_ACTIVITY)),
                "rhythm": rhythm,
                "window": window,
                # Still learning its window: days held, not yet enough.
                # The cell reads "learning", not blank (rule DASH-16).
                "window_learning": judged_by_window and window is None,
                # By its hub or by its connection, in place of a window.
                "judged_by": judged_by,
                "type": self.type_words(device_id),
                # For the tab's Area and Label filters (rule DASH-12).
                **self._area_and_labels(device_id),
            })
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    def _area_and_labels(self, device_id: str) -> dict[str, Any]:
        """The device's area name and label names, read live from Home
        Assistant's registries; nothing of it is stored (rule DASH-12)."""
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return {"area": None, "labels": []}
        area = None
        if device.area_id:
            entry = ar.async_get(self.hass).async_get_area(device.area_id)
            area = entry.name if entry else None
        labels_reg = lr.async_get(self.hass)
        labels = sorted(
            (
                entry.name
                for entry in (labels_reg.async_get_label(label_id) for label_id in (device.labels or ()))
                if entry is not None
            ),
            key=str.casefold,
        )
        return {"area": area, "labels": labels}

    def dashboard_excluded_devices(self) -> list[dict[str, Any]]:
        """The devices on the exclusion lists, for the Devices tab's
        Excluded list (rule DASH-12).

        Read live from the registry and the options: an excluded device
        is never recorded, so what is shown is what Home Assistant has
        now. A device excluded on its own can be taken back from the
        list; one excluded with its integration is taken back with the
        integration, because the broader exclusion covers it (rule
        MUTE-04). Its Device Sentinel page exists until the midnight
        that deletes its history; after that its name opens Home
        Assistant's own.
        """
        own = self.excluded_devices
        integrations = self.excluded_integrations
        records = self.data.get(DATA_DEVICES) or {}
        rows = []
        for device_id, (_name, domain, reason) in list(self._set_aside.items()):
            if reason != SET_ASIDE_EXCLUDED:
                continue
            by_integration = domain in integrations
            if not by_integration and device_id not in own:
                continue
            kept = device_id in records and not self.is_held(device_id)
            rows.append({
                "device_id": device_id,
                "name": self._device_name(device_id),
                "integration": domain,
                "integration_name": self._integration_name_of(device_id, domain),
                "how": "integration" if by_integration else "device",
                "page": kept,
                **self._area_and_labels(device_id),
            })
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    def dashboard_device(self, device_id: str) -> dict[str, Any] | None:
        """Everything known about one device, or None if it has no record.

        Read live from the registry where the registry is the truth
        (name, manufacturer, model, model id, hardware version, area,
        connections), because nothing of it is stored. The model id and
        hardware version are the fields the battery library matches on
        beside manufacturer and model (power_source.py).
        """
        records = self.data.get(DATA_DEVICES) or {}
        record = records.get(device_id)
        if record is None:
            return None
        device = dr.async_get(self.hass).async_get(device_id)
        if self.is_held(device_id):  # type: ignore[attr-defined]
            # Removed from Home Assistant, its record held in case it
            # comes back: there is no device to show (rule WATCH-07).
            return None
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
                    reading: dict[str, Any] = {"kind": kind, "entity_id": entity.entity_id}
                    if kind == "battery" and record.get(DEV_BATTERY_RAW_SCALE):
                        # The sensor's own state is on Zigbee's raw 0 to
                        # 200 scale, so the page shows it as raw beside
                        # the halved percentage Device Sentinel uses
                        # everywhere else; a bare 182% read as a broken
                        # cell (rule BAT-02).
                        reading["raw_scale"] = True
                    readings.append(reading)
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
                # Truncated by an intervention and waiting on the
                # device's first word since.
                # The whole silence while it is still running, as the
                # file shows it.
                "silence_total": (
                    dt_util.utcnow().timestamp() - row[EP_SINCE]
                    if isinstance(row.get(EP_SINCE), (int, float))
                    else None
                ),
                "still_silent": bool(
                    row.get(EP_ENDED)
                    and row.get(EP_ENDED) != EPISODE_ENDED_RESUMED
                    and row.get(EP_LAG) is None
                ),
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
                # A child device entry carries none of these.
                # getattr alone does not spare it: the child answers the
                # attribute with a deprecation line, so device_field
                # asks what the entry is first.
                # Each as the page shows it: nothing, or only zeros,
                # is None, and the page leaves the row out.
                "manufacturer": shown(device_field(device, "manufacturer")),
                "model": shown(device_field(device, "model")),
                "model_id": shown(device_field(device, "model_id")),
                "hw_version": shown(device_field(device, "hw_version")),
                # What it runs, and what it ran before (rule DEV-15).
                "firmware": _firmware(device, record),
                "area": area_name,
                "integration": domain,
                "integration_name": self._integration_name_of(device_id, domain) if domain else None,
                # The integration itself, for what is set on it: an
                # integration mute on MQTT names MQTT, though the device
                # is shown as Zigbee2MQTT's.
                "integration_title": self._integration_title(domain) if domain else None,
                # How it connects, from its integration's declaration.
                # Not for a device that reports changes on the local
                # network as they happen, the way nearly all do, because
                # a row the same on every page says nothing.
                "connects": (
                    None
                    if (iot_class := self.iot_class_of(domain)) == "local_push"
                    else CONNECTS_WORDS.get(iot_class or "")
                ),
                # Its addresses, each row named by its kind (rule DEV-13).
                "addresses": addresses(device),
                "connections": sorted(
                    [kind, value]
                    for kind, value in device_field(device, "connections", set())
                ),
                "first_observed": record.get(DEV_FIRST_OBSERVED),
                "event_count": record.get(DEV_EVENT_COUNT),
                # The Last Seen clock it is judged by: a Last Seen
                # entity, its stack's own, named by the stack, as ZHA
                # keeps, or none (rule STACK-04).
                "clock": (
                    "last_seen" if device_id in self._last_seen_entity
                    else heard[0] if (heard := stacks.last_heard(
                        self.hass, self._watched.get(device_id), device_id))
                    else "recorded"
                ),
                # Z-Wave's own status for the node: what the sensor
                # reads, "off" when it is switched off, or None for a
                # device without one (rule STACK-05).
                "node_status": self._node_status_view(device_id),
                # Battery Last Replaced: None on mains (rule BAT-07).
                "battery_replaced": self.battery_replacement_view(device_id),  # type: ignore[attr-defined]
                "watched": device_id in self._watched,
                "set_aside": (self._set_aside.get(device_id) or (None, None, ""))[2],
                "muted": self.mute_text(device_id),
                # What the page's actions need: the area's id, the
                # person's name and the integration's, the labels with
                # their meanings, a switched-off Last Seen, and each kind
                # of mute with its source (rule DASH-09).
                "actions": self.page_actions(device_id),
                # What powers it: the owner's entry, else the shipped
                # Battery Notes library, else "Not known".
                "power": self.power_view(device_id),
                # What it is: the owner's answer, else what its entities
                # say, else nothing and the pencil.
                "type": self.type_view(device_id),
                # The other devices Home Assistant shows for the same
                # hardware, and which one Device Sentinel watches it
                # through (rule WATCH-06).
                "same_hardware": self.same_hardware(device_id),
                # How the cell reports, in the words Battery Trends
                # uses; empty for a device with no battery.
                "battery_steps": (
                    BATTERY_STEPS_WORDS[self.battery_steps(record)]
                    if record.get(DEV_BATTERY_VALUE) is not None
                    else ""
                ),
            },
            "readings": readings,
            "status": {
                "category": self._page_status(device_id, record),
                # How big the flap is, beside the word.
                # Not for a device muted for unavailable or for
                # everything, which reads no flap (rule MUTE-06).
                "flap": (
                    self.flap_words(device_id).removeprefix("flapping, ")
                    if self.is_flapping(device_id)
                    and device_id not in self._muted_devices
                    and not self._unavailable_muted(device_id)  # type: ignore[attr-defined]
                    else ""
                ),
                "last_activity": _iso(record.get(DEV_LAST_ACTIVITY)),
                # A device judged by its connection alone: "connected" or
                # "dropped", else None.
                # "not known" when it cannot be read, or the device
                # sleeps.
                "connection": (
                    (
                        "dropped" if self._dropped_esphome(device_id)  # type: ignore[attr-defined]
                        else "connected" if self._awake_esphome(device_id)  # type: ignore[attr-defined]
                        else "not known"
                    )
                    if self._connection_only(device_id)  # type: ignore[attr-defined]
                    else None
                ),
                # The rule in use, as the window is.
                "rhythm": self._rhythm_in_use(record) if record.get(DEV_DAILY_MAX) else rhythm,
                # No freeze window for a device judged by its connection
                # alone.
                "window": None if self._connection_only(device_id) else self._freeze_window(record),  # type: ignore[attr-defined]
                # A Matter device of a type that reports only on use, never
                # newly called frozen while available: the page says so in
                # place of its window (rule STACK-06).
                "available_rule": self._judged_available(device_id, record),
                # Never judged for freezing, by its hub or by its
                # connection. The page shows this in place of the window,
                # the wait rule and the learning line.
                "judged_by": self._judged_by(device_id),
                # The rule in use, as people read it: "37-Day
                # Log-Normal Percentile".
                "rule": self.rule_label(self._freeze_rhythm(record)),
            },
            "rhythm": {
                "gaps": list((record.get(DEV_DAILY_MAX) or [])[-DAILY_MAX_KEEP:]),
                "set_aside": set_aside,
                # Both rules side by side: each one's figure and days,
                # which one is in use, and the Log-Normal Percentile's
                # own days with those it set aside, for its chart beneath
                # the Trimmed Maximum's. A block of their own, because
                # the History chart's day-by-day series already use the
                # names "trimmed" and "lognormal" in this one, and would
                # overwrite the figures.
                "rules": self._both_rules(record),
                # What the chart can be read against: the larger of the
                # device's window and its largest day the trim did not
                # set aside. A sensor away from the house for six weeks
                # would otherwise flatten every ordinary day.
                "scale": self._rhythm_scale(record),
                # The whole history, and the window each day had,
                # worked out from the days before it as the detector
                # worked it out then.
                "daily": list(record.get(DEV_DAILY_MAX) or []),
                # Each day's window in use ("windows"), both rules'
                # waits each day, the rule in use, and the
                # days that set and were set aside by the Trimmed
                # Maximum, for the chart's marks, laid out one slot a
                # day.
                **self._rhythm_on_days(record),
            },
            "silences": silences,
            # Judged by its hub: for a device a hub controls, its hub;
            # for a hub, its state, the devices it controls and its
            # outages. None for every other device (rule STACK-10).
            "hub": self.hub_view(device_id, dt_util.utcnow().timestamp()),  # type: ignore[attr-defined]
            "hub_self": self.hub_self_view(device_id, dt_util.utcnow().timestamp()),  # type: ignore[attr-defined]
            "battery": self._page_battery(record, device_id),
            "signal": self._page_signal(record),
            "outages": self.device_outages(domain),
            # Every daily series ends on the last day the midnight roll
            # folded, which is yesterday.
            "series_end": (dt_util.now().date() - timedelta(days=1)).isoformat(),
            "history_days": self.retention_days,
        }

    def _page_battery(self, record: dict[str, Any], device_id: str | None = None) -> dict[str, Any]:
        """The battery history and the report's own figures for it.

        The windows, the blocks, the reading and the time left come
        from the same battery rows Battery Trends is built from, so the
        two pages say the same thing about the same cell.
        """
        level = record.get(DEV_BATTERY_VALUE)
        # Laid out one slot a day, for the fit and the chart alike.
        series = battery_calendar(record)
        # A percentage runs from nothing to full: a reading outside
        # that is a raw sensor value, whichever end it is outside at,
        # and would otherwise be drawn against the threshold (rule
        # BAT-02).
        readable = (
            isinstance(level, (int, float))
            and 0.0 <= float(level) <= BATTERY_READABLE_MAX
        )
        page: dict[str, Any] = {
            "daily": battery_calendar(record),
            "now": level,
            "threshold": self.low_threshold,
            # The level a cell is judged falling at or under (rule BAT-10).
            "ceiling": self.battery_ceiling,  # type: ignore[attr-defined]
            # Under four weeks of readings in the last six: not judged,
            # and the page says nothing about it (rule BAT-10).
            "short": battery_heard_days(series) < BATTERY_FIT_MIN_DAYS,
            "readable": readable,
            # A coarse cell is judged by the low threshold alone and
            # never read as steady or falling (rule BAT-10).
            "coarse": self.battery_steps(record) == BATTERY_STEPS_COARSE,
            # Earlier Forecasts, newest first, each with what happened
            # (rule BAT-15).
            "forecasts": self.battery_forecast_view(record),  # type: ignore[attr-defined]
            # A lithium cell holds near full until its end, and the
            # others of its model fall at this pace (rule BAT-16).
            "lithium": self.battery_lithium(device_id) if device_id else None,  # type: ignore[attr-defined]
            "model_pace": self.battery_model_paces().get(device_id) if device_id else None,
            # The newest day's voltage, messages and temperature, kept
            # for a later forecast (rule BAT-16).
            "evidence": self.battery_evidence_view(record),  # type: ignore[attr-defined]
        }
        if not isinstance(level, (int, float)) or not readable or not series:
            return page
        current = float(level)
        # The same trend the rows and the rules read: weekly averages,
        # and the fitted line when the cell falls.
        trend = battery_trend(
            series, current, self.battery_steps(record) == BATTERY_STEPS_SMOOTH,
            self.battery_ceiling,  # type: ignore[attr-defined]
        )
        # A coarse cell is never read as falling (rule BAT-10).
        falling = bool(trend["reading"] and trend["pace"]) and not page["coarse"]
        target = self.battery_target(current, record)  # type: ignore[attr-defined]
        days = (current - target) / (trend["pace"] / BATTERY_WEEK_DAYS) if falling else None
        # The range a falling cell reaches the low threshold in; the
        # near end decides Days Till Low, as on the Problem List (rule
        # BAT-13).
        projection = battery_projection(series, current, target) if falling else None
        far = days
        if projection is not None:
            days, far = projection["near"], projection["far"]
        page.update({
            "weeks": trend["weeks"],
            "reading": trend["reading"],
            # The straight line, for a falling cell only: an accelerating
            # one has none, its curve is the time left's (rule BAT-12).
            "fit": trend["fit"] if falling else None,
            "sentence": battery_sentence(trend, projection),
            "falling": falling,
            "left": self.battery_time_left_range(days, far) if days is not None else None,
            "left_soon": days is not None and days <= self._battery_days(),
            # Where the time left ends: the low threshold, or 0 (rule BAT-13).
            "target": target if falling else None,
            # What the chart with its future draws (rule BAT-17).
            "projection": projection,
            "days_setting": self._battery_days(),
        })
        return page

    def _signal_on_days(self, record: dict[str, Any], values: list[Any]) -> list[Any]:
        """A signal list laid out one slot a day, ending yesterday."""
        end = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
        return on_calendar(record, FAMILY_SIGNAL, values, end)

    def _node_status_view(self, device_id: str) -> str | None:
        """The device's node status as its page shows it (rule STACK-05)."""
        entity_id = self._node_status_entity.get(device_id)
        if entity_id is None:
            return None
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None and entry.disabled_by is not None:
            return "off"
        state = self.hass.states.get(entity_id)
        return state.state if state is not None else "unknown"

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
            "p5": self._signal_on_days(record, p5),
            "p50": self._signal_on_days(record, list(record.get(DEV_SIGNAL_DAILY_P50) or [])),
            "railed_days": self._signal_on_days(record, list(record.get(DEV_SIGNAL_DAILY_RAIL) or [])),
            "scale": record.get(DEV_SIGNAL_SCALE),
            "now": record.get(DEV_SIGNAL_VALUE),
            "judged": self._signal_on_days(
                record, [self.signal_day_judgment(record, index) for index in range(len(p5))]
            ),
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
        """Return a day's start, its end, and whether it is today.

        A finished day ends at the next local midnight rather than 24
        hours after it began, because the day the clocks go back runs
        25 hours and the day they go forward runs 23. The end belongs to
        the next day, so an event at the stroke of midnight is told once.
        """
        start = dt_util.as_utc(dt_util.start_of_local_day(day)).timestamp()
        now = dt_util.utcnow().timestamp()
        today = day == dt_util.now().date()
        end = (
            now
            if today
            else dt_util.as_utc(
                dt_util.start_of_local_day(day + timedelta(days=1))
            ).timestamp()
        )
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
            if self._brief_muted(device_id, kind):  # type: ignore[attr-defined]
                # The kinds its mutes cover, as the written brief (rule BRIEF-08).
                continue
            rows.append({
                "device_id": device_id,
                # The name it has today, as every surface (rule DEV-02);
                # the stored one only for a device no longer known.
                "name": (
                    self._device_names.get(device_id)
                    or row.get(INC_NAME)
                    or self._device_name(device_id)
                ),
                # The words the brief used when it opened: a past day
                # has no record of the level it read that night.
                "problem": self._brief_phrase(row),
                # From when it went, as the events beside it.
                "since": _iso(self._began_at(row)),  # type: ignore[attr-defined]
                "seconds": moment - self._began_at(row),  # type: ignore[attr-defined]
                "acknowledged": False,
                "uid": None,
            })
        rows.sort(key=lambda r: r["seconds"], reverse=True)
        return rows

    def _standing_now(self) -> list[dict[str, Any]]:
        """Today's standing problems, from the list itself, acknowledged
        ones included: the tab can tick them, which the written brief
        cannot, since the file leaves them out (rule NOTE-08)."""
        now = dt_util.utcnow().timestamp()
        rows = []
        for item in self.todo_items:
            device_id = item.get(TODO_DEVICE_ID)
            if not device_id or device_id in self._muted_devices:
                continue
            name = item.get(TODO_SORT_NAME) or ""
            kinds = item[TODO_KINDS]
            since = min((v for v in kinds.values() if isinstance(v, (int, float))), default=None)
            rows.append({
                "device_id": device_id,
                "name": name,
                "problem": self._problem_text(item),
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
        # The written brief's fold, so the tab never calls an
        # escalation a recovery the file does not.
        incidents = [
            row
            for row in withdrawals_once(fold(self.incident_rows()))
            if start <= row[INC_WHEN] < end
            and self._brief_keeps(row)  # type: ignore[attr-defined]
            and row[INC_DEVICE_ID] not in silenced
        ]
        system = [
            row
            for row in self.data.get(DATA_SYSTEM_EVENTS) or []
            if isinstance(row, dict)
            and isinstance(row.get(SYS_WHEN), (int, float))
            and start <= row[SYS_WHEN] < end
        ]
        events = [
            {
                # An unavailable opening at when the device went, as
                # the written brief has it.
                "when": _iso(self._began_at(row)),  # type: ignore[attr-defined]
                "who": self._told_name(row),
                "device_id": row.get(INC_DEVICE_ID),
                "what": self._brief_phrase(row),
            }
            for row in incidents
        ] + [
            {
                "when": _iso(row[SYS_WHEN]),
                "who": self._system_event_who(row),
                "device_id": self._system_event_device(row),
                "what": self._system_event_phrase(row),
            }
            for row in system
        ]
        events.sort(key=lambda row: row["when"] or "", reverse=True)
        # Repeat offenders look back seven days from the day shown, so
        # they can be told only while those days are still on record.
        held_from = dt_util.utcnow().timestamp() - INCIDENT_KEEP_DAYS * 86400.0
        covered = end - REPEAT_WINDOW_DAYS * 86400.0 >= held_from
        repeat: dict[str, Any] = {
            "available": covered,
            "rows": [],
            "paragraph": "",
            "words": "",
        }
        if covered:
            # The rows the brief's section is built from, so the tab
            # and the file say the same thing about the same devices.
            # The tab draws the table itself from the rows, because
            # printing the section's Markdown gave a paragraph of pipes.
            rows = self._repeat_offender_rows(end)
            repeat["rows"] = [
                {
                    "device_id": row.get("device_id"),
                    "name": row["name"],
                    "what": row["what"],
                    "times": row["n"],
                    "when": row["when"],
                    "typical": row["typical"],
                    "with": row["with"],
                }
                for row in rows
            ]
            if rows:
                repeat["paragraph"] = REPEAT_PARAGRAPH
            else:
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
            if len(series) < BATTERY_WEEK_DAYS:
                continue
            cells.append((device_id, record, series))
        return cells

    def battery_model_paces(self) -> dict[str, dict[str, Any]]:
        """For each cell, how fast the others of its model fall (rule BAT-16).

        Others means the cells of the same maker and model, the grouping
        By Model uses, the cell itself left out. A cell with no weekly
        fall yet (under four weeks of history, risen or flat) is left out rather than
        counted as losing nothing, which pulled the pace toward zero.
        The pace is a range, the slowest and the fastest of the others'
        falls over the last four weeks, points a week. Shown beside a
        battery as context and never used as its time left: a battery
        given its sisters' pace missed its own by about as much as the
        pace itself, since a door opened forty times a day and one
        opened twice share a model, not a drain. At least two others
        with a fall, or nothing is said.
        """
        registry = dr.async_get(self.hass)
        groups: dict[tuple[str, str], list[tuple[str, float | None]]] = {}
        for device_id, _record, series in self._battery_cells():
            device = registry.async_get(device_id)
            key = (
                device_field(device, "manufacturer") or "not reported",
                device_field(device, "model") or "not reported",
            )
            drop = battery_month_drop(series)
            groups.setdefault(key, []).append(
                (device_id, drop / 3 if drop is not None else None)
            )
        paces: dict[str, dict[str, Any]] = {}
        for (maker, model), cells in groups.items():
            for device_id, _own in cells:
                others = [
                    fall for other, fall in cells
                    # A cell that rose (a new cell, a recharge) or held
                    # flat (a cell that reads 100 for weeks) has no fall
                    # to give.
                    if other != device_id and fall is not None and fall > 0
                ]
                if len(others) < BATTERY_MODEL_PACE_MIN_OTHERS:
                    continue
                paces[device_id] = {
                    "model": f"{maker} {model}",
                    "others": len(others),
                    "pace_low": round(min(others), 2),
                    "pace_high": round(max(others), 2),
                }
        return paces

    def battery_trends(self) -> dict[str, Any]:
        """The battery fleet: the bank, every model, and the report's groups."""
        registry = dr.async_get(self.hass)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        bank = [0] * 10
        # Each device's type, read once: the tab narrows to one
        # type, and By Model lists the types a model's cells have.
        types: dict[str, str | None] = {}

        def type_of(device_id: str | None) -> str | None:
            if not device_id:
                return None
            if device_id not in types:
                types[device_id] = self.type_words(device_id)  # type: ignore[attr-defined]
            return types[device_id]

        cell_rows: list[dict[str, Any]] = []
        for device_id, record, series in self._battery_cells():
            level = float(record[DEV_BATTERY_VALUE])
            bank[min(9, int(level // 10))] += 1
            device = registry.async_get(device_id)
            key = (
                device_field(device, "manufacturer") or "not reported",
                device_field(device, "model") or "not reported",
            )
            cell = {
                "device_id": device_id,
                "name": self._device_name(device_id),
                "level": level,
                # Points a week over the last four weeks, negative for a
                # fall, as the models table has always sorted: the
                # hungriest model first.
                "rate": -(battery_month_drop(series) or 0.0) / 3,
                "type": type_of(device_id),
            }
            groups.setdefault(key, []).append(cell)
            cell_rows.append({**cell, "maker": key[0], "model": key[1]})
        models = []
        for (maker, model), cells in groups.items():
            lowest = min(cells, key=lambda cell: cell["level"])
            kinds: dict[str, int] = {}
            for cell in cells:
                kinds[cell["type"] or ""] = kinds.get(cell["type"] or "", 0) + 1
            models.append({
                "maker": maker,
                "model": model,
                "cells": len(cells),
                "rate": _middle([cell["rate"] for cell in cells]),
                "typical": _middle([cell["level"] for cell in cells]),
                "lowest": lowest["level"],
                "lowest_name": lowest["name"],
                "lowest_id": lowest["device_id"],
                # Each type its cells have and how many, most first;
                # "" for cells with no type.
                "types": sorted(kinds.items(), key=lambda item: (-item[1], item[0])),
            })
        models.sort(key=lambda row: (row["rate"], -row["cells"]))
        report = self._battery_rows()
        paces = self.battery_model_paces()

        def listed(rows: list[dict[str, Any]], falling: bool = False) -> list[dict[str, Any]]:
            out = []
            for row in rows:
                device_id = row.get("device_id")
                cell, lithium = (
                    self.battery_cell(device_id) if isinstance(device_id, str) else (None, None)  # type: ignore[attr-defined]
                )
                item = {
                    "device_id": row.get("device_id"),
                    "name": row.get("name"),
                    "type": type_of(row.get("device_id")),
                    "level": row.get("level"),
                    "since": row.get("since"),
                    "steps": BATTERY_STEPS_WORDS.get(str(row.get("steps") or ""), ""),
                    # The battery it takes, as its Power row says it, or
                    # None when nobody has said; a lithium cell holds
                    # near full until its end (rule BAT-16).
                    "cell": cell,
                    "lithium": lithium,
                    # The others of its model, as context (rule BAT-16).
                    "model_pace": paces.get(row["device_id"]) if isinstance(row.get("device_id"), str) else None,
                }
                if falling:
                    item.update({
                        "weeks": row.get("weeks") or [],
                        "reading": row.get("reading"),
                        "pace": -row["slope"] * BATTERY_WEEK_DAYS,
                        "left": self.battery_time_left_range(row["days"], row.get("days_far")),
                        "until": self.battery_until_words(row),
                        "left_soon": row["days"] <= self._battery_days(),
                        # Falling at a steady pace inside Days Till Low:
                        # Batteries to Watch, with no warning (rule BAT-14).
                        "watch": row["days"] <= self._battery_days() and not row.get("low")
                        and row.get("reading") != READING_ACCELERATING,
                    })
                else:
                    item["days"] = len(row.get("series") or [])
                    # Points lost over the last four weeks, from the
                    # first week's average to the last's, in place of a
                    # rate per day that described a wobble.
                    item["month_drop"] = battery_month_drop(row.get("series") or [])
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
                {"device_id": row.get("device_id"), "name": row.get("name"), "level": row.get("level"),
                 "type": type_of(row.get("device_id"))}
                for row in report["unreadable"]
            ],
            "no_battery": len(report["absent"]),
            # The same, by type, for the tab narrowed to one.
            "no_battery_types": _count_types(type_of(row.get("device_id")) for row in report["absent"]),
            "cell_rows": cell_rows,
            "threshold": self.low_threshold,
            # The level a cell is judged falling at or under (rule BAT-10).
            "ceiling": self.battery_ceiling,  # type: ignore[attr-defined]
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
            # Each bad day on its own date: a day with no reading writes
            # no row, so counting back from today would put every bad
            # day before it on the wrong date.
            dated = dates_for(record, FAMILY_SIGNAL, len(judged), today - timedelta(days=1))
            for index, day in enumerate(judged):
                if not day or not day["bad"]:
                    continue
                when = dated[index]
                back = (today - when).days - 1
                bad_by_day[when.isoformat()] = bad_by_day.get(when.isoformat(), 0) + 1
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
                # Its normal is the judgment's baseline, the one the
                # bad-day line beside it is built from, so the device
                # page and this tab print the same number. The change
                # below is measured against the middle of the days
                # before this week, which leaves this week out and is a
                # different question; the tab names it Before This Week
                # (rule SIG-12).
                "normal": last["normal"] if last else normal,
                "line": last["line"] if last else None,
                # The two middles the change is taken between, so the
                # row adds up: the last seven days' and the days before
                # them.
                "week": now,
                "usual": normal,
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
            # The devices in a flap, beside their signal, because a
            # link that keeps dropping is where a person looking at
            # network health looks first.
            "dropping_out": [
                {
                    "device_id": row["device_id"],
                    "name": row["name"],
                    "drops": row["drops"],
                    "since": _iso(row["since"]),
                    "signal": next(
                        (
                            device.get("now")
                            for device in devices
                            if device.get("device_id") == row["device_id"]
                        ),
                        None,
                    ),
                }
                for row in self.flapping_list
            ],
        }
