# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_voltage_card.py, Version: 0.27.10 (2026-10-27)

"""The Battery Voltage Switched Off card (rules REC-05, REC-09, REC-10).

Each night keeps a battery device's voltage (rule BAT-16), but
Zigbee2MQTT ships its voltage sensor switched off, and turning on the
battery sensor turns on the percentage only. So the card is built as
the other switched-off cards are, counted in the emailed Brief, shown
in Simple too, and lists only a device with a battery reading whose
voltage nothing else reports.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.helpers import register_device, setup_entry

INTEGRATION = er.RegistryEntryDisabler.INTEGRATION


def _device(hass: HomeAssistant, uid: str, name: str, *, battery=True, voltage_on=False,
            attrs=None):
    """A device with a voltage sensor and, if asked, a battery sensor."""
    device, entity_ids = register_device(hass, uid, name=name, entity_count=2)
    registry = er.async_get(hass)
    first, second = entity_ids
    if battery:
        registry.async_update_entity(first, original_device_class="battery", unit_of_measurement="%")
        hass.states.async_set(first, "88", {"unit_of_measurement": "%", "device_class": "battery", **(attrs or {})})
    registry.async_update_entity(
        second, original_device_class="voltage", unit_of_measurement="mV",
        disabled_by=None if voltage_on else INTEGRATION,
    )
    if voltage_on:
        hass.states.async_set(second, "2950", {"unit_of_measurement": "mV", "device_class": "voltage"})
    return device, second


def _card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "voltage_off"), None)


async def _coord(hass):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    return coord


async def test_a_battery_device_with_its_voltage_off_is_listed_in_simple_and_advanced(hass: HomeAssistant):
    """Listed, and counted in the emailed Brief (rule REC-10). Shown in
    Simple as well, because Simple's device page does not offer to turn a
    sensor on, so the card is where it is done (rule REC-09).
    """
    door, _ = _device(hass, "d1", "Door Hall")
    coord = await _coord(hass)
    card = _card(coord)
    assert card is not None and card["title"] == "Battery Voltage Switched Off"
    assert [row["device_id"] for row in card["devices"]] == [door.id]
    assert card["simple"] is True and card["active"] == 1
    assert "Battery Voltage Switched Off (1): " in "\n".join(coord._recommendations_section())
    # The card's body, word for word (rule REC-05).
    assert "This device has a battery voltage entity which can be used for more accurate battery reporting and forecasting." in card["body"]


async def test_the_diagnostics_download_counts_the_card(hass: HomeAssistant):
    """The download's switched-off counts include this card, with the
    devices it lists: a plug's line voltage sensor is not counted."""
    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

    _device(hass, "d1", "Door Hall")
    _device(hass, "p1", "Plug Desk", battery=False)
    coord = await _coord(hass)
    diag = await async_get_config_entry_diagnostics(hass, coord.entry)
    assert diag["switched_off"]["voltage"] == {"devices": 1, "by_user": 0}
    assert len(_card(coord)["devices"]) == 1


async def test_a_device_with_no_battery_reading_is_not_listed(hass: HomeAssistant):
    """A plug's line voltage sensor is not a battery's."""
    _device(hass, "p1", "Plug Desk", battery=False)
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_a_wired_device_is_not_listed(hass: HomeAssistant):
    """A device on mains with a backup battery reading: its voltage
    sensor reads the supply, not a battery.
    """
    siren, _ = _device(hass, "s1", "Siren Hall")
    coord = await _coord(hass)
    coord.page_set_power(siren.id, "Mains Powered")
    assert _card(coord) is None


async def test_a_voltage_already_on_is_not_listed(hass: HomeAssistant):
    _device(hass, "d2", "Door Hall", voltage_on=True)
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_a_voltage_given_on_the_battery_sensor_is_not_listed(hass: HomeAssistant):
    """ZHA gives the voltage on the battery sensor; nothing to turn on."""
    _device(hass, "z1", "Door Hall", attrs={"battery_voltage": 2.9})
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_its_row_turns_on_the_voltage_sensor_only(hass: HomeAssistant):
    door, voltage = _device(hass, "d3", "Door Hall")
    coord = await _coord(hass)
    assert coord.page_turn_on(door.id, "voltage") == 1
    registry = er.async_get(hass)
    assert registry.async_get(voltage).disabled_by is None
    coord._rebuild_registry_view()
    assert _card(coord) is None


async def test_a_tick_leaves_the_brief(hass: HomeAssistant):
    """Ticked as the other switched-off cards are (rule REC-07)."""
    door, _ = _device(hass, "d4", "Door Hall")
    coord = await _coord(hass)
    coord.set_recommendation_ack(True, kind="voltage_off", device_id=door.id)
    assert _card(coord)["active"] == 0
    assert "Battery Voltage Switched Off" not in "\n".join(coord._recommendations_section())
