# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_firmware_updates.py, Version: 0.29.2 (2026-11-15)

"""Devices behind on firmware, and the update check switched off
(rule REC-12).

A device's own update entity decides. With none, a device that gives a
hardware version is compared with its maker, model and hardware
version. With neither, a mix of versions says nothing, because one
model name can hold different hardware on its own current firmware.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.firmware_updates import (
    comparable_version,
    plural_type,
    version_number,
)

from tests.helpers import setup_entry

OFF = er.RegistryEntryDisabler.INTEGRATION


def _source(hass, domain):
    found = hass.config_entries.async_entries(domain)
    if found:
        return found[0]
    source = MockConfigEntry(domain=domain, title=domain.title())
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    return source


def _device(
    hass, uid, *, domain="test", maker="Acme", model="Socket", hw=None, sw=None,
    update=None, update_off=False, identifier=None,
):
    """A device with a sensor, and if asked an update entity of its own:
    update is (state, installed, latest)."""
    source = _source(hass, domain)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={identifier or (domain, uid)},
        name=uid.replace("_", " ").title(),
        manufacturer=maker,
        model=model,
        hw_version=hw,
        sw_version=sw,
    )
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor", domain, f"{uid}_sensor", device_id=device.id, config_entry=source
    ).entity_id
    hass.states.async_set(sensor, "21")
    if update is not None or update_off:
        entry = registry.async_get_or_create(
            "update", domain, f"{uid}_firmware", device_id=device.id, config_entry=source,
            disabled_by=OFF if update_off else None,
        )
        if update is not None and not update_off:
            state, installed, latest = update
            hass.states.async_set(
                entry.entity_id, state,
                {"installed_version": installed, "latest_version": latest, "device_class": "firmware"},
            )
    return device


async def _coord(hass):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    return coord


def _card(coord, kind="firmware"):
    return next((c for c in coord.device_recommendations() if c["kind"] == kind), None)


# --------------------------------------------- 1. the update entity decides


async def test_the_update_entity_decides_and_one_row_names_the_model(hass: HomeAssistant):
    behind = [_device(hass, f"socket_{i}", update=("on", "6.06.0", "6.10.0")) for i in range(2)]
    _device(hass, "socket_new", update=("off", "6.10.0", "6.10.0"))
    _device(hass, "socket_quiet", update=("off", None, None))
    coord = await _coord(hass)
    card = _card(coord)
    assert card is not None and card["title"] == "Firmware Updates"
    [row] = card["devices"]
    assert row["name"] == "Acme Socket"
    assert {d["device_id"] for d in row["behind"]} == {d.id for d in behind}
    assert row["text"] == (
        "2 of your Acme Socket devices require a firmware update. 1 is on the new firmware: "
        "6.10.0. 2 are on an old firmware: 6.06.0. 1 is not reported."
    )
    assert row["zigbee2mqtt"] is False


async def test_a_device_up_to_date_by_its_entity_is_never_behind_its_neighbours(hass: HomeAssistant):
    """With an update entity, rule 2 never applies: a different version
    on the same hardware is the entity's to judge."""
    _device(hass, "a", hw="gen3", sw="2.1.1", update=("off", "2.1.1", "2.1.1"))
    _device(hass, "b", hw="gen3", sw="2.2.1", update=("off", "2.2.1", "2.2.1"))
    coord = await _coord(hass)
    assert _card(coord) is None


# ------------------------------ 2. the same maker, model and hardware version


async def test_without_an_update_entity_the_same_hardware_is_compared(hass: HomeAssistant):
    """Six plugs on hardware gen3: one on 2.2.1, five on 2.1.1."""
    _device(hass, "plug_new", maker="Shelly", model="1PM Mini Gen3", hw="gen3", sw="2.2.1")
    for i in range(5):
        _device(hass, f"plug_{i}", maker="Shelly", model="1PM Mini Gen3", hw="gen3", sw="2.1.1")
    coord = await _coord(hass)
    [row] = _card(coord)["devices"]
    assert len(row["behind"]) == 5
    assert row["text"] == (
        "5 of your Shelly 1PM Mini Gen3 devices require a firmware update. 1 is on the new "
        "firmware: 2.2.1. 5 are on an old firmware: 2.1.1."
    )


