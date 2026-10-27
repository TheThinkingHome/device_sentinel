# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_actions.py, Version: 0.27.10 (2026-10-27)

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
from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from .const import (
    DATA_EXCLUSION_OFFERS,
    OFFER_CLOSED,
    OFFER_OPEN,
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
)

# What a "Turn it on" switches on, as the brief's row names it
# (rule DASH-09). Last Seen and the Z-Wave status are apart, each with
# its own card (rule REC-05).
TURN_ON_WORDS = {
    "last_seen": "Last Seen",
    "node_status": "Z-Wave status",
    "battery": "Battery sensor",
    "signal": "Signal sensor",
    "voltage": "Battery voltage sensor",
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
    # The Devices tab's Excluded list (rule DASH-12).
    "devices_tab": "from the Devices tab",
}

MUTE_KINDS: dict[str, tuple[str, str, str]] = {
    "everything": (CONF_MUTED_INTEGRATIONS, CONF_MUTED_LABELS, CONF_MUTED_DEVICES),
    "freeze": (CONF_FREEZE_MUTED_INTEGRATIONS, CONF_FREEZE_MUTED_LABELS, CONF_FREEZE_MUTED_DEVICES),
    "battery": (CONF_BATTERY_MUTED_INTEGRATIONS, CONF_BATTERY_MUTED_LABELS, CONF_BATTERY_MUTED_DEVICES),
    "signal": (CONF_SIGNAL_MUTED_INTEGRATIONS, CONF_SIGNAL_MUTED_LABELS, CONF_SIGNAL_MUTED_DEVICES),
    # A device only: no integration or label list, so those two keys
    # are never set.
    # By label or device, never integration (rule MUTE-06).
    "unavailable": ("", CONF_UNAVAILABLE_MUTED_LABELS, CONF_UNAVAILABLE_MUTED_DEVICES),
}


