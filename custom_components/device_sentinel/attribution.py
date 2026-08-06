# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: attribution.py, Version: 0.12.5 (2026-08-06)

"""Which recorded event explains an incident, and which do not.

WHY THIS EXISTS. The cause of a recovery used to be borrowed from the
device's most recent silence episode, whichever one that was. When an
incident closed with no episode behind it, which is exactly what a
broker outage produces, the lookup returned a fact from a week
earlier. On the reference fleet on 2026-08-06 that put four different
explanations on one event: 74 devices recovered inside 8.5 seconds
from a single broker outage, and the brief credited 38 to a bridge
reconnect, 3 to a reboot, and 24 to nothing, with devices resolving in
the same millisecond disagreeing. The wording was wrong rather than
merely inconsistent (ruling #228).

WHAT REPLACES IT. An incident is explained by a recorded intervention
whose window overlaps it and whose scope covers the device. Nothing
else. Where no intervention covers it, the device recovered on its
own and the brief says so rather than naming a lever.

SCOPE IS THE HALF THAT MATTERS. A Zigbee bridge reconnecting cannot
revive a HomeKit accessory, and crediting it with one is the fault
this file exists to prevent. So a restart covers every device, a
broker covers the MQTT domain, a bridge or a pairing window covers
the devices of its own stack, and a storm covers only its own
integration.

WHY AT RENDER TIME. A broker outage is written up to a minute after
its devices drop, so an opening cannot be attributed when it is
recorded, only afterwards. Attributing on the way out also means the
687 incident rows already on disk are read correctly, rather than
only those recorded from this release onward.
"""

from __future__ import annotations

from typing import Any

from .const import (
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_STORM_CLOSED,
    SYS_STORM_OPEN,
    SYS_UNCLEAN_RESTART,
    SYS_WHEN,
)

# The pairs, opening kind to closing kind. Each becomes one window
# running from the opening to the close, or left open where the close
# has not been recorded yet.
_PAIRS = {
    SYS_BRIDGE_DOWN: SYS_BRIDGE_UP,
    SYS_BROKER_DOWN: SYS_BROKER_UP,
    SYS_PAIRING_OPEN: SYS_PAIRING_CLOSED,
    SYS_STORM_OPEN: SYS_STORM_CLOSED,
}
_CLOSERS = set(_PAIRS.values())

# How wide a moment a restart is. Its recorded duration is the span
# nothing was listening, which is when its devices fell silent, and
# the seconds after it come back are when they return.
_RESTART_TAIL_SECONDS = 120.0
# A window is allowed to explain an incident that began shortly
# before it was recorded, because a sampler notices an outage up to
# one tick after it starts.
_EDGE_SECONDS = 90.0


class Window:
    """One recorded intervention, with a span and a reach."""

    __slots__ = ("kind", "scope", "start", "end", "devices")

    def __init__(self, kind, scope, start, end, devices=None):
        """Hold what an intervention was, when, and how big."""
        self.kind = kind
        self.scope = scope
        self.start = start
        self.end = end
        self.devices = devices

    @property
    def key(self) -> tuple[str, str, float]:
        """Return what makes two incidents share one explanation."""
        return (self.kind, self.scope, self.start)

    def covers(self, domain: str | None, stack: str | None) -> bool:
        """Return whether this intervention could reach this device.

        The whole point of the file. A restart touches everything; a
        broker touches whatever speaks through it; a bridge and a
        pairing window touch their own stack; a storm touches only
        the integration it was seen on.
        """
        if self.kind in (SYS_RESTART, SYS_UNCLEAN_RESTART):
            return True
        if self.kind == SYS_BROKER_DOWN:
            return domain == "mqtt"
        if self.kind in (SYS_BRIDGE_DOWN, SYS_PAIRING_OPEN):
            return stack is not None and stack == self.scope
        if self.kind == SYS_STORM_OPEN:
            return domain is not None and domain == self.scope
        return False

    def overlaps(self, opened: float, closed: float | None) -> bool:
        """Return whether this window and an incident share any time.

        The edge allowance is the sampler's own resolution: a bridge
        or broker outage is noticed up to a tick after it began, so
        an incident that opened just before the record is still the
        same event.
        """
        end = self.end if self.end is not None else closed
        if end is None:
            end = opened
        last = closed if closed is not None else opened
        return (
            self.start - _EDGE_SECONDS <= last
            and end + _EDGE_SECONDS >= opened
        )


def windows(events: list[dict[str, Any]]) -> list[Window]:
    """Return every intervention window in the system events log.

    Openings are paired with their closings by kind and scope, so a
    bridge outage becomes one window rather than two moments. An
    opening with no closing yet stays open, which is correct: the
    thing is still happening.
    """
    found: list[Window] = []
    pending: dict[tuple[str, str], Window] = {}
    for row in sorted(events or [], key=lambda item: item.get(SYS_WHEN) or 0):
        kind = row.get(SYS_KIND)
        scope = row.get(SYS_SCOPE) or ""
        when = row.get(SYS_WHEN)
        if when is None:
            continue
        if kind in (SYS_RESTART, SYS_UNCLEAN_RESTART):
            span = row.get(SYS_DURATION) or 0.0
            found.append(
                Window(kind, scope, when - span, when + _RESTART_TAIL_SECONDS)
            )
            continue
        if kind in _PAIRS:
            window = Window(kind, scope, when, None, row.get(SYS_DEVICES))
            pending[(kind, scope)] = window
            found.append(window)
            continue
        if kind in _CLOSERS:
            for opening, closing in _PAIRS.items():
                if closing != kind:
                    continue
                window = pending.pop((opening, scope), None)
                if window is not None:
                    window.end = when
                    if window.devices is None:
                        window.devices = row.get(SYS_DEVICES)
    return found


def attribute(
    all_windows: list[Window],
    domain: str | None,
    stack: str | None,
    opened: float,
    closed: float | None,
) -> Window | None:
    """Return the intervention that explains one incident, or None.

    Where more than one could, the narrowest wins: a storm on the
    device's own integration says more than a restart of the whole
    machine, and saying the more specific true thing is the point.
    """
    candidates = [
        window
        for window in all_windows
        if window.covers(domain, stack) and window.overlaps(opened, closed)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda window: _RANK.get(window.kind, 99))


# Narrower first. A storm names one integration, a bridge one stack,
# a broker one transport, a restart the whole house.
_RANK = {
    SYS_STORM_OPEN: 0,
    SYS_PAIRING_OPEN: 1,
    SYS_BRIDGE_DOWN: 2,
    SYS_BROKER_DOWN: 3,
    SYS_UNCLEAN_RESTART: 4,
    SYS_RESTART: 5,
}

# What a person reads. Written here rather than in the brief so the
# prose, the tables and any future notification cannot describe one
# event three ways.
_PHRASE = {
    SYS_STORM_OPEN: "the {scope} integration reloading",
    SYS_PAIRING_OPEN: "a {scope} pairing window",
    SYS_BRIDGE_DOWN: "the {scope} bridge going down and coming back",
    SYS_BROKER_DOWN: "the MQTT broker going down and coming back",
    SYS_UNCLEAN_RESTART: "an unclean restart",
    SYS_RESTART: "a restart",
}


def phrase(window: Window) -> str:
    """Return the clause naming an intervention, without punctuation."""
    return _PHRASE.get(window.kind, window.kind).format(scope=window.scope)
