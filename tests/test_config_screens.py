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
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_EXCLUDED_INTEGRATIONS,
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
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: [],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
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
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: [],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
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
            "exclude": {
                CONF_EXCLUDED_INTEGRATIONS: ["ping"],
            },
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["ping"]
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


async def test_the_excludes_live_in_a_section_and_store_flat(
    hass: HomeAssistant,
):
    """Ruling #314. The section draws the screen; the keys stay flat.

    Tim Plas asked for the heading and its explanation to sit above
    the pickers rather than below them, and a Home Assistant section
    renders its name, then its description, then its fields. So each
    screen keeps its plain settings loose at the top and moves its
    exclude ladder into a section, the pattern Advanced already used
    for Data Trim.

    What must not change is storage. Every reader of these options,
    and every entry already written to disk, knows them by their flat
    names, so a save unwraps the section before storing.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )

    top = result["data_schema"].schema
    assert any(str(key) == "battery_muting" for key in top)
    assert not any("excluded" in str(key) for key in top)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 25,
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: ["mqtt"],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == ["mqtt"]
    assert "battery_muting" not in entry.options


async def test_every_sectioned_screen_keeps_its_settings_loose(
    hass: HomeAssistant,
):
    """One section per screen, holding only the excludes.

    The pattern is Advanced's: what a person came for stays at the
    top, and the one group that is different in kind sits below it
    under its own heading. A screen that swept its settings into the
    section too would bury them.
    """
    entry = await setup_entry(hass)
    expected = {
        "battery": ("battery_muting", 2),
        "signal": ("signal_muting", 4),
        "freeze": ("freeze_muting", 2),
        "exclusions": ("muting", 1),
    }
    for step, (section_key, loose_count) in expected.items():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        keys = [str(key) for key in result["data_schema"].schema]
        assert section_key in keys, step
        assert len(keys) == loose_count + 1, (step, keys)


async def test_each_section_carries_a_heading_and_an_explanation(
    hass: HomeAssistant,
):
    """The whole point of the change (ruling #314).

    A section with no name and no description would move the fields
    without moving the words, which is the complaint rather than the
    fix.
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
        steps = json.loads(source.read_text())["options"]["step"]
        for step, key in (
            ("battery", "battery_muting"),
            ("signal", "signal_muting"),
            ("freeze", "freeze_muting"),
            ("exclusions", "muting"),
        ):
            block = steps[step]["sections"][key]
            assert block["name"], (step, "name")
            assert len(block["description"]) > 40, (step, "description")
            assert len(block["data"]) == 3, (step, "fields")
            assert len(block["data_description"]) == 3, (step, "help")


async def test_the_ignore_list_has_its_own_section(hass: HomeAssistant):
    """Ruling #315. Both halves of Global Exclusions carry a heading.

    A loose field renders its label above the input and its help
    below it, which left the ignore list explained underneath its
    chooser while the exclude ladder beside it had its explanation
    above. Two sections and nothing loose departs from the Advanced
    pattern on purpose: this screen has no plain settings, only two
    groups of lists that need different explanations.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )

    assert [str(key) for key in result["data_schema"].schema] == [
        "exclude",
        "muting",
    ]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["ping"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["ping"]
    assert "ignore" not in entry.options


async def test_both_halves_carry_a_heading_and_an_explanation(
    hass: HomeAssistant,
):
    """The whole point of giving ignore a section of its own."""
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        step = json.loads(source.read_text())["options"]["step"]["exclusions"]
        assert not step["data"], "nothing loose on this screen"
        assert step["sections"]["exclude"]["name"] == "Integrations to Exclude"
        assert (
            step["sections"]["muting"]["name"] == "Global Muting"
        )
        for key in ("exclude", "muting"):
            assert len(step["sections"][key]["description"]) > 60, key
