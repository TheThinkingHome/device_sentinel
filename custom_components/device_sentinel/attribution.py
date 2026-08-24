# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: attribution.py, Version: 0.15.5 (2026-08-17)

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

AN EXPLANATION MUST HAVE BEEN IN EFFECT WHEN THE SILENCE BEGAN. That
is the whole selection rule, and it separates a cause from its own
symptom without ranking anything. A broker outage at 01:47 takes
devices at 01:50 and they return at 02:04, and the burst of them
returning is itself recorded as a storm at 02:04. Both cover the
device and both overlap the incident, but only the broker window was
open when the device went quiet, so only the broker can have caused
it. Ranking by narrowness picked the storm and named a consequence as
the cause (ruling #229). The same test fixes the nightly reboot,
where the burst of devices returning inside startup grace is the
restart rather than an integration reloading.

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

    __slots__ = (
        "kind",
        "scope",
        "start",
        "end",
        "devices",
        "inferred_end",
    )

    def __init__(
        self, kind, scope, start, end, devices=None, inferred_end=False
    ):
        """Hold what an intervention was, when, and how big.

        inferred_end says the closing was never recorded and this end
        was worked out rather than seen (ruling #287). It changes what
        may be said about the window: we know the thing ended, and we
        do not know that it recovered.
        """
        self.kind = kind
        self.scope = scope
        self.start = start
        self.end = end
        self.devices = devices
        self.inferred_end = inferred_end

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

    def in_effect_at(self, moment: float) -> bool:
        """Return whether this intervention was under way at a moment.

        The edge allowance is the sampler's own resolution. A bridge
        or broker outage is noticed up to a tick after it began and
        its recovery up to a tick after that, so a device that fell
        quiet just before the record, or returned just after it, is
        still the same event.
        """
        if moment < self.start - _EDGE_SECONDS:
            return False
        if self.end is None:
            return True
        return moment <= self.end + _EDGE_SECONDS


def windows(events: list[dict[str, Any]]) -> list[Window]:
    """Return every intervention window in the system events log.

    Openings are paired with their closings by kind and scope, so a
    bridge outage becomes one window rather than two moments.

    An opening whose closing was never recorded used to stay open
    forever, and forever is not a figure of speech: a bridge outage
    from 2 August was still explaining recoveries on the 17th,
    because attribute() prefers the earliest window and an unbounded
    one beats every real candidate. On the reference fleet 23 windows
    were in that state, and the brief credited a device's 03:23
    recovery to a bridge that went down fifteen days earlier.

    The cause is ordinary and permanent: the opening is written, the
    system restarts, and the closing is never written because the
    storm or the outage only existed in memory. So the rule has to
    work forever rather than clean up once (ruling #287). An unclosed
    window ends at the first restart after it opened, or at the next
    opening of the same kind and scope, whichever comes first. Both
    are proof that it must have ended: a system that restarted lost
    it, and a bridge cannot go down twice without coming up in
    between. Against the reference fleet the restart bound closes 3
    and the next-opening bound closes 20, and neither alone reaches
    all 23.

    An opening with nothing after it stays open, which is still
    correct: a bridge that is down right now is in effect.
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
            # Anything still open did not survive this, and the
            # closing was never going to be written. Bounded at the
            # moment the system came back rather than the moment it
            # went down, because the outage ran through the gap and
            # the restart's own window covers the gap itself.
            for open_window in pending.values():
                open_window.end = when
                open_window.inferred_end = True
            pending.clear()
            span = row.get(SYS_DURATION) or 0.0
            found.append(
                Window(kind, scope, when - span, when + _RESTART_TAIL_SECONDS)
            )
            continue
        if kind in _PAIRS:
            previous = pending.get((kind, scope))
            if previous is not None:
                # The same thing opening again is proof the last one
                # ended, whether or not anybody wrote it down.
                previous.end = when
                previous.inferred_end = True
            window = Window(kind, scope, when, None, row.get(SYS_DEVICES))
            pending[(kind, scope)] = window
            found.append(window)
            continue
        if kind in _CLOSERS:
            for opening, closing in _PAIRS.items():
                if closing != kind:
                    continue
                closed = pending.pop((opening, scope), None)
                if closed is not None:
                    closed.end = when
                    if closed.devices is None:
                        closed.devices = row.get(SYS_DEVICES)
    return found


def attribute(
    all_windows: list[Window],
    domain: str | None,
    stack: str | None,
    opened: float,
    closed: float | None,
) -> Window | None:
    """Return the intervention that explains one incident, or None.

    First choice is a window that was already in effect when the
    device went quiet, because that is the only kind that can have
    caused the silence. Where several were, the earliest wins: an
    outage that takes a broker down also produces a burst when its
    devices return, and the outage is the cause of both.

    Second choice, only where nothing was in effect at the opening,
    is a window covering the recovery. A device that had been silent
    for hours before an outage was not silenced by it, but it may
    well have been revived when everything else came back, and
    saying so is more useful than saying nothing.
    """
    reach = [
        window for window in all_windows if window.covers(domain, stack)
    ]
    began = [
        window for window in reach if window.in_effect_at(opened)
    ]
    if began:
        return min(began, key=lambda window: window.start)
    if closed is None:
        return None
    revived = [window for window in reach if window.in_effect_at(closed)]
    if not revived:
        return None
    return min(revived, key=lambda window: window.start)

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


# What may be said about a window whose closing was never recorded.
# The wording above is written for an observed pair, and two of them
# assert a return: a bridge or a broker "going down and coming back".
# For an inferred end we know the thing ended and we do not know that
# it came back, so the claim is dropped rather than repeated on
# evidence that does not exist (ruling #287).
_PHRASE_INFERRED = {
    SYS_BRIDGE_DOWN: "the {scope} bridge going down",
    SYS_BROKER_DOWN: "the MQTT broker going down",
}


def phrase(window: Window) -> str:
    """Return the clause naming an intervention, without punctuation."""
    if getattr(window, "inferred_end", False):
        wording = _PHRASE_INFERRED.get(window.kind)
        if wording is not None:
            return wording.format(scope=window.scope)
    return _PHRASE.get(window.kind, window.kind).format(scope=window.scope)
