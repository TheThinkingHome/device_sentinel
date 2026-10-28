# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_hue_smartthings_probe.py, Version: 0.27.10 (2026-10-27)

"""Hue and SmartThings in Extended Diagnostics, read more fully
(rules STACK-11, STACK-13).

Sampling only: once a minute, from memory, nothing sent to a bridge or
a cloud and no callback added to either library. The bridge and the
location are the real libraries (tests/hue_smartthings_fakes.py), so a
renamed field or a changed enum fails here rather than in a house. The
last tests hand the readers libraries that are broken in every way
found, and the minute check must carry on.
"""

from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest
from aiohue.v2.controllers.events import EventStreamStatus
from homeassistant.components.smartthings import FullDevice, SmartThingsData
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    DATA_DEVICES,
    DEV_LAST_ACTIVITY,
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NOW,
    PROBE_WAS,
)
from custom_components.device_sentinel.study_stacks import (
    HUE_DOMAIN,
    SMARTTHINGS_DOMAIN,
    coordinator_rows,
    entry_nodes,
    probe_rows,
    smartthings_network,
)

from .helpers import probe_lines, setup_coordinator, setup_entry
from .hue_smartthings_fakes import (
    BRIDGE_DEVICE,
    hue_api,
    hue_bridge_resources,
    hue_green_power,
    hue_lamp,
    hue_runtime,
    hue_sensor,
    hue_update,
    set_retries,
    set_stream,
    st_client,
    st_device,
)

LAMP = "d1000000-0000-4000-8000-000000000001"
MOTION = "d2000000-0000-4000-8000-000000000001"
TAP = "d3000000-0000-4000-8000-000000000001"
HUB = "aaaa1111-0000-4000-8000-000000000001"
CONTACT = "bbbb2222-0000-4000-8000-000000000001"
SPEAKER = "cccc3333-0000-4000-8000-000000000001"


def _entry(hass, domain, runtime, title=None, **kwargs):
    entry = MockConfigEntry(domain=domain, title=title or domain, **kwargs)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = runtime
    return entry


def _device(hass, entry, domain, ident, name):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, ident)}, name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{ident}-reading", device_id=device.id, config_entry=entry,
    )
    hass.states.async_set(entity.entity_id, "21")
    return device, entity.entity_id


def _line(coord, name):
    return [row for row in probe_lines(coord) if row[PROBE_DEVICE_ID] == name][-1]


async def _house(hass, stream=EventStreamStatus.CONNECTED, ignored=(), lamp_status="connected",
                 certified=True, update="no_update"):
    api = await hue_api(
        hue_bridge_resources(update)
        + hue_lamp(LAMP, "Hall lamp", lamp_status, certified=certified)
        + hue_sensor(MOTION, "Stair motion", level=12, battery="low")
        + hue_green_power(TAP, "Hue Tap"),
        stream,
    )
    entry = _entry(hass, HUE_DOMAIN, hue_runtime(api), options={"ignore_availability": list(ignored)})
    entry.devices = {
        ident: _device(hass, entry, HUE_DOMAIN, ident, name)[0]
        for ident, name in ((LAMP, "Hall lamp"), (MOTION, "Stair motion"), (TAP, "Hue Tap"),
                            (BRIDGE_DEVICE, "Hue Bridge"))
    }
    return api, entry


async def _studied(hass, *labels):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: list(labels)})


# ------------------------------------------------------------------ Hue


async def test_hue_reads_the_bridge_and_each_device(hass: HomeAssistant):
    """The real aiohue bridge: the lamp's link, the sensor's battery,
    the Tap named rather than skipped, the bridge's firmware, and no
    row for the bridge's own device."""
    api, _entry_ = await _house(hass, update="ready_to_install")
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    lamp = _line(coord, "Hall lamp")
    assert lamp[PROBE_NOW] == "connected" and lamp[PROBE_DETAIL] == ""
    assert _line(coord, "Stair motion")[PROBE_DETAIL] == "battery 12%, low"
    assert _line(coord, "Hue Tap")[PROBE_NOW] == "no link reported (Green Power)"
    assert _line(coord, "Hue Tap")[PROBE_AGREES] == ""
    assert not [row for row in probe_lines(coord) if row[PROBE_DEVICE_ID] == "Hue Bridge"]
    (bridge,) = probe_lines(coord, "bridge")
    assert bridge[PROBE_NOW] == "connected"
    assert bridge[PROBE_DETAIL].startswith("firmware 1.70.1970019010, ")
    if hasattr(api.devices, "get_software_update"):  # the newer aiohue, on Home Assistant 2026.10
        assert "update ready to install" in bridge[PROBE_DETAIL]
    else:  # the older aiohue, on 2026.5, has no update state and says nothing
        assert "update" not in bridge[PROBE_DETAIL]
    assert "entry loaded" in bridge[PROBE_DETAIL]
    assert "Device Sentinel" in bridge[PROBE_DETAIL]


