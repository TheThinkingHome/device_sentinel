# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: device_fields.py, Version: 0.22.18 (2026-09-21)

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


def child_devices(registry: dr.DeviceRegistry, entry_id: str) -> list[Any]:
    """Return the child devices of one config entry, or none."""
    if _CHILD_ENTRIES_FOR_CONFIG_ENTRY is None:
        return []
    return list(_CHILD_ENTRIES_FOR_CONFIG_ENTRY(registry, entry_id))
