# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_stacks.py, Version: 0.27.10 (2026-10-27)

"""What six stacks say about their devices, gathered so their support
can be built: Z-Wave and Matter in depth, and Hue, SmartThings, Tuya
and Lutron for the stack probe.

Device Sentinel learns a rhythm and judges silence against it, which
is the only way to read a stack that says nothing about itself.
Z-Wave and Matter say a great deal, and what this gathers judges
nothing.

Z-Wave names a node's state outright: alive, asleep, dead or unknown.
It also says whether a node listens, sleeps or wakes briefly, which is
the difference between silence meaning trouble and silence meaning a
battery device behaving exactly as designed. Matter says whether a
node is available, and which network it is on, so a Thread device can
be told from one on Wi-Fi.

This gathers both, lightly, while Extended Diagnostics is on and the
stack's own toggle is ticked (rule STACK-11). It detects nothing and changes
no verdict. Anyone running these stacks who sends a diagnostics
download teaches the next release what the wild actually holds:
which attributes exist in which versions, what a healthy fleet's
numbers look like, and what a sick one's look like. That is the
evidence the detectors will be built on.

The same readings feed the stack probe (rule STACK-12): `probe_rows`, the
node listeners of `zwave_nodes` and the controller counters of
`zwave_health` let `study.py` write each change to `stack_probe.md`
beside Device Sentinel's own view of the device, the readers in shadow.
They too detect nothing.

Hue and SmartThings are read more fully. For Hue: each
bridge's event stream, firmware and update state, when the library last
lost the stream and the bridge's clock on its newest event; each
device's link, marked stale while the stream is down, its place on
Hue's ignore list, whether it is Hue certified, its battery and its
light's on or off. For SmartThings: each location's event stream, its
retries and subscription, and whether Home Assistant is asking for it
to be signed in again; each device's availability and how it reaches
the cloud. Two of these readings are private to the libraries and two
to Home Assistant, allowed because this records and never judges
(rule STACK-08). Each is taken from memory once a minute.

Everything is read defensively. A library that renames an attribute,
or a version that never had it, is recorded as absent rather than
raising, and the name that was found is recorded beside the value so
a later release knows which shape it is reading.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .device_fields import identifier_values
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

    A moment is written as the moment it is, not as the word
    "datetime".
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    # An enum's value; read through _read, since an object whose
    # attributes raise would otherwise escape here.
    name = _read(value, "value")
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


# What Z-Wave JS numbers a node's state with, in words, so the file
# says asleep, dead and alive rather than 1, 3 and 4 (rule STACK-05).
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
# Assistant shows as Thread or Wi-Fi reads the same here (rule STACK-12).
_MATTER_FEATURES = ((2, "thread"), (1, "wifi"), (4, "ethernet"))
_MATTER_DIAGNOSTICS = ((53, "thread"), (54, "wifi"), (55, "ethernet"))
# Where a version might keep the moment a node was last heard. Read
# defensively, and the name that answered is recorded.
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
    # Only entries set up to run (rule STACK-12).
    entries = live_entries(hass, ZWAVE_DOMAIN)
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
    # Only entries set up to run (rule STACK-12).
    entries = live_entries(hass, MATTER_DOMAIN)
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
                # version keeps it by, recorded beside it.
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
    credentials are never touched (rule STACK-13).
    """
    return {
        "integration_loaded": "thread" in hass.config.components,
        "border_router_loaded": "otbr" in hass.config.components,
        "border_routers": len(live_entries(hass, "otbr")),
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


# ------------------------------------------------- names and coordinators
#
# Home Assistant registers a Z-Wave node as
# ("zwave_js", "<home id>-<node id>") and a Matter node as ("matter",
# "deviceid_<fabric hex>-<node hex>-MatterNodeDevice"), with an
# endpoint number in place of the last part for a bridged device. So a
# node is named from the device registry, and neither integration is
# imported (rule STACK-12).

_ZWAVE_IDENT = re.compile(r"^\d+-(\d+)$")
_MATTER_IDENT = re.compile(r"^deviceid_[0-9A-F]{16}-([0-9A-F]{16})-(.+)$")
# A Thread device's routing role, from Thread Network Diagnostics
# (0/53/1), as the Matter specification numbers it.
_THREAD_ROLES = {
    0: "unspecified", 1: "unassigned", 2: "sleepy end device",
    3: "end device", 4: "router-eligible end device", 5: "router",
    6: "leader",
}


# Hue, SmartThings, Tuya and Lutron are read as Z-Wave and Matter are:
# from what Home Assistant already holds in memory, by attribute, with
# no import and nothing in the manifest. The Lutron session is a
# private attribute, which Extended Diagnostics may read since it
# records and never judges (rule STACK-08).
HUE_DOMAIN = "hue"
SMARTTHINGS_DOMAIN = "smartthings"
TUYA_DOMAIN = "tuya"
LUTRON_DOMAIN = "lutron_caseta"
PLAIN_ID_DOMAINS = (HUE_DOMAIN, SMARTTHINGS_DOMAIN, TUYA_DOMAIN)


def node_devices(hass: HomeAssistant, entry: Any, domain: str) -> dict[str, str]:
    """Each node id of an entry's network, mapped to its device id.

    A Matter bridge's own node maps to the bridge; its bridged
    endpoints are devices of their own and are not a node.
    """
    registry = dr.async_get(hass)
    found: dict[str, str] = {}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        # Any length; the stack's own id is the first part after the
        # domain.
        for ident_domain, parts in identifier_values(device):
            if ident_domain != domain or not parts:
                continue
            ident = parts[0]
            if domain in PLAIN_ID_DOMAINS:
                # Hue, SmartThings and Tuya register a device by the
                # stack's own id for it, unchanged.
                found[str(ident)] = device.id
            elif domain == ZWAVE_DOMAIN:
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

    Home Assistant makes one per node, enabled by default. "dead"
    makes the device unavailable and "alive" after dead counts as
    contact; otherwise the status is never a report (rule STACK-05).
    The probe says where it is on.
    """
    unique_id = f"{home_id}.{node_id}.node_status"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", ZWAVE_DOMAIN, unique_id)
    if entity_id is None:
        return "absent"
    entry = er.async_get(hass).async_get(entity_id)
    return "off" if entry is not None and entry.disabled_by else "on"


def zwave_route(node: Any) -> str:
    """The route a Z-Wave node's messages last traveled.

    From the node's last working route: the repeaters between it and
    the controller, or the two nodes a route failed between. Z-Wave's
    version of which router a device depends on; when a repeater dies,
    everything routed through it goes quiet with it. Read from the
    statistics the library already holds in memory; nothing is sent.
    """
    lwr = _read(_read(node, "statistics"), "lwr")
    if lwr is None:
        return ""
    data = _read(lwr, "data")
    data = data if isinstance(data, dict) else {}
    failed = data.get("routeFailedBetween")
    if isinstance(failed, (list, tuple)) and len(failed) == 2:
        return f"route failed between {_plain(failed[0])} and {_plain(failed[1])}"
    repeaters = data.get("repeaters")
    if not isinstance(repeaters, (list, tuple)):
        return ""
    ids = [str(_plain(each)) for each in repeaters]
    return f"route via {', '.join(ids)}" if ids else "route direct"


def zwave_health(hass: HomeAssistant) -> list[tuple[str, str, dict[str, int], str]]:
    """Each Z-Wave controller's counters and background noise.

    The counters only ever rise, so the caller writes the day's change.
    Background noise is the controller's own reading of each channel,
    the sign of interference that no counter shows.
    """
    found: list[tuple[str, str, dict[str, int], str]] = []
    for entry, node in entry_nodes(live_entries(hass, ZWAVE_DOMAIN), "controller"):
        controller = _read(
            _read(_read(_read(entry, "runtime_data"), "client"), "driver"),
            "controller",
        )
        if controller is None:
            continue
        counters = {
            name: value
            for name, value in _statistics(controller, _CONTROLLER_STATISTICS).items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        stats_data = _read(_read(controller, "statistics"), "data")
        raw = stats_data.get("backgroundRSSI") if isinstance(stats_data, dict) else None
        channels = []
        if isinstance(raw, dict):
            for index in range(4):
                reading = raw.get(f"channel{index}")
                if isinstance(reading, dict):
                    average = reading.get("average")
                    if isinstance(average, (int, float)) and not isinstance(average, bool):
                        channels.append(f"ch{index} {average} dBm")
        found.append((str(entry.entry_id), node, counters, ", ".join(channels)))
    return found


def zwave_nodes(hass: HomeAssistant) -> list[tuple[Any, str, str]]:
    """Each Z-Wave node object with its id and device, to listen to."""
    nodes_found: list[tuple[Any, str, str]] = []
    for entry, tag in entry_tags(live_entries(hass, ZWAVE_DOMAIN)):
        controller = _read(
            _read(_read(_read(entry, "runtime_data"), "client"), "driver"),
            "controller",
        )
        devices = node_devices(hass, entry, ZWAVE_DOMAIN)
        for node in _listed(_read(controller, "nodes")):
            if _read(node, "is_controller_node"):
                continue
            node_id = str(_plain(_read(node, "node_id")))
            nodes_found.append((node, tagged(tag, node_id), devices.get(node_id, "")))
    return nodes_found


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
        parts = [f"thread role {_THREAD_ROLES.get(role, role)}"]
        network = thread_network_id(table.get("0/53/4"))
        if network:
            parts.append(f"thread network {network}")
        return ", ".join(parts)
    return ""


def thread_network_id(value: Any) -> str:
    """A Thread network's Extended PAN ID as sixteen hex digits.

    A Thread node reports it in attribute 0/53/4 and a border router
    announces the same number, so the two can be matched: it says which
    border routers a device actually depends on, which matters where an
    Apple or Google router carries the same network or a separate one
    (rule STACK-06). Written as the border router announces it;
    anything that is not a whole number is left out.
    """
    if isinstance(value, bool):
        return ""
    if isinstance(value, int) and value >= 0:
        return f"{value:016x}"
    if isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{16}", value):
        return value.lower()
    return ""


# One reader per stack, each run on its own so a stack whose library
# throws costs its own lines and nothing else, and never stops the
# minute tick or the midnight fold for the whole house.
StackFailure = Callable[[str, Exception], None]


def _failed(on_failure: StackFailure | None, domain: str, err: Exception) -> None:
    """Hand a stack's failure to the caller, or note it at debug."""
    if on_failure is not None:
        on_failure(domain, err)
    else:
        LOGGER.debug("device_sentinel: %s could not be read (%s)", domain, err)


def _zwave_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Z-Wave node, with its device, status and last seen."""
    rows: list[dict[str, Any]] = []
    for entry, tag in entry_tags(live_entries(hass, ZWAVE_DOMAIN)):
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
            route = zwave_route(node)
            rows.append({
                "stack": ZWAVE_DOMAIN,
                "node": tagged(tag, node_id),
                "device_id": devices.get(node_id, ""),
                "now": status,
                "seen": _zwave_seen(node),
                "route": route,
                "detail": ", ".join(
                    extra + ([route] if route else []) + ([numbers] if numbers else [])
                ),
            })
    return rows


def _matter_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Matter node, with its device, availability and network."""
    rows: list[dict[str, Any]] = []
    for entry, tag in entry_tags(live_entries(hass, MATTER_DOMAIN)):
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
                "node": tagged(tag, node_id),
                "device_id": devices.get(node_id, ""),
                "now": "available" if _read(node, "available") else "away",
                "quiet": not _read(node, "available"),
                "network": _matter_network(node),
                "detail": ", ".join(detail),
            })
    return rows


