# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_radio_channels.py, Version: 0.30.0 (2026-11-21)

"""Radio channels (rules SIG-19, SIG-20, REC-13, DASH-19).

The scan below is shaped on a real house's 2.4 GHz band, names and
addresses replaced: a mesh router on Wi-Fi channel 4 with three
networks and a hidden one on one radio, a neighbour heard at 52% on
channel 1, a weaker one on 6 and a strong one on 11; Zigbee2MQTT on
channel 11 and ZHA on channel 25.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_WIFI_NETWORKS,
    STACK_Z2M,
    STACK_ZHA,
    WIFI_KEY,
)
from custom_components.device_sentinel.radio_channels import (
    covers,
    wifi_channel,
    zigbee_mhz,
)
from tests.helpers import setup_coordinator

HOME, IOT, GUEST = "Home", "Home-IoT", "Home-Guest"
SCAN: list[dict[str, Any]] = [
    {"mode": "infrastructure", "ssid": HOME, "frequency": 2427, "signal": 84, "mac": "5E:11:22:2C:33:44"},
    {"mode": "infrastructure", "ssid": IOT, "frequency": 2427, "signal": 84, "mac": "5E:11:22:4C:33:44"},
    {"mode": "infrastructure", "ssid": GUEST, "frequency": 2427, "signal": 84, "mac": "5E:11:22:5C:33:44"},
    {"mode": "infrastructure", "ssid": "", "frequency": 2427, "signal": 84, "mac": "5C:11:22:5C:33:44"},
    {"mode": "infrastructure", "ssid": "Neighbour", "frequency": 2412, "signal": 52, "mac": "A0:B1:C2:D3:E4:F5"},
    {"mode": "infrastructure", "ssid": "", "frequency": 2412, "signal": 50, "mac": "A2:B1:C2:D3:E4:F5"},
    {"mode": "infrastructure", "ssid": "Across", "frequency": 2437, "signal": 34, "mac": "10:20:30:40:50:60"},
    {"mode": "infrastructure", "ssid": "Upstairs", "frequency": 2462, "signal": 99, "mac": "70:80:90:A0:B0:C0"},
    {"mode": "infrastructure", "ssid": HOME, "frequency": 5180, "signal": 70, "mac": "5E:11:22:2C:33:45"},
]


class FakeSupervisor:
    def __init__(self, wireless: bool = True, points: list[dict[str, Any]] | None = None) -> None:
        self.wireless = wireless
        self.points = SCAN if points is None else points
        self.scans = 0
        self.info = 0

    async def send_command(self, path: str, method: str = "get") -> dict:
        if path == "/network/info":
            self.info += 1
            rows = [{"interface": "enp2s0", "type": "ethernet", "connected": True, "wifi": None}]
            if self.wireless:
                rows.append({"interface": "wlo1", "type": "wireless", "connected": True,
                             "wifi": {"ssid": IOT, "signal": 84}})
            return {"data": {"interfaces": rows}}
        if path.endswith("/accesspoints"):
            self.scans += 1
            return {"data": {"accesspoints": list(self.points)}}
        raise AssertionError(f"unexpected path {path}")


@pytest.fixture(name="supervisor")
def supervisor_fixture(hass: HomeAssistant) -> FakeSupervisor:
    fake = FakeSupervisor()
    hass.data["hassio"] = fake
    return fake


def _zha(hass: HomeAssistant, channel: Any) -> None:
    info = SimpleNamespace(channel=channel)
    app = SimpleNamespace(state=SimpleNamespace(network_info=info))
    hass.data["zha"] = SimpleNamespace(gateway_proxy=SimpleNamespace(gateway=SimpleNamespace(application_controller=app)))


def _zigbee(coord, hass, z2m: int | None = 11, zha: int | None = 25) -> None:
    if z2m is not None:
        coord._bridge_readers[STACK_Z2M] = SimpleNamespace(hardware={"channel": z2m}, async_stop=lambda: None)
    if zha is not None:
        _zha(hass, zha)


async def _scanned(hass, coord) -> None:
    coord._air_next = 0.0
    await coord.async_sweep_air(now=1_000_000.0)


# ------------------------------------------------------------ arithmetic


def test_channel_arithmetic():
    assert wifi_channel(2412) == 1
    assert wifi_channel(2427) == 4
    assert wifi_channel(2484) == 14
    assert wifi_channel(5180) == 36
    assert wifi_channel(2400) is None
    assert zigbee_mhz(11) == 2405
    assert zigbee_mhz(25) == 2475
    # Wi-Fi 1 covers Zigbee 11 to 14, 6 covers 16 to 19, 11 covers 21 to 24.
    assert [c for c in range(11, 27) if covers(2412, c)] == [11, 12, 13, 14]
    assert [c for c in range(11, 27) if covers(2437, c)] == [16, 17, 18, 19]
    assert [c for c in range(11, 27) if covers(2462, c)] == [21, 22, 23, 24]
    assert not covers(5180, 11)


# ------------------------------------------------------------- the scan


async def test_hourly_scan_where_no_network_is_chosen(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    assert supervisor.scans == 1
    await coord.async_sweep_air(now=1_000_000.0 + 1800)
    assert supervisor.scans == 1, "a second scan inside the hour"
    await coord.async_sweep_air(now=1_000_000.0 + 3600)
    assert supervisor.scans == 2


async def test_no_extra_scan_where_a_network_is_chosen(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [IOT]})
    await _scanned(hass, coord)
    assert supervisor.scans == 0
    await coord.async_sweep_wifi()
    assert supervisor.scans == 1
    assert coord.air_view()["scan"] == "ok"
    assert len(coord.air_view()["wifi"]) == len(SCAN)


async def test_no_adapter_no_scan(hass: HomeAssistant):
    fake = FakeSupervisor(wireless=False)
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    assert fake.scans == 0
    view = coord.air_view()
    assert view["scan"] == "no_adapter" and view["wifi"] == []


async def test_no_supervisor_no_scan(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    assert coord.air_view()["scan"] == "no_supervisor"


async def test_own_networks_include_the_same_radio(hass: HomeAssistant, supervisor: FakeSupervisor):
    """The server's network, and the networks and hidden one on its
    router's same radio, are the house's own; neighbours are not."""
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    rows = coord.air_view()["wifi"]
    own = {(r["ssid"], r["mhz"]) for r in rows if r["own"]}
    assert own == {(HOME, 2427), (IOT, 2427), (GUEST, 2427), ("", 2427), (HOME, 5180)}
    # The neighbour's hidden network on channel 1 stays a neighbour's.
    assert not any(r["own"] for r in rows if r["mhz"] == 2412)


async def test_a_bad_scan_row_is_skipped(hass: HomeAssistant):
    fake = FakeSupervisor(points=[{"ssid": "x"}, "junk", {"ssid": 5, "frequency": 2412, "signal": "high"}])
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    rows = coord.air_view()["wifi"]
    assert rows == [{"ssid": "", "mhz": 2412, "channel": 1, "band": "2.4 GHz", "signal": None, "own": False, "bad": False}]


# ----------------------------------------------------- what is used


async def test_zigbee_channels_from_both_stacks(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    assert [(n["key"], n["channel"]) for n in coord.zigbee_networks()] == [(STACK_Z2M, 11), (STACK_ZHA, 25)]


async def test_zha_shapes_that_moved_are_ignored(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    for broken in (None, SimpleNamespace(), SimpleNamespace(gateway_proxy=None), {"gateway_proxy": 1}):
        hass.data["zha"] = broken
        assert coord.zigbee_networks() == []
    _zha(hass, "eleven")
    assert coord.zigbee_networks() == []
    _zha(hass, 40)
    assert coord.zigbee_networks() == []


async def test_device_rows(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord._radio_stack = {"zb": STACK_Z2M}
    radio = coord.device_radio("zb")
    assert radio["words"] == "Zigbee channel 11, from Zigbee2MQTT"
    # A healthy mesh: no Zigbee card, so no warning (rule SIG-20).
    assert radio["warn"] is None
    # A device a router reports on the 2.4 GHz band of its network.
    hass.states.async_set("device_tracker.plug", "home", {"source_type": "router", "band": "2G"})
    coord._wifi_ties = {"plug": "device_tracker.plug"}
    radio = coord.device_radio("plug")
    assert radio["words"] == "Wi-Fi channel 4, 2.4 GHz, from its band on your network"
    # Named by UniFi's network and radio.
    hass.states.async_set("device_tracker.cam", "home", {"essid": HOME, "radio": "na"})
    coord._wifi_ties["cam"] = "device_tracker.cam"
    assert coord.device_radio("cam")["words"] == "Wi-Fi channel 36, 5 GHz, from its network Home"
    assert coord.device_radio("nothing") is None


async def test_matter_thread_and_wifi(hass: HomeAssistant, supervisor: FakeSupervisor, monkeypatch):
    coord = await setup_coordinator(hass)
    monkeypatch.setattr(coord, "_matter_nodes", lambda: [
        ("t1", {"0/53/0": 15}), ("w1", {"0/54/3": 6, "0/54/0": "aabbccddeeff"}), ("x", {"0/53/0": "x"}),
    ])
    coord._radio_stack = {"t1": "matter", "w1": "matter", "x": "matter"}
    assert coord.device_radio("t1")["words"] == "Thread channel 15, from the device"
    assert coord.device_radio("w1")["words"] == "Wi-Fi channel 6, 2.4 GHz, from the device"
    assert coord.device_radio("x") is None
    assert coord.network_radio("matter") == {"thread": [{"channel": 15, "devices": 1}]}


async def test_a_broken_matter_library_never_breaks_the_page(hass: HomeAssistant):
    coord = await setup_coordinator(hass)

    def boom():
        raise RuntimeError("moved")

    coord._matter_nodes = boom
    coord._radio_stack = {"m": "matter"}
    assert coord.device_radio_safe("m") is None
    assert coord.network_radio("matter") is None


# ------------------------------------------------------------- cards


async def test_wifi_card_moves_to_six(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    cards = coord.channel_cards(WIFI_KEY)
    assert len(cards) == 1 and cards[0]["channel"] == 6
    assert cards[0]["sentence"].startswith(
        "Your Wi-Fi on channel 4 overlaps a neighbour's network on channel 1, heard at 52%. "
        "If your router lets you choose, channel 6 is clearer"
    )


async def test_wifi_card_never_covers_own_zigbee(hass: HomeAssistant):
    """Own Wi-Fi on channel 1 covers Zigbee 11: the card offers 6, never
    1 again, and says why."""
    points = [
        {"ssid": HOME, "frequency": 2412, "signal": 80, "mac": "02:00:00:00:00:01"},
        {"ssid": "Far", "frequency": 2462, "signal": 20, "mac": "02:00:00:00:00:09"},
    ]
    hass.data["hassio"] = FakeSupervisor(points=points)
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [HOME]})
    _zigbee(coord, hass, z2m=11, zha=None)
    await coord.async_sweep_wifi()
    cards = coord.channel_cards(WIFI_KEY)
    assert [c["channel"] for c in cards] == [6]
    assert "covers your Zigbee or Thread channel 11" in cards[0]["sentence"]
    # The Zigbee card leaves this to the Wi-Fi card.
    coord._network_members = lambda: {STACK_Z2M: ["a"]}
    coord.is_flapping = lambda _d: True
    assert coord.channel_cards(STACK_Z2M) == []


async def test_no_wifi_card_on_a_clear_channel(hass: HomeAssistant):
    points = [{"ssid": HOME, "frequency": 2437, "signal": 80, "mac": "02:00:00:00:00:01"},
              {"ssid": "Far", "frequency": 2412, "signal": 30, "mac": "02:00:00:00:00:09"}]
    hass.data["hassio"] = FakeSupervisor(points=points)
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [HOME]})
    _zigbee(coord, hass, z2m=11, zha=None)
    await coord.async_sweep_wifi()
    assert coord.channel_cards(WIFI_KEY) == []


async def test_zigbee_card_only_when_the_mesh_shows_the_cost(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord._network_members = lambda: {STACK_Z2M: ["a", "b", "c"]}
    coord.is_flapping = lambda _d: False
    assert coord.channel_cards(STACK_Z2M) == [], "no card while every device is healthy"
    coord.is_flapping = lambda d: d in ("a", "b")
    cards = coord.channel_cards(STACK_Z2M)
    assert len(cards) == 1 and cards[0]["channel"] == 20
    assert cards[0]["sentence"] == (
        "Zigbee2MQTT is on channel 11, inside a neighbour's Wi-Fi on channel 1, heard at 52%, "
        "and 2 of its devices have a weak link. Channel 20 is clearer."
    )
    assert "pairing some devices again" in cards[0]["question"]
    # ZHA on 25 is clear of every strong network: no card.
    coord._network_members = lambda: {STACK_ZHA: ["a"]}
    assert coord.channel_cards(STACK_ZHA) == []


async def test_air_view_marks_bad_overlaps(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    view = coord.air_view()
    bad = {(o["network"], o["wifi_channel"], o["signal"]) for o in view["overlaps"] if o["bad"]}
    assert bad == {("Zigbee2MQTT", 1, 52), ("Zigbee2MQTT", 1, 50)}
    assert all(not o["bad"] for o in view["overlaps"] if o["network"] == "ZHA")
    assert [z["channel"] for z in view["zigbee"]] == [11, 25]
    assert "bssid" not in view["wifi"][0], "the chart never carries an access point's address"


async def test_cards_reach_the_recommendations_tab(hass: HomeAssistant, supervisor: FakeSupervisor, monkeypatch):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    monkeypatch.setattr(coord, "network_keys", lambda *a: [WIFI_KEY])
    rows = coord.network_recommendations()
    assert [(r["key"], [c["kind"] for c in r["cards"]]) for r in rows] == [(WIFI_KEY, ["channel"])]


# ------------------------------------------------------- the download


async def test_download_hides_every_name_and_address(hass: HomeAssistant, monkeypatch):
    """Each network the server hears, the house's own and every
    neighbour's, and each access point's address are stand-ins in the
    download; the channels stay readable (rule STOR-21)."""
    import json

    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
    from tests.helpers import setup_entry

    names = ["Lantern-Rotarran", "Lantern-Rotarran-IoT", "Lantern-Guest", "Vecino Torres 3B", "CNT_FIBRA_7781", "Casa Ortiz"]
    points = [
        {"ssid": names[0], "frequency": 2427, "signal": 84, "mac": "5E:11:22:2C:33:44"},
        {"ssid": names[1], "frequency": 2427, "signal": 84, "mac": "5E:11:22:4C:33:44"},
        {"ssid": names[2], "frequency": 2427, "signal": 84, "mac": "5E:11:22:5C:33:44"},
        {"ssid": names[3], "frequency": 2412, "signal": 52, "mac": "a0b1c2d3e4f5"},
        {"ssid": names[4], "frequency": 2437, "signal": 34, "mac": "10-20-30-40-50-6A"},
        {"ssid": names[5], "frequency": 2462, "signal": 99, "mac": "70:80:90:A0:B0:C0"},
    ]
    fake = FakeSupervisor(points=points)
    hass.data["hassio"] = fake

    async def joined(path, method="get"):
        if path == "/network/info":
            return {"data": {"interfaces": [{"interface": "wlo1", "type": "wireless", "connected": True,
                                             "wifi": {"ssid": names[1], "signal": 84}}]}}
        return await FakeSupervisor.send_command(fake, path, method)

    fake.send_command = joined
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    monkeypatch.setattr(coord, "zigbee_networks", lambda: [{"key": STACK_Z2M, "name": "Zigbee2MQTT", "channel": 11}])
    await _scanned(hass, coord)
    assert fake.scans == 1
    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry), default=str)
    for name in names:
        assert name not in text, name
    for mac in ("2C:33:44", "D3:E4:F5", "d3e4f5", "40-50-6A", "A0:B0:C0"):
        assert mac not in text, mac
    radio = json.loads(text)["classification"]["radio_channels"]
    assert radio["scan"] == "ok"
    # Keys only: a network's display name could read as a device's.
    assert radio["zigbee"] == [{"key": "z2m", "channel": 11}]
    assert all("question" not in c for c in radio["cards"]["wifi"])
    assert radio["acknowledged"] == []
    assert [r["channel"] for r in radio["heard"]] == [1, 4, 4, 4, 6, 11]
    assert [c["channel"] for c in radio["cards"]["wifi"]] == [6]


async def test_a_supervisor_that_fails_is_asked_again_in_five_minutes(hass: HomeAssistant):
    fake = FakeSupervisor()
    real = fake.send_command
    down = {"on": True}

    async def flaky(path, method="get"):
        if down["on"]:
            raise RuntimeError("starting")
        return await real(path, method)

    fake.send_command = flaky
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    assert coord.air_view()["scan"] == "not_yet"
    down["on"] = False
    await coord.async_sweep_air(now=1_000_000.0 + 120)
    assert fake.scans == 0, "asked again before five minutes"
    await coord.async_sweep_air(now=1_000_000.0 + 300)
    assert fake.scans == 1 and coord.air_view()["scan"] == "ok"


async def test_matter_nodes_through_the_matter_server(hass: HomeAssistant):
    """A node's channel reaches its own device, read from what the
    Matter integration holds, with its access point written in base64."""
    import base64

    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.device_sentinel.radio_channels import _matter_mac

    coord = await setup_coordinator(hass)
    entry = MockConfigEntry(domain="matter", title="matter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    fabric = 0x2A6F1C3D4E5B6A79
    reg = dr.async_get(hass)
    thread = reg.async_get_or_create(config_entry_id=entry.entry_id, name="Sensor",
                                     identifiers={("matter", f"deviceid_{fabric:016X}-{22:016X}-MatterNodeDevice")})
    plug = reg.async_get_or_create(config_entry_id=entry.entry_id, name="Plug",
                                   identifiers={("matter", f"deviceid_{fabric:016X}-{19:016X}-MatterNodeDevice")})
    ap = base64.b64encode(bytes.fromhex("5E11224C3344")).decode()
    nodes = [
        SimpleNamespace(node_id=22, node_data=SimpleNamespace(attributes={"0/53/0": 25, "0/53/1": 3})),
        SimpleNamespace(node_id=19, node_data=SimpleNamespace(attributes={"0/54/3": 11, "0/54/0": ap, "0/54/4": -60})),
        SimpleNamespace(node_id=7, node_data=SimpleNamespace(attributes={"0/53/0": 15})),
    ]
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=SimpleNamespace(get_nodes=lambda: nodes)))
    radios = coord._matter_radios()
    assert radios == {thread.id: {"kind": "thread", "channel": 25},
                      plug.id: {"kind": "wifi", "channel": 11, "bssid": "5E:11:22:4C:33:44"}}
    assert _matter_mac("5e:11:22:4c:33:44") == "5E:11:22:4C:33:44"
    assert _matter_mac(bytes.fromhex("5E11224C3344")) == "5E:11:22:4C:33:44"
    assert _matter_mac("not-a-mac") is None
    coord._radio_stack = {thread.id: "matter"}
    assert coord.device_radio(thread.id)["words"] == "Thread channel 25, from the device"


async def test_an_adapter_turned_off_is_not_scanned(hass: HomeAssistant):
    fake = FakeSupervisor()
    real = fake.send_command

    async def off(path, method="get"):
        answer = await real(path, method)
        if path == "/network/info":
            for row in answer["data"]["interfaces"]:
                if row["type"] == "wireless":
                    row.update(enabled=False, connected=False, wifi=None)
        return answer

    fake.send_command = off
    hass.data["hassio"] = fake
    coord = await setup_coordinator(hass)
    await _scanned(hass, coord)
    assert fake.scans == 0
    assert coord.air_view()["scan"] == "adapter_off"


async def test_a_zigbee_card_never_offers_a_thread_channel(hass: HomeAssistant, supervisor: FakeSupervisor, monkeypatch):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord._network_members = lambda: {STACK_Z2M: ["a"]}
    coord.is_flapping = lambda _d: True
    monkeypatch.setattr(coord, "_matter_nodes", lambda: [("t1", {"0/53/0": 20})])
    cards = coord.channel_cards(STACK_Z2M)
    assert [c["channel"] for c in cards] != [20]
    assert all(c["channel"] not in (20, 25) for c in cards)


async def test_a_mesh_on_two_channels_gets_one_wifi_card(hass: HomeAssistant):
    """Two of the house's access points, on channels 1 and 4, both
    crowded: one card, for the one over Zigbee channel 11."""
    points = [
        {"ssid": HOME, "frequency": 2412, "signal": 80, "mac": "02:00:00:00:00:01"},
        {"ssid": HOME, "frequency": 2427, "signal": 70, "mac": "02:00:00:00:00:11"},
        {"ssid": "Next", "frequency": 2417, "signal": 90, "mac": "0A:00:00:00:00:09"},
    ]
    hass.data["hassio"] = FakeSupervisor(points=points)
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [HOME]})
    _zigbee(coord, hass, z2m=11, zha=None)
    await coord.async_sweep_wifi()
    cards = coord.channel_cards(WIFI_KEY)
    assert len(cards) == 1
    assert cards[0]["sentence"].startswith("Your Wi-Fi on channel 1 covers your Zigbee or Thread channel 11")


# ------------------------------------------------------- the tick


async def test_a_ticked_channel_card_stays_faded_and_leaves_the_count(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    [card] = row["cards"]
    assert card["ack_key"] == "net:wifi:channel:to:6:crowded" and card["acknowledged"] is False
    coord.set_recommendation_ack(True, line=card["ack_key"])
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    assert row["cards"][0]["acknowledged"] is True, "still listed, ticked"
    # The router moves to channel 1, over Zigbee channel 11: a new card, unticked.
    for air in coord._air:
        if air["ssid"].startswith("Home") and air["mhz"] == 2427:
            air.update(mhz=2412, channel=1)
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    assert row["cards"][0]["ack_key"] == "net:wifi:channel:to:6:covered"
    assert row["cards"][0]["acknowledged"] is False


async def test_a_router_that_moves_with_the_same_advice_keeps_its_tick(hass: HomeAssistant, supervisor: FakeSupervisor):
    """A mesh router that picks its own channel each night moved from 4
    to 3: the card still says channel 6, so the person's tick holds, and
    the device pages stay quiet (rule REC-07)."""
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    coord.set_recommendation_ack(True, line=row["cards"][0]["ack_key"])
    for air in coord._air:
        if air["mhz"] == 2427:
            air.update(mhz=2422, channel=3)
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    [card] = row["cards"]
    assert card["reason"] == "wifi:3:crowded" and card["channel"] == 6
    assert card["acknowledged"] is True


async def test_a_tick_given_on_the_earlier_release_still_holds(hass: HomeAssistant, supervisor: FakeSupervisor):
    """The tick was first kept under the router's channel. After the
    update, with nothing changed, the card stays ticked; unticking it
    clears it."""
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    coord._acks().setdefault("lines", {})["net:wifi:channel:wifi:4:crowded"] = True
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    assert row["cards"][0]["acknowledged"] is True
    coord.set_recommendation_ack(False, line=row["cards"][0]["ack_key"])
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    assert row["cards"][0]["acknowledged"] is False


async def test_untick_brings_it_back(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    key = coord.network_recommendations()[0]["cards"][0]["ack_key"]
    coord.set_recommendation_ack(True, line=key)
    coord.set_recommendation_ack(False, line=key)
    assert coord.network_recommendations()[0]["cards"][0]["acknowledged"] is False


async def test_a_tick_needs_a_card_that_is_shown(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    for line in ("net:wifi:channel:wifi:9:crowded", "net:mqtt:channel:x", "net:"):
        with pytest.raises(ValueError):
            coord.set_recommendation_ack(True, line=line)


async def test_midnight_keeps_a_shown_cards_tick_and_forgets_a_gone_one(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    key = coord.network_recommendations()[0]["cards"][0]["ack_key"]
    coord.set_recommendation_ack(True, line=key)
    coord.prune_recommendation_acks()
    assert coord._acks()["lines"].get(key) is True
    # The neighbour goes quiet: the card is held a day (rule REC-13),
    # then gone, and two days on, no tick.
    coord._air = [r for r in coord._air if r["mhz"] != 2412]
    coord.prune_recommendation_acks()
    assert coord._acks()["lines"].get(key) is True, "held for a day"
    freezer.tick(86400 + 60)
    coord.network_recommendations()
    coord._net_ack_seen = {}
    coord.prune_recommendation_acks()
    assert key not in coord._acks()["lines"]


async def test_the_device_warning_follows_its_card(hass: HomeAssistant, supervisor: FakeSupervisor):
    """A neighbour over Zigbee channel 11: no warning while the mesh is
    healthy, a warning once the Zigbee card shows, none once it is ticked."""
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    coord._radio_stack = {"zb": STACK_Z2M}
    coord._network_members = lambda: {STACK_Z2M: ["zb", "b"]}
    coord.is_flapping = lambda _d: False
    assert coord.device_radio("zb")["warn"] is None
    coord.is_flapping = lambda _d: True
    assert coord.device_radio("zb")["warn"] == "A neighbour's Wi-Fi on channel 1, heard at 52%, covers this channel."
    [card] = coord.channel_cards(STACK_Z2M)
    coord.mark_network_cards(STACK_Z2M, [card])
    coord.set_recommendation_ack(True, line=card["ack_key"])
    assert coord.device_radio("zb")["warn"] is None


async def test_the_own_wifi_warning_follows_the_wifi_card(hass: HomeAssistant):
    points = [{"ssid": HOME, "frequency": 2412, "signal": 80, "mac": "02:00:00:00:00:01"},
              {"ssid": "Far", "frequency": 2462, "signal": 20, "mac": "02:00:00:00:00:09"}]
    hass.data["hassio"] = FakeSupervisor(points=points)
    coord = await setup_coordinator(hass, {CONF_WIFI_NETWORKS: [HOME]})
    _zigbee(coord, hass, z2m=11, zha=None)
    await coord.async_sweep_wifi()
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    coord._radio_stack = {"zb": STACK_Z2M}
    assert coord.device_radio("zb")["warn"] == "Your own Wi-Fi on channel 1 covers this channel."
    [row] = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    coord.set_recommendation_ack(True, line=row["cards"][0]["ack_key"])
    assert coord.device_radio("zb")["warn"] is None


async def test_the_tick_command(hass: HomeAssistant, supervisor: FakeSupervisor, hass_ws_client):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/recommendations"})
    recs = (await client.receive_json())["result"]
    [row] = [r for r in recs["networks"] if r["key"] == WIFI_KEY]
    key = row["cards"][0]["ack_key"]
    await client.send_json({"id": 2, "type": "device_sentinel/recommendation_ack", "line": key, "on": True})
    assert (await client.receive_json())["success"]
    await client.send_json({"id": 3, "type": "device_sentinel/network", "key": WIFI_KEY})
    page = (await client.receive_json())["result"]
    assert page["cards"][0]["acknowledged"] is True


async def test_hostile_ticks_are_ignored(hass: HomeAssistant, supervisor: FakeSupervisor):
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    coord.network_keys = lambda *a: [WIFI_KEY, STACK_Z2M]
    coord._recommendation_acks = {"devices": {}, "lines": {"net:wifi:channel:wifi:4:crowded": "yes"}}
    coord._acks_read({"lines": {"net:wifi:channel:wifi:4:crowded": "yes", "net:x": 5}})
    assert coord._acks()["lines"] == {}
