# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stack_probes_hubs.py, Version: 0.23.9 (2026-09-26)

"""Hue, SmartThings, Tuya and Lutron in Extended Diagnostics (0.23.9).

Recording only, into the one stack_probe.md. The fakes follow the
shapes read on 26 September 2026 in Home Assistant 2026.9.2 and the
libraries it pins: aiohue 4.9.0, pysmartthings 4.0.1,
tuya-device-sharing-sdk 0.2.15, and the Lutron probe's reading of
pylutron-caseta. Also the Connects line: how each device reaches Home
Assistant, from its integration's own declaration.
"""

from __future__ import annotations

import enum
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    CONNECTS_WORDS,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NOW,
    PROBE_SENTINEL,
    STUDIABLE,
)
from custom_components.device_sentinel.study_stacks import (
    HUE_DOMAIN,
    LUTRON_DOMAIN,
    SMARTTHINGS_DOMAIN,
    TUYA_DOMAIN,
    coordinator_rows,
    probe_rows,
)

from .helpers import probe_lines, setup_coordinator


class _Connectivity(enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTIVITY_ISSUE = "connectivity_issue"
    UNIDIRECTIONAL_INCOMING = "unidirectional_incoming"


class _Stream(enum.Enum):
    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2


class _Type(enum.StrEnum):
    ZIGBEE = "ZIGBEE"
    VIPER = "VIPER"


def _entry(hass, domain, runtime, **kwargs):
    entry = MockConfigEntry(domain=domain, title=domain, **kwargs)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = runtime
    return entry


def _device(hass, entry, domain, ident, name):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, ident)}, name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{ident}-reading", device_id=device.id, config_entry=entry,
    )
    return device


class _HueDevices:
    def __init__(self, statuses):
        self._statuses = statuses

    def __iter__(self):
        return iter(SimpleNamespace(id=node) for node in self._statuses)

    def get_zigbee_connectivity(self, node):
        return SimpleNamespace(status=self._statuses[node])


def _hue(hass, statuses, stream=_Stream.CONNECTED, version=2, ignored=()):
    api = SimpleNamespace(devices=_HueDevices(statuses), events=SimpleNamespace(status=stream))
    return _entry(hass, HUE_DOMAIN, SimpleNamespace(api_version=version, api=api),
                  options={"ignore_availability": list(ignored)})


async def _studied(hass, *labels):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: list(labels)})


def test_the_four_stacks_are_offered():
    for domain, label in (
        (HUE_DOMAIN, "Philips Hue"), (SMARTTHINGS_DOMAIN, "SmartThings"),
        (TUYA_DOMAIN, "Tuya"), (LUTRON_DOMAIN, "Lutron Caséta"),
    ):
        assert STUDIABLE[domain] == label


async def test_hue_gives_the_bridges_own_judgment(hass: HomeAssistant):
    """A light on Hue's ignore list stays available while disconnected;
    the line says so, and the bridge's judgment sits beside Device
    Sentinel's."""
    lamp_id, strip_id = "3a1b2c3d-0000-4000-8000-000000000001", "3a1b2c3d-0000-4000-8000-000000000002"
    entry = _hue(hass, {lamp_id: _Connectivity.CONNECTIVITY_ISSUE, strip_id: _Connectivity.CONNECTED},
                 ignored=[lamp_id])
    lamp = _device(hass, entry, HUE_DOMAIN, lamp_id, "Hall lamp")
    coord = await _studied(hass, "Philips Hue")
    record = coord.data[DATA_DEVICES][lamp.id]
    record[DEV_LAST_ACTIVITY] = 1.0
    record[DEV_FROZEN_CATEGORY] = "frozen"
    coord.probe_tick(1000.0)
    line = next(row for row in probe_lines(coord) if row[PROBE_DEVICE_ID] == "Hall lamp")
    assert line[PROBE_NOW] == "connectivity_issue"
    assert line[PROBE_SENTINEL] == "frozen" and line[PROBE_AGREES] == "yes"
    assert line[PROBE_DETAIL] == "availability ignored in Hue's options"
    bridge = next(row for row in probe_lines(coord, "bridge"))
    assert bridge[PROBE_NOW] == "connected"


async def test_a_v1_hue_bridge_is_named_and_not_read(hass: HomeAssistant):
    _hue(hass, {"x": _Connectivity.CONNECTED}, version=1)
    assert probe_rows(hass, {HUE_DOMAIN}) == []
    assert [row["now"] for row in coordinator_rows(hass, {HUE_DOMAIN})] == ["v1 bridge, not read"]


