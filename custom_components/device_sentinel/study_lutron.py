# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: study_lutron.py, Version: 0.22.26 (2026-09-23)

"""What a Lutron house can tell us, for a detector we cannot yet build.

The fourth fleet ran a probe on two Caseta hubs for two days, and it
settled the shape of a Lutron outage. A hub's session drops while
`is_connected()` stays True throughout. No entity moves: the lights
hold their last state and refuse commands, and nothing reads
unavailable. A Lutron light reports only when a person uses it, so its
silence says nothing; a device's health is its hub's health. A restart
during an outage is the one case the entities notice, and the hub's
config entry then sits in setup_retry. Every Pico button entity is
disabled, so a Pico has no entity at all and its presses arrive only as
a bus event.

What the probe could not settle is whether any of that is visible from
a surface an integration may use. It added a TCP check against the
hub's port 8081 to answer that, and the campaign to prove it was never
run. So this gathers the evidence instead, from any Lutron house that
turns Extended Diagnostics on (0.22.26):

- each hub's config entry, its state, host and port, and how many
  devices sit behind it;
- what the library exposes in that house's version: whether a bridge
  object is reachable at all, what `is_connected()` says, and whether
  a session handle exists and is truthy, each read defensively and
  never assumed present;
- one TCP connect to the hub, with how long it took or the error it
  gave, which is what the probe's 1.1 would have measured;
- the entity picture per hub: how many entities are enabled, how many
  disabled, and which devices have none, the Pico case behind issue
  #14.

It detects nothing and changes no verdict. Lutron support is scheduled
after the deprecation, and this is the evidence it will be built on.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import LOGGER

LUTRON_DOMAIN = "lutron_caseta"
# The Caseta LEAP port, which is what the hub answers on.
LUTRON_PORT = 8081
# A hub on the same network answers in milliseconds. This is a
# diagnostic, taken once per download, so it waits briefly and moves on.
CONNECT_TIMEOUT = 2.0
# The names a bridge object has carried. Read by trying each, so a
# library that renames one is recorded as absent rather than crashing.
SESSION_NAMES = ("_leap", "leap", "_session", "session")
BRIDGE_NAMES = ("bridge", "smartbridge", "_smartbridge")


def _look(holder: Any, names: tuple[str, ...]) -> tuple[str | None, Any]:
    """Return the first of these attributes that exists, and its value."""
    for name in names:
        try:
            value = getattr(holder, name)
        except Exception as err:  # noqa: BLE001 - a property may raise
            LOGGER.debug(
                "device_sentinel: Lutron attribute %s could not be read "
                "(%s), so it is recorded as absent",
                name,
                err,
            )
            value = None
        if value is not None:
            return name, value
    return None, None


def _bridge_of(entry_data: Any) -> tuple[str | None, Any]:
    """Return the library's bridge object for an entry, if it is there."""
    if entry_data is None:
        return None, None
    if isinstance(entry_data, dict):
        for name in BRIDGE_NAMES:
            if entry_data.get(name) is not None:
                return name, entry_data[name]
        return None, None
    return _look(entry_data, BRIDGE_NAMES)


async def _tcp_check(host: str | None, port: int) -> dict[str, Any]:
    """One connection to the hub: how long, or what went wrong."""
    if not host:
        return {"tried": False}
    started = time.monotonic()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except TimeoutError:
        return {"tried": True, "answered": False, "error": "timed out"}
    except OSError as err:
        return {"tried": True, "answered": False, "error": str(err)[:120]}
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return {
        "tried": True,
        "answered": True,
        "milliseconds": round((time.monotonic() - started) * 1000, 1),
    }


async def lutron_study(hass: HomeAssistant) -> dict[str, Any]:
    """The Lutron evidence, or an empty dict where there is no Lutron."""
    entries = hass.config_entries.async_entries(LUTRON_DOMAIN)
    if not entries:
        return {}
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    hubs: list[dict[str, Any]] = []
    for entry in entries:
        host = entry.data.get("host") or entry.data.get(
            "CONF_HOST", entry.data.get("ip_address")
        )
        behind = dr.async_entries_for_config_entry(devices, entry.entry_id)
        enabled = disabled = 0
        without = 0
        for device in behind:
            rows = er.async_entries_for_device(
                entities, device.id, include_disabled_entities=True
            )
            if not rows:
                without += 1
            for row in rows:
                if row.disabled_by is None:
                    enabled += 1
                else:
                    disabled += 1
        name, bridge = _bridge_of(
            (hass.data.get(LUTRON_DOMAIN) or {}).get(entry.entry_id)
        )
        connected: Any = None
        if bridge is not None:
            call = getattr(bridge, "is_connected", None)
            if callable(call):
                try:
                    connected = bool(call())
                except Exception as err:  # noqa: BLE001 - a library call
                    connected = f"raised {type(err).__name__}"
        session_name, session = (
            _look(bridge, SESSION_NAMES) if bridge is not None else (None, None)
        )
        hubs.append({
            "entry_id": entry.entry_id,
            "title": entry.title,
            "state": str(entry.state),
            "host_known": bool(host),
            "port": LUTRON_PORT,
            "devices": len(behind),
            "entities_enabled": enabled,
            "entities_disabled": disabled,
            "devices_with_no_entities": without,
            # What the library gives this house, by name, so a version
            # that renames or removes one is visible rather than
            # guessed at.
            "bridge_attribute": name,
            "is_connected": connected,
            "session_attribute": session_name,
            "session_present": session is not None,
            "session_truthy": bool(session) if session is not None else None,
            "tcp": await _tcp_check(host, LUTRON_PORT),
        })
    return {"hubs": hubs}
