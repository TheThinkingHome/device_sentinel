# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_network_page_extras.py, Version: 0.28.11 (2026-11-10)

"""More on a network's page (rules DASH-17, DASH-18).

Its devices and makeup, how long it has run, the devices that keep
failing on it, Wi-Fi address changes, firmware, and a Z-Wave
controller's radio noise. All read from what Device Sentinel keeps and
Home Assistant's registries, states and statistics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_ADDRESS_CHANGES,
    DATA_DEVICES,
    DATA_SHORT_DROPS,
    DEV_FIRMWARE_HISTORY,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
)
from tests.helpers import setup_coordinator

NOW = "2026-09-24T20:00:00+00:00"


@pytest.fixture
def _afternoon(freezer):
    freezer.move_to(NOW)


def _ago(days: float) -> float:
    return dt_util.utcnow().timestamp() - days * 86400.0


def _device(hass, domain, key, name, maker=None, model=None, firmware=None, entry=None):
    if entry is None:
        entry = MockConfigEntry(domain=domain, title=name)
        entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, key)}, name=name,
        manufacturer=maker, model=model, sw_version=firmware,
    )
    er.async_get(hass).async_get_or_create("sensor", domain, key, device_id=device.id, config_entry=entry)
    return device, entry


def _update(hass, domain, key, device, entry, disabled=False):
    return er.async_get(hass).async_get_or_create(
        "update", domain, f"{key}_fw", device_id=device.id, config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION if disabled else None,
    )


@pytest.mark.usefixtures("_afternoon")
async def test_its_devices_by_name_with_maker_model_firmware(hass: HomeAssistant):
    shade, entry = _device(hass, "zha", "z1", "Shade", "IKEA of Sweden", "FYRTUR", "2.3.088")
    lamp, _ = _device(hass, "zha", "z2", "Lamp", "Philips", "LCT015", "1.50.2", entry)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    page = coordinator.dashboard_network("zha")
    assert [d["name"] for d in page["devices"]] == ["Lamp", "Shade"]
    first = page["devices"][0]
    assert (first["maker"], first["model"], first["firmware"]) == ("Philips", "LCT015", "1.50.2")
    assert first["power"] == "Not known"
    makeup = page["makeup"]
    assert {m["name"] for m in makeup["makers"]} == {"IKEA of Sweden", "Philips"}
    assert makeup["power"] == [{"name": "Not known", "devices": 2}]
    assert page["own_page"] is True


@pytest.mark.usefixtures("_afternoon")
async def test_a_zigbee2mqtt_device_reads_its_part_in_the_mesh(hass: HomeAssistant):
    entry = MockConfigEntry(domain="mqtt", title="MQTT")
    entry.add_to_hass(hass)
    plug = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x00aa")}, name="Plug",
    )
    er.async_get(hass).async_get_or_create("sensor", "mqtt", "0x00aa_lqi", device_id=plug.id, config_entry=entry)
    coordinator = await setup_coordinator(hass)
    roles = {"0x00aa": "Router"}
    reader = SimpleNamespace(
        state="running", zigbee_role=lambda ieee: roles.get(ieee), async_stop=lambda: None,
        availability_enabled=None, hardware={}, pairing_open=False,
    )
    coordinator._bridge_readers = {"z2m": reader}
    from custom_components.device_sentinel.stack_z2m import device_key
    assert device_key(plug) == "0x00aa", plug.identifiers
    assert coordinator.bridge_reader("z2m") is reader
    assert coordinator._mesh_role("z2m", plug) == "Router"
    roles["0x00aa"] = "EndDevice"
    assert coordinator._mesh_role("z2m", plug) == "End device"
    roles["0x00aa"] = 7
    assert coordinator._mesh_role("z2m", plug) is None
    assert coordinator._network_makeup([{"role": "Router", "power": "Mains", "maker": "Sonoff"},
                                         {"role": "Router", "power": "Mains", "maker": " "},
                                         {"role": None, "power": "Battery", "maker": None}])["roles"] == [
        {"name": "Router", "devices": 2}]


@pytest.mark.usefixtures("_afternoon")
async def test_a_zha_role_that_cannot_be_read_is_none(hass: HomeAssistant):
    device, _ = _device(hass, "zha", "z9", "Lamp")
    coordinator = await setup_coordinator(hass)
    # ZHA is not running, so its internals are not there.
    assert coordinator._mesh_role("zha", device) is None
    assert coordinator._mesh_role("matter", device) is None


@pytest.mark.usefixtures("_afternoon")
async def test_running_since_its_last_outage_ended(hass: HomeAssistant):
    _device(hass, "zha", "z3", "Lamp")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    went = _ago(2)
    coordinator._record_system_event(SYS_BRIDGE_DOWN, scope="zha", when=went)
    coordinator._record_system_event(SYS_BRIDGE_UP, scope="zha", when=went + 300, duration=300)
    up = coordinator.dashboard_network("zha")["up"]
    assert dt_util.parse_datetime(up["back_since"]).timestamp() == went + 300
    assert up["outages"] == 1 and up["expected"] == 0


@pytest.mark.usefixtures("_afternoon")
async def test_the_devices_with_the_most_short_drop_outs(hass: HomeAssistant):
    a, entry = _device(hass, "zha", "z4", "Door")
    b, _ = _device(hass, "zha", "z5", "Window", entry=entry)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    rows = coordinator.data.setdefault(DATA_SHORT_DROPS, [])
    for device, n in ((a, 2), (b, 5)):
        for i in range(n):
            rows.append({"device_id": device.id, "went": _ago(1) + i * 600, "length": 240.0, "window": 900.0})
    rows.append({"device_id": a.id, "went": _ago(9), "length": 240.0, "window": 900.0})
    assert coordinator.short_drops_by_device([a.id, b.id]) == {a.id: 2, b.id: 5}
    offenders = coordinator.dashboard_network("zha")["offenders"]
    assert [(r["name"], r["drops"]) for r in offenders["drops"]] == [("Window", 5), ("Door", 2)]
    assert isinstance(offenders["repeat"], list)


@pytest.mark.usefixtures("_afternoon")
async def test_wifi_address_changes_count_changes_not_first_readings(hass: HomeAssistant):
    plug, _ = _device(hass, "shelly", "s1", "Desk Plug")
    lamp, _ = _device(hass, "shelly", "s2", "Hall Lamp")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator._wifi_ties = {plug.id: "device_tracker.plug", lamp.id: "device_tracker.lamp"}
    coordinator.data[DATA_ADDRESS_CHANGES] = [
        {"device_id": plug.id, "when": _ago(40), "ip": "10.0.0.5", "ap": "aa"},
        {"device_id": plug.id, "when": _ago(5), "ip": "10.0.0.9", "ap": "aa"},
        {"device_id": plug.id, "when": _ago(3), "ip": "10.0.0.9", "ap": "bb"},
        {"device_id": plug.id, "when": _ago(2), "ip": "10.0.0.7", "ap": "aa"},
        {"device_id": lamp.id, "when": _ago(1), "ip": "10.0.0.20", "ap": "aa"},
        {"device_id": lamp.id, "when": "soon", "ip": "10.0.0.21", "ap": "aa"},
        # Away, the tracker drops its address and access point; back on
        # the same ones, nothing changed.
        {"device_id": lamp.id, "when": _ago(0.5), "ip": None, "ap": None},
        {"device_id": lamp.id, "when": _ago(0.2), "ip": "10.0.0.20", "ap": "aa"},
    ]
    coordinator._forget_address_index()
    changes = coordinator.dashboard_network("wifi")["wifi_changes"]
    assert [(r["name"], r["addresses"], r["moves"]) for r in changes] == [("Desk Plug", 2, 2)]
    assert coordinator.dashboard_network("wifi")["devices"]


@pytest.mark.usefixtures("_afternoon")
async def test_firmware_updates_offered_and_update_checks_off(hass: HomeAssistant):
    lamp, entry = _device(hass, "zha", "z6", "Lamp", "Philips", "LCT015", "1.50.2")
    shade, _ = _device(hass, "zha", "z7", "Shade", "Philips", "LCT015", "1.88.1", entry)
    on = _update(hass, "zha", "z6", lamp, entry)
    _update(hass, "zha", "z7", shade, entry, disabled=True)
    hass.states.async_set(on.entity_id, "on", {"installed_version": "1.50.2", "latest_version": "1.122.2"})
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    page = coordinator.dashboard_network("zha")
    fw = page["firmware"]
    assert [(u["name"], u["installed"], u["latest"]) for u in fw["updates"]] == [("Lamp", "1.50.2", "1.122.2")]
    assert fw["mixed"] == [{"maker": "Philips", "model": "LCT015", "versions": [
        {"version": "1.50.2", "devices": 1}, {"version": "1.88.1", "devices": 1}]}]
    checks = {row["kind"]: row for row in page["sensors"]}["firmware"]
    assert checks["have"] == 2 and [d["name"] for d in checks["off"]] == ["Shade"]
    assert checks["label"] == "Firmware update checks"
    hass.states.async_set(on.entity_id, "off", {})
    assert coordinator.dashboard_network("zha")["firmware"]["updates"] == []


@pytest.mark.usefixtures("_afternoon")
async def test_the_update_check_is_turned_on_one_device_at_a_time(hass: HomeAssistant, hass_ws_client):
    shade, entry = _device(hass, "zha", "z8", "Shade")
    off = _update(hass, "zha", "z8", shade, entry, disabled=True)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_sentinel/device_turn_on", "device_id": shade.id,
                                    "kind": "firmware", "source": "network_page"})
    reply = await client.receive_json()
    assert reply["success"], reply
    assert reply["result"]["enabled"] == 1
    assert er.async_get(hass).async_get(off.entity_id).disabled_by is None


@pytest.mark.usefixtures("_afternoon")
async def test_an_update_entity_of_another_integration_is_not_its_own(hass: HomeAssistant):
    """Guard: only the owning integration's update entity counts (rule WATCH-02)."""
    shade, entry = _device(hass, "zha", "z10", "Shade")
    other = MockConfigEntry(domain="hacs", title="HACS")
    other.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("update", "hacs", "x", device_id=shade.id, config_entry=other,
                                           disabled_by=er.RegistryEntryDisabler.USER)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    assert "firmware" not in {row["kind"] for row in coordinator.dashboard_network("zha")["sensors"]}


