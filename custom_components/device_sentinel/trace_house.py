# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/trace_house.py, Version: 0.21.7 (2026-09-15)

"""Replay a recorded outage through the shipped coordinator.

Every constructed test in this suite lands its events in the same
millisecond. Four defects on 14 September lived in the gaps between
moments: the scan closed an outage twenty seconds before five devices
finished reconnecting, and no test could express twenty seconds.

A trace is a recording from the outage probe on a real house: every
tracker leaving and returning, every entity going unavailable and
recovering, each with its real offset from the start of the outage.
Replaying it gives the one thing a constructed house cannot, which is
real timing between two subsystems that move at different speeds.

The trace carries names and offsets, not hardware. The devices built
here are stand-ins with the recorded names, so what is under test is
the integration's behaviour against a real sequence rather than a
reproduction of anyone's fleet.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
)

from tests.helpers import setup_coordinator

TRACES = Path(__file__).parent / "traces"


def load_trace(name: str) -> dict[str, Any]:
    """Read a recorded outage."""
    return json.loads((TRACES / name).read_text())


class TraceHouse:
    """A house whose devices and trackers are named by a trace."""

    def __init__(self, hass, coord, devices, trackers, macs):
        self.hass = hass
        self.coord = coord
        self.devices = devices      # recorded name -> registry device
        self.trackers = trackers    # recorded entity_id -> our entity_id
        self.macs = macs
        self.unavailable: set[str] = set()

    def _tracker_state(self, entity_id: str, state: str) -> None:
        current = self.hass.states.get(entity_id)
        attrs = dict(current.attributes) if current else {}
        # A real router changes its counters on every poll, which is
        # what makes each reading a distinct state update.
        attrs["packets_sent"] = attrs.get("packets_sent", 0) + 1
        self.hass.states.async_set(entity_id, state, attrs)

    async def play(self, freezer, events, until: int | None = None):
        """Replay the trace, advancing the clock to each offset.

        Yields after every event so a test can assert mid-outage.
        """
        clock = 0
        for event in events:
            offset = event["offset"]
            if until is not None and offset > until:
                return
            if offset > clock:
                freezer.tick(timedelta(seconds=offset - clock))
                clock = offset
                self.coord._sample_wifi(_now())
            if event["kind"] == "tracker":
                tracker = self.trackers.get(event["entity"])
                if tracker:
                    self._tracker_state(
                        tracker, "home" if event["to"] == "home" else "not_home"
                    )
            else:
                device = self.devices.get(event["device"])
                if device is not None:
                    self._mark(device, event["to"])
            await self.hass.async_block_till_done()
            yield event, clock

    def _mark(self, device, what: str) -> None:
        """Land or clear a verdict, as the freeze detector would."""
        record = self.coord.data[DATA_DEVICES].setdefault(device.id, {})
        if what == "unavailable":
            record[DEV_FROZEN_CATEGORY] = "unavailable"
            record[DEV_FROZEN_SINCE] = _now()
            self.unavailable.add(device.id)
        else:
            record[DEV_FROZEN_CATEGORY] = None
            record[DEV_FROZEN_SINCE] = None
            self.unavailable.discard(device.id)

    def still_down(self) -> set[str]:
        return set(self.unavailable)

    def claimed(self) -> set[str]:
        return {
            device_id for device_id in self.unavailable
            if self.coord.upstream_down_since(device_id) is not None
        }

    def orphaned(self) -> set[str]:
        """Devices down and claimed by nothing: their own rows."""
        return self.still_down() - self.claimed()


def _now() -> float:
    from homeassistant.util import dt as dt_util

    return dt_util.utcnow().timestamp()


def load_ties() -> dict[str, str]:
    """The recorded device to tracker map.

    The probe names devices and trackers separately and never says
    which belongs to which, so a trace alone cannot be tied
    faithfully. Pairing them by sorted index looked harmless and was
    not: it tied devices to trackers at random, so devices recovered
    while unrelated trackers were still away and the replay reported
    orphans the real house never had. The map comes from a
    diagnostics capture of the same fleet.
    """
    return json.loads((TRACES / "reference_ties.json").read_text())


async def build(hass, trace: dict[str, Any], networks=("IKS_Rotarran-IoT",)):
    """Build a house carrying every name the trace mentions."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)

    names = sorted({
        event["device"] for event in trace["events"]
        if event["kind"] == "entity"
    })
    tracked = sorted({
        event["entity"] for event in trace["events"]
        if event["kind"] == "tracker"
    })

    ties = load_ties()
    devices: dict[str, Any] = {}
    trackers: dict[str, str] = {}
    macs: dict[str, str] = {}
    # tracker entity id, as recorded -> the device name it belongs to
    owner = {tracker: name for name, tracker in ties.items()}

    # Every recorded device, tied to a tracker where the trace has
    # one to spare, so the tie set is the size the recording implies.
    for index, name in enumerate(names):
        mac = f"aa:bb:cc:00:{index // 256:02x}:{index % 256:02x}"
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("wifi_hub", f"d{index}")},
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            name=name,
        )
        entities.async_get_or_create(
            "sensor", "wifi_hub", f"d{index}", device_id=device.id,
            config_entry=source,
        )
        devices[name] = device
        macs[name] = mac

    for index, recorded in enumerate(tracked):
        entry = entities.async_get_or_create(
            "device_tracker", "tplink_router", f"t{index}"
        )
        attrs = {"source_type": "router", "connection": "IoT", "band": "2G"}
        # Tied only where the recording says so. A tracker with no
        # device behind it is a guest phone, and the real house has
        # more of those than it has hardware.
        name = owner.get(recorded)
        if name in macs:
            attrs["mac"] = macs[name].upper().replace(":", "-")
        hass.states.async_set(entry.entity_id, "home", attrs)
        trackers[recorded] = entry.entity_id

    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    if networks:
        hass.config_entries.async_update_entry(
            coord.entry,
            options={**coord.entry.options, "wifi_networks": list(networks)},
        )
        await hass.async_block_till_done()
    coord._rebuild_registry_view()
    return TraceHouse(hass, coord, devices, trackers, macs)
