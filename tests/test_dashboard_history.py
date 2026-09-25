# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_history.py, Version: 0.23.6 (2026-09-25)

"""The device page's history: the report's figures, worked out once.

Every figure the page shows beside its graphs comes from the same
functions the battery and signal reports call, so the page and the
reports cannot disagree. Nothing is stored: a past day's judgment is
recalculated from the daily history whenever it is asked for. The
outages drawn behind the graphs are the natural ones on the device's
own path; one that began during a restart or its grace is not drawn.

The series are Button Terrace Dining's, from the reference rig's
storage of 20 September.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_SCALE,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_WHEN,
    SYS_WORST,
)

from tests.helpers import setup_coordinator

BATTERY = [95.0, 95.0, 95.0, 94.5, 95.5, 95.0, 95.0, 94.5, 95.0, 95.0, 94.0, 94.5, 94.5, 94.0, 94.0, 94.5, 94.0, 93.5, 93.0, 93.5, 94.0, 94.5, 93.5, 93.5, 93.0, 94.0, 93.5, 92.5, 93.0, 93.5, 93.0, 93.0, 93.0, 93.5, 92.5, 93.0, 93.0, 93.0, 93.5, 91.5, 93.0, 92.0, 93.0, 92.5, 92.5, 92.0, 92.5, 92.0, 92.0, 93.0, 92.0, 92.0, 92.5, 92.0, 92.0, 91.5, 91.5, 92.0, 92.0, 92.0, 91.5, 91.5, 91.5, 91.0]
P50 = [215.94, 196.08, 200.02, 200.23, 196.06, 192.39, 190.35, 180.42, 187.86, 192.83, 188.01, 196.0, 185.34, 199.96, 187.03, 189.33, 183.15, 208.03, 192.34, 179.54, 167.11, 181.27, 190.81, 188.94, 189.01, 195.95, 199.96, 189.91, 192.26, 192.89, 182.01, 181.49, 172.31, 166.08, 169.5, 199.55, 181.27, 194.48, 181.02]
P5 = [188.29, 152.53, 192.03, 168.1, 118.26, 152.08, 176.03, 164.0, 164.43, 164.37, 152.07, 152.07, 172.17, 168.42, 172.24, 172.33, 148.4, 157.15, 157.96, 172.02, 152.02, 172.0, 120.56, 184.0, 176.3, 176.05, 176.32, 180.01, 192.0, 185.57, 180.0, 164.12, 144.02, 148.02, 156.01, 180.2, 152.08, 120.52, 156.88]
GAPS = [14769, 17477, 27788, 20244, 33311, 32961, 10054, 28532, 11328, 21731, 14278, 12145, 21306, 24445, 33380, 43358, 43354, 29873, 28251, 29807, 35787, 43357, 38946, 35955, 37086, 43376, 43369, 38984, 40275, 42145, 39960, 38711, 37800, 43232, 54980, 38830, 26299, 33280, 43271, 43310, 38801, 23849, 33311, 43297, 43272, 38813, 34606, 33289, 43268, 43289, 40131, 42238, 33046, 41080, 38932, 43431, 43350, 38901, 33487, 33431, 43436, 43472, 38921, 27977, 33482, 43434, 41969, 38907, 43353, 33400, 43484]
COUNTS = [9] * 25 + [8, 7, 7, 7, 10, 11, 21, 7, 13, 10, 7, 13, 8, 12]


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def _terrace(hass: HomeAssistant):
    mqtt = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", "terrace")},
        name="Button Terrace Dining", manufacturer="Third Reality", model="Smart button",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "terrace_battery", device_id=device.id, config_entry=mqtt,
        original_device_class="battery", unit_of_measurement="%",
    )
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id].update({
        DEV_BATTERY_VALUE: 91.0,
        DEV_BATTERY_DAILY: list(BATTERY),
        DEV_SIGNAL_DAILY_P5: list(P5),
        DEV_SIGNAL_DAILY_P50: list(P50),
        DEV_SIGNAL_DAILY_COUNT: list(COUNTS),
        DEV_SIGNAL_SCALE: "lqi",
        DEV_DAILY_MAX: list(GAPS),
    })
    return coord, device


async def _page(hass, hass_ws_client, device):
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/device", device_id=device.id)
    assert reply["success"], reply
    return reply["result"]


async def test_the_battery_figures_are_the_reports_own(hass: HomeAssistant, hass_ws_client):
    """Button Terrace Dining's cell of 20 September, which the report
    listed as falling "over a year" on a seven-day slope of -0.167 a
    day. Its weekly averages move by a few tenths, so since 0.23.6 it
    reads steady, with no line drawn and no time left: the fault the
    release was built for, on a real cell."""
    from custom_components.device_sentinel.report_battery import battery_weeks

    coord, device = await _terrace(hass)
    page = await _page(hass, hass_ws_client, device)
    battery = page["battery"]
    record = coord.data["devices"][device.id]
    assert battery["weeks"] == battery_weeks(record["battery_daily_value"])
    assert len(battery["weeks"]) == 5
    assert all(abs(a - b) < 1.0 for a, b in zip(battery["weeks"], battery["weeks"][1:]))
    assert battery["reading"] == ""
    assert battery["fit"] is None
    assert battery["left"] is None
    assert battery["sentence"] == ""
    assert device.id not in [row["device_id"] for row in coord._battery_rows()["falling"]]


async def test_each_signal_day_is_judged_as_the_report_judges_it(hass: HomeAssistant, hass_ws_client):
    coord, device = await _terrace(hass)
    page = await _page(hass, hass_ws_client, device)
    judged = page["signal"]["judged"]
    record = coord.data["devices"][device.id]
    assert len(judged) == len(P5)
    for index, day in enumerate(judged):
        expected = coord.signal_day_judgment(record, index)
        assert day == expected, index
    bad = [index for index, day in enumerate(judged) if day and day["bad"]]
    assert bad == [32], "13 September, low end 144 against a line of 148"
    assert round(judged[32]["line"]) == 148
    assert page["signal"]["readings_a_day"] == 9


async def test_the_window_each_day_is_worked_out_from_the_days_before(hass: HomeAssistant, hass_ws_client):
    coord, device = await _terrace(hass)
    page = await _page(hass, hass_ws_client, device)
    rhythm = page["rhythm"]
    assert rhythm["daily"] == GAPS
    assert rhythm["windows"][0] is None
    for index in range(1, len(GAPS)):
        assert rhythm["windows"][index] == coord._freeze_window({DEV_DAILY_MAX: GAPS[:index]}), index


async def test_outages_are_the_natural_ones_on_its_path(hass: HomeAssistant, hass_ws_client):
    coord, device = await _terrace(hass)
    now = dt_util.utcnow().timestamp()
    night = now - 3 * 86400
    events = [
        # The nightly pattern: the bridge drops as Home Assistant goes
        # down for its restart and returns after it.
        {SYS_WHEN: night - 120, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"},
        {SYS_WHEN: night, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system", SYS_DURATION: 100.0},
        {SYS_WHEN: night + 60, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m", SYS_DURATION: 180.0},
        # The broker that was down from that restart until the afternoon.
        {SYS_WHEN: night + 44052, SYS_KIND: SYS_BROKER_DOWN, SYS_SCOPE: "mqtt"},
        {SYS_WHEN: night + 44052, SYS_KIND: SYS_BROKER_UP, SYS_SCOPE: "mqtt", SYS_DURATION: 44052.0},
        # A natural outage, with a restart falling inside it.
        {SYS_WHEN: now - 86400, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"},
        {SYS_WHEN: now - 86400 + 1740, SYS_KIND: SYS_RESTART, SYS_SCOPE: "system", SYS_DURATION: 31.0},
        {SYS_WHEN: now - 86400 + 2754, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m",
         SYS_DURATION: 2754.0, SYS_DEVICES: 77, SYS_WORST: 75},
        # One during maintenance.
        {SYS_WHEN: now - 7200, SYS_KIND: SYS_MAINTENANCE_OPEN, SYS_SCOPE: "system"},
        {SYS_WHEN: now - 6000, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "z2m"},
        {SYS_WHEN: now - 5700, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "z2m", SYS_DURATION: 300.0},
        {SYS_WHEN: now - 5000, SYS_KIND: SYS_MAINTENANCE_CLOSED, SYS_SCOPE: "system"},
        # Not on its path.
        {SYS_WHEN: now - 4000, SYS_KIND: "wifi_down", SYS_SCOPE: "wifi"},
        {SYS_WHEN: now - 3700, SYS_KIND: "wifi_up", SYS_SCOPE: "wifi", SYS_DURATION: 300.0},
        {SYS_WHEN: now - 3600, SYS_KIND: SYS_BRIDGE_DOWN, SYS_SCOPE: "zha"},
        {SYS_WHEN: now - 3300, SYS_KIND: SYS_BRIDGE_UP, SYS_SCOPE: "zha", SYS_DURATION: 300.0},
    ]
    coord.data[DATA_SYSTEM_EVENTS] = events
    page = await _page(hass, hass_ws_client, device)
    outages = page["outages"]
    assert [(o["what"], o["minutes"], o["maintenance"]) for o in outages] == [
        ("Bridge: Zigbee2MQTT", 46, False),
        ("Bridge: Zigbee2MQTT", 5, True),
    ]
    assert outages[0]["devices"] == 77 and outages[0]["worst"] == 75
