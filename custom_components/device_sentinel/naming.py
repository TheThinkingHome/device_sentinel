# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: naming.py, Version: 0.29.4 (2026-11-16)

"""What a device is called, when the registry does not say.

Home Assistant lets an integration register a device with no name.
UniFi does it for every client it has not been told about, so a house
with a router can carry dozens. Without a name, a surface would show
``device.id``, a hash that answers nothing and cannot be looked up
anywhere. This module answers instead, in a fixed order, and every
surface asks it.

The order (rule DEV-01):

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
upstreams where it has an entry, and by its domain otherwise (rule
GEN-07).
"""

from __future__ import annotations

import re

from homeassistant.helpers import device_registry as dr

from .const import NAME_LENGTH_MAX, STACK_DISPLAY_NAMES
from .device_fields import device_field, parent_name_part

ID_TAIL = 8


def _first_mac(device: dr.DeviceEntry) -> str | None:
    """Return the device's first network MAC as the registry spells it."""
    for kind, value in device_field(device, "connections", set()):
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


def _fit(name: str) -> str:
    """A name cut to NAME_LENGTH_MAX characters, the cut marked (rule DEV-03).

    The longest real name seen is 54 characters, so the cut reaches no
    real name. It stops a name of any length, which a registry allows,
    from reaching every report, page and message whole, where a name
    of 10,000 characters would make a telemetry row longer still.
    """
    if len(name) <= NAME_LENGTH_MAX:
        return name
    return name[: NAME_LENGTH_MAX - 1].rstrip() + "\u2026"


def _starts_with(text: str, start: str) -> bool:
    """Whether a name begins with another as whole words."""
    a, b = text.casefold(), start.casefold()
    return a == b or a.startswith(b + " ")


def with_parent(name: str, parent: str | None) -> str:
    """A child device's own name after its parent's, as Home Assistant
    shows it, unless it already begins with it (rule DEV-18)."""
    if not parent or _starts_with(name, parent):
        return name
    return f"{parent} {name}"


def without_parent(name: str, parent: str | None) -> str:
    """A name as a child device keeps it: its parent's name taken off the
    front where a person typed it whole, so Home Assistant, which adds
    the parent itself, never shows it twice (rule DEV-18)."""
    if not parent:
        return name
    # Matched on the text as typed, so a letter that changes length when
    # its case is folded, as "ß" does, never cuts the name in the wrong
    # place; such a name is kept whole.
    found = re.match(rf"\s*{re.escape(parent.strip())}\s+(\S.*)$", name, re.IGNORECASE | re.DOTALL)
    return found.group(1).strip() if found else name


def composed_name(device: dr.DeviceEntry | None, registry: dr.DeviceRegistry | None = None) -> str | None:
    """The device's name as Home Assistant shows it, whole: the name a
    person gave it, or the integration's, after its parent's for a child
    with no area of its own (rule DEV-18). None for a device with no
    name."""
    if device is None:
        return None
    named = _clean(device.name_by_user) or _clean(device.name)
    if not named:
        return None
    parent = parent_name_part(registry, device) if registry is not None else None
    return with_parent(named, parent)


def display_name(
    device: dr.DeviceEntry | None,
    domain: str | None,
    device_id: str,
    registry: dr.DeviceRegistry | None = None,
) -> str:
    """Return what to call this device, never its raw id (rule DEV-01),
    and never longer than NAME_LENGTH_MAX characters.

    Given the registry, a child device with no area of its own carries
    its parent's name first, as Home Assistant shows it (rule DEV-18).
    """
    if device is not None:
        named = composed_name(device, registry)
        if named:
            return _fit(named)
        mac = _first_mac(device)
        make = _clean(device_field(device, "manufacturer"))
        model = _clean(device_field(device, "model"))
        if mac and make and model:
            return _fit(f"{make} {model} {mac}")
        if mac:
            return _fit(f"{integration_label(domain)} {mac}")
    tail = device_id[-ID_TAIL:] if device_id else "unknown"
    return _fit(f"{integration_label(domain)}-{tail}")


def _key(text: object) -> str:
    """A name or area as compared: trimmed, without regard to capitals."""
    return str(text or "").strip().casefold()


def cannot_be_told_apart(name: str, area: str | None, other_name: str, other_area: str | None) -> bool:
    """Whether a device shows the same as another (rule REC-04).

    Home Assistant names each device for what it is and tells devices of
    one name apart by their area, and Device Sentinel shows the area
    beside the name. So two devices of one name are told apart when each
    has an area of its own and the areas differ. One with no area has
    nothing beside its name, so it is told apart from no device of its
    name.
    """
    if not _key(name) or _key(name) != _key(other_name):
        return False
    # Two that read the same in a notification are not told apart,
    # whatever their areas: a name ending in a bracket, or holding its
    # own area, is printed without the area (rule NOTE-13).
    if _key(with_area(name, area)) == _key(with_area(other_name, other_area)):
        return True
    if not _key(area) or not _key(other_area):
        return not _key(area)
    return _key(area) == _key(other_area)


def devices_sharing_a_name(shown: dict[str, tuple[str, str | None]]) -> list[str]:
    """The devices that cannot be told apart from another, from each
    device's name and area (rule REC-04)."""
    by_name: dict[str, list[str]] = {}
    for device_id, (name, _area) in shown.items():
        if _key(name):
            by_name.setdefault(_key(name), []).append(device_id)
    found: list[str] = []
    for ids in by_name.values():
        for device_id in ids:
            name, area = shown[device_id]
            if any(
                cannot_be_told_apart(name, area, *shown[other])
                for other in ids if other != device_id
            ):
                found.append(device_id)
    return found


def area_is_said(name: str, area: str | None) -> bool:
    """Whether a name already says where the device is (rules NOTE-13,
    BRIEF-13): it ends in a bracket, as "Soil Moisture (Monstera)" does,
    or holds the area's name, as "Kitchen light" in the Kitchen does,
    the way names were written before Home Assistant had areas."""
    if not area or not area.strip():
        return True
    text = (name or "").rstrip()
    # The area as whole words, so "Den" is not found in "Garden plug".
    # An underscore counts as a break, as in "kitchen_light".
    held = re.search(rf"(?<![^\W_]){re.escape(area.strip().casefold())}(?![^\W_])", text.casefold())
    return text.endswith((")", "]")) or held is not None


def with_area(name: str, area: str | None) -> str:
    """A device's name with its area in brackets, where the name does not
    already say it: "TIMMERFLOTTE temp/hmd sensor (Kitchen)" (rule NOTE-13)."""
    return name if area_is_said(name, area) else f"{name} ({area.strip()})"  # type: ignore[union-attr]
