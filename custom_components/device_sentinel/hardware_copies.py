# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/hardware_copies.py, Version: 0.27.10 (2026-10-27)

"""One piece of hardware shown as several devices (rule WATCH-06).

Since Home Assistant 2026.8 a device belongs to one integration, so a
piece of hardware that several integrations know becomes one registry
device each.
A Bluetooth proxy can be four: ESPHome, Bluetooth, BlueSight and
UniFi. Judged one by one, a dead proxy is several
problems, and a copy that is quiet by nature reads frozen while the
hardware is fine.

Two devices are copies of one piece of hardware only on evidence Home Assistant
recorded, never on a name:

1. **The same connection.** Each integration records the hardware's
   addresses (a network MAC, a Bluetooth address, a Zigbee IEEE). Two
   devices of different integrations holding the same address are the
   same hardware. Devices of one integration sharing an address are
   left alone: that is a hub and its children, not copies, and no
   group ever holds two devices of one integration.
2. **A Bluetooth adapter registered for a proxy.** Home Assistant's
   Bluetooth integration registers each proxy's adapter as a device of
   its own and points it at the proxy's device (via_device).
3. **An identifier that is another device's address.** Some integrations record no connection and name the device
   by the hardware's address instead: BlueSight registers each proxy as
   ("bluesight", "<the proxy's Bluetooth address>"), so its devices
   never meet rule 1. An identifier part shaped like a MAC address is pooled with
   every connection and every other identifier holding that address,
   whatever its kind or spelling, and the pool joins on rule 1's terms:
   never two devices of one integration. Such a copy ranks below one
   that records an address of its own (see rank_of()).

Only a group holding two or more devices that would otherwise be
watched changes anything. One copy is kept watched, the one that
reaches the hardware most directly; the others are set aside as copies
and keep their records, so if the group ever comes apart they are
watched again with their history.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from .device_fields import device_field, identifier_values

# How directly an integration reaches its hardware, from its manifest's
# iot_class: a push from the device itself beats polling, local beats
# the cloud. A copy that only tracks the hardware on the network ranks
# below all of them (see rank()).
IOT_RANK = {
    "local_push": 4,
    "local_polling": 3,
    "cloud_push": 2,
    "cloud_polling": 1,
}
BLUETOOTH_DOMAIN = "bluetooth"


def _connections(device: Any) -> set[tuple[str, str]]:
    found = set()
    for item in device_field(device, "connections", set()) or ():
        if isinstance(item, (tuple, list)) and len(item) == 2:
            kind, value = item
            if isinstance(kind, str) and isinstance(value, str) and value:
                found.add((kind, value.lower()))
    return found


# Six pairs of hex digits joined by colons or hyphens, or twelve hex
# digits bare: the shapes a MAC or Bluetooth address takes in a
# connection or an identifier.
_MAC_SHAPE = re.compile(r"^(?:[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}|[0-9a-f]{12})$")
# Addresses that name no hardware: unset and broadcast.
_NO_BOX = {"000000000000", "ffffffffffff"}


def mac_of(value: Any) -> str | None:
    """A MAC-shaped value as twelve lowercase hex digits, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not _MAC_SHAPE.match(text):
        return None
    bare = text.replace(":", "").replace("-", "")
    return None if bare in _NO_BOX else bare


def _identifier_macs(device: Any) -> set[str]:
    found = set()
    for _domain, parts in identifier_values(device):
        for part in parts:
            mac = mac_of(part)
            if mac:
                found.add(mac)
    return found


