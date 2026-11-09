# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: networks.py, Version: 0.28.7 (2026-11-09)

"""The Networks tab and each network's page (rule DASH-17).

A network is what a device reports through: a radio stack (Zigbee2MQTT,
ZHA, Z-Wave, Matter), Wi-Fi, the MQTT broker, or a hub such as a Lutron
Caseta Smart Bridge. A network appears only where the house has it.

Everything here is read from what Device Sentinel already keeps: the
registry walk's radio owner, the Wi-Fi ties, the hub map, the system
events, the problem list and the signal and drop records. Nothing new is
stored, and nothing here changes another integration's settings (rule
STACK-13). A sensor switched off is offered back one device at a time,
through the same action as the device page (rule REC-05).

A device sits on one network: its radio stack, else its hub, else
Wi-Fi. A device that reaches Home Assistant through the broker is also
counted under the broker, since the broker failing takes it down too.
A Zigbee2MQTT device is not: Zigbee2MQTT is its network, and the
broker's outages are shown on Zigbee2MQTT's page instead.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BRIDGE_BINDING,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BROKER_DOWN,
    BROKER_RIDER_DOMAINS,
    BROKER_RUNNING,
    BROKER_SCOPE,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_CONTROLLER_STATUS,
    STACK_DISPLAY_NAMES,
    STACK_MATTER,
    STACK_Z2M,
    STACK_ZHA,
    STACK_ZWAVE,
    SYS_BRIDGE_DOWN,
    SYS_BROKER_DOWN,
    SYS_DURATION,
    SYS_INTEGRATION_DOWN,
    SYS_KIND,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WIFI_DOWN,
    TODO_DEVICE_ID,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_FLAPPING,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_KINDS,
    TODO_STATUS,
    WIFI_BAND_NAME,
    WIFI_KEY,
)
from .const import ADDR_AP, DEV_SIGNAL_DAILY_P5, LOGGER
from .daily_dates import FAMILY_SIGNAL, dates_for
from .device_fields import device_field

# How far back a network page looks: outages, pairing and new devices.
NETWORK_WINDOW_DAYS = 30
# The days "this week" covers on Signal Health.
NETWORK_WEEK_DAYS = 7
# A hub's network key is this and the hub's device id.
HUB_PREFIX = "hub:"
# A hub's outages come from its unavailable incidents, which are kept 14
# days, so a hub's page looks back 14 days, and says so.
HUB_WINDOW_DAYS = 14
# The order the tab lists them in; hubs follow, by name.
NETWORK_ORDER = (STACK_Z2M, STACK_ZHA, STACK_ZWAVE, STACK_MATTER, WIFI_KEY, BROKER_SCOPE)
BROKER_NETWORK_NAME = "MQTT Broker"

# Each problem kind's group, as the network page's tiles and the Devices
# tab's Problem filter count them.
PROBLEM_GROUP_OF = {
    TODO_KIND_FROZEN: "frozen",
    TODO_KIND_UNAVAILABLE: "unavailable",
    TODO_KIND_UNKNOWN: "unavailable",
    TODO_KIND_NEVER_REPORTED: "never_reported",
    TODO_KIND_LOW_BATTERY: "battery",
    TODO_KIND_FALLING_BATTERY: "battery",
    TODO_KIND_RAILED_SIGNAL: "signal",
    TODO_KIND_FLAPPING: "drops",
}
PROBLEM_GROUPS = ("frozen", "unavailable", "never_reported", "battery", "signal", "drops")

# The sensors each network's devices are expected to have, in the order
# the page lists them. Each is a kind the device page can switch on.
SENSOR_KINDS = {
    STACK_Z2M: ("last_seen", "signal", "battery", "firmware"),
    STACK_ZHA: ("signal", "battery", "firmware"),
    STACK_ZWAVE: ("node_status", "signal", "battery", "firmware"),
    STACK_MATTER: ("battery", "firmware"),
    WIFI_KEY: ("signal", "firmware"),
    BROKER_SCOPE: ("signal", "firmware"),
}
SENSOR_LABELS = {
    "last_seen": "Last Seen sensors",
    "node_status": "Z-Wave status sensors",
    "signal": "Signal sensors",
    "battery": "Battery sensors",
    # Home Assistant's firmware update entities (rule DASH-18).
    "firmware": "Firmware update checks",
}
# Zigbee2MQTT's own word for its signal sensor.
Z2M_SIGNAL_LABEL = "Link quality sensors"


def problem_groups(kinds: Any) -> list[str]:
    """The problem groups a problem list item's kinds fall in, in the
    tiles' order."""
    if not isinstance(kinds, dict):
        return []
    found = {PROBLEM_GROUP_OF[kind] for kind in kinds if kind in PROBLEM_GROUP_OF}
    return [group for group in PROBLEM_GROUPS if group in found]


