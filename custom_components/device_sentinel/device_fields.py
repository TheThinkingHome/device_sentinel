# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: device_fields.py, Version: 0.29.4 (2026-11-16)

"""Child devices, and the fields only an ordinary device carries.

Home Assistant 2026.9 added child devices: a device filed under
another, such as a boiler's pump beneath the boiler. The registry keeps
them in a list of their own, and the lookup by config entry returns
ordinary devices only, so a registry walk that asks only that misses
every child. `child_devices` asks the second question.

A child carries a name, an area, labels, a config entry and a disabled
flag, and none of the fields an ordinary device adds: manufacturer,
model, model ID, software and hardware versions, connections, the
device it is reached through, its entry type and the rest. Home
Assistant answers a custom integration that reads one of them from a
child with an empty value and a deprecation line, and says the read
breaks in 2027.9. `getattr` with a default does not avoid it, because
the child answers the attribute rather than raising. So every such read
in this integration goes through `device_field`, which asks what the
entry is before it reads.

Both names are looked up rather than imported, because the floor
release, 2026.5.0, has neither: there are no child devices to find and
no child entry to test for, and both helpers then do what the code did
before.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import device_registry as dr

_CHILD_ENTRY = getattr(dr, "ChildDeviceEntry", None)
_CHILD_ENTRIES_FOR_CONFIG_ENTRY = getattr(
    dr, "async_child_entries_for_config_entry", None
)


def is_child_device(device: Any) -> bool:
    """Return whether this registry entry is a child device."""
    return _CHILD_ENTRY is not None and isinstance(device, _CHILD_ENTRY)


def device_field(device: Any, field: str, default: Any = None) -> Any:
    """Return a field only an ordinary device carries, or the default.

    None for a missing device, the default for a child device, and the
    entry's own value otherwise. The caller names the default a child
    stands for: an empty set for connections, None for the rest.
    """
    if device is None or is_child_device(device):
        return default
    return getattr(device, field, default)


def identifier_values(device: Any) -> list[tuple[str, tuple[Any, ...]]]:
    """Each of a device's identifiers as its domain and the parts after it.

    Home Assistant types an identifier as a pair, a domain and a value,
    but stores whatever an integration registers. The hOn integration
    registers three parts, its domain, the appliance's MAC and its type,
    and reading every identifier as a pair stops Device Sentinel starting
    and fails the diagnostics download. Any length is read here: the
    domain first, every part after it kept. Anything that is not a
    tuple or a list with a domain is skipped.
    """
    values: list[tuple[str, tuple[Any, ...]]] = []
    try:
        identifiers = list(device_field(device, "identifiers", set()) or ())
    except TypeError:
        return values
    for identifier in identifiers:
        if isinstance(identifier, (tuple, list)) and identifier:
            values.append((str(identifier[0]), tuple(identifier[1:])))
    return values


def child_devices(registry: dr.DeviceRegistry, entry_id: str) -> list[Any]:
    """Return the child devices of one config entry, or none."""
    if _CHILD_ENTRIES_FOR_CONFIG_ENTRY is None:
        return []
    return list(_CHILD_ENTRIES_FOR_CONFIG_ENTRY(registry, entry_id))


def parent_device(registry: dr.DeviceRegistry, device: Any) -> Any:
    """The ordinary device a child device belongs to, or None."""
    if not is_child_device(device):
        return None
    parent_id = getattr(device, "parent_device_id", None)
    return registry.async_get(parent_id) if parent_id else None


def effective_area_id(registry: dr.DeviceRegistry, device: Any) -> str | None:
    """The area a device is in, as Home Assistant places it (rule DEV-18).

    A device's own area; for a child device with none of its own, its
    parent's. Home Assistant 2026.11 reads a child's area the same way
    (`async_get_effective_area_id`), and its dashboard shows the child
    in the parent's room.
    """
    if device is None:
        return None
    own = getattr(device, "area_id", None)
    if own:
        return str(own)
    parent = parent_device(registry, device)
    area = getattr(parent, "area_id", None) if parent is not None else None
    return str(area) if area else None


def parent_name_part(registry: dr.DeviceRegistry, device: Any) -> str | None:
    """The parent's name a child device is shown with, or None (rule DEV-18).

    Home Assistant puts the parent device's name before a child's when
    the child has no area of its own, so "Socket 1" reads "Power strip
    Socket 1"; a child in an area of its own is named alone.
    """
    if device is None or getattr(device, "area_id", None):
        return None
    parent = parent_device(registry, device)
    if parent is None:
        return None
    for value in (getattr(parent, "name_by_user", None), getattr(parent, "name", None)):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def area_name_of(hass: Any, device: Any) -> str | None:
    """The name of the area a device is in, its parent's for a child
    device with none of its own, or None (rule DEV-18)."""
    from homeassistant.helpers import area_registry as ar

    area_id = effective_area_id(dr.async_get(hass), device)
    if not area_id:
        return None
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area is not None else None


def update_device(hass: Any, device_id: str, **changes: Any) -> None:
    """Write a name, an area or labels to a device or a child device.

    Home Assistant refuses `async_update_device` for a child device and
    takes `async_update_child_device` instead, with the same fields
    (rule DEV-18). Before child devices existed there is only the one.
    """
    registry = dr.async_get(hass)
    if is_child_device(registry.async_get(device_id)):
        registry.async_update_child_device(device_id, **changes)  # type: ignore[attr-defined]
    else:
        registry.async_update_device(device_id, **changes)
