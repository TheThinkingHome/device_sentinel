# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendation_card_tick.py, Version: 0.29.8 (2026-11-19)

"""A whole recommendation card ticked Acknowledged in one press (rule REC-07).

A person with hundreds of rows on one card, Devices Sharing A Name for
one, ticks the card itself. It leaves the count and the Brief, rows
added later included, until it is unticked, or until the person works
on the card again: ticking one of its rows takes the card's tick off
(opening the card does so from the dashboard). The rows keep their own
ticks underneath.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.helpers import register_device, setup_entry

INTEGRATION = er.RegistryEntryDisabler.INTEGRATION


def _battery_off(hass: HomeAssistant, uid: str, name: str):
    device, (entity_id,) = register_device(hass, uid, name=name)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, original_device_class="battery", disabled_by=INTEGRATION)
    registry.async_update_entity(entity_id, unit_of_measurement="%")
    return device


def _card(coord, kind: str):
    return next((c for c in coord.device_recommendations() if c["kind"] == kind), None)


async def _house(hass: HomeAssistant, count: int = 3):
    devices = [_battery_off(hass, f"d{i}", f"Door {i}") for i in range(count)]
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    return coord, devices


async def test_a_ticked_card_counts_nothing_and_leaves_the_brief(hass: HomeAssistant):
    coord, devices = await _house(hass)
    assert _card(coord, "battery_off")["active"] == 3
    coord.set_recommendation_ack(True, card="battery_off")
    card = _card(coord, "battery_off")
    assert card["card_acknowledged"] is True
    assert card["active"] == 0 and card["brief"] is None
    # The rows keep their own ticks underneath.
    assert [row["acknowledged"] for row in card["devices"]] == [False, False, False]


async def test_a_row_added_later_is_silenced_too(hass: HomeAssistant):
    coord, devices = await _house(hass)
    coord.set_recommendation_ack(True, card="battery_off")
    _battery_off(hass, "late", "Late Door")
    coord._rebuild_registry_view()
    card = _card(coord, "battery_off")
    assert len(card["devices"]) == 4 and card["active"] == 0


async def test_working_on_a_row_takes_the_cards_tick_off(hass: HomeAssistant):
    coord, devices = await _house(hass)
    coord.set_recommendation_ack(True, card="battery_off")
    coord.set_recommendation_ack(True, kind="battery_off", device_id=devices[0].id)
    card = _card(coord, "battery_off")
    assert card["card_acknowledged"] is False
    assert card["active"] == 2


async def test_untick_brings_the_count_back_as_it_was(hass: HomeAssistant):
    coord, devices = await _house(hass)
    coord.set_recommendation_ack(True, kind="battery_off", device_id=devices[1].id)
    coord.set_recommendation_ack(True, card="battery_off")
    coord.set_recommendation_ack(False, card="battery_off")
    card = _card(coord, "battery_off")
    assert card["card_acknowledged"] is False and card["active"] == 2


async def test_a_card_not_shown_cannot_be_ticked(hass: HomeAssistant):
    coord, _ = await _house(hass)
    for kind in ("no_such_card", "battery_confirm"):
        with pytest.raises(ValueError):
            coord.set_recommendation_ack(True, card=kind)


async def test_the_cards_tick_is_kept_in_the_answers_file(hass: HomeAssistant):
    coord, _ = await _house(hass)
    coord.set_recommendation_ack(True, card="battery_off")
    payload = coord._acks_payload()
    assert payload["cards"] == {"battery_off": True}
    # Read back, and a file written before whole cards with none reads clean.
    assert coord._acks_read(payload) == 0
    assert coord._acks()["cards"] == {"battery_off": True}
    assert coord._acks_read({"devices": {}, "lines": {}}) == 0
    assert coord._acks()["cards"] == {}
    assert coord._acks_read({"devices": {}, "lines": {}, "cards": {"x": "yes"}}) == 1


async def test_midnight_forgets_the_tick_of_a_card_no_longer_shown(hass: HomeAssistant):
    coord, _ = await _house(hass)
    coord.set_recommendation_ack(True, card="battery_off")
    coord._acks()["cards"]["gone_card"] = True
    coord.prune_recommendation_acks()
    assert coord._acks()["cards"] == {"battery_off": True}
