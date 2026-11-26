# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/study_matter.py, Version: 0.30.7 (2026-11-26)

"""What a Matter house shows beyond its entities, recorded for Extended
Diagnostics (rule STACK-19).

Home Assistant keeps no last-contact time for a Matter device, and a
sleepy Thread device's keep-alive never reaches it. Any value a device
sends does reach Home Assistant's Matter client, even one no entity
shows. While Matter is studied, Device Sentinel listens there and keeps
its own clock per device: when it was last heard, how often today, and
the longest silence. The download sets that clock beside the device's
last report through its entities, so a later release can learn whether
the clock sees a sleepy device the entities miss.

Also recorded, read from what the Matter server already holds:

- each device's check-in state (the server's schema 12 or later);
- each device's Power Source answer: wired or battery, and the battery
  it names and how many;
- the Thread map's routers and what each carries, from the map Device
  Sentinel already keeps (rule STACK-18), never refreshed.

Recorded only. Nothing here changes a verdict, and nothing is stored:
the clock starts again at each restart.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.core import callback

from .const import LOGGER
from .matter_mesh import matter_client

# What a device sends itself: a changed value, or an event such as a press.
CONTACT = frozenset({"attribute_updated", "node_event"})
# A whole-node update comes from the server, also when it marks a device
# unavailable, so it is counted apart and is never contact.
NODE_UPDATED = "node_updated"
# How long one check-in question may take, in seconds.
CHECK_IN_SECONDS = 5.0
CHECK_IN_SCHEMA = 12
# The Power Source cluster and the attributes read from it.
POWER_CLUSTER = 47
FEATURE_MAP = 65532
POWER_WIRED, POWER_BATTERY, POWER_RECHARGEABLE, POWER_REPLACEABLE = 1, 2, 4, 8
BATTERY_WORDS = {19: "replacement", 20: "ansi", 21: "iec", 31: "quantity"}


class MatterContactMixin:
    """The coordinator's contact clock for each Matter device."""

    def _contact_state(self) -> dict[str, Any]:
        if "_matter_contact" not in self.__dict__:
            self._matter_contact = {"client": None, "unsubs": {}, "nodes": {}}
        return self._matter_contact

    @callback
    def _matter_contact_tick(self, now: float) -> None:
        """Listen to each Matter device not yet listened to. Safe every minute."""
        state = self._contact_state()
        client = matter_client(self.hass)  # type: ignore[attr-defined]
        if client is None or not callable(getattr(client, "subscribe_events", None)):
            self._matter_contact_clear()
            return
        if client is not state["client"]:
            # A new client after a Matter reload: the old listeners died with the old one.
            self._matter_contact_clear()
            state["client"] = client
        try:
            nodes = list(client.get_nodes() or [])
        except Exception as err:  # noqa: BLE001 - another integration's client
            LOGGER.debug("device_sentinel: Matter nodes not read for the contact clock: %s", err)
            return
        for node in nodes:
            number = getattr(node, "node_id", None)
            if not isinstance(number, int) or number in state["unsubs"]:
                continue
            try:
                state["unsubs"][number] = client.subscribe_events(
                    self._contact_heard(number, now), node_filter=number
                )
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("device_sentinel: Matter node %s not listened to: %s", number, err)

    def _contact_heard(self, number: int, since: float):
        """The listener for one device: cheap, never raises."""
        nodes = self._contact_state()["nodes"]
        nodes.setdefault(number, {"since": since, "last": None, "count": 0, "longest": 0.0, "updates": 0})

        def heard(event: Any, _data: Any) -> None:
            try:
                what = str(getattr(event, "value", event))
                row = nodes.get(number)
                if row is None:
                    return
                if what == NODE_UPDATED:
                    row["updates"] += 1
                    return
                if what not in CONTACT:
                    return
                now = _wall()
                start = row["last"] if row["last"] is not None else row["since"]
                row["longest"] = max(row["longest"], now - start)
                row["last"] = now
                row["count"] += 1
            except Exception:  # noqa: BLE001 - a listener on another integration's client never raises
                return

        return heard

    @callback
    def _matter_contact_clear(self) -> None:
        """Stop listening and forget the clock."""
        state = self._contact_state()
        for unsub in list(state["unsubs"].values()):
            try:
                unsub()
            except Exception as err:  # noqa: BLE001 - the client may already be gone
                LOGGER.debug("device_sentinel: a Matter listener was already gone: %s", err)
        state["unsubs"].clear()
        state["nodes"].clear()
        state["client"] = None

    def matter_contact_view(self) -> dict[int, dict[str, Any]]:
        """Each listened-to device's clock, for the download."""
        now = _wall()
        out: dict[int, dict[str, Any]] = {}
        for number, row in self._contact_state()["nodes"].items():
            start = row["last"] if row["last"] is not None else row["since"]
            out[number] = {
                "heard": row["count"],
                # Whole-node updates from the server, not the device.
                "server_updates": row.get("updates", 0),
                "last_seconds_ago": round(now - row["last"]) if row["last"] is not None else None,
                "listening_seconds": round(now - row["since"]),
                # The silence still running counts once it is the longest.
                "longest_silence_seconds": round(max(row["longest"], now - start)),
            }
        return out


def _wall() -> float:
    return time.time()


def power_source(node: Any) -> dict[str, Any] | None:
    """What the device's Power Source cluster says, or None when it has none."""
    attributes = getattr(getattr(node, "node_data", None), "attributes", None)
    if not isinstance(attributes, dict):
        return None
    sources: list[dict[str, Any]] = []
    for path, value in attributes.items():
        parts = str(path).split("/")
        if len(parts) != 3 or parts[1] != str(POWER_CLUSTER) or parts[2] != str(FEATURE_MAP):
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        row: dict[str, Any] = {
            "endpoint": parts[0],
            "wired": bool(value & POWER_WIRED),
            "battery": bool(value & POWER_BATTERY),
            "rechargeable": bool(value & POWER_RECHARGEABLE),
            "replaceable": bool(value & POWER_REPLACEABLE),
        }
        for attribute, name in BATTERY_WORDS.items():
            found = attributes.get(f"{parts[0]}/{POWER_CLUSTER}/{attribute}")
            if isinstance(found, (str, int)) and not isinstance(found, bool) and found != "":
                row[name] = found if isinstance(found, int) else found[:60]
        sources.append(row)
    return {"sources": sources[:4]} if sources else None


async def check_in(client: Any, number: int, budget: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The server's check-in state for one device, or None where it has none.

    With a budget shared across one download, a server that has once kept
    Device Sentinel waiting is not asked again, so a stuck server costs the
    download five seconds, not five for each device."""
    info = getattr(client, "server_info", None)
    schema = getattr(info, "schema_version", None)
    getter = getattr(client, "get_icd_state", None)
    if not isinstance(schema, int) or schema < CHECK_IN_SCHEMA or not callable(getter):
        return None
    if budget is not None and budget.get("slow"):
        return {"error": "skipped"}
    try:
        state = await asyncio.wait_for(getter(number), CHECK_IN_SECONDS)
    except Exception as err:  # noqa: BLE001 - another integration's server
        if budget is not None and isinstance(err, TimeoutError):
            budget["slow"] = True
        return {"error": type(err).__name__}
    keep = ("supported", "lit_supported", "registered", "operating_mode", "awake", "available", "next_expected_checkin")
    return {key: getattr(state, key, None) for key in keep}
