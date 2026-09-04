# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_reachability.py, Version: 0.20.1 (2026-09-04)

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
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import stack_z2m
from custom_components.device_sentinel.const import (
    EVENT_UPSTREAM_DOWN,
    EVENT_UPSTREAM_RESTORED,
    INTEGRATION_DOWN_DWELL_SECONDS,
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


# The upstream events (ruling #381). A stopped broker or bridge
# silences every device behind it deliberately, so until this pair
# existed the one failure that takes a house quiet was the one an
# automation could not see.


def _heard(hass, kind):
    """Collect one event kind off the bus."""
    seen: list = []
    hass.bus.async_listen(kind, lambda event: seen.append(event.data))
    return seen


def _past_grace(coord):
    """Leave the startup grace, where the bus is deliberately silent.

    Everything reports at once on a restart and none of it is news
    (ruling #291), so a freshly built coordinator fires nothing. A
    test about the bus has to step outside that window first.
    """
    coord._grace_until = 0.0


async def test_a_bridge_going_down_reaches_the_bus(hass: HomeAssistant):
    """The down half, with the count of what it took with it."""
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(down) == 1, down
    assert down[0]["kind"] == "bridge"
    assert down[0]["name"] == "z2m"
    assert down[0]["since"]
    assert isinstance(down[0]["devices"], int)


async def test_a_bridge_coming_back_reaches_the_bus(hass: HomeAssistant):
    """The restored half, carrying how long it was gone."""
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    down_at = dt_util.utcnow().timestamp() - 600.0
    coord.data[DATA_BRIDGE_SEEN] = {
        "z2m": {BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: down_at}
    }
    coord._bridge_seen.clear()
    coord._bridge_down_at.clear()
    coord._restore_bridge_state()
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(back) == 1, back
    assert back[0]["kind"] == "bridge"
    assert back[0]["name"] == "z2m"
    assert back[0]["for_seconds"] > 500.0


async def test_a_fresh_install_announces_no_recovery(
    hass: HomeAssistant,
):
    """Nothing stored is a start, not a recovery (ruling #222).

    The events sit on the transition rather than on the state, so a
    restart that comes up with a bridge already running must not
    announce a recovery that never happened.
    """
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    down = _heard(hass, EVENT_UPSTREAM_DOWN)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    coord.data[DATA_BRIDGE_SEEN] = {}
    coord._bridge_seen.clear()
    coord._restore_bridge_state()
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert down == []
    assert back == []


async def test_a_bridge_still_down_across_a_restart_is_announced(
    hass: HomeAssistant,
):
    """An outage that survived a restart is still news (ruling #291).

    Nothing is said during the grace, because every integration is
    still coming up and none of it is news. But an upstream still
    down when the grace ends owes the bus an announcement, or its
    eventual recovery arrives with no failure before it and an
    automation pairing the two never closes.
    """
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    down = _heard(hass, EVENT_UPSTREAM_DOWN)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    down_at = dt_util.utcnow().timestamp() - 900.0
    coord.data[DATA_BRIDGE_SEEN] = {
        "z2m": {BRIDGE_SEEN_STATE: BRIDGE_DOWN, BRIDGE_SEEN_SINCE: down_at}
    }
    coord._bridge_seen.clear()
    coord._bridge_down_at.clear()
    coord._restore_bridge_state()
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(down) == 1, down
    assert down[0]["name"] == "z2m"
    # Carrying when it really began, not when the grace ended.
    assert down[0]["since"] < dt_util.now().isoformat()
    assert back == []

    # Said once, not on every sample after.
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert len(down) == 1


async def test_the_count_is_membership_not_casualties(
    hass: HomeAssistant,
):
    """How many devices sit behind it, not how many have fallen yet.

    At the moment an upstream fails no device has been judged silent,
    because judging one takes minutes. A count of casualties would
    therefore always be zero on the down event and something else on
    the restored one, which is two meanings for one field.
    """
    source = MockConfigEntry(domain="mqtt", title="Zigbee")
    source.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0",
        device_id=bridge.id, config_entry=source,
    )
    for index in range(5):
        uid = f"zigbee2mqtt_0x{index:016x}"
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", uid)},
            name=f"Sensor {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", "mqtt", uid,
            device_id=device.id, config_entry=source,
        )

    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(down) == 1
    # Nothing has been judged silent, and the count is still real.
    assert down[0]["devices"] >= 5, down[0]