async def test_a_stream_outage_reads_down_and_its_devices_stale(hass: HomeAssistant):
    """aiohue holds CONNECTING through every wait to reconnect, so an outage
    reads down, not "connecting". The entities keep their last state, so
    the bridge's word on each device is stale and gives no opinion."""
    api, _entry_ = await _house(hass)
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    await hue_update(api, {"id": f"{MOTION[:-2]}p1", "type": "device_power",
                           "power_state": {"battery_level": 11, "battery_state": "low"}})
    api._disconnect_timestamp = 1030.0
    set_stream(api, EventStreamStatus.CONNECTING)
    coord.probe_tick(1060.0)
    bridge = probe_lines(coord, "bridge")[-1]
    assert bridge[PROBE_WAS] == "connected" and bridge[PROBE_NOW] == "down, retrying"
    assert "1 change in the last hour" in bridge[PROBE_DETAIL]
    assert "stream last dropped or failed to reconnect" in bridge[PROBE_DETAIL]
    assert "newest event 2026-10-15T13:01:02Z on the bridge's clock" in bridge[PROBE_DETAIL]
    lamp = _line(coord, "Hall lamp")
    assert lamp[PROBE_NOW] == "connected (stale while the bridge stream is down)"
    assert lamp[PROBE_AGREES] == ""
    set_stream(api, EventStreamStatus.DISCONNECTED)
    coord.probe_tick(1120.0)
    assert probe_lines(coord, "bridge")[-1][PROBE_NOW] == "down, stopped"
    set_stream(api, EventStreamStatus.CONNECTED)
    coord.probe_tick(1180.0)
    assert "3 changes in the last hour" in probe_lines(coord, "bridge")[-1][PROBE_DETAIL]
    assert _line(coord, "Hall lamp")[PROBE_NOW] == "connected"


async def test_a_light_switched_while_not_connected_is_a_line(hass: HomeAssistant):
    """Home Assistant's Hue integration warns once when a light that
    is not Hue certified changes while the bridge says it is not
    connected; the probe writes it each time."""
    api, _entry_ = await _house(hass, lamp_status="connectivity_issue", certified=False)
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    first = _line(coord, "Hall lamp")
    assert first[PROBE_NOW] == "connectivity_issue" and first[PROBE_DETAIL] == "not Hue certified"
    coord.probe_tick(1060.0)
    count = len(probe_lines(coord))
    await hue_update(api, {"id": f"{LAMP[:-2]}l1", "type": "light", "on": {"on": False}})
    coord.probe_tick(1120.0)
    assert len(probe_lines(coord)) == count + 1
    assert _line(coord, "Hall lamp")[PROBE_DETAIL] == "light switched while not connected, not Hue certified"
    coord.probe_tick(1180.0)
    assert len(probe_lines(coord)) == count + 1


async def test_a_light_switched_while_the_stream_is_down_is_not_flagged(hass: HomeAssistant):
    """While the stream is down the bridge's word is stale, so a light
    changing then says nothing about the bridge's judgment."""
    api, _entry_ = await _house(hass, lamp_status="disconnected")
    coord = await _studied(hass, "Philips Hue")
    set_stream(api, EventStreamStatus.CONNECTING)
    coord.probe_tick(1000.0)
    await hue_update(api, {"id": f"{LAMP[:-2]}l1", "type": "light", "on": {"on": False}})
    coord.probe_tick(1060.0)
    assert not [row for row in probe_lines(coord) if "switched" in row[PROBE_DETAIL]]


async def test_the_ignore_list_is_described_as_hue_applies_it(hass: HomeAssistant):
    """Hue's ignore list keeps a light available and does nothing for
    a device without one: Home Assistant's Hue entity applies it only
    where the resource has an on feature."""
    await _house(hass, ignored=[LAMP, MOTION])
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    assert _line(coord, "Hall lamp")[PROBE_DETAIL] == "on Hue's ignore list, its light stays available"
    assert _line(coord, "Stair motion")[PROBE_DETAIL] == (
        "on Hue's ignore list, which does nothing without a light, battery 12%, low"
    )