def find_groups(devices: Iterable[Any], domain_of: Callable[[Any], str | None]) -> list[set[str]]:
    """Groups of two or more device ids that are one piece of hardware.

    A group never holds two devices of one integration. An address that
    one integration gives to two of its devices (a hub and a child) says
    nothing about which hardware it is, so it joins nothing; and a join that
    would put two devices of one integration together through some
    other path is refused, so a chain of addresses cannot make a hub
    and its child copies.
    """
    devices = sorted(devices, key=lambda d: d.id)
    parent: dict[str, str] = {d.id: d.id for d in devices}
    domains = {d.id: domain_of(d) for d in devices}
    held: dict[str, set[str | None]] = {d.id: {domains[d.id]} for d in devices}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a: str, b: str) -> None:
        ra, rb = root(a), root(b)
        if ra == rb or held[ra] & held[rb]:
            return
        keep, gone = min(ra, rb), max(ra, rb)
        parent[gone] = keep
        held[keep] |= held.pop(gone)

    by_connection: dict[tuple[str, str], list[str]] = {}
    for device in devices:
        for connection in sorted(_connections(device)):
            by_connection.setdefault(connection, []).append(device.id)
    for connection in sorted(by_connection):
        members = by_connection[connection]
        owners = [domains.get(m) for m in members]
        if len(set(owners)) != len(owners):
            continue
        for other in members[1:]:
            join(members[0], other)
    # Rule 3: an identifier that is another device's
    # address. Only an address some device holds in an identifier is
    # pooled here; two connections that read alike with no identifier
    # holding the address are left to rule 1.
    by_mac_connection: dict[str, set[str]] = {}
    for device in devices:
        for _kind, value in _connections(device):
            mac = mac_of(value)
            if mac:
                by_mac_connection.setdefault(mac, set()).add(device.id)
    by_mac_identifier: dict[str, set[str]] = {}
    for device in devices:
        try:
            macs = _identifier_macs(device)
        except Exception:  # noqa: BLE001 - another integration's data
            # An entry that cannot be read names no address.
            macs = set()
        for mac in macs:
            by_mac_identifier.setdefault(mac, set()).add(device.id)
    for mac in sorted(by_mac_identifier):
        holders = sorted(by_mac_connection.get(mac, set()) | by_mac_identifier[mac])
        if len(holders) < 2:
            continue
        # The same refusal as rule 1: an address one integration gives
        # to two of its devices is a hub and a child, not copies.
        owners = [domains.get(m) for m in holders]
        if len(set(owners)) != len(owners):
            continue
        for other in holders[1:]:
            join(holders[0], other)
    for device in devices:
        via = device_field(device, "via_device_id")
        if domains.get(device.id) == BLUETOOTH_DOMAIN and via in parent and domains.get(via) != BLUETOOTH_DOMAIN:
            join(device.id, via)
    groups: dict[str, set[str]] = {}
    for device_id in parent:
        groups.setdefault(root(device_id), set()).add(device_id)
    return [members for members in groups.values() if len(members) > 1]


def choose_copies(
    groups: list[set[str]],
    watched: dict[str, str],
    rank: Callable[[str], tuple[Any, ...]],
) -> dict[str, str]:
    """For each group with two or more watched devices, every watched
    copy but the best ranked, mapped to the one kept."""
    copies: dict[str, str] = {}
    for members in groups:
        candidates = sorted(d for d in members if d in watched)
        if len(candidates) < 2:
            continue
        keep = max(candidates, key=lambda d: (rank(d), _tie(d)))
        for device_id in candidates:
            if device_id != keep:
                copies[device_id] = keep
    return copies


def _tie(device_id: str) -> tuple[int, ...]:
    # A stable last tie-break, lowest id kept, so the choice never
    # changes between restarts on equal ranks.
    return tuple(-ord(ch) for ch in device_id)


def rank_of(
    iot_class: str | None,
    own_domains: set[str],
    own_count: int,
    battery: bool = False,
    addressed: bool = True,
) -> tuple[int, int, int, int, int, int]:
    """How good a copy is to watch the hardware through.

    First, whether it has entities of its own at all. Then whether it is
    more than a network tracker: a device with a tracker of its own is a
    router's view of the hardware, which describes the network, not the
    hardware.
    Then whether it records an address of its own: a device joined only because its identifier names
    another device's address, as BlueSight's are, is a view of the hardware
    from outside, and it carries more entities than a plain ESPHome
    proxy, so on entity count alone it would be the copy kept.
    Then whether it carries the hardware's battery reading: a copy set aside
    has its readings dropped with it, so keeping the one without the
    battery would stop the battery being watched. Then how
    directly its integration reaches the hardware. Then how many entities it
    has.
    """
    has_own = 1 if own_count else 0
    # Any tracker of its own marks a router's view of the hardware, whatever
    # else that integration adds.
    not_tracker = 0 if "device_tracker" in own_domains else 1
    return (
        has_own,
        not_tracker,
        1 if addressed else 0,
        1 if battery else 0,
        IOT_RANK.get(iot_class or "", 0),
        own_count,
    )
