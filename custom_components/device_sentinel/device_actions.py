# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_actions.py, Version: 0.24.5 (2026-10-04)

"""Acting from the device page (0.24.5, Project__Device_Page_Actions.md).

A person looking at a device in trouble can rename it, place it, label
it, give it a better clock or mute it without leaving the page. Names,
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

from typing import Any

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from .const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    SYS_DEVICE_PAGE,
)

# Each mute kind's three settings lists, in the order every mute is
# read: the integration, the device's labels, the device itself.
MUTE_KINDS: dict[str, tuple[str, str, str]] = {
    "everything": (CONF_MUTED_INTEGRATIONS, CONF_MUTED_LABELS, CONF_MUTED_DEVICES),
    "freeze": (CONF_FREEZE_MUTED_INTEGRATIONS, CONF_FREEZE_MUTED_LABELS, CONF_FREEZE_MUTED_DEVICES),
    "battery": (CONF_BATTERY_MUTED_INTEGRATIONS, CONF_BATTERY_MUTED_LABELS, CONF_BATTERY_MUTED_DEVICES),
    "signal": (CONF_SIGNAL_MUTED_INTEGRATIONS, CONF_SIGNAL_MUTED_LABELS, CONF_SIGNAL_MUTED_DEVICES),
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
            kind for kind in ("freeze", "battery", "signal")
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
        Enable, limited to one device)."""
        self._device(device_id)
        found = self._enable_matching_entities(  # type: ignore[attr-defined]
            self._is_last_seen, "last_seen", device_id=device_id  # type: ignore[attr-defined]
        )
        enabled = int(found.get("enabled", 0))
        if enabled:
            self._page_done(device_id, "Last Seen turned on")
        return enabled

    def page_set_mute(self, device_id: str, kind: str, on: bool) -> None:
        """Set or lift one kind's mute on the device, in the options
        Settings writes, through the same update listener."""
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
            detail=f"{kind} {'muted' if on else 'unmuted'}, from its device page",
            device_id=device_id,
        )
        self._mark_changed()  # type: ignore[attr-defined]