async def test_only_version_numbers_are_compared(hass: HomeAssistant):
    """A device reporting its bridge's version, as Zigbee2MQTT fills in
    for one that gives none, is not a device behind."""
    _device(hass, "a", maker="Tuya", model="3-gang", hw="1", sw="1.1.0")
    _device(hass, "b", maker="Tuya", model="3-gang", hw="1", sw="Zigbee2MQTT 2.14.3")
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_one_version_written_two_ways_is_not_behind(hass: HomeAssistant):
    _device(hass, "a", hw="1", sw="1.0")
    _device(hass, "b", hw="1", sw="1.0.0")
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_different_hardware_is_never_compared(hass: HomeAssistant):
    _device(hass, "a", hw="1", sw="1.0.0")
    _device(hass, "b", hw="2", sw="3.0.0")
    coord = await _coord(hass)
    assert _card(coord) is None


# ------------------------------------------------------------ 3. neither


async def test_a_mix_with_no_hardware_version_and_no_entity_says_nothing(hass: HomeAssistant):
    """One model name can hold different internal hardware, each on its
    own current firmware, as Lightwave's sockets do."""
    for i in range(3):
        _device(hass, f"old_{i}", maker="LightwaveRF", model="L42MK3", sw="6.06.0")
    _device(hass, "new", maker="LightwaveRF", model="L42MK3", sw="6.10.0")
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_a_model_that_stands_for_none_is_never_compared(hass: HomeAssistant):
    _device(hass, "a", maker="Espressif", model="esp32dev", hw="1", sw="1.0.0")
    _device(hass, "b", maker="Espressif", model="esp32dev", hw="1", sw="2.0.0")
    coord = await _coord(hass)
    assert _card(coord) is None


# ------------------------------------- a check switched off, and no model


async def test_a_check_switched_off_counts_as_none(hass: HomeAssistant):
    """An integration that ships its update check off doesn't push its
    updates, and Device Sentinel doesn't ask for it: the device is
    compared with its make, model and hardware version, against a device
    whose own check shows the version it is on."""
    off = _device(hass, "a", hw="1", sw="1.0.0", update_off=True)
    _device(hass, "b", hw="1", sw="2.0.0", update=("off", "2.0.0", "2.0.0"))
    coord = await _coord(hass)
    [row] = _card(coord)["devices"]
    assert [d["device_id"] for d in row["behind"]] == [off.id]
    assert row["text"] == (
        "1 of your Acme Socket devices requires a firmware update. 1 is on the new firmware: "
        "2.0.0. 1 is on an old firmware: 1.0.0."
    )
    assert not [c for c in coord.device_recommendations() if c["kind"] == "firmware_off"]


async def test_a_device_with_no_model_and_an_update_has_its_own_row(hass: HomeAssistant):
    proxy = _device(hass, "bluetooth_proxy", domain="esphome", maker="Espressif", model="esp32-poe-iso",
                    update=("on", "2026.10.1", "2026.11.0"))
    _device(hass, "kitchen_board", domain="esphome", maker="Espressif", model="esp32-poe-iso",
            update=("off", "2026.11.0", "2026.11.0"))
    coord = await _coord(hass)
    [row] = _card(coord)["devices"]
    assert row["name"] == "Bluetooth Proxy" and row["device_id"] == proxy.id
    assert row["text"] == (
        "Bluetooth Proxy requires a firmware update. It is on 2026.10.1. The new firmware is 2026.11.0."
    )


async def test_a_device_with_no_model_and_no_check_is_never_listed(hass: HomeAssistant):
    """With no model there is nothing to compare, so only its own check,
    switched on, can say it is behind."""
    _device(hass, "a", domain="esphome", maker="Espressif", model="esp32", hw="1", sw="2026.10.1", update_off=True)
    _device(hass, "b", domain="esphome", maker="Espressif", model="esp32", hw="1", sw="2026.11.0")
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_a_single_number_is_read_as_text(hass: HomeAssistant):
    """A build number or a date is never compared."""
    _device(hass, "a", hw="1", sw="1.2.0")
    _device(hass, "b", hw="1", sw="20230512")
    _device(hass, "c", model="Lamp", hw="1", sw="47")
    _device(hass, "d", model="Lamp", hw="1", sw="52")
    coord = await _coord(hass)
    assert _card(coord) is None


async def test_a_first_generation_shelly_is_read_by_its_version(hass: HomeAssistant):
    """Its firmware reads "20230913-111730/v1.14.0-gcb84623": the build's
    date and time, then its version."""
    old = _device(hass, "ht_old", maker="Shelly", model="Shelly H&T", hw="gen1",
                  sw="20221027-091427/v1.12.1-ga9117d3", update_off=True)
    _device(hass, "ht_new", maker="Shelly", model="Shelly H&T", hw="gen1",
            sw="20230913-111730/v1.14.0-gcb84623", update_off=True)
    coord = await _coord(hass)
    [row] = _card(coord)["devices"]
    assert [d["device_id"] for d in row["behind"]] == [old.id]
    assert "1 is on the new firmware: 20230913-111730/v1.14.0-gcb84623." in row["text"]