async def test_two_bridges_have_a_line_each(hass: HomeAssistant):
    """Two bridges share the node name "bridge", so the probe must not read
    them as one flipping between their two states."""
    upstairs = await hue_api(hue_bridge_resources() + hue_lamp(LAMP, "Hall lamp"))
    downstairs = await hue_api(hue_bridge_resources() + hue_lamp(MOTION, "Den lamp"))
    up = _entry(hass, HUE_DOMAIN, hue_runtime(upstairs), title="Hue Bridge 001788fffe6a1b2c")
    down = _entry(hass, HUE_DOMAIN, hue_runtime(downstairs), title="Hue Bridge 001788fffe0a0b0c")
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    set_stream(downstairs, EventStreamStatus.CONNECTING)
    coord.probe_tick(1060.0)
    coord.probe_tick(1120.0)
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"bridge {up.entry_id[-8:]}")] == ["connected"]
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"bridge {down.entry_id[-8:]}")] == [
        "connected", "down, retrying",
    ]
    assert not [line for line in coord._probe_recent if "001788fffe" in line]


def test_entries_are_named_by_id_never_by_title():
    """Hue titles an entry with its bridge's address and Tuya with the
    account's email or phone number."""
    one = SimpleNamespace(title="Hue Bridge 001788fffe6a1b2c", entry_id="01JABCDEFGH")
    two = SimpleNamespace(title="someone@example.com", entry_id="01JXYZ12345")
    assert [name for _e, name in entry_nodes([one], "bridge")] == ["bridge"]
    assert [name for _e, name in entry_nodes([one, two], "cloud")] == [
        "cloud ABCDEFGH", "cloud XYZ12345",
    ]


async def test_a_v1_bridge_reads_its_poll(hass: HomeAssistant):
    poll = SimpleNamespace(last_update_success=True)
    runtime = SimpleNamespace(api_version=1, sensor_manager=SimpleNamespace(coordinator=poll))
    _entry(hass, HUE_DOMAIN, runtime)
    assert probe_rows(hass, {HUE_DOMAIN}) == []
    assert [row["now"] for row in coordinator_rows(hass, {HUE_DOMAIN})] == ["v1 bridge, polling"]
    poll.last_update_success = False
    assert [row["now"] for row in coordinator_rows(hass, {HUE_DOMAIN})] == ["v1 bridge, polling failing"]


async def test_the_bridge_line_says_when_device_sentinel_last_heard_its_devices(hass: HomeAssistant):
    _api, entry = await _house(hass)
    coord = await _studied(hass, "Philips Hue")
    lamp = entry.devices[LAMP]
    coord.data[DATA_DEVICES][lamp.id][DEV_LAST_ACTIVITY] = 990.0
    for record in coord.data[DATA_DEVICES].values():
        if record is not coord.data[DATA_DEVICES][lamp.id]:
            record[DEV_LAST_ACTIVITY] = 10.0
    coord.probe_tick(1000.0)
    detail = probe_lines(coord, "bridge")[-1][PROBE_DETAIL]
    assert f"Device Sentinel last heard one of its devices {coord._episode_stamp(990.0)}" in detail


# ----------------------------------------------------------- SmartThings


def _location(hass, devices, subscription="9f8e7d6c-5b4a-3210-fedc-ba9876543210", client=None):
    client = client or st_client()
    runtime = SmartThingsData(
        devices={device.device_id: FullDevice(device=device, status={}, online=True) for device in devices},
        scenes={}, rooms={}, client=client,
    )
    return _entry(hass, SMARTTHINGS_DOMAIN, runtime, title="Home",
                  data={"subscription_id": subscription}), client


async def _socket(hass, entry):
    """Home Assistant's own background task, under the name its
    SmartThings integration gives the stream."""
    gate = asyncio.Event()
    entry.async_create_background_task(hass, gate.wait(), "smartthings_socket")
    await asyncio.sleep(0)
    return gate


