# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_multiple_z2m_bridges.py, Version: 0.30.9 (2026-11-27)

"""Independent MQTT bridge discovery, ownership and pairing (rule STACK-03)."""

import inspect
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_z2m
from custom_components.device_sentinel.const import (
    BRIDGE_DOWN, BRIDGE_RUNNING, BRIDGE_HANDBACK_SECONDS, BRIDGE_DOWN_WAIT_SECONDS,
    DATA_BRIDGE_SEEN, DATA_SYSTEM_EVENTS, BRIDGE_SEEN_STATE, BRIDGE_SEEN_SINCE,
    DEV_LOGNORMAL_DAYS, DATA_DEVICES, STACK_Z2M, SYS_SCOPE, SYS_KIND, SYS_BRIDGE_DOWN,
)
from tests.helpers import setup_coordinator


def _message(payload, *, retain=False):
    return SimpleNamespace(payload=json.dumps(payload), retain=retain)


def _fleet(hass, monkeypatch):
    """Two equally named bridges, nested prefixes and distinct children."""
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    bridges, children, payloads = [], [], {}
    for index, base in enumerate(("house/downstairs/radio", "upstairs-custom")):
        identifier = f"zigbee2mqtt_bridge_0x{index:016x}"
        bridge = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", identifier)}, name="Renamed coordinator",
        )
        parent = (
            {"via_device_id": bridge.id}
            if "via_device_id" in inspect.signature(registry.async_get_or_create).parameters
            else {"via_device": ("mqtt", identifier)}
        )
        child = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", f"zigbee2mqtt_0x{index + 10:016x}")},
            **parent, name=f"Sensor {index}",
        )
        payloads[bridge.id] = base
        bridges.append(bridge)
        children.append(child)
    _answer_topics(monkeypatch, bridges, payloads)
    return source, bridges, children, payloads


def _answer_topics(monkeypatch, bridges, bases):
    """Each bridge's base topic as the topic search would hear it, by its
    coordinator address; None for one not heard yet. The search itself is
    proved through Home Assistant's own MQTT in test_z2m_topic_search.py."""
    def base_for(_finder, address):
        return next((
            bases.get(bridge.id) for bridge in bridges
            if stack_z2m.coordinator_address(bridge) == address
        ), None)
    monkeypatch.setattr(stack_z2m.Z2MTopicFinder, "base_for", base_for)


async def test_renamed_bridges_have_independent_topics_and_ownership(hass, monkeypatch):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    readers = stack_z2m.make_readers(hass, stack_z2m.Z2MTopicFinder(hass))
    assert len(readers) == 2
    first, second = readers.values()
    assert first.base_topic == "house/downstairs/radio"
    assert second.base_topic == "upstairs-custom"
    assert all(stack_z2m.detects("mqtt", bridge) for bridge in bridges)
    first._on_state(_message({"state": "offline"}))
    second._on_state(_message({"state": "online"}))
    second._on_info(_message({"permit_join": True}))
    assert first.state == BRIDGE_DOWN
    assert second.pairing_open
    for child, expected in zip(children, (first, second), strict=True):
        assert stack_z2m.reader_for_device(readers, hass, child.id) is expected


async def test_parent_wins_over_stale_roll_and_ambiguous_ieee_is_unknown(hass, monkeypatch):
    _source, _bridges, children, _payloads = _fleet(hass, monkeypatch)
    readers = stack_z2m.make_readers(hass, stack_z2m.Z2MTopicFinder(hass))
    first, second = readers.values()
    ieee = stack_z2m.device_key(children[0])
    for reader in (first, second):
        reader._on_devices(_message([{"friendly_name": "same", "ieee_address": ieee}]))
    assert stack_z2m.reader_for_device(readers, hass, children[0].id) is first
    dr.async_get(hass).async_update_device(children[0].id, via_device_id=None)
    assert stack_z2m.reader_for_device(readers, hass, children[0].id) is None
    # An empty roll leaves the last one standing, as it always has, so the
    # address stays claimed twice and still gives no opinion.
    second._on_devices(_message([]))
    assert stack_z2m.reader_for_device(readers, hass, children[0].id) is None


