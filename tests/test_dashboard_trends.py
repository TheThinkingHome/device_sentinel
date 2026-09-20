# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_trends.py, Version: 0.22.10 (2026-09-20)

"""The Battery Trends and Signal Trends tabs.

Both are fleet views: they answer questions a single device's page
cannot. Which of your models eat cells, and which days several
devices had a bad signal at once. Every figure comes from the
reports' own functions, worked out when asked.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
)

from tests.helpers import setup_coordinator


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _add(hass, entry, uid, name, maker, model):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", uid)},
        name=name, manufacturer=maker, model=model,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", f"{uid}_x", device_id=device.id, config_entry=entry
    )
    return device


async def _fleet(hass: HomeAssistant):
    entry = MockConfigEntry(domain="mqtt", title="MQTT")
    entry.add_to_hass(hass)
    # Two of one model, holding; one of another, falling; one unreadable;
    # one mains device with no battery at all.
    holding_a = _add(hass, entry, "d1", "Door One", "Aqara", "Door and window sensor")
    holding_b = _add(hass, entry, "d2", "Door Two", "Aqara", "Door and window sensor")
    falling = _add(hass, entry, "m1", "Motion Hall", "Third Reality", "Wireless motion sensor")
    unreadable = _add(hass, entry, "l1", "LUX Outdoors", "Tuya", "Illuminance sensor")
    mains = _add(hass, entry, "p1", "Plug Kitchen", "Third Reality", "Smart plug")
    coord = await setup_coordinator(hass)
    records = coord.data["devices"]
    records[holding_a.id].update({DEV_BATTERY_VALUE: 100.0, DEV_BATTERY_DAILY: [100.0] * 40})
    records[holding_b.id].update({DEV_BATTERY_VALUE: 98.0, DEV_BATTERY_DAILY: [98.0] * 40})
    # Losing a point every five days: 0.2 a day.
    series = [100.0 - index * 0.2 for index in range(40)]
    records[falling.id].update({DEV_BATTERY_VALUE: series[-1], DEV_BATTERY_DAILY: series})
    records[unreadable.id].update({DEV_BATTERY_VALUE: 180.0, DEV_BATTERY_DAILY: [180.0] * 40})
    # Signal: two devices steady, one that fell away in its last week.
    steady = [200.0] * 30
    fell = [200.0] * 23 + [150.0] * 7
    records[holding_a.id].update({
        DEV_SIGNAL_DAILY_P50: list(steady), DEV_SIGNAL_DAILY_P5: [190.0] * 30,
        DEV_SIGNAL_DAILY_COUNT: [12] * 30, DEV_SIGNAL_SCALE: "lqi", DEV_SIGNAL_VALUE: 200.0,
    })
    records[falling.id].update({
        DEV_SIGNAL_DAILY_P50: list(fell), DEV_SIGNAL_DAILY_P5: [190.0] * 23 + [140.0] * 7,
        DEV_SIGNAL_DAILY_COUNT: [9] * 30, DEV_SIGNAL_SCALE: "lqi", DEV_SIGNAL_VALUE: 150.0,
    })
    records[mains.id].update({
        DEV_SIGNAL_DAILY_P50: [-55.0] * 30, DEV_SIGNAL_DAILY_P5: [-60.0] * 30,
        DEV_SIGNAL_DAILY_COUNT: [20] * 30, DEV_SIGNAL_SCALE: "rssi", DEV_SIGNAL_VALUE: -55.0,
    })
    return coord, holding_a, falling, unreadable, mains


async def test_battery_trends_group_every_cell_by_model(hass: HomeAssistant, hass_ws_client):
    coord, holding, falling, unreadable, _ = await _fleet(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/battery_trends")
    assert reply["success"], reply
    page = reply["result"]
    models = {f"{row['maker']} {row['model']}": row for row in page["models"]}
    assert sum(row["cells"] for row in page["models"]) == page["cells"]
    assert page["cells"] == 3, "the unreadable cell and the mains device are not counted"
    aqara = models["Aqara Door and window sensor"]
    assert aqara["cells"] == 2
    assert aqara["rate"] == 0.0
    assert aqara["lowest"] == 98.0
    assert aqara["typical"] == 99.0
    third = models["Third Reality Wireless motion sensor"]
    assert round(third["rate"], 3) == -0.2
    assert page["models"][0]["maker"] == "Third Reality", "the fastest drain first"


async def test_battery_trends_carry_the_reports_own_groups(hass: HomeAssistant, hass_ws_client):
    coord, holding, falling, unreadable, _ = await _fleet(hass)
    client = await hass_ws_client(hass)
    page = (await _call(client, type="device_sentinel/battery_trends"))["result"]
    report = coord._battery_rows()
    assert [row["device_id"] for row in page["falling"]] == [row["device_id"] for row in report["falling"]]
    assert page["falling"][0]["reading"] == report["falling"][0]["reading"]
    assert page["falling"][0]["left"] == coord.battery_time_left(report["falling"][0]["days"])
    assert [row["device_id"] for row in page["unreadable"]] == [unreadable.id]
    assert page["no_battery"] == 1, "the mains device"
    assert len(page["bank"]) == 10
    assert sum(page["bank"]) == page["cells"]


async def test_signal_trends_measure_each_link_against_its_own_normal(hass: HomeAssistant, hass_ws_client):
    coord, holding, falling, _, mains = await _fleet(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/signal_trends")
    assert reply["success"], reply
    page = reply["result"]
    rows = {row["device_id"]: row for row in page["devices"]}
    assert rows[holding.id]["change"] == 0.0
    # Its last week reads 150 against a normal of 200.
    assert rows[falling.id]["now"] == 150.0
    assert rows[falling.id]["normal"] == 200.0
    assert rows[falling.id]["change"] == -50.0
    assert rows[falling.id]["spreads"] is not None
    assert page["scales"] == {"lqi": 2, "rssi": 1}
    assert rows[mains.id]["scale"] == "rssi"


async def test_signal_trends_name_the_days_several_devices_had_a_bad_one(hass: HomeAssistant, hass_ws_client):
    coord, holding, falling, _, _ = await _fleet(hass)
    client = await hass_ws_client(hass)
    page = (await _call(client, type="device_sentinel/signal_trends"))["result"]
    for row in page["bad_days"]:
        assert row["devices"] >= 2, "a single device's bad day is its own business"
        assert row["day"] <= dt_util.now().date().isoformat()
    steady = [row for row in page["devices"] if row["bad_days"] == 0]
    assert holding.id in [row["device_id"] for row in steady]
    assert page["counts"]["steady"] + page["counts"]["unsteady"] == len(page["devices"])


async def test_both_are_admin_only(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await _fleet(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for kind in ("battery_trends", "signal_trends"):
        assert (await _call(client, type=f"device_sentinel/{kind}"))["error"]["code"] == "unauthorized"
