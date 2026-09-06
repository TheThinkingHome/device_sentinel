# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study.py, Version: 0.20.10 (2026-09-06)

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

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_STUDY_HARDWARE,
    LOGGER,
    STUDIABLE,
    STUDY_SHAPE_CAP,
)

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
        for device_id in self._watched:
            device = devices.async_get(device_id)
            if device is None:
                continue
            watched.append({
                "name": device.name_by_user or device.name,
                "integration": next(iter(device.identifiers), ("", ""))[0],
                "connections": sorted(
                    f"{kind}:{value}" for kind, value in device.connections
                ),
                "identifiers": sorted(
                    str(ident) for _domain, ident in device.identifiers
                ),
            })
        return {"trackers": trackers, "watched_devices": watched}

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