@pytest.mark.parametrize("factor", [1, 1000])
async def test_pairing_deadlines_are_independent_and_expire_without_mqtt(hass, monkeypatch, factor):
    _source, _bridges, _children, _payloads = _fleet(hass, monkeypatch)
    first, second = stack_z2m.make_readers(hass, stack_z2m.Z2MTopicFinder(hass)).values()
    now = dt_util.utcnow()
    end = now + timedelta(seconds=30)
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    for reader in (first, second):
        reader._on_state(_message({"state": "online"}))
    first._on_info(_message({"permit_join": True, "permit_join_end": end.timestamp() * factor}, retain=True))
    second._on_info(_message({"permit_join": True, "permit_join_end": (now.timestamp() - 1) * factor}, retain=True))
    assert first.pairing_open
    assert second.state == BRIDGE_RUNNING
    assert second.pairing_changed_at is None
    assert not second.pairing_active_within(10, now.timestamp())

    now = end + timedelta(seconds=5)
    assert first.state == BRIDGE_RUNNING
    assert first.permit_join_end is None
    assert first.pairing_changed_at == pytest.approx(end.timestamp())
    assert first.pairing_active_within(10, now.timestamp())
    assert not first.pairing_active_within(10, now.timestamp() + 6)
    first._on_info(_message({"permit_join": "false"}))
    assert first.state == BRIDGE_RUNNING


