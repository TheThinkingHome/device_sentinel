# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_actions.py, Version: 0.26.6 (2026-10-18)

"""Acting from the device page (0.24.5, Project__Device_Page_Actions.md).

A person looking at a device in trouble can rename it, place it, label
it, give it a better clock, mute it or exclude it (0.25.6) without
leaving the page. Names,
areas and labels are written to Home Assistant's device registry, so
they stay Home Assistant's and are read back as every other registry
change is. A mute is written to Device Sentinel's own options, the
same ones Settings writes, through the same update listener, so
everything that reacts to a mute reacts the same way.

Every act rebuilds Device Sentinel's view at once, so the page shows
what was done even inside the registry debouncer's two seconds
(0.24.2), and records one row in the brief, on the device's own line,
"from its device page". The options a page mute writes are left out of
the "Settings changed" row, so one act makes one row (ruling #307's
rule for the trim).
"""

from __future__ import annotations

import unicodedata

from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from .const import (
    CONF_UNAVAILABLE_MUTED_LABELS,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    DEFAULT_EXCLUDED_INTEGRATIONS,
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

# Each mute kind's three settings lists, in the order every mute is
# read: the integration, the device's labels, the device itself.
# Where a mute was pressed, in the words the brief prints (ruling
# #643): the Slow Reporting Devices card and the Problem List call the
# same action as the device page, and all three once read "from its
# device page".
MUTE_SOURCES_SAID: dict[str, str] = {
    "device_page": "from its device page",
    "recommendations": "from the Recommendations tab",
    "problem_list": "from the Problem List",
    # The Devices tab's Excluded list (ruling #658).
    "devices_tab": "from the Devices tab",
}

MUTE_KINDS: dict[str, tuple[str, str, str]] = {
    "everything": (CONF_MUTED_INTEGRATIONS, CONF_MUTED_LABELS, CONF_MUTED_DEVICES),
    "freeze": (CONF_FREEZE_MUTED_INTEGRATIONS, CONF_FREEZE_MUTED_LABELS, CONF_FREEZE_MUTED_DEVICES),
    "battery": (CONF_BATTERY_MUTED_INTEGRATIONS, CONF_BATTERY_MUTED_LABELS, CONF_BATTERY_MUTED_DEVICES),
    "signal": (CONF_SIGNAL_MUTED_INTEGRATIONS, CONF_SIGNAL_MUTED_LABELS, CONF_SIGNAL_MUTED_DEVICES),
    # A device only: no integration or label list (James, 17 October
    # 2026), so those two keys are never set.
    # By label or device, never integration (James, 18 October 2026).
    "unavailable": ("", CONF_UNAVAILABLE_MUTED_LABELS, CONF_UNAVAILABLE_MUTED_DEVICES),
}


class NameInUse(Exception):
    """Another device already shows this name; the page asks first."""

    def __init__(self, name: str, area: str | None) -> None:
        super().__init__(name)
        self.name = name
        self.area = area


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
            "mutes": self.page_mutes(device_id),
            "excluded": self.page_excluded(device_id),
        }

    def page_excluded(self, device_id: str) -> dict[str, bool]:
        """Whether the device is excluded on its own, and whether its
        integration is (ruling #625). Only its own can be lifted here."""
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

    def page_choices(self) -> dict[str, list[dict[str, str]]]:
        """The areas and labels a picker offers, fetched when it opens."""
        areas = [
            {"id": area.id, "name": area.name}
            for area in ar.async_get(self.hass).async_list_areas()
        ]
        labels = [
            {"id": label.label_id, "name": label.name, "meaning": self.label_meaning(label.label_id)}
            for label in lr.async_get(self.hass).async_list_labels()
        ]
        areas.sort(key=lambda item: item["name"].casefold())
        labels.sort(key=lambda item: item["name"].casefold())
        return {"areas": areas, "labels": labels}

    def _switched_off_last_seen(self, device_id: str) -> str | None:
        """The device's switched-off Last Seen entity, if it has one."""
        from homeassistant.helpers import entity_registry as er

        for ent in er.async_entries_for_device(
            er.async_get(self.hass), device_id, include_disabled_entities=True
        ):
            if ent.disabled_by is not None and self._is_last_seen(ent):  # type: ignore[attr-defined]
                return str(ent.entity_id)
        return None

    def _switched_off_node_status(self, device_id: str) -> bool:
        """Whether the device's node status sensor is switched off (#671)."""
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

    def _page_done(self, device_id: str, what: str) -> None:
        """Show the act at once and record it, once, on the device's line."""
        self._rebuild_registry_view()  # type: ignore[attr-defined]
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_DEVICE_PAGE, detail=f"{what}, from its device page", device_id=device_id
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
            # A NUL or a direction-flipping mark reached the registry,
            # and from there the brief and notifications (0.24.9). The
            # same refusal as the Power row's own words.
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

        Held to the rename's rule (0.24.9): accents and emoji are
        welcome, hidden and control characters are not, since the name
        goes on to the brief, the Problem List and notifications.
        """
        wanted = (name or "").strip()
        if not wanted:
            raise ValueError("Give it a name.")
        if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn") for ch in wanted):
            raise ValueError("That text holds characters that cannot be shown.")
        return wanted

    def page_new_area(self, device_id: str, name: str | None) -> None:
        """Make an area and move the device into it (0.25.0, Tim Plas).

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
        """Make a label and put it on the device (0.25.0, Tim Plas).

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

    def page_enable_last_seen(self, device_id: str) -> int:
        """Switch on this device's Last Seen entity alone (the house-wide
        Enable, limited to one device), and its node status sensor with
        it (ruling #671)."""
        self._device(device_id)
        last_seen_off = self._switched_off_last_seen(device_id) is not None
        status_off = self._switched_off_node_status(device_id)
        found = self._enable_matching_entities(  # type: ignore[attr-defined]
            self._is_liveness, "last_seen", device_id=device_id  # type: ignore[attr-defined]
        )
        enabled = int(found.get("enabled", 0))
        if enabled:
            # Say what was turned on (adversarial round of 16 October
            # 2026): on a Z-Wave device it may be the status alone.
            status_too = status_off and not self._switched_off_node_status(device_id)
            if last_seen_off and status_too:
                done = "Last Seen and Z-Wave status turned on"
            elif last_seen_off:
                done = "Last Seen turned on"
            else:
                done = "Z-Wave status turned on"
            self._page_done(device_id, done)
        return enabled

    def page_set_excluded(
        self, device_id: str, on: bool, source: str = "device_page"
    ) -> None:
        """Exclude the device, or take it back (ruling #625), in the list
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
        dashboard (ruling #659), in the list Settings writes, through the
        same update listener. The ladder is settled as a Settings save
        settles it (ruling #336), so its mutes go with an exclusion. Its
        devices' records go at the next midnight's fold, so taking it
        back before then loses nothing. One act, one row in the brief."""
        from .config_flow import settle_options  # the flow imports this module's package

        stored = self.entry.options.get(CONF_EXCLUDED_INTEGRATIONS)
        if stored is None:
            # The default list stands until the option is first saved.
            current = list(DEFAULT_EXCLUDED_INTEGRATIONS)
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
        self._record_system_event(  # type: ignore[attr-defined]
            SYS_INTEGRATION_PAGE,
            scope=domain,
            detail="excluded" if on else "no longer excluded",
        )
        self._mark_changed()  # type: ignore[attr-defined]

    def _mute_words(self, device_id: str, kind: str, on: bool) -> str:
        """What a mute set or lifted on the device page covers, for its
        system event: each mute its own kind (James, 18 October 2026)."""
        return kind

    def page_set_mute(
        self, device_id: str, kind: str, on: bool, source: str = "device_page"
    ) -> None:
        """Set or lift one kind's mute on the device, in the options
        Settings writes, through the same update listener. The brief's
        line says where it was pressed (ruling #643)."""
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
        # "Settings changed" row (ruling #307's rule for the trim).
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