def test_smartthings_types_say_how_a_device_reaches_the_cloud():
    """A hub, which carries hub data, is not read as a device behind a hub."""
    assert smartthings_network("HUB") == "a SmartThings hub"
    for kind in ("ZIGBEE", "ZWAVE", "MATTER", "LAN", "EDGE_CHILD"):
        assert smartthings_network(kind) == "behind a SmartThings hub"
    for kind in ("VIPER", "OCF", "MOBILE", "ENDPOINT_APP", "BLE_D2D"):
        assert smartthings_network(kind) == "on its own to the cloud"
    assert smartthings_network("SOMETHING_NEW") == "reach not known"


async def test_smartthings_reads_each_device_as_home_assistant_shows_it(hass: HomeAssistant):
    """pysmartthings' own Device models in Home Assistant's own
    SmartThingsData: the stack's word is the entities, which follow the
    cloud's online and offline live."""
    entry, _client = _location(hass, [
        st_device(HUB, "Hub", "HUB", firmware="000.055.00009"),
        st_device(CONTACT, "Garage contact", "ZIGBEE", parent=HUB),
        st_device(SPEAKER, "Kitchen speaker", "VIPER"),
    ])
    _device(hass, entry, SMARTTHINGS_DOMAIN, HUB, "Hub")
    _contact, contact_entity = _device(hass, entry, SMARTTHINGS_DOMAIN, CONTACT, "Garage contact")
    _speaker, speaker_entity = _device(hass, entry, SMARTTHINGS_DOMAIN, SPEAKER, "Kitchen speaker")
    hass.states.async_set(speaker_entity, "unavailable")
    await _socket(hass, entry)
    coord = await _studied(hass, "SmartThings")
    coord.probe_tick(1000.0)
    hub = _line(coord, "Hub")
    assert hub[PROBE_NOW] == "available"
    assert hub[PROBE_DETAIL] == "a SmartThings hub, type hub, firmware 000.055.00009"
    contact = _line(coord, "Garage contact")
    assert contact[PROBE_DETAIL] == "behind a SmartThings hub, type zigbee, parent aaaa1111"
    assert _line(coord, "Kitchen speaker")[PROBE_NOW] == "unavailable"
    assert _line(coord, "Kitchen speaker")[PROBE_DETAIL] == "on its own to the cloud, type viper"
    hass.states.async_set(contact_entity, "unavailable")
    coord.probe_tick(1060.0)
    contact = _line(coord, "Garage contact")
    assert contact[PROBE_WAS] == "available" and contact[PROBE_NOW] == "unavailable"


async def test_smartthings_reads_its_stream(hass: HomeAssistant):
    """The stream task, its retries and the subscription, each a line
    when it changes."""
    entry, client = _location(hass, [st_device(SPEAKER, "Kitchen speaker", "VIPER")])
    _device(hass, entry, SMARTTHINGS_DOMAIN, SPEAKER, "Kitchen speaker")
    gate = await _socket(hass, entry)
    coord = await _studied(hass, "SmartThings")
    coord.probe_tick(1000.0)
    first = probe_lines(coord, "cloud")[-1]
    assert first[PROBE_NOW] == "stream running"
    assert first[PROBE_DETAIL].startswith("subscription 9f8e7d6c, entry loaded, ")
    set_retries(client, 3)
    coord.probe_tick(1060.0)
    line = probe_lines(coord, "cloud")[-1]
    assert line[PROBE_NOW] == "stream retrying"
    assert line[PROBE_DETAIL].startswith("subscription 9f8e7d6c, retry 3, wait 8 s, entry loaded")
    set_retries(client, 0)
    hass.config_entries.async_update_entry(entry, data={"subscription_id": "11112222-aaaa"})
    coord.probe_tick(1120.0)
    line = probe_lines(coord, "cloud")[-1]
    assert line[PROBE_NOW] == "stream running" and line[PROBE_DETAIL].startswith("subscription 11112222,")
    gate.set()
    await hass.async_block_till_done()
    coord.probe_tick(1180.0)
    assert probe_lines(coord, "cloud")[-1][PROBE_NOW] == "stream stopped"


async def test_smartthings_retry_wait_is_named_without_computing_it(hass: HomeAssistant):
    """The library's wait has no ceiling; a count in the thousands is
    named, never raised to a power."""
    entry, client = _location(hass, [])
    await _socket(hass, entry)
    set_retries(client, 5000)
    (row,) = coordinator_rows(hass, {SMARTTHINGS_DOMAIN})
    assert "retry 5000, wait over 18 hours" in row["detail"]
    set_retries(client, True)
    (row,) = coordinator_rows(hass, {SMARTTHINGS_DOMAIN})
    assert row["now"] == "stream running"


