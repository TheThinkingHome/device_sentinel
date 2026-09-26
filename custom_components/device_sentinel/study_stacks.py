# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_stacks.py, Version: 0.23.8 (2026-09-25)

"""Z-Wave and Matter, gathered so their support can be built.

Device Sentinel learns a rhythm and judges silence against it, which
is the only way to read a stack that says nothing about itself.
Z-Wave and Matter say a great deal, and none of it is used yet.

Z-Wave names a node's state outright: alive, asleep, dead or unknown.
It also says whether a node listens, sleeps or wakes briefly, which is
the difference between silence meaning trouble and silence meaning a
battery device behaving exactly as designed. Matter says whether a
node is available, and which network it is on, so a Thread device can
be told from one on Wi-Fi.

This gathers both, lightly, while Extended Diagnostics is on and the
stack's own toggle is ticked (0.22.26). It detects nothing and changes
no verdict. Anyone running these stacks who sends a diagnostics
download teaches the next release what the wild actually holds:
which attributes exist in which versions, what a healthy fleet's
numbers look like, and what a sick one's look like. That is the
evidence the detectors will be built on.

Everything is read defensively. A library that renames an attribute,
or a version that never had it, is recorded as absent rather than
raising, and the name that was found is recorded beside the value so
a later release knows which shape it is reading.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import LOGGER

ZWAVE_DOMAIN = "zwave_js"
MATTER_DOMAIN = "matter"
# A fleet of any size is summarised by its counts; the rows are for
# reading shapes, so they are capped and the cap is recorded.
NODE_ROW_CAP = 120


def _read(holder: Any, name: str, default: Any = None) -> Any:
    """Return an attribute, or the default where reading it fails."""
    try:
        value = getattr(holder, name, default)
    except Exception as err:  # noqa: BLE001 - a property may raise
        LOGGER.debug(
            "device_sentinel: %s could not be read (%s), recorded as absent",
            name,
            err,
        )
        return default
    return value


def _plain(value: Any) -> Any:
    """Return something a JSON file can hold, or its type's name.

    A moment is written as the moment it is: the second fleet's first
    capture wrote the word "datetime" for every Z-Wave node's last
    seen (0.23.3).
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    name = getattr(value, "value", None)
    if isinstance(name, (str, int, float)):
        return name
    return type(value).__name__


