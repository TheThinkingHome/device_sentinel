# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: hubs.py, Version: 0.26.3 (2026-10-14)

"""Judged by its hub (rulings #663 to #665).

Some integrations put their devices behind a hub that reports nothing
about any one of them. Lutron Caseta is the first: a light, switch,
Pico remote or occupancy group tells Home Assistant nothing of when it
last spoke, its battery or its losing power, and a light reports only
when someone uses it. What Lutron does report is whether its hub is
connected. So the hub is judged, up or down, and the devices it
controls are judged by it: never frozen, never "never reported", and
listed on the hub's page, not on the Problem List, while it is down.

Which device is a hub and which devices it controls is Home
Assistant's own answer: each device is registered "via" its hub. A
device of a hub-judged integration registered via another device of
the same integration and config entry is controlled by that device,
and that device is a hub. Nothing here names Lutron except the one
reader in HUB_READERS, so Hue and SmartThings can join with a reader
of their own (James, 14 October 2026).

The Lutron reader is the one private field #663 rules in under #639:
the library's session handle. pylutron-caseta checks its hub once a
minute itself and clears the handle when the hub stops answering, then
keeps it clear while it retries; `is_connected()` is no help, since it
stays True through an outage (Christopher Robert's five outages, 20
September 2026, and the library's own code, 0.29.0). Nothing is
imported, nothing is sent to the hub, and any failure to read it is no
opinion: the hub is then judged as any other device, never down.

A hub reads down once its session has been gone for two readings of
the minute check (HUB_DOWN_CONFIRM_SECONDS), which rides past the
library's own reconnect of a few seconds. Its entity changes only at a
restart, so its silence is not judged either. A hub whose integration
failed to start is the integration outage rule's (#445), as before.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_PRIORITY,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    HUB_DOWN_CONFIRM_SECONDS,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    LOGGER,
    TODO_DEVICE_ID,
    TODO_SUMMARY,
)
from .device_fields import device_field
from .records import BAD_STATES

LUTRON = "lutron_caseta"

# A hub's integration that Home Assistant says failed to start.
_FAILED_SETUP = frozenset({ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR})


def _lutron_connected(entry: Any) -> bool:
    """Whether a Lutron hub's session is up (#663).

    The bridge keeps its session in `_leap`, set on a connection and
    cleared when the connection drops. A bridge without the attribute
    at all is a changed library, which raises and reads as no opinion.
    """
    bridge = entry.runtime_data.bridge
    if not hasattr(bridge, "_leap"):
        raise AttributeError("the Lutron bridge has no session field")
    return bridge._leap is not None  # noqa: SLF001 - ruled under #639 and #663


# The one line per hub-judged integration: its domain and how to read
# whether one of its hubs is up. Hue and SmartThings join here (0.26.4).
HUB_READERS: dict[str, Any] = {LUTRON: _lutron_connected}

# The bus events that say a device controlled by a hub was used, where
# the device has no entity that would say so (#664): a Lutron Pico's
# buttons are disabled by default and only command it from Home
# Assistant, so a press reaches Home Assistant only as this event,
# carrying the device's registry id.
HUB_BUTTON_EVENTS = ("lutron_caseta_button_event",)
HUB_BUTTON_PRESS = "press"

# The word a device of each integration's own model names uses on its
# page ("this light"), from Lutron's device types in the model text.
_LUTRON_KINDS = (
    ("Pico", "remote"),
    ("Keypad", "keypad"),
    ("Occupancy", "sensor"),
    ("Switch", "switch"),
    ("Fan", "fan control"),
    ("Shade", "shade"),
    ("Dimmer", "light"),
    ("Plug", "plug"),
)


def device_kind(model: str | None) -> str:
    """The word a device's page uses for it: light, switch, remote."""
    text = model or ""
    for marker, word in _LUTRON_KINDS:
        if marker.lower() in text.lower():
            return word
    return "device"


