# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/matter_mesh.py, Version: 0.30.7 (2026-11-26)

"""The Thread mesh as the Matter server's own map shows it (rule STACK-18).

The Matter server keeps a map of the Thread mesh: each device's role
(router, end device, sleepy end device), each border router, and the
strength of each link. Home Assistant draws it on its Matter panel
(since 2026.9), so Device Sentinel draws no second map. It shows each
Matter device's role and link on its page, and the Thread network on the
Networks tab, with a link to Home Assistant's map.

Read through the Matter client Home Assistant already holds, as the
Extended Diagnostics study reads it, never by importing Matter
(rule STACK-08). The map is asked for every ten minutes, never
refreshed: a refresh reads every device over the radio. The map can lag
a few minutes, and a router taken away can stay on it, so a role is a
hint and never proof a device is alive. Nothing here changes a verdict.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import LOGGER, STACK_MATTER

# How often the map is asked for, and how long one answer may take, in seconds.
MESH_SECONDS = 600.0
MESH_WAIT_SECONDS = 30.0
# The server's map needs its schema 13 or later.
MESH_SCHEMA = 13
# Home Assistant's own map counts these roles as routers.
ROUTER_ROLES = frozenset({"leader", "router", "reed"})
SLEEPY_ROLE = "sleepy_end_device"
END_ROLE = "end_device"
# How Home Assistant's Matter panel opens its map.
MATTER_MAP_PATH = "/config/matter/visualization"
ROLE_WORDS = {
    "leader": "Router (leader)", "router": "Router", "reed": "Router-eligible end device",
    END_ROLE: "End device", SLEEPY_ROLE: "Sleepy end device",
}
STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}


def matter_client(hass: Any) -> Any:
    """Home Assistant's own Matter client, or None."""
    for entry in hass.config_entries.async_entries(STACK_MATTER, include_ignore=False, include_disabled=False):
        adapter = getattr(getattr(entry, "runtime_data", None), "adapter", None)
        client = getattr(adapter, "matter_client", None)
        if client is not None:
            return client
    return None