def _status_rank(status: tuple[str, float, bool]) -> tuple[bool, float]:
    """Not Ready before Ready, then the newer."""
    return (status[0].strip().lower() != "ready", status[1])


# ZHA's radio types as their makers write them.
ZHA_RADIO_NAMES = {"ezsp": "EZSP", "znp": "ZNP", "deconz": "deCONZ", "zigate": "ZiGate", "xbee": "XBee"}


def _iso(stamp: Any) -> str | None:
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    return dt_util.utc_from_timestamp(float(stamp)).isoformat()


def _stamp(iso: Any) -> float | None:
    if not isinstance(iso, str):
        return None
    moment = dt_util.parse_datetime(iso)
    return moment.timestamp() if moment is not None else None


class NetworksMixin:
    """The Networks tab, mixed into the coordinator (rule DASH-17)."""

    _radio_stack: dict[str, str]

    # ------------------------------------------------------- membership

    def device_networks(self, device_id: str) -> list[str]:
        """The networks one watched device reports through.

        Its radio stack, else its hub (or the hub itself), else Wi-Fi.
        Then the broker, for a device whose integration reaches Home
        Assistant through it.
        """
        found: list[str] = []
        stack = self._radio_stack.get(device_id)
        if stack is not None:
            found.append(stack)
        else:
            # Only a hub Device Sentinel watches is a network: one it
            # does not has no record, so no state, outages or page.
            hub = self.hub_of(device_id)  # type: ignore[attr-defined]
            if hub is not None and self.is_hub(hub) and hub in self._watched:  # type: ignore[attr-defined]
                found.append(HUB_PREFIX + hub)
            elif self.is_hub(device_id):  # type: ignore[attr-defined]
                found.append(HUB_PREFIX + device_id)
            elif device_id in self._wifi_ties:  # type: ignore[attr-defined]
                found.append(WIFI_KEY)
        domain = self._watched.get(device_id)  # type: ignore[attr-defined]
        if domain in BROKER_RIDER_DOMAINS or (domain == BROKER_SCOPE and stack != STACK_Z2M):
            found.append(BROKER_SCOPE)
        return found

    def _network_members(self) -> dict[str, list[str]]:
        members: dict[str, list[str]] = {}
        for device_id in self._watched:  # type: ignore[attr-defined]
            for key in self.device_networks(device_id):
                members.setdefault(key, []).append(device_id)
        return members

    def _mqtt_configured(self) -> bool:
        return self._entries_state(BROKER_SCOPE) is not None

    def network_keys(self, members: dict[str, list[str]] | None = None) -> list[str]:
        """The networks this house has, in the tab's order."""
        members = self._network_members() if members is None else members
        stacks = set(getattr(self, "_stacks", set()) or set())
        stacks.update(self.bridge_stacks)  # type: ignore[attr-defined]
        keys: list[str] = []
        for key in NETWORK_ORDER:
            if key == WIFI_KEY:
                have = (
                    key in members
                    or self.wifi_capable  # type: ignore[attr-defined]
                    or self.wifi_scan_configured  # type: ignore[attr-defined]
                )
            elif key == BROKER_SCOPE:
                have = key in members or (
                    self._mqtt_configured() and self._broker_reader is not None  # type: ignore[attr-defined]
                )
            else:
                # A stack whose integration is excluded, with no device
                # of its own watched, is not listed.
                domain = BROKER_SCOPE if key == STACK_Z2M else key
                have = key in members or (
                    key in stacks and domain not in self.excluded_integrations  # type: ignore[attr-defined]
                )
            if have:
                keys.append(key)
        hubs = {
            HUB_PREFIX + hub for hub in getattr(self, "_hub_entry", {})
            if hub in self._watched  # type: ignore[attr-defined]
        }
        hubs.update(key for key in members if key.startswith(HUB_PREFIX))
        keys.extend(sorted(hubs, key=lambda key: self.network_name(key).lower()))
        return keys

    def network_name(self, key: str) -> str:
        """What a person calls a network."""
        if key.startswith(HUB_PREFIX):
            hub = key[len(HUB_PREFIX):]
            domain = self._watched.get(hub) or ""  # type: ignore[attr-defined]
            title = self._integration_title(domain) if domain else ""  # type: ignore[attr-defined]
            name = self._device_name(hub)  # type: ignore[attr-defined]
            return f"{title}: {name}" if title else name
        if key == WIFI_KEY:
            return WIFI_BAND_NAME
        if key == BROKER_SCOPE:
            return BROKER_NETWORK_NAME
        return STACK_DISPLAY_NAMES.get(key, key)

    # ----------------------------------------------------------- status

    def _entries_state(self, domain: str) -> str | None:
        """"loaded", "not_loaded", or None where the integration is not set up."""
        entries = [
            entry for entry in self.hass.config_entries.async_entries(domain)  # type: ignore[attr-defined]
            if entry.disabled_by is None and entry.source != "ignore"
        ]
        if not entries:
            return None
        if any(entry.state is ConfigEntryState.LOADED for entry in entries):
            return "loaded"
        return "not_loaded"

    def _controller_status(self) -> tuple[str, float, bool] | None:
        """The Z-Wave controller's recorded Status, and since when (rule
        STACK-15). With two controllers, one not Ready is told before one
        that is, the newest first within each."""
        newest: tuple[str, float, bool] | None = None
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        for device_id in self._watched:  # type: ignore[attr-defined]
            record = records.get(device_id)
            pairs = record.get(DEV_CONTROLLER_STATUS) if isinstance(record, dict) else None
            if not isinstance(pairs, list) or not pairs:
                continue
            last = pairs[-1]
            if (
                isinstance(last, (list, tuple)) and len(last) == 2
                and isinstance(last[0], str)
                and isinstance(last[1], (int, float)) and not isinstance(last[1], bool)
            ):
                # Whether this is the only reading, dated when it was first
                # read rather than when it began.
                candidate = (last[0], float(last[1]), len(pairs) == 1)
                if newest is None or _status_rank(candidate) > _status_rank(newest):
                    newest = candidate
        return newest

    def _open_since(self, kind: str, scope: Any) -> str | None:
        """When the newest down of this kind and scope began, if no return
        has followed it."""
        rows = [
            row for row in self.data.get(DATA_SYSTEM_EVENTS) or []  # type: ignore[attr-defined]
            if isinstance(row, dict) and row.get(SYS_SCOPE) == scope
            and isinstance(row.get(SYS_WHEN), (int, float))
        ]
        rows.sort(key=lambda row: row[SYS_WHEN])
        since = None
        for row in rows:
            if row.get(SYS_KIND) == kind:
                since = row[SYS_WHEN]
            elif since is not None and row.get(SYS_KIND) == kind.replace("_down", "_up"):
                since = None
        return _iso(since)

    def network_status(self, key: str) -> dict[str, Any]:
        """The network's state: "ok", "pairing", "down", "warn" or
        "unknown", its words, and since when where known."""
        if key.startswith(HUB_PREFIX):
            hub = key[len(HUB_PREFIX):]
            down = self.hub_down_since(hub)  # type: ignore[attr-defined]
            if down is not None:
                return {"state": "down", "words": "Hub down", "since": _iso(down)}
            return {"state": "ok", "words": "Connected", "since": None}
        if key == WIFI_KEY:
            down = self.wifi_down_at  # type: ignore[attr-defined]
            if down is not None:
                return {"state": "down", "words": "Down", "since": _iso(down)}
            return {"state": "ok", "words": "Running", "since": None}
        if key == BROKER_SCOPE:
            if self._entries_state(BROKER_SCOPE) == "not_loaded":
                return {"state": "down", "words": "Integration not loaded", "since": None}
            state = self.broker_state  # type: ignore[attr-defined]
            if state == BROKER_DOWN:
                return {"state": "down", "words": "Down", "since": self._open_since(SYS_BROKER_DOWN, BROKER_SCOPE)}
            if state == BROKER_RUNNING:
                return {"state": "ok", "words": "Running", "since": None}
            return {"state": "unknown", "words": "Not heard from yet", "since": None}
        # Zigbee2MQTT reaches Home Assistant through the MQTT integration,
        # and its bridge reader keeps its last reading while that is not
        # loaded, so the integration is asked first.
        if key == STACK_Z2M and self._entries_state(BROKER_SCOPE) == "not_loaded":
            return {"state": "down", "words": "Integration not loaded", "since": None}
        bridge = self.bridge_state(key)  # type: ignore[attr-defined]
        if bridge is not None:
            if bridge == BRIDGE_RUNNING:
                return {"state": "ok", "words": "Running", "since": None}
            if bridge == BRIDGE_BINDING:
                return {"state": "pairing", "words": "Pairing open", "since": None}
            if bridge == BRIDGE_DOWN:
                return {"state": "down", "words": "Down", "since": self._open_since(SYS_BRIDGE_DOWN, key)}
            return {"state": "unknown", "words": "Not heard from yet", "since": None}
        if key == STACK_ZWAVE and self._entries_state(STACK_ZWAVE) == "loaded":
            # Only while Z-Wave JS runs: the last status recorded stays
            # in the record when the integration stops.
            status = self._controller_status()
            if status is not None:
                value, since, first = status
                ready = value.strip().lower() == "ready"
                return {
                    "state": "ok" if ready else "down",
                    "words": f"Controller {value.strip().capitalize()}",
                    # A first reading's moment is when it was read, not
                    # when it began, so no "since" is given for it.
                    "since": None if first else _iso(since),
                }
        # Zigbee2MQTT's devices come through the MQTT integration.
        loaded = self._entries_state(BROKER_SCOPE if key == STACK_Z2M else key)
        if loaded == "loaded":
            return {"state": "ok", "words": "Integration loaded", "since": None}
        if loaded == "not_loaded":
            return {"state": "down", "words": "Integration not loaded", "since": None}
        return {"state": "unknown", "words": "Not set up", "since": None}

    # ---------------------------------------------------------- problems

    def _problem_groups_by_device(self) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for item in self.todo_items:  # type: ignore[attr-defined]
            found[item[TODO_DEVICE_ID]] = {
                "groups": problem_groups(item.get(TODO_KINDS)),
                "acknowledged": item.get(TODO_STATUS) == "completed",
            }
        return found

    @staticmethod
    def _count_groups(
        members: list[str], problems: dict[str, dict[str, Any]]
    ) -> tuple[int, dict[str, int]]:
        counts = {group: 0 for group in PROBLEM_GROUPS}
        with_problem = 0
        for device_id in members:
            problem = problems.get(device_id)
            if problem is None:
                continue
            with_problem += 1
            for group in problem["groups"]:
                counts[group] += 1
        return with_problem, counts

    # ----------------------------------------------------------- outages

    def network_window(self, key: str) -> int:
        """How many days a network's outages go back."""
        return HUB_WINDOW_DAYS if key.startswith(HUB_PREFIX) else NETWORK_WINDOW_DAYS

    def network_outages(self, key: str, days: int | None = None) -> list[dict[str, Any]]:
        """The network's outages in the last `days` days, newest first.

        Each: when it went down, how long, how many devices went with it,
        what went down, and whether it still stands.
        """
        days = self.network_window(key) if days is None else days
        if key.startswith(HUB_PREFIX):
            hub = key[len(HUB_PREFIX):]
            rows = []
            for outage in self.hub_outages(hub, days):  # type: ignore[attr-defined]
                start, end = _stamp(outage.get("start")), _stamp(outage.get("end"))
                if start is None:
                    continue
                rows.append({
                    "went_down": outage["start"],
                    "what": f"{self._device_name(hub)} went down",  # type: ignore[attr-defined]
                    "duration": end - start if end is not None else None,
                    # How many went with it is not recorded for a hub.
                    "devices": None,
                    "open": end is None,
                })
            return rows
        wanted: list[tuple[str, Any]] = []
        if key == WIFI_KEY:
            wanted = [(SYS_WIFI_DOWN, WIFI_KEY)]
        elif key == BROKER_SCOPE:
            wanted = [(SYS_BROKER_DOWN, BROKER_SCOPE), (SYS_INTEGRATION_DOWN, BROKER_SCOPE)]
        elif key == STACK_Z2M:
            # Zigbee2MQTT reaches Home Assistant through the broker, so
            # the broker's outages took its devices too.
            wanted = [
                (SYS_BRIDGE_DOWN, STACK_Z2M),
                (SYS_BROKER_DOWN, BROKER_SCOPE),
                (SYS_INTEGRATION_DOWN, BROKER_SCOPE),
            ]
        else:
            wanted = [(SYS_BRIDGE_DOWN, key), (SYS_INTEGRATION_DOWN, key)]
        rows = []
        for kind, scope, outage in self.paired_outages(days):  # type: ignore[attr-defined]
            if (kind, scope) in wanted:
                rows.append({
                    "went_down": outage["went_down"],
                    "what": outage["what"],
                    "duration": outage["duration"],
                    "devices": outage["devices"],
                    "open": outage["open"],
                    # A broker outage on Zigbee2MQTT's page is the
                    # broker's own: only the broker's expected times
                    # cover it (rule DASH-18).
                    **({"source": BROKER_SCOPE} if key == STACK_Z2M and scope == BROKER_SCOPE else {}),
                })
        return rows

    # -------------------------------------------------------------- tab

    def dashboard_networks(self) -> list[dict[str, Any]]:
        """One row per network the house has (rule DASH-17)."""
        members = self._network_members()
        problems = self._problem_groups_by_device()
        rows = []
        for key in self.network_keys(members):
            devices = members.get(key, [])
            with_problem, counts = self._count_groups(devices, problems)
            outages = [dict(o) for o in self.network_outages(key)]
            # An outage the person expects is listed, never counted
            # (rule DASH-18).
            for outage in outages:
                outage["expected"] = self.outage_is_expected(key, outage)  # type: ignore[attr-defined]
            counted = [o for o in outages if not o["expected"]]
            rows.append({
                "key": key,
                "name": self.network_name(key),
                "kind": "hub" if key.startswith(HUB_PREFIX) else key,
                "status": self.network_status(key),
                "watched": len(devices),
                "with_problem": with_problem,
                "counts": counts,
                # The newest outage the person does not expect, else the
                # newest expected one, marked so (rule DASH-18).
                "last_outage": counted[0] if counted else (outages[0] if outages else None),
                "outages": len(counted),
                "expected": len(outages) - len(counted),
                "window_days": self.network_window(key),
            })
        return rows

    # ------------------------------------------------------------- page

    def dashboard_network(self, key: str) -> dict[str, Any] | None:
        """One network's page, or None for a network the house lacks."""
        members_by = self._network_members()
        if key not in self.network_keys(members_by):
            return None
        members = members_by.get(key, [])
        problems = self._problem_groups_by_device()
        with_problem, counts = self._count_groups(members, problems)
        status = self.network_status(key)
        extras = self.network_extras(key, members, status)  # type: ignore[attr-defined]
        return {
            "key": key,
            "name": self.network_name(key),
            "kind": "hub" if key.startswith(HUB_PREFIX) else key,
            "status": status,
            "watched": len(members),
            "with_problem": with_problem,
            "counts": counts,
            "hardware": self._network_hardware(key),
            **extras,
            "notices": self._network_notices(key),
            "sensors": self._network_sensors(key, members),
            "signal": self._network_signal(key, members),
            "pairing": self._network_pairing(key, members),
            "wifi": self._network_wifi(members) if key == WIFI_KEY else None,
            "window_days": self.network_window(key),
        }

    # ---------------------------------------------------------- hardware

    def _device_at_host(self, host: str) -> str | None:
        """The registry device a coordinator's own integration shows at
        this address, if one does."""
        from .device_type import _host, _own_hosts

        if host in _own_hosts(self.hass):  # type: ignore[attr-defined]
            return None
        for device in self._registry_devices_of(None):
            if _host(device_field(device, "configuration_url")) == host:
                return str(device.id)
        return None

    def _registry_devices_of(self, domain: str | None) -> list[Any]:
        """The registry's devices, of one integration or of all, walked
        per config entry: reading the registry as a mapping is
        deprecated."""
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        seen: dict[str, Any] = {}
        entries = (
            self.hass.config_entries.async_entries(domain)  # type: ignore[attr-defined]
            if domain else self.hass.config_entries.async_entries()  # type: ignore[attr-defined]
        )
        for entry in entries:
            for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
                seen.setdefault(device.id, device)
        return list(seen.values())

    def _hardware_row(self, label: str, value: Any, device_id: str | None = None) -> dict[str, Any] | None:
        if value is None or value == "":
            return None
        return {"label": label, "value": str(value), "device_id": device_id}

    def _network_hardware(self, key: str) -> list[dict[str, Any]]:
        """The coordinator, controller or hub, as its integration reports
        it. Read only (rule STACK-13)."""
        from .device_type import _host, _zwave_node

        rows: list[dict[str, Any] | None] = []
        if key == STACK_Z2M:
            reader = self.bridge_reader(STACK_Z2M)  # type: ignore[attr-defined]
            info: dict[str, Any] = {}
            try:
                info = dict(getattr(reader, "hardware", None) or {})
            except Exception:  # noqa: BLE001 - a reader never breaks a page
                info = {}
            port = info.get("port")
            host = _host(port)
            device_id = self._device_at_host(host) if host else None
            if device_id is not None:
                rows.append(self._hardware_row("Device", self._device_name(device_id), device_id))  # type: ignore[attr-defined]
            rows.append(self._hardware_row("Type", info.get("type")))
            rows.append(self._hardware_row("Firmware", info.get("firmware")))
            rows.append(self._hardware_row("Zigbee channel", info.get("channel")))
            if isinstance(port, str) and port:
                rows.append(self._hardware_row("Connected by", "Network" if host else "USB or serial"))
            rows.append(self._hardware_row("Zigbee2MQTT", info.get("version")))
        elif key == STACK_ZHA:
            for entry in self.hass.config_entries.async_entries(STACK_ZHA):  # type: ignore[attr-defined]
                if entry.disabled_by is not None or entry.source == "ignore":
                    continue
                data = entry.data or {}
                device = data.get("device") if isinstance(data.get("device"), dict) else {}
                path = device.get("path") if isinstance(device, dict) else None
                host = _host(path)
                device_id = self._device_at_host(host) if host else None
                if device_id is not None:
                    rows.append(self._hardware_row("Device", self._device_name(device_id), device_id))  # type: ignore[attr-defined]
                radio = data.get("radio_type")
                if isinstance(radio, str):
                    rows.append(self._hardware_row("Radio type", ZHA_RADIO_NAMES.get(radio.lower(), radio)))
                if isinstance(path, str) and path:
                    rows.append(self._hardware_row("Connected by", "Network" if host else "USB or serial"))
                break
        elif key == STACK_ZWAVE:
            controllers = [
                device for device in self._registry_devices_of(STACK_ZWAVE)
                if _zwave_node(device) == "1"
            ]
            # A watched controller first; one Device Sentinel does not
            # watch is named without a link, since it has no page here.
            controllers.sort(key=lambda device: device.id not in self._watched)  # type: ignore[attr-defined]
            for device in controllers[:1]:
                watched = device.id in self._watched  # type: ignore[attr-defined]
                rows.append(self._hardware_row(
                    "Controller", device.name_by_user or device.name or device.id,
                    device.id if watched else None,
                ))
                rows.append(self._hardware_row("Model", device_field(device, "model")))
                rows.append(self._hardware_row("Firmware", device_field(device, "sw_version")))
            status = self._controller_status()
            if status is not None and self._entries_state(STACK_ZWAVE) == "loaded":
                rows.append(self._hardware_row("Controller status", status[0].strip().capitalize()))
        elif key.startswith(HUB_PREFIX):
            hub = key[len(HUB_PREFIX):]
            device = dr.async_get(self.hass).async_get(hub)  # type: ignore[attr-defined]
            rows.append(self._hardware_row("Hub", self._device_name(hub), hub))  # type: ignore[attr-defined]
            if device is not None:
                rows.append(self._hardware_row("Model", device_field(device, "model")))
                rows.append(self._hardware_row("Firmware", device_field(device, "sw_version")))
        return [row for row in rows if row is not None]

    # ---------------------------------------------------- status sensors

    def _network_notices(self, key: str) -> list[dict[str, Any]]:
        """A setting of the network's own that would help, with where to
        change it. Device Sentinel never changes it (rule STACK-13)."""
        notices: list[dict[str, Any]] = []
        if key == STACK_Z2M:
            reader = self.bridge_reader(STACK_Z2M)  # type: ignore[attr-defined]
            enabled = getattr(reader, "availability_enabled", None) if reader is not None else None
            if enabled is False:
                notices.append({
                    "title": "Zigbee2MQTT's Availability is off.",
                    "words": (
                        "With it on, Device Sentinel shows Zigbee2MQTT's own view beside "
                        "each freeze verdict. Turn it on in Zigbee2MQTT: Settings, "
                        "Availability, Enable availability, then Submit. Device Sentinel "
                        "never changes Zigbee2MQTT's settings."
                    ),
                    "open": "Zigbee2MQTT",
                })
            elif enabled is True:
                notices.append({"title": None, "words": "Zigbee2MQTT's Availability is on.", "open": None, "on": True})
        return notices

    def _network_sensors(self, key: str, members: list[str]) -> list[dict[str, Any]]:
        """For each sensor the network's devices are expected to have: how
        many devices have it, how many have it on, and the devices with it
        switched off, each to be turned on one at a time (rule REC-05)."""
        kinds = SENSOR_KINDS.get(key, ())
        rows = []
        for kind in kinds:
            have = 0
            off: list[dict[str, Any]] = []
            for device_id in members:
                own = self._own_entities_of(device_id, kind)  # type: ignore[attr-defined]
                if not own:
                    continue
                have += 1
                who = self.switched_off(device_id, kind)  # type: ignore[attr-defined]
                if who is not None:
                    off.append({
                        "device_id": device_id,
                        "name": self._device_name(device_id),  # type: ignore[attr-defined]
                        # Switched off by a person, or by Home Assistant
                        # or its integration.
                        "by": who,
                    })
            if not have:
                continue
            off.sort(key=lambda row: str(row["name"]).lower())
            label = Z2M_SIGNAL_LABEL if key == STACK_Z2M and kind == "signal" else SENSOR_LABELS[kind]
            rows.append({"kind": kind, "label": label, "have": have, "on": have - len(off), "off": off})
        return rows

    # ------------------------------------------------------------ signal

    def _network_signal(self, key: str, members: list[str]) -> dict[str, Any]:
        """Signal health over the last seven days: devices with a weak-link
        day, short drop-outs and on how many devices, and railed readings."""
        wanted = set(members)
        # Each device's own judged days, whatever its age: the Signal
        # Trends tab waits for 21 days, which a new device has not had.
        weak = 0
        records = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        today = dt_util.now().date()
        for device_id in members:
            record = records.get(device_id)
            if (
                not isinstance(record, dict)
                or device_id in self._muted_devices  # type: ignore[attr-defined]
                or self._signal_muted(device_id)  # type: ignore[attr-defined]
            ):
                continue
            try:
                held = len(record.get(DEV_SIGNAL_DAILY_P5) or [])
                dated = dates_for(record, FAMILY_SIGNAL, held, today - timedelta(days=1))
                for index in range(held):
                    if (today - dated[index]).days > NETWORK_WEEK_DAYS:
                        continue
                    day = self.signal_day_judgment(record, index)  # type: ignore[attr-defined]
                    if day and day["bad"]:
                        weak += 1
                        break
            except Exception as err:  # noqa: BLE001 - one record never breaks a page
                LOGGER.debug("Signal days for %s not read: %s", device_id, err)
        # Muted devices left out, as from the bad-signal days above; the
        # count is the one the page's repeat offenders list by device.
        wanted = {
            device_id for device_id in wanted
            if device_id not in self._muted_devices  # type: ignore[attr-defined]
            and not self._signal_muted(device_id)  # type: ignore[attr-defined]
        }
        counts = self.short_drops_by_device(sorted(wanted), NETWORK_WEEK_DAYS)  # type: ignore[attr-defined]
        drops = sum(counts.values())
        dropping = set(counts)
        problems = self._problem_groups_by_device()
        railed = sum(1 for device_id in members if "signal" in (problems.get(device_id) or {}).get("groups", []))
        return {"weak_week": weak, "drops": drops, "drop_devices": len(dropping), "railed": railed}

    # ----------------------------------------------------------- pairing

    def _network_pairing(self, key: str, members: list[str]) -> dict[str, Any] | None:
        """The last pairing window in the window, how many windows, and
        the network's devices added to Home Assistant in it. None for a
        network with no pairing of its own."""
        if key not in (STACK_Z2M, STACK_ZHA, STACK_ZWAVE, STACK_MATTER):
            return None
        # Only Zigbee2MQTT says when pairing opens and closes; the others
        # keep no window, so theirs give the devices added alone.
        windowed = key == STACK_Z2M
        now = dt_util.utcnow().timestamp()
        since = now - NETWORK_WINDOW_DAYS * 86400.0
        rows = sorted(
            (
                row for row in self.data.get(DATA_SYSTEM_EVENTS) or []  # type: ignore[attr-defined]
                if isinstance(row, dict) and row.get(SYS_SCOPE) == key
                and row.get(SYS_KIND) in (SYS_PAIRING_OPEN, SYS_PAIRING_CLOSED)
                and isinstance(row.get(SYS_WHEN), (int, float))
                and not isinstance(row.get(SYS_WHEN), bool)
            ),
            key=lambda row: row[SYS_WHEN],
        )
        windows: list[dict[str, Any]] = []
        opened: float | None = None
        for row in rows:
            if row[SYS_KIND] == SYS_PAIRING_OPEN:
                opened = float(row[SYS_WHEN])
                continue
            duration = row.get(SYS_DURATION)
            start = (
                opened if opened is not None
                else row[SYS_WHEN] - duration
                if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                else None
            )
            opened = None
            if start is not None and start >= since:
                windows.append({"opened": _iso(start), "duration": row[SYS_WHEN] - start, "open": False})
        if opened is not None and opened >= since:
            # Open only while Zigbee2MQTT says so: a close missed across a
            # restart leaves an opening with no end, whose length is not
            # known.
            still = self.bridge_state(key) == BRIDGE_BINDING  # type: ignore[attr-defined]
            windows.append({"opened": _iso(opened), "duration": None, "open": still})
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        new = 0
        for device_id in members:
            device = registry.async_get(device_id)
            created = device_field(device, "created_at") if device is not None else None
            moment = getattr(created, "timestamp", None)
            if callable(moment) and moment() >= since:
                new += 1
        if not windowed:
            return {"windows": None, "last": None, "new_devices": new}
        return {"windows": len(windows), "last": windows[-1] if windows else None, "new_devices": new}

    # ------------------------------------------------------------- Wi-Fi

    def _network_wifi(self, members: list[str]) -> dict[str, Any]:
        """The networks watched by name, the access points the devices are
        joined to, and addresses two devices hold at once (rule UP-19)."""
        points: dict[str, int] = {}
        index = self._address_index()  # type: ignore[attr-defined]
        names: dict[str, str | None] = {}
        for device_id in members:
            row = index.get(device_id) or {}
            point = row.get(ADDR_AP)
            if isinstance(point, str) and point:
                if point not in names:
                    names[point] = self.ap_name(point)  # type: ignore[attr-defined]
                shown = names[point] or point
                points[shown] = points.get(shown, 0) + 1
        shared = []
        for address, holders in sorted(self.shared_addresses().items()):  # type: ignore[attr-defined]
            shared.append({
                "address": address,
                "devices": [
                    {"device_id": device_id, "name": self._device_name(device_id)}  # type: ignore[attr-defined]
                    for device_id in holders
                ],
            })
        return {
            "watched_networks": list(self.wifi_networks),  # type: ignore[attr-defined]
            "scan": bool(self.wifi_scan_configured),  # type: ignore[attr-defined]
            "access_points": [
                {"name": point, "devices": count}
                for point, count in sorted(points.items(), key=lambda pair: (-pair[1], pair[0]))
            ],
            "shared": shared,
        }
