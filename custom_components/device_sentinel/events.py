# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: events.py, Version: 0.15.9 (2026-08-18)

"""What Device Sentinel says on the Home Assistant bus.

Until now the integration only listened. An automation could not react
to a device going frozen except by polling an entity's state, which is
the one thing a monitoring integration ought to make easy.

Every fire call lives here, the same way every Repair call will live in
one place, so the payload shape is decided once rather than in each of
the three modules that has a transition to announce.

Three event types with separate names rather than one type carrying an
action field, because an automation triggers on event_type and a
distinct name is what a person types into the trigger box.

Where they fire is the whole design (ruling #289). A device earns an
event when its line is added to the problem list, when a kind leaves
it, and when a person ticks it. Nowhere else. That boundary already
carries the per-device debounce (#117) and the multi-fault collapse
(#213), so an automation gets the same filtering a person gets: no
thirty-second blips, one event for a device with two faults, and
nothing at all during the startup grace (#291).

What is deliberately absent: an event for a coordinator outage. #264
suppresses the cascade at the problem list itself, so the devices
behind a downed bridge never become rows and nothing fires. A person
watching a coordinator has its own availability entity, which is
simpler and more direct than anything this could offer.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    EVENT_ACKNOWLEDGED,
    EVENT_FAULT,
    EVENT_RECOVERED,
    LOGGER,
    RECOVERY_BY_INTERVENTION,
    RECOVERY_BY_SELF,
    RECOVERY_BY_UNKNOWN,
    RECOVERY_CAUSES_INTERVENTION,
    RECOVERY_CAUSES_SELF,
    TODO_KIND_SEVERITY,
    UNASSIGNED_AREA,
)


@callback
def sort_kinds(kinds) -> list[str]:
    """Return a device's kinds worst first (ruling #289).

    kinds[0] is the headline, so an automation can read the worst
    thing wrong with a device without writing a template. Unavailable
    leads because FREEZE_CATEGORY_PRIORITY already ruled it above
    frozen, and nothing here contradicts a decision already made.

    A kind this release has never heard of sorts last rather than
    first. A record written by a later version should not be able to
    make its unknown kind the headline of an older one.
    """
    order = {kind: index for index, kind in enumerate(TODO_KIND_SEVERITY)}
    return sorted(kinds, key=lambda kind: order.get(kind, len(order)))


@callback
def resolved_by(cause: str | None) -> str:
    """Say how a silence ended, and say unknown when it is unknown.

    The incident carries four cause values in practice. A bridge
    reconnect or a reboot is an intervention; a recorded absence of
    one is the device recovering by itself; and a null is two
    different things wearing one value, a battery or a rail that has
    no lever to name and a silence whose episode fell outside #228's
    slack.

    Those nulls become unknown rather than being guessed into self
    (ruling #291). An automation that resumes trusting a device on a
    self-recovery must not be told self when the truth is that nobody
    knows.
    """
    if cause in RECOVERY_CAUSES_INTERVENTION:
        return RECOVERY_BY_INTERVENTION
    if cause in RECOVERY_CAUSES_SELF:
        return RECOVERY_BY_SELF
    return RECOVERY_BY_UNKNOWN


class EventMixin:
    """Fire the three bus events. Mixed into the coordinator."""

    hass: HomeAssistant

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
        two faults two events, which is #213's collapse undone on the
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
    def _fire(self, event_type: str, payload: dict[str, Any]) -> None:
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
        if self._in_startup_grace():
            return
        try:
            self.hass.bus.async_fire(event_type, payload)
        except Exception:  # noqa: BLE001 - never break the sync
            LOGGER.exception(
                "Could not fire %s for %s", event_type, payload.get("name")
            )
