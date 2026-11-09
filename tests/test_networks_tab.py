# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_networks_tab.py, Version: 0.28.6 (2026-11-08)

"""The Networks tab and each network's page (rule DASH-17).

A network appears only where the house has it. Each device sits on one
network, and a device that reaches Home Assistant through the broker is
also counted under the broker. A network's page looks back 30 days.
Nothing here changes another integration's settings.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_WIFI_DOWN,
    SYS_WIFI_UP,
    TODO_DEVICE_ID,
    TODO_KIND_FROZEN,
    TODO_KIND_LOW_BATTERY,
    TODO_KINDS,
    TODO_STATUS,
)
from custom_components.device_sentinel.networks import problem_groups
from custom_components.device_sentinel.stack_z2m import Z2MBridgeReader
from tests.helpers import setup_coordinator

NOW = "2026-09-24T20:00:00+00:00"


@pytest.fixture
def _mid_afternoon(freezer):
    freezer.move_to(NOW)


class _Reader:
    def __init__(self, state, **extra):
        self.state = state
        for name, value in extra.items():
            setattr(self, name, value)

    def async_stop(self):
        return None


def _device(hass, domain: str, key: str, name: str, battery_off: bool = False):
    entry = MockConfigEntry(domain=domain, title=name)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, key)}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, key, device_id=device.id, config_entry=entry
    )
    if battery_off:
        er.async_get(hass).async_get_or_create(
            "sensor", domain, f"{key}_battery", device_id=device.id, config_entry=entry,
            original_device_class="battery", unit_of_measurement="%",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    return device


def _problems(monkeypatch, coordinator, items):
    monkeypatch.setattr(type(coordinator), "todo_items", property(lambda self: items))


def _ago(days: float) -> float:
    return dt_util.utcnow().timestamp() - days * 86400.0


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def test_problem_groups_fold_kinds_into_the_tiles():
    assert problem_groups({TODO_KIND_LOW_BATTERY: 1, TODO_KIND_FROZEN: 2, "falling_battery": 3}) == [
        "frozen", "battery",
    ]
    assert problem_groups(None) == []
    assert problem_groups({"something_new": 1}) == []


@pytest.mark.usefixtures("_mid_afternoon")
async def test_each_device_sits_on_its_network(hass: HomeAssistant):
    zha = _device(hass, "zha", "z1", "Hall Motion")
    relay = _device(hass, "tasmota", "t1", "Stove Vent Relays")
    plug = _device(hass, "shelly", "s1", "Desk Plug")
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator._wifi_ties = {relay.id: "device_tracker.relay", plug.id: "device_tracker.plug"}
    assert coordinator.device_networks(zha.id) == ["zha"]
    # Tasmota reaches Home Assistant through the broker and over Wi-Fi.
    assert coordinator.device_networks(relay.id) == ["wifi", "mqtt"]
    assert coordinator.device_networks(plug.id) == ["wifi"]


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_radio_device_is_not_counted_under_wifi(hass: HomeAssistant):
    """Guard: a Zigbee device tied to a tracker by mistake stays Zigbee's
    (rule UP-15)."""
    zha = _device(hass, "zha", "z2", "Porch Light")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator._wifi_ties = {zha.id: "device_tracker.porch"}
    assert coordinator.device_networks(zha.id) == ["zha"]


@pytest.mark.usefixtures("_mid_afternoon")
async def test_the_tab_lists_only_what_the_house_has(hass: HomeAssistant, monkeypatch):
    zha = _device(hass, "zha", "z3", "Bath Motion")
    _device(hass, "zha", "z4", "Bath Door")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    _problems(monkeypatch, coordinator, [
        {TODO_DEVICE_ID: zha.id, TODO_KINDS: {TODO_KIND_FROZEN: _ago(1)}, TODO_STATUS: "needs_action"},
    ])
    rows = coordinator.dashboard_networks()
    assert [row["key"] for row in rows] == ["zha"]
    row = rows[0]
    assert row["name"] == "ZHA"
    assert row["watched"] == 2
    assert row["with_problem"] == 1
    assert row["counts"]["frozen"] == 1
    assert row["last_outage"] is None


@pytest.mark.usefixtures("_mid_afternoon")
async def test_status_reads_the_bridge_and_the_broker(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {"z2m": _Reader("binding"), "zha": _Reader("down")}
    coordinator._broker_reader = _Reader("running")
    from homeassistant.config_entries import ConfigEntryState

    mqtt_entry = MockConfigEntry(domain="mqtt")
    mqtt_entry.add_to_hass(hass)
    mqtt_entry.mock_state(hass, ConfigEntryState.LOADED)
    rows = {row["key"]: row for row in coordinator.dashboard_networks()}
    assert list(rows) == ["z2m", "zha", "mqtt"]
    assert rows["z2m"]["status"]["words"] == "Pairing open"
    assert rows["zha"]["status"]["state"] == "down"
    assert rows["mqtt"]["status"]["words"] == "Running"
    assert rows["mqtt"]["name"] == "MQTT Broker"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_an_outage_20_days_ago_is_on_the_network_page_only(hass: HomeAssistant):
    """The network page looks back 30 days; the integration page keeps
    its 14 (rule UP-11)."""
    _device(hass, "zha", "z5", "Office Motion")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    went = _ago(20)
    coordinator._record_system_event(SYS_BRIDGE_DOWN, scope="zha", when=went)
    coordinator._record_system_event(SYS_BRIDGE_UP, scope="zha", when=went + 180, duration=180, devices=12)
    coordinator._record_system_event(SYS_BRIDGE_DOWN, scope="zha", when=_ago(40))
    coordinator._record_system_event(SYS_BRIDGE_UP, scope="zha", when=_ago(40) + 60, duration=60)
    page = coordinator.dashboard_network("zha")
    assert len(page["outages"]) == 1
    outage = page["outages"][0]
    assert outage["duration"] == 180
    assert outage["devices"] == 12
    assert outage["open"] is False
    assert coordinator.integration_outages().get("zha", []) == []
    assert coordinator.dashboard_networks()[0]["last_outage"]["devices"] == 12


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_wifi_outage_is_on_the_wifi_page(hass: HomeAssistant):
    plug = _device(hass, "shelly", "s2", "Desk Plug")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator._wifi_ties = {plug.id: "device_tracker.plug"}
    coordinator._record_system_event(SYS_WIFI_DOWN, scope="wifi", when=_ago(2), devices=34)
    coordinator._record_system_event(SYS_WIFI_UP, scope="wifi", when=_ago(2) + 60, duration=60)
    page = coordinator.dashboard_network("wifi")
    assert page["name"] == "Wi-Fi"
    assert [o["what"] for o in page["outages"]] == ["Wi-Fi"]
    assert page["outages"][0]["duration"] == 60
    # Wi-Fi belongs to no integration.
    assert "wifi" not in coordinator.integration_outages()


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_wifi_down_left_by_a_restart_is_not_still_down(hass: HomeAssistant):
    """Guard: a down with no return, while no outage stands, is not shown
    as standing."""
    plug = _device(hass, "shelly", "s3", "Desk Plug")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator._wifi_ties = {plug.id: "device_tracker.plug"}
    coordinator._record_system_event(SYS_WIFI_DOWN, scope="wifi", when=_ago(3), devices=34)
    assert coordinator.dashboard_network("wifi")["outages"] == []


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_network_the_house_lacks_is_not_found(hass: HomeAssistant, hass_ws_client):
    _device(hass, "zha", "z6", "Kitchen Motion")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/network", key="matter")
    assert not reply["success"]
    assert reply["error"]["code"] == "not_found"
    reply = await _call(client, type="device_sentinel/network", key="zha")
    assert reply["success"], reply
    assert reply["result"]["name"] == "ZHA"
    reply = await _call(client, type="device_sentinel/networks")
    assert [row["key"] for row in reply["result"]["rows"]] == ["zha"]


async def test_the_commands_are_for_administrators(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in ({"type": "device_sentinel/networks"}, {"type": "device_sentinel/network", "key": "zha"}):
        reply = await _call(client, **message)
        assert not reply["success"]
        assert reply["error"]["code"] == "unauthorized"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_switched_off_sensor_is_listed_to_turn_on(hass: HomeAssistant):
    """The page counts the sensors and lists each device with one off; the
    device page's own action turns it on, one device at a time (rule
    REC-05)."""
    lamp = _device(hass, "zha", "z7", "Lamp", battery_off=True)
    _device(hass, "zha", "z8", "Shade")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    sensors = {row["kind"]: row for row in coordinator.dashboard_network("zha")["sensors"]}
    battery = sensors["battery"]
    assert battery["have"] == 1
    assert battery["on"] == 0
    assert [row["device_id"] for row in battery["off"]] == [lamp.id]
    assert battery["off"][0]["by"] == "user"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_pairing_windows_in_the_last_30_days(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {"z2m": _Reader("running")}
    opened = _ago(5)
    coordinator._record_system_event(SYS_PAIRING_OPEN, scope="z2m", when=opened)
    coordinator._record_system_event(SYS_PAIRING_CLOSED, scope="z2m", when=opened + 240, duration=240)
    coordinator._record_system_event(SYS_PAIRING_OPEN, scope="z2m", when=_ago(45))
    coordinator._record_system_event(SYS_PAIRING_CLOSED, scope="z2m", when=_ago(45) + 60, duration=60)
    pairing = coordinator.dashboard_network("z2m")["pairing"]
    assert pairing["windows"] == 1
    assert pairing["last"]["duration"] == 240


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_stack_with_no_pairing_window_gives_devices_added_alone(hass: HomeAssistant):
    """ZHA, Z-Wave and Matter say nothing of a pairing window, so none is
    claimed: "None in 30 days" would be false after a person paired."""
    _device(hass, "zha", "z9", "Garage Door")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    pairing = coordinator.dashboard_network("zha")["pairing"]
    assert pairing["windows"] is None
    assert pairing["last"] is None
    # The fixture's device was added to Home Assistant just now.
    assert pairing["new_devices"] == 1


@pytest.mark.usefixtures("_mid_afternoon")
async def test_z_wave_down_is_down_whatever_the_controller_last_said(hass: HomeAssistant):
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.device_sentinel.const import DATA_DEVICES, DEV_CONTROLLER_STATUS

    controller = _device(hass, "zwave_js", "3967834211-1", "Stick")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator.data[DATA_DEVICES][controller.id][DEV_CONTROLLER_STATUS] = [["ready", _ago(20)]]
    entry = hass.config_entries.async_entries("zwave_js")[0]
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert coordinator.network_status("zwave_js")["words"] == "Controller Ready"
    coordinator.data[DATA_DEVICES][controller.id][DEV_CONTROLLER_STATUS] = [["jammed", _ago(1)]]
    assert coordinator.network_status("zwave_js")["state"] == "down"
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    status = coordinator.network_status("zwave_js")
    assert status == {"state": "down", "words": "Integration not loaded", "since": None}


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_young_device_with_a_bad_day_counts(hass: HomeAssistant, monkeypatch):
    """The Signal Trends tab waits 21 days; a network's week does not."""
    from custom_components.device_sentinel.const import DATA_DEVICES, DEV_SIGNAL_DAILY_P5

    young = _device(hass, "zha", "z11", "New Plug")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator.data[DATA_DEVICES][young.id][DEV_SIGNAL_DAILY_P5] = [-70.0] * 5
    monkeypatch.setattr(type(coordinator), "signal_day_judgment",
                        lambda self, record, index: {"bad": index == 4, "normal": -70.0, "line": -80.0})
    assert coordinator.dashboard_network("zha")["signal"]["weak_week"] == 1


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_hubs_page_looks_back_14_days(hass: HomeAssistant):
    """A hub's outages come from incidents, kept 14 days, so its page says
    14, not 30."""
    coordinator = await setup_coordinator(hass)
    assert coordinator.network_window("hub:abc") == 14
    assert coordinator.network_window("zha") == 30