async def test_smartthings_not_loaded_and_signing_in_again(hass: HomeAssistant):
    entry, _client = _location(hass, [])
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY, "Could not delete old subscription")
    (row,) = coordinator_rows(hass, {SMARTTHINGS_DOMAIN})
    assert row["now"] == "not loaded"
    assert row["detail"] == (
        "subscription 9f8e7d6c, reason Could not delete old subscription, entry setup_retry"
    )
    entry.async_get_active_flows = lambda _hass, sources: iter([{"source": "reauth"}])
    (row,) = coordinator_rows(hass, {SMARTTHINGS_DOMAIN})
    assert row["now"] == "needs signing in again"


async def test_two_locations_have_a_line_each(hass: HomeAssistant):
    first, _ = _location(hass, [])
    second, _ = _location(hass, [], subscription=None)
    nodes = sorted(row["node"] for row in coordinator_rows(hass, {SMARTTHINGS_DOMAIN}))
    assert nodes == sorted([f"cloud {first.entry_id[-8:]}", f"cloud {second.entry_id[-8:]}"])


async def test_another_integrations_entity_is_not_the_device(hass: HomeAssistant):
    """A Battery Notes entity on an offline SmartThings device stays
    available; the row reads the device's own entities only
    (rule WATCH-02)."""
    entry, _client = _location(hass, [st_device(CONTACT, "Garage contact", "ZIGBEE", parent=HUB)])
    contact, contact_entity = _device(hass, entry, SMARTTHINGS_DOMAIN, CONTACT, "Garage contact")
    notes = er.async_get(hass).async_get_or_create(
        "sensor", "battery_notes", f"{CONTACT}-battery-type", device_id=contact.id,
    )
    hass.states.async_set(notes.entity_id, "CR2032")
    hass.states.async_set(contact_entity, "unavailable")
    await _socket(hass, entry)
    (row,) = probe_rows(hass, {SMARTTHINGS_DOMAIN})
    assert row["now"] == "unavailable" and row["quiet"] is True


async def test_smartthings_devices_are_stale_while_the_stream_is_down(hass: HomeAssistant):
    """Home Assistant moves a SmartThings entity's availability only on
    health events that come over the stream, so with it down every
    device keeps its last word; the rows give no opinion, as Hue's do."""
    entry, client = _location(hass, [st_device(SPEAKER, "Kitchen speaker", "VIPER")])
    _device(hass, entry, SMARTTHINGS_DOMAIN, SPEAKER, "Kitchen speaker")
    gate = await _socket(hass, entry)
    coord = await _studied(hass, "SmartThings")
    coord.probe_tick(1000.0)
    assert _line(coord, "Kitchen speaker")[PROBE_NOW] == "available"
    set_retries(client, 2)
    coord.probe_tick(1060.0)
    speaker = _line(coord, "Kitchen speaker")
    assert speaker[PROBE_NOW] == "available (stale while the cloud stream is down)"
    assert speaker[PROBE_AGREES] == ""
    set_retries(client, 0)
    coord.probe_tick(1120.0)
    assert _line(coord, "Kitchen speaker")[PROBE_NOW] == "available"
    gate.set()
    await hass.async_block_till_done()
    coord.probe_tick(1180.0)
    assert _line(coord, "Kitchen speaker")[PROBE_NOW] == "available (stale while the cloud stream is down)"


async def test_an_ignored_or_disabled_entry_is_not_a_bridge(hass: HomeAssistant):
    """A dismissed discovery is an ignored entry of the same domain; it
    is not a second bridge, and the real one keeps its plain name."""
    api = await hue_api(hue_bridge_resources() + hue_lamp(LAMP, "Hall lamp"))
    _entry(hass, HUE_DOMAIN, hue_runtime(api))
    MockConfigEntry(domain=HUE_DOMAIN, source="ignore", unique_id="001788fffe0a0b0c").add_to_hass(hass)
    MockConfigEntry(domain=HUE_DOMAIN, disabled_by=ConfigEntryDisabler.USER, unique_id="001788fffe0d0e0f").add_to_hass(hass)
    MockConfigEntry(domain=SMARTTHINGS_DOMAIN, source="ignore", unique_id="loc-2").add_to_hass(hass)
    assert [row["node"] for row in coordinator_rows(hass, {HUE_DOMAIN, SMARTTHINGS_DOMAIN})] == ["bridge"]