def probe_rows(
    hass: HomeAssistant,
    studied: set[str],
    on_failure: StackFailure | None = None,
) -> list[dict[str, Any]]:
    """What each studied stack's nodes say right now, one row each.

    Each row carries the node's device, when there is one, so the
    recorder can set Device Sentinel's own view beside the stack's
    (rule STACK-12). A stack that throws is handed to on_failure and
    the others are read as usual.
    """
    rows: list[dict[str, Any]] = []
    for domain, reader in (
        (ZWAVE_DOMAIN, _zwave_rows),
        (MATTER_DOMAIN, _matter_rows),
        (HUE_DOMAIN, _hue_rows),
        (SMARTTHINGS_DOMAIN, _smartthings_rows),
        (TUYA_DOMAIN, _tuya_rows),
    ):
        if domain not in studied:
            continue
        try:
            rows.extend(reader(hass))
        except Exception as err:  # noqa: BLE001 - a library behaving oddly
            _failed(on_failure, domain, err)
    return rows[:NODE_ROW_CAP * 4]


def _listed(container: Any) -> list[Any]:
    """The items of a mapping or an iterable, or nothing."""
    try:
        values = container.values() if hasattr(container, "values") else container
        return list(values or [])
    except Exception as err:  # noqa: BLE001 - a library's container
        LOGGER.debug("device_sentinel: stack items unreadable (%s)", err)
        return []


