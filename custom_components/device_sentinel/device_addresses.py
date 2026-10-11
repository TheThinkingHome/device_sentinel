# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/device_addresses.py, Version: 0.25.5 (2026-10-10)

"""What the device page shows of a device's identity (0.25.5).

A row with nothing to show is not drawn (James, 10 October 2026). The
registry's text fields count as empty when they hold nothing but a
zero: 32 of the reference house's Zigbee2MQTT devices give "0" as a
hardware version, which says nothing about the hardware.

Each address is named by its kind, one row per kind: the connections
Home Assistant records (MAC, Zigbee, Bluetooth, UPnP), the IEEE address
Zigbee2MQTT gives in its identifier, a Z-Wave device's node number,
and a Matter device's serial number. Zigbee2MQTT records no connection
at all, which is why the reference house showed no address for any of
its 78 Zigbee devices before this.
"""

from __future__ import annotations

from typing import Any

from .device_fields import device_field, identifier_values
from .device_type import _zwave_node
from .stack_z2m import device_key as zigbee2mqtt_address

MAC = "MAC Address"
ZIGBEE = "Zigbee Address"
BLUETOOTH = "Bluetooth Address"
UPNP = "UPnP ID"
ZWAVE_NODE = "Z-Wave Node"
SERIAL = "Serial Number"

# Home Assistant's connection kinds, and the row each is shown under.
CONNECTION_ROWS = {
    "mac": MAC,
    "zigbee": ZIGBEE,
    "bluetooth": BLUETOOTH,
    "upnp": UPNP,
}
ROW_ORDER = (MAC, ZIGBEE, BLUETOOTH, UPNP, ZWAVE_NODE, SERIAL)
MATTER_SERIAL_PREFIX = "serial_"


def shown(value: Any) -> str | None:
    """A registry text field as the page shows it, or None for nothing.

    Empty, blank and all-zero values ("0", "0.0", "0.0.0") are nothing.
    For display only: the record, the diagnostics and the battery
    library read the field as Home Assistant holds it."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or set(text) <= {"0", "."}:
        return None
    return text


def addresses(device: Any) -> list[dict[str, str]]:
    """The device's addresses, one row per kind, in a fixed order."""
    found: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}

    def add(row: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        value = value.strip()
        known = seen.setdefault(row, set())
        if value.casefold() not in known:
            known.add(value.casefold())
            found.setdefault(row, []).append(value)

    try:
        connections = list(device_field(device, "connections", set()) or ())
    except TypeError:
        connections = []
    for item in sorted(
        tuple(item)
        for item in connections
        if isinstance(item, (tuple, list)) and len(item) == 2
        and all(isinstance(part, str) for part in item)
    ):
        kind, value = item
        row = CONNECTION_ROWS.get(kind)
        if row is not None:
            add(row, value)
    if device is not None:
        add(ZIGBEE, zigbee2mqtt_address(device))
        try:
            add(ZWAVE_NODE, _zwave_node(device))
        except TypeError:
            pass
    for domain, parts in identifier_values(device):
        if domain != "matter":
            continue
        for part in parts:
            if isinstance(part, str) and part.startswith(MATTER_SERIAL_PREFIX):
                add(SERIAL, part[len(MATTER_SERIAL_PREFIX):])
    return [
        {"label": row, "value": ", ".join(found[row])}
        for row in ROW_ORDER
        if found.get(row)
    ]