async def test_an_outage_inside_the_grace_is_held_not_dropped(
    hass: HomeAssistant,
):
    """Silent during the grace, announced the moment it ends.

    The grace exists so every other integration can finish starting
    without its noise being read as news (ruling #291). An upstream
    that fails inside it and is still down afterwards is news, and
    the announcement carries the moment it really failed.
    """
    coord = await setup_coordinator(hass)
    down = _heard(hass, EVENT_UPSTREAM_DOWN)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert down == [], "the grace must be silent"
    failed_at = coord._bridge_down_at["z2m"]

    _past_grace(coord)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(down) == 1, down
    said = dt_util.parse_datetime(down[0]["since"])
    assert abs(said.timestamp() - failed_at) < 2.0

    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert len(back) == 1, back


async def test_an_outage_that_came_and_went_inside_the_grace_is_silent(
    hass: HomeAssistant,
):
    """A restart artifact, not an event a person needs."""
    coord = await setup_coordinator(hass)
    down = _heard(hass, EVENT_UPSTREAM_DOWN)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_DOWN)
    coord._sample_bridges()
    coord._bridge_readers["z2m"] = _stub_reader(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    _past_grace(coord)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert down == []
    assert back == []


# The integration outage (ruling #382). The third thing that can
# carry a house's devices, after the broker and a bridge, and the
# only one with nothing watching it until now.


def _plant(hass, count, domain, prefix):
    """Register devices under one integration, and return its entry.

    The domains are stand-ins rather than real ones. Home Assistant
    tries to load and unload a real domain around the test, which
    leaves the loop holding work at teardown. `controller_hub` stands
    for Z-Wave and `server_hub` for Matter: one entry, many devices,
    and a reload on a dropped connection.
    """
    source = MockConfigEntry(domain=domain, title=f"{domain} hub")
    source.add_to_hass(hass)
    made = []
    for index in range(count):
        uid = f"{prefix}{index}"
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(domain, uid)},
            name=f"{prefix.upper()} {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", domain, uid,
            device_id=device.id, config_entry=source,
        )
        made.append(device)
    return source, made


async def test_an_integration_that_falls_over_is_the_upstream(
    hass: HomeAssistant,
):
    """Past the dwell, the devices behind it are reported as it."""
    source, made = _plant(hass, 4, "controller_hub", "zw")
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    now = dt_util.utcnow().timestamp()
    # Seen up first. Nothing that was never up can go down, so a
    # real system always observes loaded before an outage.
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    # First sighting proves nothing.
    coord._sample_integrations(now)
    assert down == []
    assert coord.upstream_down_since(made[0].id) is None

    # Inside the dwell, still nothing.
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS - 1)
    assert down == []

    # Past it, the integration is the upstream.
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    await hass.async_block_till_done()
    assert len(down) == 1, down
    assert down[0]["kind"] == "integration"
    assert down[0]["name"] == "controller_hub"
    assert down[0]["devices"] == 4

    for device in made:
        found = coord.upstream_down_since(device.id)
        assert found is not None
        assert found[0] == "controller_hub"


async def test_a_reload_is_not_an_outage(hass: HomeAssistant):
    """An entry dropped for nine seconds says nothing.

    This is the whole reason for the dwell. Every upgrade drops every
    entry it touches, and without it an upgrade would announce an
    outage per integration.
    """
    source, _made = _plant(hass, 3, "server_hub", "mt")
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.NOT_LOADED)
    coord._sample_integrations(now)
    source.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    coord._sample_integrations(now + 5)
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 9)
    await hass.async_block_till_done()

    assert down == []