def _called(function: Any, *args: Any) -> Any:
    """A library call's answer, or None where it throws.

    Every Hue and SmartThings reading is taken through `_read` or
    here, so a library that renames, removes or breaks something costs
    that one reading and never the minute check.
    """
    if not callable(function):
        return None
    try:
        return function(*args)
    except Exception as err:  # noqa: BLE001 - a library call
        LOGGER.debug("device_sentinel: a stack reading failed (%s), recorded as absent", err)
        return None


def _option_list(entry: Any, key: str) -> set[str]:
    """An entry option holding a list, as strings, or nothing."""
    options = _read(entry, "options")
    if not isinstance(options, Mapping):
        return set()
    value = options.get(key)
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {str(item) for item in value}


def _hue_stream(api: Any) -> str | None:
    """The event stream's status name: CONNECTED, CONNECTING or
    DISCONNECTED, or None where it cannot be read."""
    name = _read(_read(_read(api, "events"), "status"), "name")
    return name if isinstance(name, str) else None


def _hue_services(device: Any) -> dict[str, list[str]]:
    """A Hue device's services, by resource type."""
    found: dict[str, list[str]] = {}
    for service in _listed(_read(device, "services")):
        kind = _plain(_read(service, "rtype"))
        rid = _read(service, "rid")
        if isinstance(kind, str) and isinstance(rid, str):
            found.setdefault(kind, []).append(rid)
    return found


