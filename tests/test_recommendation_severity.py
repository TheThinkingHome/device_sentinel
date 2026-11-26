# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendation_severity.py, Version: 0.30.7 (2026-11-26)

"""The Recommendations tab ordered by severity, and counted by answers
needed (rules REC-01, REC-08).

Every card and written line has a place: an alarm that cannot reach the
person or cannot fire first, the inventory last. A grouped card's title
counts the answers still needed, one a model, while its brief line
still counts the devices waiting.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel import device_recommendations as recs
from custom_components.device_sentinel.device_recommendations import (
    NETWORK_RANK,
    SEVERITY_ORDER,
    SEVERITY_UNKNOWN,
    card_rank,
    line_rank,
)

from tests.helpers import register_device, setup_coordinator


def _kinds() -> list[str]:
    return [value for name, value in vars(recs).items() if name.startswith("KIND_") and isinstance(value, str)]


def test_every_card_kind_has_a_place():
    for kind in _kinds():
        assert card_rank(kind) < SEVERITY_UNKNOWN, kind


def test_the_order_is_as_ruled():
    order = [card_rank(k) for k in (
        recs.KIND_NODE_STATUS_OFF, recs.KIND_LAST_SEEN, recs.KIND_BATTERY_OFF, recs.KIND_HUB_LINK_OFF,
        recs.KIND_RESTART_CACHED, recs.KIND_RESTART_LIVE, recs.KIND_SHARED_ADDRESS, recs.KIND_BATTERY_CONFIRM,
        recs.KIND_OTHER_POWER, recs.KIND_FIRMWARE, recs.KIND_SLOW, recs.KIND_NAMES, recs.KIND_AREA,
        recs.KIND_SIGNAL_OFF, recs.KIND_VOLTAGE_OFF, recs.KIND_POWER, recs.KIND_TYPE, recs.KIND_MIXED_TYPES,
    )]
    assert order == sorted(order)
    assert line_rank("target:notify.gone") < card_rank(recs.KIND_NODE_STATUS_OFF)
    assert line_rank("no_target") < line_rank("muted:freeze") < card_rank(recs.KIND_LAST_SEEN)
    assert card_rank(recs.KIND_HUB_LINK_OFF) < line_rank("z2m_availability") < line_rank("wifi_network") < card_rank(recs.KIND_RESTART_CACHED)
    assert card_rank(recs.KIND_OTHER_POWER) < line_rank("links") < card_rank(recs.KIND_FIRMWARE) < NETWORK_RANK
    assert NETWORK_RANK < card_rank(recs.KIND_SLOW) < line_rank("offer:alexa_media") < line_rank("router:unifi") < card_rank(recs.KIND_NAMES)


def test_an_unknown_line_or_card_goes_last():
    assert card_rank("from_a_later_release") == SEVERITY_UNKNOWN
    assert line_rank("later:thing") == SEVERITY_UNKNOWN
    # A key that only starts like a whole key is not that key.
    assert line_rank("no_targets") == SEVERITY_UNKNOWN
    assert line_rank("linksx") == SEVERITY_UNKNOWN
    assert len(set(SEVERITY_ORDER)) == len(SEVERITY_ORDER)


async def test_cards_come_most_severe_first_and_count_answers(hass: HomeAssistant):
    bulbs = [register_device(hass, f"b{n}", name=f"Bulb {n}")[0] for n in range(3)]
    for device in bulbs:
        dr.async_get(hass).async_update_device(device.id, manufacturer="IKEA", model="TRADFRI E27")
    register_device(hass, "lone", name="Lone")
    door, (entity_id,) = register_device(hass, "door", name="Door")
    er.async_get(hass).async_update_entity(
        entity_id, original_device_class="battery", disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    coord = await setup_coordinator(hass)
    cards = coord.device_recommendations()
    kinds = [card["kind"] for card in cards]
    assert kinds.index("battery_off") < kinds.index("area") < kinds.index("power") < kinds.index("type")
    assert [card["rank"] for card in cards] == sorted(card["rank"] for card in cards)
    power = next(card for card in cards if card["kind"] == "power")
    # Three bulbs of one model and two devices with none: three answers.
    assert power["active"] == 3
    assert power["brief"].startswith("5 devices have no battery")
    # One bulb acknowledged: its model still waits for the other two.
    coord.set_recommendation_ack(True, kind="power", device_id=bulbs[0].id)
    power = next(card for card in coord.device_recommendations() if card["kind"] == "power")
    assert power["active"] == 3
    for device in bulbs[1:]:
        coord.set_recommendation_ack(True, kind="power", device_id=device.id)
    power = next(card for card in coord.device_recommendations() if card["kind"] == "power")
    assert power["active"] == 2 and power["brief"].startswith("2 devices have no battery")


async def test_the_emailed_brief_orders_lines_and_cards_together(hass: HomeAssistant):
    door, (entity_id,) = register_device(hass, "door", name="Door")
    er.async_get(hass).async_update_entity(
        entity_id, original_device_class="battery", disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    coord = await setup_coordinator(hass)
    lines = coord.recommendation_lines()
    assert [line["rank"] for line in lines] == sorted(line["rank"] for line in lines)
    section = coord._recommendations_section()
    text = [line for line in section if line and not line.startswith("##")]
    first = next(i for i, line in enumerate(text) if line.startswith("Notifications Recipient Not Set"))
    battery = next(i for i, line in enumerate(text) if line.startswith("Battery Sensor Switched Off"))
    power = next(i for i, line in enumerate(text) if line.startswith("Power Not Set"))
    assert first < battery < power