def _statistics(holder: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """The statistics a version happens to carry, by name."""
    stats = _read(holder, "statistics")
    if stats is None:
        return {}
    found: dict[str, Any] = {}
    for name in names:
        value = _plain(_read(stats, name))
        if value is not None:
            found[name] = value
    return found


# What Z-Wave JS numbers a node's state with, in words (0.23.3). The
# second fleet's first capture wrote 1, 3 and 4 where the file promised
# asleep, dead and alive.
ZWAVE_STATUS_WORDS = {0: "unknown", 1: "asleep", 2: "awake", 3: "dead", 4: "alive"}


def _zwave_status(node: Any) -> str | None:
    """A Z-Wave node's state as a word, whatever shape it arrives in.

    None where the node carries no state at all, which is what a
    version change looks like from here.
    """
    raw = _read(node, "status")
    if raw is None:
        return None
    name = getattr(raw, "name", None)
    if isinstance(name, str) and name:
        return name.lower()
    value = _plain(raw)
    if isinstance(value, int) and not isinstance(value, bool):
        return ZWAVE_STATUS_WORDS.get(value, f"state {value}")
    return str(value)


# Matter's Network Commissioning cluster (0x0031) on the root endpoint
# names the interfaces a node has in its feature map: Wi-Fi, Thread,
# Ethernet. Where the map is absent, the diagnostics cluster the node
# carries says the same: Thread (0x0035), Wi-Fi (0x0036), Ethernet
# (0x0037). Read from the node's attribute table, so a node Home
# Assistant shows as Thread or Wi-Fi reads the same here (0.23.3).
_MATTER_FEATURES = ((2, "thread"), (1, "wifi"), (4, "ethernet"))
_MATTER_DIAGNOSTICS = ((53, "thread"), (54, "wifi"), (55, "ethernet"))
# Where a version might keep the moment a node was last heard. Read
# defensively, and the name that answered is recorded (0.23.3).
_MATTER_SEEN = ("last_seen", "lastSeen", "last_interview")


def _matter_attributes(node: Any) -> dict[str, Any]:
    for holder in (_read(node, "node_data"), node):
        table = _read(holder, "attributes")
        if isinstance(table, dict):
            return table
    return {}


def _matter_network(node: Any) -> str:
    """Thread, Wi-Fi or Ethernet, from the node's own attributes."""
    table = _matter_attributes(node)
    features = table.get("0/49/65532")
    if isinstance(features, int) and not isinstance(features, bool):
        found = [name for bit, name in _MATTER_FEATURES if features & bit]
        if found:
            return "+".join(found)
    present = {key.split("/")[1] for key in table if key.startswith("0/")}
    for cluster, name in _MATTER_DIAGNOSTICS:
        if str(cluster) in present:
            return name
    return ""


def _matter_seen(node: Any) -> tuple[str, Any]:
    """The name a version keeps a node's last contact under, and it."""
    for holder in (node, _read(node, "node_data")):
        for name in _MATTER_SEEN:
            value = _plain(_read(holder, name))
            if value not in (None, ""):
                return name, value
    return "", None


def _matter_detail(node: Any) -> str:
    """What a Matter line carries: its network, and when last heard."""
    parts = []
    network = _matter_network(node)
    if network:
        parts.append(f"network {network}")
    name, seen = _matter_seen(node)
    if name:
        parts.append(f"{name} {seen}")
    return ", ".join(parts)


_NODE_STATISTICS = (
    "rtt", "rssi", "last_seen", "commands_tx", "commands_rx",
    "commands_dropped_tx", "commands_dropped_rx", "timeout_response",
)
_CONTROLLER_STATISTICS = (
    "messages_tx", "messages_rx", "messages_dropped_tx",
    "messages_dropped_rx", "can", "nak", "timeout_ack", "timeout_callback",
)


def zwave_study(hass: HomeAssistant) -> dict[str, Any]:
    """What this house's Z-Wave network says about itself."""
    entries = hass.config_entries.async_entries(ZWAVE_DOMAIN)
    if not entries:
        return {}
    networks: list[dict[str, Any]] = []
    for entry in entries:
        client = _read(_read(entry, "runtime_data"), "client")
        driver = _read(client, "driver")
        controller = _read(driver, "controller")
        nodes = _read(controller, "nodes") or {}
        try:
            listed = list(nodes.values())
        except Exception:  # noqa: BLE001 - a mapping that is not one
            listed = []
        by_status: dict[str, int] = {}
        rows: list[dict[str, Any]] = []
        for node in listed:
            status = _zwave_status(node)
            key = str(status)
            by_status[key] = by_status.get(key, 0) + 1
            if len(rows) >= NODE_ROW_CAP:
                continue
            rows.append({
                "node_id": _plain(_read(node, "node_id")),
                "status": status,
                "ready": _plain(_read(node, "ready")),
                "controller": _plain(_read(node, "is_controller_node")),
                # How it listens, which is what makes its silence
                # normal or not: a mains node listens always, a
                # battery node sleeps, a FLiRS node wakes briefly.
                "listening": _plain(_read(node, "is_listening")),
                "frequent_listening": _plain(
                    _read(node, "is_frequent_listening")
                ),
                "routing": _plain(_read(node, "is_routing")),
                "statistics": _statistics(node, _NODE_STATISTICS),
            })
        networks.append({
            "entry_id": entry.entry_id,
            "state": str(entry.state),
            "driver_present": driver is not None,
            "nodes": len(listed),
            "by_status": by_status,
            "rows_capped": len(listed) > NODE_ROW_CAP,
            "controller_statistics": _statistics(
                controller, _CONTROLLER_STATISTICS
            ),
            "node_rows": rows,
        })
    return {"networks": networks}


async def matter_study(hass: HomeAssistant) -> dict[str, Any]:
    """What this house's Matter fabric says, and its Thread network."""
    entries = hass.config_entries.async_entries(MATTER_DOMAIN)
    if not entries:
        return {}
    fabrics: list[dict[str, Any]] = []
    for entry in entries:
        data = _read(entry, "runtime_data")
        client = _read(_read(data, "adapter"), "matter_client")
        listed: list[Any] = []
        getter = _read(client, "get_nodes")
        if callable(getter):
            try:
                listed = list(getter())
            except Exception as err:  # noqa: BLE001 - a library call
                LOGGER.debug("device_sentinel: Matter nodes unreadable: %s", err)
        rows: list[dict[str, Any]] = []
        available = 0
        for node in listed:
            if _read(node, "available"):
                available += 1
            if len(rows) >= NODE_ROW_CAP:
                continue
            rows.append({
                "node_id": _plain(_read(node, "node_id")),
                "available": _plain(_read(node, "available")),
                "bridge": _plain(_read(node, "is_bridge_device")),
                # Which network it is on, so Thread is told from
                # Wi-Fi. The name is recorded rather than assumed,
                # since this is the attribute most likely to move.
                "network": _matter_network(node) or None,
                # When the node was last heard, under the name the
                # version keeps it by, recorded beside it (0.23.3).
                "seen_as": _matter_seen(node)[0] or None,
                "seen": _matter_seen(node)[1],
            })
        fabrics.append({
            "entry_id": entry.entry_id,
            "state": str(entry.state),
            "client_present": client is not None,
            "nodes": len(listed),
            "available": available,
            "rows_capped": len(listed) > NODE_ROW_CAP,
            "node_rows": rows,
        })
    return {"fabrics": fabrics, "thread": _thread_network(hass)}


def _thread_network(hass: HomeAssistant) -> dict[str, Any]:
    """Whether Thread and a border router are set up in this house.

    Read from the outside, as every other stack is. Device Sentinel
    imports MQTT because it subscribes to a broker; it imports none of
    ZHA, Zigbee2MQTT, Z-Wave, Matter or Lutron, because it only ever
    watches what they publish, and a stack it cannot reach into cannot
    break it when that stack changes. Thread is observed too, so it is
    read the same way: which integrations are loaded, and whether a
    border router has a config entry of its own. The network's own
    credentials are never touched (0.22.26).
    """
    return {
        "integration_loaded": "thread" in hass.config.components,
        "border_router_loaded": "otbr" in hass.config.components,
        "border_routers": len(hass.config_entries.async_entries("otbr")),
    }


# ------------------------------------------------------- the recorder
#
# A snapshot answers what a version looks like. It cannot answer what
# a network does over a fortnight, and that is the question these two
# stacks can answer and Lutron already has: a node going dead, a
# sleeper missing its wake, a Thread device dropping off. Those are
# rare, so a download taken at any one moment shows a healthy network
# and teaches nothing.
#
# So while Extended Diagnostics is on and a stack's toggle is ticked,
# every tick reads what each node says about itself and writes a line
# only when it changes. Reading is in memory, with no network call, so
# the cost is one attribute per node per tick. The numbers ride along
# on a slower cadence, because they are the bulk of the file and the
# thing a detector will eventually be tuned against.


def _node_state(node: Any) -> tuple[str, str]:
    """A Z-Wave node's state, and the numbers worth keeping."""
    status = str(_zwave_status(node))
    stats = _statistics(node, _NODE_STATISTICS)
    detail = ", ".join(f"{name} {value}" for name, value in stats.items())
    return status, detail


# ------------------------------------------ names and coordinators, 0.23.8
#
# Researched on 25 September 2026 in the code Home Assistant 2026.9.2
# ships and the libraries it pins (zwave-js-server-python 0.73.1,
# matter-python-client 1.4.0); the findings are in
# Project__Stack_Readers.md. Home Assistant registers a Z-Wave node as
# ("zwave_js", "<home id>-<node id>") and a Matter node as ("matter",
# "deviceid_<fabric hex>-<node hex>-MatterNodeDevice"), with an
# endpoint number in place of the last part for a bridged device. So a
# node is named from the device registry, and neither integration is
# imported (#478).

_ZWAVE_IDENT = re.compile(r"^\d+-(\d+)$")
_MATTER_IDENT = re.compile(r"^deviceid_[0-9A-F]{16}-([0-9A-F]{16})-(.+)$")
# A Thread device's routing role, from Thread Network Diagnostics
# (0/53/1), as the Matter specification numbers it.
_THREAD_ROLES = {
    0: "unspecified", 1: "unassigned", 2: "sleepy end device",
    3: "end device", 4: "router-eligible end device", 5: "router",
    6: "leader",
}


def node_devices(hass: HomeAssistant, entry: Any, domain: str) -> dict[str, str]:
    """Each node id of an entry's network, mapped to its device id.

    A Matter bridge's own node maps to the bridge; its bridged
    endpoints are devices of their own and are not a node.
    """
    registry = dr.async_get(hass)
    found: dict[str, str] = {}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        for ident_domain, ident in device.identifiers:
            if ident_domain != domain:
                continue
            if domain == ZWAVE_DOMAIN:
                match = _ZWAVE_IDENT.match(str(ident))
                if match:
                    found[match.group(1)] = device.id
            else:
                match = _MATTER_IDENT.match(str(ident))
                if match and match.group(2) == "MatterNodeDevice":
                    found[str(int(match.group(1), 16))] = device.id
    return found


def _zwave_seen(node: Any) -> float | None:
    """When a Z-Wave node was last heard, as a timestamp."""
    for holder in (node, _read(node, "statistics")):
        seen = _read(holder, "last_seen")
        if isinstance(seen, datetime):
            return seen.timestamp()
    return None


def _zwave_status_sensor(hass: HomeAssistant, home_id: Any, node_id: Any) -> str:
    """Whether the node's status sensor is on, off or absent.

    Home Assistant makes one per node, enabled by default, and its
    change to "dead" is a state change on the device like any other,
    which Device Sentinel counts as the device speaking (research
    finding 5). The probe says where it is on.
    """
    unique_id = f"{home_id}.{node_id}.node_status"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", ZWAVE_DOMAIN, unique_id)
    if entity_id is None:
        return "absent"
    entry = er.async_get(hass).async_get(entity_id)
    return "off" if entry is not None and entry.disabled_by else "on"


def _zwave_listening(node: Any) -> str:
    """How a node listens, which makes its silence normal or not."""
    if _read(node, "is_listening"):
        return "listens"
    if _read(node, "is_frequent_listening"):
        return "wakes briefly"
    if _read(node, "is_listening") is False:
        return "sleeps"
    return ""


def _matter_radio(node: Any) -> str:
    """A Wi-Fi node's signal or a Thread node's role, where carried."""
    table = _matter_attributes(node)
    rssi = table.get("0/54/4")
    if isinstance(rssi, (int, float)) and not isinstance(rssi, bool):
        return f"wifi rssi {rssi}"
    role = table.get("0/53/1")
    if isinstance(role, int) and not isinstance(role, bool):
        return f"thread role {_THREAD_ROLES.get(role, role)}"
    return ""


def probe_rows(hass: HomeAssistant, studied: set[str]) -> list[dict[str, Any]]:
    """What each studied stack's nodes say right now, one row each.

    Each row carries the node's device, when there is one, so the
    recorder can set Device Sentinel's own view beside the stack's
    (0.23.8).
    """
    rows: list[dict[str, Any]] = []
    if ZWAVE_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(ZWAVE_DOMAIN):
            controller = _read(
                _read(_read(_read(entry, "runtime_data"), "client"), "driver"),
                "controller",
            )
            home_id = _read(controller, "home_id")
            devices = node_devices(hass, entry, ZWAVE_DOMAIN)
            nodes = _read(controller, "nodes") or {}
            try:
                listed = list(nodes.values())
            except Exception as err:  # noqa: BLE001 - not a mapping
                LOGGER.debug(
                    "device_sentinel: Z-Wave nodes unreadable (%s)", err
                )
                listed = []
            for node in listed:
                if _read(node, "is_controller_node"):
                    continue
                node_id = str(_plain(_read(node, "node_id")))
                status, numbers = _node_state(node)
                extra = [
                    part for part in (
                        _zwave_listening(node),
                        f"status sensor {_zwave_status_sensor(hass, home_id, node_id)}",
                    ) if part
                ]
                rows.append({
                    "stack": ZWAVE_DOMAIN,
                    "node": node_id,
                    "device_id": devices.get(node_id, ""),
                    "now": status,
                    "seen": _zwave_seen(node),
                    "detail": ", ".join(extra + ([numbers] if numbers else [])),
                })
    if MATTER_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
            client = _read(
                _read(_read(entry, "runtime_data"), "adapter"), "matter_client"
            )
            getter = _read(client, "get_nodes")
            if not callable(getter):
                continue
            devices = node_devices(hass, entry, MATTER_DOMAIN)
            try:
                listed = list(getter())
            except Exception as err:  # noqa: BLE001 - a library call
                LOGGER.debug(
                    "device_sentinel: Matter nodes unreadable (%s)", err
                )
                listed = []
            for node in listed:
                node_id = str(_plain(_read(node, "node_id")))
                detail = [part for part in (_matter_detail(node), _matter_radio(node)) if part]
                rows.append({
                    "stack": MATTER_DOMAIN,
                    "node": node_id,
                    "device_id": devices.get(node_id, ""),
                    "now": "available" if _read(node, "available") else "away",
                    "network": _matter_network(node),
                    "detail": ", ".join(detail),
                })
    return rows[:NODE_ROW_CAP * 4]


# What a Z-Wave controller says about itself (ControllerStatus).
_CONTROLLER_WORDS = {0: "ready", 1: "unresponsive", 2: "jammed"}


def coordinator_rows(hass: HomeAssistant, studied: set[str]) -> list[dict[str, Any]]:
    """Each studied stack's coordinator, one row per config entry.

    Z-Wave: the entry's state, whether the client's connection to the
    Z-Wave JS server is open, whether the driver is there, and the
    controller's own status. Matter: the entry's state and whether the
    server connection is open. A stick pulled or a server restarted
    shows here, which is what a reader must tell from a real outage
    (research findings 1, 6 and 10).
    """
    rows: list[dict[str, Any]] = []
    if ZWAVE_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(ZWAVE_DOMAIN):
            client = _read(_read(entry, "runtime_data"), "client")
            driver = _read(client, "driver")
            raw = _read(_read(driver, "controller"), "status")
            value = _plain(raw)
            words = (
                _CONTROLLER_WORDS.get(value, f"status {value}")
                if isinstance(value, int) and not isinstance(value, bool)
                else (str(value) if value is not None else "no controller")
            )
            state = getattr(entry.state, "value", str(entry.state))
            connected = bool(_read(client, "connected"))
            now = (
                words if connected and driver is not None
                else "no driver" if connected
                else "disconnected"
            )
            rows.append({
                "stack": ZWAVE_DOMAIN,
                "node": "controller",
                "now": now,
                "detail": f"entry {state}",
            })
    if MATTER_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
            client = _read(_read(_read(entry, "runtime_data"), "adapter"), "matter_client")
            connected = _read(_read(client, "connection"), "connected")
            state = getattr(entry.state, "value", str(entry.state))
            rows.append({
                "stack": MATTER_DOMAIN,
                "node": "server",
                "now": "connected" if connected else "disconnected",
                "detail": f"entry {state}",
            })
    return rows