def _hue_resource(controller: Any, rid: str) -> Any:
    """One resource from an aiohue controller, or None."""
    return _called(_read(controller, "get"), rid)


def _hue_light_on(api: Any, services: dict[str, list[str]]) -> bool | None:
    """Whether the device's first light is on, or None without one."""
    for rid in services.get("light", []):
        on = _read(_read(_hue_resource(_read(api, "lights"), rid), "on"), "on")
        if isinstance(on, bool):
            return on
    return None


def _hue_battery(api: Any, services: dict[str, list[str]]) -> str:
    """The device's battery as the bridge reports it, or nothing."""
    store = _read(_read(api, "sensors"), "device_power")
    for rid in services.get("device_power", []):
        power = _read(_hue_resource(store, rid), "power_state")
        state = _plain(_read(power, "battery_state"))
        level = _read(power, "battery_level")
        parts = [
            f"{level}%" if isinstance(level, int) and not isinstance(level, bool) else "",
            str(state) if isinstance(state, str) else "",
        ]
        if any(parts):
            return "battery " + ", ".join(part for part in parts if part)
    return ""


def _hue_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Hue device's Zigbee connectivity, as the bridge judges it.

    The bridge says connected, disconnected, connectivity issue,
    unidirectional incoming (heard but not reachable) or pending
    discovery; Home Assistant makes that available or not. While the
    bridge's event stream is down nothing new arrives, Home Assistant
    keeps every entity on its last state, and the bridge's word is
    stale, so the row says so and gives no opinion. Hue's
    ignore list keeps a device's light available whatever the bridge
    says, and does nothing for a device without a light. A Green Power
    switch has no Zigbee link to report and is named. A v1 bridge
    exposes none of this and gives no rows.
    """
    rows: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(HUE_DOMAIN):
        bridge = _read(entry, "runtime_data")
        if _read(bridge, "api_version") != 2:
            continue
        api = _read(bridge, "api")
        devices = _read(api, "devices")
        lookup = _read(devices, "get_zigbee_connectivity")
        if not callable(lookup):
            continue
        stale = _hue_stream(api) != "CONNECTED"
        ignored = _option_list(entry, "ignore_availability")
        mapped = node_devices(hass, entry, HUE_DOMAIN)
        for device in _listed(devices):
            node_id = _read(device, "id")
            if not isinstance(node_id, str) or not node_id:
                continue
            services = _hue_services(device)
            if "bridge" in services:
                continue
            status = _plain(_read(_called(lookup, node_id), "status"))
            if not isinstance(status, str):
                now = (
                    "no link reported (Green Power)" if "zgp_connectivity" in services
                    else "no link reported"
                )
                quiet: bool | None = None
            else:
                now, quiet = status, status != "connected"
                if stale:
                    now, quiet = f"{status} (stale while the bridge stream is down)", None
            light_on = _hue_light_on(api, services)
            parts = []
            if node_id in ignored:
                parts.append(
                    "on Hue's ignore list, its light stays available" if "light" in services
                    else "on Hue's ignore list, which does nothing without a light"
                )
            if _read(_read(device, "product_data"), "certified") is False:
                parts.append("not Hue certified")
            parts.append(_hue_battery(api, services))
            rows.append({
                "stack": HUE_DOMAIN,
                "node": node_id[:8],
                "device_id": mapped.get(node_id, ""),
                "now": now,
                "quiet": quiet,
                "light_on": light_on,
                "detail": ", ".join(part for part in parts if part),
            })
    return rows


# SmartThings device types by how the device reaches the cloud: through
# a SmartThings hub, or on its own. The hub's own health is never
# published.
SMARTTHINGS_HUB_TYPES = frozenset({"HUB"})
SMARTTHINGS_BEHIND_HUB_TYPES = frozenset({"ZIGBEE", "ZWAVE", "MATTER", "LAN", "EDGE_CHILD"})
SMARTTHINGS_CLOUD_TYPES = frozenset({"VIPER", "OCF", "MOBILE", "ENDPOINT_APP", "BLE_D2D"})


def smartthings_network(kind: str) -> str:
    """How a SmartThings device reaches the cloud, from its type."""
    if kind in SMARTTHINGS_HUB_TYPES:
        return "a SmartThings hub"
    if kind in SMARTTHINGS_BEHIND_HUB_TYPES:
        return "behind a SmartThings hub"
    if kind in SMARTTHINGS_CLOUD_TYPES:
        return "on its own to the cloud"
    return "reach not known"


def _entity_availability(hass: HomeAssistant, device_id: str) -> tuple[str, bool | None]:
    """What Home Assistant shows for a device's enabled entities."""
    if not device_id:
        return "no device", None
    # Only SmartThings' own entities: another integration's entity on
    # the device, a Battery Notes battery type say, stays available
    # while the device is offline and is not the device speaking
    # (rule WATCH-02).
    states = [
        hass.states.get(entity.entity_id)
        for entity in er.async_entries_for_device(er.async_get(hass), device_id)
        if entity.platform == SMARTTHINGS_DOMAIN
    ]
    known = [state.state for state in states if state is not None]
    if not known:
        return "no entity states", None
    if all(state == "unavailable" for state in known):
        return "unavailable", True
    return "available", False