async def test_smartthings_records_its_cloud_subscription(hass: HomeAssistant):
    """The cloud-outage question: a lost subscription is a line."""
    runtime = SimpleNamespace(devices={
        "b7e1": SimpleNamespace(device=SimpleNamespace(device_id="b7e1", type=_Type.ZIGBEE, hub=SimpleNamespace(), parent_device_id=None)),
        "c9f2": SimpleNamespace(device=SimpleNamespace(device_id="c9f2", type=_Type.VIPER, hub=None, parent_device_id=None)),
    })
    entry = _entry(hass, SMARTTHINGS_DOMAIN, runtime, data={"subscription_id": "abc"})
    _device(hass, entry, SMARTTHINGS_DOMAIN, "b7e1", "Garage contact")
    coord = await _studied(hass, "SmartThings")
    coord.probe_tick(1000.0)
    contact = next(row for row in probe_lines(coord) if row[PROBE_DEVICE_ID] == "Garage contact")
    assert contact[PROBE_NOW] == "zigbee" and contact[PROBE_DETAIL] == "behind a SmartThings hub"
    hass.config_entries.async_update_entry(entry, data={"subscription_id": None})
    coord.probe_tick(1060.0)
    assert [row[PROBE_NOW] for row in probe_lines(coord, "cloud")] == ["subscribed", "not subscribed"]


async def test_tuya_records_its_cloud_link_and_each_device(hass: HomeAssistant):
    link = {"up": True}
    manager = SimpleNamespace(
        device_map={"eb01": SimpleNamespace(id="eb01", online=False, sub=True, category="wsdcg")},
        mq=SimpleNamespace(client=SimpleNamespace(is_connected=lambda: link["up"])),
    )
    entry = _entry(hass, TUYA_DOMAIN, SimpleNamespace(manager=manager))
    _device(hass, entry, TUYA_DOMAIN, "eb01", "Patio sensor")
    coord = await _studied(hass, "Tuya")
    coord.probe_tick(1000.0)
    sensor = next(row for row in probe_lines(coord) if row[PROBE_DEVICE_ID] == "Patio sensor")
    assert sensor[PROBE_NOW] == "offline"
    assert sensor[PROBE_DETAIL] == "behind a Tuya gateway, category wsdcg"
    link["up"] = False
    coord.probe_tick(1060.0)
    assert [row[PROBE_NOW] for row in probe_lines(coord, "cloud")] == ["connected", "disconnected"]


async def test_lutron_records_whether_the_library_holds_its_session(hass: HomeAssistant):
    """The Lutron hub's outage leaves every light showing its last
    state; the library's session is the honest signal, and its own
    is_connected() stays true through it."""
    bridge = SimpleNamespace(_leap=object(), is_connected=lambda: True)
    _entry(hass, LUTRON_DOMAIN, SimpleNamespace(bridge=bridge))
    coord = await _studied(hass, "Lutron Caséta")
    coord.probe_tick(1000.0)
    bridge._leap = None
    coord.probe_tick(1060.0)
    lines = probe_lines(coord, "hub")
    assert [row[PROBE_NOW] for row in lines] == ["session held", "no session"]
    assert lines[-1][PROBE_DETAIL] == "library says connected, entry loaded"


async def test_each_device_says_how_it_connects(hass: HomeAssistant):
    """From each integration's own declaration, through the public
    loader: cloud push for Tuya, local polling for ZHA."""
    for domain in ("tuya", "zha", "mqtt"):
        await async_get_integration(hass, domain)
    coord = await setup_coordinator(hass)
    assert coord.iot_class_of("tuya") == "cloud_push"
    assert coord.iot_class_of("zha") == "local_polling"
    assert coord.iot_class_of("mqtt") == "local_push"
    assert coord.iot_class_of("not_an_integration") is None
    assert CONNECTS_WORDS["cloud_push"].startswith("Through the maker's cloud.")
    entry = MockConfigEntry(domain="tuya", title="Tuya")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    device = _device(hass, entry, "tuya", "eb02", "Hall plug")
    await hass.config_entries.async_reload(coord.entry.entry_id)
    await hass.async_block_till_done()
    page = coord.entry.runtime_data.dashboard_device(device.id)
    assert page["identity"]["connects"] == CONNECTS_WORDS["cloud_push"]