@pytest.mark.usefixtures("_mid_afternoon")
async def test_the_devices_tab_rows_carry_networks_and_groups(hass: HomeAssistant, monkeypatch):
    zha = _device(hass, "zha", "z10", "Stair Motion")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    _problems(monkeypatch, coordinator, [
        {
            TODO_DEVICE_ID: zha.id, TODO_KINDS: {TODO_KIND_LOW_BATTERY: _ago(1)},
            TODO_STATUS: "needs_action", "summary": "Stair Motion: battery low", "sort_name": "Stair Motion",
        },
    ])
    row = next(r for r in coordinator.dashboard_devices() if r["device_id"] == zha.id)
    assert row["networks"] == ["zha"]
    assert row["groups"] == ["battery"]


def _msg(payload):
    return SimpleNamespace(payload=payload)


async def test_zigbee2mqtt_hardware_is_read_from_bridge_info(hass: HomeAssistant):
    reader = Z2MBridgeReader(hass)
    reader._on_info(_msg(json.dumps({
        "version": "2.6.3",
        "coordinator": {"type": "EmberZNet", "meta": {"revision": "7.4.4 [GA]"}},
        "network": {"channel": 15, "pan_id": 6754},
        "config": {"serial": {"port": "tcp://192.168.1.50:6638"}},
    })))
    assert reader.hardware == {
        "type": "EmberZNet",
        "firmware": "7.4.4 [GA]",
        "channel": 15,
        "version": "2.6.3",
        "port": "tcp://192.168.1.50:6638",
    }