async def test_each_reader_subscribes_only_to_its_prefix(hass, monkeypatch):
    source, _bridges, _children, _payloads = _fleet(hass, monkeypatch)
    source.mock_state(hass, ConfigEntryState.LOADED)
    subscribe = AsyncMock(return_value=Mock())
    monkeypatch.setattr(stack_z2m.mqtt, "async_subscribe", subscribe)
    monkeypatch.setattr(stack_z2m.mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    for reader in stack_z2m.make_readers(hass, stack_z2m.Z2MTopicFinder(hass)).values():
        subscribe.reset_mock()
        assert await reader.async_start()
        assert {call.args[1] for call in subscribe.call_args_list} == {
            f"{reader.base_topic}/{suffix}" for suffix in (
                "bridge/event", "bridge/state", "bridge/info", "bridge/devices", "+/availability",
            )
        }
        reader.async_stop()


async def test_late_discovery_and_topic_change_keep_stable_scope(hass, monkeypatch):
    from homeassistant.helpers import entity_registry as er

    _source, bridges, _children, payloads = _fleet(hass, monkeypatch)
    start = AsyncMock(return_value=False)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", start)
    saved = payloads[bridges[0].id]
    payloads[bridges[0].id] = None
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    scope = f"z2m:{bridges[0].id}"
    # Its topic decides its scope, so a bridge not known yet gets no reader
    # and no sensor; the other bridge is read as usual.
    assert coord.bridge_reader(scope) is None
    assert coord.bridge_reader(f"z2m:{bridges[1].id}").base_topic == "upstairs-custom"
    registry = er.async_get(hass)
    unique_id = f"{coord.entry.entry_id}_bridge_{scope}"
    assert registry.async_get_entity_id("sensor", "device_sentinel", unique_id) is None

    async def assert_labels(label):
        coord._notify()
        await hass.async_block_till_done()
        name = f"Bridge: {label}"
        parts = {part["key"]: part["name"] for part in coord.dashboard_status()["parts"]}
        assert parts[scope] == name
        assert parts[f"z2m:{bridges[1].id}"] == "Bridge: upstairs-custom"
        assert coord._outage_label(SYS_BRIDGE_DOWN, scope) == name
        assert registry.async_get(entity_id).original_name == name
        assert hass.states.get(entity_id).attributes["friendly_name"].endswith(name)

    payloads[bridges[0].id] = saved
    await coord._start_bridge_readers()
    coord._notify()
    await hass.async_block_till_done()
    entity_id = registry.async_get_entity_id("sensor", "device_sentinel", unique_id)
    assert entity_id is not None
    assert coord.bridge_reader(scope).base_topic == "house/downstairs/radio"
    await assert_labels("house/downstairs/radio")
    # Discovery briefly missing keeps the reader it already has.
    payloads[bridges[0].id] = None
    await coord._start_bridge_readers()
    assert coord.bridge_reader(scope).base_topic == "house/downstairs/radio"
    assert coord.network_name(scope) == "Zigbee2MQTT: house/downstairs/radio"
    payloads[bridges[0].id] = "new/prefix"
    await coord._start_bridge_readers()
    assert coord.bridge_reader(scope).base_topic == "new/prefix"
    await assert_labels("new/prefix")
    assert len(coord.bridge_stacks) == 2


async def test_coordinator_isolates_outages_pairing_and_networks(hass, monkeypatch):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    first_scope, second_scope = (f"z2m:{bridge.id}" for bridge in bridges)
    first, second = (coord.bridge_reader(scope) for scope in (first_scope, second_scope))
    for child in children:
        coord._watched[child.id] = "mqtt"
        coord._radio_stack[child.id] = STACK_Z2M
        coord._stack_keys[child.id] = (STACK_Z2M, stack_z2m.device_key(child))
    first._on_state(_message({"state": "online"}))
    first._on_info(_message({"permit_join": True}))
    second._on_state(_message({"state": "online"}))
    second._on_info(_message({"permit_join": False}))
    assert second.state == BRIDGE_RUNNING
    assert coord._recovered_during_pairing(children[0].id, 0)
    assert not coord._recovered_during_pairing(children[1].id, 0)
    coord._bridge_down_pending[first_scope] = 1
    assert coord._held_by_upstream(children[0].id, 2)
    assert not coord._held_by_upstream(children[1].id, 2)
    assert coord._upstream_devices(first_scope) == 1
    assert coord.device_networks(children[0].id) == [first_scope]
    assert coord.device_networks(children[1].id) == [second_scope]
    assert first_scope in coord.network_keys()
    assert second_scope in coord.network_keys()
    assert STACK_Z2M not in coord.network_keys()
    assert coord.network_name(first_scope) != coord.network_name(second_scope)
    unrelated = dr.async_get(hass).async_get_or_create(
        config_entry_id=_source.entry_id, identifiers={("mqtt", "tasmota")}, name="Other MQTT",
    )
    coord._watched[unrelated.id] = "mqtt"
    assert coord._stack_for_device(unrelated.id) is None


async def test_same_friendly_name_never_shares_availability(hass, monkeypatch):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    for index, (bridge, child) in enumerate(zip(bridges, children, strict=True)):
        coord._watched[child.id] = "mqtt"
        ieee = stack_z2m.device_key(child)
        coord._stack_keys[child.id] = (STACK_Z2M, ieee)
        reader = coord.bridge_reader(f"z2m:{bridge.id}")
        reader._on_devices(_message([{"friendly_name": "same", "ieee_address": ieee}]))
        reader._on_info(_message({"config": {"availability": {"enabled": True}}}))
        state = "offline" if index == 0 else "online"
        reader._on_availability(SimpleNamespace(topic=f"{reader.base_topic}/same/availability", payload=json.dumps({"state": state})))
    assert coord.reachability(children[0].id)["state"] == "offline"
    assert coord.reachability(children[1].id)["state"] == "online"


async def test_join_recorders_restart_only_the_owning_device(hass, monkeypatch):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    for child in children:
        coord._watched[child.id] = "mqtt"
        coord._stack_keys[child.id] = (STACK_Z2M, stack_z2m.device_key(child))
        coord.data[DATA_DEVICES].setdefault(child.id, {})[DEV_LOGNORMAL_DAYS] = 30
    first = coord.bridge_reader(f"z2m:{bridges[0].id}")
    first._on_state(_message({"state": "online"}))
    first._on_info(_message({"permit_join": True}))
    first._on_event(_message({"type": "device_joined", "data": {"ieee_address": stack_z2m.device_key(children[0])}}))
    assert coord.data[DATA_DEVICES][children[0].id][DEV_LOGNORMAL_DAYS] == 0
    assert coord.data[DATA_DEVICES][children[1].id][DEV_LOGNORMAL_DAYS] == 30


async def test_sampler_confirms_only_the_failed_instance(hass, monkeypatch, freezer):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    scopes = [f"z2m:{bridge.id}" for bridge in bridges]
    for bridge, child in zip(bridges, children, strict=True):
        coord._watched[child.id] = "mqtt"
        reader = coord.bridge_reader(f"z2m:{bridge.id}")
        reader._on_state(_message({"state": "online"}))
        reader._on_info(_message({"permit_join": False}))
    coord._sample_bridges()
    coord.bridge_reader(scopes[0])._on_state(_message({"state": "offline"}))
    coord._sample_bridges()
    freezer.tick(BRIDGE_DOWN_WAIT_SECONDS + 1)
    coord._sample_bridges()
    downs = [row for row in coord.data[DATA_SYSTEM_EVENTS] if row[SYS_KIND] == SYS_BRIDGE_DOWN]
    assert [row[SYS_SCOPE] for row in downs] == [scopes[0]]
    assert coord.upstream_down_since(children[0].id)[0] == scopes[0]
    assert coord.upstream_down_since(children[1].id) is None
    coord.bridge_reader(scopes[0])._on_state(_message({"state": "online"}))
    coord._sample_bridges()
    assert scopes[0] in coord._bridge_handback
    assert scopes[1] not in coord._bridge_handback


async def test_restart_restores_only_the_failed_bridge_and_handback(hass, monkeypatch, freezer):
    _source, bridges, children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    scopes = [f"z2m:{bridge.id}" for bridge in bridges]
    now = dt_util.utcnow().timestamp()
    for child in children:
        coord._watched[child.id] = "mqtt"
    coord.data[DATA_BRIDGE_SEEN] = {
        scopes[0]: {BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: now - 300},
        scopes[1]: {BRIDGE_SEEN_STATE: BRIDGE_RUNNING},
    }
    coord._restore_bridge_state()
    assert coord.upstream_down_since(children[0].id) is not None
    assert coord.upstream_down_since(children[1].id) is None
    coord._bridge_down_at.pop(scopes[0])
    coord._bridge_handback[scopes[0]] = (now - 300, now)
    assert coord.upstream_down_since(children[0].id) is not None
    assert coord.upstream_down_since(children[1].id) is None
    freezer.tick(BRIDGE_HANDBACK_SECONDS + 1)
    assert coord.upstream_down_since(children[0].id) is None


async def test_missing_discovery_never_subscribes_to_default(hass, monkeypatch):
    reader = stack_z2m.Z2MBridgeReader(hass, None)
    subscribe = AsyncMock()
    monkeypatch.setattr(stack_z2m.mqtt, "async_subscribe", subscribe)
    assert not await reader.async_start()
    subscribe.assert_not_called()


async def test_removed_bridge_unsubscribes_without_affecting_the_other(hass, monkeypatch):
    _source, bridges, _children, _payloads = _fleet(hass, monkeypatch)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    scopes = [f"z2m:{bridge.id}" for bridge in bridges]
    stopped = Mock()
    first = coord.bridge_reader(scopes[0])
    first._unsubs.append(stopped)
    second = coord.bridge_reader(scopes[1])
    dr.async_get(hass).async_remove_device(bridges[0].id)
    await coord._start_bridge_readers()
    stopped.assert_called_once()
    assert coord.bridge_reader(scopes[0]) is None
    assert coord.bridge_reader(scopes[1]) is second


async def test_late_bridge_gets_a_sensor_without_renaming_existing_ones(hass, monkeypatch):
    from homeassistant.helpers import entity_registry as er

    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    _source, bridges, _children, _payloads = _fleet(hass, monkeypatch)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    coord._notify()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    unique_ids = {
        entity.unique_id for entity in er.async_entries_for_config_entry(registry, coord.entry.entry_id)
        if "bridge_z2m:" in entity.unique_id
    }
    assert unique_ids == {
        f"{coord.entry.entry_id}_bridge_z2m:{bridge.id}" for bridge in bridges
    }
    dr.async_get(hass).async_update_device(bridges[0].id, name_by_user="New name")
    await coord._start_bridge_readers()
    coord._notify()
    await hass.async_block_till_done()
    assert unique_ids == {
        entity.unique_id for entity in er.async_entries_for_config_entry(registry, coord.entry.entry_id)
        if "bridge_z2m:" in entity.unique_id
    }


async def test_one_bridge_on_the_default_topic_keeps_its_scope_and_sensor(hass, monkeypatch):
    """A house with one bridge on zigbee2mqtt sees no change (rule STACK-03)."""
    from homeassistant.helpers import entity_registry as er

    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_bridge_0x00000000000000aa")}, name="Zigbee2MQTT Bridge",
    )
    payloads = {bridge.id: "zigbee2mqtt"}
    bridges = [bridge]
    _answer_topics(monkeypatch, bridges, payloads)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    assert coord.bridge_stacks == [STACK_Z2M]
    assert coord.bridge_reader(STACK_Z2M).base_topic == "zigbee2mqtt"
    coord._notify()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "sensor", "device_sentinel", f"{coord.entry.entry_id}_bridge_{STACK_Z2M}"
    ) is not None
    assert not [e for e in registry.entities.values() if "bridge_z2m:" in e.unique_id]

    # A second bridge added later gets its own scope and sensor; the first
    # keeps both.
    second = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_bridge_0x00000000000000bb")}, name="Upstairs",
    )
    bridges.append(second)
    payloads[second.id] = "upstairs"
    await coord._start_bridge_readers()
    assert coord.bridge_stacks == sorted([STACK_Z2M, f"z2m:{second.id}"])
    assert coord.bridge_reader(STACK_Z2M).base_topic == "zigbee2mqtt"


