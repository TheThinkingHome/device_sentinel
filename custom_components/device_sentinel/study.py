# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study.py, Version: 0.23.9 (2026-09-26)

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
)

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
        sentinel_quiet = (
            None if sentinel in ("", STATUS_SET_ASIDE, STATUS_NEVER_REPORTED)
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

    @callback
    def probe_tick(self, now: float) -> None:
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
            return
        wifi_nodes: dict[str, bool] = {}
        for row in probe_rows(self.hass, studied):
            views = self._probe_views(row, now)
            if row["stack"] == MATTER_DOMAIN and "wifi" in (row.get("network") or ""):
                wifi_nodes[self._probe_name(row)] = row["now"] == "available"
            key = (row["stack"], row["node"])
            said = (views["now"], views["sentinel"])
            before = self._probe_last.get(key)
            self._probe_last[key] = said
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
        for row in coordinator_rows(self.hass, studied):
            key = (row["stack"], row["node"])
            said = (row["now"], row["detail"])
            before = self._probe_last.get(key)
            self._probe_last[key] = said
            if before == said:
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

    @callback
    def probe_fold(self, now: float) -> None:
        """One counting line a day per stack, and the old lines dropped.

        The count carries each state and, since 0.23.8, how many nodes
        the stack and Device Sentinel agreed on and how many they did
        not, which is the figure the readers will be built from.
        """
        studied = self.studied
        if studied & PROBED_DOMAINS:
            counts: dict[str, dict[str, int]] = {}
            agreement: dict[str, dict[str, int]] = {}
            for row in probe_rows(self.hass, studied):
                views = self._probe_views(row, now)
                by_state = counts.setdefault(row["stack"], {})
                by_state[row["now"]] = by_state.get(row["now"], 0) + 1
                if views["agrees"]:
                    tally = agreement.setdefault(row["stack"], {"yes": 0, "no": 0})
                    tally[views["agrees"]] += 1
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