class HubMixin:
    """Which devices are hubs, which they control, and whether each is up."""

    _hub_of: dict[str, str]
    _hub_entry: dict[str, str]
    _hub_lost: dict[str, float]
    _hub_unreadable: set[str]

    def _init_hubs(self) -> None:
        self._hub_of = {}
        self._hub_entry = {}
        self._hub_lost = {}
        self._hub_unreadable = set()

    def _rebuild_hubs(self, all_devices: Any) -> None:
        """Map each controlled device to its hub, from the registry walk.

        A watched device of a hub-judged integration, registered via a
        device of the same integration in the same config entry, is
        controlled by it. Done on the rebuild that already walks the
        registry, so it costs one pass over devices already in hand.
        """
        watched = self._watched  # type: ignore[attr-defined]
        entry_of = self._entry_of_device  # type: ignore[attr-defined]
        hub_of: dict[str, str] = {}
        hub_entry: dict[str, str] = {}
        by_id = {getattr(d, "id", None): d for d in all_devices}
        for device in all_devices:
            device_id = getattr(device, "id", None)
            if not isinstance(device_id, str):
                continue
            domain = watched.get(device_id)
            if domain not in HUB_READERS:
                continue
            via = device_field(device, "via_device_id")
            entry_id = entry_of.get(device_id)
            if not isinstance(via, str) or not via or via == device_id or entry_id is None:
                # A device registered via itself, as Home Assistant
                # 2026.5's Lutron integration registers its hub, is not
                # its own hub: mapped, its mute asked itself for ever.
                continue
            # The hub need not be watched itself: a hub with no entity,
            # or one set aside, still speaks for the devices it controls.
            parent = by_id.get(via)
            if parent is None or entry_id not in self._owner_candidates(parent):  # type: ignore[attr-defined]
                continue
            hub_of[device_id] = via
            hub_entry[via] = entry_id
        # A hub is never one of the devices a hub controls, so nothing
        # here can lead back to itself.
        self._hub_of = {d: hub for d, hub in hub_of.items() if d not in hub_entry}
        self._hub_entry = hub_entry
        for hub in list(self._hub_lost):
            if hub not in hub_entry:
                self._hub_lost.pop(hub, None)

    @callback
    def _hub_button_filter(self, event_data: Any) -> bool:
        """Fast pre-filter: a press on a watched device a hub controls."""
        try:
            return (
                event_data.get("action") == HUB_BUTTON_PRESS
                and event_data.get("device_id") in self._hub_of
            )
        except AttributeError:
            return False

    @callback
    def _on_hub_button(self, event: Any) -> None:
        """A press counts as the device reporting (#664)."""
        device_id = event.data.get("device_id")
        if device_id not in self._watched:  # type: ignore[attr-defined]
            return
        self._record_activity(  # type: ignore[attr-defined]
            device_id, self._entry_of_device.get(device_id)  # type: ignore[attr-defined]
        )

    def judged_by_hub(self, device_id: str) -> bool:
        """Whether a device is a hub or controlled by one (#664)."""
        return device_id in self._hub_of or device_id in self._hub_entry

    def hub_takes_over(self, device_id: str) -> bool:
        """Whether a watched hub speaks for this device's outages (#664).

        A hub that is not watched (no entity of its own, or excluded)
        gets no verdict, so the integration outage rule keeps covering
        its entry, as in 0.26.2. A muted hub still speaks, silently.
        """
        if device_id in self._hub_entry:
            return self._hub_judged(device_id)
        hub = self._hub_of.get(device_id)
        return hub is not None and self._hub_judged(hub)

    def _hub_judged(self, hub_id: str) -> bool:
        """Whether a hub is watched, so it speaks for its devices.

        Muted or not: a hub's mute covers the devices it controls
        (James, 14 October 2026), so muting it silences them all and
        hands nothing to anyone. Until then a muted hub's devices went
        to their own entities and the integration outage rule, and a
        mute changed mid-outage moved verdicts, rows and an announced
        outage from one to the other, which took three review rounds
        and was never whole.
        """
        return hub_id in self._watched  # type: ignore[attr-defined]

    def hub_mutes(self, device_id: str, is_muted: Any) -> bool:
        """Whether the hub controlling a device is muted by `is_muted`.

        One family's mute check, asked of the hub: a hub's mute covers
        the devices it controls, mute by mute (James, 14 October 2026).
        """
        hub = self.watched_hub_of(device_id)
        return hub is not None and bool(is_muted(hub))

    def watched_hub_of(self, device_id: str) -> str | None:
        """The watched hub that speaks for a device, or None.

        A hub that is not watched (excluded, disabled, or with no
        entity) speaks for nothing, so its mute covers nothing either
        (seventh review round, 14 October 2026).
        """
        hub = getattr(self, "_hub_of", {}).get(device_id)
        if hub is None or hub not in getattr(self, "_watched", {}):
            return None
        return hub

    def hub_of(self, device_id: str) -> str | None:
        """The hub that controls this device, if one does."""
        return self._hub_of.get(device_id)

    def is_hub(self, device_id: str) -> bool:
        """Whether this device is a hub other devices are controlled by."""
        return device_id in self._hub_entry

    def hub_unavailable_words(self, device_id: str | None) -> tuple[str, str] | None:
        """A hub's words for unavailable: "went down" and "down".

        The card and the Daily Brief say of a hub what the Problem List
        says (James, 14 October 2026). None for any other device.
        """
        if device_id is None or not self.is_hub(device_id):
            return None
        return "went down", "down"

    def hub_members(self, hub_id: str) -> list[str]:
        """The watched devices a hub controls, by name."""
        members = [d for d, hub in self._hub_of.items() if hub == hub_id]
        return sorted(members, key=lambda d: self._device_name(d).lower())  # type: ignore[attr-defined]

    def _hub_connected(self, hub_id: str) -> bool | None:
        """Whether a hub's connection is up, or None for no opinion.

        No opinion when its entry is not loaded (that is the integration
        outage rule's, #445), when the integration has no reader, and
        when the reader cannot read: the first failure per entry is
        logged once at info, as #639 asks.
        """
        entry_id = self._hub_entry.get(hub_id)
        if entry_id is None:
            return None
        entry = self.hass.config_entries.async_get_entry(entry_id)  # type: ignore[attr-defined]
        if entry is None:
            return None
        if entry.state in _FAILED_SETUP:
            # Its integration could not start, as after a restart taken
            # with the hub unplugged: the hub is not connected (#664).
            return False
        if entry.state is not ConfigEntryState.LOADED:
            return None
        reader = HUB_READERS.get(entry.domain)
        if reader is None:
            return None
        try:
            connected = reader(entry)
            if not isinstance(connected, bool):
                raise TypeError(type(connected).__name__)
            return connected
        except Exception as err:  # noqa: BLE001 - a moved field is no opinion
            if entry_id not in self._hub_unreadable:
                self._hub_unreadable.add(entry_id)
                LOGGER.info(
                    "device_sentinel: could not read whether the %s hub "
                    "%s is connected (%s); it is judged as any other device",
                    entry.domain,
                    entry.title,
                    err,
                )
            return None

    def _sample_hubs(self, now: float) -> None:
        """Note when each hub's connection was first seen gone. Each minute."""
        for hub_id in list(self._hub_entry):
            connected = self._hub_connected(hub_id)
            if connected is False:
                self._hub_lost.setdefault(hub_id, now)
            elif connected is True:
                self._hub_lost.pop(hub_id, None)
            # No opinion keeps what was known: an entry between retries,
            # reloading, or a reading that failed says nothing of the hub.

    def hub_down_since(self, hub_id: str, now: float | None = None) -> float | None:
        """When a hub went down, once it has read down for the confirm time."""
        first = self._hub_lost.get(hub_id)
        if first is None:
            return None
        if now is None:
            now = dt_util.utcnow().timestamp()
        if now - first < HUB_DOWN_CONFIRM_SECONDS:
            return None
        return first

    def _hub_category(self, device_id: str, record: dict[str, Any], now: float) -> str | None:
        """The verdict for a hub or a device it controls (#664).

        Never frozen and never "never reported": these devices report
        only when used or at a restart. A hub whose connection is down
        is unavailable. Otherwise a device is down only when every
        entity it has reads down, which happens at a restart with its
        hub away. A frozen verdict standing from before 0.26.3 stays
        until the device reports, as #529 keeps one through a rule
        change.
        """
        current = record.get(DEV_FROZEN_CATEGORY)
        if self.is_hub(device_id):
            if self.hub_down_since(device_id, now) is not None:
                return FREEZE_CATEGORY_UNAVAILABLE
            if device_id in self._hub_lost:
                # Going, not yet confirmed: nothing changes yet.
                return current
            if self._hub_connected(device_id) is True:
                # Its connection is the truth for a hub: up is up, and a
                # frozen verdict from 0.26.2 has nothing behind it.
                return None
        hub = self._hub_of.get(device_id)
        if hub is not None and hub in self._hub_lost and self.hub_takes_over(device_id):
            # Its hub is down, or going: what its own entities read says
            # nothing of the device, which waits for its hub with its
            # verdict as it stood.
            return current
        states = self._live_entity_states(device_id)  # type: ignore[attr-defined]
        if states and all(s in BAD_STATES for s in states):
            present = {
                FREEZE_CATEGORY_UNAVAILABLE: STATE_UNAVAILABLE in states,
                FREEZE_CATEGORY_UNKNOWN: STATE_UNKNOWN in states,
            }
            for category in FREEZE_CATEGORY_PRIORITY:
                if present.get(category):
                    return category
            return FREEZE_CATEGORY_UNAVAILABLE
        if current == FREEZE_CATEGORY_FROZEN and not self.is_hub(device_id):
            return FREEZE_CATEGORY_FROZEN
        return None

    def hub_view(self, device_id: str, now: float) -> dict[str, Any] | None:
        """What a controlled device's page says about its hub."""
        hub_id = self._hub_of.get(device_id)
        if hub_id is None or not self._hub_judged(hub_id):
            # A hub that cannot speak has no page of its own to send
            # anyone to: the device's page is an ordinary one.
            return None
        down = self.hub_down_since(hub_id, now) is not None
        # Going but not yet confirmed still reads as it stood: up.
        known = down or hub_id in self._hub_lost or self._hub_connected(hub_id) is True
        return {
            "name": self._device_name(hub_id),  # type: ignore[attr-defined]
            "device_id": hub_id,
            # None when the hub's connection cannot be read just now.
            "up": None if not known else not down,
            "since": self._hub_since_iso(hub_id, now),
            "kind": device_kind(self._model_text(device_id)),
            # A shade the hub reports a battery for (Home Assistant
            # 2026.10): the page leaves "not its battery" out.
            "battery": device_id in getattr(self, "_battery_entity", {}),
        }

    def hub_self_view(self, device_id: str, now: float) -> dict[str, Any] | None:
        """What a hub's page says: its state and the devices it controls."""
        if not self.is_hub(device_id) or not self._hub_judged(device_id):
            # A hub that is not watched is shown as any other device,
            # as the devices it controls are (hub_view).
            return None
        down = self.hub_down_since(device_id, now) is not None
        if not down and device_id not in self._hub_lost and self._hub_connected(device_id) is not True:
            # Its connection cannot be read: the hub is shown as any
            # other device, with no claim about it.
            return None
        problems = {
            item.get(TODO_DEVICE_ID): item
            for item in getattr(self, "todo_items", []) or []
            if isinstance(item, dict)
        }
        behind = []
        for member in self.hub_members(device_id):
            record = (self.data or {}).get(DATA_DEVICES, {}).get(member) or {}  # type: ignore[attr-defined]
            item = problems.get(member)
            name = self._device_name(member)  # type: ignore[attr-defined]
            problem = ""
            if item:
                summary = item.get(TODO_SUMMARY) or ""
                problem = summary[len(name) + 2:] if summary.startswith(f"{name}: ") else summary
            behind.append({
                "device_id": member,
                "name": name,
                "type": self.type_words(member) or device_kind(self._model_text(member)).capitalize(),  # type: ignore[attr-defined]
                "standing": (
                    # Muted by its hub alone, it says so in those words
                    # (James, 14 October 2026).
                    "Muted with its hub" if (muted := self.mute_text(member))  # type: ignore[attr-defined]
                    and all("with its hub" in part for part in muted.split("; "))
                    else f"Watched, muted: {muted}" if muted
                    else "Watched, waiting for its hub" if down
                    else "Watched"
                ),
                "last_seen": _iso(record.get(DEV_LAST_ACTIVITY)),
                "problem": problem,
            })
        return {
            "up": not down,
            "since": self._hub_since_iso(device_id, now),
            "behind": behind,
            "outages": self.hub_outages(device_id),
        }

    def hub_outages(self, hub_id: str) -> list[dict[str, Any]]:
        """The hub's own outages in the last 14 days, newest first.

        Read from the hub's own unavailable incidents, which the
        problem list already writes when it goes down and comes back:
        nothing new is stored.
        """
        now = dt_util.utcnow().timestamp()
        since = now - 14 * 86400
        opened: list[float] = []
        rows: list[dict[str, Any]] = []
        for row in (self.data or {}).get(DATA_INCIDENTS) or []:  # type: ignore[attr-defined]
            if not isinstance(row, dict) or row.get(INC_DEVICE_ID) != hub_id:
                continue
            if row.get(INC_KIND) != FREEZE_CATEGORY_UNAVAILABLE:
                continue
            when = row.get(INC_WHEN)
            if not isinstance(when, (int, float)) or isinstance(when, bool):
                continue
            if row.get(INC_EVENT) == INCIDENT_OPENED:
                opened.append(float(when))
            elif row.get(INC_EVENT) == INCIDENT_RESOLVED:
                duration = row.get(INC_DURATION)
                start = (
                    float(when) - float(duration)
                    if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                    else (opened.pop() if opened else None)
                )
                if opened and start is not None:
                    opened = [o for o in opened if o > start + 1]
                if start is not None and start >= since:
                    rows.append({"start": _iso(start), "end": _iso(float(when))})
        for start in opened:
            if start >= since:
                rows.append({"start": _iso(start), "end": None})
        rows.sort(key=lambda row: row["start"] or "", reverse=True)
        return rows

    def _hub_since_iso(self, hub_id: str, now: float) -> str | None:
        """Down since, or connected since: the moment the hub's state began."""
        down = self.hub_down_since(hub_id, now)
        if down is not None:
            return _iso(down)
        for row in reversed((self.data or {}).get(DATA_INCIDENTS) or []):  # type: ignore[attr-defined]
            if (
                isinstance(row, dict)
                and row.get(INC_DEVICE_ID) == hub_id
                and row.get(INC_KIND) == FREEZE_CATEGORY_UNAVAILABLE
                and row.get(INC_EVENT) == INCIDENT_RESOLVED
                and isinstance(row.get(INC_WHEN), (int, float))
            ):
                return _iso(float(row[INC_WHEN]))
        started = getattr(self, "_started_at", None)
        return _iso(float(started)) if isinstance(started, (int, float)) else None

    def _model_text(self, device_id: str) -> str:
        device = dr.async_get(self.hass).async_get(device_id)  # type: ignore[attr-defined]
        return str(device_field(device, "model") or "") if device is not None else ""

    def hub_problem_words(self, device_id: str | None) -> str | None:
        """The Problem List's words for a hub that is down (#665)."""
        if device_id is None or not self.is_hub(device_id) or self.hub_down_since(device_id) is None:
            return None
        count = len(self.hub_members(device_id))
        noun = "device" if count == 1 else "devices"
        return f"Hub down, {count} {noun} that it controls"

    def hub_problem_line(self, device_id: str, when: str | None) -> str | None:
        """The tap-open line for a hub that is down (#665)."""
        if not self.is_hub(device_id) or self.hub_down_since(device_id) is None:
            return None
        count = len(self.hub_members(device_id))
        devices = "The device it controls is" if count == 1 else f"The {count} devices it controls are"
        start = f"Down since {when}." if when else "Down."
        return f"{start} {devices} listed on its page, not on the Problem List, until it is back."

    def hub_diagnostics(self) -> dict[str, Any]:
        """Each hub's state, for the diagnostics download."""
        now = dt_util.utcnow().timestamp()
        return {
            hub: {
                "entry": self._hub_entry[hub],
                "connected": self._hub_connected(hub),
                "down_since": self.hub_down_since(hub, now),
                "controls": len(self.hub_members(hub)),
            }
            for hub in sorted(self._hub_entry)
        }


def _iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return dt_util.utc_from_timestamp(float(value)).isoformat()