async def test_a_bridge_not_known_yet_is_read_on_the_default_topic(hass, monkeypatch):
    """Discovery not ready at startup: the reader older releases made."""
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_bridge_0x00000000000000aa")}, name="Zigbee2MQTT Bridge",
    )
    payloads = {bridge.id: None}
    _answer_topics(monkeypatch, [bridge], payloads)
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    first = coord.bridge_reader(STACK_Z2M)
    assert coord.bridge_stacks == [STACK_Z2M]
    assert first.base_topic == "zigbee2mqtt"
    assert STACK_Z2M not in {part["key"] for part in coord.dashboard_status()["parts"]}
    first._on_state(_message({"state": "online"}))
    assert STACK_Z2M in {part["key"] for part in coord.dashboard_status()["parts"]}
    payloads[bridge.id] = "zigbee2mqtt"
    await coord._start_bridge_readers()
    assert coord.bridge_reader(STACK_Z2M) is first, "the same reader, not a second one"
    assert first.bridge_device_id == bridge.id


async def test_a_saved_outage_on_the_default_bridge_stays_where_it_was(hass, monkeypatch):
    _source, bridges, children, payloads = _fleet(hass, monkeypatch)
    payloads[bridges[0].id] = "zigbee2mqtt"
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_BRIDGE_SEEN] = {STACK_Z2M: {
        BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: now - 300,
    }}
    coord._restore_bridge_state()
    await coord._start_bridge_readers()
    assert coord._bridge_down_at[STACK_Z2M] == now - 300
    assert not any(scope.startswith("z2m:") for scope in coord._bridge_down_at)


