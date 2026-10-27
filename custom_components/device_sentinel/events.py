# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: events.py, Version: 0.27.10 (2026-10-27)

"""What Device Sentinel says on the Home Assistant bus.

An automation reacts to a device going frozen through these events
rather than by polling an entity's state.

Every fire call lives here, the same way every Repair call lives in
`repairs.py`, so the payload shape is decided once rather than in each
module that has a transition to announce.

Six event types, each with its own name rather than one type carrying
an action field, because an automation triggers on event_type and a
distinct name is what a person types into the trigger box: a fault,
its recovery, an acknowledgment, a withdrawal when a device leaves the
watched set without recovering, and an upstream going down and coming
back (rule NOTE-12).

Where they fire is the whole design. A device earns an
event when its line is added to the problem list, when a kind leaves
it, and when a person ticks it. Nowhere else. That boundary already
carries the per-device debounce and the multi-fault collapse, so an
automation gets the same filtering a person gets: no thirty-second
blips, one event for a device with two faults, and nothing at all
during the startup grace (rules NOTE-12, WATCH-10).

An outage upstream, a broker or bridge, fires its own pair rather
than one event per device, because the devices behind a downed bridge
never become rows and never fire (rule UP-05). A stopped broker or
bridge silences a whole house, and without the pair an automation
could not see the one failure that takes a house quiet (rule UP-10).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    EVENT_ACKNOWLEDGED,
    EVENT_FAULT,
    EVENT_UPSTREAM_DOWN,
    EVENT_UPSTREAM_RESTORED,
    EVENT_RECOVERED,
    EVENT_WITHDRAWN,
    LOGGER,
    RECOVERY_BY_INTERVENTION,
    RECOVERY_BY_SELF,
    RECOVERY_BY_UNKNOWN,
    RECOVERY_CAUSES_INTERVENTION,
    RECOVERY_CAUSES_RESTART,
    RECOVERY_CAUSES_SELF,
    TODO_KIND_SEVERITY,
    UNASSIGNED_AREA,
)
from .normalise import SPAN_HIGHEST


# Recoveries held inside the startup grace, kept in the stored file so
# a reload or restart inside it does not lose them (rule WATCH-10).
DATA_HELD_RECOVERIES = "held_recoveries"

_TEXT_FIELDS = ("device_id", "name", "area", "kind", "resolved_by")


def _sound_recovery(payload: Any) -> bool:
    """Whether a stored held recovery has the shape `fire_recovered`
    gives it, with values held to what is possible (rule STOR-07)."""
    if not isinstance(payload, dict) or set(payload) != {*_TEXT_FIELDS, "down_for"}:
        return False
    if not all(isinstance(payload[f], str) and payload[f] for f in _TEXT_FIELDS):
        return False
    down_for = payload["down_for"]
    if down_for is None:
        return True
    return (
        isinstance(down_for, int)
        and not isinstance(down_for, bool)
        and 0 <= down_for <= SPAN_HIGHEST
    )


@callback
def sort_kinds(kinds) -> list[str]:
    """Return a device's kinds worst first (rule NOTE-12).

    kinds[0] is the headline, so an automation can read the worst
    thing wrong with a device without writing a template. Unavailable
    leads because FREEZE_CATEGORY_PRIORITY already puts it above
    frozen, and this order agrees with it.

    A kind this release has never heard of sorts last rather than
    first. A record written by a later version should not be able to
    make its unknown kind the headline of an older one.
    """
    order = {kind: index for index, kind in enumerate(TODO_KIND_SEVERITY)}
    return sorted(kinds, key=lambda kind: order.get(kind, len(order)))


@callback
def resolved_by(cause: str | None) -> str:
    """Say how a silence ended, and say unknown when it is unknown.

    The incident carries a few cause values in practice. A person's
    own act, handling the device, is an intervention; a restart or an
    outage is not, and a recovery after one is the device recovering
    by itself, as is a recorded absence of any intervention (rule
    BRIEF-05); and a null is two different things wearing one value, a
    battery or a rail that has no lever to name and a silence whose
    episode fell outside the slack.

    Those nulls become unknown rather than being guessed into self
    (rule NOTE-12). An automation that resumes trusting a device on a
    self-recovery must not be told self when the truth is that nobody
    knows.
    """
    if cause in RECOVERY_CAUSES_INTERVENTION:
        return RECOVERY_BY_INTERVENTION
    if cause in RECOVERY_CAUSES_SELF or cause in RECOVERY_CAUSES_RESTART:
        return RECOVERY_BY_SELF
    return RECOVERY_BY_UNKNOWN


class EventMixin:
    """Fire the bus events. Mixed into the coordinator."""

    hass: HomeAssistant
    # Recoveries that happened inside the startup grace, waiting for it
    # to close (rule WATCH-10). Set per coordinator in its __init__.
    _held_recoveries: list[dict[str, Any]]

    @callback
    def _area_of(self, device_id: str) -> str:
        """The device's area, or the word the reports already use.

        Unassigned rather than None, because a template joining a null
        into a message renders the word None at a person, and the
        reports have said Unassigned for as long as they have existed.
        An automation tests for the word rather than for a null.
        """
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id)
        if device is None or device.area_id is None:
            return UNASSIGNED_AREA
        from homeassistant.helpers import area_registry as ar

        area = ar.async_get(self.hass).async_get_area(device.area_id)
        return area.name if area is not None else UNASSIGNED_AREA

    @callback
    def fire_fault(
        self,
        device_id: str,
        name: str,
        kinds,
        since: str,
        *,
        renewed: bool = False,
        level: float | None = None,
        battery_type: str | None = None,
        signal_value: float | None = None,
    ) -> None:
        """One event for a device, after its kind map has settled.

        Not one per kind. _journal_addition runs once for every kind
        that arrives, so firing there would give a device landing with
        two faults two events, the multi-fault collapse undone on the
        bus while it holds on the screen.

        A device that gains a second fault later fires again with the
        fuller list, because the new fault is news. The wiki page says
        so: an automation acting on every fault acts twice on such a
        device, and one gating on the headline changing does not.

        The battery and signal fields are present only when a kind
        that needs them is on the line, so an automation can read
        them without checking whether they mean anything.
        """
        ordered = sort_kinds(kinds)
        if not ordered:
            return
        payload: dict[str, Any] = {
            "device_id": device_id,
            "name": name,
            "area": self._area_of(device_id),
            "kinds": ordered,
            "since": since,
            "renewed": renewed,
        }
        if level is not None and any(
            kind.endswith("battery") for kind in ordered
        ):
            payload["battery_level"] = level
        if battery_type is None and any(kind.endswith("battery") for kind in ordered):
            # What powers it, beside a battery fault only.
            battery_type = self.power_text(device_id)  # type: ignore[attr-defined]
        if battery_type is not None:
            payload["battery_type"] = battery_type
        if signal_value is not None:
            payload["signal_value"] = signal_value
        self._fire(EVENT_FAULT, payload)

    @callback
    def fire_recovered(
        self,
        device_id: str,
        name: str,
        kind: str,
        down_for: float | None,
        cause: str | None,
    ) -> None:
        """One event when the worst kind on a line clears.

        Fired for whatever is highest on the line at the moment it
        goes. When it goes the next kind becomes the highest and
        fires in turn when it leaves, so every kind that landed is
        answered by exactly one recovery, worst first.

        The consequence is worth stating rather than hiding: this
        does not mean the device is well. It means the worst thing is
        no longer wrong, and a device can fire it while still on the
        list with a low cell. That is the right reading for the trust
        automations this exists for, since a device reporting again is
        trustworthy whether or not its battery is low.
        """
        self._fire(
            EVENT_RECOVERED,
            {
                "device_id": device_id,
                "name": name,
                "area": self._area_of(device_id),
                "kind": kind,
                "down_for": (
                    None if down_for is None else round(down_for)
                ),
                "resolved_by": resolved_by(cause),
            },
        )

    @callback
    def fire_withdrawn(
        self, device_id: str, name: str, kinds, reason: str
    ) -> None:
        """One event when a line leaves without a recovery.

        The device was set aside, so nobody watches it, or a person
        muted it, which is their own act and leaves silently (rule
        LIST-09); the reason says which. Not a recovery:
        the device did not come back. An automation that paired a fault
        with this line gets its closing event here, carrying every kind
        the line held, and never hears "recovered" for a device that
        was never away.
        """
        self._fire(
            EVENT_WITHDRAWN,
            {
                "device_id": device_id,
                "name": name,
                "area": self._area_of(device_id),
                "kinds": list(kinds),
                "reason": reason,
            },
        )

    @callback
    def fire_upstream_down(
        self, kind: str, name: str, since: str, devices: int,
        confirmed: int | None = None,
    ) -> None:
        """One event when the thing carrying a house's devices stops.

        A stopped broker or bridge silences every device behind it
        deliberately: they are reported as the upstream rather than
        as themselves, and they get no incident, no event and no
        journal line of their own (rule UP-05). Without this event the
        one failure that takes a house quiet is the one failure an
        automation cannot see.

        `devices` is what makes it actionable. Without it every
        outage looks alike on the bus, and a bridge carrying two
        devices reads the same as one carrying seventy-six.
        """
        payload = {
            "kind": kind,
            "name": name,
            "since": since,
            "devices": devices,
        }
        # Evidence, present only where a kind produces it (the Wi-Fi
        # outage): how many claimed devices
        # already read unavailable at declaration. The contract's
        # four fields are untouched; a field that is absent for
        # every other kind amends nothing.
        if confirmed is not None:
            payload["confirmed"] = confirmed
        self._fire(EVENT_UPSTREAM_DOWN, payload)

    @callback
    def fire_upstream_restored(
        self, kind: str, name: str, since: str, devices: int,
        for_seconds: float,
        owed: bool = False,
    ) -> None:
        """The closing half of the pair.

        Fired on the transition rather than on the state, so a
        restart that comes up with an upstream already down does not
        announce a recovery that never happened (rule UP-04).
        """
        self._fire(
            EVENT_UPSTREAM_RESTORED,
            {
                "kind": kind,
                "name": name,
                "since": since,
                "devices": devices,
                "for_seconds": round(float(for_seconds), 1),
            },
            owed=owed,
        )

    @callback
    def fire_acknowledged(
        self, device_id: str, name: str, kinds
    ) -> None:
        """One event when a person ticks the item.

        Unticking has no event of its own: it is already the soft
        un-acknowledge, and the next sync re-adds and re-announces, so
        the fault fires again carrying renewed. An automation
        therefore needs no knowledge of acknowledgment at all. It
        reacts to faults; ticking silences the re-announcement and
        unticking restores it, which is what the checkbox means
        everywhere else in this project.
        """
        ordered = sort_kinds(kinds)
        if not ordered:
            return
        self._fire(
            EVENT_ACKNOWLEDGED,
            {
                "device_id": device_id,
                "name": name,
                "area": self._area_of(device_id),
                "kinds": ordered,
            },
        )

    @callback
    def _fire(
        self, event_type: str, payload: dict[str, Any], owed: bool = False
    ) -> None:
        """Put one event on the bus, and never raise into the sync.

        The sync is the path that keeps the list, the reports and the
        storage correct, so a bus that refuses must not cost a person
        their storage write. The failure is logged and the sync
        carries on.

        A badly written automation is not this guard's doing and the
        docstring should not claim it: Home Assistant dispatches
        listeners away from the caller, so a listener that throws can
        never reach here. What this covers is the narrower case the
        integration is responsible for, the fire call failing on its
        own account.
        """
        # A withdrawal is a fact about the house, not an echo of the
        # restart: a device removed or set aside while Home Assistant was
        # stopped closes the fault an automation paired it with, so it is
        # fired inside the startup grace too.
        # So is a recovery owed to a down announced before the restart:
        # the automation that heard the down is waiting for it.
        if self._in_startup_grace() and event_type != EVENT_WITHDRAWN and not owed:
            # A device that really reported inside the grace has already
            # left its verdict; its recovery is kept and fired when the
            # grace closes, so an automation that heard the fault still
            # hears it end (rule WATCH-10).
            if event_type == EVENT_RECOVERED:
                self._held_recoveries.append(payload)
                # Kept in the stored file too, saved at once, so a
                # reload or restart inside the grace does not lose it
                # (rules WATCH-10, LIST-08).
                self.data[DATA_HELD_RECOVERIES] = list(self._held_recoveries)  # type: ignore[attr-defined]
                self._dirty = True
                self._critical = True
            return
        # Anything fired after the grace goes behind the recoveries held
        # inside it, so the bus keeps the order things happened in; a
        # withdrawal or an owed restored inside the grace leaves them
        # held (rule WATCH-10).
        if not self._in_startup_grace():
            self._release_held_recoveries()
        self._send(event_type, payload)

    @callback
    def _release_held_recoveries(self) -> None:
        """Fire the recoveries held inside the startup grace, once each.

        Called when the grace closes, and before any later event, so
        whichever comes first sends them and the other finds nothing
        left (rule WATCH-10).
        """
        held, self._held_recoveries = self._held_recoveries, []
        if not held and DATA_HELD_RECOVERIES not in self.data:  # type: ignore[attr-defined]
            return
        # Cleared from the stored file and saved at once, so a restart
        # after this never sends them a second time (rule WATCH-10).
        self.data.pop(DATA_HELD_RECOVERIES, None)  # type: ignore[attr-defined]
        self._dirty = True
        self._critical = True
        self.hass.async_create_task(self._save_now())  # type: ignore[attr-defined]
        for payload in held:
            self._send(EVENT_RECOVERED, payload)

    @callback
    def _restore_held_recoveries(self) -> None:
        """Take back, at a start, the recoveries a reload or restart
        inside the last grace left held, to be sent when this run's
        grace closes (rule WATCH-10).

        Each one is checked as stored: anything that is not a recovery
        as `fire_recovered` builds it is dropped without an exception,
        and nothing is sent for it (rule STOR-07).
        """
        stored = self.data.get(DATA_HELD_RECOVERIES)  # type: ignore[attr-defined]
        kept = [
            payload for payload in (stored if isinstance(stored, list) else [])
            if _sound_recovery(payload)
        ]
        self._held_recoveries = kept
        if kept:
            if kept != stored:
                self.data[DATA_HELD_RECOVERIES] = list(kept)  # type: ignore[attr-defined]
                self._dirty = True
        elif stored is not None:
            self.data.pop(DATA_HELD_RECOVERIES, None)  # type: ignore[attr-defined]
            self._dirty = True

    @callback
    def _send(self, event_type: str, payload: dict[str, Any]) -> None:
        """Fire one event, logging rather than raising on a failure."""
        try:
            self.hass.bus.async_fire(event_type, payload)
        except Exception:  # noqa: BLE001 - never break the sync
            LOGGER.exception(
                "Could not fire %s for %s", event_type, payload.get("name")
            )
