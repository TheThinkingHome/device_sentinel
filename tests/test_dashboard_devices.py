# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_devices.py, Version: 0.27.10 (2026-10-27)

"""The Devices tab and each device's page (rules DASH-06, DASH-08).

The page answers every question about one device in one place: who it
is (with the fields a battery library matches on), how it is doing
now, the rhythm its window was learned from, its silences, and its
battery and signal history on one date axis. The status comes from
the stored verdict the Problem List reads, so the two cannot disagree.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_EPISODES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_WINDOW,
    EPISODE_ENDED_RESUMED,
)

from tests.helpers import setup_coordinator

GAPS = [3023.0, 3029.0, 3030.0, 3034.0, 3022.0, 3025.0, 3021.0, 3025.0,
        3028.0, 3020.0, 3029.0, 3022.0, 6055.0, 6030.0]


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def _door(hass: HomeAssistant):
    """Door Entryway, from a real house, as closely as a test can."""
    mqtt = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Entryway")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt.entry_id,
        identifiers={("mqtt", "zigbee2mqtt_0x00158d0001a2b3c4")},
        connections={("zigbee", "0x00158d0001a2b3c4")},
        name="Door Entryway", manufacturer="Aqara",
        model="Door and window sensor", model_id="MCCGQ11LM", hw_version="2",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    entities = er.async_get(hass)
    battery = entities.async_get_or_create(
        "sensor", "mqtt", "door_battery", device_id=device.id, config_entry=mqtt,
        original_device_class="battery", unit_of_measurement="%",
        suggested_object_id="door_entryway_battery",
    )
    signal = entities.async_get_or_create(
        "sensor", "mqtt", "door_lqi", device_id=device.id, config_entry=mqtt,
        suggested_object_id="door_entryway_linkquality",
    )
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    now = dt_util.utcnow().timestamp()
    record.update({
        DEV_DAILY_MAX: list(GAPS),
        DEV_LAST_ACTIVITY: now - 37 * 60,
        DEV_EVENT_COUNT: 10270,
        DEV_FIRST_OBSERVED: "2026-07-11T01:17:48+00:00",
        DEV_BATTERY_VALUE: 100.0,
        DEV_BATTERY_DAILY: [100.0] * 63,
        DEV_SIGNAL_VALUE: 236.0,
        DEV_SIGNAL_DAILY_P5: [220.0] * 38,
        DEV_SIGNAL_DAILY_P50: [233.0] * 38,
        DEV_SIGNAL_DAILY_RAIL: [0] * 16 + [2] + [0] * 25,
        DEV_SIGNAL_SCALE: "lqi",
    })
    coord.data[DATA_EPISODES] = [{
        EP_DEVICE_ID: device.id, EP_NAME: "Door Entryway",
        EP_SINCE: now - 30 * 3600, EP_AT: now - 30 * 3600 + 6048,
        EP_BASIS: 3060.0, EP_WINDOW: 7452.0,
        EP_ENDED: EPISODE_ENDED_RESUMED, EP_LEARNED: "yes",
    }]
    return coord, device, battery, signal


async def test_the_devices_tab_lists_every_watched_device(hass: HomeAssistant, hass_ws_client):
    coord, device, _, _ = await _door(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/devices")
    assert reply["success"], reply
    row = next(r for r in reply["result"]["rows"] if r["device_id"] == device.id)
    assert row["name"] == "Door Entryway"
    assert row["integration"] == "mqtt"
    assert row["status"] == "reporting"
    assert row["rhythm"] == 6030.0
    assert row["window"] == coord._freeze_window(coord.data["devices"][device.id])
    assert row["last_activity"] is not None
    assert len(reply["result"]["rows"]) == len(coord._watched)


async def test_a_window_still_learned_reads_learning(hass: HomeAssistant, hass_ws_client):
    """A rhythm from five days and no window yet says learning, not a
    blank cell (rule FRZ-05)."""
    coord, device, _, _ = await _door(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = list(GAPS[:5])
    assert coord._freeze_window(record) is None
    client = await hass_ws_client(hass)
    rows = (await _call(client, type="device_sentinel/devices"))["result"]["rows"]
    row = next(r for r in rows if r["device_id"] == device.id)
    assert (row["window"], row["window_learning"]) == (None, True)
    # A window learned is not learning.
    record[DEV_DAILY_MAX] = list(GAPS)
    rows = (await _call(client, type="device_sentinel/devices"))["result"]["rows"]
    row = next(r for r in rows if r["device_id"] == device.id)
    assert row["window"] and row["window_learning"] is False
    # And a device with no learned day yet, on a fresh install.
    record[DEV_DAILY_MAX] = []
    rows = (await _call(client, type="device_sentinel/devices"))["result"]["rows"]
    row = next(r for r in rows if r["device_id"] == device.id)
    assert (row["window"], row["window_learning"]) == (None, True)
    # A hub, or a device its hub judges, is never judged by a window, so
    # it is not learning one: a Lutron Caseta hub. The row says how it
    # is judged (rule STACK-10; tests/test_judged_by.py).
    coord.judged_by_hub = lambda device_id: True
    rows = (await _call(client, type="device_sentinel/devices"))["result"]["rows"]
    row = next(r for r in rows if r["device_id"] == device.id)
    assert (row["window"], row["window_learning"]) == (None, False)
    assert row["judged_by"] == {"how": "connection"}


async def test_the_page_says_when_the_log_normal_count_started_again(hass: HomeAssistant):
    """When three long days start the Log-Normal Percentile's count
    again, its chart leaves the page, so the page says since when and
    how many days are left rather than showing nothing (rule FRZ-05)."""
    from datetime import timedelta

    from custom_components.device_sentinel.const import DEV_LOGNORMAL_DAYS

    coord, device, _, _ = await _door(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3000.0 + (i % 5) * 20 for i in range(40)]
    record[DEV_LOGNORMAL_DAYS] = 8
    again = coord.dashboard_device(device.id)["rhythm"]["rules"]["counting_again"]
    today = dt_util.now().date()
    assert again == {"since": (today - timedelta(days=8)).isoformat(), "to_go": 20}
    # A day with no learned gap since does not move the restart date,
    # because the history's own days date it.
    from custom_components.device_sentinel.daily_dates import FAMILY_GAP, set_dates

    yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
    days = [yesterday - timedelta(days=i) for i in range(41) if i != 3][::-1]
    record[DEV_DAILY_MAX] = [3000.0] * len(days)
    set_dates(record, FAMILY_GAP, days)
    record[DEV_LOGNORMAL_DAYS] = 7
    again = coord.dashboard_device(device.id)["rhythm"]["rules"]["counting_again"]
    assert again["since"] == (yesterday - timedelta(days=7)).isoformat()
    # Nothing to say once the count covers 28 days, or where none started.
    record[DEV_LOGNORMAL_DAYS] = None
    assert coord.dashboard_device(device.id)["rhythm"]["rules"]["counting_again"] is None
    # Nor for a device whose history is all since the reset: it is new,
    # not counting again.
    record[DEV_DAILY_MAX] = [3000.0] * 5
    record[DEV_LOGNORMAL_DAYS] = 5
    assert coord.dashboard_device(device.id)["rhythm"]["rules"]["counting_again"] is None


async def test_a_devices_page_carries_everything_known(hass: HomeAssistant, hass_ws_client):
    coord, device, battery, signal = await _door(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/device", device_id=device.id)
    assert reply["success"], reply
    page = reply["result"]

    identity = page["identity"]
    assert identity["manufacturer"] == "Aqara"
    assert identity["model"] == "Door and window sensor"
    assert identity["model_id"] == "MCCGQ11LM"
    assert identity["hw_version"] == "2"
    assert identity["area"] == "Entryway"
    assert identity["integration"] == "mqtt"
    assert ["zigbee", "0x00158d0001a2b3c4"] in identity["connections"]
    assert identity["event_count"] == 10270
    # What powers it: the shipped Battery Notes library knows this
    # sensor with hardware version 2 as a CR1632, and no owner entry
    # exists (rule DEV-07).
    assert identity["power"]["words"] == "CR1632"
    assert identity["power"]["source"] == "library"
    assert identity["power"]["report_url"] is None

    readings = {r["kind"]: r["entity_id"] for r in page["readings"]}
    assert readings["battery"] == battery.entity_id

    status = page["status"]
    assert status["category"] == "reporting"
    assert status["rhythm"] == 6030.0
    assert status["window"] == coord._freeze_window(coord.data["devices"][device.id])

    assert page["rhythm"]["gaps"] == GAPS
    assert page["rhythm"]["set_aside"] == [12], "the longest day is set aside"

    assert len(page["silences"]) == 1
    assert page["silences"][0]["ended"] == EPISODE_ENDED_RESUMED

    assert page["battery"]["daily"] == [100.0] * 63
    assert page["battery"]["threshold"] == coord.low_threshold
    assert page["signal"]["p50"] == [233.0] * 38
    assert page["signal"]["railed_days"][16] == 2
    assert page["signal"]["scale"] == "lqi"
    assert page["history_days"] == coord.retention_days
    assert page["series_end"] < dt_util.now().date().isoformat()


async def test_an_unknown_device_is_not_found(hass: HomeAssistant, hass_ws_client):
    await _door(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/device", device_id="nope")
    assert reply["error"]["code"] == "not_found"


async def test_both_are_admin_only(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    _, device, _, _ = await _door(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "device_sentinel/devices"},
        {"type": "device_sentinel/device", "device_id": device.id},
    ):
        assert (await _call(client, **message))["error"]["code"] == "unauthorized"