async def test_any_check_offering_an_update_makes_the_device_behind(hass: HomeAssistant):
    """A coordinator with two update entities, its own firmware and its
    radio's: the second one offering an update is enough."""
    source = _source(hass, "smlight")
    device = _device(hass, "slzb", domain="smlight", maker="SMLIGHT", model="SLZB-06M",
                     update=("off", "v2.9.6", "v2.9.6"))
    entry = er.async_get(hass).async_get_or_create(
        "update", "smlight", "slzb_zigbee_firmware", device_id=device.id, config_entry=source,
    )
    hass.states.async_set(entry.entity_id, "on", {"installed_version": "20240314", "latest_version": "20250120"})
    coord = await _coord(hass)
    [row] = _card(coord)["devices"]
    assert [d["device_id"] for d in row["behind"]] == [device.id]
    assert "The new firmware is 20250120." in row["text"]


# ----------------------------------------------- Simple, brief and ticks


async def test_the_card_is_in_simple_and_the_brief_and_is_ticked_per_model(hass: HomeAssistant):
    for i in range(2):
        _device(hass, f"s_{i}", update=("on", "1.0", "2.0"))
    _device(hass, "lamp", model="Lamp", update=("on", "3.0", "4.0"))
    coord = await _coord(hass)
    card = _card(coord)
    assert card["simple"] is True and card["active"] == 2
    assert card["brief"] == (
        "2 models have devices that need a firmware update. See them on the Recommendations tab."
    )
    first = card["devices"][0]["device_id"]
    coord.set_recommendation_ack(True, kind="firmware", device_id=first)
    card = _card(coord)
    assert card["active"] == 1
    assert card["brief"].startswith("1 model has devices")


async def test_a_zigbee2mqtt_row_says_so(hass: HomeAssistant):
    _device(
        hass, "door", domain="mqtt", maker="Third Reality", model="3RDS17BZ",
        identifier=("mqtt", "zigbee2mqtt_0x282c02bfffeafa5b"), update=("on", "47", "52"),
    )
    coord = await _coord(hass)
    card = _card(coord)
    [row] = card["devices"]
    assert row["zigbee2mqtt"] is True
    assert row["text"].startswith("1 of your Third Reality 3RDS17BZ devices requires a firmware update.")
    assert "The new firmware is 52." in row["text"]


async def test_the_type_names_the_devices(hass: HomeAssistant):
    for i in range(2):
        _device(hass, f"p_{i}", model="Plug", update=("on", "1.0", "2.0"))
    coord = await _coord(hass)
    first = _card(coord)["devices"][0]["device_id"]
    coord.page_set_type(first, "Plug", whole_model=True)
    [row] = _card(coord)["devices"]
    assert row["text"].startswith("2 of your Acme Plug plugs require a firmware update.")


# ------------------------------------------------------------- the words


def test_version_numbers_and_type_plurals():
    assert version_number("6.10.0") > version_number("6.06.0")
    assert version_number("v2.1") == (2, 1)
    assert version_number("47") == (47,)
    # One version written two ways is not one behind the other.
    assert version_number("1.0") == version_number("1.0.0") == (1,)
    assert version_number("0") == (0,)
    assert version_number("Zigbee2MQTT 2.14.3") is None
    assert comparable_version("47") is None and comparable_version("20230512") is None
    assert comparable_version("6.10.0") == (6, 10)
    assert comparable_version("20230913-111730/v1.14.0-gcb84623") == (1, 14)
    assert comparable_version("20200827-070450/v1.8.3@4a8bc427") == (1, 8, 3)
    # The @ is read only in Shelly's own pattern.
    assert comparable_version("1.8.3@4a8bc427") is None
    assert comparable_version("Zigbee2MQTT 2.14.3") is None
    assert version_number(None) is None
    assert plural_type("Plug") == "plugs"
    assert plural_type("Switch") == "switches"
    assert plural_type("Door/Window Sensor") == "door/window sensors"
    assert plural_type("Zigbee Router") == "Zigbee routers"
    assert plural_type("Bluetooth Proxy") == "Bluetooth proxies"
    assert plural_type("UPS") == "devices"
    assert plural_type("Zigbee Coordinator (Zigbee2MQTT)") == "devices"
    assert plural_type(None) == "devices"
