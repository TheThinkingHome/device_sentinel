# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_reachability.py, Version: 0.12.3 (2026-08-05)

"""Zigbee2MQTT reachability, replayed against a captured fleet.

The fixtures in tests/fixtures are the reference fleet as the broker
published it on 2026-08-05: 75 entries in bridge/devices, 81
availability topics, and the bridge's own availability configuration.
Six of those topics name nothing that exists and two of the six read
online, which is the case that would otherwise contradict a correct
verdict (ruling #221).

Nothing here changes a verdict. Reachability is a second opinion that
confirms or doubts, and every path that cannot answer returns None,
which every caller reads as no opinion.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_z2m
from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    DATA_BRIDGE_SEEN,
    DATA_SYSTEM_EVENTS,
    SYS_BRIDGE_UP,
    SYS_KIND,
)
from tests.helpers import setup_coordinator

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DEVICES = json.loads((FIXTURES / "z2m_bridge_devices.json").read_text())
AVAILABILITY = json.loads((FIXTURES / "z2m_availability.json").read_text())
INFO = json.loads((FIXTURES / "z2m_bridge_info.json").read_text())

# The six topics with no device behind them, from the capture: three
# groups, a removed device, and two left by a rename. The last two
# read online, which is why the reconciliation exists.
ORPHAN_TOPICS = {
    "901",
    "Guest Bedroom Group",
    "Living Room Group",
    "Master Bedroom Group",
    "SLZB-06 Router",
    "Window Master Park Right 2",
}


def _msg(topic: str, payload):
    """Return the shape an MQTT callback receives."""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    return SimpleNamespace(topic=topic, payload=payload)


def _loaded_reader() -> stack_z2m.Z2MBridgeReader:
    """Return a reader fed the whole captured fleet."""
    reader = stack_z2m.Z2MBridgeReader(None)
    reader._on_info(_msg("zigbee2mqtt/bridge/info", INFO))
    reader._on_devices(_msg("zigbee2mqtt/bridge/devices", DEVICES))
    for name, state in AVAILABILITY.items():
        reader._on_availability(
            _msg(f"zigbee2mqtt/{name}/availability", {"state": state})
        )
    return reader


def _stub_reader(state: str) -> SimpleNamespace:
    """Return the smallest thing the sampler and shutdown both accept."""
    return SimpleNamespace(
        state=state,
        pairing_open=False,
        permit_join_end=None,
        async_stop=lambda: None,
        reachability=lambda key: None,
    )


def _ieee(friendly_name: str) -> str:
    """Return the IEEE address the bridge gives a device."""
    for entry in DEVICES:
        if entry["friendly_name"] == friendly_name:
            return entry["ieee_address"]
    raise AssertionError(friendly_name)


def test_the_capture_is_the_shape_the_design_assumed():
    """Guard the fixture itself, so the replay cannot drift."""
    assert len(DEVICES) == 75
    assert len(AVAILABILITY) == 81
    availability = INFO["config"]["availability"]
    assert availability["enabled"] is True
    assert availability["active"]["timeout"] == 10
    assert availability["passive"]["timeout"] == 1500


def test_every_topic_without_a_device_is_rejected():
    """Groups, a removed device, and two left by a rename."""
    reader = _loaded_reader()
    assert set(reader.reachability_rejected) == ORPHAN_TOPICS


def test_the_two_stale_topics_read_online_and_still_answer_nothing():
    """The case the reconciliation exists for.

    Both read online while naming no device. Asked by any IEEE
    address, they can never be the answer, because the join runs
    through the device roll rather than the topic name.
    """
    reader = _loaded_reader()
    for name in ("SLZB-06 Router", "Window Master Park Right 2"):
        assert AVAILABILITY[name] == "online"
        assert name not in {entry["friendly_name"] for entry in DEVICES}
    joined = {
        entry["ieee_address"]
        for entry in DEVICES
        if reader.reachability(entry["ieee_address"]) is not None
    }
    assert len(joined) == 75


def test_a_battery_device_carries_its_own_long_timeout():
    """55 of 75 are judged on 25 hours of silence, not 10 minutes."""
    reader = _loaded_reader()
    seen = reader.reachability(_ieee("Door 2nd Bedroom"))
    assert seen == {
        "state": "online",
        "at": seen["at"],
        "class": "passive",
        "timeout_minutes": 1500,
    }


def test_a_mains_device_carries_the_short_one():
    """The 19 devices where the bridge is quicker than a window."""
    reader = _loaded_reader()
    seen = reader.reachability(_ieee("Plug Laundry Router"))
    assert seen["class"] == "active"
    assert seen["timeout_minutes"] == 10


def test_the_dead_device_reads_offline():
    """The FJ40, silent since 20 July and offline in the capture."""
    reader = _loaded_reader()
    seen = reader.reachability(_ieee("Vibration FJ40 Land Cruiser"))
    assert seen["state"] == "offline"


def test_an_unknown_key_and_a_silent_bridge_answer_nothing():
    """Every path that cannot say returns None (ruling #221)."""
    reader = _loaded_reader()
    assert reader.reachability("0xdeadbeefdeadbeef") is None
    assert reader.reachability(None) is None
    assert reader.reachability("") is None
    assert stack_z2m.Z2MBridgeReader(None).reachability("0x1") is None


def test_availability_switched_off_answers_nothing():
    """A house that does not publish availability loses nothing."""
    reader = stack_z2m.Z2MBridgeReader(None)
    off = {"permit_join": False, "config": {"availability": {"enabled": False}}}
    reader._on_info(_msg("zigbee2mqtt/bridge/info", off))
    reader._on_devices(_msg("zigbee2mqtt/bridge/devices", DEVICES))
    reader._on_availability(
        _msg("zigbee2mqtt/Door 2nd Bedroom/availability", {"state": "offline"})
    )
    assert reader.reachability_known is False
    assert reader.reachability(_ieee("Door 2nd Bedroom")) is None


def test_a_malformed_roll_leaves_the_previous_one_standing():
    """An empty roll would silently reject every topic."""
    reader = _loaded_reader()
    reader._on_devices(_msg("zigbee2mqtt/bridge/devices", "not a list"))
    reader._on_devices(_msg("zigbee2mqtt/bridge/devices", []))
    assert reader.reachability(_ieee("Door 2nd Bedroom")) is not None


def test_the_device_key_is_the_ieee_out_of_the_identifier():
    """The join Home Assistant's side, from the live identifier."""
    device = SimpleNamespace(
        identifiers={("mqtt", "zigbee2mqtt_0x282c02bfffeafa5b")}
    )
    assert stack_z2m.device_key(device) == "0x282c02bfffeafa5b"
    assert stack_z2m.device_key(
        SimpleNamespace(identifiers={("mqtt", "nspanel_pro_james")})
    ) is None
    assert stack_z2m.device_key(
        SimpleNamespace(identifiers={("zha", "0x282c02bfffeafa5b")})
    ) is None


def test_matching_on_name_would_be_wrong_on_this_fleet():
    """Why the join is the IEEE address and not the friendly name.

    One switch carries a different name on each side, so a name join
    would drop it and mis-join nothing to it. The IEEE address is the
    same string in the bridge roll and the Home Assistant identifier.
    """
    names = {entry["friendly_name"] for entry in DEVICES}
    assert "Switch Hall Master" in names
    assert "Switch Master Entryway" not in names
    assert _ieee("Door 2nd Bedroom") == "0x282c02bfffeafa5b"


async def test_the_phrase_carries_the_timeout(hass: HomeAssistant):
    """A bare "reads online" would make a correct verdict look wrong."""
    coord = await setup_coordinator(hass)
    reader = _loaded_reader()
    coord._bridge_readers["z2m"] = reader
    coord._stack_keys = {
        "battery": ("z2m", _ieee("Door 2nd Bedroom")),
        "mains": ("z2m", _ieee("Plug Laundry Router")),
        "dead": ("z2m", _ieee("Vibration FJ40 Land Cruiser")),
    }
    assert coord.reachability_phrase("dead") == (
        "Zigbee2MQTT confirms it is offline."
    )
    assert coord.reachability_phrase("battery") == (
        "Zigbee2MQTT reads it as online, though it allows a battery "
        "device 25 hours of silence before saying otherwise."
    )
    assert coord.reachability_phrase("mains") == (
        "Zigbee2MQTT reads it as online, and it pings a mains device "
        "every 10 minutes."
    )
    assert coord.reachability_phrase("unknown_device") is None


async def test_a_reader_that_raises_is_no_opinion(hass: HomeAssistant):
    """A second opinion can never break the verdict it sits beside."""

    class Broken:
        state = BRIDGE_RUNNING
        pairing_open = False

        def reachability(self, key):
            raise RuntimeError("no")

        def async_stop(self):
            return None

    coord = await setup_coordinator(hass)
    coord._bridge_readers["z2m"] = Broken()
    coord._stack_keys = {"d1": ("z2m", "0x1")}
    assert coord.reachability("d1") is None
    assert coord.reachability_phrase("d1") is None


async def test_an_outage_spanning_a_restart_closes(hass: HomeAssistant):
    """The bridge_up that two nights on the fleet never got.

    The bridge went down at 03:40 and the house rebooted at 03:42, so
    the state it was in died with the process and the recovery was
    never written. Restored from storage, the next sample closes the
    outage with its real duration (ruling #222).
    """
    coord = await setup_coordinator(hass)
    down_at = 1785000000.0
    coord.data[DATA_BRIDGE_SEEN] = {
        "z2m": {BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: down_at}
    }
    coord._bridge_seen.clear()
    coord._bridge_down_at.clear()
    coord._restore_bridge_state()
    assert coord._bridge_seen["z2m"] == BRIDGE_DOWN
    assert coord._bridge_down_at["z2m"] == down_at

    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    coord._sample_bridges()

    ups = [
        event
        for event in coord.data[DATA_SYSTEM_EVENTS]
        if event[SYS_KIND] == SYS_BRIDGE_UP
    ]
    assert len(ups) == 1
    assert ups[0]["duration"] > 0
    assert coord.data[DATA_BRIDGE_SEEN]["z2m"][BRIDGE_SEEN_STATE] == (
        BRIDGE_RUNNING
    )


async def test_a_fresh_install_records_no_bridge_event(
    hass: HomeAssistant,
):
    """Nothing stored is a start, not a recovery."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_BRIDGE_SEEN] = {}
    coord._bridge_seen.clear()
    coord._restore_bridge_state()
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    coord._sample_bridges()
    assert len(coord.data[DATA_SYSTEM_EVENTS]) == before


async def test_the_registry_walk_records_the_key(hass: HomeAssistant):
    """The map the accessor reads, built on the walk that exists."""
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_0x282c02bfffeafa5b")},
        name="Door 2nd Bedroom",
    )
    coord = await setup_coordinator(hass)
    assert coord._stack_keys.get(device.id) == (
        "z2m",
        "0x282c02bfffeafa5b",
    )
