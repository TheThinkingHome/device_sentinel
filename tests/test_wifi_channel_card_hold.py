# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_wifi_channel_card_hold.py, Version: 0.30.0 (2026-11-21)

"""The Wi-Fi channel card's two lines (rules SIG-20, REC-13).

A card for a crowded channel is made when a neighbour is heard at 50%
or more, and stays while one is heard at 40% or more, then for a day
below that. The reference house: a card ticked with neighbours on
channel 1 at 52%; the next morning the mesh router had moved from
channel 4 to 3 and the neighbours read 49% and 47%, and the card was
gone.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import WIFI_KEY
from tests.helpers import setup_coordinator
from tests.test_radio_channels import FakeSupervisor, _scanned, _zigbee  # noqa: F401

DAY = 86400.0


def _cards(coord):
    coord.network_keys = lambda *a: [WIFI_KEY]
    rows = [r for r in coord.network_recommendations() if r["key"] == WIFI_KEY]
    return rows[0]["cards"] if rows else []


def _neighbours(coord, *signals):
    loud = iter(signals)
    for air in coord._air:
        if air["mhz"] == 2412 and not air["ssid"].startswith("Home"):
            air["signal"] = next(loud)


def _router_to(coord, channel, mhz):
    for air in coord._air:
        if air["mhz"] == 2427:
            air.update(mhz=mhz, channel=channel)


async def _house(hass):
    hass.data["hassio"] = FakeSupervisor()
    coord = await setup_coordinator(hass)
    _zigbee(coord, hass)
    await _scanned(hass, coord)
    return coord


async def test_reference_house_ticked_card_stays(hass: HomeAssistant, freezer):
    coord = await _house(hass)
    [card] = _cards(coord)
    coord.set_recommendation_ack(True, line=card["ack_key"])
    _router_to(coord, 3, 2422)
    _neighbours(coord, 49, 47)
    [card] = _cards(coord)
    assert card["acknowledged"] is True, "the ticked card stays, faded"
    assert "heard at 49%" in card["sentence"]


async def test_held_down_to_forty_then_a_day(hass: HomeAssistant, freezer):
    coord = await _house(hass)
    assert len(_cards(coord)) == 1
    _neighbours(coord, 45, 41)
    assert len(_cards(coord)) == 1, "held at 45%"
    _neighbours(coord, 35, 30)
    assert len(_cards(coord)) == 1, "under 40%, waiting a day"
    freezer.tick(DAY - 60)
    [card] = _cards(coord)
    assert "heard at 45%" in card["sentence"], "told as last heard over the line"
    freezer.tick(120)
    assert _cards(coord) == [], "a day under the line ends it"
    _neighbours(coord, 47, 30)
    assert _cards(coord) == [], "between the lines does not bring it back"
    _neighbours(coord, 51, 30)
    assert len(_cards(coord)) == 1, "50% brings it back"


async def test_back_over_forty_restarts_the_day(hass: HomeAssistant, freezer):
    coord = await _house(hass)
    _cards(coord)
    _neighbours(coord, 30, 30)
    freezer.tick(DAY - 3600)
    _neighbours(coord, 42, 30)
    assert len(_cards(coord)) == 1
    _neighbours(coord, 30, 30)
    freezer.tick(DAY - 60)
    assert len(_cards(coord)) == 1, "the day counts from the last time over 40%"


async def test_after_a_restart_a_tick_holds_and_no_tick_waits_for_fifty(hass: HomeAssistant, freezer):
    coord = await _house(hass)
    _neighbours(coord, 47, 30)
    assert _cards(coord) == [], "never shown: 47% makes no card"
    coord._acks().setdefault("lines", {})["net:wifi:channel:to:6:crowded"] = True
    [card] = _cards(coord)
    assert card["acknowledged"] is True, "a tick from before the restart holds it"