class NameInUse(Exception):
    """Another device already shows this name; the page asks first."""

    def __init__(self, name: str, area: str | None) -> None:
        super().__init__(name)
        self.name = name
        self.area = area


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
        Classification. Only a mute whose source is the device itself
        can be lifted here; one from a label or an integration is lifted
        where it was set.
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
            found[kind] = {
                "on": source is not None,
                "source": source,
                "here": source == "device",
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
        return {
            "area_id": device.area_id,
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
        devices = dr.async_get(self.hass)
        # How many devices carry each label, so the Mute by label picker
        # can say what a label mute reaches before it saves (rule MUTE-09).
        labels = [
            {
                "id": label.label_id,
                "name": label.name,
                "meaning": self.label_meaning(label.label_id),
                "devices": len(dr.async_entries_for_label(devices, label.label_id)),
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
        """Another device already showing this name, ignoring capitals."""
        wanted = name.strip().casefold()
        areas = ar.async_get(self.hass)
        registry = dr.async_get(self.hass)
        seen: set[str] = {device_id}
        # Every device, walked per config entry as the rest of the code
        # walks them: reading the registry as a mapping is deprecated.
        for config_entry in self.hass.config_entries.async_entries():
            for other in dr.async_entries_for_config_entry(registry, config_entry.entry_id):
                if other.id in seen:
                    continue
                seen.add(other.id)
                shown = other.name_by_user or other.name or ""
                if shown.strip().casefold() == wanted:
                    area = areas.async_get_area(other.area_id) if other.area_id else None
                    return NameInUse(shown, area.name if area else None)
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

        A sensor turned on, a power answer or a type set from a
        Recommendations card was recorded "from its device page", the
        only place `_page_done` knew of. The command now says where it
        was pressed, as a mute does, and the record says so (rules
        BRIEF-07, DEV-07).
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
        shown = wanted or device.name or ""
        if not confirm and shown:
            clash = self._name_in_use(device_id, shown)
            if clash is not None:
                raise clash
        dr.async_get(self.hass).async_update_device(device_id, name_by_user=wanted)
        self._page_done(
            device_id,
            f"renamed {shown}" if wanted else f"name reset to {shown}",
        )

    def page_set_area(self, device_id: str, area_id: str | None) -> None:
        self._device(device_id)
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        if area_id and area is None:
            raise ValueError("Home Assistant has no such area")
        dr.async_get(self.hass).async_update_device(device_id, area_id=area_id or None)
        self._page_done(device_id, f"moved to {area.name}" if area else "area removed")

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

    def page_new_area(self, device_id: str, name: str | None) -> None:
        """Make an area and move the device into it (rule DASH-09).

        A name Home Assistant already holds is the area it names, not a
        second area of the same name, which Home Assistant would refuse.
        """
        self._device(device_id)
        wanted = self._new_registry_name(name)
        areas = ar.async_get(self.hass)
        held = areas.async_get_area_by_name(wanted)
        area = held if held is not None else areas.async_create(wanted)
        dr.async_get(self.hass).async_update_device(device_id, area_id=area.id)
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
        dr.async_get(self.hass).async_update_device(
            device_id, labels=set(device.labels or ()) | {label.label_id}
        )
        self._page_done(device_id, f"label {label.name} added{'' if held else ', a new label'}")

    def page_label_mute(
        self, device_id: str, kind: str, label_id: str | None = None, name: str | None = None
    ) -> dict[str, Any]:
        """Mute by label, from the device page, in Advanced (rule MUTE-09).

        One of the person's labels, or a new one by name, goes on the
        device and onto the kind's label list, the list Settings writes,
        so every device carrying it is muted for that kind. Unavailable
        has a label list and no integration list; every kind here has a
        label list.
        """
        device = self._device(device_id)
        if kind not in MUTE_KINDS:
            raise ValueError(f"no mute kind {kind}")
        labels_reg = lr.async_get(self.hass)
        made = False
        if label_id is not None:
            label = labels_reg.async_get_label(label_id)
            if label is None:
                raise ValueError("Home Assistant has no such label")
        else:
            wanted = self._new_registry_name(name)
            label = labels_reg.async_get_label_by_name(wanted)
            if label is None:
                label = labels_reg.async_create(wanted)
                made = True
        if label.label_id not in (device.labels or ()):
            dr.async_get(self.hass).async_update_device(
                device_id, labels=set(device.labels or ()) | {label.label_id}
            )
        key = MUTE_KINDS[kind][1]
        current = list(self.entry.options.get(key, []))
        if label.label_id not in current:
            current.append(label.label_id)
            self._page_option_keys.add(key)
            self.hass.config_entries.async_update_entry(
                self.entry, options={**self.entry.options, key: current}
            )
        reach = len(dr.async_entries_for_label(dr.async_get(self.hass), label.label_id))
        self._page_done(
            device_id,
            f"{kind} muted by label {label.name}{', a new label' if made else ''}, "
            f"on {reach} device{'' if reach == 1 else 's'}",
        )
        return {"label_id": label.label_id, "devices": reach}

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
        dr.async_get(self.hass).async_update_device(device_id, labels=labels)
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

    def page_set_integration_excluded(self, domain: str, on: bool) -> None:
        """Exclude an integration, or take it back, from its page on the
        dashboard (rule MUTE-03), in the list Settings writes, through the
        same update listener. The ladder is settled as a Settings save
        settles it, so its mutes go with an exclusion (rule MUTE-04). Its
        devices' records go at the next midnight's fold, so taking it
        back before then loses nothing. One act, one row in the brief."""
        from .config_flow import settle_options  # the flow imports this module's package

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
        if on:
            merged = settle_options(self.hass, self, merged)
        self._page_option_keys.update(
            key
            for key in set(merged) | set(self.entry.options)
            if merged.get(key) != self.entry.options.get(key)
        )
        self.hass.config_entries.async_update_entry(self.entry, options=merged)
        offers = self.exclusion_offers()  # type: ignore[attr-defined]
        if on and offers.get(domain) == OFFER_OPEN:
            # Its card is answered for good.
            self.data[DATA_EXCLUSION_OFFERS] = {**offers, domain: OFFER_CLOSED}  # type: ignore[attr-defined]
            self._dirty = True  # type: ignore[attr-defined]
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_INTEGRATION_PAGE,
            scope=domain,
            detail="excluded" if on else "no longer excluded",
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
