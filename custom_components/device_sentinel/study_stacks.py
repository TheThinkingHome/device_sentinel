# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_stacks.py, Version: 0.22.26 (2026-09-23)

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

from typing import Any

from homeassistant.core import HomeAssistant

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
    """Return something a JSON file can hold, or its type's name."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
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
            status = _plain(_read(node, "status"))
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
                "network": _plain(
                    _read(node, "network_type") or _read(node, "transport")
                ),
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
    return {"fabrics": fabrics, "thread": await _thread_network(hass)}


async def _thread_network(hass: HomeAssistant) -> dict[str, Any]:
    """Whether a Thread network and a border router are configured."""
    found: dict[str, Any] = {
        "integration_loaded": "thread" in hass.config.components,
        "border_router_loaded": "otbr" in hass.config.components,
    }
    if not found["integration_loaded"]:
        return found
    try:
        from homeassistant.components.thread import async_get_preferred_dataset

        dataset = await async_get_preferred_dataset(hass)
    except Exception as err:  # noqa: BLE001 - an optional integration
        LOGGER.debug("device_sentinel: Thread dataset unreadable: %s", err)
        return found
    # The dataset itself is a network credential and is never
    # recorded; that one exists is the whole fact needed here.
    found["preferred_dataset"] = dataset is not None
    return found


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
    status = str(_plain(_read(node, "status")))
    stats = _statistics(node, _NODE_STATISTICS)
    detail = ", ".join(f"{name} {value}" for name, value in stats.items())
    return status, detail


def probe_rows(hass: HomeAssistant, studied: set[str]) -> list[dict[str, Any]]:
    """What each studied stack's nodes say right now, one row each."""
    rows: list[dict[str, Any]] = []
    if ZWAVE_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(ZWAVE_DOMAIN):
            controller = _read(
                _read(_read(_read(entry, "runtime_data"), "client"), "driver"),
                "controller",
            )
            nodes = _read(controller, "nodes") or {}
            try:
                listed = list(nodes.values())
            except Exception as err:  # noqa: BLE001 - not a mapping
                LOGGER.debug(
                    "device_sentinel: Z-Wave nodes unreadable (%s)", err
                )
                listed = []
            for node in listed:
                status, detail = _node_state(node)
                rows.append({
                    "stack": ZWAVE_DOMAIN,
                    "node": str(_plain(_read(node, "node_id"))),
                    "now": status,
                    "detail": detail,
                })
    if MATTER_DOMAIN in studied:
        for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
            client = _read(
                _read(_read(entry, "runtime_data"), "adapter"), "matter_client"
            )
            getter = _read(client, "get_nodes")
            if not callable(getter):
                continue
            try:
                listed = list(getter())
            except Exception as err:  # noqa: BLE001 - a library call
                LOGGER.debug(
                    "device_sentinel: Matter nodes unreadable (%s)", err
                )
                listed = []
            for node in listed:
                rows.append({
                    "stack": MATTER_DOMAIN,
                    "node": str(_plain(_read(node, "node_id"))),
                    "now": "available" if _read(node, "available") else "away",
                    "detail": str(
                        _plain(
                            _read(node, "network_type")
                            or _read(node, "transport")
                            or ""
                        )
                    ),
                })
    return rows[:NODE_ROW_CAP * 4]