async def test_a_bad_bridge_info_keeps_what_was_read(hass: HomeAssistant):
    """Guard: a field of the wrong shape changes nothing."""
    reader = Z2MBridgeReader(hass)
    reader._on_info(_msg(json.dumps({"version": "2.6.3", "network": {"channel": 15}})))
    reader._on_info(_msg(json.dumps({
        "version": 7, "coordinator": "x", "network": {"channel": 99},
    })))
    assert reader.hardware["version"] == "2.6.3"
    assert reader.hardware["channel"] == 15
    assert reader.hardware["type"] is None


@pytest.mark.usefixtures("_mid_afternoon")
async def test_zigbee2mqtts_page_names_availability_off(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {
        "z2m": _Reader("running", availability_enabled=False, hardware={"type": "EmberZNet", "port": "/dev/ttyUSB0"}),
    }
    page = coordinator.dashboard_network("z2m")
    assert page["notices"][0]["title"] == "Zigbee2MQTT's Availability is off."
    assert "never changes" in page["notices"][0]["words"]
    hardware = {row["label"]: row["value"] for row in page["hardware"]}
    assert hardware["Type"] == "EmberZNet"
    assert hardware["Connected by"] == "USB or serial"


async def test_a_watched_hub_is_a_network_and_its_devices_are_on_it(hass: HomeAssistant, freezer):
    from tests.test_lutron_hub import _house

    h = await _house(hass, freezer)
    key = "hub:" + h.g_hub.id
    assert key in h.coord.network_keys()
    assert h.coord.device_networks(h.flood.id) == [key]
    # The integration's title, then the hub's name.
    assert h.coord.network_name(key).endswith(": Garage Lutron Caseta")


async def test_a_hub_device_sentinel_does_not_watch_is_no_network(hass: HomeAssistant, freezer):
    """A hub with no entities is set aside: with no record it has no state,
    outages or page, so its devices are not filed under it."""
    from tests.test_lutron_hub import _house

    h = await _house(hass, freezer, hub_entity=False)
    assert h.b_hub.id not in h.coord._watched
    assert "hub:" + h.b_hub.id not in h.coord.network_keys()
    assert not any(key.startswith("hub:" + h.b_hub.id) for key in h.coord.device_networks(h.kitchen.id))


@pytest.mark.usefixtures("_mid_afternoon")
async def test_an_excluded_stack_with_no_devices_is_not_listed(hass: HomeAssistant):
    from custom_components.device_sentinel.const import CONF_EXCLUDED_INTEGRATIONS

    coordinator = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["zha"]})
    coordinator._bridge_readers = {"zha": _Reader("running")}
    assert "zha" not in coordinator.network_keys()


