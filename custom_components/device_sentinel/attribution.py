# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: attribution.py, Version: 0.27.10 (2026-10-27)

"""Which recorded event explains an incident, and which do not.

An incident is explained only by a recorded intervention whose window
overlaps it and whose scope covers the device. Where none covers it,
the device recovered on its own and the brief says so. A restart or an
outage is found like any window but credited with no recovery, because
it says nothing about the devices (rule BRIEF-05).

The explanation must have been in effect when the silence began. That
separates a cause from its own symptom: a broker outage takes devices
down, and the burst of them returning is recorded as a storm, but only
the broker window was open when the device went quiet (rule BRIEF-05).
The same test keeps the burst after a nightly restart from reading as
an integration reload.

Scope matters as much. A Zigbee bridge reconnecting cannot revive a
HomeKit accessory. So a restart covers every device, a broker covers
the MQTT domain, a bridge or a pairing window covers its own stack, a
storm or an integration outage covers only its own integration, a
Wi-Fi outage covers every device, and a person handling a ZHA device
covers that device alone.

Attribution runs at render time because a broker outage is written up
to a minute after its devices drop, and so incident rows already on
disk are read the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .const import (
    SYS_DETAIL,
    SYS_DEVICE_HANDLED,
    ZHA_HANDLED_TAIL_SECONDS,
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
    SYS_WIFI_DOWN,
    SYS_WIFI_UP,
    SYS_INTEGRATION_DOWN,
    SYS_INTEGRATION_UP,
)
from .outage_detail import pair_key

# The pairs, opening kind to closing kind. Each becomes one window
# running from the opening to the close, or left open where the close
# has not been recorded yet.
_PAIRS = {
    SYS_BRIDGE_DOWN: SYS_BRIDGE_UP,
    SYS_BROKER_DOWN: SYS_BROKER_UP,
    SYS_PAIRING_OPEN: SYS_PAIRING_CLOSED,
    SYS_STORM_OPEN: SYS_STORM_CLOSED,
    # So a device that fails during an integration or Wi-Fi outage is
    # explained rather than left a mystery in the brief.
    SYS_INTEGRATION_DOWN: SYS_INTEGRATION_UP,
    SYS_WIFI_DOWN: SYS_WIFI_UP,
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
        was worked out, not seen. The thing ended, but Device Sentinel
        does not know that it recovered (rule STOR-18).
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
        if self.kind == SYS_DEVICE_HANDLED:
            # One device, named in `devices`, and no other. ZHA
            # announces a device rather than a window, so a handling
            # explains that device's recovery and nothing else
            # (rule FRZ-17).
            return False
        if self.kind == SYS_STORM_OPEN:
            return domain is not None and domain == self.scope
        if self.kind == SYS_INTEGRATION_DOWN:
            # Scoped to the integration's own domain, which is what
            # the outage records.
            return domain is not None and domain == self.scope
        if self.kind == SYS_WIFI_DOWN:
            # The network reaches every integration, because what
            # fails is the transport under all of them. A device tied
            # to a tracker is already held back from reporting
            # (rule UP-05); this covers the devices no tie could claim.
            return True
        return False

    def in_effect_at(self, moment: float) -> bool:
        """Return whether this intervention was under way at a moment.

        The edge allowance is the sampler's own resolution. A bridge
        or broker outage is noticed up to a tick after it began and
        its recovery up to a tick after that, so a device that fell
        quiet just before the record, or returned just after it, is
        still the same event.
        """
        if self.kind == SYS_DEVICE_HANDLED:
            # No edge allowance here (rule FRZ-17). The edge exists
            # because a sampler notices an outage up to a tick late,
            # and a handling is not sampled: it arrives as it happens.
            # With the allowance, a handling would explain recoveries
            # before the person touched the device.
            return self.start <= moment <= (self.end or moment)
        if moment < self.start - _EDGE_SECONDS:
            return False
        if self.end is None:
            return True
        return moment <= self.end + _EDGE_SECONDS


def windows(events: list[dict[str, Any]]) -> list[Window]:
    """Return every intervention window in the system events log.

    Openings are paired with their closings by kind and scope, so a
    bridge outage becomes one window rather than two moments.

    A closing is often never written, because the system restarted
    while the storm or outage lived only in memory. An unclosed window
    ends at the first restart after it opened, or at the next opening
    of the same kind and scope, whichever comes first, because each
    proves it ended (rule STOR-18). Without this, an unbounded window
    beats every real candidate in attribute() and explains recoveries
    days later.

    An opening with nothing after it stays open, which is correct: a
    bridge that is down right now is in effect.
    """
    found: list[Window] = []
    pending: dict[tuple[Any, Any, str | None], Window] = {}
    # A corrupted event must not take the builder down. A bad row is
    # repaired or removed at the storage boundary (rule STOR-09); a
    # row that reaches here anyway, from a path that never touched a
    # file, is skipped, which costs one attribution and nothing else.
    # The timestamp test is the same real-moment test the outage
    # onset uses.
    usable = [
        row
        for row in events or []
        if isinstance(row, dict)
        and isinstance(row.get(SYS_KIND), str)
        and isinstance(row.get(SYS_WHEN), (int, float))
        and not isinstance(row.get(SYS_WHEN), bool)
        and row.get(SYS_WHEN) > 0.0
    ]
    for row in sorted(usable, key=lambda item: item[SYS_WHEN]):
        kind = row.get(SYS_KIND)
        scope = row.get(SYS_SCOPE) or ""
        when = row.get(SYS_WHEN)
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
            # A duration of the wrong type reads as zero, as a missing
            # one does, so the window covers the restart moment itself
            # rather than crashing the arithmetic.
            span = row.get(SYS_DURATION) or 0.0
            if isinstance(span, bool) or not isinstance(
                span, (int, float)
            ):
                span = 0.0
            found.append(
                Window(kind, scope, when - span, when + _RESTART_TAIL_SECONDS)
            )
            continue
        if kind == SYS_DEVICE_HANDLED:
            # Bounded, not open, because nothing writes a closing for
            # a handling, and a person who touched a device and walked
            # away must not explain its recovery an hour later. A
            # reconfigure runs 15 seconds and a re-pair 34, and the
            # message precedes the recovery by two to eight
            # (rule FRZ-17).
            #
            # The device travels in `detail` because the event's own
            # `devices` field is an integer by the storage shape and
            # would raise a fault if given an id.
            detail = row.get(SYS_DETAIL)
            named = str(detail).split(" ", 1)[0] if detail else ""
            if not named:
                continue
            found.append(
                Window(
                    kind,
                    scope,
                    when,
                    when + ZHA_HANDLED_TAIL_SECONDS,
                    [named],
                )
            )
            continue
        if kind in _PAIRS:
            # Paired by entry too, so two entries of one integration
            # are two outages.
            entry = pair_key(kind, scope, row.get(SYS_DETAIL))[2]
            previous = pending.get((kind, scope, entry))
            if previous is not None:
                # The same thing opening again is proof the last one
                # ended, whether or not anybody wrote it down.
                previous.end = when
                previous.inferred_end = True
            window = Window(kind, scope, when, None, row.get(SYS_DEVICES))
            pending[(kind, scope, entry)] = window
            found.append(window)
            continue
        if kind in _CLOSERS:
            for opening, closing in _PAIRS.items():
                if closing != kind:
                    continue
                closed = pending.pop(
                    (opening, scope, pair_key(kind, scope, row.get(SYS_DETAIL))[2]),
                    None,
                )
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
    device_id: str | None = None,
) -> Window | None:
    """Return the intervention that explains one incident, or None.

    First choice is a window already in effect when the device went
    quiet, because only that kind can have caused the silence. Where
    several were, the earliest wins: an outage that takes a broker
    down also produces a burst when its devices return, and the outage
    is the cause of both.

    Second choice, only where nothing was in effect at the opening, is
    a window covering the recovery. Finding it is not crediting it:
    only a person's own act, a pairing window or a device handled, is
    credited (`credits`), and a recovery inside a restart or an outage
    is told as happening during it, never as caused by it
    (rule BRIEF-05).
    """
    reach = [
        window
        for window in all_windows
        if window.covers(domain, stack)
        or (
            # A device-scoped window reaches the one device it names
            # and nothing else (rule FRZ-17). Kept here rather than in
            # covers() because covers() answers from the domain and
            # the stack, which cannot tell two ZHA devices apart.
            window.kind == SYS_DEVICE_HANDLED
            and device_id is not None
            and window.devices is not None
            and device_id in window.devices
        )
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
    SYS_DEVICE_HANDLED: "somebody handling the device",
    SYS_BRIDGE_DOWN: "the {scope} bridge going down and coming back",
    SYS_BROKER_DOWN: "the MQTT broker going down and coming back",
    SYS_UNCLEAN_RESTART: "an unclean restart",
    SYS_RESTART: "a restart",
}


# What may be said about a window whose closing was never recorded.
# Two of the wordings above assert a return, a bridge or a broker
# "going down and coming back". For an inferred end the thing ended
# but may not have come back, so that claim is dropped (rule STOR-18).
_PHRASE_INFERRED = {
    SYS_BRIDGE_DOWN: "the {scope} bridge going down",
    SYS_BROKER_DOWN: "the MQTT broker going down",
}


# The windows that are a person's own act and may be credited with a
# recovery. The rest are restarts and outages, which say nothing about
# the devices: a recovery inside one is told as happening during it,
# never as caused by it (rule BRIEF-05).
CREDITED_WINDOWS = frozenset({SYS_PAIRING_OPEN, SYS_DEVICE_HANDLED})


def credits(window: Window) -> bool:
    """Whether a recovery inside this window is credited to it (rule BRIEF-05)."""
    return window.kind in CREDITED_WINDOWS


def phrase(window: Window, name: Callable[[str], str] | None = None) -> str:
    """Return the clause naming an intervention, without punctuation.

    The scope is named as Home Assistant shows it where the caller can
    say: Zigbee2MQTT, not z2m (rule GEN-07).
    """
    scope = name(str(window.scope)) if name is not None and window.scope else window.scope
    if getattr(window, "inferred_end", False):
        wording = _PHRASE_INFERRED.get(window.kind)
        if wording is not None:
            return wording.format(scope=scope)
    return _PHRASE.get(window.kind, window.kind).format(scope=scope)