@pytest.mark.usefixtures("_afternoon")
async def test_firmware_changes_in_the_window(hass: HomeAssistant):
    lamp, _ = _device(hass, "zha", "z11", "Lamp")
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    coordinator.data[DATA_DEVICES][lamp.id][DEV_FIRMWARE_HISTORY] = [
        ["1.0", _ago(90)], ["1.1", _ago(60)], ["1.2", _ago(3)], ["bad"], ["1.3", "soon"],
    ]
    changed = coordinator.dashboard_network("zha")["firmware"]["changed"]
    assert [(c["from"], c["to"]) for c in changed] == [("1.1", "1.2")]


def _noise(hass, entry, controller, channel, kind):
    return er.async_get(hass).async_get_or_create(
        "sensor", "zwave_js", f"3967834211.1.statistics_background_rssi.channel_{channel}.{kind}",
        device_id=controller.id, config_entry=entry,
    )


@pytest.mark.usefixtures("_afternoon")
async def test_radio_noise_per_channel_and_a_raised_channel(hass: HomeAssistant, monkeypatch):
    controller, entry = _device(hass, "zwave_js", "3967834211-1", "Controller")
    now0 = _noise(hass, entry, controller, 0, "current")
    avg0 = _noise(hass, entry, controller, 0, "average")
    now1 = _noise(hass, entry, controller, 1, "current")
    hass.states.async_set(now0.entity_id, "-90")
    hass.states.async_set(avg0.entity_id, "-101.5")
    hass.states.async_set(now1.entity_id, "unknown")
    coordinator = await setup_coordinator(hass)

    async def daily(ids):
        return {now0.entity_id: [-104.0] * 20 + [-92.0, -91.0, -90.0], now1.entity_id: [-105.0] * 3}

    monkeypatch.setattr(coordinator, "_noise_daily", daily)
    noise = await coordinator.async_network_noise()
    zero, one = noise["channels"]
    assert (zero["channel"], zero["now"], zero["average"], zero["typical"], zero["raised"]) == (0, -90.0, -101.5, -104.0, True)
    assert one["typical"] is None and one["raised"] is False and one["now"] is None
    sentences = [c["sentence"] for c in noise["cards"]]
    assert len(sentences) == 1
    assert sentences[0].startswith("Radio noise on channel 0 has stayed at least 10 dB above its usual -104 dBm for 3 days.")