def plain(value: Any) -> Any:
    """A map as plain data, whichever shape the client hands back."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return value if isinstance(value, dict) else None


def node_of(identifiers: Any) -> int | None:
    """A Matter node's number from its device's identifier, or None.

    Home Assistant names a Matter node's device
    "deviceid_<fabric>-<node in hex>-MatterNodeDevice"; a device behind a
    bridge carries a fourth part and is not a node of its own."""
    for identifier in identifiers or ():
        if not isinstance(identifier, (tuple, list)) or len(identifier) < 2:
            continue
        domain, ident = identifier[0], identifier[1]
        if domain != STACK_MATTER or not isinstance(ident, str) or not ident.startswith("deviceid_"):
            continue
        parts = ident.split("-")
        if len(parts) == 3 and parts[2] == "MatterNodeDevice":
            try:
                return int(parts[1], 16)
            except ValueError:
                return None
    return None


class MatterMeshMixin:
    """The coordinator's side of the Thread role."""

    def _mesh_state(self) -> dict[str, Any]:
        if "_mesh" not in self.__dict__:
            self._mesh = {"graph": None, "at": None, "busy": False}
        return self._mesh

    @callback
    def mesh_tick(self, now: float) -> None:
        """Ask for the map when it is due, in the background (rule STACK-18)."""
        mesh = self._mesh_state()
        if mesh["busy"] or (mesh["at"] is not None and now - mesh["at"] < MESH_SECONDS):
            return
        client = matter_client(self.hass)  # type: ignore[attr-defined]
        if client is None:
            mesh["graph"] = None
            return
        info = getattr(client, "server_info", None)
        schema = getattr(info, "schema_version", None)
        if not isinstance(schema, int) or schema < MESH_SCHEMA or not callable(getattr(client, "get_network_topology", None)):
            mesh["graph"] = None
            mesh["at"] = now
            return
        mesh["busy"] = True
        self.hass.async_create_background_task(  # type: ignore[attr-defined]
            self._mesh_fetch(client, now), "device_sentinel matter mesh"
        )

    async def _mesh_fetch(self, client: Any, now: float) -> None:
        mesh = self._mesh_state()
        try:
            # Never refreshed: a refresh reads every device over the radio.
            mesh["graph"] = plain(await asyncio.wait_for(client.get_network_topology(refresh=False), MESH_WAIT_SECONDS))
        except Exception as err:  # noqa: BLE001 - another integration's client
            LOGGER.debug("device_sentinel: the Matter map could not be read: %s", err)
        finally:
            mesh["at"] = now
            mesh["busy"] = False

    def _mesh_parts(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]] | None:
        graph = self._mesh_state()["graph"]
        if not isinstance(graph, dict):
            return None
        nodes = {
            str(node.get("id")): node for node in graph.get("nodes") or []
            if isinstance(node, dict) and node.get("id") is not None
        }
        links = [
            link for link in graph.get("connections") or []
            if isinstance(link, dict) and link.get("network") == "thread" and link.get("strength") not in (None, "none")
            and str(link.get("source")) in nodes and str(link.get("target")) in nodes
        ]
        return nodes, links

    def _mesh_devices(self) -> dict[int, str]:
        """Each Matter node's device in Home Assistant, by its node number."""
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        found: dict[int, str] = {}
        for entry in self.hass.config_entries.async_entries(STACK_MATTER):  # type: ignore[attr-defined]
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                node = node_of(device.identifiers)
                if node is not None:
                    found[node] = device.id
        return found

    def _mesh_name(self, node: dict[str, Any], devices: dict[int, str]) -> str:
        number = node.get("node_id")
        if isinstance(number, int) and number in devices:
            return str(self._device_name(devices[number]))  # type: ignore[attr-defined]
        return str(node.get("host_name") or node.get("model_name") or node.get("ext_address") or "Unknown device")

    @staticmethod
    def _is_router(node: dict[str, Any]) -> bool:
        return node.get("kind") == "border_router" or node.get("role") in ROUTER_ROLES

    def _mesh_rows(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[int, str]] | None:
        """Each router with what it carries, and each node's best link to a router."""
        parts = self._mesh_parts()
        if parts is None:
            return None
        nodes, links = parts
        routers: dict[str, dict[str, Any]] = {}
        best: dict[str, dict[str, Any]] = {}
        for link in links:
            ends = (nodes[str(link["source"])], nodes[str(link["target"])])
            for here, there in (ends, ends[::-1]):
                if self._is_router(here):
                    row = routers.setdefault(str(here["id"]), {"node": here, "carries": 0})
                    if there.get("role") in (END_ROLE, SLEEPY_ROLE):
                        row["carries"] += 1
                if self._is_router(there):
                    rank = STRENGTH_RANK.get(str(link.get("strength")), 0)
                    held = best.get(str(here["id"]))
                    if held is None or rank > held["rank"]:
                        best[str(here["id"])] = {"rank": rank, "strength": link.get("strength"), "to": there}
        return routers, best, self._mesh_devices()

    def device_thread(self, device_id: str) -> dict[str, Any] | None:
        """The device's Thread role, what it carries and its best link, or None."""
        rows = self._mesh_rows()
        if rows is None:
            return None
        routers, best, devices = rows
        device = dr.async_get(self.hass).async_get(device_id)  # type: ignore[attr-defined]
        number = node_of(getattr(device, "identifiers", None))
        if number is None:
            return None
        parts = self._mesh_parts()
        node = next((n for n in (parts[0] if parts else {}).values() if n.get("node_id") == number), None)
        if node is None or node.get("network_type") != "thread":
            return None
        link = best.get(str(node["id"]))
        router = routers.get(str(node["id"]))
        return {
            "role": node.get("role"),
            "role_words": ROLE_WORDS.get(str(node.get("role")), "Unknown"),
            "carries": router["carries"] if router else None,
            "link": {"strength": link["strength"], "to": self._mesh_name(link["to"], devices)} if link else None,
            "network": node.get("network_name"),
            "map_path": MATTER_MAP_PATH,
        }

    def thread_view(self) -> dict[str, Any] | None:
        """The Thread network for the Networks tab, or None without a map."""
        rows = self._mesh_rows()
        parts = self._mesh_parts()
        if rows is None or parts is None:
            return None
        routers, best, devices = rows
        thread = [n for n in parts[0].values() if n.get("network_type") == "thread"]
        if not thread:
            return None
        names = sorted({str(n.get("network_name")) for n in thread if n.get("network_name")})
        listed = sorted(
            routers.values(),
            key=lambda row: (row["node"].get("kind") != "border_router", -row["carries"], self._mesh_name(row["node"], devices).casefold()),
        )
        return {
            "networks": names,
            "border_routers": sum(1 for n in thread if n.get("kind") == "border_router"),
            "routers": sum(1 for n in thread if n.get("kind") != "border_router" and n.get("role") in ROUTER_ROLES),
            "end_devices": sum(1 for n in thread if n.get("role") == END_ROLE),
            "sleepy": sum(1 for n in thread if n.get("role") == SLEEPY_ROLE),
            "rows": [
                {
                    "name": self._mesh_name(row["node"], devices),
                    "device_id": devices.get(row["node"].get("node_id")) if isinstance(row["node"].get("node_id"), int) else None,
                    "role": "Border router" if row["node"].get("kind") == "border_router" else ROLE_WORDS.get(str(row["node"].get("role")), "Router"),
                    "carries": row["carries"],
                    "link": (best.get(str(row["node"]["id"])) or {}).get("strength"),
                }
                for row in listed
            ],
            "map_path": MATTER_MAP_PATH,
            "read_at": self._mesh_state()["at"],
        }


def mesh_age(at: Any) -> float | None:
    """Seconds since the map was read, or None."""
    return time.time() - at if isinstance(at, (int, float)) and not isinstance(at, bool) else None
