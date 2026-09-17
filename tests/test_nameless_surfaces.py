# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_nameless_surfaces.py, Version: 0.21.12 (2026-09-17)

"""A nameless device is named by the ladder on every surface (#402).

Ruling #402 gave a device with no name one resolver, and said every
surface asks it. Four did not: the two maintainer reports, the
low-battery list and a settings picker each read the registry name
and fell back to the raw id. The second fleet's own classification
and telemetry reports, written by 0.21.8 on 15 September, show six
UniFi clients as 32-character ids.

The device here is shaped like those six: an empty registry name, a
manufacturer, no model, and a MAC, so the ladder names it by its
integration and its MAC.
"""

from __future__ import annotations

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import _device_options
from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_BATTERY_LOW,
    REPORT_DIR,
)
from tests.helpers import flat_schema, setup_coordinator, setup_entry

DOMAIN = "client_hub"
MAC = "68:b6:91:36:ab:13"
LADDER_NAME = f"{DOMAIN} {MAC}"


def _nameless(hass: HomeAssistant, entity: str | None = "sensor"):
    """Register a device the way the second fleet's six are held.

    The entry has no title because Home Assistant fills an empty
    device name from it, which would hide the case.
    """
    source = MockConfigEntry(domain=DOMAIN, title="")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(DOMAIN, "client1")},
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
        manufacturer="Microsoft Corporation",
        name="",
    )
    assert registry.async_get(device.id).name == ""
    if entity is not None:
        er.async_get(hass).async_get_or_create(
            entity, DOMAIN, "client1",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device


async def _report(hass: HomeAssistant, coord, name: str) -> str:
    """Write the reports and read one of the maintainer files."""
    await hass.async_add_executor_job(coord._write_reports, "manual")
    path = os.path.join(hass.config.path(REPORT_DIR), name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def test_the_telemetry_report_names_a_nameless_device(
    hass: HomeAssistant,
):
    device = _nameless(hass)
    coord = await setup_coordinator(hass)
    assert device.id in coord._watched

    text = await _report(hass, coord, "device_telemetry.md")

    assert device.id not in text
    assert LADDER_NAME in text


async def test_the_classification_report_names_a_nameless_device(
    hass: HomeAssistant,
):
    device = _nameless(hass)
    coord = await setup_coordinator(hass)
    assert device.id in coord._watched

    text = await _report(hass, coord, "classification.md")

    assert device.id not in text
    assert f"| {LADDER_NAME} |" in text


async def test_the_low_battery_list_names_a_nameless_device(
    hass: HomeAssistant,
):
    device = _nameless(hass)
    coord = await setup_coordinator(hass)
    assert device.id in coord._battery_entity
    coord.data[DATA_DEVICES][device.id][DEV_BATTERY_LOW] = True

    rows = coord.battery_low_list

    assert [row["device_id"] for row in rows] == [device.id]
    assert rows[0]["name"] == LADDER_NAME


async def test_a_nameless_pick_the_screen_no_longer_lists_is_named(
    hass: HomeAssistant,
):
    """Through the real settings screen.

    Its integration is excluded, so the device is not among the
    screen's rows and reaches the picker only as a held pick.
    """
    device = _nameless(hass)
    entry = await setup_entry(hass, {
        CONF_EXCLUDED_INTEGRATIONS: [DOMAIN],
        CONF_MUTED_DEVICES: [device.id],
    })
    assert device.id not in entry.runtime_data._watched

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    picker = flat_schema(result["data_schema"].schema)[CONF_MUTED_DEVICES]
    labels = {
        option["value"]: option["label"]
        for option in picker.config["options"]
    }

    assert labels[device.id] == f"{LADDER_NAME} (not currently listed)"


def test_the_picker_still_names_a_pick_without_a_resolver():
    """A caller that passes no resolver gets the registry's own name,
    as the screens did before, and never the raw id for a named
    device."""

    class _Device:
        name = "Motion Hall"
        name_by_user = None

    class _Registry:
        def async_get(self, device_id):
            return _Device() if device_id == "orphan" else None

    options = _device_options(
        [], ["orphan"], set(), lambda row: row["name"], _Registry()
    )

    assert options == [
        {"value": "orphan", "label": "Motion Hall (not currently listed)"}
    ]


def test_a_nameless_unifi_client_is_named_for_unifi():
    """UniFi registers every client it has not been told about with no
    name, so its label is what those clients read as."""
    from custom_components.device_sentinel.naming import integration_label

    assert integration_label("unifi") == "UniFi Network"
