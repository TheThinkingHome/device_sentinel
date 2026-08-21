# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_config_screens.py, Version: 0.16.13 (2026-08-21)

"""What the configuration screens promise a person reading them.

Ruling #312, from the first outside review of this surface. Tim Plas
runs 332 devices across 112 integrations and found the pickers
unscannable: a list of three hundred names in whatever order the
coordinator built them is not a list anybody reads. A large fleet is
exactly who runs this tool, which is his argument and a good one.

Sorting is asserted at the source rather than trusted to the
selector's own flag, because the flag is a request to a frontend and
these tests run without one.
"""

from __future__ import annotations

import json
import pathlib

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.config_flow import _device_options
from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_IGNORED_INTEGRATIONS,
    CONF_LOW_THRESHOLD,
)

from .helpers import register_device, setup_entry


def _labels(options) -> list[str]:
    return [option["label"] for option in options]


async def test_the_device_picker_is_sorted_by_name(hass: HomeAssistant):
    """Row order is the coordinator's; the picker's order is the
    reader's."""
    rows = [
        {"device_id": "d1", "name": "Zigbee Plug"},
        {"device_id": "d2", "name": "Attic Sensor"},
        {"device_id": "d3", "name": "motion hall"},
        {"device_id": "d4", "name": "Basement Leak"},
    ]
    await setup_entry(hass)

    options = _device_options(
        rows, [], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options) == [
        "Attic Sensor",
        "Basement Leak",
        "motion hall",
        "Zigbee Plug",
    ]


async def test_the_sort_ignores_case(hass: HomeAssistant):
    """A lowercase name belongs among its neighbours, not after the
    alphabet."""
    rows = [
        {"device_id": "d1", "name": "alpha"},
        {"device_id": "d2", "name": "Beta"},
        {"device_id": "d3", "name": "gamma"},
    ]
    await setup_entry(hass)

    options = _device_options(
        rows, [], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options) == ["alpha", "Beta", "gamma"]


async def test_a_pick_added_back_is_sorted_in_with_the_rest(
    hass: HomeAssistant,
):
    """A held pick whose row has gone is offered back, and it takes
    its place in the order rather than being appended at the end."""
    device, _ = register_device(hass, "held", "Aardvark Sensor")
    await setup_entry(hass)
    rows = [
        {"device_id": "d1", "name": "Middle Device"},
        {"device_id": "d2", "name": "Zebra Device"},
    ]

    options = _device_options(
        rows, [device.id], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options)[0].startswith("Aardvark Sensor")
    assert len(options) == 3


async def test_the_menu_is_called_configuration(hass: HomeAssistant):
    """Tim expected Configuration behind the gear icon and got
    Tuning. Every other integration's gear leads to configuration,
    and half these screens are exclusion lists rather than tuning
    (ruling #312).
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        strings = json.loads(source.read_text())
        assert (
            strings["options"]["step"]["init"]["title"]
            == "Device Sentinel Configuration"
        )
        assert "Tuning" not in source.read_text()


async def test_a_section_saves_and_returns_to_the_menu(
    hass: HomeAssistant,
):
    """Ruling #313, the whole change in one test.

    A section used to end by creating the entry, which writes the
    options and ends the flow in one call, so the dialog closed and
    the person landed back in Home Assistant. Tim Plas, working
    through six screens on a fleet of 332 devices, called that
    annoying. Submitting now writes the section and shows the menu
    again.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 33,
            CONF_BATTERY_EXCLUDED_INTEGRATIONS: [],
            CONF_BATTERY_EXCLUDED_LABELS: [],
            CONF_BATTERY_EXCLUDED_DEVICES: [],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_LOW_THRESHOLD] == 33


async def test_two_sections_in_one_visit_both_stick(hass: HomeAssistant):
    """The point of returning to the menu.

    A person crossing three screens in one sitting keeps all three,
    and each is written at the moment it is submitted rather than
    held until some later confirmation.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 22,
            CONF_BATTERY_EXCLUDED_INTEGRATIONS: [],
            CONF_BATTERY_EXCLUDED_LABELS: [],
            CONF_BATTERY_EXCLUDED_DEVICES: [],
        },
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_LOW_THRESHOLD] == 22

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_IGNORED_INTEGRATIONS: ["ping"],
            CONF_EXCLUDED_INTEGRATIONS: [],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: [],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_IGNORED_INTEGRATIONS] == ["ping"]
    assert entry.options[CONF_LOW_THRESHOLD] == 22


async def test_the_menu_says_a_section_saves_on_submit(
    hass: HomeAssistant,
):
    """A person who submits and then closes the dialog has to be
    able to know their work was kept.

    Home Assistant labels the button Submit and gives us no say in
    it, so the menu's own description carries the promise instead.
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        described = json.loads(source.read_text())["options"]["step"]["init"][
            "description"
        ]
        assert "saves when you submit it" in described
        assert "keeps everything you have already submitted" in described