@pytest.mark.usefixtures("_mid_afternoon")
async def test_with_two_controllers_the_one_not_ready_is_told(hass: HomeAssistant):
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.device_sentinel.const import DATA_DEVICES, DEV_CONTROLLER_STATUS

    first = _device(hass, "zwave_js", "1111-1", "Stick One")
    second = _device(hass, "zwave_js", "2222-1", "Stick Two")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    for entry in hass.config_entries.async_entries("zwave_js"):
        entry.mock_state(hass, ConfigEntryState.LOADED)
    coordinator.data[DATA_DEVICES][first.id][DEV_CONTROLLER_STATUS] = [["jammed", _ago(1)]]
    coordinator.data[DATA_DEVICES][second.id][DEV_CONTROLLER_STATUS] = [["ready", _ago(0.5)]]
    status = coordinator.network_status("zwave_js")
    assert status["words"] == "Controller Jammed"
    assert status["state"] == "down"
    rows = {row["label"]: row["value"] for row in coordinator.dashboard_network("zwave_js")["hardware"]}
    assert rows["Controller status"] == "Jammed"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_the_broker_reads_integration_not_loaded(hass: HomeAssistant):
    from homeassistant.config_entries import ConfigEntryState

    coordinator = await setup_coordinator(hass)
    coordinator._broker_reader = _Reader("unknown")
    entry = MockConfigEntry(domain="mqtt")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    assert coordinator.network_status("mqtt")["words"] == "Integration not loaded"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_a_window_whose_close_was_missed_is_not_still_open(hass: HomeAssistant):
    """A close lost across a restart leaves an opening with no end: it is
    open only while Zigbee2MQTT says pairing is open."""
    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {"z2m": _Reader("running")}
    coordinator._record_system_event(SYS_PAIRING_OPEN, scope="z2m", when=_ago(2))
    last = coordinator.dashboard_network("z2m")["pairing"]["last"]
    assert last["open"] is False
    assert last["duration"] is None
    coordinator._bridge_readers = {"z2m": _Reader("binding")}
    assert coordinator.dashboard_network("z2m")["pairing"]["last"]["open"] is True


