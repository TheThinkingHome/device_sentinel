# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: naming.py, Version: 0.20.18 (2026-09-12)

"""What a device is called, when the registry does not say.

Home Assistant lets an integration register a device with no name.
UniFi does it for every client it has not been told about, so a
router fleet carries dozens. Every human surface used to fall back to
``device.id``, a hash that answers nothing and cannot be looked up
anywhere. This module answers instead, in a fixed order, and every
surface asks it.

The order (ruling #402):

1. ``name_by_user``, what the person called it.
2. ``name``, what the integration called it.
3. ``{manufacturer} {model} {MAC}`` where the device carries make,
   model and a network MAC. On a router this reads as
   ``Ubiquiti UAP-AC-Pro 78:6c:84:24:b8:af``, which is as good as a
   name and is what a person can find in their router's client list.
4. ``{Integration} {MAC}`` where it carries a MAC but no make or
   model.
5. ``{Integration}-{id tail}`` where it carries neither. The tail
   is the last eight characters of the id, which is stable across
   restarts and distinguishes two nameless devices from each other,
   and is the last resort rather than the first.

The integration is named by the same map the problem list uses for
upstreams (ruling #266) where it has an entry, and by its domain
otherwise.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_DISPLAY_NAMES

ID_TAIL = 8


def _first_mac(device: dr.DeviceEntry) -> str | None:
    """Return the device's first network MAC as the registry spells it."""
    for kind, value in device.connections:
        if kind == dr.CONNECTION_NETWORK_MAC and isinstance(value, str):
            return value
    return None


def _clean(value: object) -> str | None:
    """A non-empty string, stripped, or None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def integration_label(domain: str | None) -> str:
    """Return the readable name for an integration domain."""
    if not domain:
        return "Unknown"
    return STACK_DISPLAY_NAMES.get(domain, domain)


def display_name(
    device: dr.DeviceEntry | None, domain: str | None, device_id: str
) -> str:
    """Return what to call this device, never its raw id (ruling #402)."""
    if device is not None:
        named = _clean(device.name_by_user) or _clean(device.name)
        if named:
            return named
        mac = _first_mac(device)
        make = _clean(device.manufacturer)
        model = _clean(device.model)
        if mac and make and model:
            return f"{make} {model} {mac}"
        if mac:
            return f"{integration_label(domain)} {mac}"
    tail = device_id[-ID_TAIL:] if device_id else "unknown"
    return f"{integration_label(domain)}-{tail}"
