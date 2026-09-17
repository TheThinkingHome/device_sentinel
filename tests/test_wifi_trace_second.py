# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_trace_second.py, Version: 0.21.12 (2026-09-17)

"""The second fleet's staged outage, replayed through the whole tick.

Recorded by the outage probe on 16 September with 0.21.10 running:
the SSIDs paused at 16:40, the devices' own integrations noticed
within the first minute, the router marked its first client away four
and a half minutes in and a second wave five minutes after that, and
the network came back at 16:50. 0.21.10 listed 53 devices beside the
outage row (rulings #440 and #446 answer it).

Unlike the reference traces, which land verdicts by hand, this one
drives each device's entity to unavailable at its recorded moment and
runs the coordinator's own minute tick, so the detector judges, the
outage is declared and backdated, and the problem list is written by
the shipped code. Names in the trace are replaced; its timings and
its ties are the house's own.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DATA_TODO_ITEMS
from tests.helpers import setup_coordinator

TRACES = Path(__file__).parent / "traces"
TRACE = "second_2026_09_16_1640.json"
TIES = "second_ties.json"


async def _house(hass):
    trace = json.loads((TRACES / TRACE).read_text())
    ties = json.loads((TRACES / TIES).read_text())
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    names = sorted({
        event["device"] for event in trace["events"]
        if event["kind"] == "entity"
    })
    owners = defaultdict(list)
    for name, tracker in ties.items():
        owners[tracker].append(name)

    device_ids: dict[str, str] = {}
    stand_in: dict[str, str] = {}
    macs: dict[str, str] = {}
    for index, name in enumerate(names):
        mac = f"aa:bb:cc:00:{index // 256:02x}:{index % 256:02x}"
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("wifi_hub", f"d{index}")},
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            name=name,
        )
        entity = entities.async_get_or_create(
            "sensor", "wifi_hub", f"d{index}",
            device_id=device.id, config_entry=source,
        )
        hass.states.async_set(entity.entity_id, "21.5")
        device_ids[name] = device.id
        stand_in[name] = entity.entity_id
        macs[name] = mac

    trackers: dict[str, list[str]] = defaultdict(list)
    for index, recorded in enumerate(sorted(owners)):
        for slot, name in enumerate(owners[recorded]):
            entity = entities.async_get_or_create(
                "device_tracker", "tplink_router", f"t{index}_{slot}"
            )
            hass.states.async_set(entity.entity_id, "home", {
                "source_type": "router", "connection": "IoT", "band": "2G",
                "mac": macs[name].upper().replace(":", "-"),
            })
            trackers[recorded].append(entity.entity_id)
    await hass.async_block_till_done()

    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    return trace, coord, device_ids, stand_in, trackers


async def _settle(hass, coord, stand_in, freezer, minutes):
    """Run the house quietly past its startup grace."""
    for _ in range(minutes):
        freezer.tick(timedelta(seconds=60))
        for entity in stand_in.values():
            hass.states.async_set(entity, "21.5", force_update=True)
        await hass.async_block_till_done()
        await coord._on_render_tick(None)


async def _replay(hass, freezer):
    trace, coord, device_ids, stand_in, trackers = await _house(hass)
    await _settle(hass, coord, stand_in, freezer, 8)
    assert not coord._in_startup_grace()
    assert len(coord._wifi_ties) == 51

    start = dt_util.utcnow().timestamp()
    ours = set(device_ids.values())
    down: dict[str, set[str]] = defaultdict(set)
    events = trace["events"]
    position = 0
    clock = 0
    minutes: list[dict] = []
    for moment in range(0, 1500, 15):
        while position < len(events) and events[position]["offset"] <= moment:
            event = events[position]
            position += 1
            if event["offset"] > clock:
                freezer.tick(timedelta(seconds=event["offset"] - clock))
                clock = event["offset"]
            if event["kind"] == "tracker":
                state = "home" if event["to"] == "home" else "not_home"
                for entity in trackers.get(event["entity"], []):
                    attrs = dict(hass.states.get(entity).attributes)
                    hass.states.async_set(entity, state, attrs)
            else:
                name = event["device"]
                if event["to"] == "unavailable":
                    down[name].add(event["entity"])
                else:
                    down[name].discard(event["entity"])
                hass.states.async_set(
                    stand_in[name], "unavailable" if down[name] else "21.5"
                )
            await hass.async_block_till_done()
        if moment > clock:
            freezer.tick(timedelta(seconds=moment - clock))
            clock = moment
        coord._sample_wifi(dt_util.utcnow().timestamp())
        if moment % 60 == 0:
            await coord._on_render_tick(None)
            items = coord.data[DATA_TODO_ITEMS]
            minutes.append({
                "at": moment,
                "device_rows": sum(
                    1 for item in items if item.get("device_id") in ours
                ),
                "outage_from": (
                    None if coord.wifi_down_at is None
                    else coord.wifi_down_at - start
                ),
                "wifi": [
                    item["summary"] for item in items
                    if "WiFi" in (item.get("summary") or "")
                ],
            })
    return minutes


async def test_no_device_is_listed_on_its_own(hass: HomeAssistant, freezer):
    minutes = await _replay(hass, freezer)
    assert [m["device_rows"] for m in minutes] == [0] * len(minutes)


async def test_the_outage_is_dated_from_the_first_device(
    hass: HomeAssistant, freezer
):
    minutes = await _replay(hass, freezer)
    dated = [m["outage_from"] for m in minutes if m["outage_from"] is not None]
    # The first entity went unavailable 38 seconds in; the first tracker
    # left at 275.
    assert dated and min(dated) == 38.0
    assert all(value < 275.0 for value in dated)


async def test_the_row_follows_the_outage_to_its_end(
    hass: HomeAssistant, freezer
):
    minutes = await _replay(hass, freezer)
    rows = [row for m in minutes for row in m["wifi"]]
    assert any(" total devices down" in row for row in rows)
    assert any(row.startswith("WiFi network is back: waiting for") for row in rows)
    assert minutes[-1]["wifi"] == []