@pytest.mark.usefixtures("_mid_afternoon")
async def test_an_ignored_zha_entry_does_not_hide_the_real_one(hass: HomeAssistant):
    from homeassistant.config_entries import SOURCE_IGNORE

    MockConfigEntry(domain="zha", source=SOURCE_IGNORE, data={}).add_to_hass(hass)
    MockConfigEntry(domain="zha", data={"radio_type": "ezsp", "device": {"path": "/dev/ttyUSB0"}}).add_to_hass(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {"zha": _Reader("running")}
    rows = {row["label"]: row["value"] for row in coordinator.dashboard_network("zha")["hardware"]}
    assert rows["Radio type"] == "EZSP"
    assert rows["Connected by"] == "USB or serial"


@pytest.mark.usefixtures("_mid_afternoon")
async def test_an_access_point_is_named_from_its_registry_device(hass: HomeAssistant):
    entry = MockConfigEntry(domain="unifi", title="UniFi")
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, "78:45:58:aa:bb:cc")},
        name="Upstairs AP",
    )
    coordinator = await setup_coordinator(hass)
    assert coordinator.ap_name("78:45:58:AA:BB:CC") == "Upstairs AP"
    assert coordinator.ap_name("11:22:33:44:55:66") == "11:22:33:44:55:66"
    assert coordinator.ap_name(None) is None


@pytest.mark.usefixtures("_mid_afternoon")
async def test_zigbee2mqtt_reads_integration_not_loaded_with_mqtt_down(hass: HomeAssistant):
    """The bridge reader keeps its last reading while MQTT is not loaded."""
    from homeassistant.config_entries import ConfigEntryState

    coordinator = await setup_coordinator(hass)
    coordinator._bridge_readers = {"z2m": _Reader("running")}
    entry = MockConfigEntry(domain="mqtt")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert coordinator.network_status("z2m")["words"] == "Running"
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    assert coordinator.network_status("z2m")["words"] == "Integration not loaded"


async def _hub_down_page(hass, freezer, key):
    from tests.test_lutron_hub import _house

    # A mute set on the hub passes to the devices it controls.
    h = await _house(hass, freezer, options=lambda b, g: {key: [b.id]})
    hub = h.b_hub.id
    h.coord._hub_lost[hub] = dt_util.utcnow().timestamp() - 600
    h.coord._hub_confirmed.add(hub)
    assert h.coord.mute_text(h.kitchen.id)
    return h.coord.dashboard_device(h.kitchen.id)


async def test_a_battery_muted_device_whose_hub_is_down_reads_it_live(hass: HomeAssistant, freezer):
    """"Its hub is down" is the hub's row on the Problem List: a battery
    mute leaves it live (rule SIG-17)."""
    from custom_components.device_sentinel.const import CONF_BATTERY_MUTED_DEVICES

    page = await _hub_down_page(hass, freezer, CONF_BATTERY_MUTED_DEVICES)
    assert page["status"]["muted_shown"] is False


async def test_an_unavailable_muted_device_whose_hub_is_down_reads_it_muted(hass: HomeAssistant, freezer):
    from custom_components.device_sentinel.const import CONF_UNAVAILABLE_MUTED_DEVICES

    page = await _hub_down_page(hass, freezer, CONF_UNAVAILABLE_MUTED_DEVICES)
    assert page["status"]["muted_shown"] is True


async def test_short_drop_outs_behind_a_down_hub_are_not_greyed_by_the_unavailable_mute(hass: HomeAssistant, freezer):
    """The page reads short drop-outs, not "Its hub is down", and the list
    keeps them: only the signal mute greys them (rule SIG-17)."""
    from custom_components.device_sentinel.const import (
        CONF_UNAVAILABLE_MUTED_DEVICES,
        DATA_DEVICES,
        DEV_FLAP_SINCE,
    )
    from tests.test_lutron_hub import _house

    h = await _house(hass, freezer, options=lambda b, g: {CONF_UNAVAILABLE_MUTED_DEVICES: [b.id]})
    hub = h.b_hub.id
    h.coord._hub_lost[hub] = dt_util.utcnow().timestamp() - 600
    h.coord._hub_confirmed.add(hub)
    h.coord.data[DATA_DEVICES][h.kitchen.id][DEV_FLAP_SINCE] = dt_util.utcnow().timestamp() - 3600
    page = h.coord.dashboard_device(h.kitchen.id)
    assert page["status"]["category"] == "short_drop_outs"
    assert page["status"]["muted_shown"] is False
