# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/hue_smartthings_fakes.py, Version: 0.26.4 (2026-10-15)

"""A Hue bridge and a SmartThings location built from the real libraries.

The Hue side is aiohue's own HueBridgeV2, filled through its own
full-state path from the resource list a bridge returns, so every
controller, model and event stream is the library's (aiohue 4.9.0 on
Home Assistant 2026.10, 4.8.1 on 2026.5). Nothing reaches a network:
the one request is answered here, and the event stream's tasks are
never started. The SmartThings side is pysmartthings' own client and
Device models, held in Home Assistant's own SmartThingsData and
FullDevice (pysmartthings 4.0.3 on 2026.10, 3.7.3 on 2026.5).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from aiohue.v2 import HueBridgeV2
from aiohue.v2.controllers.events import EventStreamStatus, EventType
from pysmartthings import Device, SmartThings

BRIDGE_DEVICE = "b0000000-0000-4000-8000-000000000000"
BRIDGE_RESOURCE = "b0000000-0000-4000-8000-0000000000b1"


def _ref(rid: str, rtype: str) -> dict[str, str]:
    return {"rid": rid, "rtype": rtype}


def _device(device_id: str, name: str, services: list[dict[str, str]], certified: bool = True) -> dict[str, Any]:
    return {
        "id": device_id,
        "type": "device",
        "services": services,
        "product_data": {
            "model_id": "LCT015",
            "manufacturer_name": "Signify Netherlands B.V.",
            "product_name": "Hue color lamp",
            "product_archetype": "sultan_bulb",
            "certified": certified,
            "software_version": "1.122.2",
        },
        "metadata": {"archetype": "sultan_bulb", "name": name},
    }


def hue_lamp(device_id: str, name: str, status: str = "connected", on: bool = True,
             certified: bool = True) -> list[dict[str, Any]]:
    """A lamp: a device, its light and its Zigbee link."""
    light, link = f"{device_id[:-2]}l1", f"{device_id[:-2]}z1"
    owner = _ref(device_id, "device")
    return [
        _device(device_id, name, [_ref(light, "light"), _ref(link, "zigbee_connectivity")], certified),
        {"id": light, "type": "light", "owner": owner, "on": {"on": on}, "mode": "normal"},
        {"id": link, "type": "zigbee_connectivity", "owner": owner, "status": status,
         "mac_address": "00:17:88:01:02:03:04:05"},
    ]


def hue_sensor(device_id: str, name: str, status: str = "connected", level: int = 80,
               battery: str = "normal") -> list[dict[str, Any]]:
    """A battery sensor: a device, its power and its Zigbee link."""
    power, link = f"{device_id[:-2]}p1", f"{device_id[:-2]}z1"
    owner = _ref(device_id, "device")
    return [
        _device(device_id, name, [_ref(power, "device_power"), _ref(link, "zigbee_connectivity")]),
        {"id": power, "type": "device_power", "owner": owner,
         "power_state": {"battery_level": level, "battery_state": battery}},
        {"id": link, "type": "zigbee_connectivity", "owner": owner, "status": status,
         "mac_address": "00:17:88:01:02:03:04:06"},
    ]


def hue_green_power(device_id: str, name: str) -> list[dict[str, Any]]:
    """A Hue Tap: Green Power, no Zigbee link of its own."""
    link = f"{device_id[:-2]}g1"
    return [
        _device(device_id, name, [_ref(link, "zgp_connectivity")]),
        {"id": link, "type": "zgp_connectivity", "owner": _ref(device_id, "device"),
         "status": "connected", "source_id": "0x0001"},
    ]


def hue_bridge_resources(update: str = "no_update") -> list[dict[str, Any]]:
    """The bridge's own device, bridge resource and update state."""
    owner = _ref(BRIDGE_DEVICE, "device")
    swu = "b0000000-0000-4000-8000-0000000000c1"
    device = _device(BRIDGE_DEVICE, "Hue Bridge", [_ref(BRIDGE_RESOURCE, "bridge"),
                                                   _ref(swu, "device_software_update")])
    device["product_data"].update(model_id="BSB002", product_archetype="bridge_v2",
                                  software_version="1.70.1970019010")
    return [
        device,
        {"id": BRIDGE_RESOURCE, "type": "bridge", "owner": owner,
         "bridge_id": "001788fffe123456", "time_zone": {"time_zone": "America/Guayaquil"}},
        {"id": swu, "type": "device_software_update", "owner": owner, "state": update, "problems": []},
    ]


async def hue_api(resources: list[dict[str, Any]], stream: EventStreamStatus = EventStreamStatus.CONNECTED) -> HueBridgeV2:
    """aiohue's bridge, filled from these resources, its stream at stream."""
    api = HueBridgeV2("192.0.2.10", "test-key")

    async def answer(_method: str, _path: str, **_kwargs: Any) -> list[dict[str, Any]]:
        return resources

    api.request = answer  # type: ignore[method-assign]
    await api.fetch_full_state()
    set_stream(api, stream)
    return api


def set_stream(api: HueBridgeV2, stream: EventStreamStatus) -> None:
    """Set the event stream's status where the library keeps it."""
    api.events._status = stream  # noqa: SLF001 - the library's own field


async def hue_update(api: HueBridgeV2, resource: dict[str, Any],
                     creationtime: str = "2026-10-15T13:01:02Z") -> None:
    """An update arriving on the event stream, through the library.

    The library hands each update to its controllers as a task, so
    the loop is given a turn for them to run.
    """
    api.events._event_history.append(  # noqa: SLF001
        {"creationtime": creationtime, "type": "update", "data": [resource]}
    )
    api.events.emit(EventType.RESOURCE_UPDATED, resource)
    for _ in range(3):
        await asyncio.sleep(0)


def hue_runtime(api: Any, version: int = 2) -> SimpleNamespace:
    """What Home Assistant's Hue entry holds: the api and its version."""
    return SimpleNamespace(api_version=version, api=api)


def st_device(device_id: str, label: str, kind: str, parent: str | None = None,
              firmware: str | None = None) -> Device:
    """pysmartthings' Device, from the cloud's own JSON shape."""
    data: dict[str, Any] = {
        "deviceId": device_id,
        "name": label,
        "label": label,
        "locationId": "loc-0001",
        "type": kind,
        "components": [{
            "id": "main", "label": "main", "capabilities": [{"id": "switch", "version": 1}],
            "categories": [{"name": "Switch", "categoryType": "manufacturer"}],
        }],
        "restrictionTier": 0,
        "allowed": [],
        "executionContext": "CLOUD",
    }
    if parent:
        data["parentDeviceId"] = parent
    if firmware:
        data["hub"] = {"firmwareVersion": firmware, "hubData": {"hardwareType": "V3_HUB"}}
    return Device.from_dict(data)


def st_client() -> SmartThings:
    """pysmartthings' client, never connected."""
    return SmartThings(session=None)


def set_retries(client: SmartThings, count: int) -> None:
    """Set the client's retry count where the library keeps it."""
    client._SmartThings__retry_count = count  # noqa: SLF001 - the library's own field
