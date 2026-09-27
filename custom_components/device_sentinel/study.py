# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study.py, Version: 0.23.11 (2026-09-27)

"""Gather what building support for somebody's hardware requires.

Support for a router, a stack or an integration stalls on the same
thing every time: nobody working on this owns one, and reading a
vendor's source produces support that looks right and fails on
contact with a real system. Ruling #393 answers that by asking the
person who does own one, through a toggle they choose, into a file
they attach themselves. Nothing is transmitted.

**A photograph is not enough**, and that is the lesson this file is
built around. The two faults that cost the most releases could not
have been seen in a snapshot:

1. A router's trackers going away during an outage, how many and how
   fast, which is the whole of what detection needs.
2. What a client publishes *while disconnected*. On the reference
   fleet a router relabelled seven wireless clients as wired the
   moment they left, the tie set fell from twelve to six, and it did
   not heal (#389).

So a study keeps two things: a snapshot of how the world looks now,
and the distinct shapes of every transition it has seen.

**Shapes rather than history.** Each transition is signed by the
integration, the states it moved between, and the exact set of
attribute keys present. The first of a signature is stored whole; the
rest are counted. Twelve trackers leaving in one outage collapse to
two or three shapes, a hundred outages add nothing, and the one odd
tracker that publishes something different is kept. A later
transition replaces a stored one only when it is richer, carrying
keys the stored one lacked or values where it held nulls.

**It ends when the person ends it.** Collection stops the moment a
toggle goes off, and what was collected is dropped at the next fold,
the same way everything else here ages out.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_STUDY_HARDWARE,
    LOGGER,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    LEARNING_MIN_DAYS,
    STATUS_LEARNING,
    DATA_STACK_PROBE,
    PROBE_AGREES,
    PROBE_SENTINEL,
    STATUS_NEVER_REPORTED,
    STATUS_REPORTING,
    STATUS_SET_ASIDE,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NODE,
    PROBE_NOW,
    PROBE_STACK,
    PROBE_WAS,
    PROBE_WHEN,
    STUDIABLE,
    STUDY_SHAPE_CAP,
)
from .device_fields import device_field
from .study_stacks import (
    HUE_DOMAIN,
    LUTRON_DOMAIN,
    MATTER_DOMAIN,
    SMARTTHINGS_DOMAIN,
    TUYA_DOMAIN,
    ZWAVE_DOMAIN,
    coordinator_rows,
    probe_rows,
    zwave_health,
    zwave_nodes,
)

# The probe's own word for Device Sentinel's stance where "reporting"
# would claim a verdict never reached (0.23.11): a muted device is not
# judged, and one still learning (STATUS_LEARNING) has no window.
PROBE_MUTED = "muted"

# What the Z-Wave library announces about a node as it happens, recorded
# with the moment (0.23.11). A device awake for seconds is asleep again
# by the next minute's reading, which is how an afternoon of waking
# devices on the second fleet left no trace.
ZWAVE_NODE_EVENTS = ("wake up", "sleep", "dead", "alive")

# Border routers seen by Home Assistant's own Thread discovery (0.23.11).
THREAD_STACK = "thread"

# Every stack the probe reads (0.23.9 added the last four).
PROBED_DOMAINS = {
    ZWAVE_DOMAIN, MATTER_DOMAIN, HUE_DOMAIN, SMARTTHINGS_DOMAIN, TUYA_DOMAIN, LUTRON_DOMAIN,
}

ROUTER = "router"
IGNORED_KEYS = {"friendly_name", "icon", "device_class"}


def studied_domains(options) -> set[str]:
    """The integration domains a person has volunteered.

    Stored as labels because that is what the picker shows, so they
    are mapped back here rather than storing something the person
    cannot read on the settings screen.
    """
    chosen = set(options.get(CONF_STUDY_HARDWARE) or [])
    return {
        domain for domain, label in STUDIABLE.items() if label in chosen
    }


def _values(attributes: Any) -> dict[str, Any]:
    """The fields that bear on how a device is reached.

    Recorded by value because these are the answer to the question a
    study exists for. Everything else about a tracker is recorded as
    a key name only: knowing that a field is published is what tells
    us whether a rule can be built on it.
    """
    if not isinstance(attributes, dict):
        return {}
    wanted = (
        "source_type", "connection", "connection_type", "essid", "ssid",
        "radio", "radio_proto", "band", "vlan", "is_wired", "channel",
        "signal", "tracking_type",
    )
    out = {key: attributes.get(key) for key in wanted if key in attributes}
    if "ap_mac" in attributes:
        # Presence only: it names an access point, and which one is
        # not a question any of this answers.
        out["ap_mac_present"] = bool(attributes.get("ap_mac"))
    return out


def _shape(integration: str, was: str | None, now: str,
           attributes: Any) -> str:
    """The signature of a transition.

    The attribute key set is in the signature on purpose: a client
    that publishes six keys while home and three while away is two
    shapes, and that difference is precisely what #389 was about.
    """
    keys = sorted(
        k for k in (attributes or {}) if k not in IGNORED_KEYS
    )
    return f"{integration}|{was}->{now}|{','.join(keys)}"


class StudyMixin:
    """Collect what a volunteered integration does, and only that."""

    # Set in the coordinator's __init__ (0.23.8); declared here so
    # the type is known where the probe reads it.
    _probe_wifi_down: bool | None
    _probe_pending: list[str]
    _probe_recent: deque[str]
    _probe_failed: set[str]
    # 0.23.11: node event subscriptions keyed by the node object's id,
    # each controller's counters at the last fold, and the border router
    # discovery with what each router last said.
    _zwave_listeners: dict[int, list[Callable[[], None]]]
    _zwave_counters: dict[str, dict[str, int]]
    _thread_discovery: Any
    _thread_starting: bool
    _thread_failed: bool
    _thread_routers: dict[str, tuple[str, str, str]]

    # ------------------------------------------------------- settings

    @property
    def studied(self) -> set[str]:
        return studied_domains(self.entry.options)

    def _study_router_entities(self) -> dict[str, str]:
        """Every router tracker belonging to a studied integration."""
        if not self.studied:
            return {}
        registry = er.async_get(self.hass)
        out: dict[str, str] = {}
        for entry in registry.entities.values():
            if entry.domain != "device_tracker" or entry.disabled_by:
                continue
            if entry.platform not in self.studied:
                continue
            out[entry.entity_id] = entry.platform
        return out

    def resubscribe_study(self) -> None:
        """Listen to every tracker of a studied integration.

        Its own subscription rather than riding on the tie listener,
        because a study wants the trackers no tie could claim just as
        much as the ones it could: an unclaimable tracker is often
        the thing being studied.
        """
        if self._study_unsub is not None:
            self._study_unsub()
            self._study_unsub = None
        watched = self._study_router_entities()
        self._study_watching = watched
        if not watched:
            return
        self._study_unsub = async_track_state_change_event(
            self.hass, sorted(watched), self._on_study_state
        )

    @callback
    def _on_study_state(self, event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        entity_id = event.data.get("entity_id")
        integration = self._study_watching.get(entity_id)
        if new_state is None or integration is None:
            return
        was = old_state.state if old_state else None
        if was == new_state.state:
            return
        self.study_transition(
            entity_id, integration, was, new_state.state,
            dict(new_state.attributes),
        )

    # ------------------------------------------------------ the shapes

    @callback
    def study_transition(self, entity_id: str, integration: str,
                         was: str | None, now: str, attributes: Any) -> None:
        """Record a transition, or count it if its shape is known."""
        shapes = self._study_shapes.setdefault(integration, {})
        key = _shape(integration, was, now, attributes)
        seen = dt_util.utcnow().isoformat()
        stored = shapes.get(key)

        if stored is None:
            if len(shapes) >= STUDY_SHAPE_CAP:
                if not self._study_capped.get(integration):
                    self._study_capped[integration] = True
                    LOGGER.info(
                        "device_sentinel: study of %s reached %d shapes, "
                        "no further kinds recorded",
                        integration,
                        STUDY_SHAPE_CAP,
                    )
                return
            shapes[key] = {
                "entity_id": entity_id,
                "from": was,
                "to": now,
                "keys": sorted(
                    k for k in (attributes or {}) if k not in IGNORED_KEYS
                ),
                "values": _values(attributes),
                "first_seen": seen,
                "last_seen": seen,
                "count": 1,
            }
            self._mark_cold_dirty()
            return

        stored["count"] += 1
        stored["last_seen"] = seen
        # A richer example of the same shape replaces a poorer one:
        # same keys, but values where the stored one held nulls.
        fresh = _values(attributes)
        filled = sum(1 for v in fresh.values() if v not in (None, ""))
        held = sum(
            1 for v in (stored.get("values") or {}).values()
            if v not in (None, "")
        )
        if filled > held:
            stored["values"] = fresh
            stored["entity_id"] = entity_id

    # ---------------------------------------------------- the snapshot

    def study_snapshot(self) -> dict[str, Any]:
        """How the world looks now, for the studied integrations.

        Every router tracker with what it currently publishes, and
        every watched device with the connections the registry holds
        for it. Together those answer whether a tie can be made and
        by which rung, which is the first thing support for a router
        needs.
        """
        if not self.studied:
            return {}
        devices = dr.async_get(self.hass)
        trackers = []
        for entity_id, integration in self._study_router_entities().items():
            state = self.hass.states.get(entity_id)
            trackers.append({
                "entity_id": entity_id,
                "integration": integration,
                "state": state.state if state else None,
                "keys": sorted(
                    k for k in (state.attributes if state else {})
                    if k not in IGNORED_KEYS
                ),
                "values": _values(state.attributes if state else None),
            })

        watched = []
        for device_id, integration in self._watched.items():
            device = devices.async_get(device_id)
            if device is None:
                continue
            watched.append({
                "name": device.name_by_user or device.name,
                # The integration Device Sentinel assigned, not the first
                # identifier's domain: a Bluetooth or address-linked
                # device carries no identifier, and the fourth fleet's
                # SwitchBot and ESPHome devices read empty.
                "integration": integration,
                "connections": sorted(
                    f"{kind}:{value}"
                    for kind, value in device_field(device, "connections", set())
                ),
                "identifiers": sorted(
                    str(ident) for _domain, ident in device.identifiers
                ),
            })
        return {"trackers": trackers, "watched_devices": watched}

    # ------------------------------------------- the probe, 0.22.26

    def _probe_views(self, row: dict[str, Any], now: float) -> dict[str, Any]:
        """The stack's view of a node beside Device Sentinel's (0.23.8).

        The readers in shadow: each is worked out and written down, and
        neither acts. A Z-Wave node counts as quiet when the stack says
        dead, or when it was last heard longer ago than the device's own
        freeze window, because a mains node stays "alive" until a
        command to it fails (research finding 4: Tim Plas's P03 read
        alive three days after it was last heard). A Matter node counts
        as quiet when it is away. Device Sentinel counts a device quiet
        when its page would read anything but reporting, set aside or
        never reported.
        """
        device_id = row.get("device_id") or ""
        record = (self.data.get(DATA_DEVICES) or {}).get(device_id) if device_id else None
        sentinel = self._page_status(device_id, record) if record is not None else ""  # type: ignore[attr-defined]
        # A muted device is not judged and one still learning has no
        # window, so "reporting" would claim a verdict never reached
        # (0.23.11). The second fleet's S81, dead to Z-Wave for a week
        # and a half and muted, read as a disagreement.
        if record is not None and sentinel == STATUS_REPORTING:
            if device_id in getattr(self, "_muted_devices", set()) or self._freeze_muted(device_id):  # type: ignore[attr-defined]
                sentinel = PROBE_MUTED
            elif len(record.get(DEV_DAILY_MAX) or []) < LEARNING_MIN_DAYS:
                sentinel = STATUS_LEARNING
        sentinel_quiet = (
            None
            if sentinel in ("", STATUS_SET_ASIDE, STATUS_NEVER_REPORTED, PROBE_MUTED, STATUS_LEARNING)
            else sentinel != STATUS_REPORTING
        )
        state = row["now"]
        stale = False
        detail = row.get("detail") or ""
        if row["stack"] == ZWAVE_DOMAIN:
            seen = row.get("seen")
            window = self._freeze_window(record) if record is not None else None  # type: ignore[attr-defined]
            if isinstance(seen, (int, float)):
                age = max(0.0, now - seen)
                detail = ", ".join(
                    part for part in (f"last heard {self._episode_duration(age)} ago", detail) if part  # type: ignore[attr-defined]
                )
                stale = window is not None and age > window
            stack_quiet = True if state == "dead" or stale else (
                None if state in ("unknown", "None") else False
            )
        else:
            # Matter, Hue and Tuya say quiet or not on the row; a
            # SmartThings row carries only the device's type (None).
            stack_quiet = row.get("quiet")
        agrees = (
            "" if stack_quiet is None or sentinel_quiet is None
            else "yes" if stack_quiet == sentinel_quiet else "no"
        )
        return {
            "now": f"{state}, not heard within its window" if stale else state,
            "sentinel": sentinel,
            "agrees": agrees,
            "detail": detail,
        }

    def _probe_failure(self, what: str, err: Exception) -> None:
        """Say once per start that a stack could not be read (0.23.10).

        The probe records and never judges, so a library that throws
        costs its own lines and nothing else. Logged as a warning the
        first time each stack fails with each kind of error, and at
        debug after, since the tick would otherwise repeat it every
        minute.
        """
        name = STUDIABLE.get(what, what)
        key = f"{what}:{type(err).__name__}"
        if key in self._probe_failed:
            LOGGER.debug("device_sentinel: Extended Diagnostics, %s: %s", name, err)
            return
        self._probe_failed.add(key)
        LOGGER.warning(
            "Extended Diagnostics could not read %s (%s: %s). Its lines are "
            "left out of stack_probe.md; detection is unaffected. Said once "
            "per start.",
            name,
            type(err).__name__,
            err,
        )

    @callback
    def probe_tick(self, now: float) -> None:
        """The probe's minute, guarded (0.23.10).

        Runs in the minute tick ahead of the freeze judgment. Before
        0.23.10 a throw anywhere in it stopped that tick, so while a
        studied library misbehaved nothing was judged, listed or
        saved.
        """
        try:
            self._probe_tick(now)
        except Exception as err:  # noqa: BLE001 - recording must never stop judging
            self._probe_failure("the probe", err)

    @callback
    def _probe_tick(self, now: float) -> None:
        """Write a line when a studied stack's node, its coordinator, or
        Device Sentinel's view of the node's device changes.

        Nothing is written while both sides say what they said last
        tick, which on a healthy network is every tick. Reading is in
        memory, so the cost is one attribute per node. A Z-Wave plug
        unplugged stays "alive", so the stack side alone would write
        nothing for it; the line comes from last seen passing the
        device's window, or from Device Sentinel's verdict changing
        (0.23.8, research finding 12).
        """
        self._probe_migrate()
        self._probe_flush()
        studied = self.studied
        if not studied & PROBED_DOMAINS:
            self._probe_last.clear()
            self._zwave_unlisten()
            self._thread_stop()
            return
        if ZWAVE_DOMAIN in studied:
            self._zwave_listen()
        else:
            self._zwave_unlisten()
        if MATTER_DOMAIN in studied:
            self._thread_start()
        else:
            self._thread_stop()
        wifi_nodes: dict[str, bool] = {}
        for row in probe_rows(self.hass, studied, self._probe_failure):
            views = self._probe_views(row, now)
            if row["stack"] == MATTER_DOMAIN and "wifi" in (row.get("network") or ""):
                wifi_nodes[self._probe_name(row)] = row["now"] == "available"
            key = (row["stack"], row["node"])
            # A Z-Wave node's route is part of what it says (0.23.11):
            # a repeater dying moves or breaks the routes through it.
            route = row.get("route") or ""
            said = (views["now"], views["sentinel"], route)
            before = self._probe_last.get(key)
            self._probe_last[key] = said
            if before is not None and before[:2] == said[:2] and before[2] != route:
                views["detail"] = ", ".join(
                    part for part in (f"route changed from {before[2] or 'unknown'}", views["detail"]) if part
                )
            if before is None:
                # The first reading of a node is its own line, so a
                # file read months later knows where each node began.
                was = ""
            elif before == said:
                # The numbers move constantly and the state does not;
                # a line is worth writing when a state changes, and the
                # numbers ride on that line.
                continue
            else:
                was = before[0]
            self._probe_queue({
                PROBE_WHEN: now,
                PROBE_STACK: row["stack"],
                PROBE_NODE: row["node"],
                PROBE_DEVICE_ID: row.get("device_id") or "",
                PROBE_WAS: was,
                PROBE_NOW: views["now"],
                PROBE_SENTINEL: views["sentinel"],
                PROBE_AGREES: views["agrees"],
                PROBE_DETAIL: views["detail"],
            })
        for row in coordinator_rows(self.hass, studied, self._probe_failure):
            key = (row["stack"], row["node"])
            stated = (row["now"], row["detail"])
            before = self._probe_last.get(key)
            self._probe_last[key] = stated
            if before == stated:
                continue
            self._probe_queue({
                PROBE_WHEN: now,
                PROBE_STACK: row["stack"],
                PROBE_NODE: row["node"],
                PROBE_DEVICE_ID: "",
                PROBE_WAS: before[0] if before else "",
                PROBE_NOW: row["now"],
                PROBE_SENTINEL: "",
                PROBE_AGREES: "",
                PROBE_DETAIL: row["detail"],
            })
        # Matter over Wi-Fi in a Wi-Fi outage (#412's exception): when
        # Device Sentinel's Wi-Fi outage opens or closes, which Matter
        # Wi-Fi nodes were away and which were not.
        wifi_down = getattr(self, "_wifi_down_at", None) is not None
        if MATTER_DOMAIN in studied and wifi_down != self._probe_wifi_down:
            if self._probe_wifi_down is not None and wifi_nodes:
                away = sorted(name for name, up in wifi_nodes.items() if not up)
                up = sorted(name for name, up in wifi_nodes.items() if up)
                self._probe_queue({
                    PROBE_WHEN: now,
                    PROBE_STACK: MATTER_DOMAIN,
                    PROBE_NODE: "wifi",
                    PROBE_DEVICE_ID: "",
                    PROBE_WAS: "",
                    PROBE_NOW: "wifi down" if wifi_down else "wifi up",
                    PROBE_SENTINEL: "",
                    PROBE_AGREES: "",
                    PROBE_DETAIL: (
                        f"away: {', '.join(away) or 'none'}; "
                        f"available: {', '.join(up) or 'none'}"
                    ),
                })
            self._probe_wifi_down = wifi_down

    def _probe_name(self, row: dict[str, Any]) -> str:
        """A node's device name, or its node id where it has none."""
        device_id = row.get("device_id")
        return (self._device_name(device_id) if device_id else None) or f"node {row['node']}"  # type: ignore[attr-defined]

    def _probe_queue(self, row: dict[str, Any]) -> None:
        """Render a probe line now and hold it for the next flush.

        Rendered at once, so the device name is the one it had when
        the line happened. Written to the file on the next tick or at
        the fold, off the event loop (0.23.9).
        """
        line = self._probe_render(row)  # type: ignore[attr-defined]
        self._probe_pending.append(line)
        self._probe_recent.append(line)

    @callback
    def _probe_flush(self) -> None:
        """Append the held lines to stack_probe.md, off the event loop."""
        if not self._probe_pending:
            return
        lines, self._probe_pending = self._probe_pending, []
        self.hass.async_add_executor_job(self._probe_write_lines, lines)  # type: ignore[attr-defined]

    @callback
    def _probe_migrate(self) -> None:
        """Move lines stored before 0.23.9 into the file, once.

        They were kept in storage and the file was rebuilt from them;
        now the file is the record. The old file, a copy of those
        lines newest first, is replaced by them in order.
        """
        rows = self.data.get(DATA_STACK_PROBE)
        if not rows:
            return
        ordered = sorted(
            (row for row in rows if isinstance(row, dict)),
            key=lambda row: row.get(PROBE_WHEN) or 0.0,
        )
        lines = [self._probe_render(row) for row in ordered]  # type: ignore[attr-defined]
        self.data[DATA_STACK_PROBE] = []
        self._mark_cold_dirty()
        self.hass.async_add_executor_job(self._probe_write_lines, lines, True)  # type: ignore[attr-defined]

    async def async_probe_stop(self) -> None:
        """Write the lines still held, as Device Sentinel stops (0.23.10).

        Lines wait for the next tick to be written, and a stop has no
        next tick, so the minute before every restart or settings
        change was lost. Called on Home Assistant's stop event and on
        every unload, each time ahead of the save that must follow it,
        so nothing here may raise: a throw would cost the save and the
        clean-stop marker, and the next start would read the stop as a
        power cut.
        """
        self._zwave_unlisten()
        discovery, self._thread_discovery = self._thread_discovery, None
        if discovery is not None:
            try:
                await discovery.async_stop()
            except Exception as err:  # noqa: BLE001 - the save after this must run
                LOGGER.debug("device_sentinel: Thread discovery did not stop (%s)", err)
        if not self._probe_pending:
            return
        lines, self._probe_pending = self._probe_pending, []
        try:
            await self.hass.async_add_executor_job(self._probe_write_lines, lines)  # type: ignore[attr-defined]
        except Exception as err:  # noqa: BLE001 - the save after this must run
            LOGGER.warning(
                "Device Sentinel could not write its last Extended "
                "Diagnostics lines at the stop (%s: %s)",
                type(err).__name__,
                err,
            )

    # --------------------------------------- node events and routers, 0.23.11

    @callback
    def _zwave_listen(self) -> None:
        """Listen to each Z-Wave node's wake up, sleep, dead and alive.

        Recording only: the library already announces these to Home
        Assistant, and listening sends nothing to the network. A node
        object is replaced when the driver reconnects, so subscriptions
        are keyed by the object and a new one is listened to afresh.
        """
        seen: set[int] = set()
        for node, node_id, device_id in zwave_nodes(self.hass):  # type: ignore[attr-defined]
            key = id(node)
            seen.add(key)
            if key in self._zwave_listeners:
                continue
            on = getattr(node, "on", None)
            if not callable(on):
                continue
            removers: list[Callable[[], None]] = []
            for event in ZWAVE_NODE_EVENTS:
                try:
                    removers.append(on(event, self._zwave_event_handler(node_id, device_id, event)))
                except Exception as err:  # noqa: BLE001 - a library behaving oddly
                    self._probe_failure(ZWAVE_DOMAIN, err)
                    break
            self._zwave_listeners[key] = [each for each in removers if callable(each)]
        for key in [k for k in self._zwave_listeners if k not in seen]:
            self._remove_all(self._zwave_listeners.pop(key))

    @staticmethod
    def _remove_all(removers: list[Callable[[], None]]) -> None:
        """Call each unsubscribe, ignoring a node already gone."""
        for remove in removers:
            try:
                remove()
            except Exception as err:  # noqa: BLE001 - a node already gone
                LOGGER.debug("device_sentinel: a Z-Wave listener was already gone (%s)", err)

    @callback
    def _zwave_unlisten(self) -> None:
        """Stop listening to every Z-Wave node."""
        for removers in self._zwave_listeners.values():
            self._remove_all(removers)
        self._zwave_listeners.clear()

    def _zwave_event_handler(self, node_id: str, device_id: str, event: str) -> Callable[..., None]:
        """One node event, written as a line with the second it came."""

        @callback
        def _heard(_data: Any = None) -> None:
            try:
                moment = dt_util.now()
                row = {"stack": ZWAVE_DOMAIN, "node": node_id, "device_id": device_id, "now": event}
                views = self._probe_views(row, moment.timestamp())
                self._probe_queue({
                    PROBE_WHEN: moment.timestamp(),
                    PROBE_STACK: ZWAVE_DOMAIN,
                    PROBE_NODE: node_id,
                    PROBE_DEVICE_ID: device_id,
                    PROBE_WAS: "",
                    PROBE_NOW: f"event: {event}",
                    PROBE_SENTINEL: views["sentinel"],
                    PROBE_AGREES: "",
                    PROBE_DETAIL: f"at {moment.strftime('%H:%M:%S')}",
                })
            except Exception as err:  # noqa: BLE001 - recording must never stop the library
                self._probe_failure(ZWAVE_DOMAIN, err)

        return _heard

    @callback
    def _zwave_health_line(self, now: float) -> None:
        """One line a day per controller: the counters' change and the noise.

        Dropped messages, NAKs, collisions and timeouts only ever rise,
        so the line carries the day's change; the counters restart with
        Home Assistant, and the first line after a start carries the
        count since then. Background noise is the controller's own
        reading of each channel.
        """
        for entry_id, counters, noise in zwave_health(self.hass):  # type: ignore[attr-defined]
            before = self._zwave_counters.get(entry_id) or {}
            self._zwave_counters[entry_id] = counters
            changes = []
            for name in sorted(counters):
                start = before.get(name, 0)
                change = counters[name] - start if counters[name] >= start else counters[name]
                changes.append(f"{name} +{change}")
            detail = ", ".join(part for part in (", ".join(changes), f"noise {noise}" if noise else "") if part)
            self._probe_queue({
                PROBE_WHEN: now,
                PROBE_STACK: ZWAVE_DOMAIN,
                PROBE_NODE: "controller",
                PROBE_DEVICE_ID: "",
                PROBE_WAS: "",
                PROBE_NOW: "health",
                PROBE_SENTINEL: "",
                PROBE_AGREES: "",
                PROBE_DETAIL: detail or "no counters read",
            })

    @callback
    def _thread_start(self) -> None:
        """Start watching for Thread border routers, once.

        Home Assistant's Thread integration finds border routers by
        their announcements on the local network, and says when one
        appears and when one goes; its Thread panel shows the same
        (ruled 27 September 2026, recording only).
        """
        if self._thread_discovery is not None or self._thread_starting or self._thread_failed:
            return
        self._thread_starting = True
        self.hass.async_create_task(self._async_thread_start())  # type: ignore[attr-defined]

    async def _async_thread_start(self) -> None:
        """Open the discovery; a house without Thread simply has none."""
        try:
            from homeassistant.components.thread.discovery import (  # noqa: PLC0415 - loaded only when studied
                ThreadRouterDiscovery,
            )

            discovery = ThreadRouterDiscovery(
                self.hass,  # type: ignore[attr-defined]
                self._thread_router_found,
                self._thread_router_gone,
            )
            await discovery.async_start()
        except Exception as err:  # noqa: BLE001 - no Thread, or a library behaving oddly
            # Tried once per start: a house without Thread has neither the
            # integration nor its library, and asking every minute would
            # only repeat the answer.
            LOGGER.debug("device_sentinel: Thread discovery not started (%s)", err)
            self._thread_starting = False
            self._thread_failed = True
            return
        self._thread_discovery = discovery
        self._thread_starting = False

    @callback
    def _thread_stop(self) -> None:
        """Stop watching for border routers."""
        discovery, self._thread_discovery = self._thread_discovery, None
        if discovery is not None:
            self.hass.async_create_task(discovery.async_stop())  # type: ignore[attr-defined]

    def _thread_router_found(self, address: str, data: Any) -> None:
        """A border router announced itself, or changed what it says."""
        name = " ".join(
            str(part) for part in (getattr(data, "vendor_name", None), getattr(data, "model_name", None)) if part
        ) or str(getattr(data, "instance_name", "") or "")
        detail = ", ".join(
            part
            for part in (
                f"network {getattr(data, 'network_name', None) or 'unnamed'}",
                f"network id {str(getattr(data, 'extended_pan_id', '') or '').lower() or 'unknown'}",
                name,
                f"router {address}",
            )
            if part
        )
        self.hass.loop.call_soon_threadsafe(self._thread_router_line, address, "present", detail)  # type: ignore[attr-defined]

    def _thread_router_gone(self, address: str) -> None:
        """A border router stopped announcing itself."""
        self.hass.loop.call_soon_threadsafe(self._thread_router_line, address, "gone", "")  # type: ignore[attr-defined]

    @callback
    def _thread_router_line(self, address: str, state: str, detail: str) -> None:
        """Write a border router's line when what it says changes."""
        try:
            before = self._thread_routers.get(address)
            if state == "gone":
                if before is None or before[0] == "gone":
                    return
                detail = before[1]
            elif before is not None and before[:2] == (state, detail):
                return
            self._thread_routers[address] = (state, detail, "")
            self._probe_queue({
                PROBE_WHEN: dt_util.utcnow().timestamp(),
                PROBE_STACK: THREAD_STACK,
                PROBE_NODE: "border router",
                PROBE_DEVICE_ID: "",
                PROBE_WAS: before[0] if before else "",
                PROBE_NOW: state,
                PROBE_SENTINEL: "",
                PROBE_AGREES: "",
                PROBE_DETAIL: ", ".join(
                    part for part in (detail, f"at {dt_util.now().strftime('%H:%M:%S')}") if part
                ),
            })
        except Exception as err:  # noqa: BLE001 - recording must never stop discovery
            self._probe_failure(THREAD_STACK, err)

    @callback
    def probe_fold(self, now: float) -> None:
        """The probe's part of the midnight fold, guarded (0.23.10).

        Runs before the day is rolled. Before 0.23.10 a throw here
        aborted the fold for every device in the house.
        """
        try:
            self._probe_fold(now)
        except Exception as err:  # noqa: BLE001 - recording must never stop the fold
            self._probe_failure("the probe", err)

    @callback
    def _probe_fold(self, now: float) -> None:
        """One counting line a day per stack, and the old lines dropped.

        The count carries each state and, since 0.23.8, how many nodes
        the stack and Device Sentinel agreed on and how many they did
        not, which is the figure the readers will be built from.
        """
        studied = self.studied
        if studied & PROBED_DOMAINS:
            counts: dict[str, dict[str, int]] = {}
            agreement: dict[str, dict[str, int]] = {}
            for row in probe_rows(self.hass, studied, self._probe_failure):
                views = self._probe_views(row, now)
                by_state = counts.setdefault(row["stack"], {})
                by_state[row["now"]] = by_state.get(row["now"], 0) + 1
                if views["agrees"]:
                    tally = agreement.setdefault(row["stack"], {"yes": 0, "no": 0})
                    tally[views["agrees"]] += 1
            if ZWAVE_DOMAIN in studied:
                self._zwave_health_line(now)
            for stack, by_state in counts.items():
                tally = agreement.get(stack, {"yes": 0, "no": 0})
                self._probe_queue({
                    PROBE_WHEN: now,
                    PROBE_STACK: stack,
                    PROBE_NODE: "",
                    PROBE_DEVICE_ID: "",
                    PROBE_WAS: "",
                    PROBE_NOW: "day",
                    PROBE_SENTINEL: "",
                    PROBE_AGREES: f"{tally['yes']} agree, {tally['no']} do not",
                    PROBE_DETAIL: ", ".join(
                        f"{state} {count}"
                        for state, count in sorted(by_state.items())
                    ),
                })
        self._probe_flush()

    # --------------------------------------------------- the fold, #393

    @callback
    def study_fold(self) -> None:
        """Drop what is no longer volunteered.

        Unticking a toggle stops collection at once and the shapes go
        at the next fold, the same way every other retention in this
        integration works.
        """
        studied = self.studied
        gone = [name for name in self._study_shapes if name not in studied]
        for name in gone:
            self._study_shapes.pop(name, None)
            self._study_capped.pop(name, None)
            LOGGER.info(
                "device_sentinel: study of %s ended, its readings are "
                "removed",
                name,
            )
        if gone:
            self._mark_cold_dirty()

    # ---------------------------------------------------- diagnostics

    @property
    def study_diagnostics(self) -> dict[str, Any]:
        """Everything a study has gathered, for the download."""
        if not self.studied and not self._study_shapes:
            return {}
        return {
            "studying": sorted(self.studied),
            "capped": sorted(
                name for name, hit in self._study_capped.items() if hit
            ),
            "shapes": {
                name: list(shapes.values())
                for name, shapes in sorted(self._study_shapes.items())
            },
            "snapshot": self.study_snapshot(),
        }