async def test_a_reload_keeps_what_was_known(hass: HomeAssistant):
    """While a Hue entry reloads it gives no rows; when it is back, a
    device's "since" is when it was first seen, not the reload."""
    api, entry = await _house(hass)
    coord = await _studied(hass, "Philips Hue")
    coord.probe_tick(1000.0)
    runtime = entry.runtime_data
    entry.runtime_data = None
    coord.probe_tick(1060.0)
    entry.runtime_data = runtime
    coord.probe_tick(1120.0)
    assert coord._probe_since[(HUE_DOMAIN, LAMP[:8])] == ("connected", 1000.0)


# ----------------------------------------------------------- downloads


async def test_the_download_carries_hue_and_smartthings(hass: HomeAssistant):
    await _house(hass)
    entry, _client = _location(hass, [st_device(SPEAKER, "Kitchen speaker", "VIPER")])
    _device(hass, entry, SMARTTHINGS_DOMAIN, SPEAKER, "Kitchen speaker")
    own = await setup_entry(hass, {CONF_STUDY_HARDWARE: ["Philips Hue", "SmartThings"]})
    own.runtime_data.probe_tick(1000.0)
    report = await diagnostics.async_get_config_entry_diagnostics(hass, own)
    hue = report["classification"]["hue"]
    assert [item["now"] for item in hue["entries"]] == ["connected"]
    assert hue["entries"][0]["devices"] == 4
    lamp = next(item for item in hue["devices"] if item["node"] == LAMP[:8])
    assert lamp["now"] == "connected" and lamp["light_on"] is True and lamp["since"]
    things = report["classification"]["smartthings"]
    assert things["entries"][0]["now"] == "stream stopped"
    assert things["devices"][0]["detail"] == "on its own to the cloud, type viper"
    assert "unreadable" not in hue and "unreadable" not in things


async def test_the_download_is_empty_where_the_stack_is_not_ticked(hass: HomeAssistant):
    await _house(hass)
    own = await setup_entry(hass, {CONF_STUDY_HARDWARE: ["SmartThings"]})
    report = await diagnostics.async_get_config_entry_diagnostics(hass, own)
    found = report["classification"]
    assert found["hue"] == {} and found["smartthings"] == {"entries": [], "devices": []}


# ---------------------------------------------------------------- safety


async def test_nothing_is_sent_to_a_bridge_or_a_cloud(hass: HomeAssistant):
    """The minute check reads memory only: a request to the bridge, or
    any call on the SmartThings client, fails this test."""
    api, _entry_ = await _house(hass)
    calls: list[str] = []

    async def refuse(*args, **kwargs):
        calls.append("hue request")
        raise AssertionError("the bridge was contacted")

    api.request = refuse
    client = st_client()
    for name in ("get_devices", "get_device_status", "get_device_health", "create_subscription",
                 "delete_subscription", "subscribe", "get_locations"):
        setattr(client, name, lambda *a, _n=name, **k: calls.append(_n))
    _location(hass, [st_device(SPEAKER, "Kitchen speaker", "VIPER")], client=client)
    coord = await _studied(hass, "Philips Hue", "SmartThings")
    for minute in range(5):
        coord.probe_tick(1000.0 + 60 * minute)
    await hass.async_block_till_done()
    assert calls == []


class _Raises:
    """Every attribute, call, iteration, index and truth test raises."""

    def __getattr__(self, name):
        raise RuntimeError(f"broken {name}")

    def __call__(self, *args, **kwargs):
        raise RuntimeError("broken call")

    def __iter__(self):
        raise RuntimeError("broken iteration")

    def __getitem__(self, key):
        raise RuntimeError("broken index")

    def __bool__(self):
        raise RuntimeError("broken truth")

    def __len__(self):
        raise RuntimeError("broken length")


class _BadStatus:
    @property
    def name(self):
        raise RuntimeError("broken name")