async def test_the_default_bridge_and_another_each_have_a_network_and_their_own_devices(hass, monkeypatch):
    _source, bridges, children, payloads = _fleet(hass, monkeypatch)
    payloads[bridges[0].id] = "zigbee2mqtt"
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    coord._stacks.add(STACK_Z2M)
    await coord._start_bridge_readers()
    other = f"z2m:{bridges[1].id}"
    for child in children:
        coord._watched[child.id] = "mqtt"
        coord._radio_stack[child.id] = STACK_Z2M
        coord._stack_keys[child.id] = (STACK_Z2M, stack_z2m.device_key(child))
    assert coord.device_networks(children[0].id) == [STACK_Z2M]
    assert coord.device_networks(children[1].id) == [other]
    keys = coord.network_keys()
    assert STACK_Z2M in keys and other in keys
    assert keys.index(other) == keys.index(STACK_Z2M) + 1
    coord.bridge_reader(STACK_Z2M)._on_state(_message({"state": "online"}))
    coord.bridge_reader(STACK_Z2M)._on_info(_message({"permit_join": True}))
    assert coord._recovered_during_pairing(children[0].id, 0)
    assert not coord._recovered_during_pairing(children[1].id, 0)


async def test_existing_default_bridge_sensor_is_reused_after_late_discovery(hass, monkeypatch):
    """The sensor people's automations use, renamed by them, is the one
    the default bridge keeps once its topic is heard (from Reifircax's
    regression test)."""
    from homeassistant.helpers import entity_registry as er

    _source, bridges, _children, payloads = _fleet(hass, monkeypatch)
    payloads[bridges[0].id] = None
    monkeypatch.setattr(stack_z2m.Z2MBridgeReader, "async_start", AsyncMock(return_value=False))
    coord = await setup_coordinator(hass)
    registry = er.async_get(hass)
    unique_id = f"{coord.entry.entry_id}_bridge_z2m"
    existing = registry.async_get_or_create(
        "sensor", "device_sentinel", unique_id, config_entry=coord.entry,
        suggested_object_id="device_sentinel_bridge_zigbee2mqtt", original_name="Bridge: Zigbee2MQTT",
    )
    entity_id = existing.entity_id
    assert entity_id == "sensor.device_sentinel_bridge_zigbee2mqtt"
    registry.async_update_entity(entity_id, name="Zigbee used in automations")

    coord._stacks.add(STACK_Z2M)
    payloads[bridges[0].id] = "zigbee2mqtt"
    await coord._start_bridge_readers()
    custom_scope = f"z2m:{bridges[1].id}"
    default = coord.bridge_reader(STACK_Z2M)
    default._on_state(_message({"state": "online"}))
    default._on_info(_message({"permit_join": False}))
    coord.bridge_reader(custom_scope)._on_state(_message({"state": "offline"}))
    coord._notify()
    await hass.async_block_till_done()

    assert registry.async_get_entity_id("sensor", "device_sentinel", unique_id) == entity_id
    assert registry.async_get(entity_id).name == "Zigbee used in automations"
    default_state = hass.states.get(entity_id)
    assert default_state.state == BRIDGE_RUNNING
    assert default_state.attributes["stack"] == STACK_Z2M
    assert default_state.attributes["sentinel_type"] == "bridge_z2m"
    assert not [e for e in registry.entities.values() if e.unique_id == f"{coord.entry.entry_id}_bridge_z2m:{bridges[0].id}"]
    custom_sensor = registry.async_get_entity_id(
        "sensor", "device_sentinel", f"{coord.entry.entry_id}_bridge_{custom_scope}"
    )
    assert hass.states.get(custom_sensor).state == BRIDGE_DOWN