def _smartthings_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each SmartThings device's availability, and how it reaches the cloud.

    Home Assistant keeps a SmartThings entity available while the
    cloud says its device is online, live, so the stack's word is what
    the entities show. The online flag Home Assistant stores is set
    only at start and is not read. The device's type says whether it
    is a hub, sits behind one, or reaches the cloud on its own.
    """
    rows: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(SMARTTHINGS_DOMAIN):
        # Home Assistant moves a SmartThings entity's availability only
        # on health events, which arrive over the stream; with it down
        # every entity keeps its last word, so the rows say so and give
        # no opinion, as Hue's do.
        stale = _smartthings_stream_down(hass, entry)
        mapped = node_devices(hass, entry, SMARTTHINGS_DOMAIN)
        for full in _listed(_read(_read(entry, "runtime_data"), "devices")):
            device = _read(full, "device")
            node_id = _read(device, "device_id")
            if not isinstance(node_id, str) or not node_id:
                continue
            kind = _plain(_read(device, "type"))
            kind = kind.upper() if isinstance(kind, str) else "UNKNOWN"
            device_id = mapped.get(node_id, "")
            now, quiet = _entity_availability(hass, device_id)
            if stale and quiet is not None:
                now, quiet = f"{now} (stale while the cloud stream is down)", None
            parent = _read(device, "parent_device_id")
            firmware = _read(_read(device, "hub"), "firmware_version") if kind == "HUB" else None
            parts = [
                smartthings_network(kind),
                f"type {kind.lower()}",
                f"parent {parent[:8]}" if isinstance(parent, str) and parent else "",
                f"firmware {firmware}" if isinstance(firmware, str) and firmware else "",
            ]
            rows.append({
                "stack": SMARTTHINGS_DOMAIN,
                "node": node_id[:8],
                "device_id": device_id,
                "now": now,
                "quiet": quiet,
                "detail": ", ".join(part for part in parts if part),
            })
    return rows


def _tuya_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Tuya device's online flag, kept live by Tuya's cloud.

    Home Assistant makes a Tuya entity available exactly while its
    device reads online. A sub-device sits behind a Tuya gateway, so
    the line says which devices share one.
    """
    rows: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(TUYA_DOMAIN):
        manager = _read(_read(entry, "runtime_data"), "manager")
        mapped = node_devices(hass, entry, TUYA_DOMAIN)
        for device in _listed(_read(manager, "device_map") or {}):
            node_id = str(_read(device, "id") or "")
            online = bool(_read(device, "online"))
            parts = [
                part for part in (
                    "behind a Tuya gateway" if _read(device, "sub") else "",
                    f"category {_read(device, 'category')}" if _read(device, "category") else "",
                ) if part
            ]
            rows.append({
                "stack": TUYA_DOMAIN,
                "node": node_id[:8],
                "device_id": mapped.get(node_id, ""),
                "now": "online" if online else "offline",
                "quiet": not online,
                "detail": ", ".join(parts),
            })
    return rows