_HUE_HOSTILE = [
    _Raises(),
    SimpleNamespace(api_version=2, api=_Raises()),
    SimpleNamespace(api_version=2, api=SimpleNamespace(
        devices=SimpleNamespace(get_zigbee_connectivity=_Raises(), __iter__=None),
        events=_Raises(), config=_Raises(), lights=_Raises(), sensors=_Raises(),
        _disconnect_timestamp="yesterday",
    )),
    SimpleNamespace(api_version=2, api=SimpleNamespace(
        devices=[SimpleNamespace(id=7), SimpleNamespace(id=None), SimpleNamespace(id="x", services="lights")],
        events=SimpleNamespace(status=_BadStatus(), last_events=_Raises()),
        config=SimpleNamespace(software_version=12, bridge_device=SimpleNamespace(id=[1])),
        _disconnect_timestamp=float("nan"),
    )),
    SimpleNamespace(api_version=2, api=SimpleNamespace(
        devices=SimpleNamespace(
            get_zigbee_connectivity=lambda node: SimpleNamespace(status=SimpleNamespace(value=None)),
            __iter__=lambda: iter([SimpleNamespace(
                id="e1", services=[SimpleNamespace(rtype=_Raises(), rid="r"),
                                   SimpleNamespace(rtype="light", rid=_Raises()),
                                   SimpleNamespace(rtype="light", rid="r2"),
                                   SimpleNamespace(rtype="device_power", rid="r3")],
                product_data=_Raises(),
            )]),
        ),
        events=SimpleNamespace(status=EventStreamStatus.CONNECTED, last_events=deque([None, 5, "x"])),
        lights=SimpleNamespace(get=lambda rid: SimpleNamespace(on=_Raises())),
        sensors=SimpleNamespace(device_power=SimpleNamespace(get=lambda rid: SimpleNamespace(
            power_state=SimpleNamespace(battery_level=True, battery_state=_Raises())
        ))),
        config=SimpleNamespace(software_version=_Raises()),
        _disconnect_timestamp=True,
    )),
]


class _IterDevices:
    """aiohue's controller iterates; SimpleNamespace cannot."""

    def __init__(self, items, lookup):
        self._items = items
        self.get_zigbee_connectivity = lookup

    def __iter__(self):
        return iter(self._items)


def _hostile_hue(hass, runtime, options):
    api = getattr(runtime, "__dict__", {}).get("api")
    devices = getattr(api, "__dict__", {}).get("devices") if api is not None else None
    if isinstance(devices, SimpleNamespace) and callable(devices.__dict__.get("__iter__")):
        api.devices = _IterDevices(list(devices.__iter__()), devices.get_zigbee_connectivity)
    return _entry(hass, HUE_DOMAIN, runtime, options=options)


_ST_HOSTILE = [
    _Raises(),
    SimpleNamespace(devices=_Raises(), client=_Raises()),
    SimpleNamespace(devices={"a": SimpleNamespace(device=_Raises())}, client=SimpleNamespace()),
    SimpleNamespace(devices={"a": SimpleNamespace(device=SimpleNamespace(
        device_id=12, type=None, parent_device_id=5, hub=_Raises()))}, client=None),
    SimpleNamespace(devices={"a": SimpleNamespace(device=SimpleNamespace(
        device_id="a1", type=_Raises(), parent_device_id="", hub=SimpleNamespace(firmware_version=3)))},
        client=SimpleNamespace(_SmartThings__retry_count=-4)),
    SimpleNamespace(devices=[1, 2, None], client=SimpleNamespace(_SmartThings__retry_count="3")),
]


@pytest.mark.parametrize("index", range(len(_HUE_HOSTILE)))
@pytest.mark.parametrize("options", [{"ignore_availability": _Raises()}, {"ignore_availability": "abc"}, {}])
async def test_a_broken_hue_library_never_breaks_the_minute(hass: HomeAssistant, index, options, caplog):
    """A library renamed, removed, raising or returning the wrong type
    costs its readings and nothing else: no warning, no failure noted,
    and Device Sentinel's own minute goes on."""
    _hostile_hue(hass, _HUE_HOSTILE[index], options)
    coord = await _studied(hass, "Philips Hue")
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    assert coord._probe_failed == set()
    assert "Extended Diagnostics could not read" not in caplog.text
    probe_rows(hass, {HUE_DOMAIN})
    coordinator_rows(hass, {HUE_DOMAIN})
    assert isinstance(coord.stack_diagnostics(HUE_DOMAIN), dict)


