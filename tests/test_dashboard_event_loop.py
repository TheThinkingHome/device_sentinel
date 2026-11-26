# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_event_loop.py, Version: 0.30.0 (2026-11-21)

"""The dashboard never touches a file on the event loop (rule CODE-06).

Every page of the dashboard is answered on Home Assistant's event loop,
the one thread everything else waits on, so a page is built from what
is in memory and anything it needs from a file is read at setup on a
worker thread. The Brief tab once read the settings labels from
strings.json there, and Home Assistant logged a blocking call after
each restart.

Each command that only reads is asked, every day of the brief, each
integration's and each network's page, and a device page, on the
second test house where it is present, and on a small built house
otherwise. Any file opened, listed or looked up from Device Sentinel's
code on the event loop's thread fails the test.
"""

from __future__ import annotations

import builtins
import itertools
import os
import threading
import sys
from datetime import date, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DATA_DEVICES, SYS_OPTIONS_CHANGED

from tests.conftest import fleet_data, fleet_path
from tests.helpers import devices_of_entry, register_device, setup_coordinator

SECOND = fleet_path("second", "device_sentinel_storage.json")
OURS = os.sep + os.path.join("custom_components", "device_sentinel") + os.sep

_ids = itertools.count(1)


def _watch_the_loop(monkeypatch) -> list[str]:
    """Record each file touched from Device Sentinel's code on this thread."""
    loop_thread = threading.get_ident()
    seen: list[str] = []

    def ours() -> bool:
        # The call is Device Sentinel's own: made from its code, not from
        # Python finding a source line for a log message on the way.
        return OURS in sys._getframe(2).f_code.co_filename

    def watched(real, name):
        def spy(*args, **kwargs):
            if threading.get_ident() == loop_thread and ours():
                seen.append(f"{name} {args[0] if args else ''}")
            return real(*args, **kwargs)
        return spy

    monkeypatch.setattr(builtins, "open", watched(builtins.open, "open"))
    for name in ("listdir", "scandir", "stat"):
        monkeypatch.setattr(os, name, watched(getattr(os, name), name))
    for name in ("exists", "isfile", "getsize"):
        monkeypatch.setattr(os.path, name, watched(getattr(os.path, name), name))
    return seen


async def _ask(client, **msg):
    await client.send_json({"id": next(_ids), **msg})
    return await client.receive_json()


async def _ask_every_page(hass: HomeAssistant, client, coord) -> int:
    """Ask each read-only command; return how many answered."""
    # A changed setting, which the brief names by its screen label:
    # the row that once read strings.json on the loop.
    coord._record_system_event(SYS_OPTIONS_CHANGED, detail="low_threshold")
    answered = 0
    for kind in ("status", "devices", "classification", "problem_list", "recommendations",
                 "integrations", "networks", "battery_trends", "signal_trends", "device_choices"):
        reply = await _ask(client, type=f"device_sentinel/{kind}")
        assert reply["success"], (kind, reply)
        answered += 1
        if kind == "integrations":
            for row in (reply["result"].get("rows") or reply["result"].get("integrations") or [])[:20]:
                domain = row.get("domain") if isinstance(row, dict) else None
                if domain:
                    await _ask(client, type="device_sentinel/integration", domain=domain)
                    answered += 1
        if kind == "networks":
            for row in (reply["result"].get("rows") or reply["result"].get("networks") or []):
                key = row.get("key") if isinstance(row, dict) else None
                if key:
                    await _ask(client, type="device_sentinel/network", key=key)
                    answered += 1
    today = date.today()
    for back in range(15):
        await _ask(client, type="device_sentinel/brief", day=(today - timedelta(days=back)).isoformat())
        answered += 1
    for device_id in list(coord.data[DATA_DEVICES])[:12]:
        reply = await _ask(client, type="device_sentinel/device", device_id=device_id)
        assert reply["success"], reply
        answered += 1
    await hass.async_block_till_done()
    return answered


async def _seat_second_house(hass: HomeAssistant):
    """The second house's records onto devices planted under its ids."""
    data = fleet_data(SECOND)
    records = data.get("devices") or {}
    source = MockConfigEntry(domain="test", title="")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    for device_id in records:
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id, identifiers={("test", device_id)}, name=f"Device {device_id[:6]}")
        entities.async_get_or_create("sensor", "test", device_id, device_id=device.id, config_entry=source)
    coord = await setup_coordinator(hass)
    live_for = {ident: device.id for device in devices_of_entry(hass, source.entry_id)
                for domain, ident in device.identifiers if domain == "test"}
    for device_id, record in records.items():
        if device_id in live_for and isinstance(record, dict):
            coord.data[DATA_DEVICES][live_for[device_id]] = dict(record)
    for key in ("system_events", "incidents", "storm_days", "silence_episodes", "short_drops",
                "short_drop_days", "address_changes", "signal_stress"):
        coord.data[key] = data.get(key) or []
    coord._rebuild_registry_view()
    return coord


@pytest.mark.skipif(not SECOND.exists(), reason="the second test house is not present")
async def test_no_page_of_a_real_house_touches_a_file_on_the_loop(hass: HomeAssistant, hass_ws_client, monkeypatch):
    coord = await _seat_second_house(hass)
    client = await hass_ws_client(hass)
    seen = _watch_the_loop(monkeypatch)
    answered = await _ask_every_page(hass, client, coord)
    assert answered > 30, answered
    assert seen == [], seen[:5]


async def test_no_page_of_a_small_house_touches_a_file_on_the_loop(hass: HomeAssistant, hass_ws_client, monkeypatch):
    for n in range(4):
        register_device(hass, f"loop{n}", f"Loop Device {n}")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    client = await hass_ws_client(hass)
    seen = _watch_the_loop(monkeypatch)
    await _ask_every_page(hass, client, coord)
    assert seen == [], seen[:5]


async def test_the_labels_are_read_while_starting(hass: HomeAssistant):
    """The settings labels the brief names a changed setting by are read
    on a worker thread while Device Sentinel starts, not when a page is
    asked for (rule CODE-06)."""
    coord = await setup_coordinator(hass)
    labels = getattr(coord, "_option_label_cache", None)
    assert labels, "the setting labels are read during setup"
    assert labels.get("low_threshold_alkaline") == "Alkaline Batteries"
    assert "Alkaline Batteries" in coord._changed_labels("low_threshold_alkaline")