# What a Z-Wave controller says about itself (ControllerStatus).
_CONTROLLER_WORDS = {0: "ready", 1: "unresponsive", 2: "jammed"}


def _zwave_controller_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Z-Wave entry's client, driver and controller."""
    rows: list[dict[str, Any]] = []
    for entry, node in entry_nodes(live_entries(hass, ZWAVE_DOMAIN), "controller"):
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
            "node": node,
            "now": now,
            "detail": f"entry {state}",
        })
    return rows


def _matter_server_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Each Matter entry's server connection."""
    rows: list[dict[str, Any]] = []
    for entry, node in entry_nodes(live_entries(hass, MATTER_DOMAIN), "server"):
        client = _read(_read(_read(entry, "runtime_data"), "adapter"), "matter_client")
        connected = _read(_read(client, "connection"), "connected")
        state = getattr(entry.state, "value", str(entry.state))
        rows.append({
            "stack": MATTER_DOMAIN,
            "node": node,
            "now": "connected" if connected else "disconnected",
            "detail": f"entry {state}",
        })
    return rows


def live_entries(hass: HomeAssistant, domain: str) -> list[Any]:
    """A stack's entries that are set up to run: an ignored discovery or
    a disabled entry is not a controller, bridge, hub or cloud."""
    return hass.config_entries.async_entries(domain, include_ignore=False, include_disabled=False)


def entry_tags(entries: list[Any]) -> list[tuple[Any, str]]:
    """Each entry with the tag its nodes carry: nothing for a
    lone entry, and the end of the entry's id where there
    are several. The start of an id is a timestamp, which two entries
    made in one second share. Not the title: Hue titles an entry with
    its bridge's id, which is the bridge's address, and Tuya with the
    account's email or phone number, and stack_probe.md is a file
    people attach to issues.
    """
    if len(entries) <= 1:
        return [(entry, "") for entry in entries]
    return [(entry, str(_read(entry, "entry_id") or "")[-8:]) for entry in entries]


def tagged(tag: str, name: str) -> str:
    """A node's name with its entry's tag, where it has one."""
    return f"{name} {tag}" if tag else name


def entry_nodes(entries: list[Any], base: str) -> list[tuple[Any, str]]:
    """Each entry with a node name of its own.

    The probe keys a line by stack and node, so two Z-Wave networks,
    two bridges or two SmartThings locations sharing one name would
    read as one node flipping between two states, a line each minute.
    """
    return [(entry, tagged(tag, base)) for entry, tag in entry_tags(entries)]


HubReader = Callable[[HomeAssistant, Any], dict[str, Any]]


def _hub_rows(
    hass: HomeAssistant,
    domain: str,
    base: str,
    reader: HubReader,
    members: bool = False,
) -> list[dict[str, Any]]:
    """Each entry of a hub or cloud stack, through its reader.

    A reader gives what the entry says now and the detail that rides
    with it, and may add readings that change every minute; those are
    written with a line but never cause one. With members, the row
    also lists the entry's devices, so the recorder can say when
    Device Sentinel last heard any of them.
    """
    rows: list[dict[str, Any]] = []
    for entry, node in entry_nodes(live_entries(hass, domain), base):
        said = reader(hass, entry)
        state = getattr(entry.state, "value", str(entry.state))
        row: dict[str, Any] = {
            "stack": domain,
            "node": node,
            "now": str(said.get("now") or "unknown"),
            "detail": ", ".join(
                part for part in (str(said.get("detail") or ""), f"entry {state}") if part
            ),
        }
        for key in ("lost_at", "bridge_event"):
            if said.get(key) is not None:
                row[key] = said[key]
        if members:
            row["members"] = sorted(set(node_devices(hass, entry, domain).values()))
        rows.append(row)
    return rows