@pytest.mark.usefixtures("_afternoon")
async def test_noise_that_came_down_is_not_raised(hass: HomeAssistant, monkeypatch):
    controller, entry = _device(hass, "zwave_js", "3967834211-1", "Controller")
    now0 = _noise(hass, entry, controller, 0, "current")
    hass.states.async_set(now0.entity_id, "unavailable")
    coordinator = await setup_coordinator(hass)

    async def daily(ids):
        return {now0.entity_id: [-104.0] * 20 + [-92.0, -100.0, -90.0]}

    monkeypatch.setattr(coordinator, "_noise_daily", daily)
    noise = await coordinator.async_network_noise()
    assert noise["channels"][0]["raised"] is False and noise["channels"][0]["now"] is None
    assert noise["cards"] == []


@pytest.mark.usefixtures("_afternoon")
async def test_a_channel_with_no_current_reading_is_left_out(hass: HomeAssistant, monkeypatch):
    """An 800 series stick's Long Range channel has an average sensor and
    no current one; a row of blanks for it says nothing (rule DASH-18)."""
    controller, entry = _device(hass, "zwave_js", "3967834211-1", "Controller")
    now0 = _noise(hass, entry, controller, 0, "current")
    avg3 = _noise(hass, entry, controller, 3, "average")
    hass.states.async_set(now0.entity_id, "-95")
    hass.states.async_set(avg3.entity_id, "-100")
    coordinator = await setup_coordinator(hass)

    async def daily(ids):
        assert ids == [now0.entity_id]
        return {}

    monkeypatch.setattr(coordinator, "_noise_daily", daily)
    noise = await coordinator.async_network_noise()
    assert [c["channel"] for c in noise["channels"]] == [0]


