# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_actions.py, Version: 0.30.2 (2026-11-22)

"""Acting from the device page (rule DASH-09).

A person looking at a device in trouble can rename it, place it, label
it, give it a better clock, mute it or exclude it without leaving the
page. Names, areas and labels are written to Home Assistant's device
registry, so they stay Home Assistant's and are read back as every
other registry change is. A mute is written to Device Sentinel's own
options, the same ones Settings writes, through the same update
listener, so everything that reacts to a mute reacts the same way.

Every act rebuilds Device Sentinel's view at once, so the page shows
what was done even inside the registry debouncer's two seconds, and
records one row in the brief, on the device's own line, with where it
was pressed: "from its device page", or "from the Recommendations
tab" for an act pressed on a card there. The options a page mute
writes are left out of the "Settings changed" row, so one act makes
one row (rule BRIEF-07).
"""

from __future__ import annotations

import unicodedata

from collections.abc import Callable
import re
from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from .const import (
    CONF_UNAVAILABLE_MUTED_LABELS,
    LOGGER,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    SYS_DEVICE_PAGE,
    SYS_INTEGRATION_PAGE,
    SYS_INTEGRATIONS_TAB,
    SYS_RECOMMENDATIONS_TAB,
)
from .device_fields import area_name_of, child_devices, parent_device, parent_name_part, update_device
from .stacks import is_hub_link
from .naming import cannot_be_told_apart, composed_name, display_name, with_parent, without_parent

# What a "Turn it on" switches on, as the brief's row names it
# (rule DASH-09). Last Seen and the Z-Wave status are apart, each with
# its own card (rule REC-05).
TURN_ON_WORDS = {
    "last_seen": "Last Seen",
    "node_status": "Z-Wave status",
    "battery": "Battery sensor",
    "signal": "Signal sensor",
    "voltage": "Battery voltage sensor",
    "firmware": "Firmware update check",
    # A Lightwave hub's own link (rule STACK-17).
    "hub_link": "Cloud Link",
}

# Each mute kind's three settings lists, in the order every mute is
# read: the integration, the device's labels, the device itself.
# Where a mute was pressed, in the words the brief prints, because the
# Slow Reporting Devices card and the Problem List call the same action
# as the device page (rule BRIEF-07).
MUTE_SOURCES_SAID: dict[str, str] = {
    "device_page": "from its device page",
    "recommendations": "from the Recommendations tab",
    "problem_list": "from the Problem List",
    # The Devices tab's Excluded list (rule DASH-12), and a "Not Set" set
    # from a tab's list (rule DASH-04).
    "devices_tab": "from the Devices tab",
    "battery_trends": "from the Battery Trends tab",
    "classification": "from the Classification tab",
    # A network's Status Sensors and Settings (rule DASH-17).
    "network_page": "from the Networks tab",
}

MUTE_KINDS: dict[str, tuple[str, str, str]] = {
    "everything": (CONF_MUTED_INTEGRATIONS, CONF_MUTED_LABELS, CONF_MUTED_DEVICES),
    "freeze": (CONF_FREEZE_MUTED_INTEGRATIONS, CONF_FREEZE_MUTED_LABELS, CONF_FREEZE_MUTED_DEVICES),
    "battery": (CONF_BATTERY_MUTED_INTEGRATIONS, CONF_BATTERY_MUTED_LABELS, CONF_BATTERY_MUTED_DEVICES),
    "signal": (CONF_SIGNAL_MUTED_INTEGRATIONS, CONF_SIGNAL_MUTED_LABELS, CONF_SIGNAL_MUTED_DEVICES),
    # By label or device, never integration, so the integration key is
    # empty and never set (rule MUTE-06).
    "unavailable": ("", CONF_UNAVAILABLE_MUTED_LABELS, CONF_UNAVAILABLE_MUTED_DEVICES),
}


class NameInUse(Exception):
    """Another device already shows this name; the page asks first."""

    def __init__(self, name: str, area: str | None) -> None:
        super().__init__(name)
        self.name = name
        self.area = area