def coordinator_rows(
    hass: HomeAssistant,
    studied: set[str],
    on_failure: StackFailure | None = None,
) -> list[dict[str, Any]]:
    """Each studied stack's coordinator, one row per config entry.

    Z-Wave: the entry's state, whether the client's connection to the
    Z-Wave JS server is open, whether the driver is there, and the
    controller's own status. Matter: the entry's state and whether the
    server connection is open. A stick pulled or a server restarted
    shows here, which is what a reader must tell from a real outage.
    Hue: the bridge's event stream. SmartThings: the event stream to
    Samsung's cloud. A stack that throws is handed to on_failure and
    the others are read as usual.
    """
    rows: list[dict[str, Any]] = []
    readers: tuple[tuple[str, Callable[[], list[dict[str, Any]]]], ...] = (
        (ZWAVE_DOMAIN, lambda: _zwave_controller_rows(hass)),
        (MATTER_DOMAIN, lambda: _matter_server_rows(hass)),
        (HUE_DOMAIN, lambda: _hub_rows(hass, HUE_DOMAIN, "bridge", _hue_bridge, members=True)),
        (SMARTTHINGS_DOMAIN, lambda: _hub_rows(
            hass, SMARTTHINGS_DOMAIN, "cloud", _smartthings_cloud, members=True
        )),
        (TUYA_DOMAIN, lambda: _hub_rows(hass, TUYA_DOMAIN, "cloud", _tuya_cloud)),
        (LUTRON_DOMAIN, lambda: _hub_rows(hass, LUTRON_DOMAIN, "hub", _lutron_hub)),
    )
    for domain, read in readers:
        if domain not in studied:
            continue
        try:
            rows.extend(read())
        except Exception as err:  # noqa: BLE001 - a library behaving oddly
            _failed(on_failure, domain, err)
    return rows


# The event stream's status in words. The library sets
# CONNECTING at the start of every try to reconnect and holds it
# through the wait, so an outage samples as CONNECTING; it reads down.
HUE_STREAM_WORDS = {
    "CONNECTED": "connected",
    "CONNECTING": "down, retrying",
    "DISCONNECTED": "down, stopped",
}