@pytest.mark.parametrize("index", range(len(_ST_HOSTILE)))
async def test_a_broken_smartthings_library_never_breaks_the_minute(hass: HomeAssistant, index, caplog):
    entry = _entry(hass, SMARTTHINGS_DOMAIN, _ST_HOSTILE[index], data={"subscription_id": 42})
    entry._background_tasks = _Raises() if index % 2 else {_Raises()}
    entry.async_get_active_flows = _Raises()
    coord = await _studied(hass, "SmartThings")
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    assert coord._probe_failed == set()
    assert "Extended Diagnostics could not read" not in caplog.text
    assert isinstance(coord.stack_diagnostics(SMARTTHINGS_DOMAIN), dict)


async def test_an_entry_without_options_or_data_is_read(hass: HomeAssistant):
    """MockConfigEntry always has both; a real entry mid-migration
    might hold the wrong type."""
    hue = _entry(hass, HUE_DOMAIN, SimpleNamespace(api_version=2, api=None))
    things = _entry(hass, SMARTTHINGS_DOMAIN, None)
    object.__setattr__(hue, "options", None)
    object.__setattr__(things, "data", ["not", "a", "mapping"])
    coord = await _studied(hass, "Philips Hue", "SmartThings")
    coord.probe_tick(1000.0)
    assert coord._probe_failed == set()
    assert [row[PROBE_NOW] for row in probe_lines(coord, "bridge")] == ["unknown"]
    assert [row[PROBE_NOW] for row in probe_lines(coord, "cloud")] == ["stream stopped"]
    assert things.entry_id


# ------------------------------------------------- Z-Wave and Matter


def _zwave_network(hass, status, nodes=(4,)):
    """A Z-Wave entry: a client, its driver and a controller."""
    controller = SimpleNamespace(
        home_id=1, status=status,
        nodes={n: SimpleNamespace(node_id=n, status=4, is_controller_node=False) for n in nodes},
    )
    client = SimpleNamespace(driver=SimpleNamespace(controller=controller), connected=True)
    return _entry(hass, "zwave_js", SimpleNamespace(client=client))


def _matter_server(hass, connected):
    node = SimpleNamespace(node_id=5, available=True, node_data=SimpleNamespace(attributes={}))
    client = SimpleNamespace(get_nodes=lambda: [node], connection=SimpleNamespace(connected=connected))
    return _entry(hass, "matter", SimpleNamespace(adapter=SimpleNamespace(matter_client=client)))


async def test_an_ignored_zwave_or_matter_discovery_writes_nothing_each_minute(hass: HomeAssistant):
    """An ignored add-on or USB discovery is an entry of the same domain.
    Sharing the controller's or server's key, its line would flip
    between the two every minute for good (rule STACK-12)."""
    zwave = _zwave_network(hass, 0)
    matter = _matter_server(hass, True)
    MockConfigEntry(domain="zwave_js", source="ignore", unique_id="usb-1").add_to_hass(hass)
    MockConfigEntry(domain="matter", source="ignore", unique_id="addon-1").add_to_hass(hass)
    coord = await _studied(hass, "Z-Wave", "Matter")
    for minute in range(4):
        coord.probe_tick(1000.0 + 60 * minute)
    assert [row[PROBE_NOW] for row in probe_lines(coord, "controller")] == ["ready"]
    assert [row[PROBE_NOW] for row in probe_lines(coord, "server")] == ["connected"]
    assert zwave.entry_id and matter.entry_id


async def test_two_zwave_networks_have_their_own_lines(hass: HomeAssistant):
    """Two networks each have a controller and a node 4; each keeps its
    own line, tagged with the end of its entry's id."""
    first = _zwave_network(hass, 0)
    second = _zwave_network(hass, 1)
    coord = await _studied(hass, "Z-Wave")
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    one, two = first.entry_id[-8:], second.entry_id[-8:]
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"controller {one}")] == ["ready"]
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"controller {two}")] == ["unresponsive"]
    assert len(probe_lines(coord, f"4 {one}")) == 1 and len(probe_lines(coord, f"4 {two}")) == 1
    assert not probe_lines(coord, "controller") and not probe_lines(coord, "4")


async def test_two_matter_servers_have_their_own_lines(hass: HomeAssistant):
    first = _matter_server(hass, True)
    second = _matter_server(hass, False)
    coord = await _studied(hass, "Matter")
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"server {first.entry_id[-8:]}")] == ["connected"]
    assert [row[PROBE_NOW] for row in probe_lines(coord, f"server {second.entry_id[-8:]}")] == ["disconnected"]
