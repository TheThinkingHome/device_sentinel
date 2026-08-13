# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_enable_assist.py, Version: 0.13.3 (2026-08-13)

"""The enable-assist buttons that turn on the diagnostics we learn from.

Some integrations ship signal, last-seen, and battery entities disabled
by default. The assist buttons enable those, so the integration can
learn from them, while leaving anything a person disabled themselves
alone. This test proves that split: integration-disabled entities are
enabled whoever disabled them (ruling #257), and unrelated entities are
untouched.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.helpers import setup_coordinator


async def test_enable_assist(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "ea")},
        name="EA",
    )
    ent_reg = er.async_get(hass)
    int_disabled = ent_reg.async_get_or_create(
        "sensor", "test", "ea_ls",
        suggested_object_id="ea_last_seen",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    user_disabled = ent_reg.async_get_or_create(
        "sensor", "test", "ea_lq",
        suggested_object_id="ea_linkquality",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    plain = ent_reg.async_get_or_create(
        "sensor", "test", "ea_temp",
        suggested_object_id="ea_temperature",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    coord = await setup_coordinator(hass)

    # Signals: the linkquality entity was disabled by hand, and the
    # button enables it anyway, counting how many it reversed.
    result = await coord.async_enable_signal_entities()
    assert result == {"enabled": 1, "by_hand": 1}
    assert ent_reg.async_get(user_disabled.entity_id).disabled_by is None

    # Last seen: the integration-disabled last_seen entity is enabled.
    result = await coord.async_enable_last_seen_entities()
    assert result == {"enabled": 1, "by_hand": 0}
    assert ent_reg.async_get(int_disabled.entity_id).disabled_by is None

    # The plain temperature sensor is neither, so it stays disabled
    # through both presses.
    assert ent_reg.async_get(plain.entity_id).disabled_by is not None

    # The three buttons exist and press without error.
    for entity_id in (
        "button.device_sentinel_enable_signals",
        "button.device_sentinel_enable_last_seen",
        "button.device_sentinel_enable_battery",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
        await hass.services.async_call(
            "button", "press",
            {"entity_id": entity_id},
            blocking=True,
        )


async def test_the_press_names_what_it_enabled(hass: HomeAssistant, caplog):
    """A count on Status is always answerable (ruling #237 keeps the
    attribute a bare number): the press logs the entity ids it
    enabled, and a press that enabled nothing names nothing."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "ea2")},
        name="EA2",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "ea2_ls",
        suggested_object_id="ea2_last_seen",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    coord = await setup_coordinator(hass)

    await coord.async_enable_last_seen_entities()
    assert (
        "Enable last_seen turned on: sensor.ea2_last_seen" in caplog.text
    )

    caplog.clear()
    await coord.async_enable_last_seen_entities()
    assert "turned on:" not in caplog.text