def _is_update(ent: Any) -> bool:
    """A firmware update entity: Home Assistant's update domain, never a
    beta channel's, such as a first-generation Shelly's second one."""
    entity_id = getattr(ent, "entity_id", "")
    if not isinstance(entity_id, str) or not entity_id.startswith("update."):
        return False
    # A beta channel by Home Assistant's own marks, never by a name a
    # person gave: "beta" as a word of the unique id or translation key.
    marks = (str(getattr(ent, "unique_id", "") or ""), str(getattr(ent, "translation_key", "") or ""))
    return not any(re.search(r"(^|[._\-])beta($|[._\-])", mark.lower()) for mark in marks)


def _is_voltage(ent: Any) -> bool:
    """A voltage sensor of the device's own: on a battery device, its
    battery voltage."""
    return (
        str(ent.device_class or ent.original_device_class) == "voltage"
        and ent.entity_id.startswith("sensor.")
    )


def _and_list(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


class DeviceActionsMixin:
    """The device page's six actions. Mixed into the coordinator."""

    hass: Any
    entry: Any
    _watched: dict[str, str]
    _page_option_keys: set[str]

    # ------------------------------------------------------------ reading

    def label_meaning(self, label_id: str) -> str:
        """What Device Sentinel does with a label, in the page's words:
        "mutes freeze and battery", "mutes everything", or empty."""
        options = self.entry.options
        if label_id in options.get(CONF_MUTED_LABELS, []):
            return "mutes everything"
        kinds = [
            kind for kind in ("freeze", "unavailable", "battery", "signal")
            if label_id in options.get(MUTE_KINDS[kind][1], [])
        ]
        return f"mutes {_and_list(kinds)}" if kinds else ""

    def page_mutes(self, device_id: str) -> dict[str, dict[str, Any]]:
        """Each mute kind's state on a device and where it comes from.

        The source is the one the reports name (`_mute_source`, the
        ladder every mute uses), so the page cannot disagree with
        the Devices tab. "here" is whether the device is on the kind's own
        list, whatever else also mutes it, since that is what its button
        lifts; one from a label, an integration or a hub is lifted where
        it was set (rule MUTE-09). "labels" holds the ids of the labels
        the mute comes from, so the page lights each one by its id: a
        label's name may hold any punctuation, a comma included, and
        reading names back out of the source text would split it.
        """
        options = self.entry.options
        found: dict[str, dict[str, Any]] = {}
        for kind, (integrations, labels, devices) in MUTE_KINDS.items():
            source = self._mute_source(  # type: ignore[attr-defined]
                device_id,
                options.get(integrations, []),
                options.get(labels, []),
                options.get(devices, []),
            )
            from_labels = (
                sorted(
                    self._device_labels.get(device_id, frozenset())  # type: ignore[attr-defined]
                    & set(options.get(labels, []))
                )
                if isinstance(source, str) and source.startswith("label: ")
                else []
            )
            found[kind] = {
                "on": source is not None,
                "source": source,
                "here": device_id in options.get(devices, []),
                "labels": from_labels,
            }
        return found

    def page_actions(self, device_id: str) -> dict[str, Any] | None:
        """What the page needs to offer its actions, or None for a device
        the registry no longer has."""
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return None
        labels = lr.async_get(self.hass)
        shown = []
        for label_id in sorted(device.labels or ()):
            entry = labels.async_get_label(label_id)
            shown.append({
                "id": label_id,
                "name": entry.name if entry else label_id,
                "meaning": self.label_meaning(label_id),
            })
        shown.sort(key=lambda item: item["name"].casefold())
        # A child device's "No area" puts it in its parent's area, so the
        # page names the parent and that area, whether the child is in it
        # now or has an area of its own (rule DEV-18).
        registry = dr.async_get(self.hass)
        parent = parent_device(registry, device)
        area_from = (
            (parent.name_by_user or parent.name or None)
            if parent is not None and getattr(parent, "area_id", None)
            else None
        )
        return {
            "area_id": device.area_id,
            "area_from": area_from,
            "area_from_area": area_name_of(self.hass, parent) if area_from else None,
            "name_by_user": device.name_by_user,
            "integration_name": device.name,
            "labels": shown,
            "last_seen_off": self._switched_off_last_seen(device_id) is not None,
            # The Battery and Signal sensor rows' "Turn it on"
            # (rule DASH-09).
            "battery_off": self.switched_off(device_id, "battery") is not None,
            "signal_off": self.switched_off(device_id, "signal") is not None,
            "mutes": self.page_mutes(device_id),
            "excluded": self.page_excluded(device_id),
            # The After a restart row and its notes (rule WATCH-12).
            "restart": self.page_restart(device_id),  # type: ignore[attr-defined]
        }

    def page_excluded(self, device_id: str) -> dict[str, bool]:
        """Whether the device is excluded on its own, and whether its
        integration is (rule MUTE-03). Only its own can be lifted here."""
        own = device_id in self.excluded_devices  # type: ignore[attr-defined]
        domain = None
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            try:
                domain = self._primary_domain(device)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - another integration's data
                domain = None
        return {
            "here": own,
            "integration": domain is not None and domain in self.excluded_integrations,  # type: ignore[attr-defined]
        }

    def page_choices(self) -> dict[str, list[dict[str, Any]]]:
        """The areas and labels a picker offers, fetched when it opens."""
        areas = [
            {"id": area.id, "name": area.name}
            for area in ar.async_get(self.hass).async_list_areas()
        ]
        # Each label with what Device Sentinel does with it (rule MUTE-09).
        labels = [
            {
                "id": label.label_id,
                "name": label.name,
                "meaning": self.label_meaning(label.label_id),
            }
            for label in lr.async_get(self.hass).async_list_labels()
        ]
        areas.sort(key=lambda item: item["name"].casefold())
        labels.sort(key=lambda item: item["name"].casefold())
        return {"areas": areas, "labels": labels}

    def _own_entities_of(self, device_id: str, kind: str) -> list[Any]:
        """The device's own registry entries of one kind (rule REC-05).

        Own means the integration that owns the device wrote them: a
        battery sensor Battery Notes adds, or any other integration's
        entity on the device, never counts (rule WATCH-02).
        """
        from homeassistant.helpers import entity_registry as er

        domain = self._watched.get(device_id)  # type: ignore[attr-defined]
        if domain is None:
            return []
        matches = {
            "last_seen": self._is_last_seen,  # type: ignore[attr-defined]
            "node_status": self._is_node_status_entry,  # type: ignore[attr-defined]
            "battery": self._is_battery_percentage,  # type: ignore[attr-defined]
            "signal": self._is_signal,  # type: ignore[attr-defined]
            "voltage": _is_voltage,
            # Home Assistant's firmware update entity (rule REC-05).
            "firmware": _is_update,
            # A hub's own link sensor, as a Lightwave hub's Cloud Link
            # (rule STACK-17).
            "hub_link": lambda ent: is_hub_link(domain, ent),
        }[kind]
        return [
            ent
            for ent in er.async_entries_for_device(
                er.async_get(self.hass), device_id, include_disabled_entities=True
            )
            if ent.platform == domain and matches(ent)
        ]

    def switched_off(self, device_id: str, kind: str) -> str | None:
        """Whether a watched device's kind is switched off (rule REC-05).

        "user" when a person switched off every one of its own entities
        of that kind, "other" when Home Assistant or the integration did,
        None when one of them is on or it has none. A device with one
        entity of the kind on and another off reports that kind already,
        so it is not listed: a ZHA device with its RSSI on and its LQI
        off has a signal.
        """
        from homeassistant.helpers import entity_registry as er

        own = self._own_entities_of(device_id, kind)
        if not own or any(ent.disabled_by is None for ent in own):
            return None
        if all(ent.disabled_by is er.RegistryEntryDisabler.USER for ent in own):
            return "user"
        return "other"

    def switched_off_devices(self, kind: str) -> dict[str, str]:
        """Every watched device whose kind is switched off, with who did it."""
        found: dict[str, str] = {}
        for device_id in list(self._watched):  # type: ignore[attr-defined]
            who = self.switched_off(device_id, kind)
            if who is not None:
                found[device_id] = who
        return found

    def _switched_off_last_seen(self, device_id: str) -> str | None:
        """The device's switched-off Last Seen entity, if its Last Seen
        is switched off (rule REC-05)."""
        if self.switched_off(device_id, "last_seen") is None:
            return None
        own = self._own_entities_of(device_id, "last_seen")
        return str(own[0].entity_id) if own else None

    def _switched_off_node_status(self, device_id: str) -> bool:
        """Whether the device's node status sensor is switched off (rule DASH-09)."""
        from homeassistant.helpers import entity_registry as er

        entity_id = self._node_status_entity.get(device_id)  # type: ignore[attr-defined]
        if entity_id is None:
            return False
        entry = er.async_get(self.hass).async_get(entity_id)
        return entry is not None and entry.disabled_by is not None

    def _name_in_use(self, device_id: str, name: str) -> NameInUse | None:
        """Another device this one could not be told apart from under the
        name: the same name, without regard to capitals, in the same
        area, or either with no area (rule REC-04). A device of the same
        name in an area of its own is told apart by it, as Home Assistant
        tells them apart."""
        registry = dr.async_get(self.hass)
        device = registry.async_get(device_id)
        # A child device is shown after its parent, so its new name is
        # compared whole, as it will be shown (rule DEV-18).
        wanted = with_parent(name.strip(), parent_name_part(registry, device))
        return self._shown_in_use(device_id, wanted, area_name_of(self.hass, device))

    def _all_devices(self) -> list[Any]:
        """Every device and child device, walked per config entry as the
        rest of the code walks them: reading the registry as a mapping is
        deprecated."""
        registry = dr.async_get(self.hass)
        found: dict[str, Any] = {}
        for config_entry in self.hass.config_entries.async_entries():
            for other in (
                *dr.async_entries_for_config_entry(registry, config_entry.entry_id),
                *child_devices(registry, config_entry.entry_id),
            ):
                found.setdefault(other.id, other)
        return list(found.values())

    def _shown_in_use(
        self, device_id: str, wanted: str, here: str | None, skip: set[str] | frozenset[str] = frozenset()
    ) -> NameInUse | None:
        """Another device that `wanted`, shown in the area `here`, could
        not be told apart from (rule REC-04). `skip` names devices whose
        own names change in the same act, such as a parent's children."""
        registry = dr.async_get(self.hass)
        for other in self._all_devices():
            if other.id == device_id or other.id in skip:
                continue
            # Compared whole, never cut to the length a surface shows.
            shown = composed_name(other, registry) or display_name(other, None, other.id, registry)
            there = area_name_of(self.hass, other)
            # Either way round: a device with no area left beside a
            # same-named one could no longer be told apart from it.
            if cannot_be_told_apart(wanted, here, shown, there) or cannot_be_told_apart(shown, there, wanted, here):
                return NameInUse(shown, there)
        return None

    def _children_of(self, device: Any) -> list[Any]:
        """The child devices shown under this device's name: those with
        no area of their own (rule DEV-18)."""
        registry = dr.async_get(self.hass)
        return [
            other for other in self._all_devices()
            if getattr(other, "parent_device_id", None) == device.id and parent_name_part(registry, other)
        ]

    @staticmethod
    def _own_name(device: Any) -> str:
        """The name a device carries before any parent's is put in front."""
        for value in (getattr(device, "name_by_user", None), getattr(device, "name", None)):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _move_in_use(self, device_id: str, area_name: str | None, area_id: str | None) -> NameInUse | None:
        """A clash the move to an area would make (rules REC-04, DASH-10).

        The device is compared as it will be shown there: a child moved
        into an area of its own loses its parent's name, and one left
        with none is shown with its parent's name in its parent's area.
        A parent's children with no area of their own move with it.
        """
        registry = dr.async_get(self.hass)
        device = self._device(device_id)
        own = self._own_name(device)
        parent = parent_device(registry, device)
        if area_id is None and parent is not None:
            shown, here = with_parent(own, self._own_name(parent) or None), area_name_of(self.hass, parent)
        else:
            shown, here = own, area_name
        children = self._children_of(device)
        moving = {child.id for child in children} | {device_id}
        if shown:
            # Its own children move with it: a name they already share
            # with it is not one the move makes.
            clash = self._shown_in_use(device_id, shown, here, moving)
            if clash is not None:
                return clash
        for child in children:
            shown = with_parent(self._own_name(child), own or None)
            # A child with no area of its own is in its parent's.
            clash = self._shown_in_use(child.id, shown, here, moving)
            if clash is not None:
                return clash
        return None

    # ------------------------------------------------------------ acting

    def _device(self, device_id: str) -> Any:
        # A device entry, or a child entry on newer Home Assistant.
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            raise KeyError(device_id)
        return device

    # Where the act running now was pressed, set by `page_from` for the
    # length of one act.
    _page_source: str = "device_page"

    def page_from(self, source: str, act: Callable[[], Any]) -> Any:
        """Run one act, recorded as pressed where `source` says.

        A sensor turned on, a power answer, a type, an area or a name set
        from a Recommendations card or a tab's "Not Set" is recorded with
        where it was pressed, as a mute is (rules BRIEF-07, DEV-07).
        """
        self._page_source = source
        try:
            return act()
        finally:
            self._page_source = "device_page"

    def _page_done(self, device_id: str, what: str) -> None:
        """Show the act at once and record it, once, on the device's line,
        with where it was pressed (rule BRIEF-07)."""
        self._rebuild_registry_view()  # type: ignore[attr-defined]
        where = MUTE_SOURCES_SAID.get(self._page_source, MUTE_SOURCES_SAID["device_page"])
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_DEVICE_PAGE, detail=f"{what}, {where}", device_id=device_id
        )
        self._mark_changed()  # type: ignore[attr-defined]

    def page_rename(self, device_id: str, name: str | None, confirm: bool = False) -> None:
        """Set the name a person gives the device; empty resets it to the
        integration's. A name another device shows is held for a yes."""
        device = self._device(device_id)
        wanted = (name or "").strip() or None
        if wanted is not None and any(
            unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in wanted
        ):
            # A NUL or a direction-flipping mark would reach the
            # registry, and from there the brief and notifications. The
            # same refusal as the Power row's own words (rule DEV-05).
            raise ValueError("That text holds characters that cannot be shown.")
        if wanted is not None:
            # A child device keeps its own name; Home Assistant adds its
            # parent's (rule DEV-18).
            wanted = without_parent(wanted, parent_name_part(dr.async_get(self.hass), device)) or wanted
        shown = wanted or device.name or ""
        if not confirm and shown:
            clash = self._name_in_use(device_id, shown)
            if clash is None:
                # A parent's children with no area of their own are shown
                # after its name, so each is checked under the new one
                # (rules REC-04, DEV-18).
                children = self._children_of(device)
                moving = {child.id for child in children}
                for child in children:
                    clash = self._shown_in_use(
                        child.id, with_parent(self._own_name(child), shown), area_name_of(self.hass, child), moving
                    )
                    if clash is not None:
                        break
            if clash is not None:
                raise clash
        update_device(self.hass, device_id, name_by_user=wanted)
        self._page_done(
            device_id,
            f"renamed {shown}" if wanted else f"name reset to {shown}",
        )

    def page_set_area(self, device_id: str, area_id: str | None, confirm: bool = False) -> None:
        """Move a device to an area, or to none. A move that would leave it
        beside a device it could not be told apart from is held for a
        yes, as a rename is (rules REC-04, DASH-10)."""
        self._device(device_id)
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        if area_id and area is None:
            raise ValueError("Home Assistant has no such area")
        if not confirm:
            clash = self._move_in_use(device_id, area.name if area else None, area_id or None)
            if clash is not None:
                raise clash
        update_device(self.hass, device_id, area_id=area_id or None)
        if area is None:
            # A child device with no area is in its parent's, and the
            # brief says so rather than "area removed" (rule DEV-18).
            inherited = area_name_of(self.hass, self._device(device_id))
            self._page_done(device_id, f"set to its parent's area, {inherited}" if inherited else "area removed")
            return
        self._page_done(device_id, f"moved to {area.name}")

    @staticmethod
    def _new_registry_name(name: str | None) -> str:
        """A name for a new area or label, or a refusal saying why.

        Held to the rename's rule: accents and emoji are welcome,
        hidden and control characters are not, since the name goes on
        to the brief, the Problem List and notifications (rule DEV-05).
        """
        wanted = (name or "").strip()
        if not wanted:
            raise ValueError("Give it a name.")
        if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in wanted):
            raise ValueError("That text holds characters that cannot be shown.")
        return wanted

    def page_new_area(self, device_id: str, name: str | None, confirm: bool = False) -> None:
        """Make an area and move the device into it (rule DASH-09).

        A name Home Assistant already holds is the area it names, not a
        second area of the same name, which Home Assistant would refuse.
        """
        self._device(device_id)
        wanted = self._new_registry_name(name)
        areas = ar.async_get(self.hass)
        held = areas.async_get_area_by_name(wanted)
        if not confirm:
            # Checked before the area is made, so a held move leaves no
            # empty area behind (rules REC-04, DASH-10).
            clash = self._move_in_use(device_id, held.name if held is not None else wanted, held.id if held else "new")
            if clash is not None:
                raise clash
        area = held if held is not None else areas.async_create(wanted)
        update_device(self.hass, device_id, area_id=area.id)
        self._page_done(device_id, f"moved to {area.name}{'' if held else ', a new area'}")

    def page_new_label(self, device_id: str, name: str | None) -> None:
        """Make a label and put it on the device (rule DASH-09).

        As with an area, a name Home Assistant already holds is that
        label.
        """
        device = self._device(device_id)
        wanted = self._new_registry_name(name)
        labels_reg = lr.async_get(self.hass)
        held = labels_reg.async_get_label_by_name(wanted)
        label = held if held is not None else labels_reg.async_create(wanted)
        update_device(self.hass, device_id, labels=set(device.labels or ()) | {label.label_id})
        self._page_done(device_id, f"label {label.name} added{'' if held else ', a new label'}")

    def page_label(self, device_id: str, label_id: str, add: bool) -> None:
        device = self._device(device_id)
        label = lr.async_get(self.hass).async_get_label(label_id)
        if label is None:
            raise ValueError("Home Assistant has no such label")
        labels = set(device.labels or ())
        if add:
            labels.add(label_id)
        else:
            labels.discard(label_id)
        update_device(self.hass, device_id, labels=labels)
        self._page_done(device_id, f"label {label.name} {'added' if add else 'removed'}")

    def page_turn_on(self, device_id: str, kind: str) -> int:
        """Switch on one device's own entities of one kind (rule REC-05).

        The one way Device Sentinel switches on another integration's
        entity: one device, one kind, pressed by an administrator on the
        device's page or its Recommendations card. Last Seen and the
        Z-Wave status are separate kinds, each with its own card.
        Returns how many entities were switched on.
        """
        from homeassistant.helpers import entity_registry as er

        self._device(device_id)
        if kind not in TURN_ON_WORDS:
            raise ValueError("Device Sentinel cannot switch that on")
        registry = er.async_get(self.hass)
        enabled = 0
        for ent in self._own_entities_of(device_id, kind):
            if ent.disabled_by is None:
                continue
            registry.async_update_entity(ent.entity_id, disabled_by=None)
            enabled += 1
        if enabled:
            LOGGER.debug(
                "Turned on %d %s entities on %s, from Device Sentinel's dashboard",
                enabled, kind, self._device_name(device_id),  # type: ignore[attr-defined]
            )
            self._page_done(device_id, f"{TURN_ON_WORDS[kind]} turned on")
        return enabled

    def page_set_excluded(
        self, device_id: str, on: bool, source: str = "device_page"
    ) -> None:
        """Exclude the device, or take it back (rule MUTE-03), in the list
        Settings writes beside the integrations, through the same update
        listener. Its record goes at the next midnight's fold, as an
        excluded integration's does, so taking it back before then
        loses nothing."""
        self._device(device_id)
        stored = self.entry.options.get(CONF_EXCLUDED_DEVICES)
        current = [d for d in stored if isinstance(d, str)] if isinstance(stored, (list, tuple)) else []
        if on and device_id not in current:
            current.append(device_id)
        elif not on and device_id in current:
            current.remove(device_id)
        else:
            return
        self._page_option_keys.add(CONF_EXCLUDED_DEVICES)
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_EXCLUDED_DEVICES: current}
        )
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_DEVICE_PAGE,
            detail=f"{'excluded' if on else 'no longer excluded'}, {MUTE_SOURCES_SAID.get(source, MUTE_SOURCES_SAID['device_page'])}",
            device_id=device_id,
        )
        self._mark_changed()  # type: ignore[attr-defined]

    def page_set_integration_excluded(
        self, domain: str, on: bool, source: str = "integration_page"
    ) -> None:
        """Exclude an integration, or take it back, from its page, the
        Integrations tab or its card on the Recommendations tab (rule
        MUTE-03), in the list Settings writes,
        through the same update listener. Its mutes, and its devices'
        own, are kept, as a device's are when it is excluded, so a
        second press before midnight loses nothing; a Settings save
        settles them (rule MUTE-04). Its devices' records go at the next
        midnight's fold. One act, one row in the brief."""
        stored = self.entry.options.get(CONF_EXCLUDED_INTEGRATIONS)
        if stored is None:
            # The default list stands until the option is first saved.
            current = list(self.default_exclusions())  # type: ignore[attr-defined]
        elif isinstance(stored, (list, tuple)):
            current = [d for d in stored if isinstance(d, str)]
        else:
            current = []
        if on and domain not in current:
            current.append(domain)
        elif not on and domain in current:
            current.remove(domain)
        else:
            return
        merged = {**self.entry.options, CONF_EXCLUDED_INTEGRATIONS: current}
        self._page_option_keys.add(CONF_EXCLUDED_INTEGRATIONS)
        self.hass.config_entries.async_update_entry(self.entry, options=merged)
        self._record_system_event(  # type: ignore[attr-defined]
            {
                "integrations_tab": SYS_INTEGRATIONS_TAB,
                "recommendations_tab": SYS_RECOMMENDATIONS_TAB,
            }.get(source, SYS_INTEGRATION_PAGE),
            scope=domain,
            detail="excluded" if on else "no longer excluded",
        )
        self._mark_changed()  # type: ignore[attr-defined]

    def page_set_integration_mute(
        self, domain: str, kind: str, on: bool, source: str = "integrations_tab"
    ) -> None:
        """Set or lift one kind's mute on a whole integration, from the
        Integrations tab or the integration's page, in the list Settings
        writes, and the brief names where it was pressed (rule MUTE-03).
        Nothing narrower is cleared, so a second press undoes it exactly;
        a Settings save settles the ladder (rule MUTE-04). Unavailable is
        never muted by integration (rule MUTE-06), and an excluded
        integration is not muted at all."""
        if kind not in MUTE_KINDS or not MUTE_KINDS[kind][0]:
            raise ValueError(f"no integration mute {kind}")
        if on and domain in self.excluded_integrations:  # type: ignore[attr-defined]
            raise ValueError("the integration is excluded")
        key = MUTE_KINDS[kind][0]
        current = [d for d in self.entry.options.get(key, []) or [] if isinstance(d, str)]
        if on and domain not in current:
            current.append(domain)
        elif not on and domain in current:
            current.remove(domain)
        else:
            return
        self._page_option_keys.add(key)
        self.hass.config_entries.async_update_entry(self.entry, options={**self.entry.options, key: current})
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_INTEGRATION_PAGE if source == "integration_page" else SYS_INTEGRATIONS_TAB,
            scope=domain,
            detail=f"muted for {kind}" if on else f"{kind} mute lifted",
        )
        self._mark_changed()  # type: ignore[attr-defined]

    def _mute_words(self, device_id: str, kind: str, on: bool) -> str:
        """What a mute set or lifted on the device page covers, for its
        system event: each mute its own kind."""
        return kind

    def page_set_mute(
        self, device_id: str, kind: str, on: bool, source: str = "device_page"
    ) -> None:
        """Set or lift one kind's mute on the device, in the options
        Settings writes, through the same update listener. The brief's
        line says where it was pressed (rule BRIEF-07)."""
        self._device(device_id)
        if kind not in MUTE_KINDS:
            raise ValueError(f"no mute kind {kind}")
        key = MUTE_KINDS[kind][2]
        current = list(self.entry.options.get(key, []))
        if on and device_id not in current:
            current.append(device_id)
        elif not on and device_id in current:
            current.remove(device_id)
        else:
            return
        # One act, one row: the listener leaves this key out of its
        # "Settings changed" row (rule BRIEF-07).
        self._page_option_keys.add(key)
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, key: current}
        )
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_DEVICE_PAGE,
            detail=f"{self._mute_words(device_id, kind, on)} {'muted' if on else 'unmuted'}, {MUTE_SOURCES_SAID.get(source, MUTE_SOURCES_SAID['device_page'])}",
            device_id=device_id,
        )
        self._mark_changed()  # type: ignore[attr-defined]
