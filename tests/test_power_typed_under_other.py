# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_power_typed_under_other.py, Version: 0.30.7 (2026-11-26)

"""Words typed under Other are a battery or a wired source (rules DEV-08, REC-04).

Anything typed under Other used to be saved as a battery, so "UPS"
put a wired device in the battery lists. Other asks instead: wired
takes no quantity and is judged as mains. A device saved the old way,
whose words name no battery, is listed on Check Power Typed Under Other
until answered.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.power_source import _clean_entry, known_battery_type

from tests.helpers import register_device, setup_coordinator


@pytest.mark.parametrize(("words", "battery"), [
    ("UPS", False), ("switched mains", False), ("UPS 1500", False), ("USB-C", False), ("solar", False),
    ("LR44", True), ("2 AA lithium", True), ("CR2032", True), ("18650", True), ("INR18650", True),
    ("Rechargeable", True), ("9V", True), ("LIR2450", True), ("2× AAA", True), ("", False),
])
def test_battery_words(words, battery):
    assert known_battery_type(words) is battery


def _card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "other_power"), None)


async def test_wired_is_judged_as_mains(hass: HomeAssistant):
    router, _ = register_device(hass, "router", name="Router")
    coord = await setup_coordinator(hass)
    coord.page_set_power(router.id, "Other", 2, "UPS", wired=True)
    known = coord.power_of(router.id)
    assert known["kind"] == "mains" and known["type"] == "UPS" and known["quantity"] is None
    assert coord.power_report_url(router.id) is None
    assert not coord._battery_powered(router.id)
    assert _card(coord) is None


async def test_battery_keeps_its_count_and_is_not_asked_again(hass: HomeAssistant):
    remote, _ = register_device(hass, "remote", name="Remote")
    coord = await setup_coordinator(hass)
    coord.page_set_power(remote.id, "Other", 3, "Coin thing", wired=False)
    known = coord.power_of(remote.id)
    assert known["kind"] == "battery" and known["quantity"] == 3
    assert _card(coord) is None


async def test_words_saved_the_old_way_are_listed_until_answered(hass: HomeAssistant):
    router, _ = register_device(hass, "router", name="Router")
    cell, _ = register_device(hass, "cell", name="Cell")
    coord = await setup_coordinator(hass)
    coord.page_set_power(router.id, "Other", 1, "UPS")
    coord.page_set_power(cell.id, "Other", 1, "LR44")
    card = _card(coord)
    assert [row["device_id"] for row in card["devices"]] == [router.id]
    assert card["devices"][0]["detail"] == "UPS" and card["devices"][0]["quantity"] == 1
    assert card["simple"] is True and card["title"] == "Check Power Typed Under Other"
    assert card["brief"].startswith("1 device has power typed under Other that is treated as a battery.")
    coord.page_set_power(router.id, "Other", None, "UPS", wired=True)
    assert _card(coord) is None


async def test_the_answer_is_kept_across_a_restart():
    assert _clean_entry({"kind": "mains", "type": "UPS", "quantity": None, "asked": True})["asked"] is True
    assert "asked" not in _clean_entry({"kind": "battery", "type": "UPS", "quantity": 1})
    assert _clean_entry({"kind": "battery", "type": "UPS", "quantity": 1, "asked": "yes"}).get("asked") is None


async def test_wired_words_must_be_given(hass: HomeAssistant):
    router, _ = register_device(hass, "router", name="Router")
    coord = await setup_coordinator(hass)
    with pytest.raises(ValueError):
        coord.page_set_power(router.id, "Other", None, "   ", wired=True)
    with pytest.raises(ValueError):
        coord.page_set_power(router.id, "Other", None, "Not known", wired=True)