async def test_an_integration_coming_back_pairs(hass: HomeAssistant):
    """The restored half, and the devices are theirs again."""
    source, made = _plant(hass, 5, "controller_hub", "zw")
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)
    back = _heard(hass, EVENT_UPSTREAM_RESTORED)

    now = dt_util.utcnow().timestamp()
    # Seen up first. Nothing that was never up can go down, so a
    # real system always observes loaded before an outage.
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    await hass.async_block_till_done()
    assert len(down) == 1

    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 600.0)
    await hass.async_block_till_done()

    assert len(back) == 1, back
    assert back[0]["kind"] == "integration"
    assert back[0]["name"] == "controller_hub"
    assert back[0]["for_seconds"] > 500.0
    assert coord.upstream_down_since(made[0].id) is None


async def test_an_integration_with_no_watched_devices_is_ignored(
    hass: HomeAssistant,
):
    """Nobody is relying on it, so it has no story to tell."""
    source = MockConfigEntry(domain="grok_conversation", title="Grok")
    source.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.SETUP_ERROR)
    coord._sample_integrations(now)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    await hass.async_block_till_done()

    assert down == []


async def test_a_stack_with_a_reader_answers_for_itself(
    hass: HomeAssistant,
):
    """A Zigbee device is never blamed on its integration.

    ZHA and Zigbee2MQTT report their own liveness, so a device on
    either is answered by the bridge and this must not speak for it.
    """
    source = MockConfigEntry(domain="mqtt", title="Zigbee")
    source.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0",
        device_id=bridge.id, config_entry=source,
    )
    for index in range(4):
        uid = f"zigbee2mqtt_0x{index:016x}"
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", uid)},
            name=f"Sensor {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", "mqtt", uid,
            device_id=device.id, config_entry=source,
        )

    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    now = dt_util.utcnow().timestamp()
    # Seen up first. Nothing that was never up can go down, so a
    # real system always observes loaded before an outage.
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    await hass.async_block_till_done()

    kinds = [payload["kind"] for payload in down]
    assert "integration" not in kinds, down


async def test_the_broker_still_outranks_an_integration(
    hass: HomeAssistant,
):
    """Order is broker, then bridge, then integration (#264)."""
    source, made = _plant(hass, 3, "controller_hub", "zw")
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()

    now = dt_util.utcnow().timestamp()
    # Seen up first. Nothing that was never up can go down, so a
    # real system always observes loaded before an outage.
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now - 1)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    assert coord.upstream_down_since(made[0].id)[0] == "controller_hub"

    coord._broker_down_at = now - 30.0
    assert coord.upstream_down_since(made[0].id)[0] != "controller_hub"


async def test_an_entry_never_seen_loaded_is_not_an_outage(
    hass: HomeAssistant,
):
    """Nothing that was never up can have gone down.

    Found by the suite: the rung claimed every device whose entry had
    not been observed loaded, which suppressed a real freeze because
    the integration behind it was read as down. An entry that has
    never been seen loaded is either still starting or was broken
    before the house came up, and neither is an outage this can date.
    """
    source, made = _plant(hass, 3, "controller_hub", "zw")
    coord = await setup_coordinator(hass)
    _past_grace(coord)
    coord._rebuild_registry_view()
    down = _heard(hass, EVENT_UPSTREAM_DOWN)

    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.SETUP_ERROR)
    coord._sample_integrations(now)
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    coord._sample_integrations(now + 3600.0)
    await hass.async_block_till_done()

    assert down == []
    # And the devices are still their own story, which is what makes
    # a freeze behind such an entry reach the list.
    for device in made:
        assert coord.upstream_down_since(device.id) is None