@pytest.mark.usefixtures("_afternoon")
async def test_only_average_sensors_is_no_noise(hass: HomeAssistant):
    controller, entry = _device(hass, "zwave_js", "3967834211-1", "Controller")
    _noise(hass, entry, controller, 3, "average")
    coordinator = await setup_coordinator(hass)
    assert await coordinator.async_network_noise() is None


async def test_no_noise_sensors_no_noise(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    assert await coordinator.async_network_noise() is None


async def test_noise_statistics_without_a_recorder_read_nothing(hass: HomeAssistant):
    coordinator = await setup_coordinator(hass)
    assert await coordinator._noise_daily(["sensor.x"]) == {}


@pytest.mark.usefixtures("_afternoon")
async def test_a_beta_firmware_check_is_never_turned_on(hass: HomeAssistant):
    """A first-generation Shelly has a stable and a beta update entity,
    both off; only the stable one is the device's firmware check."""
    plug, entry = _device(hass, "shelly", "s9", "Plug")
    stable = _update(hass, "shelly", "s9", plug, entry, disabled=True)
    beta = er.async_get(hass).async_get_or_create(
        "update", "shelly", "s9_fwupdate_beta", device_id=plug.id, config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    assert coordinator.page_turn_on(plug.id, "firmware") == 1
    assert er.async_get(hass).async_get(stable.entity_id).disabled_by is None
    assert er.async_get(hass).async_get(beta.entity_id).disabled_by is not None


@pytest.mark.usefixtures("_afternoon")
async def test_a_device_named_for_beta_keeps_its_firmware_check(hass: HomeAssistant):
    plug, entry = _device(hass, "shelly", "alphabeta", "Alphabeta Plug")
    off = _update(hass, "shelly", "alphabeta", plug, entry, disabled=True)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    assert coordinator.page_turn_on(plug.id, "firmware") == 1
    assert er.async_get(hass).async_get(off.entity_id).disabled_by is None


async def test_noise_statistics_end_at_the_start_of_today(hass: HomeAssistant, monkeypatch):
    import custom_components.device_sentinel.network_extras as extras

    coordinator = await setup_coordinator(hass)
    hass.config.components.add("recorder")
    seen = {}

    def fake(hass_, start, end, ids, period, units, types):
        seen["end"] = end
        return {}

    class Instance:
        async def async_add_executor_job(self, job):
            return job()

    monkeypatch.setattr("homeassistant.components.recorder.statistics.statistics_during_period", fake)
    monkeypatch.setattr("homeassistant.components.recorder.get_instance", lambda hass_: Instance())
    await coordinator._noise_daily(["sensor.x"])
    assert seen["end"] == dt_util.start_of_local_day()
    assert extras is not None


@pytest.mark.usefixtures("_afternoon")
async def test_boards_are_not_one_model_on_mixed_firmware(hass: HomeAssistant):
    """Two unrelated devices that report a bare board's maker and name
    run their own firmware; that is not one model on two versions (rule
    DEV-06)."""
    dryer, entry = _device(hass, "zha", "e1", "Dryer Sensor", "Espressif", "m5stack-atom", "2026.10.1")
    _device(hass, "zha", "e2", "Furnace Monitor", "Espressif", "m5stack-atom", "2026.9.0", entry)
    _device(hass, "zha", "e3", "Plug A", "Athom", "Smart Plug V2", "2026.10.1", entry)
    _device(hass, "zha", "e4", "Plug B", "Athom", "Smart Plug V2", "2026.9.0", entry)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    mixed = coordinator.dashboard_network("zha")["firmware"]["mixed"]
    assert [(m["maker"], m["model"]) for m in mixed] == [("Athom", "Smart Plug V2")]