def _hue_bridge(_hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """The Hue bridge's event stream, firmware and update state.

    A v2 bridge's entities do not go unavailable when the stream
    drops; they keep their last state, so the stream is the one sign
    of a bridge gone. The library's private record of when it last
    lost the stream, and the bridge's clock on the newest event it
    sent, are read too: recorded, never judged (rule STACK-08). A v1 bridge is
    polled, and the poll's last result is its sign.
    """
    bridge = _read(entry, "runtime_data")
    if bridge is None:
        return {"now": "not loaded"}
    if _read(bridge, "api_version") == 1:
        success = _read(_read(_read(bridge, "sensor_manager"), "coordinator"), "last_update_success")
        return {
            "now": (
                "v1 bridge, polling" if success is True
                else "v1 bridge, polling failing" if success is False
                else "v1 bridge, not read"
            ),
        }
    api = _read(bridge, "api")
    stream = _hue_stream(api)
    config = _read(api, "config")
    firmware = _read(config, "software_version")
    bridge_id = _read(_read(config, "bridge_device"), "id")
    update = (
        _plain(_read(_called(_read(_read(api, "devices"), "get_software_update"), bridge_id), "state"))
        if isinstance(bridge_id, str) else None
    )
    parts = [
        f"firmware {firmware}" if isinstance(firmware, str) and firmware else "",
        f"update {str(update).replace('_', ' ')}" if isinstance(update, str) and update != "no_update" else "",
    ]
    said: dict[str, Any] = {
        "now": HUE_STREAM_WORDS.get(stream, "unknown") if stream else "unknown",
        "detail": ", ".join(part for part in parts if part),
    }
    lost = _read(api, "_disconnect_timestamp")
    if isinstance(lost, (int, float)) and not isinstance(lost, bool) and lost > 0:
        said["lost_at"] = float(lost)
    history = _read(_read(api, "events"), "last_events")
    try:
        newest = history[-1] if history else None
    except Exception as err:  # noqa: BLE001 - a library's container
        LOGGER.debug("device_sentinel: Hue event history unreadable (%s)", err)
        newest = None
    stamp = newest.get("creationtime") if isinstance(newest, dict) else None
    if isinstance(stamp, str) and stamp:
        said["bridge_event"] = stamp[:40]
    return said


def _smartthings_task(entry: Any) -> str:
    """Whether the entry's event stream task is running.

    Home Assistant holds an entry's background tasks in a private set
    and drops each one as it ends; the SmartThings stream is the task
    named "smartthings_socket" (rule STACK-08).
    """
    tasks = _read(entry, "_background_tasks")
    if tasks is None:
        return "not read"
    try:
        held = list(tasks)
    except Exception as err:  # noqa: BLE001 - a private container
        LOGGER.debug("device_sentinel: SmartThings tasks unreadable (%s)", err)
        return "not read"
    for task in held:
        if _called(_read(task, "get_name")) == "smartthings_socket":
            return "stopped" if _called(_read(task, "done")) is True else "running"
    return "stopped"


def _smartthings_retries(client: Any) -> str:
    """The stream's retry count and the wait it implies.

    pysmartthings waits two to the power of the count, in seconds,
    with no ceiling, and sets the count back to nought when the stream
    opens. The count is private (rule STACK-08).
    """
    count = _read(client, "_SmartThings__retry_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return ""
    wait = f"{2 ** count} s" if count <= 16 else "over 18 hours"
    return f"retry {count}, wait {wait}"


def _smartthings_reauth(hass: HomeAssistant, entry: Any) -> bool:
    """Whether Home Assistant is asking for SmartThings to be signed in again."""
    flows = _called(_read(entry, "async_get_active_flows"), hass, {"reauth"})
    if flows is None:
        return False
    try:
        return any(True for _flow in flows)
    except Exception as err:  # noqa: BLE001 - a flow manager
        LOGGER.debug("device_sentinel: SmartThings flows unreadable (%s)", err)
        return False


def _smartthings_stream_down(hass: HomeAssistant, entry: Any) -> bool:
    """Whether the entry's event stream is known to be down: not
    loaded, waiting to be signed in again, its task ended, or retrying.
    A task Device Sentinel cannot read is not taken as down."""
    if getattr(_read(entry, "state"), "value", None) != "loaded":
        return True
    if _smartthings_reauth(hass, entry):
        return True
    if _smartthings_task(entry) == "stopped":
        return True
    return bool(_smartthings_retries(_read(_read(entry, "runtime_data"), "client")))


def _smartthings_cloud(hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """The SmartThings entry's event stream to Samsung's cloud.

    The stream is the task that carries every device's events and its
    online or offline, so a dead task leaves Home Assistant on its
    last word for every device. Home Assistant keeps the stream's
    subscription id in the entry and replaces it when the stream is
    made again; its first eight characters ride with the line, so a
    change of subscription is a line.
    """
    data = _read(entry, "data")
    subscription = data.get("subscription_id") if isinstance(data, Mapping) else None
    state = getattr(_read(entry, "state"), "value", None)
    retries = (
        _smartthings_retries(_read(_read(entry, "runtime_data"), "client"))
        if state == "loaded" else ""
    )
    if _smartthings_reauth(hass, entry):
        now = "needs signing in again"
    elif state != "loaded":
        now = "not loaded"
    else:
        task = _smartthings_task(entry)
        now = (
            f"stream {task}" if task != "running"
            else "stream retrying" if retries
            else "stream running"
        )
    reason = _read(entry, "reason") if state != "loaded" else None
    parts = [
        f"subscription {subscription[:8]}" if isinstance(subscription, str) and subscription
        else "no subscription",
        retries,
        f"reason {reason}" if isinstance(reason, str) and reason else "",
    ]
    return {"now": now, "detail": ", ".join(part for part in parts if part)}


def _tuya_cloud(_hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Whether Tuya's cloud push connection is up."""
    queue = _read(_read(_read(entry, "runtime_data"), "manager"), "mq")
    if queue is None:
        return {"now": "no cloud link"}
    check = _read(_read(queue, "client"), "is_connected")
    try:
        connected = bool(check()) if callable(check) else False
    except Exception as err:  # noqa: BLE001 - a library call
        LOGGER.debug("device_sentinel: Tuya connection unreadable (%s)", err)
        return {"now": "unknown"}
    return {"now": "connected" if connected else "disconnected"}


def _lutron_hub(_hass: HomeAssistant, entry: Any) -> dict[str, Any]:
    """Whether the Lutron library holds a live session with its hub.

    The Lutron integration checks its hub once, at setup, and its
    entities never go unavailable after, so an outage leaves every
    light showing its last state. The library drops its session on
    every failure and makes a new one on every reconnect; that session
    is the honest signal, read from a private attribute. Its own
    is_connected() answers from a login marker that is never reset,
    and is recorded beside the session to show it.
    """
    bridge = _read(_read(entry, "runtime_data"), "bridge")
    if bridge is None:
        return {"now": "not loaded"}
    session = "session held" if getattr(bridge, "_leap", None) is not None else "no session"
    check = _read(bridge, "is_connected")
    try:
        said = ("says connected" if check() else "says not connected") if callable(check) else ""
    except Exception as err:  # noqa: BLE001 - a library call
        LOGGER.debug("device_sentinel: Lutron connection unreadable (%s)", err)
        said = ""
    return {"now": session, "detail": f"library {said}" if said else ""}
