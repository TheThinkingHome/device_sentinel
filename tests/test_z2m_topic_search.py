# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_z2m_topic_search.py, Version: 0.30.9 (2026-11-27)

"""Each Zigbee2MQTT bridge's base topic, found through MQTT's own subscribe (rule STACK-03).

Every bridge publishes a retained bridge/info message under its base topic,
naming its coordinator's address, and Zigbee2MQTT names its bridge device in
Home Assistant "zigbee2mqtt_bridge_" and that address. These tests run the
search through Home Assistant's real MQTT integration, so the wildcard
matching is Home Assistant's own, not a stand-in: one to four levels are
found, a fifth is not, anything that names no coordinator is ignored, and an
address two topics claim gives no topic.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.device_sentinel import stack_z2m
from custom_components.device_sentinel.const import BRIDGE_RUNNING, STACK_Z2M
from tests.helpers import setup_coordinator

# Home Assistant's MQTT integration leaves its own housekeeping timer.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def _info(address: str) -> str:
    """A bridge/info payload as Zigbee2MQTT publishes it, trimmed."""
    return json.dumps({
        "version": "2.6.3",
        "coordinator": {"ieee_address": address, "type": "zStack3x0"},
        "permit_join": False,
        "config": {"mqtt": {"server": "mqtt://core-mosquitto"}},
    })


async def _heard(hass: HomeAssistant, topic: str, payload: str, retain: bool = False) -> None:
    """A message as a subscriber gets it: retain marks only what the broker
    already held when the subscription began; a change after that arrives
    unmarked, and Home Assistant hands each subscription one retained
    message per topic."""
    async_fire_mqtt_message(hass, topic, payload, retain=retain)
    await hass.async_block_till_done()


async def _finder(hass: HomeAssistant) -> stack_z2m.Z2MTopicFinder:
    finder = stack_z2m.Z2MTopicFinder(hass)
    assert await finder.async_start()
    return finder


@pytest.mark.parametrize("base", [
    "zigbee2mqtt",
    "zigbee2mqtt_upstairs",
    "home/zigbee2mqtt",
    "site/home/zigbee2mqtt",
    "a/b/c/zigbee2mqtt",
    "custom name",
    "with:punctuation",
])
async def test_a_base_topic_one_to_four_levels_deep_is_found(hass, mqtt_mock, base):
    finder = await _finder(hass)
    assert finder.base_for("0x00124b0024c5d7a1") is None, "nothing heard yet"
    await _heard(hass, f"{base}/bridge/info", _info("0x00124b0024c5d7a1"), retain=True)
    assert finder.base_for("0x00124b0024c5d7a1") == base


async def test_a_fifth_level_is_not_found(hass, mqtt_mock):
    finder = await _finder(hass)
    await _heard(hass, "a/b/c/d/zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    assert finder.base_for("0x00124b0024c5d7a1") is None


async def test_each_coordinator_finds_its_own_topic(hass, mqtt_mock):
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "house/upstairs/bridge/info", _info("0x00124b0029aa3b10"))
    assert finder.base_for("0x00124b0024c5d7a1") == "zigbee2mqtt"
    assert finder.base_for("0x00124b0029aa3b10") == "house/upstairs"
    assert finder.base_for("0x00124b00ffffffff") is None


async def test_the_address_is_matched_whatever_its_case(hass, mqtt_mock):
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124B0024C5D7A1"))
    assert finder.base_for(
        stack_z2m.coordinator_address(_device_like("zigbee2mqtt_bridge_0x00124b0024c5d7a1"))
    ) == "zigbee2mqtt"


@pytest.mark.parametrize("payload", [
    "not json",
    "[]",
    "{}",
    json.dumps({"coordinator": "0x00124b0024c5d7a1"}),
    json.dumps({"coordinator": {"type": "zStack3x0"}}),
    json.dumps({"coordinator": {"ieee_address": ""}}),
    json.dumps({"coordinator": {"ieee_address": 5}}),
])
async def test_a_message_that_names_no_coordinator_is_ignored(hass, mqtt_mock, payload):
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "other/bridge/info", payload)
    assert finder.base_for("0x00124b0024c5d7a1") == "zigbee2mqtt"
    # And it never takes over a topic already found.
    await _heard(hass, "zigbee2mqtt/bridge/info", payload)
    assert finder.base_for("0x00124b0024c5d7a1") == "zigbee2mqtt"


async def test_two_topics_claiming_one_coordinator_give_no_topic(hass, mqtt_mock):
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "old/zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    assert finder.base_for("0x00124b0024c5d7a1") is None
    # The stale one cleared from the broker: the other stands alone again.
    await _heard(hass, "old/zigbee2mqtt/bridge/info", "")
    assert finder.base_for("0x00124b0024c5d7a1") == "zigbee2mqtt"


async def test_a_bridge_moved_to_a_new_topic_follows_it(hass, mqtt_mock):
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "zigbee2mqtt/bridge/info", "")
    await _heard(hass, "downstairs/bridge/info", _info("0x00124b0024c5d7a1"))
    assert finder.base_for("0x00124b0024c5d7a1") == "downstairs"


async def test_a_device_topic_that_ends_like_a_bridge_is_not_a_bridge(hass, mqtt_mock):
    """A device whose friendly name holds a slash publishes under the base
    topic; its own state names no coordinator."""
    finder = await _finder(hass)
    await _heard(hass, "zigbee2mqtt/garage/bridge/info", json.dumps({"state": "ON", "linkquality": 120}))
    assert finder._address_of == {}


async def test_stopped_it_hears_nothing_more(hass, mqtt_mock):
    finder = await _finder(hass)
    finder.async_stop()
    assert not finder.started
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    assert finder.base_for("0x00124b0024c5d7a1") is None


async def test_without_mqtt_it_waits_and_says_nothing(hass: HomeAssistant):
    finder = stack_z2m.Z2MTopicFinder(hass)
    assert not await finder.async_start()
    assert not finder.started
    assert finder.base_for("0x00124b0024c5d7a1") is None


def _device_like(identifier: str):
    class _Device:
        identifiers = {("mqtt", identifier)}
    return _Device()


def test_the_coordinator_address_comes_from_the_bridge_identifier():
    assert stack_z2m.coordinator_address(_device_like("zigbee2mqtt_bridge_0x00124B0024C5D7A1")) == "0x00124b0024c5d7a1"
    assert stack_z2m.coordinator_address(_device_like("zigbee2mqtt_0x00124b0024c5d7a1")) is None, "a device, not the bridge"
    assert stack_z2m.coordinator_address(_device_like("zigbee2mqtt_bridge_")) is None


def _bridge(hass: HomeAssistant, entry, address: str, name: str):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("mqtt", f"zigbee2mqtt_bridge_{address}")},
        manufacturer="Zigbee2MQTT", model="Bridge", name=name,
    )


async def test_one_bridge_on_zigbee2mqtt_is_read_as_before(hass, mqtt_mock):
    """Your house: one bridge on the default topic keeps its scope and its
    sensor, from the first update and once the search has heard it."""
    entry = hass.config_entries.async_entries("mqtt")[0]
    _bridge(hass, entry, "0x00124b0024c5d7a1", "Zigbee2MQTT Bridge")
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    assert coord.bridge_stacks == [STACK_Z2M]
    assert coord.bridge_reader(STACK_Z2M).base_topic == "zigbee2mqtt"
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await coord._start_bridge_readers()
    assert coord.bridge_stacks == [STACK_Z2M]
    reader = coord.bridge_reader(STACK_Z2M)
    await _heard(hass, "zigbee2mqtt/bridge/state", '{"state":"online"}')
    assert reader.state == BRIDGE_RUNNING
    coord._notify()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "sensor", "device_sentinel", f"{coord.entry.entry_id}_bridge_{STACK_Z2M}"
    ) == "sensor.device_sentinel_bridge_zigbee2mqtt"
    await coord.async_shutdown()
    assert not coord._topic_finders


async def test_two_bridges_are_each_read_on_their_own_topic(hass, mqtt_mock):
    entry = hass.config_entries.async_entries("mqtt")[0]
    first = _bridge(hass, entry, "0x00124b0024c5d7a1", "Zigbee2MQTT Bridge")
    second = _bridge(hass, entry, "0x00124b0029aa3b10", "Zigbee2MQTT Bridge")
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "house/upstairs/bridge/info", _info("0x00124b0029aa3b10"))
    await coord._start_bridge_readers()
    other = f"z2m:{second.id}"
    assert coord.bridge_stacks == sorted([STACK_Z2M, other])
    assert coord.bridge_reader(STACK_Z2M).bridge_device_id == first.id
    assert coord.bridge_reader(other).base_topic == "house/upstairs"
    # Each listens to its own bridge only.
    await _heard(hass, "house/upstairs/bridge/state", '{"state":"online"}')
    assert coord.bridge_reader(other).state == BRIDGE_RUNNING
    assert coord.bridge_reader(STACK_Z2M).state != BRIDGE_RUNNING, "not until its own bridge says online"
    await _heard(hass, "zigbee2mqtt/bridge/state", '{"state":"online"}')
    assert coord.bridge_reader(STACK_Z2M).state == BRIDGE_RUNNING
    await coord.async_shutdown()


async def test_two_custom_bridges_replace_the_unconfirmed_default_reader(hass, mqtt_mock):
    entry = hass.config_entries.async_entries("mqtt")[0]
    bases = ("zigbee2mqtt-home", "zigbee2mqtt-garage")
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    assert coord.bridge_reader(STACK_Z2M) is not None
    assert STACK_Z2M not in {part["key"] for part in coord.dashboard_status()["parts"]}

    for index, base in enumerate(bases):
        address = f"0x{index:016x}"
        identifier = f"zigbee2mqtt_bridge_{address}"
        await _heard(hass, f"homeassistant/sensor/{base}_bridge/config", json.dumps({
            "unique_id": f"{base}_bridge_state",
            "state_topic": f"{base}/bridge/state",
            "device": {"identifiers": [identifier], "name": "Renamed bridge",
                       "manufacturer": "Zigbee2MQTT", "model": "Bridge"},
        }))
        roll = []
        for child in range(index + 1):
            ieee = f"0x{index * 10 + child + 10:016x}"
            roll.append({"ieee_address": ieee, "friendly_name": f"sensor_{child}"})
            await _heard(hass, f"homeassistant/sensor/{base}_{child}/config", json.dumps({
                "unique_id": f"{base}_sensor_{child}",
                "state_topic": f"{base}/sensor_{child}",
                "availability_topic": f"{base}/bridge/state",
                "device": {"identifiers": [f"zigbee2mqtt_{ieee}"], "name": f"{base} sensor {child}"},
            }))
        await _heard(hass, f"{base}/bridge/info", _info(address), retain=True)
        await coord._start_bridge_readers()
        await _heard(hass, f"{base}/bridge/devices", json.dumps(roll), retain=True)
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 5
    coord._rebuild_registry_view()
    await coord._start_bridge_readers()
    assert coord.bridge_reader(STACK_Z2M) is None
    for base in bases:
        await _heard(hass, f"{base}/bridge/state", '{"state":"online"}')

    parts = {part["name"]: part["state"] for part in coord.dashboard_status()["parts"] if part["key"].startswith("z2m")}
    assert parts == {f"Bridge: {base}": BRIDGE_RUNNING for base in bases}
    rows = {row["name"]: row["watched"] for row in coord.dashboard_networks() if row["kind"] == STACK_Z2M}
    assert rows == {f"Zigbee2MQTT: {base}": index + 1 for index, base in enumerate(bases)}
    await coord.async_shutdown()


async def test_a_bridge_deeper_than_four_levels_waits_unknown(hass, mqtt_mock):
    """Not found, so not guessed: the other bridge is read, and this one
    gets no reader of its own rather than a wrong one."""
    entry = hass.config_entries.async_entries("mqtt")[0]
    _bridge(hass, entry, "0x00124b0024c5d7a1", "Zigbee2MQTT Bridge")
    deep = _bridge(hass, entry, "0x00124b0029aa3b10", "Deep")
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    await _heard(hass, "zigbee2mqtt/bridge/info", _info("0x00124b0024c5d7a1"))
    await _heard(hass, "a/b/c/d/radio/bridge/info", _info("0x00124b0029aa3b10"))
    await coord._start_bridge_readers()
    assert coord.bridge_stacks == [STACK_Z2M]
    assert coord.bridge_reader(f"z2m:{deep.id}") is None
    await coord.async_shutdown()


async def test_a_bridge_heard_after_startup_is_picked_up(hass, mqtt_mock):
    entry = hass.config_entries.async_entries("mqtt")[0]
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    late = _bridge(hass, entry, "0x00124b0029aa3b10", "Upstairs")
    await _heard(hass, "upstairs/bridge/info", _info("0x00124b0029aa3b10"))
    await coord._start_bridge_readers()
    assert coord.bridge_reader(f"z2m:{late.id}").base_topic == "upstairs"
    await coord.async_shutdown()


async def test_mqtt_loaded_after_device_sentinel_starts_the_search_then(hass: HomeAssistant):
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    finder = coord._topic_finders[STACK_Z2M]
    assert not finder.started, "asked again at the next update"
